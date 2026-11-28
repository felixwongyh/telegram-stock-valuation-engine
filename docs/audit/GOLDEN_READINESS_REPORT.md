# Golden Readiness Report

**Phase 4 deliverable.** Generated with `UPDATE_GOLDEN=1` **prohibited** for this
session — no golden file was regenerated, and no expected value was edited.

Snapshot set: `20261123`. Benchmark: 50 tickers.

---

## 1. Bottom line

**The current golden set cannot be legally re-frozen.** Not "should not" —
*cannot*. The frozen snapshots store normalised statements, not the vendor
timeseries they were built from, and they predate the provenance schema. There is
no input available from which `REPORTED` provenance could be recovered.

A re-freeze requires **re-fetching** every ticker, which produces a **new**
snapshot id. That is a different, larger decision: it changes the numbers, not
just the labels.

---

## 2. Snapshot inventory

| Item | Count |
|---|---|
| Benchmark tickers | 50 |
| `*_20261123.json` files on disk | 50 |
| Of those, actual benchmark tickers | 49 |
| Non-stock file in the directory | 1 (`^TNX`, the 10-year yield series) |
| Benchmark tickers with a snapshot | 49 |
| Benchmark tickers **without** a snapshot | 1 (**AMD**) |

The `^TNX` file is not a corrupted entry — it is a macro series used for the
risk-free rate, stored in the same directory. It is not a stock and is not part
of the 50.

### AMD: present as 20261128, absent as 20261123

`AMD_20261128.json` exists. `AMD_20261123.json` does not. These are different
snapshots taken five days apart, and the difference is the whole point:

- The `20261123` run has no AMD data (the file was destroyed, no backup exists).
- Writing the `20261128` payload under the `20261123` name would claim a
  provenance the data does not have — **prohibited**, and not done.

The gap is asserted in `tests/test_provenance_four_tickers.py` and in
`tests/test_status_matrix.py::KNOWN_MISSING`.

---

## 3. Provenance coverage (49 tickers actually loaded)

| Origin | Fields | Share |
|---|---|---|
| `UNKNOWN_LEGACY` | 6809 | **91.14%** |
| `DERIVED` | 479 | 6.41% |
| `ESTIMATED` | 93 | 1.24% |
| `IMPUTED` | 0 | 0.00% |
| `REPORTED` | 0 | **0.00%** |
| none (suppressed) | 90 | 1.20% |
| **Total** | **7471** | 100% |

`derived_without_audit`: **empty for all 49 tickers** — every inferred value now
carries a version and an input hash.

### What the 0% REPORTED means

Every number in the frozen set whose origin was not computable is labelled
`UNKNOWN_LEGACY`. It is **not** labelled `REPORTED`, because nobody recorded that
the company filed it. The label is accurate. The consequence is that the
benchmark currently **cannot distinguish a filed figure from a reconstructed
one** — the distinction exists in the schema and is exercised in the builder, but
the stored data does not carry it.

The 479 `DERIVED` and 93 `ESTIMATED` entries are the ones *this* pipeline
computed at load time from the stored numbers, so they are known-good as records
even though their inputs are `UNKNOWN_LEGACY`.

---

## 4. Which tickers can be legally rebuilt

| Category | Count | Tickers |
|---|---|---|
| **Rebuildable from snapshot** (provenance recomputable) | 0 | — |
| **Loadable but legacy-labelled** | 49 | all benchmark tickers with a `20261123` file |
| **Not rebuildable — data absent** | 1 | AMD |
| **Re-fetch required for real provenance** | 50 | all |

"Rebuildable" in the strict sense means: the stored inputs let the provenance be
reconstructed *and attributed to a filed source*. That would require the vendor
timeseries. Inspecting a snapshot shows why it is unavailable:

```
payload keys: __type__, ticker, source, annual_income, quarterly_income, ttm,
              annual_balance_sheet, ..., market, quality, historical_prices, ...
annual_income[0] keys: __type__, period_end, period_type, currency, revenue, ...
                       has field_provenance: False
```

Only the normalised statements and market data are stored. The raw
`TotalRevenue` / `OperatingIncome` timeseries that `_build_statements` consumed
is not in the snapshot, so `REPORTED` cannot be recovered from it.

