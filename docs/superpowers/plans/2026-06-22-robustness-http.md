# 健壮性(智能重试 + 限流 + 密钥脱敏)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让所有数据源 HTTP 调用具备错误分类重试、按数据源限流,并保证 API 密钥永不进日志,为长跑实时服务器打稳基础。

**Architecture:** 改造 `BaseHTTPClient`(智能重试 + 接入限流);新增 `AsyncRateLimiter`(并发上限 + 最小间隔)与全局 `SecretRedactingFilter`(模式 + 精确值脱敏);新增 `http` 配置段(default + 按数据源 override,字段级合并);app_factory 按数据源穿线,`__main__`/dashboard 启动时装脱敏过滤器。LLMJudge/codex/Store/models 不动。

**Tech Stack:** Python 3.11+,asyncio,httpx,respx(测试重放),pydantic v2,pytest。

参考 spec:[docs/superpowers/specs/2026-06-22-robustness-http-design.md](../specs/2026-06-22-robustness-http-design.md)

---

## 文件结构

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/memedog/clients/ratelimit.py` | 新建 | `AsyncRateLimiter`:并发上限 + 最小请求间隔 |
| `src/memedog/observability/__init__.py` | 新建 | 空包标记 |
| `src/memedog/observability/redaction.py` | 新建 | `SecretRedactingFilter` + `install_redaction()` |
| `src/memedog/config/settings.py` | 修改 | `HTTPClientPolicy` / `HTTPConfig` + `Config.http` + loader |
| `src/memedog/config/thresholds.yaml` | 修改 | `http` 段 |
| `src/memedog/clients/base.py` | 修改 | 智能重试(错误分类/Retry-After/jitter)+ 接入限流 |
| `src/memedog/app_factory.py` | 修改 | 按数据源构造 limiter + policy kwargs |
| `src/memedog/__main__.py` | 修改 | 启动装 `install_redaction` |
| `dashboard/app.py` | 修改 | 启动装 `install_redaction` |
| `tests/clients/test_ratelimit.py` | 新建 | 限流器测试 |
| `tests/observability/test_redaction.py` | 新建 | 脱敏测试 |
| `tests/clients/test_base.py` | 修改 | 智能重试新测试 + 更新 jitter 影响的旧测试 |
| `tests/config/test_config.py` | 修改 | http 配置测试 |

---

## Task 1: AsyncRateLimiter

**Files:**
- Create: `src/memedog/clients/ratelimit.py`
- Test: `tests/clients/test_ratelimit.py`

- [ ] **Step 1: Write the failing tests**

创建 `tests/clients/test_ratelimit.py`:

```python
"""Tests for AsyncRateLimiter (concurrency cap + min interval)."""
import asyncio
import time

import pytest

from memedog.clients.ratelimit import AsyncRateLimiter


async def test_concurrency_cap_limits_simultaneous_entries():
    limiter = AsyncRateLimiter(max_concurrency=2, min_interval_sec=0.0)
    concurrent = 0
    peak = 0

    async def worker():
        nonlocal concurrent, peak
        async with limiter:
            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0.05)
            concurrent -= 1

    await asyncio.gather(*(worker() for _ in range(6)))
    assert peak <= 2


async def test_min_interval_spaces_sequential_acquires():
    limiter = AsyncRateLimiter(max_concurrency=10, min_interval_sec=0.05)
    start = time.monotonic()
    for _ in range(3):
        async with limiter:
            pass
    elapsed = time.monotonic() - start
    # 3 acquires → at least 2 inter-acquire gaps of 0.05s
    assert elapsed >= 0.09


async def test_zero_settings_no_limit():
    limiter = AsyncRateLimiter(max_concurrency=0, min_interval_sec=0.0)
    # Should not block at all
    async with limiter:
        pass
    async with limiter:
        pass
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/clients/test_ratelimit.py -q`
Expected: FAIL — `ModuleNotFoundError: memedog.clients.ratelimit`

- [ ] **Step 3: Implement**

创建 `src/memedog/clients/ratelimit.py`:

```python
"""Async rate limiter: concurrency cap + minimum interval between request starts."""
from __future__ import annotations

