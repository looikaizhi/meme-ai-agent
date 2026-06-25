from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from memedog.discovery.gmgn_telegram import GMGNTelegramFeed
from memedog.config import load_config
from memedog.observability.redaction import install_redaction
from memedogV2.__main__ import _build_runner
from memedogV2.intake import AddressIntake, IntakeProcessor
from memedogV2.scanner import IntakeBufferAdapter
from memedogV2.store import V2Store

logger = logging.getLogger(__name__)

_DASHBOARD = str(Path(__file__).resolve().parents[2] / "dashboard" / "app.py")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="memedogV2.serve")
    parser.add_argument("--backend", default="codex", choices=["codex", "deepseek"])
    parser.add_argument("--db", default=os.environ.get("MEMEDOG_DB", "memedog.db"))
    parser.add_argument("--port", type=int, default=8501)
    return parser.parse_args(argv)


def build_streamlit_cmd(port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        _DASHBOARD,
        "--server.port",
        str(port),
        "--server.headless",
        "true",
    ]


def build_telegram_feed(*, intake: AddressIntake, store: V2Store):
    cfg = load_config()
    install_redaction(cfg.settings)

    api_id = cfg.settings.telegram_api_id
    api_hash = cfg.settings.telegram_api_hash
    if not api_id or not api_hash:
        raise RuntimeError("TELEGRAM_API_ID/TELEGRAM_API_HASH missing")

    buffer = IntakeBufferAdapter(intake, store=store)
    return GMGNTelegramFeed(
        buffer,
        api_id=api_id,
        api_hash=api_hash,
        session=cfg.settings.telegram_session or "memedog_gmgn",
        chat=cfg.discovery.gmgn_chats or cfg.discovery.gmgn_chat,
        backoff_initial=cfg.discovery.reconnect_backoff_initial_sec,
        backoff_max=cfg.discovery.reconnect_backoff_max_sec,
        backfill_limit=cfg.discovery.gmgn_backfill_limit,
        max_open_age_min=cfg.discovery.gmgn_max_open_age_min,
        launch_only=True,
    )


async def _worker(processor: IntakeProcessor, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        if processor.pending() == 0:
            await asyncio.sleep(1.0)
            continue
        try:
            await processor.process_next()
        except Exception as exc:
            logger.warning("V2 intake processor error: %s", exc, exc_info=True)


async def run_server(
    *,
    backend: str,
    port: int,
    db_path: str,
    stop_event: asyncio.Event,
    popen=subprocess.Popen,
) -> None:
    os.environ["MEMEDOG_DB"] = db_path
    os.environ["MEMEDOG_V2"] = "1"

    store = V2Store(db_path)
    intake = AddressIntake()
    runner = _build_runner(backend)
    processor = IntakeProcessor(intake=intake, runner=runner, store=store)
    feed = build_telegram_feed(intake=intake, store=store)

    proc = popen(build_streamlit_cmd(port))
    logger.info("memedogV2 dashboard launched on port %d (db=%s)", port, db_path)

    tasks = [
        asyncio.create_task(feed.run(stop_event)),
        asyncio.create_task(_worker(processor, stop_event)),
    ]
    try:
        await stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            proc.terminate()
        except Exception:
            pass
        store.close()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stderr,
    )
    args = parse_args(argv)
    stop_event = asyncio.Event()

    async def _run():
        await run_server(
            backend=args.backend,
            port=args.port,
            db_path=args.db,
            stop_event=stop_event,
        )

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nmemedogV2.serve: interrupted - shutting down", file=sys.stderr)


if __name__ == "__main__":
    main()
