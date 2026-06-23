# Enricher 智能化升级 Phase 1 — 设计文档

**日期:** 2026-06-24
**范围:** 第三层 Enricher 的确定性升级 —— 把聪明钱从"一个计数"升级成"谁+几个+什么级别"的共识信号,并零成本补齐社交元数据,全部喂给 LLM 判断。**兼容默认 Codex 后端,保持离线可复现。**

> 本设计是两期拆分中的 **Phase 1**。Phase 2(LLM 函数调用工具:让 agent 自行拉取聪明钱历史交易/PnL)是独立子系统,需要扩展 LLM 层的 tool-calling 循环 + tool-capable provider,**不在本 spec**,后续单独 spec/plan。

---

## 1. 背景与动机

第三层 Enricher 现状:并行抓 4 维(safety/holders/momentum/social),组装 `TokenSnapshot` 给 ScoreEngine + LLM。两个短板:

1. **聪明钱太薄。** [`helius.count_smart_money_buys`](../../../src/memedog/clients/helius.py) 只返回一个 `int`(有多少笔转账到标注钱包),LLM 只看到"聪明钱买入=N",**不知道是谁、几个不同钱包、什么质量级别、是否多方共识**。`plan/09`(35–78 行)指出聪明钱共识是公开样本中**最高频**的高收益方法。
2. **社交几乎为零成本信号未利用。** 当前社交维度依赖**付费 Twitter API**;而 DexScreener pair 响应里 **`info.socials`/`info.websites` 是免费的**,"有没有真社交、有哪些平台"本身就是强信号(裸盘无社交 vs tw+tg+web 齐全),我们却没采集。

### 调研结论(社交数据替代 Twitter)
| 方案 | 成本 | 信号 | 取舍 |
|------|------|------|------|
| 官方 X API | $100/月、$0.005/条 | 全量 | 太贵 |
| **DexScreener/pump.fun 社交字段** | **免费(已在拉)** | 有无真社交/平台/官号 | 元数据,非热度 → **本期主用** |
| LunarCrush | 免费档限流 | Galaxy Score/社交量 | **本期做成可选 provider,默认关** |
| Kaito Yaps | 开源 API | mindshare | 2026-01 曾因 X 封 API 关停,稳定性存疑 → 不用 |
| Apify cashtag 爬虫 | $0.01/1k | 提及数 | 每 2–4 周失效,脆弱 → 不用 |

