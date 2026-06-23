# HardFilter 参数优化 + AMM 剔除修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 HardFilter 把 AMM 池当持有者的 bug,并把可调参数集中成带注释的调参面板、写入实测优化值,同时把 buy/sell ratio 从硬红线降级为兑底红线 + 打分信号。

**Architecture:** 三个解耦改动 —— (1) `rugcheck.parse_report` 用 `knownAccounts` type==AMM 剔除池账户后再算集中度;(2) `MomentumFilterConfig` 字段 `min_buy_sell_ratio_5m` 改名为 `min_buy_sell_ratio_floor`,`check_momentum` 改兑底语义;(3) `thresholds.yaml` 重排为调参面板并写入新阈值。全程 TDD,外部 API 全 mock,不联网。

**Tech Stack:** Python 3.11+ / pydantic v2 / pytest(`pythonpath=["src"]` 已配,直接 `pytest`)。

参考规范:`docs/superpowers/specs/2026-06-23-hardfilter-param-tuning-design.md`

---

## 文件结构

| 文件 | 责任 | 改动 |
|------|------|------|
| `src/memedog/clients/rugcheck.py` | RugCheck 解析 | 新增 `_amm_accounts`;`parse_report` 剔 AMM 后算 top10/max_wallet/sniper |
| `src/memedog/config/settings.py` | 配置模型 | `MomentumFilterConfig` 字段改名 |
| `src/memedog/hardfilter/rules.py` | 纯规则函数 | `check_momentum` ratio 改兑底 |
| `src/memedog/config/thresholds.yaml` | 调参面板 | 重排 + 注释 + 新值 + 字段改名 |
| `tests/clients/test_rugcheck.py` | 解析单测 | 新增 AMM 剔除用例 |
| `tests/hardfilter/test_rules.py` | 规则单测 | ratio 用例改兑底语义 + 字段改名 |
| `tests/hardfilter/test_hardfilter.py` | 聚合器单测 | 字段改名(4 处) |
| `tests/test_integration_pipeline.py` / `tests/test_orchestrator.py` | 集成单测 | 字段改名(各 1 处) |

---

## Task 1: AMM/LP 池剔除(核心 bug 修复)

**Files:**
- Modify: `src/memedog/clients/rugcheck.py`(新增 `_amm_accounts`;改写 `parse_report` 持币段,约 91–125 行)
- Test: `tests/clients/test_rugcheck.py`

- [ ] **Step 1: 写失败测试**

在 `tests/clients/test_rugcheck.py` 顶部"Synthetic fixtures"区(约 66 行后)追加一个 fixture 常量:

```python
# A graduated-token report: knownAccounts marks AMM pool accounts; topHolders
# contains pool accounts (matched by address AND by owner) that MUST be excluded
# from concentration math.
AMM_POOL_REPORT: dict = {
    "mintAuthority": None,
    "freezeAuthority": None,
    "score_normalised": 10,
    "rugged": False,
    "knownAccounts": {
        "POOLADDR111": {"name": "Pump Fun AMM", "type": "AMM"},
        "POOLOWNER22": {"name": "Pump Fun AMM", "type": "AMM"},
        "CREATORX": {"name": "Creator", "type": "CREATOR"},
    },
    "topHolders": [
        {"address": "POOLADDR111", "pct": 21.0, "owner": "POOLOWNER22", "insider": False},
        {"address": "VAULT2", "pct": 9.0, "owner": "POOLOWNER22", "insider": False},
        {"address": "WHALE1", "pct": 12.0, "owner": "WALLET1", "insider": False},
        {"address": "WHALE2", "pct": 8.0, "owner": "WALLET2", "insider": True},
        {"address": "WHALE3", "pct": 5.0, "owner": "WALLET3", "insider": False},
    ],
    "markets": [{"lp": {"lpLockedPct": 100}}],
    "token": {"supply": 1_000_000, "decimals": 6, "mintAuthority": None, "freezeAuthority": None},
    "creator": "CREATORX",
    "creatorBalance": 0,
}
```

