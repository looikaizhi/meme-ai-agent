"""TTL'd, non-destructive, de-duplicated buffer of discovered mints."""
from __future__ import annotations

import time
from typing import Any, Callable


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
        self._meta: dict[str, dict[str, Any]] = {}

    def add(self, mint: str, **metadata: Any) -> None:
        if not mint:
            return
        if mint not in self._items:
            self._items[mint] = self._clock()
        if metadata:
            current = self._meta.get(mint, {})
            current.update({key: value for key, value in metadata.items() if value is not None})
            self._meta[mint] = current

    def recent(self) -> list[str]:
        now = self._clock()
        self._items = {
            mint: ts for mint, ts in self._items.items() if now - ts < self._ttl
        }
        self._meta = {
            mint: meta for mint, meta in self._meta.items() if mint in self._items
        }
        return list(self._items.keys())

    def metadata(self, mint: str) -> dict[str, Any]:
        self.recent()
        return dict(self._meta.get(mint, {}))
