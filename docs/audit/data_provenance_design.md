# U-2b — Data Provenance Architecture (Design Only)

**Status: DESIGN. No code changed in this round.**
Session #58. U-2b remains OPEN until implementation is approved and lands.

Scope: how to record where a financial field came from, so a computed number can
never be mistaken for a disclosed one. U-2 (the synthesis itself) is explicitly
out of scope and stays open.

---

## 0. What this design is built on

Every claim below was checked against the code, and the hazards in §7 were
reproduced by running them. Nothing here is assumed.

| Fact | Evidence |
|---|---|
| `FinancialStatement` 26 fields, `FinancialData` 18, `MarketData` 43, `DataQualityFlags` 8 | `dataclasses.fields(...)` |
| `FinancialStatement` has no `to_dict`/`from_dict` | `data/models.py:14-58` |
| Serialization lives in the provider | `data/providers.py:1162` `_serialize_data_to_jsonable` |
| Deserialization uses a `__type__` allow-list | `data/providers.py:1188-1234` `_dataclass_registry` |
| Unregistered types degrade to plain `dict` | reproduced, §7.3 |
| Cache schema check is `!=`, i.e. hard reject | `data/providers.py:1318` |
| 67 frozen snapshots remain, all v5 (8 on 20261122, 50 on 20261123, 9 on 20261124) | `glob .cache/yahoo_finance/*.json` |
| The 50-ticker gate pins `UVE_SNAPSHOT_ID=20261123` | `docs/audit/benchmark_50_postfix_report.json` |
| Snapshots are keyed by `resolve_snapshot_id()`; unpinned, it is *today* | `providers.py:95-113` |
| An **unfrozen** cache read deletes a snapshot older than 4h | `providers.py:1309-1316` |
| `raw_fields` exists but is never populated | written only as `{}` at `providers.py:952` |
| `MarketData.beta_provenance` already records provenance as `Dict[str, Any]` | `providers.py:1739`, `models.py:140` |
| Normalizer runs **outside** the provider | called by `telegram_bot`, `benchmark/collector`, `benchmark/shadow_nwc_run` |

### 0.1 An incident during this design round

While checking whether `beta_provenance` survives a cache round trip, I read
`AMD_20261123.json` with `cache_enabled=True` but **without**
`UVE_FREEZE_CACHE=1`. The file was 4.7 days old, past the 4-hour TTL, so
`_cache_read` deleted it (`providers.py:1309-1316`). The snapshot is not
git-tracked and there is no backup, so it is gone.

Impact — and a correction to my first assessment:

- **AMD is in the 50-ticker universe** (`benchmark/registry.py`), so the loss is
  not cosmetic. I first concluded it was unaffected because AMD does not appear
  in `benchmark_50_postfix_report.json`; that was a bad inference — the report
  lists only the 3 *changed* tickers, not the universe.
- **`tests/test_status_matrix.py::test_status_tally_is_stable` now fails**:
  `Solved` drops 32 → 31, because AMD raises `FrozenSnapshotMissError` and gets
  `rd_status=None`. Suite state is now 1327 passed, 1 failed, 2 skipped. This is
  a real regression caused by this session, not a pre-existing failure — the
  suite was 1328 passing before the deletion, and the same test fails on a clean
  tree now, so it is environment state, not my documentation edits.
- Restoring it requires a live fetch, which the freeze policy exists to prevent,
  so the state is not recoverable by me.

Two lessons belong in the design, not just in this note:

1. **Reading a snapshot is destructive unless frozen.** Any tooling that
   inspects `.cache/yahoo_finance` must set `UVE_FREEZE_CACHE=1`. See §9.5.
2. **The snapshots are not versioned.** One unflagged read can permanently
   remove a benchmark input, and nothing in the repo can restore it. That is a
   reproducibility risk independent of U-2b.

### 0.2 A residual defect found while classifying fields

Classifying fields by source (§2) turned up a case the U-1 fix does not cover.
`_suppress_bank_operating_income` clears `operating_income` and `ebit` for banks
but leaves `ebitda` untouched. For JPM the surviving `ebitda` is exactly the old
synthesized EBIT plus D&A:

