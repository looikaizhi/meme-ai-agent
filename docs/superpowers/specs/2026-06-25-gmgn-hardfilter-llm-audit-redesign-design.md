# 设计:GMGN 驱动的 HardFilter + LLM 审计架构改造

> 日期:2026-06-25
> 状态:已通过 brainstorming,待用户复核 → 转 writing-plans

## 1. 背景与动机

现有流水线:`Scanner(DexScreener) → HardFilter(momentum + RugCheck) → Enricher(RugCheck/Helius/metadata) → ScoreEngine(4 维 0–100) → LLMJudge(Bull/Bear/Judge) → PaperTrader`。

问题:取数分散在 RugCheck + Helius + DexScreener 三个源,Enricher/ScoreEngine 把"判断"前置成确定性分数,压缩了 LLM 的解读空间。

本次改造目标:
1. **数据源统一到 GMGN**:用 `gmgn-cli`(GMGN OpenAPI 的确定性 CLI)接管安全/持仓/流动性取数,**不再用 RugCheck 与 Helius**。
2. **HardFilter 只做客观红线**:用 `gmgn-cli` 三条命令的硬事实做排雷,产出极少数过闸候选。
3. **判断完全交给 LLM**:不要 ScoreEngine 前置 0–100 分;由 Bull/Bear 分析师 + Judge(可用 gmgn-skills 主动取证)直接给出 `BULLISH/BEARISH/NEUTRAL` 与是否推荐。

**隔离策略(重要):本轮全部代码新建在独立包 `src/memedogV2/`,不改、不删现有 `src/memedog/`。** 旧 memedog(含 RugCheck/Helius/Enricher/ScoreEngine)原样保留可继续运行;memedogV2 是一套平行实现,二者互不依赖。下文所有路径以 `src/memedogV2/` 为根。

## 2. 范围

**在范围内(全部新建于 `src/memedogV2/`):**
- `gmgn-cli` 确定性封装(`memedogV2/clients/gmgn_cli.py`),含限速/缓存/429 退避。
- HardFilter:三条 gmgn-cli 命令 + 客观红线规则。
- LLM 审计 workflow:证据采集 → Bull → Bear → Judge,经 `codex exec` 调起、用 gmgn-skills 取证。
- 数据契约:`HardFilterResult`、`EvidenceBundle`、`Signal`(含 `recommended`)—— 在 memedogV2 内自有,不复用 memedog 的 `TokenSnapshot`/`Score`。
- memedogV2 自己的 orchestrator(入口 = 地址)+ PaperTrader/Dashboard/Alert 复用或薄封装(见 §4.5)。

**不在范围内(本次不做):**
- **改动现有 `src/memedog/`**:旧包原样保留,不删 RugCheck/Helius/Enricher/ScoreEngine。
- **Telegram bot 抓取**:系统入口直接接受 `(ca_address, lp_address)`。抓取层留接口占位,手动/测试可直接喂地址。
- Scanner/DexScreener 发现层:memedogV2 不含发现层(入口即地址)。
- 真实下单 / `gmgn-swap`:永不做,项目仅 paper trading。

## 3. 目标架构(改造后漏斗)

```
[0] AddressIntake(占位,事件式入口)
        外部给定 (ca_address, lp_address);受控排空队列,避免突发打爆 gmgn 漏桶
        │
        ▼  入口参数 = (CA address, LP address)
[1] HardFilter(确定性,零 LLM)— clients/gmgn_cli.py + hardfilter/
        gmgn-cli token security → 权限 + 集中度 + rug/wash/dev 红线   (先跑,最可能毙)
        ↓ 过则
        gmgn-cli token pool     → 流动性 + LP 状态红线
        ↓ 过则
        gmgn-cli token info     → 动量门槛(价格/交易活动/launchpad)
        │  任一红线不过 → drop(记录规则名+实际值+阈值)
        ▼  过闸的极少数候选
[2] LLM 审计 workflow(codex agent + gmgn-skills,--output-schema 强约束 JSON)
        2a 证据采集 agent:gmgn-track/market/token → 一份 EvidenceBundle
                            (smart money、KOL holder、历史战绩、趋势、holders 明细)
        2b Bull 分析师(读同一份证据)→ 看多论点(结构化)
        2c Bear 分析师(读同一份证据)→ 看空论点(结构化)
        2d Judge → BULLISH/BEARISH/NEUTRAL + recommended:bool + 理由 + 引用证据
        │
        ▼
[3] PaperTrader + Dashboard + Alert(骨架不动,字段微调)
```

