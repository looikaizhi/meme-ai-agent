from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from memedog.backtesting import BacktestBar, BacktestEngine, BacktestSignal
from memedog.config.settings import PaperTraderConfig
from memedog.models import SignalType


@pytest.fixture
def cfg() -> PaperTraderConfig:
    return PaperTraderConfig(
        entry_min_confidence=0.60,
        size_usd=100.0,
        take_profit_pct=0.50,
        stop_loss_pct=0.25,
        max_hold_minutes=10,
        price_poll_sec=30,
        starting_balance_usd=10000.0,
    )


def _ts(minutes: int = 0) -> datetime:
    return datetime(2026, 6, 23, 0, minutes, tzinfo=timezone.utc)


def _bar(minutes: int, open_: float, high: float, low: float, close: float) -> BacktestBar:
    return BacktestBar(
        ts=_ts(minutes),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000.0,
    )


def _signal(
    minutes: int = 0,
    signal: SignalType = SignalType.BULLISH,
    confidence: float = 0.80,
    price_usd: float | None = 1.0,
) -> BacktestSignal:
    return BacktestSignal(
        ts=_ts(minutes),
        mint="MINT_A",
        symbol="DOG",
        signal=signal,
        confidence=confidence,
        price_usd=price_usd,
        trace_id="trace-1",
    )


def test_backtest_opens_bullish_signal_and_exits_take_profit(
    cfg: PaperTraderConfig,
) -> None:
    result = BacktestEngine(cfg).run(
        bars=[
            _bar(0, open_=1.0, high=1.10, low=0.95, close=1.05),
            _bar(5, open_=1.05, high=1.60, low=1.00, close=1.55),
        ],
        signals=[_signal()],
    )

    assert result.trade_count == 1
    trade = result.trades[0]
    assert trade.exit_reason == "TP"
    assert trade.exit_price == pytest.approx(1.50)
    assert trade.pnl_usd == pytest.approx(50.0)
    assert result.win_rate == pytest.approx(1.0)


def test_backtest_uses_stop_loss_when_same_bar_touches_tp_and_sl(
    cfg: PaperTraderConfig,
) -> None:
    result = BacktestEngine(cfg).run(
        bars=[_bar(0, open_=1.0, high=1.60, low=0.70, close=1.20)],
        signals=[_signal()],
    )

    trade = result.trades[0]
    assert trade.exit_reason == "SL"
    assert trade.exit_price == pytest.approx(0.75)
    assert trade.pnl_usd == pytest.approx(-25.0)


def test_backtest_exits_on_max_hold_timeout(cfg: PaperTraderConfig) -> None:
    result = BacktestEngine(cfg).run(
        bars=[
            _bar(0, open_=1.0, high=1.10, low=0.90, close=1.00),
            _bar(15, open_=1.0, high=1.20, low=0.90, close=1.10),
        ],
        signals=[_signal()],
    )

    trade = result.trades[0]
    assert trade.exit_reason == "TIMEOUT"
    assert trade.exit_price == pytest.approx(1.10)
    assert trade.pnl_usd == pytest.approx(10.0)


def test_backtest_ignores_non_bullish_and_low_confidence_signals(
    cfg: PaperTraderConfig,
) -> None:
    result = BacktestEngine(cfg).run(
        bars=[_bar(0, open_=1.0, high=2.0, low=0.5, close=1.0)],
        signals=[
            _signal(signal=SignalType.BEARISH, confidence=0.99),
            _signal(signal=SignalType.NEUTRAL, confidence=0.99),
            _signal(confidence=0.59),
        ],
    )

    assert result.trade_count == 0
    assert result.final_balance_usd == pytest.approx(10000.0)


def test_backtest_reports_playbook_style_metrics(cfg: PaperTraderConfig) -> None:
    result = BacktestEngine(cfg).run(
        bars=[
            _bar(0, open_=1.0, high=1.60, low=0.95, close=1.50),
            _bar(20, open_=1.0, high=1.10, low=0.70, close=0.75),
        ],
        signals=[
            _signal(0, price_usd=1.0),
            _signal(20, price_usd=1.0),
        ],
    )

    assert result.trade_count == 2
    assert result.total_return_usd == pytest.approx(25.0)
    assert result.total_return_pct == pytest.approx(0.0025)
    assert result.max_drawdown_pct == pytest.approx(25.0 / 10050.0)
    assert result.win_rate == pytest.approx(0.5)
    assert result.sharpe != 0.0