```
old operating_income (pre-fix) = 186249682034.89746
depreciation_amortization      =   9896000000.0
sum                            = 196145682034.89746
ttm.ebitda after suppression   = 196145682034.89746   ← bit-identical
```

So the bank's `ebitda` is a number whose inputs were deleted. It is not vendor
EBITDA — it is `EBIT + D&A` where `EBIT` was the vendor `operatingIncome`. The
same holds for every annual and quarterly period.

This is not a U-2b task and I am not proposing to fix it here. It is recorded
because it is precisely the class of defect provenance is meant to expose: a
`DERIVED` field whose `input_fields` no longer exist. Under this design such a
field would have to report `DERIVED` with `input_fields=["ebit","depreciation_amortization"]`,
and the fact that `ebit` is `None` would make the inconsistency visible instead
of silent.

**Open question for the ruling:** should a bank's `ebitda` be
`NOT_APPLICABLE` (a bank has no meaningful EBITDA) or kept as `DERIVED`? I lean
`NOT_APPLICABLE` for consistency with `ebit`, but it changes DDM/RIM inputs, so
it is a product decision, not mine.

That last row matters. The pipeline is not a single guarded chokepoint:

```
YahooFinanceProvider._get_financial_data_sync
  └─ _build_statements(is_bank=...)      # live fetch
  └─ _suppress_bank_operating_income     # applied at 1327 (cache) and 2697 (sync)
        ↓  returns FinancialData
caller decides whether to normalize      # ← no single entry point
  └─ FinancialNormalizer.normalize_all   # telegram_bot.py:139, collector.py:188
        └─ ensure_ttm → fill_derived_fields → _mark_missing
```

Any provenance design that assumes one funnel is wrong, because the U-1 defect
itself proved that: the provider was correct and the field still came back after
normalization.

---

## 1. Field inventory — what needs provenance

`FinancialStatement` carries 26 fields. They fall into four groups by how they
come into existence, and the groups need different defaults.

### Group A — direct vendor disclosure (`REPORTED`)

Straight from Yahoo `incomeStatementHistory` / `cashflowStatementHistory`:

`revenue`, `cost_of_revenue`, `gross_profit`, `net_income`,
`depreciation_amortization`, `capex`, `operating_cash_flow`,
`interest_expense`, `income_tax`, `shares_outstanding`, `eps`,
`stock_based_compensation`

Caveat: `operating_income` and `ebit` belong here **only for non-banks**. For a
bank, the vendor value is EBIT masquerading as operating profit, which is the
whole of U-1. So the same field name has a different honest origin depending on
the entity — provenance cannot be a property of the field name alone.

### Group B — computed by the pipeline (`DERIVED`)

- `free_cash_flow` = `operating_cash_flow + capex` (`normalizer.py:162`)
- `ebitda` = `ebit + depreciation_amortization` (`normalizer.py:160`)
- `change_in_nwc` from the cash-flow line (`nwc_from_cashflow_line`)
- TTM values summed from four quarters (`compute_ttm_from_quarters`)
- `eps` = `net_income / shares_outstanding` (`normalizer.py:171-175`)

These are exact given their inputs. `DERIVED` is the right label, and it must
carry the input field names so the arithmetic is auditable.

Three field names in total (`free_cash_flow`, `ebitda`, `change_in_nwc`); `eps`
and TTM values are listed above as derivations but their field names are shared
with Group A, so they are counted once, in A. The list is a set of *formulas*,
not a set of fields.

### Group C — inferred from a model or a ratio (`IMPUTED`)

- quarterly `ebit`/`operating_income` = `revenue × prior-year margin`
  (`providers.py:2077-2078`) — this is U-2
- quarterly `ebit` = `net_income + interest + tax` (`providers.py:2063-2071`)
- annual EBIT rebuild in `fill_derived_fields` (`normalizer.py:146-158`)
- `interest_expense` = `revenue × ratio`, `income_tax` = `revenue × ratio`
  (`normalizer.py:142,144`)
