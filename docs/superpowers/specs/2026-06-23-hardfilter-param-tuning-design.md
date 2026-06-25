# HardFilter 参数优化 + AMM 剔除修复 — 设计文档

**日期:** 2026-06-23
**范围:** HardFilter 第二层(模块 02)的参数调优、AMM/LP 持仓剔除 bug 修复、buy/sell ratio 从硬红线降级为打分项。

---

## 1. 背景与动机

对最近 100 个 pump.fun 毕业币(`complete=true`)做了真实端到端测试,跑了完整 HardFilter 流程,得到以下经验事实:

### 1.1 采样真相
- "最新毕业"feed(按创建时间倒序)中 **88/100 是毕业后已死的尸体**:创建至今中位 9.6 小时,USD 市值中位仅 $2,044(毕业线 ~$69k,等于已崩 ~97%)。
- 仅 **12/100 活币**(市值 ≥ $20k)。调参只能针对这 12 个活币的分布。
- momentum 把 88 个死币正确拒掉了 —— 过滤器主体逻辑是对的。

### 1.2 核心 bug:AMM 池被当成持有者,holder 维度系统性误杀
- RugCheck `parse_report` 计算 `top10_pct` / `max_wallet_pct` 时,**把 AMM 池账户也算进去了**,与设计文档 [`plan/02-hardfilter.md`](../../../plan/02-hardfilter.md) 第 27 行"Top10 占比(剔除 LP)"矛盾。
- RugCheck 报告顶层有 `knownAccounts`(地址 → `{name, type}`),池账户标记为 `type == "AMM"`。这是权威、可靠的剔除依据。
- **用 `knownAccounts` type==AMM 正确剔除后,活币集中度回到合理区间:**

| 指标 | 原始(含池) | 正确剔池后 |
|------|------------|-----------|
| top10 中位 | 64% | **31.2%** |
| top10 p75 | 69% | **33.9%** |
| top10 p90 | 78% | 46% |
| max_wallet 中位 | 20.9% | **5.0%** |
| max_wallet p90 | 24% | 20% |

**结论:** holder 阈值(top10 ≤ 35%、单钱包 < 20%)本就合理,唯一问题是没剔池子。修复 bug 后现有阈值即可正常工作。

### 1.3 其它阈值经验
- `min_liquidity_usd = 20000` 偏高:活币流动性中位 $17.6k、p25 $13.6k → 砍掉 ~2/3 活币。
- `min_volume_5m = 1000` 偏高:活币 5min 量 p25 = $292(5min 窗口本就抖动大)。
- `max_fdv_to_liquidity = 50` 形同虚设:活币最大才 5.9,永不触发。
- `min_buy_sell_ratio_5m = 1.0` 偏严:5min 买卖比抖动大,砍掉 ~40% 活币;且该信号已在 ScoreEngine 作为打分子项存在。

---

## 2. 目标

1. 把 HardFilter 的全部可调参数集中在 `thresholds.yaml` 的 `hardfilter` 段(已是唯一入口),**重排为带中文注释的"调参面板"**:每个参数注明 `含义 | 建议区间 | 影响哪一关`,并写入优化后的新值。改参数永远只动这一个文件。
2. 修复 AMM/LP 剔除 bug。
3. 把 buy/sell ratio 从硬红线降级为打分信号,仅保留一个极端兑底硬红线。

**非目标(YAGNI):** 不改 authority / dev_pct / sniper_pct 规则结构;不重写 ScoreEngine 权重;不引入新数据源;不改采样层(实时发现层已验收)。

---

## 3. 参数变更清单

