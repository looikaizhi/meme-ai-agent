# X/Twitter 近一年 Meme 币高收益策略研究

研究日期: 2026-06-22  
时间窗口: 2025-06-22 至 2026-06-22  
用途: 为 MemeDog Radar 的 Scanner、Enricher、ScoreEngine 设计提供策略样本。

> 重要说明: Meme 币属于极高风险市场。本报告总结的是 X/Twitter 上公开分享的交易方法和声称有效的流程,不是投资建议,也不是收益保证。很多帖子使用了 "100x"、"高胜率"、"金狗" 等营销语言,需要用链上数据回测验证。

## 1. 检索范围与限制

本次检索使用公开 Web 搜索、X 公开 SEO 页面、X trending/Grok 摘要页、X article/status URL 片段。尝试过 X guest GraphQL 和单帖 syndication 接口,但当前环境没有 X 登录态/API 权限,无法稳定读取所有 thread 全文。因此:

- 已检索 100+ 条公开索引候选结果,并剔除明显广告、赌博、云挖矿、非 Meme 交易内容。
- 对有 `status` 或 `article` ID 的 X 链接,用 Twitter Snowflake ID 反推发布日期,筛掉 2025-06-22 之前的旧帖。
- 样本内频次代表"公开索引样本中出现多少次",不代表全 Twitter 真实占比。
- 未能严格证明"100 条高质量攻略帖全文均已读取",因为 X 登录墙限制了全文访问。以下结论采用可验证标题、摘要、片段和公开文章页归纳。

## 2. 样本内最多人使用的方法排序

| 排名 | 方法族 | 样本内出现次数 | 核心逻辑 | 适合放入 MemeDog Radar 的模块 |
|---:|---|---:|---|---|
| 1 | 聪明钱/盈利钱包追踪 | 24 | 找长期盈利钱包、KOL 钱包、早期买入钱包,跟踪其新仓和共识买入 | Enricher.holders/social, ScoreEngine |
| 2 | 工具流扫链和过滤 | 18 | 用 GMGN、Axiom、Photon、DexScreener、Moby、Bitget 金狗雷达筛新币 | Scanner, HardFilter |
| 3 | 仓位、止盈止损、退出纪律 | 14 | 小仓试错、分批止盈、禁止追高二次买回、限制单币亏损 | PaperTrader, ScoreEngine |
| 4 | 叙事、社交热度、KOL 传播 | 10 | 看 X 讨论度、Kaito/InfoFi 热度、社区传播速度、文化 meme 强度 | Enricher.social, LLMJudge |
| 5 | Pump.fun 迁移/低市值早期盘 | 9 | 关注内盘到外盘迁移、迁移后成交量放大、Memescope/直播流量 | Scanner, MomentumInfo |
| 6 | 反 Rug/反 Bundle/持币结构检查 | 8 | 查 holder 集中度、bundle、dev 历史、前排钱包、LP/权限风险 | HardFilter, Enricher.holders/safety |
| 7 | 波段/反 PVP/形态重复模式 | 6 | 不抢开盘,等放量、回踩、二次启动或大跌后反转 | ScoreEngine.momentum |
| 8 | 长持/Conviction/Diamond Hands | 5 | 选择强社区、强文化和持续传播标的,用长期信念换大倍数 | LLMJudge |
| 9 | AI Agent/自动化交易 | 4 | 将筛选、买入、TP/SL、跟单交给自动化 Agent 或 Bot | Orchestrator, future live trading |
| 10 | LP/DLMM 流动性收益 | 2 | 不只买币,在 Meteora/DLMM 等池子做主动流动性管理赚手续费 | 暂不属于 MVP,可作为后续模块 |

## 3. 方法流程总结

### 3.1 聪明钱/盈利钱包追踪

核心观点: 很多高收益攻略不直接教"买什么币",而是教"跟谁"。在样本中,GMGN、Moby、Axiom、OpenClaw、Bitget 金狗雷达、各类 Telegram 信号群都围绕这个逻辑。

流程:

1. 从历史大涨 Meme 币中回溯早期买入钱包。
2. 过滤掉一次性中彩票的钱包,保留多次盈利、低回撤、非项目方的钱包。
3. 观察这些钱包是否同时买入同一新币,形成 group confirmation。
4. 对候选币做二次过滤: 市值、流动性、交易量、持币集中度、前排钱包、dev 历史。
5. 小仓进入,设置硬止损或时间止损。
6. 若聪明钱持续加仓、交易量放大、社交热度扩散,允许加仓。
7. 若聪明钱快速卖出、前排砸盘、holder 变差,立即退出。