- `depreciation_amortization` = `revenue × prior ratio` (`providers.py:2080,2086`)
- TTM approximated from a single annual (`ensure_ttm`, `normalizer.py:83-106`)

`IMPUTED` is the label that would have caught this entire defect class. A number
here is a guess with arithmetic clothing.

### Group D — deliberately absent (`MISSING` / `NOT_APPLICABLE`)

- bank `operating_income` / `ebit` → `NOT_APPLICABLE` (the concept does not
  exist for a bank), not `MISSING`. That distinction is real: a bank has no
  operating income line by construction, whereas a non-bank that failed to
  report it is merely missing. Collapsing the two would lose the U-1 insight.
- TTM with fewer than four quarters → the field is `MISSING`

### Group E — metadata and dead fields

Not every field is a number, and not every field is alive. Being explicit here
prevents the next round from treating metadata as data:

| Field | Status |
|---|---|
| `period_end`, `period_type`, `currency` | identity metadata, `REPORTED` (period descriptor, not a measurement) |
| `restated` | metadata, set by the provider |
| `source_timestamp` | metadata, set at construction |
| `raw_fields` | **dead** — always `{}` (§7.4) |
| `weighted_avg_basic_shares` | **dead** — zero non-test, non-model references |
| `weighted_avg_diluted_shares` | **dead** — zero non-test, non-model references |
| `shares_source` | **dead** — never written on `FinancialStatement`; the two live `shares_source` keys are unrelated (`models/base.py:50`, `models/multiples.py:394`) |

The three dead fields are a finding in their own right: `FinancialStatement` has
26 fields, of which 4 carry no value. A provenance layer that silently stamps
`MISSING` on them would imply someone looked and found nothing, when in fact
nothing ever wrote them. They should be removed or populated, not labelled.

Complete count, verified programmatically against `dataclasses.fields`:

| Bucket | Fields |
|---|---|
| A — vendor-disclosed numeric | 14 |
| B — pipeline-computed numeric | 3 |
| metadata | 5 |
| dead | 4 |
| **total** | **26** |

The union of the four buckets equals the 26 declared fields exactly, with no
field unclassified and no bucket naming a field that does not exist. Groups A
and C overlap by entity type — `operating_income` is `REPORTED` for a non-bank
and `NOT_APPLICABLE` for a bank — so C adds no field name that A does not
already carry; it reclassifies the same names. That is why the totals sum to 26
without double counting.

### `FinancialData`-level fields

`market.*`, `quality.*`, `revenue_composition`, `reconciliation`,
`reconciliation_overrides` also have origins. `market.current_price` is
`REPORTED` from the quote endpoint; `quality.data_quality_score` is `DERIVED`;
`reconciliation_overrides` is a record of substitutions and should stay as the
existing `OverrideLog` rather than be folded into field provenance — it already
has the right shape.

---

## 2. Schema

The review ruling is adopted: origin and availability are **two dimensions**, not
one enum. `MISSING` answers "is there a number", `IMPUTED` answers "where did it
come from". Putting them in one list would force a value to pick one and lose
the other.

```python
class DataOriginType(str, Enum):          # str-Enum is mandatory, see §7.1
    REPORTED = "reported"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    IMPUTED = "imputed"
    UNKNOWN_LEGACY = "unknown_legacy"


class DataAvailability(str, Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    INVALID = "invalid"


@dataclass
class FieldProvenance:
    origin_type: Optional[DataOriginType]        # None when no value exists — see invariant
    availability: DataAvailability
    source_provider: Optional[str] = None      # "yahoo" | "sec_xbrl" | "synthetic"
    source_field: Optional[str] = None         # vendor key, e.g. "operatingIncome"
    source_period: Optional[str] = None        # "FY2025" | "2026-Q3"
    snapshot_id: Optional[str] = None          # UVE_SNAPSHOT_ID
    derivation_method: Optional[str] = None    # "REVENUE_X_PRIOR_MARGIN"
    input_fields: List[str] = field(default_factory=list)
```

### Why `origin_type` is optional, not required

