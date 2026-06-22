"""Tests for LLMJudge (Task 6). Uses FakeProvider — no real LLM calls."""
import json
from datetime import datetime, timezone

import pytest

from memedog.llm.provider import FakeProvider
from memedog.models import (
    DimensionScore,
    HolderInfo,
    MomentumInfo,
    SafetyInfo,
    Score,
    Signal,
    SignalType,
    SocialInfo,
    TokenCandidate,
    TokenSnapshot,
)
from memedog.llmjudge.judge import LLMJudge, JudgeOut, StepFinding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(mint="MINT001", symbol="DOGX", trace_id="trace-1"):
    return TokenCandidate(
        mint=mint,
        pair_address="PAIR001",
        symbol=symbol,
        chain="solana",
        pair_created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        price_usd=0.0001,
        liquidity_usd=30000.0,
        fdv_usd=300000.0,
        volume_5m=1500.0,
        volume_1h=8000.0,
        txns_5m_buys=40,
        txns_5m_sells=15,
        price_change_5m=3.0,
        trace_id=trace_id,
    )


def _make_snapshot(mint="MINT001", symbol="DOGX", trace_id="trace-1"):
    return TokenSnapshot(
        candidate=_make_candidate(mint=mint, symbol=symbol, trace_id=trace_id),
        safety=SafetyInfo(available=True, rug_trust_score=88),
        holders=HolderInfo(available=True, top10_pct=22.0),
        momentum=MomentumInfo(available=True, liquidity_usd=30000.0, volume_5m=1500.0),
        social=SocialInfo(available=True, smart_money_buys=2),
        enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _make_score(mint="MINT001", total=72.0, trace_id="trace-1"):
    return Score(
        mint=mint,
        total=total,
        dimensions=[
            DimensionScore(name="safety", raw=88.0, weight=0.35, weighted=30.8),
            DimensionScore(name="holders", raw=75.0, weight=0.25, weighted=18.75),
            DimensionScore(name="momentum", raw=60.0, weight=0.25, weighted=15.0),
            DimensionScore(name="social", raw=50.0, weight=0.15, weighted=7.5),
        ],
        trace_id=trace_id,
    )


def _judge_json(
    signal="BULLISH",
    confidence=0.75,
    bull_points=None,
    bear_points=None,
    red_flags=None,
    rationale="Looks good",
):
    return json.dumps(
        {
            "signal": signal,
            "confidence": confidence,
            "bull_points": bull_points or ["Strong momentum"],
            "bear_points": bear_points or ["High top10 concentration"],
            "red_flags": red_flags or [],
            "rationale": rationale,
        }
    )


def _make_fake_cfg():
    """Return a minimal LLMJudgeConfig-like object for tests."""
    from memedog.config.settings import CodexConfig, LLMJudgeConfig

    return LLMJudgeConfig(
        models={"bull": "codex:default", "bear": "codex:default", "judge": "codex:default"},
        temperature={"bull": 0.5, "bear": 0.5, "judge": 0.2},
        max_tokens=512,
        repair_retries=1,
        codex=CodexConfig(bin="codex", timeout_sec=30, sandbox="read-only"),
    )


# ---------------------------------------------------------------------------
# Sub-project A — JudgeOut.workflow schema (backward compatible)
# ---------------------------------------------------------------------------


def test_config_has_confidence_guard_defaults():
    """LLMJudgeConfig exposes a confidence_guard with enabled + floor."""
    from memedog.config import load_config

    cfg = load_config().llmjudge
    assert hasattr(cfg, "confidence_guard")
    assert cfg.confidence_guard.enabled is True
    assert 0.0 <= cfg.confidence_guard.floor <= 1.0


def test_judgeout_parses_workflow_field():
    """JudgeOut accepts a structured workflow array."""
    data = {
        "signal": "BULLISH",
        "confidence": 0.7,
        "bull_points": ["x"],
        "bear_points": ["y"],
        "red_flags": [],
        "rationale": "ok",
        "workflow": [
            {"step": "safety", "assessment": "pass", "note": "authorities revoked"},
            {"step": "momentum", "assessment": "concern", "note": "thin volume"},
        ],
    }
    out = JudgeOut.model_validate(data)
    assert len(out.workflow) == 2
    assert out.workflow[0].step == "safety"
    assert out.workflow[0].assessment == "pass"
    assert isinstance(out.workflow[1], StepFinding)


def test_judgeout_workflow_defaults_empty_when_absent():
    """Old bodies without 'workflow' still parse (backward compat)."""
    data = {
        "signal": "BEARISH",
        "confidence": 0.6,
        "bull_points": [],
        "bear_points": ["z"],
        "red_flags": ["flag"],
        "rationale": "old body",
    }
    out = JudgeOut.model_validate(data)
    assert out.workflow == []


# ---------------------------------------------------------------------------
# Task 6 — happy path using REAL captured codex fixtures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_happy_path_bullish_real_fixtures(fixture):
    """Bull/bear/judge use real captured codex outputs → BULLISH Signal with real fields.

    Call ordering: asyncio.gather runs bull (idx=0) then bear (idx=1) concurrently,
    followed by judge (idx=2). FakeProvider consumes by index.
    """
    bull_text = fixture("codex/bull_argument.txt")    # real ~2KB bull argument
    bear_text = fixture("codex/bear_argument.txt")    # real ~2.5KB bear argument
    judge_data = fixture("codex/judge_bullish.json")  # real JudgeOut dict
    judge_json_str = json.dumps(judge_data)

    # index 0 → bull, index 1 → bear, index 2 → judge
    fp = FakeProvider([bull_text, bear_text, judge_json_str])

    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    snapshot = _make_snapshot(mint="MINT001", symbol="DOGX", trace_id="trace-1")
    score = _make_score(mint="MINT001", total=72.0, trace_id="trace-1")

    result = await judge.judge(snapshot, score)

    assert isinstance(result, Signal)
    assert result.mint == "MINT001"
    assert result.symbol == "DOGX"
    # Verify against REAL fixture values
    assert result.signal == SignalType.BULLISH
    # snapshot is fully available → completeness guard cap=1.0 → confidence unchanged
    assert result.confidence == pytest.approx(judge_data["confidence"])
    assert result.score_total == pytest.approx(72.0)
    assert result.trace_id == "trace-1"
    # Verify real fixture bull_points / bear_points / red_flags
    assert result.bull_points == judge_data["bull_points"]
    assert result.bear_points == judge_data["bear_points"]
    assert result.red_flags == judge_data["red_flags"]
    # rationale now carries the folded workflow summary + the original rationale
    assert judge_data["rationale"] in result.rationale
    assert judge_data["workflow"][0]["step"] in result.rationale


@pytest.mark.asyncio
async def test_judge_happy_path_bearish_real_fixtures(fixture):
    """Real judge_bearish.json fixture → BEARISH Signal with confidence=0.82."""
    bull_text = fixture("codex/bull_argument.txt")
    bear_text = fixture("codex/bear_argument.txt")
    judge_data = fixture("codex/judge_bearish.json")  # real BEARISH JudgeOut
    judge_json_str = json.dumps(judge_data)

    fp = FakeProvider([bull_text, bear_text, judge_json_str])

    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    result = await judge.judge(_make_snapshot(), _make_score())

    assert result.signal == SignalType.BEARISH
    # snapshot is fully available → completeness guard cap=1.0 → confidence unchanged
    assert result.confidence == pytest.approx(judge_data["confidence"])
    assert result.bull_points == judge_data["bull_points"]
    assert result.bear_points == judge_data["bear_points"]
    assert result.red_flags == judge_data["red_flags"]
    # rationale now carries the folded workflow summary + the original rationale
    assert judge_data["rationale"] in result.rationale
    assert judge_data["workflow"][0]["step"] in result.rationale


@pytest.mark.asyncio
async def test_judge_neutral_signal():
    """Constructed NEUTRAL JSON → NEUTRAL (logic edge case, no real fixture covers it)."""
    neutral_json = _judge_json(signal="NEUTRAL", confidence=0.5)
    fp = FakeProvider(["bull", "bear", neutral_json])

    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    result = await judge.judge(_make_snapshot(), _make_score())

    assert result.signal == SignalType.NEUTRAL


@pytest.mark.asyncio
async def test_judge_confidence_clamped_to_zero_one():
    """Confidence values outside [0,1] should be clamped (constructed edge cases)."""
    too_high = _judge_json(signal="BULLISH", confidence=1.5)
    fp = FakeProvider(["bull", "bear", too_high])

    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    result = await judge.judge(_make_snapshot(), _make_score())
    assert result.confidence <= 1.0

    too_low = _judge_json(signal="BEARISH", confidence=-0.3)
    fp2 = FakeProvider(["bull", "bear", too_low])
    judge2 = LLMJudge(cfg=_make_fake_cfg(), provider=fp2)
    result2 = await judge2.judge(_make_snapshot(), _make_score())
    assert result2.confidence >= 0.0


@pytest.mark.asyncio
async def test_judge_unknown_signal_string_defaults_neutral():
    """Unrecognized signal string → NEUTRAL (constructed edge case)."""
    weird_json = _judge_json(signal="MAYBE", confidence=0.5)
    fp = FakeProvider(["bull", "bear", weird_json])

    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    result = await judge.judge(_make_snapshot(), _make_score())
    assert result.signal == SignalType.NEUTRAL


@pytest.mark.asyncio
async def test_judge_result_has_bull_bear_red_flag_rationale():
    """Signal carries bull_points, bear_points, red_flags, rationale from JudgeOut.

    Kept as constructed test — this verifies the mapping logic specifically,
    separate from the fixture-based tests above.
    """
    out_json = _judge_json(
        signal="BULLISH",
        confidence=0.7,
        bull_points=["high smart money"],
        bear_points=["low liquidity"],
        red_flags=["dev wallet 8%"],
        rationale="Net positive",
    )
    fp = FakeProvider(["bull text", "bear text", out_json])

    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    result = await judge.judge(_make_snapshot(), _make_score())

    assert "high smart money" in result.bull_points
    assert "low liquidity" in result.bear_points
    assert "dev wallet 8%" in result.red_flags
    assert result.rationale == "Net positive"


# ---------------------------------------------------------------------------
# Sub-project A — workflow folding + confidence guard
# ---------------------------------------------------------------------------


def _make_snapshot_missing(n_missing: int):
    """Snapshot with the last n dimensions marked unavailable (order: social, momentum, holders)."""
    snap = _make_snapshot()
    if n_missing >= 1:
        snap.social = SocialInfo(available=False)
    if n_missing >= 2:
        snap.momentum = MomentumInfo(available=False)
    if n_missing >= 3:
        snap.holders = HolderInfo(available=False)
    return snap


def _judge_json_with_workflow(confidence=0.95):
    return json.dumps({
        "signal": "BULLISH",
        "confidence": confidence,
        "bull_points": ["strong liquidity $42,300"],
        "bear_points": ["social missing"],
        "red_flags": [],
        "rationale": "Net positive.",
        "workflow": [
            {"step": "safety", "assessment": "pass", "note": "authorities revoked"},
            {"step": "momentum", "assessment": "pass", "note": "liquidity healthy"},
        ],
    })


@pytest.mark.asyncio
async def test_judge_folds_workflow_into_rationale():
    fp = FakeProvider(["bull", "bear", _judge_json_with_workflow(confidence=0.6)])
    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    result = await judge.judge(_make_snapshot(), _make_score())
    # rationale carries both the step summary and the original rationale
    assert "safety:pass" in result.rationale
    assert "Net positive." in result.rationale


@pytest.mark.asyncio
async def test_judge_confidence_guard_caps_on_missing_dimensions():
    # 2 missing dimensions → completeness=0.5 → cap = 0.5 + 0.5*0.5 = 0.75
    fp = FakeProvider(["bull", "bear", _judge_json_with_workflow(confidence=0.95)])
    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    result = await judge.judge(_make_snapshot_missing(2), _make_score())
    assert result.confidence == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_judge_confidence_guard_noop_when_all_available():
    fp = FakeProvider(["bull", "bear", _judge_json_with_workflow(confidence=0.9)])
    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    # all 4 available → completeness=1.0 → cap=1.0 → unchanged
    result = await judge.judge(_make_snapshot(), _make_score())
    assert result.confidence == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_judge_confidence_guard_disabled():
    from memedog.config.settings import ConfidenceGuardConfig
    cfg = _make_fake_cfg()
    cfg.confidence_guard = ConfidenceGuardConfig(enabled=False, floor=0.5)
    fp = FakeProvider(["bull", "bear", _judge_json_with_workflow(confidence=0.95)])
    judge = LLMJudge(cfg=cfg, provider=fp)
    result = await judge.judge(_make_snapshot_missing(3), _make_score())
    assert result.confidence == pytest.approx(0.95)  # not capped


# ---------------------------------------------------------------------------
# Task 6 — degrade path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_degrades_on_provider_error():
    """If provider raises, degrade to rule-based signal; rationale contains '降级'."""
    from memedog.llm.provider import LLMProviderError

    class _ErrorProvider:
        async def complete(self, *, model, messages, temperature=0.3, max_tokens=1024):
            raise LLMProviderError("network fail")

    judge = LLMJudge(cfg=_make_fake_cfg(), provider=_ErrorProvider())
    score = _make_score(total=75.0)  # above 70 → BULLISH
    result = await judge.judge(_make_snapshot(), score)

    assert isinstance(result, Signal)
    assert "降级" in result.rationale
    assert result.signal == SignalType.BULLISH


@pytest.mark.asyncio
async def test_judge_degrades_bearish_on_low_score():
    """Score ≤ 40 → degraded BEARISH."""
    from memedog.llm.provider import LLMProviderError

    class _ErrorProvider:
        async def complete(self, *, model, messages, temperature=0.3, max_tokens=1024):
            raise LLMProviderError("fail")

    judge = LLMJudge(cfg=_make_fake_cfg(), provider=_ErrorProvider())
    score = _make_score(total=35.0)
    result = await judge.judge(_make_snapshot(), score)

    assert result.signal == SignalType.BEARISH
    assert "降级" in result.rationale


@pytest.mark.asyncio
async def test_judge_degrades_neutral_on_mid_score():
    """Score between 40 and 70 → degraded NEUTRAL."""
    from memedog.llm.provider import LLMProviderError

    class _ErrorProvider:
        async def complete(self, *, model, messages, temperature=0.3, max_tokens=1024):
            raise LLMProviderError("fail")

    judge = LLMJudge(cfg=_make_fake_cfg(), provider=_ErrorProvider())
    score = _make_score(total=55.0)
    result = await judge.judge(_make_snapshot(), score)

    assert result.signal == SignalType.NEUTRAL
    assert "降级" in result.rationale


@pytest.mark.asyncio
async def test_judge_never_raises():
    """judge() must never propagate exceptions — always returns a Signal."""
    from memedog.llm.provider import LLMProviderError

    class _AlwaysCrash:
        async def complete(self, *, model, messages, temperature=0.3, max_tokens=1024):
            raise RuntimeError("unexpected crash")

    judge = LLMJudge(cfg=_make_fake_cfg(), provider=_AlwaysCrash())
    result = await judge.judge(_make_snapshot(), _make_score())
    assert isinstance(result, Signal)


@pytest.mark.asyncio
async def test_judge_degrade_confidence_in_range():
    """Degraded signal confidence is between 0 and 1."""
    from memedog.llm.provider import LLMProviderError

    class _ErrorProvider:
        async def complete(self, *, model, messages, temperature=0.3, max_tokens=1024):
            raise LLMProviderError("fail")

    for total in [20.0, 50.0, 80.0]:
        judge = LLMJudge(cfg=_make_fake_cfg(), provider=_ErrorProvider())
        result = await judge.judge(_make_snapshot(), _make_score(total=total))
        assert 0.0 <= result.confidence <= 1.0, f"total={total} gave confidence={result.confidence}"


def test_judge_honors_codex_config_bin_timeout():
    """LLMJudge (non-injected) must build CodexCLIProvider from cfg.codex,
    not from CodexCLIProvider defaults — so bin/timeout/sandbox are configurable."""
    from memedog.config import load_config
    from memedog.llm.codex_provider import CodexCLIProvider

    cfg = load_config().llmjudge
    cfg.codex.bin = "my-custom-codex"
    cfg.codex.timeout_sec = 99
    cfg.codex.sandbox = "read-only"

    judge = LLMJudge(cfg)  # no injected provider → production make_provider path
    provider, model = judge._get_provider_and_model("bull")

    assert isinstance(provider, CodexCLIProvider)
    assert provider._bin == "my-custom-codex"
    assert provider._timeout == 99
    assert model == ""  # codex:default → empty model name
