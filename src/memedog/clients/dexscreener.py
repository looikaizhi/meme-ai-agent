"""DexScreener API client for MemeDog Radar."""
from __future__ import annotations

import logging

from memedog.clients.base import BaseHTTPClient

logger = logging.getLogger(__name__)

_SEARCH_PATH = "/latest/dex/search"


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
