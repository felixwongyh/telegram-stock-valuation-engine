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
for members of `BANK_HOLDING_COMPANIES`, enforced in `_build_statements` and in
`_suppress_bank_operating_income` (cache path). PPNR was rejected: it needs the
provision for credit losses, which the vendor does not supply and which cannot be
fetched offline. See `bank_operating_income_mapping_audit.md`.

## U-2 — Quarterly operating income is synthesized, not reported

**Severity: high. Status: RESOLVED for banks; open for other tickers.**

`data/providers.py:2033-2035` fills a missing quarterly EBIT with
`revenue × latest_annual_ebit_margin` and assigns it to `op_inc`. The inferred
value is indistinguishable from a reported one downstream, and the normalizer
sums four inferred quarters into TTM.

**Resolution (partial):** for banks the field no longer reaches a consumer, so
the synthesis cannot mislead there. The synthesis itself is still in place for
non-bank tickers that omit quarterly EBIT. It remains a silent inference: the
value carries no provenance marker. Tracked below as U-2b.

## U-2b — Inferred quarterly EBIT is not flagged as inferred

**Severity: medium. Status: open.**

Even where inference is legitimate, a consumer cannot tell a reported quarterly
EBIT from one computed as `revenue × annual margin`. Adding a provenance flag on
`FinancialStatement` would let models weight or refuse inferred inputs. Not done
here because it touches the statement schema and every consumer, which is beyond
a data audit.

Why not fixed now: removing the inference changes TTM operating income for every
ticker currently relying on it. That is a wide blast radius and needs its own
drift audit across the full 50-stock benchmark, which this audit is not scoped to
perform. Note the benchmark contains no bank other than JPM/BAC/GS/CB, so a
50-stock drift check would not by itself cover the affected population.

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
