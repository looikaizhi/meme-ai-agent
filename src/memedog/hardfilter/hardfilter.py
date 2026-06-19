"""HardFilter aggregator.

Pipeline:
  1. Momentum rules (cheap, no I/O) — fail fast, skip RugCheck
  2. RugCheck fetch + parse
  3. Authority rules
  4. Holder rules

On DataSourceError from RugCheck:
  - on_rugcheck_failure="drop"         → drop candidate, reason "rugcheck_unavailable"
  - on_rugcheck_failure="pass_flagged" → keep candidate, note recorded but no crash

Results:
  - Returns list[TokenCandidate] of survivors.
  - self.dropped: list[tuple[mint: str, reason: str]] reset each apply() call.
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from memedog.clients.base import DataSourceError
from memedog.clients.rugcheck import parse_report
from memedog.config.settings import HardFilterConfig
from memedog.hardfilter.rules import check_authorities, check_holders, check_momentum
from memedog.models import TokenCandidate

logger = logging.getLogger(__name__)


@runtime_checkable
class RugCheckProtocol(Protocol):
    """Minimal protocol for a rug-check provider (sync or async get_token_report)."""

    async def get_token_report(self, mint: str) -> dict:
        ...


class HardFilter:
    """Filter candidates through momentum, authority, and holder rules.

    Parameters
    ----------
    rugcheck:
        Any object satisfying RugCheckProtocol (real RugCheckClient or a fake).
    cfg:
        HardFilterConfig loaded from thresholds.yaml.
    """

    def __init__(self, rugcheck: RugCheckProtocol, cfg: HardFilterConfig) -> None:
        self._rugcheck = rugcheck
        self._cfg = cfg
        self.dropped: list[tuple[str, str]] = []

    async def apply(self, candidates: list[TokenCandidate]) -> list[TokenCandidate]:
        """Run all three rule families; return survivors.

        self.dropped is reset at the start of each call so repeated calls
        only reflect the most recent batch.
        """
        self.dropped = []
        survivors: list[TokenCandidate] = []

        for candidate in candidates:
            mint = candidate.mint

            # ------------------------------------------------------------------
            # Stage 1 — Momentum (cheap, no I/O)
            # ------------------------------------------------------------------
            mom_passed, mom_reason = check_momentum(
                liquidity_usd=candidate.liquidity_usd,
                volume_5m=candidate.volume_5m,
                txns_5m_buys=candidate.txns_5m_buys,
                txns_5m_sells=candidate.txns_5m_sells,
                fdv_usd=candidate.fdv_usd,
                cfg=self._cfg.momentum,
            )
            if not mom_passed:
                logger.debug("HardFilter DROP %s momentum: %s", mint, mom_reason)
                self.dropped.append((mint, mom_reason))
                continue  # skip RugCheck entirely

            # ------------------------------------------------------------------
            # Stage 2 — Fetch + parse RugCheck report
            # ------------------------------------------------------------------
            try:
                raw_report = await self._rugcheck.get_token_report(mint)
                report = parse_report(raw_report)
            except DataSourceError as exc:
                if self._cfg.on_rugcheck_failure == "pass_flagged":
                    logger.warning(
                        "HardFilter PASS_FLAGGED %s: rugcheck unavailable (%s)", mint, exc
                    )
                    survivors.append(candidate)
                else:
                    reason = f"rugcheck_unavailable: {exc}"
                    logger.warning("HardFilter DROP %s: %s", mint, reason)
                    self.dropped.append((mint, reason))
                continue

            # ------------------------------------------------------------------
            # Stage 3 — Authority rules
            # ------------------------------------------------------------------
            auth_passed, auth_reason = check_authorities(
                mint_revoked=report.get("mint_authority_revoked"),
                freeze_revoked=report.get("freeze_authority_revoked"),
                lp_locked=report.get("lp_burned_or_locked"),
                cfg=self._cfg.authority,
            )
            if not auth_passed:
                logger.debug("HardFilter DROP %s authority: %s", mint, auth_reason)
                self.dropped.append((mint, auth_reason))
                continue

            # ------------------------------------------------------------------
            # Stage 4 — Holder rules
            # ------------------------------------------------------------------
            holders_passed, holders_reason = check_holders(
                top10_pct=report.get("top10_pct"),
                max_wallet_pct=report.get("max_wallet_pct"),
                dev_pct=report.get("dev_pct"),
                sniper_pct=report.get("sniper_pct"),
                cfg=self._cfg.holders,
            )
            if not holders_passed:
                logger.debug("HardFilter DROP %s holders: %s", mint, holders_reason)
                self.dropped.append((mint, holders_reason))
                continue

            # ------------------------------------------------------------------
            # Passed all stages — keep
            # ------------------------------------------------------------------
            survivors.append(candidate)
            logger.debug("HardFilter PASS %s", mint)

        return survivors
