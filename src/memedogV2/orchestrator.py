from __future__ import annotations

import logging
from typing import Optional

from memedogV2.clients.errors import RateLimitBanned
from memedogV2.models.contracts import Signal

logger = logging.getLogger(__name__)


class AuditPipeline:
    """Adapter: HardFilterResult -> EvidenceGatherer -> BullBearJudge -> Signal."""

    def __init__(self, *, gatherer, judge) -> None:
        self._gatherer = gatherer
        self._judge = judge

    async def run(self, hf_result) -> Signal:
        bundle = await self._gatherer.gather(hf_result.ca_address)
        sig = await self._judge.decide(bundle)
        sig.trace_id = hf_result.trace_id
        return sig


class V2Orchestrator:
    """One-shot per address: hardfilter gate, then audit survivors. Never raises."""

    def __init__(self, *, hardfilter, audit) -> None:
        self._hf = hardfilter
        self._audit = audit

    async def process(self, ca: str, lp: str, trace_id: str = "") -> Optional[Signal]:
        try:
            hf = await self._hf.evaluate(ca, lp, trace_id=trace_id)
        except RateLimitBanned as e:
            logger.warning("gmgn rate-limit ban for %s until %s; skipping", ca, e.reset_at)
            return None
        except Exception as e:
            logger.warning("hardfilter error for %s: %s", ca, e)
            return None

        if not hf.passed:
            logger.info("hardfilter dropped %s: %s", ca, hf.dropped)
            return None

        try:
            sig = await self._audit.run(hf)
            if sig is not None:
                sig.trace_id = trace_id
            return sig
        except Exception as e:
            logger.warning("audit error for %s: %s", ca, e)
            return None
