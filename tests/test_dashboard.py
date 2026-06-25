"""Tests for dashboard pure helpers (no Streamlit runtime)."""
from datetime import datetime, timezone


def test_format_event_row_contains_stage_and_symbol():
    from dashboard.app import format_event_row

    row = format_event_row({
        "ts": datetime(2024, 1, 1, 12, 30, 5, tzinfo=timezone.utc),
        "trace_id": "t1", "stage": "judge", "mint": "M1",
        "symbol": "DOGX", "status": "ok", "detail": "BULLISH 0.78",
    })
    assert "judge" in row.lower()
    assert "DOGX" in row
    assert "BULLISH 0.78" in row
    assert "12:30:05" in row


def test_format_event_row_handles_empty_symbol():
    from dashboard.app import format_event_row

    row = format_event_row({
        "ts": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "trace_id": "", "stage": "scan", "mint": "",
        "symbol": "", "status": "ok", "detail": "5 candidates",
    })
    assert "scan" in row.lower()
    assert "5 candidates" in row


def test_format_addr_compacts_long_address():
    from dashboard.app import format_addr

    assert format_addr("123456789ABCDEFGHJKLM") == "12345678...GHJKLM"


def test_format_addr_keeps_short_or_empty_address():
    from dashboard.app import format_addr

    assert format_addr("SHORT") == "SHORT"
    assert format_addr("") == ""


def test_dashboard_run_source_stage_and_flags_from_payload():
    from dashboard.app import run_source, run_stage, run_flags

    row = {
        "payload": {
            "source": "gmgn_trending",
            "stage": "trending",
            "hardfilter_flags": ["momentum: buy/sell 0.9 < 1.0"],
        }
    }

    assert run_source(row) == "gmgn_trending"
    assert run_stage(row) == "trending"
    assert run_flags(row) == ["momentum: buy/sell 0.9 < 1.0"]


def test_dashboard_separates_telegram_from_eval_runs():
    from dashboard.app import is_telegram_run, is_telegram_scan

    assert is_telegram_scan({"source": "gmgn_telegram"}) is True
    assert is_telegram_scan({"source": "candidate_arg"}) is False
    assert is_telegram_run({"payload": {"source": "gmgn_telegram"}}) is True
    assert is_telegram_run({"payload": {"source": "gmgn_trending"}}) is False


def test_outcome_summary_computes_success_and_return():
    from dashboard.app import outcome_summary

    summary = outcome_summary([
        {"success": True, "return_pct": 10.0},
        {"success": False, "return_pct": -5.0},
    ])

    assert summary["count"] == 2
    assert summary["success_rate"] == 0.5
    assert summary["avg_return_pct"] == 2.5
