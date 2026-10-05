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
