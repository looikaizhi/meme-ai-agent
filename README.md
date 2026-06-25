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
| **是真的能跑吗?** | 是 —— 已对 **DexScreener、RugCheck、Helius、Telegram、Codex** 全部真实联网验证,并跑通完整端到端 cycle。 |
| **怎么一眼看到效果?** | **一条命令** `python -m memedog.serve --demo` 同时拉起后端循环 + 实时看板,浏览器里能**实时看到 token 在漏斗里逐阶段流动**(离线、确定性、无需任何 key)。 |

---

## 2. 架构总览(一眼看懂)

整个系统是一条 **六段漏斗**。每一段都是职责单一的模块,模块之间只通过**带类型的数据对象**通信 —— 因此任何一层都可独立替换或调参。

```
                      每轮数百个
  ┌─────────────┐    ──────────────────►   ┌──────────────┐   幸存者(个位数)
  │ [1] Scanner │  TokenCandidate[]         │[2] HardFilter│  ──────────────────────────►
  └─────────────┘                           └──────────────┘
   轮询 DexScreener                          三类红线闸门
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
                                          ┌──────────────────────────────┤
                                          ▼                              ▼
                                  ┌────────────────┐            ┌──────────────────┐
                                  │[6] PaperTrader │            │  看板 + 告警       │
                                  └────────────────┘            └──────────────────┘
                                   开虚拟仓                       Streamlit 看板
                                   止盈/止损/超时平仓             + 可选 Telegram 推送
                                   跟踪虚拟盈亏
```

### 每一层具体做什么

| # | 层 | 一句话职责 | 输入 → 输出 | 主要数据源 | 代码 |
|---|-----|-----------|------------|-----------|------|
| **1** | **Scanner(扫描器)** | 轮询新盘,只留有早期动量的,并去重 | `()` → `TokenCandidate[]` | DexScreener(免费) | [`scanner/`](src/memedog/scanner/) |
| **2** | **HardFilter(硬规则闸门)** | 在花任何 LLM 之前,用三类客观红线排掉 rug/蜜罐 | `TokenCandidate[]` → `TokenCandidate[]` | RugCheck | [`hardfilter/`](src/memedog/hardfilter/) |
| **3** | **Enricher(数据富化)** | **并行**抓取 4 个信号维度,失败优雅降级 | `TokenCandidate` → `TokenSnapshot` | RugCheck · Helius RPC · DexScreener · X/Twitter | [`enricher/`](src/memedog/enricher/) |
| **4** | **ScoreEngine(打分)** | 把 4 维映射成 **0–100** 加权分(给 LLM 的客观锚点) | `TokenSnapshot` → `Score` | 纯逻辑,配置驱动 | [`scoring/`](src/memedog/scoring/) |
| **5** | **LLMJudge(裁决)** | 把原始链上证据喂给 Bull/Bear 双角色辩论,裁决者按**固定 6 步 workflow**(安全→集中度→动量→社交→辩论→裁决)推理出结构化信号,并用数据完备度给置信度封顶 | `TokenSnapshot + Score` → `Signal` | LLM(默认 Codex CLI) | [`llmjudge/`](src/memedog/llmjudge/) |
| **6** | **PaperTrader(模拟交易)** | 开虚拟仓,按止盈/止损/超时平仓,记录盈亏 | `Signal` → `Position / TradeRecord` | DexScreener(轮询价格) | [`papertrader/`](src/memedog/papertrader/) |
| **—** | **Dashboard / Alert(看板/告警)** | 顶部**实时活动流**逐阶段滚动 + 信号/漏斗/盈亏可视化;可选地把 BULLISH 信号推到 Telegram | 读取存储 | Streamlit · Telegram | [`dashboard/`](dashboard/) · [`alert/`](src/memedog/alert/) |

> 各段由 [`orchestrator.py`](src/memedog/orchestrator.py) 串联(每阶段发**实时事件**到 SQLite 供看板 tail);带类型的数据对象定义在 [`models/`](src/memedog/models/)(见[数据契约](plan/08-data-contracts.md))。一键服务器入口见 [`serve.py`](src/memedog/serve.py)。

### [2] HardFilter 的三类红线(花 LLM 之前的排雷)

> 顺序 fail-fast:先跑**免费、不联网**的动量规则,过了才调 RugCheck 取权限/持币。任一红线不过即丢弃,并记录"是哪条规则、实际值 vs 阈值"供看板回溯。所有阈值集中在 [`thresholds.yaml`](src/memedog/config/thresholds.yaml) 的**调参面板**(含义+建议区间+影响哪一关),改参数不改代码。

