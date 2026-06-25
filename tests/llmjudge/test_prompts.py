"""Tests for prompt rendering (Task 5)."""
from datetime import datetime, timezone

import pytest

from memedog.models import (
    DimensionScore,
    HolderInfo,
    MomentumInfo,
    NarrativeInfo,
    SafetyInfo,
    Score,
    SocialInfo,
    TokenCandidate,
    TokenSnapshot,
    WalletInfo,
)
from memedog.llmjudge.prompts import (
    bear_prompt,
    bull_prompt,
    judge_prompt,
    _snapshot_evidence,
)


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
# _snapshot_evidence tests (Task 3)
# ---------------------------------------------------------------------------


@pytest.fixture
def snapshot_rich(candidate):
    return TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(
            available=True, mint_authority_revoked=True, freeze_authority_revoked=True,
            lp_burned_or_locked=True, rug_trust_score=78, rug_risk_level="LOW",
        ),
        holders=HolderInfo(
            available=True, top10_pct=24.5, max_wallet_pct=6.2,
            dev_wallet_pct=3.1, holder_count=412, sniper_pct=8.0,
        ),
        momentum=MomentumInfo(
            available=True, liquidity_usd=42300.0, volume_5m=18400.0, volume_1h=96200.0,
            buy_sell_ratio_5m=1.8, unique_buyers_1h=210, fdv_to_liquidity=3.2,
        ),
        social=SocialInfo(available=False),
        enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def test_evidence_contains_raw_values(snapshot_rich, score):
    text = _snapshot_evidence(snapshot_rich, score)
    assert "42,300" in text          # liquidity formatted with thousands sep
    assert "24.5%" in text           # top10 pct
    assert "78" in text              # trust score
    assert "1.80" in text            # buy/sell ratio 2dp


def test_evidence_marks_missing_dimension(snapshot_rich, score):
    text = _snapshot_evidence(snapshot_rich, score)
    # social is unavailable
    assert "SOCIAL" in text.upper()
    assert "DATA MISSING" in text.upper() or "缺失" in text


def test_evidence_omits_none_fields(candidate, score):
    # holders available but only top10 set; others None must not render "None"
    snap = TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(available=True, rug_trust_score=80),
        holders=HolderInfo(available=True, top10_pct=20.0),
        momentum=MomentumInfo(available=True, liquidity_usd=30000.0),
        social=SocialInfo(available=False),
        enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    text = _snapshot_evidence(snap, score)
    assert "None" not in text


def test_evidence_includes_prescore_reference(snapshot_rich, score):
    text = _snapshot_evidence(snapshot_rich, score)
    # the composite pre-score (72.5 from the `score` fixture) appears as reference
    assert "72.5" in text
    assert "RULE BASELINE" in text
    assert "not final truth" in text


def test_evidence_places_raw_values_before_rule_baseline(snapshot_rich, score):
    text = _snapshot_evidence(snapshot_rich, score)
    assert text.index("42,300") < text.index("RULE BASELINE")
    assert text.index("24.5%") < text.index("RULE BASELINE")
    assert text.index("trust=78/100") < text.index("RULE BASELINE")


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


def test_bull_prompt_injects_raw_evidence(snapshot_rich, score):
    msgs = bull_prompt(snapshot_rich, score)
    all_text = " ".join(m["content"] for m in msgs)
    assert "42,300" in all_text          # raw liquidity present
    assert "top10" in all_text
    assert "持币人" in all_text
    assert "5min量" in all_text
    assert "mint撤权" in all_text


def test_bull_prompt_demands_data_citation(snapshot_rich, score):
    msgs = bull_prompt(snapshot_rich, score)
    all_text = " ".join(m["content"] for m in msgs).lower()
    assert "cite" in all_text or "引用" in all_text


def test_bull_prompt_warns_rule_baseline_is_not_final(snapshot_rich, score):
    msgs = bull_prompt(snapshot_rich, score)
    all_text = " ".join(m["content"] for m in msgs).lower()
    assert "rule baseline" in all_text
    assert "not a conclusion" in all_text or "not final truth" in all_text
    assert "raw field" in all_text


def test_bear_prompt_injects_raw_evidence(snapshot_rich, score):
    msgs = bear_prompt(snapshot_rich, score)
    all_text = " ".join(m["content"] for m in msgs)
    assert "42,300" in all_text
    assert "top10" in all_text
    assert "持币人" in all_text
    assert "5min量" in all_text
    assert "mint撤权" in all_text


