"""Every benchmark ticker must land in an explicit, explained outcome.

The acceptance bar is "no omission, no default-pass, no silent skip". A missing
reverse-DCF status is legitimate only for names the registry marks as not
applicable (banks / insurers / REITs routed to their own methodology), and even
then the exclusion must name a business type. Anything else is a silent skip and
must fail rather than quietly disappear from the totals.
"""

from __future__ import annotations

import pytest

from benchmark.audit import DATA_ISSUE, FAIL, NOT_APPLICABLE, check_e_coverage
from benchmark.registry import BY_TICKER


def _an_applicable() -> str:
    return next(t for t, e in BY_TICKER.items() if e.expect_applicable)


def _a_non_applicable() -> str:
    return next(t for t, e in BY_TICKER.items() if not e.expect_applicable)


def test_solved_ticker_produces_no_coverage_finding() -> None:
    t = _an_applicable()
    assert check_e_coverage(t, {"rd_status": "Solved"}) == []


def test_expected_but_missing_status_fails() -> None:
    t = _an_applicable()
    out = check_e_coverage(t, {"rd_status": None, "business_type": "MatureTech"})
    assert out and out[0].verdict == FAIL
    assert "silent skip" in out[0].detail


def test_excluded_without_business_type_is_data_issue() -> None:
    t = _a_non_applicable()
    out = check_e_coverage(t, {"rd_status": None, "business_type": None})
    assert out and out[0].verdict == DATA_ISSUE


def test_excluded_with_business_type_is_not_applicable() -> None:
    t = _a_non_applicable()
    out = check_e_coverage(t, {"rd_status": None, "business_type": "Bank"})
    assert out and out[0].verdict == NOT_APPLICABLE
    assert "Bank" in out[0].detail


def test_unknown_ticker_fails() -> None:
    out = check_e_coverage("NOT_A_TICKER", {"rd_status": None})
    assert out and out[0].verdict == FAIL


class TestLiveBenchmarkCoverage:
    """Run the check against the captured facts, if present."""

    def test_every_registry_ticker_has_facts(self):
        import json
        from pathlib import Path

        p = Path("benchmark/results/raw_facts.json")
        if not p.exists():
            pytest.skip("no captured facts; run benchmark/run_benchmark.py first")
        facts = json.loads(p.read_text())
        assert set(BY_TICKER) <= set(facts), (
            f"tickers missing from captured facts: {sorted(set(BY_TICKER) - set(facts))}"
        )

    def test_no_silent_skips_in_captured_facts(self):
        import json
        from pathlib import Path

        p = Path("benchmark/results/raw_facts.json")
        if not p.exists():
            pytest.skip("no captured facts")
        facts = json.loads(p.read_text())
        for t, e in BY_TICKER.items():
            f = facts.get(t) or {}
            out = check_e_coverage(t, f)
            assert all(x.verdict != FAIL for x in out), (
                f"{t}: silent skip -- {[x.detail for x in out]}"
            )

    def test_every_no_solution_names_a_mechanism(self):
        """A no-solution result must say *why*, and the why must be a known cause."""
        import json
        from pathlib import Path

        p = Path("benchmark/results/raw_facts.json")
        if not p.exists():
            pytest.skip("no captured facts")
        facts = json.loads(p.read_text())
        allowed = {
            "above_search_ceiling", "below_search_floor",
            "ev_decreasing_in_growth",
        }
        for t, f in facts.items():
            if f.get("rd_status") != "No Solution In Range":
                continue
            meta = f.get("rd_solver_meta") or {}
            assert meta.get("failure") in allowed, (
                f"{t}: no-solution without a recognised failure reason "
                f"({meta.get('failure')!r})"
            )
