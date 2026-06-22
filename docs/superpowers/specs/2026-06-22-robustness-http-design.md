# 设计:健壮性 — 智能重试 + 限流 + 密钥不入日志(子项目 B)

- **日期**:2026-06-22
- **分支**:`feature/robustness-http`
- **状态**:已获用户批准(设计阶段),待写实现计划
- **范围归属**:第二阶段三段拆分(A 信号质量 ✅ → **B 健壮性** → C 实时服务器)中的 **B**

## 背景与动机

子项目 A 已合入 main。B 的目标是**为后续本地实时服务器(C)打稳基础**:长跑数小时不崩、不因 429 被数据源封、不把 API 密钥写进日志。

现状缺口(读 `clients/base.py` 得出):
- 重试对**所有非 2xx 都重试**(404 不该重试浪费配额;429 没读 `Retry-After`);退避无 jitter,并发重试会踩踏。
- **无限流**:Scanner 每轮打 DexScreener、Enricher 每个候选打 RugCheck/Helius,免费档严格限流,易触发 429。
- **日志泄密**:非 2xx 时打印完整 URL,Helius 把 `api-key` 放在 URL 里 → 密钥进日志(此前 Telegram bot token 泄漏即同类问题)。

用户确认的 B 范围(多选结果):**智能重试 + 限流**、**密钥不入日志**。
明确**不在 B**(往后放):codex 熔断、缓存 + 配额耗尽降级。

## 范围边界

**要动**:
- `src/memedog/clients/base.py` — 智能重试 + 接入限流
- `src/memedog/clients/ratelimit.py`(新)— `AsyncRateLimiter`
- `src/memedog/observability/__init__.py` + `redaction.py`(新)— 日志脱敏过滤器
- `src/memedog/config/settings.py` + `config/thresholds.yaml` — 新 `http` 配置段
- `src/memedog/app_factory.py` — 按数据源把 http 配置穿进各 client
- `src/memedog/__main__.py`、`dashboard/app.py` — 启动时装脱敏过滤器
- 相关测试

**不动**:
- LLMJudge / codex(熔断不在 B)
- ScoreEngine / HardFilter / Enricher 业务逻辑(Enricher 已有"单源失败降级"逻辑,B 不改其语义)
- Store / models / 数据契约

## 组件设计

### ① 智能重试(`BaseHTTPClient._request`)

错误分类:
- **可重试**:`httpx.HTTPError`(含超时/连接错误)、HTTP 状态码 ∈ `{429, 500, 502, 503, 504}`。
- **不可重试**:其他非 2xx(尤其 `400/401/403/404`)→ 立即 `raise DataSourceError`,不再重试。
- 可重试状态码集合写入 config(`http` 段),不硬编码。

退避与等待:
- 默认退避 **full jitter**:`delay = random.uniform(0, backoff_base * 2**attempt)`,封顶 `max_backoff_sec`。
- **`429`/`503` 且响应含 `Retry-After`**(整数秒):等待 `min(Retry-After, max_backoff_sec)`,覆盖 jitter 退避。
- 最后一次尝试后不再 sleep。

不变量:
- 仍统一抛 `DataSourceError`,保留 `__cause__` 链。
- `_request` 返回 `dict | list`,签名不变。

### ② 限流(`src/memedog/clients/ratelimit.py`)

```python
class AsyncRateLimiter:
    """并发上限 + 最小请求间隔。线程内 asyncio 安全。"""
    def __init__(self, max_concurrency: int, min_interval_sec: float) -> None: ...
    async def __aenter__(self) -> "AsyncRateLimiter": ...
    async def __aexit__(self, *exc) -> None: ...
```

语义:
- **并发上限**:内部 `asyncio.Semaphore(max_concurrency)`;进入时 acquire,退出时 release。
- **最小间隔**:用 `asyncio.Lock` + 单调钟 `loop.time()` 记录上次"放行时刻";若距上次不足 `min_interval_sec`,`await asyncio.sleep(差值)` 后再放行。`min_interval_sec=0` 时不限速。
- `max_concurrency <= 0` 视为无并发上限(退化为仅间隔限速);`min_interval_sec<=0` 视为不限速。

