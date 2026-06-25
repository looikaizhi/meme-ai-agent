import os
import pytest
from memedogV2.harness.model_registry import DeepSeekBackend
from memedogV2.audit import prompts
from memedogV2.sources.base import Facts

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_real_deepseek_judge_returns_detailed_report():
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set")
    be = DeepSeekBackend()
    facts = Facts(mint_revoked=True, lp_safe=True, top10_rate=0.27, liquidity_usd=57000,
                  volume_5m=12000, buys_5m=83, sells_5m=40, smart_money_count=52,
                  kol_count=6, dev_created_count=69, historical_ath=243000000)
    sources = {"mint_revoked": "rugcheck", "lp_safe": "rugcheck", "liquidity_usd": "gmgn",
               "smart_money_count": "gmgn", "dev_created_count": "gmgn"}
    verdict, rec = await be.complete(
        role="judge",
        prompt=prompts.judge_prompt(facts, sources, ["dev_graduation_rate"],
                                    bull={"thesis": "hot", "points": ["52 smart money"]},
                                    bear={"thesis": "risk", "points": ["dev made 69 tokens"]}),
        schema=prompts.JUDGE_SCHEMA)
    assert rec.schema_valid is True
    assert verdict["signal"] in ("BULLISH", "BEARISH", "NEUTRAL")
    assert isinstance(verdict["recommended"], bool)
    # detailed report present
    assert verdict["summary"]
    assert isinstance(verdict["strengths"], list) and isinstance(verdict["risks"], list)
    assert isinstance(verdict["key_metrics"], list)
