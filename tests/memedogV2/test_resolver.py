import pytest
from memedogV2.sources.base import PartialFacts
from memedogV2.sources.resolver import DataResolver, ResolvedFacts
from memedogV2.harness.contracts import ToolCallRecord
from memedogV2.clients.errors import RateLimitBanned


class StubSource:
    def __init__(self, name, partial, ok=True):
        self.name = name
        self._pf = partial
        self._ok = ok

    async def fetch(self, ca, lp):
        rec = ToolCallRecord(tool=self.name, command=f"x {ca}", exit_status=0 if self._ok else 1)
        return self._pf, rec


@pytest.mark.asyncio
async def test_priority_merge_prefers_rugcheck_then_gmgn():
    rug = StubSource("rugcheck", PartialFacts(mint_revoked=True, top10_rate=0.2))
    gmgn = StubSource("gmgn", PartialFacts(mint_revoked=False, top10_rate=0.9,
                                           liquidity_usd=50000, volume_5m=5000,
                                           buys_5m=10, sells_5m=2))
    r = DataResolver(sources={"rugcheck": rug, "gmgn": gmgn})
    out = await r.resolve("CA", "LP")
    assert isinstance(out, ResolvedFacts)
    assert out.facts.mint_revoked is True
    assert out.facts.top10_rate == 0.2
    assert out.facts.liquidity_usd == 50000
    assert out.sources["mint_revoked"] == "rugcheck"
    assert out.sources["liquidity_usd"] == "gmgn"
    assert len(out.attempts) == 2
    assert out.momentum_unavailable is False


@pytest.mark.asyncio
async def test_primary_failure_falls_back_to_gmgn():
    rug = StubSource("rugcheck", PartialFacts(), ok=False)
    gmgn = StubSource("gmgn", PartialFacts(mint_revoked=True, liquidity_usd=1,
                                           volume_5m=1, buys_5m=1, sells_5m=1))
    r = DataResolver(sources={"rugcheck": rug, "gmgn": gmgn})
    out = await r.resolve("CA", "LP")
    assert out.facts.mint_revoked is True
    assert out.sources["mint_revoked"] == "gmgn"


@pytest.mark.asyncio
async def test_momentum_unavailable_flagged_when_gmgn_missing_it():
    gmgn = StubSource("gmgn", PartialFacts(mint_revoked=True))
    r = DataResolver(sources={"gmgn": gmgn})
    out = await r.resolve("CA", "LP")
    assert out.momentum_unavailable is True


@pytest.mark.asyncio
async def test_source_raising_is_tolerated():
    class Boom:
        name = "rugcheck"
        async def fetch(self, ca, lp):
            raise RuntimeError("network")
    gmgn = StubSource("gmgn", PartialFacts(mint_revoked=True, liquidity_usd=1,
                                           volume_5m=1, buys_5m=1, sells_5m=1))
    r = DataResolver(sources={"rugcheck": Boom(), "gmgn": gmgn})
    out = await r.resolve("CA", "LP")               # must not raise
    assert out.facts.mint_revoked is True
    assert any(a.tool == "rugcheck" and a.exit_status != 0 for a in out.attempts)


@pytest.mark.asyncio
async def test_ratelimit_banned_propagates():
    class Banned:
        name = "gmgn"
        async def fetch(self, ca, lp):
            raise RateLimitBanned("banned", reset_at=1)
    r = DataResolver(sources={"gmgn": Banned()})
    with pytest.raises(RateLimitBanned):
        await r.resolve("CA", "LP")
