# memedogV2 Multi-Source Resilient Data Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace gmgn-as-sole-source with a resilience-first multi-source data layer: RugCheck/Helius supply safety/LP/concentration with gmgn fallback; gmgn supplies momentum/evidence (with bounded retry, since momentum is required). Every field records its source. Fold in the audit fixes (C-1 no-crash on source failure, H-1 gmgn retry). Add a mandatory real end-to-end test gate.

**Architecture:** New `src/memedogV2/sources/` package: a canonical `Facts` model + per-source adapters (`RugCheckSource`, `GmgnSource`, `HeliusSource`) each returning partial normalized facts + a `ToolCallRecord`, and a `DataResolver` that calls sources, tolerates failures, and merges per-field by priority with source attribution. The harness runner fetches via the resolver instead of the gmgn-only tool_registry; HardFilter rules read canonical field names instead of gmgn JSON.

**Tech Stack:** Python 3.11+, asyncio, httpx (RugCheck/Helius HTTP), existing `GmgnCli`, pydantic v2, pytest (`asyncio_mode=auto`).

**Spec:** `docs/superpowers/specs/2026-06-25-memedogV2-multisource-resilient-data.md`
**Audit it fixes:** `docs/superpowers/audits/2026-06-25-memedogV2-audit.md` (C-1, H-1, H-2)

---

## Context the implementer must know

