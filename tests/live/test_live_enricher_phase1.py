"""Live Phase-1 enricher tests — real calls against alive memecoins.

Run:  python -m pytest -m live tests/live/test_live_enricher_phase1.py -v
Needs HELIUS_API_KEY for the smart-money test (self-skips otherwise).
DexScreener/narrative tests are keyless.
"""
import pytest

from memedog.clients.dexscreener import DexScreenerClient
from memedog.clients.helius import HeliusClient
from memedog.config import load_config
from memedog.enricher.narrative import classify_narrative
from memedog.models import WalletInfo

pytestmark = pytest.mark.live

# Durable, definitely-alive Solana memecoins (verified to have real socials).
ALIVE = {
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
}
_KNOWN_PLATFORMS = {"twitter", "telegram", "discord", "website", "tiktok", "instagram", "reddit", "youtube"}


async def test_live_dexscreener_socials_real_alive_tokens():
    """Real DexScreener: at least one durable memecoin exposes social platforms."""
    dex = DexScreenerClient()
    try:
        any_socials = False
        for sym, mint in ALIVE.items():
            pairs = await dex.get_token_pairs(mint)
            sol = [p for p in pairs if p.get("chainId") == "solana"]
            if not sol:
                continue
            info = (sol[0].get("info") or {})
            platforms = {(s.get("type") or "").lower() for s in (info.get("socials") or [])}
            if info.get("websites"):
                platforms.add("website")
            assert platforms <= _KNOWN_PLATFORMS, f"{sym}: unexpected {platforms}"
            any_socials = any_socials or bool(platforms)
        assert any_socials, "expected at least one durable memecoin to have socials"
    finally:
        await dex.aclose()


async def test_live_narrative_on_real_symbols():
    """Narrative classifier on real alive symbols — valid category + WIF/POPCAT animal."""
    valid = {"animal", "ai", "political", "culture", "finance_utility", "unknown"}
    n_wif = classify_narrative("$WIF", "dogwifhat")
    assert n_wif.category == "animal" and "wif" in n_wif.meme_collision
    n_pop = classify_narrative("POPCAT", "Popcat")
    assert n_pop.category == "animal"
    n_bonk = classify_narrative("Bonk", "Bonk")
    assert "bonk" in n_bonk.meme_collision  # collision even without animal keyword
    assert n_bonk.category in valid


async def test_live_analyze_smart_money_shape_on_real_token():
    """Real Helius: analyze_smart_money returns a sane consensus structure."""
    cfg = load_config()
    if not cfg.settings.helius_api_key:
        pytest.skip("HELIUS_API_KEY not set in .env")
    helius = HeliusClient(api_key=cfg.settings.helius_api_key)
    try:
        library = {"SomeWalletThatMayOrMayNotAppear": WalletInfo(address="SomeWalletThatMayOrMayNotAppear", tier="A")}
        result = await helius.analyze_smart_money(ALIVE["BONK"], library)
        if result is None:
            pytest.skip("Helius transactions endpoint transient failure this run")
        assert set(result) == {"buys", "distinct_wallets", "buyers", "top_tier"}
        assert result["distinct_wallets"] <= result["buys"] or result["buys"] == 0
        assert result["top_tier"] in {"S", "A", "B", None}
        assert isinstance(result["buyers"], list)
    finally:
        await helius.aclose()


async def test_live_empty_library_is_zero_no_network():
    """Empty wallet library must short-circuit to zeros without a network call."""
    cfg = load_config()
    helius = HeliusClient(api_key=cfg.settings.helius_api_key or "unused")
    try:
        result = await helius.analyze_smart_money(ALIVE["WIF"], {})
        assert result == {"buys": 0, "distinct_wallets": 0, "buyers": [], "top_tier": None}
    finally:
        await helius.aclose()
