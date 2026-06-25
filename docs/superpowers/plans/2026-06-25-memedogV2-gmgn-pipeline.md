# memedogV2: GMGN HardFilter + LLM Audit Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a parallel `src/memedogV2/` package that takes a `(ca_address, lp_address)` pair, runs a deterministic `gmgn-cli` HardFilter, then a Bull/Bear/Judge LLM audit (via `codex exec` + gmgn-skills), and emits a `Signal` with a `recommended` flag — without touching the existing `src/memedog/`.

**Architecture:** Funnel. `AddressIntake` queue → `HardFilter` (three deterministic `gmgn-cli` commands behind a rate-limited/cached client, objective red-lines only) → `Audit` (one shared `EvidenceBundle` gathered via gmgn-skills, then Bull + Bear analysts + Judge, each a structured `codex exec --output-schema` call) → `Signal`. All gmgn JSON field paths are isolated in one `FIELD_MAP` confirmed by the Phase 0 spike; downstream tasks test against captured fixtures.

**Tech Stack:** Python 3.11+, asyncio, pydantic v2, subprocess (gmgn-cli, codex exec), pytest. No real network in tests.

**Spec:** `docs/superpowers/specs/2026-06-25-gmgn-hardfilter-llm-audit-redesign-design.md`

---

## ⚠️ Task 0 Spike Corrections (AUTHORITATIVE — override any conflicting task body below)

The Phase 0 spike ran for real (GREEN, 2026-06-25) against `gmgn-cli@1.4.7` + `codex exec` (gpt-5.5). Fixtures live in `tests/memedogV2/fixtures/{security,info,pool}.json`. These corrections supersede the originally-guessed details in Tasks 4–8:

