"""Tests for Task A: Data contracts (pydantic v2 models)."""
from datetime import datetime, timezone

import pytest


def _now():
    return datetime.now(tz=timezone.utc)


class TestTokenCandidate:
    def test_construct_minimal(self):
        from memedog.models import TokenCandidate

        tc = TokenCandidate(
            mint="mintABC",
            pair_address="pairXYZ",
            symbol="DOG",
            pair_created_at=_now(),
            price_usd=0.0001,
            liquidity_usd=15000.0,
            fdv_usd=500000.0,
            volume_5m=800.0,
            volume_1h=12000.0,
            txns_5m_buys=40,
            txns_5m_sells=10,
            price_change_5m=5.2,
            trace_id="trace-001",
        )
        assert tc.mint == "mintABC"
        assert tc.chain == "solana"  # default


class TestSafetyInfo:
    def test_defaults(self):
        from memedog.models import SafetyInfo

        s = SafetyInfo()
        assert s.available is True
        assert s.mint_authority_revoked is None

    def test_construct_full(self):
        from memedog.models import SafetyInfo

        s = SafetyInfo(
            available=True,
            mint_authority_revoked=True,
            freeze_authority_revoked=True,
            lp_burned_or_locked=True,
            rug_trust_score=85,
            rug_risk_level="low",
        )
        assert s.rug_trust_score == 85


class TestHolderInfo:
    def test_defaults(self):
        from memedog.models import HolderInfo

        h = HolderInfo()
        assert h.available is True
        assert h.top10_pct is None


class TestMomentumInfo:
    def test_construct(self):
        from memedog.models import MomentumInfo

        m = MomentumInfo(
            liquidity_usd=20000.0,
            volume_5m=1000.0,
            volume_1h=15000.0,
            buy_sell_ratio_5m=1.5,
            fdv_to_liquidity=10.0,
        )
        assert m.available is True


class TestSocialInfo:
    def test_defaults(self):
        from memedog.models import SocialInfo

        s = SocialInfo()
        assert s.available is True
        assert s.smart_money_buys is None


class TestTokenSnapshot:
    def test_construct(self):
        from memedog.models import (
            HolderInfo,
            MomentumInfo,
            SafetyInfo,
            SocialInfo,
            TokenCandidate,
            TokenSnapshot,
        )

        tc = TokenCandidate(
            mint="mintABC",
            pair_address="pairXYZ",
            symbol="DOG",
            pair_created_at=_now(),
            price_usd=0.0001,
            liquidity_usd=15000.0,
            fdv_usd=500000.0,
            volume_5m=800.0,
            volume_1h=12000.0,
            txns_5m_buys=40,
            txns_5m_sells=10,
            price_change_5m=5.2,
            trace_id="trace-001",
        )
        snap = TokenSnapshot(
            candidate=tc,
            safety=SafetyInfo(),
            holders=HolderInfo(),
            momentum=MomentumInfo(
                liquidity_usd=20000.0,
                volume_5m=1000.0,
                volume_1h=15000.0,
                buy_sell_ratio_5m=1.5,
                fdv_to_liquidity=10.0,
            ),
            social=SocialInfo(),
            enriched_at=_now(),
        )
        assert snap.candidate.symbol == "DOG"


class TestDimensionScore:
    def test_construct(self):
        from memedog.models import DimensionScore

        ds = DimensionScore(name="safety", raw=0.8, weight=0.35, weighted=0.28)
        assert ds.notes == []


class TestScore:
    def test_construct(self):
        from memedog.models import DimensionScore, Score

        sc = Score(
            mint="mintABC",
            total=72.5,
            dimensions=[DimensionScore(name="safety", raw=0.8, weight=0.35, weighted=0.28)],
            trace_id="trace-001",
        )
        assert sc.total == 72.5


class TestSignalType:
    def test_enum_value(self):
        from memedog.models import SignalType

        assert SignalType("BULLISH") == SignalType.BULLISH
        assert SignalType("BEARISH") == SignalType.BEARISH
        assert SignalType("NEUTRAL") == SignalType.NEUTRAL


class TestSignal:
    def test_construct(self):
        from memedog.models import Signal, SignalType

        sig = Signal(
            mint="mintABC",
            symbol="DOG",
            signal=SignalType.BULLISH,
            confidence=0.82,
            score_total=74.0,
            bull_points=["good liquidity"],
            bear_points=[],
            red_flags=[],
            rationale="Strong momentum",
            created_at=_now(),
            trace_id="trace-001",
        )
        assert sig.signal == SignalType.BULLISH


class TestPosition:
    def test_construct(self):
        from memedog.models import Position

        pos = Position(
            mint="mintABC",
            symbol="DOG",
            entry_price=0.0001,
            entry_time=_now(),
            size_usd=100.0,
            status="open",
            take_profit_pct=0.5,
            stop_loss_pct=0.25,
            max_hold_minutes=120,
        )
        assert pos.status == "open"


class TestTradeRecord:
    def test_construct(self):
        from memedog.models import TradeRecord

        tr = TradeRecord(
            mint="mintABC",
            symbol="DOG",
            entry_price=0.0001,
            exit_price=0.00015,
            pnl_usd=5.0,
            pnl_pct=0.5,
            exit_reason="take_profit",
            entry_time=_now(),
            exit_time=_now(),
        )
        assert tr.exit_reason == "take_profit"
