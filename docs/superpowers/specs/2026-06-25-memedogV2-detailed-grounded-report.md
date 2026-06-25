# memedogV2 详细 grounded 审计报告 设计规格

> 日期:2026-06-25 · 对象:`src/memedogV2/audit/` + `harness/` · 关联:verify 发现(证据仅 5 标量、Judge rationale 仅 256 字)

## 一、背景与目标

verify 实测:多源流水线真实跑通,但喂给 Bull/Bear/Judge 的证据**只有 5 个标量**(rich gmgn 数据被丢弃),Judge 只输出一句话 rationale。不满足"详细分析报告 + 更详细 meme 数据"的要求。

目标:**不加新阶段、不改数据源**,只做三件事:
1. 把 resolver 已取到的**完整规范 Facts(含每字段来源)**喂给审计三阶段。
2. 每阶段固定一个 grounded 角色 prompt:**只许基于所给数据推理、必须引用具体数字、缺失就说缺失、严禁编造** —— 以此压制幻觉。
3. Judge 输出**结构化 + narrative 报告**:recommended + signal + confidence + summary + strengths[] + risks[] + key_metrics[]。

## 二、非目标

- 不改 `sources/`、`hardfilter/`、数据源、HardFilter 红线。
- 不加新流水线阶段(顺序仍 read_facts→hardfilter→build_evidence→bull→bear→judge→signal)。
- 不引入新外部依赖。

## 三、架构与改动

**数据流不变,丰富证据内容:**
```
ResolvedFacts(完整 Facts + sources)
   ↓ build_evidence_from_facts  (carry 全字段,不再只留 5 标量)
EvidenceBundle(扩展为承载完整 Facts + sources + missing)
   ↓ prompts.evidence_text      (分组、带来源、带 missing 的富文本)
Bull / Bear(grounded 角色 prompt,引用数字) → Judge(结构化+narrative 报告)
   ↓
Signal(扩展:summary/strengths/risks/key_metrics)
```

### 3.1 富证据
`EvidenceBundle` 扩展为携带完整规范字段(安全/集中度/动量/聪明钱·dev 四组)+ `sources: dict[field, src]` + `missing: list`。`build_evidence_from_facts(facts, sources, ca)` 直接搬运,不丢字段。

### 3.2 富文本(prompts.evidence_text)
按四组渲染,每字段 `名称=值 (source: x)`;末尾列 `Missing: [...]`。例:
```
SAFETY: mint_revoked=True (rugcheck) | freeze_revoked=True (rugcheck) | lp_safe=True (rugcheck) | honeypot=False (gmgn)
CONCENTRATION: top10_rate=0.27 (rugcheck) | sniper_count=5 (gmgn) | fresh_wallet_rate=0.1 (gmgn) ...
MOMENTUM: liquidity_usd=57000 (gmgn) | volume_5m=12000 (gmgn) | buys_5m=83 | sells_5m=40 | mcap≈... 
SMART/DEV: smart_money_count=52 (gmgn) | kol_count=6 (gmgn) | dev_created_count=69 (gmgn) | historical_ath=243000000 (gmgn)
Missing: [dev_graduation_rate]
```

### 3.3 grounded 角色 prompt(反幻觉)
三阶段共用硬规则前缀:**"Base your analysis ONLY on the DATA below. Cite specific numbers. If a field is in Missing, treat it as unknown — never invent a value."**
- Bull:列举 upside 论点,每条引用一个指标。
- Bear:列举 risk 论点,每条引用一个指标。
- Judge:综合双方与数据,产出结构化+narrative 报告。

### 3.4 Judge schema(严格,Codex/DeepSeek 通用)
```json
{ "type":"object","additionalProperties":false,
  "properties":{
    "recommended":{"type":"boolean"},
    "signal":{"type":"string","enum":["BULLISH","BEARISH","NEUTRAL"]},
    "confidence":{"type":"number"},
    "summary":{"type":"string"},
    "strengths":{"type":"array","items":{"type":"string"}},
    "risks":{"type":"array","items":{"type":"string"}},
    "key_metrics":{"type":"array","items":{"type":"string"}}
  },
  "required":["recommended","signal","confidence","summary","strengths","risks","key_metrics"] }
```
(全 array[string]/标量,避开 strict 模式嵌套对象坑。)

### 3.5 Signal 扩展
`models/contracts.py` 的 `Signal` 增加:`summary: str = ""`、`strengths: list[str] = []`、`risks: list[str] = []`、`key_metrics: list[str] = []`。`rationale` 保留(= summary 或拼接,向后兼容)。runner 的 `_build_signal` 映射新字段;非法/缺失仍降级为 None(永不抛,沿用现状)。

## 四、错误处理

- Judge 输出缺字段/类型错 → `_build_signal` 返回 None → signal 步 FAILED、无信号(现状)。
- summary/strengths/risks/key_metrics 缺省安全([] / "")。
- 后端报错/429 → 现有 try/except 不变。

## 五、测试

- **单测(真实录制夹具 + Fake 后端)**:`test_prompts.py`(evidence_text 含四组+来源+missing、schema 严格且 required 全覆盖、角色 prompt 含反幻觉规则);`test_workflow_runner.py`(FakeBackend 返回结构化 judge → Signal 带 strengths/risks/key_metrics)。
- **强制真实闸门** `test_gate_real.py::test_gate_real_pipeline`:真实多源 + 真实 DeepSeek,断言 `final_signal.recommended is not None`、`summary` 非空、`strengths`/`risks`/`key_metrics` 至少各 1 条。
- **真实验证(交付)**:实跑过闸活币 → 输出完整报告(引用真实 gmgn 数字)。

## 六、验收

1. 审计三阶段都收到完整 Facts(四组)+ 来源标注。
2. Judge 返回 recommended + summary + strengths[] + risks[] + key_metrics[](引用具体数字)。
3. Missing 字段被显式标注,模型不编造。
4. 真实数据下闸门通过,run 记录含完整报告。
