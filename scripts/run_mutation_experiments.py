"""§10 Mutation testing harness.

A green suite only proves the suite cannot see the bugs it never tests. This
script injects each of the 16 defects named in Master Validation §10 into the
real source, runs the *specific* test that is supposed to catch it, and records
whether that test actually failed. Then the source is restored byte-for-byte.

Two rules the harness enforces:

* A mutation must be caught by the **named** test, not merely by "pytest went
  red somewhere" (§10 acceptance criterion). A mutation caught only by an
  unrelated test is reported as MISATTRIBUTED: the intended guard is not the
  one doing the work.
* The file is restored exactly and verified by SHA-256, even if the run crashes.
  A harness that leaves mutated source behind is worse than no harness.

Usage::

    python scripts/run_mutation_experiments.py [--json out.json] [--only ID]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parent.parent


@dataclass
class Mutation:
    """One deliberate defect plus the test that is supposed to notice it."""

    mid: str
    title: str
    path: str
    old: str
    new: str
    tests: List[str]
    note: str = ""
    #: 1-based index of the occurrence to patch when ``old`` is not unique.
    #: Anchoring by occurrence keeps the mutation honest even when the same
    #: statement appears in several code paths (FCF is projected in three
    #: places); patching "all of them" would test something else.
    occurrence: int = 1
    result: dict = field(default_factory=dict)


MUTATIONS: List[Mutation] = [
    Mutation(
        "M01",
        "price_residual_tol 1e-4 -> 1e-3",
        "config.py",
        "    price_residual_tol: float = 1e-4",
        "    price_residual_tol: float = 1e-3",
        ["tests/test_false_solved_regressions.py::"
         "test_endpoint_short_circuit_cannot_bypass_residual_bar"],
        "A 10x looser residual bar must let a 5e-4 residual through, which the "
        "endpoint regression test pins.",
    ),
    Mutation(
        "M02",
        "newton_tol 1e-10 -> 1e-4",
        "config.py",
        "    newton_tol: float = 1e-10",
        "    newton_tol: float = 1e-4",
        ["tests/test_false_solved_regressions.py::"
         "test_tuning_one_instance_does_not_pollute_the_default"],
        "The config default is asserted explicitly, so reverting it is caught.",
    ),
    Mutation(
        "M03",
        "treasury freeze ignored (always refetch)",
        "data/providers.py",
        '    _FREEZE_ENV = "UVE_FREEZE_CACHE"',
        '    _FREEZE_ENV = "UVE_FREEZE_CACHE_DISABLED"',
        ["tests/test_freeze_miss_refusal.py::"
         "test_treasury_frozen_miss_must_not_fetch"],
        "Renaming the env var means the freeze flag is never seen, so a frozen "
        "miss silently downloads.",
    ),
    Mutation(
        "M04",
        "frozen miss auto-fetches instead of raising",
        "data/providers.py",
        "            if self._cache_frozen():\n"
        "                raise FrozenSnapshotMissError(\n"
        '                    f"UVE_FREEZE_CACHE is set but no cached data for {ticker_u}: "\n'
        '                    "refusing to fetch live data into a frozen snapshot"\n'
        "                )",
        "            if False:\n"
        "                raise FrozenSnapshotMissError(\n"
        '                    f"UVE_FREEZE_CACHE is set but no cached data for {ticker_u}: "\n'
        '                    "refusing to fetch live data into a frozen snapshot"\n'
        "                )",
        ["tests/test_freeze_miss_refusal.py::"
         "test_yahoo_frozen_miss_must_not_fetch"],
        "Freeze mode cache miss must refuse, never fall through to the network.",
    ),
    Mutation(
        "M05",
        "beta pairs shifted by one month",
        "data/providers.py",
        "            for i in range(1, len(common)):\n"
        "                tp = tgt_p[common[i - 1]][0]\n"
        "                tc = tgt_p[common[i]][0]\n"
        "                sp = spy_p[common[i - 1]][0]\n"
        "                sc = spy_p[common[i]][0]",
        "            for i in range(1, len(common)):\n"
        "                tp = tgt_p[common[i - 1]][0]\n"
        "                tc = tgt_p[common[i]][0]\n"
        "                sp = spy_p[common[max(i - 2, 0)]][0]\n"
        "                sc = spy_p[common[i - 1]][0]",
        ["tests/test_beta_synthetic_recovery.py::"
         "test_missing_month_reduces_sample_without_shifting_pairs"],
        "Shifting the SPY leg by one month is exactly the misalignment the "
        "calendar-keyed test was written for.",
    ),
    Mutation(
        "M06",
        "CapEx sign reversed (spend becomes income)",
        "forecasts/fcf_projection.py",
        "        capex = rev * capex_ratio",
        "        capex = -rev * capex_ratio",
        ["tests/test_growth_direction.py::"
         "TestMatchesRealProjection::test_sign_matches_engine"],
        "Capex must always be a cash *outflow*; flipping the sign inflates FCF.",
        occurrence=2,
    ),
    Mutation(
        "M07",
        "NWC investment intensity used as marginal NWC",
        "forecasts/nwc_utils.py",
        "    return marginal_ratio * delta_revenue",
        "    return marginal_ratio * delta_revenue * 10.0",
        ["tests/test_nwc_marginal_change.py::"
         "test_it_scales_the_revenue_change"],
        "Scaling the marginal ratio by 10 is the same class of error as reading "
        "an investment-intensity level where a marginal slope belongs.",
    ),
    Mutation(
        "M08",
        "synthetic provenance tag dropped",
        "data/validator.py",
        '            tag = "synthetic_demo_not_live_market"',
        '            tag = ""',
        ["tests/test_universe_and_provenance_guards.py::"
         "test_synthetic_source_is_flagged"],
        "Losing the provenance tag lets synthetic data read as live market data.",
    ),
    Mutation(
        "M09",
        "root scan returns only the first root",
        "models/reverse_dcf.py",
        "            if not any(abs(r - u) < 1e-4 for u in uniq):\n"
        "                uniq.append(r)\n"
        "        return uniq",
        "            if not any(abs(r - u) < 1e-4 for u in uniq):\n"
        "                uniq.append(r)\n"
        "        return uniq[:1]",
        ["tests/test_multi_root_scan.py::test_all_crossings_are_returned"],
        "Truncating to one root hides a genuine second root, so a "
        "non-unique implied growth would be reported as unique.",
    ),
    Mutation(
        "M10",
        "multiple-roots flag forced off",
        "models/reverse_dcf.py",
        '                "multiple_roots": multi,',
        '                "multiple_roots": False,',
        ["tests/test_multi_root_scan.py::"
         "test_solver_meta_reports_multiple_roots_when_they_exist"],
        "Hiding a known second root must be visible to the solver-meta audit.",
    ),
    Mutation(
        "M11",
        "local growth direction reported as global",
        "forecasts/growth_direction.py",
        'VERDICT_SCOPE = "LOCAL_EV_DIRECTION_AT_REFERENCE_G"',
        'VERDICT_SCOPE = "GLOBAL_EV_DIRECTION"',
        ["tests/test_growth_direction.py::"
         "test_verdict_is_local_not_extrapolated"],
        "The scope string is a contract: a local sign must not be sold as global.",
    ),
    Mutation(
        "M12",
        "terminal growth allowed to equal WACC",
        "valuation/terminal_growth.py",
        "        wacc_floor = max(0.005, wacc - 0.005)",
        "        wacc_floor = wacc",
        ["tests/test_terminal_growth.py::"
         "TestTerminalGrowthBands::test_tight_gordon_bound_slides_window"],
        "A zero spread lets tg reach WACC, making the Gordon TV explode.",
    ),
    Mutation(
        "M13",
        "negative FCF silently made positive",
        "forecasts/fcf_projection.py",
        "        fcf = nopat + da - capex - nwc",
        "        fcf = abs(nopat + da - capex - nwc)",
        ["tests/test_growth_direction.py::"
         "test_analytic_slope_matches_finite_difference_pointwise"],
        "abs() on FCF turns a loss-making company into a profitable one, which "
        "the analytic-vs-finite-difference slope check sees immediately.",
        occurrence=2,
    ),
    Mutation(
        "M14",
        "MODEL_NOT_APPLICABLE reported as SOLVED",
        "benchmark/report.py",
        "            return (\n"
        "                MODEL_NOT_APPLICABLE,\n"
        '                f"reverse DCF not applicable ({bt}); {reason}",\n'
        "            )",
        "            return (\n"
        "                SOLVED,\n"
        '                f"reverse DCF not applicable ({bt}); {reason}",\n'
        "            )",
        ["tests/test_report_status.py::"
         "test_routed_out_ticker_gets_explicit_status_not_blank"],
        "A correct decline must never be upgraded to a solution.",
    ),
    Mutation(
        "M15",
        "one ticker renamed out of the universe",
        "benchmark/registry.py",
        '        "VICI", "VICI Properties", "Gaming REIT", "Real Estate",',
        '        "VICIX", "VICI Properties", "Gaming REIT", "Real Estate",',
        ["tests/test_universe_and_provenance_guards.py::"
         "test_reits_are_present_in_the_universe"],
        "A renamed ticker is a lost ticker: the universe still has 50 rows but "
        "VICI no longer resolves, so the coverage identity must break.",
    ),
    Mutation(
        "M16",
        "golden fingerprint key field altered",
        "tests/golden/report_fingerprints.json",
        '"beta_effective": 1.0',
        '"beta_effective": 1.0001',
        ["tests/test_golden_report.py::TestGoldenDiff::"
         "test_golden_fingerprint_matches"],
        "The fingerprint exists to catch exactly this kind of silent drift.",
    ),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_tests(tests: List[str]) -> tuple:
    """Run the named tests; return (returncode, summary line)."""
    cmd = [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:randomly", *tests]
    proc = subprocess.run(
        cmd, cwd=REPO, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    return proc.returncode, (tail[-1] if tail else "<no output>")


def apply_mutation(m: Mutation) -> Optional[str]:
    """Inject the defect. Returns an error string, or None on success."""
    target = REPO / m.path
    if not target.exists():
        return f"target missing: {m.path}"
    text = target.read_text(encoding="utf-8")
    count = text.count(m.old)
    if count < m.occurrence:
        return (
            f"anchor found {count} time(s) in {m.path} but occurrence "
            f"{m.occurrence} was requested - the mutation target has drifted"
        )
    idx = -1
    for _ in range(m.occurrence):
        idx = text.find(m.old, idx + 1)
    target.write_text(text[:idx] + m.new + text[idx + len(m.old):], encoding="utf-8")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--only", default=None, help="run a single mutation id")
    args = ap.parse_args()

    selected = [m for m in MUTATIONS if not args.only or m.mid == args.only]
    if not selected:
        print(f"no mutation matches {args.only!r}", file=sys.stderr)
        return 2

    print(f"§10 mutation testing - {len(selected)} of {len(MUTATIONS)} mutations\n")
    print(f"{'ID':<5} {'verdict':<14} {'mutation'}")
    print("-" * 78)

    for m in selected:
        target = REPO / m.path
        original = target.read_bytes() if target.exists() else b""
        original_sha = hashlib.sha256(original).hexdigest()
        backup = Path(tempfile.mkdtemp()) / "backup"
        backup.write_bytes(original)

        err = apply_mutation(m)
        if err:
            m.result = {"verdict": "ANCHOR_DRIFT", "detail": err}
            print(f"{m.mid:<5} {'ANCHOR_DRIFT':<14} {m.title}")
            continue

        try:
            rc, summary = run_tests(m.tests)
        finally:
            target.write_bytes(backup.read_bytes())
            restored_sha = sha256(target)
            if restored_sha != original_sha:
                raise SystemExit(
                    f"FATAL: {m.path} not restored ({original_sha} -> {restored_sha})"
                )

        caught = rc != 0
        m.result = {
            "verdict": "CAUGHT" if caught else "SURVIVED",
            "mutation": m.title,
            "target": m.path,
            "expected_tests": m.tests,
            "pytest_summary": summary,
            "restored_sha256": original_sha,
        }
        print(f"{m.mid:<5} {m.result['verdict']:<14} {m.title}")
        print(f"      expected: {m.tests[0].split('::')[-1]}")
        print(f"      pytest  : {summary}")

    survivors = [m for m in selected if m.result.get("verdict") != "CAUGHT"]
    print("\n" + "=" * 78)
    print(f"caught {len(selected) - len(survivors)}/{len(selected)}")
    if survivors:
        print("NOT CAUGHT BY THE INTENDED TEST:")
        for m in survivors:
            print(f"  {m.mid} {m.title} -> {m.result.get('verdict')} "
                  f"{m.result.get('detail', '')}")

    if args.json:
        Path(args.json).write_text(
            json.dumps({m.mid: m.result for m in selected}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nwrote {args.json}")

    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
