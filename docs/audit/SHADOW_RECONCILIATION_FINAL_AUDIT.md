# Shadow Snapshot & Golden Reconciliation — Final Audit

Snapshot: `shadow-20261128`  
Tickers with a shadow: AMD, BAC, JPM, MSFT  
Scope: **evidence production only**. No golden file was overwritten and no
historical identity was re-labelled.

---

## 1. 六问

### 问一：每个 Shadow Snapshot 的每个字段，是否都能追溯到一条原始数据记录？

**是，但有一处必须说清楚。**

每个 ticker 目录下保存了 vendor 的原始响应字节：

```
data/shadow_snapshots/shadow-20261128/<TICKER>/
    manifest.json       每件产物的 url / sha256 / 大小 / 抓取时间
    raw/timeseries.json  fundamentals-timeseries 原始响应（逐字节）
    raw/chart.json
    raw/quote_summary.json
    raw/sec_facts.json  SEC XBRL 交叉验证所用的原始 concept 响应
    statement.json      年度视图 + 字段值
    provenance.json     年度视图逐字段来源
    ttm_statement.json  TTM 视图 + 字段值
    ttm_provenance.json TTM 视图逐字段来源
```

`verify_shadow()` 会对每件产物重新计算 SHA-256 并与 manifest 比对。
`tests/test_shadow_snapshot.py::test_verify_shadow_detects_a_modified_artifact`
证明了改动一个字节就会让校验失败——也就是说"证据链断裂"是可见的，而不是无声的。

**必须说清楚的一处**：TTM 视图中的每个数值都不是某一条原始记录，而是
四条季度记录之和。它仍然是可追溯的——`ttm_provenance.json` 里记录了
`input_fields`（哪四个季度）、`input_hash`、以及 `derivation_method`——
但它追溯到的是**一组记录加一个明确的推导**，不是单条记录。把它说成
"某一条记录"是不准确的，所以这里分开陈述。

### 问二：有多少字段真正获得了 COMPANY_REPORTED？

按**年度视图**统计（只有年度数字可能与某份年报里的某一个 XBRL fact 完全对应）：

| Ticker | 年度财期 | COMPANY_REPORTED | VENDOR_REPORTED | SEC 反驳 | 检过但无 fact | 无 concept 映射 |
|---|---|---|---|---|---|---|
| MSFT | 2026-06-30 | 12 | 7 | 0 | 1 | 6 |
| JPM | 2025-12-31 | 10 | 4 | 0 | 1 | 3 |
| BAC | 2025-12-31 | 9 | 6 | 1 | 1 | 4 |
| AMD | 2025-12-31 | 11 | 8 | 0 | 2 | 6 |

后两列必须分开看，因为它们说的不是一回事：

- **检过但无 fact**——有同语义 concept，但该公司该财期没有对应的年度申报行
  （例如 MSFT 的 `depreciation_amortization`：SEC 返回 404，公司用的是
  entity-specific 扩展标签）。这是"确实没查到"。
- **无 concept 映射**——该字段本身就没有语义相同的 us-gaap concept
  （`ebit`、`ebitda`、`free_cash_flow`、`total_debt`、`change_in_nwc`、
  `stock_based_compensation`），所以**根本没有去查**。这是"无从查起"。

把两者混成一个数字会让人以为引擎查过而失败了，实际上有一半的字段是引擎
正确地拒绝拿一个近似量去比对。

`COMPANY_REPORTED` 的判定条件是**全部满足**：

1. SEC 存在同语义的 us-gaap concept；
2. 存在 form 为 10-K / 20-F / 10-K/A / 20-F/A 的 fact；
3. 该 fact 的期末与财期相差 ≤ 10 天；
4. 数值相对误差 ≤ 0.5%；
5. 该 fact 带有 `accn`（accession）与 `filed`（申报日期）。

