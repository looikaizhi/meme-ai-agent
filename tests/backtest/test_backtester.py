"""Tests for MemeDog signal backtesting."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from memedog.backtest import Backtester, PricePoint, build_playbook_prompt
from memedog.config.settings import PaperTraderConfig
from memedog.models import Signal, SignalType


def cfg() -> PaperTraderConfig:
    return PaperTraderConfig(
        entry_min_confidence=0.60,
        size_usd=100.0,
        take_profit_pct=0.50,
        stop_loss_pct=0.25,
        max_hold_minutes=120,
        price_poll_sec=30,
        starting_balance_usd=10_000.0,
    )


def ts(minutes: int) -> datetime:
    return datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc) + timedelta(
        minutes=minutes
    )


def signal(
    mint: str,
    *,
    signal_type: SignalType = SignalType.BULLISH,
    confidence: float = 0.80,
) -> Signal:
    return Signal(
        mint=mint,
        symbol=mint[-4:],
        signal=signal_type,
        confidence=confidence,
        score_total=75.0,
        bull_points=["momentum"],
        bear_points=["volatile"],
        red_flags=[],
        rationale="test",
        created_at=ts(0),
        trace_id=f"trace-{mint}",
    )


def point(minutes: int, price: float) -> PricePoint:
    return PricePoint(ts=ts(minutes), price=price)


def test_backtester_take_profit_trade_counts_as_win():
    report = Backtester(cfg()).run(
        [signal("MINT_TP")],
        {"MINT_TP": [point(0, 1.0), point(30, 1.2), point(60, 1.6)]},
    )

    assert report.signals_seen == 1
    assert report.trades_opened == 1
    assert report.win_rate == pytest.approx(1.0)
    assert report.total_pnl_usd == pytest.approx(60.0)
    assert report.best_trade_pct == pytest.approx(0.60)
    assert report.trades[0].exit_reason == "TP"


def test_backtester_stop_loss_trade_counts_as_loss():
    report = Backtester(cfg()).run(
        [signal("MINT_SL")],
        {"MINT_SL": [point(0, 1.0), point(10, 0.7)]},
    )

    assert report.trades_opened == 1
    assert report.total_pnl_usd == pytest.approx(-30.0)
    assert report.worst_trade_pct == pytest.approx(-0.30)
    assert report.trades[0].exit_reason == "SL"


def test_backtester_timeout_exits_at_last_price_inside_hold_window():
    report = Backtester(cfg()).run(
        [signal("MINT_TIMEOUT")],
        {"MINT_TIMEOUT": [point(0, 1.0), point(60, 1.1), point(120, 1.2), point(150, 1.4)]},
    )

    assert report.trades_opened == 1
    assert report.trades[0].exit_reason == "TIMEOUT"
    assert report.trades[0].exit_price == pytest.approx(1.2)
    assert report.total_pnl_usd == pytest.approx(20.0)


def test_backtester_skips_non_bullish_and_low_confidence_signals():
    report = Backtester(cfg()).run(
        [
            signal("MINT_BEAR", signal_type=SignalType.BEARISH, confidence=0.99),
            signal("MINT_LOW", confidence=0.20),
        ],
        {
            "MINT_BEAR": [point(0, 1.0), point(5, 2.0)],
            "MINT_LOW": [point(0, 1.0), point(5, 2.0)],
        },
    )

    assert report.signals_seen == 2
    assert report.trades_opened == 0
    assert report.total_pnl_usd == pytest.approx(0.0)


def test_backtester_profit_factor_and_drawdown():
    report = Backtester(cfg()).run(
        [signal("MINT_A"), signal("MINT_B"), signal("MINT_C")],
        {
            "MINT_A": [point(0, 1.0), point(1, 1.5)],
            "MINT_B": [point(0, 1.0), point(1, 0.75)],
            "MINT_C": [point(0, 1.0), point(1, 1.5)],
        },
    )

    assert report.total_pnl_usd == pytest.approx(75.0)
    assert report.profit_factor == pytest.approx(4.0)
    assert report.max_drawdown_usd == pytest.approx(-25.0)


def test_backtester_skips_missing_price_history():
    report = Backtester(cfg()).run([signal("MISSING")], {})

    assert report.trades_opened == 0
    assert report.skipped_no_price == 1


def test_build_playbook_prompt_contains_core_memedog_rules():
    prompt = build_playbook_prompt("MemeDog Momentum", cfg())

    assert "MemeDog Momentum" in prompt
    assert "signal == BULLISH" in prompt
    assert "confidence >= 0.60" in prompt
    assert "Take profit at +50.0%" in prompt
    assert "playbook key: [your Playbook API Key]" in prompt
