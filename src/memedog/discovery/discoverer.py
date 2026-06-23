"""Adapter from MigrationFeed to Scanner's TokenDiscoverer protocol."""
from __future__ import annotations


class MigrationDiscoverer:
    """Discover mints via a realtime feed and enrich pairs via DexScreener."""

    def __init__(self, *, feed, dex_client) -> None:
        self._feed = feed
        self._dex = dex_client

    async def fetch_latest_token_addresses(self, chain: str) -> list[str]:
        return self._feed.recent_mints()

    async def get_token_pairs(self, mint: str) -> list[dict]:
        return await self._dex.get_token_pairs(mint)
