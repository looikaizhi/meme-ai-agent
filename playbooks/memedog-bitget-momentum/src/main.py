"""Entry point for the MemeDog Bitget Momentum Playbook."""
import math
from typing import Any

from getagent import backtest, data, runtime


def _sanitize(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _sanitize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: _sanitize(value) for key, value in metrics.items()}


def run() -> None:
    cfg = runtime.manifest.get("strategy_config", {}) or {}
    symbols = cfg.get("trading_symbols") or ["DOGEUSDT"]
    symbol = symbols[0]
    exchange = cfg.get("exchange") or "bitget"

    bars = data.crypto.futures.kline(
        symbol=symbol,
        interval="1h",
        exchange=exchange,
        limit=1000,
    )
    replay_frame = backtest.prepare_frame(bars, datetime_index="date")

    if replay_frame.empty:
        runtime.emit_signal(
            action="watch",
            symbol=symbol,
            confidence=0.0,
            metrics={"rows": 0},
            meta={"reason": "no historical bars returned"},
        )
        return

    instrument_key = f"{symbol}.{exchange.upper()}"
    result = backtest.run(
        ohlcv_data={instrument_key: replay_frame},
        spec=runtime.backtest_spec,
    )
    chart_path = backtest.generate_chart(result)
    summary = result.summary or {}

    metrics = _sanitize_metrics(
        {
            "total_return_pct": result.total_return_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown_pct": result.max_drawdown_pct,
            "win_rate": result.win_rate,
            "total_trades": result.total_trades,
            "profit_factor": result.profit_factor,
            "starting_balance": summary.get("starting_balance"),
            "net_pnl": summary.get("net_pnl"),
            "rows": len(replay_frame),
        }
    )

    action = "long" if (result.total_trades or 0) > 0 and (result.total_return_pct or 0) > 0 else "watch"
    runtime.emit_signal(
        action=action,
        symbol=symbol,
        confidence=_sanitize(result.win_rate) or 0.0,
        metrics=metrics,
        meta={
            "chart_path": chart_path,
            "exchange": exchange,
            "fast_period": cfg.get("fast_period"),
            "slow_period": cfg.get("slow_period"),
        },
    )


if __name__ == "__main__":
    run()

