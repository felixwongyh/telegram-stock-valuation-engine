# U-2 Inference Audit

**Scope:** every `DERIVED`, `ESTIMATED` and `IMPUTED` field the pipeline can
produce, audited against the five Phase 1 rules.
**Snapshot set:** `20261123`, frozen, 49 of 50 benchmark tickers present.
**Date:** Session #59.

---

## 0. Summary

| Finding | Severity | State |
|---|---|---|
| `fill_derived_fields` filled 9 fields with **no provenance at all** | **high** | fixed |
| TTM `interest_expense` / `income_tax` silently replaced `None` with `revenue x prior ratio` | **high** | fixed, now `ESTIMATED` |
| Four post-construction derivations in `_build_statements` were unstamped | medium | fixed |
| `REPORTED` fields carried no `source_fields` (untraceable) | medium | fixed |
| TTM sum silently skipped a missing quarter, understating the total | medium | fixed, now `IMPUTED` |
| `provenance_notes` covered 1 of 11 DCF inputs | medium | fixed |
| Every frozen snapshot is `UNKNOWN_LEGACY` | **known limitation** | not fixable without re-snapshot |

The last line is the one that matters most and cannot be coded away: **0 of 7471
fields in the frozen set are `REPORTED`.** The snapshot format predates the
provenance schema, so on load every field without an existing record is labelled
`UNKNOWN_LEGACY` rather than guessed at. That is the honest label, and it means
the current benchmark's data lineage is *recorded as unknown*, not *established*.

---

## 1. Audit record schema

`FieldProvenance` (in `data/provenance.py`) now carries every column the brief
names:

| Column | Source | Note |
|---|---|---|
| `field_name` | dict key | |
| `origin_type` | writer | `reported`/`derived`/`estimated`/`imputed`/`unknown_legacy` |
| `availability` | writer | `available`/`missing`/`not_applicable`/`invalid` |
| `source_fields` | writer | concrete field names read |
| `derivation_method` | writer | key into `ALGORITHM_VERSIONS` |
| `algorithm_version` | registry lookup | `None` if the method is unregistered (deliberate) |
| `input_hash` | `compute_input_hash(input_values)` | SHA-256/16 of the normalised input values |
| `output_value` | read from the statement after assignment | |
| `generated_at` | UTC ISO-8601 at write time | |

`availability` is a separate axis from `origin_type` on purpose: a
`NOT_APPLICABLE` field has no number whose origin could be described, and
collapsing the two forces a value to surrender one of the two facts.

`input_hash` normalises floats to 12 significant digits and sorts keys, so two
runs over the same numbers produce the same digest while a meaningful change does
not.

---

## 2. Complete inference inventory

Every site that writes an inferred value, and what it now records.

### 2.1 `data/providers.py::_build_statements`

| Field | Method | Origin | Inputs |
|---|---|---|---|
| `ebit`, `operating_income` | `NI_PLUS_INTEREST_PLUS_TAX` | IMPUTED | net_income, interest_expense, income_tax |
| `ebit`, `operating_income` | `REVENUE_X_PRIOR_MARGIN` | IMPUTED | revenue, prior margin |
| `depreciation_amortization` | `REVENUE_X_PRIOR_DA_RATIO` | IMPUTED | revenue, prior ratio |
| `ebitda` | `EBIT_PLUS_DA` | IMPUTED | ebit, depreciation_amortization |
| `operating_cash_flow` | `OCF_FROM_FCF_MINUS_CAPEX` | DERIVED | free_cash_flow, capex |
| `free_cash_flow` | `FCF_FROM_OCF_PLUS_CAPEX` | DERIVED | operating_cash_flow, capex |
| `eps` | `EPS_FROM_NI_OVER_SHARES` | DERIVED | net_income, shares_outstanding |
| `gross_profit` | `GROSS_PROFIT_FROM_REVENUE_MINUS_COGS` | DERIVED | revenue, cost_of_revenue |

The last four were assigned *after* `_stamp_statement_provenance` had already
run, so they previously kept either a `REPORTED` label belonging to a vendor
value that did not exist, or no label at all. Both were wrong; both are fixed.

### 2.2 `data/normalizer.py::fill_derived_fields`

| Field | Method | Origin | Trigger |
|---|---|---|---|
| `gross_profit` | `GROSS_PROFIT_FROM_REVENUE_MINUS_COGS` | DERIVED | revenue + cogs present |
| `cost_of_revenue` | `COGS_FROM_REVENUE_MINUS_GROSS_PROFIT` | DERIVED | revenue + gross profit present |
| `ebit` | `EBIT_FROM_OPERATING_INCOME` | DERIVED | op income present, ebit absent |
| `interest_expense` | `REVENUE_X_PRIOR_INTEREST_RATIO` | **ESTIMATED** | TTM revenue present, field absent |
| `income_tax` | `REVENUE_X_PRIOR_TAX_RATIO` | **ESTIMATED** | TTM revenue present, field absent |
| `ebit`, `operating_income` | `NI_PLUS_INTEREST_PLUS_TAX` | IMPUTED | ebit absent, addbacks available |
| `ebitda` | `EBIT_PLUS_DA` | DERIVED | ebit + D&A present |
| `free_cash_flow` | `FCF_FROM_OCF_PLUS_CAPEX` | DERIVED | OCF + capex present |
| `change_in_nwc` | `NWC_FROM_NOPAT_DA_CAPEX_FCF` | DERIVED | inputs resolvable |
| `eps` | `EPS_FROM_NI_OVER_SHARES` | DERIVED | NI + shares present |