来源:[LunarCrush pricing](https://lunarcrush.com/pricing) · [Kaito Yaps 关停](https://coinjournal.net/news/kaito-winds-down-yaps-product-after-losing-access-to-the-x-api/) · [DexScreener API reference](https://docs.dexscreener.com/api/reference) · [Apify cashtag scraper](https://apify.com/fastcrawler/twitter-cashtag-scraper-pay-per-result-for-stock-crypto/api/cli)

---

## 2. 目标(Phase 1)

1. **聪明钱共识(组件 A)**:钱包库升级为带标签/质量级别;实时产出 distinct 买入钱包数、各自标签/级别、共识强度;把这些 + 钱包身份喂给 LLM。
2. **免费社交元数据(组件 B)**:在 Scanner 取数时零成本采集社交平台存在性,写入快照;可选 LunarCrush galaxy score(默认关,降级不崩);喂给 LLM。
3. 保持确定性、可单测、demo 离线可跑、兼容 Codex 默认后端。

**非目标(YAGNI / 明确推迟):**
- LLM 函数调用工具、agent 自拉钱包历史 → **Phase 2**。
- Codex judge 的 web 搜索叙事层 → 推迟(与 Phase 2 一起)。
- 实时逐钱包 PnL/胜率计算(太重,与漏斗控成本冲突)。
- **不改 ScoreEngine 四维权重结构**;新字段只进 LLM prompt,不改打分公式(避免连锁重构)。聪明钱仍归在 social 维度内,只扩字段。

---

## 3. 数据契约变更(全部 additive、Optional、默认 None → 向后兼容)

### 3.1 钱包库格式(`config/smart_wallets.txt`)
从"一行一个地址"升级为可带标签的 CSV 风格,**向后兼容**(只有地址的行 = 无标签/级别):
```
# address,label,tier
9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin,early-BONK-buyer,S
3NkzLTtTfEWqDY2Mm3uVt2wog8yDN48yDu3vsTS4MSaq,KOL-wallet,A
AAv8T8KHrQwPqLp...                                  # 纯地址行,label/tier=None
```
- `tier` 取值约定:`S/A/B`(质量从高到低),自由文本也允许。
- 离线维护;本期提供一份示例库 + 解析器,不做自动质量计算。

### 3.2 `WalletInfo`(新,定义在 `models/snapshot.py`,在 `SocialInfo` 之前)
```python
class WalletInfo(BaseModel):
    address: str
    label: Optional[str] = None
    tier: Optional[str] = None
```

### 3.3 `TokenCandidate` 扩字段(Scanner 取数时零成本采集)
```python
    social_platforms: list[str] = []   # 归一化平台名,如 ["twitter","telegram","website"]
```
- 来源:DexScreener pair 的 `info.socials[].type` + `info.websites`(存在即 "website")。
- 缺失/无 info → 空列表(不报错)。

### 3.4 `SocialInfo` 扩字段(全 Optional 默认 None)
```python
    # 聪明钱共识(组件 A)
    smart_money_distinct_wallets: Optional[int] = None
    smart_money_buyers: Optional[list[WalletInfo]] = None   # 谁买了 + 标签 + 级别
    smart_money_top_tier: Optional[str] = None              # 买家中最高级别(S>A>B)
    # 社交元数据(组件 B)
    has_twitter: Optional[bool] = None
    has_telegram: Optional[bool] = None
    has_website: Optional[bool] = None
    socials_count: Optional[int] = None
    galaxy_score: Optional[float] = None                    # LunarCrush,可选,默认 None
```
保留现有 `smart_money_buys / twitter_mentions_1h / twitter_growth`(ScoreEngine 仍读 `smart_money_buys`,不破坏打分)。

---

## 4. 组件设计

### 组件 A — 聪明钱共识

**A1. 钱包库加载器** — `enricher/enricher.py` 的 `_load_smart_wallets`
- 返回从 `set[str]` 改为 `dict[str, WalletInfo]`(地址 → 标签/级别)。
- 解析每行:逗号分割,首列地址(必需),第 2/3 列 label/tier(可选);`#` 开头或空行跳过。
- 文件缺失/读失败 → 空 dict(沿用现有容错)。

**A2. Helius 共识分析** — `clients/helius.py`
- 新增 `analyze_smart_money(mint, wallet_library: dict[str, WalletInfo]) -> dict`:
  - 空库 → `{"distinct_wallets":0,"buyers":[],"buys":0,"top_tier":None}`,不联网。
  - 否则拉 Enhanced Transactions(同现有 TRANSFER 端点),统计:
    - `buys`:命中标注钱包的转账笔数(= 现有计数,保留)。
    - `distinct_wallets`:命中的**不同**标注钱包数(共识强度代理)。
    - `buyers`:命中钱包的 `WalletInfo` 列表(地址+标签+级别)。
    - `top_tier`:buyers 中最高级别(S>A>B,无则 None)。
  - 任一错误 → 返回 None(让 provider 标该子源不可用),沿用现有 best-effort 语义。
- 现有 `count_smart_money_buys` 可保留为薄封装或由 `analyze_smart_money` 取代;`fetch_social` 改调新方法。

**A3. provider 装配** — `enricher/providers.py` 的 `fetch_social`
- 调 `analyze_smart_money`,把结果填入 `SocialInfo` 的聪明钱字段。
- 子源失败语义不变(聪明钱失败但社交元数据 ok → 仍 `available=True`)。

### 组件 B — 社交元数据

**B1. Scanner 采集** — `scanner/scanner.py` 的 `_convert`
- 从 `pair.get("info",{})` 读 `socials`(list of `{type/platform, ...}`)和 `websites`,归一化成平台名列表写入 `candidate.social_platforms`。无 info → `[]`。

**B2. provider 派生** — `fetch_social`
- 从 `candidate.social_platforms` 派生 `has_twitter/has_telegram/has_website/socials_count` 写入 `SocialInfo`。
- 注意:`fetch_social` 当前签名收 `symbol/mint`,需要把 candidate 的 `social_platforms` 传进来(改 `enricher.enrich` 的装配,把列表透传)。

**B3. 可选 LunarCrush** — `clients/lunarcrush.py`(新,可选)
- 新增 `LunarCrushClient`(继承 BaseHTTPClient),`get_galaxy_score(symbol) -> Optional[float]`。
- `EnricherConfig` 加开关;`Settings` 加 `LUNARCRUSH_API_KEY`(默认 None)。
- **默认关**:无 key → provider 跳过,`galaxy_score=None`。有 key 才调用;失败降级为 None。

### 组件 C — LLM 喂数(prompt)

**C1. `llmjudge/prompts.py` 的 `_snapshot_evidence`** —— social 行扩展:
- 聪明钱:`聪明钱=3个(S:early-BONK-buyer, A:KOL-wallet, …)` —— 显示 distinct 数 + 各 buyer 标签/级别。
- 社交:`社交=tw+tg+web(3)` 或 `社交=无` —— 平台存在性。
- galaxy:有则 `galaxy=NN`。
- judge 的 6 步 workflow 第 4 步(social)措辞补充:让 LLM 用"聪明钱共识强度 + 钱包质量级别 + 社交真实性"判断,而非只看一个计数;数据缺失仍按不确定性处理,不臆造。

---

## 5. 受影响文件清单

| 文件 | 改动 |
|------|------|
| `src/memedog/models/snapshot.py` | `SocialInfo` 扩字段;新增 `WalletInfo` |
| `src/memedog/models/candidate.py` | `TokenCandidate.social_platforms` |
| `src/memedog/scanner/scanner.py` | `_convert` 采集 social_platforms |
| `src/memedog/clients/helius.py` | 新增 `analyze_smart_money` |
| `src/memedog/clients/lunarcrush.py` | 新增可选 client |
| `src/memedog/enricher/enricher.py` | `_load_smart_wallets` 返回 dict;透传 social_platforms + 可选 lunarcrush |
| `src/memedog/enricher/providers.py` | `fetch_social` 接共识 + 社交元数据(+ 可选 galaxy) |
| `src/memedog/config/settings.py` | `EnricherConfig` 加 lunarcrush 开关;`Settings` 加 key |
| `src/memedog/config/thresholds.yaml` | enricher 段加 lunarcrush 开关(默认关) |
| `src/memedog/llmjudge/prompts.py` | social 证据行 + workflow 措辞 |
| `config/smart_wallets.txt`(示例) | 升级为带 label/tier 的示例库 |
| 对应 `tests/**` | 各单元新增/更新 |

---

## 6. 测试策略(TDD,不联网)

1. **钱包库解析**:带 label/tier 行、纯地址行、注释/空行、缺文件 → 正确 dict / 空 dict。
2. **analyze_smart_money**:mock Helius TRANSFER 响应,断言 distinct_wallets / buyers(含 label/tier)/ top_tier;空库不联网返回 0;错误 → None。
3. **Scanner social_platforms**:含 info.socials/websites 的 pair → 归一化列表;无 info → `[]`。
4. **fetch_social 装配**:聪明钱 ok+社交 ok / 一方失败 / 都失败 的 available 语义;字段正确填充。
5. **LunarCrush**:有 key 走 mock 返回 galaxy;无 key 跳过返回 None;HTTP 失败 → None。
6. **prompt 渲染**:有聪明钱共识/有社交/全缺三种 → 证据行文案正确,缺失走 DATA MISSING。
7. **回归**:demo 离线 cycle、ScoreEngine 不受影响(仍读 smart_money_buys)。

---

## 7. 风险与缓解

- **聪明钱库质量是上限**:标签/级别靠离线维护,本期只给示例库 + 解析/装配管道;质量计算(PnL/胜率)= Phase 2。
- **DexScreener info.socials 不总存在**:缺失 → 空列表,LLM 视为"无社交信号"(本身也是信号),不报错。
- **distinct_wallets 仅近似共识**:Enhanced Transactions 端点不分页、不做买/卖精确分类(沿用现有 best-effort);真共识聚类留待后续。
- **新增 Optional 字段**:全部默认 None,ScoreEngine/现有 prompt 路径不受影响;demo 路径不依赖任何新外部源。
