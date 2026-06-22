# 信号质量深化 — LLMJudge 多步推理 workflow 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 LLMJudge 看见原始链上数据、按 6 步 workflow 推理、输出可审计的分步结论,并用完备度护栏校准置信度。

**Architecture:** 只动 LLMJudge 层(`prompts.py` + `judge.py` + `config/settings.py` 的 judge 段 + `thresholds.yaml`)。保留 Bull/Bear/Judge 三次 codex 调用的真辩论。证据块把 `TokenSnapshot` 原始值灌进三个 prompt;judge prompt 内嵌固定 6 步推理指令;`JudgeOut` 向后兼容新增 `workflow` 字段;置信度受完备度护栏约束。ScoreEngine / HardFilter / clients / models / store 不动。

**Tech Stack:** Python 3.11+, pydantic v2, pytest + pytest-asyncio, codex CLI(live 层), respx(无关本子项目)。

参考 spec:[docs/superpowers/specs/2026-06-22-signal-quality-llmjudge-design.md](../specs/2026-06-22-signal-quality-llmjudge-design.md)

---

## 文件结构

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/memedog/llmjudge/judge.py` | 修改 | `StepFinding` / `JudgeOut.workflow`;workflow 折叠进 rationale;置信度护栏 |
| `src/memedog/llmjudge/prompts.py` | 修改 | `_snapshot_evidence()` 证据块;bull/bear 携带证据;judge 6 步 workflow |
| `src/memedog/config/settings.py` | 修改 | `ConfidenceGuardConfig` + `LLMJudgeConfig.confidence_guard`(带默认值) |
| `src/memedog/config/thresholds.yaml` | 修改 | `llmjudge.confidence_guard: { enabled, floor }` |
| `tests/llmjudge/test_prompts.py` | 修改 | 证据块/6 步 workflow 断言 |
| `tests/llmjudge/test_judge.py` | 修改 | workflow 解析/护栏/rationale 折叠;更新 fixture 等值断言 |
| `tests/fixtures/codex/judge_bullish.json` | 修改 | 真实重捕,含 `workflow` 数组 |
| `tests/fixtures/codex/judge_bearish.json` | 修改 | 真实重捕,含 `workflow` 数组 |

---

## Task 1: `JudgeOut.workflow` schema(向后兼容)

**Files:**
- Modify: `src/memedog/llmjudge/judge.py`
- Test: `tests/llmjudge/test_judge.py`

- [ ] **Step 1: Write the failing tests**

在 `tests/llmjudge/test_judge.py` 顶部 import 区后追加:

```python
from memedog.llmjudge.judge import StepFinding


def test_judgeout_parses_workflow_field():
    """JudgeOut accepts a structured workflow array."""
    data = {
        "signal": "BULLISH",
        "confidence": 0.7,
        "bull_points": ["x"],
        "bear_points": ["y"],
        "red_flags": [],
        "rationale": "ok",
        "workflow": [
            {"step": "safety", "assessment": "pass", "note": "authorities revoked"},
            {"step": "momentum", "assessment": "concern", "note": "thin volume"},
        ],
    }
    out = JudgeOut.model_validate(data)
    assert len(out.workflow) == 2
    assert out.workflow[0].step == "safety"
    assert out.workflow[0].assessment == "pass"
    assert isinstance(out.workflow[1], StepFinding)


def test_judgeout_workflow_defaults_empty_when_absent():
    """Old bodies without 'workflow' still parse (backward compat)."""
    data = {
        "signal": "BEARISH",
        "confidence": 0.6,
        "bull_points": [],
        "bear_points": ["z"],
        "red_flags": ["flag"],
        "rationale": "old body",
    }
    out = JudgeOut.model_validate(data)
    assert out.workflow == []
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/llmjudge/test_judge.py::test_judgeout_parses_workflow_field tests/llmjudge/test_judge.py::test_judgeout_workflow_defaults_empty_when_absent -v`
Expected: FAIL — `ImportError: cannot import name 'StepFinding'`

- [ ] **Step 3: Implement**

在 `src/memedog/llmjudge/judge.py`,把现有 `JudgeOut` 替换为(新增 `StepFinding` 并加 `workflow` 字段):

```python
class StepFinding(BaseModel):
    """One step of the judge's multi-step reasoning workflow."""

    step: str        # "safety" | "concentration" | "momentum" | "social" | "debate"
    assessment: str  # "pass" | "concern" | "fail" | "neutral" | "missing"
    note: str = ""


