from memedogV2.harness.contracts import HarnessRun
from memedogV2.models.contracts import Signal, SignalKind
from memedogV2.store import V2Store


def test_v2_store_records_scanner_item(tmp_path):
    store = V2Store(str(tmp_path / "v2.db"))

    store.save_scanner_item(
        source="gmgn_telegram",
        ca_address="CA1",
        lp_address="LP1",
        trace_id="tr1",
        enqueued=True,
        raw_text="New pool",
    )

    rows = store.recent_scanner_items()
    assert rows[0]["ca_address"] == "CA1"
    assert rows[0]["lp_address"] == "LP1"
    assert rows[0]["enqueued"] is True


def test_v2_store_records_run_with_signal(tmp_path):
    store = V2Store(str(tmp_path / "v2.db"))
    run = HarnessRun(run_id="r1", ca_address="CA1", backend="fake", mode="production")
    run.facts_snapshot = {
        "price_usd": 0.05,
        "liquidity_usd": 50000,
        "volume_5m": 5000,
    }
    run.final_signal = Signal(
        ca_address="CA1",
        signal=SignalKind.BULLISH,
        recommended=True,
        confidence=0.77,
        rationale="ok",
        summary="looks good",
        trace_id="tr1",
    )

    store.save_run(run, trace_id="tr1")

    rows = store.recent_runs()
    assert rows[0]["run_id"] == "r1"
    assert rows[0]["signal"] == "BULLISH"
    assert rows[0]["recommended"] is True
    assert rows[0]["confidence"] == 0.77
    assert rows[0]["entry_price_usd"] == 0.05
    assert rows[0]["liquidity_usd"] == 50000
    assert rows[0]["payload"]["final_signal"]["summary"] == "looks good"


def test_v2_store_records_backtest_outcome(tmp_path):
    store = V2Store(str(tmp_path / "v2.db"))

    store.save_backtest_outcome({
        "run_row_id": 1,
        "run_id": "r1",
        "ca_address": "CA1",
        "trace_id": "tr1",
        "horizon_min": 60,
        "entry_ts": "2026-06-25T11:00:00+00:00",
        "observed_ts": "2026-06-25T12:00:00+00:00",
        "entry_price_usd": 0.05,
        "observed_price_usd": 0.075,
        "return_pct": 50.0,
        "signal": "BULLISH",
        "recommended": True,
        "confidence": 0.77,
        "verdict": "bullish_hit",
        "success": True,
        "payload": {"win_return_pct": 20.0},
    })

    rows = store.recent_backtest_outcomes()
    assert rows[0]["run_id"] == "r1"
    assert rows[0]["return_pct"] == 50.0
    assert rows[0]["success"] is True
