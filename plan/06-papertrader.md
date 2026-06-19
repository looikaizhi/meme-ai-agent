# 模块 06:PaperTrader(模拟交易)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。

**Goal:** 收到 BULLISH 信号时开"虚拟仓",周期轮询价格,按止盈/止损/超时规则平仓,记录虚拟盈亏。**不接真实钱包、不真实下单。**

**Architecture:** 两部分。`PaperTrader` 管仓位生命周期(开/查/平);一个独立的 `PriceWatcher` 协程周期性拉所有 OPEN 仓的最新价并触发平仓判定。仓位与成交记录落 SQLite(`store.py`),供看板读。

**Tech Stack:** asyncio、SQLite、DexScreener(取最新价,复用 client)。

---

## 职责边界
- **做**:按信号开虚拟仓、按规则平仓、算盈亏、持久化。
- **不做**:真实交易、信号生成。
- 入场策略(演示版,可配):`signal == BULLISH and confidence >= entry_min_confidence` → 开固定 `size_usd` 虚拟仓;同一 mint 不重复开仓。

## 平仓规则(可配)
| 规则 | 默认 | 说明 |
|------|------|------|
| 止盈 take_profit | +50% | 涨到入场价 *1.5 平仓 |
| 止损 stop_loss | -25% | 跌到入场价 *0.75 平仓 |
| 超时 max_hold | 120 min | 到时强平(meme 币不留隔夜) |

`exit_reason` ∈ {TP, SL, TIMEOUT}。

## 文件结构

```
src/memedog/papertrader/trader.py       # PaperTrader:开/平仓 + 盈亏
src/memedog/papertrader/watcher.py      # PriceWatcher:轮询价格协程
src/memedog/store.py                     # SQLite 持久化(仓位/成交/快照/信号)
tests/papertrader/test_trader.py
tests/papertrader/test_watcher.py
```

## 配置(thresholds.yaml -> papertrader 段)

```yaml
papertrader:
  entry_min_confidence: 0.6
  size_usd: 100
  take_profit_pct: 0.50
  stop_loss_pct: 0.25
  max_hold_minutes: 120
  price_poll_sec: 30
  starting_balance_usd: 10000
```

## 任务

### Task 1: store.py(SQLite 持久化)

**Files:** Create `src/memedog/store.py`; Test `tests/test_store.py`

- [ ] **Step 1: 写失败测试** — 用临时 sqlite 文件,断言可存/取 Position 与 TradeRecord,可查所有 OPEN 仓。
- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现** — `Store(db_path)`:`save_position / update_position / open_positions() / save_trade / all_trades()`;表结构对应 `08` 的 Position/TradeRecord。同时提供 `save_snapshot/save_signal` 供看板。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(store): sqlite persistence"`

### Task 2: PaperTrader(开/平仓 + 盈亏)

**Files:** Create `src/memedog/papertrader/trader.py`; Test `tests/papertrader/test_trader.py`

- [ ] **Step 1: 写失败测试**

```python
def test_on_signal_opens_position_when_bullish(store, cfg):
    pt = PaperTrader(store=store, cfg=cfg)
    sig = make_signal(signal="BULLISH", confidence=0.8, price=1.0)
    pt.on_signal(sig, entry_price=1.0)
    assert len(store.open_positions()) == 1

def test_on_signal_skips_low_confidence(store, cfg):
    pt = PaperTrader(store=store, cfg=cfg)
    pt.on_signal(make_signal("BULLISH", 0.3, 1.0), entry_price=1.0)
    assert store.open_positions() == []

def test_evaluate_take_profit():
    pt = PaperTrader(store=store, cfg=cfg)   # tp=0.5
    pos = make_open_position(entry_price=1.0)
    rec = pt.evaluate(pos, current_price=1.6)   # +60% → 触发 TP
    assert rec.exit_reason == "TP" and rec.pnl_pct > 0
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现**
  - `on_signal(signal, entry_price)`:满足入场条件且无同 mint 持仓 → 建 Position(写 tp/sl/max_hold)存库。
  - `evaluate(position, current_price, now)`:依次判 TP / SL / TIMEOUT → 命中则算 `pnl_usd/pnl_pct` 返回 TradeRecord、置仓 CLOSED;否则返回 None。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(papertrader): open/close + pnl"`

### Task 3: PriceWatcher(轮询协程)

**Files:** Create `src/memedog/papertrader/watcher.py`; Test `tests/papertrader/test_watcher.py`

- [ ] **Step 1: 写失败测试** — 注入 fake 价格源,模拟价格突破止盈,断言 watcher 一轮后该仓被平且 store 有 TradeRecord。
- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现 `run()`** — 周期 `price_poll_sec`:取所有 OPEN 仓 → 批量拉最新价(DexScreener)→ 对每仓调 `trader.evaluate` → 命中则落库。单个取价失败跳过该仓,不中断。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(papertrader): price watcher loop"`

## 备注
- 入场价取信号生成时的 `candidate.price_usd`(或开仓瞬间最新价,二选一,写入 config)。
- 盈亏为虚拟,基于价格变动 * size,演示忽略滑点/手续费(可在 config 加 `fee_pct` 后续细化)。
- 汇总指标(总盈亏、胜率、平均持仓时长)由看板从 `all_trades()` 计算,PaperTrader 不重复算。
