"""Tests for PaperTrader — strict TDD.

PaperTrader.on_signal: enter only BULLISH + confidence >= threshold + no open duplicate.
PaperTrader.evaluate: close on TP / SL / TIMEOUT; return None when still open.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memedog.config.settings import PaperTraderConfig
from memedog.models import Position, Signal, SignalType, TradeRecord
from memedog.papertrader.trader import PaperTrader
from memedog.store import Store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "trader_test.db")


@pytest.fixture
def store(db_path: str) -> Store:
    s = Store(db_path)
    yield s
    s.close()


@pytest.fixture
def cfg() -> PaperTraderConfig:
    return PaperTraderConfig(
        entry_min_confidence=0.60,
        size_usd=100.0,
        take_profit_pct=0.50,
        stop_loss_pct=0.25,
        max_hold_minutes=120,
        price_poll_sec=30,
        starting_balance_usd=10000.0,
    )


@pytest.fixture
def trader(store: Store, cfg: PaperTraderConfig) -> PaperTrader:
    return PaperTrader(store=store, cfg=cfg)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _bullish_signal(
    mint: str = "MINT_A",
    symbol: str = "DOGE",
    confidence: float = 0.85,
    signal_type: SignalType = SignalType.BULLISH,
) -> Signal:
    return Signal(
        mint=mint,
        symbol=symbol,
        signal=signal_type,
        confidence=confidence,
        score_total=75.0,
        bull_points=["good"],
        bear_points=[],
        red_flags=[],
        rationale="looks good",
        created_at=_utcnow(),
        trace_id="t001",
    )


# ---------------------------------------------------------------------------
# on_signal tests
# ---------------------------------------------------------------------------


def test_on_signal_bullish_high_confidence_opens_position(
    trader: PaperTrader, store: Store
) -> None:
    """BULLISH signal with confidence >= threshold creates an OPEN position."""
    sig = _bullish_signal(confidence=0.85)
    pos = trader.on_signal(sig, entry_price=1.0)

    assert pos is not None
    assert pos.mint == "MINT_A"
    assert pos.symbol == "DOGE"
    assert pos.status == "OPEN"
    assert pos.entry_price == 1.0
    assert pos.size_usd == 100.0
    # position is persisted in store
    open_positions = store.open_positions()
    assert len(open_positions) == 1
    assert open_positions[0].mint == "MINT_A"


def test_on_signal_low_confidence_returns_none(
    trader: PaperTrader, store: Store
) -> None:
    """BULLISH signal below threshold returns None and does not persist."""
    sig = _bullish_signal(confidence=0.30)
    pos = trader.on_signal(sig, entry_price=1.0)

    assert pos is None
    assert store.open_positions() == []


def test_on_signal_non_bullish_returns_none(
    trader: PaperTrader, store: Store
) -> None:
    """BEARISH signal returns None regardless of confidence."""
    sig = _bullish_signal(signal_type=SignalType.BEARISH, confidence=0.95)
    pos = trader.on_signal(sig, entry_price=1.0)

    assert pos is None
    assert store.open_positions() == []


def test_on_signal_neutral_returns_none(
    trader: PaperTrader, store: Store
) -> None:
    """NEUTRAL signal returns None regardless of confidence."""
    sig = _bullish_signal(signal_type=SignalType.NEUTRAL, confidence=0.95)
    pos = trader.on_signal(sig, entry_price=1.0)

    assert pos is None
    assert store.open_positions() == []


def test_on_signal_duplicate_mint_returns_none(
    trader: PaperTrader, store: Store
) -> None:
    """Second BULLISH signal for same mint while already OPEN returns None."""
    sig = _bullish_signal(mint="MINT_DUP", confidence=0.80)
    first = trader.on_signal(sig, entry_price=1.0)
    assert first is not None

    # Second signal for same mint
    second = trader.on_signal(sig, entry_price=1.5)
    assert second is None
    # Still only one open position
    assert len(store.open_positions()) == 1


def test_on_signal_at_threshold_confidence_opens_position(
    trader: PaperTrader,
) -> None:
    """Confidence exactly equal to entry_min_confidence still opens."""
    sig = _bullish_signal(confidence=0.60)  # exactly at threshold
    pos = trader.on_signal(sig, entry_price=2.0)
    assert pos is not None


def test_on_signal_position_uses_cfg_defaults(
    trader: PaperTrader, cfg: PaperTraderConfig
) -> None:
    """Opened position inherits TP, SL, max_hold from cfg."""
    sig = _bullish_signal(confidence=0.90)
    pos = trader.on_signal(sig, entry_price=1.0)
    assert pos is not None
    assert pos.take_profit_pct == cfg.take_profit_pct
    assert pos.stop_loss_pct == cfg.stop_loss_pct
    assert pos.max_hold_minutes == cfg.max_hold_minutes


def test_on_signal_entry_time_is_utc_aware(trader: PaperTrader) -> None:
    """entry_time on new position is UTC-aware."""
    sig = _bullish_signal(confidence=0.80)
    pos = trader.on_signal(sig, entry_price=1.0)
    assert pos is not None
    assert pos.entry_time.tzinfo is not None


# ---------------------------------------------------------------------------
# evaluate tests
# ---------------------------------------------------------------------------


def _open_pos(
    mint: str = "MINT_A",
    entry_price: float = 1.0,
    minutes_ago: float = 0,
    size_usd: float = 100.0,
) -> Position:
    entry_time = _utcnow() - timedelta(minutes=minutes_ago)
    return Position(
        mint=mint,
        symbol="DOGE",
        entry_price=entry_price,
        entry_time=entry_time,
        size_usd=size_usd,
        status="OPEN",
        take_profit_pct=0.50,
        stop_loss_pct=0.25,
        max_hold_minutes=120,
    )


def test_evaluate_take_profit_returns_tp_record(
    trader: PaperTrader, store: Store
) -> None:
    """Price +60% (>= 50% TP) triggers TP exit with correct pnl."""
    pos = _open_pos(entry_price=1.0)
    store.save_position(pos)

    current_price = 1.60  # +60%, above 50% TP
    rec = trader.evaluate(pos, current_price)

    assert rec is not None
    assert rec.exit_reason == "TP"
    assert rec.pnl_pct == pytest.approx(0.60)
    assert rec.pnl_usd == pytest.approx(60.0)
    assert rec.exit_price == pytest.approx(1.60)
    assert rec.mint == pos.mint


def test_evaluate_tp_closes_position_in_store(
    trader: PaperTrader, store: Store
) -> None:
    """After TP, store.open_positions() no longer includes the position."""
    pos = _open_pos(mint="MINT_TP")
    store.save_position(pos)
    trader.evaluate(pos, current_price=1.60)
    assert store.open_positions() == []


def test_evaluate_tp_saves_trade_to_store(
    trader: PaperTrader, store: Store
) -> None:
    """After TP, trade is persisted in store.all_trades()."""
    pos = _open_pos()
    store.save_position(pos)
    trader.evaluate(pos, current_price=1.60)
    trades = store.all_trades()
    assert len(trades) == 1
    assert trades[0].exit_reason == "TP"


def test_evaluate_stop_loss_returns_sl_record(
    trader: PaperTrader, store: Store
) -> None:
    """Price -30% (<= -25% SL) triggers SL exit with negative pnl."""
    pos = _open_pos(entry_price=1.0)
    store.save_position(pos)

    current_price = 0.70  # -30%, beyond -25% SL
    rec = trader.evaluate(pos, current_price)

    assert rec is not None
    assert rec.exit_reason == "SL"
    assert rec.pnl_pct == pytest.approx(-0.30)
    assert rec.pnl_usd == pytest.approx(-30.0)


def test_evaluate_stop_loss_closes_position(
    trader: PaperTrader, store: Store
) -> None:
    """After SL, position is removed from open_positions."""
    pos = _open_pos(mint="MINT_SL")
    store.save_position(pos)
    trader.evaluate(pos, current_price=0.70)
    assert store.open_positions() == []


def test_evaluate_timeout_returns_timeout_record(
    trader: PaperTrader, store: Store
) -> None:
    """Position held past max_hold_minutes triggers TIMEOUT exit."""
    pos = _open_pos(entry_price=1.0, minutes_ago=121)  # 121 min > 120 limit
    store.save_position(pos)

    # Small price movement within bounds
    current_price = 1.05  # +5%, no TP/SL
    now = pos.entry_time + timedelta(minutes=121)
    rec = trader.evaluate(pos, current_price, now=now)

    assert rec is not None
    assert rec.exit_reason == "TIMEOUT"


def test_evaluate_within_bounds_returns_none(
    trader: PaperTrader, store: Store
) -> None:
    """No exit when price and time are within all bounds."""
    pos = _open_pos(entry_price=1.0, minutes_ago=30)
    store.save_position(pos)

    # +10% move, well within 50% TP and 25% SL, only 30 min in
    now = pos.entry_time + timedelta(minutes=30)
    rec = trader.evaluate(pos, current_price=1.10, now=now)

    assert rec is None
    # position still open
    assert len(store.open_positions()) == 1


def test_evaluate_exactly_at_tp_triggers_exit(
    trader: PaperTrader, store: Store
) -> None:
    """Price exactly at take_profit_pct triggers TP (>= comparison)."""
    pos = _open_pos(entry_price=1.0)
    store.save_position(pos)
    rec = trader.evaluate(pos, current_price=1.50)  # exactly +50%
    assert rec is not None
    assert rec.exit_reason == "TP"


def test_evaluate_exactly_at_sl_triggers_exit(
    trader: PaperTrader, store: Store
) -> None:
    """Price exactly at -stop_loss_pct triggers SL (<= comparison)."""
    pos = _open_pos(entry_price=1.0)
    store.save_position(pos)
    rec = trader.evaluate(pos, current_price=0.75)  # exactly -25%
    assert rec is not None
    assert rec.exit_reason == "SL"


def test_evaluate_exit_time_is_utc_aware(
    trader: PaperTrader, store: Store
) -> None:
    """TradeRecord.exit_time is timezone-aware UTC."""
    pos = _open_pos(entry_price=1.0)
    store.save_position(pos)
    rec = trader.evaluate(pos, current_price=1.60)
    assert rec is not None
    assert rec.exit_time.tzinfo is not None


def test_evaluate_zero_entry_price_returns_none_without_raising(
    trader: PaperTrader, store: Store
) -> None:
    """evaluate() with entry_price=0 returns None and does not raise ZeroDivisionError."""
    pos = _open_pos(entry_price=0.0)
    store.save_position(pos)

    # Must not raise ZeroDivisionError
    rec = trader.evaluate(pos, current_price=1.0)
    assert rec is None
