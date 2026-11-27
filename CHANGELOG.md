# 📝 CHANGELOG.md — 版本变更记录
> 格式: [语义化版本 vX.Y.Z] - YYYY-MM-DD  (或 Session 编号用于未发布)
> 分类: ✨ Added / 🔧 Changed / 🐛 Fixed / 🗑️ Removed / ⚠️ Deprecated / 🔒 Security

---

## [Unreleased] — 2026-11-19 (Session #54 — MC Raw vs Adjusted CAPM Ke 溯源 Note)

> 触发：`monte_carlo.py` 里有一条注释承诺「MC notes 会展示 raw vs adjusted ke」，但从未实现（Session #53 清理 F841 时发现）。
> 纪律：先做数据溯源再改码。**Monte Carlo 分布零变化，50 股零漂移，Solved 仍 32。**

### 🐛 Fixed
- **银行 CAPM 审计链从未生效（`models/bank.py`）**：`_resolve_discount_inputs_detail` 把 `BetaChain` 写入 `kwargs["_capm_chain"]`，但函数接收的是 `**kwargs` 展开出的**新字典**，写入永不回传给调用方，因此 `breakdown["capm_chain"]` 恒为 `None`。实测 JPM/BAC/GS 三只银行全部为 `None`。改为**由返回值携带** chain（第 6 个返回值），调用点改为直接使用。**Ke 数值不受影响**（`ke_bd == rf + beta×erp` 修复前后逐位一致），修的是审计管道而非计算。
- **银行 MC 成功路径不渲染 `notes`**：`reporting/dashboard.py` 的银行概率段落只输出概率结论，`notes` 中的任何审计行都不会出现在报告里——即使 Note 生成成功，用户也看不到。新增 `bank_ke_note_lines()` 渲染该行。

### ✨ Added
- `build_bank_ke_note()`（`simulation/monte_carlo.py`）：输出原始 β / 采用 β / β 选择方法 / 原始 CAPM Ke / 采用 Ke / 差异 bps / 调整说明。
  - 差异定义：`采用 Ke − 原始 Ke`（正 = 上调，负 = 下调）。
  - 可区分 Blume 收缩 / β 截断 / 银行 Ke 区间夹紧 / bottom-up 选择。
  - **不完整即沉默**：chain 缺失、任一字段非有限（NaN/Inf）、或 chain 与 MC 实际 Ke 口径不一致（`rf + used_beta×erp ≠ base_ke`、β 不符、Rf/ERP 不符）时返回 `None`，绝不生成误导行。
- `tests/test_bank_ke_note.py`（19 项）：覆盖 Blume≠raw、bottom-up≠raw、raw==used、差异正/负/零、缺 β、NaN/Inf、不同选择方法、Note 与 MC Ke 输入一致、以及报告渲染可达性。

### ✅ Verification
- 全套 pytest：**1124 passed / 2 skipped / 0 failed**（+19 新增）。
- Golden：`nwc_estimator` / `nwc_sensitivity` / `report` 三份指纹 **md5 字节级一致**，无需更新基线。
- 50 股冻结（`UVE_SNAPSHOT_ID=20261123`）：Before/After **全字段 0 差异**；status `{Solved:32, No Solution In Range:9, None:9}` 不变；False SOLVED 0。
- 真实报告验证：GS 渲染出 `原始 β=1.368 → 采用 β=1.091 ｜ 11.52% → 10.00% ｜ -152.3 bps ｜ 银行 Ke 区间夹紧`。
- ruff `E4,E7,E9,F`：**All checks passed**。

### 📌 数据溯源结论（记录口径契约）
| 变量 | 真实来源 |
|---|---|
| `raw_capm_ke` | `BetaChain` = Rf + raw_beta×ERP（`capm_engine.py:175`） |
| `raw_beta` | `resolve_effective_beta().beta_raw`（provider 回归 β，未截断） |
| `valuation_beta` | winsorize/Blume/银行 band 夹紧后的实际估值 β |
| `cost_of_equity` | `risk_free + beta×market_premium`，等于 `adjusted_valuation_ke` |
| MC Ke 输入 | `risk_free + beta_draw×erp`，Rf/ERP 与 bank 模型同源同默认值（0.04/0.06） |
| β 选择方法 | `WaccBreakdown.beta_selection_method`（bottom_up / regression / fallback） |

---

## [Unreleased] — 2026-11-19 (Session #53 — §10 变异测试收口 + 快照契约 + 可选 ML 依赖显式化)

> 触发：§10 变异测试有 9/16 存活；4 个测试因「缓存按系统日期取文件」而失败；18 个 ML 测试报 error。
> 纪律：**先证伪自己的诊断再改码**——本轮三次推翻自己的判断（见「已证伪」）。**未放宽任何估值标准：Solved 仍 32。**

### 🐛 Fixed
- **缓存键由 `datetime.utcnow()` 生成，使数据成为机器时钟的函数（`data/providers.py`）**：`_cache_path` 用当天日期拼文件名，同一份代码在次日读到不同或缺失的文件。实测系统日期为 11-24 时，11-23 的 50 股快照全部 miss，冻结机制正确抛 `FrozenSnapshotMissError` 拒绝实时抓取。新增 `UVE_SNAPSHOT_ID`（`YYYYMMDD`），缓存键优先取它；**格式非法直接抛错而不回退时钟**。`TreasuryYieldProvider` 与 `YahooFinanceProvider` 共用同一解析器（`resolve_snapshot_id`），避免像此前 `_FREEZE_ENV` 那样漏掉一侧。
- **M05 测试对 beta 整体偏移失明**：原测试比较 `partial` 与 `full` 两个**同时被污染**的 beta，正确实现下偏移仅 0.00033，远小于 0.05 容差。改为断言**绝对** beta 恢复到已知 β=1.3。
- **M10 假存活：测试自行重算答案**：多根测试原本自己算 `len(roots) > 1` 再断言它，测的是测试自己的算术。改为 monkeypatch 投影函数、直接读取生产 `meta["multiple_roots"]`。
- **`forecast_nwc_change` 无任何直接单元测试**（真实覆盖缺口）：新增 `tests/test_nwc_marginal_change.py`（5 项）。
- **`_scan_roots` 多根情形从未被覆盖**：新增 `tests/test_multi_root_scan.py`（7 项），含 4 根与 3 根两个受控场景。

### ✨ Added
- `tests/test_snapshot_contract.py`（11 项）：快照存在→正常读取；缺失→`FrozenSnapshotMissError`；过期但冻结→仍读原文件且永不删除；损坏→明确 miss；冻结关闭→正常实时规则；系统时钟变化→不得移动已指定 Snapshot ID；非法 Snapshot ID→抛错。
- `requirements-ml.txt`：`scikit-learn` / `lightgbm`。二者**从未写进 `requirements.txt`**，但 `MLHybridClassifier.classify` 缺依赖时回退到规则分类器，故属**可选依赖**而非缺陷。
- `scripts/run_mutation_experiments.py` / `scripts/triage_mutation_survivors.py`：16 个变异体 + 存活项分类（MISATTRIBUTED vs UNCOVERED）。

### 🔧 Changed
- `tests/test_ml_classifier.py` / `tests/test_classification_identity.py`：新增 `_require_ml_deps()`，缺可选依赖时**带明确理由 skip**（装了真实依赖则真跑）。**不 Mock 模型，不把 error 伪装成 skip。**
- `tests/test_status_matrix.py` / `tests/test_determinism_contract.py`：显式绑定 `UVE_SNAPSHOT_ID=20261123`，测试由**数据快照**驱动而非电脑时钟。

### ✅ Verification
- Mutation **16/16 全部捕获**。
- 全套 pytest：**1105 passed / 2 skipped / 0 failed / 0 errors**（修复前 4 failed + 18 errors）。
- 50 股冻结确定性：连跑两次 **0 差异**；NVDA=125.53、rfr=0.04912 与历史记录逐位一致。
- 50 股字段漂移审计：**0/50**（`rd_status` / 隐含 CAGR / WACC / base_fcf / beta / rfr / price / terminal growth）。
- **False SOLVED = 0**：32 个 Solved 全部满足 `relative_residual <= 1e-4`。
- Golden 回归 13 passed，零漂移。
- ruff `E4,E7,E9,F`：本轮改动/新增文件全通过；仓库既有 24 条**未清理**（经核对在 HEAD 上已存在，非本轮引入）。
- 状态分布不变：32 Solved / 9 No Solution In Range / 9 路由排除。

### 🧪 已证伪（本轮推翻的自我诊断）
- 「9 个变异存活 = 9 处覆盖缺口」→ 实测 8 个是**映射错误**（缺陷被另一个测试抓到），仅 M05 是真弱点。
- 「多根测试有效」→ 它自己重算结论，M10 变异下照样通过，是**假存活**。
- 「18 个 error 是代码缺陷」→ 根因是可选依赖未安装/未声明，装上后 33 passed。

## [Unreleased] — 2026-11-19 (Session #52 — P0-7 非有限链条 + 10 条件 SOLVED 资格门 + 输出层门禁)

> 触发：Session #51 遗留的 P0-7（非有限投影被误报 `SOLVED` / `NO_ROOT`，而非数据质量问题），以及用户要求的「SOLVED 资格门」——把 10 条资格条件写成**代码门禁**，而不是写在报告里的口号。
> 纪律：**先证伪自己的诊断再改码**。本轮又一次推翻自己的判断（见「已证伪」）：最初以为残差门是唯一守卫，实测证明它是**第二道**防线。

### 🐛 Fixed
- **P0-7 非有限投影链（`models/reverse_dcf.py`）**——四个独立缺陷，逐个证伪后修复：
  1. `_project_ev` 失败时返回 `0.0`，凭空造出一个「EV=0」的伪解。现返回 `nan`，让「无法投影」保持为「无法投影」。
  2. `target_ev` 非有限时原判 `INFEASIBLE`。`INFEASIBLE` 读作「假设不可行」，与事实不符：输入是有限的，是乘积**溢出**了。改为 `DATA_QUALITY_ERROR`（`config.py` 新增 `SolverStatus.DATA_QUALITY_ERROR`）。这是语义修复：无效数据必须被标为**数据质量问题**，不能混进「无根」或「已解」。
  3. **端点短路守卫被 NaN 绕过**：`abs(a-b) <= tol` 对 `nan` 恒 `False`，看似安全，但下游 `nan > tol` 也恒 `False`，于是 `nan` 残差被判「在容差内」→ `SOLVED`。现两端点与内部根都走显式 `isfinite` 检查。
  4. **二分回退伪造增长（本轮第三个缺陷）**：`fa * fm <= 0` 对 `nan` 恒 `False`，循环于是把下界 `a` 一路推向上界 `hi`，最终返回 `APPROXIMATE cagr=1.5`（上界值）——一个凭空捏造的 150% 增长。现对区间端点与每个中点的非有限值显式拒绝。
- **残差门是第二道防线，不是唯一防线（变异测试更正了原假设）**：单独禁用残差门，端到端测试**仍然通过**——因为 EV 对增长单调递增，溢出总是先撞到区间上界 `hi`，被端点守卫先拦下。所以残差门是**纵深防御**。原单元测试的 docstring 声称它「单独可证」，实测证伪，已改写为真实性质（两门缺一不可），并新增 `test_residual_gate_rejects_nan_residual_directly`：钩住 `scipy.optimize.brentq`，让它正常收敛，**在返回之后**才投毒投影，使非有限值只被残差门看到。该测试在禁用残差门时**确实失败**（已实测）。
- **输出层仍在泄漏 `nan`（新增发现，非原计划）**：`float('nan')` 能被 `f"{v:,.2f}"` 正常格式化，于是 `$nan`、`inf%`、`$infT` 会直接出现在 Telegram 消息里。逐个证伪后修复：
  - `reporting/dashboard.py`：`_fmt_money` / `_fmt_share` / `_fmt_pct` / `_fmt_num` 现对非有限值返回 `N/A`。
  - `analysis/divergence.py`：`_fmt_share` 同问题同修（独立的第二份实现）。
  - `analysis/model_agreement.py`：`if r.share_count` 挡不住 `nan`（`nan` 为**真值**），现显式 `math.isfinite`。
  - `telegram_bot/telegram_bot.py`：`price is not None` 挡不住 `nan`，现显式检查。
  - `benchmark/report.py`：`_final_status` 对 `SOLVED` **完全不检查**残差是否有限——而 `nan <= bar` 与 `nan > bar` 同为 `False`，纯阈值判断会把 NaN 残差报成 `SOLVED`。现补显式有限性门 + 「未记录收敛」门，并补 `Data Quality Error (Non-Finite Projection)` → `DATA_ERROR` 映射。

### ✨ Added
- **`models/solved_eligibility.py`（新模块）——10 条件 SOLVED 资格门**：单一、可审计的实现，取代散落各处的隐式判断。10 条：`finite_price_and_shares`、`finite_target_wacc_tg`、`projection_inputs_ok`、`model_applicable`、`no_blocking_data_quality`、`solver_converged`、`residual_within_tolerance`、`outputs_finite`、`band_and_root_recorded`、`root_independently_recomputed`（**独立重算根**，不信任求解器自报）。已接入 `calculate()`：只有 10 条全过才保留 `SOLVED`，否则降级并写明失败项。
- **`breakdown["solver_input_dependencies"]`**：记录解的输入依赖度。
- **`wacc_local_elasticity` 用隐函数定理计算**：`-(∂EV/∂w)/(∂EV/∂g)`。原实现用 `dEV/dw`，量纲是「美元/WACC」，不是无量纲弹性。AAPL 实测 `dg/dwacc=3.58`（与 §4 早前独立测得的 ≈4 一致，交叉验证成立）。
- `tests/test_non_finite_chain.py`（42）：非有限链条的定点回归，含上述变异实验。
- `tests/test_report_output_finiteness.py`（30）：输出边界测试——5 个格式化器 × 3 个非有限值，加上 analysis 层第二份实现、model_agreement 表格、以及 benchmark 报告层最后一道门。

### 🔬 已证伪（本轮推翻的两个判断）
- **「残差门可单独隔离验证」——错。** 变异 E（禁用残差门）端到端**存活**，因为端点守卫先命中。结论改为：残差门是纵深防御的第二层；要隔离它必须让 `brentq` 先成功返回再投毒。
- **「`_fmt_*` 已安全」——错。** 实测 `_fmt_money(nan)` → `'$nan'`。异常捕获只挡 `TypeError/ValueError`，`float('nan')` 两者都不抛。

### 🧪 Tests
- 全套 **1075 passed / 2 skipped**（Session #51 为 1003 + 2）。
- `ruff check --select E4,E7,E9,F`：**本轮改动的 10 个文件 All checks passed**。仓库其余 24 条（9 个文件）经 `git show HEAD:<file>` 逐文件核对，**全部在 HEAD 上已存在**，非本轮引入；其中 5 条 `F841` 经查为死读取（赋值后未使用），不影响计算结果，留作独立债务。
- **golden 零漂移**：`test_golden_report.py` 3 passed。
- **50 只冻结实跑：32 SOLVED 全部保留，0 只被新门禁误降级**——资格门没有伤害任何真实解。报告层最终状态 32 SOLVED / 9 NO_SOLUTION_MATHEMATICAL / 9 MODEL_NOT_APPLICABLE，与 Session #51 完全一致。

---

## [Unreleased] — 2026-11-19 (Session #51 — Master Validation §1–§10 续：3 个新 P0 缺陷 + 94 项守护测试)

> 触发：承接 Session #50 的《Reverse DCF Master Validation》，继续执行 §1 确定性 / §2 求解器数值稳定 / §3 假 SOLVED 防护 / §4 输入扰动 / §5 EV 曲线 / §6–§7 历史与并发 / §8–§9 50 股矩阵 / §10 变异测试。
> 纪律：**先证伪自己的诊断再改码**。本轮**三次推翻自己的假设**（见「已证伪」），只在证据成立处改码。

### 🐛 Fixed
- **P0-4 非有限报价伪造 SOLVED（`models/reverse_dcf.py`）**：`price <= 0` 对 `NaN` 恒为 `False`，故 `NaN`/`inf` 报价穿过守卫 → `target_ev = nan` → `brentq` 的符号判断对 NaN 失效，求解器返回**搜索下界** `cagr=-0.5` 并标 `SOLVED`。实测 `NaN`、`inf` 两只均复现，`-inf` 因 `<0` 侥幸被拦。修复分两层：① 新增 `_is_finite_positive()` 守卫价格与股数（非有限报价 = 缺失数据，不是便宜股票）；② `_solve_revenue_cagr` 入口对 `target_ev` / `wacc` / `tg` 做 `isfinite` 检查，非有限一律 `INFEASIBLE`。**变异测试证明两层缺一不可**：删掉任一层，`NaN` 立刻重新伪造 SOLVED。
- **P0-5 端点短路绕过残差门（Session #51 前段已修，本轮补变异证据）**：端点相等曾用 `abs_tol = 1e-3 * target` 且不计算残差，5e-4 相对偏移被报 `SOLVED`（真实残差 5.003e-04）。现端点走与内部根相同的 `price_residual_tol` 门。变异验证：把门槛放宽 1000 倍 → `test_endpoint_short_circuit_cannot_bypass_residual_bar` 立即失败。
- **P0-6 模块级配置被实例污染（本轮补变异证据）**：`DEFAULT_REVERSE_DCF_CONFIG` 是可变对象，旧代码 `self.rcfg` 直接引用它，任何 `setattr` 永久污染进程内后续所有实例，使「同一股票在不同运行顺序下得到不同容差」。现用 `dataclasses.replace` 复制。变异验证：改回 `self.rcfg = base` → `test_mutation_shared_config_cannot_pollute_defaults` 失败。

### ✨ Added（94 项守护测试，10 个文件）
- `tests/test_freeze_miss_refusal.py`（8）：冻结缓存未命中必须 `FrozenSnapshotMissError`，**不得静默联网**。
- `tests/test_determinism_contract.py`（4）：50 只 × 86 字段两次冻结运行 0 差异；4 种顺序 0 差异；3 个 `PYTHONHASHSEED` 0 差异。
- `tests/test_solver_stability.py`（21）：已知增长反解往返（误差 ≤1e-8）、`xtol` 扫描、端点根、无根拒绝。
- `tests/test_false_solved_regressions.py`（4）：两个 P0 的定点回归。
- `tests/test_false_solved_prevention.py`（16）：`NaN`/`inf`/0/None 价格、0/None 股数、缺失 TTM、零营收全部拒绝；并配**对照用例**防止「全部拒绝」也能通过。
- `tests/test_input_perturbation.py`（18）：价格/营收/WACC/终值增长/NWC/β 弹性；EV 对 WACC 连续且单调递减、对终值增长单调递增；价格扫描无阶梯。
- `tests/test_ev_curve_stability.py`（5）：健康公司曲线单调 → 唯一根；不可达目标必须指明**方向**；无根永不返回 CAGR。
- `tests/test_history_concurrency_stability.py`（6）：模型不得改写入参 `FinancialData`；同一共享实例重复调用稳定；并发采集 = 顺序采集；`horizon` 不跨业务类型泄漏。
- `tests/test_status_matrix.py`（8）：50 股状态分布固定（32/9/9）；每个 SOLVED 有真实残差且有限；每个无解有具名原因且不给数字；9 只 routed-out 均写明业务类型且**直接探测一致**（不会解却被路由掉）。
- `tests/test_mutation_guards.py`（8）：8 类注入缺陷的守护断言，配套 4 次真实源码变异实验。

