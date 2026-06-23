# Enricher 智能化升级 Phase 1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给第三层 Enricher 加上聪明钱共识、免费社交元数据、确定性叙事分类(新增第 5 打分维度),并把 Twitter 移出生产路径 —— 让 LLM 拿到更智能的判断依据。

**Architecture:** 数据契约先行(全部默认值,零 call-site 破坏);叶子纯函数(叙事分类器、钱包库加载、Helius 共识、Scanner 采集)各自 TDD;再装配 provider/enricher;最后改 ScoreEngine(加 narrative 维 + 去 twitter 依赖)、config 权重、LLM prompt。全程外部 API mock,不联网。

**Tech Stack:** Python 3.11+ / pydantic v2 / pytest(`pythonpath=["src"]`,直接 `pytest`)。

参考:`docs/superpowers/specs/2026-06-24-enricher-intelligence-phase1-design.md`

---

## 文件结构

| 文件 | 责任 | 改动 |
|------|------|------|
| `src/memedog/models/snapshot.py` | 数据契约 | 新增 `WalletInfo`/`NarrativeInfo`;`SocialInfo` 扩字段;`TokenSnapshot.narrative`(默认值) |
| `src/memedog/models/candidate.py` | 候选契约 | `social_platforms: list[str] = []` |
| `src/memedog/models/__init__.py` | 导出 | 导出 `WalletInfo`/`NarrativeInfo` |
| `src/memedog/enricher/narrative.py` | 叙事分类(纯函数) | 新增 `classify_narrative` |
| `src/memedog/clients/helius.py` | 聪明钱共识 | 新增 `analyze_smart_money` |
| `src/memedog/clients/lunarcrush.py` | 可选社交热度 | 新增 `LunarCrushClient` |
| `src/memedog/scanner/scanner.py` | 采集社交平台 | `_convert` 写 `social_platforms` |
| `src/memedog/enricher/enricher.py` | 装配 | `_load_smart_wallets`→dict;透传 social_platforms;装配 narrative;去 twitter |
| `src/memedog/enricher/providers.py` | 维度 provider | `fetch_social` 重写;新增 `fetch_narrative` |
| `src/memedog/scoring/dimensions.py` | 维度打分 | 新增 `score_narrative`;`score_social` 去 twitter |
| `src/memedog/scoring/engine.py` | 聚合 | 加 narrative 维 + 必填键 |
| `src/memedog/config/settings.py` | 配置模型 | `ScoringNarrativeConfig`;`EnricherConfig`/`Settings` lunarcrush |
| `src/memedog/config/thresholds.yaml` | 阈值/权重 | weights 加 narrative + narrative 段 + enricher lunarcrush |
| `src/memedog/llmjudge/prompts.py` | LLM 证据 | social 行 + NARRATIVE 行 + workflow |
| `config/smart_wallets.txt` | 示例钱包库 | 升级带 label/tier |

---

## Task 1: 数据契约(零 call-site 破坏)

**Files:**
- Modify: `src/memedog/models/snapshot.py`
- Modify: `src/memedog/models/candidate.py`
- Modify: `src/memedog/models/__init__.py`
- Test: `tests/models/test_contracts.py`

- [ ] **Step 1: 写失败测试**

在 `tests/models/test_contracts.py` 末尾追加:

```python
def test_wallet_info_defaults():
    from memedog.models import WalletInfo
    w = WalletInfo(address="ABC")
    assert w.address == "ABC"
    assert w.label is None and w.tier is None


def test_narrative_info_defaults():
    from memedog.models import NarrativeInfo
    n = NarrativeInfo()
    assert n.available is True
    assert n.category is None
    assert n.matched_keywords == [] and n.meme_collision == []
    assert n.summary == ""


def test_social_info_new_fields_default_none():
    from memedog.models import SocialInfo
    s = SocialInfo()
    assert s.smart_money_distinct_wallets is None
    assert s.smart_money_buyers is None
    assert s.smart_money_top_tier is None
    assert s.has_twitter is None and s.has_telegram is None and s.has_website is None
    assert s.socials_count is None and s.galaxy_score is None


def test_candidate_social_platforms_default_empty(make_candidate_kwargs):
    from memedog.models import TokenCandidate
    c = TokenCandidate(**make_candidate_kwargs)
    assert c.social_platforms == []


def test_token_snapshot_narrative_defaults(make_snapshot_kwargs):
    from memedog.models import TokenSnapshot, NarrativeInfo
    snap = TokenSnapshot(**make_snapshot_kwargs)
    assert isinstance(snap.narrative, NarrativeInfo)
    assert snap.narrative.available is True
```

> 注:`make_candidate_kwargs` / `make_snapshot_kwargs` 若 conftest 无,改用文件内已有的构造方式(参考该测试文件现有 TokenCandidate/TokenSnapshot 构造,补齐必填字段;**不要**传 `social_platforms`/`narrative` 以验证默认值)。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/models/test_contracts.py -k "wallet_info or narrative or social_info_new or social_platforms or snapshot_narrative" -v`
Expected: FAIL（`WalletInfo`/`NarrativeInfo` 不可导入;新字段不存在）。

- [ ] **Step 3: 实现**

在 `src/memedog/models/snapshot.py`,`SocialInfo` 之前新增:

```python
class WalletInfo(BaseModel):
    address: str
    label: Optional[str] = None
    tier: Optional[str] = None


class NarrativeInfo(BaseModel):
    available: bool = True
    category: Optional[str] = None
    matched_keywords: list[str] = []
    meme_collision: list[str] = []
    summary: str = ""
