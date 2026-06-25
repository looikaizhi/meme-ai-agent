import json
import pytest
from memedogV2.harness.tool_registry import ToolRegistry, FixtureToolSource


@pytest.mark.asyncio
async def test_fixture_source_records_tool_calls():
    src = FixtureToolSource(security={"renounced_mint": True}, info={"liquidity": "50000"})
    reg = ToolRegistry(source=src)
    sec, rec_sec = await reg.fetch_security("CA")
    info, rec_info = await reg.fetch_info("CA")
    assert sec == {"renounced_mint": True}
    assert info == {"liquidity": "50000"}
    assert rec_sec.tool == "gmgn-cli" and "security" in rec_sec.command
    assert rec_sec.exit_status == 0 and rec_info.exit_status == 0


@pytest.mark.asyncio
async def test_gmgncli_source_wraps_client():
    class FakeCli:
        async def token_security(self, ca): return {"a": 1}
        async def token_info(self, ca): return {"b": 2}
    from memedogV2.harness.tool_registry import GmgnCliToolSource
    reg = ToolRegistry(source=GmgnCliToolSource(FakeCli()))
    sec, rec = await reg.fetch_security("CA")
    assert sec == {"a": 1} and rec.output_summary  # summary is non-empty
