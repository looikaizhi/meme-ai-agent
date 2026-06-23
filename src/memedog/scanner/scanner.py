"""Scanner: discovers latest tokens, selects representative pairs, filters, and deduplicates."""
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
# Protocol — structural type for the injected discovery client
# ---------------------------------------------------------------------------


class TokenDiscoverer(Protocol):
    """Structural type for any object that can discover tokens and their pairs."""

    async def fetch_latest_token_addresses(self, chain: str) -> list[str]: ...

    async def get_token_pairs(self, mint: str) -> list[dict]: ...


class Scanner:
    """Orchestrates periodic scanning for new Solana meme-coin candidates.

    Discovery flow:
    1. ``fetch_latest_token_addresses(chain)`` → list of recently-listed mints.
    2. For each mint (skipping already-seen ones): ``get_token_pairs(mint)`` → raw pairs.
    3. Filter pairs to the configured chain; pick the one with highest liquidity.
    4. Apply the age / liquidity / volume prefilter.
    5. Convert to :class:`TokenCandidate` and record in the dedup cache.

    Parameters
    ----------
    client:
        Any object satisfying the :class:`TokenDiscoverer` protocol.
    cfg:
        A :class:`~memedog.config.settings.ScannerConfig` instance.
    """

    def __init__(self, client: TokenDiscoverer, cfg: ScannerConfig) -> None:
        self._client = client
        self._cfg = cfg
        # mint -> unix timestamp (float) of first emission
        self._seen: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan(self) -> list[TokenCandidate]:
        """Discover, prefilter, convert, and deduplicate Solana pairs.

        Returns
        -------
        list[TokenCandidate]
            New candidates that passed all filters and were not in the
            dedup cache.  Returns ``[]`` on
            :class:`~memedog.clients.base.DataSourceError` from the
            address-discovery step.
        """
        # Step 1: discover latest token addresses
        try:
            addresses = await self._client.fetch_latest_token_addresses(self._cfg.chain)
        except DataSourceError as exc:
            logger.warning("DataSourceError fetching token addresses: %s", exc)
            return []

        now_utc = datetime.now(timezone.utc)
        now_ts = now_utc.timestamp()

        # Expire old dedup entries
        ttl_sec = self._cfg.dedup_ttl_min * 60
        self._seen = {
            mint: ts
            for mint, ts in self._seen.items()
            if now_ts - ts < ttl_sec
        }

        candidates: list[TokenCandidate] = []

        for mint in addresses:
            # Skip already-seen mints without making an extra API call
            if mint in self._seen:
                continue

            # Step 2: fetch pairs for this token
            try:
                raw_pairs = await self._client.get_token_pairs(mint)
            except DataSourceError as exc:
                logger.warning(
                    "DataSourceError fetching pairs for mint=%s, skipping: %s",
                    mint,
                    exc,
                )
                continue

            # Step 3: select the representative pair (best-liquidity on-chain pair)
            representative = self._select_representative_pair(mint, raw_pairs)
            if representative is None:
                continue

            # Step 4: prefilter
            if not self._passes_prefilter(representative, now_utc):
                continue

            # Step 5: convert
            try:
                candidate = self._convert(representative)
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "Failed to convert pair %s for mint=%s: %s",
                    representative.get("pairAddress"),
                    mint,
                    exc,
                )
                continue

            # Record seen and collect
            self._seen[mint] = now_ts
            candidates.append(candidate)

        return candidates

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_representative_pair(
        self, mint: str, raw_pairs: list[dict]
    ) -> dict | None:
        """From *raw_pairs*, pick the one on the configured chain with the highest liquidity.

        Parameters
        ----------
        mint:
            Token mint address (used only for log messages).
        raw_pairs:
            All pairs returned by ``get_token_pairs``.

        Returns
        -------
        dict or None
            The representative pair dict, or ``None`` if no on-chain pair
            was found or the data is malformed.
        """
        chain_pairs: list[dict] = []
        for pair in raw_pairs:
            if not isinstance(pair, dict):
                continue
            if pair.get("chainId") != self._cfg.chain:
                continue
            chain_pairs.append(pair)

        if not chain_pairs:
            logger.debug(
                "No pairs on chain=%s for mint=%s (total pairs: %d)",
                self._cfg.chain,
                mint,
                len(raw_pairs),
            )
            return None

        # Pick the pair with the highest liquidity USD
        def _liquidity(pair: dict) -> float:
            try:
                return float(pair["liquidity"]["usd"])
            except (KeyError, TypeError, ValueError):
                return 0.0

        return max(chain_pairs, key=_liquidity)

    @staticmethod
    def _parse_created_at(pair: dict) -> datetime:
        """Parse pairCreatedAt ms-epoch → timezone-aware datetime."""
        return datetime.fromtimestamp(pair["pairCreatedAt"] / 1000, tz=timezone.utc)

    def _passes_prefilter(self, pair: dict, now_utc: datetime) -> bool:
        """Return True if *pair* satisfies all configured prefilter thresholds."""
        try:
            created_at = self._parse_created_at(pair)
            liquidity_usd: float = float(pair["liquidity"]["usd"])
            volume_m5: float = float(pair["volume"]["m5"])
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Skipping pair %s in prefilter — schema mismatch: %s",
                pair.get("pairAddress"),
                exc,
            )
            return False

        age_min = (now_utc - created_at).total_seconds() / 60.0

        if age_min < self._cfg.min_pair_age_min:
            return False
        if age_min > self._cfg.max_pair_age_min:
            return False
        if liquidity_usd < self._cfg.prefilter_min_liquidity_usd:
            return False
        if volume_m5 < self._cfg.prefilter_min_volume_5m:
            return False

        return True

    def _convert(self, pair: dict) -> TokenCandidate:
        """Convert a raw DexScreener pair dict to a :class:`TokenCandidate`."""
        created_at = self._parse_created_at(pair)
        info = pair.get("info") or {}
        platforms: list[str] = []
        for s in info.get("socials") or []:
            t = (s.get("type") or s.get("platform") or "").strip().lower()
            if t and t not in platforms:
                platforms.append(t)
        if (info.get("websites") or []) and "website" not in platforms:
            platforms.append("website")
        return TokenCandidate(
            mint=pair["baseToken"]["address"],
            pair_address=pair["pairAddress"],
            symbol=pair["baseToken"]["symbol"],
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
            social_platforms=platforms,
            trace_id=uuid4().hex,
        )
