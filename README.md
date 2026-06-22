# 🐕‍🦺 MemeDog Radar

> **Solana meme-coin (“金狗 / golden-dog”) early-momentum monitoring & signal engine.**
> A funnel pipeline that scans hundreds of fresh tokens, defuses rugs with hard rules, enriches survivors with on-chain data, scores them, and lets two LLM personas (Bull vs Bear) debate before a judge emits a **`BULLISH / BEARISH / NEUTRAL`** signal — then paper-trades the result and shows it on a live dashboard.

**⚠️ Disclaimer:** Research / demo only. **Monitoring + signals + simulated (paper) trading. No real wallet, no real orders.** Not financial advice.

---

## 1. TL;DR for judges

| Question | Answer |
|----------|--------|
| **What stage does it target?** | The **“first momentum” window** of a meme coin — ~20 min to a few hours after launch (not millisecond sniping). |
| **What's the core idea?** | A **funnel**: hundreds of candidates → a handful → only those few ever touch the (expensive) LLM. This makes multi-agent LLM reasoning affordable at high frequency. |
| **Where's the AI?** | A provider-agnostic LLM layer runs a **Bull/Bear debate + a Judge verdict** over real on-chain data, anchored by a deterministic rule-based score. |
| **How is it run cheaply?** | The default LLM backend is the **OpenAI Codex CLI as a subprocess**, riding a ChatGPT subscription → near-zero per-call cost. Swappable to Claude / OpenAI / DeepSeek via one config string. |
| **Is it real?** | Yes — verified live against **DexScreener, RugCheck, Helius, Telegram, and Codex**. Tests are driven by **real captured API responses**, plus an opt-in live tier. |

---

## 2. The architecture at a glance

The whole system is a **6-stage funnel**. Each stage is a single-responsibility module that talks to the next only through a typed data object — so any layer can be swapped or tuned independently.

```
                      hundreds / cycle
  ┌─────────────┐    ──────────────────►   ┌──────────────┐   survivors (single digits)
  │ [1] Scanner │  TokenCandidate[]         │[2] HardFilter│  ──────────────────────────►
  └─────────────┘                           └──────────────┘
   poll DexScreener                          3 red-line gates
   prefilter "has momentum"                  (authority / concentration / liquidity)
   dedup                                     drop the rest  ✂️
                                                   │
        ┌──────────────────────────────────────────┘
        ▼
  ┌──────────────┐   TokenSnapshot   ┌───────────────┐   Score 0-100   ┌──────────────┐
  │ [3] Enricher │ ────────────────► │[4] ScoreEngine│ ──────────────► │ [5] LLMJudge │
  └──────────────┘                   └───────────────┘                 └──────────────┘
   4 dims in parallel:                4-dim weighted score              Bull ⚔ Bear debate
   safety / holders /                 (objective anchor)                + Judge verdict
   momentum / social                                                    │
   degrade-not-crash                                                    ▼
                                                              Signal: BULLISH / BEARISH / NEUTRAL
                                                              + confidence + reasons + red_flags
                                                                         │
                                          ┌──────────────────────────────┤
                                          ▼                              ▼
                                  ┌────────────────┐            ┌──────────────────┐
                                  │[6] PaperTrader │            │ Dashboard + Alert│
                                  └────────────────┘            └──────────────────┘
                                   open virtual position         Streamlit board
                                   TP / SL / timeout exit        + optional Telegram push
                                   track virtual PnL
```

### What each layer actually does

