# 模块 02:HardFilter(硬规则闸门)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。

**Goal:** 用客观可量化的链上事实把绝大多数 rug/蜜罐/无热度币挡在 LLM 之前,产出极少数过闸候选。

**Architecture:** 纯函数式同步过滤器。每条规则是一个独立、可单测的"判定函数",返回 `(passed: bool, reason: str)`。HardFilter 聚合所有规则,任一硬红线不过即丢弃。**为控成本,HardFilter 需要的安全/持币数据由一个轻量级检查在此阶段拉取**(只拉硬规则必需字段,完整 4 维富化仍在 Enricher)。

**Tech Stack:** Python 纯逻辑 + RugCheck/Solana RPC 轻量调用。阈值全部来自 `thresholds.yaml`。

---

## 设计依据(为什么是这些规则)

meme 币无基本面,硬规则本质是"先排雷,再看潜力"。三类红线,来源为行业公开经验(RugCheck / GoPlus / DEXTools 链上清单):

**A. 合约权限红线(任一不过 = 直接丢弃)**
| 规则 | 通过条件 | 理由 |
|------|---------|------|
| mint authority | 已放弃 | 否则可无限增发砸盘 |
| freeze authority | 已放弃 | 否则冻结钱包=蜜罐卖不出 |
| LP 状态 | 已烧毁或锁定 | 否则可随时抽干流动性 |

**B. 持币集中度红线**
| 规则 | 默认阈值 |
|------|---------|
| Top10 占比(剔除 LP) | ≤ 35% |
| 单一钱包最大占比 | < 20% |
| 开发者持仓 | < 10% |
| sniper(首 120s)抢筹占比 | < 30% |

**C. 资金/动量门槛**
| 规则 | 默认阈值 |
|------|---------|
| 流动性 | ≥ $20000 |
| 5min 交易量 | ≥ $1000 |
| 买/卖笔数比(5m) | ≥ 1.0 |
| FDV / 流动性 | ≤ 50 |

> 这些值是**演示默认**,全部可在 YAML 调。命中红线时记录是哪条规则、实际值 vs 阈值,供看板展示与调参。

## 文件结构

```
src/memedog/hardfilter/rules.py        # 各独立判定函数
src/memedog/hardfilter/hardfilter.py   # HardFilter 聚合器
src/memedog/clients/rugcheck.py        # RugCheck 轻量查询(权限/LP/持币摘要)
tests/hardfilter/test_rules.py
tests/hardfilter/test_hardfilter.py
```

## 配置(thresholds.yaml -> hardfilter 段)

```yaml
hardfilter:
  authority:
    require_mint_revoked: true
    require_freeze_revoked: true
    require_lp_burned_or_locked: true
  holders:
    max_top10_pct: 35
    max_single_wallet_pct: 20
    max_dev_pct: 10
    max_sniper_pct: 30
  momentum:
    min_liquidity_usd: 20000
    min_volume_5m: 1000
    min_buy_sell_ratio_5m: 1.0
    max_fdv_to_liquidity: 50
```

## 任务

### Task 1: 独立规则函数

**Files:** Create `src/memedog/hardfilter/rules.py`; Test `tests/hardfilter/test_rules.py`

- [ ] **Step 1: 写失败测试**(每条规则一个测试,边界值正反各一)

```python
from memedog.hardfilter.rules import check_top10, check_authorities, check_momentum

def test_top10_pass_and_fail():
    assert check_top10(top10_pct=30, max_pct=35)[0] is True
    ok, reason = check_top10(top10_pct=40, max_pct=35)
    assert ok is False and "top10" in reason.lower()

def test_authorities_block_active_mint():
    ok, _ = check_authorities(mint_revoked=False, freeze_revoked=True,
                              lp_locked=True, cfg={...})
    assert ok is False
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现规则函数** — 每个函数签名 `(value..., threshold...) -> tuple[bool, str]`,reason 含规则名 + 实际值 + 阈值。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(hardfilter): rule functions"`

### Task 2: RugCheckClient(轻量)

**Files:** Create `src/memedog/clients/rugcheck.py`; Test `tests/clients/test_rugcheck.py`

- [ ] **Step 1: 写失败测试**(mock RugCheck 响应,解析出 mint/freeze authority、LP 状态、top holders、trustScore/riskLevel)
- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现** — `get_token_report(mint) -> dict`,继承 base client。端点:`https://api.rugcheck.xyz/v1/tokens/<mint>/report`(若需 key 走 .env)。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(clients): rugcheck client"`

### Task 3: HardFilter 聚合器

**Files:** Create `src/memedog/hardfilter/hardfilter.py`; Test `tests/hardfilter/test_hardfilter.py`

- [ ] **Step 1: 写失败测试**

```python
async def test_hardfilter_keeps_clean_drops_dirty(clean_cand, rug_cand, cfg, fake_rugcheck):
    hf = HardFilter(rugcheck=fake_rugcheck, cfg=cfg)
    out = await hf.apply([clean_cand, rug_cand])
    assert [c.mint for c in out] == [clean_cand.mint]
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现 `apply(candidates)`**
  - momentum 类规则可直接用 `TokenCandidate` 已有字段(无需联网),先跑这些(便宜)。
  - 通过 momentum 的才调 RugCheck 取权限/持币 → 跑 A、B 规则。
  - 任一红线不过即剔除;记录 `dropped` 列表(规则名 + 值)供看板。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(hardfilter): aggregator"`

## 降级与边界
- RugCheck 不可用:按 config 策略——演示期可"放行但标记 safety_unknown",生产期应"保守丢弃"。该开关写入 `hardfilter.on_rugcheck_failure: drop|pass_flagged`。
- 顺序优化:先跑不联网的 momentum 规则,能剔除的尽早剔除,减少 RugCheck 调用量。
