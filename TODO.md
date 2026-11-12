# ✅ TODO.md — 长期待办事项
> (当前: 2026-11-12) 通用估值引擎 Telegram Bot

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
| L-08 | 反向 DCF 升级为三变量求解 | ⬜ TODO | 求解「营收 CAGR + 稳态 FCF margin + capex intensity」三变量，输出当前价隐含的最低假设 (Session #07) |
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

---

## 💡 注意事项
1. **严禁重复做 C-01**：1001 行 CSV 已完成，任何修改只需 UPDATE，不需要重新跑 `_dump_features_for_labeling.py`
2. **C-02 人工标注**是当前唯一 BLOCKER，所有后续任务都依赖它
3. 如果 C-05 评估准确率 <90%：先回到标注纠错 (预计有 5-10% 边界错误正常)，再考虑加特征 (M-02/M-03)
