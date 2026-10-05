# 🗺️ ROADMAP.md — 产品路线图
> **当前日期**: 2026-10-05  
> **当前阶段**: 🟡 **Phase 2b — 1001 行特征收集完成，等待人工标注**  
> **总体进度**: 约 65% (距 v1.0.0 发布)

---

## 🎯 愿景 (Vision)
> 一个 **可审计、可解释、跨市场** 的股票估值助手，通过 Telegram 提供服务，  
> 将机构级 DCF/WACC 方法论带到个人投资者指尖，  
> 且商业模式分类准确率 ≥ 95%，避免致命模型错配。

---

## 阶段总览 (Timeline & Milestones)

```
Phase 1  规划设计      2026-09     [✅ 100%]
  ├─ 模块划分: 9个目录 (data/valuation/...)
  ├─ 数据契约定义: FinancialData / CompanyProfile Dataclass
  └─ 硬约束明确: WACC7步 / TVG约束 / 缓存4h

Phase 2  核心开发      2026-09     [✅ 95%]
  2a ─ 数据层: YahooProvider + TreasuryProvider + 合成fallback
  2b ─ 估值底层: WACC7步 + TVG约束 + DCF/ReverseDCF/NAV/Bank/SOTP/Multiples
  2c ─ 分析层: 敏感性矩阵 + 风险/情景/一致性
  2d ─ 分类器: 确定性85% → LightGBM合成版98%(train)
  2e ─ 接口: main.py统一入口 + Telegram Bot集成
  2f ─ ⭐ **1001行特征收集** ⭐ ← 我们现在在这里 (刚完成)
               ↓↓↓ [BLOCKER: 人工标注 label 列] ↓↓↓
  2g ─ ⚠️ 真实模型训练 + AB测试对比

Phase 3  测试与质量   2026-10~11   [⬜ ~10%]
  3a ─ pytest 覆盖率: 45% → 80%
  3b ─ 回归测试集: 30只 ticker × 3市场环境 (bull/bear/sideway)
  3c ─ 端到端演示: Telegram端 ←→ 估值报告格式严格校验
  3d ─ 边界case: 负盈利银行 / 刚IPO无3年数据 / 仙股市值<1亿

Phase 4  生产部署     2026-11~12   [⬜ 0%]
  4a ─ Render / Cloudflare Workers 部署 (参考 user_profile 偏好)
  4b ─ Watchlist SQLite 持久化 (peewee 已安装)
  4c ─ 监控: Yahoo API成功率 / 响应延迟 / 用户限流
  4d ─ 告警: 估值偏离内在价值±20%主动推送

Phase 5  扩展与运营   2027-Q1+     [⬜ 0%]
  5a ─ 双市场: 港股 0700.HK / A股 600519.SS
  5b ─ Dashboard PNG 图表报告 → Telegram 内联
  5c ─ 导出到 Google Sheets (用户偏好)
  5d ─ 社区功能: 用户共享估值 / 讨论区链接

v1.0.0 公开发布      2026-12+
```

---

## ✅ Phase 1 — 规划设计 (DONE ✅)
| 任务 | 状态 | 产出 |
|------|------|------|
| 1.1 定义 BusinessType 11类分类体系 | ✅ | config.py BusinessType 枚举 |
| 1.2 定义 FinancialData 数据契约 | ✅ | data/models.py 10+ dataclass |
| 1.3 明确 WACC7步 / TVG三重约束 硬约束 | ✅ | DECISIONS.md ADR-001/002 |
| 1.4 模块划分与职责边界 | ✅ | 9 个包 + 清晰 import 依赖图 |
| 1.5 技术栈锁定: Python3.13 + httpx + LightGBM + TG | ✅ | .venv 环境就绪 |

**关键风险已处理**:
- 数据缺失时仍能估值 → SyntheticDataProvider 兜底

---

## 🟡 Phase 2 — 核心开发 (2f 完成, 等待 2g)

### 2a 数据层 ✅
- Yahoo Finance Chart + Fundamentals 双端点异步抓取 (semaphore=8)
- Treasury.gov Yield Curve CSV (带完整浏览器 headers 防403)
- `.cache/{yahoo_finance,treasury_yield}` 4h TTL 原子 JSON 缓存
- 失败率: 实测 <1%，synthetic fallback 兜底

### 2b 估值底层 ✅
- **WACC 7步法**: 从 Rf(10Y) → CapStructure 完整可溯
- **TVG 约束**: min(企业, 名义GDP, WACC-0.5%) 三档情景 Base/Low/High
- 6 种估值模型: DCF (2阶段) / Reverse DCF / NAV / Bank DDM / SOTP / Multiples

