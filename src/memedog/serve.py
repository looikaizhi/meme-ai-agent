"""One-command local server: backend pipeline loop + Streamlit dashboard.

Usage:
    python -m memedog.serve [--demo] [--db PATH] [--port N] [--scan-interval S]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from memedog.app_factory import build_orchestrator, build_price_fn

logger = logging.getLogger(__name__)

_DASHBOARD = str(Path(__file__).resolve().parents[2] / "dashboard" / "app.py")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="memedog.serve")
    p.add_argument("--demo", action="store_true", help="offline demo mode (fixtures + replay LLM)")
    p.add_argument("--db", default=os.environ.get("MEMEDOG_DB", "memedog.db"))
    p.add_argument("--port", type=int, default=8501)
    p.add_argument("--scan-interval", type=int, default=None)
    return p.parse_args(argv)


def build_streamlit_cmd(port: int, dashboard_path: str) -> list[str]:
    return [
        sys.executable, "-m", "streamlit", "run", dashboard_path,
        "--server.port", str(port), "--server.headless", "true",
    ]


async def run_server(
    *,
    demo: bool,
    port: int,
    db_path: str,
    stop_event: asyncio.Event,
    scan_interval: int | None = None,
    popen=subprocess.Popen,
) -> None:
    """Run backend loop + streamlit subprocess until stop_event is set."""
    from memedog.clients.dexscreener import DexScreenerClient
    from memedog.config import load_config
    from memedog.observability.redaction import install_redaction
    from memedog.papertrader.watcher import PriceWatcher
    from memedog.store import Store

    os.environ["MEMEDOG_DB"] = db_path
    if demo:
        os.environ["MEMEDOG_DEMO"] = "1"

    cfg = load_config()
    install_redaction(cfg.settings)
    if scan_interval is not None:
        cfg.scanner.scan_interval_sec = scan_interval
    elif demo:
        cfg.scanner.scan_interval_sec = 3  # snappy demo cadence

    store = Store(db_path)
    orch = build_orchestrator(cfg, store, demo=demo)

    # Price source: real for production, random-walk for demo.
    dex_client = None
    if demo:
        from memedog.demo.demo_source import build_demo_price_fn
        price_fn = build_demo_price_fn()
    else:
        dex_client = DexScreenerClient()
        price_fn = build_price_fn(dex_client)

    watcher = PriceWatcher(store=store, trader=orch.paper_trader,
                           price_fn=price_fn, cfg=cfg.papertrader)

    proc = popen(build_streamlit_cmd(port, _DASHBOARD))
    logger.info("Streamlit launched on port %d (db=%s, demo=%s)", port, db_path, demo)

    async def _backend():
        tasks = [
            orch.run_forever(stop_event=stop_event),
            watcher.run(stop_event=stop_event),
        ]
        if getattr(orch, "feed", None) is not None:
            tasks.append(orch.feed.run(stop_event))
        await asyncio.gather(*tasks)

    backend_task = asyncio.create_task(_backend())
    try:
        await stop_event.wait()
    finally:
        backend_task.cancel()
        try:
            await backend_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        if dex_client is not None:
            await dex_client.aclose()
        store.close()
        logger.info("Server stopped.")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    args = parse_args(argv)
    stop_event = asyncio.Event()

    async def _run():
        await run_server(
            demo=args.demo, port=args.port, db_path=args.db,
            stop_event=stop_event, scan_interval=args.scan_interval,
        )

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nmemedog.serve: interrupted — shutting down", file=sys.stderr)


if __name__ == "__main__":
    main()
