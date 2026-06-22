"""Base HTTP client with retry/backoff logic for MemeDog data sources."""
from __future__ import annotations

import asyncio
import logging
import random

import httpx

logger = logging.getLogger(__name__)


class DataSourceError(Exception):
    """Raised when a data source request fails after all retries."""


class BaseHTTPClient:
    """Async HTTP wrapper over httpx.AsyncClient with exponential-backoff retries.

    Parameters
    ----------
    base_url:
        Prepended to every relative URL passed to get_json / post_json.
    timeout:
        Per-request timeout in seconds.
    max_retries:
        Number of attempts (including the first).  A value of 3 means one
        initial attempt plus two retries.
    backoff_base:
        Sleep multiplier: ``backoff_base * 2 ** attempt`` seconds between
        retries.  Set to 0 in tests to avoid real sleeping.
    """

    def __init__(
        self,
        base_url: str = "",
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.2,
        max_backoff: float = 10.0,
        retry_status_codes: list[int] | None = None,
        rate_limiter=None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._max_backoff = max_backoff
        self._retry_status_codes = (
            set(retry_status_codes) if retry_status_codes is not None
            else {429, 500, 502, 503, 504}
        )
        self._rate_limiter = rate_limiter
        self._client = httpx.AsyncClient(timeout=timeout)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_url(self, url: str) -> str:
        if url.startswith("http://") or url.startswith("https://"):
            return url
        if not self._base_url:
            return url
        return self._base_url.rstrip("/") + "/" + url.lstrip("/")

    @staticmethod
    def _parse_retry_after(response: "httpx.Response") -> float | None:
        """Return Retry-After seconds as float, or None if absent/unparseable."""
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> dict | list:
        full_url = self._build_url(url)
        last_exc: Exception | None = None

        for attempt in range(self._max_retries):
            retry_after: float | None = None
            try:
                response = await self._client.request(method, full_url, **kwargs)
                if response.is_success:
                    return response.json()

                status = response.status_code
                # Non-retryable status (e.g. 400/401/403/404) → fail immediately.
                if status not in self._retry_status_codes:
                    raise DataSourceError(
                        f"{method} {full_url} returned {status}: {response.text[:200]}"
                    )

                last_exc = DataSourceError(
                    f"{method} {full_url} returned {status}: {response.text[:200]}"
                )
                if status in (429, 503):
                    retry_after = self._parse_retry_after(response)
                logger.warning(
                    "Attempt %d/%d: %s %s → %d (retryable)",
                    attempt + 1, self._max_retries, method, full_url, status,
                )
            except httpx.HTTPError as exc:
                # Wrap as DataSourceError so the final raise does not leak
                # a raw httpx type as __cause__.
                last_exc = DataSourceError(
                    f"{method} {full_url} raised httpx error: {exc}"
                )
                last_exc.__cause__ = exc  # preserve the original chain
                logger.warning(
                    "Attempt %d/%d: %s %s → httpx error: %s",
                    attempt + 1, self._max_retries, method, full_url, exc,
                )

            # Sleep before next retry (not after the last attempt).
            if attempt < self._max_retries - 1:
                if retry_after is not None:
                    delay = min(retry_after, self._max_backoff)
                else:
                    upper = min(self._backoff_base * (2 ** attempt), self._max_backoff)
                    delay = random.uniform(0, upper)
                if delay > 0:
                    await asyncio.sleep(delay)

        raise DataSourceError(
            f"All {self._max_retries} attempts failed for {method} {full_url}"
        ) from last_exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_json(self, url: str, **kwargs) -> dict | list:
        """Perform a GET request and return parsed JSON."""
        return await self._request("GET", url, **kwargs)

    async def post_json(
        self, url: str, json: dict | None = None, **kwargs
    ) -> dict | list:
        """Perform a POST request with an optional JSON body and return parsed JSON."""
        return await self._request("POST", url, json=json, **kwargs)

    # ------------------------------------------------------------------
    # Resource management
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()

    async def __aenter__(self) -> "BaseHTTPClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.aclose()
