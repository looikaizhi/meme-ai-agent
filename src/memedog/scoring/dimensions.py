"""Dimension scorer functions for MemeDog Radar ScoreEngine.

Each function computes a raw score (0–100) for one data dimension.
Weight and weighted fields are left at 0.0 as placeholders — the engine
fills them after renormalization.

Heuristics documented:
- lerp_score: general clamped linear map; handles both "higher is better"
  (full_at > zero_at) and "lower is better" (full_at < zero_at).
- Safety: base = rug_trust_score (0–100); if no score available use neutral.
  CRITICAL/HIGH rug_risk_level caps raw to min(raw, 20).
  Each explicitly-False authority flag (mint/freeze/lp) deducts 15 pts.
- Holders: average of available sub-metrics; top10 uses lerp (lower→better);
  max_wallet uses lerp from 0→100 (lower→better, full at 0, zero at max_wallet_zero_at).
- Momentum: average liquidity and volume_5m lerps; buy_sell_ratio > 1 adds a
  gentle bonus: min(10, (ratio-1)*10); all clamped to [0,100].
- Social: smart_money_buys mapped via lerp(full_at=10, zero_at=0); twitter_growth
  mapped via lerp(full_at=2.0, zero_at=-1.0); average of available metrics.
"""
from __future__ import annotations

from typing import Optional

from memedog.models.snapshot import HolderInfo, MomentumInfo, SafetyInfo, SocialInfo
from memedog.models.score import DimensionScore


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def lerp_score(value: float, full_at: float, zero_at: float) -> float:
    """Map *value* linearly so full_at→100 and zero_at→0, clamped to [0,100].

    Works for both directions:
    - full_at > zero_at: higher value is better (e.g. liquidity)
    - full_at < zero_at: lower value is better (e.g. top10 concentration)
    """
    if full_at == zero_at:
        return 100.0 if value == full_at else 0.0
    # Linear interpolation: t = (value - zero_at) / (full_at - zero_at)
    # t=0 → 0 points, t=1 → 100 points
    t = (value - zero_at) / (full_at - zero_at)
    return float(max(0.0, min(100.0, t * 100.0)))


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def score_safety(info: SafetyInfo, cfg) -> DimensionScore:
    """Score the safety dimension.

    cfg is ScoringConfig (or any object with .neutral_score).

    Heuristic:
    1. Base = rug_trust_score if present, else neutral_score.
    2. Each explicitly-False authority flag deducts 15 pts from raw.
    3. CRITICAL or HIGH rug_risk_level caps raw to min(raw, 20).
    """
    notes: list[str] = []

    if not info.available:
        notes.append("数据缺失 (safety unavailable)")
        return DimensionScore(name="safety", raw=cfg.neutral_score, weight=0.0, weighted=0.0, notes=notes)

    # Base raw from trust score
    raw: float = float(info.rug_trust_score) if info.rug_trust_score is not None else cfg.neutral_score

    # Penalise explicitly-False authority/lp flags
    for flag_name, flag_val in [
        ("mint_authority_revoked", info.mint_authority_revoked),
        ("freeze_authority_revoked", info.freeze_authority_revoked),
        ("lp_burned_or_locked", info.lp_burned_or_locked),
    ]:
        if flag_val is False:
            raw -= 15.0
            notes.append(f"{flag_name} is False — deducted 15 pts")

    # Fix 3: always record CRITICAL/HIGH risk in notes, even when penalties
    # already pushed raw below the cap so the audit trail is never incomplete.
    if info.rug_risk_level in {"CRITICAL", "HIGH"}:
        notes.append(f"rug_risk_level={info.rug_risk_level} — high risk detected")
        if raw > 20:
            notes.append(f"rug_risk_level={info.rug_risk_level} — capped raw to 20")
            raw = 20.0

    raw = max(0.0, min(100.0, raw))
    return DimensionScore(name="safety", raw=raw, weight=0.0, weighted=0.0, notes=notes)


