"""Tests for dashboard_helpers.compute_summary.

Pure function — no mocks needed.
Tests are written before implementation (TDD - red first).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from memedog.models import TradeRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade(
    pnl_usd: float,
    hold_minutes: float = 30.0,
    symbol: str = "ABC",
) -> TradeRecord:
    entry = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    exit_ = entry + timedelta(minutes=hold_minutes)
    sign = 1 if pnl_usd >= 0 else -1
    entry_price = 1.0
    exit_price = entry_price + pnl_usd / 100.0  # size_usd=100 implied
    return TradeRecord(
        mint=f"mint-{symbol}",
        symbol=symbol,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_usd,  # not used in compute_summary
        exit_reason="take_profit" if pnl_usd >= 0 else "stop_loss",
        entry_time=entry,
        exit_time=exit_,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestComputeSummary:

    def test_empty_trades_all_zeros(self):
        from memedog.dashboard_helpers import compute_summary

        result = compute_summary([], starting_balance=10_000.0)
        assert result["total_pnl"] == 0.0
        assert result["win_rate"] == 0.0
        assert result["avg_hold_minutes"] == 0.0
        assert result["balance"] == 10_000.0
        assert result["num_trades"] == 0

    def test_balance_equals_starting_plus_pnl(self):
        from memedog.dashboard_helpers import compute_summary

        trades = [_make_trade(50.0), _make_trade(-20.0)]
        result = compute_summary(trades, starting_balance=10_000.0)
        assert result["balance"] == pytest.approx(10_030.0)

    def test_total_pnl_sums_all(self):
        from memedog.dashboard_helpers import compute_summary

        trades = [_make_trade(50.0), _make_trade(-20.0), _make_trade(30.0)]
        result = compute_summary(trades, starting_balance=1000.0)
        assert result["total_pnl"] == pytest.approx(60.0)

    def test_win_rate_two_winners_one_loser(self):
        from memedog.dashboard_helpers import compute_summary

        trades = [_make_trade(50.0), _make_trade(30.0), _make_trade(-10.0)]
        result = compute_summary(trades, starting_balance=1000.0)
        assert result["win_rate"] == pytest.approx(2 / 3)
        assert result["num_trades"] == 3

    def test_avg_hold_minutes_computed_correctly(self):
        from memedog.dashboard_helpers import compute_summary

        # hold_minutes: 30, 60, 90 → avg = 60
        trades = [
            _make_trade(10.0, hold_minutes=30.0),
            _make_trade(-5.0, hold_minutes=60.0),
            _make_trade(20.0, hold_minutes=90.0),
        ]
        result = compute_summary(trades, starting_balance=1000.0)
        assert result["avg_hold_minutes"] == pytest.approx(60.0)

    def test_win_rate_all_winners(self):
        from memedog.dashboard_helpers import compute_summary

        trades = [_make_trade(10.0), _make_trade(20.0)]
        result = compute_summary(trades, starting_balance=500.0)
        assert result["win_rate"] == pytest.approx(1.0)

    def test_win_rate_all_losers(self):
        from memedog.dashboard_helpers import compute_summary

        trades = [_make_trade(-10.0), _make_trade(-20.0)]
        result = compute_summary(trades, starting_balance=500.0)
        assert result["win_rate"] == pytest.approx(0.0)

    def test_single_trade_winner(self):
        from memedog.dashboard_helpers import compute_summary

        trades = [_make_trade(100.0, hold_minutes=45.0)]
        result = compute_summary(trades, starting_balance=1000.0)
        assert result["total_pnl"] == pytest.approx(100.0)
        assert result["win_rate"] == pytest.approx(1.0)
        assert result["avg_hold_minutes"] == pytest.approx(45.0)
        assert result["balance"] == pytest.approx(1100.0)
        assert result["num_trades"] == 1

    def test_zero_pnl_trade_counts_as_winner(self):
        """A trade with pnl_usd==0 should be treated as a non-loser (win)."""
        from memedog.dashboard_helpers import compute_summary

        trades = [_make_trade(0.0), _make_trade(-5.0)]
        result = compute_summary(trades, starting_balance=1000.0)
        # 1 out of 2 is a winner (pnl >= 0)
        assert result["win_rate"] == pytest.approx(0.5)
