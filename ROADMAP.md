# 🗺️ ROADMAP.md — 产品路线图
> **当前日期**: 2026-11-14
> **当前阶段**: 🟢 **估值完整性重构 (Phase 1/2/3/4) 完成 + 内部标准 Taxonomy 五维公司拆解 (Session #23) 完成 + 三源 sector/industry 补全链 & bottom-up β 唤醒 (Session #24) 完成 + Bottom-up β 三级业务身份筛选接入 CAPM (Session #25 / M-34) 完成 + 分部收入数据层 & Segment-level β (Session #26 / M-31+M-35) 完成 + M-35 收尾：FMP 多 key / `/stable` 端点 / Shape C / 关键词表补全 (Session #27 / M-36) 完成 + 商业理解层六模块映射 + 四态决策契约 + Identity Resolution (Session #28 / M-37) 完成 + SEC 10-K/20-F filing-instance XBRL 业务证据抽取 & 四态决策端到端测试 (Session #29 / M-38) 完成 + SEC filing-instance XBRL 生产化接入 providers 主链 (Session #30 / M-39) 完成 + Taxonomy 参与路由（跨族冲突才覆盖 + 经济护栏）(Session #30 / M-32) 完成 + 50 只跨行业蓝筹全量验证 & Reverse DCF 递归自我改进 3 轮 (Session #31–#33) 完成**（另有一条分类器数据轨：2g 待人工标注 BLOCKER）
> **总体进度**: 约 84% (距 v1.0.0 发布)

---

## 🧪 50 只跨行业蓝筹全量验证 + Reverse DCF 递归自我改进 3 轮 (2026-11-14，Session #31–#33)

> 触发：用户给出 50 只跨行业蓝筹（NVDA/MSFT/AVGO/…/PLD/O/AMT/VICI），要求验证「① 行业分类准确性 ② 模型分配正确性 ③ 不同行业估值方法正确性 ④ 特殊情况（盈利·亏损·高增长·高负债·负 FCF）鲁棒性 ⑤ Reverse DCF 市场隐含预期合理性」，并执行 **3 轮递归自我改进**——每轮产出作为下一轮起点来定位缺陷、修码、重跑。
> 方法：`_batch_eval.py`（50 标的离线全量审计 → JSON）+ `_audit_summary.py`（紧凑五问）为**可断言产出**；每轮「评估产出 → 定位缺陷 → 修码 → 重跑」。
> 总纪律：**绝不伪造**（不合理的点估改为诚实 bound / 命名约束，绝不伪造点估）；**数据驱动而非调阈**（每处阈值变更都由真实样例证据驱动）。

```
Session #31–#33  ✅  50 标的全量验证 + Reverse DCF 递归自我改进 3 轮   [✅ DONE]

【Round 1 · Session #31】结构化 bound
  ├─ models/reverse_dcf.py::calculate：市场价超出业务类型 sanctioned growth band 时输出
  │   implied_revenue_cagr_bound={kind, value, ev_at_bound}
  │   （above_band_ceiling→「≥ 上限」/ below_band_floor→「≤ 下限」）
  ├─ normalized 救援仅在 bridge_broken 时启用（不作为「凑出 band 内数字」手段）
  └─ 新建审计 harness：_batch_eval.py（50 标的 → JSON）+ _audit_summary.py（五问摘要）

【Round 2 · Session #32】报告双处渲染口径统一 + 初版 σ 门
  ├─ 缺陷 #1：_implied_section（有 bound）vs _gap_section（N/A）自相矛盾（PG）
  │   → ExpectationGap +implied_revenue_cagr_bound/is_bound + 透传 + _gap_section 镜像
  ├─ 缺陷 #2（初版）：growth_vol 绝对 σ 门（消除 CV 假 High 的一半）
  └─ _batch_eval.py 增记 risk flags / _audit_summary.py 增 Q4b 风险底线；新建 _diag_risk.py / _audit_risk_detail.py

【Round 3 · Session #33】下行离散度 + Rf 下限（本轨收尾）
  ├─ 缺陷 #3：σ 门不足（SO σ≈10.5pp 恰越阈；PLD/VICI 单调收购爬坡被当波动）
  │   → _growth_risk() 改 下行离散度 dd=RMS(min(growth,0))（growth_dd_medium=0.05 / high=0.10）
  ├─ 缺陷 #4：隐含 WACC 反解出 sub-Rf（DUK 2.3%/SO 2.7%/CEG 3.3% = 负风险溢价）
  │   → dcf._estimate_wacc_breakdown() 暴露 Rf 单一真理源 + reverse_dcf 以 Rf 为 implied-WACC 下限
  │     （连 Rf 都够不到 → NO_SOLUTION_IN_RANGE + implied_wacc_floor_rf 命名约束）
  └─ golden 二次有意重生成（差异全部为 Growth Risk 移除/降级，逐条核对）

验证：pytest 429/429；_batch_eval.py round3 → 50/50 = 100.0% | routing_viol=0 | defects=0
     Reverse DCF：量化 22 / bound-only 19 / 未量化 0；implied_wacc < Rf = 0 例

待跟进（非本次范围）：
  ├─ 部分标的隐含 FCF 利润率 / 隐含终值增长率仍 NO_SOLUTION_IN_RANGE → 可给 bound 措辞（M-40）
  ├─ FMP 在线分部需 key（M-35 精度跟进）
  └─ M-16 / C-02（真实标注 → 90%+ 准确率）仍为唯一真实 BLOCKER

---

## 🧭 Taxonomy 参与路由 + Filing 证据生产化轨道 (2026-11-14，Session #30 / M-32 + M-39)

> 触发：用户两阶段要求 —— ① 把 M-38 的 `filing_evidence` 从「可用入口」变「生产默认路径」（FMP 缺 key / 失效 / 额度耗尽 / ticker 未覆盖时自动回退 SEC filing-instance XBRL），且**不触碰 golden 基线**（仍 shadow 数据填充）；② 再做 M-32（taxonomy 从 shadow 层切换为**参与路由**）。
> 口径（用户三次明确）：M-32 切换 = **CONFIRMED + 尊重经济特征护栏**；golden = **不重生成、保持零漂移**；gating = **跨族冲突才覆盖 + 护栏**。
> 关键设计纠错：M-32 gate 必须对比**内部身份判定 `best_bt`**，而**不是** `routing_bt`（后者是 Phase 1.3 ambiguous 时的「保守估值路由」，GOOGL 会被重路由为 `TELECOM`）——若对比 `routing_bt`，`TELECOM` 与 `tech.internet(MatureTech)` 跨族 → GOOGL 被误覆盖、golden 漂移。
> 原则：**绝不伪造**（两层皆空 → `[]`；gate 不通过 → 保留内部路由）；**跨族才覆盖**（同族差异如 `MatureTech` vs `SaaS` 同属 `tech` 族 → 不覆盖，归经济驱动分类器所有）；**经济护栏优先**（claim 资产轻却重资本建设 → 拒绝）；**零重生成**（结构性排除 18 只 basket 的漂移风险）。

```
Session #30  ✅  M-39：SEC filing-instance XBRL 生产化 + M-32：Taxonomy 参与路由   [✅ DONE]

【阶段 A · M-39】filing_evidence 接入 providers 主链（生产默认源链）
  ├─ data/segment_revenue.py::resolve_segments(ticker)：Layer 1 FMP revenue-product-segmentation（需 key）
  │   → Layer 2 SEC 10-K/20-F filing-instance XBRL（免 key、权威，惰性 import 避免与 filing_evidence 循环）
  │   → 两层皆空 → []（绝不伪造）
  ├─ data/providers.py：改调 resolve_segments(ticker) → FMP 无 key / 失效 / 额度耗尽 / 未覆盖 → 自动降级 SEC 一手分部
  └─ 仍为 shadow 数据填充（不改 business_type / 路由）→ golden 零漂移

【阶段 B · M-32】taxonomy 从 shadow 层切换为参与路由（跨族冲突才覆盖 + 经济护栏）
  ├─ classification/taxonomy.py：taxonomy_routing_override(内部身份, canonical_key, decision_status, guard_blocked)
  │   三道 gating：① decision_status ∈ TAXONOMY_ROUTING_STATUSES（={CONFIRMED}）
  │              ② canonical 身份与内部身份判定 best_bt 跨 identity family 冲突（同族差异不覆盖）
  │              ③ guard_blocked=True（claim 资产轻却 capex/营收≥1.0 且负 FCF）→ 拒绝
  ├─ ARCHETYPE_FAMILIES（由 IDENTITY_NODES 树推导，archetype↔node tree 不漂移）+ same_identity_family()
  ├─ classification/classifier.py + ml_classifier.py：routing 前构建 _taxonomy，gate 通过 → _routed_business_type=_tax_bt
  │   （ML 路径对比 best_bt；economics = raw ML top-1 而非 sector 硬规则后标签）
  ├─ attach_taxonomy_profile(..., tp=_taxonomy)：复用同一 profile，避免重复构建
  └─ tests/test_taxonomy.py：TestTaxonomyRoutingGate 12 用例 + tension basket（ORCL/NBIS/CRWV → tax=tech.software.infra 但 business_type=MatureTech）

验证：pytest 413 → 429 passed；golden 指纹零漂移（未重生成）；改动模块/新测试 Ruff clean

待跟进（非本次范围）:
  ├─ 分部 label → 行业映射（`_SEGMENT_INDUSTRY_KEYWORDS`，M-35 精度）随语料补全
  ├─ M-33 GICS / NAICS 外部标签补齐
  └─ M-16 / C-02：hybrid 阈值复评 + 人工标注重训 → 分类准确率 90%+（唯一真实 BLOCKER）
```

---

## 📑 一手 Filing 证据轨道 — SEC 10-K / 20-F filing-instance XBRL 业务证据抽取 (2026-11-14，Session #29 / M-38)

> 触发：承接 Session #28 收尾时诚实记录的真实缺口「10-K / 20-F XBRL 业务抽取未做」，用户确认推进 **M-38** 并补 **四态决策端到端测试**。
> 关键实测纠错：SEC `companyfacts` JSON **不含 dimensional（axis/member）数据**（计数为 0）→ 取一手分部必须解析 **filing-instance XBRL**（10-K/20-F 内嵌 `*_htm.xml` 实例文档）。
> 原则：**绝不伪造**（无 CIK / 无实例 / 解析失败 / malformed XML → `[]`；`offline` 零网络）；**drop-in 兼容**（返回既有 `segment_revenue.Segment` + `source="sec-xbrl"`，零扰动接入 `to_revenue_composition`/taxonomy ③）。

```
Session #29  ✅  M-38：SEC 10-K/20-F filing-instance XBRL 业务证据抽取          [✅ DONE]
  ├─ data/filing_evidence.py（新建）：FilingRef + FilingBusinessExtractor
  │   CIK → submissions/CIK{cik}.json（filings.recent newest-first）→ 首个 10-K/20-F
  │   → filing index.json 优选 *_htm.xml 实例（排除 r\d+.xml / *_cal|def|lab|pre|ref.xml）
  ├─ parse_segment_revenue(xml) 纯函数：
  │   xbrli:context → (endDate, axis, member)；仅取带 segment 轴的事实（排除合并总额）
  │   单轴 _AXIS_PRIORITY（StatementBusinessSegments > ProductOrService > ifrs Segments > Geographical）
  │   取最新期间；忽略 instant context；us-gaap + ifrs-full revenue concept
  ├─ get_segments() → segment_revenue.Segment + source="sec-xbrl"（drop-in 兼容 to_revenue_composition）
  ├─ _MEM + .cache/filing_evidence.json 磁盘缓存；offline 零网络；绝不伪造（→ []）
  ├─ tests/test_filing_evidence.py（新建，9 用例）
  │   + tests/test_taxonomy.py::TestDecisionContractEndToEnd（6 用例，真实 builder/classifier 全链路）
  └─ pytest 398 → 413；Ruff clean（改动模块/新测试）；golden 零漂移

待跟进（本次范围外）:
  ├─ ✅ filing_evidence.get_segments() 接入 data/providers.py 主链（FMP 缺 key 时自动回退）→ Session #30 / M-39 已交付
  ├─ ✅ M-32 Taxonomy / 四态决策参与路由 → Session #30 已交付（跨族冲突才覆盖 + 护栏）
  ├─ 分部 label → 行业映射（`_SEGMENT_INDUSTRY_KEYWORDS`，M-35 精度）随语料补全
  └─ M-33 GICS / NAICS 外部标签补齐
```

---

## 🧠 商业理解层轨道 — 六模块映射 + 四态决策契约 + Identity Resolution (2026-11-14，Session #28 / M-37)

> 触发：用户提交《最终确定的五维分类体系》提案，要求把项目正式化为 **Universal Business Taxonomy & Intelligence Engine**（商业理解层），并给出六模块划分（`identity_resolver` / `industry_taxonomy` / `business_intelligence` / `classification_resolver` / `economic_profile` / `peer_selection`；ML 保留独立 `ml_classifier.py`）。
> 差距分析：提案约 **70% 已落地**（五维 Taxonomy / 三源数据链 / bottom-up β 三级筛选 + Segment-level β / Valuation Router）；真实缺口三处：① 无 Identity Resolution 层（CIK/SIC/FIGI）；② 无 Business Evidence 收集器；③ 分类裁决缺「能否据此行动」四态契约。
> 形态：**不重组、原位扩展**（既有逻辑零迁移、缺失模块新建、新模块仅做薄封装）→ 既得 6 模块表面，又保 import 与 golden 基线。
> 原则（用户明确要求的三条架构原则）：① 不允许单一数据源直接覆盖内部分类；② 不允许 ML 错误分类直接影响 WACC/估值；③ 不允许缺收入证据的公司被强赋高置信度。均以「绝不伪造 + shadow 接线 + 门控」落地。

```
Session #28  ✅  商业理解层（Business Intelligence Layer）                    [✅ DONE]
  ├─ classification/taxonomy.py：DecisionStatus（CONFIRMED/PROBABLE/AMBIGUOUS/INSUFFICIENT_DATA）
  │   + decide_status() 确定性映射 + _ECONOMICS_ONLY_MIN_CONF=0.55 + _DECISION_LABELS
  │   + BusinessTaxonomyProfile.decision_status → CompanyProfile.taxonomy_decision_status（shadow）
  ├─ data/identity_resolver.py（新建）：IdentityResolver/ResolvedIdentity（CIK/SIC/FIGI）
  │   Layer A 复用在位 SEC 链（SectorIndustryResolver.resolve_identity()）+ Layer B OpenFIGI（需 key）
  ├─ classification/business_intelligence.py（新建）：extract_business_evidence() → 业务描述 + 分部收入 + provenance
  ├─ data/industry_resolver.py：+ resolve_identity()（供 identity_resolver 复用 CIK，避免重复抓取）
  ├─ data/models.py：CompanyProfile + taxonomy_decision_status（additive shadow）
  ├─ 六模块映射（原位扩展）：industry_taxonomy / classification_resolver / economic_profile / peer_selection
  ├─ tests：TestDecisionContract(7) + test_identity_resolver(5) + test_business_intelligence(4)
  └─ pytest 382 → 398；golden 零漂移；新模块/新测试 Ruff clean

待跟进（本次范围外）:
  ├─ M-37 ✅ 已交付；M-38 10-K/20-F XBRL 业务抽取 → Session #29 已交付
  ├─ ✅ M-32 Taxonomy / 四态决策参与路由 → Session #30 已交付（跨族冲突才覆盖 + 护栏）
  └─ classification_resolver / economic_profile / peer_selection 仍为「点位」非独立文件（如需物理拆分须单独审阅）
```

---

## 🎯 折现率精化轨道（续）— M-35 收尾：FMP 多 key / `/stable` 端点 / 关键词表数据驱动补全 (2026-11-14，Session #27 / M-36)

> 触发：用户在 `.env` 中配置了**两个逗号分隔的 `FMP_API_KEY`**，并要求「分部→行业关键词表数据驱动补全」。检查发现原 `segment_revenue.py` 把整串 `key1,key2` 当单一 key 使用 → 请求必然 403；且 FMP 在 2025-08-31 后停用了全部 `/api/v3`、`/api/v4` 遗留端点（实测返回 `403 "Legacy Endpoint"`），仅 `/stable/...` 可用。
> 关键实测纠错：`/stable/revenue-product-segmentation` 返回**元数据外层包裹嵌套 `data` 字典**（Shape C：`[{"symbol","fiscalYear","period","date","data":{segment: revenue}}]`）——不识别会把 `fiscalYear`/`period` 误当分部名污染 β 权重。
> 原则：**绝不伪造**（无 key / 无法解析 → `[]`，绝不猜测）；**多 key 透明轮换**（非 200 即落到下一把）；**映射只增不改**（保 golden 零漂移）；**桶 / 地理 / 品牌名 / 缩写恒不映射**（`Other`/`Corporate`/`All Other`/`…and Eliminations`、`Latin America (Segment)`、`Botox`/`RINVOQ`、`GMI`/`GMNA` → 丢弃优先）。

```
Session #27  ✅  M-35 收尾（多 key / /stable / Shape C / 关键词表补全）   [✅ DONE]
  ├─ data/segment_revenue.py：_fmp_keys() 逗号分隔多 key；_from_fmp 按序轮换（非 200/不可解析→下一把，全耗尽→[]）
  ├─ 端点优先级：_from_fmp_stable → _from_fmp_v4 → _from_fmp_v3（v4/v3 保留但已知 403「Legacy Endpoint」）
  ├─ _extract_fmp()：新增 Shape C 分支（识别 first["data"] 为 dict），杜绝 fiscalYear/period 元数据污染
  ├─ data/industry_beta.py：_SEGMENT_INDUSTRY_KEYWORDS 两轮数据驱动补全（只增不改；桶/地理/品牌名/缩写恒不映射）
  ├─ _discover_segment_labels.py：90 只多业务大票 → 真实 segment label 语料（172 distinct / 107 covered / 65 uncovered）
  ├─ tests/test_segment_revenue.py + test_industry_beta.py：+6 用例（多 key 轮换 / Shape C / 真实语料映射 / 负向断言）
  └─ pytest 376 → 382；golden 零漂移；新模块/新测试 Ruff clean

待跟进（非本次范围）:
  ├─ 残余 65 uncovered 中约 39 个属「桶 / 地理 / 品牌名 / 缩写」→ **恒不映射**，不得强补
  ├─ 其余为发行人专属 / 歧义词 → 可由 `python _discover_segment_labels.py` 增量迭代，人工审阅后再入库
  └─ Segment-level β 在线生效依赖 FMP key；离线 golden 无分部数据 → 透明回退公司级 β（设计如此）
```

---

## 🎯 折现率精化轨道（续）— 分部收入数据层 + Segment-level β (2026-11-14，Session #26 / M-31 + M-35)

> 触发：用户要求落地 **M-35 Segment-level β（最高优先级）**——多业务公司（BRK-B / GE / AMZN）按分部 β × 业务价值权重整合，是公司级 bottom-up β 的最大剩余误差源；确认范围「M-31 + M-35 全链」+ 映射口径「分部标签→行业→bottom-up」+ 权重口径「按业务价值/盈利权重」。
> 关键前提纠错：**SEC `companyfacts` JSON 不含分部（dimensional）数据**（AAPL `Axis`/`ProductOrService`/`StatementBusinessSegments` 计数均为 0）→ M-31 以 **FMP `/revenue-product-segmentation` 为主源**。
> 原则：**绝不伪造**（无 key/无法解析 → `[]`/`None`）；**透明回退**（分部 <2 或覆盖 <60% → 回退公司级 β）；**接线为 add**（golden 离线无分部数据 → 零漂移）。

```
Session #26  ✅  分部收入数据层 (M-31) + Segment-level β (M-35)   [✅ DONE]
  ├─ data/segment_revenue.py：FMP 分部收入（v4 flat / v3 legacy）→ Segment[]；类级 _MEM + 磁盘缓存
  ├─ to_revenue_composition()（→ taxonomy ③ RevenueComposition）+ segment_weights(by="value")（营业利润优先，回退收入）
  ├─ derive_segment_level_beta()：分部 label→行业（~65 关键词）→ 复用 M-34 三级筛选求 β_u → 加权整合 → cash-adjust → relever
  ├─ level=0 / source="segment-weighted" / IndustryBetaResult.segments 审计；门控 min_segments=2 + 覆盖 ≥60%
  ├─ derive_bottom_up_beta(segments=...) 优先分支（不足则透明回退公司级）；FinancialData +revenue_composition；providers 接线
  └─ +23 用例；pytest 353 → 376；golden 零漂移；新模块/新测试 Ruff clean

待跟进（非本次范围）:
  ├─ M-31 需配置 FMP_API_KEY 才有在线分部数据（无 key → 回退公司级 β）
  ├─ 分部→行业关键词表可随分部 label 语料驱动补全
  └─ SEC 一手分部（若需要）：整包 Financial Statement Data Sets 或 filing-instance XBRL（勿再试 companyfacts）
```

---

## 🎯 折现率精化轨道 — Bottom-up β 三级业务身份筛选 + 完整 β 链接入 CAPM (2026-11-14，Session #25 / M-34)

> 触发：用户要求「先升级 bottom-up β 再做 M-34」——裸 `get_companies_by_industry(industry)` 会把异质同业（fabless vs 重资产代工）混入中位。原则：**绝不伪造**（无同业→L3 快照，未覆盖/缺失→None；无 bottom-up→回退回归 β）；**保持单一 β 出口**（`resolve_effective_beta()`，ADR-019）；**接线为 add**（golden 离线 `bottom_up_beta=None` → 零漂移）。

```
Session #25  ✅  Bottom-up β 升级「业务身份三级筛选 + 完整 β 链」接入 CAPM   [✅ DONE]
  ├─ get_companies_by_business_identity(sub_industry, business_model, economic_profile) 替换裸 industry 筛选
  ├─ 三级筛选：L1 同子行业+商业模式 → L2 相邻行业+相似经济特征 → L3 Damodaran 行业基准
  ├─ 完整链：Peer Levered → Unlevered(Hamada) → Median → Cash-adjusted → Target Relevered
  ├─ L3 数据：data/damodaran_beta.json（Jan 2026，100 行业，未覆盖→None，绝不伪造）
  ├─ wacc.py::calculate() 三段优先级（bottom-up 优先 / 缺失回退回归 β / 都无则 default）；clamped 语义修正
  ├─ MarketData +bottom_up_beta / +bottom_up_beta_chain；providers 接线
  └─ +20 用例；pytest 333 → 353；golden 零漂移；新模块/新测试 Ruff clean

待跟进（非本次范围）:
  └─ M-35 Segment-level β（多业务公司按分部 β + 业务价值权重整合；依赖 M-31 分部数据）
```

---

## 🔌 数据源补全轨道 — 三源 sector/industry 链 + bottom-up β (2026-11-14，Session #24 / H-03)

> 触发：Yahoo `quoteSummary/assetProfile` 长期 401（约 83%）→ `sector/industry` 大面积为 `None` → 分类器行业硬规则（+3.0）整体失效、ML 文本特征丢失最强信号，准确率被钉在 ~75%。原则：**绝不伪造**（缺失返回 `{}`/`None`）；**SIC→Yahoo 桥接必须「可消费」**（产出 industry 必须能被下游硬规则消费）；**优雅降级**（外部库 optional import）；**接线为 add**（不改 CAPM / taxonomy 仍 shadow）。

```
Session #24  ✅  三源 sector/industry 补全链 + bottom-up β 唤醒   [✅ DONE]
  ├─ data/sic_map.py：SEC SIC → Yahoo 桥接（~180 精确 4 位 + ~68 类 + ~130 关键词，具体→宽泛）
  ├─ data/industry_resolver.py：SectorIndustryResolver = FinanceDatabase → SEC EDGAR(SIC) → Wikidata(P452)
  ├─ data/industry_beta.py：动态同业无杠杆 β（Hamada，t=0.21，取中位，<3 家 → None）
  ├─ data/providers.py 接线（填充 industry_beta）+ classifier.py 补 "asset management" 硬规则
  ├─ 三源测试 45 用例（离线 monkeypatch）；pytest 288 → 333；golden 零漂移；Ruff clean
  └─ 在线实测：SEC 层 10/10 精确；硬规则命中率 75% → 78.3%；Semis bottom-up β_u = 1.2447

待跟进（非本次范围）:
  ├─ M-16 阈值数据驱动复评（特征缺口已补）+ C-02 真实标注重训 → 目标 90%+
  ├─ M-31 ③ Revenue Composition 复用 SEC 通道取分部收入
  ├─ M-33 基于 SEC SIC 推导 NAICS（GICS 需 FMP）
  └─ M-34 bottom-up β 升级为 CAPM 输入（须先审阅收敛差异）
```

---

## 🏛️ 内部标准 Taxonomy 五维拆解轨道 (2026-11-14，Session #23)

> 触发：原分类依赖 Yahoo industry 与 ML 标签的临时冲突规则，无标准树、口径分散、易被财务经济特征误导。原则：**分离「公司做什么」与「经济特征」；economics 只能族内细化 identity，严禁跨族决定（黄金法则）；外部标签原样保留不覆盖内部判断；先 shadow 接入零漂移，再单独提审参与路由**。

```
Session #23  ✅  内部标准 Taxonomy + 五维公司拆解   [✅ DONE]
  ├─ classification/taxonomy.py：99 节点 canonical 树（点分 key + parent + archetype；depth 由 parent 链推导）
  ├─ 五维：① Business Identity ② Business Model ③ Revenue Composition ④ Economic Profile ⑤ External Classification
  ├─ 黄金法则：economic_identity_ceiling()（跨族不提升 / 同族兄弟收敛 common ancestor）+ ConflictKind 五档
  ├─ node_from_yahoo() 两段式 longest-key-wins（industry 优先 → sector → 兜底；修复 AMZN/KR 误判）
  ├─ additive shadow 接线（CompanyProfile 8 字段；不改 business_type/路由 → golden 零漂移）
  └─ tests/test_taxonomy.py 48 用例；pytest 288/288；新增文件 Ruff clean

待跟进（非本次范围）:
  ├─ M-31 ③ Revenue Composition 接入真实分部收入源（SEC XBRL / FMP / Alpha Vantage）→ Session #26 M-31 + Session #30 M-39 已交付
  ├─ ✅ M-32 taxonomy 切换为「参与路由」→ Session #30 已交付（跨族冲突才覆盖 + 护栏）
  └─ M-33 外部标签补齐 GICS / NAICS
```

---

## 🔧 估值完整性重构轨道 (2026-11-13，并行于 Phase 2g 分类数据轨)

> 触发：MSFT 测试报告暴露「模型严重分歧时系统仍给出虚假高一致性」等缺陷。原则：**不整引擎重写，先审计再分阶段修改；保留已修行为；不硬编码单公司规则；不伪造假设**。

```
Phase 1  🔴 P0  一致性/风险/分类   [✅ DONE]
  ├─ 报告百分比方向自审 (reporting/math_audit.py)
  ├─ 模型分歧诊断 (analysis/divergence.py) — IQR 排除核心模型须降一致性等级
  ├─ 风险等级底线 (Risk Floor) — 任一维度 High 直接提升整体等级
  └─ 分类引擎 Business Identity vs Economics 分离 (classification/classifier.py)

Phase 1.5 ✅  规范化估值阶梯 + base-anchored 百分比用词 (pct_vs/phrase_vs) + 报告数学自审

Phase 2  🟠 P1  预测/MC/情景   [✅ DONE — Session #20]
  ├─ MC 双模式 base_case / historical（ADR-034）
  ├─ 路径形参化锚点对账：零扰动锚点 = 确定性 DCF（MSFT/AAPL/NBIS +0.0%）
  ├─ 去除人为 +2% 利润率地板，允许负利润率，边界可配置
  ├─ 经营情景 vs 折现率情景拆分（ADR-035）
  └─ 报告透明化：模式/种子/请求/有效/无效/截断/分布/相关矩阵 + Wipeout 用词

Phase 3  🟠 P1  WACC/Peer/去重   [✅ DONE — Session #21]
  ├─ WACC Beta 多窗口 (2Y Weekly / 3Y Monthly / 5Y Monthly) + bottom-up beta 槽位（ADR-036）
  ├─ Peer Multiples fallback 标签 (EXACT_INDUSTRY/SECTOR_FALLBACK/BUSINESS_TYPE_FALLBACK/APPROXIMATE) + n_peers
  └─ model_family 同源证据去重（覆盖率门控按独立证据数计票，ADR-037）

Phase 4  ✅  全量回归与验收   [✅ DONE — Session #22]
  ├─ 回归域 9 → 18 只（AAPL/MSFT/GOOGL/AMZN/NVDA/AVGO/ORCL/NBIS/CRWV/UPS/KR/BAC/PLD/NU/JPM/XOM…，7 类 archetype；invariants 全空）
  ├─ golden 指纹 +5 字段（原始解算 / IQR 排除 / 参与聚合）+ invariant 2b（核心模型被 IQR 排除却强一致性 → 缺陷）
  ├─ 边界/验收用例（`tests/test_phase4_integrity.py` 9 用例锚定 10 条验收标准）
  └─ Ruff clean；pytest 240/240；golden 基线重生成（原 9 只无漂移）；Pyright 未安装
```

---

## 🎯 愿景 (Vision)
> 一个 **可审计、可解释、跨市场** 的股票估值助手，通过 Telegram 提供服务，  
> 将机构级 DCF/WACC 方法论带到个人投资者指尖，  
> 且商业模式分类准确率 ≥ 95%，避免致命模型错配。

---

## 阶段总览 (Timeline & Milestones)

```
Phase 1  规划设计      2026-09     [✅ 100%]
  ├─ 模块划分: 9个目录 (data/valuation/...)
  ├─ 数据契约定义: FinancialData / CompanyProfile Dataclass
  └─ 硬约束明确: WACC7步 / TVG约束 / 缓存4h

Phase 2  核心开发      2026-09     [✅ 95%]
  2a ─ 数据层: YahooProvider + TreasuryProvider + 合成fallback
  2b ─ 估值底层: WACC7步 + TVG约束 + DCF/ReverseDCF/NAV/Bank/SOTP/Multiples
  2c ─ 分析层: 敏感性矩阵 + 风险/情景/一致性
  2d ─ 分类器: 确定性85% → LightGBM合成版98%(train)
  2e ─ 接口: main.py统一入口 + Telegram Bot集成
  2f ─ ⭐ **1001行特征收集** ⭐ ← 我们现在在这里 (刚完成)
               ↓↓↓ [BLOCKER: 人工标注 label 列] ↓↓↓
  2g ─ ⚠️ 真实模型训练 + AB测试对比

Phase 3  测试与质量   2026-10~11   [⬜ ~10%]
  3a ─ pytest 覆盖率: 45% → 80%
  3b ─ 回归测试集: 30只 ticker × 3市场环境 (bull/bear/sideway)
  3c ─ 端到端演示: Telegram端 ←→ 估值报告格式严格校验
  3d ─ 边界case: 负盈利银行 / 刚IPO无3年数据 / 仙股市值<1亿

Phase 4  生产部署     2026-11~12   [⬜ 0%]
  4a ─ Render / Cloudflare Workers 部署 (参考 user_profile 偏好)
  4b ─ Watchlist SQLite 持久化 (peewee 已安装)
  4c ─ 监控: Yahoo API成功率 / 响应延迟 / 用户限流
  4d ─ 告警: 估值偏离内在价值±20%主动推送

Phase 5  扩展与运营   2027-Q1+     [⬜ 0%]
  5a ─ 双市场: 港股 0700.HK / A股 600519.SS
  5b ─ Dashboard PNG 图表报告 → Telegram 内联
  5c ─ 导出到 Google Sheets (用户偏好)
  5d ─ 社区功能: 用户共享估值 / 讨论区链接

v1.0.0 公开发布      2026-12+
```

---

## ✅ Phase 1 — 规划设计 (DONE ✅)
| 任务 | 状态 | 产出 |
|------|------|------|
| 1.1 定义 BusinessType 11类分类体系 | ✅ | config.py BusinessType 枚举 |
| 1.2 定义 FinancialData 数据契约 | ✅ | data/models.py 10+ dataclass |
| 1.3 明确 WACC7步 / TVG三重约束 硬约束 | ✅ | DECISIONS.md ADR-001/002 |
| 1.4 模块划分与职责边界 | ✅ | 9 个包 + 清晰 import 依赖图 |
| 1.5 技术栈锁定: Python3.13 + httpx + LightGBM + TG | ✅ | .venv 环境就绪 |

**关键风险已处理**:
- 数据缺失时仍能估值 → SyntheticDataProvider 兜底

---

## 🟡 Phase 2 — 核心开发 (2f 完成, 等待 2g)

### 2a 数据层 ✅
- Yahoo Finance Chart + Fundamentals 双端点异步抓取 (semaphore=8)
- Treasury.gov Yield Curve CSV (带完整浏览器 headers 防403)
- `.cache/{yahoo_finance,treasury_yield}` 4h TTL 原子 JSON 缓存
- 失败率: 实测 <1%，synthetic fallback 兜底

### 2b 估值底层 ✅
- **WACC 7步法**: 从 Rf(10Y) → CapStructure 完整可溯
- **TVG 约束**: min(企业, 名义GDP, WACC-0.5%) 三档情景 Base/Low/High
- 6 种估值模型: DCF (2阶段) / Reverse DCF / NAV / Bank DDM / SOTP / Multiples

### 2c 分析层 ✅
- WACC×g 敏感性矩阵 (25 cell) + Base单元格高亮 + 稳定性4档分级
- Scenario 三档情景: Low/Base/High 驱动整个估值链
- Risk 因子 + Model Agreement (多模型一致性)

### 2d 分类器 ✅
- 确定性规则 BusinessClassifier (~85%): 11 类规则 + 适用性裁决
- LightGBM 合成版: 15数值 + TFIDF(χ² K=60) → Train Acc ~98%
- 混合架构 MLHybridClassifier: Top1 Prob≥40%用ML，否则回退规则
- 结构覆盖4类强规则: Bank / REIT / Semi / Util → ≥99% 准

### 2e 接口 ✅
- `main.py`: 6 个子命令 (bot/demo/demo_fast/test_demo/test/help)
- Telegram Bot: `/value /value_fast /wacc /classify /models`

### 2f ⭐ 1001 行真实特征收集 ✅ (2026-10-05)
| 指标 | 数值 |
|------|------|
| 总行数 | **1001** (去重后) |
| 15数值特征完整率 | 100% |
| company_name 完整率 | 100% |
| sector/industry 完整率 | 171/1001 (约17%) |
| synthetic 填充占比 | <1% (note 列可见) |
| 总耗时 | ~1.4 min (并发8 + 缓存) |

### 2g ⚠️ 等待: 真实训练 + AB 测试 (BLOCKER)
**输入依赖**: C-02 人工标注完成 (见 TODO.md)

完成后 1 天内可完成:
```
[ ] 修改 ml_classifier.py L705: 1行替换
[ ] 删除 3 个旧 .pkl 文件
[ ] python main.py demo AAPL 触发重训 (~10-30s)
[ ] 记录 train_meta_v2.pkl 准确率
[ ] _ab_classifier_compare.py 输出混淆矩阵: det / syn / real 三版对比
```

---

## ⬜ Phase 3 — 测试与质量
**目标日期**: 2026-10~11 (2-3 周)

### 3a pytest 覆盖率 45% → 80%
| 模块 | 当前 | 目标 | 重点测试内容 |
|------|------|------|--------------|
| classification/ml_classifier.py | 中 | ✅ | CSV→训练→预测链路；边界label处理；结构覆盖 4 类数值强规则各 3 case |
| valuation/wacc.py | 低 | ✅ | 7步每步单独失败回退；Sanity Check 阈值；与手动计算 AAPL/WFC 对账 |
| models/router.py | 低 | ✅ | 11 BusinessType × 适用模型映射表锁死；Bank/REIT 不会错分到 DCF-growth |
| sensitivity.py | 中 | ✅ | 矩阵尺寸；Base单元格坐标；Highly Sensitive阈值触发 |

### 3b 30 只回归测试集 (固定黄金样本)
```
MatureTech: AAPL MSFT ORCL
SaaS:       NOW CRWD DDOG
Semi:       NVDA AVGO TSM ASML AMD
ConsCycl:   TSLA AMZN HD BKNG
REIT:       AMT PLD EQIX PSA O
Bank:       JPM BAC WFC C GS MS
Insurance:  BRK-B PGR TRV MET
Commodity:  XOM CVX FCX NUE BHP
Utilities:  NEE DUK SO D AEP
Conglomerate: BRK-B GE HON CAT BA
Unknown:    SPCE RIVN LCID HOOD
```
→ 每只都有 "预期分类/预期模型/预期估值区间上下界" 锁死

### 3c 端到端格式校验
- Telegram Markdown V2 特殊字符转义 (`. - ( ) + = ! ~ > # | { }`)
- 报告段落顺序: 摘要 → 分类 → WACC拆解 → 估值表 → 敏感性 → 建议

### 3d 边界 case
| Case | 预期行为 |
|------|----------|
| 近期 IPO 无 3 年数据 | 回退到 Multiples + 警告 "历史数据不足" |
| 银行负净收入 (金融危机模拟) | Bank 模型自动切到 P/B 估值 |
| 仙股 (market cap < $50M) | 明确提示 "流动性风险极高，估值不可靠" |
| 高增长 SaaS (负盈利但高 FCF) | 仍可 DCF，注意 TVG 钳制不会发散 |

---

## ⬜ Phase 4 — 生产部署
**目标日期**: 2026-11~12

### 4a 云部署
- **Webhook Mode**: Render Web Service + Webhook 回调 (比长轮询更省)
- **Telegram Bot Token** 通过环境变量注入 (已在 .env 模板)
- **Secret Webhook Path**: 防止伪造请求

### 4b 数据持久化
- **SQLite + peewee** (项目已预装) 3 张表:
  - `valuations(id, ticker, timestamp, result_json, user_id)`
  - `watchlists(user_id, tickers_json)`
  - `daily_close(ticker, date, close)` 每日收盘快照
- 可选迁移到 **Supabase PostgreSQL** (user_profile 偏好)

### 4c 监控
- Yahoo 端点成功率 P95 > 98% (当前 99%+)
- 平均响应: /value_fast < 10s；/value < 20s
- 用户级限流: 20 req/day (可管理员调)

### 4d Watchlist 主动推送
- 每日收盘后拉取
- 价格 < Base 估值 80% → **Undervalued** 推送 + 理由
- 价格 > Base 估值 120% → **Overvalued** 推送 + 风险提示

---

## ⬜ Phase 5 — 扩展与运营
**目标日期**: 2027-Q1+

### 5a 双市场支持
| 市场 | 数据源 | 注意 |
|------|--------|------|
| 美股 (US) | Yahoo Finance ✅ | 当前已完美 |
| 港股 (.HK) | 东方财富 / Yahoo `.HK` 后缀 | WACC 切换 HKMA 基本利率 / 恒生 ERP |
| A股 (.SS/SZ) | 东方财富原生API | 汇率考虑; ERP 使用中证债券收益率 |

### 5b 图表报告
- Matplotlib/Seaborn 生成 PNG (无需浏览器)
- 内含: WACC 瀑布图 + 估值分布条形 + 敏感性热力图 (Base 十字准星高亮)

### 5c Google Sheets 导出
- 参考用户偏好 (user_profile: 熟悉 Google Sheets/Drive API)
- `/export_sheet` 命令: 最近 30 天估值写到指定 Sheet

### 5d 运营
- 每季度回测: Top10 低估组合 vs S&P 500 → 业绩基准证明
- 用户标注反馈闭环: 用户"分类错误"一键报告 → 训练集增量修正

---

## 🎯 关键 KPI 追踪
| KPI | 目标 | 当前 | 测法 |
|-----|------|------|------|
| 分类准确率 (11类) | ≥ 95% | ~85% (规则) | 30 只回归集人工对账 |
| Bank/REIT/Semi/Util 分类 | ≥ 99% | ~98% | 结构强规则已接近 |
| 单 ticker 估值耗时 (缓存命中) | < 2s | ~1.2s ✅ | main.py demo_fast 10 次平均 |
| 单 ticker 估值耗时 (冷) | < 10s | ~7s ✅ | 删除 cache 后测 |
| 用户报告 "明显错误估值" | < 2% | N/A | 部署后统计 |
| Telegram 报告格式错误 | 0 | N/A | Markdown V2 转义严格测试 |

---

## ⚠️ 已知风险与缓释
| # | 风险 | 概率 | 影响 | 缓释策略 |
|---|------|------|------|----------|
| R1 | Yahoo API 大规模封号 | 中 | 高 | 引入 Alpha Vantage / FMP 二级数据源 (DECISIONS P-001) |
| R2 | 人工标注质量差 (错误率>10%) | 高 | 中 | 标注后跑一致性校验: 规则/人工冲突行人工再审; 允许 Unknown 占比≤5% |
| R3 | 真实训练准确率未达 95% (≤90%) | 中 | 中 | 引入 M-02 季度变化特征 / M-03 ETF 相关特征 再训练 |
| R4 | Telegram 封禁 Bot (Spam 误报) | 低 | 高 | 使用官方推荐 webhook 模式; 单用户 rate limit 严格 |
| R5 | 用户输入非美股代码崩溃 | 中 | 低 | 已在 Provider 层做了 synthetic fallback; 加友好提示 "市场暂未支持" |

---

## 🚀 接下来 7 天可执行清单
1. **Day 1-2**: 人工标注 1001 行 label 列 (BLOCKER)
2. **Day 3**: 切换训练源 → 重训 LightGBM → 记录 train_acc
3. **Day 4**: `_ab_classifier_compare.py` 三版对比，输出混淆矩阵 + F1
4. **Day 5-6**: 扩充 pytest (classification/ml_classifier / valuation/wacc / models/router 3 个模块先冲 80%)
5. **Day 7**: 30 只回归集黄金标注 + 端到端格式校验

→ 完成后进入 Phase 4 部署准备 🎉
