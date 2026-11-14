# 📝 CHANGELOG.md — 版本变更记录
> 格式: [语义化版本 vX.Y.Z] - YYYY-MM-DD  (或 Session 编号用于未发布)
> 分类: ✨ Added / 🔧 Changed / 🐛 Fixed / 🗑️ Removed / ⚠️ Deprecated / 🔒 Security

---

## [Unreleased] — 2026-11-14 (Session #31–#33 — 50 只跨行业蓝筹全量验证 + Reverse DCF 递归自我改进 3 轮)

> 触发：用户给出 50 只跨行业蓝筹清单，要求验证「行业分类准确性 / 模型分配正确性 / 不同行业估值方法正确性 / 特殊情况（盈利·亏损·高增长·高负债·负 FCF）鲁棒性 / Reverse DCF 市场隐含预期合理性」，并明确执行 **3 轮递归自我改进**——每轮产出作为下一轮起点来定位缺陷、修码、重跑。
> 方法：`_batch_eval.py`（50 标的离线全量审计 → `_batch_eval_roundN.json`）+ `_audit_summary.py`（紧凑五问摘要）为**可断言产出**；每轮「评估产出 → 定位缺陷 → 修码 → `python -m pytest` → 重跑」。
> 总纪律：**绝不伪造**（不合理的点估改为诚实 bound / 命名约束）；**数据驱动而非调阈**（每处阈值变更都由真实样例证据驱动）。
> 验证：pytest **429/429 passed**；`_batch_eval.py round3` → `50/50 = 100.0% | routing_viol=0 | defects=0`；`implied_wacc < 0.045` 计数 = **0**。

### ✨ Added
- ✨ **结构化 bound（`models/reverse_dcf.py`，Round 1）**：市场价超出业务类型 **sanctioned growth band** 时输出 `implied_revenue_cagr_bound={kind, value, ev_at_bound}`（`above_band_ceiling`→「≥ 上限」/`below_band_floor`→「≤ 下限」），用「市场已 price-in 的最小/最大增速 + 边界 EV」诚实表达区间，而非伪造 band 内点估；normalized 救援仅在 **bridge_broken** 时启用
- ✨ **`ExpectationGap` bound 字段（`analysis/expectation.py`，Round 2）**：新增 `implied_revenue_cagr_bound` / `implied_revenue_cagr_is_bound` 并透传，使 `_implied_section`（implied 区）与 `_gap_section`（市场预期缺口区）共享同一数据源
- ✨ **`_estimate_wacc_breakdown()`（`models/dcf.py`，Round 3）**：暴露 WACC **实际使用的** Rf（`WaccBreakdown.risk_free_rate`），作为「隐含 WACC 下限」的**单一真理源**，避免反向 DCF 自行重解 Rf 而与报告 WACC 悄悄分叉
- ✨ **审计工具**：`_batch_eval.py`（Round 1）/ `_audit_summary.py`（Round 1）/ `_diag_risk.py`（Round 2）/ `_audit_risk_detail.py`（Round 2）

### 🔧 Changed
- 🔧 **`analysis/expectation.py` + `reporting/dashboard.py`（Round 2）**：`_gap_section` 镜像 bound 措辞 → 同一标的（如 PG）不再出现「一区 ≥ 上限 / 一区 N/A」的自相矛盾
- 🔧 **`analysis/risk.py::_growth_risk()`（Round 3）**：从「总离散度 σ + CV」改为**下行离散度** `dd=RMS(min(growth,0))`——CV 在 μ→0 时爆炸（受管制公用事业 SO：μ≈0.9%、σ≈10.5pp → CV≈11.9 误报 High）；总 σ 把单调收购爬坡（PLD 6.0→8.8bn、VICI 2.6→4.0bn）当波动风险。下行离散度只保留「营收收缩的幅度与频率」
- 🔧 **`config.py`（Round 3）**：`RISK_THRESHOLDS[RiskType.GROWTH]` 阈值改为 `growth_dd_medium=0.05` / `growth_dd_high=0.10`
- 🔧 **`models/reverse_dcf.py`（Round 3）**：`calculate()` 解析并透传 `risk_free_rate`；`_implied_expectations()` 的隐含 WACC 求解以 Rf 为下限（`wacc_lo = max(cfg, tg+spread, Rf)`），目标 EV 连 Rf 都够不到 → `NO_SOLUTION_IN_RANGE` 且把下限写进 `implied_wacc_floor_rf`（**命名约束，不伪造**）
- 🔧 **`tests/golden/report_fingerprints.json`**：因 Growth Risk 行为修正二次重生成（差异**全部为 Growth Risk 移除/降级**，无任何新增旗标）

### 🐛 Fixed
- 🐛 **Round 1**：市场价超出 sanctioned growth band 时的伪点估（改为结构化 bound + 诚实区间）
- 🐛 **Round 2**：同一「市场隐含预期」在报告两处渲染口径不一致（`_implied_section` 有 bound、`_gap_section` 显示 N/A）
- 🐛 **Round 3**：Growth Risk 因 `CV=σ/|μ|` 在 μ→0 爆炸而误报 High（SO 等受管制公用事业）+ 单调收购爬坡被 σ 误判为波动风险（PLD/VICI/CEG/AMT）
- 🐛 **Round 3**：隐含 WACC 反解出 **低于无风险利率**的值（DUK 2.3% / SO 2.7% / CEG 3.3%，等价于「负风险溢价」）→ 以 Rf 为下限，sub-Rf → `NO_SOLUTION_IN_RANGE`

### 📊 Baseline Verification (Session #31–#33)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **429/429 passed** | 无回归 |
| 50 标的审计 | ✅ `50/50 = 100.0%` | `routing_viol=0 | defects=0` |
| Reverse DCF | ✅ 量化 22 / bound-only 19 / 未量化 0 | 每只标的均给出点估或诚实 bound |
| implied_wacc < Rf | ✅ **0** 例 | Rf 下限生效 |
| golden 回归 | ⚠️ **二次有意重生成** | 差异全部为 Growth Risk 移除/降级（逐条核对为行为修正） |

### ⚠️ Known Issues (Session #31–#33)
- ① **部分标的隐含 FCF 利润率 / 隐含终值增长率仍为 `NO_SOLUTION_IN_RANGE`**：可给 bound 措辞（与 Round 1 一致的处理方式），后续跟进
- ② **FMP 在线分部需 key**：无 key 时放分部级 β 回退公司级（M-35 精度）
- ③ **M-16 / C-02（真实标注 → 90%+ 准确率）仍为唯一真实 BLOCKER**：分类准确率瓶颈已从「数据源」转为「真值粒度」，需人工标注驱动

---

## [Unreleased] — 2026-11-14 (Session #30 — M-39：SEC filing-instance XBRL 生产化接入 providers 主链 + M-32：Taxonomy 参与路由)

> 触发：用户两阶段要求 —— ① 把 M-38 的 `filing_evidence` 从「可用入口」变「生产默认路径」（FMP 缺 key / 失效 / 额度耗尽 / ticker 未覆盖时自动回退 SEC filing-instance XBRL），且**不触碰 golden 基线**；② 再做 M-32（taxonomy 从 shadow 层切换为**参与路由**）。
> 口径（用户三次明确）：M-32 切换 = **CONFIRMED + 尊重经济特征护栏**；golden = **不重生成、保持零漂移**；gating = **跨族冲突才覆盖 + 护栏**。
> 关键设计纠错：M-32 gate 必须对比**内部身份判定 `best_bt`**，而非 `routing_bt`（后者是 Phase 1.3 ambiguous 的「保守估值路由」，GOOGL 会被重路由为 `TELECOM`）——对比 `routing_bt` 会让 `TELECOM` 与 `tech.internet(MatureTech)` 跨族而误覆盖 GOOGL。
> 原则：**绝不伪造**（两层皆空 → `[]`；gate 不通过 → 保留内部路由）；**跨族才覆盖**（同族差异如 `MatureTech` vs `SaaS` 同属 `tech` 族 → 不覆盖）；**经济护栏优先**；**零重生成**。
> 验证：pytest **413 → 429 passed**；golden 指纹**零漂移**（未重生成）；改动模块/新测试 Ruff clean。

### ✨ Added
- ✨ **生产默认源链（`data/segment_revenue.py::resolve_segments`，M-39）**：`resolve_segments(ticker, *, client, offline, fmp_cache_path, filing_cache_path, identity_resolver)`——**Layer 1** FMP `revenue-product-segmentation`（需 key）→ **Layer 2** SEC 10-K/20-F filing-instance XBRL（免 key、权威，`FilingBusinessExtractor` 惰性 import 以避免与 `filing_evidence` 循环）；两层皆空 → `[]`（绝不伪造）
- ✨ **Taxonomy 参与路由 gate（`classification/taxonomy.py`，M-32）**：`TAXONOMY_ROUTING_STATUSES = frozenset({DecisionStatus.CONFIRMED})` + `ARCHETYPE_FAMILIES`（由 `IDENTITY_NODES` 树推导，`archetype↔node tree` 不漂移）+ `same_identity_family(internal_bt, taxonomy_key)` + `taxonomy_routing_override(internal_bt, taxonomy_key, decision_status, *, guard_blocked=False)`（三道 gating：CONFIRMED / **跨 identity family 冲突** / 经济护栏）
- ✨ **`attach_taxonomy_profile(..., tp=...)`**：允许调用方复用已构建的 `BusinessTaxonomyProfile`（M-32 需在模型路由**前**构建 taxonomy 以喂 `taxonomy_routing_override`）
- ✨ **测试**：`tests/test_taxonomy.py` 新增 `TestTaxonomyRoutingGate`（12 用例：同族不覆盖 / 跨族覆盖 / 非 CONFIRMED 不覆盖 / 护栏拒绝 / UNKNOWN 不覆盖 / 与 `routing_bt` 无关等）+ tension basket 用例（ORCL/NBIS/CRWV：`taxonomy_identity_key == "tech.software.infra"` 但 `business_type == "MatureTech"`）

### 🔧 Changed
- 🔧 **`data/providers.py`**：分部收入采集改调 `resolve_segments(ticker)` → FMP 无 key / key 失效 / 额度耗尽 / ticker 未被覆盖时**自动降级**到 SEC 一手分部（仍为 shadow 数据填充，不改 `business_type` / 路由）
- 🔧 **`classification/classifier.py`**：规则路径在 `_model_applicability()` **之前**构建 `_taxonomy` 并调用 `taxonomy_routing_override(best_bt, ...)`；gate 通过 → `routing_bt = _tax_bt` 且 `business_type=_routed_business_type.value`；新增 `_asset_light_guard_blocked()` staticmethod（复用 `ASSET_LIGHT_TYPES` + `ASSET_LIGHT_CONFLICT_CAPEX_RATIO` 阈值）；`attach_taxonomy_profile(data, profile, tp=_taxonomy)` 复用同一 profile
- 🔧 **`classification/ml_classifier.py`**：ML 路径对称接入（`taxonomy_routing_override as _taxonomy_routing_override`；economics 用 **raw ML top-1**（预 sector 硬规则）以保留统计/原型冲突信号；对比 `best_bt`）

### 📊 Baseline Verification (Session #30)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **429/429 passed** | 413 → 429（+16：M-32 gate 12 + tension basket 等） |
| taxonomy 分步 | ✅ 通过 | `tests/test_taxonomy.py`（含 `TestTaxonomyRoutingGate`） |
| golden 回归 | ✅ **零漂移（未重生成）** | 同族差异不覆盖 → ORCL/NBIS/CRWV 保持 `MatureTech`；`UPDATE_GOLDEN` 未执行 |
| Ruff | ✅ 改动模块/新测试 clean | `taxonomy.py` / `classifier.py` / `ml_classifier.py` / `segment_revenue.py` / `providers.py` |

### ⚠️ Known Issues (Session #30)
- ① **`_SEGMENT_INDUSTRY_KEYWORDS` 覆盖仍有限（107/172）**：filing-instance XBRL 产出的原始分部 label 尚未喂关键词表（M-35 精度）→ 未映射 label 交由公司级 β **透明回退**（M-35 precision 跟进）
- ② **M-33 GICS / NAICS 仍缺**：⑤ External Classification 仅 Yahoo sector/industry + SEC SIC + ML 标签
- ③ **分类准确率 78.3% 未达 90%**：唯一真实 BLOCKER 为 M-16 / C-02（hybrid 阈值复评 + 人工标注 1001 行重训），非数据源问题

---

## [Unreleased] — 2026-11-14 (Session #29 — M-38：SEC 10-K / 20-F filing-instance XBRL 业务证据抽取 + 四态决策端到端测试)

> 触发：承接 Session #28 收尾时诚实记录的真实缺口「10-K / 20-F XBRL 业务抽取未做」，用户确认同时推进 **M-38（SEC filing-instance XBRL 业务证据抽取）** 与 **四态决策端到端测试**。
> 关键实测纠错：SEC `companyfacts` JSON **不含 dimensional（axis/member）数据**（计数为 0）→ 取一手分部必须解析 **filing-instance XBRL**（10-K/20-F 内嵌 `*_htm.xml` 实例文档）。
> 原则：**绝不伪造**（无 CIK / 无实例 / 解析失败 / malformed XML → `[]`；`offline` 零网络）；**drop-in 兼容**（返回既有 `segment_revenue.Segment` + `source="sec-xbrl"`，零扰动接入 `to_revenue_composition`/taxonomy ③）；**四态端到端**（用真实 builder/classifier 锁定 shadow 接线）。
> 验证：pytest **398 → 413 passed**；改动模块/新测试 Ruff clean；golden 指纹**零漂移**。

### ✨ Added
- ✨ **SEC filing-instance XBRL 业务证据抽取（`data/filing_evidence.py`，新建）**：`FilingRef`（`cik`/`form`/`accession`/`filing_date`/`primary_document` + `accession_nodash`/`index_url`）+ `FilingBusinessExtractor`——`latest_filing(ticker)` 走 CIK → `data.sec.gov/submissions/CIK{cik}.json` 的 `filings.recent`（newest first）→ 首个 `10-K`/`20-F`；`_instance_url()` 走 filing `index.json` 优选 `*_htm.xml` 实例（`_pick_instance` 排除 `r\d+.xml` 与 `*_cal|def|lab|pre|ref.xml`）；`get_segments(ticker)` 先 `_MEM` → 磁盘缓存 → `_resolve` → 写缓存
- ✨ **`parse_segment_revenue(xml_text) -> List[(label, revenue)]`（纯函数）**：`_parse_contexts` 解析 `xbrli:context` → `(endDate, axis, member)`（`xbrldi:explicitMember@dimension` 识别 segment 轴）；**仅取带 segment 轴的事实**（`_REVENUE_LOCALS` = us-gaap `Revenues`/`RevenueFromContractWithCustomerExcludingAssessedTax`/`SalesRevenueNet`… + ifrs-full `Revenue`/`RevenueFromContractsWithCustomers`，用于 20-F）；按 `_AXIS_PRIORITY`（`StatementBusinessSegmentsAxis` > `ProductOrServiceAxis` > ifrs `SegmentsAxis` > `StatementGeographicalAxis`）**取单一轴**聚合；**排除合并总额**；**取最新期间**；**instant context 一律忽略**
- ✨ **测试**：`tests/test_filing_evidence.py`（新建，9 用例：分部解析且排除合并总额 / 取最新期间 / business 轴优先于地理 / instant 忽略 / malformed+empty / latest_filing 选年报 / 端到端 `to_revenue_composition` 占比和=1.0 / 未解析不伪造 / offline 零调用）+ `tests/test_taxonomy.py::TestDecisionContractEndToEnd`（6 用例：真实 `build_taxonomy_profile`/`attach_taxonomy_profile`/ML 标签全链路）

### 🔧 Changed
- 🔧 **`tests/test_taxonomy.py`**：import 新增 `attach_taxonomy_profile`/`build_taxonomy_profile`；文件末尾追加 `TestDecisionContractEndToEnd`（6 用例）——把 Session #28 的四态 shadow 接线从「单元级」升级为「真实 builder/classifier 全链路」断言（NVDA/MSFT/JPM/PLD 多原型状态合法）

### 📊 Baseline Verification (Session #29)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **413/413 passed** | 398 → 413（+15：filing_evidence 9 + 端到端 6） |
| filing XBRL 分步 | ✅ **9 passed** | `tests/test_filing_evidence.py` |
| taxonomy 分步 | ✅ **61 passed** | `tests/test_taxonomy.py`（含新增 6 端到端） |
| golden 回归 | ✅ 零漂移 | 新数据层未接入主链；不改 `business_type`/路由 |
| Ruff | ✅ 改动模块/新测试 clean | `data/filing_evidence.py` / 两个测试文件 |

### ⚠️ Known Issues (Session #29)
- ① **`filing_evidence.get_segments()` 尚未在主链自动接线**：~~当前为 drop-in 独立入口（可手动喂 `to_revenue_composition`），未在 `data/providers.py` 自动调用、也未在 FMP 缺 key 时自动回退（TODO 跟进）~~ → ✅ **Session #30 / M-39 已解决**：`resolve_segments()` 源链（FMP → SEC filing-instance XBRL）+ `providers.py` 接线，FMP 缺 key/失效时自动回退
- ② **SEC `companyfacts` 仍不可用**：无 dimensional 数据；如需全量历史分部须整包 Financial Statement Data Sets（勿再试 `companyfacts`）
- ③ **分部 label → 行业映射未接入**：`parse_segment_revenue` 产出的原始 label 尚未喂 `_SEGMENT_INDUSTRY_KEYWORDS`（M-35 精度），需随语料补全（Session #30 仍为待跟进）
- ④ **taxonomy / 四态仍为 shadow**：~~参与路由（M-32）待 golden 有意漂移逐字段审阅~~ → ✅ **Session #30 / M-32 已解决**：`taxonomy_routing_override()` 跨族冲突才覆盖 + 经济护栏，**零重生成 golden**

---

## [Unreleased] — 2026-11-14 (Session #28 — 商业理解层（Business Intelligence Layer）：六模块映射 + 四态决策契约 + Identity Resolution)

> 触发：用户提交《最终确定的五维分类体系》提案，要求把项目正式化为 **Universal Business Taxonomy & Intelligence Engine**（商业理解层），并给出六模块划分（`identity_resolver` / `industry_taxonomy` / `business_intelligence` / `classification_resolver` / `economic_profile` / `peer_selection`）。用户决策：范围＝按 6 模块重构；命名＝保留现名、正式化「商业理解层」；形态＝**不重组、原位扩展**。
> 差距分析：提案约 **70% 已落地**（五维 Taxonomy / 三源数据链 / bottom-up β 三级筛选 + Segment-level β / Valuation Router 均已存在）。真实缺口三处：① 无 Identity Resolution 层（CIK/SIC/FIGI）；② 无 Business Evidence 收集器；③ 分类裁决缺「能否据此行动」的四态契约。
> 原则：**绝不伪造**（缺失标识一律 None）；**原位扩展**（既有逻辑零迁移、六模块表面齐备）；**additive shadow**（四态为审计字段，不改路由 → golden 零漂移）。
> 验证：pytest **382 → 398 passed**；golden 指纹**零漂移**。

### ✨ Added
- ✨ **四态决策契约 `DecisionStatus`（`classification/taxonomy.py`）**：把「信号如何相关」（`ConflictKind`）与「能否据此行动」（`DecisionStatus`）分离——`CONFIRMED` / `PROBABLE` / `AMBIGUOUS` / `INSUFFICIENT_DATA`；新增确定性映射函数 `decide_status(conflict_kind, identity_source, *, ml_confidence)`（无标的特例）+ 常量 `_ECONOMICS_ONLY_MIN_CONF=0.55` + 中文标签 `_DECISION_LABELS`
- ✨ **Identity Resolution 层（`data/identity_resolver.py`，新建）**：`IdentityResolver.resolve(ticker) → ResolvedIdentity`（`cik`/`sic`/`sic_description`/`figi`/`sector`/`industry` + `sources` + `provenance()`）——Layer A 复用在位 SEC 链（经 `SectorIndustryResolver.resolve_identity()`），Layer B OpenFIGI（`OPENFIGI_API_KEY` 存在才调用，`offline` 跳过）；缺失字段**一律 None，绝不伪造**；模块级便捷入口 `resolve_identity(ticker, *, offline=False)`
- ✨ **Business Evidence 收集器（`classification/business_intelligence.py`，新建）**：`extract_business_evidence(data, *, description=None) → BusinessEvidence`（业务描述 + 分部收入 `(label, pct)` + 各自 `*_source` + `provenance()`）；证据缺失**显式标注为缺失**（`notes`），使下游可诚实输出「数据不足」；来源＝provider 业务描述（`MarketData.description`）+ `FinancialData.revenue_composition`（M-31）
- ✨ **测试**：`tests/test_identity_resolver.py`（5 用例：SEC 供 CIK / 未解析不伪造 / OpenFIGI 仅有 key 时使用 / offline 跳过 / 空 ticker）/ `tests/test_business_intelligence.py`（4 用例）/ `tests/test_taxonomy.py::TestDecisionContract`（7 用例，锁定五档 ConflictKind → 四态映射）

