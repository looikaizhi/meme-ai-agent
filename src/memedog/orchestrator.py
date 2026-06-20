"""Orchestrator — wires all pipeline stages into a single run_cycle.

Pipeline order (漏斗式):
  Scanner → HardFilter → [per survivor: Enricher → ScoreEngine → LLMJudge]
  → Store.save_snapshot / Store.save_signal
  → PaperTrader.on_signal
  → maybe_notify (alert; errors swallowed)

Design goals:
- Full dependency injection: every collaborator is passed at construction time.
- Per-candidate try/except: a failure on one candidate is logged and skipped;
  the rest of the cycle continues.
- run_cycle never raises.
- run_forever loops run_cycle + sleep until stop_event.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from memedog.alert import maybe_notify
from memedog.config.settings import Config
from memedog.models import Signal
from memedog.store import Store

logger = logging.getLogger(__name__)


class Orchestrator:
    """Funnel pipeline orchestrator.

    Parameters
    ----------
    scanner:
        Object with ``async scan() -> list[TokenCandidate]``.
    hardfilter:
        Object with ``async apply(candidates) -> list[TokenCandidate]``.
    enricher:
        Object with ``async enrich(candidate, rugcheck_report=None) -> TokenSnapshot``.
    score_engine:
        Object with ``score(snapshot) -> Score``.
    llm_judge:
        Object with ``async judge(snapshot, score) -> Signal``.
    paper_trader:
        Object with ``on_signal(signal, entry_price) -> Position | None``.
    store:
        :class:`~memedog.store.Store` instance for persistence.
    cfg:
        Full :class:`~memedog.config.settings.Config` (used for alert + scan interval).
    """

    def __init__(
        self,
        *,
        scanner,
        hardfilter,
        enricher,
        score_engine,
        llm_judge,
        paper_trader,
        store: Store,
        cfg: Config,
    ) -> None:
        self._scanner = scanner
        self._hardfilter = hardfilter
        self._enricher = enricher
        self._score_engine = score_engine
        self._llm_judge = llm_judge
        self._paper_trader = paper_trader
        self._store = store
        self._cfg = cfg

    @property
    def paper_trader(self):
        """Read-only access to the injected paper trader."""
        return self._paper_trader

    async def run_cycle(self) -> list[Signal]:
        """Run one full pipeline cycle and return the collected signals.

        Never raises — any per-candidate exception is caught, logged, and the
        candidate is skipped. The cycle always returns a (possibly empty) list.
        """
        # Step 1 — Scanner
        try:
            candidates = await self._scanner.scan()
        except Exception as exc:
            logger.error("Scanner failed: %s — returning empty cycle", exc)
            return []

        logger.info("Cycle: scanner produced %d candidate(s)", len(candidates))

        # Step 2 — HardFilter
        try:
            survivors = await self._hardfilter.apply(candidates)
        except Exception as exc:
            logger.error("HardFilter failed: %s — returning empty cycle", exc)
            return []

        logger.info(
            "Cycle: hardfilter passed %d / %d candidate(s)",
            len(survivors),
            len(candidates),
        )

        # Step 3 — Per-survivor pipeline
        signals: list[Signal] = []

        for candidate in survivors:
            mint = candidate.mint
            try:
                # Enrich
                snap = await self._enricher.enrich(candidate)

                # Score
                score = self._score_engine.score(snap)

                # LLM judge
                signal = await self._llm_judge.judge(snap, score)

                # Persist
                self._store.save_snapshot(snap)
                self._store.save_signal(signal)

                # Paper trade
                self._paper_trader.on_signal(signal, entry_price=candidate.price_usd)

                # Alert (errors already swallowed inside maybe_notify)
                try:
                    await maybe_notify(signal, self._cfg)
                except Exception as alert_exc:
                    logger.warning("maybe_notify raised unexpectedly for %s: %s", mint, alert_exc)

                signals.append(signal)
                logger.info(
                    "Cycle: processed %s → %s (confidence=%.2f, score=%.1f)",
                    mint,
                    signal.signal.value,
                    signal.confidence,
                    signal.score_total,
                )

            except Exception as exc:
                logger.warning(
                    "Cycle: skipping candidate %s due to error: %s",
                    mint,
                    exc,
                    exc_info=True,
                )
                # Continue processing remaining candidates

        logger.info("Cycle complete: %d signal(s) produced", len(signals))

        # Step 4 — Record funnel event (non-fatal: a persistence failure must not
        # abort the cycle or change its return value).
        try:
            dropped = list(getattr(self._hardfilter, "dropped", []))
            flagged = list(getattr(self._hardfilter, "flagged", []))
            self._store.save_funnel_event(
                scanned=len(candidates),
                passed_hardfilter=len(survivors),
                signals=len(signals),
                dropped=dropped,
                flagged=flagged,
            )
        except Exception as funnel_exc:
            logger.warning("Failed to save funnel event: %s", funnel_exc)

        return signals

    async def run_forever(self, stop_event: Optional[asyncio.Event] = None) -> None:
        """Loop run_cycle() until stop_event is set (or cancelled).

        Sleeps for ``cfg.scanner.scan_interval_sec`` between cycles.
        Errors from run_cycle are already swallowed inside; this level only
        guards against truly unexpected exceptions.
        """
        interval = self._cfg.scanner.scan_interval_sec

        while True:
            if stop_event is not None and stop_event.is_set():
                logger.info("run_forever: stop_event set — exiting loop")
                break

            try:
                await self.run_cycle()
            except Exception as exc:
                logger.error("run_forever: unexpected error in run_cycle: %s", exc, exc_info=True)

            await asyncio.sleep(interval)

            if stop_event is not None and stop_event.is_set():
                logger.info("run_forever: stop_event set after sleep — exiting loop")
                break
