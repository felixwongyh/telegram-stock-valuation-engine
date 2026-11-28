# 50-Ticker Regression Gate — Bank Operating Income Suppression

Snapshot `UVE_SNAPSHOT_ID=20261123`, `UVE_FREEZE_CACHE=1`. Universe from
`benchmark/registry.py` (exactly 50 tickers). Baseline is
`benchmark/results/raw_facts.json` as committed before the fix; post-fix run is
the same command re-executed against the same frozen snapshot.

Machine-readable diff: `benchmark_50_postfix_report.json`.

## Acceptance criteria

| Criterion | Result |
|---|---|
| 50/50 executed | **Pass** — 50 of 50, no fetch errors |
| JPM/BAC/GS bank operating income suppressed | **Pass** — all three now `None` |
| JPM/BAC/GS Bank DDM & RIM unchanged | **Pass** — bit-identical (see below) |
| CB/V/BRK-B operating income unchanged | **Pass** — 14.596B / 29.874B / 101.277B identical |
| Other tickers free of unexpected field changes | **Pass** — 47/50 have zero field diffs |
| Golden drift explained | **Pass** — 3 tickers changed, all explained below |

## What changed, and only this

3 of 50 tickers differ. Every difference is one of three fields:

| Ticker | Field | Before | After |
|---|---|---|---|
| JPM | `operating_income` | 186,249,682,034.90 | `None` |
| BAC | `operating_income` | 123,717,465,980.53 | `None` |
| GS | `operating_income` | 106,031,653,621.12 | `None` |
| JPM/BAC/GS | `rd_direct_notes` | 2 entries | + `TTM operating_income missing` |
| JPM | `classification_confidence` | 0.872 | 0.708 |
| BAC | `classification_confidence` | 0.994 | 0.998 |
| GS | `classification_confidence` | 0.933 | 0.733 |

The note is the audit trail for the suppression — a field that vanishes without
explanation is indistinguishable from a bug.

## Why classification confidence moved

`classification/taxonomy.py:1078` computes `operating_margin = ttm.operating_income
/ ttm.revenue`, which feeds the ML feature vector, which feeds confidence. With
the field gone, the margin is missing rather than a fabricated ~0.94, so the
feature vector shifts and confidence moves with it.

This is a correct consequence, not collateral damage: the old confidence was
partly built on a number that was wrong by construction. The *verdict* is
unchanged in all three cases — `financial_business_model = Bank`, routed to
`P/E, P/B, Bank DDM, Bank RIM` — because bank identity is settled by the
`BANK_HOLDING_COMPANIES` registry and deposit structure, not by this ratio.
BAC moving *up* 0.004 while JPM and GS move down confirms the ratio is one
input among several, not a thumb on the scale.

## Valuation zero-drift, verified in isolation

The first comparison I ran simulated "before" by emptying `BANK_HOLDING_COMPANIES`,
which also changed classification — a confounded experiment. Redone by injecting
only the old `operating_income` value back into otherwise identical objects:

| Ticker | P/E | P/B | Bank DDM | Bank RIM |
|---|---|---|---|---|
| JPM | 269.829051738457 | 148.22337691384058 | 104.21381790075398 | 145.2566392734194 |
| BAC | 47.08446360319299 | 45.504777373308634 | 17.703575190128184 | 38.47523769855623 |
| GS | 794.3063449508404 | 447.7696447345231 | 257.38976528925605 | 426.2326373439123 |

Identical to full float precision before and after. Bank DDM/RIM never read the
field, which is why a data-correctness fix lands with zero valuation drift.

Note these differ from the figures quoted in the earlier session summary
(JPM P/E 201.56338983050847 etc.). Those came from `SyntheticDataProvider`;
these are the real cached snapshot. The zero-drift conclusion holds on both,
but the numbers are not interchangeable.

## A third synthesis path, found by this gate

This run caught something the unit tests had missed. `FinancialNormalizer.
fill_derived_fields` rebuilds EBIT as `net_income + interest_expense + income_tax`
and writes it back into `operating_income`. The provider-layer fix therefore
survived only until normalization, after which the benchmark still saw
186.2B / 123.7B / 106.0B.

Guarded now in `data/normalizer.py`, with three tests added and mutation-checked:

| Mutation | Caught |
|---|---|
| Remove the normalizer guard | 2 tests fail |
| Widen the guard to all tickers | 1 test fails |

The 50-stock gate earned its place: it found a real leak that 16 passing unit
tests did not.