关键指标:

- 监控钱包的历史 PnL、胜率、平均持仓时间。
- 同时买入的高质量钱包数量。
- 买入时市值和当前市值差。
- 钱包是否经常买在 KOL 发推之前。
- 钱包是否与 deployer、dev、前排地址有资金关联。

落地到 MemeDog Radar:

- `smart_money_buys`: 过去 5-60 分钟内标注钱包买入数。
- `smart_money_consensus`: 买入钱包是否来自不同集群。
- `smart_money_quality`: 钱包历史胜率、平均 ROI、最大回撤。
- `dev_wallet_overlap`: 聪明钱是否疑似 dev/insider。

风险:

- 热门聪明钱钱包会被反向利用,项目方可能制造假跟单信号。
- 跟单延迟会导致买在别人出货前。
- 只看盈利钱包容易幸存者偏差。

代表来源:

- GMGN Alerts, "AI Agents Are Eating the Memecoin Trenches", 2026-06-09: https://x.com/gmgnalerts/status/2064247161231937845
- GMGN Alerts, "How to Read GMGN Token Data Like a Pro", 2026-06-08: https://x.com/gmgnalerts/article/2063974806026858621
- OffGridKat, "The Ultimate Guide to Moby", 2026-06-01: https://x.com/OffGridKat/article/2061442415093796884
- OffGridKat, "Memecoin Playbook: How to Find Runners and Stay Alive", 2026-04-03: https://x.com/OffGridKat/article/2039737814422556895
- XDmnnn, "追踪聪明钱在买什么", 2026-03-16: https://x.com/XDmnnn0616/article/2032026571989520663
- NFTCPS, 低市值聪明钱包案例, 2026-01-28: https://x.com/NFTCPS/status/2016402166337163398
- qkl2058, 分散跟 3-5 个高胜率钱包, 2026-04-08: https://x.com/qkl2058/status/2041783546604585252

### 3.2 工具流扫链和过滤

核心观点: 近一年攻略里最常见的不是手动找币,而是使用交易终端和扫描器。被反复提到的工具包括 GMGN、Axiom、Photon、DexScreener、Moby、MevX、Bitget Wallet 金狗雷达、OpenClaw、Meteora Discovery Pool。

流程:

1. 用扫描器拉取新币或热门池子。
2. 先按硬条件过滤: 流动性、交易量、买卖比、市值区间、创建时间。
3. 查看 holder、bundle、前排钱包、dev 历史、社交链接。
4. 使用交易终端快速下单,减少手动跳转导致的延迟。
5. 设置预定义交易模板: 买入金额、滑点、止盈、止损、卖出比例。
6. 建立 watchlist,只交易符合自己规则的币。

常见筛选条件:

- 市值小但成交量快速放大。
- 买单数量和净流入上升。
- 持币分布没有明显单点集中。
- 有真实社交账号和持续讨论。
- 无明显 bundle、黑名单权限、冻结权限、异常 LP 风险。

落地到 MemeDog Radar:

- Scanner 使用 DexScreener/Pump.fun/Meteora 数据做候选池。
- HardFilter 加入 holder、bundle、LP、权限红线。
- Enricher 增加工具信号字段,例如 Dex ad、迁移状态、热门榜排名。

风险:

- 工具越普及,优势越容易被抢跑。
- 交易终端可能放大过度交易。
- 返佣推广帖很多,需要区分攻略和广告。

代表来源:

- BlackhatEmpire, GMGN/Trojan/Axiom 终端对比, 2026-02-05: https://x.com/BlackhatEmpire/status/2019333072601116928
- AutorunSOL, Axiom setup guide, 2026-06-02: https://x.com/AutorunSOL/status/2061692383616499876
- thelearningpill, TON Meme trading guide, 2026-05-09: https://x.com/thelearningpill/status/2053105282159645025
- MEVX Official, AFK Trade and migration sniper, 2026-06-08: https://x.com/MEVX_Official/article/2064017033021497376
- xixikawaii, BSC 链上打狗指南, 2026-01-20: https://x.com/xixikawaii/status/2013522582885278160

### 3.3 仓位、止盈止损、退出纪律

核心观点: 很多高收益帖子强调,赚钱不是因为胜率极高,而是因为亏损被限制、盈利被放大。样本里常见话术包括 "do not double dip"、"smaller ruin odds"、"position sizing"、"auto TP/SL"。

流程:

