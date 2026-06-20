"""DexScreener API client for MemeDog Radar."""
from __future__ import annotations

import logging
from typing import Optional

from memedog.clients.base import BaseHTTPClient

logger = logging.getLogger(__name__)

_SEARCH_PATH = "/latest/dex/search"
_TOKEN_PATH = "/latest/dex/tokens/{mint}"


class DexScreenerClient(BaseHTTPClient):
    """Client for the DexScreener public API.

    Fetches recent Solana trading pairs from the DexScreener search endpoint.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(base_url="https://api.dexscreener.com", **kwargs)

    async def fetch_solana_pairs(self) -> list[dict]:
        """Query the DexScreener search endpoint for Solana pairs.

        Returns
        -------
        list[dict]
            Raw pair dicts from the ``pairs`` array in the API response.
            Returns ``[]`` if the response contains no ``pairs`` key.
        """
        data = await self.get_json(_SEARCH_PATH, params={"q": "solana"})
        if not isinstance(data, dict):
            logger.warning("DexScreener returned unexpected response type: %s", type(data))
            return []
        # Fix 2 — treat {"pairs": null} the same as {"pairs": []}
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
        path = _TOKEN_PATH.format(mint=mint)
        data = await self.get_json(path)
        if not isinstance(data, dict):
            logger.warning("get_token_price: unexpected response type for mint=%s: %s", mint, type(data))
            return None
        pairs = data.get("pairs") or []
        if not pairs:
            logger.debug("get_token_price: no pairs for mint=%s", mint)
            return None
        first_pair = pairs[0]
        try:
            price_str = first_pair["priceUsd"]
            return float(price_str)
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("get_token_price: could not parse priceUsd for mint=%s: %s", mint, exc)
            return None
