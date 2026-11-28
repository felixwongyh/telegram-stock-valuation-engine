"""U-2b: inferred values must say they are inferred, and consumers must gate.

The defect: ``operating_income`` rebuilt as ``revenue x prior margin`` or as
``NI + interest + tax`` landed in the same ``float`` field as a figure the
company filed, and every model treated the two identically.

These tests pin the schema (two axes), the cache round trip (three documented
silent-degradation traps), the writer stamps, and the tiered gating a consumer
uses to decide what an ``IMPUTED`` number may and may not drive.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from data.models import FinancialData, FinancialStatement
from data.provenance import (
    DataAvailability,
    DataOriginType,
    FieldProvenance,
    GateAction,
    ProvenanceTier,
    gate_field,
    stamp,
)
from data.providers import YahooFinanceProvider

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "yahoo_finance"


# ------------------------------------------------------------------ the axes

def test_origin_and_availability_are_independent():
    """MISSING and IMPUTED answer different questions, so they coexist."""
    imputed = FieldProvenance(availability=DataAvailability.AVAILABLE,
                              origin_type=DataOriginType.IMPUTED)
    assert imputed.availability is DataAvailability.AVAILABLE
    assert imputed.origin_type is DataOriginType.IMPUTED

    missing = FieldProvenance(availability=DataAvailability.MISSING)
    assert missing.origin_type is None


def test_not_applicable_has_no_origin():
    """A bank has no operating income, so no origin may be asserted."""
    p = FieldProvenance(availability=DataAvailability.NOT_APPLICABLE)
    assert p.origin_type is None
    assert p.to_dict()["origin_type"] is None


def test_unknown_legacy_ranks_below_reported():
    """Unknown origin must never outrank a filed number."""
    legacy = FieldProvenance(availability=DataAvailability.AVAILABLE,
                             origin_type=DataOriginType.UNKNOWN_LEGACY)
    reported = FieldProvenance(availability=DataAvailability.AVAILABLE,
                               origin_type=DataOriginType.REPORTED)
    assert legacy.tier.value > reported.tier.value


# ------------------------------------------------------- round-trip hazards

def test_str_enum_survives_json_and_is_coerced_back():
    """Design §7.3: a str-Enum comes back as a bare ``str`` after a real JSON
    round trip, and ``.value`` then raises. ``__post_init__`` must coerce."""
    p = FieldProvenance(availability=DataAvailability.AVAILABLE,
                        origin_type=DataOriginType.IMPUTED)
    revived = FieldProvenance(**json.loads(json.dumps(p.to_dict())))
    assert revived.origin_type is DataOriginType.IMPUTED
    assert revived.availability is DataAvailability.AVAILABLE
    assert revived.origin_type.value == "imputed"


def test_provenance_survives_the_real_cache_serializer():
    """Not a re-implementation: the provider's own serializer must keep the
    type, not degrade it to dict/str (design §7.1, §7.3, §7.5)."""
    stmt = FinancialStatement(period_end="2026-09-30", period_type="ttm",
                              operating_income=100.0)
    stamp(stmt, "operating_income", DataOriginType.IMPUTED,
          derivation_method="REVENUE_X_PRIOR_MARGIN", input_fields=["revenue"])
    data = FinancialData(ticker="TEST", ttm=stmt, annual_income=[stmt])

    blob = YahooFinanceProvider._serialize_data_to_jsonable(data)
    back = YahooFinanceProvider._data_from_jsonable(json.loads(json.dumps(blob)))

    assert back is not None
    prov = back.ttm.field_provenance["operating_income"]
    assert isinstance(prov, FieldProvenance), (
        f"provenance degraded to {type(prov).__name__}; "
        "FieldProvenance must be in _dataclass_registry"
    )
    assert prov.origin_type is DataOriginType.IMPUTED
    assert prov.derivation_method == "REVENUE_X_PRIOR_MARGIN"
    assert prov.input_fields == ["revenue"]


def test_field_provenance_is_a_declared_field():
    """A dynamic attribute would be dropped by the serializer (§7.5)."""
    import dataclasses
    names = {f.name for f in dataclasses.fields(FinancialStatement)}
    assert "field_provenance" in names


# ------------------------------------------------------------------- gating

def _stmt_with(origin, availability=DataAvailability.AVAILABLE):
    stmt = FinancialStatement(period_end="2026-09-30", operating_income=1.0)
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=availability, origin_type=origin)
    return stmt


def test_reported_passes_a_core_model_cleanly():
    d = gate_field(_stmt_with(DataOriginType.REPORTED), "operating_income")
    assert d.action is GateAction.ALLOW
    assert d.allowed is True


def test_imputed_is_flagged_for_a_core_model_not_silently_trusted():
    d = gate_field(_stmt_with(DataOriginType.IMPUTED), "operating_income")
    assert d.action is GateAction.ALLOW_WITH_FLAG
    assert "imputed" in d.reason.lower()
    assert d.tier is ProvenanceTier.IMPUTED


def test_imputed_is_downweighted_for_classification():
    """A feature built on imputed data must not carry reported-level confidence
    (the Session #57 drift)."""
    d = gate_field(_stmt_with(DataOriginType.IMPUTED), "operating_income",
                   consumer="classification")
    assert d.action is GateAction.DOWNWEIGHT


def test_no_value_is_refused_regardless_of_origin():
    for avail in (DataAvailability.MISSING, DataAvailability.NOT_APPLICABLE,
                  DataAvailability.INVALID):
        d = gate_field(_stmt_with(DataOriginType.IMPUTED, avail),
                       "operating_income")
        assert d.action is GateAction.REFUSE
        assert d.allowed is False


def test_absent_provenance_is_treated_as_legacy_not_reported():
    stmt = FinancialStatement(period_end="2026-09-30", operating_income=1.0)
    d = gate_field(stmt, "operating_income")
    assert d.tier is ProvenanceTier.UNKNOWN_LEGACY
    assert d.action is GateAction.ALLOW_WITH_FLAG, (
        "unrecorded provenance must not be treated as clean"
    )


# ------------------------------------------------------------ writer stamps

def _load(ticker: str, monkeypatch):
    monkeypatch.setenv("UVE_SNAPSHOT_ID", "20261123")
    monkeypatch.setenv("UVE_FREEZE_CACHE", "1")
    if not (CACHE_DIR / f"{ticker}_20261123.json").exists():
        pytest.skip(f"no frozen snapshot for {ticker}")
    return asyncio.run(YahooFinanceProvider().get_financial_data(ticker))


def test_legacy_snapshot_fields_are_unknown_not_reported(monkeypatch):
    """The frozen snapshots predate this schema, so their numbers have no
    recorded origin. The honest label is ``UNKNOWN_LEGACY`` — asserting
    ``REPORTED`` here would launder unknown data into "the company said so"."""
    data = _load("MSFT", monkeypatch)
    prov = data.ttm.field_provenance
    assert prov, "legacy snapshot was not backfilled"
    for name in ("revenue", "net_income"):
        if getattr(data.ttm, name) is not None:
            assert prov[name].origin_type is DataOriginType.UNKNOWN_LEGACY
            assert prov[name].availability is DataAvailability.AVAILABLE


def test_bank_suppression_is_not_applicable_not_imputed(monkeypatch):
    """Design acceptance: a bank's operating_income is NOT_APPLICABLE, never
    IMPUTED, and its ebitda is not a DERIVED orphan."""
    data = _load("JPM", monkeypatch)
    prov = data.ttm.field_provenance
    assert prov["operating_income"].availability is DataAvailability.NOT_APPLICABLE
    assert prov["operating_income"].origin_type is None
    assert prov["ebit"].availability is DataAvailability.NOT_APPLICABLE
    assert prov["ebitda"].availability is DataAvailability.INVALID
    assert prov["ebitda"].origin_type is None


def test_bank_fields_are_refused_by_a_core_model(monkeypatch):
    """A model asking whether it may use a bank's EBIT must be told no."""
    data = _load("JPM", monkeypatch)
    for name in ("operating_income", "ebit", "ebitda"):
        d = gate_field(data.ttm, name)
        assert d.action is GateAction.REFUSE, f"{name} was not refused"


def test_writer_stamps_imputed_with_method_and_inputs():
    """The stamping helper must record IMPUTED plus *why* and *from what*.

    Tested directly rather than through a snapshot: the frozen 20261123 set was
    captured before this schema existed, so it exercises the legacy backfill, not
    the build-time writer. Asserting on a real ticker here would pass or skip
    depending on whether that ticker happened to need inference.
    """
    from data.providers import _stamp_statement_provenance

    stmt = FinancialStatement(
        period_end="2026-09-30", period_type="quarterly",
        revenue=100.0, ebit=20.0, operating_income=20.0,
        depreciation_amortization=5.0, ebitda=25.0,
    )
    _stamp_statement_provenance(
        stmt, "REVENUE_X_PRIOR_MARGIN", ["revenue"],
        "REVENUE_X_PRIOR_DA_RATIO", "USD",
    )

    for name in ("ebit", "operating_income"):
        p = stmt.field_provenance[name]
        assert p.origin_type is DataOriginType.IMPUTED
        assert p.derivation_method == "REVENUE_X_PRIOR_MARGIN"
        assert p.input_fields == ["revenue"]

    da = stmt.field_provenance["depreciation_amortization"]
    assert da.origin_type is DataOriginType.IMPUTED
    assert da.derivation_method == "REVENUE_X_PRIOR_DA_RATIO"

    assert stmt.field_provenance["ebitda"].origin_type is DataOriginType.IMPUTED
    assert stmt.field_provenance["revenue"].origin_type is DataOriginType.REPORTED


def test_writer_stamps_reported_when_no_inference_fired():
    from data.providers import _stamp_statement_provenance

    stmt = FinancialStatement(period_end="2026-09-30", ebit=20.0,
                              operating_income=20.0, revenue=100.0)
    _stamp_statement_provenance(stmt, None, [], None, "USD")
    assert stmt.field_provenance["operating_income"].origin_type is (
        DataOriginType.REPORTED)
    assert stmt.field_provenance["ebit"].origin_type is DataOriginType.REPORTED
    # Nothing inferred, so nothing may claim a derivation.
    assert stmt.field_provenance["ebit"].derivation_method is None


# ------------------------------------------------- tiered gating in a model

def test_imputed_ebit_does_not_refuse_the_dcf():
    """The ruling was tiered gating, not a ban. An inferred EBIT must not make
    the model unrunnable, or every legacy snapshot silently loses its DCF."""
    from models.dcf import DCFModel

    stmt = FinancialStatement(
        period_end="2026-09-30", period_type="ttm",
        revenue=100.0, operating_income=20.0, shares_outstanding=10.0,
    )
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=DataAvailability.AVAILABLE,
        origin_type=DataOriginType.IMPUTED,
        derivation_method="REVENUE_X_PRIOR_MARGIN",
        input_fields=["revenue"],
    )
    data = FinancialData(ticker="TEST", ttm=stmt)
    data.market.current_price = 10.0

    ok, reasons = DCFModel().applicability_check(data, None)
    assert ok is True, f"IMPUTED EBIT wrongly refused the DCF: {reasons}"
    assert not any("operating_income" in r for r in reasons)