1. 每笔只投入组合的一小部分,低市值币更小仓。
2. 买入前写清楚: 入场理由、无效条件、止损、第一止盈、最终退出。
3. 到达第一目标先取回本金或部分利润。
4. 剩余仓位跟随趋势,用移动止盈或分批卖出。
5. 禁止卖出后因为 FOMO 再买回,除非重新满足完整入场条件。
6. 记录每笔交易,按策略类型统计胜率、R 值、平均亏损。

可参数化规则:

- 单币最大亏损: 0.25%-1% 组合权益。
- 首次止盈: 2x 卖 30%-50%。
- 回撤退出: 从高点回撤 30%-50% 或跌破关键支撑。
- 时间止损: 30-120 分钟无放量即退出。

落地到 MemeDog Radar:

- PaperTrader 支持 TP/SL/timeout。
- ScoreEngine 不只给买入信号,还给 position size 建议。
- Dashboard 增加每类策略的胜率、平均盈亏比、最大回撤。

风险:

- 自动止损在低流动性池里可能滑点巨大。
- Meme 币常见瞬时插针,过紧止损会被扫出。
- 过度分批可能错失极少数大赢家。

代表来源:

- BlackhatEmpire, "Degens Don't Need Bigger Entries", 2026-06-12: https://x.com/BlackhatEmpire/article/2065455353794322849
- 0xEthan, multiple six figures in 2025, 2026-01-18: https://x.com/0xEthan/status/2012694177541505471
- OKX Wallet, AI agents fail because execution is bad, 2026-03-25: https://x.com/wallet/status/2036695205789708369
- askginadotai, auto take-profit example, 2025-12-13: https://x.com/askginadotai/status/1999915754427191647

### 3.4 叙事、社交热度、KOL 传播

核心观点: Meme 币不靠现金流定价,更多靠注意力和传播。攻略常把 X 讨论度、KOL 参与、社区 meme 产出、Kaito/InfoFi 热度作为确认信号。

流程:

1. 先从链上发现早期异动。
2. 搜索 X 是否已有自然讨论,而不是只有机器人刷屏。
3. 判断叙事是否简单、可传播、能被二创。
4. 观察是否有多个 KOL 或社区节点开始自发扩散。
5. 比较社交热度和市值是否匹配: 热度高、市值低才有赔率。
6. 社交热度衰退、KOL 转移、社区停更时退出。

适合量化的指标:

- `twitter_mentions_1h`
- `unique_influencers_1h`
- `mention_growth`
- `kaito_mindshare`
- `telegram_growth`
- `meme_velocity`: 图片、视频、二创数量增长。

风险:

- KOL 可能提前建仓后出货。
- 机器人刷量会制造假热度。
- 高热度币的入场点往往已经偏晚。

代表来源:

- X trending, "Memecoins: Easy Wins Gone for New Traders?", 2025-11-24: https://x.com/i/trending/1992767569560842741
- X trending, "Crypto Traders Stress Conviction Over Meta-Chasing", 2025-12-22: https://x.com/i/trending/2003202084196213158
- wang_xiaolou, Kaito 华语总结, 2025-09-16: https://x.com/wang_xiaolou/status/1967883916938989690
- 0xVeil, SPX 路径分析, 2025-08-12: https://x.com/0xVeil/status/1955254702473634191/photo/3

### 3.5 Pump.fun 迁移/低市值早期盘

核心观点: 早期盘的赔率最高,但 PVP 最重。帖子里常见两个分支: 一个是抢 pump.fun 内盘/迁移,另一个是等迁移到外盘后再确认放量。

流程:

1. 监听新发币和 bonding curve 进度。
2. 不在完全无数据阶段盲抢,先看前排钱包、bundle、dev 行为。
3. 迁移到 Raydium/Meteora/Jupiter 相关路由后,观察 5m 成交量是否异常放大。
4. 过滤明显直播割韭菜、streamer 先手盘、狙击钱包过多的标的。
5. 符合流动性、持币、热度条件后小仓试错。
6. 若 5m/15m 动能持续,分批加仓;若成交缩量或大户出货,退出。

更保守的版本:

- 只做外盘,不做内盘。
- 只做迁移后 5m K 线放量。
- 只做有真实社区和多钱包共识的币。

风险:

- 同块 sniping、bundle、MEV 对普通用户非常不友好。
- 直播带单、Memescope 活动里大量跟单者可能成为退出流动性。
- 迁移瞬间滑点和失败交易成本高。

代表来源:

