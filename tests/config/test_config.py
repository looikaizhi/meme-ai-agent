"""Tests for Task B: Config system."""
import pytest


class TestLoadConfig:
    def test_returns_config_instance(self):
        from memedog.config.settings import Config, load_config

        cfg = load_config()
        assert isinstance(cfg, Config)

    def test_scanner_min_pair_age(self):
        from memedog.config.settings import load_config

        cfg = load_config()
        assert cfg.scanner.min_pair_age_min == 20

    def test_scoring_safety_weight(self):
        from memedog.config.settings import load_config

        cfg = load_config()
        assert cfg.scoring.weights["safety"] == 0.35

    def test_hardfilter_holders_max_top10(self):
        from memedog.config.settings import load_config

        cfg = load_config()
        assert cfg.hardfilter.holders.max_top10_pct == 35

    def test_llmjudge_judge_model(self):
        from memedog.config.settings import load_config

        cfg = load_config()
        assert cfg.llmjudge.models["judge"] == "codex:default"

    def test_settings_attribute_exists(self):
        from memedog.config.settings import load_config

        cfg = load_config()
        # Settings object must exist; API keys default to None when .env absent
        assert cfg.settings is not None
        assert cfg.settings.helius_api_key is None or isinstance(
            cfg.settings.helius_api_key, str
        )

    def test_scanner_scan_interval(self):
        from memedog.config.settings import load_config

        cfg = load_config()
        assert cfg.scanner.scan_interval_sec == 30

    def test_papertrader_size_usd(self):
        from memedog.config.settings import load_config

        cfg = load_config()
        assert cfg.papertrader.size_usd == 100

    def test_alert_only_signal(self):
        from memedog.config.settings import load_config

        cfg = load_config()
        assert cfg.alert.only_signal == "BULLISH"
