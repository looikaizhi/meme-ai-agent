"""Tests for Task B: Config system.

Per project rules (CLAUDE.md §4) thresholds must NEVER be hardcoded.
These tests use structural / type assertions, or compare against values
loaded directly from thresholds.yaml as a single source of truth.
"""
from pathlib import Path

import yaml
import pytest

# Load the canonical thresholds once at module level so every test can
# reference actual yaml values without duplicating literals.
_THRESHOLDS_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "memedog" / "config" / "thresholds.yaml"
)
with _THRESHOLDS_PATH.open("r", encoding="utf-8") as _fh:
    _THRESHOLDS = yaml.safe_load(_fh)


class TestLoadConfig:
    def test_returns_config_instance(self):
        from memedog.config.settings import Config, load_config

        cfg = load_config()
        assert isinstance(cfg, Config)

    # --- structural section-presence and type checks ---

    def test_all_seven_sections_present_and_typed(self):
        """All 7 config sections must exist and be correctly typed sub-models."""
        from memedog.config.settings import (
            AlertConfig,
            Config,
            EnricherConfig,
            HardFilterConfig,
            LLMJudgeConfig,
            PaperTraderConfig,
            ScannerConfig,
            ScoringConfig,
            load_config,
        )

        cfg = load_config()
        assert isinstance(cfg.scanner, ScannerConfig)
        assert isinstance(cfg.hardfilter, HardFilterConfig)
        assert isinstance(cfg.enricher, EnricherConfig)
        assert isinstance(cfg.scoring, ScoringConfig)
        assert isinstance(cfg.llmjudge, LLMJudgeConfig)
        assert isinstance(cfg.papertrader, PaperTraderConfig)
        assert isinstance(cfg.alert, AlertConfig)

    def test_scanner_section_field_types(self):
        """Scanner fields have the right Python types."""
        from memedog.config.settings import load_config

        cfg = load_config()
        assert isinstance(cfg.scanner.scan_interval_sec, int)
        assert isinstance(cfg.scanner.min_pair_age_min, int)
        assert isinstance(cfg.scanner.max_pair_age_min, int)
        assert isinstance(cfg.scanner.chain, str)
        assert isinstance(cfg.scanner.prefilter_min_liquidity_usd, float)

    def test_scanner_values_match_yaml(self):
        """Scanner numeric values must equal thresholds.yaml (no duplication here)."""
        from memedog.config.settings import load_config

        cfg = load_config()
        yaml_scanner = _THRESHOLDS["scanner"]
        assert cfg.scanner.min_pair_age_min == yaml_scanner["min_pair_age_min"]
        assert cfg.scanner.scan_interval_sec == yaml_scanner["scan_interval_sec"]
        assert cfg.scanner.max_pair_age_min == yaml_scanner["max_pair_age_min"]

    def test_scoring_weights_structural(self):
        """Scoring weights dict must contain the four expected dimension keys."""
        from memedog.config.settings import load_config

        cfg = load_config()
        weights = cfg.scoring.weights
        assert set(weights.keys()) >= {"safety", "holders", "momentum", "social"}
        for v in weights.values():
            assert isinstance(v, float)

    def test_scoring_weights_sum_to_one(self):
        """Scoring weights must sum to 1.0."""
        from memedog.config.settings import load_config

        cfg = load_config()
        assert sum(cfg.scoring.weights.values()) == pytest.approx(1.0, abs=1e-6)

    def test_scoring_weights_match_yaml(self):
        """Each scoring weight must equal thresholds.yaml value."""
        from memedog.config.settings import load_config

        cfg = load_config()
        yaml_weights = _THRESHOLDS["scoring"]["weights"]
        for key, val in yaml_weights.items():
            assert cfg.scoring.weights[key] == pytest.approx(val)

    def test_hardfilter_values_match_yaml(self):
        """HardFilter holder thresholds must equal thresholds.yaml."""
        from memedog.config.settings import load_config

        cfg = load_config()
        yaml_holders = _THRESHOLDS["hardfilter"]["holders"]
        assert cfg.hardfilter.holders.max_top10_pct == yaml_holders["max_top10_pct"]
        assert cfg.hardfilter.holders.max_single_wallet_pct == yaml_holders["max_single_wallet_pct"]
        assert cfg.hardfilter.holders.max_dev_pct == yaml_holders["max_dev_pct"]

    def test_llmjudge_models_has_required_keys(self):
        """llmjudge.models must have bull, bear, and judge keys."""
        from memedog.config.settings import load_config

        cfg = load_config()
        models = cfg.llmjudge.models
        assert "bull" in models
        assert "bear" in models
        assert "judge" in models
        for v in models.values():
            assert isinstance(v, str)

    def test_llmjudge_models_match_yaml(self):
        """llmjudge model strings must equal thresholds.yaml values."""
        from memedog.config.settings import load_config

        cfg = load_config()
        yaml_models = _THRESHOLDS["llmjudge"]["models"]
        assert cfg.llmjudge.models["judge"] == yaml_models["judge"]
        assert cfg.llmjudge.models["bull"] == yaml_models["bull"]
        assert cfg.llmjudge.models["bear"] == yaml_models["bear"]

    def test_settings_attribute_exists(self):
        from memedog.config.settings import load_config

        cfg = load_config()
        # Settings object must exist; API keys default to None when .env absent
        assert cfg.settings is not None
        assert cfg.settings.helius_api_key is None or isinstance(
            cfg.settings.helius_api_key, str
        )

    def test_papertrader_values_match_yaml(self):
        """Papertrader numeric values must equal thresholds.yaml."""
        from memedog.config.settings import load_config

        cfg = load_config()
        yaml_pt = _THRESHOLDS["papertrader"]
        assert cfg.papertrader.size_usd == yaml_pt["size_usd"]
        assert cfg.papertrader.max_hold_minutes == yaml_pt["max_hold_minutes"]
        assert cfg.papertrader.price_poll_sec == yaml_pt["price_poll_sec"]

    def test_alert_values_match_yaml(self):
        """Alert config values must equal thresholds.yaml."""
        from memedog.config.settings import load_config

        cfg = load_config()
        yaml_alert = _THRESHOLDS["alert"]
        assert cfg.alert.only_signal == yaml_alert["only_signal"]
        assert cfg.alert.enabled == yaml_alert["enabled"]
