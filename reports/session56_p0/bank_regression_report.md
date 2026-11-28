# Bank Regression Report — Session #56 P0

## 结论

JPM / BAC / GS 的估值结果**逐位不变**。零差异。

## 方法

同一快照（20261123）、同一数据缓存，分别在
`git stash`（修复前，HEAD=151e14e）与修复后运行同一脚本，
对比 4 个模型的 `status` / `value_per_share` / `beta_raw` / `beta_clamped`。

## 结果

```
TOTAL DIFFS: 0
```

| 股票 | 模型 | 修复前 | 修复后 | β_raw | 夹紧 |
|---|---|---|---|---|---|
| JPM | Bank DDM | 104.213818 | 104.213818 | 0.878506 | 否 |
| JPM | Bank RIM | 145.256639 | 145.256639 | 0.878506 | 否 |
| JPM | P/B | 148.223377 | 148.223377 | — | — |
| JPM | P/E | 269.829052 | 269.829052 | — | — |
| BAC | Bank DDM | 17.703575 | 17.703575 | 1.005161 | 否 |
| BAC | Bank RIM | 38.475238 | 38.475238 | 1.005161 | 否 |
| BAC | P/B | 45.504777 | 45.504777 | — | — |
| BAC | P/E | 47.084464 | 47.084464 | — | — |
| GS | Bank DDM | 257.389765 | 257.389765 | 1.367867 | **是** |
| GS | Bank RIM | **426.232637** | **426.232637** | 1.367867 | **是** |
| GS | P/B | 447.769645 | 447.769645 | — | — |
| GS | P/E | 794.306345 | 794.306345 | — | — |

GS Bank RIM `426.232637` 与 Session #55 记录的 `426.2326…` 一致。

## Session #55 字段语义保持不变

| 字段 | 语义 | 本会话 |
|---|---|---|
| `beta_raw` | 原始 Beta | 未改动 |
| `beta_selected` | 真正选中的 Beta | 未改动 |
| `valuation_beta` | 用于复现估值 Ke 的有效 Beta | 未改动 |
| `clamp_equivalent_beta` | 从夹紧后 Ke 反推的等效 Beta | 未改动 |

`models/bank.py`、`valuation/capm_engine.py`、`simulation/monte_carlo.py`
本会话**零改动**（见 `git diff --stat`）。

## 本轮明确未触碰

- RIM 数学公式 — 未改
- Beta Selection 规则 — 未改
- Cost of Equity 参数 — 未改
- Ke Clamp — 未改
- Monte Carlo 分布 — 未改
- Bank BetaChain — 未改

## Golden 指纹

```
tests/test_golden_report.py: 3 passed
```

18 只 golden 标的指纹零漂移，含 BAC（Bank）与 NU（FinTech 放贷机构）。

## 50 股覆盖

```
before: n=50 fetch_ok=50
after : n=50 fetch_ok=50
```

无标的状态变化（`*_status` 字段前后全等）。