## 4. 模块设计

### 4.1 AddressIntake(占位)
- 接口:`enqueue(ca_address, lp_address) -> trace_id`。
- 内部受控排空队列:按 `gmgn.intake_drain_rps` 出队,避免一批新币瞬时并发打爆 gmgn 漏桶。
- 本次仅实现队列 + 手动/测试入队;Telegram 抓取留 TODO。

### 4.2 HardFilter(确定性,零 LLM)
**`memedogV2/clients/gmgn_cli.py`** —— `gmgn-cli` 子进程封装:
- 方法:`token_security(ca)`、`token_pool(ca)`、`token_info(ca)`,均 `--chain sol --address <CA> --raw`,解析 JSON。
- 自带:**客户端限速器**(token-bucket,移植/参考 memedog 现有 `clients/ratelimit.py` 思路,默认保守 `~1 req/s` 可配)、**按地址结果缓存**(TTL)、**429 感知退避**(读 `reset_at`,封禁期间挂起到解封,**绝不冷却期重试**——重试会把封禁每次延长 5s)。
- 失败抛 `DataSourceError`,由 HardFilter 按 config 决定 drop / pass_flagged。

**`memedogV2/hardfilter/`** —— 纯函数规则聚合器:
- 调用顺序按"最可能被拒 + 便宜"排:**security → pool → info**;早毙早返回,省后续命令。
- 红线分类(阈值全进 `thresholds.yaml`):

| 类别 | 字段来源 | 红线 |
|------|---------|------|
| A 权限 | `token security` | mint/freeze authority 未放弃 → 毙;LP(`token pool`)未烧/未锁 → 毙 |
| B 集中度 | `token security` | Top10 实际持仓、单一钱包最大持仓、Dev 当前持仓、Sniper 数量、Fresh Wallet 比例、Bundler 比例 超阈值 → 毙 |
| B' Dev 战绩(极端硬闸) | `token security` / 证据 | 历史成功毕业比例 = 0% **且** 历史创建 Token 数 ≥ N(连环 rug 子)→ 毙;其余交 LLM |
| C 动量 | `token info` | 流动性(`token pool`)、5m 量、买卖比、FDV/流动性 不达标 → 毙 |
| 风险标记 | `token security` | Rug / Wash 命中按 config drop 或 pass_flagged |

- 产出 `HardFilterResult`:地址、各 gmgn 原始事实、`passed:bool`、`dropped`(规则名+实际值+阈值)、`flagged`。

### 4.3 LLM 审计 workflow
**字段分配原则:客观风险红线 → HardFilter;潜力/声誉/解读信号 → LLM。**

- **交给 LLM 的证据**(进 `EvidenceBundle`):Smart Money 数量、KOL Holder 数量、历史创建 Token 数、历史成功毕业比例、历史 Token ATH、趋势/K线、holders 明细。
- **2a 证据采集 agent**:一个 agent 用 gmgn-skills(gmgn-track / gmgn-market / gmgn-token)在**固定调用预算**(`gmgn.max_evidence_calls`,默认 ≤ 5)内收齐成**一份** `EvidenceBundle`。bull/bear 共享,避免重复调用。
- **2b Bull / 2c Bear**:各自读同一份 `EvidenceBundle`,输出结构化论点(论点列表 + 引用字段 + 置信度)。
- **2d Judge**:综合双方 → `Signal{ signal: BULLISH/BEARISH/NEUTRAL, recommended: bool, confidence, rationale, evidence_refs }`。

