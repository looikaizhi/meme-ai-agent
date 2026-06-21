"""DexScreener API client for MemeDog Radar."""
from __future__ import annotations

import logging
from typing import Optional

from memedog.clients.base import BaseHTTPClient

logger = logging.getLogger(__name__)

_TOKEN_PROFILES_PATH = "/token-profiles/latest/v1"
_TOKEN_PAIRS_PATH = "/latest/dex/tokens/{mint}"


class DexScreenerClient(BaseHTTPClient):
    """Client for the DexScreener public API.

    Provides token discovery via the token-profiles endpoint and
    per-token pair data via the tokens endpoint.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(base_url="https://api.dexscreener.com", **kwargs)

    async def fetch_latest_token_addresses(self, chain: str) -> list[str]:
        """Fetch recently-listed token addresses filtered by chain.

        Calls ``GET /token-profiles/latest/v1``; the response is a JSON list
        of token profile objects.  Only items whose ``chainId`` matches *chain*
        are included in the result.

        Parameters
        ----------
        chain:
            Chain identifier to filter by (e.g. ``"solana"``).

        Returns
        -------
        list[str]
            ``tokenAddress`` values for matching profiles.
            Returns ``[]`` if the response is not a list, or on missing keys.

        Raises
        ------
        DataSourceError
            Propagated from the underlying HTTP layer on network / HTTP errors.
        """
        data = await self.get_json(_TOKEN_PROFILES_PATH)
        if not isinstance(data, list):
            logger.warning(
                "fetch_latest_token_addresses: expected list, got %s", type(data)
            )
            return []

        addresses: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("chainId") != chain:
                continue
            addr = item.get("tokenAddress")
            if addr:
                addresses.append(addr)
        return addresses

    async def get_token_pairs(self, mint: str) -> list[dict]:
        """Fetch all trading pairs for a given token mint address.

        Calls ``GET /latest/dex/tokens/{mint}`` and returns the ``pairs``
        array from the response.

        Parameters
        ----------
        mint:
            The token mint / contract address to look up.

        Returns
        -------
        list[dict]
            Raw pair dicts from the ``pairs`` array.
            Returns ``[]`` if the response has no ``pairs`` key, or if
            ``pairs`` is null/non-list.

        Raises
        ------
        DataSourceError
            Propagated from the underlying HTTP layer on network / HTTP errors.
        """
        path = _TOKEN_PAIRS_PATH.format(mint=mint)
        data = await self.get_json(path)
        if not isinstance(data, dict):
            logger.warning(
                "get_token_pairs: unexpected response type for mint=%s: %s",
                mint,
                type(data),
            )
            return []
        return data.get("pairs") or []

    async def get_token_price(self, mint: str) -> Optional[float]:
        """Fetch the current USD price for a token by its mint address.

        Calls the per-token endpoint ``GET /latest/dex/tokens/{mint}`` and
        returns the ``priceUsd`` of the first pair in the response.

        Parameters
        ----------
        mint:
            The Solana token mint address to look up.

        Returns
        -------
        float or None
            The USD price from the first pair, or ``None`` if no pairs are
            found or ``priceUsd`` is missing/unparseable.

        Raises
        ------
        DataSourceError
            Propagated from the underlying HTTP layer on network / HTTP errors.
        """
        pairs = await self.get_token_pairs(mint)
        if not pairs:
            logger.debug("get_token_price: no pairs for mint=%s", mint)
            return None
        first_pair = pairs[0]
        try:
            price_str = first_pair["priceUsd"]
            return float(price_str)
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug(
                "get_token_price: could not parse priceUsd for mint=%s: %s", mint, exc
            )
            return None
