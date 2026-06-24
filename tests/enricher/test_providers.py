"""Task 3 — Tests for enricher provider functions.

RED phase: all tests must fail until providers.py is implemented.

Tests each provider:
  - success path → fills fields correctly
  - error path  → returns *Info(available=False), never raises

fetch_social semantics (Twitter removed from production — Phase 1):
  - smart-money consensus present → available=True with consensus fields set
  - smart money None but social metadata present → available=True
  - no smart money and no social metadata → available=False
"""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from memedog.models import WalletInfo

# Real fixtures for use in the fetch_safety and fetch_holders real-data tests
from tests.conftest import load_fixture as _load_fixture

_REPORT_BONK_RAW = _load_fixture("rugcheck/report_bonk.json")
_HELIUS_LARGEST_OK = _load_fixture("helius/largest_accounts_ok.json")


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

def make_candidate():
    """Return a minimal TokenCandidate for testing."""
    from memedog.models import TokenCandidate

    return TokenCandidate(
        mint="So11111111111111111111111111111111111111112",
        pair_address="PairABC",
        symbol="DOGE",
        chain="solana",
        pair_created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        price_usd=0.001,
        liquidity_usd=50_000.0,
        fdv_usd=500_000.0,
        volume_5m=1_500.0,
        volume_1h=15_000.0,
        txns_5m_buys=80,
        txns_5m_sells=40,
        price_change_5m=2.5,
        trace_id="trace-001",
    )


PARSED_REPORT = {
    "mint_authority_revoked": True,
    "freeze_authority_revoked": True,
    "lp_burned_or_locked": True,
    "top10_pct": 23.4,
    "max_wallet_pct": 5.0,
    "dev_pct": 2.0,
    "sniper_pct": 4.0,
    "trust_score": 85,
    "risk_level": "low",
}


# ---------------------------------------------------------------------------
# fetch_safety
# ---------------------------------------------------------------------------


class TestFetchSafety:
    async def test_pre_fetched_report_maps_to_safety_info(self):
        """When a pre-parsed report dict is supplied, maps fields to SafetyInfo."""
        from memedog.enricher.providers import fetch_safety

        result = await fetch_safety(
            mint="MINT123",
            rugcheck_report=PARSED_REPORT,
        )

        assert result.available is True
        assert result.mint_authority_revoked is True
        assert result.freeze_authority_revoked is True
        assert result.lp_burned_or_locked is True
        assert result.rug_trust_score == 85
        assert result.rug_risk_level == "low"

    async def test_no_report_fetches_via_client(self):
        """When no pre-fetched report, calls rugcheck_client.get_token_report.

        Uses real RugCheck API schema: score_normalised (RISK score, higher=riskier)
        is used to derive trust_score (100 - score_normalised) and risk_level.
        score_normalised=30 → trust=70, risk_level='MEDIUM'.
        """
        from memedog.enricher.providers import fetch_safety
        from memedog.clients.rugcheck import parse_report

        mock_client = AsyncMock()
        mock_client.get_token_report = AsyncMock(
            return_value={
                "mintAuthority": None,
                "freezeAuthority": None,
                "score_normalised": 30,  # RISK score; trust = 100-30 = 70
                "rugged": False,
                "markets": [],
                "topHolders": [],
                "token": {"supply": 1_000_000, "decimals": 6},
                "creatorBalance": 0,
            }
        )

        result = await fetch_safety(
            mint="MINT123",
            rugcheck_report=None,
            rugcheck_client=mock_client,
        )

        mock_client.get_token_report.assert_called_once_with("MINT123")
        assert result.available is True
        assert result.rug_trust_score == 70
        assert result.rug_risk_level == "MEDIUM"

    async def test_client_error_returns_unavailable(self):
        """If rugcheck_client raises, return SafetyInfo(available=False)."""
        from memedog.enricher.providers import fetch_safety
        from memedog.clients.base import DataSourceError

        mock_client = AsyncMock()
        mock_client.get_token_report = AsyncMock(
            side_effect=DataSourceError("network error")
        )

        result = await fetch_safety(
            mint="MINT123",
            rugcheck_report=None,
            rugcheck_client=mock_client,
        )

        assert result.available is False

    async def test_no_report_and_no_client_returns_unavailable(self):
        """No report + no client → SafetyInfo(available=False), no crash."""
        from memedog.enricher.providers import fetch_safety

        result = await fetch_safety(mint="MINT123", rugcheck_report=None)

        assert result.available is False

    async def test_real_bonk_report_via_client_maps_to_safety_info(self):
        """Real report_bonk.json returned by rugcheck client maps correctly to SafetyInfo.

        BONK parsed values: trust_score=93, risk_level='LOW',
        mint_authority_revoked=True, freeze_authority_revoked=True,
        lp_burned_or_locked=False (lpLockedPct=0 in real data).
        """
        from memedog.enricher.providers import fetch_safety

        mock_client = AsyncMock()
        mock_client.get_token_report = AsyncMock(return_value=_REPORT_BONK_RAW)

        result = await fetch_safety(
            mint=_REPORT_BONK_RAW["mint"],
            rugcheck_report=None,
            rugcheck_client=mock_client,
        )

        mock_client.get_token_report.assert_called_once_with(_REPORT_BONK_RAW["mint"])
        assert result.available is True
        # BONK: score_normalised=7 → trust_score=93, risk_level='LOW'
        assert result.rug_trust_score == 93
        assert result.rug_risk_level == "LOW"
        assert result.mint_authority_revoked is True
        assert result.freeze_authority_revoked is True
        assert result.lp_burned_or_locked is False  # real BONK: lpLockedPct=0


