"""Tests for Task 2: Scanner (prefilter + convert + dedup)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from memedog.clients.base import DataSourceError
from memedog.config.settings import ScannerConfig
from memedog.models import TokenCandidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_scanner_config(**overrides) -> ScannerConfig:
    """Return a ScannerConfig with test-friendly defaults."""
    defaults = dict(
        scan_interval_sec=30,
        chain="solana",
        min_pair_age_min=5,
        max_pair_age_min=60,
        prefilter_min_liquidity_usd=10_000.0,
        prefilter_min_volume_5m=100.0,
        dedup_ttl_min=30,
    )
    defaults.update(overrides)
    return ScannerConfig(**defaults)


def make_raw_pair(
    address: str = "MINT_AAA",
    symbol: str = "AAA",
    pair_address: str = "PAIR_AAA",
    liquidity_usd: float = 25_000.0,
    volume_m5: float = 500.0,
    age_min: float = 15.0,          # age in minutes (relative to now)
    price_usd: str = "0.001",
    fdv: float = 1_000_000.0,
    volume_h1: float = 3_000.0,
    buys: int = 20,
    sells: int = 8,
    price_change_m5: float = 3.5,
) -> dict:
    """Build a raw DexScreener pair dict. age_min controls pairCreatedAt."""
    now_ms = int(time.time() * 1000)
    created_at_ms = now_ms - int(age_min * 60 * 1000)
    return {
        "baseToken": {"address": address, "symbol": symbol},
        "pairAddress": pair_address,
        "priceUsd": price_usd,
        "liquidity": {"usd": liquidity_usd},
        "fdv": fdv,
        "volume": {"m5": volume_m5, "h1": volume_h1},
        "txns": {"m5": {"buys": buys, "sells": sells}},
        "priceChange": {"m5": price_change_m5},
        "pairCreatedAt": created_at_ms,
    }


def make_fake_client(pairs: list[dict]) -> AsyncMock:
    """Return a mock client whose fetch_solana_pairs returns *pairs*."""
    client = AsyncMock()
    client.fetch_solana_pairs = AsyncMock(return_value=pairs)
    return client


# ---------------------------------------------------------------------------
# Prefilter tests
# ---------------------------------------------------------------------------

class TestPrefilter:
    async def test_pair_passing_all_filters_is_returned(self):
        """A pair within age window and above thresholds should be returned."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        pair = make_raw_pair(liquidity_usd=25_000, volume_m5=500, age_min=15)
        client = make_fake_client([pair])

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        assert isinstance(results[0], TokenCandidate)
        assert results[0].mint == "MINT_AAA"

    async def test_pair_below_liquidity_threshold_is_dropped(self):
        """A pair with liquidity < prefilter_min_liquidity_usd must be dropped."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(prefilter_min_liquidity_usd=10_000.0)
        pair = make_raw_pair(liquidity_usd=2_000.0, age_min=15)
        client = make_fake_client([pair])

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []

    async def test_pair_below_volume_threshold_is_dropped(self):
        """A pair with volume_m5 < prefilter_min_volume_5m must be dropped."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(prefilter_min_volume_5m=100.0)
        pair = make_raw_pair(volume_m5=50.0, age_min=15)
        client = make_fake_client([pair])

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []

    async def test_pair_too_young_is_dropped(self):
        """A pair younger than min_pair_age_min must be dropped."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(min_pair_age_min=5)
        pair = make_raw_pair(age_min=2.0)   # 2 min old, threshold is 5
        client = make_fake_client([pair])

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []

    async def test_pair_too_old_is_dropped(self):
        """A pair older than max_pair_age_min must be dropped."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(max_pair_age_min=60)
        pair = make_raw_pair(age_min=90.0)  # 90 min old, threshold is 60
        client = make_fake_client([pair])

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []

    async def test_mixed_pairs_only_passing_ones_returned(self):
        """Only pairs passing all filters are returned in a mixed batch."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        good = make_raw_pair(address="GOOD", liquidity_usd=25_000, volume_m5=500, age_min=15)
        bad_liq = make_raw_pair(address="BAD_LIQ", liquidity_usd=500, age_min=15)
        bad_age = make_raw_pair(address="BAD_AGE", age_min=120)  # too old
        client = make_fake_client([good, bad_liq, bad_age])

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        assert results[0].mint == "GOOD"


# ---------------------------------------------------------------------------
# Conversion tests
# ---------------------------------------------------------------------------

class TestConversion:
    async def test_token_candidate_fields_populated(self):
        """scan() converts raw pair to TokenCandidate with correct field values."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        pair = make_raw_pair(
            address="MINT_XYZ",
            symbol="XYZ",
            pair_address="PAIR_XYZ",
            liquidity_usd=30_000.0,
            volume_m5=800.0,
            age_min=20.0,
            price_usd="0.0045",
            fdv=500_000.0,
            volume_h1=4_000.0,
            buys=30,
            sells=10,
            price_change_m5=5.0,
        )
        client = make_fake_client([pair])

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        tc = results[0]
        assert tc.mint == "MINT_XYZ"
        assert tc.symbol == "XYZ"
        assert tc.pair_address == "PAIR_XYZ"
        assert tc.chain == "solana"
        assert tc.price_usd == pytest.approx(0.0045)
        assert tc.liquidity_usd == pytest.approx(30_000.0)
        assert tc.fdv_usd == pytest.approx(500_000.0)
        assert tc.volume_5m == pytest.approx(800.0)
        assert tc.volume_1h == pytest.approx(4_000.0)
        assert tc.txns_5m_buys == 30
        assert tc.txns_5m_sells == 10
        assert tc.price_change_5m == pytest.approx(5.0)
        assert isinstance(tc.pair_created_at, datetime)
        assert tc.pair_created_at.tzinfo is not None  # timezone-aware
        assert isinstance(tc.trace_id, str)
        assert len(tc.trace_id) > 0

    async def test_each_candidate_has_unique_trace_id(self):
        """Each TokenCandidate from a single scan() call has a unique trace_id."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        pair1 = make_raw_pair(address="MINT_A", pair_address="PAIR_A")
        pair2 = make_raw_pair(address="MINT_B", pair_address="PAIR_B")
        client = make_fake_client([pair1, pair2])

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 2
        trace_ids = {r.trace_id for r in results}
        assert len(trace_ids) == 2  # all unique


# ---------------------------------------------------------------------------
# Dedup tests
# ---------------------------------------------------------------------------

class TestDedup:
    async def test_first_scan_returns_candidate(self):
        """The first scan() call emits the candidate."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(dedup_ttl_min=30)
        pair = make_raw_pair()
        client = make_fake_client([pair])

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1

    async def test_second_scan_deduplicates_within_ttl(self):
        """The second scan() within TTL returns [] for the same mint."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(dedup_ttl_min=30)
        pair = make_raw_pair()
        client = make_fake_client([pair])

        scanner = Scanner(client=client, cfg=cfg)
        await scanner.scan()              # first scan — emits candidate
        results = await scanner.scan()    # second scan — deduped

        assert results == []

    async def test_different_mints_are_not_deduped(self):
        """Two different mints in successive scans are both emitted."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(dedup_ttl_min=30)
        pair1 = make_raw_pair(address="MINT_A", pair_address="PAIR_A")
        pair2 = make_raw_pair(address="MINT_B", pair_address="PAIR_B")

        client1 = make_fake_client([pair1])
        client2 = make_fake_client([pair2])

        scanner = Scanner(client=client1, cfg=cfg)
        r1 = await scanner.scan()

        # Swap the underlying client to simulate second scan with different pair
        scanner._client = client2
        r2 = await scanner.scan()

        assert len(r1) == 1
        assert len(r2) == 1
        assert r1[0].mint == "MINT_A"
        assert r2[0].mint == "MINT_B"

    async def test_ttl_expiry_allows_reemit(self):
        """A mint seen longer than dedup_ttl_min ago is emitted again."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(dedup_ttl_min=30)
        pair = make_raw_pair()

        client = make_fake_client([pair])
        scanner = Scanner(client=client, cfg=cfg)

        # First scan — emits
        r1 = await scanner.scan()
        assert len(r1) == 1

        # Manually expire the seen-set by backdating the entry
        mint = pair["baseToken"]["address"]
        # Set first-seen time to 31 minutes ago (past TTL)
        past_ts = time.time() - (31 * 60)
        scanner._seen[mint] = past_ts

        # Second scan — should emit again because TTL expired
        r2 = await scanner.scan()
        assert len(r2) == 1


# ---------------------------------------------------------------------------
# DataSourceError handling
# ---------------------------------------------------------------------------

class TestDataSourceErrorHandling:
    async def test_datasource_error_returns_empty_list(self):
        """When the client raises DataSourceError, scan() returns [] without propagating."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        client = AsyncMock()
        client.fetch_solana_pairs = AsyncMock(side_effect=DataSourceError("network error"))

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []

    async def test_datasource_error_does_not_raise(self):
        """scan() must never propagate DataSourceError to the caller."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        client = AsyncMock()
        client.fetch_solana_pairs = AsyncMock(side_effect=DataSourceError("boom"))

        scanner = Scanner(client=client, cfg=cfg)
        # Must not raise
        try:
            await scanner.scan()
        except DataSourceError:
            pytest.fail("scan() propagated DataSourceError to caller")


# ---------------------------------------------------------------------------
# Fix 1 — missing baseToken must not crash the scan
# ---------------------------------------------------------------------------

class TestMalformedPairs:
    async def test_missing_base_token_skips_only_bad_pair(self):
        """A batch with one good pair + one pair missing baseToken returns only the good candidate."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        good = make_raw_pair(address="MINT_GOOD", pair_address="PAIR_GOOD")
        # Pair missing baseToken entirely
        bad = {
            "pairAddress": "PAIR_BAD",
            "priceUsd": "0.001",
            "liquidity": {"usd": 25_000.0},
            "fdv": 1_000_000.0,
            "volume": {"m5": 500.0, "h1": 3_000.0},
            "txns": {"m5": {"buys": 20, "sells": 8}},
            "priceChange": {"m5": 3.5},
            "pairCreatedAt": good["pairCreatedAt"],  # same age so it passes prefilter
        }
        client = make_fake_client([good, bad])

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        assert results[0].mint == "MINT_GOOD"