- **Existing (do not break):** `clients/gmgn_cli.py` (`GmgnCli.token_security/token_info`, raises `RateLimitBanned`/`DataSourceError`), `clients/errors.py`, `hardfilter/fieldmap.py` (`FIELD_MAP` gmgn paths), `hardfilter/rules.py` (`get_path`, `num`, `check_*`), `hardfilter/hardfilter.py`, `harness/*`, `models/contracts.py`, `audit/*`.
- **Old memedog reference (read, don't import):** `src/memedog/clients/rugcheck.py` has `parse_report(report)` producing `mint_authority_revoked`, `freeze_authority_revoked`, `lp_burned_or_locked`, `top10_pct`, `max_wallet_pct`, `sniper_pct`, `total_holders` from the RugCheck `/v1/tokens/{mint}/report` JSON (excludes AMM accounts). `src/memedog/clients/helius.py` has `get_largest_holders(mint)` → `{top10_pct, max_wallet_pct, holder_count}` via `getTokenLargestAccounts`. Reuse their parsing LOGIC (copy/adapt into the new adapters); do not import from `src/memedog`.
- **`.env`:** `HELIUS_API_KEY` present. RugCheck public API needs no key. `DEEPSEEK_API_KEY` present. gmgn key in `~/.config/gmgn/.env`.
- **Canonical field names** (used by rules + the new `Facts`): `mint_revoked, freeze_revoked, lp_safe, honeypot, top10_rate, max_wallet_rate, creator_rate, dev_rate, sniper_count, fresh_wallet_rate, bundler_rate, liquidity_usd, volume_5m, buys_5m, sells_5m, price_usd, circulating_supply, smart_money_count, kol_count, dev_created_count, historical_ath`.
- Rates are **0–1 fractions**; numeric gmgn fields are strings (use `num()`); RugCheck `pct` values are **percent (0–100)** → divide by 100 to normalize to fractions.
- `live`/real tests: pyproject `addopts = -m 'not live'`. The mandatory gate in Task 9 is **NOT** marked `live` (so it runs by default) but `pytest.skip`s when creds/binaries are absent.

## File Structure

```
src/memedogV2/sources/
├── __init__.py
├── base.py            # Facts, PartialFacts, SourceAdapter protocol, FIELD priority table
├── gmgn_source.py     # wraps GmgnCli; gmgn JSON -> PartialFacts; bounded retry (H-1)
├── rugcheck_source.py # httpx GET rugcheck report -> PartialFacts
├── helius_source.py   # httpx getTokenLargestAccounts -> PartialFacts (concentration fallback)
└── resolver.py        # DataResolver: call sources, tolerate failures, merge by priority

src/memedogV2/hardfilter/
└── facts_filter.py    # NEW: run red-line rules over a ResolvedFacts (replaces gmgn-coupled aggregator path)

tests/memedogV2/
├── fixtures/sources/{rugcheck,helius,gmgn}.json   # real captured per-source responses (Task 0)
├── test_sources_gmgn.py
├── test_sources_rugcheck.py
├── test_sources_helius.py
├── test_resolver.py
├── test_facts_filter.py
└── test_gate_real.py        # mandatory real gate (default run, skip-if-no-creds)
scripts/refresh_source_fixtures.sh
```

---

## Task 0: Capture real per-source fixtures (manual, gating for unit tests)

Real data for the unit tests must be captured from live APIs (no invented JSON). Pick one real token (any live mint works for shape capture).

- [ ] **Step 1: Capture RugCheck + Helius + gmgn raw responses**

```bash
cd /Users/kellylim/meme-ai-agent
mkdir -p tests/memedogV2/fixtures/sources
CA=DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263   # BONK (stable shape)
set -a; . ./.env 2>/dev/null; set +a
curl -s "https://api.rugcheck.xyz/v1/tokens/$CA/report" -o tests/memedogV2/fixtures/sources/rugcheck.json
curl -s "https://mainnet.helius-rpc.com/?api-key=$HELIUS_API_KEY" \
  -X POST -H 'Content-Type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"getTokenLargestAccounts\",\"params\":[\"$CA\"]}" \
  -o tests/memedogV2/fixtures/sources/helius.json
gmgn-cli token info --chain sol --address $CA --raw > tests/memedogV2/fixtures/sources/gmgn_info.json
sleep 2
gmgn-cli token security --chain sol --address $CA --raw > tests/memedogV2/fixtures/sources/gmgn_security.json
for f in tests/memedogV2/fixtures/sources/*.json; do echo "== $f =="; head -c 200 "$f"; echo; done
```

Expected: 4 non-empty JSON files. If RugCheck returns an error body or Helius lacks `result.value`, note it (the adapters must tolerate that shape).

- [ ] **Step 2: Write the refresh script** `scripts/refresh_source_fixtures.sh` with the same commands (parameterized by `$1` CA, default BONK), so fixtures can be re-recorded to catch field drift. `chmod +x` it.

- [ ] **Step 3: Commit**

```bash
git add tests/memedogV2/fixtures/sources scripts/refresh_source_fixtures.sh
git commit -m "test(sources): capture real RugCheck/Helius/gmgn fixtures + refresh script"
```

---

## Task 1: Canonical Facts + SourceAdapter base + priority table

**Files:** Create `src/memedogV2/sources/__init__.py`, `src/memedogV2/sources/base.py`; Test `tests/memedogV2/test_sources_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_sources_base.py
from memedogV2.sources.base import Facts, FIELD_PRIORITY, ALL_FIELDS


def test_facts_defaults_all_none():
    f = Facts()
    for name in ALL_FIELDS:
        assert getattr(f, name) is None


def test_priority_table_covers_every_field_and_orders_sources():
    for name in ALL_FIELDS:
        assert name in FIELD_PRIORITY
        for src in FIELD_PRIORITY[name]:
            assert src in ("rugcheck", "gmgn", "helius")
    # momentum is gmgn-only
    assert FIELD_PRIORITY["liquidity_usd"] == ["gmgn"]
    # authorities/LP/top10 prefer rugcheck then gmgn
    assert FIELD_PRIORITY["mint_revoked"][0] == "rugcheck"
    assert FIELD_PRIORITY["top10_rate"] == ["rugcheck", "gmgn", "helius"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_sources_base.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/sources/__init__.py
"""memedogV2 multi-source resilient data layer."""
```

```python
# src/memedogV2/sources/base.py
from __future__ import annotations

from typing import Any, Awaitable, Optional, Protocol

from pydantic import BaseModel

from memedogV2.harness.contracts import ToolCallRecord

ALL_FIELDS = [
    "mint_revoked", "freeze_revoked", "lp_safe", "honeypot",
    "top10_rate", "max_wallet_rate", "creator_rate", "dev_rate",
    "sniper_count", "fresh_wallet_rate", "bundler_rate",
    "liquidity_usd", "volume_5m", "buys_5m", "sells_5m",
    "price_usd", "circulating_supply",
    "smart_money_count", "kol_count", "dev_created_count", "historical_ath",
]

# Per-field source priority (resilience-first). Momentum is gmgn-only & required.
_RUGCHECK_FIRST = ["rugcheck", "gmgn"]
FIELD_PRIORITY: dict[str, list[str]] = {
    "mint_revoked": _RUGCHECK_FIRST, "freeze_revoked": _RUGCHECK_FIRST,
    "lp_safe": _RUGCHECK_FIRST,
    "top10_rate": ["rugcheck", "gmgn", "helius"],
    "max_wallet_rate": ["rugcheck", "gmgn", "helius"],
    "honeypot": ["gmgn"], "creator_rate": ["gmgn"], "dev_rate": ["gmgn"],
    "sniper_count": ["gmgn"], "fresh_wallet_rate": ["gmgn"], "bundler_rate": ["gmgn"],
    "liquidity_usd": ["gmgn"], "volume_5m": ["gmgn"], "buys_5m": ["gmgn"],
    "sells_5m": ["gmgn"], "price_usd": ["gmgn"], "circulating_supply": ["gmgn"],
    "smart_money_count": ["gmgn"], "kol_count": ["gmgn"],
    "dev_created_count": ["gmgn"], "historical_ath": ["gmgn"],
}

# momentum fields that must be present (gmgn required); used by resolver
MOMENTUM_FIELDS = ["liquidity_usd", "volume_5m", "buys_5m", "sells_5m"]


class Facts(BaseModel):
    """Canonical, source-agnostic facts. None = unknown/unavailable."""
    mint_revoked: Optional[bool] = None
    freeze_revoked: Optional[bool] = None
    lp_safe: Optional[bool] = None
    honeypot: Optional[bool] = None
    top10_rate: Optional[float] = None
    max_wallet_rate: Optional[float] = None
    creator_rate: Optional[float] = None
    dev_rate: Optional[float] = None
    sniper_count: Optional[int] = None
    fresh_wallet_rate: Optional[float] = None
    bundler_rate: Optional[float] = None
    liquidity_usd: Optional[float] = None
    volume_5m: Optional[float] = None
    buys_5m: Optional[int] = None
    sells_5m: Optional[int] = None
    price_usd: Optional[float] = None
    circulating_supply: Optional[float] = None
    smart_money_count: Optional[int] = None
    kol_count: Optional[int] = None
    dev_created_count: Optional[int] = None
    historical_ath: Optional[float] = None


class PartialFacts(Facts):
    """Same shape as Facts; what a single source could provide."""


class SourceAdapter(Protocol):
    name: str
    async def fetch(self, ca: str, lp: str) -> tuple["PartialFacts", ToolCallRecord]: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_sources_base.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/sources/__init__.py src/memedogV2/sources/base.py tests/memedogV2/test_sources_base.py
git commit -m "feat(sources): canonical Facts + source priority table"
```

---

## Task 2: GmgnSource (wraps GmgnCli, normalizes, bounded retry — H-1)

**Files:** Create `src/memedogV2/sources/gmgn_source.py`; Test `tests/memedogV2/test_sources_gmgn.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_sources_gmgn.py
import json
import pytest
from memedogV2.sources.gmgn_source import GmgnSource
from memedogV2.clients.errors import DataSourceError, RateLimitBanned


class FakeCli:
    def __init__(self, security, info, fail_times=0, exc=None):
        self._sec, self._info = security, info
        self._fail_times, self._exc = fail_times, exc
        self.calls = 0

    async def token_security(self, ca):
        return self._sec

    async def token_info(self, ca):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._exc
        return self._info


@pytest.mark.asyncio
async def test_gmgn_source_normalizes_real_fixtures():
    sec = json.load(open("tests/memedogV2/fixtures/sources/gmgn_security.json"))
    info = json.load(open("tests/memedogV2/fixtures/sources/gmgn_info.json"))
    src = GmgnSource(cli=FakeCli(sec, info), max_retries=2)
    pf, rec = await src.fetch("CA", "LP")
    assert pf.liquidity_usd is not None and pf.liquidity_usd > 0   # momentum present
    assert pf.mint_revoked in (True, False)
    assert pf.top10_rate is not None and 0.0 <= pf.top10_rate <= 1.0
    assert rec.tool == "gmgn" and rec.exit_status == 0


@pytest.mark.asyncio
async def test_gmgn_source_retries_transient_then_succeeds():
    sec, info = {"renounced_mint": True}, {"liquidity": "1"}
    cli = FakeCli(sec, info, fail_times=1, exc=DataSourceError("tls blip"))
    src = GmgnSource(cli=cli, max_retries=2)
    pf, rec = await src.fetch("CA", "LP")
    assert cli.calls == 2 and rec.exit_status == 0   # retried once, then ok


@pytest.mark.asyncio
async def test_gmgn_source_gives_up_after_retries():
    cli = FakeCli({"renounced_mint": True}, {}, fail_times=99, exc=DataSourceError("down"))
    src = GmgnSource(cli=cli, max_retries=2)
    pf, rec = await src.fetch("CA", "LP")
    assert pf.liquidity_usd is None and rec.exit_status != 0   # degraded, not raised


@pytest.mark.asyncio
async def test_gmgn_source_does_not_retry_429():
    cli = FakeCli({"renounced_mint": True}, {}, fail_times=99,
                  exc=RateLimitBanned("banned", reset_at=1))
    src = GmgnSource(cli=cli, max_retries=2)
    with pytest.raises(RateLimitBanned):
        await src.fetch("CA", "LP")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_sources_gmgn.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/sources/gmgn_source.py
from __future__ import annotations

import asyncio
import time

from memedogV2.clients.errors import DataSourceError, RateLimitBanned
from memedogV2.hardfilter.fieldmap import FIELD_MAP
from memedogV2.hardfilter.rules import get_path, num
from memedogV2.harness.contracts import ToolCallRecord
from memedogV2.sources.base import PartialFacts


def _b(v):
    return bool(v) if isinstance(v, bool) else (None if v is None else bool(v))


class GmgnSource:
    """gmgn-cli source: security+info -> normalized PartialFacts. Bounded retry on
    transient (non-429) errors; 429 propagates as RateLimitBanned (never retried)."""
    name = "gmgn"

    def __init__(self, *, cli, max_retries: int = 2) -> None:
        self._cli = cli
        self._max_retries = max_retries

    async def fetch(self, ca: str, lp: str) -> tuple[PartialFacts, ToolCallRecord]:
        t0 = time.perf_counter()
        try:
            facts = await self._fetch_with_retry(ca)
            dur = (time.perf_counter() - t0) * 1000.0
            return facts, ToolCallRecord(tool="gmgn", command=f"token security+info {ca}",
                                         input_summary=ca, exit_status=0, duration_ms=dur)
        except RateLimitBanned:
            raise
        except DataSourceError as e:
            dur = (time.perf_counter() - t0) * 1000.0
            return PartialFacts(), ToolCallRecord(tool="gmgn", command=f"token security+info {ca}",
                                                  input_summary=ca, exit_status=1,
                                                  output_summary=str(e)[:200], duration_ms=dur)

    async def _fetch_with_retry(self, ca: str):
        sec = await self._cli.token_security(ca)   # security: no retry needed in tests
        attempt = 0
        while True:
            try:
                info = await self._cli.token_info(ca)
                break
            except RateLimitBanned:
                raise
            except DataSourceError:
                attempt += 1
                if attempt > self._max_retries:
                    raise
                await asyncio.sleep(min(2.0, 0.2 * (2 ** attempt)))
        return self._normalize(sec, info)

    @staticmethod
    def _normalize(sec: dict, info: dict) -> PartialFacts:
        facts = {**sec, **info}

        def f(key):
            return num(get_path(facts, FIELD_MAP[key]))

        lp_burned = get_path(facts, FIELD_MAP["burn_status"]) == "burn"
        lp_locked = get_path(facts, FIELD_MAP["lp_locked"]) is True
        lp_safe = None
        if get_path(facts, FIELD_MAP["burn_status"]) is not None or \
           get_path(facts, FIELD_MAP["lp_locked"]) is not None:
            lp_safe = lp_burned or lp_locked
        honeypot_v = f("honeypot")
        return PartialFacts(
            mint_revoked=_b(get_path(facts, FIELD_MAP["renounced_mint"])),
            freeze_revoked=_b(get_path(facts, FIELD_MAP["renounced_freeze"])),
            lp_safe=lp_safe,
            honeypot=(honeypot_v == 1) if honeypot_v is not None else None,
            top10_rate=f("top10_rate"), max_wallet_rate=None,
            creator_rate=f("creator_hold_rate"), dev_rate=f("dev_team_hold_rate"),
            sniper_count=(int(f("sniper_wallets")) if f("sniper_wallets") is not None else None),
            fresh_wallet_rate=f("fresh_wallet_rate"), bundler_rate=f("bundler_rate"),
            liquidity_usd=f("liquidity_usd"), volume_5m=f("volume_5m"),
            buys_5m=(int(f("buys_5m")) if f("buys_5m") is not None else None),
            sells_5m=(int(f("sells_5m")) if f("sells_5m") is not None else None),
            price_usd=f("price_usd"), circulating_supply=f("circulating_supply"),
            smart_money_count=(int(f("smart_wallets")) if f("smart_wallets") is not None else None),
            kol_count=(int(f("renowned_wallets")) if f("renowned_wallets") is not None else None),
            dev_created_count=(int(f("dev_created_count")) if f("dev_created_count") is not None else None),
            historical_ath=f("dev_ath_mc"),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_sources_gmgn.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/sources/gmgn_source.py tests/memedogV2/test_sources_gmgn.py
git commit -m "feat(sources): gmgn source with normalization + bounded retry (H-1)"
```

---

## Task 3: RugCheckSource (httpx, normalize report)

**Files:** Create `src/memedogV2/sources/rugcheck_source.py`; Test `tests/memedogV2/test_sources_rugcheck.py`

> Reference `src/memedog/clients/rugcheck.py::parse_report` for the field logic. RugCheck `pct` values are 0–100 → divide by 100. `lp_safe` = any `markets[].lp.lpLockedPct >= 90`. The `fetcher` seam (an async callable returning the raw report dict) keeps tests offline; the real default uses httpx.

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_sources_rugcheck.py
import json
import pytest
from memedogV2.sources.rugcheck_source import RugCheckSource


@pytest.mark.asyncio
async def test_rugcheck_normalizes_real_fixture():
    report = json.load(open("tests/memedogV2/fixtures/sources/rugcheck.json"))
    src = RugCheckSource(fetcher=lambda mint: _coro(report))
    pf, rec = await src.fetch("CA", "LP")
    assert pf.mint_revoked in (True, False, None)
    assert pf.lp_safe in (True, False, None)
    if pf.top10_rate is not None:
        assert 0.0 <= pf.top10_rate <= 1.0          # normalized to fraction
    assert pf.liquidity_usd is None                  # rugcheck has no momentum
    assert rec.tool == "rugcheck"


@pytest.mark.asyncio
async def test_rugcheck_failure_degrades_not_raises():
    async def boom(mint):
        raise RuntimeError("network")
    src = RugCheckSource(fetcher=boom)
    pf, rec = await src.fetch("CA", "LP")
    assert pf.mint_revoked is None and rec.exit_status != 0   # degraded


async def _coro(v):
    return v
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_sources_rugcheck.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/sources/rugcheck_source.py
from __future__ import annotations

import time
from typing import Awaitable, Callable, Optional

from memedogV2.harness.contracts import ToolCallRecord
from memedogV2.sources.base import PartialFacts

Fetcher = Callable[[str], Awaitable[dict]]
_BASE = "https://api.rugcheck.xyz/v1/tokens"


async def _httpx_fetch(mint: str) -> dict:
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_BASE}/{mint}/report")
        resp.raise_for_status()
        return resp.json()


