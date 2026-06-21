"""Pure rule functions for HardFilter.

Each rule returns (passed: bool, reason: str).
When passed is True, reason is an empty string.
When passed is False, reason describes the rule name, actual value, and threshold.

No I/O; all inputs are plain Python values so rules are trivially testable.
"""
from __future__ import annotations

from typing import Optional

from memedog.config.settings import (
    AuthorityFilterConfig,
    HoldersFilterConfig,
    MomentumFilterConfig,
)

_EPSILON = 1e-9


# ---------------------------------------------------------------------------
# Momentum rules
# ---------------------------------------------------------------------------


def check_momentum(
    liquidity_usd: float,
    volume_5m: float,
    txns_5m_buys: int,
    txns_5m_sells: int,
    fdv_usd: float,
    cfg: MomentumFilterConfig,
) -> tuple[bool, str]:
    """Check all momentum rules in order; fail fast on the first violation.

    Rules (in order):
    1. liquidity_usd >= min_liquidity_usd
    2. volume_5m >= min_volume_5m
    3. buy/sell ratio = txns_5m_buys / max(txns_5m_sells, 1) >= min_buy_sell_ratio_5m
    4. fdv_usd / max(liquidity_usd, epsilon) <= max_fdv_to_liquidity
    """
    # Rule 1: liquidity
    if liquidity_usd < cfg.min_liquidity_usd:
        return (
            False,
            f"momentum:liquidity_usd={liquidity_usd} < min={cfg.min_liquidity_usd}",
        )

    # Rule 2: volume
    if volume_5m < cfg.min_volume_5m:
        return (
            False,
            f"momentum:volume_5m={volume_5m} < min={cfg.min_volume_5m}",
        )

    # Rule 3: buy/sell ratio (avoid division by zero)
    ratio = txns_5m_buys / max(txns_5m_sells, 1)
    if ratio < cfg.min_buy_sell_ratio_5m:
        return (
            False,
            f"momentum:buy_sell_ratio={ratio:.4f} < min={cfg.min_buy_sell_ratio_5m}",
        )

    # Rule 4: FDV / liquidity
    fdv_ratio = fdv_usd / max(liquidity_usd, _EPSILON)
    if fdv_ratio > cfg.max_fdv_to_liquidity:
        return (
            False,
            f"momentum:fdv_to_liquidity={fdv_ratio:.2f} > max={cfg.max_fdv_to_liquidity}",
        )

    return (True, "")


# ---------------------------------------------------------------------------
# Authority rules
# ---------------------------------------------------------------------------


def check_authorities(
    mint_revoked: Optional[bool],
    freeze_revoked: Optional[bool],
    lp_locked: Optional[bool],
    cfg: AuthorityFilterConfig,
) -> tuple[bool, str]:
    """Check authority flags against configuration requirements.

    When require_* is True, the corresponding fact must be True to pass.
    None (unknown) counts as not-satisfied → fail.
    """
    if cfg.require_mint_revoked and mint_revoked is not True:
        return (False, "authority:mint_revoked is not confirmed (got None or False)")

    if cfg.require_freeze_revoked and freeze_revoked is not True:
        return (False, "authority:freeze_revoked is not confirmed (got None or False)")

    if cfg.require_lp_burned_or_locked and lp_locked is not True:
        return (False, "authority:lp_burned_or_locked is not confirmed (got None or False)")

    return (True, "")


# ---------------------------------------------------------------------------
# Holder rules
# ---------------------------------------------------------------------------


def check_holders(
    top10_pct: Optional[float],
    max_wallet_pct: Optional[float],
    dev_pct: Optional[float],
    sniper_pct: Optional[float],
    cfg: HoldersFilterConfig,
) -> tuple[bool, str]:
    """Check holder concentration metrics against configuration thresholds.

    Concentration assessability requirement:
    - At least one of (top10_pct, max_wallet_pct) must be present (non-None).
    - If BOTH are None → cannot assess concentration at all → fail with
      reason "holders_unassessable".

    Rules for present metrics (None → skip, not fail):
    1. top10_pct <= max_top10_pct            (if top10_pct is not None)
    2. max_wallet_pct < max_single_wallet_pct (strict <, if not None)
    3. dev_pct < max_dev_pct                 (strict <, if not None)
    4. sniper_pct < max_sniper_pct           (strict <, if not None)

    Rationale: dev_pct/sniper_pct may be genuinely unavailable (e.g. no
    creatorBalance field in response) and should not auto-drop an otherwise
    clean candidate.  However, if we cannot assess ANY concentration metric
    we cannot make a safety judgement → drop.
    """
    # Guard: require at least one concentration metric
    if top10_pct is None and max_wallet_pct is None:
        return (False, "holders_unassessable: both top10_pct and max_wallet_pct are None")

    # Rule 1: top-10 concentration (<=) — skip if None
    if top10_pct is not None:
        if top10_pct > cfg.max_top10_pct:
            return (
                False,
                f"holders:top10_pct={top10_pct} > max={cfg.max_top10_pct}",
            )

    # Rule 2: single wallet (strict <) — skip if None
    if max_wallet_pct is not None:
        if max_wallet_pct >= cfg.max_single_wallet_pct:
            return (
                False,
                f"holders:single_wallet_pct={max_wallet_pct} >= max={cfg.max_single_wallet_pct}",
            )

    # Rule 3: dev (strict <) — skip if None
    if dev_pct is not None:
        if dev_pct >= cfg.max_dev_pct:
            return (
                False,
                f"holders:dev_pct={dev_pct} >= max={cfg.max_dev_pct}",
            )

    # Rule 4: sniper (strict <) — skip if None
    if sniper_pct is not None:
        if sniper_pct >= cfg.max_sniper_pct:
            return (
                False,
                f"holders:sniper_pct={sniper_pct} >= max={cfg.max_sniper_pct}",
            )

    return (True, "")