```

把 `SocialInfo` 改为(新增字段,保留旧字段):

```python
class SocialInfo(BaseModel):
    available: bool = True
    smart_money_buys: Optional[int] = None
    twitter_mentions_1h: Optional[int] = None   # deprecated: 生产不再填充
    twitter_growth: Optional[float] = None       # deprecated: 生产不再填充
    # 聪明钱共识
    smart_money_distinct_wallets: Optional[int] = None
    smart_money_buyers: Optional[list[WalletInfo]] = None
    smart_money_top_tier: Optional[str] = None
    # 社交元数据
    has_twitter: Optional[bool] = None
    has_telegram: Optional[bool] = None
    has_website: Optional[bool] = None
    socials_count: Optional[int] = None
    galaxy_score: Optional[float] = None
```

把 `TokenSnapshot` 加一维(**带默认值**,避免破坏 10 处构造):

```python
class TokenSnapshot(BaseModel):
    candidate: TokenCandidate
    safety: SafetyInfo
    holders: HolderInfo
    momentum: MomentumInfo
    social: SocialInfo
    narrative: NarrativeInfo = NarrativeInfo()
    enriched_at: AwareDatetime
```

在 `src/memedog/models/candidate.py` 的 `TokenCandidate` 末尾加字段:

```python
    social_platforms: list[str] = []
```

在 `src/memedog/models/__init__.py` 导出 `WalletInfo`、`NarrativeInfo`:把 import 行改为
`from memedog.models.snapshot import (HolderInfo, MomentumInfo, NarrativeInfo, SafetyInfo, SocialInfo, TokenSnapshot, WalletInfo)`,并在 `__all__` 加 `"WalletInfo"`, `"NarrativeInfo"`。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/models/ -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/memedog/models/ tests/models/test_contracts.py
git commit -m "feat(models): WalletInfo, NarrativeInfo, social fields, snapshot.narrative

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 叙事分类器(纯函数)

**Files:**
- Create: `src/memedog/enricher/narrative.py`
- Test: `tests/enricher/test_narrative.py`

- [ ] **Step 1: 写失败测试**

Create `tests/enricher/test_narrative.py`:

```python
"""Tests for deterministic narrative classification."""
from memedog.enricher.narrative import classify_narrative


def test_animal_meme():
    n = classify_narrative("QDOG", "Quantum Dog")
    assert n.category == "animal"
    assert "dog" in n.matched_keywords
    assert n.available is True


def test_ai_meme():
    n = classify_narrative("GROKAI", "Grok AI Agent")
    assert n.category == "ai"
    assert "grok" in n.meme_collision  # grok is a known winner


def test_political_meme():
    n = classify_narrative("TRUMPWIN", "Trump 2028")
    assert n.category == "political"
    assert "trump" in n.meme_collision


def test_finance_utility_name():
    n = classify_narrative("ASSETFUND", "Asset Funds Protocol")
    assert n.category == "finance_utility"


def test_unknown_falls_back():
    n = classify_narrative("XQZ", "Xqzzy")
    assert n.category == "unknown"
    assert n.matched_keywords == []


def test_meme_collision_detected():
    n = classify_narrative("BONKINU", "Bonk Inu")
    assert "bonk" in n.meme_collision
    assert n.category == "animal"  # inu is animal


def test_never_raises_on_weird_input():
    # empty / None-ish symbol must not raise
    n = classify_narrative("", "")
    assert n.category == "unknown"


def test_summary_is_non_empty_for_known():
    n = classify_narrative("CATGPT", "Cat GPT")
    assert isinstance(n.summary, str) and n.summary != ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/enricher/test_narrative.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

Create `src/memedog/enricher/narrative.py`:

```python
"""Deterministic narrative classification from a token's symbol/name.

No network, no LLM, never raises. Answers "does this coin have a memeable hook"
purely from its name — a cheap attention proxy.
"""
from __future__ import annotations

from memedog.models import NarrativeInfo

# Category keyword tables (classification logic; ordered by priority).
# Scores for these categories live in thresholds.yaml (tunable), not here.
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("animal", ["dog", "doge", "inu", "shib", "cat", "kitty", "pepe", "frog",
                "bear", "bull", "ape", "monkey", "wif", "hippo", "penguin"]),
    ("ai", ["ai", "gpt", "agent", "grok", "bot", "neural", "llm", "gpu"]),
    ("political", ["trump", "biden", "maga", "election", "vance", "boden", "potus"]),
    ("culture", ["meme", "chad", "wojak", "giga", "based", "moon", "pump",
                 "pepe", "pokemon", "anime", "mon"]),
    ("finance_utility", ["fund", "capital", "finance", "protocol", "dao", "swap",
                         "chain", "pay", "asset", "yield", "stake", "cash"]),
]

# Known runaway memes a new name may echo (context + scoring bonus).
_MEME_WINNERS = ["wif", "pepe", "bonk", "doge", "shib", "cat", "grok", "trump", "musk"]

_CATEGORY_LABEL = {
    "animal": "动物系 meme",
    "ai": "AI/agent 叙事",
    "political": "政治/名人事件",
    "culture": "网络文化/游戏",
    "finance_utility": "金融/工具型命名",
    "unknown": "无明显叙事钩子",
}


def classify_narrative(symbol: str, name: str) -> NarrativeInfo:
    """Classify a token's narrative from its symbol + name. Never raises."""
    try:
        text = f"{symbol or ''} {name or ''}".lower()

        category = "unknown"
        matched: list[str] = []
        for cat, keywords in _CATEGORY_KEYWORDS:
            hits = [kw for kw in keywords if kw in text]
            if hits:
                category = cat
                matched = hits
                break

        collisions = [w for w in _MEME_WINNERS if w in text]

        label = _CATEGORY_LABEL.get(category, _CATEGORY_LABEL["unknown"])
        if collisions:
            summary = f"{label};呼应已知 meme: {', '.join(collisions)}"
        else:
            summary = label

        return NarrativeInfo(
            available=True,
            category=category,
            matched_keywords=matched,
            meme_collision=collisions,
            summary=summary,
        )
    except Exception:  # noqa: BLE001 — deterministic, but stay defensive
        return NarrativeInfo(available=False)
```

