from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from memedogV2.harness.contracts import HarnessRun

_CREATE_V2_SCANNER_ITEMS = """
CREATE TABLE IF NOT EXISTS v2_scanner_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    source      TEXT NOT NULL,
    ca_address  TEXT NOT NULL,
    lp_address  TEXT NOT NULL DEFAULT '',
    trace_id    TEXT NOT NULL DEFAULT '',
    enqueued    INTEGER NOT NULL,
    raw_text    TEXT NOT NULL DEFAULT ''
);
"""

_CREATE_V2_RUNS = """
CREATE TABLE IF NOT EXISTS v2_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    ca_address  TEXT NOT NULL,
    backend     TEXT NOT NULL,
    mode        TEXT NOT NULL,
    trace_id    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,
    signal      TEXT NOT NULL DEFAULT '',
    recommended INTEGER,
    confidence  REAL,
    summary     TEXT NOT NULL DEFAULT '',
    payload     TEXT NOT NULL
);
"""

_CREATE_V2_BACKTEST_OUTCOMES = """
CREATE TABLE IF NOT EXISTS v2_backtest_outcomes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                 TEXT NOT NULL,
    run_row_id         INTEGER NOT NULL,
    run_id             TEXT NOT NULL,
    ca_address         TEXT NOT NULL,
    trace_id           TEXT NOT NULL DEFAULT '',
    horizon_min        INTEGER NOT NULL,
    entry_ts           TEXT NOT NULL,
    observed_ts        TEXT NOT NULL,
    entry_price_usd    REAL NOT NULL,
    observed_price_usd REAL NOT NULL,
    return_pct         REAL NOT NULL,
    signal             TEXT NOT NULL DEFAULT '',
    recommended        INTEGER,
    confidence         REAL,
    verdict            TEXT NOT NULL DEFAULT '',
    success            INTEGER NOT NULL,
    payload            TEXT NOT NULL,
    UNIQUE(run_id, horizon_min)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class V2Store:
    """SQLite persistence for memedogV2 scanner intake and harness runs."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.execute(_CREATE_V2_SCANNER_ITEMS)
        self._conn.execute(_CREATE_V2_RUNS)
        self._conn.execute(_CREATE_V2_BACKTEST_OUTCOMES)
        self._ensure_column("v2_runs", "entry_price_usd", "REAL")
        self._ensure_column("v2_runs", "liquidity_usd", "REAL")
        self._ensure_column("v2_runs", "volume_5m", "REAL")
        self._conn.commit()

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        cols = {
            row["name"]
            for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in cols:
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def save_scanner_item(
        self,
        *,
        source: str,
        ca_address: str,
        lp_address: str = "",
        trace_id: str = "",
        enqueued: bool,
        raw_text: str = "",
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO v2_scanner_items
              (ts, source, ca_address, lp_address, trace_id, enqueued, raw_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (_now(), source, ca_address, lp_address, trace_id, int(enqueued), raw_text),
        )
        self._conn.commit()

    def save_run(self, run: HarnessRun, *, trace_id: str = "") -> None:
        sig = run.final_signal
        status = "signal" if sig is not None else "no_signal"
        facts = run.facts_snapshot or {}
        self._conn.execute(
            """
            INSERT INTO v2_runs
              (ts, run_id, ca_address, backend, mode, trace_id, status, signal,
               recommended, confidence, summary, payload, entry_price_usd,
               liquidity_usd, volume_5m)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                run.run_id,
                run.ca_address,
                run.backend,
                run.mode,
                trace_id or (sig.trace_id if sig is not None else ""),
                status,
                sig.signal.value if sig is not None else "",
                int(sig.recommended) if sig is not None else None,
                sig.confidence if sig is not None else None,
                sig.summary if sig is not None else "",
                run.model_dump_json(),
                _optional_float(facts.get("price_usd")),
                _optional_float(facts.get("liquidity_usd")),
                _optional_float(facts.get("volume_5m")),
            ),
        )
        self._conn.commit()

    def runs_due_for_outcome(self, *, horizon_min: int, limit: int = 50) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc).timestamp() - horizon_min * 60
        cutoff_ts = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
        rows = self._conn.execute(
            """
            SELECT *
            FROM v2_runs r
            WHERE r.status = 'signal'
              AND r.entry_price_usd IS NOT NULL
              AND r.entry_price_usd > 0
              AND r.ts <= ?
              AND NOT EXISTS (
                SELECT 1
                FROM v2_backtest_outcomes o
                WHERE o.run_id = r.run_id AND o.horizon_min = ?
              )
            ORDER BY r.id ASC
            LIMIT ?
            """,
            (cutoff_ts, horizon_min, limit),
        ).fetchall()
        return [self._run_row_to_dict(row) for row in rows]

    def save_backtest_outcome(self, outcome: dict[str, Any]) -> None:
        payload = outcome.get("payload", {})
        self._conn.execute(
            """
            INSERT OR REPLACE INTO v2_backtest_outcomes
              (ts, run_row_id, run_id, ca_address, trace_id, horizon_min,
               entry_ts, observed_ts, entry_price_usd, observed_price_usd,
               return_pct, signal, recommended, confidence, verdict, success, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                outcome["run_row_id"],
                outcome["run_id"],
                outcome["ca_address"],
                outcome.get("trace_id", ""),
                int(outcome["horizon_min"]),
                outcome["entry_ts"],
                outcome["observed_ts"],
                float(outcome["entry_price_usd"]),
                float(outcome["observed_price_usd"]),
                float(outcome["return_pct"]),
                outcome.get("signal", ""),
                (
                    None
                    if outcome.get("recommended") is None
                    else int(bool(outcome["recommended"]))
                ),
                outcome.get("confidence"),
                outcome.get("verdict", ""),
                int(bool(outcome["success"])),
                json.dumps(payload),
            ),
        )
        self._conn.commit()

    def recent_backtest_outcomes(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM v2_backtest_outcomes ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["ts"] = _parse_ts(row["ts"])
            item["entry_ts"] = _parse_ts(row["entry_ts"])
            item["observed_ts"] = _parse_ts(row["observed_ts"])
            item["recommended"] = (
                None if row["recommended"] is None else bool(row["recommended"])
            )
            item["success"] = bool(row["success"])
            try:
                item["payload"] = json.loads(row["payload"])
            except json.JSONDecodeError:
                item["payload"] = {}
            out.append(item)
        return out

    def recent_scanner_items(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM v2_scanner_items ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                **dict(row),
                "ts": _parse_ts(row["ts"]),
                "enqueued": bool(row["enqueued"]),
            }
            for row in rows
        ]

    def recent_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM v2_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._run_row_to_dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _run_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["ts"] = _parse_ts(row["ts"])
        item["recommended"] = (
            None if row["recommended"] is None else bool(row["recommended"])
        )
        try:
            item["payload"] = json.loads(row["payload"])
        except json.JSONDecodeError:
            item["payload"] = {}
        return item


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
