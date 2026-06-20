"""PriceWatcher — async loop that polls prices and evaluates open positions.

The real logic lives in tick() so it can be tested without sleeping.
run() is a thin wrapper that calls tick() repeatedly until stopped.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from memedog.config.settings import PaperTraderConfig
from memedog.models import TradeRecord
from memedog.papertrader.trader import PaperTrader
from memedog.store import Store

logger = logging.getLogger(__name__)

# Type alias for the injected price function.
# Must be an async callable: async (mint: str) -> float | None
PriceFn = Callable[[str], "asyncio.Coroutine[object, object, Optional[float]]"]


class PriceWatcher:
    """Polls prices for all open positions and triggers evaluate() on each tick.

    Args:
        store: SQLite store providing open_positions().
        trader: PaperTrader used to call evaluate().
        price_fn: Async callable ``async (mint: str) -> float | None``.
                  Returns None when the price is temporarily unavailable.
                  In production this wraps DexScreener; injected for tests.
        cfg: Paper trader config (price_poll_sec controls sleep duration).
    """

    def __init__(
        self,
        store: Store,
        trader: PaperTrader,
        price_fn: PriceFn,
        cfg: PaperTraderConfig,
    ) -> None:
        self._store = store
        self._trader = trader
        self._price_fn = price_fn
        self._cfg = cfg

    async def tick(self) -> list[TradeRecord]:
        """Evaluate all open positions against current prices.

        For each open position:
          - Call price_fn(mint). If it returns None, log and skip.
          - If price_fn raises, log the error and skip (does not abort tick).
          - Otherwise call trader.evaluate(pos, price); collect any TradeRecords.

        Returns:
            List of TradeRecords for positions that were closed this tick.
        """
        positions = self._store.open_positions()
        closed: list[TradeRecord] = []

        for pos in positions:
            try:
                price = await self._price_fn(pos.mint)
            except Exception as exc:
                logger.warning(
                    "price_fn failed for mint=%s: %s — skipping", pos.mint, exc
                )
                continue

            if price is None:
                logger.debug("No price available for mint=%s — skipping", pos.mint)
                continue

            rec = self._trader.evaluate(pos, price)
            if rec is not None:
                closed.append(rec)

        return closed

    async def run(self, stop_event: Optional[asyncio.Event] = None) -> None:
        """Poll prices on a fixed interval until stop_event is set.

        Args:
            stop_event: When set, the loop exits after the current tick completes.
                        If None, runs indefinitely (until cancelled).
        """
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                records = await self.tick()
                if records:
                    logger.info("tick() closed %d position(s)", len(records))
            except Exception as exc:
                logger.error("Unexpected error in PriceWatcher.tick(): %s", exc)

            await asyncio.sleep(self._cfg.price_poll_sec)

            if stop_event is not None and stop_event.is_set():
                break
