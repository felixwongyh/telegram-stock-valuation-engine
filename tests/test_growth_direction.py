"""Tests for the derived growth-direction criterion.

The criterion's value depends entirely on it being *conditional*: it must be
right when its assumptions hold, and silent when they do not. Both halves are
tested against the engine's real projection, not a toy model.
"""
import pytest

from forecasts.fcf_projection import project_enterprise_value_shaped
from forecasts.growth_direction import (
    BOUNDARY_BAND,
    analytic_slope,
    evaluate,
    pv_factors,
    sign_over_range,
    steady_state_fcf_margin,
)

WACC, TG, HORIZON = 0.09, 0.02, 10
OM, TAX, DA, CAPEX = 0.20, 0.21, 0.05, 0.06


def _slope(w, *, om=OM, tau=TAX, da=DA, capex=CAPEX, eps=1e-6):
    def ev(g):
        return project_enterprise_value_shaped(
            1000.0, g, om, tau, da, capex, w, WACC, TG, HORIZON
        ).enterprise_value
    return (ev(eps) - ev(-eps)) / (2 * eps)


class TestSteadyStateMargin:
    def test_formula(self):
        assert steady_state_fcf_margin(0.20, 0.21, 0.05, 0.06) == \
            pytest.approx(0.20 * 0.79 + 0.05 - 0.06)

    def test_capex_sign_is_irrelevant(self):
        """Capex is a cash outflow whichever sign the provider reports."""
        assert steady_state_fcf_margin(0.20, 0.21, 0.05, -0.06) == \
            pytest.approx(steady_state_fcf_margin(0.20, 0.21, 0.05, 0.06))


class TestPvFactors:
    def test_hurdle_is_not_one(self):
        """The naive k0/w > 1 rule is wrong; the hurdle is ~1/duration."""
        p, d = pv_factors(WACC, TG, HORIZON)
        assert p / d == pytest.approx(0.136, abs=0.005)
        assert p / d != pytest.approx(1.0)

    def test_hurdle_falls_with_horizon(self):
        short = pv_factors(WACC, TG, 3)
        long_ = pv_factors(WACC, TG, 40)
        assert short[0] / short[1] > long_[0] / long_[1]

    def test_degenerate_inputs(self):
        assert pv_factors(WACC, TG, 0) == (0.0, 0.0)
        assert pv_factors(0.02, 0.02, 10) == (0.0, 0.0)


class TestMatchesRealProjection:
    @pytest.mark.parametrize("w", [0.10, 0.20, 0.40, 0.80, 1.00, 1.50, 2.50])
    def test_sign_matches_engine(self, w):
        test = evaluate(OM, TAX, DA, CAPEX, w, WACC, TG, HORIZON)
        if not test.applicable:
            pytest.skip("criterion declined this point")
        assert test.growth_adds_value == (_slope(w) > 0)

    def test_flip_point_is_near_hurdle(self):
        """Sign changes between the two w values that straddle the hurdle."""
        # k0/w = hurdle  =>  w = k0/hurdle
        _, d = pv_factors(WACC, TG, HORIZON)
        p, _ = pv_factors(WACC, TG, HORIZON)
        k0 = steady_state_fcf_margin(OM, TAX, DA, CAPEX)
        w_flip = k0 / (p / d)
        # A *smaller* NWC coefficient means a higher k0/w, hence growth adds value.
        assert evaluate(OM, TAX, DA, CAPEX, w_flip * 0.6, WACC, TG, HORIZON) \
            .growth_adds_value is True
        assert evaluate(OM, TAX, DA, CAPEX, w_flip * 1.4, WACC, TG, HORIZON) \
            .growth_adds_value is False


