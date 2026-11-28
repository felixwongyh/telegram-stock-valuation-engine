# Financial Model Routing Report — Session #56 P0

## 结论

**Visa 的模型路由真的变了，不是改了显示标签。**

`applicable_models` 是路由的唯一真相源（`ModelRouter.run_all` 直接遍历它）。
Visa 的该字段移除了 `Bank DDM` 与 `Bank RIM`，因此两个银行模型**不再被执行**。

## 路由证据（快照 20261123，真实管线）

| 股票 | business_type | financial_business_model | applicable_models | Bank 模型 |
|---|---|---|---|---|
| JPM | Bank | Bank | P/E, P/B, **Bank DDM, Bank RIM** | ✅ 保留 |
| BAC | Bank | Bank | P/E, P/B, **Bank DDM, Bank RIM** | ✅ 保留 |
| GS | Bank | Bank | P/E, P/B, **Bank DDM, Bank RIM** | ✅ 保留 |
| **V** | FinTech | **PaymentNetwork** | DCF, ReverseDCF, P/E, EV/Sales, P/B, SOTP | **❌ 已移除** |
| CB | Insurance | OtherFinancial | P/E, P/B | ❌ 从未有 |
| BRK-B | Insurance | OtherFinancial | P/E, P/B | ❌ 从未有 |

## Visa 前后对比

```
before: ['DCF','ReverseDCF','P/E','EV/Sales','P/B','Bank DDM','Bank RIM','SOTP']
after : ['DCF','ReverseDCF','P/E','EV/Sales','P/B','SOTP']
removed: {'Bank DDM', 'Bank RIM'}
added  : {}
```

Visa 保留 `DCF` / `ReverseDCF`——按裁决要求「如果标准 FCFF 模型已经支持，
就使用该模型」。已支持，因此使用，而非返回 MODEL_NOT_APPLICABLE。
**没有为了排除而强行套用其他模型**：模型集合只是移除了不适用的银行模型。

## 50 股路由变化审计

全池 50 只，`applicable_models` 发生变化的**只有 V 一只**：

```
ROUTING CHANGES (applicable_models): ['V']
```

其余 49 只（含 JPM/BAC/GS/CB/BRK-B）路由逐项相同。

## 分类与路由分别记录

Collector 现在分别落盘两个轴，便于区分"标签变了"与"路由变了"：

| 字段 | 含义 |
|---|---|
| `business_type` | 企业业务分类（原字段，语义未变） |
| `financial_business_model` | 业务模型（本会话新增） |
| `financial_business_model_reason` | 判定理由（本会话新增） |
| `applicable_models` | 实际路由结果（原字段，语义未变） |

## MODEL_NOT_APPLICABLE 路径

路由对不支持的模型给出显式拒绝，而非静默跳过：

```
na_reasons["Bank RIM"] = "Not applicable for business type FinTech"
```

对 Visa 实测已写入该原因（见 `test_na_reason_recorded_for_excluded_bank_model`）。

对于**任何模型都不适用**的业务，`applicable_models` 为空列表，路由不执行任何
模型——即 `MODEL_NOT_APPLICABLE`。当前 50 股池中无此情况。

## Collector None 契约

未改动。`TickerFacts` 中 `business_type`、`is_financial_institution` 等仍为
`Optional`，分类失败时保持 `None` 并记录 `notes`，不会因为新增字段而变成猜测值。
