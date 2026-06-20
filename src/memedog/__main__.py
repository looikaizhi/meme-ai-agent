"""MemeDog Radar — runnable entrypoint.

Usage:
    python -m memedog

Runs the Orchestrator (pipeline cycles) and PriceWatcher (position monitoring)
concurrently until interrupted (KeyboardInterrupt / SIGINT).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


async def main() -> None:
    """Build and run the full MemeDog Radar pipeline."""
    import logging as _logging

    _logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )

    from memedog.app_factory import build_orchestrator, build_price_fn
    from memedog.clients.dexscreener import DexScreenerClient
    from memedog.config.settings import load_config
    from memedog.papertrader.watcher import PriceWatcher
    from memedog.papertrader.trader import PaperTrader
    from memedog.store import Store

    cfg = load_config()
    db_path = os.environ.get("MEMEDOG_DB", "memedog.db")
    store = Store(db_path)

    logger.info("MemeDog Radar starting — db=%s", db_path)

    orch = build_orchestrator(cfg, store)

    # Build the price function and PriceWatcher
    dex_client = DexScreenerClient()
    price_fn = build_price_fn(dex_client)
    paper_trader = orch.paper_trader  # reuse the one already inside the orchestrator
    watcher = PriceWatcher(
        store=store,
        trader=paper_trader,
        price_fn=price_fn,
        cfg=cfg.papertrader,
    )

    stop_event = asyncio.Event()

    async def run_orch():
        await orch.run_forever(stop_event=stop_event)

    async def run_watcher():
        await watcher.run(stop_event=stop_event)

    try:
        await asyncio.gather(run_orch(), run_watcher())
    except asyncio.CancelledError:
        logger.info("MemeDog Radar: tasks cancelled — shutting down")
    finally:
        await dex_client.aclose()
        store.close()
        logger.info("MemeDog Radar stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nMemeDog Radar: interrupted by user", file=sys.stderr)