在文件的 `parse_report` 测试区追加这些测试(放在该文件已有的 parse_report 测试类/函数附近;以下用模块级函数即可):

```python
def test_parse_report_excludes_amm_by_address_and_owner():
    """AMM pool accounts (matched via knownAccounts type==AMM, by address OR owner)
    are excluded before computing top10/max_wallet/sniper."""
    from memedog.clients.rugcheck import parse_report

    out = parse_report(AMM_POOL_REPORT)
    # Excluded: POOLADDR111 (address match) and VAULT2 (owner POOLOWNER22 match).
    # Remaining holders: WHALE1=12, WHALE2=8, WHALE3=5  → top10 = 25.0
    assert out["top10_pct"] == pytest.approx(25.0)
    # Largest remaining wallet = WHALE1 = 12.0 (the 21% pool is gone)
    assert out["max_wallet_pct"] == pytest.approx(12.0)
    # Sniper = insider holders among the NON-AMM remainder = WHALE2 = 8.0
    assert out["sniper_pct"] == pytest.approx(8.0)


def test_parse_report_without_known_accounts_falls_back():
    """When knownAccounts is missing, behaviour is the old all-holders sum (no crash)."""
    from memedog.clients.rugcheck import parse_report

    report = dict(AMM_POOL_REPORT)
    report.pop("knownAccounts")
    out = parse_report(report)
    # No exclusion → top10 = 21+9+12+8+5 = 55.0, max_wallet = 21.0
    assert out["top10_pct"] == pytest.approx(55.0)
    assert out["max_wallet_pct"] == pytest.approx(21.0)


def test_parse_report_all_holders_are_amm_yields_none():
    """If every holder is an AMM account, concentration is unassessable → None."""
    from memedog.clients.rugcheck import parse_report

    report = {
        "mintAuthority": None,
        "freezeAuthority": None,
        "score_normalised": 5,
        "rugged": False,
        "knownAccounts": {"P1": {"type": "AMM"}, "P2": {"type": "AMM"}},
        "topHolders": [
            {"address": "P1", "pct": 80.0, "owner": "P1", "insider": False},
            {"address": "x", "pct": 20.0, "owner": "P2", "insider": False},
        ],
        "markets": [{"lp": {"lpLockedPct": 100}}],
        "token": {"supply": 1_000_000, "decimals": 6, "mintAuthority": None, "freezeAuthority": None},
        "creator": "c",
        "creatorBalance": 0,
    }
    out = parse_report(report)
    assert out["top10_pct"] is None
    assert out["max_wallet_pct"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/clients/test_rugcheck.py -k "amm or known_accounts" -v`
Expected: FAIL — `test_parse_report_excludes_amm_by_address_and_owner` 得到 55.0 而非 25.0(当前未剔除);`_amm_accounts` 未定义。

- [ ] **Step 3: 实现**

在 `src/memedog/clients/rugcheck.py` 中,`parse_report` 定义之前新增 helper:

```python
def _amm_accounts(report: dict) -> set[str]:
    """Addresses flagged by RugCheck knownAccounts as AMM/LP pool accounts.

    Returns an empty set when knownAccounts is missing or malformed (the parser
    then degrades to counting all holders — old behaviour, no crash).
    """
    known = report.get("knownAccounts")
    if not isinstance(known, dict):
        return set()
    return {
        addr
        for addr, meta in known.items()
        if isinstance(meta, dict) and meta.get("type") == "AMM"
    }
```

把 `parse_report` 里"holder metrics"整段(从 `top_holders = report.get("topHolders")` 到 `sniper_pct` 计算结束)替换为:

