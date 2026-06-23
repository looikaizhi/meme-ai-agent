# 实时发现层(PumpPortal + Helius)设计

**状态:** 已批准设计,待写实现计划
**分支:** `feature/realtime-discovery`
**日期:** 2026-06-23

---

## 1. 背景与问题

Scanner 当前用 DexScreener `GET /token-profiles/latest/v1` 作为"发现最新币"的来源。**这是错的**:该端点返回的是 DexScreener 的"代币资料卡(token profiles)"——即被推广/更新过 profile 的代币列表,**不是新发行/新上池的币**。因此第一层(发现"金狗")并不能真正实时捕获最新 meme 币。

两轮联网研究 + 真实抓包交叉验证后的关键事实:

1. **DexScreener 没有"实时新发现"API**。它的收录前提是"代币已进入流动性池且至少有一笔交易",所以**不索引仍在 bonding curve 上的 pump.fun 新币**,只在**毕业(graduate)到 PumpSwap/Raydium 之后**才有 pair / 流动性 / 量。
2. **最优实时发现源 = PumpPortal WebSocket**(`wss://pumpportal.fun/api/data`),免费、无需 API key、事件级推送。
3. **官方兜底 = Helius `logsSubscribe` 监听 pump.fun 程序**(复用已有 Helius key)。
4. PumpPortal 无 SLA、会自行断线、滥用连接会被临时封 IP(单连接 + 重连退避即可规避)。

### 1.1 真实抓包证据(本设计的数据契约依据)

`subscribeMigration` 真实消息(本机实测捕获):
```json
{
  "signature": "eim7s8A6z3ZBK7yFYRZm4RMWDZHtWVXKHM7LtgnCzpapogLjnN1JnLqbkPZWsA5d4nY7EHaF5zuQ2WearaQ5nhm",
  "mint": "8yo564u5NKNzKV3jWQTSqSxXXFX69ALgweu4c8eapump",
  "txType": "migrate",
  "pool": "pump-amm"
}
```
订阅成功 ack(需被解析逻辑忽略):
```json
{ "message": "Successfully subscribed to token creation events." }
```
Helius:连接 + `logsSubscribe` 订阅 ack 正常;返回的是**原始日志**,需 base64 解码迁移指令才能取出 mint;30s 内 400 条通知绝大多数是买卖交易,Create/迁移事件稀疏。

## 2. 选定窗口与核心洞察

**窗口 = "刚毕业(just-graduated)"**(用户已拍板)。理由:刚毕业的币已落到 PumpSwap/Raydium,**现有 DexScreener 富化层 + ScoreEngine 原样可用**,几乎不改下游;且仍处在"发盘几十分钟~几小时"的目标窗口内。代价是放弃 bonding-curve 阶段最早的入场点(作为未来 early-watch 层,不在本设计范围)。

**核心洞察 —— "发现"只需要一个东西:`mint`。**
其余所有 candidate 字段(symbol / 流动性 / 量 / 价格 / FDV / 买卖笔数 / 建池时间)都由**毕业后的 DexScreener 富化**提供,不是发现源的职责。

| 项目在"发现"阶段需要的基础数据 | 来源 |
|---|---|
| 刚毕业币的 `mint` | PumpPortal(干净给出)/ Helius(同一事件,需解码原始日志) |
| symbol / 流动性 / 量 / 价格 / FDV / 买卖笔数 / 建池时间 | DexScreener 富化(`get_token_pairs`,两发现源都不提供) |

### 2.1 Helius 的定位:可靠性冗余,而非"补数据"

实测确认:**PumpPortal 在数据上已经足够**(干净给出 `mint`)。Helius 读的是**同一个迁移事件**,只是更原始;它**不提供任何"项目需要但 PumpPortal 缺失"的额外基础数据**。因此 Helius 的价值是**纯可靠性冗余**——当 PumpPortal 断线时,用官方源顶上同一份 `mint`,不是为了取得更丰富的数据。用户要求保留 Helius,本设计将其实现为防御性的冗余备份。

## 3. 架构总览

```
发现"刚毕业的 mint":
   PumpPortal WS (主, 干净给 mint) ──┐
   Helius logsSubscribe (备, 解码取同一 mint) ──┴─► 去重缓冲(TTL) ─► Scanner 排空

富化(查行情):
   DexScreener (毕业后 liquidity/量/价/FDV/笔数 齐全, 下游原样复用)
```

