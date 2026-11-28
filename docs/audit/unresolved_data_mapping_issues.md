# Unresolved Data Mapping Issues

Session #57 audit. Items found during the JPM operating income investigation that
were **not** fixed. Recording them is the point: an audit that only lists what it
closed is not an audit.

## U-1 — Banks have no operating income in the vendor feed

**Severity: high. Status: RESOLVED (Session #57) — field suppressed for banks.**

Yahoo's `operatingIncome` for a bank is EBIT (`pre-tax income + interest
expense`). SEC reports no `us-gaap:OperatingIncomeLoss` for JPM, BAC or GS
(HTTP 404). So there is no correct value to map to in the current feed at all —
this is not a mapping typo that can be corrected by choosing a different tag. Any
fix needs either a bank-specific concept (PPNR) or the field must be marked
unavailable for banks.

**Resolution:** the second option. `operating_income` and `ebit` are now `None`
for members of `BANK_HOLDING_COMPANIES`, enforced at three layers:
`_build_statements` (live fetch), `_suppress_bank_operating_income` (cache read),
and `FinancialNormalizer.fill_derived_fields` (which rebuilt the field from
NI + interest + tax and re-shipped it). PPNR was rejected: it needs the provision
for credit losses, which the vendor does not supply and which cannot be fetched
offline. See `bank_operating_income_mapping_audit.md`.

## U-2 — Quarterly operating income is synthesized, not reported

**Severity: high. Status: OPEN.**

`data/providers.py` fills a missing quarterly EBIT with
`revenue × latest_annual_ebit_margin` and assigns it to `op_inc`. The inferred
value is indistinguishable from a reported one downstream, and the normalizer
sums four inferred quarters into TTM.

**Partial mitigation only:** for banks the field no longer reaches a consumer, so
the synthesis cannot mislead there. That is a consequence of the U-1 fix, not a
fix for U-2. The synthesis itself is still in place for every non-bank ticker
that omits quarterly EBIT, and those tickers are the majority of the exposure.
U-2 stays open until the inference either carries provenance (U-2b) or is
removed with a measured drift audit.

## U-2b — Inferred values carry no provenance

**Severity: medium. Status: OPEN. Schema design complete (Session #58), implementation not approved.**

A consumer cannot tell a reported figure from a computed one. `operating_income`
rebuilt as `revenue × margin`, or as `NI + interest + tax`, lands in the same
`float` field as a figure the company actually filed. Every downstream model,
and the classification feature vector, treats them identically.

Design: **`docs/audit/data_provenance_design.md`**. Summary of what it settles
and what it leaves open:

- Two dimensions, per the ruling: `DataOriginType` (reported / derived /
  estimated / imputed / unknown_legacy) and `DataAvailability` (available /
  missing / not_applicable / invalid). `origin_type` is optional, because a
  `NOT_APPLICABLE` field has no number to describe.
- Sidecar `FinancialStatement.field_provenance: dict[str, FieldProvenance]`,
  so the 47 existing `operating_income` read sites keep their type contract.
- Compatibility: **do not bump `_CACHE_SCHEMA_VERSION`**. All 51 frozen snapshots
  are v5 and the check is `!=`, so a bump invalidates every one of them and
  raises `FrozenSnapshotMissError` under freeze. Absent provenance reads as
  `UNKNOWN_LEGACY`, never `REPORTED`.
- Three silent-degradation hazards found and reproduced: a plain `Enum`
  serializes to `None`; a `str`-Enum comes back as `str` after a JSON round trip
  (`==` passes, `.value` raises); an unregistered dataclass becomes a plain
  `dict`.
- Open decision, not settled: whether `models/` should *refuse* `IMPUTED` inputs
  or accept them with a warning. That changes valuations, so it is a product
  call.

Implementation is **not approved**; this remains OPEN until it lands.

Proposed shape — a value plus its origin, not a bare number:

```json
{
  "value": 123456789,
  "origin_type": "DERIVED",
  "source_field": "revenue",
  "derivation_method": "REVENUE_X_PRIOR_YEAR_MARGIN",
  "source_period": "FY2025",
  "confidence": "INDICATIVE"
}
```

At minimum the following must stay distinct, because collapsing them into one
plain number is how this defect class recurs. Note these are **two axes**, not
one list — an earlier draft of this file put `MISSING` alongside `IMPUTED`, which
was wrong: "is there a number" and "where did it come from" are independent
questions, and a single enum forces a value to answer only one.

| `origin_type` | Meaning |
|---|---|
| `REPORTED` | Filed by the company; authoritative. |
| `DERIVED` | Computed from reported figures; exact if the inputs are. |
| `ESTIMATED` | Model output, e.g. a forecast. |
| `IMPUTED` | Filled in for missing data, e.g. `revenue × prior margin`. |
| `UNKNOWN_LEGACY` | A number exists but its origin predates provenance. Never upgraded to `REPORTED`. |

| `availability` | Meaning |
|---|---|
| `AVAILABLE` | A usable number is present. |
| `MISSING` | Absent, but the field would normally exist. Must never render as `0`. |
| `NOT_APPLICABLE` | The concept does not exist for this entity (bank `operating_income`). |
| `INVALID` | A value was supplied and rejected. |

The U-1 fix is the limiting case of this idea — a bank's `operating_income` is
`NOT_APPLICABLE`, and the honest representation is `None` rather than a plausible
float. U-2b generalises that one case into a schema rule.

Scope note: this touches the `FinancialStatement` schema and every consumer, so
it needs its own design pass — hence `docs/audit/data_provenance_design.md`,
which supersedes the JSON sketch above. That sketch is kept only to show the
rejected single-axis shape; do not implement it.

## U-3 — TTM interest expense is absent for all three banks

**Severity: medium. Status: open.**

`ttm.interest_expense` is `None` for JPM, BAC and GS, while annual values are
present (JPM FY2025: 97,898,000,000). Any logic keyed on interest expense against
operating income silently falls back. The fallback is documented and conservative,
so nothing breaks — but the intended signal never runs.

## U-4 — The operating-income sanity guard tests the wrong thing

**Severity: medium. Status: open.**

The guard in `providers.py` rejects `op_inc` only when it exceeds gross profit or
revenue. For JPM, gross profit is `None`, so the ceiling is revenue and a value at
93.8% of revenue passes. The guard catches arithmetically impossible values, not
implausible ones. A bank operating at 94% operating margin is implausible; the
guard has no way to say so.

## U-5 — Snapshot claims 2026-09-30; SEC XBRL stops at 2025-12-31

**Severity: medium. Status: open, needs a decision.**

The frozen snapshot is labelled `TTM(2026-09-30)` and contains 2026 quarters.
SEC XBRL for JPM has no fact later than 2025-12-31, and its quarterly facts stop
in 2014. The 2026 quarters therefore cannot be validated against SEC XBRL.

This audit can prove the *operating income* on those quarters is fabricated. It
cannot prove the *revenue* on them is genuine — that would need the 10-Q or the
issuer's own reporting. Until that is checked, treat 2026 quarterly revenue for
these banks as unverified.

## U-6 — JPM revenue differs from SEC by 600M

**Severity: low. Status: open.**

SEC FY2025 `Revenues` is 182,447,000,000; the snapshot carries 181,847,000,000, a
0.33% difference. Too small to change any conclusion here, but it means the
snapshot's revenue is not a byte-for-byte copy of the SEC figure and the two
sources should be reconciled before any line-item work that depends on exact
revenue.

## U-7 — No bank appears in the 50-stock benchmark except four

**Severity: low. Status: open.**

The benchmark covers JPM, BAC, GS, CB, V and BRK-B on the financial side. A
"50-stock drift audit" therefore has thin coverage of banks specifically. Any
future change to bank data mapping needs a dedicated bank regression set, not the
general benchmark.

## What was deliberately not changed

Per the audit restrictions: no valuation formula, Bank RIM, Beta, Ke, deposit
threshold, frozen snapshot or golden file was modified. No repair was attempted
before the root cause was established. The four audit documents and this list are
the deliverable; the fixes are a separate, approved piece of work.
