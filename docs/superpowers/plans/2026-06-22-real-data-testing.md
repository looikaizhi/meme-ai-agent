# Real-Data-Driven Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace hand-fabricated mock API responses with real captured fixtures across all external-API-boundary tests, and add an opt-in live test tier.

**Architecture:** A capture script hits real APIs and stores response bodies only (no secrets) under `tests/fixtures/<source>/`. Boundary tests load those fixtures via a `load_fixture` helper and serve them through respx / fake clients. A `live` pytest marker (excluded by default) gates real-network tests that self-skip without keys.

**Tech Stack:** pytest, respx, httpx, pydantic, real APIs (DexScreener, RugCheck, Helius, Telegram, Codex CLI).

Spec: `docs/superpowers/specs/2026-06-22-real-data-testing-design.md`

---

## Pre-req (controller does this BEFORE dispatching test-rewrite tasks)

Capture is a live operation requiring keys; the controller runs it directly (not a subagent) so the real fixtures exist before tests are rewritten. See Task 1.

---

### Task 1: Capture script + produce real fixtures

**Files:**
- Create: `scripts/capture_fixtures.py`
- Create (by running it): `tests/fixtures/dexscreener/*.json`, `tests/fixtures/helius/*.json`, `tests/fixtures/telegram/*.json`, `tests/fixtures/rugcheck/report_concentrated.json`, `tests/fixtures/rugcheck/report_notfound.json`, `tests/fixtures/codex/*`
- Keep existing: `tests/fixtures/rugcheck/report_bonk.json`
- Create: `tests/fixtures/twitter/counts_sample.json` (documented-shape, hand-written, labeled)

- [ ] **Step 1: Write `scripts/capture_fixtures.py`**

