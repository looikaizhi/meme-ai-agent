# 实时可观测 + 一键本地服务器 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一条命令拉起后端流水线循环 + 实时看板 + 统一日志,逐阶段实时呈现漏斗,并提供离线确定性的 `--demo` 模式让漏斗持续流动。

**Architecture:** Store 新增 append-only `pipeline_events` 表;Orchestrator 在每阶段插桩发事件(不改业务逻辑);新增 `serve.py` launcher(后端 asyncio + streamlit 子进程 + 优雅退出);新增 `demo/` 模块(fixture 驱动的 scanner/enricher/rugcheck stub + 循环 ReplayProvider + 随机游走价格);app_factory 支持 `demo=True` 注入;dashboard 顶部加实时活动流。

**Tech Stack:** Python 3.11+,asyncio,sqlite3,subprocess,argparse,Streamlit,pydantic v2,pytest。

参考 spec:[docs/superpowers/specs/2026-06-23-realtime-server-design.md](../specs/2026-06-23-realtime-server-design.md)

---

## 文件结构

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/memedog/store.py` | 修改 | `pipeline_events` 表 + `save_event` / `recent_events` |
| `src/memedog/orchestrator.py` | 修改 | `_emit` 插桩(每阶段发事件) |
| `src/memedog/demo/__init__.py` | 新建 | 包标记 |
| `src/memedog/demo/demo_source.py` | 新建 | `ReplayProvider` / `DemoScanner` / `DemoRugCheckClient` / `DemoEnricher` / `build_demo_snapshot` / `build_demo_price_fn` |
| `src/memedog/app_factory.py` | 修改 | `build_orchestrator(cfg, store, demo=False)` demo 注入 |
| `src/memedog/serve.py` | 新建 | launcher 入口 `python -m memedog.serve` |
| `dashboard/app.py` | 修改 | 顶部"实时活动流"区 + demo 刷新更快 |
| `tests/test_store.py` | 修改/新建 | 事件表往返测试 |
| `tests/test_orchestrator.py` | 修改 | 事件插桩测试 |
| `tests/demo/test_demo_source.py` | 新建 | demo 组件测试 |
| `tests/test_serve.py` | 新建 | launcher 测试(monkeypatch,不真起 streamlit) |
| `tests/test_app_factory.py` | 修改 | demo 注入结构测试 |

---

## Task 1: Store `pipeline_events` 表

**Files:**
- Modify: `src/memedog/store.py`
- Test: `tests/test_store.py`(若不存在则新建)

- [ ] **Step 1: Write the failing test**

> 先确认:`ls tests/test_store.py 2>/dev/null`。存在则追加下面的 class;不存在则新建文件(加顶部 `from memedog.store import Store` 与 import）。

```python
class TestPipelineEvents:
    def test_save_and_recent_events_roundtrip(self, tmp_path):
        from memedog.store import Store

        s = Store(str(tmp_path / "ev.db"))
        try:
            s.save_event("scan", status="ok", detail="5 candidates")
            s.save_event("judge", trace_id="t1", mint="MINT", symbol="DOGX",
                         status="ok", detail="BULLISH 0.78")
            events = s.recent_events(limit=10)
        finally:
            s.close()

        assert len(events) == 2
        # newest first
        assert events[0]["stage"] == "judge"
        assert events[0]["symbol"] == "DOGX"
        assert events[0]["status"] == "ok"
        assert events[0]["detail"] == "BULLISH 0.78"
        from datetime import datetime
        assert isinstance(events[0]["ts"], datetime)
        assert events[1]["stage"] == "scan"

    def test_recent_events_limit(self, tmp_path):
        from memedog.store import Store

        s = Store(str(tmp_path / "ev2.db"))
        try:
            for i in range(10):
                s.save_event("scan", detail=str(i))
            events = s.recent_events(limit=3)
        finally:
            s.close()
        assert len(events) == 3
        assert events[0]["detail"] == "9"  # newest
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_store.py::TestPipelineEvents -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'save_event'`

- [ ] **Step 3: Implement**

在 `src/memedog/store.py`,`_CREATE_FUNNEL_EVENTS` 字符串之后新增 DDL 常量:

```python
_CREATE_PIPELINE_EVENTS = """
CREATE TABLE IF NOT EXISTS pipeline_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    trace_id  TEXT NOT NULL DEFAULT '',
    stage     TEXT NOT NULL,
    mint      TEXT NOT NULL DEFAULT '',
    symbol    TEXT NOT NULL DEFAULT '',
    status    TEXT NOT NULL DEFAULT '',
    detail    TEXT NOT NULL DEFAULT ''
);
"""
```

在 `_create_tables` 末尾加一行:

```python
        cur.execute(_CREATE_PIPELINE_EVENTS)
