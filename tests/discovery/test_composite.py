import asyncio

import pytest

from memedog.discovery.buffer import MintBuffer
from memedog.discovery.composite import CompositeFeed


class _ToyFeed:
    def __init__(self, buffer, mints):
        self._buffer = buffer
        self._mints = mints

    def recent_mints(self):
        return self._buffer.recent()

    async def run(self, stop_event):
        for mint in self._mints:
            self._buffer.add(mint)
        await stop_event.wait()


@pytest.mark.asyncio
async def test_composite_merges_and_dedups():
    buf = MintBuffer(ttl_sec=60)
    f1 = _ToyFeed(buf, ["A", "B"])
    f2 = _ToyFeed(buf, ["B", "C"])
    comp = CompositeFeed([f1, f2], buffer=buf)
    stop = asyncio.Event()

    async def _stopper():
        await asyncio.sleep(0.05)
        stop.set()

    asyncio.create_task(_stopper())
    await asyncio.wait_for(comp.run(stop), timeout=2.0)

    assert sorted(comp.recent_mints()) == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_composite_one_feed_failing_does_not_break_others():
    buf = MintBuffer(ttl_sec=60)

    class _Boom:
        def recent_mints(self):
            return buf.recent()

        async def run(self, stop_event):
            raise RuntimeError("feed down")

    good = _ToyFeed(buf, ["GOOD"])
    comp = CompositeFeed([_Boom(), good], buffer=buf)
    stop = asyncio.Event()

    async def _stopper():
        await asyncio.sleep(0.05)
        stop.set()

    asyncio.create_task(_stopper())
    await asyncio.wait_for(comp.run(stop), timeout=2.0)
    assert "GOOD" in comp.recent_mints()
