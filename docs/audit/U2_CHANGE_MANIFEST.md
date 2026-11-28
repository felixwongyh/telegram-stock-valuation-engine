# U-2 Change Manifest

Session #59 (second pass). Everything changed to close U-2, and why.

---

## New files

| File | Purpose |
|---|---|
| `data/provenance.py` | provenance schema, gate, audit tools (`audit_records`, `drifted_fields`, `coverage_summary`, `assert_no_forbidden_upgrade`, `compute_input_hash`) |
| `data/algorithm_versions.py` | version registry + AST source fingerprints + drift check |
| `data/provenance_baseline.json` | recorded fingerprints; the diff of this file is the change record for an algorithm edit |
| `tests/test_data_provenance.py` | 20 tests: schema, tiers, gate, cache round trip (from U-2b) |
| `tests/test_bank_ebitda_suppression.py` | U-8 bank `ebitda` suppression |
| `tests/test_provenance_four_tickers.py` | Phase 2: MSFT/AMD/JPM/BAC evidence, 24 tests |
| `tests/test_provenance_breakage.py` | Phase 5: six intentional breakages, 27 tests |
| `tests/test_dcf_provenance_regression.py` | Phase 3: DCF regression protection, 15 tests |
| `docs/audit/U2_INFERENCE_AUDIT.md` | Phase 1 deliverable |
| `docs/audit/PROVENANCE_VALIDATION.md` | Phase 2 + 5 deliverable |
| `docs/audit/GOLDEN_READINESS_REPORT.md` | Phase 4 deliverable |

## Modified files

| File | Change |
|---|---|
| `data/models.py` | `FinancialStatement.field_provenance` (28th field, declared) |
| `data/normalizer.py` | `_stamp_derived`, `_stamp_ttm_sums`; all 9 `fill_derived_fields` branches stamped; partial-quarter detection; `ensure_ttm` annual approximation stamped ESTIMATED |
| `data/providers.py` | `_stamp_derived_field`; 4 post-construction derivations stamped; `source_fields` added to all REPORTED stamps; `_backfill_legacy_provenance` unchanged in behaviour |
| `models/dcf.py` | `provenance_notes()` covers all 11 audited DCF inputs (was 1); refusal gated on `REFUSE` only |
| `docs/audit/data_provenance_design.md` | §11 (U-2b implementation), §12 (U-2 inference audit) |
| `docs/audit/unresolved_data_mapping_issues.md` | U-2b closed (§11), U-2 closed (§12) |
| `tests/test_status_matrix.py` | `EXPECTED["Solved"]=31` + exact AMD-gap assertion (U-8 round) |
| `tests/test_snapshot_freeze.py` | freeze-path guards (U-8 round) |
| `tests/golden/report_fingerprints.json` | JPM/BAC `recon_checks` 10->9 (U-8 round, established correct) |

---

## Behaviour changes

Only one, and it is additive:

**`DCFModel.provenance_notes()`** now reports every inferred DCF input instead of
only `operating_income`. On MSFT the caveat count rises 1 -> 11. It adds strings;
it changes no applicability verdict and no valuation figure.

Verified unchanged: `Solved` 31, `None` 10, `No Solution In Range` 9, golden
fingerprints all pass (38 tests).

---

## Defects fixed

| # | Defect | Evidence it was real |
|---|---|---|
| 1 | `fill_derived_fields` wrote 9 fields with no provenance | MSFT TTM `interest_expense` `None -> 3.185e9`, `income_tax` `None -> 3.360e10`, `prov=None` |
| 2 | 4 derivations ran after `_stamp_statement_provenance` | kept REPORTED labels for values that never existed |
| 3 | `REPORTED` fields had empty `source_fields` | found only by driving `_build_statements` directly; invisible on the frozen set (0 REPORTED) |
| 4 | TTM sum skipped missing quarters silently | 3-of-4 sum is ~75% of the truth and looks ordinary |
| 5 | `provenance_notes` covered 1 of 11 inputs | a caveat list naming one field while nine were inferred reads as complete |
| 6 | algorithm fingerprints hashed text, so a comment flagged as a change | comment edit -> 1 mismatch; wrong for a behaviour rule |

---

## Not done, deliberately

| Item | Why |
|---|---|
| Re-snapshot to restore `REPORTED` coverage | changes the numbers; a separate decision — see `GOLDEN_READINESS_REPORT.md` §8 |
| `UPDATE_GOLDEN=1` | prohibited this session; no golden value modified |
| AMD rebuild from `AMD_20261128.json` | provenance fraud: would claim 2026-11-23 while holding 2026-11-28 data |
| Lower `EXPECTED["Solved"]` | the gap is asserted, not absorbed |
| Version the valuation models (DCF/RIM/DDM) | out of U-2 scope; data derivations only |

---

## Verification

```
1359 -> 1425 tests   (+66 this round)
1425 passed, 3 skipped, 0 failed
0 algorithm-baseline mismatches
Solved = 31 (unchanged)
golden fingerprints: 38 passed, unchanged
```

Each Phase 5 breakage was verified both ways: test passes on correct code, and
the production code was actually broken to confirm the test fails. Results are
recorded in `PROVENANCE_VALIDATION.md` §6.