A required `origin_type` contradicts `NOT_APPLICABLE`. A bank has no operating
income line, so there is no number whose origin could be described — forcing
`REPORTED` there would be a lie, and forcing `IMPUTED` would be worse.

The invariant is therefore:

| `availability` | value | `origin_type` |
|---|---|---|
| `AVAILABLE` | not `None` | **required**, never `UNKNOWN_LEGACY` on fresh data |
| `MISSING` | `None` | `None` |
| `NOT_APPLICABLE` | `None` | `None` |
| `INVALID` | `None`, or the rejected value retained in `raw_fields` | `None` |

The bank case keeps its audit trail through `source_provider` / `source_field`
rather than `origin_type`: we record that Yahoo *did* supply `operatingIncome`
and that it was rejected as `NOT_APPLICABLE`, which is more informative than any
origin label. Note this is the one place a rejected value is deliberately *not*
stored in the numeric field — the U-1 fix already discards it, and this design
does not resurrect it.

Note on `UNKNOWN_LEGACY`: it belongs in `origin_type`, not `availability`. Old
cache entries have a *number* (so they are `AVAILABLE`) but no known origin. That
is exactly the state this value names, and it must never be auto-upgraded to
`REPORTED` — doing so would launder unknown data into "the company said so".

### Where it lives

A sidecar, as ruled, so no existing consumer's type contract changes:

```python
# on FinancialStatement
field_provenance: Dict[str, FieldProvenance] = field(default_factory=dict)
```

`stmt.operating_income` stays a plain `float | None`. 74 non-test call sites
across 16 files keep working untouched (164 references including tests). That is the decisive argument for the sidecar over
wrapping every number in a value object.

### The cost of a sidecar, stated plainly

A sidecar can drift out of sync with the value it describes. If code writes
`stmt.revenue = 50.0` and forgets `field_provenance["revenue"]`, the provenance
now describes the old number and nothing detects it. Mitigations, in order of
strength:

1. **Single writer.** All mutations go through one function
   (`set_field(stmt, name, value, provenance)`), and direct assignment is
   discouraged by convention. Enforcement is review, not the type system.
2. **Consistency check.** `_mark_missing` (or a new validator) asserts: value is
   `None` ⟺ `availability` is `MISSING`/`NOT_APPLICABLE`/`INVALID`; value is not
   `None` ⟺ `availability` is `AVAILABLE`. This catches the common drift cheaply.
3. **Preservation test.** §8 asserts provenance survives every transformation.

I recommend (2) and (3) in the implementation round. A sidecar without a
consistency check is worse than no sidecar, because it *looks* trustworthy.

---

## 3. Consumer impact analysis

`operating_income` is read in 16 non-test files, 74 sites. Grouped by what they
would need if they ever asked "can I trust this number":

| Layer | Files | Reads | Needs provenance? |
|---|---|---|---|
| models | `dcf.py`, `nav.py` | presence / value | **Yes** — DCF must not silently use an `IMPUTED` EBIT as if reported |
| classification | `classifier.py`, `ml_classifier.py`, `taxonomy.py` | ratios → features | **Yes** — this is the confidence drift from Session #57; a feature built on `IMPUTED` data should be down-weighted or refused |
| forecasts | `forecast.py` | margin, tax rate | **Yes** — forecasting from an imputed margin compounds the guess |
| analysis | `divergence.py`, `risk.py` | margins | Medium — read-only diagnostics |
| data | `validator.py`, `nwc_utils.py`, `normalizer.py`, `segment_revenue.py` | sanity checks | **Writers** — these are the sites that must stamp provenance |
| reporting | `dashboard.py` | display | **Yes** — the report should show a marker, per the "don't disguise a computed number" rule |
| simulation | `monte_carlo.py` | revenue, shares | Medium — revenue is `REPORTED` in practice |
| benchmark | `collector.py` | snapshot capture | **Yes** — the collector is where provenance should be recorded for the 50-ticker gate |

`revenue` has 600 references (437 outside tests) and is `REPORTED` almost always, so it is the lowest
priority to enforce but the highest blast radius if the sidecar is malformed.
Recommended order: stamp writers first, then gate `models/` and `classification/`,
leave `analysis/` read-only.

