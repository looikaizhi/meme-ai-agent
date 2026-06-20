"""Task 1 — Tests for HeliusClient.

RED phase: all tests must fail until HeliusClient is implemented.
Uses respx to mock HTTP; no real network calls.
"""
from __future__ import annotations

import pytest
import respx
import httpx

MINT = "So11111111111111111111111111111111111111112"
API_KEY = "test-api-key-123"
BASE_URL = f"https://mainnet.helius-rpc.com/?api-key={API_KEY}"

# Simulated RPC response: 4 accounts whose uiAmounts are 50, 30, 15, 5 (total 100)
LARGEST_ACCOUNTS_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "context": {"slot": 12345},
        "value": [
            {"address": "Wallet1", "amount": "50000000", "uiAmount": 50.0},
            {"address": "Wallet2", "amount": "30000000", "uiAmount": 30.0},
            {"address": "Wallet3", "amount": "15000000", "uiAmount": 15.0},
            {"address": "Wallet4", "amount": "5000000",  "uiAmount": 5.0},
        ],
    },
}

# Edge case: only one account dominates entirely
SINGLE_WALLET_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "context": {"slot": 1},
        "value": [
            {"address": "BigWallet", "amount": "100000000", "uiAmount": 100.0},
        ],
    },
}

# Edge case: empty value list
EMPTY_ACCOUNTS_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "context": {"slot": 1},
        "value": [],
    },
}

# Edge case: no result key at all (error response)
ERROR_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 1,
    "error": {"code": -32602, "message": "Invalid param"},
}


class TestGetLargestHolders:
    async def test_top10_pct_and_max_wallet_computed_correctly(self):
        """With 4 accounts totaling 100, top10=100%, max_wallet=50%."""
        from memedog.clients.helius import HeliusClient

        with respx.mock:
            respx.post(BASE_URL).mock(
                return_value=httpx.Response(200, json=LARGEST_ACCOUNTS_RESPONSE)
            )
            async with HeliusClient(api_key=API_KEY) as client:
                result = await client.get_largest_holders(MINT)

        # top10 = sum of all 4 accounts / total * 100 = 100%
        assert result["top10_pct"] == pytest.approx(100.0)
        # max_wallet = largest (50) / total (100) * 100 = 50%
        assert result["max_wallet_pct"] == pytest.approx(50.0)

    async def test_holder_count_returns_number_of_accounts(self):
        """holder_count is len of returned accounts (lower bound / rough proxy)."""
        from memedog.clients.helius import HeliusClient

        with respx.mock:
            respx.post(BASE_URL).mock(
                return_value=httpx.Response(200, json=LARGEST_ACCOUNTS_RESPONSE)
            )
            async with HeliusClient(api_key=API_KEY) as client:
                result = await client.get_largest_holders(MINT)

        assert result["holder_count"] == 4

    async def test_single_wallet_is_max(self):
        """When only one wallet holds all supply, max_wallet=100%, top10=100%."""
        from memedog.clients.helius import HeliusClient

        with respx.mock:
            respx.post(BASE_URL).mock(
                return_value=httpx.Response(200, json=SINGLE_WALLET_RESPONSE)
            )
            async with HeliusClient(api_key=API_KEY) as client:
                result = await client.get_largest_holders(MINT)

        assert result["top10_pct"] == pytest.approx(100.0)
        assert result["max_wallet_pct"] == pytest.approx(100.0)
        assert result["holder_count"] == 1

    async def test_empty_accounts_returns_none_values(self):
        """Empty value list → all fields None, no crash."""
        from memedog.clients.helius import HeliusClient

        with respx.mock:
            respx.post(BASE_URL).mock(
                return_value=httpx.Response(200, json=EMPTY_ACCOUNTS_RESPONSE)
            )
            async with HeliusClient(api_key=API_KEY) as client:
                result = await client.get_largest_holders(MINT)

        assert result["top10_pct"] is None
        assert result["max_wallet_pct"] is None
        # holder_count may be 0 or None — either is acceptable for empty list
        assert result["holder_count"] in (0, None)

    async def test_error_response_returns_none_values(self):
        """RPC error body (no result key) → None values, no crash."""
        from memedog.clients.helius import HeliusClient

        with respx.mock:
            respx.post(BASE_URL).mock(
                return_value=httpx.Response(200, json=ERROR_RESPONSE)
            )
            async with HeliusClient(api_key=API_KEY) as client:
                result = await client.get_largest_holders(MINT)

        assert result["top10_pct"] is None
        assert result["max_wallet_pct"] is None
        assert result["holder_count"] is None

    async def test_top10_only_sums_top_10_when_more_than_10_accounts(self):
        """When more than 10 accounts returned, top10_pct uses only the first 10."""
        from memedog.clients.helius import HeliusClient

        # 12 accounts: first 10 each have uiAmount=10; last 2 have uiAmount=5
        accounts = [{"address": f"W{i}", "amount": "10000000", "uiAmount": 10.0}
                    for i in range(10)]
        accounts += [{"address": "W10", "amount": "5000000", "uiAmount": 5.0},
                     {"address": "W11", "amount": "5000000", "uiAmount": 5.0}]
        total = 10 * 10.0 + 2 * 5.0  # 110
        response = {"jsonrpc": "2.0", "id": 1, "result": {"context": {}, "value": accounts}}

        with respx.mock:
            respx.post(BASE_URL).mock(
                return_value=httpx.Response(200, json=response)
            )
            async with HeliusClient(api_key=API_KEY) as client:
                result = await client.get_largest_holders(MINT)

        # top10 = 100 / 110 * 100
        expected_top10 = 100.0 / 110.0 * 100.0
        assert result["top10_pct"] == pytest.approx(expected_top10)

    async def test_http_error_raises_datasource_error(self):
        """Non-2xx HTTP response → DataSourceError raised."""
        from memedog.clients.helius import HeliusClient
        from memedog.clients.base import DataSourceError

        with respx.mock:
            respx.post(BASE_URL).mock(
                return_value=httpx.Response(500, json={"error": "server error"})
            )
            async with HeliusClient(api_key=API_KEY, max_retries=1) as client:
                with pytest.raises(DataSourceError):
                    await client.get_largest_holders(MINT)


