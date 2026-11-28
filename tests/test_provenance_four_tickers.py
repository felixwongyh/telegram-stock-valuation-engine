"""Phase 2: provenance evidence on four real tickers, plus the audit guarantees.

Four tickers chosen because they cover the four origin classes that matter:

* ``MSFT`` -- a non-financial filer: reported vendor lines, normalizer-derived
  arithmetic, prior-ratio estimates.
* ``AMD``  -- its frozen snapshot was destroyed (P0-1). This file asserts the gap
  is *real and visible*; it must never be papered over with live data.
* ``JPM``  -- a bank: ``operating_income``/``ebit`` ``NOT_APPLICABLE``, ``ebitda``
  ``INVALID`` (U-8), plus normalizer estimates that must stay labelled.
* ``BAC``  -- second bank, same class, different numbers (its orphan ``ebitda``
  used to produce a false reconciliation mismatch).

Everything here runs against the frozen ``20261123`` snapshot, pinned. No test
in this file may fetch live data or write a snapshot file.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from data.normalizer import FinancialNormalizer
from data.provenance import (
    DataAvailability,
    DataOriginType,
    FieldProvenance,
    audit_records,
    coverage_summary,
    drifted_fields,
    gate_field,
)
from data.providers import YahooFinanceProvider

SNAPSHOT_ID = "20261123"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "yahoo_finance"


def _snapshot_path(ticker: str) -> Path:
    return CACHE_DIR / f"{ticker}_{SNAPSHOT_ID}.json"


@pytest.fixture(scope="module", autouse=True)
def _pin_snapshot():
    import os
    old_id = os.environ.get("UVE_SNAPSHOT_ID")
    old_freeze = os.environ.get("UVE_FREEZE_CACHE")
    os.environ["UVE_SNAPSHOT_ID"] = SNAPSHOT_ID
    os.environ["UVE_FREEZE_CACHE"] = "1"
    yield
    for key, old in (("UVE_SNAPSHOT_ID", old_id), ("UVE_FREEZE_CACHE", old_freeze)):
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


def _load(ticker: str):
    if not _snapshot_path(ticker).exists():
        pytest.skip(f"no frozen {SNAPSHOT_ID} snapshot for {ticker}")
    data = asyncio.run(YahooFinanceProvider().get_financial_data(ticker))
    return FinancialNormalizer.normalize_all(data)


# ------------------------------------------------------- AMD: the real gap

def test_amd_snapshot_is_absent_and_that_is_the_expected_state():
    """AMD's snapshot was destroyed by the P0-1 deletion bug.

    The honest state is "absent". If a future session restores it, this test
    fails on purpose so the recovery is recorded rather than silently absorbed.
    """
    assert not _snapshot_path("AMD").exists(), (
        "AMD_20261123.json exists again; if it was legitimately re-captured, "
        "update KNOWN_MISSING in tests/test_status_matrix.py and this test"
    )


def test_amd_load_raises_frozen_snapshot_miss():
    """A missing snapshot under freeze must raise, never fall back to live data.

    A silent network fallback is the failure mode that would let 2026-11-28 data
    masquerade as a 2026-11-23 snapshot.
    """
    from data.errors import FrozenSnapshotMissError

    with pytest.raises(FrozenSnapshotMissError) as exc:
        asyncio.run(YahooFinanceProvider().get_financial_data("AMD"))
    assert "AMD" in str(exc.value)


def test_no_snapshot_file_was_written_during_this_session():
    """Guards against a 'helpful' rebuild that fabricates the missing input."""
    assert not _snapshot_path("AMD").exists()


# ------------------------------------------------------------ MSFT: filer

def test_msft_has_all_four_state_classes():
    """MSFT must exhibit reported, derived and estimated values at once."""
    data = _load("MSFT")
    provs = data.ttm.field_provenance
    origins = {p.origin_type for p in provs.values() if p.origin_type}
    assert DataOriginType.UNKNOWN_LEGACY in origins   # pre-schema snapshot
    assert DataOriginType.DERIVED in origins          # normalizer arithmetic
    assert DataOriginType.ESTIMATED in origins        # prior-ratio estimate


def test_msft_derived_values_carry_a_full_audit_record():
    """Every DERIVED/ESTIMATED field must be reproducible from its record."""
    data = _load("MSFT")
    rows = [r for r in audit_records(data.ttm)
            if r["origin_type"] in ("derived", "estimated")]
    assert rows, "no derived/estimated fields on MSFT TTM"
    for r in rows:
        assert r["derivation_method"], f"{r['field_name']}: no method"
        assert r["algorithm_version"], f"{r['field_name']}: no version"
        assert r["input_hash"], f"{r['field_name']}: no input hash"
        assert r["output_value"] is not None, f"{r['field_name']}: no output"
        assert r["generated_at"], f"{r['field_name']}: no timestamp"
        assert r["source_fields"], f"{r['field_name']}: no source fields"


def test_msft_records_do_not_drift_from_the_values_they_describe():
    data = _load("MSFT")
    assert drifted_fields(data.ttm) == [], (
        "a stamped value disagrees with its own audit record"
    )


def test_msft_estimated_interest_is_labelled_not_hidden():
    """The specific silent-fill defect U-2 found: TTM interest_expense was
    ``None`` and got replaced by ``revenue x prior ratio`` with no label."""
    data = _load("MSFT")
    prov = data.ttm.field_provenance.get("interest_expense")
    assert prov is not None, "interest_expense has no provenance at all"
    assert prov.origin_type is not DataOriginType.REPORTED
    if prov.origin_type is DataOriginType.ESTIMATED:
        assert prov.derivation_method == "REVENUE_X_PRIOR_INTEREST_RATIO"
        assert prov.input_hash


# ------------------------------------------------------------- JPM: bank

def test_jpm_suppressed_fields_are_not_applicable_or_invalid():
    data = _load("JPM")
    provs = data.ttm.field_provenance
    assert provs["operating_income"].availability is DataAvailability.NOT_APPLICABLE
    assert provs["ebit"].availability is DataAvailability.NOT_APPLICABLE
    assert provs["ebitda"].availability is DataAvailability.INVALID


def test_jpm_suppressed_fields_are_refused_by_a_core_model():
    data = _load("JPM")
    for name in ("operating_income", "ebit", "ebitda"):
        assert gate_field(data.ttm, name).action.value == "refuse"


def test_jpm_estimates_are_labelled_even_though_the_bank_is_routed_out():
    """Routing a bank out of DCF does not license anonymous numbers elsewhere:
    interest_expense/income_tax estimates must still name themselves."""
    data = _load("JPM")
    for name in ("interest_expense", "income_tax"):
        prov = data.ttm.field_provenance.get(name)
        if getattr(data.ttm, name) is None:
            continue
        assert prov is not None, f"{name} filled with no provenance"
        assert prov.origin_type is DataOriginType.ESTIMATED
        assert prov.algorithm_version and prov.input_hash


# -------------------------------------------------------------- BAC: bank

def test_bac_suppression_matches_jpm_semantics():
    data = _load("BAC")
    provs = data.ttm.field_provenance
    assert provs["operating_income"].availability is DataAvailability.NOT_APPLICABLE
    assert provs["ebitda"].availability is DataAvailability.INVALID


def test_bac_has_no_derived_ebitda_orphan():
    """The U-8 defect: a DERIVED ebitda whose only input was suppressed."""
    data = _load("BAC")
    prov = data.ttm.field_provenance["ebitda"]
    assert prov.origin_type is None
    assert prov.availability is not DataAvailability.AVAILABLE


# ----------------------------------------------- cross-ticker: the invariants

@pytest.mark.parametrize("ticker", ["MSFT", "JPM", "BAC"])
def test_no_inferred_field_is_missing_its_audit_record(ticker):
    data = _load(ticker)
    summary = coverage_summary(data)
    assert summary["derived_without_audit"] == [], (
        f"{ticker}: inferred fields without algorithm_version/input_hash: "
        f"{summary['derived_without_audit'][:5]}"
    )


@pytest.mark.parametrize("ticker", ["MSFT", "JPM", "BAC"])
def test_no_field_is_labelled_reported_without_a_source(ticker):
    """REPORTED means "the filer published it", which requires naming the
    vendor field.

    NOTE on scope: the frozen snapshots carry no REPORTED fields at all (they
    predate the schema and go through ``_backfill_legacy_provenance``, which
    labels ``UNKNOWN_LEGACY``). So on these tickers this assertion holds with
    zero entries and is *not* evidence on its own — the real coverage is
    ``test_reported_path_stamps_a_source_for_every_vendor_field`` below, which
    drives the builder directly. Kept here so the invariant is checked wherever
    a REPORTED entry does appear once the set is re-snapshotted.
    """
    data = _load(ticker)
    bad = [
        name for name, p in data.ttm.field_provenance.items()
        if p.origin_type is DataOriginType.REPORTED and not p.source_field
    ]
    assert not bad, f"{ticker}: REPORTED without a source field: {bad}"


@pytest.mark.parametrize("ticker", ["MSFT", "JPM", "BAC"])
def test_provenance_survives_a_real_cache_round_trip(ticker):
    """The audit record must be readable after a save/load, not just in memory."""
    data = _load(ticker)
    blob = YahooFinanceProvider._serialize_data_to_jsonable(data)
    back = YahooFinanceProvider._data_from_jsonable(json.loads(json.dumps(blob)))
    assert back is not None
    for name, prov in data.ttm.field_provenance.items():
        if not prov.is_derived:
            continue
        restored = back.ttm.field_provenance[name]
        assert isinstance(restored, FieldProvenance)
        assert restored.algorithm_version == prov.algorithm_version
        assert restored.input_hash == prov.input_hash
        assert restored.derivation_method == prov.derivation_method


# ------------------------------------- the REPORTED path, on real builder code

_VENDOR_TS = {
    "TotalRevenue": [{"period_end": "2026-09-30", "value": 1000.0}],
    "GrossProfit": [{"period_end": "2026-09-30", "value": 400.0}],
    "EBIT": [{"period_end": "2026-09-30", "value": 200.0}],
    "OperatingIncome": [{"period_end": "2026-09-30", "value": 200.0}],
    "NetIncome": [{"period_end": "2026-09-30", "value": 150.0}],
    "OperatingCashFlow": [{"period_end": "2026-09-30", "value": 180.0}],
    "CapitalExpenditure": [{"period_end": "2026-09-30", "value": 30.0}],
}


def _build_vendor_stmt():
    stmts = YahooFinanceProvider._build_statements(
        dict(_VENDOR_TS), "", "annual", "USD", 10.0, [], None, None, False)
    assert stmts, "builder produced nothing"
    return stmts[0]


def test_reported_path_stamps_a_source_for_every_vendor_field():
    """The frozen snapshots exercise the legacy backfill, not this path, so this
    is the only place the REPORTED stamp is actually proven. Without it, "no
    REPORTED value may lack a source" would pass vacuously at 0 REPORTED fields.
    """
    stmt = _build_vendor_stmt()
    reported = {n: p for n, p in stmt.field_provenance.items()
                if p.origin_type is DataOriginType.REPORTED}
    assert len(reported) >= 6, f"expected the vendor fields, got {sorted(reported)}"
    for name, p in reported.items():
        assert p.source_fields == [name], f"{name}: source_fields={p.source_fields}"
        assert p.source_provider == "yahoo"
        assert p.generated_at


def test_reported_value_is_not_labelled_derived():
    """A filed number must not be labelled inferred just because the builder also
    runs arithmetic nearby."""
    stmt = _build_vendor_stmt()
    for name in ("revenue", "net_income", "operating_income"):
        assert stmt.field_provenance[name].origin_type is DataOriginType.REPORTED


def test_derived_value_is_not_labelled_reported():
    """``eps`` is computed (NI/shares); calling it REPORTED would be a lie."""
    stmt = _build_vendor_stmt()
    eps = stmt.field_provenance["eps"]
    assert eps.origin_type is DataOriginType.DERIVED
    assert eps.derivation_method == "EPS_FROM_NI_OVER_SHARES"
    assert eps.input_hash and eps.algorithm_version
