"""Twitter/X API v2 client for social mention tracking.

Design decision on missing bearer token:
  If bearer_token is None, count_mentions raises DataSourceError immediately.
  This is the cleaner approach because:
    1. It makes the unavailability explicit and traceable in logs.
    2. The caller (fetch_social provider) catches DataSourceError to mark
       the twitter sub-source as unavailable — no special None-check needed.
    3. No ambiguity between "configured but returned 0 mentions" vs "not configured".
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from memedog.clients.base import BaseHTTPClient, DataSourceError

logger = logging.getLogger(__name__)

_TWITTER_BASE = "https://api.twitter.com"
_COUNTS_ENDPOINT = "/2/tweets/counts/recent"


class TwitterClient(BaseHTTPClient):
    """HTTP client for the X/Twitter API v2 recent-counts endpoint.

    Parameters
    ----------
    bearer_token:
        OAuth 2.0 bearer token. If None, count_mentions raises DataSourceError.
    **kwargs:
        Forwarded to BaseHTTPClient (timeout, max_retries, backoff_base).
    """

    def __init__(self, bearer_token: Optional[str], **kwargs) -> None:
        self._bearer_token = bearer_token
        kwargs.setdefault("base_url", _TWITTER_BASE)
        super().__init__(**kwargs)

    async def count_mentions(self, query: str, lookback_min: int) -> dict:
        """Count recent tweet mentions for *query* over the past *lookback_min* minutes.

        Calls GET /2/tweets/counts/recent with granularity=minute (aggregated).

        Returns
        -------
        dict with keys:
          mentions_1h: int | None  — total tweet count from meta.total_tweet_count
          growth:      float | None — (last_bucket - first_bucket) / first_bucket * 100
                                     None when fewer than 2 buckets available

        Raises
        ------
        DataSourceError
            If bearer_token is not configured, or on HTTP/network failure.
        """
        if self._bearer_token is None:
            raise DataSourceError(
                "twitter bearer not configured — social twitter dimension unavailable"
            )

        headers = {"authorization": f"Bearer {self._bearer_token}"}
        start_time = datetime.now(timezone.utc) - timedelta(minutes=lookback_min)
        params = {
            "query": query,
            "granularity": "hour",
            "start_time": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        raw = await self.get_json(
            _COUNTS_ENDPOINT,
            headers=headers,
            params=params,
        )

        buckets = raw.get("data", [])
        meta_total = raw.get("meta", {}).get("total_tweet_count", 0)

        if not buckets:
            return {"mentions_1h": meta_total, "growth": None}

        mentions_1h: int = meta_total

        # Growth: compare first and last time bucket
        growth: Optional[float] = None
        if len(buckets) >= 2:
            first_count = buckets[0].get("tweet_count", 0)
            last_count = buckets[-1].get("tweet_count", 0)
            denominator = max(first_count, 1)
            growth = (last_count - first_count) / denominator * 100.0

        return {"mentions_1h": mentions_1h, "growth": growth}
