import asyncio
import json

import pytest

from memedog.discovery.buffer import MintBuffer
from memedog.discovery.pumpportal import PumpPortalFeed


class _FakeWS:
    def __init__(self, messages, on_send=None):
        self._messages = list(messages)
        self._on_send = on_send
        self.sent = []

    async def send(self, data):
        self.sent.append(data)
        if self._on_send:
            self._on_send(data)

    def __aiter__(self):
        self._it = iter(self._messages)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _FakeConnect:
    def __init__(self, ws_factory):
        self._ws_factory = ws_factory
        self.calls = 0

    def __call__(self, url, **kw):
        self.calls += 1
        self._ws = self._ws_factory(self.calls)
        return self

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_run_fills_buffer_from_migration_messages():
    buf = MintBuffer(ttl_sec=60)
    stop = asyncio.Event()
    migration = json.dumps({"txType": "migrate", "mint": "MINT123", "pool": "pump-amm"})
    ack = json.dumps({"message": "Successfully subscribed"})

    feed = PumpPortalFeed(
        buf,
        url="wss://x",
        connect=_FakeConnect(lambda call_n: _FakeWS([ack, migration])),
        backoff_initial=0.001,
        backoff_max=0.002,
    )

    async def _stopper():
        await asyncio.sleep(0.05)
        stop.set()

    asyncio.create_task(_stopper())
    await asyncio.wait_for(feed.run(stop), timeout=2.0)

    assert "MINT123" in buf.recent()
    assert feed.recent_mints() == buf.recent()


@pytest.mark.asyncio
async def test_run_sends_subscribe_payload():
    buf = MintBuffer(ttl_sec=60)
    stop = asyncio.Event()
    sent_holder = {}

    feed = PumpPortalFeed(
        buf,
        url="wss://x",
        connect=_FakeConnect(
            lambda call_n: _FakeWS(
                [], on_send=lambda data: sent_holder.setdefault("payload", data)
            )
        ),
        backoff_initial=0.001,
        backoff_max=0.002,
    )

    async def _stopper():
        await asyncio.sleep(0.05)
        stop.set()

    asyncio.create_task(_stopper())
    await asyncio.wait_for(feed.run(stop), timeout=2.0)

    assert json.loads(sent_holder["payload"]) == {"method": "subscribeMigration"}


@pytest.mark.asyncio
async def test_run_reconnects_after_connection_error_without_raising():
    buf = MintBuffer(ttl_sec=60)
    stop = asyncio.Event()
    migration = json.dumps({"txType": "migrate", "mint": "AFTER_RECONNECT"})

    def ws_factory(call_n):
        if call_n == 1:
            raise ConnectionError("boom")
        return _FakeWS([migration])

    feed = PumpPortalFeed(
        buf,
        url="wss://x",
        connect=_FakeConnect(ws_factory),
        backoff_initial=0.001,
        backoff_max=0.002,
    )

    async def _stopper():
        await asyncio.sleep(0.08)
        stop.set()

    asyncio.create_task(_stopper())
    await asyncio.wait_for(feed.run(stop), timeout=2.0)

    assert "AFTER_RECONNECT" in buf.recent()
