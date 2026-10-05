# 📈 通用估值引擎 Telegram Bot (Universal Valuation Engine)

> 基于 Python 3.13 的股票估值系统，支持 11 种商业模式分类、6 种估值模型、WACC 七步法实时计算、敏感性分析矩阵，并通过 Telegram Bot 提供服务。

---

## ✨ 核心特性

### 🔍 商业模式识别 (Business Type Classification)
- **11 类分类体系**：MatureTech / SaaS / Semiconductor / ConsumerCyclical / REIT / Bank / Insurance / Commodity / Utilities / Conglomerate / Unknown
- **混合分类器**：LightGBM 多分类 (数值 + TF-IDF 文本) + 确定性规则覆盖 + 结构强规则兜底
- **Top-2 候选 + 概率分布**：低置信度自动回退规则引擎 (阈值 ML_FALLBACK_THRESHOLD=40%)
- **1001 只真实训练数据**：已完成特征提取，等待人工标注 (见 `classification\labeling_dump.csv`)

### 🧮 估值模型 (Valuation Models)
| 模型 | 适用场景 | 输出 |
|------|----------|------|
| DCF (两阶段) | 成熟稳定企业 | 每股内在价值 |
| Reverse DCF | 验证市场预期 | 反推隐含增长率 |
| NAV (净资产) | REIT / 投资控股 | 每股 NAV 及折溢价 |
| Bank (银行专用) | 银行 / 保险 | DDM / ROE 估值 |
| SOTP (分部估值) | 多元化集团 | 各部分加总值 |
| Multiples (可比) | 全行业辅助 | PE / PB / EV-EBITDA |

### 📊 WACC 七步法 (NO 默认值!)
严格从数据推导，**拒绝 8%拍脑袋值**：
```
Step 1: Rf (10Y 美债收益率，Treasury.gov 实时拉取)
  → Step 2: Beta (5Y 月收益率对 SPY 回归)
    → Step 3: ERP (股权风险溢价，Damodaran 级参数化)
      → Step 4: CAPM → Cost of Equity
        → Step 5: Cost of Debt (利息/总负债 + 信用利差 proxy)
          → Step 6: Effective Tax Rate (财务数据推导)
            → Step 7: Cap Structure (D/E 实时权重)
              → WACC = E/V*Ke + D/V*Kd*(1-T)
Sanity Check: 输出值 vs 行业区间 (如科技 9-13%, 公用 5-7%)
```

### 📉 终值增长率 TVG 智能约束
严格遵循 Gordon 增长模型数学边界：
```python
TVG = min(
    企业层面可支撑增速,
    经济体名义GDP (3-4%),
    WACC - 0.5%   # 数学硬约束: g < WACC
)
输出三档情景: Low = 1.5%  Base = 2.5%  High = 3.5% (自动clip)
```

### 🔬 敏感性分析 + 稳定性分级
- **WACC (±3%) × g (±1.5%) 双维度矩阵** (9 或 25 单元格)
- **Base 情景单元格斜体高亮** (基准值定位)
- **波动率分档**：
  - Stable: ±<10% 变动 (<15% cells out of ±20% band)
  - Moderate: 10-20%
  - Sensitive: 20-40%
  - Highly Sensitive: >40% ⚠️ 谨慎依赖单点估值

### 🤖 Telegram Bot 接口
```
/start          欢迎
/value AAPL     完整估值报告 (DCF + 矩阵 + 分级)
/value_fast     跳过蒙特卡洛 (快 3-5s)
/wacc AAPL      仅 WACC 拆解 + Sanity Check
/classify AAPL  仅商业模式分类 (ML prob + Top-2)
/models         适用估值模型 + 解释
```

---

## 🚀 快速开始 (Quick Start)

### 1. 环境准备
```powershell
# 克隆/进入项目
cd Telegram股票分析

# .venv 已存在，直接激活 (Windows)
.venv\Scripts\Activate.ps1

# 如需全新安装
pip install -r requirements.txt   # 如无 requirements.txt，参考模块导入
```

### 2. 配置 .env
```powershell
Copy-Item .env.example .env
# 编辑 .env，填写:
TELEGRAM_BOT_TOKEN=你的BotFather_token
# 其他可选参数 (均有默认值):
#   DCF_FORECAST_YEARS=5
#   WACC_DEFAULT=0.09   (硬约束: 仅当7步全部失败才会用)
```

### 3. 运行
```powershell
# 完整功能入口
python main.py                    # 启动 Telegram Bot
python main.py demo AAPL          # 控制台演示 AAPL 估值全流程
python main.py demo_fast NVDA     # 跳过MC快速演示
python main.py test_demo          # AAPL/MSFT/NVDA 三连演示
python main.py test               # 运行 pytest 套件
```

---

## 🧠 ML 模型训练 (当前重点!)

### 当前状态
✅ **1001 只真实股票特征数据已就绪** → `classification\labeling_dump.csv`

### CSV 结构 (20 列)
| 组 | 字段 | 说明 |
|----|------|------|
| 标识 | `ticker` | 股票代码 (AAPL等) |
| 文本 TF-IDF | `company_name` `sector` `industry` | 用于 TF-IDF + 关键词覆盖 |
| **15数值特征** | `log_revenue` `revenue_cagr_3y` `gross_margin` `gross_margin_vol_3y` `operating_margin` `operating_margin_vol_3y` `fcf_margin` `capex_to_revenue` `interest_to_revenue` `de_ratio` `beta` `market_cap_log` `pe` `pb` `ev_ebitda` | ML 训练主信号 |
| **待人工填** | **`label`** | ⚠️ BusinessType.value PascalCase |
| 备注 | `note` | 如有synthetic填充会写明 |

