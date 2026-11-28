# Bank Operating Income — Cross-Bank Mapping Audit

Session #57. Compares JPM, BAC and GS to establish whether the field the pipeline
calls `operating_income` has one economic definition across banks, and whether it
is fit for a shared threshold.

## Verdict

The three banks share **one** definition, and it is the wrong one for a bank.
Because it is consistent across all three, it is *not* a case of mixed
definitions — but it is also not usable for calibration, because the quantity it
measures is not operating profit.

## The shared definition

For each bank, Yahoo's annual `operating_income` minus its own interest expense
equals SEC's pre-tax income, to the dollar:

| Bank | Yahoo op_inc | Yahoo interest exp | op_inc − int_exp | SEC pre-tax income | Match |
|---|---|---|---|---|---|
| JPM | 170,493,000,000 | 97,898,000,000 | 72,595,000,000 | 72,595,000,000 | exact |
| BAC | 116,165,000,000 | 78,470,000,000 | 37,695,000,000 | 37,695,000,000 | exact |
| GS | 88,666,000,000 | 66,814,000,000 | 21,852,000,000 | 21,852,000,000 | exact |

All three are FY2025 (period end 2025-12-31). The identity
`op_inc = pre-tax income + interest expense` holds for all three, so the field is
**EBIT**, uniformly.

## The same fabrication appears in all three

Quarterly `operating_income / revenue` takes exactly one value per bank, matching
that bank's own FY2025 annual margin:

| Bank | Distinct quarterly ratios | The single ratio | FY2025 annual ratio | Match |
|---|---|---|---|---|
| JPM | 1 | 0.937563 | 0.937563 | exact |
| BAC | 1 | 1.027127 | 1.027127 | exact |
| GS | 1 | 1.521301 | 1.521301 | exact |

Five quarters per bank, one ratio each. Real quarterly margins vary; a constant
to six decimals is a computed value, not a reported one.

Note BAC (1.027) and GS (1.521) exceed 1.0: "operating income" is reported as
**larger than revenue**. That is impossible for an operating profit and is only
explicable once the field is read as EBIT with interest added back.

For contrast, tickers whose quarterly data is genuine show five different ratios:

| Ticker | Distinct quarterly ratios |
|---|---|
| V | 0.6129, 0.6373, 0.6575, 0.6735, 0.6830 |
| CB | 0.2156, 0.2208, 0.2397, 0.2503, 0.2591 |
| BRK-B | 0.1479, 0.1618, 0.2311, 0.2424, 0.2833 |

So the synthesis is not a global pipeline behaviour — it triggers where the
vendor omits a quarterly EBIT, which happens to be the case for these banks.

## Does the definition differ between banks?

No. That is the finding, and it cuts both ways:

- **Good news for consistency**: JPM, BAC and GS are directly comparable to each
  other. A relative comparison of the three is not corrupted by definition drift.
- **Bad news for calibration**: they are consistently wrong in the same way.
  Sharing a definition does not make the definition correct. A threshold tuned on
  this field would be tuned on `pre-tax income + interest expense`, which for a
  bank scales with the size of the deposit base rather than with profitability.

The audit instruction was: if the field means different things, do not use it for
a shared threshold. Here it means the same thing everywhere — and still must not
be used, because what it means is not operating profit.

## Correct bank concept

Banks do not report `us-gaap:OperatingIncomeLoss` — the concept returns HTTP 404
for JPM, BAC and GS alike. The closest genuine operating-profit measures are:

| Concept | JPM FY2025 | Definition |
|---|---|---|
| Pre-provision net revenue (PPNR) | 86,807,000,000 | revenue − noninterest expense |
| Pre-tax income | 72,595,000,000 | PPNR − provision for credit losses |
| Net income | 57,048,000,000 | pre-tax − tax |

The pipeline's 186,249,682,034 TTM figure is **2.1×** JPM's PPNR. It is not a
sloppy estimate of any of the three; it is a different quantity.

## Implications

1. `operating_income` for banks must not be used to calibrate any threshold, and
   must not be presented as operating profit.
2. Bank valuation is unaffected: Bank DDM and Bank RIM read `net_income`,
   `book_equity`, `eps` and `dps`, never `operating_income`.
