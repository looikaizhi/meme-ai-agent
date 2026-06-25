"""Tests for Scanner — discovery-based flow (Task 2).

The Scanner now depends on a client that exposes:
  - async fetch_latest_token_addresses(chain: str) -> list[str]
  - async get_token_pairs(mint: str) -> list[dict]

All tests use a fake async client injected via the constructor.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from memedog.clients.base import DataSourceError
from memedog.config.settings import ScannerConfig
from memedog.models import TokenCandidate

# Load real fixtures at module level for use in fixture-based tests
from tests.conftest import load_fixture as _load_fixture

_BONK_PAIRS = _load_fixture("dexscreener/tokens_bonk.json")["pairs"]
_TOKEN_PROFILES = _load_fixture("dexscreener/token_profiles_latest.json")


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
    chain_id: str = "solana",
    liquidity_usd: float = 25_000.0,
    volume_m5: float = 500.0,
    age_min: float = 15.0,
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
        "chainId": chain_id,
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


def make_fake_client(
    addresses: list[str],
    pairs_by_mint: dict[str, list[dict]],
    *,
    address_error: Exception | None = None,
    pair_errors: dict[str, Exception] | None = None,
) -> AsyncMock:
    """
    Build a fake async client with fetch_latest_token_addresses + get_token_pairs.

    Parameters
    ----------
    addresses:
        Return value of fetch_latest_token_addresses (for all chains).
    pairs_by_mint:
        Map of mint -> list of pair dicts returned by get_token_pairs.
    address_error:
        If set, fetch_latest_token_addresses raises this exception.
    pair_errors:
        Map of mint -> exception to raise from get_token_pairs.
    """
    pair_errors = pair_errors or {}

    async def fake_fetch_latest(chain: str) -> list[str]:
        if address_error is not None:
            raise address_error
        return addresses

    async def fake_get_pairs(mint: str) -> list[dict]:
        if mint in pair_errors:
            raise pair_errors[mint]
        return pairs_by_mint.get(mint, [])

    client = AsyncMock()
    client.fetch_latest_token_addresses = AsyncMock(side_effect=fake_fetch_latest)
    client.get_token_pairs = AsyncMock(side_effect=fake_get_pairs)
    return client


class _FakeStore:
    def __init__(self):
        self.scanner_candidates = []

    def save_scanner_candidate(self, **kwargs):
        self.scanner_candidates.append(kwargs)


# ---------------------------------------------------------------------------
# Prefilter tests
# ---------------------------------------------------------------------------

class TestPrefilter:
    async def test_pair_passing_all_filters_is_returned(self):
        """A pair within age window and above thresholds should be returned."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        pair = make_raw_pair(liquidity_usd=25_000, volume_m5=500, age_min=15)
        client = make_fake_client(
            addresses=["MINT_AAA"],
            pairs_by_mint={"MINT_AAA": [pair]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        assert isinstance(results[0], TokenCandidate)
        assert results[0].mint == "MINT_AAA"

    async def test_passing_candidate_is_persisted_with_discovery_source(self):
        """Only a DexScreener-prefilter-passing candidate is saved to scanner output."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        pair = make_raw_pair(liquidity_usd=25_000, volume_m5=500, age_min=15)
        client = make_fake_client(
            addresses=["MINT_AAA"],
            pairs_by_mint={"MINT_AAA": [pair]},
        )
        client.get_token_metadata = lambda mint: {
            "source": "gmgn_telegram",
            "raw_text": "raw alert",
        }
        store = _FakeStore()

        scanner = Scanner(client=client, cfg=cfg, store=store)
        results = await scanner.scan()

        assert len(results) == 1
        assert len(store.scanner_candidates) == 1
        saved = store.scanner_candidates[0]
        assert saved["candidate"].mint == "MINT_AAA"
        assert saved["candidate"].pair_address == "PAIR_AAA"
        assert saved["source"] == "gmgn_telegram"
        assert saved["raw_text"] == "raw alert"

    async def test_pair_below_liquidity_threshold_is_dropped(self):
        """A pair with liquidity < prefilter_min_liquidity_usd must be dropped."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(prefilter_min_liquidity_usd=10_000.0)
        pair = make_raw_pair(liquidity_usd=2_000.0, age_min=15)
        client = make_fake_client(
            addresses=["MINT_AAA"],
            pairs_by_mint={"MINT_AAA": [pair]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []

    async def test_pair_below_volume_threshold_is_dropped(self):
        """A pair with volume_m5 < prefilter_min_volume_5m must be dropped."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(prefilter_min_volume_5m=100.0)
        pair = make_raw_pair(volume_m5=50.0, age_min=15)
        client = make_fake_client(
            addresses=["MINT_AAA"],
            pairs_by_mint={"MINT_AAA": [pair]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []

    async def test_pair_too_young_is_dropped(self):
        """A pair younger than min_pair_age_min must be dropped."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(min_pair_age_min=5)
        pair = make_raw_pair(age_min=2.0)
        client = make_fake_client(
            addresses=["MINT_AAA"],
            pairs_by_mint={"MINT_AAA": [pair]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []

    async def test_pair_too_old_is_dropped(self):
        """A pair older than max_pair_age_min must be dropped."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(max_pair_age_min=60)
        pair = make_raw_pair(age_min=90.0)
        client = make_fake_client(
            addresses=["MINT_AAA"],
            pairs_by_mint={"MINT_AAA": [pair]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []

    async def test_mixed_pairs_only_passing_ones_returned(self):
        """Only pairs passing all filters are returned in a mixed batch."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        good = make_raw_pair(address="GOOD", pair_address="PAIR_GOOD",
                             liquidity_usd=25_000, volume_m5=500, age_min=15)
        bad_liq = make_raw_pair(address="BAD_LIQ", pair_address="PAIR_BAD_LIQ",
                                liquidity_usd=500, age_min=15)
        bad_age = make_raw_pair(address="BAD_AGE", pair_address="PAIR_BAD_AGE",
                                age_min=120)
        client = make_fake_client(
            addresses=["GOOD", "BAD_LIQ", "BAD_AGE"],
            pairs_by_mint={
                "GOOD": [good],
                "BAD_LIQ": [bad_liq],
                "BAD_AGE": [bad_age],
            },
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        assert results[0].mint == "GOOD"


# ---------------------------------------------------------------------------
# Representative pair selection (highest liquidity Solana pair)
# ---------------------------------------------------------------------------

class TestRepresentativePairSelection:
    async def test_picks_highest_liquidity_solana_pair(self):
        """When a token has multiple solana pairs, the one with highest liquidity wins."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        pair_low = make_raw_pair(
            address="MINT_A", pair_address="PAIR_LOW",
            liquidity_usd=15_000.0, volume_m5=200.0, age_min=20,
        )
        pair_high = make_raw_pair(
            address="MINT_A", pair_address="PAIR_HIGH",
            liquidity_usd=50_000.0, volume_m5=800.0, age_min=20,
        )
        client = make_fake_client(
            addresses=["MINT_A"],
            pairs_by_mint={"MINT_A": [pair_low, pair_high]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        assert results[0].pair_address == "PAIR_HIGH"
        assert results[0].liquidity_usd == pytest.approx(50_000.0)

    async def test_skips_token_when_all_pairs_are_wrong_chain(self):
        """A token whose pairs are all on base-chain (not solana) is skipped."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(chain="solana")
        pair_base = make_raw_pair(
            address="MINT_BASE", pair_address="PAIR_BASE",
            chain_id="base",  # wrong chain
            liquidity_usd=50_000.0, volume_m5=800.0, age_min=20,
        )
        client = make_fake_client(
            addresses=["MINT_BASE"],
            pairs_by_mint={"MINT_BASE": [pair_base]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []

    async def test_uses_only_solana_pairs_when_mixed_chains(self):
        """Among solana + base pairs, only the best solana pair is used."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(chain="solana")
        solana_pair = make_raw_pair(
            address="MINT_MIX", pair_address="PAIR_SOL",
            chain_id="solana",
            liquidity_usd=20_000.0, volume_m5=300.0, age_min=20,
        )
        base_pair = make_raw_pair(
            address="MINT_MIX", pair_address="PAIR_BASE",
            chain_id="base",
            liquidity_usd=999_000.0,  # higher liquidity, but wrong chain
            volume_m5=9999.0, age_min=20,
        )
        client = make_fake_client(
            addresses=["MINT_MIX"],
            pairs_by_mint={"MINT_MIX": [base_pair, solana_pair]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        assert results[0].pair_address == "PAIR_SOL"

    async def test_skips_token_when_no_pairs_returned(self):
        """A token address that yields no pairs is silently skipped."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        client = make_fake_client(
            addresses=["MINT_EMPTY"],
            pairs_by_mint={"MINT_EMPTY": []},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []


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
        client = make_fake_client(
            addresses=["MINT_XYZ"],
            pairs_by_mint={"MINT_XYZ": [pair]},
        )

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
        assert tc.pair_created_at.tzinfo is not None
        assert isinstance(tc.trace_id, str)
        assert len(tc.trace_id) > 0

    async def test_each_candidate_has_unique_trace_id(self):
        """Each TokenCandidate from a single scan() call has a unique trace_id."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        pair1 = make_raw_pair(address="MINT_A", pair_address="PAIR_A")
        pair2 = make_raw_pair(address="MINT_B", pair_address="PAIR_B")
        client = make_fake_client(
            addresses=["MINT_A", "MINT_B"],
            pairs_by_mint={"MINT_A": [pair1], "MINT_B": [pair2]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 2
        trace_ids = {r.trace_id for r in results}
        assert len(trace_ids) == 2


# ---------------------------------------------------------------------------
# Dedup tests
# ---------------------------------------------------------------------------

class TestDedup:
    async def test_first_scan_returns_candidate(self):
        """The first scan() call emits the candidate."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(dedup_ttl_min=30)
        pair = make_raw_pair()
        client = make_fake_client(
            addresses=["MINT_AAA"],
            pairs_by_mint={"MINT_AAA": [pair]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1

    async def test_second_scan_deduplicates_within_ttl(self):
        """The second scan() within TTL returns [] for the same mint."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(dedup_ttl_min=30)
        pair = make_raw_pair()
        client = make_fake_client(
            addresses=["MINT_AAA"],
            pairs_by_mint={"MINT_AAA": [pair]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        await scanner.scan()           # first scan — emits candidate
        results = await scanner.scan() # second scan — deduped

        assert results == []

    async def test_different_mints_are_not_deduped(self):
        """Two different mints in successive scans are both emitted."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(dedup_ttl_min=30)
        pair1 = make_raw_pair(address="MINT_A", pair_address="PAIR_A")
        pair2 = make_raw_pair(address="MINT_B", pair_address="PAIR_B")

        client1 = make_fake_client(
            addresses=["MINT_A"],
            pairs_by_mint={"MINT_A": [pair1]},
        )
        client2 = make_fake_client(
            addresses=["MINT_B"],
            pairs_by_mint={"MINT_B": [pair2]},
        )

        scanner = Scanner(client=client1, cfg=cfg)
        r1 = await scanner.scan()

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
        client = make_fake_client(
            addresses=["MINT_AAA"],
            pairs_by_mint={"MINT_AAA": [pair]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        r1 = await scanner.scan()
        assert len(r1) == 1

        # Manually expire the seen-set by backdating the entry
        mint = pair["baseToken"]["address"]
        past_ts = time.time() - (31 * 60)
        scanner._seen[mint] = past_ts

        r2 = await scanner.scan()
        assert len(r2) == 1

    async def test_already_seen_mint_skips_get_token_pairs_call(self):
        """When a mint is in the dedup cache, get_token_pairs is not called for it."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(dedup_ttl_min=30)
        pair = make_raw_pair()

        call_count = {"n": 0}
        async def counting_get_pairs(mint: str) -> list[dict]:
            call_count["n"] += 1
            return [pair]

        client = AsyncMock()
        client.fetch_latest_token_addresses = AsyncMock(return_value=["MINT_AAA"])
        client.get_token_pairs = AsyncMock(side_effect=counting_get_pairs)

        scanner = Scanner(client=client, cfg=cfg)
        await scanner.scan()          # first — calls get_token_pairs once
        assert call_count["n"] == 1

        await scanner.scan()          # second — MINT_AAA already seen, skip
        assert call_count["n"] == 1   # no additional call


# ---------------------------------------------------------------------------
# DataSourceError handling
# ---------------------------------------------------------------------------

class TestDataSourceErrorHandling:
    async def test_fetch_latest_raises_returns_empty_list(self):
        """When fetch_latest_token_addresses raises DataSourceError, scan() returns []."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        client = make_fake_client(
            addresses=[],
            pairs_by_mint={},
            address_error=DataSourceError("network error"),
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert results == []

    async def test_fetch_latest_raises_does_not_propagate(self):
        """scan() must never propagate DataSourceError from fetch_latest."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        client = make_fake_client(
            addresses=[],
            pairs_by_mint={},
            address_error=DataSourceError("boom"),
        )

        scanner = Scanner(client=client, cfg=cfg)
        try:
            await scanner.scan()
        except DataSourceError:
            pytest.fail("scan() propagated DataSourceError to caller")

    async def test_get_token_pairs_raises_skips_that_token_others_processed(self):
        """When get_token_pairs raises for one mint, the others are still processed."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        good_pair = make_raw_pair(address="MINT_GOOD", pair_address="PAIR_GOOD",
                                  liquidity_usd=25_000, volume_m5=500, age_min=15)
        client = make_fake_client(
            addresses=["MINT_ERR", "MINT_GOOD"],
            pairs_by_mint={"MINT_GOOD": [good_pair]},
            pair_errors={"MINT_ERR": DataSourceError("timeout")},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        assert results[0].mint == "MINT_GOOD"

    async def test_get_token_pairs_raises_does_not_abort_scan(self):
        """A DataSourceError from get_token_pairs for one token does not raise."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        client = make_fake_client(
            addresses=["MINT_A", "MINT_B"],
            pairs_by_mint={},
            pair_errors={
                "MINT_A": DataSourceError("fail A"),
                "MINT_B": DataSourceError("fail B"),
            },
        )

        scanner = Scanner(client=client, cfg=cfg)
        try:
            results = await scanner.scan()
            assert results == []
        except DataSourceError:
            pytest.fail("scan() propagated DataSourceError to caller")


# ---------------------------------------------------------------------------
# Malformed pair / token handling
# ---------------------------------------------------------------------------

class TestMalformedPairs:
    async def test_missing_base_token_skips_only_bad_pair(self):
        """A batch with one good pair + one pair missing baseToken returns only the good candidate."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config()
        good = make_raw_pair(address="MINT_GOOD", pair_address="PAIR_GOOD")
        bad = {
            "chainId": "solana",
            "pairAddress": "PAIR_BAD",
            "priceUsd": "0.001",
            "liquidity": {"usd": 25_000.0},
            "fdv": 1_000_000.0,
            "volume": {"m5": 500.0, "h1": 3_000.0},
            "txns": {"m5": {"buys": 20, "sells": 8}},
            "priceChange": {"m5": 3.5},
            "pairCreatedAt": good["pairCreatedAt"],
        }
        # "MINT_GOOD" returns both; the bad pair is for another address
        client = make_fake_client(
            addresses=["MINT_GOOD", "MINT_BAD"],
            pairs_by_mint={
                "MINT_GOOD": [good],
                "MINT_BAD": [bad],
            },
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        # Only the good pair survives; bad pair has no baseToken so it's skipped
        assert len(results) == 1
        assert results[0].mint == "MINT_GOOD"


# ---------------------------------------------------------------------------
# Configurable chain
# ---------------------------------------------------------------------------

class TestConfigurableChain:
    async def test_candidate_chain_matches_config(self):
        """TokenCandidate.chain is set from ScannerConfig.chain, not hardcoded."""
        from memedog.scanner.scanner import Scanner

        cfg = make_scanner_config(chain="solana")
        pair = make_raw_pair()
        client = make_fake_client(
            addresses=["MINT_AAA"],
            pairs_by_mint={"MINT_AAA": [pair]},
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        assert results[0].chain == "solana"


# ---------------------------------------------------------------------------
# Aware datetime enforcement (model boundary)
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
                pair_created_at=datetime(2024, 1, 1, 12, 0, 0),  # naive
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


# ---------------------------------------------------------------------------
# Real fixture tests — BONK pairs + token_profiles_latest addresses
# ---------------------------------------------------------------------------


class TestRealFixtureData:
    """Tests that drive the scanner with REAL captured DexScreener data."""

    def _patch_pair_age(self, pair: dict, age_min: float = 30.0) -> dict:
        """Return a shallow copy of pair with pairCreatedAt set to age_min minutes ago.

        The real BONK pairs are 2+ years old, so we rewrite pairCreatedAt so
        the prefilter age-window check passes.  All other fields are real.
        """
        now_ms = int(time.time() * 1000)
        patched = dict(pair)
        patched["pairCreatedAt"] = now_ms - int(age_min * 60 * 1000)
        return patched

    async def test_real_token_profiles_addresses_used_as_fetch_latest(self):
        """fetch_latest_token_addresses returns real addresses from token_profiles_latest.json.

        Verifies the client can return all 30 real addresses and the scanner
        calls get_token_pairs for each one (or filters them if chain doesn't match).
        """
        from memedog.scanner.scanner import Scanner

        real_addresses = [p["tokenAddress"] for p in _TOKEN_PROFILES]
        assert len(real_addresses) == 30  # fixture has exactly 30 entries

        # All addresses are Solana and Base; Scanner config is solana-only.
        # For each address we return no pairs so the scan silently skips them.
        client = make_fake_client(
            addresses=real_addresses,
            pairs_by_mint={},  # no pairs → no candidates
        )
        cfg = make_scanner_config(chain="solana")
        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        # No pairs returned → no candidates; but fetch_latest was called
        assert results == []
        client.fetch_latest_token_addresses.assert_called_once_with("solana")
        # get_token_pairs was called for every address
        assert client.get_token_pairs.call_count == len(real_addresses)

    async def test_real_bonk_pairs_parsed_to_token_candidates(self):
        """Real BONK pairs from tokens_bonk.json drive the scanner.

        BONK pairs are old (2024) so we patch pairCreatedAt to pass the age window.
        All pairs are solana → the scanner's chain filter accepts them.
        The scanner picks the highest-liquidity pair; if that pair is missing
        priceChange.m5 (a real-world gap in the fixture), conversion fails and
        the scanner logs a warning + returns [].  We assert that outcome directly.
        The test also verifies the schema key that causes the skip.
        """
        from memedog.scanner.scanner import Scanner

        bonk_mint = _BONK_PAIRS[0]["baseToken"]["address"]  # DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
        assert bonk_mint == "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

        # Patch pairCreatedAt so pairs fall inside the age window
        patched_pairs = [self._patch_pair_age(p, age_min=30.0) for p in _BONK_PAIRS]

        # The highest-liquidity BONK pair (BrMYU1…) has no priceChange.m5 in the
        # real fixture — this is a schema gap in captured data, not a code bug.
        highest_liq_pair = max(
            (p for p in patched_pairs if p.get("chainId") == "solana"),
            key=lambda p: p.get("liquidity", {}).get("usd", 0),
        )
        assert "m5" not in highest_liq_pair.get("priceChange", {}), (
            "Fixture changed: highest-liquidity pair now has m5. Update test assertions."
        )

        client = make_fake_client(
            addresses=[bonk_mint],
            pairs_by_mint={bonk_mint: patched_pairs},
        )
        cfg = make_scanner_config(
            min_pair_age_min=5,
            max_pair_age_min=360,
            prefilter_min_liquidity_usd=1_000.0,
            prefilter_min_volume_5m=0.0,
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        # Scanner picks highest-liq pair, fails conversion (missing priceChange.m5),
        # logs a warning, and returns [] — correct graceful-degradation behaviour.
        assert results == [], (
            "Expected [] because the highest-liquidity BONK pair lacks priceChange.m5"
        )

    async def test_real_bonk_full_schema_pair_converts(self):
        """A real BONK pair that has all required fields converts to a TokenCandidate.

        We take the first BONK pair (6oFWm7…), which has priceChange.m5, and verify
        the scanner maps every field correctly from the real fixture data.
        """
        from memedog.scanner.scanner import Scanner

        bonk_mint = _BONK_PAIRS[0]["baseToken"]["address"]

        # Pick the first pair which has the complete schema (including priceChange.m5)
        first_pair = _BONK_PAIRS[0]
        assert "m5" in first_pair.get("priceChange", {}), (
            "First BONK pair expected to have priceChange.m5 — fixture may have changed."
        )
        patched = self._patch_pair_age(first_pair, age_min=30.0)

        client = make_fake_client(
            addresses=[bonk_mint],
            pairs_by_mint={bonk_mint: [patched]},
        )
        cfg = make_scanner_config(
            min_pair_age_min=5,
            max_pair_age_min=360,
            prefilter_min_liquidity_usd=1_000.0,
            prefilter_min_volume_5m=0.0,
        )

        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        assert len(results) == 1
        tc = results[0]
        assert isinstance(tc, TokenCandidate)
        assert tc.mint == bonk_mint
        assert tc.symbol == "Bonk"
        assert tc.chain == "solana"
        assert tc.pair_address == first_pair["pairAddress"]
        assert tc.price_usd == pytest.approx(float(first_pair["priceUsd"]), rel=1e-4)
        assert tc.liquidity_usd == pytest.approx(first_pair["liquidity"]["usd"], rel=1e-4)
        assert tc.fdv_usd == pytest.approx(float(first_pair["fdv"]), rel=1e-4)
        assert tc.volume_5m == pytest.approx(first_pair["volume"]["m5"], rel=1e-4)
        assert tc.volume_1h == pytest.approx(first_pair["volume"]["h1"], rel=1e-4)
        assert tc.txns_5m_buys == first_pair["txns"]["m5"]["buys"]
        assert tc.txns_5m_sells == first_pair["txns"]["m5"]["sells"]
        assert tc.price_change_5m == pytest.approx(first_pair["priceChange"]["m5"], rel=1e-4)
        assert isinstance(tc.pair_created_at, datetime)
        assert tc.pair_created_at.tzinfo is not None

    async def test_real_profiles_chain_filtering(self):
        """token_profiles_latest.json contains non-solana entries (base, bsc).

        Scanner must skip those — returning pairs marked base/bsc — and only produce
        candidates for solana pairs.  Uses a constructed pair for a known non-solana
        address to verify the filtering path.
        """
        from memedog.scanner.scanner import Scanner

        # Get a known non-solana address from the real fixture
        non_solana = [p for p in _TOKEN_PROFILES if p["chainId"] != "solana"]
        assert len(non_solana) >= 1, "Fixture must contain at least one non-solana entry"
        non_sol_addr = non_solana[0]["tokenAddress"]

        # Give it a pair on "base" (wrong chain) — should be skipped
        base_pair = make_raw_pair(
            address=non_sol_addr,
            pair_address="PAIR_BASE_001",
            chain_id="base",
            liquidity_usd=50_000.0,
            volume_m5=500.0,
            age_min=20.0,
        )

        client = make_fake_client(
            addresses=[non_sol_addr],
            pairs_by_mint={non_sol_addr: [base_pair]},
        )
        cfg = make_scanner_config(chain="solana")
        scanner = Scanner(client=client, cfg=cfg)
        results = await scanner.scan()

        # The non-solana pair must be filtered out
        assert results == []
