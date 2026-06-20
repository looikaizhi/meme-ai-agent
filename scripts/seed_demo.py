"""Seed demo data into a MemeDog Radar SQLite database.

Usage::

    python scripts/seed_demo.py

The database path is taken from the ``MEMEDOG_DB`` environment variable,
or defaults to ``memedog.db`` in the current working directory.

This script is idempotent — running it multiple times simply adds more rows.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure src/ is on the path when running from the project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from memedog.models import (
    HolderInfo,
    MomentumInfo,
    Position,
    SafetyInfo,
    Signal,
    SignalType,
    SocialInfo,
    TokenCandidate,
    TokenSnapshot,
    TradeRecord,
)
from memedog.store import Store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _candidate(mint: str, symbol: str, n: int = 0) -> TokenCandidate:
    created = _now() - timedelta(hours=n + 1)
    return TokenCandidate(
        mint=mint,
        pair_address=f"pair-{mint[:8]}",
        symbol=symbol,
        chain="solana",
        pair_created_at=created,
        price_usd=0.00001 * (n + 1),
        liquidity_usd=50_000.0 + n * 5_000,
        fdv_usd=500_000.0 + n * 50_000,
        volume_5m=3_000.0 + n * 500,
        volume_1h=25_000.0 + n * 2_000,
        txns_5m_buys=120 + n * 10,
        txns_5m_sells=40 + n * 5,
        price_change_5m=0.05 + n * 0.01,
        trace_id=f"trace-seed-{n:03d}",
    )


def _snapshot(candidate: TokenCandidate) -> TokenSnapshot:
    return TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(
            available=True,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            lp_burned_or_locked=True,
            rug_trust_score=85,
            rug_risk_level="low",
        ),
        holders=HolderInfo(
            available=True,
            top10_pct=22.5,
            max_wallet_pct=5.3,
            dev_wallet_pct=2.1,
            holder_count=1_200,
            sniper_pct=4.0,
        ),
        momentum=MomentumInfo(
            available=True,
            liquidity_usd=candidate.liquidity_usd,
            volume_5m=candidate.volume_5m,
            volume_1h=candidate.volume_1h,
            buy_sell_ratio_5m=3.0,
            unique_buyers_1h=300,
            fdv_to_liquidity=10.0,
        ),
        social=SocialInfo(
            available=True,
            smart_money_buys=3,
            twitter_mentions_1h=45,
            twitter_growth=0.8,
        ),
        enriched_at=_now(),
    )


def _signal(candidate: TokenCandidate, sig_type: SignalType, confidence: float) -> Signal:
    return Signal(
        mint=candidate.mint,
        symbol=candidate.symbol,
        signal=sig_type,
        confidence=confidence,
        score_total=72.0 if sig_type == SignalType.BULLISH else 38.0,
        bull_points=["strong momentum", "low top10 holder pct", "smart money present"],
        bear_points=["new token, limited history"],
        red_flags=[] if sig_type != SignalType.BEARISH else ["high sniper pct"],
        rationale=(
            "Strong momentum with healthy holder distribution."
            if sig_type == SignalType.BULLISH
            else "Risk factors outweigh momentum signals."
        ),
        created_at=_now(),
        trace_id=candidate.trace_id,
    )


def _position(candidate: TokenCandidate, status: str = "OPEN") -> Position:
    return Position(
        mint=candidate.mint,
        symbol=candidate.symbol,
        entry_price=candidate.price_usd,
        entry_time=_now() - timedelta(minutes=30),
        size_usd=100.0,
        status=status,
        take_profit_pct=0.50,
        stop_loss_pct=0.25,
        max_hold_minutes=120,
    )


def _trade(
    candidate: TokenCandidate,
    pnl_pct: float,
    exit_reason: str,
    hold_min: float = 45.0,
    size_usd: float = 100.0,
) -> TradeRecord:
    """Build a TradeRecord with internally consistent financials.

    Parameters
    ----------
    pnl_pct:
        Fraction (e.g. 0.45 means +45%).  Used to derive pnl_usd and exit_price.
    """
    entry_time = _now() - timedelta(minutes=hold_min + 10)
    exit_time = entry_time + timedelta(minutes=hold_min)
    entry_price = candidate.price_usd
    exit_price = entry_price * (1 + pnl_pct)
    pnl_usd = size_usd * pnl_pct
    return TradeRecord(
        mint=candidate.mint,
        symbol=candidate.symbol,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl_usd=pnl_usd,
        pnl_pct=pnl_pct,
        exit_reason=exit_reason,
        entry_time=entry_time,
        exit_time=exit_time,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def seed(db_path: str) -> None:
    print(f"Seeding demo data into: {db_path}")
    store = Store(db_path)

    # --- 5 demo tokens ---
    tokens = [
        ("So11111111111111111111111111111111111111111", "DOGE2"),
        ("So22222222222222222222222222222222222222222", "SHIB3"),
        ("So33333333333333333333333333333333333333333", "PEPE4"),
        ("So44444444444444444444444444444444444444444", "BONK5"),
        ("So55555555555555555555555555555555555555555", "WIF6"),
    ]

    candidates = [_candidate(mint, sym, n) for n, (mint, sym) in enumerate(tokens)]

    # Snapshots for all 5
    for cand in candidates:
        store.save_snapshot(_snapshot(cand))

    # Signals: 3 BULLISH, 1 BEARISH, 1 NEUTRAL
    sig_types = [
        (SignalType.BULLISH, 0.88),
        (SignalType.BULLISH, 0.76),
        (SignalType.BEARISH, 0.65),
        (SignalType.BULLISH, 0.82),
        (SignalType.NEUTRAL, 0.55),
    ]
    for cand, (stype, conf) in zip(candidates, sig_types):
        store.save_signal(_signal(cand, stype, conf))

    # Open positions for the first 2 BULLISH tokens
    for cand in candidates[:2]:
        try:
            store.save_position(_position(cand, status="OPEN"))
        except Exception:
            pass  # already exists (idempotent guard)

    # Closed trades: 2 winners, 1 loser
    # pnl_pct is a fraction: 0.45 = +45%, -0.18 = -18%
    trade_specs = [
        (candidates[0], 0.45, "take_profit", 60.0),
        (candidates[1], 0.30, "take_profit", 45.0),
        (candidates[2], -0.18, "stop_loss", 25.0),
    ]
    for cand, pnl_pct, reason, hold in trade_specs:
        store.save_trade(_trade(cand, pnl_pct, reason, hold))

    store.close()
    print(
        f"Done. Inserted: 5 snapshots, 5 signals, 2 open positions, 3 closed trades."
    )


if __name__ == "__main__":
    db_path = os.environ.get("MEMEDOG_DB", "memedog.db")
    seed(db_path)
