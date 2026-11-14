# ✅ TODO.md — 长期待办事项
> (当前: 2026-11-14) 通用估值引擎 Telegram Bot

优先级定义：
- 🔴 **CRITICAL** — 阻塞发布 / 核心功能错误
- 🟠 **HIGH** — 近期必须完成 (1-2 周)
- 🟡 **MEDIUM** — 本月迭代
- 🟢 **LOW** — 有空再做 / Nice to have

---

## 🔴 CRITICAL (阻塞发布)
| # | 任务 | 负责 | 状态 | 备注 |
|---|------|------|------|------|
| C-01 | ~~收集1001只股票特征训练数据~~ | Agent | ✅ **DONE** | `classification\labeling_dump.csv` 1001行 |
| C-02 | **人工标注 1001 行 `label` 列** | 👤 Human | 🟡 **DOING** | 11类 PascalCase; 参考 sector/industry / company_name |
| C-03 | 切换 ML 训练源到真实 CSV | Agent | ⬜ TODO | 修改 `ml_classifier.py:L705` 处 1 行代码 |
| C-04 | 删除旧 `.pkl` 并重新训练真实模型 | Agent | ⬜ TODO | 触发方式: `python main.py demo AAPL` |
| C-05 | 在测试集上评估真实模型准确率 | Agent | ⬜ TODO | 目标 ≥ 95% (vs 确定性 ~85%, 合成 ~98%) |

---