```

在 `recent_funnel_events` 方法之后新增两个方法:

```python
    def save_event(
        self,
        stage: str,
        *,
        trace_id: str = "",
        mint: str = "",
        symbol: str = "",
        status: str = "",
        detail: str = "",
        ts: "datetime | None" = None,
    ) -> None:
        """Append one pipeline event row (real-time activity stream)."""
        if ts is None:
            ts = datetime.now(tz=timezone.utc)
        self._conn.execute(
            """
            INSERT INTO pipeline_events
              (ts, trace_id, stage, mint, symbol, status, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (_dt_to_str(ts), trace_id, stage, mint, symbol, status, detail),
        )
        self._conn.commit()

    def recent_events(self, limit: int = 50) -> list[dict]:
        """Return the most recent N pipeline events, newest first."""
        cur = self._conn.execute(
            "SELECT * FROM pipeline_events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        result = []
        for row in cur.fetchall():
            result.append(
                {
                    "ts": _str_to_dt(row["ts"]),
                    "trace_id": row["trace_id"],
                    "stage": row["stage"],
                    "mint": row["mint"],
                    "symbol": row["symbol"],
                    "status": row["status"],
                    "detail": row["detail"],
                }
            )
        return result
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_store.py::TestPipelineEvents -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memedog/store.py tests/test_store.py
git commit -m "feat(store): add pipeline_events table + save_event/recent_events"
```

---

## Task 2: Orchestrator `_emit` 插桩

**Files:**
- Modify: `src/memedog/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_orchestrator.py`(文件已存在;import 区按需补 `from memedog.store import Store`)。该测试用一个记录事件的内存 store 包装:

```python
class TestPipelineEventEmission:
    @pytest.mark.asyncio
    async def test_run_cycle_emits_stage_events(self, tmp_path):
        from memedog.store import Store
        from memedog.orchestrator import Orchestrator
        from memedog.models import (
            TokenCandidate, TokenSnapshot, SafetyInfo, HolderInfo,
            MomentumInfo, SocialInfo, Score, DimensionScore, Signal, SignalType,
        )
        from datetime import datetime, timezone

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
            async def enrich(self, c): return snap
        class _SE:
            def score(self, s): return score
        class _Judge:
            async def judge(self, s, sc): return signal
        class _PT:
            def on_signal(self, sig, entry_price=None): return None

        store = Store(str(tmp_path / "o.db"))
        from memedog.config import load_config
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
        """A broken save_event must not break the cycle (still returns signals)."""
        from memedog.orchestrator import Orchestrator
        from memedog.config import load_config
        from datetime import datetime, timezone
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
            async def enrich(self, c): return snap
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
        assert len(signals) == 1  # cycle still completed despite save_event errors
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_orchestrator.py::TestPipelineEventEmission -q`
Expected: FAIL — no `scan`/`score`/`judge` events emitted (stages missing)

- [ ] **Step 3: Implement**

在 `src/memedog/orchestrator.py` 的 `Orchestrator` 类中新增 `_emit` 方法(放在 `run_cycle` 之前):

```python
    def _emit(
        self,
        stage: str,
        *,
        trace_id: str = "",
        mint: str = "",
        symbol: str = "",
        status: str = "",
        detail: str = "",
    ) -> None:
        """Emit a real-time pipeline event. Never raises."""
        try:
            self._store.save_event(
                stage, trace_id=trace_id, mint=mint, symbol=symbol,
                status=status, detail=detail,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("save_event failed for stage=%s: %s", stage, exc)
```

在 `run_cycle` 中插桩(不改业务逻辑,只加 emit 调用):

1) scan 成功后(`logger.info("Cycle: scanner produced ...")` 之后):
```python
        self._emit("scan", status="ok", detail=f"{len(candidates)} candidates")
```

2) hardfilter 成功后(`logger.info("Cycle: hardfilter passed ...")` 之后):
```python
        self._emit("hardfilter", status="ok", detail=f"{len(survivors)}/{len(candidates)} passed")
        for mint_d, reason_d in list(getattr(self._hardfilter, "dropped", [])):
            self._emit("hardfilter", mint=mint_d, status="drop", detail=reason_d)
        for mint_f, reason_f in list(getattr(self._hardfilter, "flagged", [])):
            self._emit("hardfilter", mint=mint_f, status="flag", detail=reason_f)
```

3) 在 per-survivor 循环里,enrich/score/judge/signal/trade 各加 emit。把循环体改为:
```python
        for candidate in survivors:
            mint = candidate.mint
            try:
                self._emit("enrich", trace_id=candidate.trace_id, mint=mint,
                           symbol=candidate.symbol, status="start")
                snap = await self._enricher.enrich(candidate)

                score = self._score_engine.score(snap)
                self._emit("score", trace_id=candidate.trace_id, mint=mint,
                           symbol=candidate.symbol, status="ok",
                           detail=f"{score.total:.1f}/100")

                signal = await self._llm_judge.judge(snap, score)
                degraded = "降级" in signal.rationale
                self._emit("judge", trace_id=candidate.trace_id, mint=mint,
                           symbol=candidate.symbol,
                           status="degraded" if degraded else "ok",
                           detail=f"{signal.signal.value} {signal.confidence:.2f}")

                self._store.save_snapshot(snap)
                self._store.save_signal(signal)
                self._emit("signal", trace_id=candidate.trace_id, mint=mint,
                           symbol=candidate.symbol, status="ok",
                           detail=f"{signal.signal.value} score={signal.score_total:.1f}")

                pos = self._paper_trader.on_signal(signal, entry_price=candidate.price_usd)
                if pos is not None:
                    self._emit("trade", trace_id=candidate.trace_id, mint=mint,
                               symbol=candidate.symbol, status="ok", detail="position opened")

                try:
                    await maybe_notify(signal, self._cfg)
                except Exception as alert_exc:
                    logger.warning("maybe_notify raised unexpectedly for %s: %s", mint, alert_exc)

                signals.append(signal)
                logger.info(
                    "Cycle: processed %s → %s (confidence=%.2f, score=%.1f)",
                    mint, signal.signal.value, signal.confidence, signal.score_total,
                )
            except Exception as exc:
                self._emit("error", mint=mint, status="fail", detail=str(exc)[:200])
                logger.warning(
                    "Cycle: skipping candidate %s due to error: %s", mint, exc, exc_info=True,
                )
```

> 注:保持 `save_snapshot`/`save_signal`/`maybe_notify`/`save_funnel_event` 等既有逻辑不变,仅新增 `_emit` 行与把 `on_signal` 返回值捕获为 `pos` 用于 trade 事件。

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_orchestrator.py -q`
Expected: PASS（含既有 orchestrator 测试 + 2 新)

- [ ] **Step 5: Commit**

```bash
git add src/memedog/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): emit per-stage pipeline events"
```

---

## Task 3: `ReplayProvider`(demo LLM)

**Files:**
- Create: `src/memedog/demo/__init__.py`(空)
- Create: `src/memedog/demo/demo_source.py`
- Test: `tests/demo/__init__.py`(空)、`tests/demo/test_demo_source.py`

- [ ] **Step 1: Write the failing test**

创建 `tests/demo/__init__.py`(空)与 `tests/demo/test_demo_source.py`:

```python
"""Tests for demo source components."""
import json
import pytest

from memedog.demo.demo_source import ReplayProvider


@pytest.mark.asyncio
async def test_replay_provider_cycles_bull_bear_judge():
    p = ReplayProvider()
    # 3 calls per judge() — bull, bear, judge(JSON)
    bull = await p.complete(model="", messages=[{"role": "user", "content": "x"}])
    bear = await p.complete(model="", messages=[{"role": "user", "content": "x"}])
    judge = await p.complete(model="", messages=[{"role": "user", "content": "x"}])
    assert isinstance(bull, str) and bull
    assert isinstance(bear, str) and bear
    parsed = json.loads(judge)
    assert parsed["signal"] in ("BULLISH", "BEARISH", "NEUTRAL")
    assert 0.0 <= parsed["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_replay_provider_never_exhausts():
    p = ReplayProvider()
    # 30 calls (10 judge rounds) must not raise
    for _ in range(30):
        out = await p.complete(model="", messages=[{"role": "user", "content": "x"}])
        assert isinstance(out, str) and out


@pytest.mark.asyncio
async def test_replay_provider_drives_real_judge():
    """ReplayProvider plugged into the real LLMJudge yields a real Signal."""
    from memedog.llmjudge.judge import LLMJudge
    from memedog.config import load_config
    from memedog.demo.demo_source import build_demo_snapshot, DemoScanner
    from memedog.scoring.engine import ScoreEngine

    cfg = load_config()
    cand = (await DemoScanner().scan())[0]
    snap = build_demo_snapshot(cand)
    score = ScoreEngine(cfg=cfg.scoring).score(snap)
    judge = LLMJudge(cfg.llmjudge, provider=ReplayProvider())
    sig = await judge.judge(snap, score)
    assert sig.signal.value in ("BULLISH", "BEARISH", "NEUTRAL")
    assert "降级" not in sig.rationale  # replay succeeded, not degraded
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/demo/test_demo_source.py -q`
Expected: FAIL — `ModuleNotFoundError: memedog.demo`

- [ ] **Step 3: Implement (ReplayProvider 部分)**

创建 `src/memedog/demo/__init__.py`(空)与 `src/memedog/demo/demo_source.py`(本任务先放 ReplayProvider + 嵌入的 judge JSON;DemoScanner/build_demo_snapshot 在 Task 4 补全,但因为 Task 3 测试引用了它们,本步把它们一并最小实现):

```python
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


# --- minimal DemoScanner + build_demo_snapshot (expanded in Task 4) -----------

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
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/demo/test_demo_source.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memedog/demo tests/demo
git commit -m "feat(demo): ReplayProvider + DemoScanner + build_demo_snapshot"
```

---

## Task 4: Demo enricher / rugcheck stub / price fn

**Files:**
- Modify: `src/memedog/demo/demo_source.py`
- Test: `tests/demo/test_demo_source.py`

- [ ] **Step 1: Write the failing test**

追加到 `tests/demo/test_demo_source.py`:

```python
@pytest.mark.asyncio
async def test_demo_enricher_returns_snapshot_offline():
    from memedog.demo.demo_source import DemoScanner, DemoEnricher
    cand = (await DemoScanner().scan())[0]
    snap = await DemoEnricher().enrich(cand)
    assert snap.candidate.mint == cand.mint
    assert snap.safety.available and snap.momentum.available


@pytest.mark.asyncio
async def test_demo_rugcheck_report_parses_and_passes_authorities():
    from memedog.demo.demo_source import DemoRugCheckClient
    from memedog.clients.rugcheck import parse_report
    raw = await DemoRugCheckClient().get_token_report("anymint")
    parsed = parse_report(raw)
    assert parsed["mint_authority_revoked"] is True
    assert parsed["freeze_authority_revoked"] is True


@pytest.mark.asyncio
async def test_demo_price_fn_returns_float():
    from memedog.demo.demo_source import build_demo_price_fn
    fn = build_demo_price_fn()
    price = await fn("anymint")
    assert isinstance(price, float) and price > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/demo/test_demo_source.py -k "demo_enricher or demo_rugcheck or demo_price" -q`
Expected: FAIL — `DemoEnricher` / `DemoRugCheckClient` / `build_demo_price_fn` not defined

- [ ] **Step 3: Implement**

在 `src/memedog/demo/demo_source.py` 末尾追加。先确认 rugcheck 原始报告字段(`parse_report` 读什么):rugcheck `parse_report` 期望原始字段含 `mintAuthority`/`freezeAuthority`(为空/None 表示已撤)、`score`、`risks` 等。用一个能被 `parse_report` 解析为"双撤权 + 低风险"的最小原始 dict:

```python
class DemoEnricher:
    """Offline enricher: returns build_demo_snapshot (no network)."""

    async def enrich(self, candidate: TokenCandidate) -> TokenSnapshot:
        return build_demo_snapshot(candidate)


# Minimal raw RugCheck report shaped so parse_report() yields revoked authorities
# + low risk. Field names mirror the real RugCheck API response.
_DEMO_RUGCHECK_RAW = {
    "mintAuthority": None,
    "freezeAuthority": None,
    "score": 88,
    "score_normalised": 88,
    "risks": [],
    "markets": [{"lp": {"lpLockedPct": 100}}],
    "topHolders": [],
}


class DemoRugCheckClient:
    """Offline RugCheck stub for HardFilter/Enricher in demo mode."""

    async def get_token_report(self, mint: str) -> dict:
        return dict(_DEMO_RUGCHECK_RAW)

    async def aclose(self) -> None:
        return None


def build_demo_price_fn():
    """Return an async price fn doing a small random walk (no network)."""
    async def _price_fn(mint: str):
        return round(0.001 * random.uniform(0.7, 1.6), 8)
    return _price_fn
```

> 实施时必须**核对** `parse_report` 真正读取的字段名(打开 `src/memedog/clients/rugcheck.py` 的 `parse_report`),据此调整 `_DEMO_RUGCHECK_RAW` 使 `parse_report(_DEMO_RUGCHECK_RAW)` 返回 `mint_authority_revoked=True`、`freeze_authority_revoked=True`。测试 `test_demo_rugcheck_report_parses_and_passes_authorities` 即为此守门。

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/demo/test_demo_source.py -q`
Expected: PASS（全部 demo 测试）

- [ ] **Step 5: Commit**

```bash
git add src/memedog/demo/demo_source.py tests/demo/test_demo_source.py
git commit -m "feat(demo): DemoEnricher + DemoRugCheckClient + demo price fn"
```

---

## Task 5: app_factory `demo=True` 注入

**Files:**
- Modify: `src/memedog/app_factory.py`
- Test: `tests/test_app_factory.py`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_app_factory.py`:

```python
def test_build_orchestrator_demo_injects_demo_components(cfg, store):
    from memedog.app_factory import build_orchestrator
    from memedog.demo.demo_source import DemoScanner, DemoEnricher, ReplayProvider

    orch = build_orchestrator(cfg, store, demo=True)
    assert isinstance(orch._scanner, DemoScanner)
    assert isinstance(orch._enricher, DemoEnricher)
    # judge uses the ReplayProvider (injected provider attribute)
    assert isinstance(orch._llm_judge._injected_provider, ReplayProvider)


@pytest.mark.asyncio
async def test_build_orchestrator_demo_cycle_runs_offline(cfg, store):
    """A full demo run_cycle produces a signal + events, fully offline."""
    from memedog.app_factory import build_orchestrator

    orch = build_orchestrator(cfg, store, demo=True)
    signals = await orch.run_cycle()
    assert len(signals) >= 1
    stages = [e["stage"] for e in store.recent_events(limit=50)]
    assert "judge" in stages and "signal" in stages
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_app_factory.py -k demo -q`
Expected: FAIL — `build_orchestrator() got an unexpected keyword argument 'demo'`

- [ ] **Step 3: Implement**

在 `src/memedog/app_factory.py`,把 `build_orchestrator` 签名改为带 `demo=False`,并在 demo 分支替换 scanner/enricher/judge + hardfilter 的 rugcheck:

```python
def build_orchestrator(cfg: Config, store: Store, demo: bool = False) -> Orchestrator:
```

在函数体构造 modules 处,demo 时替换。具体:在现有 `scanner = Scanner(...)` / `hardfilter = HardFilter(...)` / `enricher = Enricher(...)` / `llm_judge = LLMJudge(...)` 这组构造**之前**加分支:

```python
    if demo:
        from memedog.demo.demo_source import (
            DemoScanner, DemoEnricher, DemoRugCheckClient, ReplayProvider,
        )
        demo_rug = DemoRugCheckClient()
        scanner = DemoScanner()
        hardfilter = HardFilter(rugcheck=demo_rug, cfg=cfg.hardfilter)
        enricher = DemoEnricher()
        score_engine = ScoreEngine(cfg=cfg.scoring)
        llm_judge = LLMJudge(cfg.llmjudge, provider=ReplayProvider())
        paper_trader = PaperTrader(store=store, cfg=cfg.papertrader)
        return Orchestrator(
            scanner=scanner, hardfilter=hardfilter, enricher=enricher,
            score_engine=score_engine, llm_judge=llm_judge,
            paper_trader=paper_trader, store=store, cfg=cfg,
        )
```

> 放在数据 client 构造之前即可短路返回,demo 不创建真实 HTTP client。生产路径(`demo=False`)保持原样不变。

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_app_factory.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memedog/app_factory.py tests/test_app_factory.py
git commit -m "feat(app_factory): demo=True injects offline demo components"
```

---

## Task 6: Launcher `serve.py`

**Files:**
- Create: `src/memedog/serve.py`
- Test: `tests/test_serve.py`

- [ ] **Step 1: Write the failing test**

创建 `tests/test_serve.py`:

```python
"""Tests for the serve launcher (no real streamlit / network)."""
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from memedog import serve


def test_build_streamlit_cmd_includes_port_and_app():
    cmd = serve.build_streamlit_cmd(port=8599, dashboard_path="dashboard/app.py")
    assert "streamlit" in cmd
    assert "run" in cmd
    assert "dashboard/app.py" in cmd
    assert "8599" in cmd


def test_parse_args_demo_and_port():
    args = serve.parse_args(["--demo", "--port", "8600", "--db", "x.db"])
    assert args.demo is True
    assert args.port == 8600
    assert args.db == "x.db"


@pytest.mark.asyncio
async def test_run_server_spawns_and_terminates(tmp_path, monkeypatch):
    """run_server starts streamlit via injected popen and terminates it on stop."""
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None  # still running
    spawned = {}

    def fake_popen(cmd, **kw):
        spawned["cmd"] = cmd
        return fake_proc

    stop_event = asyncio.Event()

    # stop almost immediately so the backend loop exits fast
    async def _stopper():
        await asyncio.sleep(0.05)
        stop_event.set()

    monkeypatch.setenv("MEMEDOG_DB", str(tmp_path / "serve.db"))
    asyncio.create_task(_stopper())
    await serve.run_server(
        demo=True, port=8601, db_path=str(tmp_path / "serve.db"),
        stop_event=stop_event, popen=fake_popen,
    )
    assert "cmd" in spawned  # streamlit was launched
    fake_proc.terminate.assert_called()  # terminated on shutdown
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_serve.py -q`
Expected: FAIL — `ModuleNotFoundError: memedog.serve` / attrs missing

- [ ] **Step 3: Implement**

创建 `src/memedog/serve.py`:

```python
"""One-command local server: backend pipeline loop + Streamlit dashboard.

Usage:
    python -m memedog.serve [--demo] [--db PATH] [--port N] [--scan-interval S]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_DASHBOARD = str(Path(__file__).resolve().parents[2] / "dashboard" / "app.py")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="memedog.serve")
    p.add_argument("--demo", action="store_true", help="offline demo mode (fixtures + replay LLM)")
    p.add_argument("--db", default=os.environ.get("MEMEDOG_DB", "memedog.db"))
    p.add_argument("--port", type=int, default=8501)
    p.add_argument("--scan-interval", type=int, default=None)
    return p.parse_args(argv)


