from __future__ import annotations

import uuid

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
            sec, rec = await self._tools.fetch_security(ca)
            facts.update(sec)
            run.steps.append(StepResult(name="read_security", status=StepStatus.OK,
                                        tool_calls=[rec]))
            info, rec = await self._tools.fetch_info(ca)
            facts.update(info)
            run.steps.append(StepResult(name="read_info", status=StepStatus.OK,
                                        tool_calls=[rec]))
        except RateLimitBanned as e:
            run.steps.append(StepResult(name="read_data", status=StepStatus.FAILED,
                                        error=f"rate-limit ban until {e.reset_at}"))
            return self._finish(run)

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

        bundle = build_evidence(facts=facts, ca=ca)
        run.steps.append(StepResult(name="build_evidence", status=StepStatus.OK,
                                    detail=f"missing={bundle.missing}"))

        bull, m = await self._backend.complete(
            role="bull", prompt=prompts.analyst_prompt("bull", bundle),
            schema=prompts.ANALYST_SCHEMA)
        run.steps.append(self._model_step("bull", m))
        bear, m = await self._backend.complete(
            role="bear", prompt=prompts.analyst_prompt("bear", bundle),
            schema=prompts.ANALYST_SCHEMA)
        run.steps.append(self._model_step("bear", m))

        verdict, m = await self._backend.complete(
            role="judge", prompt=prompts.judge_prompt(bundle, bull=bull, bear=bear),
            schema=prompts.JUDGE_SCHEMA)
        run.steps.append(self._model_step("judge", m))

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
