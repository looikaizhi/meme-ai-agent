import pytest
from memedogV2.harness.runner import HarnessRunner
from memedogV2.harness.model_registry import FakeBackend
from memedogV2.harness.contracts import ToolCallRecord
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
CFG = {"max_top10_rate": 0.35, "max_creator_rate": 0.10, "max_dev_rate": 0.10,
       "max_sniper_wallets": 20, "max_fresh_wallet_rate": 0.6, "max_bundler_rate": 0.3,
       "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0,
       "max_fdv_to_liquidity": 50}


@pytest.mark.asyncio
async def test_clean_token_flows_to_recommended_signal():
    resolver = DataResolver(sources={"gmgn": StubSource("gmgn", CLEAN)})
    backend = FakeBackend(responses={
        "bull": {"thesis": "x", "points": []}, "bear": {"thesis": "y", "points": []},
        "judge": {"recommended": True, "signal": "BULLISH", "confidence": 0.7,
                  "summary": "net positive", "strengths": ["liq healthy"],
                  "risks": ["dev tokens"], "key_metrics": ["liquidity=50000"]}})
    runner = HarnessRunner(resolver=resolver, backend=backend, hardfilter_cfg=CFG)
    run = await runner.run("CA", "LP", trace_id="t-e2e")
    assert run.final_signal is not None and run.final_signal.signal.value == "BULLISH"
    assert run.final_signal.summary and run.final_signal.key_metrics
