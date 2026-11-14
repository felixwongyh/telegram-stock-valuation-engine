"""Business intelligence layer lock: business description + revenue segments.

Pins the evidence collector's contract — it carries provenance and reports
absent evidence *as absent* (never invents a description or a segment mix).
"""
from __future__ import annotations

from classification.business_intelligence import BusinessEvidence, extract_business_evidence
from classification.taxonomy import RevenueComposition, SegmentRevenue


class _NS:
    """Minimal duck-typed stand-in for the dataclasses under test."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_description_from_market():
    data = _NS(market=_NS(description="Makes chips", business_summary=None), revenue_composition=None)
    ev = extract_business_evidence(data)
    assert isinstance(ev, BusinessEvidence)
    assert ev.has_description and ev.description == "Makes chips"
    assert ev.description_source == "provider_description"
    assert not ev.has_segments


def test_description_override():
    data = _NS(market=_NS(description="provider text"), revenue_composition=None)
    ev = extract_business_evidence(data, description="override")
    assert ev.description == "override"


def test_segments_from_composition():
    comp = RevenueComposition(
        available=True,
        source="fmp",
        as_of="2024-09-30",
        segments=[
            SegmentRevenue(label="iPhone", pct=0.5),
            SegmentRevenue(label="Services", pct=0.5),
        ],
    )
    data = _NS(market=_NS(description=None), revenue_composition=comp)
    ev = extract_business_evidence(data)
    assert [s[0] for s in ev.revenue_segments] == ["iPhone", "Services"]
    assert ev.revenue_source == "fmp"
    assert ev.revenue_as_of == "2024-09-30"
    assert ev.has_segments


def test_no_evidence_is_explicit():
    data = _NS(market=_NS(description="   "), revenue_composition=None)
    ev = extract_business_evidence(data)
    assert not ev.has_description and not ev.has_segments
    assert ev.provenance() == {"description": "unknown", "revenue_segments": "unknown"}
    assert ev.notes