### 3.1 Reference counts, verified

Counted with `grep -rn "\b<field>\b" --include=*.py .`, split into all files and
non-test files. These replace earlier numbers in this document that were too low
by roughly a factor of three to four — the earlier pass used a narrower match.

| Field | All refs | Non-test refs |
|---|---|---|
| `revenue` | 600 | 437 |
| `capex` | 228 | 183 |
| `free_cash_flow` | 98 | 68 |
| `interest_expense` | 97 | 41 |
| `operating_income` | 164 | 74 |
| `net_income` | 67 | 49 |
| `ebit` | 64 | 53 |
| `ebitda` | 50 | 46 |
| `gross_profit` | 35 | 32 |
| `income_tax` | 28 | 23 |

`operating_income` appears in 29 files (16 non-test). The suite is 88 test
modules (91 `.py` files under `tests/`), of which 52 reference at least one of
`operating_income`, `revenue`, `ebitda`, `free_cash_flow`, `net_income`.

The absolute numbers matter less than the ratio: for every field, most
references are in tests, and the non-test surface is still large enough that a
type change — wrapping the number instead of using a sidecar — would be a
codebase-wide edit. That is the quantitative basis for the sidecar decision in
§2.

---

## 4. Compatibility strategy

### The hard constraint

`providers.py:1318`:

```python
if int(blob.get("__cache_schema_version__") or 0) != self._CACHE_SCHEMA_VERSION:
    return None          # → cache miss → FrozenSnapshotMissError under freeze
```

The check is `!=`. All 67 remaining snapshots are v5 (it was 68 before §0.1),
and the 50-ticker gate pins `UVE_SNAPSHOT_ID=20261123`. Bumping
`_CACHE_SCHEMA_VERSION` to 6 therefore invalidates every one of them, and under
`UVE_FREEZE_CACHE` that raises rather than refetches. The 50-ticker gate would
stop working the moment the schema changed.

### Consequence

Provenance must be **additive and backward-readable**. Two options:

| Option | Effect on v5 snapshots | Verdict |
|---|---|---|
| A. Bump version to 6, require provenance | all 68 miss; the 50-gate breaks until re-snapshotted | Rejected for now |
| B. Keep version 5, treat absent provenance as `UNKNOWN_LEGACY` | old files load, fields marked unknown | **Recommended** |

Option B, concretely:

- No `_CACHE_SCHEMA_VERSION` bump. The blob gains an optional key; old readers
  ignore it, new readers tolerate its absence.
- On load, if a statement has no `field_provenance`, synthesize
  `{field: FieldProvenance(UNKNOWN_LEGACY, AVAILABLE)}` for every non-`None`
  value and `(UNKNOWN_LEGACY, MISSING)` for every `None`. Never `REPORTED`.
- A future version bump can be justified later, once fresh snapshots exist; it is
  a separate data operation, not part of this design.

There is an honest limitation here: under Option B, a v5 snapshot cannot tell you
whether its `operating_income` was reported or synthesized. It will read as
`UNKNOWN_LEGACY`, which is true. The fix does not retroactively clean history,
and pretending otherwise would repeat the original error.

---

## 5. Write-site mapping

Each synthesis site and the provenance it should stamp:

| Site | Field | Should stamp |
|---|---|---|
| `_build_statements` annual | all Group A | `REPORTED`, `source_provider="yahoo"`, `source_field=<vendor key>` |
| `_build_statements` quarterly, `op_inc = ebit` | `operating_income` | `DERIVED` from `ebit` |
| `providers.py:2078` margin synthesis | `ebit`, `operating_income` | `IMPUTED`, `derivation_method="REVENUE_X_PRIOR_MARGIN"`, inputs `["revenue"]` |
| `providers.py:2063` NI+int+tax | `ebit`, `operating_income` | `IMPUTED`, inputs `["net_income","interest_expense","income_tax"]` |
| `_suppress_bank_operating_income` | `operating_income`, `ebit` | `availability=NOT_APPLICABLE`, `origin_type=None`, keep `source_provider="yahoo"` / `source_field="operatingIncome"` as the rejection record |
| `compute_ttm_from_quarters` | summed fields | inherit the **worst** origin among inputs; if any quarter `MISSING`, TTM is `IMPUTED` and inputs list the quarters — see §7.2 |
| `ensure_ttm` annual-approx | all | `IMPUTED`, `derivation_method="TTM_FROM_LATEST_ANNUAL"` |
| `fill_derived_fields` EBIT rebuild | `ebit`, `operating_income` | `IMPUTED`, inputs `["net_income","interest_expense","income_tax"]` |
| `fill_derived_fields` fcf/ebitda/eps | those | `DERIVED`, inputs listed |
| `segment_revenue` | segment fields | `REPORTED` if from filing, else `DERIVED` |