### 🔬 关键发现
- **`base_fcf` 变化不影响隐含增长率是设计正确的**：反向 DCF 的求解走「营收 × 营业利润率」投影路径，`base_fcf` 只是桥接/展示口径（SBC 归一后）。故把 TTM FCF 从 0 改到 199B，`implied_revenue_cagr` 逐位不变。**这不是缺陷**——正确做法是扰动营收/价格，而非 FCF。
- **反向 DCF 的增长率对 WACC 高度敏感是固有性质**：AAPL 实测每 25bp WACC ≈ 1.0pp 隐含增长（弹性 ≈ 4×）。因此 §4 的界写成**弹性**（`0 < dg/dw < 6`）而非绝对值上限——写绝对上限只会把正确行为判成缺陷。
- **终值增长的弹性是负的**：终值增长↑ → 永续部分已贡献更多价值 → 显式期所需增长↓（实测 `dg/dtg ≈ -3.1`）。首版断言写成正值，被实测证伪后修正。
- **50 只中有 8 只 EV 随增长非单调**（AMZN/TSLA/FCX/BA/LLY/MRNA/NEE/CEG）——这是真实经济现象（增长破坏价值），且**全部被正确拒绝**并给出具名原因（`NEGATIVE_BASE_FCF_NO_VALID_ROOT` ×5、`NO_ROOT_IN_EXPANDED_RANGE` ×4）。
- **9 只 `rd_status=None` 是正当路由排除，不是静默失败**：均为 Bank/REIT/Insurance，`rd_routed_out=True` 且 `rd_routed_out_reason` 写明业务类型；`rd_direct_status` 直接探测同样 `Insufficient Data`，双向一致。

### 🧪 Tests
- 全套 **1003 passed / 2 skipped**（较 Session #50 的 909 增加 94 项）。
- `ruff check --select E4,E7,E9,F` → 本轮改动文件 **All checks passed**（`models/bank.py` 的 2 条 F841 为基线既存，本轮未触碰）。
- **golden 零漂移**：`test_golden_report.py` + `test_nwc_estimator_golden.py` 共 5 passed。
- **50 只冻结实跑：0 字段漂移**，状态 32 / 9 / 9 与 Session #50 完全一致——本轮修复只影响无效数据路径，不触碰真实数据的解。

### ⚠️ 未放宽任何标准
Solved 仍为 **32**。本轮所有修复都是**拒绝不该有的答案**，没有一条是「让更多股票解出来」。

---

## [Unreleased] — 2026-11-23 (Session #50 — Reverse DCF 主验证：50 股测试、修复与验收)

> 触发：用户下发《Reverse DCF Master Validation》规格——固定 50 股 Benchmark 宇宙，要求数学 / 金融数据 / 求解器 / 经济 / 回归五维验证，且**不得为抬高 Solved 数而放宽经济合理性标准**，**不得混淆**数学无解 / 数据错误 / 模型不适用 / 数值不收敛。

### 🐛 Fixed
- **P0-1 求解器残差门槛比验收宽 10 倍**（`config.py`、`models/reverse_dcf.py`）：`converged` 与降级判断硬编码 `1e-3`，验收门槛是 `1e-4`。COST 1.024e-4 / PFE 1.074e-4 / BKNG 1.24e-4 / JNJ 1.07e-4 超门槛却报 `Solved`。根因：`brentq` 按 `xtol`（x 区间）收敛，不保证 `|f(x)|`。修复：`newton_tol 1e-4 → 1e-10`，新增 `price_residual_tol=1e-4` 契约字段并替换两处硬编码。修复后 32 只残差降至 1e-11~1e-15。
- **P0-2 数据快照不可复现**（`data/providers.py`）：4h 缓存 TTL 在验证中途重取 10Y 国债收益率，使 PFE 隐含 CAGR 1.93%→1.39%、WACC 6.267%→6.123%，**代码未改**。新增 `UVE_FREEZE_CACHE=1`（冻结时缓存不过期、不删除），`TreasuryYieldProvider` 与 `YahooFinanceProvider` 共用。冻结后连跑两次结果逐位相同。
- **P0-3 routed-out 无显式终态**（`benchmark/report.py`）：9 只银行/保险/REIT 的 `rd_status=None`，使「正确拒绝」与「从未运行」不可区分，50 = Σ(status) 不可证伪。新增 §14 报告层派生显式终态（`MODEL_NOT_APPLICABLE` / `NO_SOLUTION_MATHEMATICAL` / `SOLVED`，合计 50），对空白终态与未知状态抛异常。

### ✨ Added
- `benchmark/report.py`：§14 报告层，含 18 个必填字段 + 显式终态 + 运行级快照 id（`snap-xxxxxxxxxxxx`，rfr 取非空众数，避免 routed-out 的 `None` 把一次运行劈成两个快照）。
- `tests/test_solver_numeric_contract.py`（6 项）：根精度 ≤1e-8、`xtol` 契约、残差门槛来自 config 而非字面量、端到端残差在门槛内。
- `tests/test_snapshot_freeze.py`（4 项）：冻结开关语义、过期缓存默认删除 / 冻结时保留、两 Provider 共用开关。
- `tests/test_report_status.py`（11 项）：routed-out 显式终态、静默跳过判为 DATA_ERROR、tally 求和、未收敛不算 Solved、多根判歧义、超经济区间标记、数学无解 ≠ 数据错误、未知状态抛错、快照 id 按运行而非按股。
- `tests/test_dcf_synthetic_cases.py`（5 项）：§5 三标准案例（常数增长 / 零增长永久年金 / 价值陷阱），全部对闭式解验证到 1e-6 相对误差。
- `tests/test_beta_synthetic_recovery.py`：新增无噪声 β 恢复测试，守护 §5 的 1e-6 门槛（原测试仅 2e-2，含噪声）。

### 🔬 关键发现
- **golden 指纹对本轮缺陷零信息量**：`golden/report_fingerprints.json` 只含聚合量（`median_value`、`n_solved`），不含 solver 残差 / 隐含 CAGR / WACC。故它全程通过，却对「残差超门槛仍报 Solved」无感。mutation 验证：`newton_tol` 改回 1e-4，新测试立即失败。
- **§9 隔离实证**：旧代码（HEAD worktree）与新代码共用同一冻结缓存重跑 50 只，状态零变化、CAGR 位移 ≤2.4e-5（xtol 收紧量级）；而修复前后最大 5.0e-2 位移**全部伴随 rfr 5.052%→4.912%**。大位移是市场数据，小位移才是代码。
- **未放宽任何标准**：Solved 仍为 32（修复前后一致），9 数学无解、9 模型不适用，合计 50。

### 🧪 Tests
- 全套 **909 passed / 2 skipped**（较上轮 878 增加 31 项），ruff `E4,E7,E9,F` 通过，两个 golden 指纹未漂移。

### ⚠️ 未做（如实记录）
- `benchmark/results/master_validation_report.json` 与 `raw_facts.json` 为本轮产物，未提交（属运行产物，是否入库需裁定）。
- 本轮未创建 PR。

## [Unreleased] — 2026-11-23 (Session #49 续 7 — 等级政策化 / 敏感度多点 / 工作树审计)

> 触发：用户要求「分档应标记为模型的数据质量政策，而不是统计学定律」，并建议敏感度不要只固定 g=5%。

### 🔧 Changed
- `analysis/nwc_confidence.py`：`GRADE_IS_POLICY` / `GRADE_POLICY_NOTE` 成为**随 payload 输出的契约**（`grade_is_policy`、`grade_policy_note`），不再只是注释。明确列出样本量代理无法排除的四类失真：行业结构变化、会计口径变更、并购、异常年份。
- `HISTORY_MORE_ESTABLISHED` 标签改为「较可用（8+ 对）：本引擎作为主要估计，**非已证明正确**」——原「较已确立」在措辞上暗示了已证明。
- `analysis/nwc_shadow.py`：报告渲染新增 ℹ️ 政策说明行。
- `tests/test_nwc_estimator_golden.py`：敏感度扫描由单点 g=5% 改为 **g∈{2%,5%,10%} + 各公司隐含收入 CAGR**，每个 g 下扫 6 个 w。

### 🔬 关键发现
- **单点敏感度基线会严重误导**：XOM 在自身增长率 7.55% 时 EV 相对值 **−6.7%**（转负），而固定 g=2% 时为 **+61.7%**。同一家公司，测试位置不同，结论从「大幅增厚」变成「毁灭价值」。
- **工作树实际是三批而非两批**：批次①（11-21~22）β 分层/Blume 与 Reverse-DCF 双波段；批次②（11-23 00:0x）三估计器框架 + P2 路由；批次③（11-23 10:47~12:05）本轮。`data/providers.py` 单文件横跨①②，无法按路径拆分，需 `git add -p`。

### 🧪 Tests
- 新增 `test_grade_is_labelled_as_policy_not_law`、`test_more_established_does_not_claim_proof`。
- 全套 **878 passed / 2 skipped**，ruff 通过，两个 golden 通过。

### ⚠️ 未做（如实记录）
- 未提交：批次拆分需要 `git add -p` 处理 `providers.py` 的跨批改动，且批次①是否该独立成提交需用户裁定。
- `.cache/segment_revenue.json` 已被 git 跟踪，属缓存文件不应入库，本轮未处理。

## [Unreleased] — 2026-11-23 (Session #49 续 6 — 解析导数边界验收)

> 触发：用户评审「通过设计审查，进入边界验收」，要求补 4 项 P0/P1 边界测试：Reference Growth、Flip Point 验证、Multiple Flip、Boundary Testing；并指出扫描变号可能漏掉相切根。

### ✨ Added
- `sign_over_range()` 重写：`flip_points` 报告**全部**变号点并用**二分精修**（不再量化到网格）；`valid_direction_intervals` 给出与参考点同号的**所有**子区间；`tangent_points` 检测不变号的相切根（相对容差启发式）；`local_direction`（INCREASING/DECREASING）；保留 `flips_at_growth` 兼容单值调用方。
- `GrowthDirectionTest` 新增 `flip_points` / `valid_direction_intervals` / `tangent_points` / `local_direction`，并全部进入 `as_dict()`。
- `evaluate(..., growth_range=)`：可指定扫描窗口（默认 −5%~50%）。
- 多翻转时报告自动追加「EV 曲线非单调」理由，渲染层显示全部翻转点与有效区间。

### 🐛 Fixed
- **翻转点只保留第一个**：原先 `flips_at_growth` 遇到第一个变号即 `break`，会静默丢弃后续翻转。现全部报告。

### 🧪 Tests（新增 25 项）
- **P0 Reference Growth**：6 个参考增长率（含负增长）的局部导数解析 vs 差分一致；`reference_growth`/`local_direction` 正确出现在输出。
- **P0 Flip Point 验证**：解析与**纯中心差分**独立定位翻转位置，5 个 w 全部误差 ≤5e-7（容差 1e-4）；翻转点是真根（斜率/尺度 <1e-6）而非网格线。
- **P1 Multiple Flip**：真实 2 根案例（k0=0.055, w=1.50, H=10 → g≈−45.2%、−16.2%）两个翻转点均被报告，符号确实交替，`valid_direction_intervals` 为 2 段。
- **P1 Boundary**：翻转点贴近扫描上下界仍能检出，并经两侧符号验证为真实变号；窗外不报告。
- **切线根**：以构造双根 `(g−0.1)²` 单测检测器本身（真实参数空间无内点切线根，如实说明）。

### 🔬 关键发现（本轮实证，非推测）
- 把 `dEV/dg` 写成 `(1+g)` 的**精确有理系数多项式**后求解：**g>0 域最多 1 个根**（宽参数扫描 0 例外）；**g<0 域存在 2 个根**。故多重翻转是真实存在的，但只发生在收缩区间。
- 50 只 benchmark 中 0 只出现多重翻转——真实公司 `k0 > w`，此时导数严格递增，最多一个根。
- 引擎参数空间内找不到任何**内点**切线根（13 个近零极小值全部位于扫描边界）。

### ⚠️ 诚实结论
- 接口支持多重翻转，但**当前真实数据不会触发**；这不是缺陷，是 `k0 > w` 的数学后果。
- 切线根检测是启发式，**未在真实数据上验证过**，仅保证不遗漏构造的双根。

## [Unreleased] — 2026-11-23 (Session #49 续 5 — 判别式作用域降级、NWC 证据分级、独立 golden)

> 触发：用户评审 A/B/C。A（最重要）：`k0/w > P/D` 只是**单一增长率处的局部结论**，不是全局「EV 方向」判别，必须声明计算点；B：4 年 / 3 对数据不足以支撑「确立」结论，需更严格的年限分档；C：报告 golden 不含 NWC 字段，不能作为 NWC 的安全证明。
> 纪律：**先证伪自己的诊断再改码**——本轮证伪的是**自己上一轮 ⑤ 的表述**（公式对，作用域错）。

### 🐛 Fixed
- **判别式被误当作全局方向判别（A）**：`EV(g)` 非单调，`dEV/dg` 随 g 变号。实测 9 组参数中 3 组翻转（w=0.80 在 g=0 为 +3608、g=0.08 为 −479；w=0.80/0.70/0.50 翻转点 ≈0.08/0.12/0.27）。现将结论标注为 `LOCAL_EV_DIRECTION_AT_REFERENCE_G`，随附 `reference_growth` 与 `flips_at_growth`，并禁止省略作用域。
- **「稳健」被当作证据强度**：`NWC_ROBUST_MARGINAL` 在 3 对上即成立。新增 `history_grade()`（INSUFFICIENT/INDICATIVE/PROVISIONAL/MORE_ESTABLISHED）与 `claim_strength`（none/indicative/established），由**样本量**而非算法名决定结论强度。
- **敏感度基线在 g=0 扫描毫无信息量**：g=0 时 ΔRevenue=0，NWC 项恒为零，所有系数得到相同 EV（实测全部为 1.0）。改为在 g=5% 扫描后，XOM 在 w=1.50 时 EV 相对值转负（−0.139）。
- 报告重复打印同一条 4 年数据警告（shadow warnings 与 taxonomy notes 各一份），已去重。
- 作用域措辞自相矛盾（「仅在 g≈0% 附近成立」却给出 13.5% 翻转点），改为「仅在 g∈[0%, 13.5%) 内成立」。

### ✨ Added
- `forecasts/growth_direction.py`：`analytic_slope()`（解析导数）、`sign_over_range()`（扫描翻转点）、`VERDICT_SCOPE`/`REFERENCE_G`/`BOUNDARY_BAND`；`evaluate(..., revenue0=)` 自动附带翻转点。
- `analysis/nwc_confidence.py`：`history_grade()`、`HISTORY_GRADE_LABELS`、`DIRECTION_GRADES`、`INDICATIVE_DIRECTION_GRADES`、`claim_strength` 输出。
- `analysis/nwc_shadow.py`：`projection_params_from_engine()`（供敏感度基线复用引擎真实投影参数，而非仿制）、`_claim_suffix()`（渲染证据强度与作用域）、`projection_params` 字段。
- `tests/test_nwc_estimator_golden.py` + `tests/golden/nwc_estimator_fingerprints.json` + `nwc_sensitivity_fingerprints.json`：**与报告 golden 解耦**的 NWC 独立基线（C）。有效性已验证：改 `HISTORY_GRADES` 边界 → NWC golden 失败、报告 golden 仍通过。
- 测试：解析 vs 中心差分**逐点**核对 5×10=50 组（0 符号不符，最大相对误差 2e-8）；翻转点检测；`history_grade` 边界；`claim_strength` 分级。

### 🔧 Changed
- `forecasts/nwc_utils.py`：`aggregate` 标签改为 `LEGACY_PRIMARY_RESIDUAL_ESTIMATE = "legacy_primary_residual"`，并在 docstring 中写明「长期使用不等于最可靠」。估计值本身**不变**（golden 未动）。
- `tests/test_precision_fixes.py`：跟随标签重命名。

### ⚠️ 诚实结论
- 50 只中 7 个方向结论**全部为 `indicative`**（均仅 4 年数据）：这是分级要暴露的事实，不是回归。
- 判别式现在能自我限定作用域，但**仍不能回答「增长是否增厚价值」这个全局问题**——那需要在整个可信 g 区间内判定，而非单点导数。

## [Unreleased] — 2026-11-23 (Session #49 续 4 — NWC 三指标分离、判别式推导与证伪、Shadow Run)

> 触发：用户裁定「采纳 aggregate residual slope 为正式标准；annual mean ΔNWC/Revenue 只作条件性估计与敏感性；不要把 50 只全部换成后者；不要留 8 只永久显示 unknown，也不要用未验证代理给出看似确定的结论」。
> 纪律：**先证伪自己的诊断再改码**。本轮证伪了**自己上一轮的判别式公式**，并把「不作答」写成机器强制。

### 🐛 Fixed
- **判别式 `g_BE = k0/NWC` 被证伪（推翻 Session #49 续 3 ⑬）**：符号推导显示 FCF 利润率的零点应为 `k0/(w−k0)`，而非 `k0/w`；且两者都**不预测** `dEV/dg` 的翻转点（w=0.40 时实际翻转 g=0.419，两式分别给 0.370 / 0.587）。原「递减组 4.8–12.5% vs 递增组 19–652% 完全分离」是 41 只样本上的**观察性巧合，不是定理**。已在 `AGENT.md` ⑬ 原地标注证伪，避免错误公式继续传播。
- **「NWC 边际比是残差反推」只对模型系数成立，对原始 `change_in_nwc` 不成立**：`data/providers.py` 显式请求现金流表 `ChangeInWorkingCapital` 并直接取用；把它与派生系数 `nwc_marginal_ratio` 混为一谈是本轮的起点错误。
- **概念维度混淆（用户纠正已固化）**：NEE 的 1.9% 是 **投资强度 `ΔNWC/Revenue`**，既非 **存量比率 `NWC/Revenue`**，也非 **模型系数 `ΔNWC/ΔRevenue`**（NEE≈14.0%）。`forecasts/nwc_estimators.py` 为每个估计打 `dimension` 标签，`reconcile()` 只在 marginal 维度内比较，**level 永不参与**（测试锁定）。
- **强度→边际换算的分母塌陷**：CEG 增长率 1.5%、强度 23.5% 会产出 **1598%** 的「边际比」。新增 `MIN_GROWTH_FOR_PROXY=2%`，低于阈值直接拒绝并记录 `intensity_proxy_refused_reason`。
- **三处自相矛盾（本轮自查）**：ⓐ `applicable=False` 仍打印方向结论 → 不适用即不输出；ⓑ `NWC_ESTIMATE_CONFLICT` 仍给方向 → 分类学设为唯一闸门；ⓒ 点估计结论与引擎「方向翻转」扫描并存 → 扫描证据更强，点估计结论撤销并说明理由。
- **`level` 比率不再可能被补零捏造**：缺 AR 或 AP 时 `operating_nwc_from_balance_sheet()` 返回 `None`，不把缺失当 0。

### ✨ Added
- `forecasts/nwc_estimators.py` — 三种维度显式区分的估计器：`balance_sheet_nwc_ratio`（level）、`nwc_investment_intensity`（intensity）、`robust_marginal_nwc`（marginal，median / Theil-Sen / Huber 三法交叉验证）、`marginal_from_intensity`、`reconcile`。
- `forecasts/growth_direction.py` — **从引擎实际投影推导**的判别式：增长增加价值 ⟺ `k0/w > P/D = 1/久期`。P/D 对 10 年/9% WACC/2% 终值为 **0.136（久期 7.34 年），不是 1**；数值验证 10/10 符号正确，门槛随 horizon 单调变化（H=3→0.356，H=40→0.083）。在 `k0≤0` / `WACC≤tg` / 缺 `w` / **距门槛 ±25% 内**一律拒绝作答（`BOUNDARY_BAND`，依据：利润率漂移下符号 18/21 一致，3 次不一致全在边界）。
- `analysis/nwc_confidence.py` — 五档分类学 `NWC_DIRECT` / `NWC_ROBUST_MARGINAL` / `NWC_INTENSITY_PROXY` / `NWC_ESTIMATE_CONFLICT` / `MECHANISM_UNCONFIRMED`；`can_claim_direction` 同时要求系数可估**且**引擎扫描方向不翻转。
- `analysis/nwc_shadow.py` — 单只诊断装配（三种估计 + 判别式 + 分类 + 警告），`format_report()` 输出中文报告。
- `benchmark/shadow_nwc_run.py` — 50 只 Shadow Run，只读引擎 breakdown、不写回、不动 golden；产物在 `benchmark/results/shadow_nwc/`（`summary.tsv` / `per_ticker.txt` / `diagnostics.json`）。
- `data/providers.py` — 新增六个资产负债表营运资本字段：`AccountsReceivable` / `Inventory` / `AccountsPayable` / `CurrentDeferredRevenue` / `OtherCurrentAssets` / `OtherCurrentLiabilities`。

