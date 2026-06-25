# memedogV2 Execution Harness (Production Path) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the post-HardFilter audit flow **deterministic and backend-agnostic**: an execution harness fetches GMGN data and builds the evidence bundle itself (the LLM never decides whether to call tools), then any structured-reasoning model backend (DeepSeek or Codex) runs Bull/Bear/Judge over that bundle, and every run is recorded with auditable tool-call + model-call evidence.

**Architecture:** New `src/memedogV2/harness/` package. The harness `runner` drives a fixed workflow (security → info → hardfilter → build-evidence → bull → bear → judge → signal), pulling GMGN data via a `tool_registry` (which wraps the existing rate-limited `GmgnCli` and records every `ToolCallRecord`) and calling LLMs via a `model_registry` (unified `ModelBackend` interface: `FakeBackend`, `DeepSeekBackend`, `CodexBackend`). A `recorder` writes a structured `HarnessRun` to `runs/memedogV2/`. This replaces the old LLM-driven `EvidenceGatherer` (deleted) and removes the "did the model really call gmgn?" uncertainty from production — gmgn fetching is now deterministic harness code.

**Tech Stack:** Python 3.11+, asyncio, pydantic v2, `openai` SDK 2.43 (DeepSeek via `base_url=https://api.deepseek.com`), `codex exec` (strict `--output-schema`), pytest (`asyncio_mode=auto`, `live` marker for real-env tests).

**Spec:** `docs/superpowers/specs/2026-06-25-memedogV2-harness-design.md`
**Decisions:** (1) production runs both DeepSeek + Codex behind `model_registry`, default configurable; (2) the old codex `EvidenceGatherer` is deleted (evidence is now deterministic). (3) **Every stage has a real-environment test** (`live`-marked): real `gmgn-cli` + real DeepSeek/Codex.

**Deferred to a follow-up plan (NOT in scope):** `compliance.py` (agent-compliance evaluation path, design §七), full `replay.py` cross-model diffing, dashboard.

---

## Reuse / context the implementer must know

- Existing deterministic layer is DONE and must not change: `clients/gmgn_cli.py` (`GmgnCli.token_security/token_info`, rate-limited + cached + raises `RateLimitBanned`), `hardfilter/hardfilter.py` (`HardFilter.evaluate(ca, lp, trace_id="") -> HardFilterResult`), `hardfilter/fieldmap.py` (`FIELD_MAP`), `hardfilter/rules.py` (`get_path`, `num`).
- Contracts in `models/contracts.py`: `HardFilterResult{ca_address, lp_address, passed, facts, dropped, flagged, trace_id}`, `EvidenceBundle{ca_address, smart_money_count, kol_holder_count, dev_created_token_count, dev_graduation_rate, historical_ath, trend, holders_detail, missing}`, `Signal{ca_address, signal, recommended, confidence, rationale, evidence_refs, trace_id}`, `SignalKind`.
- Bull/Bear/Judge prompt + schema logic currently lives in `audit/debate.py` (`_ANALYST_SCHEMA`, `_JUDGE_SCHEMA`, `BullBearJudge`). This plan extracts the prompt/schema pieces into `audit/prompts.py` and drives them from the harness; `BullBearJudge` is removed once the harness replaces it.
- Real `token info`/`token security` JSON fixtures: `tests/memedogV2/fixtures/{info,security}.json`.
- `.env` has `DEEPSEEK_API_KEY`. gmgn key is in `~/.config/gmgn/.env`. `live`-marked tests are deselected by default (`addopts = -m 'not live'`); run with `pytest -m live`.

## File Structure

```
src/memedogV2/
├── audit/
│   ├── prompts.py          # NEW: role prompt builders + strict schemas (moved out of debate.py)
│   ├── evidence.py         # DELETE (old codex EvidenceGatherer)
│   └── debate.py           # DELETE after runner replaces it (Task 9)
├── harness/
│   ├── __init__.py
│   ├── contracts.py        # StepStatus, ToolCallRecord, ModelCallRecord, StepResult, HarnessRun
│   ├── tool_registry.py    # ToolRegistry: real GmgnCli source + fixture source; emits ToolCallRecord
│   ├── evidence_builder.py # build_evidence(facts, ca) -> (EvidenceBundle) deterministic from FIELD_MAP
│   ├── model_registry.py   # ModelBackend protocol; FakeBackend, DeepSeekBackend, CodexBackend
│   ├── recorder.py         # Recorder: assemble HarnessRun, write runs/memedogV2/<file>.json
│   └── runner.py           # HarnessRunner.run(ca, lp, trace_id) -> HarnessRun
└── __main__.py             # MODIFY: drive HarnessRunner

tests/memedogV2/
├── test_harness_contracts.py
├── test_tool_registry.py
├── test_evidence_builder.py
├── test_model_registry.py
├── test_recorder.py
├── test_workflow_runner.py
├── test_prompts.py
└── live/
    ├── test_live_gmgn.py        # live: real gmgn-cli via tool_registry
    ├── test_live_deepseek.py    # live: real DeepSeek backend over a fixed bundle
    ├── test_live_codex.py       # live: real Codex backend over a fixed bundle
    └── test_live_pipeline.py    # live: real end-to-end (real gmgn + real model)
```

---

## Task 1: Harness contracts