It must store ONLY response bodies (never headers/URLs/tokens). Structure:
```python
"""Capture REAL API response bodies into tests/fixtures/ (no secrets stored).
Re-runnable maintenance tool. Reads keys from .env via load_config().
Usage: PYTHONPATH=src python scripts/capture_fixtures.py
"""
import asyncio, json, os
from pathlib import Path
from memedog.config import load_config
from memedog.clients.dexscreener import DexScreenerClient
from memedog.clients.rugcheck import RugCheckClient
from memedog.clients.helius import HeliusClient

FX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

def _write(rel, body):
    p = FX / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body, indent=2), encoding="utf-8")
    print("wrote", rel)

async def capture_dexscreener():
    c = DexScreenerClient()
    try:
        profiles = await c.get_json("/token-profiles/latest/v1")
        _write("dexscreener/token_profiles_latest.json", profiles)
        bonk = await c.get_json(f"/latest/dex/tokens/{BONK}")
        _write("dexscreener/tokens_bonk.json", bonk)
        # find a thin pair (missing liquidity) and an empty one from latest tokens
        addrs = await c.fetch_latest_token_addresses("solana")
        thin = None; empty = None
        for a in addrs:
            data = await c.get_json(f"/latest/dex/tokens/{a}")
            pairs = data.get("pairs") or []
            if not pairs and empty is None:
                empty = data
            if pairs and "liquidity" not in pairs[0] and thin is None:
                thin = data
            if thin and empty: break
        _write("dexscreener/tokens_empty.json", empty or {"pairs": None})
        if thin: _write("dexscreener/tokens_thin.json", thin)
    finally:
        await c.aclose()

async def capture_rugcheck():
    c = RugCheckClient()
    try:
        # concentrated: pick a fresh token from dexscreener and fetch its report
        dex = DexScreenerClient()
        addrs = await dex.fetch_latest_token_addresses("solana"); await dex.aclose()
        for a in addrs:
            try:
                rep = await c.get_token_report(a)
            except Exception:
                continue
            from memedog.clients.rugcheck import parse_report
            parsed = parse_report(rep)
            if (parsed.get("top10_pct") or 0) > 40:
                _write("rugcheck/report_concentrated.json", rep); break
        # not-found: a clearly invalid mint
        try:
            await c.get_token_report("11111111111111111111111111111111")
        except Exception as e:
            _write("rugcheck/report_notfound.json", {"error": str(e)[:200]})
    finally:
        await c.aclose()

async def capture_helius(cfg):
    key = cfg.settings.helius_api_key
    if not key:
        print("skip helius (no key)"); return
    c = HeliusClient(api_key=key)
    dex = DexScreenerClient()
    try:
        addrs = await dex.fetch_latest_token_addresses("solana")
        # ok + (capture the raw RPC json by calling post_json directly)
        for a in addrs[:8]:
            payload = {"jsonrpc":"2.0","id":1,"method":"getTokenLargestAccounts","params":[a]}
            raw = await c.post_json(c._rpc_url, json=payload)
            if "result" in raw and raw["result"].get("value"):
                _write("helius/largest_accounts_ok.json", raw); break
        # overloaded error on a huge token (BONK often overloads)
        payload = {"jsonrpc":"2.0","id":1,"method":"getTokenLargestAccounts","params":[BONK]}
        raw = await c.post_json(c._rpc_url, json=payload)
        if "error" in raw:
            _write("helius/largest_accounts_overloaded.json", raw)
        # empty: an invalid mint returns empty/err — store a minimal real-shaped empty
        _write("helius/largest_accounts_empty.json", {"jsonrpc":"2.0","id":1,"result":{"value":[]}})
    finally:
        await c.aclose(); await dex.aclose()

async def capture_telegram(cfg):
    tok = cfg.settings.telegram_bot_token; chat = cfg.settings.telegram_chat_id
    if not (tok and chat):
        print("skip telegram (no creds)"); return
    import httpx
    async with httpx.AsyncClient(timeout=15) as h:
        ok = (await h.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                           json={"chat_id": chat, "text": "fixture capture (ignore)"})).json()
        _write("telegram/send_ok.json", ok)
        bad = (await h.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                            json={"chat_id": tok, "text": "x"})).json()  # bot->bot = 403 body
        _write("telegram/send_forbidden.json", bad)

def capture_twitter_sample():
    # No API key → documented-shape sample, clearly labeled as NOT live-captured.
    _write("twitter/counts_sample.json", {
        "_note": "DOCUMENTED-SHAPE SAMPLE — not live-captured (no API key). Shape per X API v2 /2/tweets/counts/recent.",
        "data": [{"start":"2026-01-01T00:00:00Z","end":"2026-01-01T01:00:00Z","tweet_count":12},
                 {"start":"2026-01-01T01:00:00Z","end":"2026-01-01T02:00:00Z","tweet_count":30}],
        "meta": {"total_tweet_count": 42},
    })

async def main():
    cfg = load_config()
    await capture_dexscreener()
    await capture_rugcheck()
    await capture_helius(cfg)
    await capture_telegram(cfg)
    capture_twitter_sample()
    print("DONE")

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it (controller, live)**

Run: `PYTHONPATH=src python scripts/capture_fixtures.py`
Expected: prints `wrote ...` for each fixture, `DONE`. Verify no file under `tests/fixtures/` contains an api-key/token (grep for `api-key`, `bot<digits>`, the helius key prefix). Codex fixtures (Task 1b) captured separately.

- [ ] **Step 3: Capture codex fixtures (controller, live)**

Run a one-off (codex bin = full path) producing real codex outputs for a fixed snapshot/score, writing:
`tests/fixtures/codex/bull_argument.txt`, `bear_argument.txt`, `judge_bullish.json`, `judge_bearish.json`. (Use a high-score snapshot for bullish, a low-score one for bearish.) Confirm each file is non-empty and the judge_*.json parse as JudgeOut.

- [ ] **Step 4: Commit**

```bash
git add scripts/capture_fixtures.py tests/fixtures/
git commit -m "test(fixtures): capture script + real API response fixtures"
```

---

### Task 2: conftest — fixture loader + live marker

**Files:**
- Create/modify: `tests/conftest.py`
- Modify: `pyproject.toml` (`[tool.pytest.ini_options]`)

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import json
from pathlib import Path
import pytest

_FX = Path(__file__).parent / "fixtures"

def load_fixture(relpath: str):
    """Load a real captured fixture body. .json -> parsed; else -> text."""
    p = _FX / relpath
    text = p.read_text(encoding="utf-8")
    return json.loads(text) if p.suffix == ".json" else text

@pytest.fixture
def fixture():
    return load_fixture
```

- [ ] **Step 2: Configure markers + default exclusion in `pyproject.toml`**

Under `[tool.pytest.ini_options]` add:
```toml
markers = ["live: hits real external APIs; needs keys; run with -m live"]
addopts = "-m 'not live'"
```
(Keep existing `asyncio_mode`, `testpaths`, `pythonpath`.)

