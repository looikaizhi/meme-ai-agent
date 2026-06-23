"""Backtesting data contracts."""
from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel

from memedog.models import SignalType


class BacktestBar(BaseModel):
    """Single OHLCV observation for one token."""

    ts: AwareDatetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


class BacktestSignal(BaseModel):
    """Historical signal event used as a simulated entry trigger."""

    ts: AwareDatetime
    mint: str
    symbol: str
    signal: SignalType
    confidence: float
    price_usd: float | None = None
    trace_id: str = ""


class BacktestTrade(BaseModel):
    """Closed simulated trade emitted by a backtest."""

    mint: str
    symbol: str
    trace_id: str
    entry_ts: AwareDatetime
    exit_ts: AwareDatetime
    entry_price: float
    exit_price: float
    size_usd: float
    quantity: float
    pnl_usd: float
    pnl_pct: float
    exit_reason: Literal["TP", "SL", "TIMEOUT", "EOD"]


class BacktestResult(BaseModel):
    """Playbook-style strategy metrics for a completed backtest."""

    starting_balance_usd: float
    final_balance_usd: float
    total_return_usd: float
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    win_rate: float
    trade_count: int
    trades: list[BacktestTrade]
