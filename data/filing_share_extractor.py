"""data/filing_share_extractor.py — Extract share-count facts from original
SEC filing XBRL instance documents (Phase 1.1 / 1.2).

Why this exists
---------------
EdgarTools Company Facts (and the SEC Company Facts JSON API) aggregate XBRL
facts across filings, but they only return the **consolidated** (un-dimensioned)
values. For companies like HOOD that disclose shares **by class** (Class A /
Class B / Class C) using XBRL dimensions, the consolidated fact may be 0 or
missing, while the dimensioned facts carry the real numbers.

This module downloads the original 10-K / 10-Q XBRL instance document, parses
every share-related fact (including those with `StatementClassOfStockAxis` or
`StatementEquityComponentsAxis` dimensions), and returns structured evidence
with full provenance.

Resolution chain
----------------
  1. CIK           — reused from :class:`data.identity_resolver.IdentityResolver`.
  2. Latest filings — SEC submissions API (10-K and 10-Q).
  3. Instance URL  — filing directory index JSON → ``*_htm.xml``.
  4. Parse         — :func:`parse_share_facts_from_xbrl` (pure, offline-testable).

Design principles (from the P0 spec):
  * Every share number must trace to a source — never fabricate.
  * 0 is treated as invalid unless explicitly confirmed meaningful.
  * Weighted Average Shares are never used as a proxy for period-end shares.
  * Class-level facts are only summed when mutually exclusive and time-consistent.
  * Dimensioned facts and un-dimensioned facts are never double-counted.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import get_logger
from data.identity_resolver import IdentityResolver

log = get_logger("data.filing_share_extractor")

_DEFAULT_UA = "ValuationEngine/1.0 (research; contact@example.com)"
_SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_SEC_FILING_INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
_SEC_ARCHIVE_FILE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{name}"

# Share-related XBRL concepts (local names — match any taxonomy prefix).
_SHARE_LOCALS = frozenset({
    # DEI (cover page)
    "EntityCommonStockSharesOutstanding",
    # US-GAAP period-end (instant)
    "CommonStockSharesOutstanding",
    "CommonStockSharesIssued",
    "TreasuryStockShares",
    "PreferredStockSharesOutstanding",
    # US-GAAP weighted average (duration)
    "WeightedAverageNumberOfSharesOutstandingBasic",
    "WeightedAverageNumberOfDilutedSharesOutstanding",
    "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    # Additional
    "EntityPublicFloat",
})

# Axes that describe share class.
_CLASS_AXES = frozenset({
    "StatementClassOfStockAxis",
    "CommonStockClassAxis",
})

# Axes that describe equity components.
_EQUITY_AXES = frozenset({
    "StatementEquityComponentsAxis",
})

_NON_INSTANCE_XML = re.compile(r"^(r\d+|filingsummary)\.xml$|_(cal|def|lab|pre|ref)\.xml$")


@dataclass(frozen=True)
class FilingShareFact:
    """A single share-count fact from an XBRL instance document."""
    concept: str              # local name (e.g. "EntityCommonStockSharesOutstanding")
    value: float
    unit_ref: str
    context_id: str
    period_end: Optional[str]
    period_start: Optional[str]
    period_type: str          # "instant" or "duration"
    dimensions: Dict[str, str] = field(default_factory=dict)  # axis → member
    filing_form: str = ""     # "10-K", "10-Q"
    filing_date: str = ""
    accession_number: str = ""
    instance_filename: str = ""

    @property
    def has_class_dimension(self) -> bool:
        return any(a in _CLASS_AXES for a in self.dimensions)

    @property
    def has_equity_dimension(self) -> bool:
        return any(a in _EQUITY_AXES for a in self.dimensions)

    @property
    def is_dimensioned(self) -> bool:
        return bool(self.dimensions)

    @property
    def share_class(self) -> Optional[str]:
        """Extract the share class member name if present."""
        for axis, member in self.dimensions.items():
            if axis in _CLASS_AXES:
                return member
        return None

    @property
    def is_valid(self) -> bool:
        """0 is treated as invalid unless explicitly confirmed."""
        return self.value > 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "concept": self.concept,
            "value": self.value,
            "unit_ref": self.unit_ref,
            "context_id": self.context_id,
            "period_end": self.period_end,
            "period_start": self.period_start,
            "period_type": self.period_type,
            "dimensions": dict(self.dimensions),
            "has_class_dimension": self.has_class_dimension,
            "share_class": self.share_class,
            "filing_form": self.filing_form,
            "filing_date": self.filing_date,
            "accession_number": self.accession_number,
            "is_valid": self.is_valid,
        }


@dataclass
class ShareClassBreakdown:
    """Aggregated share-count by class for one filing."""
    classes: Dict[str, float] = field(default_factory=dict)  # class name → shares
    total: Optional[float] = None
    calculation_method: str = ""   # "sum_of_classes" | "direct_consolidated" | "single_class"
    period_end: Optional[str] = None
    source_filing: str = ""
    reconciliation_status: str = ""  # "VERIFIED" | "NEEDS_REVIEW" | "INCOMPLETE"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "classes": dict(self.classes),
            "total": self.total,
            "calculation_method": self.calculation_method,
            "period_end": self.period_end,
            "source_filing": self.source_filing,
            "reconciliation_status": self.reconciliation_status,
        }


def _local(tag: str) -> str:
    if not tag:
        return ""
    return tag.rsplit("}", 1)[-1]


def _local_attr(tag: str) -> str:
    """Local name of a QName or namespaced attribute value.

    Handles both formats:
      - ``{uri}local`` (ElementTree namespaced attribute)
      - ``prefix:local`` (QName as string, e.g. ``us-gaap:StatementClassOfStockAxis``)
    """
    if not tag:
        return ""
    # ElementTree {uri}local format
    if "}" in tag:
        tag = tag.rsplit("}", 1)[-1]
    # QName prefix:local format (e.g. us-gaap:StatementClassOfStockAxis)
    if ":" in tag:
        tag = tag.split(":", 1)[-1]
    return tag


def _fetch_json(url: str) -> Optional[dict]:
    import httpx
    try:
        client = httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
        r = client.get(url, headers={"User-Agent": _DEFAULT_UA})
        client.close()
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as e:
        log.debug(f"fetch error {url}: {e}")
        return None


def _fetch_text(url: str) -> Optional[str]:
    import httpx
    try:
        client = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))
        r = client.get(url, headers={"User-Agent": _DEFAULT_UA})
        client.close()
        if r.status_code != 200:
            return None
        return r.text
    except Exception as e:
        log.debug(f"fetch error {url}: {e}")
        return None


def _get_latest_filings(cik: str, forms: List[str], limit: int = 5) -> List[dict]:
    """Get latest filings from SEC submissions API."""
    cik_padded = str(cik).lstrip("0").zfill(10)
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
            if len(result) >= limit:
                break
    return result


def _pick_instance(names: Sequence[str]) -> Optional[str]:
    """Pick the XBRL instance from an EDGAR filing directory listing."""
    for n in names:
        if n.lower().endswith("_htm.xml"):
            return n
    for n in names:
        low = n.lower()
        if not low.endswith(".xml"):
            continue
        if _NON_INSTANCE_XML.match(low):
            continue
        return n
    return None


def parse_share_facts_from_xbrl(
    xml_text: str,
    *,
    filing_form: str = "",
    filing_date: str = "",
    accession_number: str = "",
    instance_filename: str = "",
) -> List[FilingShareFact]:
    """Parse all share-related facts from an XBRL instance document.

    This is the core pure function — no network, so it is unit-testable offline.
    Returns ALL share-related facts, including those with dimensions.

    Rules:
      - 0 values are INCLUDED in the output (marked as is_valid=False) so the
        caller can distinguish "filed as 0" from "missing entirely".
      - Dimensioned facts and un-dimensioned facts are both returned.
      - The caller is responsible for aggregation and dedup.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.debug(f"XML parse error: {e}")
        return []

    # Parse ALL contexts
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
    facts: List[FilingShareFact] = []
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
        facts.append(FilingShareFact(
            concept=concept,
            value=value,
            unit_ref=unit_ref,
            context_id=cref,
            period_end=ctx.get("period_end"),
            period_start=ctx.get("period_start"),
            period_type=ctx.get("period_type") or "",
            dimensions=ctx.get("dimensions", {}),
            filing_form=filing_form,
            filing_date=filing_date,
            accession_number=accession_number,
            instance_filename=instance_filename,
        ))

    return facts


