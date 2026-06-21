"""Capture REAL API response bodies into tests/fixtures/ (no secrets stored).

Re-runnable maintenance tool. Reads keys from .env via load_config().
Stores ONLY response bodies — never headers, URLs, or tokens.

Usage:
    PYTHONPATH=src python scripts/capture_fixtures.py
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from memedog.config import load_config
from memedog.clients.dexscreener import DexScreenerClient
from memedog.clients.rugcheck import RugCheckClient, parse_report
from memedog.clients.helius import HeliusClient

FX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"


def _write(rel: str, body) -> None:
    p = FX / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote", rel)


async def capture_dexscreener() -> None:
    c = DexScreenerClient()
    try:
        profiles = await c.get_json("/token-profiles/latest/v1")
        _write("dexscreener/token_profiles_latest.json", profiles)
        bonk = await c.get_json(f"/latest/dex/tokens/{BONK}")
        _write("dexscreener/tokens_bonk.json", bonk)

        addrs = await c.fetch_latest_token_addresses("solana")
        thin = None
        empty = None
        for a in addrs[:25]:
            data = await c.get_json(f"/latest/dex/tokens/{a}")
            pairs = data.get("pairs") or []
            if not pairs and empty is None:
                empty = data
            if pairs and "liquidity" not in pairs[0] and thin is None:
                thin = data
            if thin is not None and empty is not None:
                break
        _write("dexscreener/tokens_empty.json", empty or {"schemaVersion": "1.0.0", "pairs": None})
        if thin is not None:
            _write("dexscreener/tokens_thin.json", thin)
        else:
            print("note: no thin (missing-liquidity) pair found this run; skipping tokens_thin.json")
    finally:
        await c.aclose()


async def capture_rugcheck() -> None:
    c = RugCheckClient()
    dex = DexScreenerClient()
    try:
        addrs = await dex.fetch_latest_token_addresses("solana")
        found = False
        for a in addrs[:25]:
            try:
                rep = await c.get_token_report(a)
            except Exception:
                continue
            parsed = parse_report(rep)
            if (parsed.get("top10_pct") or 0) > 40:
                _write("rugcheck/report_concentrated.json", rep)
                found = True
                break
        if not found:
            print("note: no concentrated token found this run; report_concentrated.json not updated")
        try:
            await c.get_token_report("11111111111111111111111111111111")
            print("note: invalid-mint report did not error; report_notfound.json not updated")
        except Exception as e:
            _write("rugcheck/report_notfound.json", {"error": str(e)[:200]})
    finally:
        await c.aclose()
        await dex.aclose()


async def capture_helius(cfg) -> None:
    key = cfg.settings.helius_api_key
    if not key:
        print("skip helius (no key)")
        return
    c = HeliusClient(api_key=key)
    dex = DexScreenerClient()
    try:
        addrs = await dex.fetch_latest_token_addresses("solana")
        for a in addrs[:8]:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getTokenLargestAccounts", "params": [a]}
            raw = await c.post_json(c._rpc_url, json=payload)
            if "result" in raw and raw["result"].get("value"):
                _write("helius/largest_accounts_ok.json", raw)
                break
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getTokenLargestAccounts", "params": [BONK]}
        raw = await c.post_json(c._rpc_url, json=payload)
        if "error" in raw:
            _write("helius/largest_accounts_overloaded.json", raw)
        else:
            print("note: BONK did not return overloaded error this run")
        # documented real shape for the empty-result case
        _write("helius/largest_accounts_empty.json", {"jsonrpc": "2.0", "id": 1, "result": {"context": {"slot": 0}, "value": []}})
    finally:
        await c.aclose()
        await dex.aclose()


async def capture_telegram(cfg) -> None:
    tok = cfg.settings.telegram_bot_token
    chat = cfg.settings.telegram_chat_id
    if not (tok and chat):
        print("skip telegram (no creds)")
        return
    import httpx

    def _sanitize_ok(body: dict) -> dict:
        """Strip PII (real chat id / names) from a real success body, keep shape."""
        res = body.get("result") or {}
        if "from" in res:
            res["from"] = {"id": 1000000000, "is_bot": True,
                           "first_name": "memedog bot", "username": "memedog_test_bot"}
        if "chat" in res:
            res["chat"] = {"id": 2000000000, "first_name": "Test", "last_name": "User",
                           "username": "test_user", "type": "private"}
        return body

    async with httpx.AsyncClient(timeout=15) as h:
        ok = (
            await h.post(
                f"https://api.telegram.org/bot{tok}/sendMessage",
                json={"chat_id": chat, "text": "fixture capture (ignore)"},
            )
        ).json()
        _write("telegram/send_ok.json", _sanitize_ok(ok))
        bad = (
            await h.post(
                f"https://api.telegram.org/bot{tok}/sendMessage",
                json={"chat_id": tok, "text": "x"},  # bot -> bot = real 403 body
            )
        ).json()
        _write("telegram/send_forbidden.json", bad)


def capture_twitter_sample() -> None:
    _write(
        "twitter/counts_sample.json",
        {
            "_note": "DOCUMENTED-SHAPE SAMPLE — not live-captured (no API key). Shape per X API v2 /2/tweets/counts/recent.",
            "data": [
                {"start": "2026-01-01T00:00:00.000Z", "end": "2026-01-01T01:00:00.000Z", "tweet_count": 12},
                {"start": "2026-01-01T01:00:00.000Z", "end": "2026-01-01T02:00:00.000Z", "tweet_count": 30},
            ],
            "meta": {"total_tweet_count": 42},
        },
    )


async def main() -> None:
    cfg = load_config()
    await capture_dexscreener()
    await capture_rugcheck()
    await capture_helius(cfg)
    await capture_telegram(cfg)
    capture_twitter_sample()
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