class JudgeOut(BaseModel):
    """Schema for the LLM judge's final JSON output."""

    signal: str
    confidence: float
    bull_points: list[str]
    bear_points: list[str]
    red_flags: list[str]
    rationale: str
    workflow: list[StepFinding] = []
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/llmjudge/test_judge.py -v`
Expected: PASS(全部既有 + 2 新增)

- [ ] **Step 5: Commit**

```bash
git add src/memedog/llmjudge/judge.py tests/llmjudge/test_judge.py
git commit -m "feat(llmjudge): add backward-compatible workflow field to JudgeOut"
```

---

## Task 2: 置信度完备度护栏 config

**Files:**
- Modify: `src/memedog/config/settings.py`
- Modify: `src/memedog/config/thresholds.yaml`
- Test: `tests/config/` 下(若无则在 `tests/llmjudge/test_judge.py` 内加 config 测试)

> 说明:先确认 `tests/config/` 是否存在。Run: `ls tests/config 2>/dev/null`。不存在则把下面的测试放进 `tests/llmjudge/test_judge.py`。

- [ ] **Step 1: Write the failing test**

追加到 `tests/llmjudge/test_judge.py`:

```python
def test_config_has_confidence_guard_defaults():
    """LLMJudgeConfig exposes a confidence_guard with enabled + floor."""
    from memedog.config import load_config

    cfg = load_config().llmjudge
    assert hasattr(cfg, "confidence_guard")
    assert cfg.confidence_guard.enabled is True
    assert 0.0 <= cfg.confidence_guard.floor <= 1.0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/llmjudge/test_judge.py::test_config_has_confidence_guard_defaults -v`
Expected: FAIL — `AttributeError: ... has no attribute 'confidence_guard'`

- [ ] **Step 3: Implement**

在 `src/memedog/config/settings.py`,`CodexConfig` 之后、`LLMJudgeConfig` 之前新增:

```python
class ConfidenceGuardConfig(BaseModel):
    """Caps LLM confidence by data completeness (available dimensions / 4)."""

    enabled: bool = True
    floor: float = 0.5
```

并把 `LLMJudgeConfig` 改为(新增带默认值的字段,保持现有测试 `_make_fake_cfg` 不传也能用):

```python
class LLMJudgeConfig(BaseModel):
    models: dict[str, str]
    temperature: dict[str, float]
    max_tokens: int
    repair_retries: int
    codex: CodexConfig
    confidence_guard: ConfidenceGuardConfig = ConfidenceGuardConfig()
```

在 `src/memedog/config/thresholds.yaml` 的 `llmjudge:` 段(`codex:` 行之后)加一行:

```yaml
  confidence_guard: { enabled: true, floor: 0.5 }
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/llmjudge/test_judge.py::test_config_has_confidence_guard_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memedog/config/settings.py src/memedog/config/thresholds.yaml tests/llmjudge/test_judge.py
git commit -m "feat(config): add llmjudge.confidence_guard (enabled + floor)"
```

---

## Task 3: `_snapshot_evidence()` 证据块

**Files:**
- Modify: `src/memedog/llmjudge/prompts.py`
- Test: `tests/llmjudge/test_prompts.py`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/llmjudge/test_prompts.py`(import 区加 `from memedog.llmjudge.prompts import _snapshot_evidence`):

```python
@pytest.fixture
def snapshot_rich(candidate):
    return TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(
            available=True, mint_authority_revoked=True, freeze_authority_revoked=True,
            lp_burned_or_locked=True, rug_trust_score=78, rug_risk_level="LOW",
        ),
        holders=HolderInfo(
            available=True, top10_pct=24.5, max_wallet_pct=6.2,
            dev_wallet_pct=3.1, holder_count=412, sniper_pct=8.0,
        ),
        momentum=MomentumInfo(
            available=True, liquidity_usd=42300.0, volume_5m=18400.0, volume_1h=96200.0,
            buy_sell_ratio_5m=1.8, unique_buyers_1h=210, fdv_to_liquidity=3.2,
        ),
        social=SocialInfo(available=False),
        enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def test_evidence_contains_raw_values(snapshot_rich, score):
    text = _snapshot_evidence(snapshot_rich, score)
    assert "42,300" in text          # liquidity formatted with thousands sep
    assert "24.5%" in text           # top10 pct
    assert "78" in text              # trust score
    assert "1.80" in text            # buy/sell ratio 2dp


def test_evidence_marks_missing_dimension(snapshot_rich, score):
    text = _snapshot_evidence(snapshot_rich, score)
    # social is unavailable
    assert "SOCIAL" in text.upper()
    assert "DATA MISSING" in text.upper() or "缺失" in text


def test_evidence_omits_none_fields(candidate, score):
    # holders available but only top10 set; others None must not render "None"
    snap = TokenSnapshot(
        candidate=candidate,
        safety=SafetyInfo(available=True, rug_trust_score=80),
        holders=HolderInfo(available=True, top10_pct=20.0),
        momentum=MomentumInfo(available=True, liquidity_usd=30000.0),
        social=SocialInfo(available=False),
        enriched_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    text = _snapshot_evidence(snap, score)
    assert "None" not in text


def test_evidence_includes_prescore_reference(snapshot_rich, score):
    text = _snapshot_evidence(snapshot_rich, score)
    # the composite pre-score (72.5 from the `score` fixture) appears as reference
    assert "72.5" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/llmjudge/test_prompts.py -k evidence -v`
