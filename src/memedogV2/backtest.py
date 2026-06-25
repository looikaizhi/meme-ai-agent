from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

PriceFn = Callable[[str], float | None | Awaitable[float | None]]


def classify_outcome(
    *,
    signal: str,
    recommended: bool | None,
    return_pct: float,
    win_return_pct: float = 20.0,
) -> tuple[str, bool]:
    """Classify whether a matured V2 signal was useful.

    The first scoreboard is intentionally simple: a bullish recommendation has
    to clear the win threshold, while bearish/neutral/not-recommended calls are
    successful when they did not miss a runner.
    """
    signal = signal.upper()
    if recommended and signal == "BULLISH":
        if return_pct >= win_return_pct:
            return "bullish_hit", True
        if return_pct < 0:
            return "bullish_loss", False
        return "bullish_flat", False

    if signal == "BEARISH":
        if return_pct <= 0:
            return "bearish_avoided", True
        if return_pct >= win_return_pct:
            return "bearish_missed_runner", False
        return "bearish_small_up", False

    if return_pct >= win_return_pct:
        return "skip_missed_runner", False
    return "skip_ok", True


async def evaluate_due_outcomes(
    store,
    *,
    price_fn: PriceFn,
    horizon_min: int = 60,
    limit: int = 25,
    win_return_pct: float = 20.0,
) -> list[dict[str, Any]]:
    """Evaluate due V2 runs against the current token price.

    This is a forward-looking backtest harness: it scores decisions once they
    are at least ``horizon_min`` old, using the price captured at decision time
    as entry and the current price as the horizon observation.
    """
    outcomes: list[dict[str, Any]] = []
    for run in store.runs_due_for_outcome(horizon_min=horizon_min, limit=limit):
        observed_price = price_fn(run["ca_address"])
        if inspect.isawaitable(observed_price):
            observed_price = await observed_price
        if observed_price is None:
            continue

        entry_price = float(run["entry_price_usd"])
        if entry_price <= 0:
            continue

        observed = float(observed_price)
        return_pct = ((observed - entry_price) / entry_price) * 100.0
        verdict, success = classify_outcome(
            signal=run.get("signal", ""),
            recommended=run.get("recommended"),
            return_pct=return_pct,
            win_return_pct=win_return_pct,
        )
        observed_ts = datetime.now(timezone.utc).isoformat()
        outcome = {
            "run_row_id": run["id"],
            "run_id": run["run_id"],
            "ca_address": run["ca_address"],
            "trace_id": run.get("trace_id", ""),
            "horizon_min": horizon_min,
            "entry_ts": run["ts"].isoformat(),
            "observed_ts": observed_ts,
            "entry_price_usd": entry_price,
            "observed_price_usd": observed,
            "return_pct": return_pct,
            "signal": run.get("signal", ""),
            "recommended": run.get("recommended"),
            "confidence": run.get("confidence"),
            "verdict": verdict,
            "success": success,
            "payload": {
                "win_return_pct": win_return_pct,
                "liquidity_usd": run.get("liquidity_usd"),
                "volume_5m": run.get("volume_5m"),
            },
        }
        store.save_backtest_outcome(outcome)
        outcomes.append(outcome)
    return outcomes


def summarize_outcomes(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    if not outcomes:
        return {"count": 0, "success_rate": None, "avg_return_pct": None}
    wins = sum(1 for row in outcomes if row["success"])
    return {
        "count": len(outcomes),
        "success_rate": wins / len(outcomes),
        "avg_return_pct": sum(row["return_pct"] for row in outcomes) / len(outcomes),
    }
