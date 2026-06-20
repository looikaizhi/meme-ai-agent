"""LiteLLMProvider — delegates to litellm.acompletion."""
from __future__ import annotations

import litellm

from memedog.llm.provider import LLMMessage, LLMProviderError


class LiteLLMProvider:
    """Async LLM provider backed by litellm (supports many providers via prefixes)."""

    async def complete(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str:
        try:
            resp = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(f"LiteLLM call failed: {exc}") from exc
