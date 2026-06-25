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
    async with httpx.AsyncClient(timeout=15.0) as client:
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
                pf = PartialFacts(
                    top10_rate=sum(sorted(amounts, reverse=True)[:10]) / total,
                    max_wallet_rate=max(amounts) / total)
            dur = (time.perf_counter() - t0) * 1000.0
            return pf, ToolCallRecord(tool="helius", command=f"getTokenLargestAccounts {ca}",
                                      input_summary=ca, exit_status=0, duration_ms=dur)
        except Exception as e:
            dur = (time.perf_counter() - t0) * 1000.0
            return PartialFacts(), ToolCallRecord(tool="helius", command=f"getTokenLargestAccounts {ca}",
                                                  input_summary=ca, exit_status=1,
                                                  output_summary=str(e)[:200], duration_ms=dur)
