import pytest
from memedogV2.harness.model_registry import FakeBackend, build_backend


@pytest.mark.asyncio
async def test_fake_backend_returns_scripted_and_records():
    be = FakeBackend(responses={"bull": {"thesis": "x", "points": []}})
    out, rec = await be.complete(role="bull", prompt="p", schema={"type": "object"})
    assert out == {"thesis": "x", "points": []}
    assert rec.backend == "fake" and rec.role == "bull" and rec.schema_valid is True


@pytest.mark.asyncio
async def test_fake_backend_marks_schema_invalid_on_missing_key():
    be = FakeBackend(responses={"bull": {"points": []}})
    out, rec = await be.complete(
        role="bull", prompt="p",
        schema={"type": "object", "required": ["thesis"], "properties": {"thesis": {}}})
    assert rec.schema_valid is False


def test_build_backend_selects_by_name():
    assert build_backend("fake").name == "fake"
    assert build_backend("deepseek").name == "deepseek"
    assert build_backend("codex").name == "codex"
