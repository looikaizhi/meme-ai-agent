# 模块 01:Scanner(扫描器)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development 或 executing-plans。

**Goal:** 周期性从 DexScreener 拉取 Solana 新盘,初筛出"初有动量"候选并去重,产出 `List[TokenCandidate]`。

**Architecture:** 一个 `DexScreenerClient`(继承统一 client 基类,带重试/限流)+ 一个 `Scanner` 业务类。Scanner 只做"取新盘 + 粗筛动量 + 去重",不做深度安全/链上分析(那是 HardFilter/Enricher 的事)。

**Tech Stack:** httpx(async)、pydantic。数据源:DexScreener 公开 API(免费,无需 key)。

---

## 职责边界

- **做**:拉新盘、转 `TokenCandidate`、按"目标时间窗 + 最低流动性/量"粗筛、去重(已见过的 mint 不重复发)。
- **不做**:合约权限、持币分布、社交——全部留给后续模块。
- **输入**:无(自驱动)。**输出**:`List[TokenCandidate]`。

## 文件结构

```
src/memedog/clients/dexscreener.py   # DexScreenerClient
src/memedog/scanner/scanner.py       # Scanner
src/memedog/scanner/__init__.py
tests/clients/test_dexscreener.py
tests/scanner/test_scanner.py
```

## 数据源说明

- DexScreener 端点(只读,免费):
  - 搜索/最新 pairs:`GET https://api.dexscreener.com/latest/dex/search?q=<query>` 或 token-profiles / pairs 接口。
  - 返回字段含:`priceUsd`、`liquidity.usd`、`fdv`、`volume.m5/h1`、`txns.m5.buys/sells`、`priceChange.m5`、`pairCreatedAt`、`baseToken.address/symbol`。
- **注意**:DexScreener 无官方"全部新盘"流式接口,实现上用其 pairs/search 接口轮询 Solana 新建 pair,以 `pairCreatedAt` 倒序取近窗口。客户端需限流(建议 ≤300 req/min)。

## 配置(thresholds.yaml -> scanner 段)

```yaml
scanner:
  scan_interval_sec: 30
  chain: solana
  min_pair_age_min: 20        # 目标窗口下界:太新先不看
  max_pair_age_min: 360       # 上界:超过 6h 不算"初有动量"
  prefilter_min_liquidity_usd: 10000   # 粗筛(HardFilter 还会更严)
  prefilter_min_volume_5m: 500
  dedup_ttl_min: 720          # 去重缓存保留 12h
```

## 任务

### Task 1: DexScreenerClient

**Files:** Create `src/memedog/clients/dexscreener.py`; Test `tests/clients/test_dexscreener.py`

- [ ] **Step 1: 写失败测试**(用 mock 的 httpx 响应,断言解析出正确字段)

```python
import respx, httpx
from memedog.clients.dexscreener import DexScreenerClient

@respx.mock
async def test_fetch_new_pairs_parses_fields():
    respx.get(url__regex=r".*dexscreener.*").mock(return_value=httpx.Response(200, json={
        "pairs": [{"baseToken": {"address": "MINT1", "symbol": "DOG"},
            "pairAddress": "PAIR1", "priceUsd": "0.001",
            "liquidity": {"usd": 25000}, "fdv": 1000000,
            "volume": {"m5": 800, "h1": 4000},
            "txns": {"m5": {"buys": 12, "sells": 3}},
            "priceChange": {"m5": 5.0}, "pairCreatedAt": 1700000000000}]}))
    client = DexScreenerClient()
    pairs = await client.fetch_solana_pairs()
    assert pairs[0]["baseToken"]["address"] == "MINT1"
```

- [ ] **Step 2: 跑测试确认失败** — `pytest tests/clients/test_dexscreener.py -v` → FAIL
- [ ] **Step 3: 实现 client** — 继承 `clients/base.py` 的 `BaseHTTPClient`(超时/重试/限流);方法 `fetch_solana_pairs()` 返回原始 pair dict 列表。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(clients): dexscreener client"`

### Task 2: Scanner(粗筛 + 转换 + 去重)

**Files:** Create `src/memedog/scanner/scanner.py`; Test `tests/scanner/test_scanner.py`

- [ ] **Step 1: 写失败测试**

```python
from memedog.scanner.scanner import Scanner

async def test_scanner_prefilters_and_dedups(fake_client, cfg):
    # fake_client 返回 2 个 pair:一个流动性 25k(过),一个 2k(被粗筛掉)
    scanner = Scanner(client=fake_client, cfg=cfg)
    out1 = await scanner.scan()
    assert len(out1) == 1 and out1[0].liquidity_usd == 25000
    out2 = await scanner.scan()          # 第二轮同样数据
    assert out2 == []                    # 去重:不重复产出
```

- [ ] **Step 2: 跑测试确认失败** → FAIL
- [ ] **Step 3: 实现 Scanner**
  - `scan()`:调 client → 对每个 pair 计算 `pair_age` → 应用 `min/max_pair_age`、`min_liquidity`、`min_volume_5m` 粗筛 → 转 `TokenCandidate`(生成 `trace_id`)→ 经去重缓存(TTL `dedup_ttl_min`)过滤已见 mint。
- [ ] **Step 4: 跑测试确认通过** → PASS
- [ ] **Step 5: commit** — `git commit -m "feat(scanner): prefilter + dedup"`

## 降级与边界
- DexScreener 超时/限流:重试耗尽后本轮返回空列表并记日志,不抛到主循环。
- 去重缓存用内存 dict + 时间戳(单进程足够);若多进程后续换 Redis。