def build_streamlit_cmd(port: int, dashboard_path: str) -> list[str]:
    return [
        sys.executable, "-m", "streamlit", "run", dashboard_path,
        "--server.port", str(port), "--server.headless", "true",
    ]


async def run_server(
    *,
    demo: bool,
    port: int,
    db_path: str,
    stop_event: asyncio.Event,
    scan_interval: int | None = None,
    popen=subprocess.Popen,
) -> None:
    """Run backend loop + streamlit subprocess until stop_event is set."""
    from memedog.app_factory import build_orchestrator, build_price_fn
    from memedog.clients.dexscreener import DexScreenerClient
    from memedog.config import load_config
    from memedog.observability.redaction import install_redaction
    from memedog.papertrader.watcher import PriceWatcher
    from memedog.store import Store

    os.environ["MEMEDOG_DB"] = db_path
    if demo:
        os.environ["MEMEDOG_DEMO"] = "1"

    cfg = load_config()
    install_redaction(cfg.settings)
    if scan_interval is not None:
        cfg.scanner.scan_interval_sec = scan_interval
    elif demo:
        cfg.scanner.scan_interval_sec = 3  # snappy demo cadence

    store = Store(db_path)
    orch = build_orchestrator(cfg, store, demo=demo)

    # Price source: real for production, random-walk for demo.
    dex_client = None
    if demo:
        from memedog.demo.demo_source import build_demo_price_fn
        price_fn = build_demo_price_fn()
    else:
        dex_client = DexScreenerClient()
        price_fn = build_price_fn(dex_client)

    watcher = PriceWatcher(store=store, trader=orch.paper_trader,
                           price_fn=price_fn, cfg=cfg.papertrader)

    proc = popen(build_streamlit_cmd(port, _DASHBOARD))
    logger.info("Streamlit launched on port %d (db=%s, demo=%s)", port, db_path, demo)

    async def _backend():
        await asyncio.gather(
            orch.run_forever(stop_event=stop_event),
            watcher.run(stop_event=stop_event),
        )

    backend_task = asyncio.create_task(_backend())
    try:
        await stop_event.wait()
    finally:
        backend_task.cancel()
        try:
            await backend_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        if dex_client is not None:
            await dex_client.aclose()
        store.close()
        logger.info("Server stopped.")


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )
    args = parse_args(argv)
    stop_event = asyncio.Event()

    async def _run():
        await run_server(
            demo=args.demo, port=args.port, db_path=args.db,
            stop_event=stop_event, scan_interval=args.scan_interval,
        )

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nmemedog.serve: interrupted — shutting down", file=sys.stderr)


