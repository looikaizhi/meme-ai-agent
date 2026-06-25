import shutil
import pytest
from memedogV2.harness.model_registry import CodexBackend
from memedogV2.audit import prompts
from memedogV2.sources.base import Facts

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_real_codex_judge_returns_detailed_report():
    if shutil.which("codex") is None:
        pytest.skip("codex not installed")
    be = CodexBackend()
    facts = Facts(mint_revoked=True, lp_safe=True, liquidity_usd=57000,
                  smart_money_count=200, dev_created_count=3)
    sources = {"mint_revoked": "rugcheck", "lp_safe": "rugcheck", "liquidity_usd": "gmgn",
               "smart_money_count": "gmgn"}
    verdict, rec = await be.complete(
        role="judge",
        prompt=prompts.judge_prompt(facts, sources, [],
                                    bull={"thesis": "hot", "points": []},
                                    bear={"thesis": "risk", "points": []}),
        schema=prompts.JUDGE_SCHEMA)
    assert rec.schema_valid is True
    assert verdict["signal"] in ("BULLISH", "BEARISH", "NEUTRAL")
    assert verdict["summary"]
