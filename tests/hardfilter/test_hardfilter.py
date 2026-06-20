"""Task 3 — Tests for HardFilter aggregator.

RED phase: write failing tests first.
Uses fake rugcheck object (no real network) and fake TokenCandidate instances.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memedog.clients.base import DataSourceError
from memedog.config.settings import (
    AuthorityFilterConfig,
    HardFilterConfig,
    HoldersFilterConfig,
    MomentumFilterConfig,
)
from memedog.models import TokenCandidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_candidate(
    mint: str = "MINT_GOOD",
    symbol: str = "GOOD",
    liquidity_usd: float = 25_000.0,
    volume_5m: float = 2_000.0,
    txns_5m_buys: int = 10,
    txns_5m_sells: int = 5,
    fdv_usd: float = 500_000.0,
) -> TokenCandidate:
    return TokenCandidate(
        mint=mint,
        pair_address=f"PAIR_{mint}",
        symbol=symbol,
        chain="solana",
        pair_created_at=datetime.now(tz=timezone.utc),
        price_usd=0.001,
        liquidity_usd=liquidity_usd,
        fdv_usd=fdv_usd,
        volume_5m=volume_5m,
        volume_1h=10_000.0,
        txns_5m_buys=txns_5m_buys,
        txns_5m_sells=txns_5m_sells,
        price_change_5m=2.5,
        trace_id=f"trace_{mint}",
    )


def make_hard_filter_cfg(on_rugcheck_failure: str = "drop") -> HardFilterConfig:
    return HardFilterConfig(
        authority=AuthorityFilterConfig(
            require_mint_revoked=True,
            require_freeze_revoked=True,
            require_lp_burned_or_locked=True,
        ),
        holders=HoldersFilterConfig(
            max_top10_pct=35.0,
            max_single_wallet_pct=20.0,
            max_dev_pct=10.0,
            max_sniper_pct=30.0,
        ),
        momentum=MomentumFilterConfig(
            min_liquidity_usd=20_000.0,
            min_volume_5m=1_000.0,
            min_buy_sell_ratio_5m=1.0,
            max_fdv_to_liquidity=50.0,
        ),
        on_rugcheck_failure=on_rugcheck_failure,
    )


def make_clean_rugcheck_report() -> dict:
    """Return a parsed RugCheck report with all flags green."""
    return {
        "mint_authority_revoked": True,
        "freeze_authority_revoked": True,
        "lp_burned_or_locked": True,
        "top10_pct": 25.0,
        "max_wallet_pct": 10.0,
        "dev_pct": 4.0,
        "sniper_pct": 15.0,
        "trust_score": 90,
        "risk_level": "low",
    }


class FakeRugCheck:
    """Fake rugcheck client that returns pre-configured reports."""

    def __init__(self, reports: dict[str, dict] | None = None, error: Exception | None = None):
        """
        reports: mint → parsed_report dict (already normalised)
        error: if set, raise this exception for every call
        """
        self._reports = reports or {}
        self._error = error
        self.call_count = 0
        self.called_mints: list[str] = []

    async def get_token_report(self, mint: str) -> dict:
        self.call_count += 1
        self.called_mints.append(mint)
        if self._error is not None:
            raise self._error
        return self._reports.get(mint, {})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg() -> HardFilterConfig:
    return make_hard_filter_cfg(on_rugcheck_failure="drop")


@pytest.fixture
def cfg_pass_flagged() -> HardFilterConfig:
    return make_hard_filter_cfg(on_rugcheck_failure="pass_flagged")


# ---------------------------------------------------------------------------
# Task 3: HardFilter.apply tests
# ---------------------------------------------------------------------------


class TestHardFilterCleanCandidate:
    async def test_clean_candidate_is_kept(self, cfg):
        """A candidate that passes momentum + clean rugcheck report must survive."""
        from memedog.hardfilter.hardfilter import HardFilter
        from memedog.clients.rugcheck import parse_report

        candidate = make_candidate(mint="GOOD_MINT")
        raw_report = {
            "mintAuthority": None,
            "freezeAuthority": None,
            "markets": [{"lpBurned": True, "lpLocked": False}],
            "topHolders": [{"pct": 2.5}] * 10,
            "largestWalletPct": 10.0,
            "insiders": {"devPct": 4.0, "sniperPct": 15.0},
            "score": 90,
            "riskLevel": "low",
        }
        fake_rc = FakeRugCheck(reports={"GOOD_MINT": raw_report})

        hf = HardFilter(rugcheck=fake_rc, cfg=cfg)
        survivors = await hf.apply([candidate])

        assert len(survivors) == 1
        assert survivors[0].mint == "GOOD_MINT"
        assert len(hf.dropped) == 0


class TestHardFilterMomentumDrop:
    async def test_low_liquidity_dropped_without_calling_rugcheck(self, cfg):
        """Candidate failing momentum must be dropped without RugCheck being called."""
        from memedog.hardfilter.hardfilter import HardFilter

        candidate = make_candidate(mint="LOW_LIQ", liquidity_usd=5_000.0)
        fake_rc = FakeRugCheck(reports={})

        hf = HardFilter(rugcheck=fake_rc, cfg=cfg)
        survivors = await hf.apply([candidate])

        assert len(survivors) == 0
        # RugCheck must NOT have been called for the low-liquidity candidate
        assert fake_rc.call_count == 0
        assert "LOW_LIQ" not in fake_rc.called_mints
        # The dropped list must contain this candidate with a reason
        assert len(hf.dropped) == 1
        dropped_mint, reason = hf.dropped[0]
        assert dropped_mint == "LOW_LIQ"
        assert "liquidity" in reason.lower()

    async def test_low_volume_dropped_without_calling_rugcheck(self, cfg):
        from memedog.hardfilter.hardfilter import HardFilter

        candidate = make_candidate(mint="LOW_VOL", volume_5m=100.0)
        fake_rc = FakeRugCheck(reports={})

        hf = HardFilter(rugcheck=fake_rc, cfg=cfg)
        survivors = await hf.apply([candidate])

        assert len(survivors) == 0
        assert fake_rc.call_count == 0


class TestHardFilterAuthorityDrop:
    async def test_active_mint_authority_drops_candidate(self, cfg):
        """A token with mint authority NOT revoked is dropped at authority stage."""
        from memedog.hardfilter.hardfilter import HardFilter

        candidate = make_candidate(mint="MINT_ACTIVE")
        # mintAuthority is not None → not revoked
        raw_report = {
            "mintAuthority": "SomeActiveKey",
            "freezeAuthority": None,
            "markets": [{"lpBurned": True, "lpLocked": False}],
            "topHolders": [{"pct": 2.5}] * 10,
            "largestWalletPct": 10.0,
            "insiders": {"devPct": 4.0, "sniperPct": 15.0},
            "score": 50,
            "riskLevel": "medium",
        }
        fake_rc = FakeRugCheck(reports={"MINT_ACTIVE": raw_report})

        hf = HardFilter(rugcheck=fake_rc, cfg=cfg)
        survivors = await hf.apply([candidate])

        assert len(survivors) == 0
        assert len(hf.dropped) == 1
        _, reason = hf.dropped[0]
        assert "mint" in reason.lower()

    async def test_lp_not_locked_drops_candidate(self, cfg):
        from memedog.hardfilter.hardfilter import HardFilter

        candidate = make_candidate(mint="LP_BAD")
        raw_report = {
            "mintAuthority": None,
            "freezeAuthority": None,
            "markets": [{"lpBurned": False, "lpLocked": False}],
            "topHolders": [{"pct": 2.5}] * 10,
            "largestWalletPct": 10.0,
            "insiders": {"devPct": 4.0, "sniperPct": 15.0},
            "score": 60,
            "riskLevel": "medium",
        }
        fake_rc = FakeRugCheck(reports={"LP_BAD": raw_report})

        hf = HardFilter(rugcheck=fake_rc, cfg=cfg)
        survivors = await hf.apply([candidate])

        assert len(survivors) == 0
        _, reason = hf.dropped[0]
        assert "lp" in reason.lower()


class TestHardFilterHoldersDrop:
    async def test_high_top10_concentration_drops_candidate(self, cfg):
        from memedog.hardfilter.hardfilter import HardFilter

        candidate = make_candidate(mint="HIGH_CONC")
        raw_report = {
            "mintAuthority": None,
            "freezeAuthority": None,
            "markets": [{"lpBurned": True, "lpLocked": False}],
            "topHolders": [{"pct": 4.0}] * 10,  # sum = 40 > 35
            "largestWalletPct": 10.0,
            "insiders": {"devPct": 4.0, "sniperPct": 15.0},
            "score": 70,
            "riskLevel": "medium",
        }
        fake_rc = FakeRugCheck(reports={"HIGH_CONC": raw_report})

        hf = HardFilter(rugcheck=fake_rc, cfg=cfg)
        survivors = await hf.apply([candidate])

        assert len(survivors) == 0
        _, reason = hf.dropped[0]
        assert "top10" in reason.lower() or "top 10" in reason.lower()


class TestHardFilterRugCheckFailure:
    async def test_rugcheck_datasource_error_drop_mode(self, cfg):
        """DataSourceError with on_rugcheck_failure='drop' → candidate is dropped."""
        from memedog.hardfilter.hardfilter import HardFilter

        candidate = make_candidate(mint="RC_FAIL")
        fake_rc = FakeRugCheck(error=DataSourceError("network error"))

        hf = HardFilter(rugcheck=fake_rc, cfg=cfg)
        survivors = await hf.apply([candidate])

        assert len(survivors) == 0
        assert len(hf.dropped) == 1
        _, reason = hf.dropped[0]
        assert "rugcheck" in reason.lower() or "unavailable" in reason.lower()

    async def test_rugcheck_datasource_error_pass_flagged_mode(self, cfg_pass_flagged):
        """DataSourceError with on_rugcheck_failure='pass_flagged' → candidate survives
        and an audit entry is recorded in hf.flagged."""
        from memedog.hardfilter.hardfilter import HardFilter

        candidate = make_candidate(mint="RC_FLAG")
        fake_rc = FakeRugCheck(error=DataSourceError("timeout"))

        hf = HardFilter(rugcheck=fake_rc, cfg=cfg_pass_flagged)
        survivors = await hf.apply([candidate])

        # Must survive
        assert len(survivors) == 1
        assert survivors[0].mint == "RC_FLAG"
        # Must NOT be in dropped
        assert len(hf.dropped) == 0
        # Must have audit entry in flagged
        assert ("RC_FLAG", "rugcheck_unavailable_pass_flagged") in hf.flagged


class TestHardFilterMultipleCandidates:
    async def test_mixed_candidates_correct_routing(self, cfg):
        """With 3 candidates: one passes, one fails momentum, one fails authority."""
        from memedog.hardfilter.hardfilter import HardFilter

        good = make_candidate(mint="GOOD")
        low_liq = make_candidate(mint="LOW_LIQ", liquidity_usd=1_000.0)
        bad_auth = make_candidate(mint="BAD_AUTH")

        good_report = {
            "mintAuthority": None,
            "freezeAuthority": None,
            "markets": [{"lpBurned": True, "lpLocked": False}],
            "topHolders": [{"pct": 2.5}] * 10,
            "largestWalletPct": 10.0,
            "insiders": {"devPct": 4.0, "sniperPct": 15.0},
            "score": 90,
            "riskLevel": "low",
        }
        bad_auth_report = {
            "mintAuthority": "SomeActiveKey",
            "freezeAuthority": None,
            "markets": [{"lpBurned": True, "lpLocked": False}],
            "topHolders": [{"pct": 2.5}] * 10,
            "largestWalletPct": 10.0,
            "insiders": {"devPct": 4.0, "sniperPct": 15.0},
            "score": 50,
            "riskLevel": "medium",
        }
        fake_rc = FakeRugCheck(reports={"GOOD": good_report, "BAD_AUTH": bad_auth_report})

        hf = HardFilter(rugcheck=fake_rc, cfg=cfg)
        survivors = await hf.apply([good, low_liq, bad_auth])

        assert len(survivors) == 1
        assert survivors[0].mint == "GOOD"
        # LOW_LIQ was dropped at momentum stage → RugCheck never called for it
        assert "LOW_LIQ" not in fake_rc.called_mints
        # Total dropped = 2
        assert len(hf.dropped) == 2

    async def test_apply_resets_dropped_between_calls(self, cfg):
        """dropped list must be reset at the start of each apply() call."""
        from memedog.hardfilter.hardfilter import HardFilter

        bad = make_candidate(mint="BAD", liquidity_usd=1_000.0)
        fake_rc = FakeRugCheck(reports={})

        hf = HardFilter(rugcheck=fake_rc, cfg=cfg)
        await hf.apply([bad])
        assert len(hf.dropped) == 1

        # Second call with no candidates → dropped must be empty
        await hf.apply([])
        assert len(hf.dropped) == 0