### 🔧 Changed
- 🔧 **`classification/taxonomy.py`**：`BusinessTaxonomyProfile` +`decision_status` 字段；`audit_lines()` 追加「◆ 决策状态」行；`build_taxonomy_profile()` 计算并传入 `decision_status`；`attach_taxonomy_profile()` 写 `profile.taxonomy_decision_status`
- 🔧 **`data/industry_resolver.py`**：新增 `resolve_identity(ticker)` 公共方法（返回 `cik`/`sic`/`sic_description`/`sector`/`industry`/`source` 子集，缺失字段省略不猜测）→ 供 `identity_resolver.py` 复用，避免重复抓取
- 🔧 **`data/models.py`**：`CompanyProfile` +`taxonomy_decision_status`（位于 `taxonomy_conflict_kind` 与 `taxonomy_audit` 之间，纯 additive shadow）

### 📊 Baseline Verification (Session #28)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **398/398 passed** | 382 → 398（+16，含决策契约 7 / identity 5 / evidence 4） |
| 分步验证 | ✅ **64 passed** | `test_taxonomy.py` + `test_identity_resolver.py` + `test_business_intelligence.py` |
| golden 回归 | ✅ 零漂移 | 四态为 shadow 字段；不改 `business_type`/`applicable_models`/路由 |
| Identity（离线） | ✅ 缺失即 None | 无 `OPENFIGI_API_KEY` → FIGI 恒 None（不伪造） |
| Ruff | ✅ 改动模块/测试 clean | — |

### ⚠️ Known Issues (Session #28)
- ① **四态决策契约仍为 shadow 字段**：已写入 `CompanyProfile` 但不参与路由（与 M-32 taxonomy 路由切换同一取舍：待 golden 有意漂移逐字段审阅）
- ② **OpenFIGI 需 `OPENFIGI_API_KEY` 方生效**：无 key → FIGI 恒 `None`（诚实缺省）
- ③ **10-K / 20-F XBRL 业务抽取未做**：本次仅提供 `BusinessEvidence` 收集器；SEC `companyfacts` 无 dimensional 数据，如需一手分部须整包 Financial Statement Data Sets / filing-instance XBRL
- ④ **`classification_resolver.py` / `economic_profile.py` / `peer_selection.py` 为「点位」非独立文件**（原位扩展的代价）；如需物理拆分须单独审阅

---

## [Unreleased] — 2026-11-14 (Session #27 — FMP 多 key 轮换 + `/stable` 新端点 + Shape C 解析 + 分部→行业关键词表数据驱动补全)

> 触发：用户提供**两个 FMP API Key**（写入 `.env`：`FMP_API_KEY=key1,key2`）并要求「**分部→行业关键词表数据驱动补全**」（M-35 收尾迭代）。
> 关键实测纠错：**FMP `/api/v4/...` 与 `/api/v3/...` 遗留端点自 2025-08-31 起返回 403 `Legacy Endpoint`**（仅遗留订阅可用）→ 分部收入须改用 **`/stable/revenue-product-segmentation`**；其响应为**新的 Shape C**（元数据外层包裹嵌套 `data` 混合字典），旧的 Shape A/B 解析会把 `fiscalYear`/`period` 误当分部。
> 原则：**绝不伪造**（无 key / 全部 key 耗尽 → `[]`）；**多 key 透明轮换**（限速/失效自动落到下一个 key）；**关键词表只增不改、非分部/地理/品牌名/缩写恒不映射**（丢弃优先，绝不猜测）。
> 验证：pytest **376 → 382 passed**；关键词表覆盖真实语料 **102 → 107 / 172 distinct labels**；golden 指纹**零漂移**。

### ✨ Added
- ✨ **FMP 多 key 轮换（`data/segment_revenue.py::_fmp_keys` + `_from_fmp`）**：`FMP_API_KEY` 支持逗号分隔多 key（自动 strip 空白），**按序尝试**，某 key 返回非 200 或不可解析时透明落到下一个；全部耗尽 → `[]`（绝不伪造）
- ✨ **`/stable` 新端点为首层**：端点为 `https://financialmodelingprep.com/stable/revenue-product-segmentation`；层优先序改为 **`_from_fmp_stable` → `_from_fmp_v4` → `_from_fmp_v3`**（三层统一走多 key `_from_fmp`）
- ✨ **Shape C 解析（`_extract_fmp`）**：识别 `[{...,"fiscalYear":...,"period":"FY","date":...,"data":{...}}]` 新形状——只把嵌套 `data` 里的 label→数值当分部，`date` 作 `as_of`，**元数据（`fiscalYear`/`period`/`symbol`）绝不泄漏为分部**
- ✨ **测试（`tests/test_segment_revenue.py`）**：新增 Shape C 用例（含 `"fiscalYear" not in labels` 元数据防泄漏断言）、`/stable` 端点优先用例、多 key 轮换/空白 strip/全部耗尽三方用例

### 🔧 Changed
- 🔧 **`data/industry_beta.py::_SEGMENT_INDUSTRY_KEYWORDS`（M-35 数据驱动补全）**：以真实 FMP 分部语料（90 只多业务大票 → 41 只成功解析 → 172 distinct label）为驱动，两轮扩充——
  - **Round 1**：~40 条业务线词（`aeronautics`/`commercial airplanes`/`biopharma`/`medtech`/`upstream`/`downstream`/`midstream`/`foundry`/`client computing`/`wealth`/`broadband`/`youtube`/`linkedin`/`windows`/`theme park`/`online stores`/`apparel`/`footwear` …）
  - **Round 2**：~6 条残余可复用业务线词（`space`→Aerospace & Defense、`print and publishing`/`publishing`→Publishing、`data processing`→Information Technology Services、`energy products`→Oil & Gas Refining & Marketing、`digital experience`→Software - Application）
  - **恒不映射（丢弃优先）**：非分部桶（`Other`/`Corporate`/`…and Eliminations`/XBRL reconciling）、地理区域（`Africa, Middle East and South Asia`/`Latin America (Segment)`）、发行人专属药品品牌名（`Botox`/`RINVOQ`/`SKYRIZI` …）、发行人缩写（`GMI`/`GMNA`）
- 🔧 **测试（`tests/test_industry_beta.py`）**：`test_default_segment_resolver_real_corpus_additions` 增 Round 2 锁定断言 + 品牌名/缩写「恒不映射」负向断言

### 📊 Baseline Verification (Session #27)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **382/382 passed** | 376 → 382（+6，含 Shape C / 多 key / 端点优先） |
| golden 回归 | ✅ 零漂移 | 关键词表只增不改；离线解析路径不变 |
| 关键词表覆盖 | ✅ **102 → 107 / 172** labels | 数据驱动；余 65 为桶/地理/品牌名/缩写（须保持不映射） |
| FMP 端点 | ✅ `/stable` 200（两 key）| `/api/v4`、`/api/v3` → 403 Legacy Endpoint（2025-08-31 起停用） |
| 多 key 轮换 | ✅ 首 key 失效 → 次 key 接续 | `test_multi_key_rotation_*` |
| Ruff | ✅ 改动模块/测试 clean | — |

### ⚠️ Known Issues (Session #27)
- ① **`/stable` 响应形状为 Shape C**：新增分支已识别并加「元数据不泄漏」断言；若 FMP 再改形状需同步 `_extract_fmp`
- ② **`FMP_API_KEY` 需落盘 `.env`**：仅在编辑器缓冲区输入而未保存（`Ctrl+S`）时，`dotenv` 读不到 → 运行期回退 `[]`
- ③ **关键词表覆盖存在上限**：残余 65 个未映射 label 中约 39 个（桶/地理/品牌名/缩写）**必须保持不映射**；其余为发行人专属/歧义词，交由公司级 β 透明回退（对单业务发行人即为正确结果）

---

## [Unreleased] — 2026-11-14 (Session #26 — 分部收入数据层 (M-31) + Segment-level β (M-35)：多业务公司按业务价值权重整合分部 β)

> 触发：用户要求落地 **M-35 Segment-level β（优先级最高）**——多业务公司（如 BRK-B / GE / AMZN）按分部 β × 业务价值权重整合，是当前 bottom-up β 的最大剩余误差源；并确认「**M-31 + M-35 全链**」范围 + 「**分部标签→行业→bottom-up**」映射口径 + 「**按业务价值/盈利权重**」加权口径。
> 关键前提纠错：**SEC `companyfacts` JSON 不含分部（dimensional）数据**（实测 AAPL `Axis`/`ProductOrService`/`StatementBusinessSegments` 计数均为 0）→ M-31 以 **FMP `/revenue-product-segmentation` 为主源**，SEC 层明确排除。
> 原则：**绝不伪造**（无 key / 无法解析 → `[]` / `None`，不填猜测值）；**透明回退**（分部不足 2 个或覆盖权重 < 60% → 回退公司级 β）；**接线为 add**（golden 离线无分部数据 → 走旧路径，**零漂移**）。
> 验证：pytest **353 → 376 passed**（+23）；golden 指纹**零漂移**；新模块/新测试 Ruff clean。

### ✨ Added
- ✨ **`data/segment_revenue.py`（新模块，M-31）**：分部收入数据层。`Segment`（frozen：`label`/`revenue`/`operating_income`/`as_of`/`source`）；`SegmentRevenueResolver`（类级 `_MEM` + `.cache/segment_revenue.json` 磁盘缓存；`get_segments`/`batch_get`；层 `_from_fmp_v4`（v4 flat）/`_from_fmp_v3`（legacy）**需 `FMP_API_KEY`，无 key → `[]`**）；`to_revenue_composition(segments)`（按收入占比归一为 taxonomy `RevenueComposition`，空 → `unavailable()`）；`segment_weights(segments, by="value")`（**业务价值优先**：所有可用分部均有 `operating_income>0` 时按营业利润加权，否则回退收入加权，返回归一到 1.0 的 `[(label, weight)]`）
- ✨ **`derive_segment_level_beta(...)`（`data/industry_beta.py`，M-35）**：逐分部 `label` → 行业（`_default_segment_industry_resolver` 经 `_SEGMENT_INDUSTRY_KEYWORDS` ~65 条关键词匹配，具体优先）→ 复用 M-34 三级筛选链求分部 β_u → 按覆盖子集重归一权重加权求和 → `_cash_adjust` → target-relever；`level=0` / `source="segment-weighted"` / `IndustryBetaResult.segments`（逐分部 `label`/`industry`/`weight`/`beta_unlevered`/`level`/`source` 审计）；**门控** `min_segments=2` + `_MIN_SEGMENT_COVERAGE=0.60`（不足 → `None` → 调用方保留公司级 β）
- ✨ **`IndustryBetaResult.segments` + `note()`/`to_chain()` 扩展**：新增 `segments` 字段；`note()` 增 `level 0 →「分部加权 (Segment-level)」` 映射 + 分部明细文本；`to_chain()` 增 `"segments"` 键
- ✨ **`FinancialData.revenue_composition`（`data/models.py`，M-31 消费端契约）**：`Optional[Any] = None`（用 `Any` 避免 data→classification 循环 import；taxonomy 缺失时视为显式 `unavailable`，离线/golden 安全）
- ✨ **23 新用例**：`tests/test_segment_revenue.py`（11：两种 FMP shape 解析 / 无 key 不发请求 / 非正与空 label 丢弃 / 磁盘持久化 + 离线复放 / `to_revenue_composition` 归一与空值 / 权重业务价值优先 + 收入回退 + 无可用返回 `[]`）；`tests/test_industry_beta.py`（+12 M-35：分部权重×β_u 求和 / 审计明细 + chain 键 / 覆盖子集重归一 / cash-adjust + relever / `min_segments` 与 `min_coverage` 门控返回 None / offline 返回 None / `derive_bottom_up_beta(segments=...)` 优先分支 / 分部不足回退公司级 / 默认关键词 resolver / `_coerce_segments` 形状 / `BOTTOM_UP_BETA=0` 关闭）

### 🔧 Changed
- 🔧 **`derive_bottom_up_beta(...)`（M-35 接入）**：新增 `segments` / `segment_industry_resolver` / `segment_cash_to_firm` / `segment_beta_provider` 形参；顶部守卫后**优先尝试分部链**（成功即返回 `level=0` 结果），否则走原公司级三级筛选链（**透明回退，零漂移**）
- 🔧 **`data/providers.py`（M-31/M-35 接线）**：bottom-up β 块新增——`SegmentRevenueResolver().get_segments(ticker)` → `to_revenue_composition(...)`（落 `FinancialData.revenue_composition`）+ `segment_weights(...)`（`_cash_to_firm = cash_eq/(mkt_cap+debt)`）→ `derive_bottom_up_beta(..., segments=..., segment_cash_to_firm=...)`；无分部数据时 `segments=None` → 回退公司级
- 🔧 **`classification/taxonomy.py`（M-31 消费端）**：`build_taxonomy_profile` 在 `revenue_composition is None` 时改为读取 `getattr(data, "revenue_composition", None) or RevenueComposition.unavailable()`（此前恒 `unavailable`）
- 🔧 **`tests/test_segment_revenue.py` 隔离**：新增 autouse fixture 清 `SegmentRevenueResolver._MEM` + `FMP_API_KEY`（类级缓存跨用例泄漏 → 断言失败）

### 📊 Baseline Verification (Session #26)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **376/376 passed** | 353 → 376（+23） |
| golden 回归 | ✅ 零漂移 | 离线无分部数据 → `segments=None` → 回退公司级 β |
| 分部加权数学 | ✅ 权重×β_u 求和 + 覆盖子集重归一 | `test_segment_weights_sum_beta_unlevered` 等 |
| 门控 | ✅ `<2 分部` / `覆盖 <60%` → None | `test_segment_returns_none_below_*` |
| SEC 前提核实 | ✅ companyfacts 无分部数据 | 实测 AAPL dimensional 计数 = 0 |
| Ruff | ✅ 新模块/新测试 clean | — |

### ⚠️ Known Issues (Session #26)
- ① **M-31 依赖 `FMP_API_KEY`**：无 key → `[]`（分部数据缺省，回退公司级 β）；FMP 分部接口为付费/限流端点，需配置 key 才有在线分部数据
- ② **分部→行业为关键词映射**：`_SEGMENT_INDUSTRY_KEYWORDS` 为启发式（~65 条），冷门/自定义分部 label 未覆盖 → 丢弃（不猜测）；后续可由 M-31 的分部 label 语料驱动补全
- ③ **SEC 分部数据未接入**：companyfacts 无 dimensional 数据；如需 SEC 一手分部，需整包 Financial Statement Data Sets 或 filing-instance XBRL 解析（本会话已明确排除，见 ADR-042）

---

## [Unreleased] — 2026-11-14 (Session #25 — Bottom-up β 升级「业务身份三级筛选 + 完整 β 链」接入 CAPM，M-34)

> 触发：用户要求**先升级 bottom-up β 再做 M-34**——不再用 `get_companies_by_industry(industry)`，改用 `get_companies_by_business_identity(sub_industry, business_model, economic_profile)` 的**三级筛选**（L1 同子行业+商业模式 / L2 相邻行业+相似经济特征 / L3 Damodaran 基准），并计算完整链：**Peer Levered → Peer Unlevered → Median → Cash-adjusted → Target Relevered**，让 WACC 更贴近真实商业风险。
> 原则：**绝不伪造**（无同业 → L3 快照，行业未覆盖/文件缺失 → `None`；无 bottom-up 则回退回归 β）；**保持单一 β 出口**（`resolve_effective_beta()` 不变，ADR-019）；**接线为 add**（golden 因离线 `bottom_up_beta=None` **零漂移**）。
> 验证：pytest **333 → 353 passed**（+20）；golden 指纹**零漂移**；新模块 `industry_beta.py` / 新测试 **Ruff clean**。

### ✨ Added
- ✨ **`data/damodaran_beta.json`（新数据）**：Damodaran 公开行业 unlevered β 快照（**Jan 2026**，100 行业），字段 `unlevered_beta` + `unlevered_beta_cash_adjusted`；仅作 L3 兜底基准，缺失即 null（绝不伪造）
- ✨ **`data/industry_beta.py` 完整 β 链**：`PeerBeta` / `PeerScreen` / `IndustryBetaResult`（`note()` + `to_chain()` 审计快照）；`_unlever` / `_relever`（Hamada）/ `_cash_adjust`（`β_business = β_u/(1−Cash/Firm)`，`Cash/Firm` 上限 0.90）
- ✨ **三级业务身份筛选**：`get_companies_by_business_identity(sub_industry, business_model, economic_profile, *, sector, industry_lister, neighbor_lister, model_resolver, profile_resolver, min_peers, use_neighbors)`——L1 同子行业(+模型过滤) / L2 相邻行业(+经济特征过滤) / L3 空集（走基准）；`_profile_matches`（duck-typed 形状比较，缺失不算不匹配）
- ✨ **L3 基准解析**：`_DAMODARAN_ALIASES`（Yahoo industry → Damodaran 名 ~80 条）+ `_normalize_industry()`（en/em-dash → hyphen）+ `_damodaran_lookup()`（未匹配 → `None`）
- ✨ **`derive_bottom_up_beta(...)`**：完整三级筛选 + 链式推导（`_collect_peer_chain` → median → cash-adjust → relever）；缓存 key 含 `business_model`；`BOTTOM_UP_BETA=0` 可关；`offline`/`use_neighbors`/`use_benchmark`/`benchmark_path` 可注入；**全部失败 → `None`**
- ✨ **`MarketData`（`data/models.py`）M-34 字段**：`bottom_up_beta: Optional[float]`（CAPM 消费的 target-relevered β）+ `bottom_up_beta_chain: Optional[Dict]`（完整链快照）；`industry_beta` 保留为原始 peer-median *unlevered*
- ✨ **20 新用例（`tests/test_industry_beta.py`）**：cash-adjust / relever 数学；三级筛选（L1 模型过滤 / L2 经济特征过滤 / L3 无同业）；Damodaran alias + unmatched + 缺失文件 + 内置快照；完整链（含 cash + relever）；L3 基准 fallback；`to_chain()` 字段完整性；`PeerBeta` 对象输入；**CAPM 优先级（bottom-up 优先 / 回退回归 β / 超上限 winsorize）**

### 🔧 Changed
- 🔧 **`valuation/wacc.py`（M-34 接线）**：`calculate()` β 段改为**三段优先级**——bottom-up（cash-adjusted + target-relevered，仍 winsorize [0.30, 2.50]）→ 回归 β（winsorized）→ `default_unlevered_beta`；`WaccBreakdown` 新增 `beta_bottom_up` / `beta_bottom_up_note`；`beta_transparency_note()` 展示完整分子链
- 🔧 **`valuation/wacc.py::resolve_effective_beta()` 语义修正**：`clamped` 现仅表示「**原始回归 β** 超出 CAPM 带」，不与「所用 β 不同」混淆（避免 bottom-up 选取被误报为截断）
- 🔧 **`data/providers.py`（接线）**：`_fetch` 在 `kd_snapshot` 后新增 **bottom-up β 链块**（从 business description + industry 推断 `BusinessModel`，target D/E = 总债务/市值，tax = `etr_snapshot`），`MarketData(...)` 构造改传 `industry_beta=industry_beta_unlev, bottom_up_beta=bottom_up_beta, bottom_up_beta_chain=bottom_up_chain`；旧 Layer-3 β 块删除
- 🔧 **`analysis/risk.py`**：`_wacc_risk()` evidence 文案改为「原始回归 β = X 超出 CAPM 区间」，与 `clamped` 新语义一致
- 🔧 **`reporting/dashboard.py`**：β 文案「统一采用截断值」改为「统一采用 β = X」

### 📊 Baseline Verification (Session #25)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **353/353 passed** | 333 → 353（+20） |
| golden 回归 | ✅ 无漂移 | 离线 `bottom_up_beta=None` → 回退回归 β，基线不变 |
| CAPM 优先级 | ✅ bottom-up 优先、缺失回退 | `test_capm_prefers_bottom_up_beta` / `test_capm_falls_back_to_regression_beta` |
| L3 基准 | ✅ alias 命中、未匹配 → None | 内置快照 Jan 2026 |
| Ruff | ✅ 新模块/新测试 clean | 遗留 E7xx 均为未改动旧代码 |

### ⚠️ Known Issues (Session #25)
- ① **Segment-level β 未实现**：多业务公司仍用公司级 β（按业务价值加权整合留待后续，见 ROADMAP）
- ② **L2 经济特征过滤依赖 `profile_resolver`**：真实同业 `EconomicProfile` 数据接入前，L2 仅按行业相邻（代码已显式声明，不冒充「相似经济特征」）
- ③ **L3 快照需年度维护**：`data/damodaran_beta.json` 为 Jan 2026 版本，Damodaran 更新后需同步（`_meta.as_of` 留痕）

---


## [Unreleased] — 2026-11-14 (Session #24 — 三源 sector/industry 补全链 + bottom-up β 唤醒，H-03)

