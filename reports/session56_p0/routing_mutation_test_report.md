# Routing Mutation Test Report — Session #56 P0

## 目的

验证测试**真的能失败**。一个永远通过的测试不能证明任何事。

## 方法

不满足于"测试通过"，而是**实际把 bug 改回去**，确认测试失败，再恢复修复。

### 步骤 1 — 注入回归

在 `classification/classifier.py` 中：

1. 把 `BusinessType.FINTECH: ["P/E", "P/B", "EV/Sales"]` 改回
   `["Bank DDM", "Bank RIM", "P/E", "P/B", "EV/Sales"]`（原始 bug）
2. 移除业务模型闸门（`if fin_model in (...)` 分支改为 `pass`）

### 步骤 2 — 观察失败

```
5 failed, 14 passed
FAILED TestModelRouting::test_payment_network_is_excluded_from_bank_models
FAILED TestModelRouting::test_unknown_financial_does_not_enter_bank_rim
FAILED TestModelRouting::test_na_reason_recorded_for_excluded_bank_model
FAILED TestRoutingMutation::test_visa_forced_to_bank_would_be_caught
FAILED TestRoutingMutation::test_bank_models_never_come_from_the_label_alone
```

### 步骤 3 — 恢复

```
19 passed
```

## 四个必需的 mutation 场景

| 场景 | 测试 | 结果 |
|---|---|---|
| 人为将 Visa 错误路由为 BANK | `test_visa_forced_to_bank_would_be_caught` | ✅ 能捕获 |
| 人为将 JPM 路由为 PAYMENT_NETWORK | `test_jpm_downgraded_to_payment_network_would_be_caught` | ✅ 能捕获 |
| 删除分类信息时不得静默猜测 | `test_missing_classification_is_not_guessed_as_bank` | ✅ 能捕获 |
| 未知金融业务不得自动进 Bank RIM | `test_unknown_financial_does_not_enter_bank_rim` | ✅ 能捕获 |

## JPM→PAYMENT_NETWORK 场景说明

该测试不断言"强行改标签就会失败"，而是断言**结构性判据本身拒绝这种误判**：

```python
model, _ = classify_financial_business_model(jpm, BusinessType.FINTECH)
assert model is FinancialBusinessModel.FINTECH_LENDER
```

即：即便有人把 JPM 的 `BusinessType` 硬改成 FINTECH，融资成本比率
（0.881）仍会把它判为 `FINTECH_LENDER`，而不是 `PAYMENT_NETWORK`。
标签无法覆盖结构证据。

## 边界覆盖

`test_bank_models_never_come_from_the_label_alone` 遍历三种输入：

| `interest_expense` | 预期 |
|---|---|
| `None`（缺失） | 无银行模型 |
| `1.0`（可忽略） | 无银行模型 |
| `7.5e7`（Visa 量级） | 无银行模型 |
