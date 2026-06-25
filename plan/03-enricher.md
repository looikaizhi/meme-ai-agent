# 模块 03:Enricher(数据富化)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。

**Goal:** 对过闸的少数候选,**并行**抓取 4 维完整信号,组装成 `TokenSnapshot`。只取数,不判断。

**Architecture:** 每个维度一个独立 "provider" 函数(`safety / holders / momentum / social`),各自封装一个 client。Enricher 用 `asyncio.gather(..., return_exceptions=True)` 并行执行;单个 provider 失败 → 该维度 `available=False`,其余照常(降级而非崩溃)。

**Tech Stack:** asyncio + httpx。数据源:RugCheck(to be removed)、Helius/Solana RPC、DexScreener、X/Twitter。

---

## 职责边界
- **做**:并行调 4 维数据源 → 填充 `SafetyInfo/HolderInfo/MomentumInfo/SocialInfo` → 组装 `TokenSnapshot`。
- **不做**:打分、推理。
- 与 HardFilter 的区别:HardFilter 只取"硬规则必需"的最小字段做排雷;Enricher 取**完整**字段供打分与 LLM(如 holder_count、twitter_growth、smart_money_buys)。可复用 HardFilter 阶段已取的 RugCheck 报告(传入避免重复请求)。

## 文件结构

```
src/memedog/enricher/enricher.py        # 编排 4 维并行
src/memedog/enricher/providers.py       # 4 个 provider 函数
src/memedog/clients/helius.py           # 持币/聪明钱(Solana RPC + Helius)
src/memedog/clients/twitter.py          # 社交热度
# rugcheck.py / dexscreener.py 复用模块 01/02
tests/enricher/test_providers.py
tests/enricher/test_enricher.py
```

## 4 维 provider 映射

| 维度 | provider | 数据源 | 填充字段 |
|------|----------|--------|---------|
| safety | `fetch_safety` | RugCheck(复用报告) | trust_score, risk_level, 三权限 |
| holders | `fetch_holders` | Helius / RPC `getTokenLargestAccounts` | top10_pct, max_wallet_pct, dev_pct, holder_count, sniper_pct |
| momentum | `fetch_momentum` | DexScreener(可复用 candidate) | liquidity, vol_5m/1h, buy_sell_ratio, unique_buyers, fdv/liq |
| social | `fetch_social` | Helius 标注钱包 + Twitter 搜索 | smart_money_buys, twitter_mentions_1h, twitter_growth |

## 配置(.env / thresholds.yaml -> enricher 段)

```yaml
enricher:
  per_provider_timeout_sec: 8
  smart_money_wallets_file: config/smart_wallets.txt   # 标注的聪明钱地址清单
  twitter_lookback_min: 60
# .env: HELIUS_API_KEY=..., TWITTER_BEARER=...(社交可选,缺失则 social.available=False)
```

## 任务

### Task 1: HeliusClient(持币 + 聪明钱)

**Files:** Create `src/memedog/clients/helius.py`; Test `tests/clients/test_helius.py`

- [ ] **Step 1: 写失败测试** — mock RPC `getTokenLargestAccounts` 响应,断言算出 top10_pct、max_wallet_pct。
- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现** — `get_largest_holders(mint)`、`get_holder_count(mint)`;聪明钱:对照 `smart_wallets.txt` 统计近窗口买入数。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(clients): helius holders"`

### Task 2: TwitterClient(社交,可选维度)

**Files:** Create `src/memedog/clients/twitter.py`; Test `tests/clients/test_twitter.py`

- [ ] **Step 1: 写失败测试** — mock 搜索响应,断言算出 mentions_1h 与 growth;无 token 时返回 `available=False` 标志。
- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现** — `count_mentions(symbol, lookback)`;缺 `TWITTER_BEARER` 时直接返回不可用(不报错)。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(clients): twitter mentions"`

### Task 3: 4 个 provider 函数

**Files:** Create `src/memedog/enricher/providers.py`; Test `tests/enricher/test_providers.py`

- [ ] **Step 1: 写失败测试** — 每个 provider:正常返回填满对应子对象;client 抛错时返回 `available=False` 的子对象。

```python
async def test_fetch_holders_degrades_on_error(failing_helius):
    info = await fetch_holders(mint="m", client=failing_helius)
    assert info.available is False
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现 4 个 provider**,每个 `try/except` 包裹,失败返回 `available=False` 的子对象。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(enricher): providers with degradation"`

### Task 4: Enricher 并行编排

**Files:** Create `src/memedog/enricher/enricher.py`; Test `tests/enricher/test_enricher.py`

- [ ] **Step 1: 写失败测试**

```python
async def test_enrich_parallel_assembles_snapshot(cand, fake_providers):
    snap = await Enricher(**fake_providers).enrich(cand)
    assert snap.candidate.mint == cand.mint
    assert snap.safety.available and snap.momentum.available
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现 `enrich(candidate)`** — `asyncio.gather` 4 个 provider(`return_exceptions=True`),每个加 `per_provider_timeout`;组装 `TokenSnapshot`,`enriched_at=now`。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(enricher): parallel orchestration"`

## 降级与边界
- 任一维度失败只影响该维度 `available`;ScoreEngine 据此降权,LLMJudge 在 prompt 中被告知"该维度数据缺失"。
- 复用原则:HardFilter 已取的 RugCheck 报告与 candidate 的 DexScreener 字段传入 Enricher,避免重复请求。
