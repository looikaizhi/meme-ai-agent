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

_STEPS_TO_SKIP_ON_DROP = ["build_evidence", "bull", "bear", "judge", "signal"]

_JUDGE_REQUIRED = {"signal", "recommended", "confidence", "rationale"}


class HarnessRunner:
    """Deterministic production audit path. Never raises."""

    def __init__(self, *, tool_registry, backend, hardfilter_cfg: dict,
                 recorder=None, on_failure: str = "pass_flagged") -> None:
        if on_failure not in ("drop", "pass_flagged"):
            raise ValueError(f"on_failure must be 'drop' or 'pass_flagged', got {on_failure!r}")
        self._tools = tool_registry
        self._backend = backend
        self._cfg = hardfilter_cfg
        self._recorder = recorder
        self._on_failure = on_failure

    async def run(self, ca: str, lp: str, trace_id: str = "") -> HarnessRun:
        run = HarnessRun(run_id=uuid.uuid4().hex[:8], ca_address=ca,
                         backend=getattr(self._backend, "name", "unknown"),
                         mode="production")

        # --- Stage 1: security ---
        try:
            sec, rec = await self._tools.fetch_security(ca)
            run.steps.append(StepResult(name="read_security", status=StepStatus.OK,
                                        tool_calls=[rec]))
        except RateLimitBanned as e:
            run.steps.append(StepResult(name="read_security", status=StepStatus.FAILED,
                                        error=f"rate-limit ban until {e.reset_at}"))
            return self._finish(run)

        # --- Stage 2: info ---
        try:
            info, rec = await self._tools.fetch_info(ca)
            run.steps.append(StepResult(name="read_info", status=StepStatus.OK,
                                        tool_calls=[rec]))
        except RateLimitBanned as e:
            run.steps.append(StepResult(name="read_info", status=StepStatus.FAILED,
                                        error=f"rate-limit ban until {e.reset_at}"))
            return self._finish(run)

        # Merged facts for evidence builder; HardFilter gets separate sec/info via _FactsCli
        facts: dict = {**sec, **info}

        hf = HardFilter(cli=_FactsCli(sec, info), cfg=self._cfg, on_failure=self._on_failure)
        hf_res = await hf.evaluate(ca, lp, trace_id=trace_id)
        hf_status = StepStatus.DEGRADED if hf_res.flagged else StepStatus.OK
        run.steps.append(StepResult(
            name="hardfilter",
            status=hf_status,
            detail=("passed" if hf_res.passed else f"dropped: {hf_res.dropped}")))

        if not hf_res.passed:
            for name in _STEPS_TO_SKIP_ON_DROP:
                run.steps.append(StepResult(name=name, status=StepStatus.SKIPPED))
            return self._finish(run)

        bundle = build_evidence(facts=facts, ca=ca)
        run.steps.append(StepResult(name="build_evidence", status=StepStatus.OK,
                                    detail=f"missing={bundle.missing}"))

        # The whole audit (real model calls + verdict parsing) is wrapped so run()
        # never raises: a backend network error or malformed model output becomes a
        # FAILED step with no signal, not an exception out of the pipeline.
        try:
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
        refs = verdict.get("evidence_refs", [])
        return Signal(
            ca_address=ca,
            signal=kind,
            recommended=bool(verdict["recommended"]),
            confidence=confidence,
            rationale=str(verdict["rationale"]),
            evidence_refs=list(refs) if isinstance(refs, list) else [],
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


class _FactsCli:
    """Adapts already-fetched security/info dicts to the GmgnCli interface HardFilter expects,
    so hardfilter runs over harness-fetched data without re-calling gmgn.

    Keeps the two payloads separate to avoid silent key clobbering when both
    gmgn payloads share a top-level field name.
    """

    def __init__(self, sec: dict, info: dict) -> None:
        self._sec = sec
        self._info = info

    async def token_security(self, ca: str) -> dict:
        return self._sec

    async def token_info(self, ca: str) -> dict:
        return self._info
