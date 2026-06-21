"""Tests for RugCheckClient and parse_report.

Tests use respx to mock HTTP; no real network calls.
parse_report tests load the real BONK fixture (tests/fixtures/rugcheck_bonk.json)
to assert against verified live-API field names and values.
"""
from __future__ import annotations

import json
import pathlib

import httpx
import pytest
import respx

# ---------------------------------------------------------------------------
# Load real BONK fixture
# ---------------------------------------------------------------------------

_FIXTURE_PATH = pathlib.Path(__file__).parent.parent / "fixtures" / "rugcheck_bonk.json"
BONK_REPORT = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Synthetic fixtures for edge-case tests
# ---------------------------------------------------------------------------

# A sparse report with almost nothing — tests defensive fallback
SPARSE_REPORT: dict = {
    "mint": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
}

# A report where mintAuthority is an active pubkey (not revoked)
ACTIVE_MINT_AUTHORITY_REPORT: dict = {
    "mintAuthority": "SomeActiveAuthority999",
    "freezeAuthority": None,
    "score_normalised": 30,
    "rugged": False,
    "topHolders": [{"address": "x", "pct": 5.0, "uiAmount": 100, "owner": "y", "insider": False}],
    "markets": [{"lp": {"lpLockedPct": 0}}],
    "token": {"supply": 1_000_000, "decimals": 6, "mintAuthority": "SomeActiveAuthority999", "freezeAuthority": None},
    "creator": "creator1",
    "creatorBalance": 10_000,
}

# A report with a market that has lpLockedPct >= 90 → lp_burned_or_locked = True
LP_LOCKED_REPORT: dict = {
    "mintAuthority": None,
    "freezeAuthority": None,
    "score_normalised": 5,
    "rugged": False,
    "topHolders": [],
    "markets": [
        {"lp": {"lpLockedPct": 100}},  # fully locked
    ],
    "token": {"supply": 1_000_000, "decimals": 6, "mintAuthority": None, "freezeAuthority": None},
    "creator": "creator2",
    "creatorBalance": 0,
}

# A rugged token → risk_level "CRITICAL"
RUGGED_REPORT: dict = {
    "mintAuthority": "ActiveKey",
    "freezeAuthority": "ActiveKey",
    "score_normalised": 80,
    "rugged": True,
    "topHolders": [],
    "markets": [],
    "token": {"supply": 1_000_000, "decimals": 6, "mintAuthority": "ActiveKey", "freezeAuthority": "ActiveKey"},
    "creator": "creator3",
    "creatorBalance": 0,
}


# ---------------------------------------------------------------------------
# get_token_report — network layer (unchanged behavior)
# ---------------------------------------------------------------------------


class TestGetTokenReport:
    async def test_returns_parsed_json_for_valid_mint(self):
        from memedog.clients.rugcheck import RugCheckClient

        mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        with respx.mock:
            respx.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report").mock(
                return_value=httpx.Response(200, json=BONK_REPORT)
            )
            async with RugCheckClient() as client:
                result = await client.get_token_report(mint)

        assert result["mint"] == mint
        assert result["score"] == 101

    async def test_raises_datasource_error_on_404(self):
        from memedog.clients.base import DataSourceError
        from memedog.clients.rugcheck import RugCheckClient

        mint = "BADMINTADDRESS"
        with respx.mock:
            respx.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report").mock(
                return_value=httpx.Response(404, json={"error": "not found"})
            )
            async with RugCheckClient(max_retries=1) as client:
                with pytest.raises(DataSourceError):
                    await client.get_token_report(mint)

    async def test_raises_datasource_error_on_500(self):
        from memedog.clients.base import DataSourceError
        from memedog.clients.rugcheck import RugCheckClient

        mint = "SOMEMINT123"
        with respx.mock:
            respx.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report").mock(
                return_value=httpx.Response(500, json={"error": "server error"})
            )
            async with RugCheckClient(max_retries=1, backoff_base=0) as client:
                with pytest.raises(DataSourceError):
                    await client.get_token_report(mint)


