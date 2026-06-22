"""Live Helius tests — need HELIUS_API_KEY in .env. Self-skip otherwise.

Run with:  python -m pytest -m live tests/live/test_live_helius.py -v
"""
import pytest

from memedog.clients.dexscreener import DexScreenerClient
from memedog.clients.helius import HeliusClient
from memedog.config import load_config

pytestmark = pytest.mark.live


async def test_live_largest_holders_on_fresh_token():
    cfg = load_config()
    if not cfg.settings.helius_api_key:
        pytest.skip("HELIUS_API_KEY not set in .env")

    dex = DexScreenerClient()
    helius = HeliusClient(api_key=cfg.settings.helius_api_key)
    try:
        addrs = await dex.fetch_latest_token_addresses("solana")
        if not addrs:
            pytest.skip("DexScreener returned no fresh tokens this run")
        # Try a few; tokens with huge account sets can return a transient overload error.
        computed = False
        for mint in addrs[:6]:
            res = await helius.get_largest_holders(mint)
            assert set(res) == {"top10_pct", "max_wallet_pct", "holder_count"}
            if res["top10_pct"] is not None:
                assert 0 < res["top10_pct"] <= 100
                assert 0 < res["max_wallet_pct"] <= 100
                computed = True
                break
        if not computed:
            pytest.skip("no token returned computable holders this run (transient)")
    finally:
        await dex.aclose()
        await helius.aclose()
