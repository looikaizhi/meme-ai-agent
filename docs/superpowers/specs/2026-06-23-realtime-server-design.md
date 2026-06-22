# 设计:实时可观测 + 一键本地服务器(子项目 C)

- **日期**:2026-06-23
- **分支**:`feature/realtime-server`
- **状态**:已获用户批准(设计阶段),待写实现计划
- **范围归属**:第二阶段三段拆分(A 信号质量 ✅ → B 健壮性 ✅ → **C 实时服务器**)的最后一块,最终交付物。

## 背景与动机

A、B 已合入 main。流水线能跑、信号有深度、长跑稳。C 把成果**实时摊在台面上**:一条命令同时拉起后端循环 + 实时看板 + 统一日志,demo 时一眼看懂 token 在漏斗里流动。

现状:
- `python -m memedog` 跑后端循环写 SQLite;`streamlit run dashboard/app.py` 是**独立进程**读 SQLite,30s 轮询。
- 漏斗事件**仅按轮记录**(scanned/passed/signals + dropped/flagged),粒度粗、延迟高。
- 现实中 HardFilter 严、codex 一次判决 ~数分钟 → 5 分钟 demo 期间漏斗常常"不动"。

用户确认的三个方向:
1. **Launcher 进程**:一条命令拉起后端 asyncio 循环 + streamlit 子进程,统一日志,Ctrl-C 一起优雅退出。
2. **逐阶段实时事件流**:后端每走一步 append 一条事件,看板顶部滚动"实时活动流"。
3. **Demo 模式**:`--demo` 用真实捕获的 fixtures 快速馈送候选过真流水线、replay 掉慢 codex,保证漏斗持续流动;不传则走完全真实链路。

## 范围边界

**要动 / 新增**:
- `src/memedog/store.py` — 新增 `pipeline_events` 表 + `save_event` / `recent_events`
- `src/memedog/orchestrator.py` — 加 `_emit` 插桩(每阶段发事件),构造期接收可选 emit 开关
- `src/memedog/serve.py`(新)— launcher 入口 `python -m memedog.serve`
- `src/memedog/demo/__init__.py` + `demo_source.py`(新)— Demo 候选源 + `ReplayProvider`
- `src/memedog/app_factory.py` — 支持 demo 注入(demo scanner + replay provider)
- `dashboard/app.py` — 顶部新增"实时活动流"区 + demo 模式刷新更快
- 相关测试

**不动**:
- HardFilter / ScoreEngine / Enricher / LLMJudge 的**业务逻辑**(C 只在 orchestrator 编排处插桩 + 在 demo 注入 seam)
- A/B 已完成的信号质量与健壮性逻辑
- models / 数据契约(事件表是新增,不改既有契约)

## 组件设计

### ① 实时事件流

`store.py` 新增:
```sql
CREATE TABLE IF NOT EXISTS pipeline_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,      -- ISO8601 UTC
    trace_id  TEXT NOT NULL DEFAULT '',
    stage     TEXT NOT NULL,      -- scan|hardfilter|enrich|score|judge|signal|trade|error
    mint      TEXT NOT NULL DEFAULT '',
    symbol    TEXT NOT NULL DEFAULT '',
    status    TEXT NOT NULL DEFAULT '',  -- start|ok|drop|flag|degraded|fail|...
    detail    TEXT NOT NULL DEFAULT ''
);
```
- `save_event(stage, *, trace_id="", mint="", symbol="", status="", detail="") -> None`:单行 insert,`ts=now(UTC).isoformat()`。
- `recent_events(limit=50) -> list[dict]`:按 `id` 倒序返回最近 N 条(键:ts(datetime)、trace_id、stage、mint、symbol、status、detail)。

`orchestrator.py`:
- 新增私有 `_emit(stage, *, trace_id="", mint="", symbol="", status="", detail="")`:`try: self._store.save_event(...) except Exception: logger.debug(...)`。绝不抛。
- 在 `run_cycle` 关键转换处调用(不改各阶段逻辑):
  - scan 后:`_emit("scan", status="ok", detail=f"{N} candidates")`
  - hardfilter 后:`_emit("hardfilter", status="ok", detail=f"{passed}/{scanned} passed")`;对每个 dropped/flagged 各发一条(mint+status=drop/flag)
  - 每个存活候选:enrich 前 `status=start`、score 后 `detail=总分`、judge 后 `status=ok/degraded` + signal 后 `detail=signal+conf`、trade 开仓后 `status=ok`
  - 候选异常:`_emit("error", mint=..., status="fail", detail=str(exc))`
