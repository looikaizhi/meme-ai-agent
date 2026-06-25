from __future__ import annotations

import asyncio
import uuid

from pydantic import BaseModel


class IntakeItem(BaseModel):
    ca_address: str
    lp_address: str
    trace_id: str


class AddressIntake:
    """Event-driven (ca, lp) queue with dedup. Drain pacing is the orchestrator's job
    (via the shared gmgn rate limiter); this just buffers and dedups bursts."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[IntakeItem] = asyncio.Queue()
        self._seen: set[str] = set()

    def enqueue(self, ca_address: str, lp_address: str) -> str:
        if ca_address in self._seen:
            return ""
        self._seen.add(ca_address)
        tid = uuid.uuid4().hex[:12]
        self._q.put_nowait(IntakeItem(ca_address=ca_address, lp_address=lp_address, trace_id=tid))
        return tid

    async def get(self) -> IntakeItem:
        return await self._q.get()

    def size(self) -> int:
        return self._q.qsize()
