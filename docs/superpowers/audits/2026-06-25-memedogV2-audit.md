# memedogV2 代码审计报告

> 日期:2026-06-25 · 审计对象:`src/memedogV2/`(分支 `feat/memedogV2-gmgn-pipeline`,30 commits vs main)
> 范围:harness 生产路径 + 确定性层。**本报告只审计,不修改代码。**
> 方法:真实环境实跑(零 mock)+ 逐文件源码审阅。

---

## 0. 真实环境运行证据(本次实跑,无任何 mock)

**A. 用户给定的真实新币** `2kDX…bonk`(symbol `Immpo` / "ISS PETRI MUTANT ORB",13 holders,supply 1012):

- **第 1 次 `python -m memedogV2 <CA> <LP> deepseek`:进程崩溃** —— `DataSourceError: gmgn-cli token security ... Client network socket disconnected before secure TLS connection`。瞬时网络抖动,但**整个 run 直接抛异常退出**(见发现 C-1)。
- **第 2 次(网络恢复后):正常产出 run 记录** ——
  - `read_security` OK(真实 gmgn-cli,2103ms,已记录 ToolCallRecord)
  - `read_info` OK(真实 gmgn-cli,4351ms,已记录)
  - `hardfilter` → **dropped: `authority: LP not burned/locked`**(该币 `burn_status="none"` 且 LP 未锁,正确命中红线)
  - `build_evidence / bull / bear / judge / signal` → 全部 `skipped`
  - `final_signal: null`;run 记录写入 `runs/memedogV2/20260625T082254Z-51044179-2kDX2fm3.json`(2509 bytes)
  - **结论:此币在确定性层就被正确淘汰,不进入 LLM 审计**(与 BONK 一致)。后端选 deepseek/codex 对结果无影响,因为在模型步之前就 drop。

**B. 真实环境测试套件** `pytest tests/memedogV2/live -m live`(5 项,39.84s,全绿):
- `test_live_gmgn` —— 真实 gmgn-cli security+info,字段与记录正确 ✓
- `test_live_deepseek` —— 真实 DeepSeek 裁决,返回合法结构(`schema_valid=True`)✓
- `test_live_codex` —— 真实 Codex 裁决,返回合法结构 ✓
- `test_live_pipeline[deepseek|codex]` —— 真实 gmgn + 全链路 ✓

**真实审计路径此前也已验证**(BONK):DeepSeek/Codex 能基于真实 gmgn 证据产出有理有据的 BEARISH 信号。

---

## 1. 总体评价

架构干净、分层清晰、可观测性扎实(每次运行落 `runs/*.json`,含工具调用与模型调用证据),确定性取数 + LLM 只做结构化推理的设计正确地解决了"DeepSeek 能否用"和"如何证明真调了 gmgn"两个问题。**生产 deepseek 路径在安全性与确定性上明显优于 codex 路径。**

但**真实环境实跑当场暴露了一个 Critical 缺陷**(网络错误使整条流水线崩溃),以及测试策略与"每个测试都用真实环境"的要求存在结构性落差。详见下。

---

## 2. 发现(按严重度)

### 🔴 Critical

**C-1. `runner.run()` 在 gmgn `DataSourceError` 上崩溃,违反"永不抛"契约**
`src/memedogV2/harness/runner.py:36-54`
两个取数阶段的 `try/except` **只捕获 `RateLimitBanned`,没有捕获 `DataSourceError`**。而 `DataSourceError` 正是 gmgn-cli 最常见的真实失败(网络/TLS 抖动、解析失败、rc≠0)。本次第 1 次实跑就因此**整个 `run()` 抛异常退出**,没有 run 记录、没有降级。
- 连带:`HarnessRunner` 接收的 `on_failure: drop|pass_flagged` 配置在 harness 路径里**形同虚设** —— 取数发生在 `HardFilter` 之前的 `tool_registry`,而 `HardFilter` 拿到的是已抓好的 `_FactsCli`,永远不会触发它自己的 `on_failure` 分支。所以瞬时取数失败既不重试、也无策略、直接崩。
- 为何单测没抓到:所有单测用 `FixtureToolSource`,它永不抛 `DataSourceError`;`test_workflow_runner` 只测了 `RateLimitBanned`。**这正是"必须真实环境测试"的价值所在。**

### 🟠 High

**H-1. 瞬时网络错误无任何重试/韧性**
`src/memedogV2/clients/gmgn_cli.py:69-71`
`GmgnCli` 对 429 故意不重试是对的(避免延长封禁),但**瞬时 TLS/socket 断开不是 429**,一次有界重试就能救。本次实跑"第 1 次崩、第 2 次成"正是教科书案例。当前实现对这类错误既不重试也不降级。