if __name__ == "__main__":
    main()
```

> 说明:`run_server` 在 `stop_event` 触发后取消 backend、terminate streamlit、关 store。测试通过注入 `popen` 与提前 set `stop_event` 验证,不真起 streamlit。KeyboardInterrupt(Ctrl-C)由 `asyncio.run` 抛出后由 `main` 捕获;run_forever/watcher 收到 CancelledError 退出。

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_serve.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memedog/serve.py tests/test_serve.py
git commit -m "feat: one-command serve launcher (backend loop + streamlit subprocess)"
```

---

## Task 7: Dashboard 实时活动流

**Files:**
- Modify: `dashboard/app.py`
- Test: `tests/test_dashboard.py`(若不存在则新建)

- [ ] **Step 1: Write the failing test**

> 先确认 `ls tests/test_dashboard.py 2>/dev/null`。dashboard 渲染依赖 streamlit;若无法在测试环境调 `main()`,改为对新增 helper 做纯函数测试。本任务把活动流渲染逻辑抽成纯函数 `format_event_row(event) -> str` 便于离线测试。

创建/追加 `tests/test_dashboard.py`:

```python
def test_format_event_row_contains_stage_and_symbol():
    from dashboard.app import format_event_row
    from datetime import datetime, timezone

    row = format_event_row({
        "ts": datetime(2024, 1, 1, 12, 30, 5, tzinfo=timezone.utc),
        "trace_id": "t1", "stage": "judge", "mint": "M1",
        "symbol": "DOGX", "status": "ok", "detail": "BULLISH 0.78",
    })
    assert "judge" in row.lower()
    assert "DOGX" in row
    assert "BULLISH 0.78" in row
    assert "12:30:05" in row


def test_format_event_row_handles_empty_symbol():
    from dashboard.app import format_event_row
    from datetime import datetime, timezone

    row = format_event_row({
        "ts": datetime(2024, 1, 1, tzinfo=timezone.utc),
        "trace_id": "", "stage": "scan", "mint": "",
        "symbol": "", "status": "ok", "detail": "5 candidates",
    })
    assert "scan" in row.lower()
    assert "5 candidates" in row
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_dashboard.py -q`
Expected: FAIL — `cannot import name 'format_event_row'`