def test_imputed_ebit_is_flagged_in_the_dcf_notes():
    """...but it must be visible, not silent. That is the 'flags it' half of
    the acceptance criterion."""
    from models.dcf import DCFModel

    stmt = FinancialStatement(
        period_end="2026-09-30", period_type="ttm",
        revenue=100.0, operating_income=20.0, shares_outstanding=10.0,
    )
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=DataAvailability.AVAILABLE,
        origin_type=DataOriginType.IMPUTED,
        derivation_method="REVENUE_X_PRIOR_MARGIN",
        input_fields=["revenue"],
    )
    data = FinancialData(ticker="TEST", ttm=stmt)

    notes = DCFModel().provenance_notes(data)
    assert notes and "imputed" in notes[0].lower()


def test_reported_ebit_produces_no_caveat():
    """A fully reported input set produces no caveats.

    Every audited input is stamped REPORTED here, not just ``operating_income``:
    ``provenance_notes`` now covers all eleven DCF inputs, so an unstamped
    ``revenue`` would (correctly) raise its own caveat.
    """
    from models.dcf import DCFModel

    stmt = FinancialStatement(period_end="2026-09-30", period_type="ttm",
                              revenue=100.0, operating_income=20.0)
    for name in DCFModel._AUDITED_INPUTS:
        if getattr(stmt, name, None) is None:
            continue
        stmt.field_provenance[name] = FieldProvenance(
            availability=DataAvailability.AVAILABLE,
            origin_type=DataOriginType.REPORTED,
            source_field=name, source_fields=[name])
    data = FinancialData(ticker="TEST", ttm=stmt)
    assert DCFModel().provenance_notes(data) == []


def test_unusable_ebit_does_refuse_the_dcf():
    """Tiers must differ in consequence, or the gate is decoration."""
    from models.dcf import DCFModel

    stmt = FinancialStatement(period_end="2026-09-30", period_type="ttm",
                              revenue=100.0, operating_income=20.0,
                              shares_outstanding=10.0)
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=DataAvailability.INVALID,
        origin_type=DataOriginType.DERIVED)
    data = FinancialData(ticker="TEST", ttm=stmt)
    data.market.current_price = 10.0

    ok, reasons = DCFModel().applicability_check(data, None)
    assert ok is False
    assert any("unusable" in r for r in reasons)
