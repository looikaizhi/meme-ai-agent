"""Tests for AsyncRateLimiter (concurrency cap + min interval)."""
import asyncio
import time

import pytest

from memedog.clients.ratelimit import AsyncRateLimiter


async def test_concurrency_cap_limits_simultaneous_entries():
    limiter = AsyncRateLimiter(max_concurrency=2, min_interval_sec=0.0)
    concurrent = 0
    peak = 0

    async def worker():
        nonlocal concurrent, peak
        async with limiter:
            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0.05)
            concurrent -= 1

    await asyncio.gather(*(worker() for _ in range(6)))
    assert peak <= 2


async def test_min_interval_spaces_sequential_acquires():
    limiter = AsyncRateLimiter(max_concurrency=10, min_interval_sec=0.05)
    start = time.monotonic()
    for _ in range(3):
        async with limiter:
            pass
    elapsed = time.monotonic() - start
    # 3 acquires → at least 2 inter-acquire gaps of 0.05s
    assert elapsed >= 0.09


async def test_zero_settings_no_limit():
    limiter = AsyncRateLimiter(max_concurrency=0, min_interval_sec=0.0)
    # Should not block at all
    async with limiter:
        pass
    async with limiter:
        pass
