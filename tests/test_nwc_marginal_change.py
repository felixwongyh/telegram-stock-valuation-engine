"""§10 M07: ``forecast_nwc_change`` is a marginal relation, not a level.

The function converts a revenue *change* into the working-capital *change* that
funds it. It appears in three projection paths, so an error here shifts every
FCF and every implied growth, yet no test called it directly - the existing
NWC tests exercise the *estimators* that produce ``marginal_ratio``, not the
one-line consumer. These tests pin the consumer's contract.
"""

from __future__ import annotations

import pytest

from forecasts.nwc_utils import forecast_nwc_change


def test_it_scales_the_revenue_change():
    """NWC investment is proportional to the change in revenue."""
    assert forecast_nwc_change(100.0, 0.10) == pytest.approx(10.0)
    assert forecast_nwc_change(-40.0, 0.25) == pytest.approx(-10.0)


def test_zero_growth_invests_nothing():
    """No revenue growth means no incremental working capital."""
    assert forecast_nwc_change(0.0, 0.30) == pytest.approx(0.0)


def test_shrinking_revenue_releases_cash():
    """A marginal ratio is a slope, so it must preserve the sign of the change.

    A level-style error (``ratio × revenue``) would return a positive number
    here and hide the cash release.
    """
    assert forecast_nwc_change(-100.0, 0.12) < 0


def test_it_is_linear_in_both_arguments():
    """Doubling either input doubles the result; there is no constant term."""
    base = forecast_nwc_change(50.0, 0.08)
    assert forecast_nwc_change(100.0, 0.08) == pytest.approx(2 * base)
    assert forecast_nwc_change(50.0, 0.16) == pytest.approx(2 * base)


def test_magnitude_matches_the_stated_ratio():
    """The ratio is the fraction of new revenue tied up in NWC, verbatim."""
    delta, ratio = 250.0, 0.06
    assert forecast_nwc_change(delta, ratio) == pytest.approx(delta * ratio)