> 触发：用户要求用 **SEC EDGAR**（一手 SIC）、**Wikipedia/Wikidata**（冷门/退市兜底）、**FinanceDatabase**（30 万+ 离线元数据）三来源补全 `sector/industry`，同时唤醒 bottom-up β 并把分类准确率从 75% 推到 90%+。
> 根因：Yahoo `quoteSummary/assetProfile` 长期 **401（约 83%）** → `sector/industry` 大面积为 `None` → 分类器 layer-2 行业硬规则（+3.0）整体失效 + ML 文本特征丢失最强信号 → 边界准确率被钉在 ~75%。
> 原则：**绝不伪造**（缺失即返回 `{}`/`None`，不填猜测值）；**SIC→Yahoo 桥接必须「可消费」**（映射产出的 industry 必须能被硬规则消费，否则返回 None）；**优雅降级**（外部库 optional import，断网/未装 → 该层跳过）；**接线为 add**（bottom-up β 不改 CAPM，taxonomy 仍 shadow）。（ADR-040）
> 验证：pytest **333/333 passed**（288 → 333，新增 45 用例）；golden 指纹**零漂移**；Ruff clean；在线 smoke — SEC 层 **10/10 精确**（AAPL/NVDA/JPM/PLD/XOM/MSFT/BRK-B/KR/AMZN/BLK），硬规则命中率 **75% → 78.3%**，Semis bottom-up 无杠杆 β = **1.2447**。

### ✨ Added
- ✨ **`data/sic_map.py`（新模块）**：SEC **SIC → Yahoo** taxonomy 桥接。`SIC_TO_YAHOO`（约 180 条精确 4 位：3571 Computer Hardware / 3674 Semiconductors / 7372 Software-App / 6021 Banks-Diversified / 6331 Insurance-P&C / 6798 REIT-Diversified / 2911 Oil&Gas Refining / 4911 Utilities-Electric …）+ `SIC2_TO_YAHOO`（约 68 条 2 位大类）+ `SIC_DESC_KEYWORDS`（约 130 条关键词，按**具体→宽泛**排序）+ `map_sic_to_yahoo(sic, sic_description)`（解析序：精确 4 位 → 2 位大类 → 描述关键词）+ `_normalize_sic()`（零填充）
- ✨ **`data/industry_resolver.py`（新模块）**：`SectorIndustryResolver` **三源优先级链**——`_from_financedatabase`（离线 Yahoo 兼容）→ `_from_sec_edgar`（`_load_sec_ticker_map` → `_sec_cik_for` → `_SEC_SUBMISSIONS_URL` 取 `sic`+`sicDescription`）→ `_from_wikidata`（SPARQL P452）。返回 `{sector, industry, sic, sic_description, source}`；类级 `_MEM` + `.cache/` 磁盘缓存；`batch_get()` 只返回非空；辅助 `_sec_ua()`（读 `SEC_USER_AGENT`）/ `_ticker_variants()`（BRK.B→BRK-B）/ `_first_str()`；便捷入口 `resolve_sector_industry()`
- ✨ **`data/industry_beta.py`（新模块）**：`derive_industry_unlevered_beta(...)` **动态同业无杠杆 β（Hamada）**。`β_u = β_L / (1 + (1−t)·(D/E))`，`t=0.21`；同业来自 `fd.Equities().select(industry=)`，逐 peer β 与 D/E 来自 yfinance；**取中位**抗离群；`IndustryBetaResult.note()`；`_MIN_PEERS=3` / `_DEFAULT_TAX=0.21` / `BOTTOM_UP_BETA=0` 开关；缓存 `.cache/industry_beta.json`（key `{sector}|{industry}`）；**<3 家同业或 β 不可得 → `None`（绝不伪造）**
- ✨ **三源测试（`tests/test_sic_map.py` / `tests/test_industry_resolver.py` / `tests/test_industry_beta.py`，共 45 用例）**：SIC 精确/大类/关键词解析与「产出必可分类」守卫；三源链分层优先级（无 HTTP 走 FinanceDB / SEC 映射 SIC / Wikidata 兜底）、点号变体、磁盘持久化 + offline 复用、无法解析返回 `{}`；Hamada 去杠杆、中位取值、样本不足返回 `None`、缓存与 `offline`。全部 monkeypatch 离线化

### 🔧 Changed
- 🔧 **`data/providers.py`（H-03）**：`_fetch_quote_summary_simple` 在 Layer-3 sector/industry resolver 块后新增 **bottom-up β 块**——当 `industry_beta` 缺失且已有 sector/industry 时调用 `derive_industry_unlevered_beta()` 填充 `out["industry_beta"]`（失败静默 debug，不阻断），使 `MarketData.industry_beta` 审计槽位不再恒为 `None`
- 🔧 **`classification/classifier.py`（H-03）**：`SECTOR_INDUSTRY_MAP` 新增 `("asset management", BusinessType.BANK)`（置于 `capital markets`/`brokerage` 同族附近）——修复 SEC SIC "6726"/"67" → "Asset Management" 经 `map_sector_industry()` 返回 None 的唯一硬规则覆盖缺口

### 📊 Baseline Verification (Session #24)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **333/333 passed** | 288 → 333（+45） |
| golden 回归 | ✅ 无漂移 | 三源链 + bottom-up β 均为 add，`business_type`/路由未变 |
| 在线 smoke | ✅ SEC 层 10/10 精确 | AAPL/NVDA/JPM/PLD/XOM/MSFT/BRK-B/KR/AMZN/BLK；硬规则命中率 75% → 78.3% |
| bottom-up β | ✅ Semis β_u = 1.2447 | 动态同业推导（Hamada 去杠杆 + 中位） |
| Ruff | ✅ clean | — |

### ⚠️ Known Issues (Session #24)
- ① 分类硬规则命中率 **78.3%（18/23）未达 90%**：剩余 5 只（ASML/QCOM/MSFT/XOM/BRK-B）是**真值/粒度差**而非 `None` 缺口 → 需 M-16（阈值复评）+ C-02（真实标注重训）
- ② bottom-up β 当前**仅作审计展示，不参与 CAPM**（`beta_transparency_note()`）；升级为 CAPM 输入须单独审阅与回归 β 的收敛差异（By Design）
- ③ 三源链依赖外部库/网络（**优雅降级**）：FinanceDatabase / SEC EDGAR / Wikidata 均 optional import，未装或断网 → 该层返回 `{}` 继续下一层；SEC 需合规 `User-Agent` 且限流保守（By Design）

---

## [Unreleased] — 2026-11-14 (Session #23 — 内部标准 Taxonomy + 五维公司拆解 + 黄金法则「经济学不得跨族决定 Identity」)

> 触发：用户提问「把 Yahoo `Software—Infrastructure`、ML 的 `MatureTech/SaaS`、业务描述、收入结构放在一起做冲突处理」→ 决定实现**五维模型**（Identity / Model / Revenue / Economics / External）。
> 核心原则：**财务特征可以帮助判断经济模式，但不能单独决定 Business Identity**——高毛利 + 高 CapEx + 低负债也可以是一家经营大型 AI 数据中心的 Software/Cloud 公司，而不是 Semiconductor（ADR-039）。
> 验证：pytest **288/288 passed**（240 → 288，新增 48 用例）；golden 指纹**零漂移**（taxonomy 为 additive/shadow 接线）；改动文件 import/运行通过。

### ✨ Added
- ✨ **`classification/taxonomy.py`（新模块 ≈1000 行）**：① Business Identity 显式节点树（99 节点，`canonical key + parent + archetype`）/ ② `BusinessModel` 枚举 + 关键词推断 / ③ `RevenueComposition`（不可用即显式声明）/ ④ `EconomicProfile`（ttm-first 形状推导）/ ⑤ `ExternalClassification`（原始标签留痕）
- ✨ **冲突裁决 contract**：`reconcile_identity()` + `ConflictKind`（`consistent` / `refinement` / `identity_wins` / `economics_only` / `insufficient`）+ `TaxonomyReconciliation`（含 `confidence_delta` 与中文 `notes`）
- ✨ **黄金法则 API**：`economic_identity_ceiling()`——经济学仅可**族内**细化；同族兄弟冲突收敛至 `common_ancestor`，**绝不采用经济学节点**
- ✨ **映射表**：`YAHOO_INDUSTRY_TO_NODE`（+logistics 等）/ `YAHOO_SECTOR_TO_NODE` / `ML_LABEL_TO_NODE` / `_DESCRIPTION_NODE_HINTS`（data center → `tech.cloud_infra`）
- ✨ **五维装配 + 接线**：`build_taxonomy_profile()` / `attach_taxonomy_profile()`（additive 写入 `CompanyProfile`）
- ✨ **`CompanyProfile` 8 个 shadow 字段**：`taxonomy_identity_key` / `taxonomy_identity_label` / `taxonomy_business_models` / `taxonomy_conflict_kind` / `taxonomy_audit` / `revenue_composition_available` / `revenue_composition_note` / `external_classification`
- ✨ **`MarketData.description`**：采集 Yahoo `assetProfile.longBusinessSummary`（原已请求但被丢弃，无需新增网络请求）
- ✨ **`tests/test_taxonomy.py`（48 用例）**：节点树完整性 / longest-key-wins / industry 优先于 sector / 黄金法则（跨族 + 同族兄弟）/ 冲突状态机 / 商业模式推断 / 经济形状 / 五维契约 additive

### 🔧 Changed
- 🔧 **`classification/classifier.py` + `classification/ml_classifier.py`**：规则路径与 ML 路径（含 `rule_fallback`）统一调用 `attach_taxonomy_profile()`；ML 路径传入**原始 top-1**（pre sector-hard-rule）以便 reconcile 观察到统计/原型冲突
- 🔧 **`node_from_yahoo()` 改两段式**：industry 优先匹配 → sector 匹配 → sector→family 兜底表（修复长 sector 短语压过具体 industry）
- 🔧 **`depth` 改由 parent 链推导**（原 `key.count(".")`）；`cs` 族根去掉 `cons` 父边（族根应无父）

### 🐛 Fixed
- 🐛 **`_MODEL_KEYWORDS` 死词条**：`"commodot"`（永不匹配的 typo）→ `"commodit"`（识别 `commodities`/`commodity`）
- 🐛 **AMZN 误判**：`Consumer Cyclical / Internet Retail` 原 → `cons.generic`（"Consumer Cyclical" 17 字符压过 "Internet Retail" 15 字符）→ 现 `cons.ecommerce`
- 🐛 **KR 误判**：`Consumer Defensive / Grocery Stores` 原 → `cs.generic` → 现 `cs.retail`

### 📊 Baseline Verification (Session #23)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **288/288 passed** | 240 → 288（+48） |
| golden 回归 | ✅ 无漂移 | taxonomy additive，`business_type`/路由未变 |
| 运行验证 | ✅ `import` + demo 端到端通过 | NBIS(Software-Infra)+ML(Semiconductor,57%) → `tech`/MatureTech，非 Semiconductor |
| Ruff | ⬜ 未执行 | — |

### ⚠️ Known Issues (Session #23)
- ③ Revenue Composition 仍恒为 `unavailable`（Yahoo timeseries 无分部收入；SEC EDGAR 未启用）
- taxonomy 为 **shadow 层**：暂不参与 `business_type`/路由，需后续显式切换才影响估值
- ⑤ 中 GICS / NAICS 当前 provider 不提供（字段占位，留空）

---

## [Unreleased] — 2026-11-13 (Session #22 / Phase 4 — 全量回归 + 边界/验收用例断言化 + golden 指纹扩展)

> 触发：《估值完整性重构》任务书 **Phase 4（测试与验收）**（`tests/golden_report.py` / `tests/golden/report_fingerprints.json` / `tests/test_phase4_integrity.py`）。
> 核心原则：**验收标准必须断言化——样本口径（原始解算 / IQR 排除 / 参与聚合）可审计；核心模型被 IQR 排除却显示强一致性必须被判为缺陷；风险等级不得被加成总分掩盖**（ADR-038）。
> 验证：pytest **240/240 passed**（231 → 240，新增 9 用例）；golden 基线重生成（原 9 只既有字段无漂移）；改动文件 ruff clean。

### ✨ Added
- ✨ **`tests/test_phase4_integrity.py`（9 用例）**：逐条锚定任务书 10 条验收标准——风险底线全 universe / High 旗标强制整体 ≥High / Floor 实际触发 / IQR 排除核心模型→`Unresolved Disagreement (Review Required)` / 封顶按独立证据数计票 / 极端 TV/EV 支配下调 DCF 权重 / 未知身份不冒充精确行业匹配 / 全 universe invariant + 样本口径 / 负 FCF 建构保留旗标
- ✨ **golden 指纹 5 新字段（`tests/golden_report.py`）**：`n_independent_evidence` / `raw_solved_count` / `outlier_count` / `effective_aggregation_count` / `core_model_excluded`

### 🔧 Changed
- 🔧 **回归 universe 扩展（`BASKET` 9 → 18）**：+GOOGL / AMZN / AVGO / ORCL / CRWV / UPS / KR / BAC / NU（新增 9 只 fixture 见 `data/providers.py`）
- 🔧 **`check_invariants()` 覆盖率封顶门控**：`n_solved` → `n_independent_evidence`（与 Phase 3 计票口径一致）
- 🔧 **golden 基线重生成**：`UPDATE_GOLDEN=1 pytest tests/test_golden_report.py`（原 9 只既有字段无漂移）

### 🐛 Fixed
- 🐛 **新增 invariant 2b**：核心模型（DCF）被 IQR 排除却仍输出 Very Strong/Strong/Moderate → 判为缺陷（禁止「静默移除核心模型却显示高一致性」）
- 🐛 **`tests/test_providers_provenance.py`**：原用 `"BAC"` 作「未知 ticker」，Phase 4 新增 BAC fixture 后不再抛异常 → 2 处改为 `"ZZZZ"`
- 🐛 **Ruff 遗留清理**：`analysis/risk.py`（未用 `Tuple` 导入 + 未用 `reason` 局部变量）、`tests/golden_report.py`（未用 `by_name`）

### 📊 Baseline Verification (Session #22)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **240/240 passed** | 231 → 240（+9） |
| golden 回归 | ✅ 2 passed / 1 skipped | 基线重生成，原 9 只无漂移 |
| 回归 universe | ✅ 18 只 | 10 只新画像 invariants 全空 |
| Ruff（改动文件） | ✅ All checks passed | risk.py / golden_report.py / test_phase4_integrity.py / model_agreement.py / test_providers_provenance.py |
| Pyright | ⚠️ 不可用 | 未安装 |

### ⚠️ Known Issues (Session #22)
- Pyright 未安装 → 类型检查暂缺（非代码缺陷，如实记录）
- 报告样本口径变更会触发 golden 漂移，须逐字段审阅再重生成

---

## [Unreleased] — 2026-11-13 (Session #21 / Phase 3 — WACC β 多窗口敏感性 + peer 倍数来源溯源 + 同源证据去重)

> 触发：《估值完整性重构》任务书 **Phase 3（P1）**（`valuation/wacc.py` / `models/multiples.py` / `analysis/model_agreement.py` / `reporting/dashboard.py`）。
> 核心原则：**单一回归 β 不得掩盖估计不稳（须暴露多窗口 β 及离散度）；peer 倍数须标注来源档位与样本数，缺失不得静默；同一证据族的多个模型不得作为「多条独立证据」抬高一致性门控**（ADR-036 / ADR-037）。
> 验证：pytest **231/231 passed**（217 → 231，新增 14 用例）；新版文件 ruff clean；golden 无漂移。

### ✨ Added
- ✨ **`MarketData.beta_windows` / `MarketData.industry_beta`（`data/models.py`）**：窗口标签→回归 β（2Y 周/3Y 月/5Y 月）+ bottom-up β 槽位；`None` 表示「无来源」，绝不伪造
- ✨ **`BETA_WINDOWS` 常量 + `_estimate_beta_windows()`（`data/providers.py`）**：逐窗口独立回归，失败窗口显式 `None`
- ✨ **`WaccBreakdown.beta_windows` / `beta_dispersion` + `beta_window_note()`（`valuation/wacc.py`）**：<2 窗口返回 `None`；极差 >0.50 标注「窗口间波动较大」
- ✨ **peer 来源溯源常量（`models/multiples.py`）**：`PEER_SOURCE_EXACT_INDUSTRY` / `SECTOR_FALLBACK` / `BUSINESS_TYPE_FALLBACK` / `APPROXIMATE` + `PEER_SOURCE_LABELS` 封闭集 + `peer_sample_size`
- ✨ **`_MODEL_FAMILY` + `_independent_evidence()`（`analysis/model_agreement.py`）**：同源证据归并；`ModelAgreement.n_independent_evidence` / `duplicate_evidence_groups`
- ✨ **报告区块「🔎 同行倍数来源 (可审计)」（`reporting/dashboard.py`）**
- ✨ **测试 14 用例（`tests/test_phase3_integrity.py`）**

### 🔧 Changed
- 🔧 **`_estimate_beta()`（`data/providers.py`）**：由单窗口泛化为 `(range_, interval, min_obs)`；周线用 ISO-week keying（`_monthly_returns`→`_period_closes`）
- 🔧 **`_sector_peer_multiple` / `_resolve_peer_bucket`（`models/multiples.py`）**：返回 4 元组 `(value, source_text, source_kind, n_peers)`；`calculate()` breakdown 落 `peer_source_kind` / `peer_sample_size`
- 🔧 **覆盖率门控（`analysis/model_agreement.py`）**：`_COVERAGE_CAP.get(n_solved)` → `.get(n_independent)`（同源证据不重复计票）
- 🔧 **WACC 区块渲染（`reporting/dashboard.py`）**：追加 `beta_window_note()` 输出；渲染层消费引擎字段，不硬编码口径词

### 🐛 Fixed
- 🐛 **单一 β 掩盖估计不稳**：报告只给一个 β，读者无法判断稳定性 → 新增多窗口 β + 离散度披露
- 🐛 **peer 倍数来源不明**：倍数来源（精确行业/回退/近似）与样本数缺失 → 4 档溯源标签 + 样本数，缺失显式呈现
- 🐛 **同源证据重复计票**：`P/E`↔`Historical Multiples`（同 `PEModel`）、`EV/Sales`↔`EV/Sales (Unit Econ)`、`DCF`↔`ReverseDCF` 被当作独立证据抬高一致性 → `model_family` 归并后按独立证据数计票

### 📊 Baseline Verification (Session #21)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **231/231 passed** | 217 → 231（+14） |
| 新增测试 | ✅ `tests/test_phase3_integrity.py` | β ×7 / peer ×3 / 去重 ×4 |
| Ruff（新增/改动文件） | ✅ clean | 仓库无 ruff 配置，scoped 运行 |
| Pyright | ⚠️ 不可用 | 未安装 |
| golden 指纹 | ✅ 无漂移 | β 窗口不在指纹字段；新增区块仅渲染层 |
| 端到端 | ✅ | AAPL `EXACT_INDUSTRY` / NBIS `APPROXIMATE` n=5 / JPM `EXACT_INDUSTRY` |

### ⚠️ Known Issues (Session #21)
- bottom-up β 依赖同业 unlevered β 数据源，当前 provider 无该数据 → `industry_beta` 恒为 `None`（字段与渲染就绪，待数据源接入）
- β 多窗口为独立审计输入，**不覆盖** CAPM 使用的标量 `beta`

---

## [Unreleased] — 2026-11-13 (Session #20 / Phase 2 — Monte Carlo 双模式 + 路径锚点对账 + 经营/折现情景拆分 + 报告透明化)

> 触发：《估值完整性重构》任务书 **Phase 2**（`forecasts/` / `simulation/monte_carlo.py` / `reporting/dashboard.py`）。
> 核心原则：**MC 不是独立估值证据，而是「确定性 DCF 假设的扰动分布」——零扰动时必须精确复现确定性 DCF 的 base 点值；人为利润率地板必须移除；经营驱动情景与折现率情景必须拆分展示**（ADR-034 / ADR-035）。
> 验证：pytest **217/217 passed**（163 → 217，新增 14 用例）；golden 无漂移（golden 走 `monte_carlo=None`）。

### ✨ Added
- ✨ **MC 双模式常量（`simulation/monte_carlo.py`）**：`MODE_BASE_CASE` / `MODE_HISTORICAL` + `DRIVER_LABELS`
- ✨ **`_base_case_path()` / `_project_one_path()`（`simulation/monte_carlo.py`）**：提取确定性 DCF base 的逐年 `shape_rev` / `margin_offsets`，零扰动时精确复现 DCF base FCF 路径
- ✨ **`MonteCarloResult` 新字段（`simulation/monte_carlo.py`）**：`mode` / `random_seed` / `n_requested` / `n_invalid` / `n_truncated` / `param_distributions` / `correlation` / `anchor_value` / `dcf_anchor` / `reconcile_gap`
- ✨ **可配置 MC 边界（`config.py` `MonteCarloConfig`）**：`revenue_cagr_lower/upper`、`op_margin_lower/upper`（含负值）、`wacc_lower/upper`、`tg_lower/upper`、`mode`（默认 `base_case`）
- ✨ **`ScenarioAnalyzer.run_operating()`（`analysis/scenario.py`）**：营收增长 × 利润率扰动 → FCF → EV（`scenario_kind="operating"`）
- ✨ **报告区块（`config.py` `REPORT_SECTION_TITLES`）**：`scenarios="🎭 折现率情景"` + `operating_scenarios="🏭 经营性情景"`
- ✨ **`_operating_scenario_section()`（`reporting/dashboard.py`）**
- ✨ **测试 14 用例（`tests/test_monte_carlo_modes.py`）**

