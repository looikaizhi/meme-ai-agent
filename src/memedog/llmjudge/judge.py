"""LLMJudge: Bull/Bear debate + structured verdict → Signal.

JudgeOut is the Pydantic model for the LLM's final JSON output.
LLMJudge orchestrates the three-role debate and maps the output to Signal.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from memedog.llm.provider import LLMProvider, LLMProviderError
from memedog.llm.structured import StructuredParseError, complete_structured
from memedog.models import Score, Signal, SignalType, TokenSnapshot

log = logging.getLogger(__name__)


class StepFinding(BaseModel):
    """One step of the judge's multi-step reasoning workflow."""

    step: str        # "safety" | "concentration" | "momentum" | "social" | "debate"
    assessment: str  # "pass" | "concern" | "fail" | "neutral" | "missing"
    note: str = ""


class JudgeOut(BaseModel):
    """Schema for the LLM judge's final JSON output."""

    signal: str
    confidence: float
    bull_points: list[str]
    bear_points: list[str]
    red_flags: list[str]
    rationale: str
    workflow: list[StepFinding] = []


def _map_signal(raw: str) -> SignalType:
    """Map a raw string from the LLM to SignalType, defaulting to NEUTRAL."""
    mapping = {
        "BULLISH": SignalType.BULLISH,
        "BEARISH": SignalType.BEARISH,
        "NEUTRAL": SignalType.NEUTRAL,
    }
    return mapping.get(raw.upper().strip(), SignalType.NEUTRAL)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _degrade_signal(score_total: float) -> tuple[SignalType, float]:
    """Rule-based signal + confidence from score.total when LLM fails."""
    if score_total >= 70:
        sig = SignalType.BULLISH
        confidence = _clamp((score_total - 70) / 30)
    elif score_total <= 40:
        sig = SignalType.BEARISH
        confidence = _clamp((40 - score_total) / 40)
    else:
        sig = SignalType.NEUTRAL
        confidence = _clamp(1.0 - abs(score_total - 55) / 15)
    return sig, confidence


def _summarize_workflow(steps: list[StepFinding]) -> str:
    """Compact one-line summary of workflow steps for the Signal.rationale."""
    if not steps:
        return ""
    parts = []
    for s in steps:
        seg = f"{s.step}:{s.assessment}"
        if s.note:
            seg += f"({s.note})"
        parts.append(seg)
    return " | ".join(parts)


def _completeness(snapshot: TokenSnapshot) -> float:
    """Fraction of the 4 dimensions whose data is available."""
    flags = [
        snapshot.safety.available,
        snapshot.holders.available,
        snapshot.momentum.available,
        snapshot.social.available,
    ]
    return sum(1 for f in flags if f) / 4.0