Expected: FAIL — `ImportError: cannot import name '_snapshot_evidence'`

- [ ] **Step 3: Implement**

在 `src/memedog/llmjudge/prompts.py` 顶部 import 之后新增格式化助手与证据块函数:

```python
def _fmt_money(v: float) -> str:
    try:
        return f"${v:,.0f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_pct(v: float) -> str:
    try:
        return f"{v:.1f}%"
    except (TypeError, ValueError):
        return str(v)


def _fmt_ratio(v: float) -> str:
    try:
        return f"{v:.2f}"
    except (TypeError, ValueError):
        return str(v)


def _evidence_line(label: str, available: bool, fields: list[tuple[str, str]]) -> str:
    """Render one dimension line; DATA MISSING when unavailable or all fields empty."""
    if not available or not fields:
        return f"{label:<22}DATA MISSING (数据缺失)"
    body = "  ".join(f"{name}={val}" for name, val in fields)
    return f"{label:<22}{body}"


def _snapshot_evidence(snapshot: TokenSnapshot, score: Score) -> str:
    """Render the raw on-chain evidence block shared by all three prompts."""
    s = snapshot.safety
    h = snapshot.holders
    m = snapshot.momentum
    soc = snapshot.social

    safety_fields: list[tuple[str, str]] = []
    if s.mint_authority_revoked is not None:
        safety_fields.append(("mint撤权", str(s.mint_authority_revoked)))
    if s.freeze_authority_revoked is not None:
        safety_fields.append(("freeze撤权", str(s.freeze_authority_revoked)))
    if s.lp_burned_or_locked is not None:
        safety_fields.append(("LP烧/锁", str(s.lp_burned_or_locked)))
    if s.rug_trust_score is not None:
        safety_fields.append(("trust", f"{s.rug_trust_score}/100"))
    if s.rug_risk_level is not None:
        safety_fields.append(("risk", str(s.rug_risk_level)))

    holder_fields: list[tuple[str, str]] = []
    if h.top10_pct is not None:
        holder_fields.append(("top10", _fmt_pct(h.top10_pct)))
    if h.max_wallet_pct is not None:
        holder_fields.append(("最大钱包", _fmt_pct(h.max_wallet_pct)))
    if h.dev_wallet_pct is not None:
        holder_fields.append(("dev", _fmt_pct(h.dev_wallet_pct)))
    if h.holder_count is not None:
        holder_fields.append(("持币人", str(h.holder_count)))
    if h.sniper_pct is not None:
        holder_fields.append(("sniper", _fmt_pct(h.sniper_pct)))

    mom_fields: list[tuple[str, str]] = []
    if m.liquidity_usd is not None:
        mom_fields.append(("流动性", _fmt_money(m.liquidity_usd)))
    if m.volume_5m is not None:
        mom_fields.append(("5min量", _fmt_money(m.volume_5m)))
    if m.volume_1h is not None:
        mom_fields.append(("1h量", _fmt_money(m.volume_1h)))
    if m.buy_sell_ratio_5m is not None:
        mom_fields.append(("买卖比", _fmt_ratio(m.buy_sell_ratio_5m)))
    if m.unique_buyers_1h is not None:
        mom_fields.append(("独立买家", str(m.unique_buyers_1h)))
    if m.fdv_to_liquidity is not None:
        mom_fields.append(("FDV/流", _fmt_ratio(m.fdv_to_liquidity)))

    soc_fields: list[tuple[str, str]] = []
    if soc.smart_money_buys is not None:
        soc_fields.append(("聪明钱买入", str(soc.smart_money_buys)))
    if soc.twitter_mentions_1h is not None:
        soc_fields.append(("推特提及", str(soc.twitter_mentions_1h)))
    if soc.twitter_growth is not None:
        soc_fields.append(("推特增速", _fmt_ratio(soc.twitter_growth)))

    lines = [
        _evidence_line("SAFETY (RugCheck):", s.available, safety_fields),
        _evidence_line("HOLDERS (Helius):", h.available, holder_fields),
        _evidence_line("MOMENTUM (DexScreen):", m.available, mom_fields),
        _evidence_line("SOCIAL:", soc.available, soc_fields),
    ]

    dim_map = {d.name: d.raw for d in score.dimensions}
    pre = (
        f"[规则预筛分(参考,非最终结论): 总分 {score.total:.1f}/100 | "
        f"safety {dim_map.get('safety', float('nan')):.0f} "
        f"holders {dim_map.get('holders', float('nan')):.0f} "
        f"momentum {dim_map.get('momentum', float('nan')):.0f} "
        f"social {dim_map.get('social', float('nan')):.0f}]"
    )
    lines.append(pre)
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/llmjudge/test_prompts.py -k evidence -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memedog/llmjudge/prompts.py tests/llmjudge/test_prompts.py
git commit -m "feat(llmjudge): add _snapshot_evidence raw-data block"
```