> 注:`test_meme_collision_detected` 用 "BONKINU" → text 含 "inu"(animal,优先级最高)与 "bonk"(collision)。`test_ai_meme` 用 "GROKAI" → "ai" 命中 ai 类、"grok" 进 collision。确保关键词表覆盖这些。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/enricher/test_narrative.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/memedog/enricher/narrative.py tests/enricher/test_narrative.py
git commit -m "feat(enricher): deterministic narrative classifier

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 钱包库加载器升级(带 label/tier)

**Files:**
- Modify: `src/memedog/enricher/enricher.py`（`_load_smart_wallets`）
- Modify: `config/smart_wallets.txt`（示例)
- Test: `tests/enricher/test_enricher.py`（新增加载器测试)

- [ ] **Step 1: 写失败测试**

在 `tests/enricher/test_enricher.py` 追加（若无该文件则创建，含必要 import）:

```python
def test_load_smart_wallets_with_labels(tmp_path):
    from memedog.enricher.enricher import _load_smart_wallets
    p = tmp_path / "wallets.txt"
    p.write_text(
        "# comment line\n"
        "AAA,early-BONK-buyer,S\n"
        "BBB,KOL-wallet,A\n"
        "CCC\n"            # bare address, no label/tier
        "\n",             # blank line
        encoding="utf-8",
    )
    lib = _load_smart_wallets(str(p))
    assert set(lib.keys()) == {"AAA", "BBB", "CCC"}
    assert lib["AAA"].label == "early-BONK-buyer" and lib["AAA"].tier == "S"
    assert lib["CCC"].label is None and lib["CCC"].tier is None


def test_load_smart_wallets_missing_file_returns_empty():
    from memedog.enricher.enricher import _load_smart_wallets
    lib = _load_smart_wallets("/nonexistent/path/wallets.txt")
    assert lib == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/enricher/test_enricher.py -k "load_smart_wallets" -v`
Expected: FAIL（当前 `_load_smart_wallets` 返回 `set[str]`,无 `.label`）。

- [ ] **Step 3: 实现**

在 `src/memedog/enricher/enricher.py` 顶部 import 处加 `from memedog.models import WalletInfo`。把 `_load_smart_wallets` 整个替换为:

```python
def _load_smart_wallets(filepath: str) -> dict[str, WalletInfo]:
    """Load smart wallets as address -> WalletInfo.

    Line format: ``address[,label[,tier]]``. Lines starting with ``#`` and
    blank lines are skipped. Missing/unreadable file -> empty dict (tolerant).
    """
    path = Path(filepath)
    if not path.exists():
        logger.debug("smart_wallets file not found: %s — using empty dict", filepath)
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Could not read smart_wallets file %s: %s", filepath, exc)
        return {}

    library: dict[str, WalletInfo] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        address = parts[0]
        if not address:
            continue
        label = parts[1] if len(parts) > 1 and parts[1] else None
        tier = parts[2] if len(parts) > 2 and parts[2] else None
        library[address] = WalletInfo(address=address, label=label, tier=tier)
    logger.debug("Loaded %d smart wallets from %s", len(library), filepath)
    return library
```

把 `config/smart_wallets.txt` 内容替换为示例(保留任何现有真实地址行也可，至少给出带标签示例):

```
# address,label,tier   (label/tier 可选;tier: S/A/B 高->低)
# 示例条目 — 离线维护;Phase 2 才做自动质量计算
9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin,early-runner-buyer,S
3NkzLTtTfEWqDY2Mm3uVt2wog8yDN48yDu3vsTS4MSaq,kol-wallet,A
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/enricher/test_enricher.py -k "load_smart_wallets" -v`
Expected: PASS。（此时 `fetch_social` 还在用旧的 `set` 接口 → 下个任务修;先确认本测试绿，**完整 enricher 测试可能暂红,Task 7 修复**。）

- [ ] **Step 5: Commit**

```bash
git add src/memedog/enricher/enricher.py config/smart_wallets.txt tests/enricher/test_enricher.py
git commit -m "feat(enricher): labeled smart-wallet library loader (address,label,tier)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Helius 聪明钱共识

**Files:**
- Modify: `src/memedog/clients/helius.py`
- Test: `tests/clients/test_helius.py`

- [ ] **Step 1: 写失败测试**

在 `tests/clients/test_helius.py` 追加（用 respx 风格 mock,与该文件现有测试一致;若现有用别的 mock 方式，沿用之）:

```python
import pytest
from memedog.models import WalletInfo


@pytest.mark.asyncio
async def test_analyze_smart_money_counts_distinct_and_tier(respx_mock):
    import respx, httpx
    from memedog.clients.helius import HeliusClient

    mint = "MINT123"
    library = {
        "WALLET_A": WalletInfo(address="WALLET_A", label="kol", tier="A"),
        "WALLET_S": WalletInfo(address="WALLET_S", label="early", tier="S"),
    }
    txs = [
        {"tokenTransfers": [{"toUserAccount": "WALLET_A"}]},
        {"tokenTransfers": [{"toUserAccount": "WALLET_A"}]},   # same wallet twice
        {"tokenTransfers": [{"toUserAccount": "WALLET_S"}]},
        {"tokenTransfers": [{"toUserAccount": "STRANGER"}]},   # not in library
    ]
    respx.get(url__regex=rf".*/v0/addresses/{mint}/transactions.*").mock(
        return_value=httpx.Response(200, json=txs)
    )
    async with HeliusClient(api_key="k") as client:
        result = await client.analyze_smart_money(mint, library)

    assert result["buys"] == 3                 # 3 transfers to known wallets
    assert result["distinct_wallets"] == 2     # WALLET_A + WALLET_S
    assert result["top_tier"] == "S"           # best tier among buyers
    addrs = {b.address for b in result["buyers"]}
    assert addrs == {"WALLET_A", "WALLET_S"}