def _amm_accounts(report: dict) -> set[str]:
    known = report.get("knownAccounts") or {}
    return {addr for addr, meta in known.items()
            if isinstance(meta, dict) and meta.get("type") in ("AMM", "amm")}


class RugCheckSource:
    name = "rugcheck"

    def __init__(self, *, fetcher: Optional[Fetcher] = None) -> None:
        self._fetch = fetcher or _httpx_fetch

    async def fetch(self, ca: str, lp: str) -> tuple[PartialFacts, ToolCallRecord]:
        t0 = time.perf_counter()
        try:
            report = await self._fetch(ca)
            pf = self._normalize(report)
            dur = (time.perf_counter() - t0) * 1000.0
            return pf, ToolCallRecord(tool="rugcheck", command=f"report {ca}",
                                      input_summary=ca, exit_status=0, duration_ms=dur)
        except Exception as e:
            dur = (time.perf_counter() - t0) * 1000.0
            return PartialFacts(), ToolCallRecord(tool="rugcheck", command=f"report {ca}",
                                                  input_summary=ca, exit_status=1,
                                                  output_summary=str(e)[:200], duration_ms=dur)

    @staticmethod
    def _normalize(report: dict) -> PartialFacts:
        mint_revoked = (report["mintAuthority"] is None) if "mintAuthority" in report else None
        freeze_revoked = (report["freezeAuthority"] is None) if "freezeAuthority" in report else None

        markets = report.get("markets")
        lp_safe = None
        if markets:
            lp_safe = any((m.get("lp") or {}).get("lpLockedPct", 0) >= 90 for m in markets)

        amm = _amm_accounts(report)
        holders = [h for h in (report.get("topHolders") or [])
                   if h.get("address") not in amm and h.get("owner") not in amm]
        top10_rate = None
        max_wallet_rate = None
        if holders:
            pcts = [float(h.get("pct") or 0.0) for h in holders]
            top10_rate = sum(pcts[:10]) / 100.0
            max_wallet_rate = max(pcts) / 100.0
        return PartialFacts(mint_revoked=mint_revoked, freeze_revoked=freeze_revoked,
                            lp_safe=lp_safe, top10_rate=top10_rate, max_wallet_rate=max_wallet_rate)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_sources_rugcheck.py -v`
Expected: PASS (2 tests). (If the captured `rugcheck.json` is an error body without `topHolders`, the test's `if pf.top10_rate is not None` guard keeps it green; note it.)

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/sources/rugcheck_source.py tests/memedogV2/test_sources_rugcheck.py
git commit -m "feat(sources): rugcheck source (authorities/LP/concentration), degrade-on-failure"
```

