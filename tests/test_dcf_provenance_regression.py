"""Phase 3: DCF regression protection.

Four properties must hold together. Any one alone is trivially satisfiable, so
each is asserted separately and then again in combination:

1. the 50-ticker Solved count does not fall without a stated reason;
2. only ``REFUSE`` affects DCF applicability;
3. ``ESTIMATED`` / ``IMPUTED`` / ``UNKNOWN_LEGACY`` never cause a rejection by
   merely existing;
4. a missing key input *does* reject;
5. every provenance warning is traceable in ``provenance_notes()``.
"""

from __future__ import annotations

import logging

import pytest

from data.models import FinancialData, FinancialStatement
from data.provenance import (
    DataAvailability,
    DataOriginType,
    FieldProvenance,
    GateAction,
    gate_field,
)
from models.dcf import DCFModel

logging.disable(logging.CRITICAL)


def _dcf_ready_stmt(**overrides) -> FinancialStatement:
    """A statement that can pass ``applicability_check`` with a clean origin."""
    kw = dict(period_end="2026-09-30", period_type="ttm", revenue=1000.0,
              operating_income=200.0, shares_outstanding=100.0,
              free_cash_flow=120.0, operating_cash_flow=150.0, capex=-30.0,
              depreciation_amortization=50.0, net_income=150.0, ebitda=250.0,
              ebit=200.0, change_in_nwc=10.0)
    kw.update(overrides)
    return FinancialStatement(**kw)


def _stamp_all(stmt, origin, availability=DataAvailability.AVAILABLE):
    for name in DCFModel._AUDITED_INPUTS:
        if getattr(stmt, name, None) is None:
            continue
        stmt.field_provenance[name] = FieldProvenance(
            availability=availability, origin_type=origin,
            source_field=name, source_fields=[name])


def _data(stmt) -> FinancialData:
    data = FinancialData(ticker="TEST", ttm=stmt)
    data.market.current_price = 10.0
    return data


# ------------------------------------------------- 1. no unexplained loss

def test_solved_count_is_locked_by_the_status_matrix():
    """The count is asserted in ``test_status_matrix``; this only records that
    the guard exists so a future reader does not think it is unowned."""
    from tests.test_status_matrix import EXPECTED

    assert EXPECTED["Solved"] == 31, (
        "the Solved baseline moved; if this is intentional, justify it per "
        "ticker and update GOLDEN_READINESS_REPORT.md first"
    )


# --------------------------- 2. only REFUSE affects applicability

def test_only_refuse_changes_applicability():
    """Walk every availability and assert the applicability verdict flips *only*
    at REFUSE-causing states."""
    for availability, should_reject in [
        (DataAvailability.AVAILABLE, False),
        (DataAvailability.MISSING, True),
        (DataAvailability.NOT_APPLICABLE, True),
        (DataAvailability.INVALID, True),
    ]:
        stmt = _dcf_ready_stmt()
        _stamp_all(stmt, DataOriginType.DERIVED)
        stmt.field_provenance["operating_income"] = FieldProvenance(
            availability=availability, origin_type=DataOriginType.DERIVED)
        ok, reasons = DCFModel().applicability_check(_data(stmt), None)
        assert ok is (not should_reject), (
            f"{availability.value}: applicable={ok}, reasons={reasons}")


# ------------- 3. inference classes never reject merely by existing

@pytest.mark.parametrize("origin", [
    DataOriginType.ESTIMATED,
    DataOriginType.IMPUTED,
    DataOriginType.UNKNOWN_LEGACY,
])
def test_inference_class_alone_does_not_reject(origin):
    stmt = _dcf_ready_stmt()
    _stamp_all(stmt, origin)
    ok, reasons = DCFModel().applicability_check(_data(stmt), None)
    assert ok is True, f"{origin.value} caused rejection: {reasons}"


@pytest.mark.parametrize("origin", [
    DataOriginType.ESTIMATED,
    DataOriginType.IMPUTED,
    DataOriginType.UNKNOWN_LEGACY,
])
def test_inference_class_gate_action_is_never_refuse(origin):
    stmt = _dcf_ready_stmt()
    _stamp_all(stmt, origin)
    for name in DCFModel._AUDITED_INPUTS:
        if getattr(stmt, name, None) is None:
            continue
        decision = gate_field(stmt, name, consumer="core_model")
        assert decision.action is not GateAction.REFUSE, (
            f"{origin.value} {name}: gate refused an available value")


# ------------------------------------- 4. missing key input does reject

@pytest.mark.parametrize("field", ["revenue", "operating_income"])
def test_missing_key_input_rejects_the_dcf(field):
    stmt = _dcf_ready_stmt(**{field: None})
    _stamp_all(stmt, DataOriginType.DERIVED)
    ok, reasons = DCFModel().applicability_check(_data(stmt), None)
    assert ok is False
    assert reasons


def test_unusable_but_present_value_rejects_the_dcf():
    """A number that exists but is INVALID must be refused — presence is not
    usability."""
    stmt = _dcf_ready_stmt()
    _stamp_all(stmt, DataOriginType.DERIVED)
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=DataAvailability.INVALID,
        origin_type=DataOriginType.DERIVED)
    ok, reasons = DCFModel().applicability_check(_data(stmt), None)
    assert ok is False
    assert any("unusable" in r for r in reasons)


# ------------------------------------------- 5. warnings are traceable

def test_every_inferred_input_produces_a_named_caveat():
    """The caveat set must cover every inferred input actually used, so a reader
    can see what the valuation leaned on."""
    stmt = _dcf_ready_stmt()
    _stamp_all(stmt, DataOriginType.IMPUTED)
    notes = DCFModel().provenance_notes(_data(stmt))
    used = [n for n in DCFModel._AUDITED_INPUTS
            if getattr(stmt, n, None) is not None]
    assert len(notes) == len(used), (
        f"expected one caveat per used input ({len(used)}), got {len(notes)}")
    for name in used:
        assert any(name in n for n in notes), f"{name} has no caveat"


def test_reported_inputs_produce_no_caveat():
    stmt = _dcf_ready_stmt()
    _stamp_all(stmt, DataOriginType.REPORTED)
    assert DCFModel().provenance_notes(_data(stmt)) == []


def test_caveats_do_not_change_the_verdict():
    """Traceable and non-blocking at the same time: the whole point of tiering."""
    stmt = _dcf_ready_stmt()
    _stamp_all(stmt, DataOriginType.UNKNOWN_LEGACY)
    data = _data(stmt)
    assert DCFModel().applicability_check(data, None)[0] is True
    assert DCFModel().provenance_notes(data)


def test_mixed_origins_report_only_the_inferred_ones():
    stmt = _dcf_ready_stmt()
    _stamp_all(stmt, DataOriginType.REPORTED)
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=DataAvailability.AVAILABLE,
        origin_type=DataOriginType.IMPUTED)
    notes = DCFModel().provenance_notes(_data(stmt))
    assert len(notes) == 1
    assert "operating_income" in notes[0]
