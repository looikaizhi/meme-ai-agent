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
        """Three consecutive 500s should exhaust retries and raise DataSourceError.

        The implementation makes exactly max_retries total attempts (including
        the first), so route.call_count must equal max_retries after failure.
        """
        from memedog.clients.base import BaseHTTPClient, DataSourceError

        with respx.mock:
            route = respx.get("https://api.example.com/fail").mock(
                return_value=httpx.Response(500, json={"error": "always fails"})
            )
            async with BaseHTTPClient(
                base_url="https://api.example.com", max_retries=3, backoff_base=0
            ) as client:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(DataSourceError):
                        await client.get_json("/fail")
            # The client makes exactly max_retries total attempts (1 initial + 2 retries)
            assert route.call_count == 3


class TestExponentialBackoff:
    async def test_sleep_called_with_exponential_delays(self):
        """On a 3-attempt run with backoff_base=0.01 the delays must be 0.01 then 0.02.

        The implementation sleeps *before* each retry (not after the last
        attempt), so for max_retries=3 there are exactly 2 sleep calls:
          attempt 0 → sleep(0.01 * 2**0) = sleep(0.01)
          attempt 1 → sleep(0.01 * 2**1) = sleep(0.02)
          attempt 2 → last attempt, no sleep
        """
        from memedog.clients.base import BaseHTTPClient, DataSourceError

        with respx.mock:
            respx.get("https://api.example.com/slow").mock(
                return_value=httpx.Response(500, json={"error": "always fails"})
            )
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                async with BaseHTTPClient(
                    base_url="https://api.example.com",
                    max_retries=3,
                    backoff_base=0.01,
                ) as client:
                    with pytest.raises(DataSourceError):
                        await client.get_json("/slow")

        # Must have slept exactly twice with exponential delays
        assert mock_sleep.call_count == 2
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays[0] == pytest.approx(0.01)
        assert delays[1] == pytest.approx(0.02)


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


class TestBuildUrl:
    def test_url_with_leading_slash_joins_correctly(self):
        """A url starting with / must join to base_url without double slash."""
        from memedog.clients.base import BaseHTTPClient

        client = BaseHTTPClient(base_url="https://api.example.com")
        assert client._build_url("/data") == "https://api.example.com/data"

    def test_url_without_leading_slash_joins_correctly(self):
        """A url WITHOUT a leading slash must still insert a separator slash."""
        from memedog.clients.base import BaseHTTPClient

        client = BaseHTTPClient(base_url="https://api.example.com")
        assert client._build_url("data") == "https://api.example.com/data"

    def test_absolute_url_returned_unchanged(self):
        """An absolute http(s) URL must pass through unchanged."""
        from memedog.clients.base import BaseHTTPClient

        client = BaseHTTPClient(base_url="https://api.example.com")
        assert client._build_url("https://other.com/x") == "https://other.com/x"

    def test_no_base_url_returns_url_unchanged(self):
        """When base_url is empty, url is returned as-is."""
        from memedog.clients.base import BaseHTTPClient

        client = BaseHTTPClient(base_url="")
        assert client._build_url("data") == "data"


class TestHttpxErrorWrapped:
    async def test_httpx_error_wrapped_as_datasource_error(self):
        """When all retries fail with httpx.HTTPError, the final raise must be
        DataSourceError whose __cause__ is also DataSourceError (not bare httpx).
        """
        from memedog.clients.base import BaseHTTPClient, DataSourceError

        with respx.mock:
            respx.get("https://api.example.com/broken").mock(
                side_effect=httpx.ConnectError("refused")
            )
            async with BaseHTTPClient(
                base_url="https://api.example.com", max_retries=2, backoff_base=0
            ) as client:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(DataSourceError) as exc_info:
                        await client.get_json("/broken")

        # The __cause__ must be a DataSourceError, not a raw httpx exception
        assert isinstance(exc_info.value.__cause__, DataSourceError)


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