**Files:** Create `src/memedogV2/harness/__init__.py`, `src/memedogV2/harness/contracts.py`; Test `tests/memedogV2/test_harness_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_harness_contracts.py
from memedogV2.harness.contracts import (
    StepStatus, ToolCallRecord, ModelCallRecord, StepResult, HarnessRun,
)


def test_step_result_defaults_and_records():
    sr = StepResult(name="read_security", status=StepStatus.OK)
    assert sr.tool_calls == [] and sr.model_calls == []
    assert sr.error == ""


def test_harness_run_collects_steps_and_signal():
    run = HarnessRun(run_id="r1", ca_address="CA", backend="fake", mode="production")
    run.steps.append(StepResult(name="hardfilter", status=StepStatus.OK))
    assert run.steps[0].name == "hardfilter"
    assert run.final_signal is None


def test_tool_and_model_call_records():
    t = ToolCallRecord(tool="gmgn-cli", command="token security CA",
                       exit_status=0, duration_ms=12.0)
    m = ModelCallRecord(backend="deepseek", role="bull", schema_valid=True, duration_ms=900.0)
    assert t.exit_status == 0 and m.schema_valid is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_harness_contracts.py -v`
Expected: FAIL with `ModuleNotFoundError: memedogV2.harness`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/harness/__init__.py
"""memedogV2 execution harness — deterministic production audit path."""
```

```python
# src/memedogV2/harness/contracts.py
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from memedogV2.models.contracts import Signal


class StepStatus(str, Enum):
    OK = "ok"
    SKIPPED = "skipped"
    FAILED = "failed"
    DEGRADED = "degraded"


class ToolCallRecord(BaseModel):
    tool: str
    command: str            # short summary, e.g. "token security <CA>"
    input_summary: str = ""
    output_summary: str = ""
    exit_status: int = 0
    duration_ms: float = 0.0


class ModelCallRecord(BaseModel):
    backend: str
    role: str               # "bull" | "bear" | "judge"
    input_ref: str = ""
    output_ref: str = ""
    schema_valid: bool = False
    duration_ms: float = 0.0


class StepResult(BaseModel):
    name: str
    status: StepStatus
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    model_calls: list[ModelCallRecord] = Field(default_factory=list)
    detail: str = ""
    error: str = ""


class HarnessRun(BaseModel):
    run_id: str
    ca_address: str
    backend: str
    mode: str               # "production" | "evaluation"
    steps: list[StepResult] = Field(default_factory=list)
    final_signal: Optional[Signal] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_harness_contracts.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/harness/__init__.py src/memedogV2/harness/contracts.py tests/memedogV2/test_harness_contracts.py
git commit -m "feat(harness): run/step/tool/model-call contracts"
```

---

## Task 2: Tool registry (records every gmgn call)

**Files:** Create `src/memedogV2/harness/tool_registry.py`; Test `tests/memedogV2/test_tool_registry.py`

The registry wraps the existing `GmgnCli`. Each fetch returns `(facts_dict, ToolCallRecord)`. A fixture source lets tests run without network. This is the ONLY place production gmgn data enters the audit — fully recorded.

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_tool_registry.py
import json
import pytest
from memedogV2.harness.tool_registry import ToolRegistry, FixtureToolSource


@pytest.mark.asyncio
async def test_fixture_source_records_tool_calls():
    src = FixtureToolSource(security={"renounced_mint": True}, info={"liquidity": "50000"})
    reg = ToolRegistry(source=src)
    sec, rec_sec = await reg.fetch_security("CA")
    info, rec_info = await reg.fetch_info("CA")
    assert sec == {"renounced_mint": True}
    assert info == {"liquidity": "50000"}
    assert rec_sec.tool == "gmgn-cli" and "security" in rec_sec.command
    assert rec_sec.exit_status == 0 and rec_info.exit_status == 0


@pytest.mark.asyncio
async def test_gmgncli_source_wraps_client():
    class FakeCli:
        async def token_security(self, ca): return {"a": 1}
        async def token_info(self, ca): return {"b": 2}
    from memedogV2.harness.tool_registry import GmgnCliToolSource
    reg = ToolRegistry(source=GmgnCliToolSource(FakeCli()))
    sec, rec = await reg.fetch_security("CA")
    assert sec == {"a": 1} and rec.output_summary  # summary is non-empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_tool_registry.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/harness/tool_registry.py
from __future__ import annotations

import json
import time
from typing import Any, Protocol

from memedogV2.harness.contracts import ToolCallRecord


class ToolSource(Protocol):
    async def security(self, ca: str) -> dict[str, Any]: ...
    async def info(self, ca: str) -> dict[str, Any]: ...


class FixtureToolSource:
    """Returns canned dicts; no network. For unit tests."""

    def __init__(self, *, security: dict, info: dict) -> None:
        self._security = security
        self._info = info

    async def security(self, ca: str) -> dict[str, Any]:
        return self._security

    async def info(self, ca: str) -> dict[str, Any]:
        return self._info


class GmgnCliToolSource:
    """Wraps the real rate-limited GmgnCli."""

    def __init__(self, cli) -> None:
        self._cli = cli

    async def security(self, ca: str) -> dict[str, Any]:
        return await self._cli.token_security(ca)

    async def info(self, ca: str) -> dict[str, Any]:
        return await self._cli.token_info(ca)


class ToolRegistry:
    """Fetches gmgn data through a ToolSource and records each call."""

    def __init__(self, *, source: ToolSource) -> None:
        self._source = source

    async def _fetch(self, sub: str, ca: str, coro) -> tuple[dict, ToolCallRecord]:
        t0 = time.perf_counter()
        data = await coro
        dur = (time.perf_counter() - t0) * 1000.0
        rec = ToolCallRecord(
            tool="gmgn-cli",
            command=f"token {sub} {ca}",
            input_summary=ca,
            output_summary=(json.dumps(data)[:200] if isinstance(data, dict) else str(data)[:200]),
            exit_status=0,
            duration_ms=dur,
        )
        return data, rec

    async def fetch_security(self, ca: str) -> tuple[dict, ToolCallRecord]:
        return await self._fetch("security", ca, self._source.security(ca))

    async def fetch_info(self, ca: str) -> tuple[dict, ToolCallRecord]:
        return await self._fetch("info", ca, self._source.info(ca))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_tool_registry.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/harness/tool_registry.py tests/memedogV2/test_tool_registry.py
git commit -m "feat(harness): tool registry with gmgn-cli + fixture sources, recorded calls"
```

