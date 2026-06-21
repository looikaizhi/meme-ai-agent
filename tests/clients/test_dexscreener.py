"""Tests for DexScreenerClient — new discovery methods + get_token_price."""
import httpx
import pytest
import respx


SAMPLE_PAIR = {
    "chainId": "solana",
    "baseToken": {"address": "So11111111111111111111111111111111111111112", "symbol": "SOL"},
    "pairAddress": "PAIR123",
    "priceUsd": "1.23",
    "liquidity": {"usd": 50000.0},
    "fdv": 1000000.0,
    "volume": {"m5": 500.0, "h1": 3000.0},
    "txns": {"m5": {"buys": 10, "sells": 5}},
    "priceChange": {"m5": 2.5},
    "pairCreatedAt": 1700000000000,
}


# ---------------------------------------------------------------------------
# Task 1a — fetch_latest_token_addresses
# ---------------------------------------------------------------------------

class TestFetchLatestTokenAddresses:
    """Tests for DexScreenerClient.fetch_latest_token_addresses."""

    PROFILES_URL = "https://api.dexscreener.com/token-profiles/latest/v1"

    async def test_returns_only_matching_chain_addresses(self):
        """fetch_latest_token_addresses filters by chainId — only solana returned."""
        from memedog.clients.dexscreener import DexScreenerClient

        profiles = [
            {"chainId": "solana", "tokenAddress": "ADDR_SOL_1"},
            {"chainId": "base", "tokenAddress": "ADDR_BASE_1"},
            {"chainId": "solana", "tokenAddress": "ADDR_SOL_2"},
            {"chainId": "ethereum", "tokenAddress": "ADDR_ETH_1"},
        ]

        with respx.mock:
            respx.get(self.PROFILES_URL).mock(
                return_value=httpx.Response(200, json=profiles)
            )
            async with DexScreenerClient() as client:
                result = await client.fetch_latest_token_addresses("solana")

        assert result == ["ADDR_SOL_1", "ADDR_SOL_2"]

    async def test_returns_empty_list_when_no_matching_chain(self):
        """Returns [] when no profiles match the requested chain."""
        from memedog.clients.dexscreener import DexScreenerClient

        profiles = [
            {"chainId": "base", "tokenAddress": "ADDR_BASE_1"},
            {"chainId": "ethereum", "tokenAddress": "ADDR_ETH_1"},
        ]

        with respx.mock:
            respx.get(self.PROFILES_URL).mock(
                return_value=httpx.Response(200, json=profiles)
            )
            async with DexScreenerClient() as client:
                result = await client.fetch_latest_token_addresses("solana")

        assert result == []

    async def test_returns_empty_list_when_response_is_not_list(self):
        """Returns [] defensively when response is not a list (e.g. a dict)."""
        from memedog.clients.dexscreener import DexScreenerClient

        with respx.mock:
            respx.get(self.PROFILES_URL).mock(
                return_value=httpx.Response(200, json={"error": "unexpected"})
            )
            async with DexScreenerClient() as client:
                result = await client.fetch_latest_token_addresses("solana")

        assert result == []

    async def test_returns_empty_list_when_profile_missing_keys(self):
        """Profiles missing chainId or tokenAddress are skipped gracefully."""
        from memedog.clients.dexscreener import DexScreenerClient

        profiles = [
            {"chainId": "solana"},                           # missing tokenAddress
            {"tokenAddress": "ADDR_NO_CHAIN"},               # missing chainId
            {"chainId": "solana", "tokenAddress": "GOOD"},   # valid
        ]

        with respx.mock:
            respx.get(self.PROFILES_URL).mock(
                return_value=httpx.Response(200, json=profiles)
            )
            async with DexScreenerClient() as client:
                result = await client.fetch_latest_token_addresses("solana")

        assert result == ["GOOD"]

    async def test_returns_empty_list_on_empty_response(self):
        """Returns [] when server returns an empty list."""
        from memedog.clients.dexscreener import DexScreenerClient

        with respx.mock:
            respx.get(self.PROFILES_URL).mock(
                return_value=httpx.Response(200, json=[])
            )
            async with DexScreenerClient() as client:
                result = await client.fetch_latest_token_addresses("solana")

        assert result == []

    async def test_propagates_data_source_error_on_http_failure(self):
        """fetch_latest_token_addresses raises DataSourceError on HTTP errors."""
        from memedog.clients.base import DataSourceError
        from memedog.clients.dexscreener import DexScreenerClient

        with respx.mock:
            respx.get(self.PROFILES_URL).mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )
            async with DexScreenerClient(max_retries=1) as client:
                with pytest.raises(DataSourceError):
                    await client.fetch_latest_token_addresses("solana")


# ---------------------------------------------------------------------------
# Task 1b — get_token_pairs
# ---------------------------------------------------------------------------