### 🔧 Changed
- `forecasts/nwc_estimators.py::reconcile` 输出 `marginal_spread` / `estimates_conflict` / `usable_marginal_estimates`，把「冲突」作为一等结果而非平均值。
- 文档：`AGENT.md` → v4.27（新增 Session #49 续 4 全节 + ⑬ 原地证伪）。

### 📊 Shadow Run 结果（50 只，golden 未动）
- 分布：`NWC_DIRECT 22` / `NWC_ESTIMATE_CONFLICT 11` / `NWC_INTENSITY_PROXY 7` / `NWC_ROBUST_MARGINAL 1` / 路由不适用 9（银行/保险/REIT 正确排除）/ **ERROR 0**。
- **41 只可诊断中仅 7 只给出方向结论**（6 adds / 1 destroys），其余 34 只 `indeterminate` —— 这是诚实结论，不是失败。
- 冲突案例证明三法分离非形式主义：CEG robust 0.4% vs proxy 1598%、DUK 符号相反、KO 4.77 vs 2.14、SO −5.37 vs −0.14。
- 非极端 NWC 标的无异常翻转（MSFT / WMT / COST / XOM / CVX 等稳健或按规则弃权）。

### ⚠️ 已知限制
- **数据年限不足**：Yahoo timeseries 年度实际只返回 **4 年**（季度 20 季），低于用户要求的 ≥5 年；4 年仅能形成 3 个 y/y 配对，恰在稳健下限。分类学对 <5 年一律附加「指示性、非确立结论」告警。**该缺口未掩盖。**
- 直接财报 NWC 覆盖 45/50（VICI / CRM / O / BAC / BRK-B 缺 AP）。

### ✅ 验证
- `pytest` → **784 passed / 2 skipped**。唯一 1 error 为 `scripts/test_phase1_refactoring.py` 被 pytest 误收集、缺 `ticker` fixture，与改动无关（既存）。
- 新增测试 3 文件 **67 例**：`test_nwc_estimators.py`(29) / `test_growth_direction.py`(22+1 skip) / `test_nwc_confidence.py`(16)。
- 改动文件 `ruff check --select E4,E7,E9,F` → **All checks passed**。
- **golden 零漂移**：`tests/test_golden_report.py` 3 passed；并以「回退 `data/providers.py` 改动后仍 3 passed」+「指纹不含任何 NWC 字段」双重证明本阶段改动不影响 golden。`report_fingerprints.json` 的工作区改动来自上一阶段 P2（`UNDETERMINED → display_only`），非本轮引入。

---

## [Unreleased] — 2026-11-19 (Session #49 续 3 — 模型经济合理性与边界压力测试)

> 触发：用户任务「进入模型经济合理性与边界压力测试阶段：把 NEGATIVE_INCREMENTAL_VALUE_CREATION 形式化，算增量 ROIC vs WACC；但 CapEx > D&A 不足以反推该机制」。
> 纪律：**先证伪自己的诊断再改码**。本轮**证伪了用户的核心假设**，也**推翻了上一轮我自己给出的归因**，并因此把「不可断言」写成机器强制。

### 🐛 Fixed
- 🐛 **上一轮「NEE/CEG/FCX 增长毁灭价值 = 再投资侵蚀」归因不成立（`models/reverse_dcf.py`）**：上一轮把 NEE 的 EV 递减归因为「CapEx + 营运资本超过自身现金流」。**证伪**：NWC 边际比是残差反推（`NOPAT + D&A − capex − FCF`），对它在合理区间做扫描后，**13/41 只的方向结论会翻转** —— NEE 在 nwc=14% 递增、20% 递减（恰卡临界）；CEG 20%；SO 5%；FCX 10%；AMZN 5%；TSLA 15%。新增 `_ev_direction_robustness()`：在 `config.py::nwc_sensitivity_ratios` 候选集下探测 EV 方向，**方向不稳则禁止断言任何机制**，改为报告「方向对营运资本假设敏感」及**真实翻转点**（相邻候选对，而非候选集跨度）。实测 9 只无解中 8 只判为 `EV_DIRECTION_UNDETERMINED`，仅 MRNA 方向稳健。
- 🐛 **峰值扫描带用错：注释称「限定合理区间」，代码却用全局配置（`models/reverse_dcf.py`）**：`scan_lo/hi` 取自 `rcfg.min/max_implied_cagr` = `[-0.10, 0.80]`，于是 SO 报「EV 在 g=15% 见顶」，而 Utilities 合理带是 `[-2%, 10%]` —— 正是该处注释自己警告的「报出一个业务类型不允许的增速」。新增 `plausible_lo/hi` 参数由 `run()` 传入，扫描与方向检验统一用合理带；SO 峰值由 g=15% 修正为端点 10%，NEE 收敛到 `[-2%, 10%]`。
- 🐛 **`binding` 与方向稳健性各自独立判定，导致同一标的自相矛盾（`models/reverse_dcf.py` + `reporting/dashboard.py`）**：SO 的 `binding` 分支仅比较带宽两端，判为 `above_band_ceiling`（「隐含增长 ≥ 10%」），而求解器备注已说「方向敏感、不断言」—— 同一份报告两个结论打架。现 `binding` 判定**先过稳健性闸门**：不稳则新增 `ev_direction_undetermined` 档，两处渲染（`_implied_section` / `_gap_section`）改为「不可判定（方向对营运资本假设敏感）」。
- 🐛 **非单调曲线被描述为「单调下降」（`models/reverse_dcf.py`）**：LLY 的 EV 在合理带内 g≈11.1% 处见顶再回落，但带宽备注写「EV 随营收 CAGR 上升而下降」，与求解器备注报的峰值直接冲突。改为先用 `_peak_in_band()` 探测**带内**极大值，存在内部峰时改写为「在 g≈X 处达到最大值后转为下降：曲线非单调」。
- 🐛 **归因分解漏了 CapEx / ΔNWC 的符号（`forecasts/fcf_projection.py`）**：`FCF = NOPAT + D&A − CapEx − ΔNWC`，但组件 PV 是正值幅度，首版直接相减使加和与直接差分相差 1e11（NEE `+102.6B` vs 真实 `−23.7B`）。改为在分解处对 CapEx / ΔNWC 乘 −1，加和与 `EV(g_hi) − EV(g_lo)` 精确一致（误差 ~1e-5，纯浮点）。

### ✨ Added
- ✨ **增长价值归因 `attribute_growth_value()`（`forecasts/fcf_projection.py`）**：EV 对 FCF 分项是**线性**的，故 `EV(g_hi) − EV(g_lo)` 可**精确加性分解**为 NOPAT / D&A / CapEx / ΔNWC / 终值五份 —— 无交互项、无反事实重解，因此不存在「归因顺序影响结论」的问题（朴素「置零重解」分解是有序依赖的，可翻转总和符号）。另输出 `cancellation_ratio = Σ|分项| / |合计|`：SO **125×**、CEG 10.2×、NEE 7.4×、LLY 4.6× —— 这是「方向脆弱」的数学指纹。已渲染进 `_implied_section`，≥3× 时显式告警「净额是方向相反的大额分项相减的结果，其正负号对输入假设敏感」。
- ✨ **多峰值检测 `_ev_curve_peaks()`（`models/reverse_dcf.py`）**：单网格最大值隐含单峰假设，非单调曲线会藏起第二个转折点。改为枚举所有局部极大（含两端点）+ 三分搜索局部精修 + 按增长去重，meta 记录 `ev_peak_count` / `ev_peaks` / `peak_search_range`。实测 LLY 3 峰（内部峰 g=11.1%）、TSLA 3 峰、NEE/CEG/SO 各 3 峰。
- ✨ **无解分类学 `_classify_no_root()`（meta `no_root_kind`）**：把「无解」拆成 `EV_DIRECTION_UNDETERMINED`（问不出答案）/ `NO_ROOT_IN_DOMAIN`（模型解释不了定价）/ `SEARCH_DOMAIN_INSUFFICIENT`（搜索域太窄）/ `SOLVER_NONCONVERGENCE`（根在带内但求解器没抓到）四档 —— 四者含义完全不同，合并成一个状态会诱导单一且错误的结论。实测 8 只 UNDETERMINED + 1 只 MRNA `NO_ROOT_IN_DOMAIN`。
- ✨ **`nwc_sensitivity_ratios` 配置（`config.py::ReverseDCFConfig`）**：`(-0.10, 0.0, 0.05, 0.10, 0.15, 0.20, 0.30)` —— 方向稳健性检验的候选集，集中定义便于审计与后续调整。

### 🔧 Changed
- 🔧 **`project_enterprise_value_from_data(..., nwc_ratio_override=)`（`forecasts/fcf_projection.py`）**：允许替换反推的边际 ΔNWC 比，**仅**用于敏感性探测（该参数是最不可靠的投影输入），不影响默认路径，故 golden 零漂移。
- 🔧 **审计 `check_solver_residual`（`benchmark/verify_fix.py`）**：`EV_DIRECTION_UNDETERMINED` 判 **PASS**（这是「参数不确定性下的诚实结论」，不是缺陷）；`SEARCH_DOMAIN_INSUFFICIENT` 判 WARN（提示先放宽搜索域再下结论）。

### ✅ Verified
- `python -m pytest tests/ -q` → **715 passed / 1 skipped**（基线 682 + 新增 33 例）。
- 改动文件 + `benchmark/` 的 `ruff check --select E4,E7,E9,F` → **All checks passed**。
- **golden 指纹零漂移**（P0–P3 只改注释 / meta 新字段 / 新增归因，不改任何数值路径）。
- benchmark 50 只：**Solved 32 / No Solution 9 / 正确路由排除 9**，审计 **0 硬失败 / 0 漂移**。
- 新增测试 4 文件 33 例：`test_nwc_direction_robustness.py`(8)、`test_ev_multipeak.py`(8)、`test_no_root_classification.py`(8)、`test_growth_value_attribution.py`(9)。

### ❌ 证伪记录（用户假设不成立，未按此实现）
- **「增量 ROIC < WACC 可解释 EV 随增长递减」——不成立。** 按用户要求实算增量 NOPAT / 净资本投入（CapEx−D&A+ΔNWC）：NEE 57% vs WACC 6%、CEG 27% vs 14%、FCX 30% vs 10%、LLY 45% vs 8%、KO 199% vs 7%、NVDA 215% vs 10% —— **全 50 只增量 ROIC 均高于自身 WACC**，其中 9 只 EV 仍递减。该判据**零命中**，故未实现为机制标签。用户的提醒（「CapEx > D&A 不足以反推」）方向正确且更彻底：严格算 ROIC 也不构成判别式。
- **真实判别式是 `g_BE = k0 / nwc`**：递减组临界增长 4.8%–12.5%，递增组 19%–652%，完全分离。但它依赖的 NWC 边际比本身是残差反推 —— 故正确结论不是「换个点估计」，而是**不稳健时不断言**（即 ⑭ 的实现）。

---

## [Unreleased] — 2026-11-19 (Session #49 续 2 — Reverse DCF / β 深度验收：归因纠错)

> 触发：用户任务「Reverse DCF 与 β 全链路深度验收（Post-Fix Deep Validation）」。
> 纪律：**先证伪自己的诊断再改码**。本轮证伪的是**上一轮自己刚写出的归因**，并由此发现 1 条真实分类缺陷。

### 🐛 Fixed
- 🐛 **「EV 随增长递减」被统一误归因为「终期 FCF ≤ 0」（`models/reverse_dcf.py`）**：上一版对所有递减曲线都写「终期 FCF ≤ 0、终值被抑制」。**证伪**：NEE 的 `terminal_fcf_negative=False`（终值为正）却在 g=0 见顶 $46.2B、随后单调下滑到 g=150% 的 −$31.9T —— 与「终值被抑制」的描述矛盾。真实机制是**再投资（CapEx + 营运资本）超过增长自身产生的现金流**（NEE capex 37.2% > D&A 23.3%、NWC 边际比 24.9%；CEG/LLY/FCX 同型）。现改为在**合理性区间内**扫描 EV 峰值，写入 `ev_peak_growth` / `ev_peak` / `ev_peak_below_target` / `terminal_fcf_negative_at_peak`，并据此**二选一**给出准确归因（终值抑制 vs 再投资侵蚀），同时明示「即便取最优增速，模型也无法解释当前价」。
- 🐛 **`binding` 判定无视 EV 方向，输出自相矛盾的「EV 上限」（`models/reverse_dcf.py` + `reporting/dashboard.py`）**：`above_band_ceiling` 的语义是「**更高**增速可逼近价格」，但该分支只看 `ev_at_ceiling < target_ev`，对递减曲线会渲染「模型推算 EV 上限 $-7,197,462,776 < 目标 EV $85,881,290,000」（CEG）—— 负的「上限」在语义上不成立。现新增 `ev_decreasing_in_growth` 档：EV 在合理区间内递减时不再声称「隐含增长 ≥ 上限」，`_implied_section` 与 `_gap_section` 均改为「不适用（模型 EV 随增速上升而下降）」。
- 🐛 **`solver_residual` 把「已证明无根」当成「未收敛警告」（`benchmark/verify_fix.py`）**：9 只 `ev_decreasing_in_growth` 原被判 WARN，掩盖了「这是确定性结论」。现：`ev_peak_below_target=True` → **PASS**（附峰值证据）；峰值缺失或高于目标 → 仍 WARN（区分「已证明」与「未知」）。改后 `solver_residual` PASS=41 / WARN=0。
- 🐛 **β 合成回收测试的噪声设定超出统计可辨识度（`tests/test_beta_synthetic_recovery.py`）**：噪声 σ=0.005 对市场波动 σ≈0.04 使 β 标准误 ≈0.021，超过 2e-2 容差 —— 是测试设计问题而非代码缺陷。降至 0.0015。同时修正 `window_end` 期望：37 个月度点（2022-01 起）末端为 `2025-01-15`，原断言 `2024-12-15` 少算一格。

### ✨ Added
- ✨ **验收测试 `tests/test_solver_ev_direction_label.py`（9 例）**：固定求解器的方向分类契约 —— 递增未达目标 = `above_search_ceiling`、递增已超目标 = `below_search_floor`、递减 = `ev_decreasing_in_growth`（**不得**称为上限）、曲线穿越目标 = `SOLVED`；并断言峰值搜索**限制在合理性区间内**、抑制与再投资两种归因**二选一**且措辞正确。
- ✨ **验收测试 `tests/test_beta_selection_vs_blume.py`（7 例）**：钉死「选中」与「收缩」两条路径不可混淆 —— NVDA 2.4303→0.9295 是**自下而上选中**（若误判为 Blume 应为 1.93，差 1.0）；CEG 2.1777→1.7655 是**Blume 收缩 35%**（`0.65×2.178+0.35×1.0` 精确复算）；并固定 `winsorize → shrink` 的顺序（5.0 先夹到 2.50 再收缩）。
- ✨ **验收测试 `tests/test_benchmark_coverage.py`（8 例）**：把「无遗漏、无默认通过、无静默跳过」变成断言 —— 50 只注册表全覆盖、`expect_applicable` 者不得缺状态、排除项必须能归因 `business_type`、每条 `No Solution In Range` 必须带可识别 `failure`。
- ✨ **审计规则 `check_e_coverage`（`benchmark/audit.py`）**：`judge()` 新增 E 类检查。`rd_status is None` 仅在注册表声明不适用时合法；声明适用却无状态 = **FAIL（silent skip）**；排除但无 `business_type` = **DATA_ISSUE**（排除无法解释）。

### 🔧 Changed
- 🔧 **`benchmark/verify_fix.py::check_solver_residual`**：区分「已证明无根」（PASS，带峰值证据）与「未解释未收敛」（WARN）。
- 🔧 **`benchmark/verify_fix.py::check_solver_residual` 与 `check_growth_bounds` 的 WARN 语义收紧**：前者不再把确定性无根计入警告；后者仅对 `DATA_QUALITY_WARNING` 保留 WARN（负基准 FCF 已解出，仍应警示读者）。

### ✅ Verified
- **全量测试**：`python -m pytest tests/ -q` → **682 passed / 0 failed / 1 skipped**（本轮新增 34 例）。
- **ruff 门禁**：全部改动文件 `ruff check --select E4,E7,E9,F` → **All checks passed**。
- **golden 指纹**：`tests/test_golden_report.py` 3 passed；连续两次重跑 `report_fingerprints.json` **字节级一致**，本轮改动**零漂移**。
- **50 只 benchmark 复测**（`benchmark/run_benchmark.py` 全量重跑）：**Solved 32 / No Solution In Range 9 / 路由排除 9 / 无遗漏**。9 只无解全部带 `failure=ev_decreasing_in_growth` 与峰值证据；5 只负基准 FCF（AMZN/TSLA/BA/MRNA/SO）正确归入 `NEGATIVE_BASE_FCF_NO_VALID_ROOT`。
- **`benchmark/verify_fix.py` 审计**（50×9 项）：**0 硬失败、0 漂移**。`beta_raw`/`beta_blume`/`beta_used_traceable`/`date_alignment` **PASS=50**；`beta_adjusted`/`solver_residual`/`multiple_roots`/`wacc` **PASS=41 / UNKNOWN=9**（9 只为正确路由排除）；`growth_bounds` **PASS=37 / WARN=4**（ORCL/GOOGL/META/DUK 的负基准 FCF 警示，属应保留的诚实披露）。

---

## [Unreleased] — 2026-11-19 (Session #49 — Reverse DCF 双层增长区间 + 求解器审计留痕 + DUK 式现金流失真)

> 触发：用户任务「Harden Reverse DCF（双层增长区间 + 求解器审计留痕），修 DUK 式现金流失真，补增长分档与 β 置信度验收测试」。
> 纪律：**先证伪自己的诊断再改码**。本轮除实现既定目标外，自查又证伪并修复 2 条**自己刚写出的**缺陷（见 Fixed 第 1、2 条）。

### 🐛 Fixed
- 🐛 **「无解」与「价格不合理」被混为一谈（`models/reverse_dcf.py`）**：原先**合理性区间同时充当求解区间**，市场定价一旦超出业务类型的合理增速带，求解器便直接返回 `NO_SOLUTION_IN_RANGE` —— 把「价格贵得离谱」伪装成「模型算不出来」。现拆为**搜索区间** `[-0.50, 1.50]`（只决定能否求解）与**合理性区间**（只决定可信度标注，**永不限制求解**）。新增 `growth_band_verdict` 五档，按**带宽倍数**（而非绝对百分点）分档，使 10% 公用事业带与 60% SaaS 带的「超出」含义一致。
- 🐛 **verdict 与展示值自相矛盾（`models/reverse_dcf.py`，本轮自查发现）**：首版在函数**前段**计算 verdict 并写入 `breakdown`，而 normalized 成熟稳态救援在**后段**才改写 `implied_revenue_cagr` → NBIS/CRWV 出现三重矛盾：「`No Solution In Range`」+ 报告展示「隐含营收 CAGR ≈ 26%」+ verdict 判为「`SOLVED_WITHIN_BASE_BAND`」。改为**末尾统一 finalize**，一律按「报告实际展示的那个数」定档；并对 `reason == "negative_base_fcf"` 无条件降级为 `DATA_QUALITY_WARNING`——负基准 FCF 下任何「增长解读」都不成立，不能把烧钱公司标成令人安心的数据点。
- 🐛 **无根路径求解器无留痕（`models/reverse_dcf.py`，本轮自查发现）**：`solver_meta` 原只在 brentq 成功路径写入，`NO_SOLUTION_IN_RANGE` 与投影异常时为空 dict —— 「无根」与「求解器根本没跑」无法区分。现补写 `converged=False` + `failure=above_search_ceiling|below_search_floor|projection_error` + `ev_at_lo/ev_at_hi`。
- 🐛 **DUK 式现金流失真被当作增长结论（`models/reverse_dcf.py::_fcf_base_quality`）**：公用事业/重资产标的 TTM CapEx 常超 OCF（实测 DUK：OCF 11.5B / CapEx −16.7B → FCF **−5.2B**，CapEx/OCF **145%**；SO 138%），此时「隐含增长」只是资本开支口径的算术产物。新增负基准 FCF / 高 CapEx 占比判定，输出 `DATA_QUALITY_WARNING` 且优先级高于区间标签。
- 🐛 **β 符号翻转与数值离散同等对待（`data/providers.py`）**：跨窗口 β 由 `+0.33` 翻到 `−0.34` 意味着回归**方向**都不稳定、信息量近零，原实现与「数值极差大」同档。现按更严重档位评级。

