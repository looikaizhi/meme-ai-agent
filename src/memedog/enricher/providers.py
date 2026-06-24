"""Enricher dimension providers.

Each provider function fetches one *Info dimension and is independently degradable:
  - On ANY exception (network, timeout, data error), returns *Info(available=False).
  - NEVER re-raises to the caller.

Parallel failure semantics for fetch_social:
  - smart money fails but social metadata ok → available=True (partial result)
  - Both fail                                → available=False
  - Both succeed                             → available=True (full result)
"""
from __future__ import annotations

import logging
from typing import Optional

from memedog.models import (
    TokenCandidate,
    SafetyInfo,
    HolderInfo,
    MomentumInfo,
    SocialInfo,
    NarrativeInfo,
)
from memedog.clients.rugcheck import parse_report
from memedog.enricher.narrative import classify_narrative

logger = logging.getLogger(__name__)

_EPSILON = 1e-9  # avoid division by zero in fdv_to_liquidity


# ---------------------------------------------------------------------------
# fetch_safety
# ---------------------------------------------------------------------------


async def fetch_safety(
    mint: str,
    rugcheck_report: Optional[dict],
    rugcheck_client=None,
) -> SafetyInfo:
    """Return SafetyInfo from a pre-fetched parsed report or by calling rugcheck_client.

    Parameters
    ----------
    mint:
        Token mint address (used only when fetching from client).
    rugcheck_report:
        A pre-parsed RugCheck report dict (from parse_report). When supplied,
        no network call is made.
    rugcheck_client:
        A RugCheckClient instance. Required only when rugcheck_report is None.

    Returns
    -------
    SafetyInfo with available=True on success, available=False on any error.
    """
    try:
        if rugcheck_report is not None:
            parsed = rugcheck_report
        elif rugcheck_client is not None:
            raw = await rugcheck_client.get_token_report(mint)
            parsed = parse_report(raw)
        else:
            logger.warning("fetch_safety: no report and no client for mint %s", mint)
            return SafetyInfo(available=False)

        return SafetyInfo(
            available=True,
            mint_authority_revoked=parsed.get("mint_authority_revoked"),
            freeze_authority_revoked=parsed.get("freeze_authority_revoked"),
            lp_burned_or_locked=parsed.get("lp_burned_or_locked"),
            rug_trust_score=parsed.get("trust_score"),
            rug_risk_level=parsed.get("risk_level"),
        )

    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_safety failed for mint %s: %s", mint, exc)
        return SafetyInfo(available=False)


# ---------------------------------------------------------------------------
# fetch_holders
# ---------------------------------------------------------------------------


async def fetch_holders(mint: str, helius_client) -> HolderInfo:
    """Return HolderInfo by querying Helius for the largest token accounts.

    dev_wallet_pct and sniper_pct are not available via getTokenLargestAccounts
    and will be None. Those fields require a RugCheck report (see fetch_safety).

    Returns
    -------
    HolderInfo with available=True on success, available=False on any error.
    """
    try:
        data = await helius_client.get_largest_holders(mint)
        return HolderInfo(
            available=True,
            top10_pct=data.get("top10_pct"),
            max_wallet_pct=data.get("max_wallet_pct"),
            holder_count=data.get("holder_count"),
            # dev_wallet_pct and sniper_pct not available from this RPC call
            dev_wallet_pct=None,
            sniper_pct=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_holders failed for mint %s: %s", mint, exc)
        return HolderInfo(available=False)


# ---------------------------------------------------------------------------
# fetch_momentum
# ---------------------------------------------------------------------------


async def fetch_momentum(candidate: TokenCandidate) -> MomentumInfo:
    """Derive MomentumInfo purely from TokenCandidate fields — no network call.

    This dimension is essentially always available since it derives from
    the candidate data already in memory.

    Returns
    -------
    MomentumInfo with available=True (barring any unexpected error).
    """
    try:
        buy_sell_ratio = candidate.txns_5m_buys / max(candidate.txns_5m_sells, 1)
        fdv_to_liquidity = candidate.fdv_usd / max(candidate.liquidity_usd, _EPSILON)

        return MomentumInfo(
            available=True,
            liquidity_usd=candidate.liquidity_usd,
            volume_5m=candidate.volume_5m,
            volume_1h=candidate.volume_1h,
            buy_sell_ratio_5m=buy_sell_ratio,
            fdv_to_liquidity=fdv_to_liquidity,
            unique_buyers_1h=None,  # not available from candidate fields
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_momentum failed: %s", exc)
        return MomentumInfo(available=False)


# ---------------------------------------------------------------------------
# fetch_social
# ---------------------------------------------------------------------------


async def fetch_social(
    mint: str,
    helius_client,
    smart_wallets: dict,
    social_platforms: list[str],
    galaxy_score: Optional[float] = None,
) -> SocialInfo:
    """Smart-money consensus (Helius) + free social metadata (+ optional galaxy).

    available=True if EITHER smart-money consensus OR social metadata is present.

    Returns
    -------
    SocialInfo with:
      available=True  if at least one sub-source succeeded
      available=False if both sub-sources failed
    """
    smart_ok = False
    distinct = buyers = top_tier = None
    buys: Optional[int] = None

    try:
        result = await helius_client.analyze_smart_money(mint, smart_wallets)
        if result is not None:
            smart_ok = True
            buys = result.get("buys")
            distinct = result.get("distinct_wallets")
            buyers = result.get("buyers")
            top_tier = result.get("top_tier")
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_social: smart money failed for %s: %s", mint, exc)

    platforms = social_platforms or []
    has_tw = "twitter" in platforms
    has_tg = "telegram" in platforms
    has_web = "website" in platforms
    socials_count = len(platforms)
    metadata_present = socials_count > 0 or galaxy_score is not None

    return SocialInfo(
        available=smart_ok or metadata_present,
        smart_money_buys=buys if smart_ok else None,
        smart_money_distinct_wallets=distinct if smart_ok else None,
        smart_money_buyers=buyers if smart_ok else None,
        smart_money_top_tier=top_tier if smart_ok else None,
        has_twitter=has_tw if platforms else None,
        has_telegram=has_tg if platforms else None,
        has_website=has_web if platforms else None,
        socials_count=socials_count if platforms else None,
        galaxy_score=galaxy_score,
    )


# ---------------------------------------------------------------------------
# fetch_narrative
# ---------------------------------------------------------------------------


async def fetch_narrative(symbol: str, name: str) -> NarrativeInfo:
    """Deterministic narrative classification (never raises)."""
    return classify_narrative(symbol, name)
