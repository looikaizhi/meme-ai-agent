import json
import pytest
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.hardfilter.hardfilter import HardFilter
from memedogV2.audit.evidence import EvidenceGatherer
from memedogV2.audit.debate import BullBearJudge
from memedogV2.orchestrator import V2Orchestrator, AuditPipeline


# Real gmgn field shapes: 2 commands (security + info); numbers are strings; rates are 0-1.
CLEAN = {
    "token:security:CA": {"renounced_mint": True, "renounced_freeze_account": True,
                          "honeypot": 0, "burn_status": "burn",
                          "lock_summary": {"is_locked": True}},
    "token:info:CA": {"liquidity": "50000", "circulating_supply": "1000000",
                      "price": {"price": "0.05", "volume_5m": "5000",
                                "buys_5m": 30, "sells_5m": 10},
                      "stat": {"top_10_holder_rate": "0.2", "creator_hold_rate": "0",
                               "dev_team_hold_rate": "0", "fresh_wallet_rate": "0",
                               "top_bundler_trader_percentage": "0"},
                      "wallet_tags_stat": {"sniper_wallets": 3, "smart_wallets": 4,
                                           "renowned_wallets": 1}},
}


def make_runner():
    async def runner(args):
        # args = ["token", "<sub>", "--chain", "sol", "--address", "<CA>", "--raw"]
        sub = f"{args[0]}:{args[1]}:{args[5]}"
        return (0, json.dumps(CLEAN[sub]), "")
    return runner


class StubAgent:
    async def run(self, *, prompt, schema):
        # Check JUDGE first: the judge prompt also embeds "BULL"/"BEAR" sections.
        if "JUDGE" in prompt:
            return {"signal": "BULLISH", "recommended": True, "confidence": 0.7,
                    "rationale": "net positive", "evidence_refs": ["smart_money_count"]}
        if "BULL" in prompt:
            return {"thesis": "smart money", "points": []}
        if "BEAR" in prompt:
            return {"thesis": "risks", "points": []}
        # evidence-gather call (the 5 scalar fields)
        return {"smart_money_count": 4, "kol_holder_count": 1,
                "dev_created_token_count": 0, "dev_graduation_rate": None,
                "historical_ath": None}


def _cfg():
    return {"max_top10_rate": 0.35, "max_creator_rate": 0.10, "max_dev_rate": 0.10,
            "max_sniper_wallets": 20, "max_fresh_wallet_rate": 0.6, "max_bundler_rate": 0.3,
            "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0,
            "max_fdv_to_liquidity": 50}


@pytest.mark.asyncio
async def test_clean_token_flows_to_recommended_signal():
    cli = GmgnCli(runner=make_runner(), rate_per_sec=1000, capacity=10, cache_ttl_sec=60)
    hf = HardFilter(cli=cli, cfg=_cfg())
    audit = AuditPipeline(
        gatherer=EvidenceGatherer(agent=StubAgent(), max_calls=5),
        judge=BullBearJudge(agent=StubAgent()),
    )
    orch = V2Orchestrator(hardfilter=hf, audit=audit)
    sig = await orch.process("CA", "LP", trace_id="t-e2e")
    assert sig is not None
    assert sig.recommended is True and sig.signal.value == "BULLISH"
    assert sig.trace_id == "t-e2e"
