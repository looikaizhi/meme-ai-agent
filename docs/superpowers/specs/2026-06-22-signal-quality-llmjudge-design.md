# 设计:信号质量深化 — LLMJudge 多步推理 workflow(子项目 A)

- **日期**:2026-06-22
- **分支**:`feature/signal-quality-llmjudge`
- **状态**:已获用户批准(设计阶段),待写实现计划
- **范围归属**:第二阶段三段拆分(A 信号质量 → B 健壮性 → C 实时服务器)中的 **A**

## 背景与动机

MemeDog Radar 的流水线已可运行(`python -m memedog` 跑 orchestrator 循环 + 价格监控,Streamlit 看板读 SQLite)。第二阶段是在能用的基座上做深化。本 spec 只覆盖**子项目 A:信号质量深化**。

关键问题诊断:**当前 LLM 看不见原始数据。** [prompts.py](../../../src/memedog/llmjudge/prompts.py) 只把每个维度的*打分结果*(`raw` / `weight` / `weighted` 三个数字)喂给 Bull/Bear/Judge,并未把真正的链上原始值(流动性 $、top10%、5min 量、买卖比、holder 数……)给它。LLM 在对抽象分数空谈,而非对具体证据辩论。这是信号质量最大的提升空间。

用户明确方向:**算法深度交给 LLM 判断**,把 judge 的 prompt 设计成"带 workflow 的多步推理模板",规则层(ScoreEngine)保持轻量当预筛分,重投入放在 LLM 这一层。

## 范围边界

**只动 LLMJudge 层**:
- `src/memedog/llmjudge/prompts.py`
- `src/memedog/llmjudge/judge.py`
- 相关测试 + codex fixtures

**明确不动**(留给后续子项目或保持现状):
- `ScoreEngine` / `scoring/*`(保持轻量预筛分)
- `HardFilter` / `hardfilter/*`(红线规则不变)
- `clients/*`、`enricher/*`(不接新数据源;Twitter/聪明钱按用户决定跳过)
- `models/signal.py`、`store.py`(Signal/Store schema 不变 —— 结构化分步落库与看板展示留给子项目 C 可观测性)

## 架构选择(已与用户确认)

1. **保留三次调用的真辩论**:Bull(1 次)+ Bear(1 次)并发 → Judge(1 次)。每 token 仍 3 次 codex 调用。保留两个独立对抗视角(CLAUDE.md 已选定"内嵌辩论"),不收缩成单次调用,不引入 agent 多轮工具循环。
2. **多步推理 = prompt 模板**:workflow 体现在 judge 的 prompt 指令里,LLM 按固定步骤推理后输出 JSON,而非真正的多轮 tool-calling agent。

## 组件设计

### ① 证据块:`_snapshot_evidence(snapshot, score)` (prompts.py 新增 helper)

把 `TokenSnapshot` 的原始链上值渲染成结构化、带来源标注的证据块,三个 prompt 共用。示例输出:

```
SAFETY (RugCheck):    mint撤权=True  freeze撤权=True  LP烧/锁=True  trust=78/100  risk=LOW
HOLDERS (Helius):     top10=24.5%  最大钱包=6.2%  dev=3.1%  持币人=412  sniper=8.0%
MOMENTUM (DexScreen): 流动性=$42,300  5min量=$18,400  1h量=$96,200  买卖比=1.80  独立买家=210  FDV/流=3.2
SOCIAL:               DATA MISSING (数据缺失)
[规则预筛分(参考): 总分 68.4/100 | safety 78 holders 71 momentum 62 social –]
```

规则:
- 每个维度一行,列出该维度 `*Info` 模型里所有非 None 的原始字段(字段→值)。
- 维度 `available=False` 或全字段 None → 整行渲染 `DATA MISSING (数据缺失)`。
- 单个字段为 None → 该字段省略(不渲染 `None`)。
- 末行附上规则预筛分(composite + 各维度 raw)作为**参考**,明确标注是规则引擎的预估,非最终结论。
- 数值格式:金额 `$` 千分位;百分比保留 1 位小数;比率保留 2 位小数。格式化失败不得抛错(降级为原值字符串)。

### ② Bull / Bear prompt 升级

- 两个独立对抗视角保留;system prompt 各自维持 bull-advocate / bear-risk-officer 角色。
- user prompt 改为携带**完整证据块**(替代原来只给维度分数)。
- 新增硬约束:**每个论点必须引用证据块里的具体字段/数字**;`DATA MISSING` 维度视为"不确定性升高",不得编造数据,也不得当作利好或利空。

### ③ Judge prompt:显式 6 步 workflow

judge 的 user prompt 在给出证据块 + Bull/Bear 论点后,要求 LLM **按固定顺序**逐步推理,再输出 JSON:

1. **安全门(safety)** — 审查安全证据;有无硬红线(mint/freeze 权限未撤、LP 未烧/锁、CRITICAL/HIGH 风险)。
2. **集中度(concentration)** — top10 / 最大钱包 / dev / sniper 是否健康。
3. **动量(momentum)** — 流动性下限、量趋势(5min vs 1h)、买压(买卖比)、FDV/流动性合理性。
4. **社交/聪明钱(social)** — 有数据则权衡,无则记不确定。
5. **辩论权衡(debate)** — 哪些 Bull/Bear 论点有数据支撑、哪些是猜测。
6. **裁决** — 映射 BULLISH/BEARISH/NEUTRAL + 校准置信度;关键维度缺失时显式下调置信度。