def aggregate_share_classes_multi(
    facts: List[FilingShareFact],
    concepts: Optional[List[str]] = None,
) -> ShareClassBreakdown:
    """Try multiple concepts in priority order and return the first that yields facts.

    Many companies (e.g. HOOD) report shares under ``CommonStockSharesIssued``
    rather than ``CommonStockSharesOutstanding``. This wrapper tries each
    concept in order and delegates to :func:`aggregate_share_classes` for the
    first one that produces a non-INCOMPLETE breakdown.

    If ``concepts`` is None, uses the default priority:
      1. CommonStockSharesOutstanding
      2. CommonStockSharesIssued
      3. EntityCommonStockSharesOutstanding
    """
    if concepts is None:
        concepts = [
            "CommonStockSharesOutstanding",
            "CommonStockSharesIssued",
            "EntityCommonStockSharesOutstanding",
        ]
    best: Optional[ShareClassBreakdown] = None
    for concept in concepts:
        breakdown = aggregate_share_classes(facts, concept=concept)
        if breakdown.reconciliation_status != "INCOMPLETE":
            return breakdown
        if best is None and breakdown.total is not None:
            best = breakdown
    if best is not None:
        return best
    return ShareClassBreakdown(reconciliation_status="INCOMPLETE")


def aggregate_share_classes(
    facts: List[FilingShareFact],
    concept: str = "CommonStockSharesOutstanding",
) -> ShareClassBreakdown:
    """Aggregate dimensioned share facts into a class breakdown.

    This function:
      1. Filters to the specified concept and valid (value > 0) facts.
      2. Finds the latest period_end.
      3. Groups by share class (StatementClassOfStockAxis member).
      4. Sums class-level facts ONLY if they are mutually exclusive
         (different class members for the same period).
      5. Checks if a separate un-dimensioned total exists and reconciles.

    Calculation method:
      - "sum_of_classes" — total = sum of class-level facts (no un-dimensioned total)
      - "direct_consolidated" — total = the un-dimensioned fact
      - "single_class" — only one class exists, total = that class
      - "needs_review" — classes overlap or reconciliation fails
    """
    # Filter to concept + valid facts + instant period (period-end shares)
    concept_facts = [
        f for f in facts
        if f.concept == concept and f.is_valid and f.period_type == "instant"
    ]
    if not concept_facts:
        return ShareClassBreakdown(reconciliation_status="INCOMPLETE")

    # Find latest period_end
    latest_period = max(f.period_end for f in concept_facts if f.period_end)
    period_facts = [f for f in concept_facts if f.period_end == latest_period]

    # Separate dimensioned (by class) and un-dimensioned
    class_facts: Dict[str, FilingShareFact] = {}  # class member → fact
    un_dimensioned: Optional[FilingShareFact] = None
    equity_dimensioned: Optional[FilingShareFact] = None

    for f in period_facts:
        if f.has_class_dimension:
            cls = f.share_class or "Unknown"
            # Keep the first occurrence per class (avoid double-counting duplicates)
            if cls not in class_facts:
                class_facts[cls] = f
        elif f.has_equity_dimension:
            # StatementEquityComponentsAxis:CommonStockMember is a consolidated total
            equity_dimensioned = f
        elif not f.is_dimensioned:
            un_dimensioned = f

    classes = {cls: fact.value for cls, fact in class_facts.items()}

    # Determine total and method
    if class_facts and not un_dimensioned and not equity_dimensioned:
        # Only class-level facts → sum them
        total = sum(classes.values())
        method = "sum_of_classes"
        status = "VERIFIED"
    elif un_dimensioned and not class_facts:
        # Only un-dimensioned → direct
        total = un_dimensioned.value
        method = "direct_consolidated"
        status = "VERIFIED"
    elif equity_dimensioned and not class_facts:
        # Only equity-component dimensioned → direct (consolidated via equity axis)
        total = equity_dimensioned.value
        method = "direct_consolidated"
        status = "VERIFIED"
    elif class_facts and (un_dimensioned or equity_dimensioned):
        # Both exist → check reconciliation
        class_sum = sum(classes.values())
        consolidated = (un_dimensioned or equity_dimensioned).value
        if abs(class_sum - consolidated) / max(consolidated, 1) < 0.01:
            total = consolidated
            method = "sum_of_classes_reconciled"
            status = "VERIFIED"
        else:
            total = consolidated  # prefer the consolidated total
            method = "needs_review"
            status = "NEEDS_REVIEW"
    elif len(class_facts) == 1:
        total = list(classes.values())[0]
        method = "single_class"
        status = "VERIFIED"
    else:
        total = None
        method = "needs_review"
        status = "INCOMPLETE"

    return ShareClassBreakdown(
        classes=classes,
        total=total,
        calculation_method=method,
        period_end=latest_period,
        source_filing=period_facts[0].accession_number if period_facts else "",
        reconciliation_status=status,
    )