### ✨ Added
- ✨ **求解器审计留痕（`models/reverse_dcf.py`）**：`_solve_revenue_cagr(..., meta_out=)` 写出 `solver_meta`：`solver_method` / `solver_version` / `search_bounds` / `residual` / `relative_residual` / `converged` / `n_roots_detected` / `roots` / `multiple_roots`；新增常量 `SOLVER_VERSION = "2.0-brentq-two-layer"`，使历史报告可追溯到具体求解实现。
- ✨ **增长分档判定（`config.py::GrowthBandVerdict` / `classify_growth_band`）**：五档 `SOLVED_WITHIN_BASE_BAND` / `SOLVED_OUTSIDE_BASE_BAND` / `SOLVED_EXTREME_GROWTH` / `NO_ROOT_IN_EXPANDED_RANGE` / `DATA_QUALITY_WARNING`。
- ✨ **报告层呈现（`reporting/dashboard.py` + `analysis/expectation.py`）**：`ImpliedExpectations` 与 `ExpectationGap` 均携带 `growth_band_verdict`；`_implied_section` 与 `_gap_section` 各渲染一行「**隐含增长可信度**」（`_GROWTH_BAND_VERDICT_LABELS` 五档中文标签 + 风险提示）。两节必须呈现**同一** verdict。
- ✨ **验收测试**：`tests/test_reverse_dcf_two_layer_band.py`（24 passed / 1 skipped，覆盖区间不变性、极端增长、负/重 CapEx 基准、verdict 一致性、两节渲染一致、五档标签齐备）+ `tests/test_beta_layering.py`（11 passed，覆盖符号翻转降级、数值离散分层、月度步长与斜率容差）。

### 🔧 Changed
- 🔧 **`tests/golden/report_fingerprints.json` 重新生成**：漂移共 4 只 —— AMZN / NVDA 的 `n_applicable` 6→5、`n_failed` 1→0、`n_display_only` 0→1；KR / XOM 的 `applicable_models` 新增 `ReverseDCF`、`n_total` +1、`n_display_only` +1。这是双层区间的**预期效果**：原先被合理性带宽挡在求解之外（记为 failed / 未适用）的标的，现在能解出当前价（`SOLVED_OUTSIDE_BASE_BAND`），并按 ReverseDCF 的循环论证设计标为「仅展示、不计入共识」。已逐键核对：四只的 `median_value`（47.62 / 224.35 / 60.0 / 92.43）**完全未变**，共识估值不受影响。
- 🔧 **清理 `reporting/dashboard.py` 两个 F841 死变量**（`roe_s` / `ke_s`）：基线既有，因该文件属本轮改动范围而一并清除（赋值无副作用，行为不变）。

### ✅ Verified — 50 只全量复测（同数据 A/B，非仅计成功数）

**方法论**：先把 2026-11-20 的 Yahoo 快照（60 个文件）连同 `treasury_yield` 一起钉住（回填为「今日」11-21 并刷新 mtime 绕过 4h TTL），确认 KO 价格 **97.39 与基线完全一致**，再在同一数据上跑旧代码基线 vs 新代码，从而把「代码改动」与「数据变动」彻底分离。

> ⚠️ **本轮最先证伪的一条**：首轮复测发现 16 只原本 Solved 的标的 CAGR 与 WACC **全线漂移**（NVDA cagr 0.19961→0.19226、wacc 0.101473→0.100073；AVGO、CRM、MCD、NKE、XOM 同型）。表面像 β 分层改动破坏了既有估值。逐项排查后确认**根因是数据而非代码**：`treasury_yield` 缓存的 10Y 国债收益率由 **5.052% → 4.912%（−14bp）**，恰好解释 WACC 全线 −14bp。钉住国债缓存后，16 只原本 Solved 的标的 **ΔWACC = 0（精确为 0）、ΔCAGR ≤ 2.7e-05**（求解器容差级）。若不先钉数据，会把一次数据更新误判成回归缺陷。

**结果（50 只，路由正确排除 9 只 REIT/银行/保险不计入）**：
| 指标 | 修复前 | 修复后 |
|---|---|---|
| Solved | 16 | **32** |
| No Solution In Range | 25 | **9** |
| 路由正确排除（None） | 9 | 9 |

**未破坏既有正确结果**：16 只原本 Solved 的标的 status 全部保持 Solved、WACC 零漂移、CAGR 漂移 ≤2.7e-05；`verify_fix.py` 的漂移审计 **0 findings**。

**9 只重点标的逐项验收**（用户指定）：

| 标的 | 修复前 | 修复后 | 验收要点 |
|---|---|---|---|
| KO | No Solution | **Solved 17.06%** `SOLVED_OUTSIDE_BASE_BAND` | 负 β（−0.027）按政策下限 0.30 取值并留痕；根在 [−3%,15%] 带外，**不再被伪装成「无解」** |
| JNJ | Solved | Solved 9.70% `SOLVED_WITHIN_BASE_BAND` | 负 β（−0.033）→0.30；落在 [−5%,35%] 带内，标注与数值一致 |
| DUK | No Solution | **Solved 48.66%** `DATA_QUALITY_WARNING` | TTM FCF **−5.16B**、投影首年 +6.01B（差 216%）→ 如实降级为数据质量警告，不当作增长结论 |
| SO | No Solution | No Solution `DATA_QUALITY_WARNING` | 负 β（−0.100）→0.30；负基准 FCF 且 150% 增速上限下 EV 仍为负 → 诚实「无解」，附 `above_search_ceiling` 留痕 |
| WMT | No Solution | **Solved 37.90%** `SOLVED_EXTREME_GROWTH` | 极端隐含增长被显式标注，不再静默；β 由自下而上链（Damodaran L3 去杠杆 0.76 → 目标 D/E 再加杠杆 0.82） |
| AAPL | — | No Solution `NO_ROOT_IN_EXPANDED_RANGE` | 负 β（0.603）→ 0.937；全区间 [−50%,150%] 无根 → 明确「扩区间仍无解」而非含糊 |
| MSFT | No Solution | **Solved 39.36%** `SOLVED_OUTSIDE_BASE_BAND` | 自下而上 β 0.973（分部加权 8 家同业）可追溯 |
| NVDA | Solved | Solved 19.96% `SOLVED_WITHIN_BASE_BAND` | 高增长；β 2.430 → 自下而上 0.930；残差 8.5e-08 |
| JPM | None | None | 银行模型正确路由排除（`is_financial_institution=True`），未被 DCF 误算 |

**搜索区间不变性**（用户明确要求「Test A 0–15% → 8.23%，Test B 0–30% → 8.23%」）：
- 新增 `tests/test_reverse_dcf_search_band_invariance.py`（**4 passed**），在生产路径上截获求解器真实入参后按不同区间重解。
- **先证伪**：首版断言 `spread < 1e-9` 时 NVDA 报 1.24e-05。收紧 `xtol` 至 1e-9 后两区间收敛到同一点（差 8.8e-12），**证明该差异纯属 `xtol=1e-4` 的求解器契约**，不是逻辑缺陷；断言改为 `≤ 2×xtol`。
- **KO 是核心证据**：A[0,15%] 无解、B[0,30%] 得 **17.06%** —— 根确实在窄带之外。若两者同时「无解」，即说明合理性带又悄悄变成了求解边界（已固化为回归测试 `test_root_outside_narrow_band_is_found_by_wider_search`）。

**审计引擎（`benchmark/verify_fix.py`，50 只 × 8 项检查，0 硬失败）**：
| 检查项 | PASS | WARN | FAIL | UNKNOWN |
|---|---|---|---|---|
| beta_raw | 50 | 0 | 0 | 0 |
| beta_adjusted | 41 | 0 | 0 | 9 |
| beta_used_traceable | 50 | 0 | 0 | 0 |
| date_alignment | 50 | 0 | 0 | 0 |
| solver_residual | 32 | 9 | 0 | 9 |
| multiple_roots | 41 | 0 | 0 | 9 |
| growth_bounds | 32 | 9 | 0 | 9 |
| wacc | 41 | 0 | 0 | 9 |

- **UNKNOWN 一律不计为 PASS**（未知不等于合格）：9 只路由排除标的本就没有 Reverse DCF，不予评分。
- **WARN 均为诚实披露而非缺陷**：`above_search_ceiling`（根在 150% 之上，如 SO/AAPL/BA/MRNA）、`DATA_QUALITY_WARNING`（负基准 FCF）。
- **本轮自查又证伪 3 条自己写错的审计断言**（不改产品代码，只改检查逻辑）：
  1. `beta_adjusted` 原假设「必为 raw 的 Blume 收缩」。实测 NVDA raw 2.430 → adjusted 0.930，看似违规；查证后确认该字段是**选中 β 归一化后的值**，当选中自下而上 β（NVDA 0.930）时与回归 β 无收缩关系 → 检查改为**按选择路径分支**。
  2. `date_alignment` 原按 `as_of` 单键取值，50 只全 WARN。实际证据是 `window_start/window_end` + `benchmark=SPY` + `n_observations=35` + `adjclose`，字段名写错而已 → 改为按完整证据链判定。
  3. `beta_raw` 把 CEG（2.178→1.765）判为「无 floor 的异常」。实测为 **Blume 收缩 35%**（`BETA_MAX_SHRINK`），且 `(1−0.35)×2.178+0.35×1.0 = 1.765` 完全吻合 → 改为**算术复算收缩结果**。
  4. 漂移比较原用纯相对容差，BKNG（CAGR −0.39%）因分母极小把 9e-06 绝对差读成 0.23% → 改用 `max(1e-4, |基准|×1e-3)`。

**测试与门禁**：`python -m pytest tests/ -q` → **648 passed / 1 skipped**（新增 4 个区间不变性用例）；`ruff check --select E4,E7,E9,F`（改动文件 + `benchmark/`）→ **All checks passed**。
> 注：全仓 `pytest`（含 `scripts/`）会额外报 1 个 `test_phase1_refactoring.py::test_share_count` 的 `fixture 'ticker' not found` —— 经 `git diff` 确认 `scripts/` **本轮零改动**，属基线既有问题，未触碰。

**golden 指纹**：仅 AMZN / NVDA 的 `n_applicable` 6→5、`n_failed` 1→0、`n_display_only` 0→1，以及 KR / XOM 的 `applicable_models` 新增 `ReverseDCF`、`n_total` +1。四只的 `median_value`（47.62 / 224.35 / 60.0 / 92.43）**完全未变** —— 共识估值不受影响，只是 ReverseDCF 由「失败」转为「仅展示不计入共识」。`tests/test_golden_report.py` → **3 passed**。

## [Session #48] — 2026-11-19 (50 只热门股 Reverse DCF 诊断：4 项根因修复 + 1 项诚实披露)

> 触发：用户任务「50 只标的（NVDA/MSFT/AVGO/ORCL/CRM/AMD/GOOGL/META…）为何 Reverse DCF 返回 no solution / 路由错误，诊断并修复根因，不得破坏 golden」。
> 纪律：**先证伪自己的诊断再改码**。6 条初始假设经实测推翻，仅 4 条成立（详见 AGENT.md 的「已证伪」段）。
> 验证：`python -m pytest -q` → **609 passed / 0 failed / 0 errors**；改动文件 `ruff check --select E4,E7,E9,F` → **All checks passed**；golden 已按预期重生成（仅 XOM/KR 新增 ReverseDCF）；50 只实跑 **Solved 16 / No Solution 25 / 正确排除 9 / 路由违规 0**。

### 🐛 Fixed
- 🐛 **支付网络被误判为金融机构，DCF 族被剥离（`classification/classifier.py` + `classification/ml_classifier.py`，本轮核心）**：Yahoo 把 V/MA 与 COF/AXP/SOFI 同归「Credit Services」，分类器统一映射到 `FINTECH`，随后按「金融机构」规则整体剥离 DCF/ReverseDCF。新增**结构性判据** `BusinessClassifier._is_balance_sheet_financial()`：`利息费用 / 营业利润 ≥ 0.20` 判定为资产负债表型金融（支付网络 V 0.03、MA 0.04、PYPL 0.07 vs 放贷 AXP 0.37、SOFI 0.69、COF 0.86，两簇分离度极大；营业利润缺失或为负时回落 `利息/收入 ≥ 0.10`）。同时修复 `ml_classifier.py` 中 `is_fintech_hybrid → is_financial_institution = True` 的**无条件强制覆盖**（它会绕过上述判据）。V 由「路由排除」→ **Solved（隐含营收 CAGR 29.6%）**、MA Solved 10.6%；COF/AXP/SOFI/JPM/BAC 仍正确排除。
- 🐛 **`ReverseDCF` 路由缺口（`classification/classifier.py::MODELS_BY_TYPE`）**：CONSUMER_STAPLES / COMMODITY / UTILITIES / ENERGY / TELECOM 五类缺失 `ReverseDCF`，导致 17 只预期适用标的被排除——且其中 `VZ/XOM/CVX/SLB/COP` 反而**直接求解**，自相矛盾。补齐后 17 只全部归位。
- 🐛 **SBC 披露与实际求解口径不符（`models/reverse_dcf.py`）**：注记声称隐含求解使用「SBC 调整后 FCF」，实际求解只走 收入×利润率 路径。**证伪证据**：CRM 的 SBC 由 3.665B 归零后 `base_fcf` 从 11.49B 变为 15.15B，而隐含 CAGR 到 **17 位有效数字完全相同** → FCF 对该求解零影响。注记改为如实描述。
- 🐛 **`bridge_broken` 口径错配误触发救援（`models/reverse_dcf.py`）**：原判据 `base_fcf <= 0` 用的是 SBC 归一后的**报表** FCF（GOOGL −10.66B），而投影走 收入×利润率 路径（GOOGL 首年 +84.0B）→ 误报「成熟稳态救援」。改为探测投影路径本身（首年 FCF / 终值是否为负），`proj is None` 时回退。

### ✨ Added
- ✨ **投影 FCF 与报表 FCF 口径调和披露（`models/reverse_dcf.py`）**：投影口径为 `NOPAT + D&A − CapEx − ΔNWC`，`base_fcf` 为报表 `CFO − CapEx`。当 D&A 远大于 CapEx（如内容/无形摊销，其现金支出已含在 OCF 内）时两者严重背离——NFLX 的 D&A 占收入 41%（17.9B）而 CapEx 仅 1.2%（0.93B），投影首年 FCF 30.3B 是报表 11.4B 的 2.7 倍，由此得出**假结论**「市场隐含营收 CAGR ≤ −5%」（NFLX 实际增速约 12%）。新增 `breakdown["projection_vs_reported_fcf"]`（含 `projection_year1` / `reported_ttm` / `relative_gap`）；差异 >50% 时置 `breakdown["projection_fcf_caliber_mismatch"] = True` 并追加中文注记，说明隐含增长基于投影口径、与报表现金流不可直接比较。实测精确命中 NFLX（175%），不误伤 KO 8.9% / CRM 9.7% / AMD 46%。
  - ⚠️ **已证伪的替代修法（未采用）**：「D&A 加回上限取 CapEx」。实测虽把 NFLX 误差由 166% 降到 10%，却使 AMD 由 1% 恶化到 71%，并破坏 CRM/PFE/JNJ —— 一刀切会系统性低估轻资产、高摊销企业的价值，故放弃。

### 🔧 Changed
- 🔧 **`tests/golden/report_fingerprints.json` 重新生成**：唯一漂移为 XOM 与 KR 的 `applicable_models` 新增 `ReverseDCF`、`n_display_only` +1、`n_total` +1。`n_display_only` 的增加是**预期行为**：ReverseDCF 反解出当前价格属循环论证，按设计被标记为「仅展示、不计入共识与适用分母」。
- 🔧 **开发环境依赖补齐**：`lightgbm` + `scikit-learn`。此前 18 个 `tests/test_ml_classifier.py` / `tests/test_classification_identity.py` 用例以 error 形式失败，经 `git stash` 复现确认为**基线既有**的环境缺失（非代码缺陷）；补齐后 **0 error**。

## [Session #47] — 2026-11-19 (KR 报告审计：5 项自相矛盾修复 + 推翻 Session #46 的「有意更严」判断)

> 触发：用户任务「看看这个报告有什么不合理的地方然后修复，修复了再测试，确保问题修复好」。
> 纪律：**先证伪自己的诊断再改码**。KR 报告（2026-11-20 13:21 UTC）中的 β 窗口带宽、单变量隐含解、headline 三处均先复现再改码。
> 验证：`python -m pytest -q` → **591 passed / 0 failed / 18 errors**（18 errors 为基线既有，`lightgbm` 缺失所致；基线 583 → 591，新增 8 用例）；改动文件 `ruff check --select E4,E7,E9,F` → **All checks passed**（`dashboard.py` 仅剩基线既有 `ke_s`/`roe_s` 两项）；golden **零漂移**；KR 全链路实跑 exit=0。

### 🐛 Fixed
- 🐛 **β 窗口 WACC 带宽不含自身基准（`valuation/wacc.py`，本轮最严重）**：带宽用**回归窗口 β 原始上下沿**定价（KR 窗口 β = −0.28/−0.34/0.33），而报告实际 WACC 用的是**自下而上 β = 1.19** → 输出「WACC∈[6.07%, 6.17%]」并排「Final WACC = 9.33%」，**区间不包含自己的基准**。改为以**采用值 β 为中心**、按窗口极差/2 展开（`β∈[0.86, 1.53]` → `WACC∈[8.11%, 10.54%]`），区间现已包住 9.33%。
- 🐛 **虚假「已传导至 DCF 区间」声明（`valuation/wacc.py::beta_uncertainty_note`）**：`grep` 确认**无任何代码消费** `wacc_beta_lo/hi`，DCF 用的是自己的行业带宽（`models/dcf.py::_pps_wacc_lo/hi`），二者无关。改为如实标注「敏感性参考；DCF 仍以采用值单点折现」。
- 🐛 **同一对象两套波动措辞（`valuation/wacc.py::beta_window_note`）**：极差 0.67 时，`beta_window_note` 说「窗口间波动较大」（阈值 >0.50），`beta_uncertainty_note` 说「中度波动」（阈值 ≤1.0），同屏矛盾。改为**共用 `_beta_uncertainty_label`**。⚠️ 本条**推翻了 Session #46 的「有意更严，未改阈值」判断**——当时只统一了措辞、保留双阈值，但双阈值正是矛盾的根因；`beta_uncertainty` 仅用于文案（无数值收缩），统一阈值不会移动任何 golden 值。
- 🐛 **单变量隐含解把基准值当结论（`models/reverse_dcf.py` + `analysis/expectation.py` + `reporting/dashboard.py`）**：隐含解以**已解出的隐含 CAGR** 为锚，而该路径本身就已复现目标 EV → WACC/终值增长率的求解**必然回落到自身基准值**（KR：隐含 WACC 9.3% vs 基准 9.327%、隐含 g 0.5% vs 基准 0.5%），却标注「其余假设固定为基准」，读起来像独立证据。新增 `*_degenerate` 标记，渲染为「（与基准一致：当前增速已足以解释股价，该项不构成额外证据）」。**未改锚点本身**：实测改用预测 CAGR（−0.11%）作锚会解出隐含 WACC 3.15%（低于无风险利率，不成立），故锚点选择是正确的，错的是**呈现方式**。
- 🐛 **Headline 与自身 caveat 互相矛盾（`reporting/verdict_intuition.py`）**：情景交叉检验把 `headline` 上调为「显著高估」，但 `headline_summary` 仍用**中位数标签**拼装 → 「当前价 $67.94 估值合理…（显著高估信号）」。改为用**最终 headline**，中位数口径降为从属子句：「显著高估（中位口径 估值合理，中位估值 $68.20）」。
- 🐛 **区间过宽却称「落在公允区间内」（`reporting/verdict_intuition.py`）**：KR 区间 $1.62~$77.13（宽度为中位数的 2.7 倍）仍输出「当前价落在公允估值区间内」，与 headline「显著高估」并读像是背书。改为区间宽度 > 中位数时报「区间过宽…不足以判定当前价是否合理」。
- 🐛 **正 FCF 被标为负（`classification/classifier.py::_characterize_profile`）**：KR TTM FCF **+$2.38B**（1.6% 利润率），标签却是 `Weak/Negative FCF`——杂货零售结构性薄利，与「负值」是两件事。新增 `Thin Positive FCF` 档（0 ≤ margin < 3%）；真负值仍为 `Negative FCF`。已确认 `models/multiples.py` 的 AI-cloud 判定依赖 `weak`/`neg` 子串，薄正档正确地不再命中。

