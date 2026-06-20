"""Tests for scoring dimension functions (Task 1 - TDD: write tests first)."""
from __future__ import annotations

import pytest

from memedog.models import SafetyInfo, HolderInfo, MomentumInfo, SocialInfo
from memedog.config.settings import ScoringConfig, ScoringHoldersConfig, ScoringMomentumConfig, ScoringSocialConfig
from memedog.scoring.dimensions import (
    lerp_score,
    score_safety,
    score_holders,
    score_momentum,
    score_social,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def scoring_cfg() -> ScoringConfig:
    return ScoringConfig(
        weights={"safety": 0.35, "holders": 0.25, "momentum": 0.25, "social": 0.15},
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
        missing_dimension_weight_factor=0.5,
        neutral_score=50.0,
    )


# ---------------------------------------------------------------------------
# lerp_score tests
# ---------------------------------------------------------------------------

class TestLerpScore:
    """lerp_score(value, full_at, zero_at) -> float clamped to [0,100]."""

    def test_value_at_full_at_returns_100_higher_is_better(self):
        # liquidity: higher → better; full_at=100k, zero_at=0
        assert lerp_score(100_000, full_at=100_000, zero_at=0) == pytest.approx(100.0)

    def test_value_at_zero_at_returns_0_higher_is_better(self):
        assert lerp_score(0, full_at=100_000, zero_at=0) == pytest.approx(0.0)

    def test_midpoint_higher_is_better(self):
        result = lerp_score(50_000, full_at=100_000, zero_at=0)
        assert result == pytest.approx(50.0)

    def test_clamped_above_100_higher_is_better(self):
        # Value beyond full_at → clamped to 100
        result = lerp_score(200_000, full_at=100_000, zero_at=0)
        assert result == pytest.approx(100.0)

    def test_clamped_below_0_higher_is_better(self):
        # Value below zero_at → clamped to 0
        result = lerp_score(-5, full_at=100_000, zero_at=0)
        assert result == pytest.approx(0.0)

    def test_value_at_full_at_returns_100_lower_is_better(self):
        # top10: lower concentration → better; full_at=15, zero_at=50
        assert lerp_score(15, full_at=15, zero_at=50) == pytest.approx(100.0)

    def test_value_at_zero_at_returns_0_lower_is_better(self):
        assert lerp_score(50, full_at=15, zero_at=50) == pytest.approx(0.0)

    def test_midpoint_lower_is_better(self):
        # midpoint between 15 and 50 is 32.5 → should be 50
        result = lerp_score(32.5, full_at=15, zero_at=50)
        assert result == pytest.approx(50.0)

    def test_clamped_above_100_lower_is_better(self):
        # Value below full_at (even more concentrated is worse → clamp)
        # Actually for lower-is-better: value < full_at means better → clamp to 100
        result = lerp_score(5, full_at=15, zero_at=50)
        assert result == pytest.approx(100.0)

    def test_clamped_below_0_lower_is_better(self):
        # Value beyond zero_at (worse) → clamp to 0
        result = lerp_score(80, full_at=15, zero_at=50)
        assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# score_safety tests
# ---------------------------------------------------------------------------

class TestScoreSafety:
    """score_safety(info, cfg) returns DimensionScore with name='safety'."""

    def test_name_is_safety(self, scoring_cfg):
        info = SafetyInfo(available=True, rug_trust_score=80)
        ds = score_safety(info, scoring_cfg)
        assert ds.name == "safety"

    def test_unavailable_returns_neutral_with_note(self, scoring_cfg):
        info = SafetyInfo(available=False)
        ds = score_safety(info, scoring_cfg)
        assert ds.raw == pytest.approx(scoring_cfg.neutral_score)
        assert any("缺失" in n or "missing" in n.lower() for n in ds.notes)

    def test_good_rug_trust_score_gives_high_raw(self, scoring_cfg):
        info = SafetyInfo(available=True, rug_trust_score=90, rug_risk_level="LOW")
        ds = score_safety(info, scoring_cfg)
        assert ds.raw >= 70

    def test_critical_risk_level_caps_low(self, scoring_cfg):
        info = SafetyInfo(available=True, rug_trust_score=80, rug_risk_level="CRITICAL")
        ds = score_safety(info, scoring_cfg)
        assert ds.raw <= 20

    def test_high_risk_level_caps_low(self, scoring_cfg):
        info = SafetyInfo(available=True, rug_trust_score=75, rug_risk_level="HIGH")
        ds = score_safety(info, scoring_cfg)
        assert ds.raw <= 20

    def test_false_mint_authority_reduces_score(self, scoring_cfg):
        info_good = SafetyInfo(available=True, rug_trust_score=80, rug_risk_level="LOW",
                               mint_authority_revoked=True, freeze_authority_revoked=True,
                               lp_burned_or_locked=True)
        info_bad = SafetyInfo(available=True, rug_trust_score=80, rug_risk_level="LOW",
                              mint_authority_revoked=False)
        ds_good = score_safety(info_good, scoring_cfg)
        ds_bad = score_safety(info_bad, scoring_cfg)
        assert ds_bad.raw < ds_good.raw

    def test_false_freeze_authority_reduces_score(self, scoring_cfg):
        info_good = SafetyInfo(available=True, rug_trust_score=80, rug_risk_level="LOW",
                               freeze_authority_revoked=True)
        info_bad = SafetyInfo(available=True, rug_trust_score=80, rug_risk_level="LOW",
                              freeze_authority_revoked=False)
        ds_bad = score_safety(info_bad, scoring_cfg)
        ds_good = score_safety(info_good, scoring_cfg)
        assert ds_bad.raw < ds_good.raw

    def test_false_lp_burned_reduces_score(self, scoring_cfg):
        info_good = SafetyInfo(available=True, rug_trust_score=80, rug_risk_level="LOW",
                               lp_burned_or_locked=True)
        info_bad = SafetyInfo(available=True, rug_trust_score=80, rug_risk_level="LOW",
                              lp_burned_or_locked=False)
        ds_bad = score_safety(info_bad, scoring_cfg)
        ds_good = score_safety(info_good, scoring_cfg)
        assert ds_bad.raw < ds_good.raw

    def test_no_rug_trust_score_uses_neutral(self, scoring_cfg):
        info = SafetyInfo(available=True, rug_trust_score=None, rug_risk_level=None)
        ds = score_safety(info, scoring_cfg)
        # Should use neutral_score as base (50), so raw should be around 50
        assert 30 <= ds.raw <= 70


# ---------------------------------------------------------------------------
# score_holders tests
# ---------------------------------------------------------------------------

class TestScoreHolders:
    """score_holders(info, cfg) returns DimensionScore with name='holders'."""

    def test_name_is_holders(self, scoring_cfg):
        info = HolderInfo(available=True, top10_pct=20, max_wallet_pct=5)
        ds = score_holders(info, scoring_cfg)
        assert ds.name == "holders"

    def test_unavailable_returns_neutral_with_note(self, scoring_cfg):
        info = HolderInfo(available=False)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw == pytest.approx(scoring_cfg.neutral_score)
        assert any("缺失" in n or "missing" in n.lower() for n in ds.notes)

    def test_low_concentration_gives_high_raw(self, scoring_cfg):
        # top10=12 (below full_score_at=15) and max_wallet=3 → high score
        info = HolderInfo(available=True, top10_pct=12, max_wallet_pct=3)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw >= 80

    def test_high_concentration_gives_low_raw(self, scoring_cfg):
        # top10=50 (at zero_score_at=50) and max_wallet=25 (at max_wallet_zero_at=25)
        info = HolderInfo(available=True, top10_pct=50, max_wallet_pct=25)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw <= 25

    def test_all_none_metrics_returns_neutral_with_note(self, scoring_cfg):
        info = HolderInfo(available=True, top10_pct=None, max_wallet_pct=None)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw == pytest.approx(scoring_cfg.neutral_score)
        assert any("缺失" in n or "missing" in n.lower() for n in ds.notes)

    def test_only_top10_available_uses_top10_only(self, scoring_cfg):
        # top10=15 → lerp 100; max_wallet=None → skipped → raw=100
        info = HolderInfo(available=True, top10_pct=15, max_wallet_pct=None)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw == pytest.approx(100.0)

    def test_midpoint_top10(self, scoring_cfg):
        # top10=32.5 is midpoint between full_score_at=15 and zero_score_at=50 → 50
        info = HolderInfo(available=True, top10_pct=32.5, max_wallet_pct=None)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw == pytest.approx(50.0)

    def test_high_holder_count_boosts_score(self, scoring_cfg):
        """holder_count at full_at → sub-metric = 100; above-average score expected."""
        # holder_count=500 (== holder_count_full_at) → sub-metric=100
        # top10 and max_wallet are None so only holder_count contributes → raw=100
        info = HolderInfo(available=True, top10_pct=None, max_wallet_pct=None,
                          holder_count=500, sniper_pct=None)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw == pytest.approx(100.0)

    def test_zero_holder_count_gives_low_sub_score(self, scoring_cfg):
        """holder_count=0 → sub-metric=0; combined with other Nones → raw=0."""
        info = HolderInfo(available=True, top10_pct=None, max_wallet_pct=None,
                          holder_count=0, sniper_pct=None)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw == pytest.approx(0.0)

    def test_low_sniper_pct_boosts_score(self, scoring_cfg):
        """sniper_pct=0 → sub-metric=100 (best case)."""
        info = HolderInfo(available=True, top10_pct=None, max_wallet_pct=None,
                          holder_count=None, sniper_pct=0.0)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw == pytest.approx(100.0)

    def test_high_sniper_pct_gives_low_score(self, scoring_cfg):
        """sniper_pct at sniper_zero_at (30) → sub-metric=0."""
        info = HolderInfo(available=True, top10_pct=None, max_wallet_pct=None,
                          holder_count=None, sniper_pct=30.0)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw == pytest.approx(0.0)

    def test_all_four_metrics_averages_correctly(self, scoring_cfg):
        """All four sub-metrics present → raw is average of the four scores."""
        # top10=15 → 100, max_wallet=0 → 100, holder_count=500 → 100, sniper_pct=0 → 100
        info = HolderInfo(available=True, top10_pct=15.0, max_wallet_pct=0.0,
                          holder_count=500, sniper_pct=0.0)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw == pytest.approx(100.0)

    def test_only_sniper_pct_none_averages_remaining_three(self, scoring_cfg):
        """With sniper_pct=None, average is over the other three sub-metrics."""
        # top10=15 → 100, max_wallet=0 → 100, holder_count=500 → 100, sniper_pct=None (skipped)
        info = HolderInfo(available=True, top10_pct=15.0, max_wallet_pct=0.0,
                          holder_count=500, sniper_pct=None)
        ds = score_holders(info, scoring_cfg)
        assert ds.raw == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# score_momentum tests
# ---------------------------------------------------------------------------

class TestScoreMomentum:
    """score_momentum(info, cfg) returns DimensionScore with name='momentum'."""

    def test_name_is_momentum(self, scoring_cfg):
        info = MomentumInfo(available=True, liquidity_usd=50000, volume_5m=10000)
        ds = score_momentum(info, scoring_cfg)
        assert ds.name == "momentum"

    def test_unavailable_returns_neutral(self, scoring_cfg):
        info = MomentumInfo(available=False)
        ds = score_momentum(info, scoring_cfg)
        assert ds.raw == pytest.approx(scoring_cfg.neutral_score)

    def test_high_liquidity_and_volume_gives_high_raw(self, scoring_cfg):
        # At full_at values → each sub-metric = 100 → overall high
        info = MomentumInfo(available=True, liquidity_usd=100_000, volume_5m=20_000,
                            buy_sell_ratio_5m=2.0)
        ds = score_momentum(info, scoring_cfg)
        assert ds.raw >= 80

    def test_zero_liquidity_gives_low_raw(self, scoring_cfg):
        info = MomentumInfo(available=True, liquidity_usd=0, volume_5m=0)
        ds = score_momentum(info, scoring_cfg)
        assert ds.raw <= 20

    def test_bullish_buy_sell_ratio_boosts_score(self, scoring_cfg):
        info_neutral = MomentumInfo(available=True, liquidity_usd=50_000, volume_5m=10_000,
                                     buy_sell_ratio_5m=1.0)
        info_bullish = MomentumInfo(available=True, liquidity_usd=50_000, volume_5m=10_000,
                                     buy_sell_ratio_5m=3.0)
        ds_neutral = score_momentum(info_neutral, scoring_cfg)
        ds_bullish = score_momentum(info_bullish, scoring_cfg)
        assert ds_bullish.raw >= ds_neutral.raw

    def test_only_liquidity_available(self, scoring_cfg):
        info = MomentumInfo(available=True, liquidity_usd=100_000, volume_5m=None)
        ds = score_momentum(info, scoring_cfg)
        assert ds.raw == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# score_social tests
# ---------------------------------------------------------------------------

class TestScoreSocial:
    """score_social(info, cfg) returns DimensionScore with name='social'."""

    def test_name_is_social(self, scoring_cfg):
        info = SocialInfo(available=True, smart_money_buys=5)
        ds = score_social(info, scoring_cfg)
        assert ds.name == "social"

    def test_unavailable_returns_neutral(self, scoring_cfg):
        info = SocialInfo(available=False)
        ds = score_social(info, scoring_cfg)
        assert ds.raw == pytest.approx(scoring_cfg.neutral_score)

    def test_all_none_returns_neutral_with_note(self, scoring_cfg):
        info = SocialInfo(available=True, smart_money_buys=None, twitter_mentions_1h=None,
                          twitter_growth=None)
        ds = score_social(info, scoring_cfg)
        assert ds.raw == pytest.approx(scoring_cfg.neutral_score)
        assert any("缺失" in n or "missing" in n.lower() for n in ds.notes)

    def test_high_smart_money_and_positive_growth_gives_high_raw(self, scoring_cfg):
        info = SocialInfo(available=True, smart_money_buys=10, twitter_growth=2.0)
        ds = score_social(info, scoring_cfg)
        assert ds.raw >= 70

    def test_zero_smart_money_no_growth_gives_low_raw(self, scoring_cfg):
        info = SocialInfo(available=True, smart_money_buys=0, twitter_growth=0.0)
        ds = score_social(info, scoring_cfg)
        assert ds.raw <= 50

    def test_raw_capped_at_100(self, scoring_cfg):
        # Extremely high metrics should not exceed 100
        info = SocialInfo(available=True, smart_money_buys=1000, twitter_growth=100.0)
        ds = score_social(info, scoring_cfg)
        assert ds.raw <= 100.0

    def test_raw_not_below_0(self, scoring_cfg):
        info = SocialInfo(available=True, smart_money_buys=0, twitter_growth=-10.0)
        ds = score_social(info, scoring_cfg)
        assert ds.raw >= 0.0


# ---------------------------------------------------------------------------
# Fix 3: CRITICAL/HIGH risk always recorded in notes
# ---------------------------------------------------------------------------

class TestScoreSafetyRiskLevelNotes:
    """Fix 3: CRITICAL/HIGH rug_risk_level must always appear in notes,
    even when penalties have already pushed raw below the 20-point cap."""

    def test_critical_risk_in_notes_when_penalties_already_push_below_20(self, scoring_cfg):
        """Low trust + all authority flags False pushes raw below 20 before cap.
        Notes must still mention CRITICAL."""
        # trust_score=10 → raw=10; -15*3 (all flags False) → raw=-35, clamped to 0
        # Even without the cap, raw ≤ 20, so the old code skipped the note.
        info = SafetyInfo(
            available=True,
            rug_trust_score=10,
            rug_risk_level="CRITICAL",
            mint_authority_revoked=False,
            freeze_authority_revoked=False,
            lp_burned_or_locked=False,
        )
        ds = score_safety(info, scoring_cfg)
        assert ds.raw <= 20  # sanity: score is still capped/low
        assert any("CRITICAL" in n for n in ds.notes), (
            "Expected 'CRITICAL' risk level to appear in notes even when raw was already ≤ 20"
        )

    def test_high_risk_in_notes_when_penalties_already_push_below_20(self, scoring_cfg):
        """Same scenario with HIGH risk level."""
        info = SafetyInfo(
            available=True,
            rug_trust_score=5,
            rug_risk_level="HIGH",
            mint_authority_revoked=False,
            freeze_authority_revoked=False,
            lp_burned_or_locked=False,
        )
        ds = score_safety(info, scoring_cfg)
        assert ds.raw <= 20
        assert any("HIGH" in n for n in ds.notes), (
            "Expected 'HIGH' risk level to appear in notes even when raw was already ≤ 20"
        )

    def test_critical_risk_in_notes_when_raw_was_above_20(self, scoring_cfg):
        """When raw starts above 20 the cap note also mentions CRITICAL."""
        info = SafetyInfo(
            available=True,
            rug_trust_score=80,
            rug_risk_level="CRITICAL",
        )
        ds = score_safety(info, scoring_cfg)
        assert ds.raw <= 20
        assert any("CRITICAL" in n for n in ds.notes)

    def test_low_risk_level_not_in_notes(self, scoring_cfg):
        """LOW risk level must NOT produce a risk-level note."""
        info = SafetyInfo(
            available=True,
            rug_trust_score=80,
            rug_risk_level="LOW",
        )
        ds = score_safety(info, scoring_cfg)
        assert not any("rug_risk_level=LOW" in n for n in ds.notes)


# ---------------------------------------------------------------------------
# Fix 4: social thresholds are configurable
# ---------------------------------------------------------------------------

class TestScoreSocialConfigurableThresholds:
    """Fix 4: score_social must honour cfg.social.* instead of hardcoded values."""

    def test_smart_money_full_at_from_config(self, scoring_cfg):
        """With full_at=5, 5 smart buys should give a score of 100."""
        from memedog.config.settings import ScoringSocialConfig
        custom_cfg = ScoringConfig(
            weights=scoring_cfg.weights,
            holders=scoring_cfg.holders,
            momentum=scoring_cfg.momentum,
            social=ScoringSocialConfig(
                smart_money_full_at=5,      # lower threshold: 5 buys → 100
                twitter_growth_full_at=scoring_cfg.social.twitter_growth_full_at,
                twitter_growth_zero_at=scoring_cfg.social.twitter_growth_zero_at,
            ),
            missing_dimension_weight_factor=scoring_cfg.missing_dimension_weight_factor,
            neutral_score=scoring_cfg.neutral_score,
        )
        info = SocialInfo(available=True, smart_money_buys=5, twitter_growth=None)
        ds = score_social(info, custom_cfg)
        assert ds.raw == pytest.approx(100.0)

    def test_twitter_growth_thresholds_from_config(self, scoring_cfg):
        """With twitter_growth_full_at=1.0 and zero_at=0.0, growth=0.5 → 50."""
        from memedog.config.settings import ScoringSocialConfig
        custom_cfg = ScoringConfig(
            weights=scoring_cfg.weights,
            holders=scoring_cfg.holders,
            momentum=scoring_cfg.momentum,
            social=ScoringSocialConfig(
                smart_money_full_at=scoring_cfg.social.smart_money_full_at,
                twitter_growth_full_at=1.0,
                twitter_growth_zero_at=0.0,
            ),
            missing_dimension_weight_factor=scoring_cfg.missing_dimension_weight_factor,
            neutral_score=scoring_cfg.neutral_score,
        )
        info = SocialInfo(available=True, smart_money_buys=None, twitter_growth=0.5)
        ds = score_social(info, custom_cfg)
        assert ds.raw == pytest.approx(50.0)

    def test_default_thresholds_match_yaml(self, scoring_cfg):
        """The fixture's social config values must match thresholds.yaml."""
        import yaml
        from pathlib import Path
        yaml_path = (
            Path(__file__).resolve().parents[2]
            / "src" / "memedog" / "config" / "thresholds.yaml"
        )
        with yaml_path.open("r", encoding="utf-8") as fh:
            thresholds = yaml.safe_load(fh)
        yaml_social = thresholds["scoring"]["social"]
        assert scoring_cfg.social.smart_money_full_at == yaml_social["smart_money_full_at"]
        assert scoring_cfg.social.twitter_growth_full_at == yaml_social["twitter_growth_full_at"]
        assert scoring_cfg.social.twitter_growth_zero_at == yaml_social["twitter_growth_zero_at"]

    def test_loaded_config_social_block_matches_yaml(self):
        """load_config() must expose cfg.scoring.social backed by yaml values."""
        import yaml
        from pathlib import Path
        from memedog.config.settings import load_config, ScoringSocialConfig
        yaml_path = (
            Path(__file__).resolve().parents[2]
            / "src" / "memedog" / "config" / "thresholds.yaml"
        )
        with yaml_path.open("r", encoding="utf-8") as fh:
            thresholds = yaml.safe_load(fh)
        yaml_social = thresholds["scoring"]["social"]
        cfg = load_config()
        assert isinstance(cfg.scoring.social, ScoringSocialConfig)
        assert cfg.scoring.social.smart_money_full_at == yaml_social["smart_money_full_at"]
        assert cfg.scoring.social.twitter_growth_full_at == yaml_social["twitter_growth_full_at"]
        assert cfg.scoring.social.twitter_growth_zero_at == yaml_social["twitter_growth_zero_at"]


# ---------------------------------------------------------------------------
# Fix 5: dead clamp removed from score_momentum
# ---------------------------------------------------------------------------

class TestScoreMomentumNoDeadClamp:
    """Fix 5: score_momentum result must still be in [0,100]; no duplicate clamp."""

    def test_result_always_in_range_with_bonus_at_max(self, scoring_cfg):
        """Even when base avg=100 and bonus=10, result must be clamped to 100."""
        info = MomentumInfo(
            available=True,
            liquidity_usd=200_000,   # above full_at → lerp→100
            volume_5m=40_000,        # above full_at → lerp→100
            buy_sell_ratio_5m=5.0,   # bonus = min(10, (5-1)*10)=10 → raw=100, clamped to 100
        )
        ds = score_momentum(info, scoring_cfg)
        assert 0.0 <= ds.raw <= 100.0
        assert ds.raw == pytest.approx(100.0)

    def test_result_not_below_zero(self, scoring_cfg):
        """Zero metrics should never produce a negative raw score."""
        info = MomentumInfo(available=True, liquidity_usd=0.0, volume_5m=0.0,
                            buy_sell_ratio_5m=0.5)
        ds = score_momentum(info, scoring_cfg)
        assert ds.raw >= 0.0
