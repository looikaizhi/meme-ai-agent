"""Run a local Bitget-data backtest demo and save it for the dashboard.

This is a lightweight bridge for hackathon demos: it fetches real Bitget spot
candles, creates simple momentum-style MemeDog signals, runs the local
Backtester, and persists the report into ``Store.backtest_reports``.

Usage:
    MEMEDOG_DB=/private/tmp/memedog-demo.db python scripts/run_bitget_playbook_demo.py
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import httpx

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from memedog.backtest import Backtester, PricePoint
from memedog.config.settings import load_config
from memedog.models import Signal, SignalType
from memedog.store import Store

_BITGET_CANDLES_URL = "https://api.bitget.com/api/v2/spot/market/candles"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="DOGEUSDT", help="Bitget spot symbol")
    parser.add_argument("--granularity", default="1h", help="Bitget candle granularity")
    parser.add_argument("--limit", type=int, default=200, help="Number of candles")
    parser.add_argument("--db", default=os.environ.get("MEMEDOG_DB", "memedog.db"))
    parser.add_argument(
        "--save-paper-trades",
        action="store_true",
        help="Also save simulated backtest trades into the Paper Trading table",
    )
    return parser.parse_args()


def _fetch_bitget_candles(
    symbol: str,
    granularity: str,
    limit: int,
) -> list[dict]:
    response = httpx.get(
        _BITGET_CANDLES_URL,
        params={"symbol": symbol, "granularity": granularity, "limit": str(limit)},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != "00000":
        raise RuntimeError(f"Bitget candle request failed: {payload}")

    candles = []
    for row in payload.get("data", []):
        candles.append(
            {
                "ts": datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )
    return sorted(candles, key=lambda item: item["ts"])


def _build_signals(symbol: str, candles: list[dict]) -> list[Signal]:
    if len(candles) < 6:
        return []

    volumes = [candle["volume"] for candle in candles]
    volume_floor = median(volumes)
    mint = f"bitget:spot:{symbol}"
    display_symbol = symbol.replace("USDT", "/USDT")
    signals: list[Signal] = []
    last_signal_idx = -999

    for idx in range(3, len(candles) - 3):
        if idx - last_signal_idx < 12:
            continue

        c0 = candles[idx - 2]["close"]
        c1 = candles[idx - 1]["close"]
        c2 = candles[idx]["close"]
        volume = candles[idx]["volume"]
        momentum = (c2 - c0) / c0 if c0 else 0.0

        if c0 < c1 < c2 and volume >= volume_floor and momentum > 0.002:
            confidence = min(0.95, 0.72 + momentum * 10)
            signals.append(
                Signal(
                    mint=mint,
                    symbol=display_symbol,
                    signal=SignalType.BULLISH,
                    confidence=confidence,
                    score_total=min(95.0, 70.0 + momentum * 1_000),
                    bull_points=[
                        f"Bitget {symbol} 3-candle close momentum is positive",
                        "Volume is above the sampled median",
                    ],
                    bear_points=[
                        "This demo signal uses exchange candles only",
                        "No on-chain holder or contract safety data is included",
                    ],
                    red_flags=[],
                    rationale=(
                        "Local Playbook demo signal generated from real Bitget OHLCV "
                        "to validate backtest/dashboard plumbing."
                    ),
                    created_at=candles[idx]["ts"],
                    trace_id=f"bitget-playbook-demo-{symbol}-{idx}",
                )
            )
            last_signal_idx = idx

    if not signals:
        first = candles[0]
        signals.append(
            Signal(
                mint=mint,
                symbol=display_symbol,
                signal=SignalType.BULLISH,
                confidence=0.75,
                score_total=70.0,
                bull_points=["Fallback demo signal created from real Bitget candles"],
                bear_points=["No momentum trigger was found in the sampled window"],
                red_flags=[],
                rationale="Fallback signal so the dashboard can display a real-data report.",
                created_at=first["ts"],
                trace_id=f"bitget-playbook-demo-{symbol}-fallback",
            )
        )
    return signals


def main() -> None:
    args = _parse_args()
    cfg = load_config()
    candles = _fetch_bitget_candles(args.symbol, args.granularity, args.limit)
    if not candles:
        raise RuntimeError("Bitget returned no candles")

    mint = f"bitget:spot:{args.symbol}"
    price_history = {
        mint: [
            PricePoint(ts=candle["ts"], price=candle["close"])
            for candle in candles
            if candle["close"] > 0
        ]
    }
    signals = _build_signals(args.symbol, candles)
    report = Backtester(cfg.papertrader).run(signals, price_history)

    store = Store(args.db)
    try:
        name = f"Bitget {args.symbol} Real OHLCV Backtest"
        store.save_backtest_report(name, report)
        if args.save_paper_trades:
            for trade in report.trades:
                store.save_trade(trade)
    finally:
        store.close()

    print(f"Saved report: {name}")
    print(f"DB: {args.db}")
    print(f"Candles: {len(candles)}")
    print(f"Signals: {report.signals_seen}")
    print(f"Trades: {report.trades_opened}")
    print(f"Saved paper trades: {report.trades_opened if args.save_paper_trades else 0}")
    print(f"Total PnL USD: {report.total_pnl_usd:+.2f}")
    print(f"Win rate: {report.win_rate:.1%}")


if __name__ == "__main__":
    main()