# ---------------------------------------------------------------------------
# fetch_holders
# ---------------------------------------------------------------------------


class TestFetchHolders:
    async def test_success_maps_helius_fields(self):
        """get_largest_holders result maps to HolderInfo fields."""
        from memedog.enricher.providers import fetch_holders

        mock_helius = AsyncMock()
        mock_helius.get_largest_holders = AsyncMock(
            return_value={
                "top10_pct": 35.0,
                "max_wallet_pct": 8.0,
                "holder_count": 18,
            }
        )

        result = await fetch_holders(mint="MINT123", helius_client=mock_helius)

        assert result.available is True
        assert result.top10_pct == pytest.approx(35.0)
        assert result.max_wallet_pct == pytest.approx(8.0)
        assert result.holder_count == 18
        # dev_wallet_pct and sniper_pct are not available from this call
        assert result.dev_wallet_pct is None
        assert result.sniper_pct is None

    async def test_helius_error_returns_unavailable(self):
        """If helius_client raises, return HolderInfo(available=False)."""
        from memedog.enricher.providers import fetch_holders
        from memedog.clients.base import DataSourceError

        mock_helius = AsyncMock()
        mock_helius.get_largest_holders = AsyncMock(
            side_effect=DataSourceError("rpc error")
        )

        result = await fetch_holders(mint="MINT123", helius_client=mock_helius)

        assert result.available is False

    async def test_arbitrary_exception_returns_unavailable(self):
        """Any exception (not just DataSourceError) → available=False."""
        from memedog.enricher.providers import fetch_holders

        mock_helius = AsyncMock()
        mock_helius.get_largest_holders = AsyncMock(
            side_effect=RuntimeError("unexpected")
        )

        result = await fetch_holders(mint="MINT123", helius_client=mock_helius)

        assert result.available is False

    async def test_real_helius_fixture_holders_mapped_correctly(self):
        """largest_accounts_ok.json → HolderInfo with real computed percentages.

        The HeliusClient.get_largest_holders method computes:
          top10_pct and max_wallet_pct relative to sum of returned uiAmounts.
        We simulate the client returning the pre-computed result (as the real
        client would after parsing the RPC response), and verify the mapping.

        Real fixture values (20 accounts):
          top10_pct ≈ 96.22%  (first account alone holds ~74.3%)
          max_wallet_pct ≈ 74.32%
          holder_count = 20
        """
        from memedog.enricher.providers import fetch_holders

        # Simulate what HeliusClient.get_largest_holders returns after
        # parsing the raw RPC response from largest_accounts_ok.json
        accounts = _HELIUS_LARGEST_OK["result"]["value"]
        amounts = [a.get("uiAmount") or 0.0 for a in accounts]
        total = sum(amounts)
        expected_top10_pct = sum(amounts[:10]) / total * 100.0
        expected_max_pct = max(amounts) / total * 100.0
        expected_count = len(accounts)

        mock_helius = AsyncMock()
        mock_helius.get_largest_holders = AsyncMock(
            return_value={
                "top10_pct": expected_top10_pct,
                "max_wallet_pct": expected_max_pct,
                "holder_count": expected_count,
            }
        )

        result = await fetch_holders(
            mint=_REPORT_BONK_RAW["mint"],  # reuse BONK mint for consistency
            helius_client=mock_helius,
        )

        assert result.available is True
        assert result.top10_pct == pytest.approx(expected_top10_pct, rel=1e-4)
        assert result.max_wallet_pct == pytest.approx(expected_max_pct, rel=1e-4)
        assert result.holder_count == expected_count  # 20 accounts in fixture
        assert result.dev_wallet_pct is None   # not available from this RPC call
        assert result.sniper_pct is None


