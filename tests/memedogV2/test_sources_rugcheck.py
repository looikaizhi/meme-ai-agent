import json
import pytest
from memedogV2.sources.rugcheck_source import RugCheckSource


async def _coro(v):
    return v


@pytest.mark.asyncio
async def test_rugcheck_normalizes_real_fixture():
    report = json.load(open("tests/memedogV2/fixtures/sources/rugcheck.json"))
    src = RugCheckSource(fetcher=lambda mint: _coro(report))
    pf, rec = await src.fetch("CA", "LP")
    assert pf.mint_revoked in (True, False, None)
    assert pf.lp_safe in (True, False, None)
    if pf.top10_rate is not None:
        assert 0.0 <= pf.top10_rate <= 1.0
    assert pf.liquidity_usd is None          # rugcheck has no momentum
    assert rec.tool == "rugcheck"


@pytest.mark.asyncio
async def test_rugcheck_real_fixture_lp_locked_true():
    # the captured new-token report has lpLockedPct=100 -> lp_safe must be True
    report = json.load(open("tests/memedogV2/fixtures/sources/rugcheck.json"))
    src = RugCheckSource(fetcher=lambda mint: _coro(report))
    pf, rec = await src.fetch("CA", "LP")
    assert pf.lp_safe is True
    assert pf.mint_revoked is True           # mintAuthority null in fixture


@pytest.mark.asyncio
async def test_rugcheck_failure_degrades_not_raises():
    async def boom(mint):
        raise RuntimeError("network")
    src = RugCheckSource(fetcher=boom)
    pf, rec = await src.fetch("CA", "LP")
    assert pf.mint_revoked is None and rec.exit_status != 0
