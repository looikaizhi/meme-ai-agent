import shutil
import pytest
from memedogV2.harness.model_registry import CodexBackend
from memedogV2.audit import prompts
from memedogV2.models.contracts import EvidenceBundle

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_real_codex_judge_returns_valid_structure():
    if shutil.which("codex") is None:
        pytest.skip("codex not installed")
    be = CodexBackend()
    bundle = EvidenceBundle(ca_address="CA", smart_money_count=200, missing=[])
    verdict, rec = await be.complete(
        role="judge",
        prompt=prompts.judge_prompt(bundle, bull={"thesis": "hot", "points": []},
                                    bear={"thesis": "risk", "points": []}),
        schema=prompts.JUDGE_SCHEMA)
    assert rec.schema_valid is True
    assert verdict["signal"] in ("BULLISH", "BEARISH", "NEUTRAL")
