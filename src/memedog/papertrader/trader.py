"""PaperTrader — simulated (paper) trade entry and exit logic.

NO real trading. All positions and records are persisted to SQLite via Store.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from memedog.config.settings import PaperTraderConfig
from memedog.models import Position, Signal, SignalType, TradeRecord
from memedog.store import Store

logger = logging.getLogger(__name__)


class PaperTrader:
    """Simulated trader that opens and closes paper positions.

    Args:
        store: SQLite store for persistence.
        cfg: Paper trader configuration (thresholds, sizing, etc.).
    """

    def __init__(self, store: Store, cfg: PaperTraderConfig) -> None:
        self._store = store
        self._cfg = cfg

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------

    def on_signal(self, signal: Signal, entry_price: float) -> Optional[Position]:
        """Evaluate a signal and open a new paper position if conditions are met.

        Conditions to open:
          1. signal.signal == SignalType.BULLISH
          2. signal.confidence >= cfg.entry_min_confidence
          3. No existing OPEN position for signal.mint

        Returns:
            The newly opened Position, or None if conditions are not met.
        """
        if signal.signal != SignalType.BULLISH:
            logger.debug(
                "Skipping signal for %s: not BULLISH (got %s)", signal.mint, signal.signal
            )
            return None

        if signal.confidence < self._cfg.entry_min_confidence:
            logger.debug(
                "Skipping signal for %s: confidence %.2f < min %.2f",
                signal.mint,
                signal.confidence,
                self._cfg.entry_min_confidence,
            )
            return None

        open_mints = {p.mint for p in self._store.open_positions()}
        if signal.mint in open_mints:
            logger.debug(
                "Skipping signal for %s: already have an OPEN position", signal.mint
            )
            return None

        now = datetime.now(tz=timezone.utc)
        pos = Position(
            mint=signal.mint,
            symbol=signal.symbol,
            entry_price=entry_price,
            entry_time=now,
            size_usd=self._cfg.size_usd,
            status="OPEN",
            take_profit_pct=self._cfg.take_profit_pct,
            stop_loss_pct=self._cfg.stop_loss_pct,
            max_hold_minutes=self._cfg.max_hold_minutes,
        )
        self._store.save_position(pos)
        logger.info(
            "Opened position: mint=%s symbol=%s entry_price=%.6f size_usd=%.2f",
            pos.mint,
            pos.symbol,
            entry_price,
            self._cfg.size_usd,
        )
        return pos

    # ------------------------------------------------------------------
    # Exit evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        position: Position,
        current_price: float,
        now: Optional[datetime] = None,
    ) -> Optional[TradeRecord]:
        """Evaluate an open position against current price and time.

        Closes the position and returns a TradeRecord if any exit condition is met:
          - Price >= entry_price * (1 + take_profit_pct)  → "TP"
          - Price <= entry_price * (1 - stop_loss_pct)    → "SL"
          - (now - entry_time) >= max_hold_minutes         → "TIMEOUT"

        Priority order: TP > SL > TIMEOUT (first condition matched wins).

        Args:
            position: The open position to evaluate.
            current_price: The latest market price for this position's mint.
            now: Override the current time (defaults to utcnow; useful for testing).

        Returns:
            A TradeRecord if the position was closed, else None.
        """
        if now is None:
            now = datetime.now(tz=timezone.utc)

        pct_change = (current_price - position.entry_price) / position.entry_price
        elapsed = now - position.entry_time

        exit_reason: Optional[str] = None
        if pct_change >= position.take_profit_pct:
            exit_reason = "TP"
        elif pct_change <= -position.stop_loss_pct:
            exit_reason = "SL"
        elif elapsed >= timedelta(minutes=position.max_hold_minutes):
            exit_reason = "TIMEOUT"

        if exit_reason is None:
            return None

        pnl_usd = position.size_usd * pct_change
        rec = TradeRecord(
            mint=position.mint,
            symbol=position.symbol,
            entry_price=position.entry_price,
            exit_price=current_price,
            pnl_usd=pnl_usd,
            pnl_pct=pct_change,
            exit_reason=exit_reason,
            entry_time=position.entry_time,
            exit_time=now,
        )

        self._store.update_position(position.mint, "CLOSED")
        self._store.save_trade(rec)

        logger.info(
            "Closed position: mint=%s reason=%s pnl_pct=%.2f%% pnl_usd=%.2f",
            position.mint,
            exit_reason,
            pct_change * 100,
            pnl_usd,
        )
        return rec
