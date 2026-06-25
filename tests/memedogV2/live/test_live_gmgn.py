import shutil
import pytest
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.sources.gmgn_source import GmgnSource

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_real_gmgn_source_normalizes_and_records():
    if shutil.which("gmgn-cli") is None:
        pytest.skip("gmgn-cli not installed")
    src = GmgnSource(cli=GmgnCli(rate_per_sec=1.0, capacity=1), max_retries=2)
    pf, rec = await src.fetch(USDC, "LP")
    # real normalization: USDC has revoked mint, real momentum, smart-money tags
    assert pf.mint_revoked is True
    assert pf.liquidity_usd is not None and pf.liquidity_usd > 0
    assert pf.smart_money_count is not None
    assert rec.tool == "gmgn" and rec.exit_status == 0 and rec.duration_ms > 0
