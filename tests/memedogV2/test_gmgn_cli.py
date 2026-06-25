import json
import time
import pytest
from memedogV2.clients.gmgn_cli import GmgnCli
from memedogV2.clients.errors import RateLimitBanned, DataSourceError


class FakeRunner:
    """Records calls; returns queued (returncode, stdout, stderr) tuples."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, args):
        self.calls.append(args)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_token_security_parses_raw_json():
    runner = FakeRunner([(0, json.dumps({"honeypot": False}), "")])
    cli = GmgnCli(runner=runner, rate_per_sec=1000.0, capacity=10, cache_ttl_sec=60)
    out = await cli.token_security("CA")
    assert out == {"honeypot": False}
    assert runner.calls[0][:3] == ["token", "security", "--chain"]


@pytest.mark.asyncio
async def test_cache_avoids_second_subprocess_call():
    runner = FakeRunner([(0, json.dumps({"a": 1}), "")])
    cli = GmgnCli(runner=runner, rate_per_sec=1000.0, capacity=10, cache_ttl_sec=60)
    await cli.token_info("CA")
    await cli.token_info("CA")           # served from cache
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_429_raises_ratelimitbanned_with_reset_at():
    body = json.dumps({"code": 429, "error": "RATE_LIMIT_BANNED", "reset_at": int(time.time()) + 300})
    runner = FakeRunner([(1, body, "rate limit")])
    cli = GmgnCli(runner=runner, rate_per_sec=1000.0, capacity=10, cache_ttl_sec=60)
    with pytest.raises(RateLimitBanned) as ei:
        await cli.token_pool("CA")
    assert ei.value.reset_at is not None


@pytest.mark.asyncio
async def test_nonzero_nonrate_raises_datasourceerror():
    runner = FakeRunner([(2, "", "boom")])
    cli = GmgnCli(runner=runner, rate_per_sec=1000.0, capacity=10, cache_ttl_sec=60)
    with pytest.raises(DataSourceError):
        await cli.token_info("CA")
