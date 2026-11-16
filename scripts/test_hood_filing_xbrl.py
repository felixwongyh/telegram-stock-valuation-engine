"""scripts/test_hood_filing_xbrl.py — HOOD original Filing XBRL inspection.

Phase 1.1: Find why dei:EntityCommonStockSharesOutstanding is missing from
EdgarTools Company Facts, and extract period-end shares from the original
10-K / 10-Q Inline XBRL instance document.
"""
from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("EDGAR_IDENTITY", "ValuationEngine research@example.com")

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_DEFAULT_UA = "ValuationEngine/1.0 (research; contact@example.com)"
_SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_SEC_FILING_INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
_SEC_ARCHIVE_FILE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{name}"

# Share-related XBRL concepts (local names — match any taxonomy)
_SHARE_LOCALS = frozenset({
    "EntityCommonStockSharesOutstanding",
    "CommonStockSharesOutstanding",
    "CommonStockSharesIssued",
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    "TreasuryStockShares",
    "PreferredStockSharesOutstanding",
    "EntityPublicFloat",
})

# Class-of-stock axis (common across filings)
_CLASS_AXES = frozenset({
    "StatementClassOfStockAxis",
    "CommonStockClassAxis",
})


def _local(tag: str) -> str:
    if not tag:
        return ""
    return tag.rsplit("}", 1)[-1]


def _local_attr(tag: str) -> str:
    if not tag:
        return ""
    return tag.rsplit("}", 1)[-1]


def _fetch_json(url: str) -> Optional[dict]:
    import httpx
    headers = {"User-Agent": _DEFAULT_UA}
    try:
        client = httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
        r = client.get(url, headers=headers)
        client.close()
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        print(f"  fetch error {url}: {e}")
        return None


def _fetch_text(url: str) -> Optional[str]:
    import httpx
    headers = {"User-Agent": _DEFAULT_UA}
    try:
        client = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))
        r = client.get(url, headers=headers)
        client.close()
        if r.status_code != 200:
            return None
        return r.text
    except Exception as e:
        print(f"  fetch error {url}: {e}")
        return None


def _get_latest_filings(cik: str, forms: List[str]) -> List[dict]:
    """Get latest filings from SEC submissions API."""
    # SEC API requires CIK zero-padded to 10 digits with prefix
    cik_padded = cik.zfill(10)
    url = _SEC_SUBMISSIONS.format(cik=cik_padded)
    data = _fetch_json(url)
    if not data:
        return []
    recent = data.get("filings", {}).get("recent", {})
    form_arr = recent.get("form", [])
    accn_arr = recent.get("accessionNumber", [])
    date_arr = recent.get("filingDate", [])
    period_arr = recent.get("periodOfReport", [])
    forms_set = set(forms)
    result = []
    for i, form in enumerate(form_arr):
        if form in forms_set:
            accn = accn_arr[i] if i < len(accn_arr) else ""
            accn_clean = accn.replace("-", "")
            filing_date = date_arr[i] if i < len(date_arr) else ""
            period = period_arr[i] if i < len(period_arr) else ""
            result.append({
                "form": form,
                "accession": accn_clean,
                "accession_raw": accn,
                "filing_date": filing_date,
                "period": period,
            })
    return result


def _pick_instance(names: List[str]) -> Optional[str]:
    for n in names:
        if n.lower().endswith("_htm.xml"):
            return n
    for n in names:
        low = n.lower()
        if not low.endswith(".xml"):
            continue
        if re.match(r"^(r\d+|filingsummary)\.xml$|_(cal|def|lab|pre|ref)\.xml$", low):
            continue
        return n
    return None