@pytest.mark.asyncio
async def test_analyze_smart_money_empty_library_no_network():
    from memedog.clients.helius import HeliusClient
    async with HeliusClient(api_key="k") as client:
        result = await client.analyze_smart_money("MINT", {})
    assert result == {"buys": 0, "distinct_wallets": 0, "buyers": [], "top_tier": None}
```

> 若 `tests/clients/test_helius.py` 不存在,创建之并参考 `tests/clients/test_rugcheck.py` 的 respx 用法。`HeliusClient` 支持 `async with`（继承 BaseHTTPClient）。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/clients/test_helius.py -k "analyze_smart_money" -v`
Expected: FAIL（方法不存在）。

- [ ] **Step 3: 实现**

在 `src/memedog/clients/helius.py` import 处加 `from memedog.models import WalletInfo`。在 `count_smart_money_buys` 之后新增方法:

```python
    async def analyze_smart_money(
        self, mint: str, wallet_library: dict
    ) -> dict:
        """Consensus signal: which labeled wallets recently received this token.

        Returns dict with:
          buys: int             — transfers whose recipient is in the library
          distinct_wallets: int — distinct such recipient wallets
          buyers: list[WalletInfo] — the matched wallets (with label/tier)
          top_tier: str | None  — best tier among buyers (S>A>B)

        Empty library -> all-zero result, no network. On error -> None
        (provider marks the sub-source unavailable, dimension survives).
        """
        if not wallet_library:
            return {"buys": 0, "distinct_wallets": 0, "buyers": [], "top_tier": None}

        url = (
            f"{_HELIUS_API_BASE}/v0/addresses/{mint}/transactions"
            f"?api-key={self._api_key}&type=TRANSFER"
        )
        try:
            transactions = await self.get_json(url)
        except DataSourceError as exc:
            logger.warning("analyze_smart_money: fetch failed for %s: %s", mint, exc)
            return None

        buys = 0
        matched: dict[str, WalletInfo] = {}
        if isinstance(transactions, list):
            for tx in transactions:
                for transfer in tx.get("tokenTransfers", []):
                    addr = transfer.get("toUserAccount")
                    if addr in wallet_library:
                        buys += 1
                        matched[addr] = wallet_library[addr]

        buyers = list(matched.values())
        tier_rank = {"S": 3, "A": 2, "B": 1}
        top_tier = None
        if buyers:
            ranked = [b.tier for b in buyers if b.tier in tier_rank]
            if ranked:
                top_tier = max(ranked, key=lambda t: tier_rank[t])
        return {
            "buys": buys,
            "distinct_wallets": len(matched),
            "buyers": buyers,
            "top_tier": top_tier,
        }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/clients/test_helius.py -k "analyze_smart_money" -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/memedog/clients/helius.py tests/clients/test_helius.py
git commit -m "feat(helius): analyze_smart_money consensus (distinct wallets, tiers)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Scanner 采集社交平台

**Files:**
- Modify: `src/memedog/scanner/scanner.py`（`_convert`)
- Test: `tests/scanner/test_scanner.py`

- [ ] **Step 1: 写失败测试**

在 `tests/scanner/test_scanner.py` 追加(参考该文件现有 pair fixture 构造;补齐 `_convert` 所需的全部必填字段):

```python
def test_convert_captures_social_platforms(scanner_with_cfg, base_pair):
    pair = dict(base_pair)
    pair["info"] = {
        "socials": [{"type": "twitter", "url": "x"}, {"type": "telegram", "url": "y"}],
        "websites": [{"url": "https://z"}],
    }
    cand = scanner_with_cfg._convert(pair)
    assert set(cand.social_platforms) == {"twitter", "telegram", "website"}


def test_convert_no_info_empty_platforms(scanner_with_cfg, base_pair):
    pair = dict(base_pair)
    pair.pop("info", None)
    cand = scanner_with_cfg._convert(pair)
    assert cand.social_platforms == []
```

> 注:`scanner_with_cfg`/`base_pair` 若 conftest 无,在测试内构造一个 Scanner 与一个含全部必填键(baseToken/pairAddress/priceUsd/liquidity/fdv/volume/txns/priceChange/pairCreatedAt)的 pair dict，参考文件内已有 Scanner 测试。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/scanner/test_scanner.py -k "social_platforms" -v`
Expected: FAIL（`social_platforms` 恒为默认 `[]`，第一个用例断言失败）。

- [ ] **Step 3: 实现**

在 `src/memedog/scanner/scanner.py` 的 `_convert` 里,`return TokenCandidate(...)` 之前计算 social_platforms,并在构造里加该字段:

```python
        info = pair.get("info") or {}
        platforms: list[str] = []
        for s in info.get("socials") or []:
            t = (s.get("type") or s.get("platform") or "").strip().lower()
            if t and t not in platforms:
                platforms.append(t)
        if (info.get("websites") or []) and "website" not in platforms:
            platforms.append("website")
```

并在 `TokenCandidate(...)` 调用里加一行 `social_platforms=platforms,`(放在 `trace_id` 之前)。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/scanner/test_scanner.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/memedog/scanner/scanner.py tests/scanner/test_scanner.py
git commit -m "feat(scanner): capture social_platforms from DexScreener pair info

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 可选 LunarCrush client + 配置

**Files:**
- Create: `src/memedog/clients/lunarcrush.py`
- Modify: `src/memedog/config/settings.py`（`Settings`、`EnricherConfig`)
- Modify: `src/memedog/config/thresholds.yaml`（enricher 段)
- Test: `tests/clients/test_lunarcrush.py`

- [ ] **Step 1: 写失败测试**