| 参数 | 现值 | 新值 | 依据 |
|------|------|------|------|
| **(bug)AMM 池剔除** | 无 | knownAccounts type==AMM | 让 holder 维度恢复可用 |
| `holders.max_top10_pct` | 35 | **35**(保持) | 剔池后中位 31%、p75 34% |
| `holders.max_single_wallet_pct` | 20 | **20**(保持) | 剔池后中位 5%、p90 20% |
| `holders.max_dev_pct` | 10 | **10**(保持) | 实测 ~0,留作非 pump 保险 |
| `holders.max_sniper_pct` | 30 | **30**(保持) | 实测 0,留作保险 |
| `momentum.min_liquidity_usd` | 20000 | **13000** | 活币流动性中位 $17.6k、p25 $13.6k |
| `momentum.min_volume_5m` | 1000 | **300** | 活币 5min 量 p25 = $292 |
| `momentum.max_fdv_to_liquidity` | 50 | **8** | 活币最大 5.9 |
| `momentum.min_buy_sell_ratio_5m` | 1.0 | **改名 `min_buy_sell_ratio_floor: 0.2`** | 降级为兑底红线 |

authority 三项(mint/freeze/lp require)保持不变:pump.fun 毕业币 12/12 全部已放弃/锁定,对此类币恒过,留作非 pump 币保险。

---

## 4. 设计:三个组件

### 组件 1 — `thresholds.yaml` 调参面板
- 文件:`src/memedog/config/thresholds.yaml`(`hardfilter` 段)。
- 重排为带中文注释的面板,写入第 3 节新值。
- 注释格式约定:`<参数>: <值>    # <含义> | 建议<区间> | 关:<momentum|holders|authority>`。

示意:
```yaml
hardfilter:
  # ===== 调参面板:改这里即可,无需动代码 =====
  momentum:
    min_liquidity_usd: 13000       # 流动性下限USD | 建议12k~20k | 关:momentum
    min_volume_5m: 300             # 5min成交量下限USD | 建议300~1000 | 关:momentum
    max_fdv_to_liquidity: 8        # FDV/流动性上限 | 建议5~10 | 关:momentum
    min_buy_sell_ratio_floor: 0.2  # 买卖比极端兑底(仅<此值才丢,其余交打分) | 建议0.1~0.3 | 关:momentum
  holders:                          # 注:以下占比均已剔除AMM/LP池
    max_top10_pct: 35              # Top10占比上限% | 建议30~40 | 关:holders
    max_single_wallet_pct: 20      # 单一钱包上限% | 建议15~25 | 关:holders
    max_dev_pct: 10                # 开发者持仓上限% | 建议5~10 | 关:holders
    max_sniper_pct: 30             # sniper占比上限% | 建议20~30 | 关:holders
  authority:
    require_mint_revoked: true     # 要求mint权限已放弃 | 关:authority
    require_freeze_revoked: true   # 要求freeze权限已放弃 | 关:authority
    require_lp_burned_or_locked: true # 要求LP已烧毁/锁定 | 关:authority
  on_rugcheck_failure: drop        # RugCheck不可用时:drop=保守丢弃 / pass_flagged=放行打标
```

### 组件 2 — AMM/LP 剔除(核心 bug 修复)
- 文件:`src/memedog/clients/rugcheck.py`。
- 新增纯函数 `_amm_accounts(report: dict) -> set[str]`:
  - 读取 `report.get("knownAccounts")`(dict),收集所有 `value.get("type") == "AMM"` 的 key(地址)。
  - 容错:`knownAccounts` 缺失/非 dict → 返回空集合。
- 在 `parse_report` 中,计算 `top10_pct` / `max_wallet_pct` / `sniper_pct` **之前**,先用 AMM 集合过滤 `topHolders`:
  - 排除条件:`holder.get("address") in amm_set` **或** `holder.get("owner") in amm_set`。
  - 在过滤后的列表上计算:`top10_pct = sum(前10个 pct)`、`max_wallet_pct = max(pct)`、`sniper_pct = sum(insider==True 的 pct)`。
  - `dev_pct`(creatorBalance / supply)不受影响。
