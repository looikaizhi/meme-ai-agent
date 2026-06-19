"""Tests for Task C: BaseHTTPClient."""
import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx


class TestSuccessfulGet:
    async def test_get_json_returns_parsed_json(self):
        from memedog.clients.base import BaseHTTPClient

        with respx.mock:
            respx.get("https://api.example.com/data").mock(
                return_value=httpx.Response(200, json={"key": "value"})
            )
            async with BaseHTTPClient(base_url="https://api.example.com") as client:
                result = await client.get_json("/data")
        assert result == {"key": "value"}

    async def test_get_json_list_response(self):
        from memedog.clients.base import BaseHTTPClient

        with respx.mock:
            respx.get("https://api.example.com/items").mock(
                return_value=httpx.Response(200, json=[1, 2, 3])
            )
            async with BaseHTTPClient(base_url="https://api.example.com") as client:
                result = await client.get_json("/items")
        assert result == [1, 2, 3]


class TestRetryBehavior:
    async def test_500_then_200_retries_and_succeeds(self):
        """A 500 followed by a 200 should succeed after retry."""
        from memedog.clients.base import BaseHTTPClient

        with respx.mock:
            route = respx.get("https://api.example.com/retry")
            route.side_effect = [
                httpx.Response(500, json={"error": "oops"}),
                httpx.Response(200, json={"ok": True}),
            ]
            # backoff_base=0 → no actual sleep delay
            async with BaseHTTPClient(
                base_url="https://api.example.com", backoff_base=0
            ) as client:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await client.get_json("/retry")
        assert result == {"ok": True}

    async def test_persistent_500_raises_datasource_error(self):
        """Three consecutive 500s should exhaust retries and raise DataSourceError."""
        from memedog.clients.base import BaseHTTPClient, DataSourceError

        with respx.mock:
            respx.get("https://api.example.com/fail").mock(
                return_value=httpx.Response(500, json={"error": "always fails"})
            )
            async with BaseHTTPClient(
                base_url="https://api.example.com", max_retries=3, backoff_base=0
            ) as client:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(DataSourceError):
                        await client.get_json("/fail")


class TestPostJson:
    async def test_post_json_returns_parsed_json(self):
        from memedog.clients.base import BaseHTTPClient

        with respx.mock:
            respx.post("https://api.example.com/create").mock(
                return_value=httpx.Response(200, json={"id": 42})
            )
            async with BaseHTTPClient(base_url="https://api.example.com") as client:
                result = await client.post_json("/create", json={"name": "test"})
        assert result == {"id": 42}


class TestContextManager:
    async def test_can_use_as_async_context_manager(self):
        from memedog.clients.base import BaseHTTPClient

        with respx.mock:
            respx.get("https://api.example.com/ping").mock(
                return_value=httpx.Response(200, json={"pong": True})
            )
            async with BaseHTTPClient(base_url="https://api.example.com") as client:
                result = await client.get_json("/ping")
        assert result["pong"] is True

    async def test_aclose_can_be_called_directly(self):
        from memedog.clients.base import BaseHTTPClient

        client = BaseHTTPClient(base_url="https://api.example.com")
        await client.aclose()  # should not raise


class TestHttpErrorRetry:
    async def test_httpx_error_triggers_retry(self):
        """httpx.HTTPError on first attempt should retry."""
        from memedog.clients.base import BaseHTTPClient, DataSourceError

        call_count = 0

        def side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("connection refused")
            return httpx.Response(200, json={"recovered": True})

        with respx.mock:
            respx.get("https://api.example.com/flaky").mock(side_effect=side_effect)
            async with BaseHTTPClient(
                base_url="https://api.example.com", backoff_base=0
            ) as client:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await client.get_json("/flaky")
        assert result == {"recovered": True}
