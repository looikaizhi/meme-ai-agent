"""Helius Solana RPC/Enhanced API client.

Provides:
  - get_largest_holders: fetches top token holder accounts via getTokenLargestAccounts
  - count_smart_money_buys: best-effort query for recent token transfers by known wallets

LIMITATION: getTokenLargestAccounts returns at most 20 accounts (Solana RPC cap).
Therefore:
  - top10_pct and max_wallet_pct are computed relative to the sum of returned accounts,
    NOT the true total supply. This is a reasonable proxy when accounts are the largest.
  - holder_count is len(returned accounts), a lower bound, not the true holder count.
"""
from __future__ import annotations

import logging
from typing import Optional

from memedog.clients.base import BaseHTTPClient, DataSourceError
from memedog.models import WalletInfo

logger = logging.getLogger(__name__)

_HELIUS_RPC_BASE = "https://mainnet.helius-rpc.com"
_HELIUS_API_BASE = "https://api.helius.xyz"


def _summarize_smart_money(transactions, wallet_library: dict) -> dict:
    """Pure: turn a raw transactions list + labeled wallet library into a
    consensus summary. No I/O — unit-testable with literal data."""
    buys = 0
    matched: dict[str, WalletInfo] = {}
    if isinstance(transactions, list):
        for tx in transactions:
            for transfer in tx.get("tokenTransfers", []):
                addr = transfer.get("toUserAccount")
                if addr in wallet_library:
                    buys += 1
                    matched[addr] = wallet_library[addr]
    buyers = list(matched.values())
    tier_rank = {"S": 3, "A": 2, "B": 1}
    top_tier = None
    ranked = [b.tier for b in buyers if b.tier in tier_rank]
    if ranked:
        top_tier = max(ranked, key=lambda t: tier_rank[t])
    return {
        "buys": buys,
        "distinct_wallets": len(matched),
        "buyers": buyers,
        "top_tier": top_tier,
    }


class HeliusClient(BaseHTTPClient):
    """HTTP client for Helius Solana RPC and Enhanced APIs.

    Parameters
    ----------
    api_key:
        Helius API key appended as a query param on the RPC base URL.
    **kwargs:
        Forwarded to BaseHTTPClient (timeout, max_retries, backoff_base).
    """

    def __init__(self, api_key: str, **kwargs) -> None:
        self._api_key = api_key
        # Store the full RPC URL (with query param) for direct use in requests.
        # We set base_url to "" so _build_url doesn't prepend; instead we pass
        # the absolute URL on each call to avoid double-slash issues.
        self._rpc_url = f"{_HELIUS_RPC_BASE}/?api-key={api_key}"
        kwargs.setdefault("base_url", "")
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_largest_holders(self, mint: str) -> dict:
        """Fetch the largest token accounts for *mint* and compute percentages.

        Calls getTokenLargestAccounts JSON-RPC method.
        Note: RPC returns at most 20 accounts — percentages are relative to
        the sum of returned accounts (not true total supply), making this a
        best-effort approximation.

        Returns
        -------
        dict with keys:
          top10_pct: float | None  — top 10 accounts as % of returned total
          max_wallet_pct: float | None — largest single account %
          holder_count: int | None — count of returned accounts (lower bound)
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenLargestAccounts",
            "params": [mint],
        }
        raw = await self.post_json(self._rpc_url, json=payload)

        # Guard: RPC error body has "error" key instead of "result"
        if "error" in raw or "result" not in raw:
            logger.warning(
                "getTokenLargestAccounts returned error for mint %s: %s",
                mint,
                raw.get("error"),
            )
            return {"top10_pct": None, "max_wallet_pct": None, "holder_count": None}

        accounts = raw["result"].get("value", [])

        if not accounts:
            return {"top10_pct": None, "max_wallet_pct": None, "holder_count": 0}

        amounts = [a.get("uiAmount") or 0.0 for a in accounts]
        total = sum(amounts)

        if total == 0:
            return {"top10_pct": None, "max_wallet_pct": None, "holder_count": len(accounts)}

        top10_sum = sum(amounts[:10])
        top10_pct = top10_sum / total * 100.0
        max_wallet_pct = max(amounts) / total * 100.0
        # holder_count = number of returned accounts; this is a lower bound since
        # the RPC returns at most 20 largest accounts. True count requires indexer.
        holder_count = len(accounts)

        return {
            "top10_pct": top10_pct,
            "max_wallet_pct": max_wallet_pct,
            "holder_count": holder_count,
        }

    async def count_smart_money_buys(
        self, mint: str, smart_wallets: set[str]
    ) -> Optional[int]:
        """Best-effort count of how many recent token buys came from smart wallets.

        BEST-EFFORT approximation for MVP:
          - If smart_wallets is empty, return 0 without any network call.
          - Otherwise, fetch recent TRANSFER transactions for the token via the
            Helius Enhanced Transactions API and count those whose recipient
            (toUserAccount) is in smart_wallets.
          - On any error, return None so the provider can mark the data as
            partially unavailable without failing the whole dimension.

        This is intentionally simple; a production version would use pagination
        and wallet-level buy/sell classification.
        """
        if not smart_wallets:
            return 0

        url = (
            f"{_HELIUS_API_BASE}/v0/addresses/{mint}/transactions"
            f"?api-key={self._api_key}&type=TRANSFER"
        )
        try:
            transactions = await self.get_json(url)
        except DataSourceError as exc:
            logger.warning(
                "count_smart_money_buys: failed to fetch transactions for %s: %s",
                mint,
                exc,
            )
            return None

        count = 0
        if isinstance(transactions, list):
            for tx in transactions:
                for transfer in tx.get("tokenTransfers", []):
                    if transfer.get("toUserAccount") in smart_wallets:
                        count += 1

        return count

    async def analyze_smart_money(self, mint: str, wallet_library: dict) -> dict:
        """Fetch recent TRANSFER txns and summarize labeled-wallet consensus.

        Empty library -> all-zero, no network. On error -> None (provider marks
        the sub-source unavailable; dimension survives).
        """
        if not wallet_library:
            return {"buys": 0, "distinct_wallets": 0, "buyers": [], "top_tier": None}
        url = (
            f"{_HELIUS_API_BASE}/v0/addresses/{mint}/transactions"
            f"?api-key={self._api_key}&type=TRANSFER"
        )
        try:
            transactions = await self.get_json(url)
        except DataSourceError as exc:
            logger.warning("analyze_smart_money: fetch failed for %s: %s", mint, exc)
            return None
        return _summarize_smart_money(transactions, wallet_library)
