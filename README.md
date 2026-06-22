# 🐕‍🦺 MemeDog Radar(金狗雷达)

> **Solana 链上 meme 币(“金狗”)早期动量监测与信号引擎。**
> 一条漏斗式流水线:扫描数百个新盘 → 用硬规则排雷 → 对幸存者并行富化链上数据 → 量化打分 → 两个 LLM 角色(看多 Bull / 看空 Bear)辩论、再由裁决者终审 → 输出 **`BULLISH / BEARISH / NEUTRAL`** 信号 → 模拟交易跟踪虚拟盈亏 → 实时看板展示。

**⚠️ 免责声明:** 仅供研究 / 演示。**只做监控 + 信号 + 模拟交易(paper trading),不接真实钱包、不真实下单。** 非投资建议。

---

## 1. 给评审的一句话速览

| 问题 | 回答 |
|------|------|
| **针对哪个阶段?** | meme 币的 **“初有动量”窗口** —— 发盘后约 20 分钟到几小时(不是毫秒级抢跑)。 |
| **核心思想是什么?** | 一条**漏斗**:数百候选 → 个位数 → 只有这极少数才会触达(昂贵的)LLM。这让多 agent LLM 推理在高频场景下**可负担**。 |
| **AI 在哪里?** | 一个 provider 无关的 LLM 层,基于真实链上数据跑 **Bull/Bear 双视角辩论 + 裁决终审**,并由确定性的规则打分作为客观锚点。 |
| **怎么做到便宜?** | 默认 LLM 后端是把 **OpenAI Codex CLI 当子进程调用**,走 ChatGPT 订阅额度 → 近乎零按量成本。一行配置即可切换到 Claude / OpenAI / DeepSeek。 |
| **是真的能跑吗?** | 是 —— 已对 **Bitget market-data MCP、DexScreener fallback、RugCheck、Helius、Telegram、Codex** 全部真实联网验证。测试由**真实抓取的 API 响应**驱动,另有可选的 live 真联网测试层。 |

---

## 2. 架构总览(一眼看懂)

整个系统是一条 **六段漏斗**。每一段都是职责单一的模块,模块之间只通过**带类型的数据对象**通信 —— 因此任何一层都可独立替换或调参。

```
                      每轮数百个
  ┌─────────────┐    ──────────────────►   ┌──────────────┐   幸存者(个位数)
  │ [1] Scanner │  TokenCandidate[]         │[2] HardFilter│  ──────────────────────────►
  └─────────────┘                           └──────────────┘
   轮询 Bitget MCP                           三类红线闸门
   初筛“有动量”                               (权限 / 集中度 / 流动性)
   去重                                       其余丢弃 ✂️
                                                   │
        ┌──────────────────────────────────────────┘
        ▼
  ┌──────────────┐   TokenSnapshot   ┌───────────────┐   Score 0-100   ┌──────────────┐
  │ [3] Enricher │ ────────────────► │[4] ScoreEngine│ ──────────────► │ [5] LLMJudge │
  └──────────────┘                   └───────────────┘                 └──────────────┘
   4 维并行富化:                      4 维加权打分                       Bull ⚔ Bear 辩论
   安全 / 持币 /                      (客观锚点)                         + 裁决终审
   动量 / 社交                                                          │
   降级而非崩溃                                                         ▼
                                                              Signal: BULLISH / BEARISH / NEUTRAL
                                                              + confidence + 理由 + 红旗(red_flags)
                                                                         │
                                          ┌──────────────────────────────┼──────────────────────┐
                                          ▼                              ▼                      ▼
                                  ┌────────────────┐            ┌──────────────────┐
                                  │[6a] Backtester │            │[6b] PaperTrader  │
                                  └────────────────┘            └──────────────────┘
                                   历史价回放验证                  开虚拟仓
                                   胜率/PNL/回撤                   止盈/止损/超时平仓
                                          │                       跟踪虚拟盈亏
                                          ▼
                                  ┌────────────────┐
                                  │ Bitget Playbook│
                                  └────────────────┘
                                   导出策略 prompt
                                   外部回测/发布
                                                                         │
                                                                         ▼
                                                               ┌──────────────────┐
                                                               │  看板 + 告警       │
                                                               └──────────────────┘
```