### 4.4 codex 调用层(关键集成)
- 现有 `CodexCLIProvider` 用 `codex exec --sandbox read-only`(纯文本 LLM,**跑不了 gmgn-cli**)。
- 审计 agent 需要**新增一种放开网络+命令执行的调用**:`codex exec` 配 `--sandbox workspace-write`(开网络)或受控 `--dangerously-bypass-approvals-and-sandbox`,并:
  - 把 gmgn-skills 装进 codex(`.codex` 集成),`GMGN_API_KEY` 进环境;
  - 用 `--output-schema <file>` 强约束 bull/bear/judge 的 JSON 输出。
- 认证:已 `codex login`(ChatGPT 订阅),零按量费用。
- memedogV2 的 codex 调用层是新代码(`memedogV2/llm/`),可参考 memedog 的 `CodexCLIProvider` 但不复用其 read-only 调用。

### 4.5 复用 PaperTrader / Dashboard / Alert
- memedogV2 有自己的 orchestrator(入口 = 地址,非 Scanner)。
- PaperTrader / Dashboard / Alert 优先**薄封装复用** memedog 现有实现(它们只依赖 `Signal` + 价格);若耦合过深则在 memedogV2 内重写最小版。具体在 writing-plans 阶段按实际依赖决定,默认复用。

## 5. 数据契约(memedogV2 自有,`memedogV2/models/`)
- **新增**:`HardFilterResult`(地址 + gmgn 事实 + 通过/红线/标记)、`EvidenceBundle`(LLM 证据字段)、`Signal`(含 `signal`、`recommended: bool`、`confidence`、`rationale`、`evidence_refs`)。
- **不复用** memedog 的 `TokenSnapshot`/`Score`(后者继续服务旧 memedog)。
- 全程结构化日志 `trace_id`:哪条红线、agent 调了哪些 gmgn 查询、最终 JSON,可追溯。

## 6. 速率限制约束(一等约束)
GMGN OpenAPI 限制紧、惩罚狠(来源见文末):
- 每秒:漏桶 rate=10/capacity=10,实际 `≈10÷weight` req/s;数据爬取层默认 1 req/s。
- **429 → 封禁约 5 分钟;冷却期间再请求,每次延长 5s,最高 5 分钟。** 故严禁失败即重试。
- 每日配额 / 各 endpoint weight 未公开 → Phase 0 spike 时实测确认。

设计应对:
1. HardFilter 每地址最坏 3 命令,按 security→pool→info 早毙顺序压低实际调用。
2. 入口事件式 + 受控排空队列,杜绝突发并发。
3. `gmgn_cli` 单例共享:限速器 + 缓存 + reset_at 退避(挂起到解封,不硬怼)。
4. 审计证据采集固定预算 `max_evidence_calls`,bull/bear 共享一份证据。

## 7. 配置(thresholds.yaml / .env)
```yaml
gmgn:
  rate_limit_rps: 1.0          # 客户端限速,保守
  cache_ttl_sec: 60            # 同地址结果缓存
  max_evidence_calls: 5        # 审计证据采集调用预算
  intake_drain_rps: 0.5        # 入口队列排空速率
  on_failure: pass_flagged     # gmgn-cli 失败:drop | pass_flagged
  on_429: suspend_until_reset  # 撞限:挂起到 reset_at,不重试
hardfilter:
  authority: { require_mint_revoked: true, require_freeze_revoked: true, require_lp_burned_or_locked: true }
  holders:   { max_top10_pct: 35, max_single_wallet_pct: 20, max_dev_pct: 10, max_sniper_count: ..., max_fresh_wallet_pct: ..., max_bundler_pct: ... }
  dev_track: { min_graduation_rate_for_serial: 0.0, serial_token_count_threshold: N }  # 极端硬闸
  momentum:  { min_liquidity_usd: 20000, min_volume_5m: 1000, min_buy_sell_ratio_5m: 1.0, max_fdv_to_liquidity: 50 }
```
`.env`:新增 `GMGN_API_KEY`(读 ✓);删除 `HELIUS_API_KEY`、`RUGCHECK_API_KEY`。

