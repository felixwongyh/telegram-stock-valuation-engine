# Provenance Validation — four-ticker evidence

Covers Phase 2 (evidence on real tickers) and Phase 5 (intentional breakage).
Source tests: `tests/test_provenance_four_tickers.py`,
`tests/test_provenance_breakage.py`.

Snapshot pinned to `20261123` with `UVE_FREEZE_CACHE=1` for every test in this
document. No test fetches live data; no test writes a snapshot file.

---

## 1. Ticker selection and why

| Ticker | What it proves |
|---|---|
| `MSFT` | non-financial filer: derived + estimated values coexist with legacy unknown ones |
| `AMD`  | the destroyed snapshot stays absent — the honest state, asserted |
| `JPM`  | bank suppression: `NOT_APPLICABLE` / `INVALID`, and estimates still labelled |
| `BAC`  | second bank, same semantics, different numbers; no derived `ebitda` orphan |

---

## 2. MSFT

Measured on the frozen TTM statement (160 stamped fields):

| Class | Count | Example |
|---|---|---|
| `UNKNOWN_LEGACY` | 147 | `revenue`, `operating_income` — origin lost to the pre-schema format |
| `DERIVED` | 11 | `eps = NI / shares`, `cost_of_revenue = revenue - gross_profit` |
| `ESTIMATED` | 2 | `interest_expense`, `income_tax` from prior-year ratios |
| `REPORTED` | 0 | none survivable through the legacy backfill |

Every derived/estimated field carries method, version, input hash, output value,
timestamp and source fields. `drifted_fields()` returns `[]`, i.e. no stamped
value disagrees with its own record.

The specific defect this audit closes, visible in isolation:

```
interest_expense:  before=None  after=3.185e9   prov=None   <-- silent estimate
income_tax:        before=None  after=3.360e10  prov=None   <-- silent estimate
```

After the fix both are `ESTIMATED`, method `REVENUE_X_PRIOR_*_RATIO`, version 1,
with a hash over `{revenue, ratio}`.

---

## 3. AMD — the gap is asserted, not smoothed

`AMD_20261123.json` does not exist. It was destroyed by the P0-1 deletion and no
backup exists (`raw_facts.json` holds 20 flat fields with `cash`, `equity` and
`capex` all `None`, and no three-statement payload).

Three separate tests hold that line:

1. `test_amd_snapshot_is_absent_and_that_is_the_expected_state` — fails if the
   file reappears, so a recovery is recorded rather than silently absorbed.
2. `test_amd_load_raises_frozen_snapshot_miss` — a missing snapshot under freeze
   raises `FrozenSnapshotMissError`; there is no network fallback that could let
   2026-11-28 data stand in for 2026-11-23.
3. `test_no_snapshot_file_was_written_during_this_session` — a guard against a
   "helpful" rebuild.

Live AMD data *is* fetchable and its TTM revenue (45.436B) matches the period, so
the temptation to write it under the old snapshot id is real. Doing so would be
provenance fraud: the file would claim 2026-11-23 while containing 2026-11-28
numbers. It was not done.

---

## 4. JPM and BAC — banks

| Field | JPM | BAC | Meaning |
|---|---|---|---|
| `operating_income` | `NOT_APPLICABLE` | `NOT_APPLICABLE` | a bank has no operating-income line |
| `ebit` | `NOT_APPLICABLE` | `NOT_APPLICABLE` | vendor `operatingIncome` for a bank *is* EBIT |
| `ebitda` | `INVALID` | `INVALID` | vendor sent a derived orphan whose only input was deleted (U-8) |

All three are `REFUSE` for a core model, for both banks, and the test asserts it
per field rather than trusting the aggregate.

Routing a bank out of DCF does **not** license anonymous numbers elsewhere:
`interest_expense` and `income_tax` estimates on both banks are `ESTIMATED` with
a version and hash (JPM: 1.069e11 and 1.699e10; BAC: 8.357e10 and 7.653e9).

---

## 5. Cross-ticker invariants (all hold on all three present tickers)

| Invariant | Test |
|---|---|
| no inferred field lacks a version or hash | `test_no_inferred_field_is_missing_its_audit_record` |
| no `REPORTED` value lacks a source | `test_no_field_is_labelled_reported_without_a_source` ⚠ see below |
| provenance survives a real cache round trip | `test_provenance_survives_a_real_cache_round_trip` |

⚠ **Honest limitation.** The first two are checked on the frozen snapshots, but
those contain **zero** `REPORTED` fields, so the "no unsourced REPORTED" check
holds vacuously there. It is kept for the post-re-snapshot state, and the real
proof lives in `test_reported_path_stamps_a_source_for_every_vendor_field`,
which drives `_build_statements` directly with synthetic vendor timeseries and
confirms each of 9 vendor fields is stamped `REPORTED` with
`source_fields == [name]`.

That test exists because of a bug this session found: `_stamp_statement_provenance`
passed `source_field_name` but never `source_fields`, so every `REPORTED` value
was untraceable. It was invisible on the frozen set (no REPORTED fields) and only
showed up when the builder was driven directly.

---

## 6. Phase 5 — six breakages, and the test that catches each

Each row was verified two ways: the test passes on correct code, **and** the
production code was deliberately broken to confirm the test fails.

| # | Breakage | Sabotage applied | Caught by | Result |
|---|---|---|---|---|
| 1 | delete the source record | `stamp()` returns before writing | 12 tests | fails |
| 2 | change a derivation, keep the version | `+capex` -> `-capex` in `infer_change_in_nwc` | `test_breakage_2_the_live_baseline_is_current` | 1 failed |
| 3 | promote `UNKNOWN_LEGACY` -> `REPORTED` | backfill emits `REPORTED` | 5 tests | fails |
| 4 | relabel `ESTIMATED` -> `REPORTED` | prior-ratio stamp emits `REPORTED` | 6 tests | fails |
| 5 | turn `REFUSE` into `ALLOW` | gate returns `ALLOW` for unusable | 5 + 3 tests | fails |
| 6 | make `IMPUTED` a DCF rejection | `is not ALLOW` instead of `is REFUSE` | 4 tests | fails |

### Note on breakage 2

The first fingerprint implementation hashed normalised *text*, so a comment-only
edit was flagged as a change. That contradicts the rule it was meant to serve
(record behaviour changes, not formatting). It was replaced with an AST
fingerprint, then re-verified both ways:

```
comment-only edit          -> 0 mismatch(es)      (no false alarm)
+capex -> -capex edit      -> 1 mismatch(es)      (caught)
```

### Note on breakage 6

This is not hypothetical. It is the regression actually introduced and caught in
Session #59: the first DCF gate appended a reason for *any* non-`ALLOW` decision,
and `applicability_check` reads any reason as "not applicable", so every legacy
ticker lost its DCF. The test asserts both directions — `IMPUTED` must not
refuse, and the caveat must still be traceable via `provenance_notes()`.

---

## 7. DCF caveat traceability (Phase 3)

`DCFModel.provenance_notes()` covers all **11** inputs a DCF consumes, not just
`operating_income`. On MSFT it returns 11 caveats while
`applicability_check` still returns `True` — allowed, and visible.

A caveat list that named one field while nine inferred others were silently used
would be worse than no list, because it reads as complete. Before this session it
named one.

---

## 8. Reproduction

```bash
# four-ticker evidence
UVE_SNAPSHOT_ID=20261123 UVE_FREEZE_CACHE=1 \
  python -m pytest tests/test_provenance_four_tickers.py -q

# breakage suite
python -m pytest tests/test_provenance_breakage.py -q

# algorithm-version drift
python -m data.algorithm_versions
```
