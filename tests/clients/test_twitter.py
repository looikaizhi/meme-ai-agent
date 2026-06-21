"""Task 2 — Tests for TwitterClient.

Uses respx to mock HTTP; no real network calls.
Fixture-driven tests load real/documented-shape responses from tests/fixtures/twitter/
via the `fixture` pytest helper from conftest.py.

Design decision documented here:
  - If bearer_token is None, count_mentions raises DataSourceError
    so the provider layer can mark the dimension as unavailable.
  - This is the cleaner approach: it keeps the unavailability signal
    explicit and avoids silently returning None data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
import respx
import httpx

BEARER = "test-bearer-token"
QUERY = "$DOGE OR #DOGE"
LOOKBACK_MIN = 60

# X/Twitter API v2 recent tweet counts response
COUNTS_RESPONSE = {
    "data": [
        {"end": "2024-01-01T01:00:00.000Z", "start": "2024-01-01T00:00:00.000Z", "tweet_count": 42},
        {"end": "2024-01-01T02:00:00.000Z", "start": "2024-01-01T01:00:00.000Z", "tweet_count": 58},
    ],
    "meta": {"total_tweet_count": 100},
}

# Response with only one bucket
SINGLE_BUCKET_RESPONSE = {
    "data": [
        {"end": "2024-01-01T01:00:00.000Z", "start": "2024-01-01T00:00:00.000Z", "tweet_count": 25},
    ],
    "meta": {"total_tweet_count": 25},
}

# Empty response
ZERO_COUNTS_RESPONSE = {
    "data": [],
    "meta": {"total_tweet_count": 0},
}


class TestNoBearer:
    async def test_no_bearer_raises_datasource_error(self):
        """Without a bearer token, count_mentions must raise DataSourceError."""
        from memedog.clients.twitter import TwitterClient
        from memedog.clients.base import DataSourceError

        async with TwitterClient(bearer_token=None) as client:
            with pytest.raises(DataSourceError, match="twitter bearer"):
                await client.count_mentions(QUERY, LOOKBACK_MIN)

    async def test_no_bearer_does_not_make_network_calls(self):
        """Without a bearer token, no HTTP requests should be made."""
        from memedog.clients.twitter import TwitterClient
        from memedog.clients.base import DataSourceError

        with respx.mock:
            # If any HTTP call is made, respx will raise an error (unexpected call)
            async with TwitterClient(bearer_token=None) as client:
                with pytest.raises(DataSourceError):
                    await client.count_mentions(QUERY, LOOKBACK_MIN)
            # respx.calls would be non-empty if a network call was made
            assert len(respx.calls) == 0


class TestWithBearer:
    async def test_fixture_counts_sample_returns_mentions_and_growth(self, fixture):
        """Serve twitter/counts_sample.json (documented-shape sample, not live-captured).

        NOTE: The fixture body has a _note key explaining it is a documented-shape
        sample because no live X API key was available for capture. Shape follows
        X API v2 /2/tweets/counts/recent.

        Fixture: 2 buckets (tweet_count=12, tweet_count=30), meta.total=42.
        Assert: mentions_1h == 42 (meta.total_tweet_count).
        Assert: growth computed from 2 buckets = (last - first) / max(first, 1) * 100.
        """
        from memedog.clients.twitter import TwitterClient

        # Load the documented-shape sample fixture
        # Body has _note key (which the Twitter API ignores / client should handle)
        counts_data = fixture("twitter/counts_sample.json")

        with respx.mock:
            respx.get("https://api.twitter.com/2/tweets/counts/recent").mock(
                return_value=httpx.Response(200, json=counts_data)
            )
            async with TwitterClient(bearer_token=BEARER) as client:
                result = await client.count_mentions(QUERY, LOOKBACK_MIN)

        # meta.total_tweet_count == 42
        assert result["mentions_1h"] == 42
        # growth = (30 - 12) / max(12, 1) * 100 = 150.0
        expected_growth = (30 - 12) / max(12, 1) * 100
        assert result["growth"] == pytest.approx(expected_growth, rel=1e-3)

    async def test_returns_total_mentions_count(self):
        """With valid bearer and mocked response, returns total from meta."""
        from memedog.clients.twitter import TwitterClient

        with respx.mock:
            respx.get("https://api.twitter.com/2/tweets/counts/recent").mock(
                return_value=httpx.Response(200, json=COUNTS_RESPONSE)
            )
            async with TwitterClient(bearer_token=BEARER) as client:
                result = await client.count_mentions(QUERY, LOOKBACK_MIN)

        assert result["mentions_1h"] == 100
        assert "growth" in result

    async def test_single_bucket_returns_none_growth(self):
        """With only one time bucket, growth cannot be computed → None."""
        from memedog.clients.twitter import TwitterClient

        with respx.mock:
            respx.get("https://api.twitter.com/2/tweets/counts/recent").mock(
                return_value=httpx.Response(200, json=SINGLE_BUCKET_RESPONSE)
            )
            async with TwitterClient(bearer_token=BEARER) as client:
                result = await client.count_mentions(QUERY, LOOKBACK_MIN)

        assert result["mentions_1h"] == 25
        assert result["growth"] is None

    async def test_zero_counts_returns_zero_mentions(self):
        """Empty data array → mentions_1h=0."""
        from memedog.clients.twitter import TwitterClient

        with respx.mock:
            respx.get("https://api.twitter.com/2/tweets/counts/recent").mock(
                return_value=httpx.Response(200, json=ZERO_COUNTS_RESPONSE)
            )
            async with TwitterClient(bearer_token=BEARER) as client:
                result = await client.count_mentions(QUERY, LOOKBACK_MIN)

        assert result["mentions_1h"] == 0

    async def test_growth_computed_from_bucket_trend(self):
        """Growth = (last_bucket - first_bucket) / max(first_bucket, 1) * 100."""
        from memedog.clients.twitter import TwitterClient

        # first=42, last=58 → growth = (58-42)/42 * 100 ≈ 38.1%
        with respx.mock:
            respx.get("https://api.twitter.com/2/tweets/counts/recent").mock(
                return_value=httpx.Response(200, json=COUNTS_RESPONSE)
            )
            async with TwitterClient(bearer_token=BEARER) as client:
                result = await client.count_mentions(QUERY, LOOKBACK_MIN)

        expected_growth = (58 - 42) / 42 * 100
        assert result["growth"] == pytest.approx(expected_growth, rel=1e-3)

    async def test_http_401_raises_datasource_error(self):
        """401 Unauthorized (bad bearer) → DataSourceError."""
        from memedog.clients.twitter import TwitterClient
        from memedog.clients.base import DataSourceError

        with respx.mock:
            respx.get("https://api.twitter.com/2/tweets/counts/recent").mock(
                return_value=httpx.Response(401, json={"title": "Unauthorized"})
            )
            async with TwitterClient(bearer_token=BEARER, max_retries=1) as client:
                with pytest.raises(DataSourceError):
                    await client.count_mentions(QUERY, LOOKBACK_MIN)

    async def test_sends_authorization_header(self):
        """Bearer token must be sent as Authorization: Bearer <token>."""
        from memedog.clients.twitter import TwitterClient

        with respx.mock:
            route = respx.get("https://api.twitter.com/2/tweets/counts/recent").mock(
                return_value=httpx.Response(200, json=SINGLE_BUCKET_RESPONSE)
            )
            async with TwitterClient(bearer_token=BEARER) as client:
                await client.count_mentions(QUERY, LOOKBACK_MIN)

        assert route.called
        request = route.calls.last.request
        assert request.headers.get("authorization") == f"Bearer {BEARER}"

    async def test_start_time_param_sent_for_lookback(self):
        """count_mentions must send start_time param corresponding to ~lookback_min minutes ago."""
        from memedog.clients.twitter import TwitterClient

        before_call = datetime.now(timezone.utc)

        with respx.mock:
            route = respx.get("https://api.twitter.com/2/tweets/counts/recent").mock(
                return_value=httpx.Response(200, json=COUNTS_RESPONSE)
            )
            async with TwitterClient(bearer_token=BEARER) as client:
                await client.count_mentions(QUERY, LOOKBACK_MIN)

        after_call = datetime.now(timezone.utc)

        assert route.called
        request = route.calls.last.request
        qs = parse_qs(urlparse(str(request.url)).query)

        assert "start_time" in qs, "start_time query param must be present"

        sent_start = datetime.fromisoformat(qs["start_time"][0].replace("Z", "+00:00"))

        # The sent start_time should be approximately lookback_min minutes before now.
        # Allow ±5s slack for test execution time.
        expected_earliest = before_call - timedelta(minutes=LOOKBACK_MIN) - timedelta(seconds=5)
        expected_latest = after_call - timedelta(minutes=LOOKBACK_MIN) + timedelta(seconds=5)

        assert expected_earliest <= sent_start <= expected_latest, (
            f"start_time {sent_start} not within expected window "
            f"[{expected_earliest}, {expected_latest}]"
        )
