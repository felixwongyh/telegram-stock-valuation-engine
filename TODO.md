# ✅ TODO.md — 长期待办事项
> (当前: 2026-11-13) 通用估值引擎 Telegram Bot

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
| H-03 | 修复 Yahoo `assetProfile` 401 问题 | ⬜ TODO | 方案: 增加二级数据源 (Alpha Vantage / Financial Modeling Prep) 补 sector/industry |
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
| M-16 | SOFI hybrid 标签 / SOTP 阈值复评（数据驱动） | 🟡 **PARTIAL** | 阈值已提为具名常量 `HYBRID_FIN_TO_TECH_FLOOR=0.08` 并加边界锁定测试（**锁定而非下调**）；根因 sector/industry 缺失属特征问题，待 **H-03** 补二级数据源后复评，勿动阈值（会扰动 golden 基线）(Session #14) |
| M-17 | UPST 递归自我改进 3 轮（分类子串误匹配 → 金融 EV/Sales 剔除 → 渲染层口径泄漏） | ✅ **DONE** | round1 `keyword_hit()` 词边界（修复 ticker `upst` 被 `"ups"` 子串误匹配 → Industrial）；round2 金融分叉剔除 `EV/Sales`（一致性 Very Weak→Moderate）；round3 渲染层读口径契约（WACC Risk→Cost of Equity Risk / EV 复核→P/B·P/E·RIM）；pytest 106/106；DEFECTS 空 (Session #15 ADR-026/027) |
| M-18 | 金融"数据不足"模型字段语义 + 金融情景跨度复评 | ⬜ TODO | ① `applicable_models` 含 `Bank DDM`（No dividend → Insufficient Data）却按「不适用」计入分母，字段名与实际计分口径不一致，需明确命名；② UPST 三档情景跨度仅 9% SV（金融 β±0.30 校准）——对 β=2.50 的高波动标的或过窄，待以更多金融标的（SOFI/JPM/UPST）对比复评 (Session #15) |
| M-19 | **Phase 1：修复现有引擎（负终值 + 状态污染 + 数学下限 + 残差）** | ✅ **DONE** | ① 负终期 FCF 抑制（`gordon_terminal_value()` 统一出口，不翻转符号 + `terminal_fcf_negative` 标注）(ADR-028)；② 预测年限单一真源 `resolve_forecast_horizon()`，删除 `self.horizon` 污染 (ADR-029)；③ WACC−g 统一下限 `MIN_WACC_TG_SPREAD=0.005`；④ 反向 DCF 求解器残差检查（`rel_resid>1e-3`→APPROXIMATE）；⑤ Round-trip 测试 10 用例；pytest 116/116 (Session #16) |
| M-20 | **Phase 2：反向 DCF 升级为约束式隐含求解器** | ✅ **DONE** | 单变量 one-at-a-time 独立反推 **Implied Operating Margin / FCF Margin / WACC / Terminal Growth**（+ 既有 Revenue CAGR）；`_solve_implied_scalar()` 硬边界（越界→`NO_SOLUTION_IN_RANGE` 指名边界，**不钳制**）+ 单调性 + 残差检查；FCF margin 经 flat-margin 桥独立化；透传 `ImpliedExpectations` + `_implied_section()` 渲染；测试 8 用例；pytest 124/124 (Session #17 ADR-030) |
| M-21 | **求解器 P0/P1 加固（用户代码审查 6 项）** | ✅ **DONE** | ① Brent 失败后 bracket 重校验（`f(a)·f(b)>0` → 拒可疑根 `NO_SOLUTION_IN_RANGE`）+ 求解后 residual 检查；② 单调性实测（21 点采样 → 非单调扫描 root brackets → 0 无解/1 解/>1 `MULTIPLE_ROOTS`）；③ `terminal_fcf_negative` 贯穿 breakdown/期望/渲染 + `_finalize_revenue_cagr()` 降级 `SOLVED→APPROXIMATE`（Terminal Value Suppressed）；④ 端点根合法（含容差 → SOLVED）；⑤ 常数目标 `FLAT_OBJECTIVE`/`NO_SOLUTION_IN_RANGE`；⑥ 自查修复 2 处（`mono_tol` 步长尺度 + 递减可达区间语义）；测试 +18；pytest 142/142；golden 无漂移 (Session #18 ADR-031) |
| M-22 | 隐含驱动纳入 golden 指纹/invariant | ⬜ TODO | 当前隐含驱动（OM/FCF Margin/WACC/TG）未纳入 `report_fingerprints.json`；待一次有意漂移审阅后再决定纳入，避免求解数值抖动污染基线 (Session #17/#18 遗留) |
| M-23 | **Rf 单一真源 + Terminal Growth 三档语义重定义（用户代码审查 2 项 P0）** | ✅ **DONE** | ① **P0-1**：`WaccCalculator._implied_cost_of_debt()` 新增 `risk_free_rate` 形参，`calculate()` 传入已解析 `rf` → CAPM 与所有债务成本 fallback **共用同一 Rf**（消除 MarketData 空值时 ke/kd 口径背离）；② **P0-2**：重定义三档经济学含义（Base=长期稳定终值增长率，受 GDP+Gordon 双约束；Low/High=情景区间），新增引擎契约字段 `high_exceeds_gdp`/`gdp_ceiling`/`band_labels` + `BAND_LABELS` 常量；`derivation_trace()`/`models/dcf.py`/`dashboard.py` 三处显式标注「High 为乐观情景，非长期稳定终值增长率」；测试 +5；pytest 147/147；golden 无漂移 (Session #19 ADR-032) |
| M-24 | **Quality-Weighted Median 边界修复（用户代码审查 1 项 P1）** | ✅ **DONE** | `_weighted_median()` 原返回「首个累计权重 ≥ total/2 的值」→ 等权（常见）且模型数为偶数时返回第 n/2 个值而非 `mean(values[n/2-1], values[n/2])`，导致加权中位数≠普通中位数（AAPL 176.12 vs 165.24）。改用标准 **midpoint 定义**（下/上加权中位数取平均）→ 等权时精确退化为普通中位数；零/负权重剔除；新增 `tests/test_model_agreement.py` 16 用例；golden 4 只有意漂移已审阅重生成；pytest 163/163 (Session #19 ADR-033) |

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
| L-09 | 蒙特卡洛与模型集成口径统一 + 相关性校准 | ⬜ TODO | MC 反映低覆盖问题；驱动因子相关矩阵用历史协方差校准 (Session #07 ADR-016) |

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

---

## 💡 注意事项
1. **严禁重复做 C-01**：1001 行 CSV 已完成，任何修改只需 UPDATE，不需要重新跑 `_dump_features_for_labeling.py`
2. **C-02 人工标注**是当前唯一 BLOCKER，所有后续任务都依赖它
3. 如果 C-05 评估准确率 <90%：先回到标注纠错 (预计有 5-10% 边界错误正常)，再考虑加特征 (M-02/M-03)