### 🔧 Changed
- 🔧 **`MonteCarloSimulator.run(data, profile, mode=None, dcf_value=None)`**：无 DCF 锚点（金融股 RIM/DDM 或未求解）时**自动回退 historical + 附说明**，不静默
- 🔧 **去除人为利润率地板**：取消 MC 内 `max(om, +2%)`，允许负利润率；锚点沿用 DCF「负股权 → 归零」约定
- 🔧 **`ScenarioValuation`（`analysis/scenario.py`）**：新增 `scenario_kind`（默认 `discount_rate`）+ `drivers`；`_run_financial_scenarios` → `financial`；`_run_one` → `discount_rate` + `drivers={wacc, terminal_growth}`
- 🔧 **`build_report(..., operating_scenarios=None)`（`reporting/dashboard.py`）**：`_scenario_section` 前置「本组情景仅变动折现率（WACC/g）」
- 🔧 **MC 区块透明化（`reporting/dashboard.py`）**：模式标签 + 「DCF 假设扰动分布，非独立估值证据」 + 种子/请求数/有效数/无效数/截断数/参数分布/相关矩阵；对账行**仅 `mode=="base_case"`** 渲染
- 🔧 **`telegram_bot.py`**：新增 `run_operating(data, profile)`；MC 调用传 `dcf_value=<DCF 每股价值 or None>`；`build_report(..., mc_result, operating_scenarios)`

### 🐛 Fixed
- 🐛 **MC 锚点 ≠ 确定性 DCF（MSFT 偏差 +13.85%）**：MC 用平坦 CAGR/OM，DCF 用衰减增长路径 + 漂移利润率 → 路径形参化后零扰动锚点精确等于 DCF（MSFT/AAPL 差 +0.0%）
- 🐛 **MC 人为利润率地板**：`max(om, +2%)` 制造虚假正向利润率（违反映亏损期标的的真实经济现状）→ 已移除，允许负利润率（NBIS）
- 🐛 **负股权口径撕裂**：MC 未沿用 DCF「负股权 → 归零」约定 → 锚点/分布与 DCF 不一致（已统一）
- 🐛 **情景语义混淆**：经营驱动情景与折现率情景混在同一区块 → 已拆分并各自标注口径
- 🐛 **`P(股权价值归零/破产)` 用词错误**：方向基准应为「模拟下 equity value 归零」（非公司破产）→ 改为「Equity Value Wipeout Probability」

### 📊 Baseline Verification (Session #20)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **217/217 passed** | 163 → 217（Phase 2 +14） |
| 零扰动锚点 = DCF | ✅ MSFT $197.34 vs $197.34（+0.0%）/ AAPL $77.88 vs $77.88（+0.0%） | `_project_one_path` 精确复现 |
| 亏损期归零 | ✅ NBIS 锚 $0.00 vs DCF $0.00（+0.0%） | 沿用 DCF 负股权地板 |
| 金融股回退 | ✅ JPM `mode=historical` + 说明文案 | 无 DCF 锚点自动回退 |
| 负利润率保留 | ✅ NBIS 负 OM 未被地板抬正 | 边界可配置 |
| 报告渲染 | ✅ MSFT/JPM/NBIS 端到端 | 经营情景渲染；折现情景标注；对账仅 base_case；JPM 经营情景区缺省 |
| golden | ✅ 无漂移 | golden 走 `monte_carlo=None` |

---

## [Unreleased] — 2026-11-13 (Session #19 — Rf 单一真源 + Terminal Growth 三档「经济学含义」重定义 + Quality-Weighted Median 边界修复)

> 触发：用户对 `valuation/wacc.py` / `valuation/terminal_growth.py` / `models/dcf.py` / `analysis/model_agreement.py` 的**静态代码审查（2×P0 + 1×P1，用户声明为「实际代码问题」而非推测）**。
> 核心原则：**CAPM 与 Cost of Debt 必须共用同一个已解析 Rf；GDP 上限只约束「长期稳定终值增长率」= Base，乐观 High 是情景区间——不机械禁止其超 GDP，但绝不误称为长期稳定终值增长率；加权中位数在等权时必须精确退化为普通中位数**（ADR-032 / ADR-033）。
> 验证：pytest **163/163 passed**（147 → 163）；golden 因加权中位数缺陷修复出现 4 只有意漂移（已审阅重生成）。

### ✨ Added
- ✨ **`BAND_LABELS`（`valuation/terminal_growth.py`）**：三档语义契约常量（`low`/`base`/`high` → 本地化文案），供渲染层消费，禁止渲染层自造口径词
- ✨ **`TerminalGrowthRange` 新字段（`valuation/terminal_growth.py`）**：`high_exceeds_gdp: bool`、`gdp_ceiling: float`、`band_labels: Dict[str,str]`
- ✨ **测试 3 用例（`tests/test_wacc_kd.py`）**：MarketData 无 Rf + Treasury 有效 → CAPM 与 Kd fallback **同源 Rf**；显式传入 Rf 覆盖 MarketData；无传入时回落 MarketData/config
- ✨ **测试 3 用例（`tests/test_terminal_growth.py`）**：`Base=4.5%` 时 `High=5.0%` 且 `high_exceeds_gdp=True`；正常情况 High ≤ GDP 不置旗标；`band_labels` 语义契约断言
- ✨ **新增测试文件 16 用例（`tests/test_model_agreement.py`）**：等权偶数/奇数（= 普通中位数）、二值平均、单值、乱序输入、不等权（重权主导 / 精确半权平局 / 无平局）、零权重剔除、全零返回 None、负权重钳制、缺失权重默认 1.0、空输入

### 🔧 Changed
- 🔧 **`_implied_cost_of_debt()` 签名（`valuation/wacc.py`）**：新增 `risk_free_rate: Optional[float]`；`calculate()` 改为 `self._implied_cost_of_debt(data, risk_free_rate=rf)` → 所有债务成本 fallback 与 CAPM（`ke = rf + β·ERP`）共用同一 Rf；独立调用回落原优先级链
- 🔧 **三档经济学含义重定义（`valuation/terminal_growth.py`）**：docstring / 常量注释明确「GDP 上限只约束 Base」；`calculate()` 计算 `high_exceeds_gdp` 并在为真时追加「High 为乐观情景，非长期稳定终值增长率」note；`derivation_trace()` / `_enforce_strict_bands()` docstring 同步
- 🔧 **DCF 假设说明（`models/dcf.py`）**：`Terminal Growth (Base)` → 「Long-run stable rate: min(...)」；`Terminal Growth (High)` 按 `tvg.high_exceeds_gdp` 分叉（超 GDP 标注「NOT a long-run stable terminal growth rate」）
- 🔧 **渲染契约化（`reporting/dashboard.py`）**：三档区块规则文案重写为「Base=长期稳定终值增长率（GDP+Gordon 封顶）；Low/High=保守/乐观情景区间」；超 GDP 时新增「⚠ High X% 高于长期名义 GDP Y%：仅作乐观情景参考」
- 🔧 **`_weighted_median()` 重写（`analysis/model_agreement.py`）**：改用标准 **midpoint 定义**（下加权中位数与上加权中位数取平均）→ 等权时精确退化为普通中位数；零/负权重剔除；空输入返回 None
- 🔧 **`tests/golden/report_fingerprints.json`**：`UPDATE_GOLDEN=1` 重生成基线（`median_value_weighted`：AAPL 123.99→132.19 / AMT 57.82→109.85 / JPM 139.22→151.37 / NOW 147.21→148.84；均归位到普通中位数，**已审阅的有意漂移**）

### 🐛 Fixed
- 🐛 **P0-1**：`_implied_cost_of_debt()` 独立重读 Rf → MarketData Rf 为空时 ke 用 Treasury、kd fallback 静默用 config 默认（已改为传入已解析 `rf`，单一真源）
- 🐛 **P0-2**：Terminal Growth High `= Base + 0.5%` 无条件突破长期 GDP 上限 → 易被误当长期稳定终值增长率（已重定义语义 + 显式标注）
- 🐛 **P1-3**：`_weighted_median()` 返回首个累计权重 ≥ total/2 的值 → 等权且偶数时返回第 n/2 个值而非 `mean(values[n/2-1], values[n/2])`，加权中位数 ≠ 普通中位数（AAPL 176.12 vs 165.24）（已改用 midpoint 定义）

### 📊 Baseline Verification (Session #19)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **163/163 passed** | 147 → 163（P0 +5 / P1 +16） |
| Rf 同源 | ✅ `test_capm_and_kd_fallback_share_same_treasury_rf` | MarketData 无 Rf + Treasury=5.103% → `wb.risk_free_rate == treasury_rf`；`cost_of_debt_implied_raw == treasury_rf + 0.025` |
| Rf 传参优先 | ✅ `test_implied_cost_of_debt_uses_passed_rf_not_marketdata` | 显式 Rf 覆盖 MarketData |
| Rf 回落链 | ✅ `test_implied_cost_of_debt_falls_back_when_no_rf_passed` | 无传入 → MarketData/config |
| High > GDP 旗标 | ✅ `test_high_growth_gdp_capped_base_still_spreads` | `base ≤ gdp_ceiling`；`high > gdp_ceiling`；`high_exceeds_gdp is True` |
| High ≤ GDP 不置旗 | ✅ `test_high_within_gdp_not_flagged` | `high_exceeds_gdp is False` |
| 语义契约 | ✅ `test_band_semantics_contract` | `tvg.band_labels == BAND_LABELS` |
| 加权中位数等权退化 | ✅ `TestWeightedMedianEqualWeights` | 偶数/奇数等权 == `statistics.median` |
| 加权中位数不等权/零权 | ✅ `TestWeightedMedianUnequalWeights` / `TestWeightedMedianZeroWeights` | 重权主导；零/负权重剔除；全零 None |
| 端到端渲染 | ✅ AAPL synthetic（high 2.0%，无告警）/ NVDA·MSFT·NOW·NBIS（high 5.0%，出现「⚠ High 5.00% > 长期名义 GDP 4.50%」） | 渲染层消费 `high_exceeds_gdp` |

---

## [Unreleased] — 2026-11-12 (Session #18 — 反解求解器 P0/P1 加固: bracket 重校验 + 单调性采样 + 多根/常数检测 + 负终值贯穿)

> 触发：用户对 `models/reverse_dcf.py` / `forecasts/fcf_projection.py` 的**静态代码审查（6 项：3×P0 + 3×P1）**。承接 Session #17 约束式求解器。
> 核心原则：**无有效 bracket 不得返回可疑根；单调性必须实测而非假设；终值被抑制的结果不得伪装成完整 SOLVED**（ADR-031）。
> 验证：pytest **142/142 passed**（124 → 142，新增 18 用例）；golden 无漂移。

### ✨ Added
- ✨ **`SolverStatus` 新成员（`config.py`）**：`NON_MONOTONIC` / `MULTIPLE_ROOTS` / `FLAT_OBJECTIVE`
- ✨ **`ReverseDCFConfig.implied_monotonic_samples: int = 21`（`config.py`）**：区间采样点数，用于验证声明的单调性
- ✨ **`_root_brackets()`（`models/reverse_dcf.py`）**：合并连续变号采样区间 → root bracket 列表（>1 即多解）
- ✨ **`_finish_root()`（`models/reverse_dcf.py`）**：在**已验证** bracket 内求解；端点先判、否则 `brentq`；失败且 `f(a)·f(b) > 0` → `NO_SOLUTION_IN_RANGE`（拒可疑根）；否则二分；最后 residual 检查
- ✨ **`_finalize_revenue_cagr()`（`models/reverse_dcf.py`）**：终期 FCF ≤ 0（终值已抑制）时把 `SOLVED` 降级 `APPROXIMATE` + turnaround note
- ✨ **`ImpliedExpectations.terminal_fcf_negative`（`analysis/expectation.py`）**：透传终值抑制旗标并追加「Terminal Value Suppressed — Turnaround Assumption Required」约束说明
- ✨ **测试 18 用例（`tests/test_reverse_dcf.py`）**：`TestSolverBoundariesSession18` / `TestNegativeTerminalFCFSession18` / `TestImpliedRoundTripsSession18` / `TestMultiTickerStateIsolation`

### 🔧 Changed
- 🔧 **`_solve_implied_scalar()` 重写（`models/reverse_dcf.py`）**：先 21 点采样 → 常数目标判定 → 单调方向实测 → 非单调扫描 root brackets → 单调则判可达区间（越界指名边界）→ `_finish_root`；单调性容差改为步长尺度 `mono_tol`
- 🔧 **`_solve_revenue_cagr()`（`models/reverse_dcf.py`）**：端点根优先（含容差）；越界判定改 `> 0`；二分 fallback 前重校验 bracket
- 🔧 **`calculate()` breakdown（`models/reverse_dcf.py`）**：新增 `terminal_fcf_negative`；`_implied_expectations()` 增基准投影抑制检测并入 note
- 🔧 **`dashboard._implied_section()`（`reporting/dashboard.py`）**：按 `SolverStatus` 枚举渲染新增未解状态 + 终值抑制说明

### 🐛 Fixed
- 🐛 **P0-1**：Brent 失败后 Bisection 未校验有效 bracket → 可能返回「看似正常的 CAGR」（已改为拒绝可疑根）
- 🐛 **P0-2**：求解器默认单调未验证 → 仅凭两端点判断（已改为区间采样 + 多根检测）
- 🐛 **P0-3**：负终值抑制未贯穿 Reverse DCF/期望/渲染 → 仍显示 SOLVED（已改为降级 APPROXIMATE）
- 🐛 **P1-5A**：Revenue CAGR 端点等于目标被疑似「无解」（已允许端点根）
- 🐛 **P1-5B**：常数目标未检测 → 输出无意义隐含值（已加 `FLAT_OBJECTIVE`）
- 🐛 **自查①**：单调性容差误用残差容差（被 \|target\| 放大）→ 单调曲面误判 `NON_MONOTONIC`（已改用 `mono_tol=1e-6·f_span`）
- 🐛 **自查②**：递减方向可达区间 `lo_val/hi_val` 赋值反转 → 递减目标误报「超出约束上界」（已修正）

### 📊 Baseline Verification (Session #18)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **142/142 passed** | 124 → 142（新增 18 用例） |
| 端点根 | ✅ `test_revenue_cagr_exact_upper/lower_boundary` | 端点含容差 → SOLVED，值 = 边界 |
| 无效 bracket | ✅ `test_finish_root_rejects_invalid_bracket` | `value is None` + `NO_SOLUTION_IN_RANGE` |
| 单调性/多根 | ✅ `test_non_monotonic_no_root` / `test_multiple_roots_detected` | 无根 → 无解；2 根 → `MULTIPLE_ROOTS` |
| 常数目标 | ✅ `test_constant_objective_flat` / `_mismatched_target` | `FLAT_OBJECTIVE` / `NO_SOLUTION_IN_RANGE` |
| 负终值降级 | ✅ `TestNegativeTerminalFCFSession18` | SOLVED→APPROXIMATE + note；breakdown/期望透出 |
| round-trip | ✅ FCF margin / WACC / TG 解回代 EV ≈ 目标 EV | AAPL |
| 多股票隔离 | ✅ `TestMultiTickerStateIsolation` | 共享实例 == 新建实例；年限不泄漏 |

---

## [Unreleased] — 2026-11-12 (Session #17 — Reverse DCF 升级为约束式隐含求解器: Implied OM / FCF Margin / WACC / TG)

> 触发：用户 **Phase 2 清单「升级求解器」**（Implied Revenue CAGR / Operating Margin / FCF Margin / WACC / Terminal Growth / Constraint-based Solver），承接 Session #16「问题 2（Reverse DCF 仅反推 Revenue CAGR）/ 问题 4（FCF Margin 非独立变量）」。
> 核心原则：**反解只做单变量 one-at-a-time（其余假设固定为基准）；越界必须「指名绑定边界」而非「静默钳制到边缘」**（ADR-030）。
> 验证：pytest **124/124 passed**（116 → 124，新增 8 用例）；golden 无漂移（隐含驱动未纳入指纹）。

### ✨ Added
- ✨ **约束式单变量求解器 `_solve_implied_scalar()`（`models/reverse_dcf.py`）**：**硬边界**（目标超出 `[lo,hi]` 可达区间 → `SolverStatus.NO_SOLUTION_IN_RANGE` + `note` 指名绑定边界，**绝不钳制**）+ **单调性**（`increasing` 决定可达端）+ **残差检查**（`rel_residual > implied_residual_tol(1e-3)` → `APPROXIMATE`）（ADR-030）
- ✨ **`ImpliedSolve` dataclass**：`value` / `status` / `residual` / `rel_residual` / `bound_lo` / `bound_hi` / `note`——结构化落字段
- ✨ **四个隐含驱动（one-at-a-time）**：`implied_operating_margin`、`implied_fcf_margin`、`implied_wacc`、`implied_terminal_growth`；经 `_implied_expectations()` 组装写入 `breakdown["implied_expectations"]`
- ✨ **flat-margin FCF 桥 `project_enterprise_value_flat_margin()`（`forecasts/fcf_projection.py`）**：`FCF_t = revenue_t × fcf_margin`，绕过 NOPAT/DA/CapEx/NWC 桥——使 FCF margin 成为良定义**独立**求解目标（终值仍走 `gordon_terminal_value()`）
- ✨ **`ReverseDCFConfig` 约束字段（`config.py`）**：`implied_margin_lo/hi`、`implied_fcf_margin_lo/hi`、`implied_wacc_lo/hi`、`implied_tg_lo/hi`、`implied_residual_tol`
- ✨ **透传 + 渲染**：`ImpliedExpectations`（`analysis/expectation.py`）新增 8 字段（4 驱动各含 `*_status`）+ `implied_constraint_notes`；`reporting/dashboard.py::_implied_section()` 渲染（含「不可解（超出约束区间）」与「_(近似)_」）
- ✨ **测试 8 用例**：`tests/test_reverse_dcf.py::TestConstraintSolver`（5）+ `TestImpliedExpectationsPhase2`（3）

### 🔧 Changed
- 🔧 `models/reverse_dcf.py`：`calculate()` 在解出营收 CAGR 后调用 `_implied_expectations(...)` 写入 breakdown（深负 FCF 无解时以规范化 CAGR 为基准）
- 🔧 `analysis/expectation.py`：`implied_expectations()` 从 breakdown 透传四驱动 `value`/`status` 与约束 note

### 📊 Baseline Verification (Session #17)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **124/124 passed** | 116 → 124（新增 8 用例） |
| 越界不钳制 | ✅ `TestConstraintSolver::test_target_above/below_range_is_not_clamped` | `value is None` + note 指名「上界」/「下界」 |
| 单调性 | ✅ 线性增/减两向求解命中解析解 | `increasing=True/False` |
| 利差约束 | ✅ `test_wacc_and_tg_respect_spread_constraint` | `implied_wacc.bound_lo ≥ tg+spread`；`implied_tg.bound_hi ≤ wacc−spread` |
| round-trip | ✅ OM 解回代 EV 与目标 EV 残差 ≤ tol | AAPL |
| 渲染证据 | ✅ AAPL 四驱动全解；NBIS 四驱动全 `NO_SOLUTION_IN_RANGE` | 无钳制、口径由引擎枚举驱动 |

---

## [Unreleased] — 2026-11-12 (Session #16 — 估值引擎诚实性与一致性: 负终期 FCF 抑制 + 预测年限单一真源 + 求解器残差检查)

> 触发：用户对 `forecasts/fcf_projection.py` 与 `models/reverse_dcf.py` 的代码审查（4 项发现，Phase 1「修复现有引擎」）。核心原则：**引擎不得为了让估值「好看」而伪造输入；口径与年限必须同源，禁止静默状态污染**（ADR-028/029）。
> 验证：pytest **116/116 passed**（106 → 116，新增 10 用例）；golden 基线因负终值抑制重生成（仅 NBIS.median_value 漂移，已审阅）。

### ✨ Added
- ✨ **统一 Gordon 入口 `gordon_terminal_value()`（`forecasts/fcf_projection.py`）**：返回 `TerminalValueResult`（`terminal_value` / `pv_terminal_value` / `suppressed` / `inflated` / `note`）——终期 FCF ≤ 0 时**抑制**（不翻转符号），返回显式期现值下限（ADR-028）
- ✨ **终值抑制信号 `terminal_fcf_negative`**：`FcfProjectionResult` 与 DCF `breakdown` 新增该字段；抑制时状态固定 `SolverStatus.APPROXIMATE`，note 明示「需明确转型假设」
- ✨ **预测年限单一真源 `config.resolve_forecast_horizon(business_type)`**：DCF/ReverseDCF/Scenario/Sensitivity/MonteCarlo/Expectation 全链路统一取年限（ADR-029）
- ✨ **求解器残差检查（`models/reverse_dcf.py`）**：`brentq` 解后计算 `rel_resid = |f(root)| / |target_ev|`，`> 1e-3` → 标记 APPROXIMATE + note（EV 曲面平坦的多解风险显式化）
- ✨ **`MIN_WACC_TG_SPREAD = 0.005`**：统一 WACC−g 下限常量（替代散落的 `1e-3`/`1e-4`）
- ✨ **测试 10 用例**：`tests/test_dcf.py::TestTerminalValueHonesty`（6）+ `tests/test_reverse_dcf.py::TestHorizonIsolation`（4）

