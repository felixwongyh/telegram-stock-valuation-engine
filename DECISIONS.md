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
