"""Task 1 — Tests for pure rule functions in memedog.hardfilter.rules.

RED phase: write failing tests first.
Each rule returns (bool, str) = (passed, reason).
"""
from __future__ import annotations

import pytest

from memedog.config.settings import (
    AuthorityFilterConfig,
    HoldersFilterConfig,
    MomentumFilterConfig,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mom_cfg() -> MomentumFilterConfig:
    return MomentumFilterConfig(
        min_liquidity_usd=20_000.0,
        min_volume_5m=1_000.0,
        min_buy_sell_ratio_5m=1.0,
        max_fdv_to_liquidity=50.0,
    )


@pytest.fixture
def auth_cfg() -> AuthorityFilterConfig:
    return AuthorityFilterConfig(
        require_mint_revoked=True,
        require_freeze_revoked=True,
        require_lp_burned_or_locked=True,
    )


@pytest.fixture
def holders_cfg() -> HoldersFilterConfig:
    return HoldersFilterConfig(
        max_top10_pct=35.0,
        max_single_wallet_pct=20.0,
        max_dev_pct=10.0,
        max_sniper_pct=30.0,
    )


# ---------------------------------------------------------------------------
# check_momentum — passing cases
# ---------------------------------------------------------------------------


class TestCheckMomentumPass:
    def test_all_above_thresholds_passes(self, mom_cfg):
        from memedog.hardfilter.rules import check_momentum

        passed, reason = check_momentum(
            liquidity_usd=25_000.0,
            volume_5m=2_000.0,
            txns_5m_buys=10,
            txns_5m_sells=5,
            fdv_usd=500_000.0,
            cfg=mom_cfg,
        )
        assert passed is True
        assert reason == ""

    def test_exact_boundary_values_pass(self, mom_cfg):
        """Exact boundary: liq == min, vol == min, ratio == 1.0, fdv_ratio == max."""
        from memedog.hardfilter.rules import check_momentum

        passed, reason = check_momentum(
            liquidity_usd=20_000.0,
            volume_5m=1_000.0,
            txns_5m_buys=1,
            txns_5m_sells=1,  # ratio = 1/1 = 1.0
            fdv_usd=1_000_000.0,  # fdv/liq = 50 == max
            cfg=mom_cfg,
        )
        assert passed is True


# ---------------------------------------------------------------------------
# check_momentum — failing cases
# ---------------------------------------------------------------------------


class TestCheckMomentumFail:
    def test_low_liquidity_fails_with_reason(self, mom_cfg):
        from memedog.hardfilter.rules import check_momentum

        passed, reason = check_momentum(
            liquidity_usd=5_000.0,
            volume_5m=2_000.0,
            txns_5m_buys=10,
            txns_5m_sells=5,
            fdv_usd=100_000.0,
            cfg=mom_cfg,
        )
        assert passed is False
        assert "liquidity" in reason.lower()
        assert "5000" in reason or "5,000" in reason or "5000.0" in reason

    def test_low_volume_fails_with_reason(self, mom_cfg):
        from memedog.hardfilter.rules import check_momentum

        passed, reason = check_momentum(
            liquidity_usd=25_000.0,
            volume_5m=500.0,
            txns_5m_buys=10,
            txns_5m_sells=5,
            fdv_usd=100_000.0,
            cfg=mom_cfg,
        )
        assert passed is False
        assert "volume" in reason.lower()

    def test_low_buy_sell_ratio_fails_with_reason(self, mom_cfg):
        from memedog.hardfilter.rules import check_momentum

        passed, reason = check_momentum(
            liquidity_usd=25_000.0,
            volume_5m=2_000.0,
            txns_5m_buys=3,
            txns_5m_sells=10,
            fdv_usd=100_000.0,
            cfg=mom_cfg,
        )
        assert passed is False
        assert "ratio" in reason.lower() or "buy" in reason.lower()

    def test_high_fdv_ratio_fails_with_reason(self, mom_cfg):
        from memedog.hardfilter.rules import check_momentum

        passed, reason = check_momentum(
            liquidity_usd=20_000.0,
            volume_5m=2_000.0,
            txns_5m_buys=10,
            txns_5m_sells=5,
            fdv_usd=2_000_000.0,  # fdv/liq = 100 > 50
            cfg=mom_cfg,
        )
        assert passed is False
        assert "fdv" in reason.lower()

    def test_zero_sells_does_not_divide_by_zero(self, mom_cfg):
        """txns_5m_sells=0 should not raise ZeroDivisionError."""
        from memedog.hardfilter.rules import check_momentum

        passed, reason = check_momentum(
            liquidity_usd=25_000.0,
            volume_5m=2_000.0,
            txns_5m_buys=10,
            txns_5m_sells=0,
            fdv_usd=100_000.0,
            cfg=mom_cfg,
        )
        # With 0 sells denominator is 1 (max(0,1)=1), so ratio=10, passes
        assert passed is True

    def test_low_liquidity_fails_first_before_volume(self, mom_cfg):
        """When both liquidity and volume fail, liquidity reason comes first."""
        from memedog.hardfilter.rules import check_momentum

        passed, reason = check_momentum(
            liquidity_usd=5_000.0,
            volume_5m=100.0,
            txns_5m_buys=1,
            txns_5m_sells=10,
            fdv_usd=1_000_000_000.0,
            cfg=mom_cfg,
        )
        assert passed is False
        assert "liquidity" in reason.lower()


# ---------------------------------------------------------------------------
# check_authorities — passing cases
# ---------------------------------------------------------------------------


class TestCheckAuthoritiesPass:
    def test_all_revoked_passes_when_all_required(self, auth_cfg):
        from memedog.hardfilter.rules import check_authorities

        passed, reason = check_authorities(
            mint_revoked=True,
            freeze_revoked=True,
            lp_locked=True,
            cfg=auth_cfg,
        )
        assert passed is True
        assert reason == ""

    def test_not_required_flag_ignored(self):
        """When require_* is False, corresponding fact is irrelevant."""
        from memedog.hardfilter.rules import check_authorities

        cfg = AuthorityFilterConfig(
            require_mint_revoked=False,
            require_freeze_revoked=False,
            require_lp_burned_or_locked=False,
        )
        passed, reason = check_authorities(
            mint_revoked=False,
            freeze_revoked=False,
            lp_locked=False,
            cfg=cfg,
        )
        assert passed is True


# ---------------------------------------------------------------------------
# check_authorities — failing cases
# ---------------------------------------------------------------------------


class TestCheckAuthoritiesFail:
    def test_mint_not_revoked_fails(self, auth_cfg):
        from memedog.hardfilter.rules import check_authorities

        passed, reason = check_authorities(
            mint_revoked=False,
            freeze_revoked=True,
            lp_locked=True,
            cfg=auth_cfg,
        )
        assert passed is False
        assert "mint" in reason.lower()

    def test_freeze_not_revoked_fails(self, auth_cfg):
        from memedog.hardfilter.rules import check_authorities

        passed, reason = check_authorities(
            mint_revoked=True,
            freeze_revoked=False,
            lp_locked=True,
            cfg=auth_cfg,
        )
        assert passed is False
        assert "freeze" in reason.lower()

    def test_lp_not_locked_fails(self, auth_cfg):
        from memedog.hardfilter.rules import check_authorities

        passed, reason = check_authorities(
            mint_revoked=True,
            freeze_revoked=True,
            lp_locked=False,
            cfg=auth_cfg,
        )
        assert passed is False
        assert "lp" in reason.lower()

    def test_none_mint_revoked_treated_as_fail(self, auth_cfg):
        """None (unknown) counts as not-satisfied → fail."""
        from memedog.hardfilter.rules import check_authorities

        passed, reason = check_authorities(
            mint_revoked=None,
            freeze_revoked=True,
            lp_locked=True,
            cfg=auth_cfg,
        )
        assert passed is False
        assert "mint" in reason.lower()

    def test_none_freeze_revoked_treated_as_fail(self, auth_cfg):
        from memedog.hardfilter.rules import check_authorities

        passed, reason = check_authorities(
            mint_revoked=True,
            freeze_revoked=None,
            lp_locked=True,
            cfg=auth_cfg,
        )
        assert passed is False
        assert "freeze" in reason.lower()

    def test_none_lp_locked_treated_as_fail(self, auth_cfg):
        from memedog.hardfilter.rules import check_authorities

        passed, reason = check_authorities(
            mint_revoked=True,
            freeze_revoked=True,
            lp_locked=None,
            cfg=auth_cfg,
        )
        assert passed is False
        assert "lp" in reason.lower()


# ---------------------------------------------------------------------------
# check_holders — passing cases
# ---------------------------------------------------------------------------


class TestCheckHoldersPass:
    def test_all_within_thresholds_passes(self, holders_cfg):
        from memedog.hardfilter.rules import check_holders

        passed, reason = check_holders(
            top10_pct=30.0,
            max_wallet_pct=15.0,
            dev_pct=5.0,
            sniper_pct=20.0,
            cfg=holders_cfg,
        )
        assert passed is True
        assert reason == ""

    def test_exact_boundary_top10_passes(self, holders_cfg):
        """top10_pct == max_top10_pct should pass (<=)."""
        from memedog.hardfilter.rules import check_holders

        passed, reason = check_holders(
            top10_pct=35.0,
            max_wallet_pct=15.0,
            dev_pct=5.0,
            sniper_pct=20.0,
            cfg=holders_cfg,
        )
        assert passed is True


# ---------------------------------------------------------------------------
# check_holders — failing cases
# ---------------------------------------------------------------------------


class TestCheckHoldersFail:
    def test_top10_over_max_fails(self, holders_cfg):
        from memedog.hardfilter.rules import check_holders

        passed, reason = check_holders(
            top10_pct=40.0,
            max_wallet_pct=15.0,
            dev_pct=5.0,
            sniper_pct=20.0,
            cfg=holders_cfg,
        )
        assert passed is False
        assert "top10" in reason.lower() or "top_10" in reason.lower() or "top 10" in reason.lower()

    def test_single_wallet_at_or_over_max_fails(self, holders_cfg):
        """max_wallet_pct >= max_single_wallet_pct → fail (strict <)."""
        from memedog.hardfilter.rules import check_holders

        passed, reason = check_holders(
            top10_pct=30.0,
            max_wallet_pct=20.0,  # equal to max → fail (strict <)
            dev_pct=5.0,
            sniper_pct=20.0,
            cfg=holders_cfg,
        )
        assert passed is False
        assert "wallet" in reason.lower() or "single" in reason.lower()

    def test_dev_pct_at_or_over_max_fails(self, holders_cfg):
        from memedog.hardfilter.rules import check_holders

        passed, reason = check_holders(
            top10_pct=30.0,
            max_wallet_pct=15.0,
            dev_pct=10.0,  # equal to max → fail (strict <)
            sniper_pct=20.0,
            cfg=holders_cfg,
        )
        assert passed is False
        assert "dev" in reason.lower()

    def test_sniper_pct_at_or_over_max_fails(self, holders_cfg):
        from memedog.hardfilter.rules import check_holders

        passed, reason = check_holders(
            top10_pct=30.0,
            max_wallet_pct=15.0,
            dev_pct=5.0,
            sniper_pct=30.0,  # equal to max → fail (strict <)
            cfg=holders_cfg,
        )
        assert passed is False
        assert "sniper" in reason.lower()

    def test_none_top10_pct_fails(self, holders_cfg):
        """None value → can't verify → fail."""
        from memedog.hardfilter.rules import check_holders

        passed, reason = check_holders(
            top10_pct=None,
            max_wallet_pct=15.0,
            dev_pct=5.0,
            sniper_pct=20.0,
            cfg=holders_cfg,
        )
        assert passed is False
        assert "top10" in reason.lower() or "top_10" in reason.lower() or "top 10" in reason.lower() or "unknown" in reason.lower()

    def test_none_dev_pct_fails(self, holders_cfg):
        from memedog.hardfilter.rules import check_holders

        passed, reason = check_holders(
            top10_pct=30.0,
            max_wallet_pct=15.0,
            dev_pct=None,
            sniper_pct=20.0,
            cfg=holders_cfg,
        )
        assert passed is False