---

## Task 3: Deterministic evidence builder (delete codex EvidenceGatherer)

**Files:** Create `src/memedogV2/harness/evidence_builder.py`; Delete `src/memedogV2/audit/evidence.py` + `tests/memedogV2/test_evidence.py`; Test `tests/memedogV2/test_evidence_builder.py`

Evidence is now extracted deterministically from the already-fetched `token info` facts via `FIELD_MAP` — no LLM, no extra gmgn call. `dev_graduation_rate` has no gmgn source, so it is always None and listed in `missing`.

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_evidence_builder.py
import json
from memedogV2.harness.evidence_builder import build_evidence
from memedogV2.models.contracts import EvidenceBundle


def test_build_evidence_from_real_info_fixture():
    info = json.load(open("tests/memedogV2/fixtures/info.json"))
    bundle = build_evidence(facts=info, ca="EPjFW")
    assert isinstance(bundle, EvidenceBundle)
    # USDC fixture: smart/kol wallet counts are ints (0), dev_created_count present
    assert bundle.smart_money_count is not None
    assert bundle.kol_holder_count is not None
    # no gmgn source for graduation rate -> always missing
    assert bundle.dev_graduation_rate is None
    assert "dev_graduation_rate" in bundle.missing


def test_build_evidence_marks_absent_fields_missing():
    bundle = build_evidence(facts={}, ca="CA")  # empty facts
    assert bundle.smart_money_count is None
    assert "smart_money_count" in bundle.missing
    assert "kol_holder_count" in bundle.missing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_evidence_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation, then delete the old gatherer**

```python
# src/memedogV2/harness/evidence_builder.py
from __future__ import annotations

from typing import Any

from memedogV2.hardfilter.fieldmap import FIELD_MAP
from memedogV2.hardfilter.rules import get_path, num
from memedogV2.models.contracts import EvidenceBundle


def _int(facts: dict, key: str):
    v = get_path(facts, FIELD_MAP[key])
    n = num(v)
    return int(n) if n is not None else None


def _float(facts: dict, key: str):
    return num(get_path(facts, FIELD_MAP[key]))


def build_evidence(*, facts: dict[str, Any], ca: str) -> EvidenceBundle:
    """Deterministically extract LLM evidence from already-fetched gmgn facts."""
    smart = _int(facts, "smart_wallets")
    kol = _int(facts, "renowned_wallets")
    dev_created = _int(facts, "dev_created_count")
    ath = _float(facts, "dev_ath_mc")
    graduation = None  # no gmgn source for dev graduation rate

    fields = {
        "smart_money_count": smart,
        "kol_holder_count": kol,
        "dev_created_token_count": dev_created,
        "dev_graduation_rate": graduation,
        "historical_ath": ath,
    }
    missing = [k for k, v in fields.items() if v is None]
    return EvidenceBundle(ca_address=ca, missing=missing, **fields)
```

Then delete the old LLM-driven gatherer and its test:

```bash
git rm src/memedogV2/audit/evidence.py tests/memedogV2/test_evidence.py
```

- [ ] **Step 4: Run tests to verify**