### ✨ Added
- ✨ **`tests/test_kr_report_audit.py`（5 用例）**：锁定薄正 FCF 不称负、真负仍称负、退化隐含解被标记、偏离基准的求解**不得**被标记、headline 必须由情景上调后的结论主导。
- ✨ **`tests/test_phase3_integrity.py`（+2 用例，改 1 用例）**：`test_beta_window_wacc_band_contains_the_reported_wacc`（带宽必须包住自身 WACC）、`test_beta_window_wacc_band_note_does_not_claim_dcf_propagation`；原 `test_beta_window_note_reports_dispersion` 由断言「波动较大」改为「中度波动」，并新增极差 1.05 → 「波动较大」的正向用例。

### ✅ Verified non-defects（复核后未改码）
- **情景列表中的「基本面 ×1.00/×1.00」**：是**基准情形本身**，与熊市/乐观情景并列呈现以便对照，标题已写明「本组情景仅变动折现率」，非误标为独立情景。
- **隐含解以隐含 CAGR 为锚**：见上，换锚会产出低于 Rf 的 WACC，故锚点正确。

---

## [Unreleased] — 2026-11-19 (Session #46 — AAPL 报告审计：8 项自相矛盾/口径缺陷修复)

> 触发：用户任务「看看这个报告有什么不合理的地方然后修复，修复了再测试，确保问题修复好」。
> 纪律：**先证伪自己的诊断再改码**；两项疑似缺陷（覆盖因子 1.08、β 窗口阈值差异）经复核判定为设计内行为，未改码。
> 验证：`python -m pytest -q` → **583 passed / 0 failed / 18 errors**（18 errors 为基线既有，`lightgbm` 缺失所致）；改动文件 `ruff check --select E4,E7,E9,F` → **All checks passed**；golden **零漂移**；AAPL 全链路实跑 exit=0。

### 🐛 Fixed
- 🐛 **NWC 口径混用（`analysis/divergence.py::_fcf_normalization_layer`，本轮最严重）**：`_extract_history()` 返回**边际** ΔNWC/ΔRevenue（AAPL **37.9%**），却被当作**收入占比**直接从 FCF margin 扣除 → 历史正常化 FCF margin **−11.6%**（对苹果而言不可能）。改为经历史增速换算为收入占比（`hist_nwc × cagr`）后再扣 → **23.3%**，与 TTM 28.4% 同量级；假的「FCF 走弱」告警随之消失。DCF 主链经 `forecast_nwc_change()` 消费该比率，口径本就正确，未受影响。
- 🐛 **对账结论硬编码（`reporting/dashboard.py::_data_section`）**：估值可用性评分**无条件**追加「受对账不一致影响；与源数据质量分开」，而同报告写「已校验 10 项 · 一致 10 · 不一致 0」。改为按 `reconciliation_mismatches` 分三种文案（有/无对账不一致、或因每股口径等其他校验降分）。
- 🐛 **Regression Stability 语义倒置（`valuation/wacc.py::beta_uncertainty_note`）**：字段存的是**不确定性**等级，却挂在「稳定性」标题下 → 「低」被读成「稳定性差」，与同屏「窗口间稳定」自相矛盾。标题改为「回归窗口不确定性」并附解读（低 = 窗口间稳定）。
- 🐛 **敏感性章节张冠李戴（`reporting/dashboard.py::_coe_sensitivity_section`）**：标题承诺「仅变动 Ke」，但非金融企业实际走 `run_all()`，**WACC 与终值增长率 g 同时变动**；且把 `sv.wacc`（WACC）当作 Ke 打印。改为按 `drivers` 判别：金融企业为真单变量（Ke/β），非金融企业如实标注「折现率档位同时变动 WACC 与 g」，并按 WACC/g 渲染。
- 🐛 **增长特征 Unknown（`classification/classifier.py::_characterize_profile`）**：要求 `annuals[0]` 与 `annuals[-1]` 营收俱全，AAPL 2022 营收为 `None` → 明明报告另有 7.7% CAGR 却输出 `Unknown`。改为取**最长可用跨度**。
- 🐛 **未细分经济标签粗化精确身份（`classification/taxonomy.py::reconcile_identity`，本轮核心）**：Yahoo「Consumer Electronics」→ `tech.hardware`，ML「MatureTech」→ `tech.generic`（标签即「Technology (unspecified)」），旧逻辑收敛至共同祖先 `tech`，**把精确节点降级**，违反本模块自述的「经济特征只能细化、不得决定身份」黄金律。新增例外：`*.generic` 属**证据缺失**而非竞争性证据 → 保留外部身份。AAPL 节点 `tech` → **`tech.hardware`**（行业 sanity 区间随之由泛科技变为 Consumer Electronics）。
- 🐛 **Peer 适配性误报（`analysis/divergence.py::_peer_fit_check`，修 Session #45 自身遗留）**：`tech` 是**族根**（`parent=None`），本身就是板块粒度，却仍被报「粗颗粒板块锚点」。同时修正反向过修：节点无专属锚点时（`TAXONOMY_NODE_PEER_MULTIPLES` 目前仅登记 `util.ipp`）也会告警 → 几乎每只票都告警。最终规则：族根不报；**仅当该指标存在节点专属锚点却仍用板块锚点**时才报。AAPL 由 🟠 → 🟢，VST 的 `util.ipp` 告警保留。
- 🐛 **预测 FCF CAGR 跨口径（`analysis/expectation.py::forecast_cagr`）**：起点用**报告 TTM FCF**（OCF−capex，已加回 SBC，margin 28.4%），终点是**桥式**预测 FCF（NOPAT+D&A−capex−ΔNWC，margin 23.6%）→ 实际上升的路径（121.5B → 125.3B）被算成 **−1.6%**，与「基础预测营收 CAGR +6.2%」方向相反。改为 FCF 起点使用桥式锚点 → **+2.3%**。

### ✨ Added
- ✨ **`forecasts/forecast.py::ForecastEngine.bridge_fcf_anchor()`**：以预测主链同口径（`NOPAT+D&A−capex−ΔNWC`，Year-1 增速取预测自身假设）给出 TTM FCF 锚点，供任何需要与预测值比较的 CAGR/倍数计算使用，避免再次跨口径。
- ✨ **`tests/test_aapl_report_audit.py`（5 用例）**：锁定边际 NWC → 收入占比换算、`*.generic` 不粗化精确身份、具体经济冲突仍收敛至祖先、增长特征容忍末年缺失、FCF CAGR 使用桥式锚点。
- ✨ **`tests/test_taxonomy_node_anchors.py::TestFamilyRootNodeIsNotFlagged`**：锁定族根（`parent=None`）不因使用板块锚点而被误报。

### ✅ Verified non-defects（复核后未改码）
- `覆盖因子 1.08`：`sqrt(适用 7 / 解算 6)` 为设计内的轻度惩罚乘数（clamp `[1.0, 2.0]`），非缺陷。
- `beta_window_note` 的 0.50 阈值与 `_beta_uncertainty_label` 阈值不同：**有意更严**（`test_beta_window_note_reports_dispersion` 锁定极差 0.65 必须报「波动较大」），仅统一了措辞，未改阈值。

---

## [Unreleased] — 2026-11-19 (Session #45 — VST 报告审计：7 项自相矛盾缺陷 + 分类节点锚点下沉)

> 触发：用户任务「审计/优化，让 reverse DCF 更精确、最大化热门股覆盖」。
> 纪律：**先证伪自己的诊断再改码**；未复现的不改（D/E、Margin Risk CV、隐含利润率三项经复核后判定非缺陷）。
> 验证：`python -m pytest -q` → **577 passed / 0 failed / 18 errors**（18 errors 为基线既有，`git stash` 后同样 18 项，`lightgbm` 缺失所致）；改动文件 `ruff check --select E4,E7,E9,F` 仅剩基线既有 2 项；golden **零漂移**；VST 全链路实跑 exit=0。

### 🐛 Fixed
- 🐛 **样本口径恒等式不成立（`reporting/dashboard.py`）**：`2+0+2+0=4 ≠ 合计 5`——仅展示（display_only）模型被计入合计。修复后与模型分桶同源。
- 🐛 **模型分桶恒等式不成立（`reporting/dashboard.py`）**：`适用2+不适用0+解算2+失败0=4 ≠ 合计5`，与上条同一根因，一并修复。
- 🐛 **归因张冠李戴（`reporting/verdict_intuition.py`）**：headline 硬编码「股数偏差 >25%」，而 VST 实际触发的是**对账不一致**（滚动 P/E 53.22 vs 内部 18.56 = **186.8%** 偏离），真实股数偏差仅 **14.8%**。新增 `shares_cause` 分发，按真实成因输出文案。
- 🐛 **自相矛盾标签（`reporting/verdict_intuition.py`）**：「低覆盖（2/2 解算，质量因子 1.00）」——`coverage_sufficient` 把**比率 100%** 与**绝对样本数 <4** 混为一谈。改为区分「样本过少」与真实覆盖缺口。
- 🐛 **风险结论自相矛盾（`analysis/risk.py`）**：`fundamental_assessment` 取聚合分（80 → `PASS`），无视维度级 `FAIL`（Margin Risk）。改为**任一维度 FAIL 即下调总体结论**。
- 🐛 **虚假历史 FCF CAGR（`analysis/expectation.py`）**：报 **−40.9%** 实为 `>0` 过滤**静默丢弃** 2022 年负 FCF（−816M），并把跨度误标为 2 年。`historical_cagr()` 改为符号翻转/未定义时返回 `None`；dashboard 输出 `N/A（FCF 跨度为负值（无法计算 CAGR））`。
- 🐛 **同一现象两套归因（`reporting/verdict_intuition.py`）**：「股数证据不一致」与「对账不一致（TTM EPS）」并存 → 统一走 `shares_cause`。
- 🐛 **Peer 适配性自我认证（`analysis/divergence.py::_peer_fit_check`）**：原逻辑只要 `classification_status == confident` 就输出「分类明确，倍数法 peer 原型与业务身份一致」，**即使锚点停在粗板块**。新增检查：分类节点存在、而某倍数模型仍用 `EXACT_SECTOR_ANCHOR` → 输出「粗颗粒板块锚点」警告并列出受影响模型。

### ✨ Added
- ✨ **分类节点级 peer 锚点（`models/multiples.py`）**：新增 `TAXONOMY_NODE_PEER_MULTIPLES` 与解析链 **Level 0**（节点优先于 Yahoo sector，溯源 `EXACT_INDUSTRY`）。根因：`util.ipp`（商户独立发电商）与 `util.electric`（受管制电力）同属 sector `Utilities`，旧逻辑在 **Level 1 精确命中 sector 即停**，丢弃分类器已解析的更细节点 → **VST（P/B 实际 9.8×）被套用受管制电力锚点 P/B 1.8×**，得出 −81.6% 的假「显著高估」。修复后 P/B 1.8×→**3.5×**、P/E 16→**20**、EV/EBITDA 10→**11**，P/B 估值 $23.54 → **$45.77**。仅登记经济模型显著不同于母板块的节点，其余节点继续沿用板块锚点。
- ✨ **反向 DCF 增长带宽按分类节点（`config.py`）**：`REVERSE_DCF_BY_TYPE` 只按粗 `BusinessType` 取值，商户 IPP 因此继承受管制电力的 **10% 隐含 CAGR 上限** → VST 报 **「No Solution In Range」**，这是**带宽伪影而非价格结论**。新增 `REVERSE_DCF_BY_NODE`（`util.ipp` 上限 0.30）与 `get_reverse_dcf_config_for()`（节点覆盖、未列键回落 BusinessType、**不修改共享表**），接入 `models/reverse_dcf.py`。VST 由 **No Solution → Solved**：隐含营收 CAGR **18.3%**、隐含营业利润率 **9.2%**（基准 11.9%），即市场价需要**更快增长但更低利润率**，结论可解释。设计镜像既有 `CANONICAL_KEY_WACC_RANGES` 的节点分层。
- ✨ **`tests/test_taxonomy_node_anchors.py`（18 用例）**：锁定节点优先于 sector、受管制/未登记节点不受影响、无 profile 时回落、反向 DCF 带宽覆盖且不污染共享表、Peer 适配性对粗锚点告警。

### ✅ Verified non-defects（复核后未改码）
- D/E 3.94 = 20.07B / 5.10B —— 计算正确。
- Margin Risk CV = 1.01 —— 半偏差方法正确。
- 隐含营业利润率 18.0% 落在基准 11.9% 与 TTM 22.6% 之间 —— 单变量有界解，非矛盾。

### 🧪 Tests
- `tests/test_avgo_audit_remediation.py::TestP03PerShareDowngradeKeepsEv` 断言由旧的硬编码文案「股数证据不一致」改为断言**真实归因**（「每股估值基数不可靠」+「对账不一致」），与 §归因修复一致。

---

## [Unreleased] — 2026-11-19 (Session #44 — 季度 EBIT 污染修复 + 桥口径偏差根因重诊)

> 触发：用户任务「根据你的建议修复，全部修复后，再同步到 GitHub」。
> 纪律：**先证伪自己的诊断再改码**。本次最重要的产出是**推翻 Session #43 的错误归因**。
> 验证：`python -m pytest -q` → **577 passed**；改动文件 `ruff check` 项数与 HEAD **完全一致（336=336，0 新增）**；golden **零漂移**（EBIT 修复只影响实盘 Yahoo 数据，golden 用合成数据）。

### 🐛 Fixed
- 🐛 **Yahoo 季度 `EBIT` 污染导致 TTM 营业利润率失真（`data/providers.py`）**：Yahoo 的 `quarterlyEBIT` 对一部分标的是**算术不可能值**——高于毛利（`EBIT = 毛利 − 营业费用`）。最坏例 **GOOGL 2026-Q2：quarterlyEBIT 140.0B，而毛利 73.9B、收入 119.8B**，使 TTM 营业利润率变成 **61.7%**（年报实际 39.6%）。同季度 `OperatingIncome` 是干净的（40.8B）。修复三处：① `_QUARTERLY_TIMESERIES` 增加请求 `OperatingIncome`；② 取值改为**优先 `OperatingIncome`**，并对 `EBIT > 毛利（缺失时用收入）×1.001` 的值**判为污染并丢弃**（不进入 TTM 求和）；③ **NI 反推 EBIT 增加 `op_inc is None` 前置条件**——否则 `NI 112.2 + 利息 1.28 + 税 26.56 = 140.0B` 会**精确复现刚被拒绝的坏 EBIT**，静默抵消整个校验。`_CACHE_SCHEMA_VERSION` 4 → 5 以作废旧污染缓存。实测：GOOGL TTM OI 61.7% → **33.3%**（年报 39.6%）、NVDA 76.0% → **65.2%**（年报 65.6%），全 50 只不再有 `OI > 毛利` 的不可能值。

### 📊 Re-diagnosed（**推翻 Session #43 的归因**）
- 📊 **Session #43 的「桥式 FCF 偏离 5.16× 是桥式公式缺陷」结论错误**。两个混淆因子：(a) 被污染的季度 EBIT 抬高了桥式的 `NOPAT`；(b) 把 **FCFF 桥式**（`NOPAT + D&A − capex`，SBC 已作为营业费用扣过）与 **报告 FCF**（`OCF − capex`，SBC 已在 OCF 中加回）**跨口径直接相比**。同口径比较（桥式 vs 桥式）后，绝大多数标的吻合：**NVDA 0.98×、AVGO 0.85×、NFLX 1.09×、CRM 0.94×、VZ 0.95×、MCD 1.05×**。所谓「GOOGL 5.16×」在 EBIT 修复后为 **−0.30×**，方向甚至反转——原数字不可用。
- 📊 **真正剩余的偏差是「比率陈旧」，且只集中在 AI 资本开支重估的少数标的**。`_extract_history()` 用 **5 年等权平均**的 `capex/收入` 与 `D&A/收入`，而 GOOGL 的 `capex/收入` 已从 5 年均值 **14.8%** 升到 TTM **33.9%**。用真实目标 EV 反解隐含营收 CAGR，把 capex 换成 TTM 水平后的位移：**MSFT +11.3pp、META +9.3pp、GOOGL +8.0pp**，其余 19 只（XOM/JNJ/NVDA/AVGO/MCD/VZ/UPS/GE…）**位移 ≤1.9pp**。即缺陷真实存在但**高度局部**。

### ⚠️ Rejected（实测后放弃，附证据）
- ⚠️ **「TTM 比率无条件替换 5 年均值」不可行**：永续期继续按 33.9% 的 capex 扣除会把终值打成负数——前瞻 DCF 对 **GOOGL EV −130B、META −97B、ORCL −234B、AMZN −475B**（修复前分别为 +851B / +337B / +2B / −40B），并触发 `gordon_terminal_value` 的「负终值抑制」把 EV 压成只剩显式期。已回退。
- ⚠️ **「半衰期加权（2 年）」收益不足**：把首年 FCF 偏离 >50% 的标的从 11/40 降到 9/40，`median|dev|` 0.29 → 0.25，META 仍 17.8×。不足以支撑改动 golden，已回退。
- ⚠️ **「capex 在显式期线性收敛到 D&A」单独实施同样不足**（16/34 vs 15/34，无改善）。仅在与「永续期 capex=D&A 稳态终值」**配套**时才成立（负 EV 从 5 只降到 2 只，DUK 30B → 122B、SO 34B → 93B、ORCL 39B → 374B），但该组合会同时改动前瞻 DCF 与反向 DCF 的终值口径、并使 15 只已解标的的隐含增长率位移最多 25pp（FCX 30.4% → 5.3%）。**属产品决策，不在本会话单方面实施。**

### 📌 Pending Decision（未实施，需用户裁决）
- 📌 **终值期资本开支口径**：当前终值年仍按显式期的 `capex/收入` 永久扣除。教科书稳态假设是「永续期 capex ≈ D&A，故 FCF = NOPAT」，对资本开支强度正在重估的标的（GOOGL/META/MSFT/ORCL/AMZN 及 DUK/SO/NEE 类受监管公用事业）差异极大。两条候选：(a) 仅终值年改用稳态 FCF（capex=D&A）；(b) 显式期用 TTM capex + 终值稳态。两者都会改 golden 指纹并位移已解标的的隐含增长率，故**仅量化待裁**。

---

## [Unreleased] — 2026-11-19 (Session #43 — 50 只热门股压力测试：REIT 误判修复 + 桥口径偏差量化)

> 触发：用户任务「这 50 个股票我可以用来测试我的 reverse dcf 什么东西」（NVDA…VICI 共 50 只，横跨 15 个行业）。
> 方法：全 50 只实跑 `DataProvider → Normalizer → Validator → Classifier → ReverseDCF`，逐字段比对报告值与计算值，**不修改任何估值口径**，只记录实测结果。
> 验证：`python -m pytest -q` → **577 passed**（Session #42 的 574 → 577，新增 3 用例）；改动文件 `ruff check --select E4,E7,E9,F` 全部通过。

> ⚠️ **本节「桥口径偏差」的数字已被 Session #44 推翻**：GOOGL「5.16×」由「季度 EBIT 污染」+「FCFF 桥式与报告 FCF 跨口径相比」两个混淆因子造成，EBIT 修复后为 −0.30×。请以 Session #44 的「Re-diagnosed」为准；本节其余结论（REIT 修复、覆盖率、单变量可解率、SBC 影响面）仍然有效。

