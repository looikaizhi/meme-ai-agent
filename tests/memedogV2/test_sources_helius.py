import json
import pytest
from memedogV2.sources.helius_source import HeliusSource


async def _coro(v):
    return v


@pytest.mark.asyncio
async def test_helius_normalizes_largest_accounts():
    payload = {"result": {"value": [{"uiAmount": 50.0}, {"uiAmount": 30.0}, {"uiAmount": 20.0}]}}
    src = HeliusSource(fetcher=lambda mint: _coro(payload))
    pf, rec = await src.fetch("CA", "LP")
    assert abs(pf.top10_rate - 1.0) < 1e-9
    assert abs(pf.max_wallet_rate - 0.5) < 1e-9
    assert rec.tool == "helius"


@pytest.mark.asyncio
async def test_helius_real_fixture_parses():
    payload = json.load(open("tests/memedogV2/fixtures/sources/helius.json"))
    src = HeliusSource(fetcher=lambda mint: _coro(payload))
    pf, rec = await src.fetch("CA", "LP")
    assert pf.top10_rate is not None and 0.0 <= pf.top10_rate <= 1.0
    assert rec.exit_status == 0


@pytest.mark.asyncio
async def test_helius_error_body_degrades():
    # Helius JSON-RPC error body (overloaded) -> no value -> degrade, not crash
    payload = {"jsonrpc": "2.0", "error": {"code": -32603, "message": "overloaded"}, "id": 1}
    src = HeliusSource(fetcher=lambda mint: _coro(payload))
    pf, rec = await src.fetch("CA", "LP")
    assert pf.top10_rate is None and rec.exit_status == 0   # parsed ok, just no data


@pytest.mark.asyncio
async def test_helius_failure_degrades():
    async def boom(mint):
        raise RuntimeError("rpc down")
    src = HeliusSource(fetcher=boom)
    pf, rec = await src.fetch("CA", "LP")
    assert pf.top10_rate is None and rec.exit_status != 0
