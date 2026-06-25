# memedogV2 多源韧性数据层 + 真实闸门测试 设计规格

> 日期:2026-06-25 · 对象:`src/memedogV2/`(分支 `feat/memedogV2-gmgn-pipeline`)
> 关联:审计报告 `docs/superpowers/audits/2026-06-25-memedogV2-audit.md`(C-1/H-1/H-2)

## 一、背景

审计实跑暴露两件事:(1)gmgn 单点 —— 一次 TLS 抖动让整条 `run()` 崩溃(C-1),且无重试(H-1);(2)测试几乎全是 mock/夹具,真实一跑才发现跑不通(H-2),"绿"不代表系统真能跑通。

同时发现:**RugCheck(免 key 公开 API)与 Helius 对新 meme 也能取到数据**,且 RugCheck 的 LP 锁定信号(`markets[].lp.lpLockedPct`)与 gmgn 的 `burn_status` 相互独立、可互为校验/兜底。

## 二、目标

1. **韧性优先的多源取数**:安全/LP/持仓按优先级 RugCheck→gmgn(必要时 Helius 垫底)依次取,谁先返回非空就用谁;某源失败自动跳下一个,**不再因 gmgn 抖动而崩**。
2. **动量必拿**:流动性/量/买卖笔数只有 gmgn 有,gmgn 取数带**有界重试**,确保拿到;拿不到记为取数失败(不 degrade 放行)。
3. **可观测**:每个规范字段记录其**实际来源**;每个被调用的源产一条 `ToolCallRecord`。
4. **真实闸门测试**:分层测试 + 一个**默认就跑、配置齐全时不可跳过**的真实端到端闸门(真实 RugCheck+Helius+gmgn+真实 DeepSeek 跑到 Signal),外加一条韧性测试(强制主源失败,断言真实回退)。
5. 顺带修掉审计的 C-1(源失败即跳,不崩)与 H-1(gmgn 有界重试)。

## 三、非目标

1. 不改 `src/memedog/`。
2. 不接 DexScreener(只服务新 meme,动量只用 gmgn)。
3. 不做 Helius 聪明钱分析(需"标注钱包库",暂无)—— 聪明钱仍取 gmgn `wallet_tags_stat.smart_wallets`。
4. 不实现 `compliance.py`/完整 `replay.py`(延续上一份 spec 的延后项)。

## 四、总体架构

```
(CA, LP)
   │
   ▼
DataResolver(规范化多源,韧性优先)              ── src/memedogV2/sources/
   ├─ RugCheckSource  : 权限(mint/freeze)、LP(lpLockedPct≥90)、top10/单钱包集中度、sniper、总持有人
   ├─ GmgnSource      : 包现有 GmgnCli(security+info)。权限/LP/集中度的兜底 + 动量 + 证据 + tag。带有界重试。
   ├─ HeliusSource    : top holders(≤20,粗)→ 集中度最后垫底
   └─ Resolver        : 按字段优先级合并 → 规范 Facts + 每字段来源标记 + 每源 ToolCallRecord
        │
        ▼
HardFilter(规则改读规范字段名,不再绑定 gmgn JSON 形状)
        ▼
build_evidence(从规范 Facts 抽)→ DeepSeek/Codex 审计 → Signal + run 记录
```

## 五、规范 Facts(与数据源解耦的字段集)

`sources/base.py` 定义 `Facts`(pydantic)。规则与证据只读这些规范字段;每字段配一个 `<field>_source: str` 标注来源。

| 规范字段 | 类型 | 含义 |
|---------|------|------|
| `mint_revoked` / `freeze_revoked` | bool\|None | 权限已放弃 |
| `lp_safe` | bool\|None | LP 已烧或已锁 |
| `honeypot` | bool\|None | 蜜罐 |
| `top10_rate` / `max_wallet_rate` | float\|None | 0–1 比率 |
| `creator_rate` / `dev_rate` | float\|None | 0–1 |
| `sniper_count` | int\|None | 狙击钱包数 |
| `fresh_wallet_rate` / `bundler_rate` | float\|None | 0–1 |
| `liquidity_usd` / `volume_5m` / `price_usd` / `circulating_supply` | float\|None | 动量/估值 |
| `buys_5m` / `sells_5m` | int\|None | 5m 买卖笔数 |
| `smart_money_count` / `kol_count` / `dev_created_count` | int\|None | 证据 |
| `historical_ath` | float\|None | dev 历史 ATH 市值 |