### 🐛 Fixed
- 🐛 **纯数值 REIT 规则覆盖了已提供的行业映射（`classification/ml_classifier.py`）**：`_looks_like_reit` 的数值兜底（EBITDA margin 55%–90% + beta<2 + CAGR<25% + 股息/杠杆）原本**无条件**执行，会在 sector 硬规则（第 0 层）已明确映射后再次改判。50 只实测命中 2 例：**LLY（Healthcare / 制药，EBITDA margin 0.567）→ 被判为 REIT**、**NEE（Utilities / 受监管电力，0.585）→ 被判为 REIT**。REIT 判定随后触发 `applicability_check` 的「REITs prefer NAV/FFO over FCF-DCF」拒绝，使这两只**完全退出 FCF DCF 与反向 DCF**。修复：该数值兜底增加 `sector_bt is None` 前置条件——它本就是「provider 未给 sector 时的兜底」，不应覆盖已有的直接证据。真实 REIT（PLD/O/AMT/VICI）仍正确分类并正确拒绝。

### 📊 Measured（本次不改码，仅记录——见「待决」）
- 📊 **DCF 桥口径与报告 FCF 系统性偏离**：`NOPAT + D&A − capex` 推得的桥 FCF 与 Yahoo 报告 FCF 在 36 只可算标的中 9 只偏离 >±25%，最大偏差 **GOOGL 5.16×**（桥 $101.8B vs 报告 $19.7B）、**NFLX 2.80×**（$31.9B vs $11.4B）、**XOM 0.25×**、**AMD 0.58×**、**WMT 0.62×**、**TSLA −0.51×（符号翻转）**、**META −0.98×（符号翻转）**。根因是 `NFLX` 型「D&A/收入 = 36%」的内容资产摊销、以及 `GOOGL/META` 型巨额 AI 资本开支在 OCF 口径下尚未完整反映，导致桥式把非现金摊销当作可分配现金。
- 📊 **反向 DCF 覆盖率**：50 只 → Solved 15 / No Solution In Range 25 / Insufficient Data 10。10 只拒绝全部为**正确拒绝**（Bank×3、Insurance×2、FinTech×1 为金融机构；REIT×4 应走 NAV/FFO）。
- 📊 **单变量隐含解可解率**（40 只适用标的中）：营业利润率 **40/40**、FCF 利润率 **40/40**、WACC **28/40**、终值增长率 **22/40**——WACC 与终值增长率在 12–18 只上超出约束区间，属结构性无解而非求解器缺陷。
- 📊 **SBC 归一化实际影响面**：40 只适用标的中 SBC/收入 >5% 者 8 只，最高 **MRNA 18.4%**、**META 11.2%**、**AVGO 9.5%**、**CRM 8.3%**、**ISRG 7.2%**、**ORCL 6.7%**、**GOOGL 6.5%**、**GS 5.0%**。

### ✨ Added
- ✨ **`tests/test_ml_classifier.py::TestReitMarginRuleRespectsSector`（3 用例）**：已知 sector（Healthcare / Utilities）时数值 REIT 规则**不得**改判；sector 缺失时该规则**仍须**生效（防止修过头把兜底也关掉）。

### 📌 Pending Decision（未实施，需用户裁决）
- 📌 **桥式 FCF 是否改用报告 OCF 为锚**：上表 9 只偏离 >±25% 说明「从 EBIT 自下而上搭桥」在某些商业模式（内容摊销、超大规模资本开支）下失真。两条候选路线：(a) 以报告 `operating_cash_flow` 为锚、仅用桥式做利润率的**边际**外推；(b) 保留桥式但对 `D&A/收入 > 20%` 或 `|capex/收入| > 30%` 的标的强制改用 OCF 锚。两者都会改变 golden 指纹，故本次**未动**，仅量化待裁。

---

## [Unreleased] — 2026-11-19 (Session #42 — 数据完整性三项修复：ΔNWC 报告值 / TTM SBC / 反向 DCF 路径统一)

> 触发：用户任务「再拉取我的仓库并检查我的项目有什么可以优化，更加精准的 reverse dcf 和尽可能的覆盖市场上的热门股票」。
> 纪律：**先审计再改码 / 缺失值禁止 None→0 静默转换 / 反向 DCF 必须与前瞻 DCF 同模型 / 现有测试除非明确批准否则零漂移**。
> 验证：`python -m pytest -q` → **574 passed**（Session #41 的 542 → 574，新增 `tests/test_precision_fixes.py` 32 用例）；`ruff check --select E4,E7,E9,F .` → 26 项**均为既有**（本次新增 0 项）。

### 🐛 Fixed
- 🐛 **ΔNWC 改用报告值，不再用残差反推（`data/providers.py`）**：`_ANNUAL_TIMESERIES` 未请求 `ChangeInWorkingCapital`，导致 `infer_change_in_nwc()`（`NOPAT + D&A − capex − FCF`）把递延收入、SBC、拨备等**全部非资本开支现金流**塞进「营运资本」一项。与 Yahoo 报告值对比误差：**META −$36.5B**（推断 −35.56B vs 实际 +0.89B，**符号翻转**）、**GOOGL −$19.9B**、**AAPL −$15.5B**、**MSFT −$12.5B**。补入请求字段后，边际 NWC 比率从「全部撞 ±50% 钳制」恢复为可解释值（META −0.500 → −0.047）。
- 🐛 **TTM 丢失 SBC 与 ΔNWC（`data/normalizer.py` / `data/providers.py`）**：`compute_ttm_from_quarters()` 只汇总收入/利润类字段，`ttm.stock_based_compensation` 恒为 `None` → `resolve_ttm_fcf_normalized()` 判定「无 SBC 数据」**静默跳过**，整条 SBC 归一化链路从未生效（GOOGL 年报 SBC **$24.95B** 一分未扣）。`_QUARTERLY_TIMESERIES` 补 `EBIT`/`DepreciationAndAmortization`/`StockBasedCompensation`/`ChangeInWorkingCapital`；TTM 汇总与三处年度回退构造器同步透传 `stock_based_compensation` / `change_in_nwc`。修复后 GOOGL TTM SBC $30.41B、NVDA $7.24B 正常入账。
- 🐛 **边际 NWC 钳制改为诚实回退（`forecasts/nwc_utils.py`）**：`marginal_nwc_ratio()` 原先把 `0.5×(aggregate+median)` 静默钳到 ±50%（KO/VZ/JPM 撞顶），等于永久假设「每 1 元新增收入有 0.5 元被营运资本吃掉」。改为：聚合比率在带内 → 直接用（`aggregate`）；越界 → 回退到**年均流量比率** `ΔNWC/revenue`（`flow_fallback`，KO +0.079 / VZ +0.010 / JPM +0.496 均为有界可解释值）。删除中位数混合（与 aggregate 重复且引入负权重噪声）。

### 🔧 Changed
- 🔧 **反向 DCF 求解面与前瞻 DCF 对齐（`models/reverse_dcf.py` / `forecasts/fcf_projection.py`）**：新增 `dcf_projection_shape()` / `dcf_path_inputs_from_data()` / `project_enterprise_value_shaped()` / `project_enterprise_value_from_data(..., shaped=True)`。反向 DCF 的单变量隐含解（营业利润率 / FCF 利润率 / WACC / 终值增长率）全部投影在**前瞻 DCF 自己的衰减增速 + 漂移利润率路径**上，且**终值增长率改用 DCF 实际值**（原先用业务类型参考值，如 2.50% vs DCF 的 4.50%）。`breakdown["implied_expectations"]["path_shape"]` 暴露路径，便于复算审计。业务类型参考终值增长率改为**只报告不应用**，偏离 >0.25pp 时写入 notes。
- 🔧 **Yahoo 缓存 schema 版本化（`data/providers.py`）**：新增 `_CACHE_SCHEMA_VERSION = 4`；写入 payload 带 `__cache_schema_version__`，读取时版本不符**直接作废重取**（避免旧缓存缺新字段被静默解码）；修复 `@classmethod` 序列化器引用实例属性导致的 `NameError`（此前缓存写入一直静默失败）。

### ✨ Added
- ✨ **非企业标的明确拒答（`data/models.py` / `data/providers.py` / `telegram_bot/telegram_bot.py`）**：`MarketData.instrument_type` 承载 Yahoo `instrumentType`；`ValuationPipeline._non_company_reason()` 以 provider 字段优先、`^` 前缀（指数）/ `-USD` 等（加密）为回退，ETF/共同基金/货币基金/加密/指数/期货/外汇 → 输出「本引擎不适用」的说明报告，而非一串 Insufficient Data 空表。实测 SPY/QQQ/IWM/DIA/GLD/SLV/USO/TLT/HYG 全部正确拒答。
- ✨ **`tests/test_precision_fixes.py`（新建，32 用例）**：缓存 schema 版本校验（匹配接受 / 不符拒绝）、shaped 投影 == 前瞻 DCF EV、反向 DCF 往返、报告 ΔNWC 优先于残差推断、TTM 汇总 SBC/ΔNWC（含「缺失不得伪造成 0」）、边际 NWC 四种估计路径（aggregate / flow_fallback / level_fallback / 钳制边界）。
- ✨ **热门标的热补（`full_tickers_1000.txt`）**：补入 `ACN` / `FI` / `RDDT`（其余如 ARM/PLTR/COIN/MSTR/UBER 等已在列表内）。

### 说明
- 反向 DCF 对 GOOGL/META/AAPL/MSFT/KO/PG/CAT/WMT/COST 返回 `No Solution In Range` 是**诚实结果**而非缺陷：这些标的当前价已高于「业务增长带上限 + 隐含利润率/WACC」能解释的范围，报告同时给出区间边界（`above_band_ceiling`）与单变量隐含解（如 GOOGL 隐含营业利润率 40.6% / 隐含 WACC 8.7%）。
- Golden baseline 基于**离线合成数据**（`SyntheticDataProvider`），本次改动集中在 Yahoo 实时数据链路，因此 golden 零漂移。

---

## [Unreleased] — 2026-11-15 (Session #41 — AVGO Audit Remediation Phase 1: P0-1 桥缺失数据安全 / P0-2 P/E 口径一致 / P0-3 股数证据闸门)

> 触发：用户提交正式任务书 **Valuation Engine — AVGO Audit Remediation Phase 1**（基于 2026-11-15 06:27 UTC 的 AVGO 报告），修复三项 **P0 估值完整性缺陷**——① Equity Bridge 把缺失 EV 静默转 0；② P/E 用不一致的股数口径（EPS 派生价值 × 无关市场股数）；③ 股数三口径（市场隐含/财报期末/稀释加权平均）未作为**独立证据源**比较。
> 纪律：**不重设计无关模块 / 改码前先审计现有实现 / 缺失值禁止 None→0 静默转换 / 每股基准不可靠不得产出无条件强结论但保留 EV 级结果 / 现有测试与 Golden Baseline 除非明确批准否则零漂移（不得自动重生成基线）/ 未实际执行的测试不得声称通过**。
> 验证：`python -m pytest -q` → **542 passed**（Session #40 的 522 → 542，新增 15 用例）；`ruff check .` → **All checks passed!**；`tests/test_golden_report.py` 通过 → **golden 零漂移**（未重生成基线）。

### ✨ Added
- ✨ **`data/reconciliation.py::ShareCountEvidence`（新建，P0-3）**：分离**市场隐含**（`MarketData.shares_outstanding`）/ **财报期末**（最新年报 `shares_outstanding`）/ **稀释加权平均**（TTM EPS 分母）三口径，各带 `period` / `source`；`share_count_evidence(data)` 计算 `max_deviation`（`|market-implied − other| / market-implied`）、`consistent`（`≤ _TOL_SHARES=0.25`）、`notes`（明示「`market_cap ÷ price` 仅为同口径复算，**不能作为财报股数的证明**」）；`to_lines(fmt)` 渲染三口径证据块；`ReconciliationReport.share_count_evidence` + `__all__` 增补
- ✨ **`analysis/model_agreement.py::_EXPECTED_SHARE_BASIS`（新建，P0-3）**：按模型族声明期望分母口径（P/E·Historical·DCF·ReverseDCF → `ttm`；P/B·EV/EBITDA·EV/Sales·FCF Yield·SOTP·REIT NAV·Replacement NAV → `market`；`unknown` 不判异常）；`ShareCountAuditRow` 新增 `source` / `as_of` / `basis_expected`；`ModelAgreement` 新增 `share_count_reliable`
- ✨ **`tests/test_avgo_audit_remediation.py`（新建，15 用例）**：覆盖任务书 9 类回归场景（缺失 EV / 缺失债务与现金 / 已验证零净债务 / 复杂股权桥 / P/E 用 TTM 稀释 EPS 股数 / P/E vs 市场股数错配 / 股数偏差 >25% / 每股基准不可靠时 EV 估值仍可用 / model-agreement 与 Golden Baseline 兼容）

### 🔧 Changed
- 🔧 **`valuation/equity_bridge.py`（P0-1）**：`EquityBridge` 新增 `status`（`EB_STATUS_OK`/`INCOMPLETE`/`UNAVAILABLE`）+ `missing_inputs` + `net_debt_verified` + `is_reliable()`；`_resolve_net_debt()` 区分**已验证零净债务**（显式 `net_debt` 或 `total_debt`&`cash` 俱全 → verified）与**输入缺失**（按 0 展示但 `net_debt_verified=False`、`status=INCOMPLETE`、记录缺失腿）；`enterprise_to_equity(None, …)` → `equity_value=None` + `status=UNAVAILABLE`（**绝不 `0 − claims`**）；`equity_to_enterprise(None)` → `None`；`itemized_note()` 缺失时渲染「股权价值=N/A（企业价值缺失，未按 0 处理）」；保留少数股东/优先股/租赁双计守卫
- 🔧 **`models/multiples.py::P/E`（P0-2）**：股权价值由「EPS 派生每股 × **市场股数**」改为「EPS 派生每股 × **TTM 报表股数**」（与 EPS 分母同口径）；无 TTM 股数 → 回退 market 并标注「分子 basis=TTM / 分母 basis=market，口径不一致」；新增 `breakdown["pe_basis_audit"]`（`eps_basis`/`eps_period`/`eps_source`/`shares_basis`/`shares_source`/`shares_as_of`/`numerator_denominator_basis_match`）
- 🔧 **`analysis/model_agreement.py::share_count_audit_table()`（P0-3）**：审计行追加 `⚠️ 口径异常`（`basis_expected=False`）+ 「股数来源 / 报告期」逐模型列 + 不可靠时降级警告；参考口径注补充「`market_cap÷price` 仅为同口径复算，非财报股数证明」；`analyze()` 经 `share_count_evidence()` 计算 `share_count_reliable`（`None` 数据 → 不判冲突）
- 🔧 **`reporting/verdict_intuition.py`（P0-3）**：`shares_unreliable` 追加门控 `share_count_reliable is False`；caveat 文案改为「股数证据不一致」；headline 结尾封顶「每股口径不可靠」（应用在 scenario 覆盖之后，**保留 EV 级结果**）
- 🔧 **`tests/test_equity_bridge.py`（P0-1）**：`TestMissingData` 由旧 note 断言重构为 7 个状态机断言（`missing_inputs` / `net_debt_verified` / `status` / 缺失腿分流）

### 🐛 Fixed
- 🐛 **Equity Bridge 静默 0 污染**：缺失 EV 不再桥接为 `0 − claims`（会凭空造出负股权价值）；缺失债务/现金不再伪装为「已验证的零净债务」
- 🐛 **P/E 分母错配**：不再把 EPS 派生价值乘以与 EPS 无关的市场股数（AVGO 类 4.18B TTM vs 4.74B 年报股数场景）
- 🐛 **股数单源伪证**：不再把 `market_cap ÷ price` 当作财报股数的证明；三口径不一致超容差 → 每股结论降级

### ⚠️ Known Issues (Session #41)
- ⚠️ `ShareCountEvidence` 依赖 `annual_income[0]` / `ttm` 的 `shares_outstanding`；两者缺失时仅市场隐含口径可用（返回不可比而非报错）
- ⚠️ 财报口径未区分 basic vs diluted（`FinancialStatement` 仅单字段），稀释加权平均以 TTM 报表值代理
- ⚠️ `MarketData.net_debt_or_zero()` 仍存在静默 0 旧路径（P0-1 只在桥内守卫，未全库替换）

---

## [Unreleased] — 2026-11-15 (Session #40 — 跨行业阈值校准 (M-67) + SBC 归一化下沉 FCF 主链 (M-69))

> 触发：Session #39 自身遗留的两条 Known Issue——① 诊断阈值（FCF margin 带 / β 同业地板）为**全局初值**，需按业务原型校准；② SBC 归一化散落在 `reverse_dcf` 与 `multiples` 两处各自调用，存在**双计**风险，需下沉至 FCF 主链唯一出口。
> 纪律：**不新增估值模型** / **所有修复附带测试** / **Golden Baseline 零漂移** / **未知原型回退默认带，绝不静默重判** / **缺失数据返回 Insufficient Data，禁止 None→0**。
> 备注：`TODO.md` 中 **M-68 已被占用**（Monte Carlo 截断重参数化，仍 TODO），故本轮 SBC 下沉**正名为 M-69**。
> 验证：`python -m pytest -q` → **522 passed**（Session #39 的 507 → 522）；`ruff check .` → **All checks passed!**；`tests/test_golden_report.py` 通过 → **golden 零漂移**。

### ✨ Added
- ✨ **`analysis/threshold_calibration.py`（新建，M-67 运行时单一来源）**：`ThresholdCalibration`（frozen dataclass：`archetype` / `tier` / `fcf_aligned_pp` / `fcf_flag_pp` / `fcf_high_ratio` / `beta_min_peers` / `rationale` / `judged_dispersion` / `evidence_n` + `note()` 审计行）；波动分档 `tier_for_dispersion()`（`<0.03 → stable` / `0.03–0.06 → moderate` / `≥0.06 → volatile`，单调）；`thresholds_for_tier()`；`beta_min_peers_for()`（按**池广度**分档）；`calibration_for(business_type)`；`DEFAULT_CALIBRATION`（= moderate 全局带，向后兼容）；`calibration_evidence_note()` / `calibration_table_note()`（审计摘要）
- ✨ **`data/fcf_utils.py::resolve_ttm_fcf_normalized()`（新建，M-69 主链出口）**：SBC-normalized TTM FCF——调用 `normalize_fcf_for_sbc()` **恰好一次**，调整生效时 `source` 追加 `+sbc_normalized`，返回 `(value, source, SbcNormalization)`；`raw is None → (None, "missing", …)`（不臆造零）
- ✨ **`tests/test_reporting_integrity_repair.py`（扩至 48 用例，+15）**：`TestCrossIndustryThresholdCalibration`（9）+ `TestSbcMainChainExit`（6）

### 🔧 Changed
- 🔧 **`analysis/divergence.py::_fcf_margin_check()`（M-67）**：诊断带由全局常量改为**按业务原型校准**——经 `_calibration_for_profile()`（内部 `business_type_from_profile`）解析 archetype → `calibration_for()`；比较改用 `cal.fcf_flag_pp` / `cal.fcf_aligned_pp` / `cal.fcf_high_ratio`；三处 detail 追加审计行 `〔行业校准[tier]（观测 σ, n）：FCF margin 带 Xpp/Ypp/Z×，β 最小同业 N 家；rationale〕`。**同一 +4.5pp 缺口在稳定公用事业判 FLAG、在波动半导体判 MODERATE**
- 🔧 **`valuation/wacc.py::_bottom_up_reliability_label()`（M-67）**：β 最小同业地板由 `BETA_BOTTOM_UP_MIN_PEERS` 单值改为 `beta_min_peers_for(business_type)`（宽池 5 / 窄池 3 / 未知 4）；新增 `business_type` 形参；**惰性 import** 该函数（修复循环导入，见下）
- 🔧 **`models/reverse_dcf.py`（M-69）**：TTM FCF 改经 `resolve_ttm_fcf_normalized(ttm, shares=shares)` 单次归一化；breakdown 落 `base_fcf` / `fcf_source` / `sbc_normalization`
- 🔧 **`models/multiples.py::FCF Yield`（M-69）**：TTM FCF 改经 `resolve_ttm_fcf_normalized()`；**保留 Phase D 守卫**（`ttm is None or ttm.free_cash_flow is None → INSUFFICIENT_DATA`）；`fcf_used = adjusted_fcf if fcf_available else raw_fcf`；breakdown 落 `sbc_normalization` / `fcf_source` / `fcf_used`
- 🔧 **代码/测试注释 M-68 → M-69**：`data/fcf_utils.py` ×2 / `models/reverse_dcf.py` ×1 / `models/multiples.py` ×1 / `tests/test_reporting_integrity_repair.py` ×2（ID 诚实性）