| # | Layer | One-line job | Input → Output | Key data sources | Code |
|---|-------|--------------|----------------|------------------|------|
| **1** | **Scanner** | Poll new pairs, keep only ones with early momentum, de-duplicate | `()` → `TokenCandidate[]` | DexScreener (free) | [`scanner/`](src/memedog/scanner/) |
| **2** | **HardFilter** | Defuse rugs/honeypots with 3 objective red-line gates before spending any LLM | `TokenCandidate[]` → `TokenCandidate[]` | RugCheck | [`hardfilter/`](src/memedog/hardfilter/) |
| **3** | **Enricher** | Fetch 4 signal dimensions **in parallel**, degrade gracefully on failure | `TokenCandidate` → `TokenSnapshot` | RugCheck · Helius RPC · DexScreener · X/Twitter | [`enricher/`](src/memedog/enricher/) |
| **4** | **ScoreEngine** | Map the 4 dimensions to a weighted **0–100** score (objective anchor for the LLM) | `TokenSnapshot` → `Score` | pure logic, config-driven | [`scoring/`](src/memedog/scoring/) |
| **5** | **LLMJudge** | Bull persona vs Bear persona debate → Judge synthesizes a structured verdict | `TokenSnapshot + Score` → `Signal` | LLM (Codex CLI default) | [`llmjudge/`](src/memedog/llmjudge/) |
| **6** | **PaperTrader** | Open a virtual position, exit on take-profit / stop-loss / timeout, track PnL | `Signal` → `Position / TradeRecord` | DexScreener (price poll) | [`papertrader/`](src/memedog/papertrader/) |
| **—** | **Dashboard / Alert** | Visualize the whole funnel + PnL; optionally push BULLISH signals to Telegram | reads the store | Streamlit · Telegram | [`dashboard/`](dashboard/) · [`alert/`](src/memedog/alert/) |

> The pieces are wired together by [`orchestrator.py`](src/memedog/orchestrator.py); typed data objects live in [`models/`](src/memedog/models/) ([data contracts](plan/08-data-contracts.md)).

---

## 3. Why this design (the four principles)

1. **Funnel = cost control.** Scanner emits hundreds per cycle; HardFilter cuts to single digits; only survivors reach Enricher + LLM. This is what makes a multi-agent LLM debate *viable* on a high-frequency meme-coin stream.
2. **Data vs. judgment are separated.** Enricher only *fetches*, ScoreEngine only *scores*, LLMJudge only *reasons*. Each layer is independently testable and replaceable.
3. **Provider-agnostic LLM.** Business code depends on an `LLMProvider` interface, never a vendor SDK. Routing is by model-string prefix:
   - `codex:<model>` → **CodexCLIProvider** *(experiment default — runs `codex exec` as a subprocess on a ChatGPT subscription, zero per-call API cost)*
   - `litellm:<provider>/<model>` → LiteLLM (Claude / OpenAI / DeepSeek) for comparison
