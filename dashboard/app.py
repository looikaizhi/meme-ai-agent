"""MemeDog Radar — Streamlit Dashboard.

Entry point::

    streamlit run dashboard/app.py

All rendering is inside ``main()`` so importing this module does not trigger
Streamlit calls (safe for ``import ast; ast.parse(...)`` and ``import`` smoke
tests).
"""
from __future__ import annotations

import os


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Render the MemeDog Radar dashboard."""
    import streamlit as st
    import pandas as pd

    from memedog.config import load_config
    from memedog.dashboard_helpers import compute_summary
    from memedog.models import SignalType
    from memedog.store import Store

    st.set_page_config(
        page_title="MemeDog Radar",
        page_icon="🐕",
        layout="wide",
    )

    st.title("🐕 MemeDog Radar — Signal Dashboard")

    # ------------------------------------------------------------------
    # Open store (path from env or default)
    # ------------------------------------------------------------------
    db_path = os.environ.get("MEMEDOG_DB", "memedog.db")
    store = Store(db_path)

    try:
        try:
            cfg = load_config()
        except Exception:
            cfg = None

        # ------------------------------------------------------------------
        # Section 1: Live signal stream
        # ------------------------------------------------------------------
        st.header("1. Live Signal Stream")

        signals = store.recent_signals(limit=50)

        if not signals:
            st.info("No signals recorded yet.  Run the pipeline to generate signals.")
        else:
            for sig in signals:
                # Color by signal type
                if sig.signal == SignalType.BULLISH:
                    color = "green"
                    icon = "🟢"
                elif sig.signal == SignalType.BEARISH:
                    color = "red"
                    icon = "🔴"
                else:
                    color = "orange"
                    icon = "🟡"

                red_flags_str = ", ".join(sig.red_flags) if sig.red_flags else "none"
                bull_str = "; ".join(sig.bull_points[:2]) if sig.bull_points else "—"
                bear_str = "; ".join(sig.bear_points[:2]) if sig.bear_points else "—"

                with st.container():
                    cols = st.columns([1, 2, 1, 1, 2])
                    cols[0].markdown(f"**{icon} {sig.symbol}**")
                    cols[1].markdown(
                        f"<span style='color:{color}'>{sig.signal.value}</span>",
                        unsafe_allow_html=True,
                    )
                    cols[2].markdown(f"Conf: **{sig.confidence:.0%}**")
                    cols[3].markdown(f"Score: **{sig.score_total:.1f}**")
                    cols[4].markdown(
                        f"Bull: {bull_str} | Bear: {bear_str} | Flags: {red_flags_str}"
                    )
                st.divider()

        # ------------------------------------------------------------------
        # Section 2: Paper trading — open positions + closed trades + summary
        # ------------------------------------------------------------------
        st.header("2. Paper Trading")

        open_positions = store.open_positions()
        all_trades = store.all_trades()

        col_open, col_summary = st.columns([2, 1])

        with col_open:
            st.subheader("Open Positions")
            if open_positions:
                rows = [
                    {
                        "Symbol": p.symbol,
                        "Mint": p.mint[:8] + "...",
                        "Entry Price": f"${p.entry_price:.6f}",
                        "Size USD": f"${p.size_usd:.2f}",
                        "Status": p.status,
                        "TP %": f"{p.take_profit_pct:.0%}",
                        "SL %": f"{p.stop_loss_pct:.0%}",
                    }
                    for p in open_positions
                ]
                st.dataframe(pd.DataFrame(rows), use_container_width=True)
            else:
                st.info("No open positions.")

        starting_balance = (
            cfg.papertrader.starting_balance_usd if cfg else 10_000.0
        )
        summary = compute_summary(all_trades, starting_balance=starting_balance)

        with col_summary:
            st.subheader("Summary")
            st.metric("Balance", f"${summary['balance']:,.2f}")
            st.metric("Total PnL", f"${summary['total_pnl']:+,.2f}")
            st.metric("Win Rate", f"{summary['win_rate']:.1%}")
            st.metric("Avg Hold", f"{summary['avg_hold_minutes']:.0f} min")
            st.metric("Trades", str(summary["num_trades"]))

        st.subheader("Closed Trades")
        if all_trades:
            rows = [
                {
                    "Symbol": t.symbol,
                    "Entry": f"${t.entry_price:.6f}",
                    "Exit": f"${t.exit_price:.6f}",
                    "PnL USD": f"${t.pnl_usd:+.2f}",
                    "PnL %": f"{t.pnl_pct * 100:+.1f}%",
                    "Reason": t.exit_reason,
                    "Entry Time": t.entry_time.strftime("%Y-%m-%d %H:%M"),
                    "Exit Time": t.exit_time.strftime("%Y-%m-%d %H:%M"),
                }
                for t in all_trades
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No closed trades yet.")

        # ------------------------------------------------------------------
        # Section 3: Candidate funnel
        # ------------------------------------------------------------------
        st.header("3. Candidate Funnel")

        snapshots = store.recent_snapshots(limit=200)
        num_snapshots = len(snapshots)
        num_signals = len(signals)

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Snapshots (enriched candidates)", str(num_snapshots))
        col_b.metric("Signals generated", str(num_signals))
        col_c.metric("Conversion rate", f"{(num_signals / num_snapshots * 100):.1f}%" if num_snapshots else "—")

        st.caption(
            "Funnel stages: Scanner → HardFilter → Enricher (snapshots) → ScoreEngine → LLMJudge (signals)"
        )

        # ------------------------------------------------------------------
        # Section 4: Config snapshot
        # ------------------------------------------------------------------
        st.header("4. Config Snapshot")

        if cfg is None:
            st.warning("Could not load config (thresholds.yaml not found).")
        else:
            col1, col2, col3 = st.columns(3)

            with col1:
                st.subheader("HardFilter Thresholds")
                st.json(
                    {
                        "min_liquidity_usd": cfg.hardfilter.momentum.min_liquidity_usd,
                        "min_volume_5m": cfg.hardfilter.momentum.min_volume_5m,
                        "max_top10_pct": cfg.hardfilter.holders.max_top10_pct,
                        "max_single_wallet_pct": cfg.hardfilter.holders.max_single_wallet_pct,
                        "max_dev_pct": cfg.hardfilter.holders.max_dev_pct,
                    }
                )

            with col2:
                st.subheader("Scoring Weights")
                st.json(cfg.scoring.weights)
                st.subheader("Alert Config")
                st.json(
                    {
                        "enabled": cfg.alert.enabled,
                        "only_signal": cfg.alert.only_signal,
                        "min_confidence": cfg.alert.min_confidence,
                    }
                )

            with col3:
                st.subheader("LLM Models")
                st.json(cfg.llmjudge.models)
                st.subheader("PaperTrader")
                st.json(
                    {
                        "starting_balance_usd": cfg.papertrader.starting_balance_usd,
                        "size_usd": cfg.papertrader.size_usd,
                        "take_profit_pct": cfg.papertrader.take_profit_pct,
                        "stop_loss_pct": cfg.papertrader.stop_loss_pct,
                        "max_hold_minutes": cfg.papertrader.max_hold_minutes,
                        "entry_min_confidence": cfg.papertrader.entry_min_confidence,
                    }
                )
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