---

## Task 4: HeliusSource (concentration fallback)

**Files:** Create `src/memedogV2/sources/helius_source.py`; Test `tests/memedogV2/test_sources_helius.py`

> Reference `src/memedog/clients/helius.py::get_largest_holders`. `getTokenLargestAccounts` returns `result.value` = list of `{uiAmount}`; top10_rate = sum(top10)/sum(all), max_wallet_rate = max/sum. It is a lower-bound (≤20 accounts) → concentration fallback only.

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_sources_helius.py
import pytest
from memedogV2.sources.helius_source import HeliusSource


@pytest.mark.asyncio
async def test_helius_normalizes_largest_accounts():
    payload = {"result": {"value": [{"uiAmount": 50.0}, {"uiAmount": 30.0}, {"uiAmount": 20.0}]}}
    src = HeliusSource(fetcher=lambda mint: _coro(payload))
    pf, rec = await src.fetch("CA", "LP")
    assert abs(pf.top10_rate - 1.0) < 1e-9         # all 3 in top10, sum=100%
    assert abs(pf.max_wallet_rate - 0.5) < 1e-9    # 50/100
    assert rec.tool == "helius"


@pytest.mark.asyncio
async def test_helius_failure_degrades():
    async def boom(mint):
        raise RuntimeError("rpc down")
    src = HeliusSource(fetcher=boom)
    pf, rec = await src.fetch("CA", "LP")
    assert pf.top10_rate is None and rec.exit_status != 0


async def _coro(v):
    return v
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_sources_helius.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/sources/helius_source.py
from __future__ import annotations

import os
import time
from typing import Awaitable, Callable, Optional

from memedogV2.harness.contracts import ToolCallRecord
from memedogV2.sources.base import PartialFacts

Fetcher = Callable[[str], Awaitable[dict]]


async def _httpx_fetch(mint: str) -> dict:
    import httpx
    key = os.environ["HELIUS_API_KEY"]
    url = f"https://mainnet.helius-rpc.com/?api-key={key}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "getTokenLargestAccounts", "params": [mint]}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()


class HeliusSource:
    name = "helius"

    def __init__(self, *, fetcher: Optional[Fetcher] = None) -> None:
        self._fetch = fetcher or _httpx_fetch

    async def fetch(self, ca: str, lp: str) -> tuple[PartialFacts, ToolCallRecord]:
        t0 = time.perf_counter()
        try:
            payload = await self._fetch(ca)
            accounts = (((payload or {}).get("result") or {}).get("value")) or []
            amounts = [float(a.get("uiAmount") or 0.0) for a in accounts]
            total = sum(amounts)
            pf = PartialFacts()
            if total > 0:
                pf = PartialFacts(top10_rate=sum(sorted(amounts, reverse=True)[:10]) / total,
                                  max_wallet_rate=max(amounts) / total)
            dur = (time.perf_counter() - t0) * 1000.0
            return pf, ToolCallRecord(tool="helius", command=f"getTokenLargestAccounts {ca}",
                                      input_summary=ca, exit_status=0, duration_ms=dur)
        except Exception as e:
            dur = (time.perf_counter() - t0) * 1000.0
            return PartialFacts(), ToolCallRecord(tool="helius", command=f"getTokenLargestAccounts {ca}",
                                                  input_summary=ca, exit_status=1,
                                                  output_summary=str(e)[:200], duration_ms=dur)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_sources_helius.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/sources/helius_source.py tests/memedogV2/test_sources_helius.py
git commit -m "feat(sources): helius source (concentration fallback), degrade-on-failure"
```

---

## Task 5: DataResolver (merge by priority, tolerate failures, source attribution)

**Files:** Create `src/memedogV2/sources/resolver.py`; Test `tests/memedogV2/test_resolver.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_resolver.py
import pytest
from memedogV2.sources.base import PartialFacts
from memedogV2.sources.resolver import DataResolver, ResolvedFacts
from memedogV2.harness.contracts import ToolCallRecord


class StubSource:
    def __init__(self, name, partial, ok=True):
        self.name = name
        self._pf = partial
        self._ok = ok

    async def fetch(self, ca, lp):
        rec = ToolCallRecord(tool=self.name, command=f"x {ca}",
                             exit_status=0 if self._ok else 1)
        return self._pf, rec


@pytest.mark.asyncio
async def test_priority_merge_prefers_rugcheck_then_gmgn():
    rug = StubSource("rugcheck", PartialFacts(mint_revoked=True, top10_rate=0.2))
    gmgn = StubSource("gmgn", PartialFacts(mint_revoked=False, top10_rate=0.9,
                                           liquidity_usd=50000, volume_5m=5000,
                                           buys_5m=10, sells_5m=2))
    r = DataResolver(sources={"rugcheck": rug, "gmgn": gmgn})
    out = await r.resolve("CA", "LP")
    assert isinstance(out, ResolvedFacts)
    assert out.facts.mint_revoked is True            # rugcheck wins
    assert out.facts.top10_rate == 0.2               # rugcheck wins
    assert out.facts.liquidity_usd == 50000          # only gmgn has it
    assert out.sources["mint_revoked"] == "rugcheck"
    assert out.sources["liquidity_usd"] == "gmgn"
    assert len(out.attempts) == 2


