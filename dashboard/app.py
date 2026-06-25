"""MemeDog V2 Streamlit dashboard."""
from __future__ import annotations

import os
from collections import Counter


_STAGE_ICONS = {
    "scan": "🔍",
    "hardfilter": "🚧",
    "enrich": "🧪",
    "score": "📊",
    "judge": "⚖️",
    "signal": "📣",
    "trade": "💰",
    "error": "❌",
}


def format_event_row(event: dict) -> str:
    """Render one pipeline event as a compact one-line string."""
    icon = _STAGE_ICONS.get(event.get("stage", ""), "•")
    ts = event.get("ts")
    tstr = ts.strftime("%H:%M:%S") if hasattr(ts, "strftime") else str(ts)
    sym = event.get("symbol") or event.get("mint", "")[:8] or "—"
    status = event.get("status", "")
    detail = event.get("detail", "")
    return f"{tstr}  {icon} {event.get('stage','')}  {sym}  [{status}]  {detail}".rstrip()


def format_addr(addr: str, *, head: int = 8, tail: int = 6) -> str:
    """Compact a long token/wallet address for dashboard tables."""
    if not addr:
        return ""
    if len(addr) <= head + tail + 3:
        return addr
    return f"{addr[:head]}...{addr[-tail:]}"


def format_time_local(value) -> str:
    """Format a stored UTC timestamp in the machine's local timezone."""
    return value.astimezone().strftime("%H:%M:%S")


def _hardfilter_reason(row: dict) -> str:
    steps = row.get("payload", {}).get("steps", [])
    for step in steps:
        if step.get("name") == "hardfilter" and step.get("detail"):
            return str(step["detail"])
        if step.get("status") == "failed" and step.get("error"):
            return str(step["error"])
    return ""


def run_source(row: dict) -> str:
    payload = row.get("payload", {})
    return str(payload.get("source") or row.get("source") or "")


def run_stage(row: dict) -> str:
    payload = row.get("payload", {})
    return str(payload.get("stage") or row.get("stage") or "unknown")


def run_flags(row: dict) -> list[str]:
    payload = row.get("payload", {})
    flags = payload.get("hardfilter_flags", [])
    return [str(flag) for flag in flags] if isinstance(flags, list) else []


def is_telegram_scan(row: dict) -> bool:
    return str(row.get("source", "")).startswith("gmgn_telegram")


def is_telegram_run(row: dict) -> bool:
    source = run_source(row)
    return source.startswith("gmgn_telegram") or source == ""


def outcome_summary(outcomes: list[dict]) -> dict:
    if not outcomes:
        return {"count": 0, "success_rate": None, "avg_return_pct": None}
    wins = sum(1 for row in outcomes if row.get("success"))
    return {
        "count": len(outcomes),
        "success_rate": wins / len(outcomes),
        "avg_return_pct": sum(float(row.get("return_pct") or 0.0) for row in outcomes) / len(outcomes),
    }


def signal_counts(runs: list[dict]) -> dict[str, int]:
    counts = Counter(row.get("signal") or "NO_SIGNAL" for row in runs)
    return dict(counts)


def _runs_table(rows: list[dict]) -> list[dict]:
    return [
        {
            "Time": format_time_local(row["ts"]),
            "CA": format_addr(row["ca_address"]),
            "Source": run_source(row) or "-",
            "Stage": run_stage(row),
            "Status": row["status"],
            "Signal": row["signal"] or "-",
            "Recommended": row["recommended"],
            "Confidence": (
                ""
                if row["confidence"] is None
                else f"{row['confidence']:.0%}"
            ),
            "Backend": row["backend"],
            "Flags": "; ".join(run_flags(row))[:180],
            "Reason": _hardfilter_reason(row)[:180],
            "Summary": row["summary"][:180],
        }
        for row in rows
    ]


def _outcomes_table(rows: list[dict]) -> list[dict]:
    return [
        {
            "Observed": format_time_local(row["observed_ts"]),
            "CA": format_addr(row["ca_address"]),
            "Signal": row["signal"] or "-",
            "Recommended": row["recommended"],
            "Confidence": (
                ""
                if row["confidence"] is None
                else f"{row['confidence']:.0%}"
            ),
            "Entry": f"{row['entry_price_usd']:.8g}",
            "Observed Price": f"{row['observed_price_usd']:.8g}",
            "Return": f"{row['return_pct']:.2f}%",
            "Verdict": row["verdict"],
            "Success": row["success"],
            "Horizon": f"{row['horizon_min']}m",
        }
        for row in rows
    ]


