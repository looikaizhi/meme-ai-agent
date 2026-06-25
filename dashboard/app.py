"""MemeDog V2 Streamlit dashboard."""
from __future__ import annotations

import os


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
        scans = store.recent_scanner_items(limit=100)
        runs = store.recent_runs(limit=100)

        scan_col, run_col = st.columns([1, 2])

        with scan_col:
            st.subheader("GMGN New Pool Intake")
            if not scans:
                st.info("No V2 scanner intake yet.")
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
                            for row in scans
                        ]
                    ),
                    width="stretch",
                )

        with run_col:
            st.subheader("Audit Outcomes")
            if not runs:
                st.info("No V2 audit runs yet.")
            else:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Time": format_time_local(row["ts"]),
                                "CA": format_addr(row["ca_address"]),
                                "Status": row["status"],
                                "Signal": row["signal"] or "-",
                                "Recommended": row["recommended"],
                                "Confidence": (
                                    ""
                                    if row["confidence"] is None
                                    else f"{row['confidence']:.0%}"
                                ),
                                "Backend": row["backend"],
                                "Reason": _hardfilter_reason(row)[:180],
                                "Summary": row["summary"][:180],
                            }
                            for row in runs
                        ]
                    ),
                    width="stretch",
                )
    finally:
        store.close()


if __name__ == "__main__":
    main()
