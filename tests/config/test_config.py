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

    # --- Fix 4: scoring.social sub-block ---

    def test_scoring_social_block_present_and_typed(self):
        """scoring.social must load as a ScoringSocialConfig instance."""
        from memedog.config.settings import load_config, ScoringSocialConfig

        cfg = load_config()
        assert isinstance(cfg.scoring.social, ScoringSocialConfig)

    def test_scoring_social_field_types(self):
        """All ScoringSocialConfig fields must be floats."""
        from memedog.config.settings import load_config

        cfg = load_config()
        assert isinstance(cfg.scoring.social.smart_money_full_at, float)
        assert isinstance(cfg.scoring.social.twitter_growth_full_at, float)
        assert isinstance(cfg.scoring.social.twitter_growth_zero_at, float)

    def test_scoring_social_values_match_yaml(self):
        """ScoringSocialConfig values must match thresholds.yaml (yaml as source of truth)."""
        from memedog.config.settings import load_config

        cfg = load_config()
        yaml_social = _THRESHOLDS["scoring"]["social"]
        assert cfg.scoring.social.smart_money_full_at == yaml_social["smart_money_full_at"]
        assert cfg.scoring.social.twitter_growth_full_at == yaml_social["twitter_growth_full_at"]
        assert cfg.scoring.social.twitter_growth_zero_at == yaml_social["twitter_growth_zero_at"]

    # --- Fix 6: scoring.holders new fields ---

    def test_scoring_holders_new_fields_present(self):
        """scoring.holders must include holder_count_full_at and sniper_zero_at."""
        from memedog.config.settings import load_config, ScoringHoldersConfig

        cfg = load_config()
        assert isinstance(cfg.scoring.holders, ScoringHoldersConfig)
        assert isinstance(cfg.scoring.holders.holder_count_full_at, float)
        assert isinstance(cfg.scoring.holders.sniper_zero_at, float)

    def test_scoring_holders_new_fields_match_yaml(self):
        """New holders scoring thresholds must equal thresholds.yaml values."""
        from memedog.config.settings import load_config

        cfg = load_config()
        yaml_holders = _THRESHOLDS["scoring"]["holders"]
        assert cfg.scoring.holders.holder_count_full_at == yaml_holders["holder_count_full_at"]
        assert cfg.scoring.holders.sniper_zero_at == yaml_holders["sniper_zero_at"]


class TestHTTPConfig:
    def test_http_section_present(self):
        from memedog.config.settings import HTTPConfig, load_config

        cfg = load_config()
        assert isinstance(cfg.http, HTTPConfig)

    def test_policy_for_merges_override_onto_default(self):
        from memedog.config.settings import HTTPConfig

        http = HTTPConfig(
            default={"max_concurrency": 4, "min_interval_sec": 0.0, "timeout_sec": 10},
            overrides={"helius": {"min_interval_sec": 0.2}},
        )
        pol = http.policy_for("helius")
        assert pol.min_interval_sec == 0.2   # from override
        assert pol.max_concurrency == 4      # inherited from default
        assert pol.timeout_sec == 10         # inherited from default

    def test_policy_for_unknown_source_returns_default(self):
        from memedog.config.settings import HTTPConfig

        http = HTTPConfig(default={"max_concurrency": 7})
        assert http.policy_for("nope").max_concurrency == 7

    def test_load_config_without_http_section_uses_defaults(self, tmp_path):
        """A yaml missing the http section must still load (backward compat)."""
        import yaml
        from memedog.config.settings import load_config

        raw = yaml.safe_load(_THRESHOLDS_PATH.read_text(encoding="utf-8"))
        raw.pop("http", None)
        p = tmp_path / "no_http.yaml"
        p.write_text(yaml.safe_dump(raw), encoding="utf-8")
        cfg2 = load_config(p)
        assert cfg2.http.default.max_retries >= 1


class TestDiscoveryConfig:
    def test_discovery_config_loaded_with_defaults(self):
        from memedog.config.settings import DiscoveryConfig, load_config

        cfg = load_config()
        assert isinstance(cfg.discovery, DiscoveryConfig)
        assert cfg.discovery.pumpportal_ws_url.startswith("wss://")
        assert isinstance(cfg.discovery.helius_enabled, bool)
        assert cfg.discovery.buffer_ttl_min > 0
        assert isinstance(cfg.discovery.gmgn_enabled, bool)
        assert cfg.discovery.gmgn_chain == "solana"
        assert cfg.discovery.gmgn_chat
        assert cfg.discovery.gmgn_chats
        assert "2122751413" in cfg.discovery.gmgn_chats
        assert "2115686230" not in cfg.discovery.gmgn_chats
        assert "gmgnsignals" not in cfg.discovery.gmgn_chats
        assert cfg.discovery.gmgn_backfill_limit > 0
        assert cfg.discovery.gmgn_max_open_age_min > 0
        assert cfg.discovery.reconnect_backoff_initial_sec > 0
        assert (
            cfg.discovery.reconnect_backoff_max_sec
            >= cfg.discovery.reconnect_backoff_initial_sec
        )
        assert cfg.discovery.pumpfun_program_id

    def test_scanner_min_pair_age_allows_just_graduated(self):
        from memedog.config.settings import load_config

        cfg = load_config()
        assert cfg.scanner.min_pair_age_min == 0

    def test_telegram_user_client_settings_exist(self, monkeypatch):
        from memedog.config.settings import Settings

        monkeypatch.setenv("TELEGRAM_API_ID", "12345")
        monkeypatch.setenv("TELEGRAM_API_HASH", "telegram-api-hash")
        monkeypatch.setenv("TELEGRAM_SESSION", "gmgn-session")
        settings = Settings()
        assert settings.telegram_api_id == 12345
        assert settings.telegram_api_hash == "telegram-api-hash"
        assert settings.telegram_session == "gmgn-session"
