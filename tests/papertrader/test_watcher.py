"""Tests for PriceWatcher — strict TDD.

Tests focus on tick() behavior with injected price_fn.
Does NOT test run() sleeping behavior — run() is thin and delegates to tick().
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memedog.config.settings import PaperTraderConfig
from memedog.models import Position
from memedog.papertrader.trader import PaperTrader
from memedog.papertrader.watcher import PriceWatcher
from memedog.store import Store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "watcher_test.db")


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


def _open_pos(mint: str, entry_price: float = 1.0, minutes_ago: float = 0) -> Position:
    return Position(
        mint=mint,
        symbol="DOGE",
        entry_price=entry_price,
        entry_time=_utcnow() - timedelta(minutes=minutes_ago),
        size_usd=100.0,
        status="OPEN",
        take_profit_pct=0.50,
        stop_loss_pct=0.25,
        max_hold_minutes=120,
    )


# ---------------------------------------------------------------------------
# Tests: tick() with TP breach
# ---------------------------------------------------------------------------


async def test_tick_tp_breach_returns_trade_record(
    store: Store, trader: PaperTrader, cfg: PaperTraderConfig
) -> None:
    """tick() closes a position when price breaches TP and returns a TradeRecord."""
    pos = _open_pos(mint="MINT_TP", entry_price=1.0)
    store.save_position(pos)

    # price_fn returns 1.60 for MINT_TP (+60% > 50% TP)
    async def price_fn(mint: str) -> float | None:
        return 1.60

    watcher = PriceWatcher(store=store, trader=trader, price_fn=price_fn, cfg=cfg)
    records = await watcher.tick()

    assert len(records) == 1
    assert records[0].exit_reason == "TP"
    assert records[0].mint == "MINT_TP"


async def test_tick_tp_breach_position_no_longer_open(
    store: Store, trader: PaperTrader, cfg: PaperTraderConfig
) -> None:
    """After tick() closes a TP, the position is removed from open_positions."""
    pos = _open_pos(mint="MINT_TP2", entry_price=1.0)
    store.save_position(pos)

    async def price_fn(mint: str) -> float | None:
        return 2.0  # +100%, well above TP

    watcher = PriceWatcher(store=store, trader=trader, price_fn=price_fn, cfg=cfg)
    await watcher.tick()

    assert store.open_positions() == []


# ---------------------------------------------------------------------------
# Tests: tick() with None price — position stays open, no crash
# ---------------------------------------------------------------------------


async def test_tick_none_price_skips_position(
    store: Store, trader: PaperTrader, cfg: PaperTraderConfig
) -> None:
    """When price_fn returns None, position stays open and tick() returns []."""
    pos = _open_pos(mint="MINT_NO_PRICE")
    store.save_position(pos)

    async def price_fn(mint: str) -> float | None:
        return None  # price unavailable

    watcher = PriceWatcher(store=store, trader=trader, price_fn=price_fn, cfg=cfg)
    records = await watcher.tick()

    assert records == []
    # position still open
    assert len(store.open_positions()) == 1


# ---------------------------------------------------------------------------
# Tests: tick() when price_fn raises — skipped, others still processed
# ---------------------------------------------------------------------------


async def test_tick_price_fn_raises_skips_but_others_processed(
    store: Store, trader: PaperTrader, cfg: PaperTraderConfig
) -> None:
    """If price_fn raises for one mint, that position is skipped but others still evaluated."""
    pos_fail = _open_pos(mint="MINT_FAIL", entry_price=1.0)
    pos_tp = _open_pos(mint="MINT_TP_OK", entry_price=1.0)
    store.save_position(pos_fail)
    store.save_position(pos_tp)

    async def price_fn(mint: str) -> float | None:
        if mint == "MINT_FAIL":
            raise RuntimeError("Network error")
        return 1.60  # TP breach for MINT_TP_OK

    watcher = PriceWatcher(store=store, trader=trader, price_fn=price_fn, cfg=cfg)
    records = await watcher.tick()

    # MINT_TP_OK should have been closed
    assert len(records) == 1
    assert records[0].mint == "MINT_TP_OK"
    # MINT_FAIL should still be open
    open_mints = [p.mint for p in store.open_positions()]
    assert "MINT_FAIL" in open_mints


async def test_tick_price_fn_raises_does_not_crash(
    store: Store, trader: PaperTrader, cfg: PaperTraderConfig
) -> None:
    """tick() doesn't propagate exception from a failing price_fn call."""
    pos = _open_pos(mint="MINT_CRASH")
    store.save_position(pos)

    async def price_fn(mint: str) -> float | None:
        raise ConnectionError("timeout")

    watcher = PriceWatcher(store=store, trader=trader, price_fn=price_fn, cfg=cfg)
    # Should not raise
    records = await watcher.tick()
    assert records == []


# ---------------------------------------------------------------------------
# Tests: tick() with multiple positions, partial fills
# ---------------------------------------------------------------------------


async def test_tick_multiple_positions_independent_evaluation(
    store: Store, trader: PaperTrader, cfg: PaperTraderConfig
) -> None:
    """tick() evaluates all open positions independently."""
    pos_tp = _open_pos(mint="MINT_A", entry_price=1.0)
    pos_hold = _open_pos(mint="MINT_B", entry_price=1.0)
    store.save_position(pos_tp)
    store.save_position(pos_hold)

    prices = {"MINT_A": 1.60, "MINT_B": 1.05}  # A hits TP, B stays open

    async def price_fn(mint: str) -> float | None:
        return prices.get(mint)

    watcher = PriceWatcher(store=store, trader=trader, price_fn=price_fn, cfg=cfg)
    records = await watcher.tick()

    # Only MINT_A closed
    assert len(records) == 1
    assert records[0].mint == "MINT_A"
    # MINT_B still open
    open_mints = [p.mint for p in store.open_positions()]
    assert "MINT_B" in open_mints
    assert "MINT_A" not in open_mints


async def test_tick_empty_open_positions_returns_empty(
    store: Store, trader: PaperTrader, cfg: PaperTraderConfig
) -> None:
    """tick() with no open positions returns empty list without error."""
    async def price_fn(mint: str) -> float | None:
        return 1.0

    watcher = PriceWatcher(store=store, trader=trader, price_fn=price_fn, cfg=cfg)
    records = await watcher.tick()
    assert records == []
