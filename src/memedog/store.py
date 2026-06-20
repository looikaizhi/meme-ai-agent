"""SQLite persistence layer for MemeDog Radar.

Serialization contracts:
  - datetimes: stored as ISO 8601 strings with UTC offset (e.g. "2024-01-01T12:00:00+00:00").
    Deserialized back to timezone-aware datetime objects.
  - Enums (SignalType): stored as their .value string ("BULLISH", "BEARISH", "NEUTRAL").
  - TokenSnapshot: JSON-serialized via pydantic's model_dump_json() into a single TEXT column
    (``payload``), with ``mint``, ``trace_id``, and ``created_at`` as separate indexed columns
    so the dashboard can filter/sort without deserializing.

Design note:
  - Uses a file-path-based SQLite connection (not :memory:) so multiple components
    (PriceWatcher, dashboard) can share the same DB by opening separate Store instances.
    Each Store holds its own connection. Connection lifetime == Store instance lifetime.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from memedog.models import Position, Signal, SignalType, TokenSnapshot, TradeRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_POSITIONS = """
CREATE TABLE IF NOT EXISTS positions (
    mint             TEXT PRIMARY KEY,
    symbol           TEXT NOT NULL,
    entry_price      REAL NOT NULL,
    entry_time       TEXT NOT NULL,
    size_usd         REAL NOT NULL,
    status           TEXT NOT NULL,
    take_profit_pct  REAL NOT NULL,
    stop_loss_pct    REAL NOT NULL,
    max_hold_minutes INTEGER NOT NULL
);
"""

_CREATE_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mint        TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price  REAL NOT NULL,
    pnl_usd     REAL NOT NULL,
    pnl_pct     REAL NOT NULL,
    exit_reason TEXT NOT NULL,
    entry_time  TEXT NOT NULL,
    exit_time   TEXT NOT NULL
);
"""

_CREATE_SIGNALS = """
CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mint        TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    signal      TEXT NOT NULL,
    confidence  REAL NOT NULL,
    score_total REAL NOT NULL,
    bull_points TEXT NOT NULL,
    bear_points TEXT NOT NULL,
    red_flags   TEXT NOT NULL,
    rationale   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    trace_id    TEXT NOT NULL
);
"""