### 🔧 Changed
- 🔧 `forecasts/fcf_projection.py`：`project_enterprise_value()` 改调 `gordon_terminal_value()`，删除原「负 FCF → abs 均值」符号翻转逻辑
- 🔧 `models/dcf.py`：`_pv_calculations()` / `_pv_tv_only()` 统一改调 `gordon_terminal_value()`（消除三处重复翻转）；`forecast_horizon` 参数降级为一次性 override（`self._horizon_override`）+ 新增 `_resolve_horizon(profile)`；breakdown 增 `terminal_fcf_negative`
- 🔧 `models/reverse_dcf.py`：**删除 `self.horizon = int(horizon)` 污染源**，`calculate()` 内解析局部 `horizon = self._resolve_horizon(profile)`；`_project_ev` / `_solve_revenue_cagr` / `_normalized_growth_solve` 签名新增 `horizon: int`
- 🔧 `simulation/monte_carlo.py` / `analysis/scenario.py` / `analysis/sensitivity.py` / `analysis/expectation.py`：均改经 `resolve_forecast_horizon(business_type)` 取年限，不再各自回落本地常量

### 🐛 Fixed
- 🐛 **问题 1（数学 / 高优先级）**：负终期 FCF 曾被 `last_fcf = avg_abs` 偷改成正数后进入 Gordon → 为持续烧钱公司**伪造正终值**（Normal DCF / Reverse DCF / Monte Carlo 三处）。修复后终值抑制 + `terminal_fcf_negative` 显式标注
- 🐛 **问题 3（代码风险）**：`ReverseDCFModel` 共享单例被 `self.horizon = ...` 跨标的污染（SaaS 7 → Utilities 10 → Unknown 沿用 10）。修复后实例不再持有 `horizon` 状态
- 🐛 `analysis/risk.py::_terminal_value_risk()`：新增 `terminal_fcf_negative=True` → **HIGH** 级旗标分支（抑制后 `tv_percent_of_ev=0`，原阈值检测不会触发，导致旗标丢失）

### 📊 Baseline Verification (Session #16)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **116/116 passed** | 106 → 116（新增 10 用例） |
| 负终值抑制证据 | ✅ NBIS `terminal_fcf_negative=True`、`pv_terminal_value=0.0`、status=Approximate | 终期 FCF `[-3.7B … -10.4B]` 全负 |
| 年限隔离证据 | ✅ `TestHorizonIsolation`：断言 `not hasattr(model, "horizon")`；按类型解析 + override 生效 | SaaS=7 / Utilities=10 / Unknown=5 |
| 符号翻转消除 | ✅ `fcf_projection.py` / `dcf.py` 两处均改调 `gordon_terminal_value()` | 无残留 `abs(...)` 翻转逻辑 |
| golden 基线 | ℹ️ 有意漂移 1 字段：`NBIS.median_value: 12.76 → 10.46` | 旧值即由伪造正终值虚高而来（已审阅） |

---

## [Unreleased] — 2026-11-12 (Session #15 — UPST 递归自我改进 3 轮: 分类子串误匹配 + 金融 EV/Sales 剔除 + 渲染层口径泄漏)

> 方法：以 **UPST（Upstart Holdings，消费信贷 FinTech）** 为标的执行「上一轮产出（报告 + 指纹）作为下一轮起点」的递归工作流，round1 → round2 → round3；每轮 `python _recursion_run.py UPST roundN --real` + 全量 `pytest`。统一原则（ADR-019/022/024）：**同页矛盾要命名不要掩盖；口径 = 引擎输出契约，渲染层禁止猜口径**。
> 验证：pytest **106/106 passed**（95 → 106）；UPST round1/2/3 `check_invariants()` DEFECTS 均为 `[]`。

### ✨ Added
- ✨ **边界感知关键词匹配 `keyword_hit()`（`classification/ml_classifier.py`）**：裸 ASCII ≤4 字符 token 强制词边界 `(?<![a-z0-9])kw(?![a-z0-9])`；长词/带空格/CJK 保留原子串语义（ADR-026）
- ✨ **递归产出 4 轮工件**：`_recursion_upst_round0..3.txt`（round0 为修复前基线）

### 🔧 Changed
- 🔧 `classification/classifier.py`：`_model_applicability()` 金融分叉新增 `EV/Sales` 剔除（`na_reasons`「EV embeds funding debt」），与 `EV/EBITDA`/`FCF Yield` 同族（ADR-027）
- 🔧 `reporting/verdict_intuition.py`：公允区间「股数不可靠」附注改为读 `build_caliber_contract(profile)`——金融标的给「P/B、P/E、RIM 复核」（ADR-027）
- 🔧 `reporting/dashboard.py`：`_risk_section(rr, profile)` 按 `DiscountCaliber.COST_OF_EQUITY` 把 `WACC Risk` 重标「Cost of Equity Risk」；`_market_section()` β 附注「WACC 统一采用截断值」→ 中性「折现率」；`build_report` 调用点同步传 `profile`（ADR-027）

### 🐛 Fixed
- 🐛 **Round 1（分类子串误匹配）**：工业关键词 `"ups"`（UPS 快递）子串误匹配 ticker `upst` → `Structural FORCE->Industrial` 覆盖 FinTech → 走 DCF/EV-EBITDA/FCF-Yield（对借贷型无意义），DCF=$0.00、ReverseDCF 无解、情景三档全 $0.00。修复后 UPST 分类 FinTech（p=99.1%），路由 `Bank DDM/Bank RIM/P/E/P/B`
- 🐛 **Round 2（金融 EV/Sales 剔除）**：round1 报告同页矛盾——市场区打印「EV N/M（金融机构不适用）」却仍用 `EV/Sales` 作锚（$42.16，区间唯一离群值）。修复后一致性 Very Weak → **Moderate**，离散度 316% → **36.2%**，中位估值 raw==weighted（$9.61）
- 🐛 **Round 3（渲染层口径泄漏，违 ADR-022/024）**：① 公允区间附注硬编码「以 EV 口径复核」→ 读契约分支；② 风险区把 `RiskType.WACC` 原样渲染为「WACC Risk」而口径为 `ke` → 重标「Cost of Equity Risk」；③ 市场区 β 附注硬编码「WACC」→ 「折现率」

### 📊 Baseline Verification (Session #15)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **106/106 passed** | 行为修复零回归（AAPL/XOM/JPM/PLD/AMT 分类不变） |
| `check_invariants()` (UPST round1/2/3) | ✅ **DEFECTS 均为空** | round0 基线亦为空（缺陷不在自动不变性覆盖内） |
| 分类修复证据 | ✅ `PROFILE business_type: FinTech`（p=99.1%），`Bank DDM/RIM` 适用 | 修复前 `INDUSTRIAL HITS: ['ups']` → `Structural FORCE->Industrial` |
| 一致性改善证据 | ✅ Very Weak → **Moderate**（离散度 316% → 36.2%） | `_recursion_upst_round1.txt` → `round2.txt` |
| 口径泄漏修复证据 | ✅ `建议以 P/B、P/E、RIM（残差收益）口径复核` / `Cost of Equity Risk（权益成本/β）` / `折现率` | `_recursion_upst_round3.txt:5,52,151` |
| 非金融未误伤证据 | ✅ AAPL/XOM 保留 `EV/Sales`；JPM/AMT 不含 | 变更金融分叉作用域内 |

---

## [Unreleased] — 2026-11-03 (Session #14 — 口径契约化 + 封顶审计系统化 + 渲染层口径冲突 invariant + 金融运营情景)

> 方法：落实 Session #13 收尾提出的 5 项优化（口径契约、M-15 封顶审计、M-12 invariant、M-16 数据驱动、金融情景深化）。核心思想：**口径 = 引擎输出的枚举契约，渲染层只按契约分支，禁止猜口径**。
> 验证：全量 pytest **95 passed**；SOFI / JPM round3 `DEFECTS: []`；golden 基线因新增指纹字段重生成（已审阅的有意漂移）。

### ✨ Added
- ✨ **口径契约模块 `valuation/caliber.py`（新建）**：`MetricMeaning`（MEANINGFUL / REFERENCE_ONLY / NOT_MEANINGFUL）+ `DiscountCaliber`（WACC / ke）+ `CaliberContract` + `build_caliber_contract(profile)`。把「某指标对某类标的有/无意义」从渲染层内联 `if profile.is_financial_institution` 提升为引擎输出契约（唯一真相来源）
- ✨ **封顶审计测试 `tests/test_cap_boundary_guard.py`（新建）**：Part A 常量守卫闭区间断言；Part B 自动扫描「同一文件内 min/max 封顶字面量 ∩ 严格比较字面量」并强制人工审阅；Part C **跨文件** confidence 封顶守卫断言（覆盖「classifier 封顶、models 判定」的跨文件 ADR-023）
- ✨ **hybrid 阈值锁定测试 `tests/test_hybrid_threshold_lock.py`（新建）**：锁定 `HYBRID_FIN_TO_TECH_FLOOR=0.08` 并断言检测器仅在 `>= floor` 时翻转（闭区间边界）
- ✨ **golden 指纹新增口径字段**：`caliber` / `scenario_calibers`（19 → 21 字段）
- ✨ **`check_invariants()` 新增 invariant #6**：情景口径（`discount_label`）必须等于引擎口径，否则报 `main model / scenario disagreement`——把 Session #13 Round 2 需人工通读才能发现的矛盾变为**自动化断言**

### 🔧 Changed
- 🔧 `reporting/dashboard.py`：`_market_section()` 删除内联 `is_fin`/`is_reit` 猜口径逻辑，改由 `build_caliber_contract(profile)` 消费（EV / Net Debt / EV/EBITDA / FCF 的 N/M 与附注全部来自契约）；`_sensitivity_section()` 按契约 `sensitivity_applicable` 分支
- 🔧 `analysis/scenario.py`：金融分叉由 `contract.discount is DiscountCaliber.COST_OF_EQUITY` 驱动（替代硬编码 `is_financial_institution`）；金融情景升级为 **ke + 经营性 ROE 双驱动**（新增 `_FIN_ROE_SHOCK=0.20`）
- 🔧 `models/bank.py`：`BankRIMModel` 支持 `roe_override`（经营性驱动，代表净息差/信用成本），`breakdown` 新增 `roe_source`（`ttm` / `scenario_override`）
- 🔧 `classification/ml_classifier.py`：hybrid 阈值提为具名常量 `HYBRID_FIN_TO_TECH_FLOOR=0.08`（M-16，锁定而非下调）

### 🐛 Fixed
- 🐛 **跨文件 ADR-023：SOTP 置信度守卫漏检** → `models/sotp.py:57,70` 的 `conf < 0.55`：上游 `classification/classifier.py:509` 会把 confidence 封顶到**恰好 0.55**（sector/industry 缺失），严格 `<` 使被降级的分类被当作高置信。改为 `conf <= 0.55`（闭区间）。由新增 `test_confidence_cap_guards_use_closed_interval` 锁定

### 📊 Baseline Verification (Session #14)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **95/95 passed** | 新增 3 个测试文件（封顶审计 / hybrid 锁定 / 口径） |
| `check_invariants()` (SOFI / JPM round3) | ✅ **DEFECTS 均为空** | 含新 invariant #6 |
| golden 基线 | ✅ 已重生成 | 仅新增 `caliber`/`scenario_calibers` 两字段漂移（`golden=None → live`），无其它字段变化 |
| 口径一致证据 | ✅ SOFI / JPM `caliber='ke'` == `scenario_calibers=['ke']` | 主模型与情景同基 |
| 金融运营情景证据 | ✅ `情景驱动：折现率 ke ↑（β+0.30） + 经营性 ROE ↓（6.07%→4.85%）` | `_recursion_sofi_round3.txt:94` |
| 封顶审计证据 | ✅ Part A/B/C 全绿；Part C 捕获并修复 sotp.py 跨文件漏检 | `tests/test_cap_boundary_guard.py` |

---

## [Unreleased] — 2026-11-03 (Session #13 — SOFI 递归自我改进 3 轮: 银行 β/ke 口径统一 + 金融情景口径 + peer 置信度边界)

> 方法：以 **SOFI（SoFi Technologies，银行 / 金融科技）** 为标的，执行「上一轮产出（报告 + 指纹）作为下一轮起点」的递归工作流，共 3 轮（round1 → round2 → round3）；每轮跑 `_recursion_run.py SOFI roundN --real` + 全量 pytest。
> 统一原则（Decision 019 / 021）：**矛盾要命名不要掩盖；口径要同基不要混用；派生量要结构化**。金融标的一律走 `is_financial_institution` 单一分叉点（Decision 008 / ADR-008）。

### ✨ Added
- ✨ **金融标的专属情景路径**：`analysis/scenario.py::ScenarioAnalyzer._run_financial_scenarios()` —— 金融机构（银行/保险）的 Bear/Base/Bull 不再用 DCF（FCF / 净债务 / EV / WACC 对借贷型业务无定义），改由**适配主模型 Bank RIM** 沿 `ke`（基准 β ± `_FIN_BETA_STEP=0.30`）生成；`ScenarioValuation.assumptions` 携带 `discount_label="ke"` + `cost_of_equity`
- ✨ **金融机构敏感性守卫**：`reporting/dashboard.py::_sensitivity_section(profile)` 对金融标的直接返回「金融机构（银行/保险）不适用 DCF 敏感性矩阵…」说明文案，替换会与银行主模型冲突的 WACC×g 矩阵

### 🔧 Changed
- 🔧 `models/bank.py`（Round 1）：Bank DDM/RIM 统一经单一 β 出口 `resolve_effective_beta()` 取 β（winsorized [0.30, 2.50]），Rf/ERP 与 WACC / 情景路径同源 → 银行孪生模型的 CAPM `ke` 不再与全报告其它区口径撕裂；新增 `_BANK_KE_BAND=(7%, 10%)` 越界提示
- 🔧 `reporting/dashboard.py`（Round 2）：`_scenario_section()` 按 `assumptions.discount_label` 分支渲染——`ke` 显示「— ke 17.0% (Bank RIM)」，否则维持「— WACC x% / g y%」
- 🔧 `models/multiples.py`（Round 3）：peer 倍数置信度下界提为模块常量 `_PEER_MULTIPLE_CONF_FLOOR = 0.55`，并将两处严格 `conf < 0.55` 改为 `conf <= 0.55`

### 🐛 Fixed
- 🐛 **Round 1：银行模型与全报告 β / ke 口径不统一** → Bank DDM/RIM 经统一出口取 β，`ke` 与风险旗标 / 市场区一致（SOFI `ke=15.39%`，β=2.07）；修复前银行模型可能读不同 β 或默认 ke，与市场区/WACC 自相矛盾
- 🐛 **Round 2：金融标的情景口径与主模型方向矛盾** → round1 报告里情景为 DCF 口径（WACC 15.1%，$12.61~15.94）而主模型 Bank RIM 给 $9.52，两个口径方向相反却**未命名**。修复后情景亦走 Bank RIM：熊市 $9.26（ke 17.0%）/ 基本面 $9.52（ke 15.4%）/ 乐观 $9.79（ke 13.7%），三档跨度收窄至 **6% SV**，与中位锚点同基
- 🐛 **Round 3：peer 倍数置信度边界漏检** → SOFI 分类置信度被「sector/industry 缺失」截断到**恰好 0.55**，而守卫用严格 `< 0.55` → P/E、P/B 未标 `NOT FULLY VALIDATED`，把 55% 置信的银行 peer 倍数当作已验证。改为 `<=` 后两项均标注警告；质量因子 1.00 → **0.67**、一致性 Moderate → **Weak**（门控 CV 24.5% → 36.7%，为真实信号，非调参）

### 📊 Baseline Verification (Session #13)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **90/90 passed** | 每轮后各跑一次，零回归 |
| `check_invariants()` (SOFI 3 轮) | ✅ **DEFECTS 均为空** | round1 / round2 / round3 |
| golden 基线 | ✅ 已重生成 | `UPDATE_GOLDEN=1` —— JPM `median_value 111.27→151.37` / `median_value_weighted 59.02→139.22`（Bank RIM 现为真正残差收益模型，**已审阅的有意漂移**） |
| Round 1 修复证据 | ✅ `Bank RIM value = $9.52/share = book value $11.23 + PV of residual income $-1.71 (β=2.07, ke=15.39%)` | `_recursion_sofi_round1.txt:85` |
| Round 2 修复证据 | ✅ 情景由 DCF `12.61~15.94` → Bank RIM `9.26 → 9.52 → 9.79`（跨度 22% → 6% SV）；敏感性区替换为金融说明文案 | `_recursion_sofi_round2.txt:4,126` |
| Round 3 修复证据 | ✅ `⚠️ Peer multiple NOT FULLY VALIDATED … Classification confidence = 55%`；质量因子 1.00→0.67 | `_recursion_sofi_round3.txt:72,142` |
| 跨标的回归 | ✅ JPM round3 DEFECTS 为空 | 情景同走 Bank RIM（$135.28 / $139.22 / $143.36）；JPM 置信度 100% 故 peer 无警告 |

---

## [Unreleased] — 2026-11-03 (Session #12 — CRWV 递归自我改进 3 轮: 原型重路由 + 口径冲突命名 + 派生态结构化)

> 方法：以 **CRWV（CoreWeave，AI/Cloud neocloud 建设期）** 为新画像标的，严格执行「上一轮产出（报告+指纹）作为下一轮起点」的递归工作流，共 3 轮；每轮后跑 `_recursion_run.py` + pytest，全量 **90/90**。
> 统一原则（Decision 019）：**矛盾要命名不要掩盖；口径要同基不要混用；派生量要结构化不要埋在注释**。

### ✨ Added
- ✨ **`_recursion_run.py`（新建）**：递归驱动脚本——`run_pipeline(ticker)` → `render_report()` 落盘 `_recursion_<ticker>_<label>.txt`，打印 fingerprint 与 `check_invariants()` 缺陷清单（4 轮复用）
- ✨ **CRWV 合成 fixture**：`data/providers.py` `SYNTHETIC_DATA["CRWV"]`（price 75 / shares 480M / capex TTM 7.6B / FCF TTM −8.8B / debt 9B / β 2.60）——enable 递归管线在确定性离线数据上跑「重资本高增长亏损期」标的
- ✨ **口径冲突检测 caveat**：`reporting/verdict_intuition.py::build_valuation_verdict()` 新增「Median-vs-scenario SIGN conflict」——中位口径与 DCF 基准情景方向相反时显式命名（不做平均）
- ✨ **来源标记字段**：`analysis/expectation.py` 的 `ImpliedExpectations` / `ExpectationGap` 新增 `implied_revenue_cagr_source`（区分「直接求解」vs「成熟稳态推导」）

### 🔧 Changed
- 🔧 `classification/classifier.py`（Round 1）：规则分类路径新增 `ASSET_LIGHT_CONFLICT_CAPEX_RATIO=1.0` + `ASSET_LIGHT_TYPES` + ISSUE #1b 块（**对齐 `ml_classifier.py`**）→ 重资本建设期标的确定性重路由 `AI/Cloud Infrastructure`（`effective_business_type` + `business_type_conflict_note`）
- 🔧 `reporting/dashboard.py`（Round 1）：`_business_section()` hybrid 分支补渲染 `→ **估值原型重路由: …**`
- 🔧 `models/reverse_dcf.py`（Round 3）：`_normalized_growth_solve()` 的隐含营收 CAGR 现写入 `breakdown["implied_revenue_cagr"]` + `implied_revenue_cagr_source="normalized_growth_solve"`
- 🔧 `reporting/dashboard.py`（Round 3）：`_implied_section()` / `_gap_section()` 标注「成熟稳态经济推导，APPROXIMATE」

### 🐛 Fixed
- 🐛 **Round 1：报告头 `MatureTech / SaaS` 与 peer 区 `AI/Cloud Infrastructure` 自相矛盾** → 根因：规则分类路径（离线/golden 走这条）漏实现「资产轻原型冲突」判定；修复后头行显示 `→ **估值原型重路由: AI/Cloud Infrastructure**`
- 🐛 **Round 2：一句话结论内部矛盾（中位判显著高估 vs DCF 基准 $138.57 反判低估）未命名** → 新增 caveat 显式命名并归因（DCF 终值主导已被降权/剔除），**不做平均**
- 🐛 **Round 2（自持 bug）：caveat 基期口径错误** → "高于当前价 X%" 误用 base-relative `(price−base)/base`，修正为 price-relative `(base−price)/price`（85% 而非 46%）
- 🐛 **Round 3：结构化字段与正文自相矛盾** → 隐含营收 CAGR 仅在 free-text note（≈26%）而字段显示 `N/A` → 落结构化字段，字段与 note 一致
- 🐛 **Round 3：`_gap_section` 方向文案 bug** → `direction` 变量被计算却未插值，恒输出「高出」；现按符号输出「高/低」（CRWV：`比历史水平低 429.9 个百分点`）

