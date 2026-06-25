from __future__ import annotations

from typing import Optional, Protocol

from pydantic import BaseModel

from memedogV2.harness.contracts import ToolCallRecord

ALL_FIELDS = [
    "mint_revoked", "freeze_revoked", "lp_safe", "honeypot",
    "top10_rate", "max_wallet_rate", "creator_rate", "dev_rate",
    "sniper_count", "fresh_wallet_rate", "bundler_rate",
    "liquidity_usd", "volume_5m", "buys_5m", "sells_5m",
    "price_usd", "circulating_supply",
    "smart_money_count", "kol_count", "dev_created_count", "historical_ath",
]

# Per-field source priority (resilience-first). Momentum is gmgn-only & required.
_RUGCHECK_FIRST = ["rugcheck", "gmgn"]
FIELD_PRIORITY: dict[str, list[str]] = {
    "mint_revoked": _RUGCHECK_FIRST, "freeze_revoked": _RUGCHECK_FIRST,
    "lp_safe": _RUGCHECK_FIRST,
    "top10_rate": ["rugcheck", "gmgn", "helius"],
    "max_wallet_rate": ["rugcheck", "gmgn", "helius"],
    "honeypot": ["gmgn"], "creator_rate": ["gmgn"], "dev_rate": ["gmgn"],
    "sniper_count": ["gmgn"], "fresh_wallet_rate": ["gmgn"], "bundler_rate": ["gmgn"],
    "liquidity_usd": ["gmgn"], "volume_5m": ["gmgn"], "buys_5m": ["gmgn"],
    "sells_5m": ["gmgn"], "price_usd": ["gmgn"], "circulating_supply": ["gmgn"],
    "smart_money_count": ["gmgn"], "kol_count": ["gmgn"],
    "dev_created_count": ["gmgn"], "historical_ath": ["gmgn"],
}

# momentum fields that must be present (gmgn required); used by the resolver
MOMENTUM_FIELDS = ["liquidity_usd", "volume_5m", "buys_5m", "sells_5m"]


class Facts(BaseModel):
    """Canonical, source-agnostic facts. None = unknown/unavailable."""
    mint_revoked: Optional[bool] = None
    freeze_revoked: Optional[bool] = None
    lp_safe: Optional[bool] = None
    honeypot: Optional[bool] = None
    top10_rate: Optional[float] = None
    max_wallet_rate: Optional[float] = None
    creator_rate: Optional[float] = None
    dev_rate: Optional[float] = None
    sniper_count: Optional[int] = None
    fresh_wallet_rate: Optional[float] = None
    bundler_rate: Optional[float] = None
    liquidity_usd: Optional[float] = None
    volume_5m: Optional[float] = None
    buys_5m: Optional[int] = None
    sells_5m: Optional[int] = None
    price_usd: Optional[float] = None
    circulating_supply: Optional[float] = None
    smart_money_count: Optional[int] = None
    kol_count: Optional[int] = None
    dev_created_count: Optional[int] = None
    historical_ath: Optional[float] = None


class PartialFacts(Facts):
    """Same shape as Facts; what a single source could provide (None = source lacks it)."""


class SourceAdapter(Protocol):
    name: str
    async def fetch(self, ca: str, lp: str) -> tuple["PartialFacts", ToolCallRecord]: ...