---

## Task 4: Bull / Bear prompt 携带证据块

**Files:**
- Modify: `src/memedog/llmjudge/prompts.py`
- Test: `tests/llmjudge/test_prompts.py`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/llmjudge/test_prompts.py`:

```python
def test_bull_prompt_injects_raw_evidence(snapshot_rich, score):
    msgs = bull_prompt(snapshot_rich, score)
    all_text = " ".join(m["content"] for m in msgs)
    assert "42,300" in all_text          # raw liquidity present
    assert "top10" in all_text


def test_bull_prompt_demands_data_citation(snapshot_rich, score):
    msgs = bull_prompt(snapshot_rich, score)
    all_text = " ".join(m["content"] for m in msgs).lower()
    assert "cite" in all_text or "引用" in all_text


def test_bear_prompt_injects_raw_evidence(snapshot_rich, score):
    msgs = bear_prompt(snapshot_rich, score)
    all_text = " ".join(m["content"] for m in msgs)
    assert "42,300" in all_text
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/llmjudge/test_prompts.py -k "injects_raw_evidence or demands_data_citation" -v`
Expected: FAIL — assertions on raw values not present (current prompts only carry dimension scores)

- [ ] **Step 3: Implement**

在 `src/memedog/llmjudge/prompts.py` 改写 `bull_prompt` 和 `bear_prompt`,用证据块替换 `_dimension_summary`:

```python
def bull_prompt(snapshot: TokenSnapshot, score: Score) -> list[LLMMessage]:
    """Render a bullish advocate prompt grounded in raw evidence."""
    symbol = snapshot.candidate.symbol
    mint = snapshot.candidate.mint
    evidence = _snapshot_evidence(snapshot, score)
    missing_note = _missing_note(snapshot)

    system_content = (
        "You are a bullish crypto analyst. Identify all positive signals and reasons to BUY. "
        "Cite concrete numbers from the evidence (引用证据中的具体数字). "
        "Do NOT invent data for DATA MISSING dimensions — treat them as elevated uncertainty."
    )
    user_content = (
        f"Analyze token {symbol} (mint: {mint}).\n\n"
        f"=== EVIDENCE (raw on-chain data) ===\n{evidence}"
        f"{missing_note}\n\n"
        "Make the strongest BULLISH case. Each bull point MUST cite a specific field/number above."
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


def bear_prompt(snapshot: TokenSnapshot, score: Score) -> list[LLMMessage]:
    """Render a bearish advocate prompt grounded in raw evidence."""
    symbol = snapshot.candidate.symbol
    mint = snapshot.candidate.mint
    evidence = _snapshot_evidence(snapshot, score)
    missing_note = _missing_note(snapshot)

    system_content = (
        "You are a bearish crypto analyst / risk officer. Identify all risks, red flags, and "
        "reasons to AVOID. Cite concrete numbers from the evidence (引用证据中的具体数字). "
        "Do NOT invent data for DATA MISSING dimensions — treat them as elevated uncertainty."
    )
    user_content = (
        f"Analyze token {symbol} (mint: {mint}).\n\n"
        f"=== EVIDENCE (raw on-chain data) ===\n{evidence}"
        f"{missing_note}\n\n"
        "Make the strongest BEARISH case. Each bear point / red flag MUST cite a specific field/number above."
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/llmjudge/test_prompts.py -v`
Expected: PASS(既有 bull/bear 测试 + 新增。`test_bull_prompt_notes_missing_dimension` 仍过,因为 `_missing_note` 保留)

- [ ] **Step 5: Commit**

```bash
git add src/memedog/llmjudge/prompts.py tests/llmjudge/test_prompts.py
git commit -m "feat(llmjudge): bull/bear prompts cite raw evidence block"
```

---

## Task 5: Judge prompt 6 步 workflow

**Files:**
- Modify: `src/memedog/llmjudge/prompts.py`
- Test: `tests/llmjudge/test_prompts.py`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/llmjudge/test_prompts.py`:

```python
def test_judge_prompt_lists_workflow_steps(snapshot_all_available, score):
    msgs = judge_prompt(snapshot_all_available, score, "bull", "bear")
    all_text = " ".join(m["content"] for m in msgs).lower()
    for step in ["safety", "concentration", "momentum", "social", "debate"]:
        assert step in all_text, f"workflow step '{step}' missing from judge prompt"


def test_judge_prompt_requests_workflow_json_field(snapshot_all_available, score):
    msgs = judge_prompt(snapshot_all_available, score, "bull", "bear")
    all_text = " ".join(m["content"] for m in msgs)
    assert "workflow" in all_text


def test_judge_prompt_injects_raw_evidence(snapshot_rich, score):
    msgs = judge_prompt(snapshot_rich, score, "bull", "bear")
    all_text = " ".join(m["content"] for m in msgs)
    assert "42,300" in all_text
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/llmjudge/test_prompts.py -k "workflow or judge_prompt_injects" -v`
Expected: FAIL — workflow steps / field not present

- [ ] **Step 3: Implement**

在 `src/memedog/llmjudge/prompts.py` 改写 `judge_prompt`:

```python
def judge_prompt(
    snapshot: TokenSnapshot,
    score: Score,
    bull_text: str,
    bear_text: str,
) -> list[LLMMessage]:
    """Render the impartial judge prompt with a fixed 6-step workflow."""
    symbol = snapshot.candidate.symbol
    mint = snapshot.candidate.mint
    evidence = _snapshot_evidence(snapshot, score)
    missing_note = _missing_note(snapshot)

    system_content = (
        "You are an impartial trading signal judge. Reason through a fixed workflow, then "
        "output a single structured JSON object. No prose outside the JSON."
    )
    user_content = (
        f"Token: {symbol} (mint: {mint})\n\n"
        f"=== EVIDENCE (raw on-chain data) ===\n{evidence}"
        f"{missing_note}\n\n"
        f"=== BULL ARGUMENT ===\n{bull_text}\n\n"
        f"=== BEAR ARGUMENT ===\n{bear_text}\n\n"
        "Reason through these ordered steps before deciding:\n"
        "  1. safety        — hard red lines? (mint/freeze authority not revoked, LP not burned/locked, CRITICAL/HIGH risk)\n"
        "  2. concentration — top10 / largest wallet / dev / sniper healthy or concerning?\n"
        "  3. momentum      — liquidity floor, 5m-vs-1h volume trend, buy pressure, FDV/liquidity sanity\n"
        "  4. social        — weigh if available; if DATA MISSING, raise uncertainty (do not invent)\n"
        "  5. debate        — which bull/bear points are data-backed vs speculative\n"
        "  6. verdict       — map to BULLISH/BEARISH/NEUTRAL; LOWER confidence when key dimensions are missing\n\n"
        "Output ONLY a valid JSON object (no prose, no code fences) with these fields:\n"
        "{\n"
        '  "signal": "<one of: BULLISH, BEARISH, NEUTRAL>",\n'
        '  "confidence": <float between 0.0 and 1.0>,\n'
        '  "bull_points": ["<key bull point citing data>", ...],\n'
        '  "bear_points": ["<key bear point citing data>", ...],\n'
        '  "red_flags": ["<red flag>", ...],\n'
        '  "rationale": "<1-2 sentence summary>",\n'
        '  "workflow": [\n'
        '    {"step": "safety", "assessment": "<pass|concern|fail|neutral|missing>", "note": "<short>"},\n'
        '    {"step": "concentration", "assessment": "...", "note": "..."},\n'
        '    {"step": "momentum", "assessment": "...", "note": "..."},\n'
        '    {"step": "social", "assessment": "...", "note": "..."},\n'
        '    {"step": "debate", "assessment": "...", "note": "..."}\n'
        "  ]\n"
        "}"
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
```

> 注:`_dimension_summary` 若不再被任何函数引用,可保留(无害)或删除;本计划保留以减小 diff。

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/llmjudge/test_prompts.py -v`
Expected: PASS(含既有 `test_judge_prompt_instructs_json_output` / `test_judge_prompt_contains_bull_and_bear_text` —— 证据块与 JSON 说明都保留)

- [ ] **Step 5: Commit**

```bash
git add src/memedog/llmjudge/prompts.py tests/llmjudge/test_prompts.py
git commit -m "feat(llmjudge): judge prompt drives a fixed 6-step workflow"
```

---

## Task 6: judge.py — workflow 折叠进 rationale + 置信度护栏

**Files:**
- Modify: `src/memedog/llmjudge/judge.py`
- Test: `tests/llmjudge/test_judge.py`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/llmjudge/test_judge.py`(顶部已 import 的基础上,确保 `_make_snapshot` 支持构造缺失维度——见下面 helper):

```python
def _make_snapshot_missing(n_missing: int):
    """Snapshot with the last n dimensions marked unavailable (order: social, momentum, holders)."""
    snap = _make_snapshot()
    if n_missing >= 1:
        snap.social = SocialInfo(available=False)
    if n_missing >= 2:
        snap.momentum = MomentumInfo(available=False)
    if n_missing >= 3:
        snap.holders = HolderInfo(available=False)
    return snap


def _judge_json_with_workflow(confidence=0.95):
    import json as _json
    return _json.dumps({
        "signal": "BULLISH",
        "confidence": confidence,
        "bull_points": ["strong liquidity $42,300"],
        "bear_points": ["social missing"],
        "red_flags": [],
        "rationale": "Net positive.",
        "workflow": [
            {"step": "safety", "assessment": "pass", "note": "authorities revoked"},
            {"step": "momentum", "assessment": "pass", "note": "liquidity healthy"},
        ],
    })


@pytest.mark.asyncio
async def test_judge_folds_workflow_into_rationale():
    fp = FakeProvider(["bull", "bear", _judge_json_with_workflow(confidence=0.6)])
    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    result = await judge.judge(_make_snapshot(), _make_score())
    # rationale carries both the step summary and the original rationale
    assert "safety:pass" in result.rationale
    assert "Net positive." in result.rationale


@pytest.mark.asyncio
async def test_judge_confidence_guard_caps_on_missing_dimensions():
    # 2 missing dimensions → completeness=0.5 → cap = 0.5 + 0.5*0.5 = 0.75
    fp = FakeProvider(["bull", "bear", _judge_json_with_workflow(confidence=0.95)])
    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    result = await judge.judge(_make_snapshot_missing(2), _make_score())
    assert result.confidence == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_judge_confidence_guard_noop_when_all_available():
    fp = FakeProvider(["bull", "bear", _judge_json_with_workflow(confidence=0.9)])
    judge = LLMJudge(cfg=_make_fake_cfg(), provider=fp)
    # all 4 available → completeness=1.0 → cap=1.0 → unchanged
    result = await judge.judge(_make_snapshot(), _make_score())
    assert result.confidence == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_judge_confidence_guard_disabled():
    from memedog.config.settings import ConfidenceGuardConfig
    cfg = _make_fake_cfg()
    cfg.confidence_guard = ConfidenceGuardConfig(enabled=False, floor=0.5)
    fp = FakeProvider(["bull", "bear", _judge_json_with_workflow(confidence=0.95)])
    judge = LLMJudge(cfg=cfg, provider=fp)
    result = await judge.judge(_make_snapshot_missing(3), _make_score())
    assert result.confidence == pytest.approx(0.95)  # not capped
```

> `_make_fake_cfg` 已构造 `LLMJudgeConfig`;因为 `confidence_guard` 有默认值,无需改它。`_make_snapshot_missing` 直接改 pydantic 实例属性(model 默认允许赋值)。

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/llmjudge/test_judge.py -k "guard or folds_workflow" -v`
Expected: FAIL — rationale 无 `safety:pass`;confidence 未封顶

- [ ] **Step 3: Implement**

在 `src/memedog/llmjudge/judge.py` 新增 helper(放在 `_degrade_signal` 之后):

```python
def _summarize_workflow(steps: list["StepFinding"]) -> str:
    """Compact one-line summary of workflow steps for the Signal.rationale."""
    if not steps:
        return ""
    parts = []
    for s in steps:
        seg = f"{s.step}:{s.assessment}"
        if s.note:
            seg += f"({s.note})"
        parts.append(seg)
    return " | ".join(parts)


def _completeness(snapshot: TokenSnapshot) -> float:
    """Fraction of the 4 dimensions whose data is available."""
    flags = [
        snapshot.safety.available,
        snapshot.holders.available,
        snapshot.momentum.available,
        snapshot.social.available,
    ]
    return sum(1 for f in flags if f) / 4.0
```

在 `judge()` 成功路径,把现有 `confidence = _clamp(judge_out.confidence)` 与 `Signal(...)` 构造之间改为:

```python
            sig_type = _map_signal(judge_out.signal)
            confidence = _clamp(judge_out.confidence)

            # Confidence guard: cap by data completeness when enabled.
            guard = getattr(self._cfg, "confidence_guard", None)
            if guard is not None and getattr(guard, "enabled", False):
                completeness = _completeness(snapshot)
                cap = guard.floor + (1.0 - guard.floor) * completeness
                confidence = min(confidence, cap)

            # Fold the workflow step summary into the rationale (no schema change).
            summary = _summarize_workflow(judge_out.workflow)
            rationale = (
                f"{summary}\n{judge_out.rationale}" if summary else judge_out.rationale
            )

            return Signal(
                mint=snapshot.candidate.mint,
                symbol=snapshot.candidate.symbol,
                signal=sig_type,
                confidence=confidence,
                score_total=score.total,
                bull_points=judge_out.bull_points,
                bear_points=judge_out.bear_points,
                red_flags=judge_out.red_flags,
                rationale=rationale,
                created_at=datetime.now(tz=timezone.utc),
                trace_id=snapshot.candidate.trace_id,
            )
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/llmjudge/test_judge.py -v`
Expected: PASS — 含新增护栏/折叠测试。`test_judge_happy_path_*_real_fixtures` 仍过:现有 fixture 无 `workflow` → summary 为空 → rationale 等于原值;snapshot 四维齐全 → cap=1.0 → confidence 不变(0.78 / 0.82)。

- [ ] **Step 5: Commit**

```bash
git add src/memedog/llmjudge/judge.py tests/llmjudge/test_judge.py
git commit -m "feat(llmjudge): fold workflow into rationale + confidence completeness guard"
```

---

## Task 7: 真实重捕 codex fixtures(含 workflow)+ 更新等值断言

**Files:**
- Modify: `tests/fixtures/codex/judge_bullish.json`
- Modify: `tests/fixtures/codex/judge_bearish.json`
- Modify: `tests/llmjudge/test_judge.py`

> 本任务需要本机 codex 可用(ChatGPT 订阅)。若当前环境 codex 不可用,跳过 Step 1–2 的真实重捕,改用手工补 `workflow` 字段到现有 fixture(标注为"形状真实、内容补全"),并在提交信息注明。优先真实重捕。

- [ ] **Step 1: 真实跑一次 judge 捕获含 workflow 的输出**

确认 codex:`python -c "import shutil; print(shutil.which('codex'))"`。若为 None,用绝对路径 `C:/Users/looik/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe`。

写一个一次性脚本 `scripts/_recapture_judge.py`(临时,捕获后可删):

```python
import asyncio, json
from datetime import datetime, timezone
from memedog.config import load_config
from memedog.llmjudge.judge import LLMJudge
from memedog.llmjudge.prompts import judge_prompt
from memedog.llm.codex_provider import CodexCLIProvider
from memedog.llm.structured import complete_structured
from memedog.llmjudge.judge import JudgeOut
from memedog.models import (DimensionScore, HolderInfo, MomentumInfo, SafetyInfo,
                            Score, SocialInfo, TokenCandidate, TokenSnapshot)

def snap(strong: bool):
    c = TokenCandidate(mint="MINT", pair_address="P", symbol="DOGX", chain="solana",
        pair_created_at=datetime(2024,1,1,tzinfo=timezone.utc), price_usd=0.001,
        liquidity_usd=42300.0, fdv_usd=135000.0, volume_5m=18400.0, volume_1h=96200.0,
        txns_5m_buys=50, txns_5m_sells=28, price_change_5m=5.0, trace_id="t")
    if strong:
        return TokenSnapshot(candidate=c,
            safety=SafetyInfo(available=True, mint_authority_revoked=True, freeze_authority_revoked=True,
                lp_burned_or_locked=True, rug_trust_score=88, rug_risk_level="LOW"),
            holders=HolderInfo(available=True, top10_pct=22.0, max_wallet_pct=5.0, dev_wallet_pct=2.0,
                holder_count=500, sniper_pct=6.0),
            momentum=MomentumInfo(available=True, liquidity_usd=42300.0, volume_5m=18400.0,
                volume_1h=96200.0, buy_sell_ratio_5m=1.8, unique_buyers_1h=210, fdv_to_liquidity=3.2),
            social=SocialInfo(available=True, smart_money_buys=4),
            enriched_at=datetime(2024,1,1,tzinfo=timezone.utc))
    return TokenSnapshot(candidate=c,
        safety=SafetyInfo(available=True, mint_authority_revoked=False, freeze_authority_revoked=True,
            lp_burned_or_locked=False, rug_trust_score=30, rug_risk_level="HIGH"),
        holders=HolderInfo(available=True, top10_pct=55.0, max_wallet_pct=22.0, dev_wallet_pct=9.0,
            holder_count=80, sniper_pct=30.0),
        momentum=MomentumInfo(available=True, liquidity_usd=12000.0, volume_5m=900.0,
            volume_1h=4000.0, buy_sell_ratio_5m=0.7, unique_buyers_1h=20, fdv_to_liquidity=15.0),
        social=SocialInfo(available=False),
        enriched_at=datetime(2024,1,1,tzinfo=timezone.utc))

def score(total):
    return Score(mint="MINT", total=total, dimensions=[
        DimensionScore(name="safety", raw=88.0, weight=0.35, weighted=30.8),
        DimensionScore(name="holders", raw=80.0, weight=0.25, weighted=20.0),
        DimensionScore(name="momentum", raw=75.0, weight=0.25, weighted=18.75),
        DimensionScore(name="social", raw=60.0, weight=0.15, weighted=9.0)], trace_id="t")

async def cap(strong, total, path):
    cfg = load_config().llmjudge
    prov = CodexCLIProvider(codex_bin=cfg.codex.bin, timeout=cfg.codex.timeout_sec, sandbox=cfg.codex.sandbox)
    msgs = judge_prompt(snap(strong), score(total), "Bull: strong liquidity and revoked authorities.",
                        "Bear: watch concentration and missing social.")
    out = await complete_structured(provider=prov, model="", messages=msgs, model_cls=JudgeOut,
                                    temperature=0.2, max_tokens=1024, retries=1)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out.model_dump(), f, ensure_ascii=False)
    print(path, "->", out.signal, len(out.workflow), "steps")

async def main():
    await cap(True, 86.0, "tests/fixtures/codex/judge_bullish.json")
    await cap(False, 28.0, "tests/fixtures/codex/judge_bearish.json")

asyncio.run(main())
```

Run: `python scripts/_recapture_judge.py`
Expected: 两个 fixture 被真实 codex 输出覆盖,各含非空 `workflow`;打印 `... -> BULLISH N steps` / `... -> BEARISH N steps`。

> 若 bearish 那次 codex 没给出 BEARISH(LLM 自由判断),保留其真实结果,并在 Step 3 据实更新断言里的 signal/confidence 值。捕获后删除临时脚本:`rm scripts/_recapture_judge.py`。

- [ ] **Step 2: 校验 fixture 形状**

Run: `python -c "import json; d=json.load(open('tests/fixtures/codex/judge_bullish.json',encoding='utf-8')); print(d['signal'], d['confidence'], len(d['workflow']))"`
Expected: 打印 signal、confidence(0~1)、workflow 步数 > 0。

- [ ] **Step 3: 更新 fixture 等值断言以适配新 rationale + workflow**

`test_judge_happy_path_bullish_real_fixtures` 现在 rationale 会被折叠(因为 fixture 含 workflow)。把该测试里:

```python
    assert result.rationale == judge_data["rationale"]
```

改为(对 bullish 与 bearish 两个测试都改):

```python
    assert judge_data["rationale"] in result.rationale
    # workflow summary folded in
    assert judge_data["workflow"][0]["step"] in result.rationale
```

并把对 `confidence` 的硬编码期望值改为读自 fixture(因为重捕后数值会变,且四维齐全时不被护栏改动):

```python
    assert result.confidence == pytest.approx(judge_data["confidence"])
```

（bullish 的 `_make_snapshot()` 四维齐全 → 护栏 cap=1.0 → 不改动 confidence,等值成立。）

对 bearish 测试同理:`signal` 改为读 `judge_data["signal"]` 映射后的 SignalType,confidence 用 `pytest.approx(judge_data["confidence"])`。

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/llmjudge/test_judge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/codex/judge_bullish.json tests/fixtures/codex/judge_bearish.json tests/llmjudge/test_judge.py
git commit -m "test(llmjudge): re-capture real codex judge fixtures with workflow"
```

---

## Task 8: 全量测试 + live 真实验证

**Files:** 无改动(验证 + 必要修补)

- [ ] **Step 1: 默认套件全过 + 零联网**

Run: `python -m pytest -q`
Expected: 全过(默认 `-m 'not live'`)。若有失败,定位修复后重跑。

Run(证明零外部联网,放行 loopback 给 asyncio):
`python -m pytest -q -p no:cacheprovider --allow-hosts=127.0.0.1,::1,localhost`
> 需 `pytest-socket`。若未装:`python -m pip install pytest-socket`。Expected: 通过且无外部网络调用。

- [ ] **Step 2: live 层真实打 codex**

Run: `python -m pytest -m live tests/live/test_live_codex.py -v`
Expected: 真实 codex 调用返回可解析 JudgeOut;无 codex 时自跳过。

- [ ] **Step 3: live e2e 真实判决含 workflow**

Run: `python -m pytest -m live tests/live/test_live_e2e.py -v`
Expected: 端到端跑通,judge 返回含 workflow 的信号(或按 e2e 既有断言通过)。

- [ ] **Step 4: 合并回 main**

```bash
git checkout main
git merge --no-ff feature/signal-quality-llmjudge -m "feat: signal-quality LLMJudge multi-step workflow (sub-project A)"
```

> 合并前先在分支上 review 一次(见执行流程),确认无误再并。

---

## 自审清单(写计划后)

- **Spec 覆盖**:① 证据块=Task3;② bull/bear=Task4;③ 6 步 workflow=Task5;④ JudgeOut.workflow=Task1;⑤ 置信度护栏=Task2+Task6;⑥ 数据流/降级=Task6(降级路径未改,既有测试覆盖);测试策略=Task3–8;fixture 重捕=Task7。✅ 全覆盖。
- **占位符**:无 TBD/TODO;每步含可运行命令与完整代码。✅
- **类型一致**:`StepFinding`/`JudgeOut.workflow`(Task1)、`ConfidenceGuardConfig`/`LLMJudgeConfig.confidence_guard`(Task2)、`_snapshot_evidence`(Task3)、`_summarize_workflow`/`_completeness`(Task6)命名前后一致。✅
- **向后兼容**:`workflow` 默认 `[]`、`confidence_guard` 带默认实例 → 既有 `_make_fake_cfg` 与旧 fixture 不破。Task6 不动降级路径。✅
