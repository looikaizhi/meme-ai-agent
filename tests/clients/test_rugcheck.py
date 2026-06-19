"""Task 2 — Tests for RugCheckClient.

RED phase: write failing tests first.
Tests use respx to mock HTTP; no real network calls.
"""
from __future__ import annotations

import pytest
import respx
import httpx


# ---------------------------------------------------------------------------
# Fixtures — sample RugCheck report payloads
# ---------------------------------------------------------------------------

FULL_REPORT = {
    "mint": "So11111111111111111111111111111111111111112",
    "mintAuthority": None,  # revoked if None
    "freezeAuthority": None,  # revoked if None
    "risks": [],
    "score": 85,
    "riskLevel": "low",
    "markets": [
        {
            "liquidityA": 50000,
            "liquidityB": 50000,
            "lpBurned": True,
            "lpLocked": False,
        }
    ],
    "topHolders": [
        {"pct": 5.0},
        {"pct": 4.5},
        {"pct": 3.0},
        {"pct": 2.5},
        {"pct": 2.0},
        {"pct": 1.8},
        {"pct": 1.5},
        {"pct": 1.2},
        {"pct": 1.0},
        {"pct": 0.9},
    ],
    "insiders": {"devPct": 3.5, "sniperPct": 8.0},
    "largestWalletPct": 5.0,
}

# A minimal report with most fields absent (tests defensive fallback)
SPARSE_REPORT = {
    "mint": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
}


# ---------------------------------------------------------------------------
# get_token_report — network layer
# ---------------------------------------------------------------------------


class TestGetTokenReport:
    async def test_returns_parsed_json_for_valid_mint(self):
        from memedog.clients.rugcheck import RugCheckClient

        mint = "So11111111111111111111111111111111111111112"
        with respx.mock:
            respx.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report").mock(
                return_value=httpx.Response(200, json=FULL_REPORT)
            )
            async with RugCheckClient() as client:
                result = await client.get_token_report(mint)

        assert result["mint"] == mint
        assert result["score"] == 85

    async def test_raises_datasource_error_on_404(self):
        from memedog.clients.rugcheck import RugCheckClient
        from memedog.clients.base import DataSourceError

        mint = "BADMINTADDRESS"
        with respx.mock:
            respx.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report").mock(
                return_value=httpx.Response(404, json={"error": "not found"})
            )
            async with RugCheckClient(max_retries=1) as client:
                with pytest.raises(DataSourceError):
                    await client.get_token_report(mint)

    async def test_raises_datasource_error_on_500(self):
        from memedog.clients.rugcheck import RugCheckClient
        from memedog.clients.base import DataSourceError

        mint = "SOMEMINT123"
        with respx.mock:
            respx.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report").mock(
                return_value=httpx.Response(500, json={"error": "server error"})
            )
            async with RugCheckClient(max_retries=1, backoff_base=0) as client:
                with pytest.raises(DataSourceError):
                    await client.get_token_report(mint)


# ---------------------------------------------------------------------------
# parse_report — normalization
# ---------------------------------------------------------------------------


class TestParseReport:
    def test_full_report_extracts_all_fields(self):
        from memedog.clients.rugcheck import parse_report

        result = parse_report(FULL_REPORT)

        # Authority: None mintAuthority → revoked = True
        assert result["mint_authority_revoked"] is True
        # None freezeAuthority → revoked = True
        assert result["freeze_authority_revoked"] is True
        # lpBurned=True on first market → lp_burned_or_locked = True
        assert result["lp_burned_or_locked"] is True
        # top10 = sum of top 10 holder pcts
        expected_top10 = sum(h["pct"] for h in FULL_REPORT["topHolders"])
        assert result["top10_pct"] == pytest.approx(expected_top10)
        # largest wallet
        assert result["max_wallet_pct"] == pytest.approx(5.0)
        # dev and sniper
        assert result["dev_pct"] == pytest.approx(3.5)
        assert result["sniper_pct"] == pytest.approx(8.0)
        # trust score and risk level
        assert result["trust_score"] == 85
        assert result["risk_level"] == "low"

    def test_sparse_report_returns_none_for_missing_fields(self):
        """Missing fields must become None — no crash."""
        from memedog.clients.rugcheck import parse_report

        result = parse_report(SPARSE_REPORT)

        # All optional fields default to None
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

    def test_lp_locked_flag_detected(self):
        """If lpLocked=True (instead of lpBurned) it should still return True."""
        from memedog.clients.rugcheck import parse_report

        report = {
            **FULL_REPORT,
            "markets": [{"lpBurned": False, "lpLocked": True}],
        }
        result = parse_report(report)
        assert result["lp_burned_or_locked"] is True

    def test_lp_neither_burned_nor_locked_returns_false(self):
        from memedog.clients.rugcheck import parse_report

        report = {
            **FULL_REPORT,
            "markets": [{"lpBurned": False, "lpLocked": False}],
        }
        result = parse_report(report)
        assert result["lp_burned_or_locked"] is False

    def test_non_none_mint_authority_is_active(self):
        """A non-None mintAuthority means authority is NOT revoked → False."""
        from memedog.clients.rugcheck import parse_report

        report = {**FULL_REPORT, "mintAuthority": "SomeActiveAuthority"}
        result = parse_report(report)
        assert result["mint_authority_revoked"] is False

    def test_non_none_freeze_authority_is_active(self):
        from memedog.clients.rugcheck import parse_report

        report = {**FULL_REPORT, "freezeAuthority": "SomeActiveAuthority"}
        result = parse_report(report)
        assert result["freeze_authority_revoked"] is False
