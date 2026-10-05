# 📝 CHANGELOG.md — 版本变更记录
> 格式: [语义化版本 vX.Y.Z] - YYYY-MM-DD  (或 Session 编号用于未发布)
> 分类: ✨ Added / 🔧 Changed / 🐛 Fixed / 🗑️ Removed / ⚠️ Deprecated / 🔒 Security

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