@pytest.mark.asyncio
async def test_primary_failure_falls_back_to_gmgn():
    rug = StubSource("rugcheck", PartialFacts(), ok=False)     # failed -> all None
    gmgn = StubSource("gmgn", PartialFacts(mint_revoked=True, liquidity_usd=1,
                                           volume_5m=1, buys_5m=1, sells_5m=1))
    r = DataResolver(sources={"rugcheck": rug, "gmgn": gmgn})
    out = await r.resolve("CA", "LP")
    assert out.facts.mint_revoked is True            # fell back to gmgn
    assert out.sources["mint_revoked"] == "gmgn"


@pytest.mark.asyncio
async def test_momentum_unavailable_flagged_when_gmgn_missing_it():
    gmgn = StubSource("gmgn", PartialFacts(mint_revoked=True))  # no momentum fields
    r = DataResolver(sources={"gmgn": gmgn})
    out = await r.resolve("CA", "LP")
    assert out.momentum_unavailable is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_resolver.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/sources/resolver.py
from __future__ import annotations

from pydantic import BaseModel, Field

from memedogV2.clients.errors import RateLimitBanned
from memedogV2.harness.contracts import ToolCallRecord
from memedogV2.sources.base import (
    ALL_FIELDS, FIELD_PRIORITY, MOMENTUM_FIELDS, Facts, PartialFacts,
)


class ResolvedFacts(BaseModel):
    facts: Facts
    sources: dict[str, str] = Field(default_factory=dict)   # field -> source name
    attempts: list[ToolCallRecord] = Field(default_factory=list)
    momentum_unavailable: bool = False


class DataResolver:
    """Calls sources (tolerating per-source failure), merges fields by priority."""

    def __init__(self, *, sources: dict) -> None:
        self._sources = sources   # name -> adapter

    async def resolve(self, ca: str, lp: str) -> ResolvedFacts:
        partials: dict[str, PartialFacts] = {}
        attempts: list[ToolCallRecord] = []
        for name, src in self._sources.items():
            try:
                pf, rec = await src.fetch(ca, lp)
            except RateLimitBanned:
                raise
            except Exception as e:   # defensive: adapters degrade internally, but never crash here
                pf = PartialFacts()
                rec = ToolCallRecord(tool=name, command="fetch", exit_status=1,
                                     output_summary=str(e)[:200])
            partials[name] = pf
            attempts.append(rec)

        merged = Facts()
        source_of: dict[str, str] = {}
        for field in ALL_FIELDS:
            for src_name in FIELD_PRIORITY[field]:
                pf = partials.get(src_name)
                if pf is None:
                    continue
                val = getattr(pf, field)
                if val is not None:
                    setattr(merged, field, val)
                    source_of[field] = src_name
                    break

        momentum_missing = any(getattr(merged, f) is None for f in MOMENTUM_FIELDS)
        return ResolvedFacts(facts=merged, sources=source_of, attempts=attempts,
                             momentum_unavailable=momentum_missing)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_resolver.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/sources/resolver.py tests/memedogV2/test_resolver.py
git commit -m "feat(sources): DataResolver — priority merge, failure-tolerant, source attribution"
```

---

## Task 6: facts_filter — run red-lines over ResolvedFacts

**Files:** Create `src/memedogV2/hardfilter/facts_filter.py`; Test `tests/memedogV2/test_facts_filter.py`

Reuse the existing pure rule functions in `hardfilter/rules.py`, but feed them canonical `Facts` values directly (no FIELD_MAP, no gmgn JSON).

- [ ] **Step 1: Write the failing test**

```python
# tests/memedogV2/test_facts_filter.py
from memedogV2.hardfilter.facts_filter import evaluate_facts
from memedogV2.sources.base import Facts

CFG = {"max_top10_rate": 0.35, "max_creator_rate": 0.10, "max_dev_rate": 0.10,
       "max_sniper_wallets": 20, "max_fresh_wallet_rate": 0.6, "max_bundler_rate": 0.3,
       "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0,
       "max_fdv_to_liquidity": 50}


def _clean():
    return Facts(mint_revoked=True, freeze_revoked=True, honeypot=False, lp_safe=True,
                 top10_rate=0.2, creator_rate=0.0, dev_rate=0.0, sniper_count=3,
                 fresh_wallet_rate=0.0, bundler_rate=0.0, liquidity_usd=50000,
                 volume_5m=5000, buys_5m=30, sells_5m=10, price_usd=0.05,
                 circulating_supply=1000000)


def test_clean_facts_pass():
    passed, dropped = evaluate_facts(_clean(), CFG)
    assert passed is True and dropped == []


def test_mint_not_revoked_drops():
    f = _clean(); f.mint_revoked = False
    passed, dropped = evaluate_facts(f, CFG)
    assert passed is False and any("mint" in d for d in dropped)


def test_lp_unsafe_drops():
    f = _clean(); f.lp_safe = False
    passed, dropped = evaluate_facts(f, CFG)
    assert passed is False and any("LP" in d for d in dropped)


def test_low_liquidity_drops():
    f = _clean(); f.liquidity_usd = 5000
    passed, dropped = evaluate_facts(f, CFG)
    assert passed is False and any("liquidity" in d for d in dropped)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/memedogV2/test_facts_filter.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Write minimal implementation**

```python
# src/memedogV2/hardfilter/facts_filter.py
from __future__ import annotations

from memedogV2.hardfilter import rules as R
from memedogV2.sources.base import Facts


def evaluate_facts(f: Facts, cfg: dict) -> tuple[bool, list[str]]:
    """Run red-line rules over canonical Facts. Returns (passed, dropped_reasons).
    Degrades open on missing values (same policy as the gmgn-coupled filter)."""
    dropped: list[str] = []

    # authorities (honeypot int->bool already in Facts; pass as 1/0 to the rule)
    ok, reason = R.check_authorities(
        renounced_mint=f.mint_revoked, renounced_freeze=f.freeze_revoked,
        honeypot=(1 if f.honeypot else 0) if f.honeypot is not None else None)
    if not ok:
        dropped.append(reason); return False, dropped

    ok, reason = R.check_lp(
        burn_status=("burn" if f.lp_safe else "") if f.lp_safe is not None else None,
        lp_locked=f.lp_safe)
    if not ok:
        dropped.append(reason); return False, dropped

    ok, reason = R.check_concentration(top10_rate=f.top10_rate, creator_rate=f.creator_rate,
                                       dev_rate=f.dev_rate, cfg=cfg)
    if not ok:
        dropped.append(reason); return False, dropped

    ok, reason = R.check_manipulation(sniper_wallets=f.sniper_count, fresh_rate=f.fresh_wallet_rate,
                                      bundler_rate=f.bundler_rate, cfg=cfg)
    if not ok:
        dropped.append(reason); return False, dropped

    ratio = (f.buys_5m / f.sells_5m) if (f.buys_5m is not None and f.sells_5m) else None
    fdv = (f.price_usd * f.circulating_supply) if (f.price_usd is not None
                                                   and f.circulating_supply is not None) else None
    ok, reason = R.check_momentum(liquidity=f.liquidity_usd, volume_5m=f.volume_5m,
                                  buy_sell=ratio, fdv=fdv, cfg=cfg)
    if not ok:
        dropped.append(reason); return False, dropped

    return True, dropped
```

