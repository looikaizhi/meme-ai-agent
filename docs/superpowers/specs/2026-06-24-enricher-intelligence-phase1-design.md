# Enricher 智能化升级 Phase 1 — 设计文档

**日期:** 2026-06-24
**范围:** 第三层 Enricher + ScoreEngine 的确定性升级。四件事:(A) 聪明钱共识、(B) 免费社交元数据、(C) 确定性叙事分类(新增第 5 打分维度)、(D) Twitter 移出生产路径。**全部确定性、可单测、兼容默认 Codex 后端、demo 离线可跑。**

> 两期拆分中的 **Phase 1**。Phase 2(LLM 函数调用工具:agent 自拉聪明钱历史/PnL)+ Codex 叙事 web 搜索 = 独立子系统,**不在本 spec**。

---

## 1. 背景与动机

Enricher 现状:并行抓 4 维(safety/holders/momentum/social)组装 `TokenSnapshot`。结合外部 "Twitter-Free Attention Enrichment Plan" 复盘后,确定四个改进:

1. **聪明钱太薄** —— [`helius.count_smart_money_buys`](../../../src/memedog/clients/helius.py) 只返回一个 `int`,LLM 不知道是谁/几个/什么级别。`plan/09`(35–78 行)指出聪明钱共识是公开样本中最高频的高收益方法。
2. **社交元数据零成本未用** —— DexScreener pair 的 `info.socials`/`info.websites` 免费,"有没有真社交"是强信号。
3. **缺"叙事"信号** —— meme 靠注意力。不去问"推特在聊吗"(贵且不可靠),改为**从代币名字/符号确定性分类**(狗/AI/政治/文化 meme、是否命中已知爆款词)。零成本、确定性,直答"这盘有没有能扩散的 meme 钩子"。
4. **Twitter 该下线** —— 既不付费、数据又不稳。从生产路径移除,改由免费叙事 + 社交元数据承接注意力维度。