def find_dei_shares(facts: List[FilingShareFact]) -> Optional[FilingShareFact]:
    """Find the latest EntityCommonStockSharesOutstanding (DEI cover page).

    This is typically the most accurate period-end share count because it's
    reported as of a date close to the filing date (not the period end).
    """
    dei_facts = [
        f for f in facts
        if f.concept == "EntityCommonStockSharesOutstanding" and f.is_valid
    ]
    if not dei_facts:
        return None
    # DEI facts are instant — get the latest by period_end (filing cover date)
    return max(dei_facts, key=lambda f: f.period_end or "")


class FilingShareExtractor:
    """Download and parse share-count facts from SEC filing XBRL instances.

    Usage:
        extractor = FilingShareExtractor()
        facts = extractor.extract("HOOD")
        dei = find_dei_shares(facts)
        breakdown = aggregate_share_classes(facts)

    Phase 1.4: Also supports dilution evidence extraction via
    :meth:`extract_dilution`, which parses Options / RSU / Convertible /
    SBC facts from the same XBRL instances.
    """

    _MEM: Dict[str, List[FilingShareFact]] = {}
    _DILUTION_MEM: Dict[str, list] = {}
    _DEFAULT_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "filing_share_extractor.json"

    def __init__(self):
        self._xml_texts: Dict[str, List[Tuple[str, str, str, str]]] = {}
        """Maps ticker → list of (xml_text, form, filing_date, accession)."""

    def extract(self, ticker: str, max_filings: int = 3) -> List[FilingShareFact]:
        """Extract share facts from the latest filings for ``ticker``."""
        if ticker in self._MEM:
            return self._MEM[ticker]

        resolver = IdentityResolver(offline=False)
        identity = resolver.resolve(ticker)
        cik = identity.cik
        if not cik:
            return []

        cik_int = str(int(cik))
        filings = _get_latest_filings(cik_int, ["10-K", "10-Q"], limit=max_filings)
        if not filings:
            return []

        all_facts: List[FilingShareFact] = []
        xml_store: List[Tuple[str, str, str, str]] = []
        for filing in filings:
            accn = filing["accession"]
            index_url = _SEC_FILING_INDEX.format(cik=cik_int, accession=accn)
            index = _fetch_json(index_url)
            if not index:
                continue
            items = index.get("directory", {}).get("item", [])
            names = [item.get("name", "") for item in items if isinstance(item, dict)]
            instance_name = _pick_instance(names)
            if not instance_name:
                continue

            instance_url = _SEC_ARCHIVE_FILE.format(
                cik=cik_int, accession=accn, name=instance_name
            )
            xml_text = _fetch_text(instance_url)
            if not xml_text:
                continue

            # Store XML text for dilution extraction (Phase 1.4)
            xml_store.append((xml_text, filing["form"], filing["filing_date"], filing["accession_raw"]))

            facts = parse_share_facts_from_xbrl(
                xml_text,
                filing_form=filing["form"],
                filing_date=filing["filing_date"],
                accession_number=filing["accession_raw"],
                instance_filename=instance_name,
            )
            all_facts.extend(facts)

        self._xml_texts[ticker] = xml_store
        self._MEM[ticker] = all_facts
        return all_facts

    def extract_dilution(self, ticker: str) -> list:
        """Extract dilution evidence (Options / RSU / Convertible / SBC) from filings.

        Returns a list of :class:`data.dilution_evidence.DilutionEvidence`.

        This reuses the same XBRL instances downloaded by :meth:`extract`.
        If :meth:`extract` has not been called, it is called first.
        """
        from data.dilution_evidence import (
            parse_dilution_facts_from_xbrl,
            DilutionEvidence,
        )

        if ticker in self._DILUTION_MEM:
            return self._DILUTION_MEM[ticker]

        # Ensure share facts are extracted (which populates _xml_texts)
        if ticker not in self._xml_texts:
            self.extract(ticker)

        xml_store = self._xml_texts.get(ticker, [])
        all_dilution: list = []
        for xml_text, form, filing_date, accession in xml_store:
            dilution_facts = parse_dilution_facts_from_xbrl(
                xml_text,
                filing_form=form,
                filing_date=filing_date,
                accession_number=accession,
            )
            all_dilution.extend(dilution_facts)

        self._DILUTION_MEM[ticker] = all_dilution
        return all_dilution


__all__ = [
    "FilingShareFact",
    "ShareClassBreakdown",
    "FilingShareExtractor",
    "parse_share_facts_from_xbrl",
    "aggregate_share_classes",
    "aggregate_share_classes_multi",
    "find_dei_shares",
]