| 类别 | 规则(默认阈值) |
|------|----------------|
| **A. 合约权限** | mint 权限已放弃 · freeze 权限已放弃 · LP 已烧毁/锁定(任一不满足即丢) |
| **B. 持币集中度** | Top10 ≤ 35% · 单一钱包 < 20% · 开发者 < 10% · sniper < 30%(**占比已自动剔除 AMM/LP 池**) |
| **C. 流动性/动量** | 流动性 ≥ $13k · 5min 量 ≥ $300 · FDV/流动性 ≤ 8 · 买卖比兜底 ≥ 0.2(其余交打分) |

---

## 3. 为什么这样设计(四条原则)

1. **漏斗 = 成本控制。** Scanner 每轮产出数百个;HardFilter 砍到个位数;只有幸存者进入 Enricher + LLM。正是这一点让多 agent LLM 辩论在高频 meme 币流上**变得可行**。
2. **数据与判断分离。** Enricher 只“取数”、ScoreEngine 只“算分”、LLMJudge 只“推理”。每一层可独立测试与替换。
3. **provider 无关的 LLM。** 业务代码只依赖 `LLMProvider` 接口,绝不直接 import 任何厂商 SDK。按模型串前缀路由:
   - `codex:<model>` → **CodexCLIProvider**(*本实验默认 —— 把 `codex exec` 当子进程,走 ChatGPT 订阅,零按量 API 成本*)
   - `litellm:<provider>/<model>` → LiteLLM(Claude / OpenAI / DeepSeek)用于对比
4. **降级,而非崩溃。** 任一数据源失败 → 该维度标记“缺失”(打分自动重新归一,并在 prompt 中告知 LLM)—— 流水线继续。若 LLM 本身不可达,LLMJudge 退化为基于规则的兜底信号。
5. **长跑要稳、不泄密。** HTTP 层做**错误分类重试**(4xx 不重试、429/503 读 `Retry-After`、退避加 jitter)+ **按数据源限流**(并发上限 + 最小间隔,防 429 被封);全局日志过滤器保证 **API key / token 永不进日志**。

---

## 4. 信号的具体构成

**硬红线**(任一不过即丢弃;所有阈值写在 [`config/thresholds.yaml`](src/memedog/config/thresholds.yaml),**严禁硬编码**):

- **合约权限** —— mint 权限已放弃 · freeze 权限已放弃 · LP 已烧毁/锁定
- **持币集中度** —— Top10(**已剔除 AMM/LP 池**)≤ 35% · 单一钱包 < 20% · 开发者 < 10% · sniper < 30%
- **流动性 / 动量** —— 流动性 ≥ $13k · 5 分钟量 ≥ $300 · FDV/流动性 ≤ 8 · 买卖比兜底 ≥ 0.2(其余交打分)

> 阈值集中在 [`thresholds.yaml`](src/memedog/config/thresholds.yaml) 的调参面板,均来自对 100 个真实毕业币的实测分布;改参数只动这一个文件。

**四个打分维度**(加权到 0–100):

| 维度 | 主数据源 | 信号含义 |
|------|---------|---------|
| 安全 / Rug | RugCheck(trustScore、riskLevel) | 能不能卖出?是不是蜜罐? |
| 持币分布 | Helius RPC `getTokenLargestAccounts` | 集中度 / 砸盘风险 |
| 资金 / 流动性 / 动量 | DexScreener | 是否有真实资金流入? |
| 聪明钱 / 社交 | Helius(标注钱包)+ X/Twitter | 叙事热度与聪明钱兴趣 |

**LLM 裁决** → `Signal { signal, confidence, bull_points[], bear_points[], red_flags[], rationale }`。

---

## 5. 技术栈

- **后端:** Python 3.11+ · `asyncio` + `httpx`(并行取数)
- **模型 / 数据契约:** `pydantic` v2
- **LLM:** provider 无关接口 → **Codex CLI**(默认)/ LiteLLM(Claude·OpenAI·DeepSeek)
- **配置:** `pydantic-settings` + `.env` + YAML 阈值文件(调策略不改代码)
- **存储:** SQLite(快照 / 信号 / 仓位 / 漏斗事件 / 逐阶段实时事件)
- **看板:** Streamlit(实时活动流 + 信号/漏斗/盈亏)· **告警:** Telegram Bot API(可选)
- **健壮性:** 错误分类重试 + 按源限流 + 全局密钥脱敏(`observability/redaction.py`)
- **一键服务器:** `serve.py` launcher + 离线 `--demo` 模式

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
| DexScreener / RugCheck | 扫描 + 安全 | 无需 key(公开) |