### 2c 分析层 ✅
- WACC×g 敏感性矩阵 (25 cell) + Base单元格高亮 + 稳定性4档分级
- Scenario 三档情景: Low/Base/High 驱动整个估值链
- Risk 因子 + Model Agreement (多模型一致性)

### 2d 分类器 ✅
- 确定性规则 BusinessClassifier (~85%): 11 类规则 + 适用性裁决
- LightGBM 合成版: 15数值 + TFIDF(χ² K=60) → Train Acc ~98%
- 混合架构 MLHybridClassifier: Top1 Prob≥40%用ML，否则回退规则
- 结构覆盖4类强规则: Bank / REIT / Semi / Util → ≥99% 准

### 2e 接口 ✅
- `main.py`: 6 个子命令 (bot/demo/demo_fast/test_demo/test/help)
- Telegram Bot: `/value /value_fast /wacc /classify /models`

### 2f ⭐ 1001 行真实特征收集 ✅ (2026-10-05)
| 指标 | 数值 |
|------|------|
| 总行数 | **1001** (去重后) |
| 15数值特征完整率 | 100% |
| company_name 完整率 | 100% |
| sector/industry 完整率 | 171/1001 (约17%) |
| synthetic 填充占比 | <1% (note 列可见) |
| 总耗时 | ~1.4 min (并发8 + 缓存) |

### 2g ⚠️ 等待: 真实训练 + AB 测试 (BLOCKER)
**输入依赖**: C-02 人工标注完成 (见 TODO.md)

完成后 1 天内可完成:
```
[ ] 修改 ml_classifier.py L705: 1行替换
[ ] 删除 3 个旧 .pkl 文件
[ ] python main.py demo AAPL 触发重训 (~10-30s)
[ ] 记录 train_meta_v2.pkl 准确率
[ ] _ab_classifier_compare.py 输出混淆矩阵: det / syn / real 三版对比
```

---

## ⬜ Phase 3 — 测试与质量
**目标日期**: 2026-10~11 (2-3 周)

### 3a pytest 覆盖率 45% → 80%
| 模块 | 当前 | 目标 | 重点测试内容 |
|------|------|------|--------------|
| classification/ml_classifier.py | 中 | ✅ | CSV→训练→预测链路；边界label处理；结构覆盖 4 类数值强规则各 3 case |
| valuation/wacc.py | 低 | ✅ | 7步每步单独失败回退；Sanity Check 阈值；与手动计算 AAPL/WFC 对账 |
| models/router.py | 低 | ✅ | 11 BusinessType × 适用模型映射表锁死；Bank/REIT 不会错分到 DCF-growth |
| sensitivity.py | 中 | ✅ | 矩阵尺寸；Base单元格坐标；Highly Sensitive阈值触发 |

### 3b 30 只回归测试集 (固定黄金样本)
```
MatureTech: AAPL MSFT ORCL
SaaS:       NOW CRWD DDOG
Semi:       NVDA AVGO TSM ASML AMD
ConsCycl:   TSLA AMZN HD BKNG
REIT:       AMT PLD EQIX PSA O
Bank:       JPM BAC WFC C GS MS
Insurance:  BRK-B PGR TRV MET
Commodity:  XOM CVX FCX NUE BHP
Utilities:  NEE DUK SO D AEP
Conglomerate: BRK-B GE HON CAT BA
Unknown:    SPCE RIVN LCID HOOD
```
→ 每只都有 "预期分类/预期模型/预期估值区间上下界" 锁死

### 3c 端到端格式校验
- Telegram Markdown V2 特殊字符转义 (`. - ( ) + = ! ~ > # | { }`)
- 报告段落顺序: 摘要 → 分类 → WACC拆解 → 估值表 → 敏感性 → 建议

### 3d 边界 case
| Case | 预期行为 |
|------|----------|
| 近期 IPO 无 3 年数据 | 回退到 Multiples + 警告 "历史数据不足" |
| 银行负净收入 (金融危机模拟) | Bank 模型自动切到 P/B 估值 |
| 仙股 (market cap < $50M) | 明确提示 "流动性风险极高，估值不可靠" |
| 高增长 SaaS (负盈利但高 FCF) | 仍可 DCF，注意 TVG 钳制不会发散 |

---

## ⬜ Phase 4 — 生产部署
**目标日期**: 2026-11~12

