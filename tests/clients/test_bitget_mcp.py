"""Tests for Bitget market-data MCP client parsing helpers."""
from __future__ import annotations

import pytest

from memedog.clients.bitget_mcp import BitgetMCPMarketDataClient


def test_parse_sse_message_decodes_json_rpc_payload():
    text = (
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    )

    parsed = BitgetMCPMarketDataClient._parse_sse_message(text)

    assert parsed["jsonrpc"] == "2.0"
    assert parsed["result"]["ok"] is True


def test_decode_content_parses_tool_text_json():
    content = [
        {
            "type": "text",
            "text": '[{"chainId":"solana","baseToken":{"address":"MINT_A"}}]',
        }
    ]

    decoded = BitgetMCPMarketDataClient._decode_content(content)

    assert decoded == [{"chainId": "solana", "baseToken": {"address": "MINT_A"}}]


def test_extract_token_address_accepts_common_bitget_and_dex_shapes():
    assert (
        BitgetMCPMarketDataClient._extract_token_address(
            {"chainId": "solana", "tokenAddress": "MINT_PROFILE"}
        )
        == "MINT_PROFILE"
    )
    assert (
        BitgetMCPMarketDataClient._extract_token_address(
            {"chainId": "solana", "baseToken": {"address": "MINT_BASE"}}
        )
        == "MINT_BASE"
    )
    assert (
        BitgetMCPMarketDataClient._extract_token_address(
            {"chainId": "solana", "token": {"address": "MINT_TOKEN"}}
        )
        == "MINT_TOKEN"
    )


@pytest.mark.asyncio
async def test_get_token_price_uses_matching_mint_pair(monkeypatch):
    client = BitgetMCPMarketDataClient()

    async def fake_get_token_pairs(mint: str):
        return [
            {
                "baseToken": {"address": "OTHER", "symbol": "OTHER"},
                "quoteToken": {"address": "TARGET", "symbol": "DOGE"},
                "priceUsd": "0.00123",
            }
        ]

    monkeypatch.setattr(client, "get_token_pairs", fake_get_token_pairs)

    assert await client.get_token_price("TARGET") == pytest.approx(0.00123)
    await client.aclose()


@pytest.mark.asyncio
async def test_get_token_price_returns_none_when_mint_not_in_pairs(monkeypatch):
    client = BitgetMCPMarketDataClient()

    async def fake_get_token_pairs(mint: str):
        return [
            {
                "baseToken": {"address": "OTHER", "symbol": "OTHER"},
                "quoteToken": {"address": "SOL", "symbol": "SOL"},
                "priceUsd": "0.00123",
            }
        ]

    monkeypatch.setattr(client, "get_token_pairs", fake_get_token_pairs)

    assert await client.get_token_price("TARGET") is None
    await client.aclose()