# ---------------------------------------------------------------------------
# fetch_momentum
# ---------------------------------------------------------------------------


class TestFetchMomentum:
    async def test_derives_fields_from_candidate(self):
        """MomentumInfo is derived purely from TokenCandidate — no network."""
        from memedog.enricher.providers import fetch_momentum

        candidate = make_candidate()
        result = await fetch_momentum(candidate)

        assert result.available is True
        assert result.liquidity_usd == pytest.approx(50_000.0)
        assert result.volume_5m == pytest.approx(1_500.0)
        assert result.volume_1h == pytest.approx(15_000.0)

    async def test_buy_sell_ratio_computed(self):
        """buy_sell_ratio_5m = txns_5m_buys / max(txns_5m_sells, 1)."""
        from memedog.enricher.providers import fetch_momentum

        candidate = make_candidate()  # 80 buys, 40 sells → ratio = 2.0
        result = await fetch_momentum(candidate)

        assert result.buy_sell_ratio_5m == pytest.approx(2.0)

    async def test_zero_sells_does_not_divide_by_zero(self):
        """When txns_5m_sells=0, uses max(0, 1)=1 to avoid division by zero."""
        from memedog.enricher.providers import fetch_momentum

        candidate = make_candidate()
        candidate = candidate.model_copy(update={"txns_5m_sells": 0, "txns_5m_buys": 10})
        result = await fetch_momentum(candidate)

        assert result.buy_sell_ratio_5m == pytest.approx(10.0)
        assert result.available is True

    async def test_fdv_to_liquidity_computed(self):
        """fdv_to_liquidity = fdv_usd / max(liquidity_usd, epsilon)."""
        from memedog.enricher.providers import fetch_momentum

        candidate = make_candidate()  # fdv=500_000, liquidity=50_000 → 10.0
        result = await fetch_momentum(candidate)

        assert result.fdv_to_liquidity == pytest.approx(10.0)

    async def test_unique_buyers_1h_is_none(self):
        """unique_buyers_1h is not available from candidate fields → None."""
        from memedog.enricher.providers import fetch_momentum

        result = await fetch_momentum(make_candidate())

        assert result.unique_buyers_1h is None


# ---------------------------------------------------------------------------
# fetch_social (new DI-style signature: no Twitter, uses analyze_smart_money)
# ---------------------------------------------------------------------------


