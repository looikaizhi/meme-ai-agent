import pytest
from memedogV2.audit.debate import BullBearJudge
from memedogV2.models.contracts import EvidenceBundle, Signal, SignalKind


class ScriptedAgent:
    """Returns queued payloads in order (bull, bear, judge)."""
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.prompts = []

    async def run(self, *, prompt, schema):
        self.prompts.append(prompt)
        return self._payloads.pop(0)


@pytest.mark.asyncio
async def test_debate_produces_recommended_signal():
    agent = ScriptedAgent([
        {"thesis": "smart money in", "points": ["4 smart wallets"]},
        {"thesis": "thin liquidity risk", "points": ["fresh wallets high"]},
        {"signal": "BULLISH", "recommended": True, "confidence": 0.72,
         "rationale": "smart money outweighs risk", "evidence_refs": ["smart_money_count"]},
    ])
    jbj = BullBearJudge(agent=agent)
    bundle = EvidenceBundle(ca_address="CA", smart_money_count=4)
    sig = await jbj.decide(bundle)
    assert isinstance(sig, Signal)
    assert sig.signal is SignalKind.BULLISH and sig.recommended is True
    assert sig.confidence == 0.72
    assert len(agent.prompts) == 3        # bull, bear, judge order
    assert "bull" in agent.prompts[0].lower()
    assert "bear" in agent.prompts[1].lower()


@pytest.mark.asyncio
async def test_bundle_missing_dims_flow_into_judge_prompt():
    agent = ScriptedAgent([
        {"thesis": "ok", "points": []},
        {"thesis": "ok", "points": []},
        {"signal": "NEUTRAL", "recommended": False, "confidence": 0.4,
         "rationale": "insufficient evidence", "evidence_refs": []},
    ])
    jbj = BullBearJudge(agent=agent)
    bundle = EvidenceBundle(ca_address="CA", missing=["kol_holder_count"])
    sig = await jbj.decide(bundle)
    assert sig.signal is SignalKind.NEUTRAL and sig.recommended is False
    assert "kol_holder_count" in agent.prompts[2]   # missing dims surfaced to judge


@pytest.mark.asyncio
async def test_confidence_clamped_to_unit_interval():
    agent = ScriptedAgent([
        {"thesis": "x", "points": []},
        {"thesis": "y", "points": []},
        {"signal": "BULLISH", "recommended": True, "confidence": 1.5,
         "rationale": "over-confident model", "evidence_refs": []},
    ])
    jbj = BullBearJudge(agent=agent)
    sig = await jbj.decide(EvidenceBundle(ca_address="CA"))
    assert sig.confidence == 1.0
