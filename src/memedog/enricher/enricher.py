"""Enricher: parallel orchestration of the 4 dimension providers.

Each provider runs concurrently under asyncio.gather with an individual timeout.
If a provider times out or raises, its dimension is substituted with
*Info(available=False). enrich() NEVER raises to the caller.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from memedog.config.settings import EnricherConfig
from memedog.models import (
    TokenCandidate,
    TokenSnapshot,
    SafetyInfo,
    HolderInfo,
    MomentumInfo,
    SocialInfo,
    WalletInfo,
)
from memedog.enricher.providers import (
    fetch_safety,
    fetch_holders,
    fetch_momentum,
    fetch_social,
)

logger = logging.getLogger(__name__)


def _load_smart_wallets(filepath: str) -> dict[str, WalletInfo]:
    """Load smart wallets as address -> WalletInfo.

    Line format: ``address[,label[,tier]]``. Lines starting with ``#`` and
    blank lines are skipped. Missing/unreadable file -> empty dict (tolerant).
    """
    path = Path(filepath)
    if not path.exists():
        logger.debug("smart_wallets file not found: %s — using empty dict", filepath)
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Could not read smart_wallets file %s: %s", filepath, exc)
        return {}

    library: dict[str, WalletInfo] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        address = parts[0]
        if not address:
            continue
        label = parts[1] if len(parts) > 1 and parts[1] else None
        tier = parts[2] if len(parts) > 2 and parts[2] else None
        library[address] = WalletInfo(address=address, label=label, tier=tier)
    logger.debug("Loaded %d smart wallets from %s", len(library), filepath)
    return library


class Enricher:
    """Orchestrates parallel enrichment of a TokenCandidate into a TokenSnapshot.

    Parameters
    ----------
    rugcheck_client:
        RugCheckClient instance used for the safety dimension.
    helius_client:
        HeliusClient instance used for holders and smart-money sub-sources.
    twitter_client:
        TwitterClient instance used for the social twitter sub-source.
    cfg:
        EnricherConfig with per_provider_timeout_sec, smart_money_wallets_file,
        and twitter_lookback_min.
    """

    def __init__(
        self,
        rugcheck_client,
        helius_client,
        twitter_client,
        cfg: EnricherConfig,
    ) -> None:
        self._rugcheck_client = rugcheck_client
        self._helius_client = helius_client
        self._twitter_client = twitter_client
        self._cfg = cfg

    async def enrich(
        self,
        candidate: TokenCandidate,
        rugcheck_report: Optional[dict] = None,
    ) -> TokenSnapshot:
        """Enrich *candidate* by running all 4 dimension providers in parallel.

        Each provider is wrapped with asyncio.wait_for using the configured
        per_provider_timeout_sec. Timeouts and exceptions are caught per-provider
        and substitute the corresponding *Info(available=False).

        Parameters
        ----------
        candidate:
            The token to enrich.
        rugcheck_report:
            Optional pre-parsed RugCheck report dict. When supplied, the safety
            provider uses it directly without a network call.

        Returns
        -------
        TokenSnapshot — always; never raises.
        """
        timeout = self._cfg.per_provider_timeout_sec
        smart_wallets = _load_smart_wallets(self._cfg.smart_money_wallets_file)

        # Build coroutines for each dimension provider
        safety_coro = fetch_safety(
            mint=candidate.mint,
            rugcheck_report=rugcheck_report,
            rugcheck_client=self._rugcheck_client,
        )
        holders_coro = fetch_holders(
            mint=candidate.mint,
            helius_client=self._helius_client,
        )
        momentum_coro = fetch_momentum(candidate)
        social_coro = fetch_social(
            symbol=candidate.symbol,
            mint=candidate.mint,
            helius_client=self._helius_client,
            twitter_client=self._twitter_client,
            smart_wallets=smart_wallets,
            lookback_min=self._cfg.twitter_lookback_min,
        )

        # Run all providers concurrently; collect results/exceptions
        results = await asyncio.gather(
            asyncio.wait_for(safety_coro, timeout=timeout),
            asyncio.wait_for(holders_coro, timeout=timeout),
            asyncio.wait_for(momentum_coro, timeout=timeout),
            asyncio.wait_for(social_coro, timeout=timeout),
            return_exceptions=True,
        )

        safety, holders, momentum, social = results

        # Substitute unavailable info for any provider that timed out or raised
        if isinstance(safety, BaseException):
            logger.warning("safety provider failed: %s", safety)
            safety = SafetyInfo(available=False)

        if isinstance(holders, BaseException):
            logger.warning("holders provider failed: %s", holders)
            holders = HolderInfo(available=False)

        if isinstance(momentum, BaseException):
            logger.warning("momentum provider failed: %s", momentum)
            momentum = MomentumInfo(available=False)

        if isinstance(social, BaseException):
            logger.warning("social provider failed: %s", social)
            social = SocialInfo(available=False)

        return TokenSnapshot(
            candidate=candidate,
            safety=safety,
            holders=holders,
            momentum=momentum,
            social=social,
            enriched_at=datetime.now(timezone.utc),
        )