1. **HardFilter calls 2 commands, not 3:** `token security` then `token info`. `token info` already contains concentration, manipulation, momentum, dev, and smart-money fields; `token security` only adds authorities + burn/lock + tax. **Drop `token pool` from HardFilter** (and from the security→pool→info ordering — it's now security→info).

2. **Real `FIELD_MAP`** (`src/memedogV2/hardfilter/fieldmap.py`) — paths confirmed against fixtures:
```python
FIELD_MAP = {
    # from `token security --raw`
    "renounced_mint":     "renounced_mint",            # bool
    "renounced_freeze":   "renounced_freeze_account",  # bool
    "honeypot":           "honeypot",                  # int 0/1 (SOL has no is_honeypot)
    "burn_status":        "burn_status",               # "burn" == LP burned
    "lp_locked":          "lock_summary.is_locked",    # bool
    "buy_tax":            "buy_tax",                    # str number
    "sell_tax":           "sell_tax",                  # str number
    # from `token info --raw`
    "top10_rate":         "stat.top_10_holder_rate",        # str 0-1 fraction
    "creator_hold_rate":  "stat.creator_hold_rate",         # str 0-1
    "dev_team_hold_rate": "stat.dev_team_hold_rate",        # str 0-1
    "fresh_wallet_rate":  "stat.fresh_wallet_rate",         # str 0-1
    "sniper_hold_rate":   "stat.top70_sniper_hold_rate",    # str 0-1
    "bundler_rate":       "stat.top_bundler_trader_percentage",  # str 0-1
    "sniper_wallets":     "wallet_tags_stat.sniper_wallets",     # int
    "liquidity_usd":      "liquidity",                 # str number (top-level in info)
    "price_usd":          "price.price",               # str number
    "circulating_supply": "circulating_supply",        # str number
    "volume_5m":          "price.volume_5m",           # str number
    "buys_5m":            "price.buys_5m",             # int
    "sells_5m":           "price.sells_5m",            # int
    # LLM evidence only (NOT hard gates)
    "dev_created_count":  "dev.creator_open_count",          # int
    "dev_ath_mc":         "dev.ath_token_info.ath_mc",       # str (may be "")
    "smart_wallets":      "wallet_tags_stat.smart_wallets",  # int
    "renowned_wallets":   "wallet_tags_stat.renowned_wallets",  # int
}
```

3. **Coercion is mandatory.** Add to `rules.py`:
```python
def num(v):
    """Coerce gmgn string/number to float; '' or None -> None."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
```
All rate fields are **0–1 fractions** — compare against fractional thresholds (e.g. `max_top10_rate: 0.35`, not `35`). Rename the hardfilter config keys accordingly: `max_top10_rate`, `max_single/creator_rate`, `max_dev_rate`, `max_fresh_wallet_rate`, `max_sniper_hold_rate`, `max_bundler_rate`, and keep count/usd keys (`max_sniper_wallets`, `min_liquidity_usd`, `min_volume_5m`, `min_buy_sell_ratio_5m`, `max_fdv_to_liquidity`). FDV = `num(price_usd) * num(circulating_supply)`.

4. **Authorities/LP from real fields:** fail if `renounced_mint is False` or `renounced_freeze is False` or `honeypot == 1`. LP-safe if `burn_status == "burn"` OR `lp_locked is True` (fail only when both indicate unsafe and at least one value is present).

5. **No dev hard-gate.** There is no graduation-rate field in gmgn data. **Remove `check_dev_track`** from HardFilter; dev track record (`dev_created_count`, `dev_ath_mc`) goes into the `EvidenceBundle` for the LLM only.

6. **codex/`--output-schema` is strict (Tasks 6–8):** every schema object MUST have `"additionalProperties": false` AND list every property in `"required"`. For optional fields use nullable types `{"type": ["integer", "null"]}` but still include them in `required`. Also: `codex exec` MUST be invoked with stdin closed (`< /dev/null` / `asyncio.subprocess.DEVNULL`) or it hangs reading stdin. The working invocation is in `scripts/spike_codex_gmgn.sh` (`--dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --output-schema <f> -o <out>`).

7. **Test fixtures over invented JSON:** Tasks 4/5 tests should load `tests/memedogV2/fixtures/{security,info}.json` for the "clean token" path (USDC: passes authorities, near-zero concentration, high liquidity) rather than hand-built dicts, plus small synthetic dicts for the failing red-line cases.

---

## File Structure

```
src/memedogV2/
├── __init__.py
├── models/
│   ├── __init__.py
│   └── contracts.py          # HardFilterResult, EvidenceBundle, Signal, SignalKind
├── clients/
│   ├── __init__.py
│   ├── ratelimit.py          # async TokenBucket
│   ├── errors.py             # DataSourceError, RateLimitBanned
│   └── gmgn_cli.py           # GmgnCli: subprocess wrapper + cache + 429 backoff
├── hardfilter/
│   ├── __init__.py
│   ├── fieldmap.py           # FIELD_MAP: gmgn --raw JSON paths (confirmed by spike)
│   ├── rules.py              # pure rule functions -> (passed, reason)
│   └── hardfilter.py         # HardFilter aggregator (security->pool->info, early-exit)
├── audit/
│   ├── __init__.py
│   ├── evidence.py           # EvidenceGatherer -> EvidenceBundle (codex agent)
│   └── debate.py             # BullBearJudge -> Signal
├── llm/
│   ├── __init__.py
│   └── codex_agent.py        # CodexAgent: codex exec (network on) + --output-schema
├── intake.py                 # AddressIntake queue (ca, lp), drain-rate limited
├── orchestrator.py           # V2Orchestrator: intake -> hardfilter -> audit
└── config.py                 # V2Config (pydantic-settings): gmgn + hardfilter knobs

tests/memedogV2/
├── __init__.py
├── fixtures/                 # captured gmgn --raw JSON (from Task 0 spike)
├── test_models.py
├── test_ratelimit.py
├── test_gmgn_cli.py
├── test_rules.py
├── test_hardfilter.py
├── test_codex_agent.py
├── test_evidence.py
├── test_debate.py
├── test_intake.py
└── test_orchestrator.py
```

---

## Task 0: Phase 0 Spike (GATING — manual, no downstream code until green)

**Goal:** Prove `codex exec` can run a gmgn-skill + `gmgn-cli` non-interactively and return schema-valid JSON, AND capture real `--raw` output to use as fixtures and to fill `FIELD_MAP`.

This task is investigation, not TDD. Do NOT start Task 1 until Step 6 is green.

- [ ] **Step 1: Ensure prerequisites**

```bash
codex --version            # expect codex-cli >= 0.142
echo "$GMGN_API_KEY"       # must be non-empty; if empty, stop and ask user to fill .env
which node npx
```

Expected: codex present, `GMGN_API_KEY` non-empty. If the key is empty, STOP — the spike cannot run.

- [ ] **Step 2: Install gmgn-skills into codex**

```bash
cd /Users/kellylim/meme-ai-agent
npx -y skills add GMGNAI/gmgn-skills
ls -la .codex .claude-plugin 2>/dev/null   # confirm skill/plugin files landed
```

Expected: gmgn skill files present (`.codex/` or equivalent). Record where they landed.

- [ ] **Step 3: Capture raw gmgn-cli JSON for a real Solana token (manual, rate-limit-aware)**

Pick one known live mint (CA). Run ONE command, wait, then the next (respect ~1 req/s; never retry on 429):

```bash
gmgn-cli token security --chain sol --address <REAL_CA> --raw > tests/memedogV2/fixtures/security.json
sleep 2
gmgn-cli token pool     --chain sol --address <REAL_CA> --raw > tests/memedogV2/fixtures/pool.json
sleep 2
gmgn-cli token info     --chain sol --address <REAL_CA> --raw > tests/memedogV2/fixtures/info.json
```

Expected: three non-empty JSON files. If any returns `429 RATE_LIMIT_*`, STOP, wait 5 min, retry later — do not loop.

- [ ] **Step 4: Fill `FIELD_MAP` from the real JSON**

Open the three fixtures. Record the exact JSON path for each field the HardFilter needs (see Task 5 `FIELD_MAP`). Note which of these actually exist in `token security --raw`: mint/freeze authority, LP burned/locked (likely in `pool`), top10 %, max single wallet %, dev %, sniper count, fresh-wallet %, bundler %, dev historical token count, dev graduation rate, liquidity USD, 5m volume, buy/sell counts, FDV. If a field is absent, note the alternative command or mark it `None` (degraded).

- [ ] **Step 5: Validate codex exec runs a skill + gmgn-cli with structured output**

Create `scripts/spike_codex_gmgn.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
SCHEMA=$(mktemp); OUT=$(mktemp)
cat > "$SCHEMA" <<'JSON'
{ "type":"object",
  "properties":{ "address":{"type":"string"}, "honeypot":{"type":"boolean"}, "raw_ok":{"type":"boolean"} },
  "required":["address","raw_ok"], "additionalProperties": true }
JSON
codex exec \
  --sandbox workspace-write \
  --skip-git-repo-check \
  --output-schema "$SCHEMA" \
  -o "$OUT" \
  "Use the gmgn-token skill to run gmgn-cli token security for Solana address <REAL_CA>. Return JSON with address, honeypot (bool if known else false), and raw_ok=true if the command returned data."
echo "----- codex last message -----"; cat "$OUT"
```

```bash
chmod +x scripts/spike_codex_gmgn.sh && ./scripts/spike_codex_gmgn.sh
```

Expected: codex executes the skill, runs `gmgn-cli`, and `$OUT` is schema-valid JSON with `raw_ok=true`. If codex blocks on network/approval, try adding `--dangerously-bypass-approvals-and-sandbox` (note this in findings) and record the exact working invocation.

- [ ] **Step 6: Record findings & GO/NO-GO**

Append to the spec under "13. 开放风险" the confirmed: (a) working `codex exec` flag set, (b) gmgn JSON field paths, (c) observed rate-limit behavior. Commit fixtures + script.

```bash
git add tests/memedogV2/fixtures scripts/spike_codex_gmgn.sh docs/superpowers/specs/2026-06-25-gmgn-hardfilter-llm-audit-redesign-design.md
git commit -m "spike(memedogV2): confirm codex+gmgn-cli integration, capture fixtures and field paths"
```

GO = Step 5 returned schema-valid JSON. NO-GO = return to brainstorming; do not proceed.

---

## Task 1: Package skeleton + data contracts

**Files:**
- Create: `src/memedogV2/__init__.py`, `src/memedogV2/models/__init__.py`, `src/memedogV2/models/contracts.py`
- Create: `tests/memedogV2/__init__.py`, `tests/memedogV2/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_models.py
from memedogV2.models.contracts import (
    SignalKind, HardFilterResult, EvidenceBundle, Signal,
)


def test_hardfilter_result_defaults():
    r = HardFilterResult(ca_address="CA", lp_address="LP")
    assert r.passed is False
    assert r.dropped == [] and r.flagged == []
    assert r.facts == {}


def test_evidence_bundle_holds_optional_signals():
    e = EvidenceBundle(ca_address="CA", smart_money_count=3, kol_holder_count=1)
    assert e.smart_money_count == 3
    assert e.dev_graduation_rate is None  # optional/degraded allowed


def test_signal_recommended_and_kind():
    s = Signal(
        ca_address="CA", signal=SignalKind.BULLISH, recommended=True,
        confidence=0.8, rationale="strong smart money", evidence_refs=["smart_money_count"],
    )
    assert s.signal is SignalKind.BULLISH
    assert s.recommended is True
    assert s.confidence == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: memedogV2`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/__init__.py
"""memedogV2 — GMGN-driven HardFilter + LLM audit pipeline (parallel to memedog)."""
```

```python
# src/memedogV2/models/__init__.py
from memedogV2.models.contracts import (
    SignalKind, HardFilterResult, EvidenceBundle, Signal,
)

__all__ = ["SignalKind", "HardFilterResult", "EvidenceBundle", "Signal"]
```

```python
# src/memedogV2/models/contracts.py
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SignalKind(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class HardFilterResult(BaseModel):
    """Deterministic gmgn-cli facts + red-line outcome for one address."""
    ca_address: str
    lp_address: str
    passed: bool = False
    facts: dict[str, Any] = Field(default_factory=dict)
    dropped: list[str] = Field(default_factory=list)   # "rule_name: actual vs threshold"
    flagged: list[str] = Field(default_factory=list)
    trace_id: str = ""


class EvidenceBundle(BaseModel):
    """Interpretation signals gathered for the LLM audit (all optional/degradable)."""
    ca_address: str
    smart_money_count: Optional[int] = None
    kol_holder_count: Optional[int] = None
    dev_created_token_count: Optional[int] = None
    dev_graduation_rate: Optional[float] = None
    historical_ath: Optional[float] = None
    trend: Optional[dict[str, Any]] = None
    holders_detail: Optional[dict[str, Any]] = None
    missing: list[str] = Field(default_factory=list)   # dims that failed to fetch


class Signal(BaseModel):
    ca_address: str
    signal: SignalKind
    recommended: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)
    trace_id: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/__init__.py src/memedogV2/models tests/memedogV2/__init__.py tests/memedogV2/test_models.py
git commit -m "feat(memedogV2): data contracts (HardFilterResult, EvidenceBundle, Signal)"
```

---

## Task 2: Async TokenBucket rate limiter

**Files:**
- Create: `src/memedogV2/clients/__init__.py`, `src/memedogV2/clients/ratelimit.py`
- Create: `tests/memedogV2/test_ratelimit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_ratelimit.py
import asyncio
import pytest
from memedogV2.clients.ratelimit import TokenBucket


@pytest.mark.asyncio
async def test_bucket_allows_burst_then_throttles():
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    b = TokenBucket(rate_per_sec=10.0, capacity=2)
    await b.acquire()        # immediate (capacity)
    await b.acquire()        # immediate (capacity)
    await b.acquire()        # must wait ~0.1s for a refill
    elapsed = loop.time() - t0
    assert elapsed >= 0.08
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_ratelimit.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/clients/__init__.py
```

```python
# src/memedogV2/clients/ratelimit.py
from __future__ import annotations

import asyncio


class TokenBucket:
    """Simple async token-bucket. Conservative default suits gmgn's tight limits."""

    def __init__(self, rate_per_sec: float, capacity: int) -> None:
        self._rate = float(rate_per_sec)
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._lock = asyncio.Lock()
        self._last = asyncio.get_event_loop().time()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = asyncio.get_event_loop().time()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._last) * self._rate
                )
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_ratelimit.py -v`
Expected: PASS. (If `pytest-asyncio` mode errors, add `asyncio_mode = auto` to `pyproject.toml [tool.pytest.ini_options]`.)

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/clients/__init__.py src/memedogV2/clients/ratelimit.py tests/memedogV2/test_ratelimit.py
git commit -m "feat(memedogV2): async token-bucket rate limiter"
```

