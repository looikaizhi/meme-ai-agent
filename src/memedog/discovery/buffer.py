"""TTL'd, non-destructive, de-duplicated buffer of discovered mints."""
from __future__ import annotations

import time
from typing import Callable


class MintBuffer:
    """Hold recently discovered mints with stable insertion order."""

    def __init__(
        self,
        ttl_sec: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_sec
        self._clock = clock
        self._items: dict[str, float] = {}

    def add(self, mint: str) -> None:
        if not mint:
            return
        if mint not in self._items:
            self._items[mint] = self._clock()

    def recent(self) -> list[str]:
        now = self._clock()
        self._items = {
            mint: ts for mint, ts in self._items.items() if now - ts < self._ttl
        }
        return list(self._items.keys())