---

## 5. Inference algorithm versions

Current registry (`data/algorithm_versions.py`), all at version **1**:

| Method | Version | Implementation |
|---|---|---|
| `NI_PLUS_INTEREST_PLUS_TAX` | 1 | `_build_statements` |
| `REVENUE_X_PRIOR_MARGIN` | 1 | `_build_statements` |
| `REVENUE_X_PRIOR_DA_RATIO` | 1 | `_build_statements` |
| `EBIT_PLUS_DA` | 1 | `_build_statements` |
| `OCF_FROM_FCF_MINUS_CAPEX` | 1 | `_build_statements` |
| `FCF_FROM_OCF_PLUS_CAPEX` | 1 | `_build_statements` / `fill_derived_fields` |
| `GROSS_PROFIT_FROM_REVENUE_MINUS_COGS` | 1 | both |
| `COGS_FROM_REVENUE_MINUS_GROSS_PROFIT` | 1 | `fill_derived_fields` |
| `EBIT_FROM_OPERATING_INCOME` | 1 | `fill_derived_fields` |
| `REVENUE_X_PRIOR_INTEREST_RATIO` | 1 | `fill_derived_fields` |
| `REVENUE_X_PRIOR_TAX_RATIO` | 1 | `fill_derived_fields` |
| `EPS_FROM_NI_OVER_SHARES` | 1 | both |
| `NWC_FROM_NOPAT_DA_CAPEX_FCF` | 1 | `infer_change_in_nwc` |
| `TTM_SUM_4Q` | 1 | `compute_ttm_from_quarters` |
| `TTM_EPS_SUM_4Q` | 1 | `_ttm_eps` |
| `TTM_FROM_LATEST_ANNUAL` | 1 | `ensure_ttm` |
| `PRIOR_MARGIN_FALLBACK` | 1 | `_build_statements` |

`python -m data.algorithm_versions` reports **0 mismatch(es)** against
`data/provenance_baseline.json`.

---

## 6. Potential divergence from the current golden set

Provenance is metadata: it does not enter any arithmetic. Verified — the golden
fingerprint tests pass unchanged (38 passed), and the benchmark tally is
identical to before this work:

| Metric | Before | After |
|---|---|---|
| `Solved` | 31 | **31** |
| `None` | 10 | 10 |
| `No Solution In Range` | 9 | 9 |

One behavioural change was deliberately made this session, and it is *additive*
only: `provenance_notes()` now reports 11 DCF inputs instead of 1. It adds caveat
strings; it does not change applicability or any valuation figure. Confirmed:
MSFT is still applicable and still solves, and the caveat count rose from 1 to 11.

`tests/golden/report_fingerprints.json` carries the two-line `recon_checks` 10->9
change from U-8 (JPM, BAC) — established in the previous session as correct and
unchanged here.

**No golden value was modified in this session.**

---

## 7. What a re-snapshot would change

If the set is re-fetched (new snapshot id, e.g. `20261129`):

1. Every field would be stamped `REPORTED` or `IMPUTED` by `_build_statements`,
   replacing 91% `UNKNOWN_LEGACY` with real origins.
2. The numbers themselves would move — five days of new filings and prices. The
   golden fingerprints would change for reasons unrelated to provenance.
3. AMD would come back with real data, resolving the asserted gap.
4. Solved count could move in either direction, and it must be explained, not
   accepted.

This is why it is a separate decision and not part of closing U-2.

---

## 8. Preconditions before a legitimate re-freeze

- [ ] A new snapshot id is chosen and recorded (never reuse `20261123`).
- [ ] AMD is re-fetched and its presence confirmed; the `KNOWN_MISSING` assertion
      in `test_status_matrix.py` is removed *because the gap closed*, not relaxed.
- [ ] `python -m data.algorithm_versions` reports 0 mismatches.
- [ ] `coverage_summary` shows a `REPORTED` share > 0 for every ticker.
- [ ] Every changed golden fingerprint is explained per ticker, with the reason
      (new period, price move, provenance-only) named.
- [ ] Solved count change, if any, is justified line by line.
