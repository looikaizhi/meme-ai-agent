# 模块 05:LLMJudge(双视角辩论 + 裁决)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。

**Goal:** 把 `TokenSnapshot + Score` 交给 LLM,内部跑 Bull / Bear 双视角,再由裁决者综合双方与量化分,输出结构化 `Signal`(BULLISH/BEARISH/NEUTRAL + confidence + 理由)。

**Architecture:** 两层。底层是 **provider 无关的 `LLMProvider` 抽象**,有两个实现:
1. **`CodexCLIProvider`(本实验默认)** —— 把 OpenAI Codex CLI 当作无交互子进程调用,用 ChatGPT Plus 订阅额度而非按量 API 计费。
2. **`LiteLLMProvider`(备选)** —— 通过 LiteLLM 走标准 API,可切 Claude/OpenAI/DeepSeek 做对比。
上层是 `LLMJudge` 业务:Bull 与 Bear 两次并行调用 + 一次裁决调用。结构化输出统一走"要求 JSON → pydantic 校验 → 失败修复重试一次",规避各家差异。

**Tech Stack:** asyncio.subprocess(调 codex)、LiteLLM(备选)、pydantic。

---

## 为什么 provider 无关 + 为什么用 Codex CLI

- 业务代码只依赖 `LLMProvider` 接口,**不直接 import 任何厂商 SDK**,可随时换后端做对比。
- 本实验后端选 **Codex CLI 子进程**:用户有 ChatGPT Plus,`codex exec` 无交互模式可把 codex 当成"输入 prompt → 输出文本"的 LLM,**走订阅额度,零按量费用**。
- 模型路由用前缀约定决定走哪个实现:
  - `codex:<model>` → `CodexCLIProvider`(`<model>` 可为 `default` 表示用 codex 默认模型)
  - `litellm:<provider>/<model>` → `LiteLLMProvider`(如 `litellm:openai/gpt-4o`、`litellm:anthropic/claude-opus-4-8`)
- 各角色(bull/bear/judge)可分别指定。

## Codex CLI 无交互调用要点(来源:developers.openai.com/codex/noninteractive)

- `codex exec "<prompt>"`:单次跑到完成,无 TUI,最终消息打到 stdout。
- `--output-last-message <file>`:把**最终回答**写入文件(最稳的取值方式,避免解析事件流)。
- `--output-schema <file.json>`:强制最终输出符合给定 JSON Schema —— 裁决调用可用它直接拿合法 JSON。
- `--model <m>`:选模型;省略则用 codex 默认。
- `--sandbox read-only` + `--ask-for-approval never`:**禁止改文件、禁止交互审批**(我们只要它推理,绝不让它碰仓库)。
- `--skip-git-repo-check`:允许在任意目录运行。
- 前置:用户需先 `npm i -g @openai/codex` 并 `codex login`(用 ChatGPT 账户,一次性交互)。**代码不负责登录。**

## 文件结构

```
src/memedog/llm/provider.py          # LLMProvider 协议 + 路由工厂 make_provider()
src/memedog/llm/codex_provider.py    # CodexCLIProvider(子进程)
src/memedog/llm/litellm_provider.py  # LiteLLMProvider(备选)
src/memedog/llm/structured.py        # JSON 提取 + pydantic 校验 + 修复重试
src/memedog/llmjudge/prompts.py      # bull / bear / judge 三套 prompt 模板
src/memedog/llmjudge/judge.py        # LLMJudge 编排
tests/llm/test_provider.py
tests/llm/test_codex_provider.py
tests/llm/test_structured.py
tests/llmjudge/test_prompts.py
tests/llmjudge/test_judge.py
```

## LLMProvider 接口与路由

```python
class LLMMessage(TypedDict):
    role: str            # "system" | "user" | "assistant"
    content: str

class LLMProvider(Protocol):
    async def complete(self, *, model: str, messages: list[LLMMessage],
                       temperature: float = 0.3, max_tokens: int = 1024) -> str: ...

def make_provider(model_str: str) -> tuple[LLMProvider, str]:
    """按前缀路由,返回 (provider 实例, 传给 provider 的真实 model 串)。
    'codex:gpt-5-codex'        -> (CodexCLIProvider(), 'gpt-5-codex')
    'codex:default'            -> (CodexCLIProvider(), '')          # 省略 --model
    'litellm:openai/gpt-4o'    -> (LiteLLMProvider(),  'openai/gpt-4o')
    """
```

### CodexCLIProvider(核心)

