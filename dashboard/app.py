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

    # ------------------------------------------------------------------
    # Auto-refresh: use st.autorefresh when available (Streamlit >= 1.28),
    # otherwise fall back to a sidebar refresh-interval control + st.rerun().
    # All import and invocation is guarded so the app never crashes on older
    # Streamlit installs.
    # ------------------------------------------------------------------
    _REFRESH_DEFAULT_SEC = 30
    if hasattr(st, "autorefresh"):
        # streamlit-autorefresh or Streamlit >= 1.28 native
        try:
            refresh_sec = st.sidebar.number_input(
                "Auto-refresh interval (s)",
                min_value=5,
                max_value=300,
                value=_REFRESH_DEFAULT_SEC,
                step=5,
                key="_autorefresh_interval",
            )
            st.autorefresh(interval=int(refresh_sec) * 1000, key="_dashboard_autorefresh")
        except Exception:
            pass  # autorefresh not supported on this build — continue silently
    else:
        # Fallback: sidebar manual-refresh button
        st.sidebar.markdown("**Auto-refresh**")
        if st.sidebar.button("Refresh now", key="_manual_refresh"):
            st.rerun()

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

                with st.container():
                    cols = st.columns([1, 1, 1, 1, 2])
                    cols[0].markdown(f"**{icon} {sig.symbol}**")
                    cols[1].markdown(
                        f"<span style='color:{color}'>{sig.signal.value}</span>",
                        unsafe_allow_html=True,
                    )
                    cols[2].markdown(f"Conf: **{sig.confidence:.0%}**")
                    cols[3].markdown(f"Score: **{sig.score_total:.1f}**")
                    cols[4].markdown(f"`{sig.mint[:12]}...`")

                    with st.expander("Review debate and judge verdict"):
                        bull_tab, bear_tab, judge_tab = st.tabs(
                            ["Bull Case", "Bear Case", "Judge Verdict"]
                        )
                        with bull_tab:
                            if sig.bull_points:
                                for point in sig.bull_points:
                                    st.markdown(f"- {point}")
                            else:
                                st.info("No bull-case points recorded.")
                        with bear_tab:
                            if sig.bear_points:
                                for point in sig.bear_points:
                                    st.markdown(f"- {point}")
                            else:
                                st.info("No bear-case points recorded.")
                        with judge_tab:
                            verdict_cols = st.columns(3)
                            verdict_cols[0].metric("Verdict", sig.signal.value)
                            verdict_cols[1].metric("Confidence", f"{sig.confidence:.0%}")
                            verdict_cols[2].metric("Score", f"{sig.score_total:.1f}")
                            st.markdown("**Rationale**")
                            st.write(sig.rationale)
                            if sig.red_flags:
                                st.markdown("**Red Flags**")
                                for flag in sig.red_flags:
                                    st.markdown(f"- {flag}")
                            else:
                                st.caption("No red flags recorded.")
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
        # Section 3: Backtesting
        # ------------------------------------------------------------------
        st.header("3. Backtesting")

        backtest_reports = store.recent_backtest_reports(limit=5)
        if not backtest_reports:
            st.info("No backtest reports recorded yet. Run a backtest or seed demo data.")
        else:
            latest = backtest_reports[0]
            report = latest["report"]
            st.caption(
                f"{latest['name']} | "
                f"{latest['created_at'].strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
            metric_cols = st.columns(6)
            metric_cols[0].metric("Signals Seen", str(report.signals_seen))
            metric_cols[1].metric("Trades", str(report.trades_opened))
            metric_cols[2].metric("Win Rate", f"{report.win_rate:.1%}")
            metric_cols[3].metric("Total PnL", f"${report.total_pnl_usd:+,.2f}")
            metric_cols[4].metric("Avg PnL", f"{report.avg_pnl_pct * 100:+.1f}%")
            profit_factor = (
                "n/a" if report.profit_factor is None else f"{report.profit_factor:.2f}"
            )
            metric_cols[5].metric("Profit Factor", profit_factor)
            st.metric("Max Drawdown", f"${report.max_drawdown_usd:,.2f}")

            if report.trades:
                rows = [
                    {
                        "Symbol": t.symbol,
                        "Mint": t.mint[:12] + "...",
                        "Entry": f"${t.entry_price:.8f}",
                        "Exit": f"${t.exit_price:.8f}",
                        "PnL USD": f"${t.pnl_usd:+.2f}",
                        "PnL %": f"{t.pnl_pct * 100:+.1f}%",
                        "Reason": t.exit_reason,
                        "Entry Time": t.entry_time.strftime("%Y-%m-%d %H:%M"),
                        "Exit Time": t.exit_time.strftime("%Y-%m-%d %H:%M"),
                    }
                    for t in report.trades
                ]
                st.dataframe(pd.DataFrame(rows), use_container_width=True)
            else:
                st.info("Latest backtest did not open any trades.")

            if len(backtest_reports) > 1:
                st.subheader("Recent Backtest Runs")
                rows = [
                    {
                        "Name": item["name"],
                        "Created": item["created_at"].strftime("%Y-%m-%d %H:%M"),
                        "Signals": item["report"].signals_seen,
                        "Trades": item["report"].trades_opened,
                        "Win Rate": f"{item['report'].win_rate:.1%}",
                        "PnL USD": f"${item['report'].total_pnl_usd:+.2f}",
                    }
                    for item in backtest_reports
                ]
                st.dataframe(pd.DataFrame(rows), use_container_width=True)

        # ------------------------------------------------------------------
        # Section 4: Candidate funnel (driven by store.recent_funnel_events)
        # ------------------------------------------------------------------
        st.header("4. Candidate Funnel")

        funnel_events = store.recent_funnel_events(limit=20)

        if not funnel_events:
            st.info(
                "No funnel events recorded yet.  "
                "Run the pipeline (python -m memedog) to populate this section."
            )
        else:
            # Latest cycle metrics
            latest = funnel_events[0]
            col_a, col_b, col_c, col_d = st.columns(4)
            col_a.metric("Scanned (latest cycle)", str(latest["scanned"]))
            col_b.metric("Passed HardFilter", str(latest["passed_hardfilter"]))
            col_c.metric("Signals produced", str(latest["signals"]))
            conversion = (
                f"{latest['signals'] / latest['scanned'] * 100:.1f}%"
                if latest["scanned"] > 0
                else "—"
            )
            col_d.metric("Conversion", conversion)

            st.caption(
                f"Latest cycle: {latest['ts'].strftime('%Y-%m-%d %H:%M:%S UTC')}  |  "
                "Funnel: Scanner → HardFilter → Enricher → ScoreEngine → LLMJudge"
            )

            # Table of dropped candidates (flattened from recent events)
            dropped_rows = []
            for ev in funnel_events:
                ts_str = ev["ts"].strftime("%H:%M:%S")
                for mint, reason in ev["dropped"]:
                    dropped_rows.append(
                        {"Time": ts_str, "Mint": mint[:12] + "..." if len(mint) > 12 else mint, "Rule Hit": reason}
                    )

            st.subheader("Dropped Candidates (recent cycles)")
            if dropped_rows:
                st.dataframe(pd.DataFrame(dropped_rows), use_container_width=True)
            else:
                st.info("No candidates were dropped in the last 20 cycles.")

            # Table of flagged candidates
            flagged_rows = []
            for ev in funnel_events:
                ts_str = ev["ts"].strftime("%H:%M:%S")
                for mint, reason in ev["flagged"]:
                    flagged_rows.append(
                        {"Time": ts_str, "Mint": mint[:12] + "..." if len(mint) > 12 else mint, "Flag": reason}
                    )

            if flagged_rows:
                st.subheader("Flagged Candidates (passed with caveats)")
                st.dataframe(pd.DataFrame(flagged_rows), use_container_width=True)

        # ------------------------------------------------------------------
        # Section 5: Config snapshot
        # ------------------------------------------------------------------
        st.header("5. Config Snapshot")

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
