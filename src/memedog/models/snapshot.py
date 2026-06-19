"""Snapshot data contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from memedog.models.candidate import TokenCandidate


class SafetyInfo(BaseModel):
    available: bool = True
    mint_authority_revoked: Optional[bool] = None
    freeze_authority_revoked: Optional[bool] = None
    lp_burned_or_locked: Optional[bool] = None
    rug_trust_score: Optional[int] = None
    rug_risk_level: Optional[str] = None


class HolderInfo(BaseModel):
    available: bool = True
    top10_pct: Optional[float] = None
    max_wallet_pct: Optional[float] = None
    dev_wallet_pct: Optional[float] = None
    holder_count: Optional[int] = None
    sniper_pct: Optional[float] = None


class MomentumInfo(BaseModel):
    available: bool = True
    liquidity_usd: float
    volume_5m: float
    volume_1h: float
    buy_sell_ratio_5m: float
    unique_buyers_1h: Optional[int] = None
    fdv_to_liquidity: float


class SocialInfo(BaseModel):
    available: bool = True
    smart_money_buys: Optional[int] = None
    twitter_mentions_1h: Optional[int] = None
    twitter_growth: Optional[float] = None


class TokenSnapshot(BaseModel):
    candidate: TokenCandidate
    safety: SafetyInfo
    holders: HolderInfo
    momentum: MomentumInfo
    social: SocialInfo
    enriched_at: datetime
