from __future__ import annotations

import uuid

from memedogV2.audit import prompts
from memedogV2.clients.errors import RateLimitBanned
from memedogV2.hardfilter.facts_filter import evaluate_facts
from memedogV2.harness.contracts import (
    HarnessRun, ModelCallRecord, StepResult, StepStatus,
)
from memedogV2.harness.evidence_builder import important_missing
from memedogV2.models.contracts import Signal, SignalKind

_STEPS_TO_SKIP_ON_DROP = ["build_evidence", "bull", "bear", "judge", "signal"]

_JUDGE_REQUIRED = {"signal", "recommended", "confidence", "summary"}


class HarnessRunner:
    """Deterministic production audit path. Never raises."""

    def __init__(self, *, resolver, backend, hardfilter_cfg: dict,
                 recorder=None) -> None:
        self._resolver = resolver
        self._backend = backend
        self._cfg = hardfilter_cfg
        self._recorder = recorder

    async def run(self, ca: str, lp: str, trace_id: str = "") -> HarnessRun:
        run = HarnessRun(run_id=uuid.uuid4().hex[:8], ca_address=ca,
                         backend=getattr(self._backend, "name", "unknown"),
                         mode="production")

        # read_facts (multi-source resolver) — never crashes the pipeline (C-1)
        try:
            resolved = await self._resolver.resolve(ca, lp)
        except RateLimitBanned as e:
            run.steps.append(StepResult(name="read_facts", status=StepStatus.FAILED,
                                        error=f"rate-limit ban until {e.reset_at}"))
            return self._finish(run)
        except Exception as e:
            run.steps.append(StepResult(name="read_facts", status=StepStatus.FAILED,
                                        error=f"resolve failed: {e}"))
            return self._finish(run)
        run.steps.append(StepResult(name="read_facts", status=StepStatus.OK,
                                    tool_calls=list(resolved.attempts),
                                    detail=f"sources={resolved.sources}"))

        # momentum is required (gmgn-only)
        if resolved.momentum_unavailable:
            run.steps.append(StepResult(name="hardfilter", status=StepStatus.FAILED,
                                        error="momentum unavailable (gmgn required)"))
            for name in ["build_evidence", "bull", "bear", "judge", "signal"]:
                run.steps.append(StepResult(name=name, status=StepStatus.SKIPPED))
            return self._finish(run)

        passed, dropped = evaluate_facts(resolved.facts, self._cfg)
        run.steps.append(StepResult(name="hardfilter", status=StepStatus.OK,
                                    detail=("passed" if passed else f"dropped: {dropped}")))
        if not passed:
            for name in ["build_evidence", "bull", "bear", "judge", "signal"]:
                run.steps.append(StepResult(name=name, status=StepStatus.SKIPPED))
            return self._finish(run)

        facts, srcs = resolved.facts, resolved.sources
        missing = important_missing(facts)
        run.steps.append(StepResult(name="build_evidence", status=StepStatus.OK,
                                    detail=f"fields={len(srcs)} missing={len(missing)}"))

        # The whole audit (real model calls + verdict parsing) is wrapped so run()
        # never raises: a backend network error or malformed model output becomes a
        # FAILED step with no signal, not an exception out of the pipeline.
        try:
            bull, m = await self._backend.complete(
                role="bull", prompt=prompts.analyst_prompt("bull", facts, srcs, missing),
                schema=prompts.ANALYST_SCHEMA)
            run.steps.append(self._model_step("bull", m))
            bear, m = await self._backend.complete(
                role="bear", prompt=prompts.analyst_prompt("bear", facts, srcs, missing),
                schema=prompts.ANALYST_SCHEMA)
            run.steps.append(self._model_step("bear", m))

            verdict, m = await self._backend.complete(
                role="judge",
                prompt=prompts.judge_prompt(facts, srcs, missing, bull=bull, bear=bear),
                schema=prompts.JUDGE_SCHEMA)
            run.steps.append(self._model_step("judge", m))
        except RateLimitBanned as e:
            run.steps.append(StepResult(name="signal", status=StepStatus.FAILED,
                                        error=f"rate-limit ban until {e.reset_at}"))
            return self._finish(run)
        except Exception as e:  # backend/network failure — degrade, don't crash
            run.steps.append(StepResult(name="signal", status=StepStatus.FAILED,
                                        error=f"audit model call failed: {e}"))
            return self._finish(run)

        sig = self._build_signal(ca, verdict, trace_id)
        if sig is None:
            run.steps.append(StepResult(name="signal", status=StepStatus.FAILED,
                                        error="judge verdict missing/invalid required fields"))
            return self._finish(run)

        run.final_signal = sig
        run.steps.append(StepResult(name="signal", status=StepStatus.OK,
                                    detail=f"{sig.signal.value} recommended={sig.recommended}"))
        return self._finish(run)

    @staticmethod
    def _build_signal(ca: str, verdict: dict, trace_id: str):
        """Validate a judge verdict into a Signal, or return None if malformed.
        Never raises — invalid signal enum / non-numeric confidence -> None."""
        if not isinstance(verdict, dict) or any(k not in verdict for k in _JUDGE_REQUIRED):
            return None
        try:
            kind = SignalKind(str(verdict["signal"]).upper())
            confidence = max(0.0, min(1.0, float(verdict["confidence"])))
        except (ValueError, TypeError):
            return None

        def _strs(key):
            v = verdict.get(key, [])
            return [str(x) for x in v] if isinstance(v, list) else []

        summary = str(verdict.get("summary", ""))
        return Signal(
            ca_address=ca,
            signal=kind,
            recommended=bool(verdict["recommended"]),
            confidence=confidence,
            rationale=summary,                       # back-compat: rationale = summary
            evidence_refs=_strs("evidence_refs"),
            summary=summary,
            strengths=_strs("strengths"),
            risks=_strs("risks"),
            key_metrics=_strs("key_metrics"),
            trace_id=trace_id,
        )

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