class TestCountSmartMoneyBuys:
    async def test_empty_smart_wallets_returns_zero(self):
        """When no smart wallets configured, return 0 without network call."""
        from memedog.clients.helius import HeliusClient

        async with HeliusClient(api_key=API_KEY) as client:
            result = await client.count_smart_money_buys(MINT, set())

        assert result == 0

    async def test_smart_wallets_with_no_matches_returns_zero(self):
        """Smart wallets configured but none appear in recent transfers → 0."""
        from memedog.clients.helius import HeliusClient

        # Mock the enhanced transactions endpoint with no matching wallets
        tx_response = [
            {
                "signature": "sig1",
                "tokenTransfers": [
                    {"toUserAccount": "UnknownWallet", "mint": MINT}
                ],
            }
        ]
        smart_wallets = {"KnownSmartWallet1", "KnownSmartWallet2"}

        with respx.mock:
            respx.get(
                f"https://api.helius.xyz/v0/addresses/{MINT}/transactions?api-key={API_KEY}&type=TRANSFER"
            ).mock(return_value=httpx.Response(200, json=tx_response))
            async with HeliusClient(api_key=API_KEY) as client:
                result = await client.count_smart_money_buys(MINT, smart_wallets)

        assert result == 0

    async def test_smart_wallet_match_counts_correctly(self):
        """When a smart wallet appears as buyer, count is incremented."""
        from memedog.clients.helius import HeliusClient

        smart_wallet = "SmartWalletABC"
        tx_response = [
            {
                "signature": "sig1",
                "tokenTransfers": [
                    {"toUserAccount": smart_wallet, "mint": MINT}
                ],
            },
            {
                "signature": "sig2",
                "tokenTransfers": [
                    {"toUserAccount": "RandomWallet", "mint": MINT}
                ],
            },
        ]

        with respx.mock:
            respx.get(
                f"https://api.helius.xyz/v0/addresses/{MINT}/transactions?api-key={API_KEY}&type=TRANSFER"
            ).mock(return_value=httpx.Response(200, json=tx_response))
            async with HeliusClient(api_key=API_KEY) as client:
                result = await client.count_smart_money_buys(MINT, {smart_wallet})

        assert result == 1

    async def test_network_error_returns_none(self):
        """On network failure in smart money query, return None (best-effort)."""
        from memedog.clients.helius import HeliusClient

        with respx.mock:
            respx.get(
                f"https://api.helius.xyz/v0/addresses/{MINT}/transactions?api-key={API_KEY}&type=TRANSFER"
            ).mock(return_value=httpx.Response(500, json={"error": "server error"}))
            async with HeliusClient(api_key=API_KEY, max_retries=1) as client:
                result = await client.count_smart_money_buys(MINT, {"SomeSmartWallet"})

        assert result is None
