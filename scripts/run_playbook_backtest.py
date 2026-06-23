#!/usr/bin/env python
"""Upload a Playbook package to Bitget GetAgent and run a hosted backtest."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from memedog.backtesting.playbook import (  # noqa: E402
    PLAYBOOK_API_BASE_URL,
    PlaybookClient,
    assert_safe_backtest_playbook,
    build_playbook_archive,
    mask_access_key,
)
from memedog.config.settings import load_config  # noqa: E402


def _access_key(env_name: str | None) -> str:
    if env_name:
        value = os.environ.get(env_name)
        if value:
            return value

    cfg_value = load_config().settings.bitget_playbook_access_key
    if cfg_value:
        return cfg_value

    for name in ("BITGET_PLAYBOOK_ACCESS_KEY", "PLAYBOOK_API_KEY", "BITGET_ACCESS_KEY"):
        value = os.environ.get(name)
        if value:
            return value

    raise SystemExit(
        "Missing Bitget Playbook key. Set BITGET_PLAYBOOK_ACCESS_KEY, "
        "PLAYBOOK_API_KEY, or BITGET_ACCESS_KEY."
    )


def _summary(uploaded: dict, dispatched: dict, result: dict) -> dict:
    signal = (result.get("signal_output") or [{}])[0]
    metrics = result.get("metrics_output") or {}
    summary = metrics.get("summary") or metrics
    return {
        "upload": {
            "strategy_id": uploaded.get("strategy_id"),
            "draft_id": uploaded.get("draft_id"),
            "status": uploaded.get("status"),
            "suggested_version": uploaded.get("suggested_version"),
        },
        "dispatch": {
            "run_id": dispatched.get("run_id"),
            "version_id": dispatched.get("version_id"),
            "status": dispatched.get("status"),
        },
        "run": {
            "run_id": result.get("run_id"),
            "status": result.get("status"),
            "active_runtime_ms": result.get("active_runtime_ms"),
            "failure_reason": result.get("failure_reason"),
            "signal_action": signal.get("action"),
            "signal_symbol": signal.get("symbol"),
            "signal_confidence": signal.get("confidence"),
            "total_return_pct": summary.get("total_return_pct")
            if summary
            else result.get("total_return_pct"),
            "sharpe_ratio": summary.get("sharpe_ratio")
            if summary
            else result.get("sharpe_ratio"),
            "max_drawdown_pct": summary.get("max_drawdown_pct")
            if summary
            else result.get("max_drawdown_pct"),
            "win_rate": summary.get("win_rate") if summary else result.get("win_rate"),
            "total_trades": summary.get("total_trades")
            if summary
            else result.get("total_trades"),
            "starting_balance": summary.get("starting_balance")
            if summary
            else result.get("starting_balance"),
            "ending_balance": summary.get("ending_balance")
            if summary
            else result.get("ending_balance"),
            "net_pnl": summary.get("net_pnl") if summary else result.get("net_pnl"),
            "metrics_basis": result.get("metrics_basis"),
            "margin_budget": result.get("margin_budget"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build, upload, and run a Bitget GetAgent Playbook backtest."
    )
    parser.add_argument(
        "--playbook-dir",
        type=Path,
        default=ROOT / "playbooks" / "memedog-bitget-momentum",
    )
    parser.add_argument("--archive", type=Path, default=None)
    parser.add_argument("--access-key-env", default=None)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    parser.add_argument("--timeout-sec", type=float, default=300.0)
    parser.add_argument(
        "--full-json",
        action="store_true",
        help="Print the full Bitget run payload instead of a compact summary",
    )
    args = parser.parse_args()

    access_key = _access_key(args.access_key_env)
    assert_safe_backtest_playbook(args.playbook_dir)
    archive = build_playbook_archive(args.playbook_dir, args.archive)
    name = args.playbook_dir.name
    print(
        f"upload draft {name} -> GetAgent prod {PLAYBOOK_API_BASE_URL} "
        f"with ACCESS-KEY={mask_access_key(access_key)}"
    )

    with PlaybookClient(access_key) as client:
        uploaded = client.upload_package(archive)
        version_id = uploaded.get("draft_id") or uploaded.get("version_id")
        if not version_id:
            raise SystemExit(f"Upload response did not include draft_id: {uploaded}")

        dispatched = client.start_run(str(version_id))
        run_id = dispatched.get("run_id")
        if not run_id:
            raise SystemExit(f"Run response did not include run_id: {dispatched}")

        result = client.poll_run(
            str(run_id),
            poll_sec=args.poll_sec,
            timeout_sec=args.timeout_sec,
        )

    payload = (
        {"upload": uploaded, "dispatch": dispatched, "run": result}
        if args.full_json
        else _summary(uploaded, dispatched, result)
    )
    print(json.dumps(payload, indent=2))
    if result.get("status") == "failed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
