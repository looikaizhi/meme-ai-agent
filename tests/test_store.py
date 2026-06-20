"""Tests for Store (SQLite persistence) — TDD red phase.

Serialization contract:
  - datetimes: ISO 8601 strings, timezone-aware UTC
  - enums: stored as their .value string
  - TokenSnapshot: JSON-serialized via pydantic model_dump_json(), stored in a
    single TEXT column alongside mint, trace_id, created_at for indexing.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from memedog.models import (
    Position,
    Signal,
    SignalType,
    TokenSnapshot,
    TradeRecord,
)
from memedog.models.candidate import TokenCandidate
from memedog.models.snapshot import (
    HolderInfo,
    MomentumInfo,
    SafetyInfo,
    SocialInfo,
)
from memedog.store import Store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_memedog.db")


@pytest.fixture
def store(db_path: str) -> Store:
    s = Store(db_path)
    yield s
    s.close()


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_position(
    mint: str = "MINT_A",
    symbol: str = "DOGE",
    entry_price: float = 1.0,
    status: str = "OPEN",
) -> Position:
    return Position(
        mint=mint,
        symbol=symbol,
        entry_price=entry_price,
        entry_time=_utcnow(),
        size_usd=100.0,
        status=status,
        take_profit_pct=0.5,
        stop_loss_pct=0.25,
        max_hold_minutes=120,
    )


def _make_trade(
    mint: str = "MINT_A",
    symbol: str = "DOGE",
    exit_reason: str = "TP",
    pnl_usd: float = 50.0,
    pnl_pct: float = 0.5,
) -> TradeRecord:
    now = _utcnow()
    return TradeRecord(
        mint=mint,
        symbol=symbol,
        entry_price=1.0,
        exit_price=1.5,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        exit_reason=exit_reason,
        entry_time=now,
        exit_time=now,
    )


def _make_signal(
    mint: str = "MINT_A",
    symbol: str = "DOGE",
    signal_type: SignalType = SignalType.BULLISH,
    confidence: float = 0.85,
) -> Signal:
    return Signal(
        mint=mint,
        symbol=symbol,
        signal=signal_type,
        confidence=confidence,
        score_total=75.0,
        bull_points=["good liquidity"],
        bear_points=[],
        red_flags=[],
        rationale="looking good",
        created_at=_utcnow(),
        trace_id="trace-001",
    )


def _make_snapshot(mint: str = "MINT_A") -> TokenSnapshot:
    candidate = TokenCandidate(
        mint=mint,
        pair_address="PAIR_A",
        symbol="DOGE",
        chain="solana",
        pair_created_at=_utcnow(),
        price_usd=1.0,
        liquidity_usd=50000.0,
        fdv_usd=200000.0,
        volume_5m=5000.0,
        volume_1h=20000.0,
        txns_5m_buys=50,
        txns_5m_sells=20,
        price_change_5m=2.5,
        trace_id="trace-001",
    )
    return TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(available=True, mint_authority_revoked=True),
        holders=HolderInfo(available=True, top10_pct=20.0),
        momentum=MomentumInfo(available=True, liquidity_usd=50000.0),
        social=SocialInfo(available=True, smart_money_buys=3),
        enriched_at=_utcnow(),
    )


# ---------------------------------------------------------------------------
# Test: Store creates DB file and tables on init
# ---------------------------------------------------------------------------


def test_store_creates_db_file(db_path: str) -> None:
    """Store creates a SQLite file at the given path."""
    assert not os.path.exists(db_path)
    s = Store(db_path)
    s.close()
    assert os.path.exists(db_path)


# ---------------------------------------------------------------------------
# Test: Position round-trip
# ---------------------------------------------------------------------------


def test_save_and_retrieve_position(store: Store) -> None:
    """save_position + open_positions returns the saved position."""
    pos = _make_position()
    store.save_position(pos)

    positions = store.open_positions()
    assert len(positions) == 1
    retrieved = positions[0]
    assert retrieved.mint == pos.mint
    assert retrieved.symbol == pos.symbol
    assert retrieved.entry_price == pos.entry_price
    assert retrieved.size_usd == pos.size_usd
    assert retrieved.status == "OPEN"
    assert retrieved.take_profit_pct == pos.take_profit_pct
    assert retrieved.stop_loss_pct == pos.stop_loss_pct
    assert retrieved.max_hold_minutes == pos.max_hold_minutes
    # datetime should be timezone-aware
    assert retrieved.entry_time.tzinfo is not None


def test_open_positions_returns_only_open(store: Store) -> None:
    """open_positions excludes CLOSED positions."""
    open_pos = _make_position(mint="MINT_OPEN", status="OPEN")
    closed_pos = _make_position(mint="MINT_CLOSED", status="CLOSED")
    store.save_position(open_pos)
    store.save_position(closed_pos)

    positions = store.open_positions()
    mints = [p.mint for p in positions]
    assert "MINT_OPEN" in mints
    assert "MINT_CLOSED" not in mints


def test_update_position_to_closed_removes_from_open(store: Store) -> None:
    """update_position(mint, 'CLOSED') removes position from open_positions."""
    pos = _make_position(mint="MINT_X")
    store.save_position(pos)
    assert len(store.open_positions()) == 1

    store.update_position("MINT_X", "CLOSED")
    assert store.open_positions() == []


def test_update_nonexistent_position_is_noop(store: Store) -> None:
    """update_position on an unknown mint does not raise."""
    store.update_position("UNKNOWN_MINT", "CLOSED")  # should not raise


# ---------------------------------------------------------------------------
# Test: TradeRecord round-trip
# ---------------------------------------------------------------------------


def test_save_and_retrieve_trade(store: Store) -> None:
    """save_trade + all_trades round-trips a TradeRecord."""
    rec = _make_trade()
    store.save_trade(rec)

    trades = store.all_trades()
    assert len(trades) == 1
    t = trades[0]
    assert t.mint == rec.mint
    assert t.symbol == rec.symbol
    assert t.entry_price == rec.entry_price
    assert t.exit_price == rec.exit_price
    assert t.pnl_usd == rec.pnl_usd
    assert t.pnl_pct == rec.pnl_pct
    assert t.exit_reason == rec.exit_reason
    assert t.entry_time.tzinfo is not None
    assert t.exit_time.tzinfo is not None


def test_all_trades_returns_multiple(store: Store) -> None:
    """all_trades returns all saved records in insertion order."""
    store.save_trade(_make_trade(mint="MINT_1", pnl_usd=10.0))
    store.save_trade(_make_trade(mint="MINT_2", pnl_usd=20.0))

    trades = store.all_trades()
    assert len(trades) == 2


# ---------------------------------------------------------------------------
# Test: Signal round-trip
# ---------------------------------------------------------------------------


def test_save_and_recent_signals_roundtrip(store: Store) -> None:
    """save_signal + recent_signals round-trips signal type and confidence."""
    sig = _make_signal()
    store.save_signal(sig)

    signals = store.recent_signals()
    assert len(signals) == 1
    s = signals[0]
    assert s.mint == sig.mint
    assert s.symbol == sig.symbol
    assert s.signal == SignalType.BULLISH
    assert s.confidence == pytest.approx(0.85)
    assert s.created_at.tzinfo is not None
    assert s.trace_id == "trace-001"


def test_recent_signals_respects_limit(store: Store) -> None:
    """recent_signals(limit=N) returns at most N signals."""
    for i in range(5):
        store.save_signal(_make_signal(mint=f"MINT_{i}", confidence=0.7 + i * 0.01))

    signals = store.recent_signals(limit=3)
    assert len(signals) == 3


def test_recent_signals_bearish_roundtrip(store: Store) -> None:
    """Enum value BEARISH survives serialization."""
    sig = _make_signal(signal_type=SignalType.BEARISH)
    store.save_signal(sig)
    signals = store.recent_signals()
    assert signals[0].signal == SignalType.BEARISH


# ---------------------------------------------------------------------------
# Test: TokenSnapshot persistence
# ---------------------------------------------------------------------------


def test_save_and_recent_snapshots(store: Store) -> None:
    """save_snapshot + recent_snapshots returns at least the saved snapshot."""
    snap = _make_snapshot()
    store.save_snapshot(snap)

    results = store.recent_snapshots()
    assert len(results) >= 1


def test_recent_snapshots_limit(store: Store) -> None:
    """recent_snapshots(limit=N) returns at most N items."""
    for i in range(5):
        store.save_snapshot(_make_snapshot(mint=f"MINT_{i}"))
    results = store.recent_snapshots(limit=2)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# Test: Store.close() can be called multiple times safely (no exception)
# ---------------------------------------------------------------------------


def test_store_close_is_idempotent(db_path: str) -> None:
    """close() can be called multiple times without raising."""
    s = Store(db_path)
    s.close()
    s.close()  # second close should not raise


# ---------------------------------------------------------------------------
# Test: corrupt snapshot payloads are logged and skipped
# ---------------------------------------------------------------------------


def test_recent_snapshots_logs_and_skips_corrupt_payload(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    """recent_snapshots skips corrupt JSON payloads and logs a warning."""
    import logging

    # Insert a corrupt payload directly into the DB
    store._conn.execute(
        """
        INSERT INTO snapshots (mint, trace_id, created_at, payload)
        VALUES (?, ?, ?, ?)
        """,
        ("MINT_BAD", "trace-bad", "2024-01-01T00:00:00+00:00", "NOT_VALID_JSON"),
    )
    store._conn.commit()

    with caplog.at_level(logging.WARNING, logger="memedog.store"):
        results = store.recent_snapshots()

    # Corrupt row is skipped
    assert results == []
    # Warning is logged with the error detail
    assert any("skipping corrupt snapshot payload" in r.message for r in caplog.records)
