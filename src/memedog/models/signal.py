"""Signal data contracts."""
from datetime import datetime
from enum import Enum

from pydantic import AwareDatetime, BaseModel


class SignalType(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class Signal(BaseModel):
    mint: str
    symbol: str
    signal: SignalType
    confidence: float
    score_total: float
    bull_points: list[str]
    bear_points: list[str]
    red_flags: list[str]
    rationale: str
    created_at: AwareDatetime
    trace_id: str
