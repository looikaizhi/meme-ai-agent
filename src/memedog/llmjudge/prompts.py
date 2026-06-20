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