class TestGetTokenPairs:
    """Tests for DexScreenerClient.get_token_pairs."""

    MINT = "So11111111111111111111111111111111111111112"

    def _pairs_url(self):
        return f"https://api.dexscreener.com/latest/dex/tokens/{self.MINT}"

    async def test_returns_pairs_array(self):
        """get_token_pairs returns the pairs list from the API response."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {"pairs": [SAMPLE_PAIR]}

        with respx.mock:
            respx.get(self._pairs_url()).mock(
                return_value=httpx.Response(200, json=payload)
            )
            async with DexScreenerClient() as client:
                result = await client.get_token_pairs(self.MINT)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["pairAddress"] == "PAIR123"

    async def test_returns_empty_list_when_pairs_null(self):
        """get_token_pairs returns [] when pairs is null."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {"pairs": None}

        with respx.mock:
            respx.get(self._pairs_url()).mock(
                return_value=httpx.Response(200, json=payload)
            )
            async with DexScreenerClient() as client:
                result = await client.get_token_pairs(self.MINT)

        assert result == []

    async def test_returns_empty_list_when_pairs_missing(self):
        """get_token_pairs returns [] when response has no 'pairs' key."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {"schemaVersion": "1.0.0"}

        with respx.mock:
            respx.get(self._pairs_url()).mock(
                return_value=httpx.Response(200, json=payload)
            )
            async with DexScreenerClient() as client:
                result = await client.get_token_pairs(self.MINT)

        assert result == []

    async def test_returns_empty_list_when_pairs_empty(self):
        """get_token_pairs returns [] when pairs array is empty."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {"pairs": []}

        with respx.mock:
            respx.get(self._pairs_url()).mock(
                return_value=httpx.Response(200, json=payload)
            )
            async with DexScreenerClient() as client:
                result = await client.get_token_pairs(self.MINT)

        assert result == []

    async def test_returns_empty_list_when_response_not_dict(self):
        """get_token_pairs returns [] when response is not a dict."""
        from memedog.clients.dexscreener import DexScreenerClient

        with respx.mock:
            respx.get(self._pairs_url()).mock(
                return_value=httpx.Response(200, json=[SAMPLE_PAIR])
            )
            async with DexScreenerClient() as client:
                result = await client.get_token_pairs(self.MINT)

        assert result == []

    async def test_propagates_data_source_error_on_http_failure(self):
        """get_token_pairs raises DataSourceError on HTTP errors."""
        from memedog.clients.base import DataSourceError
        from memedog.clients.dexscreener import DexScreenerClient

        with respx.mock:
            respx.get(self._pairs_url()).mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )
            async with DexScreenerClient(max_retries=1) as client:
                with pytest.raises(DataSourceError):
                    await client.get_token_pairs(self.MINT)


# ---------------------------------------------------------------------------
# get_token_price tests (unchanged — keep as-is)
# ---------------------------------------------------------------------------

class TestGetTokenPrice:
    """Tests for DexScreenerClient.get_token_price."""

    MINT = "So11111111111111111111111111111111111111112"

    async def test_returns_float_price_when_pair_present(self):
        """get_token_price returns the float priceUsd from the first pair."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {
            "pairs": [
                {
                    "baseToken": {"address": self.MINT, "symbol": "SOL"},
                    "priceUsd": "42.50",
                }
            ]
        }

        with respx.mock:
            respx.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{self.MINT}"
            ).mock(return_value=httpx.Response(200, json=payload))
            async with DexScreenerClient() as client:
                result = await client.get_token_price(self.MINT)

        assert result == pytest.approx(42.50)

    async def test_returns_none_when_pairs_empty(self):
        """get_token_price returns None when the response has an empty pairs list."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {"pairs": []}

        with respx.mock:
            respx.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{self.MINT}"
            ).mock(return_value=httpx.Response(200, json=payload))
            async with DexScreenerClient() as client:
                result = await client.get_token_price(self.MINT)

        assert result is None

    async def test_returns_none_when_pairs_missing(self):
        """get_token_price returns None when response has no 'pairs' key."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {"schemaVersion": "1.0.0"}

        with respx.mock:
            respx.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{self.MINT}"
            ).mock(return_value=httpx.Response(200, json=payload))
            async with DexScreenerClient() as client:
                result = await client.get_token_price(self.MINT)

        assert result is None

    async def test_returns_none_when_pairs_is_null(self):
        """get_token_price returns None when pairs is null."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {"pairs": None}

        with respx.mock:
            respx.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{self.MINT}"
            ).mock(return_value=httpx.Response(200, json=payload))
            async with DexScreenerClient() as client:
                result = await client.get_token_price(self.MINT)

        assert result is None

    async def test_returns_none_when_price_usd_missing(self):
        """get_token_price returns None when first pair has no priceUsd field."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {
            "pairs": [
                {"baseToken": {"address": self.MINT, "symbol": "SOL"}}
                # no priceUsd
            ]
        }

        with respx.mock:
            respx.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{self.MINT}"
            ).mock(return_value=httpx.Response(200, json=payload))
            async with DexScreenerClient() as client:
                result = await client.get_token_price(self.MINT)

        assert result is None

    async def test_propagates_data_source_error_on_http_failure(self):
        """get_token_price lets DataSourceError propagate on HTTP errors."""
        from memedog.clients.base import DataSourceError
        from memedog.clients.dexscreener import DexScreenerClient

        with respx.mock:
            respx.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{self.MINT}"
            ).mock(return_value=httpx.Response(500, text="Internal Server Error"))
            async with DexScreenerClient(max_retries=1) as client:
                with pytest.raises(DataSourceError):
                    await client.get_token_price(self.MINT)

    async def test_uses_correct_base_url(self):
        """DexScreenerClient uses https://api.dexscreener.com as base URL."""
        from memedog.clients.dexscreener import DexScreenerClient

        client = DexScreenerClient()
        assert client._base_url == "https://api.dexscreener.com"
        await client.aclose()
