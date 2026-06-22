"""Bitget Playbook prompt export helpers."""
from __future__ import annotations

from memedog.config.settings import PaperTraderConfig


def build_playbook_prompt(strategy_name: str, cfg: PaperTraderConfig) -> str:
    """Return a Bitget Playbook prompt for the MemeDog signal strategy.

    The prompt is meant to be pasted into a coding agent after obtaining a
    Playbook API key, matching Bitget's hackathon Playbook workflow.
    """
    return f"""Install getagent using https://www.npmjs.com/package/@bitget-ai/getagent-skill

Use getagent to create a strategy playbook named "{strategy_name}", then upload,
backtest, and publish it. Once backtest succeeds, show the key metrics in a table.

Strategy philosophy:
Trade only when MemeDog Radar emits a high-conviction BULLISH signal. Treat the
MemeDog score as the objective anchor and the Bull/Bear/Judge rationale as the
final narrative filter. Avoid entries with critical red flags, weak liquidity,
or uncertain holder/rug data. Do not enter on BEARISH or NEUTRAL signals.

Entry rules:
- Enter long only when signal == BULLISH.
- Require confidence >= {cfg.entry_min_confidence:.2f}.
- Prefer score_total >= 70.
- Ignore duplicate open positions for the same asset.

Exit rules:
- Take profit at +{cfg.take_profit_pct * 100:.1f}%.
- Stop loss at -{cfg.stop_loss_pct * 100:.1f}%.
- Timeout exit after {cfg.max_hold_minutes} minutes.
- Position size: {cfg.size_usd:.2f} USD notional per signal.

Risk notes:
This strategy is for research and paper/backtest validation. Meme coins are
high-volatility assets; backtest results must be evaluated with drawdown, win
rate, profit factor, and sample size, not only total PnL.

playbook key: [your Playbook API Key]
"""