任一条不满足就不升级。`tests/test_shadow_phase_invariants.py` 中
`test_annual_company_reported_fields_cite_a_filing` 断言：凡是标记为
`company_reported` 的字段，必须同时具备 `sec_accession`、`sec_filed`、
`evidence_raw_sha256`。

### 问三：有没有把 vendor 数字伪装成公司披露？

**没有，且这是本阶段投入最多的地方。**

新增了两个并列的源层级，而不是把 Yahoo 的数字直接标成 `reported`：

- `company_reported` —— 匹配到了公司申报的 XBRL fact；
- `vendor_reported` —— vendor 返回的规范化数字，**没有**任何申报文件佐证。

`vendor_reported` 在信任排序中**低于** `company_reported`（也低于旧的
`reported`）。理由写在 `DataOriginType` 的文档里：vendor 会重述、重分类、
四舍五入，所以"Yahoo 这么说"是比"10-K 这么写"更弱的陈述。

强制机制：

- `_FORBIDDEN_UPGRADES` 由 `_INFERRED_LEVELS × _REPORTED_LEVELS` 的笛卡尔积
  生成，而不是手写清单。原先手写清单只把 `REPORTED` 当目标，新增两个层级
  会留下 6 个静默缺口。
- `vendor_reported → company_reported` 被明确禁止静默发生。
- 唯一的合法出口是 `assert_no_forbidden_upgrade(..., evidence={"raw_sha256": ...})`：
  带可取回证据的**重新取源**是研究，静默改标签才是洗白。

### 问四：Golden 被改动了吗？

**没有被本阶段改动。**

`tests/test_shadow_phase_invariants.py::test_golden_fingerprints_are_unchanged_this_phase`
用 `git diff` 断言：相对 HEAD，`tests/golden/report_fingerprints.json` 中被
修改的**键名集合**只能是 `{"recon_checks"}`。那两个值是**前一轮会话**遗留的
（10 → 9），不是本阶段所为；本阶段若要动它，键名集合就会变大，测试会失败。

50 支基准的历史身份未变：Solved 数量仍为 **31**，与基线一致。

### 问五：算法版本能证明"没有变"吗？

**能，而且比上一轮更强。**

上一轮的 `source_fingerprint()` 只哈希锚点函数本身。它看不见两种真实的漂移：

- 锚点调用的 helper 的算术被改了（调用方的 AST 完全不变）；
- 锚点读取的模块级常量被重新绑定（`TOLERANCE` 这个表达式不变，变的只是它的值）。

新增 `dependency_fingerprint()`：从锚点出发做**传递闭包**，收集被调用的函数
与引用的标量常量，连同方法名与文档化公式一起哈希。

- 17 个方法 → **17 个互不相同的指纹**（此前 5 个共用 `_build_statements`
  的方法哈希完全相同，无法归因）；
- 依赖数 1–10，例如 `TTM_SUM_4Q` 会穿透到 `_ttm_eps` 与 `stamp`；
- `test_editing_a_helper_moves_the_fingerprint` 与
  `test_changing_a_constant_moves_the_fingerprint` 用真实的运行时变异证明它有效；
- `test_anchor_only_fingerprint_does_not_see_helper_edits` 反向钉住"窄指纹
  看不见这种改动"这一事实，防止有人把它"简化"回去。

当前漂移检查：`0 mismatch(es)`。

### 问六：有没有为了"让它通过"而放宽标准？

**没有。相反，过程中抓出了四个真实缺陷，全部是修正引擎而不是放宽判据。**

