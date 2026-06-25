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


def test_update_nonexistent_position_logs_warning(
    store: Store, caplog: pytest.LogCaptureFixture
) -> None:
    """update_position on an unknown mint does not raise but logs a warning."""
    import logging

    with caplog.at_level(logging.WARNING, logger="memedog.store"):
        store.update_position("UNKNOWN_MINT", "CLOSED")  # should not raise

    assert any("UNKNOWN_MINT" in r.message for r in caplog.records), (
        "Expected a warning mentioning the missing mint"
    )


def test_update_existing_position_works(store: Store) -> None:
    """update_position on a known mint updates the status without warning."""
    pos = _make_position(mint="MINT_UPD", status="OPEN")
    store.save_position(pos)

    store.update_position("MINT_UPD", "CLOSED")

    # Should no longer appear in open positions
    assert store.open_positions() == []


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


# ---------------------------------------------------------------------------
# Test: funnel_events round-trip
# ---------------------------------------------------------------------------


def test_save_funnel_event_and_retrieve(store: Store) -> None:
    """save_funnel_event + recent_funnel_events returns the saved event."""
    dropped = [("MINT_BAD1", "low_liquidity"), ("MINT_BAD2", "rugcheck_unavailable")]
    flagged = [("MINT_FLAGGED", "rugcheck_unavailable_pass_flagged")]
    ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    store.save_funnel_event(
        scanned=10,
        passed_hardfilter=3,
        signals=2,
        dropped=dropped,
        flagged=flagged,
        ts=ts,
    )

    events = store.recent_funnel_events(limit=10)
    assert len(events) == 1
    ev = events[0]

    # Counts correct
    assert ev["scanned"] == 10
    assert ev["passed_hardfilter"] == 3
    assert ev["signals"] == 2

    # Lists round-trip
    assert ev["dropped"] == dropped
    assert ev["flagged"] == flagged

    # Timestamp is timezone-aware and matches
    assert ev["ts"].tzinfo is not None
    assert ev["ts"].year == 2025
    assert ev["ts"].month == 1
    assert ev["ts"].day == 15


def test_save_funnel_event_default_ts(store: Store) -> None:
    """save_funnel_event without explicit ts uses current UTC time."""
    before = datetime.now(tz=timezone.utc)
    store.save_funnel_event(scanned=5, passed_hardfilter=2, signals=1, dropped=[], flagged=[])
    after = datetime.now(tz=timezone.utc)

    events = store.recent_funnel_events()
    assert len(events) == 1
    ts = events[0]["ts"]
    assert ts.tzinfo is not None
    assert before <= ts <= after


def test_recent_funnel_events_newest_first(store: Store) -> None:
    """recent_funnel_events returns events newest first (descending by id)."""
    ts1 = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2025, 1, 2, 0, 0, 0, tzinfo=timezone.utc)

    store.save_funnel_event(scanned=1, passed_hardfilter=0, signals=0, dropped=[], flagged=[], ts=ts1)
    store.save_funnel_event(scanned=5, passed_hardfilter=3, signals=2, dropped=[], flagged=[], ts=ts2)

    events = store.recent_funnel_events(limit=10)
    assert len(events) == 2
    # Newest (ts2) is first
    assert events[0]["scanned"] == 5
    assert events[1]["scanned"] == 1


def test_recent_funnel_events_limit(store: Store) -> None:
    """recent_funnel_events(limit=N) returns at most N events."""
    for i in range(5):
        store.save_funnel_event(
            scanned=i, passed_hardfilter=0, signals=0, dropped=[], flagged=[]
        )

    events = store.recent_funnel_events(limit=3)
    assert len(events) == 3


def test_funnel_event_empty_lists(store: Store) -> None:
    """dropped and flagged empty lists round-trip correctly."""
    store.save_funnel_event(scanned=0, passed_hardfilter=0, signals=0, dropped=[], flagged=[])
    events = store.recent_funnel_events()
    assert events[0]["dropped"] == []
    assert events[0]["flagged"] == []


