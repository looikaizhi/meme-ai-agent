# MemeDog Verifiable Usage Records

This folder contains lightweight exports from the local `memedog.db` V2 tables for hackathon submission.

Generated from:

- `v2_scanner_items`: Telegram / GMGN launch pipeline inputs.
- `v2_runs`: Evaluation Lab and live LLM audit outputs.
- `v2_backtest_outcomes`: Forward outcome scoring for prior LLM decisions.

Files:

- `summary.json`: row counts and timestamp ranges for the exported source tables.
- `telegram_pipeline_inputs.csv`: recent candidate inputs from the Telegram / GMGN scanner pipeline.
- `evaluation_lab_outputs.csv`: recent MemeDog V2 LLM judgments with signal, confidence, entry price, liquidity, volume, and summary.
- `backtest_outcomes.csv`: scored outcomes for persisted runs, including horizon, observed price, return, verdict, and success flag.

These records are intended to satisfy the requirement:

> Verifiable usage record, such as test record, real user usage record, or sample input + output file.
