import asyncio
import pytest
from memedogV2.clients.ratelimit import TokenBucket


@pytest.mark.asyncio
async def test_bucket_allows_burst_then_throttles():
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    b = TokenBucket(rate_per_sec=10.0, capacity=2)
    await b.acquire()        # immediate (capacity)
    await b.acquire()        # immediate (capacity)
    await b.acquire()        # must wait ~0.1s for a refill
    elapsed = loop.time() - t0
    assert elapsed >= 0.08
