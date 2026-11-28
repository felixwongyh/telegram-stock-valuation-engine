"""Shadow snapshot: evidence, unit handling and fiscal-period matching.

These tests use **stored artefacts**, not the network. They pin the four defects
found while building the snapshots, each of which produced a wrong *label* rather
than an exception — the failure mode that matters here, because a wrong label
propagates into a provenance report as fact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.provenance import (
    DataOriginType,
    FieldProvenance,
    ProvenanceError,
    assert_no_forbidden_upgrade,
    is_forbidden_upgrade,
)
from data.shadow_snapshot import (
    CONCEPT_UNITS,
    SEC_CONCEPT_MAP,
    SIGN_FLIP,
    RawArtifact,
    annual_facts_from_concept,
    sha256_bytes,
    verify_shadow,
)


def _artifact(body: dict, name: str = "sec_test") -> RawArtifact:
    raw = json.dumps(body).encode()
    return RawArtifact(
        name=name, url="test://x", http_status=200, fetched_at="2026-11-28T00:00:00Z",
        sha256=sha256_bytes(raw), byte_length=len(raw), vendor="sec_edgar", body=raw,
    )


def _concept(facts, unit="USD") -> RawArtifact:
    return _artifact({"units": {unit: facts}})


def _fact(end, val, form="10-K", filed="2026-01-30", accn="0000-26-000001"):
    return {"end": end, "val": val, "form": form, "filed": filed,
            "accn": accn, "fy": 2026, "fp": "FY"}


# --------------------------------------------------------- evidence integrity

def test_digest_changes_when_a_byte_changes():
    a = _artifact({"x": 1})
    b = _artifact({"x": 2})
    assert a.sha256 != b.sha256


def test_verify_shadow_detects_a_modified_artifact(tmp_path):
    """A silent edit to a stored response must break the evidence chain."""
    from data.shadow_snapshot import ShadowWriter

    art = _artifact({"v": 10}, name="chart")
    w = ShadowWriter(snapshot_id="s1", root=tmp_path)
    w.write("TEST", [art], {"period_end": "2026-06-30"}, {})
    assert verify_shadow("s1", "TEST", root=tmp_path)["ok"] is True

    p = tmp_path / "s1" / "TEST" / "raw" / "chart.json"
    p.write_bytes(b'{"v": 11}')

    res = verify_shadow("s1", "TEST", root=tmp_path)
    assert res["ok"] is False
    assert any(m["reason"] == "digest changed" for m in res["mismatches"])


# -------------------------------------- 52/53-week fiscal period (AMD class)

def test_fiscal_year_label_gap_still_matches():
    """AMD: SEC end 2025-12-27, Yahoo label 2025-12-31. Both are FY2025.

    An exact string compare reported all 13 AMD fields as "no filing exists",
    which is indistinguishable from a company that never filed.
    """
    art = _concept([_fact("2025-12-27", 34_639_000_000)])
    got = annual_facts_from_concept(art, "2025-12-31")
    assert got is not None
    assert got["val"] == 34_639_000_000
    assert got["_period_gap_days"] == 4


def test_a_different_fiscal_year_is_not_matched():
    """Tolerance must not reach across a year boundary into a neighbour."""
    art = _concept([_fact("2025-12-27", 1), _fact("2024-12-28", 2)])
    got = annual_facts_from_concept(art, "2024-06-30")
    assert got is None, "a June target must not match a December fact"


def test_nearest_period_wins_when_two_are_in_range():
    art = _concept([
        _fact("2025-12-27", 100, filed="2026-01-30"),
        _fact("2025-12-31", 200, filed="2026-01-30"),
    ])
    got = annual_facts_from_concept(art, "2025-12-31")
    assert got["val"] == 200, "exact/nearer period must outrank a farther one"


def test_restatement_supersedes_the_original_filing():
    art = _concept([
        _fact("2025-12-27", 999, filed="2026-02-01", accn="new"),
        _fact("2025-12-27", 100, filed="2026-01-30", accn="old"),
    ])
    got = annual_facts_from_concept(art, "2025-12-27")
    assert got["accn"] == "new"


def test_quarterly_forms_are_not_used_for_annual_corroboration():
    art = _concept([_fact("2025-12-27", 100, form="10-Q")])
    assert annual_facts_from_concept(art, "2025-12-27") is None


# --------------------------------------------------------------- unit buckets

def test_share_concepts_are_read_from_the_shares_bucket():
    """Reading shares out of the USD bucket returned nothing, which looked like
    "no share count filed". The unit map is what fixes it."""
    assert CONCEPT_UNITS["CommonStockSharesOutstanding"] == "shares"

    usd_only = _concept([_fact("2025-12-27", 1_630_000_000)], unit="USD")
    assert annual_facts_from_concept(
        usd_only, "2025-12-27", unit="shares") is None

    shares = _concept([_fact("2025-12-27", 1_630_000_000)], unit="shares")
    got = annual_facts_from_concept(shares, "2025-12-27", unit="shares")
    assert got is not None and got["val"] == 1_630_000_000


# ------------------------------------------------------------ concept mapping

def test_ebit_is_not_mapped_to_operating_income():
    """They are different quantities. Mapping EBIT to OperatingIncomeLoss
    produced a false 8.9% contradiction on MSFT (155.2B vs 169.0B); the map was
    wrong, not the data."""
    assert "ebit" not in SEC_CONCEPT_MAP
    assert SEC_CONCEPT_MAP["operating_income"] == ["OperatingIncomeLoss"]


def test_capex_is_sign_flipped_before_comparison():
    assert "capex" in SIGN_FLIP


# ------------------------------------------------------- promotion discipline

@pytest.mark.parametrize("old", [
    DataOriginType.UNKNOWN_LEGACY,
    DataOriginType.ESTIMATED,
    DataOriginType.IMPUTED,
    DataOriginType.DERIVED,
])
@pytest.mark.parametrize("new", [
    DataOriginType.VENDOR_REPORTED,
    DataOriginType.COMPANY_REPORTED,
    DataOriginType.REPORTED,
])
def test_promotion_without_evidence_is_refused(old, new):
    with pytest.raises(ProvenanceError):
        assert_no_forbidden_upgrade(old, new, "revenue")


def test_promotion_with_a_raw_digest_is_permitted():
    """Re-sourcing from a hash-recorded retrieval is scholarship, not laundering."""
    assert_no_forbidden_upgrade(
        DataOriginType.UNKNOWN_LEGACY, DataOriginType.COMPANY_REPORTED, "revenue",
        evidence={"raw_sha256": "abc123"},
    )


def test_vendor_reported_cannot_become_company_reported_silently():
    assert is_forbidden_upgrade(DataOriginType.VENDOR_REPORTED,
                               DataOriginType.COMPANY_REPORTED)


def test_company_reported_outranks_vendor_reported():
    def tier(origin):
        return FieldProvenance(origin_type=origin).tier

    assert (tier(DataOriginType.COMPANY_REPORTED)
            < tier(DataOriginType.VENDOR_REPORTED))


def test_vendor_reported_is_not_treated_as_a_company_disclosure():
    """The whole point of the split: same value, weaker claim."""
    from data.provenance import ProvenanceTier

    t = FieldProvenance(origin_type=DataOriginType.VENDOR_REPORTED).tier
    assert t > ProvenanceTier.REPORTED
    assert t < ProvenanceTier.DERIVED


# --------------------------------------------------------- stored snapshots

SHADOW = Path(__file__).resolve().parent.parent / "data" / "shadow_snapshots"


def _shadow_ids():
    if not SHADOW.exists():
        return []
    return [d.name for d in SHADOW.iterdir() if d.is_dir()]


@pytest.mark.parametrize("sid", _shadow_ids())
def test_every_stored_shadow_verifies(sid):
    """If a shadow exists on disk, its digests must still match its bytes."""
    tickers = [d.name for d in (SHADOW / sid).iterdir() if d.is_dir()]
    for t in tickers:
        res = verify_shadow(sid, t)
        assert res["ok"], f"{t} artefact mismatch: {res['mismatches']}"


@pytest.mark.parametrize("sid", _shadow_ids())
def test_no_shadow_claims_company_reported_without_an_accession(sid):
    """The hard rule: COMPANY_REPORTED requires a filing identifier behind it."""
    for d in (SHADOW / sid).iterdir():
        if not d.is_dir():
            continue
        prov_path = d / "provenance.json"
        if not prov_path.exists():
            continue
        prov = json.loads(prov_path.read_text())
        for field_name, rec in prov.items():
            origin = rec.get("origin_type")
            if origin == DataOriginType.COMPANY_REPORTED.value:
                assert rec.get("sec_accession"), (
                    f"{d.name}/{field_name} claims COMPANY_REPORTED "
                    f"with no accession number")


@pytest.mark.parametrize("sid", _shadow_ids())
def test_no_shadow_writes_outside_its_own_directory(sid):
    """A shadow must never touch .cache or a golden file."""
    root = Path(__file__).resolve().parent.parent
    assert (root / "data" / "shadow_snapshots" / sid).is_dir()
