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
