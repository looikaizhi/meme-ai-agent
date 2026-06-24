"""End-to-end integration smoke test — Task 3.

Builds the FULL pipeline using REAL module classes but FAKE external IO.
No real network calls are made.

Pipeline under test:
  Scanner (fake DexScreener) → HardFilter (fake RugCheck) → Enricher (fake clients)
  → real ScoreEngine → real LLMJudge (FakeProvider) → real PaperTrader → real Store
  → real Orchestrator.run_cycle()

Assertions:
  - run_cycle() returns at least one Signal
  - store.recent_signals() is non-empty
  - A paper Position was opened (store.open_positions() non-empty) for the
    BULLISH high-confidence signal
  - No real network was touched
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from memedog.clients.base import DataSourceError
from memedog.config.settings import (
    AlertConfig,
    AuthorityFilterConfig,
    CodexConfig,
    Config,
    EnricherConfig,
    HardFilterConfig,
    HoldersFilterConfig,
    LLMJudgeConfig,
    MomentumFilterConfig,
    PaperTraderConfig,
    ScannerConfig,
    ScoringConfig,
    ScoringHoldersConfig,
    ScoringMomentumConfig,
    ScoringSocialConfig,
    Settings,
)
from memedog.hardfilter.hardfilter import HardFilter
from memedog.enricher.enricher import Enricher
from memedog.llm.provider import FakeProvider
from memedog.llmjudge.judge import LLMJudge
from memedog.models import SignalType
from memedog.orchestrator import Orchestrator
from memedog.papertrader.trader import PaperTrader
from memedog.scanner.scanner import Scanner
from memedog.scoring.engine import ScoreEngine
from memedog.store import Store

# Real captured fixtures for LLM FakeProvider
from tests.conftest import load_fixture as _load_fixture

_BULL_TEXT = _load_fixture("codex/bull_argument.txt")
_BEAR_TEXT = _load_fixture("codex/bear_argument.txt")
_JUDGE_BULLISH = _load_fixture("codex/judge_bullish.json")   # dict: signal=BULLISH, confidence=0.78


# ---------------------------------------------------------------------------
# Fake DexScreener client — returns 2 raw pair dicts
# One pair will pass HardFilter momentum; one will fail momentum (low volume).
# ---------------------------------------------------------------------------

# The scanner's prefilter checks: age window, liquidity, volume_m5.
# We set pair_created_at to 60 minutes ago (inside the 20-360 min window).
_NOW_TS_MS = int(datetime.now(timezone.utc).timestamp() * 1000) - 60 * 60 * 1000  # 60 min ago


_GOOD_PAIR = {
    "chainId": "solana",
    "pairAddress": "PAIR_GOOD",
    "baseToken": {"address": "MINT_GOOD", "symbol": "GOODDOG"},
    "priceUsd": "0.00123",
    "liquidity": {"usd": 35000.0},   # > 10000 prefilter; > 20000 hardfilter
    "fdv": 350000.0,                  # FDV/liq = 10, < 50 max
    "volume": {"m5": 2000.0, "h1": 12000.0},  # > 1000 hardfilter min
    "txns": {"m5": {"buys": 50, "sells": 20}},  # ratio = 2.5, >= 1.0
    "priceChange": {"m5": 4.5},
    "pairCreatedAt": _NOW_TS_MS,
}

_BAD_PAIR = {
    "chainId": "solana",
    "pairAddress": "PAIR_BAD",
    "baseToken": {"address": "MINT_BAD", "symbol": "BADDOG"},
    "priceUsd": "0.00001",
    "liquidity": {"usd": 15000.0},   # > 10000 prefilter (passes scanner)
    "fdv": 150000.0,
    "volume": {"m5": 600.0, "h1": 2000.0},  # FAILS HardFilter momentum: < 1000
    "txns": {"m5": {"buys": 10, "sells": 5}},
    "priceChange": {"m5": 1.0},
    "pairCreatedAt": _NOW_TS_MS,
}

# Map of mint address → pairs (used by FakeDexScreenerClient)
_PAIRS_BY_MINT: dict[str, list[dict]] = {
    "MINT_GOOD": [_GOOD_PAIR],
    "MINT_BAD": [_BAD_PAIR],
}


class FakeDexScreenerClient:
    async def fetch_latest_token_addresses(self, chain: str) -> list[str]:
        return list(_PAIRS_BY_MINT.keys())

    async def get_token_pairs(self, mint: str) -> list[dict]:
        return _PAIRS_BY_MINT.get(mint, [])


# ---------------------------------------------------------------------------
# Fake RugCheck client — returns a clean report for MINT_GOOD
# ---------------------------------------------------------------------------

_CLEAN_RUGCHECK_REPORT = {
    "mintAuthority": None,        # revoked
    "freezeAuthority": None,      # revoked
    "markets": [{"lp": {"lpLockedPct": 100}}],  # LP fully locked → lp_burned_or_locked=True
    "topHolders": [
        {"address": f"addr{i}", "pct": 3.0, "uiAmount": 100, "owner": f"owner{i}", "insider": False}
        for i in range(8)
    ],  # 8 holders × 3% = 24% top10
    "token": {"supply": 1_000_000_000, "decimals": 6, "mintAuthority": None, "freezeAuthority": None},
    "creator": "creatorIntegration",
    "creatorBalance": 20_000_000,  # dev_pct = 2%
    "score_normalised": 12,        # trust = 88, risk_level = "LOW"
    "rugged": False,
}


class FakeRugCheckClient:
    async def get_token_report(self, mint: str) -> dict:
        if mint == "MINT_GOOD":
            return _CLEAN_RUGCHECK_REPORT
        raise DataSourceError(f"fake rugcheck unavailable for {mint}")


# ---------------------------------------------------------------------------
# Fake Helius + Twitter clients — used by Enricher; return minimal data
# ---------------------------------------------------------------------------


class FakeHeliusClient:
    async def get_largest_holders(self, mint: str) -> dict:
        return {"top10_pct": 24.0, "max_wallet_pct": 3.5, "holder_count": 8}

    async def count_smart_money_buys(self, mint: str, smart_wallets: set) -> int:
        return 3

    async def analyze_smart_money(self, mint: str, library: dict) -> dict:
        return {"buys": 3, "distinct_wallets": 1, "buyers": [], "top_tier": None}


class FakeTwitterClient:
    async def count_mentions(self, query: str, lookback_min: int) -> dict:
        return {"mentions_1h": 120, "growth": 15.0}


# ---------------------------------------------------------------------------
# Config factory — alert disabled, entry_min_confidence=0.5 so we get a position
# ---------------------------------------------------------------------------


def _make_integration_cfg() -> Config:
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
            weights={"safety": 0.35, "holders": 0.25, "momentum": 0.25, "social": 0.15},
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
            entry_min_confidence=0.5,   # low threshold to guarantee position opens
            size_usd=100.0,
            take_profit_pct=0.50,
            stop_loss_pct=0.25,
            max_hold_minutes=120,
            price_poll_sec=30,
            starting_balance_usd=10_000.0,
        ),
        alert=AlertConfig(
            enabled=False,   # no network calls
            only_signal="BULLISH",
            min_confidence=0.6,
        ),
        settings=Settings(),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "integration_test.db")


@pytest.fixture
def store(db_path: str) -> Store:
    s = Store(db_path)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Integration test helpers
# ---------------------------------------------------------------------------

def _judge_json(signal="BULLISH", confidence=0.82):
    """Return a valid JudgeOut JSON string (constructed; used for degradation test)."""
    return json.dumps({
        "signal": signal,
        "confidence": confidence,
        "bull_points": ["Strong momentum", "Low holder concentration", "Smart money buys"],
        "bear_points": ["Market is volatile"],
        "red_flags": [],
        "rationale": "Strong on-chain signals: clean rug report, good volume, smart money present.",
    })


# ---------------------------------------------------------------------------
# Main integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_e2e(store: Store) -> None:
    """Full pipeline smoke test: 2 raw pairs in → only 1 passes HardFilter → 1 BULLISH signal out.

    Uses REAL module classes wired together; only external IO is faked.
    Verifies:
    - run_cycle() returns at least one Signal (the good one)
    - store.recent_signals() is non-empty
    - A paper Position was opened (store.open_positions() non-empty)
    - Only MINT_GOOD produces a signal (MINT_BAD fails HardFilter momentum)
    """
    cfg = _make_integration_cfg()

    # --- Real Scanner with fake DexScreener client ---
    scanner = Scanner(client=FakeDexScreenerClient(), cfg=cfg.scanner)

    # --- Real HardFilter with fake RugCheck ---
    hardfilter = HardFilter(rugcheck=FakeRugCheckClient(), cfg=cfg.hardfilter)

    # --- Real Enricher with all-fake data clients ---
    enricher = Enricher(
        rugcheck_client=FakeRugCheckClient(),
        helius_client=FakeHeliusClient(),
        twitter_client=FakeTwitterClient(),
        cfg=cfg.enricher,
    )

    # --- Real ScoreEngine ---
    score_engine = ScoreEngine(cfg=cfg.scoring)

    # --- Real LLMJudge with FakeProvider using REAL captured codex fixtures ---
    # FakeProvider call order: idx=0 → bull, idx=1 → bear, idx=2 → judge
    # (asyncio.gather runs bull+bear concurrently; judge is called after)
    fake_provider = FakeProvider([
        _BULL_TEXT,                          # real codex bull argument (~2KB)
        _BEAR_TEXT,                          # real codex bear argument (~2.5KB)
        json.dumps(_JUDGE_BULLISH),          # real codex JudgeOut: BULLISH, confidence=0.78
    ])
    llm_judge = LLMJudge(cfg=cfg.llmjudge, provider=fake_provider)

    # --- Real PaperTrader ---
    paper_trader = PaperTrader(store=store, cfg=cfg.papertrader)

    # --- Real Orchestrator ---
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

    # Run one full cycle
    signals = await orch.run_cycle()

    # --- Assertions ---

    # At least one signal produced
    assert len(signals) >= 1, f"Expected at least 1 signal, got {len(signals)}"

    # The signal is for MINT_GOOD (MINT_BAD failed hardfilter momentum)
    good_signals = [s for s in signals if s.mint == "MINT_GOOD"]
    assert len(good_signals) == 1, "Expected exactly 1 signal for MINT_GOOD"

    # It should be BULLISH with confidence from real judge_bullish.json fixture (0.78)
    sig = good_signals[0]
    assert sig.signal == SignalType.BULLISH
    assert sig.confidence == pytest.approx(0.78)  # from real codex/judge_bullish.json
    assert sig.symbol == "GOODDOG"

    # store.recent_signals() is non-empty
    stored_sigs = store.recent_signals(limit=10)
    assert len(stored_sigs) >= 1

    # Snapshot was saved
    stored_snaps = store.recent_snapshots(limit=10)
    assert len(stored_snaps) >= 1
    assert stored_snaps[0].candidate.mint == "MINT_GOOD"

    # A paper position was opened (BULLISH + confidence 0.78 >= 0.5 entry threshold)
    open_pos = store.open_positions()
    assert len(open_pos) >= 1, "Expected at least one open paper position"
    assert open_pos[0].mint == "MINT_GOOD"
    assert open_pos[0].status == "OPEN"
    assert open_pos[0].entry_price == pytest.approx(0.00123)


@pytest.mark.asyncio
async def test_bad_pair_does_not_produce_signal(store: Store) -> None:
    """MINT_BAD's low volume must cause HardFilter to drop it — no signal for MINT_BAD."""
    cfg = _make_integration_cfg()

    scanner = Scanner(client=FakeDexScreenerClient(), cfg=cfg.scanner)
    hardfilter = HardFilter(rugcheck=FakeRugCheckClient(), cfg=cfg.hardfilter)
    enricher = Enricher(
        rugcheck_client=FakeRugCheckClient(),
        helius_client=FakeHeliusClient(),
        twitter_client=FakeTwitterClient(),
        cfg=cfg.enricher,
    )
    score_engine = ScoreEngine(cfg=cfg.scoring)

    # FakeProvider uses real captured fixtures for the one good candidate (3 calls)
    # idx=0 → bull, idx=1 → bear, idx=2 → judge (real BULLISH fixture)
    fake_provider = FakeProvider([
        _BULL_TEXT,
        _BEAR_TEXT,
        json.dumps(_JUDGE_BULLISH),
    ])
    llm_judge = LLMJudge(cfg=cfg.llmjudge, provider=fake_provider)
    paper_trader = PaperTrader(store=store, cfg=cfg.papertrader)

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

    # No signal should be for MINT_BAD
    bad_signals = [s for s in signals if s.mint == "MINT_BAD"]
    assert bad_signals == [], f"MINT_BAD should not produce a signal, got: {bad_signals}"

    # HardFilter should have dropped MINT_BAD
    assert any(
        "MINT_BAD" == mint for mint, _ in hardfilter.dropped
    ), "MINT_BAD should appear in hardfilter.dropped"