class TestRefusesWhenInapplicable:
    def test_declines_near_boundary(self):
        k0 = steady_state_fcf_margin(OM, TAX, DA, CAPEX)
        p, d = pv_factors(WACC, TG, HORIZON)
        w_at_hurdle = k0 / (p / d)
        test = evaluate(OM, TAX, DA, CAPEX, w_at_hurdle, WACC, TG, HORIZON)
        assert test.applicable is False
        assert test.verdict == "indeterminate"
        assert any("边界" in r or "以内" in r for r in test.reasons)

    def test_no_verdict_when_inapplicable(self):
        """An inapplicable test must not also answer."""
        test = evaluate(OM, TAX, DA, CAPEX, 0.20, WACC, TG, HORIZON,
                        margin_is_flat=False)
        assert test.applicable is False
        assert test.growth_adds_value is None
        assert test.verdict == "indeterminate"

    def test_declines_when_k0_nonpositive(self):
        test = evaluate(0.02, 0.21, 0.01, 0.30, 0.20, WACC, TG, HORIZON)
        assert test.applicable is False
        assert any("k0" in r for r in test.reasons)

    def test_declines_when_wacc_below_terminal_growth(self):
        test = evaluate(OM, TAX, DA, CAPEX, 0.20, 0.02, 0.02, HORIZON)
        assert test.applicable is False
        assert any("Gordon" in r or "终值" in r for r in test.reasons)

    def test_declines_without_marginal_nwc(self):
        test = evaluate(OM, TAX, DA, CAPEX, None, WACC, TG, HORIZON)
        assert test.applicable is False
        assert any("边际 NWC" in r for r in test.reasons)


class TestZeroAndNegativeNwc:
    def test_zero_nwc_reduces_to_k0_positive(self):
        test = evaluate(OM, TAX, DA, CAPEX, 0.0, WACC, TG, HORIZON)
        assert test.growth_adds_value is True
        assert test.applicable is True

    def test_negative_nwc_flagged(self):
        """A negative coefficient inverts the ratio's meaning."""
        test = evaluate(OM, TAX, DA, CAPEX, -0.15, WACC, TG, HORIZON)
        assert any("负" in r for r in test.reasons)


class TestVerdicts:
    def test_verdict_matches_boolean(self):
        adds = evaluate(OM, TAX, DA, CAPEX, 0.20, WACC, TG, HORIZON)
        assert adds.verdict == "adds_value"
        destroys = evaluate(OM, TAX, DA, CAPEX, 3.0, WACC, TG, HORIZON)
        assert destroys.verdict == "destroys_value"

    def test_serialisable(self):
        d = evaluate(OM, TAX, DA, CAPEX, 0.20, WACC, TG, HORIZON).as_dict()
        for key in ("k0", "hurdle_ratio", "verdict", "applicable",
                    "duration_years", "reasons"):
            assert key in d

    def test_boundary_band_is_a_relative_fraction(self):
        assert 0 < BOUNDARY_BAND < 1


# --- Local-scope verification (review requirement) -------------------------
# The criterion is a LOCAL derivative sign. These tests exist because an
# earlier version presented the g=0 sign as a range-wide claim, which is false:
# for w=0.80 the slope is positive at g=0 and negative from g~0.08 upward.

def _fd(g, *, w, r=WACC, tg=TG, H=HORIZON, h=1e-6, R0=1000.0):
    def ev(x):
        return project_enterprise_value_shaped(
            R0, x, OM, TAX, DA, CAPEX, w, r, tg, H
        ).enterprise_value
    return (ev(g + h) - ev(g - h)) / (2 * h)


GRID = [-0.04, 0.0, 0.02, 0.05, 0.08, 0.10, 0.15, 0.25, 0.40, 0.60]
W_VALUES = [0.10, 0.30, 0.80, 1.50, 2.60]


@pytest.mark.parametrize("w", W_VALUES)
@pytest.mark.parametrize("g", GRID)
def test_analytic_slope_matches_finite_difference_pointwise(w, g):
    """Point-by-point agreement, not one sample: the review's core requirement."""
    a = analytic_slope(1000.0, g, OM, TAX, DA, CAPEX, w, WACC, TG, HORIZON)
    f = _fd(g, w=w)
    assert a is not None
    scale = max(abs(a), abs(f), 1e-12)
    assert abs(a - f) / scale < 1e-5
    assert (a > 0) == (f > 0), f"sign mismatch at w={w}, g={g}"


