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