# ---------------------------------------------------------------------------
# parse_report — BONK real-data assertions
# ---------------------------------------------------------------------------


class TestParseReportBonk:
    """Assert against values verified live against api.rugcheck.xyz (BONK token)."""

    def test_mint_authority_revoked_true(self):
        """BONK mintAuthority is null → revoked = True."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(BONK_REPORT)
        assert result["mint_authority_revoked"] is True

    def test_freeze_authority_revoked_true(self):
        """BONK freezeAuthority is null → revoked = True."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(BONK_REPORT)
        assert result["freeze_authority_revoked"] is True

    def test_trust_score_equals_93(self):
        """BONK score_normalised=7 → trust = 100-7 = 93."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(BONK_REPORT)
        assert result["trust_score"] == 93

    def test_risk_level_low(self):
        """BONK score_normalised=7 → risk_level 'LOW'."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(BONK_REPORT)
        assert result["risk_level"] == "LOW"

    def test_lp_burned_or_locked_false(self):
        """BONK lpLockedPct=0 → lp_burned_or_locked = False."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(BONK_REPORT)
        assert result["lp_burned_or_locked"] is False

    def test_max_wallet_pct_approx(self):
        """BONK largest holder pct ≈ 7.951234087754192."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(BONK_REPORT)
        assert result["max_wallet_pct"] == pytest.approx(7.951234087754192)

    def test_top10_pct_sum(self):
        """top10_pct = sum of first 10 holders from BONK fixture."""
        from memedog.clients.rugcheck import parse_report

        expected = sum(h["pct"] for h in BONK_REPORT["topHolders"][:10])
        result = parse_report(BONK_REPORT)
        assert result["top10_pct"] == pytest.approx(expected)

    def test_sniper_pct_zero(self):
        """BONK has no insider holders → sniper_pct == 0.0."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(BONK_REPORT)
        assert result["sniper_pct"] == pytest.approx(0.0)

    def test_dev_pct_small_positive(self):
        """BONK creatorBalance=14608186413, supply=8799471848022988767 → tiny dev_pct."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(BONK_REPORT)
        assert result["dev_pct"] is not None
        expected = 14608186413 / 8799471848022988767 * 100
        assert result["dev_pct"] == pytest.approx(expected)
        assert 0 < result["dev_pct"] < 1  # very small percentage

    def test_all_keys_present(self):
        """All nine output keys must be present regardless of input."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(BONK_REPORT)
        required_keys = {
            "mint_authority_revoked",
            "freeze_authority_revoked",
            "lp_burned_or_locked",
            "top10_pct",
            "max_wallet_pct",
            "dev_pct",
            "sniper_pct",
            "trust_score",
            "risk_level",
        }
        assert required_keys == set(result.keys())


# ---------------------------------------------------------------------------
# parse_report — edge case / synthetic tests
# ---------------------------------------------------------------------------


class TestParseReportEdgeCases:
    def test_sparse_report_returns_none_for_missing_fields(self):
        """Missing fields must become None — no crash."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(SPARSE_REPORT)
        assert result["mint_authority_revoked"] is None
        assert result["freeze_authority_revoked"] is None
        assert result["lp_burned_or_locked"] is None
        assert result["top10_pct"] is None
        assert result["max_wallet_pct"] is None
        assert result["dev_pct"] is None
        assert result["sniper_pct"] is None
        assert result["trust_score"] is None
        assert result["risk_level"] is None

    def test_empty_dict_does_not_crash(self):
        """An entirely empty dict must not crash."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report({})
        assert isinstance(result, dict)
        assert result["trust_score"] is None

    def test_active_mint_authority_gives_false(self):
        """Non-null mintAuthority → mint_authority_revoked = False."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(ACTIVE_MINT_AUTHORITY_REPORT)
        assert result["mint_authority_revoked"] is False

    def test_lp_locked_pct_100_gives_true(self):
        """lpLockedPct >= 90 → lp_burned_or_locked = True."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(LP_LOCKED_REPORT)
        assert result["lp_burned_or_locked"] is True

    def test_lp_locked_pct_exactly_90_gives_true(self):
        """lpLockedPct == 90 is the boundary → True."""
        from memedog.clients.rugcheck import parse_report

        report = {
            **LP_LOCKED_REPORT,
            "markets": [{"lp": {"lpLockedPct": 90}}],
        }
        result = parse_report(report)
        assert result["lp_burned_or_locked"] is True

    def test_lp_locked_pct_89_gives_false(self):
        """lpLockedPct=89 < 90 → lp_burned_or_locked = False."""
        from memedog.clients.rugcheck import parse_report

        report = {
            **LP_LOCKED_REPORT,
            "markets": [{"lp": {"lpLockedPct": 89}}],
        }
        result = parse_report(report)
        assert result["lp_burned_or_locked"] is False

    def test_market_missing_lp_key_treated_as_zero(self):
        """A market dict without 'lp' key → treated as lpLockedPct=0 (not locked)."""
        from memedog.clients.rugcheck import parse_report

        report = {**LP_LOCKED_REPORT, "markets": [{}]}
        result = parse_report(report)
        assert result["lp_burned_or_locked"] is False

    def test_rugged_true_gives_critical_risk_level(self):
        """rugged=True → risk_level 'CRITICAL' regardless of score."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(RUGGED_REPORT)
        assert result["risk_level"] == "CRITICAL"

    def test_score_normalised_50_gives_high_risk(self):
        """score_normalised=50 → risk_level 'HIGH'."""
        from memedog.clients.rugcheck import parse_report

        report = {**SPARSE_REPORT, "score_normalised": 50, "rugged": False}
        result = parse_report(report)
        assert result["risk_level"] == "HIGH"

    def test_score_normalised_20_gives_medium_risk(self):
        """score_normalised=20 → risk_level 'MEDIUM'."""
        from memedog.clients.rugcheck import parse_report

        report = {**SPARSE_REPORT, "score_normalised": 20, "rugged": False}
        result = parse_report(report)
        assert result["risk_level"] == "MEDIUM"

    def test_score_normalised_10_gives_low_risk(self):
        """score_normalised=10 → risk_level 'LOW'."""
        from memedog.clients.rugcheck import parse_report

        report = {**SPARSE_REPORT, "score_normalised": 10, "rugged": False}
        result = parse_report(report)
        assert result["risk_level"] == "LOW"

    def test_trust_score_clamped_to_zero_on_high_risk(self):
        """score_normalised=110 → trust clamped to 0 (not negative)."""
        from memedog.clients.rugcheck import parse_report

        report = {**SPARSE_REPORT, "score_normalised": 110, "rugged": False}
        result = parse_report(report)
        assert result["trust_score"] == 0

    def test_empty_markets_list_gives_none(self):
        """Empty markets list → lp_burned_or_locked = None."""
        from memedog.clients.rugcheck import parse_report

        report = {**SPARSE_REPORT, "markets": []}
        result = parse_report(report)
        assert result["lp_burned_or_locked"] is None

    def test_insider_holders_sum_as_sniper_pct(self):
        """Holders with insider=True → their pct summed as sniper_pct."""
        from memedog.clients.rugcheck import parse_report

        report = {
            **SPARSE_REPORT,
            "topHolders": [
                {"address": "a", "pct": 5.0, "uiAmount": 100, "owner": "x", "insider": True},
                {"address": "b", "pct": 3.0, "uiAmount": 50, "owner": "y", "insider": False},
                {"address": "c", "pct": 2.0, "uiAmount": 20, "owner": "z", "insider": True},
            ],
        }
        result = parse_report(report)
        # insider sum = 5.0 + 2.0
        assert result["sniper_pct"] == pytest.approx(7.0)
        # sniper_pct does NOT include the non-insider holder
        assert result["sniper_pct"] != pytest.approx(10.0)