### ④ JudgeOut 增加可审计分步结论(向后兼容)

```python
class StepFinding(BaseModel):
    step: str        # "safety" | "concentration" | "momentum" | "social" | "debate"
    assessment: str  # "pass" | "concern" | "fail" | "neutral" | "missing"
    note: str

class JudgeOut(BaseModel):
    signal: str
    confidence: float
    bull_points: list[str]
    bear_points: list[str]
    red_flags: list[str]
    rationale: str
    workflow: list[StepFinding] = []   # 新增,默认 [] → 解析向后兼容
```

- `workflow` 默认 `[]`:旧 fixture / LLM 偶尔漏字段时,`complete_structured` 仍能解析成功,降级路径不受影响。
- 判决时把 `workflow` 折叠成一段分步小结写入现有 `Signal.rationale`(例:`安全:pass; 集中度:concern(top10偏高); 动量:pass; ...`)。**不改 Signal / Store schema** —— 结构化逐步落库与看板展示是子项目 C 的事。

### ⑤ 置信度校准护栏(可配置)

在 LLM 给出的 `confidence` 之上加一道确定性护栏:

```
completeness = (可用维度数 / 4)
confidence = min(llm_confidence, floor + (1 - floor) * completeness)
```

- `completeness` 的"可用维度数"= `snapshot.{safety,holders,momentum,social}.available` 为 True 的个数(0~4)。
- `floor` 与是否启用写入 config(`llmjudge` 段),不硬编码。缺省 `floor = 0.5`,即四维全缺时置信度上限 0.5,四维全有时上限 1.0。
- 缺失维度越多 → 上限越低,避免数据稀薄时给出高置信信号。
- 该护栏只在成功路径生效;降级路径仍用 `_degrade_signal` 既有逻辑。

## 数据流

```
snapshot + score
  → _snapshot_evidence() 渲染原始数据证据块
  → bull_prompt / bear_prompt(证据块 + 对抗指令)
  → bull.complete ‖ bear.complete(并发)
  → judge_prompt(证据块 + bull/bear 论点 + 6 步 workflow 指令)
  → complete_structured(JudgeOut, 含 workflow, 一次修复重试)
  → 映射 Signal:rationale = 分步小结;confidence = min(llm, 完备度护栏)
  → Signal
```

## 错误处理(不变 + 强化)

- 任何 LLM/解析失败 → 既有 `_degrade_signal(score.total)` 规则降级,`rationale` 标注 `降级(degraded)`。
- `workflow` 默认 `[]` 保证结构解析稳健;`complete_structured` 一次修复重试逻辑不变。
- 证据块渲染对单字段 None / 格式化异常必须容错,绝不让 prompt 构建抛错。

## 测试策略(真实调用,非 mock 假设)

延续项目既有"真实数据驱动 + 降级测试"约定。离线层用真实捕获的 fixture 重放,不编造 API body;live 层打真实 codex。

**离线层(默认运行,零联网):**
- 证据块单测:断言含具体原始值(`$42,300`、`top10`、`24.5%`),缺失维度渲染 `DATA MISSING`,单字段 None 不渲染 `None`。
- bull/bear prompt 测试:断言证据块注入、对抗指令存在。
- judge prompt 测试:断言 6 个 workflow 步骤名出现在指令中,JSON 输出格式说明含 `workflow` 字段。
- JudgeOut 解析测试:用扩展后的真实 codex fixture(`judge_bullish.json` / `judge_bearish.json` 增加真实 `workflow` 数组)验证解析;另测一个**不含** `workflow` 的旧 body 仍解析成功(向后兼容)。
- 置信度护栏单测:构造缺 1/2/3 维度的 snapshot,断言 confidence 被正确上限封顶;config 关闭护栏时不封顶。
- 分步小结映射测试:断言 `Signal.rationale` 含分步摘要。
- 降级路径测试:LLM 抛错 → 规则信号,行为不变。

**live 层(`-m live`,需 codex,自跳过):**
- 既有 `test_live_codex` / e2e:确认升级后的 prompt 真实跑通 codex,返回可解析的含 workflow 的 JudgeOut。

**fixture 重新捕获:**
- 用 `scripts/capture_fixtures.py` 以新 judge prompt 真实跑一次 codex,捕获含 `workflow` 的真实输出覆盖旧 fixture(不手写编造)。

## 验收标准

1. Bull/Bear/Judge 三个 prompt 都携带原始数据证据块(可在测试中断言具体数值)。
2. Judge prompt 含明确的 6 步 workflow 指令。
3. `JudgeOut.workflow` 可解析且向后兼容(缺字段不报错)。
4. 成功路径置信度受完备度护栏约束;阈值可配置。
5. `Signal.rationale` 含分步小结。
6. 降级路径行为不变。
7. 默认测试套件全过且零外部联网;live 层真实打 codex 通过。
8. ScoreEngine / HardFilter / clients / models / store 未被改动。

## 非目标(明确排除)

- 不改 ScoreEngine 启发式或 HardFilter 红线(那是可选的 B 范围)。
- 不接 Twitter / 聪明钱新数据源。
- 不改 Signal / Store schema,不做结构化分步落库或看板展示(子项目 C)。
- 不引入 agent 式多轮 tool-calling。