- 只剔 `AMM`,**不剔 `LOCKER`**(已决策:锁仓量保守计入集中度)。
- 边界:剔除后 `topHolders` 为空 → `top10_pct` / `max_wallet_pct` = None(沿用现有"全 None → holders_unassessable"语义)。

### 组件 3 — buy/sell ratio 出硬红线、进打分
- 文件:`src/memedog/hardfilter/rules.py` 的 `check_momentum`。
  - 删除原"`ratio >= min_buy_sell_ratio_5m` 否则丢"规则。
  - 改为兑底:仅当 `ratio < cfg.min_buy_sell_ratio_floor`(0.2)时返回 `(False, "momentum:buy_sell_ratio_floor=...")`。
- 文件:`src/memedog/config/settings.py` 的 `MomentumFilterConfig`:
  - 字段 `min_buy_sell_ratio_5m: float` 改名为 `min_buy_sell_ratio_floor: float`。
- 打分侧无需改动:[`scoring/dimensions.py`](../../../src/memedog/scoring/dimensions.py) 的 `score_momentum` 已有 `buy_sell_ratio_5m > 1` 的奖励逻辑,momentum 维度自然承接该信号。

---

## 5. 受影响文件清单

| 文件 | 改动 |
|------|------|
| `src/memedog/config/thresholds.yaml` | 重排 hardfilter 面板 + 新值 + 字段改名 |
| `src/memedog/config/settings.py` | `MomentumFilterConfig.min_buy_sell_ratio_5m` → `min_buy_sell_ratio_floor` |
| `src/memedog/clients/rugcheck.py` | 新增 `_amm_accounts`;`parse_report` 剔除 AMM holder |
| `src/memedog/hardfilter/rules.py` | `check_momentum`:ratio 硬规则改兑底 |
| `tests/clients/test_rugcheck.py` | 新增含 AMM holder 的 fixture 与剔除断言 |
| `tests/hardfilter/test_rules.py` | 更新 ratio 用例为兑底语义;边界值跟新阈值 |
| `tests/hardfilter/test_hardfilter.py` | 字段改名(4 处 `min_buy_sell_ratio_5m`) |
| `tests/test_integration_pipeline.py`, `tests/test_orchestrator.py` | 字段改名 |

> 注:`buy_sell_ratio_5m`(`MomentumInfo`/snapshot 字段)与配置字段同名但不同物,**不改**。scoring 测试不受影响。

---

## 6. 测试策略(全程 TDD,不联网)

1. **AMM 剔除(组件 2)**
   - 新 fixture:一份含 `knownAccounts`(若干 `type:AMM`)+ `topHolders`(其中部分 address/owner 命中 AMM)的报告。
   - 断言:剔除后 `top10_pct` / `max_wallet_pct` 明显低于不剔除;命中 owner 的也被剔;`knownAccounts` 缺失时退化为旧行为(不崩)。
2. **ratio 兑底(组件 3)**
   - `ratio = 0.5` 现在应 PASS(高于 0.2 兑底);`ratio = 0.1` 应 DROP;reason 含 `buy_sell_ratio_floor`。
3. **新阈值边界(组件 1)**
   - liquidity 在 13000 上下、volume 在 300 上下、fdv/liq 在 8 上下各正反一例。
4. **回归**:`hardfilter` / `rules` / `clients` 全套测试通过;改名后 `settings` 加载 YAML 不报错。

---

## 7. 风险与缓解

- **样本量小(活币 n=12):** 阈值为演示默认,全部可在 YAML 调;后续可用 PumpPortal migration WS 在"毕业瞬间"采集更干净的样本复核(本次不做)。
- **RugCheck `knownAccounts` 字段缺失/改版:** `_amm_accounts` 容错返回空集 → 退化为旧行为(保守计入,不崩)。
- **改名遗漏引用:** 第 5 节已穷举全部 `min_buy_sell_ratio_5m` 引用点,实现时逐一更新并跑全测验证。