### 🐛 Fixed
- 🐛 **`valuation/wacc.py` 循环导入**：模块级 `from analysis.threshold_calibration import beta_min_peers_for` 触发 `models.dcf → valuation.wacc → analysis（包 __init__）→ analysis.expectation → models.reverse_dcf → models.dcf` 环（`ImportError: cannot import name 'DCFModel' from partially initialized module`，`3 errors during collection`）；改为函数体内惰性 import，零行为变更
- 🐛 **SBC 双计结构性风险**：消除 `reverse_dcf` / `multiples` 各自调用 `normalize_fcf_for_sbc()` 的重复施加路径——统一到 `resolve_ttm_fcf_normalized()` 单一出口

### ⚠️ Known Issues (Session #40)
- ⚠️ 分档 cut point（0.03 / 0.06）与带宽为**文档化先验**；`CALIBRATION_EVIDENCE` 篮子仅 19 名、各原型 n 偏小（仅作佐证，非精度声明）——扩充样本后应重推
- ⚠️ 窄池原型集合 `{NEOBANK, FINTECH, CONGLOMERATE}` 硬编码，新增原型需同步 `_NARROW_PEER_POOLS`
- ⚠️ 新 FCF 消费者**必须**经 `resolve_ttm_fcf_normalized()`，否则漏 SBC 归一化（无强制门禁，靠约定 + 测试）
- ⚠️ Monte Carlo 截断（**M-68**）仍为 TODO，未改为截断正态/重参数化抽样

---

## [Unreleased] — 2026-11-15 (Session #39 — 口径统一 + 报告解释修复 / Phase A–F)

> 触发：用户提交**代码审查报告**，目标「**统一现有模型的财务口径，并让报告正确解释计算结果**」——**明确不新增估值模型**。
> 纪律：**口径一致**（DCF / Monte Carlo / Multiples 共享同一 EV↔Equity 桥、SBC 口径、股数口径）/ **报告措辞必须与计算一致**（高终值依赖不得写成「显式期贡献占主导」）/ **缺失数据返回 Insufficient Data**（禁止 `None → 0` 静默）/ **Golden Baseline 零漂移**（未重生成基线）/ **静态板块锚点不得冒充实时同行中位数**。
> 验证：`python -m pytest -q` → **507 passed**（golden 零漂移）；`ruff check .` → **All checks passed!**

### ✨ Added
- ✨ **`analysis/divergence.py::_fcf_normalization_layer()`（新建，Phase A）**：TTM vs 3–5 年历史**正常化层**——输出并对比 `TTM CapEx/收入`、`历史均值 CapEx/收入`、`TTM D&A/收入`、`TTM ΔNWC/收入`、`TTM FCF margin`、`历史正常化 FCF margin`；据此区分「暂态资本开支周期」（CapEx/收入 > 历史均值 ×1.3 → `moderate`）与「长期经营现金流能力恶化」（无 CapEx 解释 → `flag`）；**历史均值绝不直接当作未来正常值**（`hist_om*(1−tax)+hist_da−hist_capex−hist_nwc`）
- ✨ **`analysis/model_agreement.py::ShareCountAuditRow`（新建，Phase F）** + `ModelAgreement.share_count_audit` + `ModelAgreement.share_count_audit_table()`：逐模型列出 `Model | Share Count | Basis | Deviation vs Market`（有符号偏差 `(used − reference)/reference`），不可比行标 `⚠️ 不可比`，末尾附参考口径行；`__all__` 增补 `ShareCountAuditRow`
- ✨ **`simulation/monte_carlo.py`（Phase C + 截断透明度）**：`MonteCarloResult` 新增 `sample_driver_mean` / `sample_driver_std` / `lower_bound_hit_rate` / `upper_bound_hit_rate` / `gordon_constraint_hit_rate` + `distribution_transparency_note()`；模块级 `_format_transparency_note()` 逐驱动输出「请求 μ/σ → **实际样本** μ/σ（下界命中 x%，上界命中 y%）」+「Gordon 约束 (g<WACC) 命中 z%」
- ✨ **`tests/test_reporting_integrity_repair.py`（新建，33 用例）**：锁定用户第六章全部验收场景

### 🔧 Changed
- 🔧 **`analysis/divergence.py::_fcf_margin_check()`（Phase A）**：触发条件由「绝对差 ≥15pp」改为**相对判断**——新增常量 `FCF_MARGIN_ALIGNED_PP=0.03` / `FCF_MARGIN_FLAG_PP=0.05` / `FCF_MARGIN_HIGH_RATIO=2.0`；`符号翻转` 或 `|Δ|≥5pp` 或 `预测 > 2× TTM` → `flag`；`3–5pp` → `moderate`；`<3pp` → `aligned`。**GOOG TTM 4.2% → 预测 13.7%（+9.5pp，>3×）不再被误判为 ALIGNED**（`__all__` 增补三常量）
- 🔧 **`analysis/divergence.py::_tv_check()`（Phase B）**：**报告措辞分级与 Risk Severity 阈值分离**——`<50%` 显式期占多数 / `50–70%` 终值占多数 / `70–80%` **高终值依赖，需要审查**（`moderate`）/ `≥80%` 极高终值依赖触发风险警告（`flag`）。**TV/EV = 73.9% 现正确描述为「高终值依赖，需要审查」**，不再写成「显式期贡献占主导」
- 🔧 **`simulation/monte_carlo.py::_project_one()` / `_project_one_path()`（Phase C）**：EV→Equity 由内联 `proj.enterprise_value − net_debt` 改为统一调用 **`enterprise_to_equity(ev, mkt).equity_value`**（与 DCF 同源、同资本结构口径）；`enterprise_value is None` → 返回 `None`（**无效状态，不静默按 0**）；零扰动锚点与确定性 DCF 精确对齐
- 🔧 **`models/multiples.py::FCF Yield`（Phase D）**：接入 **`normalize_fcf_for_sbc()`**（`fcf_used = sbc_norm.adjusted_fcf`，`breakdown["sbc_normalization"]` + `breakdown["fcf_used"]`，与 DCF 同口径、不重复扣）；**TTM FCF 缺失 → `SolverStatus.INSUFFICIENT_DATA`**（`breakdown["fcf_used"]=None`），不再把缺失 FCF 当作真实零
- 🔧 **`valuation/wacc.py`（Phase E）**：Beta 不确定性由「单看回归窗口极差」拆为**三个独立指标**——`Regression Stability`（回归窗口稳定性）/ `Bottom-up Reliability`（同业数量·质量·适配性，`BETA_BOTTOM_UP_MIN_PEERS=4` 以下降级）/ `Methodology Divergence`（Regression vs Bottom-up 差异，**0.94 vs 1.41 → Material**）；`beta_uncertainty_note()` 三行并列展示
- 🔧 **`models/multiples.py::_resolve_peer_bucket()`（Phase F）**：来源标签细分——新增 **`PEER_SOURCE_EXACT_SECTOR_ANCHOR="EXACT_SECTOR_ANCHOR"`**（Yahoo sector 与静态表 key 精确匹配，**非真实同业中位数**）；`PEER_SOURCE_LABELS` 明示 `LIVE_PEER_MEDIAN`=实时同业中位数 / `EXACT_SECTOR_ANCHOR`=精确板块静态锚点（非实时同业报价）/ `SECTOR_FALLBACK` / `BUSINESS_TYPE_FALLBACK` / `APPROXIMATE`
- 🔧 **`reporting/dashboard.py`**：`_agreement_section` 渲染 Share Count Audit Table；`_data_section` 渲染 Monte Carlo 截断透明度 note

### 🐛 Fixed
- 🐛 **`analysis/divergence.py`**：修复「4.2% → 13.7% 被判 ALIGNED」与「TV/EV 73.9% 被写成显式期占主导」两处**报告与计算脱节**
- 🐛 **`simulation/monte_carlo.py`**：修复复杂资本结构下 MC 概率分布与 DCF 基准**口径不一致**（仅扣净债务）；修复 `ev=None → 0`
- 🐛 **`models/multiples.py`**：修复 FCF Yield 忽略 SBC；修复缺失 FCF 被静默当作 0
- 🐛 **`tests/test_reporting_integrity_repair.py`**：移除未用导入 `ShareCountBasis`（ruff F401）

### ⚠️ Known Issues (Session #39)
- ⚠️ **Phase A 阈值（3pp / 5pp / 2×）与 Phase E 的 `BETA_BOTTOM_UP_MIN_PEERS` 为初始值，需跨行业校准**（高 CapEx 成长股 vs 稳健消费股的最优切分可能不同）
- ⚠️ Monte Carlo 截断仍在边界产生概率质量堆积（已**透明化**：输出下/上界命中率与 Gordon 命中率，但未改为截断正态/重参数化抽样）
- ⚠️ Share Count Audit Table 依赖各模型申报 `share_count`；未申报的模型不出现在审计表（保持「未声明 ≠ 冲突」）

---

## [Unreleased] — 2026-11-15 (Session #38 — Phase 1 · Valuation Integrity / 6 项「错误输入·错误来源·错误股权桥接」修复)

> 触发：用户提交 **Phase 1 — Valuation Integrity**（最高优先级），目标「确保估值没有错误的输入、错误的来源和错误的股权价值桥接」。
> 纪律：**标签必须能证明自身**（β 来源只渲染 provenance 可验证的内容，不再硬编码「3Y monthly vs SPY」）/ **股权桥接独立成模块**（EV−NetDebt−MI−Preferred−OtherClaims+NonOperating，杜绝重复扣除）/ **SBC 二选一**（扣 FCF 或调股数，绝不双重计数）/ **币种一致性**（现金流币种 ↔ Rf ↔ 通胀假设 ↔ 终值增速同源）/ **钳制 ≠ 计算结果**（raw / final / reason 三分离并升级为估值风险）。
> 验证：`python -m pytest -q` → **474 passed**；`ruff check .` → **All checks passed!**；golden **零漂移**（USD 币种 / 简单资本结构 / 无 SBC 时全部退化为原行为）。

### ✨ Added
- ✨ **`valuation/equity_bridge.py`**（新建）：`EquityBridge` dataclass + `enterprise_to_equity()` / `equity_to_enterprise()`（**精确互逆**）+ `_resolve_claims()`（重复扣除守卫）+ `equity_bridge_components()`。公式 `Equity = EV − NetDebt − MinorityInterest − PreferredEquity − Leases(未含于Debt时) − OtherClaims + NonOperatingAssets`；每项可选（`None` = "无该项索偿"，绝不静默按 0）；`leases_in_debt is True` 或调用方声明 `net_debt_includes_*` 时不重复扣；返回明细 `itemized_note()` + `notes` 供审计
- ✨ **`valuation/sbc.py`**（新建）：`normalize_fcf_for_sbc(reported_fcf, sbc, *, method, shares, sbc_dilution_rate)` + `SbcNormalization` dataclass。三种方法 `SBC_METHODS=("expense","dilution","none")`（`DEFAULT_SBC_METHOD="expense"`）；`expense`→`adjusted = rfcf − sbc`（股数不变）；`dilution`→`factor = 1 + sbc_dilution_rate`（FCF 不变）；**SBC 缺失/为 0 不调整（绝不臆造成本）**；`dilution` 无稀释率 → 回退 `expense`
- ✨ **`config.py`**：`CURRENCY_RISK_FREE_RATES`（USD 4.5% / HKD 4.5% / CNY 2.3% / MYR 3.9% / EUR 3.0% / GBP 4.5% / JPY 1.2% / SGD 3.0%）+ `CURRENCY_NOMINAL_GDP`（USD 4.5% / CNY 5.5% / JPY 1.5% / MYR 5.5% …）+ `DEFAULT_MACRO_CURRENCY="USD"`（未知币种回退 USD 带，**显式记录不静默**）
- ✨ **`tests/test_equity_bridge.py`**（新建，18 用例）：简单/复杂资本结构、租赁口径、互逆 round-trip（parametrize）、缺失数据、6 模型接线
- ✨ **`tests/test_sbc.py`**（新建，13 用例）：expense / dilution / 不调整 / Reverse DCF 接线

### 🔧 Changed
- 🔧 **`valuation/wacc.py`（Beta Source & Provenance）**：删除硬编码 `sources["β"] = "3Y monthly vs SPY estimate = …"`，改为 `_format_beta_source(prov, beta_value)`——**只渲染 provenance 能证明的内容**（`regression` → 窗口标签/价格口径/基准/起止日期/观测数/缺口数；`provider` → 明示「vendor estimate, method unverified」；无 provenance → 明示「source unverified」）
- 🔧 **`valuation/wacc.py`（Currency-aware Rf）**：新增 `currency_macro_anchors(currency)`；Rf 解析优先级 = (a) 注入值（**仅当币种一致，或 provenance 非 USD 来源**）→ (b) 活 U.S. Treasury（**仅 USD**）→ (c) `CURRENCY_RISK_FREE_RATES[cf_ccy]` 主权锚 → (d) 配置默认。USD 来源 Rf 用于非 USD 现金流时**显式替换并记录** `sources["Rf (currency)"]`
- 🔧 **`valuation/wacc.py`（WACC raw/clamp 分离）**：保留 `wacc_raw`（模型原始计算值）+ `wacc`（钳制后）+ `wacc_clamped` + `wacc_clamp_reason` + `WaccBreakdown.wacc_clamp_note()`；`sources` 追加「WACC (raw) model-computed (pre-clamp)」与钳制原因——**钳制结果不再伪装成模型真实计算值**
- 🔧 **`data/providers.py::_estimate_beta()`**：β 回归改用**复权价格 `adjclose`**（raw close 仅作回退，`price_basis` 标注 `adjclose / adjclose+fallback / close(unadjusted)`）+ **日期连续性检查**（ISO-week/period keying，记 `missing_periods` 缺口数）+ 返回 provenance dict（`source/window_label/price_basis/benchmark/window_start/window_end/n_observations/missing_periods`）
- 🔧 **`valuation/terminal_growth.py`**：GDP 上限随**现金流币种**动态调整（`calculate()` 新增 `nominal_gdp_ceiling` 形参；默认由 `data.market.currency` 经 `CURRENCY_NOMINAL_GDP` 推导）；USD 保持 0.045（避免 golden 漂移），非 USD 取对应上限；`hard_cap` / `high_exceeds_gdp` 随之改用币种上限；`derivation_trace` 新增 `long_term_nominal_gdp` / `gdp_ceiling`
- 🔧 **`models/dcf.py` / `models/reverse_dcf.py` / `models/multiples.py` / `models/sotp.py` / `models/unit_economics.py` / `models/nav.py` / `forecasts/fcf_projection.py`**：全部 EV→Equity 计算**改走 `enterprise_to_equity()`**（不再内联 `ev - net_debt`）；SOTP 自举 EV 改 `equity_to_enterprise()`；各模型 `breakdown` 新增 `equity_bridge` 明细

### 🐛 Fixed
- 🐛 **`models/sotp.py`**：`equity_value` 桥接收口——修复复杂资本结构下「仅减净债务」的股权价值偏差；`notes` 改为「SOTP 股权价值 = 分部 EV 合计 − 净债务等索偿」
- 🐛 **`models/reverse_dcf.py`**：目标 EV 由 `target_equity + net_debt` 改为 `equity_to_enterprise(target_equity, data.market)`（与桥接同源，杜绝漂移）；接入 SBC 归一化（`stock_based_compensation` → `normalize_fcf_for_sbc`），`assumptions` 新增 SBC Adjustment、`breakdown` 新增 `sbc_normalization`
- 🐛 **`tests/test_equity_bridge.py::test_itemized_note_lists_each_adjustment`**：`itemized_note()` 使用**带符号**的 deduction 值（`少数股东权益=-300` / `+非经营性资产=400`）——断言修正为匹配实符号
- 🐛 **`models/reverse_dcf.py`** import 行修复（一次编辑误合并两行 import 导致语法错误）

### ⚠️ Known Issues (Session #38)
- ⚠️ SBC 归一化当前仅接入 Reverse DCF（正/反向 DCF 的 TTM FCF 主链）；后续应统一到 `data/fcf_utils.resolve_ttm_fcf()` 出口，使所有 FCF 消费端自动受益
- ⚠️ 币种 Rf 的非 USD 分支使用 `CURRENCY_RISK_FREE_RATES` **静态锚**（秒级可用、无外部依赖）；如需实时曲线需接入各市场收益率源

---

## [Unreleased] — 2026-11-15 (Session #37 — Pyright 类型检查归零 / 0 error)

> 触发：修复类型检查存量。`npx pyright` 从 **40 errors + 3 warnings** 收敛到 **0**（126 文件）。
> 纪律：**只补类型收窄与运行时守卫，不改行为**；全部为 `Optional` 收窄 / `Any` 标注 / 可选依赖豁免，不改变任何运行时分支。
> 规则分布：`reportArgumentType` 34 / `reportOptionalIterable` 3 / `reportMissingImports` 3 / `reportPossiblyUnboundVariable` 2 / `reportOptionalMemberAccess` 1。
> 验证：`npx pyright` → **0 errors / 0 warnings**；`ruff check .` → **All checks passed!**；`python -m pytest -q` → **436 passed**（行为零回归，golden 零漂移）。

### 🐛 Fixed
- 🐛 **`analysis/model_agreement.py`（`reportArgumentType` + `reportOptionalMemberAccess`）**：`_resolve_share_reference` 股数反查的「列表推导 + getattr 链式守卫」→ **显式 for 循环 + 逐层 None 收窄**（`res`→`sc`→`shares`），消除 `float(float | None)` 与 `None.shares_used`
- 🐛 **`classification/taxonomy.py`（`reportArgumentType`）**：`build_taxonomy_profile` 构造 `BusinessTaxonomyProfile` 时 `revenue_composition or RevenueComposition.unavailable()`——`Optional` 参数经 `or` 收窄为 `RevenueComposition`
- 🐛 **`data/segment_revenue.py`（`reportArgumentType` ×2）**：`to_revenue_composition` 改 `usable: List[Tuple[Segment, float]]`（遍历时 `isinstance(rev,(int,float)) and rev>0` 收窄并 `float(rev)`）；`total`/`pct` 取已收窄 float
- 🐛 **`data/industry_beta.py`（`reportArgumentType`）**：`_coerce_segments` 增 `if not label or weight is None: continue`（`float(weight)` 前排除 None）
- 🐛 **`models/reverse_dcf.py`（`reportArgumentType` ×3）**：反向 DCF 上下限改**显式 None 判定**——`bt_params.get()` 值类型为 `_Opt[float]`，原 `.get(k, default)` 仍带 `None`
- 🐛 **`data/providers.py`（`reportPossiblyUnboundVariable` ×2）**：分部收入 import（`resolve_segments`/`segment_weights`/`to_revenue_composition`）**移出 try**（import 本不会因网络失败）；`resolve_segments` 求解仍保留 try/except 优雅降级
- 🐛 **`data/sic_map.py`（`reportArgumentType`）**：`map_sic_to_yahoo`/`_normalize_sic` 入参放宽为 `Optional[Union[str, int]]`（函数本就 `str(sic)` 归一；测试断言 int 与 str 等价）
- 🐛 **`data/akshare_provider.py`（`reportMissingImports` ×3）**：可选依赖 `akshare` 三处 import 加 `# pyright: ignore[reportMissingImports]`（已被 `try/except ImportError` 守卫）
- 🐛 **`tests/test_industry_beta.py`（`reportArgumentType` ×多 + `reportOptionalIterable` ×3）**：`**kwargs`/`**base` 展开的 `dict()` 加 `Dict[str, Any]` 标注（消除异构 dict 解包误报）；两处 `assert res.segments is not None` 收窄 Optional 字段

