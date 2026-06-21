# Real-Data-Driven Testing — Design

**Status:** Approved 2026-06-22

## Goal

Eliminate hand-fabricated mock API responses from the test suite. Every test that
crosses an external API boundary must be driven by **real captured response bodies**
(fixtures), not invented JSON. Add an opt-in **live** test tier that hits real APIs.
Degradation tests (e.g. missing key → dimension unavailable) are kept — they encode
real behavior.

## Decisions (from brainstorming)

1. **Real-data-driven, not live-by-default.** Default suite replays real captured
   response bodies — deterministic, offline, fast, CI-friendly.
2. **Scope = external API boundary only.** Pure-logic tests (scoring, hardfilter
   rules, papertrader math, structured parsing, models, config, dashboard helpers)
   stay as they are; their inputs are constructed domain objects, not mocks.
3. **Add an optional live tier** (`@pytest.mark.live`), excluded by default, run via
   `pytest -m live`, auto-skipped when keys are absent.
4. **Mechanism = explicit captured fixtures + respx.** A capture script calls real
   APIs and stores **only response bodies** (never headers/URLs → no secret leakage).
   No VCR auto-recording (it would capture keys in URLs/headers).

## Non-Goals

- Reworking pure-logic unit tests.
- Capturing a real Twitter data-path response (no API key available — see Limitations).
- Making the default suite hit the network.

## Architecture

### A. Fixture corpus — `tests/fixtures/<source>/`

Real captured response bodies, committed. Each must be a genuine API body (capture
provenance — mint/endpoint/date — recorded in `scripts/capture_fixtures.py`).

```
tests/fixtures/
  dexscreener/
    token_profiles_latest.json     # GET /token-profiles/latest/v1 (real list, mixed/solana)
    tokens_bonk.json               # GET /latest/dex/tokens/{BONK} (full pair schema)
    tokens_empty.json              # real response with no/null pairs
    tokens_thin.json               # real pair(s) missing the `liquidity` key
  rugcheck/
    report_bonk.json               # clean/safe token (already captured)
    report_concentrated.json       # real token with high top10 concentration
    report_rugged.json             # real token with rugged=true (or high score_normalised)
    report_notfound.json           # real error body for a nonexistent mint (+ status noted)
  helius/
    largest_accounts_ok.json       # real getTokenLargestAccounts success
    largest_accounts_overloaded.json # real JSON-RPC -32603 "overloaded" error
    largest_accounts_empty.json    # real empty value list
  telegram/
    send_ok.json                   # real {"ok":true,"result":{...}} (body only)
    send_forbidden.json            # real 403 body
  twitter/
    counts_sample.json             # documented-shape sample (NOT live-captured; see Limitations)
  codex/
    bull_argument.txt              # real codex bull-role output
    bear_argument.txt              # real codex bear-role output
    judge_bullish.json            # real codex JudgeOut JSON (BULLISH)
    judge_bearish.json            # real codex JudgeOut JSON (BEARISH)
```

### B. Capture script — `scripts/capture_fixtures.py`

Re-runnable. Reads keys from `.env`. For each source: call the real API, write the
**response body** to the fixture path. Must:
- store only `response.json()` / final text — never headers, never the request URL,
  never tokens;
- skip a source gracefully (log + continue) when its key is missing (Twitter, etc.);
- run real `codex exec` to capture codex outputs (uses configured codex bin);
- print a provenance summary (which mint/endpoint, timestamp).
NOT part of the test suite; a maintenance tool.

### C. Fixture loader — `tests/conftest.py`

- `load_fixture(relpath) -> dict | list | str` helper resolving `tests/fixtures/`.
- A small helper to mount a fixture as a respx response.
- Register the `live` marker and configure default exclusion (see E).

### D. Boundary test rewrites (default tier)

Replace inline invented payloads with `load_fixture(...)`:

| Test file | Change |
|-----------|--------|
| `tests/clients/test_dexscreener.py` | respx serves dexscreener/* fixtures |
| `tests/clients/test_rugcheck.py` | already fixture-based; extend with concentrated/rugged/notfound |
| `tests/clients/test_helius.py` | respx serves helius/* (ok / overloaded / empty) |
| `tests/clients/test_twitter.py` | keep real degradation (no bearer → DataSourceError); data-path uses counts_sample.json (flagged) |
| `tests/alert/test_telegram.py` | respx serves telegram/send_ok + send_forbidden |
| `tests/llm/test_codex_provider.py` | subprocess still intercepted (it tests process plumbing, not data); the replayed output is a real captured codex fixture |
| `tests/scanner/test_scanner.py` | Fake discoverer returns real captured pair dicts (from dexscreener fixtures) |
| `tests/hardfilter/test_hardfilter.py` | Fake rugcheck returns real captured reports |
| `tests/enricher/test_providers.py`, `test_enricher.py` | fakes return real captured bodies |
| `tests/llmjudge/test_judge.py` | FakeProvider replays real captured codex outputs |
| `tests/test_integration_pipeline.py` | fakes feed real captured bodies end-to-end |

Assertions must match the real data. Where exact values are market-dependent, assert
**structural invariants and ranges** rather than brittle exact numbers (except where a
fixture pins a known value, e.g. BONK authorities revoked).

### E. Live tier — `tests/live/`

`@pytest.mark.live` on each. `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = ["live: hits real external APIs; needs keys; run with -m live"]
addopts = "-m 'not live'"
```
Tests (each skips if its prerequisite key/binary is missing):
- `test_live_dexscreener.py` — real scan returns solana candidates.
- `test_live_rugcheck.py` — real BONK report → parse_report sane (authorities revoked, trust_score in range).
- `test_live_helius.py` — real holders on a fresh token → percentages computed.
- `test_live_codex.py` — real `complete()` returns text; real `judge()` non-degraded.
- `test_live_telegram.py` — real send; **double-gated** behind `MEMEDOG_LIVE_TELEGRAM=1` to avoid accidental sends.
- `test_live_e2e.py` — real `orchestrator.run_cycle()` runs without crash; funnel event persisted.
Codex live tests resolve the binary from `cfg.llmjudge.codex.bin` or PATH; skip if unavailable.

## Limitations (explicit)

- **Twitter data-path**: no API key available, so the "has data" path cannot be
  driven by a real captured response. `counts_sample.json` is a documented-shape
  sample, clearly labeled. The real, key-free behavior (no bearer → `DataSourceError`)
  IS tested. A live Twitter test is included but will skip without a bearer.
- Live tier requires network + keys; it is not run in CI by default.

## Success Criteria

- Default `pytest` is green, performs **no network calls**, and every external-boundary
  test is driven by a real captured fixture (no hand-fabricated API JSON remains).
- `pytest -m live` exercises real APIs when keys/binary are present; each live test
  self-skips otherwise.
- Pure-logic tests unchanged. Degradation tests retained.
- `scripts/capture_fixtures.py` can refresh all capturable fixtures and never writes secrets.
