"""Tests for demo source components."""
import json
import pytest

from memedog.demo.demo_source import ReplayProvider


@pytest.mark.asyncio
async def test_replay_provider_cycles_bull_bear_judge():
    p = ReplayProvider()
    # 3 calls per judge() — bull, bear, judge(JSON)
    bull = await p.complete(model="", messages=[{"role": "user", "content": "x"}])
    bear = await p.complete(model="", messages=[{"role": "user", "content": "x"}])
    judge = await p.complete(model="", messages=[{"role": "user", "content": "x"}])
    assert isinstance(bull, str) and bull
    assert isinstance(bear, str) and bear
    parsed = json.loads(judge)
    assert parsed["signal"] in ("BULLISH", "BEARISH", "NEUTRAL")
    assert 0.0 <= parsed["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_replay_provider_never_exhausts():
    p = ReplayProvider()
    # 30 calls (10 judge rounds) must not raise
    for _ in range(30):
        out = await p.complete(model="", messages=[{"role": "user", "content": "x"}])
        assert isinstance(out, str) and out


@pytest.mark.asyncio
async def test_demo_enricher_returns_snapshot_offline():
    from memedog.demo.demo_source import DemoScanner, DemoEnricher
    cand = (await DemoScanner().scan())[0]
    snap = await DemoEnricher().enrich(cand)
    assert snap.candidate.mint == cand.mint
    assert snap.safety.available and snap.momentum.available


@pytest.mark.asyncio
async def test_demo_rugcheck_report_parses_and_passes_authorities():
    from memedog.demo.demo_source import DemoRugCheckClient
    from memedog.clients.rugcheck import parse_report
    raw = await DemoRugCheckClient().get_token_report("anymint")
    parsed = parse_report(raw)
    assert parsed["mint_authority_revoked"] is True
    assert parsed["freeze_authority_revoked"] is True


@pytest.mark.asyncio
async def test_demo_price_fn_returns_float():
    from memedog.demo.demo_source import build_demo_price_fn
    fn = build_demo_price_fn()
    price = await fn("anymint")
    assert isinstance(price, float) and price > 0


@pytest.mark.asyncio
async def test_replay_provider_drives_real_judge():
    """ReplayProvider plugged into the real LLMJudge yields a real Signal."""
    from memedog.llmjudge.judge import LLMJudge
    from memedog.config import load_config
    from memedog.demo.demo_source import build_demo_snapshot, DemoScanner
    from memedog.scoring.engine import ScoreEngine

    cfg = load_config()
    cand = (await DemoScanner().scan())[0]
    snap = build_demo_snapshot(cand)
    score = ScoreEngine(cfg=cfg.scoring).score(snap)
    judge = LLMJudge(cfg.llmjudge, provider=ReplayProvider())
    sig = await judge.judge(snap, score)
    assert sig.signal.value in ("BULLISH", "BEARISH", "NEUTRAL")
    assert "降级" not in sig.rationale  # replay succeeded, not degraded
