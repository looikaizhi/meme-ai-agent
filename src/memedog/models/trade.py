"""Trade data contracts."""
from datetime import datetime

from pydantic import BaseModel


class Position(BaseModel):
    mint: str
    symbol: str
    entry_price: float
    entry_time: datetime
    size_usd: float
    status: str
    take_profit_pct: float
    stop_loss_pct: float
    max_hold_minutes: int


class TradeRecord(BaseModel):
    mint: str
    symbol: str
    entry_price: float
    exit_price: float
    pnl_usd: float
    pnl_pct: float
    exit_reason: str
    entry_time: datetime
    exit_time: datetime
