from __future__ import annotations

from dataclasses import dataclass

from memedogV2.hardfilter import rules as R
from memedogV2.sources.base import Facts


_PENDING_STAGES = {"new_creation", "near_completion", "bonding_curve"}


@dataclass(frozen=True)
class HardfilterDecision:
    passed: bool
    dropped: list[str]
    flagged: list[str]
    stage: str = "unknown"


def evaluate_facts(f: Facts, cfg: dict) -> tuple[bool, list[str]]:
    """Run red-line rules over canonical Facts. Returns (passed, dropped_reasons).
    Degrades open on missing values (same policy as the gmgn-coupled filter)."""
    decision = evaluate_facts_detail(f, cfg)
    return decision.passed, decision.dropped


def evaluate_facts_detail(
    f: Facts,
    cfg: dict,
    *,
    stage: str = "unknown",
) -> HardfilterDecision:
    """Run stage-aware redlines and return soft risks for the audit prompt.

    The redline gate decides whether a token is safe enough to spend LLM calls on.
    Borderline market-structure concerns are carried forward as flags so the
    judge can still return BEARISH/NEUTRAL with full rationale.
    """
    dropped: list[str] = []
    flagged: list[str] = []
    stage = stage or "unknown"
    stage_pending = stage in _PENDING_STAGES

    ok, reason = R.check_authorities(
        renounced_mint=f.mint_revoked, renounced_freeze=f.freeze_revoked,
        honeypot=(1 if f.honeypot else 0) if f.honeypot is not None else None)
    if not ok:
        if stage_pending and ("mint" in reason or "freeze" in reason):
            flagged.append(f"{reason} (stage_pending)")
        else:
            dropped.append(reason)
            return HardfilterDecision(False, dropped, flagged, stage)

    ok, reason = R.check_lp(
        burn_status=("burn" if f.lp_safe else "") if f.lp_safe is not None else None,
        lp_locked=f.lp_safe)
    if not ok:
        if stage_pending:
            flagged.append(f"{reason} (stage_pending)")
        else:
            dropped.append(reason)
            return HardfilterDecision(False, dropped, flagged, stage)

    top10 = R.num(f.top10_rate)
    if top10 is not None:
        if top10 > cfg.get("hard_max_top10_rate", cfg["max_top10_rate"]):
            dropped.append(
                f"concentration: top10 {top10} > "
                f"{cfg.get('hard_max_top10_rate', cfg['max_top10_rate'])}"
            )
            return HardfilterDecision(False, dropped, flagged, stage)
        if top10 > cfg["max_top10_rate"]:
            flagged.append(f"concentration: top10 {top10} > {cfg['max_top10_rate']}")
    for name, value, key in (
        ("creator", f.creator_rate, "max_creator_rate"),
        ("dev", f.dev_rate, "max_dev_rate"),
    ):
        v = R.num(value)
        if v is not None and v > cfg[key]:
            dropped.append(f"concentration: {name} {v} > {cfg[key]}")
            return HardfilterDecision(False, dropped, flagged, stage)

    if f.sniper_count is not None:
        hard_snipers = cfg.get("hard_max_sniper_wallets", cfg["max_sniper_wallets"])
        if f.sniper_count > hard_snipers:
            dropped.append(f"manipulation: snipers {f.sniper_count} > {hard_snipers}")
            return HardfilterDecision(False, dropped, flagged, stage)
        if f.sniper_count > cfg["max_sniper_wallets"]:
            flagged.append(
                f"manipulation: snipers {f.sniper_count} > {cfg['max_sniper_wallets']}"
            )
    for name, value, soft_key, hard_key in (
        ("fresh", f.fresh_wallet_rate, "max_fresh_wallet_rate", "hard_max_fresh_wallet_rate"),
        ("bundler", f.bundler_rate, "max_bundler_rate", "hard_max_bundler_rate"),
    ):
        v = R.num(value)
        hard = cfg.get(hard_key, cfg[soft_key])
        if v is not None:
            if v > hard:
                dropped.append(f"manipulation: {name} {v} > {hard}")
                return HardfilterDecision(False, dropped, flagged, stage)
            if v > cfg[soft_key]:
                flagged.append(f"manipulation: {name} {v} > {cfg[soft_key]}")

    ratio = (f.buys_5m / f.sells_5m) if (f.buys_5m is not None and f.sells_5m) else None
    fdv = (f.price_usd * f.circulating_supply) if (f.price_usd is not None
                                                   and f.circulating_supply is not None) else None
    ok, reason = R.check_momentum(liquidity=f.liquidity_usd, volume_5m=f.volume_5m,
                                  buy_sell=ratio, fdv=fdv, cfg=cfg)
    if not ok:
        dropped.append(reason)
        return HardfilterDecision(False, dropped, flagged, stage)
    soft_ratio = cfg.get("soft_min_buy_sell_ratio_5m")
    if ratio is not None and soft_ratio is not None and ratio < soft_ratio:
        flagged.append(f"momentum: buy/sell {ratio} < {soft_ratio}")

    return HardfilterDecision(True, dropped, flagged, stage)