```python
class CodexCLIProvider:
    def __init__(self, codex_bin="codex", timeout=120, sandbox="read-only"):
        ...

    async def complete(self, *, model, messages, temperature=0.3, max_tokens=1024) -> str:
        prompt = self._flatten(messages)          # system+user 拼成单 prompt
        out_path = <临时文件>
        cmd = [self.codex_bin, "exec",
               "--sandbox", self.sandbox,
               "--ask-for-approval", "never",
               "--skip-git-repo-check",
               "--output-last-message", out_path]
        if model:
            cmd += ["--model", model]
        cmd += [prompt]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), self.timeout)
        if proc.returncode != 0:
            raise LLMProviderError(f"codex exit {proc.returncode}: {stderr.decode()[:500]}")
        return Path(out_path).read_text(encoding="utf-8").strip()
```

> 注:`temperature` / `max_tokens` 在 codex CLI 无直接对应,`CodexCLIProvider` 接受但忽略(或经 `-c` 透传),在 docstring 注明。测试用 monkeypatch 替换 `asyncio.create_subprocess_exec`,**不真实调用 codex**。

## 配置(.env / thresholds.yaml -> llmjudge 段)

```yaml
llmjudge:
  models:
    bull:  "codex:default"      # 本实验:全部走 codex 子进程(ChatGPT Plus)
    bear:  "codex:default"
    judge: "codex:default"
  temperature: { bull: 0.5, bear: 0.5, judge: 0.2 }
  max_tokens: 1024
  repair_retries: 1
  codex:
    bin: "codex"
    timeout_sec: 120
    sandbox: "read-only"
# 切到标准 API 对比时,改成如 "litellm:openai/gpt-4o";.env 配相应 *_API_KEY
```

## 任务

### Task 1: LLMProvider 协议 + 路由工厂

**Files:** Create `src/memedog/llm/provider.py`; Test `tests/llm/test_provider.py`

- [ ] **Step 1: 写失败测试**

```python
from memedog.llm.provider import make_provider
from memedog.llm.codex_provider import CodexCLIProvider

def test_route_codex_prefix():
    p, model = make_provider("codex:gpt-5-codex")
    assert isinstance(p, CodexCLIProvider) and model == "gpt-5-codex"

def test_route_codex_default_blank_model():
    p, model = make_provider("codex:default")
    assert model == ""

def test_route_litellm_prefix():
    p, model = make_provider("litellm:openai/gpt-4o")
    assert model == "openai/gpt-4o"
```

- [ ] **Step 2: 跑测试确认失败** — `pytest tests/llm/test_provider.py -v` → FAIL
- [ ] **Step 3: 实现** `LLMMessage`、`LLMProvider` Protocol、`LLMProviderError`、`make_provider()`、测试用 `FakeProvider`(满足协议,返回预设文本)。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(llm): provider protocol + routing factory"`

### Task 2: CodexCLIProvider(子进程)

**Files:** Create `src/memedog/llm/codex_provider.py`; Test `tests/llm/test_codex_provider.py`

- [ ] **Step 1: 写失败测试**(monkeypatch `asyncio.create_subprocess_exec`,模拟 codex 写出 last-message 文件)

```python
async def test_codex_complete_reads_last_message(monkeypatch, tmp_path):
    async def fake_exec(*cmd, **kw):
        # 找到 --output-last-message 后一个参数,写入预设回答
        out = cmd[cmd.index("--output-last-message") + 1]
        Path(out).write_text('{"signal":"BULLISH"}', encoding="utf-8")
        class P:
            returncode = 0
            async def communicate(self): return (b"", b"")
        return P()
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    p = CodexCLIProvider()
    text = await p.complete(model="", messages=[{"role":"user","content":"hi"}])
    assert "BULLISH" in text

async def test_codex_nonzero_exit_raises(monkeypatch):
    async def fake_exec(*cmd, **kw):
        class P:
            returncode = 1
            async def communicate(self): return (b"", b"boom")
        return P()
    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    with pytest.raises(LLMProviderError):
        await CodexCLIProvider().complete(model="", messages=[{"role":"user","content":"x"}])
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现 `CodexCLIProvider`** 如上接口:`_flatten(messages)` 把 role+content 拼成单 prompt;用临时文件接 `--output-last-message`;`asyncio.wait_for` 加超时;非零退出抛 `LLMProviderError`;`finally` 清理临时文件。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(llm): codex CLI subprocess provider"`

### Task 3: LiteLLMProvider(备选)

**Files:** Create `src/memedog/llm/litellm_provider.py`; Test `tests/llm/test_provider.py`(追加)

- [ ] **Step 1: 写失败测试** — monkeypatch `litellm.acompletion` 返回固定对象,断言 `complete()` 取出文本。
- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现** `LiteLLMProvider.complete()`:`await litellm.acompletion(model, messages, temperature, max_tokens)` → 取 `choices[0].message.content`。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(llm): litellm provider (alt backend)"`

