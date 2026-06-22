"""Live DexScreener tests — hit the real public API (no key needed).

Run with:  python -m pytest -m live tests/live/test_live_dexscreener.py -v
Excluded from the default suite via `addopts = -m 'not live'`.
"""
import pytest

from memedog.clients.dexscreener import DexScreenerClient
from memedog.config import load_config
from memedog.scanner.scanner import Scanner

pytestmark = pytest.mark.live


async def test_live_fetch_latest_token_addresses():
    client = DexScreenerClient()
    try:
        addrs = await client.fetch_latest_token_addresses("solana")
        assert isinstance(addrs, list)
        assert all(isinstance(a, str) and a for a in addrs)
    finally:
        await client.aclose()


async def test_live_scan_returns_only_solana_candidates():
    cfg = load_config()
    client = DexScreenerClient()
    scanner = Scanner(client=client, cfg=cfg.scanner)
    try:
        candidates = await scanner.scan()
        # Market-dependent: count may be 0; assert structural invariants only.
        assert isinstance(candidates, list)
        assert all(c.chain == "solana" for c in candidates)
        assert all(c.liquidity_usd >= cfg.scanner.prefilter_min_liquidity_usd for c in candidates)
    finally:
        await client.aclose()