Aggregation rule, stated once because it is the subtle one: **TTM inherits the
weakest input origin.** `REPORTED × 4 → REPORTED`; any `IMPUTED` quarter →
`IMPUTED`; any `MISSING` quarter → `IMPUTED` with the missing quarter named,
because a three-quarter sum is not a TTM.

### Why the sidecar is a `dict`, and what that costs

`FinancialStatement` is constructed in 6 production sites (`data/providers.py`
×4, `data/normalizer.py` ×2) and the field set is 26 wide. A `dict` keyed by
field name means a new field added later gets **no** provenance entry and no
error — it simply reads as "not in the dict".
The consistency check in §2.2 covers this: a non-`None` value with no provenance
entry is a hard failure, not a silent default. That check is what makes the
`dict` safe; without it the sidecar would rot one field at a time.

---

## 6. Classification confidence split

The Session #57 ruling asked for `classification_confidence` to stop meaning
several things at once. Current state: `CompanyProfile` (`data/models.py:412`) already has
`ml_raw_confidence`, `ml_model_used`, `rule_fallback_triggered`, and
`financial_business_model_confidence` — so the raw material exists, it is just
not assembled into one unambiguous statement.

Proposed presentation fields (no change to existing ones in the design round):

| Field | Meaning | JPM example |
|---|---|---|
| `ml_classifier_score` | what the ML model said, on its own features | 0.708 |
| `evidence_confidence` | how complete the underlying data was | medium |
| `classification_method` | which path decided | `BANK_REGISTRY_OVERRIDE` |
| `final_business_model` | the verdict actually used for routing | `Bank` |

This makes 0.708 read as "the model's score on current features", not "70.8%
probability this is a bank". It also removes the temptation to treat a registry
decision as an ML probability.

Caveat the ruling already flagged, and I agree: the new score is not calibrated.
It is a model output, not a frequency. Nothing here should be presented as a
probability until calibration is done on a held-out set.

---

## 7. Hazards found while designing

These are the reasons the design is not a two-line enum addition. Each was run,
not reasoned about.

### 7.1 A plain `Enum` is silently destroyed by the cache

`_serialize_data_to_jsonable` handles `int/float/str/bool`, datetime, list, dict,
dataclass, and `DataSource`. A plain `Enum` matches none of these and falls to
the function's final `return None`.

```
plain Enum   -> ('FALLS_TO_None', None)
str Enum     -> ('passthrough', <StrEnum_.A: 'a'>)
```

So `DataOriginType` must subclass `str`, or every provenance value becomes
`None` on the first cache write. The existing code only special-cases
`DataSource`, which is why this is easy to miss.

### 7.2 A partial quarter silently produces a plausible wrong TTM

`compute_ttm_from_quarters._sum` skips `None` and sums the rest:

```
4 quarters, one op_inc=None -> TTM op_inc = 60.0     (true value would be 80.0)
```

A 25% understatement that looks like an ordinary number. Nothing in the object
records that a quarter was dropped. This is why §5 requires a `MISSING` quarter
to force the TTM to `IMPUTED` and name it.

### 7.3 Enum and dataclass types degrade across a real JSON round trip

Even with `str`-Enum, the value comes back as `str`, not `OriginStr`:

