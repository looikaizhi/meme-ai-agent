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
    ScoringNarrativeConfig,
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
                min_buy_sell_ratio_floor=0.2,
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
            weights={"safety": 0.30, "holders": 0.25, "momentum": 0.30, "social": 0.10, "narrative": 0.05},
            holders=ScoringHoldersConfig(
                top10_full_score_at=15.0,
                top10_zero_score_at=50.0,
                max_wallet_zero_at=25.0,
                holder_count_full_at=500.0,
                sniper_zero_at=30.0,
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
            narrative=ScoringNarrativeConfig(
                category_scores={"animal": 70, "ai": 65, "political": 60, "culture": 55, "finance_utility": 35, "unknown": 40},
                meme_collision_bonus=10,
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

    def __init__(self, pass_mints: set[str], reports: dict[str, dict] | None = None) -> None:
        self._pass = pass_mints
        self._reports = reports or {}
        self.dropped: list[tuple[str, str]] = []
        self.flagged: list[tuple[str, str]] = []
        self.rugcheck_reports: dict[str, dict] = {}

    async def apply(self, candidates: list[TokenCandidate]) -> list[TokenCandidate]:
        survivors = [c for c in candidates if c.mint in self._pass]
        self.dropped = [(c.mint, "test_drop") for c in candidates if c.mint not in self._pass]
        self.flagged = []
        self.rugcheck_reports = {
            c.mint: self._reports[c.mint]
            for c in survivors
            if c.mint in self._reports
        }
        return survivors


class FakeEnricher:
    """Returns a canned snapshot per candidate; can be set to raise for specific mints."""

    def __init__(self, raise_for: set[str] | None = None) -> None:
        self._raise_for = raise_for or set()
        self.calls: list[tuple[TokenCandidate, dict | None]] = []

    async def enrich(self, candidate: TokenCandidate, rugcheck_report=None) -> TokenSnapshot:
        self.calls.append((candidate, rugcheck_report))
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


def test_paper_trader_property_returns_injected_trader(store: Store, cfg: Config) -> None:
    """paper_trader property returns the injected paper_trader instance."""
    from memedog.orchestrator import Orchestrator

    paper_trader = FakePaperTrader()
    orch = Orchestrator(
        scanner=FakeScanner([]),
        hardfilter=FakeHardFilter(pass_mints=set()),
        enricher=FakeEnricher(),
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(),
        paper_trader=paper_trader,
        store=store,
        cfg=cfg,
    )

    assert orch.paper_trader is paper_trader
    # Private attribute is preserved unchanged
    assert orch._paper_trader is paper_trader


def test_orchestrator_accepts_optional_feed(store: Store, cfg: Config) -> None:
    from memedog.orchestrator import Orchestrator

    sentinel = object()
    orch = Orchestrator(
        scanner=FakeScanner([]),
        hardfilter=FakeHardFilter(pass_mints=set()),
        enricher=FakeEnricher(),
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(),
        paper_trader=FakePaperTrader(),
        store=store,
        cfg=cfg,
        feed=sentinel,
    )
    assert orch.feed is sentinel


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
async def test_run_cycle_passes_hardfilter_rugcheck_report_to_enricher(
    store: Store, cfg: Config
) -> None:
    """Reuse HardFilter's parsed RugCheck report instead of refetching in Enricher."""
    from memedog.orchestrator import Orchestrator

    candidate = _make_candidate("MINT_REPORT")
    report = {
        "mint_authority_revoked": True,
        "freeze_authority_revoked": True,
        "lp_burned_or_locked": True,
        "trust_score": 91,
        "risk_level": "LOW",
    }
    hardfilter = FakeHardFilter(
        pass_mints={"MINT_REPORT"},
        reports={"MINT_REPORT": report},
    )
    enricher = FakeEnricher()
    orch = Orchestrator(
        scanner=FakeScanner([candidate]),
        hardfilter=hardfilter,
        enricher=enricher,
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(),
        paper_trader=FakePaperTrader(),
        store=store,
        cfg=cfg,
    )

    signals = await orch.run_cycle()

    assert len(signals) == 1
    assert len(enricher.calls) == 1
    called_candidate, called_report = enricher.calls[0]
    assert called_candidate.mint == "MINT_REPORT"
    assert called_report is report


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


# ---------------------------------------------------------------------------
# Tests — funnel event persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cycle_saves_funnel_event(store: Store, cfg: Config) -> None:
    """After run_cycle, store.recent_funnel_events() has one event with correct counts.

    Scanner returns 2 candidates; hardfilter passes 1 (mint=MINT_A); 1 signal produced.
    Funnel event must record: scanned=2, passed_hardfilter=1, signals=1.
    """
    from memedog.orchestrator import Orchestrator

    c1 = _make_candidate("MINT_A", price_usd=0.001)
    c2 = _make_candidate("MINT_B", price_usd=0.002)

    hardfilter = FakeHardFilter(pass_mints={"MINT_A"})  # MINT_B dropped

    orch = Orchestrator(
        scanner=FakeScanner([c1, c2]),
        hardfilter=hardfilter,
        enricher=FakeEnricher(),
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(SignalType.BULLISH),
        paper_trader=FakePaperTrader(),
        store=store,
        cfg=cfg,
    )

    signals = await orch.run_cycle()
    assert len(signals) == 1  # sanity

    events = store.recent_funnel_events(limit=5)
    assert len(events) == 1

    ev = events[0]
    assert ev["scanned"] == 2
    assert ev["passed_hardfilter"] == 1
    assert ev["signals"] == 1


@pytest.mark.asyncio
async def test_run_cycle_funnel_event_dropped_list(store: Store, cfg: Config) -> None:
    """Funnel event records the dropped candidates from hardfilter.dropped."""
    from memedog.orchestrator import Orchestrator

    c1 = _make_candidate("MINT_P")
    c2 = _make_candidate("MINT_Q")

    hardfilter = FakeHardFilter(pass_mints=set())  # all dropped

    orch = Orchestrator(
        scanner=FakeScanner([c1, c2]),
        hardfilter=hardfilter,
        enricher=FakeEnricher(),
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(),
        paper_trader=FakePaperTrader(),
        store=store,
        cfg=cfg,
    )

    await orch.run_cycle()

    events = store.recent_funnel_events(limit=5)
    assert len(events) == 1

    ev = events[0]
    assert ev["scanned"] == 2
    assert ev["passed_hardfilter"] == 0
    assert ev["signals"] == 0
    # dropped should contain both mints
    dropped_mints = {mint for mint, _ in ev["dropped"]}
    assert "MINT_P" in dropped_mints
    assert "MINT_Q" in dropped_mints


@pytest.mark.asyncio
async def test_run_cycle_funnel_event_no_crash_on_save_failure(
    store: Store, cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure in save_funnel_event must not abort the cycle or raise."""
    from memedog.orchestrator import Orchestrator

    def _bad_save(*args, **kwargs):
        raise RuntimeError("DB write failure simulation")

    monkeypatch.setattr(store, "save_funnel_event", _bad_save)

    c1 = _make_candidate("MINT_R")

    orch = Orchestrator(
        scanner=FakeScanner([c1]),
        hardfilter=FakeHardFilter(pass_mints={"MINT_R"}),
        enricher=FakeEnricher(),
        score_engine=FakeScoreEngine(),
        llm_judge=FakeLLMJudge(SignalType.BULLISH),
        paper_trader=FakePaperTrader(),
        store=store,
        cfg=cfg,
    )

    # Must not raise even though save_funnel_event raises
    signals = await orch.run_cycle()
    assert len(signals) == 1  # cycle still completes


class TestPipelineEventEmission:
    @pytest.mark.asyncio
    async def test_run_cycle_emits_stage_events(self, tmp_path):
        from memedog.store import Store
        from memedog.orchestrator import Orchestrator
        from memedog.models import (
            TokenCandidate, TokenSnapshot, SafetyInfo, HolderInfo,
            MomentumInfo, SocialInfo, Score, DimensionScore, Signal, SignalType,
        )
        from memedog.config import load_config

        cand = TokenCandidate(
            mint="M1", pair_address="P", symbol="DOGX", chain="solana",
            pair_created_at=datetime(2024, 1, 1, tzinfo=timezone.utc), price_usd=0.001,
            liquidity_usd=40000, fdv_usd=120000, volume_5m=15000, volume_1h=80000,
            txns_5m_buys=40, txns_5m_sells=10, price_change_5m=5.0, trace_id="tr1",
        )
        snap = TokenSnapshot(
            candidate=cand,
            safety=SafetyInfo(available=True, rug_trust_score=88),
            holders=HolderInfo(available=True, top10_pct=20.0),
            momentum=MomentumInfo(available=True, liquidity_usd=40000, volume_5m=15000),
            social=SocialInfo(available=True, smart_money_buys=3),
            enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        score = Score(mint="M1", total=75.0, trace_id="tr1", dimensions=[
            DimensionScore(name="safety", raw=88, weight=0.35, weighted=30.8),
        ])
        signal = Signal(
            mint="M1", symbol="DOGX", signal=SignalType.BULLISH, confidence=0.8,
            score_total=75.0, bull_points=[], bear_points=[], red_flags=[],
            rationale="ok", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc), trace_id="tr1",
        )

        class _Scanner:
            async def scan(self): return [cand]
        class _HF:
            dropped = []; flagged = []
            async def apply(self, c): return list(c)
        class _Enr:
            async def enrich(self, c, rugcheck_report=None): return snap
        class _SE:
            def score(self, s): return score
        class _Judge:
            async def judge(self, s, sc): return signal
        class _PT:
            def on_signal(self, sig, entry_price=None): return None

        store = Store(str(tmp_path / "o.db"))
        try:
            orch = Orchestrator(
                scanner=_Scanner(), hardfilter=_HF(), enricher=_Enr(),
                score_engine=_SE(), llm_judge=_Judge(), paper_trader=_PT(),
                store=store, cfg=load_config(),
            )
            await orch.run_cycle()
            stages = [e["stage"] for e in store.recent_events(limit=50)]
        finally:
            store.close()

        for expected in ["scan", "hardfilter", "score", "judge", "signal"]:
            assert expected in stages, f"missing stage event: {expected}"

    @pytest.mark.asyncio
    async def test_run_cycle_survives_save_event_failure(self, tmp_path):
        from memedog.orchestrator import Orchestrator
        from memedog.config import load_config
        from memedog.models import (
            TokenCandidate, TokenSnapshot, SafetyInfo, HolderInfo,
            MomentumInfo, SocialInfo, Score, DimensionScore, Signal, SignalType,
        )

        cand = TokenCandidate(
            mint="M1", pair_address="P", symbol="DOGX", chain="solana",
            pair_created_at=datetime(2024, 1, 1, tzinfo=timezone.utc), price_usd=0.001,
            liquidity_usd=40000, fdv_usd=120000, volume_5m=15000, volume_1h=80000,
            txns_5m_buys=40, txns_5m_sells=10, price_change_5m=5.0, trace_id="tr1",
        )
        snap = TokenSnapshot(
            candidate=cand, safety=SafetyInfo(available=True, rug_trust_score=88),
            holders=HolderInfo(available=True, top10_pct=20.0),
            momentum=MomentumInfo(available=True, liquidity_usd=40000, volume_5m=15000),
            social=SocialInfo(available=True), enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        score = Score(mint="M1", total=75.0, trace_id="tr1",
                      dimensions=[DimensionScore(name="safety", raw=88, weight=1.0, weighted=88)])
        signal = Signal(mint="M1", symbol="DOGX", signal=SignalType.BULLISH, confidence=0.8,
                        score_total=75.0, bull_points=[], bear_points=[], red_flags=[],
                        rationale="ok", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc), trace_id="tr1")

        class _Scanner:
            async def scan(self): return [cand]
        class _HF:
            dropped = []; flagged = []
            async def apply(self, c): return list(c)
        class _Enr:
            async def enrich(self, c, rugcheck_report=None): return snap
        class _SE:
            def score(self, s): return score
        class _Judge:
            async def judge(self, s, sc): return signal
        class _PT:
            def on_signal(self, sig, entry_price=None): return None

        class _BrokenStore:
            def save_event(self, *a, **k): raise RuntimeError("db down")
            def save_snapshot(self, *a, **k): pass
            def save_signal(self, *a, **k): pass
            def save_funnel_event(self, *a, **k): pass

        orch = Orchestrator(
            scanner=_Scanner(), hardfilter=_HF(), enricher=_Enr(),
            score_engine=_SE(), llm_judge=_Judge(), paper_trader=_PT(),
            store=_BrokenStore(), cfg=load_config(),
        )
        signals = await orch.run_cycle()
        assert len(signals) == 1
