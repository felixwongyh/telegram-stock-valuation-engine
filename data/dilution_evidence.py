"""data/dilution_evidence.py — Dilution evidence parser (Phase 1.4).

Extracts evidence of potential dilutive securities from SEC filings:
  - Stock Options (outstanding, exercisable, weighted average exercise price)
  - RSU (unvested, granted, vested, forfeited)
  - Convertible Securities (principal, conversion price, potential shares)
  - SBC Expense (stock-based compensation — a cost, NOT a share count)

IMPORTANT DESIGN PRINCIPLE:
  This module ONLY COLLECTS EVIDENCE. It does NOT calculate fully-diluted
  shares. The calculation requires method choices (treasury stock method,
  if-converted method, etc.) that must be made explicitly by the valuation
  model, not silently by the data layer.

  GAAP Diluted Weighted Average Shares (already available from the share
  count engine) is the primary diluted share count. This module provides
  the ADDITIONAL evidence needed to understand what's behind that number.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import get_logger

log = get_logger("data.dilution_evidence")

# XBRL concepts related to dilutive securities (local names)
_DILUTION_LOCALS = frozenset({
    # Stock options
    "StockOptionsOutstanding",
    "StockOptionsExercisable",
    "WeightedAverageExercisePriceStockOptions",
    "RemainingContractualLifeStockOptions",
    # RSU
    "RestrictedStockUnitsOutstanding",
    "RestrictedStockUnitsUnvested",
    "RestrictedStockUnitsVested",
    "RestrictedStockUnitsForfeited",
    "RestrictedStockUnitsGranted",
    # Convertible
    "ConvertibleNotes",
    "ConvertibleDebt",
    "ConversionPrice",
    "ConversionRatio",
    "PotentialCommonSharesConvertible",
    # SBC
    "StockBasedCompensationExpense",
    "ShareBasedPaymentArrangement",
    "IncrementalCommonSharesAwarded",
    # Diluted shares
    "IncrementalSharesUsedToCalculateDilutedEarningsPerShare",
    "AntidilutiveSecuritiesExcludedFromCalculation",
    "DilutedEarningsPerShare",
    "BasicEarningsPerShare",
})


@dataclass
class DilutionEvidence:
    """A single piece of dilution evidence from a filing."""
    concept: str
    value: float
    unit: str
    period_end: Optional[str] = None
    period_type: str = ""
    dimensions: Dict[str, str] = field(default_factory=dict)
    filing_form: str = ""
    filing_date: str = ""
    accession_number: str = ""
    evidence_type: str = ""   # "options" | "rsu" | "convertible" | "sbc" | "diluted_eps"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "concept": self.concept,
            "value": self.value,
            "unit": self.unit,
            "period_end": self.period_end,
            "period_type": self.period_type,
            "dimensions": dict(self.dimensions),
            "filing_form": self.filing_form,
            "filing_date": self.filing_date,
            "accession_number": self.accession_number,
            "evidence_type": self.evidence_type,
        }


@dataclass
class DilutionEvidenceReport:
    """Aggregated dilution evidence for one company."""
    ticker: str = ""
    options: List[DilutionEvidence] = field(default_factory=list)
    rsu: List[DilutionEvidence] = field(default_factory=list)
    convertible: List[DilutionEvidence] = field(default_factory=list)
    sbc: List[DilutionEvidence] = field(default_factory=list)
    diluted_eps_info: List[DilutionEvidence] = field(default_factory=list)
    antidilutive: List[DilutionEvidence] = field(default_factory=list)
    all_evidence: List[DilutionEvidence] = field(default_factory=list)

    # Summary (NOT a calculation — just what the filing discloses)
    gaap_diluted_weighted_avg_shares: Optional[float] = None
    incremental_dilutive_shares: Optional[float] = None  # from EPS reconciliation
    antidilutive_shares: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "options": [e.as_dict() for e in self.options],
            "rsu": [e.as_dict() for e in self.rsu],
            "convertible": [e.as_dict() for e in self.convertible],
            "sbc": [e.as_dict() for e in self.sbc],
            "diluted_eps_info": [e.as_dict() for e in self.diluted_eps_info],
            "antidilutive": [e.as_dict() for e in self.antidilutive],
            "gaap_diluted_weighted_avg_shares": self.gaap_diluted_weighted_avg_shares,
            "incremental_dilutive_shares": self.incremental_dilutive_shares,
            "antidilutive_shares": self.antidilutive_shares,
            "all_evidence_count": len(self.all_evidence),
        }


def _local(tag: str) -> str:
    if not tag:
        return ""
    return tag.rsplit("}", 1)[-1]


def _classify_evidence(concept: str) -> str:
    """Classify a concept into an evidence type."""
    c = concept.lower()
    if "option" in c:
        return "options"
    if "restricted" in c or "rsu" in c:
        return "rsu"
    if "convert" in c:
        return "convertible"
    if "stockbased" in c or "sharebased" in c or "stock_based" in c:
        return "sbc"
    if "antidilutive" in c:
        return "antidilutive"
    if "diluted" in c or "incremental" in c:
        return "diluted_eps"
    return ""


def parse_dilution_facts_from_xbrl(
    xml_text: str,
    *,
    filing_form: str = "",
    filing_date: str = "",
    accession_number: str = "",
) -> List[DilutionEvidence]:
    """Parse dilution-related facts from an XBRL instance document.

    This is the pure parsing function — no network, unit-testable.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Parse contexts (same logic as filing_share_extractor)
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
                dim = _local(sub.get("dimension") or "")
                if sub.text:
                    member = sub.text.strip().split(":", 1)[-1]
                    ctx["dimensions"][dim] = member
        contexts[cid] = ctx

    facts: List[DilutionEvidence] = []
    for el in root.iter():
        concept = _local(el.tag)
        if concept not in _DILUTION_LOCALS:
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
        etype = _classify_evidence(concept)
        facts.append(DilutionEvidence(
            concept=concept,
            value=value,
            unit=unit_ref,
            period_end=ctx.get("period_end"),
            period_type=ctx.get("period_type") or "",
            dimensions=ctx.get("dimensions", {}),
            filing_form=filing_form,
            filing_date=filing_date,
            accession_number=accession_number,
            evidence_type=etype,
        ))

    return facts


def build_dilution_report(
    ticker: str,
    all_facts: List[DilutionEvidence],
) -> DilutionEvidenceReport:
    """Build a structured dilution evidence report from parsed facts."""
    report = DilutionEvidenceReport(ticker=ticker, all_evidence=all_facts)

    for f in all_facts:
        if f.evidence_type == "options":
            report.options.append(f)
        elif f.evidence_type == "rsu":
            report.rsu.append(f)
        elif f.evidence_type == "convertible":
            report.convertible.append(f)
        elif f.evidence_type == "sbc":
            report.sbc.append(f)
        elif f.evidence_type == "diluted_eps":
            report.diluted_eps_info.append(f)
            if "Incremental" in f.concept:
                report.incremental_dilutive_shares = f.value
        elif f.evidence_type == "antidilutive":
            report.antidilutive.append(f)
            report.antidilutive_shares = f.value

    return report


__all__ = [
    "DilutionEvidence",
    "DilutionEvidenceReport",
    "parse_dilution_facts_from_xbrl",
    "build_dilution_report",
]
