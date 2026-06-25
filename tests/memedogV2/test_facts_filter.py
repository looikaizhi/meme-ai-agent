from memedogV2.hardfilter.facts_filter import evaluate_facts, evaluate_facts_detail
from memedogV2.sources.base import Facts

CFG = {"max_top10_rate": 0.35, "max_creator_rate": 0.10, "max_dev_rate": 0.10,
       "hard_max_top10_rate": 0.55, "max_sniper_wallets": 20, "hard_max_sniper_wallets": 40,
       "max_fresh_wallet_rate": 0.6, "hard_max_fresh_wallet_rate": 0.7,
       "max_bundler_rate": 0.3, "hard_max_bundler_rate": 0.5,
       "min_liquidity_usd": 20000, "min_volume_5m": 1000, "min_buy_sell_ratio_5m": 0.8,
       "soft_min_buy_sell_ratio_5m": 1.0, "max_fdv_to_liquidity": 50}


def _clean():
    return Facts(mint_revoked=True, freeze_revoked=True, honeypot=False, lp_safe=True,
                 top10_rate=0.2, creator_rate=0.0, dev_rate=0.0, sniper_count=3,
                 fresh_wallet_rate=0.0, bundler_rate=0.0, liquidity_usd=50000,
                 volume_5m=5000, buys_5m=30, sells_5m=10, price_usd=0.05,
                 circulating_supply=1000000)


def test_clean_facts_pass():
    passed, dropped = evaluate_facts(_clean(), CFG)
    assert passed is True and dropped == []


def test_mint_not_revoked_drops():
    f = _clean(); f.mint_revoked = False
    passed, dropped = evaluate_facts(f, CFG)
    assert passed is False and any("mint" in d for d in dropped)


def test_lp_unsafe_drops():
    f = _clean(); f.lp_safe = False
    passed, dropped = evaluate_facts(f, CFG)
    assert passed is False and any("LP" in d for d in dropped)


def test_pending_stage_lp_unsafe_flags_not_drops():
    f = _clean(); f.lp_safe = False
    decision = evaluate_facts_detail(f, CFG, stage="new_creation")
    assert decision.passed is True
    assert decision.dropped == []
    assert any("LP" in flag for flag in decision.flagged)


def test_honeypot_drops():
    f = _clean(); f.honeypot = True
    passed, dropped = evaluate_facts(f, CFG)
    assert passed is False


def test_high_concentration_drops():
    f = _clean(); f.top10_rate = 0.9
    passed, dropped = evaluate_facts(f, CFG)
    assert passed is False and any("top10" in d for d in dropped)


def test_soft_concentration_flags_not_drops():
    f = _clean(); f.top10_rate = 0.4
    decision = evaluate_facts_detail(f, CFG)
    assert decision.passed is True
    assert any("top10" in flag for flag in decision.flagged)


def test_borderline_buy_sell_flags_not_drops():
    f = _clean(); f.buys_5m = 9; f.sells_5m = 10
    decision = evaluate_facts_detail(f, CFG)
    assert decision.passed is True
    assert any("buy/sell" in flag for flag in decision.flagged)


def test_low_liquidity_drops():
    f = _clean(); f.liquidity_usd = 5000
    passed, dropped = evaluate_facts(f, CFG)
    assert passed is False and any("liquidity" in d for d in dropped)


def test_missing_values_degrade_open():
    # all-None facts (except momentum present so momentum rule has data) -> pass
    f = Facts(liquidity_usd=50000, volume_5m=5000, buys_5m=30, sells_5m=10,
              price_usd=0.05, circulating_supply=1000000)
    passed, dropped = evaluate_facts(f, CFG)
    assert passed is True