3. The synthesized quarters are summed into TTM, so the defect is not confined to
   quarterly views — the headline TTM number is affected.
4. Because BAC and GS exceed revenue, any consumer that divides by
   `operating_income` (tax rate, margin) is materially distorted: JPM's implied
   effective tax rate comes out at 9.1% against a true 21.4%.

## Scope limit

Only JPM, BAC and GS were cross-checked against SEC XBRL. CB, V and BRK-B were
inspected for the ratio signature (they show genuine variation) but not
reconciled to SEC line items. Treat the "genuine data" claim for those three as
strong evidence, not proof.

## Remediation (Session #57)

**Decision:** stop presenting `operating_income` and `ebit` for bank holding
companies. Nothing is substituted in their place.

The alternative — deriving a bank operating profit such as PPNR — was rejected
because PPNR requires the provision for credit losses, which the vendor does not
supply and which the pipeline cannot obtain offline. Inventing a number to fill
a field that the source never provided would recreate the original defect with
better arithmetic.

### Where the fix lives

Two enforcement points, because there are two ways a `FinancialData` object is
produced:

1. `YahooFinanceProvider._build_statements(..., is_bank=...)` — strips the fields
   from each period dict before statements are built. Covers a live fetch.
2. `YahooFinanceProvider._suppress_bank_operating_income(data)` — applied at both
   `_cache_read` and the end of `_get_financial_data_sync`. Covers frozen
   snapshots, which are deserialized straight into `FinancialData` and never pass
   through the builder.

A third path was found later by the 50-ticker gate, and it was the one that
actually shipped the bug downstream:

3. `FinancialNormalizer.fill_derived_fields` — rebuilds EBIT as
   `net_income + interest_expense + income_tax` and assigns it to **both**
   `ebit` and `operating_income`. Guarding only the provider meant the benchmark
   still saw 186.2B for JPM after normalization. Now scoped out for banks.

Three enforcement points, one rule. The duplication is not ideal, but each layer
can be entered independently: a live fetch, a cache read, and a caller that
normalizes an object built elsewhere.

The membership test is `data.bank_registry.BANK_HOLDING_COMPANIES`. That list was
moved out of `classification.classifier` (which now imports it) so the provider
does not have to import the classification layer; there remains exactly one copy.

### What was deliberately left alone

| Item | Why |
|---|---|
| `interest_expense` | Genuine vendor data, and needed for cost-of-debt. |
| Synthetic fixtures (`SyntheticDataProvider`) | Hand-authored, not the vendor's mislabelled field. A bank fixture keeping an operating margin is not a defect. |
| `forecasts/forecast.py` tax-rate logic | It now simply finds no `operating_income` for a bank and takes its documented fallback. Changing the fallback would be a valuation change, out of scope for a data audit. |
| Bank DDM / RIM | Never read the field. Verified byte-identical output before and after. |

### Verification

- Valuation outputs are unchanged to full float precision, on both data sources:
  - Synthetic fixture: JPM P/E 201.56338983050847, P/B 163.52542372881356,
    Bank DDM 64.13294985123963, Bank RIM 141.9577341569924.
  - Real snapshot `20261123` (the numbers that actually ship): JPM P/E
    269.829051738457, P/B 148.22337691384058, Bank DDM 104.21381790075398,
    Bank RIM 145.2566392734194 — identical before and after.
- CB, V and BRK-B retain their operating income.
- Full suite: 1328 passed, 2 skipped (1309 before, +19 new).
- Mutation-checked: reverting any of the three enforcement points, or widening the
  rule to all tickers, makes the new tests fail. The tests are not vacuous.
- 50-ticker benchmark gate at snapshot `20261123`: 50/50 executed, 47 unchanged,
  3 changed (`JPM`/`BAC`/`GS`), every change explained. See
  `benchmark_50_postfix_report.md`.

### Residual limitation

The frozen snapshot still *contains* the bad numbers on disk; they are masked on
read rather than deleted. A future cache schema bump should drop them at write
time so the artifact stops carrying a figure we consider wrong. Until then,
anything that reads `.cache/yahoo_finance/*.json` directly — rather than going
through the provider — will still see EBIT labelled as operating income.