# ---------------------------------------------------------------------------
# Fix 3 — configurable chain
# ---------------------------------------------------------------------------

class TestConfigurableChain:
    async def test_candidate_chain_matches_config(self):
        """TokenCandidate.chain is set from ScannerConfig.chain, not hardcoded."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(chain="ethereum")
        pair = make_raw_pair()
        client = make_fake_client([pair])

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        assert results[0].chain == "ethereum"


# ---------------------------------------------------------------------------
# Fix 10 — naive datetime rejected at model boundary
# ---------------------------------------------------------------------------

class TestAwareDatetimeEnforcement:
    def test_naive_datetime_raises_validation_error(self):
        """TokenCandidate must reject a naive (timezone-unaware) pair_created_at."""
        from datetime import datetime

        import pytest
        from pydantic import ValidationError

        from memedog.models import TokenCandidate

        with pytest.raises(ValidationError):
            TokenCandidate(
                mint="mintABC",
                pair_address="pairXYZ",
                symbol="DOG",
                pair_created_at=datetime(2024, 1, 1, 12, 0, 0),  # naive — no tzinfo
                price_usd=0.0001,
                liquidity_usd=15000.0,
                fdv_usd=500000.0,
                volume_5m=800.0,
                volume_1h=12000.0,
                txns_5m_buys=40,
                txns_5m_sells=10,
                price_change_5m=5.2,
                trace_id="trace-001",
            )