### 📊 Baseline Verification (Session #12)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **90/90 passed** | 每轮后各跑一次，零回归 |
| `check_invariants()` (4 轮) | ✅ **DEFECTS 均为空** | Round 0/1/2/3 |
| CRWV 模型分桶 | ✅ 适用 7 · 解算 6 · 失败 1 · 合计 10 | 覆盖恒等式成立 |
| CRWV 覆盖率（两条腿） | ✅ `Replacement NAV $6.87` + `EV/Sales (Unit Econ) $5.89` | 重资本建设期两条腿均适用 |
| Round 1 修复证据 | ✅ `→ **估值原型重路由: AI/Cloud Infrastructure**` | `_recursion_crwv_round1.txt:25` |
| Round 2 修复证据 | ✅ `⚠️ 口径冲突：…DCF 基准情景 $138.57 高于当前价 85%` | `_recursion_crwv_round2/3.txt:9` |
| Round 3 修复证据 | ✅ `隐含营收 CAGR: 26.4% _(成熟稳态经济推导，APPROXIMATE)_` | `_recursion_crwv_round3.txt:168` |

---

## [Unreleased] — 2026-11-03 (Session #11 — 覆盖率第二条腿: EV/Sales + 单位经济学模型族)

> 方法：延续 Session #10「覆盖率不足应引入适配模型族，而非降权规避」原则。上轮 Replacement NAV 补齐**资产基础锚**（第一条腿），本轮补上经济含义**正交**的 **earnings-power 锚**（第二条腿）。
> 每项改动后跑 pytest；最终全量 **90/90**（78 → 90，+12 用例）并刷新 golden 基线。

### ✨ Added
- ✨ **EV/Sales + 单位经济学模型族 → `models/unit_economics.py`（新建）**
  - `UnitEconomicsSalesModel`：`deployed_capital = Σcapex − ΣD&A`；`capacity_revenue = max(TTM营收, deployed_capital × BENCHMARK_REVENUE_YIELD)`；`EV = capacity_revenue × MATURE_EV_SALES × ramp_discount`
  - `utilisation_gap = clamp(1 − current_yield/benchmark_yield, 0, 1)`；`ramp_discount = (1+WACC)^−(RAMP_YEARS × utilisation_gap)`
  - `MIN_CAPEX_RATIO=0.50` / `BENCHMARK_REVENUE_YIELD=0.35` / `MATURE_EV_SALES=4.0` / `RAMP_YEARS=3.0` + 敏感性 `_SENSITIVITY_YIELDS=(0.25,0.35,0.50)` × `_SENSITIVITY_RAMP_YEARS=(2.0,3.0,5.0)`
  - breakdown 暴露 deployed_capital / current_revenue_yield / benchmark_revenue_yield / capacity_revenue / utilisation_gap / effective_ramp_years / ramp_discount / wacc / enterprise_value / net_debt / equity_value / implied_ev_sales / sensitivity
  - `applicability_check()`：排除金融/REIT；要求 shares + 正营收；`capex/revenue ≥ 0.50`；`Σcapex − ΣD&A > 0`；且为 build-out（负 FCF 或亏损或 High Growth）
- ✨ **测试**：`tests/test_unit_economics.py`（12 测试：路由 4 / 解算 3 / 覆盖率提升 2 / 敏感性方向 2 / 适用性守卫 1）

### 🔧 Changed
- 🔧 `config.py`：`ModelName` 新增 `UNIT_ECON_SALES = "EV/Sales (Unit Econ)"`
- 🔧 `models/router.py` / `models/__init__.py`：注册并导出 `UnitEconomicsSalesModel`
- 🔧 `classification/classifier.py`：`ALL_MODELS` 扩列 + `_model_applicability()` 动态追加 Unit Economics + 新增 `_is_unit_economics_candidate()`
- 🔧 `tests/golden/report_fingerprints.json`：`UPDATE_GOLDEN=1` 重生成基线（NBIS：`n_total=10` / `n_applicable=7` / `n_solved=6` / `agreement_level="Very Weak"` / `median_value=12.76` / `median_value_weighted=11.13`）

### 🐛 Fixed
- 🐛 **Session #11：重资本建设期标的仅靠资产锚（Replacement NAV）单腿支撑，缺 earnings-power 视角** → 新增正交的单位经济学 EV/Sales 锚，**NBIS 覆盖率 5/6 → 6/7**（不再是单腿；不靠降权规避）
- 🐛 **Session #11（诚实性）：无 GPU 稼动率/ARPU 明细字段时容易硬凑 SOLVED** → 模型固定返回 `APPROXIMATE`（永不 SOLVED）+ notes 标注「派生代理 / 方向性参考」，杜绝虚假精度

### 📊 Baseline Verification (Session #11)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **90/90 passed** | 78 → 90（新增 12 用例） |
| golden 整篮 9 只 | ✅ **defects 为空** | AAPL/MSFT/NVDA/JPM/PLD/NOW/NBIS/AMT/XOM |
| NBIS 覆盖率 | ✅ **5/6 → 6/7** | 模型分桶「适用 7 · 解算 6 · 失败 1 · 合计 10」 |
| NBIS 单位经济学锚 | ✅ `EV/Sales (Unit Econ): $27.02` | 隐含当期 EV/Sales ≈ 36.7x；资产基础产品率 2.48% vs 成熟基准 35% |
| NBIS 一致性 | 🟡 **Weak → Very Weak** | 新增居中模型抬高 IQR 上界 → 极端 DCF 重回样本（离散度 247.5%）；**真实信号，非缺陷，不调参规避** |
| 诚实性 | ✅ 固定 APPROXIMATE | 派生代理（无稼动率/ARPU 明细字段）+ notes 方向性标注 |

---

## [Unreleased] — 2026-11-03 (Session #10 — 五项系统优化: 覆盖率锚 + 对账反向校验 + Golden diff + Beta 统一 + REIT/Energy)

> 方法：承接 Session #08（NBIS）/ #09（JNJ）递归自我改进的沉淀，针对用户列出的 5 项系统性短板一次性落地。
> 每项改动后跑 pytest；最终全量 **78/78**（61 → 78，+17 用例）并产出 golden 整篮 9 只回归（defects 为空）。

### ✨ Added
- ✨ **Replacement-cost NAV 模型族 → `models/replacement_nav.py`（新建）**
  - `ReplacementNAVModel`：资产基础锚 `equity = book_equity + net_ppe×(factor−1)`（`net_ppe = Σcapex − ΣD&A`，缺 book_equity 时回退 `replacement_ppe − net_debt`）
  - `DEFAULT_REPLACEMENT_FACTOR=1.15`（在建/重估溢价）+ `_SENSITIVITY_FACTORS=(1.00, 1.10, 1.15, 1.25, 1.40)`；breakdown 暴露 accumulated_capex / accumulated_da / net_ppe / replacement_ppe / basis / sensitivity
  - `applicability_check()`：排除金融/REIT；要求 shares；要求 `capex/revenue ≥ MIN_CAPEX_RATIO(0.30)`；要求 `net_ppe > 0`；要求「负 FCF 或亏损或 High Growth」
- ✨ **对账层写侧反向校验 → `data/reconciliation.py`**
  - `OverrideRecord`（field/provider_value/internal_value/rel_diff/unit/reason/applied）+ `OverrideLog`（records/applied/n_applied/to_lines）
  - `_OVERRIDE_FIELDS` 白名单 + `_OVERRIDE_TOLERANCE=0.25` + `apply_overrides()`
  - 股数守卫：偏差 >25% 但市值恒等式自洽 → 仅标注；恒等式被破坏 → 按市值/价格反推
- ✨ **golden report diff 回归工程化**
  - `tests/golden_report.py`（新建）：`BASKET` 9 只（AAPL/MSFT/NVDA/JPM/PLD/NOW/NBIS/AMT/XOM）+ `run_pipeline()` + `build_fingerprint()`（19 稳定字段）+ `check_invariants()`（5 类自相矛盾）+ `render_report()`
  - `tests/test_golden_report.py`（新建，3 测试）：invariants hold / coverage identity explicit / golden fingerprint matches（`UPDATE_GOLDEN=1` 刷新基线）
  - `tests/golden/report_fingerprints.json`（新建）：9 只标的 golden 指纹基线
- ✨ **Beta 单一出口 → `valuation/wacc.py::resolve_effective_beta()`**
  - 按优先级 `wacc_breakdown → provider(winsorized) → fallback` 解析，返回带 `origin` 的可审计对象
- ✨ **资产结构覆盖 fixtures**
  - `data/providers.py`：`SYNTHETIC_DATA` 新增 NBIS（AI/Cloud 建设期）/ AMT（tower REIT）/ XOM（Energy）
  - `tests/conftest.py`：新增 `_load()` + fixtures `nbis_data`/`amt_data`/`xom_data`/`amt_profile`/`xom_profile`
- ✨ **测试**：`tests/test_reconciliation_override.py`（6 测试）+ `tests/test_asset_structure_coverage.py`（8 测试）

### 🔧 Changed
- 🔧 `config.py`：`ModelName` 新增 `REPLACEMENT_NAV`
- 🔧 `models/router.py` / `models/__init__.py`：注册并导出 `ReplacementNAVModel`
- 🔧 `classification/classifier.py`：`ALL_MODELS` 扩列 + `_model_applicability()` 末尾动态追加 Replacement NAV + 新增 `_is_replacement_nav_candidate()`
- 🔧 `data/models.py`：`FinancialData` 新增 `reconciliation_overrides` 字段
- 🔧 `data/validator.py`：`_check_reconciliation()` 调用 `apply_overrides()` 并挂载 OverrideLog + 写 restatement_notes
- 🔧 `reporting/dashboard.py`：`_data_section()` 渲染「🩹 对账自动修正（偏差 > 25% 时改用内部推算值）」

### 🐛 Fixed
- 🐛 **Session #10 #1（最大短板）：NBIS 覆盖率仅 2/3**（DCF 负 FCF 近乎失效、P/E 1205x 不适用、EV/EBITDA D&A 拉爆）→ 新增 Replacement NAV + 动态入桶，**覆盖率 2/3 → 5/6**（不再靠降权规避）
- 🐛 **Session #10 #2：对账层只标记不修正，下游仍读到污染基数** → 新增写侧 `apply_overrides()`（偏差 >25% 自动改用内部推算值并标注）+ 审计链（PLD 实测：EV $179B→$302B、P/E 33.00→90.65 自动修正）
- 🐛 **Session #10 #3：自改进靠人工读报告找矛盾，不可扩展** → golden report diff（19 字段指纹 + 5 类 invariant + 基线 diff）
- 🐛 **Session #10 #4：β 在市场区/风险旗标/WACC 三处各读不同口径** → 统一为 `resolve_effective_beta()` 单一出口 + golden invariant 断言
- 🐛 **Session #10 #5：REIT（AMT）/ Energy（XOM）资产结构缺端到端回归** → 新增 fixtures + `test_asset_structure_coverage.py`（AMT REIT NAV 4/4；XOM Energy 5/5 Strong）

### 📊 Baseline Verification (Session #10)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **78/78 passed** | 61 → 78（新增 17 用例：6 + 8 + 3） |
| golden 整篮 9 只 | ✅ **defects 为空** | AAPL/MSFT/NVDA/JPM/PLD/NOW/NBIS/AMT/XOM |
| NBIS 覆盖率 | ✅ **2/3 → 5/6** | Replacement NAV $11.13；模型分桶「适用 6 · 解算 5 · 失败 1 · 合计 9」 |
| PLD 对账自动修正 | ✅ 渲染正常 | 「🩹 对账自动修正」：EV $179B→$302B（−40.7%）、P/E 33.00→90.65（−63.6%） |
| AMT (REIT) | ✅ `is_reit=True` | REIT NAV 4/4；override_applied=[滚动 P/E] |
| XOM (Energy) | ✅ `business_type=="Energy"` | 5/5 Strong；β_effective 0.90 |

---

## [Unreleased] — 2026-11-03 (Session #09 — JNJ 递归自我改进 3 轮: 分桶算术 + 对账口径语义 + 风险展示诚实性)

> 方法：以 JNJ（成熟高股息医药巨头，与 NBIS 完全对立的画像）为标的，
> **上一轮报告作为下一轮改进的起点**，连续迭代 3 轮。每轮均以
> `pytest 61/61` + 端到端重跑验证，并做 NBIS / SOFI / AAPL / JPM 回归。

### 🐛 Fixed
- 🐛 **Round 1 — 模型分桶算术不自洽 + ReverseDCF 双重身份**
  - 根因：`analyze()` 用 `n_total = len(results)` 计入 ReverseDCF，却用 `_EXCLUDED_FROM_MEDIAN` 将其从 `solved` 中 `continue` 掉，且未计入 `not_applicable` / `failed` → 出现 `适用 6 · 解算 5 · 失败 0 · 合计 6`（5+0+0≠6）以及**虚假**告警 `1 of 6 applicable models failed`（实际无模型失败），并让覆盖标签误显示「模型基本可用（5/6 已解算）」
  - 修复：`analysis/model_agreement.py` 新增 `n_display_only` / `display_only_models` 第四桶，`n_applicable = n_total − n_not_applicable − n_display_only`，使 `适用 = 解算 + 失败` 恒等成立；虚假 failed 告警改为按真实 `len(failed)` 触发（JNJ/AAPL 下不再出现）
  - `reporting/dashboard.py`：ReverseDCF 在估值列表中由误导性的 `[估值合理]`（其「估值」＝当前价，恒等）改标为 `（反向求解＝当前价，非独立估值）`；模型分桶行显示 `合计 6（含 1 个仅展示，不计入统计）`
- 🐛 **Round 2 — 对账把「GAAP vs 调整后 EPS 口径差」误判为「盈利基数极不稳定」**
  - 根因：`data/reconciliation.py` 的 `滚动 P/E ≈ 价格/TTM EPS` 检查用静态文案「盈利基数极不稳定，P/E 不可作为估值锚」。JNJ 供应商 P/E 26.38x vs 其自身 TTM EPS 隐含 43.94x（−40%）实为**调整后（non-GAAP）/正常化 EPS** 与 GAAP 口径差（几乎所有大盘股都有），并非盈利不稳定
  - 修复：改为**方向感知**文案——供应商 P/E 低于价格/GAAP-EPS 隐含值 → 判定为 non-GAAP/正常化口径差异；高于 → 判定为旧口径/摊薄股数或盈利下滑。JNJ 现输出「通常为『调整后（non-GAAP）/正常化 EPS』差异（非盈利不稳定）；两种口径不可混用」
- 🐛 **Round 3 — FCF Yield Gap 风险语义误报 + Beta 展示不一致**
  - 根因 A：`analysis/risk.py` 的 `FCF Yield Gap` 用 `abs(fcf_yield − 4%)/4%` 打分，对 JNJ（正 FCF $19.6B、FCF/净利=1.22、低增长）的 2.77% 收益率误报 **High** 风险；其规则文案本身却称「不直接等同于预测不可靠」
  - 修复 A：新增守卫——**正 FCF 且转化健康（FCF/净利≥0.8）且非高增长**、收益率低于 4% 启发式时降一级并说明「属估值偏高观察，非现金流质量风险」。JNJ 该旗标 High→Medium，总体风险评分 75→80、High 计数 2→1（AAPL 同类标的同步受益）
  - 根因 B：市场区显示原始 β = −0.09，而 WACC 区显示截断后 β = 0.30，两处自相矛盾（风险旗标又用原始 −0.09）
  - 修复 B：`valuation/wacc.py` 暴露 `BETA_WINSOR_LO/HI` 常量；`reporting/dashboard.py` 在市场区对越界 β 追加标注「（原始值超出 CAPM 可用区间 [0.30, 2.50]，WACC 采用截断值 0.30）」

### ✨ Added
- `analysis/model_agreement.py`：`ModelAgreement.n_display_only` / `display_only_models`（第四桶）
- `valuation/wacc.py`：`BETA_WINSOR_LO` / `BETA_WINSOR_HI`（供 WACC 与展示层共用）

### 🔧 Changed
- `analysis/model_agreement.py`：`n_applicable` 分母剔除仅展示模型；虚假 failed 告警按真实失败数触发
- `data/reconciliation.py`：滚动 P/E 不一致文案改为方向感知
- `analysis/risk.py`：FCF Yield Gap 增加「正 FCF + 健康转化 + 非高增长」降级守卫
- `reporting/dashboard.py`：ReverseDCF 标签、模型分桶行、Beta 标注

---

## [Unreleased] — 2026-11-03 (Session #08 — NBIS 递归自我改进 3 轮: 报告自洽 + 极端终值门控 + 数据失真守卫)

> 方法：以 NBIS 为标的，**上一轮报告作为下一轮改进的起点**，连续迭代 3 轮
> （评估产出 → 定位缺陷 → 修代码 → 重跑）。每轮均以 `pytest 61/61` + 端到端重跑验证。

### 🐛 Fixed
- 🐛 **Round 1 — 报告自相矛盾消除**
  - 增长标题桶与 bullet 桶不一致：header 说「历史表现属于**高速增长**」而同一卡片 bullet 说「**爆发式增长 (>40%)**（239.8%）」→ `reporting/verdict_intuition.py::build_growth_verdict()` 标题改用与 `_rev_cagr_label()` 相同的分档（≥40% 爆发式 / ≥25% 高速 / ≥15% 稳健 / ≥5% 温和 / ≥0% 低速）
  - 业务类型标题与其自身冲突警告矛盾：headline 显示「SaaS（置信度 50%）」，同页却声明 SaaS 为资产轻原型冲突、peer 已重路由 AI/Cloud → `data/models.py::CompanyProfile` 新增 `effective_business_type` / `business_type_conflict_note`；`classification/ml_classifier.py` 冲突触发时写入；`reporting/dashboard.py::_business_section()` 渲染为「SaaS（置信度 50%） → **估值原型重路由: AI/Cloud Infrastructure**」
- 🐛 **Round 2 — DCF 极端终值权重可靠性门控**
  - 根因：NBIS 的 DCF 点估值 $30.37 由 TV/EV=499% 的终值单独决定（显式期 FCF 现值深度为负），却被按「仅降权一半」作为中位估值锚
  - 修复：`analysis/model_agreement.py` 引入分级降权 `_TV_EXTREME_THRESHOLD=1.5`（×0.25）/ `_TV_ARTIFACT_THRESHOLD=3.0`（×0.1）；NBIS DCF 权重 0.5→0.1，**质量加权中位估值由 $30.37(DCF) 转为 $26.41(EV/Sales)**；`models/dcf.py` 对 TV/EV>150% 输出「DCF point value unreliable」；新增置顶告警「⚠️ 极端终值占比重估」
- 🐛 **Round 3 — 反推与风险指标失真守卫**
  - 反向 DCF 输出无意义的负「EV 上限 $-59,617,890,134」→ `models/reverse_dcf.py` 改述为「即便取 80% 营收 CAGR 上限，模型推算 EV 仍为负（约 $-59.6B）…当前价隐含增长超出模型可解区间」
  - 风险「Operating margin volatility CV=1.02 (mean **-1143.1%**)」为近零营收基期导致的比率失真 → `analysis/risk.py::_margin_risk()` 剔除营收低于峰值 10% 的基期；不足 3 期时降级为 Low「无法计算可靠的利润率波动」；NBIS 风险 High→Medium（评分 50→58，High 3→2）

### ✨ Added
- `data/models.py`：`CompanyProfile.effective_business_type` / `CompanyProfile.business_type_conflict_note`
- `analysis/model_agreement.py`：`_TV_EXTREME_THRESHOLD` / `_TV_ARTIFACT_THRESHOLD` 分级降权 + 极端终值置顶 note

### 🔧 Changed
- `analysis/model_agreement.py`：TV/EV>80% 的 DCF 由单一 ×0.5 改为分级（0.5 / 0.25 / 0.1）
- `models/dcf.py`：TV/EV>150% 与 >85% 两种 note 文案分离
- `analysis/risk.py`：营业利润率序列加入营收基期规模守卫
- `reporting/dashboard.py` / `reporting/verdict_intuition.py`：如上

---

## [Unreleased] — 2026-10-27 (Session #07 — NBIS 第二版方法论修复: 覆盖率门控 + 质量加权中位 + 估值可用性拆分 + 概率结论)