### 每一层具体做什么

| # | 层 | 一句话职责 | 输入 → 输出 | 主要数据源 | 代码 |
|---|-----|-----------|------------|-----------|------|
| **1** | **Scanner(扫描器)** | 轮询新盘,只留有早期动量的,并按 mint 地址去重 | `()` → `TokenCandidate[]` | Bitget market-data MCP(默认) / DexScreener fallback | [`scanner/`](src/memedog/scanner/) |
| **2** | **HardFilter(硬规则闸门)** | 在花任何 LLM 之前,用三类客观红线排掉 rug/蜜罐 | `TokenCandidate[]` → `TokenCandidate[]` | RugCheck | [`hardfilter/`](src/memedog/hardfilter/) |
| **3** | **Enricher(数据富化)** | **并行**抓取 4 个信号维度,失败优雅降级 | `TokenCandidate` → `TokenSnapshot` | RugCheck · Helius RPC · Candidate momentum · X/Twitter | [`enricher/`](src/memedog/enricher/) |
| **4** | **ScoreEngine(打分)** | 把 4 维映射成 **0–100** 加权分(给 LLM 的客观锚点) | `TokenSnapshot` → `Score` | 纯逻辑,配置驱动 | [`scoring/`](src/memedog/scoring/) |
| **5** | **LLMJudge(裁决)** | 看多 vs 看空双角色辩论 → 裁决者综合出结构化信号 | `TokenSnapshot + Score` → `Signal` | LLM(默认 Codex CLI) | [`llmjudge/`](src/memedog/llmjudge/) |
| **6a** | **Backtester(历史验证)** | 回放历史价格,验证 MemeDog 信号是否有正期望 | `Signal[] + prices` → `BacktestReport` | 历史价格序列 / Bitget Playbook 外部回测 | [`backtest/`](src/memedog/backtest/) |
| **6b** | **PaperTrader(模拟交易)** | 开虚拟仓,按止盈/止损/超时平仓,记录盈亏 | `Signal` → `Position / TradeRecord` | Bitget market-data MCP(轮询价格) | [`papertrader/`](src/memedog/papertrader/) |
| **—** | **Dashboard / Alert(看板/告警)** | 可视化整条漏斗与盈亏;可选地把 BULLISH 信号推到 Telegram | 读取存储 | Streamlit · Telegram | [`dashboard/`](dashboard/) · [`alert/`](src/memedog/alert/) |

> 各段由 [`orchestrator.py`](src/memedog/orchestrator.py) 串联;带类型的数据对象定义在 [`models/`](src/memedog/models/)(见[数据契约](plan/08-data-contracts.md))。

---

## 3. 为什么这样设计(四条原则)

1. **漏斗 = 成本控制。** Scanner 每轮产出数百个;HardFilter 砍到个位数;只有幸存者进入 Enricher + LLM。正是这一点让多 agent LLM 辩论在高频 meme 币流上**变得可行**。
2. **数据与判断分离。** Enricher 只“取数”、ScoreEngine 只“算分”、LLMJudge 只“推理”。每一层可独立测试与替换。
3. **provider 无关的 LLM。** 业务代码只依赖 `LLMProvider` 接口,绝不直接 import 任何厂商 SDK。按模型串前缀路由:
   - `codex:<model>` → **CodexCLIProvider**(*本实验默认 —— 把 `codex exec` 当子进程,走 ChatGPT 订阅,零按量 API 成本*)
   - `litellm:<provider>/<model>` → LiteLLM(Claude / OpenAI / DeepSeek)用于对比
4. **降级,而非崩溃。** 任一数据源失败 → 该维度标记“缺失”(打分自动重新归一,并在 prompt 中告知 LLM)—— 流水线继续。若 LLM 本身不可达,LLMJudge 退化为基于规则的兜底信号。

---

## 4. 信号的具体构成

**硬红线**(任一不过即丢弃;所有阈值写在 [`config/thresholds.yaml`](src/memedog/config/thresholds.yaml),**严禁硬编码**):