**H-2. 测试绝大多数是 mock/夹具,不满足"每个测试都用真实环境"**
- 21 个测试文件里只有 `tests/memedogV2/live/`(5 项)真打真实服务,且默认 `-m 'not live'` **被排除**;其余 ~50 个全部基于 `FixtureToolSource`/`FakeBackend`/冻结的 `fixtures/*.json`。
- 冻结夹具是**真实快照**(好),但**字段漂移**(设计文档自列的风险 #3)只有 live 测试能发现,而 live 默认不跑。
- **没有任何自动化测试覆盖"全链路走到一个真实 signal"**:`test_live_pipeline` 用 USDC,而 USDC 在 hardfilter 就 drop(买卖比 <1),永远到不了模型步。也就是说**"过闸→真实 bull/bear/judge→signal"这条最关键的真实路径,没有任何自动化测试守护**,只有人工实跑验证过(BONK)。

### 🟡 Medium

**M-1. DeepSeek 的 `_schema_valid` 是浅校验,`schema_valid=True` 可能误导**
`src/memedogV2/harness/model_registry.py:11-14`
只检查"required 键是否存在",不校验类型/枚举。一个 `{"signal":"STRONG_BUY","confidence":"high",...}` 会被判 `schema_valid=True` 并记进 `ModelCallRecord`,实际非法 —— 真正的拦截发生在更后面的 `runner._build_signal()`(返回 None)。即**运行记录里的 `schema_valid` 不完全可信**。建议用 `jsonschema` 真校验,或在 record 里区分"键齐全"与"类型合法"。

**M-2. DeepSeek 每次调用新建 `AsyncOpenAI` 客户端**
`model_registry.py:47-49` —— 每个 run 3 次(bull/bear/judge)各建一个连接池,轻微浪费。`__init__` 或 memoize 一次即可。

**M-3. `intake.py`(`AddressIntake`)在 V2 生产路径里是死代码**
`grep` 确认 `harness/` 与 `__main__.py` 均不引用它;`_seen` 还会无界增长。要么接进入口、要么删除,别留着误导。

**M-4. 没有自动化测试覆盖"模型后端被 runner 真实调用并产出 signal"**(同 H-2 后半):建议加一个 `live` 测试,用一个**会过闸**的真实币(或临时放宽阈值的夹具→真实模型)跑通到 signal。

### 🔵 Low / 安全

**S-1. CodexBackend 以 `--dangerously-bypass-approvals-and-sandbox` 运行 —— 审计 agent 无沙箱、可执行任意主机命令**
`src/memedogV2/llm/codex_agent.py:29`
缓解因素(且是设计亮点):`evidence_builder` 只抽**数值字段**(`smart_wallets` 等),**不含币名/简介等攻击者可控的自由文本**,所以喂给 codex 的 judge prompt 几乎没有 prompt-injection 面。但 codex 后端仍是全主机权限;**deepseek 后端不执行任何工具,更安全**。建议:生产默认 deepseek;codex 仅在受控评测用,并在文档里写明其权限风险。

**L-1.** `tool_registry` 的 `output_summary` 在 200 字符处硬截断,可能切断多字节字符(仅影响记录可读性)。
**L-2.** run 记录含链上 token 数据但**不含任何密钥**(已确认);gmgn key 在 `~/.config/gmgn/.env`、DeepSeek key 走 `os.environ`,均不入记录。✓

---

## 3. 亮点(值得保留)

- **可观测性**:`HarnessRun` + `ToolCallRecord` + `ModelCallRecord` + `runs/*.json`,真实跑出的记录完整可审计(已在用户币上验证)。
- **确定性取数 + 数值化证据**:既消除了"模型是否真调 gmgn"的不确定性,又把 prompt-injection 面压到极低。
- **后端可换且都已实跑验证**:DeepSeek(json_object+一次修复重试)与 Codex(strict schema)同接口,真实环境均产出合法结构。
- **429 处理正确**:撞封禁不重试,`RateLimitBanned` 带 `reset_at` 上抛。
- **runner 对模型/裁决错误已做"永不抛"**(上一轮评审 C1 已修)—— 唯独漏了取数阶段的 `DataSourceError`(本报告 C-1)。

---

## 4. 修复优先级建议(供参考,本次未改)

1. **C-1(必修)**:取数两阶段把 `except RateLimitBanned` 扩成也捕获 `DataSourceError`/`Exception` → 记 FAILED 步 + 落 run 记录 + 返回(不崩)。同时让 `on_failure` 策略真正作用于取数失败。
2. **H-1**:`GmgnCli` 对**非 429** 的瞬时错误加一次有界重试(指数退避、小上限),429 维持不重试。
3. **H-2 / M-4**:加一个**会过闸的真实币**的 `live` 全链路测试,守护"到 signal"这条路径;并在 CI/文档明确 live 套件的运行约定。
4. **M-1**:`_schema_valid` 升级为真 JSON-Schema 校验,或在记录里分离"键齐全/类型合法"。
5. **M-3**:决定 `intake.py` 去留。
6. **S-1**:文档化 codex 后端的无沙箱风险,生产默认 deepseek。

---

## 5. 一句话结论

**生产 deepseek 路径的设计是可信的,确定性与可观测性到位,真实环境基本跑通**;但**真实环境实跑当场抓出一个会让整条流水线崩溃的网络容错缺陷(C-1)**,且**测试体系仍以 mock 为主、不符合"每个测试都真实环境"的目标**。先修 C-1 + H-1,再补"会过闸真实币"的全链路 live 测试,这套系统才能算"真实场景下稳"。