### Task 4: 结构化输出(JSON 提取 + 校验 + 修复)

**Files:** Create `src/memedog/llm/structured.py`; Test `tests/llm/test_structured.py`

- [ ] **Step 1: 写失败测试**

```python
from memedog.llm.structured import parse_json_into, StructuredParseError
from memedog.llmjudge.judge import JudgeOut

def test_parse_clean_json():
    out = parse_json_into('{"signal":"BULLISH","confidence":0.8,"bull_points":[],"bear_points":[],"red_flags":[],"rationale":"x"}', JudgeOut)
    assert out.signal == "BULLISH"

def test_parse_strips_codefence_and_prose():
    raw = 'Here:\n```json\n{"signal":"BEARISH","confidence":0.4,"bull_points":[],"bear_points":[],"red_flags":[],"rationale":"y"}\n```'
    assert parse_json_into(raw, JudgeOut).signal == "BEARISH"

def test_parse_invalid_raises():
    with pytest.raises(StructuredParseError):
        parse_json_into("not json", JudgeOut)
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现** — `parse_json_into(text, model_cls)`:正则剥离 ```围栏、截取首个 `{...}` → `json.loads` → `model_cls.model_validate`;失败抛 `StructuredParseError`。`complete_structured(provider, model, messages, model_cls, retries)`:解析失败时追加"上次输出不是合法 JSON,请仅输出符合要求的 JSON"消息重试。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(llm): robust structured output"`

### Task 5: Prompt 模板 + JudgeOut

**Files:** Create `src/memedog/llmjudge/prompts.py`(`JudgeOut` 放 `judge.py`); Test `tests/llmjudge/test_prompts.py`

- [ ] **Step 1: 写失败测试** — 断言渲染后的 prompt 含 symbol、各维度数值、缺失维度提示文字。
- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现三套模板 + `JudgeOut` pydantic**
  - `JudgeOut`: `signal:str, confidence:float, bull_points:list[str], bear_points:list[str], red_flags:list[str], rationale:str`。
  - `bull_prompt/bear_prompt(snapshot, score)` 与 `judge_prompt(snapshot, score, bull, bear)`;judge 模板明确要求"仅输出 JSON,字段为 JudgeOut 所列"。
  - 模板显式注入"缺失维度"提示(读 `available=False`)。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(llmjudge): prompts + JudgeOut schema"`

### Task 6: LLMJudge 编排

**Files:** Create `src/memedog/llmjudge/judge.py`; Test `tests/llmjudge/test_judge.py`

- [ ] **Step 1: 写失败测试**(用 `FakeProvider` 预设 bull/bear/judge 三段输出;judge 段返回合法 JudgeOut JSON)

```python
async def test_judge_returns_signal(snapshot, score, fake_provider, cfg):
    judge = LLMJudge(provider=fake_provider, cfg=cfg)
    sig = await judge.judge(snapshot, score)
    assert sig.signal in ("BULLISH","BEARISH","NEUTRAL")
    assert 0 <= sig.confidence <= 1
    assert sig.mint == snapshot.candidate.mint

async def test_judge_degrades_to_rule_signal_on_llm_error(snapshot, score, failing_provider, cfg):
    sig = await LLMJudge(provider=failing_provider, cfg=cfg).judge(snapshot, score)
    assert sig.signal in ("BULLISH","BEARISH","NEUTRAL")
    assert "降级" in sig.rationale
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现 `judge(snapshot, score)`**
  - 用 `make_provider` 解析 bull/bear/judge 三个模型串(允许同一 provider 不同 model)。
  - 并行调 bull、bear(`asyncio.gather`)→ 两段要点文本。
  - judge:`complete_structured(...)` 解析成 `JudgeOut` → 组装 `Signal`(填 mint/symbol/score_total/trace_id/created_at)。
  - 任一调用异常 → 退化为规则信号(score≥70 BULLISH、≤40 BEARISH、否则 NEUTRAL),`rationale` 注明"LLM 不可用,降级为规则信号"。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(llmjudge): bull/bear debate + verdict + degradation"`

## 降级与边界
- LLM 全部异常/超时:见 Task 6 规则信号兜底,保证流水线永不因 LLM 崩。
- 成本:codex 走订阅额度;bull/bear/judge 都可指向 `codex:default`;只有过闸候选到这一步(漏斗保证)。
- 可对比性:把 `llmjudge.models` 改成 `litellm:...` 即切标准 API,跑同一批快照对比信号差异。
- **codex 串行性**:codex 子进程较重,bull/bear 并行调两个 codex 进程即可;如遇本机并发限制,可在 config 加信号量(后续优化)。