class LLMJudge:
    """Runs a three-role (bull / bear / judge) LLM debate and emits a Signal.

    Parameters
    ----------
    cfg:
        An LLMJudgeConfig instance (from settings.py).
    provider:
        Optional injected LLMProvider used for ALL three roles.  When supplied
        (test mode) ``make_provider`` is NOT called.  When omitted, each role
        gets its own provider derived from ``cfg.models``.
    """

    def __init__(self, cfg, provider: Optional[LLMProvider] = None) -> None:
        self._cfg = cfg
        self._injected_provider = provider

    def _get_provider_and_model(self, role: str) -> tuple[LLMProvider, str]:
        if self._injected_provider is not None:
            model_str = self._cfg.models[role]
            # Parse model name from model_str (strip prefix)
            if model_str.startswith("codex:"):
                suffix = model_str[len("codex:"):]
                model_name = "" if suffix == "default" else suffix
            elif model_str.startswith("litellm:"):
                model_name = model_str[len("litellm:"):]
            else:
                model_name = model_str
            return (self._injected_provider, model_name)

        from memedog.llm.provider import make_provider

        # Honor the configured Codex settings (bin / timeout / sandbox) instead of
        # CodexCLIProvider defaults. make_provider only uses the injected codex
        # instance for "codex:" model strings; litellm strings ignore it.
        codex_provider = None
        codex_cfg = getattr(self._cfg, "codex", None)
        if codex_cfg is not None:
            from memedog.llm.codex_provider import CodexCLIProvider

            codex_provider = CodexCLIProvider(
                codex_bin=codex_cfg.bin,
                timeout=codex_cfg.timeout_sec,
                sandbox=codex_cfg.sandbox,
            )
        return make_provider(self._cfg.models[role], codex=codex_provider)

    async def judge(self, snapshot: TokenSnapshot, score: Score) -> Signal:
        """Run the Bull/Bear debate and produce a Signal.

        Never raises — degrades to rule-based signal on any error.
        """
        from memedog.llmjudge.prompts import bear_prompt, bull_prompt, judge_prompt

        try:
            bull_provider, bull_model = self._get_provider_and_model("bull")
            bear_provider, bear_model = self._get_provider_and_model("bear")
            judge_provider, judge_model = self._get_provider_and_model("judge")

            bull_temp = self._cfg.temperature["bull"]
            bear_temp = self._cfg.temperature["bear"]
            judge_temp = self._cfg.temperature["judge"]

            b_msgs = bull_prompt(snapshot, score)
            r_msgs = bear_prompt(snapshot, score)

            # Run bull then bear SEQUENTIALLY (not concurrently).
            # The codex CLI runs against a single ChatGPT subscription; two
            # simultaneous subprocesses get server-side throttled/queued, which
            # in practice makes each call hang past the timeout. Sequential calls
            # let each one use full throughput. Call order (bull=0, bear=1,
            # judge=2) is preserved for FakeProvider index-based tests.
            bull_text = await bull_provider.complete(
                model=bull_model,
                messages=b_msgs,
                temperature=bull_temp,
                max_tokens=self._cfg.max_tokens,
            )
            bear_text = await bear_provider.complete(
                model=bear_model,
                messages=r_msgs,
                temperature=bear_temp,
                max_tokens=self._cfg.max_tokens,
            )

            j_msgs = judge_prompt(snapshot, score, bull_text, bear_text)
            judge_out: JudgeOut = await complete_structured(
                provider=judge_provider,
                model=judge_model,
                messages=j_msgs,
                model_cls=JudgeOut,
                temperature=judge_temp,
                max_tokens=self._cfg.max_tokens,
                retries=self._cfg.repair_retries,
            )

            sig_type = _map_signal(judge_out.signal)
            confidence = _clamp(judge_out.confidence)

            # Confidence guard: cap by data completeness when enabled.
            guard = getattr(self._cfg, "confidence_guard", None)
            if guard is not None and getattr(guard, "enabled", False):
                completeness = _completeness(snapshot)
                cap = guard.floor + (1.0 - guard.floor) * completeness
                confidence = min(confidence, cap)

            # Fold the workflow step summary into the rationale (no schema change).
            summary = _summarize_workflow(judge_out.workflow)
            rationale = (
                f"{summary}\n{judge_out.rationale}" if summary else judge_out.rationale
            )

            return Signal(
                mint=snapshot.candidate.mint,
                symbol=snapshot.candidate.symbol,
                signal=sig_type,
                confidence=confidence,
                score_total=score.total,
                bull_points=judge_out.bull_points,
                bear_points=judge_out.bear_points,
                red_flags=judge_out.red_flags,
                rationale=rationale,
                created_at=datetime.now(tz=timezone.utc),
                trace_id=snapshot.candidate.trace_id,
            )

        except Exception as exc:
            log.warning(
                "LLMJudge failed for %s (%s), degrading to rule-based signal. Error: %s",
                snapshot.candidate.mint,
                snapshot.candidate.symbol,
                exc,
            )
            sig_type, confidence = _degrade_signal(score.total)
            return Signal(
                mint=snapshot.candidate.mint,
                symbol=snapshot.candidate.symbol,
                signal=sig_type,
                confidence=confidence,
                score_total=score.total,
                bull_points=[],
                bear_points=[],
                red_flags=[],
                rationale=f"降级(degraded): LLM unavailable — rule-based fallback (score={score.total:.1f})",
                created_at=datetime.now(tz=timezone.utc),
                trace_id=snapshot.candidate.trace_id,
            )
