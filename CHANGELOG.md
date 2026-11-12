# 📝 CHANGELOG.md — 版本变更记录
> 格式: [语义化版本 vX.Y.Z] - YYYY-MM-DD  (或 Session 编号用于未发布)
> 分类: ✨ Added / 🔧 Changed / 🐛 Fixed / 🗑️ Removed / ⚠️ Deprecated / 🔒 Security

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
