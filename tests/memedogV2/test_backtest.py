from datetime import datetime, timedelta, timezone

import pytest

from memedogV2.backtest import classify_outcome, evaluate_due_outcomes
from memedogV2.harness.contracts import HarnessRun
from memedogV2.models.contracts import Signal, SignalKind
from memedogV2.store import V2Store


def test_classify_outcome_scores_recommendation_usefulness():
    assert classify_outcome(
        signal="BULLISH",
        recommended=True,
        return_pct=25.0,
    ) == ("bullish_hit", True)
    assert classify_outcome(
        signal="NEUTRAL",
        recommended=False,
        return_pct=30.0,
    ) == ("skip_missed_runner", False)


@pytest.mark.asyncio
async def test_evaluate_due_outcomes_scores_matured_v2_run(tmp_path):
    store = V2Store(str(tmp_path / "v2.db"))
    run = HarnessRun(run_id="r1", ca_address="CA1", backend="fake", mode="production")
    run.facts_snapshot = {"price_usd": 0.05, "liquidity_usd": 50000, "volume_5m": 5000}
    run.final_signal = Signal(
        ca_address="CA1",
        signal=SignalKind.BULLISH,
        recommended=True,
        confidence=0.8,
        rationale="ok",
        summary="looks good",
        trace_id="tr1",
    )
    store.save_run(run, trace_id="tr1")
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=65)).isoformat()
    store._conn.execute("UPDATE v2_runs SET ts = ? WHERE run_id = ?", (old_ts, "r1"))
    store._conn.commit()

    async def price_fn(ca: str) -> float:
        assert ca == "CA1"
        return 0.075

    outcomes = await evaluate_due_outcomes(store, price_fn=price_fn, horizon_min=60)

    assert len(outcomes) == 1
    assert outcomes[0]["verdict"] == "bullish_hit"
    assert outcomes[0]["success"] is True
    assert store.recent_backtest_outcomes()[0]["return_pct"] == pytest.approx(50.0)
    assert await evaluate_due_outcomes(store, price_fn=price_fn, horizon_min=60) == []
