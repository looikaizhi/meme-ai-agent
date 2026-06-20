"""Tests for Orchestrator — strict TDD (Task 1).

All collaborators are faked; NO real network / LLM calls.
Tests written BEFORE implementation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from memedog.config.settings import (
    AlertConfig,
    CodexConfig,
    EnricherConfig,
    HardFilterConfig,
    AuthorityFilterConfig,
    HoldersFilterConfig,
    MomentumFilterConfig,
    LLMJudgeConfig,
    PaperTraderConfig,
    ScannerConfig,
    ScoringConfig,
    ScoringHoldersConfig,
    ScoringMomentumConfig,
    ScoringSocialConfig,
    Settings,
    Config,
)
from memedog.models import (
    DimensionScore,
    HolderInfo,
    MomentumInfo,
    SafetyInfo,
    Score,
    Signal,
    SignalType,
    SocialInfo,
    TokenCandidate,
    TokenSnapshot,
)
from memedog.store import Store


# ---------------------------------------------------------------------------
# Helpers — minimal fakes for each collaborator
# ---------------------------------------------------------------------------


def _make_candidate(mint: str = "MINTAAA", price_usd: float = 0.001) -> TokenCandidate:
    return TokenCandidate(
        mint=mint,
        pair_address=f"PAIR_{mint}",
        symbol="DOGX",
        chain="solana",
        pair_created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        price_usd=price_usd,
        liquidity_usd=30_000.0,
        fdv_usd=300_000.0,
        volume_5m=1_500.0,
        volume_1h=8_000.0,
        txns_5m_buys=40,
        txns_5m_sells=15,
        price_change_5m=3.0,
        trace_id=f"trace-{mint}",
    )


def _make_snapshot(candidate: TokenCandidate) -> TokenSnapshot:
    return TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(available=True, rug_trust_score=85),
        holders=HolderInfo(available=True, top10_pct=20.0),
        momentum=MomentumInfo(available=True, liquidity_usd=30_000.0, volume_5m=1_500.0),
        social=SocialInfo(available=True, smart_money_buys=2),
        enriched_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )


def _make_score(candidate: TokenCandidate, total: float = 72.0) -> Score:
    return Score(
        mint=candidate.mint,
        total=total,
        dimensions=[
            DimensionScore(name="safety", raw=85.0, weight=0.35, weighted=29.75),
            DimensionScore(name="holders", raw=75.0, weight=0.25, weighted=18.75),
            DimensionScore(name="momentum", raw=60.0, weight=0.25, weighted=15.0),
            DimensionScore(name="social", raw=56.7, weight=0.15, weighted=8.5),
        ],
        trace_id=candidate.trace_id,
    )


def _make_signal(candidate: TokenCandidate, sig_type: SignalType = SignalType.BULLISH) -> Signal:
    return Signal(
        mint=candidate.mint,
        symbol=candidate.symbol,
        signal=sig_type,
        confidence=0.8,
        score_total=72.0,
        bull_points=["strong momentum"],
        bear_points=[],
        red_flags=[],
        rationale="Looks good",
        created_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        trace_id=candidate.trace_id,
    )


def _make_cfg() -> Config:
    """Minimal Config for the orchestrator — alert disabled so maybe_notify no-ops."""
    return Config(
        scanner=ScannerConfig(
            scan_interval_sec=30,
            chain="solana",
            min_pair_age_min=20,
            max_pair_age_min=360,
            prefilter_min_liquidity_usd=10_000.0,
            prefilter_min_volume_5m=500.0,
            dedup_ttl_min=720,
        ),
        hardfilter=HardFilterConfig(
            authority=AuthorityFilterConfig(
                require_mint_revoked=True,
                require_freeze_revoked=True,
                require_lp_burned_or_locked=True,
            ),
            holders=HoldersFilterConfig(
                max_top10_pct=35.0,
                max_single_wallet_pct=20.0,
                max_dev_pct=10.0,
                max_sniper_pct=30.0,
            ),
            momentum=MomentumFilterConfig(
                min_liquidity_usd=20_000.0,
                min_volume_5m=1_000.0,
                min_buy_sell_ratio_5m=1.0,
                max_fdv_to_liquidity=50.0,
            ),
            on_rugcheck_failure="drop",
        ),
        enricher=EnricherConfig(
            per_provider_timeout_sec=8.0,
            smart_money_wallets_file="config/smart_wallets.txt",
            twitter_lookback_min=60,
        ),
        scoring=ScoringConfig(
            weights={"safety": 0.35, "holders": 0.25, "momentum": 0.25, "social": 0.15},
            holders=ScoringHoldersConfig(
                top10_full_score_at=15.0,
                top10_zero_score_at=50.0,
                max_wallet_zero_at=25.0,
            ),
            momentum=ScoringMomentumConfig(
                liquidity_full_at=100_000.0,
                volume_5m_full_at=20_000.0,
            ),
            social=ScoringSocialConfig(
                smart_money_full_at=10.0,
                twitter_growth_full_at=2.0,
                twitter_growth_zero_at=-1.0,
            ),
            missing_dimension_weight_factor=0.5,
            neutral_score=50.0,
        ),
        llmjudge=LLMJudgeConfig(
            models={"bull": "codex:default", "bear": "codex:default", "judge": "codex:default"},
            temperature={"bull": 0.5, "bear": 0.5, "judge": 0.2},
            max_tokens=512,
            repair_retries=1,
            codex=CodexConfig(bin="codex", timeout_sec=30, sandbox="read-only"),
        ),
        papertrader=PaperTraderConfig(
            entry_min_confidence=0.6,
            size_usd=100.0,
            take_profit_pct=0.50,
            stop_loss_pct=0.25,
            max_hold_minutes=120,
            price_poll_sec=30,
            starting_balance_usd=10_000.0,
        ),
        alert=AlertConfig(
            enabled=False,  # disabled — no network calls
            only_signal="BULLISH",
            min_confidence=0.6,
        ),
        settings=Settings(),
    )


# ---------------------------------------------------------------------------
# Fake collaborators
# ---------------------------------------------------------------------------


class FakeScanner:
    def __init__(self, candidates: list[TokenCandidate]) -> None:
        self._candidates = candidates

    async def scan(self) -> list[TokenCandidate]:
        return list(self._candidates)


class FakeHardFilter:
    """Passes only candidates whose mint is in `pass_mints`."""

    def __init__(self, pass_mints: set[str]) -> None:
        self._pass = pass_mints
        self.dropped: list[tuple[str, str]] = []

    async def apply(self, candidates: list[TokenCandidate]) -> list[TokenCandidate]:
        survivors = [c for c in candidates if c.mint in self._pass]
        self.dropped = [(c.mint, "test_drop") for c in candidates if c.mint not in self._pass]
        return survivors


class FakeEnricher:
    """Returns a canned snapshot per candidate; can be set to raise for specific mints."""

    def __init__(self, raise_for: set[str] | None = None) -> None:
        self._raise_for = raise_for or set()

    async def enrich(self, candidate: TokenCandidate, rugcheck_report=None) -> TokenSnapshot:
        if candidate.mint in self._raise_for:
            raise RuntimeError(f"Fake enricher error for {candidate.mint}")
        return _make_snapshot(candidate)


class FakeScoreEngine:
    def score(self, snapshot: TokenSnapshot) -> Score:
        return _make_score(snapshot.candidate)


class FakeLLMJudge:
    def __init__(self, signal_type: SignalType = SignalType.BULLISH) -> None:
        self._signal_type = signal_type

    async def judge(self, snapshot: TokenSnapshot, score: Score) -> Signal:
        return _make_signal(snapshot.candidate, self._signal_type)


class FakePaperTrader:
    def __init__(self) -> None:
        self.on_signal_calls: list[tuple[Signal, float]] = []

    def on_signal(self, signal: Signal, entry_price: float):
        self.on_signal_calls.append((signal, entry_price))
        return None  # no position opened in fake


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "orch_test.db")


@pytest.fixture
def store(db_path: str) -> Store:
    s = Store(db_path)
    yield s
    s.close()


@pytest.fixture
def cfg() -> Config:
    return _make_cfg()


# ---------------------------------------------------------------------------
# Tests — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cycle_happy_path(store: Store, cfg: Config) -> None:
    """Scanner returns 2 candidates; hardfilter passes 1; run_cycle returns [signal].

    Verifies:
    - Return value contains exactly 1 Signal.
    - Store has snapshot + signal saved.
    - PaperTrader.on_signal called with correct entry_price.
    """
    from memedog.orchestrator import Orchestrator

    c1 = _make_candidate("MINT_A", price_usd=0.001)
    c2 = _make_candidate("MINT_B", price_usd=0.002)

    scanner = FakeScanner([c1, c2])
    hardfilter = FakeHardFilter(pass_mints={"MINT_A"})  # only c1 survives
    enricher = FakeEnricher()
    score_engine = FakeScoreEngine()
    llm_judge = FakeLLMJudge(SignalType.BULLISH)
    paper_trader = FakePaperTrader()

    orch = Orchestrator(
        scanner=scanner,
        hardfilter=hardfilter,
        enricher=enricher,
        score_engine=score_engine,
        llm_judge=llm_judge,
        paper_trader=paper_trader,
        store=store,
        cfg=cfg,
    )

    signals = await orch.run_cycle()

    # Returns exactly 1 signal
    assert len(signals) == 1
    assert signals[0].mint == "MINT_A"
    assert signals[0].signal == SignalType.BULLISH

    # Store has the snapshot saved
    snaps = store.recent_snapshots(limit=10)
    assert len(snaps) == 1
    assert snaps[0].candidate.mint == "MINT_A"

    # Store has the signal saved
    sigs = store.recent_signals(limit=10)
    assert len(sigs) == 1
    assert sigs[0].mint == "MINT_A"

    # PaperTrader was called with correct entry_price
    assert len(paper_trader.on_signal_calls) == 1
    called_signal, called_price = paper_trader.on_signal_calls[0]
    assert called_price == pytest.approx(c1.price_usd)
    assert called_signal.mint == "MINT_A"


@pytest.mark.asyncio
async def test_run_cycle_all_pass_hardfilter(store: Store, cfg: Config) -> None:
    """Both candidates pass hardfilter → 2 signals returned."""
    from memedog.orchestrator import Orchestrator

    c1 = _make_candidate("MINT_C", price_usd=0.001)
    c2 = _make_candidate("MINT_D", price_usd=0.003)

    orch = Orchestrator(
        scanner=FakeScanner([c1, c2]),
        hardfilter=FakeHardFilter(pass_mints={"MINT_C", "MINT_D"}),
        enricher=FakeEnricher(),
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(),
        paper_trader=FakePaperTrader(),
        store=store,
        cfg=cfg,
    )

    signals = await orch.run_cycle()
    assert len(signals) == 2
    mints = {s.mint for s in signals}
    assert mints == {"MINT_C", "MINT_D"}


@pytest.mark.asyncio
async def test_run_cycle_none_pass_hardfilter(store: Store, cfg: Config) -> None:
    """No candidates pass hardfilter → run_cycle returns []."""
    from memedog.orchestrator import Orchestrator

    c1 = _make_candidate("MINT_E")
    orch = Orchestrator(
        scanner=FakeScanner([c1]),
        hardfilter=FakeHardFilter(pass_mints=set()),
        enricher=FakeEnricher(),
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(),
        paper_trader=FakePaperTrader(),
        store=store,
        cfg=cfg,
    )

    signals = await orch.run_cycle()
    assert signals == []


# ---------------------------------------------------------------------------
# Tests — resilience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cycle_enricher_error_skips_candidate(store: Store, cfg: Config) -> None:
    """Enricher raises for MINT_F but not for MINT_G → MINT_G still processed.

    run_cycle MUST NOT raise; MINT_F is skipped; only MINT_G signal returned.
    """
    from memedog.orchestrator import Orchestrator

    c_bad = _make_candidate("MINT_F")
    c_good = _make_candidate("MINT_G", price_usd=0.005)

    orch = Orchestrator(
        scanner=FakeScanner([c_bad, c_good]),
        hardfilter=FakeHardFilter(pass_mints={"MINT_F", "MINT_G"}),
        enricher=FakeEnricher(raise_for={"MINT_F"}),
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(),
        paper_trader=FakePaperTrader(),
        store=store,
        cfg=cfg,
    )

    # Must not raise
    signals = await orch.run_cycle()

    # Only the good candidate produced a signal
    assert len(signals) == 1
    assert signals[0].mint == "MINT_G"

    # Store has only the good snapshot
    snaps = store.recent_snapshots(limit=10)
    assert len(snaps) == 1
    assert snaps[0].candidate.mint == "MINT_G"


@pytest.mark.asyncio
async def test_run_cycle_scanner_empty(store: Store, cfg: Config) -> None:
    """Scanner returns empty list → run_cycle returns [] without raising."""
    from memedog.orchestrator import Orchestrator

    orch = Orchestrator(
        scanner=FakeScanner([]),
        hardfilter=FakeHardFilter(pass_mints=set()),
        enricher=FakeEnricher(),
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(),
        paper_trader=FakePaperTrader(),
        store=store,
        cfg=cfg,
    )
    signals = await orch.run_cycle()
    assert signals == []


@pytest.mark.asyncio
async def test_run_cycle_does_not_raise_on_enricher_failure(store: Store, cfg: Config) -> None:
    """run_cycle never propagates exceptions from enricher; still returns list."""
    from memedog.orchestrator import Orchestrator

    c1 = _make_candidate("MINT_H")
    c2 = _make_candidate("MINT_I")

    orch = Orchestrator(
        scanner=FakeScanner([c1, c2]),
        hardfilter=FakeHardFilter(pass_mints={"MINT_H", "MINT_I"}),
        enricher=FakeEnricher(raise_for={"MINT_H", "MINT_I"}),  # both raise
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(),
        paper_trader=FakePaperTrader(),
        store=store,
        cfg=cfg,
    )

    # Must not raise even when all candidates fail enrichment
    signals = await orch.run_cycle()
    assert signals == []


# ---------------------------------------------------------------------------
# Tests — run_forever
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_forever_stops_on_event(store: Store, cfg: Config) -> None:
    """run_forever exits when stop_event is set after the first cycle."""
    import asyncio
    from memedog.orchestrator import Orchestrator

    call_count = 0

    class CountingScanner:
        async def scan(self):
            nonlocal call_count
            call_count += 1
            return []

    # Override scan_interval_sec to 0 for fast test
    cfg.scanner.scan_interval_sec = 0

    orch = Orchestrator(
        scanner=CountingScanner(),
        hardfilter=FakeHardFilter(pass_mints=set()),
        enricher=FakeEnricher(),
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(),
        paper_trader=FakePaperTrader(),
        store=store,
        cfg=cfg,
    )

    stop = asyncio.Event()

    async def stopper():
        # Let one cycle run, then set the stop event
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(
        orch.run_forever(stop_event=stop),
        stopper(),
    )

    # At least one cycle ran
    assert call_count >= 1
