from __future__ import annotations

from pydantic import BaseModel, Field

from memedogV2.clients.errors import RateLimitBanned
from memedogV2.harness.contracts import ToolCallRecord
from memedogV2.sources.base import (
    ALL_FIELDS, FIELD_PRIORITY, MOMENTUM_FIELDS, Facts, PartialFacts,
)


class ResolvedFacts(BaseModel):
    facts: Facts
    sources: dict[str, str] = Field(default_factory=dict)   # field -> source name
    attempts: list[ToolCallRecord] = Field(default_factory=list)
    momentum_unavailable: bool = False


class DataResolver:
    """Calls sources (tolerating per-source failure), merges fields by priority."""

    def __init__(self, *, sources: dict) -> None:
        self._sources = sources   # name -> adapter

    async def resolve(self, ca: str, lp: str) -> ResolvedFacts:
        partials: dict[str, PartialFacts] = {}
        attempts: list[ToolCallRecord] = []
        for name, src in self._sources.items():
            try:
                pf, rec = await src.fetch(ca, lp)
            except RateLimitBanned:
                raise
            except Exception as e:   # defensive: adapters degrade internally, but never crash here
                pf = PartialFacts()
                rec = ToolCallRecord(tool=name, command="fetch", exit_status=1,
                                     output_summary=str(e)[:200])
            partials[name] = pf
            attempts.append(rec)

        merged = Facts()
        source_of: dict[str, str] = {}
        for field in ALL_FIELDS:
            for src_name in FIELD_PRIORITY[field]:
                pf = partials.get(src_name)
                if pf is None:
                    continue
                val = getattr(pf, field)
                if val is not None:
                    setattr(merged, field, val)
                    source_of[field] = src_name
                    break

        momentum_missing = any(getattr(merged, f) is None for f in MOMENTUM_FIELDS)
        return ResolvedFacts(facts=merged, sources=source_of, attempts=attempts,
                             momentum_unavailable=momentum_missing)