- X trending, PumpFun trading stats, 2026-02-13: https://x.com/i/trending/2022206435770421745
- X trending, Memescope Monday, 2026-03-29: https://x.com/i/trending/2038225898172805605
- X trending, Memescope losses, 2026-03-31: https://x.com/i/trending/2038310188672008689
- MoonDevOnYT, sniper bots to pump.fun adaptation, 2026-02-05: https://x.com/MoonDevOnYT/status/2019421553499468270

### 3.6 反 Rug/反 Bundle/持币结构检查

核心观点: 很多攻略的真实价值不是发现上涨,而是排除必亏盘。高频提到的检查包括 holder 集中度、bundle、前排钱包、dev 历史、LP、权限、社交账号复用。

流程:

1. 拿到候选 mint 后先查合约权限和 LP 风险。
2. 计算 top holders 占比,剔除 LP 后再看真实集中度。
3. 检查前 20-100 个买入钱包是否同源、同资金来源、同时间买入。
4. 检查 deployer 是否反复发币、反复 rug。
5. 查社交账号创建时间、是否复用旧账号、是否买粉。
6. 任一红线命中则不进入 ScoreEngine。

建议红线:

- top10 非 LP 持仓过高。
- 单钱包持仓过高。
- 新钱包批量同源注资。
- dev 历史多次短命发币。
- 社交账号当天创建或名称频繁变更。
- 交易量异常但 unique buyer 很低。

落地到 MemeDog Radar:

- HardFilter 做强约束,不要交给 LLM 主观判断。
- Helius/RPC 拉 largest accounts、token accounts、交易历史。
- RugCheck 做权限、LP、风险报告。

风险:

- 完全安全的 Meme 币很少,阈值过严会漏掉早期机会。
- 一些 rug 信号需要地址图谱,单 API 不够。

代表来源:

- BlackhatEmpire, first buyers/snipers/wallet monitoring, 2026-02-05: https://x.com/BlackhatEmpire/status/2019333072601116928
- X trending, Boogiepnl rug accusations and wallet/liquidity checks, 2025-12-16: https://x.com/i/trending/2000800357866205660
- Syra Agent, structured token lenses with RugCheck/Nansen, 2026-02-04: https://x.com/syra_agent/status/2021064952765874204

### 3.7 波段/反 PVP/形态重复模式

核心观点: 中文样本里很多强调"反 PVP"和"链上量化波段",即不去抢最早的一秒,而是等数据确认后做 2-5 倍波段。

流程:

1. 建立可交易池: 过滤掉明显死币、极低流动性、权限风险。
2. 观察回调后的成交量和大户行为。
3. 寻找重复模式: 大跌后横盘、净流入恢复、聪明钱重新买入、社交重新扩散。
4. 入场后用网格、分批 TP、移动止损管理。
5. 不追连续大阳线,不在流动性枯竭时补仓。

适合的指标:

- 5m/15m 成交量放大。
- buy/sell ratio 修复。
- 大户不再持续卖出。
- 高胜率钱包重新建仓。
- 市值回踩关键区间后不破。

风险:

- Meme 币波段经常从"回调"变成"归零"。
- 低流动性下技术指标失真。

代表来源:

- NFTCPS, meme 波段和高胜率钱包, 2025-07-29: https://x.com/NFTCPS/status/1950187648389177617
- NFTCPS, meme 波段案例, 2025-07-30: https://x.com/NFTCPS/status/1950394580282855535
- NFTCPS, TP BOT 图文教程, 2025-07-30: https://x.com/NFTCPS/status/1950395196040151503

### 3.8 长持/Conviction/Diamond Hands

核心观点: 少数最高倍数收益来自长持,不是高频交易。相关帖子认为真正的大赢家要识别强文化、强社区、强 meme,并承受大回撤。

流程:

1. 只在已经通过安全过滤的标的里寻找强文化币。
2. 判断社区是否持续产出内容,而不是一次性拉盘。
3. 观察大户是否锁仓、社区是否愿意长期传播。
4. 分批建仓,不要全仓追高。
5. 只在叙事失效、社区瓦解、链上大户持续退出时卖出。

适合指标:

- 持仓时间分布。
- diamond hands 占比。
- 社区内容持续性。
- KOL 讨论周期长度。
- 回撤后交易量是否恢复。

风险:

- "信仰"很容易变成不止损。
- 绝大多数 Meme 币不会走成 BONK/SPX/Fartcoin 级别。

代表来源:

- theunipcs, BONK conviction AMA, 2025-08-07: https://x.com/theunipcs/status/1953408691182448794
- 0xEthan, White Whale / diamond hands strategy, 2025-12-28: https://x.com/0xEthan/status/2005371683788750880
- X trending, conviction over metas, 2025-12-22: https://x.com/i/trending/2003244562056454375