## 六、每字段来源优先级

| 维度 | 优先级 | 备注 |
|------|--------|------|
| `mint_revoked`/`freeze_revoked` | RugCheck → gmgn | RugCheck:`mintAuthority/freezeAuthority is None` |
| `lp_safe` | RugCheck → gmgn | RugCheck:任一 market `lp.lpLockedPct≥90`;gmgn:`burn_status=="burn"` 或 `lock_summary.is_locked` |
| `top10_rate` / `max_wallet_rate` | RugCheck → gmgn → Helius | RugCheck 剔除 AMM;Helius 粗(≤20)垫底 |
| `honeypot` / `creator_rate` / `dev_rate` / `sniper_count` / `fresh_wallet_rate` / `bundler_rate` | gmgn | RugCheck/Helius 无对应或口径不一 |
| 动量(`liquidity_usd`/`volume_5m`/`buys_5m`/`sells_5m`/`price_usd`/`circulating_supply`) | **gmgn 单源,必拿(带重试)** | RugCheck/Helius 无 |
| 证据(`smart_money_count`/`kol_count`/`dev_created_count`/`historical_ath`) | gmgn | |

`dev_graduation_rate` 仍无任何来源 → 恒 None、进 `missing`。

## 七、组件设计

`src/memedogV2/sources/`:
- **`base.py`**:`Facts` 模型;`SourceAdapter` 协议 `async fetch(ca, lp) -> tuple[PartialFacts, ToolCallRecord]`;`PartialFacts` = 该源能提供的规范字段子集(None 表示该源没有)。
- **`rugcheck_source.py`**:HTTP `GET https://api.rugcheck.xyz/v1/tokens/{mint}/report`(复用/移植 memedog `parse_report` 的归一化逻辑),输出 PartialFacts(权限/LP/集中度/sniper/holders)。
- **`gmgn_source.py`**:包现有 `GmgnCli`(security+info),把 `FIELD_MAP` 提取的值归一化成 PartialFacts(全字段)。**带有界重试**:非 429 的瞬时错误重试 ≤N 次(指数退避);429 不重试、上抛 `RateLimitBanned`。
- **`helius_source.py`**:`getTokenLargestAccounts` → top10/max-wallet/holder_count(粗,集中度垫底)。
- **`resolver.py`**:`DataResolver.resolve(ca, lp) -> ResolvedFacts`。逐源调用(各自 try/except,失败记录并跳过);按字段优先级合并;标注来源;动量缺失且 gmgn 已尽力 → 在结果里标 `momentum_unavailable=True`。产 `list[ToolCallRecord]`。

`harness/tool_registry.py`:Resolver 取代现有 `GmgnCliToolSource`。Runner 的 `read_security/read_info` 两步合并为一步 **`resolve_facts`**(内部多源),其余流程不变。

`hardfilter/`:`rules.py` 改读规范字段名(`top10_rate`、`lp_safe`、`liquidity_usd`…);`hardfilter.py` 不再调 `token_security/token_info`,改为直接对 `ResolvedFacts` 跑规则。`fieldmap.py` 退役为 gmgn_source 内部使用(把 gmgn JSON → 规范字段)。

`harness/evidence_builder.py`:`build_evidence(facts: ResolvedFacts, ca)` 从规范字段抽(不再读 gmgn 原始 dict)。

## 八、错误处理与韧性(修 C-1/H-1)

- **源级**:Resolver 对每个源 `try/except`;失败 → 记 `ToolCallRecord(exit_status≠0, error摘要)` + 该源 PartialFacts 全 None + 继续下一源。**任何源失败都不上抛、不崩。**
- **gmgn 有界重试**:`gmgn_source` 对非 429 瞬时错误重试(默认 ≤2 次,指数退避,可配 `gmgn.max_retries`)。
- **动量必拿**:若所有重试后动量仍缺 → Resolver 标 `momentum_unavailable`;Runner 据此把 hardfilter 步标 FAILED(取数失败)、无信号、落 run 记录(不崩)。
- **429**:`RateLimitBanned` 上抛到 Runner → FAILED 步 + 无信号(现状保留)。
- **Runner 取数阶段**:`resolve_facts` 用 `try/except (RateLimitBanned, Exception)`,均记 FAILED 步并返回 —— **彻底修掉 C-1**。

