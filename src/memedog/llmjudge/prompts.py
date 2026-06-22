"""Prompt builders for the LLM bull/bear/judge debate.

Each function returns a list[LLMMessage] ready to pass to a provider.
Dimensions with available=False are explicitly noted as data missing.
"""
from __future__ import annotations

from memedog.llm.provider import LLMMessage
from memedog.models import Score, TokenSnapshot


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fmt_money(v: float) -> str:
    try:
        return f"${v:,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_pct(v: float) -> str:
    try:
        return f"{v:.1f}%"
    except (TypeError, ValueError):
        return str(v)


def _fmt_ratio(v: float) -> str:
    try:
        return f"{v:.2f}"
    except (TypeError, ValueError):
        return str(v)


def _evidence_line(label: str, available: bool, fields: list[tuple[str, str]]) -> str:
    """Render one dimension line; DATA MISSING when unavailable or all fields empty."""
    if not available or not fields:
        return f"{label:<22}DATA MISSING (数据缺失)"
    body = "  ".join(f"{name}={val}" for name, val in fields)
    return f"{label:<22}{body}"


def _snapshot_evidence(snapshot: TokenSnapshot, score: Score) -> str:
    """Render the raw on-chain evidence block shared by all three prompts."""
    s = snapshot.safety
    h = snapshot.holders
    m = snapshot.momentum
    soc = snapshot.social

    safety_fields: list[tuple[str, str]] = []
    if s.mint_authority_revoked is not None:
        safety_fields.append(("mint撤权", str(s.mint_authority_revoked)))
    if s.freeze_authority_revoked is not None:
        safety_fields.append(("freeze撤权", str(s.freeze_authority_revoked)))
    if s.lp_burned_or_locked is not None:
        safety_fields.append(("LP烧/锁", str(s.lp_burned_or_locked)))
    if s.rug_trust_score is not None:
        safety_fields.append(("trust", f"{s.rug_trust_score}/100"))
    if s.rug_risk_level is not None:
        safety_fields.append(("risk", str(s.rug_risk_level)))

    holder_fields: list[tuple[str, str]] = []
    if h.top10_pct is not None:
        holder_fields.append(("top10", _fmt_pct(h.top10_pct)))
    if h.max_wallet_pct is not None:
        holder_fields.append(("最大钱包", _fmt_pct(h.max_wallet_pct)))
    if h.dev_wallet_pct is not None:
        holder_fields.append(("dev", _fmt_pct(h.dev_wallet_pct)))
    if h.holder_count is not None:
        holder_fields.append(("持币人", str(h.holder_count)))
    if h.sniper_pct is not None:
        holder_fields.append(("sniper", _fmt_pct(h.sniper_pct)))

    mom_fields: list[tuple[str, str]] = []
    if m.liquidity_usd is not None:
        mom_fields.append(("流动性", _fmt_money(m.liquidity_usd)))
    if m.volume_5m is not None:
        mom_fields.append(("5min量", _fmt_money(m.volume_5m)))
    if m.volume_1h is not None:
        mom_fields.append(("1h量", _fmt_money(m.volume_1h)))
    if m.buy_sell_ratio_5m is not None:
        mom_fields.append(("买卖比", _fmt_ratio(m.buy_sell_ratio_5m)))
    if m.unique_buyers_1h is not None:
        mom_fields.append(("独立买家", str(m.unique_buyers_1h)))
    if m.fdv_to_liquidity is not None:
        mom_fields.append(("FDV/流", _fmt_ratio(m.fdv_to_liquidity)))

    soc_fields: list[tuple[str, str]] = []
    if soc.smart_money_buys is not None:
        soc_fields.append(("聪明钱买入", str(soc.smart_money_buys)))
    if soc.twitter_mentions_1h is not None:
        soc_fields.append(("推特提及", str(soc.twitter_mentions_1h)))
    if soc.twitter_growth is not None:
        soc_fields.append(("推特增速", _fmt_ratio(soc.twitter_growth)))

    lines = [
        _evidence_line("SAFETY (RugCheck):", s.available, safety_fields),
        _evidence_line("HOLDERS (Helius):", h.available, holder_fields),
        _evidence_line("MOMENTUM (DexScreen):", m.available, mom_fields),
        _evidence_line("SOCIAL:", soc.available, soc_fields),
    ]

    dim_map = {d.name: d.raw for d in score.dimensions}
    pre = (
        f"[规则预筛分(参考,非最终结论): 总分 {score.total:.1f}/100 | "
        f"safety {dim_map.get('safety', float('nan')):.0f} "
        f"holders {dim_map.get('holders', float('nan')):.0f} "
        f"momentum {dim_map.get('momentum', float('nan')):.0f} "
        f"social {dim_map.get('social', float('nan')):.0f}]"
    )
    lines.append(pre)
    return "\n".join(lines)


