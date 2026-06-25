import pytest
from memedogV2.harness.runner import HarnessRunner
from memedogV2.harness.model_registry import FakeBackend
from memedogV2.harness.contracts import StepStatus, ToolCallRecord
from memedogV2.sources.resolver import DataResolver
from memedogV2.sources.base import PartialFacts


class StubSource:
    def __init__(self, name, pf):
        self.name = name; self._pf = pf
    async def fetch(self, ca, lp):
        return self._pf, ToolCallRecord(tool=self.name, command="x", exit_status=0)


CLEAN = PartialFacts(mint_revoked=True, freeze_revoked=True, honeypot=False, lp_safe=True,
                     top10_rate=0.2, creator_rate=0.0, dev_rate=0.0, sniper_count=3,
                     fresh_wallet_rate=0.0, bundler_rate=0.0, liquidity_usd=50000,
                     volume_5m=5000, buys_5m=30, sells_5m=10, price_usd=0.05,
                     circulating_supply=1000000, smart_money_count=4, kol_count=1)
DIRTY = PartialFacts(mint_revoked=False, freeze_revoked=True, lp_safe=True,
                     liquidity_usd=50000, volume_5m=5000, buys_5m=30, sells_5m=10)
CFG = {"max_top10_rate": 0.35, "max_creator_rate": 0.10, "max_dev_rate": 0.10,
       "max_sniper_wallets": 20, "max_fresh_wallet_rate": 0.6, "max_bundler_rate": 0.3,
       "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0,
       "max_fdv_to_liquidity": 50}


def _backend():
    return FakeBackend(responses={
        "bull": {"thesis": "x", "points": []}, "bear": {"thesis": "y", "points": []},
        "judge": {"recommended": True, "signal": "BULLISH", "confidence": 0.7,
                  "summary": "net positive", "strengths": ["liquidity $50k healthy"],
                  "risks": ["dev created many tokens"], "key_metrics": ["liquidity=50000"]}})


def _runner(pf):
    resolver = DataResolver(sources={"gmgn": StubSource("gmgn", pf)})
    return HarnessRunner(resolver=resolver, backend=_backend(), hardfilter_cfg=CFG)


@pytest.mark.asyncio
async def test_clean_facts_run_full_workflow():
    run = await _runner(CLEAN).run("CA", "LP", trace_id="t1")
    sig = run.final_signal
    assert sig is not None and sig.recommended is True
    assert run.facts_snapshot["price_usd"] == 0.05
    assert run.facts_sources["price_usd"] == "gmgn"
    # detailed report carried into the signal
    assert sig.summary and sig.strengths and sig.risks and sig.key_metrics
    names = [s.name for s in run.steps]
    assert names == ["read_facts", "hardfilter", "build_evidence", "bull", "bear", "judge", "signal"]
    assert any(s.tool_calls for s in run.steps)


@pytest.mark.asyncio
async def test_dropped_facts_skip_models():
    run = await _runner(DIRTY).run("CA", "LP")
    assert run.final_signal is None
    statuses = {s.name: s.status for s in run.steps}
    assert statuses["bull"] == StepStatus.SKIPPED


@pytest.mark.asyncio
async def test_momentum_unavailable_fails_no_crash():
    pf = PartialFacts(mint_revoked=True, freeze_revoked=True, lp_safe=True)
    run = await _runner(pf).run("CA", "LP")
    assert run.final_signal is None
    assert any(s.status == StepStatus.FAILED for s in run.steps)


@pytest.mark.asyncio
async def test_source_failure_does_not_crash():
    class Boom:
        name = "gmgn"
        async def fetch(self, ca, lp):
            raise RuntimeError("network")
    resolver = DataResolver(sources={"gmgn": Boom()})
    runner = HarnessRunner(resolver=resolver, backend=_backend(), hardfilter_cfg=CFG)
    run = await runner.run("CA", "LP")     # must NOT raise (C-1)
    assert run.final_signal is None
    assert any(s.status == StepStatus.FAILED for s in run.steps)


def _runner_with_judge(judge_obj):
    backend = FakeBackend(responses={
        "bull": {"thesis": "x", "points": []}, "bear": {"thesis": "y", "points": []},
        "judge": judge_obj})
    resolver = DataResolver(sources={"gmgn": StubSource("gmgn", CLEAN)})
    return HarnessRunner(resolver=resolver, backend=backend, hardfilter_cfg=CFG)


@pytest.mark.asyncio
async def test_invalid_signal_enum_degrades_no_crash():
    judge = {"recommended": True, "signal": "STRONG_BUY", "confidence": 0.7,
             "summary": "s", "strengths": [], "risks": [], "key_metrics": []}
    run = await _runner_with_judge(judge).run("CA", "LP")
    assert run.final_signal is None
    assert any(s.name == "signal" and s.status == StepStatus.FAILED for s in run.steps)


@pytest.mark.asyncio
async def test_missing_summary_degrades_no_crash():
    judge = {"recommended": True, "signal": "BULLISH", "confidence": 0.7}  # no summary
    run = await _runner_with_judge(judge).run("CA", "LP")
    assert run.final_signal is None


@pytest.mark.asyncio
async def test_out_of_range_confidence_clamped():
    judge = {"recommended": True, "signal": "BULLISH", "confidence": 1.5,
             "summary": "s", "strengths": [], "risks": [], "key_metrics": []}
    run = await _runner_with_judge(judge).run("CA", "LP")
    assert run.final_signal is not None and run.final_signal.confidence == 1.0
