"""Deterministic backtester for MemeDog paper-trading rules."""
from __future__ import annotations

import math
from datetime import timedelta
from statistics import fmean, pstdev
from typing import Iterable

from memedog.backtesting.models import BacktestBar, BacktestResult, BacktestSignal, BacktestTrade
from memedog.config.settings import PaperTraderConfig
from memedog.models import SignalType


class BacktestEngine:
    """Replay historical signals over OHLCV bars using PaperTrader settings."""

    def __init__(self, cfg: PaperTraderConfig) -> None:
        self._cfg = cfg

    def run(
        self,
        bars: Iterable[BacktestBar],
        signals: Iterable[BacktestSignal],
    ) -> BacktestResult:
        ordered_bars = sorted(bars, key=lambda bar: bar.ts)
        ordered_signals = sorted(signals, key=lambda signal: signal.ts)

        trades: list[BacktestTrade] = []
        last_exit_ts = None
        for signal in ordered_signals:
            if signal.signal != SignalType.BULLISH:
                continue
            if signal.confidence < self._cfg.entry_min_confidence:
                continue

            entry_idx = self._entry_index(ordered_bars, signal.ts)
            if entry_idx is None:
                continue

            entry_bar = ordered_bars[entry_idx]
            if last_exit_ts is not None and entry_bar.ts <= last_exit_ts:
                continue

            entry_price = signal.price_usd if signal.price_usd is not None else entry_bar.open
            if entry_price <= 0:
                continue

            trade = self._simulate_trade(
                signal=signal,
                bars=ordered_bars[entry_idx:],
                entry_price=entry_price,
            )
            trades.append(trade)
            last_exit_ts = trade.exit_ts

        return self._result(trades)

    @staticmethod
    def _entry_index(bars: list[BacktestBar], signal_ts) -> int | None:
        for idx, bar in enumerate(bars):
            if bar.ts >= signal_ts:
                return idx
        return None

    def _simulate_trade(
        self,
        signal: BacktestSignal,
        bars: list[BacktestBar],
        entry_price: float,
    ) -> BacktestTrade:
        entry_bar = bars[0]
        deadline = entry_bar.ts + timedelta(minutes=self._cfg.max_hold_minutes)
        stop_price = entry_price * (1 - self._cfg.stop_loss_pct)
        take_profit_price = entry_price * (1 + self._cfg.take_profit_pct)

        for bar in bars:
            if bar.low <= stop_price:
                return self._trade(
                    signal=signal,
                    entry_ts=entry_bar.ts,
                    exit_ts=bar.ts,
                    entry_price=entry_price,
                    exit_price=stop_price,
                    exit_reason="SL",
                )
            if bar.high >= take_profit_price:
                return self._trade(
                    signal=signal,
                    entry_ts=entry_bar.ts,
                    exit_ts=bar.ts,
                    entry_price=entry_price,
                    exit_price=take_profit_price,
                    exit_reason="TP",
                )
            if bar.ts >= deadline:
                return self._trade(
                    signal=signal,
                    entry_ts=entry_bar.ts,
                    exit_ts=bar.ts,
                    entry_price=entry_price,
                    exit_price=bar.close,
                    exit_reason="TIMEOUT",
                )

        last_bar = bars[-1]
        return self._trade(
            signal=signal,
            entry_ts=entry_bar.ts,
            exit_ts=last_bar.ts,
            entry_price=entry_price,
            exit_price=last_bar.close,
            exit_reason="EOD",
        )

    def _trade(
        self,
        signal: BacktestSignal,
        entry_ts,
        exit_ts,
        entry_price: float,
        exit_price: float,
        exit_reason: str,
    ) -> BacktestTrade:
        pnl_pct = (exit_price - entry_price) / entry_price
        quantity = self._cfg.size_usd / entry_price
        pnl_usd = self._cfg.size_usd * pnl_pct
        return BacktestTrade(
            mint=signal.mint,
            symbol=signal.symbol,
            trace_id=signal.trace_id,
            entry_ts=entry_ts,
            exit_ts=exit_ts,
            entry_price=entry_price,
            exit_price=exit_price,
            size_usd=self._cfg.size_usd,
            quantity=quantity,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,  # type: ignore[arg-type]
        )

    def _result(self, trades: list[BacktestTrade]) -> BacktestResult:
        starting_balance = self._cfg.starting_balance_usd
        equity = starting_balance
        peak = starting_balance
        max_drawdown = 0.0

        for trade in trades:
            equity += trade.pnl_usd
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)

        returns = [trade.pnl_pct for trade in trades]
        sharpe = 0.0
        if len(returns) >= 2:
            std = pstdev(returns)
            if std > 0:
                sharpe = fmean(returns) / std * math.sqrt(len(returns))

        total_return_usd = equity - starting_balance
        total_return_pct = total_return_usd / starting_balance if starting_balance else 0.0
        win_rate = (
            sum(1 for trade in trades if trade.pnl_usd > 0) / len(trades)
            if trades
            else 0.0
        )

        return BacktestResult(
            starting_balance_usd=starting_balance,
            final_balance_usd=equity,
            total_return_usd=total_return_usd,
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_drawdown,
            sharpe=sharpe,
            win_rate=win_rate,
            trade_count=len(trades),
            trades=trades,
        )
