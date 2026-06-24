from memedogV2.config import load_v2_config


def test_loads_defaults_and_hardfilter_section(tmp_path):
    yaml_path = tmp_path / "t.yaml"
    yaml_path.write_text(
        "gmgn:\n"
        "  rate_limit_rps: 1.0\n"
        "  cache_ttl_sec: 60\n"
        "  max_evidence_calls: 5\n"
        "  on_failure: pass_flagged\n"
        "hardfilter:\n"
        "  max_top10_rate: 0.35\n"
        "  max_creator_rate: 0.10\n"
        "  max_dev_rate: 0.10\n"
        "  max_sniper_wallets: 20\n"
        "  max_fresh_wallet_rate: 0.6\n"
        "  max_bundler_rate: 0.3\n"
        "  min_liquidity_usd: 20000\n"
        "  min_volume_5m: 1000\n"
        "  min_buy_sell_ratio_5m: 1.0\n"
        "  max_fdv_to_liquidity: 50\n"
    )
    cfg = load_v2_config(str(yaml_path))
    assert cfg.gmgn["rate_limit_rps"] == 1.0
    assert cfg.hardfilter["max_top10_rate"] == 0.35
    assert cfg.hardfilter["max_sniper_wallets"] == 20


def test_packaged_default_thresholds_load():
    # the shipped default file must parse and contain the expected keys
    import os, memedogV2
    default = os.path.join(os.path.dirname(memedogV2.__file__), "config_thresholds.yaml")
    cfg = load_v2_config(default)
    for k in ("max_top10_rate", "max_creator_rate", "max_dev_rate", "max_sniper_wallets",
              "max_fresh_wallet_rate", "max_bundler_rate", "min_liquidity_usd",
              "min_volume_5m", "min_buy_sell_ratio_5m", "max_fdv_to_liquidity"):
        assert k in cfg.hardfilter
    assert cfg.gmgn["on_failure"] in ("drop", "pass_flagged")