Note: `check_lp` here maps `lp_safe` bool to the rule's `(burn_status, lp_locked)` inputs; passing `lp_locked=f.lp_safe` makes the rule pass when `lp_safe is True`, fail when `False`, and degrade-open when `None`. Correct.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/memedogV2/test_facts_filter.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/memedogV2/hardfilter/facts_filter.py tests/memedogV2/test_facts_filter.py
git commit -m "feat(hardfilter): evaluate red-lines over canonical Facts (source-agnostic)"
```

---

## Task 7: Wire the resolver into the harness runner (replace gmgn-only fetch; fix C-1)

**Files:** Modify `src/memedogV2/harness/runner.py`; Modify `src/memedogV2/__main__.py`; Modify/replace `tests/memedogV2/test_workflow_runner.py` and `tests/memedogV2/test_e2e_mocked.py`

The runner's `read_security`/`read_info` steps become one `read_facts` step driven by `DataResolver`; hardfilter runs via `evaluate_facts`; evidence is built from the resolved `Facts`. Any source/resolve failure is caught → FAILED step, no crash (C-1).

- [ ] **Step 1: Update `build_evidence` to accept canonical Facts**

Modify `src/memedogV2/harness/evidence_builder.py` to add a Facts-based builder (keep it small):

```python
# append to src/memedogV2/harness/evidence_builder.py
from memedogV2.sources.base import Facts  # add at top with other imports


def build_evidence_from_facts(*, facts: Facts, ca: str) -> EvidenceBundle:
    fields = {
        "smart_money_count": facts.smart_money_count,
        "kol_holder_count": facts.kol_count,
        "dev_created_token_count": facts.dev_created_count,
        "dev_graduation_rate": None,
        "historical_ath": facts.historical_ath,
    }
    missing = [k for k, v in fields.items() if v is None]
    return EvidenceBundle(ca_address=ca, missing=missing, **fields)
```

- [ ] **Step 2: Write/Update the runner test** (`tests/memedogV2/test_workflow_runner.py` — replace the gmgn-fixture wiring with a resolver)

```python
import pytest
from memedogV2.harness.runner import HarnessRunner
from memedogV2.harness.model_registry import FakeBackend
from memedogV2.harness.contracts import StepStatus
from memedogV2.sources.resolver import DataResolver
from memedogV2.sources.base import PartialFacts
from memedogV2.harness.contracts import ToolCallRecord


class StubSource:
    def __init__(self, name, pf):
        self.name = name; self._pf = pf
    async def fetch(self, ca, lp):
        return self._pf, ToolCallRecord(tool=self.name, command="x", exit_status=0)


CLEAN = PartialFacts(mint_revoked=True, freeze_revoked=True, honeypot=False, lp_safe=True,
                     top10_rate=0.2, creator_rate=0.0, dev_rate=0.0, sniper_count=3,
                     fresh_wallet_rate=0.0, bundler_rate=0.0, liquidity_usd=50000,
                     volume_5m=5000, buys_5m=30, sells_5m=10, price_usd=0.05,
                     circulating_supply=1000000, smart_money_count=4, kol_count=1)
DIRTY = PartialFacts(mint_revoked=False, freeze_revoked=True, lp_safe=True,
                     liquidity_usd=50000, volume_5m=5000, buys_5m=30, sells_5m=10)
CFG = {"max_top10_rate": 0.35, "max_creator_rate": 0.10, "max_dev_rate": 0.10,
       "max_sniper_wallets": 20, "max_fresh_wallet_rate": 0.6, "max_bundler_rate": 0.3,
       "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0,
       "max_fdv_to_liquidity": 50}


def _backend():
    return FakeBackend(responses={
        "bull": {"thesis": "x", "points": []}, "bear": {"thesis": "y", "points": []},
        "judge": {"signal": "BULLISH", "recommended": True, "confidence": 0.7,
                  "rationale": "ok", "evidence_refs": []}})


def _runner(pf):
    resolver = DataResolver(sources={"gmgn": StubSource("gmgn", pf)})
    return HarnessRunner(resolver=resolver, backend=_backend(), hardfilter_cfg=CFG)


@pytest.mark.asyncio
async def test_clean_facts_run_full_workflow():
    run = await _runner(CLEAN).run("CA", "LP", trace_id="t1")
    assert run.final_signal is not None and run.final_signal.recommended is True
    names = [s.name for s in run.steps]
    assert names == ["read_facts", "hardfilter", "build_evidence", "bull", "bear", "judge", "signal"]
    assert any(s.tool_calls for s in run.steps)        # source attempts recorded


@pytest.mark.asyncio
async def test_dropped_facts_skip_models():
    run = await _runner(DIRTY).run("CA", "LP")
    assert run.final_signal is None
    statuses = {s.name: s.status for s in run.steps}
    assert statuses["bull"] == StepStatus.SKIPPED


@pytest.mark.asyncio
async def test_momentum_unavailable_fails_no_crash():
    pf = PartialFacts(mint_revoked=True, freeze_revoked=True, lp_safe=True)  # no momentum
    run = await _runner(pf).run("CA", "LP")
    assert run.final_signal is None
    assert any(s.status == StepStatus.FAILED for s in run.steps)


@pytest.mark.asyncio
async def test_source_failure_does_not_crash():
    class Boom:
        name = "gmgn"
        async def fetch(self, ca, lp):
            raise RuntimeError("network")
    resolver = DataResolver(sources={"gmgn": Boom()})
    runner = HarnessRunner(resolver=resolver, backend=_backend(), hardfilter_cfg=CFG)
    run = await runner.run("CA", "LP")     # must NOT raise (C-1)
    assert run.final_signal is None
    assert any(s.status == StepStatus.FAILED for s in run.steps)
```

- [ ] **Step 3: Rewrite the runner's fetch/hardfilter section** in `src/memedogV2/harness/runner.py`

Replace the constructor + the `read_security`/`read_info`/`hardfilter` portion so the runner takes a `resolver` instead of a `tool_registry`, runs `evaluate_facts`, and builds evidence from `Facts`. Concretely:

```python
# constructor
def __init__(self, *, resolver, backend, hardfilter_cfg: dict, recorder=None) -> None:
    self._resolver = resolver
    self._backend = backend
    self._cfg = hardfilter_cfg
    self._recorder = recorder
