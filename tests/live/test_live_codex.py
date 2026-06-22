"""Live Codex tests — need the codex CLI installed + `codex login`. Self-skip otherwise.

Run with:  python -m pytest -m live tests/live/test_live_codex.py -v
These are slow (real codex calls, tens of seconds each).
"""
import shutil
from datetime import datetime, timezone

import pytest

from memedog.config import load_config
from memedog.llm.codex_provider import CodexCLIProvider
from memedog.llmjudge.judge import LLMJudge
from memedog.models import (
    DimensionScore,
    HolderInfo,
    MomentumInfo,
    SafetyInfo,
    Score,
    SignalType,
    SocialInfo,
    TokenCandidate,
    TokenSnapshot,
)

pytestmark = pytest.mark.live


def _resolve_codex_bin() -> str | None:
    """Return a runnable codex binary path, or None to skip."""
    cfg = load_config()
    bin_name = cfg.llmjudge.codex.bin
    return shutil.which(bin_name) or (bin_name if shutil.which(bin_name) else None)


async def test_live_codex_complete_returns_text():
    bin_path = _resolve_codex_bin()
    if not bin_path:
        pytest.skip("codex binary not found on PATH (install + `codex login`)")
    provider = CodexCLIProvider(codex_bin=bin_path, timeout=240)
    out = await provider.complete(
        model="",
        messages=[{"role": "user", "content": "Reply with ONLY this exact JSON: {\"ok\": true}"}],
    )
    assert "ok" in out.lower()


def _strong_snapshot_score():
    cand = TokenCandidate(
        mint="LiveStrongMint", pair_address="P", symbol="MOON",
        pair_created_at=datetime.now(timezone.utc), price_usd=0.001, liquidity_usd=60000,
        fdv_usd=200000, volume_5m=15000, volume_1h=90000, txns_5m_buys=200, txns_5m_sells=40,
        price_change_5m=35.0, trace_id="live-strong",
    )
    snap = TokenSnapshot(
        candidate=cand,
        safety=SafetyInfo(available=True, mint_authority_revoked=True, freeze_authority_revoked=True,
                          lp_burned_or_locked=True, rug_trust_score=95, rug_risk_level="LOW"),
        holders=HolderInfo(available=True, top10_pct=22, max_wallet_pct=4, holder_count=800, sniper_pct=2),
        momentum=MomentumInfo(available=True, liquidity_usd=60000, volume_5m=15000, volume_1h=90000,
                              buy_sell_ratio_5m=5.0, unique_buyers_1h=150, fdv_to_liquidity=3.3),
        social=SocialInfo(available=True, smart_money_buys=8, twitter_mentions_1h=120, twitter_growth=1.5),
        enriched_at=datetime.now(timezone.utc),
    )
    score = Score(mint="LiveStrongMint", total=86.0, trace_id="live-strong", dimensions=[
        DimensionScore(name="safety", raw=95, weight=0.35, weighted=33.3),
        DimensionScore(name="holders", raw=88, weight=0.25, weighted=22.0),
        DimensionScore(name="momentum", raw=82, weight=0.25, weighted=20.5),
        DimensionScore(name="social", raw=70, weight=0.15, weighted=10.5),
    ])
    return snap, score


async def test_live_judge_is_not_degraded():
    bin_path = _resolve_codex_bin()
    if not bin_path:
        pytest.skip("codex binary not found on PATH (install + `codex login`)")
    cfg = load_config()
    cfg.llmjudge.codex.bin = bin_path
    cfg.llmjudge.codex.timeout_sec = 240

    snap, score = _strong_snapshot_score()
    judge = LLMJudge(cfg.llmjudge)  # production path: make_provider + cfg.codex
    sig = await judge.judge(snap, score)

    assert sig.signal in (SignalType.BULLISH, SignalType.BEARISH, SignalType.NEUTRAL)
    assert 0.0 <= sig.confidence <= 1.0
    # Real LLM produced the verdict — it must NOT be the rule-based degrade fallback.
    assert "降级" not in sig.rationale
