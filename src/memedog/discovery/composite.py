"""CompositeFeed: run multiple feeds against one shared buffer."""
from __future__ import annotations

import asyncio
import logging

from memedog.discovery.buffer import MintBuffer

logger = logging.getLogger(__name__)


class CompositeFeed:
    """Run several feeds concurrently while sharing one MintBuffer."""

    def __init__(self, feeds: list, *, buffer: MintBuffer) -> None:
        self._feeds = feeds
        self._buffer = buffer

    def recent_mints(self) -> list[str]:
        return self._buffer.recent()

    async def _run_one(self, feed, stop_event: asyncio.Event) -> None:
        try:
            await feed.run(stop_event)
        except Exception as exc:
            logger.warning("CompositeFeed: sub-feed failed: %s", exc)

    async def run(self, stop_event: asyncio.Event) -> None:
        await asyncio.gather(
            *(self._run_one(feed, stop_event) for feed in self._feeds)
        )