### ✨ Added
- ✨ **一致性覆盖率门控（Coverage-Gated Agreement）** → `analysis/model_agreement.py`
  - 模型三桶分类：solved / not_applicable（INSUFFICIENT_DATA，如 EPS≈0 的 P/E、D&A 异常的 EV/EBITDA）/ failed（NO_SOLUTION_IN_RANGE 等）
  - `gated_cv = base_cv × 覆盖因子 ÷ 质量因子`（覆盖因子 = sqrt(applicable/solved) clamp [1.0, 2.0]）
  - 硬覆盖率封顶 `_COVERAGE_CAP`：solved≤1→Very Weak、==2→Weak、==3→Moderate、≥4 不封顶
  - 新字段：`n_total` / `n_not_applicable` / `n_failed` / `not_applicable_models` / `failed_models` / `coverage_ratio` / `quality_factor` / `coverage_factor` / `gated_cv` / `agreement_level_raw` / `coverage_sufficient`
- ✨ **质量加权中位数（Quality-Weighted Median）** → `analysis/model_agreement.py`
  - 权重体系：SOLVED=1.0 / APPROXIMATE=0.5 / TV/EV>80% 的 DCF 再×0.5（`_TV_DOMINANCE_THRESHOLD`）/ 分类置信度<55% 的倍数再×0.5（`_LOW_CONFIDENCE_THRESHOLD`）
  - 新字段：`median_value_weighted` / `model_weights` / `downweighted_models` / `low_conf_downgraded_models`；`_weighted_median()` 辅助函数
- ✨ **估值可用性评分（Valuation Usability）** → `data/validator.py` + `data/models.py`
  - `DataQualityFlags` 新增 `reconciliation_mismatches` / `valuation_usability_score` + `usability_label()`
  - `DataValidator._valuation_usability()`：随对账不一致项扣分（每项 -6，上限 -30）+ per-share 基数不可靠 -20 + EBITDA 口径异常 -5
  - `DataValidator.per_share_basis_unreliable()`（三键：流通股数/市值/TTM EPS）+ `_PER_SHARE_BASIS_KEYS`
- ✨ **蒙特卡洛概率结论 + 相关性建模** → `simulation/monte_carlo.py`
  - `MonteCarloResult` 新增 `n_valid` / `current_price` / `prob_above_price` / `prob_overvalued_30` / `prob_equity_zero`
  - 模块级 `_DRIVER_CORR`（4×4：cagr/om/wacc/tg）× `_correlation_cholesky()`（失败时 eigh 修正 PSD）做相关抽样；Gordon 稳定约束 `tg=min(tg, wacc-0.005)`
  - 负每股价值 floor 到 0 并计入 `prob_equity_zero`（不再丢弃尾部）
- ✨ **WACC 三 beta 透明化 + 区间提示** → `valuation/wacc.py`
  - `WaccBreakdown` 新增 `beta_raw` / `beta_bottom_up` + `beta_transparency_note()`（raw/winsorized/bottom-up）+ `wacc_range_note()`（超行业区间提示）
- ✨ **DCF WACC 行业区间估值** → `models/dcf.py`
  - 用行业区间上下沿重新估值，写入 breakdown `value_per_share_wacc_lo` / `value_per_share_wacc_hi`（暴露结论对 WACC 的敏感性）
- ✨ **反向 DCF 隐含增长量化** → `models/reverse_dcf.py`
  - `_normalized_growth_solve()`：成熟稳态假设 + 网格/二分求解隐含最低增长，写入 `breakdown["normalized_growth_solve"]`（替代无意义负 EV）
- ✨ **人工 AI Cloud peer 组** → `models/multiples.py`
  - `AI_CLOUD_PEER_GROUP`（label="AI Cloud / GPU Infrastructure / Neocloud"；CoreWeave/IREN/Equinix/Oracle/Nebius；band_width=0.625）+ `_ai_cloud_peer_note(anchor)` 静态参考带与可比公司列表；`__all__` 导出

### 🔧 Changed
- 🔧 `analysis/model_agreement.py`：`analyze()` 改为三桶分类 + 权重累积 + 门控一致性（原「裸 CV → 一致性」直映射废弃）；`_weaker_level()` / `_level_from_cv()` 辅助保证封顶只降不升
- 🔧 `reporting/dashboard.py`：`_agreement_section()` 新增模型分桶 / 一致性门控（质量因子·覆盖因子·门控 CV·原始一致性）/ 质量加权中位估值 / 模型权重 / 不适用与失败模型列表（notes 上限 3→5）；`_valuation_section()` DCF 行新增「WACC 区间估值」，WACC 明细块新增「Beta 透明度」+ 区间提示；`_data_section()` 数据质量拆为「源数据质量评分」+「估值可用性评分」两行，并新增「🎲 概率结论」块（P(内在>价格) / P(高估>30%) / P(股权归零)）
- 🔧 `reporting/verdict_intuition.py`：`_scenario_summary()` 修正为"当前价高于**全部**情景"；`build_valuation_verdict()` 改用 `median_value_weighted`；`shares_unreliable` 判定改为三键；公允区间标注样本数 n/覆盖率；headline 硬门槛 `n_solved < 2`
- 🔧 `analysis/scenario.py`：`_run_one()` 中 `pps < 0` 时 floor 到 0 并追加"股权价值归零 / 资不抵债风险"note
- 🔧 `valuation/wacc.py`：beta source 文案改为明确的 `[0.3, 2.5]` 缩尾写法

### 🐛 Fixed
- 🐛 **NBIS 第二版 #1（最严重）：2/6 覆盖率 + "Very Strong 一致性" = 幸存者偏差**
  - 根因：剔除 4 个失败/不适用模型后仅剩 2 个恰近模型，离散度被人为压小 → "依据更少、结论更自信"
  - 修复：覆盖率门控 + 硬覆盖率封顶；NBIS 由 Very Strong → **Weak**（门控 CV 5.8%，覆盖因子 1.22，质量因子 0.38）
- 🐛 **NBIS 第二版 #2：中位 $26.88 = 两个低质量模型等权平均，被当作"公允价"**
  - 根因：无质量加权。修复：质量加权中位数（NBIS: DCF=0.5, EV/Sales=0.25）；报告展示权重与降权原因；中位值性质标为"低置信模型集成值"
- 🐛 **NBIS 第二版 #3：股数偏差 42.9% 却仍输出两位小数每股公允值**
  - 根因：无 per-share 基数门控。修复：估值可用性评分拆分（NBIS: 源数据 83/100 vs 可用性 34/100）+ 股数偏差>25% 抑制每股公允值
- 🐛 **NBIS 第二版 #4：情景/中位/公允区间口径不一致；熊市 -$4.20 负价格**
  - 修复：情景文案"高于全部情景"；负 pps floor 到 0；公允区间标注 n/覆盖率
- 🐛 **NBIS 第二版 #5：50% 置信分类的近似倍数仍占中位一半**
  - 修复：分类置信度<55% 的 APPROXIMATE 倍数权重再×0.5；人工 AI Cloud peer 组替换近似单点
- 🐛 **NBIS 第二版 #6：WACC 单点 17.51% 失控 + 反向 DCF 输出无意义负 EV**
  - 修复：WACC 三 beta 透明化 + 行业区间估值（NBIS 6.5%→$1,574.90 / 11.5%→$237.37）；反向 DCF 隐含增长量化（"当前价隐含营收 CAGR ≈ 27%"）
- 🐛 **NBIS 第二版 #7：蒙特卡洛与模型集成口径不一致，无概率结论**
  - 修复：输出 P(内在>价格)/P(高估>30%)/P(股权归零)（NBIS: 0.3% / 97.5% / 6.7%）；驱动因子相关抽样；负值 floor 计入归零概率

### 📊 Baseline Verification (Session #07)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **61/61 passed** | 改动未破坏既有断言（未断言 agreement_level/median_value/fair_value_estimate） |
| demo NBIS (重资本算力 + 低覆盖) | ✅ 通过 | 一致性 Very Strong→**Weak**；模型权重 DCF=0.5 / EV-Sales=0.25；源数据质量 83/100 vs **估值可用性 34/100**；概率结论 P(内在>价)=0.3% / P(高估>30%)=97.5% / P(归零)=6.7%；WACC 区间估值 $1,574.90~$237.37；反向 DCF 隐含营收 CAGR ≈ 27% |
| demo_fast SOFI (Bank 向后兼容) | ✅ 通过 | 5/5 覆盖 · Very Weak（门控 CV 74.0%）；权重 P/E=0.5, P/B=0.5, Bank DDM=1, Bank RIM=1, SOTP=0.5；per-share 基数不可靠提示正常 |
| demo_fast AAPL (MatureTech 向后兼容) | ✅ 通过 | 6/7 覆盖 · Moderate；权重全 1.0；源数据质量 95/100 vs 估值可用性 95/100；无门控误降级 |

---

## [Unreleased] — 2026-10-27 (Session #06 — NBIS 误估值修复: 数据对账层 + AI/Cloud 算力 peer 路由 + 无意义倍数守卫)

### ✨ Added
- ✨ **数据对账层 (Cross-field Reconciliation)** → `data/reconciliation.py` 新建（纯只读模块）
  - `reconcile(data) -> ReconciliationReport`：对 headline 字段做 10 项交叉校验
    1. `market_cap ≈ price × shares_outstanding`
    2. `enterprise_value ≈ market_cap + total_debt − cash`
    3. `TTM EPS ≈ TTM net_income / shares`
    4. `trailing P/E ≈ price / TTM EPS`
    5. `EV/EBITDA ≈ enterprise_value / TTM EBITDA`
    6. `P/B ≈ price / book_value_per_share`
    7. `EV/Sales ≈ enterprise_value / TTM revenue`（内部推导，参考项）
    8. `TTM FCF ≈ operating_cash_flow + capex`
    9. `market shares ≈ 最新年度 shares_outstanding`
    10. `EBITDA/营收 ≤ 100%`（D&A 合理性；>100% 说明 D&A 主导，EV/EBITDA 不可比）
  - 数据结构：`ReconciliationCheck`（name/expected/actual/rel_diff/tolerance/unit/status/note + `render(fmt)`）+ `ReconciliationReport`（checks/mismatches/n_ok/n_na/`has_mismatch()`/`to_lines(fmt)`）
  - 容差分级：恒等式 5%（`_TOL_IDENTITY`）/ 供应商口径差异 20%（`_TOL_PROVIDER`）/ 股数 25%（`_TOL_SHARES`）
  - **硬约束**：只读，绝不写回 `FinancialData`；不一致仅「标记 + 渲染 + 备注」，由下游（multiples 守卫 / 数据质量评分）决定是否降级
- ✨ **AI/Cloud Infrastructure peer 桶** → `models/multiples.py`
  - 技术族按经济结构细拆：`Software - SaaS` / `Software - Mature` / `Semiconductors` / **`AI/Cloud Infrastructure`**（新增）
  - AI/Cloud 桶倍数：P/E 35 / EV/EBITDA 18 / EV/Sales 8 / P/B 7 / FCF Yield 0.015
  - `_COMPUTE_INFRA_SOURCE_BUCKETS` + `_compute_infra_override()`：命中「Very Capital Intensive + 高/中增长 + 弱/负 FCF + capex/revenue ≥ 1.0」时把技术族键重路由到 AI/Cloud 桶，source 串标注 `(APPROXIMATE)`
- ✨ **倍数适用性硬守卫** → `models/multiples.py` `applicability_check()`
  - 隐含 P/E > 100x（`_IMMATERIAL_PE_THRESHOLD`）→ P/E 标记 `not meaningful`（净利极薄时 P/E 无经济意义）
  - EBITDA/营收 > 90%（`_DNA_LOADED_EBITDA_MARGIN`）→ EV/EBITDA 标记 `not directly comparable`（D&A 主导）
- ✨ **资产轻原型冲突置信度扣减** → `classification/ml_classifier.py`
  - 新增常量 `ASSET_LIGHT_CONFLICT_CAPEX_RATIO=1.0` + `ASSET_LIGHT_TYPES={SaaS, MatureTech, Media}`
  - ML 判资产轻类型 + capex/revenue≥1.0 + 负 FCF → 触发 `"Asset-light prototype conflict"` 扣减，置信度 cap 50%，写入 `ConfidenceAdjustment` 审计链 + reasons
- ✨ **报告「🔗 数据对账」区块** → `reporting/dashboard.py`
  - `_fmt_recon(v, unit)` 按单位（USD / 股 / USD-股 / 倍数）格式化
  - `_data_section()` 渲染：已校验 N 项 · 一致 X · 不一致 Y · 数据不足 Z + 逐条不匹配明细 + 供应商口径失真提示

### 🔧 Changed
- 🔧 `models/multiples.py`：`_BT_TO_SECTOR` 技术族映射更新（SaaS→Software-SaaS / MatureTech→Software-Mature / Semiconductor→Semiconductors）；`_sector_peer_multiple()` 拆出 `_resolve_peer_bucket()`（返回 `(table_key, source, blend_value)`，key 与 blend 恰一非空）后在其上做 AI/Cloud 重路由；`calculate()` 调用简化
- 🔧 `valuation/terminal_growth.py`：`0 ≤ base_unclamped < 1.5%` 分支由「坍缩到 DECLINING_BASE(0.5%)」改为「抬高到成熟地板 BASE_FLOOR(1.5%)」（只有真实衰退才衰减；flat ≠ declining）；模块 docstring 第 13 行同步
- 🔧 `data/reconciliation.py`：`ReconciliationCheck.render(fmt)` 改为双参签名 `fmt(value, unit)`；`to_lines` 默认 lambda 接受 2 参；第 10 项检查重写为比率语义（EBITDA/营收 ≤ 100%），避免金额对金额的费解渲染

### 🐛 Fixed
- 🐛 **NBIS #1：ML Top-1 SaaS 92% 但 sector/industry 缺失 → 置信度被封顶 55% 却没有「原型冲突」提示**
  - 根因：置信度只看「数据是否缺失」，不看「标签是否与财务原型矛盾」（NBIS 是重资本、负 FCF，与资产轻 SaaS 完全相反）
  - 修复：新增 "Asset-light prototype conflict" 扣减（capex/revenue≥1.0 + 负 FCF → cap 50%），审计链完整留痕
  - NBIS 修复后审计链：`ML 92.0% → 缺失封顶 -37.0% → 原型冲突 -5.0% → Final 50.0%`
- 🐛 **NBIS #2：P/E / EV-EBITDA / EV-Sales 全被路由到粗桶 "SaaS → Technology"（P/E 22 / EV-EBITDA 14 / EV-Sales 4），严重扭曲估值**
  - 根因：技术族 peer 桶过粗，把软件 / 半导体 / 算力基础设施混同
  - 修复：细粒度桶 + AI/Cloud Infrastructure 重路由（NBIS EV/Sales 由 $11.41 → $26.41，source 明确标注重路由 + APPROXIMATE）
- 🐛 **NBIS #3：P/E 对净利仅 $42M（隐含 ~1307x）仍给出 $2.58 估值，误导性极强**
  - 根因：无「倍数无意义」守卫
  - 修复：隐含 P/E > 100x → P/E 标记 `not meaningful`（输出 Insufficient Data）；EBITDA/营收 > 90% → EV/EBITDA 标记 `not directly comparable`
- 🐛 **NBIS #4：单点供应商字段静默失真（trailing P/E 671 vs 内部推算 1307；股数 361.5M vs 253.0M；EBITDA 口径年度 vs TTM）**
  - 根因：无跨字段交叉校验
  - 修复：新建只读对账层，报告新增「🔗 数据对账」区块；NBIS 输出「已校验 10 项 · 一致 6 · 不一致 4」
- 🐛 **`test_terminal_growth.py::test_floor_base_keeps_low_strictly_below` 失败（历史遗留）** → 已修复
  - 根因：`0 ≤ base < 1.5%` 分支错误坍缩到 `DECLINING_BASE`(0.5%)，使健康的零增长公司终值增长率过低
  - 修复：改为抬高到成熟地板 `BASE_FLOOR`(1.5%)（只有真实衰退才衰减）；该测试由 ❌ 变 ✅

### 📊 Baseline Verification (Session #06)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (全量) | ✅ **61/61 passed** | 含此前 1 个 TVG floor 历史遗留失败已转绿 |
| demo_fast NBIS (重资本算力) | ✅ 通过 | 分类 SaaS 置信度 50%（审计链完整）✅；P/E Insufficient Data (not meaningful) ✅；EV/EBITDA Insufficient Data (D&A-dominated) ✅；EV/Sales $26.41 重路由 AI/Cloud (APPROXIMATE) ✅；对账 4 项不一致 ✅ |
| demo_fast SOFI (Bank 向后兼容) | ✅ 通过 | Bank → `sector table[Banks]` P/E 11 / P/B 1.2 完全不变；对账「9 项 · 一致 6 · 不一致 2 · 数据不足 1」 |
| demo_fast AAPL (MatureTech 向后兼容) | ✅ 通过 | MatureTech → `sector table[Software - Mature]` P/E 25 / EV-EBITDA 17 / EV-Sales 5 完全不变；对账「10 项 · 一致 10 · 不一致 0」 |

---

## [Unreleased] — 2026-10-08 (Session #05 — Intuitive Labels 直观标签上线 + NU demo 文案双 Bug 修复)

### ✨ Added
- ✨ **直观标签计算层（Verdict Intuition Layer）** → `reporting/verdict_intuition.py` 新建纯函数模块
  - `build_growth_verdict(gap)`: 营收 CAGR 6 档分桶（爆发式>40% / 高速25~40% / 稳健15~25% / 温和5~15% / 低速0~5% / 负增长<-10%）+ FCF CAGR 5 档 + 预测 vs 历史 pp 差值一句直观中文总结（仍属「高速增长」但明显放缓-21.1pp）+ 整体增长 emoji+summary（🚀 高速 / 📈 稳健 / 📊 温和 / 📉 承压 / 🟡 放缓 / 🟢 提升）
  - `build_valuation_verdict(agreement, scenarios, ...)`: price vs median 7 档标签（显著高估>50% / 高估>20% / 小幅高估>8% / 合理±8% / 小幅低估>-20% / 低估>-50% / 显著低估<-50%）+ 三档情景跨度宽窄 4 档判断（极宽>120%SV / 较宽>60% / 适中>25% / 窄）+ 公允区间标签（高于上限偏贵 / 低于下限便宜 / 区间内）+ 模型覆盖 label（全覆盖/基本可用/覆盖不足）+ 多信号合成 headline（emoji 5 档 🟩🟢🟡🟠🔴）+ caveats 组合（弱一致/非常弱一致/即使乐观情景也达不到当前价/模型覆盖不足/Reverse DCF 不可用）
- ✨ **数据卡片分层渲染方法** → `data/models.py` 两个直观卡片 dataclass 新增：
  - `GrowthVerdictCard.bullet_lines()`: 8 字段 → 最多 4 bullet（整体增长判断 / 历史增长 / 基础预测 vs 历史 / 市场隐含 vs 历史 + 隐含 vs 预测）
  - `ValuationVerdictCard.header_lines(include_headline=True)`: 10 字段 → 最多 5 行（一句话估值结论 + 中位估值对比 + 三档情景跨度 + 公允估值参考区间 + 判断依据）；通过 `include_headline=False` 支持「只展开细节不重复 headline」分层展示
- ✨ **报告多区块直观文案渲染** → `reporting/dashboard.py` 4 处挂接：
  1. 🔥 **OVERVIEW 首屏区块（新增）**：build_report() provenance 之后 business 之前插入，合并 valuation header_lines(include_headline=True) + growth bullet_lines()，用户首屏 0.5s 直接扫到 emoji+结论；末尾附快速参考免责声明
  2. **GAP 预期差距区块**：末尾追加「📈 增长直观解读」+ growth bullet_lines()（与原始预期差距数字同屏便于交叉验证）
  3. **AGREEMENT 模型比较区块**：「🤝 估值细节拆解」+ v.header_lines(**include_headline=False**)，只 bullet 细节不重复一句话结论
- ✨ **验证基线（3 只股票端到端覆盖不同场景）**：NU (模型覆盖不足 + 高估 + 高增放缓) · SOFI (Hybrid FinTech 混合 + 显著高估 + 即使乐观也达不到) · AAPL (纯 MatureTech + 模型全 7 个解算 + 增长隐含明显提升 25pp)

### 🔧 Changed
- 🔧 `data/models.py` lines 190-266：**GrowthVerdictCard + ValuationVerdictCard 两个直观卡片方法新增 + include_headline 参数引入 + 主语重复 bug 修复**
  - `GrowthVerdictCard.bullet_lines()`：整体判断 / 历史 / 预测 vs 历史 / 隐含 vs 历史+预测 四档 bullet，隐含 vs 历史/预测有任一即显示，否则隐藏
  - `ValuationVerdictCard.header_lines(include_headline=True)`：新增 keyword-only `include_headline` 参数（默认 True）；headline_summary、scenario_summary、reasoning、fair_value_estimate_range、median_vs_price_label 五大块，每块独立判空不输出空 bullet
  - Bug #1 修复：删除中位估值 detail 行冗余前缀「中位估值」（`detail = f"（中位估值 {...}）"` → 去掉前缀，因为 _vs_median_label() 返回的 median_vs_price_detail 已是自包含完整句「当前价较中位估值高 XX%」）
