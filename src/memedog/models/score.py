"""Score data contracts."""
from pydantic import BaseModel


class DimensionScore(BaseModel):
    name: str
    raw: float
    weight: float
    weighted: float
    notes: list[str] = []


class Score(BaseModel):
    mint: str
    total: float
    dimensions: list[DimensionScore]
    trace_id: str
