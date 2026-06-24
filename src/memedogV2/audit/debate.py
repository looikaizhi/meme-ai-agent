from __future__ import annotations

import json

from memedogV2.models.contracts import EvidenceBundle, Signal, SignalKind

_ANALYST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"thesis": {"type": "string"},
                   "points": {"type": "array", "items": {"type": "string"}}},
    "required": ["thesis", "points"],
}

_JUDGE_SCHEMA = {
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


class BullBearJudge:
    """Bull + Bear read one shared EvidenceBundle; Judge weighs both -> Signal."""

    def __init__(self, *, agent) -> None:
        self._agent = agent

    @staticmethod
    def _evidence_text(b: EvidenceBundle) -> str:
        body = b.model_dump()
        missing = body.pop("missing", [])
        return (f"Evidence for {b.ca_address}: {json.dumps(body)}\n"
                f"Missing/unfetched dimensions: {missing}")

    async def decide(self, bundle: EvidenceBundle) -> Signal:
        ev = self._evidence_text(bundle)

        bull = await self._agent.run(
            prompt=f"You are the BULL analyst. Argue why this token could pump. {ev}",
            schema=_ANALYST_SCHEMA)
        bear = await self._agent.run(
            prompt=f"You are the BEAR analyst. Argue why this token is risky/avoid. {ev}",
            schema=_ANALYST_SCHEMA)

        judge = await self._agent.run(
            prompt=(
                "You are the JUDGE. Weigh the bull vs bear and decide.\n"
                f"{ev}\n"
                f"BULL: {json.dumps(bull)}\n"
                f"BEAR: {json.dumps(bear)}\n"
                "Output signal (BULLISH/BEARISH/NEUTRAL), recommended (bool), "
                "confidence 0-1, rationale, evidence_refs. If key evidence is missing, "
                "lower confidence and say so."
            ),
            schema=_JUDGE_SCHEMA)

        confidence = max(0.0, min(1.0, float(judge["confidence"])))
        return Signal(
            ca_address=bundle.ca_address,
            signal=SignalKind(judge["signal"]),
            recommended=bool(judge["recommended"]),
            confidence=confidence,
            rationale=str(judge["rationale"]),
            evidence_refs=list(judge.get("evidence_refs", [])),
        )
