"""scripts/test_edgartools_share_count.py — EdgarTools Capability Audit (Step 2).

Tests whether EdgarTools can reliably retrieve share-count data from SEC filings
for SOFI (and other test tickers). Records which concepts / periods / forms are
available so the Share Count Reconciliation Engine can decide where fallback is
needed.

Run:
    python scripts/test_edgartools_share_count.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Set SEC identity for EdgarTools
_IDENTITY = os.environ.get("EDGAR_IDENTITY", "ValuationEngine research@example.com")

# Share-count concepts to probe
_SHARE_CONCEPTS = [
    # Period-end shares
    "dei:EntityCommonStockSharesOutstanding",
    "us-gaap:CommonStockSharesOutstanding",
    "us-gaap:CommonStockSharesIssued",
    # Weighted average shares
    "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
    "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
    "us-gaap:WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    # Treasury
    "us-gaap:TreasuryStockShares",
    # Preferred
    "us-gaap:PreferredStockSharesOutstanding",
]


def _safe_getattr(obj: Any, attr: str) -> Any:
    try:
        return getattr(obj, attr)
    except Exception:
        return None


def _fact_to_dict(fact: Any) -> Dict[str, Any]:
    """Convert an EdgarTools FinancialFact to a serializable dict."""
    if fact is None:
        return {}
    return {
        "concept": _safe_getattr(fact, "concept"),
        "value": _safe_getattr(fact, "numeric_value"),
        "raw_value": _safe_getattr(fact, "value"),
        "unit": _safe_getattr(fact, "unit"),
        "period_end": str(_safe_getattr(fact, "period_end") or ""),
        "period_start": str(_safe_getattr(fact, "period_start") or ""),
        "fiscal_period": _safe_getattr(fact, "fiscal_period"),
        "fiscal_year": _safe_getattr(fact, "fiscal_year"),
        "form_type": _safe_getattr(fact, "form_type"),
        "filing_date": str(_safe_getattr(fact, "filing_date") or ""),
        "dimensions": str(_safe_getattr(fact, "dimensions") or ""),
        "accession": _safe_getattr(fact, "accession"),
        "taxonomy": _safe_getattr(fact, "taxonomy"),
        "is_dimensioned": _safe_getattr(fact, "is_dimensioned"),
    }


def probe_ticker(ticker: str) -> Dict[str, Any]:
    """Probe EdgarTools for one ticker, returning a structured report."""
    result: Dict[str, Any] = {
        "ticker": ticker,
        "cik": None,
        "shares_outstanding_property": None,
        "concepts": {},
        "filing_history": {},
        "errors": [],
    }

    try:
        import edgar

        edgar.set_identity(_IDENTITY)
        from edgar import Company

        company = Company(ticker)
        result["cik"] = str(company.cik) if company.cik else None

        # 1. Company.shares_outstanding (the convenience property)
        try:
            so = company.shares_outstanding
            result["shares_outstanding_property"] = {
                "value": float(so) if so is not None else None,
                "type": str(type(so)),
            }
        except Exception as e:
            result["shares_outstanding_property"] = {"error": str(e)}
            result["errors"].append(f"shares_outstanding: {e}")

        # 2. facts — probe each concept
        facts = company.facts
        df = facts.to_dataframe()

        for concept in _SHARE_CONCEPTS:
            concept_report: Dict[str, Any] = {
                "concept": concept,
                "available": False,
                "row_count": 0,
                "latest_fact": None,
                "annual_facts": [],
                "all_facts_summary": [],
            }
            try:
                sub = df[df["concept"] == concept]
                if len(sub) > 0:
                    concept_report["available"] = True
                    concept_report["row_count"] = len(sub)

                    # Get the latest fact via get_fact
                    try:
                        fact = facts.get_fact(concept)
                        concept_report["latest_fact"] = _fact_to_dict(fact)
                    except Exception:
                        pass

                    # Annual facts (FY)
                    annual = sub[sub["fiscal_period"] == "FY"]
                    for _, row in annual.head(5).iterrows():
                        concept_report["annual_facts"].append({
                            "value": float(row["numeric_value"]) if row["numeric_value"] is not None else None,
                            "unit": row["unit"],
                            "period_end": str(row["period_end"]),
                            "fiscal_year": row["fiscal_year"],
                        })

                    # All facts summary (latest 5)
                    for _, row in sub.head(5).iterrows():
                        concept_report["all_facts_summary"].append({
                            "value": float(row["numeric_value"]) if row["numeric_value"] is not None else None,
                            "unit": row["unit"],
                            "period_end": str(row["period_end"]),
                            "fiscal_period": row["fiscal_period"],
                            "fiscal_year": row["fiscal_year"],
                        })
            except Exception as e:
                concept_report["error"] = str(e)
                result["errors"].append(f"{concept}: {e}")

            result["concepts"][concept] = concept_report

        # 3. Filing history — 10-K and 10-Q
        for form in ("10-K", "10-Q"):
            try:
                filings = company.get_filings(form=form)
                filing_list = []
                for fl in list(filings)[:5]:
                    filing_list.append({
                        "form": fl.form,
                        "filing_date": str(fl.filing_date),
                        "accession_number": fl.accession_number,
                    })
                result["filing_history"][form] = {
                    "count": len(filings) if hasattr(filings, "__len__") else len(filing_list),
                    "latest_5": filing_list,
                }
            except Exception as e:
                result["filing_history"][form] = {"error": str(e)}
                result["errors"].append(f"filing_history {form}: {e}")

        # 4. shares_outstanding_fact
        try:
            sof = facts.shares_outstanding_fact
            result["shares_outstanding_fact"] = _fact_to_dict(sof)
        except Exception as e:
            result["shares_outstanding_fact"] = {"error": str(e)}
            result["errors"].append(f"shares_outstanding_fact: {e}")

        # 5. search_concepts for share-related terms
        try:
            search_results = {}
            for term in ("shares outstanding", "weighted average", "common stock"):
                r = facts.search_concepts(term)
                search_results[term] = str(r)
            result["search_concepts"] = search_results
        except Exception as e:
            result["search_concepts"] = {"error": str(e)}

    except Exception as e:
        result["errors"].append(f"FATAL: {e}")
        result["errors"].append(traceback.format_exc())

    return result


def main() -> None:
    test_tickers = ["SOFI", "HOOD", "PYPL", "COIN", "JPM", "BAC", "WFC"]
    results: Dict[str, Any] = {}

    for ticker in test_tickers:
        print(f"\n{'=' * 70}")
        print(f"  Probing {ticker} ...")
        print(f"{'=' * 70}")
        r = probe_ticker(ticker)
        results[ticker] = r

        # Print summary
        print(f"  CIK: {r.get('cik')}")
        so = r.get("shares_outstanding_property", {})
        if "value" in so:
            print(f"  shares_outstanding: {so['value']:,.0f}" if so.get("value") else "  shares_outstanding: None")
        elif "error" in so:
            print(f"  shares_outstanding: ERROR ({so['error'][:80]})")

        for concept, cr in r.get("concepts", {}).items():
            if cr.get("available"):
                latest = cr.get("latest_fact", {})
                val = latest.get("value")
                per = latest.get("period_end", "")
                form = latest.get("form_type", "")
                annual_cnt = len(cr.get("annual_facts", []))
                print(f"  {concept}: available ({cr['row_count']} rows, {annual_cnt} FY), latest={val:,.0f} @ {per} ({form})" if val else f"  {concept}: available ({cr['row_count']} rows), latest=None")
            else:
                print(f"  {concept}: NOT available")

        fh = r.get("filing_history", {})
        for form in ("10-K", "10-Q"):
            info = fh.get(form, {})
            cnt = info.get("count", 0)
            print(f"  {form} filings: {cnt}")

        errs = r.get("errors", [])
        if errs:
            print(f"  ERRORS: {len(errs)}")
            for e in errs[:3]:
                print(f"    - {e[:120]}")

    # Save full results
    out_path = _PROJECT_ROOT / "scripts" / "edgartools_capability_report.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n\nFull report saved to: {out_path}")


if __name__ == "__main__":
    main()