import asyncio
from typing import Optional


class AsyncRateLimiter:
    """Limit concurrent entries and enforce a minimum interval between them.

    Parameters
    ----------
    max_concurrency:
        Max simultaneous holders. ``<= 0`` disables the concurrency cap.
    min_interval_sec:
        Minimum seconds between successive acquisitions. ``<= 0`` disables
        interval spacing.
    """

    def __init__(self, max_concurrency: int, min_interval_sec: float) -> None:
        self._sem: Optional[asyncio.Semaphore] = (
            asyncio.Semaphore(max_concurrency) if max_concurrency and max_concurrency > 0 else None
        )
        self._min_interval = max(0.0, float(min_interval_sec))
        self._lock = asyncio.Lock()
        self._last_start: Optional[float] = None

    async def __aenter__(self) -> "AsyncRateLimiter":
        if self._sem is not None:
            await self._sem.acquire()
        if self._min_interval > 0:
            async with self._lock:
                loop = asyncio.get_event_loop()
                now = loop.time()
                if self._last_start is not None:
                    wait = self._min_interval - (now - self._last_start)
                    if wait > 0:
                        await asyncio.sleep(wait)
                        now = loop.time()
                self._last_start = now
        return self

    async def __aexit__(self, *exc) -> bool:
        if self._sem is not None:
            self._sem.release()
        return False
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/clients/test_ratelimit.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/memedog/clients/ratelimit.py tests/clients/test_ratelimit.py
git commit -m "feat(clients): add AsyncRateLimiter (concurrency cap + min interval)"
```

---

## Task 2: SecretRedactingFilter + install_redaction

**Files:**
- Create: `src/memedog/observability/__init__.py`
- Create: `src/memedog/observability/redaction.py`
- Test: `tests/observability/__init__.py`, `tests/observability/test_redaction.py`

- [ ] **Step 1: Write the failing tests**

创建 `tests/observability/__init__.py`(空文件)和 `tests/observability/test_redaction.py`:

```python
"""Tests for secret redaction logging filter."""
import io
import logging

from memedog.observability.redaction import SecretRedactingFilter, install_redaction


def _record(msg, args=()):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


def test_filter_scrubs_api_key_pattern():
    f = SecretRedactingFilter()
    rec = _record("calling https://x.com/?api-key=ABC123secretXYZ&z=1")
    f.filter(rec)
    assert "ABC123secretXYZ" not in rec.getMessage()
    assert "api-key=***" in rec.getMessage()


def test_filter_scrubs_telegram_token():
    f = SecretRedactingFilter()
    rec = _record("POST https://api.telegram.org/bot7423235860:AAExampleTokenValue/send")
    f.filter(rec)
    assert "AAExampleTokenValue" not in rec.getMessage()
    assert "bot***" in rec.getMessage()


def test_filter_scrubs_exact_secret_value():
    f = SecretRedactingFilter(secrets=["super-secret-key-1234"])
    rec = _record("loaded key super-secret-key-1234 ok")
    f.filter(rec)
    assert "super-secret-key-1234" not in rec.getMessage()
    assert "***" in rec.getMessage()


def test_filter_scrubs_through_args():
    f = SecretRedactingFilter()
    rec = _record("url=%s", ("https://x?api-key=SECRETVAL123456",))
    f.filter(rec)
    assert "SECRETVAL123456" not in rec.getMessage()
    assert rec.args in ((), None)


def test_filter_never_raises_on_bad_record():
    f = SecretRedactingFilter()

    class Boom:
        def __str__(self):
            raise ValueError("boom")

    rec = _record("%s", (Boom(),))
    assert f.filter(rec) is True  # must not raise


