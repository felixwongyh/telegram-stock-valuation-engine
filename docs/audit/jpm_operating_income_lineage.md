# JPM Operating Income — Data Lineage

Forensic audit, Session #57. Read-only investigation: no valuation formula,
Bank RIM, Beta, Ke or deposit threshold was touched, and no snapshot or golden
file was regenerated.

## Headline

`operating_income = 186,249,682,034.89746` for JPM is **not** a disclosed
operating income. It is a synthesized figure with two independent defects
stacked on top of each other:

1. The underlying Yahoo Finance "operating income" for a bank is really **EBIT**,
   defined as pre-tax income plus interest expense. For a bank, interest expense
   is a cost of doing business, so adding it back is wrong by construction.
2. The TTM figure is not a sum of reported quarters either: quarterly
   `operating_income` is **fabricated** as `revenue × 0.937563`, a margin carried
   over from FY2025.

Both defects reproduce exactly to the cent.

## Lineage chain

| Stage | Detail |
|---|---|
| Source provider | Yahoo Finance (Real) — `data/providers.py`, `_build_statements` |
| Original field name | `operatingIncome` in the time-series payload, mapped to ts key `OperatingIncome` |
| XBRL tag | **None.** Yahoo does not publish XBRL provenance. SEC's `us-gaap:OperatingIncomeLoss` returns **HTTP 404** for JPM — the concept is not reported by banks |
| Original value (TTM) | 186,249,682,034.89746 |
| Currency | USD |
| Unit | USD (whole dollars) |
| Fiscal period | Labelled `TTM(2026-09-30)` |
| Period basis | TTM, but synthesized — see below |
| Normalization | `ebit = rev × ebit_margin_latest_annual; op_inc = ebit` (`providers.py:2033-2035`) |
| Final value | 186,249,682,034.89746 |

## Defect 1 — the annual figure is EBIT, not operating income

Yahoo's FY2025 annual `operating_income` is 170,493,000,000. SEC's FY2025
pre-tax income is 72,595,000,000. The gap is exactly Yahoo's reported interest
expense:

```
SEC pre-tax income (FY2025)        72,595,000,000
+ Yahoo interest expense           97,898,000,000
= Yahoo "operating income"        170,493,000,000   (exact)
```

So Yahoo's field is `pre-tax income + interest expense` = EBIT. Confirmed
identically for BAC and GS (see `bank_operating_income_mapping_audit.md`).

For a non-financial this convention is defensible: interest expense sits below
EBIT, so adding it back recovers EBIT. For a bank, interest expense is the cost
of the deposit base — it is operating, not financing. Adding it back inflates
the figure by roughly the size of net interest expense.

## Defect 2 — quarterly values are fabricated, and TTM is their sum

Quarterly `operating_income` for JPM takes exactly one ratio to revenue across
all five quarters: **0.937563**. Real quarterly margins never coincide to six
decimal places. That constant is the FY2025 annual ratio:

```
FY2025 annual: 170,493 / 181,847 = 0.937562896
```

Reproducing each quarter as `revenue × 0.937562896`:

| Quarter | Revenue | Computed | Cached | Match |
|---|---|---|---|---|
| 2026-09-30 | 50,172,000,000 | 47,039,405,632.21 | 47,039,405,632.2073 | exact |
| 2026-06-30 | 52,852,000,000 | 49,552,074,194.24 | 49,552,074,194.24021 | exact |
| 2026-03-31 | 49,833,000,000 | 46,721,571,810.37 | 46,721,571,810.36806 | exact |
| 2025-12-31 | 45,796,000,000 | 42,936,630,398.08 | 42,936,630,398.0819 | exact |

The TTM value is the sum of these four fabricated quarters:
`sum = 186,249,682,034.90` — identical to the reported TTM to the cent.

Root of the fabrication is `data/providers.py:2033-2035`:

```python
if ebit is None and rev and ebit_margin_latest_annual is not None:
    ebit = rev * ebit_margin_latest_annual
    op_inc = ebit
```

This runs for the quarterly series (the annual series has real EBIT), and the
inferred value is then summed into TTM by the normalizer.

## Why the existing sanity guard did not catch it

`providers.py` drops an `op_inc` that exceeds a ceiling of gross profit, or
revenue when gross profit is absent. JPM's `gross_profit` is `None`, so the
ceiling becomes revenue (198,653,000,000). The fabricated 186,249,682,034 sits
just under that ceiling — 93.8% of revenue — so the guard passes it.

The guard was written for the case "EBIT exceeds gross profit", which is
impossible. It does not catch "EBIT is implausibly close to revenue for a bank",
which is merely implausible, not arithmetically impossible.

## Downstream consumers

| Consumer | Uses `operating_income`? | Affected? |
|---|---|---|
| `models/bank.py` (Bank DDM, Bank RIM) | No — uses `net_income`, `book_equity`, `eps`, `dps` | **No** |
| `models/dcf.py` (FCFF) | Only as a presence check | Not reached for banks |
| `forecasts/forecast.py` | Operating margin, tax rate | Not reached for banks |
| `classification/classifier.py:1339` | `interest_expense / operating_income` | Guarded, see below |
| `classification/taxonomy.py:1078` | Operating margin | Secondary |

**The bank valuations are not corrupted.** JPM/BAC/GS resolve to
`applicable_models = [Bank DDM, Bank RIM, P/B, P/E]`, and the bank models read
net income and book equity. This is the single most important finding: the
number is wrong, but it does not reach the price target.

The classification signal at `classifier.py:1339` would be affected, except that
`ttm.interest_expense` is `None` for all three banks, so the code takes the
documented fallback branch (`interest expense / revenue`) and the operating
income never enters the ratio. Banks are also classified through
`BANK_HOLDING_COMPANIES`, an explicit registry, so classification does not hinge
on this signal.

## Period caveat

The snapshot is labelled `TTM(2026-09-30)`, but SEC XBRL for JPM contains no
facts after 2025-12-31 (latest `Revenues` fact end: 2025-12-31; quarterly facts
stop in 2014). The 2026 quarters cannot be cross-checked against SEC XBRL at
all. They are labelled as reported data but carry a fabricated operating income;
whether their revenue figures are genuine is a separate question this audit
cannot settle from the frozen snapshot alone.

## Root cause classification

Two categories apply, in this order:

- **WRONG_XBRL_MAPPING** — the vendor field labelled "operating income" is EBIT
  (`pre-tax + interest expense`), a definition that is invalid for a bank.
- **INCORRECT_NORMALIZATION** — quarterly operating income is synthesized from
  an annual margin rather than reported, and the synthesized quarters are summed
  into TTM.

`CORRECT_VALUE_CORRECT_LABEL` does not apply: the value is neither correct nor
correctly labelled.