Create `tests/clients/test_lunarcrush.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_get_galaxy_score_parses_value():
    import respx, httpx
    from memedog.clients.lunarcrush import LunarCrushClient

    with respx.mock:
        respx.get(url__regex=r".*lunarcrush.*").mock(
            return_value=httpx.Response(200, json={"data": {"galaxy_score": 72.5}})
        )
        async with LunarCrushClient(api_key="k") as c:
            score = await c.get_galaxy_score("BONK")
    assert score == pytest.approx(72.5)


@pytest.mark.asyncio
async def test_get_galaxy_score_returns_none_on_error():
    import respx, httpx
    from memedog.clients.lunarcrush import LunarCrushClient
    with respx.mock:
        respx.get(url__regex=r".*lunarcrush.*").mock(return_value=httpx.Response(500))
        async with LunarCrushClient(api_key="k") as c:
            score = await c.get_galaxy_score("BONK")
    assert score is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/clients/test_lunarcrush.py -v`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

Create `src/memedog/clients/lunarcrush.py`:

```python
"""Optional LunarCrush social-intelligence client (off by default).

Only used when LUNARCRUSH_API_KEY is set. Any failure degrades to None so the
social dimension survives ("降级而非崩溃").
"""
from __future__ import annotations

import logging
from typing import Optional

from memedog.clients.base import BaseHTTPClient, DataSourceError

logger = logging.getLogger(__name__)

_LUNARCRUSH_BASE = "https://lunarcrush.com"


class LunarCrushClient(BaseHTTPClient):
    def __init__(self, api_key: str, **kwargs) -> None:
        self._api_key = api_key
        kwargs.setdefault("base_url", _LUNARCRUSH_BASE)
        super().__init__(**kwargs)

    async def get_galaxy_score(self, symbol: str) -> Optional[float]:
        """Return the Galaxy Score for *symbol*, or None on any error/missing."""
        path = f"/api4/public/coins/{symbol}/v1?key={self._api_key}"
        try:
            data = await self.get_json(path)
        except DataSourceError as exc:
            logger.warning("LunarCrush galaxy score failed for %s: %s", symbol, exc)
            return None
        try:
            return float((data.get("data") or {}).get("galaxy_score"))
        except (TypeError, ValueError, AttributeError):
            return None
```

在 `src/memedog/config/settings.py`:
- `Settings` 加字段:`lunarcrush_api_key: Optional[str] = None`
- `EnricherConfig` 加字段:`lunarcrush_enabled: bool = False`

在 `src/memedog/config/thresholds.yaml` 的 `enricher:` 段加一行:
```yaml
  lunarcrush_enabled: false   # 可选社交热度;需 LUNARCRUSH_API_KEY,默认关
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/clients/test_lunarcrush.py tests/config/ -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/memedog/clients/lunarcrush.py src/memedog/config/settings.py src/memedog/config/thresholds.yaml tests/clients/test_lunarcrush.py
git commit -m "feat(clients): optional LunarCrush galaxy-score client (off by default)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Enricher 装配(共识 + 社交元数据 + 叙事;去 Twitter)

**Files:**
- Modify: `src/memedog/enricher/providers.py`（`fetch_social` 重写;新增 `fetch_narrative`)
- Modify: `src/memedog/enricher/enricher.py`（`enrich` 装配)
- Test: `tests/enricher/test_providers.py`、`tests/enricher/test_enricher.py`

- [ ] **Step 1: 写失败测试**

在 `tests/enricher/test_providers.py` 追加:

```python
import pytest
from memedog.models import WalletInfo


class _FakeHelius:
    def __init__(self, result):
        self._result = result
    async def analyze_smart_money(self, mint, library):
        return self._result


@pytest.mark.asyncio
async def test_fetch_social_consensus_and_metadata():
    from memedog.enricher.providers import fetch_social
    helius = _FakeHelius({
        "buys": 3, "distinct_wallets": 2,
        "buyers": [WalletInfo(address="A", label="kol", tier="A")],
        "top_tier": "A",
    })
    info = await fetch_social(
        mint="M",
        helius_client=helius,
        smart_wallets={"A": WalletInfo(address="A")},
        social_platforms=["twitter", "telegram", "website"],
        galaxy_score=None,
    )
    assert info.available is True
    assert info.smart_money_buys == 3
    assert info.smart_money_distinct_wallets == 2
    assert info.smart_money_top_tier == "A"
    assert info.has_twitter is True and info.has_telegram is True and info.has_website is True
    assert info.socials_count == 3


@pytest.mark.asyncio
async def test_fetch_social_smart_money_none_still_available_via_metadata():
    from memedog.enricher.providers import fetch_social
    helius = _FakeHelius(None)  # smart money sub-source failed
    info = await fetch_social(
        mint="M", helius_client=helius, smart_wallets={"A": WalletInfo(address="A")},
        social_platforms=["twitter"], galaxy_score=None,
    )
    # metadata present -> dimension still available
    assert info.available is True
    assert info.has_twitter is True
    assert info.smart_money_distinct_wallets is None


@pytest.mark.asyncio
async def test_fetch_narrative_delegates():
    from memedog.enricher.providers import fetch_narrative
    info = await fetch_narrative(symbol="QDOG", name="Quantum Dog")
    assert info.category == "animal"
```

在 `tests/enricher/test_enricher.py` 追加一个端到端装配测试(用 fakes，确认 snapshot 带 narrative 与社交共识):

```python
@pytest.mark.asyncio
async def test_enrich_populates_narrative_and_social(monkeypatch, enricher_fakes):
    # enricher_fakes: 见文件已有 Enricher 构造方式;helius fake 返回 analyze_smart_money 结构
    enricher, candidate = enricher_fakes
    snap = await enricher.enrich(candidate)
    assert snap.narrative.available is True
    assert snap.narrative.category is not None
    # social dimension assembled without raising
    assert snap.social is not None
```

> 注:`enricher_fakes` 按 `tests/enricher/test_enricher.py` 已有的 Enricher 装配模式构造(rugcheck/helius/twitter fakes);helius fake 需提供 `analyze_smart_money` 协程。candidate 需带 `social_platforms`。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/enricher/test_providers.py -k "consensus or metadata or narrative_delegates" -v`
Expected: FAIL（`fetch_social` 旧签名/无 `fetch_narrative`）。

- [ ] **Step 3: 实现**

