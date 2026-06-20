"""Tests for LLMProvider protocol and make_provider routing (Task 1 + Task 3)."""
import pytest
import pytest_asyncio

from memedog.llm.provider import (
    FakeProvider,
    LLMProviderError,
    make_provider,
)


# ---------------------------------------------------------------------------
# Task 1 — make_provider routing
# ---------------------------------------------------------------------------


def test_make_provider_codex_named_model_returns_codex_provider():
    from memedog.llm.codex_provider import CodexCLIProvider

    provider, model = make_provider("codex:gpt-5-codex")
    assert isinstance(provider, CodexCLIProvider)
    assert model == "gpt-5-codex"


def test_make_provider_codex_default_returns_empty_model():
    from memedog.llm.codex_provider import CodexCLIProvider

    provider, model = make_provider("codex:default")
    assert isinstance(provider, CodexCLIProvider)
    assert model == ""


def test_make_provider_litellm_returns_litellm_provider():
    from memedog.llm.litellm_provider import LiteLLMProvider

    provider, model = make_provider("litellm:openai/gpt-4o")
    assert isinstance(provider, LiteLLMProvider)
    assert model == "openai/gpt-4o"


def test_make_provider_unknown_prefix_raises():
    with pytest.raises(LLMProviderError):
        make_provider("openai:gpt-4o")


def test_make_provider_no_prefix_raises():
    with pytest.raises(LLMProviderError):
        make_provider("gpt-4o")


# ---------------------------------------------------------------------------
# Task 1 — dependency injection for testing
# ---------------------------------------------------------------------------


def test_make_provider_injected_codex_instance():
    fake = FakeProvider(["hello"])
    provider, model = make_provider("codex:mymodel", codex=fake)
    assert provider is fake
    assert model == "mymodel"


def test_make_provider_injected_litellm_instance():
    fake = FakeProvider(["hello"])
    provider, model = make_provider("litellm:openai/gpt-4o", litellm=fake)
    assert provider is fake
    assert model == "openai/gpt-4o"


# ---------------------------------------------------------------------------
# Task 1 — FakeProvider behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_provider_list_returns_in_order():
    fp = FakeProvider(["first", "second", "third"])
    r1 = await fp.complete(model="m", messages=[])
    r2 = await fp.complete(model="m", messages=[])
    r3 = await fp.complete(model="m", messages=[])
    assert r1 == "first"
    assert r2 == "second"
    assert r3 == "third"


@pytest.mark.asyncio
async def test_fake_provider_records_calls():
    fp = FakeProvider(["ok"])
    msgs = [{"role": "user", "content": "hi"}]
    await fp.complete(model="x", messages=msgs, temperature=0.7)
    assert len(fp.calls) == 1
    assert fp.calls[0]["model"] == "x"
    assert fp.calls[0]["messages"] == msgs
    assert fp.calls[0]["temperature"] == 0.7


@pytest.mark.asyncio
async def test_fake_provider_dict_keyed_by_index():
    fp = FakeProvider({0: "zero", 1: "one"})
    r0 = await fp.complete(model="m", messages=[])
    r1 = await fp.complete(model="m", messages=[])
    assert r0 == "zero"
    assert r1 == "one"


@pytest.mark.asyncio
async def test_fake_provider_exhausted_raises():
    fp = FakeProvider(["only_one"])
    await fp.complete(model="m", messages=[])
    with pytest.raises(Exception):
        await fp.complete(model="m", messages=[])


# ---------------------------------------------------------------------------
# Task 3 — LiteLLMProvider (mocked litellm.acompletion)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_litellm_provider_returns_content(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock
    import litellm
    from memedog.llm.litellm_provider import LiteLLMProvider

    # Build a fake response object: resp.choices[0].message.content
    fake_msg = MagicMock()
    fake_msg.content = "hi from litellm"
    fake_choice = MagicMock()
    fake_choice.message = fake_msg
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]

    mock_acompletion = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    p = LiteLLMProvider()
    result = await p.complete(
        model="openai/gpt-4o",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.3,
        max_tokens=256,
    )
    assert result == "hi from litellm"
    mock_acompletion.assert_called_once()


@pytest.mark.asyncio
async def test_litellm_provider_wraps_exception(monkeypatch):
    from unittest.mock import AsyncMock
    import litellm
    from memedog.llm.litellm_provider import LiteLLMProvider
    from memedog.llm.provider import LLMProviderError

    monkeypatch.setattr(litellm, "acompletion", AsyncMock(side_effect=RuntimeError("net error")))
    p = LiteLLMProvider()
    with pytest.raises(LLMProviderError):
        await p.complete(model="openai/gpt-4o", messages=[])
