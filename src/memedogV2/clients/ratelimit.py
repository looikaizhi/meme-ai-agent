from __future__ import annotations

import asyncio


class TokenBucket:
    """Simple async token-bucket. Conservative default suits gmgn's tight limits."""

    def __init__(self, rate_per_sec: float, capacity: int) -> None:
        self._rate = float(rate_per_sec)
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._lock = asyncio.Lock()
        self._last = asyncio.get_event_loop().time()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = asyncio.get_event_loop().time()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._last) * self._rate
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
