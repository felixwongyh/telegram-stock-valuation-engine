"""
tests/test_golden_report.py - Golden report diff + self-contradiction guard

Two layers:

  1. `test_report_invariants_hold` — the *defect checklist*. For every ticker in
     the basket it asserts the report contains no internal contradiction
     (coverage identity, agreement-vs-coverage cap, β consistency across
     market/risk/WACC, non-negative solved values, overrides actually applied).

  2. `test_golden_fingerprint_matches` — the *golden diff*. It compares a compact
     fingerprint of the live pipeline against `golden/report_fingerprints.json`.
     Any behavioural drift fails the test and prints a readable diff, so the next
     improvement round cannot silently introduce a new inconsistency.

Regenerate the golden baseline after a *reviewed, intended* change:

    UPDATE_GOLDEN=1 pytest tests/test_golden_report.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.golden_report import (
    BASKET,
    build_fingerprint,
    check_invariants,
    run_pipeline,
)

GOLDEN_PATH = Path(__file__).parent / "golden" / "report_fingerprints.json"


def _collect():
    """Return {ticker: fingerprint} and {ticker: [defects]} for the whole basket."""
    fingerprints = {}
    defects = {}
    for t in BASKET:
        ctx = run_pipeline(t)
        fp = build_fingerprint(t)
        fingerprints[t] = fp
        defects[t] = check_invariants(fp, ctx)
    return fingerprints, defects


@pytest.fixture(scope="module")
def collected():
    return _collect()


class TestReportInvariants:
    def test_report_invariants_hold(self, collected):
        fingerprints, defects = collected
        all_defects = []
        for t, ds in defects.items():
            for d in ds:
                all_defects.append(d)
        assert not all_defects, "Report self-contradictions detected:\n  " + "\n  ".join(all_defects)

    def test_coverage_identity_explicit(self, collected):
        fingerprints, _ = collected
        for t, fp in fingerprints.items():
            assert fp["n_applicable"] == fp["n_solved"] + fp["n_failed"], (
                f"{t}: applicable {fp['n_applicable']} != "
                f"solved {fp['n_solved']} + failed {fp['n_failed']}"
            )


class TestGoldenDiff:
    def test_golden_fingerprint_matches(self, collected):
        fingerprints, _ = collected
        live = {t: fingerprints[t] for t in BASKET}

        if os.environ.get("UPDATE_GOLDEN") == "1" or not GOLDEN_PATH.exists():
            GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_PATH.write_text(
                json.dumps(live, indent=2, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            pytest.skip(f"Golden baseline written to {GOLDEN_PATH}")

        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        diffs = []
        for t in BASKET:
            g = golden.get(t, {})
            live_fp = live[t]
            for key in sorted(set(g) | set(live_fp)):
                if key == "ticker":
                    continue
                if g.get(key) != live_fp.get(key):
                    diffs.append(f"{t}.{key}: golden={g.get(key)!r} -> live={live_fp.get(key)!r}")
        assert not diffs, (
            "Report fingerprint drifted from the golden baseline "
            "(review, then regenerate with UPDATE_GOLDEN=1):\n  " + "\n  ".join(diffs)
        )
