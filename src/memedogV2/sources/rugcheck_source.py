from __future__ import annotations

import time
from typing import Awaitable, Callable, Optional

from memedogV2.harness.contracts import ToolCallRecord
from memedogV2.sources.base import PartialFacts

Fetcher = Callable[[str], Awaitable[dict]]
_BASE = "https://api.rugcheck.xyz/v1/tokens"


async def _httpx_fetch(mint: str) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{_BASE}/{mint}/report")
        resp.raise_for_status()
        return resp.json()


def _amm_accounts(report: dict) -> set[str]:
    known = report.get("knownAccounts") or {}
    out = set()
    for addr, meta in known.items():
        if isinstance(meta, dict) and str(meta.get("type", "")).upper() == "AMM":
            out.add(addr)
    return out


class RugCheckSource:
    name = "rugcheck"

    def __init__(self, *, fetcher: Optional[Fetcher] = None) -> None:
        self._fetch = fetcher or _httpx_fetch

    async def fetch(self, ca: str, lp: str) -> tuple[PartialFacts, ToolCallRecord]:
        t0 = time.perf_counter()
        try:
            report = await self._fetch(ca)
            pf = self._normalize(report)
            dur = (time.perf_counter() - t0) * 1000.0
            return pf, ToolCallRecord(tool="rugcheck", command=f"report {ca}",
                                      input_summary=ca, exit_status=0, duration_ms=dur)
        except Exception as e:
            dur = (time.perf_counter() - t0) * 1000.0
            return PartialFacts(), ToolCallRecord(tool="rugcheck", command=f"report {ca}",
                                                  input_summary=ca, exit_status=1,
                                                  output_summary=str(e)[:200], duration_ms=dur)

    @staticmethod
    def _normalize(report: dict) -> PartialFacts:
        # Authority flags: null (None) means revoked
        mint_revoked = (report["mintAuthority"] is None) if "mintAuthority" in report else None
        freeze_revoked = (report["freezeAuthority"] is None) if "freezeAuthority" in report else None

        # LP safety: any market with lpLockedPct >= 90 counts as safe
        markets = report.get("markets")
        lp_safe = None
        if markets:
            lp_safe = any((m.get("lp") or {}).get("lpLockedPct", 0) >= 90 for m in markets)

        # Concentration: filter out AMM pool accounts
        amm = _amm_accounts(report)
        holders = [h for h in (report.get("topHolders") or [])
                   if h.get("address") not in amm and h.get("owner") not in amm]

        top10_rate = None
        max_wallet_rate = None
        if holders:
            # RugCheck pct values are PERCENT (0–100); divide by 100 to get 0–1 fraction.
            # Guard: if any pct exceeds 100 the data is malformed (e.g. raw-amount / raw-supply
            # without decimal adjustment on a very-new token) — degrade concentration to None.
            pcts = [float(h.get("pct") or 0.0) for h in holders]
            if pcts and max(pcts) <= 100.0:
                top10_rate = sum(sorted(pcts, reverse=True)[:10]) / 100.0
                max_wallet_rate = max(pcts) / 100.0

        return PartialFacts(
            mint_revoked=mint_revoked,
            freeze_revoked=freeze_revoked,
            lp_safe=lp_safe,
            top10_rate=top10_rate,
            max_wallet_rate=max_wallet_rate,
        )