```python
    # --- holder metrics (AMM/LP pool accounts excluded) ---
    raw_holders = report.get("topHolders")
    amm = _amm_accounts(report)
    if raw_holders is None:
        holders: Optional[list] = None
    else:
        holders = [
            h
            for h in raw_holders
            if h.get("address") not in amm and h.get("owner") not in amm
        ]

    # top10_pct: sum of first 10 NON-AMM holders' pct
    top10_pct: Optional[float]
    if not holders:  # None or emptied-by-exclusion → cannot assess
        top10_pct = None
    else:
        top10_pct = sum(h.get("pct", 0.0) for h in holders[:10])

    # max_wallet_pct: largest single NON-AMM holder pct
    max_wallet_pct: Optional[float]
    if not holders:
        max_wallet_pct = None
    else:
        max_wallet_pct = max(h.get("pct", 0.0) for h in holders)

    # dev_pct: creator's share = creatorBalance / token.supply * 100
    dev_pct: Optional[float]
    creator_balance = report.get("creatorBalance")
    token = report.get("token") or {}
    supply = token.get("supply")
    if creator_balance is not None and supply is not None and supply > 0:
        dev_pct = creator_balance / supply * 100
    else:
        dev_pct = None

    # sniper_pct: sum of pct for NON-AMM holders flagged insider=True
    sniper_pct: Optional[float]
    if raw_holders is None:
        sniper_pct = None
    else:
        sniper_pct = sum(
            h.get("pct", 0.0) for h in (holders or []) if h.get("insider") is True
        )
```

> 注:`dev_pct` 段保持原逻辑不变(此处一并贴出仅为保持替换块连续);`mint_authority_revoked` / `freeze_authority_revoked` / `lp_burned_or_locked` / `trust_score` / `risk_level` 段不动。模块顶部 docstring 的 `top10_pct` 描述行可顺手补一句"(excludes knownAccounts AMM)"。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/clients/test_rugcheck.py -v`
Expected: PASS(新增 3 个 + 原有全部)。

- [ ] **Step 5: Commit**

```bash
git add src/memedog/clients/rugcheck.py tests/clients/test_rugcheck.py
git commit -m "fix(rugcheck): exclude AMM/LP pool accounts from holder concentration

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: buy/sell ratio 改名 + 兑底语义

**Files:**
- Modify: `src/memedog/config/settings.py:52`(字段改名)
- Modify: `src/memedog/hardfilter/rules.py`(`check_momentum` ratio 段,约 40、57–63 行)
- Modify: `src/memedog/config/thresholds.yaml:22`(键改名 + 值 0.2,仅这一行;其余值留 Task 3)
- Modify: `tests/hardfilter/test_rules.py`(fixture + ratio 用例)
- Modify: `tests/hardfilter/test_hardfilter.py`(4 处构造)、`tests/test_integration_pipeline.py:191`、`tests/test_orchestrator.py:141`

- [ ] **Step 1: 写失败测试**

改 `tests/hardfilter/test_rules.py` 的 `mom_cfg` fixture(约 24–29 行):

```python
@pytest.fixture
def mom_cfg() -> MomentumFilterConfig:
    return MomentumFilterConfig(
        min_liquidity_usd=20_000.0,
        min_volume_5m=1_000.0,
        min_buy_sell_ratio_floor=0.2,
        max_fdv_to_liquidity=50.0,
    )
```

把 `test_low_buy_sell_ratio_fails_with_reason`(约 121–133 行)替换为两个用例:

```python
    def test_moderate_low_ratio_now_passes(self, mom_cfg):
        """ratio 0.3 (above 0.2 floor) is no longer a hard drop — handled by scoring."""
        from memedog.hardfilter.rules import check_momentum

        passed, _ = check_momentum(
            liquidity_usd=25_000.0,
            volume_5m=2_000.0,
            txns_5m_buys=3,
            txns_5m_sells=10,  # ratio = 0.3
            fdv_usd=100_000.0,
            cfg=mom_cfg,
        )
        assert passed is True

    def test_extreme_low_ratio_fails_floor(self, mom_cfg):
        """ratio 0.1 (below 0.2 floor) is dropped."""
        from memedog.hardfilter.rules import check_momentum

        passed, reason = check_momentum(
            liquidity_usd=25_000.0,
            volume_5m=2_000.0,
            txns_5m_buys=1,
            txns_5m_sells=10,  # ratio = 0.1
            fdv_usd=100_000.0,
            cfg=mom_cfg,
        )
        assert passed is False
        assert "floor" in reason.lower()
```