@pytest.mark.parametrize("w", W_VALUES)
def test_verdict_is_local_not_extrapolated(w):
    """The g=0 sign must not be claimed as the sign at every growth rate."""
    t = evaluate(OM, TAX, DA, CAPEX, w, WACC, TG, HORIZON, revenue0=1000.0)
    assert t.verdict_scope == "LOCAL_EV_DIRECTION_AT_REFERENCE_G"
    if t.flips_at_growth is not None:
        assert t.flips_at_growth > t.reference_growth
        # the flip is real: the finite-difference sign actually reverses
        assert (_fd(t.flips_at_growth + 0.02, w=w) > 0) != (t.growth_adds_value)
        assert any("不可外推" in r for r in t.reasons)


def test_flip_point_exists_for_known_counterexample():
    """w=0.80 is the documented case: adds at g=0, destroys from ~0.08."""
    t = evaluate(OM, TAX, DA, CAPEX, 0.80, WACC, TG, HORIZON, revenue0=1000.0)
    assert t.growth_adds_value is True
    assert t.flips_at_growth is not None
    assert 0.02 < t.flips_at_growth < 0.20
    assert _fd(0.30, w=0.80) < 0        # sign really is negative up there


def test_no_flip_when_slope_is_monotone():
    """A clearly-destroying name must not report a spurious flip."""
    t = evaluate(OM, TAX, DA, CAPEX, 2.60, WACC, TG, HORIZON, revenue0=1000.0)
    assert t.growth_adds_value is False
    assert t.flips_at_growth is None


def test_sign_over_range_reports_distinct_signs():
    both = sign_over_range(1000.0, OM, TAX, DA, CAPEX, 0.80, WACC, TG, HORIZON)
    assert both["signs"] == ["+", "-"]
    assert both["flips_at_growth"] is not None
    one = sign_over_range(1000.0, OM, TAX, DA, CAPEX, 2.60, WACC, TG, HORIZON)
    assert one["signs"] == ["-"]


def test_reference_growth_is_reported():
    t = evaluate(OM, TAX, DA, CAPEX, 0.80, WACC, TG, HORIZON, revenue0=1000.0)
    assert t.reference_growth == 0.0
    assert t.as_dict()["verdict_scope"] == "LOCAL_EV_DIRECTION_AT_REFERENCE_G"
    assert t.as_dict()["flips_at_growth"] == t.flips_at_growth


def test_analytic_slope_undefined_cases():
    assert analytic_slope(1000.0, 0.05, OM, TAX, DA, CAPEX, 0.2, 0.02, 0.02,
                          HORIZON) is None          # wacc <= tg
    assert analytic_slope(1000.0, 0.05, OM, TAX, DA, CAPEX, None, WACC, TG,
                          HORIZON) is None          # no marginal NWC
    assert analytic_slope(1000.0, -1.5, OM, TAX, DA, CAPEX, 0.2, WACC, TG,
                          HORIZON) is None          # 1+g <= 0


# --- Boundary acceptance: reference growth, flip position, multi-flip -------

def _fd_slope(g, w, r=WACC, tg=TG, H=HORIZON, h=1e-6, R0=1000.0):
    def ev(x):
        return project_enterprise_value_shaped(
            R0, x, OM, TAX, DA, CAPEX, w, r, tg, H
        ).enterprise_value
    return (ev(g + h) - ev(g - h)) / (2 * h)


def _fd_flip_points(w, lo=-0.05, hi=0.50, n=1200, r=WACC, tg=TG, H=HORIZON):
    """Flip points located from finite differences only — no analytic help."""
    prev = None
    out = []
    for i in range(n + 1):
        g = lo + (hi - lo) * i / n
        d = _fd_slope(g, w, r, tg, H)
        if prev is not None and prev[1] != 0 and d != 0 and (prev[1] > 0) != (d > 0):
            a, b = prev[0], g
            for _ in range(60):
                m = (a + b) / 2
                if (_fd_slope(a, w, r, tg, H) > 0) != (_fd_slope(m, w, r, tg, H) > 0):
                    b = m
                else:
                    a = m
            out.append((a + b) / 2)
        prev = (g, d)
    return out


