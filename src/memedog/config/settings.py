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
    holder_count_full_at: float
    sniper_zero_at: float


class ScoringMomentumConfig(BaseModel):
    liquidity_full_at: float
    volume_5m_full_at: float


class ScoringSocialConfig(BaseModel):
    """Configurable lerp thresholds for the social dimension scorer."""

    smart_money_full_at: float
    twitter_growth_full_at: float
    twitter_growth_zero_at: float


class ScoringConfig(BaseModel):
    weights: dict[str, float]
    holders: ScoringHoldersConfig
    momentum: ScoringMomentumConfig
    social: ScoringSocialConfig
    missing_dimension_weight_factor: float
    neutral_score: float


class CodexConfig(BaseModel):
    bin: str
    timeout_sec: int
    sandbox: str


class ConfidenceGuardConfig(BaseModel):
    """Caps LLM confidence by data completeness (available dimensions / 4)."""

    enabled: bool = True
    floor: float = 0.5


class LLMJudgeConfig(BaseModel):
    models: dict[str, str]
    temperature: dict[str, float]
    max_tokens: int
    repair_retries: int
    codex: CodexConfig
    confidence_guard: ConfidenceGuardConfig = ConfidenceGuardConfig()


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


class HTTPClientPolicy(BaseModel):
    timeout_sec: float = 10.0
    max_retries: int = 3
    backoff_base_sec: float = 0.2
    max_backoff_sec: float = 10.0
    max_concurrency: int = 4
    min_interval_sec: float = 0.0
    retry_status_codes: list[int] = [429, 500, 502, 503, 504]


class HTTPConfig(BaseModel):
    default: HTTPClientPolicy = HTTPClientPolicy()
    # overrides hold partial-field dicts so unspecified fields fall back to default
    overrides: dict[str, dict] = {}

    def policy_for(self, source: str) -> HTTPClientPolicy:
        ov = self.overrides.get(source)
        return self.default.model_copy(update=ov) if ov else self.default


class DiscoveryConfig(BaseModel):
    pumpportal_ws_url: str = "wss://pumpportal.fun/api/data"
    helius_enabled: bool = True
    helius_ws_url: str = "wss://mainnet.helius-rpc.com/?api-key={api_key}"
    pumpfun_program_id: str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    buffer_ttl_min: int = 20
    reconnect_backoff_initial_sec: float = 1.0
    reconnect_backoff_max_sec: float = 30.0
    gmgn_enabled: bool = False
    gmgn_chain: Literal["solana"] = "solana"
    gmgn_chat: str = "solnewlp"
    gmgn_chats: list[str | int] = []
    gmgn_backfill_limit: int = 10
    gmgn_max_open_age_min: int = 30


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
    telegram_api_id: Optional[int] = None
    telegram_api_hash: Optional[str] = None
    telegram_session: Optional[str] = None


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
    http: HTTPConfig = HTTPConfig()
    discovery: DiscoveryConfig = DiscoveryConfig()
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
        http=HTTPConfig.model_validate(raw.get("http", {})),
        discovery=DiscoveryConfig.model_validate(raw.get("discovery", {})),
        settings=Settings(),
    )