- [ ] **Step 3: Implement**

在 `dashboard/app.py` 顶部(`main()` 之外,模块级)新增纯函数:

```python
_STAGE_ICONS = {
    "scan": "🔍", "hardfilter": "🚧", "enrich": "🧪", "score": "📊",
    "judge": "⚖️", "signal": "📣", "trade": "💰", "error": "❌",
}


def format_event_row(event: dict) -> str:
    """Render one pipeline event as a compact one-line string."""
    icon = _STAGE_ICONS.get(event.get("stage", ""), "•")
    ts = event.get("ts")
    tstr = ts.strftime("%H:%M:%S") if hasattr(ts, "strftime") else str(ts)
    sym = event.get("symbol") or event.get("mint", "")[:8] or "—"
    status = event.get("status", "")
    detail = event.get("detail", "")
    return f"{tstr}  {icon} {event.get('stage','')}  {sym}  [{status}]  {detail}".rstrip()
```

在 `main()` 内、`st.title(...)` 之后、"Section 1" 之前,插入实时活动流区:

```python
        # ------------------------------------------------------------------
        # Section 0: Live activity stream
        # ------------------------------------------------------------------
        st.header("🔴 实时活动流 (Live Activity)")
        try:
            events = store.recent_events(limit=40)
        except Exception:
            events = []
        if not events:
            st.info("暂无事件。运行 `python -m memedog.serve --demo` 让漏斗流动起来。")
        else:
            st.code("\n".join(format_event_row(e) for e in events), language=None)
```