## 🟠 HIGH (近期 1-2 周)
| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| H-01 | A/B 测试对比三版分类器 | ⬜ TODO | deterministic / synthetic / real-labeled 输出混淆矩阵 |
| H-02 | 扩充 pytest 覆盖率到 80%+ | ⬜ TODO | 重点: `classification/`, `valuation/wacc.py`, `models/router.py` |
| H-03 | 修复 Yahoo `assetProfile` 401 问题 | ✅ **DONE** | 方案落地为**三源 sector/industry 补全链**（非 Alpha Vantage/FMP）：`SectorIndustryResolver` = FinanceDatabase（离线 Yahoo 兼容）→ SEC EDGAR（官方 SIC 桥接 `data/sic_map.py`）→ Wikidata SPARQL P452 兜底；`data/providers.py` 接线 + "asset management" 硬规则补齐；新增 45 测试；pytest 333/333；SEC 层在线 10/10 精确，硬规则命中率 75%→78.3% (Session #24 ADR-040) |
| H-04 | 验证 CSV 训练流水线端到端 | ⬜ TODO | 跑 `build_training_set_from_csv` → 训练 → 预测 10 只 ticker |
| H-05 | `TelegramBotRunner` 生产健壮化 | ⬜ TODO | 加入: 消息超时 / 异常捕获 / 用户限流 / 错误提示友好化 |

---

## 🟡 MEDIUM (本月迭代)
| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| M-01 | 训练数据集扩充到 5000 行 | ⬜ TODO | 覆盖 S&P MidCap 400 + Russell 2000 头部 |
| M-02 | 新特征: 季度同比变化率 | ⬜ TODO | 利润率扩张 / 收入加速等 4 个 Δ 特征 |
| M-03 | 新特征: Sector ETF 相关性 | ⬜ TODO | 60D 滚动 corr vs XLK / XLF / XLRE 等 |
| M-04 | 港股 (`.HK`) 与 A股 (`.SS`) 支持 | ⬜ TODO | 需要额外数据源 (如东方财富 / 新浪财经 API) |
| M-05 | 估值报告增加 "与上次估值对比" diff | ⬜ TODO | 存储每次估值结果到 SQLite; 输出 Δ% |
| M-06 | Dashboard 报告可视化 | ⬜ TODO | Matplotlib / Seaborn 输出 PNG; Telegram 内联图 |
| M-07 | 多语言输出 (ZH / EN) | ⬜ TODO | 当前中文优先; 加英文模板切换开关 |
| M-08 | 对账层 pytest 用例 | ⬜ TODO | 覆盖 `data/reconciliation.py` 10 项交叉校验 + AI/Cloud 重路由 (Session #06) |
| M-09 | AI/Cloud 重路由回归扩样 | ⬜ TODO | CRWV / CORZ / IREN 等算力/数据中心标的，校准 AI/Cloud 桶倍数 (Session #06) |
| M-10 | 覆盖率门控 / 质量加权中位 / 概率结论 pytest 用例 | ⬜ TODO | 覆盖 `analysis/model_agreement.py` 门控与权重 + `simulation/monte_carlo.py` 概率输出 (Session #07) |
| M-11 | 报告展示失败模型清单 + 保留对照 | ⬜ TODO | 列出失败模型及原因，并展示"保留 P/E 和 EV/EBITDA 时中位值会变成多少" (Session #07) |
| M-12 | 把「渲染层口径冲突」纳入声明式 invariant | ✅ **DONE** | `check_invariants()` 新增 invariant #6：情景 `discount_label` 必须 == 引擎口径（`caliber`），否则报 `main model / scenario disagreement`；golden 指纹加 `caliber`/`scenario_calibers` (Session #14 ADR-024) |
| M-13 | WACC 行业 sanity 区间随原型重路由收口 | ⬜ TODO | CRWV 重路由 AI/Cloud 后 `Industry sanity` 仍读 Software 8%~11.5%；与 peer 桶一并改为按 `effective_business_type` 取区间 (Session #12 Known Issue #1) |
| M-14 | 金融机构口径分叉 scenario/sensitivity pytest 用例 | ✅ **DONE** | 金融标的情景 `discount_label=="ke"`、不走 DCF、敏感性返回说明文案；契约由 `valuation/caliber.py` 单点驱动 (Session #13/#14 ADR-022/024) |
| M-15 | 审计所有 `min/max` 封顶点与边界守卫比较符 | ✅ **DONE** | `tests/test_cap_boundary_guard.py` 三层审计（常量守卫 / 同文件字面量配对扫描 / 跨文件 confidence 封顶）；**捕获并修复** `models/sotp.py` 跨文件漏检 (`conf < 0.55` → `<=`) (Session #14 ADR-025) |
| M-16 | SOFI hybrid 标签 / SOTP 阈值复评（数据驱动） | 🟡 **PARTIAL** | 阈值已提为具名常量 `HYBRID_FIN_TO_TECH_FLOOR=0.08` 并加边界锁定测试（**锁定而非下调**）；根因 sector/industry 缺失属特征问题，**H-03 三源链已于 Session #24 补齐该特征缺口** → 现可数据驱动复评；仍须配合 C-02 真实标注重训方可推高到 90%+，复评阈值会扰动 golden 基线需逐字段审阅 (Session #14 → #24) |
| M-17 | UPST 递归自我改进 3 轮（分类子串误匹配 → 金融 EV/Sales 剔除 → 渲染层口径泄漏） | ✅ **DONE** | round1 `keyword_hit()` 词边界（修复 ticker `upst` 被 `"ups"` 子串误匹配 → Industrial）；round2 金融分叉剔除 `EV/Sales`（一致性 Very Weak→Moderate）；round3 渲染层读口径契约（WACC Risk→Cost of Equity Risk / EV 复核→P/B·P/E·RIM）；pytest 106/106；DEFECTS 空 (Session #15 ADR-026/027) |
| M-18 | 金融"数据不足"模型字段语义 + 金融情景跨度复评 | ⬜ TODO | ① `applicable_models` 含 `Bank DDM`（No dividend → Insufficient Data）却按「不适用」计入分母，字段名与实际计分口径不一致，需明确命名；② UPST 三档情景跨度仅 9% SV（金融 β±0.30 校准）——对 β=2.50 的高波动标的或过窄，待以更多金融标的（SOFI/JPM/UPST）对比复评 (Session #15) |
| M-19 | **Phase 1：修复现有引擎（负终值 + 状态污染 + 数学下限 + 残差）** | ✅ **DONE** | ① 负终期 FCF 抑制（`gordon_terminal_value()` 统一出口，不翻转符号 + `terminal_fcf_negative` 标注）(ADR-028)；② 预测年限单一真源 `resolve_forecast_horizon()`，删除 `self.horizon` 污染 (ADR-029)；③ WACC−g 统一下限 `MIN_WACC_TG_SPREAD=0.005`；④ 反向 DCF 求解器残差检查（`rel_resid>1e-3`→APPROXIMATE）；⑤ Round-trip 测试 10 用例；pytest 116/116 (Session #16) |
| M-20 | **Phase 2：反向 DCF 升级为约束式隐含求解器** | ✅ **DONE** | 单变量 one-at-a-time 独立反推 **Implied Operating Margin / FCF Margin / WACC / Terminal Growth**（+ 既有 Revenue CAGR）；`_solve_implied_scalar()` 硬边界（越界→`NO_SOLUTION_IN_RANGE` 指名边界，**不钳制**）+ 单调性 + 残差检查；FCF margin 经 flat-margin 桥独立化；透传 `ImpliedExpectations` + `_implied_section()` 渲染；测试 8 用例；pytest 124/124 (Session #17 ADR-030) |
| M-21 | **求解器 P0/P1 加固（用户代码审查 6 项）** | ✅ **DONE** | ① Brent 失败后 bracket 重校验（`f(a)·f(b)>0` → 拒可疑根 `NO_SOLUTION_IN_RANGE`）+ 求解后 residual 检查；② 单调性实测（21 点采样 → 非单调扫描 root brackets → 0 无解/1 解/>1 `MULTIPLE_ROOTS`）；③ `terminal_fcf_negative` 贯穿 breakdown/期望/渲染 + `_finalize_revenue_cagr()` 降级 `SOLVED→APPROXIMATE`（Terminal Value Suppressed）；④ 端点根合法（含容差 → SOLVED）；⑤ 常数目标 `FLAT_OBJECTIVE`/`NO_SOLUTION_IN_RANGE`；⑥ 自查修复 2 处（`mono_tol` 步长尺度 + 递减可达区间语义）；测试 +18；pytest 142/142；golden 无漂移 (Session #18 ADR-031) |
| M-22 | 隐含驱动纳入 golden 指纹/invariant | ⬜ TODO | 当前隐含驱动（OM/FCF Margin/WACC/TG）未纳入 `report_fingerprints.json`；待一次有意漂移审阅后再决定纳入，避免求解数值抖动污染基线 (Session #17/#18 遗留) |
| M-23 | **Rf 单一真源 + Terminal Growth 三档语义重定义（用户代码审查 2 项 P0）** | ✅ **DONE** | ① **P0-1**：`WaccCalculator._implied_cost_of_debt()` 新增 `risk_free_rate` 形参，`calculate()` 传入已解析 `rf` → CAPM 与所有债务成本 fallback **共用同一 Rf**（消除 MarketData 空值时 ke/kd 口径背离）；② **P0-2**：重定义三档经济学含义（Base=长期稳定终值增长率，受 GDP+Gordon 双约束；Low/High=情景区间），新增引擎契约字段 `high_exceeds_gdp`/`gdp_ceiling`/`band_labels` + `BAND_LABELS` 常量；`derivation_trace()`/`models/dcf.py`/`dashboard.py` 三处显式标注「High 为乐观情景，非长期稳定终值增长率」；测试 +5；pytest 147/147；golden 无漂移 (Session #19 ADR-032) |
| M-24 | **Quality-Weighted Median 边界修复（用户代码审查 1 项 P1）** | ✅ **DONE** | `_weighted_median()` 原返回「首个累计权重 ≥ total/2 的值」→ 等权（常见）且模型数为偶数时返回第 n/2 个值而非 `mean(values[n/2-1], values[n/2])`，导致加权中位数≠普通中位数（AAPL 176.12 vs 165.24）。改用标准 **midpoint 定义**（下/上加权中位数取平均）→ 等权时精确退化为普通中位数；零/负权重剔除；新增 `tests/test_model_agreement.py` 16 用例；golden 4 只有意漂移已审阅重生成；pytest 163/163 (Session #19 ADR-033) |
| M-25 | **Phase 2：Monte Carlo 双模式 + 路径锚点对账 + 经营/折现情景拆分** | ✅ **DONE** | ① MC 双模式 `base_case`（以 DCF base 为中心，仅扰动假设）/ `historical`（独立），无锚点自动回退 + 说明；② 去除人为 +2% 利润率地板，允许负利润率，边界可配置；③ 路径形参化（`_base_case_path` + `_project_one_path`）→ 零扰动锚点精确复现确定性 DCF（MSFT/AAPL +0.0%）；④ 负股权归零口径与 DCF 统一（NBIS $0.00）；⑤ `ScenarioAnalyzer.run_operating()` 经营情景 vs 折现率情景拆分；⑥ 报告透明化（模式/种子/请求/有效/无效/截断/分布/相关矩阵）；⑦ `P(股权归零)`→「Equity Value Wipeout Probability」；测试 +14；pytest 217/217；golden 无漂移 (Session #20 ADR-034/035) |
| M-26 | **Phase 3：WACC Beta 多窗口敏感性 + bottom-up beta** | ✅ **DONE** | `MarketData` 新增 `beta_windows`（窗口→回归 β）/`industry_beta`（bottom-up 槽位，缺失即 `None` 不伪造）；`data/providers.py` 新增 `BETA_WINDOWS=(2y_weekly/3y_monthly/5y_monthly)` + `_estimate_beta_windows()`（逐窗口独立回归，失败窗口显式 `None`；周线 ISO-week keying）；`WaccBreakdown` 新增 `beta_windows`/`beta_dispersion` + `beta_window_note()`（<2 窗口返回 `None`；极差 >0.50 标注「窗口间波动较大」）；**多窗口为独立审计输入，不覆盖 CAPM 标量 β**；dashboard 渲染 (Session #21 ADR-036) |
| M-27 | **Phase 3：Peer Multiples fallback 标签 + peer 样本数** | ✅ **DONE** | `models/multiples.py` 4 档来源常量 `PEER_SOURCE_EXACT_INDUSTRY`/`SECTOR_FALLBACK`/`BUSINESS_TYPE_FALLBACK`/`APPROXIMATE` + `PEER_SOURCE_LABELS` 封闭集；`_sector_peer_multiple`/`_resolve_peer_bucket` 返回 4 元组 `(value, source_text, source_kind, n_peers)`；`calculate()` breakdown 落 `peer_source_kind`/`peer_sample_size`；dashboard 渲染「🔎 同行倍数来源 (可审计)」；端到端 AAPL `EXACT_INDUSTRY` / NBIS `APPROXIMATE` n=5 / JPM `EXACT_INDUSTRY` (Session #21) |
| M-28 | **Phase 3：model_family / dependency_group 同源证据去重** | ✅ **DONE** | `analysis/model_agreement.py` 新增 `_MODEL_FAMILY`（P/E↔Historical Multiples→`earnings_multiple`、EV/Sales↔EV/Sales (Unit Econ)→`sales_multiple`、DCF/ReverseDCF→`dcf_forecast`）+ `_independent_evidence()`；覆盖率门控 `_COVERAGE_CAP.get(n_solved)` → `.get(n_independent)`；`ModelAgreement` 新增 `n_independent_evidence`/`duplicate_evidence_groups` + 去重 note (Session #21 ADR-037) |
| M-29 | **Phase 4：全量回归 + 边界用例 + lint/type 检查** | ✅ **DONE** | 回归域 9 → **18 只**（+GOOGL/AMZN/AVGO/ORCL/CRWV/UPS/KR/BAC/NU，7 类 archetype，`check_invariants()` 全空）；golden 指纹 +5 字段（区分原始解算 / IQR 排除 / 参与聚合）；invariant #2 门控改 `n_independent_evidence` + 新增 invariant 2b（核心模型被 IQR 排除却强一致性 → 缺陷）；新建 `tests/test_phase4_integrity.py` 9 用例锚定 10 条验收标准；修复 `test_providers_provenance.py`（BAC→ZZZZ）；Ruff clean（清理 3 处遗留）；pytest **240/240**；Pyright 未安装 (Session #22 ADR-038) |
| M-30 | **内部标准 Taxonomy + 五维公司拆解（黄金法则：经济学不得跨族决定 Identity）** | ✅ **DONE** | 新建 `classification/taxonomy.py`（99 节点树 / `BusinessModel` / `RevenueComposition` / `EconomicProfile` / `ExternalClassification` + `reconcile_identity` + `ConflictKind` + `economic_identity_ceiling`）；`node_from_yahoo()` 改「industry 优先」两段式（修复长 sector 短语压过具体 industry：AMZN→`cons.ecommerce`、KR→`cs.retail`）；`depth` 改由 parent 链推导；`MarketData.description` 采集 `longBusinessSummary`；`CompanyProfile` +8 shadow 字段（additive，路由不变）；规则/ML 双路径接线；新建 `tests/test_taxonomy.py` 48 用例；pytest **288/288**；golden 零漂移 (Session #23 ADR-039) |
| M-31 | ③ Revenue Composition 接入真实分部收入数据源 | ✅ **DONE** | 新建 `data/segment_revenue.py`（`Segment` / `SegmentRevenueResolver` / `segment_weights` / `to_revenue_composition`）：**FMP `/revenue-product-segmentation`（v4 flat / v3 legacy）为主源**，需 `FMP_API_KEY`；无 key → `[]`（绝不伪造）；类级 `_MEM` + `.cache/segment_revenue.json` 磁盘缓存（可离线复放）；`FinancialData` +`revenue_composition` 字段 + taxonomy 消费端读取。**关键纠错**：实测 SEC `companyfacts` JSON **不含**分部（dimensional）数据（AAPL `Axis`/`ProductOrService`/`StatementBusinessSegments` 计数均为 0）→ SEC 层明确排除（需整包 Financial Statement Data Sets 或 filing-instance XBRL 解析）(Session #26 ADR-042) |
| M-32 | **Taxonomy 从 shadow 层切换为参与路由（跨族冲突才覆盖 + 经济护栏）** | ✅ **DONE** | 新增 `taxonomy_routing_override()`（三道 gating：① 决策状态必须 `CONFIRMED`（`TAXONOMY_ROUTING_STATUSES`）；② canonical 身份须与**内部身份判定 `best_bt`**（非 `routing_bt`）**跨 identity family** 冲突；③ 经济特征护栏优先，`guard_blocked=True` 时拒绝资产轻目标）+ `ARCHETYPE_FAMILIES`（由节点树推导，与 archetype 不漂移）+ `same_identity_family()`；规则/ML 双路径接线（`_routed_business_type`）；`attach_taxonomy_profile(tp=...)` 复用同一 profile。**零重生成 golden**：同族差异（`MatureTech` vs `SaaS` 同属 `tech` 族）不覆盖 → ORCL/NBIS/CRWV 保持 MatureTech；pytest **429/429**；golden 零漂移 (Session #30 ADR-047) |
| M-39 | **M-38 生产化：`filing_evidence` 接入 `providers` 主链（FMP 缺 key 自动回退 SEC filing-instance XBRL）** | ✅ **DONE** | `data/segment_revenue.py::resolve_segments()` = 生产默认源链：**Layer 1** FMP `revenue-product-segmentation`（需 key）→ **Layer 2** SEC 10-K/20-F filing-instance XBRL（免 key、权威，惰性 import 避免与 `filing_evidence` 循环）；两层皆空 → `[]`（绝不伪造）。`data/providers.py` 改调 `resolve_segments(ticker)` → FMP 无 key / key 失效 / 额度耗尽 / ticker 未覆盖时**自动降级**到 SEC 一手分部，不再丢收入结构。仍为 shadow 数据填充（不改 `business_type`/路由），pytest **429/429**；golden 零漂移 (Session #30 ADR-046) |
| M-40 | **50 只跨行业蓝筹全量验证 harness（五问：分类 / 模型分配 / 估值方法 / 特殊情形 / Reverse DCF）** | ✅ **DONE** | 新建 `_batch_eval.py`（50 标的离线全量审计 → `_batch_eval_roundN.json`）+ `_audit_summary.py`（紧凑五问摘要）+ `_diag_risk.py` / `_audit_risk_detail.py`（增长序列诊断）；每轮一行可断言回归门 `50/50 = 100.0% \| routing_viol=0 \| defects=0`；Round 3 结果：Reverse DCF 量化 22 / bound-only 19 / 未量化 0 (Session #31–#33) |
| M-41 | **Reverse DCF 市场隐含预期：结构化 bound（sanctioned growth band 之外不伪造点估）** | ✅ **DONE** | `models/reverse_dcf.py::calculate` 输出 `implied_revenue_cagr_bound={kind, value, ev_at_bound}`（`above_band_ceiling`→「≥ 上限」/`below_band_floor`→「≤ 下限」）；normalized 救援仅在 `bridge_broken` 启用；Round 2 把 bound 结构化落进 `ExpectationGap` 并让 `_gap_section` 镜像措辞（消除同标的一 bound 一 N/A 的自相矛盾）(Session #31–#32) |
| M-42 | **Growth Risk 改「下行离散度」——消除 CV→0 爆炸与单调收购爬坡两类伪信号** | ✅ **DONE** | `analysis/risk.py::_growth_risk()` 从「总离散度 σ + CV」改为 `dd=RMS(min(growth,0))`（相对 0 的半离差，只捕捉营收收缩）；`config.py` 阈值 `growth_dd_medium=0.05` / `growth_dd_high=0.10`；结果 SO High→Medium、PLD/VICI/CEG/AMT 旗标消失，仅真实收缩标的（XOM/CVX/COP/NUE/PFE/MRNA/NEE/UPS/NKE/BA/SO）保留 (Session #33) |
| M-43 | **隐含 WACC 以无风险利率为下限（going-concern 折现率不得低于 Rf）** | ✅ **DONE** | `models/dcf.py::_estimate_wacc_breakdown()` 暴露 WACC 实际使用的 Rf（单一真理源）+ `models/reverse_dcf.py` 以 Rf 为 implied-WACC 下限（`wacc_lo = max(cfg, tg+spread, Rf)`）；目标 EV 连 Rf 都够不到 → `NO_SOLUTION_IN_RANGE` + `implied_wacc_floor_rf`（命名约束，不伪造）；修复 DUK 2.3% / SO 2.7% / CEG 3.3% 的 sub-Rf 反解；全 50 标的 `implied_wacc < 0.045` = 0 例 (Session #33) |
| M-44 | 隐含 FCF 利润率 / 隐含终值增长率 `<NO_SOLUTION_IN_RANGE>` 的 bound 措辞 | ⬜ TODO | 部分标的这两项仍无解；可套用 M-41 的结构化 bound 方式（输出「≥/≤ 边界 + ev_at_bound」而非 N/A）(Session #33 遗留) |
| M-34 | bottom-up 同业无杠杆 β 升级为 CAPM 输入（可选） | ✅ **DONE** | 升级为**业务身份三级筛选 + 完整 β 链**并接入 CAPM：`get_companies_by_business_identity(sub_industry, business_model, economic_profile)` 替换裸 `get_companies_by_industry(industry)`——L1 同子行业+商业模式 / L2 相邻行业+相似经济特征 / L3 Damodaran 基准（内置 `data/damodaran_beta.json` Jan 2026 快照，未覆盖→None）；链 = Peer Levered → Unlevered(Hamada) → Median → Cash-adjusted → Target Relevered；`wacc.py::calculate()` 三段优先级（bottom-up 优先、缺失回退回归 β、都无则 default），保持 `resolve_effective_beta()` 单一出口；`clamped` 语义修正；`MarketData` +`bottom_up_beta`/`bottom_up_beta_chain`；+20 用例；pytest **353/353**；golden 零漂移 (Session #25 ADR-041) |
| M-35 | Segment-level β（多业务公司按业务价值/权重整合） | ✅ **DONE** | `data/industry_beta.py` 新增 `derive_segment_level_beta()`：逐分部 label→行业（`_SEGMENT_INDUSTRY_KEYWORDS` ~65 条关键词→Yahoo 行业，具体优先）→ 复用 M-34 三级筛选求分部 β_u → 按权重（`segment_weights(by="value")`，营业利润占比优先、缺失回退收入）加权求和 → cash-adjust → target-relever；`level=0` / `source="segment-weighted"` / `IndustryBetaResult.segments` 审计明细；门控 `min_segments=2` + `_MIN_SEGMENT_COVERAGE=0.60`（不足→透明回退公司级 β）；`derive_bottom_up_beta(segments=...)` 优先分支；providers 接线（Auto）；+23 用例；pytest 353 → **376**；golden 零漂移 (Session #26 ADR-042) |
| M-36 | **M-35 收尾：FMP 多 key 轮换 + `/stable` 端点 + Shape C + 分部→行业关键词表数据驱动补全** | ✅ **DONE** | ① `data/segment_revenue.py` 支持 `FMP_API_KEY=key1,key2` **多 key 按序轮换**（`_fmp_keys`+`_from_fmp`，非 200/不可解析落下一 key，全耗尽→`[]`）；② 端点迁移 `/stable/revenue-product-segmentation`（v4/v3 legacy 自 2025-08-31 403）层优先序 `stable→v4→v3`；③ `_extract_fmp` 新增 **Shape C** 解析（元数据外层包裹嵌套 `data`，`fiscalYear`/`period` 不泄漏为分部）；④ `_SEGMENT_INDUSTRY_KEYWORDS` 以真实语料（90 票→172 label）**两轮补全**（覆盖 102→107；桶/地理/品牌名/缩写恒不映射）；+测试；pytest 376 → **382**；golden 零漂移；留存 `_discover_segment_labels.py` 供增量迭代 (Session #27 ADR-043) |
| M-37 | **商业理解层六模块映射 + 四态决策契约 + Identity Resolution** | ✅ **DONE** | ① `classification/taxonomy.py` 新增四态决策契约 `DecisionStatus`（CONFIRMED/PROBABLE/AMBIGUOUS/INSUFFICIENT_DATA）+ `decide_status()` 确定性映射 + `_ECONOMICS_ONLY_MIN_CONF=0.55`，写入 `CompanyProfile.taxonomy_decision_status`（shadow）；② 新建 `data/identity_resolver.py`（`IdentityResolver`：CIK/SIC/FIGI，Layer A 复用在位 SEC 链 + Layer B OpenFIGI 需 key，缺失一律 None 绝不伪造）；③ 新建 `classification/business_intelligence.py`（`extract_business_evidence()`：业务描述 + 分部收入 + provenance，缺失显式标注）；④ `data/industry_resolver.py` +`resolve_identity()`；⑤ 六模块映射（原位扩展、既有逻辑零迁移）；⑥ 三条架构原则落地（单源不覆盖 / ML 不直连 WACC / 缺证据不强赋高置信）；+16 用例；pytest 382 → **398**；golden 零漂移 (Session #28 ADR-044) |
| M-38 | **SEC 10-K / 20-F filing-instance XBRL 业务证据抽取 + 四态决策端到端测试** | ✅ **DONE** | ① 新建 `data/filing_evidence.py`：`FilingRef` + `FilingBusinessExtractor`（CIK → `data.sec.gov/submissions/CIK{cik}.json` 的 `filings.recent`（newest first）→ 首个 `10-K`/`20-F` → filing `index.json` 优选 `*_htm.xml` 实例）；`parse_segment_revenue(xml)` **纯函数**（`xbrli:context` → `(endDate, axis, member)`；**仅取带 segment 轴的事实**；`_AXIS_PRIORITY` 单轴；**排除合并总额**；**取最新期间**；instant 忽略；us-gaap + ifrs-full revenue concept）；drop-in 返回 `segment_revenue.Segment` + `source="sec-xbrl"`；`_MEM` + 磁盘缓存 + `offline` 零网络；无 CIK/实例/解析失败 → `[]`（绝不伪造）；② `tests/test_filing_evidence.py` 9 用例 + `tests/test_taxonomy.py::TestDecisionContractEndToEnd` 6 用例（真实 builder/classifier 全链路锁定四态 shadow 接线）；pytest **398 → 413**；golden 零漂移 (Session #29 ADR-045) |

---

## 🟢 LOW (有空做)
| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| L-01 | Web UI (Gradio / Streamlit) | ⬜ TODO | 不通过 Telegram 也能查估值 |
| L-02 | 每日监控 Watchlist 自动推送 | ⬜ TODO | 偏离内在价值 ±20% 时主动告警 |
| L-03 | 导出估值结果到 Google Sheets | ⬜ TODO | 用户已有使用 Google Sheets 的偏好 (user_profile 中提到) |
| L-04 | 回测模块: 过去5年低估/高估信号 | ⬜ TODO | 验证模型预测的前瞻性 |
| L-05 | 模型版本化: DVC 追踪数据集 | ⬜ TODO | labeling_dump.csv 每次标注更新后 commit hash |
| L-06 | 云原生部署到 Cloudflare Workers + Render | ⬜ TODO | user_profile 中提到的偏好架构 |
| L-07 | 增加 "合理价值区间" 而非单点 | ⬜ TODO | 结合 sensitivity 矩阵输出 Low/Base/High 三档价格 |
| L-08 | ~~**Phase 2：反向 DCF 升级为多变量求解（Constraint-based Solver）**~~ | ✅ **DONE → M-20** | 已升级为**约束式单变量隐含求解器**（one-at-a-time）：Implied Operating Margin / FCF Margin / WACC / Terminal Growth。**Note**：「多变量联合」判定为欠定（一方程多未知数 → 无穷多解），故采用单变量 + 其余固定基准；FCF Margin 经 flat-margin 桥独立化；报告显式标注「其余假设固定为基准」 (Session #07 → Session #16 → Session #17 ADR-030) |
| L-09 | 蒙特卡洛与模型集成口径统一 + 相关性校准 | 🟡 **PARTIAL** | 口径统一已做：MC `base_case` 模式零扰动锚点精确复现确定性 DCF（**DONE → M-25**）；相关性校准（驱动矩阵用历史协方差）仍 ⬜ TODO (Session #07 ADR-016 / Session #20 ADR-034) |

---

## ✅ 已完成 (最近)
| ID | 任务 | 完成日 | 备注 |
|----|------|--------|------|
| C-01 | 1001只股票特征数据收集 | 2026-10-05 | 1001 行 / 15 数值特征 / 0 fail |
| — | 批量生成 7 个项目文档 | 2026-10-05 | AGENT / README / TODO / CHANGELOG / DECISIONS / ROADMAP |
| — | 数据完整性验证 + CSV 去重 | 2026-10-05 | 从 1533 行 → 1001 行 (无重复 ticker) |
| — | NBIS 误估值修复 (Session #06) | 2026-10-27 | 数据对账层新建 + AI/Cloud peer 重路由 + P/E & EV/EBITDA 守卫 + 原型冲突扣减 + TVG floor 修复；pytest 61/61；NBIS/SOFI/AAPL 验证通过 |
| — | NBIS 第二版方法论修复 (Session #07) | 2026-10-27 | 覆盖率门控一致性 + 质量加权中位 + 估值可用性拆分 + 情景一致性 + AI Cloud 人工 peer 组 + WACC 三 beta/区间 + 反向DCF隐含量化 + 蒙特卡洛概率结论；pytest 61/61；demo NBIS + demo_fast SOFI/AAPL 验证通过 |
| — | NBIS 递归自我改进 3 轮 (Session #08) | 2026-11-03 | 报告自洽 + 极端终值门控 + 数据失真守卫；pytest 61/61 |
| — | JNJ 递归自我改进 3 轮 (Session #09) | 2026-11-03 | 分桶算术自洽 + 对账口径语义 + 风险展示诚实性；pytest 61/61 |
| — | 五项系统优化 (Session #10) | 2026-11-03 | Replacement NAV 覆盖率锚 + 对账反向校验 + Golden diff + Beta 统一 + REIT/Energy 覆盖；pytest 78/78 |
| — | 覆盖率第二条腿: EV/Sales + 单位经济学 (Session #11) | 2026-11-03 | NBIS 覆盖率 5/6 → 6/7；固定 APPROXIMATE 诚实标注；pytest 90/90 |
| — | CRWV 递归自我改进 3 轮 (Session #12) | 2026-11-03 | 原型重路由 + 口径冲突命名 + 派生态结构化；pytest 90/90 |
| — | SOFI 递归自我改进 3 轮 (Session #13) | 2026-11-03 | 银行 β/ke 口径统一 + 金融情景改走 Bank RIM + peer 置信度边界 `<=` 守卫；pytest 90/90 |
| — | 口径契约化 + 封顶审计 + 渲染层口径冲突 invariant (Session #14) | 2026-11-03 | `valuation/caliber.py` 契约 + 三层封顶审计 + invariant #6 + 金融运营 ROE 情景；pytest 95/95 |
| — | UPST 递归自我改进 3 轮 (Session #15) | 2026-11-12 | 分类子串误匹配（`keyword_hit()` 词边界）+ 金融 EV/Sales 剔除 + 渲染层口径泄漏（WACC→ke）；pytest 106/106；DEFECTS 空 |
| — | 估值引擎诚实性与一致性修复 (Session #16) | 2026-11-12 | 负终期 FCF 抑制（不伪正终值）+ 预测年限单一真源（消状态污染）+ 求解器残差检查；pytest 116/116；golden 有意漂移 1 字段 (ADR-028/029) |
| M-20 | Reverse DCF 约束式隐含求解器 (Session #17) | 2026-11-12 | Implied OM / FCF Margin / WACC / TG（one-at-a-time，硬边界不钳制 + 单调性 + 残差）；flat-margin 桥独立化 FCF margin；透传 + 渲染；pytest 124/124；golden 无漂移 (ADR-030) |
| M-21 | 求解器 P0/P1 加固（用户代码审查 6 项）(Session #18) | 2026-11-12 | 有效 bracket 重校验（拒可疑根）+ 单调性实测（多根/常数检测）+ 端点根 + 负终值抑制贯穿（SOLVED→APPROXIMATE）；自查修复 2 处真实缺陷；测试 +18；pytest 142/142；golden 无漂移 (ADR-031) |
| M-25 | **Phase 2：MC 双模式 + 路径锚点对账 + 经营/折现情景拆分** (Session #20) | 2026-11-13 | MC `base_case`/`historical` 双模式 + 去人为利润率地板 + 路径形参化（零扰动锚点 = DCF，MSFT/AAPL/NBIS +0.0%）+ 经营情景 vs 折现率情景拆分 + 报告透明化 + Wipeout 用词修正；测试 +14；pytest 217/217；golden 无漂移 (ADR-034/035) |
| M-26/27/28 | **Phase 3：WACC β 多窗口 + peer 来源溯源 + 同源证据去重** (Session #21) | 2026-11-13 | β 多窗口（2Y 周/3Y 月/5Y 月）+ bottom-up 槽位（ADR-036）+ peer 4 档来源标签+样本数 + `model_family` 同源证据去重（门控按独立证据数计票，ADR-037）；新增 `tests/test_phase3_integrity.py` 14 用例；pytest 231/231；新版文件 ruff clean；golden 无漂移 |
| M-29 | **Phase 4：全量回归 + 边界/验收用例断言化 + golden 指纹扩展** (Session #22) | 2026-11-13 | 回归域 9 → 18 只（7 类 archetype）；golden 指纹 +5 字段（原始解算 / IQR 排除 / 参与聚合）；invariant 2b（核心模型被 IQR 排除却强一致性 → 缺陷）；`tests/test_phase4_integrity.py` 9 用例锚定 10 条验收标准；修复 `test_providers_provenance.py`；Ruff clean；pytest 240/240 (ADR-038) |
| M-31/M-35 | **分部收入数据层 (M-31) + Segment-level β (M-35)** (Session #26) | 2026-11-14 | `data/segment_revenue.py`（FMP 分部收入，磁盘缓存，`to_revenue_composition`/`segment_weights`）+ `derive_segment_level_beta()`（分部 label→行业→三级筛选 β_u→按业务价值权重整合→cash-adjust→relever，`level=0`，门控回退公司级）；`FinancialData` +`revenue_composition`；providers 接线；pytest 353 → **376**；golden 零漂移 (ADR-042) |
| M-39 | **M-38 生产化：SEC filing-instance XBRL 接入 providers 主链（FMP 缺 key 自动回退）** (Session #30) | 2026-11-14 | `resolve_segments()` 源链（FMP → SEC filing-instance XBRL，两层皆空 → `[]`）；`providers.py` 改调源链 → FMP 缺 key/失效/未覆盖时自动降级到免 key 权威分部；仍 shadow 填充；pytest **429/429**；golden 零漂移 (ADR-046) |
| M-32 | **Taxonomy 参与路由（跨族冲突才覆盖 + 经济护栏）** (Session #30) | 2026-11-14 | `taxonomy_routing_override()`（CONFIRMED + 跨 identity family 冲突 + 经济护栏）+ `ARCHETYPE_FAMILIES`/`same_identity_family()`；规则/ML 双路径接线，对比 `best_bt`（非 `routing_bt`）；**零重生成 golden**（同族差异不覆盖，ORCL/NBIS/CRWV 保持 MatureTech）；pytest **429/429**；golden 零漂移 (ADR-047) |
| M-40 | **50 只跨行业蓝筹全量验证 + Reverse DCF 递归自我改进 3 轮** (Session #31–#33) | 2026-11-14 | `_batch_eval.py`（50 标的 → JSON）+ `_audit_summary.py`（五问）+ `_diag_risk.py`/`_audit_risk_detail.py`；Round 1 结构化 bound（sanctioned band 外不伪造点估）→ Round 2 报告双处边界口径统一 → Round 3 下行离散度（消 CV 假 High）+ Rf 下限（消 sub-Rf 隐含 WACC）；pytest **429/429**；`50/50 = 100.0% \| routing_viol=0 \| defects=0`；golden 二次有意重生成（全为 Growth Risk 移除/降级）(ADR-048) |

---

## 💡 注意事项
1. **严禁重复做 C-01**：1001 行 CSV 已完成，任何修改只需 UPDATE，不需要重新跑 `_dump_features_for_labeling.py`
2. **C-02 人工标注**是当前唯一 BLOCKER，所有后续任务都依赖它
3. 如果 C-05 评估准确率 <90%：先回到标注纠错 (预计有 5-10% 边界错误正常)，再考虑加特征 (M-02/M-03)
