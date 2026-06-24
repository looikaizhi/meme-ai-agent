"""Snapshot data contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import AwareDatetime, BaseModel

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
    liquidity_usd: Optional[float] = None
    volume_5m: Optional[float] = None
    volume_1h: Optional[float] = None
    buy_sell_ratio_5m: Optional[float] = None
    unique_buyers_1h: Optional[int] = None
    fdv_to_liquidity: Optional[float] = None


class WalletInfo(BaseModel):
    address: str
    label: Optional[str] = None
    tier: Optional[str] = None


class NarrativeInfo(BaseModel):
    available: bool = True
    category: Optional[str] = None
    matched_keywords: list[str] = []
    meme_collision: list[str] = []
    summary: str = ""


class SocialInfo(BaseModel):
    available: bool = True
    smart_money_buys: Optional[int] = None
    twitter_mentions_1h: Optional[int] = None   # deprecated: production no longer fills
    twitter_growth: Optional[float] = None        # deprecated: production no longer fills
    # smart-money consensus
    smart_money_distinct_wallets: Optional[int] = None
    smart_money_buyers: Optional[list[WalletInfo]] = None
    smart_money_top_tier: Optional[str] = None
    # social metadata
    has_twitter: Optional[bool] = None
    has_telegram: Optional[bool] = None
    has_website: Optional[bool] = None
    socials_count: Optional[int] = None


class TokenSnapshot(BaseModel):
    candidate: TokenCandidate
    safety: SafetyInfo
    holders: HolderInfo
    momentum: MomentumInfo
    social: SocialInfo
    narrative: NarrativeInfo = NarrativeInfo()
    enriched_at: AwareDatetime