- 🔧 `reporting/dashboard.py` lines 96-161, 478-507, 544-555：**Overview 区块新增 + Gap 增长解读追加 + Agreement 分层渲染 + 标题改名**
  - `build_report()`：第 116-119 行 provenance 之后 business 之前新增 overview section（首屏直观判断）
  - `_intuitive_overview_section()`：首次判断 profile.valuation_verdict/growth_verdict 任一非 None 才输出（防止旧 pipeline 漏挂时不报错）；末尾加快速参考 footnote：「_（以上结论基于多模型中位数 + 情景分析 + 增长三档对比，仅作快速参考）_」
  - `_gap_section()`：末尾新增「📈 增长直观解读」区块（有 growth_verdict 才显示）
  - `_agreement_section()`：Bug #2 修复三要素——(a) 注释写清 "overview 已放过 headline，这里只展开细节"；(b) section 标题从 `**🤝 一句话估值:**` 改为 `**🤝 估值细节拆解:**`；(c) 调用 `v.header_lines(include_headline=False)`

### 🐛 Fixed
- 🐛 **Bug #1：中位估值对比主语重复「中位估值 较中位估值高 +41.6%」** → 修复前 NU demo_fast 实际输出：`中位估值对比：**高估**（中位估值 较中位估值高 +41.6%）` 读不通顺
  - **根因**：_vs_median_label() 为了「自包含可审计」返回的 median_vs_price_detail 已是完整中文句子「当前价 $X 较中位估值 $Y **高出 Z%**」，但外层 header_lines() 又写 `f"（中位估值 {detail}）"` 多加了主语 → 两个「中位估值」撞车
  - **修复**：直接包 detail 自身（`f"（{detail}）"`）不再加前缀
  - **防御式规则**：写入 AGENT.md Decision 007 新增「主语不自包原则」——detail/full_sentence 字段若已是完整句，外层渲染不再加主语前缀
- 🐛 **Bug #2：一句话估值在 OVERVIEW + AGREEMENT 双区块重复展示（headline_summary 写逻辑有点重复）** → 用户明确抱怨的问题
  - **根因**：两处独立 section 都想展示直观标签，都调了默认 include_headline=True，导致报告中出现两次一模一样的「一句话估值结论：🔴 当前价 $X 高估...」
  - **修复**：分层展示架构 (Decision 007)
    • Overview 首屏 = headline(一句话) + bullet(细节) 全展示（用户第一眼看到）
    • Agreement 模型比较 = 只展示 bullet(估值细节拆解)，不传 headline（与首屏不重复）
    • 语义锚点：section 标题改名（「一句话估值」→「估值细节拆解」），读者一眼就知道这是细节展开页
- 🐛 `test_terminal_growth.py::test_floor_base_keeps_low_strictly_below` 失败（TVG floor 0.5% vs 预期 1.5%）→ **未修复，记录为历史遗留 bug**；与本次直观标签/文案修复完全无关，是 terminal_growth.py normalized_growth 地板值逻辑在 0 增长边界条件下的行为偏差，不影响报告输出质量

### 📊 Baseline Verification (Session #05)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (52 tests 全量) | ✅ **51/52 passed** | 失败 1 项：test_terminal_growth TVG floor 历史遗留，与本次直观标签完全无关 |
| pytest (核心 5 套件：risk/classifier/ml/sensitivity/dcf) | ✅ **27/27 passed** | 用户最初要求的基线套件，零回归 |
| demo_fast NU (模型覆盖不足 2/4 + 高估 + 高增放缓) | ✅ 通过 | Bug #1 主语重复修复验证 ✅；Bug #2 Agreement 不再重复 headline ✅；一句话结论只在 Overview 首屏出现一次 ✅ |
| demo_fast SOFI (Hybrid FinTech + 金融机构指标适配) | ✅ 通过 | 向后兼容：Hybrid 标签/暴露度/置信度拆解仍完整显示 ✅；SOFI 风险评分保持 95/100 ✅ |
| demo_fast AAPL (纯 MatureTech + 7 模型全覆盖) | ✅ 通过 | 向后兼容：MatureTech 99.8% 单标签（非 Hybrid 不显示混合区块）✅；增长隐含 vs 历史 +25.3pp 明显提升 正确显示 ✅ |
| 签名安全 (header_lines 新增 include_headline kw) | ✅ 零回归 | keyword-only + 默认 True = 旧调用全兼容；grep 确认 4 处调用点（dashboard overview/dashboard agreement + 无其他调用）|

---

## [Unreleased] — 2026-10-08 (Session #04 — SOFI 报告三问修复: 置信度透明 / Hybrid 业务 / 金融机构 FCF 指标)

### ✨ Added
- ✨ **置信度审计链 (Confidence Audit Trail)** → `data/models.py` 新增 `ConfidenceAdjustment` dataclass
  - 结构：`step_name: str` + `delta: float` (单位 pp) + `reason: str`
  - 挂载：`CompanyProfile.confidence_adjustments: list[ConfidenceAdjustment]` + `ml_raw_confidence: float`
  - 扣减步骤：① Unknown class penalty (若 Top-1 为 Unknown 或 <50%) ② Missing sector/industry cap (Yahoo 401 触发, 当前 SOFI 被 cap 到 55%)
- ✨ **混合业务表达 (Hybrid Classification)** → `data/models.py` 新增 `BusinessExposure` dataclass + CompanyProfile 5 字段
  - `ConfidenceAdjustment(label, weight, source="ml_aggregate")` → 5 轴聚合：Financial / Technology / Cyclical / HardAssets / Diversified
  - CompanyProfile 新增：`is_hybrid_classification` / `primary_business_type` / `secondary_business_type` / `hybrid_label` / `classification_confidence_level`
  - 三条 Hybrid 触发规则：
    1. `FinTech Hybrid`: Financial Top-1 (Bank/Insurance/REIT ≥ 50%) + Technology axis ≥ 8% (MatureTech/SaaS/Semi 合计)
    2. `Tech-Fin Hybrid`: Technology Top-1 + Financial axis ≥ 8%
    3. `Generic Low-Separation Hybrid`: Top-1 confidence < 55% 且 Top1/Top2 ratio < 3x
  - 4 档置信度等级：High (Top-1 ≥ 80%) / Medium (≥55%) / Low (≥40%) / Very Low (<40%)
- ✨ **风险信息级提示 flag (Severity=None)** → `analysis/risk.py` 新增非扣分「指标定义差异说明」
  - 金融机构(Bank/Insurance)：自动添加 "⚠️ [Info] Metric Interpretation: FCF/EV/Net Debt for banks differ from industrial companies — see Bank DDM/RIM and P/B valuation instead"
  - REITs：自动添加 "⚠️ [Info] Metric Interpretation: Prefer FFO/AFFO over GAAP FCF for REIT valuation"
- ✨ **数据质量验证基线**：demo_fast SOFI + AAPL 双向端到端验证锚点

### 🔧 Changed
- 🔧 `data/models.py` lines 165-240：CompanyProfile 数据契约扩展（向后兼容，所有新字段默认值）
- 🔧 `classification/ml_classifier.py` lines 1073-1330：分类器核心重构
  - 新增 `_build_exposures()`: 11 类 BusinessType 概率 → 5 轴 Financial/Tech/Cyclical/HardAssets/Diversified 暴露度聚合（映射表写死在函数内）
  - 新增 `_detect_hybrid()`: 三条 Hybrid 规则判定 + 4 档置信度等级
  - `classify()` 重写：置信度扣减明细逐步追加（每步 append ConfidenceAdjustment + 同步更新 confidence 数值）；ML 主分支 + rule fallback 分支**双双**补齐所有新字段（避免 None 渲染异常）
- 🔧 `classification/classifier.py` lines 57-471：规则引擎镜像改造
  - `classify()` 镜像补齐 ConfidenceAdjustment (data-quality/rule-override/structural-override 三步占位) + Hybrid (is_hybrid=False + exposures[]) 结构
  - `_characterize_profile()` 金融机构专项适配（**SOFI 修复层 #1**）：
    • profitability：operating_income 缺失时（银行常态）回退 net_margin 判定
    • cash_flow：Bank/Insurance 不用 FCF margin，改用 net_income 正/负 → Profitable/Loss-Making，文案附 "FCF not meaningful"；REIT 加 FFO/AFFO 推荐
    • leverage：Bank D/E 阈值从普通 2x Medium / 4x High 放宽到 >15x Medium（银行高杠杆是常态），文案三档 Well-Capitalized / Adequate / Under-Capitalized
    • capital_intensity：Bank/Insurance 标 "N/A for financial institutions"
- 🔧 `reporting/dashboard.py` lines 116-299：报告渲染三区块改造
  - `build_report()` L118：新增把 profile 传入 `_market_section(data, profile)`（首次漏传，已修正）
  - `_business_section()`：Hybrid 分支 (Primary Model → Secondary → Label)；置信度拆解明细（仅当 adjustments 有非 0 delta 时显示）；Exposures 条形图（阈值 ≥2% 才渲染，否则隐藏避免噪声）；classification_reasons 3→4 条
  - `_market_section(profile=None)`：新增 profile 参数；is_fin 分支 EV / Net Debt / EV/EBITDA / FCF TTM 总览四行全加斜体 caveat "*Financial institution metric not directly comparable to industrial companies*"；REIT 分支加 "*For REITs, prefer FFO/AFFO which adjusts for depreciation*"；普通公司无任何变化
- 🔧 `analysis/risk.py` lines 43-329：风险规则机构敏感化（**SOFI 修复层 #2**）
  - `analyze(profile=None)` 签名加 profile；顶部 is_fin/is_reit 布尔；末尾 append Severity=None 信息级 flag
  - `_leverage(data, profile=None)`：Bank/Insurance → D/E >15x Medium only；其他保持 2x Medium / 4x High
  - `_margin_risk(data, profile=None)`：Bank/Insurance → 完全跳过 neg-FCF 年数计数逻辑（直接 return 不生成 flag）；REIT 证据文案加 caveat
  - `_forecast_risk(data, profile=None)`：Bank/Insurance → 直接 return（根本不计算 FCF Yield 对比）；REIT 把 FCF Yield 严重度降一档 (High→Medium, Medium→Low) + 加 caveat

### 🐛 Fixed
- 🐛 **SOFI 问题 #1：业务类型置信度 66.6% → 55% 黑盒扣减** → 根因 `confidence = min(confidence, 0.55)` sector/industry cap 未留痕；修复后业务区块明确显示「ML Top-1 probability: 66.6% → Missing sector/industry data cap: -11.6pp → Final confidence: 55.0%」
- 🐛 **SOFI 问题 #2：混合业务单 Bank 标签** → 根因 11 类分类无 FinTech/Hybrid；修复后 SOFI 显示 `Primary Model: Bank Lending + Deposits` / `Secondary: FinTech Platform (Lending-as-a-Service + Investing)` / `Classification: Hybrid Financial Institution` / `Confidence Level: Medium` + 暴露度条形图 (Bank 66.6% + FinTech 22.1% + Technology 7.0%)
- 🐛 **SOFI 问题 #3：FCF=-$9B 连锁风险误报** → 根因 银行 Operating CF - Capex 被误当普通 FCF 解读；修复后：
  • 现金流剖面：Weak/Negative FCF → Profitable (net_income $636M TTM) + FCF 不适用说明
  • 风险 Medium [4y neg-FCF]：移除（不扣分）
  • 风险 High [FCF Yield -60.17% gap 1600%]：移除（不扣分）
  • 风险总分：80/100 → **95/100**（仅保留 Beta=2.31 Medium 一项 + Info 级说明一项）
  • 市场区块：EV / Net Debt / EV/EBITDA / FCF 全部附带金融机构 caveat 注释
- 🐛 `_market_section()` 首次签名变更遗漏调用点传参 → build_report L118 Edit 修正，避免 profile=None 导致所有 caveat 不显示

### 📊 Baseline Verification (Session #04)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| pytest (27 tests) | ✅ **27/27 passed** | risk + classifier + ml_classifier + sensitivity + dcf 5 套件零回归 |
| demo_fast SOFI | ✅ 通过 | 三问修复全部落地：置信度拆解显示 + Hybrid 标签 + risk 95/100 |
| demo_fast AAPL | ✅ 通过 | 非金融公司向后兼容：MatureTech 单标签(非 Hybrid) + Strong FCF + 原生指标无 caveat |
| 调用链安全（签名变更）| ✅ 零回归 | 所有新参数 =None 默认值 + getattr 防御式读取；grep 确认 telegram_bot.py:79 已天然传 profile |

---

## [Unreleased] — 2026-10-05 (Session #03 — Real-Data ML v2.1 训练发布 + Sanity 验证)

### ✨ Added
- ✨ **真实标注版 LightGBM 分类器 v2.1-real-data-train1000** → `classification/_ml_artifacts/` (3 个 .pkl)
  - `lgbm_multiclass_v2.pkl` (7.8 MB) — LightGBM 模型，1000 真实标注样本训练
  - `tfidf_vectorizer_v2.pkl` — TF-IDF 向量器 + χ² SelectKBest (k=60)
  - `train_meta_v2.pkl` — TrainMeta: version="2.1-real-data-train1000", note="real-data trained on 1000...", **train_acc=97.40%**, n_classes=11
- ✅ **demo_fast 分类正确性验证基线** (16 只 sanity 股票)：12/16 = **75.0%**
  - 正确: AAPL(Mature) · NVDA(Semi) · JPM(Bank) · BAC(Bank) · PLD(REIT) · XOM(Comm) · CVX(Comm) · DUK(Util) · KO(Conglom) · PEP(Conglom) · JNJ(Mature) · CRM(SaaS)
  - 边界误判: MSFT→Semi(60:40), AVGO→Mature(100:0 标签错!), AMT→Util(60:40 interest缺), NEE→REIT(50:50 capex乱)
- ✨ **训练集质量量化审计** (6 项登记于 AGENT.md #11 Known Issues)

### 🔧 Changed
- 🔧 `classification/ml_classifier.py` `_train_from_scratch()` (lines 771-782)
  - **永久切换训练源**: `build_synthetic_training_set()` → `build_training_set_from_csv(labeling_dump.csv)`
  - **TrainMeta 末尾 overwrite**: 构造后立即 `self._meta.version = "2.1-real-data-trainN"` + `self._meta.note = "real-data trained on N manually labeled rows..."`，防止 dataclass 默认 "2.0-synthetic" 污染真实工件
- 🔧 删除旧 synthetic 工件 (3 个 pkl) 后重新生成真实版
- 🔧 补装依赖 `lightgbm>=4.7, scikit-learn>=1.9` (运行时缺失)

### 🐛 Fixed
- 🐛 PowerShell CSV L2 重复 "ticker" 类型批注行 → **实测不存在** (dup_headers=0, 1000数据+1表头 干净)，从 Known Issues 标记 ✅ Resolved
- 🐛 `TrainMeta.version` 写死 "2.0-synthetic" → 覆盖 overwrite 修复 (即使未来再重训，版本号也会带 real-data + 样本数)

### ⚠️ Known Issues (升级到 HIGH 优先级)
- ⚠️ **HIGH**: `sector/industry` 文本特征缺失 830/1000 = **83%** (Yahoo assetProfile 401 China)
- ⚠️ **HIGH**: `interest_to_revenue` 关键数值特征=0 占 821/1000 = **82%** (Bank/REIT/Util/Ins 判别信号缺失)
- ⚠️ **MEDIUM**: `Semiconductor` 类别样本仅 29/1000 = **2.9%**，叠加 AVGO 标签错误 (Mature 应为 Semi)
- ⚠️ **MEDIUM**: Unknown 类别占比 **35.4%** (5000 样本扩充后应下降)

### 📊 Performance Baseline (Real-Data v2.1 vs Synthetic v2.0)
| 指标 | Synthetic v2.0 | Real-Data v2.1 | Δ |
|------|---------------|----------------|---|
| 训练集规模 | 1500 参数化合成 | 1000 人工标注真实 | -33% |
| train_acc | ~98% | **97.40%** | -0.6pp |
| 16-sanity OOS | ~85% (估计) | **75%** | **-10pp ↓** |
| 过拟合风险 | HIGH (合成分布偏移) | LOW (真实分布) | ✅ 改善 |

---

## [Unreleased] — 2026-10-05 (Session #02 — 1001只数据收集完成)
### ✨ Added
- ✨ **1001只真实股票特征数据集** → `classification\labeling_dump.csv`
  - 1001 行 × 20 列 (15 数值 + 4 文本 + 1 label 待填)
  - 覆盖 11 类行业: Tech/SaaS/Semi/ConCyclical/REIT/Bank/Ins/Comm/Util/Conglom/Unknown
  - 来源: Yahoo Finance Chart + Fundamentals API (synthetic fallback <1%)
- ✨ 1000+ 股票代码列表 → `full_tickers_1000.txt` (去重整理，可复用)
- ✨ **项目文档体系 6 文件**:
  - `AGENT.md` v2.0 — AI 接力完整状态 (26 章节)
  - `README.md` — 项目介绍 + Quick Start + ML 训练指南
  - `TODO.md` — 4 级优先级 30+ 待办事项
  - `CHANGELOG.md` — 本文件
  - `DECISIONS.md` — ADR 架构决策记录
  - `ROADMAP.md` — 产品 5 阶段路线图

### 🔧 Changed
- (无源代码变更；仅数据收集脚本运行 + 文档创建)

### 🐛 Fixed
- 修正 `_dump_features_for_labeling.py` 连续两次运行导致的 CSV 重复行问题
  - 1533 行 → 1001 行 (PowerShell Import-Csv/Export-Csv 去重 + 保留最新)

### 🗑️ Removed
- (无)

---

## [v0.6.0-synthetic] — 2026-09-xx (Session #01 — 核心开发完成)
> 上一阶段主要产物 (由前序 Agent 完成，从代码结构推断)

### ✨ Added
- 核心模块体系 (data/valuation/models/analysis/classification/simulation/forecasts/reporting/telegram_bot 共 9 模块)
- `YahooFinanceProvider` + `TreasuryYieldProvider` 异步 HTTP (httpx) + 4h JSON 原子缓存
- WACC **七步法实时计算** (`valuation/wacc.py`) + Sanity Check vs 行业区间
- 终值增长率 **TVG 三重约束** (`valuation/terminal_growth.py`):
  `min(企业增速, 名义GDP, WACC-0.5%)` 防止 Gordon 模型发散
- 6 个估值模型: DCF / Reverse DCF / NAV / Bank / SOTP / Multiples
- **WACC×g 敏感性矩阵** + 稳定性四档分级 (Stable → Highly Sensitive)
- 确定性 `BusinessClassifier` 11 类规则 + **结构覆盖 4 类强规则**:
  Bank (int/rev>30%) / REIT (EBITDA% 55-90+低β) / Semi (gm>50%+capex>8%+低D/E) / Util (div>3%+低β+高D/E)
- **LightGBM 合成数据版 ML 分类器** (`classification/ml_classifier.py`):
  - 15 数值 + TF-IDF (domain keywords) + χ² SelectKBest (k=60)
  - 1500 参数化合成样本，训练准确率 ~98%
  - ML_FALLBACK_THRESHOLD=0.40：低于 40% 置信度回退规则引擎
- `main.py` CLI 统一入口: `bot / demo / demo_fast / test_demo / test / help`
- Telegram Bot 集成: `python-telegram-bot` + `ValuationPipeline.run()`
- pytest 测试套件 (~45% 覆盖): dcf/reverse_dcf/sensitivity/classifier/ml_classifier/risk/normalizer/special_models/forecast/telegram_chinese

### 🔧 Changed
- `BusinessType` 枚举统一为 PascalCase .value 字符串 (MatureTech / SaaS / ...)
- 数值特征统一 15 个名称: `CSV_NUMERICAL_COLUMNS` 全局常量保证对齐
- CSV ↔ 训练集 DROP-IN 接口: `build_training_set_from_csv` 与 `build_synthetic_training_set`
  返回形状完全相同的 `(X_num_list, X_text, y_raw)` 三元组

### 🐛 Fixed
- 修复 Windows 下代理 `NO_PROXY=::1` 导致 httpx 连接崩溃 (main.py `_fix_proxy_env`)
- 修复 stdout/stderr UTF-8 编码错误 (Windows PowerShell 5 下常见)

### ⚠️ Known Issues
- Yahoo `quoteSummary/assetProfile` (sector/industry) 端点在中国区大规模 401 Unauthorized
  → 接受现状，数值特征完整，文本特征部分缺失

---

## 版本计划 (Upcoming)
### [v0.7.0-real-ml] — 人工标注完成后
- [ ] 切换 `build_synthetic_training_set()` → `build_training_set_from_csv()`
- [ ] 真实标注模型 v2.1-real 训练发布
- [ ] AB 测试对比报告 (3 版分类器混淆矩阵 + F1-score)

### [v0.8.0-prod-ready]
- [ ] pytest ≥80% 覆盖
- [ ] Telegram 异常 / 限流 / 超时处理
- [ ] Dashboard PNG 图表报告

### [v1.0.0-launch]
- [ ] Cloudflare + Render 部署
- [ ] Watchlist 监控推送
- [ ] 港股 (.HK) / A股 (.SS) 双市场支持