```
on disk: {"__type__": "Prov", "origin": "reported"}
type after JSON round-trip: str
back.origin.value -> AttributeError: 'str' object has no attribute 'value'
comparison still 'works': True
```

`==` keeps passing while `.value` breaks — the exact silent-degradation shape the
existing `_dataclass_registry` docstring warns about. And an unregistered
dataclass becomes a plain `dict`:

```
registered   -> FieldProvenance
unregistered -> dict | has .origin_type? False
```

So `FieldProvenance` **must** be added to `_dataclass_registry`, and the
round-trip test must assert type identity, not just equality.

### 7.4 `raw_fields` is dead

It looks like provenance storage and is not: it is only ever written as `{}`
(`providers.py:952`). Building on it would mean building on nothing. It should be
either populated or removed; this design does not use it.

### 7.5 An attribute that is not a declared dataclass field is silently dropped

The serializer walks `__dataclass_fields__` only. Attaching provenance to an
object after construction loses it with no warning:

```
fd.ttm.field_provenance = {...}       # dynamic attribute
serialize -> "field_provenance" in text?  False
round-trip -> the attribute is simply gone
```

This is why §2 declares `field_provenance` as a real field on
`FinancialStatement` rather than monkey-patching it onto loaded objects. It also
means any migration that "just adds provenance to existing objects" is a no-op.

### 7.6 Verification note

Hazards 7.1–7.3 and 7.5 were first sketched with a local re-implementation of
the serializer, which is weak evidence. They were then re-run against the real
`YahooFinanceProvider._serialize_data_to_jsonable` and `_data_from_jsonable`:

| Check | Real-code result |
|---|---|
| plain `Enum` field | serialized as `null` |
| `str`-Enum field | serialized as `"reported"`; deserialized as `str` |
| `.value` after round trip | `AttributeError: 'str' object has no attribute 'value'` |
| `isinstance(x, Origin)` after round trip | `False` |
| unregistered dataclass | becomes plain `dict` |
| unregistered root object | discarded entirely (`isinstance(..., FinancialData)` gate at `providers.py:1271`) |
| dynamic attribute | absent from the serialized payload |

The practical consequence stands: the round-trip test in §8 must assert type
identity, not `==`. An `==` check passes while the enum contract is already
broken.

---

## 8. Provenance Preservation test matrix

The ruling's seven assertions, plus the hazards in §7 and the orphan case in
§0.2, mapped to concrete tests. None are written yet.

| # | Assertion | Test |
|---|---|---|
| 1 | A disclosed number does not become `ESTIMATED` after normalization | `revenue` on a reported statement: `REPORTED` before and after `normalize_all` |
| 2 | A computed EBIT records formula and inputs | after `fill_derived_fields`, `ebit` provenance has `derivation_method` and `input_fields == ["net_income","interest_expense","income_tax"]` |
| 3 | Missing data is never auto-filled with zero | a statement with `net_income=None`: result stays `MISSING`, not `0.0` |
| 4 | A `DERIVED` field traces to its inputs | `free_cash_flow` provenance lists `operating_cash_flow`, `capex` |
| 5 | Cache save→load preserves provenance | round-trip asserts **type identity** (`isinstance(p, FieldProvenance)`, `isinstance(p.origin_type, DataOriginType)`), not just `==` — §7.3 |
| 6 | Old cache cannot masquerade as new | load a v5 blob with no provenance → every field `UNKNOWN_LEGACY`, none `REPORTED` |
| 7 | Same snapshot read twice is identical | two loads of the same `snapshot_id`: values and provenance both equal, including enum types |

Additional tests from §7:

| # | Hazard | Test |
|---|---|---|
| 8 | Partial-quarter TTM | 4 quarters, one `None` → TTM `availability` is not a clean `AVAILABLE`/`REPORTED`; missing quarter named |
| 9 | Enum survives JSON | `json.dumps`/`loads` of a statement with provenance → `origin_type` is `DataOriginType` (assert `isinstance`, not `==`), and `.value` works |
| 10 | Registry completeness | every type reachable from `field_provenance` is in `_dataclass_registry` |
| 11 | Sidecar is a declared field | provenance attached to a statement survives a serialize→deserialize round trip — catches §7.5, where a dynamic attribute vanishes |
| 12 | Root-type gate | a payload whose root is not `FinancialData` returns `None` rather than a half-decoded object |
| 13 | Orphan `DERIVED` field | a bank statement whose `ebit` is `None` must not carry a `DERIVED` `ebitda` — its `input_fields` would name a field that no longer has a value (§0.2) |

