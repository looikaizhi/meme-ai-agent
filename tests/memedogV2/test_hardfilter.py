import pytest
from memedogV2.hardfilter.hardfilter import HardFilter
from memedogV2.models.contracts import HardFilterResult
from memedogV2.clients.errors import DataSourceError


class FakeCli:
    def __init__(self, security, info=None):
        self._security, self._info = security, info
        self.calls = []
    async def token_security(self, ca):
        self.calls.append("security"); return self._security
    async def token_info(self, ca):
        self.calls.append("info"); return self._info
    async def token_pool(self, ca):
        self.calls.append("pool"); return {}


def _cfg():
    return {"max_top10_rate": 0.35, "max_creator_rate": 0.10, "max_dev_rate": 0.10,
            "max_sniper_wallets": 20, "max_fresh_wallet_rate": 0.6, "max_bundler_rate": 0.3,
            "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 1.0,
            "max_fdv_to_liquidity": 50}


@pytest.mark.asyncio
async def test_security_failure_short_circuits():
    # mint not revoked -> drop after security; info never called
    cli = FakeCli(security={"renounced_mint": False, "renounced_freeze_account": True})
    hf = HardFilter(cli=cli, cfg=_cfg())
    res = await hf.evaluate("CA", "LP")
    assert isinstance(res, HardFilterResult)
    assert res.passed is False
    assert cli.calls == ["security"]
    assert any("mint" in d for d in res.dropped)


@pytest.mark.asyncio
async def test_clean_token_passes_security_then_info():
    cli = FakeCli(
        security={"renounced_mint": True, "renounced_freeze_account": True,
                  "honeypot": 0, "burn_status": "burn",
                  "lock_summary": {"is_locked": False}},
        info={"liquidity": "50000", "circulating_supply": "1000000",
              "price": {"price": "0.05", "volume_5m": "5000", "buys_5m": 30, "sells_5m": 10},
              "stat": {"top_10_holder_rate": "0.2", "creator_hold_rate": "0",
                       "dev_team_hold_rate": "0", "fresh_wallet_rate": "0",
                       "top_bundler_trader_percentage": "0"},
              "wallet_tags_stat": {"sniper_wallets": 3}})
    hf = HardFilter(cli=cli, cfg=_cfg())
    res = await hf.evaluate("CA", "LP")
    assert res.passed is True
    assert cli.calls == ["security", "info"]


@pytest.mark.asyncio
async def test_high_concentration_drops_after_info():
    cli = FakeCli(
        security={"renounced_mint": True, "renounced_freeze_account": True,
                  "honeypot": 0, "burn_status": "burn", "lock_summary": {"is_locked": True}},
        info={"liquidity": "50000", "circulating_supply": "1000000",
              "price": {"price": "0.05", "volume_5m": "5000", "buys_5m": 30, "sells_5m": 10},
              "stat": {"top_10_holder_rate": "0.9"}})  # 90% top10 -> drop
    hf = HardFilter(cli=cli, cfg=_cfg())
    res = await hf.evaluate("CA", "LP")
    assert res.passed is False
    assert cli.calls == ["security", "info"]
    assert any("top10" in d for d in res.dropped)


@pytest.mark.asyncio
async def test_source_error_pass_flagged():
    class BoomCli:
        async def token_security(self, ca):
            raise DataSourceError("down")
    hf = HardFilter(cli=BoomCli(), cfg=_cfg(), on_failure="pass_flagged")
    res = await hf.evaluate("CA", "LP")
    assert res.passed is True and res.flagged
