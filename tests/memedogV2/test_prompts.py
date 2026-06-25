from memedogV2.audit.prompts import (
    evidence_text, analyst_prompt, judge_prompt, ANALYST_SCHEMA, JUDGE_SCHEMA,
)
from memedogV2.sources.base import Facts


def test_judge_schema_is_strict_and_detailed():
    assert JUDGE_SCHEMA["additionalProperties"] is False
    assert set(JUDGE_SCHEMA["required"]) == set(JUDGE_SCHEMA["properties"].keys())
    for k in ("recommended", "signal", "confidence", "summary",
              "strengths", "risks", "key_metrics"):
        assert k in JUDGE_SCHEMA["properties"]
    assert ANALYST_SCHEMA["additionalProperties"] is False


def test_evidence_text_groups_with_sources_and_missing():
    facts = Facts(mint_revoked=True, lp_safe=True, top10_rate=0.27,
                  liquidity_usd=57000, smart_money_count=52, dev_created_count=69)
    sources = {"mint_revoked": "rugcheck", "lp_safe": "rugcheck", "top10_rate": "rugcheck",
               "liquidity_usd": "gmgn", "smart_money_count": "gmgn", "dev_created_count": "gmgn"}
    txt = evidence_text(
        facts,
        sources,
        ["historical_ath"],
        stage="trending",
        source="gmgn_trending",
        hardfilter_flags=["momentum: buy/sell 0.9 < 1.0"],
    )
    assert "SAFETY:" in txt and "MOMENTUM:" in txt and "SMART_MONEY_DEV:" in txt
    assert "CONTEXT: stage=trending | discovery_source=gmgn_trending" in txt
    assert "mint_revoked=True (rugcheck)" in txt
    assert "liquidity_usd=57000.0 (gmgn)" in txt
    assert "dev_created_count=69 (gmgn)" in txt
    assert "HARD_FILTER_FLAGS: ['momentum: buy/sell 0.9 < 1.0']" in txt
    assert "MISSING: ['historical_ath']" in txt


def test_role_prompts_are_grounded():
    facts = Facts(liquidity_usd=57000)
    bp = analyst_prompt(
        "bull",
        facts,
        {"liquidity_usd": "gmgn"},
        [],
        stage="new_creation",
        hardfilter_flags=["authority: LP not burned/locked (stage_pending)"],
    )
    assert "BULL" in bp and "ONLY on the DATA" in bp
    assert "stage=new_creation" in bp
    assert "HARD_FILTER_FLAGS" in bp
    assert "BEAR" in analyst_prompt("bear", facts, {}, [])
    jp = judge_prompt(facts, {}, ["historical_ath"],
                      bull={"thesis": "x", "points": []}, bear={"thesis": "y", "points": []})
    assert "JUDGE" in jp
    for field in ("recommended", "summary", "strengths", "risks", "key_metrics"):
        assert field in jp