Layered matrix the ruling asked for:

| Layer | Tests |
|---|---|
| Normalizer | 1, 2, 3, 4, 8 |
| Cache | 5, 6, 9, 10 |
| SEC XBRL | revenue provenance is `REPORTED` with `source_provider="sec_xbrl"` |
| Yahoo | vendor fields `REPORTED`; synthesized quarters `IMPUTED` |
| Bank | `operating_income` is `NOT_APPLICABLE`, not `MISSING` and not `IMPUTED`; `ebitda` is not a `DERIVED` orphan (test 13) |
| DCF / RIM | a model given an `IMPUTED` EBIT either refuses or flags it |
| Monte Carlo | revenue provenance does not change across the simulation |

---

## 9. Open questions for the implementation round

These need a decision before code, and I do not think they should be settled
unilaterally:

1. **Enforcement.** Should `models/` refuse `IMPUTED` inputs, or accept them with
   a warning? Refusing changes valuations for every ticker currently relying on
   inferred EBIT; accepting keeps the status quo but makes the flag advisory.
   This is a product decision, not a data decision.
2. **Bank `ebit`.** Should it be `NOT_APPLICABLE` (my recommendation, since the
   concept does not exist) or `MISSING` (simpler, but loses the distinction)?
3. **`revenue` enforcement.** 600 references (437 non-test). Stamp it, but do not gate on it in
   the first round, or the blast radius becomes the whole codebase.
4. **`raw_fields`.** Populate it as the raw vendor echo, or delete it. Leaving a
   dead field that looks like provenance is itself a trap.

5. **Unfrozen snapshot reads.** `_cache_read` deletes a stale file, so a single
   unflagged inspection tool can destroy a benchmark input (§0.1). Options:
   make `_cache_read` refuse to delete when the filename encodes a snapshot ID
   older than the TTL (a pinned snapshot is by definition archival), or add a
   read-only inspection helper that always freezes. I lean toward the first: the
   current behaviour conflates "stale working cache" with "archival snapshot",
   and only the former should ever be deleted.

---

## 10. What this round did and did not do

Did, per the Session #58 ruling's four steps:

1. **Field inventory.** All 26 `FinancialStatement` fields classified into four
   buckets, verified programmatically so the union equals the declared set. Also
   enumerated `FinancialData` (18), `MarketData` (43), `DataQualityFlags` (8).
2. **Consumer impact.** Counted references per field and per module, and traced
   every caller of `normalize_all`.
3. **Compatibility.** Established that the version check is a hard `!=` and that
   the snapshots are unversioned, then chose the backward-readable path.
4. **Test plan.** 12 tests across cache, normalizer, SEC, Yahoo, bank, DCF, MC.

Also found and recorded two things not on the brief:

- A residual U-1 defect: bank `ebitda` survives suppression as an orphan whose
  inputs were deleted (§0.2). Not fixed; needs a ruling.
- Three more dead fields besides `raw_fields` (§Group E).

Corrected during review: an earlier draft said "51 frozen snapshots". It was 68
before this round; it is 67 now because I deleted one (§0.1). 51 is only the
`20261123` set the gate pins. That earlier claim was also verified with the wrong
method — the cache was read without pinning `UVE_SNAPSHOT_ID`, so the lookup used
today's date and missed every file. Re-run pinned, v5 loads and a hypothetical v6
returns `None`.

Did not: change any code, change `_CACHE_SCHEMA_VERSION`, touch U-2, or resolve
any question in §9.

The conclusion worth carrying forward: the U-1 defect survived 16 passing unit
tests because a field can be correct at one layer and wrong at the next.
Provenance makes that failure visible instead of silent, which is why it is worth
a schema round rather than a patch.