class TestFetchSocial:
    async def test_smart_money_succeeds_returns_available(self):
        """When helius analyze_smart_money succeeds, SocialInfo is available."""
        from memedog.enricher.providers import fetch_social
        from memedog.models import WalletInfo

        mock_helius = AsyncMock()
        mock_helius.analyze_smart_money = AsyncMock(
            return_value={"buys": 3, "distinct_wallets": 2, "buyers": [], "top_tier": "A"}
        )

        result = await fetch_social(
            mint="MINT123",
            helius_client=mock_helius,
            smart_wallets={"wallet1": WalletInfo(address="wallet1")},
            social_platforms=[],
            galaxy_score=None,
        )

        assert result.available is True
        assert result.smart_money_buys == 3
        assert result.smart_money_distinct_wallets == 2
        assert result.smart_money_top_tier == "A"

    async def test_social_metadata_alone_makes_available(self):
        """Social metadata (platforms) alone → available=True even if smart money fails."""
        from memedog.enricher.providers import fetch_social

        mock_helius = AsyncMock()
        mock_helius.analyze_smart_money = AsyncMock(return_value=None)

        result = await fetch_social(
            mint="MINT123",
            helius_client=mock_helius,
            smart_wallets={},
            social_platforms=["twitter", "telegram"],
            galaxy_score=None,
        )

        assert result.available is True
        assert result.has_twitter is True
        assert result.has_telegram is True
        assert result.smart_money_buys is None

    async def test_smart_money_raises_partial_result_still_available_via_metadata(self):
        """Helius raises but social metadata present → available=True, smart money fields None."""
        from memedog.enricher.providers import fetch_social
        from memedog.clients.base import DataSourceError

        mock_helius = AsyncMock()
        mock_helius.analyze_smart_money = AsyncMock(
            side_effect=DataSourceError("helius error")
        )

        result = await fetch_social(
            mint="MINT123",
            helius_client=mock_helius,
            smart_wallets={},
            social_platforms=["twitter"],
            galaxy_score=None,
        )

        assert result.available is True
        assert result.smart_money_buys is None
        assert result.has_twitter is True

    async def test_both_sources_fail_returns_unavailable(self):
        """No smart money + no social metadata → SocialInfo(available=False)."""
        from memedog.enricher.providers import fetch_social
        from memedog.clients.base import DataSourceError

        mock_helius = AsyncMock()
        mock_helius.analyze_smart_money = AsyncMock(
            side_effect=DataSourceError("helius error")
        )

        result = await fetch_social(
            mint="MINT123",
            helius_client=mock_helius,
            smart_wallets={},
            social_platforms=[],
            galaxy_score=None,
        )

        assert result.available is False

    async def test_empty_smart_wallets_dict_with_result_returns_available(self):
        """Empty wallet library → analyze_smart_money still called; result used."""
        from memedog.enricher.providers import fetch_social

        mock_helius = AsyncMock()
        mock_helius.analyze_smart_money = AsyncMock(
            return_value={"buys": 0, "distinct_wallets": 0, "buyers": [], "top_tier": None}
        )

        result = await fetch_social(
            mint="MINT123",
            helius_client=mock_helius,
            smart_wallets={},
            social_platforms=[],
            galaxy_score=None,
        )

        assert result.available is True
        assert result.smart_money_buys == 0

    async def test_smart_money_none_no_socials_returns_unavailable(self):
        """analyze_smart_money returns None + no socials → available=False."""
        from memedog.enricher.providers import fetch_social

        mock_helius = AsyncMock()
        mock_helius.analyze_smart_money = AsyncMock(return_value=None)

        result = await fetch_social(
            mint="MINT123",
            helius_client=mock_helius,
            smart_wallets={"wallet1": None},
            social_platforms=[],
            galaxy_score=None,
        )

        assert result.available is False

    async def test_smart_money_with_socials_returns_available(self):
        """analyze_smart_money returns real value + social platforms → available=True."""
        from memedog.enricher.providers import fetch_social
        from memedog.models import WalletInfo

        mock_helius = AsyncMock()
        mock_helius.analyze_smart_money = AsyncMock(
            return_value={"buys": 5, "distinct_wallets": 3, "buyers": [], "top_tier": "S"}
        )

        result = await fetch_social(
            mint="MINT123",
            helius_client=mock_helius,
            smart_wallets={"wallet1": WalletInfo(address="wallet1")},
            social_platforms=["twitter"],
            galaxy_score=None,
        )

        assert result.available is True
        assert result.smart_money_buys == 5
        assert result.has_twitter is True


# ---------------------------------------------------------------------------
# New fetch_social (DI-style, no Twitter) + fetch_narrative — Task 7
# ---------------------------------------------------------------------------


class _FakeHelius:
    def __init__(self, result):
        self._result = result

    async def analyze_smart_money(self, mint, library):
        return self._result


@pytest.mark.asyncio
async def test_fetch_social_consensus_and_metadata():
    from memedog.enricher.providers import fetch_social
    helius = _FakeHelius({
        "buys": 3, "distinct_wallets": 2,
        "buyers": [WalletInfo(address="A", label="kol", tier="A")],
        "top_tier": "A",
    })
    info = await fetch_social(
        mint="M", helius_client=helius,
        smart_wallets={"A": WalletInfo(address="A")},
        social_platforms=["twitter", "telegram", "website"],
        galaxy_score=None,
    )
    assert info.available is True
    assert info.smart_money_buys == 3
    assert info.smart_money_distinct_wallets == 2
    assert info.smart_money_top_tier == "A"
    assert info.has_twitter is True and info.has_telegram is True and info.has_website is True
    assert info.socials_count == 3


@pytest.mark.asyncio
async def test_fetch_social_smart_money_none_still_available_via_metadata():
    from memedog.enricher.providers import fetch_social
    helius = _FakeHelius(None)
    info = await fetch_social(
        mint="M", helius_client=helius, smart_wallets={"A": WalletInfo(address="A")},
        social_platforms=["twitter"], galaxy_score=None,
    )
    assert info.available is True
    assert info.has_twitter is True
    assert info.smart_money_distinct_wallets is None