接入:
- `BaseHTTPClient.__init__` 增加可选参数 `rate_limiter: AsyncRateLimiter | None = None`。
- `_request` 中,实际发送 `self._client.request(...)` 用 `async with self._rate_limiter:` 包住(limiter 为 None 时直接发送)。限流计入每次"尝试",即重试也受限流约束。

### ③ 密钥不入日志(`src/memedog/observability/redaction.py`)

```python
class SecretRedactingFilter(logging.Filter):
    """扫描每条 LogRecord,把密钥模式与精确密钥值抹成 ***。"""
    def __init__(self, secrets: list[str] | None = None) -> None: ...
    def filter(self, record: logging.LogRecord) -> bool: ...  # 永远返回 True,只改写文本

def install_redaction(settings=None) -> SecretRedactingFilter: ...
```

脱敏内容:
- **模式**(正则):
  - `api-key=<token>` → `api-key=***`(Helius URL)
  - Telegram `bot<digits>:<token>` → `bot***`
  - `Authorization: Bearer <token>` / `Bearer <token>` → `Bearer ***`
- **精确值**:若传入 `settings`,收集非空的 `helius_api_key / rugcheck_api_key / twitter_bearer / openai_api_key / anthropic_api_key / deepseek_api_key / telegram_bot_token` 真实字符串,在消息里整串替换为 `***`(最稳,长度≥8 才纳入,避免误伤)。

实现要点:
- 在 `filter()` 里把 `record.getMessage()` 的结果脱敏:先用 `record.msg % record.args` 渲染成最终字符串,脱敏后赋回 `record.msg` 并清空 `record.args`,保证后续 handler 不会再用原始 args 还原出密钥。
- `filter()` 必须容错:任何异常都不能让日志系统崩(吞掉异常,返回 True)。
- `install_redaction()` 把过滤器加到 **root logger 及其所有 handler**,并对 `logging.basicConfig` 之后新增的 handler 也生效(加到 root logger 自身的 filters,同时遍历现有 handlers 各加一份)。

### ④ 配置(`http` 段)

`settings.py` 新增:
```python
class HTTPClientPolicy(BaseModel):
    timeout_sec: float = 10.0
    max_retries: int = 3
    backoff_base_sec: float = 0.2
    max_backoff_sec: float = 10.0
    max_concurrency: int = 4
    min_interval_sec: float = 0.0
    retry_status_codes: list[int] = [429, 500, 502, 503, 504]

class HTTPConfig(BaseModel):
    default: HTTPClientPolicy = HTTPClientPolicy()
    # override 以"部分字段 dict"形式保存,避免被填成 policy 默认值
    overrides: dict[str, dict] = {}
    def policy_for(self, source: str) -> HTTPClientPolicy:
        ov = self.overrides.get(source)
        return self.default.model_copy(update=ov) if ov else self.default
```

`Config` 增加 `http: HTTPConfig`;`load_config` 解析 `raw.get("http", {})`(缺省全默认,保证向后兼容)。

> 关键:`overrides` 存**原始 partial dict**(不预解析成 `HTTPClientPolicy`),`policy_for` 用 `default.model_copy(update=ov)` 做字段级合并 —— 只有 override 里显式给出的字段覆盖 default,其余严格沿用 default。`model_copy(update=...)` 不触发校验,故 yaml 里 override 字段类型须正确(由 default 段同名字段的类型隐含约束;测试覆盖)。

`thresholds.yaml` 新增:
```yaml
http:
  default:    { timeout_sec: 10, max_retries: 3, backoff_base_sec: 0.2, max_backoff_sec: 10, max_concurrency: 4, min_interval_sec: 0.0 }
  overrides:
    dexscreener: { max_concurrency: 2, min_interval_sec: 1.0 }
    rugcheck:    { min_interval_sec: 0.5 }
    helius:      { max_concurrency: 2, min_interval_sec: 0.2 }
```

> `policy_for` 按字段合并:override 里**显式给出的字段**覆盖 default,其余沿用 default。实现上 override 项以"部分字段"形式存在 yaml,合并时以 default 为底。

### ⑤ app_factory 穿线

