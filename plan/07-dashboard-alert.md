# 模块 07:Dashboard & Alert(看板与告警)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。

**Goal:** 一个轻量 Streamlit 看板展示全链路(候选→信号→模拟仓位→盈亏);可选 Telegram 告警在出 BULLISH 信号时推送。

**Architecture:** 看板是**只读消费者**——只从 `store.py`(SQLite)读数据渲染,不参与流水线决策,因此可独立启动、不影响主循环。Alert 是流水线里一个旁路:`orchestrator` 在拿到信号后调 `alert.maybe_notify(signal)`。

**Tech Stack:** Streamlit、SQLite(读)、Telegram Bot API(可选)。

---

## 职责边界
- **Dashboard**:读 store → 展示。绝不写、不触发交易。
- **Alert**:格式化信号 → 推 Telegram。缺 token 时静默跳过(不报错)。

## 文件结构

```
dashboard/app.py                      # Streamlit 入口
src/memedog/alert/telegram.py         # TelegramAlert
src/memedog/alert/__init__.py         # maybe_notify(signal, cfg) 门面
tests/alert/test_telegram.py
```

## 看板页面(演示用,4 个区块)

1. **实时信号流**:最近 N 条 `Signal`(symbol、signal 带颜色、confidence、score_total、bull/bear 要点、red_flags)。
2. **模拟交易**:当前 OPEN 仓 + 已平仓成交表;顶部汇总卡片:总盈亏、胜率、平均持仓时长、累计余额曲线。
3. **候选漏斗**:本轮 扫描数 → 过 HardFilter 数 → 出信号数;以及被丢弃候选及命中的红线规则(调参用)。
4. **配置快照**:当前 thresholds.yaml 关键阈值与所选 LLM 模型(便于演示"改配置即改策略")。

## 配置(.env / thresholds.yaml -> alert 段)

```yaml
alert:
  enabled: true
  only_signal: BULLISH        # 只推某类信号
  min_confidence: 0.6
# .env: TELEGRAM_BOT_TOKEN=..., TELEGRAM_CHAT_ID=...(缺失则 alert 自动禁用)
```

## 任务

### Task 1: TelegramAlert + maybe_notify 门面

**Files:** Create `src/memedog/alert/telegram.py`, `src/memedog/alert/__init__.py`; Test `tests/alert/test_telegram.py`

- [ ] **Step 1: 写失败测试**

```python
async def test_maybe_notify_skips_when_disabled(cfg_no_token):
    sent = await maybe_notify(make_signal("BULLISH", 0.9), cfg_no_token)
    assert sent is False     # 缺 token → 静默跳过

async def test_maybe_notify_filters_low_confidence(cfg, fake_tg):
    await maybe_notify(make_signal("BULLISH", 0.3), cfg, client=fake_tg)
    assert fake_tg.calls == []   # 低于 min_confidence 不推
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现**
  - `TelegramAlert.send(text)`:POST `https://api.telegram.org/bot<token>/sendMessage`(继承 base client)。
  - `maybe_notify(signal, cfg, client=None)`:校验 enabled、only_signal、min_confidence、token 存在 → 格式化消息(symbol/signal/confidence/score/red_flags)→ 发送;任一不满足返回 False。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(alert): telegram notify with filters"`

### Task 2: Streamlit 看板

**Files:** Create `dashboard/app.py`

- [ ] **Step 1: 实现 4 区块**(看板偏展示,采用人工验证而非单测)
  - 用 `Store` 读 signals / open_positions / trades / 漏斗统计。
  - 汇总卡:总盈亏、胜率=盈利单/总单、平均持仓时长。
  - signal 颜色:BULLISH 绿 / BEARISH 红 / NEUTRAL 灰。
  - `st.autorefresh`(或定时 rerun)实现准实时。
- [ ] **Step 2: 人工验证** — 灌入若干测试数据后运行 `streamlit run dashboard/app.py`,确认 4 区块正确渲染、汇总数字与库中一致。
- [ ] **Step 3: commit** — `git commit -m "feat(dashboard): streamlit overview"`

## 备注
- 看板与主循环**分进程运行**(看板 `streamlit run`,流水线 `python -m memedog`),通过同一 SQLite 文件解耦。
- 演示脚本建议:准备一个 `seed_demo.py` 灌入示例快照/信号/成交,保证 demo 即使无实时新盘也有内容可看。