_CREATE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    mint       TEXT NOT NULL,
    trace_id   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload    TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dt_to_str(dt: datetime) -> str:
    """Serialize a datetime to an ISO 8601 string with UTC offset."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _str_to_dt(s: str) -> datetime:
    """Deserialize an ISO 8601 string to a timezone-aware datetime."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class Store:
    """SQLite-backed persistence store for positions, trades, signals, and snapshots."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        cur = self._conn.cursor()
        cur.execute(_CREATE_POSITIONS)
        cur.execute(_CREATE_TRADES)
        cur.execute(_CREATE_SIGNALS)
        cur.execute(_CREATE_SNAPSHOTS)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def save_position(self, pos: Position) -> None:
        """Insert or replace a position."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO positions
              (mint, symbol, entry_price, entry_time, size_usd, status,
               take_profit_pct, stop_loss_pct, max_hold_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pos.mint,
                pos.symbol,
                pos.entry_price,
                _dt_to_str(pos.entry_time),
                pos.size_usd,
                pos.status,
                pos.take_profit_pct,
                pos.stop_loss_pct,
                pos.max_hold_minutes,
            ),
        )
        self._conn.commit()

    def update_position(self, mint: str, status: str) -> None:
        """Update the status of a position by mint address."""
        self._conn.execute(
            "UPDATE positions SET status = ? WHERE mint = ?",
            (status, mint),
        )
        self._conn.commit()

    def open_positions(self) -> list[Position]:
        """Return all positions with status='OPEN'."""
        cur = self._conn.execute(
            "SELECT * FROM positions WHERE status = 'OPEN'"
        )
        rows = cur.fetchall()
        return [self._row_to_position(row) for row in rows]

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> Position:
        return Position(
            mint=row["mint"],
            symbol=row["symbol"],
            entry_price=row["entry_price"],
            entry_time=_str_to_dt(row["entry_time"]),
            size_usd=row["size_usd"],
            status=row["status"],
            take_profit_pct=row["take_profit_pct"],
            stop_loss_pct=row["stop_loss_pct"],
            max_hold_minutes=row["max_hold_minutes"],
        )

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def save_trade(self, rec: TradeRecord) -> None:
        """Insert a trade record."""
        self._conn.execute(
            """
            INSERT INTO trades
              (mint, symbol, entry_price, exit_price, pnl_usd, pnl_pct,
               exit_reason, entry_time, exit_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec.mint,
                rec.symbol,
                rec.entry_price,
                rec.exit_price,
                rec.pnl_usd,
                rec.pnl_pct,
                rec.exit_reason,
                _dt_to_str(rec.entry_time),
                _dt_to_str(rec.exit_time),
            ),
        )
        self._conn.commit()

    def all_trades(self) -> list[TradeRecord]:
        """Return all trade records ordered by insertion."""
        cur = self._conn.execute("SELECT * FROM trades ORDER BY id ASC")
        rows = cur.fetchall()
        return [self._row_to_trade(row) for row in rows]

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> TradeRecord:
        return TradeRecord(
            mint=row["mint"],
            symbol=row["symbol"],
            entry_price=row["entry_price"],
            exit_price=row["exit_price"],
            pnl_usd=row["pnl_usd"],
            pnl_pct=row["pnl_pct"],
            exit_reason=row["exit_reason"],
            entry_time=_str_to_dt(row["entry_time"]),
            exit_time=_str_to_dt(row["exit_time"]),
        )

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def save_signal(self, sig: Signal) -> None:
        """Insert a signal record."""
        self._conn.execute(
            """
            INSERT INTO signals
              (mint, symbol, signal, confidence, score_total, bull_points,
               bear_points, red_flags, rationale, created_at, trace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sig.mint,
                sig.symbol,
                sig.signal.value,  # enum → string
                sig.confidence,
                sig.score_total,
                json.dumps(sig.bull_points),
                json.dumps(sig.bear_points),
                json.dumps(sig.red_flags),
                sig.rationale,
                _dt_to_str(sig.created_at),
                sig.trace_id,
            ),
        )
        self._conn.commit()

    def recent_signals(self, limit: int = 50) -> list[Signal]:
        """Return the most recent N signals, newest first."""
        cur = self._conn.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = cur.fetchall()
        return [self._row_to_signal(row) for row in rows]

    @staticmethod
    def _row_to_signal(row: sqlite3.Row) -> Signal:
        return Signal(
            mint=row["mint"],
            symbol=row["symbol"],
            signal=SignalType(row["signal"]),  # string → enum
            confidence=row["confidence"],
            score_total=row["score_total"],
            bull_points=json.loads(row["bull_points"]),
            bear_points=json.loads(row["bear_points"]),
            red_flags=json.loads(row["red_flags"]),
            rationale=row["rationale"],
            created_at=_str_to_dt(row["created_at"]),
            trace_id=row["trace_id"],
        )

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def save_snapshot(self, snap: TokenSnapshot) -> None:
        """Insert a snapshot, serialized as JSON payload."""
        self._conn.execute(
            """
            INSERT INTO snapshots (mint, trace_id, created_at, payload)
            VALUES (?, ?, ?, ?)
            """,
            (
                snap.candidate.mint,
                snap.candidate.trace_id,
                _dt_to_str(snap.enriched_at),
                snap.model_dump_json(),
            ),
        )
        self._conn.commit()

    def recent_snapshots(self, limit: int = 50) -> list[TokenSnapshot]:
        """Return the most recent N snapshots as TokenSnapshot objects, newest first."""
        cur = self._conn.execute(
            "SELECT payload FROM snapshots ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = cur.fetchall()
        results = []
        for row in rows:
            try:
                results.append(TokenSnapshot.model_validate_json(row["payload"]))
            except Exception as exc:
                logger.warning("skipping corrupt snapshot payload: %s", exc)
        return results

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection. Safe to call multiple times."""
        try:
            self._conn.close()
        except Exception:
            pass