@pytest.mark.asyncio
async def test_fetch_social_no_smart_no_socials_unavailable():
    from memedog.enricher.providers import fetch_social
    helius = _FakeHelius(None)
    info = await fetch_social(mint="M", helius_client=helius, smart_wallets={}, social_platforms=[], galaxy_score=None)
    assert info.available is False


@pytest.mark.asyncio
async def test_fetch_social_galaxy_alone_makes_available():
    """galaxy_score is the sole signal (no smart money, no socials) → available=True."""
    from memedog.enricher.providers import fetch_social
    helius = _FakeHelius(None)
    info = await fetch_social(
        mint="M", helius_client=helius, smart_wallets={},
        social_platforms=[], galaxy_score=61.0,
    )
    assert info.available is True
    assert info.galaxy_score == 61.0
    assert info.socials_count is None


@pytest.mark.asyncio
async def test_fetch_narrative_delegates():
    from memedog.enricher.providers import fetch_narrative
    info = await fetch_narrative(symbol="QDOG", name="Quantum Dog")
    assert info.category == "animal"


# --- Fix: holders must be AMM-consistent with HardFilter (use RugCheck report) ---

class _FakeHeliusHolders:
    """Returns AMM-INCLUDED (inflated) concentration like the raw RPC does."""
    async def get_largest_holders(self, mint):
        return {"top10_pct": 99.0, "max_wallet_pct": 50.0, "holder_count": 18}


@pytest.mark.asyncio
async def test_fetch_holders_prefers_rugcheck_amm_excluded():
    """When a RugCheck report is present, holders concentration comes from it
    (AMM-excluded, consistent with HardFilter) — NOT the inflated Helius value."""
    from memedog.enricher.providers import fetch_holders
    report = {"top10_pct": 24.2, "max_wallet_pct": 3.0, "dev_pct": 0.0, "sniper_pct": 1.5}
    info = await fetch_holders("M", _FakeHeliusHolders(), rugcheck_report=report)
    assert info.available is True
    assert info.top10_pct == 24.2          # RugCheck, not Helius 99.0
    assert info.max_wallet_pct == 3.0       # RugCheck, not Helius 50.0
    assert info.dev_wallet_pct == 0.0
    assert info.sniper_pct == 1.5
    assert info.holder_count == 18          # count still from Helius


@pytest.mark.asyncio
async def test_fetch_holders_falls_back_to_helius_without_report():
    from memedog.enricher.providers import fetch_holders
    info = await fetch_holders("M", _FakeHeliusHolders(), rugcheck_report=None)
    assert info.top10_pct == 99.0           # no report → Helius approximation
    assert info.holder_count == 18


class _SlowCountHelius:
    async def get_largest_holders(self, mint):
        await asyncio.sleep(5)              # simulate a hanging RPC
        return {"holder_count": 20}


@pytest.mark.asyncio
async def test_fetch_holders_concentration_survives_slow_helius_count():
    """With a RugCheck report, a slow/hanging Helius holder_count call must NOT
    lose the (already-available, AMM-excluded) concentration data."""
    from memedog.enricher.providers import fetch_holders
    report = {"top10_pct": 24.2, "max_wallet_pct": 3.0, "dev_pct": 0.0, "sniper_pct": 1.5}
    info = await fetch_holders(
        "M", _SlowCountHelius(), rugcheck_report=report, holder_count_timeout=0.1
    )
    assert info.available is True
    assert info.top10_pct == 24.2          # concentration preserved
    assert info.max_wallet_pct == 3.0
    assert info.holder_count is None        # count timed out → None, not fatal


# --- Fix: free social metadata must survive a slow/hanging smart-money call ---

class _SlowHelius:
    async def analyze_smart_money(self, mint, library):
        await asyncio.sleep(5)  # simulate a slow Helius transactions call
        return {"buys": 1, "distinct_wallets": 1, "buyers": [], "top_tier": None}


@pytest.mark.asyncio
async def test_fetch_social_metadata_survives_slow_smart_money():
    from memedog.enricher.providers import fetch_social
    info = await fetch_social(
        mint="M", helius_client=_SlowHelius(),
        smart_wallets={"A": WalletInfo(address="A")},
        social_platforms=["twitter", "telegram"], galaxy_score=None,
        smart_money_timeout=0.1,  # smart money exceeds this → degrades
    )
    assert info.available is True           # metadata preserved
    assert info.has_twitter is True and info.has_telegram is True
    assert info.socials_count == 2
    assert info.smart_money_distinct_wallets is None  # smart money timed out