### 3.9 AI Agent/自动化交易

核心观点: 2026 年样本中开始出现"AI agent 吃掉 trenches"的说法。核心不是模型预测涨跌,而是自动执行: 监控、筛选、买入、止盈止损、跟单。

流程:

1. 给 Agent 设置允许交易的链、池子、市值范围、最大滑点。
2. 输入策略: 跟单钱包、迁移 sniper、DEX 广告买入、智能钱共识等。
3. 配置 TP/SL、最大持仓数、最大单币亏损。
4. Agent 只执行规则,交易日志回写。
5. 定期回测和淘汰失效策略。

风险:

- 自动化会放大坏策略。
- 私钥和授权风险极高。
- 交易失败、滑点、MEV、RPC 延迟都会影响收益。

代表来源:

- GMGN Alerts, AI agents and agent wallets, 2026-06-09: https://x.com/gmgnalerts/status/2064247161231937845
- OKX Wallet, execution issues for agents, 2026-03-25: https://x.com/wallet/status/2036695205789708369
- PumpDevIO, agent skill for pump.fun, profile snippet: https://x.com/PumpDevIO
- RollX, AI trading stack, 2026-05-25: https://x.com/rollxfi/article/2059039486567473592

### 3.10 LP/DLMM 流动性收益

核心观点: 少数帖子不建议直接 PVP 买币,而是利用 Meteora DLMM、动态 LP、memecoin liquidity farming 赚手续费。

流程:

1. 找波动大且成交活跃的池子。
2. 选择 DLMM 策略形状: spot、curve、bid-ask 或多仓位。
3. 控制 token-sided exposure,避免单边暴露过重。
4. 定期 rebalance,把仓位移到成交活跃区间。
5. 监控无常损失、手续费收入、池子深度和项目风险。

风险:

- 无常损失可能大于手续费。
- Meme 币归零时 LP 会变成接盘。
- 需要更复杂的策略管理,不适合当前 MemeDog Radar MVP。

代表来源:

- Meteora_PH, strategy shift away from heavy token-sided exposure, 2026-06-15: https://x.com/Meteora_PH/status/2066420925114011654
- Sinagster, Meteora Discovery Pool 30m filter, 2026-02-12: https://x.com/sinag_crypto/status/2024032467036913772
- skolmbeaghNFT, DLMM guides, 2025-07-28: https://x.com/skolmbeaghNFT/status/1949815355112570995

## 4. 对 MemeDog Radar 的策略映射

建议把 X 上最多人使用的方法转成可量化字段,而不是直接照搬主观判断。

### Scanner

优先发现:

- 新 pair / 新 mint。
- pump.fun 迁移外盘。
- 5m volume 异常放大。
- liquidity 突破阈值。
- DexScreener/GMGN/Axiom 热榜出现。

### HardFilter

必须过滤:

- 权限未放弃。
- holder 过度集中。
- bundle 或同源前排钱包明显。
- dev 历史不良。
- 流动性过低或买卖不可持续。

### Enricher

重点补齐:

- top10 holder pct。
- max wallet pct。
- smart money buys。
- smart money consensus cluster。
- unique buyers。
- social mentions growth。
- KOL mentions。
- dev wallet history。

### ScoreEngine

建议初始权重:

| 维度 | 权重 | 理由 |
|---|---:|---|
| safety | 0.30 | 先活下来,避免 rug |
| holders | 0.25 | 聪明钱和集中度是样本中最高频方法 |
| momentum | 0.25 | 成交量、流动性、买卖比决定短线能否走出来 |
| social | 0.20 | Meme 币最终靠注意力扩散 |

### LLMJudge

LLM 不应该负责判断合约是否危险。LLM 适合做:

- 叙事是否容易传播。
- Bull/Bear 论点平衡。
- 是否属于"工具信号强但社交弱"或"社交强但链上危险"。
- 是否有明显 exit liquidity 风险。

## 5. 推荐落地的三套 MVP 策略

### 策略 A: 聪明钱共识追踪

1. Scanner 拉新盘。
2. HardFilter 排除权限、holder、LP 红线。
3. Helius 统计过去 30 分钟标注钱包买入。
4. 如果 3 个以上不同集群高质量钱包买入,加分。
5. DexScreener 确认 5m volume 和 buy/sell ratio。
6. PaperTrader 小仓入场,2x 取回本金,剩余仓位跟踪。

### 策略 B: 外盘迁移放量