### 启动

**一键(推荐)—— 后端循环 + 实时看板一起拉起:**
```bash
python -m memedog.serve --demo          # demo 模式:漏斗持续流动,离线确定性,无需任何 key
python -m memedog.serve                 # 生产模式:真实 DexScreener/RugCheck/Helius/Codex
```
打开 `http://localhost:8501`,顶部"🔴 实时活动流"会随后端逐阶段滚动。`Ctrl-C` 一起优雅退出(看板子进程会被关闭)。
常用参数:`--port`(看板端口)、`--db`(SQLite 路径)、`--scan-interval`(轮询间隔秒)。

> **demo 模式**:用真实抓取的 fixtures 快速喂候选过**真实**的 HardFilter/ScoreEngine/裁决逻辑/PaperTrader,只把"慢 codex 调用"替换为已捕获的判决输出 → 几秒一个候选、全程离线,适合 5 分钟现场演示。

**或分进程手动起:**
```bash
python -m memedog                       # 只跑流水线(扫描 → … → 模拟交易)
python scripts/seed_demo.py             # 灌入示例数据用于看板演示
streamlit run dashboard/app.py          # 只起看板
```

---

## 7. 真实测试(不是只有 mock)

测试采用**真实数据驱动**,分两层:

- **默认套件 —— `pytest` → 534 个测试,完全离线、确定性。** 每个外部 API 测试都由**真实抓取的 API 响应体**驱动(存于 [`tests/fixtures/`](tests/fixtures/),可用 [`scripts/capture_fixtures.py`](scripts/capture_fixtures.py) 刷新;密钥/PII 绝不入库)。已验证**零外部联网**(`pytest --disable-socket --allow-hosts=127.0.0.1,::1,localhost`)。覆盖智能重试/限流、密钥脱敏、实时事件流,以及完整的离线 `--demo` 端到端 cycle。
- **live 层 —— `pytest -m live` → 9 个测试**,真实命中 DexScreener / RugCheck / Helius / Codex / Telegram,并跑一次完整端到端 cycle。缺对应 key/二进制时各自自动 skip;Telegram 双重闸门(`MEMEDOG_LIVE_TELEGRAM=1`)防止误发。

五个外部集成 + 一次完整的真实 `run_cycle` 均已真实跑通并确认可用。

---

## 8. 项目结构

```
src/memedog/
├── serve.py               # 一键 launcher(后端循环 + streamlit 子进程 + 优雅退出)
├── orchestrator.py        # 把 1→6 各段串成漏斗 cycle,逐阶段发实时事件
├── models/                # 带类型的数据契约(TokenCandidate → Signal → TradeRecord)
├── clients/               # 每个 API 一个封装 + 带重试/限流的基类 + ratelimit.py
├── scanner/  hardfilter/  enricher/  scoring/  llmjudge/  papertrader/
├── llm/                   # provider 无关的 LLM 层(codex / litellm)+ 结构化输出
├── demo/                  # 离线 demo 源(fixture 候选 + ReplayProvider + 随机游走价格)
├── observability/         # 全局密钥脱敏日志过滤器
├── alert/                 # Telegram
├── config/                # settings.py + thresholds.yaml(含 http / 阈值 / 置信度护栏)
└── store.py               # SQLite 持久化(含 pipeline_events 实时事件)
dashboard/app.py           # Streamlit 看板(实时活动流 + 信号/漏斗/盈亏)
plan/                      # 各模块设计文档(00 架构 … 08 数据契约)
docs/superpowers/          # spec + 实现计划
tests/                     # 测试套件
```

各模块的设计理由见 [`plan/`](plan/) —— 建议从 [`plan/00-architecture.md`](plan/00-architecture.md) 看起。

---

## 9. 范围与局限(诚实说明)

- **仅模拟交易** —— 无钱包、无下单。盈亏为虚拟(默认忽略滑点/手续费)。
- **Solana 优先。** 新币通常高度集中 / 无社交,因此真正的 `BULLISH` 裁决(理应)很少。
- **Twitter** 需付费 X API 档位;没有时社交维度直接降级。
- **LLM 延迟** 真实裁决约数十秒至数分钟(3 次顺序 codex 调用,受 ChatGPT 订阅吞吐影响);可接受,因为漏斗每轮只送极少数候选进来。**现场演示请用 `--demo`**,它 replay 已捕获的判决、瞬时出信号。

---

*为 Bitget AI Hackathon 而构建。仅供研究与演示,非投资建议。*
