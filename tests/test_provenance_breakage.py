"""Phase 5: intentional breakage. Each test breaks one rule and proves a guard
catches it.

A test that only asserts "the happy path works" cannot tell a working guard from
an absent one. Every test here first demonstrates that the *broken* state really
is broken (and would otherwise pass silently), then asserts that the guard fires.

Six breakages, per the brief:
1. delete the source record
2. change a derivation without bumping its version
3. promote UNKNOWN_LEGACY to REPORTED
4. relabel ESTIMATED as REPORTED
5. turn REFUSE into ALLOW
6. make IMPUTED a DCF rejection condition
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.algorithm_versions import (
    ALGORITHM_VERSIONS,
    baseline_mismatches,
    fingerprint_table,
    source_fingerprint,
    version_of,
    write_baseline,
)
from data.models import FinancialData, FinancialStatement
from data.normalizer import FinancialNormalizer
from data.provenance import (
    DataAvailability,
    DataOriginType,
    FieldProvenance,
    ProvenanceError,
    assert_no_forbidden_upgrade,
    audit_records,
    compute_input_hash,
    coverage_summary,
    drifted_fields,
    gate_field,
    is_forbidden_upgrade,
    stamp,
)
from data.providers import YahooFinanceProvider


def _provenance(src: str = "REVENUE_X_PRIOR_MARGIN") -> FieldProvenance:
    return FieldProvenance(
        availability=DataAvailability.AVAILABLE,
        origin_type=DataOriginType.IMPUTED,
        derivation_method=src,
        source_provider="yahoo",
        source_fields=["revenue"],
        input_fields=["revenue"],
        input_hash=compute_input_hash({"revenue": 100.0}),
        output_value=20.0,
        generated_at="2026-11-23T00:00:00+00:00",
    )


# ------------------------------------------------- 1. delete the source record

def test_breakage_1_deleting_the_source_record_is_detected():
    """Remove the provenance entry and the audit must show the field as
    unaccounted-for, not as a clean number."""
    stmt = FinancialStatement(period_end="2026-09-30", operating_income=20.0)
    stamp(stmt, "operating_income", DataOriginType.IMPUTED,
          derivation_method="REVENUE_X_PRIOR_MARGIN",
          source_fields=["revenue"], input_values={"revenue": 100.0})

    assert "operating_income" in stmt.field_provenance
    del stmt.field_provenance["operating_income"]

    # The number is untouched; only its record is gone. The gate must treat that
    # as "unknown", never as clean.
    assert stmt.operating_income == 20.0
    decision = gate_field(stmt, "operating_income")
    assert decision.tier.value == DataOriginType.UNKNOWN_LEGACY.value or (
        decision.action.value == "allow_with_flag"
    )
    assert decision.action.value != "allow"
    assert "no provenance" in decision.reason.lower()


def test_breakage_1_deleting_the_source_is_visible_in_coverage():
    """``coverage_summary`` must lose a counted field, proving the record was
    what the audit was reading."""
    stmt = FinancialStatement(period_end="2026-09-30", revenue=100.0,
                              operating_income=20.0)
    stamp(stmt, "operating_income", DataOriginType.IMPUTED,
          derivation_method="REVENUE_X_PRIOR_MARGIN",
          source_fields=["revenue"], input_values={"revenue": 100.0})
    data = FinancialData(ticker="T", ttm=stmt)
    before = coverage_summary(data)["total_fields"]
    del stmt.field_provenance["operating_income"]
    after = coverage_summary(data)["total_fields"]
    assert after == before - 1


# --------------------------------- 2. change the derivation, keep the version

def test_breakage_2_editing_an_algorithm_without_a_version_bump_is_detected(tmp_path, monkeypatch):
    """The fingerprint of the implementing source is recorded; editing that
    source without a version bump must surface as drift.

    The edit is simulated by pinning a stale fingerprint in a temporary
    baseline, which is exactly what a code change without a baseline refresh
    leaves behind.
    """
    import data.algorithm_versions as av

    method = next(iter(ALGORITHM_VERSIONS))
    current = fingerprint_table()

    stale = {m: dict(v) for m, v in current.items()}
    stale[method]["fingerprint"] = "0000000000000000"  # pretend the code moved

    fake_baseline = tmp_path / "baseline.json"
    fake_baseline.write_text(json.dumps(stale))
    monkeypatch.setattr(av, "BASELINE_PATH", fake_baseline)

    drift = av.baseline_mismatches()
    assert method in drift
    assert "without a version bump" in drift[method]


def test_breakage_2_a_real_version_bump_is_also_detected(tmp_path, monkeypatch):
    """Bumping the version constant without refreshing the baseline is a change
    too, and must not be swallowed."""
    import data.algorithm_versions as av

    method = next(iter(ALGORITHM_VERSIONS))
    current = fingerprint_table()
    stale = {m: dict(v) for m, v in current.items()}
    stale[method]["version"] = "999"

    fake = tmp_path / "baseline.json"
    fake.write_text(json.dumps(stale))
    monkeypatch.setattr(av, "BASELINE_PATH", fake)

    drift = av.baseline_mismatches()
    assert method in drift
    assert "version changed" in drift[method]


def test_breakage_2_the_live_baseline_is_current():
    """The committed baseline must match the code, or every drift check above is
    meaningless because it compares against a stale reference."""
    assert baseline_mismatches() == {}, (
        "data/provenance_baseline.json is stale; regenerate with "
        "`python -m data.algorithm_versions --write-baseline` and review the diff"
    )


def test_breakage_2_an_unregistered_method_has_no_version():
    """A derivation wired up but not registered must report no version rather
    than borrow one, so the coverage check fails loudly."""
    assert version_of("SOME_UNREGISTERED_METHOD") is None
    p = FieldProvenance(availability=DataAvailability.AVAILABLE,
                        origin_type=DataOriginType.IMPUTED,
                        derivation_method="SOME_UNREGISTERED_METHOD")
    assert p.algorithm_version is None


# --------------------------- 3. promote UNKNOWN_LEGACY to REPORTED

def test_breakage_3_unknown_legacy_may_not_become_reported():
    assert is_forbidden_upgrade(DataOriginType.UNKNOWN_LEGACY,
                                DataOriginType.REPORTED)
    with pytest.raises(ProvenanceError) as exc:
        assert_no_forbidden_upgrade(DataOriginType.UNKNOWN_LEGACY,
                                    DataOriginType.REPORTED, "operating_income")
    assert "illegal origin upgrade" in str(exc.value)


def test_breakage_3_the_guard_would_catch_the_relabel():
    """Demonstrate the relabel a careless migration would perform, then prove the
    guard refuses it."""
    stmt = FinancialStatement(period_end="2026-09-30", operating_income=20.0)
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=DataAvailability.AVAILABLE,
        origin_type=DataOriginType.UNKNOWN_LEGACY,
        source_provider="cache",
    )
    old = stmt.field_provenance["operating_income"]
    with pytest.raises(ProvenanceError):
        assert_no_forbidden_upgrade(old, DataOriginType.REPORTED, "operating_income")


def test_breakage_3_legacy_backfill_never_produces_reported():
    """The one code path that creates UNKNOWN_LEGACY en masse must not emit
    REPORTED for any field."""
    data = FinancialData(
        ticker="T",
        ttm=FinancialStatement(period_end="2026-09-30", revenue=1.0),
        annual_income=[FinancialStatement(period_end="2025-09-30", revenue=2.0)],
    )
    from data.providers import _backfill_legacy_provenance

    _backfill_legacy_provenance(data)
    origins = {p.origin_type for p in data.ttm.field_provenance.values()}
    assert DataOriginType.REPORTED not in origins
    assert origins == {DataOriginType.UNKNOWN_LEGACY}


# --------------------------------- 4. relabel ESTIMATED as REPORTED

def test_breakage_4_estimated_may_not_become_reported():
    assert is_forbidden_upgrade(DataOriginType.ESTIMATED, DataOriginType.REPORTED)
    with pytest.raises(ProvenanceError):
        assert_no_forbidden_upgrade(DataOriginType.ESTIMATED,
                                    DataOriginType.REPORTED, "interest_expense")


def test_breakage_4_estimated_may_not_become_derived_either():
    """Downgrading the inference class is also a laundromat: an estimate from a
    prior ratio is not deterministic arithmetic on known inputs."""
    assert is_forbidden_upgrade(DataOriginType.ESTIMATED, DataOriginType.DERIVED)


def test_breakage_4_a_genuine_upgrade_is_still_allowed():
    """The guard must not be so broad that a real correction is impossible:
    a fresh, explicitly sourced value may be reported."""
    # ``None`` (no origin yet) -> REPORTED is legitimate: nothing was inferred,
    # a source simply arrived.
    assert not is_forbidden_upgrade(None, DataOriginType.REPORTED)
    # A no-op relabel is not an illegal upgrade.
    assert not is_forbidden_upgrade(DataOriginType.UNKNOWN_LEGACY,
                                    DataOriginType.UNKNOWN_LEGACY)


# -------------------------------------------- 5. turn REFUSE into ALLOW

def test_breakage_5_a_missing_value_is_refused():
    stmt = FinancialStatement(period_end="2026-09-30", operating_income=None)
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=DataAvailability.MISSING,
        origin_type=None,
    )
    d = gate_field(stmt, "operating_income")
    assert d.action.value == "refuse"
    assert d.allowed is False


@pytest.mark.parametrize("availability", [
    DataAvailability.MISSING,
    DataAvailability.NOT_APPLICABLE,
    DataAvailability.INVALID,
])
def test_breakage_5_every_unusable_availability_refuses(availability):
    """Flipping any of these to ALLOW would let a blank or rejected value into a
    valuation. All three must refuse, for both consumers."""
    stmt = FinancialStatement(period_end="2026-09-30")
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=availability, origin_type=DataOriginType.IMPUTED)
    for consumer in ("core_model", "classification"):
        d = gate_field(stmt, "operating_income", consumer=consumer)
        assert d.action.value == "refuse", f"{availability} allowed for {consumer}"


def test_breakage_5_refuse_does_block_dcf_applicability():
    """The other direction: if REFUSE stopped blocking, a DCF could run on a
    blank EBIT. Proven on the real model."""
    from models.dcf import DCFModel

    stmt = FinancialStatement(period_end="2026-09-30", period_type="ttm",
                              revenue=100.0, operating_income=20.0,
                              shares_outstanding=10.0)
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=DataAvailability.INVALID,
        origin_type=DataOriginType.DERIVED)
    data = FinancialData(ticker="T", ttm=stmt)
    data.market.current_price = 10.0
    ok, reasons = DCFModel().applicability_check(data, None)
    assert ok is False
    assert any("unusable" in r for r in reasons)


# ----------------------- 6. make IMPUTED a DCF rejection condition

def test_breakage_6_imputed_alone_must_not_refuse_the_dcf():
    """The regression that was actually introduced and caught in Session #59:
    treating any non-ALLOW decision as a refusal silently killed DCF coverage
    for every legacy ticker."""
    from models.dcf import DCFModel

    stmt = FinancialStatement(period_end="2026-09-30", period_type="ttm",
                              revenue=100.0, operating_income=20.0,
                              shares_outstanding=10.0)
    stmt.field_provenance["operating_income"] = _provenance()
    data = FinancialData(ticker="T", ttm=stmt)
    data.market.current_price = 10.0

    ok, reasons = DCFModel().applicability_check(data, None)
    assert ok is True, f"IMPUTED alone refused the DCF: {reasons}"
    assert not any("operating_income" in r for r in reasons)


@pytest.mark.parametrize("origin", [
    DataOriginType.ESTIMATED,
    DataOriginType.IMPUTED,
    DataOriginType.UNKNOWN_LEGACY,
])
def test_breakage_6_no_inference_class_blocks_the_dcf(origin):
    from models.dcf import DCFModel

    stmt = FinancialStatement(period_end="2026-09-30", period_type="ttm",
                              revenue=100.0, operating_income=20.0,
                              shares_outstanding=10.0)
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=DataAvailability.AVAILABLE, origin_type=origin)
    data = FinancialData(ticker="T", ttm=stmt)
    data.market.current_price = 10.0
    ok, _ = DCFModel().applicability_check(data, None)
    assert ok is True, f"{origin.value} blocked the DCF"


@pytest.mark.parametrize("origin", [
    DataOriginType.ESTIMATED,
    DataOriginType.IMPUTED,
    DataOriginType.UNKNOWN_LEGACY,
])
def test_breakage_6_but_the_caveat_is_still_traceable(origin):
    """Allowed is not the same as invisible: the warning must reach the notes."""
    from models.dcf import DCFModel

    stmt = FinancialStatement(period_end="2026-09-30", period_type="ttm",
                              revenue=100.0, operating_income=20.0)
    stmt.field_provenance["operating_income"] = FieldProvenance(
        availability=DataAvailability.AVAILABLE, origin_type=origin)
    data = FinancialData(ticker="T", ttm=stmt)
    notes = DCFModel().provenance_notes(data)
    assert notes, f"{origin.value} produced no traceable caveat"
    assert "DCF input caveat" in notes[0]


# ------------------------------------------------------ drift detection itself

def test_drift_is_detected_when_a_value_moves_without_a_new_stamp():
    stmt = FinancialStatement(period_end="2026-09-30", operating_income=20.0)
    stamp(stmt, "operating_income", DataOriginType.DERIVED,
          derivation_method="EBIT_FROM_OPERATING_INCOME",
          source_fields=["operating_income"],
          input_values={"operating_income": 20.0})
    assert drifted_fields(stmt) == []

    stmt.operating_income = 25.0   # moved after the fact, record not updated
    drift = drifted_fields(stmt)
    assert len(drift) == 1
    assert drift[0]["field_name"] == "operating_income"
    assert drift[0]["recorded"] == 20.0
    assert drift[0]["current"] == 25.0


def test_partial_quarter_ttm_is_imputed_not_derived():
    """Design §7.2: a skipped missing quarter understates the total. The TTM
    must say IMPUTED, not DERIVED."""
    q = [
        FinancialStatement(period_end=f"2026-0{i}-30", period_type="quarterly",
                           revenue=10.0, operating_income=5.0, net_income=2.0,
                           shares_outstanding=10.0, eps=0.2)
        for i in (1, 2, 3)
    ]
    q.append(FinancialStatement(period_end="2026-04-30",
                                period_type="quarterly", revenue=10.0,
                                operating_income=None, net_income=2.0,
                                shares_outstanding=10.0, eps=0.2))
    ttm = FinancialNormalizer.compute_ttm_from_quarters(q)
    prov = ttm.field_provenance["operating_income"]
    assert prov.origin_type is DataOriginType.IMPUTED
    assert prov.derivation_method == "TTM_SUM_4Q"


def test_complete_quarter_ttm_is_derived():
    q = [
        FinancialStatement(period_end=f"2026-0{i}-30", period_type="quarterly",
                           revenue=10.0, operating_income=5.0, net_income=2.0,
                           shares_outstanding=10.0, eps=0.2)
        for i in (1, 2, 3, 4)
    ]
    ttm = FinancialNormalizer.compute_ttm_from_quarters(q)
    assert ttm.field_provenance["operating_income"].origin_type is (
        DataOriginType.DERIVED)
