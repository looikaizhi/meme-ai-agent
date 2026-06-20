"""Tests for structured JSON parsing + complete_structured (Task 4)."""
import pytest
from pydantic import BaseModel

from memedog.llm.provider import FakeProvider
from memedog.llm.structured import StructuredParseError, complete_structured, parse_json_into


# ---------------------------------------------------------------------------
# Minimal model for parse_json_into tests
# ---------------------------------------------------------------------------


class _Simple(BaseModel):
    x: int
    y: str


# ---------------------------------------------------------------------------
# parse_json_into — happy paths
# ---------------------------------------------------------------------------


def test_parse_json_into_clean_json():
    result = parse_json_into('{"x": 1, "y": "hello"}', _Simple)
    assert result.x == 1
    assert result.y == "hello"


def test_parse_json_into_code_fenced():
    text = '```json\n{"x": 2, "y": "world"}\n```'
    result = parse_json_into(text, _Simple)
    assert result.x == 2


def test_parse_json_into_prose_before_and_after():
    text = 'Here is the JSON:\n{"x": 3, "y": "ok"}\nEnd.'
    result = parse_json_into(text, _Simple)
    assert result.x == 3


def test_parse_json_into_code_fence_no_language():
    text = "```\n{\"x\": 4, \"y\": \"bare\"}\n```"
    result = parse_json_into(text, _Simple)
    assert result.x == 4


# ---------------------------------------------------------------------------
# parse_json_into — error paths
# ---------------------------------------------------------------------------


def test_parse_json_into_no_json_raises():
    with pytest.raises(StructuredParseError):
        parse_json_into("no json here", _Simple)


def test_parse_json_into_invalid_json_raises():
    with pytest.raises(StructuredParseError):
        parse_json_into("{x: 1}", _Simple)  # not valid JSON


def test_parse_json_into_wrong_schema_raises():
    with pytest.raises(StructuredParseError):
        parse_json_into('{"x": "not_an_int", "y": 123}', _Simple)


def test_parse_json_into_missing_field_raises():
    with pytest.raises(StructuredParseError):
        parse_json_into('{"x": 1}', _Simple)  # y is required


# ---------------------------------------------------------------------------
# complete_structured — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_structured_returns_parsed_model():
    fp = FakeProvider(['{"x": 10, "y": "done"}'])
    result = await complete_structured(
        provider=fp,
        model="m",
        messages=[{"role": "user", "content": "go"}],
        model_cls=_Simple,
    )
    assert result.x == 10
    assert result.y == "done"


# ---------------------------------------------------------------------------
# complete_structured — retry behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_structured_retries_on_bad_then_good():
    """First call returns bad JSON; second call (retry) returns valid JSON."""
    fp = FakeProvider(["not json at all", '{"x": 5, "y": "retry"}'])
    result = await complete_structured(
        provider=fp,
        model="m",
        messages=[{"role": "user", "content": "go"}],
        model_cls=_Simple,
        retries=1,
    )
    assert result.x == 5
    # Should have sent a corrective message on retry
    assert len(fp.calls) == 2
    # The second call messages should include the corrective user message
    second_call_msgs = fp.calls[1]["messages"]
    corrective = [m for m in second_call_msgs if m["role"] == "user"]
    assert any("JSON" in m["content"] or "json" in m["content"].lower() for m in corrective)


@pytest.mark.asyncio
async def test_complete_structured_exhausts_retries_raises():
    """All attempts return bad JSON → StructuredParseError after retries."""
    fp = FakeProvider(["bad", "also bad", "still bad"])
    with pytest.raises(StructuredParseError):
        await complete_structured(
            provider=fp,
            model="m",
            messages=[{"role": "user", "content": "go"}],
            model_cls=_Simple,
            retries=2,
        )


@pytest.mark.asyncio
async def test_complete_structured_zero_retries_raises_immediately():
    """With retries=0, a single bad response raises immediately."""
    fp = FakeProvider(["not json"])
    with pytest.raises(StructuredParseError):
        await complete_structured(
            provider=fp,
            model="m",
            messages=[{"role": "user", "content": "go"}],
            model_cls=_Simple,
            retries=0,
        )