- emit 默认开启(store 已注入);零额外依赖。

### ② Launcher(`src/memedog/serve.py`)

`python -m memedog.serve [--demo] [--db PATH] [--port N] [--scan-interval S]`

流程:
1. `argparse` 解析 flags;`logging.basicConfig` + `install_redaction(cfg.settings)`。
2. `cfg = load_config()`;`--scan-interval` 覆盖 `cfg.scanner.scan_interval_sec`(可选)。
3. 设环境 `MEMEDOG_DB`(子进程 dashboard 共享同库);demo 时设 `MEMEDOG_DEMO=1`(dashboard 据此刷快)。
4. 以子进程拉起 streamlit:`[sys.executable, "-m", "streamlit", "run", "<dashboard/app.py>", "--server.port", str(port), "--server.headless", "true"]`,继承 stdout/stderr(统一输出)。
5. 构造 orchestrator:`build_orchestrator(cfg, store, demo=args.demo)`;构造 PriceWatcher —— 生产用 `build_price_fn(dex_client)`,demo 用 `build_demo_price_fn()`(见 ③,不联网)。
6. `asyncio.gather(orchestrator.run_forever(stop), watcher.run(stop))`。
7. **优雅退出**:注册 SIGINT(及 Windows 下 KeyboardInterrupt)→ set stop_event → 等任务取消 → `streamlit_proc.terminate()`(超时再 kill)→ `store.close()`。
8. streamlit 子进程意外退出 → 记日志并触发主进程停止。

### ③ Demo 模式(`src/memedog/demo/`)

`demo_source.py`:
- `DemoScanner`:`async scan() -> list[TokenCandidate]`,从真实捕获的 dexscreener fixtures 构造一批候选,每轮轮转返回 1–3 个(保证 hardfilter 有的能过);带轻微随机化让画面有变化。
- `build_demo_snapshot(candidate) -> TokenSnapshot`:用 rugcheck/helius fixtures 拼装合法快照(供 demo enricher 直接返回,避免网络)。
- `DemoEnricher`:`async enrich(candidate) -> TokenSnapshot`,直接返回 `build_demo_snapshot`(不联网)。
- `ReplayProvider`:实现 `LLMProvider.complete`;按 bull→bear→judge **循环**返回已捕获的 `codex/bull_argument.txt` / `bear_argument.txt` / `judge_*.json` fixtures(瞬时,不调 codex)。与 `FakeProvider` 区别:无限循环、不耗尽。
- `build_demo_price_fn() -> async callable(mint)->float|None`:返回随机游走价格(围绕入场价上下波动),让 demo 中持仓能触发止盈/止损、PnL 动起来,**不联网**。serve 在 `--demo` 时用它替代 `build_price_fn(dex_client)`。

`app_factory.build_orchestrator(cfg, store, demo=False)`:
- `demo=False`:与现状一致(真 scanner/enricher/clients/codex)。
- `demo=True`:scanner=`DemoScanner`、enricher=`DemoEnricher`、`LLMJudge(cfg.llmjudge, provider=ReplayProvider())`;HardFilter/ScoreEngine/PaperTrader/事件发射**全真实**。
- demo 时缩短轮间隔(在 serve 里把 scan_interval 设小,如 3s)。

**Demo 真实/模拟边界(明确)**:demo 中 HardFilter、ScoreEngine、LLMJudge 判决逻辑、PaperTrader、事件流是**真实代码跑在真实捕获数据上**;被替换的只有"取数"(scanner/enricher 的网络)与"慢 codex 调用"。这与项目"真实数据、不编造"的约定一致(fixtures 是真实捕获的响应)。

### ④ 看板实时化(`dashboard/app.py`)