### 4a 云部署
- **Webhook Mode**: Render Web Service + Webhook 回调 (比长轮询更省)
- **Telegram Bot Token** 通过环境变量注入 (已在 .env 模板)
- **Secret Webhook Path**: 防止伪造请求

### 4b 数据持久化
- **SQLite + peewee** (项目已预装) 3 张表:
  - `valuations(id, ticker, timestamp, result_json, user_id)`
  - `watchlists(user_id, tickers_json)`
  - `daily_close(ticker, date, close)` 每日收盘快照
- 可选迁移到 **Supabase PostgreSQL** (user_profile 偏好)

### 4c 监控
- Yahoo 端点成功率 P95 > 98% (当前 99%+)
- 平均响应: /value_fast < 10s；/value < 20s
- 用户级限流: 20 req/day (可管理员调)

### 4d Watchlist 主动推送
- 每日收盘后拉取
- 价格 < Base 估值 80% → **Undervalued** 推送 + 理由
- 价格 > Base 估值 120% → **Overvalued** 推送 + 风险提示

---

## ⬜ Phase 5 — 扩展与运营
**目标日期**: 2027-Q1+

### 5a 双市场支持
| 市场 | 数据源 | 注意 |
|------|--------|------|
| 美股 (US) | Yahoo Finance ✅ | 当前已完美 |
| 港股 (.HK) | 东方财富 / Yahoo `.HK` 后缀 | WACC 切换 HKMA 基本利率 / 恒生 ERP |
| A股 (.SS/SZ) | 东方财富原生API | 汇率考虑; ERP 使用中证债券收益率 |

### 5b 图表报告
- Matplotlib/Seaborn 生成 PNG (无需浏览器)
- 内含: WACC 瀑布图 + 估值分布条形 + 敏感性热力图 (Base 十字准星高亮)

### 5c Google Sheets 导出
- 参考用户偏好 (user_profile: 熟悉 Google Sheets/Drive API)
- `/export_sheet` 命令: 最近 30 天估值写到指定 Sheet

### 5d 运营
- 每季度回测: Top10 低估组合 vs S&P 500 → 业绩基准证明
- 用户标注反馈闭环: 用户"分类错误"一键报告 → 训练集增量修正

---

## 🎯 关键 KPI 追踪
| KPI | 目标 | 当前 | 测法 |
|-----|------|------|------|
| 分类准确率 (11类) | ≥ 95% | ~85% (规则) | 30 只回归集人工对账 |
| Bank/REIT/Semi/Util 分类 | ≥ 99% | ~98% | 结构强规则已接近 |
| 单 ticker 估值耗时 (缓存命中) | < 2s | ~1.2s ✅ | main.py demo_fast 10 次平均 |
| 单 ticker 估值耗时 (冷) | < 10s | ~7s ✅ | 删除 cache 后测 |
| 用户报告 "明显错误估值" | < 2% | N/A | 部署后统计 |
| Telegram 报告格式错误 | 0 | N/A | Markdown V2 转义严格测试 |

---

## ⚠️ 已知风险与缓释
| # | 风险 | 概率 | 影响 | 缓释策略 |
|---|------|------|------|----------|
| R1 | Yahoo API 大规模封号 | 中 | 高 | 引入 Alpha Vantage / FMP 二级数据源 (DECISIONS P-001) |
| R2 | 人工标注质量差 (错误率>10%) | 高 | 中 | 标注后跑一致性校验: 规则/人工冲突行人工再审; 允许 Unknown 占比≤5% |
| R3 | 真实训练准确率未达 95% (≤90%) | 中 | 中 | 引入 M-02 季度变化特征 / M-03 ETF 相关特征 再训练 |
| R4 | Telegram 封禁 Bot (Spam 误报) | 低 | 高 | 使用官方推荐 webhook 模式; 单用户 rate limit 严格 |
| R5 | 用户输入非美股代码崩溃 | 中 | 低 | 已在 Provider 层做了 synthetic fallback; 加友好提示 "市场暂未支持" |

---

## 🚀 接下来 7 天可执行清单
1. **Day 1-2**: 人工标注 1001 行 label 列 (BLOCKER)
2. **Day 3**: 切换训练源 → 重训 LightGBM → 记录 train_acc
3. **Day 4**: `_ab_classifier_compare.py` 三版对比，输出混淆矩阵 + F1
4. **Day 5-6**: 扩充 pytest (classification/ml_classifier / valuation/wacc / models/router 3 个模块先冲 80%)
5. **Day 7**: 30 只回归集黄金标注 + 端到端格式校验

→ 完成后进入 Phase 4 部署准备 🎉