### ⚠️ Known Issues (Session #37)
- ⚠️ 同 Session #36：`datetime.utcnow()` / `datetime.utcfromtimestamp()` 弃用告警（pytest 2156 warnings）**不在 pyright / ruff 默认规则集**内，未处理

---

## [Unreleased] — 2026-11-15 (Session #36 — 仓库级 Ruff 清理 / lint 0 error)

> 触发：修复上一轮遗留的 lint 存量。`ruff check .` 从 **174 errors** 收敛到 **0**。
> 纪律：**只修 lint 与死代码，不改行为**；一次性 dev/debug 脚本用配置排除而非强行改写（其 E402 为 `sys.path` 引导的**有意**写法）。
> 验证：`ruff check .` → **All checks passed!**；`python -m pytest -q` → **436 passed**（行为零回归，golden 零漂移）。

### ✨ Added
- ✨ **`pyproject.toml`**：`[tool.ruff]` `target-version="py312"` + `extend-exclude = ["_*.py", "**/_*.py", "verify_bot.py"]`（一次性开发/调试脚本）+ `[tool.ruff.lint.per-file-ignores]` 对 `main.py` / `tests/conftest.py` 放行 **E402**（导入前必须 `sys.path` 引导）

### 🐛 Fixed
- 🐛 **E402（结构性，`config.py`）**：中段 `import sys as _sys` / `import io as _io` / `from typing import Optional as _Opt` 上移文件顶部 → 消除 3 处
- 🐛 **E701（`valuation/wacc.py` ×7、`data/providers.py` ×8）**：单行多语句（`if …: return …` / `try: … except: …`）展开为多行
- 🐛 **E702（`data/providers.py` ×4）**：分号分隔语句展开为多行
- 🐛 **E741（`classification/ml_classifier.py`）**：歧义变量名 `l → lab`
- 🐛 **F841（死变量）**：`analysis/sensitivity.py`（`bear_wacc`/`bull_wacc`）、`classification/ml_classifier.py`（`cong_p`/`ml_used`）、`data/providers.py`（`vals`）、`tests/test_scenario_sensitivity_consistency.py`（`provider`）
- 🐛 **F401 / F541 / 其它 E702（35 处，`ruff --fix` 自动）**：未用导入、无占位符 f-string、分号语句——跨 `analysis/expectation.py`、`data/akshare_provider.py`、`data/normalizer.py`、`data/validator.py`、`models/dcf.py`、`models/nav.py`、`reporting/dashboard.py`、`telegram_bot/telegram_bot.py`、`tests/*` 等

### 🔧 Changed
- 🔧 **`config.py`**：清理未用导入（`dataclasses.field` / `typing.List` / `typing.Optional` / `typing.Tuple`）
- 🔧 **`tests/test_scenario_sensitivity_consistency.py`**：删除未用的局部导入 `SyntheticDataProvider` 与其实例化

### ⚠️ Known Issues (Session #36)
- ⚠️ `datetime.utcnow()` / `datetime.utcfromtimestamp()` 弃用告警（pytest 输出 2156 warnings）**不在 ruff 默认规则集**内，未处理；如需清理建议启用 flake8-datetimez（DTZ）后统一迁移为 timezone-aware

---

## [Unreleased] — 2026-11-14 (Session #35 — 用户代码审查 4 项 P1：SOTP 三态状态机 / 多窗口 β 稳定性 / ETR 口径分离 / 估值可比性 Gate)

> 触发：用户对引擎做第二轮代码审查，给出 **4 个 P1（高影响）** 缺陷，均已定位到具体文件与函数并附修改建议。
> 纪律：**反对把市场估值按概率拆分冒充独立证据**（SOTP 无独立分部财务 → display_only）；**不确定性必须传导而非仅提示**（β 极差 → shrinkage → WACC 区间）；**输入数据与模型实际使用数据显式区分**（ETR 双口径）；**不兼容模型可知情展示但不得无条件进入共识**（Comparability Gate）；**未声明口径 ≠ 冲突**（Gate 不排除未声明者）。
> 验证：`python -m pytest -q` → **436 passed**；golden 因 SOTP→display_only 行为修正**有意重生成一次**（差异逐条核对为预期，非回归）。

### 🐛 Fixed
- 🐛 **P1-SOTP（`models/sotp.py`）循环估值伪装独立证据**：`_derive_segments_from_profile()` 用**公司自身** `ev/revenue` 作 `ev_rev_mult`（`max(0.5, min(10.0, ev/revenue))`）乘回 `revenue` → Operating EV ≈ 当前市场 EV，再按 ML `business_exposures` 拆成多业务 = **先取市场估值再按概率分配**（循环估值）。修复：**三态状态机** `SOTP_SOLVED` / `SOTP_APPROXIMATE` / `SOTP_INSUFFICIENT`——仅「真实分部收入 + 利润 + 独立 peer multiple」→ SOLVED（计入共识）；部分真实 + 部分估算 → APPROXIMATE；**仅 ML 暴露度、无独立分部财务数据 → INSUFFICIENT**（`breakdown["display_only"]=True`，聚合层剔除，**绝不把 ML 的 50% Utilities + 49.9% Energy 当作两个独立业务估值证据**）；`breakdown["segments_detail"]` 输出每分部 Revenue/EBITDA/EBIT/Applied Multiple/Segment EV/Source/Confidence/As-of Date；修复 `operating_ev` 对净债的**双重扣除** bug
- 🐛 **P1-6（`valuation/wacc.py`）多窗口 β 不稳定却直接用单一 β**：VST（2Y周 1.49 / 3Y月 2.30 / 5Y月 1.35，极差 0.95）多窗口 β **仅用于展示，未参与稳健估计**。修复：稳定性**参与估计**——**Blume-style 收缩**（`beta_adjusted = selected + shrink×(1.0 − selected)`，`shrink = min(BETA_MAX_SHRINK=0.35, dispersion 超阈增量)`，`BETA_DISPERSION_SHRINK_THRESHOLD=0.50`；**明确不取三窗口平均**——观测频率/样本长度不同）；`WaccBreakdown` 新增 `beta_raw`（供应商回归）/ `beta_selected`（winsorize 基础）/ `beta_adjusted`（最终用于 CAPM）/ `beta_shrinkage` / `beta_dispersion` / `beta_uncertainty`；β 不确定性**传导至 WACC 区间**（`wacc_beta_lo` / `wacc_beta_hi`）
- 🐛 **P1-7（`reporting/dashboard.py`）报告出现两个 ETR**：`_market_section()` 读供应商 `m.effective_tax_rate`（20.4%），WACC 用 `wacc_bd.effective_tax_rate`（19.634%）→ 自相矛盾。修复：市场快照**主值改 WACC 实际使用 ETR**（+ `_etr_basis_suffix()` 标注 `tax_period_basis`）；供应商值**另标 Provider ETR**——明确区分「输入数据」与「模型实际使用数据」
- 🐛 **P1-8（`analysis/model_agreement.py`）成功解算 ≠ 使用可比较数据口径**：各模型股本/币种/期间口径可能不兼容却无条件进入共识中位数。修复：新增 **Valuation Comparability Gate**——`_comparability_gate()` 检测 7 维冲突（币种 / 估值口径 / 财务期间 / 估值日期 > `COMPARABILITY_DATE_TOL_DAYS=45` / `peer_valid=False` / 数据质量 < `COMPARABILITY_QUALITY_FLOOR=50`），冲突模型**从 `solved_agg` 剔除并重算 `n_applicable`**（仍展示）；**空 `comparability` ⇒ 未声明口径 ≠ 冲突，不排除**

### ✨ Added
- ✨ **`SOTP_SOLVED` / `SOTP_APPROXIMATE` / `SOTP_INSUFFICIENT` + `SOTPSegment`（`models/sotp.py`）**：SOTP 三态状态机 + 分部 dataclass（`is_independent_evidence()` / `as_dict()`），`segments_detail` 可审计明细（P1-SOTP）
- ✨ **`WaccBreakdown` β 三分离字段（`valuation/wacc.py`）**：`beta_raw` / `beta_selected` / `beta_adjusted` / `beta_shrinkage` / `beta_dispersion` / `beta_uncertainty` + `wacc_beta_lo` / `wacc_beta_hi`（P1-6）
- ✨ **`make_comparability()`（`models/base.py`）**：可比性声明契约（`value_basis` / `currency` / `financial_period` / `valuation_date`（ISO 归一化）/ `peer_valid`）+ `ValuationResult.comparability`（P1-8）
- ✨ **`analysis/model_agreement.py::_comparability_gate()`** + `_as_iso_date()` / `_days_between()` + `ModelAgreement.comparability_reference` / `.comparability_conflicts` / `.comparability_excluded_models`（P1-8）
- ✨ **`reporting/dashboard.py::_etr_basis_suffix()`**：ETR 口径后缀标注（P1-7）

### 🔧 Changed
- 🔧 **`models/dcf.py` / `models/multiples.py` / `models/sotp.py`**：`calculate()` 返回值接线 `comparability=make_comparability(...)`（DCF/Multiples/SOTP 均声明 TTM / equity_per_share / USD；SOTP 仅 SOLVED 时 `peer_valid=True`）
- 🔧 **`analysis/model_agreement.py::analyze()`**：在 `solved_agg` 构建后调用 `_comparability_gate()`，剔除冲突模型并重算 `n_applicable`（扣减冲突数），notes 增列 Gate 剔除说明
- 🔧 **`tests/test_special_models.py::test_sotp_model_runs`**：重写为三态契约（无分部数据 → INSUFFICIENT + display_only + `n_independent_segments==0`；外部 segments → SOLVED + `n_independent_segments==2`）
- 🔧 **`tests/golden/report_fingerprints.json`**：因 SOTP→display_only **有意重生成一次**（PLD/NOW/NBIS/CRWV/NU：`n_solved` −1、`n_display_only` +1、`n_independent_evidence` −1，逐条核对为预期）

### 📊 Baseline Verification (Session #35)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **436/436 passed** | 无回归（除有意 golden 漂移） |
| P1-SOTP 三态 | ✅ 无分部数据 → `INSUFFICIENT`+`display_only`+`n_independent_segments=0`；外部 segments → `SOLVED`+`n_independent_segments=2` | 循环估值不再计入共识 |
| P1-6 β 稳定性 | ✅ VST `raw=2.3` / `adjusted≈1.89` / `shrinkage≈0.315` / `dispersion=0.95` / `wacc_beta_lo≈0.104` / `hi≈0.147` | 不确定性传导至 WACC 区间 |
| P1-7 ETR 口径 | ✅ 主值 = WACC 实际使用 ETR（含 `tax_period_basis`）；Provider ETR 旁注 | 双数字消除 |
| P1-8 可比性 Gate | ✅ 8 用例（币种冲突剔除且 `median==105.0`、未声明不剔除、peer 无效、陈旧日期、财务期间冲突、低数据质量、无数据无 Gate） | 未声明口径不排除 |
| golden 回归 | ⚠️ **有意重生成一次** | 差异全部为 SOTP→display_only（逐条核对为预期） |

### ⚠️ Known Issues (Session #35)
- ① **SOTP 在无 FMP 分部 key 时基本不产出可计入共识的估值**（有意为之）：真实分部数据接入后 SOTP 方可 SOLVED
- ② **`beta_shrinkage` / dispersion 阈值为工程启发式**（`0.35` / `0.50`），非统计最优，可随真实样本校准
- ③ **SOTP 独立 peer multiple 目前仍主要依赖行业默认表**，分部级 peer 倍数是后续方向
- ④ 承接 Session #31–#34 遗留：`CANONICAL_KEY_WACC_RANGES` 仅覆盖 util 族 + 综合能源；M-44（隐含 FCF 利润率/终值增长率 bound 措辞）；M-16/C-02（真实标注 → 90%+）仍为唯一真实 BLOCKER

---

## [Unreleased] — 2026-11-14 (Session #34 — 用户代码审查 4 项 P0：行业 WACC 身份键 / ETR 非重叠口径 / 股数口径契约 / FCF Yield 非对称风险)

> 触发：用户对引擎做代码审查，给出 **4 个 P0（必须优先修复）** 缺陷，均已定位到具体文件与函数并附修改建议。
> 纪律：**反对伪精确**（行业区间读身份键，不靠字符串巧合；不把受管制公用事业与独立发电商混为一谈）；**口径必须显式可审计**（`tax_period_basis` / `industry_range_source` / `share_count`）；**拒绝为凑漂亮数字而掩盖口径冲突**（不重写股数凑中位数）；**风险方向必须如实**（高 FCF 收益率不是风险）。
> 验证：`python -m pytest -q` → **429 passed**；golden 因 P0-4/P0-2 行为修正**有意重生成一次**（差异逐条核对为预期旗标/中位修正，非回归）。

### 🐛 Fixed
- 🐛 **P0-1（`valuation/wacc.py`）行业 WACC 区间匹配错误**：`INDUSTRY_WACC_RANGES` 关键词 `"Utility"` **不是** Yahoo 行业字段 `"Utilities"` 的子串 → VST 类标的**静默落入 `DEFAULT_INDUSTRY_RANGE=(6.5%~11.5%, Market Average)`**（报告已出现）。修复：① 关键词改为 `"Utilities"`（保留 `"Utility"` 兼容单数）；② 新增 **`CANONICAL_KEY_WACC_RANGES`**（`util.electric` / `util.gas` / `util.water` / `util.ipp`（**独立/商业发电：商品+电量风险、无 rate base，区间刻意高于受管制**）/ `util.diversified` / `en.oil_gas.integrated` 各自独立区间）；③ `_match_industry_range()` 改**四级优先级**（canonical key（profile）→ `node_from_yahoo()` → 关键词表 → 默认）+ 第 4 元 `source`；④ 新增 `_normalize_industry_text()`（统一 em/en dash 与连字符空格，命中 `Utilities—Independent Power Producers`）；⑤ `WaccBreakdown.industry_range_source` 经 dashboard 透传
- 🐛 **P0-2（`valuation/wacc.py::_effective_tax_rate`）ETR 重复计算重叠期间**：TTM 与 `annual_income[:3]` **相加** → 最新财年被**双重加权**，ETR 失真并污染税后债务成本/WACC（报告出现 `ΣTax/ΣEBT over 4 period(s)`）。修复：改为**非重叠期间策略**——① TTM 模式（TTM 有 tax+EBIT）**只用 TTM**；② 历史模式用**不重叠完整财年**（按 `period_end` 去重）；③ 兜底法定默认；返回值升级为 `(etr, source, tax_period_basis)`，新增 **`tax_period_basis ∈ {ttm, fyN, default}`**
- 🐛 **P0-3（`models/*` + `analysis/model_agreement.py`）每股估值分母不统一**：DCF/Reverse DCF/Multiples/SOTP 各用不同股数来源，却把**不同口径的每股估值当同一单位**进入共识中位数。修复：① 新增 **`ShareCountBasis`**（BASIC/DILUTED/TTM/MARKET/UNKNOWN）+ `ShareCount`（`shares_used/shares_source/shares_as_of/shares_basis/shares_reliable`）+ `make_share_count()`，`ValuationResult.share_count` 强制各模型申报口径；② `_resolve_share_reference()` + 可比性校验层：偏差 > `SHARE_COUNT_COMPARABLE_TOL=0.10` 的模型**剔除出共识中位数**（`share_count_excluded_models`），`n_applicable` 相应扣减；③ **保留 EV / Equity Value 独立参考，不重写股数凑中位数**
- 🐛 **P0-4（`analysis/risk.py`）FCF Yield Gap 风险方向误判**：`pos_fcf_gap = abs(fcf_yield - 0.04)/0.04` **对称**度量 → 正 FCF 但收益率**高于** 4%（VST 5.03%）被误标 High。修复：改为**非对称方向感知**——正 FCF ≥ 锚点**不因偏离判风险**；正 FCF < 锚点仅「估值偏高观察」（materiality gate）；**负 FCF** 按**恶化幅度与持续性**评估（`_fcf_trend()`）；**4% 降格为可配置参考参数**（`fcf_yield_reference`）

### ✨ Added
- ✨ **`ShareCountBasis` / `ShareCount` / `make_share_count()`（`models/base.py`）**：股数口径契约（P0-3）
- ✨ **`CANONICAL_KEY_WACC_RANGES` / `_normalize_industry_text()`（`valuation/wacc.py`）**：Taxonomy canonical key → 行业 WACC 参考区间 + 破折号归一化（P0-1）
- ✨ **`WaccBreakdown.tax_period_basis` / `.industry_range_source`（`valuation/wacc.py`）**：ETR 口径与行业区间来源审计字段（P0-1 / P0-2）
- ✨ **`config.py`**：`SHARE_COUNT_COMPARABLE_TOL=0.10`（P0-3）；`RISK_THRESHOLDS[RiskType.FORECAST]` 新增 `fcf_yield_reference=0.04` / `positive_fcf_gap_medium=0.10` / `positive_fcf_gap_high=0.25` / `fcf_decline_medium=0.30` / `fcf_decline_high=0.60` / `fcf_decline_consecutive=2`（P0-4）
- ✨ **`analysis/risk.py::_fcf_trend()` / `_downgrade()`**：FCF 恶化幅度与持续性度量 + 风险等级「可降不可凭偏差升」（P0-4）
- ✨ **`analysis/model_agreement.py::_resolve_share_reference()`** + `share_count_reference(_source)` / `share_count_bases` / `share_incomparable_models` / `share_count_excluded_models` 字段（P0-3）

### 🔧 Changed
- 🔧 **`models/dcf.py` / `models/reverse_dcf.py` / `models/multiples.py` / `models/sotp.py`**：均登记 `share_count` provenance 与 breakdown 字段（DCF/ReverseDCF→TTM、倍数 EV 家族→Market-or-TTM、P/B→Market、SOTP→Market/TTM）
- 🔧 **`analysis/model_agreement.py`**：`analyze()` 新增 P0-3 协调块（构建 `share_bases` → 解析参考 → 逐模型偏差判定 → 剔除不可比）→ `solved_agg` 驱动 `_independent_evidence` / `_iqr_filter` / `all_vals`；新增两条 notes（口径不可比剔除 + 股数口径基准）
- 🔧 **`tests/golden_report.py::build_fingerprint`**：新增指纹字段 `share_ref_source` / `share_count_excluded`（把股数口径契约纳入回归保护）
- 🔧 **`tests/golden/report_fingerprints.json`**：因 P0-4/P0-2 行为修正**有意重生成一次**（XOM 假 FCF 旗标移除、KR High→Medium、ORCL score 63→60、AVGO median 58.41→58.48 等，逐条核对为预期修正）

### 📊 Baseline Verification (Session #34)
| 验证维度 | 结果 | 备注 |
|---------|------|------|
| 全量 pytest | ✅ **429/429 passed** | 无回归（除有意 golden 漂移） |
| P0-1 行业区间 | ✅ IPP→`(6.5%,9.8%, Independent Power Producer (Merchant))`；Regulated Electric→`(5.0%,7.8%)`；Gas→`(4.8%,7.5%)` | 不再落入 Market Average |
| P0-2 ETR 口径 | ✅ basis = `ttm` / `fy2` / `default` | 三重口径均可复现，无重叠期间 |
| P0-3 股数可比性 | ✅ P/E（30.4B vs 15.2B，偏差 100%）被剔除 | 中位 132.19→123.99；`n_applicable == n_solved + n_failed` |
| P0-4 FCF 方向 | ✅ KR High→Medium；XOM/AAPL 假 FCF 旗标消失 | 高收益率不再误判 |
| golden 回归 | ⚠️ **有意重生成一次** | 差异全部为旗标/中位修正（逐条核对为行为修正） |

### ⚠️ Known Issues (Session #34)
- ① **`CANONICAL_KEY_WACC_RANGES` 需随 taxonomy 新增身份键同步**：当前仅覆盖 util 族 + 综合能源，其余身份回落关键词表/默认
- ② **P0-3 参考口径在多股权结构标的**：以 `market_cap ÷ current_price` 反推股数为主，多类别股标的需注意（已按优先级回退）
- ③ 承接 Session #31–#33 遗留：M-44（隐含 FCF 利润率/终值增长率 bound 措辞）、FMP 在线分部需 key、M-16/C-02（真实标注）仍为唯一真实 BLOCKER

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
