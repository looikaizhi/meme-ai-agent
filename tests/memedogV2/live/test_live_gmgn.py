import shutil
import pytest
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.harness.tool_registry import ToolRegistry, GmgnCliToolSource

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_real_gmgn_security_and_info_recorded():
    if shutil.which("gmgn-cli") is None:
        pytest.skip("gmgn-cli not installed")
    reg = ToolRegistry(source=GmgnCliToolSource(GmgnCli(rate_per_sec=1.0, capacity=1)))
    sec, rec_sec = await reg.fetch_security(USDC)
    info, rec_info = await reg.fetch_info(USDC)
    assert sec.get("renounced_mint") is True
    assert "wallet_tags_stat" in info
    assert rec_sec.exit_status == 0 and rec_sec.duration_ms > 0
    assert "security" in rec_sec.command and "info" in rec_info.command