@pytest.mark.parametrize("g_ref", [-0.02, 0.0, 0.05, 0.10, 0.20, 0.35])
def test_reference_growth_local_derivative(g_ref):
    """P0: the local derivative is correct at any reference growth, not just 0."""
    a = analytic_slope(1000.0, g_ref, OM, TAX, DA, CAPEX, 0.80, WACC, TG, HORIZON)
    f = _fd_slope(g_ref, 0.80)
    assert a is not None
    assert abs(a - f) / max(abs(a), abs(f), 1e-12) < 1e-5
    assert (a > 0) == (f > 0)


@pytest.mark.parametrize("g_ref", [0.0, 0.05, 0.12, 0.30])
def test_reference_growth_reported_in_output(g_ref):
    t = evaluate(OM, TAX, DA, CAPEX, 0.80, WACC, TG, HORIZON,
                 reference_growth=g_ref, revenue0=1000.0)
    assert t.reference_growth == g_ref
    d = t.as_dict()
    assert d["reference_growth"] == g_ref
    assert d["verdict_scope"] == "LOCAL_EV_DIRECTION_AT_REFERENCE_G"
    # local_direction must agree with the analytic slope at that very point
    a = analytic_slope(1000.0, g_ref, OM, TAX, DA, CAPEX, 0.80, WACC, TG, HORIZON)
    if a is not None and a != 0:
        assert d["local_direction"] == ("INCREASING" if a > 0 else "DECREASING")


@pytest.mark.parametrize("w", [0.50, 0.60, 0.70, 0.80, 1.00])
def test_flip_position_matches_finite_difference(w):
    """P0: the *position* of the flip agrees with finite differences.

    Checking the derivative at points is not enough — a sign error that is
    symmetric in g would pass a pointwise test yet put the flip in the wrong
    place. This pins the root itself.
    """
    analytic = sign_over_range(
        1000.0, OM, TAX, DA, CAPEX, w, WACC, TG, HORIZON
    )["flip_points"]
    numeric = _fd_flip_points(w)
    assert len(analytic) == len(numeric) >= 1
    for a, f in zip(analytic, numeric):
        assert abs(a - f) < 1e-4, f"flip position off: analytic={a} fd={f}"


def test_flip_point_is_refined_beyond_grid_step():
    """The reported flip must be a root, not a grid cell boundary."""
    r = sign_over_range(1000.0, OM, TAX, DA, CAPEX, 0.80, WACC, TG, HORIZON,
                        step=0.02)
    assert r["flip_points"], "expected a flip"
    f = r["flip_points"][0]
    # slope at the reported root is ~0 relative to the curve's scale
    d = analytic_slope(1000.0, f, OM, TAX, DA, CAPEX, 0.80, WACC, TG, HORIZON)
    scale = max(abs(analytic_slope(1000.0, g, OM, TAX, DA, CAPEX, 0.80,
                                   WACC, TG, HORIZON))
                for g in (-0.05, 0.0, 0.3, 0.5))
    assert abs(d) / scale < 1e-6
    # and it is not on a 0.02 grid line
    assert abs((f / 0.02) - round(f / 0.02)) > 1e-3


#: A low-margin, high-NWC configuration whose slope has two roots. The second
#: root exists only for negative growth — that is a property of this model, not
#: an artefact of the scan, and the interface must not hide it.
_MULTI = dict(om=0.10, tax=0.55, da=0.01, capex=0.00, w=1.50, horizon=10,
              growth_range=(-0.60, 0.20))


def test_multiple_flip_points_are_all_reported():
    """P1: two sign changes must both survive, not just the first."""
    m = _MULTI
    r = sign_over_range(1000.0, m["om"], m["tax"], m["da"], m["capex"],
                        m["w"], WACC, TG, m["horizon"],
                        growth_range=m["growth_range"], step=0.002)
    assert len(r["flip_points"]) == 2, r["flip_points"]
    a, b = r["flip_points"]
    assert a < b
    # the sign really does alternate across the two roots
    def s(g):
        return analytic_slope(1000.0, g, m["om"], m["tax"], m["da"],
                              m["capex"], m["w"], WACC, TG, m["horizon"])
    s1, s2, s3 = s(a - 0.02), s((a + b) / 2), s(b + 0.02)
    assert (s1 > 0) != (s2 > 0) and (s2 > 0) != (s3 > 0)