在 `src/memedog/enricher/providers.py`:
- 顶部 import 加 `from memedog.models import NarrativeInfo` 和 `from memedog.enricher.narrative import classify_narrative`。
- 把整个 `fetch_social` 替换为(去掉 twitter_client / smart_wallets:set 的旧实现):

```python
async def fetch_social(
    mint: str,
    helius_client,
    smart_wallets: dict,
    social_platforms: list[str],
    galaxy_score: Optional[float] = None,
) -> SocialInfo:
    """Smart-money consensus (Helius) + free social metadata (+ optional galaxy).

    available=True if EITHER smart-money consensus OR social metadata is present.
    """
    smart_ok = False
    distinct = buyers = top_tier = None
    buys: Optional[int] = None

    try:
        result = await helius_client.analyze_smart_money(mint, smart_wallets)
        if result is not None:
            smart_ok = True
            buys = result.get("buys")
            distinct = result.get("distinct_wallets")
            buyers = result.get("buyers")
            top_tier = result.get("top_tier")
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_social: smart money failed for %s: %s", mint, exc)

    platforms = social_platforms or []
    has_tw = "twitter" in platforms
    has_tg = "telegram" in platforms
    has_web = "website" in platforms
    socials_count = len(platforms)
    metadata_present = socials_count > 0 or galaxy_score is not None

    return SocialInfo(
        available=smart_ok or metadata_present,
        smart_money_buys=buys if smart_ok else None,
        smart_money_distinct_wallets=distinct if smart_ok else None,
        smart_money_buyers=buyers if smart_ok else None,
        smart_money_top_tier=top_tier if smart_ok else None,
        has_twitter=has_tw if platforms else None,
        has_telegram=has_tg if platforms else None,
        has_website=has_web if platforms else None,
        socials_count=socials_count if platforms else None,
        galaxy_score=galaxy_score,
    )


async def fetch_narrative(symbol: str, name: str) -> NarrativeInfo:
    """Deterministic narrative classification (never raises)."""
    return classify_narrative(symbol, name)
```

在 `src/memedog/enricher/enricher.py` 的 `enrich`:
- 删除 twitter 相关 coroutine 与 `social_coro` 旧参数;`smart_wallets` 现在是 dict。
- 装配改为(关键片段):

```python
        social_platforms = list(getattr(candidate, "social_platforms", []) or [])
        galaxy_score = None
        if getattr(self._cfg, "lunarcrush_enabled", False) and self._lunarcrush is not None:
            try:
                galaxy_score = await self._lunarcrush.get_galaxy_score(candidate.symbol)
            except Exception:  # noqa: BLE001
                galaxy_score = None

        social_coro = fetch_social(
            mint=candidate.mint,
            helius_client=self._helius_client,
            smart_wallets=smart_wallets,            # now dict[str, WalletInfo]
            social_platforms=social_platforms,
            galaxy_score=galaxy_score,
        )
        narrative_coro = fetch_narrative(candidate.symbol, getattr(candidate, "name", "") or candidate.symbol)
```

把 `asyncio.gather(...)` 改为含 4 个网络维 + narrative(narrative 无 I/O,可直接 await 或并入 gather)。最简:在 gather 前 `narrative = await narrative_coro`,gather 仍跑 safety/holders/momentum/social(去掉 twitter)。然后 `TokenSnapshot(..., narrative=narrative, ...)`。

- `Enricher.__init__` 增加可选 `lunarcrush_client=None` 形参,存 `self._lunarcrush`;`twitter_client` 形参保留(向后兼容,不再使用)以免破坏 app_factory 装配——或在 app_factory 同步去掉传参。**实现时:保留 `twitter_client` 形参但不调用**,最小破坏。
- 删除 `enrich` 里对 `_load_smart_wallets` 返回值当 set 的用法(现在是 dict,直接传给 fetch_social)。

> app_factory(`src/memedog/app_factory.py`)装配 Enricher 处:如仍传 `twitter_client=`,保留即可(形参仍在);可选传 `lunarcrush_client`。若构造签名变化导致 app_factory 报错,在本任务一并修正其 `Enricher(...)` 调用。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/enricher/ -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/memedog/enricher/ tests/enricher/
git commit -m "feat(enricher): assemble smart-money consensus + social metadata + narrative; drop Twitter

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: ScoreEngine 加 narrative 维 + score_social 去 twitter

**Files:**
- Modify: `src/memedog/scoring/dimensions.py`（`score_narrative`、`score_social`)
- Modify: `src/memedog/scoring/engine.py`
- Modify: `src/memedog/config/settings.py`（`ScoringNarrativeConfig`、`ScoringConfig.narrative`)
- Modify: `src/memedog/config/thresholds.yaml`（weights + narrative 段)
- Test: `tests/scoring/test_dimensions.py`、`tests/scoring/test_engine.py`

- [ ] **Step 1: 写失败测试**

在 `tests/scoring/test_dimensions.py` 追加:

```python
def test_score_narrative_category_and_collision(scoring_cfg):
    from memedog.scoring.dimensions import score_narrative
    from memedog.models import NarrativeInfo
    # animal base + collision bonus
    d = score_narrative(NarrativeInfo(category="animal", meme_collision=["bonk"]), scoring_cfg)
    assert d.name == "narrative"
    assert d.raw == pytest.approx(80.0)   # 70 base + 10 bonus (see thresholds)

def test_score_narrative_unknown_neutral(scoring_cfg):
    from memedog.scoring.dimensions import score_narrative
    from memedog.models import NarrativeInfo
    d = score_narrative(NarrativeInfo(category="unknown"), scoring_cfg)
    assert d.raw == pytest.approx(40.0)

def test_score_social_ignores_twitter_growth(scoring_cfg):
    from memedog.scoring.dimensions import score_social
    from memedog.models import SocialInfo
    # twitter_growth set but must NOT change the score anymore
    a = score_social(SocialInfo(available=True, smart_money_buys=5, twitter_growth=2.0), scoring_cfg)
    b = score_social(SocialInfo(available=True, smart_money_buys=5, twitter_growth=None), scoring_cfg)
    assert a.raw == pytest.approx(b.raw)
```

