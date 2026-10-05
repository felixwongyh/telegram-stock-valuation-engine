# ✅ TODO.md — 长期待办事项
> (当前: 2026-10-05) 通用估值引擎 Telegram Bot

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

---

## ✅ 已完成 (最近)
| ID | 任务 | 完成日 | 备注 |
|----|------|--------|------|
| C-01 | 1001只股票特征数据收集 | 2026-10-05 | 1001 行 / 15 数值特征 / 0 fail |
| — | 批量生成 7 个项目文档 | 2026-10-05 | AGENT / README / TODO / CHANGELOG / DECISIONS / ROADMAP |
| — | 数据完整性验证 + CSV 去重 | 2026-10-05 | 从 1533 行 → 1001 行 (无重复 ticker) |

---

## 💡 注意事项
1. **严禁重复做 C-01**：1001 行 CSV 已完成，任何修改只需 UPDATE，不需要重新跑 `_dump_features_for_labeling.py`
2. **C-02 人工标注**是当前唯一 BLOCKER，所有后续任务都依赖它
3. 如果 C-05 评估准确率 <90%：先回到标注纠错 (预计有 5-10% 边界错误正常)，再考虑加特征 (M-02/M-03)