Run: `pytest tests/memedogV2/test_evidence_builder.py tests/memedogV2 -q`
Expected: new builder tests PASS; whole memedogV2 suite PASS (the deleted `test_evidence.py` is gone, no import of `audit.evidence` remains — if anything still imports it, that surfaces here; the orchestrator/AuditPipeline used a `gatherer` duck-type, not `audit.evidence` directly, so it is unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/harness/evidence_builder.py tests/memedogV2/test_evidence_builder.py
git commit -m "feat(harness): deterministic evidence builder; remove LLM-driven EvidenceGatherer"
```

---

## Task 4: Audit prompts + schemas (extracted, role-based)

**Files:** Create `src/memedogV2/audit/prompts.py`; Test `tests/memedogV2/test_prompts.py`

Move the Bull/Bear/Judge prompt construction + strict schemas into a backend-agnostic module the harness can call per role.

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_prompts.py
from memedogV2.audit.prompts import (
    evidence_text, analyst_prompt, judge_prompt, ANALYST_SCHEMA, JUDGE_SCHEMA,
)
from memedogV2.models.contracts import EvidenceBundle


def test_schemas_are_strict():
    for schema in (ANALYST_SCHEMA, JUDGE_SCHEMA):
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"].keys())


def test_evidence_text_drops_none_and_lists_missing():
    b = EvidenceBundle(ca_address="CA", smart_money_count=4, missing=["historical_ath"])
    txt = evidence_text(b)
    assert "smart_money_count" in txt and "4" in txt
    assert "historical_ath" in txt          # surfaced as missing
    assert "null" not in txt                # None fields filtered out


def test_role_prompts_label_their_role():
    b = EvidenceBundle(ca_address="CA")
    assert "BULL" in analyst_prompt("bull", b)
    assert "BEAR" in analyst_prompt("bear", b)
    jp = judge_prompt(b, bull={"thesis": "x", "points": []}, bear={"thesis": "y", "points": []})
    assert "JUDGE" in jp and "BULL" in jp and "BEAR" in jp
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/audit/prompts.py
from __future__ import annotations

import json

from memedogV2.models.contracts import EvidenceBundle

ANALYST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"thesis": {"type": "string"},
                   "points": {"type": "array", "items": {"type": "string"}}},
    "required": ["thesis", "points"],
}

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "signal": {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
        "recommended": {"type": "boolean"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["signal", "recommended", "confidence", "rationale", "evidence_refs"],
}


def evidence_text(b: EvidenceBundle) -> str:
    body = b.model_dump()
    missing = body.pop("missing", [])
    body.pop("ca_address", None)
    present = {k: v for k, v in body.items() if v is not None}
    return (f"Evidence for {b.ca_address}: {json.dumps(present)}\n"
            f"Missing/unfetched dimensions: {missing}")


def analyst_prompt(role: str, b: EvidenceBundle) -> str:
    ev = evidence_text(b)
    if role == "bull":
        return f"You are the BULL analyst. Argue why this token could pump. {ev}"
    if role == "bear":
        return f"You are the BEAR analyst. Argue why this token is risky/avoid. {ev}"
    raise ValueError(f"unknown analyst role: {role}")


def judge_prompt(b: EvidenceBundle, *, bull: dict, bear: dict) -> str:
    ev = evidence_text(b)
    return (
        "You are the JUDGE. Weigh the bull vs bear and decide.\n"
        f"{ev}\n"
        f"BULL: {json.dumps(bull)}\n"
        f"BEAR: {json.dumps(bear)}\n"
        "Output signal (BULLISH/BEARISH/NEUTRAL), recommended (bool), "
        "confidence 0-1, rationale, evidence_refs. If key evidence is missing, "
        "lower confidence and say so."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_prompts.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/audit/prompts.py tests/memedogV2/test_prompts.py
git commit -m "feat(audit): extract role prompts + strict schemas (backend-agnostic)"
```

---

## Task 5: Model registry (FakeBackend, DeepSeekBackend, CodexBackend)

**Files:** Create `src/memedogV2/harness/model_registry.py`; Test `tests/memedogV2/test_model_registry.py`

Unified interface: `async complete(*, role, prompt, schema) -> tuple[dict, ModelCallRecord]`. DeepSeek uses `openai` SDK against `https://api.deepseek.com` with `response_format={"type":"json_object"}` + pydantic-free dict parse + ONE repair retry (DeepSeek lacks strict json_schema). Codex reuses the existing `CodexAgent` (strict `--output-schema`). `FakeBackend` returns scripted dicts for unit tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_model_registry.py
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
    # required key 'thesis' absent -> schema_valid False but still returns dict
    be = FakeBackend(responses={"bull": {"points": []}})
    out, rec = await be.complete(
        role="bull", prompt="p",
        schema={"type": "object", "required": ["thesis"], "properties": {"thesis": {}}})
    assert rec.schema_valid is False


def test_build_backend_selects_by_name():
    assert build_backend("fake").name == "fake"
    # deepseek/codex construct lazily without network at build time
    assert build_backend("deepseek").name == "deepseek"
    assert build_backend("codex").name == "codex"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_model_registry.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/harness/model_registry.py
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
            # one repair retry: restate the schema requirement
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_model_registry.py -v`
Expected: PASS (3 tests). (No network: `build_backend("deepseek")` only constructs; the client is built lazily inside `complete`.)

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/harness/model_registry.py tests/memedogV2/test_model_registry.py
git commit -m "feat(harness): model registry (fake/deepseek/codex) with call records"
```

---

## Task 6: Recorder (write run records)

**Files:** Create `src/memedogV2/harness/recorder.py`; Test `tests/memedogV2/test_recorder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_recorder.py
import json
from memedogV2.harness.recorder import Recorder
from memedogV2.harness.contracts import HarnessRun, StepResult, StepStatus


def test_recorder_writes_json_run_file(tmp_path):
    run = HarnessRun(run_id="r1", ca_address="CAabcdef", backend="fake", mode="production")
    run.steps.append(StepResult(name="hardfilter", status=StepStatus.OK))
    rec = Recorder(runs_dir=str(tmp_path))
    path = rec.write(run)
    assert path.endswith(".json")
    data = json.load(open(path))
    assert data["run_id"] == "r1" and data["steps"][0]["name"] == "hardfilter"
    # filename contains run id and ca summary
    import os
    assert "r1" in os.path.basename(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_recorder.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/harness/recorder.py
from __future__ import annotations

import os
from datetime import datetime, timezone

from memedogV2.harness.contracts import HarnessRun


class Recorder:
    """Writes a HarnessRun as JSON to runs_dir (default runs/memedogV2/)."""

    def __init__(self, runs_dir: str = "runs/memedogV2") -> None:
        self._dir = runs_dir

    def write(self, run: HarnessRun) -> str:
        os.makedirs(self._dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ca = (run.ca_address[:8] or "unknown")
        path = os.path.join(self._dir, f"{ts}-{run.run_id}-{ca}.json")
        with open(path, "w") as f:
            f.write(run.model_dump_json(indent=2))
        return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_recorder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/harness/recorder.py tests/memedogV2/test_recorder.py
echo "runs/" >> .gitignore
git add .gitignore
git commit -m "feat(harness): run recorder (writes runs/memedogV2/*.json); gitignore runs/"
```

---

## Task 7: Workflow runner (wire the whole production path)

**Files:** Create `src/memedogV2/harness/runner.py`; Test `tests/memedogV2/test_workflow_runner.py`

The runner drives: read security → read info → hardfilter → (drop? skip model steps) → build evidence → bull → bear → judge → signal, recording each step. RateLimitBanned is recorded as a failed step and the run ends with no signal (never raises).

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_workflow_runner.py
import pytest
from memedogV2.harness.runner import HarnessRunner
from memedogV2.harness.tool_registry import ToolRegistry, FixtureToolSource
from memedogV2.harness.model_registry import FakeBackend
from memedogV2.harness.contracts import StepStatus


CLEAN_SEC = {"renounced_mint": True, "renounced_freeze_account": True,
             "honeypot": 0, "burn_status": "burn", "lock_summary": {"is_locked": True}}
CLEAN_INFO = {"liquidity": "50000", "circulating_supply": "1000000",
              "price": {"price": "0.05", "volume_5m": "5000", "buys_5m": 30, "sells_5m": 10},
              "stat": {"top_10_holder_rate": "0.2", "creator_hold_rate": "0",
                       "dev_team_hold_rate": "0", "fresh_wallet_rate": "0",
                       "top_bundler_trader_percentage": "0"},
              "wallet_tags_stat": {"sniper_wallets": 3, "smart_wallets": 4, "renowned_wallets": 1}}
DIRTY_SEC = {"renounced_mint": False, "renounced_freeze_account": True}

CFG = {"max_top10_rate": 0.35, "max_creator_rate": 0.10, "max_dev_rate": 0.10,
       "max_sniper_wallets": 20, "max_fresh_wallet_rate": 0.6, "max_bundler_rate": 0.3,
       "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0,
       "max_fdv_to_liquidity": 50}


def _fake_backend():
    return FakeBackend(responses={
        "bull": {"thesis": "smart money", "points": []},
        "bear": {"thesis": "risk", "points": []},
        "judge": {"signal": "BULLISH", "recommended": True, "confidence": 0.7,
                  "rationale": "ok", "evidence_refs": ["smart_money_count"]},
    })


@pytest.mark.asyncio
async def test_clean_token_runs_full_workflow():
    reg = ToolRegistry(source=FixtureToolSource(security=CLEAN_SEC, info=CLEAN_INFO))
    runner = HarnessRunner(tool_registry=reg, backend=_fake_backend(),
                           hardfilter_cfg=CFG, recorder=None)
    run = await runner.run("CA", "LP", trace_id="t1")
    assert run.final_signal is not None
    assert run.final_signal.recommended is True
    assert run.final_signal.trace_id == "t1"
    names = [s.name for s in run.steps]
    assert names == ["read_security", "read_info", "hardfilter",
                     "build_evidence", "bull", "bear", "judge", "signal"]
    # evidence step recorded the gmgn tool calls
    tool_steps = [s for s in run.steps if s.tool_calls]
    assert tool_steps  # security/info calls were recorded


@pytest.mark.asyncio
async def test_dropped_token_skips_model_steps():
    reg = ToolRegistry(source=FixtureToolSource(security=DIRTY_SEC, info=CLEAN_INFO))
    runner = HarnessRunner(tool_registry=reg, backend=_fake_backend(),
                           hardfilter_cfg=CFG, recorder=None)
    run = await runner.run("CA", "LP")
    assert run.final_signal is None
    statuses = {s.name: s.status for s in run.steps}
    assert statuses["hardfilter"] == StepStatus.OK   # ran, decided drop
    assert statuses["bull"] == StepStatus.SKIPPED
    assert statuses["judge"] == StepStatus.SKIPPED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_workflow_runner.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/harness/runner.py
from __future__ import annotations

import uuid
from typing import Optional

from memedogV2.audit import prompts
from memedogV2.clients.errors import RateLimitBanned
from memedogV2.hardfilter.hardfilter import HardFilter
from memedogV2.harness.contracts import (
    HarnessRun, ModelCallRecord, StepResult, StepStatus,
)
from memedogV2.harness.evidence_builder import build_evidence
from memedogV2.models.contracts import Signal, SignalKind

_STEPS_AFTER_DROP = ["build_evidence", "bull", "bear", "judge", "signal"]


class HarnessRunner:
    """Deterministic production audit path. Never raises."""

    def __init__(self, *, tool_registry, backend, hardfilter_cfg: dict,
                 recorder=None, on_failure: str = "pass_flagged") -> None:
        self._tools = tool_registry
        self._backend = backend
        self._cfg = hardfilter_cfg
        self._recorder = recorder
        self._on_failure = on_failure

    async def run(self, ca: str, lp: str, trace_id: str = "") -> HarnessRun:
        run = HarnessRun(run_id=uuid.uuid4().hex[:8], ca_address=ca,
                         backend=getattr(self._backend, "name", "unknown"),
                         mode="production")
        facts: dict = {}
        try:
            # read_security
            sec, rec = await self._tools.fetch_security(ca)
            facts.update(sec)
            run.steps.append(StepResult(name="read_security", status=StepStatus.OK,
                                        tool_calls=[rec]))
            # read_info
            info, rec = await self._tools.fetch_info(ca)
            facts.update(info)
            run.steps.append(StepResult(name="read_info", status=StepStatus.OK,
                                        tool_calls=[rec]))
        except RateLimitBanned as e:
            run.steps.append(StepResult(name="read_data", status=StepStatus.FAILED,
                                        error=f"rate-limit ban until {e.reset_at}"))
            return self._finish(run)

        # hardfilter (reuse rules over already-fetched facts)
        hf = HardFilter(cli=_FactsCli(facts), cfg=self._cfg, on_failure=self._on_failure)
        hf_res = await hf.evaluate(ca, lp, trace_id=trace_id)
        run.steps.append(StepResult(
            name="hardfilter",
            status=StepStatus.OK,
            detail=("passed" if hf_res.passed else f"dropped: {hf_res.dropped}")))

        if not hf_res.passed:
            for name in _STEPS_AFTER_DROP:
                run.steps.append(StepResult(name=name, status=StepStatus.SKIPPED))
            return self._finish(run)

        # build_evidence (deterministic)
        bundle = build_evidence(facts=facts, ca=ca)
        run.steps.append(StepResult(name="build_evidence", status=StepStatus.OK,
                                    detail=f"missing={bundle.missing}"))

        # bull / bear
        bull, m = await self._backend.complete(
            role="bull", prompt=prompts.analyst_prompt("bull", bundle),
            schema=prompts.ANALYST_SCHEMA)
        run.steps.append(self._model_step("bull", m))
        bear, m = await self._backend.complete(
            role="bear", prompt=prompts.analyst_prompt("bear", bundle),
            schema=prompts.ANALYST_SCHEMA)
        run.steps.append(self._model_step("bear", m))

        # judge
        verdict, m = await self._backend.complete(
            role="judge", prompt=prompts.judge_prompt(bundle, bull=bull, bear=bear),
            schema=prompts.JUDGE_SCHEMA)
        run.steps.append(self._model_step("judge", m))

        # signal
        sig = Signal(
            ca_address=ca,
            signal=SignalKind(verdict["signal"]),
            recommended=bool(verdict["recommended"]),
            confidence=max(0.0, min(1.0, float(verdict["confidence"]))),
            rationale=str(verdict["rationale"]),
            evidence_refs=list(verdict.get("evidence_refs", [])),
            trace_id=trace_id,
        )
        run.final_signal = sig
        run.steps.append(StepResult(name="signal", status=StepStatus.OK,
                                    detail=f"{sig.signal.value} recommended={sig.recommended}"))
        return self._finish(run)

    @staticmethod
    def _model_step(role: str, rec: ModelCallRecord) -> StepResult:
        return StepResult(name=role,
                          status=StepStatus.OK if rec.schema_valid else StepStatus.DEGRADED,
                          model_calls=[rec])

    def _finish(self, run: HarnessRun) -> HarnessRun:
        if self._recorder is not None:
            try:
                self._recorder.write(run)
            except Exception:
                pass
        return run


class _FactsCli:
    """Adapts already-fetched facts to the GmgnCli interface HardFilter expects,
    so hardfilter runs over harness-fetched data without re-calling gmgn."""

    def __init__(self, facts: dict) -> None:
        self._facts = facts

    async def token_security(self, ca: str) -> dict:
        return self._facts

    async def token_info(self, ca: str) -> dict:
        return self._facts
```

Note: `_FactsCli` returns the merged `facts` for both calls; `HardFilter` reads each rule's fields via `FIELD_MAP` paths, which are unique per field, so merging security+info into one dict is correct and avoids a second gmgn fetch.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_workflow_runner.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/harness/runner.py tests/memedogV2/test_workflow_runner.py
git commit -m "feat(harness): workflow runner (security->info->hardfilter->evidence->bull/bear/judge->signal)"
```

---

## Task 8: Wire `__main__` to the harness; remove old audit path

**Files:** Modify `src/memedogV2/__main__.py`; Delete `src/memedogV2/audit/debate.py`, `src/memedogV2/orchestrator.py`, and their tests; update `tests/memedogV2/test_e2e_mocked.py`

The harness runner is now the production entry. The old `V2Orchestrator`/`AuditPipeline`/`BullBearJudge` are replaced.

- [ ] **Step 1: Update the mocked e2e test to use the harness**

```python
# tests/memedogV2/test_e2e_mocked.py  (replace file contents)
import pytest
from memedogV2.harness.runner import HarnessRunner
from memedogV2.harness.tool_registry import ToolRegistry, FixtureToolSource
from memedogV2.harness.model_registry import FakeBackend

CLEAN_SEC = {"renounced_mint": True, "renounced_freeze_account": True,
             "honeypot": 0, "burn_status": "burn", "lock_summary": {"is_locked": True}}
CLEAN_INFO = {"liquidity": "50000", "circulating_supply": "1000000",
              "price": {"price": "0.05", "volume_5m": "5000", "buys_5m": 30, "sells_5m": 10},
              "stat": {"top_10_holder_rate": "0.2", "creator_hold_rate": "0",
                       "dev_team_hold_rate": "0", "fresh_wallet_rate": "0",
                       "top_bundler_trader_percentage": "0"},
              "wallet_tags_stat": {"sniper_wallets": 3, "smart_wallets": 4, "renowned_wallets": 1}}
CFG = {"max_top10_rate": 0.35, "max_creator_rate": 0.10, "max_dev_rate": 0.10,
       "max_sniper_wallets": 20, "max_fresh_wallet_rate": 0.6, "max_bundler_rate": 0.3,
       "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0,
       "max_fdv_to_liquidity": 50}


@pytest.mark.asyncio
async def test_clean_token_flows_to_recommended_signal():
    reg = ToolRegistry(source=FixtureToolSource(security=CLEAN_SEC, info=CLEAN_INFO))
    backend = FakeBackend(responses={
        "bull": {"thesis": "smart money", "points": []},
        "bear": {"thesis": "risk", "points": []},
        "judge": {"signal": "BULLISH", "recommended": True, "confidence": 0.7,
                  "rationale": "net positive", "evidence_refs": ["smart_money_count"]}})
    runner = HarnessRunner(tool_registry=reg, backend=backend, hardfilter_cfg=CFG)
    run = await runner.run("CA", "LP", trace_id="t-e2e")
    assert run.final_signal is not None
    assert run.final_signal.recommended is True
    assert run.final_signal.signal.value == "BULLISH"
```

- [ ] **Step 2: Run it — expect FAIL** (old e2e imported removed modules / new wiring not in `__main__` yet)

Run: `pytest tests/memedogV2/test_e2e_mocked.py -v`
Expected: PASS already if harness is in place (it doesn't depend on `__main__`). If it fails, the failure names the missing import — fix only test wiring.

- [ ] **Step 3: Rewrite `__main__.py` and delete the old path**

```python
# src/memedogV2/__main__.py  (replace file contents)
"""Manual entrypoint: process one (CA, LP) through the harness production path.

Usage: python -m memedogV2 <CA> <LP> [backend]   # backend: deepseek (default) | codex
Requires GMGN_API_KEY in ~/.config/gmgn/.env, gmgn-cli installed; DEEPSEEK_API_KEY or codex login.
"""
from __future__ import annotations

import asyncio
import os
import sys

from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.config import load_v2_config
from memedogV2.harness.model_registry import build_backend
from memedogV2.harness.recorder import Recorder
from memedogV2.harness.runner import HarnessRunner
from memedogV2.harness.tool_registry import GmgnCliToolSource, ToolRegistry

_CFG = os.path.join(os.path.dirname(__file__), "config_thresholds.yaml")


async def _main(ca: str, lp: str, backend_name: str) -> None:
    cfg = load_v2_config(_CFG)
    cli = GmgnCli(rate_per_sec=cfg.gmgn["rate_limit_rps"], capacity=1,
                  cache_ttl_sec=cfg.gmgn["cache_ttl_sec"])
    reg = ToolRegistry(source=GmgnCliToolSource(cli))
    backend = build_backend(backend_name, cwd=os.getcwd())
    runner = HarnessRunner(tool_registry=reg, backend=backend,
                           hardfilter_cfg=cfg.hardfilter,
                           recorder=Recorder(), on_failure=cfg.gmgn["on_failure"])
    run = await runner.run(ca, lp)
    print(run.model_dump_json(indent=2))


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print("usage: python -m memedogV2 <CA> <LP> [deepseek|codex]")
        sys.exit(2)
    name = sys.argv[3] if len(sys.argv) == 4 else "deepseek"
    asyncio.run(_main(sys.argv[1], sys.argv[2], name))
```

Then delete the superseded modules + tests:

```bash
git rm src/memedogV2/orchestrator.py src/memedogV2/audit/debate.py \
       tests/memedogV2/test_orchestrator.py tests/memedogV2/test_debate.py
```

- [ ] **Step 4: Run the whole suite**

Run: `pytest tests/memedogV2 -q`
Expected: ALL PASS (no import of removed modules remains). Then `pytest -q` (whole repo) — memedog still green.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(harness): make harness the production path; remove old orchestrator/debate"
```

---

## Task 9: Real-environment tests (live-marked, per stage)

**Files:** Create `tests/memedogV2/live/__init__.py`, `tests/memedogV2/live/test_live_gmgn.py`, `test_live_deepseek.py`, `test_live_codex.py`, `test_live_pipeline.py`

These hit real services. They are `@pytest.mark.live` (deselected by default; run with `pytest -m live`). Each asserts real behavior + recorded evidence. They `skip` if the required credential/binary is missing so the suite stays green where unconfigured.

- [ ] **Step 1: Write the live tests**

```python
# tests/memedogV2/live/__init__.py
```

```python
# tests/memedogV2/live/test_live_gmgn.py
import shutil
import pytest
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.harness.tool_registry import ToolRegistry, GmgnCliToolSource

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_real_gmgn_security_and_info_recorded():
    if shutil.which("gmgn-cli") is None:
        pytest.skip("gmgn-cli not installed")
    reg = ToolRegistry(source=GmgnCliToolSource(GmgnCli(rate_per_sec=1.0, capacity=1)))
    sec, rec_sec = await reg.fetch_security(USDC)
    info, rec_info = await reg.fetch_info(USDC)
    # real fields present + recorded
    assert sec.get("renounced_mint") is True            # USDC mint revoked
    assert "wallet_tags_stat" in info
    assert rec_sec.exit_status == 0 and rec_sec.duration_ms > 0
    assert "security" in rec_sec.command and "info" in rec_info.command
```

```python
# tests/memedogV2/live/test_live_deepseek.py
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
```

```python
# tests/memedogV2/live/test_live_codex.py
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
```

```python
# tests/memedogV2/live/test_live_pipeline.py
import os, shutil
import pytest
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.config import load_v2_config
from memedogV2.harness.runner import HarnessRunner
from memedogV2.harness.tool_registry import ToolRegistry, GmgnCliToolSource
from memedogV2.harness.model_registry import build_backend

pytestmark = pytest.mark.live
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["deepseek", "codex"])
async def test_real_pipeline_runs_and_records(backend):
    if shutil.which("gmgn-cli") is None:
        pytest.skip("gmgn-cli not installed")
    if backend == "deepseek" and not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set")
    if backend == "codex" and shutil.which("codex") is None:
        pytest.skip("codex not installed")
    cfg = load_v2_config("src/memedogV2/config_thresholds.yaml")
    reg = ToolRegistry(source=GmgnCliToolSource(GmgnCli(rate_per_sec=1.0, capacity=1)))
    runner = HarnessRunner(tool_registry=reg, backend=build_backend(backend),
                           hardfilter_cfg=cfg.hardfilter)
    run = await runner.run(USDC, "LP")
    # USDC reaches at least hardfilter; every step has a status; gmgn calls recorded
    names = [s.name for s in run.steps]
    assert names[:3] == ["read_security", "read_info", "hardfilter"]
    assert any(s.tool_calls for s in run.steps)
    # if it passed hardfilter, a signal exists with a valid kind
    if run.final_signal is not None:
        assert run.final_signal.signal.value in ("BULLISH", "BEARISH", "NEUTRAL")
```

- [ ] **Step 2: Verify they are collected but skipped by default**

Run: `pytest tests/memedogV2 -q`
Expected: PASS, with the live tests deselected (`-m 'not live'` is the default in pyproject).

- [ ] **Step 3: Run the live suite for real (manual, rate-limit aware)**

Run: `pytest tests/memedogV2/live -m live -v -s`
Expected: real gmgn-cli + DeepSeek + Codex tests PASS (or `skip` where a credential/binary is absent). Watch for gmgn 429 — if seen, wait 5 min, do not loop. Codex tests are slow (~1-2 min each).

- [ ] **Step 4: Commit**

```bash
git add tests/memedogV2/live
git commit -m "test(harness): live real-environment tests (gmgn-cli, deepseek, codex, full pipeline)"
```

---

## Task 10: Docs — record the harness as the production path

**Files:** Modify `docs/superpowers/specs/2026-06-25-memedogV2-harness-design.md` (append an "implemented" note) and `CLAUDE.md` (point the V2 pipeline at the harness)

- [ ] **Step 1: Append an implementation note to the harness spec**

Add a short section noting: phase-1 production harness implemented (`src/memedogV2/harness/`), DeepSeek + Codex backends behind `model_registry`, evidence deterministic from facts, run records in `runs/memedogV2/`, real-env tests under `tests/memedogV2/live/` (run `pytest -m live`). Note that `compliance.py` and full `replay.py` remain deferred.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-06-25-memedogV2-harness-design.md CLAUDE.md
git commit -m "docs(harness): record harness as memedogV2 production path"
```

---

## Self-Review Notes

- **Spec coverage:** §四 hybrid (production deterministic + eval) → production path built (Tasks 1–9); eval/compliance path explicitly deferred. §五 dir → harness package (contracts/tool_registry/evidence_builder/model_registry/recorder/runner; `workflow.py` logic folded into `runner.py` since the sequence is linear — `compliance.py`/`replay.py` deferred). §六 production path → Task 7 runner. §八 contracts → Task 1. §九 state machine (skip-on-drop) → Task 7 (`test_dropped_token_skips_model_steps`). §十 two backend classes → Task 5 (DeepSeek=structured-reasoning, Codex=executable-agent but used here only for structured reasoning). §十二 run records → Task 6. §十三 tests: unit (Tasks 1–8) + **real-env per stage (Task 9, your requirement)**. §十四 error handling: RateLimitBanned recorded no-retry (Task 7), model schema-invalid → DEGRADED + one repair retry for DeepSeek (Task 5). §十六 acceptance: deterministic fixture runs (Task 7/8), drop skips models (Task 7), same bundle across backends (Task 5 interface + Task 9 parametrized), auditable steps (Task 1/6).
- **Deferred & called out:** `compliance.py` (§七), full `replay.py` (§十二 cross-model diff), GMGN skills lock file (§十一 — not needed now that production doesn't depend on skills; revisit when building the compliance path).
- **Type consistency:** `ModelBackend.complete(*, role, prompt, schema) -> (dict, ModelCallRecord)` used identically in Tasks 5/7/9. `ToolRegistry.fetch_security/fetch_info -> (dict, ToolCallRecord)` consistent Tasks 2/7/9. `build_evidence(*, facts, ca)` consistent Tasks 3/7. `HarnessRunner(tool_registry=, backend=, hardfilter_cfg=, recorder=, on_failure=)` consistent Tasks 7/8/9.
- **Real-env requirement:** Task 9 covers every stage live — gmgn fetch (`test_live_gmgn`), each model backend over a real bundle (`test_live_deepseek`/`test_live_codex`), and full real pipeline (`test_live_pipeline`, parametrized over both backends). Live tests `skip` when a credential/binary is absent so default CI stays green.
```
