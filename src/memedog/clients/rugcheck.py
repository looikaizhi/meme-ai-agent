"""RugCheck API client.

Real RugCheck API schema (verified live against api.rugcheck.xyz):

Top-level fields:
  mintAuthority          → null when revoked; pubkey string when active
  freezeAuthority        → null when revoked; pubkey string when active
  score                  → RISK score (can exceed 100); higher = MORE risky
  score_normalised       → 0–100ish risk score; higher = MORE risky (BONK=7)
  rugged                 → bool
  risks                  → list of {name, description, score, level}
  totalHolders           → int total holder count
  creator                → creator pubkey
  creatorBalance         → raw token amount held by creator
  token                  → {supply (raw int), decimals, mintAuthority, freezeAuthority, ...}
  markets                → list; each has lp sub-object with lpLocked, lpLockedPct,
                           lpLockedUSD, lpTotalSupply, lpCurrentSupply
  topHolders             → list of {address, pct (float %), uiAmount, owner, insider (bool)}

NO largestWalletPct key. NO insiders key. NO riskLevel key.

parse_report output keys (always present; missing source fields → None):
  mint_authority_revoked   → mintAuthority is None
  freeze_authority_revoked → freezeAuthority is None
  lp_burned_or_locked      → any market's lp.lpLockedPct >= 90
  top10_pct                → sum of pct for first 10 topHolders (excludes knownAccounts AMM accounts)
  max_wallet_pct           → max(pct) across topHolders (excludes knownAccounts AMM accounts)
  dev_pct                  → creatorBalance / token.supply * 100
  sniper_pct               → sum of pct for insider=True topHolders (excludes knownAccounts AMM accounts)
  trust_score              → 0–100 SAFETY score = clamp(100 - score_normalised, 0, 100)
  risk_level               → "CRITICAL"/"HIGH"/"MEDIUM"/"LOW" derived from rugged + score_normalised
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


def _amm_accounts(report: dict) -> set[str]:
    """Addresses flagged by RugCheck knownAccounts as AMM/LP pool accounts.

    Returns an empty set when knownAccounts is missing or malformed (the parser
    then degrades to counting all holders — old behaviour, no crash).
    """
    known = report.get("knownAccounts")
    if not isinstance(known, dict):
        return set()
    return {
        addr
        for addr, meta in known.items()
        if isinstance(meta, dict) and meta.get("type") == "AMM"
    }


def parse_report(report: dict) -> dict:
    """Normalise a raw RugCheck report into a clean, typed dict.

    All nine output keys are always present; missing source fields become None.
    See module docstring for the complete real-API field mapping.
    """
    # --- authority flags ---
    # mintAuthority/freezeAuthority: null (None) → revoked; pubkey string → active
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
    # Real schema: markets[].lp.lpLockedPct (0–100); >= 90 counts as locked/burned.
    lp_burned_or_locked: Optional[bool]
    markets = report.get("markets")
    if markets is None or len(markets) == 0:
        lp_burned_or_locked = None
    else:
        lp_burned_or_locked = any(
            (m.get("lp") or {}).get("lpLockedPct", 0) >= 90
            for m in markets
        )

    # --- holder metrics (AMM/LP pool accounts excluded) ---
    raw_holders = report.get("topHolders")
    amm = _amm_accounts(report)
    if raw_holders is None:
        holders: Optional[list] = None
    else:
        holders = [
            h
            for h in raw_holders
            if h.get("address") not in amm and h.get("owner") not in amm
        ]

    # top10_pct: sum of first 10 NON-AMM holders' pct
    top10_pct: Optional[float]
    if not holders:  # None or emptied-by-exclusion → cannot assess
        top10_pct = None
    else:
        top10_pct = sum(h.get("pct", 0.0) for h in holders[:10])

    # max_wallet_pct: largest single NON-AMM holder pct
    max_wallet_pct: Optional[float]
    if not holders:
        max_wallet_pct = None
    else:
        max_wallet_pct = max(h.get("pct", 0.0) for h in holders)

    # dev_pct: creator's share = creatorBalance / token.supply * 100
    dev_pct: Optional[float]
    creator_balance = report.get("creatorBalance")
    token = report.get("token") or {}
    supply = token.get("supply")
    if creator_balance is not None and supply is not None and supply > 0:
        dev_pct = creator_balance / supply * 100
    else:
        dev_pct = None

    # sniper_pct: sum of pct for NON-AMM holders flagged insider=True
    sniper_pct: Optional[float]
    if not holders:  # None or emptied-by-exclusion → cannot assess
        sniper_pct = None
    else:
        sniper_pct = sum(
            h.get("pct", 0.0) for h in holders if h.get("insider") is True
        )

    # --- trust score and risk level ---
    # score_normalised is a RISK score (higher = MORE risky).
    # Invert to get a SAFETY score (higher = safer): trust = clamp(100 - score_normalised, 0, 100)
    score_normalised = report.get("score_normalised")
    trust_score: Optional[int]
    if score_normalised is not None:
        trust_score = max(0, min(100, 100 - int(score_normalised)))
    else:
        trust_score = None

    # risk_level: derive string from rugged flag and score_normalised
    rugged = report.get("rugged")
    risk_level: Optional[str]
    if rugged is True:
        risk_level = "CRITICAL"
    elif score_normalised is not None:
        if score_normalised >= 50:
            risk_level = "HIGH"
        elif score_normalised >= 20:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"
    else:
        risk_level = None

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
