"""Tests for prompt rendering (Task 5)."""
from datetime import datetime, timezone

import pytest

from memedog.models import (
    DimensionScore,
    HolderInfo,
    MomentumInfo,
    SafetyInfo,
    Score,
    SocialInfo,
    TokenCandidate,
    TokenSnapshot,
)
from memedog.llmjudge.prompts import bear_prompt, bull_prompt, judge_prompt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def candidate():
    return TokenCandidate(
        mint="MINT123",
        pair_address="PAIR456",
        symbol="DOGE2",
        chain="solana",
        pair_created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        price_usd=0.001,
        liquidity_usd=50000.0,
        fdv_usd=500000.0,
        volume_5m=2000.0,
        volume_1h=10000.0,
        txns_5m_buys=50,
        txns_5m_sells=20,
        price_change_5m=5.0,
        trace_id="trace-abc",
    )


@pytest.fixture
def snapshot_all_available(candidate):
    return TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(available=True, rug_trust_score=90),
        holders=HolderInfo(available=True, top10_pct=25.0),
        momentum=MomentumInfo(available=True, liquidity_usd=50000.0, volume_5m=2000.0),
        social=SocialInfo(available=True, smart_money_buys=3),
        enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def snapshot_social_missing(candidate):
    return TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(available=True, rug_trust_score=85),
        holders=HolderInfo(available=True, top10_pct=20.0),
        momentum=MomentumInfo(available=True, liquidity_usd=40000.0),
        social=SocialInfo(available=False),  # unavailable
        enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def score():
    return Score(
        mint="MINT123",
        total=72.5,
        dimensions=[
            DimensionScore(name="safety", raw=85.0, weight=0.35, weighted=29.75),
            DimensionScore(name="holders", raw=70.0, weight=0.25, weighted=17.5),
            DimensionScore(name="momentum", raw=60.0, weight=0.25, weighted=15.0),
            DimensionScore(name="social", raw=55.0, weight=0.15, weighted=8.25),
        ],
        trace_id="trace-abc",
    )


# ---------------------------------------------------------------------------
# bull_prompt tests
# ---------------------------------------------------------------------------


def test_bull_prompt_contains_symbol(snapshot_all_available, score):
    msgs = bull_prompt(snapshot_all_available, score)
    all_text = " ".join(m["content"] for m in msgs)
    assert "DOGE2" in all_text


def test_bull_prompt_contains_dimension_value(snapshot_all_available, score):
    msgs = bull_prompt(snapshot_all_available, score)
    all_text = " ".join(m["content"] for m in msgs)
    # Should mention at least one dimension score
    assert "safety" in all_text.lower() or "85" in all_text


def test_bull_prompt_notes_missing_dimension(snapshot_social_missing, score):
    msgs = bull_prompt(snapshot_social_missing, score)
    all_text = " ".join(m["content"] for m in msgs)
    # Should note social data is missing
    assert "social" in all_text.lower()
    assert "missing" in all_text.lower() or "缺失" in all_text


def test_bull_prompt_returns_list_of_messages(snapshot_all_available, score):
    msgs = bull_prompt(snapshot_all_available, score)
    assert isinstance(msgs, list)
    assert len(msgs) >= 1
    for m in msgs:
        assert "role" in m and "content" in m


# ---------------------------------------------------------------------------
# bear_prompt tests
# ---------------------------------------------------------------------------


def test_bear_prompt_contains_symbol(snapshot_all_available, score):
    msgs = bear_prompt(snapshot_all_available, score)
    all_text = " ".join(m["content"] for m in msgs)
    assert "DOGE2" in all_text


def test_bear_prompt_notes_missing_dimension(snapshot_social_missing, score):
    msgs = bear_prompt(snapshot_social_missing, score)
    all_text = " ".join(m["content"] for m in msgs)
    assert "social" in all_text.lower()
    assert "missing" in all_text.lower() or "缺失" in all_text


# ---------------------------------------------------------------------------
# judge_prompt tests
# ---------------------------------------------------------------------------


def test_judge_prompt_contains_symbol(snapshot_all_available, score):
    msgs = judge_prompt(snapshot_all_available, score, "bull text", "bear text")
    all_text = " ".join(m["content"] for m in msgs)
    assert "DOGE2" in all_text


def test_judge_prompt_contains_bull_and_bear_text(snapshot_all_available, score):
    msgs = judge_prompt(snapshot_all_available, score, "Bull says bullish", "Bear says bearish")
    all_text = " ".join(m["content"] for m in msgs)
    assert "Bull says bullish" in all_text
    assert "Bear says bearish" in all_text


def test_judge_prompt_instructs_json_output(snapshot_all_available, score):
    msgs = judge_prompt(snapshot_all_available, score, "bull", "bear")
    all_text = " ".join(m["content"] for m in msgs)
    # Must mention JSON output format and required fields
    assert "JSON" in all_text or "json" in all_text
    assert "signal" in all_text
    assert "confidence" in all_text


def test_judge_prompt_mentions_signal_values(snapshot_all_available, score):
    msgs = judge_prompt(snapshot_all_available, score, "bull", "bear")
    all_text = " ".join(m["content"] for m in msgs)
    assert "BULLISH" in all_text or "BEARISH" in all_text or "NEUTRAL" in all_text


def test_judge_prompt_notes_missing_dimension(snapshot_social_missing, score):
    msgs = judge_prompt(snapshot_social_missing, score, "bull", "bear")
    all_text = " ".join(m["content"] for m in msgs)
    assert "social" in all_text.lower()
    assert "missing" in all_text.lower() or "缺失" in all_text