把 autorefresh 默认间隔在 demo 下调快:找到 `_REFRESH_DEFAULT_SEC = 30`,改为:

```python
    import os as _os
    _REFRESH_DEFAULT_SEC = 3 if _os.environ.get("MEMEDOG_DEMO") == "1" else 30
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_dashboard.py -q`
Expected: PASS

并做 dashboard 语法/渲染 smoke:
Run: `python -c "import ast; ast.parse(open('dashboard/app.py',encoding='utf-8').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add dashboard/app.py tests/test_dashboard.py
git commit -m "feat(dashboard): live activity stream section + faster demo refresh"
```

---

## Task 8: 全量测试 + 真实端到端验证 + 合并

**Files:** 无改动(验证 + 必要修补)

- [ ] **Step 1: 默认全量套件**

Run: `python -m pytest -q`
Expected: 全过(新增 ~15 测试)。失败则定位修复后重跑。

- [ ] **Step 2: 零外部联网证明**

Run: `python -m pytest -q --disable-socket --allow-hosts=127.0.0.1,::1,localhost`
Expected: 全过且无外部网络调用。

- [ ] **Step 3: 真实 demo 端到端小验证(离线、确定性、非 mock)**

写一次性脚本 `scripts/_demo_smoke.py`(验证后删):

```python
import asyncio, tempfile, os
from memedog.config import load_config
from memedog.app_factory import build_orchestrator
from memedog.store import Store

async def main():
    db = os.path.join(tempfile.mkdtemp(), "demo.db")
    store = Store(db)
    orch = build_orchestrator(load_config(), store, demo=True)
    for _ in range(3):
        await orch.run_cycle()
    events = store.recent_events(limit=100)
    stages = {e["stage"] for e in events}
    sigs = store.recent_signals(limit=10)
    store.close()
    assert {"scan", "hardfilter", "score", "judge", "signal"} <= stages, stages
    assert len(sigs) >= 1, "no signals produced"
    print("demo smoke OK — stages:", sorted(stages), "signals:", len(sigs))

asyncio.run(main())
```

