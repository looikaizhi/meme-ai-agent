import json
import pytest
from memedogV2.sources.gmgn_source import GmgnSource
from memedogV2.clients.errors import DataSourceError, RateLimitBanned


class FakeCli:
    def __init__(self, security, info, fail_times=0, exc=None):
        self._sec, self._info = security, info
        self._fail_times, self._exc = fail_times, exc
        self.calls = 0

    async def token_security(self, ca):
        return self._sec

    async def token_info(self, ca):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._exc
        return self._info


@pytest.mark.asyncio
async def test_gmgn_source_normalizes_real_fixtures():
    sec = json.load(open("tests/memedogV2/fixtures/sources/gmgn_security.json"))
    info = json.load(open("tests/memedogV2/fixtures/sources/gmgn_info.json"))
    src = GmgnSource(cli=FakeCli(sec, info), max_retries=2)
    pf, rec = await src.fetch("CA", "LP")
    assert pf.liquidity_usd is not None and pf.liquidity_usd > 0
    assert pf.mint_revoked in (True, False)
    assert pf.top10_rate is not None and 0.0 <= pf.top10_rate <= 1.0
    assert rec.tool == "gmgn" and rec.exit_status == 0


@pytest.mark.asyncio
async def test_gmgn_source_retries_transient_then_succeeds():
    sec, info = {"renounced_mint": True}, {"liquidity": "1"}
    cli = FakeCli(sec, info, fail_times=1, exc=DataSourceError("tls blip"))
    src = GmgnSource(cli=cli, max_retries=2)
    pf, rec = await src.fetch("CA", "LP")
    assert cli.calls == 2 and rec.exit_status == 0


@pytest.mark.asyncio
async def test_gmgn_source_gives_up_after_retries():
    cli = FakeCli({"renounced_mint": True}, {}, fail_times=99, exc=DataSourceError("down"))
    src = GmgnSource(cli=cli, max_retries=2)
    pf, rec = await src.fetch("CA", "LP")
    assert pf.liquidity_usd is None and rec.exit_status != 0


@pytest.mark.asyncio
async def test_gmgn_source_does_not_retry_429():
    cli = FakeCli({"renounced_mint": True}, {}, fail_times=99,
                  exc=RateLimitBanned("banned", reset_at=1))
    src = GmgnSource(cli=cli, max_retries=2)
    with pytest.raises(RateLimitBanned):
        await src.fetch("CA", "LP")
