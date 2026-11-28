# Routing Golden Drift Report — Session #56 P0

## 结论

Golden 指纹**零漂移**。18 只标的逐字段相同。

## Golden 测试

```
tests/test_golden_report.py — 3 passed
```

## 50 股全池路由漂移

对比修复前后 `benchmark/results/raw_facts.json`：

| 项目 | 结果 |
|---|---|
| 标的数量 | 50 → 50 |
| fetch 成功 | 50 → 50 |
| `applicable_models` 变化 | **仅 1 只：V** |
| `*_status` 变化 | **0** |
| 其它 49 只路由 | 逐项相同 |

## 唯一变化的标的

```
V:
  before: ['DCF','ReverseDCF','P/E','EV/Sales','P/B','Bank DDM','Bank RIM','SOTP']
  after : ['DCF','ReverseDCF','P/E','EV/Sales','P/B','SOTP']
  removed: {'Bank DDM', 'Bank RIM'}
  added  : {}
```

这是**预期纠错**：Visa 是收费型支付网络，不应使用贷款账估值模型。

## 新增字段（非行为变化）

`financial_business_model` / `financial_business_model_reason` 对全部 50 只
都是**新增**字段（修复前不存在，值为 `None`）。这不是漂移，是新增可追溯信息。

分布：

| 值 | 数量 |
|---|---|
| NotFinancial | 44 |
| Bank | 3 |
| OtherFinancial | 2 |
| PaymentNetwork | 1 |

## JPM / BAC / GS 漂移

零。见 `bank_regression_report.md`（`TOTAL DIFFS: 0`）。

## Visa 估值数值

Visa 的 `Bank DDM` / `Bank RIM` 结果不再产生，因此这两个模型的数值
从有到无——这是**路由纠错的结果**，不是公式变化。Visa 的 DCF / ReverseDCF /
P/E / EV/Sales / P/B / SOTP 数值未受影响。