- **合约权限** —— mint 权限已放弃 · freeze 权限已放弃 · LP 已烧毁/锁定
- **持币集中度** —— Top10(剔除 LP)≤ 35% · 单一钱包 < 20% · 开发者 < 10% · sniper 抢筹不畸高
- **流动性 / 动量** —— 流动性 ≥ $20k · 5 分钟量过下限 · 买卖比 ≥ 1 · FDV/流动性比合理

**四个打分维度**(加权到 0–100):

| 维度 | 主数据源 | 信号含义 |
|------|---------|---------|
| 安全 / Rug | RugCheck(trustScore、riskLevel) | 能不能卖出?是不是蜜罐? |
| 持币分布 | Helius RPC `getTokenLargestAccounts` | 集中度 / 砸盘风险 |
| 资金 / 流动性 / 动量 | Bitget market-data MCP `dex_market` / candidate pair data | 是否有真实资金流入? |
| 聪明钱 / 社交 | Helius(标注钱包)+ X/Twitter | 叙事热度与聪明钱兴趣 |

**LLM 裁决** → `Signal { signal, confidence, bull_points[], bear_points[], red_flags[], rationale }`。

---

## 4.1 Scanner 数据源与同名币处理

Scanner 通过一个很小的 discovery 接口工作:

```python
fetch_latest_token_addresses(chain) -> list[str]
get_token_pairs(mint) -> list[dict]
```

默认实现是 Bitget Hackathon Toolkit 里的 **market-data MCP** `dex_market` 工具。DexScreener 客户端保留为 fallback 和离线 fixture 测试源:

```yaml
scanner:
  source: bitget_mcp      # 默认
  bitget_mcp_url: https://datahub.noxiaohao.com/mcp
```

Bitget MCP 模式使用:

- `dex_market(action="trending", chain="solana")` 发现候选 token 地址
- `dex_market(action="token", token_address="solana/<mint>")` 拉取该 mint 的交易对详情

无论使用哪个数据源,系统都把 **Solana mint 地址** 当作唯一身份,`symbol` 只用于展示。因此两个都叫 `DOGE` 的 meme coin 不会互相覆盖。Scanner 在转换 pair 时会检查 `baseToken` 和 `quoteToken`,只采用与请求 mint 匹配的一侧,避免把同一交易对里的 SOL/USDC 或另一个同名 token 误当成目标币。

---

## 4.2 Backtesting 与 Bitget Playbook

MemeDog 有两层验证:

1. **内部 Signal Backtester** —— 对实际输出的 `Signal` 做历史价回放,复用 PaperTrader 的入场/出场规则:
   - 只交易 `BULLISH`
   - `confidence >= entry_min_confidence`
   - `take_profit_pct` / `stop_loss_pct` / `max_hold_minutes`
   - 输出胜率、总 PnL、平均 PnL、profit factor、最大回撤、逐笔 `TradeRecord`

2. **Bitget Playbook 导出** —— [`build_playbook_prompt`](src/memedog/backtest/playbook.py) 会生成可粘贴到 Bitget Playbook / GetAgent workflow 的策略 prompt,用于 hackathon 展示中的外部回测、指标表和发布。

内部回测用于验证 **MemeDog 自己的信号质量**;Bitget Playbook 用于把同一套策略哲学转成可展示、可发布的量化策略回测。

---

## 5. 技术栈

- **后端:** Python 3.11+ · `asyncio` + `httpx`(并行取数)
- **模型 / 数据契约:** `pydantic` v2
- **LLM:** provider 无关接口 → **Codex CLI**(默认)/ LiteLLM(Claude·OpenAI·DeepSeek)
- **配置:** `pydantic-settings` + `.env` + YAML 阈值文件(调策略不改代码)
- **存储:** SQLite(快照 / 信号 / 仓位 / 漏斗事件)
- **看板:** Streamlit · **告警:** Telegram Bot API(可选)

---

## 6. 如何运行

### 前置
- Python 3.11+、Node 18+(用于 Codex CLI)
- (可选)各 API key —— 缺失时系统会**优雅降级**。见 [`.env.example`](.env.example)。

### 安装
```bash
pip install -e ".[dev]"          # 或: pip install pydantic pydantic-settings httpx pyyaml litellm streamlit
cp .env.example .env             # 然后填入你拥有的 key
```

