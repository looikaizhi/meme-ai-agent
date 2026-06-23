"""Live discovery tests. Run with: python -m pytest -m live tests/live/test_live_discovery.py -v"""
from __future__ import annotations

import asyncio

import pytest

from memedog.config import load_config
from memedog.discovery.buffer import MintBuffer
from memedog.discovery.helius_feed import HeliusMigrationFeed
from memedog.discovery.pumpportal import PumpPortalFeed

pytestmark = pytest.mark.live


async def test_live_pumpportal_connects_and_subscribes():
    cfg = load_config()
    buf = MintBuffer(ttl_sec=120)
    feed = PumpPortalFeed(
        buf,
        url=cfg.discovery.pumpportal_ws_url,
        backoff_initial=1.0,
        backoff_max=5.0,
    )
    stop = asyncio.Event()

    async def _stop_later():
        await asyncio.sleep(40)
        stop.set()

    task = asyncio.create_task(_stop_later())
    try:
        await asyncio.wait_for(feed.run(stop), timeout=60)
    except asyncio.TimeoutError:
        pass
    finally:
        stop.set()
        task.cancel()
    assert all(isinstance(mint, str) and mint for mint in buf.recent())


async def test_live_helius_connects():
    cfg = load_config()
    if not (cfg.discovery.helius_enabled and cfg.settings.helius_api_key):
        pytest.skip("HELIUS_API_KEY not set or Helius disabled")
    buf = MintBuffer(ttl_sec=120)
    url = cfg.discovery.helius_ws_url.format(api_key=cfg.settings.helius_api_key)
    feed = HeliusMigrationFeed(
        buf,
        url=url,
        program_id=cfg.discovery.pumpfun_program_id,
        backoff_initial=1.0,
        backoff_max=5.0,
    )
    stop = asyncio.Event()

    async def _stop_later():
        await asyncio.sleep(15)
        stop.set()

    task = asyncio.create_task(_stop_later())
    try:
        await asyncio.wait_for(feed.run(stop), timeout=30)
    except asyncio.TimeoutError:
        pass
    finally:
        stop.set()
        task.cancel()
    assert all(isinstance(mint, str) and mint for mint in buf.recent())
