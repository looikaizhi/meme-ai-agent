"""LLM provider protocol, routing, and FakeProvider for testing.

Routing via make_provider:
  "codex:<model>"            -> (CodexCLIProvider(), "<model>")
  "codex:default"            -> (CodexCLIProvider(), "")
  "litellm:<provider>/<m>"   -> (LiteLLMProvider(), "<provider>/<m>")
  unknown / no prefix        -> raise LLMProviderError
"""
from __future__ import annotations

from typing import Any, Protocol, TypedDict


class LLMMessage(TypedDict):
    role: str
    content: str


class LLMProviderError(Exception):
    """Raised when an LLM provider call fails."""


class LLMProvider(Protocol):
    """Protocol satisfied by any LLM backend."""

    async def complete(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str: ...


class FakeProvider:
    """In-memory provider for tests.

    Accepts either:
    - A list of strings consumed in order (index 0, 1, 2, …).
    - A dict keyed by call index (0, 1, 2, …) mapping to response strings.

    Records every call to ``self.calls`` as a dict with keys:
    model, messages, temperature, max_tokens.

    Raises IndexError / KeyError when responses are exhausted.
    """

    def __init__(self, responses: list[str] | dict[int, str]) -> None:
        self._responses: list[str] | dict[int, str] = responses
        self._call_count: int = 0
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        idx = self._call_count
        self._call_count += 1
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if isinstance(self._responses, dict):
            if idx not in self._responses:
                raise IndexError(f"FakeProvider: no response for call index {idx}")
            return self._responses[idx]
        else:
            if idx >= len(self._responses):
                raise IndexError(
                    f"FakeProvider: responses exhausted (call {idx}, have {len(self._responses)})"
                )
            return self._responses[idx]


def make_provider(
    model_str: str,
    codex: LLMProvider | None = None,
    litellm: LLMProvider | None = None,
) -> tuple[LLMProvider, str]:
    """Route *model_str* to a (provider_instance, model_name) tuple.

    Parameters
    ----------
    model_str:
        One of ``"codex:<model>"``, ``"codex:default"``,
        ``"litellm:<provider>/<model>"``.
    codex:
        Optional injected CodexCLIProvider (for DI / testing).
    litellm:
        Optional injected LiteLLMProvider (for DI / testing).
    """
    if model_str.startswith("codex:"):
        suffix = model_str[len("codex:"):]
        model_name = "" if suffix == "default" else suffix
        if codex is not None:
            return (codex, model_name)
        from memedog.llm.codex_provider import CodexCLIProvider  # lazy import
        return (CodexCLIProvider(), model_name)

    if model_str.startswith("litellm:"):
        model_name = model_str[len("litellm:"):]
        if litellm is not None:
            return (litellm, model_name)
        from memedog.llm.litellm_provider import LiteLLMProvider  # lazy import
        return (LiteLLMProvider(), model_name)

    raise LLMProviderError(
        f"Unknown provider prefix in model string: {model_str!r}. "
        "Expected 'codex:<model>', 'codex:default', or 'litellm:<provider>/<model>'."
    )