`test_exact_boundary_values_pass`(ratio=1.0)无需改 —— 1.0 仍 > 0.2,保持 PASS。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/hardfilter/test_rules.py -k "ratio or boundary" -v`
Expected: FAIL — `MomentumFilterConfig` 不接受 `min_buy_sell_ratio_floor`(字段尚未改名)。

- [ ] **Step 3: 实现改名 + 兑底**

`src/memedog/config/settings.py` 第 52 行:

```python
class MomentumFilterConfig(BaseModel):
    min_liquidity_usd: float
    min_volume_5m: float
    min_buy_sell_ratio_floor: float
    max_fdv_to_liquidity: float
```

`src/memedog/hardfilter/rules.py` —— 把 `check_momentum` 的 ratio 段(约 57–63 行)替换为:

```python
    # Rule 3: extreme buy/sell floor (ratio normally feeds scoring, not a hard gate)
    ratio = txns_5m_buys / max(txns_5m_sells, 1)
    if ratio < cfg.min_buy_sell_ratio_floor:
        return (
            False,
            f"momentum:buy_sell_ratio_floor={ratio:.4f} < floor={cfg.min_buy_sell_ratio_floor}",
        )
```

并把该函数 docstring 第 40 行的规则 3 描述改为:`3. extreme floor: ratio = buys / max(sells,1) >= min_buy_sell_ratio_floor`。

`src/memedog/config/thresholds.yaml` 第 22 行(仅这一行,其余值 Task 3 处理):

```yaml
    min_buy_sell_ratio_floor: 0.2
```

更新其余内联构造 `MomentumFilterConfig` 的测试,把 `min_buy_sell_ratio_5m=1.0` 改为 `min_buy_sell_ratio_floor=0.2`:
- `tests/hardfilter/test_hardfilter.py` 第 76、436、459、574 行
- `tests/test_integration_pipeline.py` 第 191 行
- `tests/test_orchestrator.py` 第 141 行

(可用:`grep -rln "min_buy_sell_ratio_5m" tests/` 找全,逐一替换为 `min_buy_sell_ratio_floor`,值 `1.0` → `0.2`。)

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/hardfilter/ tests/test_integration_pipeline.py tests/test_orchestrator.py tests/config/ -q`
Expected: PASS（无 `min_buy_sell_ratio_5m` 残留报错；load_config 正常）。

- [ ] **Step 5: Commit**

