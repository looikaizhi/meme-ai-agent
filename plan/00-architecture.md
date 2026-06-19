# MemeDog Radar 架构总览

> 本文件是整个系统的设计基线。各模块详细方案见同目录 `01`~`08`。
> 实现某个模块前,先读本文件 + 该模块对应的 `0X-*.md` + `08-data-contracts.md`。

**目标:** Solana meme 币(金狗)早期动量监测与信号系统——监控、信号、模拟交易。

**架构:** 漏斗式六段流水线。Scanner 海量进、HardFilter 砍到个位数、Enricher 富化、ScoreEngine 量化打分、LLMJudge 双视角辩论终审、PaperTrader 模拟交易。模块间只通过结构化数据对象通信,取数/算分/推理三层解耦。

**技术栈:** Python 3.11+ / asyncio + httpx / Anthropic SDK(Claude)/ pydantic / Streamlit。

---

## 1. 设计原则(不可妥协)

1. **漏斗控成本**:LLM 只作用于极少数过闸候选。Scanner→HardFilter 必须把每轮候选从几百压到个位数。
2. **数据与判断分离**:Enricher 只取数,ScoreEngine 只算分,LLMJudge 只推理。任一层可独立替换。
3. **模块化**:每模块单一职责、明确接口、可独立单测。模块间不共享内部状态,只传数据对象。
4. **阈值/权重全可配置**:写入 `config/`,严禁硬编码。
5. **降级而非崩溃**:单个数据源失败 → 标注该维度缺失,流水线继续。

## 2. 数据流(漏斗)

```
DexScreener 新盘
      │  每轮 ~数百
      ▼
[1] Scanner ──────────► List[TokenCandidate]      (基础市场数据 + 去重)
      │  ~数百
      ▼
[2] HardFilter ───────► List[TokenCandidate]      (三类红线过滤,剩个位数)
      │  个位数
      ▼
[3] Enricher ─────────► TokenSnapshot             (4 维并行抓取后的完整快照)
      │
      ▼
[4] ScoreEngine ──────► Score                     (4 维加权 0~100 + 分项明细)
      │
      ▼
[5] LLMJudge ─────────► Signal                    (BULLISH/BEARISH/NEUTRAL + 理由)
      │
      ▼
[6] PaperTrader ──────► Position / TradeRecord     (虚拟开平仓 + 盈亏)
      │
      └──► Dashboard(Streamlit) + Alert(Telegram 可选)
```

每段输入输出的精确类型定义见 `08-data-contracts.md`。

## 3. 模块清单与对应文档

| # | 模块 | 职责一句话 | 输入 → 输出 | 文档 |
|---|------|-----------|------------|------|
| 1 | Scanner | 轮询拉新盘、初筛动量、去重 | `()` → `List[TokenCandidate]` | `01-scanner.md` |
| 2 | HardFilter | 三类红线排雷 | `List[TokenCandidate]` → `List[TokenCandidate]` | `02-hardfilter.md` |
| 3 | Enricher | 4 维并行富化 | `TokenCandidate` → `TokenSnapshot` | `03-enricher.md` |
| 4 | ScoreEngine | 加权量化打分 | `TokenSnapshot` → `Score` | `04-scoreengine.md` |
| 5 | LLMJudge | Bull/Bear 辩论 + 裁决 | `TokenSnapshot + Score` → `Signal` | `05-llmjudge.md` |
| 6 | PaperTrader | 模拟交易与盈亏 | `Signal` → `Position/TradeRecord` | `06-papertrader.md` |
| — | Dashboard/Alert | 展示与告警 | 读全链路 | `07-dashboard-alert.md` |
| — | 数据契约 | 模块间数据对象 | — | `08-data-contracts.md` |

## 4. 目录结构

```
src/memedog/
├── orchestrator.py        # 串起 1→6 的主循环(asyncio)
├── models/                # 数据契约(pydantic),见 08
├── clients/               # 外部 API 封装:dexscreener / rugcheck / helius / twitter
│   └── base.py            # 统一重试/超时/限流基类
├── scanner/
├── hardfilter/
├── enricher/
├── scoring/
├── llmjudge/
├── papertrader/
├── config/                # settings.py(pydantic-settings) + thresholds.yaml
└── store.py               # 轻量持久化(SQLite,存快照/信号/仓位供看板读)
dashboard/app.py           # Streamlit
tests/                     # 与 src 镜像
```

## 5. 编排主循环(orchestrator)

```python
async def run_cycle(cfg):
    candidates = await scanner.scan()                 # [1]
    candidates = hardfilter.apply(candidates, cfg)    # [2] 同步、纯函数
    for cand in candidates:                            # 个位数,可并发受限
        snap  = await enricher.enrich(cand, cfg)       # [3]
        score = scoreengine.score(snap, cfg)           # [4]
        signal = await llmjudge.judge(snap, score, cfg) # [5]
        store.save(snap, score, signal)
        papertrader.on_signal(signal)                  # [6]
        alert.maybe_notify(signal, cfg)
# 主循环按 cfg.scan_interval 周期调用 run_cycle;PaperTrader 另有价格轮询协程
```

## 6. 配置体系

- `config/settings.py`:`pydantic-settings`,从 `.env` 读 API key、模型 id、轮询间隔。
- `config/thresholds.yaml`:所有硬规则阈值与打分权重,运行时加载。
- 原则:**改策略只改 YAML,改密钥只改 .env,不改代码。**

## 7. 错误处理与可观测

- 每个外部 client:超时 + 指数退避重试 + 限流;失败抛 `DataSourceError`。
- Enricher 捕获单维失败 → 在 `TokenSnapshot` 标记 `<dim>_available=False`,继续。
- ScoreEngine/LLMJudge 对缺失维度降权并在输出 `notes` 注明。
- 结构化日志:每个候选币带 `trace_id`,可追溯从扫描到信号到平仓全过程。

## 8. 实现顺序建议

1. `08` 数据契约(所有模块依赖)
2. `clients/base.py` + 各 client(可 mock 联调)
3. `01 Scanner` → `02 HardFilter`(先打通漏斗前段)
4. `03 Enricher` → `04 ScoreEngine`
5. `05 LLMJudge`
6. `06 PaperTrader`
7. `orchestrator` 串联
8. `07 Dashboard/Alert`

每模块 TDD:先写失败测试(外部 API 全 mock)→ 最小实现 → 通过 → commit。
