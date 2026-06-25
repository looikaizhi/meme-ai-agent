import pytest
from memedogV2.harness.runner import HarnessRunner
from memedogV2.harness.tool_registry import ToolRegistry, FixtureToolSource
from memedogV2.harness.model_registry import FakeBackend
from memedogV2.harness.contracts import StepStatus


CLEAN_SEC = {"renounced_mint": True, "renounced_freeze_account": True,
             "honeypot": 0, "burn_status": "burn", "lock_summary": {"is_locked": True}}
CLEAN_INFO = {"liquidity": "50000", "circulating_supply": "1000000",
              "price": {"price": "0.05", "volume_5m": "5000", "buys_5m": 30, "sells_5m": 10},
              "stat": {"top_10_holder_rate": "0.2", "creator_hold_rate": "0",
                       "dev_team_hold_rate": "0", "fresh_wallet_rate": "0",
                       "top_bundler_trader_percentage": "0"},
              "wallet_tags_stat": {"sniper_wallets": 3, "smart_wallets": 4, "renowned_wallets": 1}}
DIRTY_SEC = {"renounced_mint": False, "renounced_freeze_account": True}

CFG = {"max_top10_rate": 0.35, "max_creator_rate": 0.10, "max_dev_rate": 0.10,
       "max_sniper_wallets": 20, "max_fresh_wallet_rate": 0.6, "max_bundler_rate": 0.3,
       "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0,
       "max_fdv_to_liquidity": 50}


def _fake_backend():
    return FakeBackend(responses={
        "bull": {"thesis": "smart money", "points": []},
        "bear": {"thesis": "risk", "points": []},
        "judge": {"signal": "BULLISH", "recommended": True, "confidence": 0.7,
                  "rationale": "ok", "evidence_refs": ["smart_money_count"]},
    })


@pytest.mark.asyncio
async def test_clean_token_runs_full_workflow():
    reg = ToolRegistry(source=FixtureToolSource(security=CLEAN_SEC, info=CLEAN_INFO))
    runner = HarnessRunner(tool_registry=reg, backend=_fake_backend(),
                           hardfilter_cfg=CFG, recorder=None)
    run = await runner.run("CA", "LP", trace_id="t1")
    assert run.final_signal is not None
    assert run.final_signal.recommended is True
    assert run.final_signal.trace_id == "t1"
    names = [s.name for s in run.steps]
    assert names == ["read_security", "read_info", "hardfilter",
                     "build_evidence", "bull", "bear", "judge", "signal"]
    tool_steps = [s for s in run.steps if s.tool_calls]
    assert tool_steps


@pytest.mark.asyncio
async def test_dropped_token_skips_model_steps():
    reg = ToolRegistry(source=FixtureToolSource(security=DIRTY_SEC, info=CLEAN_INFO))
    runner = HarnessRunner(tool_registry=reg, backend=_fake_backend(),
                           hardfilter_cfg=CFG, recorder=None)
    run = await runner.run("CA", "LP")
    assert run.final_signal is None
    statuses = {s.name: s.status for s in run.steps}
    assert statuses["hardfilter"] == StepStatus.OK
    assert statuses["bull"] == StepStatus.SKIPPED
    assert statuses["judge"] == StepStatus.SKIPPED


@pytest.mark.asyncio
async def test_ratelimit_ban_recorded_no_signal():
    from memedogV2.clients.errors import RateLimitBanned

    class BannedSource:
        async def security(self, ca):
            raise RateLimitBanned("banned", reset_at=999)
        async def info(self, ca):
            return {}
    runner = HarnessRunner(tool_registry=ToolRegistry(source=BannedSource()),
                           backend=_fake_backend(), hardfilter_cfg=CFG, recorder=None)
    run = await runner.run("CA", "LP")
    assert run.final_signal is None
    assert any(s.status == StepStatus.FAILED for s in run.steps)
