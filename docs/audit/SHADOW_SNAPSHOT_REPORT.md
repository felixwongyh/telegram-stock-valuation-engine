# Shadow Snapshot Report

Snapshot id: `shadow-20261128`  
Generated: 2026-11-28T05:45:46.146019+00:00  
Generator: `python -m benchmark.report_reconciliation`

## What a shadow snapshot is

Each ticker directory under `data/shadow_snapshots/<snapshot>/<TICKER>/`
holds the vendor's **raw response bytes**, a SHA-256 per artefact, the
retrieval timestamp, the fiscal period, and per-field provenance.
`verify_shadow()` re-hashes every artefact, so a silent edit becomes
visible rather than invisible.

## Integrity

| Ticker | Artefacts | Digests verified | Filing evidence |
|---|---|---|---|
| AMD | 4 | yes | yes |
| BAC | 4 | yes | yes |
| JPM | 4 | yes | yes |
| MSFT | 4 | yes | yes |

## Field provenance per ticker

`COMPANY_REPORTED` requires a filing accession number. `VENDOR_REPORTED`
means the vendor returned it and nothing corroborated it — a weaker
claim, labelled as such.

### AMD

Annual period end: `2025-12-31`  
CIK: `0000002488`  

| Origin | Fields |
|---|---|
| company_reported | 11 |
| vendor_reported | 8 |

Corroborated by SEC XBRL: **11** fields  
Contradicted by SEC XBRL: **0**   
Checked, no filing fact found: **2** (depreciation_amortization, total_liabilities)  
No SEC concept of that semantics: **6** (change_in_nwc, ebit, ebitda, free_cash_flow, stock_based_compensation, total_debt)

Fiscal-period label gaps (vendor label vs filing period):
- `capex`: vendor `2025-12-31` vs filing `2025-12-27` (4 days)
- `cash`: vendor `2025-12-31` vs filing `2025-12-27` (4 days)
- `gross_profit`: vendor `2025-12-31` vs filing `2025-12-27` (4 days)
- `income_tax`: vendor `2025-12-31` vs filing `2025-12-27` (4 days)
- `interest_expense`: vendor `2025-12-31` vs filing `2025-12-27` (4 days)
- `net_income`: vendor `2025-12-31` vs filing `2025-12-27` (4 days)
- `operating_cash_flow`: vendor `2025-12-31` vs filing `2025-12-27` (4 days)
- `revenue`: vendor `2025-12-31` vs filing `2025-12-27` (4 days)
- `shares_outstanding`: vendor `2025-12-31` vs filing `2025-12-27` (4 days)
- `stockholders_equity`: vendor `2025-12-31` vs filing `2025-12-27` (4 days)
- `total_assets`: vendor `2025-12-31` vs filing `2025-12-27` (4 days)

### BAC

Annual period end: `2025-12-31`  
CIK: `0000070858`  

| Origin | Fields |
|---|---|
| company_reported | 9 |
| vendor_reported | 6 |

Corroborated by SEC XBRL: **9** fields  
Contradicted by SEC XBRL: **1** (cash)  
Checked, no filing fact found: **1** (interest_expense)  
No SEC concept of that semantics: **4** (change_in_nwc, free_cash_flow, stock_based_compensation, total_debt)

### JPM

Annual period end: `2025-12-31`  
CIK: `0000019617`  

| Origin | Fields |
|---|---|
| company_reported | 10 |
| vendor_reported | 4 |

Corroborated by SEC XBRL: **10** fields  
Contradicted by SEC XBRL: **0**   
Checked, no filing fact found: **1** (interest_expense)  
No SEC concept of that semantics: **3** (change_in_nwc, free_cash_flow, total_debt)

### MSFT

Annual period end: `2026-06-30`  
CIK: `0000789019`  

| Origin | Fields |
|---|---|
| company_reported | 12 |
| vendor_reported | 7 |

Corroborated by SEC XBRL: **12** fields  
Contradicted by SEC XBRL: **0**   
Checked, no filing fact found: **1** (depreciation_amortization)  
No SEC concept of that semantics: **6** (change_in_nwc, ebit, ebitda, free_cash_flow, stock_based_compensation, total_debt)

