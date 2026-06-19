"""RugCheck API client.

Field-path assumptions for parse_report:
  mintAuthority          → None means revoked; non-None means active
  freezeAuthority        → None means revoked; non-None means active
  markets[].lpBurned     → True if LP tokens have been burned
  markets[].lpLocked     → True if LP tokens are locked (alternative to burn)
  topHolders[].pct       → list of holder percentages; sum gives top-10 total
  largestWalletPct       → single largest wallet percentage
  insiders.devPct        → dev wallet percentage
  insiders.sniperPct     → sniper wallet percentage
  score                  → numeric trust score (0-100)
  riskLevel              → string e.g. "low", "medium", "high"
"""
from __future__ import annotations

from typing import Optional

from memedog.clients.base import BaseHTTPClient

_RUGCHECK_BASE = "https://api.rugcheck.xyz"


class RugCheckClient(BaseHTTPClient):
    """HTTP client for the RugCheck public API."""

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("base_url", _RUGCHECK_BASE)
        super().__init__(**kwargs)

    async def get_token_report(self, mint: str) -> dict:
        """Fetch the full token report from RugCheck.

        GET /v1/tokens/{mint}/report → returns parsed JSON dict.
        Raises DataSourceError on non-2xx or network failure.
        """
        return await self.get_json(f"/v1/tokens/{mint}/report")


def parse_report(report: dict) -> dict:
    """Normalise a raw RugCheck report into a clean, typed dict.

    All keys are always present in the output; missing source fields become None.

    Field paths assumed (see module docstring for full mapping):
      mintAuthority, freezeAuthority, markets, topHolders,
      largestWalletPct, insiders.devPct, insiders.sniperPct,
      score, riskLevel.
    """
    # --- authority flags ---
    # RugCheck sets mintAuthority / freezeAuthority to None when revoked.
    mint_authority_revoked: Optional[bool]
    freeze_authority_revoked: Optional[bool]

    if "mintAuthority" not in report:
        mint_authority_revoked = None
    else:
        mint_authority_revoked = report["mintAuthority"] is None

    if "freezeAuthority" not in report:
        freeze_authority_revoked = None
    else:
        freeze_authority_revoked = report["freezeAuthority"] is None

    # --- LP burned or locked ---
    lp_burned_or_locked: Optional[bool]
    markets = report.get("markets")
    if markets is None or len(markets) == 0:
        lp_burned_or_locked = None
    else:
        # Any market has LP burned or locked → overall is True
        lp_burned_or_locked = any(
            bool(m.get("lpBurned")) or bool(m.get("lpLocked"))
            for m in markets
        )

    # --- holder metrics ---
    top_holders = report.get("topHolders")
    if top_holders is None:
        top10_pct: Optional[float] = None
    else:
        top10_pct = sum(h.get("pct", 0.0) for h in top_holders[:10])

    max_wallet_pct: Optional[float] = report.get("largestWalletPct")

    insiders = report.get("insiders") or {}
    dev_pct: Optional[float] = insiders.get("devPct") if insiders else None
    sniper_pct: Optional[float] = insiders.get("sniperPct") if insiders else None

    # --- trust score and risk level ---
    trust_score: Optional[int] = report.get("score")
    risk_level: Optional[str] = report.get("riskLevel")

    return {
        "mint_authority_revoked": mint_authority_revoked,
        "freeze_authority_revoked": freeze_authority_revoked,
        "lp_burned_or_locked": lp_burned_or_locked,
        "top10_pct": top10_pct,
        "max_wallet_pct": max_wallet_pct,
        "dev_pct": dev_pct,
        "sniper_pct": sniper_pct,
        "trust_score": trust_score,
        "risk_level": risk_level,
    }
