"""Async rate limiter: concurrency cap + minimum interval between request starts."""
from __future__ import annotations

import asyncio
from typing import Optional


class AsyncRateLimiter:
    """Limit concurrent entries and enforce a minimum interval between them.

    Parameters
    ----------
    max_concurrency:
        Max simultaneous holders. ``<= 0`` disables the concurrency cap.
    min_interval_sec:
        Minimum seconds between successive acquisitions. ``<= 0`` disables
        interval spacing.
    """

    def __init__(self, max_concurrency: int, min_interval_sec: float) -> None:
        self._sem: Optional[asyncio.Semaphore] = (
            asyncio.Semaphore(max_concurrency) if max_concurrency and max_concurrency > 0 else None
        )
        self._min_interval = max(0.0, float(min_interval_sec))
        self._lock = asyncio.Lock()
        self._last_start: Optional[float] = None

    async def __aenter__(self) -> "AsyncRateLimiter":
        if self._sem is not None:
            await self._sem.acquire()
        if self._min_interval > 0:
            async with self._lock:
                loop = asyncio.get_event_loop()
                now = loop.time()
                if self._last_start is not None:
                    wait = self._min_interval - (now - self._last_start)
                    if wait > 0:
                        await asyncio.sleep(wait)
                        now = loop.time()
                self._last_start = now
        return self

    async def __aexit__(self, *exc) -> bool:
        if self._sem is not None:
            self._sem.release()
        return False