```bash
git add src/memedog/config/settings.py src/memedog/hardfilter/rules.py src/memedog/config/thresholds.yaml tests/
git commit -m "refactor(hardfilter): demote buy/sell ratio to a configurable floor gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: thresholds.yaml 调参面板 + 新阈值

**Files:**
- Modify: `src/memedog/config/thresholds.yaml`(`hardfilter` 段,约 9–25 行)
- Test: `tests/config/test_config.py`(已有,动态对比 YAML,无需改;仅复跑验证)

- [ ] **Step 1: 复跑现有 config 测试(基线)**

Run: `pytest tests/config/test_config.py -q`
Expected: PASS（确认改 YAML 前是绿的;该测试读 YAML 动态对比,改值不会破坏它）。

- [ ] **Step 2: 重排 `hardfilter` 段为调参面板并写入新值**

把 `src/memedog/config/thresholds.yaml` 的整个 `hardfilter:` 段替换为:

```yaml
hardfilter:
  # ===== 调参面板:改阈值只动这里,无需改代码 =====
  momentum:                          # 资金/动量门槛(用 Scanner 已有数据,不联网)
    min_liquidity_usd: 13000         # 流动性下限USD | 建议12k~20k | 关:momentum
    min_volume_5m: 300               # 5min成交量下限USD | 建议300~1000 | 关:momentum
    max_fdv_to_liquidity: 8          # FDV/流动性上限 | 建议5~10 | 关:momentum
    min_buy_sell_ratio_floor: 0.2    # 买卖比极端兑底(仅<此值才丢,其余交打分) | 建议0.1~0.3 | 关:momentum
  holders:                           # 持币集中度(占比均已剔除AMM/LP池)
    max_top10_pct: 35                # Top10占比上限% | 建议30~40 | 关:holders
    max_single_wallet_pct: 20        # 单一钱包上限% | 建议15~25 | 关:holders
    max_dev_pct: 10                  # 开发者持仓上限% | 建议5~10 | 关:holders
    max_sniper_pct: 30               # sniper占比上限% | 建议20~30 | 关:holders
  authority:                         # 合约权限红线(任一不过即丢)
    require_mint_revoked: true       # 要求mint权限已放弃 | 关:authority
    require_freeze_revoked: true     # 要求freeze权限已放弃 | 关:authority
    require_lp_burned_or_locked: true # 要求LP已烧毁/锁定 | 关:authority
  on_rugcheck_failure: drop          # RugCheck不可用:drop=保守丢弃 / pass_flagged=放行打标
```

> 注:YAML 数值写成整数(13000、35 等)即可,pydantic `float` 字段会自动接收。

- [ ] **Step 3: 验证 YAML 加载 + 值正确**

Run: `pytest tests/config/test_config.py -q`
Expected: PASS。

再快速断言新值(临时命令,验证后无需保留):

Run:
```bash
python -c "from memedog.config import load_config; c=load_config().hardfilter; print(c.momentum.min_liquidity_usd, c.momentum.min_volume_5m, c.momentum.max_fdv_to_liquidity, c.momentum.min_buy_sell_ratio_floor, c.holders.max_top10_pct)"
```
Expected 输出: `13000.0 300.0 8.0 0.2 35.0`

- [ ] **Step 4: Commit**

```bash
git add src/memedog/config/thresholds.yaml
git commit -m "feat(config): hardfilter tuning panel with retuned thresholds

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 全量回归

**Files:** 无(仅验证)

- [ ] **Step 1: 跑全套测试**

Run: `pytest -q`
Expected: 全绿。若有 `min_buy_sell_ratio_5m` 残留导致的 fail,`grep -rn min_buy_sell_ratio_5m src tests` 定位并改为 `min_buy_sell_ratio_floor`。

- [ ] **Step 2: 确认无残留旧字段名**

Run: `grep -rn "min_buy_sell_ratio_5m" src tests`
Expected: 无输出(全部已改名)。

- [ ] **Step 3:（可选)真实端到端抽查**

可用 scratchpad 里的批量脚本对当前毕业币复跑,确认剔池后 top10 分布回落、活币有过闸的(非计划必需,联网)。

---

## Self-Review 记录

- **Spec 覆盖:** §3 参数表 → Task 2(ratio 改名/floor)、Task 3(liquidity/volume/fdv/holders 值);§4 组件 1 → Task 3;组件 2(AMM 剔除)→ Task 1;组件 3(ratio 降级)→ Task 2;§5 文件清单全部落到 Task 1–3;§6 测试策略 → 各 Task 的 TDD 步 + Task 4。无遗漏。
- **占位符扫描:** 无 TBD/TODO;每个代码步含完整代码与确切命令/期望输出。
- **类型一致性:** 字段名 `min_buy_sell_ratio_floor` 在 settings/rules/yaml/tests 一致;helper `_amm_accounts(report)->set[str]` 在 Task 1 定义并使用;`parse_report` 输出键不变(top10_pct/max_wallet_pct/sniper_pct/dev_pct 等)。
- **顺序依赖:** Task 2 同时改 settings 字段名 + thresholds.yaml 该键,保证 `load_config()` 不中途断裂;Task 3 仅改值/排版,安全。
