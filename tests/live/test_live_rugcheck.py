"""Live RugCheck tests — hit the real public API (no key needed).

Run with:  python -m pytest -m live tests/live/test_live_rugcheck.py -v
"""
import pytest

from memedog.clients.rugcheck import RugCheckClient, parse_report

pytestmark = pytest.mark.live

BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"


async def test_live_bonk_report_parses_sane():
    client = RugCheckClient()
    try:
        report = await client.get_token_report(BONK)
    finally:
        await client.aclose()

    parsed = parse_report(report)
    # BONK is an established token: mint & freeze authority are revoked.
    assert parsed["mint_authority_revoked"] is True
    assert parsed["freeze_authority_revoked"] is True
    # trust_score is a derived 0..100 safety score.
    assert parsed["trust_score"] is None or 0 <= parsed["trust_score"] <= 100
    # holder concentration is a percentage when present.
    if parsed["max_wallet_pct"] is not None:
        assert 0 <= parsed["max_wallet_pct"] <= 100