def test_multiple_flip_points_yield_multiple_valid_intervals():
    """P1: non-monotone EV must produce more than one valid-direction interval."""
    m = _MULTI
    t = evaluate(m["om"], m["tax"], m["da"], m["capex"], m["w"], WACC, TG,
                 m["horizon"], revenue0=1000.0, growth_range=m["growth_range"])
    assert len(t.flip_points) == 2
    assert len(t.valid_direction_intervals) == 2
    assert any("非单调" in r for r in t.reasons)


def test_evaluate_and_scan_agree_on_flip_points():
    m = _MULTI
    scan = sign_over_range(1000.0, m["om"], m["tax"], m["da"], m["capex"],
                           m["w"], WACC, TG, m["horizon"],
                           growth_range=m["growth_range"], step=0.002)
    t = evaluate(m["om"], m["tax"], m["da"], m["capex"], m["w"], WACC, TG,
                 m["horizon"], revenue0=1000.0, growth_range=m["growth_range"])
    assert t.flip_points == scan["flip_points"]


def test_single_flip_case_reports_one_point_and_one_interval():
    t = evaluate(OM, TAX, DA, CAPEX, 0.80, WACC, TG, HORIZON, revenue0=1000.0)
    assert len(t.flip_points) == 1
    assert len(t.valid_direction_intervals) == 1


@pytest.mark.parametrize("w,target", [(1.40, "lo"), (0.368, "hi")])
def test_flip_near_scan_boundary_is_reported(w, target):
    """P1: a flip just inside either end of the scan must still be found."""
    r = sign_over_range(1000.0, OM, TAX, DA, CAPEX, w, WACC, TG, HORIZON)
    assert r["flip_points"], "flip near boundary was missed"
    f = r["flip_points"][0]
    if target == "lo":
        assert f < 0.0
    else:
        assert f > 0.4
    # and it is a genuine sign change, not a boundary artefact
    lo, hi = f - 0.01, f + 0.01
    s_lo = analytic_slope(1000.0, lo, OM, TAX, DA, CAPEX, w, WACC, TG, HORIZON)
    s_hi = analytic_slope(1000.0, hi, OM, TAX, DA, CAPEX, w, WACC, TG, HORIZON)
    assert (s_lo > 0) != (s_hi > 0)


def test_no_flip_reports_empty_list_not_none():
    r = sign_over_range(1000.0, OM, TAX, DA, CAPEX, 0.05, WACC, TG, HORIZON)
    assert r["flip_points"] == []
    assert r["flips_at_growth"] is None
    assert r["local_direction"] == "INCREASING"


def test_tangent_detector_catches_double_root():
    """The tangent detector must not depend on a sign change.

    No natural engine configuration produces an interior tangent root (checked:
    every near-zero slope minimum sits on the scan boundary), so this exercises
    the detector on a constructed double root instead of pretending otherwise.
    """
    # (g - 0.1)^2 has a double root at 0.1: touches zero, no sign change.
    def touching_slope(g):
        return (g - 0.1) ** 2 + 0.0

    vals = [(g / 1000.0, touching_slope(g / 1000.0)) for g in range(-50, 501)]
    scale = max(abs(d) for _, d in vals)
    tol = 1e-3 * scale
    extrema = [
        gb for (ga, da), (gb, db), (gc, dc)
        in zip(vals, vals[1:], vals[2:])
        if db <= da and db <= dc and (db < da or db < dc) and abs(db) <= tol
    ]
    assert extrema, "detector missed a constructed tangent root"
    assert any(abs(g - 0.1) < 1e-3 for g in extrema)


def test_scan_range_limits_are_respected():
    """A flip outside the requested window must not be reported."""
    inside = sign_over_range(1000.0, OM, TAX, DA, CAPEX, 0.80, WACC, TG,
                             HORIZON, growth_range=(0.0, 0.20))
    assert inside["flip_points"]
    outside = sign_over_range(1000.0, OM, TAX, DA, CAPEX, 0.80, WACC, TG,
                              HORIZON, growth_range=(0.30, 0.50))
    assert outside["flip_points"] == []
