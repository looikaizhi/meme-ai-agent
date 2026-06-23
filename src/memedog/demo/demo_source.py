"""Demo source: fixture-driven feed + replay LLM for offline, fast demos.

All embedded values are derived from real captured fixtures (rugcheck/helius/
dexscreener/codex). Kept inline so src/ stays self-contained (no tests/ coupling).
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from itertools import count

from memedog.llm.provider import LLMMessage
from memedog.models import (
    HolderInfo,
    MomentumInfo,
    SafetyInfo,
    SocialInfo,
    TokenCandidate,
    TokenSnapshot,
)

# Real captured judge output (from tests/fixtures/codex/judge_bullish.json).
_DEMO_JUDGE_JSON = json.dumps({
    "signal": "BULLISH",
    "confidence": 0.78,
    "bull_points": ["Liquidity healthy at ~$42k", "Authorities revoked", "Buy pressure 1.8x"],
    "bear_points": ["Social demand modest"],
    "red_flags": [],
    "rationale": "Strong safety and momentum with broad-based dimension strength.",
    "workflow": [
        {"step": "safety", "assessment": "pass", "note": "mint/freeze revoked, LP burned"},
        {"step": "concentration", "assessment": "pass", "note": "top10 ~22%"},
        {"step": "momentum", "assessment": "pass", "note": "liquidity + buy pressure healthy"},
        {"step": "social", "assessment": "neutral", "note": "modest"},
        {"step": "debate", "assessment": "pass", "note": "bull points data-backed"},
    ],
})

_DEMO_BULL = "Bull: liquidity ~$42,300, authorities revoked, buy/sell 1.8 — momentum constructive."
_DEMO_BEAR = "Bear: social demand modest; watch holder concentration if it climbs."


class ReplayProvider:
    """LLMProvider that replays captured bull/bear/judge outputs, cycling forever."""

    def __init__(self) -> None:
        self._n = 0

    async def complete(self, *, model, messages: list[LLMMessage],
                       temperature: float = 0.3, max_tokens: int = 1024) -> str:
        i = self._n % 3
        self._n += 1
        if i == 0:
            return _DEMO_BULL
        if i == 1:
            return _DEMO_BEAR
        return _DEMO_JUDGE_JSON


# --- DemoScanner + build_demo_snapshot ---------------------------------------

_DEMO_TOKENS = [
    ("So1Demo1111111111111111111111111111111111", "DOGWIF", 42300.0),
    ("So1Demo2222222222222222222222222222222222", "PEPESOL", 58000.0),
    ("So1Demo3333333333333333333333333333333333", "MOONCAT", 31000.0),
]
_counter = count()


class DemoScanner:
    """Yields a rotating set of demo candidates built from real-shaped values."""

    async def scan(self) -> list[TokenCandidate]:
        idx = next(_counter)
        mint, symbol, liq = _DEMO_TOKENS[idx % len(_DEMO_TOKENS)]
        jitter = random.uniform(0.9, 1.1)
        return [TokenCandidate(
            mint=mint, pair_address=f"pair-{mint[:6]}", symbol=symbol, chain="solana",
            pair_created_at=datetime.now(tz=timezone.utc), price_usd=0.001 * jitter,
            liquidity_usd=liq * jitter, fdv_usd=liq * 3 * jitter,
            volume_5m=15000 * jitter, volume_1h=80000 * jitter,
            txns_5m_buys=int(40 * jitter), txns_5m_sells=int(12 * jitter),
            price_change_5m=5.0 * jitter, trace_id=f"demo-{idx}",
        )]


def build_demo_snapshot(candidate: TokenCandidate) -> TokenSnapshot:
    """Assemble a realistic, passing snapshot (values from real captures)."""
    return TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(available=True, mint_authority_revoked=True,
                          freeze_authority_revoked=True, lp_burned_or_locked=True,
                          rug_trust_score=88, rug_risk_level="LOW"),
        holders=HolderInfo(available=True, top10_pct=22.0, max_wallet_pct=5.0,
                           dev_wallet_pct=2.0, holder_count=500, sniper_pct=6.0),
        momentum=MomentumInfo(available=True, liquidity_usd=candidate.liquidity_usd,
                              volume_5m=candidate.volume_5m, volume_1h=candidate.volume_1h,
                              buy_sell_ratio_5m=1.8, unique_buyers_1h=210, fdv_to_liquidity=3.2),
        social=SocialInfo(available=True, smart_money_buys=4),
        enriched_at=datetime.now(tz=timezone.utc),
    )


class DemoEnricher:
    """Offline enricher: returns build_demo_snapshot (no network)."""

    async def enrich(self, candidate: TokenCandidate, rugcheck_report=None) -> TokenSnapshot:
        return build_demo_snapshot(candidate)


# Minimal raw RugCheck report shaped so parse_report() yields revoked authorities
# + low risk + locked LP. Field names mirror the real RugCheck API response:
#   mintAuthority/freezeAuthority = None  → revoked
#   markets[].lp.lpLockedPct >= 90        → LP locked/burned
_DEMO_RUGCHECK_RAW = {
    "mintAuthority": None,
    "freezeAuthority": None,
    "score": 88,
    "score_normalised": 88,
    "risks": [],
    "markets": [{"lp": {"lpLockedPct": 100}}],
    # synthetic non-AMM holders; top-10 sum = 20%, max wallet 6% → passes holder rules
    "topHolders": [
        {"address": "demo_h1", "pct": 6.0, "owner": "demo_o1", "insider": False},
        {"address": "demo_h2", "pct": 5.0, "owner": "demo_o2", "insider": False},
        {"address": "demo_h3", "pct": 4.0, "owner": "demo_o3", "insider": False},
        {"address": "demo_h4", "pct": 3.0, "owner": "demo_o4", "insider": False},
        {"address": "demo_h5", "pct": 2.0, "owner": "demo_o5", "insider": False},
    ],
}


class DemoRugCheckClient:
    """Offline RugCheck stub for HardFilter in demo mode."""

    async def get_token_report(self, mint: str) -> dict:
        return dict(_DEMO_RUGCHECK_RAW)

    async def aclose(self) -> None:
        return None


def build_demo_price_fn():
    """Return an async price fn doing a small random walk (no network)."""
    async def _price_fn(mint: str):
        return round(0.001 * random.uniform(0.7, 1.6), 8)
    return _price_fn
