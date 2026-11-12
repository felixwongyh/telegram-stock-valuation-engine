"""Caliber contract lock: archetype metric semantics + peer-multiple consumption.

Extends ADR-022/024. Previously `valuation/caliber.py` only covered
financial / reit / standard, and `models/multiples.py` re-derived the caliber
inline (``if profile.is_financial_institution: ...``) — the same class of
"two sites disagree" bug that produced the SOFI round-2 contradiction.

This test pins:
  * the two NEW archetypes (energy asset-revaluation, unit-econ build-out) and
    which metrics they declare NOT_MEANINGFUL / REFERENCE_ONLY;
  * that the peer-multiple layer *consumes* the contract:
      - NOT_MEANINGFUL  → applicability_check rejects the model;
      - REFERENCE_ONLY  → the model still values, but status is APPROXIMATE.
"""
from __future__ import annotations

from types import SimpleNamespace

from data import SyntheticDataProvider
from classification.classifier import BusinessClassifier
from models.multiples import EVSalesModel, MultiplesModel
from valuation.caliber import (
    DiscountCaliber,
    MetricMeaning,
    build_caliber_contract,
)


def _profile(**kw):
    base = dict(
        is_financial_institution=False, is_reit=False, business_type="MatureTech",
        applicable_models=[], business_exposures=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Contract tables
# ---------------------------------------------------------------------------

def test_energy_archetype_declares_sales_reference_only():
    c = build_caliber_contract(_profile(business_type="Energy"))
    assert c.archetype == "energy"
    assert c.discount is DiscountCaliber.WACC
    assert c.meaning("EV_Sales") is MetricMeaning.REFERENCE_ONLY
    # EBITDA remains the anchor for a commodity producer.
    assert c.meaning("EV_EBITDA") is MetricMeaning.MEANINGFUL


def test_unit_econ_archetype_declares_earnings_not_meaningful():
    c = build_caliber_contract(_profile(applicable_models=["EV/Sales (Unit Econ)"]))
    assert c.archetype == "unit_econ"
    assert c.meaning("P/E") is MetricMeaning.NOT_MEANINGFUL
    assert c.meaning("FCF_Yield") is MetricMeaning.NOT_MEANINGFUL
    assert c.meaning("EV_EBITDA") is MetricMeaning.REFERENCE_ONLY
    assert c.meaning("P/B") is MetricMeaning.REFERENCE_ONLY
    assert c.meaning("EV_Sales") is MetricMeaning.MEANINGFUL


def test_replacement_nav_also_routes_to_unit_econ_archetype():
    c = build_caliber_contract(_profile(applicable_models=["Replacement NAV"]))
    assert c.archetype == "unit_econ"


def test_financial_and_reit_archetypes_unchanged():
    fin = build_caliber_contract(_profile(is_financial_institution=True))
    assert fin.archetype == "financial"
    assert fin.discount is DiscountCaliber.COST_OF_EQUITY
    assert fin.sensitivity_applicable is False

    reit = build_caliber_contract(_profile(is_reit=True, business_type="REIT"))
    assert reit.archetype == "reit"
    assert reit.meaning("FCF") is MetricMeaning.REFERENCE_ONLY


def test_financial_precedence_over_energy_business_type():
    # A bank-like entity mislabelled Energy must stay on the cost-of-equity caliber.
    c = build_caliber_contract(_profile(is_financial_institution=True, business_type="Energy"))
    assert c.archetype == "financial"


# ---------------------------------------------------------------------------
# Peer-multiple layer consumes the contract
# ---------------------------------------------------------------------------

def _live(name: str):
    data = SyntheticDataProvider().get_financial_data(name)
    profile = BusinessClassifier().classify(data)
    return data, profile


def test_energy_ev_sales_is_reference_only_not_rejected():
    """Energy EV/Sales must still value (directional), never be gated out."""
    data, profile = _live("XOM")
    profile = _profile(business_type="Energy")
    ok, reasons = EVSalesModel().applicability_check(data, profile)
    assert ok, reasons


def test_ev_ebitda_gated_for_financial_by_contract_not_inline():
    """The bank EV/EBITDA rejection now comes from the contract, not an inline if."""
    data, _ = _live("JPM")
    profile = _profile(is_financial_institution=True, business_type="Bank")
    model = MultiplesModel("EV/EBITDA")
    ok, reasons = model.applicability_check(data, profile)
    assert not ok
    assert any("archetype 'financial'" in r for r in reasons)
