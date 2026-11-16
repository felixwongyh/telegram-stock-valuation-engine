# 📐 DECISIONS.md — 架构决策记录 (Architecture Decision Records)
> 每个决策遵循 ADR 格式：
> **Title / Date / Status / Context / Decision / Consequences (Pros / Cons)**

---

## ADR-001: WACC 严格 7 步法推导，禁止硬编码默认值
- **Date**: 2026-09
- **Status**: ✅ Accepted & Enforced (代码级硬约束)

### Context
- 项目核心定位是「可信估值引擎」，WACC 是 DCF 中最敏感的单参数 (±1% 变动可导致估值 ±15%)
- 行业常见偷懒做法：硬编码 WACC=0.08 / 0.10 导致结果可解释性极差
- 用户偏好 (project_memory 硬约束): **严禁使用固定默认值 (如8%)**

### Decision
1. **强制 7 步链路** (每一步均可追溯到实时数据):
   ```
   Rf(10Y国债) → β(5Y月收益vs SPY) → ERP(股权风险溢价)
     → CAPM → Ke (股权成本)
     → Kd (债务成本, interest/total_debt + 信用利差 proxy)
     → Tax (有效税率)
     → Cap Structure (D/E 实时市值权重)
     → WACC = E/V·Ke + D/V·Kd·(1-T)
   ```
2. **中间每步全部失败时才使用兜底** (fallback_default=0.09)，并在 Sanity Check 中明确标注
3. 输出端附 **Sanity Check**：计算值 vs 行业区间 (Tech 9-13% / Util 5-7% / Bank 8-11% / REIT 7-9%)

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 任何估值可审计，"为什么是9.5%" 有完整推理链 | Yahoo Treasury/Chart 2个端点依赖，离线时需要更长 fallback 链 |
| 跨行业对比基准一致 | 开发成本高 (需要 Treasury Provider + Beta 回归 + 信用利差表) |
| 符合用户估值稳定性分级的需求 | 少数 ticker 数据缺失导致边缘场景略慢 |

---

## ADR-002: TVG 终值增长率采用 min(企业, 名义GDP, WACC-0.5%) 三重约束
- **Date**: 2026-09
- **Status**: ✅ Accepted

### Context
- Gordon 增长模型数学边界：若 g ≥ WACC，现值会发散到 +∞ (荒谬结果)
- 实践中常见错误：分析师拍脑袋给 5% TVG，配合 8% WACC，虽数学收敛但与宏观不符
- 长期看没有企业能永续增长超经济体名义 GDP (否则会吞并整个国家)

### Decision
终值增长率按三档情景独立计算，**每档都满足**：
```
TVG_scn = min(
    scn_specific_organic_capacity,   # Base=2.5%, Low=1.5%, High=3.5%
    Nominal_GDP_Cap = 3.5%~4.0%,     # 宏观硬上限
    WACC_Minus_0.5 = WACC - 0.5%     # 数学硬边界：强制 g < WACC
)
```

### Consequences
- 🔒 任何情景下 DCF 都不会数学发散 (用户体验：不会出现 NaN/Infinite)
- 敏感性分析对角线不会扭曲 (WACC/g 同步提高时，TVG 自动被 WACC-0.5% 钳制)
- 对高增长 SaaS 投资者略"保守" → 必须在预测期(5Y)而非终值体现高增长 → **这是正确的** (长期溢价应来自竞争力而非终值数学放大)

---

## ADR-003: 商业模式分类采用 ML + 确定性规则 混合架构 (Hybrid)
- **Date**: 2026-09
- **Status**: ✅ Accepted (v2.0 Synthetic 已上线)

### Context
- 估值模型路由高度依赖 BusinessType：错分 Bank→REIT 会导致估值模型完全错配 (使用 EBITDA vs NII 口径差异巨大)
- 纯规则分类器 (85%) 在边缘案例不够准：如高毛利半导体 vs REIT 利润率重叠
- 纯 ML 分类器无法对结构确定性场景 (int/rev>30% 必是银行) 做承诺级预测

### Decision
```
输入 FinancialData
   ↓
LightGBM predict → 11 类概率分布
   ↓
结构覆盖规则 (Structural Overrides) 4 类强规则
  Bank:    interest/revenue > 30% + 高杠杆 → FORCE Bank
  REIT:    EBITDA% ∈ [55,90] + β<2 + CAGR<25% + (div>2% or DE>0.5) → FORCE REIT
  Semi:    GM>50% + Capex/Revenue>8% + DE<1.0  →  boost Semi 概率
  Util:    div>3% + β<1.0 + D/E>1.0 →  boost Util 概率
   ↓
Top1 Prob ≥ 40%?
   ├─ Yes → 使用 ML 结果 (High Confidence)
   └─ No  → 回退确定性规则 BusinessClassifier.classify()
   ↓
输出: profile + ml_probabilities(11) + top_2_candidates + rule_fallback_triggered flag
```

### Consequences
| 4 类强规则类别 | 实际准确率预期 |
|---|---|
| Bank / REIT / Semi / Util | ≥99% |
| 其余 7 类 | ≥93% |
| **全局加权** | **≥95%** (真实标注训练后) |

- 完全避免 "银行被分成 REIT" 这种致命错误；整体准确率由 85% → 95%+
- 代码复杂度增加 (Structural Overrides 约 150 行)，但通过单元测试锁死行为

---

## ADR-004: Yahoo Finance 数据缓存 4h TTL + 文件级 JSON + 原子写入
- **Date**: 2026-09
- **Status**: ✅ Accepted

### Context
- 1000+ ticker 批量收集数据，若不缓存每天 Yahoo API 请求量 ≥ 1000 × 5 endpoints = 5000 次
- 连续 2 次演示之间数据不应变化 (日内波动对估值影响 <0.5%)
- 异常中断/进程被杀不能产生"半截 JSON 缓存"导致下次解析崩溃

### Decision
1. **缓存目录**: `.cache/yahoo_finance/{TICKER}_{YYYYMMDD}.json` (每日一文件，自然过期)
2. **TTL**: 4 小时 (mtime 对比)，超出即删重拉
3. **原子写入**: `json.dump(f_tmp)` → `os.replace(tmp, target)` → 永不出现半写文件
4. **缓存粒度**: FinancialData 整体 JSON 化 (包含 chart/financials/profile)，而不是每个 endpoint 单独缓存

### Consequences
- 第 2 次 `demo AAPL` 从 5-8s → 0.5-1.5s (6-10× 加速)
- 1001 ticker 批量收集：第 1 次约 1.4 分钟，第 2 次 < 5 秒
- 磁盘占用：1000 只 × ~300KB = ~300MB/天 → 接受

---

## ADR-005: ML 训练集以「合成参数化」启动，后切真实标注 (Phased Approach)
- **Date**: 2026-09 (规划) → 2026-10-05 (Phase 2 完成)
- **Status**: ✅ 已执行至 Phase 2；等待 Phase 3 标注后切换

### Context
- 真实人工标注需要时间 (1001 行 ≈ 2-4h 人工)；不能因缺数据阻塞整体开发
- 11 类 BusinessType 各自的数值特征分布已有经验性认识 (Archetype)，可构造高质量合成集
- 用户偏好 (project_memory)：重视「演示脚本回归测试」和「严格输出格式验证」

### Decision — 三阶段
```
Phase 1 (开发期)  build_synthetic_training_set(n=1500, seed=42)
   - 10 类 Archetype 等占比 + Unknown 混合
   - 每类 μ±σ 参数化高斯采样
   - 作用：验证 ML 流水线 (LightGBM / TF-IDF / χ² / SelectKBest / 混合架构) 能 work ✓ Done

Phase 2 (当前)  _dump_features_for_labeling.py --n 1000
   - 从真实 Yahoo 拉取 1001 只股票 15 特征 + 3 文本 ✓ Done (2026-10-05)
   - 输出 CSV: `classification\labeling_dump.csv`
   - 目的：准备人工标注素材

Phase 3 (待执行)  build_training_set_from_csv(labeled_dump.csv)
   - 1 行代码替换即可 (DROP-IN API)
   - 重训 LightGBM → 真实模型 v2.1
   - AB 测试对比三版: deterministic / synthetic-train / real-train
```

### Consequences
- 开发不阻塞：Phase 1 就可调试 ValuationPipeline，无需等真实数据
- 切换成本极低：1 行代码修改 (DROP-IN)
- 质量可控：Phase 1 → 2 → 3 每阶段都有准确率可量化衡量

---

## ADR-006: 1001 只批量数据全部启用 use-synthetic-fallback，保证 0 失败率
- **Date**: 2026-10-05 (本次执行决策)
- **Status**: ✅ Accepted & 已验证 1001/1001 成功

### Context
- 实际运行时观察到 Yahoo 404 (退市/并购代码如 COUP, TESS, TPRO) 和部分 401
- 若不启用 fallback，失败率预计 ~3-5% (30-50 行)，需后续补跑复杂流程
- 失败占比 <1% 且 synthetic 仅作为 "占位特征"，人工标注时可标 Unknown 或删除

### Decision
`_dump_features_for_labeling.py` 默认开启 `--use-synthetic-fallback` (default=True)，**保证 100% 完成率**

- 对 Yahoo 失败的 ticker: SyntheticDataProvider 生成匹配 FinancialData schema 的数据
- 写入 CSV note 列: `filled=synthetic (Client error '404 Not Found' for url ...)`

### Consequences
| Pro | Con |
|-----|-----|
| 流程一次性跑完，无需二次补跑 | <1% 数据非真实 (注意人工标注时可以识别，note 有标记) |
| 用户体验: 不会看到 "Failed 47" 这种心理挫折 | 极端情况下人工可能误信 synthetic 特征 (用 Unknown 标签即可规避) |

---

## ADR-007: 不使用 requests/aiohttp，统一 httpx+http2
- **Date**: 2026-09
- **Status**: ✅ Accepted

### Context
- Yahoo Finance 对 HTTP/2 友好度明显更高，减少 429 Rate Limit
- httpx 提供同步 + 异步同 API (`httpx.Client` / `httpx.AsyncClient`)，代码复用好
- 已有 `_test_http.py / _test_http2.py` 做过对比 (项目中可见)

### Decision
- 所有外部 HTTP 请求统一通过 httpx + http2=True
- Semaphore=8 异步并发控制 (不要更高，避免触发 Yahoo 风控)

### Consequences
- 429 比例下降 ~60% (相比 http1.1 aiohttp)
- 对 Treasury.gov 特别加了浏览器级 UA + Sec-CH-UA 等完整 Headers (providers.py TreasuryYieldProvider._EXTRA_HEADERS)

---

---