## 8. 降级与错误处理
- `gmgn-cli` 单命令失败 → 按 `gmgn.on_failure`:`drop` 或 `pass_flagged`。
- 撞 429 → 挂起到 `reset_at`,该地址本轮跳过,不阻塞其他。
- 审计某维取证失败 → Judge 降权并在 `rationale` 标注"该维缺失"。
- 任一环节失败不崩流水线;orchestrator 维持 per-candidate try/except。

## 9. memedogV2 目录结构(全新建,不动 memedog)
```
src/memedogV2/
├── __init__.py
├── orchestrator.py          # 入口=地址的主循环(无 Scanner)
├── intake.py                # AddressIntake 占位队列 (ca, lp)
├── models/                  # HardFilterResult / EvidenceBundle / Signal
├── clients/
│   └── gmgn_cli.py          # gmgn-cli 子进程封装 + 限速/缓存/429 退避
├── hardfilter/              # 三命令 + 客观红线规则(纯函数)
├── audit/                   # 证据采集 agent + bull/bear/judge workflow
├── llm/                     # codex exec 调用层(放开网络 + --output-schema)
└── config/                  # memedogV2 自有 thresholds + settings 段
tests/memedogV2/             # 镜像测试
```
旧 `src/memedog/`(含 rugcheck/helius/enricher/scoring/snapshot/score)**原样保留,本轮不动**。

## 10. Phase 0 spike(唯一硬风险,先做,绿前不写下游)
一次真实端到端验证:
1. `npx skills add GMGNAI/gmgn-skills` 装进 codex,配 `GMGN_API_KEY`。
2. 一次 `codex exec`(放开网络的 sandbox + `--output-schema`):加载某 gmgn skill → 跑 `gmgn-cli token security <真实CA>` → 返回符合 schema 的 JSON。
3. 顺带实测 gmgn 限速/weight 行为,校准 `rate_limit_rps`。
**判定**:能稳定返回结构化 JSON 且不立即撞封禁 = 绿;否则回到 brainstorming 调整调用方式。

## 11. 实现顺序
1. **Phase 0 spike**(gating)。
2. `src/memedogV2/` 包骨架 + 数据契约:`HardFilterResult` / `EvidenceBundle` / `Signal`(TDD)。
3. `memedogV2/clients/gmgn_cli.py`:限速 + 缓存 + 429 退避(mock 子进程 TDD)。
4. HardFilter:三命令 + 红线规则(mock CLI TDD)。
5. 审计 workflow:证据采集 agent + bull/bear/judge + codex 调用层(mock codex TDD)。
6. memedogV2 orchestrator + AddressIntake 队列;PaperTrader/Dashboard/Alert 复用接线。

每模块 TDD:先失败测试(gmgn-cli / codex 全 mock,不真实联网)→ 最小实现 → 通过 → commit。

## 12. 测试策略
- `gmgn_cli`:mock 子进程 stdout(真实 `--raw` JSON 样本作 fixture);测限速器、缓存命中、429 reset_at 退避路径。
- HardFilter:mock gmgn_cli,验证三类红线正反边界 + 早毙顺序(security 命中不再调 pool/info)。
- 审计:mock codex `--output-schema` 输出,验证 EvidenceBundle 装配、bull/bear 共享、judge 合议与降级标注。
- 不在测试中真实联网。

## 13. 开放风险 / 待验证
- **codex exec 能否非交互地稳定跑 gmgn skill + gmgn-cli**(Phase 0 验证)。
- **gmgn 各 endpoint weight 与每日配额**(未公开,spike 实测)。
- **图2 部分字段是否真出现在 `token security --raw`**(如 Sniper/Fresh Wallet/Bundler/历史战绩)还是需额外命令 —— spike 时核对真实 JSON 字段。

## 来源
- GMGN Agent API 文档:https://docs.gmgn.ai/index/gmgn-agent-api
- gmgn-skills(GitHub):https://github.com/GMGNAI/gmgn-skills
- gmgn-skills Wiki(中文):https://github.com/GMGNAI/gmgn-skills/wiki/Home-Chinese
