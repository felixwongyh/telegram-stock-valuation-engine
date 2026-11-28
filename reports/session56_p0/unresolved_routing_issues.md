# Unresolved Routing Issues — Session #56 P0

以下问题**本轮未解决**，需要后续决策。全部如实记录，不隐藏。

## 1. WFC / C / MA 未能在快照中验证（P0 清单要求）

裁决要求测试 JPM/BAC/GS/WFC/C/V/MA。当前快照 `20261123` 的缓存中
**没有 WFC、C、MA、AXP、PYPL、SOFI** 的数据：

```
FrozenSnapshotMissError: UVE_FREEZE_CACHE is set but no cached data for WFC
```

冻结快照机制正确地**拒绝**在冻结模式下抓取实时数据，因此无法在不污染
快照的前提下验证这 3 只。已用结构性判据的合成数据测试覆盖同类逻辑：

- `test_fintech_lender_is_not_a_bank`（SOFI/AXP/COF 类，比率 0.40）
- `test_payment_network_has_no_loan_book`（V/MA 类，比率 0.025）

**需要的决策**：是否为 WFC/C/MA 刷新快照。这属于数据操作，非代码问题。

## 2. FintechLender 尚无独立适用性判断

裁决要求 FINTECH_LENDER「需要独立适用性判断」。当前实现中，
`FINTECH_LENDER` 与 `BANK` **共享** Bank DDM/RIM 模型集。

这意味着 SOFI/AXP/COF 这类"有贷款账但非存款银行"的企业，仍会跑
银行 RIM。它们的融资结构（非存款、高资金成本）与 JPM 显著不同，
RIM 的假设可能不完全成立。

**本轮未改**，因为：改动会触及估值适用性规则，超出"只改分类与路由"的授权，
且 50 股池内无此类标的，无法做回归验证。

## 3. taxonomy 层仍把 Asset Management / Broker Dealer 映射到 BANK

`classification/taxonomy.py`：

```python
("fin.capital_markets",    "Capital Markets / Brokerage", "fin", BusinessType.BANK),
("fin.asset_management",   "Asset Management",            "fin", BusinessType.BANK),
("fin.exchange",           "Financial Data & Exchanges",  "fin", BusinessType.BANK),
("fin.generic",            "Financial Services (unspecified)", "fin", BusinessType.BANK),
```

按裁决，资管/券商/交易所应属 `OTHER_FINANCIAL`，**不允许自动进入 Bank RIM**。
但当前 `classify_financial_business_model` 对 `BusinessType.BANK` 直接返回
`BANK`，因此经 taxonomy 映射为 BANK 的资管公司仍会进入银行模型。

50 股池内无此类标的（CB/BRK-B 走 INSURANCE 分支），所以本轮未暴露。
但这是一个**真实存在的未修复缺口**。

**建议**：P0.1 修复，让 taxonomy 区分真正的银行与其它金融服务。

## 4. 结构性判据依赖 `interest_expense` 字段质量

判别完全依赖 `interest_expense` 与 `operating_income`。若数据源对某类企业
不报 `interest_expense`（如部分支付公司将其并入其他科目），分类会保守退回
`OTHER_FINANCIAL`——这**不会**误入银行模型（安全方向），但会失去 DCF 路由。

属于可接受的保守失效，但需在 P1 数据覆盖时一并核查。

## 5. 阈值 0.20 的样本外稳健性未验证

0.20 阈值基于已知种群（V 0.03 / MA 0.04 / PYPL 0.07 vs AXP 0.37 / COF 0.86 /
SOFI 0.69）。两簇间隔很大，但**样本外**（如新兴市场支付公司、混合型金融科技）
是否仍能正确分离，未经实证。

**建议**：P1 扩大样本时复核该阈值。

## 6. 未生成 MODEL_NOT_APPLICABLE 的真实案例

裁决要求"不支持的业务明确返回 MODEL_NOT_APPLICABLE"。代码路径已具备
（`applicable_models` 为空则不执行任何模型），但**50 股池内无任何标的天生
落入该状态**，因此该路径只有单元测试覆盖，无真实案例。