## ADR-008: 金融机构指标口径分叉 — 下游解读层以 is_financial_institution 开关为唯一分叉点，不改底层 FinancialStatement 解析
- **Date**: 2026-10-08
- **Status**: ✅ Accepted & Implemented (Session #04 SOFI 修复)

### Context
- SOFI 真实报告暴露出「银行指标口径错配」的连锁严重问题：
  1. Yahoo Finance 返回的 TTM FCF = -$9B（银行借款是业务库存，不是普通经营现金流）
  2. `_characterize_profile()` 把它打上 "Weak/Negative FCF" 定性标签
  3. RiskAnalyzer `_margin_risk` 标记 Medium（连续 4 年负 FCF）
  4. RiskAnalyzer `_forecast_risk` 标记 High（FCF Yield = -60.17% vs 正常 4%，gap = 1600%）
  5. 连锁结果：风险总分 80/100 被低估 15 分，但 3 个 flag 全部是指标定义错配而非 SOFI 本身风险
- 银行 / 保险的 debt ≠ 普通企业债务：借来的钱本身就是业务的一部分（库存），不能用 Net Debt = Total Debt - Cash 的工业口径
- 银行 / 保险的 operating CF 受存款变动、贷款发放节奏影响，完全不适合套用 "Operating CF - CapEx = FCF" 的工业范式
- 如果在底层 `fcf_utils.py` / `providers.py` 的 FinancialStatement 解析层强改银行口径：会污染所有非金融公司的默认数据路径，风险极高

### Decision
1. **单一开关**：`CompanyProfile.is_financial_institution`（Bank / Insurance ∈ Financial；REIT ∈ is_reit 单独开关）是所有解读层分叉的**唯一入口**；任何新增机构类型（Broker-Dealer / Credit Card / Mortgage REIT）都挂到这两个开关下，不新增额外布尔字段
2. **三层分叉架构**（均不修改底层 FinancialStatement 结构）：
   ```
   Layer 1 — 定性 Profile: classification/classifier.py _characterize_profile()
     • Bank/Ins profitability: operating_income 缺失 → 回退 net_margin（银行 operating_income 常缺）
     • Bank/Ins cash_flow: 不用 FCF margin，改用 net_income 正/负 → Profitable/Loss-Making；文案加 caveat
     • Bank/Ins leverage: D/E 阈值 2x/4x → 放宽到 >15x Medium；文案 Well-Capitalized/Adequate/Under-Capitalized
     • Bank/Ins capital_intensity: N/A
     • REIT cash_flow: 文案加 Prefer FFO/AFFO over GAAP FCF

   Layer 2 — 规则引擎 Risk: analysis/risk.py analyze() + 3 子函数签名加 profile=None
     • 顶部 is_fin = getattr(profile, "is_financial_institution", False)；is_reit 同理
     • _leverage(): Bank D/E >15x Medium only；普通保持 2x/4x
     • _margin_risk(): Bank → 直接 return（跳过 neg-FCF 年数计数）；REIT → 证据文案加 caveat
     • _forecast_risk(): Bank → 直接 return（不算 FCF Yield）；REIT → 严重度降一档 (High→Medium) + 加 caveat
     • 末尾 append Severity=None 级信息 flag（不扣分，仅提示读者指标定义差异）

   Layer 3 — 渲染 Reporting: reporting/dashboard.py _market_section(profile=None)
     • build_report() 必须传 profile（首次漏传已修复）
     • is_fin 分支：EV / Net Debt / EV/EBITDA / FCF TTM 四行全加斜体 caveat
     • is_reit 分支：FCF / EV/EBITDA 加 prefer FFO/AFFO 文案
     • 普通公司：完全不变 → 零回归
   ```
3. **签名变更安全模式**：所有函数新增参数 `=None` 默认值 + 防御式 `getattr(profile, "flag", False)`；任何未传 profile 的旧调用（pytest、脚本、第三方集成）行为与修改前 100% 一致

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 非金融公司（AAPL/MSFT/NVDA 等 90% 覆盖）完全零影响 | 新增的机构类型（如 Credit Card / FinTech Lender）需要主动扩展 is_fin 判断条件，不会自动覆盖 |
| 银行指标一致性：三层都走同一开关，不会出现 Profile 说「Profitable」而 Risk 说「Weak FCF」的自相矛盾 | 代码耦合点增多（5 个文件 × 7 个函数），新增机构适配时必须同步改三处，容易漏 → 建议未来加 `@institution_aware` 装饰器统一 |
| SOFI 修复效果立竿见影：risk score 80→95，三个误报 flag 全消 + 新增信息说明 | 底层数据层的 FCF 数值仍然是错误定义（-$9B），仅在上层"忽略/降级/加注释"；如果未来有模块直接读 data 而非走 profile/risk/reporting，仍会踩到坑 → 需文档警示 |
| 向后兼容零风险：pytest 27/27 全过，AAPL 输出与修改前字节级一致（除新增置信度拆解外） | — |
| 估值模型路由不变：仍然 Bank→DDM/RIM、REIT→NAV，Hybrid 仅是"语义层"表达，不影响数学计算 | — |

---

## ADR-009: 混合业务分类采用「单标签 11 类 BusinessType + 多轴暴露度聚合」方案，不新增 FinTech / Hybrid 枚举值
- **Date**: 2026-10-08
- **Status**: ✅ Accepted & Implemented (Session #04 SOFI 修复)

### Context
- SOFI 不是纯传统 Bank：同时包含 Lending / Financial Services / Technology Platform / Deposits / Investing / Personal Finance，在当前 11 类单标签分类下只能输出：
  ```
  Bank 66.6% · Unknown 22.1% · MatureTech 7.0% · Semiconductor 3.5%
  ```
  Top-1/Top-2 ratio = 3.0x 区分度中等，强行判 Bank 100% 会丢失模型给出的「非纯银行」信号
- BusinessType 枚举的直接下游耦合：
  1. `models/router.py` `MODELS_BY_TYPE`：Bank→[Bank, Multiples, P/E, P/B]，SaaS→[DCF, ReverseDCF, Multiples...]，每类对应 3-4 个估值模型权重表；新增一类需同步 4 处权重调参
  2. `classification/classifier.py` 结构覆盖规则 (Structural Overrides)：4 类强规则（int/rev>30%→Bank 等），新增一类需补边界规则
  3. 训练集 labeling_dump.csv：1000 行已标完，扩枚举需重新定义 Hybrid/FinTech 边界并返工标注（可能 ≥200 行边界样本返工）
  4. 训练流程 `ml_classifier.py`：类别数 11→12 需修改所有 n_classes 常量 + SelectKBest k 值可能需重调
- 用户的核心诉求不是「路由到一个新 FinTech 估值模型」，而是「报告能诚实告诉读者这个公司不是纯银行，有科技平台成分，注意边界性」——这是**语义层**需求，不是**估值模型路由层**需求

### Decision
1. **枚举不扩**：`BusinessType` 保持当前 11 类不变（Bank / SaaS / MatureTech / Semiconductor / ConsumerCyclical / REIT / Insurance / Commodity / Utilities / Conglomerate / Unknown）
2. **单标签仍用于路由**：估值模型路由完全不变（SOFI 仍走 Bank 的 DDM/RIM/P/B 等模型）——数学逻辑稳定不折腾
3. **Profile 新增 Hybrid 语义字段**（5 个 + 1 个暴露度数组，均不影响路由）：
   ```python
   is_hybrid_classification: bool = False
   primary_business_type: str | None = None      # "Bank Lending + Deposits"
   secondary_business_type: str | None = None    # "FinTech Platform (Lending-as-a-Service + Investing)"
   hybrid_classification_label: str | None = None  # "Hybrid Financial Institution"
   classification_confidence_level: str | None = None  # "High" / "Medium" / "Low" / "Very Low"
   business_exposures: list[BusinessExposure] = field(default_factory=list)
   ```
4. **11→5 轴概率聚合**（`_build_exposures()` 映射表写死）：
   ```
   Financial axis    ← Bank(1.0) + Insurance(1.0) + REIT(0.7) + Conglomerate(0.2)
   Technology axis   ← SaaS(1.0) + MatureTech(1.0) + Semiconductor(0.8) + Unknown(0.3)
   Cyclical axis     ← ConsumerCyclical(1.0) + Commodity(0.8) + Semiconductor(0.3)
   HardAssets axis   ← REIT(1.0) + Utilities(1.0) + Commodity(1.0)
   Diversified axis  ← Conglomerate(1.0) + Unknown(0.5)
   (每轴 = Σ (class_prob × axis_weight)，归一化到 0~100%)
   ```
5. **三条 Hybrid 触发规则**（满足任一即开启）：
   ```
   (a) FinTech Hybrid:    Financial axis Top-1 (≥50%) AND Technology axis ≥ 8%
        → Label = "Hybrid Financial Institution" · Secondary = "FinTech/Technology Platform"
   (b) Tech-Fin Hybrid:   Technology axis Top-1 (≥50%) AND Financial axis ≥ 8%
        → Label = "Technology Company with Financial Exposure" · Secondary = "Fin/Insurance Segment"
   (c) Generic Low-Separation Hybrid: Top-1 raw prob < 55% AND Top1/Top2 ratio < 3x
        → Label = "Diversified / Multi-Segment Business" · Secondary = "Mixed industry signals"
   ```
6. **报告渲染策略**（仅触发时显示，避免噪声）：
   - Hybrid=True 时显示 Primary Model → Secondary → Classification → Confidence Level
   - 置信度拆解仅当有实际扣减时显示（adjustments 有非 0 delta）
   - Exposures 条形图仅显示 weight≥2% 的轴（<2% 的微小轴隐藏）

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 零模型重训：不需要重新标数据 / 重新跑 LightGBM / 重新调 Optuna | 11→5 轴映射表是硬编码权重，未来可能需要微调（比如 Utilities 是否算 Hard Assets） |
| 零路由改动：估值模型权重表、结构覆盖规则完全不动，数学稳定性 100% 保持 | Hybrid 判定规则 (8% 阈值 / 55% Top1 / 3x ratio) 是拍脑袋经验值，真实边界案例多了之后可能需要重调（可用 Optuna 搜索最佳阈值） |
| SOFI 效果完美：Primary=Bank + Secondary=FinTech Platform + 暴露度三轴(66.6/22.1/7.0)，完全满足用户"不要强行判 Bank 100%"的诉求 | 暴露度聚合是「线性加权」的简化模型，无法捕捉非线性交互（比如 Unknown 22% 部分到底是真 Unknown 还是 FinTech 信号被吸收），仅作"方向提示"不作定量承诺 |
| 向后兼容：AAPL/NVDA/JPM/BAC 等纯类公司 is_hybrid=False，报告完全不显示 Hybrid 区块，视觉无噪声 | — |
| 可扩展：未来加 BrokerDealer / CreditCard / MortgageREIT 等新 BusinessType 只需在映射表加权重，无需改下游逻辑 | — |
| 与估值模型分层解耦：即使未来真的要做「FinTech 专属估值模型」（Lending Book + Tech Revenue SOTP 分部估值），也可以在 router 里按 is_hybrid=True + BusinessType=Bank 的组合条件加分支，不需要动枚举本体 | — |

---

## ADR-010: 直观标签（Intuitive Labels）三层架构 + 「一次 head、多次细节」防重策略 + 主语不自包原则
- **Date**: 2026-10-08
- **Status**: ✅ Accepted & Implemented (Session #05 — bug 双修复后正式化)

### Context
- 用户核心诉求「报告首屏直接给中文结论，不用一行行扫百分比」带来两个结构性挑战：
  1. **首屏 vs 细节重复展示问题**：结论性一句话估值（headline）需要放在最前面让用户 0.5s 扫到；但中位估值对比、情景跨度、公允区间这些支撑性 bullet 又需要在「模型比较章节」跟模型数值结果放在一起方便交叉验证。如果两处都完整展示（headline + details），就会出现「为什么又说一遍一句话估值」的用户抱怨。
  2. **文案组装主语重复问题**：底层 pure-function 计算模块 `_vs_median_label()` 返回完整自包含中文句子「当前价 $15.58 较中位估值 $11.01 高出 +41.6%」（方便未来单独作为一行使用），上层渲染方法如果写 `f"（中位估值 {detail}）"` 就会组装出「中位估值 较中位估值」这种读不通顺的重复主语 bug。
- 这两个问题在 NU (Nu Holdings) demo_fast 实际输出中首次暴露：
  ```
  Bug #1: 中位估值对比：**高估**（中位估值 较中位估值高 +41.6%）← 主语重复
  Bug #2: OVERVIEW 显示「一句话估值结论：🔴 高估」，AGREEMENT 又显示「一句话估值：🔴 高估」← headline 重复（内容字节级相同）
  ```
- 这不是 NU 单例问题，是架构性问题：只要上层渲染模块独立工作、没有统一的分层展示契约，未来任何新 section 想展示直观标签都可能回归这两个 bug。

### Decision
1. **三层架构（数据隔离 + 计算纯函数 + 渲染策略层）**
   ```
   Layer 1 — Data Cards (data/models.py)
     • GrowthVerdictCard / ValuationVerdictCard dataclass
     • 只存结构化标签（headline_label/emoji/headline_summary、median_vs_price_label/        _detail、scenario_summary、reasoning、fair_value_estimate_range）
     • 不存「要不要展示」的策略信息；渲染策略放在上层函数

   Layer 2 — Pure Computation (reporting/verdict_intuition.py)
     • build_growth_verdict(gap) / build_valuation_verdict(agreement, scenarios, ...)
     • 纯函数，零 IO、零副作用；输入原始 analysis 对象，输出 Layer 1 的卡片
     • 所有百分比桶（6 档营收 CAGR、5 档 FCF CAGR、7 档估值偏离、4 档情景跨度）写死在 helper 中，方便单独 pytest

   Layer 3 — Rendering Strategy (reporting/dashboard.py + models.py 方法)
     • header_lines(include_headline=True) + bullet_lines()：**支持分层渲染**
     • 调用方显式声明「我这节要 headline 还是不要」
   ```
2. **「一次 head、多次细节」防重契约（One-Head-Many-Details Contract）**
   - **headline 展示规则**：同一份报告中，headline（一句话估值结论 + emoji + summary）只在 **OVERVIEW 首屏区块** 展示一次，对应 `header_lines(include_headline=True)`
   - **细节展示规则**：其他任何区块（AGREEMENT 模型比较、RISK 风险、VALUATION 估值）想复用直观标签时，必须用 `header_lines(include_headline=False)` 或者 `bullet_lines()`，只能展示支撑性 bullet 细节，不得再复读 headline
   - **语义锚点配合**：不同区块的 section 标题必须语义区分，不能都叫「一句话估值」；细节展开页统一用「估值细节拆解」「增长直观解读」这类明确表达「展开细节」的标题，消除用户"为什么重复"的困惑
3. **主语不自包原则（No-Self-Contained-Subject Re-Wrapping Principle）**
   - **字段命名约定**：返回完整句子的字段命名必须带 `_sentence`、`_detail`、`_full` 后缀（如 `median_vs_price_detail`、`scenario_summary`），表示「这是自包含完整句，外层不要再包主语」
   - **渲染层约束**：任何组装 `f"（X {_detail}）"` 形式前，先肉眼检查 `_detail` 内部是否已经包含 X；拿不准时把字段值打印出来再写代码
   - **Bug 修复模式固化**：本次 NU Bug #1 作为判例写入 ADR，「句子字段 + 外层前缀 = 重复主语 = 架构性 bug」= 优先修改外层去掉前缀，而非修改内层句子字段（否则破坏句子字段在其他地方的自包含性）

### Implementation — 本次 Session #05 对应的落地锚点
| 决策点 | 落地位置 | 代码锚点 |
|--------|---------|---------|
| 三层架构 Layer 1: Data Cards | data/models.py L190-266 | `GrowthVerdictCard`（8 字段）+ `ValuationVerdictCard`（10 字段）定义 |
| 三层架构 Layer 2: Pure Compute | reporting/verdict_intuition.py L22-369 | `_rev_cagr_label` 6 档分桶 · `_fcf_cagr_label` 5 档 · `_vs_median_label` 7 档 + 自包含完整句 · `_scenario_summary` 4 档跨度宽窄 · `build_growth_verdict` + `build_valuation_verdict` 主入口 |
| 三层架构 Layer 3: include_headline | data/models.py L252-265 | `def header_lines(self, *, include_headline: bool = True) -> List[str]` keyword-only 参数 + 首行 `if include_headline and self.headline_summary` 守卫 |
| 一次 head: Overview 首屏 | reporting/dashboard.py L136-161 | `_intuitive_overview_section()` 调用 `v.header_lines()`（默认 include_headline=True）+ `g.bullet_lines()` + 末尾快速参考 disclaimer |
| 多次细节: Agreement 章节 | reporting/dashboard.py L548-555 | `_agreement_section()` 注释 "overview 已放过 headline，这里只展开细节" + 标题改名「🤝 估值细节拆解」 + `v.header_lines(include_headline=False)` |
| 多次细节: Gap 章节增长解读 | reporting/dashboard.py L499-507 | `_gap_section()` 末尾追加「📈 增长直观解读」+ `g.bullet_lines()`（Growth 卡片没有 headline 字段，本来就只有细节） |
| 主语不自包修复 | reporting/verdict_intuition.py L175-207 + data/models.py L256-258 | `_vs_median_label()` 返回自包含中文完整句 sent；`header_lines()` 第 257 行从 `f"（中位估值 {detail}）"` → 改为 `f"（{detail}）"` 去掉前缀 |

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 未来不会再出现类似 NU 的 headline 重复 / 主语重复 bug：任何未来想加直观标签展示的新 section（如 Telegram Inline Keyboard summary、PNG 图表标题、HTML 版本等）都只需按契约选择 include_headline=True/False + 语义标题区分即可 | 需要所有协作 AI Agent 先读本 ADR + AGENT.md Decision 007，否则可能会"好心"在别的 section 再加一遍 headline；建议把本 ADR 链接放在 header_lines() 方法 docstring 中 |
| 计算层 purity 保证：verdict_intuition.py 纯函数可直接 pytest（不需要构造完整 CompanyProfile），未来扩 14 档、21 档分桶、或调整阈值边界不需要改渲染层代码 | 字段命名约定（_detail/_sentence/_full 后缀是自包含句子）是「约定」而非代码级强制，未来新增字段如果命名不规范可能会被误包装；最佳实践：在 dataclass field docstring 中标明「本字段为完整中文句，外层渲染请勿重复添加主语」 |
| 向后兼容 100%：include_headline 默认 True，旧调用无需修改；grep 确认现有 2 处调用都已正确区分（overview=True / agreement=False） | Gap 章节「增长直观解读」与 Overview 中的增长 bullet 目前是字节级重复（都是整体判断 + 历史 + 预测 vs 历史 + 隐含），属于有意设计（交叉验证方便），但未来用户如果反馈太冗余可把 Gap 章节改为 `bullet_lines_details_only()` 新方法，去掉 overall_growth_summary 第一行——但本次不作为必须修复 |
| ADR 直接成为 pytest/回归测试 checklist：未来跑 demo_fast 时只需扫首屏 + Agreement 标题 + 中位对比句主语，3 秒即可判断是否回归 | — |
| 新增文件 reporting/verdict_intuition.py 的职责边界清晰：只管"数字→中文标签"映射，不管报告格式——未来可独立做 "标签正确性 unit test"（比如 gap.historical_cagr=0.55 → 必须返回「爆发式增长 (>40%)」）无需构造整个 dashboard | — |

---

## ADR-011: 数据对账层「只读探测」+（Session #10 修订）「白名单写侧反向校验 + 审计链」
- **Date**: 2026-10-27（Session #06 初版）→ 2026-11-03（Session #10 修订）
- **Status**: ✅ Accepted & Implemented（**已修订**：由「纯只读」升级为「只读探测 + 白名单写侧 + 审计链」双模）

### Context
- NBIS 实测报告暴露：供应商单点字段可静默失真且用户无法察觉——
  - trailing P/E 供应商给 671，但内部推算 price ÷ TTM EPS = 153.27 ÷ 0.117 ≈ 1307（差近 2x）
  - 市值口径股数 361.5M vs 公司最新年度股数 253.0M（差 +42.9%）
  - 年度口径 EBITDA 与 TTM 口径 EBITDA 混用 → EV/EBITDA 供应商 104.27 vs 内部 40.76（+155.8%）
- 这些偏差会直接污染估值倍数（P/E、EV/EBITDA、EV/Sales），而报告此前完全没有一致性检查。
- **Session #10 复查发现初版「只标记不修正」的缺口**：对账虽渲染了警告，但下游估值仍读取被污染的供应商基数 → 警告形同虚设。用户明确要求：「当偏差 >25% 时自动改用内部推算值并标注，而非仅渲染警告」。

### Decision
1. **保留 `reconcile(data) -> ReconciliationReport` 纯只读探测**，做 10 项交叉校验：
   `market_cap≈price×shares` / `EV≈mcap+debt−cash` / `TTM EPS≈NI/shares` / `trailing P/E≈price÷EPS` / `EV/EBITDA≈EV÷EBITDA` / `P/B≈price÷BVPS` / `EV/Sales≈EV÷revenue` / `TTM FCF≈OCF+capex` / `market shares≈年度 shares` / `EBITDA/营收 ≤ 100%`
2. **容差分级**：会计恒等式 5%（`_TOL_IDENTITY`，按构造必须成立）；供应商口径差异 20%（`_TOL_PROVIDER`，年度 vs TTM、稀释 vs 基本股数合法偏离）；股数 25%（`_TOL_SHARES`）
3. **（Session #10 新增）写侧反向校验 `apply_overrides()`**：
   - 当某字段偏差 > `_OVERRIDE_TOLERANCE`(25%) 时，按 `_OVERRIDE_FIELDS` **白名单**自动改用内部推算值，写入 `OverrideRecord`（field/provider_value/internal_value/rel_diff/unit/reason/applied）
   - **股数守卫**：若股数偏差 >25% 但市值恒等式（mcap≈price×shares）自洽 → 仅标注不覆盖；若恒等式被破坏 → 按市值/价格反推
   - `OverrideLog` 全量审计链（`records` + `n_applied` + `to_lines`）；`data/validator.py::_check_reconciliation()` 接入并挂到 `FinancialData.reconciliation_overrides`
4. **修正必须可渲染**：`reporting/dashboard.py::_data_section()` 渲染「🩹 对账自动修正（偏差 > 25% 时改用内部推算值）」，逐条给出「原供应商值 → 内部推算值」对照
5. **原则固化**：写回必须**白名单 + 审计 + 可渲染**三件套，绝不静默改写；超出白名单的偏差仍只标记不修正

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 供应商单点失真不再静默传播到估值倍数（下游读到的是内部推算值，非污染值）| 写侧引入「自动修改数据」的能力，若白名单过宽会误改合法口径差异 → 用 25% 阈值 + 白名单 + 审计链约束 |
| 用户可见「原值 → 修正值」对照，修正可追溯、可复核 | 需额外维护 10 项校验逻辑与 override 白名单；供应商字段口径变化时容差要复评 |
| 股数守卫避免「恒等式自洽却强行改股数」的过度修正 | 仍会对部分「合法口径差异」产生噪音（如年度 vs TTM EBITDA）—— 属「暴露不确定」优于「伪精确」的设计取舍 |
| 只读探测与写侧解耦：`reconcile()` 无副作用，`apply_overrides()` 显式调用，可分别测试 | — |

---

## ADR-012: Peer 倍数按「经济结构」而非「粗粒度行业标签」路由；重资本算力业务强制改道 AI/Cloud Infrastructure
- **Date**: 2026-10-27
- **Status**: ✅ Accepted & Implemented (Session #06)

### Context
- NBIS 报告把 P/E / EV-EBITDA / EV-Sales 全部路由到粗桶 `"SaaS → Technology"`（P/E 22 / EV-EBITDA 14 / EV-Sales 4）。
- 但 NBIS 是 AI 云 / GPU 基础设施 / 算力租赁：capex/revenue ≈ 822%、负 FCF（-$6B）、高增长（历史 CAGR 239.8%）—— 重资本、负 FCF、高增长，与资产轻 SaaS 的经济结构完全相反。
- 用 SaaS 的 P/E 22 + EV/Sales 4 会严重扭曲估值（报告给出 EV/Sales $11.41 vs 重路由后 $26.41）。
- 用户明确："NBIS 更接近 AI 云/GPU 基础设施/算力租赁……不是典型 SaaS。"

### Decision
1. **技术族 peer 桶按经济结构细拆**：`Software - SaaS` / `Software - Mature` / `Semiconductors` / **`AI/Cloud Infrastructure`**（新增）；不再有聚合的 `"Technology"` 粗桶参与技术族路由
2. **AI/Cloud Infrastructure 倍数**：P/E 35 / EV/EBITDA 18 / EV/Sales 8 / P/B 7 / FCF Yield 0.015（重资本 → EV 口径为主，净利口径倍率抬升）
3. **自动重路由 `_compute_infra_override()`**：四条件同时满足才改写路由——
   - `capital_intensity == "Very Capital Intensive"`（capex/revenue ≥ 0.20 起，NBIS ≈ 8.22）
   - `growth_profile ∈ {High Growth, Moderate Growth}`
   - `cash_flow_profile` 含 weak/neg
   - `|TTM capex| / TTM revenue ≥ 1.0`（`_COMPUTE_INFRA_CAPEX_RATIO`，capex 超过自身营收 = 明确算力建设期）
4. 命中后把技术族键重路由到 `"AI/Cloud Infrastructure"`，source 串显式标注重路由原因 + `(APPROXIMATE)`，保证可审计
5. **倍数结构守卫**（与 ADR-011 互补）：隐含 P/E > 100x → P/E `not meaningful`；EBITDA/营收 > 90% (D&A 主导) → EV/EBITDA `not directly comparable`

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 重资本算力/数据中心标的不再被资产轻 SaaS 倍数扭曲 | AI/Cloud 桶的倍数是行业经验值，仍需后续用真实算力标的（CRWV/CORZ/IREN）校准 |
| 判定条件基于可审计财务指标（capex ratio + FCF 符号），非硬编码 ticker 名单 | 边界情形（capex ratio 恰在 1.0 附近）会翻转路由，已在 source 串标注 APPROXIMATE 提示 |
| 向后兼容：SOFI(Bank) / AAPL(MatureTech) 路由与倍数输出完全不变 | — |

---

## ADR-013: 分类置信度必须反映「标签 vs 财务原型」冲突，并显式向估值确定性传导
- **Date**: 2026-10-27
- **Status**: ✅ Accepted & Implemented (Session #06)

### Context
- NBIS 的 ML Top-1 = SaaS 92%（基于 15 个数值特征的效果），但 `sector`/`industry` 缺失触发置信度 cap 到 55%。
- 该 55% 只反映「数据缺失」，完全没有捕捉到更强的信号：**标签与财务原型根本矛盾**（SaaS 应当资产轻、正 FCF；NBIS 重资本、负 FCF）。
- 用户偏好（user_profile）："分类不确定性必须向估值确定性传导，反对在基础数据不确定时给出伪精确的结果。"

### Decision
1. `classification/ml_classifier.py` 新增常量 `ASSET_LIGHT_CONFLICT_CAPEX_RATIO = 1.0` + `ASSET_LIGHT_TYPES = {SaaS, MatureTech, Media}`
2. 当 ML 判为资产轻类型 且 `capex/revenue ≥ 1.0` 且 TTM FCF < 0 时，触发 `"Asset-light prototype conflict"` 扣减：置信度 `cap 50%`
3. 该扣减必须写入 `ConfidenceAdjustment` 审计链（step_name + delta + reason）+ `reasons`，保证透明可审计
4. 原则固化：**任何「标签 ≠ 财务原型」的矛盾都必须在置信度上体现，而非静默采信标签**

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 重资本算力业务不再被静默当作资产轻 SaaS 走估值/风险模板 | 扣减阈值（capex ratio 1.0）为经验值，未来需结合更多样本校准 |
| 与 ADR-012 联手形成「分类降权 → peer 改道」的一致信号链：分类不确信时估值也降级为 APPROXIMATE | 连续命中多个扣减（缺失 cap + 原型冲突）会使置信度快速下探，属预期行为 |
| 透明：NBIS 审计链 `92.0% → -37.0%(缺失) → -5.0%(原型冲突) → 50.0%` 用户可完整追溯 | — |

---

## ADR-014: 一致性必须做「覆盖率门控」——低覆盖率绝不允许输出强一致性
- **Date**: 2026-10-27
- **Status**: ✅ Accepted & Implemented (Session #07)

### Context
- NBIS 第二版报告：适用模型 6 / 已解算 2 / 4 个失败 / 1 个 APPROXIMATE，却输出「一致性 **Very Strong**」+「显著高估」强结论。
- 这是典型的**幸存者偏差 / 剔除偏差**：剔除 4 个失败或不适用模型后，仅剩两个恰好接近的模型，离散度被人为压小 → "依据更少、结论更自信"。
- 两个幸存模型（TV/EV=536% 的 DCF + APPROXIMATE 的 EV/Sales）共享同一组不稳定的营收/股数/净债务基数，并不独立；它们接近不能证明估值可靠。

### Decision
1. **模型三桶分类**（`analysis/model_agreement.py`）：solved / not_applicable（INSUFFICIENT_DATA：EPS≈0 的 P/E、D&A 异常的 EV/EBITDA）/ failed（NO_SOLUTION_IN_RANGE / INFEASIBLE）
2. **门控一致性**：`gated_cv = base_cv × 覆盖因子 ÷ 质量因子`
   - 覆盖因子 = `sqrt(applicable / solved)` clamp [1.0, 2.0]（覆盖率越低，惩罚越大）
   - 质量因子：SOLVED=1.0、APPROXIMATE=0.5、分类置信度<0.55 再×0.5、TV/EV>0.80 的 DCF 再×0.5
3. **硬覆盖率封顶** `_COVERAGE_CAP`：solved≤1→Very Weak、==2→Weak、==3→Moderate、≥4 不封顶（只降不升）
4. 报告显式展示：模型分桶 / 质量因子·覆盖因子·门控 CV·原始一致性 / 不适用模型清单 / 失败模型清单

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 低覆盖不再伪装成强一致性（NBIS 由 Very Strong → **Weak**） | 门控系数（sqrt/clamp/0.5）为经验值，需后续用更多样本校准 |
| 区分"模型失败"与"模型不适用"，避免用 6 做分母的伪精确 | 覆盖率封顶会普遍下调单模型/双模型标的的一致性，属预期行为 |
| 原则固化：一致性是对"证据充分"的陈述，不是对"幸存样本互相接近"的陈述 | — |

---

## ADR-015: 中位估值改为「质量加权中位数」，并显式区分「源数据质量」与「估值可用性」
- **Date**: 2026-10-27
- **Status**: ✅ Accepted & Implemented (Session #07)

### Context
- 第二版中位 $26.88 ≈ ($26.41 + $27.35)/2，把两个低质量模型（TV/EV=536% 的 DCF + 分类置信度 50% 的 APPROXIMATE EV/Sales）**等权平均**，伪装成"公允价"。
- 对账层已发现：股数 361.5M vs 253.0M 偏差 +42.9%、trailing P/E 671 vs 1307、EV/EBITDA 104 vs 41 —— 每股估值基数本身不可用。
- 原「数据质量评分 83/100」无法反映这些对账不一致，容易误导。

### Decision
1. **质量加权中位数**：权重体系（SOLVED=1.0 / APPROXIMATE=0.5 / TV/EV>80% 的 DCF 再×0.5 / 分类置信度<55% 的倍数再×0.5）驱动 `median_value_weighted`；报告展示每个模型权重 + 降权/剔除原因
2. **估值可用性评分**（与源数据质量分离）：`data/validator.py::_valuation_usability()` 随对账不一致项扣分（每项 -6，上限 -30）+ per-share 基数不可靠 -20 + EBITDA 口径异常 -5；`data/models.py` 新增 `usability_label()`；报告分「源数据质量」「估值可用性」两行（NBIS 83/100 vs 34/100）
3. **per-share 基数门控**：`per_share_basis_unreliable()`（三键：流通股数/市值/TTM EPS）命中 → 抑制每股公允值，标签改为"⚠️ 每股估值基数不可靠…仅方向性参考"
4. 中位值标签明确为「低置信模型集成值」性质，不称"公允估值"

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 低质量模型不再等权污染中位值 | 权重系数为经验值，需真实算力/低覆盖样本扩样校准 |
| 用户能一眼看到"可用性 34/100 (Critical)"而非被 83/100 误导 | 股数不可靠时抑制每股值，可能对某些数据源较差的正常公司偏保守 |
| 原则固化：当唯一证据是低质量证据时，输出"低置信参考"而非伪精确数字 | — |

---

## ADR-016: 估值结论改用「概率语言」——P(内在>价格)/P(高估>30%)/P(股权归零)
- **Date**: 2026-10-27
- **Status**: ✅ Accepted & Implemented (Session #07)

### Context
- 第二版蒙特卡洛中位 $32.47、P99 $164.30，当前价 $153.27 落在 MC 的 P98–P99 —— 这本身是"高估概率极高"的**更稳健**信号，却被单点"中位 $26.88"淹没。
- 两套分布口径不一致：MC 未反映"只有 2 个模型、1 个 APPROXIMATE"的低覆盖问题；且各驱动因子独立乱抽，未建模相关性。

### Decision
1. `simulation/monte_carlo.py` 输出三个概率结论并在报告渲染：`prob_above_price`（P(内在价值 > 当前价)）、`prob_overvalued_30`（P(高估 > 30%)）、`prob_equity_zero`（P(股权价值 ≤ 0)）
2. **相关性建模**：4×4 驱动因子（revenue cagr / operating margin / WACC / terminal g）用 Cholesky 分解（`_correlation_cholesky()`，失败时 eigh 修正 PSD）做相关抽样，不再独立乱抽；Gordon 稳定约束 `tg = min(tg, wacc - 0.005)`
3. **负值处理**：负每股价值 floor 到 0 并计入 `prob_equity_zero`（不再丢弃尾部）
4. 原则固化：当分布尾部信息比中位数更稳健时，用概率说话比用单点说话更诚实

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| NBIS 直接给出"P(高估>30%)=97.5%、P(内在>价)=0.3%"，比单点更诚实 | 相关矩阵为经验设定，需用历史驱动因子协方差校准 |
| 负价值不再被丢弃，归零概率（6.7%）被显式暴露 | MC 与模型集成的口径仍需后续进一步统一（见 TODO L-09） |
| 与 ADR-014/015 形成一致的"低置信 → 概率语言"叙事 | — |

---

## ADR-017: 重资本高增长/亏损期标的引入 Replacement-cost NAV 作为覆盖率锚，而非靠降权规避
- **Date**: 2026-11-03
- **Status**: ✅ Accepted & Implemented (Session #10)

### Context
- 用户指出覆盖率是当前**最大短板**：NBIS 只有 **2/3 模型解算**——DCF 因负 FCF 近乎失效、P/E 1205x 不适用、EV/EBITDA 被 D&A 拉爆。
- 既有对策是「降权」（ADR-014/015），但降权只改变「谁主导结论」，**不增加证据数量**：2 个幸存模型无论怎么加权都无法让结论更可靠。
- 用户建议引入**适配资产结构**的模型族——EV/Sales + 单位经济学 或 Replacement-cost NAV（算力资产重估），让覆盖率从 2/3 提升到 3-4/5。

### Decision
1. **新建 `models/replacement_nav.py`**（`ReplacementNAVModel`）：
   - 资产基础锚：`net_ppe = Σcapex − ΣD&A`（累计资本投入减去已折旧部分 = 现存在营资产）
   - 有账面权益时：`equity = book_equity + net_ppe × (factor − 1)`；否则 `equity = replacement_ppe − net_debt`
   - `factor` 默认 `DEFAULT_REPLACEMENT_FACTOR = 1.15`（在建/估值重估溢价），附 5 档敏感性 `(1.00, 1.10, 1.15, 1.25, 1.40)`
2. **`config.py` 新增 `ModelName.REPLACEMENT_NAV`**；`models/router.py` / `models/__init__.py` 注册（`NAME_TO_MODEL`）
3. **分类器动态入桶**：`classification/classifier.py::_is_replacement_nav_candidate()` —— 排除金融/REIT；要求 shares；要求 `capex/revenue ≥ MIN_CAPEX_RATIO(0.30)`；要求 `net_ppe > 0`；要求「负 FCF 或亏损或 High Growth」；命中则强制把 `Replacement NAV` 追加进 applicable
4. **原则固化**：覆盖率不足首选「引入适配资产结构的模型族」，其次才是调权重

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| NBIS 覆盖率 **2/3 → 5/6**（Replacement NAV 给出独立资产基础锚 $11.13） | `factor` 1.15 为经验值，需用真实算力/数据中心标的（CRWV/IREN）校准 |
| 资产基础锚与 DCF/倍数法**证据来源独立**，不与 FCF 假设共线 | `net_ppe = Σcapex − ΣD&A` 对会计口径（含租赁/在建工程）敏感，年报数据缺失时会退化 |
| 入桶条件基于可审计财务指标（capex ratio + FCF 符号 + net_ppe 符号），非 ticker 名单 | 边界情形（capex ratio 恰在 0.30）会翻转是否入桶 |
| 向后兼容：AAPL/JPM/PLD/AMT/XOM 的 applicable 集合不变 | — |

---

## ADR-018: 递归自我改进工程化为「golden report diff」——把上一轮报告→缺陷清单变成可断言回归
- **Date**: 2026-11-03
- **Status**: ✅ Accepted & Implemented (Session #10)

### Context
- Session #07/08/09 的递归自我改进靠「人工读渲染报告 → 找自相矛盾 → 修代码」推进，存在两个问题：
  1. **不可扩展**：每轮都要人工通读上万字报告；
  2. **无法检测新引入的矛盾**：下一轮改动若引入新的自相矛盾（如覆盖恒等式被破坏），人工不一定会发现。
- 用户要求：「把『上一轮报告 → 缺陷清单』的比对做成可断言的回归测试（golden report diff），下次改进能自动化检测是否引入了新的自相矛盾」。

### Decision
1. **提取稳定决策信号指纹**（`tests/golden_report.py::build_fingerprint()`，19 字段）——**不 diff 渲染文本**（含时间戳/provenance 会每次漂移）：
   `business_type` / `applicable_models` / 分桶计数（`n_total`/`n_applicable`/`n_solved`/`n_failed`/`n_not_applicable`/`n_display_only`）/ `agreement_level` / `median_value`(+`_weighted`) / `beta_effective`(+`origin`) / `recon_checks`/`recon_mismatches`/`override_applied` / `risk_score`/`risk_severity`/`risk_types`
2. **声明式 invariant 检查**（`check_invariants()` 返回自相矛盾清单）：
   (a) 覆盖恒等式 `applicable == solved + failed`；(b) `agreement_level` 不得超过覆盖率封顶；(c) 中位值不得为负；(d) β 在 WACC breakdown / 风险旗标 / 有效值三处一致；(e) 每个 `applied` override 必须实际生效
3. **整篮基线 diff**：`BASKET` 9 只（AAPL/MSFT/NVDA/JPM/PLD/NOW/NBIS/AMT/XOM）指纹存入 `tests/golden/report_fingerprints.json`；`tests/test_golden_report.py` 逐字段 diff，`UPDATE_GOLDEN=1` 刷新基线
4. **原则固化**：自改进的验收必须是**可断言的产物**（指纹 + invariant + 基线 diff），而非人工读报告

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 任何行为漂移（模型集合/分桶/一致性/中位/β/override/风险）都会被逐字段 diff 捕捉 | 指纹字段是「决策信号子集」，非全报告；纯文案改动不会被捕捉（属有意取舍） |
| 5 类 invariant 可直接暴露新引入的自相矛盾 | 每次**有意**的方法论变更都要 `UPDATE_GOLDEN=1` 刷新基线，否则测试失败 |
| 整篮 9 只覆盖不同资产结构，单次运行即可回归全画像 | 运行时间为整篮 pipeline（离线合成数据，秒级） |
| 把「上一轮报告 → 缺陷清单」从人工流程变为 CI 可跑断言 | 指纹维护需随新增决策字段同步 |

---

## ADR-019: Beta 全链路统一为单一 `resolve_effective_beta()` 出口
- **Date**: 2026-11-03
- **Status**: ✅ Accepted & Implemented (Session #10)

### Context
- 用户指出：「市场区 / 风险旗标 / WACC 三处目前仍各读不同的 β 口径，建议统一为单一 `WaccBreakdown.beta` 出口，消除重复口径。」
- Session #09 已暴露该矛盾的表征（市场区展示原始 β=−0.09，WACC 区展示截断 β=0.30），但当时仅追加展示标注，未从**解析层**收敛口径。

### Decision
1. `valuation/wacc.py::resolve_effective_beta(data, dcf_breakdown)` 成为**唯一 β 出口**，按优先级解析并返回带 `origin` 的可审计对象：
   `wacc_breakdown`（CAPM winsorized）→ `provider`（供应商回归 β winsorized 到 `[BETA_WINSOR_LO, BETA_WINSOR_HI]`）→ `fallback`（unlevered β）
2. 市场区 / WACC 明细 / 风险旗标三处**共用同一解析结果**，不再各自读原始 β
3. golden `check_invariants()` 断言「β 在 WACC breakdown / 风险旗标 / 有效值三处一致」
4. **原则固化**：同一指标在多处展示时，必须来自**同一解析函数**（而非各处复制口径）

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 消除「同一 β 两处显示不同值」的用户困惑 | 展示层不再能单独使用「原始 β」做旁注 → 需以 `origin`/透明化注释表达原始值 |
| `origin` 字段使 β 来源可审计（wacc_breakdown/provider/fallback） | 解析优先级为固定策略，未来若要改「优先 provider」需集中改一处 |
| golden invariant 使其成为可断言的回归项 | — |

---

## ADR-020: 重资本高增长/亏损期标的补第二条腿——EV/Sales + 单位经济学（earnings-power 锚），并诚实固定为 APPROXIMATE
- **Date**: 2026-11-03
- **Status**: ✅ Accepted & Implemented (Session #11)

### Context
- 用户要求：「给重资本高增长/亏损期标的引入 Finance 专属模型族——如 EV/Sales + 单位经济学（GPU 稼动率×ARPU）或 Replacement-cost NAV（算力资产重估），让覆盖率从 2/3 提升到 3-4/5，而不是靠降权规避。」
- Session #10 已用 Replacement NAV（ADR-017）补齐**资产基础锚**（"重建这套算力设备要多少钱"，清算/重置视角），NBIS 覆盖率 2/3 → 5/6。
- 但资产锚回答不了"这些资产装好之后按其成熟单价能挣多少"——对重资本建设期标的（NBIS），资产重估与 earnings-power 会系统性分叉；仅有资产锚使结论偏向清算视角，证据仍单腿。

### Decision
1. 新建 `models/unit_economics.py::UnitEconomicsSalesModel`，补上经济含义**正交**的 earnings-power 锚：
   - `deployed_capital = Σcapex − ΣD&A`（已投入净算力资本）
   - `capacity_revenue = max(TTM营收, deployed_capital × BENCHMARK_REVENUE_YIELD)`（把未投产/低利用率算力按成熟数据中心「营收/净PP&E=35%」基准折算为**产能口径营收**）
   - `EV = capacity_revenue × MATURE_EV_SALES × ramp_discount`
   - `utilisation_gap = clamp(1 − current_yield/benchmark_yield, 0, 1)`；`ramp_discount = (1+WACC)^−(RAMP_YEARS × utilisation_gap)`
   - 参数 `BENCHMARK_REVENUE_YIELD=0.35` / `MATURE_EV_SALES=4.0` / `RAMP_YEARS=3.0` + 敏感性（yield 0.25/0.35/0.50 × ramp 2/3/5）
2. `config.py` 新增 `ModelName.UNIT_ECON_SALES`；`models/router.py` / `models/__init__.py` 注册。
3. `classification/classifier.py`：`ALL_MODELS` 扩列 + `_model_applicability()` 动态入桶 + 新增 `_is_unit_economics_candidate()`（排除金融/REIT；`capex/revenue ≥ MIN_CAPEX_RATIO(0.50)` + 负 FCF 或亏损；`Σcapex − ΣD&A > 0`）。
4. **诚实性硬约束**：数据层无 GPU 稼动率/ARPU 明细字段，模型以「营收/净PP&E 相对成熟基准」为**派生代理**，故**固定返回 `SolverStatus.APPROXIMATE`（永不 SOLVED）**，并在 notes 标注「派生代理 / 方向性参考」。
5. **原则固化**：覆盖率不足应通过引入**经济含义独立、口径诚实**的模型族解决；第二条腿必须与第一条腿经济学正交，而非同一逻辑换个名字。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| NBIS 覆盖率 5/6 → **6/7**（第二条腿与资产锚正交，真正增加证据量） | 模型基于派生代理（无明细稼动率字段），固定 APPROXIMATE、精度受限 |
| 资产视角 + earnings-power 视角并置，避免结论偏向清算 | 新增居中模型抬高 IQR 上界 → 原被过滤的极端 DCF 重回样本 → 一致性如实降为 Very Weak（真实信号，非缺陷） |
| 敏感性（yield × ramp）暴露关键假设，方向可验证 | 参数（35% yield / 4.0x EV-Sales）为行业基准，需随数据源接入迭代校准 |
| **不靠降权规避**，符合用户「引入适配模型族」的明确要求 | — |

---

## ADR-021: 递归改进统一原则——矛盾要命名不要掩盖 / 口径要同基不要混用 / 派生量要结构化不要埋在注释
- **Date**: 2026-11-03
- **Status**: ✅ Accepted & Implemented (Session #12)

### Context
- 用户要求：以 **CRWV（CoreWeave，AI/Cloud neocloud 建设期）** 为标的做「递归自我改进」——上一轮产出作为下一轮起点，进行 **3 轮**迭代。
- 3 轮分别暴露了同一类系统性失效的三种形态：**报告内部存在两个互斥/矛盾的陈述却不点名**。
  - Round 1：报告头 `MatureTech / SaaS` 与 peer 区 `AI/Cloud Infrastructure` 互相矛盾（同一判定只在 ML 路径实现，确定性规则路径漏实现）。
  - Round 2：一句话结论中「中位口径显著高估（$6.87）」与「DCF 基准情景 $138.57 反判低估」方向相反，未命名。
  - Round 3：`ReverseDCF` 的成熟稳态推导隐含营收 CAGR ≈26% 只写在 free-text note，结构化字段 `implied_revenue_cagr` 却显示 `N/A`。

### Decision
1. **矛盾要命名不要掩盖**：当同一报告内两个口径给出方向相反的结论（如中位 vs DCF 基准情景），必须**显式命名冲突（⚠️ 口径冲突：…）+ 归因（如 DCF 终值主导/已被降权或 IQR 剔除）+ 声明不做平均**；**严禁用平均制造一个两个口径都不支持的伪共识**。
2. **口径要同基不要混用**：任何百分比措辞必须与基期严格一致——`(base−price)/base` 是 base-relative、`(base−price)/price` 才是 price-relative；混用会让「修复」本身引入数字错误（本轮 Round 2 自持 bug 即为反例，已当场修正）。
3. **派生量要结构化不要埋在注释**：引擎已推导出的量必须落**结构化字段**并携带 `*_source` 来源标记（如 `implied_revenue_cagr` + `implied_revenue_cagr_source="normalized_growth_solve"`）；派生/近似量必须在展示层标注 `APPROXIMATE`，杜绝「字段 N/A 但正文有值」。
4. **跨层判定必须两条路径镜像**：`classification/classifier.py`（确定性规则，离线/golden 走这条）与 `classification/ml_classifier.py` 中「资产轻原型冲突 → AI/Cloud 重路由」逻辑必须保持一致（Round 1 根因即两路径不一致）。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| CRWV 报告从「头/peer 自相矛盾」→ 头行显式 `→ 估值原型重路由: AI/Cloud Infrastructure` | 冲突被命名而非消除，报告会同时出现两个方向性判断（这是**诚实**的代价，读者需自行判断） |
| 结论口径冲突被点名并归因，读者不会被单一口径误导 | 需要额外人工通读报告才能发现「渲染层」矛盾（`check_invariants()` 只覆盖声明式不变式） |
| 派生量落结构化字段，`隐含营收 CAGR` 与 note 一致（26.4%） | 派生态标注 APPROXIMATE，读者须理解其为推导而非直接求解 |
| 形成可复用的递归改进原则（矛盾/口径/结构化三条） | — |

---

## ADR-022: 金融机构的三档情景必须由适配主模型（Bank RIM）生成，禁用 DCF 口径
- **Date**: 2026-11-03
- **Status**: ✅ Accepted & Implemented (Session #13)

### Context
- 用户在 **SOFI（银行 / 金融科技）** 上做「递归自我改进」第 2 轮时暴露：报告主模型区已正确路由到 **Bank RIM**（残差收益，$9.52），但**情景分析区仍走 DCF 口径**（WACC 15.1%，$12.61~15.94）。
- 两个口径方向相反（主模型判明显高估、情景判接近当前价）却**未命名**，读者会读到自相矛盾的两组数；`sensitivity` 区的 WACC×g 矩阵同理（对借贷业务无经济含义）。
- 根因：`ScenarioAnalyzer.run_all()` 对所有标的统一走 DCF；金融机构的 `is_financial_institution` 开关（ADR-008）只在 profile/risk/reporting 三层生效，未覆盖 scenario/sensitivity。

### Decision
1. `ScenarioAnalyzer.run_all()` 增加金融分叉：`is_financial_institution=True` → 走 `_run_financial_scenarios()`，用**适配主模型 Bank RIM** 生成 Bear/Base/Bull，沿 `ke` 变动（`_FIN_BETA_STEP=0.30`，β∈[0.30, 2.50]），**不使用 DCF**。
2. 情景结果必须携带 `discount_label`（金融为 `"ke"`，非金融为 `"WACC"`）供展示层按口径渲染（`— ke 15.4% (Bank RIM)` vs `— WACC x% / g y%`）。
3. 金融机构的 `sensitivity` 区直接返回「不适用 DCF 敏感性矩阵」说明文案，不渲染 WACC×g 矩阵。
4. **口径要同基**：主模型、情景、敏感性、peer 倍数四处必须同属金融适配口径，任一出现 DCF 残留即视为缺陷（递归每轮须重读产出核对此项）。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| SOFI 情景与主模型同基：$9.26 / $9.52 / $9.79（跨度 22% → **6% SV**），方向与中位锚点一致 | 金融情景不再体现「经营情景」差异，只体现折现率（ke）敏感度——但这正是借贷业务的正确风险轴 |
| 消除「主模型 vs 情景」方向矛盾，读者不再被两套口径误导 | 若银行真正需要经营情景（净息差/拨备）需另建金融专属驱动因子（未来项） |
| JPM（银行）回归验证情景亦走 Bank RIM（$135.28 / $139.22 / $143.36） | — |

---

## ADR-023: 置信度「封顶到边界值」必须用 `<=` 守卫（下界常量），严禁严格 `<`
- **Date**: 2026-11-03
- **Status**: ✅ Accepted & Implemented (Session #13)

### Context
- SOFI 递归第 3 轮暴露：分类器在 `sector/industry` 缺失时把置信度**封顶到恰好 0.55**（`confidence = min(confidence, 0.55)`，`classification/classifier.py:509`）。
- `models/multiples.py` 的 peer 倍数「未充分验证」守卫却写作严格 `conf < 0.55` → **恰好等于 0.55 的封顶情形被漏检**，导致 P/E、P/B 把 55% 置信的银行 peer 倍数当作**完全已验证**（应标 `NOT FULLY VALIDATED` / APPROXIMATE）。

### Decision
1. 阈值提为模块常量 `_PEER_MULTIPLE_CONF_FLOOR = 0.55`，守卫条件改为 `conf <= _PEER_MULTIPLE_CONF_FLOOR`（两处：`multiple_unvalidated` 判定 + notes 标注）。
2. **凡「封顶到边界值」的语义，判定端一律用闭区间（`<=` / `>=`）**：上游是 `min(x, C)` / `max(x, C)` 时，`x` 会精确落在 `C` 上，严格比较必然漏检；并与常量引用配对（展示端复用同一常量，避免魔数散落）。
3. 边界漏检修复后，下游指标要**如实响应**：SOFI 质量因子 1.00 → 0.67、一致性 Moderate → **Weak**、门控 CV 24.5% → 36.7%——这是真实信号，**不做调参规避**（与 Decision 018 一致）。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 55% 封顶置信的 peer 倍数被正确标为未充分验证，估值确定性如实下降 | 更多标的会从「已验证」降级为「近似」——这是诚实的代价 |
| 建立「封顶到边界值 → 用闭区间判定」的通用模式，杜绝同类漏检 | 需审计代码中所有 `min/max` 封顶点，核对对应守卫的比较符（本次仅发现 peer 倍数一处） |
| SOFI P/E、P/B 现均携带警告与 `Classification confidence = 55%` 溯源 | — |

---

## ADR-024: 口径必须作为引擎输出的枚举契约，渲染层禁止猜口径
- **Date**: 2026-11-03
- **Status**: ✅ Accepted & Implemented (Session #14)

### Context
- 「某指标对某类标的有无意义」这类判断，过去散落在展示层（如 `reporting/dashboard.py` 内联 `if profile.is_financial_institution: EV/EBITDA 显示 N/M`）。同一口径要在多处（市场区 / TTM 概览 / 敏感性 / 情景 / peer 倍数）重复判断，任一处遗漏或写法不一，就会出现「主模型说 A、情景说 B」的自相矛盾（Session #13 Round 2 即为实例，只能人工通读才发现）。
- 用户明确要求：**凡「该指标对某类标的有/无意义」都由引擎输出一个枚举，展示层只按契约分支，禁止在渲染层猜口径。**

### Decision
1. 新建**口径契约模块** `valuation/caliber.py`（唯一真相来源）：
   - `MetricMeaning`：`MEANINGFUL` / `REFERENCE_ONLY`（如 REIT 的 FCF → 仅供参考，以 FFO 为准）/ `NOT_MEANINGFUL`（如银行的 FCF/EV/净债务 → N/M）。
   - `DiscountCaliber`：`WACC` / `COST_OF_EQUITY`(`ke`)。
   - `CaliberContract`：携带 `archetype` / `discount` / `metrics` / `notes` / `sensitivity_applicable`；由 `build_caliber_contract(profile)` 依 `is_financial_institution` / `is_reit` 单一分叉构造。
2. **展示层只消费契约**：`dashboard.py` 删除内联 `is_fin`/`is_reit` 判断，改为 `contract.is_meaningful("EV_EBITDA")` / `contract.metric_note("FCF")` / `contract.sensitivity_applicable` 分支。N/M、附注、敏感性是否适用全部来自契约。
3. **口径进入指纹与不变式**：golden 指纹新增 `caliber` / `scenario_calibers`；`check_invariants()` 新增 invariant #6——情景 `discount_label` 必须等于引擎口径，否则报 `main model / scenario disagreement`（把「渲染层口径冲突」从人工通读升级为自动化断言，回应 M-12）。
4. 新增口径的判定逻辑改动，**必须同时更新契约与其断言**，不得回流到渲染层。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 口径判定单点化，消灭「同报告口径不一致」类 bug | 引入新模块与契约概念，新人需理解 |
| 情景 / 敏感性 / 市场区口径由同一出口派生，可被 invariant 自动校验 | 每新增一类标的原型需同步维护契约表 |
| 渲染层「按契约分支」，口径与文案解耦，易测 | — |

---

## ADR-025: `min/max` 封顶点系统性审计——静态扫描 + 跨文件断言，闭区间为唯一合规判定
- **Date**: 2026-11-03
- **Status**: ✅ Accepted & Implemented (Session #14)

### Context
- ADR-023 证明「上游 `min(x, C)` / `max(x, C)` 封顶到常量 `C` + 下游严格 `<`/`>` 比较 `C`」是必漏模式，但当时**只修了 peer 倍数一处**，属人工发现、不可持续（M-15）。
- 更隐蔽的是**跨文件**形态：`classification/classifier.py` 把 `classification_confidence` 封顶到恰好 `0.55`，而 `models/sotp.py` 用 `conf < 0.55` 判定低置信——封顶与判定不在同一文件，任何「同文件」启发式扫描都无法发现。

### Decision
在 `tests/test_cap_boundary_guard.py` 建立三层可断言审计：
1. **Part A（常量守卫）**：登记「上游封顶常量 → 文件」映射（如 `_PEER_MULTIPLE_CONF_FLOOR`），断言源码中只出现闭区间比较（`<=` / `>=`），发现严格比较即失败。
2. **Part B（同文件字面量配对扫描）**：自动收集「同一文件内既出现在 `min()/max()` 实参、又出现在严格比较」的数值字面量；任何**新增**配对都使测试失败，强制人工审阅——是修 bug（改闭区间）还是加白名单（`REVIEWED_CAP_LITERAL_PAIRS` + 理由）。
3. **Part C（跨文件 confidence 封顶断言）**：登记分类器会封顶到的 confidence 常量集 `{0.40, 0.50, 0.55}`，扫描**全部模块**中形如 `conf/confidence < C` 的严格比较，命中即失败。**修复**：`models/sotp.py` 两处 `conf < 0.55` → `conf <= 0.55`。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 把「审计所有封顶点」从人工动作变为 CI 断言，回归零成本 | Part B 基于字面量，存在「不同变量同值」的误报，需白名单 + 理由维护 |
| Part C 覆盖跨文件形态，正是本类最易漏的场景 | 扫描基于正则，对动态阈值（变量/表达式）不覆盖，需按需补充常量登记 |
| 明确「封顶到边界值 → 闭区间」为唯一合规写法 | 新增封顶常量需同步登记，否则测试会拦截（设计如此） |

---

## ADR-026: 短 token 关键词必须词边界匹配——裸 ASCII ≤4 字符禁止子串匹配
- **Date**: 2026-11-12
- **Status**: ✅ Accepted & Implemented (Session #15)

### Context
- `classification/ml_classifier.py::_structural_overrides()` 用**子串**匹配关键词做行业强制覆盖。工业关键词表含 `"ups"`（UPS 快递），而语料里 ticker `upst`（Upstart）**包含** `"ups"` 子串 → 触发 `Structural FORCE->Industrial`，覆盖了本已正确的 FinTech 判定（§0 行业硬规则先跑，§6 工业覆盖后跑）。
- 后果链：UPST 被强制 Industrial → 走 DCF/EV-EBITDA/FCF-Yield（对借贷型业务无意义）→ DCF=$0.00、ReverseDCF 无解、情景三档全 $0.00、一致性 Very Weak。
- 试过的错误修法：把 `"ups"` 改成 `" ups"`（加前导空格）——仍失败，因为 ticker 在语料中形如 `... credit services upst`，`" upst"` 依然**包含** `" ups"`。

### Decision
新增边界感知辅助函数 `keyword_hit(text, keyword)`，对**裸 ASCII 且长度 ≤ 4** 的 token 强制词边界正则 `(?<![a-z0-9])kw(?![a-z0-9])`；**长词、带前导/尾随空格的关键词、非 ASCII（CJK）关键词保留原子串语义**（以兼容合法复数/屈折形如 `industrial`→`industrials`、`metal`→`metals`，以及有意的空格消歧如 `" logistics"` 避开 `prologis`）。§6 工业强制覆盖改用 `keyword_hit()`。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 短品牌/ticker token（ups / amt / iron…）不再与更长单词（upstart / amount / environment）碰撞 | 词边界仅对 ≤4 字符 ASCII 生效；更长 token 仍有理论碰撞面（权衡：长词碰撞概率低且加边界会破坏屈折匹配） |
| 保留长词/CJK/空格关键词的原有语义，零回归（AAPL/XOM/PLTR… 分类不变） | 新增关键词时需自检长度是否 ≤4，必要时改成显式空格形式 |
| UPST 恢复 FinTech（p=99.1%）→ 路由 Bank DDM/RIM/P/E/P/B | — |

---

## ADR-027: 金融标的的 EV 家族必须完整剔除 + 渲染层禁止口径泄漏（读契约）
- **Date**: 2026-11-12
- **Status**: ✅ Accepted & Implemented (Session #15)

### Context
- **EV 家族不完整**：`classification/classifier.py::_model_applicability()` 的金融分叉只剔除了 `DCF / ReverseDCF / EV/EBITDA / FCF Yield`，**漏了 `EV/Sales`**——而 `MODELS_BY_TYPE[FinTech]` 含 `EV/Sales`。UPST round1 报告因而**同页自相矛盾**：市场区打印「企业价值: N/M（金融机构不适用）」，却仍用 `EV/Sales` 作估值锚（$42.16，为区间唯一离群值，是 Very Weak 一致性的主因）。
- **渲染层口径泄漏**（违 ADR-024）：① `verdict_intuition.py` 的「股数不可靠」附注硬编码「建议以 EV 口径复核」，而 EV 对金融标的已声明 N/M；② `dashboard.py::_risk_section` 把模型层 `RiskType.WACC` 原样渲染为「WACC Risk」，但金融标的贴现口径是 `ke`（无 WACC）；③ 市场区 β 附注硬编码「市场区 / 风险旗标 / WACC 统一采用截断值」。

### Decision
1. **EV 家族完整剔除**：金融分叉（BANK/INSURANCE/FINTECH/NEOBANK）新增 `EV/Sales` 剔除（`na_reasons` 说明「EV embeds funding debt」），与 `EV/EBITDA`/`FCF Yield` 同族——凡 EV 派生倍数，对借贷型金融机构一并剔除。
2. **渲染层口径泄漏禁止（重申 ADR-024）**：所有涉及贴现口径/复核口径的文案必须**读 `build_caliber_contract(profile)` 分支**，不得硬编码 `WACC` 或 `EV`：
   - 公允区间附注：按 `MetricMeaning("EV")` 分支（金融 → 「P/B、P/E、RIM 复核」）；
   - 风险旗标 `WACC Risk`：按 `DiscountCaliber.COST_OF_EQUITY` 重标「Cost of Equity Risk」；
   - β 附注：改用口径中性词「折现率」。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 修复同页矛盾后 UPST 一致性 Very Weak → Moderate，离散度 316% → 36.2%，中位估值 raw==weighted | 资产轻支付型 FinTech（PYPL/SQ）也被一并剔除 EV/Sales——与既有「金融分叉对全 FinTech 剔除 EV/EBITDA」的既有取舍一致，非新增风险 |
| 风险/附注文案随引擎口径自动切换，新增原型只改契约构建器 | 模型层 `RiskType.WACC` 枚举值保持不变（golden invariant #4 依赖该字符串），仅在展示层重标 |
| 与 ADR-022/024「口径即契约」形成闭环（建模 + 渲染同源） | — |

---

## ADR-028: 负终期 FCF 严禁符号翻转——终值抑制 + 显式命名（不得伪造正终值）
- **Date**: 2026-11-12
- **Status**: ✅ Accepted & Implemented (Session #16)

### Context
- `forecasts/fcf_projection.py` 曾有一段「诚实性缺陷」：
  ```python
  if last_fcf <= 0:
      avg_abs = sum(abs(f) for f in fcf_list) / max(1, len(fcf_list))
      if avg_abs > 0:
          last_fcf = avg_abs     # ← 把负终期 FCF 偷改成正数
  ```
  随后该正数进入 Gordon Growth `TV = last_fcf × (1+g) / (WACC − g)`。
- **后果**：一家**持续烧钱**的公司会被凭空制造出一个**正的终值**——估值被系统性抬高，且缺陷对下游完全不可见（无标注、无旗标）。影响面覆盖 **Normal DCF / Reverse DCF / Monte Carlo**（三处各自复制了同一段符号翻转逻辑）。
- 试过的错误修法：把 `avg_abs` 直接置 0（仍会以 0 终值静默出结果，问题从「伪造正值」变成「静默归零」，同样不诚实）。

### Decision
1. **禁止符号翻转**：终期 FCF ≤ 0（含 None）时**不再伪造正值**，改由统一函数 `gordon_terminal_value()` 返回抑制态：
   - `terminal_value = 0.0`、`pv_terminal_value = 0.0`、`suppressed=True`；
   - 估值退化为**显式期 FCF 现值之和**作为**下限**（不是「无估值」，而是「不可用终值外推的下限」）。
2. **显式命名**：`FcfProjectionResult` / DCF `breakdown` 新增 `terminal_fcf_negative: bool`；求解状态固定为 `SolverStatus.APPROXIMATE`；note 明示「该估值需明确转型（turnaround）假设才成立」。
3. **单一出口收口**：`fcf_projection.py::gordon_terminal_value()` 为唯一 Gordon 入口；`models/dcf.py` 的 `_pv_calculations()` 与 `_pv_tv_only()` 全部改调它，消除三处重复的符号翻转逻辑。
4. **风险旗标同步**：`analysis/risk.py::_terminal_value_risk()` 新增显式分支——`terminal_fcf_negative=True` 时直接给 **HIGH** 级旗标（不能依赖 `tv_percent_of_ev`，抑制后该值为 0，原阈值检测不会触发）。
5. **WACC−g 下限统一**：`MIN_WACC_TG_SPREAD = 0.005` 替代原先散落的 `1e-3` / `1e-4`，`inflated` 时用同一 floor 并标注。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 烧钱公司不再产生人为正终值，估值口径诚实 | 显式期现值下限通常远低于（甚至显著低于）含正终值的乐观估值 → 部分标的估值下移 |
| 影响面三处（DCF/ReverseDCF/MonteCarlo）经同一 `gordon_terminal_value()` 收口，行为一致 | 报告需新增「终值被抑制 / 需转型假设」文案的理解成本 |
| 新测试 6 用例锁定（`tests/test_dcf.py::TestTerminalValueHonesty`） | golden 基线有意漂移（NBIS.median_value 12.76 → 10.46，已审阅） |

**Golden 漂移证据**：NBIS（`business_type=MatureTech`）终期 FCF `[-3.7B … -10.4B]` 全负 → `terminal_fcf_negative=True`、`pv_terminal_value=0.0`、status=Approximate；旧版 `median_value=12.76` 即由伪造正终值虚高而来，新值 `10.46` 为诚实下限。

---

## ADR-029: 预测年限单一真源 `resolve_forecast_horizon()`——禁止实例级 `self.horizon` 状态污染
- **Date**: 2026-11-12
- **Status**: ✅ Accepted & Implemented (Session #16)

### Context
- `models/reverse_dcf.py::calculate()` 曾执行 `if horizon is not None: self.horizon = int(horizon)`——**写回共享单例**。
- `ModelRouter` 的 `NAME_TO_MODEL` 持有**共享模型实例**（`"ReverseDCF": ReverseDCFModel()`），故该写入造成跨标的**状态污染**：
  1. 估值 SaaS → `self.horizon` 置 7；
  2. 估值 Utilities → 置 10；
  3. 估值未知类型（`horizon=None`）→ **无人重置**，静默沿用上一次的 10。
- 同族问题：DCF / Scenario / Sensitivity / Monte Carlo / Expectation 各自从 `DEFAULT_FORECAST_HORIZON_YEARS` 或本地常量取年限，**口径可能互相不一致**（反向 DCF 的 FCF CAGR 计算周期 ≠ 正向投影周期 → 隐含增长率不可比）。

### Decision
1. 新增 **单一真源** `config.resolve_forecast_horizon(business_type) -> int`：读 `REVERSE_DCF_BY_TYPE[bt].horizon`，缺失则回落到 `DEFAULT_FORECAST_HORIZON_YEARS=5`。
2. **禁止写回实例**：`reverse_dcf.py` 删除 `self.horizon = ...`；改为每次 `calculate()` 内解析**局部** `horizon`。`__init__` 的显式 `horizon` 参数降级为**一次性 override**（存 `self._horizon_override`，不再污染类型默认）。
3. **全链路统一**：DCF / ReverseDCF / Scenario / Sensitivity / MonteCarlo / Expectation 全部改经 `resolve_forecast_horizon(business_type)`；DCF 与 ReverseDCF 预测年限**必须一致**。
4. **求解器诚实性**：`reverse_dcf` 的 `brentq` 解后新增 **residual 检查**——`rel_resid = |f(root)| / |target_ev| > 1e-3` 时标记 `SolverStatus.APPROXIMATE` 并记录 note（EV 曲面平坦 → 隐藏多解风险显式暴露）。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 未知类型标的不会再继承上一只的年限，跨标的可复现 | golden 基线会大面积重生成（承认此震动，已逐条审阅） |
| DCF 与 Reverse DCF 年限同源 → 隐含增长率可跨模型比较 | 新增 override 语义（构造期一次性）需在文档/注释中说明，避免误用 |
| 4 用例锁定（`tests/test_reverse_dcf.py::TestHorizonIsolation`，断言 `not hasattr(m, "horizon")`） | — |

---

## ADR-030: 隐含期望用「约束式单变量求解」——硬边界不钳制 + 单调性 + 残差检查，禁止联合求解
- **Date**: 2026-11-12
- **Status**: ✅ Accepted & Implemented (Session #17)

### Context
- Reverse DCF 原先**只反推 Revenue CAGR**：报告无法回答「若其它条件不变，当前价隐含的营业利润率 / FCF 利润率 / 折现率 / 终值增长率是多少」。
- FCF margin 此前**不是独立变量**——FCF 由 `ForecastEngine._extract_history()` 固定的历史营业利润率 / DA / CapEx / NWC / 税率驱动，实为「Revenue Growth → FCF → EV」单一通道，无法单独反解。
- 一方程多未知数**联合求解欠定**（无穷多解），且朴素做法（把目标钳制到搜索边界）会输出**假的可行解**。

### Decision
1. **单变量 one-at-a-time**（非联合求解）：一次只解一个隐含值，**其余假设固定为基准**（先解出的营收 CAGR + FCF 桥历史 margin/DA/CapEx/NWC/税）；每个数值在报告中显式标注「其余假设固定为基准」。
2. **硬边界约束**：`_solve_implied_scalar()` 先算目标在 `[lo, hi]` 的**可达区间**，目标越界 → `SolverStatus.NO_SOLUTION_IN_RANGE` + `note` **指名绑定边界**，`value=None`——**绝不钳制到边缘**。
3. **单调性约束**：`increasing` 决定可达端（margin/CAGR/TG 越高 EV 越大；WACC 越高 EV 越小）。
4. **残差检查**：`rel_residual = |f(root)| / |target| > implied_residual_tol(1e-3)` → 降级 `APPROXIMATE`（EV 曲面平坦 → 多解风险）。
5. **一致性下限**：`implied_wacc` 下界 = `max(implied_wacc_lo, tg + MIN_WACC_TG_SPREAD)`；`implied_terminal_growth` 上界 = `min(implied_tg_hi, wacc − MIN_WACC_TG_SPREAD)`（复用 Session #16 的统一常量）。
6. **FCF margin 独立化**：新增 flat-margin 桥 `project_enterprise_value_flat_margin()`（`FCF_t = revenue_t × fcf_margin`），绕过 NOPAT/DA/CapEx/NWC 桥，使 FCF margin 成为良定义独立求解目标；终值仍走 `gordon_terminal_value()`。
7. **落字段契约**：`ImpliedSolve`（`value`/`status`/`residual`/`rel_residual`/`bound_lo`/`bound_hi`/`note`）→ `breakdown["implied_expectations"]` → `ImpliedExpectations`（8 新字段）→ `_implied_section()` 渲染（含「不可解（超出约束区间）」/「_(近似)_」）。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 报告可独立回答四类「当前价隐含的 X」问题，且诚实区分「可解 / 越界 / 近似」 | 单变量解彼此独立，非联合一致解（已在 `note` 中显式声明，避免误读为「同时成立」） |
| 越界**指名边界**而非钳制，杜绝「假可行解」污染结论 | 越界时输出 `None` + 文案，渲染层需正确处理（已加「不可解（超出约束区间）」分支） |
| FCF margin 成为良定义独立目标（flat-margin 桥） | flat-margin 桥与主 NOPAT 桥假设不同，跨指标不可直接相加比较 |
| 8 用例锁定（`TestConstraintSolver` 5 + `TestImpliedExpectationsPhase2` 3） | 隐含驱动暂未纳入 golden 指纹（待后续审阅漂移） |

---

## ADR-031: 求解器「根的真实性」优先——有效 bracket 重校验 + 实测单调性 + 多根/常数检测 + 终值抑制贯穿
- **Date**: 2026-11-12
- **Status**: ✅ Accepted & Implemented (Session #18)

### Context
- 用户对 `models/reverse_dcf.py` / `forecasts/fcf_projection.py` 的**静态代码审查**指出 6 项风险（3×P0 + 3×P1）：
  - **P0-1** Brent 求解失败仍进入 Bisection，**未先确认 `f(a)·f(b) ≤ 0`** → 无根区间也可能返回「看似正常的 CAGR」，被报告误当真实市场隐含预期。
  - **P0-2** 求解器**默认单调**，仅凭两端点值判断可解范围——数学上端点大小**不能证明整区间单调**（TG 接近 WACC、终值占 EV 比例高、负 FCF 转正、非线性利润率桥接时尤甚）。
  - **P0-3** 负终值已被抑制（Session #16），但 `FcfProjectionResult.terminal_fcf_negative` **未贯穿**到 Reverse DCF 状态 / 情景 / 报告——终值被抑制时仍可能显示 `SOLVED`，投资者误以为十年 DCF 已完整。
  - **P1-4** `_project_ev()` 只返回 `proj.enterprise_value`，抑制旗标丢失。
  - **P1-5A** Revenue CAGR 边界条件用严格 `< 0`，`ev_lo == target` / `ev_hi == target`（端点根）被误判无解。
  - **P1-5B** 常数目标未检测——终值抑制后隐含 TG 可能**完全不影响 EV**，仍可能随便输出一个值。

### Decision
1. **根的真实性优先**：新增 `_finish_root()`——在**已验证** bracket 内求解。`brentq` 抛错后若 `f(a)·f(b) > 0` → `NO_SOLUTION_IN_RANGE`（**拒绝返回可疑根**）；否则二分；**无论哪条路径，最后都计算 residual**，`rel > implied_residual_tol` → 降级 `APPROXIMATE`。
2. **单调性必须实测**：`_solve_implied_scalar()` 先以 `implied_monotonic_samples = 21` 点采样验证声明的方向。非单调 → `_root_brackets()` 扫描变号区间：**0 → 无解；1 → 求解；>1 → `MULTIPLE_ROOTS`**（拒绝输出单一隐含值）。步长级平坦 → `NON_MONOTONIC`。单调性容差使用**步长尺度** `mono_tol = 1e-6·f_span`，**不得**复用被 `|target|` 放大的残差容差。
3. **常数目标检测**：`fmax − fmin ≤ abs_tol` 时——命中目标 → `FLAT_OBJECTIVE`（对该假设无敏感度）；不命中 → `NO_SOLUTION_IN_RANGE`。**绝不**输出无意义的隐含值。
4. **端点根合法**：`|ev_endpoint − target| ≤ abs_tol` → 直接判边界解 `SOLVED`（`ev_lo == target` / `ev_hi == target` 不再被误判无解）。
5. **终值抑制贯穿**：`terminal_fcf_negative` 纳入 Reverse DCF `breakdown` 与 `breakdown["implied_expectations"]`；`_finalize_revenue_cagr()` 在终期 FCF ≤ 0 时把 `SOLVED` 降级 `APPROXIMATE` + note「Terminal Value Suppressed — Turnaround Assumption Required」；`analysis/expectation.py` 与 `reporting/dashboard.py` 透出。
6. **可达区间语义**：`lo_val/hi_val` 恒为 `(fmin, fmax)`（与方向无关），仅交换 `x_at_max/x_at_min`；避免递减方向赋值反转导致误报「超出约束上界」。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 求解器不再返回「无根区间里的可疑根」——错误根不会被误当真实市场隐含预期 | 采样 + 多根扫描增加少量计算（21 次目标函数求值/驱动） |
| 单调性从「假设」变为「实测」，非单调/多根如实命名（`NON_MONOTONIC` / `MULTIPLE_ROOTS`） | 采样分辨率有限（21 点），极窄区间的双根理论上可能被合并——已在 `note` 提示 |
| 终值被抑制的结果不再伪装成完整 `SOLVED`（降级 `APPROXIMATE` + turnaround 文案） | 渲染层需处理 5 种新增未解状态（已按 `SolverStatus` 枚举驱动，无口径猜测） |
| 端点根 / 常数目标 / 无效 bracket 均显式命名，杜绝「假可行解」 | 未纳入 golden 指纹（沿用 Session #17 决定，待后续审阅漂移） |
| 18 用例锁定（边界 ×2 / 无效 bracket / 无 bracket / 非单调 / 多根 / 常数 ×2 / 负终值 ×4 / round-trip ×3 / 多股票隔离 ×2） | — |

---

## ADR-032: Rf 单一真源 + Terminal Growth 三档「经济学含义」重定义——GDP 上限只约束 Base，乐观 High 必须显式标注为情景
- **Date**: 2026-11-13
- **Status**: ✅ Accepted & Implemented (Session #19)
- **Supersedes part of**: ADR-028（TVG 三档间距）/ 早期 DCF 假设文案

### Context
- 用户对 `valuation/wacc.py` / `valuation/terminal_growth.py` / `models/dcf.py` 的**静态代码审查**指出 2 项 P0（用户声明为「实际代码问题，不是推测」）：
  - **P0-1 Rf 双源背离**：`WaccCalculator.calculate()` 按「`MarketData.risk_free_rate` → `TreasuryYieldProvider` → `DCFConfig.risk_free_rate`」解析 Rf，CAPM 用其算 `ke = rf + β·ERP`；但 `_implied_cost_of_debt()` **自行重读** `rf = getattr(mkt,"risk_free_rate",None) or DEFAULT_DCF_CONFIG.risk_free_rate`。**后果**：若主流程已从 Treasury 取到 5.103% 而 `MarketData.risk_free_rate` 为空，则 ke 用 5.103%，而债务成本 fallback 用 4.50% + spread——**报告的 Rf 与实际进入 WACC 的债务成本口径不一致**。
  - **P0-2 High 无条件突破长期 GDP**：`high = Base + 0.5%`，注释与 DCF 假设文案均写明「High may exceed LT GDP；only Gordon bound is a hard cap」/「Base + 0.5% (not GDP-capped)」。若 4.5% 被定义为长期名义 GDP 上限，则该算法允许 `Base=4.5% → High=5.0%`，**High 可被误读为「长期稳定终值增长率」**。

### Decision
1. **Rf 单一真源**：`_implied_cost_of_debt()` 新增 `risk_free_rate: Optional[float]` 形参；`calculate()` 改为 `self._implied_cost_of_debt(data, risk_free_rate=rf)`——**所有债务成本 fallback（ICR 合成评级 spread / BBB-like `rf + 2.5%`）与 CAPM 共用同一已解析 Rf**。禁止在任何债务成本路径内独立重读 `MarketData.risk_free_rate`。独立调用者（单测）在未传参时回落原优先级链，保持行为一致。
2. **三档经济学含义重定义**（不机械禁止 High > GDP）：
   - **Base = 长期稳定终值增长率**——唯一受 **LT nominal GDP（4.5%）** 与 **Gordon 上限（WACC−0.5%）** 双重约束的档位（即进入 base-case DCF 的值）。
   - **Low = 保守情景** / **High = 乐观情景**——情景区间，仅受 Gordon 上限约束；**High 允许高于长期 GDP**，但**绝不允许被称作长期稳定终值增长率**。
3. **引擎语义契约化**：`TerminalGrowthRange` 新增 `high_exceeds_gdp: bool`、`gdp_ceiling: float`、`band_labels: Dict[str,str]`；新增模块级 `BAND_LABELS` 契约常量（`low`/`base`/`high` → 本地化文案）。渲染层**消费**该契约，禁止自造口径词（延续 ADR-024）。
4. **三处显式标注**：`high_exceeds_gdp` 为真时，在 ①`derivation_trace()`、②`models/dcf.py` 假设说明、③`reporting/dashboard.py` 三档区块，统一标注「High 仅作乐观情景参考，非长期稳定终值增长率」，并附 `High X% > 长期名义 GDP Y%` 的比较。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| ke 与 kd fallback 严格共用同一 Rf——报告的 Rf 与进入 WACC 的债务成本口径一致 | `_implied_cost_of_debt()` 形参含义依赖调用方传入「已解析 Rf」；独立调用需回落链（已在 docstring 声明） |
| 「长期稳定终值增长率」不再被乐观 High 污染——术语诚实 | High 可超 GDP 属**有意设计**，需靠 `high_exceeds_gdp` 显式标注避免误读（已三处覆盖） |
| GDP 上限与情景间距不再互相牺牲——保留 3 档间距的经济学意义 | 渲染层需处理新旗标（已契约化，无口径猜测） |
| 新增 5 用例锁定同源 Rf + 三档语义（147/147 passed） | 未纳入 golden 指纹（沿用 Session #17/#18 决定，待后续审阅漂移） |

---

## ADR-033: Quality-Weighted Median 采用标准 midpoint 定义——等权时必须精确退化为普通中位数
- **Date**: 2026-11-13
- **Status**: ✅ Accepted & Implemented (Session #19)
- **Refines**: ADR-015（质量加权中位数权重体系）

### Context
- 用户静态审查 `analysis/model_agreement.py` 指出 P1 边界缺陷。原 `_weighted_median()`：
  ```python
  cum = 0.0
  for name, v in items:          # items 已按值升序
      cum += max(0.0, weights.get(name, 1.0))
      if cum >= total / 2.0:
          return v
  ```
  返回**首个累计权重 ≥ total/2 的值**。当所有模型权重相等（常见：多个 SOLVED 模型权重均为 1.0，如 AAPL 六模型）且求解模型数为**偶数**时，累计权重恰在第 n/2 个值处达到 total/2 → 返回第 n/2 个值，而普通中位数是 `mean(values[n/2-1], values[n/2])`。**后果**：报告的「加权中位数」在等权时系统性偏低，与「普通中位数」打架（AAPL 报告 176.12 vs 165.24）。

### Decision
1. **midpoint 定义**：加权中位数 = (下加权中位数 + 上加权中位数) / 2。
   - 下加权中位数 = 升序累加权重，首个 ≥ total/2 对应的值。
   - 上加权中位数 = **降序（对称扫描）**累加权重，首个 ≥ total/2 对应的值。
2. **等权退化不变量（硬约束）**：当所有权重相等时，该定义**精确等于** `statistics.median`——偶数取中间两值平均，奇数取正中值。此不变量以单元测试锁定。
3. **权重卫生**：负权重钳制为 0；权重缺失默认 1.0；`total ≤ 0`（含全零权重）→ 返回 `None`；空输入 → `None`；单值 → 其自身。
4. **不引入 epsilon**：midpoint 定义天然无需容差比较（下/上扫描取平均即可收敛），避免浮点 `==` 判定。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 等权时「加权中位数」== 普通中位数——消除 AAPL 176.12 vs 165.24 式自相矛盾 | 不等权且累计权重恰好落在 total/2 时，结果变为相邻两值平均（属标准行为，非缺陷） |
| 用标准 midpoint 定义，可被外部库（numpy/statistics）交叉验证 | golden 出现 4 只标的有意漂移（`median_value_weighted` 归位），需审阅重生成 |
| 权重卫生（零/负/缺失）显式化，杜绝脏权重污染统计量 | 新增 `tests/test_model_agreement.py`（16 用例）维护成本 |
| 16 用例锁定等权退化不变量 + 全部边界 | 未纳入 golden 指纹之外的额外 invariant（沿用既有决定） |

---

## ADR-034: Monte Carlo 必须是「DCF 假设的扰动分布」而非独立证据——零扰动锚点必须精确复现确定性 DCF
- **Date**: 2026-11-13
- **Status**: ✅ Accepted & Implemented (Session #20 / Phase 2)
- **Refines**: ADR-016（概率语言）；关联 ADR-028（负终值抑制）

### Context
- MSFT 报告曾出现「MC 中位 $255.70 vs 确定性 DCF $170.70」却同时宣称 CV 6.6%「Very Strong」——两条结论无法调和，因为 MC 用了**独立于 DCF 的粗糙分布**（历史统计 + 人为 `max(om, +2%)` 利润率地板），且以**平坦 CAGR / 平坦 OM** 投影，而确定性 DCF 用**衰减增长路径 + 漂移利润率路径**。零扰动时 MC 锚点 ≠ DCF（MSFT 偏差 +13.85%）。
- 「P(股权价值归零/破产)」的措辞把「equity value 归零」误命名为「公司破产」，方向与基准均错误。

### Decision
1. **双模式显式化**：MC 只有两种模式——`base_case`（以确定性 DCF 的**同一 base 预测**为中心，仅扰动假设）与 `historical`（历史分布，完全独立）。
2. **锚点对账（硬约束）**：`base_case` 模式在**零扰动**时必须精确复现确定性 DCF 的 base 点值。实现方式为**路径形参化**——`_base_case_path()` 提取 DCF base 的逐年 `shape_rev[i]`（营收形状）与 `margin_offsets[i]`（利润率偏移），`_project_one_path()` 在 `(eff_cagr, eff_om)` 处复用 DCF 相同的 `forecast_nwc_change` / `gordon_terminal_value` 精确重放。
3. **无人工地板**：移除 MC 内 `max(om, +2%)` 等任何人为利润率地板，允许负利润率；驱动边界全部由 `MonteCarloConfig` 可配置。
4. **负股权口径统一**：MC 锚点沿用 DCF「负股权价值 → 归零」约定（`anchor_value = max(anchor_value, 0)`），两侧不再撕裂。
5. **缺失锚点自动回退**：无 `dcf_value`（金融股走 RIM/DDM 或 DCF 未求解）时，**自动回退 `historical` 并附说明**，绝不静默。
6. **用词修正**：`P(股权价值归零/破产)` → 「模拟下的 Equity Value Wipeout Probability」（equity value 归零，非公司破产）。
7. **报告透明化**：MC 区块必须展示 模式 / 随机种子 / 请求数 / 有效数 / 无效数 / 截断数 / 参数分布 / 相关矩阵；对账行**仅在 `base_case` 模式**渲染，且明确标注「这是 DCF 假设的扰动分布，不是独立估值证据」。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 零扰动锚点 = 确定性 DCF（MSFT/AAPL/NBIS 差 +0.0%），MC 与 DCF 可对账 | MC 不再提供「独立于 DCF」的第二意见（独立性由 `historical` 模式承接） |
| 允许负利润率，如实反映亏损期标的（NBIS）经济现状 | 需要维护路径形参化投影（`_project_one_path`）与 DCF base 的一致性 |
| 无锚点自动回退 + 说明，金融股不再产出无意义 base_case | 回退需在报告层呈现模式标签与原因 |
| 采样计数透明，杜绝「请求 2000 / 实际有效多少」不可见 | MC 分布参数仍以历史统计为默认中心（自相关建模留待后续） |

---

## ADR-035: 情景分析必须拆分「经营驱动情景」与「折现率情景」，各自标注口径
- **Date**: 2026-11-13
- **Status**: ✅ Accepted & Implemented (Session #20 / Phase 2)
- **Refines**: ADR-022（金融情景走 Bank RIM）；关联 ADR-024（口径契约）

### Context
- 原「情景」区块把**经营驱动**（营收增长 / 利润率）与**折现率**（WACC / 终值增长率 g）两类语义完全不同的情景混在一起，读者无法判断情景间差异来自「经营假设」还是「折现假设」。
- 金融股走成本法（ke）+ 经营性 ROE，与 DCF 的 WACC/g 口径不同，更需显式区分。

### Decision
1. **`ScenarioValuation` 增 `scenario_kind`**：`discount_rate`（默认）/ `operating` / `financial`；并增 `drivers` 字典记录驱动明细。
2. **折现率情景**（`_run_one`）：仅变动 WACC / 终值增长率 g，`drivers={"wacc":..., "terminal_growth":...}`；报告区块前置「本组情景仅变动折现率（WACC / 终值增长率 g）；经营驱动情景见下文」。
3. **经营情景**（新增 `run_operating`）：变动营收增长 × 经营性利润率 → 经 `forecast._apply_multipliers` + `model._pv_calculations` → EV，`scenario_kind="operating"`；报告独立区块「🏭 经营性情景」。
4. **金融股**：`run_operating` 返回 `{}`（成本法口径无 DCF 经营情景），报告相应缺省「经营情景」区块。
5. **区块标题契约化**：`config.REPORT_SECTION_TITLES` 新增 `scenarios="🎭 折现率情景"` 与 `operating_scenarios="🏭 经营性情景"`，渲染层消费常量，禁止自造口径词。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 读者可区分情景差异来自「经营」还是「折现」 | 报告多一个区块，篇幅增加 |
| 金融股经营情景正确缺省，不再套用 DCF 口径 | 需维护 `run_operating` 与 DCF 预测引擎的一致性 |
| 区块标题/口径由引擎常量驱动，渲染层无口径泄漏 | golden 走 `monte_carlo=None` / 不含经营情景，故无漂移（如需纳入需先审阅） |

---

## ADR-036: WACC Beta 必须暴露多窗口敏感性——单一 β 不得掩盖估计不稳
- **Date**: 2026-11-13
- **Status**: ✅ Accepted & Implemented (Session #21 / Phase 3)
- **Refines**: ADR-019（β 单一出口 `resolve_effective_beta()`）；关联 ADR-032（Rf 单一真源）

### Context
- CAPM 依赖单一标量 β，而 β 是**回归估计量**——同一标的在 2Y 周线 / 3Y 月线 / 5Y 月线窗口下可能显著不同。
- 原报告只给一个 β，读者无法判断该估计是否稳定，也无法审计「结论对该假设的敏感度」。
- bottom-up β（同业 unlevered β × 公司杠杆）是交叉验证的标准手段，但需要同业数据源；缺失时必须明确标注，禁止伪造。

### Decision
1. **`MarketData` 新增两个诚实槽位**：`beta_windows: Optional[Dict[str, float]]`（窗口标签 → 回归 β）与 `industry_beta: Optional[float]`（bottom-up/peer unlevered β）；**`None` 表示「无来源」，绝不填充猜测值**。
2. **provider 多窗口回归**：`BETA_WINDOWS=(2y_weekly / 3y_monthly / 5y_monthly)`；`_estimate_beta()` 泛化为 `(range_, interval, min_obs)`；周线用 ISO-week keying 归并同周收盘；`_estimate_beta_windows()` 逐窗口独立回归，**失败窗口显式存 `None`**。
3. **β 多窗口是独立审计输入，不覆盖 CAPM 标量 β**：`resolve_effective_beta()` 输出的标量 β 仍用于 CAPM；多窗口仅用于「稳定性披露」。
4. **`WaccBreakdown` 新增 `beta_windows`/`beta_dispersion` + `beta_window_note()`**：可用窗口 < 2 时返回 `None`（不臆造稳定性结论）；极差 > 0.50 时标注「窗口间波动较大（β 随取样窗口显著变化，结论对该假设敏感）」。
5. **渲染契约化**：`reporting/dashboard.py` 在 WACC 区块消费 `beta_window_note()`，渲染层不硬编码口径词。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| β 估计的不稳定性对读者显性可见，不再被单一数值掩盖 | 每个窗口多一次 SPY 抓取，数据层开销增加 |
| bottom-up β 槽位与渲染就绪，接入同业数据即可启用 | 当前 provider 无同业 unlevered β 数据 → `industry_beta` 恒为 `None`（诚实缺省，非伪造） |
| 多窗口为独立审计输入，CAPM 口径不变 → golden 无漂移 | 窗口边界（月聚合）可能轻微合并样本，回归值有极小抖动（测试容差 0.01） |

---

## ADR-037: 同源模型族不得作为「多条独立证据」抬高一致性门控
- **Date**: 2026-11-13
- **Status**: ✅ Accepted & Implemented (Session #21 / Phase 3)
- **Refines**: ADR-018/021（覆盖率门控）；关联 ADR-033（加权中位数）

### Context
- 一致性分析按「解算成功模型数」计覆盖率门控，但**部分模型共享同一证据来源**：`P/E` 与 `Historical Multiples` 同用 `PEModel` 的盈利倍数；`EV/Sales` 与 `EV/Sales (Unit Econ)` 同族；`DCF` 与 `ReverseDCF` 同源预测路径。
- 若不归并，同一证据会**重复计票**，人为抬高覆盖率与一致性等级（虚假繁荣）。

### Decision
1. **`_MODEL_FAMILY` 映射**：`P/E`↔`Historical Multiples`→`earnings_multiple`；`EV/Sales`↔`EV/Sales (Unit Econ)`→`sales_multiple`；`DCF`/`ReverseDCF`→`dcf_forecast`；未列入者视为各自独立。
2. **`_independent_evidence()`**：按 family 归并，返回「独立证据数」与「重复族明细」。
3. **门控改用独立证据数**：`_COVERAGE_CAP.get(n_solved)` → `.get(n_independent)`。
4. **`ModelAgreement` 新增 `n_independent_evidence` / `duplicate_evidence_groups`** + 去重 note：「一致性门控按 N 个独立证据计数（而非 M 个解算模型）」。
5. **peer 倍数来源溯源（同批）**：`PEER_SOURCE_EXACT_INDUSTRY` / `SECTOR_FALLBACK` / `BUSINESS_TYPE_FALLBACK` / `APPROXIMATE` 封闭集 + `peer_sample_size`；缺失样本数不得静默。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 同源证据不再重复计票，一致性等级如实反映独立证据量 | 部分标的门控等级可能下调（真实信号，非回归） |
| peer 倍数来源可审计（档位 + 样本数） | 需维护 `_MODEL_FAMILY` 映射（新增同源模型时同步） |
| 渲染层显式披露去重组，读者可见「为何按 N 而非 M 计票」 | 去重后 `n_independent` 与 `n_solved` 并存，字段增多 |

---

## ADR-038: 验收标准必须断言化——样本口径、核心模型排除、风险底线都要有可执行回归，而非文字声明

- **Date**: 2026-11-13
- **Status**: ✅ Accepted & Implemented (Session #22 / Phase 4)
- **Refines**: ADR-014（覆盖率门控）；关联 ADR-018（golden diff）/ ADR-029（单一真源）/ ADR-033（加权中位数）

### Context
- 估值完整性重构（Phase 1–3）修复了「虚假高一致性 / 风险被总分掩盖 / 核心模型被静默移除」等缺陷，但这些修复此前**没有对应的可执行回归断言**——只能靠人工读报告判断。
- 若没有断言，未来任何改动都可能悄悄回退这些行为（如覆盖率门控又按 `n_solved` 计票、invariant 未覆盖核心模型排除场景），而测试仍「全绿」。
- 同时，报告需区分「原始解算 / IQR 排除 / 参与聚合」的样本口径（任务书验收 6），golden 指纹此前未承载这些字段。

### Decision
1. **golden 指纹承载样本口径**：`build_fingerprint()` 新增 `n_independent_evidence` / `raw_solved_count` / `outlier_count` / `effective_aggregation_count` / `core_model_excluded`；恒等式 `effective + outlier == raw` 由 `reporting/math_audit.py` 断言。
2. **invariant 显式化缺陷场景**：
   - `check_invariants()` #2 覆盖率封顶门控改按 `n_independent_evidence` 计（与 Phase 3 计票口径一致）。
   - 新增 invariant 2b：**核心模型（DCF）被 IQR 排除** 却仍输出 `Very Strong / Strong / Moderate` → 判为缺陷（禁止「静默移除核心模型却显示高一致性」，任务书验收 1/2）。
3. **验收标准测试化**：新建 `tests/test_phase4_integrity.py`，把任务书的 10 条验收标准逐条落为可执行断言（风险底线全 universe 覆盖、High 旗标强制整体 ≥High、IQR 排除核心模型 → `Unresolved Disagreement (Review Required)`、封顶按独立证据数计票、极端 TV/EV 支配下调权重、未知身份不冒充精确行业匹配、样本口径恒等、负 FCF 建构保留旗标）。
4. **回归 universe 扩展**：`BASKET` 由 9 → 18 只，覆盖 MatureTech / ConsumerCyclical / Semiconductor / FinTech / Industrial / ConsumerStaples / Bank 各 archetype，使 invariant 在更广画像上被检验。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 已修复的诚实性行为被自动化回归锁定，防止静默回退 | golden 基线字段增加，任何样本口径变更都会触发出现漂移（需审阅后重生成） |
| 报告样本口径（原始/IQR/参与）可审计、可断言 | 新增 18 只 fixture，测试运行时间略增 |
| 风控底线与核心模型排除不再依赖人工读报告 | 断言与不变式需随模型族扩充同步维护 |

## ADR-039: 引入「内部标准 Taxonomy + 五维公司拆解」——经济学特征只能族内细化 Identity，严禁跨族决定

- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #23)
- **Refines**: ADR-003（ML + 规则混合分类）；关联 ADR-013（标签 vs 财务原型冲突）/ ADR-026（词边界匹配）/ ADR-012（按经济结构路由）
- **Supersedes（部分）**: 原先散落三处的隐式 conflict 规则——`classifier.SECTOR_INDUSTRY_MAP`（扁平子串列表）/ `resolve_identity_economics_status`（硬编码 TECH_IDENTITY_TYPES）/ `ml_classifier._structural_overrides`（大量重复 `_swap_boost(X, MatureTech)`）

### Context
- 原先的「Yahoo industry vs ML 冲突处理」事实上是**一个从未抽出的 taxonomy**，散落在三个文件里，且「高毛利 + 高 CapEx + 低杠杆 ⇒ 半导体」这条错误规则**只存在于科技一个分支**——它会把经营大型 AI 数据中心的 Software/Cloud 公司误判为 Semiconductor。
- 冲突处理不可审计：没有统一的节点坐标、没有冲突分级、没有原始外部标签留痕。
- 财务特征（毛利率/CapEx/杠杆）被当作 Business Identity 的证据，违反「结构 ≠ 身份」的经济学常识。

### Decision
1. **五维拆解模型**（`classification/taxonomy.py`）：① Business Identity（显式节点树）/ ② Business Model（SaaS/Licensing/Cloud Usage/Advertising…）/ ③ Revenue Composition（分部占比 + as-of；**不可用必须显式声明**）/ ④ Economic Profile（毛利率/CapEx/FCF/杠杆**形状**）/ ⑤ External Classification（Yahoo/GICS/NAICS/ML **原样保存**，绝不覆盖内部判断）。
2. **内部标准 Taxonomy 树**：canonical node key（点分如 `tech.software.infra`）+ parent + archetype；族根为无点 key；`depth` 由 **parent 链**推导（非 key 点数——`cons.cyclical` 这类分组节点的子节点与其同点深）。
3. **黄金法则（Golden Rule）**：经济学特征只能在**同一 family 内细化** identity，**永不跨族决定**（`economic_identity_ceiling()`；同族兄弟冲突收敛至 **common ancestor**，绝不采用经济学节点——Infra-Software + 半导体经济特征 → `tech`/MatureTech，**不是** Semiconductor）。
4. **冲突分级**（`ConflictKind`）：`CONSISTENT` / `REFINEMENT`（同族收敛到共同祖先）/ `IDENTITY_WINS`（跨族冲突保留身份并扣置信度）/ `ECONOMICS_ONLY`（无结构化身份，仅经济学线索 + 扣分标注）/ `INSUFFICIENT`。
5. **匹配改为「先 industry 后 sector」两段式**：原先把 sector+industry 拼接后做 longest-key-wins，会让长的**宽泛 sector 短语**（`Consumer Cyclical` 17 字符）压过短的**具体 industry**（`Internet Retail` 15 字符）→ 误判为 `cons.generic`。现 industry 优先匹配，sector 兜底。
6. **Additive / shadow 接线**：五维结果仅写入 `CompanyProfile.taxonomy_*` / `external_classification` 等**新增字段**，不改 `business_type` / `applicable_models` / 路由 → golden 指纹零漂移。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 冲突处理从「三处散落 if」收敛为**一个显式 contract**，可审计（`audit_lines()`） | ③ Revenue Composition 仍是唯一真障碍——Yahoo timeseries 无分部收入，SEC EDGAR 未启用，故当前恒为 `unavailable` |
| 「结构 ≠ 身份」被 API 级强制（跨族/同族兄弟均不被经济学收编） | Taxonomy 是 shadow 层：暂不参与路由，需后续显式切换才会影响估值 |
| 原始外部标签留痕，冲突可回溯 | 节点表 +2 处映射（logistics 等）需随画像扩充维护 |
| 修掉 sector 短语压过 industry 的映射缺陷（AMZN→E-commerce、KR→Grocery Retail） | — |

---

## ADR-040: 三源 sector/industry 补全链（FinanceDatabase → SEC EDGAR SIC → Wikidata）+ bottom-up 同业无杠杆 β

- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #24 / H-03)
- **Refines**: ADR-003（ML + 规则混合分类）/ ADR-012（按经济结构路由）
- **Depends on**: ADR-039（taxonomy shadow 层，本决策补其上游 `sector/industry` 输入）
- **Closes（部分）**: TODO **H-03**（修复 Yahoo `assetProfile` 401）；缓解 **M-16** 根因（特征缺失）；唤醒 **M-26**（bottom-up β 空槽位）

### Context
- Yahoo `quoteSummary/assetProfile` 端点长期 **401 Unauthorized（约 83% 标的）** → `MarketData.sector` / `industry` 大面积为 `None`。这两个字段是分类器 **layer-2 行业硬规则（+3.0）** 与 ML **文本特征**的最强输入，缺失把边界准确率钉在 ~75%。
- 原 fallback 只有单一 Yahoo 通道（`_fetch_quote_summary_simple` Layer-3 resolver），无权威二级来源；同时 `MarketData.industry_beta` 自 Session #21 起一直是**空置审计槽位**（恒为 `None`）。
- 用户要求：用 **SEC EDGAR**（一手 SIC）、**Wikipedia/Wikidata**（冷门/退市兜底）、**FinanceDatabase**（30 万+ 离线元数据）三来源补全，并唤醒 bottom-up β、把分类准确率从 75% 推到 90%+。

### Decision
1. **三源优先级链（绝不伪造）**：`SectorIndustryResolver` 依次尝试 ① **FinanceDatabase**（离线、Yahoo 兼容口径、无 HTTP）→ ② **SEC EDGAR**（`company_tickers.json` 取 CIK → `submissions/CIK*.json` 取官方 **SIC 代码 + 描述**，一手监管数据）→ ③ **Wikidata SPARQL P452**（兜底刚上市/退市/冷门标的）。任一层缺失或断网返回 `{}` 继续下一层；**全部失败返回 `{}`，不填猜测值**。返回契约 `{sector, industry, sic, sic_description, source}`（`source` 标注 `financedatabase`/`sec-edgar`/`wikidata`）。
2. **SIC → Yahoo 桥接必须「可消费」**：SIC 是美国监管口径，引擎消费 Yahoo 口径（`map_sector_industry` 硬规则 / peer 桶 / WACC sanity 带）。经 `data/sic_map.py::map_sic_to_yahoo()` 解析（**精确 4 位 → 2 位大类 → 描述关键词**，关键词按具体→宽泛排序，`semiconductor` 先于 `software`）。**契约：每个映射产出的 industry 必须能被分类器硬规则消费**，否则返回 `None`——用一个「看起来对但无法行动」的值污染下游比留空更糟。
3. **SEC 合规访问**：SEC 公平访问政策要求带含联系方式的 `User-Agent`（`SEC_USER_AGENT` 可配，默认含联系方式）；限流保守；结果缓存（类级 `_MEM` + `.cache/` 磁盘，`.cache/*` 已 gitignore）。
4. **bottom-up 无杠杆 β（Hamada）**：`β_u = β_L / (1 + (1−t)·(D/E))`，`t=0.21`（美国法定税率）；同业列表来自 FinanceDatabase，逐 peer β 与 D/E 来自 yfinance；**取中位**（抗离群，不用均值）。**<3 家同业或 β 不可得 → 返回 `None`（绝不伪造）**；`BOTTOM_UP_BETA=0` 可关；`offline=True` 不触碰任何 lister。
5. **接线为 add（不覆盖 CAPM）**：bottom-up β 写入 `MarketData.industry_beta` → 由 `wacc.py::WaccBreakdown.beta_transparency_note()` 展示为**独立审计输入**，**不改 CAPM 标量 β**（回归 β 仍 winsorized [0.30, 2.50]）。taxonomy 保持 additive shadow。
6. **可注入 + 优雅降级**：三个外部库均 **optional import**（库未装或断网 → 该层返回 `{}`，不抛异常、不阻断主流程）；测试全部用 monkeypatch 离线化，保证 CI 确定性。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 不再单依赖被 401 的 Yahoo `assetProfile`；硬规则命中率 **75% → 78.3%**，SEC 层实测 **10/10 精确** | 78.3% 仍未达 90%——剩余 5 只（ASML/QCOM/MSFT/XOM/BRK-B）是**真值/粒度差**而非 `None` 缺口，需 M-16（阈值复评）+ C-02（真实标注重训） |
| SIC 桥接带「可消费」守卫，杜绝无效 industry 污染链路 | 三源均为 optional import + 网络依赖，首次解析有延迟（已用 `_MEM` + 磁盘缓存缓解） |
| bottom-up β 空槽位被唤醒（Semis 实测 β_u=1.2447），可审计 | 当前仅作展示，未参与 CAPM；升级为 CAPM 输入须单独审阅收敛差异 |
| `asset management` 映射补齐，消除 SEC SIC 6726/67 的唯一硬规则覆盖缺口 | 需随 Yahoo/SEC 分类表变化维护 `sic_map.py`（约 180 精确 + 68 类 + 130 关键词） |

---

## ADR-041: Bottom-up Beta 升级为「业务身份三级筛选 + 完整 β 链」，并接入 CAPM（M-34）
- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #25 / M-34)
- **Refines**: ADR-040（bottom-up β 从「按 industry 单一中位」升级）
- **Depends on**: ADR-039（taxonomy 五维：BusinessModel / EconomicProfile）
- **Constrained by**: ADR-019（`resolve_effective_beta()` 单一 β 出口）/ ADR-036（β 多窗口敏感性）
- **Closes**: TODO **M-34**（bottom-up β 升级为 CAPM 输入）；承接 ADR-040 的 Cons②（bottom-up β 当时不参与 CAPM）

### Context
- ADR-040 引入的 bottom-up β 用 `peers = get_companies_by_industry(industry)`：**同一 Yahoo industry 内的公司商业风险可能天差地别**（fabless 芯片设计 vs 重资产晶圆代工），单层筛选把异质同业混入中位。
- 该 β 当时仅作审计展示（`beta_transparency_note()`），**未参与 CAPM**——用户要求升级为「更接近公司真实商业风险」的折现率输入。
- 用户明确目标链：**Peer Levered β → Peer Unlevered β → Median Unlevered β → Cash-adjusted β → Target Relevered β**。

### Decision
1. **三级业务身份筛选**（`get_companies_by_business_identity(sub_industry, business_model, economic_profile)` 替换裸 `get_companies_by_industry(industry)`）：
   - **L1** 相同 **Sub-industry + Business Model**（有 `model_resolver` 时按模型过滤；无则用子行业全集并**显式声明未按模型过滤**，绝不冒充「同模型」）。
   - **L2** **相邻行业 + 相似经济特征**（同 sector 相邻行业，`profile_resolver` 提供同业 `EconomicProfile` 时按 `is_capex_heavy`/`is_loss_making`/`is_asset_light` 形状标志过滤；缺失不算不匹配）。
   - **L3** **Damodaran Industry Benchmark**（无足够同业时的静态兜底）。
2. **完整 β 链**：`Peer Levered β` → Hamada 去杠杆 `β_u = β_L/(1+(1−t)·D/E)` → **Median**（抗离群）→ **Cash-adjusted** `β_business = β_u/(1−Cash/Firm)`（剔除现金稀释，`Cash/Firm` 上限 0.90）→ **Target Relevered** `β_L = β_u·(1+(1−t)·D/E_target)`。CAPM 消费 **target-relevered** 值，中间步骤全量留痕于 `IndustryBetaResult`（`to_chain()`）。
3. **L3 数据 = 内置真实快照（绝不伪造）**：`data/damodaran_beta.json` 为 Damodaran 公开行业 unlevered β 表（**Jan 2026**，100 行业，含 `unlevered_beta` 与 `unlevered_beta_cash_adjusted`）；Yahoo industry → Damodaran 名经 `_DAMODARAN_ALIASES` 显式映射 + 归一（en/em-dash → hyphen）+ 精确匹配兜底。**文件缺失或行业未覆盖 → L3 返回 `None`**（不猜测）。
4. **接入 CAPM，但保持单一真源出口**：`wacc.py::calculate()` 的 β 采用**三段优先级**——① 有 bottom-up（已 cash-adjusted + target-relevered）即用（仍 winsorize 至 [0.30, 2.50]）→ ② 缺失回退**回归 β**（winsorized）→ ③ 都无则 `default_unlevered_beta`。三处（market/risk/WACC）继续共用 `resolve_effective_beta()`，**不破坏 ADR-019 单源真理**。
5. **`clamped` 语义修正**：`clamped` 现仅表示「**原始回归 β** 超出 CAPM 带」——避免 M-34 选用 bottom-up β 时被误报为「回归 β 被截断」。
6. **默认与可关**：`BOTTOM_UP_BETA=0` 关闭；缓存 key 含 `business_model`（`{sector}|{ind}[|{model}]`），仅缓存 peer-dependent 部分，target relever 每次现算（因公司 D/E 各异）。
7. **Segment-level β 为后续演进**（多业务公司按业务价值/权重整合；本会话不实现，登记于 ROADMAP）。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 同业按**业务身份**而非粗行业聚合，β 更贴近真实商业风险；L1 不足自动 L2/L3 降级 | L2 依赖同业 `EconomicProfile` 解析器，真实数据接入前仅按行业相邻（已显式声明） |
| 完整链全量留痕（levered/unlevered/median/cash-adjusted/relevered）+ `to_chain()` 审计快照 | L3 快照需随 Damodaran 年度更新（bundled JSON，版本化 `as_of`） |
| CAPM 优先 bottom-up、缺失回退回归 β；golden 因离线 `bottom_up_beta=None` **零漂移** | Segment-level β 未实现（多业务公司仍是公司级 β） |
| 20 用例锁定（三级筛选 / cash-adjust / relever / L3 基准 / to_chain / CAPM 优先级）；pytest **333 → 353** | — |

---

## ADR-042: 分部收入数据层 (M-31) + Segment-level β——多业务公司按业务价值权重整合分部 β（M-35）
- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #26 / M-31 + M-35)
- **Refines**: ADR-041（bottom-up β 从「公司级单链」升级到「分部加权链」）
- **Depends on**: ADR-039（taxonomy `RevenueComposition` / `SegmentRevenue` 五维）
- **Closes**: TODO **M-31**（③ Revenue Composition 接入真实分部收入）+ **M-35**（Segment-level β）

### Context
- ADR-041 落地公司级 bottom-up β 后，**多业务/多元化标的**（BRK-B 保险+铁路+能源、GE 航空+能源、AMZN 电商+AWS）仍按**整个公司**求一个 β——把风险特征迥异的多个分部压成单一行业匹配，是当前 bottom-up β 的**最大剩余误差源**（TODO M-35 明确列为「最高优先级」）。
- TODO M-31 备注原假设「可复用 SEC XBRL `companyfacts` 取 `srt:ProductOrServiceAxis` 分部」——本会话**实测证伪**：AAPL `companyfacts` JSON 中 `Axis`/`ProductOrService`/`StatementBusinessSegments` 计数**均为 0**（companyfacts 仅含合并口径，**不含** dimensional 分部数据）。
- 用户确认范围与口径：**M-31 + M-35 全链**；分部 **label → 行业 → bottom-up** 映射；**按业务价值/盈利权重**加权。

### Decision
1. **M-31 分部收入数据层**（`data/segment_revenue.py`）：以 **FMP `revenue-product-segmentation`（v4 flat / v3 legacy）为主源**（需 `FMP_API_KEY`）；**无 key → `[]`，绝不伪造**；类级 `_MEM` + `.cache/segment_revenue.json` 磁盘缓存（可离线复放）。**SEC `companyfacts` 层明确排除**（实证无 dimensional 数据；如需 SEC 一手分部须整包 Financial Statement Data Sets 或 filing-instance XBRL 解析）。
2. **分部 → 行业**（`_default_segment_industry_resolver` + `_SEGMENT_INDUSTRY_KEYWORDS`）：启发式关键词映射（~65 条，具体优先）到 Yahoo 行业；**未命中 → 该分部丢弃（不猜测）**。
3. **分部 → β_u**：每个分部的行业经**复用 M-34 三级筛选链**（`derive_bottom_up_beta`）求分部 unlevered β（同业去杠杆 → 中位 → cash-adjust）。
4. **权重 = 业务价值优先**（`segment_weights(by="value")`）：所有可用分部均有 `operating_income>0` → 按**营业利润占比**加权；否则回退**收入占比**加权；返回归一到 1.0 的 `[(label, weight)]`。
5. **整合链**（`derive_segment_level_beta`）：`β_u_company = Σ (w_i / coverage)·β_u_i`（权重在**可解析子集**上重归一）→ `_cash_adjust`（Cash/Firm）→ target-relever；输出 `level=0` / `source="segment-weighted"`，逐分部明细落 `IndustryBetaResult.segments`（审计）。
6. **门控（绝不伪造 + 透明回退）**：可解析分部 `< min_segments(2)` 或覆盖权重 `< _MIN_SEGMENT_COVERAGE(0.60)` → 返回 `None` → `derive_bottom_up_beta(segments=...)` **透明回退公司级链**（golden 离线无分部数据 → **零漂移**）。
7. **taxonomy 消费端**：`FinancialData.revenue_composition`（`Optional[Any]`，避免循环 import）由 providers 落值，`build_taxonomy_profile` 读取（缺失 → 显式 `unavailable`）。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 多业务公司按**分部 β × 业务价值权重**整合，比公司级单链更贴近真实风险结构 | M-31 依赖 `FMP_API_KEY`（无 key → 回退公司级，分部数据缺省） |
| 权重口径透明（营业利润优先、回退收入）、逐分部审计留痕（`segments`） | 分部→行业为启发式关键词映射，冷门/自定义 label 未覆盖 → 丢弃 |
| 门控 + 零漂移（无分部 → 走旧路径，golden 不变）；`level=0` 可区分 | SEC 分部数据未接入（companyfacts 无 dimensional；需 Financial Statement Data Sets / filing XBRL） |
| 23 用例锁定（分部加权数学 / 门控 / cash-adjust+relever / 优先分支 + 回退 / 权重口径）；pytest **353 → 376** | — |

### Key correction（避免重复踩坑）
> **SEC `companyfacts` 不含分部（dimensional）数据**——AAPL 实测 `Axis`/`ProductOrService`/`StatementBusinessSegments` 计数均为 0。M-31 遂以 FMP 为主源。后续若需 SEC 一手分部，必须换用整包 **Financial Statement Data Sets** 或 **filing-instance XBRL** 解析，**不要再尝试 companyfacts**。

---

## ADR-043: M-35 收尾——FMP 多 key 轮换 + `/stable` 新端点 + Shape C 解析 + 分部→行业关键词表数据驱动补全
- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #27)
- **Refines**: ADR-042（M-31 分部收入层的数据源实现：端点/形状/鉴权）
- **Closes**: TODO **M-35 收尾迭代**（新登记 M-36）

### Context
- 用户提供**两个 FMP API Key**（写入 `.env`：`FMP_API_KEY=key1,key2`），并要求以真实分部语料**数据驱动补全**「分部 label → 行业」关键词表。
- 实测发现两处必须修复的现实约束：① 原代码把 `FMP_API_KEY` 整串当**单一 key** → `key1,key2` 会鉴权失败；② FMP `/api/v4/...` 与 `/api/v3/...` 遗留端点**自 2025-08-31 起返回 403 `Legacy Endpoint`**（仅遗留订阅可用）→ 分部收入须改用 **`/stable/revenue-product-segmentation`**；③ `/stable` 响应为**新 Shape C**（`[{...,"fiscalYear":..,"period":..,"date":..,"data":{label:val}}]`）——元数据在外层、分部在嵌套 `data`，旧 Shape A 解析会把 `fiscalYear`/`period` 误当分部。
- 关键词表原为启发式手工词表，与真实 label 分布脱节（真实语料覆盖仅 102/172）。

### Decision
1. **多 key 轮换**（`_fmp_keys()` + `_from_fmp()`）：`FMP_API_KEY` 支持逗号分隔多 key（strip 空白），**按序尝试**；某 key 返回非 200 或响应不可解析 → 透明落到下一 key；**全部耗尽 → `[]`**（绝不伪造）。
2. **端点迁移 + 层优先序**：新增 `_FMP_STABLE`，层优先序改为 **`_from_fmp_stable` → `_from_fmp_v4` → `_from_fmp_v3`**（legacy 保留为薄封装，兼容遗留订阅）。
3. **Shape C 解析**（`_extract_fmp` 新增分支）：仅取嵌套 `data` 的 `label→数值`，`date` 作 `as_of`；外层元数据（`fiscalYear`/`period`/`symbol`）**绝不泄漏为分部**。
4. **关键词表数据驱动补全**：以真实 FMP 语料（90 只多业务大票 → 41 只解析成功 → **172 distinct label**）驱动 `_SEGMENT_INDUSTRY_KEYWORDS` **两轮扩充**；**只增不改**（保 golden 零漂移），覆盖 102 → 107。
5. **恒不映射（丢弃优先，绝不猜测）**：非分部桶（`Other`/`Corporate`/`…and Eliminations`/XBRL reconciling）、地理区域、发行人专属**药品品牌名**、发行人**缩写**——保持不映射，交由公司级 β 透明回退（对单业务发行人为正确结果）。
6. **留存发现工具**：`_discover_segment_labels.py` + `_segment_labels_discovered.json` 作为长期增量迭代工具（不自动写入映射，映射仍为显式审阅步骤）。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 双 key + 限速/失效自动轮换，在线分部数据可用性提升 | 关键词覆盖仍有上限（107/172）；残余须靠增量语料迭代 |
| 迁至 `/stable` 后遗留端点 403 不再阻断分部数据 | 若 FMP 再改响应形状，需同步 `_extract_fmp`（已加「元数据不泄漏」断言降低回归风险） |
| Shape C 解析杜绝 `fiscalYear` 污染分部；测试锁定 | `FMP_API_KEY` 未落盘 `.env` 时仍回退 `[]`（诚实缺省） |
| 关键词只增不改 → golden **零漂移**；「恒不映射」清单显式化 | — |
| 用例锁定（Shape C / `/stable` 优先 / 多 key 轮换）；pytest **376 → 382** | — |

---

## ADR-044: 商业理解层（Business Intelligence Layer）六模块映射 + 四态决策契约 + Identity Resolution
- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #28)
- **Depends on**: ADR-039（内部标准 Taxonomy 五维拆解）/ ADR-040（三源 sector/industry 链）/ ADR-041（bottom-up β 三级筛选）/ ADR-042（分部收入 + Segment-level β）
- **Constrained by**: ADR-039 黄金法则（经济学只能族内细化 Identity）/ 「绝不伪造」纪律

### Context
- 用户提交《最终确定的五维分类体系》提案，要求把项目正式化为 **Universal Business Taxonomy & Intelligence Engine**（商业理解层），并给出**六模块划分**：`identity_resolver` / `industry_taxonomy` / `business_intelligence` / `classification_resolver` / `economic_profile` / `peer_selection`（ML 保留独立 `ml_classifier.py`，不并入 Resolver）。
- 逐项对照现有代码发现：提案约 **70% 已落地**——五维拆解（ADR-039）、三源数据链（ADR-040）、bottom-up β 三级筛选 + Segment-level β（ADR-041/042）、Valuation Router（`models/router.py`）均已存在。
- **真实缺口**有三：① 全项目**无 Identity Resolution 层**（CIK/SIC/FIGI 无统一出口，无 OpenFIGI）；② 全项目**无 Business Evidence 收集器**（业务描述 / 分部收入证据散落在 `provider` 与 `segment_revenue`，无 provenance 汇聚层）；③ 分类裁决**只有 `ConflictKind`（信号如何相关），缺「该不该据此行动」的决策态**（用户提案的 CONFIRMED/PROBABLE/AMBIGUOUS/INSUFFICIENT_DATA 四态）。
- 用户三项决策（AskUserQuestion）：范围＝**按 6 模块重构**；命名＝**保留现名、正式化「商业理解层」**；形态＝**不重组、原位扩展（推荐）**。（前两项存在张力，故以「原位扩展」为执行方式，构建完整 6 模块**表面**：缺失模块新建、既有逻辑不迁移、新模块仅做薄封装/新能力，从而既得到 6 模块架构又不破坏 import 与 golden 基线。）

### Decision
1. **六模块映射（原位扩展，不迁移既有逻辑）**：
   | 提案模块 | 落地位置 | 形态 |
   |----------|----------|------|
   | `identity_resolver.py` | `data/identity_resolver.py` | 🆕 新建 |
   | `industry_taxonomy.py` | `classification/taxonomy.py` | 既有（ADR-039） |
   | `business_intelligence.py` | `classification/business_intelligence.py` | 🆕 新建 |
   | `classification_resolver.py` | `classification/taxonomy.py::reconcile_identity` + `decide_status` | 既有点位扩展 |
   | `economic_profile.py` | `classification/taxonomy.py::derive_economic_profile` | 既有 |
   | `peer_selection.py` | `data/industry_beta.py::get_companies_by_business_identity` | 既有（ADR-041） |
   ML 分类器保持独立 `classification/ml_classifier.py`，**不并入 Resolver**。
2. **四态决策契约 `DecisionStatus`**（`classification/taxonomy.py`）：把「信号如何相关」（`ConflictKind`）与「能否据此行动」（`DecisionStatus`）**分离**——`CONFIRMED`（可靠证据一致 → 自动通过）/ `PROBABLE`（较强证据 → 可估值、保留标记）/ `AMBIGUOUS`（重要证据冲突 → 扩展分析或审核）/ `INSUFFICIENT_DATA`（缺可靠数据 → 不强行分类）。映射函数 `decide_status(conflict_kind, identity_source, *, ml_confidence)` 为**确定性、无标的特例**：`INSUFFICIENT→INSUFFICIENT_DATA`；`IDENTITY_WINS→AMBIGUOUS`；`ECONOMICS_ONLY→PROBABLE`（当 `ml_confidence ≥ _ECONOMICS_ONLY_MIN_CONF=0.55`）否则 `AMBIGUOUS`；`REFINEMENT→PROBABLE`；`CONSISTENT` 且 identity 源于**结构化外部事实**（`yahoo_industry*`）→ `CONFIRMED`，仅自由文本 → `PROBABLE`。
3. **Identity Resolution 层**（`data/identity_resolver.py`）：`IdentityResolver.resolve(ticker) → ResolvedIdentity`（`cik`/`sic`/`sic_description`/`figi`/`sector`/`industry` + `sources` + `provenance()`）——**Layer A** 复用在位 SEC 链（新增 `SectorIndustryResolver.resolve_identity()`，避免重复抓取）；**Layer B** OpenFIGI 仅在 `OPENFIGI_API_KEY` 存在时调用（`offline` 时跳过）。**缺失字段一律 None，绝不伪造**。设计把「identity（这是谁）」与「classification（做什么）」分层。
4. **Business Evidence 收集器**（`classification/business_intelligence.py`）：`extract_business_evidence(data) → BusinessEvidence`（`description` + `revenue_segments` + 各自 `*_source` + `provenance()`）——证据缺失**显式标注为缺失**（`notes`），使下游可诚实输出「数据不足」而非猜测。证据来源：provider 业务描述（`MarketData.description` ← Yahoo `longBusinessSummary`）+ 分部收入（`FinancialData.revenue_composition` ← M-31）。
5. **additive shadow 接线**：`BusinessTaxonomyProfile` +`decision_status` 字段、`audit_lines()` 追加「◆ 决策状态」、`attach_taxonomy_profile()` 写 `profile.taxonomy_decision_status`；`CompanyProfile` +`taxonomy_decision_status`。**不改 `business_type`/`applicable_models`/路由** → golden 零漂移。
6. **三条架构原则写入设计（用户明确要求）**：① 不允许单一数据源直接覆盖内部分类（→ taxonomy 为仲裁层，外部标签原样保留于 ⑤）；② 不允许 ML 错误分类直接影响 WACC 与估值模型（→ ML 只是证据之一，`decide_status` 中 `ECONOMICS_ONLY` 需置信度门控，路由仍由 taxonomy/Valuation Router 决定）；③ 不允许缺收入证据的公司被强赋高置信度（→ `BusinessEvidence` 缺失显式化 + `INSUFFICIENT_DATA` 态）。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 六个模块表面齐备，但**既有逻辑零迁移** → import 与 golden 基线不受扰动 | `classification_resolver.py` / `economic_profile.py` / `peer_selection.py` 仍是「点位」而非独立文件（原位扩展的代价；如需物理拆分须单独审阅） |
| 四态决策契约把「信号相关」与「能否行动」解耦，渲染层可据枚举分支（延续 ADR-024 契约化） | 四态当前为 **shadow 字段**，尚未参与路由（同 M-32 的取舍：待 golden 有意漂移审阅） |
| Identity Resolution 提供稳定监管锚（CIK/SIC/FIGI），可被 taxonomy/peer/provenance 引用 | OpenFIGI 需 key 方生效；无 key → FIGI 恒 None（诚实缺省，符合「绝不伪造」） |
| Business Evidence 显式化缺失 → 诚实「数据不足」而非虚假高置信 | 10-K/20-F XBRL 业务抽取**未做**（本次仅提供证据收集器；SEC `companyfacts` 无 dimensional 数据，须整包 XBRL） |
| 三条架构原则结构化落地，与 ADR-039 黄金法则一致 | — |
| 用例锁定（`TestDecisionContract` 7 + identity_resolver 5 + business_intelligence 4）；pytest **382 → 398**；golden **零漂移** | — |

---

## ADR-045: SEC 分部（dimensional）数据必须走 filing-instance XBRL 解析——`companyfacts` 无维度，且必须以「单轴 + 排除合并总额 + 最新期间」防重复计数（M-38）
- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #29 / M-38)
- **Depends on**: ADR-042（分部收入数据层 M-31 + Segment-level β M-35）/ ADR-044（商业理解层：`BusinessEvidence` 收集器已就绪，缺一手 filing 解析）
- **Constrained by**: 「绝不伪造」纪律（无 CIK / 无实例 / 解析失败 → `[]`）/ additivity（不改 `business_type`/路由，golden 零漂移）

### Context
- Session #28 的 ADR-044 诚实记录了真实缺口：`classification/business_intelligence.py` 的 `BusinessEvidence` 收集器已就绪，**但缺一手 filing 解析**——即 10-K / 20-F 里的分部（segment）业务证据。用户确认推进 **M-38**。
- 关键实测事实（承 ADR-042）：**SEC `companyfacts` JSON 不含 dimensional（axis/member）数据**（AAPL `Axis` / `ProductOrService` / `StatementBusinessSegments` 计数均为 0）→ 该端点**不可用于分部拆解**。
- 因此一手分部只有两条路：**整包 Financial Statement Data Sets**（全量历史、体量巨大）或 **filing-instance XBRL**（10-K/20-F 内嵌 `*_htm.xml` 实例文档，按 filing 增量取）。M-38 选后者。
- 目标：当 FMP 无 key / 不可用时，仍能给出**权威（SEC 监管源）**的分部收入份额，供 taxonomy ③ Revenue Composition 消费；且**不扰动**既有 `segment_revenue` / β 管线。

### Decision
1. **数据源端点链**（`data/filing_evidence.py::FilingBusinessExtractor`）：`company_tickers.json` → CIK → `data.sec.gov/submissions/CIK{cik}.json` 的 `filings.recent`（数组 **newest first**）→ 取**首个 `10-K` / `20-F`** → filing `index.json` → `_pick_instance()` 优选 `*_htm.xml` 实例文档（排除 `r\d+.xml` 与 `*_cal|def|lab|pre|ref.xml`）。**绝不使用 `companyfacts`**。请求带合规 `User-Agent`（`SEC_USER_AGENT` 可配）。
2. **`parse_segment_revenue(xml_text)` 为纯函数**，解析规则严格：
   - `xbrli:context` → `(endDate, axis, member)`：`xbrldi:explicitMember@dimension` 识别 segment 轴，member 去 `Member` 后缀（`_humanize`）。
   - **仅取带 segment 轴的事实**：无轴（合并口径）一律跳过 → **绝不把合并总额计入分部**。
   - **单轴**：按 `_AXIS_PRIORITY`（`StatementBusinessSegmentsAxis` > `ProductOrServiceAxis` > ifrs `SegmentsAxis` > `StatementGeographicalAxis`）取**第一条**有数据的轴聚合 → **混轴会重复计数，故禁止**。
   - **取最新期间**：同一 member 跨多个 duration 时只保留最新 `endDate` → 避免上年同期被重复累加。
   - **instant context 一律忽略**：分部收入是 duration 概念，须要求 `endDate`；否则资产负债表数字会被误当收入。
   - Revenue concept 集合覆盖 us-gaap（`Revenues` / `RevenueFromContractWithCustomerExcludingAssessedTax` / `SalesRevenueNet` …）与 **ifrs-full**（`Revenue` / `RevenueFromContractsWithCustomers`，20-F 使用）。
3. **drop-in 兼容**：`get_segments()` 返回既有 `segment_revenue.Segment` 列表 + `source="sec-xbrl"`，可直接喂 `to_revenue_composition()` / taxonomy ③，**零扰动**既有管线。
4. **绝不伪造 + 可离线**：无 CIK / 无实例 / 解析失败 / malformed XML → `[]`（空列表，不猜）；`_MEM` + `.cache/filing_evidence.json` 磁盘缓存；`offline=True` 时**零网络调用**。
5. **四态决策端到端测试**（同步交付）：`tests/test_taxonomy.py::TestDecisionContractEndToEnd` 用**真实 `build_taxonomy_profile` / `attach_taxonomy_profile` / ML 标签**跑全链路，断言 `CompanyProfile.taxonomy_decision_status`（Session #28 的 shadow 字段）确实被写入且多原型（NVDA/MSFT/JPM/PLD）状态合法——把四态契约从「单元级」升级为「端到端」锁定。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 补齐提案中「10-K/20-F 业务证据」真实缺口；提供**不依赖付费 key** 的权威（SEC）分部来源 | filing-instance 解析较 FMP JSON 复杂（需 XBRL 上下文/维度解析），且仅取最新一期（无历史时间序列） |
| 「单轴 + 排除合并总额 + 最新期间 + 忽略 instant」四重防重复/污染规则，避免分部口径失真 | 分部原始 label → 行业映射（`_SEGMENT_INDUSTRY_KEYWORDS`）**尚未接入**，需随语料补全 |
| drop-in 设计（复用 `Segment` + `source="sec-xbrl"`）→ 零扰动接入既有 taxonomy ③ / β 管线，golden 零漂移 | 当前为**独立入口**，尚未在 `data/providers.py` 主链自动接线（未在 FMP 缺 key 时自动回退） |
| 纯函数 `parse_segment_revenue` 可离线单测；`offline` 零网络 | SEC 速率限制需合规 `User-Agent` + 缓存（已实现 `_MEM` + 磁盘） |
| 四态契约端到端锁定，shadow 接线不再可能静默断开；pytest **398 → 413**，Ruff clean，golden 零漂移 | taxonomy / 四态仍为 shadow（参与路由 M-32 待 golden 有意漂移审阅） |

---

## ADR-046: 分部收入走「生产默认源链」——FMP 为主、SEC filing-instance XBRL 为免 key 回退，两层皆空才返回空（M-39）
- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #30 / M-39)
- **Depends on**: ADR-042（分部收入数据层 M-31：FMP 主源）/ ADR-045（M-38：SEC filing-instance XBRL 抽取，drop-in `source="sec-xbrl"`）
- **Constrained by**: 「绝不伪造」纪律（两层皆空 → `[]`）/ additivity（不改 `business_type`/路由，golden 零漂移）

### Context
- ADR-045 交付了 `data/filing_evidence.py`（SEC 10-K/20-F filing-instance XBRL 分部抽取），但**仅作独立入口**：未在 `data/providers.py` 自动调用，FMP 无 key / 失效时收入结构会丢失。
- 用户要求把 M-38 从「可用入口」升级为「生产默认路径」：FMP 缺 key / key 失效 / 额度耗尽 / ticker 未被覆盖时，自动回退到免 key 的 SEC 权威源；且**不触碰 golden 基线**（仍 shadow 数据填充）。

### Decision
1. **单一源链入口 `resolve_segments(ticker, *, client, offline, fmp_cache_path, filing_cache_path, identity_resolver)`（`data/segment_revenue.py`）**：**Layer 1** FMP `revenue-product-segmentation`（需 key）→ 非空即返回；**Layer 2** SEC 10-K/20-F **filing-instance XBRL**（`FilingBusinessExtractor`，免 key、权威）。两层皆空 → `[]`。**绝不伪造**。
2. **惰性 import 避免循环依赖**：`segment_revenue` 不在模块顶层 import `filing_evidence`（后者从 `segment_revenue` 取 `Segment`），改为在 Layer 2 分支内 `from data.filing_evidence import FilingBusinessExtractor`；import 失败即安全返回。
3. **`data/providers.py` 改调源链**：分部收入采集由「直接调用 FMP resolver」改为 `resolve_segments(ticker)`，使 FMP 缺 key / 失效 / 未覆盖时**自动降级**到 SEC 一手分部。
4. **保持 shadow 数据填充**：结果仅落 `FinancialData.revenue_composition` / 分部 β 权重，**不改** `business_type` / `applicable_models` / 路由 → golden 指纹零漂移。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| FMP key 缺失 / 失效 / 额度耗尽时不再丢收入结构，改由免 key 的 SEC 权威源兜底 | 两条源口径不同（FMP 商业分部 vs SEC 申报分部），同一标的可能随源不同而分部标签不同 |
| 惰性 import 规避循环依赖，且 `offline` 时两层皆零网络 | SEC 层仅取最新一期（无历史时间序列），且受 SEC 限流约束（已带合规 `User-Agent` + 缓存） |
| 仍为 shadow 数据填充 → 主链接线不改路由，golden 零漂移 | 原始分部 label → 行业映射（`_SEGMENT_INDUSTRY_KEYWORDS`）未覆盖部分需公司级 β 透明回退 |

---

## ADR-047: Taxonomy 参与路由采用「跨族冲突才覆盖 + 经济护栏」的窄门——对比内部身份判定 `best_bt`，零重生成 golden（M-32）
- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #30 / M-32)
- **Depends on**: ADR-039（内部标准 Taxonomy + 黄金法则）/ ADR-044（四态决策契约 `DecisionStatus`）
- **Constrained by**: 用户口径（切换 = CONFIRMED + 尊重经济特征护栏 / golden = 不重生成、保持零漂移 / gating = 跨族冲突才覆盖 + 护栏）

### Context
- 自 Session #23 起 taxonomy 一直是 **additive shadow**：写入 `CompanyProfile` 八个字段，但**不参与** `business_type` / 模型路由（ADR-039）。M-32 要求把它切换为**参与路由**。
- 直接切换会让 18 只 golden basket 中若干标的的 `business_type` / `applicable_models` 漂移，需逐字段审阅。用户明确要求 **不重生成 golden**（保持零漂移），同时 taxonomy 必须真正参与路由。
- 冲突点：`Orchestration`（taxonomy canonical key `tech.software.infra` → archetype `SaaS`）与内部判定 `MatureTech` 同为 `tech` 族——若一律覆盖，ORCL/NBIS/CRWV 等会漂移。
- 另有陷阱：classifier 的 `routing_bt` 是 Phase 1.3 ambiguous 时**保守估值路由**（GOOGL 会取 `TELECOM`），**不是身份声明**；若 gate 对比 `routing_bt`，`TELECOM` 与 `tech.internet(MatureTech)` 跨族 → GOOGL 被误覆盖。

### Decision
1. **三道 gating（`taxonomy_routing_override(internal_bt, taxonomy_key, decision_status, *, guard_blocked=False)`）**：
   - ① `decision_status ∈ TAXONOMY_ROUTING_STATUSES`（**`={CONFIRMED}`**，多源一致才允许覆盖）；
   - ② canonical 身份与**内部身份判定 `best_bt`** **跨 identity family** 冲突（`same_identity_family()` 为真 → **不覆盖**；同族差异如 `MatureTech` vs `SaaS` 都属 `tech` 族，归经济驱动分类器所有）；
   - ③ `guard_blocked=True` → 拒绝（claim 资产轻却 `capex/营收 ≥ 1.0` 且负 FCF 的重资本建设）。
   三道全过才返回 canonical 节点 archetype，否则 `None`（保留内部路由）。
2. **对比 `best_bt` 而非 `routing_bt`**：gate 必须以**身份判定**为准；`routing_bt` 是保守估值路由，不能读作身份主张（修复 GOOGL 误覆盖）。
3. **`ARCHETYPE_FAMILIES` 由 `IDENTITY_NODES` 树推导**（`_archetype_family_index()`）：`archetype → frozenset(family)`，保证 archetype 与 node tree **永不漂移**；`UNKNOWN` 无族 → taxonomy 可补位。
4. **双路径接线 + 一次构建复用**：`classifier.py`（规则路径）在 `_model_applicability()` **之前**构建 `_taxonomy` 并 gate；`ml_classifier.py`（ML 路径）对称接入（economics 用 **raw ML top-1**，预 sector 硬规则，以保留统计/原型冲突信号）；`attach_taxonomy_profile(..., tp=_taxonomy)` 复用同一 profile，避免重复构建。
5. **零重生成**：同族差异不覆盖 → 结构性排除 18 只 basket 的漂移风险，`UPDATE_GOLDEN` **不执行**。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| taxonomy 真正参与路由，但门足够窄 → 只有「跨族 + CONFIRMED」才覆盖，可审计 | 同族内的身份细化（如 `MatureTech` → `SaaS`）仍由经济驱动分类器决定，taxonomy 不介入（有意，非缺陷） |
| 对比 `best_bt` 修正了 GOOGL 因保守 `routing_bt` 被误覆盖的缺陷 | 若未来 `best_bt` 语义变更，gate 需同步审阅 |
| `ARCHETYPE_FAMILIES` 由树推导 → archetype 与节点树不漂移 | 经济护栏阈值（`ASSET_LIGHT_CONFLICT_CAPEX_RATIO=1.0`）沿用既有常量，语义边界须与 `ml_classifier.py` 保持一致 |
| **零重生成 golden**（用户口径）+ pytest 413 → 429，Ruff clean | 只 gate `business_type`；`applicable_models` 等下游随之联动（已由 golden invariant 断言） |

---

## ADR-048: 市场隐含预期超出 sanctioned band → 结构化 bound；Growth Risk 用下行离散度；隐含 WACC 以 Rf 为下限（Session #31–#33）
- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #31 / Round 1 → #33 / Round 3)
- **Depends on**: ADR-030（约束式单变量求解）/ ADR-032（Rf 单一真源）/ ADR-024（口径契约化）
- **Constrained by**: 用户偏好「反对伪精确 / 反对绝对值化制造正向信号 / 风险等级必须如实传导 / 数学诚实性」

### Context
- 用户给出 50 只跨行业蓝筹，要求验证「分类 / 模型分配 / 估值方法 / 特殊情形 / Reverse DCF 市场隐含预期」并执行 **3 轮递归自我改进**（上一轮产出 → 定位缺陷 → 修码 → 重跑）。
- **Round 1**：市场价常落在业务类型 sanctioned growth band 之外（如低增长公用事业被市场 price-in 出高增长），此时求解器若强行在 band 内给点估 = 伪精确。
- **Round 2**：同一「市场隐含预期」在报告两处渲染（`_implied_section` 与 `_gap_section`）口径不一致（一区有 bound、一区 N/A），自相矛盾。
- **Round 3**：
  - Growth Risk 用 `CV=σ/|μ|` 时，μ→0 的受管制公用事业（SO：μ≈0.9%、σ≈10.5pp → CV≈11.9）被误报 High；改用总 σ 后，单调收购爬坡（PLD 6.0→8.8bn、VICI 2.6→4.0bn）又被当波动风险。
  - 隐含 WACC 反解出 **低于 Rf** 的值（DUK 2.3% / SO 2.7% / CEG 3.3%），等价于「负风险溢价」——going-concern 折现率经济上不自洽。

### Decision
1. **结构化 bound 而非伪点估（Round 1）**：市场价超出 sanctioned growth band 时，`models/reverse_dcf.py` 输出 `implied_revenue_cagr_bound={kind, value, ev_at_bound}`——`above_band_ceiling` → 报告「≥ 上限」+ 该边界对应 EV；`below_band_floor` → 「≤ 下限」+ 边界 EV。**normalized 救援仅在 `bridge_broken`（桥断裂）时启用**，不作为「凑出 band 内数字」的手段。
2. **bound 数据源单一（Round 2）**：把 bound 结构化落进 `ExpectationGap`（`implied_revenue_cagr_bound` / `implied_revenue_cagr_is_bound`）并透传，`_gap_section` **镜像** `_implied_section` 的措辞 → 同一标的（PG）端到端一致。
3. **Growth Risk = 下行离散度（Round 3）**：`analysis/risk.py::_growth_risk()` 用 `dd = RMS(min(growth, 0))`（相对 0 的半离差），只捕捉「营收收缩的幅度与频率」；`config.py` 阈值 `growth_dd_medium=0.05` / `growth_dd_high=0.10`。**丢弃** `CV=σ/|μ|`（μ→0 爆炸）与总 σ（把成长当波动）。
4. **隐含 WACC 以 Rf 为下限（Round 3）**：`models/dcf.py::_estimate_wacc_breakdown()` 暴露 WACC **实际使用的** Rf（单一真理源），`models/reverse_dcf.py` 以 `wacc_lo = max(cfg, tg + MIN_WACC_TG_SPREAD, Rf)` 求解；目标 EV 连 Rf 都够不到 → `NO_SOLUTION_IN_RANGE` 并把下限写进 `implied_wacc_floor_rf`（**命名约束，不伪造**）。
5. **可断言的迭代产出**：`_batch_eval.py`（50 标的 → JSON）+ `_audit_summary.py`（五问）作为每轮回归门（`50/50 = 100.0% | routing_viol=0 | defects=0`）；golden 因 Round 2/3 行为修正**二次有意重生成**，差异**全部为 Growth Risk 移除/降级**（逐条核对为行为修正，非回归）。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 市场价超出可定价区间时输出诚实 bound 而非伪点估（符合用户反对伪精确的偏好） | 报告读者需理解「≥/≤ + ev_at_bound」语义（已由 dashboard 文案说明） |
| Growth Risk 只反映真实收缩风险 → SO High→Medium，PLD/VICI/CEG/AMT 假旗标消失 | 下行离散度对「高位回落后企稳」的正常化不敏感（可后续引入趋势剔除） |
| 隐含 WACC ≥ Rf 保证折现率经济学自洽（无负风险溢价） | 部分标的因下限约束转为 `NO_SOLUTION_IN_RANGE`（诚实无解，而非伪造） |
| 每轮一行回归门 + golden diff → 递归改进可断言、可复现 | golden 二次重生成需逐条审阅（已核对全部为旧旗标移除/降级） |

---

## ADR-049: 用户代码审查 4 项 P0——行业 WACC 用身份键（非子串）/ ETR 非重叠口径 / 股数口径可比性契约 / FCF Yield 非对称风险（Session #34）
- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #34)
- **Depends on**: ADR-001（WACC 7 步法）/ ADR-024（口径契约化）/ ADR-026（短 token 词边界）/ ADR-028（负值不得符号翻转）/ ADR-039（Taxonomy 五维身份）
- **Constrained by**: 用户偏好「反对伪精确 / 拒绝为凑漂亮数字而掩盖口径冲突 / 风险方向必须如实 / 读数须可审计」

### Context
用户对当前引擎做代码审查，给出 4 个 **P0（必须优先修复）** 缺陷，均已定位到具体文件与函数：
- **P0-1**：`valuation/wacc.py` 的 `INDUSTRY_WACC_RANGES` 关键词为 `"Utility": (0.055, 0.080, "Utilities")`，但 Yahoo 的行业字段是 `"Utilities"` / `"Utilities—Independent Power Producers"`——`"utility"` **不是** `"utilities"` 的子串，`_match_industry_range()` 的 `if keyword.lower() in haystack.lower()` 永远不命中，**VST 落入 `DEFAULT_INDUSTRY_RANGE=(6.5%~11.5%, Market Average)`**（报告已出现）。更深的错误：不能把「受监管公用事业」与「独立发电商」当同一经济模型。
- **P0-2**：`_effective_tax_rate()` 把 `data.ttm` 与 `data.annual_income[:3]` **相加**——TTM 含最近四季度，最新年度重复计入 → 其税与 EBT **双重加权**，ETR 失真（报告出现 `ΣTax/ΣEBT over 4 period(s)`），并向下污染税后债务成本与 WACC。
- **P0-3**：DCF / Reverse DCF / Multiples / SOTP **各用不同股数来源**，却把不同口径的**每股估值当作同一单位**进入共识中位数（报告已出现「供应商股数与年报偏差 >25%」仍参与结论）。`reconciliation.py` 的股数保护（市值恒等式成立时不盲目覆盖）**本身正确**；**真正问题是「保护了股数，却没有阻止不同股数口径的估值结果被当成同一单位比较」**。
- **P0-4**：`analysis/risk.py` 用 `pos_fcf_gap = abs(fcf_yield - 0.04) / 0.04` **对称**度量偏差——正 FCF 且收益率 **高于** 4%（VST 5.03%）被误标 High；高收益率本非风险。

### Decision
1. **行业 WACC 区间 = 读身份键，不靠子串匹配（P0-1）**：
   - 关键词改为 `"Utilities"`（保留 `"Utility"` 兼容单数）；新增 `_normalize_industry_text()`（统一 em/en dash 与连字符空格）。
   - 新增 `CANONICAL_KEY_WACC_RANGES`：`util.electric`（受管制电力）/ `util.gas` / `util.water` / `util.ipp`（独立/商业发电——商品+电量风险、无 rate base，**区间刻意高于受管制**）/ `util.diversified` / `en.oil_gas.integrated` **各自独立区间**。
   - `_match_industry_range()` 四级优先级：**① profile 的 canonical key → ② `node_from_yahoo()` 解析 → ③ 关键词表（破折号归一化）→ ④ 默认区间**；返回第 4 元 `source`（`WaccBreakdown.industry_range_source`），dashboard 透传 → **默认区间回落可审计而非静默**。
2. **ETR 只用非重叠期间（P0-2）**：`_effective_tax_rate()` 改为 ① **TTM 模式**（TTM 有 tax+EBIT 时**只用 TTM**）；② **历史模式**（不重叠完整财年，按 `period_end` 去重）；③ 兜底法定默认。返回值升级为 `(etr, source, tax_period_basis)`，`tax_period_basis ∈ {ttm, fyN, default}` 落 `WaccBreakdown.tax_period_basis`——**明示 ETR 采用的口径，不再暗示泛化的「ΣTax/ΣEBT」**。
3. **统一股数口径契约 + 每股可比性校验层（P0-3）**：
   - `models/base.py` 新增 `ShareCountBasis`（BASIC/DILUTED/TTM/MARKET/UNKNOWN）+ `ShareCount`（`shares_used/shares_source/shares_as_of/shares_basis/shares_reliable`）+ `make_share_count()`；`ValuationResult.share_count` —— **每个模型输出必须申报其股数口径**。
   - `analysis/model_agreement.py` 新增 `_resolve_share_reference()`（`market_cap ÷ current_price` → MarketData 流通股 → TTM 股数 → 模型声明中位数）与可比性校验层：偏差 > `SHARE_COUNT_COMPARABLE_TOL=0.10` 的模型**降级可信度并剔除出共识中位数**（`share_incomparable_models` / `share_count_excluded_models`），`n_applicable` 相应扣减。
   - **保留 EV / Equity Value 为独立参考**；**绝不为了凑出漂亮的每股数字而把所有股数改成同一来源**；notes 显式列出「哪些模型因股数口径不可比被剔除 + 参考口径」。
4. **FCF Yield Gap = 非对称方向感知（P0-4）**：
   - 正 FCF 且 Yield ≥ 参考锚点 → **不因偏离判风险**（高收益率不惩罚）；正 FCF 且 Yield < 锚点 → 仅「估值偏高观察」（materiality gate：偏差 ≥ `positive_fcf_gap_medium=0.10` 才记 Low，接近锚点不触发）；**负 FCF** → 现金流风险**按恶化幅度与持续性**评估（`_fcf_trend()`：`cumulative_change` + `consecutive_declines`；`fcf_decline_medium=0.30` / `fcf_decline_high=0.60` / `fcf_decline_consecutive=2`）。
   - **4% 降格为可配置参考参数**（`fcf_yield_reference`），**不再作为全行业通用风险标准**；新增 `_downgrade()`（风险等级可降不可凭偏差升），保留 REIT / 高增长降权。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 行业区间由**身份**决定而非字符串巧合 → VST 类不再静默落入 Market Average；IPP 与受管制公用事业分属不同经济模型 | 需维护 canonical-key → 区间映射表（`CANONICAL_KEY_WACC_RANGES`），新增身份键时须同步 |
| ETR 不再重复加权 → WACC 及下游估值剔除系统性偏差 | 历史模式对财年数较少者样本更窄（但**口径统一**优先于样本量） |
| 每股估值口径冲突**显式命名并隔离**，不污染共识中位数；EV/Equity Value 仍独立可比 | 参考口径用市场价反推股数时，对多股权结构标的需注意（已按优先级回退） |
| 正 FCF 高收益率不再被误判为风险；风险只随**恶化**上升，方向诚实 | 偏向「低收益率=估值远望」的读法需在报告文案中说明（已注明为估值观察） |
| 四项修复均落**可审计字段**（`industry_range_source` / `tax_period_basis` / `share_count` / `fcf_yield_reference`） | golden 因行为修正**有意重生成一次**（差异全部为上述旗标/中位修正，逐条核对非回归） |

### Verification
- `python -m pytest -q` → **429 passed**（golden 因 P0-4/P0-2 行为修正**有意重生成一次**）。
- 定向核验：IPP `Utilities—Independent Power Producers` → `util.ipp` → `(6.5%, 9.8%, Independent Power Producer (Merchant))`；ETR 三种口径 basis = `ttm` / `fy2` / `default`；强制注入不可比股数时 P/E（30.4B vs 15.2B）被剔除、中位 132.19→123.99、`n_applicable == n_solved + n_failed` 恒等式成立；KR High→Medium、XOM/AAPL 假 FCF 旗标消失。

---

## ADR-050: 用户代码审查 4 项 P1——SOTP 三态状态机 / 多窗口 β 稳定性参与估计 / ETR 口径分离 / 估值可比性 Gate（Session #35）
- **Date**: 2026-11-14
- **Status**: ✅ Accepted & Implemented (Session #35)
- **Depends on**: ADR-024（口径契约化）/ ADR-031（β 多窗口敏感性暴露）/ ADR-038（ShareCountBasis 股数口径，同 ADR-049）/ ADR-041（反循环估值诚实原则）
- **Constrained by**: 用户偏好「反对伪精确 / 反对把市场估值按概率拆分伪装成独立证据 / 不确定性必须传导而非仅提示 / 输入数据与模型实际使用数据必须显式区分 / 不兼容模型可知情展示但不得无条件进入共识」

### Context
用户对当前引擎做第二轮代码审查，给出 4 个 **P1（高影响）** 缺陷：
- **P1-SOTP**：`models/sotp.py::_derive_segments_from_profile()` 在无独立分部数据时，用**公司自身** `ev/revenue` 作 `ev_rev_mult`（`max(0.5, min(10.0, ev/revenue))`）再乘回 `revenue` → Operating EV ≈ 当前市场 EV，再按 ML `business_exposures` 拆成多业务——**不是独立估值，而是先取市场估值再按概率分配**（循环估值）。用户明确：`SOTPModel.calculate()` 允许外部传入 `segments`，**不能仅凭 fallback 断言报告的 $75 一定是循环估值**（可能走了外部独立数据路径），需要**三态**区分；**绝不能把 ML 的 50% Utilities + 49.9% Energy 当成两个独立业务的估值证据**。
- **P1-6**：`valuation/wacc.py` 在无 bottom-up β 时优先用 3Y Monthly β 再 winsorize；多窗口 β（VST：2Y周 1.49 / 3Y月 2.30 / 5Y月 1.35，极差 0.95）**只用于展示，未参与稳健估计**。用户要求：bottom-up 优先；无之则以多窗口统计判稳定性；对极端差异加 shrinkage/confidence；输出 Raw/Selected/Adjusted β；β 不确定性**传导至 WACC 情景**。**明确反对简单取三窗口平均**（观测频率与样本长度不同）。
- **P1-7**：`reporting/dashboard.py::_market_section()` 读 `m.effective_tax_rate`（供应商 20.4%），WACC 用 `wacc_bd.effective_tax_rate`（19.634%）→ 报告出现**两个 ETR**。要求以 **WACC 实际使用 ETR** 为主，供应商值另标 **Provider ETR**。
- **P1-8**：`analysis/model_agreement.py` 的降权机制方向正确，但 VST 暴露：**模型各自成功解算 ≠ 使用可比较数据口径**（DCF 用 TTM 股数 / EV/EBITDA 用 Market / SOTP 用 Market / P/E 用 EPS）。要求增加 **Valuation Comparability Gate**：先校验 7 维（Share Count Basis / Currency / Valuation Date / Financial Period / EV-Equity Basis / Data Quality / Peer Validity），**不兼容可展示但不能无条件进入共识中位数**。

### Decision
1. **SOTP 三态状态机（P1-SOTP）**：
   - 新增常量 `SOTP_SOLVED` / `SOTP_APPROXIMATE` / `SOTP_INSUFFICIENT` 与 `SOTPSegment` dataclass（`is_independent_evidence()` / `as_dict()`）。
   - `_derive_segments_from_profile()` 不再用自身 EV/Revenue 制造「伪独立」Operating EV：**仅当分部具备真实收入/利润 + 独立 peer multiple → SOLVED**（计入共识）；**部分真实 + 部分估算 → APPROXIMATE**；**仅 ML 暴露度、无独立分部财务数据 → INSUFFICIENT**，`breakdown["display_only"]=True` 由聚合层剔除（不伪装证据）。
   - `breakdown["segments_detail"]` 输出每分部 **Revenue / EBITDA / EBIT / Applied Multiple / Segment EV / Source / Confidence / As-of Date**（可审计）。
   - 修复 `operating_ev` 对净债的**双重扣除** bug（`equity_value = total_ev - debt + cash` 仅一次）。
2. **多窗口 β 稳定性参与估计（P1-6）**：
   - `WaccBreakdown` 新增 `beta_raw`（供应商回归）/ `beta_selected`（winsorize 基础）/ `beta_adjusted`（最终用于 CAPM）/ `beta_shrinkage` / `beta_dispersion` / `beta_uncertainty`。
   - Blume-style 收缩：`beta_adjusted = selected + shrink × (1.0 - selected)`；`shrink = min(BETA_MAX_SHRINK, dispersion 超过 BETA_DISPERSION_SHRINK_THRESHOLD 的线性增量)`（`BETA_MAX_SHRINK=0.35`、`BETA_DISPERSION_SHRINK_THRESHOLD=0.50`）。**不取窗口平均**。
   - β 不确定性**传导至 WACC 区间**：`wacc_beta_lo`（窗口下沿）/ `wacc_beta_hi`（窗口上沿）重新定价，报告以区间呈现而非仅提示。
3. **ETR 口径分离（P1-7）**：`_market_section()` 主值改 `wacc_bd.effective_tax_rate`（含 `tax_period_basis`，经 `_etr_basis_suffix()` 标注）；供应商 `m.effective_tax_rate` 另标 **Provider ETR**——**明确区分「输入数据」与「模型实际使用数据」**。
4. **Valuation Comparability Gate（P1-8）**：
   - `models/base.py` 新增 `make_comparability(value_basis, currency, financial_period, valuation_date, peer_valid)`（`valuation_date` 归一化 ISO）+ `ValuationResult.comparability`；DCF / Multiples / SOTP 接线声明口径。
   - `analysis/model_agreement.py` 新增 `_comparability_gate()`（7 维冲突检测：币种 / 估值口径 / 财务期间 / 估值日期 >`COMPARABILITY_DATE_TOL_DAYS=45` / `peer_valid=False` / 数据质量 <`COMPARABILITY_QUALITY_FLOOR=50`）。冲突模型从 `solved_agg` 剔除并重算 `n_applicable`，落 `comparability_reference` / `comparability_conflicts` / `comparability_excluded_models`。
   - **空 `comparability` ⇒ 未声明口径 ≠ 冲突**——Gate 无依据排除该模型（证据缺失不等于冲突），仅「明确声明且互相冲突」才剔除。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| SOTP 不再把市场估值按 ML 概率拆分冒充独立证据；无真实分部数据时诚实降为 display_only | SOTP 在无 FMP 分部 key 时基本不产出可计入共识的估值（有意为之） |
| β 由「单一窗口 + 展示」变为「多窗口稳定性 → shrinkage → 区间传导」，不确定性进入结论 | shrinkage 常量（0.35 / 0.50）为工程取值的启发式，非统计最优 |
| 报告 ETR 单一主值（WACC 实际使用）+ Provider ETR 旁注，消除自相矛盾 | 供应商 ETR 需以次级样式呈现，渲染层需保持 |
| 穷尽 7 维可比性校验，不兼容模型隔离在共识之外但仍知情展示 | 参考口径以 MarketData 为锚，个别标的 field 缺失时 Gate 退化（不排除） |
| 未声明口径不排除——避免「证据缺失被当作冲突」的过度剔除 | 需各模型持续维护 `comparability` 声明 |

### Verification
- `python -m pytest -q` → **436 passed**（golden 因 SOTP→display_only **有意重生成一次**：PLD/NOW/NBIS/CRWV/NU 的 `n_solved` −1 / `n_display_only` +1 / `n_independent_evidence` −1，逐条核对为预期）。
- 定向核验：VST β → `beta_raw=2.3` / `beta_adjusted≈1.89` / `shrinkage≈0.315` / `dispersion=0.95` / `wacc_beta_lo≈0.104` / `wacc_beta_hi≈0.147`；SOTP 无分部数据 → `sotp_state=INSUFFICIENT` + `display_only=True` + `n_independent_segments=0`；外部 segments → `SOLVED` + `n_independent_segments=2`；Comparability Gate 8 用例（币种冲突剔除且 `median==105.0`、未声明不剔除、peer 无效、陈旧日期、财务期间冲突、低数据质量、无数据无 Gate）。

---

## ADR-051: 用户代码审查 Phase 1 · Valuation Integrity——β 溯源 / 复权回归 / EV↔Equity 独立桥 / SBC 归一化 / 币种感知 Rf / WACC 原始-钳制分离（Session #38）
- **Date**: 2026-11-15
- **Status**: ✅ Accepted & Implemented (Session #38)
- **Depends on**: ADR-019（β 单一出口）/ ADR-036（多窗口 β 暴露）/ ADR-038（ShareCountBasis 契约）/ ADR-041（bottom-up β 链）/ ADR-043（taxonomy 身份键）/ ADR-050（三态状态机、ETR 口径分离）
- **Constrained by**: 用户偏好「标签必须能证明自身 / 反对未经验证即断言 / 反对伪精确 / 不确定性必须传导 / 现金流币种↔Rf↔通胀↔终值增速必须一致 / 钳制值不得伪装成计算结果」

### Context
用户对引擎做第三轮代码审查，提交 **Phase 1 — Valuation Integrity** 最高优先级清单，目标「确保估值没有错误的输入、错误的来源和错误的股权价值桥接」，含 6 项：
- **P1-β-Source**：`valuation/wacc.py` 硬编码 `sources["β"] = f"3Y monthly vs SPY estimate = {beta_raw:.3f} …"`——该标签**无法证明** `mkt.beta` 真按此方法计算（可能是 Provider 值）。用户明确：**「我赞成修复，但不赞成未经验证就直接把自算 β 设为唯一主 β。应该先比较 Provider β / Regression β / Bottom-up β，再根据可靠性选择。」**
- **P1-β-Regression**：`_estimate_beta()` 使用 `quote.close`（未复权）——除息/拆股会在除权日制造伪收益跳变；且未做日期连续性检查。
- **P1-Bridge**：`models/dcf.py` 等直接用 `equity_val = ev - net_debt`——对简单资本结构精确，但对有少数股东权益 / 优先股 / 联营投资 / IFRS-16 租赁 / 复杂股权结构（腾讯、阿里）会明显偏差。用户明确：**「建议独立建立 Enterprise-to-Equity Bridge，而不是继续把逻辑塞进 DCF。」**
- **P1-SBC**：`CFO` 常把 SBC（非现金费用）加回，但 SBC 是股东真实经济成本。用户明确：**「不能既扣除 SBC，又对同一部分股权奖励重复计算稀释成本。」**要求独立 SBC Normalization 模块，记录调整前后 FCF 与每股价值。
- **P1-Currency**：`wacc.py` 一律用注入 Rf / 美国 10Y / 默认 Rf，无按现金流币种（USD/HKD/CNY/MYR）选 Rf 的机制。核心原则：**「现金流币种、无风险利率、通胀假设和终值增长率必须保持一致。」**
- **P1-Clamp**：`wacc = max(min_wacc, min(max_wacc, wacc_raw))` 使报告把钳制后的 6% 当真实计算值（实际 raw 5.2%）。用户要求：**「保留原始值、最终值、钳制原因，并将异常升级成估值风险提示。」**

### Decision
1. **β 溯源只渲染可验证事实（P1-β-Source）**：`valuation/wacc.py` 删除硬编码标签，新增 `_format_beta_source(prov, beta_value)`——按 provenance 的 `source` 字段分派：`regression` → 输出窗口标签 / 价格口径 / 基准 / 起止日期 / 观测数 / 缺口数；`provider` → 明示「Yahoo vendor estimate, method unverified」；**无 provenance → 明示「source unverified」，绝不臆断方法**。β 选择仍保持 `resolve_effective_beta()` 单一出口（bottom-up → 回归 → default），**未改主 β 选择逻辑**（用户明确反对未验证即改）。
2. **复权价格 + 日期连续性（P1-β-Regression）**：`data/providers.py::_estimate_beta()` 回归改用 `adjclose`（拆股/分红复权；raw close 仅回退），`price_basis ∈ {adjclose, adjclose+raw-fallback, close(unadjusted)}`；用 ISO-week/period keying 检查缺失，记 `missing_periods`；返回 provenance dict（`window_label/benchmark/window_start/window_end/n_observations/…`）供 WACC 与报告消费。
3. **EV↔Equity 独立桥（P1-Bridge）**：新建 `valuation/equity_bridge.py`：
   - `Equity = EV − NetDebt − MinorityInterest − PreferredEquity − Leases(未含于Debt时) − OtherClaims + NonOperatingAssets`。
   - **重复扣除守卫**：`net_debt_includes_minority/preferred` 或 `market.leases_in_debt is True` 时对应项不再扣；`None` 语义 = 「无该项索偿」**绝不静默按 0**。
   - `equity_to_enterprise()` 与 `enterprise_to_equity()` **共用同一 resolver → 精确互逆**（模型间零漂移）。
   - 全部 6 个 EV-based 模型（DCF / Reverse DCF / Multiples / SOTP / Unit-Economics / NAV）与 `forecasts/fcf_projection.py` 改走该模块；`breakdown["equity_bridge"]` 落明细。
4. **SBC 归一化「二选一」（P1-SBC）**：新建 `valuation/sbc.py`——`expense`（扣 FCF，股数不变）/ `dilution`（缩放股数，FCF 不变）/ `none`（禁用）；**机制上杜绝双重计数**；SBC 缺失或为 0 → 不调整（**绝不臆造成本**）；`dilution` 缺稀释率 → 回退 `expense`。接入 Reverse DCF，落 `assumptions["SBC Adjustment"]` 与 `breakdown["sbc_normalization"]`（记录调整前后 FCF 与每股）。
5. **币种感知 Rf + 终值 GDP 上限（P1-Currency）**：`config.py` 新增 `CURRENCY_RISK_FREE_RATES` / `CURRENCY_NOMINAL_GDP` / `DEFAULT_MACRO_CURRENCY`；`valuation/wacc.py::currency_macro_anchors()` 与 Rf 四级优先级（注入值仅在币种一致 / provenance 非 USD 时保留 → 活 U.S. Treasury 仅 USD → 币种主权锚 → 默认）；USD 来源 Rf 用于非 USD 现金流时**显式替换并记 `sources["Rf (currency)"]`**；`valuation/terminal_growth.py` GDP 上限随币种调整（USD 保持 0.045 以零 golden 漂移）。
6. **WACC 原始值与钳制值分离（P1-Clamp）**：`WaccBreakdown` 新增 `wacc_raw` / `wacc_clamped` / `wacc_clamp_reason` + `wacc_clamp_note()`；`sources` 追加「WACC (raw) model-computed (pre-clamp)」与钳制方向原因——**钳制结果不再伪装成模型真实计算值**，异常升级为估值风险提示。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| β 标签只声明可证明的事实，「3Y monthly vs SPY」不再冒充 Provider β | 无 provenance 的历史缓存数据会显示「source unverified」（诚实但需回填） |
| 复权回归消除除权日伪跳变；缺口显式暴露 | `adjclose` 不可用时回退 raw close，需在报告中标注口径 |
| 复杂资本结构（MI/优先股/联营/租赁）股权价值精确且可逐项审计 | 依赖 provider 是否抽取 `minority_interest` 等字段；缺失时桥接精度受限（已 note） |
| SBC 二选一机制性杜绝双重计数 | 目前仅接入 Reverse DCF；正/反向 DCF TTM FCF 主链待统一 |
| 币种 Rf/通胀/终值增速同源，非 USD 标的免于用 USD 无风险利率折现 | 非 USD 分支用静态主权锚（非实时曲线） |
| raw / clamped / reason 三分离，钳制异常升级为风险 | 报告渲染层需展示 `wacc_clamp_note()` 方可闭环 |
| 全部改动在 USD / 简单结构 / 无 SBC 时退化为原行为 → golden 零漂移 | — |

### Verification
- `python -m pytest -q` → **474 passed**（新增 `tests/test_equity_bridge.py` 18 + `tests/test_sbc.py` 13 + `tests/test_terminal_growth.py::TestCurrencyAwareGDPCeiling` 6）；`ruff check .` → **All checks passed!**；golden **零漂移**。
- 定向核验：`itemized_note()` 输出 `EV=… 净债务=… 少数股东权益=-300 优先股=… +非经营性资产=400 → 股权价值=…`；`enterprise_to_equity ∘ equity_to_enterprise = id`（parametrize round-trip）；CNY 标的 `long_term_nominal_gdp=0.055`、USD 保持 `0.045`；SBC `expense` 扣减后 `adjusted_fcf = reported − sbc`，`dilution` 走股数 `factor`。

---

## ADR-052: 统一模型财务口径 + 报告解释修复——FCF 相对诊断 / TV-EV 措辞分级 / MC 桥接一致 / SBC 全覆盖 / β 方法分歧 / Peer 溯源与股数审计（Session #39）

- **Date**: 2026-11-15
- **Status**: ✅ Accepted & Implemented (Session #39)
- **Depends on**: ADR-019（β 单一出口）/ ADR-024（口径契约，渲染层禁止猜口径）/ ADR-034（MC 零扰动锚点 = DCF）/ ADR-036（多窗口 β 暴露）/ ADR-038（ShareCountBasis 契约）/ ADR-041（bottom-up β 链）/ ADR-051（EV↔Equity 独立桥、SBC 归一化）
- **Constrained by**: 用户偏好「**本轮不新增估值模型**，只统一口径与修报告解释 / 报告措辞必须与计算一致 / 缺失数据返回 Insufficient Data，禁止 None→0 / Golden Baseline 零漂移，不得为过测试重生成 / 静态板块锚点不得冒充实时同行中位数」

### Context
用户提交**代码审查报告**，明确目标「**统一现有模型的财务口径，并让报告正确解释计算结果**」，**强调不新增估值模型**，并列出 P0/P1/P2：
- **P0 · FCF 预测与实际脱节**：`analysis/divergence.py::_fcf_margin_check()` 仅在绝对差 ≥15pp 时 flag，导致 GOOG TTM FCF margin 4.2% → 预测末年 13.7%（+9.5pp，>3×）被误判为 `ALIGNED`；历史平均可能忽略最新 TTM CapEx 抬升。
- **P1 · TV/EV 报告解释错误**：`_tv_check()` 仅在 TV/EV >80% 时 flag，导致 73.9% 被判定 `ALIGNED` 并写成「显式期贡献占主导」（实际显式期仅 26.1%）。
- **P1 · Monte Carlo 未用新 Equity Bridge**：DCF 用完整 `enterprise_to_equity()`，MC 仍用 `eq = EV − net_debt`，复杂资本结构下概率分布与 DCF 基准不同口径；且 `ev=None` 被转成 0。
- **P1 · SBC 未覆盖所有模型**：FCF Yield 用 `ttm.free_cash_flow / multiple` 未做 SBC 归一化；`float(reported_fcf or 0.0)` 把缺失 FCF 变成 0。
- **P1 · β 置信度未反映方法分歧**：报告仅据回归窗口极差判断不确定性，但实际采用 Bottom-up β（0.94）与 Regression β（1.41）差距明显，仍输出「不确定性：低」。
- **P2 · Peer 来源标签不准**：`EXACT_INDUSTRY` 实际只是 Yahoo Sector 与静态表 key 精确匹配，非真实 Industry Peer Analysis。
- **P2 · 股数对账透明度不足**：需 Share Count Audit Table（Model｜Share Count｜Basis｜Deviation vs Market）。
- **MC 截断透明度**：正态抽样后直接截断会在边界堆积概率质量，报告参数均值/标准差易被误解为实际样本统计。

### Decision
按 **Phase A–F** 分阶段落地，**不新增任何估值模型**：

1. **Phase A · FCF Normalization + FCF Margin 相对诊断**：`_fcf_margin_check()` 触发条件由绝对差改为**相对判断**（常量 `FCF_MARGIN_ALIGNED_PP=0.03` / `FCF_MARGIN_FLAG_PP=0.05` / `FCF_MARGIN_HIGH_RATIO=2.0`）：`符号翻转` 或 `|Δ|≥5pp` 或 `预测 > 2× TTM` → `flag`；`3–5pp` → `moderate`；`<3pp` → `aligned`。新增 `_fcf_normalization_layer()`：TTM vs 3–5 年历史正常化对比（`CapEx/收入`、`D&A/收入`、`ΔNWC/收入`、`FCF margin` vs 历史正常化 FCF margin），据此区分**暂态资本开支周期**（CapEx/收入 > 历史 ×1.3）与**结构性经营现金流恶化**；**历史均值绝不直接当作未来正常值**。
2. **Phase B · TV/EV 措辞分级与风险阈值分离**：`_tv_check()` **报告分级** `<50%` 显式期占多数 / `50–70%` 终值占多数 / `70–80%` **高终值依赖，需要审查**（`moderate`）/ `≥80%` 极高终值依赖触发风险警告（`flag`）；**风险 Severity 仍在 ≥80% 触发**（措辞与风险解耦）。73.9% 现读作「高终值依赖，需要审查」。
3. **Phase C · Monte Carlo 统一 Equity Bridge**：`_project_one()` / `_project_one_path()` 的 EV→Equity 改调 `enterprise_to_equity(ev, mkt).equity_value`（与 DCF 同源、同资本结构口径）；`ev is None` → 返回 `None`（**无效状态，不静默按 0**）；零扰动锚点与 DCF 精确对齐（容差仅来自数值精度）。
4. **Phase D · SBC 全覆盖**：FCF Yield 接入 `normalize_fcf_for_sbc()`（`fcf_used = adjusted_fcf`，落 `breakdown["sbc_normalization"]` + `breakdown["fcf_used"]`，与 DCF 同口径、不重复扣）；**TTM FCF 缺失 → `SolverStatus.INSUFFICIENT_DATA`**（`breakdown["fcf_used"]=None`），不把缺失伪装成真实零 FCF。
5. **Phase E · β 三指标 + 分部身份**：`valuation/wacc.py` 将 β 不确定性拆为**三个独立指标**——`Regression Stability`（回归窗口稳定性）/ `Bottom-up Reliability`（同业数量·质量·适配性，`BETA_BOTTOM_UP_MIN_PEERS=4` 以下降级为 `Requires Review`）/ `Methodology Divergence`（Regression vs Bottom-up 差异，0.94 vs 1.41 → `Material`）；`beta_uncertainty_note()` 三行并列。分部 β（`data/industry_beta.py`）breakdown 携带 peer 证据（`peer_levered` / `n_peers` / `rationale`），**不同分部不得默认落同一行业 β**。
6. **Phase F · Peer 溯源 + 股数审计**：`_resolve_peer_bucket()` 新增 `PEER_SOURCE_EXACT_SECTOR_ANCHOR="EXACT_SECTOR_ANCHOR"`（Yahoo sector == 静态表 key，**非真实同业中位数**）；`PEER_SOURCE_LABELS` 明示各来源语义。`analysis/model_agreement.py` 新增 `ShareCountAuditRow` + `share_count_audit` + `share_count_audit_table()`（`Model | Share Count | Basis | Deviation vs Market`，有符号偏差，不可比标 `⚠️ 不可比`）；`reporting/dashboard.py` 渲染该表。
7. **MC 截断透明度**：`MonteCarloResult` 新增 `sample_driver_mean` / `sample_driver_std` / `lower_bound_hit_rate` / `upper_bound_hit_rate` / `gordon_constraint_hit_rate` + `distribution_transparency_note()`，逐驱动输出「请求 μ/σ → 实际样本 μ/σ（下界命中 x%，上界命中 y%）」+「Gordon 约束命中 z%」。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| FCF margin 诊断改为相对判断：4.2% → 13.7% 这类 >2× 外推不再被掩盖 | 阈值（3pp/5pp/2×）为初值，需跨行业校准 |
| TV/EV 措辞与计算一致；高终值依赖不再被误述为显式期主导 | 措辞分级与风险阈值并存，渲染层需同时消费两者 |
| DCF 与 MC 共享同一 EV↔Equity 桥 → 概率分布与基准同口径 | MC 依赖 provider 抽取少数股东权益/优先股等字段，缺失时桥接精度受限 |
| FCF Yield 与 DCF 同 SBC 口径；缺失 FCF 诚实标 Insufficient Data | — |
| β 三指标并列，Bottom-up 与 Regression 分歧不再被窗口极差掩盖 | 三指标阈值需跨行业校准 |
| Peer 来源可追踪（静态锚点 ≠ 实时同业中位数）；股数分母逐模型可审计 | 未申报 share_count 的模型不出现在审计表（保持「未声明 ≠ 冲突」） |
| MC 截断透明度暴露概率质量堆积 | 未改为截断正态抽样（仅透明化，非修复） |
| **不新增模型 + Golden Baseline 零漂移**（未重生成基线） | — |

### Verification
- `python -m pytest -q` → **507 passed**；`ruff check .` → **All checks passed!**；`tests/test_golden_report.py` 通过 → **golden 零漂移**。
- 新增 `tests/test_reporting_integrity_repair.py`（33 用例）：`TestFcfMarginDiagnostic`（4.2%→13.7% flag / 4.5% aligned / 8.0% moderate / 2%→4.5% >2× flag / 符号翻转 flag / 阈值有序）；`TestTvWording`（0.45/0.50/0.739/0.80/0.90 分级，73.9% 不得读作显式期主导）；`TestMonteCarloEquityBridge`（`_project_one` 共享桥 + `ev=None → None` + MSFT/AAPL 复杂结构 MC anchor == DCF）；`TestFcfYieldSbc`（SBC-adjusted FCF / 缺失 FCF → INSUFFICIENT_DATA）；`TestBetaReliability`（0.94 vs 1.41 material / peer 不足降级 / note 含三指标）；`TestSegmentBetaIdentity`（分部携带 peer 证据 / 不同分部映射不同 industry）；`TestMonteCarloTruncationTransparency`（requested vs actual 字段 + note）；`TestPeerProvenance`（静态锚点 ≠ LIVE_PEER_MEDIAN）；`TestShareCountAudit`（Market/TTM/Annual 三口径偏差审计 + 表格含「不可比」）。

---

## ADR-053: 跨行业阈值校准 + SBC 归一化下沉 FCF 主链——按业务原型分档诊断带 / β 同业地板按池广度 / FCF 单一出口双函数（Session #40 · M-67 + M-69）

- **Date**: 2026-11-15
- **Status**: ✅ Accepted & Implemented (Session #40)
- **Depends on**: ADR-051（SBC 归一化 `valuation/sbc.py`、β 溯源）/ ADR-052（Phase A FCF 相对诊断全局带、Phase E `BETA_BOTTOM_UP_MIN_PEERS`、Phase D FCF Yield SBC + INSUFFICIENT_DATA、Phase F Peer 溯源）/ ADR-041（bottom-up β 链）/ ADR-036（多窗口 β）
- **Constrained by**: 用户偏好「**不新增估值模型** / 所有修复必须附带测试或验收条件 / **Golden Baseline 零漂移**，不得为过测试重生成基线 / 缺失数据返回 Insufficient Data，禁止 None→0 / 报告措辞必须与计算一致」

### Context
Session #39（ADR-052）交付 Phase A–F 后遗留两条自我标注的 Known Issue：
- **M-67 · 阈值未校准**：Phase A 的 FCF margin 诊断带（`FCF_MARGIN_ALIGNED_PP=0.03` / `FCF_MARGIN_FLAG_PP=0.05` / `FCF_MARGIN_HIGH_RATIO=2.0`）与 Phase E 的 `BETA_BOTTOM_UP_MIN_PEERS=4` 都是**全局初值**。但 5pp 的 FCF margin 摆动对受监管公用事业与重资本半导体**不是同一件事**；4 家同业中位数在深同业池原型中偏薄、在窄池原型中反而偏宽。
- **SBC 双计风险**：Phase D 让 `models/multiples.py`（FCF Yield）与 `models/reverse_dcf.py` **各自**调用 `normalize_fcf_for_sbc()`。多地各自施加调整正是 SBC 被**重复扣减**（既当费用扣 FCF、又当稀释扣股数）的经典来源；且未来任何新 FCF 消费者都要记得手动再调一次。

**ID 诚实性**：`TODO.md` 中 **M-68 已被占用**（"Monte Carlo 截断改为截断正态/重参数化抽样"，仍 `⬜ TODO`），故本轮 SBC 下沉**正名为 M-69**（不抢占既有 ID 空间，代码注释与测试标签同步更正）。

### Decision
1. **M-67 · 新建 `analysis/threshold_calibration.py`（运行时单一来源）**：
   - **波动分档（单调规则）**：以业务原型的 **3–5 年年度营业利润率总体 σ** 作 FCF margin 波动代理（FCF margin = margin·(1−t) + D&A/Rev − CapEx/Rev − ΔNWC/Rev，margin 波动主导；代理口径**显式声明**而非默认）。`σ < 0.03 → stable` / `0.03 ≤ σ < 0.06 → moderate` / `σ ≥ 0.06 → volatile`（`TIER_STABLE_MAX_DISPERSION` / `TIER_VOLATILE_MIN_DISPERSION`）。
   - **带宽随波动放大**（`_TIER_BANDS`）：stable `2pp/4pp/1.75×` / moderate `3pp/5pp/2×`（= 原全局基准，向后兼容）/ volatile `4pp/7pp/2.5×`。逻辑：**稳定业务容忍窄带**（相对小幅偏离也应是信号）；**波动业务需更宽带**（避免把正常周期波动误报为脱节）。
   - **β 同业地板按 *池广度* 分档**（非按波动，`beta_min_peers_for()`）：宽池 `BETA_MIN_PEERS_BROAD=5` / 窄池 `BETA_MIN_PEERS_NARROW=3` / 未知 `BETA_MIN_PEERS_UNKNOWN=4`。窄池 = `{NEOBANK, FINTECH, CONGLOMERATE}`（纯 play 上市公司本就寥寥，小地板是**诚实的**而非降级）；深池需更多名字才配称中位数可靠。
   - **两来源校准（可审计，可复现）**：① **内部样本** — 离线回归篮子 `tests.golden_report.BASKET` 实测各原型营业利润率 σ，冻结于 `CALIBRATION_EVIDENCE`（archetype → (σ, n)），审查者可重推；② **领域先验** — 篮子未覆盖原型（UTILITIES / TELECOM / INSURANCE = 合同化现金流 → stable；HEALTHCARE / MEDIA / CONGLOMERATE → moderate；COMMODITY / NEOBANK → volatile）。
   - **诚实规则**：该表是**唯一运行时来源**（报告确定性），校准 harness 仅是复现工具、绝不在报告期依赖；**n 随每个 σ 一并披露**，小样本仅作**佐证**、不作精度声明；**未知/未映射原型回退 `DEFAULT_CALIBRATION`（moderate 全局带）**，绝不静默重判。
   - **消费端接线**：`analysis/divergence.py::_fcf_margin_check()` 经 `_calibration_for_profile()`（内部 `business_type_from_profile`）取带，审计行追加 `〔行业校准[tier]（观测 σ, n）：FCF margin 带 Xpp/Ypp/Z×，β 最小同业 N 家；rationale〕`；`valuation/wacc.py::_bottom_up_reliability_label()` 由 `beta_min_peers_for(business_type)` 取地板（`business_type is None` → 沿用 `BETA_BOTTOM_UP_MIN_PEERS`）。
2. **M-69 · SBC 归一化下沉 FCF 主链**：`data/fcf_utils.py` 确立**双函数出口**——
   - `resolve_ttm_fcf(stmt) → (value, source)`：**raw primitive**（`reported`/`derived_ocf_capex`/`missing`），**不施加 SBC**，仅用于存在性检查。
   - `resolve_ttm_fcf_normalized(stmt, *, shares, method) → (value, source, SbcNormalization)`：**value producer**，调用 `valuation.sbc.normalize_fcf_for_sbc()` **恰好一次**；调整生效时 `source` 追加 `+sbc_normalized` 后缀；`raw is None → (None, "missing", …)`（**调用方必须出 Insufficient Data，绝不臆造 0**）。
   - 两个原消费者改为消费共享出口：`models/reverse_dcf.py`（`base_fcf` / `fcf_source` / `sbc_normalization`）与 `models/multiples.py::FCF Yield`（**保留 Phase D 守卫**：`ttm is None or ttm.free_cash_flow is None → INSUFFICIENT_DATA`；`fcf_used = adjusted_fcf if fcf_available else raw_fcf`）。**消除两处各自调用 = 消除双计来源**。
3. **循环导入修复（M-67 接线副作用）**：`valuation/wacc.py` **删除**模块级 `from analysis.threshold_calibration import beta_min_peers_for`，改为 `_bottom_up_reliability_label()` 函数体内**惰性 import**。原因：导入 `analysis.threshold_calibration` 会先执行 `analysis/__init__.py`，其 `from analysis.expectation import …` 拉入完整模型图，与 `models.dcf` 部分初始化形成环（`models.dcf → valuation.wacc → analysis → analysis.expectation → models.reverse_dcf → models.dcf`）。`business_type is None` 分支完全不走该 import。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| FCF margin 诊断按原型波动定带：稳定公用事业 4.5pp 偏离→FLAG，波动半导体同 4.5pp→MODERATE | 分档规则与 cut point（0.03/0.06）仍是**文档化先验**，样本篮子仅 19 名、n 偏小 |
| β 同业地板按池广度分档：窄池 FinTech 3 家即 high，深池半导体需 5 家 | 窄池集合 `{NEOBANK, FINTECH, CONGLOMERATE}` 目前硬编码，新增原型需同步 |
| 未知原型回退 moderate 全局带 → **零静默重判** | — |
| SBC 在主链出口**恰好施加一次** → 结构性杜绝双计（费用 ∩ 稀释） | 未来新 FCF 消费者**必须**经 `resolve_ttm_fcf_normalized`，否则漏归一化 |
| 双函数（primitive / value producer）语义分离，存在性检查不受 SBC 副作用 | — |
| 惰性 import 消除循环依赖，零行为变更 | — |
| **不新增模型 + Golden Baseline 零漂移**（USD/简单结构/无 SBC 时退化为原行为） | — |

### Verification
- `python -m pytest -q` → **522 passed**（Session #39 的 507 → 522，新增 15 用例）；`ruff check .` → **All checks passed!**；`tests/test_golden_report.py` → 通过 → **golden 零漂移**。
- 新增 `tests/test_reporting_integrity_repair.py` 两组用例：
  - `TestCrossIndustryThresholdCalibration`（9）：`tier_for_dispersion` 单调（None→moderate / 0.01→stable / 0.03→moderate / 0.04→moderate / 0.06→volatile / 0.20→volatile）；archetype 解析（Utilities→stable / MatureTech→moderate / Semiconductor→volatile）；带随波动放大；未知原型回退默认带；β 地板随池广度（FinTech/Neobank→NARROW / Semiconductor→BROAD / None→UNKNOWN）；**校准真正驱动诊断**——同 +4.5pp 缺口在 Utilities 判 FLAG、在 Semiconductor 判 MODERATE；+2.5pp 在 MatureTech 判 ALIGNED、在 Utilities 判 MODERATE；审计行含「行业校准」「β 最小同业」与 tier 名；`_bottom_up_reliability_label` 原型感知（3 家同业 FinTech→high，无原型→medium；4 家→high，Semiconductor→medium）。
  - `TestSbcMainChainExit`（6）：`resolve_ttm_fcf` 永不施加 SBC（1000→`reported`）；normalized 出口扣减一次（1000 − SBC 200 = 800，`reported+sbc_normalized`，`adjusted_fcf_per_share=8.0`）；derived FCF 亦归一化（(1000−200)−100=700，`derived_ocf_capex+sbc_normalized`）；SBC 缺失不动 FCF（1000，无后缀，`applied False`）；缺失 FCF 不臆造零（`(None, "missing", fcf_available False)`）；`ReverseDCFModel` 恰好扣一次 SBC（`base_fcf == reported×0.75`，`sbc_normalization["applied"] is True`，`fcf_source` 以 `+sbc_normalized` 结尾）。

---

## ADR-054: AVGO Audit Remediation Phase 1——Equity Bridge 缺失数据安全 / P/E 分子分母口径一致 / 股数三口径证据闸门（Session #41）

- **Date**: 2026-11-15
- **Status**: ✅ Accepted & Implemented (Session #41)
- **Depends on**: ADR-051（EV↔Equity 独立桥 `valuation/equity_bridge.py` + 双计守卫）/ ADR-052（Phase F `ShareCountAuditRow` + `share_count_audit_table()`）/ ADR-034（`ShareCountBasis` 股数口径契约 + 共识可比性校验）/ ADR-050（估值可比性 Gate）
- **Constrained by**: 用户任务书「**不重设计无关模块 / 改码前先审计现有实现 / 缺失值禁止 None→0 静默转换 / 每股基准不可靠不得产出无条件强结论但保留 EV 级结果 / 现有测试与 Golden Baseline 除非明确批准否则零漂移（不得自动重生成基线）/ 未实际执行的测试不得声称通过**」

### Context
基于 2026-11-15 06:27 UTC 生成的 AVGO 报告，审计暴露三处 P0 估值完整性缺陷：

- **P0-1 · Equity Bridge 静默 0**：`valuation/equity_bridge.py`（ADR-051）在缺 EV 时按 `0 − claims` 出值 → 会凭空造出**负股权价值**；且「债务/现金输入缺失」被按 `net_debt=0` 处理，无法与「**已验证的零净债务**」区分。
- **P0-2 · P/E 分母错配**：`models/multiples.py::P/E` 的每股价值 = `multiple × TTM EPS`（分母是 TTM 报表股数），但重建总股权价值时乘的是**市场股数**——当两者不同（AVGO 类 4.18B TTM vs 4.74B 年报）时口径不一致。
- **P0-3 · 股数单源伪证**：市场隐含（`market_cap ÷ price`）、财报期末、稀释加权平均三口径未作为**独立证据源**比较；`market_cap ÷ price` 被隐含当作财报股数的证明；股数偏差超阈值时每股结论未降级。

### Decision
1. **P0-1 · Equity Bridge 缺失数据安全**（`valuation/equity_bridge.py`）：
   - `EquityBridge` 新增 `status`（`EB_STATUS_OK` / `EB_STATUS_INCOMPLETE` / `EB_STATUS_UNAVAILABLE`）+ `missing_inputs` + `net_debt_verified` + `is_reliable()`。
   - `_resolve_net_debt()`：**verified** = 显式 `net_debt`，或 `total_debt` & `cash` **俱全**（其差即为可信值，含真实 0）；**缺失** = 债务/现金不全 → 数值按 0 腿展示（仅用于显示）但 `net_debt_verified=False`、`status=INCOMPLETE`，并记录缺失腿（`net_debt` / `total_debt` / `cash_and_equivalents`）。
   - `enterprise_to_equity(None, …)` → `equity_value=None`、`status=UNAVAILABLE`（**绝不 `0 − claims`**）；`equity_to_enterprise(None)` → `None`。
   - **保留**复杂资本结构双计守卫（`net_debt_includes_minority` / `net_debt_includes_preferred` / `leases_in_debt`），`equity_to_enterprise` 与 `enterprise_to_equity` 共用 `_resolve_claims` 保持精确互逆。
2. **P0-2 · P/E 分子分母口径一致**（`models/multiples.py`）：P/E 用 `ttm.shares_outstanding`（basis=TTM）重建股权价值；无 TTM 股数 → 回退 market 并**显式标注口径不一致**（`numerator_denominator_basis_match=False`）；新增 `breakdown["pe_basis_audit"]` 记录 EPS basis / period / source 与 shares basis / source / as_of。
3. **P0-3 · 股数三口径证据闸门**：
   - `data/reconciliation.py` 新增 `ShareCountEvidence` + `share_count_evidence()`：分离**市场隐含 / 财报期末 / 稀释加权平均**，各带 `period` / `source`；`max_deviation = max(|filing−market|, |ttm−market|)/market`，`consistent = max_dev ≤ _TOL_SHARES(0.25)`；note 明示 `market_cap ÷ price` **仅为同口径复算，非财报股数证明**。
   - `analysis/model_agreement.py` 新增 `_EXPECTED_SHARE_BASIS`（按模型族声明期望分母）+ `ShareCountAuditRow.source/as_of/basis_expected` + `ModelAgreement.share_count_reliable`（来自**独立证据**，非单源）。
   - `reporting/verdict_intuition.py`：`share_count_reliable is False` → `shares_unreliable=True` → headline 封顶「**每股口径不可靠**」（应用在 scenario 覆盖之后）；**EV 级估值结果保留**（不清零、不剔除）。

### Consequences
| Pros (+) | Cons (-) |
|----------|----------|
| 缺失 EV 不再产出伪造的负股权价值；缺失债务/现金与「已验证零净债务」可区分 | `_TOL_SHARES=0.25` 仍为经验阈值（与既有对账层一致） |
| P/E 分子分母同口径（TTM↔TTM），消除 AVGO 类股数错配 | 无 TTM 股数时仍回退 market（已显式标注，非静默） |
| 股数审计比较**独立证据源**，不再把 `market_cap÷price` 当财报证明 | 稀释加权平均以 TTM 报表值代理（`FinancialStatement` 未区分 basic/diluted） |
| 每股结论可靠时不受影响；不可靠时降级但**保留 EV 级结果** | `MarketData.net_debt_or_zero()` 旧静默路径未全库替换（仅桥内守卫） |
| 零漂移：合成 feed 三口径一致 → `share_count_reliable=True`，`share_ref_source` 字符串未变 | — |

### Verification
- `python -m pytest -q` → **542 passed**（Session #40 的 522 → 542，新增 15 用例）；`ruff check .` → **All checks passed!**；`tests/test_golden_report.py` → 通过 → **golden 零漂移**（未重生成基线）。
- 新增 `tests/test_avgo_audit_remediation.py`（15 用例）：P0-1（缺失 EV→`None`/UNAVAILABLE、缺失债务与现金→INCOMPLETE、已验证零净债务→OK、复杂桥双计保护）；P0-2（P/E 用 TTM 股数重建 `equity_value`，非市场股数；无 TTM 回退 market 且 `numerator_denominator_basis_match=False`；P/E 行 vs 市场参考 +30% → `comparable=False`）；P0-3（三口径分离、偏差 30%→`consistent=False`、≤25%→True、`market_cap÷price` 非证明、市场隐含缺失→不可比）；P0-3 降级（`share_count_reliable=False` → headline「每股口径不可靠」且 EV 级 `enterprise_value` 保留）；Golden 兼容（AVGO 管线 `check_invariants` 空 + `share_count_excluded==[]` + golden 文件 18 只全在且 `share_ref_source` 未变）。

---

## 待决策 (Proposed)

### P-001: 港股 / A 股双市场支持的数据来源
**待选项**:
- A) 东方财富 API (原生中文 / 无风控)
- B) Financial Modeling Prep (付费但稳定，支持全球市场)
- C) Yahoo Finance `.HK` / `.SS` 后缀继续 (部分可用)
**决策**: 等 v0.8 后再选，先专注美股质量

### P-002: 估值结果持久化选型
**待选项**:
- A) SQLite + peewee (项目已安装 peewee，playhouse 目录可见)
- B) Supabase PostgreSQL (云原生，用户有偏好)
- C) Parquet + DuckDB (分析查询友好)
**决策**: v0.8 时根据部署平台定
