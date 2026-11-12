# 🤖 AGENT.md
Version: 3.0
Last Updated: 2026-11-12 20:36
Project Status: 🟢 UPST Recursive Self-Improvement (3 rounds) — Short-token boundary matching (FinTech misroute) + Financial EV/Sales exclusion + Render-layer caliber leak (WACC→ke / EV re-check) (Session #15)

> **Purpose**
>
> This file is the single source of truth for every AI Agent working on this project.
>
> Every AI Agent MUST read this file BEFORE starting any task.
> Every AI Agent MUST update this file BEFORE ending a session.
>
> This prevents duplicated work, loss of context, and repeated analysis when switching between ChatGPT, Claude, Gemini, Codex, Cursor, OpenHands, or any other AI assistant.

---

# 1. Project Information

## Project Name

通用估值引擎 Telegram Bot (Universal Valuation Engine Telegram Bot)

## Repository

https://github.com/felixwongyh/telegram-stock-valuation-engine

## Owner

Felix Wong

## Objective

构建一个通用股票估值引擎，通过 Telegram Bot 接口提供服务，支持：
- DCF (现金流折现) / NAV (净资产) / Reverse DCF (反向估值) 等多模型
- WACC 7步法实时计算 (Rf, Beta, ERP, CAPM, Cost of Debt, Tax, Cap Structure)
- 终值增长率动态约束 (min(企业增长, 名义GDP, WACC - 0.5%))
- 敏感性分析矩阵 (WACC × g 双维度 + 稳定性分级)
- ML 增强的商业模式分类器 (LightGBM + TF-IDF, 11类 BusinessType)
- 多模型协议裁决 / 置信度加权

---

# 2. Current Status

Project Phase

- ⬜ Planning
- ⬜ Designing
- ✅ Developing
- ⬜ Testing
- ⬜ Deployment
- ⬜ Maintenance

Current Task

```
✅ 已完成：真实标注数据 1000 行 × LightGBM 重训 (train_acc=97.40%)
✅ 已完成：demo_fast / 16 只 sanity 股票分类正确性验证 (12/16 = 75%)
✅ 已完成 Session #04：SOFI 报告三问修复（置信度透明化 + 混合业务 Hybrid + 金融机构指标口径）
✅ 已完成 Session #05：直观标签 (Intuitive Labels) 上线 + demo_fast NU 文案 bug 修复
✅ 已完成 Session #06：NBIS 误估值修复（用户实测报告暴露的 3 类缺陷）
  - Step A: 数据对账层 data/reconciliation.py 新建（10 项交叉校验，只读，不突变 FinancialData）
  - Step B: 细粒度 peer 桶 + AI/Cloud Infrastructure 重路由（models/multiples.py）
  - Step C: P/E 无意义守卫（隐含 PE>100x）+ EV/EBITDA D&A 主导守卫（EBITDA>90% 营收）
  - Step D: 资产轻原型冲突置信度扣减（ml_classifier.py；capex/revenue≥1.0 且负 FCF → cap 50%）
  - Step E: terminal_growth.py 0≤base<1.5% 分支修复（抬高到成熟地板而非坍缩到 0.5%，同时解决历史遗留失败测试）
  - 验证：pytest 61/61 全通过；demo_fast NBIS/SOFI/AAPL 三只端到端通过
✅ 已完成 Session #07：NBIS 第二版方法论修复（用户对第二版报告的 7 点批评）
  - 问题 #1（最严重）: 一致性覆盖率门控 — 2/6 覆盖率不得输出 Very Strong（gated_cv = base_cv × 覆盖因子 ÷ 质量因子 + 硬覆盖率封顶）
  - 问题 #2: 质量加权中位数（DCF TV/EV>80% 降权、APPROXIMATE 降权）+ 低置信模型集成值命名
  - 问题 #3: 估值可用性评分（与源数据质量分离）+ 股数偏差 >25% 抑制每股公允值
  - 问题 #4: 情景一致性 — 负每股价值 floor 到 0 + "当前价高于全部情景" 文案 + 公允区间标注 n/覆盖率
  - 问题 #5: 人工 AI Cloud/GPU Infra peer 组（CoreWeave/IREN/Equinix/Oracle）+ 分类置信度<55% 倍数再降权
  - 问题 #6: WACC 三 beta 透明化（raw/winsorized/bottom-up）+ WACC 行业区间估值 + 反向 DCF 隐含增长量化
  - 问题 #7: 蒙特卡洛概率结论 P(内在>价格)/P(高估>30%)/P(股权归零) + 驱动因子相关性 + 负值 floor
  - 验证：pytest 61/61 全通过；demo NBIS + demo_fast SOFI/AAPL 三只端到端通过
✅ 已完成 Session #08：NBIS 递归自我改进 3 轮（上一轮报告作为下一轮起点）
  - 方法：Round 0 基线（_recursion_round0.txt）→ 每轮「评估产出 → 定位缺陷 → 修代码 → 重跑」→ 下一轮以新产出为起点
  - Round 1（报告自洽）：① 增长标题桶与 bullet 桶不一致（header 高速 vs bullet 爆发式）→ 统一分档；② 业务类型 headline 未反映资产轻原型冲突重路由 → 新增 effective_business_type 并渲染「SaaS → AI/Cloud Infrastructure」
  - Round 2（极端终值门控）：DCF TV/EV=499% 的点估值按分级降权（0.5/0.25/0.1），NBIS DCF 权重 0.5→0.1 → **质量加权中位估值 $30.37(DCF) → $26.41(EV/Sales)**；新增「DCF point value unreliable / 极端终值占比重估」告警
  - Round 3（数据失真守卫）：① 反向 DCF 负「EV 上限」改述为「即便 80% CAGR 上限 EV 仍为负」；② 风险边际 CV=1.02(mean -1143%) 为近零营收基期失真 → 剔除 <10% 峰值营收的基期，不足 3 期降级为 Low；NBIS 风险 High→Medium（50→58）
  - 验证：每轮 pytest 61/61 全通过；NBIS 3 轮端到端 + SOFI/AAPL 回归全通过
✅ 已完成 Session #09：JNJ 递归自我改进 3 轮（上一轮报告作为下一轮起点）
  - 标的：JNJ（成熟高股息医药，Beta −0.09，6 模型 5 解算）— 与 NBIS 完全对立的画像，压力测试引擎另一端
  - 方法：Round 0 基线（_recursion_jnj_round0.txt）→ 每轮以新产出为起点「评估产出 → 定位缺陷 → 修代码 → 重跑」
  - Round 1（分桶算术）：`n_total` 计入 ReverseDCF 却从 solved 中排除且不落 buckets → `适用6·解算5·失败0·合计6`（5+0+0≠6）+ **虚假** `1 of 6 applicable models failed`；新增仅展示桶使 `适用 = 解算 + 失败` 恒等；ReverseDCF 由 `[估值合理]` 改标为「反向求解＝当前价，非独立估值」
  - Round 2（对账口径语义）：滚动 P/E 不一致（供应商 26.4x vs GAAP 隐含 43.9x，−40%）原判「盈利基数极不稳定」，实为 non-GAAP/正常化 EPS 口径差 → 改为方向感知文案
  - Round 3（风险诚实性）：① FCF Yield Gap 对 JNJ（正 FCF $19.6B、转化 1.22）误报 High → 新增「正 FCF+健康转化+非高增长」降级守卫（High→Medium，评分 75→80）；② 市场区原始 β=−0.09 与 WACC 截断值 0.30 自相矛盾 → 市场区追加上下文标注
  - 验证：每轮 pytest 61/61 全通过；JNJ 3 轮端到端 + NBIS/SOFI/AAPL/JPM 回归全通过（4 只均 exit=0）
✅ 已完成 Session #10：五项系统优化落地（覆盖率 / 对账反向校验 / Golden diff / Beta 统一 / REIT+Energy 覆盖）
  - 优化 ①（覆盖率瓶颈）：新增 `models/replacement_nav.py`（Replacement-cost NAV：`equity = book_equity + net_ppe×(factor−1)`，net_ppe=Σcapex−ΣD&A，默认 factor 1.15）+ 分类器动态入桶（`_is_replacement_nav_candidate`：重资本 capex/revenue≥0.30 + 负 FCF/亏损 + net_ppe>0，排除金融/REIT）→ **NBIS 覆盖率由 2/3 提升至 5/6 解算**（不再靠降权规避）
  - 优化 ②（对账反向校验）：`data/reconciliation.py` 新增写侧 `apply_overrides()`（偏差 >25% → 自动改用内部推算值并标注）+ `OverrideRecord`/`OverrideLog` 审计链 + 股数守卫（恒等式自洽→仅标注 / 破坏→按市值/价格反推）；`data/validator.py` 接入；`reporting/dashboard.py` 渲染「🩹 对账自动修正（偏差 > 25% 时改用内部推算值）」
  - 优化 ③（递归自改进工程化）：新增 `tests/golden_report.py`（9 只 BASKET：AAPL/MSFT/NVDA/JPM/PLD/NOW/NBIS/AMT/XOM → 19 字段稳定指纹 + `check_invariants()` 5 类自相矛盾清单）+ `tests/test_golden_report.py`（可断言的 golden diff，`UPDATE_GOLDEN=1` 刷新基线）+ `tests/golden/report_fingerprints.json`
  - 优化 ④（Beta 全链路统一）：`valuation/wacc.py::resolve_effective_beta()` 成为唯一出口（wacc_breakdown → provider → fallback），市场区 / WACC / 风险旗标三处共用；golden `check_invariants()` 断言 β 三处一致
  - 优化 ⑤（REIT + Energy）：新增 AMT（tower REIT → REIT NAV 4/4）与 XOM（Energy → 5/5 Strong）合成 fixtures + 回归断言；覆盖剩余资产结构
  - 验证：pytest **78/78 全通过**（61 → 78，新增 17 个用例）；golden 整篮 9 只无缺陷（defects 为空）；NBIS/PLD/AMT/XOM 端到端回归报告产出
✅ 已完成 Session #11：单位经济学模型族（EV/Sales + 单位经济学）落地 — 补齐 Session #10 覆盖率锚的另一半
  - 优化（模型族补充）：新增 `models/unit_economics.py::UnitEconomicsSalesModel`
    （模型名 `EV/Sales (Unit Econ)`）：`capacity_revenue = max(TTM_rev, Σcapex−ΣD&A × BENCHMARK_YIELD=0.35)`
    → `EV = capacity_revenue × MATURE_EV_SALES=4.0 × ramp_discount`，`ramp_discount = (1+WACC)^−(RAMP_YEARS×利用率缺口)`，
    WACC 复用统一 7 步法；利用率缺口 = 1 − (当期营收/净 PP&E) / 成熟基准 → 即「GPU 稼动率 × ARPU」的单一可观测代理
  - 分类器动态入桶 `_is_unit_economics_candidate`（重资本 capex/revenue≥0.50 + 负 FCF 或亏损 + net_ppe>0，排除金融/REIT）
    → **NBIS 覆盖率由 5/6 提升至 6/7 解算**（资产法 floor + 单位经济学 earnings-power 双独立锚）
  - 诚实性：数据层无 GPU 稼动率/ARPU 明细字段 → 单位资产营收为派生代理，结果固定返回 `SolverStatus.APPROXIMATE`（绝不 SOLVED）
  - 验证：pytest **90/90 全通过**（78 → 90，新增 12 用例 `tests/test_unit_economics.py`）；golden 整篮 9 只无缺陷；NBIS 端到端回归 $27.02/股
  - 观测（诚实记录，非缺陷）：NBIS 新增 $27.02（介于簇 6.8–14.4 与 DCF 38.39 之间）→ IQR 上界被抬高，DCF（TV/EV=404%）不再被离群过滤 → 一致性由「Weak」如实降为「Very Weak」（离散度 247.5%）。覆盖率提升与离散度上升均为真实信号，未做任何数值调参规避。
✅ 已完成 Session #12：CRWV 递归自我改进 3 轮（原型重路由 + 口径冲突命名 + 派生态结构化；详见下方 Change Log）
✅ 已完成 Session #13：SOFI 递归自我改进 3 轮（银行模型 β/ke 口径统一 → 金融情景口径 → peer 置信度边界）
  - 标的：SOFI（SoFi Technologies，银行 / 金融科技，β=2.07，3 解算 + 1 不适用）— 与 NBIS/CRWV 的「重资本高增长」画像完全对立，压力测试引擎的**金融适配**分支
  - 方法：round1 → round2 → round3，每轮以「上一轮报告产出」为起点「评估产出 → 定位缺陷 → 修代码 → 重跑」；`_recursion_run.py SOFI roundN --real`
  - Round 1（β/ke 口径统一）：Bank DDM/RIM 统一走单一 β 出口 `resolve_effective_beta()` + 与 WACC/情景同源 Rf/ERP → 银行模型 CAPM `ke` 不再与全报告其它区撕裂；新增 `_BANK_KE_BAND=(7%,10%)` 越界提示（SOFI ke=15.39%，β=2.07）
  - Round 2（金融情景口径）：情景分析区仍走 DCF（WACC 15.1%，$12.61~15.94）而主模型 Bank RIM 给 $9.52 → **口径相反却未命名**。修复：`analysis/scenario.py` 新增 `_run_financial_scenarios()`（Bank RIM 沿 ke 变动，β±0.30）→ 情景 $9.26 / $9.52 / $9.79（跨度 22% → **6% SV**）；`reporting/dashboard.py` 情景区按 `discount_label` 渲染 `ke` 口径 + 敏感性区替换为金融说明文案
  - Round 3（peer 置信度边界）：SOFI 置信度被截断到**恰好 0.55**，但守卫用严格 `< 0.55` → P/E、P/B 漏标 `NOT FULLY VALIDATED`。修复：`models/multiples.py` 提取常量 `_PEER_MULTIPLE_CONF_FLOOR=0.55` 并改 `<=` → P/E、P/B 均标注警告；质量因子 1.00 → **0.67**、一致性 Moderate → **Weak**（门控 CV 24.5% → 36.7%，真实信号）
  - 验证：每轮 pytest **90/90** 全通过；SOFI 3 轮 + JPM round3 端到端 `check_invariants()` DEFECTS 均为空；golden 基线重生成（JPM Bank RIM 漂移，已审阅）
✅ 已完成 Session #14：Session #13 收尾 5 项优化落地（口径契约 / 封顶审计 / invariant / 阈值锁定 / 金融运营情景）
  - 优化 ①（口径即契约）：新增 `valuation/caliber.py`（`MetricMeaning` + `DiscountCaliber` + `CaliberContract` + `build_caliber_contract`）；`reporting/dashboard.py` 删除内联 `is_fin`/`is_reit` 猜口径，改为消费契约（EV/净债务/EV/EBITDA/FCF 的 N/M 与附注、敏感性是否适用全部来自契约）
  - 优化 ②（M-15 封顶审计）：新增 `tests/test_cap_boundary_guard.py` 三层审计；**跨文件** Part C 捕获并修复 `models/sotp.py` 的 `conf < 0.55`（上游 `classifier.py:509` 封顶到恰好 0.55）→ 改 `<=`（ADR-023 同类）
  - 优化 ③（M-12 渲染层口径冲突 invariant）：`tests/golden_report.py::check_invariants()` 新增 invariant #6——情景 `discount_label` 必须 == 引擎口径；golden 指纹新增 `caliber`/`scenario_calibers`（19 → 21 字段）
  - 优化 ④（M-16 数据驱动）：hybrid 阈值提为具名常量 `HYBRID_FIN_TO_TECH_FLOOR=0.08`（**锁定而非下调**）+ `tests/test_hybrid_threshold_lock.py` 边界断言；根因 sector/industry 缺失属特征问题，待 H-03 补数据源
  - 优化 ⑤（金融情景深化）：金融情景升级为 **ke + 经营性 ROE 双驱动**（`models/bank.py` 新增 `roe_override` + `roe_source`；`analysis/scenario.py` 新增 `_FIN_ROE_SHOCK=0.20`，驱动文案「折现率 ke ↑ + 经营性 ROE ↓」）
  - 验证：pytest **95/95 全通过**（90 → 95）；SOFI / JPM round3 `DEFECTS: []`；golden 基线重生成（仅新增 2 字段漂移，已审阅）
✅ 已完成 Session #15：UPST 递归自我改进 3 轮（分类子串误匹配 → 金融 EV/Sales 剔除 → 渲染层口径泄漏）
  - 标的：UPST（Upstart Holdings，消费信贷 FinTech，β 原始 2.96→截断 2.50）— 压力测试引擎的**金融适配 + 短 token 关键词**两个薄弱面
  - 方法：round1 → round2 → round3，每轮以「上一轮报告产出 + 指纹」为起点「评估产出 → 定位缺陷 → 修代码 → 重跑」；`_recursion_run.py UPST roundN --real`
  - Round 1（分类子串误匹配，round0 基线最强缺陷）：UPST 被 `_structural_overrides` 的工业关键词 `"ups"`（UPS 快递）**子串误匹配** ticker `upst` → 强制 `Structural FORCE->Industrial`，覆盖了正确的 FinTech 判定 → 走 `DCF/EV-EBITDA/FCF-Yield`（对借贷型业务无意义），DCF=$0.00、ReverseDCF 无解、情景三档全 $0.00、一致性 Very Weak。修复：`classification/ml_classifier.py` 新增边界感知 `keyword_hit()`（裸 ASCII ≤4 字符 token 强制词边界 `(?<![a-z0-9])…(?![a-z0-9])`，长词/带空格/CJK 保留原子串语义）→ UPST 分类 FinTech（p=99.1%），模型路由改为 `Bank DDM/Bank RIM/P/E/P/B`
  - Round 2（金融 EV/Sales 剔除）：round1 报告同页自相矛盾——市场区打印「EV: N/M（金融机构不适用）」，却仍用 `EV/Sales` 作估值锚（$42.16，为区间唯一离群值，Very Weak 的主因）。修复：`classification/classifier.py::_model_applicability` 金融分叉新增 `EV/Sales` 剔除（与 `EV/EBITDA/FCF-Yield` 同族）→ 一致性 Very Weak → **Moderate**，中位估值 raw==weighted（$9.61），离散度 316% → **36.2%**
  - Round 3（渲染层口径泄漏，违 ADR-022/024）：① 公允区间附注硬编码「建议以 EV 口径复核」而 EV 对金融标的已声明 N/M → 改为读口径契约、金融标的给「P/B、P/E、RIM 口径复核」；② 风险区把模型层 `RiskType.WACC` 原样渲染为「WACC Risk」，但本标的贴现口径为 `ke`（无 WACC）→ `_risk_section` 按 `DiscountCaliber.COST_OF_EQUITY` 重标为「Cost of Equity Risk（权益成本/β）」；③ 市场区 β 附注硬编码「WACC 统一采用截断值」→ 改中性「折现率」
  - 验证：pytest **106/106 全通过**（95 → 106，历史累计用例）；UPST round1/2/3 `check_invariants()` DEFECTS 均为 `[]`；非金融回归确认 EV/Sales 未误伤（AAPL/XOM 保留、REIT/Bank 不含）
下一步：优化 CSV 特征缺失补全 (sector/industry + interest/revenue, H-03) → 扩充训练集到 5000 → Optuna 超参调优 → 95%+
```

Overall Progress

```
93%
- 估值引擎核心: 99% (✅ 覆盖门控 + 质量加权中位 + WACC 区间 + 概率结论 + 反向DCF隐含量化 + Beta 单一出口 + Replacement NAV 覆盖率锚 + Unit-economics EV/Sales 模型族 + 金融机构 β/ke 统一 + 金融情景 Bank RIM + 口径契约 + 金融运营 ROE 情景)
- Telegram Bot: 85%
- ML 分类器: 92% (✅ 置信度审计链 + Hybrid 暴露度 + 资产轻原型冲突扣减 + hybrid 阈值锁定)
- 报告直观度: 93% (✅ Overview 首屏结论 + 数据对账 + 对账反向校验渲染 + 覆盖率门控 + 概率语言 + 单位经济学模型 + 金融情景 ke 口径渲染 + 口径契约驱动渲染)
- 测试覆盖率: 68% (✅ 95/95 passing，含 golden diff 回归套件 + 单位经济学用例 + 封顶审计 + 口径 invariant)
```

Current Pipeline Step

```
Pipeline Step: Coverage Model Family (Replacement NAV + Unit-econ EV/Sales) + Financial Caliber Unification → Feature Imputation (sector+industry+interest) → Label Correction → Optuna → v2.2 Release
```

Priority

- 🔴 Critical
- 🟠 High (当前: 优化特征补全 + 分类准确率)
- 🟡 Medium (当前: 保持 SOFI 修复成果向后兼容)
- 🟢 Low

---

# 3. Current Context

This section explains the current working context.

What has already been completed?

✅ 项目骨架完成 (main.py, config.py, 所有模块目录结构)
✅ Yahoo Finance 数据提供者 (异步httpx + 4h JSON缓存 + 合成数据回退)
✅ 15个数值特征提取器 (extract_numerical_features)
✅ WACC 7步法实时计算引擎
✅ 终值增长率 TVG 动态约束逻辑
✅ DCF / Reverse DCF / NAV / Bank / SOTP / Multiples 模型
✅ 敏感性分析矩阵 + 稳定性分级
✅ 确定性 BusinessClassifier 规则分类器 (~85%准确率)
✅ LightGBM 合成数据训练版本 (v2.0-synthetic, 1500样本)
✅ 1001只真实股票的特征数据收集 → 修正后 1000行 (labeling_dump.csv, L2 PowerShell垃圾行已验证不存在)
✅ ✨ 真实标注版 ML 训练发布 v2.1-real-data-train1000
  - train_acc = 97.40% on 1000 真实标注样本, 11 类别完整
  - TrainMeta.version/note 已在 _train_from_scratch() 末尾 overwrite 为 real-data trained
  - 删除了旧 synthetic artifacts (3 个 .pkl)
  - demo_fast 16 只 sanity 股票验证: 12/16 = 75% (边界类受文本特征缺失影响)
✅ ✨ ✨ 新完成 (Session #05 — 直观标签 Intuitive Labels 上线 + bugfix):
  Step A: 探索报告渲染链 — build_report() → 11 个 section → ValuationPipeline 挂 verdict 到 profile.valuation_verdict/growth_verdict
  Step B: 数据结构设计 — data/models.py GrowthVerdictCard (8 字段 + bullet_lines()) + ValuationVerdictCard (10 字段 + header_lines(include_headline=True))
  Step C-1: 计算逻辑 reporting/verdict_intuition.py (纯函数，零副作用)
    • build_growth_verdict(gap): 营收/FCF CAGR 分桶 → 5 类中文标签（爆发式/高速/稳健/温和/低速/负增长）+ 预测 vs 历史 pp 差值一句直观总结
    • build_valuation_verdict(agreement, scenarios, ...): median vs price 7 档标签（显著高估/高估/小幅高估/合理/小幅低估/低估/显著低估）+ 情景跨度宽窄 + 公允区间 + caveat 串；最终 headline_summary + emoji (🟩/🟢/🟡/🟠/🔴)
  Step C-2: reporting/dashboard.py 多区块渲染：
    • Overview 区 (最顶部)：合并 header_lines() + growth.bullet_lines()，用户首屏直接看到结论
    • Gap 区：末尾追加「增长直观解读」(growth verdict)
    • Agreement 区：展示「估值细节拆解」(header_lines(include_headline=False))，避免与 overview 一句话结论重复
  Step D Bugfix (NU demo 输出实际问题):
    • Bug 1: 中位估值主语重复 → models.py: detail = f"（中位估值 {detail}）" → 去掉多余前缀
    • Bug 2: overview + agreement 双重展示一句话结论 → header_lines() 加 include_headline kw，agreement section 传 False，title 改为「估值细节拆解」而非「一句话估值」
  回归验证：pytest 51/52 (1 个 TVG floor 历史遗留无关失败)；demo_fast NU/SOFI/AAPL 三只全通过。
✅ ✨ ✨ 新完成 (Session #07 — NBIS 第二版方法论修复, 用户 7 点批评):
  - 核心洞察：用 2/6 个低置信模型得「Very Strong + 显著高估」是统计假象（幸存者偏差）。修复=覆盖率门控 + 质量加权。
  - Step A: analysis/model_agreement.py 重写 — 三桶分类 (solved/not_applicable/failed) + 覆盖率门控 (gated_cv = base_cv×覆盖因子÷质量因子) + 硬覆盖率封顶 (solved≤1→Very Weak, ==2→Weak, ==3→Moderate) + 质量加权中位数 + 低置信分类再降权 (w×0.5)
  - Step B: simulation/monte_carlo.py 重写 — P(内在>价格)/P(高估>30%)/P(股权归零) + 4×4 驱动因子 Cholesky 相关抽样 + 负值 floor 计入归零概率
  - Step C: data/validator.py + data/models.py — 估值可用性评分（与源数据质量分离）+ reconciliation_mismatches 计数 + usability_label()
  - Step D: reporting/verdict_intuition.py — 情景一致性（"当前价高于全部情景"）+ 负价值 floor 文案 + 公允区间标 n/覆盖率 + 股数不可靠抑制每股要素
  - Step E: valuation/wacc.py (三 beta 透明化 + 区间提示) + models/dcf.py (WACC 行业区间估值) + models/reverse_dcf.py (隐含增长量化) + models/multiples.py (AI Cloud 人工 peer 组)
  - Step F: reporting/dashboard.py 渲染新字段（模型分桶/门控明细/质量加权中位/估值可用性/概率结论/WACC 区间/Beta 透明度）
  - 验证：pytest 61/61 全通过；demo NBIS（一致性 Very Strong→Weak，估值可用性 34/100，P(高估>30%)=97.5%）+ demo_fast SOFI/AAPL 三只全通过

What is currently being developed?

正在进行下一步优化：特征补全 (sector/industry + interest/revenue) 以把 sanity 准确率从 75% 推到 90%+，以及 Optuna 超参调优。SOFI 三问修复 + NBIS 两轮方法论修复均已落地并冻结，后续修改不破坏本次新增数据契约（一致性门控字段 / 估值可用性评分 / 概率结论字段）。

What should NOT be repeated?

❌ 不要重新设计 WACC 7步法逻辑
❌ 不要重新运行1000只股票的数据收集 (已完成于 classification/labeling_dump.csv)
❌ 不要修改 YahooFinanceProvider 的缓存策略 (4h TTL + 原子写入已成熟)
❌ 不要重建确定性分类器规则
❌ 不要删除 _ml_artifacts 下 3 个 .pkl (刚训练好的 v2.1 版本)

Current thoughts:

```
真实标注版 v2.1 已发布：train_acc=97.40% (n=1000)，11 类别分布平衡。
Sanity 准确率 12/16=75% 符合预期，4 个边界误判主要根因：
  1) 文本特征 sector/industry 缺失率 83% (Yahoo 401) → 仅靠 company_name TF-IDF 信号不够区分 MatureTech↔Semiconductor
  2) interest/revenue 为 0 的占 82% → Bank/REIT/Utilities 三个高杠杆/高利息类的关键数值信号缺失
  3) Semiconductor 类别样本过少 (29/1000=2.9%) → 类别不平衡导致 AVGO 误判成 MatureTech (CSV 内 AVGO 本身就标成了 MatureTech！标签错误)
  4) 结构覆盖 Structural Overrides 对边界情况生效但无法完全纠正

下一步关键优化方向（已排入 Pending Tasks）：
  A. 特征补全：用 Alpha Vantage / yfinance.info 补全 sector + industry + interest_expense
  B. 标签纠错：检查 CSV 中 AVGO=Semiconductor 是否被错标为 MatureTech（当前就是错的！）
  C. 超参调优：Optuna 搜索 LightGBM params (learning_rate, num_leaves, min_data_in_leaf, class_weight)
  D. 类别平衡：SMOTE / class_weight='balanced' 处理 Semiconductor/Insurance 等少数类
```

---

# 4. Completed Tasks

| ID | Task | Status | Date | Notes |
|----|------|--------|------|------|
| 001 | 项目架构设计与模块划分 | ✅ Done | 2026-09 | 8个模块: data, valuation, models, analysis, classification, simulation, forecasts, reporting, telegram_bot |
| 002 | YahooFinanceProvider 异步数据获取 | ✅ Done | 2026-09 | semaphore=8, 4h cache, synthetic fallback |
| 003 | WACC 7步法实时计算 | ✅ Done | 2026-09 | Rf→Beta→ERP→CAPM→CostDebt→Tax→CapStruct |
| 004 | DCF + Reverse DCF 模型 | ✅ Done | 2026-09 | 含TVG约束 |
| 005 | 敏感性分析矩阵 | ✅ Done | 2026-09 | WACC×g双维度 + 稳定性分级 |
| 006 | 确定性 BusinessClassifier | ✅ Done | 2026-09 | 11类, ~85%准确率 |
| 007 | LightGBM ML 分类器(合成版) | ✅ Done | 2026-09 | 1500合成样本, train_acc≈98% |
| 008 | 结构覆盖规则 (Structural Overrides) | ✅ Done | 2026-09 | Bank/REIT/Semi/Util 数值强规则 |
| 009 | Telegram Bot 集成 | ✅ Done | 2026-09 | python-telegram-bot |
| 010 | 🔴 1001只股票特征数据收集 | ✅ Done | 2026-10-05 | classification\labeling_dump.csv (最终1000行有效, L2垃圾行验证已清除) |
| 011 | ✨ 真实标注版 LightGBM v2.1 训练发布 | ✅ Done | 2026-10-05 | 删除synthetic旧artifacts → 重训 → train_acc=97.40%, n=1000 → TrainMeta.version/note overwrite |
| 012 | demo_fast 分类正确性验证 (16 只 sanity) | ✅ Done | 2026-10-05 | 12/16 = 75%，4 个误判均为 MatureTech/Semiconductor/REIT/Utilities 边界重叠，归因：sector缺失83% + interest缺失82% + Semiconductor样本2.9% |
| 013 | 🔴 SOFI 报告问题 #1：置信度 66.6%→55% 黑盒透明化 | ✅ Done | 2026-10-08 | 新增 ConfidenceAdjustment dataclass，记录 Unknown cap + Missing-sector cap 两步扣减明细；_business_section() 渲染「ML → Δ → Final」三行拆解 |
| 014 | 🔴 SOFI 报告问题 #2：混合业务 Hybrid 分类表达 | ✅ Done | 2026-10-08 | 不扩 BusinessType 枚举，新增 is_hybrid / primary / secondary / hybrid_label / 5 轴 BusinessExposure[]；三条触发规则(Fin→Tech/Tech→Fin/Low-separation)；SOFI 正确输出 Hybrid Financial Institution |
| 015 | 🔴 SOFI 报告问题 #3：金融机构 FCF/EV/Net Debt 指标口径错配 | ✅ Done | 2026-10-08 | 7 层机构敏感适配：profile.cash_flow/leverage/capital_intensity + RiskAnalyzer 三个风险函数跳过 FCF + reporting.market_section 加 caveat；SOFI risk 80→95 |
| 016 | ✨ 直观标签数据结构 (Verdict Cards) + 计算逻辑 | ✅ Done | 2026-10-08 | reporting/verdict_intuition.py 新建：build_growth_verdict() (营收/FCF CAGR 分桶 + 预测vs历史一句总结) + build_valuation_verdict() (7档高估/低估 + 情景跨度宽窄 + headline + caveats)；data/models.py 新增 GrowthVerdictCard.bullet_lines() + ValuationVerdictCard.header_lines(include_headline=True) |
| 017 | ✨ 报告多区块直观文案渲染 (Overview/Gap/Agreement) | ✅ Done | 2026-10-08 | dashboard.py：_intuitive_overview_section() (首屏一句话+增长) + _gap_section() 末尾追加增长直观解读 + _agreement_section() 展示估值细节拆解(include_headline=False 避免重复) |
| 018 | 🐛 demo_fast NU 输出文案 bug 双修复 (主语重复 + headline 重复) | ✅ Done | 2026-10-08 | Bug1: ValuationVerdictCard.header_lines() detail 前缀「中位估值」删除（median_vs_price_detail 已是完整句子）；Bug2: agreement section 改为 include_headline=False + 标题从「一句话估值:」→「估值细节拆解:」；pytest 51/52 + NU/SOFI/AAPL 三只验证通过 |
| 019 | 🔴 数据对账层 (Cross-field Reconciliation) | ✅ Done | 2026-10-27 | 新建 `data/reconciliation.py`：10 项交叉校验 (mcap≈price×shares / EV≈mcap+debt−cash / TTM EPS≈NI/shares / trailing P/E≈price÷EPS / EV/EBITDA / P/B / EV/Sales / TTM FCF≈OCF+capex / market shares≈annual shares / EBITDA≤营收)；纯只读；容差 5%(恒等式) / 20%(供应商口径) / 25%(股数)；仪表盘渲染不匹配项 |
| 020 | 🔴 细粒度 peer 倍数桶 + AI/Cloud Infrastructure 重路由 | ✅ Done | 2026-10-27 | models/multiples.py：技术族拆分为 Software-SaaS / Software-Mature / Semiconductors / AI/Cloud Infrastructure（P/E 35 / EV-EBITDA 18 / EV-Sales 8）；新增 `_resolve_peer_bucket()` + `_compute_infra_override()`（capex/revenue≥1.0 + 负 FCF + Very Capital Intensive + 高增长 → 重路由到 AI/Cloud） |
| 021 | 🔴 无意义倍数守卫：P/E + EV/EBITDA | ✅ Done | 2026-10-27 | multiples.py applicability_check()：隐含 P/E > 100x（净利极薄，如 NBIS $42M NI vs $55B 市值）→ P/E 标记 not meaningful；EBITDA/营收 > 90%（D&A 主导的重资产）→ EV/EBITDA 标记 not directly comparable |
| 022 | 🔴 资产轻原型冲突置信度扣减 | ✅ Done | 2026-10-27 | ml_classifier.py：ML 判 SaaS/MatureTech/Media 但 capex/revenue≥1.0 且负 FCF（重资本算力建设）→ 触发 "Asset-light prototype conflict" 扣减，置信度 cap 50%，审计链留痕；NBIS 分类置信度 55%→50% 且 peer 路由改道 AI/Cloud |
| 023 | 🐛 terminal_growth.py 零增长地板 bug 修复 (历史遗留) | ✅ Done | 2026-10-27 | 0≤base<1.5% 分支改为抬高到成熟地板 BASE_FLOOR(1.5%) 而非坍缩到 DECLINING_BASE(0.5%)（只有真实衰退才衰减）；`test_floor_base_keeps_low_strictly_below` 从 ❌ 变为 ✅，全量 pytest 61/61 |
| 024 | 🔴 一致性覆盖率门控 (问题 #1 最严重) | ✅ Done | 2026-10-27 | analysis/model_agreement.py 重写：三桶分类 (solved/not_applicable/failed) + gated_cv = base_cv×覆盖因子÷质量因子 + 硬覆盖率封顶 (solved≤1→Very Weak, ==2→Weak, ==3→Moderate, ≥4 不封顶)；NBIS 由 Very Strong→Weak |
| 025 | 🔴 质量加权中位数 + 模型权重可视化 (问题 #2) | ✅ Done | 2026-10-27 | 权重体系：SOLVED=1.0 / APPROXIMATE=0.5 / TV/EV>80% 的 DCF 再×0.5 / 分类置信度<55% 的倍数再×0.5；输出 `median_value_weighted` + `model_weights` + `downweighted_models`；中位标签改为「质量加权」 |
| 026 | 🔴 估值可用性评分拆分 (问题 #3) | ✅ Done | 2026-10-27 | data/validator.py 新增 `_valuation_usability()` + `per_share_basis_unreliable()`；data/models.py 新增 `reconciliation_mismatches` / `valuation_usability_score` / `usability_label()`；报告分「源数据质量」「估值可用性」两行（NBIS 83/100 vs 34/100） |
| 027 | 🔴 情景/中位/公允区间口径一致性 (问题 #4) | ✅ Done | 2026-10-27 | verdict_intuition.py：`_scenario_summary()` 支持"当前价高于**全部**情景"；analysis/scenario.py 负 pps floor 到 0 + 归零 note；公允区间标注样本数 n + 覆盖率；股数不可靠时抑制每股公允值 |
| 028 | 🎯 人工 AI Cloud peer 组 + 低置信倍数降权 (问题 #5) | ✅ Done | 2026-10-27 | models/multiples.py 新增 `AI_CLOUD_PEER_GROUP` (CoreWeave/IREN/Equinix/Oracle/Nebius, band_width=0.625) + `_ai_cloud_peer_note()` 展示参考带 + 可比公司；model_agreement 对 classification_confidence<55% 的 APPROXIMATE 模型权重再×0.5 |
| 029 | 🎯 WACC 三 beta 透明化 + 区间估值 + 反向 DCF 隐含量化 (问题 #6) | ✅ Done | 2026-10-27 | valuation/wacc.py 新增 `beta_raw`/`beta_bottom_up` + `beta_transparency_note()` + `wacc_range_note()`；models/dcf.py 新增行业区间上下沿估值 (NBIS 6.5%→$1,574.90 / 11.5%→$237.37)；models/reverse_dcf.py 新增 `_normalized_growth_solve()` 输出"当前价隐含营收 CAGR ≈ 27%"替代负 EV |
| 030 | 🎲 蒙特卡洛概率结论 + 相关性建模 (问题 #7) | ✅ Done | 2026-10-27 | simulation/monte_carlo.py 重写：`prob_above_price` / `prob_overvalued_30` / `prob_equity_zero`；4×4 驱动因子 (cagr/margin/wacc/tg) Cholesky 相关抽样 + Gordon 稳定约束；负值 floor 计入归零概率；dashboard 渲染「🎲 概率结论」块 (NBIS: 0.3% / 97.5% / 6.7%) |
| 031 | 🔴 递归自我改进 Round 1：报告自洽（增长标题桶 + 业务类型冲突显性化） | ✅ Done | 2026-11-03 | verdict_intuition.py 增长标题分档对齐 `_rev_cagr_label`（爆发式/高速/稳健/温和/低速）；CompanyProfile 新增 `effective_business_type`/`business_type_conflict_note`；ml_classifier 冲突时写入；dashboard 渲染「SaaS → AI/Cloud Infrastructure」 |
| 032 | 🔴 递归自我改进 Round 2：DCF 极端终值权重可靠性门控 | ✅ Done | 2026-11-03 | model_agreement.py 分级降权 `_TV_EXTREME_THRESHOLD=1.5`(×0.25) / `_TV_ARTIFACT_THRESHOLD=3.0`(×0.1)；NBIS DCF 权重 0.5→0.1 → 质量加权中位 $30.37→$26.41；dcf.py 输出「DCF point value unreliable」；极端终值置顶告警 |
| 033 | 🔴 递归自我改进 Round 3：反向 DCF 负上限措辞 + 风险指标失真守卫 | ✅ Done | 2026-11-03 | reverse_dcf.py 负 EV 改述（即便 80% CAGR 上限 EV 仍为负）；risk.py `_margin_risk()` 剔除营收 <10% 峰值的基期，不足 3 期降级 Low；NBIS 风险 High→Medium(50→58) |
| 034 | 🔴 JNJ 递归改进 Round 1：模型分桶算术自洽 + ReverseDCF 误导标签 | ✅ Done | 2026-11-03 | model_agreement.py 新增 `n_display_only`/`display_only_models` 第四桶，`n_applicable = n_total − n_not_applicable − n_display_only`，使「适用 = 解算 + 失败」恒等成立；虚假 failed 告警改为按真实 `len(failed)` 触发；dashboard ReverseDCF 由误导性 `[估值合理]` 改标「反向求解＝当前价，非独立估值」，分桶行显示「合计 6（含 1 个仅展示）」 |
| 035 | 🔴 JNJ 递归改进 Round 2：对账 P/E 口径语义（GAAP vs 调整后） | ✅ Done | 2026-11-03 | reconciliation.py 滚动 P/E 检查改为方向感知文案：供应商 P/E 低于 价格/GAAP-EPS 隐含值 → 判为 non-GAAP/正常化口径差（非盈利不稳定）；高于 → 旧口径/摊薄股数或盈利下滑；JNJ 不再误报「盈利基数极不稳定」 |
| 036 | 🔴 JNJ 递归改进 Round 3：FCF Yield Gap 误报守卫 + Beta 展示一致 | ✅ Done | 2026-11-03 | risk.py FCF Yield Gap 新增守卫（正 FCF 且 FCF/净利≥0.8 且非高增长、收益率<4% → 降一级），JNJ 该旗标 High→Medium，总体风险 75→80、High 2→1；wacc.py 暴露 `BETA_WINSOR_LO/HI`；dashboard 市场区对越界 β 追加「原始值超出 CAPM 区间，WACC 采用截断值」标注 |
| 037 | 🔴 覆盖率瓶颈：新增 Replacement NAV 模型族（重资本高增长/亏损期） | ✅ Done | 2026-11-03 | 新建 `models/replacement_nav.py`（`equity = book_equity + net_ppe×(factor−1)`，net_ppe=Σcapex−ΣD&A；factor 默认 1.15 + 敏感性 1.00/1.10/1.15/1.25/1.40）；`config.py` 新增 `ModelName.REPLACEMENT_NAV`；`models/router.py`/`__init__.py` 注册；`classification/classifier.py` 动态入桶 `_is_replacement_nav_candidate`（capex/revenue≥0.30 + 负 FCF/亏损 + net_ppe>0，排除金融/REIT）；**NBIS 覆盖率 2/3 → 5/6** |
| 038 | 🔴 对账层反向校验供应商（偏差 >25% 自动改用内部推算值） | ✅ Done | 2026-11-03 | `data/reconciliation.py` 新增写侧 `apply_overrides()` + `OverrideRecord`/`OverrideLog`（审计链）+ `_OVERRIDE_FIELDS`/`_OVERRIDE_TOLERANCE=0.25` + 股数守卫（恒等式自洽→仅标注 / 破坏→按市值/价格反推）；`data/models.py` 新增 `reconciliation_overrides` 字段；`data/validator.py::_check_reconciliation` 接入；`reporting/dashboard.py::_data_section` 渲染「🩹 对账自动修正」 |
| 039 | 🔴 递归自改进工程化：golden report diff 可断言回归 | ✅ Done | 2026-11-03 | 新建 `tests/golden_report.py`（`BASKET` 9 只 + `run_pipeline`/`build_fingerprint`(19 字段)/`check_invariants`(5 类缺陷：覆盖恒等式/agreement 超封顶/负中位/β 三处一致/override 生效)）+ `tests/test_golden_report.py`（3 测试，`UPDATE_GOLDEN=1` 刷新基线）+ `tests/golden/report_fingerprints.json` |
| 040 | 🔴 Beta 全链路统一：单一 `resolve_effective_beta` 出口 | ✅ Done | 2026-11-03 | `valuation/wacc.py::resolve_effective_beta()` 统一 β 口径（wacc_breakdown → provider → fallback，`origin` 可审计）；市场区 / WACC / 风险旗标三处共用；由 golden `check_invariants()` 断言化 |
| 041 | 🎯 补 REIT（AMT）与 Energy（XOM）资产结构覆盖 | ✅ Done | 2026-11-03 | `data/providers.py` 新增 NBIS/AMT/XOM 合成 fixtures；`tests/conftest.py` 新增 nbis/amt/xom fixtures；`tests/test_asset_structure_coverage.py`（8 测试）断言 NBIS `n_solved≥3` + `Replacement NAV` 入 applicable、AMT `is_reit=True`、XOM `business_type=="Energy"` |
| 042 | 🔴 覆盖率瓶颈（第二条腿）：EV/Sales + 单位经济学模型族（重资本高增长/亏损期） | ✅ Done | 2026-11-03 | 新建 `models/unit_economics.py`（`UnitEconomicsSalesModel`）：`deployed_capital=Σcapex−ΣD&A`；`capacity_revenue=max(TTM_rev, deployed_capital×BENCHMARK_REVENUE_YIELD)` → `EV=capacity_revenue×MATURE_EV_SALES×ramp_discount`（`utilisation_gap=clamp(1−current_yield/benchmark_yield,0,1)`、`ramp_discount=(1+WACC)^−(RAMP_YEARS×utilisation_gap)`）；`BENCHMARK_REVENUE_YIELD=0.35`/`MATURE_EV_SALES=4.0`/`RAMP_YEARS=3.0` + 敏感性（yield 0.25/0.35/0.50 × ramp 2/3/5）；`config.py` 新增 `ModelName.UNIT_ECON_SALES`；`models/router.py`/`__init__.py` 注册；`classifier.py` 动态入桶 `_is_unit_economics_candidate()`（capex/revenue≥0.50 + 负 FCF/亏损 + net_ppe>0，排除金融/REIT）；**NBIS 覆盖率 5/6 → 6/7**（EV/Sales Unit Econ $27.02）；数据层无 GPU 稼动率/ARPU 明细 → 固定返回 APPROXIMATE 诚实标注 |
| 043 | 🔁 CRWV 递归自我改进 3 轮（CoreWeave — AI/Cloud neocloud 重资本建设期画像） | ✅ Done | 2026-11-03 | 以 CRWV 为新画像标的，重复「上一轮产出 → 缺陷 → 修码 → 下一轮」3 轮：**Round 1** 规则分类路径（离线/golden 走这条）缺「资产轻原型冲突 → AI/Cloud 重路由」→ 报告头 `MatureTech/SaaS` 与 peer 区 `AI/Cloud Infrastructure` 自相矛盾，`classifier.py` 补 ISSUE #1b（对齐 ml_classifier）+ `dashboard.py` hybrid 分支渲染重路由标注；**Round 2** 一句话结论内部矛盾（中位判显著高估 vs DCF 基准 $138.57 反判低估）→ `verdict_intuition.py` 新增「中位 vs 情景方向冲突」caveat（**命名矛盾、不做平均**），并修正自持的基期口径错误（base-relative vs price-relative）；**Round 3** `reverse_dcf.py` 成熟稳态推导的隐含营收 CAGR 仅存于 free-text note、结构化字段却显示 N/A → 写入 `breakdown["implied_revenue_cagr"]` + source 标记；`expectation.py` 透传 source；`dashboard.py` 标注 APPROXIMATE + 修正 `_gap_section` 方向文案 bug（原硬编码「高出」）；新增 CRWV 合成 fixture；回归证据 `_recursion_crwv_round0..3.txt`；pytest 90/90 |

---

# 5. Pending Tasks

| Priority | Task | Dependency | Assigned |
|----------|------|------------|----------|
| HIGH | 特征补全: sector/industry (Alpha Vantage / yfinance.info fallback) | 012 | Agent |
| HIGH | 特征补全: interest/revenue (从 TTM interest_expense / revenue 重算) | 012 | Agent |
| HIGH | 标签纠错: AVGO / AMT / NEE / 等 sanity 误判样本检查 label 正确性 | 012 | Agent |
| HIGH | 超参调优: Optuna 调 LightGBM params (LR, num_leaves, min_data, class_weight) | 012 | Agent |
| HIGH | 类别平衡: SMOTE / class_weight='balanced' 处理 Semiconductor (2.9%) / Insurance (3.8%) 少数类 | 012 | Agent |
| MEDIUM | AB测试: deterministic / synthetic / real-v2.1 三者混淆矩阵 + F1-score 对比 | 012 | Agent |
| MEDIUM | 扩充训练集到 5000 行 (覆盖更多中/小盘股, 减少 Unknown 35.4%过高占比) | 011 | Agent |
| MEDIUM | 完善 pytest 覆盖 (当前≈48%) → 80%+ | 随时 | Agent |
| MEDIUM | 为对账层补 pytest 用例 (10 项交叉校验 + AI/Cloud 重路由 + P/E/EBITDA 守卫) | 019-022 | Agent |
| MEDIUM | 为覆盖率门控 / 质量加权中位 / 蒙特卡洛概率结论补 pytest 用例 | 024-030 | Agent |
| MEDIUM | AI/Cloud 重路由回归扩样 (CRWV / CORZ / IREN 等算力/数据中心标的) | 020 | Agent |
| LOW | 报告展示「失败模型清单 + 失败原因」与「保留 P/E/EV-EBITDA 时的中位值对照」 | 024 | Agent |
| LOW | 反向 DCF 升级为三变量求解 (营收 CAGR + 稳态 FCF margin + capex intensity) | 029 | Agent |
| LOW | 部署到 Cloudflare / Render | 核心完成 | Agent |

---

# 6. Next Immediate Task

The NEXT AI Agent should start here.

Task:

```
特征补全 + 标签纠错（推高 Sanity 准确率从 75% → 90%+），执行步骤：
1. 标签纠错: 打开 classification\labeling_dump.csv 批量修正：
   - AVGO: MatureTech → Semiconductor（Broadcom 是半导体设计 + 并购平台，典型 Semi）
   - AMT: REIT → 保留（American Tower 是通信塔 REIT），需修正 interest_to_revenue=0 → 从 TTM interest expense / revenue 重算
   - NEE: Utilities → 保留（NextEra Energy 是电力公司），修正特征
   - MSFT: label 正确 = MatureTech，误判是因为 Semiconductor 数值信号太强（gm=68%, om=51%）
2. 特征补全: 写脚本遍历 1000 行：
   a) sector/industry: 先试 yfinance.Ticker(t).info['sector']/'industry'，再试 Alpha Vantage API
   b) interest_to_revenue: 若为 0，重算为 max(interest_expense, 0) / max(revenue, 1)
3. 删除旧 artifacts，重新运行 classification\_run_train_and_verify.py
4. 期望 Sanity 准确率 ≥ 90% (15/16)
```

Expected Output

```
- 修正后的 labeling_dump.csv（标签 + 特征补全）
- v2.2 模型 artifacts (3个 .pkl)
- train_acc ≥ 98% (1000行)
- sanity 准确率 ≥ 90% (≥15/16)
```

Files to modify

```
classification\labeling_dump.csv       (批量标签 + 特征修正)
classification\ml_classifier.py        (如需引入 Optuna 调参或 class_weight)
classification\_ml_artifacts\*         (删除旧 v2.1，生成新 v2.2)
```

Estimated Difficulty

- Easy
- ✅ Medium (批处理 CSV + 跑补全脚本 + 重训验证)
- Hard

---

# 7. Project Structure

```
Telegram股票分析/
├── main.py                      # 入口: bot/demo/test/test_demo
├── config.py                    # 配置: BusinessType枚举, 日志, 路径
├── _dump_features_for_labeling.py  # ✅ 批量特征提取(刚用它收集1001只)
├── _demo_ml_classifier.py       # ML分类器演示脚本
├── _ab_classifier_compare.py    # AB测试对比脚本
├── full_tickers_1000.txt        # ✅ 1000+股票代码列表(本次新建)
│
├── data/
│   ├── providers.py             # YahooFinanceProvider + TreasuryYieldProvider + Synthetic
│   ├── models.py                # FinancialData / CompanyProfile dataclasses
│   ├── normalizer.py            # 财务数据标准化
│   └── validator.py             # 数据质量验证
│
├── valuation/
│   ├── wacc.py                  # WACC 7步法 + Sanity Check
│   └── terminal_growth.py       # TVG 动态约束 (min(企业, GDP, WACC-0.5%))
│
├── models/
│   ├── base.py                  # BaseValuationModel 抽象基类
│   ├── router.py                # 模型路由 (根据BusinessType选模型)
│   ├── dcf.py                   # 两阶段 DCF
│   ├── reverse_dcf.py           # Reverse DCF (反推隐含增长)
│   ├── nav.py                   # NAV / 净资产估值 (REITs)
│   ├── bank.py                  # 银行模型 (股息/ROE估值)
│   ├── sotp.py                  # SOTP 分部估值
│   └── multiples.py             # 可比公司倍数估值
│
├── analysis/
│   ├── sensitivity.py           # WACC×g 敏感性矩阵 + Base高亮
│   ├── risk.py                  # 风险因子分析
│   ├── scenario.py              # 三档情景 (Base/Low/High)
│   ├── model_agreement.py       # 多模型一致性评估
│   └── expectation.py           # 市场预期分析
│
├── classification/
│   ├── __init__.py
│   ├── classifier.py            # 确定性规则 BusinessClassifier (~85% acc)
│   ├── ml_classifier.py         # LightGBM + TF-IDF (当前合成版 v2.0)
│   ├── labeling_dump.csv        # ✅ 1001×15特征, 等待label标注 (本次产出)
│   ├── labeling_dump_failures.csv
│   └── _ml_artifacts/           # 训练产物 (3个 .pkl)
│       ├── lgbm_multiclass_v2.pkl
│       ├── tfidf_vectorizer_v2.pkl
│       └── train_meta_v2.pkl
│
├── simulation/
│   └── monte_carlo.py           # 蒙特卡洛模拟
│
├── forecasts/
│   └── forecast.py              # 收入/利润预测模块
│
├── reporting/
│   └── dashboard.py             # 仪表盘/报告生成
│
├── telegram_bot/
│   └── telegram_bot.py          # Telegram Bot 主逻辑 + ValuationPipeline
│
├── tests/                       # pytest 测试套件 (~45%覆盖)
│   ├── conftest.py
│   ├── test_dcf.py
│   ├── test_reverse_dcf.py
│   ├── test_sensitivity.py
│   ├── test_classifier.py
│   ├── test_ml_classifier.py
│   └── ...
│
├── .cache/
│   ├── yahoo_finance/           # 4h TTL, JSON 文件缓存 (已有~500+文件)
│   └── treasury_yield/
│
├── .venv/                       # Python 3.13 虚拟环境
├── .env.example                 # TELEGRAM_BOT_TOKEN 等
└── .env                         # (不提交到版本控制)
```

---

# 8. Files Created

| File | Purpose | Created |
|------|---------|---------|
| classification\labeling_dump.csv | ✨ 1001只股票×15特征训练数据集 | 2026-10-05 |
| classification\labeling_dump_failures.csv | 失败股票记录 (空) | 2026-10-05 |
| full_tickers_1000.txt | ✨ 1000+ 股票代码列表 (去重源) | 2026-10-05 |
| extra_tickers.txt | 中间文件，已整合进 full_tickers_1000.txt | 2026-10-05 |
| reporting\verdict_intuition.py | ✨ 直观标签计算逻辑：build_growth_verdict() + build_valuation_verdict() 纯函数，把百分比映射为中文定性标签（高速增长 / 明显高估 / 增长放缓等） | 2026-10-08 |
| data\reconciliation.py | ✨ 数据对账层：reconcile(data) 对市值/股数/EPS/PE/EV/EBITDA/EV Sales/FCF 做 10 项交叉校验；ReconciliationCheck/ReconciliationReport dataclass + render/to_lines 渲染；纯只读，绝不突变 FinancialData | 2026-10-27 |
| models\replacement_nav.py | ✨ Session #10 覆盖率锚：ReplacementNAVModel（重资本高增长/亏损期的资产基础锚）——`equity = book_equity + net_ppe×(factor−1)` 或 `replacement_ppe − net_debt`；net_ppe=Σcapex−ΣD&A；factor 默认 1.15 + 5 档敏感性 | 2026-11-03 |
| tests\test_reconciliation_override.py | ✨ Session #10：对账反向校验写侧行为 6 测试（EV 覆盖生效 / 小偏差不覆盖 / 股数守卫恒等式自洽仅标注 / 恒等式破坏按市值反推 / OverrideLog 渲染 / validator 挂载 OverrideLog） | 2026-11-03 |
| tests\test_asset_structure_coverage.py | ✨ Session #10：资产结构覆盖 8 测试（Replacement NAV 覆盖率提升 4 + REIT 结构 2 + Energy 结构 2） | 2026-11-03 |
| tests\golden_report.py | ✨ Session #10：golden 指纹模块（BASKET 9 只 + run_pipeline + build_fingerprint 19 字段 + check_invariants 5 类缺陷清单 + render_report） | 2026-11-03 |
| tests\test_golden_report.py | ✨ Session #10：golden diff 回归 3 测试（invariants hold / coverage identity explicit / golden fingerprint matches；`UPDATE_GOLDEN=1` 刷新基线） | 2026-11-03 |
| tests\golden\report_fingerprints.json | ✨ Session #10：9 只标的 golden 指纹基线（AAPL/MSFT/NVDA/JPM/PLD/NOW/NBIS/AMT/XOM） | 2026-11-03 |
| models\unit_economics.py | ✨ Session #11 覆盖率锚（第二条腿）：UnitEconomicsSalesModel（EV/Sales + 单位经济学，重资本高增长/亏损期的 earnings-power 锚）——`capacity_revenue = max(TTM_rev, deployed_capital×benchmark_yield)` → `EV = capacity_revenue×mature_ev_sales×ramp_discount`；`MIN_CAPEX_RATIO=0.50` / `BENCHMARK_REVENUE_YIELD=0.35` / `MATURE_EV_SALES=4.0` / `RAMP_YEARS=3.0` + 敏感性；固定返回 APPROXIMATE | 2026-11-03 |
| tests\test_unit_economics.py | ✨ Session #11：单位经济学模型 12 测试（路由 4 / 解算 3 / 覆盖率提升 2 / 敏感性方向 2 / 适用性守卫 1） | 2026-11-03 |
| _recursion_run.py | ✨ Session #12：递归改进驱动脚本——`run_pipeline(ticker)` → `render_report()` 落盘 `_recursion_<ticker>_<label>.txt` + 打印 fingerprint 与 `check_invariants()` 缺陷清单，供「上一轮产出 → 下一轮起点」（4 轮复用：CRWV round0..3） | 2026-11-03 |
| valuation\caliber.py | ✨ Session #14：口径契约模块（唯一真相来源）——`MetricMeaning` / `DiscountCaliber` / `CaliberContract` / `build_caliber_contract(profile)`；把「某指标对某类标的有无意义」提升为引擎输出枚举 | 2026-11-03 |
| tests\test_cap_boundary_guard.py | ✨ Session #14：ADR-023 封顶审计 3 测试（Part A 常量守卫闭区间 / Part B 同文件字面量配对审阅 / Part C 跨文件 confidence 封顶断言） | 2026-11-03 |
| tests\test_hybrid_threshold_lock.py | ✨ Session #14：hybrid 阈值锁定 2 测试（`HYBRID_FIN_TO_TECH_FLOOR==0.08` + 检测器仅在 `>= floor` 翻转的闭区间边界） | 2026-11-03 |

---

# 9. Files Modified

| File | Reason | Modified |
|------|--------|----------|
| classification\ml_classifier.py | 在 _train_from_scratch() 末尾增加 TrainMeta.version / note overwrite 逻辑 (version: "2.0-synthetic" → "2.1-real-data-trainN", note: "real-data trained on N manually labeled rows")，同时已永久切换 build_training_set_from_csv() 替换合成数据生成 | 2026-10-05 |
| data\models.py | 新增 ConfidenceAdjustment + BusinessExposure 两个 dataclass；CompanyProfile 扩展 13 个字段 (ml_raw_confidence / confidence_adjustments[] / is_hybrid_classification / primary_business_type / secondary_business_type / hybrid_label / classification_confidence_level / business_exposures[] 等)；新增 GrowthVerdictCard + ValuationVerdictCard 两个直观标签卡片及 header_lines(include_headline=True) / bullet_lines() 渲染方法 | 2026-10-08 |
| classification\ml_classifier.py | 新增 _build_exposures() (11 类 → 5 轴聚合) + _detect_hybrid() (三条触发规则)；MLHybridClassifier.classify() 重构：置信度调整明细数组 + 填充所有 Hybrid 新字段；rule fallback 分支同样补齐结构 | 2026-10-08 |
| classification\classifier.py | 规则引擎端镜像补齐 ConfidenceAdjustment + Hybrid + Exposures 三个新结构；_characterize_profile() 金融机构专项修复 (FCF margin→net income、杠杆 2x→15x、capital intensity N/A、REIT FFO 文案) | 2026-10-08 |
| reporting\dashboard.py | build_report() 新增「🔥 OVERVIEW」首屏直观判断区块（_intuitive_overview_section）；_business_section() Hybrid+置信度拆解+Exposures；_market_section() 金融机构 caveat；_gap_section() 末尾追加增长直观解读；_agreement_section() 改「估值细节拆解」(include_headline=False 避免一句话结论重复) | 2026-10-08 |
| analysis\risk.py | analyze(profile=None) 顶部 is_fin/is_reit 判断 + 末尾 None 级「指标定义差异说明」信息 flag；_leverage / _margin_risk / _forecast_risk 签名加 profile：金融机构 D/E 阈值 15x / 跳过 neg-FCF 计数 / 直接 return 不算 FCF Yield；REIT 对应降级处理 | 2026-10-08 |
| data\models.py (Session #05 bugfix) | ValuationVerdictCard.header_lines() 新增 include_headline 关键字参数；删除中位估值 detail 行中冗余的「中位估值」前缀（因为 median_vs_price_detail 已是"当前价较中位估值"的自包含完整句） | 2026-10-08 |
| reporting\dashboard.py (Session #05 bugfix) | _agreement_section() 标题由「🤝 一句话估值:」改为「🤝 估值细节拆解:」，并调用 v.header_lines(include_headline=False) 避免与 overview 区「一句话估值结论」重复展示 | 2026-10-08 |
| models\multiples.py (Session #06) | 技术族 peer 桶细粒度化 (SaaS→Software-SaaS 等) + 新增 AI/Cloud Infrastructure 桶；新增 `_COMPUTE_INFRA_CAPEX_RATIO` 常量 + `_COMPUTE_INFRA_SOURCE_BUCKETS` + `_compute_infra_override()` 检测重资本算力建设；`_sector_peer_multiple()` 拆出 `_resolve_peer_bucket()` 并在技术族键上做 AI/Cloud 重路由；applicability_check() 新增 P/E(>100x 无意义) + EV/EBITDA(EBITDA>90%营收 D&A 主导) 守卫；README/docstring 同步 | 2026-10-27 |
| classification\ml_classifier.py (Session #06) | 新增 `ASSET_LIGHT_CONFLICT_CAPEX_RATIO` + `ASSET_LIGHT_TYPES` 常量；新增 "Asset-light prototype conflict" 置信度扣减 (ML 判资产轻类型但 capex/revenue≥1.0 且负 FCF → cap 50%)，append 到 ConfidenceAdjustment 审计链 + reasons | 2026-10-27 |
| valuation\terminal_growth.py (Session #06) | 修复 0≤base<1.5% 分支：由坍缩到 DECLINING_BASE(0.5%) 改为抬高到成熟地板 BASE_FLOOR(1.5%)（只有真实衰退才衰减）；模块 docstring 第 13 行同步说明「flat ≠ declining」 | 2026-10-27 |
| reporting\dashboard.py (Session #06) | 新增 `_fmt_recon(v, unit)` 按单位（USD / 股 / USD-股）格式化对账值；_data_section() 新增「🔗 数据对账」区块渲染 (已校验 N / 一致 / 不一致 / 数据不足 + 不匹配项逐条 render + 口径失真提示) | 2026-10-27 |
| data\reconciliation.py (Session #06 修订) | `ReconciliationCheck.render(fmt)` 改为 `fmt(value, unit)`；`to_lines` 默认 lambda 接受 2 参；第 10 项检查重写为比率语义 (EBITDA/营收 ≤ 100%) 避免金额对金额的费解渲染 | 2026-10-27 |
| analysis\model_agreement.py (Session #07) | 重写：三桶分类 (solved/not_applicable/failed) + 覆盖率门控 (gated_cv = base_cv×覆盖因子÷质量因子) + 硬覆盖率封顶 (`_COVERAGE_CAP`) + 质量加权中位数 (`_weighted_median`) + 低置信分类再降权 (w×0.5)；新增字段 n_total/n_failed/coverage_ratio/quality_factor/coverage_factor/gated_cv/median_value_weighted/model_weights 等 | 2026-10-27 |
| simulation\monte_carlo.py (Session #07) | `run()` 重写：4×4 驱动因子 (cagr/margin/wacc/tg) Cholesky 相关抽样 + Gordon 稳定约束 + 负值 floor；`MonteCarloResult` 新增 n_valid/current_price/prob_above_price/prob_overvalued_30/prob_equity_zero；新增模块级 `_DRIVER_CORR` + `_correlation_cholesky()` | 2026-10-27 |
| data\validator.py (Session #07) | `_check_reconciliation()` 记录 `reconciliation_mismatches`；新增 `_PER_SHARE_BASIS_KEYS` + `per_share_basis_unreliable()` + `_valuation_usability()`；`_finalize_quality_score()` 写入 `valuation_usability_score` | 2026-10-27 |
| data\models.py (Session #07) | `DataQualityFlags` 新增 `reconciliation_mismatches` / `valuation_usability_score` + `usability_label()` | 2026-10-27 |
| reporting\verdict_intuition.py (Session #07) | `_scenario_summary()` 修正为"当前价高于全部情景"；`build_valuation_verdict()` 改用 `median_value_weighted`；股数不可靠判定改为三键 (流通股数/市值/TTM EPS)；公允区间标注 n/覆盖率；headline 硬门槛 n_solved<2 | 2026-10-27 |
| analysis\scenario.py (Session #07) | `_run_one()` 中 `pps < 0` 时 floor 到 0 并追加"股权价值归零"note | 2026-10-27 |
| valuation\wacc.py (Session #07) | `WaccBreakdown` 新增 `beta_raw`/`beta_bottom_up` + `beta_transparency_note()` + `wacc_range_note()`；beta source 文案标注 `[0.3, 2.5]` 缩尾 | 2026-10-27 |
| models\dcf.py (Session #07) | 新增 WACC 行业区间上下沿估值（写入 breakdown `value_per_share_wacc_lo/hi`） | 2026-10-27 |
| models\reverse_dcf.py (Session #07) | `NO_SOLUTION_IN_RANGE` 文案汉化 + 区分"FCF 深度为负"vs"仍低于目标"；新增 `_normalized_growth_solve()` 隐含量化 diagnostic | 2026-10-27 |
| models\multiples.py (Session #07) | 新增 `AI_CLOUD_PEER_GROUP` + `_ai_cloud_peer_note()` 静态参考带与可比公司列表；AI/Cloud 重路由 source 追加 peer note；`__all__` 导出 | 2026-10-27 |
| reporting\dashboard.py (Session #07) | `_agreement_section()` 新增模型分桶/一致性门控/质量加权中位/模型权重/不适用与失败模型列表；`_valuation_section()` 新增 DCF WACC 区间估值 + Beta 透明度 + WACC 区间提示；`_data_section()` 拆源数据质量/估值可用性 + 蒙特卡洛概率结论块 | 2026-10-27 |
| analysis\model_agreement.py (Session #09) | 新增第四桶 `n_display_only`/`display_only_models`（ReverseDCF 从 `solved` continue 后落桶），`n_applicable = n_total − n_not_applicable − n_display_only` 使「适用 = 解算 + 失败」恒等；虚假 failed 告警改为按真实 `len(failed)` 触发；docstring 三分桶→四分桶 | 2026-11-03 |
| reporting\dashboard.py (Session #09) | ReverseDCF 由误导性 `[估值合理]` 改标「（反向求解＝当前价，非独立估值）」；模型分桶行显示「合计 N（含 n 个仅展示，不计入统计）」；市场区对越界 β 追加「原始值超出 CAPM 区间 [0.30, 2.50]，WACC 采用截断值」标注（引用 `BETA_WINSOR_LO/HI`） | 2026-11-03 |
| data\reconciliation.py (Session #09) | 滚动 P/E 检查改为方向感知文案：供应商 P/E 低于 价格/GAAP-EPS 隐含值 → non-GAAP/正常化口径差（非盈利不稳定）；高于 → 旧口径/摊薄股数或盈利下滑 | 2026-11-03 |
| analysis\risk.py (Session #09) | FCF Yield Gap 新增守卫：正 FCF 且 FCF/净利≥0.8 且非高增长、收益率<4% → 降一级并说明「属估值偏高观察，非现金流质量风险」 | 2026-11-03 |
| valuation\wacc.py (Session #09) | 暴露 `BETA_WINSOR_LO=0.30` / `BETA_WINSOR_HI=2.50` 模块常量，winsorize 逻辑与 source 文案改用常量（供展示层复用） | 2026-11-03 |
| config.py (Session #10) | `ModelName` 枚举新增 `REPLACEMENT_NAV = "Replacement NAV"`（位于 `REIT_NAV` 之后、`BANK_DDM` 之前） | 2026-11-03 |
| models\router.py (Session #10) | import `ReplacementNAVModel`；`NAME_TO_MODEL` 新增 `"Replacement NAV"` 映射 | 2026-11-03 |
| models\__init__.py (Session #10) | import 与 `__all__` 加入 `ReplacementNAVModel` | 2026-11-03 |
| classification\classifier.py (Session #10) | `ALL_MODELS` 加入 `"Replacement NAV"`；`_model_applicability()` 末尾新增强制追加逻辑（build-out 标的）+ 新增 `_is_replacement_nav_candidate()` staticmethod（排除金融/REIT；要求 shares；capex/revenue≥0.30；net_ppe>0；负 FCF 或亏损或 High Growth） | 2026-11-03 |
| data\reconciliation.py (Session #10) | 新增写侧反向校验：`OverrideRecord`/`OverrideLog` + `_OVERRIDE_FIELDS` + `_OVERRIDE_TOLERANCE=0.25` + `apply_overrides()`（偏差 >25% 自动改用内部推算值并标注）+ 股数守卫（恒等式自洽→仅标注 / 破坏→按市值/价格反推）；模块由「纯只读」升级为「只读 + 显式写侧 + 审计」（ADR-011 修订） | 2026-11-03 |
| data\models.py (Session #10) | `FinancialData` 新增 `reconciliation_overrides` 字段（承载 OverrideLog） | 2026-11-03 |
| data\validator.py (Session #10) | `_check_reconciliation()` 调用 `apply_overrides()` 并将 OverrideLog 挂到 data + 写 restatement_notes | 2026-11-03 |
| reporting\dashboard.py (Session #10) | `_data_section()` 在既有对账段后追加 `OverrideLog.to_lines(_fmt_recon)` 渲染「🩹 对账自动修正（偏差 > 25% 时改用内部推算值）」 | 2026-11-03 |
| valuation\wacc.py (Session #10) | 新增 `resolve_effective_beta()`（单一 β 出口：wacc_breakdown → provider → fallback，返回带 `origin` 的可审计对象），市场区 / WACC / 风险旗标三处共用 | 2026-11-03 |
| data\providers.py (Session #10) | `SYNTHETIC_DATA` 新增 NBIS（AI/Cloud 建设期）/ AMT（tower REIT）/ XOM（Energy）三组 fixtures | 2026-11-03 |
| tests\conftest.py (Session #10) | 新增 `_load()` 辅助 + fixtures `nbis_data`/`amt_data`/`xom_data`/`amt_profile`/`xom_profile`（session-scoped，经 normalize_all + validate） | 2026-11-03 |
| config.py (Session #11) | `ModelName` 枚举新增 `UNIT_ECON_SALES = "EV/Sales (Unit Econ)"`（位于 `REPLACEMENT_NAV` 之后） | 2026-11-03 |
| models\router.py (Session #11) | import `UnitEconomicsSalesModel`；`NAME_TO_MODEL` 新增 `"EV/Sales (Unit Econ)"` 映射 | 2026-11-03 |
| models\__init__.py (Session #11) | import 与 `__all__` 加入 `UnitEconomicsSalesModel` | 2026-11-03 |
| classification\classifier.py (Session #11) | `ALL_MODELS` 加入 `"EV/Sales (Unit Econ)"`；`_model_applicability()` 中 Replacement NAV 入桶后新增 Unit Economics 入桶块；新增 `_is_unit_economics_candidate()` staticmethod（排除金融/REIT；capex/revenue≥0.50 + 负 FCF 或亏损；Σcapex−ΣD&A>0） | 2026-11-03 |
| tests\golden\report_fingerprints.json (Session #11) | 由 `UPDATE_GOLDEN=1` 重新生成：NBIS 新基线 `n_total=10`/`n_applicable=7`/`n_solved=6`/`agreement_level="Very Weak"`/`median_value=12.76`/`median_value_weighted=11.13`，`applicable_models` 含 `"EV/Sales (Unit Econ)"`（已审阅的有意变更） | 2026-11-03 |
| data\providers.py (Session #12) | `SYNTHETIC_DATA` 新增 CRWV（CoreWeave，AI/Cloud neocloud 建设期画像）：price 75 / shares 480M / capex TTM 7.6B / FCF TTM −8.8B / debt 9B / β 2.60 —— 使递归管线可在确定性离线数据上跑「重资本高增长亏损期」标的 | 2026-11-03 |
| classification\classifier.py (Session #12 / Round 1) | 规则分类路径新增 `ASSET_LIGHT_CONFLICT_CAPEX_RATIO=1.0` + `ASSET_LIGHT_TYPES` + 「ISSUE #1b 资产轻原型冲突」块（对齐 `ml_classifier.py`）：`best_bt ∈ 资产轻类型` 且 `capex/revenue≥1.0` 且负 FCF → 置信度 cap 至 0.50 + `effective_business_type="AI/Cloud Infrastructure"` + `business_type_conflict_note`，消除报告头与 peer 区标签矛盾 | 2026-11-03 |
| reporting\dashboard.py (Session #12 / Round 1) | `_business_section()` hybrid 分支补渲染 `→ **估值原型重路由: {effective_business_type}**`（此前 hybrid（CRWV 命中 "Technology Company with Financial Exposure"）不显示重路由，头行仍是被拒标签） | 2026-11-03 |
| reporting\verdict_intuition.py (Session #12 / Round 2) | `build_valuation_verdict()` 新增「Median-vs-scenario SIGN conflict」caveat：中位口径与 DCF 基准情景方向相反时**显式命名冲突**（不做平均，归因 DCF 终值主导）；同步修正本轮自持的基期口径错误（`gap_vs_base` vs `gap_vs_price` 分列，"高于当前价 X%" 改为 price-relative） | 2026-11-03 |
| models\reverse_dcf.py (Session #12 / Round 3) | `_normalized_growth_solve()` 的隐含营收 CAGR 此前仅写入 free-text note，结构化 `breakdown["implied_revenue_cagr"]` 保持 `None` → 现写入该值 + `implied_revenue_cagr_source="normalized_growth_solve"`，使「市场隐含预期」区块不再显示 N/A（note 与字段一致） | 2026-11-03 |
| analysis\expectation.py (Session #12 / Round 3) | `ImpliedExpectations` / `ExpectationGap` 新增 `implied_revenue_cagr_source` 字段并透传（供展示层区分「直接求解」vs「成熟稳态推导 APPROXIMATE」） | 2026-11-03 |
| reporting\dashboard.py (Session #12 / Round 3) | `_implied_section()` / `_gap_section()` 对 `normalized_growth_solve` 来源标注「成熟稳态经济推导，APPROXIMATE」；修正 `_gap_section` 方向文案 bug（`direction` 之前计算未被插值，恒输出「高出」→ 现按符号输出「高/低」） | 2026-11-03 |
| models\bank.py (Session #13 / Round 1) | Bank DDM/RIM 统一经单一 β 出口 `resolve_effective_beta()` 取 β（winsorized [0.30, 2.50]），Rf/ERP 与 WACC / 情景路径同源 → 银行孪生模型 CAPM `ke` 不再与全报告其它区撕裂；新增 `_BANK_KE_BAND=(0.070, 0.100)` 越界提示 + `_resolve_discount_inputs()` | 2026-11-03 |
| analysis\scenario.py (Session #13 / Round 2) | 新增金融机构专属情景路径：`run_all()` 增 `is_financial_institution` 分叉 → `_run_financial_scenarios()`（Bank RIM 沿 `ke` 变动，`_FIN_BETA_STEP=0.30`）；`ScenarioValuation.assumptions` 新增 `discount_label`/`cost_of_equity`；机构标的情景不再用 DCF 口径 | 2026-11-03 |
| reporting\dashboard.py (Session #13 / Round 2) | `_scenario_section()` 按 `assumptions.discount_label` 分支渲染（`ke` 显示「— ke x% (Bank RIM)」，否则「— WACC x% / g y%」）；`_sensitivity_section(profile)` 对金融标的直接返回「不适用 DCF 敏感性矩阵」说明文案 | 2026-11-03 |
| models\multiples.py (Session #13 / Round 3) | 新增模块常量 `_PEER_MULTIPLE_CONF_FLOOR=0.55`；两处严格 `conf < 0.55` 改为 `conf <= _PEER_MULTIPLE_CONF_FLOOR`（`multiple_unvalidated` 判定 + notes 标注）→ 修复「置信度被封顶到恰好 0.55」时的边界漏检 | 2026-11-03 |
| valuation\caliber.py (Session #14) | ✨ **新建口径契约模块（唯一真相来源）**：`MetricMeaning`(MEANINGFUL/REFERENCE_ONLY/NOT_MEANINGFUL) + `DiscountCaliber`(WACC/ke) + `CaliberContract`(archetype/discount/metrics/notes/sensitivity_applicable) + `build_caliber_contract(profile)`；口径判定从渲染层内联提升为引擎输出枚举 | 2026-11-03 |
| reporting\dashboard.py (Session #14) | 删除 `_market_section()` 内联 `is_fin`/`is_reit` 猜口径，改为消费 `build_caliber_contract(profile)`（EV/净债务/EV/EBITDA/FCF 的 N/M 与附注来自契约）；`_sensitivity_section()` 按 `contract.sensitivity_applicable` 分支 | 2026-11-03 |
| analysis\scenario.py (Session #14) | 金融分叉改由 `contract.discount is DiscountCaliber.COST_OF_EQUITY` 驱动（替代硬编码 `is_financial_institution`）；金融情景升级为 **ke + 经营性 ROE 双驱动**（新增 `_FIN_ROE_SHOCK=0.20`，驱动文案「折现率 ke ± + 经营性 ROE ±」） | 2026-11-03 |
| models\bank.py (Session #14) | `BankRIMModel` 支持 `roe_override`（经营性驱动，≈净息差/信用成本）；`breakdown` 新增 `roe_source`（`ttm` / `scenario_override`） | 2026-11-03 |
| models\sotp.py (Session #14) | 🐛 跨文件 ADR-023 修复：`conf < 0.55`（2 处）→ `conf <= 0.55`（上游 `classifier.py:509` 会封顶到恰好 0.55，严格 `<` 漏检被降级的低置信分类） | 2026-11-03 |
| classification\ml_classifier.py (Session #14) | hybrid 阈值提为具名常量 `HYBRID_FIN_TO_TECH_FLOOR=0.08`（M-16，**锁定而非下调**）+ 注释说明根因是 sector/industry 缺失 | 2026-11-03 |
| tests\golden_report.py (Session #14) | 指纹新增 `caliber` / `scenario_calibers`（19 → 21 字段）；`check_invariants()` 新增 invariant #6（情景 `discount_label` 必须 == 引擎口径） | 2026-11-03 |
| tests\golden\report_fingerprints.json (Session #14) | 由 `UPDATE_GOLDEN=1` 重新生成：仅新增 `caliber`/`scenario_calibers` 两字段（JPM 为 `ke`），无其它字段漂移（已审阅的有意变更） | 2026-11-03 |
| classification\ml_classifier.py (Session #15) | 🐛 Round 1：新增 `import re` + 边界感知 `keyword_hit()`（裸 ASCII ≤4 字符 token 强制词边界，长词/带空格/CJK 保留原子串语义）；§6 工业强制覆盖改用 `keyword_hit()` → 修复 ticker `upst` 被工业关键词 `"ups"` 子串误匹配、强制 `Structural FORCE->Industrial` 覆盖 FinTech 的缺陷 | 2026-11-12 |
| classification\classifier.py (Session #15) | 🐛 Round 2：`_model_applicability()` 金融分叉新增 `EV/Sales` 剔除（`na_reasons` 说明「EV embeds funding debt」），与 `EV/EBITDA`/`FCF Yield` 同族；修复「市场区声明 EV N/M 却用 EV/Sales 作估值锚」的同页自相矛盾 | 2026-11-12 |
| reporting\verdict_intuition.py (Session #15) | 🐛 Round 3：`build_valuation_verdict()` 的「股数不可靠」附注改为读 `build_caliber_contract(profile)`——金融标的（EV NOT_MEANINGFUL）给「P/B、P/E、RIM 口径复核」，替代硬编码「以 EV 口径复核」 | 2026-11-12 |
| reporting\dashboard.py (Session #15) | 🐛 Round 3：`_risk_section(rr, profile)` 新增 `profile` 入参并按 `DiscountCaliber.COST_OF_EQUITY` 把 `WACC Risk` 重标为「Cost of Equity Risk（权益成本/β）」（`build_report` 调用点同步传 `profile`）；`_market_section()` β 附注「市场区/风险旗标/WACC 统一采用截断值」→ 中性「折现率」；`import` 增加 `DiscountCaliber` | 2026-11-12 |

---

# 10. Important Decisions

Document important architectural decisions.

## Decision 001: 1001只股票全部通过 YahooFinanceProvider + Synthetic Fallback 收集

Reason: Yahoo quoteSummary (assetProfile) 端点返回 401 Unauthorized 频繁，但 chart + fundamentals-timeseries 端点稳定；数值特征是 ML 训练主信号，文本(sector/industry)是辅助，缺失不致命。开启 use_synthetic_fallback 保证 0 失败率。

Date: 2026-10-05

---

## Decision 002: 不使用 fixed WACC 默认值，严格7步法

Reason: 项目硬约束，保证估值一致性和可解释性。

Date: 2026-09

---

## Decision 003: TVG 采用 min(企业增长, 名义GDP, WACC - 0.5%) 三重下界约束

Reason: 防止 Gordon 增长模型数学发散 (g ≥ WACC时现值无穷大)，同时使终值与宏观经济一致。

Date: 2026-09

---

## Decision 004: ML 模型失败时回退到确定性分类器，而不是报错

Reason: 生产可用性，ML_FALLBACK_THRESHOLD=0.40 已调优；结构覆盖规则 (Structural Overrides) 进一步兜底 4 个高确定性类别 (Bank/REIT/Semi/Util)。

Date: 2026-09

---

## Decision 005: 金融机构指标口径分叉 — 下游解读层以 is_financial_institution 开关为唯一分叉点，不改底层 FinancialStatement 解析

Reason: SOFI 报告连锁误报暴露了把银行 FCF 当普通公司解读的严重问题。银行的 debt/operating CF 本质是业务库存而非普通融资/经营现金流，在解析层统一口径不现实，改为 profile/risk/reporting 三层读取 is_financial_institution 标志分叉。

Date: 2026-10-08

---

## Decision 006: 单标签分类 (11 类 BusinessType) + 多轴暴露度聚合 = Hybrid 表达，不新增 FinTech 枚举值

Reason: BusinessType 直接决定估值模型路由，扩枚举会导致 MODELS_BY_TYPE 膨胀 + 模型权重表重写。FinTech 是 Bank+Tech 的混合光谱，不是离散第 12 类。通过 5 轴 (Fin/Tech/Cyclical/HardAssets/Diversified) 聚合 Top-N 概率，既能表达混合，又不破坏路由。

Date: 2026-10-08

---

## Decision 007: 直观标签（Intuitive Labels）采用「纯函数计算层 + Dataclass 卡片 + 多区块差异化渲染」三层架构；同一条结论在报告中只显示一次 head、多次展开细节

Reason: 用户核心诉求「不用扫数字就能直接看结论」需要放在最前面（首屏），但估值细节（中位估值对比、情景跨度、公允区间、判断依据）又需要在模型比较章节重复出现。如果两次都展示同一句话结论（"一句话估值：高估"），会导致冗余、让用户疑惑"为什么又说一遍"。

方案：
1. **数据卡片（Data Layer）**：`ValuationVerdictCard` 只存结构化标签（headline_label/emoji/headline_summary、median_vs_price_label/detail、scenario_summary、reasoning、fair_value_range 等），不负责「要不要显示」
2. **纯函数计算（Compute Layer）**：`reporting/verdict_intuition.py` 两个纯函数 build_growth_verdict() + build_valuation_verdict()，输入原始 analysis 结果（gap/model_agreement/scenarios 等），输出卡片；零副作用便于 pytest
3. **多区块渲染（Render Layer）**：`header_lines(include_headline=True)` + `bullet_lines()` 支持分层渲染：
   - **Overview 首屏**：include_headline=True → 一句话结论 + bullet 全细节（用户第一眼看到结论）
   - **Agreement 模型比较**：include_headline=False + 改标题为「估值细节拆解」→ 只展示 bullet 细节（中位估值/情景/区间），不重复展示「一句话结论」
   - **Gap 增长区**：只调用 growth.bullet_lines() → 增长细节，不在其他区重复
4. **主语不自包原则**：detail 字段是自包含完整句（"当前价 $15.58 较中位估值 $11.01 高出 +41.6%"），外层渲染时不要再包一层前缀（如「（中位估值 ...）」），否则会出现「中位估值 较中位估值」的主语重复 bug

Date: 2026-10-08

---

## Decision 008: 新增只读「数据对账层」(reconciliation.py)，在任何倍数被消费前先做恒等式交叉校验

Reason: NBIS 报告暴露单点供应商字段（如年度口径 EBITDA 用于 EV/EBITDA、虚高 trailing P/E、股数年度 vs 市值口径不一致）会静默扭曲估值倍数，用户无法察觉。对账层以纯函数 reconcile(data) 做 10 项交叉校验（市值≈价×股数 / EV≈市值+债−现 / EPS≈净利÷股数 / P-E≈价÷EPS / EV-EBITDA / P-B / EV-Sales / FCF≈OCF+capex / 股数≈年度股数 / EBITDA≤营收），对恒等式用 5% 紧容差、对供应商口径差异用 20% 松容差、股数 25%。**关键约束：只读，绝不突变 FinancialData**——不一致只做「标记 + 渲染 + 备注」，由下游（multiples 守卫 / 数据质量评分）决定是否降级处理，避免污染主数据流。

Date: 2026-10-27

---

## Decision 009: Peer 倍数按「经济结构」而非「粗粒度行业」路由；重资本算力业务强制改道 AI/Cloud Infrastructure

Reason: 原 `"SaaS → Technology"` 粗桶把软件/半导体/算力基础设施混为一谈，对 NBIS（AI 云/GPU 租赁：capex/revenue≈822%、负 FCF、高增长）套用 SaaS 的 P/E 22 + EV/Sales 4 严重扭曲估值。方案：(1) 技术族按经济结构拆细为 Software-SaaS / Software-Mature / Semiconductors / AI/Cloud Infrastructure；(2) 新增 `_compute_infra_override()` 以「Very Capital Intensive + 高增长 + 负 FCF + capex/revenue≥1.0」四条件识别算力建设，命中则把技术族键重路由到 AI/Cloud 桶并在 source 串标注 `(APPROXIMATE)`；(3) 对「结构上无意义」的倍数加硬守卫：隐含 P/E > 100x（净利极薄）→ P/E not meaningful，EBITDA/营收 > 90%（D&A 主导）→ EV/EBITDA not comparable。原则：倍数只有在标的与 peer 具备相同经济结构（资产轻重、资本强度、现金流形态）时才可比。

Date: 2026-10-27

---

## Decision 010: 分类置信度必须反映「原型冲突」——ML 标签与财务原型矛盾时显式降权，而非静默采信

Reason: NBIS 被 ML 判为 SaaS 92%（基于数值特征），但资产轻重原型完全相反（重资本、负 FCF）。若静默采信会把重资本算力业务导入资产轻 SaaS 的估值/风险模板。方案：ml_classifier.py 新增 "Asset-light prototype conflict" 步骤——当 ML 判为资产轻类型（SaaS/MatureTech/Media）但 capex/revenue≥1.0 且负 FCF 时，置信度 cap 50% 并写入 ConfidenceAdjustment 审计链。原则：**分类不确定性必须向估值确定性传导**，宁可在报告里显式暴露「标签与原型冲突」，也不给出伪精确的估值。

Date: 2026-10-27

---

## Decision 011: 一致性必须做「覆盖率门控」——低覆盖率绝不允许输出强一致性；一致性 = 基础离散度 × 覆盖率因子 × 质量因子

Reason: 第二版 NBIS 报告用 2/6 个低置信模型得出 "Very Strong 一致性 + 显著高估"，属幸存者偏差：把 4 个失败/不适用模型剔除后，仅剩两个恰好接近的模型，离散度被人为压小，于是"依据更少、结论更自信"。方案：analysis/model_agreement.py 重写——(1) 模型三桶分类：solved / not_applicable（INSUFFICIENT_DATA，如 EPS≈0 的 P/E、D&A 异常的 EV/EBITDA）/ failed（NO_SOLUTION_IN_RANGE 等）；(2) `gated_cv = base_cv × 覆盖因子 ÷ 质量因子`（覆盖因子 = sqrt(applicable/solved) clamp [1.0, 2.0]；质量因子：SOLVED=1.0、APPROXIMATE=0.5、分类置信度<0.55 再×0.5、TV/EV>0.8 的 DCF 再×0.5）；(3) 硬覆盖率封顶：solved≤1→Very Weak、==2→Weak、==3→Moderate、≥4 不封顶。原则：**一致性是对"证据充分"的陈述，不是对"幸存样本互相接近"的陈述**。

Date: 2026-10-27

---

## Decision 012: 中位估值改为「质量加权中位数」，并显式区分「源数据质量」与「估值可用性」

Reason: 原中位 $26.88 ≈ ($26.41+$27.35)/2，把两个低质量模型（TV/EV=536% 的 DCF + APPROXIMATE 的 EV/Sales）等权平均，伪装成"公允价"。方案：(1) 权重体系（SOLVED=1.0 / APPROXIMATE=0.5 / TV/EV>80% 的 DCF 再×0.5 / 分类置信度<55% 的倍数再×0.5）驱动 `median_value_weighted`，并在报告展示每个模型权重、降权/剔除原因；(2) 数据质量评分拆为「源数据质量」（83/100，反映 provider 原始数据完整性）与「估值可用性」（34/100，随对账不一致项数扣减，且股数偏差>25% 触发 per-share 基数不可靠 → 抑制每股公允值）；(3) 中位值标签明确为「低置信模型集成值」性质而非"公允估值"。原则：**当唯一可用证据是低质量证据时，输出必须是"低置信参考"，而不是伪精确数字**。

Date: 2026-10-27

---

## Decision 013: 估值结论改用「概率语言」——输出 P(内在>价格)/P(高估>30%)/P(股权归零)，蒙特卡洛与模型集成口径统一

Reason: 第二版蒙特卡洛中位 $32.47、P99 $164.30，当前价在 P98–P99，本质是"高估概率极高"的稳健信号，却被单点"中位 $26.88"淹没。方案：simulation/monte_carlo.py 重写——(1) 输出 `prob_above_price` / `prob_overvalued_30` / `prob_equity_zero` 三个概率结论并在报告渲染；(2) 4×4 驱动因子（revenue cagr / operating margin / WACC / terminal g）用 Cholesky 分解做相关抽样（不再独立乱抽）+ Gordon 稳定约束 `tg = min(tg, wacc-0.005)`；(3) 负每股价值 floor 到 0 并计入归零概率（不再丢弃尾部）。原则：**当分布尾部信息比中位数更稳健时，用概率说话比用单点说话更诚实**。

Date: 2026-10-27

---

## Decision 014: 重资本高增长/亏损期标的引入 Replacement-cost NAV 作为覆盖率锚，而非靠降权规避

Reason: NBIS 只有 2/3 模型解算（DCF 因负 FCF 近乎失效、P/E 1205x 不适用、EV/EBITDA 被 D&A 拉爆）——覆盖率是当前最大短板。降权只能回避问题，不能让结论更可靠。方案：(1) 新建 `models/replacement_nav.py`，用资产基础锚 `equity = book_equity + net_ppe×(factor−1)`（net_ppe=Σcapex−ΣD&A，缺 book_equity 时回退 `replacement_ppe − net_debt`），factor 默认 1.15 并附 5 档敏感性；(2) 分类器 `_is_replacement_nav_candidate()` 对「重资本（capex/revenue≥0.30）+ 负 FCF/亏损 + net_ppe>0」的 build-out 动态追加该模型入桶（排除金融/REIT）。原则：**覆盖率不足应通过引入适配资产结构的模型族解决，而不是把已有模型降权**。NBIS 覆盖率 2/3 → **5/6**。

Date: 2026-11-03

---

## Decision 015: 对账层升级为「只读探测 + 显式写侧反向校验 + 审计链」双模

Reason: 第一代对账层只标记不修正，下游仍读到被污染的供应商基数（NBIS 股数偏差 +42.9%、EV/EBITDA 偏差 +155.8%）。仅渲染警告不足以保证估值不读错数据。方案：(1) 保留 `reconcile()` 纯只读探测；(2) 新增 `apply_overrides()` 写侧——当某项偏差 > `_OVERRIDE_TOLERANCE`(25%) 时，按 `_OVERRIDE_FIELDS` 白名单自动改用内部推算值并写入 `OverrideRecord`（含 provider_value/internal_value/rel_diff/reason/applied）；(3) 股数守卫：若股数偏差 >25% 但市值恒等式自洽 → 仅标注不覆盖；若恒等式被破坏 → 按市值/价格反推；(4) `OverrideLog` 全量审计链，`reporting/dashboard.py` 渲染「🩹 对账自动修正」。原则：**只标记不修正在污染基数面前不够——但任何写回必须白名单 + 审计 + 可渲染，绝非静默改写**。

Date: 2026-11-03（修订 ADR-011「只读」硬约束）

---

## Decision 016: 递归自改进工程化为「golden report diff」——把上一轮报告→缺陷清单变成可断言回归

Reason: 递归自我改进此前靠人工读报告找自相矛盾，不可扩展，且下一轮改动引入新矛盾时无法自动发现。方案：(1) `tests/golden_report.py::build_fingerprint()` 从完整 pipeline 提取 19 个**稳定决策信号**（非原始文本，避免时间戳漂移）：business_type/applicable_models/分桶计数(n_total/applicable/solved/failed/not_applicable/display_only)/agreement_level/median_value(+weighted)/beta_effective(+origin)/recon_checks/mismatches/override_applied/risk_score/severity/types；(2) `check_invariants()` 返回自相矛盾清单（覆盖恒等式 / agreement 超覆盖率封顶 / 负中位 / β 三处一致 / 每个 applied override 实际生效）；(3) `tests/test_golden_report.py` 对 `report_fingerprints.json` 基线逐字段 diff，`UPDATE_GOLDEN=1` 刷新。原则：**自改进的验收必须是可断言的产物，而非人工读报告**。

Date: 2026-11-03

---

## Decision 017: Beta 全链路统一为单一 `resolve_effective_beta()` 出口

Reason: 市场区 / 风险旗标 / WACC 三处各读不同 β 口径（原始回归 β vs winsorize 截断 β），用户会读到互相矛盾的 β。方案：`valuation/wacc.py::resolve_effective_beta(data, dcf_breakdown)` 成为唯一出口，按优先级 `wacc_breakdown → provider(winsorized) → fallback` 解析并返回带 `origin` 的可审计对象；三处共用同一值；golden `check_invariants()` 断言 β 一致。原则：**同一指标在多处展示时，必须来自同一解析函数**。

Date: 2026-11-03

---

## Decision 018: 重资本高增长/亏损期标的补第二条腿——EV/Sales + 单位经济学（earnings-power 锚），且诚实固定为 APPROXIMATE

Reason: Replacement NAV（Decision 014）提供的是**资产基础锚**（"重建这套算力设备要多少钱"），但它回答不了"这些资产装好之后按其成熟单价能挣多少"——对重资本建设期标的（如 NBIS），资产重估值与 earniings-power 会系统性分叉，仅有资产锚会让结论偏向清算视角。方案：新建 `models/unit_economics.py::UnitEconomicsSalesModel`，用独立的经济含义补第二条腿——(1) `deployed_capital = Σcapex − ΣD&A`（已投入净算力资本）；(2) `capacity_revenue = max(TTM营收, deployed_capital × BENCHMARK_REVENUE_YIELD)`（把未投产/低利用率算力按成熟数据中心营收/净PP&E 基准 35% 折算为**产能口径营收**）；(3) `EV = capacity_revenue × MATURE_EV_SALES × ramp_discount`（成熟 EV/Sales=4.0，按爬坡折现 `(1+WACC)^−(RAMP_YEARS × utilisation_gap)`，`utilisation_gap=clamp(1−current_yield/benchmark_yield,0,1)`）；(4) 分类器 `_is_unit_economics_candidate()` 对「capex/revenue≥0.50 + 负 FCF/亏损 + net_ppe>0」的 build-out 动态入桶（排除金融/REIT）。**诚实性硬约束**：数据层无 GPU 稼动率/ARPU 明细字段，故用「营收/净PP&E 相对成熟基准」作派生代理，模型**固定返回 `SolverStatus.APPROXIMATE`，永不 SOLVED**，并在 notes 标注"派生代理/方向性参考"，避免虚假精度。原则：**覆盖率不足应通过引入经济含义独立、口径诚实的模型族解决；第二条腿必须与第一条腿在经济学上正交，而非同一逻辑换个名字**。NBIS 覆盖率 **5/6 → 6/7**（EV/Sales Unit Econ $27.02）。

Date: 2026-11-03

---

## Decision 019: 递归改进遵循「命名矛盾，不做平均」——同一报告内的口径冲突必须显式陈述，派生值必须结构化落字段

Reason: CRWV 三轮递归暴露同一类系统性失效——**报告内部出现两个方向相反的结论却不点名**：
- Round 1：报告头 `MatureTech/SaaS` 与 peer 区 `AI/Cloud Infrastructure` 互相矛盾。根因是**同一套「资产轻原型冲突」逻辑只在 ML 分类路径实现，确定性规则路径（离线/golden 走这条）漏实现**。原则：**同一判定必须在两条分类路径口径一致**（`classifier.py` 与 `ml_classifier.py` 对齐），
- Round 2：一句话结论里「中位口径判显著高估（$6.87）」与「DCF 基准情景 $138.57 反判低估」方向相反，报告未命名该冲突。原则：**方向性口径冲突必须显式命名（⚠️ 口径冲突：…）并归因（DCF 终值主导已被降权/剔除），绝不用平均把矛盾抹平**——平均会制造一个两个口径都不支持的伪共识。附带修正：措辞必须与基期一致（"高于当前价 X%" 必须用 price-relative，而非 base-relative），否则修复本身引入新的口径错误。
- Round 3：`ReverseDCF` 的成熟稳态推导值（隐含营收 CAGR ≈26%）**只存在于 free-text note，结构化字段 `implied_revenue_cagr` 却显示 N/A**。原则：**凡引擎已经推导出的量，必须落到结构化字段（并携带 `*_source` 来源标记）而非仅藏在注释**；派生/近似量必须在展示层标注 APPROXIMATE，杜绝「字段 N/A 但正文有值」的自相矛盾。

三条统一为一条递归改进原则：**矛盾要命名不要掩盖；口径要同基不要混用；派生量要结构化不要埋在注释**。

Date: 2026-11-03

---

## Decision 020: 金融机构的三档情景必须由适配主模型（Bank RIM）生成，禁用 DCF 口径

Reason: SOFI 递归第 2 轮暴露——报告主模型区已正确路由到 **Bank RIM**（$9.52），但**情景分析区仍走 DCF 口径**（WACC 15.1%，$12.61~15.94），两个口径方向相反却未命名。根因：`is_financial_institution` 分叉（Decision 005 / ADR-008）只覆盖 profile/risk/reporting，未覆盖 scenario/sensitivity。

原则：**金融机构（银行/保险）的主模型、情景、敏感性、peer 倍数四处必须同属金融适配口径，任一出现 DCF 残留即视为缺陷**。
- `ScenarioAnalyzer.run_all()` 增金融分叉 → `_run_financial_scenarios()`：Bear/Base/Bull 由 Bank RIM 沿 `ke` 变动（`_FIN_BETA_STEP=0.30`，β∈[0.30, 2.50]）生成；
- 情景结果携带 `discount_label`（金融 `"ke"` / 非金融 `"WACC"`）供展示层按口径渲染；
- 金融标的的 `sensitivity` 区直接返回「不适用 DCF 敏感性矩阵」说明文案。
- 效果：SOFI 情景 $9.26 / $9.52 / $9.79（跨度 22% → 6% SV），与中位锚点同基；JPM 回归亦走 Bank RIM。

Date: 2026-11-03

---

## Decision 021: 置信度「封顶到边界值」必须用 `<=` 守卫（下界常量），严禁严格 `<`

Reason: SOFI 递归第 3 轮暴露——分类器在 `sector/industry` 缺失时把置信度**封顶到恰好 0.55**（`min(confidence, 0.55)`），但 peer 倍数「未充分验证」守卫写作严格 `conf < 0.55` → **恰好等于边界的封顶情形被漏检**，P/E、P/B 把 55% 置信的银行 peer 倍数当作完全已验证。

原则：**凡「封顶到边界值」的语义，判定端一律用闭区间（`<=` / `>=`）**；上游是 `min(x, C)` / `max(x, C)` 时 `x` 会精确落在 `C` 上，严格比较必然漏检。阈值必须提为模块常量（`_PEER_MULTIPLE_CONF_FLOOR=0.55`）并被展示端复用，避免魔数散落。修复后下游指标如实响应（质量因子 1.00→0.67、一致性 Moderate→Weak），**不做调参规避**（与 Decision 018 一致）。

Date: 2026-11-03

---

## Decision 022: 口径必须作为引擎输出的枚举契约，渲染层禁止猜口径

Reason: 「某指标对某类标的有无意义」过去散落在展示层内联判断（`if profile.is_financial_institution:`），同一口径在多个区块重复实现，任一处遗漏即产生「主模型 A / 情景 B」的自相矛盾（Session #13 Round 2），且只能人工通读发现。

原则：**凡「该指标对某类标的有/无意义」都由引擎输出一个枚举，展示层只按契约分支，禁止在渲染层猜口径。**
- 新增 `valuation/caliber.py`：`MetricMeaning`(MEANINGFUL/REFERENCE_ONLY/NOT_MEANINGFUL) + `DiscountCaliber`(WACC/ke) + `CaliberContract` + `build_caliber_contract(profile)`（依 `is_financial_institution`/`is_reit` 单一分叉）；
- `dashboard.py` 删除内联猜口径，改为消费契约（N/M、附注、敏感性是否适用全部来自契约）；
- 口径进入 golden 指纹（`caliber`/`scenario_calibers`）与 invariant #6（情景口径必须 == 引擎口径）。

Date: 2026-11-03

---

## Decision 023: `min/max` 封顶点系统性审计——静态扫描 + 跨文件断言，闭区间唯一合规

Reason: Decision 021 只修了 peer 倍数一处，属人工发现、不可持续；更隐蔽的是**跨文件**形态（`classifier.py` 封顶 confidence 到 0.55，`sotp.py` 用 `conf < 0.55` 判定），任何「同文件」启发式都发现不了。

原则：**把「封顶到边界值 → 闭区间判定」提升为 CI 断言**（`tests/test_cap_boundary_guard.py`）：
- Part A 常量守卫闭区间断言（登记 `min/max` 封顶常量 → 文件，出现严格比较即失败）；
- Part B 同文件字面量配对自动扫描（新增配对必须人工审阅或白名单 + 理由）；
- Part C 跨文件 confidence 封顶断言（扫描全模块 `conf < {0.40,0.50,0.55}`）→ 本次**捕获并修复** `models/sotp.py` 两处跨文件漏检。

Date: 2026-11-03

---

# 11. Known Issues

| Issue | Status | Solution |
|--------|--------|----------|
| Yahoo quoteSummary/assetProfile 端点 401 Unauthorized (830/1000 = 83%) | ⚠️ Acceptable → 🔧 优化中 | 数值特征完整 (15/15)，文本特征仅 company_name 可用；下一步用 Alpha Vantage / yfinance.info fallback 补全 sector+industry 推高边界准确率 |
| CSV 第一列多一行 "ticker" 重复表头 (PowerShell Import-Csv/Export-Csv 遗留) | ✅ Resolved | 实测 labeling_dump.csv 1000 行数据 + 1 行表头，无重复表头 L2 垃圾行；之前警告已清除 |
| 部分 Yahoo ticker 返回 404 (如 COUP, FUV, TESS, TPRO, SOL) | ✅ Resolved | 合成数据填充，note 列标注，数量<1%可忽略 |
| interest_to_revenue = 0 占 821/1000 = 82.1% | ⚠️ High Impact → 🔧 优化中 | Bank/REIT/Utilities/Insurance 分类关键信号缺失；下一步脚本重算: interest_expense / revenue |
| Semiconductor 类别样本过少 (29/1000 = 2.9%) | ⚠️ Medium → 🔧 优化中 | AVGO 实际应为 Semiconductor 但被标成 MatureTech 进一步加剧；下一步 class_weight='balanced' + SMOTE |
| Unknown 类别占比过高 (354/1000 = 35.4%) | ⚠️ Acceptable | 可接受：早期标注阶段大量边缘公司先归 Unknown；扩充到 5000 训练集后占比会下降 |
| ⚠️ **SOFI 连锁误报 #1：ML 置信度 66.6% → 业务类型 55% 黑盒扣减** | ✅ Resolved (2026-10-08) | 根因：sector/industry missing 触发 confidence=min(conf, 0.55) 未透明记录。修复：新增 ConfidenceAdjustment[]，所有扣减 step + delta(pp) + reason 全链路记录并在业务区块渲染拆解明细 |
| ⚠️ **SOFI 连锁误报 #2：单标签分类无法表达 FinTech 混合业务** | ✅ Resolved (2026-10-08) | 根因：11 类无 FinTech/Hybrid，Bank+Unknown+MatureTech 混合被硬判为 Bank。修复：不扩枚举，新增 3 条 Hybrid 触发规则 + 5 轴 Exposures 聚合 (Fin/Tech/Cyclical/HardAssets/Diversified) |
| ⚠️ **SOFI 连锁误报 #3：银行 FCF=-$9B 触发 3 个风险误报 (score 80→95)** | ✅ Resolved (2026-10-08) | 根因：把银行的 Operating CF - Capex 当普通公司 FCF 解读，产生 Weak FCF 标签 + 4y neg-FCF Medium + FCF Yield=-60% High 三个连锁误报。修复：7 层机构敏感分叉，风险评分 80→95 |
| ⚠️ **Session #05 Bug #1：中位估值对比主语重复「中位估值 较中位估值高 +41.6%」** | ✅ Resolved (2026-10-08) | 根因：detail = f"（中位估值 {median_vs_price_detail}）" 外层多加了前缀，但 median_vs_price_detail 内部已自带「当前价较中位估值」完整句。修复：直接 `f"（{detail}）"`，去掉「中位估值」前缀；Decision 007 新增「主语不自包原则」 |
| ⚠️ **Session #05 Bug #2：一句话估值在 OVERVIEW + AGREEMENT 双区块重复展示（headline_summary 逻辑重复）** | ✅ Resolved (2026-10-08) | 根因：两处都调了 v.header_lines() 默认 include_headline=True。修复：header_lines() 新增 include_headline 关键字参数；agreement section 改为 `v.header_lines(include_headline=False)` + 标题改名「🤝 估值细节拆解」，只展示 bullet 细节不重复 headline；Decision 007 明确「一次 head、多次细节」 |
| ⚠️ **NBIS #1：ML Top-1 SaaS 92% 但 sector/industry 缺失 → 置信度被封顶 55% 却无「原型冲突」提示** | ✅ Resolved (2026-10-27) | 根因：置信度只看「数据是否缺失」，不看「标签是否与财务原型矛盾」。修复：新增 "Asset-light prototype conflict" 扣减（capex/revenue≥1.0 + 负 FCF → cap 50%），审计链留痕（Decision 010） |
| ⚠️ **NBIS #2：P/E/EV-EBITDA/EV-Sales 全被路由到粗桶 "SaaS → Technology"（P/E 22 / EV-EBITDA 14 / EV-Sales 4）** | ✅ Resolved (2026-10-27) | 根因：技术族 peer 桶过粗，混同软件/半导体/算力基础设施。修复：细粒度桶 + AI/Cloud Infrastructure 重路由 + 倍数结构守卫（Decision 009） |
| ⚠️ **NBIS #3：P/E 对净利仅 $42M（隐含 ~1307x）仍给出 $2.58 估值，误导性极强** | ✅ Resolved (2026-10-27) | 根因：无「倍数无意义」守卫。修复：applicability_check() 隐含 P/E > 100x → P/E not meaningful（Insufficient Data）；EBITDA/营收 > 90% → EV/EBITDA not comparable |
| ⚠️ **NBIS #4：单点供应商字段静默失真（trailing P/E 671 vs 内部推算 1307；股数 361.5M vs 253.0M；EBITDA 口径年度 vs TTM）** | ✅ Resolved (2026-10-27) | 根因：无跨字段交叉校验。修复：新建只读对账层 data/reconciliation.py（10 项恒等式校验）+ 仪表盘渲染不匹配项（Decision 008） |
| test_terminal_growth.py::test_floor_base_keeps_low_strictly_below 失败（TVG floor 逻辑） | ✅ Resolved (2026-10-27) | 原为历史遗留（base 0.5% vs 预期 1.5%）。修复：0≤base<1.5% 分支改为抬高到成熟地板 BASE_FLOOR(1.5%) 而非坍缩到 DECLINING_BASE(0.5%)；全量 pytest 61/61 |
| ⚠️ **NBIS 第二版 #1（最严重）：2/6 覆盖率却报 "Very Strong 一致性 + 显著高估"（幸存者偏差）** | ✅ Resolved (2026-10-27) | 根因：剔除 4 个失败/不适用模型后仅剩两个恰近模型，离散度被人为压小。修复：覆盖率门控 gated_cv + 硬覆盖率封顶（solved==2→Weak）；NBIS 由 Very Strong→**Weak**（Decision 011） |
| ⚠️ **NBIS 第二版 #2：中位 $26.88 = 两个低质量模型等权平均，被当作"公允价"** | ✅ Resolved (2026-10-27) | 根因：无质量加权。修复：质量加权中位数（DCF TV/EV>80% 降权、APPROXIMATE 降权、分类置信度<55% 再降权）+ 展示权重/降权原因；中位值性质标为"低置信模型集成值"（Decision 012） |
| ⚠️ **NBIS 第二版 #3：每股估值基数不可用（股数 361.5M vs 253.0M 差 42.9%）却仍输出两位小数每股公允值** | ✅ Resolved (2026-10-27) | 根因：无 per-share 基数门控 + 质量评分未反映"可用性"。修复：估值可用性评分（与源数据质量分离）+ 股数偏差>25% → `per_share_basis_unreliable` → 抑制每股公允值，仅方向性参考（NBIS: 源数据 83 vs 可用性 34） |
| ⚠️ **NBIS 第二版 #4：情景/中位/公允区间口径不一致；"当前价落在熊市~牛市区间"错误；熊市 -$4.20 负价格** | ✅ Resolved (2026-10-27) | 修复：`_scenario_summary()` 支持"当前价高于**全部**情景"；负 pps floor 到 0 + "股权价值归零"note；公允区间标注样本数 n + 覆盖率；三类口径分开陈述 |
| ⚠️ **NBIS 第二版 #5：分类仍偏 SaaS、peer 仍是近似值、50% 置信倍数仍占中位一半** | ✅ Resolved (2026-10-27) | 修复：新增人工 `AI_CLOUD_PEER_GROUP`（CoreWeave/IREN/Equinix/Oracle/Nebius）+ 参考带展示；分类置信度<55% 的 APPROXIMATE 倍数权重再×0.5（不能占中位一半） |
| ⚠️ **NBIS 第二版 #6：WACC 单点 17.51% 失控（超行业区间 6.5%~11.5%）；反向 DCF 输出无意义负 EV** | ✅ Resolved (2026-10-27) | 修复：WACC 三 beta 透明化（raw/winsorized/bottom-up）+ `wacc_range_note()`；输出行业区间上下沿估值（NBIS 6.5%→$1,574.90 / 11.5%→$237.37）；反向 DCF 隐含量化"当前价隐含营收 CAGR ≈ 27%"替代负 EV |
| ⚠️ **NBIS 第二版 #7：蒙特卡洛与模型集成口径不一致；无概率结论；负值处理不当** | ✅ Resolved (2026-10-27) | 修复：蒙特卡洛输出 P(内在>价格)/P(高估>30%)/P(股权归零)（NBIS: 0.3% / 97.5% / 6.7%）；4×4 驱动因子 Cholesky 相关抽样；负值 floor 计入归零概率（Decision 013） |
| ⚠️ **Session #10 #1（最大短板）：NBIS 覆盖率仅 2/3（DCF 负 FCF 近乎失效、P/E 1205x 不适用、EV/EBITDA D&A 拉爆）** | ✅ Resolved (2026-11-03) | 根因：缺少适配「重资本高增长/亏损期」资产结构的模型族，只能靠降权规避。修复：新增 `ReplacementNAVModel` + 分类器动态入桶 → NBIS 覆盖率 **2/3 → 5/6**（Decision 014） |
| ⚠️ **Session #10 #2：对账层只标记不修正，下游仍读到污染基数** | ✅ Resolved (2026-11-03) | 根因：`reconcile()` 纯只读、无写侧，偏差 >25% 仅渲染警告。修复：新增 `apply_overrides()` 白名单写侧（偏差 >25% 自动改用内部推算值）+ `OverrideLog` 审计链 + 股数守卫 + dashboard「🩹 对账自动修正」渲染（Decision 015） |
| ⚠️ **Session #10 #3：自改进靠人工读报告找矛盾，不可扩展** | ✅ Resolved (2026-11-03) | 根因：无「上一轮报告 → 缺陷清单」的可断言产物。修复：golden report diff（19 字段指纹 + 5 类 invariant 检查 + JSON 基线逐字段 diff）（Decision 016） |
| ⚠️ **Session #10 #4：β 在市场区/风险旗标/WACC 三处各读不同口径** | ✅ Resolved (2026-11-03) | 根因：三处各取原始/winsorize β。修复：统一为 `resolve_effective_beta()` 单一出口（Decision 017），golden invariant 断言一致 |
| ⚠️ **Session #10 #5：REIT（AMT）与 Energy（XOM）资产结构缺端到端回归覆盖** | ✅ Resolved (2026-11-03) | 修复：新增 AMT/XOM 合成 fixtures + `test_asset_structure_coverage.py` 断言（AMT REIT NAV 4/4；XOM Energy 5/5 Strong） |
| ⚠️ **Session #11 #1：一致性水平由 Weak → Very Weak（NBIS），为真实信号非缺陷** | 🟡 By Design (2026-11-03) | 根因：新增 `EV/Sales (Unit Econ)` $27.02 居中，使 IQR 上界抬高 → 原被离群过滤的 DCF（TV/EV=404%）重新进入样本 → 离散度 247.5%、一致性如实降为 Very Weak、门控 CV 130.4%。**判定为真实信号（模型分歧扩大），非缺陷，不做调参规避**；这是「引入新证据 → 一致性指标诚实响应」的预期行为（Decision 018） |
| ⚠️ **Session #11 #2：单位经济学模型为「派生代理」而非明细驱动** | 🟡 Open / By Design (2026-11-03) | 数据层暂无 GPU 稼动率 / ARPU 明细字段，`benchmark_revenue_yield`（成熟营收/净PP&E=35%）与 `utilisation_gap` 为相对成熟基准的派生量。缓解：模型固定返回 `APPROXIMATE`（绝不 SOLVED）+ notes 标注方向性；后续若接入算力稼动率数据源可升级为直接驱动 |
| ⚠️ **Session #12 #1：WACC 行业 sanity 区间在原型重路由后仍按原标签（Software 8%~11.5%）** | 🟡 Open (2026-11-03) | CRWV 已重路由为 `AI/Cloud Infrastructure`，但 WACC 区间的 `Industry sanity` 仍读被拒标签 `Software` → 出现「peer 用 AI/Cloud，WACC 用 Software」的轻度口径不一致。影响有限（同属技术族），暂记录待与 peer 桶一并收口 |
| ⚠️ **Session #12 #2：fingerprint 顶层 `business_type` 保留原始标签（MatureTech），重路由仅在 `effective_business_type`** | 🟡 By Design (2026-11-03) | golden 指纹 `business_type` 反映**分类器原始输出**，重路由是估值原型层的独立字段（`effective_business_type`）——保留二者分离是有意的（原始标签可审计、重路由可追溯），非缺陷 |
| ⚠️ **Session #13 #1：SOFI 情景分析走 DCF 口径，与主模型 Bank RIM 方向相反却未命名** | ✅ Resolved (2026-11-03) | 根因：`is_financial_institution` 分叉（ADR-008）未覆盖 scenario/sensitivity。修复：`_run_financial_scenarios()`（Bank RIM 沿 ke）+ 情景区 `discount_label` 渲染 + 敏感性金融守卫（Decision 020 / ADR-022） |
| ⚠️ **Session #13 #2：银行模型 β/ke 与全报告其它区口径不统一** | ✅ Resolved (2026-11-03) | 根因：Bank DDM/RIM 未收敛到单一 β 出口。修复：统一 `resolve_effective_beta()` + 同源 Rf/ERP + `_BANK_KE_BAND` 越界提示（Round 1） |
| ⚠️ **Session #13 #3：peer 倍数置信度「封顶到恰好 0.55」时边界漏检（严格 `<`）** | ✅ Resolved (2026-11-03) | 根因：守卫用 `conf < 0.55` 但上游封顶恰为 0.55。修复：常量 `_PEER_MULTIPLE_CONF_FLOOR` + `<=`；SOFI P/E、P/B 均标 NOT FULLY VALIDATED（Decision 021 / ADR-023） |
| ⚠️ **Session #13 #4：SOFI hybrid 标签/SOTP 未触发（tech_p=5.5% < Case B 阈值 8%）** | 🟡 Open / 数据驱动 (2026-11-03) | SOFI 业务模式暴露度 Technology 仅 5.5%，未达 `ml_classifier.py::_detect_hybrid` Case B 的 `tech_p>=0.08` 阈值 → 不加 hybrid 标签、不做 SOTP。属**数据驱动**（sector/industry 缺失压低 tech 权重），非算法缺陷；待特征补全后复评，勿轻调阈值（会影响 golden 基线）。Session #14 已将阈值提为具名常量 `HYBRID_FIN_TO_TECH_FLOOR` 锁定 |
| ⚠️ **Session #14 #1：跨文件 ADR-023——SOTP 置信度守卫漏检** | ✅ Resolved (2026-11-03) | 根因：`models/sotp.py` 用 `conf < 0.55`，但上游 `classification/classifier.py:509` 把 confidence 封顶到**恰好 0.55**（sector/industry 缺失）→ 被降级的分类被判为高置信。修复：改 `conf <= 0.55`（2 处）；新增跨文件断言 `test_confidence_cap_guards_use_closed_interval` 锁定（Decision 023 / ADR-025） |
| ⚠️ **Session #14 #2：渲染层口径判定散落、无 invariant 守卫** | ✅ Resolved (2026-11-03) | 根因：口径判断内联在展示层多处，场景/主模型不一致靠人工通读发现。修复：新增 `valuation/caliber.py` 契约 + dashboard 消费契约 + invariant #6（Decision 022 / ADR-024） |
| ⚠️ **Session #14 #3：金融情景仅沿 ke 敏感，缺经营性驱动** | ✅ Resolved (2026-11-03) | 根因：金融情景只变 β/ke，未反映经营（净息差/拨备）。修复：`BankRIMModel` 支持 `roe_override` + `_FIN_ROE_SHOCK=0.20`，金融情景为 ke + 经营性 ROE 双驱动（Decision 020 深化） |
| ⚠️ **Session #14 #4：封顶审计 Part B 基于字面量，存在「不同变量同值」误报** | 🟡 By Design (2026-11-03) | 扫描器以数值字面量为键，无法区分变量（如 `confidence` vs `top1_p` 同为 0.55）。缓解：命中项须人工审阅后加白名单 + 理由；真正的 confidence 封顶由 Part C 跨文件断言兜底。判定为可接受的召回/精确度权衡 |

---

# 12. Blockers

Current blockers preventing progress.

```
🟡 MINOR BLOCKER: 特征补全 (sector/industry + interest_to_revenue)
  - sector/industry 缺失率 83% → 用 Alpha Vantage / yfinance.info 批量跑一次补全（需要 API key）
  - interest_to_revenue 缺失率 82% → 从 TTM interest_expense / revenue 重新计算（可本地完成，无需 API）
  - AVGO 等少数样本标签错误需人工确认修正
```

---

# 13. Things Already Finished (DO NOT REPEAT)

Never repeat these tasks.

- ✅ 项目模块架构设计 (8个模块目录)
- ✅ Yahoo Finance Provider (异步 + 4h缓存 + 合成fallback)
- ✅ WACC 7步法实时计算
- ✅ 终值增长率 TVG 约束逻辑
- ✅ DCF / Reverse DCF / NAV / Bank / SOTP / Multiples 6个估值模型
- ✅ 敏感性分析矩阵 + 稳定性分级
- ✅ 确定性 BusinessClassifier (11类, ~85%)
- ✅ LightGBM ML 分类器合成版 (1500样本)
- ✅ Telegram Bot 集成 (python-telegram-bot)
- ✅ 🔴 1000只真实股票特征数据收集 (classification\labeling_dump.csv, 1000行有效, L2垃圾行验证已清除)
- ✅ ✨ 真实标注版 LightGBM v2.1 训练发布 (train_acc=97.40%, n=1000, 11类完整)
- ✅ demo_fast 分类正确性验证 (16只 sanity, 12/16=75%)
- ✅ 🔴 SOFI 报告三问修复：
  (1) 置信度黑盒透明化 (ML 66.6% → Missing-sector cap -11.6% → Final 55%)
  (2) 混合业务 Hybrid 表达 (SOFI=Hybrid Financial Institution, 3条触发规则+5轴暴露度)
  (3) 金融机构指标口径适配 (7层分叉, risk score 80→95)
- ✅ pytest 27/27 回归通过 (risk/classifier/ml_classifier/sensitivity/dcf 5套件)
- ✅ demo_fast SOFI 修复验证 + demo_fast AAPL 向后兼容验证 (双端到端通过)
- ✅ ✨ Session #05 直观标签 (Intuitive Labels) 上线：
  • reporting/verdict_intuition.py 新建：Growth + Valuation 两张卡片的纯函数计算
  • Overview 首屏直观判断区块 + Gap 增长解读 + Agreement 估值细节拆解 三区块渲染
  • 🐛 两个 demo_fast NU 输出文案 bug 修复 (主语重复 + headline 重复)
  • pytest 51/52 全通过 (1 个 TVG floor 历史遗留无关失败)
  • demo_fast NU / SOFI / AAPL 三只端到端验证全通过
- ✅ ✨ Session #06 NBIS 误估值修复（用户实测报告暴露）：
  • 🔗 数据对账层 data/reconciliation.py 新建（10 项交叉校验，纯只读）
  • 🎯 models/multiples.py 技术族 peer 桶细粒度化 + AI/Cloud Infrastructure 重路由 + P/E/EV-EBITDA 无意义守卫
  • 🧠 ml_classifier.py 资产轻原型冲突置信度扣减（capex/revenue≥1.0 + 负 FCF → cap 50%）
  • 🐛 valuation/terminal_growth.py 零增长地板 bug 修复（历史遗留测试转绿）
  • pytest 61/61 全通过；demo_fast NBIS / SOFI / AAPL 三只端到端验证全通过
- ✅ ✨ Session #07 NBIS 第二版方法论修复（用户 7 点批评）：
  • 🎯 analysis/model_agreement.py 覆盖率门控 + 质量加权中位数 + 三桶分类 + 低置信降权
  • 🎲 simulation/monte_carlo.py 概率结论 (P(内在>价)/P(高估>30%)/P(归零)) + 4×4 相关抽样 + 负值 floor
  • 📊 data/validator.py + data/models.py 估值可用性评分拆分 + per-share 基数门控
  • 🧭 reporting/verdict_intuition.py 情景一致性修正 + 负价值 floor 文案 + 公允区间标 n/覆盖率
  • ⚖️ valuation/wacc.py 三 beta 透明化 + models/dcf.py WACC 区间估值 + models/reverse_dcf.py 隐含量化 + models/multiples.py AI Cloud 人工 peer 组
  • pytest 61/61 全通过；demo NBIS（Very Strong→Weak，可用性 34/100，P(高估>30%)=97.5%）+ demo_fast SOFI/AAPL 三只端到端验证全通过
- ✅ ✨ Session #10 五项系统优化（覆盖率 / 对账反向校验 / Golden diff / Beta 统一 / REIT+Energy）：
  • 🧱 models/replacement_nav.py 新建（Replacement-cost NAV）+ 分类器动态入桶 → NBIS 覆盖率 **2/3 → 5/6**
  • 🩹 data/reconciliation.py 写侧 apply_overrides（偏差 >25% 自动改用内部推算值）+ OverrideLog 审计 + dashboard 渲染「🩹 对账自动修正」
  • 🧪 tests/golden_report.py + test_golden_report.py + golden/report_fingerprints.json（19 字段指纹 + 5 类 invariant + 逐字段 diff）
  • 🎯 valuation/wacc.py::resolve_effective_beta() 统一 β 出口（市场/风险/WACC 三处共用）
  • 🏢 NBIS/AMT/XOM 合成 fixtures + test_asset_structure_coverage.py（REIT NAV 4/4；Energy 5/5）
  • pytest **78/78 全通过**（61 → 78，+17 用例）；golden 整篮 9 只无缺陷

If modification is required,

Update instead of rebuilding.

---

# 14. Recovery Guide

If another AI Agent continues this project:

Step 1

Read this file completely.

Step 2

Check

Completed Tasks

Step 3

Check

Pending Tasks

Step 4

Check

Current Context

Step 5

Continue ONLY from

Next Immediate Task

DO NOT

- Re-analyze 架构
- Re-design 估值模型
- Re-run 1001只股票数据收集 (csv已存在于 classification\labeling_dump.csv)
- Re-create 确定性分类器规则
- Delete .cache/yahoo_finance 目录 (节省重新拉取时间)

---

# 15. Session Memory

Temporary memory from previous AI Agent.

Current assumptions

```
1. ✅ 用户已经完成了 1000 行 label 列的人工标注（实际训练时验证：1000 行均有 label，无 skipped / unknown）
2. ✅ ml_classifier.py 已经永久切换为 build_training_set_from_csv()，不再走合成数据路径
3. TrainMeta.version/note 在 _train_from_scratch() 末尾 overwrite，保证默认 dataclass 值不会污染新工件
4. demo_fast 16 只股票的预期标签是基准真值（MatureTech/Semiconductor/REIT/Utilities/Bank/Commodity/SaaS/Conglomerate/ConsumerCyclical/Insurance），即使个别有争议也作为 sanity 回归测试基线
5. ✅ 新增数据契约 (ConfidenceAdjustment + BusinessExposure + CompanyProfile 13 字段) 已冻结，后续修改不破坏默认值向后兼容
6. ✅ is_financial_institution 开关是金融机构指标分叉的唯一入口，profile/risk/reporting 三层一致
```

Important discoveries

```
1. CSV L2 重复表头行实际不存在：实测 1001 行(1头+1000数据)、dup_headers=0、empty_label=0
2. 真实数据集的文本特征问题比预期严重：sector/industry 缺失率 83%（Yahoo China 401 区域限制），company_name 是唯一 TF-IDF 文本信号
3. 数值特征的 interest_to_revenue=0 缺失率高达 82%，这是 Bank/REIT/Utilities 的最强判别特征，缺失直接导致这三类的边界混淆
4. AVGO 在 CSV 中本身标签就是 MatureTech（应为 Semiconductor）→ 训练数据标签错误进一步推高 MatureTech↔Semiconductor 的误判率
5. Semiconductor 类别样本最少 (29/1000=2.9%)，类别不平衡叠加标签错误 → 该类召回率明显偏低
6. 结构覆盖规则 (Structural Overrides) 对数值强信号类别有效（Bank int/rev>30%, REIT ebitda%55-90），但对 MatureTech↔Semiconductor 这种高毛利率+高利润率的重叠无能为力
7. LightGBM 在 1000 真实样本上的 train_acc=97.40%，与合成版 (~98%) 相当，但 OOS sanity 准确率低 20 个百分点 → 确认合成版存在过拟合 + 人工合成分布与真实分布偏移
8. ✨ SOFI 报告暴露出的 confidence 黑盒根因：ml_classifier.py#L1282 `if not (sector or industry): confidence = min(confidence, 0.55)` 扣了 11.6pp 但没记录 reason，导致用户看到 ML 66.6% vs 业务 55% 对不上
9. ✨ 银行 FCF 无意义的连锁反应：SOFI TTM FCF=-$9B → (a) Weak/Negative FCF 标签 (b) 4y neg-FCF Medium (c) FCF Yield=-60.17% High → risk 总分 80/100，但三个 flag 全是误报！修复后 score 回到 95/100
10. ✨ 分类器签名变更安全模式：RiskAnalyzer.analyze(..., profile=None) 加新参数带默认值，grep 确认仅 telegram_bot.py 调用且已天然传 profile；pytest 默认 profile=None → getattr 返 False → 行为不变 → 零回归
11. ✨ NBIS 报告暴露「单字段静默失真」：trailing P/E 671（供应商）vs 内部推算 1307（价÷TTM EPS → $0.117 EPS）；市值股数 361.5M vs 最新年度 253.0M（差 +42.9%）；EV/EBITDA 104.27 vs 内部 40.76（+155.8%）——说明供应商字段口径与公司实际口径可大幅偏离，交叉校验是必需的
12. ✨ NBIS 经济结构：capex/revenue≈822%（远超任何 SaaS），TTM EBITDA $1B > 营收 $1B（EBITDA/营收=103%，被 D&A 拉爆）→ 这是典型算力/数据中心重资本建设期图形，与资产轻 SaaS 完全相反的现金流形态
13. ✨ 对账层「只读」是硬约束：一致性检查若允许写回 FinancialData，会把一次错误的推断传播成「修正后的真相」，反而放大风险；正确做法是只标记 + 渲染 + 交下游决策
14. ✨ (Session #08) NBIS 的 DCF 点估值本质是终值单变量函数：TV/EV=499%（显式期 FCF 现值深度为负），按「仅降权一半」放权会让一个近噪音模型主导 headline；分级阈值 1.5/3.0 后 DCF 权重 0.5→0.1，中位锚点自然切换到 EV/Sales
15. ✨ (Session #08) 「mean 营业利润率 -1143%」不是风险信号而是近零营收基期导致的比率失真：营收 < 峰值 10% 的年份必须先剔除，否则 CV 会被一个无意义的均值裹挟
16. ✨ (Session #09) 分桶统计必须满足「适用 = 解算 + 失败」恒等式：JNJ 出现 `适用6·解算5·失败0·合计6`，根因是 `n_total=len(results)` 计入 ReverseDCF 却被 `_EXCLUDED_FROM_MEDIAN` 从 `solved` 里 `continue` 排除且未落桶 → 必须显式设「仅展示(display_only)」第四桶，并让虚假 `1 of 6 failed` 告警按真实 `len(failed)` 触发
17. ✨ (Session #09) 对账文案必须「方向感知」：JNJ 供应商 P/E 26.38x vs 自身 TTM GAAP EPS 隐含 43.94x（−40%）不是「盈利基数极不稳定」而是**调整后(non-GAAP)/正常化 EPS** 与 GAAP 的口径差（几乎所有大盘股都有）；静态文案会把最常见的口径差误判为盈利质量问题
18. ✨ (Session #09) 低 beta 稳定高股息标的（JNJ β=−0.09）会同时触发两处误报：(a) FCF Yield Gap 按其 2.77% 收益率误报 High（正 FCF $19.6B、FCF/净利=1.22 的健康标的）→ 需「正 FCF + 健康转化 + 非高增长」降级守卫；(b) 市场区展示原始 β=−0.09 与 WACC 截断 β=0.30 自相矛盾 → 展示层须复用 `BETA_WINSOR_LO/HI` 常量并标注
19. ✨ (Session #10) 覆盖率是低质量标的的「第一性短板」：NBIS 降权后仍只有 2 个幸存模型，任何降权都无法让结论更可靠；引入**适配资产结构**的新模型（Replacement-cost NAV 把「累计 capex − 累计 D&A」当资产基础锚）比反复调权重有效得多 → 覆盖率 2/3 → 5/6
20. ✨ (Session #10) 「只标记不修正」在污染基数面前不够：对账发现偏差后若下游仍读供应商值，警告形同虚设；正确模型是「只读探测 + 白名单写侧 + 审计链」，且写回必须可渲染（dashboard「🩹 对账自动修正」），绝不静默改写
21. ✨ (Session #10) golden 指纹必须提取**稳定决策信号**而非渲染文本：报告含时间戳/provenance，逐字节 diff 会每次漂移；提取 business_type/分桶计数/agreement/median/β/override/risk 等 19 个语义字段后，diff 才可断言
22. ✨ (Session #10) β 三处不一致（市场区原始 β vs WACC 截断 β vs 风险旗标）的根因是「同一指标多处各自解析」；把解析收敛到单一 `resolve_effective_beta()` 并用 invariant 断言，是消除此类矛盾的通用模式
23. ✨ (Session #11) 「第二条腿」必须与第一条腿经济学**正交**：Replacement NAV 回答「重建资产要多少钱」（资产基础/清算视角），Unit-econ EV/Sales 回答「装好的算力按成熟单价能挣多少」（earnings-power 视角）；NBIS 上二者分叉明显，正交的锚才真正提升证据量，同一逻辑换个名字只是重复计数
24. ✨ (Session #11) 新增一个「居中」的模型会抬高 IQR 上界，从而让原先被离群过滤的极端模型（NBIS DCF TV/EV=404%）重新进入样本 → 一致性指标如实降级（Weak→Very Weak，离散度 247.5%）。这是「证据变化 → 指标诚实响应」，不是回归缺陷；写进 Known Issues 保留，比调参掩盖更符合「分类不确定性 → 估值确定性」的传导原则
25. ✨ (Session #12) 同一判定逻辑若只在 ML 路径实现、确定性规则路径漏实现，会制造「两条分类路径给出不同标签」的隐性缺陷：CRWV 报告头写 MatureTech/SaaS，peer 区写 AI/Cloud Infrastructure。根因是 classifier.py 缺 `ASSET_LIGHT_CONFLICT` 块（ml_classifier.py 有）→ 凡「原型冲突重路由」这类跨层判定，必须在两条路径镜像实现（Round 1）
26. ✨ (Session #12) 报告内部两个口径方向相反（中位判显著高估 vs DCF 基准反判低估）时，**平均会制造伪共识**；正确做法是「命名冲突 + 归因（DCF 终值主导/已被降权或 IQR 剔除）+ 声明不做平均」。同时修复措辞必须与基期严格一致：`(base-price)/base` 是 base-relative，`(base-price)/price` 才是 price-relative，混用会让修复本身产生新的数字错误（Round 2）
27. ✨ (Session #12) 引擎已推导出的量若只写进 free-text note 而不落结构化字段，会制造「note 有值（隐含营收 CAGR ≈26%）但字段显示 N/A」的自相矛盾；正确做法是写入 breakdown 字段 + 携带 `*_source` 来源标记（`normalized_growth_solve`），并在展示层标注 APPROXIMATE（Round 3）
28. ✨ (Session #13) 金融机构的口径分叉（`is_financial_institution`）必须覆盖**主模型 / 情景 / 敏感性 / peer 倍数四处**，漏一处就会撕裂：SOFI 主模型走 Bank RIM（$9.52），情景区却仍走 DCF（$12.61~15.94），两个方向相反的结论并排出现却未命名（Round 2）
29. ✨ (Session #13) 银行模型的 β/ke 必须与全报告共用同一出口（`resolve_effective_beta()` + 同源 Rf/ERP），否则同一个 `ke` 在不同区读到不同值；SOFI 统一后 `ke=15.39%`（β=2.07）到处一致，且越界（银行带 7%~10%）时显式提示（Round 1）
30. ✨ (Session #13) **「封顶到边界值」的守卫必须用闭区间**：分类器 `min(confidence, 0.55)` 使 SOFI 置信度精确落在 0.55，而 peer 倍数守卫写 `conf < 0.55` → 边界漏检，把 55% 置信的银行 peer 倍数当作已验证。改为 `conf <= 0.55` 后 P/E、P/B 才如实标 NOT FULLY VALIDATED（Round 3）
31. ✨ (Session #14) 同一 ADR-023 bug class 有**跨文件**形态：`classification/classifier.py:509` 把 `classification_confidence` 封顶到恰好 0.55，`models/sotp.py:57,70` 却用 `conf < 0.55` 判定低置信 → 任何「同文件」启发式扫描都发现不了；必须做**跨文件**断言（Part C）
32. ✨ (Session #14) 口径判定散落在展示层（内联 `if is_financial_institution`）是「同报告口径矛盾」的结构性根因；把它提升为引擎输出的枚举契约（`valuation/caliber.py`）后，展示层「按契约分支」而非猜测，矛盾点从 N 处收敛到 1 处
33. ✨ (Session #14) 加了「引擎口径 vs 情景口径」的 invariant #6 后，Session #13 需人工通读才能发现的 Round 2 矛盾变成了**自动化断言**——渲染层口径冲突自此可被 CI 捕获
34. ✨ (Session #14) 金融情景只沿 `ke`（β）敏感是不够的；引入 `roe_override`（≈净息差/信用成本）后，情景可沿「折现率 × 经营性 ROE」双驱动（`_FIN_ROE_SHOCK=0.20`），更贴近银行经营现实，且仍复用 Bank RIM 而非 DCF
35. ✨ (Session #14) 「封顶审计」的 Part B 基于数值字面量，无法区分变量（`confidence` 与 `top1_p` 同为 0.55），存在「不同变量同值」误报 → 需白名单 + 理由；精确覆盖由「按变量名 + 常量集」的 Part C 兜底，二者互补
```

Lessons learned

```
1. TrainMeta 的 dataclass 默认值 vs 实际训练版本号：默认写死 "2.0-synthetic" 会误导即使切换了真实数据后加载出来的 meta，如果忘记在构造时覆盖就会把合成版版本号写到真实工件里 → 最佳实践：构造 TrainMeta 后立即显式 overwrite version/note
2. PowerShell "重复表头行" 恐慌：实际 1001 行 CSV 经 csv.DictReader 解析无 dup_headers → 不要相信肉眼看第一页数据的印象，必须写脚本跑一遍 dup_headers + empty_label 统计
3. Sanity 准确率 vs 训练集准确率差距 ≥ 20% 时，先查 3 件事：(a) 训练集标签错误 (b) 类别分布极度不平衡 (c) 关键特征在训练集中系统性缺失
4. demo_fast / test_demo 命令输出的 Markdown 报告是验证分类结果最可靠的回归测试：不仅看业务类型，还要看 Top2 和候选区分度 ratio（Top1/Top2 < 2x 视为边界模糊应人工复核）
5. ✨ 置信度扣减必须留痕：任何 confidence 非单调变换（min/max/cap/clamp）都必须记录 step_name + delta + reason，否则用户会怀疑模型「偷偷改数」失去信任
6. ✨ 指标口径分叉最佳分层：不要在底层 FinancialStatement 解析层硬改（会污染所有上层），而是在 Profile（定性描述）/Risk（规则判断）/Reporting（渲染文案）三层分别读取 is_financial_institution 开关做适配，非金融公司完全零影响
7. ✨ Hybrid 不要扩枚举：BusinessType 枚举值和路由表/模型权重强耦合，扩 FinTech 第 12 类成本极高。改「概率分布聚合 + 多轴暴露度」是增量兼容方案，无需重训模型即可识别边界案例
8. ✨ Windows PowerShell stderr 会把 WARNING 级日志包装成 RemoteException（视觉红色），实际 exit code=0，不要误判为 Python 报错；看 exit code + stdout 才是王道
9. ✨ 分类置信度必须看「标签 vs 财务原型」是否矛盾，而不只是「数据是否缺失」：NBIS ML 92% SaaS 但 capex/revenue=822% + 负 FCF，原型冲突比数据缺失更严重；新增维度化扣减（Asset-light prototype conflict）
10. ✨ Peer 倍数的可比性 = 相同经济结构（资产轻重 / 资本强度 / 现金流形态），不是相同「行业标签」。粗粒度行业桶（Technology）会把软件、半导体、算力基础设施错误混同；应按经济结构细拆并加结构守卫（重资本→AI/Cloud，净利极薄→P/E 无意义）
11. ✨ 对账层用「比率语义」而非「金额对金额」更易读：EBITDA/营收 ≤ 100% 的判断比 "$1B vs $1B +2.6%" 直观得多；重资产公司的 D&A 可以把 EBITDA 推到超过营收，这时 EV/EBITDA 根本不可比
12. ✨ (Session #09) 用一个「与上轮完全对立画像」的标的做回归最有价值：NBIS（重资本高增长、β 高）迭代出来的守卫，在 JNJ（成熟高股息、β=−0.09）上暴露出「阈值启发式对另一类标的误报」——凡按固定阈值（如 FCF 收益率 4%、β 区间）打风险/展示的规则，都要配一个「健康反向守卫」，否则会系统性惩罚稳定型标的
13. ✨ (Session #09) 展示层与计算层必须共用同一常量：WACC 用 winsorize 截断 β 计算，市场区却展示原始 β，用户会读到两个矛盾的 β；把 `BETA_WINSOR_LO/HI` 提为模块常量并让展示层引用 + 标注，是消除「同一指标两处不一致」的最小改动模式
14. ✨ (Session #10) 覆盖率不足时，「引入适配的模型族」优先于「调整已有模型权重」：权重只改变谁主导结论，不改变证据数量；Replacement NAV 让资产基础成为独立证据源
15. ✨ (Session #10) 数据修正必须「可渲染 + 可审计」：写侧 override 若不留 `OverrideRecord` 且不在报告展示，用户无从知晓估值基数已被改写 → 白名单（`_OVERRIDE_FIELDS`）+ 审计链（`OverrideLog`）+ 报告渲染三件套是底线
16. ✨ (Session #10) 「上一轮报告 → 缺陷清单」的工程化路径是「提取稳定语义指纹 + 声明式 invariant + 基线 diff」，而不是把渲染文本喂给 diff；invariant 检查（覆盖恒等式/封顶/β 一致/override 生效）可直接暴露新引入的自相矛盾
17. ✨ (Session #11) 缺乏明细字段时（无 GPU 稼动率/ARPU），诚实做法是「派生代理 + 固定 APPROXIMATE」而非硬凑一个 SOLVED；必须在 notes 明确标注「派生代理 / 方向性参考」，否则会制造虚假精度——这与用户「反对伪精确」的偏好一致
18. ✨ (Session #12) 递归自我改进要选「与上一轮不同画像」的标的才能暴露新缺陷：NBIS/JNJ 迭代出的是覆盖率/风险守卫，换到 CRWV（neocloud 建设期、重债务、深度负 FCF）才暴露「规则分类路径漏实现原型重路由」「结论口径方向冲突未命名」「派生量未结构化」三类渲染/契约层缺陷——每换一个画像，缺陷类型就换一层
19. ✨ (Session #12) 一个修复本身会引入新缺陷（Round 2 修 caveat 时误用 base-relative 当 price-relative）——所以递归的每一轮都必须「重跑 + 重读产出」，不能假设「改完即对」；修完立刻验证是本项目硬纪律（写完必须自己跑）
20. ✨ (Session #13) 「口径分叉」是一个横切关注点，不能在某一层实现一次就算完成：`is_financial_institution` 必须在 profile / risk / reporting / **scenario / sensitivity** 全覆盖，否则会出现「主模型说 A、情景说 B」的并排矛盾。最好把口径当成**输出契约字段**（`discount_label="ke"`）显式传给展示层，让渲染端按契约分支而非猜测
21. ✨ (Session #13) 阈值守卫要警惕「上游封顶 = 下游边界」的组合：只要上游用 `min/max` 把值钳到常量，下游用严格比较判定该常量就必然漏检。通用做法是「阈值提为常量 + 判定端用闭区间 + 展示端复用同常量」，并在递归中审计所有 `min/max` 封顶点
22. ✨ (Session #14) 「把口径当作输出契约字段」是消除渲染层矛盾的通用模式：引擎输出枚举（`MetricMeaning`/`DiscountCaliber`），展示层只按契约分支，禁止在渲染层猜口径；契约同时进指纹 + invariant，使「主模型/情景口径不一致」可被自动断言
23. ✨ (Session #14) 封顶审计必须**跨文件**：上游封顶与下游判定往往不在同一模块（`classifier` 封顶 → `sotp` 判定），只做「同文件」扫描必然漏检。做法是「按被封顶的变量名 + 已知封顶常量集」扫描全代码库，命中即失败
24. ✨ (Session #14) 数据驱动优于调阈值：SOFI hybrid/SOTP 未触发（tech_p=5.5% < 8%）根因是 sector/industry 缺失压低 tech 权重，属**特征问题**；正确动作是把阈值提为具名常量并**锁定**（加边界测试），而非下调阈值——下调会扰动 golden 基线且掩盖根因
25. ✨ (Session #14) 「不同变量同值」会让基于字面量的静态扫描产生误报（`confidence` 与 `top1_p` 同为 0.55）；检测器要分层：宽召回（字面量配对，命中即人工审阅 + 白名单）＋ 高精确（按变量名 + 常量集），二者互补而非互相替代
```

Useful references

```
- ml_classifier.py lines 771-782: TrainMeta 构造 + 末尾 overwrite version/note 锚点位置
- ml_classifier.py lines 705: build_training_set_from_csv() 已永久替换合成数据路径（无需再改）
- classification/_run_train_and_verify.py: 训练 + 打印 meta + 15 只 sanity 预测的黄金回归脚本
- main.py demo_fast 命令: 跳过蒙特卡洛的端到端估值演示，分类结果在 "业务类型" + "🧠 ML 概率分布" 两节
- Known Issues 表格 (AGENT.md #11)：6 个质量问题 + 优先级 + 当前解决进度记录
- ✨ data/models.py lines 165-240: ConfidenceAdjustment + BusinessExposure dataclass + CompanyProfile 新字段锚点（SOFI 修复的底层契约）
- ✨ classification/ml_classifier.py lines 1073-1330: _build_exposures() + _detect_hybrid() + classify() 重构（置信度拆解 + Hybrid 判定）
- ✨ classification/classifier.py lines 331-471: _characterize_profile() 金融机构 7 项适配（现金流/杠杆/资本密集度/REIT FFO）
- ✨ reporting/dashboard.py lines 132-299: _business_section() Hybrid/置信度拆解/Exposures + _market_section() 金融机构 caveat
- ✨ analysis/risk.py lines 43-329: analyze() + _leverage() + _margin_risk() + _forecast_risk() 四个函数的机构敏感适配
- ✨ data/reconciliation.py: reconcile(data) 10 项交叉校验 + ReconciliationCheck.render(fmt)/ReconciliationReport.to_lines(fmt)（内部 fmt(value, unit) 双参签名）
- ✨ models/multiples.py: SECTOR_PEER_MULTIPLES 细粒度桶 + _BT_TO_SECTOR 映射 + _resolve_peer_bucket() + _compute_infra_override()（_COMPUTE_INFRA_CAPEX_RATIO=1.0 阈值）+ applicability_check() 的 P/E(>100x)/EV-EBITDA(EBITDA>90%营收) 守卫
- ✨ classification/ml_classifier.py: ASSET_LIGHT_CONFLICT_CAPEX_RATIO + ASSET_LIGHT_TYPES + "Asset-light prototype conflict" 扣减分支（is_fintech_hybrid 块之后）
- ✨ valuation/terminal_growth.py: 0≤base<1.5% 分支（抬高到 BASE_FLOOR 而非 DECLINING_BASE）
- ✨ reporting/dashboard.py: _fmt_recon(v, unit) + _data_section() 「🔗 数据对账」区块
- NBIS 复盘基准：ML Top-1 SaaS 92% → 缺失封顶 -37pp → 原型冲突 -5pp → Final 50%；P/E 671（供应商）vs 1307（内部推算）；股数 361.5M vs 253.0M；EBITDA/营收 103%
- ✨ tests/golden_report.py: `BASKET`(9 只) + `run_pipeline()` + `build_fingerprint()`（19 字段）+ `check_invariants()`（5 类缺陷）+ `render_report()`
- ✨ tests/test_golden_report.py + tests/golden/report_fingerprints.json: golden diff 回归（`UPDATE_GOLDEN=1` 刷新基线）
- ✨ models/replacement_nav.py: `ReplacementNAVModel`（`MIN_CAPEX_RATIO=0.30` / `DEFAULT_REPLACEMENT_FACTOR=1.15` / 5 档敏感性 `_SENSITIVITY_FACTORS`）
- ✨ data/reconciliation.py: `apply_overrides()` + `OverrideRecord`/`OverrideLog` + `_OVERRIDE_FIELDS` + `_OVERRIDE_TOLERANCE=0.25` + 股数守卫
- ✨ valuation/wacc.py: `resolve_effective_beta()`（β 单一出口，`origin ∈ wacc_breakdown / provider / fallback`）+ `BETA_WINSOR_LO/HI`
- ✨ classification/classifier.py: `_is_replacement_nav_candidate()`（capex/revenue≥0.30 + 负 FCF/亏损 + net_ppe>0，排除金融/REIT）
- Session #10 回归证据：`_recursion_reg_NBIS.txt`（5/6 解算 + Replacement NAV $11.13）/ `_recursion_reg_PLD.txt`（对账自动修正渲染）/ `_recursion_reg_AMT.txt` / `_recursion_reg_XOM.txt`
- ✨ models/unit_economics.py: `UnitEconomicsSalesModel`（`MIN_CAPEX_RATIO=0.50` / `BENCHMARK_REVENUE_YIELD=0.35` / `MATURE_EV_SALES=4.0` / `RAMP_YEARS=3.0` + `_SENSITIVITY_YIELDS=(0.25,0.35,0.50)` / `_SENSITIVITY_RAMP_YEARS=(2.0,3.0,5.0)`；固定返回 `SolverStatus.APPROXIMATE`）
- ✨ classification/classifier.py: `_is_unit_economics_candidate()`（capex/revenue≥0.50 + 负 FCF/亏损 + Σcapex−ΣD&A>0，排除金融/REIT）
- ✨ tests/test_unit_economics.py: 12 测试（路由 4 / 解算 3 / 覆盖率提升 2 / 敏感性方向 2 / 适用性守卫 1）
- ✨ Session #11 回归证据：`_recursion_reg_NBIS.txt`（模型分桶「适用 7 · 解算 6 · 失败 1 · 合计 10」；`EV/Sales (Unit Econ): $27.02`；隐含当期 EV/Sales ≈ 36.7x；资产基础产品率 2.48% vs 成熟基准 35%；一致性 Very Weak / 门控 CV 130.4%）
- ✨ _recursion_run.py: 递归驱动（`run_pipeline` → `render_report` → `_recursion_<ticker>_<label>.txt` + fingerprint + `check_invariants`）
- ✨ Session #12 回归证据：`_recursion_crwv_round0..3.txt`（Round 1 头行 `→ **估值原型重路由: AI/Cloud Infrastructure**`；Round 2 `⚠️ 口径冲突：…DCF 基准情景 $138.57 高于当前价 85%`；Round 3 `隐含营收 CAGR: 26.4% _(成熟稳态经济推导，APPROXIMATE)_` + `比历史水平低 429.9 个百分点`；4 轮 DEFECTS 均为空）
- ✨ classification/classifier.py: `ASSET_LIGHT_CONFLICT_CAPEX_RATIO` / `ASSET_LIGHT_TYPES` / ISSUE #1b 块 + `effective_business_type`/`business_type_conflict_note`
- ✨ models/reverse_dcf.py: `_normalized_growth_solve()` + `breakdown["implied_revenue_cagr"]` / `implied_revenue_cagr_source`（Round 3 落字段点）
- ✨ reporting/verdict_intuition.py: `build_valuation_verdict()` 的「Median-vs-scenario SIGN conflict」caveat（`gap_vs_base` / `gap_vs_price` 双基期）
- ✨ analysis/scenario.py: `ScenarioAnalyzer.run_all()` 金融分叉 + `_run_financial_scenarios()`（`_FIN_BETA_STEP=0.30`；Bank RIM 沿 ke）+ `ScenarioValuation.assumptions["discount_label"|"cost_of_equity"]`
- ✨ models/bank.py: `_resolve_discount_inputs()`（β 经 `resolve_effective_beta()`）+ `_BANK_KE_BAND=(0.070, 0.100)`（银行 ke 越界提示锚点）
- ✨ models/multiples.py: `_PEER_MULTIPLE_CONF_FLOOR=0.55`（peer 倍数未验证下界常量，两处 `<=` 判定）
- ✨ reporting/dashboard.py: `_scenario_section()` 的 `discount_label` 分支 + `_sensitivity_section(profile)` 金融机构守卫
- ✨ Session #13 回归证据：`_recursion_sofi_round1/2/3.txt`（Round 1 `Bank RIM=… ke=15.39%`；Round 2 情景 `9.26→9.52→9.79`（6% SV）+ 敏感性金融文案；Round 3 `Peer multiple NOT FULLY VALIDATED … 55%` + 质量因子 0.67）+ 跨标的 `_recursion_jpm_round3.txt`（情景 Bank RIM $135.28/$139.22/$143.36）
```

---

# 16. Validation Checklist

Before marking a task as completed:

- [x] Code Compiles (无语法错误，通过 .venv 解释器运行)
- [x] Tests Pass (pytest 运行前未被破坏)
- [x] Documentation Updated (AGENT.md, TODO.md, ROADMAP.md 等新建)
- [x] README Updated (新建)
- [x] AGENT.md Updated (本文件)
- [x] No duplicate logic (每个模块职责清晰)
- [x] No TODO left without reason (label 列是人工任务，非代码TODO)

---

# 17. AI Agent Rules

Every AI Agent MUST

✅ Read AGENT.md first

✅ Continue existing work

✅ Never restart completed work

✅ Update AGENT.md before ending

✅ Record every important decision

✅ Record every new file

✅ Record every modified file

✅ Record blockers

✅ Record next task

Failure to update AGENT.md means the task is NOT complete.

---

# 18. Change Log

## 2026-11-12 (Session #15 — UPST 递归自我改进 3 轮: 分类子串误匹配 → 金融 EV/Sales 剔除 → 渲染层口径泄漏)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以 **UPST（Upstart Holdings，消费信贷 FinTech）** 为标的执行「上一轮产出（报告 + 指纹）作为下一轮起点」的递归工作流，round1 → round2 → round3；每轮 `python _recursion_run.py UPST roundN --real` + 全量 `pytest`。统一原则（ADR-019/022/024）：**同页矛盾要命名不要掩盖；口径 = 引擎输出契约，渲染层禁止猜口径**。

Completed

- ✅ **Round 1（分类子串误匹配，round0 基线最强缺陷）**：工业关键词 `"ups"`（UPS 快递）子串误匹配 ticker `upst` → `Structural FORCE->Industrial` 覆盖 FinTech → 走 DCF/EV-EBITDA/FCF-Yield（对借贷型无意义），DCF=$0.00、ReverseDCF 无解、情景三档全 $0.00。修复：`ml_classifier.py` 新增边界感知 `keyword_hit()` → UPST 分类 FinTech（p=99.1%），路由 `Bank DDM/Bank RIM/P/E/P/B`
- ✅ **Round 2（金融 EV/Sales 剔除）**：round1 同页矛盾——市场区打印「EV N/M（金融机构不适用）」却仍用 `EV/Sales` 作锚（$42.16，区间唯一离群值）。修复：`classifier.py::_model_applicability` 金融分叉剔除 `EV/Sales` → 一致性 Very Weak → **Moderate**，离散度 316% → **36.2%**
- ✅ **Round 3（渲染层口径泄漏，违 ADR-022/024）**：① `verdict_intuition.py` 公允区间附注按 `build_caliber_contract` 分支（金融标的给「P/B、P/E、RIM 复核」）；② `dashboard.py::_risk_section` 按 `DiscountCaliber.COST_OF_EQUITY` 把 `WACC Risk` 重标「Cost of Equity Risk」；③ 市场区 β 附注「WACC 统一采用截断值」→ 中性「折现率」

Created

- `_recursion_upst_round0.txt` / `_recursion_upst_round1.txt` / `_recursion_upst_round2.txt` / `_recursion_upst_round3.txt`（4 轮产出，round0 为修复前基线）

Modified

- `classification/ml_classifier.py` / `classification/classifier.py` / `reporting/verdict_intuition.py` / `reporting/dashboard.py`
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md` / `TODO.md`

Notes

- 验证：pytest **106/106 全通过**；UPST round1/2/3 `check_invariants()` DEFECTS 均为 `[]`；非金融回归确认 EV/Sales 未误伤（AAPL/XOM 保留，REIT/Bank 不含）

## 2026-11-03 (Session #14 — 口径契约化 + 封顶审计系统化 + 渲染层口径冲突 invariant + 金融运营情景)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：落实 Session #13 收尾提出的 5 项优化（口径契约 / M-15 封顶审计 / M-12 invariant / M-16 数据驱动 / 金融情景深化）。核心思想：**口径 = 引擎输出的枚举契约，展示层只按契约分支，禁止猜口径**。每步 `python -m pytest -q` 全量回归。

Completed

- ✅ **优化 ①（口径即契约，ADR-024）**：新建 `valuation/caliber.py`（`MetricMeaning` / `DiscountCaliber` / `CaliberContract` / `build_caliber_contract`）；`reporting/dashboard.py` 删除内联 `is_fin`/`is_reit` 猜口径，改为消费契约（EV/净债务/EV-EBITDA/FCF 的 N/M 与附注、敏感性适用性全部来自契约）
- ✅ **优化 ②（M-15 封顶审计，ADR-025）**：新建 `tests/test_cap_boundary_guard.py` 三层审计；**跨文件 Part C** 捕获并修复 `models/sotp.py` 的 `conf < 0.55`（上游 `classifier.py:509` 封顶到恰好 0.55）→ `conf <= 0.55`
- ✅ **优化 ③（M-12 渲染层口径冲突 invariant）**：`tests/golden_report.py::check_invariants()` 新增 invariant #6（情景 `discount_label` 必须 == 引擎口径）；golden 指纹新增 `caliber`/`scenario_calibers`（19 → 21 字段）
- ✅ **优化 ④（M-16 数据驱动）**：hybrid 阈值提为具名常量 `HYBRID_FIN_TO_TECH_FLOOR=0.08`（**锁定而非下调**）+ 新建 `tests/test_hybrid_threshold_lock.py` 边界断言
- ✅ **优化 ⑤（金融情景深化）**：`models/bank.py` 新增 `roe_override` + `roe_source`；`analysis/scenario.py` 新增 `_FIN_ROE_SHOCK=0.20` → 金融情景为 **ke + 经营性 ROE 双驱动**（驱动文案「折现率 ke ± + 经营性 ROE ±」），仍复用 Bank RIM 而非 DCF

Created

- `valuation/caliber.py`（口径契约唯一真相来源）
- `tests/test_cap_boundary_guard.py` / `tests/test_hybrid_threshold_lock.py`
- `CHANGELOG.md`（Session #14 条目）

Modified

- `reporting/dashboard.py` / `analysis/scenario.py` / `models/bank.py` / `models/sotp.py` / `classification/ml_classifier.py` / `tests/golden_report.py`
- `tests/golden/report_fingerprints.json`（`UPDATE_GOLDEN=1` 重生成；仅新增 2 字段，已审阅）

Notes

- 验证：pytest **95/95 passed**（90 → 95，新增 3 个测试文件）；SOFI / JPM round3 `check_invariants()` `DEFECTS: []`；`caliber='ke'` == `scenario_calibers=['ke']`
- SOFI 金融情景驱动证据：`情景驱动：折现率 ke ↑（β+0.30） + 经营性 ROE ↓（6.07%→4.85%）`（`_recursion_sofi_round3.txt:94`）
- 决策：新增 Decision 022（口径契约）/ 023（封顶审计）；DECISIONS.md（ADR-024/025）已同步；TODO.md M-12/M-15 标 DONE、M-16 标 PARTIAL
- 遗留（By Design）：封顶审计 Part B 基于字面量存在「不同变量同值」误报，需白名单 + 理由；精确覆盖由 Part C 兜底（见 Known Issues #14-4）

---

## 2026-11-03 (Session #13 — SOFI 递归自我改进 3 轮: 银行 β/ke 口径统一 + 金融情景口径 + peer 置信度边界)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以 **SOFI（SoFi Technologies，银行 / 金融科技）** 为标的，执行用户定义的递归工作流——**上一轮产出（报告 + 指纹）作为下一轮起点**，识别缺陷 → 修代码 → 重跑验证，共 3 轮。每轮跑 `_recursion_run.py SOFI roundN --real` 与全量 pytest。

Completed

- ✅ **Round 1（银行 β/ke 口径统一）**：Bank DDM/RIM 未收敛到单一 β 出口，可能与市场区/WACC 读不同 β 或默认 ke。修复：`models/bank.py` 统一经 `resolve_effective_beta()` 取 β（winsorized [0.30, 2.50]）+ 与 WACC/情景同源 Rf/ERP + 新增 `_BANK_KE_BAND=(7%,10%)` 越界提示。SOFI `ke=15.39%`（β=2.07）与全报告一致
- ✅ **Round 2（金融情景口径）**：报告主模型已走 Bank RIM（$9.52），但情景区仍走 DCF（WACC 15.1%，$12.61~15.94）→ **口径相反却未命名**。修复：`analysis/scenario.py` 新增 `_run_financial_scenarios()`（Bank RIM 沿 ke 变动，`_FIN_BETA_STEP=0.30`）→ $9.26 / $9.52 / $9.79（跨度 22% → **6% SV**）；`reporting/dashboard.py` 情景区按 `discount_label` 渲染 ke 口径 + 敏感性区替换为「不适用 DCF 敏感性矩阵」文案
- ✅ **Round 3（peer 置信度边界）**：SOFI 置信度被截断到**恰好 0.55**，守卫用严格 `conf < 0.55` → P/E、P/B 漏标 `NOT FULLY VALIDATED`。修复：`models/multiples.py` 提取 `_PEER_MULTIPLE_CONF_FLOOR=0.55` + 改 `<=` → P/E、P/B 均标警告；质量因子 1.00 → **0.67**、一致性 Moderate → **Weak**（门控 CV 24.5% → 36.7%，真实信号）

Created

- 回归证据：`_recursion_sofi_round1.txt` / `round2` / `round3` + 跨标的 `_recursion_jpm_round3.txt`
- `CHANGELOG.md`（Session #13 条目）

Modified

- `models/bank.py` / `analysis/scenario.py` / `reporting/dashboard.py` / `models/multiples.py`
- `tests/golden/report_fingerprints.json`（`UPDATE_GOLDEN=1` 重生成；JPM Bank RIM 有意漂移）

Notes

- SOFI 关键结果：业务类型 Bank（置信度 55%，sector/industry 缺失封顶）；模型分桶「适用 3 · 解算 3 · 失败 0 · 合计 4」（Bank DDM 无股息→不适用）；中位估值 $9.52；情景 9.26/9.52/9.79（Bank RIM, ke 口径）；质量因子 0.67、一致性 Weak、门控 CV 36.7%；对账自动修正滚动 P/E（32.21 → 24.37）。
- pytest **90/90 passed**；SOFI 3 轮 + JPM round3 `check_invariants()` DEFECTS 均为空。
- 决策：新增 Decision 020（金融情景必须走适配主模型，禁 DCF）/ 021（封顶到边界值用 `<=` 守卫）；CHANGELOG.md 与 DECISIONS.md（ADR-022/023）已同步。
- 遗留（数据驱动，非缺陷）：SOFI hybrid 标签/SOTP 未触发（tech_p=5.5% < Case B 8% 阈值），待特征补全后复评（见 Known Issues #13-4）。

---

## 2026-11-03 (Session #12 — CRWV 递归自我改进 3 轮: 原型重路由 + 口径冲突命名 + 派生态结构化)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以 **CRWV（CoreWeave，AI/Cloud neocloud 建设期）** 为新画像标的，严格执行用户定义的递归工作流——**上一轮产出（报告+指纹）作为下一轮起点**，识别缺陷 → 修代码 → 重跑验证，共 3 轮。每轮后跑 `_recursion_run.py` 与 pytest。

Completed

- ✅ **Round 1（分类原型重路由）**：规则分类路径（离线/golden 走这条）缺「资产轻原型冲突」判定 → 报告头 `MatureTech / SaaS` 与 peer 区 `AI/Cloud Infrastructure` **自相矛盾**。修复：`classification/classifier.py` 新增 `ASSET_LIGHT_CONFLICT_CAPEX_RATIO=1.0` / `ASSET_LIGHT_TYPES` / ISSUE #1b 块（对齐 `ml_classifier.py`）→ `effective_business_type="AI/Cloud Infrastructure"`；`reporting/dashboard.py` hybrid 分支渲染 `→ **估值原型重路由: …**`
- ✅ **Round 2（结论口径冲突命名）**：一句话结论内部矛盾——中位口径判「显著高估（$6.87）」但 DCF 基准情景 $138.57 **反判低估**，报告未命名。修复：`reporting/verdict_intuition.py::build_valuation_verdict()` 新增「Median-vs-scenario SIGN conflict」caveat（**命名 + 归因 + 不做平均**）；并修正本轮自持的基期口径错误（`gap_vs_base` vs `gap_vs_price`）
- ✅ **Round 3（派生量结构化）**：`ReverseDCF` 成熟稳态推导的隐含营收 CAGR ≈26% 仅存于 free-text note，结构化字段却显示 `N/A`。修复：`models/reverse_dcf.py` 写入 `breakdown["implied_revenue_cagr"]` + `implied_revenue_cagr_source="normalized_growth_solve"`；`analysis/expectation.py` 透传 source 字段；`reporting/dashboard.py` 标注 APPROXIMATE + 修正 `_gap_section` 方向文案 bug（原恒输出「高出」）
- ✅ **新增 CRWV 合成 fixture**：`data/providers.py` `SYNTHETIC_DATA["CRWV"]`（price 75 / shares 480M / capex TTM 7.6B / FCF TTM −8.8B / debt 9B / β 2.60）

Created

- `_recursion_run.py`（递归驱动脚本）
- 回归证据：`_recursion_crwv_round0.txt` / `round1` / `round2` / `round3`

Modified

- `data/providers.py` / `classification/classifier.py` / `reporting/dashboard.py` / `reporting/verdict_intuition.py` / `models/reverse_dcf.py` / `analysis/expectation.py`

Notes

- CRWV 关键结果：模型分桶「适用 7 · 解算 6 · 失败 1 · 合计 10」；中位估值 $6.87；`Replacement NAV $6.87` + `EV/Sales (Unit Econ) $5.89`（两条腿均适用）；一致性 Very Weak（离散度 191.8%，DCF TV/EV=292.9% 已降权/IQR 剔除）；`check_invariants()` 4 轮 DEFECTS 均为空。
- pytest **90/90 passed**；declared invariants 未覆盖渲染层口径矛盾（故需人工通读报告），已作为后续可选加固方向（见 Known Issues / Next Immediate Task）。
- 决策：新增 Decision 019（矛盾要命名不要掩盖 / 口径要同基不要混用 / 派生量要结构化不要埋在注释）；CHANGELOG.md 与 DECISIONS.md（ADR-021）已同步。

---

## 2026-11-03 (Session #11 — 覆盖率第二条腿: EV/Sales + 单位经济学模型族)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：延续 Session #10 的「覆盖率不足应引入适配模型族，而非降权规避」原则。上轮 Replacement NAV 补齐了**资产基础锚**（第一条腿），本轮补上经济含义正交的 **earnings-power 锚**（第二条腿）。全部改动后跑 pytest，最终全量 **90/90**（78 → 90，+12 用例）并刷新 golden 基线。

Completed

- ✅ **重资本高增长/亏损期标的引入 EV/Sales + 单位经济学模型族**
  - 新建 `models/unit_economics.py::UnitEconomicsSalesModel`：`deployed_capital = Σcapex − ΣD&A`；`capacity_revenue = max(TTM营收, deployed_capital × BENCHMARK_REVENUE_YIELD)`；`EV = capacity_revenue × MATURE_EV_SALES × ramp_discount`；`utilisation_gap = clamp(1 − current_yield/benchmark_yield, 0, 1)`；`ramp_discount = (1+WACC)^−(RAMP_YEARS × utilisation_gap)`
  - 参数：`MIN_CAPEX_RATIO=0.50` / `BENCHMARK_REVENUE_YIELD=0.35` / `MATURE_EV_SALES=4.0` / `RAMP_YEARS=3.0` + 敏感性（yield 0.25/0.35/0.50 × ramp 2/3/5）
  - `config.py` 新增 `ModelName.UNIT_ECON_SALES`；`models/router.py` / `models/__init__.py` 注册
  - `classification/classifier.py`：`ALL_MODELS` 扩列 + `_model_applicability()` 动态入桶 + 新增 `_is_unit_economics_candidate()`（capex/revenue≥0.50 + 负 FCF/亏损 + net_ppe>0，排除金融/REIT）
  - **结果：NBIS 覆盖率 5/6 → 6/7**（`EV/Sales (Unit Econ): $27.02`；隐含当期 EV/Sales ≈ 36.7x；资产基础产品率 2.48% vs 成熟基准 35% → 产能利用率缺口 93% → 需 2.8 年爬坡）
- ✅ **诚实性硬约束**：数据层无 GPU 稼动率/ARPU 明细字段，故以「营收/净PP&E 相对成熟基准」为派生代理，模型**固定返回 `SolverStatus.APPROXIMATE`（永不 SOLVED）** 并在 notes 标注「派生代理 / 方向性参考」
- ✅ **golden 基线刷新**：`UPDATE_GOLDEN=1` 重生成 `tests/golden/report_fingerprints.json`（NBIS 新基线 `n_total=10` / `n_applicable=7` / `n_solved=6` / `agreement_level="Very Weak"` / `median_value=12.76` / `median_value_weighted=11.13`）

Created

- `models/unit_economics.py`
- `tests/test_unit_economics.py`（12 测试：路由 4 / 解算 3 / 覆盖率提升 2 / 敏感性方向 2 / 适用性守卫 1）
- 回归证据：`_recursion_reg_NBIS.txt`（重生成；模型分桶「适用 7 · 解算 6 · 失败 1 · 合计 10」）

Modified

- `config.py` / `models/router.py` / `models/__init__.py` / `classification/classifier.py` / `tests/golden/report_fingerprints.json`

Notes

- **IQR 副效应（真实信号，非缺陷）**：新增居中模型 $27.02 抬高 IQR 上界 → 原被离群过滤的 DCF（TV/EV=404%）重新进入样本 → 离散度 247.5%、一致性如实由 Weak 降为 **Very Weak**、门控 CV 130.4%。这是「证据变化 → 指标诚实响应」，已记入 Known Issues，**不做调参规避**（Decision 018）。
- pytest **90/90 passed**（78 → 90，+12 用例）；golden 整篮 9 只 defects 为空。CHANGELOG.md 已同步 Session #11 条目。

---

## 2026-11-03 (Session #10 — 五项系统优化: 覆盖率锚 + 对账反向校验 + Golden diff + Beta 统一 + REIT/Energy)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：承接 Session #08（NBIS）/ #09（JNJ）递归自我改进的沉淀，针对用户列出的 5 项系统性短板一次性落地。每项改动后跑 pytest；最终全量 **78/78** 并产出 golden 整篮 9 只回归。

Completed

- ✅ **优化 ① 覆盖率瓶颈（最大短板）：Replacement-cost NAV 模型族**
  - 新建 `models/replacement_nav.py`：`ReplacementNAVModel`，`equity = book_equity + net_ppe×(factor−1)`（net_ppe = Σcapex − ΣD&A，缺 book_equity 时回退 `replacement_ppe − net_debt`）；factor 默认 1.15 + 5 档敏感性
  - `config.py` 新增 `ModelName.REPLACEMENT_NAV`；`models/router.py` / `models/__init__.py` 注册
  - `classification/classifier.py`：`ALL_MODELS` 扩列 + `_model_applicability()` 末尾动态追加 + 新增 `_is_replacement_nav_candidate()`（重资本 capex/revenue≥0.30 + 负 FCF/亏损 + net_ppe>0，排除金融/REIT）
  - **结果：NBIS 覆盖率 2/3 → 5/6**（Replacement NAV 估值 $11.13；不再靠降权规避）
- ✅ **优化 ② 对账层反向校验供应商**
  - `data/reconciliation.py` 新增写侧 `apply_overrides()` + `OverrideRecord`/`OverrideLog`（审计链）+ `_OVERRIDE_FIELDS` 白名单 + `_OVERRIDE_TOLERANCE=0.25` + 股数守卫（恒等式自洽→仅标注 / 破坏→按市值/价格反推）
  - `data/models.py` 新增 `reconciliation_overrides` 字段；`data/validator.py::_check_reconciliation()` 接入
  - `reporting/dashboard.py::_data_section()` 渲染「🩹 对账自动修正（偏差 > 25% 时改用内部推算值）」（PLD 实测：EV $179B→$302B、P/E 33.00→90.65 自动修正）
- ✅ **优化 ③ 递归自改进工程化：golden report diff**
  - 新建 `tests/golden_report.py`（`BASKET` 9 只 + `run_pipeline` + `build_fingerprint` 19 字段 + `check_invariants` 5 类缺陷 + `render_report`）
  - 新建 `tests/test_golden_report.py`（3 测试）+ `tests/golden/report_fingerprints.json` 基线（`UPDATE_GOLDEN=1` 刷新）
  - **结果：golden 整篮 9 只 defects 为空**（无自相矛盾）
- ✅ **优化 ④ Beta 全链路统一**
  - `valuation/wacc.py::resolve_effective_beta()` 成为单一 β 出口（wacc_breakdown → provider(winsorized) → fallback，返回带 `origin` 的可审计对象）；市场区 / WACC / 风险旗标三处共用；golden invariant 断言 β 一致
- ✅ **优化 ⑤ 补 REIT（AMT）与 Energy（XOM）覆盖**
  - `data/providers.py` 新增 NBIS/AMT/XOM 合成 fixtures；`tests/conftest.py` 新增对应 fixtures
  - 新建 `tests/test_asset_structure_coverage.py`（8 测试）：AMT `is_reit=True`（REIT NAV 4/4）、XOM `business_type=="Energy"`（5/5 Strong）、NBIS `n_solved≥3` + `Replacement NAV` 入 applicable

Created

- `models/replacement_nav.py`、`tests/test_reconciliation_override.py`（6 测试）、`tests/test_asset_structure_coverage.py`（8 测试）、`tests/golden_report.py`、`tests/test_golden_report.py`（3 测试）、`tests/golden/report_fingerprints.json`
- 回归证据：`_recursion_reg_NBIS.txt`（重生成，5/6 解算）、`_recursion_reg_PLD.txt`、`_recursion_reg_AMT.txt`、`_recursion_reg_XOM.txt`

Modified

- `config.py` / `models/router.py` / `models/__init__.py` / `classification/classifier.py` / `data/reconciliation.py` / `data/models.py` / `data/validator.py` / `reporting/dashboard.py` / `valuation/wacc.py` / `data/providers.py` / `tests/conftest.py`

Notes

- 覆盖恒等式（适用 = 解算 + 失败）在 golden invariant 中显式断言；对账层由「纯只读」修订为「只读探测 + 白名单写侧 + 审计链」（ADR-011 修订，见 DECISIONS.md）。
- `_recursion_reg_NBIS.txt` 已用 Session #10 的离线确定性 pipeline 重新生成（旧文件为 Session #09 的 Yahoo 实时版）。
- pytest **78/78 passed**（61 → 78，+17 用例）。CHANGELOG.md 已同步 Session #10 条目。

## 2026-11-03 (Session #09 — JNJ 递归自我改进 3 轮: 分桶算术 + 对账口径语义 + 风险展示诚实性)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以 JNJ（成熟高股息医药巨头，Beta −0.09，与 NBIS 完全对立画像）为标的，**上一轮报告作为下一轮起点**，连续 3 轮「评估产出 → 定位缺陷 → 修代码 → 重跑」。
基线 `_recursion_jnj_round0.txt` → 每轮产出 `_recursion_jnj_roundN.txt`；每轮后 `pytest 61/61` 通过，并做 NBIS / SOFI / AAPL / JPM 回归（4 只均 exit=0）。

Completed

- ✅ **Round 1：模型分桶算术自洽 + ReverseDCF 误导标签**
  - 根因：`n_total=len(results)` 计入 ReverseDCF，但被 `_EXCLUDED_FROM_MEDIAN` 从 `solved` 里 `continue` 排除且未落桶 → `适用6·解算5·失败0·合计6`（5+0+0≠6）
  - 修复：`analysis/model_agreement.py` 新增第四桶 `n_display_only`/`display_only_models`，`n_applicable = n_total − n_not_applicable − n_display_only`，使「适用 = 解算 + 失败」恒等；虚假 `1 of 6 applicable models failed` 告警改为按真实 `len(failed)` 触发
  - `reporting/dashboard.py`：ReverseDCF 由误导性 `[估值合理]` 改标「（反向求解＝当前价，非独立估值）」；分桶行显示「合计 6（含 1 个仅展示，不计入统计）」，覆盖标签由「基本可用（5/6）」纠正为「充分（5/5）」
- ✅ **Round 2：对账把「GAAP vs 调整后 EPS 口径差」误判为「盈利基数极不稳定」**
  - `data/reconciliation.py` 滚动 P/E 检查改为方向感知文案：供应商 P/E 低于 价格/GAAP-EPS 隐含值 → 判为 non-GAAP/正常化口径差；高于 → 旧口径/摊薄股数或盈利下滑
- ✅ **Round 3：FCF Yield Gap 误报守卫 + Beta 展示一致性**
  - `analysis/risk.py`：FCF Yield Gap 新增守卫（正 FCF 且 FCF/净利≥0.8 且非高增长、收益率<4% → 降一级）；JNJ 该旗标 High→Medium，总体风险 75→80、High 2→1
  - `valuation/wacc.py` 暴露 `BETA_WINSOR_LO/HI`；`reporting/dashboard.py` 市场区对越界 β 追加「原始值超出 CAPM 区间 [0.30, 2.50]，WACC 采用截断值 0.30」标注

Created

- `_recursion_jnj_round0..3.txt`（本轮 JNJ 迭代产出）+ `_recursion_reg_NBIS/SOFI/AAPL/JPM.txt`（跨标的回归证据）

Modified

- `analysis/model_agreement.py` / `reporting/dashboard.py` / `data/reconciliation.py` / `analysis/risk.py` / `valuation/wacc.py`

Notes

- 未改动数据契约破坏性字段；NBIS/SOFI/AAPL/JPM 回归全通过。CHANGELOG.md 已同步 Session #09 条目。

## 2026-11-03 (Session #08 — NBIS 递归自我改进 3 轮: 报告自洽 + 极端终值门控 + 数据失真守卫)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以 NBIS 为标的，**上一轮报告作为下一轮起点**，连续 3 轮「评估产出 → 定位缺陷 → 修代码 → 重跑」。
基线 `_recursion_round0.txt` → 每轮产出 `_recursion_roundN.txt`；每轮后 `pytest 61/61` 通过。

Completed

- ✅ **Round 1：报告自相矛盾消除**
  - 增长标题「高速增长」与 bullet「爆发式增长 (>40%)」矛盾 → `verdict_intuition.py::build_growth_verdict()` 标题对齐 `_rev_cagr_label` 分档
  - 业务类型 headline「SaaS」与自身资产轻冲突警告矛盾 → `CompanyProfile.effective_business_type`/`business_type_conflict_note` + `dashboard._business_section()` 渲染「SaaS → AI/Cloud Infrastructure」
- ✅ **Round 2：DCF 极端终值权重可靠性门控**
  - `model_agreement.py` DCF 降权由单一 ×0.5 改为分级（TV/EV>0.8→0.5 / >1.5→0.25 / >3.0→0.1）
  - NBIS DCF 权重 0.5→0.1，**质量加权中位估值 $30.37(DCF) → $26.41(EV/Sales)**；`dcf.py` 输出「DCF point value unreliable」；极端终值 note 置顶
- ✅ **Round 3：反向 DCF 负上限措辞 + 风险指标失真守卫**
  - `reverse_dcf.py` 负 EV 改述（即便 80% CAGR 上限 EV 仍为负）
  - `risk.py::_margin_risk()` 剔除营收 <10% 峰值基期，不足 3 期降级 Low；NBIS 风险 High→Medium（50→58）

Created

- `_recursion_round0..3.txt`（本轮 NBIS 迭代产出，回归证据）

Modified

- `reporting/verdict_intuition.py` / `data/models.py` / `classification/ml_classifier.py` / `reporting/dashboard.py` / `analysis/model_agreement.py` / `models/dcf.py` / `models/reverse_dcf.py` / `analysis/risk.py`

Notes

- 未改动数据契约破坏性字段；SOFI/AAPL demo 回归通过。

## 2026-10-27 (Session #07 — NBIS 第二版方法论修复: 覆盖率门控 + 质量加权中位 + 概率结论 + 估值可用性拆分)

AI Agent

```
DeepSeek-based Agent (TRAECoder — session #7, resumed from context loss)
```

Completed

- ✅ **问题 #1（最严重）：2/6 覆盖率 + Very Strong = 统计假象** → `analysis/model_agreement.py` 重写
  - 模型三桶分类：solved / not_applicable（INSUFFICIENT_DATA）/ failed（NO_SOLUTION_IN_RANGE 等）
  - 覆盖率门控：`gated_cv = base_cv × 覆盖因子 ÷ 质量因子`（覆盖因子 = sqrt(applicable/solved) clamp [1.0, 2.0]）
  - 硬覆盖率封顶：solved≤1→Very Weak、==2→Weak、==3→Moderate、≥4 不封顶
  - 报告展示：模型分桶 / 一致性门控（质量因子·覆盖因子·门控 CV·原始一致性）/ 不适用模型列表 / 失败模型列表
  - NBIS：一致性由 Very Strong → **Weak**
- ✅ **问题 #2：中位估值 $26.88 = 两个低质量模型等权平均** → 质量加权中位数
  - 权重体系：SOLVED=1.0 / APPROXIMATE=0.5 / TV/EV>80% 的 DCF 再×0.5 / 分类置信度<55% 的倍数再×0.5
  - 输出 `median_value_weighted` + `model_weights` + `downweighted_models`；报告展示权重与降权原因（NBIS: DCF=0.5, EV/Sales=0.25）
- ✅ **问题 #3：每股估值基数不可用（股数差 42.9%）** → 估值可用性评分拆分
  - `data/validator.py`：`_valuation_usability()` + `per_share_basis_unreliable()`（三键：流通股数/市值/TTM EPS）
  - `data/models.py`：`reconciliation_mismatches` / `valuation_usability_score` / `usability_label()`
  - 报告分「源数据质量」（NBIS 83/100 High）与「估值可用性」（NBIS 34/100 Critical）两行；股数偏差>25% 抑制每股公允值
- ✅ **问题 #4：情景/中位/公允区间口径不一致；负熊市值** → `verdict_intuition.py` + `analysis/scenario.py`
  - `_scenario_summary()`：支持"当前价高于**全部**情景"（不再误写"落在区间内"）
  - 负 pps floor 到 0 + "股权价值归零"note
  - 公允区间标注样本数 n + 覆盖率；股数不可靠 → 标签改为"⚠️ 每股估值基数不可靠…仅方向性参考"
- ✅ **问题 #5：分类偏 SaaS / peer 近似 / 50% 置信倍数占中位一半** → 人工 AI Cloud peer 组 + 再降权
  - `models/multiples.py`：`AI_CLOUD_PEER_GROUP`（CoreWeave/IREN/Equinix/Oracle/Nebius，band_width=0.625）+ `_ai_cloud_peer_note()` 参考带
  - 分类置信度<55% 的 APPROXIMATE 倍数权重再×0.5
- ✅ **问题 #6：WACC 单点失控 + 反向 DCF 负 EV** → 三 beta 透明化 + 区间估值 + 隐含量化
  - `valuation/wacc.py`：`beta_raw`/`beta_bottom_up` + `beta_transparency_note()` + `wacc_range_note()`
  - `models/dcf.py`：WACC 行业区间上下沿估值（NBIS 6.5%→$1,574.90 / 11.5%→$237.37，暴露结论对 WACC 极端敏感）
  - `models/reverse_dcf.py`：`_normalized_growth_solve()` → "当前价隐含营收 CAGR ≈ 27%"替代无意义负 EV
- ✅ **问题 #7：蒙特卡洛与模型集成口径不一致** → `simulation/monte_carlo.py` 重写
  - `prob_above_price` / `prob_overvalued_30` / `prob_equity_zero`（NBIS: 0.3% / 97.5% / 6.7%）
  - 4×4 驱动因子 (cagr/margin/wacc/tg) Cholesky 相关抽样 + Gordon 稳定约束 `tg=min(tg, wacc-0.005)`
  - 负值 floor 到 0 计入归零概率（不再丢弃尾部）
- ✅ **回归验证：pytest 61/61 全通过**；demo NBIS + demo_fast SOFI/AAPL 端到端全通过

Modified

- `analysis/model_agreement.py` — 三桶分类 + 覆盖率门控 + 质量加权中位 + 低置信降权（重写）
- `simulation/monte_carlo.py` — 概率结论 + 相关抽样 + 负值 floor（重写 run/result）
- `data/validator.py` — `_valuation_usability()` + `per_share_basis_unreliable()` + `reconciliation_mismatches`
- `data/models.py` — `reconciliation_mismatches` / `valuation_usability_score` / `usability_label()`
- `reporting/verdict_intuition.py` — 情景一致性 + 负价值文案 + 公允区间 n/覆盖率 + 股数不可靠门控
- `analysis/scenario.py` — 负 pps floor 到 0 + 归零 note
- `valuation/wacc.py` — 三 beta 透明度 + 区间提示
- `models/dcf.py` — WACC 区间估值
- `models/reverse_dcf.py` — 隐含量化 diagnostic
- `models/multiples.py` — `AI_CLOUD_PEER_GROUP` + `_ai_cloud_peer_note()`
- `reporting/dashboard.py` — 渲染模型分桶/门控/质量加权中位/估值可用性/概率结论/WACC 区间/Beta 透明度

Created

- （无新文件；本次全部为既有模块的方法论硬化）

Notes

- 用户第二版 NBIS 报告 7 点批评是本轮修复的规格：核心方法论 = "依据更少、结论更自信"是致命缺陷，必须让不确定性向下游传导
- 修复哲学与 user_profile 一致：反对在基础数据不确定时给出伪精确结果；当唯一证据是低质量证据时，输出"低置信参考 + 概率语言"，而非单点"公允价"
- 向后兼容：SOFI（Bank, 5/5 覆盖, Very Weak）/ AAPL（MatureTech, 6/7, Moderate）peer 路由与倍数输出完全不变，零回归

---

## 2026-10-27 (Session #06 — NBIS 误估值修复: 数据对账层 + AI/Cloud 算力 peer 路由 + 无意义倍数守卫)

AI Agent

```
DeepSeek-based Agent (TRAECoder — session #6, resumed from context loss)
```

Completed

- ✅ **问题 #1：数据对账层缺失** → 新建只读 `data/reconciliation.py`（10 项交叉校验）
  - 校验项：market_cap≈price×shares / EV≈mcap+debt−cash / TTM EPS≈NI/shares / trailing P/E≈price÷EPS / EV/EBITDA / P/B / EV/Sales / TTM FCF≈OCF+capex / market shares≈最新年度 shares / EBITDA≤营收（D&A 合理性）
  - 容差：恒等式 5%（`_TOL_IDENTITY`）/ 供应商口径 20%（`_TOL_PROVIDER`）/ 股数 25%（`_TOL_SHARES`）
  - 纯只读：`reconcile(data)` 绝不突变 FinancialData；下游（multiples 守卫 / 数据质量评分 / 报告）自主决定是否降级
  - 仪表盘新增「🔗 数据对账」区块：NBIS 输出「已校验 10 项 · 一致 6 · 不一致 4」（P/E 671.57 vs 1306.71 / EV-EBITDA 104.27 vs 40.76 / 股数 361.5M vs 253.0M / EBITDA/营收 103%）
- ✅ **问题 #2：行业分类 / peer 倍数路由错误** → `models/multiples.py` 细粒度化 + AI/Cloud 重路由
  - 技术族 peer 桶拆分：Software-SaaS / Software-Mature / Semiconductors / **AI/Cloud Infrastructure**（新增，P/E 35 / EV-EBITDA 18 / EV-Sales 8）
  - `_BT_TO_SECTOR` 映射更新：SaaS→Software-SaaS、MatureTech→Software-Mature、Semiconductor→Semiconductors
  - 新增 `_resolve_peer_bucket()`（返回 key/src/blend 三元，key 与 blend 恰一非空）+ `_compute_infra_override()`（Very Capital Intensive + 高/中增长 + 弱/负 FCF + capex/revenue≥1.0）
  - 命中时把技术族键重路由到 AI/Cloud 桶，source 串标注 `re-routed ... (APPROXIMATE)`
- ✅ **问题 #3：P/E 与 EV/EBITDA 对不适用公司仍给值** → `applicability_check()` 新增两个硬守卫
  - 隐含 P/E > 100x（`_IMMATERIAL_PE_THRESHOLD`）→ P/E "not meaningful"（NBIS 净利 $42M vs 市值 $55B，隐含 ~1307x）
  - EBITDA/营收 > 90%（`_DNA_LOADED_EBITDA_MARGIN`）→ EV/EBITDA "not directly comparable"（NBIS EBITDA/营收=103%，D&A 主导）
- ✅ **问题 #4：置信度不看「标签 vs 财务原型」矛盾** → `classification/ml_classifier.py` 新增资产轻原型冲突扣减
  - 常量：`ASSET_LIGHT_CONFLICT_CAPEX_RATIO=1.0` + `ASSET_LIGHT_TYPES={SAAS, MATURE_TECH, MEDIA}`
  - ML 判资产轻类型 + capex/revenue≥1.0 + 负 FCF → 置信度 cap 50%，写 ConfidenceAdjustment（step="Asset-light prototype conflict"）+ reasons
  - NBIS 审计链：ML 92.0% → 缺失封顶 -37.0% → 原型冲突 -5.0% → Final 50.0%
- ✅ **附带修复：terminal_growth.py 零增长地板 bug（历史遗留）**
  - 0≤base<1.5% 分支：由坍缩到 DECLINING_BASE(0.5%) 改为抬高到成熟地板 BASE_FLOOR(1.5%)（只有真实衰退才衰减）；docstring 同步
  - `test_terminal_growth.py::test_floor_base_keeps_low_strictly_below` 由 ❌ 变 ✅
- ✅ **回归验证：pytest 61/61 全通过**（此前 60 passed + 1 failed）
- ✅ **端到端验证（三只覆盖不同场景）**：
  - NBIS：分类 SaaS 置信度 50%（审计链完整）+ P/E Insufficient Data(not meaningful) + EV/EBITDA Insufficient Data(D&A-dominated) + EV/Sales $26.41 重路由 AI/Cloud(APPROXIMATE) + 对账 4 项不一致 ✅
  - SOFI：Bank → sector table[Banks] P/E 11 / P/B 1.2（向后兼容不变）✅
  - AAPL：MatureTech → sector table[Software - Mature] P/E 25 / EV-EBITDA 17 / EV-Sales 5（向后兼容不变）✅

Modified

- `models/multiples.py` — 细粒度桶 + `_BT_TO_SECTOR` 更新 + `_COMPUTE_INFRA_CAPEX_RATIO`/`_COMPUTE_INFRA_SOURCE_BUCKETS` 常量 + `_compute_infra_override()` + `_resolve_peer_bucket()` 拆分 + `_sector_peer_multiple()` 重路由 + `applicability_check()` 两守卫
- `classification/ml_classifier.py` — `ASSET_LIGHT_CONFLICT_CAPEX_RATIO`/`ASSET_LIGHT_TYPES` + "Asset-light prototype conflict" 扣减分支（is_fintech_hybrid 之后）+ reasons 追加
- `valuation/terminal_growth.py` — 0≤base<1.5% 分支修复 + docstring 第 13 行
- `reporting/dashboard.py` — `_fmt_recon(v, unit)` + `_data_section()` 对账区块
- `data/reconciliation.py` — `ReconciliationCheck.render(fmt)` 改双参签名 + `to_lines` 默认 lambda 双参 + 第 10 项检查改比率语义

Created

- `data/reconciliation.py` — 数据对账层（纯只读；ReconciliationCheck/ReconciliationReport/reconcile）

Notes

- 用户实测 NBIS 报告是本轮修复的黄金样本：重资本算力（capex/revenue≈822%）、负 FCF（-$6B）、EBITDA/营收=103%、净利极薄（$42M）、股数口径偏差 +42.9%、供应商 P/E 与内部推算差 2x
- 修复哲学：宁可显式暴露「不确定 / 不可比 / 近似」，也不给出伪精确的倍数估值——对上 user_profile「分类不确定性必须向估值确定性传导」的偏好
- 向后兼容：SOFI（Bank）/ AAPL（MatureTech）peer 路由与倍数输出完全不变，零回归

---

## 2026-10-08 (Session #05 — Intuitive Labels 直观标签上线 + NU demo 文案双 Bug 修复)

AI Agent

```
GPT-based Agent (TRAECoder — session #5, resumed from Step D)
```

Completed

- ✅ **直观标签计算层 (Verdict Intuition)** — 新建 `reporting/verdict_intuition.py`
  - `build_growth_verdict(gap)`: 营收 CAGR 6 档分桶（爆发式/高速/稳健/温和/低速/负增长）+ FCF CAGR 5 档 + 预测vs历史 pp 差值一句直观中文总结（"仍属高速增长，但预测较历史明显放缓-21.1pp"）+ 整体增长 emoji+summary（🚀/📈/📊/📉 + 历史表现判断 + 预测增速变化）
  - `build_valuation_verdict(agreement, scenarios, ...)`: price vs median 7 档标签（显著高估/高估/小幅高估/合理/小幅低估/低估/显著低估）+ 三档情景跨度宽窄判断（极宽>120%SV / 较宽>60% / 适中>25% / 窄）+ 公允区间标签（在上限/下限/区间内）+ 模型覆盖 label + 多信号合成 headline（emoji 5 档 🟩🟢🟡🟠🔴）+ caveats 组合（弱一致/非常弱一致/即使乐观情景也达不到/模型覆盖不足）
- ✅ **数据卡片 + 分层渲染方法** — `data/models.py`
  - `GrowthVerdictCard.bullet_lines()`: 8 字段 → 4 bullet（整体增长判断/历史增长/预测vs历史/隐含vs历史+隐含vs预测）
  - `ValuationVerdictCard.header_lines(include_headline=True)`: 10 字段 → 最多 5 行（一句话结论 + 中位估值对比 + 情景跨度 + 公允区间 + 判断依据），通过 include_headline 开关避免 headline 重复展示
- ✅ **报告多区块差异化渲染 (分层展示)** — `reporting/dashboard.py` 4 处挂接：
  1. 🔥 **OVERVIEW 首屏区块（新增）**：build_report() 最前部（provenance banner 后，business 前）调用 `_intuitive_overview_section()`，合并 valuation header_lines(include_headline=True) + growth bullet_lines()，用户首屏直接看到结论 + disclaimer 提示「快速参考」
  2. **GAP 预期差距区块**：末尾追加「📈 增长直观解读」+ growth bullet_lines()（与 Overview 增长区内容重复，但属于对应章节的上下文关联展示，按设计保留）
  3. **AGREEMENT 模型比较区块**：`_agreement_section()` 改名标题 →「🤝 估值细节拆解」+ 调 header_lines(**include_headline=False**)，只展示 bullet 细节（中位对比/情景/公允/依据），**不**重复展示一句话结论 headline，解决用户抱怨的 headline_summary 逻辑重复
- ✅ **🐛 Bug #1 修复：中位估值对比主语重复**
  - 修复前输出：`中位估值对比：**高估**（中位估值 较中位估值高 +41.6%）`
  - 根因：`detail = f"（中位估值 {self.median_vs_price_detail}）"` 外层多加了前缀，但 _vs_median_label() 输出的 median_vs_price_detail 已是自包含完整句「当前价 $15.58 较中位估值 $11.01 高出 +41.6%」
  - 修复后：`中位估值对比：**高估**（当前价 $15.58 较中位估值 $11.01 **高出 +41.6%**）` → 主语清晰，无重复
  - 同时在 Decision 007 中新增「主语不自包原则」防止未来回归
- ✅ **🐛 Bug #2 修复：一句话估值在 OVERVIEW + AGREEMENT 双区块重复展示**
  - 修复前输出：首屏显示「一句话估值结论」，模型比较区又显示「一句话估值」完全相同的文案，用户困惑"为什么又说一遍"
  - 根因：两处都调用了默认参数 `v.header_lines()` → `include_headline=True`
  - 修复方案：(a) `header_lines()` 新增 `include_headline: bool = True` 关键字参数；(b) `_agreement_section()` 传 `include_headline=False`；(c) section 标题从「🤝 一句话估值:」改为「🤝 估值细节拆解:」，明确定位为"展开 bullet 细节"而非"重复结论"
  - 设计原则固化：Decision 007 明确「一次 head、多次细节」的分层架构
- ✅ **回归验证：pytest 51/52**（唯一失败 test_terminal_growth.py::test_floor_base_keeps_low_strictly_below 是 TVG floor 历史遗留 bug，与本次改动无关；之前用户确认的 27/27 risk/classifier/ml/sensitivity/dcf 套件全部通过）
- ✅ **端到端验证：demo_fast NU + SOFI + AAPL 三只全通过**（覆盖 Conglomerate、Hybrid Financial Institution、MatureTech 三种典型类型）：
  - NU: 一句话结论🔴高估、增长🟡历史高速+预测明显放缓、估值细节拆解仅展示bullet（无重复headline）✅
  - SOFI: Hybrid Financial Institution 混合标签✅ + classification_confidence_level Medium + exposures 双轴显示✅ + 金融机构风险/指标 caveat 全部✅ + 🚀整体增长 + 🔴显著高估 + 即使乐观情景也达不到当前价✅
  - AAPL: MatureTech 99.8% 单标签✅（非Hybrid，不显示混合区块）+ 增长隐含vs历史明显提升 25pp✅ + 显著高估 + 即使乐观情景也达不到✅

Modified

- `data/models.py` — lines 190-266：**GrowthVerdictCard.bullet_lines() + ValuationVerdictCard.header_lines(include_headline=True)** 两个渲染方法新增；Bug #1 修复：header_lines() 第257行删除 detail 冗余前缀「中位估值」；Bug #2 修复：新增 include_headline kwarg（默认True保持向后兼容）
- `reporting/dashboard.py` — lines 96-161, 478-507, 544-555：**_intuitive_overview_section() 新增**（首屏直观判断+快速参考免责声明）；build_report() 第 116-119 行 provenance 之后 business 之前插入 overview 区块；_gap_section() 末尾追加「📈 增长直观解读」；**_agreement_section() Bug #2 修复**：标题改名 + v.header_lines(include_headline=False)
- `reporting/verdict_intuition.py` — **本次新建文件**（Session #05 Step C-1 产出）；__all__ 暴露 8 个符号（2 个 build 主函数 + 5 个分桶 helper + 1 个 scenario helper）

Created

- `reporting/verdict_intuition.py` — 直观标签计算层（纯函数、无 IO、便于测试）；374 行代码（236 行估值 + 135 行增长 + 3 行 __all__）

Notes

- **直观度设计哲学**：首屏 Overview 只做「结论速览」不做证据，详细证据（每个模型的数值/敏感性/风险）在后续章节展开。用户典型阅读路径：首屏结论（0.5秒扫emoji+label）→ 决定看不看细节 → 是则翻到对应章节（估值/模型/风险）；否则直接关页面节省时间
- **Growth 增长标签在 Overview 出现 + 在 Gap 章节再次出现是有意设计**（不是 bug）：前者是"结论区速览"，后者是"和原始预期差距数字放在一起便于读者交叉验证"；未来若用户嫌冗余可将 Gap 章节的增长解读简化为纯 bullet 细节（不加整体判断emoji）
- **NU (Nu Holdings)** 是测试文案渲染 bug 的黄金样本：(a) sector/industry=Missing 触发 confidence cap；(b) model coverage=2/4 不足（触发「⚠️模型覆盖不足」caveat + Reverse DCF 不可用）；(c) 41.6% 溢价正好落在 >20% <50% 区间（**高估**非显著高估）；(d) historical 52.9% 爆发式增长 → forecast 31.9% 仍高速 + -21pp 明显放缓（覆盖了 verdict_intuition.py 第 104-108 行高速分支的放缓分支）

---

## 2026-10-08 (Session #04 — SOFI 报告三问修复: 置信度透明 / Hybrid 业务 / 金融机构 FCF 指标)

AI Agent

```
GPT-based Agent (TRAECoder — session #4)
```

Completed

- ✅ 问题 #1 修复：ML 置信度 66.6% → 业务类型 55% 黑盒扣减透明化
  - 新增 `data/models.py` ConfidenceAdjustment dataclass (step_name + delta + reason)
  - CompanyProfile 新增 ml_raw_confidence + confidence_adjustments[] 字段
  - `ml_classifier.py` classify() 记录两步扣减：Unknown class penalty + Missing-sector/industry cap (每步有 pp 差值和 reason)
  - `dashboard.py` _business_section() 渲染「ML Top-1 prob → 每步 Δ → Final」拆解明细（仅当有实际扣减时显示）
  - 验证：SOFI 输出 "ML 66.6% → Missing sector/industry cap -11.6% → Final 55.0%"，AAPL 同样显示扣减链，扣减前=后=99.8%
- ✅ 问题 #2 修复：SOFI 单 Bank 标签 → Hybrid Financial Institution 混合表达
  - 不扩 BusinessType 枚举，新增 CompanyProfile 5 字段：is_hybrid / primary_business_type / secondary_business_type / hybrid_label / classification_confidence_level
  - 新增 BusinessExposure dataclass：5 轴暴露度聚合 (Financial / Technology / Cyclical / HardAssets / Diversified)，阈值≥2% 才渲染
  - 三条 Hybrid 触发规则：
    (a) FinTech Hybrid: Financial Top-1 + Technology≥8% (Bank p≥50% + MatureTech/SaaS/Semiconductor 合计≥8%)
    (b) Tech-Fin Hybrid: Technology Top-1 + Financial≥8%
    (c) Generic Low-Separation: Top-1<55% 且 Top1/Top2 ratio<3x
  - 验证：SOFI ✅ 触发 (a) → Primary=Bank, Secondary=FinTech Platform, Label="Hybrid Financial Institution", Level=Medium；AAPL ❌ 不触发，保持 MatureTech 单一
  - `classifier.py` 规则引擎端镜像补齐 Hybrid + Exposures 字段保证契约一致
- ✅ 问题 #3 修复：金融机构 FCF/EV/Net Debt 指标口径严重错配 → 7 层机构敏感适配
  - 根因链：银行 TTM FCF=-$9B (经营借款是业务本身, 非经营现金流) → 三个连锁误报：(a) 现金流剖面 Weak/Negative FCF (b) 4y neg-FCF Medium risk (c) FCF Yield=-60.17% High risk → SOFI risk 80/100 低估 15 分
  - 修复层 1 `classifier.py _characterize_profile()`:
     • Bank/Insurance profitability：operating_income 缺失时回退 net_margin（银行 operating_income 常缺失于 Yahoo）
     • Bank/Insurance cash_flow：不用 FCF margin 判 Weak，改用 net_income 正/负判 Profitable/Loss-Making；文案加 "FCF not meaningful for banks"
     • Bank/Insurance leverage：D/E 阈值从普通 2x Medium / 4x High 放宽到 >15x 才 Medium（银行高杠杆是常态，8-12x 属健康范围）；文案 "Well-Capitalized / Adequate / Under-Capitalized" 三档
     • Bank/Insurance capital_intensity：标 "N/A for financial institutions"
     • REIT cash_flow：文案加 "Prefer FFO/AFFO metrics over GAAP FCF for REITs"
  - 修复层 2 `analysis/risk.py` 4 个风险函数签名加 profile=None：
     • analyze() 顶部 is_fin/is_reit 判断 → 末尾新增 Severity=None 级「指标定义差异说明」信息 flag（不扣分，仅提示读者）
     • _leverage(profile): Bank D/E >15x Medium only；普通公司保持 2x/4x 不变
     • _margin_risk(profile): Bank 完全跳过 neg-FCF 年数计数 flag；REIT 证据文案加 GAAP-vs-FFO 备注
     • _forecast_risk(profile): Bank 直接 return（根本不计算 FCF Yield）；REIT 把 FCF Yield 严重度降一档 (High→Medium, Medium→Low) + 加 caveat
  - 修复层 3 `reporting/dashboard.py _market_section(profile=None)`:
     • profile 参数新增；build_report() L118 同步传参（首次漏传已修正）
     • is_fin 分支：EV / Net Debt / EV/EBITDA / FCF TTM 总览 四行全部加斜体 caveat 注释（_*Financial institution metric not directly comparable*_）
     • is_reit 分支：FCF / EV/EBITDA 行加 prefer FFO/AFFO 文案
     • 普通公司：完全无 caveat，向后兼容零回归
  - 验证：SOFI risk=95/100（仅 Beta=2.31 一个 Medium flag）+ 信息栏新增 "Financial institution metrics differ" 说明；AAPL 保持 Strong FCF / Asset Light / 原生指标无 caveat
- ✅ 回归测试：`pytest tests/test_risk.py tests/test_classifier.py tests/test_ml_classifier.py tests/test_sensitivity.py tests/test_dcf.py` → **27/27 passed** (零回归)
- ✅ 端到端验证：`python main.py demo_fast SOFI` (三问修复效果) + `python main.py demo_fast AAPL` (非金融公司向后兼容) → 双通过

Modified

- `data/models.py` — lines 165-240：新增 ConfidenceAdjustment + BusinessExposure dataclass；CompanyProfile 扩展 13 字段（ml_raw_confidence / confidence_adjustments[] / is_hybrid_classification / primary_business_type / secondary_business_type / hybrid_label / classification_confidence_level / business_exposures[] 等）+ __all__ 导出两个新 class
- `classification/ml_classifier.py` — lines 1073-1330：新增 _build_exposures() (11 类→5 轴聚合) + _detect_hybrid() (3 条触发规则 + 4 档置信度等级)；classify() 重构：置信度调整明细数组(Unknown cap + Missing-sector cap 两步) + 填充所有 Hybrid/Exposures 字段；rule fallback 分支同样补齐结构防止空值异常
- `classification/classifier.py` — lines 57-471：classify() 规则引擎端镜像补齐 ConfidenceAdjustment + Hybrid + Exposures 三结构；_characterize_profile() 金融机构专项修复(profitability 回退 net_margin / cash_flow 文案换 Profitable+FCF-caveat / leverage 15x 阈值 / capital_intensity N/A / REIT FFO 文案)
- `reporting/dashboard.py` — lines 116-299：build_report() L118 传 profile 给 _market_section；_business_section() 重构：Hybrid 分支(Primary/Secondary Model + 分类+置信度等级) + 置信度拆解明细仅当有扣减才显示 + Exposures 5 轴条形图(≥2%才渲染) + classification_reasons 3→4 条；_market_section(profile=None) 新增：Bank/Insurance 的 EV/Net Debt/EV-EBITDA/FCF TTM 四行 caveat 斜体 + REIT prefer FFO/AFFO
- `analysis/risk.py` — lines 43-329：analyze(profile=None) 顶部 is_fin/is_reit 判断 + 末尾 None 级信息 flag；_leverage(profile) 金融机构 15x Medium / 普通 2x-4x；_margin_risk(profile) 银行跳过 neg-FCF 计数 / REIT 证据加备注；_forecast_risk(profile) 银行直接 return / REIT 严重度降一档 + 文案

Created

- (无新文件；均为现有文件扩展修改)

Notes

- 风险评分修复对比：SOFI 修复前 80/100 (Medium×2 + High×1) → 修复后 95/100 (仅 WACC Beta Medium×1 + Info×1)
- Hybrid 触发规则设计哲学：不改变估值模型路由（仍然 Bank 用 Bank DDM/RIM），仅增加"语义层"的混合表达 + 暴露度多轴提示读者边界性
- 调用链签名变更安全保证：所有新增 profile 参数全带 =None 默认值 + getattr(profile, "is_xxx", False) 判断 → pytest 现有构造的所有 analyze() 调用 (未传 profile) 行为与修改前 100% 一致；经 grep 确认唯一其他调用点 telegram_bot.py:79 已天然传 profile
- Windows PowerShell stderr 警告：WARNING 级日志被 PS 包装为红色 NotSpecified RemoteException，但 pytest exit=0、passed=27 全部正常；不要看到红色就恐慌

---

## 2026-10-05 (Session #03 — Real-Data ML v2.1 训练发布 + Sanity 验证)

AI Agent

```
GPT-based Agent (TRAECoder — session #3)
```

Completed

- ✅ 验证 CSV 质量：1001行（1表头+1000数据），dup_headers=0，empty_label=0，L2 PowerShell 类型批注垃圾行确认已清除
- ✅ 删除 3 个旧 synthetic 工件 (lgbm/tfidf/meta v2.0-synthetic .pkl)
- ✅ 修改 ml_classifier.py _train_from_scratch() 末尾增加 TrainMeta.version / note overwrite 逻辑
  - version: 从 dataclass 默认 "2.0-synthetic" 动态改为 `"2.1-real-data-train%d" % n_samples`
  - note:    写死 archetypes → `"real-data trained on N manually labeled rows from labeling_dump.csv"`
- ✅ 重新训练 LightGBM：train_acc=97.40%，n=1000，11 类别分布完整
- ✅ 安装依赖 lightgbm + scikit-learn（运行时缺包，已补装）
- ✅ 运行 classification/_run_train_and_verify.py：打印 TrainMeta.version/note 确认 overwrite 生效 (2.1-real-data-train1000 / real-data trained on 1000 rows)
- ✅ 15 只 sanity 股票预测 (AAPL/MSFT/NVDA/JPM/BAC/PLD/AMT/XOM/CVX/NEE/DUK/KO/PEP/JNJ/CRM)：Top1/Top2 分布合理
- ✅ 运行 main.py demo_fast NVDA：端到端 Markdown 报告分类 Semiconductor 99.9% ✅，报告格式完整 (WACC/TVG/Sensitivity/Risk)
- ✅ 运行 main.py test_demo：AAPL/MSFT/NVDA 三件套完整跑通
- ✅ 自定义 16 只扩展 sanity 集分类正确性验证：12/16 = 75%，详细根因分析（4 类边界误判）
- ✅ 训练集质量量化审计：6 项 Known Issues 登记 + 3 项高影响特征缺失排入优化
- ✅ AGENT.md v2.0 → v2.1 全量更新（26章节，Current Context/Completed/Pending/Next/Known Issues/Blockers/Session Memory/Checkpoints/Change Log 全部同步）

Modified

- `classification/ml_classifier.py` — lines 771-782：在 TrainMeta 构造后增加 2 行 overwrite 代码，永久修正 dataclass 默认 "2.0-synthetic" 污染真实工件问题
- `classification/_ml_artifacts/*.pkl` × 3 — 删除旧 v2.0-synthetic 后重新生成 v2.1-real-data-train1000 版本

Created

- `classification/_ml_artifacts/lgbm_multiclass_v2.pkl` — v2.1 真实标注版模型 (7798730 bytes)
- `classification/_ml_artifacts/tfidf_vectorizer_v2.pkl` — v2.1 向量器 + SelectKBest (3296 bytes)
- `classification/_ml_artifacts/train_meta_v2.pkl` — v2.1 TrainMeta (version="2.1-real-data-train1000", note="real-data trained on 1000...", train_acc=0.9740)

Notes

- 合成版 vs 真实版 train_acc 对比：98% ≈ 97.4%，但 OOS sanity 准确率从合成版 ~85% (推断) 降到真实版 75% → 合成数据过拟合确认
- Sanity 4 个边界误判清单：MSFT(Mature→Semi 60:40), AVGO(Semi→Mature 100:0 CSV标签错!), AMT(REIT→Util 60:40 interest缺失), NEE(Util→REIT 50:50 capex异常)
- 下一步最关键优化不是加数据而是特征补全（sector/industry 83% + interest 82%）和标签纠错（AVGO）

---

## 2026-10-05 (Session #02 — 1001只数据收集完成)

# 19. Checkpoints

Checkpoint ID

```
CP-0031 - Caliber Contract + Systematized Cap-Boundary Audit + Render-Layer Caliber Invariant + Financial Operating Scenario (Session #14: caliber.py contract consumed by rendering layer; 3-layer ADR-023 cap-boundary audit incl. cross-file Part C → fixed models/sotp.py `conf <= 0.55`; golden invariant #6 engine-vs-scenario caliber; financial scenario ke + operating ROE dual-driver; pytest 95/95, DEFECTS empty)
```

Current Branch

```
main (local only, not initialized)
```

Current Commit

```
<待 git init>
```

Safe Rollback

```
<none>
```

Pipeline Step

```
Pipeline Step 30 / 31: Coverage Model Family Frozen (Replacement NAV + Unit-econ EV/Sales) + Report-Self-Consistency Hardening (prototype re-route parity, lens-conflict naming, derived-value structuring) → Feature Imputation (sector+industry+interest) → Label Correction → Optuna → v2.2 Retrain → sanity≥90% → AB Test → Deploy
```

---

# 20. Task Dependency Graph

```
Data Providers (Yahoo + Treasury)
    ↓
Financial Data Models + Normalizer
    ↓
WACC 7步法 ← Terminal Growth
    ↓
Valuation Models (6) ← BusinessClassifier (确定性)
    ↓                            ↓
Sensitivity + Scenario      LightGBM (synthetic v2)
    ↓                            ↓
Telegram Bot + Pipeline    ←  ML Hybrid Classifier
                                 ↑
                          ⭐ 1001 rows labeled CSV ⭐ (当前步骤)
                                 ↓
                          Retrain LightGBM (real-labels)
                                 ↓
                          A/B Test: deterministic vs synthetic vs real
                                 ↓
                          Deploy to Cloud + Monitoring
```

Never skip dependency order.

---

# 21. Coding Standards

Language

Python 3.13 (当前 .venv 使用)

Style

PEP8

Formatter

Black (已安装于 .venv)

Linter

Ruff

Type Checking

Pyright

---

# 22. Project Goals

Primary Goal

```
构建一个可在 Telegram 中使用的、准确率 ≥ 90%、解释性强的股票估值引擎
支持 11 类商业模式、6 种估值模型、敏感性分析与置信度输出
```

Secondary Goal

```
通过 1001 只真实标注数据，将商业模式分类准确率从 85% → 95%+
减少错误分类导致的估值模型不适用问题 (如把银行误分为 REIT 会导致模型完全错配)
```

Future Improvements

- 将训练集扩充到 5000+ (覆盖中盘/小盘股，提升非S&P500股票分类)
- 引入 Sector ETF 价格相关性作为额外分类特征
- 增加季度级别变化特征 (margin expansion/contraction rate)
- 支持非美股市场 (港股 0700.HK / A股 600519.SS)

---

# 23. Performance Targets

Example

Single Ticker Valuation (no cache)

< 8 sec (Yahoo 数据拉取 + WACC 计算 + DCF + Sensitivity)

With Hot Cache (<4h)

< 1.5 sec

ML Classification

< 200 ms (predict, 包含 TF-IDF 变换)

Telegram Bot Respond

< 15 sec (含 Markdown 分段 + 图表渲染 if enabled)

Training Dataset Size

≥ 1000 rows ⭐ 已达成 (1001)

ML Classification Accuracy (11-way)

- Deterministic rules:                ~85%
- Synthetic LightGBM (train):         ~98% (过拟合确认，OOS sanity 估计 80%)
- ✅ Real-labeled v2.1 (train):        97.4% (1000 rows)
- ✅ Real-labeled v2.1 (sanity OOS):   75.0% (12/16, 边界类受特征缺失影响)
- Real-labeled target (post 优化):    ≥ 90%  ← 补全 sector+industry+interest + 标签纠错 + 类别平衡 + Optuna 后目标

---

# 24. Future Roadmap

Phase 1

Planning ✅ 已完成 (架构/模块设计)

Phase 2

Core Development ✅ 90% — 还差 label 标注后的 ML 模型重训 + AB测试

Phase 3

Testing ⚪ 下阶段 — 扩充 pytest 覆盖到 80%+

Phase 4

Deployment ⚪ 后续 — Render / Cloudflare Workers 部署

Phase 5

Monitoring ⚪ 后续 — 追踪每日估值命中率、Yahoo API成功率

---

# 25. Notes

Free-form notes.

```
如何快速标注 1001 行 label？
推荐流程：
  1) 用 sector/industry 列先筛选 (已填充的 171 只直接批量标注)
  2) 对剩余 830 只用 company_name 关键词批量 VLOOKUP:
     - 含 "bank" / "banc" / "trust" → Bank
     - 含 "reit" / "real estate" / "property" → REIT
     - 含 "insurance" → Insurance
     - 含 "semiconductor" / "chip" / "gpu" / "memory" → Semiconductor
     - 含 "software" / "cloud" / "saas" / "platform" → SaaS (或 MatureTech 看增长)
     - 含 "utility" / "electric" / "power" / "water" / "gas" → Utilities
     - 含 "oil" / "gas" / "mining" / "metal" / "steel" / "coal" → Commodity
     - 含 "holdings" / "group" / "conglomerate" / "brk" / "ge" → Conglomerate
     - 剩余模糊的先标 Unknown，模型会继续用 fallback
  3) 最后人工抽检 5% 行纠错
```

---

# 26. End-of-Session Checklist

Before ending the session, confirm:

- [x] Completed task recorded (✅ Session #07: NBIS 第二版方法论修复（覆盖率门控 + 质量加权中位 + 估值可用性拆分 + 情景一致性 + AI Cloud peer 组 + WACC 三 beta/区间 + 反向DCF隐含量化 + 蒙特卡洛概率结论）；pytest 61/61；demo NBIS + demo_fast SOFI/AAPL 端到端通过)
- [x] Pending tasks updated (新增 2 个 MEDIUM：门控/概率结论 pytest 用例 + AI-Cloud 扩样；新增 2 个 LOW：失败模型清单展示 + 反向 DCF 三变量求解；Next Immediate Task 不变：特征补全 + 标签纠错)
- [x] Current status updated (🟢 Coverage-Gated Model Agreement + Probability Verdict)
- [x] Files created recorded (本次无新文件——全部为既有模块方法论硬化)
- [x] Files modified recorded (analysis/model_agreement.py / simulation/monte_carlo.py / data/validator.py / data/models.py / reporting/verdict_intuition.py / analysis/scenario.py / valuation/wacc.py / models/dcf.py / models/reverse_dcf.py / models/multiples.py / reporting/dashboard.py)
- [x] Decisions documented (新增 Decision 011 覆盖率门控 / 012 质量加权中位+估值可用性拆分 / 013 概率语言；对应 DECISIONS.md ADR-014/015/016)
- [x] Blockers documented (🟡 Minor 保持不变：特征补全 + 标签纠错；7 个 NBIS 第二版缺陷从 Known Issues → ✅ Resolved)
- [x] Next task assigned (Next Immediate Task 保持不变：特征补全 sector/industry + interest_to_revenue 重算 → AVGO 标签纠错 → v2.2 重训 → sanity≥90%)
- [x] Change log updated (2026-10-27 Session #07 完整记录 + 对应 CHANGELOG.md 新增 Session #07 Added/Changed/Fixed 三段)
- [x] Session memory updated (新增覆盖率门控/质量加权/估值可用性/概率结论锚点；NBIS 第二版复盘数值；3 只股票验证结果)
- [x] CHANGELOG.md 更新 (Session #07 Added/Changed/Fixed 三段 + Modified Files 明细)
- [x] DECISIONS.md 更新 (新增 ADR-014 覆盖率门控 / ADR-015 质量加权中位 + 估值可用性拆分 / ADR-016 概率结论)
- [x] pytest 回归验证 (tests/* 全部 61 项：**61/61 passed**)
- [x] demo_fast 端到端验证 (demo NBIS 覆盖率门控降级验证；SOFI Bank / AAPL MatureTech 向后兼容三只全通过)

### Session #09 (2026-11-03 — JNJ 递归自我改进 3 轮)

- [x] Completed task recorded (✅ Session #09: JNJ 递归改进 3 轮——Round 1 模型分桶算术自洽 + ReverseDCF 误导标签；Round 2 对账 P/E 口径语义；Round 3 FCF Yield Gap 误报守卫 + Beta 展示一致)
- [x] Current status updated (🟢 Bucket Arithmetic + Reconciliation Semantics + Risk Honesty)
- [x] Files created recorded (_recursion_jnj_round0..3.txt + _recursion_reg_NBIS/SOFI/AAPL/JPM.txt 回归证据)
- [x] Files modified recorded (analysis/model_agreement.py / reporting/dashboard.py / data/reconciliation.py / analysis/risk.py / valuation/wacc.py)
- [x] Change log updated (本节 Session #09 完整记录 + CHANGELOG.md `## [Unreleased] — 2026-11-03 (Session #09)` 条目)
- [x] Session memory updated (新增 discoveries 16/17/18 + Lessons learned 12/13)
- [x] pytest 回归验证 (tests/* 全部 61 项：**61/61 passed**，每轮后各跑一次)
- [x] 端到端验证 (JNJ demo_fast exit=0；NBIS / SOFI / AAPL / JPM 跨标的回归 4 只均 exit=0)

### Session #10 (2026-11-03 — 五项系统优化)

- [x] Completed task recorded (✅ Session #10: ① Replacement NAV 覆盖率锚（NBIS 2/3→5/6）；② 对账写侧 apply_overrides + OverrideLog；③ golden report diff 可断言回归；④ resolve_effective_beta 统一 β；⑤ AMT/XOM 资产结构覆盖)
- [x] Pending tasks updated (新增 MEDIUM：golden 基线随每次方法论变更刷新；AI/Cloud 重路由扩样仍保持)
- [x] Current status updated (🟢 Coverage + Reconciliation Hardening Frozen)
- [x] Files created recorded (models/replacement_nav.py + tests/test_reconciliation_override.py + tests/test_asset_structure_coverage.py + tests/golden_report.py + tests/test_golden_report.py + tests/golden/report_fingerprints.json + 回归证据 _recursion_reg_{NBIS,PLD,AMT,XOM}.txt)
- [x] Files modified recorded (config.py / models/router.py / models/__init__.py / classification/classifier.py / data/reconciliation.py / data/models.py / data/validator.py / reporting/dashboard.py / valuation/wacc.py / data/providers.py / tests/conftest.py)
- [x] Decisions documented (新增 Decision 014 Replacement NAV 覆盖率锚 / 015 对账双模反向校验 / 016 golden diff 工程化 / 017 Beta 单一出口；对应 DECISIONS.md ADR-017/018/019 + ADR-011 修订)
- [x] Blockers documented (Session #10 五个缺陷从 Known Issues → ✅ Resolved；🟡 Minor blocker 保持不变)
- [x] Next task assigned (Next Immediate Task 保持不变：特征补全 + 标签纠错 → v2.2 重训 → sanity≥90%)
- [x] Change log updated (本节 Session #10 完整记录 + CHANGELOG.md `## [Unreleased] — 2026-11-03 (Session #10)` 条目)
- [x] Session memory updated (新增 discoveries 19/20/21/22 + Lessons learned 14/15/16 + Useful references golden/ReplacementNAV/override 锚点)
- [x] CHANGELOG.md 更新 (Session #10 Added/Changed/Fixed 三段)
- [x] DECISIONS.md 更新 (新增 ADR-017/018/019 + 修订 ADR-011)
- [x] pytest 回归验证 (tests/* 全部 **78/78 passed**)
- [x] 端到端验证 (golden 整篮 9 只 defect-free；NBIS 5/6 解算 + Replacement NAV $11.13；PLD 对账自动修正渲染；AMT REIT NAV 4/4；XOM Energy 5/5)

If every item is checked,

The project is safe for another AI Agent to continue immediately.

### Session #11 (2026-11-03 — 覆盖率第二条腿: EV/Sales + 单位经济学)

- [x] Completed task recorded (✅ Session #11: 重资本高增长/亏损期标的引入 EV/Sales + 单位经济学模型族（earnings-power 锚）；NBIS 覆盖率 5/6 → 6/7；固定 APPROXIMATE 诚实标注；golden 基线刷新)
- [x] Pending tasks updated (Next Immediate Task 保持不变：特征补全 + 标签纠错 → v2.2 重训 → sanity≥90%)
- [x] Current status updated (🟢 Coverage Model Family Completion)
- [x] Files created recorded (models/unit_economics.py + tests/test_unit_economics.py + 回归证据 _recursion_reg_NBIS.txt 重生成)
- [x] Files modified recorded (config.py / models/router.py / models/__init__.py / classification/classifier.py / tests/golden/report_fingerprints.json)
- [x] Decisions documented (新增 Decision 018 EV/Sales + 单位经济学 earnings-power 锚 + 固定 APPROXIMATE；对应 DECISIONS.md ADR-020)
- [x] Blockers documented (新增 Session #11 #1 IQR 一致性降级 = By Design；Session #11 #2 派生代理 = Open/By Design；🟡 Minor blocker 保持不变)
- [x] Next task assigned (Next Immediate Task 保持不变：特征补全 sector/industry + interest_to_revenue 重算 → AVGO 标签纠错 → v2.2 重训 → sanity≥90%)
- [x] Change log updated (本节 Session #11 完整记录 + CHANGELOG.md `## [Unreleased] — 2026-11-03 (Session #11)` 条目)
- [x] Session memory updated (新增 discoveries 23/24 + Lessons learned 17 + Useful references unit_econ 锚点)
- [x] CHANGELOG.md 更新 (Session #11 Added/Changed/Baseline 三段)
- [x] DECISIONS.md 更新 (新增 ADR-020)
- [x] pytest 回归验证 (tests/* 全部 **90/90 passed**，78 → 90，+12 用例)
- [x] 端到端验证 (NBIS 6/7 解算；`EV/Sales (Unit Econ)` $27.02；golden 整篮 9 只 defect-free；golden 基线已刷新)

### Session #12 (2026-11-03 — CRWV 递归自我改进 3 轮)

- [x] Completed task recorded (✅ Session #12: CRWV 递归 3 轮——Round 1 规则分类路径补「资产轻原型冲突→AI/Cloud 重路由」（对齐 ML 路径）+ hybrid 分支渲染重路由标注；Round 2 一句话结论「中位 vs DCF 基准方向冲突」显式命名（不做平均）+ 修正自持基期口径；Round 3 ReverseDCF 成熟稳态隐含营收 CAGR 落结构化字段 + APPROXIMATE 标注 + `_gap_section` 方向文案 bug 修复；新增 CRWV fixture)
- [x] Pending tasks updated (Next Immediate Task 保持不变：特征补全 + 标签纠错 → v2.2 重训 → sanity≥90%；新增可选加固方向：把「渲染层口径冲突」纳入 `check_invariants()` 声明式检查)
- [x] Current status updated (🟢 Prototype Re-route + Lens-Conflict Naming + Derived-Value Structuring)
- [x] Files created recorded (_recursion_run.py + 回归证据 _recursion_crwv_round0..3.txt)
- [x] Files modified recorded (data/providers.py / classification/classifier.py / reporting/dashboard.py / reporting/verdict_intuition.py / models/reverse_dcf.py / analysis/expectation.py)
- [x] Decisions documented (新增 Decision 019 命名矛盾不平均 / 口径同基 / 派生量结构化；对应 DECISIONS.md ADR-021)
- [x] Blockers documented (新增 Session #12 #1 WACC 行业 sanity 未随原型重路由 = Open；Session #12 #2 fingerprint business_type 保留原始标签 = By Design；🟡 Minor blocker 保持不变)
- [x] Next task assigned (Next Immediate Task 保持不变：特征补全 sector/industry + interest_to_revenue 重算 → AVGO 标签纠错 → v2.2 重训 → sanity≥90%)
- [x] Change log updated (本节 Session #12 完整记录 + CHANGELOG.md `## [Unreleased] — 2026-11-03 (Session #12)` 条目)
- [x] Session memory updated (新增 discoveries 25/26/27 + Lessons learned 18/19 + Useful references CRWV/recursion 锚点)
- [x] CHANGELOG.md 更新 (Session #12 Added/Changed/Fixed 三段)
- [x] DECISIONS.md 更新 (新增 ADR-021)
- [x] pytest 回归验证 (tests/* 全部 **90/90 passed**，每轮后各跑一次)
- [x] 端到端验证 (CRWV 4 轮 `_recursion_run.py` exit=0；`check_invariants()` DEFECTS 4 轮均为空；Round 3 `隐含营收 CAGR: 26.4%` 已落字段 + 方向文案正确)

### Session #13 (2026-11-03 — SOFI 递归自我改进 3 轮)

- [x] Completed task recorded (✅ Session #13: SOFI 递归 3 轮——Round 1 银行 DDM/RIM 统一 β 出口 `resolve_effective_beta()` + 同源 Rf/ERP + `_BANK_KE_BAND`；Round 2 金融情景改走 Bank RIM（`_run_financial_scenarios`）消除与主模型口径矛盾 + 敏感性金融守卫；Round 3 peer 倍数置信度边界 `<=` 修复（`_PEER_MULTIPLE_CONF_FLOOR`）)
- [x] Pending tasks updated (遗留 Known Issues #13-4 SOFI hybrid/SOTP 未触发（数据驱动）；Next Immediate Task 保持不变：特征补全 + 标签纠错 → v2.2 重训 → sanity≥90%)
- [x] Current status updated (🟢 Financial-Model Caliber Unification + Financial Scenario (Bank RIM) + Confidence-Boundary Guard)
- [x] Files created recorded (回归证据 `_recursion_sofi_round1/2/3.txt` + 跨标的 `_recursion_jpm_round3.txt`；本次无新增源码文件)
- [x] Files modified recorded (models/bank.py / analysis/scenario.py / reporting/dashboard.py / models/multiples.py / tests/golden/report_fingerprints.json)
- [x] Decisions documented (新增 Decision 020 金融情景必须走适配主模型 / 021 封顶到边界值用闭区间；对应 DECISIONS.md ADR-022/023)
- [x] Blockers documented (Session #13 #1/#2/#3 → ✅ Resolved；#4 hybrid/SOTP 未触发 = 🟡 Open 数据驱动；🟡 Minor blocker 保持不变)
- [x] Next task assigned (Next Immediate Task 保持不变：特征补全 sector/industry + interest_to_revenue 重算 → AVGO 标签纠错 → v2.2 重训 → sanity≥90%)
- [x] Change log updated (本节 Session #13 完整记录 + CHANGELOG.md `## [Unreleased] — 2026-11-03 (Session #13)` 条目)
- [x] Session memory updated (新增 discoveries 28/29/30 + Lessons learned 20/21 + Useful references scenario/bank/multiples 锚点)
- [x] CHANGELOG.md 更新 (Session #13 Added/Changed/Fixed + Baseline Verification 四段)
- [x] DECISIONS.md 更新 (新增 ADR-022 金融情景口径 / ADR-023 封顶边界守卫)
- [x] pytest 回归验证 (tests/* 全部 **90/90 passed**，每轮后各跑一次)
- [x] 端到端验证 (SOFI 3 轮 + JPM round3 `_recursion_run.py` exit=0；`check_invariants()` DEFECTS 均为空；golden 基线 `UPDATE_GOLDEN=1` 重生成，JPM Bank RIM 漂移已审阅)

### Session #14 (2026-11-03 — 口径契约化 + 封顶审计系统化 + 渲染层口径冲突 invariant + 金融运营情景)

- [x] Completed task recorded (✅ Session #14: ① 口径契约 `valuation/caliber.py` + dashboard 消费；② M-15 封顶审计三层（含跨文件 Part C，捕获并修复 `models/sotp.py` 跨文件漏检）；③ M-12 invariant #6 + 指纹 `caliber`/`scenario_calibers`；④ M-16 阈值具名锁定 `HYBRID_FIN_TO_TECH_FLOOR`；⑤ 金融情景 ke + 经营性 ROE 双驱动)
- [x] Pending tasks updated (TODO.md M-12/M-15 → DONE，M-14 → DONE，M-16 → PARTIAL（待 H-03 补特征后复评）；Next Immediate Task 保持不变：特征补全 + 标签纠错 → v2.2 重训 → sanity≥90%)
- [x] Current status updated (🟢 Caliber Contract + Systematized Cap-Boundary Audit + Render-Layer Caliber Invariant + Financial Operating Scenario)
- [x] Files created recorded (valuation/caliber.py + tests/test_cap_boundary_guard.py + tests/test_hybrid_threshold_lock.py；回归证据 `_recursion_sofi_round3.txt`/`_recursion_jpm_round3.txt` 重生成)
- [x] Files modified recorded (reporting/dashboard.py / analysis/scenario.py / models/bank.py / models/sotp.py / classification/ml_classifier.py / tests/golden_report.py / tests/golden/report_fingerprints.json)
- [x] Decisions documented (新增 Decision 022 口径契约 / 023 封顶审计；对应 DECISIONS.md ADR-024/025)
- [x] Blockers documented (Session #14 #1/#2/#3 → ✅ Resolved；#4 封顶审计 Part B 字面量误报 = 🟡 By Design；Session #13 #4 = 🟡 Open 数据驱动；🟡 Minor blocker 保持不变)
- [x] Next task assigned (Next Immediate Task 保持不变：特征补全 sector/industry + interest_to_revenue 重算 → AVGO 标签纠错 → v2.2 重训 → sanity≥90%)
- [x] Change log updated (本节 Session #14 完整记录 + CHANGELOG.md `## [Unreleased] — 2026-11-03 (Session #14)` 条目)
- [x] Session memory updated (新增 discoveries 31–35 + Lessons learned 22–25)
- [x] CHANGELOG.md 更新 (Session #14 Added/Changed/Fixed + Baseline Verification 四段)
- [x] DECISIONS.md 更新 (新增 ADR-024 口径契约 / ADR-025 封顶审计)
- [x] pytest 回归验证 (tests/* 全部 **95/95 passed**，90 → 95，+5 用例：封顶审计 3 + hybrid 锁定 2)
- [x] 端到端验证 (SOFI / JPM round3 `_recursion_run.py` exit=0；`check_invariants()` DEFECTS 均为空；`caliber='ke'` == `scenario_calibers=['ke']`；金融情景驱动「ke ↑ + 经营性 ROE ↓」生效；golden 基线 `UPDATE_GOLDEN=1` 重生成，仅新增 2 字段漂移已审阅)
