"""P2 — "no solution" must be split into categories that mean different things.

Collapsing every no-root outcome into one status hides whether the *model* is
wrong, the *search domain* is too narrow, or the *question* is unanswerable at
the available precision. A single status invites a single (wrong) conclusion.
"""
from __future__ import annotations


from models.reverse_dcf import _classify_no_root


class TestNoRootClassification:
    def test_undetermined_wins_over_everything(self):
        # Even with a ceiling failure and a peak below target, a direction that
        # flips under plausible NWC means nothing can be concluded.
        kind = _classify_no_root(
            failure="above_search_ceiling",
            direction_undetermined=True,
            peak_below_target=True,
        )
        assert kind == "EV_DIRECTION_UNDETERMINED"

    def test_ceiling_failure_is_search_domain_insufficient(self):
        kind = _classify_no_root(
            failure="above_search_ceiling",
            direction_undetermined=False,
            peak_below_target=False,
        )
        assert kind == "SEARCH_DOMAIN_INSUFFICIENT"

    def test_floor_failure_is_search_domain_insufficient(self):
        kind = _classify_no_root(
            failure="below_search_floor",
            direction_undetermined=False,
            peak_below_target=False,
        )
        assert kind == "SEARCH_DOMAIN_INSUFFICIENT"

    def test_decreasing_curve_with_peak_below_target_is_no_root_in_domain(self):
        kind = _classify_no_root(
            failure="ev_decreasing_in_growth",
            direction_undetermined=False,
            peak_below_target=True,
        )
        assert kind == "NO_ROOT_IN_DOMAIN"

    def test_decreasing_curve_with_peak_above_target_is_solver_nonconvergence(self):
        # A root exists inside the band but the solver missed it: the defect is
        # numerical, not economic, and must not be reported as "no root".
        kind = _classify_no_root(
            failure="ev_decreasing_in_growth",
            direction_undetermined=False,
            peak_below_target=False,
        )
        assert kind == "SOLVER_NONCONVERGENCE"

    def test_unknown_failure_defaults_to_no_root_in_domain(self):
        kind = _classify_no_root(
            failure=None,
            direction_undetermined=False,
            peak_below_target=True,
        )
        assert kind == "NO_ROOT_IN_DOMAIN"


class TestAuditUnderstandsTheTaxonomy:
    def test_undetermined_is_not_reported_as_a_defect(self):
        from benchmark.verify_fix import check_solver_residual

        verdict, reason = check_solver_residual({
            "rd_solver_meta": {
                "converged": False,
                "failure": "ev_decreasing_in_growth",
                "no_root_kind": "EV_DIRECTION_UNDETERMINED",
                "ev_flips_between": [[0.05, 0.10]],
            }
        })
        assert verdict == "PASS"
        assert "undetermined" in reason

    def test_search_domain_insufficient_is_a_warning(self):
        from benchmark.verify_fix import check_solver_residual

        verdict, _ = check_solver_residual({
            "rd_solver_meta": {
                "converged": False,
                "failure": "above_search_ceiling",
                "no_root_kind": "SEARCH_DOMAIN_INSUFFICIENT",
            }
        })
        assert verdict == "WARN"
