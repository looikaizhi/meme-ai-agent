# MemeDog Bitget Momentum

Deterministic GetAgent Playbook package for hosted Bitget backtesting.

This package is intentionally a replayable momentum proxy, not the full live
MemeDog scanner. The production scanner uses live Solana migration data,
RugCheck, enriched holder/liquidity evidence, and LLM debate, which cannot be
fairly reconstructed inside a historical kline-only Playbook run.

Upload and run from the repo root:

```bash
python scripts/run_playbook_backtest.py
```

## 策略

本 Playbook 是 MemeDog 的可重放动量代理策略,用于在 Bitget 支持的合约 K
线数据上做官方云端回测。它不是完整的 Solana scanner,因为毕业币发现、
RugCheck、持币富化和 LLM 辩论都依赖实时证据。

## 开仓

当较快的趋势读数上穿较慢的趋势读数时,策略开多仓。这个逻辑对应 MemeDog
里“已经出现资金持续流入后再考虑”的思路。

## 平仓

当较快的趋势读数重新跌回较慢趋势读数下方时,策略平掉多仓并回到观望状态。

## 风险

横盘、急速反转、交易所衍生品流动性和链上新币流动性脱节时,该策略可能连续
亏损。历史回测不能代表真实交易收益。
