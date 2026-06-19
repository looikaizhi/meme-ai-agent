# 模块 08:数据契约(Data Contracts)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。步骤用 `- [ ]` 跟踪。

**Goal:** 定义所有模块间传递的 pydantic 数据对象,作为整个流水线的"接口"。

**Architecture:** 每段流水线的输入输出都是这里定义的不可变(`frozen` 优先)数据对象。先实现本模块,其余模块都 import 这里的类型。

**Tech Stack:** Python 3.11+ / pydantic v2。

---

## 文件结构

```
src/memedog/models/
├── __init__.py        # 导出所有契约
├── candidate.py       # TokenCandidate
├── snapshot.py        # TokenSnapshot + 4 个维度子对象
├── score.py           # Score + DimensionScore
├── signal.py          # Signal + SignalType 枚举
└── trade.py           # Position / TradeRecord
tests/models/
└── test_contracts.py
```

## 数据对象定义

### TokenCandidate(Scanner/HardFilter 产出)
```python
class TokenCandidate(BaseModel):
    mint: str                      # token mint 地址(主键)
    pair_address: str              # DEX pair 地址
    symbol: str
    chain: str = "solana"
    pair_created_at: datetime      # 池创建时间
    price_usd: float
    liquidity_usd: float
    fdv_usd: float
    volume_5m: float
    volume_1h: float
    txns_5m_buys: int
    txns_5m_sells: int
    price_change_5m: float
    trace_id: str                  # 全链路追踪 id
```

### TokenSnapshot(Enricher 产出)
```python
class SafetyInfo(BaseModel):
    available: bool = True
    mint_authority_revoked: bool | None = None
    freeze_authority_revoked: bool | None = None
    lp_burned_or_locked: bool | None = None
    rug_trust_score: int | None = None        # 0~100
    rug_risk_level: str | None = None         # LOW/MEDIUM/HIGH/CRITICAL

class HolderInfo(BaseModel):
    available: bool = True
    top10_pct: float | None = None            # 剔除 LP
    max_wallet_pct: float | None = None
    dev_wallet_pct: float | None = None
    holder_count: int | None = None
    sniper_pct: float | None = None           # 首 120s 抢筹占比

class MomentumInfo(BaseModel):
    available: bool = True
    liquidity_usd: float
    volume_5m: float
    volume_1h: float
    buy_sell_ratio_5m: float
    unique_buyers_1h: int | None = None
    fdv_to_liquidity: float

class SocialInfo(BaseModel):
    available: bool = True
    smart_money_buys: int | None = None       # 标注钱包买入数
    twitter_mentions_1h: int | None = None
    twitter_growth: float | None = None       # 增速

class TokenSnapshot(BaseModel):
    candidate: TokenCandidate
    safety: SafetyInfo
    holders: HolderInfo
    momentum: MomentumInfo
    social: SocialInfo
    enriched_at: datetime
```

### Score(ScoreEngine 产出)
```python
class DimensionScore(BaseModel):
    name: str                  # safety/holders/momentum/social
    raw: float                 # 0~100
    weight: float
    weighted: float            # raw * weight
    notes: list[str] = []      # 缺失/降权说明

class Score(BaseModel):
    mint: str
    total: float               # 0~100 加权总分
    dimensions: list[DimensionScore]
    trace_id: str
```

### Signal(LLMJudge 产出)
```python
class SignalType(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"

class Signal(BaseModel):
    mint: str
    symbol: str
    signal: SignalType
    confidence: float          # 0~1
    score_total: float         # 来自 Score
    bull_points: list[str]
    bear_points: list[str]
    red_flags: list[str]
    rationale: str             # 裁决理由
    created_at: datetime
    trace_id: str
```

### Position / TradeRecord(PaperTrader 产出)
```python
class Position(BaseModel):
    mint: str
    symbol: str
    entry_price: float
    entry_time: datetime
    size_usd: float
    status: str                # OPEN/CLOSED
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
    exit_reason: str           # TP/SL/TIMEOUT
    entry_time: datetime
    exit_time: datetime
```

## 任务

### Task 1: 实现并测试所有契约

**Files:**
- Create: `src/memedog/models/candidate.py` `snapshot.py` `score.py` `signal.py` `trade.py` `__init__.py`
- Test: `tests/models/test_contracts.py`

- [ ] **Step 1: 写失败测试** —— 校验每个对象可构造、字段类型正确、可选维度默认 `available=True`。

```python
from datetime import datetime
from memedog.models import TokenCandidate, TokenSnapshot, SafetyInfo, Score, Signal, SignalType

def test_candidate_minimal():
    c = TokenCandidate(mint="m", pair_address="p", symbol="DOG",
        pair_created_at=datetime.now(), price_usd=1.0, liquidity_usd=20000,
        fdv_usd=1e6, volume_5m=1000, volume_1h=5000, txns_5m_buys=10,
        txns_5m_sells=2, price_change_5m=0.1, trace_id="t1")
    assert c.chain == "solana"

def test_signal_enum():
    assert SignalType("BULLISH") == SignalType.BULLISH
```

- [ ] **Step 2: 跑测试确认失败** — `pytest tests/models/test_contracts.py -v` → FAIL(模块未定义)
- [ ] **Step 3: 按上面定义实现各 pydantic model**
- [ ] **Step 4: 跑测试确认通过** — `pytest tests/models/test_contracts.py -v` → PASS
- [ ] **Step 5: commit** — `git add -A && git commit -m "feat(models): add pipeline data contracts"`

## 备注
- 契约一旦被多个模块引用,**改字段需同步更新所有 plan 文档与依赖模块**。
- 维度子对象用 `available` 标志支持"降级而非崩溃"(见 `03-enricher.md`)。
