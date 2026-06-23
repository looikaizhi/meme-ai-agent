"""Protocol for realtime migration feeds."""
from __future__ import annotations

import asyncio
from typing import Protocol


class MigrationFeed(Protocol):
    async def run(self, stop_event: asyncio.Event) -> None: ...
    def recent_mints(self) -> list[str]: ...