def test_install_redaction_wires_handlers_for_child_loggers():
    root = logging.getLogger()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    try:
        class _S:
            helius_api_key = "HELIUSKEY1234567"
            rugcheck_api_key = None
            twitter_bearer = None
            openai_api_key = None
            anthropic_api_key = None
            deepseek_api_key = None
            telegram_bot_token = None

        install_redaction(_S())
        logging.getLogger("memedog.clients.helius").info(
            "rpc https://x/?api-key=HELIUSKEY1234567"
        )
        handler.flush()
        out = buf.getvalue()
        assert "HELIUSKEY1234567" not in out
        assert "***" in out
    finally:
        root.removeHandler(handler)
        # remove the filter we installed so other tests are unaffected
        for filt in list(root.filters):
            root.removeFilter(filt)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/observability/test_redaction.py -q`
Expected: FAIL — `ModuleNotFoundError: memedog.observability`

- [ ] **Step 3: Implement**

创建 `src/memedog/observability/__init__.py`(空文件)和 `src/memedog/observability/redaction.py`:

```python
"""Global logging filter that scrubs API keys / tokens from log output."""
from __future__ import annotations

import logging
import re

# Pattern-based redaction (applied to every log message).
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(api-key=)[^&\s\"']+", re.IGNORECASE), r"\1***"),
    (re.compile(r"bot\d+:[A-Za-z0-9_\-]+"), "bot***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE), r"\1***"),
]

_SECRET_ATTRS = (
    "helius_api_key",
    "rugcheck_api_key",
    "twitter_bearer",
    "openai_api_key",
    "anthropic_api_key",
    "deepseek_api_key",
    "telegram_bot_token",
)


