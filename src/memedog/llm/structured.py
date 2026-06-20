"""Structured JSON output parsing + retry wrapper for LLM providers."""
from __future__ import annotations

import json
import re
from typing import Any, Type, TypeVar

from memedog.llm.provider import LLMMessage, LLMProvider

T = TypeVar("T")


class StructuredParseError(Exception):
    """Raised when LLM output cannot be parsed into the target model."""


# Regex to match the first balanced JSON object in a string.
# We walk character-by-character for balance, but use a regex to find start.
_JSON_START = re.compile(r"\{")


def _strip_code_fence(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` fences if present."""
    # Strip ```json...``` or ```...```
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text.strip(), flags=re.IGNORECASE)
    return text.strip()


def _extract_first_json_object(text: str) -> str:
    """Find and extract the first balanced {...} object from *text*."""
    start = _JSON_START.search(text)
    if start is None:
        raise StructuredParseError(f"No JSON object found in text: {text[:200]!r}")

    depth = 0
    in_string = False
    escape_next = False
    i = start.start()

    for j in range(i, len(text)):
        ch = text[j]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[i : j + 1]

    raise StructuredParseError(
        f"Unbalanced JSON braces in text: {text[:200]!r}"
    )


def parse_json_into(text: str, model_cls: Type[T]) -> T:
    """Parse *text* into *model_cls* (a Pydantic BaseModel subclass).

    Strips ```json code fences and surrounding prose before parsing.
    Raises StructuredParseError on any failure.
    """
    try:
        # First try stripping code fences then extracting JSON
        cleaned = _strip_code_fence(text)
        json_str = _extract_first_json_object(cleaned)
    except StructuredParseError:
        # Fallback: search the original text
        try:
            json_str = _extract_first_json_object(text)
        except StructuredParseError as exc:
            raise StructuredParseError(str(exc)) from exc

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise StructuredParseError(f"JSON decode error: {exc}") from exc

    try:
        return model_cls.model_validate(data)  # type: ignore[attr-defined]
    except Exception as exc:
        raise StructuredParseError(f"Schema validation failed: {exc}") from exc


_CORRECTIVE_MSG: LLMMessage = {
    "role": "user",
    "content": (
        "Your previous output was not valid JSON. "
        "Return ONLY a valid JSON object matching the schema. "
        "Do not include any explanation, prose, or code fences."
    ),
}


async def complete_structured(
    provider: LLMProvider,
    model: str,
    messages: list[LLMMessage],
    model_cls: Type[T],
    temperature: float = 0.3,
    max_tokens: int = 1024,
    retries: int = 1,
) -> T:
    """Call *provider.complete* and parse the result into *model_cls*.

    On StructuredParseError, append a corrective user message and retry up to
    *retries* additional times. Raises StructuredParseError if still failing.
    """
    current_messages = list(messages)
    last_exc: StructuredParseError | None = None

    for attempt in range(retries + 1):
        text = await provider.complete(
            model=model,
            messages=current_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            return parse_json_into(text, model_cls)
        except StructuredParseError as exc:
            last_exc = exc
            if attempt < retries:
                # Append the LLM's bad response as an assistant turn, then corrective msg
                current_messages = current_messages + [
                    {"role": "assistant", "content": text},
                    _CORRECTIVE_MSG,
                ]

    assert last_exc is not None  # always set if we reach here
    raise last_exc
