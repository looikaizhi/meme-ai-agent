"""Grounded, data-rich prompts for the Bull/Bear/Judge audit stages.

The whole point: the model reasons ONLY over the real on-chain Facts the resolver
fetched (with per-field source attribution), is told to cite specific numbers, and
is told to treat MISSING fields as unknown — never invent. This grounding is what
suppresses hallucination, and it lets the Judge produce a detailed report.
"""
from __future__ import annotations

import json
from typing import Optional

from memedogV2.sources.base import Facts

ANALYST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"thesis": {"type": "string"},
                   "points": {"type": "array", "items": {"type": "string"}}},
    "required": ["thesis", "points"],
}

# Detailed, structured + narrative report. All scalars / array[str] -> safe for both
# Codex strict --output-schema and DeepSeek json_object modes.
JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "recommended": {"type": "boolean"},
        "signal": {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "key_metrics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["recommended", "signal", "confidence", "summary",
                 "strengths", "risks", "key_metrics"],
}

GROUND_RULE = (
    "Base your analysis ONLY on the DATA above — these are real on-chain facts. "
    "Cite the specific numbers in your reasoning. Any field listed under MISSING is "
    "unknown; treat it as unknown and never invent a value. HARD_FILTER_FLAGS are "
    "deterministic warnings that survived the redline gate; weigh them explicitly, "
    "but do not treat them as automatic rejection unless the numbers justify it."
)

_GROUPS = {
    "SAFETY": ["mint_revoked", "freeze_revoked", "lp_safe", "honeypot"],
    "CONCENTRATION": ["top10_rate", "max_wallet_rate", "creator_rate", "dev_rate",
                      "sniper_count", "fresh_wallet_rate", "bundler_rate"],
    "MOMENTUM": ["liquidity_usd", "volume_5m", "buys_5m", "sells_5m",
                 "price_usd", "circulating_supply"],
    "SMART_MONEY_DEV": ["smart_money_count", "kol_count", "dev_created_count",
                        "historical_ath"],
}


def _fmt(name: str, val, sources: dict) -> Optional[str]:
    if val is None:
        return None
    src = sources.get(name)
    return f"{name}={val}" + (f" ({src})" if src else "")


def evidence_text(
    facts: Facts,
    sources: dict,
    missing: list,
    *,
    stage: str = "unknown",
    source: str = "",
    hardfilter_flags: list[str] | None = None,
) -> str:
    lines = ["DATA (real on-chain facts; source in parens):"]
    lines.append(f"CONTEXT: stage={stage or 'unknown'}"
                 + (f" | discovery_source={source}" if source else ""))
    for group, names in _GROUPS.items():
        parts = [p for p in (_fmt(n, getattr(facts, n), sources) for n in names) if p]
        lines.append(f"{group}: " + (" | ".join(parts) if parts else "(none available)"))
    if facts.price_usd is not None and facts.circulating_supply is not None:
        mcap = facts.price_usd * facts.circulating_supply
        ratio = (facts.buys_5m / facts.sells_5m) if (facts.buys_5m and facts.sells_5m) else None
        lines.append(f"DERIVED: market_cap≈{mcap:.0f}"
                     + (f" | buy_sell_ratio_5m={ratio:.2f}" if ratio is not None else ""))
    lines.append(f"HARD_FILTER_FLAGS: {hardfilter_flags or []}")
    lines.append(f"MISSING: {missing}")
    return "\n".join(lines)


def analyst_prompt(
    role: str,
    facts: Facts,
    sources: dict,
    missing: list,
    *,
    stage: str = "unknown",
    source: str = "",
    hardfilter_flags: list[str] | None = None,
) -> str:
    ev = evidence_text(
        facts,
        sources,
        missing,
        stage=stage,
        source=source,
        hardfilter_flags=hardfilter_flags,
    )
    if role == "bull":
        lead = ("You are the BULL analyst. Make the strongest DATA-GROUNDED case FOR "
                "this memecoin having upside, relative to its lifecycle stage.")
    elif role == "bear":
        lead = ("You are the BEAR analyst. Make the strongest DATA-GROUNDED case that "
                "this memecoin is risky — a likely rug, dump, or dead token. "
                "Separate normal newborn uncertainty from true red flags.")
    else:
        raise ValueError(f"unknown analyst role: {role}")
    return (f"{lead}\n{ev}\n{GROUND_RULE}\n"
            "Return a one-sentence thesis and points[] where EACH point cites a "
            "specific metric from the DATA.")


def judge_prompt(
    facts: Facts,
    sources: dict,
    missing: list,
    *,
    bull: dict,
    bear: dict,
    stage: str = "unknown",
    source: str = "",
    hardfilter_flags: list[str] | None = None,
) -> str:
    ev = evidence_text(
        facts,
        sources,
        missing,
        stage=stage,
        source=source,
        hardfilter_flags=hardfilter_flags,
    )
    return (
        "You are the JUDGE making a go/no-go call on whether to recommend buying this "
        "Solana memecoin.\n"
        f"{ev}\n"
        f"BULL case: {json.dumps(bull)}\n"
        f"BEAR case: {json.dumps(bear)}\n"
        f"{GROUND_RULE}\n"
        "Return a DETAILED report:\n"
        "- recommended (bool): would you recommend buying this memecoin?\n"
        "- signal (BULLISH/BEARISH/NEUTRAL), confidence (0-1)\n"
        "- summary: a 2-4 sentence narrative verdict\n"
        "- strengths: list, each citing a specific metric\n"
        "- risks: list, each citing a specific metric\n"
        "- key_metrics: list of the decisive numbers, e.g. 'liquidity $57k — healthy', "
        "'dev_created_count 69 — serial-launcher red flag'\n"
        "Passing the redline hardfilter does not mean bullish. Use BULLISH and "
        "recommended=true only when safety, liquidity, distribution, and momentum are "
        "strong for this token's stage. If early but promising, prefer NEUTRAL with "
        "recommended=false and call it watchlist. If clean but crowded, near ATH, "
        "bundled, or weakly bid, prefer NEUTRAL or BEARISH. If important data is in "
        "MISSING, LOWER confidence and add a risk noting it."
    )
