"""Pure helper functions for the MemeDog dashboard.

These are side-effect free and depend only on domain models,
making them straightforward to unit-test without Streamlit.
"""
from __future__ import annotations

from memedog.models import TradeRecord


def compute_summary(
    trades: list[TradeRecord],
    starting_balance: float,
) -> dict:
    """Compute a performance summary from a list of closed trades.

    Parameters
    ----------
    trades:
        List of ``TradeRecord`` objects (closed positions).
    starting_balance:
        The initial virtual balance in USD.

    Returns
    -------
    dict with keys:
        ``total_pnl``       — sum of all pnl_usd values.
        ``win_rate``        — fraction of trades with pnl_usd >= 0 (0.0 if empty).
        ``avg_hold_minutes``— mean hold duration in minutes (0.0 if empty).
        ``balance``         — starting_balance + total_pnl.
        ``num_trades``      — number of trades.
    """
    num_trades = len(trades)

    if num_trades == 0:
        return {
            "total_pnl": 0.0,
            "win_rate": 0.0,
            "avg_hold_minutes": 0.0,
            "balance": starting_balance,
            "num_trades": 0,
        }

    total_pnl = sum(t.pnl_usd for t in trades)
    winners = sum(1 for t in trades if t.pnl_usd >= 0)
    win_rate = winners / num_trades

    hold_minutes = [
        (t.exit_time - t.entry_time).total_seconds() / 60.0 for t in trades
    ]
    avg_hold_minutes = sum(hold_minutes) / len(hold_minutes)

    return {
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "avg_hold_minutes": avg_hold_minutes,
        "balance": starting_balance + total_pnl,
        "num_trades": num_trades,
    }
