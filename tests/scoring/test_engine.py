"""Tests for ScoreEngine (Task 2 - TDD: write tests first)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memedog.models import (
    TokenSnapshot,
    SafetyInfo,
    HolderInfo,
    MomentumInfo,
    SocialInfo,
    Score,
)
from memedog.models.candidate import TokenCandidate
from memedog.config.settings import (
    ScoringConfig,
    ScoringHoldersConfig,
    ScoringMomentumConfig,
    ScoringSocialConfig,
    ScoringNarrativeConfig,
)
from memedog.scoring.engine import ScoreEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def scoring_cfg() -> ScoringConfig:
    return ScoringConfig(
        weights={"safety": 0.30, "holders": 0.25, "momentum": 0.30, "social": 0.10, "narrative": 0.05},
        holders=ScoringHoldersConfig(
            top10_full_score_at=15,
            top10_zero_score_at=50,
            max_wallet_zero_at=25,
            holder_count_full_at=500,
            sniper_zero_at=30,
        ),
        momentum=ScoringMomentumConfig(
            liquidity_full_at=100_000,
            volume_5m_full_at=20_000,
        ),
        social=ScoringSocialConfig(
            smart_money_full_at=10,
            twitter_growth_full_at=2.0,
            twitter_growth_zero_at=-1.0,
        ),
        narrative=ScoringNarrativeConfig(
            category_scores={"animal": 70, "ai": 65, "political": 60, "culture": 55, "finance_utility": 35, "unknown": 40},
            meme_collision_bonus=10,
        ),
        missing_dimension_weight_factor=0.5,
        neutral_score=50.0,
    )


@pytest.fixture
def engine(scoring_cfg) -> ScoreEngine:
    return ScoreEngine(scoring_cfg)


def _make_candidate(mint: str = "MINT123", trace_id: str = "TRACE-001") -> TokenCandidate:
    return TokenCandidate(
        mint=mint,
        pair_address="PAIR001",
        symbol="TEST",
        chain="solana",
        pair_created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        price_usd=0.001,
        liquidity_usd=50_000.0,
        fdv_usd=500_000.0,
        volume_5m=5_000.0,
        volume_1h=30_000.0,
        txns_5m_buys=50,
        txns_5m_sells=20,
        price_change_5m=0.05,
        trace_id=trace_id,
    )


def _make_full_snapshot(mint: str = "MINT123", trace_id: str = "TRACE-001") -> TokenSnapshot:
    """All dimensions available with moderate metrics."""
    return TokenSnapshot(
        candidate=_make_candidate(mint=mint, trace_id=trace_id),
        safety=SafetyInfo(
            available=True,
            rug_trust_score=75,
            rug_risk_level="LOW",
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            lp_burned_or_locked=True,
        ),
        holders=HolderInfo(
            available=True,
            top10_pct=20,
            max_wallet_pct=5,
        ),
        momentum=MomentumInfo(
            available=True,
            liquidity_usd=50_000,
            volume_5m=10_000,
            buy_sell_ratio_5m=1.5,
        ),
        social=SocialInfo(
            available=True,
            smart_money_buys=5,
            twitter_growth=1.0,
        ),
        enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Engine construction
# ---------------------------------------------------------------------------

class TestScoreEngineConstruction:
    def test_constructs_with_scoring_cfg(self, scoring_cfg):
        engine = ScoreEngine(scoring_cfg)
        assert engine is not None


# ---------------------------------------------------------------------------
# Full snapshot scoring
# ---------------------------------------------------------------------------

class TestScoreEngineFull:
    """All dimensions available."""

    def test_returns_score_object(self, engine):
        snapshot = _make_full_snapshot()
        result = engine.score(snapshot)
        assert isinstance(result, Score)

    def test_mint_matches_candidate(self, engine):
        snapshot = _make_full_snapshot(mint="SOLMINT99")
        result = engine.score(snapshot)
        assert result.mint == "SOLMINT99"

    def test_trace_id_matches_candidate(self, engine):
        snapshot = _make_full_snapshot(trace_id="TRACE-XYZ")
        result = engine.score(snapshot)
        assert result.trace_id == "TRACE-XYZ"

    def test_total_in_valid_range(self, engine):
        snapshot = _make_full_snapshot()
        result = engine.score(snapshot)
        assert 0.0 <= result.total <= 100.0

    def test_exactly_five_dimensions(self, engine):
        snapshot = _make_full_snapshot()
        result = engine.score(snapshot)
        assert len(result.dimensions) == 5

    def test_dimension_names_are_correct_set(self, engine):
        snapshot = _make_full_snapshot()
        result = engine.score(snapshot)
        names = {d.name for d in result.dimensions}
        assert names == {"safety", "holders", "momentum", "social", "narrative"}

    def test_weights_sum_to_one_all_available(self, engine):
        snapshot = _make_full_snapshot()
        result = engine.score(snapshot)
        total_weight = sum(d.weight for d in result.dimensions)
        assert total_weight == pytest.approx(1.0, abs=1e-9)

    def test_weighted_equals_raw_times_weight(self, engine):
        snapshot = _make_full_snapshot()
        result = engine.score(snapshot)
        for d in result.dimensions:
            assert d.weighted == pytest.approx(d.raw * d.weight)

    def test_total_equals_sum_of_weighted(self, engine):
        snapshot = _make_full_snapshot()
        result = engine.score(snapshot)
        assert result.total == pytest.approx(sum(d.weighted for d in result.dimensions))


# ---------------------------------------------------------------------------
# Missing dimension (social unavailable)
# ---------------------------------------------------------------------------

class TestScoreEngineMissingDimension:
    """One dimension marked unavailable → weight renormalized."""

    def _snapshot_social_unavailable(self) -> TokenSnapshot:
        return TokenSnapshot(
            candidate=_make_candidate(),
            safety=SafetyInfo(available=True, rug_trust_score=80, rug_risk_level="LOW"),
            holders=HolderInfo(available=True, top10_pct=20, max_wallet_pct=5),
            momentum=MomentumInfo(available=True, liquidity_usd=60_000, volume_5m=12_000),
            social=SocialInfo(available=False),
            enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

    def test_total_still_in_range(self, engine):
        result = engine.score(self._snapshot_social_unavailable())
        assert 0.0 <= result.total <= 100.0

    def test_weights_renormalize_to_one(self, engine):
        result = engine.score(self._snapshot_social_unavailable())
        total_weight = sum(d.weight for d in result.dimensions)
        assert total_weight == pytest.approx(1.0, abs=1e-9)

    def test_social_dimension_present_with_reduced_weight(self, engine, scoring_cfg):
        result = engine.score(self._snapshot_social_unavailable())
        social = next(d for d in result.dimensions if d.name == "social")
        # Social's effective weight before renorm = 0.15 * 0.5 = 0.075
        # Total raw weight sum = 0.35 + 0.25 + 0.25 + 0.075 = 0.925
        # Renormalized social weight = 0.075 / 0.925 ≈ 0.0811
        # So its weight should be less than the original 0.15
        assert social.weight < scoring_cfg.weights["social"]

    def test_social_raw_equals_neutral_when_unavailable(self, engine, scoring_cfg):
        result = engine.score(self._snapshot_social_unavailable())
        social = next(d for d in result.dimensions if d.name == "social")
        assert social.raw == pytest.approx(scoring_cfg.neutral_score)

    def test_five_dimensions_still_returned(self, engine):
        result = engine.score(self._snapshot_social_unavailable())
        assert len(result.dimensions) == 5


# ---------------------------------------------------------------------------
# High/low scoring scenarios
# ---------------------------------------------------------------------------

class TestScoreEngineEdgeCases:
    """Verify extreme cases stay in range and relative ordering holds."""

    def test_ideal_token_scores_high(self, engine):
        snapshot = TokenSnapshot(
            candidate=_make_candidate(),
            safety=SafetyInfo(available=True, rug_trust_score=98, rug_risk_level="LOW",
                              mint_authority_revoked=True, freeze_authority_revoked=True,
                              lp_burned_or_locked=True),
            holders=HolderInfo(available=True, top10_pct=10, max_wallet_pct=2),
            momentum=MomentumInfo(available=True, liquidity_usd=200_000, volume_5m=30_000,
                                   buy_sell_ratio_5m=3.0),
            social=SocialInfo(available=True, smart_money_buys=10, twitter_growth=2.0),
            enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        result = engine.score(snapshot)
        assert result.total >= 80

    def test_risky_token_scores_low(self, engine):
        snapshot = TokenSnapshot(
            candidate=_make_candidate(),
            safety=SafetyInfo(available=True, rug_trust_score=10, rug_risk_level="CRITICAL"),
            holders=HolderInfo(available=True, top10_pct=60, max_wallet_pct=30),
            momentum=MomentumInfo(available=True, liquidity_usd=100, volume_5m=50),
            social=SocialInfo(available=True, smart_money_buys=0, twitter_growth=-1.0),
            enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        result = engine.score(snapshot)
        assert result.total <= 25

    def test_high_safety_low_momentum_total_between_them(self, engine):
        """Total should be between the two extremes when dims differ."""
        snapshot = TokenSnapshot(
            candidate=_make_candidate(),
            safety=SafetyInfo(available=True, rug_trust_score=95, rug_risk_level="LOW",
                              mint_authority_revoked=True, freeze_authority_revoked=True,
                              lp_burned_or_locked=True),
            holders=HolderInfo(available=True, top10_pct=20, max_wallet_pct=5),
            momentum=MomentumInfo(available=True, liquidity_usd=0, volume_5m=0),
            social=SocialInfo(available=True, smart_money_buys=0, twitter_growth=0.0),
            enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        result = engine.score(snapshot)
        safety_dim = next(d for d in result.dimensions if d.name == "safety")
        momentum_dim = next(d for d in result.dimensions if d.name == "momentum")
        # Total must lie between min and max of dimension raws
        assert momentum_dim.raw < result.total < safety_dim.raw

    def test_all_dimensions_unavailable_total_equals_neutral(self, engine, scoring_cfg):
        """When every dimension is unavailable, total should equal neutral_score."""
        from memedog.models import NarrativeInfo
        snapshot = TokenSnapshot(
            candidate=_make_candidate(),
            safety=SafetyInfo(available=False),
            holders=HolderInfo(available=False),
            momentum=MomentumInfo(available=False),
            social=SocialInfo(available=False),
            narrative=NarrativeInfo(available=False),
            enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        result = engine.score(snapshot)
        # All raws = neutral_score=50; weights renormalize uniformly → total = 50
        assert result.total == pytest.approx(scoring_cfg.neutral_score, abs=0.001)
        assert sum(d.weight for d in result.dimensions) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Fix 1: division-by-zero guard in renormalization
# ---------------------------------------------------------------------------

class TestScoreEngineDivisionByZeroGuard:
    """Fix 1: when total effective weight == 0, engine must NOT raise ZeroDivisionError."""

    def test_all_dims_unavailable_factor_zero_no_exception(self, scoring_cfg):
        """All dims unavailable + missing_dimension_weight_factor=0 → no crash."""
        zero_factor_cfg = ScoringConfig(
            weights=scoring_cfg.weights,
            holders=scoring_cfg.holders,
            momentum=scoring_cfg.momentum,
            social=scoring_cfg.social,
            narrative=scoring_cfg.narrative,
            missing_dimension_weight_factor=0.0,  # kills all effective weights
            neutral_score=scoring_cfg.neutral_score,
        )
        engine = ScoreEngine(zero_factor_cfg)
        snapshot = TokenSnapshot(
            candidate=_make_candidate(),
            safety=SafetyInfo(available=False),
            holders=HolderInfo(available=False),
            momentum=MomentumInfo(available=False),
            social=SocialInfo(available=False),
            enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        # Must not raise ZeroDivisionError
        result = engine.score(snapshot)
        assert isinstance(result, Score)

    def test_all_dims_unavailable_factor_zero_total_in_valid_range(self, scoring_cfg):
        """Total score must be in [0, 100] when fallback equal-weights are used."""
        zero_factor_cfg = ScoringConfig(
            weights=scoring_cfg.weights,
            holders=scoring_cfg.holders,
            momentum=scoring_cfg.momentum,
            social=scoring_cfg.social,
            narrative=scoring_cfg.narrative,
            missing_dimension_weight_factor=0.0,
            neutral_score=scoring_cfg.neutral_score,
        )
        engine = ScoreEngine(zero_factor_cfg)
        snapshot = TokenSnapshot(
            candidate=_make_candidate(),
            safety=SafetyInfo(available=False),
            holders=HolderInfo(available=False),
            momentum=MomentumInfo(available=False),
            social=SocialInfo(available=False),
            enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        result = engine.score(snapshot)
        assert 0.0 <= result.total <= 100.0

    def test_all_dims_unavailable_factor_zero_weights_sum_to_one(self, scoring_cfg):
        """Fallback equal weights must still sum to 1.0."""
        zero_factor_cfg = ScoringConfig(
            weights=scoring_cfg.weights,
            holders=scoring_cfg.holders,
            momentum=scoring_cfg.momentum,
            social=scoring_cfg.social,
            narrative=scoring_cfg.narrative,
            missing_dimension_weight_factor=0.0,
            neutral_score=scoring_cfg.neutral_score,
        )
        engine = ScoreEngine(zero_factor_cfg)
        snapshot = TokenSnapshot(
            candidate=_make_candidate(),
            safety=SafetyInfo(available=False),
            holders=HolderInfo(available=False),
            momentum=MomentumInfo(available=False),
            social=SocialInfo(available=False),
            enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        result = engine.score(snapshot)
        assert sum(d.weight for d in result.dimensions) == pytest.approx(1.0, abs=1e-9)

    def test_all_dims_unavailable_factor_zero_equal_weights(self, scoring_cfg):
        """Fallback must assign equal weight 0.20 to each of the 5 dimensions."""
        from memedog.models import NarrativeInfo
        zero_factor_cfg = ScoringConfig(
            weights=scoring_cfg.weights,
            holders=scoring_cfg.holders,
            momentum=scoring_cfg.momentum,
            social=scoring_cfg.social,
            narrative=scoring_cfg.narrative,
            missing_dimension_weight_factor=0.0,
            neutral_score=scoring_cfg.neutral_score,
        )
        engine = ScoreEngine(zero_factor_cfg)
        snapshot = TokenSnapshot(
            candidate=_make_candidate(),
            safety=SafetyInfo(available=False),
            holders=HolderInfo(available=False),
            momentum=MomentumInfo(available=False),
            social=SocialInfo(available=False),
            narrative=NarrativeInfo(available=False),
            enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        result = engine.score(snapshot)
        for d in result.dimensions:
            assert d.weight == pytest.approx(0.20, abs=1e-9)


# ---------------------------------------------------------------------------
# Fix 2: validate weights keys at construction
# ---------------------------------------------------------------------------

class TestScoreEngineWeightsValidation:
    """Fix 2: ScoreEngine.__init__ must raise ValueError for missing weight keys."""

    def test_missing_one_key_raises_value_error(self, scoring_cfg):
        """Omitting 'social' from weights must raise ValueError at construction."""
        bad_cfg = ScoringConfig(
            weights={"safety": 0.40, "holders": 0.30, "momentum": 0.25, "narrative": 0.05},  # missing social
            holders=scoring_cfg.holders,
            momentum=scoring_cfg.momentum,
            social=scoring_cfg.social,
            narrative=scoring_cfg.narrative,
            missing_dimension_weight_factor=scoring_cfg.missing_dimension_weight_factor,
            neutral_score=scoring_cfg.neutral_score,
        )
        with pytest.raises(ValueError, match="cfg.weights missing keys"):
            ScoreEngine(bad_cfg)

    def test_missing_multiple_keys_raises_value_error(self, scoring_cfg):
        """Omitting multiple keys must also raise ValueError."""
        bad_cfg = ScoringConfig(
            weights={"safety": 1.0},  # missing holders, momentum, social, narrative
            holders=scoring_cfg.holders,
            momentum=scoring_cfg.momentum,
            social=scoring_cfg.social,
            narrative=scoring_cfg.narrative,
            missing_dimension_weight_factor=scoring_cfg.missing_dimension_weight_factor,
            neutral_score=scoring_cfg.neutral_score,
        )
        with pytest.raises(ValueError, match="cfg.weights missing keys"):
            ScoreEngine(bad_cfg)

    def test_extra_keys_allowed_no_error(self, scoring_cfg):
        """Extra keys beyond the required five must not raise."""
        extra_cfg = ScoringConfig(
            weights={
                "safety": 0.28, "holders": 0.25, "momentum": 0.28, "social": 0.10,
                "narrative": 0.05, "extra_dim": 0.04,
            },
            holders=scoring_cfg.holders,
            momentum=scoring_cfg.momentum,
            social=scoring_cfg.social,
            narrative=scoring_cfg.narrative,
            missing_dimension_weight_factor=scoring_cfg.missing_dimension_weight_factor,
            neutral_score=scoring_cfg.neutral_score,
        )
        # Should not raise
        engine = ScoreEngine(extra_cfg)
        assert engine is not None

    def test_all_five_keys_present_no_error(self, scoring_cfg):
        """Exact required five keys must not raise."""
        engine = ScoreEngine(scoring_cfg)
        assert engine is not None


# ---------------------------------------------------------------------------
# Task 8: narrative dimension in engine
# ---------------------------------------------------------------------------

def test_engine_includes_narrative_dimension(scoring_cfg):
    from memedog.scoring.engine import ScoreEngine
    from memedog.models import TokenSnapshot, NarrativeInfo
    snap = _make_full_snapshot()
    # snapshot.narrative defaults to NarrativeInfo() with category=None
    score = ScoreEngine(scoring_cfg).score(snap)
    names = {d.name for d in score.dimensions}
    assert "narrative" in names and len(score.dimensions) == 5