The two `ESTIMATED` entries are the ones that used to be invisible. Measured on
the frozen set before the fix: MSFT TTM `interest_expense` went from `None` to
`3.185e9` and `income_tax` from `None` to `3.360e10` with `prov=None`. A number
appeared where there was no disclosure, and nothing recorded it. That is the
"missing data silently replaced by an estimate" that rule 5 forbids.

### 2.3 TTM construction

| Field set | Method | Origin | Condition |
|---|---|---|---|
| summed fields | `TTM_SUM_4Q` | DERIVED | all four quarters present |
| summed fields | `TTM_SUM_4Q` | **IMPUTED** | any quarter `None` (value is understated) |
| `eps` | `TTM_EPS_SUM_4Q` | DERIVED | |
| all fields | `TTM_FROM_LATEST_ANNUAL` | **ESTIMATED** | no quarters; annual relabelled |

The partial-quarter case is design §7.2: summing three of four quarters yields
roughly 75% of the real total, and the result looks like an ordinary number. It
is now `IMPUTED` and names the gap in its `input_values`.

### 2.4 Suppression (not inference, but part of the record)

| Field | Condition | Availability | Origin |
|---|---|---|---|
| `operating_income`, `ebit` | bank | `NOT_APPLICABLE` | `None` |
| `ebitda` | bank, vendor value was a derived orphan | `INVALID` | `None` |

---

## 3. Rules, and how each is enforced

### Rule 1 — same inputs + same algorithm version must give the same result

`input_hash` is computed from the input *values*, and `algorithm_version` from
the registry. Two independent runs of the normalizer over the same snapshot
produce byte-identical `(field, input_hash, output_value, algorithm_version)`
tuples. Verified on MSFT, JPM, BAC:

```
MSFT: reproducible=True  n_inferred=4
JPM:  reproducible=True  n_inferred=3
BAC:  reproducible=True  n_inferred=3
```

### Rule 2 — when an input changes, the blast radius must be identifiable

- `drifted_fields(stmt)` reports any field whose current value no longer matches
  its recorded `output_value`.
- `input_hash` changes if and only if an input value changes materially, so two
  records can be compared to prove *whether* the change touched them.
- `source_fields` names what was read, so a changed source can be traced forward
  to the fields that consumed it.

### Rule 3 — an algorithm version change must be recorded

`data/algorithm_versions.py` holds a registry of method -> (version,
implementing function). `source_fingerprint()` hashes the implementation's AST
(not its text), so:

- a comment or re-indent does **not** raise an alarm (verified),
- a semantic edit without a version bump **does** (verified: `+capex` -> `-capex`
  was flagged as `implementation changed without a version bump`),
- a version bump without refreshing `data/provenance_baseline.json` is also
  flagged.

`tests/test_provenance_breakage.py::test_breakage_2_the_live_baseline_is_current`
fails if the committed baseline drifts from the code, which forces the change to
be reviewed rather than absorbed.

### Rule 4 — `UNKNOWN_LEGACY` may not be auto-promoted to `REPORTED`

`_FORBIDDEN_UPGRADES` names the six illegal transitions and
`assert_no_forbidden_upgrade()` raises `ProvenanceError`:

```
unknown_legacy -> reported   unknown_legacy -> derived
estimated      -> reported   estimated      -> derived
imputed        -> reported   imputed        -> derived
```

`__post_init__` never invents a version for an unregistered method, and the
legacy backfill only ever writes `UNKNOWN_LEGACY`.

### Rule 5 — missing data may not be silently replaced by an estimate

Every branch in §2 now stamps. `coverage_summary()["derived_without_audit"]`
returns the list of inferred fields lacking a version or hash; it is **empty for
all 49 tickers**.

---

## 4. Per-field sample (MSFT TTM, frozen snapshot)

```
cost_of_revenue    derived    v=1  hash=b50a5f86daf34bd9  out=112051000000.0
eps                derived    v=1  hash=fd5b97348833bf80  out=19.191469321851454
income_tax         estimated  v=1  hash=f505c40bacd9221a  out=33601633096.17013
interest_expense   estimated  v=1  hash=941fcb1d52c3dad1  out=3185290743.4026737
```

Each of the four is reproducible, versioned, attributed, and timestamped. The
other 156 TTM fields on MSFT are `UNKNOWN_LEGACY` (see §0).

---

## 5. What this audit does *not* establish

- **It does not establish that the numbers are right.** It establishes where each
  one came from. A `DERIVED` value can still be derived wrongly; the version and
  hash make that *reproducible*, not *correct*.
- **It does not give the benchmark reported lineage.** 91.1% of fields are
  `UNKNOWN_LEGACY` until the set is re-snapshotted with the current schema.
- **It does not version the models** (DCF/RIM/DDM) — only the data derivations.
  A model-parameter change is out of scope for U-2.