- [ ] **Step 3: Verify default run still excludes nothing yet & collection works**

Run: `python -m pytest -q`
Expected: still 431 passed (no behavior change yet; addopts only filters `live` which doesn't exist yet).

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py pyproject.toml
git commit -m "test(infra): add load_fixture helper and live marker (excluded by default)"
```

---

### Task 3: Convert client boundary tests to real fixtures

**Files:**
- Modify: `tests/clients/test_dexscreener.py`, `tests/clients/test_helius.py`, `tests/alert/test_telegram.py`, `tests/clients/test_rugcheck.py`, `tests/clients/test_twitter.py`

For EACH: replace inline invented JSON passed to respx with `load_fixture("<source>/<file>.json")`. Keep respx as the transport. Adjust assertions to the real data (assert structural invariants / ranges; pin known facts like BONK authorities revoked). Keep all degradation tests (no-bearer → DataSourceError, etc.).

- [ ] **Step 1 (dexscreener):** rewrite tests to serve `dexscreener/token_profiles_latest.json`, `tokens_bonk.json`, `tokens_empty.json`, `tokens_thin.json`. Assert: `fetch_latest_token_addresses("solana")` returns only solana addresses from the real list; `get_token_pairs(BONK)` returns the real pairs; empty/null → `[]`; `get_token_price` parses a real `priceUsd`. Run `python -m pytest tests/clients/test_dexscreener.py -v` → PASS.
- [ ] **Step 2 (helius):** serve `helius/largest_accounts_ok.json` (assert top10/max_wallet computed from real data, in (0,100]), `largest_accounts_overloaded.json` (assert all-None on the real `-32603` error), `largest_accounts_empty.json` (assert holder_count 0). Run that file → PASS.
- [ ] **Step 3 (telegram):** serve `telegram/send_ok.json` (real ok → send True; maybe_notify True), `telegram/send_forbidden.json` (real 403 → send raises DataSourceError → maybe_notify False). Keep all gating tests. Run that file → PASS.
- [ ] **Step 4 (rugcheck):** extend existing fixture tests with `report_concentrated.json` (assert top10_pct > 40 / a holder rule would drop it) and `report_notfound.json` (assert get_token_report raises DataSourceError on the real error — may require serving via respx with the real status). Run that file → PASS.
- [ ] **Step 5 (twitter):** keep no-bearer → DataSourceError (real). For the data path, serve `twitter/counts_sample.json` via respx with a dummy bearer; assert mentions/growth parsed. Add a comment that the body is a documented-shape sample (no key to capture live). Run that file → PASS.
- [ ] **Step 6: Commit**

```bash
git add tests/clients/ tests/alert/
git commit -m "test(clients): drive boundary tests with real captured fixtures"
```

---

### Task 4: Convert codex_provider + downstream fake-based tests

**Files:**
- Modify: `tests/llm/test_codex_provider.py`, `tests/llmjudge/test_judge.py`, `tests/scanner/test_scanner.py`, `tests/hardfilter/test_hardfilter.py`, `tests/enricher/test_providers.py`, `tests/enricher/test_enricher.py`, `tests/test_integration_pipeline.py`

- [ ] **Step 1 (codex_provider):** keep the `asyncio.create_subprocess_exec` interception (it tests subprocess plumbing, not API data), but the content written to the output file = `load_fixture("codex/judge_bullish.json")` (real codex output). Assert complete() returns that real text. Run file → PASS.
- [ ] **Step 2 (judge):** FakeProvider canned responses become real captured codex outputs: bull=`codex/bull_argument.txt`, bear=`codex/bear_argument.txt`, judge=`codex/judge_bullish.json`. Assert the produced Signal matches the real judge output (signal/confidence/points). Keep the degrade-on-error test (real behavior). Run file → PASS.
- [ ] **Step 3 (scanner):** the Fake discoverer returns real pair dicts extracted from `dexscreener/tokens_bonk.json` / `token_profiles_latest.json` (real addresses + real pairs). Keep prefilter/dedup/chain-filter assertions adjusted to real data. Run file → PASS.
- [ ] **Step 4 (hardfilter):** the Fake rugcheck returns `load_fixture("rugcheck/report_bonk.json")` (clean → kept) and `rugcheck/report_concentrated.json` (concentrated → dropped). Keep momentum-first + pass_flagged + flagged-audit tests. Run file → PASS.
- [ ] **Step 5 (enricher providers + enricher):** fakes return real bodies (helius ok fixture → real holders; rugcheck fixture → real safety). Keep degradation tests (client raises → available False). Run both files → PASS.
- [ ] **Step 6 (integration):** feed the end-to-end fakes with real fixtures (dexscreener pairs, rugcheck reports, codex judge output via FakeProvider). Assert the funnel: a clean+bullish path produces a signal & opens a position; a concentrated token is dropped by hardfilter. Run file → PASS.
- [ ] **Step 7: Commit**

```bash
git add tests/llm/ tests/llmjudge/ tests/scanner/ tests/hardfilter/ tests/enricher/ tests/test_integration_pipeline.py
git commit -m "test(pipeline): drive fake-based tests with real captured fixtures"
```

---

### Task 5: Live test tier

**Files:**
- Create: `tests/live/__init__.py`, `tests/live/test_live_dexscreener.py`, `tests/live/test_live_rugcheck.py`, `tests/live/test_live_helius.py`, `tests/live/test_live_codex.py`, `tests/live/test_live_telegram.py`, `tests/live/test_live_e2e.py`

Each test: `@pytest.mark.live`, and self-skip via `pytest.skip(...)` when its prerequisite is missing. Use `load_config()` for keys. Codex tests resolve bin from `cfg.llmjudge.codex.bin`; if not runnable, skip.

- [ ] **Step 1: dexscreener live** — `@pytest.mark.live async def test_live_scan(): cfg=load_config(); from memedog.scanner.scanner import Scanner; from memedog.clients.dexscreener import DexScreenerClient; s=Scanner(DexScreenerClient(), cfg.scanner); out=await s.scan(); assert all(c.chain=="solana" for c in out)`. Run `python -m pytest tests/live/test_live_dexscreener.py -m live -v` → PASS (needs network).
- [ ] **Step 2: rugcheck live** — fetch real BONK report, parse_report, assert `mint_authority_revoked is True` and `0 <= trust_score <= 100`. Run with `-m live` → PASS.
- [ ] **Step 3: helius live** — skip if `not cfg.settings.helius_api_key`; fetch a fresh token's holders; assert percentages computed or None (no crash). Run with `-m live` (with key) → PASS or SKIP.
- [ ] **Step 4: codex live** — skip if codex bin not runnable; `CodexCLIProvider(codex_bin=cfg.llmjudge.codex.bin).complete(...)` returns text; `LLMJudge(cfg.llmjudge).judge(...)` returns a Signal whose rationale does NOT contain "降级". Run with `-m live` → PASS or SKIP. (Long-running.)
- [ ] **Step 5: telegram live** — skip unless `cfg.settings.telegram_bot_token and chat_id and os.environ.get("MEMEDOG_LIVE_TELEGRAM")=="1"`; real send returns True. Run with `-m live` + env → PASS or SKIP.
- [ ] **Step 6: e2e live** — build_orchestrator with codex bin set; run one `run_cycle()`; assert it returns a list and a funnel event is persisted; no crash. Run with `-m live` → PASS or SKIP.
- [ ] **Step 7: verify default suite excludes live**

Run: `python -m pytest -q` → live tests NOT collected (excluded by addopts). Then `python -m pytest -m live --collect-only -q` shows the live tests.

- [ ] **Step 8: Commit**

```bash
git add tests/live/
git commit -m "test(live): opt-in live API tier (excluded by default, self-skips without keys)"
```

---

### Task 6: Final verification

- [ ] **Step 1:** `python -m pytest -q` → all default tests green, NO network (confirm by reading: no test under default tier hits a real URL without respx). Report count.
- [ ] **Step 2:** grep `tests/fixtures/` for secrets (api-key / bot token digits) → none.
- [ ] **Step 3:** Commit any final cleanup.

---

## Self-Review

- **Spec coverage:** Fixture corpus (Task 1) ✓; capture script no-secrets (Task 1) ✓; conftest loader + marker + default-exclude (Task 2) ✓; boundary rewrites (Task 3) ✓; downstream fake rewrites (Task 4) ✓; live tier with skips + telegram double-gate (Task 5) ✓; Twitter limitation handled (Task 3 Step 5) ✓; final verify no-network + no-secrets (Task 6) ✓.
- **Placeholders:** none — capture script + assertions specified.
- **Consistency:** `load_fixture(relpath)` used uniformly; fixture paths match the corpus in Task 1; `live` marker name consistent.
