# benchmark/ — 50 只标的 Reverse DCF 验收

| 文件 | 作用 |
|---|---|
| `registry.py` | 50 只标的 + 每只的业务类型期望（用于校验路由） |
| `collector.py` | `TickerFacts`：跑完整流水线并抽取原始/派生事实，**从不抛异常** |
| `run_benchmark.py` | 跑全部 50 只，写 `results/raw_facts.json` |
| `audit.py` | A–D 四类基础检查（数据 / 数学 / 终值 / 行业路由） |
| `verify_fix.py` | **阶段三验收**：8 项检查 × 50 只 + 对基线漂移比对，0 硬失败才 exit 0 |
| `results/raw_facts.json` | 当前代码的结果快照 |
| `results/baseline_prefix.json` | 修复前的基线（用于漂移比对） |

## 用法

```bash
python benchmark/run_benchmark.py
python benchmark/verify_fix.py benchmark/results/raw_facts.json benchmark/results/baseline_prefix.json
```

## 复现 A/B 的前提：钉住数据

`treasury_yield` 缓存也会影响 WACC（Rf 直接进 CAPM）。只钉行情快照不够 —— 必须把
`.cache/treasury_yield/*.json` 一并固定到与基线相同的快照，否则 10Y 国债的日常波动
（实测 5.052% → 4.912%，−14bp）会让全部 WACC 同步偏移，被误读成代码回归。

判据：钉住后，原本已 Solved 的标的 **ΔWACC 应精确为 0**。

## 检查项语义

- `UNKNOWN` 不等于 `PASS`：无法评估时返回 UNKNOWN（如路由排除的标的没有 Reverse DCF）。
- `WARN` 表示诚实披露而非缺陷：`above_search_ceiling`（根在搜索上限之上）、
  `DATA_QUALITY_WARNING`（基准 FCF 为负，隐含增长不可解读）。
- `beta_adjusted` 是**选中 β 归一化后的值**，不必然是 raw 回归 β 的 Blume 收缩：
  选中自下而上 β 时两者是不同估计量，检查须按选择路径分支。