在 `tests/scoring/test_engine.py`:更新已有的"维度数=4 / 权重"断言为 5 维(含 narrative),并新增:

```python
def test_engine_includes_narrative_dimension(scoring_cfg, snapshot_factory):
    from memedog.scoring.engine import ScoreEngine
    snap = snapshot_factory()  # 已有工厂;snapshot 默认带 NarrativeInfo
    score = ScoreEngine(scoring_cfg).score(snap)
    names = {d.name for d in score.dimensions}
    assert "narrative" in names and len(score.dimensions) == 5
```

> 注:`scoring_cfg` 工厂需包含 `narrative` 权重与 `ScoringNarrativeConfig`(category_scores + meme_collision_bonus);若 `scoring_cfg` 来自 `load_config()`,本任务更新 thresholds.yaml 后即生效。若来自手构造 ScoringConfig,需在该 fixture 补 `narrative=` 与 `weights` 含 narrative。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/scoring/ -k "narrative or ignores_twitter" -v`
Expected: FAIL（`score_narrative` 不存在;engine 4 维;`ScoringNarrativeConfig` 缺失)。

- [ ] **Step 3: 实现**

在 `src/memedog/config/settings.py`:新增并挂载:

```python
class ScoringNarrativeConfig(BaseModel):
    category_scores: dict[str, float]
    meme_collision_bonus: float
```
并在 `ScoringConfig` 加字段 `narrative: ScoringNarrativeConfig`（放在 social 之后)。

在 `src/memedog/scoring/dimensions.py`:
- 新增:

```python
def score_narrative(info, cfg) -> DimensionScore:
    """Deterministic narrative score: category base (+ collision bonus), clamp [0,100]."""
    notes: list[str] = []
    if not getattr(info, "available", True):
        notes.append("数据缺失 (narrative unavailable)")
        return DimensionScore(name="narrative", raw=cfg.neutral_score, weight=0.0, weighted=0.0, notes=notes)
    category = info.category or "unknown"
    base = cfg.narrative.category_scores.get(category, cfg.narrative.category_scores.get("unknown", cfg.neutral_score))
    if info.meme_collision:
        base += cfg.narrative.meme_collision_bonus
    raw = max(0.0, min(100.0, float(base)))
    return DimensionScore(name="narrative", raw=raw, weight=0.0, weighted=0.0, notes=notes)
```

- 把 `score_social` 中的 twitter_growth 分支整段删除(只保留 smart_money_buys 分支;并可加 socials_count 作为弱信号——本任务**只删 twitter,不强行加新子项**,保持简单)。删除后若 `scores` 为空仍走 neutral 分支。

在 `src/memedog/scoring/engine.py`:
- import 加 `score_narrative`。
- `_REQUIRED_WEIGHT_KEYS` 改为 `{"safety", "holders", "momentum", "social", "narrative"}`。
- `raw_dims` 列表加一行:`(score_narrative(snapshot.narrative, cfg), snapshot.narrative.available),`。
- 归一化/兜底逻辑无需改(用 `1/n` 自适应)。把 docstring 里"四个键/0.25 each"措辞顺手更新为五维。

在 `src/memedog/config/thresholds.yaml` 的 `scoring:` 段:
```yaml
  weights: { safety: 0.30, holders: 0.25, momentum: 0.30, social: 0.10, narrative: 0.05 }
```
并加 narrative 段:
```yaml
  narrative:
    category_scores: { animal: 70, ai: 65, political: 60, culture: 55, finance_utility: 35, unknown: 40 }
    meme_collision_bonus: 10
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/scoring/ tests/config/ -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/memedog/scoring/ src/memedog/config/settings.py src/memedog/config/thresholds.yaml tests/scoring/
git commit -m "feat(scoring): add narrative dimension; drop twitter from social scorer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: LLM prompt(社交行 + NARRATIVE 行 + workflow)

**Files:**
- Modify: `src/memedog/llmjudge/prompts.py`
- Test: `tests/llmjudge/test_prompts.py`

- [ ] **Step 1: 写失败测试**

在 `tests/llmjudge/test_prompts.py` 追加(用该文件已有的 snapshot/score 构造方式;snapshot 带 NarrativeInfo + 社交共识字段):

```python
def test_evidence_includes_narrative_and_consensus(snapshot_with_narrative, score_obj):
    from memedog.llmjudge.prompts import judge_prompt
    msgs = judge_prompt(snapshot_with_narrative, score_obj, "bull", "bear")
    text = msgs[-1]["content"]
    assert "NARRATIVE" in text or "叙事" in text
    assert "聪明钱" in text  # consensus surfaced

def test_evidence_narrative_missing_renders_data_missing(snapshot_no_narrative, score_obj):
    from memedog.llmjudge.prompts import judge_prompt
    msgs = judge_prompt(snapshot_no_narrative, score_obj, "b", "b")
    text = msgs[-1]["content"]
    assert "NARRATIVE" in text or "叙事" in text
```

