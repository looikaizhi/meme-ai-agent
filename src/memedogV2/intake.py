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


class IntakeProcessor:
    """Drain scanner intake items through the V2 production harness."""

    def __init__(self, *, intake: AddressIntake, runner, store=None) -> None:
        self._intake = intake
        self._runner = runner
        self._store = store

    async def process_next(self):
        item = await self._intake.get()
        run = await self._runner.run(
            item.ca_address,
            item.lp_address,
            trace_id=item.trace_id,
        )
        if self._store is not None:
            self._store.save_run(run, trace_id=item.trace_id)
        return run

    async def drain_available(self, limit: int | None = None) -> list:
        runs = []
        while self._intake.size() > 0 and (limit is None or len(runs) < limit):
            runs.append(await self.process_next())
        return runs

    def pending(self) -> int:
        return self._intake.size()
