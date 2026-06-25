from __future__ import annotations

import json
import os
import time
from typing import Any, Optional, Protocol

from memedogV2.harness.contracts import ModelCallRecord


def _schema_valid(obj: Any, schema: dict) -> bool:
    """Lightweight check: object + all required keys present. (Not full JSON-Schema.)"""
    if not isinstance(obj, dict):
        return False
    return all(k in obj for k in schema.get("required", []))


class ModelBackend(Protocol):
    name: str
    async def complete(self, *, role: str, prompt: str,
                       schema: dict) -> tuple[dict, ModelCallRecord]: ...


class FakeBackend:
    """Scripted backend for unit tests — no network."""
    name = "fake"

    def __init__(self, *, responses: dict[str, dict]) -> None:
        self._responses = responses

    async def complete(self, *, role, prompt, schema):
        obj = self._responses[role]
        rec = ModelCallRecord(backend=self.name, role=role,
                              schema_valid=_schema_valid(obj, schema))
        return obj, rec


class DeepSeekBackend:
    """DeepSeek via OpenAI-compatible API. json_object mode + one repair retry."""
    name = "deepseek"

    def __init__(self, *, model: str = "deepseek-chat",
                 base_url: str = "https://api.deepseek.com") -> None:
        self._model = model
        self._base_url = base_url

    def _client(self):
        from openai import AsyncOpenAI
        return AsyncOpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=self._base_url)

    async def complete(self, *, role, prompt, schema):
        client = self._client()
        sys = ("Return ONLY a JSON object that matches this schema (keys and types). "
               f"Schema: {json.dumps(schema)}")
        t0 = time.perf_counter()
        obj = await self._one(client, sys, prompt)
        if not _schema_valid(obj, schema):
            obj = await self._one(client, sys + " You MUST include all required keys.", prompt)
        dur = (time.perf_counter() - t0) * 1000.0
        rec = ModelCallRecord(backend=self.name, role=role,
                              schema_valid=_schema_valid(obj, schema), duration_ms=dur)
        return obj, rec

    async def _one(self, client, sys: str, prompt: str) -> dict:
        resp = await client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": sys},
                      {"role": "user", "content": prompt}],
        )
        try:
            return json.loads(resp.choices[0].message.content)
        except (json.JSONDecodeError, TypeError):
            return {}


class CodexBackend:
    """Codex via the existing strict-schema CodexAgent."""
    name = "codex"

    def __init__(self, *, cwd: Optional[str] = None) -> None:
        from memedogV2.llm.codex_agent import CodexAgent
        self._agent = CodexAgent(cwd=cwd or os.getcwd())

    async def complete(self, *, role, prompt, schema):
        t0 = time.perf_counter()
        obj = await self._agent.run(prompt=prompt, schema=schema)
        dur = (time.perf_counter() - t0) * 1000.0
        rec = ModelCallRecord(backend=self.name, role=role,
                              schema_valid=_schema_valid(obj, schema), duration_ms=dur)
        return obj, rec


def build_backend(name: str, **kwargs) -> ModelBackend:
    name = name.lower()
    if name == "fake":
        return FakeBackend(responses=kwargs.get("responses", {}))
    if name == "deepseek":
        return DeepSeekBackend(**{k: v for k, v in kwargs.items() if k in ("model", "base_url")})
    if name == "codex":
        return CodexBackend(**{k: v for k, v in kwargs.items() if k in ("cwd",)})
    raise ValueError(f"unknown backend: {name}")