`build_orchestrator(cfg, store)` 中,为每个 client 用 `cfg.http.policy_for("<source>")` 构造对应的 `AsyncRateLimiter` 与 BaseHTTPClient kwargs:
- `DexScreenerClient(timeout=..., max_retries=..., backoff_base=..., max_backoff=..., retry_status_codes=..., rate_limiter=AsyncRateLimiter(...))`
- RugCheck / Helius / Twitter 同理(source 名:`dexscreener / rugcheck / helius / twitter`)。
- 各 client 现有 `**kwargs` 透传即可,client 类本身基本不改(Helius/Twitter 仍各自 setdefault base_url)。

### ⑥ 启动装脱敏

- `__main__.main()`:`basicConfig` 之后调用 `install_redaction(cfg.settings)`。
- `dashboard/app.py main()`:加载 config 后调用 `install_redaction(cfg.settings)`(dashboard 也会打日志)。

## 数据流

```
client.get_json/post_json
  → BaseHTTPClient._request(method,url)
      for attempt in range(max_retries):
        async with rate_limiter:           # 并发上限 + 最小间隔
          resp = await httpx.request(...)
        if 2xx: return json
        if status not retryable: raise      # 4xx 立即失败
        compute wait (Retry-After 优先, 否则 full jitter), sleep
      raise DataSourceError
所有日志经 root logger → SecretRedactingFilter → 抹密钥 → handler 输出
```

## 错误处理 / 不变量

- 单数据源彻底失败仍抛 `DataSourceError`,上层(Enricher/Scanner)既有降级语义不变。
- 限流只增加延迟,不改变成功/失败结果。
- 脱敏过滤器异常被吞,绝不影响日志或主流程。
- 所有新配置有默认值,缺 `http` 段时行为等价于"无限流 + 旧重试为可重试集合"(注:重试语义会变严格——4xx 不再重试,这是有意改进,不视为破坏)。

## 测试策略(真实调用,非 mock 假设)

沿用项目"真实数据 fixture + respx 重放 + 离线默认"约定。

**离线层(默认):**
- 重试:respx 模拟 `429→200` 重试成功;`404` 立即 raise(断言只发 1 次请求);`500` 连续 → `DataSourceError`;`Retry-After: 2` 被遵守(monkeypatch `asyncio.sleep` 断言入参);网络错误(respx raise httpx error)被重试;jitter 用 monkeypatch `random.uniform` 决定化后断言退避时长。
- 限流:`AsyncRateLimiter(max_concurrency=2)` —— 启动 3 个并发任务,断言同时在跑的 ≤2;`min_interval_sec` —— 连续两次 acquire,断言第二次被 sleep 了≥间隔(monkeypatch `loop.time`/`asyncio.sleep` 决定化)。
- 脱敏:用 `caplog` 或自建 handler 捕获,断言含 `api-key=`/telegram token/精确密钥值的日志被抹成 `***`;断言 `record.args` 被清空后再次格式化不复现密钥;断言过滤器对畸形 record 不抛错。
- 配置:`HTTPConfig.policy_for("helius")` 字段级合并正确;缺 `http` 段时 `load_config` 仍成功且全默认。
- app_factory:构造出的 client 带正确 timeout/limiter(结构断言,不联网)。

**live 层(`-m live`,自跳过):**
- 不新增强制 live;已有 live 客户端测试在限流/重试改造后仍应通过(顺带验证真实端点不被新逻辑破坏)。

## 验收标准

1. 4xx(非 429)不再重试;429/503 遵守 `Retry-After`;退避带 jitter 且封顶。
2. 每个数据源受并发上限 + 最小间隔约束,阈值可配。
3. 日志中不出现任何 API key / bot token(模式 + 精确值双重脱敏)。
4. `http` 配置段可调,缺省向后兼容。
5. 默认测试套件全过且零外部联网;已有 live 测试仍通过。
6. LLMJudge/codex/Store/models 未被改动。

## 非目标(明确排除)

- codex 熔断 / 冷却(往后放)。
- 缓存 / 配额耗尽专门降级(往后放)。
- 改 Enricher/Scanner 的降级业务语义。
- 全局分布式限流(仅单进程 asyncio 内限流)。
