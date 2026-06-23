"""Optional LunarCrush social-intelligence client (off by default).

Only used when LUNARCRUSH_API_KEY is set. Any failure degrades to None so the
social dimension survives ("降级而非崩溃").
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

from memedog.clients.base import BaseHTTPClient

logger = logging.getLogger(__name__)

_LUNARCRUSH_BASE = "https://lunarcrush.com"


def _parse_galaxy_score(payload: dict | None) -> Optional[float]:
    """Pure: extract galaxy_score from a LunarCrush response. None on anything off."""
    try:
        return float((payload.get("data") or {}).get("galaxy_score"))
    except (TypeError, ValueError, AttributeError):
        return None


class LunarCrushClient(BaseHTTPClient):
    def __init__(self, api_key: str, **kwargs) -> None:
        if not api_key:
            raise ValueError("LunarCrushClient requires a non-empty api_key")
        self._api_key = api_key
        kwargs.setdefault("base_url", _LUNARCRUSH_BASE)
        super().__init__(**kwargs)

    async def get_galaxy_score(self, symbol: str) -> Optional[float]:
        """Return the Galaxy Score for *symbol*, or None on any error/missing."""
        path = f"/api4/public/coins/{quote(symbol, safe='')}/v1?key={self._api_key}"
        try:
            data = await self.get_json(path)
        except Exception as exc:  # noqa: BLE001 — degrade, never crash the pipeline
            logger.warning("LunarCrush galaxy score failed for %s: %s", symbol, exc)
            return None
        return _parse_galaxy_score(data)