### 调研结论(社交数据替代 Twitter)
DexScreener/pump.fun 社交字段免费(本期主用);LunarCrush 免费档限流(可选,默认关);Kaito Yaps 2026-01 因 X 封 API 关停(不用);Apify 爬虫每 2–4 周失效(不用);官方 X API $100/月起(不用)。
来源:[LunarCrush pricing](https://lunarcrush.com/pricing) · [Kaito Yaps 关停](https://coinjournal.net/news/kaito-winds-down-yaps-product-after-losing-access-to-the-x-api/) · [DexScreener API reference](https://docs.dexscreener.com/api/reference)

---

## 2. 目标(Phase 1)

1. **A 聪明钱共识**:钱包库带标签/级别;实时产出 distinct 买家数 + 标签/级别 + 共识强度 → 喂 LLM。
2. **B 免费社交元数据**:Scanner 零成本采集社交平台存在性 → 快照;可选 LunarCrush galaxy(默认关,降级不崩)。
3. **C 叙事分类(新维度)**:从 symbol/name 确定性分类 → `NarrativeInfo` → 既进 ScoreEngine 作**第 5 维**、也进 LLM prompt。
4. **D Twitter 移出生产路径**:`fetch_social` 不再调 `TwitterClient`;`twitter_mentions_1h/twitter_growth/TWITTER_BEARER/twitter_lookback_min` 弃用、不再驱动打分;`TwitterClient` 模块保留供测试/未来。

**非目标(明确推迟 / 排除):**
- LLM 函数调用工具、agent 自拉钱包历史、Codex 叙事搜索 → **Phase 2**。
- 实时逐钱包 PnL/胜率 → Phase 2。
- **PaperTrader 主流程停在 LLMJudge**(外部文件提到)→ 这是流水线范围变更,与项目定位(含 paper trading)冲突,**不纳入本 spec**,如需另开议题。
- 删除 backtesting → 不在本 spec。

---

## 3. 数据契约变更(additive / Optional;新维度除外)

### 3.1 钱包库格式(`config/smart_wallets.txt`,向后兼容)
```
# address,label,tier
9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin,early-BONK-buyer,S
3NkzLTtTfEWqDY2Mm3uVt2wog8yDN48yDu3vsTS4MSaq,KOL-wallet,A
AAv8T8KHrQwPqLp...                                  # 纯地址行,label/tier=None
```
`tier`:`S/A/B`(高→低)。离线维护;本期给示例库 + 解析器,不做自动质量计算。

### 3.2 `WalletInfo`(新,`models/snapshot.py`,在 `SocialInfo` 之前)
```python
class WalletInfo(BaseModel):
    address: str
    label: Optional[str] = None
    tier: Optional[str] = None
```

### 3.3 `NarrativeInfo`(新,`models/snapshot.py`)
```python
class NarrativeInfo(BaseModel):
    available: bool = True               # 确定性派生,几乎恒 True
    category: Optional[str] = None       # animal / ai / political / culture / finance_utility / unknown
    matched_keywords: list[str] = []     # 命中的分类关键词
    meme_collision: list[str] = []       # 名字呼应的已知爆款 (wif/pepe/bonk/doge/shib/cat/grok/trump/musk…)
    summary: str = ""                    # 一句话人读摘要
```
`category="unknown"` = 中性(不是看空)。

### 3.4 `TokenCandidate` 扩字段(Scanner 取数时零成本采集)
```python
    social_platforms: list[str] = []   # 归一化平台名,如 ["twitter","telegram","website"]
```

### 3.5 `SocialInfo` 扩字段(全 Optional 默认 None);Twitter 字段保留但弃用
```python
    # 聪明钱共识(A)
    smart_money_distinct_wallets: Optional[int] = None
    smart_money_buyers: Optional[list[WalletInfo]] = None
    smart_money_top_tier: Optional[str] = None
    # 社交元数据(B)
    has_twitter: Optional[bool] = None
    has_telegram: Optional[bool] = None
    has_website: Optional[bool] = None
    socials_count: Optional[int] = None
    galaxy_score: Optional[float] = None     # LunarCrush,可选,默认 None
    # 弃用(保留字段以兼容,但生产不再填充/打分)
    # twitter_mentions_1h, twitter_growth → 不再由 fetch_social 写入
```
保留 `smart_money_buys`(社交维度打分仍可参考)。

### 3.6 `TokenSnapshot` 加维
```python
    narrative: NarrativeInfo
```

---

## 4. 组件设计

### 组件 A — 聪明钱共识
- **A1 钱包库加载器** `enricher/enricher.py::_load_smart_wallets`:返回 `dict[str, WalletInfo]`(逗号分割;首列地址必需,2/3 列 label/tier 可选;`#`/空行跳过;缺文件→空 dict)。
- **A2 Helius 共识** `clients/helius.py`:新增 `analyze_smart_money(mint, wallet_library) -> dict`,统计 `buys`(命中笔数,保留)、`distinct_wallets`、`buyers`(WalletInfo 列表)、`top_tier`(S>A>B);空库不联网返回 0;错误→None。`count_smart_money_buys` 由其取代或保留为薄封装。
- **A3 装配** `enricher/providers.py::fetch_social`:调 `analyze_smart_money` 填聪明钱字段;子源失败语义不变。

### 组件 B — 社交元数据
- **B1 Scanner** `scanner/scanner.py::_convert`:从 `pair.get("info",{})` 的 `socials[].type` + `websites` 归一化成 `candidate.social_platforms`(无 info→`[]`)。
- **B2 派生** `fetch_social`:从 `social_platforms` 派生 `has_twitter/has_telegram/has_website/socials_count`(需把列表透传进 `fetch_social`,改 `enricher.enrich` 装配)。
- **B3 可选 LunarCrush** `clients/lunarcrush.py`(新):`get_galaxy_score(symbol)->Optional[float]`;`EnricherConfig` 加开关、`Settings` 加 `LUNARCRUSH_API_KEY`(默认 None);无 key 跳过、失败→None。

### 组件 C — 叙事分类(新维度)
- **C1 分类器** `enricher/narrative.py`(新):`classify_narrative(symbol, name) -> NarrativeInfo`,纯函数、不联网、永不抛。
  - 对 `symbol`+`name` 小写做关键词匹配 → category;命中已知爆款词 → `meme_collision`;生成 `matched_keywords`/`summary`。
  - 分类关键词表 + 爆款词表 = 模块常量(分类逻辑);**分值映射进 YAML**(可调)。
- **C2 provider** `enricher/providers.py`:新增 `fetch_narrative(symbol, name) -> NarrativeInfo`(包 classify,异常→`NarrativeInfo(available=False)`,但本质确定性几乎不会失败)。
- **C3 Enricher 装配** `enricher/enrich`:并入并行 gather(或直接同步调用,因为无 I/O);写入 `snapshot.narrative`。
- **C4 打分** `scoring/`:
  - `dimensions.py` 新增 `score_narrative(info, cfg) -> DimensionScore`:按 `category` 查 `cfg.narrative.category_scores` 得基分,`meme_collision` 非空加 `cfg.narrative.meme_collision_bonus`,clamp [0,100]。
  - `engine.py`:`_REQUIRED_WEIGHT_KEYS` 加 `"narrative"`;`score()` 加入 narrative 维(权重归一已按 `1/n` 自适应,无需改归一逻辑)。
  - `settings.py` `ScoringConfig` 加 `narrative: ScoringNarrativeConfig`。

### 组件 D — Twitter 移出生产路径
- `fetch_social` 不再调 `TwitterClient`,不再写 `twitter_mentions_1h/twitter_growth`。
- `score_social`(`dimensions.py`)改为不依赖 `twitter_growth`:用 `smart_money_buys`(或 distinct 钱包)+ 社交存在性(`socials_count`)+ 可选 `galaxy_score`。`ScoringSocialConfig` 的 twitter 字段弃用(保留以兼容旧 YAML,不再使用)。
- `EnricherConfig.twitter_lookback_min`、`Settings.twitter_bearer` 弃用(保留字段,不再驱动逻辑)。`TwitterClient` 模块保留供测试。

### 组件 E — LLM 喂数(prompt)`llmjudge/prompts.py`
- `_snapshot_evidence`:
  - social 行:`聪明钱=3个(S:early-BONK-buyer, A:KOL-wallet)`、`社交=tw+tg+web(3)` / `社交=无`、`galaxy=NN`(有则)。
  - 新增 `NARRATIVE / 叙事` 行:`category=animal  命中=[dog,inu]  碰撞=[bonk]  "狗系 meme,呼应 BONK"`;无则 DATA MISSING。
- judge workflow:第 4 步社交措辞补充(共识强度 + 钱包级别 + 社交真实性);新增叙事作为**上下文/弱置信修正**,明确:无新闻/无社交是中性非看空;**叙事只在 safety/holders/momentum 已健康时才提升置信**;强链上数据优先于叙事。

### 权重(`thresholds.yaml`)
```yaml
scoring:
  weights: { safety: 0.30, holders: 0.25, momentum: 0.30, social: 0.10, narrative: 0.05 }
  narrative:
    category_scores: { animal: 70, ai: 65, political: 60, culture: 55, finance_utility: 35, unknown: 40 }
    meme_collision_bonus: 10
```

---

## 5. 受影响文件清单

| 文件 | 改动 |
|------|------|
| `src/memedog/models/snapshot.py` | 新增 `WalletInfo`、`NarrativeInfo`;`SocialInfo` 扩字段;`TokenSnapshot.narrative` |
| `src/memedog/models/candidate.py` | `social_platforms` |
| `src/memedog/scanner/scanner.py` | `_convert` 采集 social_platforms |
| `src/memedog/enricher/narrative.py` | 新增 `classify_narrative` |
| `src/memedog/enricher/providers.py` | `fetch_social`(聪明钱共识+社交元数据,去 Twitter)+ `fetch_narrative` |
| `src/memedog/enricher/enricher.py` | `_load_smart_wallets`→dict;透传 social_platforms;装配 narrative;去 twitter 调用 |
| `src/memedog/clients/helius.py` | `analyze_smart_money` |
| `src/memedog/clients/lunarcrush.py` | 新增可选 client |
| `src/memedog/scoring/dimensions.py` | `score_narrative`;`score_social` 去 twitter 依赖 |
| `src/memedog/scoring/engine.py` | 加 narrative 维 + 必填权重键 |
| `src/memedog/config/settings.py` | `ScoringConfig.narrative`;`EnricherConfig` lunarcrush 开关;`Settings` LUNARCRUSH_API_KEY;twitter 字段弃用注释 |
| `src/memedog/config/thresholds.yaml` | weights 加 narrative + narrative 段;enricher lunarcrush 开关 |
| `src/memedog/llmjudge/prompts.py` | social 行更新 + NARRATIVE 行 + workflow 措辞 |
| `config/smart_wallets.txt`(示例) | 升级为带 label/tier |
| 对应 `tests/**` | 各单元新增/更新;ScoreEngine 5 维测试;Twitter 不再驱动打分 |

---

## 6. 测试策略(TDD,不联网)

1. **钱包库解析**:label/tier 行 / 纯地址 / 注释空行 / 缺文件 → 正确 dict / 空 dict。
2. **analyze_smart_money**:mock Helius,断言 distinct/buyers(含 label/tier)/top_tier;空库不联网=0;错误→None。
3. **Scanner social_platforms**:含 info.socials/websites → 列表;无 info → `[]`。
4. **classify_narrative**:`QDOG→animal`、AI/政治/文化样例、`AssetFunds→finance_utility`、纯无意义→unknown;命中爆款词进 meme_collision;永不抛。
5. **score_narrative**:各 category → 基分正确;meme_collision 加 bonus 并 clamp;unknown 中性。
6. **ScoreEngine 5 维**:权重含 narrative、归一正确、总分合理;某维 missing 时权重缩放仍工作。
7. **score_social 去 twitter**:twitter_growth 不再影响分;用 smart_money + 社交存在性。
8. **LunarCrush**:有 key mock galaxy;无 key 跳过→None;失败→None。
9. **prompt 渲染**:聪明钱共识 / 社交 / 叙事 / 各缺失 → 文案正确。
10. **回归**:demo 离线 cycle 通过;Twitter 移除后 enrich/score/judge 全链路绿;旧 YAML(无 narrative 段)给出明确报错或默认。

---

## 7. 风险与缓解
- **叙事分类是启发式**:关键词表覆盖有限 → unknown 中性兜底;分值在 YAML 可调;LLM 负责更细的叙事/仿冒判断。
- **聪明钱库质量是上限**:本期给示例库 + 管道;质量计算=Phase 2。
- **新增打分维度触及归一化/旧 YAML**:`engine.py` 必填键校验会让缺 `narrative` 权重的旧 YAML 在构造时显式报错(可控);随 spec 一并更新 thresholds.yaml。
- **DexScreener info.socials 不总存在**:缺失→空列表,视为"无社交信号"(本身是信号),不报错。
- **Twitter 字段弃用而非删除**:保留字段避免破坏旧快照/测试反序列化;生产不再填充/打分。