4. **Degrade, never crash.** Any single data source failing marks that dimension “unavailable” (score re-weights, LLM is told it's missing) — the pipeline keeps going. If the LLM itself is unreachable, LLMJudge falls back to a rule-based signal.

---

## 4. The signal, concretely

**Hard red lines** (any failure ⇒ dropped; all thresholds in [`config/thresholds.yaml`](src/memedog/config/thresholds.yaml), nothing hard-coded):

- **Contract authority** — mint authority revoked · freeze authority revoked · LP burned/locked
- **Holder concentration** — Top-10 (ex-LP) ≤ 35% · max wallet < 20% · dev < 10% · snipers not abnormal
- **Liquidity / momentum** — liquidity ≥ $20k · 5-min volume floor · buy/sell ratio ≥ 1 · sane FDV/liquidity

**Four scored dimensions** (weighted to 0–100):

| Dimension | Primary source | Signal |
|-----------|----------------|--------|
| Safety / Rug | RugCheck (trustScore, riskLevel) | can it be sold? is it a honeypot? |
| Holder distribution | Helius RPC `getTokenLargestAccounts` | concentration / dump risk |
| Funds / liquidity / momentum | DexScreener | is real money flowing in? |
| Smart money / social | Helius (labeled wallets) + X/Twitter | narrative & smart-money interest |

**LLM verdict** → `Signal { signal, confidence, bull_points[], bear_points[], red_flags[], rationale }`.

---

## 5. Tech stack

- **Backend:** Python 3.11+ · `asyncio` + `httpx` (parallel data fetch)
- **Models / contracts:** `pydantic` v2
- **LLM:** provider-agnostic interface → **Codex CLI** (default) / LiteLLM (Claude·OpenAI·DeepSeek)
- **Config:** `pydantic-settings` + `.env` + a YAML thresholds file (tune strategy without touching code)
- **Storage:** SQLite (snapshots / signals / positions / funnel events)
- **Dashboard:** Streamlit · **Alerts:** Telegram Bot API (optional)

---

## 6. Run it

### Prerequisites
- Python 3.11+, Node 18+ (for Codex CLI)
- (Optional) API keys — the system **degrades gracefully** without them. See [`.env.example`](.env.example).

### Install
```bash
pip install -e ".[dev]"          # or: pip install pydantic pydantic-settings httpx pyyaml litellm streamlit
cp .env.example .env             # then fill in the keys you have
```

### LLM backend (default = Codex CLI, uses your ChatGPT subscription — no API key)
```bash
npm i -g @openai/codex
codex login                      # one-time browser login with your ChatGPT account
```
> To compare a standard API instead, set `llmjudge.models` in `thresholds.yaml` to e.g. `litellm:openai/gpt-4o` and put `OPENAI_API_KEY` in `.env`.

### Keys & where they go (`.env` in project root)
| Variable | Powers | Without it |
|----------|--------|-----------|
| `HELIUS_API_KEY` | holder distribution / smart money | that dimension degrades |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram alerts | alerts silently skipped |
| `TWITTER_BEARER` | social heat | social dimension degrades |
| Codex | LLM verdict | **no env key** — uses `codex login` |
| DexScreener / RugCheck | scan + safety | no key needed (public) |

### Launch
```bash
python -m memedog                       # run the pipeline (scan → … → paper trade)
python scripts/seed_demo.py             # seed sample data for the dashboard demo
streamlit run dashboard/app.py          # live dashboard (signals, funnel, PnL)
```

---

## 7. Tested for real (not just mocks)

Testing is **real-data-driven**, in two tiers:

- **Default suite — `pytest` → 446 tests, fully offline & deterministic.** Every external-API test is driven by **real captured API response bodies** (in [`tests/fixtures/`](tests/fixtures/), refreshable via [`scripts/capture_fixtures.py`](scripts/capture_fixtures.py); secrets/PII never stored). Verified to make **zero external network calls**.
- **Live tier — `pytest -m live` → 9 tests** that hit the real DexScreener / RugCheck / Helius / Codex / Telegram and run a full end-to-end cycle. Each self-skips without its key/binary; Telegram is double-gated (`MEMEDOG_LIVE_TELEGRAM=1`) to avoid accidental sends.

All five external integrations + a full real `run_cycle` have been executed live and confirmed working.

---

## 8. Project structure

```
src/memedog/
├── orchestrator.py        # wires stages 1→6 into the funnel cycle
├── models/                # typed data contracts (TokenCandidate → Signal → TradeRecord)
├── clients/               # one wrapper per API (dexscreener, rugcheck, helius, twitter) + retry base
├── scanner/  hardfilter/  enricher/  scoring/  llmjudge/  papertrader/
├── llm/                   # provider-agnostic LLM layer (codex / litellm) + structured output
├── alert/                 # Telegram
├── config/                # settings.py + thresholds.yaml
└── store.py               # SQLite persistence
dashboard/app.py           # Streamlit board
plan/                      # per-module design docs (00 architecture … 08 data contracts)
docs/superpowers/          # spec + implementation plans
tests/  +  tests/live/     # real-fixture suite + opt-in live tier
```

Per-module design rationale lives in [`plan/`](plan/) — start with [`plan/00-architecture.md`](plan/00-architecture.md).

---

## 9. Scope & limitations (honest)

- **Simulated trading only** — no wallet, no orders. PnL is virtual (ignores slippage/fees by default).
- **Solana-first.** New tokens are usually highly concentrated / no social, so genuine `BULLISH` verdicts are (correctly) rare.
- **Twitter** needs a paid X API tier; without it the social dimension simply degrades.
- **LLM latency** ~50–80 s per verdict (3 calls); acceptable because the funnel only sends a handful of candidates per cycle.

---

*Built for the Bitget AI Hackathon. Research & demonstration use only — not investment advice.*
