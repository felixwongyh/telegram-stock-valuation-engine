# Golden Reconciliation Report

Snapshot under test: `shadow-20261128`  
Generated: 2026-11-28T05:45:46.148707+00:00

## Scope and honesty rules

- The frozen golden in `.cache/yahoo_finance` is **read, never written**.
- Shadow data is compared at **TTM cadence**, because the golden is TTM.
  Comparing an annual shadow to a TTM golden would report a period shift
  as a data change.
- A row is only called *material* above 0.5%. Below that a vendor's
  rounding is indistinguishable from a real move.
- **No golden value is proposed for replacement here.** This phase
  produces evidence; the decision to re-baseline is human.

## AMD

Golden unavailable: `FrozenSnapshotMissError`

No comparison is made. AMD has no entry in the frozen snapshot
`20261123`; the only AMD cache file present is for a different
snapshot id. Reporting a delta here would require substituting
today's data for the historical figure, which is the provenance
fraud this phase exists to prevent.

The shadow for `AMD` still exists and its provenance stands on
its own — see the Shadow Snapshot Report.

## BAC

Golden period: `TTM(2026-09-30)`  
Shadow period: `2026-09-30`  
Material changes: **4** of 9

| Field | Golden | Shadow | Δ% | Golden origin | Shadow origin | Reason |
|---|---|---|---|---|---|---|
| revenue | 120.45B | 120.45B | +0.00% | unknown_legacy | vendor_reported | within materiality tolerance |
| ebitda | — | — | — | — | — | absent in both |
| ebit | — | — | — | — | — | absent in both |
| net_income | 31.38B | 31.38B | +0.00% | unknown_legacy | vendor_reported | within materiality tolerance |
| cash | — | 258.28B | — | — | vendor_reported | **newly available (vendor_reported)** |
| total_debt | — | 380.92B | — | — | vendor_reported | **newly available (vendor_reported)** |
| stockholders_equity | — | 296.75B | — | — | vendor_reported | **newly available (vendor_reported)** |
| shares_outstanding | 8.00B | 6.92B | -13.43% | unknown_legacy | vendor_reported | **source changed (unknown_legacy -> vendor_reported) and value moved -13.43%** |
| free_cash_flow | 59.20B | 59.20B | +0.00% | unknown_legacy | vendor_reported | within materiality tolerance |

Golden fingerprint median value: **38.21** (n_solved=4, agreement=Weak)

## JPM

Golden period: `TTM(2026-09-30)`  
Shadow period: `2026-09-30`  
Material changes: **4** of 9

| Field | Golden | Shadow | Δ% | Golden origin | Shadow origin | Reason |
|---|---|---|---|---|---|---|
| revenue | 198.65B | 198.65B | +0.00% | unknown_legacy | vendor_reported | within materiality tolerance |
| ebitda | — | — | — | — | — | absent in both |
| ebit | — | — | — | — | — | absent in both |
| net_income | 65.98B | 65.98B | +0.00% | unknown_legacy | vendor_reported | within materiality tolerance |
| cash | — | 326.27B | — | — | vendor_reported | **newly available (vendor_reported)** |
| total_debt | — | 531.50B | — | — | vendor_reported | **newly available (vendor_reported)** |
| stockholders_equity | — | 372.37B | — | — | vendor_reported | **newly available (vendor_reported)** |
| shares_outstanding | 2.93B | 2.66B | -9.50% | unknown_legacy | vendor_reported | **source changed (unknown_legacy -> vendor_reported) and value moved -9.50%** |
| free_cash_flow | -84.16B | -84.16B | +0.00% | unknown_legacy | vendor_reported | within materiality tolerance |

Golden fingerprint median value: **152.74** (n_solved=4, agreement=Weak)

## MSFT

Golden period: `TTM(2026-09-30)`  
Shadow period: `2026-09-30`  
Material changes: **3** of 9

| Field | Golden | Shadow | Δ% | Golden origin | Shadow origin | Reason |
|---|---|---|---|---|---|---|
| revenue | 346.44B | 346.44B | +0.00% | unknown_legacy | vendor_reported | within materiality tolerance |
| ebitda | 222.94B | 222.94B | +0.00% | unknown_legacy | vendor_reported | within materiality tolerance |
| ebit | 180.81B | 180.81B | +0.00% | unknown_legacy | vendor_reported | within materiality tolerance |
| net_income | 142.63B | 142.63B | +0.00% | unknown_legacy | vendor_reported | within materiality tolerance |
| cash | — | 20.28B | — | — | vendor_reported | **newly available (vendor_reported)** |
| total_debt | — | 57.20B | — | — | vendor_reported | **newly available (vendor_reported)** |
| stockholders_equity | — | 470.51B | — | — | vendor_reported | **newly available (vendor_reported)** |
| shares_outstanding | 7.43B | 7.43B | -0.07% | unknown_legacy | vendor_reported | within materiality tolerance |
| free_cash_flow | 59.96B | 59.96B | +0.00% | unknown_legacy | vendor_reported | within materiality tolerance |

Golden fingerprint median value: **214.26** (n_solved=6, agreement=Very Strong)

