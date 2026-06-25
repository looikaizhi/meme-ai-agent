"""Manual entrypoint for the V2 production path.

Usage:
  python -m memedogV2 <CA> <LP> [backend]          # backend: deepseek (default) | codex
  python -m memedogV2 --scan-file alert.txt [backend]
  python -m memedogV2 --backtest-db memedog.db --horizon-min 60

Requires GMGN_API_KEY in ~/.config/gmgn/.env, gmgn-cli installed; DEEPSEEK_API_KEY or codex login.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.config import load_v2_config
from memedogV2.harness.model_registry import build_backend
from memedogV2.harness.recorder import Recorder
from memedogV2.harness.runner import HarnessRunner
from memedogV2.intake import AddressIntake, IntakeProcessor
from memedogV2.scanner import LaunchScanner
from memedogV2.sources.gmgn_source import GmgnSource
from memedogV2.sources.helius_source import HeliusSource
from memedogV2.sources.resolver import DataResolver
from memedogV2.sources.rugcheck_source import RugCheckSource

_CFG = os.path.join(os.path.dirname(__file__), "config_thresholds.yaml")


def _build_runner(backend_name: str) -> HarnessRunner:
    cfg = load_v2_config(_CFG)
    cli = GmgnCli(rate_per_sec=cfg.gmgn["rate_limit_rps"], capacity=1,
                  cache_ttl_sec=cfg.gmgn["cache_ttl_sec"])
    resolver = DataResolver(sources={
        "rugcheck": RugCheckSource(),
        "gmgn": GmgnSource(cli=cli, max_retries=cfg.gmgn.get("max_retries", 2)),
        "helius": HeliusSource(),
    })
    return HarnessRunner(resolver=resolver,
                         backend=build_backend(backend_name, cwd=os.getcwd()),
                         hardfilter_cfg=cfg.hardfilter,
                         recorder=Recorder())


async def _main(ca: str, lp: str, backend_name: str) -> None:
    runner = _build_runner(backend_name)
    run = await runner.run(ca, lp)
    print(run.model_dump_json(indent=2))


async def _scan_file(path: str, backend_name: str) -> None:
    runner = _build_runner(backend_name)
    intake = AddressIntake()
    scanner = LaunchScanner(intake)
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as f:
            text = f.read()

    enqueued = scanner.enqueue_text(text)
    processor = IntakeProcessor(intake=intake, runner=runner)
    runs = await processor.drain_available()

    print(json.dumps({
        "seen": len(enqueued),
        "enqueued": sum(1 for item in enqueued if item.enqueued),
        "runs": [run.model_dump(mode="json") for run in runs],
    }, indent=2))


async def _backtest(db_path: str, horizon_min: int, limit: int) -> None:
    from memedog.app_factory import build_price_fn
    from memedog.clients.dexscreener import DexScreenerClient
    from memedogV2.backtest import evaluate_due_outcomes, summarize_outcomes
    from memedogV2.store import V2Store

    store = V2Store(db_path)
    dex = DexScreenerClient()
    try:
        outcomes = await evaluate_due_outcomes(
            store,
            price_fn=build_price_fn(dex),
            horizon_min=horizon_min,
            limit=limit,
        )
    finally:
        await dex.aclose()
        store.close()

    print(json.dumps({
        "evaluated": len(outcomes),
        "summary": summarize_outcomes(outcomes),
        "outcomes": outcomes,
    }, indent=2, default=str))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("args", nargs="*")
    parser.add_argument("--scan-file", help="GMGN-style launch alert text file, or '-' for stdin")
    parser.add_argument("--backtest-db", help="SQLite DB path with V2 runs to score")
    parser.add_argument("--horizon-min", type=int, default=60)
    parser.add_argument("--limit", type=int, default=25)
    return parser.parse_args(argv)


if __name__ == "__main__":
    ns = _parse_args(sys.argv[1:])
    if ns.backtest_db:
        asyncio.run(_backtest(ns.backtest_db, ns.horizon_min, ns.limit))
    elif ns.scan_file:
        backend = ns.args[0] if ns.args else "deepseek"
        asyncio.run(_scan_file(ns.scan_file, backend))
    elif len(ns.args) in (2, 3):
        backend = ns.args[2] if len(ns.args) == 3 else "deepseek"
        asyncio.run(_main(ns.args[0], ns.args[1], backend))
    else:
        print("usage: python -m memedogV2 <CA> <LP> [deepseek|codex]")
        print("   or: python -m memedogV2 --scan-file alert.txt [deepseek|codex]")
        print("   or: python -m memedogV2 --backtest-db memedog.db --horizon-min 60")
        sys.exit(2)
