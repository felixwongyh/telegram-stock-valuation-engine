"""P3 — EV's growth sensitivity must be decomposable by cash-flow component.

EV is linear in the additive FCF components (``FCF = NOPAT + D&A − CapEx −
ΔNWC``), so ``EV(g_hi) − EV(g_lo)`` splits *exactly* — no interaction terms, no
order-dependent counterfactuals. That makes "why does EV fall as growth rises"
an auditable arithmetic statement instead of an assertion.
"""
from __future__ import annotations

import math

from forecasts.fcf_projection import (
    attribute_growth_value,
    project_enterprise_value_shaped,
)

_BASE = dict(
    base_revenue=1000.0,
    operating_margin=0.20,
    tax_rate=0.21,
    da_ratio=0.05,
    capex_ratio=0.06,
    nwc_marginal_ratio=0.10,
    wacc=0.09,
    terminal_growth=0.02,
    horizon=5,
)


def _direct(g_lo, g_hi):
    def ev(g):
        return project_enterprise_value_shaped(
            _BASE["base_revenue"], g, _BASE["operating_margin"],
            _BASE["tax_rate"], _BASE["da_ratio"], _BASE["capex_ratio"],
            _BASE["nwc_marginal_ratio"], _BASE["wacc"],
            _BASE["terminal_growth"], _BASE["horizon"],
        ).enterprise_value

    return ev(g_hi) - ev(g_lo)


class TestAttributionIsExact:
    def test_total_reproduces_direct_ev_difference(self):
        attr = attribute_growth_value(**_BASE, g_lo=0.0, g_hi=0.10)
        assert attr.total == _direct(0.0, 0.10)

    def test_total_is_the_sum_of_components(self):
        attr = attribute_growth_value(**_BASE, g_lo=0.0, g_hi=0.10)
        component_sum = (
            attr.nopat + attr.da + attr.capex + attr.nwc + attr.terminal
        )
        assert math.isclose(attr.total, component_sum, rel_tol=1e-12, abs_tol=1e-6)

    def test_capex_and_nwc_reduce_value(self):
        # Higher growth means more CapEx and more working capital, both of which
        # subtract from EV. Their attribution must be negative, not positive.
        attr = attribute_growth_value(**_BASE, g_lo=0.0, g_hi=0.10)
        assert attr.capex < 0
        assert attr.nwc < 0

    def test_nopat_increases_with_growth(self):
        attr = attribute_growth_value(**_BASE, g_lo=0.0, g_hi=0.10)
        assert attr.nopat > 0

    def test_zero_growth_change_gives_zero_total(self):
        attr = attribute_growth_value(**_BASE, g_lo=0.05, g_hi=0.05)
        assert abs(attr.total) < 1e-6

    def test_as_dict_round_trips_all_fields(self):
        attr = attribute_growth_value(**_BASE, g_lo=0.0, g_hi=0.10)
        d = attr.as_dict()
        for key in ("g_lo", "g_hi", "total", "nopat", "da", "capex", "nwc",
                    "terminal", "cancellation_ratio"):
            assert key in d


class TestCancellationRatio:
    def test_pure_growth_case_has_low_cancellation(self):
        # Without CapEx or NWC there is nothing to offset NOPAT + TV growth.
        attr = attribute_growth_value(
            **{**_BASE, "capex_ratio": 0.0, "nwc_marginal_ratio": 0.0},
            g_lo=0.0, g_hi=0.10,
        )
        assert attr.cancellation_ratio < 2.0

    def test_heavy_capex_case_has_high_cancellation(self):
        # CapEx large enough to nearly offset the operating gains: the total is
        # a small residual of big opposing parts, so its sign is fragile.
        attr = attribute_growth_value(
            **{**_BASE, "capex_ratio": 0.20, "nwc_marginal_ratio": 0.20},
            g_lo=0.0, g_hi=0.10,
        )
        assert attr.cancellation_ratio > 2.0

    def test_cancellation_is_infinite_when_total_is_zero(self):
        # Symmetric setup: find a capex that makes dEV ≈ 0, then the ratio blows
        # up — the numeric signature of a sign that cannot be trusted.
        lo, hi = 0.0, 0.10
        best = None
        for capex in [0.05 + 0.001 * i for i in range(400)]:
            attr = attribute_growth_value(
                **{**_BASE, "capex_ratio": capex}, g_lo=lo, g_hi=hi
            )
            if best is None or abs(attr.total) < abs(best.total):
                best = attr
        assert best is not None
        assert best.cancellation_ratio > 5.0