---

## Task 3: GmgnCli client (subprocess + cache + 429 backoff)

**Files:**
- Create: `src/memedogV2/clients/errors.py`, `src/memedogV2/clients/gmgn_cli.py`
- Create: `tests/memedogV2/test_gmgn_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_gmgn_cli.py
import json
import time
import pytest
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.clients.errors import RateLimitBanned, DataSourceError


class FakeRunner:
    """Records calls; returns queued (returncode, stdout, stderr) tuples."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, args):
        self.calls.append(args)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_token_security_parses_raw_json():
    runner = FakeRunner([(0, json.dumps({"honeypot": False}), "")])
    cli = GmgnCli(runner=runner, rate_per_sec=1000.0, capacity=10, cache_ttl_sec=60)
    out = await cli.token_security("CA")
    assert out == {"honeypot": False}
    assert runner.calls[0][:3] == ["token", "security", "--chain"]


@pytest.mark.asyncio
async def test_cache_avoids_second_subprocess_call():
    runner = FakeRunner([(0, json.dumps({"a": 1}), "")])
    cli = GmgnCli(runner=runner, rate_per_sec=1000.0, capacity=10, cache_ttl_sec=60)
    await cli.token_info("CA")
    await cli.token_info("CA")           # served from cache
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_429_raises_ratelimitbanned_with_reset_at():
    body = json.dumps({"code": 429, "error": "RATE_LIMIT_BANNED", "reset_at": int(time.time()) + 300})
    runner = FakeRunner([(1, body, "rate limit")])
    cli = GmgnCli(runner=runner, rate_per_sec=1000.0, capacity=10, cache_ttl_sec=60)
    with pytest.raises(RateLimitBanned) as ei:
        await cli.token_pool("CA")
    assert ei.value.reset_at is not None


@pytest.mark.asyncio
async def test_nonzero_nonrate_raises_datasourceerror():
    runner = FakeRunner([(2, "", "boom")])
    cli = GmgnCli(runner=runner, rate_per_sec=1000.0, capacity=10, cache_ttl_sec=60)
    with pytest.raises(DataSourceError):
        await cli.token_info("CA")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_gmgn_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/clients/errors.py
from __future__ import annotations

from typing import Optional


class DataSourceError(Exception):
    """gmgn-cli failed in a non-rate-limit way."""


class RateLimitBanned(Exception):
    """gmgn returned 429. reset_at is the unix ts when the ban lifts (if known)."""

    def __init__(self, message: str, reset_at: Optional[int] = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at
```

```python
# src/memedogV2/clients/gmgn_cli.py
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Awaitable, Callable, Optional

from memedogV2.clients.errors import DataSourceError, RateLimitBanned
from memedogV2.clients.ratelimit import TokenBucket

Runner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]


async def _subprocess_runner(args: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "gmgn-cli", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode(), err.decode()


class GmgnCli:
    """Deterministic gmgn-cli wrapper: rate-limited, cached, 429-aware.

    NEVER retries on 429 — it raises RateLimitBanned so the caller can suspend
    until reset_at (retrying during cooldown extends the ban).
    """

    def __init__(
        self,
        *,
        runner: Optional[Runner] = None,
        chain: str = "sol",
        rate_per_sec: float = 1.0,
        capacity: int = 1,
        cache_ttl_sec: float = 60.0,
    ) -> None:
        self._runner = runner or _subprocess_runner
        self._chain = chain
        self._bucket = TokenBucket(rate_per_sec=rate_per_sec, capacity=capacity)
        self._ttl = cache_ttl_sec
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def token_security(self, ca: str) -> dict[str, Any]:
        return await self._run("token", "security", ca)

    async def token_pool(self, ca: str) -> dict[str, Any]:
        return await self._run("token", "pool", ca)

    async def token_info(self, ca: str) -> dict[str, Any]:
        return await self._run("token", "info", ca)

    async def _run(self, group: str, sub: str, ca: str) -> dict[str, Any]:
        key = f"{group}:{sub}:{ca}"
        hit = self._cache.get(key)
        if hit and (time.time() - hit[0]) < self._ttl:
            return hit[1]

        await self._bucket.acquire()
        args = [group, sub, "--chain", self._chain, "--address", ca, "--raw"]
        code, stdout, stderr = await self._runner(args)

        parsed = self._try_parse(stdout)
        if parsed is not None and self._is_429(parsed):
            raise RateLimitBanned(str(parsed), reset_at=parsed.get("reset_at"))
        if code != 0:
            if parsed is not None and self._is_429(parsed):
                raise RateLimitBanned(str(parsed), reset_at=parsed.get("reset_at"))
            raise DataSourceError(f"gmgn-cli {group} {sub} rc={code}: {stderr.strip()}")
        if parsed is None:
            raise DataSourceError(f"gmgn-cli {group} {sub}: unparseable output")

        self._cache[key] = (time.time(), parsed)
        return parsed

    @staticmethod
    def _try_parse(s: str) -> Optional[dict[str, Any]]:
        s = s.strip()
        if not s:
            return None
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else {"_list": obj}
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _is_429(obj: dict[str, Any]) -> bool:
        return obj.get("code") == 429 or str(obj.get("error", "")).startswith("RATE_LIMIT")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_gmgn_cli.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/clients/errors.py src/memedogV2/clients/gmgn_cli.py tests/memedogV2/test_gmgn_cli.py
git commit -m "feat(memedogV2): gmgn-cli client with cache and 429 backoff"
```

---

## Task 4: HardFilter pure rule functions + FIELD_MAP

**Files:**
- Create: `src/memedogV2/hardfilter/__init__.py`, `src/memedogV2/hardfilter/fieldmap.py`, `src/memedogV2/hardfilter/rules.py`
- Create: `tests/memedogV2/test_rules.py`

> `FIELD_MAP` paths are filled from the Task 0 spike fixtures. Each rule reads a value via a path helper so unknown/absent fields degrade to `None` (skip rule) instead of crashing.

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_rules.py
from memedogV2.hardfilter.rules import (
    get_path, check_authorities, check_concentration, check_dev_track, check_momentum,
)


def test_get_path_nested_and_missing():
    assert get_path({"a": {"b": 5}}, "a.b") == 5
    assert get_path({"a": {}}, "a.b") is None
    assert get_path({}, "x") is None


def test_authorities_fail_when_mint_active():
    ok, reason = check_authorities(mint_revoked=False, freeze_revoked=True, lp_ok=True)
    assert ok is False and "mint" in reason.lower()


def test_authorities_pass_when_all_revoked():
    ok, _ = check_authorities(mint_revoked=True, freeze_revoked=True, lp_ok=True)
    assert ok is True


def test_concentration_fails_on_top10():
    cfg = {"max_top10_pct": 35, "max_single_wallet_pct": 20, "max_dev_pct": 10}
    ok, reason = check_concentration(top10_pct=40, single_pct=5, dev_pct=2, cfg=cfg)
    assert ok is False and "top10" in reason.lower()


def test_concentration_skips_missing_value():
    cfg = {"max_top10_pct": 35, "max_single_wallet_pct": 20, "max_dev_pct": 10}
    ok, _ = check_concentration(top10_pct=None, single_pct=None, dev_pct=None, cfg=cfg)
    assert ok is True  # nothing to fail on -> degrade open


