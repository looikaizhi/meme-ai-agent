"""Manual entrypoint for the V2 production path.

Usage:
  python -m memedogV2 <CA> <LP> [backend]          # backend: deepseek (default) | codex
  python -m memedogV2 --scan-file alert.txt [backend]
  python -m memedogV2 --gmgn-market trending --limit 5 --backend codex --db memedog.db
  python -m memedogV2 --candidate-file addresses.txt --backend codex --db memedog.db
  python -m memedogV2 --backtest-db memedog.db --horizon-min 60

Requires GMGN_API_KEY in ~/.config/gmgn/.env, gmgn-cli installed; DEEPSEEK_API_KEY or codex login.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from memedogV2.candidates import (
    MarketCandidate,
    extract_market_candidates,
    fetch_gmgn_market_candidates,
)
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


async def _run_candidates(
    candidates: list[MarketCandidate],
    *,
    backend_name: str,
    db_path: str,
    limit: int | None = None,
) -> None:
    from memedogV2.store import V2Store

    runner = _build_runner(backend_name)
    store = V2Store(db_path)
    intake = AddressIntake()
    processor = IntakeProcessor(intake=intake, runner=runner, store=store)
    selected = candidates[:limit] if limit is not None else candidates

    scanner_rows = []
    try:
        for candidate in selected:
            trace_id = intake.enqueue(
                candidate.ca_address,
                candidate.lp_address,
                source=candidate.source,
                stage=candidate.stage,
            )
            store.save_scanner_item(
                source=candidate.source,
                ca_address=candidate.ca_address,
                lp_address=candidate.lp_address,
                trace_id=trace_id,
                enqueued=bool(trace_id),
                raw_text=json.dumps(candidate.raw, default=str),
            )
            scanner_rows.append({
                "ca_address": candidate.ca_address,
                "lp_address": candidate.lp_address,
                "source": candidate.source,
                "stage": candidate.stage,
                "trace_id": trace_id,
                "enqueued": bool(trace_id),
            })

        runs = await processor.drain_available(limit=limit)
    finally:
        store.close()

    print(json.dumps({
        "db": db_path,
        "seen": len(selected),
        "enqueued": sum(1 for item in scanner_rows if item["enqueued"]),
        "candidates": scanner_rows,
        "runs": [run.model_dump(mode="json") for run in runs],
    }, indent=2))


async def _gmgn_market(args: argparse.Namespace, backend_name: str) -> None:
    candidates = await fetch_gmgn_market_candidates(
        args.gmgn_market,
        chain=args.chain,
        limit=args.limit,
        interval=args.interval,
        order_by=args.order_by,
        direction=args.direction,
        filters=args.filter,
        platforms=args.platform,
        signal_types=args.signal_type,
        trenches_types=args.trenches_type,
        filter_preset=args.filter_preset,
        sort_by=args.sort_by,
    )
    await _run_candidates(
        candidates,
        backend_name=backend_name,
        db_path=args.db,
        limit=args.limit,
    )


def _load_candidate_file(path: str, *, source: str = "candidate_file") -> list[MarketCandidate]:
    if path == "-":
        text = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    stripped = text.strip()
    if not stripped:
        return []

    if stripped[0] in "[{":
        payload = json.loads(stripped)
        if isinstance(payload, list) and all(isinstance(item, str) for item in payload):
            return [
                MarketCandidate(ca_address=item, source=source)
                for item in payload
                if item
            ]
        return extract_market_candidates(payload, source=source, limit=None)

    candidates = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        if parts:
            lp = parts[1] if len(parts) > 1 else ""
            candidates.append(
                MarketCandidate(ca_address=parts[0], lp_address=lp, source=source)
            )
    return candidates


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
    parser.add_argument("--candidate", action="append", default=[],
                        help="Candidate CA to run directly; repeatable. Use CA or CA:LP.")
    parser.add_argument("--candidate-file",
                        help="Text/JSON candidates to run directly, or '-' for stdin")
    parser.add_argument("--cohort", help="Label for curated candidate runs, e.g. famous-memes or bad-memes")
    parser.add_argument("--gmgn-market", choices=["trending", "signal", "trenches"],
                        help="Fetch live GMGN market candidates and run them directly")
    parser.add_argument("--backend", choices=["deepseek", "codex"],
                        help="LLM backend for direct, file, scan, or market runs")
    parser.add_argument("--db", default=os.environ.get("MEMEDOG_DB", "memedog.db"),
                        help="SQLite DB path for persisted candidate batch runs")
    parser.add_argument("--chain", default="sol")
    parser.add_argument("--interval", default="5m",
                        help="GMGN trending interval: 1m, 5m, 1h, 6h, 24h")
    parser.add_argument("--order-by", dest="order_by")
    parser.add_argument("--direction")
    parser.add_argument("--filter", action="append", default=[])
    parser.add_argument("--platform", action="append", default=[])
    parser.add_argument("--signal-type", type=int, action="append", default=[])
    parser.add_argument("--trenches-type", action="append", default=[])
    parser.add_argument("--filter-preset")
    parser.add_argument("--sort-by", dest="sort_by")
    parser.add_argument("--backtest-db", help="SQLite DB path with V2 runs to score")
    parser.add_argument("--horizon-min", type=int, default=60)
    parser.add_argument("--limit", type=int, default=25)
    return parser.parse_args(argv)


if __name__ == "__main__":
    ns = _parse_args(sys.argv[1:])
    backend = ns.backend or (ns.args[0] if ns.args else "deepseek")
    if ns.backtest_db:
        asyncio.run(_backtest(ns.backtest_db, ns.horizon_min, ns.limit))
    elif ns.gmgn_market:
        asyncio.run(_gmgn_market(ns, backend))
    elif ns.candidate_file or ns.candidate:
        direct = []
        source = f"cohort:{ns.cohort}" if ns.cohort else "candidate_arg"
        for raw in ns.candidate:
            ca, sep, lp = raw.partition(":")
            direct.append(MarketCandidate(ca_address=ca, lp_address=lp if sep else "",
                                          source=source))
        file_source = f"cohort:{ns.cohort}" if ns.cohort else "candidate_file"
        file_candidates = (
            _load_candidate_file(ns.candidate_file, source=file_source)
            if ns.candidate_file else []
        )
        asyncio.run(_run_candidates(
            [*direct, *file_candidates],
            backend_name=backend,
            db_path=ns.db,
            limit=ns.limit,
        ))
    elif ns.scan_file:
        asyncio.run(_scan_file(ns.scan_file, backend))
    elif len(ns.args) in (2, 3):
        direct_backend = ns.backend or (ns.args[2] if len(ns.args) == 3 else "deepseek")
        asyncio.run(_main(ns.args[0], ns.args[1], direct_backend))
    else:
        print("usage: python -m memedogV2 <CA> <LP> [deepseek|codex]")
        print("   or: python -m memedogV2 --scan-file alert.txt [deepseek|codex]")
        print("   or: python -m memedogV2 --gmgn-market trending --limit 5 --backend codex --db memedog.db")
        print("   or: python -m memedogV2 --candidate-file addresses.txt --backend codex --db memedog.db")
        print("   or: python -m memedogV2 --backtest-db memedog.db --horizon-min 60")
        sys.exit(2)
