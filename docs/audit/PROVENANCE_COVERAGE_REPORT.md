# Provenance Coverage Report

Snapshot: `shadow-20261128`  
Generated: 2026-11-28T05:45:46.182865+00:00

## Origin taxonomy

| Origin | Meaning | Trust |
|---|---|---|
| `company_reported` | Matched to a filing with an accession number | Strongest |
| `reported` | Legacy label, no source split | Vendor-level |
| `vendor_reported` | Vendor normalised figure, uncorroborated | Vendor-level |
| `derived` | Computed by a versioned algorithm | Auditable |
| `estimated` | Modelled from a ratio | Weak |
| `imputed` | Filled to complete a period | Weakest usable |
| `unknown_legacy` | Origin never recorded | Not a fact |

`vendor_reported` is deliberately ranked *below* `company_reported`: a
vendor restates, reclassifies and rounds, so 'Yahoo says so' is a weaker
statement than 'the 10-K says so'. Collapsing the two is the laundering
this taxonomy prevents.

## Coverage by layer

Both layers are shown because they say different things, and reporting
only the annual layer would overstate the result.

| Ticker | Layer | Period | company_reported | vendor_reported | unknown_legacy |
|---|---|---|---|---|---|
| AMD | golden | unavailable (FrozenSnapshotMissError) | — | — | — |
| AMD | shadow annual | 2025-12-31 | 11 | 8 | 0 |
| AMD | shadow TTM | 2026-09-30 | 0 | 19 | 0 |
| BAC | golden | TTM(2026-09-30) | 0 | 0 | 9 |
| BAC | shadow annual | 2025-12-31 | 9 | 6 | 0 |
| BAC | shadow TTM | 2026-09-30 | 0 | 15 | 0 |
| JPM | golden | TTM(2026-09-30) | 0 | 0 | 9 |
| JPM | shadow annual | 2025-12-31 | 10 | 4 | 0 |
| JPM | shadow TTM | 2026-09-30 | 0 | 14 | 0 |
| MSFT | golden | TTM(2026-09-30) | 0 | 0 | 9 |
| MSFT | shadow annual | 2026-06-30 | 12 | 7 | 0 |
| MSFT | shadow TTM | 2026-09-30 | 0 | 19 | 0 |

## The TTM layer cannot be company-reported, and that is correct

Every TTM field in every shadow is `vendor_reported`, by construction.
A trailing-twelve-month total spanning a non-calendar window is not a
figure any company files, so no XBRL fact exists to corroborate it.
Claiming `company_reported` for a sum of four quarters would be exactly
the fabrication this phase forbids.

The consequence is worth stating plainly: the golden being reconciled is
a TTM statement, so the strongest evidence available for the fields it
consumes is *vendor-reported with a recorded derivation*, not
filing-grade. Filing-grade provenance exists for the shadow's **annual**
layer only, where up to 12 fields per ticker match an SEC fact with an
accession number and a filing date.

## What stays vendor-only, and why

| Field | Reason no filing corroboration exists |
|---|---|
| `ebitda` | Derived by vendors from EBIT + D&A; no us-gaap concept of
that semantics |
| `ebit` | EBIT includes non-operating income; `OperatingIncomeLoss` is a
different quantity (matching them produced a false 8.9% contradiction on
MSFT) |
| `free_cash_flow` | A vendor construction (OCF − capex); filers report the
components, not the difference |
| `depreciation_amortization` | Filers use entity-specific extension tags;
no single us-gaap concept covers it |
| `total_debt`, `change_in_nwc`, `stock_based_compensation` | Aggregates
composed from several filing lines |

A field that stays `vendor_reported` is not a failure of the engine. It
is the engine declining to overstate what it can prove.