Run: `PYTHONPATH=src python scripts/_demo_smoke.py` then `rm scripts/_demo_smoke.py`
Expected: `demo smoke OK — stages: [...] signals: N`

- [ ] **Step 4: Launcher 冒烟(真起 streamlit,手动确认后 Ctrl-C)**

> 可选人工验证(需要本机有 streamlit)。Run(后台或单独终端):`python -m memedog.serve --demo --port 8599`
> 打开 http://localhost:8599 应看到"实时活动流"随后端滚动;Ctrl-C 应干净退出。自动化测试已覆盖逻辑,此步仅人工观感确认,可跳过。

- [ ] **Step 5: 合并回 main(分支上先 review 再合)**

```bash
git checkout main
git merge --no-ff feature/realtime-server -m "feat: realtime observability + one-command local server (sub-project C)"
python -m pytest -q   # verify on merged result
git branch -d feature/realtime-server
```

---

## 自审清单(写计划后)

- **Spec 覆盖**:① 事件流=Task1(store)+Task2(orchestrator);② launcher=Task6;③ demo(scanner/enricher/rugcheck/replay/price)=Task3+Task4,注入=Task5;④ 看板实时流=Task7;测试=Task1–8;端到端真实 demo=Task8 Step3。✅
- **占位符**:无 TBD/TODO;每步含完整代码与命令。✅
- **类型一致**:`save_event`/`recent_events`(Task1,被 Task2/5/8 用)、`ReplayProvider`/`DemoScanner`/`build_demo_snapshot`(Task3,被 Task4/5 用)、`DemoEnricher`/`DemoRugCheckClient`/`build_demo_price_fn`(Task4,被 Task5/6 用)、`build_orchestrator(...,demo=False)`(Task5,被 Task6/8 用)、`run_server`/`build_streamlit_cmd`/`parse_args`(Task6)、`format_event_row`(Task7)前后一致。✅
- **关键风险点**:`_DEMO_RUGCHECK_RAW` 必须让 `parse_report` 解析出双撤权(Task4 实施时核对 rugcheck.parse_report 字段名,测试守门)。`orch._llm_judge._injected_provider` 属性名需与 LLMJudge 实际一致(已确认 judge.py 用 `self._injected_provider`)。✅
- **向后兼容**:事件表新增不影响既有读路径;`build_orchestrator` 新增 `demo=False` 默认 → 既有调用不变;dashboard 新增区在无事件时显示提示。✅
