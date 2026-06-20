"""Tests for Task 1: DexScreenerClient."""
import httpx
import pytest
import respx


SAMPLE_PAIR = {
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


class TestFetchSolanaPairs:
    async def test_returns_list_with_pairs(self):
        """fetch_solana_pairs returns the pairs list from DexScreener response."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {"pairs": [SAMPLE_PAIR]}

        with respx.mock:
            respx.get("https://api.dexscreener.com/latest/dex/search").mock(
                return_value=httpx.Response(200, json=payload)
            )
            async with DexScreenerClient() as client:
                result = await client.fetch_solana_pairs()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["baseToken"]["address"] == "So11111111111111111111111111111111111111112"

    async def test_returns_empty_list_when_no_pairs_key(self):
        """fetch_solana_pairs returns [] when response has no 'pairs' key."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {"schemaVersion": "1.0.0"}

        with respx.mock:
            respx.get("https://api.dexscreener.com/latest/dex/search").mock(
                return_value=httpx.Response(200, json=payload)
            )
            async with DexScreenerClient() as client:
                result = await client.fetch_solana_pairs()

        assert result == []

    async def test_returns_multiple_pairs(self):
        """fetch_solana_pairs returns all pairs in the response."""
        from memedog.clients.dexscreener import DexScreenerClient

        pair2 = dict(SAMPLE_PAIR)
        pair2 = {**SAMPLE_PAIR, "pairAddress": "PAIR456"}
        payload = {"pairs": [SAMPLE_PAIR, pair2]}

        with respx.mock:
            respx.get("https://api.dexscreener.com/latest/dex/search").mock(
                return_value=httpx.Response(200, json=payload)
            )
            async with DexScreenerClient() as client:
                result = await client.fetch_solana_pairs()

        assert len(result) == 2

    async def test_uses_correct_base_url(self):
        """DexScreenerClient uses https://api.dexscreener.com as base URL."""
        from memedog.clients.dexscreener import DexScreenerClient

        client = DexScreenerClient()
        assert client._base_url == "https://api.dexscreener.com"
        await client.aclose()

    async def test_query_includes_solana_param(self):
        """fetch_solana_pairs queries with q=solana."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {"pairs": [SAMPLE_PAIR]}
        captured_request = {}

        def capture(request):
            captured_request["params"] = dict(request.url.params)
            return httpx.Response(200, json=payload)

        with respx.mock:
            respx.get("https://api.dexscreener.com/latest/dex/search").mock(
                side_effect=capture
            )
            async with DexScreenerClient() as client:
                await client.fetch_solana_pairs()

        assert captured_request["params"].get("q") == "solana"

    async def test_returns_empty_list_when_pairs_is_null(self):
        """fetch_solana_pairs returns [] when response has pairs=null (Fix 2)."""
        from memedog.clients.dexscreener import DexScreenerClient

        payload = {"pairs": None}

        with respx.mock:
            respx.get("https://api.dexscreener.com/latest/dex/search").mock(
                return_value=httpx.Response(200, json=payload)
            )
            async with DexScreenerClient() as client:
                result = await client.fetch_solana_pairs()

        assert result == []


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