| # | 缺陷 | 若不修会怎样 |
|---|---|---|
| 1 | 把 `ebit` 映射到 `OperatingIncomeLoss` | MSFT 出现 8.9% 的假"矛盾"（155.2B vs 169.0B）。EBIT 含营业外损益，与营业利润是不同量。已删除该映射 |
| 2 | 股数从 `USD` 单位桶读取 | 股票概念的 XBRL 单位是 `shares`。读 USD 桶静默返回空，表现为"公司没申报股数" |
| 3 | capex 未做符号归一 | XBRL 把流出记为正，本管道存为负。不归一则每个 capex 都显示"矛盾"，真实矛盾被淹没 |
| 4 | 财期要求逐字符相等 | AMD 财年结束于 12 月最后一个周六：SEC 记 `2025-12-27`，Yahoo 标 `2025-12-31`。**13 个字段全部被判为"无申报"**，与"公司从未申报"无法区分 |

第 4 项尤其危险：它是一种**假阴性**，看起来完全像数据缺失。修正方式是
引入 ≤10 天的财期容差，并把 `period_label_gap_days` **记录下来而不是隐藏**
——审计者必须能看到"两个来源一致"时它们的期末其实差了 4 天。

另外，我自己在 TTM 聚合里也犯了两个错，都被数据本身抓出来：

| 错误 | 症状 | 修正 |
|---|---|---|
| 把资产负债表存量也按 4 个季度求和 | MSFT 股数 7.43B → 29.7B，权益 → 1.7 万亿 | 区分流量/存量；存量取最新季度余额 |
| 用子串启发式判断存量 | `FreeCashFlow` 含 "cash"，被误判为存量，TTM FCF 59.96B → 18.63B（只剩单季） | 已映射字段只按权威映射判定，启发式仅用于未知字段 |

两者都由 `test_stock_fields_are_not_summed_over_four_quarters` 等测试钉住。

---

## 2. 七答（关键判断）

### 其一：为什么 TTM 层全是 `vendor_reported`？

因为**任何公司都不申报"TTM 合计"**。跨非日历窗口的十二个月总额是分析口径，
不是申报口径。把四个季度之和标成 `company_reported` 正是本阶段明令禁止的伪造。

由此推出一个必须直说的事实：**被对账的 golden 是 TTM 报表，所以它消费的那些
字段，最强的可得证据是"带记录推导的 vendor_reported"，而不是申报级证据。**
申报级证据只存在于 shadow 的**年度**层。

这一条已写入 `docs/audit/PROVENANCE_COVERAGE_REPORT.md`，并由
`test_coverage_report_records_that_ttm_cannot_be_company_reported` 守护，
防止今后有人把它说成"覆盖率全线提升"。

### 其二：TTM 对账为什么反而让数字完全吻合？

因为聚合口径终于一致了。MSFT 年度 FY2026-06-30 营收 331.8B 与 TTM
2026-09-30 营收 346.4B 相差 4.2%，这 4.2% **全部**来自覆盖的十二个月不同，
与数据质量无关。按 TTM 重建后：

- revenue / ebitda / ebit / net_income / free_cash_flow 在 MSFT、JPM、BAC
  三家**全部 0.00% 偏差**；
- 这同时验证了 shadow 的季度求和逻辑是对的（否则不可能精确相等）。

如果当时按年度 shadow 去对 TTM golden 并写进报告，就会产出 8 条"重大变化"，
而它们全是假的。这个陷阱已经用 `STOCK_FIELDS` 与 TTM 视图分离来规避。

### 其三：BAC 的 cash 为什么是 `contradicted`？

BAC 现金：vendor 239.32B，SEC 231.85B，差 7.5B（3.2%）。

这**没有**被抹平，也没有被算成容差内的噪声。原因是两家对"现金"的口径不同：
`CashAndCashEquivalentsAtCarryingValue` 不含受限现金，而 vendor 的
`CashAndCashEquivalents` 可能含。这是真实的口径差异，属于需要人判断的事项，
所以引擎如实标 `contradicted` 并保留两边的原始数值与 accession。

这是引擎最有价值的输出类型：它证明了 vendor 数字**不是**公司申报的那个数。

### 其四：JPM/BAC 的股数为什么与 golden 差 13%？

因为 golden 的股数不是报表数。golden fingerprint 中
`share_ref_source = "market_cap ÷ current_price"`——它是**估算**值。

