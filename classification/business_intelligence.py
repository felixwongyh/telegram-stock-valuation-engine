"""classification/business_intelligence.py — Business Intelligence Layer: evidence.

Collects the **business evidence** that describes what a company does and where
its revenue comes from. This is the raw material the taxonomy resolver
(``classification.taxonomy``) consumes for dimensions ① Business Identity and
③ Revenue Composition.

Evidence sources (all optional, all provenance-carrying):

  * Business description — the provider's business summary
    (Yahoo ``longBusinessSummary`` → ``MarketData.description``).
  * Revenue segments     — FMP segment revenue resolved by
    ``data.segment_revenue`` and stashed on ``FinancialData.revenue_composition``
    (M-31).

This module is a thin, provenance-carrying collector. It never invents a
description or a segment mix: absent evidence is reported as *absent*, so a
downstream decision can honestly say "insufficient data" instead of guessing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from config import get_logger

log = get_logger("classification.business_intelligence")


@dataclass
class BusinessEvidence:
    """Business description + revenue segment mix, with provenance.

    ``revenue_segments`` is a list of ``(label, pct)`` where ``pct`` is a 0..1
    share of total revenue (``None`` when the source did not report a share).
    """

    description: Optional[str] = None
    description_source: str = "none"
    revenue_segments: List[Tuple[str, Optional[float]]] = field(default_factory=list)
    revenue_source: str = "none"
    revenue_as_of: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @property
    def has_description(self) -> bool:
        return bool(self.description and self.description.strip())

    @property
    def has_segments(self) -> bool:
        return bool(self.revenue_segments)

    def provenance(self) -> Dict[str, str]:
        return {
            "description": self.description_source if self.has_description else "unknown",
            "revenue_segments": self.revenue_source if self.has_segments else "unknown",
        }


def _revenue_from_composition(comp: Any) -> Tuple[List[Tuple[str, Optional[float]]], str, Optional[str]]:
    """Extract ``(segments, source, as_of)`` from a RevenueComposition-like object."""
    if comp is None or not getattr(comp, "available", False):
        return [], "none", None
    segments: List[Tuple[str, Optional[float]]] = []
    for seg in getattr(comp, "segments", None) or []:
        label = getattr(seg, "label", None)
        if not label:
            continue
        segments.append((str(label), getattr(seg, "pct", None)))
    source = getattr(comp, "source", None) or "segment_revenue"
    return segments, str(source), getattr(comp, "as_of", None)


def extract_business_evidence(
    data: Any,
    *,
    description: Optional[str] = None,
) -> BusinessEvidence:
    """Assemble the business evidence for one company from ``FinancialData``.

    ``description`` overrides the provider description when supplied; otherwise
    ``MarketData.description`` / ``business_summary`` is used. Revenue segments
    come from ``FinancialData.revenue_composition`` (explicitly unavailable when
    no segment source resolved).
    """
    market = getattr(data, "market", None)
    if description is None and market is not None:
        description = getattr(market, "description", None) or getattr(market, "business_summary", None)

    ev = BusinessEvidence()
    if description and description.strip():
        ev.description = description.strip()
        ev.description_source = "provider_description"
    else:
        ev.notes.append("无业务描述证据（provider 未提供 longBusinessSummary）")

    segments, source, as_of = _revenue_from_composition(
        getattr(data, "revenue_composition", None)
    )
    ev.revenue_segments = segments
    ev.revenue_source = source
    ev.revenue_as_of = as_of
    if not segments:
        note = getattr(getattr(data, "revenue_composition", None), "note", None)
        ev.notes.append(note or "无分部收入证据（未配置分部数据源或解析失败）")

    return ev


__all__ = ["BusinessEvidence", "extract_business_evidence"]
