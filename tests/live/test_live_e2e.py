"""Live end-to-end test — runs ONE real orchestrator cycle against real APIs.

DexScreener + RugCheck need no key. Helius/Twitter degrade without keys.
Codex LLM judging runs if the codex binary is available (else LLMJudge degrades).
Telegram alerts are gated by config; this test does not force-send.

Run with:  python -m pytest -m live tests/live/test_live_e2e.py -v
Slow (real scan + filter + optional codex calls).
"""
import shutil
import tempfile
from pathlib import Path

import pytest

from memedog.app_factory import build_orchestrator
from memedog.config import load_config
from memedog.store import Store

pytestmark = pytest.mark.live


async def test_live_run_cycle_completes():
    cfg = load_config()
    # Point codex at a runnable binary if present (default cfg bin may not be on PATH here).
    codex_bin = shutil.which(cfg.llmjudge.codex.bin)
    if codex_bin:
        cfg.llmjudge.codex.bin = codex_bin
        cfg.llmjudge.codex.timeout_sec = 240

    db_path = tempfile.mktemp(suffix=".db")
    store = Store(db_path)
    orch = build_orchestrator(cfg, store)
    try:
        signals = await orch.run_cycle()
        # Market-dependent: signals may be empty if nothing survives the funnel.
        assert isinstance(signals, list)
        # A funnel event must always be persisted for the cycle.
        events = store.recent_funnel_events(limit=1)
        assert len(events) == 1
        e = events[0]
        assert e["scanned"] >= 0
        assert e["passed_hardfilter"] >= 0
        assert e["signals"] == len(signals)
    finally:
        store.close()
        p = Path(db_path)
        if p.exists():
            p.unlink()
