import json
from pathlib import Path

import pytest

from memedog.discovery.buffer import MintBuffer
from memedog.discovery.discoverer import MigrationDiscoverer

_DEX_FX = Path(__file__).resolve().parents[1] / "fixtures" / "dexscreener"


class _Feed:
    def __init__(self, buffer):
        self._b = buffer

    def recent_mints(self):
        return self._b.recent()

    async def run(self, stop_event): ...


class _FakeDex:
    def __init__(self, pairs):
        self._pairs = pairs

    async def get_token_pairs(self, mint):
        return self._pairs


@pytest.mark.asyncio
async def test_fetch_latest_delegates_to_recent_mints():
    buf = MintBuffer(ttl_sec=60)
    buf.add("M1")
    buf.add("M2")
    d = MigrationDiscoverer(feed=_Feed(buf), dex_client=_FakeDex([]))
    assert await d.fetch_latest_token_addresses("solana") == ["M1", "M2"]


@pytest.mark.asyncio
async def test_get_token_pairs_delegates_to_dexscreener():
    body = json.loads((_DEX_FX / "tokens_bonk.json").read_text(encoding="utf-8"))
    pairs = body.get("pairs") or body
    d = MigrationDiscoverer(
        feed=_Feed(MintBuffer(ttl_sec=60)),
        dex_client=_FakeDex(pairs),
    )
    assert await d.get_token_pairs("anymint") == pairs


@pytest.mark.asyncio
async def test_scanner_end_to_end_with_discoverer_produces_candidate():
    from memedog.config import load_config
    from memedog.scanner.scanner import Scanner

    cfg = load_config()
    body = json.loads((_DEX_FX / "tokens_bonk.json").read_text(encoding="utf-8"))
    pairs = body.get("pairs") or body
    buf = MintBuffer(ttl_sec=60)
    mint = pairs[0]["baseToken"]["address"]
    buf.add(mint)
    discoverer = MigrationDiscoverer(feed=_Feed(buf), dex_client=_FakeDex(pairs))
    scanner = Scanner(client=discoverer, cfg=cfg.scanner)
    candidates = await scanner.scan()
    assert isinstance(candidates, list)
    assert all(candidate.chain == "solana" for candidate in candidates)