def main() -> None:
    """Render only V2 scanner intake and audit outcomes."""
    import pandas as pd
    import streamlit as st

    from memedogV2.store import V2Store

    st.set_page_config(
        page_title="MemeDog V2",
        page_icon="🐕",
        layout="wide",
    )

    refresh_sec = st.sidebar.number_input(
        "Auto-refresh interval (s)",
        min_value=5,
        max_value=300,
        value=30,
        step=5,
        key="_autorefresh_interval",
    )
    if hasattr(st, "autorefresh"):
        try:
            st.autorefresh(interval=int(refresh_sec) * 1000, key="_dashboard_autorefresh")
        except Exception:
            pass
    elif st.sidebar.button("Refresh now", key="_manual_refresh"):
        st.rerun()

    st.title("MemeDog V2")

    db_path = os.environ.get("MEMEDOG_DB", "memedog.db")
    store = V2Store(db_path)
    try:
        scans = store.recent_scanner_items(limit=200)
        runs = store.recent_runs(limit=200)
        outcomes = store.recent_backtest_outcomes(limit=200)

        telegram_scans = [row for row in scans if is_telegram_scan(row)]
        eval_scans = [row for row in scans if not is_telegram_scan(row)]
        telegram_runs = [row for row in runs if is_telegram_run(row)]
        eval_runs = [row for row in runs if not is_telegram_run(row)]

        tab_live, tab_eval, tab_backtest = st.tabs(
            ["Telegram Launches", "Evaluation Lab", "Backtest"]
        )

        with tab_live:
            scan_col, run_col = st.columns([1, 2])
            with scan_col:
                st.subheader("GMGN New Pool Intake")
                if not telegram_scans:
                    st.info("No Telegram launch intake yet.")
                else:
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {
                                    "Time": format_time_local(row["ts"]),
                                    "CA": format_addr(row["ca_address"]),
                                    "LP": format_addr(row["lp_address"]),
                                    "Queued": row["enqueued"],
                                    "Trace": row["trace_id"],
                                }
                                for row in telegram_scans
                            ]
                        ),
                        width="stretch",
                    )

            with run_col:
                st.subheader("Telegram Audit Outcomes")
                if not telegram_runs:
                    st.info("No Telegram audit runs yet.")
                else:
                    st.dataframe(pd.DataFrame(_runs_table(telegram_runs)), width="stretch")

        with tab_eval:
            st.subheader("Curated Cohort Runs")
            metric_cols = st.columns(4)
            metric_cols[0].metric("Runs", len(eval_runs))
            metric_cols[1].metric("Signals", sum(1 for row in eval_runs if row["signal"]))
            metric_cols[2].metric(
                "Recommended",
                sum(1 for row in eval_runs if row["recommended"] is True),
            )
            metric_cols[3].metric("Sources", len({run_source(row) for row in eval_runs if run_source(row)}))

            if eval_runs:
                counts = signal_counts(eval_runs)
                st.bar_chart(pd.DataFrame([counts]).T.rename(columns={0: "count"}))
                st.dataframe(pd.DataFrame(_runs_table(eval_runs)), width="stretch")
            else:
                st.info("No curated evaluation runs yet.")

            st.subheader("Curated Intake")
            if eval_scans:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Time": format_time_local(row["ts"]),
                                "Source": row["source"],
                                "CA": format_addr(row["ca_address"]),
                                "LP": format_addr(row["lp_address"]),
                                "Queued": row["enqueued"],
                                "Trace": row["trace_id"],
                            }
                            for row in eval_scans
                        ]
                    ),
                    width="stretch",
                )

        with tab_backtest:
            summary = outcome_summary(outcomes)
            metric_cols = st.columns(3)
            metric_cols[0].metric("Evaluated", summary["count"])
            metric_cols[1].metric(
                "Success Rate",
                "-" if summary["success_rate"] is None else f"{summary['success_rate']:.0%}",
            )
            metric_cols[2].metric(
                "Avg Return",
                "-" if summary["avg_return_pct"] is None else f"{summary['avg_return_pct']:.2f}%",
            )

            if outcomes:
                st.dataframe(pd.DataFrame(_outcomes_table(outcomes)), width="stretch")
            else:
                st.info("No V2 backtest outcomes yet.")
    finally:
        store.close()


if __name__ == "__main__":
    main()