def _dimension_summary(snapshot: TokenSnapshot, score: Score) -> str:
    """Render a compact table of all four dimensions with scores and data flags."""
    dim_map = {d.name: d for d in score.dimensions}
    avail = {
        "safety": snapshot.safety.available,
        "holders": snapshot.holders.available,
        "momentum": snapshot.momentum.available,
        "social": snapshot.social.available,
    }
    lines: list[str] = []
    for name, available in avail.items():
        dim = dim_map.get(name)
        if not available:
            lines.append(
                f"  {name}: DATA MISSING (数据缺失) — dimension unavailable"
            )
        elif dim is not None:
            lines.append(
                f"  {name}: raw={dim.raw:.1f}, weight={dim.weight:.2f}, "
                f"weighted={dim.weighted:.2f}"
            )
        else:
            lines.append(f"  {name}: (no score)")
    return "\n".join(lines)


def _missing_note(snapshot: TokenSnapshot) -> str:
    """Return a note about which dimensions have missing data, if any."""
    missing = []
    if not snapshot.safety.available:
        missing.append("safety")
    if not snapshot.holders.available:
        missing.append("holders")
    if not snapshot.momentum.available:
        missing.append("momentum")
    if not snapshot.social.available:
        missing.append("social")
    if not missing:
        return ""
    dims = ", ".join(missing)
    return (
        f"\nNOTE: The following dimensions have missing data (数据缺失): {dims}. "
        "Factor this uncertainty into your analysis."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def bull_prompt(snapshot: TokenSnapshot, score: Score) -> list[LLMMessage]:
    """Render a bullish advocate prompt for *snapshot* + *score*."""
    symbol = snapshot.candidate.symbol
    mint = snapshot.candidate.mint
    total = score.total
    dim_summary = _dimension_summary(snapshot, score)
    missing_note = _missing_note(snapshot)

    system_content = (
        "You are a bullish crypto analyst. Your job is to identify all positive signals "
        "and reasons to BUY the token. Be specific and cite the data."
    )
    user_content = (
        f"Analyze token {symbol} (mint: {mint}).\n"
        f"Composite score: {total:.1f}/100\n\n"
        f"Dimension scores:\n{dim_summary}"
        f"{missing_note}\n\n"
        "Make the strongest possible BULLISH case. List concrete bull points "
        "supported by the data above."
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def bear_prompt(snapshot: TokenSnapshot, score: Score) -> list[LLMMessage]:
    """Render a bearish advocate prompt for *snapshot* + *score*."""
    symbol = snapshot.candidate.symbol
    mint = snapshot.candidate.mint
    total = score.total
    dim_summary = _dimension_summary(snapshot, score)
    missing_note = _missing_note(snapshot)

    system_content = (
        "You are a bearish crypto analyst / risk officer. Your job is to identify all "
        "risks, red flags, and reasons to AVOID the token. Be specific and cite the data."
    )
    user_content = (
        f"Analyze token {symbol} (mint: {mint}).\n"
        f"Composite score: {total:.1f}/100\n\n"
        f"Dimension scores:\n{dim_summary}"
        f"{missing_note}\n\n"
        "Make the strongest possible BEARISH case. List concrete bear points "
        "and red flags supported by the data above."
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def judge_prompt(
    snapshot: TokenSnapshot,
    score: Score,
    bull_text: str,
    bear_text: str,
) -> list[LLMMessage]:
    """Render the impartial judge prompt combining bull and bear arguments."""
    symbol = snapshot.candidate.symbol
    mint = snapshot.candidate.mint
    total = score.total
    dim_summary = _dimension_summary(snapshot, score)
    missing_note = _missing_note(snapshot)

    system_content = (
        "You are an impartial trading signal judge. You weigh bull and bear arguments "
        "and produce a final verdict as a structured JSON object."
    )
    user_content = (
        f"Token: {symbol} (mint: {mint})\n"
        f"Composite score: {total:.1f}/100\n\n"
        f"Dimension scores:\n{dim_summary}"
        f"{missing_note}\n\n"
        f"=== BULL ARGUMENT ===\n{bull_text}\n\n"
        f"=== BEAR ARGUMENT ===\n{bear_text}\n\n"
        "Based on the data and arguments above, produce a final trading signal.\n\n"
        "Output ONLY a valid JSON object (no prose, no code fences) with these fields:\n"
        "{\n"
        '  "signal": "<one of: BULLISH, BEARISH, NEUTRAL>",\n'
        '  "confidence": <float between 0.0 and 1.0>,\n'
        '  "bull_points": ["<key bull point>", ...],\n'
        '  "bear_points": ["<key bear point>", ...],\n'
        '  "red_flags": ["<red flag>", ...],\n'
        '  "rationale": "<1-2 sentence summary>"\n'
        "}"
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