def test_bear_prompt_warns_rule_baseline_is_not_final(snapshot_rich, score):
    msgs = bear_prompt(snapshot_rich, score)
    all_text = " ".join(m["content"] for m in msgs).lower()
    assert "rule baseline" in all_text
    assert "not a conclusion" in all_text or "not final truth" in all_text
    assert "raw field" in all_text


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


def test_judge_prompt_lists_workflow_steps(snapshot_all_available, score):
    msgs = judge_prompt(snapshot_all_available, score, "bull", "bear")
    all_text = " ".join(m["content"] for m in msgs).lower()
    for step in ["safety", "concentration", "momentum", "social", "debate"]:
        assert step in all_text, f"workflow step '{step}' missing from judge prompt"


def test_judge_prompt_requests_workflow_json_field(snapshot_all_available, score):
    msgs = judge_prompt(snapshot_all_available, score, "bull", "bear")
    all_text = " ".join(m["content"] for m in msgs)
    assert "workflow" in all_text


def test_judge_prompt_injects_raw_evidence(snapshot_rich, score):
    msgs = judge_prompt(snapshot_rich, score, "bull", "bear")
    all_text = " ".join(m["content"] for m in msgs)
    assert "42,300" in all_text


def test_judge_prompt_treats_score_as_guardrail_not_verdict(snapshot_rich, score):
    msgs = judge_prompt(snapshot_rich, score, "bull", "bear")
    all_text = " ".join(m["content"] for m in msgs).lower()
    assert "rule baseline" in all_text
    assert "audit guardrail" in all_text or "audit metadata" in all_text
    assert "not final truth" in all_text
    assert "raw evidence" in all_text


def test_judge_prompt_places_evidence_before_debate_and_baseline_before_debate(snapshot_rich, score):
    msgs = judge_prompt(snapshot_rich, score, "bull text", "bear text")
    user_text = next(m["content"] for m in msgs if m["role"] == "user")
    assert user_text.index("=== EVIDENCE") < user_text.index("RULE BASELINE")
    assert user_text.index("RULE BASELINE") < user_text.index("=== BULL ARGUMENT")
    assert user_text.index("=== BULL ARGUMENT") < user_text.index("=== BEAR ARGUMENT")


# ---------------------------------------------------------------------------
# Task 9: narrative + smart-money consensus tests
# ---------------------------------------------------------------------------


def test_evidence_includes_narrative_and_consensus(candidate, score):
    """NARRATIVE row must appear and smart-money consensus fields must be rendered."""
    snap = TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(available=True, rug_trust_score=90),
        holders=HolderInfo(available=True, top10_pct=25.0),
        momentum=MomentumInfo(available=True, liquidity_usd=50000.0, volume_5m=2000.0),
        social=SocialInfo(
            available=True,
            smart_money_distinct_wallets=2,
            smart_money_top_tier="S",
            smart_money_buyers=[WalletInfo(address="AAAAAA", label="kol", tier="S")],
            has_twitter=True,
            has_telegram=True,
            has_website=True,
            socials_count=3,
        ),
        narrative=NarrativeInfo(
            available=True,
            category="animal",
            matched_keywords=["dog"],
            meme_collision=["bonk"],
            summary="狗系 meme",
        ),
        enriched_at=candidate.pair_created_at,
    )
    msgs = judge_prompt(snap, score, "bull", "bear")
    text = msgs[-1]["content"]
    assert ("NARRATIVE" in text) or ("叙事" in text)
    assert "聪明钱" in text  # consensus fields surfaced


def test_evidence_narrative_missing_renders_data_missing(candidate, score):
    """When narrative is unavailable, the NARRATIVE row should show DATA MISSING."""
    snap = TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(available=True, rug_trust_score=80),
        holders=HolderInfo(available=True, top10_pct=20.0),
        momentum=MomentumInfo(available=True, liquidity_usd=30000.0),
        social=SocialInfo(available=False),
        narrative=NarrativeInfo(available=False),
        enriched_at=candidate.pair_created_at,
    )
    msgs = judge_prompt(snap, score, "b", "b")
    text = msgs[-1]["content"]
    assert ("NARRATIVE" in text) or ("叙事" in text)
    # Should show DATA MISSING since narrative is unavailable
    assert "DATA MISSING" in text.upper() or "缺失" in text