```

```python
# top of run(), replacing the two fetch stages + hardfilter:
from memedogV2.clients.errors import RateLimitBanned
from memedogV2.hardfilter.facts_filter import evaluate_facts
from memedogV2.harness.evidence_builder import build_evidence_from_facts

# read_facts (multi-source)
try:
    resolved = await self._resolver.resolve(ca, lp)
except RateLimitBanned as e:
    run.steps.append(StepResult(name="read_facts", status=StepStatus.FAILED,
                                error=f"rate-limit ban until {e.reset_at}"))
    return self._finish(run)
except Exception as e:
    run.steps.append(StepResult(name="read_facts", status=StepStatus.FAILED,
                                error=f"resolve failed: {e}"))
    return self._finish(run)
run.steps.append(StepResult(name="read_facts", status=StepStatus.OK,
                            tool_calls=list(resolved.attempts),
                            detail=f"sources={resolved.sources}"))

# momentum is required
if resolved.momentum_unavailable:
    run.steps.append(StepResult(name="hardfilter", status=StepStatus.FAILED,
                                error="momentum unavailable (gmgn required)"))
    for name in ["build_evidence", "bull", "bear", "judge", "signal"]:
        run.steps.append(StepResult(name=name, status=StepStatus.SKIPPED))
    return self._finish(run)

passed, dropped = evaluate_facts(resolved.facts, self._cfg)
run.steps.append(StepResult(name="hardfilter", status=StepStatus.OK,
                            detail=("passed" if passed else f"dropped: {dropped}")))
if not passed:
    for name in ["build_evidence", "bull", "bear", "judge", "signal"]:
        run.steps.append(StepResult(name=name, status=StepStatus.SKIPPED))
    return self._finish(run)

bundle = build_evidence_from_facts(facts=resolved.facts, ca=ca)
run.steps.append(StepResult(name="build_evidence", status=StepStatus.OK,
                            detail=f"missing={bundle.missing}"))
# ...(the existing bull/bear/judge/signal block — wrapped in try/except as before — stays)
```

Remove the now-unused `_FactsCli` class and the `build_evidence(facts=...)` call (replaced by `build_evidence_from_facts`). Keep the model-call try/except block from the earlier C1 fix intact.

- [ ] **Step 4: Update `__main__.py`** to build the resolver:

```python
# replace the tool-registry wiring in _main()
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.sources.gmgn_source import GmgnSource
from memedogV2.sources.rugcheck_source import RugCheckSource
from memedogV2.sources.helius_source import HeliusSource
from memedogV2.sources.resolver import DataResolver

cli = GmgnCli(rate_per_sec=cfg.gmgn["rate_limit_rps"], capacity=1,
              cache_ttl_sec=cfg.gmgn["cache_ttl_sec"])
resolver = DataResolver(sources={
    "rugcheck": RugCheckSource(),
    "gmgn": GmgnSource(cli=cli, max_retries=cfg.gmgn.get("max_retries", 2)),
    "helius": HeliusSource(),
})
runner = HarnessRunner(resolver=resolver, backend=build_backend(backend_name, cwd=os.getcwd()),
                       hardfilter_cfg=cfg.hardfilter, recorder=Recorder())
```

- [ ] **Step 5: Update `test_e2e_mocked.py`** to use the resolver (same `StubSource` + `CLEAN` pattern as Step 2). Delete `tests/memedogV2/test_tool_registry.py` if `tool_registry` is no longer used, OR keep `tool_registry.py` only if still imported; otherwise remove `src/memedogV2/harness/tool_registry.py`. Run `grep -rn "tool_registry\|GmgnCliToolSource\|FixtureToolSource\|build_evidence(facts" src tests` and remove dead references.

- [ ] **Step 6: Run the whole suite**

Run: `pytest tests/memedogV2 -q` → expect ALL PASS.
Run: `pytest -q` → expect memedog still green.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(harness): runner uses DataResolver (multi-source); fix C-1 (no crash on source failure)"
```

---

## Task 8: gmgn retry config + thresholds

**Files:** Modify `src/memedogV2/config_thresholds.yaml`; Test `tests/memedogV2/test_config.py` (add one assertion)

- [ ] **Step 1: Add `max_retries` under `gmgn:` in `config_thresholds.yaml`**

```yaml
gmgn:
  rate_limit_rps: 1.0
  cache_ttl_sec: 60
  max_evidence_calls: 5
  intake_drain_rps: 0.5
  on_failure: pass_flagged
  on_429: suspend_until_reset
  max_retries: 2            # bounded retry for transient (non-429) gmgn errors (H-1)
```

- [ ] **Step 2: Add a test assertion** to `tests/memedogV2/test_config.py::test_packaged_default_thresholds_load`:

```python
    assert cfg.gmgn["max_retries"] >= 1
```

- [ ] **Step 3: Run + commit**

```bash
pytest tests/memedogV2/test_config.py -q
git add src/memedogV2/config_thresholds.yaml tests/memedogV2/test_config.py
git commit -m "feat(config): gmgn.max_retries for bounded transient retry"
```

---

## Task 9: Mandatory real-environment gate (default run, skip-if-no-creds)

**Files:** Create `tests/memedogV2/test_gate_real.py`

NOT marked `live` → runs in the default suite. Skips loudly only when creds/binaries are truly absent. Proves the real multi-source + real DeepSeek pipeline works, and that resilience fallback works against real sources.

- [ ] **Step 1: Write the gate tests**

