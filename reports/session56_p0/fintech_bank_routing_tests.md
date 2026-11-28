# FinTech / Bank Routing Tests — Session #56 P0

## 测试文件

`tests/test_fintech_bank_routing.py` — **19 项，全部通过**

## Classification（8 项）

| 测试 | 断言 |
|---|---|
| `test_bank_label_classifies_as_bank` | BANK 标签 → `FinancialBusinessModel.BANK` |
| `test_payment_network_has_no_loan_book` | 比率 0.025 → `PAYMENT_NETWORK` |
| `test_fintech_lender_is_not_a_bank` | 比率 0.40 → `FINTECH_LENDER`（≠ BANK）|
| `test_insurance_is_other_financial_not_bank` | 保险 → `OTHER_FINANCIAL` |
| `test_non_financial_is_not_financial` | 半导体 → `NOT_FINANCIAL` |
| `test_fintech_without_interest_expense_is_not_routed_to_bank` | 缺字段 → `OTHER_FINANCIAL` |
| `test_fintech_without_revenue_is_not_routed_to_bank` | 无营收 → `OTHER_FINANCIAL` |
| `test_classification_is_traceable` | 5 种类型均有非空理由字符串 |

## Routing（7 项）

| 测试 | 断言 |
|---|---|
| `test_bank_gets_bank_models` | BANK 路由含 Bank RIM + Bank DDM |
| `test_payment_network_is_excluded_from_bank_models` | PAYMENT_NETWORK 不含两者，且出现在 `not_applicable` |
| `test_payment_network_keeps_fcff_models` | PAYMENT_NETWORK 保留 DCF + ReverseDCF |
| `test_fintech_lender_keeps_bank_models` | **真放贷机构不丢银行模型**（NU 回归护栏）|
| `test_insurance_never_gets_bank_models` | 保险永不含银行模型 |
| `test_unknown_financial_does_not_enter_bank_rim` | 无贷款账证据 → 不进 Bank RIM |
| `test_na_reason_recorded_for_excluded_bank_model` | 拒绝原因写入 `na_reasons` 且提及 FinTech |

## Mutation（4 项）

| 测试 | 防御的退化 |
|---|---|
| `test_visa_forced_to_bank_would_be_caught` | 支付网络被当 BANK 时银行模型会出现 → 失败 |
| `test_jpm_downgraded_to_payment_network_would_be_caught` | 银行被当支付网络 → 失败 |
| `test_missing_classification_is_not_guessed_as_bank` | 删掉证据不得静默猜成银行 |
| `test_bank_models_never_come_from_the_label_alone` | 仅凭 FINTECH 标签永不产生银行模型（遍历 ie=None/1.0/7.5e7）|

## Mutation 有效性验证

测试只有能失败才有价值。因此**实际回滚修复**验证过：

重新把 `Bank DDM`/`Bank RIM` 写回 `MODELS_BY_TYPE[FINTECH]`，并移除业务模型闸门后：

```
5 failed, 14 passed
FAILED ...::test_payment_network_is_excluded_from_bank_models
FAILED ...::test_unknown_financial_does_not_enter_bank_rim
FAILED ...::test_na_reason_recorded_for_excluded_bank_model
FAILED ...::test_visa_forced_to_bank_would_be_caught
FAILED ...::test_bank_models_never_come_from_the_label_alone
```

恢复修复后：`19 passed`。

## 全库回归

```
1165 passed, 2 skipped
```

基线 1146 + 新增 19 = 1165，零失败、零 skip 变化。
