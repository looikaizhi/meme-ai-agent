from memedogV2.hardfilter.rules import (
    get_path, num, check_authorities, check_lp,
    check_concentration, check_manipulation, check_momentum,
)


def test_get_path_nested_and_missing():
    assert get_path({"a": {"b": 5}}, "a.b") == 5
    assert get_path({"a": {}}, "a.b") is None
    assert get_path({}, "x") is None


def test_num_coercion():
    assert num("0.35") == 0.35
    assert num("9673213.6") == 9673213.6
    assert num(5) == 5.0
    assert num("") is None
    assert num(None) is None
    assert num("abc") is None


def test_authorities_honeypot_and_revokes():
    assert check_authorities(renounced_mint=True, renounced_freeze=True, honeypot=0)[0] is True
    assert check_authorities(renounced_mint=True, renounced_freeze=True, honeypot=1)[0] is False
    ok, reason = check_authorities(renounced_mint=False, renounced_freeze=True, honeypot=0)
    assert ok is False and "mint" in reason.lower()


def test_lp_burned_or_locked():
    assert check_lp(burn_status="burn", lp_locked=False)[0] is True
    assert check_lp(burn_status="", lp_locked=True)[0] is True
    ok, reason = check_lp(burn_status="", lp_locked=False)
    assert ok is False and "lp" in reason.lower()
    assert check_lp(burn_status=None, lp_locked=None)[0] is True  # unknown -> open


def test_concentration_fraction_threshold():
    cfg = {"max_top10_rate": 0.35, "max_creator_rate": 0.10, "max_dev_rate": 0.10}
    assert check_concentration(top10_rate="0.20", creator_rate="0", dev_rate="0", cfg=cfg)[0] is True
    ok, reason = check_concentration(top10_rate="0.40", creator_rate="0", dev_rate="0", cfg=cfg)
    assert ok is False and "top10" in reason.lower()
    assert check_concentration(top10_rate=None, creator_rate=None, dev_rate=None, cfg=cfg)[0] is True


def test_manipulation_counts_and_rates():
    cfg = {"max_sniper_wallets": 20, "max_fresh_wallet_rate": 0.6, "max_bundler_rate": 0.3}
    assert check_manipulation(sniper_wallets=5, fresh_rate="0.1", bundler_rate="0", cfg=cfg)[0] is True
    ok, _ = check_manipulation(sniper_wallets=50, fresh_rate="0", bundler_rate="0", cfg=cfg)
    assert ok is False


def test_momentum_liquidity_volume_ratio_fdv():
    cfg = {"min_liquidity_usd": 20000, "min_volume_5m": 1000,
           "min_buy_sell_ratio_5m": 1.0, "max_fdv_to_liquidity": 50}
    ok, _ = check_momentum(liquidity="50000", volume_5m="5000", buy_sell=3.0, fdv=100000, cfg=cfg)
    assert ok is True
    ok, reason = check_momentum(liquidity="5000", volume_5m="5000", buy_sell=3.0, fdv=None, cfg=cfg)
    assert ok is False and "liquidity" in reason.lower()
    ok, reason = check_momentum(liquidity="20000", volume_5m="5000", buy_sell=3.0, fdv=2000000, cfg=cfg)
    assert ok is False and "fdv" in reason.lower()
