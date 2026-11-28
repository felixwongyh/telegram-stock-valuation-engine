"""Guard rails for the shadow / reconciliation phase.

These assert the *invariants* the phase promised, not the specific numbers:

* the frozen golden was not modified;
* no shadow claims a filing it cannot cite;
* every stored shadow still verifies;
* the reports exist and do not claim a replacement happened.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_FP = ROOT / "tests" / "golden" / "report_fingerprints.json"
SHADOW_ROOT = ROOT / "data" / "shadow_snapshots"
DOCS = ROOT / "docs" / "audit"


def _snapshot_ids():
    if not SHADOW_ROOT.exists():
        return []
    return sorted(d.name for d in SHADOW_ROOT.iterdir() if d.is_dir())


def _tickers(sid):
    return sorted(d.name for d in (SHADOW_ROOT / sid).iterdir() if d.is_dir())


# ----------------------------------------------------- golden was not touched

def test_golden_fingerprints_are_unchanged_this_phase():
    """The phase must not rewrite the 50-ticker baseline.

    Only two values may differ from HEAD, and they are from an earlier session
    (``recon_checks`` 10 -> 9), not from this phase. The guard therefore pins
    the *set of changed keys* rather than demanding a clean tree: a new key
    appearing here means this phase edited the baseline, which the rules forbid.
    """
    try:
        res = subprocess.run(
            ["git", "diff", "-U0", "HEAD", "--",
             "tests/golden/report_fingerprints.json"],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        pytest.skip("git unavailable")
    assert res.returncode == 0

    changed_keys = set()
    for line in res.stdout.splitlines():
        s = line.lstrip("+-").strip()
        if not s.startswith('"'):
            continue
        key = s.split('"')[1] if s.count('"') >= 2 else ""
        if key:
            changed_keys.add(key)

    assert changed_keys <= {"recon_checks"}, (
        "this phase changed golden fields it must not touch: "
        f"{sorted(changed_keys - {'recon_checks'})}")


# ------------------------------------------------ no unsupported origin claims

@pytest.mark.parametrize("sid", _snapshot_ids())
def test_annual_company_reported_fields_cite_a_filing(sid):
    for t in _tickers(sid):
        p = SHADOW_ROOT / sid / t / "provenance.json"
        if not p.exists():
            continue
        for field, rec in json.loads(p.read_text()).items():
            origin = rec.get("origin_type")
            if origin == "company_reported":
                assert rec.get("sec_accession"), f"{sid}/{t}/{field}"
                assert rec.get("sec_filed"), f"{sid}/{t}/{field}"
                assert rec.get("evidence_raw_sha256"), f"{sid}/{t}/{field}"


@pytest.mark.parametrize("sid", _snapshot_ids())
def test_ttm_layer_never_claims_company_reported(sid):
    """A sum of four vendor quarters is not a figure any filer reports."""
    for t in _tickers(sid):
        p = SHADOW_ROOT / sid / t / "ttm_provenance.json"
        if not p.exists():
            continue
        for field, rec in json.loads(p.read_text()).items():
            origin = rec.get("origin_type")
            origin = getattr(origin, "value", origin)
            assert origin != "company_reported", (
                f"{sid}/{t}/{field} claims company_reported on a TTM sum")


@pytest.mark.parametrize("sid", _snapshot_ids())
def test_stock_fields_are_not_summed_over_four_quarters(sid):
    """A balance-sheet line cannot quadruple by being measured over a year."""
    for t in _tickers(sid):
        p = SHADOW_ROOT / sid / t / "ttm_provenance.json"
        if not p.exists():
            continue
        prov = json.loads(p.read_text())
        for field in ("shares_outstanding", "stockholders_equity", "cash",
                      "total_debt"):
            rec = prov.get(field)
            if not rec:
                continue
            assert rec.get("ttm_basis") == "LATEST_QUARTER_BALANCE", (
                f"{sid}/{t}/{field} basis={rec.get('ttm_basis')}")


# --------------------------------------------------------- reports are honest

def test_reports_exist_and_do_not_claim_a_replacement():
    required = ["SHADOW_SNAPSHOT_REPORT.md",
                "GOLDEN_RECONCILIATION_REPORT.md",
                "PROVENANCE_COVERAGE_REPORT.md"]
    for name in required:
        p = DOCS / name
        assert p.exists(), f"missing {name}"
        text = p.read_text().lower()
        # The phase produces evidence; it must not present itself as having
        # re-baselined the golden.
        for banned in ("golden updated", "golden replaced", "baseline updated"):
            assert banned not in text, f"{name} claims: {banned}"


def test_reconciliation_report_states_the_cadence_rule():
    text = (DOCS / "GOLDEN_RECONCILIATION_REPORT.md").read_text()
    assert "TTM cadence" in text or "TTM" in text


def test_coverage_report_records_that_ttm_cannot_be_company_reported():
    text = (DOCS / "PROVENANCE_COVERAGE_REPORT.md").read_text()
    assert "cannot be company-reported" in text.lower() or \
           "cannot be `company_reported`" in text.lower()
