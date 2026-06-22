# CLAUDE.md

本文件为 Claude Code 提供本项目的上下文。修改架构、约定或命令时,请同步更新本文件。

## 项目定位

**MemeDog Radar** —— Solana 链上 meme 币(金狗)早期动量监测与信号系统。

在 meme 币生命周期的 **"初有动量"阶段(发盘后几十分钟~几小时)** 介入:
监测新盘 → 硬规则排雷 → 多维链上数据富化 → 规则量化打分 → LLM 双视角(Bull/Bear)辩论终审 →
输出 `BULLISH / BEARISH / NEUTRAL` 信号 → 模拟交易跟踪虚拟盈亏 → 前端看板展示。

- **范围**:监控 + 信号 + 模拟交易(paper trading)。**不接真实钱包、不真实下单。**
- **目标链**:Solana(pump.fun / Raydium 生态)。
- **声明**:研究/演示用途,非投资建议。

## 核心设计原则

1. **漏斗式处理**:Scanner 每轮产出几百候选 → HardFilter 砍到个位数 → 只有过闸的才进入数据富化与 LLM。
   目的:把昂贵的 LLM 调用约束在极少数候选上,使高频场景下使用 LLM 可行。
2. **数据与判断分离**:取数(Enricher)/ 算分(ScoreEngine)/ 推理(LLMJudge)三层解耦,任一层可独立迭代。
3. **模块化优先**:每个模块职责单一、通过结构化数据对象通信、可独立单测与替换。
4. **阈值全部可配置**:所有风控阈值、权重写入 config,**严禁硬编码**,调参不改代码。

## 流水线与模块边界

```
[1] Scanner      → 轮询 Bitget market-data MCP,筛"初有动量"候选 → 产出 TokenCandidate
[2] HardFilter   → 三类红线(合约权限/持币集中度/资金动量)    → 过滤候选
[3] Enricher     → 并行抓 4 维信号,组装 TokenSnapshot         → 产出 TokenSnapshot
[4] ScoreEngine  → 4 维加权打分 0~100                          → 产出 Score
[5] LLMJudge     → Bull/Bear 双视角 + 裁决                      → 产出 Signal
[6a] Backtester  → 历史价回放 / 验证胜率PNL回撤 / Playbook导出 → 产出 BacktestReport
[6b] PaperTrader → 开虚拟仓 / 轮询价格 / 止盈止损超时平仓        → 产出 Position / PnL
     │
     └─→ Dashboard(轻前端看板) + Alert(可选 Telegram)
```

每个模块的详细方案见 `plan/` 目录,与上面编号一一对应。

## 四维信号与数据源

| 维度 | 主数据源 | 备选 |
|------|---------|------|
| 安全 / Rug | RugCheck API(trustScore 0~100、riskLevel) | GoPlus Security API |
| 持币分布 / 集中度 | Helius RPC / Solana RPC `getTokenLargestAccounts` | Birdeye |
| 资金 / 流动性 / 动量 | Bitget market-data MCP `dex_market`(默认) | DexScreener / Birdeye |
| 聪明钱 / 社交热度 | Helius(标注钱包) + X/Twitter 搜索 | LunarCrush |

## 硬规则红线(默认值,可在 config 调整)

**A. 合约权限(任一不过即丢弃)**:mint authority 已放弃 / freeze authority 已放弃 / LP 已烧毁或锁定。
**B. 持币集中度**:Top10 持仓(剔除 LP)≤ 30~40% / 单一钱包 < 20% / 开发者 < 5~10% / sniper 抢筹不畸高。
**C. 资金动量门槛**:流动性 ≥ $15k~30k / 5min·1h 量过下限 / 独立买家正增长 / FDV·流动性比不畸高 / 池龄在窗口内。

## 技术栈

- **后端**:Python 3.11+
- **异步/并发**:`asyncio` + `httpx`(并行调多个数据 API)
- **LLM(provider 无关)**:自定义 `LLMProvider` 抽象接口,按模型串前缀路由:
  - `codex:<model>` → **`CodexCLIProvider`(本实验默认)**:把 OpenAI Codex CLI 当无交互子进程(`codex exec --output-last-message`),走 ChatGPT Plus 订阅额度,零按量费用。前置:`npm i -g @openai/codex` + `codex login`。
  - `litellm:<provider>/<model>` → `LiteLLMProvider`(备选):标准 API,可切 Claude / DeepSeek 对比。
  - 角色:bull / bear / judge 可各自指定模型(本实验均 `codex:default`)。
  - 结构化输出:统一走"要求 JSON + pydantic 校验 + 一次修复重试",规避各家差异。
  - 详见 `plan/05-llmjudge.md`。
- **数据处理**:`pandas` / `pandas-ta`(技术指标,如需)
- **配置**:`pydantic-settings` + `.env` + YAML 阈值文件
- **前端看板**:Streamlit(hackathon 优先,出图快;后续可替换为 React)
- **告警(可选)**:Telegram Bot API
- **回测**:`src/memedog/backtest/` 内部回放 MemeDog 信号;`build_playbook_prompt` 导出 Bitget Playbook 策略 prompt

## 目录结构(规划)

```
.
├── CLAUDE.md
├── plan/                      # 各模块设计方案(见下)
│   ├── 00-architecture.md
│   ├── 01-scanner.md
│   ├── 02-hardfilter.md
│   ├── 03-enricher.md
│   ├── 04-scoreengine.md
│   ├── 05-llmjudge.md
│   ├── 06-papertrader.md
│   ├── 07-dashboard-alert.md
│   └── 08-data-contracts.md
├── src/memedog/               # 待实现
│   ├── scanner/
│   ├── hardfilter/
│   ├── enricher/
│   ├── scoring/
│   ├── llmjudge/
│   ├── backtest/
│   ├── papertrader/
│   ├── models/                # 结构化数据对象(数据契约)
│   ├── clients/               # 各数据源 API 封装
│   └── config/
├── dashboard/                 # Streamlit 看板
└── tests/
```

## 约定

- **类型**:全量 type hints;模块间数据对象用 `pydantic` model(见 `plan/08-data-contracts.md`)。
- **数据源访问**:统一封装在 `src/memedog/clients/`,每个外部 API 一个 client,带重试/超时/限流。
- **错误处理**:单个数据源失败不应让整条流水线崩——降级为"该维度缺失"并在 Score/Signal 中标注。
- **密钥**:所有 API key 走 `.env`,不入库。
- **测试**:每个模块可独立单测;外部 API 用 fixture/mock,不在测试中真实联网。
- **可观测**:每个候选币从进入到出信号的全过程要可追溯(结构化日志)。

## 当前状态

设计阶段。`plan/` 目录为各模块实现蓝图;`src/` 尚未实现。先读对应的 `plan/*.md` 再动手实现某模块。
