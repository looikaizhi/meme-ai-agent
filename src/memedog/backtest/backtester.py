"""Signal backtester for MemeDog Radar.

The backtester replays historical price points after each signal using the same
entry and exit rules as PaperTrader: BULLISH + confidence threshold enters;
TP, SL, or max-hold timeout exits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Sequence

from pydantic import AwareDatetime, BaseModel

from memedog.config.settings import PaperTraderConfig
from memedog.models import Signal, SignalType, TradeRecord


class PricePoint(BaseModel):
    """Historical price sample for a token."""

    ts: AwareDatetime
    price: float


class BacktestReport(BaseModel):
    signals_seen: int
    trades_opened: int
    skipped_no_price: int
    total_pnl_usd: float
    avg_pnl_pct: float
    win_rate: float
    profit_factor: float | None
    max_drawdown_usd: float
    best_trade_pct: float | None
    worst_trade_pct: float | None
    trades: list[TradeRecord]


@dataclass
class _OpenTrade:
    signal: Signal
    entry_time: datetime
    entry_price: float


class Backtester:
    """Replay MemeDog signals over historical prices."""

    def __init__(self, cfg: PaperTraderConfig) -> None:
        self._cfg = cfg

    def run(
        self,
        signals: Sequence[Signal],
        price_history: Mapping[str, Sequence[PricePoint]],
    ) -> BacktestReport:
        """Backtest *signals* against per-mint historical price series.

        Price series must be keyed by canonical mint address. Each series is
        sorted internally, so callers do not need to pre-sort fixtures.
        """
        histories = {
            mint: sorted(points, key=lambda point: point.ts)
            for mint, points in price_history.items()
        }

        trades: list[TradeRecord] = []
        skipped_no_price = 0

        for signal in sorted(signals, key=lambda sig: sig.created_at):
            if signal.signal != SignalType.BULLISH:
                continue
            if signal.confidence < self._cfg.entry_min_confidence:
                continue

            points = histories.get(signal.mint, [])
            opened = self._open_trade(signal, points)
            if opened is None:
                skipped_no_price += 1
                continue

            rec = self._exit_trade(opened, points)
            if rec is None:
                skipped_no_price += 1
                continue
            trades.append(rec)

        return self._report(signals_seen=len(signals), skipped_no_price=skipped_no_price, trades=trades)

    def _open_trade(
        self, signal: Signal, points: Sequence[PricePoint]
    ) -> _OpenTrade | None:
        for point in points:
            if point.ts >= signal.created_at and point.price > 0:
                return _OpenTrade(
                    signal=signal,
                    entry_time=point.ts,
                    entry_price=point.price,
                )
        return None

    def _exit_trade(
        self, trade: _OpenTrade, points: Sequence[PricePoint]
    ) -> TradeRecord | None:
        deadline = trade.entry_time + timedelta(minutes=self._cfg.max_hold_minutes)
        take_profit_price = trade.entry_price * (1 + self._cfg.take_profit_pct)
        stop_loss_price = trade.entry_price * (1 - self._cfg.stop_loss_pct)

        last_seen: PricePoint | None = None
        for point in points:
            if point.ts < trade.entry_time:
                continue
            if point.ts > deadline:
                break

            last_seen = point
            if point.price >= take_profit_price:
                return self._record(trade, point.price, point.ts, "TP")
            if point.price <= stop_loss_price:
                return self._record(trade, point.price, point.ts, "SL")

        if last_seen is None:
            return None
        return self._record(trade, last_seen.price, last_seen.ts, "TIMEOUT")

    def _record(
        self,
        trade: _OpenTrade,
        exit_price: float,
        exit_time: datetime,
        exit_reason: str,
    ) -> TradeRecord:
        pnl_pct = (exit_price - trade.entry_price) / trade.entry_price
        return TradeRecord(
            mint=trade.signal.mint,
            symbol=trade.signal.symbol,
            entry_price=trade.entry_price,
            exit_price=exit_price,
            pnl_usd=self._cfg.size_usd * pnl_pct,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            entry_time=trade.entry_time,
            exit_time=exit_time,
        )

    @staticmethod
    def _report(
        signals_seen: int,
        skipped_no_price: int,
        trades: list[TradeRecord],
    ) -> BacktestReport:
        pnl_values = [trade.pnl_usd for trade in trades]
        pnl_pcts = [trade.pnl_pct for trade in trades]

        wins = [pnl for pnl in pnl_values if pnl > 0]
        losses = [pnl for pnl in pnl_values if pnl < 0]
        total_gain = sum(wins)
        total_loss = abs(sum(losses))
        profit_factor = None if total_loss == 0 else total_gain / total_loss

        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for pnl in pnl_values:
            equity += pnl
            peak = max(peak, equity)
            max_drawdown = min(max_drawdown, equity - peak)

        return BacktestReport(
            signals_seen=signals_seen,
            trades_opened=len(trades),
            skipped_no_price=skipped_no_price,
            total_pnl_usd=sum(pnl_values),
            avg_pnl_pct=sum(pnl_pcts) / len(pnl_pcts) if pnl_pcts else 0.0,
            win_rate=len(wins) / len(trades) if trades else 0.0,
            profit_factor=profit_factor,
            max_drawdown_usd=max_drawdown,
            best_trade_pct=max(pnl_pcts) if pnl_pcts else None,
            worst_trade_pct=min(pnl_pcts) if pnl_pcts else None,
            trades=trades,
        )