@pytest.mark.asyncio
async def test_pipeline_does_not_raise_on_llm_failure(store: Store) -> None:
    """Even if LLMJudge FakeProvider raises (no responses left), run_cycle must not raise.

    LLMJudge degrades gracefully; a degraded Signal is still returned.
    """
    cfg = _make_integration_cfg()

    scanner = Scanner(client=FakeDexScreenerClient(), cfg=cfg.scanner)
    hardfilter = HardFilter(rugcheck=FakeRugCheckClient(), cfg=cfg.hardfilter)
    enricher = Enricher(
        rugcheck_client=FakeRugCheckClient(),
        helius_client=FakeHeliusClient(),
        twitter_client=FakeTwitterClient(),
        cfg=cfg.enricher,
    )
    score_engine = ScoreEngine(cfg=cfg.scoring)

    # Empty FakeProvider — every complete() call raises IndexError → LLMJudge degrades
    fake_provider = FakeProvider([])
    llm_judge = LLMJudge(cfg=cfg.llmjudge, provider=fake_provider)
    paper_trader = PaperTrader(store=store, cfg=cfg.papertrader)

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

    # Must not raise
    signals = await orch.run_cycle()

    # A degraded signal still comes back for MINT_GOOD
    assert isinstance(signals, list)
    assert len(signals) >= 1
    # Degraded rationale contains '降级'
    assert "降级" in signals[0].rationale
