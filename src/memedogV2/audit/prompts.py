from __future__ import annotations

import json

from memedogV2.models.contracts import EvidenceBundle

ANALYST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"thesis": {"type": "string"},
                   "points": {"type": "array", "items": {"type": "string"}}},
    "required": ["thesis", "points"],
}

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "signal": {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
        "recommended": {"type": "boolean"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["signal", "recommended", "confidence", "rationale", "evidence_refs"],
}


def evidence_text(b: EvidenceBundle) -> str:
    body = b.model_dump()
    missing = body.pop("missing", [])
    body.pop("ca_address", None)
    present = {k: v for k, v in body.items() if v is not None}
    return (f"Evidence for {b.ca_address}: {json.dumps(present)}\n"
            f"Missing/unfetched dimensions: {missing}")


def analyst_prompt(role: str, b: EvidenceBundle) -> str:
    ev = evidence_text(b)
    if role == "bull":
        return f"You are the BULL analyst. Argue why this token could pump. {ev}"
    if role == "bear":
        return f"You are the BEAR analyst. Argue why this token is risky/avoid. {ev}"
    raise ValueError(f"unknown analyst role: {role}")


def judge_prompt(b: EvidenceBundle, *, bull: dict, bear: dict) -> str:
    ev = evidence_text(b)
    return (
        "You are the JUDGE. Weigh the bull vs bear and decide.\n"
        f"{ev}\n"
        f"BULL: {json.dumps(bull)}\n"
        f"BEAR: {json.dumps(bear)}\n"
        "Output signal (BULLISH/BEARISH/NEUTRAL), recommended (bool), "
        "confidence 0-1, rationale, evidence_refs. If key evidence is missing, "
        "lower confidence and say so."
    )