- 顶部新增 **"🔴 实时活动流"** 区:`store.recent_events(limit=40)` 倒序展示(stage 图标 + symbol + status + detail + HH:MM:SS)。
- 刷新:`MEMEDOG_DEMO=1` 时 autorefresh 间隔取小(默认 3s),否则维持原值。
- 现有 4 区(信号流 / 模拟交易 / 漏斗 / 配置)保留不变。

## 数据流

```
python -m memedog.serve --demo
  ├─ subprocess: streamlit run dashboard/app.py ──reads──► SQLite ◄──writes── 后端
  │                                  (实时活动流 / 信号 / 交易 / 漏斗)
  └─ asyncio: orchestrator.run_forever ──每阶段 _emit→save_event──► pipeline_events
             + PriceWatcher
  demo: DemoScanner + DemoEnricher(fixtures) + ReplayProvider(captured judge)
        → 真实 HardFilter/Score/Judge逻辑/PaperTrader → 事件流
```

## 错误处理 / 不变量

- `_emit` / `save_event` 异常被吞,绝不影响流水线(run_cycle 仍 never-raise)。
- launcher:任一后端任务异常被 run_forever 内部吞;streamlit 子进程崩溃 → 记录 + 主进程停止;退出路径保证 terminate 子进程 + 关 store。
- demo 注入只在 `demo=True` 生效;生产路径零行为变化。
- 事件表是 append-only,不影响既有读路径与契约。

## 测试策略(真实调用,非 mock 假设)

沿用"真实数据 fixture + 离线默认"约定。

**离线层(默认):**
- Store:`save_event`/`recent_events` 真实 SQLite 往返(顺序、字段、limit、时间解析)。
- Orchestrator 事件插桩:用既有真实 fixtures 跑一轮 `run_cycle`,断言发出预期 stage 序列(scan→hardfilter→…→signal/trade);`save_event` 抛错时 run_cycle 仍正常返回(注入坏 store)。
- `ReplayProvider`:循环返回真实 fixtures,N 次调用不耗尽;经 `complete_structured` 能解析出 JudgeOut。
- `DemoScanner`/`build_demo_snapshot`/`DemoEnricher`:产出合法 `TokenCandidate`/`TokenSnapshot`(pydantic 校验通过),enrich 不联网。
- `build_orchestrator(demo=True)`:scanner 是 DemoScanner、judge 的 provider 是 ReplayProvider(结构断言,不联网)。
- Launcher:monkeypatch `subprocess.Popen`/`asyncio` —— 断言会用正确参数拉起 streamlit、注册 stop、收到停止信号后 terminate 子进程 + 关 store(**不真起 streamlit、不真联网**)。
- Dashboard:live 区渲染 smoke(`ast.parse` + 调 `main()` 在注入了事件的临时 DB 上不抛)。

**端到端真实小验证(非 mock):**
- 一次性脚本:用临时 DB 跑 `build_orchestrator(cfg, store, demo=True)` 的 `run_cycle()` 真实若干轮,断言 `recent_events` 里出现 scan/hardfilter/score/judge/signal 事件且 `recent_signals` 有真实形态信号 —— 全程离线、确定性。验证后删脚本。

**live 层**:不新增强制 live;既有 live 不破。

## 验收标准

1. `python -m memedog.serve --demo` 一条命令拉起后端 + streamlit;Ctrl-C 优雅退出(子进程被 terminate、store 关闭)。
2. 看板顶部"实时活动流"随后端逐阶段滚动更新。
3. demo 模式下漏斗持续流动(几秒一个候选),信号/交易实时出现,全程离线。
4. 生产模式(无 `--demo`)行为与现状一致,走真实 scanner/enricher/codex。
5. 默认测试套件全过且零外部联网;既有 live 不破。
6. HardFilter/ScoreEngine/LLMJudge 业务逻辑、models 未被改动。

## 非目标(明确排除)

- 不替换 Streamlit 为 React/自研前端。
- 不做 WebSocket/SSE 推送(走 SQLite 轮询,够用且与现架构一致)。
- 不做多用户/鉴权/部署(本地单机)。
- 不引入 codex 熔断、缓存(此前已归为往后放)。
- demo 模式不"伪造"判决逻辑——judge 逻辑真实,只 replay LLM 文本输出(真实捕获)。
