"""PumpPortal migration feed: parsing and WebSocket runner."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from memedog.discovery.buffer import MintBuffer

logger = logging.getLogger(__name__)

_SUBSCRIBE_PAYLOAD = json.dumps({"method": "subscribeMigration"})


def parse_migration_message(msg: Any) -> str | None:
    """Extract the mint from a PumpPortal subscribeMigration message."""
    if not isinstance(msg, dict):
        return None
    if msg.get("txType") != "migrate":
        return None
    mint = msg.get("mint")
    if isinstance(mint, str) and mint:
        return mint
    return None


class PumpPortalFeed:
    """Primary discovery feed: PumpPortal subscribeMigration over WebSocket."""

    def __init__(
        self,
        buffer: MintBuffer,
        *,
        url: str,
        connect=None,
        backoff_initial: float = 1.0,
        backoff_max: float = 30.0,
    ) -> None:
        self._buffer = buffer
        self._url = url
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        if connect is None:
            import websockets

            connect = websockets.connect
        self._connect = connect

    def recent_mints(self) -> list[str]:
        return self._buffer.recent()

    async def run(self, stop_event: asyncio.Event) -> None:
        backoff = self._backoff_initial
        while not stop_event.is_set():
            try:
                async with self._connect(self._url) as ws:
                    await ws.send(_SUBSCRIBE_PAYLOAD)
                    backoff = self._backoff_initial
                    async for raw in ws:
                        if stop_event.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                        except (TypeError, ValueError):
                            continue
                        mint = parse_migration_message(msg)
                        if mint:
                            self._buffer.add(mint)
            except Exception as exc:
                logger.warning("PumpPortalFeed connection error: %s", exc)
            if stop_event.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self._backoff_max)
