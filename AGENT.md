# 🤖 AGENT.md
Version: 4.31
Last Updated: 2026-11-19 (Session #53 — §10 变异测试收口 + 快照契约 + 可选 ML 依赖显式化)
Project Status: 🟢 Session #53 — **Mutation 16/16 全部捕获；缓存从「系统时钟驱动」改为「显式 Snapshot ID 驱动」；新增快照契约测试 11 项；`lightgbm`/`scikit-learn` 显式标为可选依赖。全套 1105 passed / 2 skipped / 0 failed / 0 errors；50 股 0 漂移。Solved 仍 32，未放宽任何标准。**

53. **变异存活不等于测试有效：9 个「存活」里 8 个是映射错误，1 个是真弱点（本轮 §10 收口）**：初跑 16 个变异有 9 个存活。逐个用 `scripts/triage_mutation_survivors.py` 在变异体下跑**全量套件**，判定它们是 MISATTRIBUTED（缺陷其实被**另一个**测试抓到，只是映射表指错了测试名）还是 UNCOVERED（真的没有测试能抓）。结论：8 个属前者，重映射即可；**M05 属后者**——原测试比较 `partial` 与 `full` 两个**同时被污染**的 beta，对整体偏移完全失明（正确实现下的偏移仅 0.00033，远小于 0.05 容差）。已改为断言**绝对** beta 恢复到已知 β=1.3。教训：**「变异被杀死」只能证明某处有测试覆盖，不能证明映射表上那个测试有效**；存活项必须区分「测错了地方」与「没测」。

54. **测试不能自己重算答案再证明自己对：M10 的假存活源于此（本轮修正）**：多根场景的测试原本自己算 `len(roots) > 1` 然后断言它——这测的是测试自己的算术，而不是生产代码。生产 `meta["multiple_roots"]` 被强制为 `False` 时它照样通过，于是 M10 假存活。改为 monkeypatch 投影函数、直接读取生产 `_solve_revenue_cagr` 返回的 `meta`。教训：**断言必须锚在生产代码的输出上**；测试内重算同一结论只是同义反复。

55. **缓存键由 `datetime.utcnow()` 生成，等于让数据成为机器时钟的函数（本轮修复，`data/providers.py`）**：`_cache_path` 用当天日期拼文件名，于是「同一份代码」在第二天读到**不同或缺失**的文件。实测：系统日期为 11-24 时，11-23 的 50 股快照全部 miss，冻结机制正确抛 `FrozenSnapshotMissError` 拒绝实时抓取——保护是对的，但测试因此永远无法复现。修复：新增 `UVE_SNAPSHOT_ID`（`YYYYMMDD`），缓存键优先取它；**格式非法直接抛错而不是回退到时钟**（一个拼写错误绝不能静默选中实时数据）。测试改为显式绑定 `20261123`。教训：**测试必须由数据快照驱动，不能由电脑时钟驱动**；「按今天缓存」在可复现性上等价于「每次跑都可能换一份数据」。

56. **冻结快照的六种状态都必须有测试，且 `lightgbm` 是可选依赖不是缺失依赖（本轮）**：新增 `tests/test_snapshot_contract.py` 11 项，覆盖：快照存在→正常读取、缺失→`FrozenSnapshotMissError`、过期但冻结→仍读原文件且**永不删除**、损坏→明确返回 miss 而非静默、冻结关闭→正常实时规则、系统时钟变化→不得移动已指定 Snapshot ID。另一方面，18 个 ML 测试 error 的根因是 `lightgbm`/`scikit-learn` **从未写进 `requirements.txt`**——但 `MLHybridClassifier.classify` 在缺依赖时会**回退到规则分类器**，所以它们是**可选依赖**，不是缺陷。正确处理是新增 `requirements-ml.txt` 并在测试里加**显式 skip 理由**（装了真实依赖则真跑），而不是 Mock 掉模型、也不是把 error 伪装成 skip。实测装上后 33 passed。教训：**可选依赖必须在测试里显式声明条件**，否则「环境没装」会被误读为「代码坏了」。

㊺ **`INFEASIBLE` 是错的标签：输入有限、乘积溢出，那是数据质量问题（本轮，`config.py` 新增 `SolverStatus.DATA_QUALITY_ERROR`）**：`price=1e308`、`shares` 有限，但 `price × shares` 溢出成 `inf`。旧代码把它判为 `INFEASIBLE`（「假设不可行」）——**这是把数据缺陷伪装成建模判断**。用户要求明确：无效数据必须被标为**数据质量问题**，绝不能混进 `NO_ROOT` 或 `SOLVED`。教训：**状态枚举的每个值都承载语义承诺**；「解不出来」有四种完全不同的原因（无根 / 数据坏 / 模型不适用 / 未收敛），用一个标签覆盖就是丢失信息。

㊻ **二分回退在 NaN 下会「成功」返回搜索上界，伪造出 150% 的增长（本轮第三个缺陷，`models/reverse_dcf.py`）**：`fa * fm <= 0` 对 `nan` 恒为 `False`，所以循环从不收缩上界、只把下界 `a` 一路推上去，最终返回 `APPROXIMATE cagr = 1.5`——**上界值本身，一个凭空捏造的数字**。这比报错更危险：报告里会出现一个看起来合理的 150% 增长。修复：区间端点与每个中点都显式 `isfinite` 检查。教训：**`brentq` 抛异常不等于安全**——`except Exception: pass` 落进回退分支，回退分支自己也有 NaN 陷阱。守卫必须覆盖**每一条**返回路径，不只是主路径。

㊼ **残差门是第二道防线，不是唯一防线——变异实验推翻了原假设（本轮）**：我原以为「禁用残差门 → 测试必失败」，实测**存活**。原因：EV 对增长单调递增，溢出**总是先撞到区间上界 `hi`**，端点守卫先拦下，残差门根本没机会被触发。这不是「残差门无用」，而是**纵深防御**：两门缺一才失败。原单元测试 docstring 声称它可单独隔离，已改写为真实性质。**隔离方法**：钩住 `scipy.optimize.brentq` 让它正常收敛，**在返回之后**才投毒投影，这样非有限值只被残差门看到——此时禁用残差门，测试**确实失败**。教训：**「测试通过」不足以证明某条守卫有效**；要证明某层守卫，必须让其它层都放行。

㊽ **`float('nan')` 能被 `f"{v:,.2f}"` 正常格式化，于是 `$nan` / `inf%` / `$infT` 直接进了 Telegram（本轮新增发现）**：`try: f"{float(v):,.2f}" except (TypeError, ValueError)` 看起来周全，但 `float('nan')` 两个异常都不抛，静默产出 `"$nan"`。修复 5 处：`reporting/dashboard.py`（4 个格式化器）、`analysis/divergence.py`（**独立的第二份实现**，同一个 bug 抄了两遍）、`analysis/model_agreement.py`、`telegram_bot/telegram_bot.py`、`benchmark/report.py`。教训：**同一格式化逻辑被复制到多个模块时，修一处等于没修**；必须 grep 全仓。另外 **`if x:` 挡不住 `nan`——`nan` 是真值**，`is not None` 也挡不住，唯一可靠的判据是 `math.isfinite`。

㊾ **`benchmark/report.py` 是最后一道门，而它对 SOLVED 完全不检查残差（本轮修复）**：`nan <= bar` 与 `nan > bar` **同为 `False`**，所以纯阈值判断会把 NaN 残差报成 `SOLVED`。`_final_status` 原本对 `mapped == SOLVED` 直接放行，只查 `multiple_roots` / `converged`。现补：① 残差非有限 → `DATA_ERROR`；② 未记录收敛 → `NON_CONVERGENT`；③ 补 `Data Quality Error (Non-Finite Projection)` → `DATA_ERROR` 映射。教训：**报告层是「最后一道」而不是「一道」**——它能看见的事实必须自己复核，不能假设上游已经查过。

㊿ **10 条件资格门必须写成代码，且第 10 条要独立重算根（本轮新增 `models/solved_eligibility.py`）**：用户要求把 SOLVED 资格做成**代码门禁**而非文档口号。10 条：`finite_price_and_shares`、`finite_target_wacc_tg`、`projection_inputs_ok`、`model_applicable`、`no_blocking_data_quality`、`solver_converged`、`residual_within_tolerance`、`outputs_finite`、`band_and_root_recorded`、`root_independently_recomputed`。最后一条最关键：**把求解器返回的根代回投影，独立重算一次 EV 并与目标比对**，不信任求解器自报的 `converged`。实测 AAPL 10 条全 `True`；50 只冻结实跑 **32 SOLVED 全部保留，0 只被误降级**——门禁没有伤害任何真实解，它只拦住了本不该通过的。教训：**「资格」必须可执行**；写成散文的资格条件在代码里等于不存在。

51. **`wacc_local_elasticity` 要用隐函数定理，不是偏导（本轮修正）**：原实现返回 `dEV/dw`，量纲是「美元 / WACC」，不是无量纲弹性。正确式：`-(∂EV/∂w) / (∂EV/∂g)`（沿 EV 等值线）。AAPL 实测 `dg/dwacc = 3.58`，与 §4 早前独立测得的 ≈4 交叉验证一致。教训：**名字里有「弹性」就必须无量纲**；单位不对的指标会被下游当成可比数字使用。

52. **未放宽任何标准（本轮最终状态）**：Solved **仍为 32**（32 Solved / 9 No Solution / 9 路由排除 = 50），报告层最终状态 `32 SOLVED / 9 NO_SOLUTION_MATHEMATICAL / 9 MODEL_NOT_APPLICABLE`，与 Session #51 完全一致。全套 **1075 passed / 2 skipped**（上轮 1003）；golden 3 passed 零漂移；本轮改动的 10 个文件 ruff `E4,E7,E9,F` 全通过（仓库其余 24 条经 `git show HEAD:<file>` 逐文件核对，**全部在 HEAD 上已存在**，非本轮引入）。

Version: 4.29
Last Updated: 2026-11-19 (Session #51 — Master Validation §1–§10 续：非有限报价伪造 SOLVED + 94 项守护测试)
Project Status: 🟢 Session #51 — **新增 P0-4（NaN/inf 报价伪造 SOLVED）；补齐 §1–§10 全部守护测试 94 项；50 股 0 漂移；Solved 仍 32，未放宽任何标准。**

㊱ **`price <= 0` 拦不住 `NaN`，于是无效报价产出了 `SOLVED`（本轮修复，`models/reverse_dcf.py`）**：`NaN` 与任何数比较恒为 `False`，所以 `price is None or price <= 0` 这个看起来周全的守卫**对 `NaN` 完全失效**。链条是：`NaN` 价 → `target_equity = NaN` → `target_ev = NaN` → `brentq` 的 `f(a)*f(b) > 0` 判断在 `NaN` 下为 `False`（既不大于 0 也不小于 0）→ 求解器「成功」返回**搜索下界** `cagr = -0.5` 并标 `SOLVED`。`inf` 同理；`-inf` 因 `< 0` 为真被侥幸拦住——**靠运气，不是靠设计**。修复分两层：① `_is_finite_positive()` 同时守卫价格与股数（非有限报价是缺失数据，不是便宜股票）；② `_solve_revenue_cagr` 入口对 `target_ev` / `wacc` / `tg` 做 `isfinite` 检查，非有限一律 `INFEASIBLE`。**变异实验证明两层缺一不可**：单独删掉任何一层，`NaN` 立刻重新伪造 `SOLVED`（见 `tests/test_mutation_guards.py` 的 patch 实验）。教训：**任何「守卫一个数值」的代码都必须先问 `NaN` 会怎样**——`<=`、`>=`、`!=` 三者在 `NaN` 上全部说谎。

㊲ **把 TTM FCF 从 0 改到 199B，隐含增长率逐位不变——这不是 bug（本轮证伪自己的诊断）**：我最初把「FCF 变异无响应」当成求解器忽略了输入，准备改码。读码后证伪：反向 DCF 的求解走「**营收 × 营业利润率**」投影路径（`project_enterprise_value_from_data` → `dcf_path_inputs_from_data` 只读 `ttm.revenue`），`base_fcf` 是 SBC 归一后的**桥接/展示口径**，代码注释已明写「营收 CAGR 求解走『营收 × 营业利润率』路径，营业利润率已含 SBC 费用，故不重复扣减」。**正确做法是扰动营收或价格**，扰动 FCF 测的是展示字段，不是求解链。教训：**测试一个字段之前先确认它在求解路径上**，否则测的是空气。

㊳ **反向 DCF 的增长率对 WACC 高度敏感是数学固有性质，不该写成绝对上限（本轮，`tests/test_input_perturbation.py`）**：AAPL 实测每 25bp WACC ≈ 1.0pp 隐含增长，即弹性 ≈ 4×（`dg/dw`）。首版 §4 断言写「WACC ±1% 时增长率偏离 ≤3pp」，实测 3.8pp 直接失败——**是断言错了，不是代码错了**。改为弹性约束 `0 < dg/dw < 6`，既守住「方向正确、无跳变、不放任」，又不把固有敏感度当缺陷。同理终值增长的弹性是**负的**（`dg/dtg ≈ -3.1`）：终值增长↑ → 永续部分已贡献更多价值 → 显式期所需增长↓。首版写成正值，被实测证伪。教训：**敏感度测试的界必须从实测标定，并写成无量纲弹性**；写绝对上限等于把自己的无知固化成断言。

㊴ **50 只里 8 只 EV 随增长非单调，这是经济现象而非缺陷，且全部被正确拒绝（本轮 §5 扫描）**：AMZN / TSLA / FCX / BA / LLY / MRNA / NEE / CEG 的 EV 曲线在 g 上不单调（增长破坏价值，终值 FCF 被抑制或再投资超过增量现金流）。**它们全部返回 `No Solution In Range` 并给出具名原因**（`NEGATIVE_BASE_FCF_NO_VALID_ROOT` ×5、`NO_ROOT_IN_EXPANDED_RANGE` ×4），**无一只伪造 CAGR**。这正是 §5 要的行为：非单调曲线不得被二分法硬塞一个根。`tests/test_ev_curve_stability.py` 把「曲线形状被尊重」与「非单调永不给出确信答案」两侧都钉住。

㊵ **9 只 `rd_status = None` 是正当路由排除，但理由在另一个字段里（本轮核实，未改码）**：初看「状态为空 + `rd_notes` 为空」像是静默失败，违反「每个状态都要有正当理由」。核实后：这 9 只（JPM/BAC/GS/CB/BRK-B/PLD/O/AMT/VICI）全部 `rd_routed_out = True`，`rd_routed_out_reason` 明写「Not applicable for business type Bank / REIT / Insurance」，且 collector 会**额外直接探测模型**，`rd_direct_status` 同样 `Insufficient Data`——**双向一致，不会解却被路由掉**。`tests/test_status_matrix.py` 把「路由排除必须写明业务类型」+「直接探测必须同样失败」都做成断言。教训：**审计一个字段为空之前，先确认它不是被设计成在另一个字段里**。

㊶ **「测试通过」不等于「测试有效」：必须真删守卫看它是否失败（本轮变异实验）**：新增 8 项守护断言后，我又做了 4 次**真实源码变异**（改完恢复）：① 价格守卫退回 `price <= 0` 朴素形式 → 2 项失败；② 删掉求解器 `isfinite` 守卫 → 4 项失败（含 `NaN` 重新伪造 `SOLVED`）；③ `self.rcfg = replace(base)` 改回 `self.rcfg = base` → 配置污染测试失败；④ 端点残差门放宽 1000× → `test_endpoint_short_circuit_cannot_bypass_residual_bar` 失败。**四项全部被捕获**。这一步是必须的：一个永不作废的测试和被删掉的测试，保护力相同。

㊷ **并发不改变结果，但并发也没有真正并行（本轮 §7 实测）**：`NAME_TO_MODEL` 持有**进程级共享模型实例**，所以「并发跑不同股票」是最大的状态串味风险。实测 8 只 gather vs 顺序：**结果零差异**。但同一实验也暴露并发比顺序**慢 3.5×**（1.63s vs 0.46s）——因为模型计算是同步 CPU 密集，在事件循环里阻塞，`gather` 实际只是排队。所以「零差异」的成因是**串行**，不是线程安全。`tests/test_history_concurrency_stability.py` 同时钉住结果一致与「模型不得改写入参 `FinancialData`」——后者才是真正的隔离保证。

㊸ **`base_fcf` / `growth_band_verdict` 等展示字段与求解字段必须分开断言（本轮，方法论）**：本轮多次因混淆「展示口径」与「求解口径」而写出错误断言。已固化的判据：**求解链** = `ttm.revenue` + 历史利润率 + WACC + 终值增长 + 股本 + 价格；**展示链** = `base_fcf` / SBC 归一 / `projection_vs_reported_fcf` 披露。测试扰动求解链，展示链只断言「存在且有限」。

㊹ **未放宽任何标准（本轮最终状态）**：Solved **仍为 32**（32 Solved / 9 No Solution / 9 路由排除 = 50），与 Session #50 完全一致；50 只冻结实跑 **0 字段漂移**。本轮 3 个 P0 全部是**拒绝不该有的答案**，没有一条是「让更多股票解出来」。全套 **1003 passed / 2 skipped**（较上轮 +94）；golden 5 passed 零漂移；改动文件 ruff `E4,E7,E9,F` 全通过。

Version: 4.28
Last Updated: 2026-11-23 (Session #50 — Reverse DCF 主验证：50 股测试、修复与验收)
Project Status: 🟢 Session #50 — **主验证修复了三个 P0 缺陷（求解器残差门槛、快照不可复现、routed-out 无终态），并新增 §14 报告层。Solved 数保持 32，未放宽任何经济合理性标准。**

㉙ **求解器「Solved」曾以 1e-3 判定，而验收门槛是 1e-4（本轮修复，`config.py` / `models/reverse_dcf.py`）**：`converged` 与降级判断都用硬编码 `1e-3`，比规格宽 10 倍。实测 **COST 1.024e-4、PFE 1.074e-4、BKNG 1.24e-4、JNJ 1.07e-4** 残差超门槛却报 `Solved`——静默通过。根因：`brentq` 以 `xtol`（x 区间宽度）收敛，**不是** `|f(x)|` 的保证，故 `newton_tol=1e-4` 根本不构成残差保证。修复：`newton_tol 1e-4 → 1e-10`，新增契约字段 `price_residual_tol=1e-4`，两处硬编码改用该字段。修复后 32 只残差降至 **1e-11~1e-15**，无一只超门槛。**注意这不是「放宽」而是收紧**——若当初为了让数字好看才放宽，方向恰好相反。

㉚ **同一代码重跑会得到不同结论：4h 缓存 TTL 让市场数据在验证中途漂移（本轮修复，`data/providers.py`）**：重算 PFE 得隐含 CAGR 1.93%→1.39%、WACC 6.267%→6.123%、rfr 5.052%→4.912%，**代码未改**。根因是 `.cache/treasury_yield/` 与 `.cache/yahoo_finance/` 的 4h TTL 会在验证期间静默重取。这正是规格 §1.2/§9 禁止的「市场数据漂移被误读为代码漂移」。修复：新增 `UVE_FREEZE_CACHE=1`，冻结时缓存**不过期、不删除**；`TreasuryYieldProvider` 与 `YahooFinanceProvider` 共用同一开关（此前 Treasury 独立实现会漏掉）。实测冻结后连跑两次 PFE，WACC/CAGR/残差**逐位相同**。

㉛ **§9 隔离实证：CAGR 位移来自市场数据，不是本轮改码（本轮用旧代码对照验证）**：把 HEAD 代码 checkout 到临时 worktree、**共用同一冻结缓存**重跑 50 只，与新代码逐只对比。结果：状态零变化，CAGR 位移 **≤2.4e-5**（xtol 收紧的预期量级）；而先前「修复前 vs 修复后」看到的最大 5.0e-2 位移，**全部伴随 rfr 5.052%→4.912%**。结论：大位移是市场数据，小位移才是代码。没有这步对照，就会把两者混为一谈。

㉜ **routed-out 的 9 只原本没有任何终态（本轮修复，`benchmark/report.py`）**：`rd_status=None` 使「正确拒绝」与「从未运行」无法区分，50 = Σ(status) 这个不变量因此**不可证伪**。不改 collector（其 `None` 契约被 `check_e_coverage` 依赖），改为新增 §14 报告层派生显式终态：`MODEL_NOT_APPLICABLE`（9 只银行/保险/REIT）、`NO_SOLUTION_MATHEMATICAL`（9 只）、`SOLVED`（32 只），**合计 50**。`build_report` 对空白终态与未知状态**抛异常**，不选一个舒服的标签。

㉝ **golden 指纹对本轮缺陷零信息量（本轮确认，未改动）**：`golden/report_fingerprints.json` 只含 `median_value`、`n_solved` 等聚合量，**不含 solver 残差、隐含 CAGR、WACC**。所以它全程 4 passed，却对「残差超门槛仍报 Solved」完全无感。因此本轮新增 5 个独立测试文件（求解器契约、快照冻结、报告终态、三标准 DCF、无噪声 β），而非依赖 golden。做 mutation 验证：把 `newton_tol` 改回 1e-4，新测试**立即失败**。

㉞ **§5 阈值现状（本轮补齐）**：β 无噪声恢复误差实测 ~1e-16，但原测试只断言 `abs=2e-2`（含噪声场景），**1e-6 门槛无人守护**——新增 `test_noiseless_beta_is_recovered_to_1e6`。求解器唯一根误差在 `xtol=1e-10` 下达 ~1e-13（原 5.1e-7），新增 ≤1e-8 断言。三标准 DCF 合成案例（常数增长/零增长永久年金/价值陷阱）全部对闭式解验证到 1e-6 相对误差。



㉔ **等级表是政策，不是统计学定律（本轮，`analysis/nwc_confidence.py`）**：用户要求明确标注。原先只在注释里写了「not a statistical law」，读代码的人看不到、复制到报告里更会丢。现在做成**代码契约**：`GRADE_IS_POLICY = True`、`GRADE_POLICY_NOTE`（明写「无法排除行业结构变化、会计口径变更、并购与异常年份」），并**随 payload 一起输出** `grade_is_policy` / `grade_policy_note`，报告渲染层显示为 ℹ️ 行。标签 `MORE_ESTABLISHED` 由「较已确立（8+ 对）：可作为主要估计」改为「**较可用**（8+ 对）：本引擎作为主要估计，**非已证明正确**」——`established` 一词本身就在暗示已被证明，这是措辞层面的过度声明。

㉕ **敏感度基线由单点改为多点（本轮，`tests/test_nwc_estimator_golden.py`）**：用户指出固定 g=5% 不够。现扫描 **g∈{2%, 5%, 10%} + 各公司自身隐含收入 CAGR**，每个 g 下扫 6 个 w，EV 相对 w=0 归一。**这不是形式改动**：XOM 在自身增长率 7.55% 时 EV 相对值 **−6.7%**（已转负），而固定 g=2% 时为 **+61.7%**——单点基线会把一个「增长即毁灭价值」的公司显示成「增长大幅增厚价值」。AAPL 在自身 33.16% 增长率下 w=0.50 时 EV 仅剩 47.9%。

㉖ **工作树批次审计：实际是三批，不是两批（本轮发现，未提交）**：用户建议拆 Commit A（P2 路由）/ Commit B（本轮）。按时间戳与 diff 核查后**该拆分无法干净执行**：
  * **批次①（11-21~11-22）**：`valuation/wacc.py`（β 分层/Blume）、`models/reverse_dcf.py`（+841 行）、`classification/*`、`config.py`、`forecasts/fcf_projection.py`、`reporting/dashboard.py` 及 8 个对应测试——属更早 Session 的 β/DCF 双波段工作，**不是 P2 路由**。
  * **批次②（11-23 00:0x）**：`forecasts/nwc_estimators.py`、`analysis/nwc_shadow.py`、`benchmark/`、`data/providers.py` 的 NWC 组件、`report_fingerprints.json`——三估计器框架与 P2 路由。
  * **批次③（11-23 10:47~12:05）**：`growth_direction.py`、`nwc_confidence.py`、NWC 两个 golden、`nwc_utils.py` 标签、`test_precision_fixes.py`、文档——本轮。
  * **关键障碍**：`data/providers.py` **同一文件内同时含批次①的 β 回归诊断与批次②的 NWC 组件**，无法按文件路径拆分，需 `git add -p` 交互式分块。
  * `.cache/segment_revenue.json` 已被 git 跟踪（不应跟踪，缓存文件），本轮未处理。

Project Status (前序·Session #49 续 6) — 🟢 Session #49 续 6 — **解析导数边界验收（用户评审「进入边界验收」）**。纪律：**先证伪自己的诊断再改码**——本轮最重要的产出不是通过测试，而是**用精确有理数把「多重翻转」的真实分布钉死**，并因此拒绝了一个看似合理但错误的接口假设。

⑲ **多重翻转：真实存在，但只在 g<0 域（本轮精确求解，`forecasts/growth_direction.py`）**。做法：把 `dEV/dg` 写成 `(1+g)` 的**精确有理系数多项式**（含终值乘数 `1+(1+tg)/(r−tg)`），再用 Descartes 符号变化数给出正根上界、用对数网格 + 二分求实根。结果：
  * **g > 0 域：宽参数扫描（k0∈{0.01..0.40} × w∈{0.30..20} × H∈{3..30} × r∈{0.06,0.09,0.12}）最多 1 个根，0 个多重翻转案例。**
  * **g < 0 域：真实存在 2 个根**（例：k0=0.055, w=1.50, H=10 → g≈−45.2%、−16.2%）。
  * 因此接口**必须支持多重翻转**（用户要求正确），但**不能假装 g>0 有多个**。实测 50 只 benchmark 中 0 只出现多重翻转（真实公司 k0>w）。
  * 数学解释：`dFCF_t/dg = R0·q^{t−2}·[t(k0−w)q + w(t−1)]`，系数符号由 `k0−w` 与终值项决定；`k0>w` 时导数严格递增（已验证 4 组 w<k0 全部 strictly increasing）→ 最多一个根。

⑳ **翻转点位置验证（P0，新增）**：不只验证单点导数，还验证**翻转位置**。解析 vs 纯中心差分（不含任何解析信息）独立定位翻转点，**误差 ≤5e-7**（容差 1e-4）。5 个 w 值全部通过。理由：一个关于 g 对称的符号错误能通过逐点测试，却把翻转点放到错误位置。

㉑ **接口已扩展为多翻转形态**（`sign_over_range` / `GrowthDirectionTest`）：输出 `local_direction`（INCREASING/DECREASING）、`flip_points`（**全部**变号点，二分精修）、`valid_direction_intervals`（与参考点同号的所有子区间）、`tangent_points`、`flips_at_growth`（首个，保留兼容）。`evaluate(..., growth_range=)` 可指定扫描窗。

㉒ **切线根（不变号的零点）是诚实的负面结果**：网格变号检测会漏掉与零相切的双根，故加入「斜率局部极值 + 相对容差」检测。但在**引擎参数空间内找不到任何内点切线根**（13 个近零极小值全部落在扫描边界 g=−0.05）。故该检测器仅以**构造的双根**做单测，**不声称在真实数据上验证过**。

㉓ **边界情况**：翻转点贴近扫描上下界（w=1.40 → g≈−4.6%；w=0.368 → g≈49.8%）仍能正确检出，且经两侧符号验证确为真实变号而非边界伪影。扫描窗外不报告。

Project Status (前序·Session #49 续 5) — 🟢 Session #49 续 5 — **判别式作用域修正、NWC 证据分级与独立 golden（用户评审 A/B/C）**。纪律：**先证伪自己的诊断再改码**——本轮证伪的是**自己上一轮 ⑤ 的表述**（公式对，但把它当成了全局方向判别式）。

⑮ **⚠️ ⑤ 的 `k0/w > P/D` 只是「参考增长率处的局部导数」，不是全局方向判别（本轮证伪，`forecasts/growth_direction.py`）**：⑤ 在 g=0 求导得 `dEV/dg|₀ = R0(k0·D − w·P)`，数学正确；但 `EV(g)` **非单调**，`dEV/dg` 会随 g 上升变号。实测 9 组参数中 **3 组翻转**：w=0.80 在 g=0 为 +3608、g=0.08 已为 −479；w=0.80/0.70/0.50 的翻转点分别约 g≈0.08/0.12/0.27。故该判据**只能回答「在 g=g_ref 处增长是否增厚价值」**，**不能**回答「增长是否增厚价值」。修正：
  * `VERDICT_SCOPE = "LOCAL_EV_DIRECTION_AT_REFERENCE_G"`，`REFERENCE_G = 0.0` 随结论输出，禁止省略作用域。
  * 新增 `analytic_slope()`（解析导数）+ `sign_over_range()`（扫描找翻转点）；`evaluate(..., revenue0=)` 传入收入规模即**自动附带 `flips_at_growth`**，并在理由中写明「仅在 g∈[g_ref, 翻转点) 内成立」。
  * **解析 vs 中心差分逐点核对**：5 个 w × 10 个 g = 50 组，**0 符号不符，最大相对误差 2e-8**（`tests/test_growth_direction.py`）。
  * 顺带确认 ⑬ 的 `g_BE=k0/w` 与 `k0/(w−k0)`（FCF 利润率零点）**都不预测**实际 `dEV/dg` 翻转点——三者是不同概念。

⑯ **「稳健」是算法名，不是证据等级（本轮修正，`analysis/nwc_confidence.py`）**：原 `NWC_ROBUST_MARGINAL` 在 3 对数据上就成立，读起来像「证据充分」。新增 `history_grade()`：1–2 对 `INSUFFICIENT`／3–4 `INDICATIVE`／5–7 `PROVISIONAL`／8+ `MORE_ESTABLISHED`；并输出 `claim_strength ∈ {none, indicative, established}`。**样本量而非算法名决定结论强度**：INDICATIVE 仅许「指示性」结论并强制加注，INSUFFICIENT 直接撤销方向结论。实测 50 只中 7 个方向结论**全部为 `indicative`**（均只有 4 年数据）——这正是该分级要暴露的事实。

⑰ **报告 golden 不覆盖 NWC，不能拿它当 NWC 的安全证明（本轮补测，`tests/test_nwc_estimator_golden.py`）**：`golden/report_fingerprints.json` **不含任何 NWC 字段**，因此它对「NWC 估计器是否稳定」**零信息量**。新建两个独立基线：
  * `nwc_estimator_fingerprints.json` — 锁三种估计值、`history_grade`、`claim_strength`、置信类别、`flips_at_growth`（18 只）。
  * `nwc_sensitivity_fingerprints.json` — 锁 EV 对 NWC 系数扫描的响应（13 只可用），**在 g=5% 非零增长处扫描**（g=0 时 ΔRevenue=0，NWC 项恒为零，全部 EV 相同——这个坑本轮实际踩到并修正）。实测 XOM 在 w=1.50 时 EV 相对值 **−0.139（转负）**，AAPL −30%。
  * **有效性验证**：故意改动 `HISTORY_GRADES` 边界 → NWC golden **失败**、报告 golden **仍 4 passed**，证明两者确实解耦且新基线非摆设。

⑱ **⑤ 的 `aggregate` 估计器身份降级（本轮，`forecasts/nwc_utils.py`）**：它是生产 Reverse-DCF 一直使用的 ΣΔNWC/ΣΔRevenue，**为可复现性保留**（改动会移动全部估值与 golden），但「长期使用」**不是「最可靠」的证据**——其输入由 FCF 残差反推、分母是累计收入增长（NEE 24.9% vs 年度强度 1.9%）。返回标签由 `aggregate` 改为 `LEGACY_PRIMARY_RESIDUAL_ESTIMATE = "legacy_primary_residual"`，新增消费方（增长归因）应优先用 `robust_marginal_nwc`。

Project Status (前序·Session #49 续 4) — 🟢 Session #49 续 4 — **NWC 三指标分离、判别式推导与证伪、Shadow Run（用户任务：「把三种 NWC 指标分离实现，引入直接财报 NWC 并做五档分类，跑 Shadow Run 但不动 golden」）**。纪律：**先证伪自己的诊断再改码**——本轮证伪了**自己上一轮的判别式公式**，并因此把「不作答」变成机器强制。

① **`change_in_nwc` 是直接财报数据，不是残差（决定性，推翻更早结论，`data/providers.py`）**：`_ANNUAL_TIMESERIES` 显式请求现金流表 `ChangeInWorkingCapital`，`nwc_from_cashflow_line` 直接取用。更早「NWC 边际比是残差反推」的说法对**模型系数 `nwc_marginal_ratio`** 成立，对**原始 `change_in_nwc`** 不成立——两者是不同的量，混为一谈正是本轮的起点错误。

② **三种指标维度不同，不可互换（`forecasts/nwc_estimators.py`）**：`level = 营运资本/收入`（存量比率）、`intensity = ΔNWC/收入`（每元总收入的投资强度，NEE=1.9%）、`marginal = ΔNWC/Δ收入`（模型真正消费的系数，NEE≈14.0%）。每个 `NWCEstimate` 带 `dimension` 标签，消费方必须匹配；`reconcile()` 只在 **marginal 维度内部**比较，**level 永不参与**（有测试锁定）。NEE 的 1.9% 是 intensity 而非 level 或 marginal——用户此前的概念纠正正确且被代码固化。

③ **直接财报营运资本已接入（`data/providers.py` + `forecasts/nwc_estimators.py`）**：新增 AR / Inventory / AP / CurrentDeferredRevenue / OtherCurrent(Assets|Liabilities) 六个字段，`operating_nwc_from_balance_sheet()` 计算 `(AR+Inv+OCA) − (AP+DefRev+OCL)`，**刻意排除现金与债务**（融资项，否则比率随司库政策漂移）。缺 AR 或 AP 时返回 `None` 而非补 0——补 0 等于凭空捏造一个水平。实测 50 只中 **45 只 AR+AP 齐备**（VICI/CRM/O/BAC/BRK-B 缺 AP）。

④ **⚠️ 数据年限不足，如实报告**：Yahoo timeseries 请求窗口为 10 年，但年度实际只返回 **4 年**（季度 20 季）。用户要求「≥5 年」，**当前不满足**——分类学对 <5 年一律附加「指示性、非确立结论」告警（`RECOMMENDED_ANNUAL_YEARS=5`）。4 年只能形成 3 个 y/y 配对，恰在稳健下限。

⑤ **正确判别式（本轮推导 + 数值验证，取代 ⑬ 的错误公式）**：由引擎实际投影 `FCF_t = rev_t·k0 − w·(rev_t − rev_{t−1})` 得 `FCF_t/rev_t = k0 − w·g/(1+g)`；对**完整 EV** 在 g=0 求导得 `dEV/dg|₀ = R0(k0·D − w·P)`，故**增长增加价值 ⟺ `k0/w > P/D = 1/久期`**。P/D 对 10 年/9% WACC/2% 终值为 **0.136（久期 7.34 年），不是 1**；`k0/w>1` 的朴素规则把门槛高估约一个久期。数值验证：**10/10 符号正确**，且门槛随 horizon 单调变化（H=3→0.356，H=40→0.083），证明确实不是常数 1。

⑥ **判别式拒绝作答的条件（`forecasts/growth_direction.py`）**：`k0≤0` / `WACC≤tg` / 缺 `w` / **距门槛 ±25% 内**（`BOUNDARY_BAND`）一律 `applicable=False` 且 `verdict="indeterminate"`，**不输出任何结论**——「不适用却仍给结论」是本仓库明令禁止的自相矛盾。边界带的依据是实测：利润率漂移下符号 18/21 一致，**3 次不一致全部落在边界附近**。

⑦ **五档分类学是方向的唯一闸门（`analysis/nwc_confidence.py`）**：`NWC_DIRECT` / `NWC_ROBUST_MARGINAL` / `NWC_INTENSITY_PROXY` / `NWC_ESTIMATE_CONFLICT` / `MECHANISM_UNCONFIRMED`。`can_claim_direction` 同时要求「系数可估」**且**「引擎 NWC 区间扫描方向不翻转」——两个不稳定性必须同时排除。

⑧ **强度→边际换算会因分母塌陷而拒绝（`MIN_GROWTH_FOR_PROXY=2%`）**：CEG 增长率 1.5%、强度 23.5% 会算出 **1598%** 的「边际比」——这是算术不是经济，且会主导任何比较。现直接拒绝并记录 `intensity_proxy_refused_reason`。

⑨ **Shadow Run 50 只（`benchmark/shadow_nwc_run.py`，不写入引擎、不动 golden）**：`NWC_DIRECT 22 / NWC_ESTIMATE_CONFLICT 11 / NWC_INTENSITY_PROXY 7 / NWC_ROBUST_MARGINAL 1 / 路由不适用 9 / ERROR 0`。**41 只可诊断中仅 7 只给出方向结论**（6 adds / 1 destroys），其余 34 只 `indeterminate`。11 只冲突案例（CEG robust 0.4% vs proxy 1598%、DUK 符号相反、KO 4.77 vs 2.14）证明三法分离不是形式主义。**非极端 NWC 标的无异常翻转**（MSFT/WMT/COST/XOM/CVX 等均稳健或按规则弃权）。

⑩ **本轮自查修掉 3 处自相矛盾**：ⓐ `applicable=False` 却仍打印「增长减少价值」→ 不适用即不输出结论；ⓑ `NWC_ESTIMATE_CONFLICT` 仍给方向 → 分类学设为唯一闸门，冲突一律撤销；ⓒ 点估计结论与引擎扫描「方向翻转」并存 → 扫描证据更强，点估计结论撤销并说明理由。
**验证**：`pytest` → **784 passed / 2 skipped**（唯一 1 error 为 `scripts/test_phase1_refactoring.py` 被 pytest 误收集、缺 `ticker` fixture，与改动无关，属既存）；新增测试 3 文件 **67 例**：`test_nwc_estimators.py`(29)、`test_growth_direction.py`(22+1skip)、`test_nwc_confidence.py`(16)；改动文件 `ruff check --select E4,E7,E9,F` → **All checks passed**；**golden 零漂移**（`tests/test_golden_report.py` 3 passed；并已用「回退 providers 改动后仍 3 passed + 指纹不含任何 NWC 字段」双重证明本阶段改动不影响 golden）。注：`report_fingerprints.json` 的工作区改动来自上一阶段 P2（`UNDETERMINED → display_only`），语义与 P2 一致，非本轮引入。
Project Status: 🟢 Session #49 续 3 — **模型经济合理性与边界压力测试（用户任务：「把 NEGATIVE_INCREMENTAL_VALUE_CREATION 形式化，算增量 ROIC vs WACC，但 CapEx>D&A 不足以反推该机制」）**。纪律：**先证伪自己的诊断再改码**——本轮**推翻了用户的核心假设与我自己上一轮的归因**，并因此把「不可断言」变成机器强制。

⑫ **增量 ROIC < WACC 解释不了任何一只（本轮证伪用户假设，`benchmark` 实测）**：按用户要求算增量 NOPAT / 净资本投入（CapEx−D&A+ΔNWC）：NEE 57% vs WACC 6%、CEG 27% vs 14%、FCX 30% vs 10%、LLY 45% vs 8%、KO 199% vs 7%、NVDA 215% vs 10% —— **全 50 只增量 ROIC 均高于自身 WACC**，但其中 9 只 EV 仍随增长递减。**「增量 ROIC < WACC」一个案例都解释不了**，它不是判别式。用户的提醒（「CapEx > D&A 不能反推该机制」）方向正确且更彻底：即便严格算 ROIC 也不成立。

⑬ ~~**真实判别式是 NWC 强度 + 临界增长（本轮实证）**~~ **⚠️ 已于 Session #49 续 4 证伪**：原记「EV 对增长的斜率符号由 `g_BE = k0 / nwc` 决定（k0 = 稳态 FCF 利润率），递减组 4.8%–12.5% 与递增组 19%–652% 完全分离」。**证伪**：`g_BE=k0/w` 既非 FCF 利润率零点（正确解为 `k0/(w−k0)`），也不预测 `dEV/dg` 的翻转点；w=0.40 时实际翻转 g=0.419，两个公式分别给 0.370 / 0.587。所谓「完全分离」是 41 只样本上的**观察性巧合，不是定理**。正确判别式见 Session #49 续 4 ⑤。仍成立的部分：NWC 边际比是**残差反推**（`NOPAT + D&A − capex − FCF`），会吸收一次性营运资本波动。
⑭ **⚠️ 推翻上一轮 NEE/CEG/FCX「增长毁灭价值」归因（本轮自查证伪，`models/reverse_dcf.py`）**：上一轮（Session #49 续 2 ⑦）我把 NEE 递减归因为「再投资超过自身现金流」。**证伪**：对 NWC 比在合理区间扫描，**13/41 只的方向结论会翻转**——NEE 在 nwc=14% 递增、20% 递减（恰卡临界）；CEG 20% 翻转；SO 5% 翻转；FCX 10% 翻转；AMZN 5% 翻转。**上一轮那句归因建立在被放大的 NWC 上，不成立**。故新增 `_ev_direction_robustness()`：在候选 NWC 集（`config.py::nwc_sensitivity_ratios`）下探测 EV 方向，**方向不稳则不得断言任何机制**，只报「方向对营运资本假设敏感」。实测 9 只无解中 **8 只为 `EV_DIRECTION_UNDETERMINED`**，仅 MRNA 方向稳健（负终值抑制，机制确定）。
⑮ **⚠️ 修复既存缺陷：峰值扫描带用错（`models/reverse_dcf.py`）**：注释称「扫描限定在业务类型合理区间」，代码却用全局配置 `[-0.1, 0.8]`。SO 报「EV 在 g=15% 见顶」而 Utilities 合理带是 [-2%,10%]——正是注释警告的自相矛盾。新增 `plausible_lo/hi` 参数，扫描与方向检验统一用合理带；SO 峰值由 g=15% 修正为端点 10%，NEE 为 [-2%,10%]。
⑯ **多峰值检测（`_ev_curve_peaks`）**：单网格最大值假设单峰，非单调曲线会藏起第二个转折点。改为枚举所有局部极大（含两端点）+ 三分搜索局部精修 + 去重，meta 记录 `ev_peak_count` / `ev_peaks` / `peak_search_range`。实测 LLY 3 峰（内部峰 g=11.1%）、TSLA 3 峰、NEE/CEG/SO 各 3 峰。
⑰ **无解分类学（`_classify_no_root`，meta `no_root_kind`）**：把「无解」拆成 `EV_DIRECTION_UNDETERMINED` / `NO_ROOT_IN_DOMAIN` / `SEARCH_DOMAIN_INSUFFICIENT` / `SOLVER_NONCONVERGENCE` 四档——区分「模型不对」「数据不对」「问不出答案」。实测 8 只 UNDETERMINED + 1 只 MRNA NO_ROOT_IN_DOMAIN；审计 `check_solver_residual` 对 UNDETERMINED 判 PASS（是解释，不是缺陷）。
⑱ **增长价值归因（`forecasts/fcf_projection.py::attribute_growth_value`）**：EV 对 FCF 分项是**线性**的，故 `EV(g_hi)−EV(g_lo)` 可**精确加性分解**为 NOPAT / D&A / CapEx / ΔNWC / 终值五份（实测误差 ~1e-5，纯浮点）。**关键符号**：CapEx 与 ΔNWC 在 FCF 里是减项，PV 是正值幅度，必须在此处乘 −1，否则加和与直接差分差 1e11（本轮曾犯此错并修正）。另出 `cancellation_ratio = Σ|分项| / |合计|`：SO **125×**、CEG 10.2×、NEE 7.4×——这是「方向脆弱」的数学指纹，已渲染到报告并在 ≥3× 时显式告警。
**验证**：`pytest tests/ -q` → **715 passed / 1 skipped**；改动文件 `ruff check --select E4,E7,E9,F` → **All checks passed**；**golden 零漂移**（P0–P3 只改注释/meta/新字段，不动数值）；benchmark 50 只 **0 硬失败 / 0 漂移**。新增测试 4 文件 33 例：`test_nwc_direction_robustness.py`(8)、`test_ev_multipeak.py`(8)、`test_no_root_classification.py`(8)、`test_growth_value_attribution.py`(9)。
Project Status (前序·Session #49 续 2) — 🟢 **Post-Fix Deep Validation（用户任务：「Reverse DCF 与 β 全链路深度验收」）**。纪律：**先证伪自己的诊断再改码**——本轮自查证伪了**自己刚写出的 2 条错误归因**（见下 ⑦⑧），并因此发现 1 条真实求解器分类缺陷。
⑦ **「EV 随增长递减」被统一归因为「终期 FCF ≤ 0」（本轮自查证伪，`models/reverse_dcf.py`）**：首版对**所有**递减曲线都写「终期 FCF ≤ 0、终值被抑制」。**证伪**：NEE 的 `terminal_fcf_negative=False`（终值为正），EV 却在 g=0 见顶 $46.2B 后单调下滑至 g=150% 的 −$31.9T。真实机制是**再投资（CapEx + 营运资本）超过增长自身产生的现金流**（NEE capex 37.2% > D&A 23.3%，NWC 边际比 24.9%）。现改为：在**合理性区间内**扫描 EV 峰值，记录 `ev_peak_growth` / `ev_peak` / `ev_peak_below_target` / `terminal_fcf_negative_at_peak`，按 `terminal_fcf_negative_at_peak` **二选一**给出准确归因（抑制 vs 再投资），并明示「即便取最优增速也无法解释当前价」。
⑧ **`binding` 判定同样无视 EV 方向（本轮自查证伪，`models/reverse_dcf.py` + `reporting/dashboard.py`）**：`above_band_ceiling` 的语义是「**更高**增速可逼近价格」，但该分支仅比较 `ev_at_ceiling < target_ev`，对递减曲线会输出自相矛盾的「EV 上限 $-7.2B < 目标」（CEG）。现新增 `ev_decreasing_in_growth` 档：EV 在合理区间内递减时不再谎称「隐含增长 ≥ 上限」，两处渲染（`_implied_section` / `_gap_section`）改为「不适用（模型 EV 随增速上升而下降）」。
⑨ **`solver_residual` 把「已证明无根」当成「未收敛警告」（`benchmark/verify_fix.py`）**：9 只 `ev_decreasing_in_growth` 原被判 WARN。既然峰值证据已能**证明**无根（`ev_peak_below_target=True`），这属确定性结论而非未决缺陷；缺峰值证据时仍 WARN（区分「已证明」与「未知」）。改后 `solver_residual` **PASS=41 / WARN=0**。
⑩ **新增验收测试（3 个文件，+34 例）**：`tests/test_solver_ev_direction_label.py`（9 例：方向分类、峰值在合理区间内、抑制 vs 再投资的归因二选一）、`tests/test_beta_selection_vs_blume.py`（7 例：NVDA 自下而上 2.430→0.930 **不是** Blume，CEG 2.178→1.766 **是** Blume 0.65×2.178+0.35×1.0；winsorize 先于 shrink）、`tests/test_benchmark_coverage.py`（8 例：50 只全覆盖、无静默跳过、每条无解必须命名机制）。另修 `tests/test_beta_synthetic_recovery.py`（噪声 0.005→0.0015 使 β 标准误 < 容差；`window_end` 期望 2024-12-15→2025-01-15）。
⑪ **新增审计规则 `check_e_coverage`（`benchmark/audit.py`）**：把「无遗漏、无默认通过、无静默跳过」变成机器强制——`rd_status is None` 仅在注册表声明不适用时合法，且必须能归因到 `business_type`，否则 FAIL。
Project Status (前序·Session #49) — 🟢 Session #49 — **Reverse DCF 双层增长区间 + 求解器审计留痕 + DUK 式现金流失真（用户任务：「Harden Reverse DCF，修 DUK 式现金流失真，补增长分档与 β 置信度验收测试」）**。纪律：**先证伪自己的诊断再改码**；本轮自查又证伪 2 条自造缺陷。
① **双层增长区间（`models/reverse_dcf.py`）**：原先**合理性区间同时充当求解区间**，市场定价超出带宽时被报成「无解」，把「价格不合理」伪装成「算不出来」。现拆为**搜索区间** `[-0.50, 1.50]`（只决定能否求解）与**合理性区间**（只决定可信度标注，永不限制求解）。新增 `growth_band_verdict` 五档：`SOLVED_WITHIN_BASE_BAND` / `SOLVED_OUTSIDE_BASE_BAND` / `SOLVED_EXTREME_GROWTH` / `NO_ROOT_IN_EXPANDED_RANGE` / `DATA_QUALITY_WARNING`（`config.py::GrowthBandVerdict` + `classify_growth_band`，按**带宽倍数**而非绝对百分点分档，使 10% 公用事业带与 60% SaaS 带的「超出」含义一致）。
② **求解器审计留痕（`models/reverse_dcf.py`）**：`_solve_revenue_cagr(..., meta_out=)` 写出 `solver_meta`（`solver_method` / `solver_version` / `search_bounds` / `residual` / `relative_residual` / `converged` / `n_roots_detected` / `roots` / `multiple_roots`），并新增 `SOLVER_VERSION = "2.0-brentq-two-layer"`。**无根路径同样留痕**（`converged=False` + `failure=above_search_ceiling|below_search_floor` + `ev_at_lo/hi`）——否则「无根」与「求解器没跑」无法区分。
③ **DUK 式现金流失真（`models/reverse_dcf.py::_fcf_base_quality`）**：公用事业/重资产标的 TTM CapEx 常超 OCF（实测 DUK OCF 11.5B / CapEx −16.7B → FCF **−5.2B**，CapEx/OCF **145%**；SO 138%），此时任何「隐含增长」都只是资本开支口径的算术产物。新增 `DATA_QUALITY_WARNING` 判定：**负基准 FCF 一律不得标为「落在合理区间内」**（该档优先级高于区间标签，且 `reason == "negative_base_fcf"` 时无条件降级），避免把烧钱公司包装成令人安心的数据点。
④ **β 置信度分层（`data/providers.py`）**：跨窗口 β 的**符号翻转**（如 +0.33 → −0.34）原与「数值离散」同等对待，但符号翻转意味着回归方向都不稳定、信息量近零。现按更严重档位评级，与数值极差分层。
⑤ **报告层落地（`reporting/dashboard.py` + `analysis/expectation.py`）**：`ImpliedExpectations` / `ExpectationGap` 均携带 `growth_band_verdict`；`_implied_section` 与 `_gap_section` 各渲染一行「**隐含增长可信度**」（`_GROWTH_BAND_VERDICT_LABELS` 五档中文标签 + 风险提示）。两节必须**同一 verdict**，否则同一数字在两处说法不一。
⑥ **本轮自查证伪的 2 条自造缺陷（均已修复）**：ⓐ 首版把 verdict 在函数**前段**计算、`breakdown` 前段写入，而 normalized 救援在后段才改 `implied_revenue_cagr` → NBIS/CRWV 出现「`No Solution In Range` + 展示 CAGR 26% + 判为 `SOLVED_WITHIN_BASE_BAND`」三重自相矛盾；改为**末尾统一 finalize**，按「报告实际展示的那个数」定档。ⓑ 无根路径 `solver_meta` 为空 → 已补。
**验证**：`python -m pytest tests/ -q` → **648 passed / 0 failed / 1 skipped**；改动文件 + `benchmark/` 的 `ruff check --select E4,E7,E9,F` → **All checks passed**（顺带清掉 `dashboard.py` 基线既有的 `ke_s`/`roe_s` 两个 F841 死变量）；**golden 已重生成**，漂移为 AMZN/NVDA 的 `n_failed=1`→`n_display_only=1` 与 KR/XOM 的 `applicable_models` 新增 `ReverseDCF`（原先被合理性带宽挡掉的求解现能解出，属 P1 预期效果），**四只 `median_value` 完全未变**。新增 `tests/test_reverse_dcf_two_layer_band.py`（24 passed / 1 skipped）+ `tests/test_beta_layering.py`（11 passed）+ `tests/test_reverse_dcf_search_band_invariance.py`（4 passed）。

### 🔬 Session #49 续 — 50 只全量复测（同数据 A/B）与 3 条方法论教训

**复测结论**：钉住同一份数据快照后，50 只 **Solved 16 → 32**、**No Solution 25 → 9**（另 9 只为 REIT/银行/保险正确路由排除）；**16 只原本 Solved 的标的 ΔWACC 精确为 0、ΔCAGR ≤ 2.7e-05**，即「修好了原先解不出的，且没动原先解对的」。审计引擎 `benchmark/verify_fix.py`（50×8 项，0 硬失败）与漂移审计 0 findings 佐证。9 只重点标的逐项结论见 CHANGELOG「✅ Verified」表。

**教训 1 — 数据未钉住时，一次数据更新会被误判成回归缺陷。** 首轮复测见 16 只 Solved 标的全线漂移（NVDA wacc 0.101473→0.100073，恰 −14bp），几乎要归咎于 `valuation/wacc.py` 的 β 分层改动。实际根因是 `treasury_yield` 缓存的 10Y 国债由 5.052%→4.912%（−14bp）。**凡做「改动前后」A/B，必须把 `treasury_yield` 与行情快照一并钉住**（仅钉行情不够：Rf 直接进 CAPM）。判据：钉住后 ΔWACC 应精确为 0，否则才是真漂移。

**教训 2 — 求解器容差不是逻辑缺陷，但必须先证伪再下结论。** 区间不变性测试首版断言 `spread < 1e-9`，NVDA 报 1.24e-05。把 `xtol` 从 1e-4 收紧到 1e-9 后，两个区间收敛到同一点（差 8.8e-12）→ 证明差异纯属 `xtol` 契约，根是唯一的。**断言应写成 `≤ 2×xtol` 并附证伪记录**，而不是放宽阈值了事。

**教训 3 — 审计脚本的断言本身也要证伪（本轮错了 4 条）。** ⓐ `beta_adjusted` 并非「raw 的 Blume 收缩」，而是**选中 β 归一化后的值**；选中自下而上 β 时与回归 β 无收缩关系（NVDA 2.430→0.930）。ⓑ 日期对齐的证据是 `window_start/end + benchmark + n_observations + adjclose`，不是单一 `as_of`。ⓒ CEG 2.178→1.765 是合法的 **Blume 收缩 35%**，应算术复算 `(1−0.35)×2.178+0.35×1.0` 而非判为异常。ⓓ 漂移容差用纯相对值会让接近 0 的增长率（BKNG −0.39%）把 9e-06 读成 0.23%，须用 `max(1e-4, |基准|×1e-3)`。**审计脚本报 FAIL 时，先怀疑断言，再怀疑产品代码。**
Project Status (前序·Session #48) — 🟢 Session #48 — **50 只热门股 Reverse DCF 诊断：4 项根因修复 + 1 项诚实披露（用户任务：「50 只标的 reverse DCF 为何 no solution / 路由错误，修根因，别破坏 golden」）**。纪律：**先证伪自己的诊断再改码**；6 条初始假设经实测被推翻，仅 4 条成立。
① **🐛 SBC 假披露（`models/reverse_dcf.py`）**：注释声称隐含求解使用「SBC 调整后 FCF」，实际求解只用 收入×利润率 路径。**证伪证据**：CRM SBC 3.665B→0 使 `base_fcf` 11.49B→15.15B，隐含 CAGR **17 位有效数字完全相同** → FCF 变化对隐含 CAGR 零影响。改为如实描述求解口径。
② **🐛 路由缺口（`classification/classifier.py::MODELS_BY_TYPE`）**：`ReverseDCF` 缺失于 CONSUMER_STAPLES / COMMODITY / UTILITIES / ENERGY / TELECOM，导致 17 只预期适用标的被排除（含 5 只 `VZ/XOM/CVX/SLB/COP` 反而直接求解的矛盾）。补齐后 17 只全部归位。
③ **🐛 支付网络被误判为金融机构（`classification/classifier.py` + `classification/ml_classifier.py`，本轮核心）**：V/MA 与 COF/AXP/SOFI 共用 Yahoo「Credit Services」→ 全被 `FINTECH` 笼统剥离 DCF/ReverseDCF。新增**结构性判据** `_is_balance_sheet_financial()`：以 `利息费用/营业利润 ≥ 0.20` 区分（支付网络 V 0.03、MA 0.04、PYPL 0.07 vs 放贷 AXP 0.37、SOFI 0.69、COF 0.86 —— 两簇分离度极大；营业利润缺失/为负时回落 `利息/收入 ≥ 0.10`）。**关键**：`ml_classifier.py` 另有一处 `is_fintech_hybrid → is_financial_institution = True` **无条件强制覆盖**，会绕过上述判据，一并改为复用同一函数。V 由「路由排除」→ **Solved（隐含营收 CAGR 29.6%）**，MA Solved 10.6%，COF/AXP/SOFI/JPM/BAC 仍正确排除。
④ **🐛 `bridge_broken` 口径错配（`models/reverse_dcf.py`）**：原用 `base_fcf <= 0`（SBC 归一后的**报表** FCF，GOOGL −10.66B）判断，而投影走 收入×利润率 路径（GOOGL 首年 +84.0B）→ 误触发「成熟稳态救援」。改为探测投影路径本身（`project_enterprise_value_from_data` 的首年 FCF / 终值为负），`proj is None` 时回退。
⑤ **🐛 投影 FCF 与报表 FCF 口径不调和未披露（`models/reverse_dcf.py`，本轮新增）**：投影为 `NOPAT + D&A − CapEx − ΔNWC`，`base_fcf` 为 报表 CFO−CapEx。**NFLX 是反例**：D&A 17.9B（占收入 41%，内容摊销）vs CapEx 0.93B（1.2%），因摊销对应的现金支出已含在 OCF 内 → 投影首年 FCF 30.3B 是报表 11.4B 的 **2.7×**，导致假结论「市场隐含营收 CAGR ≤ −5%」（真实 NFLX 增速 12%）。**证伪「D&A 加回上限 = CapEx」修法**：实测虽修好 NFLX（误差 166%→10%），却破坏 AMD（1%→71%）、CRM、PFE、JNJ —— **一刀切错误，未采用**。改为显式披露：新增 `breakdown["projection_vs_reported_fcf"]` + 差异 >50% 时置 `projection_fcf_caliber_mismatch` 并追加中文注记。实测精确命中 NFLX（175%），不误伤 KO 8.9% / CRM 9.7% / AMD 46%。
**验证**：pytest **609 passed / 0 failed / 0 errors**（基线 591 passed + 18 errors，errors 为 `lightgbm`/`scikit-learn` 缺失的环境问题——已 `git stash` 证伪为基线既有，安装依赖后清零）；改动文件 `ruff check --select E4,E7,E9,F` → **All checks passed**；**golden 已重生成**（仅 XOM/KR 新增 ReverseDCF + `n_display_only` 1 项，即 ReverseDCF 因反解出当前价而按设计标为「仅展示不计入共识」，属预期）；**50 只实跑：Solved 16 / No Solution In Range 25 / 正确路由排除 9 / 路由违规 0**。
**已证伪（非缺陷，未改码）**：① 「TTM capex 是数据 bug」——GOOGL 季度 capex 51.4/44.9/35.7/27.9B 真实（2026 AI 资本开支潮），年 91.4B 与 TTM 159.8B 自洽；② 「GOOGL 归一化救援失效」——35% 上限下最大 EV 仅 $2.05T < 目标 $3.59T，属诚实无解；③ KO/PG/WMT 等 25 只无解**多数为 band 带宽伪影**（KO 真实隐含 ≈17% vs 上限 15%、PG 17.9% vs 15%、WMT 37.9% vs 15%、DUK 48.7% vs 10%）——**带宽过紧是可量化但需用户裁决的独立议题**（放宽会移动全部已解标的的隐含增长，故本轮未动）；④ NU 被 ML 判为 Insurance 为**基线既有**（`git stash` 复现），非本轮回归。
**遗留待裁**：① 增长带宽是否按「真实隐含增长超出上限的倍数」分档放宽（KO/PG/WMT/COST/DUK 等 8 只 1.0–4.9×）；② KO/JNJ/DUK/SO 原始 β 为负（−0.027/−0.033）被夹到 `BETA_WINSLOW_LO = 0.30`，疑似 β 回归的价格对齐 bug，超出本轮 Reverse-DCF 范围。
Project Status (前序·Session #47) — **KR 报告审计：5 项自相矛盾修复 + 推翻 Session #46 的「有意更严」判断**（用户任务：「看看这个报告有什么不合理的地方然后修复，修复了再测试，确保问题修复好」）。纪律：**先证伪自己的诊断再改码**。
① **🐛 β 窗口 WACC 带宽不含自身基准（本轮最严重，`valuation/wacc.py`）**：带宽用**回归窗口 β 原始上下沿**定价（KR 窗口 β = −0.28/−0.34/0.33），而实际 WACC 用的是**自下而上 β = 1.19** → 输出「WACC∈[6.07%, 6.17%]」并排「Final WACC = 9.33%」，**区间不含自己的基准**。改为以**采用值 β 为中心**按窗口极差/2 展开（`β∈[0.86, 1.53]` → `WACC∈[8.11%, 10.54%]`），已包住 9.33%。
② **🐛 虚假「已传导至 DCF 区间」声明（`valuation/wacc.py::beta_uncertainty_note`）**：`grep` 确认**无任何代码消费** `wacc_beta_lo/hi`；DCF 用自己行业带宽（`models/dcf.py::_pps_wacc_lo/hi`），二者无关。改为「敏感性参考；DCF 仍以采用值单点折现」。
③ **🐛 同一对象两套波动措辞（`valuation/wacc.py::beta_window_note`）**：极差 0.67 时一处说「波动较大」（>0.50），另一处说「中度波动」（≤1.0）。改为**共用 `_beta_uncertainty_label`**。⚠️ **推翻 Session #46 的「有意更严，未改阈值」**——当时只统一措辞、保留双阈值，但双阈值正是矛盾根因；该字段仅用于文案（无数值收缩），统一后 golden 零漂移。
④ **🐛 单变量隐含解把基准值当结论（`models/reverse_dcf.py` + `analysis/expectation.py` + `reporting/dashboard.py`）**：隐含解以**已解出的隐含 CAGR** 为锚，该路径本身已复现目标 EV → WACC/g 求解**必然回落到自身基准值**（KR：隐含 WACC 9.3% vs 基准 9.327%、隐含 g 0.5% vs 基准 0.5%），却标「其余假设固定为基准」，读如独立证据。新增 `*_degenerate` 标记并渲染为「与基准一致…不构成额外证据」。**未改锚点**：实测改用预测 CAGR（−0.11%）会解出隐含 WACC 3.15%（低于 Rf，不成立），故锚点正确、错在**呈现**。
⑤ **🐛 Headline 与自身 caveat 矛盾（`reporting/verdict_intuition.py`）**：情景交叉检验把 `headline` 上调为「显著高估」，但 `headline_summary` 仍用**中位数标签**拼装 → 「当前价 $67.94 估值合理…（显著高估信号）」。改为用**最终 headline**，中位数口径降为从属子句。
⑥ **🐛 区间过宽却称「落在公允区间内」（`reporting/verdict_intuition.py`）**：KR 区间 $1.62~$77.13（宽度为中位数 2.7 倍）仍输出「当前价落在公允估值区间内」，与「显著高估」并读像背书。改为宽度 > 中位数时报「区间过宽…不足以判定」。
⑦ **🐛 正 FCF 被标为负（`classification/classifier.py::_characterize_profile`）**：KR TTM FCF **+$2.38B**（1.6% 利润率）却标 `Weak/Negative FCF`——杂货零售结构性薄利 ≠ 负值。新增 `Thin Positive FCF` 档（0 ≤ margin < 3%）；真负仍为 `Negative FCF`。已确认 `models/multiples.py` 的 AI-cloud 判定依赖 `weak`/`neg` 子串，薄正档正确地不再命中。
⑧ **✅ 复核后未改码**：情景列表的「基本面 ×1.00/×1.00」是**基准情形本身**（与熊/乐观并列对照，标题已写明仅变动折现率），非误标。
**验证**：pytest **591 passed / 0 failed / 18 errors**（18 errors 为**基线既有**：`lightgbm` 缺失；基线 583 → 591，新增 8 用例）；改动文件 `ruff check --select E4,E7,E9,F` → **All checks passed**（`dashboard.py` 仅剩基线既有 `ke_s`/`roe_s`）；**golden 零漂移**；KR 全链路实跑 exit=0，报告四项缺陷全部消失。
Project Status (前序·Session #46) — **AAPL 报告审计：8 项自相矛盾/口径缺陷修复**（用户任务：「看看这个报告有什么不合理的地方然后修复，修复了再测试，确保问题修复好」）。纪律：**先证伪自己的诊断再改码**；两项疑似缺陷经复核判定非缺陷，未改码。
① **🐛 NWC 口径混用（最严重，`analysis/divergence.py::_fcf_normalization_layer`）**：`_extract_history()` 返回的是**边际** ΔNWC/ΔRevenue（AAPL 37.9%），却被当作**收入占比**直接从 FCF margin 里减 → 历史正常化 FCF margin **−11.6%**（苹果不可能）。改为经历史增速换算成收入占比（`hist_nwc × cagr`）后再减 → **23.3%**，与 TTM 28.4% 同量级，假的「FCF 走弱」告警消失。
② **🐛 对账结论硬编码（`reporting/dashboard.py::_data_section`）**：估值可用性评分**无条件**打印「受对账不一致影响」，而同报告写「已校验 10 项 · 一致 10 · 不一致 0」。改为按 `reconciliation_mismatches` 分三种文案。
③ **🐛 Regression Stability 语义倒置（`valuation/wacc.py`）**：字段存的是**不确定性**等级，却挂在「稳定性」标题下 → 「低」被读成「稳定性差」，与同屏「窗口间稳定」矛盾。标题改为「回归窗口不确定性」并附解读（低=窗口间稳定）。
④ **🐛 敏感性章节张冠李戴（`reporting/dashboard.py::_coe_sensitivity_section`）**：标题承诺「仅变动 Ke」，但非金融企业走 `run_all()`，**WACC 与 g 同时变动**；且把 `sv.wacc`（WACC）当 Ke 打印。改为按 `drivers` 判别：金融企业真单变量；非金融企业如实标注「折现率档位同时变动 WACC 与 g」，并按 WACC/g 渲染。
⑤ **🐛 增长特征 Unknown（`classification/classifier.py::_characterize_profile`）**：要求 `annuals[0]` 与 `annuals[-1]` 营收俱全，AAPL 2022 营收为 `None` → 明明有 7.7% CAGR 却报 `Unknown`。改为取**最长可用跨度**。
⑥ **🐛 未细分经济标签粗化精确身份（`classification/taxonomy.py::reconcile_identity`，本轮核心）**：Yahoo「Consumer Electronics」→ `tech.hardware`，ML「MatureTech」→ `tech.generic`（=**未细分**），旧逻辑收敛至共同祖先 `tech`，**把精确节点降级**，违反本模块自述的「经济特征只能细化、不得决定身份」黄金律。新增例外：`*.generic` 不构成细化或冲突 → 保留外部身份。AAPL 节点 `tech` → **`tech.hardware`**（行业 sanity 区间随之变为 Consumer Electronics）。
⑦ **🐛 Peer 适配性误报（`analysis/divergence.py::_peer_fit_check`，修 Session #45 自身遗留）**：`tech` 是**族根**（`parent=None`），本身就是板块粒度，却仍被报「粗颗粒板块锚点」。同时反向过修：节点无专属锚点时（仅 `util.ipp` 有）也告警 → 几乎每只票都告警。改为：族根不报；仅当**该指标存在节点专属锚点却仍用板块锚点**时才报。AAPL 由 🟠 → 🟢。
⑧ **🐛 预测 FCF CAGR 跨口径（`analysis/expectation.py::forecast_cagr` + 新增 `forecasts/forecast.py::bridge_fcf_anchor`）**：起点用**报告 TTM FCF**（OCF−capex，已加回 SBC，28.4% margin），终点是**桥式**预测 FCF（23.6% margin）→ 实际上升的路径（121.5B→125.3B）被算成 **−1.6%**。改为 FCF 起点用桥式锚点 → **+2.3%**，与营收 CAGR 6.2% 同向。
⑨ **✅ 复核后未改码**：`覆盖因子 1.08` 是 `sqrt(适用/解算)` 的设计内轻度惩罚（非缺陷）；`beta_window_note` 的 0.50 与不确定性标签阈值不同是**有意更严**（有测试锁定），仅统一了措辞。
Project Status (前序·Session #45) — **VST 报告审计：7 项自相矛盾缺陷修复 + 分类节点锚点下沉**（用户任务：「审计/优化，让 reverse DCF 更精确、最大化热门股覆盖」）。纪律：**先证伪自己的诊断再改码**；未复现的不改。
① **🐛 样本口径恒等式**（`reporting/dashboard.py`）：`2+0+2+0=4 ≠ 合计 5`——仅展示模型被计入合计。修复后与模型分桶恒等式同源。
② **🐛 模型分桶恒等式**（`reporting/dashboard.py`）：`适用2+不适用0+解算2+失败0=4 ≠ 合计5`，同一根因，一并修复。
③ **🐛 归因张冠李戴**（`reporting/verdict_intuition.py`）：headline 硬编码「股数偏差 >25%」，而实际触发是**对账不一致**（P/E 53.22 vs 18.56 = 186.8% 偏离；真实股数偏差仅 14.8%）。新增 `shares_cause` 分发，按真实成因出文案。
④ **🐛 自相矛盾标签**（`reporting/verdict_intuition.py`）：「低覆盖（2/2 解算，质量因子 1.00）」——`coverage_sufficient` 把**比率 100%** 与**绝对样本数 <4** 混为一谈。改为区分「样本过少」与真实覆盖缺口。
⑤ **🐛 风险结论自相矛盾**（`analysis/risk.py`）：`fundamental_assessment` 取聚合分（80→PASS），无视维度级 FAIL（Margin Risk）。改为任一维度 FAIL 即下调总体结论。
⑥ **🐛 虚假历史 FCF CAGR**（`analysis/expectation.py`）：报 −40.9% 实为 `>0` 过滤**静默丢弃** 2022 年负 FCF（−816M）并把跨度误标为 2 年。`historical_cagr()` 改为符号翻转/未定义时返回 None，dashboard 输出 N/A 说明。
⑦ **🐛 同一现象两套归因**（`reporting/verdict_intuition.py`）：「股数证据不一致」与「对账不一致（TTM EPS）」并存 → 统一走 `shares_cause`。
⑧ **🆕 分类节点锚点下沉（本轮核心，直接服务「reverse DCF 更精确」）**：`util.ipp`（商户独立发电商）与 `util.electric`（受管制电力）同属 Yahoo sector `Utilities`，旧逻辑在 **Level 1 精确命中 sector** 即停，丢弃分类器已解析的更细节点 → VST（P/B 实际 9.8×）被套用**受管制电力锚点 P/B 1.8×**，隐含 −81.6% 的假「显著高估」。新增 `models/multiples.py::TAXONOMY_NODE_PEER_MULTIPLES` + **Level 0**（节点优先于 sector，`EXACT_INDUSTRY` 溯源）→ P/B 1.8×→3.5×、P/E 16→20、EV/EBITDA 10→11，估值从 $23.54 修正为 $45.77。
⑨ **🆕 反向 DCF 增长带宽按节点**（`config.py`）：`REVERSE_DCF_BY_TYPE` 仅按粗 `BusinessType` 取值，商户 IPP 继承受管制电力 **10% CAGR 上限** → VST 报「No Solution In Range」，**这是带宽伪影而非价格结论**。新增 `REVERSE_DCF_BY_NODE`（`util.ipp` 上限 0.30）+ `get_reverse_dcf_config_for()`（节点覆盖、未列键回落 BusinessType、**不修改共享表**），接入 `models/reverse_dcf.py`。VST 由 **No Solution → Solved**：隐含营收 CAGR 18.3%、隐含营业利润率 9.2%（基准 11.9%）——即市场价需要**更快增长但更低利润率**，结论可解释。镜像既有 `CANONICAL_KEY_WACC_RANGES` 的节点分层设计。
⑩ **🆕 Peer 适配性不得自我认证**（`analysis/divergence.py::_peer_fit_check`）：原逻辑见 `classification_status == confident` 即输出「分类明确，倍数法 peer 原型与业务身份一致」，**即使锚点停在粗板块**。新增检查：分类节点存在而某倍数模型仍用 `EXACT_SECTOR_ANCHOR` → 输出「粗颗粒板块锚点」警告。
**验证**：pytest **577 passed / 0 failed / 18 errors**（18 errors 为**基线既有**：先 `git stash` 跑得同样 18 errors，`lightgbm` 缺失导致 ML 模型加载失败，与本轮改动无关）；新增 `tests/test_taxonomy_node_anchors.py` **18 用例**；改动文件 `ruff check --select E4,E7,E9,F` 仅剩**基线既有 2 项**（dashboard.py 未用变量 `ke_s`/`roe_s`，HEAD 同样存在）；**golden 零漂移**（basket 无公用事业标的，未重生成基线）。VST 全链路实跑 exit=0。
**已证伪（非缺陷，未改码）**：D/E 3.94 = 20.07B/5.10B 正确；Margin Risk CV=1.01 方法正确；隐含营业利润率 18.0% 落在基准 11.9% 与 TTM 22.6% 之间，属单变量有界解，非矛盾。
Project Status (前序·Session #44) — **季度 EBIT 污染修复 + 推翻 Session #43 的桥口径归因**（用户任务：「根据你的建议修复，全部修复后，再同步到 GitHub」）。纪律：**先证伪自己的诊断再改码**。① **🐛 修复 Yahoo 季度 `EBIT` 污染**（`data/providers.py`）：Yahoo 的 `quarterlyEBIT` 对一部分标的是**算术不可能值**（高于毛利，而 `EBIT = 毛利 − 营业费用`）。最坏例 **GOOGL 2026-Q2：quarterlyEBIT 140.0B vs 毛利 73.9B / 收入 119.8B**，把 TTM 营业利润率推到 **61.7%**（年报实际 39.6%）；同季度 `OperatingIncome` 干净（40.8B）。三处修复：(a) `_QUARTERLY_TIMESERIES` 增加 `OperatingIncome`；(b) 取值**优先 `OperatingIncome`**，`EBIT > 毛利（缺失用收入）×1.001` 判为污染并丢弃；(c) **NI 反推 EBIT 增加 `op_inc is None` 前置**——否则 `NI 112.2 + 利息 1.28 + 税 26.56 = 140.0B` 精确复现刚被拒的坏值，静默抵消校验。`_CACHE_SCHEMA_VERSION` 4 → 5 作废旧缓存。实测 GOOGL TTM OI 61.7% → **33.3%**、NVDA 76.0% → **65.2%**，全 50 只再无 `OI > 毛利`。② **📊 推翻 Session #43 的「桥式 5.16× 是公式缺陷」结论**：两个混淆因子——(a) 污染 EBIT 抬高了桥式 NOPAT；(b) 把 **FCFF 桥式**（SBC 已在营业费用中扣过）与 **报告 FCF**（SBC 已在 OCF 中加回）**跨口径相比**。同口径（桥式 vs 桥式）后绝大多数吻合：NVDA 0.98×、AVGO 0.85×、NFLX 1.09×、CRM 0.94×、MCD 1.05×；GOOGL 修复后为 −0.30×，方向反转。③ **📊 真正的残余缺陷是「比率陈旧」且高度局部**：`_extract_history()` 用 5 年等权平均 `capex/收入`，而 GOOGL 已从 14.8% 升到 TTM 33.9%。用真实目标 EV 反解隐含营收 CAGR 的位移：**MSFT +11.3pp、META +9.3pp、GOOGL +8.0pp**，其余 19 只 ≤1.9pp。④ **⚠️ 实测后放弃三条改法（附证据，均未落地）**：(a) TTM 比率无条件替换 → 永续期按 33.9% 扣 capex 把终值打成负数，前瞻 DCF GOOGL EV −130B / META −97B / ORCL −234B / AMZN −475B（原 +851B / +337B / +2B / −40B）；(b) 半衰期 2 年加权 → 11/40 → 9/40，META 仍 17.8×，收益不足以动 golden；(c) 显式期 capex 线性收敛到 D&A 单独实施无改善（16/34 vs 15/34），仅与「永续 capex=D&A 稳态终值」配套才成立（负 EV 5 → 2 只，DUK 30B → 122B、SO 34B → 93B），但会使 15 只已解标的隐含增长率位移最多 25pp（FCX 30.4% → 5.3%）。验证：pytest **577 passed**；改动文件 ruff 项数与 HEAD **完全一致（336=336）**；golden **零漂移**。⚠️ **待用户裁决**：终值期 capex 口径（(a) 仅终值年 capex=D&A 稳态 FCF / (b) 显式期 TTM capex + 终值稳态）——两者都改 golden 并位移已解标的，故仅量化待裁。
Project Status (前序·Session #43): Session #43 — **50 只热门股压力测试（用户任务：这批标能测 reverse DCF 的什么）**。方法：全 50 只实跑 `DataProvider → Normalizer → Validator → Classifier → ReverseDCF`，逐字段比对报告值与计算值，**未改动任何估值口径**。① **🐛 修复纯数值 REIT 规则越权改判**（`classification/ml_classifier.py`）：`_looks_like_reit` 数值兜底（EBITDA margin 55–90% + beta<2 + CAGR<25% + 股息/杠杆）原为**无条件**执行，会在 sector 硬规则（第 0 层）已明确映射后再次改判——实测 **LLY（Healthcare/制药，EBITDA margin 0.567）→ REIT**、**NEE（Utilities/受监管电力，0.585）→ REIT**，随后被 `applicability_check` 以「REITs prefer NAV/FFO」拒绝，使两只**完全退出 FCF DCF 与反向 DCF**。修复：该兜底增加 `sector_bt is None` 前置条件（它本意只是「provider 未给 sector 时的兜底」，不应覆盖已有直接证据）；真实 REIT（PLD/O/AMT/VICI）不受影响。② **📊 量化 DCF 桥口径与报告 FCF 的系统性偏离**（本次不改码，仅记录待裁）：`NOPAT+D&A−capex` 桥式与报告 FCF 在 36 只可算标的中 **9 只偏离 >±25%**，最大 **GOOGL 5.16×**（桥 $101.8B vs 报告 $19.7B）、**NFLX 2.80×**（$31.9B vs $11.4B，D&A/收入=36% 的内容资产摊销被当作可分配现金）、**XOM 0.25×**、**AMD 0.58×**、**WMT 0.62×**、**TSLA −0.51×**、**META −0.98×**（后两者符号翻转）。③ **覆盖率实测**：50 只 → Solved 15 / No Solution In Range 25 / Insufficient Data 10；10 只拒绝**全部正确**（Bank×3、Insurance×2、FinTech×1 为金融机构，REIT×4 应走 NAV/FFO）。单变量隐含解可解率（40 只适用）：营业利润率 40/40、FCF 利润率 40/40、WACC 28/40、终值增长率 22/40。SBC/收入 >5% 者 8 只（MRNA 18.4%、META 11.2%、AVGO 9.5%、CRM 8.3%、ISRG 7.2%、ORCL 6.7%、GOOGL 6.5%、GS 5.0%）。验证：pytest **577 passed**（574 → 577，新增 `TestReitMarginRuleRespectsSector` 3 用例）；改动文件 `ruff check --select E4,E7,E9,F` 全通过；**golden 零漂移**（未触及估值口径）。⚠️ **Session #43 的「桥口径 5.16×」数字已被 Session #44 推翻，勿再引用。**
Project Status (前序·Session #41): Session #41 — **AVGO Audit Remediation Phase 1（用户任务书）**。基于 2026-11-15 06:27 UTC 的 AVGO 报告修复三项 P0 估值完整性缺陷，**不重设计无关模块；改码前先审计现有实现**。① **P0-1 · Equity Bridge 缺失数据安全**（`valuation/equity_bridge.py`）：`EquityBridge` 新增 `status`（`OK`/`INCOMPLETE`/`UNAVAILABLE`）+ `missing_inputs` + `net_debt_verified` + `is_reliable()`；`_resolve_net_debt()` 区分「**已验证的零净债务**」（显式 `net_debt`，或 `total_debt` & `cash` 俱全）与「债务/现金输入缺失（按 0 展示但标记未验证）」；`enterprise_value is None → equity_value None`（`UNAVAILABLE`，**绝不 `0 − claims`**）；`equity_to_enterprise(None) → None`；保留少数股东/优先股/租赁双计守卫；全部调用方（dcf/nav/unit_economics/sotp/fcf_projection/reverse_dcf/dashboard）已加 None 守卫。② **P0-2 · P/E 分子分母口径一致**（`models/multiples.py`）：P/E 的 EPS 分母为 **TTM 报表股数** → 股权价值**必须用同一 TTM 股数**重建（旧码把 EPS 派生价值乘无关的市场股数）；新增 `breakdown["pe_basis_audit"]`（eps_basis/eps_period/eps_source/shares_basis/shares_source/shares_as_of/`numerator_denominator_basis_match`）；无 TTM 股数 → 回退 market 并**显式标注口径不一致**。③ **P0-3 · 股数证据闸门**：`data/reconciliation.py` 新增 `ShareCountEvidence` + `share_count_evidence()`，分离**市场隐含 / 财报期末 / 稀释加权平均**三口径（`market_cap ÷ price` **仅为同口径复算，非财报股数证明**），偏差 >25% → `consistent False`；`analysis/model_agreement.py` 新增 `_EXPECTED_SHARE_BASIS`（P/E·Historical·DCF·ReverseDCF→`ttm`，P/B·EV··FCF Yield·SOTP·NAV→`market`，`unknown` 不判异常）+ `ShareCountAuditRow.source/as_of/basis_expected` + `ModelAgreement.share_count_reliable`（基于**独立证据**而非单源）；`reporting/verdict_intuition.py` 股数证据不一致 → headline 封顶「**每股口径不可靠**」（**EV 级结果保留**）。验证：`python -m pytest -q` → **542 passed**（Session #40 的 522 → 542，新增 `tests/test_avgo_audit_remediation.py` 15 用例）；`ruff check .` → **All checks passed!**；`tests/test_golden_report.py` 通过 → **golden 零漂移**（**未重生成基线**）。
Project Status (前序·Session #40): Session #40 — **跨行业阈值校准（M-67）+ SBC 归一化下沉 FCF 主链（M-69）**。目标：消除 Session #39 自身遗留的两条 Known Issue（全局初值阈值 + SBC 多处各自调用），**不新增估值模型**。① **M-67 · 跨行业阈值校准**：新建 `analysis/threshold_calibration.py`（**运行时单一来源**）——按业务原型 FCF-margin 波动分档（3–5 年营业利润率 σ 代理：`<0.03 stable` / `0.03–0.06 moderate` / `≥0.06 volatile`），**带宽随波动放大**（`2pp/4pp/1.75×` → `3pp/5pp/2×` → `4pp/7pp/2.5×`）；β 最小同业地板按 **peer-pool 广度**分档（宽池 `5` / 窄池 `3` / 未知 `4`，窄池=`{NEOBANK, FINTECH, CONGLOMERATE}`）；两来源校准（离线篮子 σ 冻结于 `CALIBRATION_EVIDENCE` + 领域先验），**未知原型回退 moderate 带，绝不静默重判**；`analysis/divergence.py::_fcf_margin_check()` 审计行追加 `〔行业校准[tier]（观测 σ, n）：…〕`，`valuation/wacc.py::_bottom_up_reliability_label()` 按原型取地板（**惰性 import**）。② **M-69 · SBC 下沉**：`data/fcf_utils.py` 确立**双函数出口**——`resolve_ttm_fcf()`（raw primitive，仅存在性检查，不施加 SBC）+ `resolve_ttm_fcf_normalized()`（value producer，SBC **恰好一次**，生效加 `+sbc_normalized` 后缀，缺失返 `missing` 不臆造零）；`models/reverse_dcf.py` / `models/multiples.py::FCF Yield` 改为消费共享出口，**消除两处各自调用 = 结构性杜绝 SBC 双计**（保留 Phase D 缺失守卫）。③ **循环导入修复**：`wacc.py` 模块级 `from analysis.threshold_calibration import …` 触发 `models.dcf → valuation.wacc → analysis → analysis.expectation → models.reverse_dcf → models.dcf` 环，改为函数体内惰性 import（零行为变更）。ID 诚实性：`TODO.md` 中 M-68 已被 Monte Carlo 截断占用，故 SBC 下沉**正名为 M-69**。验证：`ruff check .` All passed；pytest **522 passed**（Session #39 的 507 → 522，新增 15 用例）；golden **零漂移**（未重生成基线）。
Project Status (前序·Session #39): Session #39 — **口径统一 + 报告解释修复（用户代码审查 / Phase A–F，不新增估值模型）**。目标：**统一现有模型的财务口径，并让报告正确解释计算结果**。① **Phase A · FCF 诊断相对化**：`analysis/divergence.py::_fcf_margin_check()` 触发由「绝对差 ≥15pp」改为**相对判断**（`FCF_MARGIN_ALIGNED_PP=0.03` / `FCF_MARGIN_FLAG_PP=0.05` / `FCF_MARGIN_HIGH_RATIO=2.0`；符号翻转 / ≥5pp / >2× TTM → flag），**GOOG TTM 4.2% → 预测 13.7% 不再被误判 ALIGNED**；新增 `_fcf_normalization_layer()`（TTM vs 3–5 年历史正常化：CapEx/D&A/ΔNWC/FCF margin，区分暂态资本开支周期 vs 结构性经营现金流恶化，历史均值不当未来正常值）。② **Phase B · TV/EV 措辞分级**：`_tv_check()` 报告分级与风险阈值**分离**（<50% 显式期占多数 / 50–70% 终值占多数 / 70–80% 高终值依赖需审查 / ≥80% 风险警告），**73.9% 现读作「高终值依赖，需要审查」**。③ **Phase C · MC 统一 Equity Bridge**：`simulation/monte_carlo.py::_project_one/_project_one_path` 改调 `enterprise_to_equity()`（与 DCF 同源）；`ev is None → None`（不静默按 0）；零扰动锚点 == DCF。④ **Phase D · SBC 全覆盖**：`models/multiples.py::FCF Yield` 接入 `normalize_fcf_for_sbc()`（与 DCF 同口径）；**TTM FCF 缺失 → INSUFFICIENT_DATA**（不再伪装真实零）。⑤ **Phase E · β 三指标**：`valuation/wacc.py` 拆为 `Regression Stability` / `Bottom-up Reliability`（`BETA_BOTTOM_UP_MIN_PEERS=4` 以下降级）/ `Methodology Divergence`（**0.94 vs 1.41 → Material**）；分部 β 携带 peer 证据（`peer_levered`/`n_peers`/`rationale`）。⑥ **Phase F · Peer 溯源 + 股数审计**：新增 `PEER_SOURCE_EXACT_SECTOR_ANCHOR`（静态板块锚点 ≠ 实时同业中位数）；`analysis/model_agreement.py` 新增 `ShareCountAuditRow` + `share_count_audit_table()`（Model｜Share Count｜Basis｜Deviation vs Market）。⑦ **MC 截断透明度**：`MonteCarloResult` 新增 `sample_driver_mean/std` + `lower/upper_bound_hit_rate` + `gordon_constraint_hit_rate` + `distribution_transparency_note()`（请求 μ/σ vs 实际样本 μ/σ）。验证：`ruff check .` All passed；pytest **507 passed**（golden **零漂移**，未重生成基线）。
Project Status (前序·Session #38): Session #38 — **Phase 1 · Valuation Integrity（6/6）**。目标：估值无错误输入、无错误来源、无错误股权价值桥接。① **Beta 溯源**：`data/providers.py::_estimate_beta` 返回 `{"beta", "provenance"}`（source/method/window_label/window_start/window_end/price_basis/n_observations/missing_periods/benchmark/verified）；provider β 优先、regression β 仅作缺失回退但两者均入 provenance 对比；`valuation/wacc.py::_format_beta_source()` 据 provenance 如实渲染（不再硬编码“3Y monthly vs SPY”）。② **复权价格 + 日期连续性**：β 回归优先用 `adjclose`（缺失回退 raw close 并在 `price_basis` 如实标注），ISO 网格缺口计入 `missing_periods`。③ **EV↔Equity 独立桥**：新增 `valuation/equity_bridge.py`（`Equity=EV−NetDebt−Minority−Preferred−Leases−OtherClaims+NonOpAssets`，含重复扣除守卫 + 精确逆运算），接入 DCF / Reverse DCF / Multiples / SOTP / Unit-Economics / NAV。④ **SBC 归一化**：新增 `valuation/sbc.py`（expense 扣 FCF vs dilution 调整股数，**二选一不重复计**；记录调整前后 FCF 与每股），接入 Reverse DCF。⑤ **币种感知 Rf**：`config.CURRENCY_RISK_FREE_RATES` + WACC 按现金流币种选 Rf（USD 走实时国债，非 USD 走 anchor 并标注 mismatch）；终值增速 GDP 上限随币种调整（`CURRENCY_NOMINAL_GDP`）。⑥ **WACC 原始/钳制分离**：`wacc_raw`/`wacc_clamped`/`wacc_clamp_reason` + `wacc_clamp_note()`。验证：`ruff check .` All passed；pytest **474 passed**（golden 零漂移）。
Project Status (前序·Session #37): Session #37 — **类型检查归零（Pyright 0 error / 0 warning）**。`npx pyright` 从 **40 errors + 3 warnings** 收敛到 **0**，纪律：**只补类型收窄/守卫，不改行为**（golden 零漂移，pytest 436 passed）。修复要点：① `analysis/model_agreement.py` 股数反查把「getattr 链式守卫」改为**显式循环 + None 收窄**（消除 `float(None)` / `None.shares_used`）；② `classification/taxonomy.py` 构造 `BusinessTaxonomyProfile` 时 `revenue_composition or RevenueComposition.unavailable()`（参数声明为 `Optional` 的收窄）；③ `data/segment_revenue.py::to_revenue_composition` 改用 `List[Tuple[Segment, float]]` 显式收窄收入为非空数值（消除 `float(Optional)`）；④ `data/industry_beta.py::_coerce_segments` 前置 `weight is None` 守卫；⑤ `models/reverse_dcf.py` 反向 DCF 上下限改用**显式 None 判定**（`bt_params.get()` 值为 `_Opt[float]`，原本 `.get(k, default)` 仍带 `None`）；⑥ `data/providers.py` 分部收入 import **移出 try**（消除 `possibly unbound`，import 本不会因网络失败）；⑦ `data/sic_map.py` `map_sic_to_yahoo` / `_normalize_sic` 入参**放宽为 `Optional[Union[str, int]]`**（测试断言 int 与 str 等价，函数本就 `str(sic)`）；⑧ `data/akshare_provider.py` 可选依赖 `akshare` 三处 import 加 `# pyright: ignore[reportMissingImports]`（已被 `try/except ImportError` 守卫）；⑨ 测试端 `tests/test_industry_beta.py` 为 `dict()` 变量（`**kwargs` 展开）加 `Dict[str, Any]` 标注 + `assert res.segments is not None` 收窄 Optional 字段。
Project Status (前序·Session #36): Session #36 — **仓库级 Ruff 清理（lint 0 error）**。新增 `pyproject.toml` 固化 lint 标准：`extend-exclude` 排除一次性开发/调试脚本（根目录 `_*.py`、`**/_*.py`、`verify_bot.py`——其 E402 为 `sys.path` 引导的**有意**写法）；`per-file-ignores` 对 `main.py`/`tests/conftest.py` 放行 E402（同样为导入前的 `sys.path` 引导）。产品/测试代码全量修复：`config.py` 将中段 `import sys/io/typing` 上移顶部并清理未用导入；`valuation/wacc.py::_credit_spread_for_icr` 与 `data/providers.py`(E701×8/E702×4) 展开为多行；`classification/ml_classifier.py` 重命名歧义变量 `l→lab` 并删除死变量（`cong_p`/`ml_used`）；`analysis/sensitivity.py` 删除死变量（`bear_wacc`/`bull_wacc`）；另 `ruff --fix` 自动清理 35 处（F401 未用导入/F541 无占位符 f-string/F841 死变量/E702）。验证：`ruff check .` → **All checks passed**；pytest **436 passed**（行为零回归，golden 零漂移）。
Project Status (前序·Session #35): Session #35 — **用户代码审查 4 项 P1 全部修复**。P1-SOTP：`models/sotp.py` 引入**三态状态机**（`SOTP_SOLVED` / `SOTP_APPROXIMATE` / `SOTP_INSUFFICIENT`）——ML 暴露度拆分不再伪装成独立分部估值证据（无真实分部收入/利润 → `display_only`，剔除出共识），并输出每分部 `segments_detail`。P1-6：`valuation/wacc.py` 多窗口 β 稳定性**真正参与估计**（Blume-style shrinkage 向 β=1.0 收缩，收缩量随极差线性增长）+ **Raw/Selected/Adjusted β 三分离** + β 不确定性**传导至 WACC 区间**（`wacc_beta_lo`/`wacc_beta_hi`，"不确定性硬编码的稳健估计"非简单平均）。P1-7：报告 ETR **口径分离**——市场快照以 **WACC 实际使用 ETR** 为主、供应商值另标 **Provider ETR**（消除 20.4% vs 19.634% 双数字）。P1-8：`analysis/model_agreement.py` 新增 **Valuation Comparability Gate**（7 维：ShareCount/Currency/ValuationDate/FinancialPeriod/EV-EquityBasis/DataQuality/PeerValidity）——**不兼容模型可展示但不进入共识中位数**（未声明口径 ≠ 冲突，不排除）。验证：pytest **436 passed**（golden 因 SOTP→display_only 行为修正**有意重生成**，差异逐条核对为预期）。
Project Status (前序·Session #34): Session #34 — **用户代码审查 4 项 P0 全部修复**。P0-1：行业 WACC 区间改读 **Taxonomy canonical key**（新增 `CANONICAL_KEY_WACC_RANGES`，`util.electric`/`util.gas`/`util.water`/`util.ipp`/`util.diversified` 各自独立区间；修复 `"Utility"` ⊄ `"Utilities"` 子串陷阱 + 破折号归一化；VST 类不再静默落入 Market Average）。P0-2：`_effective_tax_rate()` 改**非重叠期间**（TTM-only / 去重财年 / 默认）+ 新增 `tax_period_basis`。P0-3：新增 **`ShareCountBasis` 股数口径契约**（各模型申报 `share_count`）+ 共识层**可比性校验**（偏差 >10% 剔除出中位数，绝不重写股数凑数）。P0-4：`FCF Yield Gap` 改**非对称方向感知**（正 FCF 高收益率不再判风险；负 FCF 按恶化幅度与持续性评估）。验证：pytest **429 passed**（golden 因 P0 行为修正**有意重生成一次**，逐条核对为预期修正）。
Project Status (前序): Session #31–#33 — **50 只跨行业蓝筹全量验证 + Reverse DCF 递归自我改进 3 轮**。Round 1（Session #31）：结构化 bound（市场价超出业务增长带 → 诚实输出「≥ 上限 / ≤ 下限」+ `ev_at_bound`，不伪造点估）；Round 2（Session #32）：bound 透传 `ExpectationGap` + `_gap_section` 镜像（消除 N/A 与自相矛盾）+ 批量审计 harness 记录风险旗标；Round 3（Session #33）：**Growth Risk 改为下行离散度**（semi-deviation，消除 CV→0 爆炸与单调收购爬坡的假 High）+ **隐含 WACC 以无风险利率为下限**（sub-Rf 点估 → NO_SOLUTION_IN_RANGE 诚实边界）。验证：50/50 分类、0 路由违规、0 缺陷；pytest **429 passed**（golden 因行为修正二次重生成）

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
✅ 已完成 Session #16：估值引擎诚实性与一致性修复（用户代码审查 4 项发现 · Phase 1「修复现有引擎」）
  - 触发：用户直接审查 `forecasts/fcf_projection.py` + `models/reverse_dcf.py`，列出 4 项问题（问题 1 数学/高优先级、问题 2 功能不足、问题 3 代码风险、问题 4 设计说明）
  - 问题 1（负终期 FCF 被伪造成正终值 · 高优先级 · 数学）：`if last_fcf <= 0: last_fcf = avg_abs` 把烧钱公司的负终期 FCF **偷改成正数**再进 Gordon → 人为制造正终值（Normal DCF / Reverse DCF / Monte Carlo 三处各复制一份）。修复：新增统一出口 `gordon_terminal_value()`（`TerminalValueResult`）——终期 FCF ≤ 0 时**抑制终值**（不翻转符号），估值退化为显式期现值**下限**，`terminal_fcf_negative=True` + `SolverStatus.APPROXIMATE` + note「需转型假设」（ADR-028）
  - 问题 3（预测年限跨标的污染 · 代码风险）：`reverse_dcf.py` 的 `self.horizon = int(horizon)` 写回 `NAME_TO_MODEL` **共享单例** → SaaS(7)→Utilities(10)→Unknown **沿用 10**。修复：新增单一真源 `config.resolve_forecast_horizon(business_type)`；删除 `self.horizon`，每次 `calculate()` 解析局部年限；DCF/ReverseDCF/Scenario/Sensitivity/MonteCarlo/Expectation 全链路统一（ADR-029）
  - 问题 2（Reverse DCF 仅反推 Revenue CAGR · 功能不足）：确认为 Phase 2 升级项（多变量反推 + 约束式求解器）→ 记入 TODO L-08，本轮不改
  - 问题 4（FCF Margin 非独立求解变量 · 设计说明）：FCF 由 `ForecastEngine._extract_history()` 固定历史营业利润率/DA/CapEx/NWC/税率驱动，实为「Revenue Growth → FCF → EV」→ 记入 TODO L-08 备注（报告需显式展示固定假设）
  - 附带修复：`analysis/risk.py::_terminal_value_risk()` 新增 `terminal_fcf_negative` → HIGH 旗标分支（抑制后 `tv_percent_of_ev=0`，原阈值检测不再触发会导致旗标丢失）；WACC−g 下限统一为 `MIN_WACC_TG_SPREAD=0.005`（替代散落 `1e-3`/`1e-4`）；反向 DCF 新增求解器 residual 检查（`rel_resid>1e-3` → APPROXIMATE）
  - 验证：pytest **116/116 全通过**（106 → 116，新增 10 用例：`TestTerminalValueHonesty` 6 + `TestHorizonIsolation` 4）；golden 基线有意漂移 1 字段（`NBIS.median_value: 12.76 → 10.46`，旧值即伪正终值虚高，已审阅）
✅ 已完成 Session #17：Reverse DCF 升级为约束式隐含求解器（Phase 2 · 用户清单）
  - 触发：用户 Phase 2 清单「升级求解器」——Implied Revenue CAGR / Operating Margin / FCF Margin / WACC / Terminal Growth / Constraint-based Solver（承接 Session #16「问题 2/问题 4 = Phase 2」）
  - 设计：**单变量 one-at-a-time**（非联合求解）——每解一个隐含值，其余假设固定在基准（先解出的营收 CAGR + FCF 桥历史 margin/DA/CapEx/NWC/税）。回答「若其它条件不变，当前价隐含的 X 是多少」（一方程多未知数联合求解欠定 → 无穷多解，故不做）
  - 约束式求解器 `_solve_implied_scalar()`（`models/reverse_dcf.py`）：**硬边界**（目标超出 [lo,hi] 可达区间 → `NO_SOLUTION_IN_RANGE` + note 指名绑定边界，**绝不钳制到边缘**）+ **单调性**（`increasing` 决定可达端）+ **残差检查**（`rel>implied_residual_tol(1e-3)` → APPROXIMATE）
  - 四个隐含驱动：`implied_operating_margin`（改 NOPAT 桥）/ `implied_fcf_margin`（新增 flat-margin 桥 `project_enterprise_value_flat_margin()`，`FCF_t=revenue_t×fcf_margin`，使 FCF margin 成为良定义独立目标）/ `implied_wacc`（下界 = `max(implied_wacc_lo, tg+spread)`）/ `implied_terminal_growth`（上界 = `min(implied_tg_hi, wacc−spread)`）
  - 落字段：`breakdown["implied_expectations"]`（`ImpliedSolve` dataclass：`value`/`status`/`residual`/`rel_residual`/`bound_lo`/`bound_hi`/`note`）；透传至 `analysis/expectation.py`（`ImpliedExpectations` 8 新字段 + `implied_constraint_notes`）；`reporting/dashboard.py::_implied_section` 渲染（含「不可解（超出约束区间）」与「_(近似)_」标注）
  - 验证：pytest **124/124 全通过**（116 → 124，新增 8 用例：`TestConstraintSolver` 5 + `TestImpliedExpectationsPhase2` 3）；AAPL 四驱动全解（OM 28.9% / FCF margin 27.1% / WACC 11.3% / TG 2.5%）；NBIS 四驱动全 `NO_SOLUTION_IN_RANGE`（绑定边界点名，无钳制）
✅ 已完成 Session #18：反解求解器 P0/P1 加固（用户代码审查 6 项发现）
  - 触发：用户静态审查 `models/reverse_dcf.py` / `forecasts/fcf_projection.py` 指出 6 项风险（3×P0 + 3×P1），要求「区分可直接确认的代码问题 vs 需运行测试确认的数值问题」
  - **P0-1 Brent 失败后 bracket 重校验**：`_finish_root()` 在 `brentq` 抛错后若 `f(a)·f(b) > 0` → 返回 `NO_SOLUTION_IN_RANGE`，**拒绝返回看似正常的根**；求解后一律计算 residual，`rel > implied_residual_tol` → APPROXIMATE（不再无条件 SOLVED）
  - **P0-2 单调性验证（区间采样）**：`_solve_implied_scalar()` 先以 `implied_monotonic_samples=21` 点采样，实测方向 `going_up`/`going_down`；非单调 → `_root_brackets()` 扫描变号区间（0 → 无解 / 1 → 求解 / >1 → `MULTIPLE_ROOTS`）；步长级平坦 → `NON_MONOTONIC`；不再仅凭两端点假设单调
  - **P0-3 负终值抑制贯穿**：`terminal_fcf_negative` 纳入 Reverse DCF `breakdown` 与 `implied_expectations`；`_finalize_revenue_cagr()` 在终期 FCF ≤ 0 时把 `SOLVED` 降级为 `APPROXIMATE` + note「Terminal Value Suppressed — Turnaround Assumption Required」；`analysis/expectation.py` 与 `dashboard._implied_section()` 透传渲染
  - **P1-5A 端点根**：Revenue CAGR 在 `ev_lo == target` / `ev_hi == target`（含容差）时**判定为边界解 SOLVED**，不再因严格 `< 0` 误判无解
  - **P1-5B 常数目标检测**：目标函数在区间内近似常数（`fmax-fmin ≤ abs_tol`）→ 命中目标时 `FLAT_OBJECTIVE`、不命中时 `NO_SOLUTION_IN_RANGE`，不输出无意义隐含值
  - **P1-6 测试补强**：新增 10 类用例（Revenue CAGR 端点根 ×2 / 无效 bracket / 非单调无根 / 多根 / 常数目标 ×2 / 负终值降级 ×4 / FCF-Margin·WACC·TG round-trip / 多股票状态隔离 ×2）
  - 验证：pytest **142/142 全通过**（124 → 142，新增 18 用例）；golden 无漂移
  - 修复过程中发现的真实缺陷：单调性判定原先误用「残差容差」（被 |target| 放大）→ 把单调曲面误判为 NON_MONOTONIC；可达区间 `lo_val/hi_val` 在递减方向赋反 → 误报无解（均已修正）
✅ 已完成 Session #19：Rf 单一真源 + Terminal Growth 三档语义重定义 + Quality-Weighted Median 边界修复（用户代码审查 2×P0 + 1×P1）
  - 触发：用户静态审查 `valuation/wacc.py` / `valuation/terminal_growth.py` / `models/dcf.py` / `analysis/model_agreement.py`，指出 2 项 P0 + 1 项 P1，并强调「这是实际代码问题，不是推测」
  - **P0-1 Rf 单一真源（Cost of Debt）**：`calculate()` 已按「MarketData → TreasuryYieldProvider → config」解析 `rf`，但 `_implied_cost_of_debt()` **重新独立重读** `data.market.risk_free_rate or DEFAULT_DCF_CONFIG.risk_free_rate` → 当 MarketData Rf 为空而 Treasury 取到 5.103% 时，CAPM 用 5.103% 而债务成本 fallback 用 4.50%（配置默认）→ 报告内部口径撕裂。修复：`_implied_cost_of_debt(data, risk_free_rate=rf)` 接收已解析 Rf，所有债务成本 fallback 与 CAPM 共用**同一 Rf**；独立调用（如测试）仍回落到原优先级链
  - **P0-2 Terminal Growth 三档语义**：原实现 `high = Base + 0.5%` 且注释/文档写 `"not GDP-capped"`，把乐观情景区间当作「长期稳定终值增长率」呈现 → 若 Base = 4.5%（长期名义 GDP 上限）则 High = 5.0% 被误读为「长期可持续的终值增长率」。修复（遵循用户「不要机械地要求 High < GDP，但不得误称为长期稳定终值增长率」）：**重定义经济学含义**——Base = 唯一受长期名义 GDP + Gordon 上限约束的长期稳定终值增长率（基准估值用）；Low = 保守情景；High = 乐观情景区间（可高于长期 GDP，仅受 Gordon 上限 WACC−0.5% 约束），并新增引擎字段 `high_exceeds_gdp` / `gdp_ceiling` / `band_labels`（`BAND_LABELS` 契约），当 High > GDP 时在推导追踪、DCF 假设说明、dashboard 渲染处**显式标注为乐观情景**
  - 渲染契约化：`models/dcf.py` 的 `Terminal Growth (High)/(Base)` 说明与 `reporting/dashboard.py` 的三档区块均消费引擎输出的 `high_exceeds_gdp` / 语义标签，不在渲染层硬编码口径词
  - 验证：pytest **147/147 全通过**（142 → 147，新增 5 用例：Rf 同源 ×2 + 三档语义 ×3）；golden 无漂移；端到端 NVDA/MSFT/NOW/NBIS 均 Base=4.5% / High=5.0% / `high_exceeds_gdp=True` 且报告出现「⚠ High 5.00% 高于长期名义 GDP 4.50%」标注
  - **P1-3 Quality-Weighted Median 边界缺陷**：原 `_weighted_median()` 返回**首个累计权重 ≥ total/2 的值**——当所有模型权重相等（常见）且求解模型数为**偶数**时，它返回第 n/2 个值，而非 `mean(values[n/2-1], values[n/2])`，导致「加权中位数」与普通中位数在等权时不一致（AAPL 报告 176.12 vs 165.24 即为该症状）。修复：改用标准 **midpoint 定义**（下加权中位数与上加权中位数的平均）——等权时**精确退化为普通中位数**；零/负权重被剔除；`models == 1` 返回其自身值
  - 验证：pytest **163/163 全通过**（147 → 163，新增 `tests/test_model_agreement.py` 16 用例：等权偶数/奇数、不等权、精确半权平局、零/负权重、缺失权重默认 1.0、空输入）；golden 出现**已审阅的有意漂移**（4 只标的 `median_value_weighted` 归位到普通中位数：AAPL 123.99→132.19 / AMT 57.82→109.85 / JPM 139.22→151.37 / NOW 147.21→148.84；MSFT·NBIS·NVDA·PLD·XOM 保持不变），已 `UPDATE_GOLDEN=1` 重生成基线
✅ 已完成 Session #20（Phase 2 — 预测 / Monte Carlo / 情景）：MC 双模式 + 去人为利润率地板 + 路径锚点对账 + 经营/折现情景拆分 + 报告透明化
  - 触发：估值完整性重构任务「Phase 2」，核心缺陷——MC 用**独立于确定性 DCF 的粗糙分布**（历史统计 + 人为 +2% 利润率地板），导致「MC 中位远低于确定性 DCF」（MSFT：MC $255.70 vs DCF $170.70 却 CV 仅 6.6%）无法解释；且经营驱动情景与折现率情景被混在同一「情景」区块
  - **MC 双模式（ADR-034）**：`MODE_BASE_CASE`（以确定性 DCF 的同一 base 预测为中心，仅扰动假设）/ `MODE_HISTORICAL`（历史分布，完全独立）；`run(..., mode=None, dcf_value=None)`——无 `dcf_value`（金融股走 RIM/DDM 或无解）时**自动回退 historical 并附说明**，不静默
  - **去除人为利润率地板**：取消 MC 内 `max(om, +2%)` 硬地板，允许负利润率（NBIS 等亏损期标的如实反映）；驱动边界全部可配置（`MonteCarloConfig`：营收 CAGR / OM / WACC / TG 上下界）
  - **路径形参化锚点对账（核心）**：原 MC 以**平坦 CAGR / 平坦 OM** 投影，而确定性 DCF 用**衰减增长路径 + 漂移利润率路径**（`ForecastEngine._build_base`）→ 零扰动时锚点 ≠ DCF（MSFT 偏差 +13.85%）。修复：新增 `_base_case_path()`（提取 DCF base 的逐年 `shape_rev[i]` 与 `margin_offsets[i]`）+ `_project_one_path()`（在 `(eff_cagr, eff_om)` 处**精确复现** DCF base FCF 路径）→ 零扰动锚点 = 确定性 DCF（MSFT $197.34 vs $197.34，差 +0.0%；AAPL $77.88 vs $77.88，+0.0%）
  - **负股权价值地板一致**：MC 锚点沿用 DCF 的「负股权价值 → 归零」约定（NBIS：锚 $0.00 vs DCF $0.00，差 +0.0%），两处口径不再撕裂
  - **经营情景 vs 折现率情景拆分（ADR-035）**：新增 `ScenarioAnalyzer.run_operating()`（营收增长 × 利润率扰动 → FCF → EV，`scenario_kind="operating"`）；原情景标 `scenario_kind="discount_rate"`；报告拆为「🎭 折现率情景」与「🏭 经营性情景」两区块；金融股 `run_operating` 返回 `{}`（成本法口径无 DCF 经营情景）
  - **报告透明化（Phase 2 验收 6）**：MC 区块新增模式 / 随机种子 / 请求数 / 有效数 / 无效数 / 截断数 / 参数分布 / 相关矩阵驱动；对账行**仅在 base_case 模式**渲染；明确标注「这是 DCF 假设的扰动分布，不是独立估值证据」
  - **用词修正（验收 10）**：`P(股权价值归零/破产)` → 「模拟下的 Equity Value Wipeout Probability」，方向与基准（equity value 归零，非公司破产）一致
  - 验证：pytest **217/217 全通过**（163 → 217，新增 `tests/test_monte_carlo_modes.py` 14 用例 + 既有测试全绿）；`compile_exit=0`；golden 无漂移（`golden_report.render_report` 走 `monte_carlo=None`，不受影响）；端到端 MSFT/JPM/NBIS 报告渲染确认（JPM 金融股正确落 historical 模式、经营情景区正确缺省）
✅ 已完成 Session #21（Phase 3 — WACC β 多窗口 / peer 来源溯源 / 同源证据去重）：估值完整性重构 P1
  - 触发：估值完整性重构任务「Phase 3」——消灭「单一 β 掩盖估计不稳」「peer 倍数来源不明」「同源证据重复计票抬高一致性」三类不透明
  - **3.1 WACC β 多窗口敏感性 + bottom-up 槽位**：`data/models.py::MarketData` 新增 `beta_windows`（窗口标签→回归 β）/`industry_beta`（bottom-up/peer unlevered β，缺失即 `None`，绝不伪造）；`data/providers.py` 新增 `BETA_WINDOWS=(2y_weekly/3y_monthly/5y_monthly)` 常量 + `_estimate_beta_windows()`（逐窗口独立回归，失败窗口显式存 `None`）；`_estimate_beta()` 由单窗口泛化为 `(range_, interval, min_obs)` 参数化，周线用 ISO-week keying；`valuation/wacc.py::WaccBreakdown` 新增 `beta_windows`/`beta_dispersion` + `beta_window_note()`（<2 个窗口返回 `None` 不臆造；极差 >0.50 标注「窗口间波动较大」）
  - **3.2 peer 倍数来源溯源标签 + 样本数**：`models/multiples.py` 4 档来源常量（`PEER_SOURCE_EXACT_INDUSTRY`/`SECTOR_FALLBACK`/`BUSINESS_TYPE_FALLBACK`/`APPROXIMATE` + `PEER_SOURCE_LABELS` 封闭集）；`_sector_peer_multiple`/`_resolve_peer_bucket` 返回 4 元组 `(value, source_text, source_kind, n_peers)`；`calculate()` breakdown 落 `peer_source_kind`/`peer_sample_size`；`reporting/dashboard.py` 渲染「🔎 同行倍数来源 (可审计)」区块
  - **3.3 model_family 同源证据去重**：`analysis/model_agreement.py` 新增 `_MODEL_FAMILY`（P/E↔Historical Multiples→`earnings_multiple`、EV/Sales↔EV/Sales (Unit Econ)→`sales_multiple`、DCF/ReverseDCF→`dcf_forecast`）+ `_independent_evidence()`；一致性覆盖率门控由 `n_solved` 改为 `n_independent`（去重后独立证据数）；`ModelAgreement` 新增 `n_independent_evidence`/`duplicate_evidence_groups` + 去重说明 note
  - 验证：pytest **231/231 全通过**（217 → 231，新增 `tests/test_phase3_integrity.py` 14 用例：β 窗口 ×7 / peer 溯源 ×3 / 同源去重 ×4）；新版文件 ruff clean；端到端 AAPL/NBIS/JPM 确认 `peer_source_kind` 全链路透传（EXACT_INDUSTRY / APPROXIMATE n=5 / EXACT_INDUSTRY）
✅ 已完成 Session #22（Phase 4 — 全量回归 + 边界用例 + 验收断言化）：估值完整性重构收尾
  - 触发：估值完整性重构任务书「Phase 4：测试与验收」——全量 pytest + golden 回归 + 边界用例 + Ruff/Pyright + 逐条对照 10 条验收标准
  - **回归 universe 扩展**：`tests/golden_report.py::BASKET` 由 9 只 → **18 只**（新增 GOOGL/AMZN/AVGO/ORCL/CRWV/UPS/KR/BAC/NU，覆盖 MatureTech/ConsumerCyclical/Semiconductor/FinTech/Industrial/ConsumerStaples/Bank 各 archetype）；实测 18 只 `check_invariants()` 缺陷全为空（分类路由正确：GOOGL→MatureTech、AMZN→ConsumerCyclical、AVGO→Semiconductor、ORCL→MatureTech、CRWV→MatureTech(AI/Cloud)、UPS→Industrial、KR→ConsumerStaples、BAC→Bank(ke)、NU→FinTech(ke)）
  - **golden 指纹扩展（验收 6）**：`build_fingerprint()` 新增 5 字段——`n_independent_evidence`（Phase 3 去重后独立证据数）、`raw_solved_count`、`outlier_count`（IQR 排除数）、`effective_aggregation_count`（参与中位数的最终模型数）、`core_model_excluded`；报告样本口径恒等式 `effective + outlier == raw` 由 `math_audit` 断言
  - **invariant 加固（验收 1/2）**：`check_invariants()` #2 覆盖率封顶门控由 `n_solved` → `n_independent_evidence`（与 Phase 3 计票口径一致）；新增 invariant 2b——**核心模型（DCF）被 IQR 排除却仍输出 Very Strong/Strong/Moderate → 判为缺陷**（禁止「静默移除核心模型却显示高一致性」）
  - **边界/验收用例断言化**：新建 `tests/test_phase4_integrity.py`（9 用例逐条锚定任务书验收标准）——风险等级底线（标准 3，全 universe：整体标签永不比最差旗标更安全 + High 旗标强制整体 ≥High + Floor 实际触发）、IQR 排除核心模型→`Unresolved Disagreement (Review Required)`（标准 1/2）、一致性封顶按独立证据数而非解算数计票、极端 TV/EV 支配下调 DCF 权重、未知身份不冒充精确行业匹配（标准 8/9）、全 universe invariant + 样本口径（标准 6/7/10）、负 FCF 建构标的保留旗标
  - **golden 基线重生成**：`UPDATE_GOLDEN=1 pytest tests/test_golden_report.py` → 2 passed / 1 skipped；原 9 只 ticker 既有字段**无漂移**（仅新增字段 + 新增 9 只条目）
  - **静态检查**：Ruff 对本次改动文件（`analysis/risk.py` / `tests/golden_report.py` / `tests/test_phase4_integrity.py` / `analysis/model_agreement.py` / `tests/test_providers_provenance.py`）**All checks passed**（顺带清理 `risk.py` 未用 `Tuple` 导入 + 未用 `reason` 局部变量、`golden_report.py` 未用 `by_name`）；Pyright 未安装（不可用，如实记录）
  - 验证：pytest **240/240 全通过**（231 → 240，新增 9 用例）；修复 `tests/test_providers_provenance.py`——原用 `"BAC"` 作「未知 ticker」，Phase 4 新增 BAC fixture 后不再抛异常 → 改为 `"ZZZZ"`（明确不在 fixture 集）
下一步：Phase 4 已收尾。后续（非本次范围）：Pyright 安装后补类型检查；H-03 接入二级数据源补 sector/industry（唤醒 bottom-up β 槽位与分类准确率）
✅ 已完成 Session #23：内部标准 Taxonomy + 五维公司拆解 + 黄金法则（additive shadow 接线，golden 零漂移）
  - 新建 `classification/taxonomy.py`（99 节点标准树）+ 五维模型（Identity / Business Model / Revenue Composition / Economic Profile / External Classification）
  - 黄金法则：economics 只能族内细化 identity，跨族一律不提升；同族兄弟冲突收敛至 common ancestor
  - 冲突分级 ConflictKind + `node_from_yahoo()` 两段式 longest-key-wins；CompanyProfile 新增 8 shadow 字段（不改路由）
  - 新建 `tests/test_taxonomy.py`（48 用例）；修复 6 处真实缺陷；pytest **288/288**，golden 零漂移
✅ 已完成 Session #24：三源 sector/industry 补全链 + bottom-up β 唤醒（H-03）
  - 新建 `data/sic_map.py`（SEC SIC → Yahoo 桥接，~180 精确 4 位 + ~68 大类 + ~130 关键词；契约：每个映射产出必可分类）
  - 新建 `data/industry_resolver.py`（三源链：FinanceDatabase 离线 → SEC EDGAR `sic`/`sicDescription` → Wikidata SPARQL P452 兜底；类级 + 磁盘缓存；合规 User-Agent）
  - 新建 `data/industry_beta.py`（动态同业无杠杆 β：Hamada `β_u=β_L/(1+(1−t)·D/E)`，t=0.21，中位聚合，<3 同业返回 None）
  - `data/providers.py` 接线填充 `MarketData.industry_beta`（长期空置槽位唤醒）；`classifier.py` 补 `("asset management", BANK)` 覆盖缺口
  - 新建 3 个测试文件共 45 用例；pytest **333/333**（288 → 333），golden 零漂移；Ruff 新文件全绿
  - 在线实测：SEC 层 10/10 精确命中；layer-2 硬规则覆盖 75% → **78.3%**（未达 90%，剩余为真值/粒度差，非 None 缺口）；Semiconductors bottom-up 无杠杆 β = **1.2447**
✅ 已完成 Session #25：Bottom-up β 升级「业务身份三级筛选 + 完整 β 链」并接入 CAPM（M-34）
  - `get_companies_by_business_identity` 三级筛选（L1 同子行业+商业模式 / L2 相邻行业+经济特征 / L3 Damodaran 基准）
  - 完整链：Peer Levered → Unlevered(Hamada) → Median → Cash-adjusted → Target Relevered；`wacc.py` 三段优先级；`clamped` 语义修正
  - +20 用例；pytest 333 → **353**；golden 零漂移
✅ 已完成 Session #26：分部收入数据层 (M-31) + Segment-level β (M-35)
  - 新建 `data/segment_revenue.py`（FMP `/revenue-product-segmentation` 为主源，无 key → `[]` 绝不伪造，类级 `_MEM` + 磁盘缓存）+ `to_revenue_composition`（→ taxonomy ③）/ `segment_weights(by="value")`（营业利润优先、回退收入）
  - `data/industry_beta.py` 新增 `derive_segment_level_beta()`（分部 label→行业（~65 关键词，具体优先）→ 复用 M-34 三级筛选求 β_u → 按业务价值权重整合 → cash-adjust → relever；`level=0` / `source="segment-weighted"` / `segments` 审计；门控 `min_segments=2` + `_MIN_SEGMENT_COVERAGE=0.60` → 回退公司级）
  - `derive_bottom_up_beta(segments=...)` 优先分支（透明回退）；`FinancialData` +`revenue_composition`（`Optional[Any]`）；`classification/taxonomy.py` 消费端读取；`data/providers.py` 接线
  - **关键纠错**：SEC `companyfacts` JSON **不含**分部（dimensional）数据（AAPL `Axis`/`ProductOrService`/`StatementBusinessSegments` 计数均为 0）→ M-31 改用 FMP 为主源，SEC 层明确排除
  - +23 用例；pytest 353 → **376**；golden 零漂移
✅ 已完成 Session #27：M-35 收尾迭代（FMP 多 key 轮换 + `/stable` 新端点 + Shape C 解析 + 分部→行业关键词表数据驱动补全）
  - `data/segment_revenue.py`：`FMP_API_KEY` 支持**逗号分隔多 key**（`_fmp_keys` + `_from_fmp` 按序尝试，非 200/不可解析透明落到下一 key，全耗尽 → `[]`）；层优先序 `_from_fmp_stable` → `_from_fmp_v4` → `_from_fmp_v3`
  - **端点纠错**：FMP `/api/v4`、`/api/v3` 自 2025-08-31 起 403 `Legacy Endpoint` → 改用 `/stable/revenue-product-segmentation`
  - **Shape C 解析**：`_extract_fmp` 识别 `[{...,"fiscalYear":..,"period":..,"date":..,"data":{label:val}}]`，只取嵌套 `data` 的分部，元数据绝不泄漏为分部
  - `data/industry_beta.py::_SEGMENT_INDUSTRY_KEYWORDS` **数据驱动两轮补全**（真实 FMP 语料：90 票 → 41 解析 → 172 distinct label；覆盖 102 → 107）；桶/地理/品牌名/缩写**恒不映射**
  - +测试（Shape C / `/stable` 优先 / 多 key 轮换）；pytest 376 → **382**；golden 零漂移
✅ 已完成 Session #28：商业理解层（六模块映射 + 四态决策契约 + Identity Resolution，M-37）
  - `classification/taxonomy.py` 新增 `DecisionStatus`（CONFIRMED/PROBABLE/AMBIGUOUS/INSUFFICIENT_DATA）+ `decide_status()` 确定性映射 + `CompanyProfile.taxonomy_decision_status`（shadow）
  - `data/identity_resolver.py`（新建，CIK/SIC/FIGI；Layer A SEC 链 + Layer B OpenFIGI 需 key；缺失一律 None）
  - `classification/business_intelligence.py`（新建，业务证据收集器；缺失显式标注）；pytest 382 → **398**；golden 零漂移
✅ 已完成 Session #29：SEC 10-K / 20-F filing-instance XBRL 业务证据抽取（M-38）
  - `data/filing_evidence.py`（新建：CIK → submissions → 10-K/20-F → `*_htm.xml` 实例；`parse_segment_revenue` 纯函数，四重防重复，`source="sec-xbrl"`，drop-in 兼容）+ 四态决策端到端测试
  - pytest 398 → **413**；golden 零漂移
✅ 已完成 Session #30：SEC filing-instance XBRL 生产化接入 providers 主链（M-39）+ Taxonomy 参与路由（M-32）
  - `data/segment_revenue.py::resolve_segments(ticker)` 生产默认源链（Layer 1 FMP → Layer 2 SEC filing-instance XBRL，两层皆空 → `[]`）；`data/providers.py` 改调源链 → FMP 缺 key / 失效 / 额度耗尽 / 未覆盖时自动降级
  - `classification/taxonomy.py` 新增 `taxonomy_routing_override()` 三道 gating（CONFIRMED + **跨 identity family 冲突** + 经济护栏）+ `ARCHETYPE_FAMILIES`（树推导）+ `TAXONOMY_ROUTING_STATUSES`；`classifier.py` / `ml_classifier.py` 对称 gate（对比内部身份判定 `best_bt`，非 `routing_bt`）
  - pytest 413 → **429**；golden **零漂移（未重生成）**
✅ 已完成 Session #34：用户代码审查 **4 项 P0** 修复（行业 WACC 身份键 / ETR 非重叠口径 / 股数口径契约 / FCF Yield 非对称风险）
  - **P0-1** `valuation/wacc.py`：新增 `CANONICAL_KEY_WACC_RANGES`（canonical key → 独立区间）+ `_normalize_industry_text()`（破折号归一化）+ `_match_industry_range()` 四级优先级 + `WaccBreakdown.industry_range_source`；修复 `"Utility"` ⊄ `"Utilities"` 子串陷阱（VST 类不再落入 Market Average）
  - **P0-2** `valuation/wacc.py::_effective_tax_rate()`：TTM-only / 不重叠去重财年 / 法定默认三口径 + `WaccBreakdown.tax_period_basis`
  - **P0-3** `models/base.py`（`ShareCountBasis`/`ShareCount`/`make_share_count`）+ 四模型 `share_count` provenance + `analysis/model_agreement.py` 可比性校验（偏差 >`SHARE_COUNT_COMPARABLE_TOL=0.10` 剔除出共识中位数，保留 EV/Equity Value 独立参考）
  - **P0-4** `analysis/risk.py::_forecast_risk()` Layer B：非对称方向感知（`_fcf_trend()` + `_downgrade()`；`fcf_yield_reference` 等阈值入 `config.py`）
  - pytest **429 passed**；golden 因行为修正**有意重生成一次**（差异逐条核对为预期旗标/中位修正）
✅ 已完成 Session #35：用户代码审查 **4 项 P1** 修复（SOTP 循环估值 / β 多窗口不稳定 / ETR 双数字 / 估值可比性 Gate）
  - **P1-SOTP** `models/sotp.py` 全量重写：新增三态常量 `SOTP_SOLVED`/`SOTP_APPROXIMATE`/`SOTP_INSUFFICIENT` + `SOTPSegment` dataclass（`is_independent_evidence()`/`as_dict()`）；**仅真实分部收入 + 独立 Peer Multiple → SOLVED 计入共识**；仅 ML 暴露度 → `INSUFFICIENT` + `breakdown["display_only"]=True`（不伪装独立估值证据）+ `segments_detail`（Revenue/EBITDA/Applied Multiple/Segment EV/Source/Confidence/As-of Date）；修复双重扣净债 bug
  - **P1-6** `valuation/wacc.py`：`beta_windows` 稳定性**参与估计**——`BETA_MAX_SHRINK=0.35` + `BETA_DISPERSION_SHRINK_THRESHOLD=0.50` Blume-style 收缩（**不取平均**）+ `beta_raw`/`beta_selected`/`beta_adjusted` 三分离 + `wacc_beta_lo`/`wacc_beta_hi` 不确定性传导
  - **P1-7** `reporting/dashboard.py::_market_section()`：ETR 主值改**WACC 实际使用 ETR**（`wacc_bd.effective_tax_rate`）+ `_etr_basis_suffix()` 标注 `tax_period_basis`；供应商 ETR 另标 **Provider ETR**
  - **P1-8** `models/base.py` 新增 `make_comparability()` + `ValuationResult.comparability`；`models/dcf.py`/`multiples.py`/`sotp.py` 接线声明口径；`analysis/model_agreement.py` 新增 **`_comparability_gate()`**（7 维冲突检测：币种/口径/财务期间/估值日期/peer_valid/数据质量）——冲突模型从 `solved_agg` 剔除并重算 `n_applicable`，**未声明口径不排除**
  - pytest **436 passed**；golden 因 SOTP→display_only **有意重生成一次**（PLD/NOW/NBIS/CRWV/NU：`n_solved` −1、`n_display_only` +1、`n_independent_evidence` −1，逐条核对为预期）
```

Overall Progress

```
97%
- 估值引擎核心: 99% (✅ 覆盖门控 + 质量加权中位 + WACC 区间 + 概率结论 + 反向DCF隐含量化 + Beta 单一出口/多窗口敏感性 + Replacement NAV 覆盖率锚 + Unit-economics EV/Sales 模型族 + 金融机构 β/ke 统一 + 金融情景 Bank RIM + 口径契约 + 金融运营 ROE 情景 + 约束式隐含求解器 + peer 来源溯源 + 同源证据去重 + 风险等级底线 + 估值完整性验收断言化)
- Telegram Bot: 85%
- 数据层: 93% (✅ 三源 sector/industry 补全链 FinanceDatabase/SEC-EDGAR-SIC/Wikidata + bottom-up 同业无杠杆 β + **分部收入层 (M-31, FMP `/stable` + 多 key 轮换 + Shape C)** + **Segment-level β (M-35)** + 分部→行业关键词表数据驱动补全；⏳ interest_to_revenue 特征补全)
- ML 分类器: 92% (✅ 置信度审计链 + Hybrid 暴露度 + 资产轻原型冲突扣减 + hybrid 阈值锁定 + 行业硬规则特征补全)
- 报告直观度: 94% (✅ Overview 首屏结论 + 数据对账 + 对账反向校验渲染 + 覆盖率门控 + 概率语言 + 单位经济学模型 + 金融情景 ke 口径渲染 + 口径契约驱动渲染 + 隐含驱动渲染 + peer 来源溯源/β 多窗口 + **ETR 口径分离（WACC 实际使用 vs Provider ETR）+ β 不确定性区间（wacc_beta_lo/hi）+ SOTP 分部明细表（Session #35）**)
- 测试覆盖率: 81% (✅ **436/436** passing，含 golden diff 回归套件（18 只 BASKET）+ 估值完整性验收断言套件 + 单位经济学用例 + 封顶审计 + 口径 invariant + 约束式求解器用例 + Phase 3 β/peer 溯源/同源去重用例 + SIC 桥接/三源解析器/bottom-up β 用例 + 分部收入（Shape C/多 key）与 Segment-level β 用例 + filing XBRL（含四态端到端）与 Taxonomy 路由门控用例 + **SOTP 三态契约 + Comparability Gate 用例（Session #35）**)
```

Current Pipeline Step

```
Pipeline Step: Coverage Model Family (Replacement NAV + Unit-econ EV/Sales) + Financial Caliber Unification + Internal Taxonomy (**participates in routing via cross-family gate + economic guard, M-32 DONE**) + Feature Completion: sector/industry via three-source chain DONE (bottom-up β awakened) + **Bottom-up β 三级业务身份筛选 DONE (M-34) + Segment-level β / 分部收入 DONE (M-31+M-35)** + **商业理解层 (M-37) + SEC filing-instance XBRL 证据 (M-38) 生产化接入 providers (M-39) DONE** → Remaining Feature Imputation (interest_to_revenue) → Label Correction → Optuna → v2.2 Release
```

Priority

- 🔴 Critical
- 🟠 High (当前: interest_to_revenue 特征补全 + 标签纠错 C-02 + 分类准确率 → 90%+)
- 🟡 Medium (当前: GICS/NAICS M-33 + 分部→行业关键词表精度 M-35；✅ 已完成: taxonomy 切换为参与路由 M-32（跨族冲突才覆盖 + 经济护栏）+ FMP_API_KEY 多 key 配置启用在线分部数据 + SEC filing-instance XBRL 生产化接入 providers（M-39）)
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

正在进行下一步优化：特征补全（interest/revenue）以把 sanity 准确率从 78.3% 推到 90%+，以及 Optuna 超参调优 / M-16 数据驱动复评。SOFI 三问修复 + NBIS 两轮方法论修复 + 内部标准 Taxonomy（M-32 参与路由）+ 三源 sector/industry 链 + bottom-up β（M-34/M-35）+ 商业理解层（M-37/M-38/M-39）均已落地并冻结，后续修改不破坏本次新增数据契约（一致性门控字段 / 估值可用性评分 / 概率结论字段 / 四态决策契约 / taxonomy 路由门控）。

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
| 035 | 🔴 JNJ 递归改进 Round 2：对账 P/E 口径语义（GAAP vs 调整后） | ✅ Done | 2026-11-03 | reconciliation.py 滚动 P/E 检查改为方向感知文案：供应商 P/E 低于价格/GAAP-EPS 隐含值 → 判为 non-GAAP/正常化口径差（非盈利不稳定）；高于 → 旧口径/摊薄股数或盈利下滑；JNJ 不再误报「盈利基数极不稳定」 |
| 036 | 🔴 JNJ 递归改进 Round 3：FCF Yield Gap 误报守卫 + Beta 展示一致 | ✅ Done | 2026-11-03 | risk.py FCF Yield Gap 新增守卫（正 FCF 且 FCF/净利≥0.8 且非高增长、收益率<4% → 降一级），JNJ 该旗标 High→Medium，总体风险 75→80、High 2→1；wacc.py 暴露 `BETA_WINSOR_LO/HI`；dashboard 市场区对越界 β 追加「原始值超出 CAPM 区间，WACC 采用截断值」标注 |
| 037 | 🔴 覆盖率瓶颈：新增 Replacement NAV 模型族（重资本高增长/亏损期） | ✅ Done | 2026-11-03 | 新建 `models/replacement_nav.py`（`equity = book_equity + net_ppe×(factor−1)`，net_ppe=Σcapex−ΣD&A；factor 默认 1.15 + 敏感性 1.00/1.10/1.15/1.25/1.40）；`config.py` 新增 `ModelName.REPLACEMENT_NAV`；`models/router.py`/`__init__.py` 注册；`classification/classifier.py` 动态入桶 `_is_replacement_nav_candidate`（capex/revenue≥0.30 + 负 FCF/亏损 + net_ppe>0，排除金融/REIT）；**NBIS 覆盖率 2/3 → 5/6** |
| 038 | 🔴 对账层反向校验供应商（偏差 >25% 自动改用内部推算值） | ✅ Done | 2026-11-03 | `data/reconciliation.py` 新增写侧 `apply_overrides()` + `OverrideRecord`/`OverrideLog`（审计链）+ `_OVERRIDE_FIELDS`/`_OVERRIDE_TOLERANCE=0.25` + 股数守卫（恒等式自洽→仅标注 / 破坏→按市值/价格反推）；`data/models.py` 新增 `reconciliation_overrides` 字段；`data/validator.py::_check_reconciliation` 接入；`reporting/dashboard.py::_data_section` 渲染「🩹 对账自动修正」 |
| 039 | 🔴 递归自改进工程化：golden report diff 可断言回归 | ✅ Done | 2026-11-03 | 新建 `tests/golden_report.py`（`BASKET` 9 只 + `run_pipeline`/`build_fingerprint`(19 字段)/`check_invariants`(5 类缺陷：覆盖恒等式/agreement 超封顶/负中位/β 三处一致/override 生效)）+ `tests/test_golden_report.py`（3 测试，`UPDATE_GOLDEN=1` 刷新基线）+ `tests/golden/report_fingerprints.json` |
| 040 | 🔴 Beta 全链路统一：单一 `resolve_effective_beta` 出口 | ✅ Done | 2026-11-03 | `valuation/wacc.py::resolve_effective_beta()` 统一 β 口径（wacc_breakdown → provider → fallback，`origin` 可审计）；市场区 / WACC / 风险旗标三处共用；由 golden `check_invariants()` 断言化 |
| 041 | 🎯 补 REIT（AMT）与 Energy（XOM）资产结构覆盖 | ✅ Done | 2026-11-03 | `data/providers.py` 新增 NBIS/AMT/XOM 合成 fixtures；`tests/conftest.py` 新增 nbis/amt/xom fixtures；`tests/test_asset_structure_coverage.py`（8 测试）断言 NBIS `n_solved≥3` + `Replacement NAV` 入 applicable、AMT `is_reit=True`、XOM `business_type=="Energy"` |
| 042 | 🔴 覆盖率瓶颈（第二条腿）：EV/Sales + 单位经济学模型族（重资本高增长/亏损期） | ✅ Done | 2026-11-03 | 新建 `models/unit_economics.py`（`UnitEconomicsSalesModel`）：`deployed_capital=Σcapex−ΣD&A`；`capacity_revenue=max(TTM_rev, deployed_capital×BENCHMARK_REVENUE_YIELD)` → `EV=capacity_revenue×MATURE_EV_SALES×ramp_discount`（`utilisation_gap=clamp(1−current_yield/benchmark_yield,0,1)`、`ramp_discount=(1+WACC)^−(RAMP_YEARS×utilisation_gap)`）；`BENCHMARK_REVENUE_YIELD=0.35`/`MATURE_EV_SALES=4.0`/`RAMP_YEARS=3.0` + 敏感性（yield 0.25/0.35/0.50 × ramp 2/3/5）；`config.py` 新增 `ModelName.UNIT_ECON_SALES`；`models/router.py`/`__init__.py` 注册；`classifier.py` 动态入桶 `_is_unit_economics_candidate()`（capex/revenue≥0.50 + 负 FCF/亏损 + net_ppe>0，排除金融/REIT）；**NBIS 覆盖率 5/6 → 6/7**（EV/Sales Unit Econ $27.02）；数据层无 GPU 稼动率/ARPU 明细 → 固定返回 APPROXIMATE 诚实标注 |
| 043 | 🔁 CRWV 递归自我改进 3 轮（CoreWeave — AI/Cloud neocloud 重资本建设期画像） | ✅ Done | 2026-11-03 | 以 CRWV 为新画像标的，重复「上一轮产出 → 缺陷 → 修码 → 下一轮」3 轮：**Round 1** 规则分类路径（离线/golden 走这条）缺「资产轻原型冲突 → AI/Cloud 重路由」→ 报告头 `MatureTech/SaaS` 与 peer 区 `AI/Cloud Infrastructure` 自相矛盾，`classifier.py` 补 ISSUE #1b（对齐 ml_classifier）+ `dashboard.py` hybrid 分支渲染重路由标注；**Round 2** 一句话结论内部矛盾（中位判显著高估 vs DCF 基准 $138.57 反判低估）→ `verdict_intuition.py` 新增「中位 vs 情景方向冲突」caveat（**命名矛盾、不做平均**），并修正自持的基期口径错误（base-relative vs price-relative）；**Round 3** `reverse_dcf.py` 成熟稳态推导的隐含营收 CAGR 仅存于 free-text note、结构化字段却显示 N/A → 写入 `breakdown["implied_revenue_cagr"]` + source 标记；`expectation.py` 透传 source；`dashboard.py` 标注 APPROXIMATE + 修正 `_gap_section` 方向文案 bug（原硬编码「高出」）；新增 CRWV 合成 fixture；回归证据 `_recursion_crwv_round0..3.txt`；pytest 90/90 |
| 044 | 🧪 **Phase 4：全量回归 + 边界/验收用例断言化 + golden 指纹扩展** | ✅ Done | 2026-11-13 | ① `tests/golden_report.py::BASKET` 由 9 → **18 只**（+GOOGL/AMZN/AVGO/ORCL/CRWV/UPS/KR/BAC/NU，覆盖 7 类 archetype；18 只 `check_invariants()` 缺陷空）；② `build_fingerprint()` 新增 5 字段区分「原始解算 / IQR 排除 / 参与聚合」样本口径（`n_independent_evidence`/`raw_solved_count`/`outlier_count`/`effective_aggregation_count`/`core_model_excluded`）；③ `check_invariants()` 覆盖率封顶门控改 `n_independent_evidence` + 新增 invariant 2b（核心模型被 IQR 排除却输出 Very Strong/Strong/Moderate → 缺陷）；④ 新建 `tests/test_phase4_integrity.py` 9 用例逐条锚定任务书验收标准；⑤ golden 基线重生成（原 9 只无漂移）；⑥ 修复 `test_providers_provenance.py`（BAC 撞 fixture → ZZZZ）；⑦ Ruff clean（顺带清理 3 处遗留）；pytest **240/240** |
| 045 | 🏛️ **内部标准 Taxonomy + 五维公司拆解 + 黄金法则** | ✅ Done | 2026-11-14 | ① 新建 `classification/taxonomy.py`（**99 节点**标准树：canonical key 点分层级 `tech.software.infra` + parent + archetype，族根为无点 key，`depth` 由 **parent 链**推导而非点计数；`IDENTITY_NODES`/`BUSINESS_MODEL` 枚举/`YAHOO_INDUSTRY_TO_NODE`/`YAHOO_SECTOR_TO_NODE` 映射）；② 五维模型：**①** Business Identity / **②** Business Model（SaaS Subscription / Licensing / Advertising / Transaction Fee / Hardware Sales / Cloud Usage …）/ **③** Revenue Composition（分部占比 + 数据日期，当前恒 unavailable）/ **④** Economic Profile（毛利率 / 经营利润率 / CapEx÷营收 / FCF Margin / Recurring / Debt）/ **⑤** External Classification（Yahoo Industry / GICS / NAICS / ML 标签，**原样保留不覆盖内部判断**）；③ **黄金法则**：`economic_identity_ceiling()` 重写——跨族经济学节点**一律不提升** Identity，同族兄弟冲突收敛至 **common ancestor**（绝不用经济学节点当作 Identity）；④ **冲突分级** `ConflictKind`（CONSISTENT/REFINEMENT/IDENTITY_WINS/ECONOMICS_ONLY/INSUFFICIENT）；⑤ `node_from_yahoo()` 两段式 **longest-key-wins**（industry 优先 → sector → sector→family 兜底，修复长 sector 短语压过具体 industry 的缺陷：AMZN `Consumer Cyclical`→`cons.ecommerce`、KR→`cs.retail`）；⑥ **additive shadow 接线**：`CompanyProfile` 新增 8 个 taxonomy 字段 + `attach_taxonomy_profile()`，**不改 `business_type`/`applicable_models`/路由**（golden 零漂移）；⑦ `data/models.py` 新增 `MarketData.description`，`data/providers.py` 采集 Yahoo `longBusinessSummary`；⑧ 新建 `tests/test_taxonomy.py`（**48 用例**）；修复 6 处真实缺陷（`commodit` typo 死词条 / `cs` 族根去父边 / depth 改 parent 链 / ceiling 重写 / node_from_yahoo 两段式 / logistics 词条）；pytest **288/288**（240 → 288），golden 零漂移 |
| 046 | 🔌 **三源 sector/industry 补全链 + bottom-up β 唤醒（H-03）** | ✅ Done | 2026-11-14 | ① 新建 `data/sic_map.py`：SEC **SIC → Yahoo taxonomy** 桥接——`SIC_TO_YAHOO`（约 180 条精确 4 位）+ `SIC2_TO_YAHOO`（约 68 条 2 位大类）+ `SIC_DESC_KEYWORDS`（约 130 条关键词，按具体→宽泛排序）；`map_sic_to_yahoo(sic, desc)` 解析顺序 = 精确 4 位 → 2 位大类 → 描述关键词（保证映射产出的 industry 100% 可被分类器硬规则消费）；② 新建 `data/industry_resolver.py`：`SectorIndustryResolver` **三源优先级链**（FinanceDatabase 离线 Yahoo 兼容 → SEC EDGAR `company_tickers.json`+`submissions/CIK*.json` 取 `sic`/`sicDescription` → Wikidata SPARQL P452 兜底），任一源缺失/断网返回 `{}` 继续下一层；类级 `_MEM` + 磁盘缓存（`.cache/`）+ `batch_get()`；SEC 请求带合规 `User-Agent`（`SEC_USER_AGENT` 可配）；③ 新建 `data/industry_beta.py`：`derive_industry_unlevered_beta()` **动态同业无杠杆 β（Hamada）**——同业列表（FinanceDatabase）→ 逐 peer β/D-E（yfinance）→ `β_u = β_L / (1 + (1−t)·(D/E))` → 取**中位**（抗离群）；`t=0.21`，**<3 家同业返回 None（绝不伪造）**；`BOTTOM_UP_BETA=0` 可关；缓存 key `{sector}|{industry}`；④ `data/providers.py::_fetch_quote_summary_simple` Layer-3 resolver 块后接入 bottom-up β，填充长期空置的 `MarketData.industry_beta` 审计槽位；⑤ `classification/classifier.py` `SECTOR_INDUSTRY_MAP` 补 `("asset management", BusinessType.BANK)`（修复 SIC "6726"/"67" → Asset Management 无法分类的唯一覆盖缺口）；⑥ 新建 3 个测试文件（`tests/test_sic_map.py` 24 用例含「每个映射产出必可分类」守卫 / `tests/test_industry_resolver.py` 三源链离线 monkeypatch / `tests/test_industry_beta.py` Hamada 数学 + 中位 + 不伪造下限 + 缓存），共 **45 用例**；pytest **288 → 333**，golden 零漂移；⑦ 在线实测：SEC 层 **10/10 精确命中**（AAPL→Computer Hardware、NVDA→Semiconductors(3674)、JPM→Banks-Diversified(6021)、PLD→REIT-Diversified(6798)、XOM→Oil&Gas Refining(2911)、MSFT→Software-App(7372)、BRK-B→Insurance-P&C(6331)、KR→Grocery Stores(5411)、AMZN→Internet Retail(5961)、BLK→Capital Markets(6211)）；layer-2 硬规则覆盖 **18/23 = 78.3%**（此前被 401 阻断）；Semiconductors 同业 bottom-up 无杠杆 β = **1.2447** |
| 047 | 🎯 **Bottom-up β 升级「业务身份三级筛选 + 完整 β 链」接入 CAPM（M-34）** | ✅ Done | 2026-11-14 | ① **重写 `data/industry_beta.py`**：裸 `get_companies_by_industry(industry)` → `get_companies_by_business_identity(sub_industry, business_model, economic_profile, *, sector, industry_lister, neighbor_lister, model_resolver, profile_resolver, min_peers, use_neighbors)`——**L1** 同子行业(+商业模式模型过滤，无 resolver 则显式声明未过滤) / **L2** 相邻行业(+`_profile_matches` 经济形状过滤：capex_heavy/loss_making/asset_light，缺失不算不匹配) / **L3** 空集（走基准）；② 完整链 `PeerBeta` → `_unlever`(Hamada) → Median → `_cash_adjust`(`β_u/(1−Cash/Firm)`，Cash/Firm 上限 0.90) → `_relever`(target D/E)；`IndustryBetaResult`（`note()` + `to_chain()` 审计快照）；③ **L3 Damodaran 基准**：新建 `data/damodaran_beta.json`（**Jan 2026**，100 行业，`unlevered_beta` + `unlevered_beta_cash_adjusted`）+ `_DAMODARAN_ALIASES`（Yahoo industry → Damodaran 名 ~80 条）+ `_normalize_industry()`（en/em-dash → hyphen）+ `_damodaran_lookup()`（未匹配/文件缺失 → **None，绝不伪造**）；④ `derive_bottom_up_beta(...)` 三级筛选 + 链式推导 + 缓存（key 含 `business_model`，仅缓存 peer 相关部分，target relever 现算）+ `BOTTOM_UP_BETA=0` 关闭 + `offline`/`use_neighbors`/`use_benchmark`/`benchmark_path` 可注入；⑤ `data/models.py` `MarketData` 新增 `bottom_up_beta`（CAPM 消费的 target-relevered）+ `bottom_up_beta_chain`（链快照），`industry_beta` 保留为原始 peer-median unlevered；⑥ `valuation/wacc.py::calculate()` β 段改**三段优先级**（bottom-up 优先、缺失回退回归 β、都无则 default，仍 winsorize [0.30,2.50]）+ `WaccBreakdown` 加 `beta_bottom_up`/`beta_bottom_up_note` + `beta_transparency_note()` 展示链；⑦ `resolve_effective_beta()` **`clamped` 语义修正**（仅指原始回归 β 越界，避免 bottom-up 选取误报截断）；⑧ `data/providers.py` 接线（推断 BusinessModel、target D/E=总债务/市值、tax=etr_snapshot）+ 删除旧 Layer-3 β 块；`analysis/risk.py`/`reporting/dashboard.py` 文案对齐；⑨ `tests/test_industry_beta.py` **12 → 32 用例**（cash-adjust/relever 数学、三级筛选、Damodaran alias/unmatched、完整链、L3 fallback、to_chain、PeerBeta 输入、CAPM 优先级）；pytest **333 → 353**，golden **零漂移**（离线 `bottom_up_beta=None` → 回退回归 β），新模块/新测试 Ruff clean |
| 048 | 🧠 **商业理解层六模块映射 + 四态决策契约 + Identity Resolution（Session #28）** | ✅ Done | 2026-11-14 | ① **四态决策契约** `classification/taxonomy.py` 新增 `DecisionStatus`（CONFIRMED/PROBABLE/AMBIGUOUS/INSUFFICIENT_DATA）+ `decide_status(conflict_kind, identity_source, *, ml_confidence)`（确定性映射：INSUFFICIENT→INSUFFICIENT_DATA / IDENTITY_WINS→AMBIGUOUS / ECONOMICS_ONLY→PROBABLE 当 `ml_confidence≥_ECONOMICS_ONLY_MIN_CONF=0.55` 否则 AMBIGUOUS / REFINEMENT→PROBABLE / CONSISTENT+结构化外部事实→CONFIRMED 仅自由文本→PROBABLE）+ `_DECISION_LABELS`；`BusinessTaxonomyProfile` +`decision_status`；`audit_lines()` 追加「◆ 决策状态」；`attach_taxonomy_profile()` 写 `profile.taxonomy_decision_status`；② **Identity Resolution 层**（新建 `data/identity_resolver.py`）：`IdentityResolver.resolve()→ResolvedIdentity`（cik/sic/sic_description/figi/sector/industry + sources + `provenance()`）——Layer A 复用在位 SEC 链（`data/industry_resolver.py` 新增 `resolve_identity()`）+ Layer B OpenFIGI（`OPENFIGI_API_KEY` 存在才调用，offline 跳过），缺失**一律 None 绝不伪造**；③ **Business Evidence 收集器**（新建 `classification/business_intelligence.py`）：`extract_business_evidence(data)→BusinessEvidence`（description + revenue_segments(label,pct) + `*_source` + provenance），缺失**显式标注**；④ `data/models.py` `CompanyProfile` +`taxonomy_decision_status`；⑤ 三个测试文件（`TestDecisionContract` 7 + `test_identity_resolver.py` 5 + `test_business_intelligence.py` 4）；⑥ 六模块映射（原位扩展，既有逻辑零迁移）：`industry_taxonomy`=taxonomy.py / `classification_resolver`=reconcile_identity+decide_status / `economic_profile`=derive_economic_profile / `peer_selection`=get_companies_by_business_identity；pytest **382 → 398**，golden **零漂移** |
| 050 | 🧭 **M-39：SEC filing-instance XBRL 生产化接入 providers 主链 + M-32：Taxonomy 参与路由（Session #30）** | ✅ Done | 2026-11-14 | ① **阶段 A（M-39）**：`data/segment_revenue.py::resolve_segments(ticker, *, client, offline, fmp_cache_path, filing_cache_path, identity_resolver)` 为**生产默认源链** —— Layer 1 FMP `revenue-product-segmentation`（需 key）→ Layer 2 SEC 10-K/20-F **filing-instance XBRL**（免 key、权威；`FilingBusinessExtractor` **惰性 import** 避免与 `filing_evidence` 循环），两层皆空 → `[]`（绝不伪造）；`data/providers.py` 改调源链 → FMP 无 key / key 失效 / 额度耗尽 / ticker 未覆盖时**自动降级**到 SEC 一手分部；仍为 shadow 数据填充（不改 `business_type`/路由）；② **阶段 B（M-32）**：`classification/taxonomy.py` 新增 `TAXONOMY_ROUTING_STATUSES={CONFIRMED}` + `ARCHETYPE_FAMILIES`（由 `IDENTITY_NODES` 树 `_archetype_family_index()` 推导，archetype↔node tree 不漂移）+ `same_identity_family()` + `taxonomy_routing_override(internal_bt, taxonomy_key, decision_status, *, guard_blocked=False)`（三道 gating：① CONFIRMED；② canonical 身份与**内部身份判定 `best_bt`** **跨 identity family** 冲突；③ 经济护栏优先）；`attach_taxonomy_profile(..., tp=...)` 复用同一 profile；③ **双路径接线**：`classifier.py`（规则路径，`_model_applicability()` 前构建 `_taxonomy`）与 `ml_classifier.py`（ML 路径，economics = **raw ML top-1** 预 sector 硬规则）对称 gate，`business_type=_routed_business_type.value`；④ `classifier.py` 新增 `_asset_light_guard_blocked()` staticmethod（复用 `ASSET_LIGHT_TYPES`/`ASSET_LIGHT_CONFLICT_CAPEX_RATIO`）；⑤ `tests/test_taxonomy.py` 新增 `TestTaxonomyRoutingGate`（12 用例）+ tension basket（ORCL/NBIS/CRWV：`taxonomy_identity_key="tech.software.infra"` 但 `business_type="MatureTech"`）；**关键纠错**：gate 对比 `best_bt` 而非 `routing_bt`（后者是 Phase 1.3 保守估值路由，GOOGL 取 `TELECOM` → 若对比会跨族误覆盖）；pytest **413 → 429**，golden **零漂移（未重生成）** |
| 051 | 🔬 **50 只跨行业蓝筹全量验证 + Reverse DCF 递归自我改进 Round 1：结构化 bound（Session #31）** | ✅ Done | 2026-11-14 | ① 用户给出 50 只跨行业蓝筹（NVDA…VICI）验证五问（分类准确性 / 模型分配 / 行业估值方法 / 特殊情况 / Reverse DCF）；② 新建 `_batch_eval.py`（50 标的离线全量审计 harness → `_batch_eval_<label>.json`）+ `_audit_summary.py`（紧凑打印 Q1–Q5）；③ `models/reverse_dcf.py::calculate` 新增 **结构化 bound**（第 232–253 行）：市场价超出业务类型 sanctioned growth band 时，`binding=above_band_ceiling / below_band_floor` + `implied_revenue_cagr_bound={kind,value,ev_at_bound}`，诚实输出「≥ 上限 / ≤ 下限」而非伪造点估（`bridge_broken` 时才启用 normalized 救援）；④ Round 1 结果：50/50 分类、0 路由违规、0 缺陷，22 量化 / 19 bound-only / 0 未量化 |
| 052 | 🔬 **逆 DCF Round 2：bound 透传与报告镜像 + 风险旗标审计（Session #32）** | ✅ Done | 2026-11-14 | ① **缺陷 #1（自相矛盾）**：`_implied_section` 已陈述「≥ 上限（非点估）」但 `_gap_section` 对同一标的打印 N/A → `analysis/expectation.py::ExpectationGap` 新增 `implied_revenue_cagr_bound` / `implied_revenue_cagr_is_bound` 两字段并在 `gap_analysis()` 透传；`reporting/dashboard.py::_gap_section` 镜像 bound 措辞（`above_band_ceiling`→「≥ X%（区间上限，非点估）」，`below_band_floor`→「≤ X%…」）；PG 端到端验证两区一致；② **缺陷 #2（CV 假阳性）**：`config.py` `RISK_THRESHOLDS[RiskType.GROWTH]` 增绝对离散度门控，`analysis/risk.py::_growth_risk()` 加 σ 门（PG High→Low、KR 同步）；③ `_batch_eval.py` 增记 `risk_severity`/`risk_flags`/`risk_severity_floor`/`risk_severity_by_score`/`beta_origin`；`_audit_summary.py` 新增 Q4b 风险底线区块；④ 新建诊断脚本 `_diag_risk.py`（增长序列 + σ/CV）、`_audit_risk_detail.py`（Growth Risk 证据）；⑤ pytest **429 passed**（golden 更新一次） |
| 053 | 🔬 **逆 DCF Round 3：Growth Risk 下行离散度化 + 隐含 WACC 以 Rf 为下限（Session #33）** | ✅ Done | 2026-11-14 | ① **缺陷 #3（Growth Risk 假 High，Round 2 σ 门不足）**：σ 门未能消除 SO（σ≈10.5pp 恰越 10pp 阈）、PLD/VICI（单调收购爬坡 σ≈14–16pp 被当「波动风险」）→ `analysis/risk.py::_growth_risk()` 改用 **下行离散度**（负增长点的 RMS，相对 0）+ `config.py` 阈值 `growth_dd_medium=0.05` / `growth_dd_high=0.10`（替换 `growth_vol_*`）；结果：SO High→Medium、PLD/VICI/CEG/AMT Growth Risk 消失，仅真实收缩标的（XOM/CVX/COP/NUE/PFE/MRNA 等）保留；② **缺陷 #4（隐含 WACC 低于无风险利率）**：`models/dcf.py` 新增 `_estimate_wacc_breakdown()`（暴露 WACC 实际使用的 Rf，单一真理源）；`models/reverse_dcf.py` 将 Rf 透传 `_implied_expectations`，`wacc_lo = max(config_lo, tg+spread, Rf)` → DUK/SO/CEG 的 sub-Rf（2.3%/2.7%/3.3%）点估改为 `NO_SOLUTION_IN_RANGE`（命名 Rf 约束），输出 `implied_wacc_floor_rf` 审计字段；③ 验证：*无任何* `implied_wacc < 0.045`（Rf 门生效）；④ pytest **429 passed**，golden 因行为修正二次重生成（全部为 Growth Risk 移除/降级，无新增） |

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
| MEDIUM | 配置 `FMP_API_KEY` 启用在线分部收入数据 (M-31)；无 key → 自动回退 SEC filing-instance XBRL (M-39)，再空 → 回退公司级 β | M-31 / M-39 | Agent |
| MEDIUM | 分部→行业关键词表补全 (`_SEGMENT_INDUSTRY_KEYWORDS`，随分部 label 语料驱动，现覆盖 107/172 label) (M-35) | M-35 | Agent |
| MEDIUM | M-33：外部标签补齐 GICS / NAICS（当前仅 Yahoo sector/industry + SEC SIC + ML 标签） | M-37 | Agent |
| LOW | ~~SEC 一手分部数据 (整包 Financial Statement Data Sets / filing-instance XBRL；勿再试 companyfacts)~~ | M-31 | ✅ **DONE** (M-38 + M-39，filing-instance XBRL 已为生产默认回退源；勿再试 `companyfacts`) |
| LOW | 报告展示「失败模型清单 + 失败原因」与「保留 P/E/EV-EBITDA 时的中位值对照」 | 024 | Agent |
| LOW | 反向 DCF 升级为三变量求解 (营收 CAGR + 稳态 FCF margin + capex intensity) | 029 | Agent |
| LOW | 部署到 Cloudflare / Render | 核心完成 | Agent |

---

# 6. Next Immediate Task

The NEXT AI Agent should start here.

Task:

```
跨行业阈值校准（M-67）+ SBC 归一化下沉 FCF 主链（M-69）（Session #40）已收尾（AGENT.md v4.14 / ADR-053）。
交付：① M-67 新建 `analysis/threshold_calibration.py`（运行时单一来源）——按业务原型 FCF-margin 波动分档（stable<0.03 / moderate 0.03–0.06 / volatile≥0.06，带宽随波动放大 2/4/1.75× → 3/5/2× → 4/7/2.5×）；β 同业地板按池广度分档（宽池 5 / 窄池 3 / 未知 4）；两来源校准（离线篮子 σ 冻结于 CALIBRATION_EVIDENCE + 领域先验），未知原型回退 moderate 带不静默重判；`divergence.py::_fcf_margin_check()` 审计行 + `wacc.py::_bottom_up_reliability_label()` 惰性接线；
② M-69 `data/fcf_utils.py` 双函数出口（resolve_ttm_fcf raw primitive + resolve_ttm_fcf_normalized value producer，SBC 恰好一次，生效加 +sbc_normalized，缺失返 missing 不臆造零）；`reverse_dcf.py` / `multiples.py::FCF Yield` 改消费共享出口；
③ 修复 `wacc.py` 循环导入（惰性 import）；④ ID 诚实性（M-68 被占用 → SBC 下沉正名 M-69）。
验证：pytest **522 passed**；ruff All passed；golden **零漂移**（未重生成基线）。
未做（诚实记录）：分档 cut point（0.03/0.06）与带宽为文档化先验，篮子仅 19 名、n 偏小 → 扩充样本后重推；窄池集合 {NEOBANK, FINTECH, CONGLOMERATE} 硬编码，新增原型需同步；新 FCF 消费者必须经 `resolve_ttm_fcf_normalized()`（无强制门禁，靠约定 + 测试）；MC 截断（**M-68**）仍为 TODO（仅透明化，未改截断正态/重参数化抽样）。

────────────────────────────────────────
以下为上一轮（Session #35）记录，已完成：

用户代码审查 4 项 P1 修复（Session #35）已收尾（AGENT.md v4.9 / ADR-050 / M-49–M-52）。
交付：① SOTP 三态状态机（SOLVED / APPROXIMATE / INSUFFICIENT）——ML 暴露度拆分不再伪装独立分部估值证据（无真实分部财务 → display_only，剔除共识）+ segments_detail 明细；
② 多窗口 β 稳定性参与估计（Blume-style shrinkage 向 β=1.0 收缩，不取平均）+ Raw/Selected/Adjusted β 三分离 + β 不确定性传导至 WACC 区间（wacc_beta_lo/hi）；
③ 报告 ETR 口径分离（市场快照以 WACC 实际使用 ETR 为主，供应商值另标 Provider ETR）；
④ Valuation Comparability Gate（7 维冲突检测，不兼容模型可展示但不进入共识中位数；未声明口径 ≠ 冲突，不排除）。
验证：pytest **436 passed**；golden 因 SOTP→display_only **有意重生成一次**（PLD/NOW/NBIS/CRWV/NU：n_solved −1、n_display_only +1、n_independent_evidence −1，逐条核对为预期）。
未做（诚实记录）：`CANONICAL_KEY_WACC_RANGES` 仍仅覆盖 util 族 + 综合能源（其余回落关键词表/默认）；
FMP 在线分部需 key（真实分部数据接入后 SOTP 方可 SOLVED）；M-16/C-02（真实标注 → 90%+）仍为唯一真实 BLOCKER；
SOTP 独立 Peer Multiple 目前仍主要依赖行业默认表，真实分部级 peer 倍数是后续方向。

────────────────────────────────────────
以下为上一轮（Session #34）记录，已完成：

用户代码审查 4 项 P0 修复（Session #34）已收尾（AGENT.md v4.8 / ADR-049 / M-45–M-48）。
交付：① 行业 WACC 区间改读 Taxonomy canonical key（`CANONICAL_KEY_WACC_RANGES` + 破折号归一化 + 四级优先级）；
② `_effective_tax_rate()` 非重叠期间（`tax_period_basis ∈ {ttm, fyN, default}`）；
③ `ShareCountBasis` 股数口径契约 + 共识层可比性校验（偏差 >10% 剔除，EV/Equity Value 独立保留）；
④ `FCF Yield Gap` 非对称方向感知（正 FCF 高收益率不判风险，负 FCF 按恶化幅度/持续性）。
验证：pytest **429 passed**；golden 因 P0 行为修正**有意重生成一次**（差异逐条核对为预期修正）。

用户 50 只跨行业蓝筹验证 + Reverse DCF 递归自我改进 3 轮（Session #31 / #32 / #33）已收尾。
标的：NVDA,MSFT,AVGO,ORCL,CRM,AMD,GOOGL,META,NFLX,VZ,AMZN,TSLA,MCD,NKE,BKNG,PG,KO,WMT,COST,
XOM,CVX,SLB,COP,LIN,FCX,NUE,CAT,GE,UPS,BA,UNP,LLY,JNJ,PFE,ISRG,MRNA,JPM,BAC,GS,V,CB,BRK-B,
NEE,DUK,CEG,SO,PLD,O,AMT,VICI（五问：分类准确性 / 模型分配 / 行业估值方法 / 特殊情况 / Reverse DCF）。
最终结论：**50/50 分类、0 路由违规、0 缺陷；22 量化点估 / 19 结构化 bound / 0 未量化**。

Round 1（Session #31）— 结构化 bound：
- `models/reverse_dcf.py::calculate` 在市场价超出业务类型 sanctioned growth band 时输出
  `implied_revenue_cagr_bound={kind(above_band_ceiling|below_band_floor), value, ev_at_bound}`
  —— 诚实边界「≥ 上限 / ≤ 下限」，绝不伪造点估；仅 `bridge_broken`（TTM FCF≤0 或 TV 抑制）
  时才启用 normalized 成熟稳态救援。
- 新建 50 标的审计 harness `_batch_eval.py`（→ `_batch_eval_<label>.json`）+ `_audit_summary.py`。

Round 2（Session #32）— bound 透传 + 报告镜像：
- 缺陷 #1：`_implied_section` 陈述「≥ 上限」但 `_gap_section` 打印 N/A（自相矛盾）→
  `analysis/expectation.py::ExpectationGap` 新增 `implied_revenue_cagr_bound`/`_is_bound` 并透传；
  `reporting/dashboard.py::_gap_section` 镜像 bound 措辞。PG 端到端两区一致。
- 缺陷 #2：CV=σ/|μ| 在 μ→0 时爆炸（PG、KR 假 High）→ 初版加绝对离散度 σ 门。
- `_batch_eval.py` 增记 risk flag；`_audit_summary.py` 新增 Q4b 风险底线区块；新建
  `_diag_risk.py` / `_audit_risk_detail.py`。

Round 3（Session #33）— 下行离散度 + Rf 下限：
- 缺陷 #3：σ 门不足（SO σ≈10.5pp 恰越阈；PLD/VICI 单调收购爬坡被当「波动风险」）→
  `analysis/risk.py::_growth_risk()` 改用 **下行离散度**（`dd = RMS(min(growth,0))`），
  `config.py` 阈值 `growth_dd_medium=0.05` / `growth_dd_high=0.10`。SO High→Medium，
  PLD/VICI/CEG/AMT 的 Growth Risk 消失；仅真实收缩标的保留。
- 缺陷 #4：隐含 WACC 低于无风险利率（DUK 2.3%/SO 2.7%/CEG 3.3%）→ `models/dcf.py` 新增
  `_estimate_wacc_breakdown()`（Rf 单一真理源）；`models/reverse_dcf.py` 将 Rf 透传
  `_implied_expectations`，`wacc_lo = max(config_lo, tg+spread, Rf)` → sub-Rf 点估改为
  `NO_SOLUTION_IN_RANGE`（命名 Rf 约束）+ `implied_wacc_floor_rf` 审计字段。验证：无任何
  `implied_wacc < 0.045`。
- 验证：pytest **429 passed**；golden 因行为修正二次重生成（差异全部为 Growth Risk 移除/
  降级，无新增）。

后续（未做，诚实记录）：FMP 在线分部（需 key）、M-33（GICS/NAICS）、分部 label→行业映射补全、
M-16/C-02（真实标注 → 分类准确率 90%+，唯一真实 BLOCKER）。Round 3 剩余可选项：隐含
FCF 利润率 / 隐含终值增长率在部分标的仍为 `NO_SOLUTION_IN_RANGE`，可视需要给出 bound 措辞。

---
以下为 Session #22–#30 的交付记录（历史，未变）：

「三源 sector/industry 补全链 + bottom-up β 唤醒」（Session #24 / H-03）、
「Bottom-up β 升级『业务身份三级筛选 + 完整 β 链』接入 CAPM」（Session #25 / M-34）、
「分部收入数据层 + Segment-level β」（Session #26 / M-31 + M-35）、
「M-35 收尾：FMP 多 key / `/stable` 端点 / Shape C / 关键词表补全」（Session #27 / M-36）、
「商业理解层六模块映射 + 四态决策契约 + Identity Resolution」（Session #28 / M-37）、
「SEC 10-K / 20-F filing-instance XBRL 业务证据抽取 + 四态决策端到端测试」（Session #29 / M-38）、
「SEC filing-instance XBRL 生产化接入 providers 主链」（Session #30 / M-39）与
「Taxonomy 参与路由（跨族冲突才覆盖 + 经济护栏）」（Session #30 / M-32）均已收尾。
Taxonomy 已由 **additive shadow 层切换为参与路由**（`taxonomy_routing_override()`）：仅当
四态决策 = `CONFIRMED` **且** canonical 身份与内部身份判定 `best_bt` **跨 identity family 冲突**
**且** 经济护栏未拦截（`guard_blocked=False`）时，才覆盖 `business_type`/估值路由；否则保留内部
路由。同族差异（如 `MatureTech` vs `SaaS` 同属 `tech` 族）归经济驱动分类器所有，不覆盖。
四态决策契约（`DecisionStatus`）现为路由门控输入（`TAXONOMY_ROUTING_STATUSES={CONFIRMED}`）+ 审计字段。
**golden 零漂移（未重生成）** —— 「跨族才覆盖」结构性排除了同族差异导致的漂移风险。

Session #30（M-39 生产化 + M-32 参与路由）已交付：
- 阶段 A（M-39）：`data/segment_revenue.py::resolve_segments(ticker)` 为**生产默认源链** ——
  Layer 1 FMP `revenue-product-segmentation`（需 key）→ Layer 2 SEC 10-K/20-F **filing-instance
  XBRL**（免 key；`FilingBusinessExtractor` *惰性 import* 避免与 `filing_evidence` 循环），
  两层皆空 → `[]`（绝不伪造）；`data/providers.py` 改调源链 → FMP 无 key / key 失效 /
  额度耗尽 / ticker 未覆盖时自动降级到 SEC 一手分部；仍为 shadow 数据填充（不改路由）。
- 阶段 B（M-32）：`classification/taxonomy.py` 新增 `TAXONOMY_ROUTING_STATUSES`（`{CONFIRMED}`）
  + `ARCHETYPE_FAMILIES`（由 `IDENTITY_NODES` 树 `_archetype_family_index()` 推导）+
  `same_identity_family()` + `taxonomy_routing_override()`；`attach_taxonomy_profile(..., tp=...)`
  复用同一 profile；`classifier.py`（规则路径）与 `ml_classifier.py`（ML 路径）对称 gate。
  **关键纠错**：gate 对比内部身份判定 `best_bt` 而非 `routing_bt`（后者是 Phase 1.3 ambiguous
  时的保守估值路由，GOOGL 取 `TELECOM` → 若对比会跨族误覆盖、golden 漂移）。
- `tests/test_taxonomy.py` 新增 `TestTaxonomyRoutingGate`（12 用例）+ tension basket
  （ORCL/NBIS/CRWV：`taxonomy_identity_key="tech.software.infra"` 但 `business_type="MatureTech"`）。
- 验证：pytest **413 → 429 passed**；golden 指纹 **零漂移（未重生成）**；golden 基线自 Session #22 起未变。

Session #29（M-38，一手 filing XBRL）已交付：
- `data/filing_evidence.py`（新建）：`FilingBusinessExtractor.get_segments()` 走
  CIK → `submissions/CIK{cik}.json`（`filings.recent` newest first）→ 首个 `10-K`/`20-F`
  → filing `index.json` 优选 `*_htm.xml` 实例；`parse_segment_revenue(xml)` **纯函数**仅取
  带 segment 轴的事实（`StatementBusinessSegmentsAxis` > `ProductOrServiceAxis` >
  ifrs `SegmentsAxis` > `StatementGeographicalAxis`，单轴）、排除合并总额、取最新期间、
  忽略 instant context；返回 `segment_revenue.Segment` + `source="sec-xbrl"`（drop-in 兼容
  `to_revenue_composition`）；`_MEM` + `.cache/filing_evidence.json` + `offline` 零网络；
  无 CIK/实例/解析失败 → `[]`（绝不伪造）。
- `tests/test_filing_evidence.py`（新建，9 用例）+ `tests/test_taxonomy.py::TestDecisionContractEndToEnd`
  （6 用例，真实 builder/classifier 全链路锁定四态 shadow 接线）。

Session #28（商业理解层）已交付：
- `classification/taxonomy.py`：`DecisionStatus`（CONFIRMED/PROBABLE/AMBIGUOUS/INSUFFICIENT_DATA）
  + `decide_status()` 确定性映射；`BusinessTaxonomyProfile.decision_status` → `CompanyProfile.taxonomy_decision_status`。
- `data/identity_resolver.py`（新建）：`IdentityResolver.resolve()` → CIK/SIC/FIGI（Layer A SEC 链复用
  `SectorIndustryResolver.resolve_identity()`，Layer B OpenFIGI 需 key）；缺失一律 None，绝不伪造。
- `classification/business_intelligence.py`（新建）：`extract_business_evidence()` → 业务描述 + 分部收入
  + provenance；证据缺失显式标注（诚实「数据不足」）。
- 六模块映射（原位扩展，既有逻辑零迁移）：`industry_taxonomy`=taxonomy.py /
  `classification_resolver`=reconcile_identity+decide_status / `economic_profile`=derive_economic_profile /
  `peer_selection`=get_companies_by_business_identity。

M-31 + M-35（Session #26）已交付：
- `data/segment_revenue.py`：FMP `/revenue-product-segmentation`（v4 flat / v3 legacy）为主源，
  无 `FMP_API_KEY` → `[]`（绝不伪造）；类级 `_MEM` + 磁盘缓存；`to_revenue_composition()`（→ taxonomy ③）
  + `segment_weights(by="value")`（营业利润占比优先、缺失回退收入）。
- `data/industry_beta.py::derive_segment_level_beta()`：逐分部 label → 行业（`_SEGMENT_INDUSTRY_KEYWORDS`）
  → 复用 M-34 三级筛选求分部 β_u → 按业务价值权重整合 → cash-adjust → target-relever；
  `level=0` / `source="segment-weighted"` / `segments` 审计；门控 `min_segments=2` + 覆盖 `≥0.60`。
- `derive_bottom_up_beta(segments=...)` 优先分支（不足 → 透明回退公司级）；
  `FinancialData` +`revenue_composition`；`classification/taxonomy.py` 消费端读取；`data/providers.py` 接线。

关键纠错（勿重犯）：
- **SEC `companyfacts` JSON 不含分部（dimensional）数据**（AAPL `Axis`/`ProductOrService`/
  `StatementBusinessSegments` 计数均为 0）→ M-31 以 FMP 为主源。**Session #29（M-38）已补齐**：
  一手分部改走 **filing-instance XBRL**（`data/filing_evidence.py` 解析 10-K/20-F 的 `*_htm.xml` 实例），
  覆盖 FMP 无 key 时的缺口；仅在需要全量历史时才考虑整包 Financial Statement Data Sets。
  **仍不要试 `companyfacts`**。

剩余可跟进项（均非本次范围，按优先级）：
1. ✅ **已交付（Session #30 / M-32）**：taxonomy 已切换为「参与路由」（跨族冲突才覆盖 +
   经济护栏，四态决策契约 `DecisionStatus` 同步纳入门控）——**golden 零漂移（未重生成）**，
   结构性排除同族差异漂移。
2. ✅ **已交付（Session #30 / M-39）**：`data/segment_revenue.py::resolve_segments()` 已把
   SEC filing-instance XBRL 接入 `data/providers.py` 主链，FMP 缺 key / 失效 / 额度耗尽 /
   ticker 未覆盖时自动回退（仍 shadow 数据填充）；**余项**：随分部 label 语料补全
   `_SEGMENT_INDUSTRY_KEYWORDS`（M-35 精度，现覆盖 107/172 label）。
3. 配 `FMP_API_KEY` 启用在线分部数据（FMP 与 SEC XBRL 双源互补，FMP 为主、SEC 为回退）。
4. M-33：外部标签补齐 GICS / NAICS（当前仅 Yahoo sector/industry + SEC SIC + ML 标签）。
5. M-16 / C-02：hybrid 阈值复评 + 人工标注 1001 行 label → 真实训练源 → 重训 → AB 测试
   （真正把分类准确率推高到 90%+ 的路径）。
6. M-22：隐含驱动（OM/FCF Margin/WACC/TG）纳入 golden 指纹（需一次有意漂移审阅）
7. Pyright：安装后对本仓库补类型检查（当前「不可用」，非代码缺陷）
8. M-13 / M-18：WACC 行业区间随原型重路由收口 / 金融"数据不足"字段语义
```

Expected Output

```
- 上述任一项的实施 + 对应测试
- 若触及 golden 基线，先逐字段审阅再 UPDATE_GOLDEN=1
- Taxonomy 相关改动须保持「五维分离 + 黄金法则」不变式（economics 不得跨族决定 identity）
- 三源补全链改动须保持「绝不伪造」不变式（缺失即 None/{}，不填猜测值）
- 分部相关改动须保持「绝不伪造 + 透明回退」不变式（无 key/无法解析 → []/None，回退公司级 β）
```

Files to modify

```
data\segment_revenue.py / data\filing_evidence.py / data\industry_beta.py / data\providers.py / data\models.py
classification\taxonomy.py / valuation\wacc.py / reporting\dashboard.py
tests\test_segment_revenue.py / tests\test_filing_evidence.py / tests\test_industry_beta.py / tests\test_taxonomy.py
AGENT.md / CHANGELOG.md / TODO.md / ROADMAP.md / DECISIONS.md
```

Estimated Difficulty

- Easy
- ✅ Medium（数据源接入属跨模块）
- Hard

---

# 6b. Session #19–#30 已完成（DO NOT REPEAT）

```
✅ Phase 1（早前 Session）：报告百分比方向自审（reporting/math_audit.py）、
   模型分歧诊断（analysis/divergence.py）、风险等级底线（Risk Floor）、
   分类引擎 Business Identity vs Economics（classification/classifier.py）
✅ Session #19：Rf 单一真源 + Terminal Growth 三档语义 + Weighted Median 修复
✅ Session #20（Phase 2）：MC 双模式 + 去人为利润率地板 + 路径锚点对账 +
   经营/折现情景拆分 + 报告透明化 + Wipeout 用词（详见 #18 Change Log）
✅ Session #21（Phase 3）：WACC β 多窗口敏感性（2Y 周/3Y 月/5Y 月）+ bottom-up 槽位 +
   peer 倍数来源溯源标签（EXACT_INDUSTRY/SECTOR_FALLBACK/BUSINESS_TYPE_FALLBACK/APPROXIMATE）
   + peer 样本数 + 同源证据去重（model_family 门控，详见 #18 Change Log）
✅ Session #22（Phase 4）：全量回归 + 回归 universe 扩展至 18 只 + golden 指纹扩展
   （区分原始解算 / IQR 排除 / 参与聚合）+ 边界/验收用例断言化（9 用例）+ Ruff clean
   （详见 #18 Change Log）
✅ Session #23（Taxonomy）：内部标准 Taxonomy（99 节点树）+ 五维公司拆解
   （Identity/Model/RevenueComposition/Economics/External）+ 黄金法则
   （economics 只能族内细化 identity、同族兄弟收敛 common ancestor）+ 冲突分级
   ConflictKind + node_from_yahoo 两段式 longest-key-wins + additive shadow 接线
   （不改路由/golden 零漂移）+ test_taxonomy.py 48 用例（详见 #18 Change Log）
✅ Session #24（数据源）：三源 sector/industry 补全链（FinanceDatabase → SEC EDGAR SIC
   → Wikidata P452）+ SIC→Yahoo 桥接 + bottom-up 同业无杠杆 β 唤醒（industry_beta 审计槽）
   + 45 用例；pytest 288 → 333；golden 零漂移（详见 #18 Change Log）
✅ Session #25（M-34）：bottom-up β 升级「业务身份三级筛选 + 完整 β 链」（Peer Levered →
   Hamada Unlevered → Median → Cash-adjusted → Target Relevered）+ L3 Damodaran 快照
   （data/damodaran_beta.json，未覆盖→None）+ 接入 CAPM 三段优先级（bottom-up 优先 /
   缺失回退回归 β）+ clamped 语义修正；+20 用例；pytest 333 → 353；golden 零漂移
   （详见 #18 Change Log / ADR-041）
✅ Session #26（M-31 + M-35）：分部收入数据层 + Segment-level β
   （data/segment_revenue.py：FMP 分部收入为主源，无 key → []，磁盘缓存，to_revenue_composition
   + segment_weights(by="value")；derive_segment_level_beta()：分部 label→行业→三级筛选 β_u→
   按业务价值权重整合→cash-adjust→relever，level=0，门控 <2 分部/覆盖 <60% → 回退公司级；
   derive_bottom_up_beta(segments=...) 优先分支；FinancialData +revenue_composition；providers 接线）；
   **关键纠错：SEC companyfacts 不含分部数据**；+23 用例；pytest 353 → 376；golden 零漂移
   （详见 #18 Change Log / ADR-042）
✅ Session #27（M-36）：M-35 收尾——FMP 多 key / `/stable` 端点 / Shape C / 关键词表补全
✅ Session #28（M-37）：商业理解层六模块映射 + 四态决策契约（DecisionStatus）+
   Identity Resolution（data/identity_resolver.py：SEC 链 + OpenFIGI）+ business_intelligence.py
   （业务证据收集器）；pytest 382 → 398；golden 零漂移（详见 #18 Change Log / ADR-043、044）
✅ Session #29（M-38）：SEC 10-K / 20-F filing-instance XBRL 业务证据抽取
   （data/filing_evidence.py：FilingBusinessExtractor 走 CIK → submissions → 10-K/20-F →
   index.json 优选 *_htm.xml 实例；parse_segment_revenue 纯函数，四重防重复，source="sec-xbrl"）
   + 四态决策端到端测试；pytest 398 → 413；golden 零漂移（详见 #18 Change Log / ADR-045）
✅ Session #30（M-39 + M-32）：SEC filing-instance XBRL 生产化接入 providers 主链
   （segment_revenue.resolve_segments 源链 FMP → SEC filing-instance XBRL，两层皆空 → []）
   + Taxonomy 参与路由（taxonomy_routing_override 三道 gating：CONFIRMED + 跨 identity family
   冲突 + 经济护栏；对比内部身份判定 best_bt 而非 routing_bt）+ TestTaxonomyRoutingGate；
   pytest 413 → 429；**golden 零漂移（未重生成）**（详见 #18 Change Log / ADR-046、047）
下一步从上方「剩余可跟进项」开始，禁止重做上述已完成项。
```

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
| pyproject.toml | 🔧 Ruff lint 标准（`target-version=py312` + 排除一次性 dev 脚本 + `main.py`/`tests/conftest.py` 的 E402 豁免）——Session #36 | 2026-11-15 |
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
| tests\test_monte_carlo_modes.py | ✨ Session #20（Phase 2）：MC 双模式 14 测试——`TestBaseCaseReconciliation`（MSFT/AAPL 锚点≈DCF；NBIS 亏损期归零）/ `TestMarginBounds`（负利润率保留 + 可配置边界）/ `TestHistoricalFallback`（JPM 金融股回退 historical）/ `TestMetadata`（种子·请求数·有效+无效数·分布·相关矩阵·可复现）/ `TestScenarioSplit`（金融股经营情景为空；operating/discount 标记）/ `TestWipeoutWording`（报告用「Equity Value Wipeout Probability」，标注非独立证据） | 2026-11-13 |
| tests\test_phase3_integrity.py | ✨ Session #21（Phase 3）：估值完整性 P1 14 测试——β 多窗口 ×7（`beta_window_note` <2 窗口返回 None / 极差离散度 / WACC 填充 windows+dispersion / 无窗口诚实返回 None / bottom-up 槽位默认缺失 / provider 周线 keying / `_estimate_beta_windows` 全窗口）+ peer 溯源 ×3（`PEER_SOURCE_LABELS` 封闭集 / breakdown 带 `peer_source_kind` / APPROXIMATE 重路由带样本数）+ 同源去重 ×4（`_independent_evidence` 归并同族 / 唯一模型各自计数 / 门控按独立证据数 / 无重复不加 note） | 2026-11-13 |
| tests\test_phase4_integrity.py | ✨ Session #22（Phase 4）：估值完整性验收断言 9 测试（逐条锚定任务书 10 条验收标准）——`test_severity_floor_never_safer_than_worst_flag`（标准 3，全 universe）/ `test_high_flag_forces_overall_at_least_high` / `test_severity_floor_actually_engages_in_universe` / `test_iqr_excluded_core_model_is_unresolved_disagreement`（无解 CDF 锚点法构造 IQR 排除核心模型 → 标准 1/2）/ `test_agreement_cap_gated_on_independent_evidence_not_solved_count` / `test_extreme_tv_dominance_downweights_dcf` / `test_unknown_identity_never_claims_exact_industry_match`（标准 8/9）/ `test_whole_universe_invariants_and_sample_accounting`（标准 6/7/10）/ `test_negative_fcf_build_outs_stay_flagged` | 2026-11-13 |
| classification\taxonomy.py | ✨ Session #23：**内部标准 Taxonomy 模块（唯一真相来源）**——`IdentityNode`（canonical key 点分层级 + label + parent + `business_type` + `depth`）/ `IDENTITY_NODES`（**99 节点**，`_NODE_DEFS` 声明；`depth` 由 **parent 链** `_structural_depth()` 推导，非 `key.count(".")`）/ `BUSINESS_MODEL` 枚举（SaaS Subscription / Licensing / Advertising / Transaction Fee / Hardware Sales / Cloud Usage …）/ `MODEL_KEYWORDS`（含 `commodit` 词干匹配）/ `YAHOO_INDUSTRY_TO_NODE` + `YAHOO_SECTOR_TO_NODE`（外部标签映射）/ `ExternalClassification`（Yahoo/GICS/NAICS/ML，原样保留）/ `ConflictKind`（CONSISTENT/REFINEMENT/IDENTITY_WINS/ECONOMICS_ONLY/INSUFFICIENT）+ `reconcile_identity()` / `economic_identity_ceiling()`（**黄金法则**）/ `common_ancestor()` / `node_from_yahoo()`（两段式 longest-key-wins）/ `detect_business_models()` / `build_revenue_composition()` / `attach_taxonomy_profile()`（additive shadow 接线） | 2026-11-14 |
| tests\test_taxonomy.py | ✨ Session #23：五维模型契约 48 用例——`TestNodeTreeIntegrity`（parent 链 / depth 结构 / 族根无父）/ `TestYahooMapping`（longest-key-wins / industry 优先于 sector / order-independent；AMZN→`cons.ecommerce`、KR→`cs.retail`）/ `TestGoldenRule`（跨族 + 同族兄弟收敛 common ancestor）/ `TestReconciliation`（5 种冲突状态 + 描述细化）/ `TestBusinessModels`（顺序 / 去重 / 商品词 / `commodit` 词干）/ `TestRevenueAndEconomics`（concentration / 形状 flags / CAGR）/ `TestFiveDimensionContract`（原样保留外部标签 / additive / description 信号 / ML 标签映射） | 2026-11-14 |
| data\sic_map.py | ✨ Session #24（H-03）：**SEC SIC → Yahoo taxonomy 桥接**（一手监管数据 → 引擎消费口径）——`SIC_TO_YAHOO`（约 180 条精确 4 位）+ `SIC2_TO_YAHOO`（约 68 条 2 位大类）+ `SIC_DESC_KEYWORDS`（约 130 条关键词，按具体→宽泛排序，`semiconductor` 先于 `software`）；`map_sic_to_yahoo(sic, sic_description)` 解析顺序 = 精确 4 位 → 2 位大类 → 描述关键词；`_normalize_sic()` 零填充；**契约：每个映射产出的 industry 必须能被 `classifier.py` 硬规则消费**（否则返回 None，不填入无法行动的字串） | 2026-11-14 |
| data\industry_resolver.py | ✨ Session #24（H-03）：**三源 sector/industry 解析器**——`SectorIndustryResolver`（类级 `_MEM` + 磁盘缓存 `.cache/`）优先级链：`_from_financedatabase`（离线 Yahoo 兼容，30 万+ 元数据）→ `_from_sec_edgar`（`company_tickers.json` 取 CIK → `data.sec.gov/submissions/CIK{cik10}.json` 取 `sic`/`sicDescription` → `map_sic_to_yahoo` 桥接）→ `_from_wikidata`（SPARQL P452 行业，兜底）；`resolve(ticker)` 返回 `{sector, industry, sic, sic_description, source}`，任一源缺失/断网返回 `{}` 继续下一层；`batch_get()` 只返回非空；SEC 请求带合规 `User-Agent`（`SEC_USER_AGENT` 可配，默认含联系方式）；点号 ticker 变体（BRK.B→BRK-B）；`resolve_sector_industry()` 便捷入口 | 2026-11-14 |
| data\industry_beta.py | ✨ Session #24（H-03）：**bottom-up 同业无杠杆 β**——`derive_industry_unlevered_beta(ticker, sector, industry, *, peer_lister, beta_fetcher, max_peers=10, tax_rate=0.21, cache_path, offline)`：同业列表（FinanceDatabase `fd.Equities().select(industry=)`）→ 逐 peer β（yfinance）与 D/E → **Hamada 去杠杆** `β_u = β_L / (1 + (1−t)·(D/E))` → 取**中位**（抗离群）；`IndustryBetaResult` dataclass + `note()`（人类可读溯源）；**契约：<3 家同业或无可得 β → 返回 None（绝不伪造）**；`BOTTOM_UP_BETA=0` 环境变量可关；缓存 key `{sector}|{industry}` 存 `.cache/industry_beta.json`；`offline=True` 时不触碰任何 lister | 2026-11-14 |
| tests\test_sic_map.py | ✨ Session #24（H-03）：SIC 桥接 24 用例——`test_exact_sic_mapping`（16 参数：3571→Computer Hardware / 3674→Semiconductors / 7372→Software-App / 6021→Banks-Diversified / 6331→Insurance-P&C / 6798→REIT-Diversified / 2834→Drug Mfrs-General / 2911→Oil&Gas Refining / 4911→Utilities-Electric / 1040→Gold / 3721→Aerospace / 3711→Auto Manufacturers / 5411→Grocery / 4813→Telecom / 9995→Conglomerates）/ `test_two_digit_major_group_fallback_when_code_unknown`（3699→SIC2["36"]）/ `test_description_keyword_fallback_when_code_missing` / `test_int_and_str_sic_are_equivalent` / `test_zero_padding_is_applied`；守卫 `test_every_exact_industry_is_classifiable` / `test_every_major_group_industry_is_classifiable` / `test_every_description_keyword_is_classifiable_and_ordered_specific_first` | 2026-11-14 |
| tests\test_industry_resolver.py | ✨ Session #24（H-03）：三源链 12 用例（离线 monkeypatch，autouse `_clear_mem` 清 `SectorIndustryResolver._MEM`）——FinanceDB 层优先（无 HTTP）/ SEC 层映射 SIC（AAPL→3571→Computer Hardware，source=sec-edgar）/ 点号变体（BRK.B→BRK-B→6331）/ Wikidata 兜底（source=wikidata）/ 磁盘持久化 + offline 复用 / offline 无缓存返回 `{}` / 无法解析返回 `{}` / `batch_get` 只返回非空 | 2026-11-14 |
| tests\test_industry_beta.py | ✨ Session #24（H-03）：bottom-up β 15 用例——`test_hamada_unlevering_math`（`_unlever(1.5,0.5,0.21)==1.5/1.395`，负 D/E 归零）/ `test_median_of_unlevered_betas` / `test_hamada_applied_across_peers` / `test_target_ticker_excluded_from_peers` / `test_returns_none_below_min_peers` / `test_returns_none_when_industry_missing` / `test_offline_returns_none_without_touching_lister` / `test_env_flag_disables_bottom_up`（BOTTOM_UP_BETA=0）/ `test_peer_lister_failure_returns_none` / `test_result_cached_per_industry` / `test_max_peers_cap_respected` / `test_note_is_human_readable`（断言「去杠杆」） | 2026-11-14 |
| data\damodaran_beta.json | ✨ Session #25（M-34）：**Damodaran 行业 β 快照（L3 兜底基准）**——`_meta`（author/url/as_of="2026-01"/fields）+ `industries`（**100 行业**，每条 `unlevered_beta` + `unlevered_beta_cash_adjusted`；Semiconductor 1.49/1.50、Software (System & Application) 1.23/1.25、Banks (Regional) 0.29/0.37、Total Market 0.72/0.76 …）；**仅作 L3 last-resort 基准，行业未覆盖/文件缺失 → 解析返回 None（绝不伪造）** | 2026-11-14 |
| data\segment_revenue.py | ✨ Session #26（M-31）：**分部收入数据层**——`Segment`（frozen dataclass：`label`/`revenue`/`operating_income`/`as_of`/`source`）；`SegmentRevenueResolver`（类级 `_MEM` + 磁盘缓存 `.cache/segment_revenue.json`；`get_segments(ticker)` 先 `_MEM` → 磁盘 → 在线；`batch_get()`）；在线层 `_from_fmp_v4`（`/api/v4/revenue-product-segmentation?structure=flat`）/`_from_fmp_v3`（legacy），**需 `FMP_API_KEY`，无 key → `[]`（绝不伪造，不发请求）**；解析 `_extract_fmp`（两种 shape：flat segment→revenue，或 `[{date:{seg:rev}}]` 取最新期）+ `_rows_from_mix`；`to_revenue_composition(segments)`（按收入占比归一为 taxonomy `RevenueComposition`，空 → `unavailable()`，延迟 import 避免循环）；`segment_weights(segments, by="value")`（**业务价值优先**：所有可用分部均有 `operating_income>0` → 按营业利润加权，否则回退收入；返回归一到 1.0 的 `[(label, weight)]`）；**关键记录：SEC `companyfacts` 不含分部（dimensional）数据，故不用 SEC 层** | 2026-11-14 |
| tests\test_segment_revenue.py | ✨ Session #26（M-31）：分部收入 11 用例（离线 `_FakeClient`，autouse `_clear_mem` 清 `SegmentRevenueResolver._MEM` + `FMP_API_KEY`）——`test_shape_date_to_mix_parses_latest` / `test_shape_flat_segment_to_revenue` / `test_no_key_returns_empty`（断言无 key 不发请求）/ `test_non_positive_and_blank_labels_dropped` / `test_disk_cache_persisted_and_replayed_offline` / `test_returns_empty_when_nothing_resolves` / `test_to_revenue_composition_normalises_pct` / `test_to_revenue_composition_unavailable_when_empty` / `test_weights_prefer_operating_income_when_present` / `test_weights_fallback_to_revenue_when_income_missing` / `test_weights_empty_when_nothing_usable` | 2026-11-14 |
| data\identity_resolver.py | ✨ Session #28（商业理解层）：**Identity Resolution 层**——`IdentityResolver`（`resolve(ticker) → ResolvedIdentity`：`cik`/`sic`/`sic_description`/`figi`/`sector`/`industry` + `sources` + `provenance()`；`has_regulatory_id`）；**Layer A** 复用在位 SEC 链（`SectorIndustryResolver.resolve_identity()`）；**Layer B** OpenFIGI（`_from_openfigi`，仅 `OPENFIGI_API_KEY` 存在时 POST `https://api.openfigi.com/v3/mapping`，`offline` 跳过）+ `_first_figi()` 解析；**缺失字段一律 None，绝不伪造**；模块级便捷入口 `resolve_identity(ticker, *, offline=False)` | 2026-11-14 |
| classification\business_intelligence.py | ✨ Session #28（商业理解层）：**Business Evidence 收集器**——`BusinessEvidence`（`description`/`description_source`/`revenue_segments: List[(label, pct)]`/`revenue_source`/`revenue_as_of`/`notes`；`has_description`/`has_segments`/`provenance()`）+ `extract_business_evidence(data, *, description=None)`（业务描述 ← `MarketData.description`/`business_summary`，分部 ← `FinancialData.revenue_composition` 经 `_revenue_from_composition`）；**证据缺失显式标注为缺失**（`notes`），使下游可诚实输出「数据不足」而非猜测 | 2026-11-14 |
| tests\test_identity_resolver.py | ✨ Session #28：Identity Resolution 5 用例（`_FakeClient` monkeypatch，autouse 清 `SectorIndustryResolver._MEM`）——SEC 供 CIK / 未解析**绝不伪造**（无 key → FIGI None）/ OpenFIGI 仅在有 key 时使用 / offline 跳过 OpenFIGI / 空 ticker | 2026-11-14 |
| tests\test_business_intelligence.py | ✨ Session #28：Business Evidence 4 用例（`_NS` duck-typed 对象）——description 来自 `market` / description override / segments 来自 `revenue_composition` / 无证据**显式标注** | 2026-11-14 |
| data\filing_evidence.py | ✨ Session #29（M-38）：**SEC 10-K / 20-F filing-instance XBRL 业务证据抽取**——`FilingRef`（`cik`/`form`/`accession`/`filing_date`/`primary_document` + `accession_nodash`/`index_url`）+ `FilingBusinessExtractor`（`latest_filing(ticker)`：CIK → `data.sec.gov/submissions/CIK{cik}.json` 的 `filings.recent`（newest first）→ 首个 `10-K`/`20-F` → `_instance_url()` 走 filing `index.json` 优选 `*_htm.xml` 实例文档（`_pick_instance` 排除 `r\d+.xml`/`*_cal|def|lab|pre|ref.xml`）；`get_segments(ticker)` 先 `_MEM` → 磁盘 → `_resolve` → 缓存）；`parse_segment_revenue(xml_text) -> List[(label, revenue)]` **纯函数**：`_parse_contexts` 解析 `xbrli:context` → `(endDate, axis, member)`（`xbrldi:explicitMember@dimension` 识别 segment 轴），**仅取带 segment 轴的事实**（`_REVENUE_LOCALS` = us-gaap `Revenues`/`RevenueFromContractWithCustomerExcludingAssessedTax`/`SalesRevenueNet`… + ifrs-full `Revenue`/`RevenueFromContractsWithCustomers`）、按 `_AXIS_PRIORITY`（`StatementBusinessSegmentsAxis` > `ProductOrServiceAxis` > ifrs `SegmentsAxis` > `StatementGeographicalAxis`）**取单一轴**聚合、**取最新期间**（`_aggregate` 按 end date 去重）、**instant context 一律忽略**（要求 duration 的 endDate）、**绝不把合并总额计入分部**；`_humanize()` 去 `Member` 后缀；`_from_rows()` 返回 `segment_revenue.Segment` + `source="sec-xbrl"`（**drop-in 兼容** `to_revenue_composition`）；`_get()` 带合规 `User-Agent`（`SEC_USER_AGENT` 可配）；**无 CIK / 无实例 / 解析失败 / malformed XML → `[]`（绝不伪造）**；`offline=True` 零网络；模块级便捷入口 `get_filing_segments(ticker, *, client, offline)` | 2026-11-14 |
| tests\test_filing_evidence.py | ✨ Session #29（M-38）：filing XBRL 9 用例（`_FakeClient` 按 URL 子串路由，autouse 清 `SectorIndustryResolver._MEM`+`FilingBusinessExtractor._MEM` + 令 `financedatabase` 不可导入）——`TestParseSegmentRevenue`：**分部解析且排除合并总额**（合并 383,285,000,000 不计入）/ **取最新期间**（上年 999 忽略）/ **business 轴优先于地理** / **instant context 忽略** / malformed+empty → `[]`；`test_latest_filing_picks_annual_form`（跳过 8-K 选 10-K）/ `test_get_segments_end_to_end`（`to_revenue_composition` 占比和 = 1.0）/ `test_unresolved_is_empty_and_never_fabricated` / `test_offline_makes_no_calls`（`client.calls == []`） | 2026-11-14 |
| _batch_eval.py | ✨ Session #31：**50 只跨行业蓝筹离线全量审计 harness**——逐标的跑 `run_pipeline`（synthetic/ML 可选），输出分类/行业/适用模型/路由违规/Reverse DCF 状态/隐含值/bound/风险旗标（`risk_severity`/`risk_flags`/`risk_severity_floor`/`risk_severity_by_score`/`beta_origin`）/特殊画像（NI<0、FCF<0）；落盘 `_batch_eval_<label>.json`（Round 2 增记风险旗标，供下一轮区分假 High / 真 High） | 2026-11-14 |
| _audit_summary.py | ✨ Session #31：**五问紧凑摘要**——`=== <label>: N/N = x% | routing_viol | defects` + 逐标的表 + Q5 Reverse DCF（量化 / bound-only / 未量化）+ **Q4b 风险底线**（Session #32 新增：`risk_severity != risk_severity_by_score` 即被单一 flag 抬升者）+ Q4 特殊情况（亏损/负 FCF + 金融 FCF 假象） | 2026-11-14 |
| _diag_risk.py | ✨ Session #32：**风险诊断脚本**——dump 标的的增长序列（`revs`/`growths`/`mean`/`σ`/`CV`）+ overall/score/floor/by_score + 全部 flag；`--synthetic` 切离线 | 2026-11-14 |
| _audit_risk_detail.py | ✨ Session #32：**Growth Risk 证据 dump**——列出每个带 Growth Risk flag 的标的的离散度证据（σ/CV/downside σ/worst year）与其它旗标，用于区分假 High 与真 High | 2026-11-14 |
| valuation\equity_bridge.py | ✨ Session #38（Phase 1-3）：**EV ↔ Equity 独立桥**——`EquityBridge` dataclass + `enterprise_to_equity()` / `equity_to_enterprise()`（**共用同一 resolver → 精确互逆**）+ `_resolve_claims()`（重复扣除守卫：`net_debt_includes_minority/preferred` / `market.leases_in_debt is True` 时不再扣）+ `equity_bridge_components()`；`Equity = EV − NetDebt − MinorityInterest − PreferredEquity − Leases(未含于Debt时) − OtherClaims + NonOperatingAssets`；每项可选（`None` = 无该项索偿，**绝不静默按 0**）；`itemized_note()` 返回逐项审计串 | 2026-11-15 |
| valuation\sbc.py | ✨ Session #38（Phase 1-4）：**SBC 归一化模块**——`normalize_fcf_for_sbc(reported_fcf, sbc, *, method, shares, sbc_dilution_rate)` + `SbcNormalization` dataclass；`SBC_METHODS=("expense","dilution","none")`（`DEFAULT_SBC_METHOD="expense"`）；`expense`→扣 FCF（股数不变）、`dilution`→缩放股数（FCF 不变）；**二选一机制性杜绝双重计数**；SBC 缺失/为 0 → 不调整（绝不臆造成本）；`dilution` 缺稀释率 → 回退 `expense`；`itemized_note()`/`as_dict()` | 2026-11-15 |
| tests\test_equity_bridge.py | ✨ Session #38：EV↔Equity 桥 18 用例——`TestSimpleStructure`（无附加索偿 = EV−NetDebt）/ `TestComplexStructure`（MI + 优先股 + 非经营性资产，`itemized_note()` 带符号断言）/ `TestLeaseConvention`（`leases_in_debt` 三态）/ `TestInverse`（`enterprise_to_equity ∘ equity_to_enterprise = id`，parametrize）/ `TestMissingData`（缺净债务 → note 不崩）/ `TestModelWiring`（6 模型接线） | 2026-11-15 |
| tests\test_sbc.py | ✨ Session #38：SBC 归一化 13 用例——`TestExpenseMethod`（`adjusted = reported − sbc`，股数不变）/ `TestDilutionMethod`（`factor = 1 + rate`，FCF 不变）/ `TestNoAdjustment`（缺失/0 → 不调整）/ `TestReverseDcfWiring`（`assumptions["SBC Adjustment"]` + `breakdown["sbc_normalization"]`） | 2026-11-15 |
| analysis\threshold_calibration.py | ✨ Session #40（M-67）：**跨行业诊断阈值校准（运行时单一来源）**——`ThresholdCalibration`（frozen dataclass：`archetype`/`tier`/`fcf_aligned_pp`/`fcf_flag_pp`/`fcf_high_ratio`/`beta_min_peers`/`rationale`/`judged_dispersion`/`evidence_n` + `note()` 审计行）；波动分档 `tier_for_dispersion()`（`<0.03 stable` / `0.03–0.06 moderate` / `≥0.06 volatile`，单调）+ `TIER_STABLE_MAX_DISPERSION` / `TIER_VOLATILE_MIN_DISPERSION`；带宽 `_TIER_BANDS`（stable `2pp/4pp/1.75×` / moderate `3pp/5pp/2×` / volatile `4pp/7pp/2.5×`，随波动放大）；β 同业地板按**池广度**分档 `beta_min_peers_for()`（`BETA_MIN_PEERS_BROAD=5` / `_NARROW=3` / `_UNKNOWN=4`，窄池 `{NEOBANK, FINTECH, CONGLOMERATE}`）；`_ARCHETYPE_TIER` + 冻结证据 `CALIBRATION_EVIDENCE`（离线篮子 σ/n）+ `calibration_for()` / `thresholds_for_tier()` / `DEFAULT_CALIBRATION`（= moderate，向后兼容）+ `calibration_evidence_note()` / `calibration_table_note()` | 2026-11-15 |

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
| data\reconciliation.py (Session #09) | 滚动 P/E 检查改为方向感知文案：供应商 P/E 低于价格/GAAP-EPS 隐含值 → non-GAAP/正常化口径差（非盈利不稳定）；高于 → 旧口径/摊薄股数或盈利下滑 | 2026-11-03 |
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
| config.py (Session #16) | ✨ 新增单一真源 `resolve_forecast_horizon(business_type)`（读 `REVERSE_DCF_BY_TYPE[bt].horizon`，缺失回落 `DEFAULT_FORECAST_HORIZON_YEARS=5`）；`__all__` 导出（ADR-029） | 2026-11-12 |
| forecasts\fcf_projection.py (Session #16) | 🐛 **问题 1**：新增 `gordon_terminal_value()`（返回 `TerminalValueResult`：`terminal_value`/`pv_terminal_value`/`suppressed`/`inflated`/`note`）——终期 FCF ≤ 0 时**抑制终值不翻转符号**；`project_enterprise_value()` 改调它并返回 `terminal_fcf_negative`；新增 `MIN_WACC_TG_SPREAD=0.005` 统一下限；`FcfProjectionResult` 增 `terminal_fcf_negative`（ADR-028） | 2026-11-12 |
| models\dcf.py (Session #16) | 🐛 `_pv_calculations()` / `_pv_tv_only()` 统一改调 `gordon_terminal_value()`（消除三处符号翻转重复）；`forecast_horizon` 降级为一次性 override（`self._horizon_override`）+ 新增 `_resolve_horizon(profile)`（经 `resolve_forecast_horizon`）；breakdown 增 `terminal_fcf_negative`；import 增 `gordon_terminal_value`（ADR-028/029） | 2026-11-12 |
| models\reverse_dcf.py (Session #16) | 🐛 **问题 3**：**删除 `self.horizon = int(horizon)` 污染源**，`calculate()` 内解析局部 `horizon = self._resolve_horizon(profile)`；`_project_ev` / `_solve_revenue_cagr` / `_normalized_growth_solve` 签名新增 `horizon: int`；新增 **求解器 residual 检查**（`rel_resid>1e-3` → `SolverStatus.APPROXIMATE` + note）（ADR-029） | 2026-11-12 |
| simulation\monte_carlo.py (Session #16) | 🐛 新增 `_resolve_horizon(profile)`（经 `resolve_forecast_horizon`）；`run()`/`_project_one()` 改用局部 `horizon`（移除本地常量回落）（ADR-029） | 2026-11-12 |
| analysis\scenario.py (Session #16) | 🐛 `run_all()`/`_run_one()`/`_forecast_engine()` 改用 `resolve_forecast_horizon`；`DCFModel(config=dcfg, forecast_horizon=horizon)`（ADR-029） | 2026-11-12 |
| analysis\sensitivity.py (Session #16) | 🐛 `wacc_vs_terminal_growth()` / `growth_vs_margin()` / `_project_value()` 改用 `resolve_forecast_horizon` + `DCFModel(forecast_horizon=horizon)`（ADR-029） | 2026-11-12 |
| analysis\expectation.py (Session #16) | 🐛 `forecast_cagr()` 改用 `resolve_forecast_horizon(business_type_from_profile(profile))`（ADR-029） | 2026-11-12 |
| analysis\risk.py (Session #16) | 🐛 `_terminal_value_risk()` 新增 `terminal_fcf_negative=True` → **HIGH** 级旗标分支（终值抑制后 `tv_percent_of_ev=0`，原阈值检测不触发会导致旗标丢失） | 2026-11-12 |
| tests\test_dcf.py (Session #16) | ✨ 新增 `TestTerminalValueHonesty`（6 用例）：负/零/None 抑制、正例闭式对齐、WACC≤g 单一 floor、烧钱公司终值抑制、投影 round-trip、DCF 透出 `terminal_fcf_negative` | 2026-11-12 |
| tests\test_reverse_dcf.py (Session #16) | ✨ 新增 `TestHorizonIsolation`（4 用例）：按类型解析年限、**断言 `not hasattr(model, "horizon")`**（无状态污染）、DCF 按类型解析、显式 override 优先 | 2026-11-12 |
| tests\golden\report_fingerprints.json (Session #16) | 🔧 `UPDATE_GOLDEN=1` 重新生成：仅 1 字段有意漂移 `NBIS.median_value: 12.76 → 10.46`（旧值由伪正终值虚高，已审阅） | 2026-11-12 |
| config.py (Session #17) | ✨ `ReverseDCFConfig` 新增 Phase 2 约束字段：`implied_margin_lo/hi`、`implied_fcf_margin_lo/hi`、`implied_wacc_lo/hi`、`implied_tg_lo/hi`、`implied_residual_tol`（硬边界 + 残差容差）（ADR-030） | 2026-11-12 |
| forecasts\fcf_projection.py (Session #17) | ✨ 新增 `project_enterprise_value_flat_margin()`（`FCF_t = revenue_t × fcf_margin`）——绕过 NOPAT/DA/CapEx/NWC 桥，使 FCF margin 成为良定义独立求解目标；终值仍走 `gordon_terminal_value()`；`__all__` 导出（ADR-030） | 2026-11-12 |
| models\reverse_dcf.py (Session #17) | ✨ 新增 `ImpliedSolve` dataclass + `_bridge_inputs()` + **约束式求解器** `_solve_implied_scalar()`（硬边界 → `NO_SOLUTION_IN_RANGE` 不钳制 + 单调性 + 残差检查）+ `_implied_expectations()`（OM / FCF margin / WACC / TG 四驱动 one-at-a-time）；`calculate()` 写入 `breakdown["implied_expectations"]`（ADR-030） | 2026-11-12 |
| analysis\expectation.py (Session #17) | ✨ `ImpliedExpectations` 新增 8 字段（`implied_operating_margin`/`implied_fcf_margin`/`implied_wacc`/`implied_terminal_growth` 各含 `*_status`）+ `implied_constraint_notes`；`implied_expectations()` 从 `breakdown["implied_expectations"]` 透传（ADR-030） | 2026-11-12 |
| reporting\dashboard.py (Session #17) | ✨ `_implied_section()` 渲染四隐含驱动（含「不可解（超出约束区间）」与「_(近似)_」标注）；`import` 增 `SolverStatus`（ADR-030） | 2026-11-12 |
| tests\test_reverse_dcf.py (Session #17) | ✨ 新增 `TestConstraintSolver`（5 用例：线性增/减求解、越界不钳制、目标越界指名边界、目标函数异常 → INFEASIBLE）+ `TestImpliedExpectationsPhase2`（3 用例：四驱动落字段、WACC/TG 利差约束、OM round-trip） | 2026-11-12 |
| config.py (Session #18) | ✨ `SolverStatus` 新增 `NON_MONOTONIC` / `MULTIPLE_ROOTS` / `FLAT_OBJECTIVE`；`ReverseDCFConfig` 新增 `implied_monotonic_samples: int = 21`（区间采样验证单调性）（ADR-031） | 2026-11-12 |
| models\reverse_dcf.py (Session #18) | 🐛 **P0-1** `_finish_root()`：`brentq` 失败后若 `f(a)·f(b) > 0` → `NO_SOLUTION_IN_RANGE`（拒可疑根），求解后一律 residual 检查；🐛 **P0-2** `_solve_implied_scalar()` 重写为「21 点采样验证单调性 → 非单调扫描 `_root_brackets()`（0/1/>1 分支）→ 常数目标 `FLAT_OBJECTIVE`」；🐛 **P1-5A** `_solve_revenue_cagr()` 端点根优先 + `> 0` 越界判定 + 二分前 bracket 重校验；🐛 **P0-3** 新增 `_finalize_revenue_cagr()`（终期 FCF ≤ 0 → SOLVED 降级 APPROXIMATE）；`breakdown` 增 `terminal_fcf_negative`（ADR-031） | 2026-11-12 |
| analysis\expectation.py (Session #18) | ✨ `ImpliedExpectations` 新增 `terminal_fcf_negative` 字段；`implied_expectations()` 从 breakdown/implied_expectations 透传抑制旗标并在 `implied_constraint_notes` 追加「Terminal Value Suppressed — Turnaround Assumption Required」（ADR-031） | 2026-11-12 |
| reporting\dashboard.py (Session #18) | ✨ `_implied_section()` 按 `SolverStatus` 枚举渲染新增未解状态（非单调/多解/无敏感度/不可行），并在终值抑制时输出「⚠️ Terminal Value Suppressed」说明（ADR-031） | 2026-11-12 |
| tests\test_reverse_dcf.py (Session #18) | ✨ 新增 18 用例：`TestSolverBoundariesSession18`（端点根 ×2 / 无效 bracket / 无 bracket / 非单调无根 / 多根 / 常数目标 ×2）+ `TestNegativeTerminalFCFSession18`（降级 ×2 / 传播 / breakdown+期望透出 / 负 FCF 标的回填）+ `TestImpliedRoundTripsSession18`（FCF margin / WACC / TG round-trip）+ `TestMultiTickerStateIsolation`（共享实例 vs 新建实例 / 年限不泄漏） | 2026-11-12 |
| valuation\wacc.py (Session #19) | 🐛 **P0-1 Rf 单一真源**：`_implied_cost_of_debt()` 签名新增 `risk_free_rate: Optional[float]`，接收 `calculate()` 已按「MarketData → Treasury → config」解析的 `rf`；所有债务成本 fallback（合成评级 / BBB-like）与 CAPM 共用同一 Rf；独立调用仍回落原优先级链；`calculate()` 改为 `self._implied_cost_of_debt(data, risk_free_rate=rf)`（ADR-032） | 2026-11-13 |
| valuation\terminal_growth.py (Session #19) | 🔧 **P0-2 三档语义重定义**：docstring/常量注释明确「GDP 上限只约束 Base」；新增 `BAND_LABELS` 契约常量；`TerminalGrowthRange` 新增 `high_exceeds_gdp` / `gdp_ceiling` / `band_labels` 字段；`calculate()` 计算 `high_exceeds_gdp` 并在为真时追加「High 为乐观情景，非长期稳定终值增长率」note；`derivation_trace()` / `_enforce_strict_bands()` docstring 同步（ADR-032） | 2026-11-13 |
| models\dcf.py (Session #19) | 🔧 **P0-2**：`Terminal Growth (Base)` 说明改为「Long-run stable rate: min(...)」；`Terminal Growth (High)` 说明按 `tvg.high_exceeds_gdp` 分叉——超 GDP 时标注「Optimistic scenario… NOT a long-run stable terminal growth rate」，否则「Optimistic scenario: Base + 0.5%（within long-run GDP）」（ADR-032） | 2026-11-13 |
| reporting\dashboard.py (Session #19) | 🔧 **P0-2 渲染契约化**：三档区块规则文案重写为「Base=长期稳定终值增长率（GDP+Gordon 封顶）；Low/High=保守/乐观情景区间」；`tg.high_exceeds_gdp` 为真时新增「⚠ High X% 高于长期名义 GDP Y%：仅作乐观情景参考，非长期稳定终值增长率」（ADR-032） | 2026-11-13 |
| tests\test_wacc_kd.py (Session #19) | ✨ 新增 3 用例：MarketData 无 Rf + Treasury 有效 → CAPM 与 Kd fallback **同源 Rf**；显式传入 Rf 覆盖 MarketData；无传入时回落 MarketData/config | 2026-11-13 |
| tests\test_terminal_growth.py (Session #19) | ✨ 新增/改写 3 用例：AVGO-like Base=4.5% 时 High=5.0% 且 `high_exceeds_gdp=True`；正常情况 High ≤ GDP 不置旗标；`band_labels` 语义契约断言 | 2026-11-13 |
| analysis\model_agreement.py (Session #19) | 🐛 **P1-3 Weighted Median 边界修复**：`_weighted_median()` 由「首个累计权重 ≥ total/2 的值」改为标准 **midpoint 定义**（下加权中位数与上加权中位数取平均）→ 等权时精确退化为普通中位数；零/负权重剔除；空输入返回 None（ADR-033） | 2026-11-13 |
| tests\test_model_agreement.py (Session #19) | ✨ **新增测试文件** 16 用例：等权偶数/奇数（=普通中位数）、二值平均、单值、乱序输入、不等权（重权主导 / 精确半权平局 / 无平局）、零权重剔除、全零返回 None、负权重钳制、缺失权重默认 1.0、空输入 | 2026-11-13 |
| tests\golden\report_fingerprints.json (Session #19) | 🔧 **已审阅的有意漂移**：`UPDATE_GOLDEN=1` 重生成 4 只标的 `median_value_weighted`（AAPL 123.99→132.19 / AMT 57.82→109.85 / JPM 139.22→151.37 / NOW 147.21→148.84；均归位到普通中位数，证实等权缺陷已修） | 2026-11-13 |
| simulation\monte_carlo.py (Session #20 / Phase 2) | 🔧 **MC 双模式 + 路径锚点对账**：新增 `MODE_BASE_CASE` / `MODE_HISTORICAL`；`run(data, profile, mode=None, dcf_value=None)` 无锚点时回退 historical（附说明）；新增 `_base_case_path()`（提取 DCF base 逐年 `shape_rev`/`margin_offsets`）+ `_project_one_path()`（零扰动精确复现 DCF base FCF 路径）；去除人为 +2% 利润率地板，允许负利润率；锚点沿用 DCF「负股权 → 归零」约定；`MonteCarloResult` 新增 `mode`/`random_seed`/`n_requested`/`n_invalid`/`n_truncated`/`param_distributions`/`correlation`/`anchor_value`/`dcf_anchor`/`reconcile_gap`（ADR-034） | 2026-11-13 |
| config.py (Session #20 / Phase 2) | 🔧 `MonteCarloConfig` 新增可配置边界：`revenue_cagr_lower/upper`、`op_margin_lower/upper`（含负值）、`wacc_lower/upper`、`tg_lower/upper`、`mode`（默认 `base_case`）；`REPORT_SECTION_TITLES` 新增 `scenarios="🎭 折现率情景（Discount Rate Scenarios）"` 与 `operating_scenarios="🏭 经营性情景（Operating Scenarios）"` | 2026-11-13 |
| analysis\scenario.py (Session #20 / Phase 2) | 🔧 **经营/折现情景拆分**：`ScenarioValuation` 新增 `scenario_kind`（默认 `discount_rate`）+ `drivers`；`_run_financial_scenarios`→`scenario_kind="financial"`；`_run_one`→`discount_rate` + `drivers={wacc, terminal_growth}`；新增 `run_operating()`（营收增长 × 利润率扰动 → FCF → EV，`scenario_kind="operating"`，金融股返回 `{}`）（ADR-035） | 2026-11-13 |
| reporting\dashboard.py (Session #20 / Phase 2) | 🔧 `build_report()` 新增 `operating_scenarios` 形参 + 渲染；`_scenario_section` 前置「本组情景仅变动折现率（WACC/g）」；新增 `_operating_scenario_section()`；MC 区块新增模式标签 + 「DCF 假设扰动分布，非独立估值证据」 + 种子/请求数/有效数/无效数/截断数/参数分布/相关矩阵 + 对账行（仅 `mode=="base_case"`）；`P(股权价值归零)` → 「Equity Value Wipeout Probability」 | 2026-11-13 |
| telegram_bot\telegram_bot.py (Session #20 / Phase 2) | 🔧 新增 `operating_scenarios = scenario_analyzer.run_operating(data, profile)`；MC 调用改为 `mc.run(data, profile, dcf_value=<DCF 每股价值 or None>)`；`build_report(..., mc_result, operating_scenarios)` | 2026-11-13 |
| data\models.py (Session #21 / Phase 3) | 🔧 `MarketData` 新增 `beta_windows: Optional[Dict[str, float]]`（窗口标签→回归 β）与 `industry_beta: Optional[float]`（bottom-up/peer unlevered β）；两者默认 `None` 表示「无来源」，绝不伪造 | 2026-11-13 |
| data\providers.py (Session #21 / Phase 3) | 🔧 新增 `BETA_WINDOWS=(("2y_weekly","2y","1wk",40),("3y_monthly","3y","1mo",18),("5y_monthly","5y","1mo",30))` 常量；`_estimate_beta()` 泛化为 `(chart, client, ticker, range_, interval, min_obs)`，SPY 抓取按窗口参数化，周线用 ISO-week keying（`_monthly_returns`→`_period_closes`）；新增 `_estimate_beta_windows()`（逐窗口独立回归，失败窗口显式 `None`）；主流程落 `extra["beta_windows"]`；MarketData 构造传入 `beta_windows`/`industry_beta` | 2026-11-13 |
| valuation\wacc.py (Session #21 / Phase 3) | 🔧 `WaccBreakdown` 新增 `beta_windows`/`beta_dispersion`；新增 `beta_window_note()`（<2 窗口返回 `None`；极差 >0.50 标注「窗口间波动较大」）；`calculate()` 读取 `mkt.beta_windows` 填充 windows+dispersion 并写入 `sources["β (windows)"]`（**多窗口为独立审计输入，不覆盖 CAPM 标量 β**） | 2026-11-13 |
| models\multiples.py (Session #21 / Phase 3) | 🔧 新增 4 档来源常量 `PEER_SOURCE_EXACT_INDUSTRY`/`SECTOR_FALLBACK`/`BUSINESS_TYPE_FALLBACK`/`APPROXIMATE` + `PEER_SOURCE_LABELS` 封闭集；`_sector_peer_multiple` / `_resolve_peer_bucket` 返回 4 元组 `(value, source_text, source_kind, n_peers)`；`calculate()` breakdown 落 `peer_source_kind` / `peer_sample_size` | 2026-11-13 |
| analysis\model_agreement.py (Session #21 / Phase 3) | 🔧 新增 `_MODEL_FAMILY`（P/E↔Historical Multiples→`earnings_multiple`、EV/Sales↔EV/Sales (Unit Econ)→`sales_multiple`、DCF/ReverseDCF→`dcf_forecast`）+ `_independent_evidence()`；覆盖率门控 `_COVERAGE_CAP.get(n_solved)` → `.get(n_independent)`；`ModelAgreement` 新增 `n_independent_evidence`/`duplicate_evidence_groups` + 去重 note（ADR-037） | 2026-11-13 |
| reporting\dashboard.py (Session #21 / Phase 3) | 🔧 导入 `PEER_SOURCE_LABELS`；`_valuation_section` 新增「🔎 同行倍数来源 (可审计)」区块（消费 `breakdown["peer_source_kind"]`）；WACC 区块追加 `beta_window_note()` 渲染 | 2026-11-13 |
| tests\golden_report.py (Session #22 / Phase 4) | 🔧 `BASKET` 9 → 18 只（+GOOGL/AMZN/AVGO/ORCL/CRWV/UPS/KR/BAC/NU）；`build_fingerprint()` 新增 5 字段（`n_independent_evidence`/`raw_solved_count`/`outlier_count`/`effective_aggregation_count`/`core_model_excluded`）；`check_invariants()` #2 门控改 `n_independent_evidence` + 新增 invariant 2b（核心模型被 IQR 排除却输出强一致性 → 缺陷）；清理未用 `by_name` | 2026-11-13 |
| tests\golden\report_fingerprints.json (Session #22 / Phase 4) | 🔧 `UPDATE_GOLDEN=1` 重生成基线（原 9 只既有字段无漂移，仅新增 5 字段 + 新增 9 只 ticker 条目） | 2026-11-13 |
| tests\test_providers_provenance.py (Session #22 / Phase 4) | 🐛 原用 `"BAC"` 作「未知 ticker」，Phase 4 新增 BAC fixture 后不再抛异常 → 2 处改为 `"ZZZZ"`（明确不在 fixture 集的占位符） | 2026-11-13 |
| analysis\risk.py (Session #22 / Phase 4) | 🔧 Ruff 清理：删除未用 `typing.Tuple` 导入 + 未用局部变量 `reason`（Severity Floor 逻辑本身不变） | 2026-11-13 |
| data\models.py (Session #23 / Taxonomy) | 🔧 `MarketData` 新增 `description: Optional[str] = None`（承载 Yahoo `longBusinessSummary`，供描述信号细化 identity）；`CompanyProfile` 新增 8 个 taxonomy **shadow** 字段（`taxonomy_identity_key`/`taxonomy_identity_label`/`taxonomy_business_models`/`taxonomy_conflict_kind`/`taxonomy_audit`/`revenue_composition_available`/`revenue_composition_note`/`external_classification`）——additive，默认缺省，不影响既有字段 | 2026-11-14 |
| data\providers.py (Session #23 / Taxonomy) | 🔧 `_fetch_quote_summary_simple` 采集 Yahoo `assetProfile.longBusinessSummary` → `out["description"]`；`MarketData(...)` 构造传入 `sector=`/`industry=`/`description=extra.get("description")`；`SyntheticDataProvider._build` 传 sector/industry/company_name；`SYNTHETIC_DATA` 补齐 sector/industry 标签（AAPL→Technology/Consumer Electronics、MSFT→Technology/Software、NVDA→Technology/Semiconductors、AMZN→Consumer Cyclical/Internet Retail、KR→Consumer Defensive/Grocery Stores、NBIS/CoreWeave/Oracle→Technology/Software - Infrastructure 等） | 2026-11-14 |
| classification\classifier.py (Session #23 / Taxonomy) | 🔧 `BusinessClassifier.classify()` 末尾调用 `attach_taxonomy_profile(data, profile)`（additive shadow 接线：写入五维 taxonomy 字段，**不改 `business_type`/`applicable_models`/路由**） | 2026-11-14 |
| classification\ml_classifier.py (Session #23 / Taxonomy) | 🔧 ML 成功路径（第 ~2217-2231 行）与 rule_fallback 路径（第 ~1946-1953 行）均调用 `attach_taxonomy_profile`；ML 路径传入原始 top-1 标签作为 `ExternalClassification` 输入（**保留原始标签，不做覆盖**） | 2026-11-14 |
| data\providers.py (Session #24 / H-03) | 🔧 `_fetch_quote_summary_simple` 在 Layer-3 sector/industry resolver 块后新增 **bottom-up β 块**：当 `industry_beta` 缺失且已有 sector/industry 时调用 `data.industry_beta.derive_industry_unlevered_beta(ticker, sector, industry)` 填充 `out["industry_beta"]`（失败静默 debug，不阻断）；配合既有 `MarketData(... industry_beta=extra.get("industry_beta"))` 构造使该审计槽位不再恒为 `None` | 2026-11-14 |
| classification\classifier.py (Session #24 / H-03) | 🔧 `SECTOR_INDUSTRY_MAP` 新增 `("asset management", BusinessType.BANK)`（置于 `capital markets`/`brokerage` 同族附近）：修复 SEC SIC "6726"/"67" → "Asset Management" 经 `map_sector_industry()` 返回 None → 无法触发 +3.0 硬规则的唯一覆盖缺口 | 2026-11-14 |
| data\industry_beta.py (Session #25 / M-34) | 🔧 **整体重写**：裸 `derive_industry_unlevered_beta` → **三级业务身份筛选 + 完整 β 链**。新增 `PeerBeta`/`PeerScreen`/`IndustryBetaResult`（`note()` + `to_chain()`）；`get_companies_by_business_identity(sub_industry, business_model, economic_profile, *, sector, industry_lister, neighbor_lister, model_resolver, profile_resolver, min_peers, use_neighbors)`（L1 同子行业+模型 / L2 相邻行业+`_profile_matches` 经济形状 / L3 空集）；车链数学 `_unlever`/`_relever`/`_cash_adjust`（Cash/Firm 上限 0.90）；`_DAMODARAN_ALIASES` + `_normalize_industry` + `_damodaran_lookup`（L3 兜底，未匹配 → None）；新 `derive_bottom_up_beta(...)`（缓存 key 含 business_model；`offline`/`use_neighbors`/`use_benchmark`/`benchmark_path`）；`derive_industry_unlevered_beta` 保留为窄访问器（`use_neighbors=False, use_benchmark=False`） | 2026-11-14 |
| data\models.py (Session #25 / M-34) | 🔧 `MarketData` 新增 `bottom_up_beta: Optional[float] = None`（CAPM 消费的 target-relevered β）+ `bottom_up_beta_chain: Optional[Dict[str, Any]] = None`（完整链快照）；`industry_beta` 语义澄清为「原始 peer-median *unlevered*」 | 2026-11-14 |
| valuation\wacc.py (Session #25 / M-34) | 🔧 `calculate()` β 段改**三段优先级**：bottom-up（>0 时用，仍 winsorize [0.30,2.50]）→ 回归 β（winsorized）→ `default_unlevered_beta`；`WaccBreakdown` 新增 `beta_bottom_up`/`beta_bottom_up_note`；`beta_transparency_note()` 展示完整分子链（有 `note` 用 note，否则 `bottom-up β = N/A`）；`resolve_effective_beta()` 的 `clamped` 语义修正为「**原始回归 β** 越界」 | 2026-11-14 |
| data\providers.py (Session #25 / M-34) | 🔧 删除旧 Layer-3 bottom-up β 块；在 `kd_snapshot` 后新增 **bottom-up β 链块**（`infer_business_models(description + industry)` 推断 `business_model`；target D/E = 总债务/市值；tax = `etr_snapshot`；调用 `derive_bottom_up_beta`）；`MarketData(...)` 构造改传 `industry_beta=industry_beta_unlev, bottom_up_beta=bottom_up_beta, bottom_up_beta_chain=bottom_up_chain` | 2026-11-14 |
| analysis\risk.py (Session #25 / M-34) | 🔧 `_wacc_risk()` evidence 文案改为「Beta = X（原始回归 β = Y 超出 CAPM 区间）」，与 `clamped` 新语义一致（不再暗示「所用 β 被截断」） | 2026-11-14 |
| reporting\dashboard.py (Session #25 / M-34) | 🔧 市场区 β 文案「统一采用截断值 {β}」→「统一采用 β = {β}」（bottom-up 选取不再被误述为截断） | 2026-11-14 |
| tests\test_industry_beta.py (Session #25 / M-34) | 🔧 **12 → 32 用例**：新增 `_cash_adjust`/`_relever` 数学；三级筛选 5 例（L1 无 resolver 声明未过滤 / L1 模型过滤 / L2 升级 / L2 经济特征过滤 / L3 无同业 / 空子行业）；Damodaran 4 例（alias 命中 / unmatched → None / 文件缺失 → None / 内置快照）；完整链 + L3 fallback + `to_chain()` 完整性 + `PeerBeta` 输入；CAPM 3 例（bottom-up 优先 / 回退回归 β / 超上限 winsorize） | 2026-11-14 |
| data\industry_beta.py (Session #26 / M-35) | 🔧 新增 `derive_segment_level_beta(ticker, segments, *, sector, target_d2e, target_tax_rate, cash_to_firm, segment_industry_resolver, beta_provider, benchmark_path, offline, min_coverage=0.60, min_segments=2)`（逐分部 label→行业→复用三级筛选求 β_u→按覆盖子集重归一权重加权→`_cash_adjust`→relever；`level=0` / `source="segment-weighted"`；门控 <min_segments 或覆盖 <min_coverage → None）；新增 `_SEGMENT_INDUSTRY_KEYWORDS`（~65 条 label 关键词→Yahoo 行业，具体优先）+ `_default_segment_industry_resolver` + `_coerce_segments`；`IndustryBetaResult` +`segments` 字段 + `note()`（`level 0 → 分部加权`）+ `to_chain()`（`"segments"`）；`_build_result` +`segments` 形参；`derive_bottom_up_beta` +`segments`/`segment_industry_resolver`/`segment_cash_to_firm`/`segment_beta_provider` 形参 + **优先分支**（成功即返回分部结果，否则走公司级）；`__all__` +`derive_segment_level_beta` | 2026-11-14 |
| data\models.py (Session #26 / M-31) | 🔧 `FinancialData` 新增 `revenue_composition: Optional[Any] = None`（M-31 分部收入组合快照；用 `Any` 避免 data→classification 循环 import；默认 None → taxonomy 视为显式 `unavailable`，离线/golden 安全） | 2026-11-14 |
| classification\taxonomy.py (Session #26 / M-31) | 🔧 `build_taxonomy_profile`：`revenue_composition is None` 时改为读取 `getattr(data, "revenue_composition", None) or RevenueComposition.unavailable()`（此前恒 `unavailable`）——消费 providers 落值的分部收入组合 | 2026-11-14 |
| data\providers.py (Session #26 / M-31 + M-35) | 🔧 bottom-up β 块新增分部接线：`SegmentRevenueResolver().get_segments(ticker)`（失败静默 debug → `[]`）→ `to_revenue_composition(...)`（落 `FinancialData.revenue_composition`）+ `segment_weights(...)`（`_cash_to_firm = cash_eq/(mkt_cap+debt)`）→ `derive_bottom_up_beta(..., segments=_seg_weights, segment_cash_to_firm=_cash_to_firm)`；`FinancialData(...)` 构造 +`revenue_composition=revenue_composition_snapshot`；无分部数据时 `segments=None` → 回退公司级（零漂移） | 2026-11-14 |
| tests\test_industry_beta.py (Session #26 / M-35) | 🔧 **32 → 44 用例**（+12 M-35）：`test_segment_weights_sum_beta_unlevered`（0.6·1.2+0.4·0.8）/ `test_segment_audit_breakdown_and_chain_keys` / `test_segment_weights_renormalised_over_resolved_subset` / `test_segment_level_beta_cash_adjust_and_relever` / `test_segment_returns_none_below_min_segments` / `test_segment_returns_none_below_min_coverage` / `test_segment_offline_returns_none` / `test_bottom_up_prefers_segment_branch`（公司级 lister 抛异常证不调用）/ `test_bottom_up_falls_back_to_company_when_segments_unresolved` / `test_default_segment_industry_resolver_keyword_map` / `test_coerce_segments_accepts_pairs_and_objects` / `test_bottom_up_env_disabled_returns_none` | 2026-11-14 |
| data\segment_revenue.py (Session #27) | 🔧 新增 `_FMP_STABLE`（`/stable/revenue-product-segmentation`）+ `_fmp_keys()`（`FMP_API_KEY` 逗号分隔多 key + strip）+ `_from_fmp(url, base_params)`（**多 key 按序轮换**，非 200/不可解析落下一 key，全耗尽 → `[]`）；层优先序改 `_from_fmp_stable` → `_from_fmp_v4` → `_from_fmp_v3`（`_from_fmp_v4`/`_from_fmp_v3` 收敛为薄封装）；`_extract_fmp` 新增 **Shape C** 分支（`first["data"]` 为 dict 时只取嵌套 `data` 的 label→数值，`date` 作 `as_of`，`fiscalYear`/`period` 等元数据不泄漏） | 2026-11-14 |
| data\industry_beta.py (Session #27) | 🔧 `_SEGMENT_INDUSTRY_KEYWORDS` **数据驱动两轮补全**（Round 1 ~40 条业务线词 + Round 2 ~6 条残余可复用词：space/print and publishing/publishing/data processing/energy products/digital experience）；桶/地理/药品品牌名/发行人缩写**恒不映射**（丢弃优先） | 2026-11-14 |
| tests\test_segment_revenue.py (Session #27) | 🔧 新增 Shape C 用例（断言 `"fiscalYear" not in labels` 元数据不泄漏）+ `/stable` 端点优先用例 + 多 key 轮换/空白 strip/全耗尽用例（`_KeyAwareClient`） | 2026-11-14 |
| tests\test_industry_beta.py (Session #27) | 🔧 `test_default_segment_resolver_real_corpus_additions` 增 Round 2 锁定断言（space/publishing/data processing/energy products/digital experience）+ 品牌名/缩写「恒不映射」负向断言 | 2026-11-14 |
| classification\taxonomy.py (Session #28) | 🔧 新增四态决策契约：`DecisionStatus(str, Enum)`（CONFIRMED/PROBABLE/AMBIGUOUS/INSUFFICIENT_DATA）+ `_ECONOMICS_ONLY_MIN_CONF=0.55` + `_DECISION_LABELS`（中文标签）+ `decide_status(conflict_kind, identity_source, *, ml_confidence)`（确定性映射，无标的特例）；`BusinessTaxonomyProfile` +`decision_status` 字段；`audit_lines()` 追加「◆ 决策状态」行；`build_taxonomy_profile()` 计算并传入 `decision_status`；`attach_taxonomy_profile()` 写 `profile.taxonomy_decision_status`（additive shadow，不改路由） | 2026-11-14 |
| data\industry_resolver.py (Session #28) | 🔧 新增 `resolve_identity(ticker) -> Dict[str, str]` 公共方法：返回 `cik`/`sic`/`sic_description`/`sector`/`industry`/`source` 子集（缺失字段省略，**不猜测**）——供 `data/identity_resolver.py` 复用 CIK，避免重复抓取 SEC | 2026-11-14 |
| data\models.py (Session #28) | 🔧 `CompanyProfile` 新增 `taxonomy_decision_status: Optional[str] = None`（位于 `taxonomy_conflict_kind` 与 `taxonomy_audit` 之间，纯 additive shadow 字段） | 2026-11-14 |
| tests\test_taxonomy.py (Session #28) | 🔧 import 新增 `DecisionStatus`/`decide_status`；文件末尾新增 `class TestDecisionContract`（7 用例：insufficient→INSUFFICIENT_DATA / IDENTITY_WINS→AMBIGUOUS / REFINEMENT→PROBABLE / CONSISTENT+structured→CONFIRMED / CONSISTENT+description only→PROBABLE / ECONOMICS_ONLY 依赖 `ml_confidence` / attach 写入 `decision_status`） | 2026-11-14 |
| tests\test_taxonomy.py (Session #29) | 🔧 import 新增 `attach_taxonomy_profile`/`build_taxonomy_profile`；文件末尾追加 `class TestDecisionContractEndToEnd`（6 用例，真实 builder/classifier 全链路）——`test_structured_identity_is_confirmed`（NVDA + Yahoo Semiconductors → `ConflictKind.CONSISTENT` + `DecisionStatus.CONFIRMED` + audit「决策状态…已确认」）/ `test_no_evidence_is_insufficient_data`（空 `FinancialData` → `INSUFFICIENT_DATA` + `identity_key is None`）/ `test_cross_family_conflict_is_ambiguous`（ml_label=BANK vs 半导体 → AMBIGUOUS）/ `test_description_only_identity_is_probable`（「A fabless chipmaker」→ `identity_source=="description"` + PROBABLE）/ `test_attach_propagates_status_to_company_profile`（`attach_taxonomy_profile(data, cp, ml_label=BANK)` → `cp.taxonomy_decision_status == AMBIGUOUS.value`）/ `test_full_pipeline_status_is_valid_across_archetypes`（NVDA/MSFT/JPM/PLD 多原型状态合法） | 2026-11-14 |
| data\segment_revenue.py (Session #30 / M-39) | 🔧 **生产默认源链**：新增模块级 `resolve_segments(ticker, *, client, offline, fmp_cache_path, filing_cache_path, identity_resolver)` —— Layer 1 `SegmentRevenueResolver(...).get_segments(ticker)`（FMP，需 key），非空即返回；Layer 2 **惰性** `from data.filing_evidence import FilingBusinessExtractor`（避免与 `filing_evidence` 循环 import）→ `get_segments()`（SEC 10-K/20-F filing-instance XBRL，免 key），异常/空 → `[]`（绝不伪造）；`__all__` 导出 | 2026-11-14 |
| data\providers.py (Session #30 / M-39) | 🔧 分部收入采集改调 `from data.segment_revenue import resolve_segments, segment_weights, to_revenue_composition` + `_segments = resolve_segments(ticker)`（替换直接构造 `SegmentRevenueResolver`）→ FMP 无 key / key 失效 / 额度耗尽 / ticker 未覆盖时**自动降级**到 SEC 一手分部；仍为 shadow 数据填充（不入 `business_type`/路由） | 2026-11-14 |
| classification\taxonomy.py (Session #30 / M-32) | ✨ 新增路由门控：`TAXONOMY_ROUTING_STATUSES = frozenset({DecisionStatus.CONFIRMED})` + `_archetype_family_index()`/`ARCHETYPE_FAMILIES`（由 `IDENTITY_NODES` 树推导，archetype↔node tree 不漂移）+ `same_identity_family(internal_bt, taxonomy_key)` + `taxonomy_routing_override(internal_bt, taxonomy_key, decision_status=None, *, guard_blocked=False)`（三道 gating：① decision_status ∈ TAXONOMY_ROUTING_STATUSES；② canonical 身份与**内部身份判定**跨 identity family 冲突；③ `guard_blocked=False`）；`attach_taxonomy_profile(..., tp=...)` 复用已构建的 `BusinessTaxonomyProfile`（避免重复构建）；`__all__` 追加 4 个符号 | 2026-11-14 |
| classification\classifier.py (Session #30 / M-32) | 🔧 `_model_applicability()` 之前构建 `_taxonomy = build_taxonomy_profile(data)`，调用 `taxonomy_routing_override(best_bt, _taxonomy.identity_key, _taxonomy.decision_status, guard_blocked=...)`；gate 通过 → `routing_bt = _tax_bt` + `_routed_business_type = _tax_bt` + reasons 记录跨族冲突；`attach_taxonomy_profile(data, profile, tp=_taxonomy)`；新增 `_asset_light_guard_blocked()` staticmethod（复用 `ASSET_LIGHT_TYPES`/`ASSET_LIGHT_CONFLICT_CAPEX_RATIO`）。**关键**：对比 `best_bt`（身份判定）而非 `routing_bt`（Phase 1.3 保守估值路由） | 2026-11-14 |
| classification\ml_classifier.py (Session #30 / M-32) | 🔧 ML 路径对称 gate：`taxonomy_routing_override as _taxonomy_routing_override`；economics 用 **raw ML top-1**（`raw_ml_snapshot`，预 sector 硬规则）；`_routed_business_type = best_bt` → gate 通过 → `effective_bt = _tax_bt` / `_routed_business_type = _tax_bt`；`business_type=_routed_business_type.value` | 2026-11-14 |
| tests\test_taxonomy.py (Session #30 / M-32) | 🔧 文件末尾新增 `class TestTaxonomyRoutingGate`（12 用例）+ tension basket（ORCL/NBIS/CRWV：`taxonomy_identity_key=="tech.software.infra"` 但 `business_type=="MatureTech"`）——锁定：非 CONFIRMED 不覆盖 / 同族不覆盖 / 跨族才覆盖 / 经济护栏拦截 / `ASSET_LIGHT_TYPES` × capex 边界 | 2026-11-14 |
| valuation\wacc.py (Session #34 / P0-1 + P0-2) | 🔧 **P0-1**：`INDUSTRY_WACC_RANGES` 关键词 `"Utility"`→`"Utilities"`（保留单数兼容）；新增 `CANONICAL_KEY_WACC_RANGES`（`util`/`util.electric`/`util.gas`/`util.water`/`util.ipp`/`util.diversified`/`en.oil_gas.integrated` 各自独立区间）+ `_normalize_industry_text()`（em/en dash + 连字符空格归一化）；`_match_industry_range()` 返回 4 元组（+`source`）并改四级优先级（canonical key（profile）→ `node_from_yahoo()` → 关键词表 → 默认）；`WaccBreakdown` +`industry_range_source`。**P0-2**：`_effective_tax_rate()` 改非重叠期间（TTM-only / 去重财年 / 默认），返回 3 元组（+`tax_period_basis`）落 `WaccBreakdown.tax_period_basis` | 2026-11-14 |
| models\base.py (Session #34 / P0-3) | ✨ 新增 `class ShareCountBasis(str, Enum)`（BASIC/DILUTED/TTM/MARKET/UNKNOWN）+ `@dataclass ShareCount`（`shares_used`/`source`/`as_of`/`basis`/`reliable` + `as_dict()`）+ `make_share_count(shares, source, basis, as_of=None, reliable=True)`；`ValuationResult` +`share_count: Optional[ShareCount] = None`；`__all__` 追加 3 符号 | 2026-11-14 |
| models\dcf.py (Session #34 / P0-3) | 🔧 导入 `ShareCountBasis`/`make_share_count`；`pps = equity_val / shares` 后构造 `_share_count`（ForecastPeriod 末期 → TTM → Unknown 三档来源）；`breakdown["share_count"]` + 返回值 `share_count=_share_count` | 2026-11-14 |
| models\reverse_dcf.py (Session #34 / P0-3) | 🔧 最终 `ValuationResult` 新增 `share_count=make_share_count(shares, "TTM 财务报表股数", ShareCountBasis.TTM, ttm.period_end)` | 2026-11-14 |
| models\multiples.py (Session #34 / P0-3) | 🔧 新增 `_market_or_ttm_shares()` 辅助；各分支登记 `_sc_shares/_sc_basis/_sc_src/_sc_asof`（P/E→TTM、EV/EBITDA/EV/Sales/FCF Yield→Market-or-TTM、P/B→MARKET）；`breakdown["share_count"]` + 返回值 `share_count=_share_count` | 2026-11-14 |
| models\sotp.py (Session #34 / P0-3) | 🔧 `shares` 解析后按 MARKET/TTM/UNKNOWN 构造 `_share_count`；`breakdown["share_count"]` + 返回值 `share_count=_share_count` | 2026-11-14 |
| analysis\model_agreement.py (Session #34 / P0-3) | 🔧 导入 `SHARE_COUNT_COMPARABLE_TOL`；`ModelAgreement` +5 字段（`share_count_reference`/`share_count_reference_source`/`share_count_bases`/`share_incomparable_models`/`share_count_excluded_models`）；新增 `@staticmethod _resolve_share_reference(data, solved, results)`（`market_cap ÷ current_price` → MarketData 流通股 → TTM → 模型声明中位数）；`analyze()` 新增 P0-3 协调块（`solved_agg` 剔除不可比 → 驱动 `_independent_evidence`/`_iqr_filter`/`all_vals`；`n_applicable` 扣减）+ 2 条 notes | 2026-11-14 |
| analysis\risk.py (Session #34 / P0-4) | 🔧 `_forecast_risk()` Layer B **非对称方向感知重写**（替换对称 `abs(fcf_yield-0.04)/0.04`）：正 FCF ≥ 参考 → 不判风险；正 FCF < 参考 → materiality gate 后仅估值观察 Low；负 FCF → 按恶化幅度与持续性（`_fcf_trend()`）评估；新增 `_downgrade()`（风险等级可降不可凭偏差升）；`reference=th.get("fcf_yield_reference", 0.04)` | 2026-11-14 |
| config.py (Session #34 / P0-3 + P0-4) | 🔧 `RISK_THRESHOLDS[RiskType.FORECAST]` +`fcf_yield_reference`/`positive_fcf_gap_medium`/`positive_fcf_gap_high`/`fcf_decline_medium`/`fcf_decline_high`/`fcf_decline_consecutive`；模块级新增 `SHARE_COUNT_COMPARABLE_TOL=0.10` + `__all__` 导出 | 2026-11-14 |
| tests\golden_report.py (Session #34 / P0-3) | 🔧 `build_fingerprint` 新增指纹字段 `share_ref_source` / `share_count_excluded`（把股数口径契约纳入回归保护） | 2026-11-14 |
| tests\golden\report_fingerprints.json (Session #34) | 🔧 因 P0-4（FCF 旗标移除/降级）与 P0-2（ETR→WACC→DCF 中位微调）**有意重生成一次** —— 差异逐条核对为预期行为修正 | 2026-11-14 |
| models\sotp.py (Session #35 / P1-SOTP) | 🔧 **全量重写**：三态常量 `SOTP_SOLVED`/`SOTP_APPROXIMATE`/`SOTP_INSUFFICIENT` + `SOTPSegment` dataclass（`is_independent_evidence()`/`as_dict()`）；`_derive_segments_from_profile` 不再用自身 EV/Revenue 制造循环估值——仅真实分部财务 → SOLVED；仅 ML 暴露度 → INSUFFICIENT + `breakdown["display_only"]=True`（剔除共识）；`breakdown["segments_detail"]` 输出每分部 Revenue/EBITDA/Applied Multiple/Segment EV/Source/Confidence/As-of Date；修复 operating_ev 双重扣净债 bug；`comparability` 仅 SOLVED 时 `peer_valid=True` | 2026-11-14 |
| valuation\wacc.py (Session #35 / P1-6) | 🔧 多窗口 β 稳定性**参与估计**：`beta_windows` 极差 → Blume-style 收缩（`BETA_MAX_SHRINK=0.35`、`BETA_DISPERSION_SHRINK_THRESHOLD=0.50`，**不取平均**，向 β=1.0 收缩）；`WaccBreakdown` 新增 `beta_raw`/`beta_selected`/`beta_adjusted`/`beta_shrinkage`/`beta_dispersion`/`beta_uncertainty`；β 不确定性传导 → `wacc_beta_lo`/`wacc_beta_hi` | 2026-11-14 |
| reporting\dashboard.py (Session #35 / P1-7) | 🔧 `_market_section()` ETR 主值改 **WACC 实际使用 ETR**（`wacc_bd.effective_tax_rate`）+ `_etr_basis_suffix()` 标注 `tax_period_basis`；供应商 ETR 另标 **Provider ETR**（消除双数字） | 2026-11-14 |
| models\base.py (Session #35 / P1-8) | ✨ 新增 `make_comparability(value_basis, currency, financial_period, valuation_date, peer_valid)`（日期归一化 ISO）+ `ValuationResult.comparability: Dict`；`__all__` 追加符号 | 2026-11-14 |
| models\dcf.py (Session #35 / P1-8) | 🔧 `calculate()` 返回值新增 `comparability=make_comparability(...)`（TTM / equity_per_share / USD） | 2026-11-14 |
| models\multiples.py (Session #35 / P1-8) | 🔧 各倍数模型返回值新增 `comparability=make_comparability(...)`（TTM / equity_per_share / peer_valid=True） | 2026-11-14 |
| analysis\model_agreement.py (Session #35 / P1-8) | ✨ 新增 **Valuation Comparability Gate**：`_as_iso_date()`/`_days_between()` + `ModelAgreementAnalyzer._comparability_gate()`（7 维：币种/口径/财务期间/估值日期/peer_valid/数据质量）+ `ModelAgreement` 新增 `comparability_reference`/`comparability_conflicts`/`comparability_excluded_models`；`analyze()` 剔除冲突模型并重算 `n_applicable`（未声明口径不排除） | 2026-11-14 |
| tests\test_special_models.py (Session #35) | 🔧 `test_sotp_model_runs` 重写为三态契约（无分部数据 → INSUFFICIENT + display_only + `n_independent_segments==0`；外部 segments → SOLVED + `n_independent_segments==2`） | 2026-11-14 |
| tests\test_model_agreement.py (Session #35) | ✨ 新增 `TestComparabilityGate`（8 用例：币种冲突剔除/未声明不剔除/peer 无效/陈旧估值日期/财务期间冲突/低数据质量/无数据无 Gate） | 2026-11-14 |
| tests\golden\report_fingerprints.json (Session #35) | 🔧 因 SOTP→display_only **有意重生成一次**（PLD/NOW/NBIS/CRWV/NU：`n_solved` −1、`n_display_only` +1、`n_independent_evidence` −1，逐条核对为预期） | 2026-11-14 |
| analysis\model_agreement.py (Session #37) | 🔧 `_resolve_share_reference` 股数反查：getattr 链式守卫列表推导 → **显式 for 循环 + None 收窄**（`res`/`sc`/`shares` 逐层判空）；消除 `reportArgumentType`(float(None)) + `reportOptionalMemberAccess` | 2026-11-15 |
| classification\taxonomy.py (Session #37) | 🔧 `build_taxonomy_profile` 构造 profile 时 `revenue_composition or RevenueComposition.unavailable()`——参数声明为 `Optional[RevenueComposition]`，`or` 收窄为 `RevenueComposition` | 2026-11-15 |
| data\segment_revenue.py (Session #37) | 🔧 `to_revenue_composition`：`usable` 改 `List[Tuple[Segment, float]]`（遍历时 `isinstance(rev,(int,float)) and rev>0` 收窄并 `float(rev)` 落库）；`total`/`pct` 直接取已收窄的 float，消除 `float(Optional)` | 2026-11-15 |
| data\industry_beta.py (Session #37) | 🔧 `_coerce_segments`：`if not label or weight is None: continue`（`weight` 来自 `Any` 元组元素，`float(weight)` 前显式排除 None） | 2026-11-15 |
| models\reverse_dcf.py (Session #37) | 🔧 反向 DCF 上下限：`bt_params.get()` 返回值类型为 `_Opt[float]`，`.get(k, default)` 仍带 `None` → 改**显式 None 判定**（`_min_cagr if _min_cagr is not None else rcfg.…`），消除传入 `_project_ev`/`_normalized_growth_solve` 的 `float | None` | 2026-11-15 |
| data\providers.py (Session #37) | 🔧 分部收入 import（`resolve_segments`/`segment_weights`/`to_revenue_composition`）**移出 try**——import 本不会因网络失败；消除 `reportPossiblyUnboundVariable`（`_segments` 求解仍保留 try/except 优雅降级） | 2026-11-15 |
| data\sic_map.py (Session #37) | 🔧 `map_sic_to_yahoo` / `_normalize_sic` 入参放宽为 `Optional[Union[str, int]]`（函数本就 `str(sic)` 归一；测试断言 int 与 str 等价）；`typing` 增加 `Union` | 2026-11-15 |
| data\akshare_provider.py (Session #37) | 🔧 可选依赖 `akshare` 三处 import 加 `# pyright: ignore[reportMissingImports]`（已被 `try/except ImportError` 守卫，缺失属预期） | 2026-11-15 |
| tests\test_industry_beta.py (Session #37) | 🔧 `**kwargs`/`**base` 展开的 `dict()` 加 `Dict[str, Any]` 标注（消除异构 dict 解包的误报）；两处 `assert res.segments is not None` 收窄 Optional 字段；`typing` 增加 `Any, Dict` | 2026-11-15 |
| config.py (Session #38 / Phase 1-5) | ✨ 新增 `CURRENCY_RISK_FREE_RATES`（USD/HKD/CNY/MYR/EUR/GBP/JPY/SGD 主权 10Y 锚）+ `CURRENCY_NOMINAL_GDP`（各币种名义 GDP 上限）+ `DEFAULT_MACRO_CURRENCY="USD"`；`__all__` 导出 | 2026-11-15 |
| data\models.py (Session #38) | 🔧 `MarketData` 承载 `beta_provenance` / `risk_free_source` / `currency` / `minority_interest` / `preferred_equity` / `non_operating_assets` / `leases_in_debt` 等桥接与溯源字段（供 EquityBridge 与 β 溯源消费） | 2026-11-15 |
| data\providers.py (Session #38 / Phase 1-2) | 🔧 `_estimate_beta()` 回归改用 **`adjclose` 复权价**（raw close 仅回退）+ **日期连续性检查**（ISO-week/period keying 记 `missing_periods`）+ 返回 provenance dict（`window_label`/`price_basis`/`benchmark`/`window_start`/`window_end`/`n_observations`/`missing_periods`）；`_estimate_beta_windows()` 逐窗口 provenance | 2026-11-15 |
| valuation\wacc.py (Session #38 / Phase 1-1·5·6) | 🔧 ① β 溯源：删除硬编码「3Y monthly vs SPY」，新增 `_format_beta_source(prov, beta_value)` 按 provenance 如实渲染（regression/provider/unverified 三态）；② 币种感知 Rf：新增 `currency_macro_anchors()` + Rf 四级优先级（注入值仅在币种一致/provenance 非 USD 时保留 → 活 U.S. Treasury 仅 USD → 币种主权锚 → 默认），USD 来源 Rf 用于非 USD 现金流时**显式替换并记 `sources["Rf (currency)"]`**；③ WACC raw/clamp 分离：`WaccBreakdown` 新增 `wacc_raw`/`wacc_clamped`/`wacc_clamp_reason` + `wacc_clamp_note()`，`sources` 追加「WACC (raw) model-computed (pre-clamp)」+ 钳制原因 | 2026-11-15 |
| valuation\terminal_growth.py (Session #38 / Phase 1-5) | 🔧 GDP 上限随**现金流币种**动态调整：`calculate()` 新增 `nominal_gdp_ceiling` 形参（默认由 `data.market.currency` 经 `CURRENCY_NOMINAL_GDP` 推导）；USD 保持 `LONG_TERM_NOMINAL_GDP=0.045`（golden 零漂移），非 USD 取对应上限；`hard_cap`/`high_exceeds_gdp` 改用币种上限；`derivation_trace` 新增 `long_term_nominal_gdp`/`gdp_ceiling` | 2026-11-15 |
| models\dcf.py (Session #38 / Phase 1-3) | 🔧 EV→Equity 改走 `enterprise_to_equity(ev, data.market)`（不再内联 `ev - net_debt`）；`breakdown` 新增 `equity_bridge` 明细 | 2026-11-15 |
| models\reverse_dcf.py (Session #38 / Phase 1-3·4) | 🔧 目标 EV 由 `target_equity + net_debt` 改 `equity_to_enterprise(target_equity, data.market)`（与桥同源）；接入 SBC 归一化（`normalize_fcf_for_sbc` + `stock_based_compensation`）→ `assumptions["SBC Adjustment"]` + `breakdown["sbc_normalization"]` | 2026-11-15 |
| models\multiples.py (Session #38 / Phase 1-3) | 🔧 EV 家族（EV/EBITDA、EV/Sales）股权价值改走 `enterprise_to_equity()`；`breakdown` 新增 `equity_bridge` | 2026-11-15 |
| models\sotp.py (Session #38 / Phase 1-3) | 🔧 `equity_value` 改走桥接（`enterprise_to_equity`）；自举 EV 改 `equity_to_enterprise(mkt.market_cap, mkt)`；`notes` 追加「EV→Equity 桥接」；`breakdown` 新增 `equity_bridge` | 2026-11-15 |
| models\unit_economics.py (Session #38 / Phase 1-3) | 🔧 股权价值（含敏感性）改走 `enterprise_to_equity()`；`breakdown` 新增 `equity_bridge` | 2026-11-15 |
| models\nav.py (Session #38 / Phase 1-3) | 🔧 NAV 股权价值（含 cap-rate 敏感性）改走 `enterprise_to_equity()` | 2026-11-15 |
| forecasts\fcf_projection.py (Session #38 / Phase 1-3) | 🔧 投影股权价值改 `enterprise_to_equity(proj.enterprise_value, data.market)`（不再内联 `− net_debt`） | 2026-11-15 |
| tests\test_terminal_growth.py (Session #38 / Phase 1-5) | ✨ 新增 `TestCurrencyAwareGDPCeiling`（6 用例：USD 0.045 / CNY 0.055 / JPY 0.015 / 未知币种回 USD / 显式 override / 跨币种 Low<Base<High 不变量）+ `_with_currency()` helper | 2026-11-15 |
| analysis\divergence.py (Session #40 / M-67) | 🔧 `_fcf_margin_check()` 诊断带由全局常量改为**按业务原型校准**：新增 `_calibration_for_profile()`（内部 `business_type_from_profile` → `calibration_for()`）；比较改用 `cal.fcf_flag_pp` / `cal.fcf_aligned_pp` / `cal.fcf_high_ratio`；三处 detail 追加审计行 `〔行业校准[tier]（观测 σ, n）：FCF margin 带 Xpp/Ypp/Z×，β 最小同业 N 家；rationale〕`；`DEFAULT_CALIBRATION` 导入（模块级三常量保留为向后兼容缺省） | 2026-11-15 |
| valuation\wacc.py (Session #40 / M-67) | 🔧 `_bottom_up_reliability_label()` 新增 `business_type` 形参（调用点 `getattr(profile, "business_type", None)`）；β 最小同业地板由 `BETA_BOTTOM_UP_MIN_PEERS` 单值改为 `beta_min_peers_for(business_type)`（宽池 5 / 窄池 3 / 未知 4）；**惰性 import** 该函数（模块级 import 触发 `models.dcf → valuation.wacc → analysis → analysis.expectation → models.reverse_dcf → models.dcf` 循环依赖） | 2026-11-15 |
| data\fcf_utils.py (Session #40 / M-69) | ✨ 确立**双函数出口**：`resolve_ttm_fcf()`（raw primitive，仅存在性检查，不施加 SBC）+ 新增 `resolve_ttm_fcf_normalized(stmt, *, shares, method)`（value producer，调用 `normalize_fcf_for_sbc()` **恰好一次**，生效加 `+sbc_normalized` 后缀，`raw is None → (None,"missing",…)` 不臆造零）；`__all__` 导出两函数；模块 docstring 说明「单一出口杜绝 SBC 双计」 | 2026-11-15 |
| models\reverse_dcf.py (Session #40 / M-69) | 🔧 TTM FCF 改经 `resolve_ttm_fcf_normalized(ttm, shares=shares)` **单次归一化**（消除自身直接调用 `normalize_fcf_for_sbc` 的重复施加路径）；breakdown 落 `base_fcf` / `fcf_source` / `sbc_normalization`；注释 ID M-68 → M-69 | 2026-11-15 |
| models\multiples.py (Session #40 / M-69) | 🔧 FCF Yield 分支改经 `resolve_ttm_fcf_normalized()`；**保留 Phase D 守卫**（`ttm is None or ttm.free_cash_flow is None → INSUFFICIENT_DATA`）；`fcf_used = sbc_norm.adjusted_fcf if sbc_norm.fcf_available else raw_fcf`；breakdown 落 `sbc_normalization` / `fcf_source` / `fcf_used`；注释 ID M-68 → M-69 | 2026-11-15 |
| tests\test_reporting_integrity_repair.py (Session #40 / M-67 + M-69) | ✨ 追加 `TestCrossIndustryThresholdCalibration`（9 用例：tier 单调 / archetype 解析 / 带随波动放大 / 未知回退默认带 / β 地板随池广度 / 同缺口跨行业差异判级 / 审计行含校准证据 / `_bottom_up_reliability_label` 原型感知）+ `TestSbcMainChainExit`（6 用例：raw primitive 不施加 SBC / normalized 扣减一次 / derived FCF 亦归一化 / SBC 缺失不动 FCF / 缺失 FCF 不臆造零 / `ReverseDCFModel` 恰好扣一次）；注释 ID M-68 → M-69 | 2026-11-15 |

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
4. **主语不自包原则**：detail 字段是自包含完整句（"当前价 $15.58 较中位估值 $11.01 高出 +41.6%"），外层渲染时不要再包一层前缀（如「（中位估值 ...）」），否则会出现「中位估值较中位估值」的主语重复 bug

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

## Decision 024: 负终期 FCF 严禁符号翻转——终值抑制 + 显式命名（不得伪造正终值）

Reason: `fcf_projection.py` 曾以 `if last_fcf <= 0: last_fcf = avg_abs(...)` 把负终期 FCF **偷改成正数**再进 Gordon → 为持续烧钱公司伪造正终值（三处复制：Normal DCF / Reverse DCF / Monte Carlo）。

原则：**引擎不得为了让估值好看而伪造输入**。终期 FCF ≤ 0（含 None）时：
1. `gordon_terminal_value()` 返回抑制态（`terminal_value=0`、`pv_terminal_value=0`、`suppressed=True`），估值退化为**显式期现值下限**；
2. `terminal_fcf_negative=True` + `SolverStatus.APPROXIMATE` + note「需明确转型假设」；
3. 唯一的 Gordon 入口，`dcf.py::_pv_calculations`/`_pv_tv_only` 全部改调它；
4. 风险层新增显式 HIGH 旗标分支（抑制后 `tv_percent_of_ev=0`，原阈值不触发）。

Date: 2026-11-12  (ADR-028)

---

## Decision 025: 预测年限单一真源 `resolve_forecast_horizon()`——禁止实例级状态污染

Reason: `reverse_dcf.py` 的 `self.horizon = int(horizon)` 写回 `NAME_TO_MODEL` **共享单例** → SaaS(7)→Utilities(10)→Unknown **沿用 10**（跨标的污染）。且各 FCF 消费方各自回落本地常量，年限口径可能不一致。

原则：**年限 = 按 business_type 解析的纯函数**。新增 `config.resolve_forecast_horizon(business_type)`；删除 `self.horizon`，每次 `calculate()` 解析局部值；DCF/ReverseDCF/Scenario/Sensitivity/MonteCarlo/Expectation 全链路统一；DCF 与 ReverseDCF 年限必须一致。

Date: 2026-11-12  (ADR-029)

---

## Decision 026: 隐含期望用「约束式单变量求解」——硬边界不钳制 + 单调性 + 残差检查，禁止联合求解

Reason: Session #16「问题 2」指出 Reverse DCF 只反推 Revenue CAGR，「问题 4」指出 FCF Margin 非独立变量。要回答「若其它条件不变，当前价隐含的 X 是多少」，需扩展为多驱动反解。

原则：
1. **单变量 one-at-a-time**（非联合求解）：一次只解一个隐含值，其余假设固定为基准。一方程多未知数联合求解**欠定**（无穷多解）→ 不做，报告中每个数值均显式标注「其余假设固定为基准」。
2. **硬边界约束**：目标超出 `[lo, hi]` 可达区间时返回 `SolverStatus.NO_SOLUTION_IN_RANGE` 并 `note` **指名绑定边界**，**绝不静默钳制到边缘**（钳制会输出一个「假的可行解」）。
3. **单调性约束**：`increasing` 决定可达端（margin/CAGR/tg 越高 EV 越大；WACC 越高 EV 越小）。
4. **残差检查**：`rel_residual > implied_residual_tol(1e-3)` → 降级 `APPROXIMATE`（EV 曲面平坦 → 多解风险）。
5. **一致性下限**：`implied_wacc` 下界 = `max(implied_wacc_lo, tg + MIN_WACC_TG_SPREAD)`；`implied_terminal_growth` 上界 = `min(implied_tg_hi, wacc − MIN_WACC_TG_SPREAD)`。
6. **FCF margin 独立化**：新增 flat-margin 桥 `project_enterprise_value_flat_margin()`（`FCF_t = revenue_t × fcf_margin`），绕过 NOPAT/DA/CapEx/NWC 桥，使 FCF margin 成为良定义独立求解目标。
7. **落字段契约**：`ImpliedSolve`（`value`/`status`/`residual`/`rel_residual`/`bound_lo`/`bound_hi`/`note`）→ `breakdown["implied_expectations"]` → `ImpliedExpectations` → 渲染层（禁止渲染层猜口径）。

Date: 2026-11-12  (ADR-030)

---

## Decision 027: 求解器「根的真实性」优先——有效 bracket 重校验 + 实测单调性 + 多根/常数检测 + 终值抑制贯穿

Reason: 用户对 `models/reverse_dcf.py` / `forecasts/fcf_projection.py` 的静态代码审查指出 6 项风险（3×P0 + 3×P1）。核心是：**错误的根会被报告误当真实市场隐含预期**——求解器绝不能返回「看似正常」但实为无根区间里的可疑解。

原则：
1. **有效 bracket 重校验**：`_finish_root()` 内 `brentq` 失败后若 `f(a)·f(b) > 0` → `NO_SOLUTION_IN_RANGE`（拒绝可疑根）；无论走哪条路径，求解后一律计算 residual，`rel > implied_residual_tol` → 降级 `APPROXIMATE`。
2. **单调性必须实测**：`implied_monotonic_samples=21` 点采样验证声明方向；非单调 → `_root_brackets()` 扫描变号区间（0 → 无解 / 1 → 求解 / >1 → `MULTIPLE_ROOTS`）；步长级平坦 → `NON_MONOTONIC`。单调性容差用**步长尺度** `mono_tol = 1e-6·f_span`（**不得**复用被 `|target|` 放大的残差容差）。
3. **常数目标检测**：`fmax − fmin ≤ abs_tol` → 命中目标 `FLAT_OBJECTIVE` / 不命中 `NO_SOLUTION_IN_RANGE`，**绝不**输出无意义隐含值。
4. **端点根合法**：`|ev_endpoint − target| ≤ abs_tol` → 边界解 `SOLVED`（`ev_lo==target` / `ev_hi==target` 不再误判无解）。
5. **终值抑制贯穿**：`terminal_fcf_negative` 纳入 `breakdown` 与 `breakdown["implied_expectations"]`；`_finalize_revenue_cagr()` 在终期 FCF ≤ 0 时 `SOLVED → APPROXIMATE` + 「Terminal Value Suppressed — Turnaround Assumption Required」；含「原始 CAGR 无投影时从 implied 块回填」；期望层 + 渲染层透出。
6. **可达区间语义**：`lo_val/hi_val` 恒为 `(fmin, fmax)`（与方向无关），仅交换 `x_at_max/x_at_min`——避免递减方向赋值反转。

Date: 2026-11-12  (ADR-031)

---

## Decision 028: Rf 单一真源 + Terminal Growth 三档「经济学含义」重定义——GDP 上限只约束 Base，乐观 High 必须显式标注为情景

Reason: 用户静态审查 `valuation/wacc.py` / `valuation/terminal_growth.py` / `models/dcf.py` 指出 2 项 P0（并强调「这是实际代码问题，不是推测」）。两项都是**同一报告内部口径不一致**：一个 Rf 有两个来源、一个「终值增长率」有两种经济学含义却被混用。

原则：
1. **Rf 单一真源（Cost of Debt 不得自行取 Rf）**：`calculate()` 已按「MarketData → TreasuryYieldProvider → config」解析出唯一 `rf`；`_implied_cost_of_debt(data, risk_free_rate=rf)` 必须**接收**该值，所有债务成本 fallback（TTM 隐含 / 合成信用评级 / BBB-like）与 CAPM 共用同一 Rf。**禁止**在 helper 内重新 `getattr(mkt, "risk_free_rate", ...)`——否则 MarketData Rf 为空时，ke 用 Treasury 5.103% 而 kd 用配置默认 4.50%，同一报告出现两个无风险利率。
2. **Terminal Growth 三档经济学含义重定义**：长期名义 GDP（4.5%）是**可持续终值增长率**的上限，只约束作为「长期稳定终值增长率」的 **Base**（基准估值使用）；**Low = 保守情景、High = 乐观情景**，是**情景区间**而非长期稳定终值增长率。
3. **不机械强制 High < GDP，但必须诚实标注**：High 允许高于长期 GDP（否则 Base=4.5% 时 High 会塌缩为 Base，丧失情景区分度），但它**仅受 Gordon 稳定上限 WACC−0.5% 约束**，且当 `high > LT nominal GDP` 时必须打旗标（`high_exceeds_gdp=True`）并在推导追踪 / DCF 假设说明 / 渲染处**显式标注为「乐观情景，非长期稳定终值增长率」**——**绝不**把它误称为长期可持续终值增长率。
4. **渲染契约化**：`BAND_LABELS` / `high_exceeds_gdp` / `gdp_ceiling` 是引擎输出的语义契约；渲染层（`models/dcf.py` / `reporting/dashboard.py`）**消费**引擎旗标与标签，禁止硬编码或猜测口径词。

Date: 2026-11-13  (ADR-032)

---

## Decision 029: Quality-Weighted Median 采用标准 midpoint 定义——等权时必须精确退化为普通中位数

Reason: 用户静态审查 `analysis/model_agreement.py` 指出 P1 边界缺陷。原 `_weighted_median()` 逐值累加权重，返回**首个累计权重 ≥ total/2 的值**。当所有模型权重相等（常见：多个 SOLVED 模型权重均为 1.0）且求解模型数为**偶数**时，累计权重恰在第 n/2 个值处达到 total/2，于是返回第 n/2 个值——而普通中位数是 `mean(values[n/2-1], values[n/2])`。AAPL 报告中「普通中位数 176.12 vs 加权中位数 165.24」即为此症状。

原则：
1. **midpoint 定义**：加权中位数 = (下加权中位数 + 上加权中位数) / 2。下加权中位数 = 升序累加权重首个 ≥ total/2 的值；上加权中位数 = 降序（对称）累加权重首个 ≥ total/2 的值。
2. **等权退化不变量**：当所有权重相等时，该定义**精确等于**普通中位数（偶数取中间两值平均、奇数取正中值）——这是可测试的硬不变量。
3. **权重卫生**：负权重钳制为 0；权重缺失默认 1.0；total ≤ 0（含全零权重）→ 返回 `None`；空输入 → `None`。
4. **单元测试覆盖**：偶数/奇数等权、不等权（重权主导 / 精确半权平局 / 无平局）、零权重剔除、全零返回 None、负权重钳制、缺失权重默认、空输入。

Date: 2026-11-13  (ADR-033)

---

## Decision 030: Monte Carlo 必须是「DCF 假设的扰动分布」而非独立证据；情景必须拆分经营/折现口径

Reason: MSFT 报告暴露「MC 中位 $255.70 远低于确定性 DCF $170.70 却 CV 仅 6.6%」无法解释——根因是 MC 用**独立于确定性 DCF 的粗糙分布**（历史统计 + 人为 +2% 利润率地板），且经营驱动情景与折现率情景被混在同一区块。

原则：
1. **MC 双模式（ADR-034）**：`base_case`（以确定性 DCF 同一 base 预测为中心，仅扰动假设）/ `historical`（历史分布，完全独立）；无 DCF 锚点（金融股 RIM/DDM 或无解）时**自动回退 historical 并附说明**，不静默。
2. **零扰动锚点 = 确定性 DCF**：路径形参化（`_base_case_path()` + `_project_one_path()`）在零扰动处**精确复现** DCF base FCF 路径（MSFT/AAPL/NBIS 差 +0.0%）；负股权沿用 DCF「归零」约定。
3. **禁止人为利润率地板**：取消 `max(om, +2%)`，允许负利润率（如实反映亏损期标的）；驱动边界全部可配置。
4. **经营/折现情景拆分（ADR-035）**：`ScenarioValuation.scenario_kind`（`discount_rate` / `operating` / `financial`）+ `drivers`；报告拆两区块；金融股经营情景返回 `{}`。
5. **报告透明化**：MC 区块披露模式/种子/请求数/有效数/无效数/截断数/参数分布/相关矩阵；标注「这是 DCF 假设的扰动分布，不是独立估值证据」；`P(股权归零/破产)` → 「Equity Value Wipeout Probability」（方向基准为 equity value 归零）。

Date: 2026-11-13  (ADR-034 / ADR-035 · Session #20)

---

## Decision 031: β 必须暴露多窗口敏感性；同源模型族不得作为「多条独立证据」；peer 倍数来源须可审计

Reason: 单一回归 β 掩盖估计不稳；`P/E`↔`Historical Multiples`、`EV/Sales`↔`EV/Sales (Unit Econ)`、`DCF`↔`ReverseDCF` 等**同源证据被重复计票**抬高一致性门控；peer 倍数来源（精确行业/回退/近似）与样本数缺失不可审计。

原则：
1. **β 多窗口（ADR-036）**：`MarketData.beta_windows`（2Y 周/3Y 月/5Y 月）+ `industry_beta`（bottom-up 槽位，缺失即 `None`，绝不伪造）；`beta_window_note()` 在 <2 窗口时返回 `None`，极差 >0.50 标注「窗口间波动较大」；**多窗口为独立审计输入，不覆盖 CAPM 标量 β**。
2. **同源证据去重（ADR-037）**：`_MODEL_FAMILY` 归并 + `_independent_evidence()`；覆盖率门控按**独立证据数**（而非解算模型数）计票；`ModelAgreement` 披露 `n_independent_evidence` / `duplicate_evidence_groups`。
3. **peer 来源溯源**：4 档封闭集 `PEER_SOURCE_EXACT_INDUSTRY` / `SECTOR_FALLBACK` / `BUSINESS_TYPE_FALLBACK` / `APPROXIMATE` + `peer_sample_size`；缺失样本数不得静默。
4. **渲染契约化**：dashboard 消费引擎输出的 `peer_source_kind` / `beta_window_note()`，不在渲染层硬编码口径词。

Date: 2026-11-13  (ADR-036 / ADR-037 · Session #21)

---

## Decision 032: 引入「内部标准 Taxonomy + 五维公司拆解」——经济学特征只能族内细化 Identity，严禁跨族决定（黄金法则）

Reason: 此前 Business Identity 依赖 Yahoo industry 与 ML 标签的临时冲突规则，口径分散、无标准树、易被财务经济特征（高毛利/高 CapEx/低负债）误导。例如一家经营大型 AI 数据中心的 Software/Cloud 公司，其经济特征与半导体厂商高度相似，若允许 economics 直接决定 identity 会被误判为 Semiconductor。

原则：
1. **五维分离**：① Business Identity（公司实际做什么）/ ② Business Model（怎样赚钱）/ ③ Revenue Composition（收入来自哪里 + 数据日期）/ ④ Economic Profile（毛利率/经营利润率/CapEx÷营收/FCF Margin/Recurring/Debt）/ ⑤ External Classification（Yahoo/GICS/NAICS/ML，**原样保留，不覆盖内部判断**）。
2. **黄金法则（最重要）**：财务经济特征只能**在同一 family 内细化** identity；**跨族一律不提升**；同族兄弟冲突收敛至 **common ancestor**（绝不用经济学节点冒充 Identity）。由 `economic_identity_ceiling()` + `common_ancestor()` 实现。
3. **标准树单一真源**：`classification/taxonomy.py::IDENTITY_NODES`（99 节点，canonical 点分 key + parent + archetype）；`depth` 由 **parent 链**推导（非点计数，分组节点子节点与父同深）。
4. **冲突分级 `ConflictKind`**：CONSISTENT / REFINEMENT / IDENTITY_WINS / ECONOMICS_ONLY / INSUFFICIENT + `taxonomy_audit` 留痕。
5. **外部标签映射**：`node_from_yahoo()` 两段式 **longest-key-wins**（industry 优先 → sector → sector→family 兜底）。
6. **additive shadow 接线**：仅写入 `CompanyProfile` 8 个 shadow 字段，**不改 `business_type` / `applicable_models` / 路由**（golden 零漂移），切换为参与路由须单独审阅（M-32）。

Date: 2026-11-14  (ADR-039 · Session #23)

---

## Decision 033: 三源 sector/industry 补全链（FinanceDatabase → SEC EDGAR SIC → Wikidata）+ bottom-up 同业无杠杆 β

Reason: Yahoo `quoteSummary/assetProfile` 端点长期 401（约 83% 未授权）→ `sector`/`industry` 大面积为 `None` → 分类器 layer-2 硬规则（+3.0）不触发、ML 文本特征丢失最强信号，边界准确率被压制在 ~75%。需接入**离线/更稳的权威数据源**补全这一关键字段，并唤醒长期空置的 `MarketData.industry_beta` 审计槽位。

原则：
1. **三源优先级链（绝不伪造）**：`SectorIndustryResolver` 依次尝试 ① FinanceDatabase（30 万+ 离线元数据，Yahoo 兼容口径，无 HTTP）→ ② SEC EDGAR（`company_tickers.json` 取 CIK → `submissions/CIK*.json` 取官方 **SIC 代码 + 描述**，一手监管数据）→ ③ Wikidata SPARQL P452（兜底冷门/退市标的）。任一层缺失/断网返回 `{}` 继续下一层；全部失败返回 `{}`（不填猜测值）。
2. **SIC → Yahoo 桥接必须「可分类」**：SIC 是美国监管口径，但引擎消费 Yahoo 口径（`map_sector_industry` 硬规则 / peer 桶 / WACC sanity 带），故经 `data/sic_map.py::map_sic_to_yahoo()` 解析（精确 4 位 → 2 位大类 → 描述关键词）。**契约：每个映射产出的 industry 必须能被分类器硬规则消费**，否则返回 None（避免填入无法行动的字串污染下游）。关键词按具体→宽泛排序（`semiconductor` 先于 `software`）。
3. **SEC 合规访问**：SEC 公平访问政策要求带含联系方式的 `User-Agent`（`SEC_USER_AGENT` 可配，默认含联系方式）；限流保守、结果缓存（类级 `_MEM` + `.cache/` 磁盘）。
4. **bottom-up 无杠杆 β（Hamada）**：`β_u = β_L / (1 + (1−t)·(D/E))`，`t=0.21`（美国法定税率）；同业列表来自 FinanceDatabase、逐 peer β 与 D/E 来自 yfinance；**取中位**（抗离群）。**<3 家同业或无可得 β → 返回 None（绝不伪造）**；`BOTTOM_UP_BETA=0` 可关；离线（`offline=True`）不触碰任何 lister。
5. **接线为 add（不覆盖 CAPM）**：bottom-up β 写入 `MarketData.industry_beta` → 由 `wacc.py::WaccBreakdown.beta_transparency_note()` 展示为**审计输入**，**不参与 CAPM 标量 β**（升级为 CAPM 输入须单独审阅，见 #6 Next Task）。taxonomy 仍为 additive shadow。
6. **可注入 + 优雅降级**：三个外部库均 optional import（缺失→该层返回 `{}`），测试用 monkeypatch 保持离线确定性。

Date: 2026-11-14  (ADR-040 · Session #24)

---

## Decision 034: Bottom-up β 升级为「业务身份三级筛选 + 完整 β 链」并接入 CAPM（M-34）

Reason: Session #24 的 bottom-up β 用裸 `get_companies_by_industry(industry)` 选同业，会把**异质**公司（如 fabless 设计 vs 重资产代工晶圆厂）混入中位，得到不代表目标公司**真实商业风险**的 β。须按**业务身份**而非粗粒度行业筛同业，并补齐从同业到目标公司的完整 β 链，最后接入 CAPM。

原则：
1. **按业务身份筛同业（替代裸 industry）**：`get_companies_by_business_identity(sub_industry=..., business_model=..., economic_profile=...) -> PeerScreen`。三级升级筛选：**L1 同 Sub-industry + Business Model** → **L2 相邻行业（同 sector）+ 相似经济特征（`_profile_matches` 比较 capex/loss/asset-light 标志）** → **L3 Damodaran 行业基准**。逐级回退，直到凑够 `_MIN_PEERS=3`。
2. **完整 β 链（绝不跳过任一环）**：Peer Levered Beta → Hamada Unlevered（`β_u = β_L / (1 + (1−t)·D/E)`）→ **Median Unlevered**（抗离群）→ **Cash-adjusted**（`β_business = β_u / (1 − Cash/Firm)`，去现金对 β 稀释；`Cash/Firm` 上限 `_CASH_TO_FIRM_CAP=0.90`，操作权重下限 10%）→ **Target Relevered**（`β_L = β_u × (1 + (1−t)·D/E_target)`）。
3. **L3 内置真实快照、绝不伪造**：`data/damodaran_beta.json`（Aswath Damodaran NYU Stern，**Jan 2026** 快照，100 行业，字段 `unlevered_beta` / `unlevered_beta_cash_adjusted`）。文件缺失或行业未覆盖（`_damodaran_lookup` 经 `_DAMODARAN_ALIASES` ~80 条 Yahoo→Damodaran 别名归一后未命中）→ **L3 返回 None**，不填猜测值。
4. **接入 CAPM 三段优先级（保持单一 β 出口 ADR-019）**：`wacc.py::calculate()` — ① 有 bottom-up（已 cash-adjusted + 按目标 D/E re-lever）→ 用作 CAPM 标量 β；② 否则回退现有回归 β；③ 都无则 `default_unlevered_beta`。二者 final β 均 winsorize 至 `[0.30, 2.50]`。`resolve_effective_beta()` 单源出口不变，市场区/风险旗标/WACC 三处一致。
5. **`clamped` 语义修正**：现意为「**原始回归 β** 超出 CAPM 带」，而非「与所用 β 不同」；因此 bottom-up 被选用**不应**被误报为截断。
6. **接线为 add（守护 golden 零漂移）**：`MarketData` 新增 `bottom_up_beta` / `bottom_up_beta_chain`；`providers.py` 接线；离线 golden 的 `MarketData` 不带这两字段（`None`）→ wacc 走回退回归 β 分支，与基线一致。默认可关（`BOTTOM_UP_BETA=0`）。
7. **多业务公司（后续）**：Segment-level β（按分部 β × 业务价值权重整合）留作 **M-35**，依赖 M-31 分部收入数据，非本次范围。

Date: 2026-11-14  (ADR-041 · Session #25 · 关闭 TODO M-34)

---

## Decision 035: 分部收入数据层 (M-31) + Segment-level β——多业务公司按业务价值权重整合分部 β（M-35）

Reason: Session #25 落地**公司级** bottom-up β 后，多业务/多元化公司（BRK-B 保险+铁路、GE 航空+能源、AMZN 电商+AWS）仍按整个公司求一个 β，把风险特征迥异的分部压成单一行业匹配，是公司级 bottom-up β 的**最大剩余误差源**（TODO M-35 列为最高优先级）。需先有分部收入数据（M-31），再按分部求 β 并按业务价值权重整合（M-35）。

原则：
1. **M-31 以 FMP 为主源（关键前提纠错）**：实测 **SEC `companyfacts` JSON 不含分部（dimensional）数据**（AAPL `Axis`/`ProductOrService`/`StatementBusinessSegments` 计数均为 0）→ `data/segment_revenue.py` 以 **FMP `/revenue-product-segmentation`（v4 flat / v3 legacy）** 为主源，**需 `FMP_API_KEY`，无 key → `[]`（绝不伪造，不发请求）**；类级 `_MEM` + 磁盘缓存（可离线复放）。如需 SEC 一手分部须整包 Financial Statement Data Sets 或 filing-instance XBRL（**勿再试 companyfacts**）。
2. **分部 → 行业（关键词映射）**：`_SEGMENT_INDUSTRY_KEYWORDS`（~65 条 label 关键词 → Yahoo 行业，具体优先）+ `_default_segment_industry_resolver`；**未命中 → 该分部丢弃（不猜测）**。
3. **分部 → β_u**：每个分部行业**复用 M-34 三级筛选链**（`derive_bottom_up_beta`）求分部 unlevered β（同业去杠杆 → 中位 → cash-adjust）。
4. **权重 = 业务价值优先**：`segment_weights(by="value")`——所有可用分部均有 `operating_income>0` → 按**营业利润占比**加权，否则回退**收入占比**；返回归一到 1.0 的 `[(label, weight)]`。
5. **整合链 + 门控（绝不伪造 + 透明回退）**：`derive_segment_level_beta` 计算 `β_u_company = Σ (w_i/coverage)·β_u_i`（权重在可解析子集重归一）→ `_cash_adjust` → target-relever；`level=0` / `source="segment-weighted"` / `segments` 逐分部审计。可解析分部 `<min_segments(2)` 或覆盖权重 `<0.60` → 返回 `None` → `derive_bottom_up_beta(segments=...)` **透明回退公司级链**（golden 离线无分部 → **零漂移**）。
6. **taxonomy 消费端**：`FinancialData.revenue_composition`（`Optional[Any]`，避免循环 import）由 providers 落值；`build_taxonomy_profile` 读取（缺失 → 显式 `unavailable`）。

Date: 2026-11-14  (ADR-042 · Session #26 · 关闭 TODO M-31 + M-35)

---

## Decision 036: Phase 1 · Valuation Integrity——EV↔Equity 独立桥 / SBC 归一化「二选一」/ 币种感知 Rf / β 溯源只渲染可验证事实 / WACC raw-clamp 分离（ADR-051 · Session #38）

Reason: 用户第三轮代码审查提交 **Phase 1 — Valuation Integrity**，核心是「确保估值没有错误的输入、错误的来源和错误的股权价值桥接」——揭露 6 个具体缺陷：① β 标签硬编码「3Y monthly vs SPY」无法证明输入 β 真按此法计算；② β 回归用未复权 close + 无日期连续性检查；③ `equity = ev - net_debt` 对复杂资本结构（MI/优先股/联营/租赁）失真；④ SBC 作为非现金费用加回 CFO，但它是股东真实成本（既扣 SBC 又算稀释 = 双重计数）；⑤ Rf 一律用美国 10Y（USD/HKD/CNY/MYR 混用）；⑥ WACC 钳制后的值被当作真实计算结果。

原则：
1. **β 溯源只渲染可验证事实**：删除硬编码标签，`_format_beta_source(prov, beta_value)` 按 provenance 的 `source` 分派（`regression` → 窗口标签/价格口径/基准/起止日期/观测数/缺口数；`provider` → 明示「vendor estimate, method unverified」；无 provenance → 「source unverified」）。**未改主 β 选择逻辑**（用户明确反对未验证即设定唯一主 β）。
2. **β 回归用复权价 + 日期连续性**：`adjclose` 优先（raw close 仅回退并如实标注 `price_basis`）；ISO-week/period keying 记 `missing_periods`。
3. **EV↔Equity 独立桥**：公式 `Equity = EV − NetDebt − MinorityInterest − PreferredEquity − Leases(未含于Debt时) − OtherClaims + NonOperatingAssets`；**重复扣除守卫**（`net_debt_includes_*` / `leases_in_debt is True` 不再扣）；`None` = 无该项索偿（绝不静默按 0）；`equity_to_enterprise()` 与 `enterprise_to_equity()` **共用同一 resolver → 精确互逆**（模型间零漂移）。
4. **SBC 归一化「二选一」**：`expense`（扣 FCF，股数不变）vs `dilution`（缩放股数，FCF 不变），**机制上杜绝双重计数**；SBC 缺失/为 0 不调整（绝不臆造成本）。
5. **币种一致性**：现金流币种 ↔ Rf ↔ 通胀假设 ↔ 终值增速同源——`CURRENCY_RISK_FREE_RATES` / `CURRENCY_NOMINAL_GDP`；Rf 四级优先级（注入值仅在币种一致/provenance 非 USD 时保留 → 活 U.S. Treasury 仅 USD → 币种主权锚 → 默认）；USD 来源 Rf 用于非 USD 现金流时**显式替换并记录**；终值 GDP 上限随币种调整。
6. **钳制 ≠ 计算结果**：保留 `wacc_raw` / `wacc_clamped` / `wacc_clamp_reason` + `wacc_clamp_note()`，报告展示原始值、最终值与钳制原因，异常升级为估值风险提示。

Date: 2026-11-15  (ADR-051 · Session #38 · 关闭 TODO M-54 ~ M-59)

---

## Decision 037: 口径统一 + 报告解释修复——FCF 相对诊断 / TV-EV 措辞分级 / MC 桥接一致 / SBC 全覆盖 / β 方法分歧 / Peer 溯源与股数审计（ADR-052 · Session #39）

Reason: 用户提交**代码审查报告**，明确目标「**统一现有模型的财务口径，并让报告正确解释计算结果**」且**强调不新增估值模型**。揭露 8 类口径/解释缺陷：① FCF margin 诊断用绝对 15pp 阈值 → 4.2%→13.7% 被误判 ALIGNED；② TV/EV 仅 >80% 才 flag → 73.9% 被写成「显式期贡献占主导」（实际显式期仅 26.1%）；③ MC 用 `EV − net_debt` 而 DCF 用完整桥 → 口径不一致，且 `ev=None → 0`；④ FCF Yield 未做 SBC 归一化 + 缺失 FCF 被 `or 0.0` 变成真实零；⑤ β 不确定性只看回归窗口极差，掩盖 Bottom-up 0.94 vs Regression 1.41 的方法分歧；⑥ `EXACT_INDUSTRY` 实为静态表 key 匹配（非真实同业中位数）；⑦ 股数分母不透明；⑧ MC 截断未透明化。

原则：
1. **口径一致优先于新增模型**：DCF / Monte Carlo / Multiples 必须共享同一 EV↔Equity 桥（`enterprise_to_equity()`）、同一 SBC 口径（`normalize_fcf_for_sbc()`）、同一股数契约（`ShareCountBasis`）。
2. **报告措辞必须与计算一致**：TV/EV 报告分级与风险 Severity 阈值**解耦**——`<50%` 显式期占多数 / `50–70%` 终值占多数 / `70–80%` 高终值依赖需审查 / `≥80%` 风险警告；**73.9% 不得读作显式期主导**。
3. **FCF margin 诊断相对化**：触发条件加入相对判断（>2× TTM、符号翻转、≥5pp），并新增 TTM vs 历史 Normalization Layer（区分暂态资本开支周期 vs 结构性经营现金流恶化；历史均值 ≠ 未来正常值）。
4. **缺失数据 = Insufficient Data**：严禁 `None → 0`（FCF Yield 缺失 FCF → `INSUFFICIENT_DATA`；MC `ev=None → None`）。
5. **β 三指标透明**：`Regression Stability` / `Bottom-up Reliability`（`BETA_BOTTOM_UP_MIN_PEERS=4` 以下降级）/ `Methodology Divergence`——方法分歧必须显式命名，不得被窗口极差掩盖。
6. **来源可追溯**：Peer 来源标签细分（`EXACT_SECTOR_ANCHOR` 明示非实时同业报价）；Share Count Audit Table（逐模型股数分母 + 相对 Market 偏差）。
7. **Golden Baseline 零漂移**：本轮不重生成基线；所有改动在 USD / 简单结构 / 无 SBC 时退化为原行为。

Date: 2026-11-15  (ADR-052 · Session #39 · 关闭 TODO M-60 ~ M-66；新增遗留 M-67 / M-68)

---

## Decision 038: 跨行业阈值校准 + SBC 归一化下沉 FCF 主链——按业务原型分档诊断带 / β 同业地板按池广度 / FCF 单一出口双函数（ADR-053 · Session #40）

Reason: 关闭 Session #39 自身遗留的两条 Known Issue——① 诊断阈值（FCF margin 带 `0.03/0.05/2.0` + `BETA_BOTTOM_UP_MIN_PEERS=4`）为**全局初值**，但 5pp 的 FCF margin 摆动对受监管公用事业与重资本半导体**不是同一件事**，4 家同业中位数在深池偏薄、窄池偏宽；② Phase D 让 `reverse_dcf` 与 `multiples` **各自**调用 `normalize_fcf_for_sbc()`，多地各自施加调整正是 SBC 被**重复扣减**（既当费用扣 FCF、又当稀释扣股数）的经典来源。

原则：
1. **阈值按业务原型校准，非全局单值**：新建 `analysis/threshold_calibration.py` 作**运行时单一来源**——以 3–5 年年度营业利润率总体 σ 代理 FCF margin 波动（`<0.03 stable` / `0.03–0.06 moderate` / `≥0.06 volatile`），**带宽随波动放大**（`2pp/4pp/1.75×` → `3pp/5pp/2×` → `4pp/7pp/2.5×`）。
2. **β 同业地板按 peer-pool 广度，而非波动**：宽池 `5` / 窄池 `3` / 未知 `4`（窄池 `{NEOBANK, FINTECH, CONGLOMERATE}`）——深池需更多名字才配称中位数可靠，窄池小地板是诚实的。
3. **两来源校准可审计可复现**：内部样本（离线篮子 `BASKET` 实测 σ 冻结于 `CALIBRATION_EVIDENCE`，n 随 σ 披露，仅作佐证非精度声明）+ 领域先验（篮子未覆盖原型）；校准 harness 仅复现工具，**绝不在报告期依赖**。
4. **未知原型回退默认带，绝不静默重判**：未映射 archetype → `DEFAULT_CALIBRATION`（moderate 全局带），报告打印 `〔行业校准[tier]…〕` 审计行说明带宽来源。
5. **SBC 归一化下沉至 FCF 主链唯一出口**：`data/fcf_utils.py` 确立**双函数**——`resolve_ttm_fcf()`（raw primitive，仅存在性检查，不施加 SBC）+ `resolve_ttm_fcf_normalized()`（value producer，SBC **恰好一次**）；所有 FCF 消费者改经后者 → **结构性杜绝双计**；缺失 FCF 返 `missing`，绝不臆造零。
6. **惰性 import 破除循环依赖**：`valuation/wacc.py` 模块级导入 `analysis.threshold_calibration` 会触发 `models.dcf → valuation.wacc → analysis → analysis.expectation → models.reverse_dcf → models.dcf` 环；改为函数体内惰性 import（零行为变更）。
7. **ID 诚实性**：`TODO.md` 中 M-68 已被 Monte Carlo 截断占用，故 SBC 下沉**正名为 M-69**（不抢占既有 ID）。
8. **Golden Baseline 零漂移**：本轮不重生成基线；所有改动在 USD / 简单结构 / 无 SBC 时退化为原行为。

Date: 2026-11-15  (ADR-053 · Session #40 · 关闭 TODO M-67 / M-69；M-68 保持 TODO)

---

# 11. Known Issues

| Issue | Status | Solution |
|--------|--------|----------|
| Yahoo quoteSummary/assetProfile 端点 401 Unauthorized (830/1000 = 83%) | 🔧 部分缓解 (2026-11-14) | 数值特征完整 (15/15)，文本特征仅 company_name 可用。**Session #24 缓解**：新增三源 `sector/industry` 补全链（FinanceDatabase → SEC EDGAR SIC → Wikidata），不再单依赖 Yahoo assetProfile；SEC 层实测 10/10 精确，layer-2 硬规则覆盖 75% → 78.3%。剩余 90%+ 目标依赖 M-16 / C-02（真实标注重训） |
| CSV 第一列多一行 "ticker" 重复表头 (PowerShell Import-Csv/Export-Csv 遗留) | ✅ Resolved | 实测 labeling_dump.csv 1000 行数据 + 1 行表头，无重复表头 L2 垃圾行；之前警告已清除 |
| 部分 Yahoo ticker 返回 404 (如 COUP, FUV, TESS, TPRO, SOL) | ✅ Resolved | 合成数据填充，note 列标注，数量<1%可忽略 |
| interest_to_revenue = 0 占 821/1000 = 82.1% | ⚠️ High Impact → 🔧 优化中 | Bank/REIT/Utilities/Insurance 分类关键信号缺失；下一步脚本重算: interest_expense / revenue |
| Semiconductor 类别样本过少 (29/1000 = 2.9%) | ⚠️ Medium → 🔧 优化中 | AVGO 实际应为 Semiconductor 但被标成 MatureTech 进一步加剧；下一步 class_weight='balanced' + SMOTE |
| Unknown 类别占比过高 (354/1000 = 35.4%) | ⚠️ Acceptable | 可接受：早期标注阶段大量边缘公司先归 Unknown；扩充到 5000 训练集后占比会下降 |
| ⚠️ **SOFI 连锁误报 #1：ML 置信度 66.6% → 业务类型 55% 黑盒扣减** | ✅ Resolved (2026-10-08) | 根因：sector/industry missing 触发 confidence=min(conf, 0.55) 未透明记录。修复：新增 ConfidenceAdjustment[]，所有扣减 step + delta(pp) + reason 全链路记录并在业务区块渲染拆解明细 |
| ⚠️ **SOFI 连锁误报 #2：单标签分类无法表达 FinTech 混合业务** | ✅ Resolved (2026-10-08) | 根因：11 类无 FinTech/Hybrid，Bank+Unknown+MatureTech 混合被硬判为 Bank。修复：不扩枚举，新增 3 条 Hybrid 触发规则 + 5 轴 Exposures 聚合 (Fin/Tech/Cyclical/HardAssets/Diversified) |
| ⚠️ **SOFI 连锁误报 #3：银行 FCF=-$9B 触发 3 个风险误报 (score 80→95)** | ✅ Resolved (2026-10-08) | 根因：把银行的 Operating CF - Capex 当普通公司 FCF 解读，产生 Weak FCF 标签 + 4y neg-FCF Medium + FCF Yield=-60% High 三个连锁误报。修复：7 层机构敏感分叉，风险评分 80→95 |
| ⚠️ **Session #05 Bug #1：中位估值对比主语重复「中位估值较中位估值高 +41.6%」** | ✅ Resolved (2026-10-08) | 根因：detail = f"（中位估值 {median_vs_price_detail}）" 外层多加了前缀，但 median_vs_price_detail 内部已自带「当前价较中位估值」完整句。修复：直接 `f"（{detail}）"`，去掉「中位估值」前缀；Decision 007 新增「主语不自包原则」 |
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
| ⚠️ **Session #16 #1（高优先级 · 数学）：负终期 FCF 被 `last_fcf = avg_abs` 偷改成正数 → 伪造正终值** | ✅ Resolved (2026-11-12) | 影响 Normal DCF / Reverse DCF / Monte Carlo 三处。修复：统一出口 `gordon_terminal_value()` 抑制终值（不翻转符号）+ `terminal_fcf_negative` 标注 + APPROXIMATE；风险层补 HIGH 旗标分支（Decision 024 / ADR-028） |
| ⚠️ **Session #16 #2（代码风险）：`ReverseDCFModel` 共享单例被 `self.horizon` 跨标的污染** | ✅ Resolved (2026-11-12) | SaaS(7)→Utilities(10)→Unknown **沿用 10**。修复：删除 `self.horizon`，新增单一真源 `resolve_forecast_horizon()`，全链路统一（Decision 025 / ADR-029） |
| ⚠️ **Session #16 #3：golden 基线有意漂移（NBIS.median_value 12.76 → 10.46）** | 🟡 By Design (2026-11-12) | 旧值由伪造正终值虚高而来，新值为显式期现值下限（诚实值）。`UPDATE_GOLDEN=1` 重生成并逐字段审阅，仅 1 字段漂移（Decision 024） |
| ⚠️ **Session #16 #4：反向 DCF 求解器无残差/收敛检查** | ✅ Resolved (2026-11-12) | `brentq` 只保证 bracket 收窄，EV 曲面平坦时可能隐藏多解。修复：新增 `rel_resid = |f(root)|/|target_ev| > 1e-3` → `SolverStatus.APPROXIMATE` + note（Decision 025） |
| ⚠️ **Session #16 #2（功能不足）：Reverse DCF 仅反推 Revenue CAGR** | ✅ Resolved (2026-11-12 · Session #17) | 新增约束式单变量求解：Implied Operating Margin / FCF Margin / WACC / Terminal Growth（one-at-a-time，其余固定基准）。硬边界越界 → `NO_SOLUTION_IN_RANGE` 不钳制（Decision 026 / ADR-030） |
| ⚠️ **Session #16 #4（设计说明）：FCF Margin 非独立变量** | ✅ Resolved (2026-11-12 · Session #17) | 新增 `project_enterprise_value_flat_margin()`（`FCF_t=revenue_t×fcf_margin`），使 FCF margin 成为良定义独立求解目标；报告显式展示固定假设（Decision 026 / ADR-030） |
| ⚠️ **Session #17 遗留：隐含驱动未纳入 golden 指纹/invariant** | 🟡 By Design (2026-11-12) | 约束式求解器的边界/单调性/残差行为已由 `TestConstraintSolver` 直接覆盖；golden 指纹扩展待后续审阅漂移后再做，避免求解数值抖动污染基线 |
| ⚠️ **Session #18 #1（P0）：Brent 失败后 Bisection 未校验有效 bracket** | ✅ Resolved (2026-11-12) | 无根区间仍进入二分 → 可能返回「看似正常的 CAGR」被误当真实隐含预期。修复：`_finish_root()` 在 `brentq` 失败且 `f(a)·f(b) > 0` 时返回 `NO_SOLUTION_IN_RANGE`（拒可疑根），求解后一律 residual 检查（Decision 027 / ADR-031） |
| ⚠️ **Session #18 #2（P0）：求解器默认单调但未验证** | ✅ Resolved (2026-11-12) | 仅两端点大小不能证明整区间单调。修复：`implied_monotonic_samples=21` 点采样实测方向；非单调 → 扫描 root brackets（0 无解 / 1 求解 / >1 → `MULTIPLE_ROOTS`）；步长级平坦 → `NON_MONOTONIC`（Decision 027 / ADR-031） |
| ⚠️ **Session #18 #3（P0）：负终值抑制未贯穿 Reverse DCF/期望/渲染** | ✅ Resolved (2026-11-12) | 终值被抑制时仍可能显示 `SOLVED`，投资者误以为十年 DCF 已完整。修复：`terminal_fcf_negative` 纳入 breakdown + implied_expectations；`_finalize_revenue_cagr()` 降级 SOLVED→APPROXIMATE + 「Terminal Value Suppressed — Turnaround Assumption Required」；期望层与渲染层透出（Decision 027 / ADR-031） |
| ⚠️ **Session #18 #4（P1）：Revenue CAGR 端点等于目标被误判无解** | ✅ Resolved (2026-11-12) | 原先 `(ev_lo−t)(ev_hi−t) < 0` 严格判定 → 端点根被判无解。修复：端点含容差判定为边界解 `SOLVED`（Decision 027 / ADR-031） |
| ⚠️ **Session #18 #5（P1）：常数目标（无敏感度）未检测** | ✅ Resolved (2026-11-12) | 终值抑制后隐含 TG 可能完全不影响 EV。修复：`fmax−fmin ≤ abs_tol` → 命中目标 `FLAT_OBJECTIVE` / 不命中 `NO_SOLUTION_IN_RANGE`（Decision 027 / ADR-031） |
| ⚠️ **Session #18 自查发现①：单调性容差误用残差容差** | ✅ Resolved (2026-11-12) | 残差容差被 \|target\| 放大 → 步长可比时把单调曲面误判 `NON_MONOTONIC`。修复：单调性改用步长尺度容差 `mono_tol=1e-6·f_span`（Decision 027） |
| ⚠️ **Session #18 自查发现②：递减方向可达区间赋值反转** | ✅ Resolved (2026-11-12) | `lo_val/hi_val` 在递减分支被赋反 → 递减目标被误报「超出约束上界」。修复：可达区间恒为 `(fmin, fmax)`，仅交换 `x_at_max/x_at_min`（Decision 027） |
| ⚠️ **Session #19 #1（P0）：Cost of Debt 独立重读 Rf（与 CAPM 背离）** | ✅ Resolved (2026-11-13) | `_implied_cost_of_debt()` 自行 `getattr(mkt,"risk_free_rate") or config` → 若 MarketData Rf 为空而主流程从 Treasury 取到有效值，则 ke 用 Treasury、kd fallback 静默用 config 默认（报告 Rf 与债务成本不一致）。修复：`calculate()` 将已解析 `rf` 传入，所有债务 fallback 与 CAPM **共用同一 Rf**；独立调用回落原优先级链（Decision 028 / ADR-032） |
| ⚠️ **Session #19 #2（P0）：Terminal Growth High 无条件突破长期 GDP 上限** | ✅ Resolved (2026-11-13) | `high = Base + 0.5%` 且注释明写「High may exceed LT GDP；only Gordon bound is a hard cap」→ Base=4.5% 时 High 可达 5.0%，易被误当「长期稳定终值增长率」。修复：重定义三档经济学含义（Base=唯一受 GDP+Gordon 约束的长期稳定终值增长率；Low/High=情景区间）；新增引擎字段 `high_exceeds_gdp` / `gdp_ceiling` / `band_labels`，在推导追踪 / DCF 假设说明 / 渲染三处显式标注「High 为乐观情景，非长期稳定终值增长率」（Decision 028 / ADR-032） |
| ⚠️ **Session #19 #3（P1）：Quality-Weighted Median 破坏等权退化不变量** | ✅ Resolved (2026-11-13) | `_weighted_median()` 返回首个累计权重 ≥ total/2 的值 → 等权（常见）且模型数为偶数时返回第 n/2 个值而非 `mean(values[n/2-1], values[n/2])`，导致「加权中位数」≠ 普通中位数（AAPL 176.12 vs 165.24）。修复：改用标准 **midpoint 定义**（下/上加权中位数取平均），等权时精确退化为普通中位数；零/负权重剔除；新增 16 用例；golden 4 只有意漂移已审阅重生成（Decision 029 / ADR-033） |
| ⚠️ **Session #21 #1：bottom-up β 无数据源（`industry_beta` 恒为 None）** | ✅ Resolved (2026-11-14) | 根因：字段与渲染已就绪，但 provider 无「同业 unlevered β」数据 → 诚实缺省 `None`。修复（Session #24）：新建 `data/industry_beta.py` **动态同业无杠杆 β（Hamada）**——同业列表（FinanceDatabase）+ 逐 peer β/D-E（yfinance）→ `β_u = β_L/(1+(1−t)·D/E)` → 中位；`providers.py` Layer-3 resolver 块后接入填充。Semiconductors 同业实测 = **1.2447**；<3 家同业仍返回 `None`（绝不伪造）（Decision 033 / ADR-040） |
| ⚠️ **Session #21 #2：β 多窗口月聚合边界可能轻微合并样本** | 🟡 By Design (2026-11-13) | 月线/周线按 key 归并同周期收盘，边界处偶有极小回归抖动（测试容差 0.01）。多窗口仅为稳定性披露（独立审计输入，不覆盖 CAPM 标量 β），非缺陷（Decision 031 / ADR-036） |
| ⚠️ **Session #23 #1：③ Revenue Composition 恒为 unavailable（无分部收入源）** | ✅ Resolved (2026-11-14) | 五维模型第 ③ 维（分部占比 + 数据日期）原为**诚实缺省**（Yahoo `quoteSummary` 不返回分部明细）。修复（Session #26 / M-31）：`data/segment_revenue.py` 以 **FMP `/stable/revenue-product-segmentation`** 为主源（Session #27 迁移 + 多 key + Shape C）→ `to_revenue_composition` 落 `FinancialData.revenue_composition`；无 key/无数据仍显式 `unavailable`（绝不伪造占比） |
| ⚠️ **Session #23 #2：taxonomy 当前为 additive shadow 层（不参与路由）** | ✅ Resolved (Session #30 / M-32) (2026-11-14) | 为保证 golden 指纹零漂移，Session #23 时 taxonomy 结果仅写入 `CompanyProfile` 8 个 shadow 字段，不参与 `business_type` / `applicable_models` / 模型路由。**Session #30 已切换为参与路由**：`taxonomy_routing_override()` 三道 gating（CONFIRMED + **跨 identity family 冲突** + 经济护栏），对比**内部身份判定 `best_bt`** 而非 `routing_bt`；「跨族才覆盖」结构性排除同族差异导致的漂移 → **golden 零漂移（未重生成）**（ADR-047） |
| ⚠️ **Session #23 #3：External Classification 仅覆盖 Yahoo sector/industry + ML 标签** | 🟡 Open (2026-11-14) | 第 ⑤ 维设计容纳 GICS / NAICS，但 provider 暂无这两类数据 → `ExternalClassification.gics`/`naics` 恒为 `None`（原样保留字段，不填充猜测值）。待 M-33 补齐 |
| ⚠️ **Session #23 自查发现：`commodit` typo 死词条 / `cs` 族根误挂父边 / depth 误用点计数 / ceiling 允许同族「提升」到经济学节点** | ✅ Resolved (2026-11-14) | ① `("commodot", COMMODITY_SPOT)` 拼写错误永不匹配 → 改 `("commodit", …)` 词干；② `cs`（Consumer Staples）族根误挂 `cons` 父边 → 去父（族根应无父，`depth=0`）；③ `depth` 由 `key.count(".")` 改为 **parent 链 `_structural_depth()`** 推导（修复 `cons.cyclical` 分组节点子节点与父同点深度的语义偏差）；④ `economic_identity_ceiling()` 原允许同族从 `tech.semiconductor`「提升」→ 重写为 `common_ancestor()` 收敛（黄金法则真正生效） |
| ⚠️ **Session #24 #1：分类硬规则命中率 78.3%（18/23），未达 90% 目标** | 🟡 Open / 待 M-16·C-02 (2026-11-14) | 三源补全已把「None 缺口」消除（此前 401 阻断导致 +3.0 硬规则整体失效）。剩余 5 只**非 None 缺失**，而是「真值/粒度差」：ASML→Industrial、QCOM→MatureTech、MSFT→SaaS、XOM→Energy、BRK-B→Insurance。推高到 90%+ 需 M-16（hybrid 阈值复评）+ C-02（真实标注重训），非数据补全问题 |
| ⚠️ **Session #24 #2：bottom-up β 当前仅作审计展示，不参与 CAPM** | 🟡 By Design (2026-11-14) | `MarketData.industry_beta` → `WaccBreakdown.beta_transparency_note()` 仅展示为**独立审计输入**；CAPM 标量 β 仍用回归 β（winsorized [0.30, 2.50]）。这是有意的增量接线（可观测、不改 WACC）。升级为 CAPM 输入须先审阅与回归 β 的收敛差异（见 #6 Next Task 第 8 项） |
| ⚠️ **Session #24 #3：三源链依赖外部库/网络（优雅降级）** | 🟡 By Design (2026-11-14) | FinanceDatabase / SEC EDGAR / Wikidata 均为 **optional import**：库未装或断网 → 该层返回 `{}` 继续下一层（全失败返回 `{}`，不伪造）。SEC 需合规 `User-Agent` 且限流保守；`sec-edgar-downloader` / `wikipedia-api` 非硬依赖。测试用 monkeypatch 保持离线确定性 |
| ⚠️ **Session #24 自查发现：SEC SIC "6726"/"67"（Asset Management）无法被分类器硬规则消费** | ✅ Resolved (2026-11-14) | `map_sic_to_yahoo()` 正确产出 "Asset Management"，但 `classifier.py::SECTOR_INDUSTRY_MAP` 缺该条目 → `map_sector_industry()` 返回 None → SEC 层填入的是「无法行动的字串」（+3.0 不触发）。修复：补 `("asset management", BusinessType.BANK)`；并由 `tests/test_sic_map.py` 的「每个映射产出必可分类」守卫锁定 |
| ⚠️ **Session #27 #1：FMP `/api/v4`、`/api/v3` 遗留端点 403 `Legacy Endpoint`（2025-08-31 起停用）** | ✅ Resolved (2026-11-14) | 分部收入接口由 legacy 迁移至 **`/stable/revenue-product-segmentation`**；新增 `_FMP_STABLE` + 层优先序 `_from_fmp_stable` → `_from_fmp_v4` → `_from_fmp_v3`（legacy 保留为薄封装以便遗留订阅） |
| ⚠️ **Session #27 #2：FMP `/stable` 响应为 Shape C（元数据外层包裹嵌套 `data`）** | ✅ Resolved (2026-11-14) | `_extract_fmp` 新增 Shape C 分支：仅取嵌套 `data` 的 label→数值，`date` 作 `as_of`；`fiscalYear`/`period`/`symbol` 等元数据**不泄漏为分部**（`test_shape_stable_data_wrapper` 断言 `"fiscalYear" not in labels`）。若 FMP 再改形状需同步此分支 |
| ⚠️ **Session #27 #3：分部→行业关键词表覆盖存在上限（真实语料 107/172）** | 🟡 By Design / 数据驱动 (2026-11-14) | 残余 65 个未映射 label 中约 39 个为**桶/地理/药品品牌名/发行人缩写**——**必须保持不映射**（丢弃优先，绝不猜测）；其余为发行人专属/歧义词，交由公司级 β **透明回退**（对单业务发行人即为正确结果）。可用 `_discover_segment_labels.py` 随语料增量迭代 |
| ⚠️ **Session #27 #4：`FMP_API_KEY` 未落盘 `.env` 时回退 `[]`** | 🟡 By Design (2026-11-14) | 支持 `FMP_API_KEY=key1,key2` **多 key 轮换**；仅当 key 写在编辑器缓冲区而未保存（`Ctrl+S`）时 `dotenv` 读不到 → 运行期 `get_segments` 返回 `[]`（绝不伪造，回退公司级 β） |
| ⚠️ **Session #30 #1（阶段 A）：`filing_evidence`（SEC filing-instance XBRL）原为独立入口，未接入生产主链** | ✅ Resolved (Session #30 / M-39) (2026-11-14) | 根因：M-38 交付的 `filing_evidence.py` 是 drop-in 兼容入口，但 `data/providers.py` 仍直接构造 `SegmentRevenueResolver`（FMP），FMP 无 key 时静默回退公司级 β、丢失一手分部。修复：新增 `segment_revenue.resolve_segments(ticker)` **生产默认源链**（Layer 1 FMP → Layer 2 SEC 10-K/20-F filing-instance XBRL，两层皆空 → `[]`），`providers.py` 改调源链 → FMP 缺 key / 失效 / 额度耗尽 / 未覆盖时自动降级；仍为 shadow 数据填充（ADR-046） |
| ⚠️ **Session #30 #2（阶段 B）：M-32 gate 对比 `routing_bt` 会致 GOOGL golden 漂移** | ✅ Resolved (Session #30 / M-32) (2026-11-14) | 根因：`routing_bt` 是 Phase 1.3 ambiguous 时的**保守估值路由**（GOOGL 取 `TELECOM`），与 `tech.internet(MatureTech)` **跨族** → 若 gate 对比 `routing_bt` 则 GOOGL 被误覆盖、`applicable_models` 改变、golden 漂移。修复：gate 改为对比**内部身份判定 `best_bt`**（`classifier.py` 注释明写 "comparison is against the verdict, not ``routing_bt``"）；`ml_classifier.py` 对称修正（economics 用 raw ML top-1） |
| ⚠️ **Session #30 #3（设计约束）：M-32 覆盖可能漂移 golden（用户口径=不重生成）** | ✅ Resolved (Session #30 / M-32) (2026-11-14) | 用户要求「taxonomy 参与路由」且「golden 不重生成、零漂移」表面冲突。修复：采用**跨族冲突才覆盖**闸门——同族差异（如 `tech.software.infra` vs 内部 `MatureTech`，ORCL/NBIS/CRWV tension basket 属此类）**不覆盖**，归经济驱动分类器所有；因此 18 只 basket 无漂移风险。golden **零漂移（未重生成）** 已由 `pytest 429 passed` 验证（ADR-047） |
| ⚠️ **Session #34 #1（P0-1）：Utilities 行业 WACC 区间匹配失败** | ✅ Resolved (2026-11-14) | 根因：`INDUSTRY_WACC_RANGES` 关键词 `"Utility"` **不是** Yahoo 行业字段 `"Utilities"` 的子串 → VST 类标的静默落入 `DEFAULT_INDUSTRY_RANGE=(6.5%~11.5%, Market Average)`；且不能把受管制公用事业与独立发电商当同一经济模型。修复：关键词改 `"Utilities"` + 新增 `CANONICAL_KEY_WACC_RANGES`（`util.electric`/`util.gas`/`util.water`/`util.ipp`/`util.diversified` **各自独立区间**）+ `_normalize_industry_text()`（破折号归一化）+ `_match_industry_range()` 四级优先级 + `WaccBreakdown.industry_range_source`（ADR-049） |
| ⚠️ **Session #34 #2（P0-2）：ETR 重复计算重叠期间** | ✅ Resolved (2026-11-14) | 根因：`_effective_tax_rate()` 把 `data.ttm` 与 `data.annual_income[:3]` **相加**——TTM 已含最近四季度，最新财年**双重加权** → ETR 失真并污染税后债务成本/WACC（报告出现 `ΣTax/ΣEBT over 4 period(s)`）。修复：非重叠期间策略（TTM-only / 去重财年 / 法定默认）+ `WaccBreakdown.tax_period_basis ∈ {ttm, fyN, default}`（ADR-049） |
| ⚠️ **Session #34 #3（P0-3）：不同股数口径的每股估值被当同一单位比较** | ✅ Resolved (2026-11-14) | 根因：DCF/Reverse DCF/Multiples/SOTP 各用不同股数来源，却把不同口径的每股估值直接并入共识中位数（`reconciliation.py` 的股数保护本身正确，但未阻止不兼容口径横向比较）。修复：新增 `ShareCountBasis`/`ShareCount`/`make_share_count()` + `ValuationResult.share_count`（各模型申报口径）+ 共识层可比性校验（偏差 >`SHARE_COUNT_COMPARABLE_TOL=0.10` 剔除出中位数）；**保留 EV/Equity Value 独立参考，不重写股数凑中位数**（ADR-049） |
| ⚠️ **Session #34 #4（P0-4）：FCF Yield Gap 风险方向误判** | ✅ Resolved (2026-11-14) | 根因：`pos_fcf_gap = abs(fcf_yield-0.04)/0.04` **对称**度量偏差 → 正 FCF 但收益率**高于** 4%（VST 5.03%）被误标 High。修复：非对称方向感知（正 FCF ≥ 参考不判风险 / < 参考仅估值观察 + materiality gate / 负 FCF 按恶化幅度与持续性）+ `_fcf_trend()` + `_downgrade()` + `fcf_yield_reference` 降格为可配置参考参数（ADR-049） |
| ⚠️ **Session #35 #1（P1-SOTP）：SOTP 循环估值伪装独立证据** | ✅ Resolved (2026-11-14) | 根因：`_derive_segments_from_profile()` 用**公司自身** `ev/revenue` 作 `ev_rev_mult`（`max(0.5,min(10.0,ev/revenue))`）乘回 revenue → Operating EV ≈ 市场 EV，再按 ML `business_exposures` 拆成多业务 = **先取市场估值再按概率分配**（循环）。修复：三态状态机（`SOTP_SOLVED`/`SOTP_APPROXIMATE`/`SOTP_INSUFFICIENT`）——仅真实分部财务 + 独立 peer multiple → SOLVED 计入共识；仅 ML 暴露度 → `display_only` 剔除；`segments_detail` 明细分部来源；修复双重扣净债 bug（ADR-050） |
| ⚠️ **Session #35 #2（P1-6）：多窗口 β 不稳定却直接用单一 β** | ✅ Resolved (2026-11-14) | 根因：多窗口 β（VST 极差 0.95）仅用于展示，无 bottom-up 时仍直接取 3Y Monthly 再 winsorize。修复：Blume-style 收缩（`BETA_MAX_SHRINK=0.35`、`BETA_DISPERSION_SHRINK_THRESHOLD=0.50`，**不取平均**）+ `beta_raw`/`beta_selected`/`beta_adjusted` 三分离 + β 不确定性**传导至 WACC 区间**（`wacc_beta_lo`/`wacc_beta_hi`）（ADR-050） |
| ⚠️ **Session #35 #3（P1-7）：报告出现两个 ETR** | ✅ Resolved (2026-11-14) | 根因：`_market_section()` 读供应商 `m.effective_tax_rate`（20.4%），WACC 用 `wacc_bd.effective_tax_rate`（19.634%）→ 双数字自相矛盾。修复：市场快照主值改 **WACC 实际使用 ETR**（+ `_etr_basis_suffix()` 标注 `tax_period_basis`）；供应商值另标 **Provider ETR**（ADR-050） |
| ⚠️ **Session #35 #4（P1-8）：成功解算 ≠ 使用可比较数据口径** | ✅ Resolved (2026-11-14) | 根因：各模型股本/币种/期间口径可能不兼容却无条件进入共识中位数。修复：新增 **Valuation Comparability Gate**（7 维冲突检测）+ `make_comparability()` 契约 + DCF/Multiples/SOTP 接线；冲突模型隔离出共识但仍展示；**未声明口径 ≠ 冲突，不排除**（ADR-050） |
| ⚠️ **Session #40 #1（M-67 遗留）：跨行业阈值分档 cut point 为文档化先验，样本篮子偏小** | 🟡 Open / 数据驱动 (2026-11-15) | `analysis/threshold_calibration.py` 的 tier cut point（σ `0.03`/`0.06`）与带宽为**文档化先验**；`CALIBRATION_EVIDENCE` 内部样本篮子仅 19 名、各原型 n 偏小（仅作**佐证**，非精度声明）。缓解：未知/未映射原型回退 `DEFAULT_CALIBRATION`（moderate 全局带），**绝不静默重判**；报告打印 `〔行业校准[tier]（观测 σ, n）…〕` 审计行。**扩充样本后应重推**（ADR-053） |
| ⚠️ **Session #40 #2（M-67 遗留）：窄池原型集合硬编码** | 🟡 Open (2026-11-15) | `_NARROW_PEER_POOLS = {NEOBANK, FINTECH, CONGLOMERATE}` 目前硬编码（这些原型纯 play 上市公司本寥寥）；新增原型需同步该集合，否则将按 `BETA_MIN_PEERS_BROAD=5` 判定（可能对窄池偏严）（ADR-053） |
| ⚠️ **Session #40 #3（M-69 遗留）：SBC 归一化靠约定 + 测试守住，无强制门禁** | 🟡 By Design (2026-11-15) | `data/fcf_utils.py` 确立 FCF **单一出口**（`resolve_ttm_fcf` raw primitive / `resolve_ttm_fcf_normalized` value producer），但新 FCF 消费者**必须**经后者方可获 SBC 归一化——当前无编译期/运行期强制门禁，靠约定 + `TestSbcMainChainExit` 守住。后续可加静态检查（禁止直接读 `stmt.free_cash_flow` 绕过出口）（ADR-053） |
| ⚠️ **Session #40 #4（M-68）：Monte Carlo 截断仍在边界堆积概率质量** | ⬜ Open / TODO (2026-11-15) | 正态抽样后直接 clamp 会在边界堆积概率质量（Session #39 已**透明化**：`distribution_transparency_note()` 输出下/上界命中率与 Gordon 命中率，但未改分布）。修复方向 = 截断正态 / 拒绝采样（重参数化抽样），**明确排入 M-68**（TODO.md 中仍 `⬜ TODO`，本轮未做） |

---

# 12. Blockers

Current blockers preventing progress.

```
🟢 sector/industry 缺失（原 MINOR BLOCKER）已由 Session #24 三源补全链解除：
  - FinanceDatabase（离线）→ SEC EDGAR（SIC 桥接，一手监管）→ Wikidata（兜底）；
    SEC 层实测 10/10 精确，layer-2 硬规则覆盖 75% → 78.3%。

🟡 剩余 MINOR BLOCKER: 训练特征补全 + 标签纠错
  - interest_to_revenue 缺失率 82% → 从 TTM interest_expense / revenue 重新计算（可本地完成，无需 API）
  - AVGO 等方法样本标签错误需人工确认修正（AVGO 实为 Semiconductor 却标 MatureTech）
  - C-02：人工标注 1001 行 label → 切换真实训练源 → 重训 → AB 测试（推高准确率至 90%+）
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
  • Overview 首屏直观判断区块 + Gap 增长解读 + Agreement 估值细节拆解三区块渲染
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
- ✅ ✨ Session #24 三源 sector/industry 补全链 + bottom-up β（H-03）：
  • 🔌 data/industry_resolver.py 三源解析器（FinanceDatabase → SEC EDGAR SIC → Wikidata）+ data/sic_map.py SIC→Yahoo 桥接
  • 🧮 data/industry_beta.py 动态同业无杠杆 β（Hamada，t=0.21，<3 同业返回 None）+ providers.py 接线
  • 🐛 classifier.py SECTOR_INDUSTRY_MAP 补 ("asset management", BANK) 覆盖缺口
  • ✅ pytest **333/333 全通过**（288 → 333，+45 用例）；golden 零漂移；Ruff 新文件全绿
- ✅ ✨ Session #25 Bottom-up β 升级「业务身份三级筛选 + 完整 β 链」接入 CAPM（M-34）：
  • 🎯 data/industry_beta.py::get_companies_by_business_identity() 三级筛选（L1 同子行业+商业模式 → L2 相邻行业+相似经济特征 → L3 Damodaran 基准）
  • 🧮 完整 β 链（Peer Levered → Hamada Unlevered → Median → Cash-adjusted → Target Relevered）+ data/damodaran_beta.json（Jan 2026，100 行业，未覆盖→None）
  • ⚙️ valuation/wacc.py CAPM 三段优先级（bottom-up 优先 / 缺失回退回归 β / 都无 default）；clamped 语义修正；MarketData +bottom_up_beta/_chain；providers 接线
  • ✅ pytest **353/353 全通过**（333 → 353，+20 用例）；golden 零漂移；新模块/新测试 Ruff clean
- ✅ ✨ Session #26 分部收入数据层 + Segment-level β（M-31 + M-35）：data/segment_revenue.py（FMP 主源，无 key → []）+ derive_segment_level_beta（分部 β_u 按业务价值权重整合，门控 <2 分部/覆盖<60% → 回退）；pytest 353 → 376；golden 零漂移
- ✅ ✨ Session #27 M-35 收尾（M-36）：FMP 多 key 轮换 + `/stable` 端点迁移 + Shape C 解析 + `_SEGMENT_INDUSTRY_KEYWORDS` 两轮补全
- ✅ ✨ Session #28 商业理解层六模块映射 + 四态决策契约 + Identity Resolution（M-37）：DecisionStatus（decide_status 确定性映射）+ data/identity_resolver.py（SEC 链 + OpenFIGI）+ classification/business_intelligence.py（业务证据收集器）；pytest 382 → 398；golden 零漂移
- ✅ ✨ Session #29 SEC 10-K / 20-F filing-instance XBRL 业务证据抽取（M-38）：data/filing_evidence.py（FilingBusinessExtractor + parse_segment_revenue 纯函数，四重防重复，source="sec-xbrl"）+ 四态决策端到端测试；pytest 398 → 413；golden 零漂移
- ✅ ✨ Session #30 SEC filing-instance XBRL 生产化接入 providers 主链（M-39）+ Taxonomy 参与路由（M-32）：
  • 🔌 data/segment_revenue.py::resolve_segments() 生产默认源链（Layer 1 FMP → Layer 2 SEC filing-instance XBRL，两层皆空 → []）+ providers.py 改调源链（FMP 缺 key/失效/额度耗尽/未覆盖 → 自动降级）
  • 🧭 classification/taxonomy.py 新增 `taxonomy_routing_override()`（三道 gating：CONFIRMED + 跨 identity family 冲突 + 经济护栏）+ `ARCHETYPE_FAMILIES`（树推导）+ `TAXONOMY_ROUTING_STATUSES`；classifier.py / ml_classifier.py 对称 gate（对比内部身份判定 `best_bt`，非 `routing_bt`）
  • 🧪 tests/test_taxonomy.py 新增 TestTaxonomyRoutingGate（12 用例）+ tension basket（ORCL/NBIS/CRWV）
  • ✅ pytest **429/429 全通过**（413 → 429，+16 用例）；golden **零漂移（未重生成）**；改动模块/新测试 Ruff clean
- ✅ 🐛 Session #34 用户代码审查 4 项 P0 修复（行业 WACC 身份键 / ETR 非重叠口径 / 股数口径契约 / FCF Yield 非对称风险）：
  • 🧭 valuation/wacc.py P0-1：`CANONICAL_KEY_WACC_RANGES`（canonical key → 独立区间）+ `_normalize_industry_text()` + `_match_industry_range()` 四级优先级 + `WaccBreakdown.industry_range_source`（修复 `"Utility"` ⊄ `"Utilities"` 子串陷阱）
  • 🧾 valuation/wacc.py P0-2：`_effective_tax_rate()` 非重叠期间（`tax_period_basis ∈ {ttm,fyN,default}`）
  • 🧮 models/base.py P0-3：`ShareCountBasis`/`ShareCount`/`make_share_count()` + 四模型 `share_count` + model_agreement 可比性校验（偏差 >10% 剔除出中位数）
  • ⚖️ analysis/risk.py P0-4：FCF Yield Gap 非对称方向感知（`_fcf_trend()` + `_downgrade()` + `fcf_yield_reference`）
  • ✅ pytest **429/429 全通过**；golden 因 P0 行为修正**有意重生成一次**（逐条核对为预期修正）

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
36. ✨ (Session #23) 「经济学特征 ≠ Business Identity」是本项目最隐蔽的误判源：一家经营大型 AI 数据中心的 Software/Cloud 公司，其高毛利+高 CapEx+低负债与半导体厂商高度相似；若允许 economics 直接决定 identity，NBIS 类标的会被误判为 Semiconductor。正确约束是「economics 只能族内细化，跨族一律不提升，同族兄弟冲突收敛至 common ancestor」
37. ✨ (Session #23) taxonomy 的 `depth` 语义不能靠 `key.count(".")`：`cons.cyclical` 是**分组节点**（其子节点与它同点深度），点计数会把分组层级误当父子层级 → 必须由 **parent 链**遍历推导
38. ✨ (Session #23) 外部标签映射必须是**两段式 longest-key-wins**（industry 优先 → sector → 兜底）：单表混排会让 17 字符的 `Consumer Cyclical` 压过 15 字符的 `Internet Retail`，把 AMZN 误判为 `cons.generic`、KR 误判为 `cs.generic`
39. ✨ (Session #23) 引入新分类层时，只写「影子字段」(shadow) 不碰 `business_type`/`applicable_models`/路由，可实现「可观测 + 零 golden 漂移」的增量接线；待契约稳定后再单独审阅切换为「参与路由」（M-32）
40. ✨ (Session #24) 分类硬规则命中率卡在 ~75% 时，根因往往是**上游特征缺口**（Yahoo 401 → `sector/industry` 大面积为 `None`）而非阈值调参；先用「离线/一手数据源链」（FinanceDatabase → SEC EDGAR SIC → Wikidata）补齐特征，再谈数据驱动复评（M-16）；且外部口径（SIC）到内部消费口径（Yahoo industry）的桥接必须「可被下游硬规则消费」，否则宁可返回 None 也不填无法行动的字串
41. ✨ (Session #25) bottom-up β 的准确性瓶颈不在数学，而在 **peer 集合的语义纯度**：裸 `get_companies_by_industry()` 把 fabless/代工/设备商混入中位 → β 不反映目标公司的真实商业风险；须按**业务身份三级升级筛选**（L1 同子行业+商业模式 → L2 相邻行业+相似经济特征 → L3 Damodaran 基准）；且须走完整链（Peer Levered → Hamada Unlevered → Median → Cash-adjusted → Target Relevered），其中 **Cash-adjusted 去现金稀释** 与 **target D/E re-lever** 缺一不可
42. ✨ (Session #25) 把新 β 源接入 CAPM 时，必须守住**单一 β 出口**（`resolve_effective_beta()`）与 **winsorize 带**；同时修正 `clamped` 语义为「原始回归 β 超带」而非「与所用 β 不同」，否则 bottom-up 被选用会被误报为「截断」，污染风险区/报告文案
43. ✨ (Session #28) 「信号如何相关」（`ConflictKind`）与「能否据此行动」（`DecisionStatus`）是两个正交问题：前者说「证据是否一致」，后者说「分类是否安全可行动」。把二者混为一谈会让「一致但仅自由文本支撑」的结论被误当作 CONFIRMED；正确做法是四态契约 + 确定性映射（结构化外部事实 → CONFIRMED，仅自由文本 → PROBABLE，跨族冲突 → AMBIGUOUS，无可靠证据 → INSUFFICIENT_DATA），并与 ADR-024 口径契约一脉相承
44. ✨ (Session #28) 「Identity（这是谁）」与「Classification（做什么）」必须分层：CIK/SIC/FIGI 是**稳定监管锚**，sector/industry 是**可变的营销标签**。把二者混在同一层会导致「标签变了 → 身份跟着变」的隐性漂移；`IdentityResolver` 单列一层后，taxonomy / peer / provenance 皆可引用稳定 key。且外部标识（尤其 OpenFIGI）**无 key 即 None、绝不伪造**，是「绝不伪造」纪律在身份层的延伸
45. ✨ (Session #29) SEC 分部（dimensional）数据只有**两条路**：`companyfacts` JSON **不含 axis/member 维度**（实测计数为 0），故必须解析 **filing-instance XBRL**（10-K/20-F 内嵌 `*_htm.xml`）或整包 Financial Statement Data Sets。filing-instance 路线的成败关键在**上下文解析**：`xbrli:context` 决定 `(期间, 维度轴, 成员)`，只有同时持有 segment 轴 + member + **duration endDate** 的事实才是分部收入——漏判 `endDate` 会把 `<xbrli:instant>` 的资产负债表数字（如总资产）误当分部收入
46. ✨ (Session #29) 分部聚合必须防三类重复/污染：(a) **绝不把合并总额计入分部**（无轴事实一律跳过）；(b) **单一轴**（`StatementBusinessSegmentsAxis` 等按优先级取一条，混轴会重复计数）；(c) **取最新期间**（同一 member 跨多个 duration 时只保留最新 endDate，否则上年同期被重复累加）。drop-in 设计（返回既有 `Segment` + `source="sec-xbrl"`）使新数据源能零扰动接入既有 `to_revenue_composition`/taxonomy ③ 管线
47. ✨ (Session #29) 四态决策契约的价值要靠**端到端**测试锁定：单测只证明映射函数本身，必须用**真实 `build_taxonomy_profile` / `attach_taxonomy_profile` / ML 标签**跑全链路，断言 shadow 字段（`CompanyProfile.taxonomy_decision_status`）确实被写入且在多原型（NVDA/MSFT/JPM/PLD）下状态合法——否则「接线」可能在重构中静默断开而单测全绿
48. ✨ (Session #30 / M-39) 「可用入口」≠「生产默认路径」：M-38 的 `filing_evidence` 是 drop-in 入口，但只要 `providers.py` 仍直连 FMP，FMP 缺 key 时就静默回退公司级 β、一手分部永远用不上。正确做法是把多源降级封装为**单一源链入口** `resolve_segments(ticker)`（Layer 1 FMP → Layer 2 SEC filing-instance XBRL，两层皆空 → `[]`），让调用方只依赖「拿到的分部」，源的优先级与降级逻辑内聚在链内；跨模块引用（`filing_evidence`）用**惰性 import** 避免循环依赖
49. ✨ (Session #30 / M-32) taxonomy 从 shadow 切换到「参与路由」时，gate 对比的**必须是内部身份判定 `best_bt`，而非 `routing_bt`**：`routing_bt` 是 Phase 1.3 ambiguous 时的**保守估值路由**（GOOGL 被重路由为 `TELECOM`），与 `tech.internet(MatureTech)` 属**跨 identity family** → 若对比 `routing_bt` 会判定「跨族冲突」而误覆盖 GOOGL，改变 `applicable_models`、golden 漂移。区分「身份判定」与「估值路由」是本次最关键的口径纠错
50. ✨ (Session #30 / M-32) 「taxonomy 参与路由」与「golden 不重生成、零漂移」并非不可调和：采用**跨族冲突才覆盖**的窄门后，同族差异（如 `tech.software.infra` vs 内部 `MatureTech`，ORCL/NBIS/CRWV 的 tension basket 正属此类）**不覆盖**，归经济驱动分类器所有 → 18 只 basket 结构性无漂移风险。`ARCHETYPE_FAMILIES` 由 `IDENTITY_NODES` 树**推导**（非硬编码），保证 archetype 与节点树永不漂移；`TAXONOMY_ROUTING_STATUSES={CONFIRMED}` 把「能否据此行动」（四态契约）正式接入路由门控
51. ✨ (Session #31 / Round 1) 当市场价落在业务类型 **sanctioned growth band 之外**时，「伪造一个 band 内的点估」是伪精确的反面教材：正确做法是输出**结构化 bound**（`implied_revenue_cagr_bound={kind, value, ev_at_bound}`，`above_band_ceiling`→「≥ 上限」/`below_band_floor`→「≤ 下限」）—— 用「市场已 price-in 的最小/最大增速 + 该边界对应的 EV」诚实表达「超出模型可定价区间」，把不确定性从点估传导到区间。normalized 救援只在 **bridge_broken**（桥断裂）时启用，不作为「凑出 band 内数字」的手段
52. ✨ (Session #32 / Round 2) 同一份「市场隐含预期」在报告里由两处渲染（`_implied_section` 与 `_gap_section`）时，**必须共享同一数据来源**：Round 1 只把 bound 写进 implied 区，gap 区仍读点估 → PG 出现「一区 ≥93.9% / 一区 N/A」的自相矛盾。修复是把 bound 结构化落进 `ExpectationGap`（`implied_revenue_cagr_bound`/`implied_revenue_cagr_is_bound`）并让 gap 区镜像措辞 —— 与 ADR-019「命名矛盾不做平均」、ADR-022「口径契约化」一脉相承
53. ✨ (Session #33 / Round 3) **Growth Risk 必须测「下行离散度」而非总离散度或 CV**：`CV=σ/|μ|` 在 μ→0 时爆炸（受管制的公用事业 SO：μ≈0.9%、σ≈10.5pp → CV≈11.9 被误报 High）；总 σ 把**向上的**离散也计入（PLD 6.0→8.0→8.2→8.8bn、VICI 2.6→3.6→3.8→4.0bn 这类**单调收购爬坡是成长不是波动**，却被 σ≈14–16pp 标 High）。改用 `dd=RMS(min(growth,0))`（相对 0 的半离差）后，只保留「营收收缩的幅度与频率」这一经济学真实信号 → SO High→Medium、PLD/VICI/CEG/AMT 旗标消失，仅真实收缩标的（XOM/CVX/COP/NUE/PFE/MRNA/NEE/UPS/NKE/BA/SO）保留
54. ✨ (Session #33 / Round 3) **going-concern 折现率不可能低于无风险利率**：Round 2 后仍有标的（DUK 2.3%/SO 2.7%/CEG 3.3%）反解出 sub-Rf 的隐含 WACC，等价于「负风险溢价」—— 经济上不自洽。修复：`dcf._estimate_wacc_breakdown()` 暴露 WACC **实际使用的** Rf（单一真理源，避免反向 DCF 自行重解 Rf 而与报告 WACC 悄悄分叉），反向 DCF 以 Rf 为 implied-WACC 下限；目标 EV 连 Rf 都够不到时 → `NO_SOLUTION_IN_RANGE` 并把下限写进 `implied_wacc_floor_rf`（**命名约束，不伪造**）。验证后全 50 标的 `implied_wacc < 0.045` 计数 = 0
55. ✨ (Session #34 / P0-1) 行业 WACC 区间靠**关键词子串包含**匹配是静默失效源：`INDUSTRY_WACC_RANGES` 关键词写 `"Utility"`，而 Yahoo 字段实为 `"Utilities—Independent Power Producers"`（`"Utility" ⊄ "Utilities"`，且 Yahoo 用**无空格 em/en dash**）→ VST 类标的静默落入 `DEFAULT_INDUSTRY_RANGE=(6.5%,11.5%, Market Average)`。修复：关键词改 `"Utilities"`（保留单数兼容）+ 新增 `CANONICAL_KEY_WACC_RANGES`（`util.electric/util.gas/util.water/util.ipp/util.diversified` 各自独立区间，**按 Taxonomy Canonical Key 而非字符串巧合**）+ `_normalize_industry_text()`（em/en dash 与 `" - "` 两侧归一化）+ `_match_industry_range()` 四级优先级（canonical key → `node_from_yahoo` → 关键词表 → 默认），并把命中来源写进 `WaccBreakdown.industry_range_source`
56. ✨ (Session #34 / P0-2) ETR 的 `data.ttm + data.annual_income[:3]` 相加是**重叠期间双重加权**：TTM 已含最近财年，再叠加最近三个财年 ⇒ 最新财年被计两次（报告出现 `ΣTax/ΣEBT over 4 period(s)`）。修复：`_effective_tax_rate()` 改为**非重叠期间策略**（TTM-only → 去重财年 → 法定默认），返回值升为 3 元组 `(etr, source, tax_period_basis)`，`tax_period_basis ∈ {ttm, fyN, default}`；实测 `0.2105/ttm`、`0.2142/fy2`、`0.21/default` 三口径可复现
57. ✨ (Session #34 / P0-3) 各模型股数来源不一却被并入同一中位数：DCF/Reverse DCF/Multiples/SOTP 各用不同口径股数（TTM/稀释/市值），`reconciliation.py` 的股数保护只管「单模型内」，管不住「跨模型横向比较」。修复：新增 `ShareCountBasis`（BASIC/DILUTED/TTM/MARKET/UNKNOWN）+ `ShareCount` + `make_share_count()` + `ValuationResult.share_count`（各模型申报口径），`model_agreement` 增加可比性校验（偏差 `>SHARE_COUNT_COMPARABLE_TOL=0.10` 剔除出中位数）。实测：AAPL P/E（30.4B vs 参考 15.2B，偏差 100%）被剔除，中位 132.19→123.99，覆盖率恒等式仍成立
58. ✨ (Session #34 / P0-4) FCF Yield Gap 用**对称偏差** `pos_fcf_gap = abs(fcf_yield-0.04)/0.04` 是方向误判：正 FCF 且收益率**高于** 4%（VST 5.03%）的健康标的被误标 High。修复：改**非对称方向感知**（正 FCF ≥ 参考不判风险 / < 参考仅估值观察 + materiality gate / 负 FCF 按恶化幅度与持续性评估）+ `_fcf_trend()`（`cumulative_change` + `consecutive_declines`）+ `_downgrade()`（可降不可凭偏差升）+ `fcf_yield_reference` 可配置。实测：KR High→Medium、XOM/AAPL 假 FCF 旗标消失、风险总分相应回落
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
26. ✨ (Session #23) 分类层要分「身份」与「经济特征」两个正交维度：finance 特征可用于**同族内**细分，绝不能跨族决定身份；把这条约束写成单一函数（`economic_identity_ceiling()`）并用「同族兄弟应收敛到共同祖先、跨族应拒绝提升」的用例锁定，是防止「财务特征伪造身份」的结构性防线
27. ✨ (Session #23) 结构语义（树深/层级）必须从**显式 parent 关系**推导，不要从字符串形态（点计数）反推：一旦存在「分组节点」（自身不增加层级深度，仅用于归类），形态推断就会失真；显式 `_PARENT_OF` 映射是唯一可靠真源
28. ✨ (Session #23) 映射表匹配要用 **longest-key-wins + 分层优先**（具体层先于宽泛层），并写「相位无关」用例（断言 `node_from_yahoo("Consumer Cyclical","Internet Retail") == "cons.ecommerce"`）——否则长字符串的宽泛标签会静默压过短字符串的具体标签，制造难察觉的误判
29. ✨ (Session #23) 新增分类/推断层时，先以 **shadow 字段**接入（不改既有路由与输出），用全量回归证明「零漂移」，再单独提审「参与路由」的切换——把「新能力引入」与「行为变更」解耦，避免一次性引入不可控的 golden 漂移
30. ✨ (Session #24) 上游字段（`sector/industry`）是分类器最强硬规则的输入：Yahoo assetProfile 401（83%）让 `+3.0` 行业硬规则整体失效，把边界准确率钉在 ~75%。补上权威来源（本地元数据 / SEC 一手 SIC）后硬规则覆盖率立即 75% → 78.3%——**先修数据源，再谈调模型/阈值**
31. ✨ (Session #24) 跨 taxonomy 桥接（SIC → Yahoo）必须带「可消费」契约：SIC 是监管口径、引擎消费 Yahoo 口径；映射函数不仅要产出 industry 字符串，还必须保证该字符串能被下游硬规则消费，否则等于用一个「看起来对但无法行动」的值污染链路。用「每个映射产出必可分类」的守卫测试锁定
32. ✨ (Session #24) bottom-up β 的「绝不伪造」纪律：同业样本 <3 家或 β 不可得时返回 `None`，而非用单一 peer 或行业均值硬凑；Hamada 去杠杆 + 取**中位**（不用均值）是对同业离群的结构性防御
33. ✨ (Session #24) 外部数据源一律 **optional import + 优雅降级**：库未装或断网 → 该层返回 `{}`（不抛异常、不阻断主流程）继续下一层；测试全部用 monkeypatch 离线化，保证 CI 确定性
34. ✨ (Session #30) 多源降级要封装为**单一入口**，而非让每个调用方各自拼源：`resolve_segments(ticker)` 把「FMP 为主 → SEC filing-instance XBRL 为回退 → 皆空即 `[]`」内聚为一条链后，`providers.py` 只依赖「拿到的分部」，新增/替换源对调用方透明。跨模块引用用**惰性 import** 打破循环（`segment_revenue` ↔ `filing_evidence`）
35. ✨ (Session #30) 「参与决策」的 gate 必须对比**决策语义对应的那个量**，而不是同名易混的邻变量：M-32 若对比 `routing_bt`（估值路由，含保守重路由）会误判 GOOGL 跨族并漂移 golden；对比 `best_bt`（身份判定）才是正确的「身份冲突」比较面。落地时把结论写进代码注释（"comparison is against the verdict, not routing_bt"）以防未来回退
36. ✨ (Session #30) 当「新增能力」与「保持基线零漂移」冲突时，用**结构性窄门**而非调参/白名单化解：M-32 的「跨族冲突才覆盖」在结构上排除了同族差异（等同族均可由经济特征分类器处理）→ 无需列举豁免标的即可保证 18 只 basket 零漂移。比「逐标的白名单」更可维护、更少特例
37. ✨ (Session #31–#33) **递归自我改进的每轮修复都会引入下一轮的新缺陷面**：Round 1 加 bound 却漏了 gap 区镜像（Round 2 修）；Round 2 用 σ 门却漏了 μ→0 与单调爬坡（Round 3 修）；Round 3 才发现 sub-Rf 折现率不自洽。故每轮必须**重跑 + 重读产出**（`_batch_eval.py roundN` → `_audit_summary.py roundN`），绝不能假设「改完即对」—— 与用户「写完必须自己运行」硬纪律一致
38. ✨ (Session #33) 一份审计产出要能**被断言**才驱动得了迭代：把「50 只标的 → 五问结论」落成结构化 JSON（`_batch_eval_roundN.json`）+ 紧凑摘要（`_audit_summary.py`：分类准确率 / 路由违例 / 缺陷数 / reverse-DCF 量化 vs bound-only vs 未量化），每轮用一行 `50/50 = 100.0% | routing_viol=0 | defects=0` 做回归门；否则「验证」会退化成人工读报告，无法跨轮对比
39. ✨ (Session #34 / P0-1) **口径必须由「身份」决定，而非字符串巧合**：用 `in` 子串包含匹配行业名（`"Utility"` vs `"Utilities"`）会静默回退到默认值——「匹配失败」与「本就不在表内」无法区分。正确做法是从 **Taxonomy Canonical Key** 读显式映射（受管制电力/燃气/水务/独立发电商各自独立区间），并把命中来源（`industry_range_source`）写进结构化产物，使「走的是哪条规则」可被断言与审计；同一归一化（em/en dash）必须在映射表两侧对称执行
40. ✨ (Session #34 / P0-2) **加总重叠期间 ⇒ 双重加权**：凡「TTM + 最近年度」这类拼接口径，必须先判定期间是否重叠再累加，否则最新财年被计两次、指标被单向拉偏且报告数字看起来仍「合理」。落地模式是把**期间基准**显式化为返回值的一部分（`tax_period_basis ∈ {ttm, fyN, default}`），让「用的哪段期间」成为可审计契约而非隐含假设
41. ✨ (Session #34 / P0-3) **不同口径的数字「可读」不等于「可并列比较」**：单模型内的股数保护挡不住跨模型的每股估值横向合并。正确做法是引入**口径契约**（`ShareCountBasis` + `ShareCount` + `make_share_count()`）+ **可比性校验层**（偏差超阈值剔除出中位数，但保留 EV/Equity Value 作独立参考），而不是把所有股数强行改成同源去凑一个漂亮中位数——「隔离不可比」优先于「强行统一」
42. ✨ (Session #34 / P0-4) **对称偏差度量会把「更好」误判为「更差」**：`abs(value - benchmark)` 对方向不敏感，正 FCF 且收益率高于参考的健康标的会被风险旗标惩罚。风险判定必须**方向感知**（一侧为风险、另一侧为优点）、带 materiality gate，并允许基准按行业可配置；`_downgrade()`（可降不可凭偏差升）是「宁漏勿错报」的非对称守卫——与 ADR-024「分类不确定性 → 估值确定性」的传导纪律一致
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
- ✨ data/sic_map.py: `SIC_TO_YAHOO`（~180 精确 4 位：3571 Computer Hardware / 3674 Semiconductors / 7372 Software-App / 6021 Banks-Diversified / 6331 Insurance-P&C / 6798 REIT-Diversified / 2911 Oil&Gas Refining / 4911 Utilities-Electric …）+ `SIC2_TO_YAHOO`（~68 类）+ `SIC_DESC_KEYWORDS`（~130 关键词，specific→broad）+ `map_sic_to_yahoo(sic, desc)` + `_normalize_sic()`
- ✨ data/industry_resolver.py: `SectorIndustryResolver`（`_MEM` 类缓存 + `.cache/` 磁盘缓存 + `batch_get()`）+ 层 `_from_financedatabase` / `_from_sec_edgar`（`_load_sec_ticker_map` → `_sec_cik_for` → `_SEC_SUBMISSIONS_URL`）/ `_from_wikidata`（SPARQL P452）+ `_sec_ua()`（读 `SEC_USER_AGENT`）+ `_ticker_variants()` + `resolve_sector_industry()`
- ✨ data/industry_beta.py: `derive_industry_unlevered_beta(ticker, sector, industry, *, peer_lister, beta_fetcher, max_peers=10, tax_rate=0.21, cache_path, offline)` + `IndustryBetaResult.note()` + `_default_peer_lister()`（`fd.Equities().select(industry=)`）+ `_default_beta_fetcher()`（yfinance β + debtToEquity/100）+ `_unlever()` + `_MIN_PEERS=3` / `_DEFAULT_TAX=0.21` / `BOTTOM_UP_BETA=0` 开关 + 缓存 `.cache/industry_beta.json`（key `{sector}|{industry}`）
- ✨ data/providers.py: `_fetch_quote_summary_simple` Layer-3 resolver 块后的 bottom-up β 块（填充 `out["industry_beta"]`）
- ✨ classification/classifier.py: `SECTOR_INDUSTRY_MAP` 新增 `("asset management", BusinessType.BANK)`
- ✨ tests/test_sic_map.py / tests/test_industry_resolver.py / tests/test_industry_beta.py: 共 45 用例（离线 monkeypatch）
- ✨ Session #24 在线实测：SEC 层 10/10 精确（AAPL/NVDA/JPM/PLD/XOM/MSFT/BRK-B/KR/AMZN/BLK）；Semiconductors bottom-up 无杠杆 β = 1.2447；pytest 333/333
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

## 2026-11-15 (Session #41 — AVGO Audit Remediation Phase 1: P0-1 桥缺失数据安全 / P0-2 P/E 口径一致 / P0-3 股数证据闸门)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：用户提交正式任务书 **Valuation Engine — AVGO Audit Remediation Phase 1**（基于 2026-11-15 06:27 UTC 的 AVGO 报告），纪律：**不重设计无关模块 / 改码前先审计现有实现 / 缺失值禁止 None→0 静默转换 / 每股基准不可靠不得产出无条件强结论 / 保持 EV 级结果 / 现有测试与 Golden Baseline 除非明确批准否则零漂移（不得自动重生成基线）/ 未实际执行的测试不得声称通过**。

Completed

- ✅ **① P0-1 · Equity Bridge 缺失数据安全**（`valuation/equity_bridge.py`）：`EquityBridge` 新增 `status`（`EB_STATUS_OK`/`INCOMPLETE`/`UNAVAILABLE`）+ `missing_inputs` + `net_debt_verified` + `is_reliable()`；`_resolve_net_debt()` 区分**已验证零净债务**（显式 `net_debt` 或 `total_debt`&`cash` 俱全）与**输入缺失**（按 0 展示但 `net_debt_verified=False`、`status=INCOMPLETE`）；`enterprise_value is None → equity_value=None`（`UNAVAILABLE`，**绝不 `0 − claims`**）；`equity_to_enterprise(None) → None`；保留复杂资本结构双计守卫；`equity_to_enterprise` 与 `enterprise_to_equity` 共用 `_resolve_claims` 保持精确互逆
- ✅ **② P0-2 · P/E 分子分母口径一致**（`models/multiples.py`）：P/E 的 EPS 分母为 TTM 报表股数 → 股权价值用**同一 TTM 股数**重建（旧码乘无关的市场股数）；无 TTM 股数 → 回退 market 并显式标注口径不一致；新增 `breakdown["pe_basis_audit"]`
- ✅ **③ P0-3 · 股数证据闸门**：`data/reconciliation.py` 新增 `ShareCountEvidence` + `share_count_evidence()`（分离市场隐含/财报期末/稀释加权平均，偏差 >25% → `consistent False`，明示 `market_cap÷price` 非财报股数证明）；`analysis/model_agreement.py` 新增 `_EXPECTED_SHARE_BASIS` + `ShareCountAuditRow.source/as_of/basis_expected` + `ModelAgreement.share_count_reliable`；`reporting/verdict_intuition.py` 股数证据不一致 → headline 封顶「每股口径不可靠」
- ✅ **④ 回归测试**：新建 `tests/test_avgo_audit_remediation.py`（15 用例）覆盖任务书 9 类场景（缺失 EV / 缺失债务与现金 / 已验证零净债务 / 复杂股权桥 / P/E 用 TTM 稀释 EPS 股数 / P/E vs 市场股数错配 / 股数偏差 >25% / 每股基准不可靠时 EV 估值仍可用 / model-agreement 与 Golden Baseline 兼容）

Modified

- `valuation/equity_bridge.py`、`models/multiples.py`、`data/reconciliation.py`、`analysis/model_agreement.py`、`reporting/verdict_intuition.py`、`tests/test_equity_bridge.py`
- 文档：`AGENT.md` / `CHANGELOG.md` / `DECISIONS.md` / `TODO.md`

Created

- `tests/test_avgo_audit_remediation.py`（15 用例）

Notes

- 验证：`python -m pytest -q` → **542 passed**（Session #40 的 522 → 542）；`ruff check .` → **All checks passed!**；`tests/test_golden_report.py` 通过 → **golden 零漂移**（未重生成基线）
- ADR-054 · 关闭 AVGO 三条 P0；Golden Baseline 未重生成

## 2026-11-15 (Session #40 — 跨行业阈值校准 (M-67) + SBC 归一化下沉 FCF 主链 (M-69))

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：关闭 Session #39 自身遗留的两条 Known Issue——① 诊断阈值（FCF margin 带 + β 同业地板）为**全局初值**，需按业务原型校准；② SBC 归一化散落在 `reverse_dcf` 与 `multiples` 两处各自调用，存在**双计**风险，需下沉至 FCF 主链唯一出口。纪律：**不新增估值模型** / **所有修复附带测试** / **Golden Baseline 零漂移** / **未知原型回退默认带，绝不静默重判** / **缺失数据返回 Insufficient Data，禁止 None→0**。备注：`TODO.md` 中 M-68 已被 Monte Carlo 截断占用，故 SBC 下沉**正名为 M-69**。

Completed

- ✅ **① M-67 · 跨行业阈值校准**：新建 `analysis/threshold_calibration.py`（**运行时单一来源**）——波动分档 `tier_for_dispersion()`（`<0.03 stable` / `0.03–0.06 moderate` / `≥0.06 volatile`，单调）+ 带宽 `_TIER_BANDS`（`2pp/4pp/1.75×` → `3pp/5pp/2×` → `4pp/7pp/2.5×`，随波动放大）；β 同业地板按**池广度**分档 `beta_min_peers_for()`（宽池 `5` / 窄池 `3` / 未知 `4`）；`CALIBRATION_EVIDENCE`（离线篮子 σ/n）+ `_ARCHETYPE_TIER` + `DEFAULT_CALIBRATION`（moderate，向后兼容）+ `calibration_for()` / `note()` / `calibration_table_note()`
- ✅ **② M-67 接线**：`analysis/divergence.py::_fcf_margin_check()` 经 `_calibration_for_profile()` 取带，审计行 `〔行业校准[tier]（观测 σ, n）：…〕`——同 +4.5pp 缺口在 Utilities 判 FLAG、在 Semiconductor 判 MODERATE；`valuation/wacc.py::_bottom_up_reliability_label()` 新增 `business_type` 形参 + `beta_min_peers_for()`（**惰性 import**）
- ✅ **③ M-69 · SBC 下沉**：`data/fcf_utils.py` 确立**双函数出口**——`resolve_ttm_fcf()`（raw primitive，仅存在性检查）+ 新增 `resolve_ttm_fcf_normalized()`（value producer，SBC **恰好一次**，生效加 `+sbc_normalized` 后缀，缺失返 `missing` 不臆造零）；`models/reverse_dcf.py` / `models/multiples.py::FCF Yield` 改消费共享出口（保留 Phase D 缺失守卫）
- ✅ **④ 循环导入修复**：`wacc.py` 模块级 `from analysis.threshold_calibration import …` 触发 `models.dcf → valuation.wacc → analysis → analysis.expectation → models.reverse_dcf → models.dcf` 环 → 函数体内惰性 import（零行为变更）

Modified

- `analysis/divergence.py`、`valuation/wacc.py`、`data/fcf_utils.py`、`models/reverse_dcf.py`、`models/multiples.py`、`tests/test_reporting_integrity_repair.py`
- 文档：`AGENT.md` / `CHANGELOG.md` / `DECISIONS.md` / `TODO.md`

Created

- `analysis/threshold_calibration.py`、`tests/test_reporting_integrity_repair.py` 的 `TestCrossIndustryThresholdCalibration`（9 用例）+ `TestSbcMainChainExit`（6 用例）

Notes

- 验证：`python -m pytest -q` → **522 passed**（Session #39 的 507 → 522）；`ruff check .` → **All checks passed!**；`tests/test_golden_report.py` 通过 → **golden 零漂移**（未重生成基线）
- ADR-053 · 关闭 TODO M-67 / M-69；M-68（MC 截断重参数化）保持 TODO

## 2026-11-15 (Session #38 — Phase 1 · Valuation Integrity / 6 项错误输入·错误来源·错误股权桥接修复)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：用户提交 **Phase 1 — Valuation Integrity**（最高优先级），目标「确保估值没有错误的输入、错误的来源和错误的股权价值桥接」。纪律：**标签必须能证明自身**（β 来源只渲染 provenance 可验证内容）/ **股权桥接独立成模块** / **SBC 二选一**（杜绝双重计数）/ **币种一致性**（现金流币种 ↔ Rf ↔ 通胀 ↔ 终值增速）/ **钳制 ≠ 计算结果**（raw/final/reason 三分离）。

Completed

- ✅ **① Beta 溯源**：`valuation/wacc.py` 删除硬编码 `sources["β"]="3Y monthly vs SPY…"` → 新增 `_format_beta_source(prov, beta_value)`（regression → 窗口/价格口径/基准/起止/观测/缺口；provider → 「method unverified」；无 provenance → 「source unverified」）。**未改主 β 选择逻辑**（用户明确反对未验证即改）
- ✅ **② 复权价格 + 日期连续性**：`data/providers.py::_estimate_beta()` 改 `adjclose`（raw close 仅回退）+ ISO-week/period keying 记 `missing_periods` + 返回 provenance dict
- ✅ **③ EV↔Equity 独立桥**：新建 `valuation/equity_bridge.py`（含重复扣除守卫 + 精确互逆），接入 DCF/ReverseDCF/Multiples/SOTP/Unit-Economics/NAV + `fcf_projection.py`
- ✅ **④ SBC 归一化**：新建 `valuation/sbc.py`（expense 扣 FCF / dilution 调股数，二选一；缺失不臆造），接入 Reverse DCF
- ✅ **⑤ 币种感知 Rf**：`config.py` 新增 `CURRENCY_RISK_FREE_RATES`/`CURRENCY_NOMINAL_GDP`/`DEFAULT_MACRO_CURRENCY`；`wacc.py::currency_macro_anchors()` + Rf 四级优先级；`terminal_growth.py` GDP 上限随币种调整
- ✅ **⑥ WACC raw/clamp 分离**：`WaccBreakdown` 新增 `wacc_raw`/`wacc_clamped`/`wacc_clamp_reason` + `wacc_clamp_note()`

Modified

- `valuation/wacc.py`、`valuation/terminal_growth.py`、`data/providers.py`、`data/models.py`、`config.py`
- `models/dcf.py`、`models/reverse_dcf.py`、`models/multiples.py`、`models/sotp.py`、`models/unit_economics.py`、`models/nav.py`、`forecasts/fcf_projection.py`
- `tests/test_terminal_growth.py`
- 文档：`AGENT.md` / `CHANGELOG.md` / `DECISIONS.md` / `TODO.md`

Created

- `valuation/equity_bridge.py`、`valuation/sbc.py`、`tests/test_equity_bridge.py`、`tests/test_sbc.py`

Notes

- 验证：`python -m pytest -q` → **474 passed**；`ruff check .` → **All checks passed!**；golden **零漂移**（USD 币种 / 简单资本结构 / 无 SBC 时全部退化为原行为）
- ADR-051 · 关闭 TODO M-54 ~ M-59

## 2026-11-15 (Session #37 — 类型检查归零 / Pyright 0 error)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：`npx pyright`（CLI 未装，经 npx 拉取）从 **40 errors + 3 warnings** 收敛到 **0**。规则分布：`reportArgumentType` 34、`reportOptionalIterable` 3、`reportMissingImports` 3、`reportPossiblyUnboundVariable` 2、`reportOptionalMemberAccess` 1。纪律：**只补类型收窄与运行时守卫，不改行为**——全部为 `Optional` 收窄 / `Any` 标注 / 可选依赖豁免，不改变任何运行时分支。

Completed

- ✅ **`analysis/model_agreement.py`**：`_resolve_share_reference` 的股数反查由「列表推导 + getattr 链式守卫」改为**显式 for 循环 + 逐层 None 收窄**（`res`→`sc`→`shares`）——消除 `float(float | None)` 与 `None.shares_used`
- ✅ **`classification/taxonomy.py`**：`BusinessTaxonomyProfile(... revenue_composition=revenue_composition or RevenueComposition.unavailable())`——`Optional` 参数经 `or` 收窄为 `RevenueComposition`
- ✅ **`data/segment_revenue.py`**：`to_revenue_composition` 改 `usable: List[Tuple[Segment, float]]`（`isinstance`+`>0` 收窄后 `float(rev)` 落库），`total`/`pct` 取已收窄 float
- ✅ **`data/industry_beta.py`**：`_coerce_segments` 增 `weight is None` 守卫
- ✅ **`models/reverse_dcf.py`**：反向 DCF 上下限改**显式 None 判定**（`bt_params` 值类型 `_Opt[float]`）
- ✅ **`data/providers.py`**：分部收入 import 移出 `try`（消除 possibly-unbound；求解仍保留 try/except 降级）
- ✅ **`data/sic_map.py`**：`map_sic_to_yahoo`/`_normalize_sic` 入参放宽为 `Optional[Union[str, int]]`
- ✅ **`data/akshare_provider.py`**：`akshare` 三处 import 加 `# pyright: ignore[reportMissingImports]`
- ✅ **`tests/test_industry_beta.py`**：`dict()`（`**kwargs`/`**base`）加 `Dict[str, Any]` 标注 + 两处 `assert res.segments is not None`

Modified

- 上述 9 个源/测试文件（仅类型收窄与守卫，无行为变更）

Created

- —

Notes

- 验证：`npx pyright` → **0 errors / 0 warnings**；`ruff check .` → **All checks passed**；`python -m pytest -q` → **436 passed**（golden 零漂移）
- 未处理（非 pyright 默认范围）：`datetime.utcnow()`/`utcfromtimestamp()` 弃用告警（2156 warnings）

## 2026-11-15 (Session #36 — 仓库级 Ruff 清理 / lint 0 error)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：`ruff check .` 从 **174 errors** 收敛到 **0**。先固化 lint 标准（新增 `pyproject.toml`），再自动修复可安全修复项，最后手工处理不可自动修复项（E701/E702/E741/结构性 E402）。纪律：**只修 lint 与死代码，不改行为**；一次性开发/调试脚本用配置排除而非强行改写。

Completed

- ✅ **新增 `pyproject.toml`**：`[tool.ruff]` `target-version="py312"`；`extend-exclude = ["_*.py", "**/_*.py", "verify_bot.py"]`（一次性 dev/debug 脚本，其 E402 为 `sys.path` 引导的**有意**写法）；`[tool.ruff.lint.per-file-ignores]` 对 `main.py`/`tests/conftest.py` 放行 **E402**（导入前必须 `sys.path.insert`）
- ✅ **`config.py`**：中段 `import sys as _sys`/`import io as _io`/`from typing import Optional as _Opt` 上移顶部；清理未用导入（`field`/`List`/`Optional`/`Tuple`）→ 消除 3×E402 + 4×F401
- ✅ **`valuation/wacc.py`**：`_credit_spread_for_icr` 展开为多行 → 消除 7×E701
- ✅ **`data/providers.py`**：缓存删除块、`datetime`/`DataSource` 反序列化块、`t_ret/s_ret` 切片、`_tax/_ebt` 初始化展开为多行 → 消除 8×E701 + 4×E702；删除死变量 `vals`
- ✅ **`classification/ml_classifier.py`**：歧义变量 `l → lab`（E741）；删除死变量 `cong_p`/`ml_used`
- ✅ **`analysis/sensitivity.py`**：删除死变量 `bear_wacc`/`bull_wacc`
- ✅ **`tests/test_scenario_sensitivity_consistency.py`**：删除未用的局部导入与 `provider = SyntheticDataProvider()`
- ✅ **`ruff --fix` 自动清理 35 处**：F401 未用导入、F541 无占位符 f-string、F841 死变量、E702 分号语句（跨 `analysis/expectation.py`、`data/akshare_provider.py`、`data/normalizer.py`、`data/validator.py`、`models/dcf.py`、`models/nav.py`、`reporting/dashboard.py`、`telegram_bot/telegram_bot.py`、`tests/*` 等）

Modified

- 新增 `pyproject.toml`（lint 标准）
- `config.py` / `valuation/wacc.py` / `data/providers.py` / `classification/ml_classifier.py` / `analysis/sensitivity.py` / `tests/test_scenario_sensitivity_consistency.py`
- 自动修复触及：`analysis/expectation.py`、`data/akshare_provider.py`、`data/normalizer.py`、`data/validator.py`、`models/dcf.py`、`models/nav.py`、`reporting/dashboard.py`、`telegram_bot/telegram_bot.py`、`tests/test_classifier.py`、`tests/test_dcf.py`、`tests/test_forecast.py`、`tests/test_ml_classifier.py`、`tests/test_risk.py`、`tests/test_secondary_profile.py`、`tests/test_sensitivity.py`

Created

- `pyproject.toml`

Notes

- 验证：`ruff check .` → **All checks passed!**；`python -m pytest -q` → **436 passed**（行为零回归，golden 零漂移）
- 未做（诚实记录）：`datetime.utcnow()`/`utcfromtimestamp()` 弃用告警（2156 warnings）不属 ruff 默认规则集，未处理——如需清理建议启用 flake8-datetimez（DTZ）后统一迁移为 timezone-aware

---

## 2026-11-14 (Session #35 — 用户代码审查 4 项 P1 修复)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：用户对引擎做第二轮代码审查，给出 **4 个 P1（高影响）** 缺陷并附修改建议。逐项定位 → 修码 → 定向核验 → `python -m pytest` → 有意重生成 golden → 重跑确认全绿。总纪律：**反对把市场估值按概率拆分冒充独立证据**、**不确定性必须传导而非仅提示**、**输入数据与模型实际使用数据显式区分**、**不兼容模型可展示但不得无条件进入共识**、**未声明口径 ≠ 冲突**。

Completed

- ✅ **P1-SOTP 循环估值（`models/sotp.py`）**：`_derive_segments_from_profile()` 用公司自身 `ev/revenue` 乘回 revenue → Operating EV ≈ 市场 EV，再按 ML `business_exposures` 拆分（先取市场估值再按概率分配）。修复：三态状态机（`SOTP_SOLVED`/`SOTP_APPROXIMATE`/`SOTP_INSUFFICIENT`）——仅真实分部财务 + 独立 peer multiple 计入共识；仅 ML 暴露度 → `display_only`（聚合层剔除）；`segments_detail` 输出每分部 Revenue/EBITDA/EBIT/Applied Multiple/Segment EV/Source/Confidence/As-of Date；修复 `operating_ev` 双重扣净债 bug
- ✅ **P1-6 多窗口 β 不稳定（`valuation/wacc.py`）**：VST 极差 0.95 却仍单一 β。修复：稳定性**参与估计**——Blume-style 收缩（`BETA_MAX_SHRINK=0.35`、`BETA_DISPERSION_SHRINK_THRESHOLD=0.50`，**不取平均**）+ `beta_raw`/`beta_selected`/`beta_adjusted` 三分离 + `beta_shrinkage`/`beta_dispersion`/`beta_uncertainty` + **β 不确定性传导至 WACC 区间**（`wacc_beta_lo`/`wacc_beta_hi`）
- ✅ **P1-7 报告 ETR 双数字（`reporting/dashboard.py`）**：`_market_section()` 改用 **WACC 实际使用 ETR**（`wacc_bd.effective_tax_rate`）+ `_etr_basis_suffix()`；供应商 ETR 另标 **Provider ETR**
- ✅ **P1-8 估值可比性 Gate（`models/base.py` + `analysis/model_agreement.py`）**：新增 `make_comparability()` + `ValuationResult.comparability`（DCF/Multiples/SOTP 接线）+ `_comparability_gate()` 7 维冲突检测（币种/口径/财务期间/估值日期/peer_valid/数据质量）；冲突模型从共识剔除并重算 `n_applicable`，**未声明口径不排除**

Modified

- `models/sotp.py`（三态重写 + `SOTPSegment` + `segments_detail` + 双重扣净债修复 + comparability）
- `valuation/wacc.py`（多窗口 β shrinkage + Raw/Selected/Adjusted 三分离 + `wacc_beta_lo`/`wacc_beta_hi`）
- `reporting/dashboard.py`（`_market_section()` ETR 口径分离 + `_etr_basis_suffix()`）
- `models/base.py`（`make_comparability` + `ValuationResult.comparability`）
- `models/dcf.py` / `models/multiples.py`（comparability 接线）
- `analysis/model_agreement.py`（`_comparability_gate` + 3 字段 + `analyze()` 剔除块）
- `tests/test_special_models.py`（SOTP 三态契约）/ `tests/test_model_agreement.py`（`TestComparabilityGate` 8 用例）
- `tests/golden/report_fingerprints.json`（因 SOTP→display_only 有意重生成一次）
- `DECISIONS.md`（ADR-050）/ `TODO.md` / `CHANGELOG.md` / `ROADMAP.md` / `README.md` / `AGENT.md`

Created

- （无新增模块；改动均为既有文件的契约/逻辑增强）

Notes

- 验证：`python -m pytest -q` → **436 passed**；定向核验：VST β `raw=2.3`/`adjusted≈1.89`/`dispersion=0.95`/`wacc_beta_lo≈0.104`/`hi≈0.147`；SOTP 无分部数据 → `INSUFFICIENT`+`display_only`+`n_independent_segments=0`、外部 segments → `SOLVED`+`n_independent_segments=2`；Gate 8 用例全绿
- Golden **有意重生成 1 次**：差异全部为 PLD/NOW/NBIS/CRWV/NU 的 SOTP→display_only（`n_solved` −1 / `n_display_only` +1 / `n_independent_evidence` −1），逐条核对为预期，非回归
- 未做（诚实记录）：`CANONICAL_KEY_WACC_RANGES` 仅覆盖 util 族 + 综合能源；FMP 在线分部需 key（真实分部接入后 SOTP 方可 SOLVED）；SOTP 独立 peer multiple 仍主要依赖行业默认表；M-16/C-02（真实标注 → 90%+）仍为唯一真实 BLOCKER

---

## 2026-11-14 (Session #34 — 用户代码审查 4 项 P0 修复)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：用户对引擎做代码审查，给出 **4 个 P0（必须优先修复）** 缺陷并附修改建议（Pasted text(1).txt + 四段定位说明）。逐项定位 → 修码 → 定向核验 → `python -m pytest` → 有意重生成 golden → 重跑确认全绿。总纪律：**反对伪精确**（行业区间读身份键，不靠字符串巧合）、**口径显式可审计**、**拒绝为凑漂亮数字掩盖口径冲突**、**风险方向必须如实**。

Completed

- ✅ **P0-1 行业 WACC 区间匹配错误（`valuation/wacc.py`）**：`"Utility"` ⊄ Yahoo 的 `"Utilities"` → VST 类静默落入 `DEFAULT_INDUSTRY_RANGE=(6.5%~11.5%, Market Average)`。修复：关键词改 `"Utilities"`（保留单数兼容）+ 新增 `CANONICAL_KEY_WACC_RANGES`（`util.electric`/`util.gas`/`util.water`/`util.ipp`/`util.diversified`/`en.oil_gas.integrated` **各自独立区间**，IPP 与受管制公用事业分属不同经济模型）+ `_normalize_industry_text()`（em/en dash 归一化命中年报字符串）+ `_match_industry_range()` 四级优先级（canonical key → `node_from_yahoo()` → 关键词表 → 默认）+ `WaccBreakdown.industry_range_source`
- ✅ **P0-2 ETR 重复计算重叠期间（`valuation/wacc.py::_effective_tax_rate`）**：原先 TTM + `annual_income[:3]` **相加** → 最新财年双重加权。修复：非重叠期间策略（TTM-only / 去重财年 / 法定默认）+ 返回值升级 3 元组 + `WaccBreakdown.tax_period_basis ∈ {ttm, fyN, default}`
- ✅ **P0-3 每股估值分母不统一（`models/*` + `analysis/model_agreement.py`）**：新增 `ShareCountBasis`/`ShareCount`/`make_share_count()` + `ValuationResult.share_count`，四模型申报口径；共识层 `_resolve_share_reference()` + 可比性校验（偏差 >`SHARE_COUNT_COMPARABLE_TOL=0.10` 剔除出中位数，`share_count_excluded_models` 记录，`n_applicable` 扣减）；**保留 EV/Equity Value 独立参考，不重写股数凑中位数**
- ✅ **P0-4 FCF Yield Gap 风险方向误判（`analysis/risk.py`）**：`abs(fcf_yield-0.04)/0.04` 对称偏差 → VST 5.03% 误标 High。修复：非对称方向感知（正 FCF ≥ 锚点不判风险 / < 锚点仅估值观察 + materiality gate / 负 FCF 按恶化幅度与持续性）+ `_fcf_trend()` + `_downgrade()` + `fcf_yield_reference` 可配置参考

Modified

- `valuation/wacc.py`（`CANONICAL_KEY_WACC_RANGES` / `_normalize_industry_text` / `_match_industry_range` 4 元 / `_effective_tax_rate` 3 元 / `WaccBreakdown.industry_range_source` + `tax_period_basis`）
- `models/base.py`（`ShareCountBasis` / `ShareCount` / `make_share_count` / `ValuationResult.share_count`）
- `models/dcf.py` / `models/reverse_dcf.py` / `models/multiples.py` / `models/sotp.py`（`share_count` provenance + breakdown）
- `analysis/model_agreement.py`（`_resolve_share_reference` + 可比性校验块 + 新字段 + notes）
- `analysis/risk.py`（`_forecast_risk` Layer B 非对称重写 + `_fcf_trend` + `_downgrade`）
- `config.py`（`SHARE_COUNT_COMPARABLE_TOL` + `RISK_THRESHOLDS[FORECAST]` 新阈值）
- `tests/golden_report.py`（指纹 +`share_ref_source` / `share_count_excluded`）+ `tests/golden/report_fingerprints.json`（有意重生成一次）
- `TODO.md` / `CHANGELOG.md` / `DECISIONS.md`（ADR-049） / `AGENT.md`

Created

- （无新增模块；改动均为既有文件的契约/逻辑增强）

Notes

- 验证：`python -m pytest -q` → **429 passed**；定向核验：IPP→`(6.5%,9.8%, Independent Power Producer (Merchant))`、ETR basis=`ttm`/`fy2`/`default`、AAPL P/E 因口径偏差 100% 被剔除（中位 132.19→123.99）、KR High→Medium、XOM/AAPL 假 FCF 旗标消失
- Golden **有意重生成 1 次**：差异全部为 P0-4（FCF 旗标移除/降级）与 P0-2（ETR→WACC→DCF 中位微调），逐条核对为预期行为修正，非回归
- 未做（诚实记录）：`CANONICAL_KEY_WACC_RANGES` 仅覆盖 util 族 + 综合能源；M-44（隐含 FCF 利润率/终值增长率 bound 措辞）；FMP 在线分部需 key；M-16/C-02（真实标注 → 90%+ 准确率）仍为唯一真实 BLOCKER

---

## 2026-11-14 (Session #31–#33 — 50 只跨行业蓝筹全量验证 + Reverse DCF 递归自我改进 3 轮)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：用户给出 50 只跨行业蓝筹并明确要求「测试 → 产出结果作为下一轮起点 → 修复」的 **3 轮递归自我改进**。以 `_batch_eval.py`（50 标的离线全量审计 → JSON）+ `_audit_summary.py`（紧凑五问）为**可断言产出**，每轮「评估产出 → 定位缺陷 → 修码 → 重跑」。总纪律：**绝不伪造**（不合理的点估改为诚实 bound / 拒绝输出），**数据驱动而非调阈**（每处阈值变更都由真实样例证据驱动）。

Completed

- ✅ **Round 1（Session #31）**：`models/reverse_dcf.py::calculate` 新增**结构化 bound** —— 市场价超出业务类型 sanctioned growth band 时输出 `implied_revenue_cagr_bound={kind, value, ev_at_bound}`（`above_band_ceiling`→「≥ 上限」/`below_band_floor`→「≤ 下限」），而非伪造点估；仅 `bridge_broken` 时启用 normalized 救援。新建 `_batch_eval.py` + `_audit_summary.py`
- ✅ **Round 2（Session #32）**：缺陷 #1（`_implied_section` 与 `_gap_section` 对同一标的一 bound 一 N/A 自相矛盾）→ `ExpectationGap` 新增 bound 字段并透传 + `_gap_section` 镜像措辞（PG 端到端一致）；缺陷 #2（CV 假 High）→ 初版 σ 门；`_batch_eval.py` 增记 risk flag、`_audit_summary.py` 增 Q4b 风险底线；新建 `_diag_risk.py` / `_audit_risk_detail.py`
- ✅ **Round 3（Session #33）**：缺陷 #3（σ 门不足：SO σ≈10.5pp 恰越阈、PLD/VICI 单调收购爬坡被当波动风险）→ `_growth_risk()` 改 **下行离散度** `dd=RMS(min(growth,0))`（`growth_dd_medium=0.05`/`growth_dd_high=0.10`）；缺陷 #4（隐含 WACC 低于 Rf：DUK 2.3%/SO 2.7%/CEG 3.3%）→ `dcf._estimate_wacc_breakdown()` 暴露 Rf 单一真理源 + `reverse_dcf` 以 Rf 为 implied-WACC 下限（sub-Rf → `NO_SOLUTION_IN_RANGE` + `implied_wacc_floor_rf`）

Modified

- `models/reverse_dcf.py`（结构化 bound；Rf 透传 + implied-WACC 下限）
- `models/dcf.py`（`_estimate_wacc_breakdown()`）
- `analysis/expectation.py`（`ExpectationGap` bound 字段 + 透传）/ `reporting/dashboard.py`（`_gap_section` 镜像）
- `analysis/risk.py`（`_growth_risk` 下行离散度）/ `config.py`（`growth_dd_*` 阈值）
- `_batch_eval.py` / `_audit_summary.py`（审计字段 + Q4b）
- `tests/golden/report_fingerprints.json`（因行为修正二次重生成）
- `TODO.md` / `ROADMAP.md` / `CHANGELOG.md` / `DECISIONS.md` / `AGENT.md`

Created

- `_batch_eval.py`（50 标的审计 harness，Round 1）
- `_audit_summary.py`（五问紧凑摘要，Round 1）
- `_diag_risk.py`（增长序列 + σ/CV 诊断，Round 2）
- `_audit_risk_detail.py`（Growth Risk 证据 dump，Round 2）

Notes

- 验证：`python -m pytest -q` → **429 passed**；`python _batch_eval.py round3` → `50/50 = 100.0% | routing_viol=0 | defects=0`；`implied_wacc < 0.045` 计数 = **0**
- Golden 重生成 2 次，差异**全部为 Growth Risk 移除/降级**（MSFT/BAC/UPS/GOOGL/PLD/VICI/CEG/AMT…），无任何新增旗标 —— 经逐条核对为预期行为修正，非回归
- 未做（诚实记录）：Round 3 后隐含 FCF 利润率 / 隐含终值增长率在部分标的仍为 `NO_SOLUTION_IN_RANGE`（可给 bound 措辞）；FMP 在线分部需 key；M-16/C-02（真实标注 → 90%+ 准确率）仍为唯一真实 BLOCKER

## 2026-11-14 (Session #30 — M-39：SEC filing-instance XBRL 生产化接入 providers 主链 + M-32：Taxonomy 参与路由)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：承接 Session #29 收尾时诚实记录的缺口「filing_evidence 尚未在 providers 主链自动接线」与用户两阶段要求。**阶段 A（M-39）**：把 M-38 的 `filing_evidence` 从「可用入口」变「生产默认路径」——新增 `segment_revenue.resolve_segments(ticker)` 单一源链入口（Layer 1 FMP → Layer 2 SEC 10-K/20-F filing-instance XBRL，两层皆空 → `[]`，绝不伪造），`providers.py` 改调源链，FMP 缺 key / 失效 / 额度耗尽 / ticker 未覆盖时自动降级 SEC 一手分部；仍为 shadow 数据填充（不改 `business_type`/路由）。**阶段 B（M-32）**：taxonomy 从 additive shadow 切换为**参与路由**——用户口径为「CONFIRMED + 尊重经济特征护栏」「golden 不重生成、保持零漂移」「跨族冲突才覆盖 + 护栏」。关键设计纠错：gate 对比**内部身份判定 `best_bt`** 而非 `routing_bt`（后者是 Phase 1.3 ambiguous 保守估值路由，GOOGL 会取 `TELECOM` → 若对比会跨族误覆盖、golden 漂移）。

Completed

- ✅ **阶段 A（M-39）**：`data/segment_revenue.py::resolve_segments(ticker, *, client, offline, fmp_cache_path, filing_cache_path, identity_resolver)` —— Layer 1 `SegmentRevenueResolver(...).get_segments(ticker)`（FMP，需 key），非空即返回；Layer 2 **惰性** `from data.filing_evidence import FilingBusinessExtractor`（避免与 `filing_evidence` 循环 import）→ `get_segments()`（SEC filing-instance XBRL，免 key），异常/空 → `[]`；`data/providers.py` 改调源链 → FMP 无 key / 失效 / 额度耗尽 / 未覆盖时自动降级到 SEC 一手分部
- ✅ **阶段 B（M-32）**：`classification/taxonomy.py` 新增 `TAXONOMY_ROUTING_STATUSES = frozenset({DecisionStatus.CONFIRMED})` + `_archetype_family_index()`/`ARCHETYPE_FAMILIES`（由 `IDENTITY_NODES` 树推导）+ `same_identity_family()` + `taxonomy_routing_override(internal_bt, taxonomy_key, decision_status=None, *, guard_blocked=False)`（**三道 gating**：① CONFIRMED；② canonical 身份与内部身份判定跨 identity family 冲突；③ 经济护栏未拦截）；`attach_taxonomy_profile(..., tp=...)` 复用同一 profile
- ✅ **双路径接线**：`classifier.py`（规则路径，`_model_applicability()` 前构建 `_taxonomy` + 新增 `_asset_light_guard_blocked()` staticmethod）与 `ml_classifier.py`（ML 路径，economics 用 raw ML top-1）对称 gate；gate 通过 → `business_type = _routed_business_type.value`
- ✅ **关键纠错**：gate 对比 `best_bt`（身份判定）而非 `routing_bt`（估值路由）；两文件注释明写 "comparison is against the verdict, not routing_bt"
- ✅ **测试**：`tests/test_taxonomy.py` 新增 `TestTaxonomyRoutingGate`（12 用例）+ tension basket（ORCL/NBIS/CRWV：`taxonomy_identity_key="tech.software.infra"` 但 `business_type="MatureTech"`）

Modified

- `data/segment_revenue.py`（+`resolve_segments()` 源链）/ `data/providers.py`（改调源链）
- `classification/taxonomy.py`（routing gate）/ `classification/classifier.py`（gate + 护栏）/ `classification/ml_classifier.py`（对称 gate）
- `tests/test_taxonomy.py`（+`TestTaxonomyRoutingGate`）/ `TODO.md` / `ROADMAP.md` / `CHANGELOG.md` / `DECISIONS.md`（ADR-046/047）/ `AGENT.md`

Created

- （无新文件；均为现有文件扩展）

Notes

- 验证：`python -m pytest -q` → **429 passed**（Session #29 基线 413 + 16：TestTaxonomyRoutingGate 12 等）；golden 指纹 **零漂移（未重生成）**；改动模块/新测试 Ruff clean
- 口径冲突消解：「taxonomy 参与路由」与「golden 零漂移」通过**跨族冲突才覆盖**的窄门结构性统一 —— 同族差异（如 `MatureTech` vs `SaaS`）不覆盖，归经济驱动分类器所有，18 只 basket 无漂移风险
- 未做（诚实记录）：FMP 在线分部（需 `FMP_API_KEY`）、M-33（GICS/NAICS）、分部 label → 行业映射（`_SEGMENT_INDUSTRY_KEYWORDS`，现 107/172）、M-16/C-02（真实标注 → 准确率 90%+，唯一真实 BLOCKER）

## 2026-11-14 (Session #29 — M-38：SEC 10-K / 20-F filing-instance XBRL 业务证据抽取 + 四态决策端到端测试)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：承接 Session #28 收尾时诚实记录的缺口「10-K / 20-F XBRL 业务抽取未做」，逐项补齐。设计路径由「绝不伪造 + drop-in 兼容」两条纪律约束：**SEC `companyfacts` 无 dimensional 数据**已知，故不走 `companyfacts`，改解析 **filing-instance XBRL**（10-K/20-F 内嵌 `*_htm.xml`）；产出直接复用既有 `segment_revenue.Segment` + `to_revenue_composition`，不扰动 taxonomy/β 管线。同步补「四态决策契约端到端测试」，把 Session #28 的 shadow 接线（`attach_taxonomy_profile` → `CompanyProfile.taxonomy_decision_status`）从「单元级」升级为「真实 builder/classifier 全链路」断言。

Completed

- ✅ **`data/filing_evidence.py`（新建）**：`FilingRef` + `FilingBusinessExtractor`（CIK → `data.sec.gov/submissions/CIK{cik}.json` 的 `filings.recent`（newest first）→ 首个 `10-K`/`20-F` → filing `index.json` 优选 `*_htm.xml` 实例）+ `parse_segment_revenue(xml)` **纯函数**（`xbrli:context` → `(endDate, axis, member)`；**仅取带 segment 轴的事实**；`_AXIS_PRIORITY` 单轴聚合；**排除合并总额**；**取最新期间**；instant context 忽略；us-gaap + ifrs-full revenue concept）
- ✅ **drop-in 兼容**：`get_segments()` 返回 `segment_revenue.Segment` + `source="sec-xbrl"`，可直接喂 `to_revenue_composition()`；`_MEM` + `.cache/filing_evidence.json` 磁盘缓存；`offline` 零网络
- ✅ **绝不伪造**：无 CIK / 无实例 / 解析失败 / malformed XML → `[]`；`_get()` 带合规 `User-Agent`
- ✅ **四态决策端到端测试**：`tests/test_taxonomy.py::TestDecisionContractEndToEnd` 6 用例（真实 `build_taxonomy_profile`/`attach_taxonomy_profile`/ML 标签）

Modified

- `tests/test_taxonomy.py` → 追加 `TestDecisionContractEndToEnd`（6 用例）
- `DECISIONS.md`（ADR-045）/ `CHANGELOG.md`（Session #29）/ `AGENT.md` / `TODO.md`（M-38 → DONE）/ `ROADMAP.md`

Created

- `data/filing_evidence.py`（SEC filing-instance XBRL 业务证据抽取）
- `tests/test_filing_evidence.py`（9 用例）

Notes

- 验证：`python -m pytest -q` → **413 passed**（Session #28 基线 398 + 本轮 15：filing_evidence 9 + 端到端 6）；`ruff check` 对改动模块/新测试**全通过**；golden 指纹**零漂移**
- 纠错（承前）：**勿再试 SEC `companyfacts` 取分部**（无 dimensional 数据）；本次以 filing-instance XBRL 补齐 FMP 无 key 时的缺口
- 未做（诚实记录）：`filing_evidence.get_segments()` **尚未在 `data/providers.py` 主链自动接线**（当前为独立入口，未在 FMP 缺 key 时自动回退）；taxonomy/四态参与路由（M-32）仍待 golden 有意漂移审阅

## 2026-11-14 (Session #28 — 商业理解层（Business Intelligence Layer）：六模块映射 + 四态决策契约 + Identity Resolution)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户《最终确定的五维分类体系》提案（要求正式化为 Universal Business Taxonomy & Intelligence Engine + 六模块划分）为输入。逐项对照现有代码得出差距分析：提案约 **70% 已落地**（五维 Taxonomy / 三源数据链 / bottom-up β 三级筛选 + Segment-level β / Valuation Router）。真实缺口三处：① 无 Identity Resolution 层；② 无 Business Evidence 收集器；③ 分类裁决缺「能否据此行动」四态契约。用户三项决策（范围＝按 6 模块重构 / 命名＝保留现名正式化「商业理解层」/ 形态＝不重组原位扩展）→ 以「原位扩展」执行：缺失模块新建、既有逻辑零迁移、新模块仅做薄封装/新能力，从而既得 6 模块表面又不破坏 import 与 golden 基线。

Completed

- ✅ **四态决策契约**：`classification/taxonomy.py` 新增 `DecisionStatus`（CONFIRMED/PROBABLE/AMBIGUOUS/INSUFFICIENT_DATA）+ `_ECONOMICS_ONLY_MIN_CONF=0.55` + `_DECISION_LABELS` + `decide_status()`（确定性映射）；`BusinessTaxonomyProfile` +`decision_status`；`audit_lines()` 追加「◆ 决策状态」；`attach_taxonomy_profile()` 写 `taxonomy_decision_status`
- ✅ **Identity Resolution 层**：新建 `data/identity_resolver.py`（`IdentityResolver`/`ResolvedIdentity`：CIK/SIC/Figi；Layer A 复用在位 SEC 链 + Layer B OpenFIGI 需 key；缺失一律 None 绝不伪造）
- ✅ **Business Evidence 收集器**：新建 `classification/business_intelligence.py`（`extract_business_evidence()`：业务描述 + 分部收入 + provenance；缺失显式标注）
- ✅ **SEC 链复用入口**：`data/industry_resolver.py` 新增 `resolve_identity()`
- ✅ **shadow 字段**：`data/models.py` `CompanyProfile` +`taxonomy_decision_status`
- ✅ **测试**：`TestDecisionContract` 7 + `tests/test_identity_resolver.py` 5 + `tests/test_business_intelligence.py` 4

Modified

- `classification/taxonomy.py` / `data/industry_resolver.py` / `data/models.py` / `tests/test_taxonomy.py`
- `DECISIONS.md`（ADR-044）/ `CHANGELOG.md`（Session #28）/ `AGENT.md` / `TODO.md`（M-37）/ `ROADMAP.md`

Created

- `data/identity_resolver.py`（Identity Resolution 层）
- `classification/business_intelligence.py`（Business Evidence 收集器）
- `tests/test_identity_resolver.py` / `tests/test_business_intelligence.py`

Notes

- 验证：`python -m pytest -q` → **398 passed**（Session #27 基线 382 + 16 新增）；分步 `test_taxonomy.py + test_identity_resolver.py + test_business_intelligence.py` → **64 passed**；golden 指纹**零漂移**（四态为 shadow，不改 `business_type`/`applicable_models`/路由）
- 三条架构原则结构化落地（用户明确要求）：① 单源不得覆盖内部分类（taxonomy 为仲裁层，外部标签原样留于 ⑤）；② ML 错误分类不得直接影响 WACC/估值（`ECONOMICS_ONLY` 需置信度门控，路由仍由 taxonomy 决定）；③ 缺收入证据不得强赋高置信度（`BusinessEvidence` 缺失显式化 + `INSUFFICIENT_DATA` 态）
- 未做（诚实记录，见 TODO M-37 之外）：10-K/20-F XBRL 业务抽取（本次仅证据收集器）；四态/taxonomy 参与路由切换（同 M-32 取舍）

## 2026-11-14 (Session #27 — M-35 收尾迭代：FMP 多 key 轮换 + `/stable` 新端点 + Shape C 解析 + 分部→行业关键词表数据驱动补全)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户「我有两个 FMP_API_KEY（写入 .env）+ 分部→行业关键词表数据驱动补全」为输入。核心实测纠错：（1）`FMP_API_KEY=key1,key2` 会被整体当单 key → 实现**按序轮换**；（2）FMP `/api/v4`、`/api/v3` 遗留端点自 **2025-08-31 起 403 `Legacy Endpoint`** → 分部收入改用 **`/stable/revenue-product-segmentation`**；（3）`/stable` 为**新 Shape C**（元数据外层包裹嵌套 `data`）→ 旧解析会把 `fiscalYear` 误当分部，须新增分支。随后以真实语料（90 只多业务大票 → 41 只解析成功 → 172 distinct label）驱动**两轮关键词表补全**（覆盖 102 → 107）。全程「绝不伪造 + 只增不改 + 桶/地理/品牌名/缩写恒不映射」。

Completed

- ✅ **FMP 多 key 轮换**：`data/segment_revenue.py` 新增 `_fmp_keys()`（逗号分隔 + strip 空白）+ `_from_fmp(url, base_params)`（按序尝试，非 200/不可解析透明落到下一 key，**全耗尽 → `[]`**）
- ✅ **`/stable` 新端点为首层**：新增 `_FMP_STABLE`；层优先序 `_from_fmp_stable` → `_from_fmp_v4` → `_from_fmp_v3`
- ✅ **Shape C 解析**：`_extract_fmp` 新增分支识别 `[{...,"fiscalYear":..,"period":..,"date":..,"data":{label:val}}]`，只取嵌套 `data`，元数据不泄漏为分部
- ✅ **关键词表数据驱动两轮补全**：`data/industry_beta.py::_SEGMENT_INDUSTRY_KEYWORDS`——Round 1（~40 业务线词）+ Round 2（~6 残余可复用词）；覆盖真实语料 **102 → 107 / 172**
- ✅ **测试**：Shape C（含元数据防泄漏）/ `/stable` 优先 / 多 key 轮换三方用例 + Round 2 映射锁定 + 「恒不映射」负向断言

Modified

- `data/segment_revenue.py`（多 key + `/stable` + Shape C）/ `data/industry_beta.py`（关键词表两轮补全）/ `tests/test_segment_revenue.py` / `tests/test_industry_beta.py`
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md`（ADR-043）/ `TODO.md`（M-35 收尾 + 新增 M-36）/ `ROADMAP.md`

Created

- `_discover_segment_labels.py`（数据驱动发现工具：拉真实分部 label → 对当前关键词表算覆盖/缺口，**留存复用**）
- `_segment_labels_discovered.json`（发现输出：172 distinct label + uncovered/no_segments）

Notes

- 验证：`python -m pytest -q` → **382 passed**（Session #26 基线 376 + 6 新增），golden 指纹**零漂移**（关键词表只增不改；离线解析路径不变）
- 临时探测脚本 `_tmp_fmp_probe.py` 已删除；发现工具与 JSON 留存（与仓库既有 `_*.py` 开发脚本惯例一致）
- 残余 65 个未映射 label 中约 39 个（桶/地理/品牌名/缩写）**必须保持不映射**；其余为发行人专属/歧义词 → 交由公司级 β 透明回退（对单业务发行人为正确结果）
- `FMP_API_KEY` 已落盘 `.env`（`key1,key2`）

## 2026-11-14 (Session #26 — 分部收入数据层 (M-31) + Segment-level β (M-35))

AI Agent

```
DeepSeek-based Agent (TRAE)
```

> 注：本条为本会话（#27）补录的 #26 摘要；完整细节见 `CHANGELOG.md` Session #26 与 **ADR-042**。

Completed

- ✅ **`data/segment_revenue.py`（M-31）**：FMP `/revenue-product-segmentation` 为主源（无 key → `[]`）；`Segment` / `SegmentRevenueResolver`（类级 `_MEM` + 磁盘缓存）/ `to_revenue_composition` / `segment_weights(by="value")`（营业利润优先、回退收入）
- ✅ **`derive_segment_level_beta()`（M-35）**：逐分部 label→行业→复用 M-34 三级筛选求 β_u→按权重加权→cash-adjust→relever（`level=0` / `source="segment-weighted"`）；门控 `min_segments=2` + `_MIN_SEGMENT_COVERAGE=0.60` → 透明回退公司级
- ✅ **接线（add）**：`FinancialData.revenue_composition` + taxonomy 消费端 + `data/providers.py`；**关键纠错**：SEC `companyfacts` 不含 dimensional 分部数据 → 改用 FMP
- ✅ +23 用例；pytest **353 → 376**；golden 零漂移

Modified

- `data/segment_revenue.py`（新建）/ `data/industry_beta.py` / `data/models.py` / `classification/taxonomy.py` / `data/providers.py` / `tests/test_segment_revenue.py` / `tests/test_industry_beta.py`
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md`（ADR-042）/ `TODO.md`（M-31 + M-35 收口）/ `ROADMAP.md`

Created

- `data/segment_revenue.py`

Notes

- 详见 `CHANGELOG.md` Session #26；ADR-042

## 2026-11-14 (Session #25 — Bottom-up β 升级「业务身份三级筛选 + 完整 β 链」接入 CAPM，M-34)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户「先升级 bottom-up β 再做 M-34」为输入。核心洞察：Session #24 的 bottom-up β 用裸 `get_companies_by_industry(industry)` 选同业，会把**异质**公司（fabless 设计 vs 重资产代工晶圆厂）混入中位 → β 不代表目标公司**真实商业风险**。故改为**按业务身份三级筛选**同业，并补齐「Peer Levered → Hamada Unlevered → Median → Cash-adjusted → Target Relevered」完整 β 链，最后以**三段优先级**接入 CAPM（同时保持 `resolve_effective_beta()` 单一 β 出口）。L3 采用**内置 Damodaran 真实快照**（未覆盖→None）；接线为 **add**（离线 golden `bottom_up_beta=None` → 零漂移）。

Completed

- ✅ **业务身份三级筛选**：`data/industry_beta.py::get_companies_by_business_identity(sub_industry=..., business_model=..., economic_profile=...) -> PeerScreen`——**L1** 同 Sub-industry + Business Model（`model_resolver` 注入；未提供则按子行业筛选不按模型过滤）→ **L2** 相邻行业（同 sector）+ 相似经济特征（`_profile_matches` 比较 `is_capex_heavy`/`is_loss_making`/`is_asset_light`，缺失不算不匹配）→ **L3** Damodaran 行业基准；逐级回退直到凑够 `_MIN_PEERS=3`
- ✅ **完整 β 链**：`_unlever`（Hamada）→ `_cash_adjust`（`β_u/(1−Cash/Firm)`，`_CASH_TO_FIRM_CAP=0.90`）→ `_relever`（`β_L = β_u × (1+(1−t)·D/E_target)`）；`IndustryBetaResult` 暴露 `beta_unlevered`/`beta_cash_adjusted`/`beta_relevered`/`cash_to_firm`/`target_d2e`/`tax_rate`/`level`/`rationale`/`peer_levered`/`peer_unlevered` + `note()`/`to_chain()`
- ✅ **L3 内置真实快照（绝不伪造）**：新建 `data/damodaran_beta.json`（Aswath Damodaran NYU Stern，**Jan 2026** 快照，100 行业，字段 `unlevered_beta`/`unlevered_beta_cash_adjusted`）；`_DAMODARAN_ALIASES`（~80 条 Yahoo→Damodaran 别名，`_normalize_industry` 归一 en/em-dash）；**文件缺失或行业未覆盖 → L3 返回 None**
- ✅ **`derive_bottom_up_beta(...)`**：编排三级筛选 → β 链 → `IndustryBetaResult`（缓存 key `{sector}|{industry}[|{business_model}]`）；`derive_industry_unlevered_beta(...)` 保留为向后兼容窄访问器
- ✅ **接入 CAPM 三段优先级**：`valuation/wacc.py::calculate()`——① bottom-up（cash-adjusted + target-relevered，winsorize 至 `[0.30, 2.50]`）优先 → ② 缺失回退现有回归 β → ③ 都无则 `default_unlevered_beta`；`WaccBreakdown` 新增 `beta_bottom_up`/`beta_bottom_up_note`
- ✅ **`clamped` 语义修正**：`resolve_effective_beta()` 的 `clamped` 现意为「**原始回归 β** 超出 CAPM 带」，bottom-up 被选用不再被误报为截断
- ✅ **接线为 add**：`data/models.py::MarketData` 新增 `bottom_up_beta`/`bottom_up_beta_chain`（`industry_beta` 保留为原始 peer-median unlevered）；`data/providers.py::MarketData(...)` 接线；`analysis/risk.py` / `reporting/dashboard.py` 文案配套
- ✅ **测试**：`tests/test_industry_beta.py` 由 12 → **32 用例**（+20）——cash-adjust/relever 数学、三级筛选 L1/L2/L3、Damodaran alias/unmatched/缺文件、完整链、CAPM 三段优先级 / winsorize

Modified

- `data/industry_beta.py`（重写为「三级筛选 + 完整 β 链」）/ `data/models.py`（MarketData +2 字段）/ `valuation/wacc.py`（CAPM 三段优先级 + clamped 语义）/ `data/providers.py`（bottom-up β 接线）/ `analysis/risk.py` / `reporting/dashboard.py` / `tests/test_industry_beta.py`
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md`（ADR-041）/ `TODO.md`（M-34 收口 + 新增 M-35）/ `ROADMAP.md`

Created

- `data/damodaran_beta.json`（Damodaran 行业 unlevered β Jan 2026 快照，100 行业）

Notes

- 验证：`python -m pytest -q` → **353 passed**（Session #24 基线 333 + 20 新增），golden 指纹**零漂移**（`test_golden_report` 通过）
- Ruff：新增/重写模块 `industry_beta.py` 与新测试文件 **clean**（仓库根无 ruff/black 配置；其余 26 条为未改动旧代码的 pre-existing debt）
- 接线为 add：离线 golden 的 `MarketData` 不带 `bottom_up_beta`（`None`）→ wacc 走回退回归 β 分支，基线不变
- L3 绝不伪造：alias 命中 / unmatched→None / 缺文件→None 三态均有测试锁定；内置快照可用
- 多业务公司 Segment-level β 留作 **M-35**（依赖 M-31 分部数据），非本次范围

## 2026-11-14 (Session #24 — 三源 sector/industry 补全链 + bottom-up β 唤醒，H-03)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户「用三个库补全 `sector/industry`，同时唤醒 bottom-up β 并提升分类准确率」为输入。核心洞察：Yahoo `quoteSummary/assetProfile` 长期 401（约 83%）导致 `sector/industry` 大面积为 `None` → 分类器 layer-2 硬规则（+3.0）整体失效、ML 文本特征丢失最强信号。故引入**离线/权威数据源**（本地元数据 + 一手监管 SIC + 百科兜底）作为补全链，并把长期空置的 `MarketData.industry_beta` 槽位用**动态同业无杠杆 β（Hamada）**唤醒。三源链贯彻「绝不伪造」原则。

Completed

- ✅ **SEC SIC → Yahoo 桥接**：新建 `data/sic_map.py`——`SIC_TO_YAHOO`（约 180 条精确 4 位）+ `SIC2_TO_YAHOO`（约 68 条 2 位大类）+ `SIC_DESC_KEYWORDS`（约 130 条关键词，按具体→宽泛排序，`semiconductor` 先于 `software`）；`map_sic_to_yahoo(sic, desc)` 顺序：精确 4 位 → 2 位大类 → 描述关键词；契约：**每个映射产出必须能被分类器硬规则消费**，否则返回 None
- ✅ **三源 sector/industry 解析器**：新建 `data/industry_resolver.py`——`SectorIndustryResolver` 优先级链 ① FinanceDatabase（30 万+ 离线 Yahoo 兼容，无 HTTP）→ ② SEC EDGAR（`company_tickers.json` 取 CIK → `submissions/CIK*.json` 取官方 `sic`/`sicDescription`）→ ③ Wikidata SPARQL P452 兜底；类级 `_MEM` + `.cache/` 磁盘缓存 + `batch_get()`；SEC 带合规 `User-Agent`（`SEC_USER_AGENT` 可配）；任一源缺失/断网返回 `{}` 继续下一层
- ✅ **bottom-up 同业无杠杆 β（Hamada）**：新建 `data/industry_beta.py`——`derive_industry_unlevered_beta()`：同业列表（FinanceDatabase）→ 逐 peer β/D-E（yfinance）→ `β_u = β_L/(1+(1−t)·D/E)`（`t=0.21`）→ 取**中位**（抗离群）；`IndustryBetaResult.note()` 人类可读溯源；**<3 家同业或无可得 β 返回 None（绝不伪造）**；`BOTTOM_UP_BETA=0` 可关；缓存 `{sector}|{industry}`
- ✅ **providers 接线**：`data/providers.py::_fetch_quote_summary_simple` 在 Layer-3 resolver 块后新增 bottom-up β 块 → 填充 `MarketData.industry_beta`（审计槽位不再恒为 `None`）
- ✅ **分类覆盖缺口修复**：`classification/classifier.py::SECTOR_INDUSTRY_MAP` 新增 `("asset management", BusinessType.BANK)`（修复 SEC SIC "6726"/"67" → "Asset Management" 经 `map_sector_industry()` 返回 None 的唯一缺口）
- ✅ **测试**：新建 3 个测试文件共 **45 用例**——`tests/test_sic_map.py`（24 用例，含「每个映射产出必可分类」守卫 + 关键词有序性）/ `tests/test_industry_resolver.py`（12 用例，三源链离线 monkeypatch + 磁盘缓存 + offline）/ `tests/test_industry_beta.py`（15 用例，Hamada 数学 + 中位 + 不伪造下限 + 目标剔除 + 缓存 + env 开关）
- ✅ **在线实测**：SEC 层 **10/10 精确命中**（AAPL→Computer Hardware、NVDA→Semiconductors(3674)、JPM→Banks-Diversified(6021)、PLD→REIT-Diversified(6798)、XOM→Oil&Gas Refining(2911)、MSFT→Software-App(7372)、BRK-B→Insurance-P&C(6331)、KR→Grocery Stores(5411)、AMZN→Internet Retail(5961)、BLK→Capital Markets(6211)）；layer-2 硬规则覆盖 **18/23 = 78.3%**（此前被 401 阻断）；Semiconductors 同业 bottom-up 无杠杆 β = **1.2447**

Modified

- `data/providers.py`（bottom-up β 接线）/ `classification/classifier.py`（asset management 映射）
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md`（ADR-040）/ `TODO.md`（H-03 收口）/ `ROADMAP.md`

Created

- `data/sic_map.py`（SEC SIC → Yahoo taxonomy 桥接）
- `data/industry_resolver.py`（三源 sector/industry 解析器）
- `data/industry_beta.py`（bottom-up 同业无杠杆 β）
- `tests/test_sic_map.py` / `tests/test_industry_resolver.py` / `tests/test_industry_beta.py`（共 45 用例）

Notes

- 验证：`python -m pytest -q` → **333 passed**（288 基线 + 45 新增），golden 指纹**零漂移**（`test_golden_report` 通过）
- Ruff：本次新增/改动 6 文件 `All checks passed!`
- 未达目标（诚实标注）：分类硬规则命中率 78.3%，**未达 90%**——剩余 5 只为真值/粒度差（ASML/QCOM/MSFT/XOM/BRK-B），非 `None` 缺口；推高到 90%+ 需 M-16（hybrid 阈值复评）+ C-02（真实标注重训）
- bottom-up β 当前仅作**审计展示**（`WaccBreakdown.beta_transparency_note()`），**不参与 CAPM 标量 β**（升级须单独审阅）
- 三源链为 **optional import + 优雅降级**：库未装/断网 → 返回 `{}` 继续下一层，全失败返回 `{}`（不伪造）

## 2026-11-14 (Session #23 — 内部标准 Taxonomy + 五维公司拆解 + 黄金法则)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户《行业 taxonomy 映射层》设想为输入，落地为 **五维公司拆解模型**。核心原则（**黄金法则**）：**财务/经济特征可以帮助判断经济模式，但不能单独决定 Business Identity**——高毛利率 + 高 CapEx + 低负债不足以证明一家公司是 Semiconductor（它可能只是经营大型 AI 数据中心的 Software/Cloud 公司）。因此 economics 只能在**同一 family 内细化** identity，跨族一律不提升；同族兄弟冲突收敛至 **common ancestor**（绝不用经济学节点冒充 Identity）。

Completed

- ✅ **内部标准 Taxonomy（99 节点树）**：新建 `classification/taxonomy.py`——canonical key 点分层级（`tech.software.infra`）+ `label` + `parent` + `business_type`(archetype) + `depth`；族根为无点 key；`depth` 由 **parent 链** `_structural_depth()` 推导（**非** `key.count(".")`，修复 `cons.cyclical` 这类分组节点的子节点与父同点深度的语义偏差）；`IDENTITY_NODES` 单一真源
- ✅ **五维模型**：① **Business Identity**（Software Platform / Semiconductor Manufacturer / Cloud Infrastructure / E-commerce / Bank …）/ ② **Business Model**（SaaS Subscription / Licensing / Advertising / Transaction Fee / Hardware Sales / Cloud Usage …，`BUSINESS_MODEL` 枚举 + `MODEL_KEYWORDS` 顺序去重）/ ③ **Revenue Composition**（分部占比 + 数据日期；当前恒 `available=False`，诚实缺省）/ ④ **Economic Profile**（毛利率 / 经营利润率 / CapEx÷营收 / FCF Margin / Recurring / Debt，输出 shape flags + concentration）/ ⑤ **External Classification**（Yahoo Industry / GICS / NAICS / ML 标签，**原样保留不覆盖内部判断**）
- ✅ **黄金法则**：`economic_identity_ceiling(identity_key, economics_key)` 重写——跨族经济学节点**一律返回 identity**（不提升）；同族时经 `common_ancestor()` 收敛；绝不让 economics 节点成为 Identity
- ✅ **冲突分级 `ConflictKind`**：CONSISTENT / REFINEMENT / IDENTITY_WINS / ECONOMICS_ONLY / INSUFFICIENT（`reconcile_identity(external, economics_key)` 判定 + `taxonomy_audit` 留痕）
- ✅ **Yahoo 映射两段式 longest-key-wins**：`node_from_yahoo()` 先 industry 匹配 → sector 匹配 → sector→family 兜底表；修复「长 sector 短语压过具体 industry」缺陷（真实误判 AMZN `Consumer Cyclical`(17 字符) 压过 `Internet Retail`(15) → `cons.ecommerce`；KR `Consumer Defensive` 压过 `Grocery Stores` → `cs.retail`）
- ✅ **数据层承载**：`data/models.py` 新增 `MarketData.description` + `CompanyProfile` 8 个 taxonomy shadow 字段；`data/providers.py` 采集 Yahoo `longBusinessSummary` → description，`SYNTHETIC_DATA` 补齐 sector/industry 标签
- ✅ **additive shadow 接线**：`classifier.py`（末尾）/ `ml_classifier.py`（ML 成功路径 + rule_fallback 路径）均调用 `attach_taxonomy_profile()`；**不改 `business_type` / `applicable_models` / 模型路由** → golden 指纹零漂移
- ✅ **测试**：新建 `tests/test_taxonomy.py`（**48 用例**）——树完整性（parent 链 / depth / 族根无父）、Yahoo 映射（longest-key-wins / industry 优先 / order-independent）、黄金法则（跨族 + 同族兄弟收敛）、冲突分级（5 状态 + 描述细化）、业务模型（顺序 / 去重 / 商品词）、收入与经济（concentration / flags / CAGR）、五维契约（原样保留外部标签 / additive / description 信号 / ML 标签映射）
- ✅ **修复 6 处真实缺陷**：`("commodot", …)` typo 死词条 → `commodit` 词干 / `cs` 族根去父边 / depth 改 parent 链 / `economic_identity_ceiling()` 重写（阻止同族「提升」）/ `node_from_yahoo()` 两段式 / 补 `ind.logistics`（integrated freight / freight & logistics / logistics / air freight）

Modified

- `classification/classifier.py` / `classification/ml_classifier.py` / `data/models.py` / `data/providers.py`
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md`（ADR-039）/ `TODO.md`（M-30~M-33）

Created

- `classification/taxonomy.py`（99 节点树 + 五维模型 + 黄金法则）
- `tests/test_taxonomy.py`（48 用例）

Notes

- 验证：`python -c "import ..."` → taxonomy OK（`nodes: 99`）；pytest **288/288 全通过**（240 → 288，新增 48 用例）；golden 指纹**零漂移**（taxonomy 为 shadow 层，不进指纹字段）
- Ruff：新增文件 `classification/taxonomy.py` + `tests/test_taxonomy.py` **All checks passed**；既有文件 `data/providers.py`/`classification/ml_classifier.py` 仍存 19 处**历史遗留**样式告警（E701/E702 单行多语句 / F841 未用局部变量 / F541 空占位符 f-string / E741 歧义变量名 `l`），**非本次引入**，按「scoped ruff」惯例不在本次范围（如需清理可另开任务）
- 端到端抽查：NBIS（Yahoo `Software - Infrastructure`）+ ML `Semiconductor`(57%) → 经黄金法则收敛 `tech` / archetype `MatureTech`（**非** Semiconductor）✓；MSFT（synthetic industry `Software` → `tech.generic`）+ description「enterprise software and related cloud services」→ `tech.software.application` ✓
- 未解决（诚实缺省，非缺陷）：③ Revenue Composition 恒 unavailable（无分部数据源，待 M-31）；taxonomy 暂为 shadow 不参与路由（待 M-32）；GICS/NAICS 缺失（待 M-33）

## 2026-11-13 (Session #22 / Phase 4 — 全量回归 + 边界/验收用例断言化 + golden 指纹扩展)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户《估值完整性重构》任务书的 **Phase 4（测试与验收）** 为输入，收尾整个重构。核心原则：**报告不得在核心模型被移出后仍显示高一致性；样本口径必须区分「原始解算 / IQR 排除 / 参与聚合」；风险等级不得被加成总分掩盖；每个验收标准都要有可执行的断言，而非文字声明**。

Completed

- ✅ **回归 universe 扩展**：`tests/golden_report.py::BASKET` 由 9 只 → **18 只**（+GOOGL/AMZN/AVGO/ORCL/CRWV/UPS/KR/BAC/NU）；实测 18 只 `check_invariants()` 缺陷全为空；分类路由正确（GOOGL→MatureTech、AMZN→ConsumerCyclical、AVGO→Semiconductor、ORCL→MatureTech、CRWV→MatureTech(AI/Cloud)、UPS→Industrial、KR→ConsumerStaples、BAC→Bank(ke)、NU→FinTech(ke)）
- ✅ **golden 指纹扩展（验收 6）**：`build_fingerprint()` 新增 5 字段（`n_independent_evidence`/`raw_solved_count`/`outlier_count`/`effective_aggregation_count`/`core_model_excluded`）；样本口径恒等式 `effective + outlier == raw` 由 `math_audit` 断言
- ✅ **invariant 加固（验收 1/2）**：`check_invariants()` #2 覆盖率封顶门控由 `n_solved` → `n_independent_evidence`；新增 invariant 2b——核心模型（DCF）被 IQR 排除却仍输出 Very Strong/Strong/Moderate → 判为缺陷
- ✅ **边界/验收用例断言化**：新建 `tests/test_phase4_integrity.py`（9 用例）：风险等级底线（标准 3，全 universe）、High 旗标强制整体 ≥High、Floor 实际触发、IQR 排除核心模型→`Unresolved Disagreement (Review Required)`（标准 1/2）、一致性封顶按独立证据数计票、极端 TV/EV 支配下调 DCF 权重、未知身份不冒充精确行业匹配（标准 8/9）、全 universe invariant + 样本口径（标准 6/7/10）、负 FCF 建构标的保留旗标

Modified

- `tests/golden_report.py` / `tests/golden/report_fingerprints.json`（重生成）/ `tests/test_providers_provenance.py`（BAC→ZZZZ）/ `analysis/risk.py`（Ruff 清理）
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md` / `TODO.md` / `ROADMAP.md`

Created

- `tests/test_phase4_integrity.py`（9 用例）

Notes

- 验证：pytest **240/240 全通过**（231 → 240）；golden 基线重生成（原 9 只既有字段无漂移，`UPDATE_GOLDEN=1 pytest tests/test_golden_report.py` → 2 passed / 1 skipped）；改动文件 Ruff **All checks passed**（顺带清理 3 处遗留）；pyright 未安装（不可用）

## 2026-11-13 (Session #21 / Phase 3 — WACC β 多窗口敏感性 + peer 倍数来源溯源 + 同源证据去重)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户《估值完整性重构》任务书的 **Phase 3（P1）** 为输入。核心原则：**单一回归 β 会掩盖估计不稳——须暴露多窗口 β 及其离散度；peer 倍数须标注来源档位（精确行业/行业回退/业务类型回退/近似）与样本数，缺失不得静默；同一证据族的多个模型（P/E↔Historical Multiples、EV/Sales↔EV/Sales (Unit Econ)、DCF↔ReverseDCF）不得作为「多条独立证据」抬高一致性门控**（ADR-036 / ADR-037）。

Completed

- ✅ **3.1 β 多窗口敏感性 + bottom-up 槽位**：`MarketData` 新增 `beta_windows`（窗口标签→回归 β）/`industry_beta`（bottom-up/peer unlevered β，缺失即 `None`，不伪造）；provider 新增 `BETA_WINDOWS=(2y_weekly / 3y_monthly / 5y_monthly)` + `_estimate_beta_windows()`（逐窗口独立回归，失败窗口显式 `None`）；`_estimate_beta()` 泛化为 `(range_, interval, min_obs)`，周线 ISO-week keying；`WaccBreakdown` 新增 `beta_windows`/`beta_dispersion` + `beta_window_note()`（<2 窗口返回 `None`；极差 >0.50 标注「窗口间波动较大」）；dashboard 在 WACC 区块渲染
- ✅ **3.2 peer 倍数来源溯源**：`PEER_SOURCE_EXACT_INDUSTRY` / `SECTOR_FALLBACK` / `BUSINESS_TYPE_FALLBACK` / `APPROXIMATE` + `PEER_SOURCE_LABELS` 封闭集；`_sector_peer_multiple` / `_resolve_peer_bucket` 返回 4 元组 `(value, source_text, source_kind, n_peers)`；`calculate()` breakdown 落 `peer_source_kind`/`peer_sample_size`；dashboard 新增「🔎 同行倍数来源 (可审计)」区块
- ✅ **3.3 同源证据去重**：`_MODEL_FAMILY` 映射 + `_independent_evidence()` 归并同族；一致性覆盖率门控由 `n_solved` 改为 `n_independent`；`ModelAgreement` 新增 `n_independent_evidence` / `duplicate_evidence_groups` + 去重 note

Modified

- `data/models.py` / `data/providers.py` / `valuation/wacc.py` / `models/multiples.py` / `analysis/model_agreement.py` / `reporting/dashboard.py`
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md` / `TODO.md` / `ROADMAP.md`

Created

- `tests/test_phase3_integrity.py`（14 用例：β 多窗口 ×7 / peer 溯源 ×3 / 同源去重 ×4）

Notes

- 验证：pytest **231/231 全通过**（217 → 231，新增 14 用例）；新版文件 ruff clean（仓库无 ruff 配置，scoped 运行）；pyright 未安装（不可用）
- 端到端抽查确认 `peer_source_kind` 全链路透传：AAPL `EXACT_INDUSTRY`(n=None)、NBIS `APPROXIMATE`(n=5)、JPM `EXACT_INDUSTRY`(n=None)
- golden 无漂移（β 窗口不在指纹字段内；dashboard 新增区块仅在渲染层，`golden_report` 指纹不受影响）
- 未解决：bottom-up β 依赖同业 unlevered β 数据源，当前 provider 无该数据 → `industry_beta` 恒为 `None`（字段与渲染已就绪，待数据源接入，属后续可选题）；β 多窗口为独立审计输入，**不覆盖** CAPM 使用的标量 `beta`

## 2026-11-13 (Session #20 / Phase 2 — Monte Carlo 双模式 + 路径锚点对账 + 经营/折现情景拆分 + 报告透明化)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户《估值完整性重构》任务书的 **Phase 2**（forecasts / monte_carlo / dashboard）为输入。核心原则：**MC 不是独立估值证据，而是「确定性 DCF 假设的扰动分布」——零扰动时必须精确复现确定性 DCF 的 base 点值；人为利润率地板必须移除；经营驱动情景与折现率情景必须拆分展示；报告须区分请求数/有效数/无效数/截断数**（ADR-034 / ADR-035）。

Completed

- ✅ **MC 双模式**：`MODE_BASE_CASE`（以确定性 DCF 同一 base 预测为中心，仅扰动假设）/ `MODE_HISTORICAL`（历史分布，独立模式）；`run(data, profile, mode=None, dcf_value=None)`——无 `dcf_value`（金融股 RIM/DDM 或 DCF 未求解）时**自动回退 historical 并附说明**
- ✅ **去除人为利润率地板**：取消 MC 内 `max(om, +2%)` 硬地板，允许负利润率；`MonteCarloConfig` 驱动边界全部可配置
- ✅ **路径形参化锚点对账（核心）**：新增 `_base_case_path()`（提取 DCF base 逐年 `shape_rev` / `margin_offsets`）+ `_project_one_path()`（在 `(eff_cagr, eff_om)` 精确复现 DCF base FCF 路径）→ 零扰动锚点 = 确定性 DCF（MSFT/AAPL 差 +0.0%）；锚点沿用 DCF「负股权 → 归零」约定（NBIS $0.00 vs $0.00）
- ✅ **经营 / 折现情景拆分**：`ScenarioAnalyzer.run_operating()`（营收增长 × 利润率 → FCF → EV，`scenario_kind="operating"`）；原情景标 `discount_rate`；报告拆两区块；金融股经营情景返回 `{}`
- ✅ **报告透明化**：MC 区块新增模式 / 随机种子 / 请求数 / 有效数 / 无效数 / 截断数 / 参数分布 / 相关矩阵；对账行**仅 base_case 模式**渲染；标注「DCF 假设扰动分布，非独立估值证据」
- ✅ **用词修正**：`P(股权价值归零/破产)` → 「Equity Value Wipeout Probability」

Modified

- `simulation/monte_carlo.py` / `config.py` / `analysis/scenario.py` / `reporting/dashboard.py` / `telegram_bot/telegram_bot.py`
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md` / `TODO.md` / `ROADMAP.md`

Created

- `tests/test_monte_carlo_modes.py`（14 用例：锚点对账 / 负利润率 / 可配置边界 / historical 回退 / 元数据可复现 / 情景拆分 / Wipeout 用词）

Notes

- 验证：pytest **217/217 全通过**（163 → 217，新增 14 用例 + 既有全绿）；`compile_exit=0`
- golden 无漂移（`golden_report.render_report` 走 `monte_carlo=None`，Phase 2 变更不影响指纹）
- 端到端 MSFT/JPM/NBIS 报告渲染确认：经营情景区块正常；折现情景标注「仅变动折现率」；对账行仅 base_case 出现；JPM 金融股落 historical 模式且经营情景区正确缺省
- 未解决：Phase 2 范围内的 MC 分布参数仍以历史统计为默认中心（base_case 仅平移中心到 DCF base，未做参数自相关建模）——属 Phase 3/后续可选题

## 2026-11-13 (Session #19 — Rf 单一真源 + Terminal Growth 三档「经济学含义」重定义 + Quality-Weighted Median 边界修复)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户对 `valuation/wacc.py` / `valuation/terminal_growth.py` / `models/dcf.py` / `analysis/model_agreement.py` 的**静态代码审查（2×P0 + 1×P1，用户声明为「实际代码问题」而非推测）**为输入。核心原则：**CAPM 与 Cost of Debt 必须共用同一个已解析 Rf（单一真源）；GDP 上限只约束「长期稳定终值增长率」= Base，乐观 High 是情景区间——不机械禁止其超 GDP，但绝不允许被误称为长期稳定终值增长率；加权中位数在等权时必须精确退化为普通中位数**（ADR-032 / ADR-033）。

Completed

- ✅ **P0-1 Rf 单一真源**：`_implied_cost_of_debt()` 新增 `risk_free_rate: Optional[float]` 形参；`calculate()` 改为 `self._implied_cost_of_debt(data, risk_free_rate=rf)`，所有债务成本 fallback（合成评级 spread / BBB-like）与 CAPM（`ke = rf + β·ERP`）共用同一 Rf；独立调用（单测）回落原优先级链
- ✅ **P0-2 三档语义重定义**：明确「Base = 长期稳定终值增长率（受 LT nominal GDP 4.5% + Gordon WACC−0.5% 双重约束）；Low = 保守情景；High = 乐观情景（仅 Gordon 封顶）」；新增引擎语义契约字段 `high_exceeds_gdp` / `gdp_ceiling` / `band_labels`；`high > gdp_ceiling` 时追加 note
- ✅ **P0-2 渲染契约化**：`derivation_trace()` / `models/dcf.py` 假设说明 / `reporting/dashboard.py` 三档区块文案统一改写；超 GDP 时渲染「⚠ High X% 高于长期名义 GDP Y%：仅作乐观情景参考，非长期稳定终值增长率」
- ✅ **P1-3 Weighted Median 边界修复**：`_weighted_median()` 改用标准 **midpoint 定义**（下/上加权中位数取平均）→ 等权时精确退化为普通中位数（修复 AAPL 176.12 vs 165.24 症状）；零/负权重剔除；空输入返回 None

Modified

- `valuation/wacc.py` / `valuation/terminal_growth.py` / `models/dcf.py` / `reporting/dashboard.py`
- `analysis/model_agreement.py`
- `tests/test_wacc_kd.py` / `tests/test_terminal_growth.py` / `tests/golden/report_fingerprints.json`（有意漂移）
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md` / `TODO.md`

Created

- `tests/test_model_agreement.py`（16 用例，覆盖加权中位数全部边界）
- （无新模块；`BAND_LABELS` 契约常量与 `TerminalGrowthRange` 新增字段为增量）

Notes

- 验证：pytest **163/163 全通过**（147 → 163：P0 修复 +5 用例，P1 修复 +16 用例）；golden 因加权中位数缺陷修复出现**已审阅的有意漂移**（4 只标的 `median_value_weighted` 归位到普通中位数，已 `UPDATE_GOLDEN=1` 重生成）
- 端到端抽查：AAPL synthetic（base 1.5% / high 2.0% / `high_exceeds_gdp=False`）正常渲染；NVDA/MSFT/NOW/NBIS（base 4.5% / high 5.0% / `high_exceeds_gdp=True`）报告出现「⚠ High 5.00% 高于长期名义 GDP 4.50%」

## 2026-11-12 (Session #18 — 反解求解器 P0/P1 加固: bracket 重校验 + 单调性采样 + 多根/常数检测 + 负终值贯穿)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户对 `models/reverse_dcf.py` / `forecasts/fcf_projection.py` 的**静态代码审查（6 项：3×P0 + 3×P1）**为输入。核心原则：**求解器绝不在无有效 bracket 时返回可疑根；单调性必须实测而非假设；终值被抑制的结果不得伪装成完整 SOLVED**（ADR-031）。

Completed

- ✅ **P0-1 有效 bracket 校验**：新增 `_finish_root()`——`brentq` 失败后若 `f(a)·f(b) > 0` → `NO_SOLUTION_IN_RANGE`（拒可疑根）；求解后一律计算 residual 并按 `implied_residual_tol` 判定
- ✅ **P0-2 单调性验证**：`_solve_implied_scalar()` 以 `implied_monotonic_samples=21` 采样验证；非单调 → `_root_brackets()` 扫描（0 无解 / 1 求解 / >1 → `MULTIPLE_ROOTS`）
- ✅ **P0-3 负终值贯穿**：`terminal_fcf_negative` 纳入 breakdown + implied_expectations；`_finalize_revenue_cagr()` 在终期 FCF ≤ 0 时 SOLVED → APPROXIMATE + turnaround note；`analysis/expectation.py` / `dashboard._implied_section()` 透出
- ✅ **P1-5A 端点根**：Revenue CAGR 端点等于目标（含容差）→ 判定边界解 SOLVED
- ✅ **P1-5B 常数目标**：`fmax−fmin ≤ abs_tol` → `FLAT_OBJECTIVE` / `NO_SOLUTION_IN_RANGE`
- ✅ **P1-6 测试 18 用例**：端点根 ×2 / 无效 bracket / 无 bracket / 非单调无根 / 多根 / 常数目标 ×2 / 负终值降级与传播 ×4（含负 FCF 标的回填）/ FCF-Margin·WACC·TG round-trip / 多股票状态隔离 ×2
- ✅ **自查修复 2 处真实缺陷**：单调性容差误用（改用步长尺度 `mono_tol`）；递减方向可达区间赋值反转

Modified

- `config.py` / `models/reverse_dcf.py` / `analysis/expectation.py` / `reporting/dashboard.py`
- `tests/test_reverse_dcf.py`
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md` / `TODO.md`

Created

- （无新模块；`_root_brackets()` / `_finish_root()` / `_finalize_revenue_cagr()` 为新增方法）

Notes

- 验证：pytest **142/142 全通过**（124 → 142，新增 18 用例）；golden 无漂移
- 用户静态审查明确声明「未在运行环境执行 pytest」，本次已在本机全量运行并确认全通过

## 2026-11-12 (Session #17 — Reverse DCF 约束式隐含求解器: Implied OM / FCF Margin / WACC / TG)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户 **Phase 2 清单「升级求解器」**为输入（Implied Revenue CAGR / Operating Margin / FCF Margin / WACC / Terminal Growth / Constraint-based Solver）。承接 Session #16「问题 2（仅反推 Revenue CAGR）/ 问题 4（FCF Margin 非独立变量）」。核心原则：**反解只做单变量（其余固定基准），越界要「指名边界」不「钳制到边缘」**（ADR-030）。

Completed

- ✅ **约束式单变量求解器 `_solve_implied_scalar()`**（`models/reverse_dcf.py`）：硬边界（越界 → `NO_SOLUTION_IN_RANGE` + note 指名绑定边界，不钳制）+ 单调性（`increasing` 决定可达端）+ 残差检查（`rel>1e-3` → APPROXIMATE）
- ✅ **四隐含驱动 one-at-a-time**：`implied_operating_margin` / `implied_fcf_margin` / `implied_wacc`（下界 = `max(lo, tg+spread)`）/ `implied_terminal_growth`（上界 = `min(hi, wacc−spread)`）
- ✅ **FCF margin 独立化**：新增 flat-margin 桥 `project_enterprise_value_flat_margin()`（`FCF_t=revenue_t×fcf_margin`）
- ✅ **落字段 + 透传 + 渲染**：`ImpliedSolve` → `breakdown["implied_expectations"]` → `ImpliedExpectations`（8 新字段）→ `_implied_section()`（含「不可解（超出约束区间）」/「_(近似)_」）
- ✅ **测试 8 用例**：`TestConstraintSolver`（5）+ `TestImpliedExpectationsPhase2`（3）

Modified

- `config.py` / `forecasts/fcf_projection.py` / `models/reverse_dcf.py` / `analysis/expectation.py` / `reporting/dashboard.py`
- `tests/test_reverse_dcf.py`
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md` / `TODO.md`

Created

- （无新模块；`ImpliedSolve` dataclass / `_solve_implied_scalar()` / `_implied_expectations()` / `project_enterprise_value_flat_margin()` 为新增）

Notes

- 验证：pytest **124/124 全通过**（116 → 124，新增 8 用例）；golden 无漂移（隐含驱动未纳入指纹）；AAPL 四驱动全解（OM 28.9% / FCF margin 27.1% / WACC 11.3% / TG 2.5%）；NBIS 四驱动全 `NO_SOLUTION_IN_RANGE`（绑定边界点名，无钳制）

## 2026-11-12 (Session #16 — 估值引擎诚实性与一致性: 负终期 FCF 抑制 + 预测年限单一真源 + 求解器残差检查)

AI Agent

```
DeepSeek-based Agent (TRAE)
```

方法：以用户对 `forecasts/fcf_projection.py` + `models/reverse_dcf.py` 的**代码审查**为输入（4 项发现，Phase 1「修复现有引擎」）。核心原则：**引擎不得为了让估值好看而伪造输入；口径与年限必须同源，禁止静默状态污染**。每步 `python -m pytest -q` 全量回归。

Completed

- ✅ **问题 1（高优先级 · 数学）负终期 FCF 伪造成正终值**：`if last_fcf <= 0: last_fcf = avg_abs` 把烧钱公司的负终期 FCF 偷改成正数再进 Gordon → 人为制造正终值（Normal DCF / Reverse DCF / Monte Carlo 三处各复制一份）。修复：统一出口 `gordon_terminal_value()`——终期 FCF ≤ 0（含 None）时**抑制终值不翻转符号**，估值退化为显式期现值下限，`terminal_fcf_negative=True` + `SolverStatus.APPROXIMATE` + note「需转型假设」
- ✅ **问题 3（代码风险）预测年限跨标的污染**：`reverse_dcf.py` 的 `self.horizon = int(horizon)` 写回 `NAME_TO_MODEL` 共享单例 → SaaS(7)→Utilities(10)→Unknown 沿用 10。修复：新增单一真源 `config.resolve_forecast_horizon(business_type)`，删除 `self.horizon`，全链路（DCF/ReverseDCF/Scenario/Sensitivity/MonteCarlo/Expectation）统一
- ✅ **附带修复**：WACC−g 下限统一为 `MIN_WACC_TG_SPREAD=0.005`；反向 DCF 新增求解器 residual 检查（`rel_resid>1e-3` → APPROXIMATE）；`analysis/risk.py` 补 `terminal_fcf_negative` → HIGH 旗标分支
- ✅ **问题 2 / 问题 4**（Reverse DCF 仅反推 Revenue CAGR / FCF Margin 非独立变量）：确认为 Phase 2 升级项 → 记入 TODO L-08（含报告显式展示固定假设）

Modified

- `config.py` / `forecasts/fcf_projection.py` / `models/dcf.py` / `models/reverse_dcf.py` / `simulation/monte_carlo.py` / `analysis/scenario.py` / `analysis/sensitivity.py` / `analysis/expectation.py` / `analysis/risk.py`
- `tests/test_dcf.py` / `tests/test_reverse_dcf.py` / `tests/golden/report_fingerprints.json`
- `AGENT.md` / `CHANGELOG.md` / `DECISIONS.md` / `TODO.md`

Created

- （无新模块；`gordon_terminal_value()` / `TerminalValueResult` / `resolve_forecast_horizon()` 为新增函数/类型）

Notes

- 验证：pytest **116/116 全通过**（106 → 116，新增 10 用例：`TestTerminalValueHonesty` 6 + `TestHorizonIsolation` 4）；golden 基线有意漂移 1 字段（`NBIS.median_value: 12.76 → 10.46`，旧值即伪正终值虚高，已审阅）

## 2026-11-12 (Session #15 — UPST 递归自我改进 3 轮: 分类子串误匹配 → 金融 EV/Sales 剔除 + 渲染层口径泄漏)

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
  - `data/reconciliation.py` 滚动 P/E 检查改为方向感知文案：供应商 P/E 低于价格/GAAP-EPS 隐含值 → 判为 non-GAAP/正常化口径差；高于 → 旧口径/摊薄股数或盈利下滑
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
  - 修复前输出：`中位估值对比：**高估**（中位估值较中位估值高 +41.6%）`
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
     • is_fin 分支：EV / Net Debt / EV/EBITDA / FCF TTM 总览四行全部加斜体 caveat 注释（_*Financial institution metric not directly comparable*_）
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

```
CP-0039 - Cross-industry threshold calibration (M-67) + SBC normalization sunk into the FCF main chain (M-69) (Session #40) — analysis/threshold_calibration.py NEW (single RUNTIME source of truth): ThresholdCalibration frozen dataclass (archetype/tier/fcf_aligned_pp/fcf_flag_pp/fcf_high_ratio/beta_min_peers/rationale/judged_dispersion/evidence_n + note()); tier_for_dispersion() monotone (<0.03 stable / 0.03-0.06 moderate / >=0.06 volatile); _TIER_BANDS widen with volatility (2pp/4pp/1.75x -> 3pp/5pp/2x -> 4pp/7pp/2.5x); beta_min_peers_for() by PEER-POOL BREADTH not volatility (BROAD=5 / NARROW=3 / UNKNOWN=4, narrow={NEOBANK,FINTECH,CONGLOMERATE}); two-source calibration (CALIBRATION_EVIDENCE frozen offline-basket sigma/n, corroborating only + domain prior) ; DEFAULT_CALIBRATION = moderate global band (backwards compatible); unknown archetype falls back to default band, NEVER silently re-graded; analysis/divergence.py _fcf_margin_check() consumes calibration_for(business_type) via _calibration_for_profile() + appends audit line 〔行业校准[tier]（观测 σ, n）：...〕 (same +4.5pp gap = FLAG for a stable utility, MODERATE for a volatile semiconductor); valuation/wacc.py _bottom_up_reliability_label() takes business_type + beta_min_peers_for() via LAZY import (module-level import created models.dcf -> valuation.wacc -> analysis -> analysis.expectation -> models.reverse_dcf -> models.dcf circular); data/fcf_utils.py TWO-function exit: resolve_ttm_fcf() raw primitive (existence check only, NO SBC) + resolve_ttm_fcf_normalized() value producer (applies normalize_fcf_for_sbc() EXACTLY ONCE, +sbc_normalized suffix when it moved the value, raw None -> (None,"missing") never a fabricated zero); models/reverse_dcf.py + models/multiples.py FCF Yield consume the shared exit (Phase D missing-FCF guard retained); ID honesty: M-68 already taken by Monte Carlo truncation -> SBC sink renamed M-69; tests/test_reporting_integrity_repair.py +TestCrossIndustryThresholdCalibration(9) +TestSbcMainChainExit(6); pytest 507 -> 522 passed, golden ZERO drift (NOT regenerated), ruff clean
```

```
CP-0038 - User code review 4×P1 fixes (Session #35) — models/sotp.py FULL REWRITE: three-state machine SOTP_SOLVED/SOTP_APPROXIMATE/SOTP_INSUFFICIENT + SOTPSegment dataclass (is_independent_evidence()/as_dict()); _derive_segments_from_profile no longer manufactures "pseudo-independent" Operating EV from the company's OWN ev/revenue (max(0.5,min(10.0,ev/revenue)) × revenue ≈ market EV, then split by ML business_exposures = market valuation redistributed by probability, CIRCULAR); only real segment revenue/profit + independent peer multiple -> SOLVED (counts in consensus); partial real + estimated -> APPROXIMATE; ML exposures only, no independent segment financials -> INSUFFICIENT + breakdown["display_only"]=True (aggregation layer excludes, never masquerades as evidence) + breakdown["segments_detail"] per-segment Revenue/EBITDA/EBIT/Applied Multiple/Segment EV/Source/Confidence/As-of Date + fixes operating_ev double net-debt deduction (equity_value = total_ev - debt + cash exactly once); valuation/wacc.py multi-window beta stability now PARTICIPATES in estimation: Blume-style shrinkage toward beta=1.0 BETA_MAX_SHRINK=0.35 BETA_DISPERSION_SHRINK_THRESHOLD=0.50 (NOT window averaging), WaccBreakdown +beta_raw/beta_selected/beta_adjusted/beta_shrinkage/beta_dispersion/beta_uncertainty + beta uncertainty PROPagated to wacc_beta_lo/wacc_beta_hi interval; reporting/dashboard.py _market_section() ETR primary value = WACC actually-used ETR (wacc_bd.effective_tax_rate) + _etr_basis_suffix() tax_period_basis, provider ETR relabelled "Provider ETR"; models/base.py NEW make_comparability(value_basis,currency,financial_period,valuation_date,peer_valid) ISO-normalised + ValuationResult.comparability; dcf/multiples/sotp wire declarations; analysis/model_agreement.py NEW _comparability_gate() 7-dim conflict detection (currency/value-basis/financial-period/valuation-date>COMPARABILITY_DATE_TOL_DAYS=45/peer_valid=False/data-quality<COMPARABILITY_QUALITY_FLOOR=50) + ModelAgreement +comparability_reference/comparability_conflicts/comparability_excluded_models; analyze() removes conflicting models from solved_agg and recomputes n_applicable — EMPTY comparability = undeclared ≠ conflict, NOT excluded; tests/test_special_models.py SOTP three-state contract + tests/test_model_agreement.py TestComparabilityGate (8); pytest 429 -> 436 passed, golden INTENTIONALLY regenerated ONCE (PLD/NOW/NBIS/CRWV/NU: n_solved -1 / n_display_only +1 / n_independent_evidence -1, verified expected), ruff clean
```

```
CP-0037 - SEC filing-instance XBRL productionized into providers main chain (M-39) + Taxonomy participates in routing via cross-family gate (M-32) (Session #30) — data/segment_revenue.py resolve_segments(ticker, *, client, offline, fmp_cache_path, filing_cache_path, identity_resolver): Layer 1 FMP revenue-product-segmentation (needs key) -> Layer 2 SEC 10-K/20-F filing-instance XBRL (key-free, Lazy import of FilingBusinessExtractor to avoid circular dep), both empty -> [] never fabricated; data/providers.py now calls resolve_segments() so FMP missing/expired/rate-limited/uncovered key auto-degrades to SEC first-party segments (still shadow fill, no routing change); classification/taxonomy.py +TAXONOMY_ROUTING_STATUSES={CONFIRMED} + ARCHETYPE_FAMILIES (derived from IDENTITY_NODES tree via _archetype_family_index, archetype<->node tree never drifts) + same_identity_family() + taxonomy_routing_override(internal_bt, taxonomy_key, decision_status, *, guard_blocked=False) three gating gates (CONFIRMED; cross identity-family conflict; economic guard not blocked) + attach_taxonomy_profile(..., tp=...) reuse; classification/classifier.py (rule path: builds _taxonomy before _model_applicability, +_asset_light_guard_blocked staticmethod) and ml_classifier.py (ML path: economics = raw ML top-1) symmetric gates, business_type=_routed_business_type.value; KEY FIX: gate compares internal identity verdict best_bt NOT routing_bt (latter is Phase 1.3 conservative valuation routing, GOOGL -> TELECOM would cross-family misfire); tests/test_taxonomy.py +TestTaxonomyRoutingGate (12 cases) + tension basket ORCL/NBIS/CRWV (taxonomy_identity_key="tech.software.infra" but business_type="MatureTech"); pytest 413 -> 429 passed, golden ZERO drift (NOT regenerated), ruff clean
```

```
CP-0036 - SEC 10-K / 20-F filing-instance XBRL business evidence (M-38) + four-state decision end-to-end tests (Session #29) — data/filing_evidence.py NEW (FilingRef cik/form/accession/index_url + FilingBusinessExtractor: CIK -> data.sec.gov/submissions/CIK{cik}.json filings.recent newest-first -> first 10-K/20-F -> filing index.json prefers *_htm.xml instance; parse_segment_revenue(xml) PURE: xbrli:context -> (endDate, axis, member), ONLY facts carrying a segment axis, single-axis _AXIS_PRIORITY StatementBusinessSegmentsAxis > ProductOrServiceAxis > ifrs SegmentsAxis > StatementGeographicalAxis, consolidated total EXCLUDED, latest period wins, instant context ignored; returns segment_revenue.Segment + source="sec-xbrl" drop-in for to_revenue_composition; _MEM + disk cache + offline zero-network; no CIK/no instance/parse-fail/malformed -> [] never fabricated; compliant User-Agent); tests/test_filing_evidence.py NEW (9 cases) + tests/test_taxonomy.py TestDecisionContractEndToEnd (6 cases, real builder/classifier full chain); pytest 398 -> 413, ruff clean on changed modules, golden ZERO drift
```

```
CP-0035 - Business Intelligence Layer: Six-Module Mapping + Four-State Decision Contract + Identity Resolution (Session #28) — classification/taxonomy.py (DecisionStatus enum CONFIRMED/PROBABLE/AMBIGUOUS/INSUFFICIENT_DATA + _ECONOMICS_ONLY_MIN_CONF=0.55 + _DECISION_LABELS + decide_status() deterministic mapping + BusinessTaxonomyProfile.decision_status + audit line + attach_taxonomy_profile writes taxonomy_decision_status); data/identity_resolver.py NEW (IdentityResolver/ResolvedIdentity: CIK/SIC/FIGI; Layer A reuses in-place SEC chain via SectorIndustryResolver.resolve_identity(), Layer B OpenFIGI only with OPENFIGI_API_KEY, offline skips; missing -> None never fabricated); classification/business_intelligence.py NEW (extract_business_evidence -> BusinessEvidence: description + revenue_segments + provenance, absent evidence explicit); data/models.py CompanyProfile +taxonomy_decision_status; tests/test_taxonomy.py TestDecisionContract (7) + tests/test_identity_resolver.py (5) + tests/test_business_intelligence.py (4); pytest 382 -> 398, golden ZERO drift
```

```
CP-0034 - Three-Source sector/industry Completion + bottom-up β (Session #24 / H-03) — data/sic_map.py (SIC->Yahoo bridge, exact/2-digit/keyword resolution, "every mapping must be classifiable" contract); data/industry_resolver.py (SectorIndustryResolver: FinanceDatabase -> SEC EDGAR SIC -> Wikidata SPARQL P452, class _MEM + disk cache, compliant SEC User-Agent, batch_get); data/industry_beta.py (derive_industry_unlevered_beta Hamada beta_u = beta_L/(1+(1-t)*D/E), t=0.21, median, <3 peers -> None, BOTTOM_UP_BETA=0 kill switch); data/providers.py bottom-up beta wiring into MarketData.industry_beta; classification/classifier.py +("asset management", BANK); tests/test_sic_map.py + test_industry_resolver.py + test_industry_beta.py (45 cases); pytest 333/333, golden ZERO drift
```

Checkpoint ID

```
CP-0033 - Internal Taxonomy + Five-Dimension Decomposition (Session #23) — classification/taxonomy.py (99-node canonical tree, parent-chain depth, BUSINESS_MODEL enum, Yahoo industry/sector maps, ExternalClassification, ConflictKind, economic_identity_ceiling GOLDEN RULE, node_from_yahoo two-stage longest-key-wins, attach_taxonomy_profile additive shadow wiring); data/models.py +MarketData.description +8 CompanyProfile shadow fields; data/providers.py longBusinessSummary collection + synthetic sector/industry labels; classifier.py + ml_classifier.py attach hook; tests/test_taxonomy.py (48 cases); pytest 288/288, golden ZERO drift
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
Pipeline Step 32 / 33: Coverage Model Family Frozen + Report-Self-Consistency Hardening + Internal Taxonomy (shadow → **participates in routing via cross-family gate + economic guard, M-32 DONE**) + **Feature Completion: sector/industry via three-source chain (FinanceDatabase/SEC-EDGAR-SIC/Wikidata) DONE; bottom-up β awakened** + **Bottom-up β upgraded (business-identity 3-level screening + full β chain: Levered→Unlevered→Median→Cash-adjusted→Target-Relevered) & wired into CAPM (M-34) DONE** + **Business Intelligence Layer (six modules + four-state DecisionStatus + Identity Resolution, M-37 DONE)** + **SEC filing-instance XBRL evidence (M-38) productionized into providers main chain (M-39 DONE)** → Remaining Feature Imputation (interest_to_revenue) → Label Correction → Optuna → v2.2 Retrain → sanity≥90% → AB Test → Deploy
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

---

## Session #53 Checklist — §10 变异收口 / 快照契约 / 可选 ML 依赖

- [x] Mutation 16/16 全部被捕获（`scripts/run_mutation_experiments.py`，JSON 存 `/tmp/mut_final.json`）
- [x] M05 改为断言绝对 beta 恢复到已知 β=1.3（原测试 partial-vs-full 双污染失明）
- [x] `forecast_nwc_change` 独立单元测试（`tests/test_nwc_marginal_change.py`，5 项）
- [x] `_scan_roots` 多根测试读取生产 meta（`tests/test_multi_root_scan.py`，7 项；4 根 + 3 根场景）
- [x] 修正 M10 假存活：断言生产 `meta["multiple_roots"]`，不再自行重算
- [x] 缓存从时钟驱动改为 Snapshot ID 驱动（`data/providers.py: resolve_snapshot_id`）
- [x] 新增 `tests/test_snapshot_contract.py`（11 项：存在/缺失/过期/损坏/freeze 关闭/时钟变化）
- [x] `test_status_matrix.py` / `test_determinism_contract.py` 显式绑定 `UVE_SNAPSHOT_ID=20261123`
- [x] 新增 `requirements-ml.txt`；ML 测试加显式依赖 skip 理由（不 Mock、不伪装 skip）
- [x] 全套 pytest：**1105 passed / 2 skipped / 0 failed / 0 errors**
- [x] 50 股冻结确定性：连跑两次 **0 差异**；NVDA=125.53、rfr=0.04912 与历史记录一致
- [x] 50 股字段漂移审计：**0/50**（`rd_status`/CAGR/WACC/base_fcf/beta/rfr/price/tg）
- [x] False SOLVED = **0**（32 个 Solved 全部 `relative_residual <= 1e-4`）
- [x] Golden 回归 13 passed，零漂移
- [x] ruff `E4,E7,E9,F`：本轮改动/新增文件 **全通过**；仓库既有 24 条**未清理**（非本轮引入）
- [x] 未放宽任何估值标准：Solved 仍 **32**（32 Solved / 9 No Solution / 9 路由排除）

---

## Session #54 Checklist — MC Raw vs Adjusted CAPM Ke 溯源 Note

- [x] 数据溯源审计（8 个变量逐个查证真实来源，禁止按名称猜测）
- [x] 确认 Rf/ERP 口径一致（bank 模型与 MC 均取 `data.market.*`，默认值同 0.04/0.06）
- [x] **发现真 bug**：`_resolve_discount_inputs_detail` 写 `kwargs["_capm_chain"]` 永不回传 → `breakdown["capm_chain"]` 恒 None（JPM/BAC/GS 实测确认）
- [x] 修复为返回值携带 chain；**Ke 数值零变化**（修复前后逐位一致）
- [x] **发现第二处缺口**：银行 MC 成功路径不渲染 notes → 用户看不到 Note；新增 `bank_ke_note_lines()`
- [x] 新增 `build_bank_ke_note()`（7 项信息 + 4 类调整可区分 + 数据不全即沉默）
- [x] 新增 `tests/test_bank_ke_note.py`（19 项，覆盖规格要求的 10 类场景）
- [x] Golden：三份指纹 **md5 字节级一致**，未重新生成基线
- [x] 50 股冻结 Before/After：**全字段 0 差异**，status 不变（32/9/9）
- [x] 全套 pytest：**1124 passed / 2 skipped**
- [x] ruff `E4,E7,E9,F`：All checks passed
- [x] 真实报告端到端验证：GS 渲染出 -152.3 bps 银行 band 夹紧说明
- [x] 未修改任何 MC 计算（seed / N / 分布 / median / percentiles / status 全不变）

---

## Session #55 Checklist — Bank Valuation & Monte Carlo Master Audit

- [x] 数据溯源审计先行：银行模型只有 DDM + RIM（无 FCFF/EV 路径），路由 `BANK/FINTECH/NEOBANK → Bank DDM + Bank RIM`
- [x] **证伪 #1（未改动）**：Rf 硬编码 0.04 **不是 bug** —— 规格 §8.1 GS fixture（Raw β=1.368 → Raw Ke=11.52%）仅在 rf=0.04 成立；改成 config 的 0.045 会得 12.02%，与规格冲突
- [x] **证伪 #2（未改动）**：银行不使用 `bottom_up_beta` **不是 bug** —— 规格 GS「Selected β=1.091」实为 band 夹紧反推的**等效 β**（(10%−4%)/5.5%），真选定 β=raw=1.368；且 bottom-up 链的 D/E 含存款（规格 §5 禁止把存款当有息负债）
- [x] 证伪 #3：RIM 数学 vs 独立重实现 → JPM/BAC/GS 绝对误差 0.0
- [x] 证伪 #4：MC 可复现性 → seed=42，3 个新实例逐位一致；n_valid=2000 / n_invalid=0
- [x] **发现真 bug**：`breakdown["beta_raw"]` 在未夹紧时恒为 None（`chain.ke_adjusted` 为假 → 审计字段被抹掉）；改为始终取 `chain.raw_beta`
- [x] **发现真缺口**：银行 Rf 回落 4% 无溯源，与市场实测值不可区分；新增 `BetaChain.risk_free_source`
- [x] **发现真缺口**：note 缺规格 §3.4/§8.2 要求的三层 Ke 分解（raw → selected → used）
- [x] 新增三层分解：`β 调整 bps` + `银行 Ke 区间夹紧 bps`，仅在有 `normalized_*` 时渲染（不编造 0 bps 分层）
- [x] 一致性守卫：`normalized_ke == rf + beta_selected×erp`（1e-9），否则沉默 —— 修正了原先「两层求和==总差」的**恒真死代码**（代数上必然成立）
- [x] 假定 Rf 显式告警（`assumed_*` → `⚠ 非市场实测`），市场来源不告警
- [x] 新增 `tests/test_bank_model_audit.py`（14 项）+ `tests/test_bank_ke_note.py` +9 项
- [x] Golden 三份指纹：**零漂移**，未更新基线
- [x] JPM/BAC/GS 端到端：vps / MC median / beta / beta_raw **逐位不变**
- [x] 全套 pytest：**1146 passed / 2 skipped**（+22）
- [x] ruff `E4,E7,E9,F`：All checks passed
- [x] 未放宽任何经济合理性标准（无模型从不适用被抬成已解）
- [ ] 遗留：银行专用会计字段（NII/NIM/CET1/RWA/存款/拨备/NPL/有形账面）数据层 0 处引用 → 规格 §2/§5/§9 前提缺数据，待产品决策
- [ ] 遗留：FINTECH 与 BANK 共享银行模型路由（Visa 进入银行模型），分类口径问题

### 复审补正（β 字段语义）
- [x] 取证确认：`capm_engine.py` band 夹紧时**覆写** `valuation_beta` → GS 的 1.091 = `(10%−4%)/5.5%`，是反推等效值
- [x] 新增 `beta_selected`（=1.368，选择层结果）与 `clamp_equivalent_beta`（=1.091，派生值，未夹紧时为 None）
- [x] Note 不再把 1.091 冠以「选择方法」；改为「夹紧等效 β=1.091，由 Ke 反推，非选择结果」
- [x] `valuation_beta` 语义保持不变（scenario / MC 依赖「能复现所用 Ke 的 β」）
- [x] CHANGELOG / AGENT 中「Selected Beta=1.091」的旧表述同步修正
- [x] 数值零漂移：GS RIM vps=426.2326…、MC median=426.2932… 逐位不变；golden 零漂移
