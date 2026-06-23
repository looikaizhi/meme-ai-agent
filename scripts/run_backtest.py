#!/usr/bin/env python
"""Run a local MemeDog signal backtest from JSON bars and signals."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from memedog.backtesting import BacktestBar, BacktestEngine, BacktestSignal  # noqa: E402
from memedog.config.settings import load_config  # noqa: E402


def _load_list(path: Path, model):
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must contain a JSON array")
    return [model.model_validate(item) for item in raw]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backtest MemeDog signals over OHLCV bars using PaperTrader rules."
    )
    parser.add_argument("--bars", required=True, type=Path, help="JSON array of OHLCV bars")
    parser.add_argument(
        "--signals", required=True, type=Path, help="JSON array of signal events"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional thresholds.yaml path; defaults to packaged config",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    bars = _load_list(args.bars, BacktestBar)
    signals = _load_list(args.signals, BacktestSignal)
    result = BacktestEngine(cfg.papertrader).run(bars=bars, signals=signals)
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