### 下一步: 人工标注 → 训练
```
Step 1: 打开 classification\labeling_dump.csv (Excel / Google Sheets)
Step 2: 填充 label 列，11 种取值 (大小写敏感!):
          MatureTech | SaaS | Semiconductor | ConsumerCyclical | REIT |
          Bank | Insurance | Commodity | Utilities | Conglomerate | Unknown
Step 3: 保存 CSV (UTF-8)
Step 4: 修改 classification\ml_classifier.py 第 ~705 行:
          旧: X_num_list, X_text, y_raw = build_synthetic_training_set()
          新: X_num_list, X_text, y_raw = build_training_set_from_csv(r"classification\labeling_dump.csv")
Step 5: 删除旧工件触发重训
          Remove-Item classification\_ml_artifacts\*.pkl
Step 6: 触发自动重训
          python main.py demo AAPL
```

---

## 📁 项目结构 (Project Structure)
```
Telegram股票分析/
├── main.py                      # ⭐ CLI入口
├── config.py                    # 日志 / 枚举 / 路径 / 默认参数
├── AGENT.md                     # ⭐ AI接力状态文件 (必读)
├── README.md                    # 本文件
├── TODO.md / ROADMAP.md         # 待办 + 路线图
├── CHANGELOG.md / DECISIONS.md  # 变更 + 架构决策
│
├── _dump_features_for_labeling.py  # ✨ 1001行数据的来源脚本
├── _demo_ml_classifier.py       # ML 单独演示
├── _ab_classifier_compare.py    # 对比 deterministic vs synthetic vs real
│
├── data/                        # 数据层
│   ├── providers.py             # Yahoo / Treasury / Synthetic Provider
│   ├── models.py                # FinancialData / CompanyProfile 数据类
│   ├── normalizer.py / validator.py
│
├── valuation/                   # 估值底层参数
│   ├── wacc.py                  # ⭐ 七步法 WACC
│   └── terminal_growth.py       # ⭐ TVG 约束
│
├── models/                      # 6 个估值模型 + 路由
├── analysis/                    # 敏感性 / 风险 / 情景 / 一致性
├── classification/              # ⚠️ 当前工作重点
│   ├── classifier.py            # 确定性规则引擎 (~85%)
│   ├── ml_classifier.py         # LightGBM + TF-IDF (合成版)
│   ├── labeling_dump.csv        # ✨ 1001行, 待标注
│   └── _ml_artifacts/           # 重训后生成3个.pkl
│
├── simulation/monte_carlo.py    # 蒙特卡洛 (demo_fast 跳过)
├── forecasts/forecast.py        # 收入/利润预测
├── reporting/dashboard.py       # 报告/图表
├── telegram_bot/                # python-telegram-bot 集成
├── tests/                       # pytest 套件 (~45%覆盖)
└── .cache/{yahoo_finance,treasury_yield}  # 4h TTL JSON缓存
```

---

## ⚠️ 已知问题 & Workaround
| 问题 | 影响 | 解决 |
|------|------|------|
| Yahoo `assetProfile` 401 (830/1001) | sector/industry 文本缺失 | 数值特征 100% 完好；company_name 提供足够 TF-IDF 信号；结构规则兜底 Bank/REIT/Semi/Util |
| CSV 顶部疑似多一行 "ticker" | PowerShell 导出 artifact | pandas/python `csv` 可自动跳过；若 `build_training_set_from_csv` 报错，手动删除那一行 |
| 少量 ticker 404 → synthetic | <1% 数据非真实 | note 列标有 `filled=synthetic`，标注时可优先标 Unknown 或跳过 |

---

## 🧪 验证你的修改
每次修改代码后运行:
```powershell
python main.py test              # pytest 全量
python main.py demo_fast AAPL    # 快速 AAPL 冒烟
python _ab_classifier_compare.py # 如有分类器改动
```

---

## 🛠 数据缓存策略 (成熟稳定，勿动)
- **路径**: `.cache/yahoo_finance/{TICKER}_{YYYYMMDD}.json`
- **TTL**: 4 小时 (同一天重复访问不触网)
- **原子写入**: `write tmp → os.replace`，断电不产生半写损坏文件
- **大小**: 当前 ~500 files / ~200MB (可随时删，会自动重拉)

---

## 📚 参考
- [AGENT.md](AGENT.md) — AI 接力完整状态 (**必看**，尤其是 Next Immediate Task)
- [TODO.md](TODO.md) — 长期待办事项
- [ROADMAP.md](ROADMAP.md) — 产品路线图
- [DECISIONS.md](DECISIONS.md) — 架构决策记录 (ADR)
- [CHANGELOG.md](CHANGELOG.md) — 每次版本变更记录
- `_dump_features_for_labeling.py` 顶部注释 — 详细 3 步工作流

---

**Made with 🐍 + 📈 by TRAE Agent on Python 3.13**

**Next Step: 人工标注 classification\labeling_dump.csv 中的 `label` 列 (1001 行)**
