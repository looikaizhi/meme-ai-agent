from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SignalKind(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class HardFilterResult(BaseModel):
    """Deterministic gmgn-cli facts + red-line outcome for one address."""
    ca_address: str
    lp_address: str
    passed: bool = False
    facts: dict[str, Any] = Field(default_factory=dict)
    dropped: list[str] = Field(default_factory=list)   # "rule_name: actual vs threshold"
    flagged: list[str] = Field(default_factory=list)
    trace_id: str = ""


class EvidenceBundle(BaseModel):
    """Interpretation signals gathered for the LLM audit (all optional/degradable)."""
    ca_address: str
    smart_money_count: Optional[int] = None
    kol_holder_count: Optional[int] = None
    dev_created_token_count: Optional[int] = None
    dev_graduation_rate: Optional[float] = None
    historical_ath: Optional[float] = None
    trend: Optional[dict[str, Any]] = None
    holders_detail: Optional[dict[str, Any]] = None
    missing: list[str] = Field(default_factory=list)   # dims that failed to fetch


class Signal(BaseModel):
    ca_address: str
    signal: SignalKind
    recommended: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)
    trace_id: str = ""
