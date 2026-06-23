"""Task 4 — Tests for Enricher orchestration.

RED phase: all tests must fail until enricher.py is implemented.

Tests:
  - all providers succeed → snapshot has all dimensions available
  - one provider raises → that dimension available=False, others fine
  - one provider times out → that dimension available=False, others fine
  - enrich() never raises (swallows all dimension failures)
  - enriched_at is timezone-aware UTC
"""
from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

# Real fixture for pre-fetched rugcheck report test
from tests.conftest import load_fixture as _load_fixture
from memedog.clients.rugcheck import parse_report as _parse_report

_REPORT_BONK_PARSED = _parse_report(_load_fixture("rugcheck/report_bonk.json"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_candidate():
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


def make_enricher_cfg(timeout_sec: float = 5.0):
    """Return an EnricherConfig-like object for testing."""
    from memedog.config.settings import EnricherConfig

    return EnricherConfig(
        per_provider_timeout_sec=timeout_sec,
        smart_money_wallets_file="nonexistent_file.txt",
        twitter_lookback_min=60,
    )


# ---------------------------------------------------------------------------
# Fake clients / providers for injection
# ---------------------------------------------------------------------------

class FakeRugCheckClient:
    async def get_token_report(self, mint: str) -> dict:
        return {"score": 90, "riskLevel": "low"}


class FakeHeliusClient:
    async def get_largest_holders(self, mint: str) -> dict:
        return {"top10_pct": 20.0, "max_wallet_pct": 5.0, "holder_count": 15}

    async def count_smart_money_buys(self, mint: str, smart_wallets: set) -> int:
        return 0


class FakeTwitterClient:
    async def count_mentions(self, query: str, lookback_min: int) -> dict:
        return {"mentions_1h": 42, "growth": 10.0}


class SlowHeliusClient:
    """Simulates a provider that takes longer than the configured timeout."""
    async def get_largest_holders(self, mint: str) -> dict:
        await asyncio.sleep(10)  # longer than any test timeout
        return {"top10_pct": 1.0, "max_wallet_pct": 1.0, "holder_count": 1}

    async def count_smart_money_buys(self, mint: str, smart_wallets: set) -> int:
        return 0


class ErrorHeliusClient:
    """Simulates a provider that always raises."""
    async def get_largest_holders(self, mint: str) -> dict:
        raise RuntimeError("helius is down")

    async def count_smart_money_buys(self, mint: str, smart_wallets: set) -> int:
        raise RuntimeError("helius is down")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnricherAllSucceed:
    async def test_snapshot_returned_with_all_dimensions_available(self):
        """When all providers succeed, every dimension in snapshot is available."""
        from memedog.enricher.enricher import Enricher

        enricher = Enricher(
            rugcheck_client=FakeRugCheckClient(),
            helius_client=FakeHeliusClient(),
            twitter_client=FakeTwitterClient(),
            cfg=make_enricher_cfg(),
        )

        snapshot = await enricher.enrich(make_candidate())

        assert snapshot.safety.available is True
        assert snapshot.holders.available is True
        assert snapshot.momentum.available is True
        # social may or may not be available depending on smart_wallets file absence
        # at minimum, enrich returns a TokenSnapshot
        from memedog.models import TokenSnapshot
        assert isinstance(snapshot, TokenSnapshot)

    async def test_enriched_at_is_timezone_aware_utc(self):
        """enriched_at must be timezone-aware (UTC)."""
        from memedog.enricher.enricher import Enricher

        enricher = Enricher(
            rugcheck_client=FakeRugCheckClient(),
            helius_client=FakeHeliusClient(),
            twitter_client=FakeTwitterClient(),
            cfg=make_enricher_cfg(),
        )

        snapshot = await enricher.enrich(make_candidate())

        assert snapshot.enriched_at.tzinfo is not None

    async def test_candidate_preserved_in_snapshot(self):
        """The candidate passed to enrich() is stored in snapshot.candidate."""
        from memedog.enricher.enricher import Enricher

        enricher = Enricher(
            rugcheck_client=FakeRugCheckClient(),
            helius_client=FakeHeliusClient(),
            twitter_client=FakeTwitterClient(),
            cfg=make_enricher_cfg(),
        )
        candidate = make_candidate()
        snapshot = await enricher.enrich(candidate)

        assert snapshot.candidate.mint == candidate.mint
        assert snapshot.candidate.symbol == candidate.symbol


class TestEnricherPartialFailure:
    async def test_holders_provider_raises_makes_holders_unavailable(self):
        """If helius client raises, holders dimension is available=False; others fine."""
        from memedog.enricher.enricher import Enricher

        enricher = Enricher(
            rugcheck_client=FakeRugCheckClient(),
            helius_client=ErrorHeliusClient(),
            twitter_client=FakeTwitterClient(),
            cfg=make_enricher_cfg(),
        )

        snapshot = await enricher.enrich(make_candidate())

        assert snapshot.holders.available is False
        # safety and momentum should still be available
        assert snapshot.safety.available is True
        assert snapshot.momentum.available is True

    async def test_enrich_never_raises_on_provider_failure(self):
        """enrich() must never propagate provider exceptions to the caller."""
        from memedog.enricher.enricher import Enricher

        enricher = Enricher(
            rugcheck_client=FakeRugCheckClient(),
            helius_client=ErrorHeliusClient(),
            twitter_client=FakeTwitterClient(),
            cfg=make_enricher_cfg(),
        )

        # Must not raise
        snapshot = await enricher.enrich(make_candidate())
        assert snapshot is not None

    async def test_pre_fetched_rugcheck_report_used_for_safety(self):
        """When rugcheck_report passed to enrich(), used directly for safety.

        Uses the REAL parsed report_bonk.json fixture instead of a hand-crafted dict.
        BONK real values: trust_score=93 (score_normalised=7 → 100-7=93), risk_level='LOW',
        mint_authority_revoked=True, freeze_authority_revoked=True, lp_burned_or_locked=False.
        """
        from memedog.enricher.enricher import Enricher

        enricher = Enricher(
            rugcheck_client=FakeRugCheckClient(),
            helius_client=FakeHeliusClient(),
            twitter_client=FakeTwitterClient(),
            cfg=make_enricher_cfg(),
        )

        # Pass the REAL pre-parsed BONK report fixture
        snapshot = await enricher.enrich(make_candidate(), rugcheck_report=_REPORT_BONK_PARSED)

        # Verify real BONK fixture values are reflected in SafetyInfo
        assert snapshot.safety.rug_trust_score == 93   # 100 - score_normalised(7)
        assert snapshot.safety.rug_risk_level == "LOW"
        assert snapshot.safety.mint_authority_revoked is True
        assert snapshot.safety.freeze_authority_revoked is True
        assert snapshot.safety.lp_burned_or_locked is False  # real BONK: lpLockedPct=0


class TestEnricherTimeout:
    async def test_slow_helius_causes_holders_unavailable(self):
        """If helius times out (past per_provider_timeout_sec), holders=unavailable."""
        from memedog.enricher.enricher import Enricher

        # Use a very short timeout so SlowHeliusClient always times out
        enricher = Enricher(
            rugcheck_client=FakeRugCheckClient(),
            helius_client=SlowHeliusClient(),
            twitter_client=FakeTwitterClient(),
            cfg=make_enricher_cfg(timeout_sec=0.05),  # 50ms
        )

        snapshot = await enricher.enrich(make_candidate())

        assert snapshot.holders.available is False

    async def test_timeout_does_not_prevent_other_dimensions(self):
        """When helius times out, safety and momentum are still available."""
        from memedog.enricher.enricher import Enricher

        enricher = Enricher(
            rugcheck_client=FakeRugCheckClient(),
            helius_client=SlowHeliusClient(),
            twitter_client=FakeTwitterClient(),
            cfg=make_enricher_cfg(timeout_sec=0.05),
        )

        snapshot = await enricher.enrich(make_candidate())

        assert snapshot.safety.available is True
        assert snapshot.momentum.available is True

    async def test_enrich_never_raises_on_timeout(self):
        """enrich() must not raise even when providers time out."""
        from memedog.enricher.enricher import Enricher

        enricher = Enricher(
            rugcheck_client=FakeRugCheckClient(),
            helius_client=SlowHeliusClient(),
            twitter_client=FakeTwitterClient(),
            cfg=make_enricher_cfg(timeout_sec=0.05),
        )

        # Must not raise
        snapshot = await enricher.enrich(make_candidate())
        assert snapshot is not None


class TestEnricherSmartWalletsFile:
    async def test_missing_smart_wallets_file_does_not_crash(self):
        """If smart_money_wallets_file does not exist, enrich proceeds normally."""
        from memedog.enricher.enricher import Enricher

        enricher = Enricher(
            rugcheck_client=FakeRugCheckClient(),
            helius_client=FakeHeliusClient(),
            twitter_client=FakeTwitterClient(),
            cfg=make_enricher_cfg(),  # points to nonexistent_file.txt
        )

        snapshot = await enricher.enrich(make_candidate())
        assert snapshot is not None


# ---------------------------------------------------------------------------
# Task 3 — _load_smart_wallets loader upgrade tests
# ---------------------------------------------------------------------------


def test_load_smart_wallets_with_labels(tmp_path):
    from memedog.enricher.enricher import _load_smart_wallets
    p = tmp_path / "wallets.txt"
    p.write_text(
        "# comment line\n"
        "AAA,early-BONK-buyer,S\n"
        "BBB,KOL-wallet,A\n"
        "CCC\n"            # bare address, no label/tier
        "\n",             # blank line
        encoding="utf-8",
    )
    lib = _load_smart_wallets(str(p))
    assert set(lib.keys()) == {"AAA", "BBB", "CCC"}
    assert lib["AAA"].label == "early-BONK-buyer" and lib["AAA"].tier == "S"
    assert lib["CCC"].label is None and lib["CCC"].tier is None


def test_load_smart_wallets_missing_file_returns_empty():
    from memedog.enricher.enricher import _load_smart_wallets
    lib = _load_smart_wallets("/nonexistent/path/wallets.txt")
    assert lib == {}