shadow 用的是 `OrdinarySharesNumber`，并有 SEC `CommonStockSharesOutstanding`
佐证（delta 2.7e-5）。

所以这个差异的方向是：**golden 侧是近似，shadow 侧更接近申报事实。**
报告里把它标为 material，但没有建议替换 golden——那是人的决定。

### 其五：AMD 为什么在 golden 里对不上？

`FrozenSnapshotMissError`。冻结集 `20261123` 内没有 AMD；缓存里唯一的 AMD
文件属于另一个 snapshot id（`20261128`）。

本阶段**没有**用今天的 AMD 数据去填 20261123 的位置。那正是"把当前数据伪装成
历史数据"。报告里 AMD 一节明写"不做对比"，并说明原因。

AMD 的 shadow 本身是完整有效的（11 个字段有 SEC 佐证），只是无可对账的基线。

### 其六：把旧的 `REPORTED` 保留下来，是不是在和稀泥？

是权衡，且是必要的一步。

全仓有 36 处 `origin_type=REPORTED` 的写入点，1425 个测试依赖它。若把
`REPORTED` 直接拆成两个新值，这些写入点会全部变成未定义行为，测试大面积失败，
而失败的噪声会掩盖真正要验证的东西。

保留 `REPORTED` 的代价是它仍在信任排序里、且高于 `vendor_reported`。这个代价
被两点限制住：

1. 注释明确写了它是**遗留标签**，新写入点应优先用两个更具体的层级；
2. 本阶段的 shadow 写入器**一个 `REPORTED` 都不写**——它只写
   `company_reported` / `vendor_reported` / `imputed`。

迁移路径清晰：逐个把旧的写入点改成具体层级，`REPORTED` 自然退场。

### 其七：这些 shadow 能直接替换 golden 吗？

**不能，而且本阶段刻意不提供这个动作。**

三个原因：

1. **只有 4 支**。基准是 50 支，4 支不足以支撑任何结论性的替换。
2. **只有年度层有申报级证据**，而 golden 是 TTM。要让 TTM 也达到申报级，
   需要按季度逐个匹配 XBRL fact 再求和——工作量与判据都不同，属于下一阶段。
3. **AMD 无可对账基线**，`^TNX` 混杂在缓存里，这些都需要先清理。

本阶段交付的是**可复现的证据**与**可归因的差异**。是否替换、如何分批替换，
应该由人在此基础上决定。`tests/test_shadow_phase_invariants.py` 中的
`test_reports_exist_and_do_not_claim_a_replacement` 明确禁止报告自称已完成替换。

---

## 3. 验收状态

| 项 | 结果 |
|---|---|
| 全量测试 | **1470 passed, 3 skipped, 0 failed** |
| 算法漂移 | **0 mismatch(es)** |
| Solved 数量 | **31**（基线 31，未变） |
| Shadow 可重现 | 4/4 通过 `verify_shadow` 逐字节校验 |
| Golden 未被覆盖 | `git diff` 键名集合 ⊆ `{recon_checks}`（前轮遗留） |
| 50 支历史身份未变 | 是 |
| `UPDATE_GOLDEN` | **未执行，等待人工批准** |

## 4. 复现命令

```bash
# 生成 shadow（真实抓取 + SEC 交叉验证）
python -m benchmark.build_shadow_snapshot MSFT JPM BAC AMD

# 校验证据链
python - <<'PY'
from data.shadow_snapshot import verify_shadow
print(verify_shadow("shadow-20261128", "MSFT"))
PY

# 生成三份报告
UVE_FREEZE_CACHE=1 UVE_SNAPSHOT_ID=20261123 \
  python -m benchmark.report_reconciliation

# 验证不变量
python -m pytest tests/test_shadow_snapshot.py \
                 tests/test_shadow_phase_invariants.py \
                 tests/test_algorithm_dependency_fingerprint.py -q
```
