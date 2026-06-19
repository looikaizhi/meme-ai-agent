"""Scanner: fetches, filters, converts, and deduplicates Solana meme-coin pairs."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from memedog.clients.base import DataSourceError
from memedog.config.settings import ScannerConfig
from memedog.models import TokenCandidate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fix 5 — type-annotate client via Protocol
# ---------------------------------------------------------------------------


class PairFetcher(Protocol):
    """Structural type for any object that can fetch trading pairs."""

    async def fetch_solana_pairs(self) -> list[dict]: ...


class Scanner:
    """Orchestrates periodic scanning for new Solana meme-coin candidates.

    Parameters
    ----------
    client:
        Any object with ``async fetch_solana_pairs() -> list[dict]``.
    cfg:
        A :class:`~memedog.config.settings.ScannerConfig` instance.
    """

    def __init__(self, client: PairFetcher, cfg: ScannerConfig) -> None:
        self._client = client
        self._cfg = cfg
        # mint -> unix timestamp (float) of first emission
        self._seen: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan(self) -> list[TokenCandidate]:
        """Fetch, prefilter, convert, and deduplicate Solana pairs.

        Returns
        -------
        list[TokenCandidate]
            New, non-deduplicated candidates that passed all filters.
            Returns ``[]`` on :class:`~memedog.clients.base.DataSourceError`.
        """
        try:
            raw_pairs = await self._client.fetch_solana_pairs()
        except DataSourceError as exc:
            logger.warning("DataSourceError in Scanner.scan: %s", exc)
            return []

        now_utc = datetime.now(timezone.utc)
        # Fix 6 — single clock source: derive now_ts from the same snapshot
        now_ts = now_utc.timestamp()

        candidates: list[TokenCandidate] = []

        # Expire old dedup entries before processing
        ttl_sec = self._cfg.dedup_ttl_min * 60
        self._seen = {
            mint: ts
            for mint, ts in self._seen.items()
            if now_ts - ts < ttl_sec
        }

        for pair in raw_pairs:
            # --- Prefilter ---
            if not self._passes_prefilter(pair, now_utc):
                continue

            # Fix 1 — wrap per-pair dedup key extraction + convert so a
            # malformed pair skips only itself, not the whole scan.
            try:
                mint = pair["baseToken"]["address"]
            except (KeyError, TypeError) as exc:
                logger.warning(
                    "Skipping pair %s — missing baseToken: %s",
                    pair.get("pairAddress"),
                    exc,
                )
                continue

            # --- Dedup ---
            if mint in self._seen:
                continue

            # --- Convert ---
            try:
                candidate = self._convert(pair)
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Failed to convert pair %s: %s", pair.get("pairAddress"), exc)
                continue

            # Record seen and collect
            self._seen[mint] = now_ts
            candidates.append(candidate)

        return candidates

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_created_at(pair: dict) -> datetime:
        """Fix 7 — single helper to parse pairCreatedAt ms-epoch → aware datetime."""
        return datetime.fromtimestamp(pair["pairCreatedAt"] / 1000, tz=timezone.utc)

    def _passes_prefilter(self, pair: dict, now_utc: datetime) -> bool:
        """Return True if *pair* satisfies all configured prefilter thresholds."""
        try:
            # Fix 7 — reuse _parse_created_at instead of duplicating the parse
            created_at = self._parse_created_at(pair)
            liquidity_usd: float = float(pair["liquidity"]["usd"])
            volume_m5: float = float(pair["volume"]["m5"])
        except (KeyError, TypeError, ValueError) as exc:
            # Fix 4 — log a warning so API schema breakage is observable
            logger.warning(
                "Skipping pair %s in prefilter — schema mismatch: %s",
                pair.get("pairAddress"),
                exc,
            )
            return False

        # Age check
        age_min = (now_utc - created_at).total_seconds() / 60.0

        if age_min < self._cfg.min_pair_age_min:
            return False
        if age_min > self._cfg.max_pair_age_min:
            return False

        # Liquidity check
        if liquidity_usd < self._cfg.prefilter_min_liquidity_usd:
            return False

        # Volume check
        if volume_m5 < self._cfg.prefilter_min_volume_5m:
            return False

        return True

    def _convert(self, pair: dict) -> TokenCandidate:
        """Convert a raw DexScreener pair dict to a :class:`TokenCandidate`."""
        # Fix 7 — reuse _parse_created_at
        created_at = self._parse_created_at(pair)
        return TokenCandidate(
            mint=pair["baseToken"]["address"],
            pair_address=pair["pairAddress"],
            symbol=pair["baseToken"]["symbol"],
            # Fix 3 — honour configurable chain instead of hardcoding "solana"
            chain=self._cfg.chain,
            pair_created_at=created_at,
            price_usd=float(pair["priceUsd"]),
            liquidity_usd=float(pair["liquidity"]["usd"]),
            fdv_usd=float(pair["fdv"]),
            volume_5m=float(pair["volume"]["m5"]),
            volume_1h=float(pair["volume"]["h1"]),
            txns_5m_buys=int(pair["txns"]["m5"]["buys"]),
            txns_5m_sells=int(pair["txns"]["m5"]["sells"]),
            price_change_5m=float(pair["priceChange"]["m5"]),
            trace_id=uuid4().hex,
        )
