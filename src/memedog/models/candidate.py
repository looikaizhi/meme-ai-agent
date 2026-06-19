"""TokenCandidate data contract."""
from pydantic import AwareDatetime, BaseModel


class TokenCandidate(BaseModel):
    mint: str
    pair_address: str
    symbol: str
    chain: str = "solana"
    # Fix 10 — enforce timezone-aware datetimes at the model boundary
    pair_created_at: AwareDatetime
    price_usd: float
    liquidity_usd: float
    fdv_usd: float
    volume_5m: float
    volume_1h: float
    txns_5m_buys: int
    txns_5m_sells: int
    price_change_5m: float
    trace_id: str