def parse_share_facts_from_xbrl(xml_text: str) -> List[Dict[str, Any]]:
    """Parse all share-related facts from an XBRL instance document.

    Returns a list of dicts with: concept, value, unit, context_id, period_end,
    period_start, dimensions (dict of axis→member).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  XML parse error: {e}")
        return []

    # Parse ALL contexts (not just segment ones)
    contexts: Dict[str, Dict[str, Any]] = {}
    for el in root.iter():
        if _local(el.tag) != "context":
            continue
        cid = el.get("id")
        if not cid:
            continue
        ctx: Dict[str, Any] = {
            "period_end": None,
            "period_start": None,
            "period_type": None,
            "dimensions": {},
        }
        for sub in el.iter():
            lname = _local(sub.tag)
            if lname == "instant" and sub.text:
                ctx["period_end"] = sub.text.strip()
                ctx["period_type"] = "instant"
            elif lname == "startDate" and sub.text:
                ctx["period_start"] = sub.text.strip()
                ctx["period_type"] = "duration"
            elif lname == "endDate" and sub.text and not ctx["period_end"]:
                ctx["period_end"] = sub.text.strip()
                ctx["period_type"] = "duration"
            elif lname == "explicitMember":
                dim = _local_attr(sub.get("dimension") or "")
                if sub.text:
                    member = sub.text.strip().split(":", 1)[-1]
                    ctx["dimensions"][dim] = member
        contexts[cid] = ctx

    # Parse share-related facts
    facts: List[Dict[str, Any]] = []
    for el in root.iter():
        concept = _local(el.tag)
        if concept not in _SHARE_LOCALS:
            continue
        cref = el.get("contextRef")
        if not cref or el.text is None:
            continue
        ctx = contexts.get(cref, {})
        try:
            value = float(el.text.strip())
        except (ValueError, TypeError):
            continue
        unit_ref = el.get("unitRef", "")
        facts.append({
            "concept": concept,
            "value": value,
            "unit_ref": unit_ref,
            "context_id": cref,
            "period_end": ctx.get("period_end"),
            "period_start": ctx.get("period_start"),
            "period_type": ctx.get("period_type"),
            "dimensions": ctx.get("dimensions", {}),
        })

    return facts


def inspect_hood():
    """Full HOOD XBRL inspection."""
    print("=" * 70)
    print("  HOOD — Original Filing XBRL Inspection")
    print("=" * 70)

    cik = "0001783879"  # HOOD's CIK (zero-padded for SEC submissions API)
    cik_int = "1783879"  # for archive URLs (no leading zeros)

    # Step 1: Get latest 10-K and 10-Q filings
    print("\n--- Step 1: Get latest filings ---")
    filings = _get_latest_filings(cik, ["10-K", "10-Q"])
    if not filings:
        print("  No filings found!")
        return

    for f in filings[:5]:
        print(f"  {f['form']} filed {f['filing_date']} period {f['period']} accession={f['accession']}")

    # Step 2: Download and parse the XBRL instance for each filing
    all_results: Dict[str, Any] = {}

    for filing in filings[:4]:  # Check up to 4 filings
        accn = filing["accession"]
        form = filing["form"]
        period = filing["period"]
        print(f"\n--- Step 2: Parse {form} (period {period}, accession {accn}) ---")

        # Get filing directory listing
        index_url = _SEC_FILING_INDEX.format(cik=cik_int, accession=accn)
        index = _fetch_json(index_url)
        if not index:
            print(f"  Could not fetch index for {accn}")
            continue

        items = index.get("directory", {}).get("item", [])
        names = [item.get("name", "") for item in items if isinstance(item, dict)]
        instance_name = _pick_instance(names)
        if not instance_name:
            print(f"  No XBRL instance found in {accn}")
            print(f"  Files: {names[:15]}")
            continue

        print(f"  XBRL instance: {instance_name}")

        # Download the instance
        instance_url = _SEC_ARCHIVE_FILE.format(cik=cik_int, accession=accn, name=instance_name)
        xml_text = _fetch_text(instance_url)
        if not xml_text:
            print(f"  Could not download {instance_url}")
            continue

        print(f"  Downloaded {len(xml_text)} chars")

        # Parse share facts
        share_facts = parse_share_facts_from_xbrl(xml_text)
        print(f"  Found {len(share_facts)} share-related facts")

        # Group by concept and show details
        by_concept: Dict[str, List[dict]] = {}
        for f in share_facts:
            by_concept.setdefault(f["concept"], []).append(f)

        for concept, facts_list in sorted(by_concept.items()):
            print(f"\n  Concept: {concept} ({len(facts_list)} facts)")
            for fact in facts_list[:5]:
                dims = fact["dimensions"]
                dim_str = f" dims={dims}" if dims else ""
                period = fact["period_end"] or "?"
                val = fact["value"]
                print(f"    value={val:,.0f} period={period}{dim_str}")

        all_results[f"{form}_{period}"] = {
            "filing": filing,
            "instance": instance_name,
            "facts_count": len(share_facts),
            "facts": share_facts,
        }

    # Step 3: Analysis
    print("\n" + "=" * 70)
    print("  ANALYSIS")
    print("=" * 70)

    # Check if EntityCommonStockSharesOutstanding exists in any filing
    for key, result in all_results.items():
        facts = result["facts"]
        dei_facts = [f for f in facts if f["concept"] == "EntityCommonStockSharesOutstanding"]
        gaap_facts = [f for f in facts if f["concept"] == "CommonStockSharesOutstanding"]
        issued_facts = [f for f in facts if f["concept"] == "CommonStockSharesIssued"]

        print(f"\n  {key}:")
        print(f"    EntityCommonStockSharesOutstanding: {len(dei_facts)} facts")
        if dei_facts:
            latest = max(dei_facts, key=lambda f: f["period_end"] or "")
            print(f"      Latest: {latest['value']:,.0f} @ {latest['period_end']}")
        print(f"    CommonStockSharesOutstanding: {len(gaap_facts)} facts")
        if gaap_facts:
            for f in sorted(gaap_facts, key=lambda x: x["period_end"] or "")[-3:]:
                dims = f["dimensions"]
                dim_str = f" dims={dims}" if dims else ""
                print(f"      {f['value']:,.0f} @ {f['period_end']}{dim_str}")
        print(f"    CommonStockSharesIssued: {len(issued_facts)} facts")
        if issued_facts:
            for f in sorted(issued_facts, key=lambda x: x["period_end"] or "")[-3:]:
                dims = f["dimensions"]
                dim_str = f" dims={dims}" if dims else ""
                print(f"      {f['value']:,.0f} @ {f['period_end']}{dim_str}")

    # Save full results
    out_path = _PROJECT_ROOT / "scripts" / "hood_filing_xbrl_report.json"
    out_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n  Full results saved to: {out_path}")


if __name__ == "__main__":
    inspect_hood()