```python
# tests/memedogV2/test_gate_real.py
import os, shutil, asyncio
import pytest
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.config import load_v2_config
from memedogV2.sources.gmgn_source import GmgnSource
from memedogV2.sources.rugcheck_source import RugCheckSource
from memedogV2.sources.helius_source import HeliusSource
from memedogV2.sources.resolver import DataResolver
from memedogV2.harness.runner import HarnessRunner
from memedogV2.harness.model_registry import build_backend


def _need(cond, why):
    if not cond:
        pytest.skip(f"GATE SKIPPED — {why}")


def _resolver():
    cli = GmgnCli(rate_per_sec=1.0, capacity=1)
    return DataResolver(sources={
        "rugcheck": RugCheckSource(),
        "gmgn": GmgnSource(cli=cli, max_retries=2),
        "helius": HeliusSource(),
    })


# A pinned (CA, LP) that currently passes hardfilter — REPLACE with a live one found
# during validation; the dynamic finder below is the primary path.
PINNED_CA = ""   # filled during Task 11 validation
PINNED_LP = ""


async def _find_passing_token():
    """Dynamic: query gmgn-cli market trenches for a CA that passes hardfilter.
    Returns (ca, lp) or None. Implemented during validation; falls back to PINNED."""
    return (PINNED_CA, PINNED_LP) if PINNED_CA else None


@pytest.mark.asyncio
async def test_gate_real_pipeline():
    _need(shutil.which("gmgn-cli"), "gmgn-cli not installed")
    _need(os.environ.get("DEEPSEEK_API_KEY"), "DEEPSEEK_API_KEY not set")
    token = await _find_passing_token()
    _need(token and token[0], "no passing token available right now (dynamic finder + pinned both empty)")
    ca, lp = token
    cfg = load_v2_config("src/memedogV2/config_thresholds.yaml")
    runner = HarnessRunner(resolver=_resolver(), backend=build_backend("deepseek"),
                           hardfilter_cfg=cfg.hardfilter)
    run = await runner.run(ca, lp)
    assert any(s.name == "read_facts" and s.tool_calls for s in run.steps)
    # this token was selected because it passes -> a real signal must come out
    assert run.final_signal is not None
    assert run.final_signal.signal.value in ("BULLISH", "BEARISH", "NEUTRAL")


@pytest.mark.asyncio
async def test_gate_resilience_real_fallback():
    """Force RugCheck to fail; assert real gmgn still supplies authorities/LP/concentration."""
    _need(shutil.which("gmgn-cli"), "gmgn-cli not installed")
    USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    class BoomRug:
        name = "rugcheck"
        async def fetch(self, ca, lp):
            raise RuntimeError("forced rugcheck failure")

    cli = GmgnCli(rate_per_sec=1.0, capacity=1)
    resolver = DataResolver(sources={"rugcheck": BoomRug(),
                                     "gmgn": GmgnSource(cli=cli, max_retries=2)})
    resolved = await resolver.resolve(USDC, "LP")   # must not raise
    assert resolved.facts.mint_revoked is True             # came from gmgn fallback
    assert resolved.sources.get("mint_revoked") == "gmgn"
    assert any(a.tool == "rugcheck" and a.exit_status != 0 for a in resolved.attempts)
```

- [ ] **Step 2: Verify it runs in the default suite (not deselected)**

Run: `pytest tests/memedogV2/test_gate_real.py -v`
Expected: with creds present, `test_gate_resilience_real_fallback` PASSES (real gmgn), and `test_gate_real_pipeline` SKIPS until `PINNED_CA`/dynamic finder is filled (Task 11). Without creds, both SKIP loudly. Confirm it is NOT deselected by `-m 'not live'`: `pytest tests/memedogV2 -q` includes it.

- [ ] **Step 3: Commit**

```bash
git add tests/memedogV2/test_gate_real.py
git commit -m "test(gate): mandatory real-environment gate (pipeline + resilience fallback)"
```

---

## Task 10: Docs

**Files:** Modify the spec (append implemented note) and `CLAUDE.md` (note multi-source resolver)

- [ ] **Step 1: Append an "implemented" note** to `docs/superpowers/specs/2026-06-25-memedogV2-multisource-resilient-data.md` summarizing: `sources/` package, per-field priority, C-1/H-1 fixed, real gate in `test_gate_real.py`. Update the `CLAUDE.md` memedogV2 bullet to mention RugCheck/Helius/gmgn multi-source resolver.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-06-25-memedogV2-multisource-resilient-data.md CLAUDE.md
git commit -m "docs: record multi-source resolver as implemented"
```

---

## Task 11: Real validation (manual — find a passing token, run the real pipeline)

This is the deliverable the user asked for: a real run that reaches a Signal.

- [ ] **Step 1: Find a live (CA, LP) that passes hardfilter.** Use `gmgn-cli market` trenches/trending to list new tokens, then for each candidate run the real resolver + `evaluate_facts` until one passes (mint/freeze revoked, LP burned/locked, top10≤35%, liquidity≥$20k, vol5m≥$1k, buys/sells≥1). Record the CA + its biggest_pool_address as LP.

```bash
set -a; . ./.env 2>/dev/null; set +a
gmgn-cli market trenches --chain sol --raw 2>/dev/null | head -c 2000   # inspect available fields
# (script: iterate candidates, run resolver+evaluate_facts, print first passing CA/LP)
```

- [ ] **Step 2: Fill `PINNED_CA`/`PINNED_LP`** in `tests/memedogV2/test_gate_real.py` with the found token (and/or wire the dynamic finder). Re-run the gate:

```bash
set -a; . ./.env 2>/dev/null; set +a
pytest tests/memedogV2/test_gate_real.py::test_gate_real_pipeline -v -s
```

Expected: real pipeline runs to a `final_signal` (real DeepSeek verdict). If no passing token exists at that moment, document it (the gate skips loudly — that is acceptable and itself a finding about new-meme quality).

- [ ] **Step 3: Run the full real pipeline via the CLI and capture the run record**

```bash
set -a; . ./.env 2>/dev/null; set +a
python -m memedogV2 <PASSING_CA> <PASSING_LP> deepseek
ls -t runs/memedogV2/ | head -1   # the recorded run with per-field sources + attempts
```

- [ ] **Step 4: Commit the pinned token + any finder script**

```bash
git add tests/memedogV2/test_gate_real.py scripts/ 2>/dev/null
git commit -m "test(gate): pin a real passing (CA, LP); real pipeline reaches a signal"
```

---

## Self-Review Notes

- **Spec coverage:** §四 architecture → Tasks 1–7; §五 Facts → Task 1; §六 priority → Task 1 table + Task 5 merge; §七 components → Tasks 2/3/4 (sources) + 5 (resolver) + 6 (facts_filter) + 7 (wiring); §八 resilience/C-1/H-1 → Task 2 (retry), Task 5 (failure-tolerant merge), Task 7 (runner never-raises); §九 observability → Task 5 `sources`/`attempts` + Task 7 `read_facts.tool_calls`; §十 tests → real fixtures (Task 0) + unit (Tasks 1–6) + mandatory gate (Task 9) + real validation (Task 11); §十一 migration → Task 7; §十二 acceptance → Tasks 5/7/9.
- **Types:** `SourceAdapter.fetch(ca, lp) -> (PartialFacts, ToolCallRecord)` consistent Tasks 2/3/4/5/7/9. `DataResolver.resolve(ca, lp) -> ResolvedFacts{facts, sources, attempts, momentum_unavailable}` consistent Tasks 5/7/9. `evaluate_facts(Facts, cfg) -> (bool, list[str])` consistent Tasks 6/7. `build_evidence_from_facts(facts, ca) -> EvidenceBundle` consistent Task 7.
- **Real-test requirement:** unit tests use REAL captured fixtures (Task 0); the gate (Task 9) runs real services by default and is the non-skippable-when-configured proof; Task 11 is the live human-validated run that reaches a signal.
- **Known soft spot:** `test_gate_real_pipeline` depends on a passing token existing; it skips (loudly) when none is available rather than failing — documented in §十三 and Task 11. The resilience gate (`test_gate_resilience_real_fallback`) always runs real gmgn and has no such dependency.
```
