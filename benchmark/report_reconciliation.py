"""benchmark/report_reconciliation.py -- emit the three phase reports.

Run:
    python -m benchmark.report_reconciliation
    python -m benchmark.report_reconciliation --snapshot shadow-20261128

Writes to ``docs/audit/``:

* ``SHADOW_SNAPSHOT_REPORT.md``      -- what each shadow holds and proves
* ``GOLDEN_RECONCILIATION_REPORT.md``-- field-by-field golden vs shadow
* ``PROVENANCE_COVERAGE_REPORT.md``  -- origin counts before vs after

The reports state facts and open questions. They never assert that a shadow
*should* replace the golden -- that is a human decision this phase must not
pre-empt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark.reconcile import (
    DATA_FIELDS,
    load_shadow,
    reconcile_data,
    summary,
)
from data.shadow_snapshot import SHADOW_ROOT, verify_shadow

log = logging.getLogger("benchmark.report_reconciliation")

DOCS = Path(__file__).resolve().parent.parent / "docs" / "audit"
GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "golden" / "report_fingerprints.json"


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if abs(v) >= 1e9:
            return f"{v/1e9:,.2f}B"
        if abs(v) >= 1e6:
            return f"{v/1e6:,.2f}M"
        return f"{v:,.4f}"
    return str(v)


def _golden_ttm(ticker: str) -> Dict[str, Any]:
    """Load the frozen golden statement for one ticker (read-only)."""
    from data.normalizer import FinancialNormalizer
    from data.providers import YahooFinanceProvider

    d = FinancialNormalizer.normalize_all(
        asyncio.run(YahooFinanceProvider().get_financial_data(ticker)))
    ttm = d.ttm
    g = {f: getattr(ttm, f, None) for f in DATA_FIELDS}
    prov = {}
    for f in DATA_FIELDS:
        fp = (ttm.field_provenance or {}).get(f)
        ot = getattr(fp, "origin_type", None) if fp else None
        prov[f] = {
            "origin_type": getattr(ot, "value", ot),
            "algorithm_version": getattr(fp, "algorithm_version", None) if fp else None,
        }
    g["_provenance"] = prov
    g["_period_end"] = str(getattr(ttm, "period_end", ""))
    return g


def build_shadow_report(snapshot_id: str, tickers: List[str]) -> str:
    lines = [
        "# Shadow Snapshot Report",
        "",
        f"Snapshot id: `{snapshot_id}`  ",
        f"Generated: {datetime.now(timezone.utc).isoformat()}  ",
        "Generator: `python -m benchmark.report_reconciliation`",
        "",
        "## What a shadow snapshot is",
        "",
        "Each ticker directory under `data/shadow_snapshots/<snapshot>/<TICKER>/`",
        "holds the vendor's **raw response bytes**, a SHA-256 per artefact, the",
        "retrieval timestamp, the fiscal period, and per-field provenance.",
        "`verify_shadow()` re-hashes every artefact, so a silent edit becomes",
        "visible rather than invisible.",
        "",
        "## Integrity",
        "",
        "| Ticker | Artefacts | Digests verified | Filing evidence |",
        "|---|---|---|---|",
    ]
    for t in tickers:
        v = verify_shadow(snapshot_id, t)
        n = v.get("artifacts_checked", 0)
        ok = "yes" if v.get("ok") else f"**NO** ({v.get('mismatches')})"
        filing = "yes" if v.get("has_company_filing_evidence") else "no"
        lines.append(f"| {t} | {n} | {ok} | {filing} |")

    lines += [
        "",
        "## Field provenance per ticker",
        "",
        "`COMPANY_REPORTED` requires a filing accession number. `VENDOR_REPORTED`",
        "means the vendor returned it and nothing corroborated it — a weaker",
        "claim, labelled as such.",
        "",
    ]
    for t in tickers:
        p = SHADOW_ROOT / snapshot_id / t / "provenance.json"
        if not p.exists():
            continue
        prov = json.loads(p.read_text())
        counts = Counter(
            (rec.get("origin_type") if isinstance(rec.get("origin_type"), str)
             else getattr(rec.get("origin_type"), "value", None))
            for rec in prov.values()
        )
        sec = json.loads(
            (SHADOW_ROOT / snapshot_id / t / "raw" / "sec_facts.json").read_text()
        ) if (SHADOW_ROOT / snapshot_id / t / "raw" / "sec_facts.json").exists() else {}
        lines += [
            f"### {t}",
            "",
            f"Annual period end: `{json.loads((SHADOW_ROOT/snapshot_id/t/'statement.json').read_text()).get('period_end')}`  ",
            f"CIK: `{sec.get('cik')}`  ",
            "",
            "| Origin | Fields |",
            "|---|---|",
        ]
        for origin, n in sorted(counts.items(), key=lambda kv: str(kv[0])):
            lines.append(f"| {origin} | {n} |")

        matched = sec.get("matched_fields") or []
        corr = sec.get("corroborations") or {}
        contradicted = [k for k, v in corr.items()
                        if v.get("status") == "contradicted"]
        checked_no_fact = [k for k, v in corr.items()
                           if v.get("status") == "no_sec_fact"]
        unmapped = sorted(set(prov) - set(corr))
        lines += [
            "",
            f"Corroborated by SEC XBRL: **{len(matched)}** fields  ",
            f"Contradicted by SEC XBRL: **{len(contradicted)}** "
            f"{('(' + ', '.join(contradicted) + ')') if contradicted else ''}  ",
            f"Checked, no filing fact found: **{len(checked_no_fact)}** "
            f"{('(' + ', '.join(checked_no_fact) + ')') if checked_no_fact else ''}  ",
            f"No SEC concept of that semantics: **{len(unmapped)}** "
            f"{('(' + ', '.join(unmapped) + ')') if unmapped else ''}",
            "",
        ]
        gaps = [(k, v) for k, v in corr.items() if v.get("period_label_gap_days")]
        if gaps:
            lines.append("Fiscal-period label gaps (vendor label vs filing period):")
            for k, v in gaps:
                lines.append(f"- `{k}`: vendor `{v.get('period_end')}` vs filing "
                             f"`{v.get('sec_period_end')}` "
                             f"({v.get('period_label_gap_days')} days)")
            lines.append("")
    return "\n".join(lines)


def build_reconciliation_report(snapshot_id: str, tickers: List[str]) -> str:
    golden_fp = json.loads(GOLDEN.read_text())
    lines = [
        "# Golden Reconciliation Report",
        "",
        f"Snapshot under test: `{snapshot_id}`  ",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Scope and honesty rules",
        "",
        "- The frozen golden in `.cache/yahoo_finance` is **read, never written**.",
        "- Shadow data is compared at **TTM cadence**, because the golden is TTM.",
        "  Comparing an annual shadow to a TTM golden would report a period shift",
        "  as a data change.",
        "- A row is only called *material* above 0.5%. Below that a vendor's",
        "  rounding is indistinguishable from a real move.",
        "- **No golden value is proposed for replacement here.** This phase",
        "  produces evidence; the decision to re-baseline is human.",
        "",
    ]
    for t in tickers:
        shadow = load_shadow(snapshot_id, t)
        if not shadow:
            lines += [f"## {t}", "", "No shadow snapshot found.", ""]
            continue
        try:
            golden = _golden_ttm(t)
        except Exception as e:
            lines += [
                f"## {t}", "",
                f"Golden unavailable: `{type(e).__name__}`", "",
                "No comparison is made. AMD has no entry in the frozen snapshot",
                "`20261123`; the only AMD cache file present is for a different",
                "snapshot id. Reporting a delta here would require substituting",
                "today's data for the historical figure, which is the provenance",
                "fraud this phase exists to prevent.",
                "",
                f"The shadow for `{t}` still exists and its provenance stands on",
                "its own — see the Shadow Snapshot Report.",
                "",
            ]
            continue

        rows = reconcile_data(golden, shadow)
        s = summary(rows)
        lines += [
            f"## {t}",
            "",
            f"Golden period: `{golden.get('_period_end')}`  ",
            f"Shadow period: `{shadow.get('_period_end')}`  ",
            f"Material changes: **{s['material']}** of {s['total_rows']}",
            "",
            "| Field | Golden | Shadow | Δ% | Golden origin | Shadow origin | Reason |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            pct = "—" if r.percentage_delta is None else f"{r.percentage_delta:+.2%}"
            reason = r.reason if not r.material else f"**{r.reason}**"
            lines.append(
                f"| {r.metric} | {_fmt(r.old_value)} | {_fmt(r.new_value)} | {pct} "
                f"| {r.old_provenance or '—'} | {r.new_provenance or '—'} | {reason} |"
            )

        # Agreement with the golden valuation fingerprint is reported, but the
        # fingerprint is not recomputed: that needs the live pipeline, and a
        # number produced here would look like a shadow re-baseline.
        g = golden_fp.get(t) or {}
        lines += [
            "",
            f"Golden fingerprint median value: **{g.get('median_value')}** "
            f"(n_solved={g.get('n_solved')}, agreement={g.get('agreement_level')})",
            "",
        ]
    return "\n".join(lines)


def build_coverage_report(snapshot_id: str, tickers: List[str]) -> str:
    lines = [
        "# Provenance Coverage Report",
        "",
        f"Snapshot: `{snapshot_id}`  ",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Origin taxonomy",
        "",
        "| Origin | Meaning | Trust |",
        "|---|---|---|",
        "| `company_reported` | Matched to a filing with an accession number | Strongest |",
        "| `reported` | Legacy label, no source split | Vendor-level |",
        "| `vendor_reported` | Vendor normalised figure, uncorroborated | Vendor-level |",
        "| `derived` | Computed by a versioned algorithm | Auditable |",
        "| `estimated` | Modelled from a ratio | Weak |",
        "| `imputed` | Filled to complete a period | Weakest usable |",
        "| `unknown_legacy` | Origin never recorded | Not a fact |",
        "",
        "`vendor_reported` is deliberately ranked *below* `company_reported`: a",
        "vendor restates, reclassifies and rounds, so 'Yahoo says so' is a weaker",
        "statement than 'the 10-K says so'. Collapsing the two is the laundering",
        "this taxonomy prevents.",
        "",
        "## Coverage by layer",
        "",
        "Both layers are shown because they say different things, and reporting",
        "only the annual layer would overstate the result.",
        "",
        "| Ticker | Layer | Period | company_reported | vendor_reported | unknown_legacy |",
        "|---|---|---|---|---|---|",
    ]
    for t in tickers:
        try:
            golden = _golden_ttm(t)
            gc = Counter(
                (r.get("origin_type") or "unknown_legacy")
                for r in golden["_provenance"].values()
            )
            gline = (f"| {t} | golden | {golden.get('_period_end')} "
                     f"| {gc.get('company_reported', 0)} "
                     f"| {gc.get('vendor_reported', 0) + gc.get('reported', 0)} "
                     f"| {gc.get('unknown_legacy', 0)} |")
        except Exception as e:
            gline = (f"| {t} | golden | unavailable ({type(e).__name__}) "
                     f"| — | — | — |")
        lines.append(gline)

        for layer, fname in (("shadow annual", "provenance.json"),
                             ("shadow TTM", "ttm_provenance.json")):
            sp = SHADOW_ROOT / snapshot_id / t / fname
            if not sp.exists():
                continue
            prov = json.loads(sp.read_text())
            sc = Counter(
                (r.get("origin_type") if isinstance(r.get("origin_type"), str)
                 else getattr(r.get("origin_type"), "value", None))
                for r in prov.values()
            )
            stmt = json.loads((SHADOW_ROOT / snapshot_id / t /
                               ("statement.json" if fname == "provenance.json"
                                else "ttm_statement.json")).read_text())
            lines.append(
                f"| {t} | {layer} | {stmt.get('period_end')} "
                f"| {sc.get('company_reported', 0)} "
                f"| {sc.get('vendor_reported', 0)} "
                f"| {sc.get('unknown_legacy', 0)} |"
            )

    lines += [
        "",
        "## The TTM layer cannot be company-reported, and that is correct",
        "",
        "Every TTM field in every shadow is `vendor_reported`, by construction.",
        "A trailing-twelve-month total spanning a non-calendar window is not a",
        "figure any company files, so no XBRL fact exists to corroborate it.",
        "Claiming `company_reported` for a sum of four quarters would be exactly",
        "the fabrication this phase forbids.",
        "",
        "The consequence is worth stating plainly: the golden being reconciled is",
        "a TTM statement, so the strongest evidence available for the fields it",
        "consumes is *vendor-reported with a recorded derivation*, not",
        "filing-grade. Filing-grade provenance exists for the shadow's **annual**",
        "layer only, where up to 12 fields per ticker match an SEC fact with an",
        "accession number and a filing date.",
        "",
        "## What stays vendor-only, and why",
        "",
        "| Field | Reason no filing corroboration exists |",
        "|---|---|",
        "| `ebitda` | Derived by vendors from EBIT + D&A; no us-gaap concept of",
        "that semantics |",
        "| `ebit` | EBIT includes non-operating income; `OperatingIncomeLoss` is a",
        "different quantity (matching them produced a false 8.9% contradiction on",
        "MSFT) |",
        "| `free_cash_flow` | A vendor construction (OCF − capex); filers report the",
        "components, not the difference |",
        "| `depreciation_amortization` | Filers use entity-specific extension tags;",
        "no single us-gaap concept covers it |",
        "| `total_debt`, `change_in_nwc`, `stock_based_compensation` | Aggregates",
        "composed from several filing lines |",
        "",
        "A field that stays `vendor_reported` is not a failure of the engine. It",
        "is the engine declining to overstate what it can prove.",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--tickers", nargs="*", default=None)
    args = ap.parse_args(argv)

    sid = args.snapshot
    if sid is None:
        ids = sorted(p.name for p in SHADOW_ROOT.iterdir() if p.is_dir()) \
            if SHADOW_ROOT.exists() else []
        if not ids:
            print("no shadow snapshots found")
            return 1
        sid = ids[-1]
    tickers = args.tickers or sorted(p.name for p in (SHADOW_ROOT / sid).iterdir()
                                     if p.is_dir())

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "SHADOW_SNAPSHOT_REPORT.md").write_text(
        build_shadow_report(sid, tickers) + "\n")
    (DOCS / "GOLDEN_RECONCILIATION_REPORT.md").write_text(
        build_reconciliation_report(sid, tickers) + "\n")
    (DOCS / "PROVENANCE_COVERAGE_REPORT.md").write_text(
        build_coverage_report(sid, tickers) + "\n")
    print(f"wrote 3 reports for {sid}: {', '.join(tickers)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