WS 是**推送**,现有 Scanner 是**拉取**——用一个后台 WS 任务维持连接、把收到的 mint 填入**带 TTL 的去重缓冲**,Scanner 每轮通过适配器的 `fetch_latest_token_addresses()` 排空缓冲。**Scanner 本体、HardFilter、Enricher、ScoreEngine、LLMJudge 全部不改。**

## 4. 组件设计(单一职责 + 可独立测试)

### 4.1 `MigrationFeed` 协议
位置:`src/memedog/discovery/feed.py`
```python
class MigrationFeed(Protocol):
    async def run(self, stop_event: asyncio.Event) -> None: ...   # 维持连接, 填缓冲, 永不抛出
    def recent_mints(self) -> list[str]: ...                       # 非破坏性返回未过期 mint
```

### 4.2 `MintBuffer`(带 TTL 的去重缓冲)
位置:`src/memedog/discovery/buffer.py`
- `add(mint: str)`:记录 mint→入队时间戳(已存在则更新?否——保留首次时间以驱动 TTL 过期)。
- `recent() -> list[str]`:返回未过期(`now - ts < ttl`)的 mint,顺序稳定(按加入顺序);**非破坏性**(不弹出),让 Scanner 可跨轮重试同一 mint 直到 DexScreener 收录或 TTL 过期。
- 内部惰性清理过期项。
- TTL 来自配置(默认 ~20min)。
- 纯内存、无 I/O → 完全离线单测。

> **为什么非破坏性 + Scanner 既有 `_seen` 去重**:刚毕业的币 DexScreener 可能延迟几分钟才收录。Scanner 每轮都能在缓冲里看到该 mint 并重试 `get_token_pairs`;一旦成功产出 candidate,Scanner 的 `_seen` 会去重避免重复产出;TTL 过期后缓冲自动丢弃。**既不漏币,也不重复。**

### 4.3 `PumpPortalFeed`(主源)
位置:`src/memedog/discovery/pumpportal.py`
- 连 `wss://pumpportal.fun/api/data`,开连发送 `{"method":"subscribeMigration"}`。
- 每条消息经纯函数 `parse_migration_message(raw: dict) -> str | None`:`txType == "migrate"` 且含 `mint` → 返回 `mint`;ack / 未知 / 缺字段 → `None`。
- `run`:单连接;断线→指数退避重连并重发订阅;`stop_event` 置位则退出;任何异常只记日志不抛。
- **单连接**(避免触发 PumpPortal 封 IP)。

### 4.4 `HeliusMigrationFeed`(冗余备份)
位置:`src/memedog/discovery/helius_feed.py`
- 连 `wss://mainnet.helius-rpc.com/?api-key=...`,发送 `logsSubscribe`(mentions = pump.fun 程序 `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`,commitment `processed`)。
- 纯函数 `parse_helius_log(raw: dict) -> str | None`:识别迁移相关日志并解码取 mint。
- **诚实标注的不确定性**:迁移日志的精确字节布局未文档化。实施时必须**先连真实 WS 抓一条真实迁移 tx 的日志**,据此写解码逻辑并存为 fixture。**若解码不可靠 → 该 feed 返回空贡献(no-op),绝不污染主路**;PumpPortal 独立承载发现。
- 由配置开关 `discovery.helius_enabled` 控制是否启用。

### 4.5 `CompositeFeed`
位置:`src/memedog/discovery/composite.py`
- 并行 `run` 多个子 feed(`asyncio.gather`),共享同一个 `MintBuffer`。
- `recent_mints()` = 缓冲内容(已天然按 mint 去重)→ 主备冗余、互不重复。

### 4.6 `MigrationDiscoverer`(Scanner 适配器)
位置:`src/memedog/discovery/discoverer.py`
- 满足 Scanner 既有 `TokenDiscoverer` 协议:
  - `fetch_latest_token_addresses(chain) -> list[str]` → `feed.recent_mints()`。
  - `get_token_pairs(mint) -> list[dict]` → 委派给注入的 `DexScreenerClient`(不变)。
- **Scanner 一行不改**:它只依赖 `TokenDiscoverer` 协议。

## 5. 生命周期 / 配置 / 依赖

- **后台任务**:`feed.run(stop_event)` 并入 `serve.py` 与 `__main__.py` 现有的 `asyncio.gather`(与 orchestrator、watcher 同级)。
- **app_factory**:`build_orchestrator` 生产路径装配 `CompositeFeed`(PumpPortal[+Helius])+ `MigrationDiscoverer` + Scanner;额外暴露 feed 以便 serve/main 启动其 `run`。`--demo` 路径**不连 WS**(仍用 `DemoScanner`)。
- **配置新段** `discovery`(写入 `thresholds.yaml`,严禁硬编码):
  - `pumpportal_ws_url`、`helius_enabled`(bool)、`helius_ws_url`、`pumpfun_program_id`、`buffer_ttl_min`(默认 20)、`reconnect_backoff_initial_sec` / `reconnect_backoff_max_sec`。