1. 监听 pump.fun 迁移或新 Raydium/Meteora pair。
2. 等外盘 5m K 线成交量放大。
3. 检查前排钱包和 bundle。
4. 检查社交链接是否真实。
5. 小仓进入,30-60 分钟无延续则退出。

### 策略 C: 反 PVP 波段

1. 只看已通过安全检查的币。
2. 等第一波拉升后回调。
3. 如果聪明钱没有完全退出、交易量恢复、社交继续增长,进入。
4. 分批止盈,不追二次 FOMO。

## 6. 代表性来源索引

以下为本次研究中被用于归纳的公开 X 来源。`status/article` 的日期可通过 Snowflake 反推; `trending/profile/highlights` 只能作为公开摘要或线索。

| ID | 来源 | 类型 | 日期/时间性 | 归类 |
|---|---|---|---|---|
| S001 | https://x.com/gmgnalerts/status/2064247161231937845 | status | 2026-06-09 | AI agent, 聪明钱 |
| S002 | https://x.com/gmgnalerts/article/2063974806026858621 | article | 2026-06-08 | GMGN 数据读取 |
| S003 | https://x.com/OffGridKat/article/2061442415093796884 | article | 2026-06-01 | Moby, whale consensus |
| S004 | https://x.com/OffGridKat/article/2039737814422556895 | article | 2026-04-03 | Memecoin playbook |
| S005 | https://x.com/OffGridKat/status/2031848336806809635 | status | 2026-03-12 | smart money rotation |
| S006 | https://x.com/BlackhatEmpire/article/2065455353794322849 | article | 2026-06-12 | 仓位和 ruin risk |
| S007 | https://x.com/BlackhatEmpire/status/2019333072601116928 | status | 2026-02-05 | 终端对比, wallet monitoring |
| S008 | https://x.com/MEVX_Official/article/2064017033021497376 | article | 2026-06-08 | AFK, migration sniper |
| S009 | https://x.com/wallet/status/2036695205789708369 | status | 2026-03-25 | AI agent execution |
| S010 | https://x.com/0xEthan/status/2012694177541505471 | status | 2026-01-18 | 信息速度, double dipping |
| S011 | https://x.com/0xEthan/status/2005371683788750880 | status | 2025-12-28 | diamond hands |
| S012 | https://x.com/theunipcs/status/1953408691182448794 | status | 2025-08-07 | conviction case |
| S013 | https://x.com/thelearningpill/status/2053105282159645025 | status | 2026-05-09 | TON meme guide |
| S014 | https://x.com/AutorunSOL/status/2061692383616499876 | status | 2026-06-02 | Axiom setup |
| S015 | https://x.com/TradeSimplest/status/2029987795712827683 | status | 2026-03-06 | Nansen/profitable wallets |
| S016 | https://x.com/desola__xn/status/2006368495710433488 | status | 2025-12-31 | group confirmation |
| S017 | https://x.com/WhiteWhaleLabs/status/2045184600029254102 | status | 2026-04-17 | debrief, CTO risk |
| S018 | https://x.com/GemisAlpha/status/2049758075142230100 | status | 2026-04-30 | repetitive patterns |
| S019 | https://x.com/DonnyDicey/status/2044859008885149964 | status | 2026-04-16 | memecoin playbook critique |
| S020 | https://x.com/Xpad_Official/article/2059986844289237486 | article | 2026-05-28 | flip vs earning |
| S021 | https://x.com/ClaudeOnSolana/status/2028524890161062298 | status | 2026-03-02 | playbook |
| S022 | https://x.com/AveaiGlobal/status/2053936328107343939 | status | 2026-05-11 | smart money/KOL signals |
| S023 | https://x.com/askginadotai/status/1999915754427191647 | status | 2025-12-13 | auto take-profit |
| S024 | https://x.com/thegreatola/status/2011745584013861344 | status | 2026-01-15 | sector risk |
| S025 | https://x.com/qkl2058/status/1976390726138433998 | status | 2025-10-09 | GMGN smart wallet |
| S026 | https://x.com/qkl2058/status/1975546079971319993 | status | 2025-10-07 | wallet tracking |
| S027 | https://x.com/qkl2058/status/1976497479093977320 | status | 2025-10-10 | insider wallet |
| S028 | https://x.com/qkl2058/status/2058579987566055837 | status | 2026-05-24 | GMGN 扫链 |
| S029 | https://x.com/qkl2058/status/2041783546604585252 | status | 2026-04-08 | 高胜率钱包分散跟单 |
| S030 | https://x.com/NFTCPS/status/1950187648389177617 | status | 2025-07-29 | meme 波段 |
| S031 | https://x.com/NFTCPS/status/1950394580282855535 | status | 2025-07-30 | 量化波段 |
| S032 | https://x.com/NFTCPS/status/1950395196040151503 | status | 2025-07-30 | TP BOT |
| S033 | https://x.com/NFTCPS/status/2016402166337163398 | status | 2026-01-28 | 聪明钱包案例 |
| S034 | https://x.com/xixikawaii/status/2013522582885278160 | status | 2026-01-20 | BSC 打狗指南 |
| S035 | https://x.com/wang_xiaolou/status/1968323377917239623 | status | 2025-09-17 | Kaito/链上热点 |
| S036 | https://x.com/wang_xiaolou/status/1967883916938989690 | status | 2025-09-16 | PUMP/HYPE 讨论 |
| S037 | https://x.com/uniswap12/status/2059916107893592504 | status | 2026-05-28 | 策略创作者列表 |
| S038 | https://x.com/BiteyeCN/article/2038884038602273200 | article | 2026-03-31 | Meme 生态 |
| S039 | https://x.com/monsterblockhk/status/1964572536391553198 | status | 2025-09-07 | 交易任务/项目筛选 |
| S040 | https://x.com/XDmnnn0616/article/2032026571989520663 | article | 2026-03-12 | OpenClaw 每日简报 |
| S041 | https://x.com/Meteora_PH/status/2066420925114011654 | status | 2026-06-15 | DLMM exposure |
| S042 | https://x.com/sinag_crypto/status/2024032467036913772 | status | 2026-02-18 | Meteora discovery |
| S043 | https://x.com/SolanaVortexBot/highlights | highlights | recent snippet | DLMM semi-auto |
| S044 | https://x.com/skolmbeaghNFT/status/1949815355112570995 | status | 2025-07-28 | DLMM guides |
| S045 | https://x.com/satsmonkes/status/1945022344675909856 | status | 2025-07-15 | DLMM/LP army |
| S046 | https://x.com/CryptoJournaal/status/1991183037640384728 | status | 2025-11-19 | Meteora strategy support |
| S047 | https://x.com/JodienX_/status/2004624125315481676 | status | 2025-12-26 | tactical LP |
| S048 | https://x.com/bellaTLopez/status/1950737437392789815 | status | 2025-07-31 | Meteora liquidity |
| S049 | https://x.com/Castle_labs/status/1954851951075582333 | status | 2025-08-11 | Pump.fun group coins |
| S050 | https://x.com/Mattertrades/status/2011217273504350715 | status | 2026-01-14 | Pump.fun dominance |
| S051 | https://x.com/MoonDevOnYT/status/2019421553499468270 | status | 2026-02-05 | sniper to pump.fun adaptation |
| S052 | https://x.com/PumpDevIO | profile | recent snippet | pump.fun automation |
| S053 | https://x.com/LensProjectSOL | profile | recent snippet | copy trade workflow |
| S054 | https://x.com/Ymirs_signal | profile | recent snippet | co-location/sniper warning |
| S055 | https://x.com/TrulyDivineMS | profile | recent snippet | fast copy/AFK automation |
| S056 | https://x.com/Fried_Dev/with_replies | profile/replies | recent snippet | dev/insider wallet list |
| S057 | https://x.com/ibeamalu_j | profile | recent snippet | beginner meme strategy |
| S058 | https://x.com/gmgncom | profile | recent snippet | GMGN + AI smart money guide |
| S059 | https://x.com/GMGNAiCare/with_replies | profile/replies | 2025-11 snippet | top 50-100 wallets |
| S060 | https://x.com/heurist_ai/article/2021317498499731542 | article | 2026-02-10 | AI research with GMGN |
| S061 | https://x.com/Velvet_Capital/status/2029591838672523680 | status | 2026-03-05 | describe strategy to AI |
| S062 | https://x.com/rollxfi/article/2059039486567473592 | article | 2026-05-25 | AI trading stack |
| S063 | https://x.com/OffGridKat/status/2031848336806809635 | status | 2026-03-12 | whale clustering |
| S064 | https://x.com/i/trending/1992767569560842741 | trending | 2025-11-24 | copy trading debate |
| S065 | https://x.com/i/trending/2028276957985505549 | trending | 2026-03-03 | trader decline |
| S066 | https://x.com/i/trending/2038310188672008689 | trending | 2026-03-31 | Memescope losses |
| S067 | https://x.com/i/trending/2038225898172805605 | trending | 2026-03-29 | Memescope push |
| S068 | https://x.com/i/trending/2039098907767251074 | trending | 2026-04-01 | 58 second hold time |
| S069 | https://x.com/i/trending/2022206435770421745 | trending | 2026-02-13 | PumpFun stats |
| S070 | https://x.com/i/trending/2000800357866205660 | trending | 2025-12-16 | rug/liquidity checks |
| S071 | https://x.com/i/trending/2003202084196213158 | trending | 2025-12-22 | conviction over meta |
| S072 | https://x.com/i/trending/2003244562056454375 | trending | 2025-12-22 | conviction |
| S073 | https://x.com/i/trending/2034826075021214150 | trending | 2026-03-20 | patience over gambling |
| S074 | https://x.com/0xVeil/status/1955254702473634191/photo/3 | status/photo | 2025-08-12 | SPX path |
| S075 | https://x.com/GiggleFundBSC/status/1976047373865685212 | status | 2025-10-08 | community expansion |
| S076 | https://x.com/gm365/status/1951212142675517768 | status | 2025-08-01 | Pump.fun data/story |
| S077 | https://x.com/OrdzWorld/article/1913197033399480573 | article | updated 2026-01-23 | 中文 Meme 指南 |
| S078 | https://x.com/zhuzhuge888/with_replies | profile/replies | 2025-11 snippet | 金狗信号 |
| S079 | https://x.com/Huwangyan | profile | recent snippet | 回测/自定义信号 |
| S080 | https://x.com/metropio_news/highlights | highlights | recent snippet | signal screener |
| S081 | https://x.com/couragedefi | profile | recent snippet | 新手 memecoin 策略 |
| S082 | https://x.com/ibeamalu_j | profile | 2026-05 snippet | 新手 memecoin 策略 |
| S083 | https://x.com/0xkhlassic | profile | recent snippet | Axiom workflow |
| S084 | https://x.com/NabilAminuBawa | profile | recent snippet | anti-rug/trading guide |
| S085 | https://x.com/top7ico/status/2027029998335336935 | status | 2026-02-26 | insider/bundler tracking |
| S086 | https://x.com/coinesper/status/2010482930267652446 | status | 2026-01-11 | anti-sniper strategy |
| S087 | https://x.com/NFTTrack | profile | recent snippet | wallet tracking/sniper detection |
| S088 | https://x.com/voxelizes/with_replies | profile/replies | recent snippet | bundle warning |
| S089 | https://x.com/CryptoPatel/status/2011037762183401814 | status | 2026-01-13 | random tweet memecoin warning |
| S090 | https://x.com/atareh/status/1958350450459042110 | status | 2025-08-21 | anti-sniping launch design |
| S091 | https://x.com/monad/status/2014760037449715984 | status | 2026-01-23 | Fomo/copy trading case |
| S092 | https://x.com/Cesco_Sol | profile | recent snippet | public wallet/bundle risk |
| S093 | https://x.com/santimentfeed/status/1958616509611209016 | status | 2025-08-21 | insider dump risk |
| S094 | https://x.com/shinytechapes | profile | recent snippet | bundler distribution strategy |
| S095 | https://x.com/i/trending/2026808307932074280 | trending | 2026-02-25 | Axiom tool-abuse risk |
| S096 | https://x.com/QuiverQuant | profile | 2026-06 snippet | suspicious trade detection |
| S097 | https://x.com/ProfullstackInc/status/2045903405605167534 | status | 2026-04-19 | launch automation architecture |
| S098 | https://x.com/FourPillarsFP/status/1945407764387573835 | status | 2025-07-16 | bundle/MEV infrastructure |
| S099 | https://x.com/search?q=%24DBP | X search result | recent snippet | first 70 buyers ratio |
| S100 | https://x.com/search?q=Four.Meme+coin | X search result | recent snippet | first 70 buyers / risk label |

## 7. 结论

近一年公开样本里,最主流的高收益 Meme 币策略不是单一的"冲早盘",而是四件事的组合:

1. 用工具快速发现候选。
2. 用链上数据排除必亏盘。
3. 用聪明钱和社交热度确认动量。
4. 用仓位和退出纪律控制归零风险。

对 MemeDog Radar 来说,最值得优先实现的是:

1. `smart_money_buys` 和高质量钱包库。
2. holder/bundle/dev 风险过滤。
3. 5m/15m 动量确认。
4. 社交热度增长。
5. PaperTrader 回测不同 TP/SL 和 position sizing。

不要把 LLM 放在最前面选币。LLM 应该只在候选已经通过硬过滤、链上富化和量化打分后,负责解释叙事、指出冲突信号和生成最终交易理由。