def test_dev_track_extreme_gate():
    cfg = {"serial_token_count_threshold": 5, "min_graduation_rate_for_serial": 0.0}
    ok, reason = check_dev_track(created=8, graduation_rate=0.0, cfg=cfg)
    assert ok is False and "dev" in reason.lower()
    ok2, _ = check_dev_track(created=8, graduation_rate=0.3, cfg=cfg)
    assert ok2 is True


def test_momentum_fails_low_liquidity():
    cfg = {"min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0}
    ok, reason = check_momentum(liquidity=5000, vol5m=2000, buy_sell=1.5, cfg=cfg)
    assert ok is False and "liquidity" in reason.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_rules.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/hardfilter/__init__.py
```

```python
# src/memedogV2/hardfilter/fieldmap.py
"""Dotted JSON paths into gmgn-cli --raw output.

CONFIRM/ADJUST these against tests/memedogV2/fixtures/*.json captured in Task 0.
A path that does not exist returns None at read time -> rule degrades open.
"""

FIELD_MAP = {
    # from `token security --raw`
    "mint_revoked": "security.renounced.mint",
    "freeze_revoked": "security.renounced.freeze",
    "top10_pct": "security.top_10_holder_rate",
    "single_wallet_pct": "security.top_holder_rate",
    "dev_pct": "security.dev.holdings_rate",
    "sniper_count": "security.sniper_count",
    "fresh_wallet_pct": "security.fresh_wallet_rate",
    "bundler_pct": "security.bundler_rate",
    "dev_created_count": "security.dev.created_token_count",
    "dev_graduation_rate": "security.dev.graduation_rate",
    # from `token pool --raw`
    "lp_burned": "pool.burn_status",
    "lp_locked": "pool.lock_status",
    "liquidity_usd": "pool.liquidity",
    # from `token info --raw`
    "volume_5m": "info.volume.m5",
    "buy_count_5m": "info.txns.m5.buys",
    "sell_count_5m": "info.txns.m5.sells",
    "fdv": "info.fdv",
}
```

```python
# src/memedogV2/hardfilter/rules.py
from __future__ import annotations

from typing import Any, Optional


def get_path(obj: Any, dotted: str) -> Optional[Any]:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def check_authorities(*, mint_revoked: Optional[bool], freeze_revoked: Optional[bool],
                      lp_ok: Optional[bool]) -> tuple[bool, str]:
    if mint_revoked is False:
        return False, "authority: mint not revoked"
    if freeze_revoked is False:
        return False, "authority: freeze not revoked"
    if lp_ok is False:
        return False, "authority: LP not burned/locked"
    return True, "authorities ok (or unknown)"


def check_concentration(*, top10_pct: Optional[float], single_pct: Optional[float],
                        dev_pct: Optional[float], cfg: dict) -> tuple[bool, str]:
    if top10_pct is not None and top10_pct > cfg["max_top10_pct"]:
        return False, f"concentration: top10 {top10_pct} > {cfg['max_top10_pct']}"
    if single_pct is not None and single_pct > cfg["max_single_wallet_pct"]:
        return False, f"concentration: single {single_pct} > {cfg['max_single_wallet_pct']}"
    if dev_pct is not None and dev_pct > cfg["max_dev_pct"]:
        return False, f"concentration: dev {dev_pct} > {cfg['max_dev_pct']}"
    return True, "concentration ok (or unknown)"


def check_manipulation(*, sniper_count: Optional[int], fresh_pct: Optional[float],
                       bundler_pct: Optional[float], cfg: dict) -> tuple[bool, str]:
    if sniper_count is not None and sniper_count > cfg["max_sniper_count"]:
        return False, f"manipulation: sniper {sniper_count} > {cfg['max_sniper_count']}"
    if fresh_pct is not None and fresh_pct > cfg["max_fresh_wallet_pct"]:
        return False, f"manipulation: fresh {fresh_pct} > {cfg['max_fresh_wallet_pct']}"
    if bundler_pct is not None and bundler_pct > cfg["max_bundler_pct"]:
        return False, f"manipulation: bundler {bundler_pct} > {cfg['max_bundler_pct']}"
    return True, "manipulation ok (or unknown)"


def check_dev_track(*, created: Optional[int], graduation_rate: Optional[float],
                    cfg: dict) -> tuple[bool, str]:
    """Extreme gate only: serial creator with zero graduations."""
    if created is None or graduation_rate is None:
        return True, "dev track unknown"
    if (created >= cfg["serial_token_count_threshold"]
            and graduation_rate <= cfg["min_graduation_rate_for_serial"]):
        return False, f"dev: serial creator {created} tokens, graduation {graduation_rate}"
    return True, "dev track ok"


def check_momentum(*, liquidity: Optional[float], vol5m: Optional[float],
                   buy_sell: Optional[float], cfg: dict) -> tuple[bool, str]:
    if liquidity is not None and liquidity < cfg["min_liquidity_usd"]:
        return False, f"momentum: liquidity {liquidity} < {cfg['min_liquidity_usd']}"
    if vol5m is not None and vol5m < cfg["min_volume_5m"]:
        return False, f"momentum: vol5m {vol5m} < {cfg['min_volume_5m']}"
    if buy_sell is not None and buy_sell < cfg["min_buy_sell_ratio_5m"]:
        return False, f"momentum: buy/sell {buy_sell} < {cfg['min_buy_sell_ratio_5m']}"
    return True, "momentum ok (or unknown)"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_rules.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/hardfilter/__init__.py src/memedogV2/hardfilter/fieldmap.py src/memedogV2/hardfilter/rules.py tests/memedogV2/test_rules.py
git commit -m "feat(memedogV2): hardfilter pure rule functions + field map"
```

---

## Task 5: HardFilter aggregator (security → pool → info, early-exit)

**Files:**
- Create: `src/memedogV2/hardfilter/hardfilter.py`
- Create: `tests/memedogV2/test_hardfilter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_hardfilter.py
import pytest
from memedogV2.hardfilter.hardfilter import HardFilter
from memedogV2.models.contracts import HardFilterResult


class FakeCli:
    def __init__(self, security, pool=None, info=None):
        self._security, self._pool, self._info = security, pool, info
        self.calls = []

    async def token_security(self, ca):
        self.calls.append("security"); return self._security

    async def token_pool(self, ca):
        self.calls.append("pool"); return self._pool

    async def token_info(self, ca):
        self.calls.append("info"); return self._info


def _cfg():
    return {
        "max_top10_pct": 35, "max_single_wallet_pct": 20, "max_dev_pct": 10,
        "max_sniper_count": 50, "max_fresh_wallet_pct": 60, "max_bundler_pct": 30,
        "serial_token_count_threshold": 5, "min_graduation_rate_for_serial": 0.0,
        "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0,
    }


@pytest.mark.asyncio
async def test_security_failure_short_circuits():
    # mint not revoked -> drop after security; pool/info never called
    cli = FakeCli(security={"security": {"renounced": {"mint": False, "freeze": True}}})
    hf = HardFilter(cli=cli, cfg=_cfg())
    res = await hf.evaluate("CA", "LP")
    assert isinstance(res, HardFilterResult)
    assert res.passed is False
    assert cli.calls == ["security"]
    assert any("mint" in d for d in res.dropped)


@pytest.mark.asyncio
async def test_clean_token_passes_all_three():
    cli = FakeCli(
        security={"security": {"renounced": {"mint": True, "freeze": True},
                               "top_10_holder_rate": 20, "top_holder_rate": 8,
                               "dev": {"holdings_rate": 2, "created_token_count": 1,
                                       "graduation_rate": 0.5}}},
        pool={"pool": {"burn_status": True, "lock_status": True, "liquidity": 50000}},
        info={"info": {"volume": {"m5": 5000}, "txns": {"m5": {"buys": 30, "sells": 10}},
                       "fdv": 100000}},
    )
    hf = HardFilter(cli=cli, cfg=_cfg())
    res = await hf.evaluate("CA", "LP")
    assert res.passed is True
    assert cli.calls == ["security", "pool", "info"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_hardfilter.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/hardfilter/hardfilter.py
from __future__ import annotations

from memedogV2.clients.errors import DataSourceError, RateLimitBanned
from memedogV2.hardfilter import rules as R
from memedogV2.hardfilter.fieldmap import FIELD_MAP
from memedogV2.models.contracts import HardFilterResult


class HardFilter:
    """Deterministic gate. Calls gmgn-cli in cheapest-reject order: security -> pool -> info.

    Returns a HardFilterResult; never raises for rule failures. gmgn errors are
    surfaced via on_failure policy: 'drop' (fail closed) or 'pass_flagged'.
    """

    def __init__(self, *, cli, cfg: dict, on_failure: str = "pass_flagged") -> None:
        self._cli = cli
        self._cfg = cfg
        self._on_failure = on_failure

    @staticmethod
    def _val(facts: dict, key: str):
        return R.get_path(facts, FIELD_MAP[key])

    async def evaluate(self, ca: str, lp: str, trace_id: str = "") -> HardFilterResult:
        res = HardFilterResult(ca_address=ca, lp_address=lp, trace_id=trace_id)

        # --- Stage 1: security (authorities + concentration + manipulation + dev) ---
        try:
            sec = await self._cli.token_security(ca)
        except RateLimitBanned:
            raise
        except DataSourceError as e:
            return self._on_source_error(res, "security", e)
        res.facts.update(sec)

        for ok, reason in (
            R.check_authorities(mint_revoked=self._val(res.facts, "mint_revoked"),
                                freeze_revoked=self._val(res.facts, "freeze_revoked"),
                                lp_ok=None),
            R.check_concentration(top10_pct=self._val(res.facts, "top10_pct"),
                                  single_pct=self._val(res.facts, "single_wallet_pct"),
                                  dev_pct=self._val(res.facts, "dev_pct"), cfg=self._cfg),
            R.check_manipulation(sniper_count=self._val(res.facts, "sniper_count"),
                                 fresh_pct=self._val(res.facts, "fresh_wallet_pct"),
                                 bundler_pct=self._val(res.facts, "bundler_pct"), cfg=self._cfg),
            R.check_dev_track(created=self._val(res.facts, "dev_created_count"),
                              graduation_rate=self._val(res.facts, "dev_graduation_rate"),
                              cfg=self._cfg),
        ):
            if not ok:
                res.dropped.append(reason)
                return res

        # --- Stage 2: pool (LP status + liquidity) ---
        try:
            pool = await self._cli.token_pool(ca)
        except RateLimitBanned:
            raise
        except DataSourceError as e:
            return self._on_source_error(res, "pool", e)
        res.facts.update(pool)

        lp_burned = self._val(res.facts, "lp_burned")
        lp_locked = self._val(res.facts, "lp_locked")
        lp_ok = None if lp_burned is None and lp_locked is None else bool(lp_burned or lp_locked)
        ok, reason = R.check_authorities(mint_revoked=None, freeze_revoked=None, lp_ok=lp_ok)
        if not ok:
            res.dropped.append(reason)
            return res

        # --- Stage 3: info (momentum) ---
        try:
            info = await self._cli.token_info(ca)
        except RateLimitBanned:
            raise
        except DataSourceError as e:
            return self._on_source_error(res, "info", e)
        res.facts.update(info)

        buys = self._val(res.facts, "buy_count_5m")
        sells = self._val(res.facts, "sell_count_5m")
        ratio = (buys / sells) if (buys is not None and sells) else None
        ok, reason = R.check_momentum(liquidity=self._val(res.facts, "liquidity_usd"),
                                      vol5m=self._val(res.facts, "volume_5m"),
                                      buy_sell=ratio, cfg=self._cfg)
        if not ok:
            res.dropped.append(reason)
            return res

        res.passed = True
        return res

    def _on_source_error(self, res: HardFilterResult, stage: str, exc: Exception) -> HardFilterResult:
        if self._on_failure == "drop":
            res.passed = False
            res.dropped.append(f"{stage}: source error ({exc})")
        else:  # pass_flagged
            res.passed = True
            res.flagged.append(f"{stage}: source error, passed flagged ({exc})")
        return res
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_hardfilter.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/hardfilter/hardfilter.py tests/memedogV2/test_hardfilter.py
git commit -m "feat(memedogV2): hardfilter aggregator with early-exit ordering"
```

---

## Task 6: CodexAgent (codex exec, network on, --output-schema)

**Files:**
- Create: `src/memedogV2/llm/__init__.py`, `src/memedogV2/llm/codex_agent.py`
- Create: `tests/memedogV2/test_codex_agent.py`

> Flags confirmed in Task 0 spike. Default uses `--sandbox workspace-write`; `bypass=True` switches to `--dangerously-bypass-approvals-and-sandbox` if the spike showed it was required.

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_codex_agent.py
import json
import pytest
from memedogV2.llm.codex_agent import CodexAgent


class FakeExec:
    def __init__(self, last_message):
        self._msg = last_message
        self.calls = []

    async def __call__(self, *, prompt, schema, cwd):
        self.calls.append({"prompt": prompt, "schema": schema})
        return self._msg


@pytest.mark.asyncio
async def test_run_returns_parsed_json():
    fake = FakeExec(json.dumps({"signal": "BULLISH", "recommended": True}))
    agent = CodexAgent(executor=fake)
    out = await agent.run(prompt="judge this", schema={"type": "object"})
    assert out == {"signal": "BULLISH", "recommended": True}
    assert fake.calls[0]["schema"] == {"type": "object"}


@pytest.mark.asyncio
async def test_run_raises_on_unparseable():
    fake = FakeExec("not json at all")
    agent = CodexAgent(executor=fake)
    with pytest.raises(ValueError):
        await agent.run(prompt="x", schema={"type": "object"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_codex_agent.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/llm/__init__.py
```

```python
# src/memedogV2/llm/codex_agent.py
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any, Awaitable, Callable, Optional

Executor = Callable[..., Awaitable[str]]


async def _codex_exec(*, prompt: str, schema: dict, cwd: str, bypass: bool = False) -> str:
    """Run `codex exec` with network + structured output; return last message text."""
    schema_fd, schema_path = tempfile.mkstemp(suffix=".json", prefix="v2_schema_")
    out_fd, out_path = tempfile.mkstemp(suffix=".txt", prefix="v2_out_")
    os.close(schema_fd); os.close(out_fd)
    try:
        with open(schema_path, "w") as f:
            json.dump(schema, f)
        sandbox = (["--dangerously-bypass-approvals-and-sandbox"] if bypass
                   else ["--sandbox", "workspace-write"])
        args = ["codex", "exec", *sandbox, "--skip-git-repo-check",
                "--output-schema", schema_path, "-o", out_path, prompt]
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"codex exec rc={proc.returncode}: {err.decode().strip()}")
        with open(out_path) as f:
            return f.read()
    finally:
        for p in (schema_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


class CodexAgent:
    """Thin wrapper: prompt + JSON schema -> parsed dict via codex exec."""

    def __init__(self, *, executor: Optional[Executor] = None, cwd: str = ".") -> None:
        self._exec = executor or _codex_exec
        self._cwd = cwd

    async def run(self, *, prompt: str, schema: dict) -> dict[str, Any]:
        raw = await self._exec(prompt=prompt, schema=schema, cwd=self._cwd)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"codex output not valid JSON: {raw[:200]}") from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_codex_agent.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/llm tests/memedogV2/test_codex_agent.py
git commit -m "feat(memedogV2): codex agent wrapper with output-schema"
```

---

## Task 7: EvidenceGatherer → EvidenceBundle

**Files:**
- Create: `src/memedogV2/audit/__init__.py`, `src/memedogV2/audit/evidence.py`
- Create: `tests/memedogV2/test_evidence.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_evidence.py
import pytest
from memedogV2.audit.evidence import EvidenceGatherer
from memedogV2.models.contracts import EvidenceBundle


class FakeAgent:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def run(self, *, prompt, schema):
        self.calls.append(prompt)
        return self._payload


@pytest.mark.asyncio
async def test_gather_maps_payload_into_bundle():
    agent = FakeAgent({
        "smart_money_count": 4, "kol_holder_count": 2,
        "dev_created_token_count": 1, "dev_graduation_rate": 0.5,
        "historical_ath": 1.2e6, "trend": {"m5": "up"}, "holders_detail": {"n": 100},
    })
    g = EvidenceGatherer(agent=agent, max_calls=5)
    b = await g.gather("CA")
    assert isinstance(b, EvidenceBundle)
    assert b.smart_money_count == 4 and b.kol_holder_count == 2
    assert b.missing == []


@pytest.mark.asyncio
async def test_gather_records_missing_dims():
    agent = FakeAgent({"smart_money_count": 1})  # rest absent
    g = EvidenceGatherer(agent=agent, max_calls=5)
    b = await g.gather("CA")
    assert b.smart_money_count == 1
    assert "kol_holder_count" in b.missing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_evidence.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/audit/__init__.py
```

```python
# src/memedogV2/audit/evidence.py
from __future__ import annotations

from memedogV2.models.contracts import EvidenceBundle

_EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "smart_money_count": {"type": ["integer", "null"]},
        "kol_holder_count": {"type": ["integer", "null"]},
        "dev_created_token_count": {"type": ["integer", "null"]},
        "dev_graduation_rate": {"type": ["number", "null"]},
        "historical_ath": {"type": ["number", "null"]},
        "trend": {"type": ["object", "null"]},
        "holders_detail": {"type": ["object", "null"]},
    },
    "additionalProperties": True,
}

_FIELDS = ["smart_money_count", "kol_holder_count", "dev_created_token_count",
           "dev_graduation_rate", "historical_ath", "trend", "holders_detail"]


class EvidenceGatherer:
    """One codex agent call that uses gmgn-skills to assemble a shared EvidenceBundle."""

    def __init__(self, *, agent, max_calls: int = 5) -> None:
        self._agent = agent
        self._max_calls = max_calls

    def _prompt(self, ca: str) -> str:
        return (
            "Use the gmgn-track, gmgn-market, and gmgn-token skills to investigate "
            f"Solana token {ca}. You may run at most {self._max_calls} gmgn-cli calls total. "
            "Collect: smart_money_count, kol_holder_count, dev_created_token_count, "
            "dev_graduation_rate, historical_ath, trend, holders_detail. "
            "Return them as JSON; use null for anything you could not fetch."
        )

    async def gather(self, ca: str) -> EvidenceBundle:
        payload = await self._agent.run(prompt=self._prompt(ca), schema=_EVIDENCE_SCHEMA)
        data = {k: payload.get(k) for k in _FIELDS}
        missing = [k for k in _FIELDS if data.get(k) is None]
        return EvidenceBundle(ca_address=ca, missing=missing, **data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_evidence.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/audit/__init__.py src/memedogV2/audit/evidence.py tests/memedogV2/test_evidence.py
git commit -m "feat(memedogV2): evidence gatherer -> shared EvidenceBundle"
```

---

## Task 8: BullBearJudge → Signal

**Files:**
- Create: `src/memedogV2/audit/debate.py`
- Create: `tests/memedogV2/test_debate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_debate.py
import pytest
from memedogV2.audit.debate import BullBearJudge
from memedogV2.models.contracts import EvidenceBundle, Signal, SignalKind


class ScriptedAgent:
    """Returns queued payloads in order (bull, bear, judge)."""
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.prompts = []

    async def run(self, *, prompt, schema):
        self.prompts.append(prompt)
        return self._payloads.pop(0)


@pytest.mark.asyncio
async def test_debate_produces_recommended_signal():
    agent = ScriptedAgent([
        {"thesis": "smart money in", "points": ["4 smart wallets"]},
        {"thesis": "thin liquidity risk", "points": ["fresh wallets high"]},
        {"signal": "BULLISH", "recommended": True, "confidence": 0.72,
         "rationale": "smart money outweighs risk", "evidence_refs": ["smart_money_count"]},
    ])
    jbj = BullBearJudge(agent=agent)
    bundle = EvidenceBundle(ca_address="CA", smart_money_count=4)
    sig = await jbj.decide(bundle)
    assert isinstance(sig, Signal)
    assert sig.signal is SignalKind.BULLISH and sig.recommended is True
    assert sig.confidence == 0.72
    assert len(agent.prompts) == 3        # bull, bear, judge order
    assert "bull" in agent.prompts[0].lower()
    assert "bear" in agent.prompts[1].lower()


@pytest.mark.asyncio
async def test_bundle_missing_dims_flow_into_judge_prompt():
    agent = ScriptedAgent([
        {"thesis": "ok", "points": []},
        {"thesis": "ok", "points": []},
        {"signal": "NEUTRAL", "recommended": False, "confidence": 0.4,
         "rationale": "insufficient evidence", "evidence_refs": []},
    ])
    jbj = BullBearJudge(agent=agent)
    bundle = EvidenceBundle(ca_address="CA", missing=["kol_holder_count"])
    sig = await jbj.decide(bundle)
    assert sig.signal is SignalKind.NEUTRAL and sig.recommended is False
    assert "kol_holder_count" in agent.prompts[2]   # missing dims surfaced to judge
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_debate.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/audit/debate.py
from __future__ import annotations

import json

from memedogV2.models.contracts import EvidenceBundle, Signal, SignalKind

_ANALYST_SCHEMA = {
    "type": "object",
    "properties": {"thesis": {"type": "string"},
                   "points": {"type": "array", "items": {"type": "string"}}},
    "required": ["thesis"], "additionalProperties": True,
}

_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "signal": {"type": "string", "enum": ["BULLISH", "BEARISH", "NEUTRAL"]},
        "recommended": {"type": "boolean"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["signal", "recommended", "confidence", "rationale"],
    "additionalProperties": True,
}


class BullBearJudge:
    """Bull + Bear read one shared EvidenceBundle; Judge合议 -> Signal."""

    def __init__(self, *, agent) -> None:
        self._agent = agent

    @staticmethod
    def _evidence_text(b: EvidenceBundle) -> str:
        body = b.model_dump()
        missing = body.pop("missing", [])
        return (f"Evidence for {b.ca_address}: {json.dumps(body)}\n"
                f"Missing/unfetched dimensions: {missing}")

    async def decide(self, bundle: EvidenceBundle) -> Signal:
        ev = self._evidence_text(bundle)

        bull = await self._agent.run(
            prompt=f"You are the BULL analyst. Argue why this token could pump. {ev}",
            schema=_ANALYST_SCHEMA)
        bear = await self._agent.run(
            prompt=f"You are the BEAR analyst. Argue why this token is risky/avoid. {ev}",
            schema=_ANALYST_SCHEMA)

        judge = await self._agent.run(
            prompt=(
                "You are the JUDGE. Weigh the bull vs bear and decide.\n"
                f"{ev}\n"
                f"BULL: {json.dumps(bull)}\n"
                f"BEAR: {json.dumps(bear)}\n"
                "Output signal (BULLISH/BEARISH/NEUTRAL), recommended (bool), "
                "confidence 0-1, rationale, evidence_refs. If key evidence is missing, "
                "lower confidence and say so."
            ),
            schema=_JUDGE_SCHEMA)

        return Signal(
            ca_address=bundle.ca_address,
            signal=SignalKind(judge["signal"]),
            recommended=bool(judge["recommended"]),
            confidence=float(judge["confidence"]),
            rationale=str(judge["rationale"]),
            evidence_refs=list(judge.get("evidence_refs", [])),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_debate.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/audit/debate.py tests/memedogV2/test_debate.py
git commit -m "feat(memedogV2): bull/bear/judge debate -> Signal"
```

---

## Task 9: AddressIntake queue (drain-rate limited)

**Files:**
- Create: `src/memedogV2/intake.py`
- Create: `tests/memedogV2/test_intake.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_intake.py
import pytest
from memedogV2.intake import AddressIntake


@pytest.mark.asyncio
async def test_enqueue_then_drain_one():
    q = AddressIntake()
    tid = q.enqueue("CA1", "LP1")
    assert isinstance(tid, str) and tid
    item = await q.get()
    assert item.ca_address == "CA1" and item.lp_address == "LP1"
    assert item.trace_id == tid


@pytest.mark.asyncio
async def test_dedup_same_ca_not_queued_twice():
    q = AddressIntake()
    q.enqueue("CA1", "LP1")
    q.enqueue("CA1", "LP1")     # duplicate ignored
    assert q.size() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_intake.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/intake.py
from __future__ import annotations

import asyncio
import uuid

from pydantic import BaseModel


class IntakeItem(BaseModel):
    ca_address: str
    lp_address: str
    trace_id: str


class AddressIntake:
    """Event-driven (ca, lp) queue with dedup. Drain pacing is the orchestrator's job
    (via the shared gmgn rate limiter); this just buffers and dedups bursts."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[IntakeItem] = asyncio.Queue()
        self._seen: set[str] = set()

    def enqueue(self, ca_address: str, lp_address: str) -> str:
        if ca_address in self._seen:
            return ""
        self._seen.add(ca_address)
        tid = uuid.uuid4().hex[:12]
        self._q.put_nowait(IntakeItem(ca_address=ca_address, lp_address=lp_address, trace_id=tid))
        return tid

    async def get(self) -> IntakeItem:
        return await self._q.get()

    def size(self) -> int:
        return self._q.qsize()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_intake.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/intake.py tests/memedogV2/test_intake.py
git commit -m "feat(memedogV2): address intake queue with dedup"
```

---

## Task 10: V2Orchestrator (intake → hardfilter → audit)

**Files:**
- Create: `src/memedogV2/orchestrator.py`
- Create: `tests/memedogV2/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_orchestrator.py
import pytest
from memedogV2.orchestrator import V2Orchestrator
from memedogV2.models.contracts import HardFilterResult, Signal, SignalKind


class FakeHF:
    def __init__(self, passed):
        self._passed = passed
        self.seen = []

    async def evaluate(self, ca, lp, trace_id=""):
        self.seen.append(ca)
        return HardFilterResult(ca_address=ca, lp_address=lp, passed=self._passed,
                                trace_id=trace_id)


class FakeAudit:
    def __init__(self):
        self.audited = []

    async def run(self, hf_result):
        self.audited.append(hf_result.ca_address)
        return Signal(ca_address=hf_result.ca_address, signal=SignalKind.BULLISH,
                      recommended=True, confidence=0.6, rationale="ok")


@pytest.mark.asyncio
async def test_dropped_candidate_skips_audit():
    hf, audit = FakeHF(passed=False), FakeAudit()
    orch = V2Orchestrator(hardfilter=hf, audit=audit)
    sig = await orch.process("CA", "LP")
    assert sig is None
    assert audit.audited == []


@pytest.mark.asyncio
async def test_passed_candidate_gets_signal():
    hf, audit = FakeHF(passed=True), FakeAudit()
    orch = V2Orchestrator(hardfilter=hf, audit=audit)
    sig = await orch.process("CA", "LP")
    assert sig is not None and sig.recommended is True
    assert audit.audited == ["CA"]


@pytest.mark.asyncio
async def test_process_never_raises_on_audit_error():
    class BoomAudit:
        async def run(self, hf_result):
            raise RuntimeError("audit down")
    orch = V2Orchestrator(hardfilter=FakeHF(passed=True), audit=BoomAudit())
    sig = await orch.process("CA", "LP")     # swallowed
    assert sig is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/orchestrator.py
from __future__ import annotations

import logging
from typing import Optional

from memedogV2.clients.errors import RateLimitBanned
from memedogV2.models.contracts import Signal

logger = logging.getLogger(__name__)


class AuditPipeline:
    """Adapter: HardFilterResult -> EvidenceGatherer -> BullBearJudge -> Signal."""

    def __init__(self, *, gatherer, judge) -> None:
        self._gatherer = gatherer
        self._judge = judge

    async def run(self, hf_result) -> Signal:
        bundle = await self._gatherer.gather(hf_result.ca_address)
        sig = await self._judge.decide(bundle)
        sig.trace_id = hf_result.trace_id
        return sig


class V2Orchestrator:
    """One-shot per address: hardfilter gate, then audit survivors. Never raises."""

    def __init__(self, *, hardfilter, audit) -> None:
        self._hf = hardfilter
        self._audit = audit

    async def process(self, ca: str, lp: str, trace_id: str = "") -> Optional[Signal]:
        try:
            hf = await self._hf.evaluate(ca, lp, trace_id=trace_id)
        except RateLimitBanned as e:
            logger.warning("gmgn rate-limit ban for %s until %s; skipping", ca, e.reset_at)
            return None
        except Exception as e:
            logger.warning("hardfilter error for %s: %s", ca, e)
            return None

        if not hf.passed:
            logger.info("hardfilter dropped %s: %s", ca, hf.dropped)
            return None

        try:
            return await self._audit.run(hf)
        except Exception as e:
            logger.warning("audit error for %s: %s", ca, e)
            return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_orchestrator.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/orchestrator.py tests/memedogV2/test_orchestrator.py
git commit -m "feat(memedogV2): orchestrator wiring hardfilter -> audit"
```

---

## Task 11: V2Config + thresholds + assembly wiring

**Files:**
- Create: `src/memedogV2/config.py`
- Create: `src/memedogV2/config_thresholds.yaml`
- Create: `tests/memedogV2/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_config.py
from memedogV2.config import load_v2_config


def test_loads_defaults_and_hardfilter_section(tmp_path):
    yaml_path = tmp_path / "t.yaml"
    yaml_path.write_text(
        "gmgn:\n"
        "  rate_limit_rps: 1.0\n"
        "  cache_ttl_sec: 60\n"
        "  max_evidence_calls: 5\n"
        "  on_failure: pass_flagged\n"
        "hardfilter:\n"
        "  max_top10_pct: 35\n"
        "  max_single_wallet_pct: 20\n"
        "  max_dev_pct: 10\n"
        "  max_sniper_count: 50\n"
        "  max_fresh_wallet_pct: 60\n"
        "  max_bundler_pct: 30\n"
        "  serial_token_count_threshold: 5\n"
        "  min_graduation_rate_for_serial: 0.0\n"
        "  min_liquidity_usd: 20000\n"
        "  min_volume_5m: 1000\n"
        "  min_buy_sell_ratio_5m: 1.0\n"
    )
    cfg = load_v2_config(str(yaml_path))
    assert cfg.gmgn["rate_limit_rps"] == 1.0
    assert cfg.hardfilter["max_top10_pct"] == 35
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/config.py
from __future__ import annotations

import yaml
from pydantic import BaseModel


class V2Config(BaseModel):
    gmgn: dict
    hardfilter: dict


def load_v2_config(path: str) -> V2Config:
    with open(path) as f:
        data = yaml.safe_load(f)
    return V2Config(gmgn=data["gmgn"], hardfilter=data["hardfilter"])
```

```yaml
# src/memedogV2/config_thresholds.yaml
gmgn:
  rate_limit_rps: 1.0          # conservative; calibrate from Task 0 spike
  cache_ttl_sec: 60
  max_evidence_calls: 5
  intake_drain_rps: 0.5
  on_failure: pass_flagged     # drop | pass_flagged
  on_429: suspend_until_reset
hardfilter:
  require_mint_revoked: true
  require_freeze_revoked: true
  require_lp_burned_or_locked: true
  max_top10_pct: 35
  max_single_wallet_pct: 20
  max_dev_pct: 10
  max_sniper_count: 50         # calibrate from real data
  max_fresh_wallet_pct: 60     # calibrate from real data
  max_bundler_pct: 30          # calibrate from real data
  serial_token_count_threshold: 5
  min_graduation_rate_for_serial: 0.0
  min_liquidity_usd: 20000
  min_volume_5m: 1000
  min_buy_sell_ratio_5m: 1.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/config.py src/memedogV2/config_thresholds.yaml tests/memedogV2/test_config.py
git commit -m "feat(memedogV2): config loader + thresholds defaults"
```

---

## Task 12: End-to-end smoke (mocked) + manual run script

**Files:**
- Create: `src/memedogV2/__main__.py`
- Create: `tests/memedogV2/test_e2e_mocked.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_e2e_mocked.py
import json
import pytest
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.hardfilter.hardfilter import HardFilter
from memedogV2.audit.evidence import EvidenceGatherer
from memedogV2.audit.debate import BullBearJudge
from memedogV2.orchestrator import V2Orchestrator, AuditPipeline


CLEAN = {
    "token:security:CA": {"security": {"renounced": {"mint": True, "freeze": True},
                          "top_10_holder_rate": 20, "top_holder_rate": 8,
                          "dev": {"holdings_rate": 2, "created_token_count": 1,
                                  "graduation_rate": 0.5}}},
    "token:pool:CA": {"pool": {"burn_status": True, "lock_status": True, "liquidity": 50000}},
    "token:info:CA": {"info": {"volume": {"m5": 5000}, "txns": {"m5": {"buys": 30, "sells": 10}},
                      "fdv": 100000}},
}


def make_runner():
    async def runner(args):
        sub = f"{args[0]}:{args[1]}:{args[5]}"   # token:<sub>:<CA>
        return (0, json.dumps(CLEAN[sub]), "")
    return runner


class StubAgent:
    async def run(self, *, prompt, schema):
        if "BULL" in prompt:
            return {"thesis": "smart money", "points": []}
        if "BEAR" in prompt:
            return {"thesis": "risks", "points": []}
        if "JUDGE" in prompt:
            return {"signal": "BULLISH", "recommended": True, "confidence": 0.7,
                    "rationale": "net positive", "evidence_refs": ["smart_money_count"]}
        return {"smart_money_count": 4, "kol_holder_count": 2}   # evidence call


@pytest.mark.asyncio
async def test_clean_token_flows_to_recommended_signal():
    cfg = {
        "max_top10_pct": 35, "max_single_wallet_pct": 20, "max_dev_pct": 10,
        "max_sniper_count": 50, "max_fresh_wallet_pct": 60, "max_bundler_pct": 30,
        "serial_token_count_threshold": 5, "min_graduation_rate_for_serial": 0.0,
        "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0,
    }
    cli = GmgnCli(runner=make_runner(), rate_per_sec=1000, capacity=10, cache_ttl_sec=60)
    hf = HardFilter(cli=cli, cfg=cfg)
    audit = AuditPipeline(
        gatherer=EvidenceGatherer(agent=StubAgent(), max_calls=5),
        judge=BullBearJudge(agent=StubAgent()),
    )
    orch = V2Orchestrator(hardfilter=hf, audit=audit)
    sig = await orch.process("CA", "LP")
    assert sig is not None
    assert sig.recommended is True and sig.signal.value == "BULLISH"
```

- [ ] **Step 2: Run the test (integration smoke — confirms wiring)**

Run: `pytest tests/memedogV2/test_e2e_mocked.py -v`
This is an integration test over already-built units (Tasks 1–10). It may PASS immediately if every contract lines up — that passing IS the validation. If it FAILS, the failure pinpoints a wiring/contract mismatch between two units; fix the offending unit before continuing. (`__main__.py` in Step 3 is exercised manually in Task 13, not by this test.)

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/__main__.py
"""Manual entrypoint: process one (CA, LP) through the real pipeline.

Usage: python -m memedogV2 <CA> <LP>
Requires GMGN_API_KEY in env and gmgn-skills installed in codex (see Task 0).
"""
from __future__ import annotations

import asyncio
import os
import sys

from memedogV2.audit.debate import BullBearJudge
from memedogV2.audit.evidence import EvidenceGatherer
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.config import load_v2_config
from memedogV2.hardfilter.hardfilter import HardFilter
from memedogV2.llm.codex_agent import CodexAgent
from memedogV2.orchestrator import AuditPipeline, V2Orchestrator

_CFG = os.path.join(os.path.dirname(__file__), "config_thresholds.yaml")


async def _main(ca: str, lp: str) -> None:
    cfg = load_v2_config(_CFG)
    cli = GmgnCli(rate_per_sec=cfg.gmgn["rate_limit_rps"], capacity=1,
                  cache_ttl_sec=cfg.gmgn["cache_ttl_sec"])
    hf = HardFilter(cli=cli, cfg=cfg.hardfilter, on_failure=cfg.gmgn["on_failure"])
    agent = CodexAgent(cwd=os.getcwd())
    audit = AuditPipeline(
        gatherer=EvidenceGatherer(agent=agent, max_calls=cfg.gmgn["max_evidence_calls"]),
        judge=BullBearJudge(agent=agent),
    )
    orch = V2Orchestrator(hardfilter=hf, audit=audit)
    sig = await orch.process(ca, lp)
    print(sig.model_dump_json(indent=2) if sig else "DROPPED or no signal")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python -m memedogV2 <CA> <LP>"); sys.exit(2)
    asyncio.run(_main(sys.argv[1], sys.argv[2]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_e2e_mocked.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full memedogV2 suite**

Run: `pytest tests/memedogV2 -v`
Expected: ALL PASS. Confirm `tests/memedog` (old) is untouched: `pytest tests/memedog -q` still passes.

- [ ] **Step 6: Commit**

```bash
git add src/memedogV2/__main__.py tests/memedogV2/test_e2e_mocked.py
git commit -m "feat(memedogV2): mocked end-to-end smoke + manual entrypoint"
```

---

## Task 13: Live smoke (manual, real gmgn + codex — optional, rate-limit-aware)

**Goal:** Run one real `(CA, LP)` through `python -m memedogV2` end to end. This is manual validation, not CI.

- [ ] **Step 1: Confirm prerequisites**: `GMGN_API_KEY` set, gmgn-skills installed in codex (Task 0), `codex login` valid.
- [ ] **Step 2: Run once on a known live token**

```bash
python -m memedogV2 <REAL_CA> <REAL_LP>
```

Expected: either `DROPPED` with a red-line reason, or a `Signal` JSON with `recommended`. Watch for 429 — if seen, stop and wait 5 min (do not loop).

- [ ] **Step 3: Record result** in the spec's "13. 开放风险" section (field-map corrections, rate-limit observations). If `FIELD_MAP` paths were wrong, fix `fieldmap.py` and re-run Task 5 tests.

```bash
git add -A && git commit -m "chore(memedogV2): live smoke notes + field-map corrections"
```

---

## Self-Review Notes

- **Spec coverage:** §3 funnel → Tasks 9/5/7/8/10; §4.2 gmgn_cli + 3-command order → Tasks 3/5; §4.3 shared evidence + bull/bear/judge → Tasks 7/8; §4.4 codex network+schema → Task 6; §4.5 reuse → noted (paper/dashboard/alert wiring left to live integration, out of this plan's core); §5 contracts → Task 1; §6 rate-limit budget → Tasks 2/3 + intake Task 9; §7 config → Task 11; §8 degradation → Tasks 3/5/10; §10 spike → Task 0; §12 testing → all tasks mocked, no network.
- **FIELD_MAP** is the single point of unknown gmgn JSON paths, confirmed by Task 0 fixtures and Task 13 live run — by design, not a placeholder.
- **PaperTrader/Dashboard/Alert reuse** (§4.5) is intentionally deferred: this plan delivers a working address→Signal pipeline; wiring Signal into the existing paper trader is a small follow-up once the core is green.