- **Scanner 配置调整**:`min_pair_age_min` 调到允许刚毕业新池(0 或很小),`max_pair_age_min` 覆盖目标窗口。
- **新依赖**:`websockets`(本机已 15.0.1)→ 加入 `pyproject.toml` 依赖。

## 6. 错误处理与不变量

- 断线 → 退避重连(不崩)。
- 未知 / ack / 畸形消息 → 跳过。
- Helius 解码不稳 → 空贡献,主路不受影响。
- discovery 整体不可用 → `recent_mints()` 返回 `[]` → Scanner 既有降级(返回 `[]`),流水线照常空转不崩。
- 所有 `run` 永不向上抛异常(与既有"降级而非崩溃"原则一致)。

## 7. 测试策略(真实数据驱动,非 mock 假设)

延续项目既有测试哲学:默认套件离线确定性、由**真实抓取的报文**驱动;`-m live` 层真实联网且无 key/网络时自跳过。

### 7.1 真实捕获(存入 `tests/fixtures/discovery/`)
- `pumpportal_migration.json` —— ✅ 本设计第 1.1 节已实测捕获,可直接落盘。
- `pumpportal_subscribe_ack.json` —— ✅ 已捕获。
- `helius_migration_log.json` —— 实施时连真实 WS 抓取(若当时无迁移事件,记录此事实并以该 feed 的 no-op 降级路径覆盖)。
- 用 `scripts/capture_fixtures.py` 增补可重跑的捕获入口(不存任何密钥)。

### 7.2 离线测试(默认套件)
- `parse_migration_message`:对真实 fixture → 取出 mint;对 ack / 缺字段 / 错 txType → `None`。
- `parse_helius_log`:对真实日志 fixture → 取出 mint;对噪声日志 → `None`。
- `MintBuffer`:TTL 过期、非破坏性返回、去重、惰性清理。
- `CompositeFeed`:多 feed 写同一缓冲后合并去重。
- `MigrationDiscoverer`:`fetch_latest_token_addresses` 委派 `recent_mints`;`get_token_pairs` 委派 DexScreener(用既有真实 dexscreener fixture)。
- Scanner + `MigrationDiscoverer` 端到端:缓冲注入 mint + 真实 dexscreener fixture → 产出合法 `TokenCandidate`。
- 健壮性:feed `run` 在连接异常下不抛、能退避(用可注入的假 WS 连接工厂,驱动真实重连逻辑——非业务 mock,而是 I/O 边界替身)。

### 7.3 live 测试(`-m live`,自跳过)
- `PumpPortalFeed` 真连 `subscribeMigration`,在超时窗口内收到 ≥1 条可解析消息或干净超时跳过。
- `HeliusMigrationFeed` 真连并收到订阅 ack(需 `HELIUS_API_KEY`)。

### 7.4 验证关卡
- 默认全量套件全过。
- 零外部联网:`pytest --disable-socket --allow-hosts=127.0.0.1,::1,localhost` 全过。
- 既有 501 测试不回归。

## 8. 范围与非目标

- **范围内**:刚毕业窗口的实时发现(PumpPortal 主 + Helius 备 + 缓冲 + Scanner 适配器 + 装配 + 配置 + 真实测试)。
- **非目标**:bonding-curve 分钟级 early-watch 层(未来可加);PumpPortal 成交流自算 momentum;更换富化源。富化继续走 DexScreener。
- **诚实局限**:Helius 迁移日志解码字节布局未文档化,实施需实测;PumpPortal 无 SLA(故做冗余);"刚毕业"是幸存者窗口,会漏掉毕业前的最早入场点。

## 9. 文件清单(预告,细节进实现计划)
- 新增:`src/memedog/discovery/{__init__,feed,buffer,pumpportal,helius_feed,composite,discoverer}.py`
- 修改:`src/memedog/app_factory.py`、`src/memedog/serve.py`、`src/memedog/__main__.py`、`src/memedog/config/settings.py`、`src/memedog/config/thresholds.yaml`、`scripts/capture_fixtures.py`、`pyproject.toml`
- 测试:`tests/discovery/`、`tests/fixtures/discovery/`、`tests/live/test_live_discovery.py`
- 不改:`scanner.py`、`hardfilter/`、`enricher/`、`scoring/`、`llmjudge/`