> 注:`snapshot_with_narrative` = snapshot 带 `narrative=NarrativeInfo(category="animal", meme_collision=["bonk"], summary="狗系")` 且 `social` 带 `smart_money_distinct_wallets=2, smart_money_buyers=[WalletInfo(...tier="S")]`;`snapshot_no_narrative` = `narrative=NarrativeInfo(available=False)`。按文件已有构造补齐。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/llmjudge/test_prompts.py -k "narrative or consensus" -v`
Expected: FAIL（证据无 narrative 行;社交行无共识)。

- [ ] **Step 3: 实现**

在 `src/memedog/llmjudge/prompts.py` 的 `_snapshot_evidence`:
- 社交 `soc_fields` 段改写为优先展示共识(替换原有 smart_money_buys/twitter 行):

```python
    soc_fields: list[tuple[str, str]] = []
    if soc.smart_money_distinct_wallets is not None:
        soc_fields.append(("聪明钱钱包数", str(soc.smart_money_distinct_wallets)))
    if soc.smart_money_top_tier is not None:
        soc_fields.append(("最高级别", str(soc.smart_money_top_tier)))
    if soc.smart_money_buyers:
        labels = ", ".join(
            f"{b.tier or '?'}:{b.label or b.address[:6]}" for b in soc.smart_money_buyers[:5]
        )
        soc_fields.append(("买家", labels))
    elif soc.smart_money_buys is not None:
        soc_fields.append(("聪明钱买入", str(soc.smart_money_buys)))
    if soc.socials_count is not None:
        present = [p for p, ok in (("tw", soc.has_twitter), ("tg", soc.has_telegram), ("web", soc.has_website)) if ok]
        soc_fields.append(("社交", ("+".join(present) or "无") + f"({soc.socials_count})"))
    if soc.galaxy_score is not None:
        soc_fields.append(("galaxy", _fmt_ratio(soc.galaxy_score)))
```

- 新增 narrative 证据行:在 `_snapshot_evidence` 里加

```python
    nar = snapshot.narrative
    nar_fields: list[tuple[str, str]] = []
    if nar.category is not None:
        nar_fields.append(("category", str(nar.category)))
    if nar.matched_keywords:
        nar_fields.append(("命中", ",".join(nar.matched_keywords[:5])))
    if nar.meme_collision:
        nar_fields.append(("碰撞", ",".join(nar.meme_collision[:5])))
    if nar.summary:
        nar_fields.append(("摘要", nar.summary))
```

并把 `lines` 列表加一行(在 SOCIAL 之后):

```python
        _evidence_line("NARRATIVE / 叙事:", nar.available, nar_fields),
```

- `judge_prompt` 的 workflow 第 4 步措辞补充 + 新增叙事说明(改 `user_content` 中 step 列表):把 step4 改为
  `"  4. social/narrative — 聪明钱共识强度+钱包级别+社交真实性;叙事(meme 钩子)仅作弱置信修正:无社交/无新闻为中性非看空,叙事只在 safety/holders/momentum 已健康时才提升置信\n"`。
  其余步骤序号不变(仍 6 步)。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/llmjudge/ -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/memedog/llmjudge/prompts.py tests/llmjudge/test_prompts.py
git commit -m "feat(llmjudge): surface smart-money consensus + narrative in evidence/workflow

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Twitter 弃用收尾 + 全量回归

**Files:**
- Modify: `src/memedog/config/settings.py`（`EnricherConfig.twitter_lookback_min` / `Settings.twitter_bearer` 弃用注释)
- Modify: 任何仍向 Enricher 传 twitter 的装配点(按需)
- Test: 全套

- [ ] **Step 1: 确认 twitter 不再驱动生产**

Run: `grep -rn "twitter_client\|count_mentions\|twitter_growth\|twitter_mentions" src/memedog/enricher src/memedog/scoring`
Expected: enricher/scoring 里**不再有**对 twitter 的活跃调用(仅可能残留 deprecated 字段定义)。若有活跃调用,清除。

- [ ] **Step 2: 加弃用注释**

在 `src/memedog/config/settings.py`:给 `EnricherConfig.twitter_lookback_min`、`Settings.twitter_bearer` 上方各加注释 `# deprecated: Twitter 已移出生产路径(Phase 1),保留以兼容旧配置`。不删字段(避免破坏旧 .env/yaml 加载)。

- [ ] **Step 3: 跑全量回归**

Run: `pytest -q`
Expected: 全绿(allow 既有 skip)。若有失败,优先排查:
- 仍把 `_load_smart_wallets` 当 set 用的地方;
- 仍断言 social 维度受 twitter_growth 影响的旧测试(改为断言不受影响);
- 断言 4 维 / 旧权重的 scoring 测试(改 5 维)。
逐一修正(改测试以匹配新设计,**不要**弱化断言)。

- [ ] **Step 4: demo 离线端到端**

Run: `pytest -q tests/test_app_factory.py -k demo`
并(可选)`python -m memedog.serve --demo` 手动起一下确认 snapshot 含 narrative。
Expected: PASS / 看板正常。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: deprecate Twitter config; full regression green for Phase 1

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review 记录

- **Spec 覆盖:** §2 目标 A→Task 3/4/7;B→Task 5/6/7;C(叙事)→Task 2/7/8/9;D(去 Twitter)→Task 7/8/10;§3 数据契约→Task 1;§4.C4 打分→Task 8;§4.E prompt→Task 9;§权重→Task 8;§6 测试→各任务 TDD + Task 10 回归。PaperTrader/Phase 2 明确排除,未建任务(符合 spec 非目标)。无遗漏。
- **占位符扫描:** 无 TBD/TODO;每个代码步给出完整代码与确切命令/期望。少量"参考文件已有 fixture 构造"为测试装配说明(指向真实既有模式),非代码占位。
- **类型一致性:** `WalletInfo(address,label,tier)`、`NarrativeInfo(available,category,matched_keywords,meme_collision,summary)`、`analyze_smart_money -> {buys,distinct_wallets,buyers,top_tier}`、`fetch_social(mint,helius_client,smart_wallets:dict,social_platforms,galaxy_score)`、`score_narrative(info,cfg)`、`ScoringNarrativeConfig(category_scores,meme_collision_bonus)` 在各任务一致;category 集合与 `category_scores` 键一致(animal/ai/political/culture/finance_utility/unknown)。
- **顺序与绿:** Task 1 数据契约带默认值→不破坏 call-site;Task 3 改加载器后完整 enricher 测试暂红、Task 7 修复(已注明);Task 8 改 scoring 维度/权重并同步更新 thresholds.yaml + scoring 测试,保持 load_config 一致;Task 10 兜底全量回归。