class TestPipelineEvents:
    def test_save_and_recent_events_roundtrip(self, tmp_path):
        from memedog.store import Store

        s = Store(str(tmp_path / "ev.db"))
        try:
            s.save_event("scan", status="ok", detail="5 candidates")
            s.save_event("judge", trace_id="t1", mint="MINT", symbol="DOGX",
                         status="ok", detail="BULLISH 0.78")
            events = s.recent_events(limit=10)
        finally:
            s.close()

        assert len(events) == 2
        # newest first
        assert events[0]["stage"] == "judge"
        assert events[0]["symbol"] == "DOGX"
        assert events[0]["status"] == "ok"
        assert events[0]["detail"] == "BULLISH 0.78"
        from datetime import datetime
        assert isinstance(events[0]["ts"], datetime)
        assert events[1]["stage"] == "scan"

    def test_recent_events_limit(self, tmp_path):
        from memedog.store import Store

        s = Store(str(tmp_path / "ev2.db"))
        try:
            for i in range(10):
                s.save_event("scan", detail=str(i))
            events = s.recent_events(limit=3)
        finally:
            s.close()
        assert len(events) == 3
        assert events[0]["detail"] == "9"  # newest


class TestDiscoveryAlerts:
    def test_save_and_recent_discovery_alerts_roundtrip(self, tmp_path):
        from datetime import datetime
        from memedog.store import Store

        s = Store(str(tmp_path / "alerts.db"))
        try:
            s.save_discovery_alert(
                source="gmgn_telegram",
                mint="MINT_A",
                author="AUTHOR_A",
                liquidity_pool="LP_A",
                raw_text="CA: MINT_A\nAuthor: AUTHOR_A",
            )
            s.save_discovery_alert(
                source="gmgn_telegram",
                mint="MINT_B",
                author="AUTHOR_B",
                liquidity_pool="LP_B",
                raw_text="CA: MINT_B\nAuthor: AUTHOR_B",
            )
            alerts = s.recent_discovery_alerts(limit=10)
        finally:
            s.close()

        assert len(alerts) == 2
        assert alerts[0]["mint"] == "MINT_B"
        assert alerts[0]["author"] == "AUTHOR_B"
        assert alerts[0]["creator_address"] == "AUTHOR_B"
        assert alerts[0]["liquidity_pool_address"] == "LP_B"
        assert alerts[0]["source"] == "gmgn_telegram"
        assert alerts[0]["raw_text"] == "CA: MINT_B\nAuthor: AUTHOR_B"
        assert isinstance(alerts[0]["ts"], datetime)

    def test_recent_discovery_alerts_limit(self, tmp_path):
        from memedog.store import Store

        s = Store(str(tmp_path / "alerts_limit.db"))
        try:
            for i in range(5):
                s.save_discovery_alert(source="gmgn_telegram", mint=f"MINT_{i}")
            alerts = s.recent_discovery_alerts(limit=2)
        finally:
            s.close()

        assert [alert["mint"] for alert in alerts] == ["MINT_4", "MINT_3"]


class TestScannerCandidates:
    def test_save_and_recent_scanner_candidates_roundtrip(self, tmp_path):
        from datetime import datetime
        from memedog.store import Store

        candidate = _make_snapshot(mint="MINT_PASS").candidate
        s = Store(str(tmp_path / "scanner_candidates.db"))
        try:
            s.save_scanner_candidate(
                candidate=candidate,
                source="gmgn_telegram",
                raw_text="raw alert",
            )
            rows = s.recent_scanner_candidates(limit=10)
        finally:
            s.close()

        assert len(rows) == 1
        assert rows[0]["mint"] == "MINT_PASS"
        assert rows[0]["source"] == "gmgn_telegram"
        assert rows[0]["pair_address"] == candidate.pair_address
        assert rows[0]["liquidity_pool_address"] == candidate.pair_address
        assert rows[0]["liquidity_usd"] == candidate.liquidity_usd
        assert rows[0]["raw_text"] == "raw alert"
        assert isinstance(rows[0]["ts"], datetime)

    def test_recent_scanner_candidates_limit(self, tmp_path):
        from memedog.store import Store

        s = Store(str(tmp_path / "scanner_candidates_limit.db"))
        try:
            for i in range(5):
                candidate = _make_snapshot(mint=f"MINT_{i}").candidate
                s.save_scanner_candidate(candidate=candidate, source="gmgn")
            rows = s.recent_scanner_candidates(limit=2)
        finally:
            s.close()

        assert [row["mint"] for row in rows] == ["MINT_4", "MINT_3"]