## 九、可观测性

`ResolvedFacts` 带 `sources: dict[field, source_name]`(每字段实际来源)与 `attempts: list[ToolCallRecord]`(每源一条,含命令/退出码/耗时/错误)。Runner 把这些写进 `read_facts` 步的 `tool_calls`。run 记录因此能回答:**哪个字段来自哪个源、哪个源失败了、各花多久**。

## 十、测试策略(分层 + 强制真实闸门)

**第 1 层 — 纯逻辑单测(快、确定性,用真实录制数据)**
- 各 source adapter 解析器:用从真实 API 录的 per-source 快照 `tests/memedogV2/fixtures/sources/{rugcheck,helius,gmgn}.json` 测归一化。
- Resolver 优先级/降级/来源标注:合成 PartialFacts 测纯逻辑(含"主源失败→用次源""动量缺失→标记")。
- HardFilter 规则:真实快照 + 边界合成。
- `scripts/refresh_source_fixtures.sh`:从真实 API 重录三源快照,捕捉字段漂移。

**第 2 层 — 强制真实闸门(默认就跑;凭证齐全时不可跳过)**
- `tests/memedogV2/test_gate_real.py`(**不带 live 标记 → 默认 suite 就跑**):
  - `test_gate_real_pipeline`:真实多源 + 真实 DeepSeek,对一个**当前能过闸的 (CA, LP)** 跑到 Signal;断言有 `final_signal` 且 signal 合法、run 记录里 `read_facts` 步含真实 `ToolCallRecord`。
  - `test_gate_resilience_fallback`:强制 RugCheck 源抛错,断言**真实回退到 gmgn**仍拿到权限/LP/集中度字段、流程不崩(直接守护 C-1)。
  - **缺凭证/二进制时 loud-skip**(`pytest.skip` 带醒目原因);**有凭证则必须通过**。
- 过闸活币来源:
  - **动态**:`gmgn-cli market`(trending/trenches)拉当前候选,挑第一个过闸的跑(永远有当下活币)。
  - **钉住兜底**:实现/验证阶段线上找一个当前过闸的 `(CA, LP)` 写进测试常量(附"可能需刷新")。动态失败时用它。

**真实执行**:实现完成后,实跑闸门(找过闸活币 → 真实多源 → 真实 DeepSeek → 出 Signal),把真实结果交付。

## 十一、迁移与兼容

- 规则函数签名基本不变(本就按逻辑字段取值);改的是**喂给它们的来源**(ResolvedFacts 而非 gmgn JSON)。
- `gmgn_cli.py`/`ratelimit.py`/`errors.py` 不动;`fieldmap.py` 收进 `gmgn_source` 使用。
- `model_registry`/`prompts`/`recorder`/`contracts` 不动。
- 删:`harness/tool_registry.py` 里 `GmgnCliToolSource`/`FixtureToolSource` 由 sources/ 取代(或保留 Fixture 版供单测)。

## 十二、验收标准

1. 任一数据源失败,流水线**不崩**,落 run 记录并标注失败源。
2. RugCheck 在线时,权限/LP/集中度字段**来源标注为 rugcheck**;RugCheck 失败时自动回退 gmgn。
3. 动量经重试仍拿不到 → hardfilter 步 FAILED、无信号(不 degrade 放行)。
4. `test_gate_real_pipeline` 在凭证齐全环境**默认就跑且必须通过**;缺凭证 loud-skip。
5. `test_gate_resilience_fallback` 真实证明主源失败时回退有效。
6. 每个规范字段在 run 记录里可追溯到具体来源。

## 十三、开放风险

- RugCheck 公开 API 限流/可用性未知 → 归入"源失败即跳"的韧性范畴,实现时实测其稳定性。
- "过闸活币"会过期 → 动态发现为主、钉住为辅;闸门测试需容忍"当下确实无过闸活币"(此时 loud-skip 并提示,而非误报失败)。
- 多源字段口径差异(如 RugCheck sniper_pct vs gmgn sniper_count)→ 不混用;按表各管各字段。
