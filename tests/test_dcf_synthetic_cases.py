"""§5 three canonical synthetic DCF cases, each checked against closed form.

The point of these is not "the model runs" but "the model reproduces arithmetic
that can be verified on paper". A model that drifts by a rounding error on a
case with a known answer has a bug the 50-ticker run cannot reveal, because real
companies have no ground truth.

Case 1 - constant growth: FCF grows at g forever, EV = FCF1 / (wacc - g).
Case 2 - zero growth: a perpetuity, EV = FCF / wacc.
Case 3 - value trap: FCF never turns positive, so the terminal value must be
          suppressed rather than fabricated from a negative number.
"""

from __future__ import annotations

import pytest

from forecasts.fcf_projection import gordon_terminal_value, project_enterprise_value

WACC = 0.09


def test_case1_constant_growth_matches_gordon_closed_form() -> None:
    """Case 1: one explicit year then a Gordon tail equals the Gordon formula.

    With ``last_fcf`` the terminal-year FCF and growth ``g``, the value at the
    valuation date is ``last_fcf * (1 + g) / (wacc - g)``. Checked to 1e-6
    relative, the §5 arithmetic bar.
    """
    last_fcf, g, horizon = 1_000.0, 0.03, 1
    r = gordon_terminal_value(last_fcf, WACC, g, horizon)
    expected_tv = last_fcf * (1 + g) / (WACC - g)
    expected_pv = expected_tv / (1 + WACC) ** horizon

    assert r.suppressed is False
    assert r.terminal_value == pytest.approx(expected_tv, rel=1e-6)
    assert r.pv_terminal_value == pytest.approx(expected_pv, rel=1e-6)


def test_case2_zero_growth_is_a_perpetuity() -> None:
    """Case 2: g = 0 must collapse to FCF / wacc, with no growth leaking in."""
    fcf = 500.0
    r = gordon_terminal_value(fcf, WACC, 0.0, 1)
    assert r.suppressed is False
    assert r.terminal_value == pytest.approx(fcf / WACC, rel=1e-6)


def test_case2b_zero_growth_projection_equals_discounted_perpetuity() -> None:
    """A flat projection with g=0 must agree with the closed-form perpetuity.

    This exercises the full projection path (explicit years + terminal), not
    just the terminal-value helper, so a discounting error shows up.
    """
    base_rev, horizon, wacc = 1_000.0, 5, WACC
    # margin 10%, no tax/d&a/capex/nwc -> FCF == 10% of revenue every year
    res = project_enterprise_value(
        base_revenue=base_rev, revenue_cagr=0.0, operating_margin=0.10,
        tax_rate=0.0, da_ratio=0.0, capex_ratio=0.0, nwc_marginal_ratio=0.0,
        wacc=wacc, terminal_growth=0.0, horizon=horizon,
    )
    fcf = base_rev * 0.10
    # EV = sum(FCF / 1.09^t, t=1..H) + (FCF / wacc) / 1.09^H
    explicit = sum(fcf / (1 + wacc) ** t for t in range(1, horizon + 1))
    terminal_pv = (fcf / wacc) / (1 + wacc) ** horizon
    assert res.enterprise_value == pytest.approx(explicit + terminal_pv, rel=1e-6)


def test_case3_value_trap_suppresses_terminal_value() -> None:
    """Case 3: a permanent cash burner must not receive a terminal value.

    A negative terminal FCF run through Gordon produces a *negative* TV; adding
    it would quietly subtract value, and flipping the sign would invent value
    from nothing. Both are forbidden, so the TV is suppressed to zero and EV is
    the explicit-period value only.
    """
    res = project_enterprise_value(
        base_revenue=1_000.0, revenue_cagr=0.05, operating_margin=-0.30,
        tax_rate=0.21, da_ratio=0.02, capex_ratio=0.60,
        nwc_marginal_ratio=0.02, wacc=WACC, terminal_growth=0.02, horizon=5,
    )
    assert res.terminal_fcf_negative is True
    assert res.pv_terminal == 0.0
    assert res.enterprise_value == pytest.approx(res.pv_explicit, rel=1e-9)


def test_case3_negative_fcf_never_becomes_a_positive_terminal() -> None:
    """Directly: Gordon on a negative FCF must return zero, never a sign flip."""
    for bad in (-1.0, -1e9, 0.0):
        r = gordon_terminal_value(bad, WACC, 0.02, 5)
        assert r.suppressed is True
        assert r.terminal_value == 0.0
        assert r.pv_terminal_value == 0.0