class SecretRedactingFilter(logging.Filter):
    """Scrub secret patterns and exact secret values from log records.

    Always returns True (never drops a record); only rewrites the text.
    """

    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self._secrets = [s for s in (secrets or []) if s and len(s) >= 8]

    def _scrub(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, "***")
        for pat, repl in _PATTERNS:
            text = pat.sub(repl, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            scrubbed = self._scrub(msg)
            if scrubbed != msg:
                record.msg = scrubbed
                record.args = ()
        except Exception:
            # Logging must never crash the app.
            pass
        return True


def install_redaction(settings=None) -> SecretRedactingFilter:
    """Install a SecretRedactingFilter on the root logger and its handlers.

    Handler-level installation is what catches records that propagate up from
    child loggers (logger-level filters only see records logged directly).
    """
    secrets: list[str] = []
    if settings is not None:
        for name in _SECRET_ATTRS:
            val = getattr(settings, name, None)
            if val:
                secrets.append(str(val))
    filt = SecretRedactingFilter(secrets=secrets)
    root = logging.getLogger()
    root.addFilter(filt)
    for handler in root.handlers:
        handler.addFilter(filt)
    return filt
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/observability/test_redaction.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/memedog/observability tests/observability
git commit -m "feat(observability): add secret-redacting logging filter"
```

---

## Task 3: HTTP 配置段

**Files:**
- Modify: `src/memedog/config/settings.py`
- Modify: `src/memedog/config/thresholds.yaml`
- Test: `tests/config/test_config.py`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/config/test_config.py`(在 `TestLoadConfig` 类外、文件末尾即可):

```python
class TestHTTPConfig:
    def test_http_section_present(self):
        from memedog.config.settings import HTTPConfig, load_config

        cfg = load_config()
        assert isinstance(cfg.http, HTTPConfig)

    def test_policy_for_merges_override_onto_default(self):
        from memedog.config.settings import HTTPConfig

        http = HTTPConfig(
            default={"max_concurrency": 4, "min_interval_sec": 0.0, "timeout_sec": 10},
            overrides={"helius": {"min_interval_sec": 0.2}},
        )
        pol = http.policy_for("helius")
        assert pol.min_interval_sec == 0.2   # from override
        assert pol.max_concurrency == 4      # inherited from default
        assert pol.timeout_sec == 10         # inherited from default

    def test_policy_for_unknown_source_returns_default(self):
        from memedog.config.settings import HTTPConfig

        http = HTTPConfig(default={"max_concurrency": 7})
        assert http.policy_for("nope").max_concurrency == 7

    def test_load_config_without_http_section_uses_defaults(self, tmp_path):
        """A yaml missing the http section must still load (backward compat)."""
        import yaml
        from memedog.config.settings import load_config

        cfg = load_config()
        raw = yaml.safe_load(_THRESHOLDS_PATH.read_text(encoding="utf-8"))
        raw.pop("http", None)
        p = tmp_path / "no_http.yaml"
        p.write_text(yaml.safe_dump(raw), encoding="utf-8")
        cfg2 = load_config(p)
        assert cfg2.http.default.max_retries >= 1
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/config/test_config.py::TestHTTPConfig -q`
Expected: FAIL — `cannot import name 'HTTPConfig'` / `cfg.http` missing

- [ ] **Step 3: Implement**

在 `src/memedog/config/settings.py`,`AlertConfig` 之后新增:

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
    overrides: dict[str, dict] = {}

    def policy_for(self, source: str) -> HTTPClientPolicy:
        ov = self.overrides.get(source)
        return self.default.model_copy(update=ov) if ov else self.default
```

把 `Config` 增加 `http` 字段(带默认值,缺段也能用):

```python
class Config(BaseModel):
    scanner: ScannerConfig
    hardfilter: HardFilterConfig
    enricher: EnricherConfig
    scoring: ScoringConfig
    llmjudge: LLMJudgeConfig
    papertrader: PaperTraderConfig
    alert: AlertConfig
    http: HTTPConfig = HTTPConfig()
    settings: Settings
```

在 `load_config` 的 `return Config(...)` 里加一行(在 `alert=...` 之后、`settings=...` 之前):

```python
        http=HTTPConfig.model_validate(raw.get("http", {})),
```

在 `src/memedog/config/thresholds.yaml` 末尾(`alert:` 段之后)新增:

```yaml
http:
  default:
    timeout_sec: 10
    max_retries: 3
    backoff_base_sec: 0.2
    max_backoff_sec: 10
    max_concurrency: 4
    min_interval_sec: 0.0
    retry_status_codes: [429, 500, 502, 503, 504]
  overrides:
    dexscreener: { max_concurrency: 2, min_interval_sec: 1.0 }
    rugcheck:    { min_interval_sec: 0.5 }
    helius:      { max_concurrency: 2, min_interval_sec: 0.2 }
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/config/test_config.py -q`
Expected: PASS (既有 + 4 新)

- [ ] **Step 5: Commit**

```bash
git add src/memedog/config/settings.py src/memedog/config/thresholds.yaml tests/config/test_config.py
git commit -m "feat(config): add http section (per-source retry + rate-limit policy)"
```

---

## Task 4: BaseHTTPClient 智能重试

**Files:**
- Modify: `src/memedog/clients/base.py`
- Test: `tests/clients/test_base.py`

- [ ] **Step 1: Write the failing tests**

追加到 `tests/clients/test_base.py` 末尾:

```python
class TestSmartRetry:
    async def test_404_not_retried(self):
        from memedog.clients.base import BaseHTTPClient, DataSourceError

        with respx.mock:
            route = respx.get("https://api.example.com/missing").mock(
                return_value=httpx.Response(404, json={"error": "nope"})
            )
            async with BaseHTTPClient(base_url="https://api.example.com", backoff_base=0) as client:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(DataSourceError):
                        await client.get_json("/missing")
            assert route.call_count == 1  # no retry on 4xx

    async def test_429_retried(self):
        from memedog.clients.base import BaseHTTPClient

        with respx.mock:
            route = respx.get("https://api.example.com/limited")
            route.side_effect = [
                httpx.Response(429, json={"error": "slow down"}),
                httpx.Response(200, json={"ok": True}),
            ]
            async with BaseHTTPClient(base_url="https://api.example.com", backoff_base=0) as client:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await client.get_json("/limited")
        assert result == {"ok": True}

    async def test_429_honors_retry_after(self):
        from memedog.clients.base import BaseHTTPClient

        with respx.mock:
            route = respx.get("https://api.example.com/ra")
            route.side_effect = [
                httpx.Response(429, headers={"Retry-After": "2"}, json={}),
                httpx.Response(200, json={"ok": True}),
            ]
            async with BaseHTTPClient(base_url="https://api.example.com", backoff_base=0.01) as client:
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    await client.get_json("/ra")
        # the wait must equal Retry-After (2s), not the jitter backoff
        assert any(call.args and call.args[0] == 2 for call in mock_sleep.call_args_list)

    async def test_retry_after_capped_at_max_backoff(self):
        from memedog.clients.base import BaseHTTPClient

        with respx.mock:
            route = respx.get("https://api.example.com/big")
            route.side_effect = [
                httpx.Response(503, headers={"Retry-After": "999"}, json={}),
                httpx.Response(200, json={"ok": True}),
            ]
            async with BaseHTTPClient(
                base_url="https://api.example.com", backoff_base=0.01, max_backoff=5
            ) as client:
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    await client.get_json("/big")
        assert any(call.args and call.args[0] == 5 for call in mock_sleep.call_args_list)

    async def test_backoff_uses_jitter(self):
        """With jitter, delay = random.uniform(0, base*2**attempt). Patch random."""
        from memedog.clients.base import BaseHTTPClient, DataSourceError

        with respx.mock:
            respx.get("https://api.example.com/jit").mock(
                return_value=httpx.Response(500, json={})
            )
            with patch("memedog.clients.base.random.uniform", return_value=0.123) as mock_rand:
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    async with BaseHTTPClient(
                        base_url="https://api.example.com", max_retries=3, backoff_base=0.01
                    ) as client:
                        with pytest.raises(DataSourceError):
                            await client.get_json("/jit")
        assert mock_rand.called
        # every jittered sleep is the patched value
        assert all(call.args[0] == 0.123 for call in mock_sleep.call_args_list)
```

并**更新**已有的 `TestExponentialBackoff::test_sleep_called_with_exponential_delays`(jitter 后不再是确定值)。把该测试体替换为(patch `random.uniform` 让其返回上界 `base*2**attempt`,从而断言确定的退避序列):

```python
class TestExponentialBackoff:
    async def test_sleep_uses_jittered_exponential_upper_bound(self):
        """With random.uniform patched to return its upper bound, the delays are
        backoff_base*2**attempt: 0.01 then 0.02 (2 sleeps for max_retries=3)."""
        from memedog.clients.base import BaseHTTPClient, DataSourceError

        with respx.mock:
            respx.get("https://api.example.com/slow").mock(
                return_value=httpx.Response(500, json={"error": "always fails"})
            )
            with patch("memedog.clients.base.random.uniform", side_effect=lambda lo, hi: hi):
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    async with BaseHTTPClient(
                        base_url="https://api.example.com", max_retries=3, backoff_base=0.01
                    ) as client:
                        with pytest.raises(DataSourceError):
                            await client.get_json("/slow")

        assert mock_sleep.call_count == 2
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays[0] == pytest.approx(0.01)
        assert delays[1] == pytest.approx(0.02)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/clients/test_base.py -q`
Expected: FAIL — 404 currently retried (call_count 3≠1);Retry-After 未遵守;jitter 未实现;旧 backoff 测试已替换为引用 `memedog.clients.base.random`(尚未 import)。

- [ ] **Step 3: Implement**

在 `src/memedog/clients/base.py` 顶部加 `import random`:

```python
import asyncio
import logging
import random

import httpx
```

新增一个解析 Retry-After 的私有 helper(放在 `_build_url` 之后):

```python
    @staticmethod
    def _parse_retry_after(response: "httpx.Response") -> float | None:
        """Return Retry-After seconds as float, or None if absent/unparseable."""
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
```

把 `__init__` 改为新增 `max_backoff` 与 `retry_status_codes` 参数:

```python
    def __init__(
        self,
        base_url: str = "",
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 0.2,
        max_backoff: float = 10.0,
        retry_status_codes: list[int] | None = None,
        rate_limiter=None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._max_backoff = max_backoff
        self._retry_status_codes = (
            set(retry_status_codes) if retry_status_codes is not None
            else {429, 500, 502, 503, 504}
        )
        self._rate_limiter = rate_limiter
        self._client = httpx.AsyncClient(timeout=timeout)
```

把 `_request` 整体替换为(错误分类 + Retry-After + jitter;限流接入见 Task 5,本步先不加 limiter 包裹):

```python
    async def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> dict | list:
        full_url = self._build_url(url)
        last_exc: Exception | None = None

        for attempt in range(self._max_retries):
            retry_after: float | None = None
            try:
                response = await self._client.request(method, full_url, **kwargs)
                if response.is_success:
                    return response.json()

                status = response.status_code
                # Non-retryable status (e.g. 400/401/403/404) → fail immediately.
                if status not in self._retry_status_codes:
                    raise DataSourceError(
                        f"{method} {full_url} returned {status}: {response.text[:200]}"
                    )

                last_exc = DataSourceError(
                    f"{method} {full_url} returned {status}: {response.text[:200]}"
                )
                if status in (429, 503):
                    retry_after = self._parse_retry_after(response)
                logger.warning(
                    "Attempt %d/%d: %s %s → %d (retryable)",
                    attempt + 1, self._max_retries, method, full_url, status,
                )
            except httpx.HTTPError as exc:
                last_exc = DataSourceError(
                    f"{method} {full_url} raised httpx error: {exc}"
                )
                last_exc.__cause__ = exc
                logger.warning(
                    "Attempt %d/%d: %s %s → httpx error: %s",
                    attempt + 1, self._max_retries, method, full_url, exc,
                )

            # Sleep before next retry (not after the last attempt).
            if attempt < self._max_retries - 1:
                if retry_after is not None:
                    delay = min(retry_after, self._max_backoff)
                else:
                    upper = min(self._backoff_base * (2 ** attempt), self._max_backoff)
                    delay = random.uniform(0, upper)
                if delay > 0:
                    await asyncio.sleep(delay)

        raise DataSourceError(
            f"All {self._max_retries} attempts failed for {method} {full_url}"
        ) from last_exc
```

> 注:`DataSourceError` 已在文件顶部定义,immediate-raise 分支直接 raise 不进入重试。

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/clients/test_base.py -q`
Expected: PASS（含新 `TestSmartRetry` 与更新后的 backoff 测试;`test_500_then_200` / `test_persistent_500` / httpx 错误测试仍过）

- [ ] **Step 5: Commit**

```bash
git add src/memedog/clients/base.py tests/clients/test_base.py
git commit -m "feat(clients): error-classified retry with Retry-After + jitter"
```

---

## Task 5: BaseHTTPClient 接入限流

**Files:**
- Modify: `src/memedog/clients/base.py`
- Test: `tests/clients/test_base.py`

- [ ] **Step 1: Write the failing test**

追加到 `tests/clients/test_base.py`:

```python
class TestRateLimiterIntegration:
    async def test_rate_limiter_entered_per_attempt(self):
        """The injected rate limiter is entered once per HTTP attempt."""
        from memedog.clients.base import BaseHTTPClient

        entries = 0

        class _SpyLimiter:
            async def __aenter__(self_):
                nonlocal entries
                entries += 1
                return self_
            async def __aexit__(self_, *exc):
                return False

        with respx.mock:
            route = respx.get("https://api.example.com/x")
            route.side_effect = [
                httpx.Response(500, json={}),
                httpx.Response(200, json={"ok": True}),
            ]
            async with BaseHTTPClient(
                base_url="https://api.example.com", backoff_base=0,
                rate_limiter=_SpyLimiter(),
            ) as client:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await client.get_json("/x")
        assert result == {"ok": True}
        assert entries == 2  # one 500 attempt + one 200 attempt

    async def test_no_limiter_still_works(self):
        from memedog.clients.base import BaseHTTPClient

        with respx.mock:
            respx.get("https://api.example.com/y").mock(
                return_value=httpx.Response(200, json={"ok": True})
            )
            async with BaseHTTPClient(base_url="https://api.example.com") as client:
                result = await client.get_json("/y")
        assert result == {"ok": True}
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/clients/test_base.py::TestRateLimiterIntegration -q`
Expected: FAIL — limiter 未被使用(entries == 0)

- [ ] **Step 3: Implement**

在 `_request` 中,把单独一行的请求发送

```python
                response = await self._client.request(method, full_url, **kwargs)
```

替换为(用 limiter 包裹实际发送):

```python
                if self._rate_limiter is not None:
                    async with self._rate_limiter:
                        response = await self._client.request(method, full_url, **kwargs)
                else:
                    response = await self._client.request(method, full_url, **kwargs)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/clients/test_base.py -q`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add src/memedog/clients/base.py tests/clients/test_base.py
git commit -m "feat(clients): route requests through optional rate limiter"
```

---

## Task 6: app_factory 穿线 + 启动装脱敏

**Files:**
- Modify: `src/memedog/app_factory.py`
- Modify: `src/memedog/__main__.py`
- Modify: `dashboard/app.py`
- Test: `tests/test_app_factory.py`(若不存在则新建)

> 先确认:Run `ls tests/test_app_factory.py 2>/dev/null`。不存在则按下方新建。

- [ ] **Step 1: Write the failing test**

创建/追加 `tests/test_app_factory.py`:

```python
"""Structural tests for app_factory http-policy wiring (no network)."""
from memedog.app_factory import build_orchestrator
from memedog.clients.ratelimit import AsyncRateLimiter
from memedog.config import load_config
from memedog.store import Store


def test_clients_get_rate_limiter_and_policy(tmp_path):
    cfg = load_config()
    store = Store(str(tmp_path / "t.db"))
    try:
        orch = build_orchestrator(cfg, store)
        # scanner's client is the dexscreener client
        scanner_client = orch._scanner._client
        assert isinstance(scanner_client._rate_limiter, AsyncRateLimiter)
        # dexscreener override: timeout from default (10)
        assert scanner_client._timeout == cfg.http.policy_for("dexscreener").timeout_sec
    finally:
        store.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_app_factory.py -q`
Expected: FAIL — `scanner_client._rate_limiter` is None(尚未穿线)

- [ ] **Step 3: Implement**

在 `src/memedog/app_factory.py` 顶部加 import:

```python
from memedog.clients.ratelimit import AsyncRateLimiter
```

在 `build_orchestrator` 里,把"Data clients"段改为按 policy 构造。新增一个本地 helper 并替换 4 个 client 构造:

```python
    def _http_kwargs(source: str) -> dict:
        pol = cfg.http.policy_for(source)
        return dict(
            timeout=pol.timeout_sec,
            max_retries=pol.max_retries,
            backoff_base=pol.backoff_base_sec,
            max_backoff=pol.max_backoff_sec,
            retry_status_codes=pol.retry_status_codes,
            rate_limiter=AsyncRateLimiter(pol.max_concurrency, pol.min_interval_sec),
        )

    dex_client = DexScreenerClient(**_http_kwargs("dexscreener"))
    rugcheck_client = RugCheckClient(**_http_kwargs("rugcheck"))
    helius_api_key: str = cfg.settings.helius_api_key or ""
    helius_client = HeliusClient(api_key=helius_api_key, **_http_kwargs("helius"))
    twitter_bearer: Optional[str] = cfg.settings.twitter_bearer
    twitter_client = TwitterClient(bearer_token=twitter_bearer, **_http_kwargs("twitter"))
```

> 删除原来的 4 行无参 client 构造(`DexScreenerClient()` 等),用上面替换。其余 orchestrator 组装不变。

在 `src/memedog/__main__.py` 的 `main()` 里,`load_config()` 之后、构造 orchestrator 之前加:

```python
    from memedog.observability.redaction import install_redaction
    install_redaction(cfg.settings)
```

在 `dashboard/app.py` 的 `main()` 里,加载 `cfg = load_config()` 成功后加:

```python
        try:
            from memedog.observability.redaction import install_redaction
            install_redaction(cfg.settings)
        except Exception:
            pass
```

> dashboard 中 `cfg` 可能为 None(load 失败已被 try 包裹),故仅在 `cfg` 非 None 分支调用;若现有结构是 `try: cfg = load_config() except: cfg = None`,把上面这段放进成功路径(`if cfg is not None:`)。

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_app_factory.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/memedog/app_factory.py src/memedog/__main__.py dashboard/app.py tests/test_app_factory.py
git commit -m "feat: wire http policy + rate limiters into clients; install log redaction at startup"
```

---

## Task 7: 全量测试 + 真实验证

**Files:** 无改动(验证 + 必要修补)

- [ ] **Step 1: 默认全量套件**

Run: `python -m pytest -q`
Expected: 全过(新增 ~20 测试)。失败则定位修复后重跑。

- [ ] **Step 2: 零外部联网证明**

Run: `python -m pytest -q --disable-socket --allow-hosts=127.0.0.1,::1,localhost`
Expected: 全过且无外部网络调用。

- [ ] **Step 3: 真实脱敏端到端小验证(真实日志路径,非 mock)**

写一次性脚本 `scripts/_redaction_smoke.py`(验证后删):

```python
import logging, io
from memedog.config import load_config
from memedog.observability.redaction import install_redaction

buf = io.StringIO()
h = logging.StreamHandler(buf)
logging.getLogger().addHandler(h)
logging.getLogger().setLevel(logging.INFO)
install_redaction(load_config().settings)
logging.getLogger("memedog.clients.base").warning(
    "GET https://mainnet.helius-rpc.com/?api-key=FAKEKEY1234567 returned 429"
)
h.flush()
out = buf.getvalue()
assert "FAKEKEY1234567" not in out, out
assert "api-key=***" in out, out
print("redaction smoke OK:", out.strip())
```

Run: `python scripts/_redaction_smoke.py` then `rm scripts/_redaction_smoke.py`
Expected: 打印 `redaction smoke OK: ... api-key=*** ...`

- [ ] **Step 4: live 既有客户端测试未被破坏(可选,需网络)**

Run: `python -m pytest -m live tests/live/test_live_dexscreener.py tests/live/test_live_rugcheck.py -q`
Expected: 通过或自跳过(限流/重试改造不破坏真实端点)。

- [ ] **Step 5: 合并回 main(分支上先 review 再合)**

```bash
git checkout main
git merge --no-ff feature/robustness-http -m "feat: robustness — smart retry + rate limit + secret redaction (sub-project B)"
python -m pytest -q   # verify on merged result
git branch -d feature/robustness-http
```

---

## 自审清单(写计划后)

- **Spec 覆盖**:智能重试=Task4;限流器=Task1,接入=Task5;脱敏=Task2,启动装=Task6;http 配置=Task3,穿线=Task6;测试=Task1–7;非目标(codex 熔断/缓存)未触及。✅
- **占位符**:无 TBD/TODO;每步含完整代码与可运行命令。✅
- **类型一致**:`AsyncRateLimiter(max_concurrency,min_interval_sec)`(Task1/3/6)、`SecretRedactingFilter(secrets=)`/`install_redaction(settings)`(Task2/6)、`HTTPClientPolicy`/`HTTPConfig.policy_for`(Task3/6)、BaseHTTPClient 新参 `max_backoff`/`retry_status_codes`/`rate_limiter`(Task4/5/6)前后一致。✅
- **向后兼容**:`Config.http` 带默认、`load_config` 用 `raw.get("http",{})`、BaseHTTPClient 新参均有默认 → 既有测试与无 http 段 yaml 不破。旧 backoff 测试已随 jitter 更新。✅
- **已知 logging 陷阱**:logger 级 filter 不拦子 logger 传播的记录 → `install_redaction` 同时给 root 的每个 handler 装 filter(Task2 已处理,测试覆盖)。✅
