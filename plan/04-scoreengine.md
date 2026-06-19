# 模块 04:ScoreEngine(规则量化打分)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。

**Goal:** 把 `TokenSnapshot` 的 4 维客观数据,经可配置权重映射成一个 0~100 的量化分 `Score`,带分项明细。

**Architecture:** 纯函数,无 IO。每维一个 `score_<dim>(info, cfg) -> DimensionScore`,把原始指标归一化到 0~100;ScoreEngine 加权汇总。缺失维度(`available=False`)降权并在 notes 注明。打分给 LLMJudge 一个客观锚点,避免 LLM 凭空判断。

**Tech Stack:** Python 纯逻辑。权重/归一化参数全部来自 `thresholds.yaml`。

---

## 打分思路

每维把关键指标映射到 0~100(越高越看涨/越安全),再乘权重。归一化用"分段线性"或"阈值打分",参数可配:

| 维度 | 关键指标 → 打分逻辑(示例) | 默认权重 |
|------|---------------------------|---------|
| safety | trust_score 直接用(0~100);risk_level CRITICAL/HIGH 封顶降分 | 0.35 |
| holders | top10 越低越高分、max_wallet 越低越高分、holder_count 越多越高分、sniper 越低越高分 | 0.25 |
| momentum | 流动性、量、买卖比、独立买家增速 综合(越活跃越高,过热也适度封顶) | 0.25 |
| social | smart_money_buys、twitter 增速(越热越高,但权重最低,噪声大) | 0.15 |

> 权重之和 = 1。某维 `available=False` 时:该维 `raw` 记为中性值(如 50)且权重折半,剩余权重按比例归一,notes 标注"数据缺失,已降权"。

## 文件结构

```
src/memedog/scoring/dimensions.py     # 4 个 score_<dim> 函数
src/memedog/scoring/engine.py         # ScoreEngine 汇总
tests/scoring/test_dimensions.py
tests/scoring/test_engine.py
```

## 配置(thresholds.yaml -> scoring 段)

```yaml
scoring:
  weights:
    safety: 0.35
    holders: 0.25
    momentum: 0.25
    social: 0.15
  holders:
    top10_full_score_at: 15      # top10<=15% 给满分
    top10_zero_score_at: 50      # top10>=50% 给 0 分(线性插值)
    max_wallet_zero_at: 25
  momentum:
    liquidity_full_at: 100000
    volume_5m_full_at: 20000
  missing_dimension_weight_factor: 0.5   # 缺失维度权重折半
  neutral_score: 50
```

## 任务

### Task 1: 维度打分函数

**Files:** Create `src/memedog/scoring/dimensions.py`; Test `tests/scoring/test_dimensions.py`

- [ ] **Step 1: 写失败测试**(每维含:满分点、零分点、缺失降级)

```python
from memedog.scoring.dimensions import score_holders, score_safety

def test_score_holders_concentration():
    info = HolderInfo(top10_pct=15, max_wallet_pct=5, holder_count=500, sniper_pct=5)
    ds = score_holders(info, cfg)
    assert ds.raw >= 90                 # 低集中度 → 高分

def test_score_holders_high_concentration_low():
    info = HolderInfo(top10_pct=50, max_wallet_pct=25, holder_count=20, sniper_pct=40)
    assert score_holders(info, cfg).raw <= 20

def test_missing_dimension_neutral():
    info = SafetyInfo(available=False)
    ds = score_safety(info, cfg)
    assert ds.raw == 50 and "缺失" in " ".join(ds.notes)
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现 4 个函数** — 分段线性归一化辅助 `lerp_score(value, full_at, zero_at)`;缺失维度返回中性分 + note。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(scoring): dimension scorers"`

### Task 2: ScoreEngine 汇总

**Files:** Create `src/memedog/scoring/engine.py`; Test `tests/scoring/test_engine.py`

- [ ] **Step 1: 写失败测试**

```python
def test_engine_weighted_total(full_snapshot, cfg):
    score = ScoreEngine(cfg).score(full_snapshot)
    assert 0 <= score.total <= 100
    assert {d.name for d in score.dimensions} == {"safety","holders","momentum","social"}

def test_engine_renormalizes_when_dimension_missing(snap_no_social, cfg):
    score = ScoreEngine(cfg).score(snap_no_social)
    # social 缺失,权重重新归一,total 仍在 0~100
    assert 0 <= score.total <= 100
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现 `score(snapshot)`** — 调 4 个维度函数 → 对缺失维度按 `missing_dimension_weight_factor` 折权并重新归一 → 汇总 `total` → 组装 `Score`。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(scoring): weighted engine with renormalization"`

## 备注
- 打分**不直接出 BULLISH/BEARISH**——那是 LLMJudge 的职责。Score 只是客观锚点。
- 调策略 = 改 YAML 权重/归一化点,无需改代码。
