import pytest
from memedogV2.orchestrator import V2Orchestrator
from memedogV2.models.contracts import HardFilterResult, Signal, SignalKind
from memedogV2.clients.errors import RateLimitBanned


class FakeHF:
    def __init__(self, passed):
        self._passed = passed
        self.seen = []

    async def evaluate(self, ca, lp, trace_id=""):
        self.seen.append(ca)
        return HardFilterResult(ca_address=ca, lp_address=lp, passed=self._passed,
                                trace_id=trace_id)


class FakeAudit:
    def __init__(self):
        self.audited = []

    async def run(self, hf_result):
        self.audited.append(hf_result.ca_address)
        return Signal(ca_address=hf_result.ca_address, signal=SignalKind.BULLISH,
                      recommended=True, confidence=0.6, rationale="ok")


@pytest.mark.asyncio
async def test_dropped_candidate_skips_audit():
    hf, audit = FakeHF(passed=False), FakeAudit()
    orch = V2Orchestrator(hardfilter=hf, audit=audit)
    sig = await orch.process("CA", "LP")
    assert sig is None
    assert audit.audited == []


@pytest.mark.asyncio
async def test_passed_candidate_gets_signal():
    hf, audit = FakeHF(passed=True), FakeAudit()
    orch = V2Orchestrator(hardfilter=hf, audit=audit)
    sig = await orch.process("CA", "LP", trace_id="t1")
    assert sig is not None and sig.recommended is True
    assert sig.trace_id == "t1"
    assert audit.audited == ["CA"]


@pytest.mark.asyncio
async def test_process_never_raises_on_audit_error():
    class BoomAudit:
        async def run(self, hf_result):
            raise RuntimeError("audit down")
    orch = V2Orchestrator(hardfilter=FakeHF(passed=True), audit=BoomAudit())
    sig = await orch.process("CA", "LP")     # swallowed
    assert sig is None


@pytest.mark.asyncio
async def test_process_swallows_ratelimit_ban():
    class BannedHF:
        async def evaluate(self, ca, lp, trace_id=""):
            raise RateLimitBanned("banned", reset_at=999)
    orch = V2Orchestrator(hardfilter=BannedHF(), audit=FakeAudit())
    sig = await orch.process("CA", "LP")
    assert sig is None