def score_holders(info: HolderInfo, cfg) -> DimensionScore:
    """Score the holders dimension.

    Sub-metrics (each in [0,100]):
    - top10_pct: lerp(full_at=top10_full_score_at, zero_at=top10_zero_score_at) — lower is better
    - max_wallet_pct: lerp(full_at=0, zero_at=max_wallet_zero_at) — lower is better

    Average of available sub-metrics. If none available → neutral + note.
    """
    notes: list[str] = []

    if not info.available:
        notes.append("数据缺失 (holders unavailable)")
        return DimensionScore(name="holders", raw=cfg.neutral_score, weight=0.0, weighted=0.0, notes=notes)

    scores: list[float] = []

    if info.top10_pct is not None:
        s = lerp_score(info.top10_pct,
                       full_at=cfg.holders.top10_full_score_at,
                       zero_at=cfg.holders.top10_zero_score_at)
        scores.append(s)

    if info.max_wallet_pct is not None:
        s = lerp_score(info.max_wallet_pct,
                       full_at=0.0,
                       zero_at=cfg.holders.max_wallet_zero_at)
        scores.append(s)

    if not scores:
        notes.append("数据缺失 (no holder metrics available)")
        return DimensionScore(name="holders", raw=cfg.neutral_score, weight=0.0, weighted=0.0, notes=notes)

    raw = sum(scores) / len(scores)
    return DimensionScore(name="holders", raw=raw, weight=0.0, weighted=0.0, notes=notes)


def score_momentum(info: MomentumInfo, cfg) -> DimensionScore:
    """Score the momentum dimension.

    Sub-metrics:
    - liquidity_usd: lerp(full_at=liquidity_full_at, zero_at=0)
    - volume_5m: lerp(full_at=volume_5m_full_at, zero_at=0)
    - buy_sell_ratio_5m: gentle bonus = min(10, (ratio-1)*10) if ratio > 1 else 0
      (added to the average of liquidity+volume, clamped to [0,100])

    Average of available liquidity/volume metrics, then apply ratio bonus.
    """
    notes: list[str] = []

    if not info.available:
        notes.append("数据缺失 (momentum unavailable)")
        return DimensionScore(name="momentum", raw=cfg.neutral_score, weight=0.0, weighted=0.0, notes=notes)

    scores: list[float] = []

    if info.liquidity_usd is not None:
        s = lerp_score(info.liquidity_usd,
                       full_at=cfg.momentum.liquidity_full_at,
                       zero_at=0.0)
        scores.append(s)

    if info.volume_5m is not None:
        s = lerp_score(info.volume_5m,
                       full_at=cfg.momentum.volume_5m_full_at,
                       zero_at=0.0)
        scores.append(s)

    if not scores:
        notes.append("数据缺失 (no momentum metrics available)")
        return DimensionScore(name="momentum", raw=cfg.neutral_score, weight=0.0, weighted=0.0, notes=notes)

    raw = sum(scores) / len(scores)

    # Gentle buy/sell ratio bonus
    if info.buy_sell_ratio_5m is not None and info.buy_sell_ratio_5m > 1.0:
        bonus = min(10.0, (info.buy_sell_ratio_5m - 1.0) * 10.0)
        raw = min(100.0, raw + bonus)

    # Fix 5: removed dead clamp here (raw is already within [0,100] at this point)
    return DimensionScore(name="momentum", raw=raw, weight=0.0, weighted=0.0, notes=notes)


def score_social(info: SocialInfo, cfg) -> DimensionScore:
    """Score the social dimension (noisy; keep mapping simple).

    Sub-metrics:
    - smart_money_buys: lerp(full_at=cfg.social.smart_money_full_at, zero_at=0)
    - twitter_growth: lerp(full_at=cfg.social.twitter_growth_full_at,
                           zero_at=cfg.social.twitter_growth_zero_at)

    Fix 4: thresholds are now read from cfg.social (ScoringSocialConfig) rather
    than being hardcoded, honouring the project's no-hardcoding rule.

    Average of available metrics. All None → neutral + note.
    """
    notes: list[str] = []

    if not info.available:
        notes.append("数据缺失 (social unavailable)")
        return DimensionScore(name="social", raw=cfg.neutral_score, weight=0.0, weighted=0.0, notes=notes)

    scores: list[float] = []

    if info.smart_money_buys is not None:
        s = lerp_score(
            float(info.smart_money_buys),
            full_at=cfg.social.smart_money_full_at,
            zero_at=0.0,
        )
        scores.append(s)

    if info.twitter_growth is not None:
        s = lerp_score(
            info.twitter_growth,
            full_at=cfg.social.twitter_growth_full_at,
            zero_at=cfg.social.twitter_growth_zero_at,
        )
        scores.append(s)

    if not scores:
        notes.append("数据缺失 (no social metrics available)")
        return DimensionScore(name="social", raw=cfg.neutral_score, weight=0.0, weighted=0.0, notes=notes)

    raw = max(0.0, min(100.0, sum(scores) / len(scores)))
    return DimensionScore(name="social", raw=raw, weight=0.0, weighted=0.0, notes=notes)
