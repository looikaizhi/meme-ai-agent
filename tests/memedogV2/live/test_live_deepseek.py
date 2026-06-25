import os
import pytest
from memedogV2.harness.model_registry import DeepSeekBackend
from memedogV2.audit import prompts
from memedogV2.models.contracts import EvidenceBundle

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_real_deepseek_judge_returns_valid_structure():
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set")
    be = DeepSeekBackend()
    bundle = EvidenceBundle(ca_address="CA", smart_money_count=200, kol_holder_count=50,
                            missing=["dev_graduation_rate"])
    verdict, rec = await be.complete(
        role="judge",
        prompt=prompts.judge_prompt(bundle, bull={"thesis": "hot", "points": []},
                                    bear={"thesis": "risk", "points": []}),
        schema=prompts.JUDGE_SCHEMA)
    assert rec.schema_valid is True
    assert verdict["signal"] in ("BULLISH", "BEARISH", "NEUTRAL")
    assert isinstance(verdict["recommended"], bool)
