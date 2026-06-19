"""Config system for MemeDog Radar.

Loads thresholds.yaml into typed pydantic v2 models, and reads optional
secrets from .env via pydantic-settings.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_YAML = Path(__file__).parent / "thresholds.yaml"
# Anchor .env to the project root (three parents up from this file:
#   settings.py → config/ → memedog/ → src/ → project root)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Section sub-models
# ---------------------------------------------------------------------------


class ScannerConfig(BaseModel):
    scan_interval_sec: int
    chain: str
    min_pair_age_min: int
    max_pair_age_min: int
    prefilter_min_liquidity_usd: float
    prefilter_min_volume_5m: float
    dedup_ttl_min: int


class AuthorityFilterConfig(BaseModel):
    require_mint_revoked: bool
    require_freeze_revoked: bool
    require_lp_burned_or_locked: bool


class HoldersFilterConfig(BaseModel):
    max_top10_pct: float
    max_single_wallet_pct: float
    max_dev_pct: float
    max_sniper_pct: float


class MomentumFilterConfig(BaseModel):
    min_liquidity_usd: float
    min_volume_5m: float
    min_buy_sell_ratio_5m: float
    max_fdv_to_liquidity: float


class HardFilterConfig(BaseModel):
    authority: AuthorityFilterConfig
    holders: HoldersFilterConfig
    momentum: MomentumFilterConfig
    on_rugcheck_failure: Literal["drop", "pass_flagged"]


class EnricherConfig(BaseModel):
    per_provider_timeout_sec: float
    smart_money_wallets_file: str
    twitter_lookback_min: int


class ScoringHoldersConfig(BaseModel):
    top10_full_score_at: float
    top10_zero_score_at: float
    max_wallet_zero_at: float


class ScoringMomentumConfig(BaseModel):
    liquidity_full_at: float
    volume_5m_full_at: float


class ScoringConfig(BaseModel):
    weights: dict[str, float]
    holders: ScoringHoldersConfig
    momentum: ScoringMomentumConfig
    missing_dimension_weight_factor: float
    neutral_score: float


class CodexConfig(BaseModel):
    bin: str
    timeout_sec: int
    sandbox: str


class LLMJudgeConfig(BaseModel):
    models: dict[str, str]
    temperature: dict[str, float]
    max_tokens: int
    repair_retries: int
    codex: CodexConfig


class PaperTraderConfig(BaseModel):
    entry_min_confidence: float
    size_usd: float
    take_profit_pct: float
    stop_loss_pct: float
    max_hold_minutes: int
    price_poll_sec: int
    starting_balance_usd: float


class AlertConfig(BaseModel):
    enabled: bool
    only_signal: str
    min_confidence: float


# ---------------------------------------------------------------------------
# Settings (secrets from .env)
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"), extra="ignore"
    )

    helius_api_key: Optional[str] = None
    rugcheck_api_key: Optional[str] = None
    twitter_bearer: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Top-level Config container
# ---------------------------------------------------------------------------


class Config(BaseModel):
    scanner: ScannerConfig
    hardfilter: HardFilterConfig
    enricher: EnricherConfig
    scoring: ScoringConfig
    llmjudge: LLMJudgeConfig
    papertrader: PaperTraderConfig
    alert: AlertConfig
    settings: Settings


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(yaml_path: str | Path | None = None) -> Config:
    """Load configuration from *yaml_path* (defaults to packaged thresholds.yaml)."""
    path = Path(yaml_path) if yaml_path is not None else _DEFAULT_YAML
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    return Config(
        scanner=ScannerConfig.model_validate(raw["scanner"]),
        hardfilter=HardFilterConfig.model_validate(raw["hardfilter"]),
        enricher=EnricherConfig.model_validate(raw["enricher"]),
        scoring=ScoringConfig.model_validate(raw["scoring"]),
        llmjudge=LLMJudgeConfig.model_validate(raw["llmjudge"]),
        papertrader=PaperTraderConfig.model_validate(raw["papertrader"]),
        alert=AlertConfig.model_validate(raw["alert"]),
        settings=Settings(),
    )
