"""Enricher dimension providers.

Each provider function fetches one *Info dimension and is independently degradable:
  - On ANY exception (network, timeout, data error), returns *Info(available=False).
  - NEVER re-raises to the caller.

Parallel failure semantics for fetch_social:
  - Twitter fails but smart money ok  → available=True (partial result)
  - Smart money fails but twitter ok  → available=True (partial result)
  - Both fail                         → available=False
  - Both succeed                      → available=True (full result)
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
)
from memedog.clients.rugcheck import parse_report

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
    symbol: str,
    mint: str,
    helius_client,
    twitter_client,
    smart_wallets: set[str],
    lookback_min: int,
) -> SocialInfo:
    """Combine smart-money buys (Helius) and Twitter mentions into SocialInfo.

    Partial failure semantics (documented at module level):
      - Either sub-source failing alone keeps available=True with its fields as None.
      - Both sub-sources failing → available=False.

    Returns
    -------
    SocialInfo with:
      available=True  if at least one sub-source succeeded
      available=False if both sub-sources failed
    """
    smart_money_buys: Optional[int] = None
    twitter_mentions_1h: Optional[int] = None
    twitter_growth: Optional[float] = None

    smart_money_ok = False
    twitter_ok = False

    # --- smart money buys (helius, best-effort) ---
    try:
        smart_money_buys = await helius_client.count_smart_money_buys(mint, smart_wallets)
        smart_money_ok = True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "fetch_social: smart money query failed for mint %s: %s", mint, exc
        )

    # --- twitter mentions ---
    try:
        twitter_result = await twitter_client.count_mentions(symbol, lookback_min)
        twitter_mentions_1h = twitter_result.get("mentions_1h")
        twitter_growth = twitter_result.get("growth")
        twitter_ok = True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "fetch_social: twitter query failed for symbol %s: %s", symbol, exc
        )

    # Determine overall availability: at least one sub-source must have succeeded
    available = smart_money_ok or twitter_ok

    return SocialInfo(
        available=available,
        smart_money_buys=smart_money_buys if smart_money_ok else None,
        twitter_mentions_1h=twitter_mentions_1h,
        twitter_growth=twitter_growth,
    )