### LLM 后端(默认 = Codex CLI,走你的 ChatGPT 订阅,无需 API key)
```bash
npm i -g @openai/codex
codex login                      # 一次性浏览器登录你的 ChatGPT 账户
```
> 若想改用标准 API 对比,把 `thresholds.yaml` 里的 `llmjudge.models` 改成如 `litellm:openai/gpt-4o`,并在 `.env` 填 `OPENAI_API_KEY`。

### 各 key 放哪(项目根目录的 `.env`)
| 变量 | 作用 | 缺失时 |
|------|------|--------|
| `HELIUS_API_KEY` | 持币分布 / 聪明钱 | 该维度降级 |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram 告警 | 告警静默跳过 |
| `TWITTER_BEARER` | 社交热度 | 社交维度降级 |
| Codex | LLM 裁决 | **无需 env key** —— 用 `codex login` |
| Bitget market-data MCP | Scanner + 价格轮询 + news/sentiment 工具 | 默认公开 MCP URL,无需项目内 key |
| DexScreener fallback / RugCheck | fallback 扫描 + 安全 | 无需 key(公开) |

### Scanner 数据源

默认使用 Bitget MCP:

```yaml
scanner:
  source: bitget_mcp
  bitget_mcp_url: https://datahub.noxiaohao.com/mcp
```

如需回退到 DexScreener:

```yaml
scanner:
  source: dexscreener
```

### 启动
```bash
python -m memedog                       # 跑流水线(扫描 → … → 模拟交易)
python scripts/seed_demo.py             # 灌入示例数据用于看板演示
streamlit run dashboard/app.py          # 实时看板(信号、漏斗、盈亏)
```

---

## 7. 真实测试(不是只有 mock)

测试采用**真实数据驱动**,分两层:

- **默认套件 —— `pytest` → 446 个测试,完全离线、确定性。** 每个外部 API 测试都由**真实抓取的 API 响应体**驱动(存于 [`tests/fixtures/`](tests/fixtures/),可用 [`scripts/capture_fixtures.py`](scripts/capture_fixtures.py) 刷新;密钥/PII 绝不入库)。已验证**零外部联网**。
- **live 层 —— `pytest -m live` → 9 个测试**,真实命中 Bitget MCP / DexScreener fallback / RugCheck / Helius / Codex / Telegram,并跑一次完整端到端 cycle。缺对应 key/二进制时各自自动 skip;Telegram 双重闸门(`MEMEDOG_LIVE_TELEGRAM=1`)防止误发。

五个外部集成 + 一次完整的真实 `run_cycle` 均已真实跑通并确认可用。

---

## 8. 项目结构

```
src/memedog/
├── orchestrator.py        # 把 1→6 各段串成漏斗 cycle
├── models/                # 带类型的数据契约(TokenCandidate → Signal → TradeRecord)
├── clients/               # API 封装(dexscreener, bitget_mcp, rugcheck, helius, twitter)+ 带重试的基类
├── scanner/  hardfilter/  enricher/  scoring/  llmjudge/  backtest/  papertrader/
├── llm/                   # provider 无关的 LLM 层(codex / litellm)+ 结构化输出
├── alert/                 # Telegram
├── config/                # settings.py + thresholds.yaml
└── store.py               # SQLite 持久化
dashboard/app.py           # Streamlit 看板
plan/                      # 各模块设计文档(00 架构 … 08 数据契约)
docs/superpowers/          # spec + 实现计划
tests/  +  tests/live/     # 真实 fixture 套件 + 可选 live 层
```

各模块的设计理由见 [`plan/`](plan/) —— 建议从 [`plan/00-architecture.md`](plan/00-architecture.md) 看起。

---

## 9. 范围与局限(诚实说明)

- **仅模拟交易** —— 无钱包、无下单。盈亏为虚拟(默认忽略滑点/手续费)。
- **Solana 优先。** 新币通常高度集中 / 无社交,因此真正的 `BULLISH` 裁决(理应)很少。
- **Twitter** 需付费 X API 档位;没有时社交维度直接降级。
- **LLM 延迟** 每次裁决约 50–80 秒(3 次调用);可接受,因为漏斗每轮只送极少数候选进来。

---

*为 Bitget AI Hackathon 而构建。仅供研究与演示,非投资建议。*
