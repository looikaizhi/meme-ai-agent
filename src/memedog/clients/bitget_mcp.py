"""Bitget market-data MCP client.

This client intentionally exposes the same discovery methods as
``DexScreenerClient`` so the scanner can swap data sources without changing its
business logic.  It uses Bitget's market-data MCP ``dex_market`` tool:

- ``dex_market(action="trending", chain="solana")`` for lightweight discovery
- ``dex_market(action="token", token_address="solana/<mint>")`` for pair data
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from memedog.clients.base import DataSourceError

logger = logging.getLogger(__name__)

_DEFAULT_MCP_URL = "https://datahub.noxiaohao.com/mcp"
_PROTOCOL_VERSION = "2025-06-18"


class BitgetMCPMarketDataClient:
    """Small async client for Bitget's market-data MCP server."""

    def __init__(
        self,
        url: str = _DEFAULT_MCP_URL,
        timeout: float = 15.0,
        max_retries: int = 2,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=timeout)
        self._session_id: str | None = None
        self._next_id = 1

    async def fetch_latest_token_addresses(self, chain: str) -> list[str]:
        """Return recently trending token addresses for *chain*.

        The MCP tool returns provider-shaped payloads, so this parser accepts a
        few common address keys and preserves order while removing duplicates.
        """
        result = await self._call_tool(
            "dex_market",
            {"action": "trending", "chain": chain, "limit": 30},
        )
        items = self._as_items(result)

        addresses: list[str] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("chainId") not in (None, chain):
                continue
            address = self._extract_token_address(item)
            if address and address not in seen:
                seen.add(address)
                addresses.append(address)
        return addresses

    async def get_token_pairs(self, mint: str) -> list[dict]:
        """Return DexScreener-style pair dictionaries for *mint*."""
        token_address = mint if "/" in mint else f"solana/{mint}"
        result = await self._call_tool(
            "dex_market",
            {"action": "token", "token_address": token_address, "limit": 30},
        )

        if isinstance(result, dict):
            pairs = result.get("pairs")
            if isinstance(pairs, list):
                return [pair for pair in pairs if isinstance(pair, dict)]

        items = self._as_items(result)
        if items and all(isinstance(item, dict) for item in items):
            return [item for item in items if isinstance(item, dict)]
        return []

    async def get_token_price(self, mint: str) -> Optional[float]:
        """Fetch the current USD price for *mint* using Bitget MCP pair data."""
        pairs = await self.get_token_pairs(mint)
        if not pairs:
            logger.debug("get_token_price: no pairs for mint=%s", mint)
            return None

        for pair in pairs:
            token = self._token_side_for_mint(pair, mint)
            if token is None:
                continue
            try:
                return float(pair["priceUsd"])
            except (KeyError, TypeError, ValueError) as exc:
                logger.debug(
                    "get_token_price: could not parse priceUsd for mint=%s: %s",
                    mint,
                    exc,
                )
                return None
        return None

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        await self._ensure_session()
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }

        last_exc: Exception | None = None
        for _ in range(self._max_retries):
            try:
                message = await self._post(payload)
                if "error" in message:
                    raise DataSourceError(str(message["error"]))
                result = message.get("result", {})
                if result.get("isError"):
                    raise DataSourceError(str(result))
                return self._decode_content(result.get("content", []))
            except (httpx.HTTPError, DataSourceError, ValueError) as exc:
                last_exc = exc
                logger.warning("Bitget MCP tool %s failed: %s", name, exc)

        raise DataSourceError(f"Bitget MCP tool {name} failed") from last_exc

    async def _ensure_session(self) -> None:
        if self._session_id is not None:
            return

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "memedog-radar", "version": "0.1.0"},
            },
        }
        response = await self._client.post(
            self._url,
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()
        self._session_id = response.headers.get("mcp-session-id")
        if not self._session_id:
            raise DataSourceError("Bitget MCP initialize did not return session id")

        message = self._parse_sse_message(response.text)
        if "error" in message:
            raise DataSourceError(str(message["error"]))

        # Notify the server that the client is ready.  This notification has no
        # response body requirement, so failures are logged but not fatal.
        try:
            await self._client.post(
                self._url,
                headers=self._headers(),
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                },
            )
        except httpx.HTTPError as exc:
            logger.debug("Bitget MCP initialized notification failed: %s", exc)

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(
            self._url,
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()
        return self._parse_sse_message(response.text)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _next_request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    @staticmethod
    def _parse_sse_message(text: str) -> dict[str, Any]:
        data_lines = [
            line.removeprefix("data:").strip()
            for line in text.splitlines()
            if line.startswith("data:")
        ]
        if not data_lines:
            raise ValueError("MCP response did not contain SSE data")
        return json.loads("\n".join(data_lines))

    @staticmethod
    def _decode_content(content: list[dict[str, Any]]) -> Any:
        texts = [
            item.get("text")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        if not texts:
            return None
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except json.JSONDecodeError:
                return texts[0]
        decoded: list[Any] = []
        for text in texts:
            try:
                decoded.append(json.loads(text))
            except json.JSONDecodeError:
                decoded.append(text)
        return decoded

    @staticmethod
    def _as_items(result: Any) -> list[Any]:
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("pairs", "tokens", "items", "data", "results"):
                value = result.get(key)
                if isinstance(value, list):
                    return value
        return []

    @staticmethod
    def _extract_token_address(item: dict[str, Any]) -> str | None:
        for key in ("tokenAddress", "token_address", "address"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value

        base = item.get("baseToken")
        if isinstance(base, dict):
            value = base.get("address")
            if isinstance(value, str) and value:
                return value

        token = item.get("token")
        if isinstance(token, dict):
            value = token.get("address")
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _token_side_for_mint(pair: dict[str, Any], mint: str) -> dict[str, Any] | None:
        raw_mint = mint.split("/", 1)[1] if "/" in mint else mint
        for key in ("baseToken", "quoteToken"):
            token = pair.get(key)
            if not isinstance(token, dict):
                continue
            if token.get("address") == raw_mint:
                return token
        return None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "BitgetMCPMarketDataClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.aclose()
