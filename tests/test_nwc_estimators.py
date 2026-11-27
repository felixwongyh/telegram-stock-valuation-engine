"""Tests for the three-estimator NWC framework.

The properties under test are the ones that keep the defect from returning:
dimensions are never conflated, a robust slope ignores one bad year, the
intensity→marginal conversion refuses to divide by a tiny growth rate, and
conflicting estimators are reported as conflicting rather than averaged away.
"""
import statistics

import pytest

from forecasts.nwc_estimators import (
    DIM_INTENSITY,
    DIM_LEVEL,
    DIM_MARGINAL,
    MIN_GROWTH_FOR_PROXY,
    balance_sheet_nwc_ratio,
    marginal_from_intensity,
    nwc_investment_intensity,
    operating_nwc_from_balance_sheet,
    reconcile,
    robust_marginal_nwc,
)


class TestOperatingNwcFromBalanceSheet:
    def test_standard_components(self):
        rec = {
            "Accounts Receivable": 100.0,
            "Inventory": 50.0,
            "Other Current Assets": 10.0,
            "Accounts Payable": 40.0,
            "Current Deferred Revenue": 20.0,
            "Other Current Liabilities": 5.0,
        }
        nwc, missing = operating_nwc_from_balance_sheet(rec)
        assert nwc == pytest.approx(160.0 - 65.0)
        assert missing == []

    def test_missing_ar_is_not_zero_filled(self):
        """Absent AR must yield None, never a fabricated level."""
        rec = {"Accounts Payable": 40.0, "Inventory": 50.0}
        nwc, missing = operating_nwc_from_balance_sheet(rec)
        assert nwc is None
        assert "Accounts Receivable" in missing

    def test_missing_ap_is_not_zero_filled(self):
        rec = {"Accounts Receivable": 40.0}
        nwc, missing = operating_nwc_from_balance_sheet(rec)
        assert nwc is None
        assert "Accounts Payable" in missing

    def test_cash_and_debt_are_excluded(self):
        """Financing items must not move operating NWC."""
        base = {"Accounts Receivable": 100.0, "Accounts Payable": 100.0}
        with_cash = dict(base, **{"Cash And Cash Equivalents": 9e9,
                                  "Total Debt": 5e9})
        assert operating_nwc_from_balance_sheet(base)[0] == \
            operating_nwc_from_balance_sheet(with_cash)[0]


class TestBalanceSheetRatio:
    def test_ratio_uses_matching_periods(self):
        bs = [
            {"period_end": "2024", "Accounts Receivable": 120.0,
             "Accounts Payable": 20.0},
            {"period_end": "2023", "Accounts Receivable": 100.0,
             "Accounts Payable": 0.0},
        ]
        rev = {"2024": 1000.0, "2023": 1000.0}
        est = balance_sheet_nwc_ratio(bs, rev)
        assert est.value == pytest.approx((0.10 + 0.10) / 2)
        assert est.dimension == DIM_LEVEL
        assert est.n_observations == 2

    def test_period_without_revenue_is_skipped(self):
        bs = [{"period_end": "2024", "Accounts Receivable": 100.0,
               "Accounts Payable": 0.0}]
        est = balance_sheet_nwc_ratio(bs, {})
        assert est.value is None
        assert est.n_observations == 0

    def test_few_periods_flagged(self):
        bs = [{"period_end": "2024", "Accounts Receivable": 100.0,
               "Accounts Payable": 0.0}]
        est = balance_sheet_nwc_ratio(bs, {"2024": 1000.0})
        assert any("only 1 usable" in n for n in est.notes)


class TestInvestmentIntensity:
    def test_mean_of_dnwc_over_revenue(self):
        est = nwc_investment_intensity(
            {"2024": 20.0, "2023": 10.0}, {"2024": 1000.0, "2023": 1000.0}
        )
        assert est.value == pytest.approx(0.015)
        assert est.dimension == DIM_INTENSITY

    def test_zero_revenue_period_skipped(self):
        est = nwc_investment_intensity({"2024": 20.0}, {"2024": 0.0})
        assert est.value is None


class TestRobustMarginal:
    def test_exact_linear_series(self):
        # ΔNWC = 0.2 * ΔRevenue exactly: Δrev is 200 each year, ΔNWC 40 each year
        series = [("2024", 1400.0, 40.0), ("2023", 1200.0, 40.0),
                  ("2022", 1000.0, 0.0)]
        est = robust_marginal_nwc(series)
        assert est.value == pytest.approx(0.2)
        assert est.dimension == DIM_MARGINAL

    def test_one_bad_year_does_not_dominate(self):
        """A single extreme pair must not set a median-based coefficient."""
        series = [
            ("2024", 1600.0, 40.0),
            ("2023", 1400.0, 40.0),
            ("2022", 1200.0, 900.0),   # outlier: 4.5x the marginal rate
            ("2021", 1000.0, 0.0),
        ]
        est = robust_marginal_nwc(series)
        assert est.n_observations == 3
        assert est.value == pytest.approx(0.2)   # median of {0.2, 0.2, 4.5}
        assert est.value < 1.0

    def test_near_zero_revenue_move_dropped(self):
        series = [("2024", 1000.5, 500.0), ("2023", 1000.0, 0.0)]
        est = robust_marginal_nwc(series)
        assert est.n_near_zero_rev == 1
        assert est.value is None

    def test_revenue_decline_counted(self):
        series = [("2024", 900.0, 10.0), ("2023", 1000.0, 0.0)]
        est = robust_marginal_nwc(series)
        assert est.n_revenue_decline == 1
        assert any("declining revenue" in n for n in est.notes)

    def test_below_three_pairs_flagged(self):
        series = [("2024", 1100.0, 20.0), ("2023", 1000.0, 0.0)]
        est = robust_marginal_nwc(series)
        assert est.n_observations == 1
        assert any("3-pair floor" in n for n in est.notes)

    def test_median_theilsen_huber_reported(self):
        series = [("2024", 1400.0, 40.0), ("2023", 1200.0, 40.0),
                  ("2022", 1000.0, 0.0)]
        est = robust_marginal_nwc(series)
        assert est.samples == pytest.approx([0.2, 0.2])
        assert est.dispersion == pytest.approx(0.0)


class TestIntensityConversion:
    def test_identity_when_growth_matches(self):
        # intensity 2%, growth 10% -> marginal 20%
        assert marginal_from_intensity(0.02, 0.10) == pytest.approx(0.2)

    def test_refuses_tiny_growth(self):
        """CEG: 23.5% intensity at 1.5% growth would give a 1598% ratio."""
        assert marginal_from_intensity(0.235, 0.015) is None

    def test_refuses_nonpositive_growth(self):
        assert marginal_from_intensity(0.05, 0.0) is None
        assert marginal_from_intensity(0.05, -0.02) is None

    def test_threshold_is_respected(self):
        assert marginal_from_intensity(0.05, MIN_GROWTH_FOR_PROXY) is not None
        assert marginal_from_intensity(0.05, MIN_GROWTH_FOR_PROXY * 0.99) is None

    def test_none_inputs(self):
        assert marginal_from_intensity(None, 0.1) is None
        assert marginal_from_intensity(0.05, None) is None


class TestReconcile:
    def _est(self, **kw):
        from forecasts.nwc_estimators import NWCEstimate
        defaults = dict(name="x", dimension=DIM_MARGINAL, value=0.2,
                        method="m", n_observations=4, samples=[0.2])
        defaults.update(kw)
        return NWCEstimate(**defaults)

    def test_agreement_is_not_conflict(self):
        # intensity 2% at 10% growth -> proxy 20%, matching the robust 21%
        rec = reconcile(self._est(), self._est(dimension=DIM_INTENSITY,
                                               value=0.02),
                        self._est(value=0.21), 0.10)
        assert rec["estimates_conflict"] is False

    def test_sign_disagreement_is_conflict(self):
        rec = reconcile(self._est(), self._est(dimension=DIM_INTENSITY,
                                               value=0.02),
                        self._est(value=-0.2), 0.10)
        assert rec["estimates_conflict"] is True

    def test_large_spread_is_conflict(self):
        # proxy 20% vs robust 1%: same sign, but far apart
        rec = reconcile(self._est(), self._est(dimension=DIM_INTENSITY,
                                               value=0.02),
                        self._est(value=0.01), 0.10)
        assert rec["estimates_conflict"] is True

    def test_level_never_enters_marginal_comparison(self):
        """A level ratio must not be compared against a marginal one."""
        rec = reconcile(self._est(value=0.95),
                        self._est(dimension=DIM_INTENSITY, value=0.02),
                        self._est(value=0.2), 0.10)
        assert rec["estimates_conflict"] is False
        assert rec["level"]["value"] == 0.95

    def test_refusal_reason_recorded(self):
        rec = reconcile(self._est(), self._est(dimension=DIM_INTENSITY,
                                               value=0.235),
                        self._est(value=None), 0.015)
        assert rec["intensity_proxy_marginal"] is None
        assert rec["intensity_proxy_refused_reason"]

    def test_usable_estimates_exclude_none(self):
        rec = reconcile(self._est(), self._est(dimension=DIM_INTENSITY,
                                               value=0.02),
                        self._est(value=None), 0.0)
        assert "robust_marginal" not in rec["usable_marginal_estimates"]

    def test_dispersion_and_samples_survive_serialisation(self):
        rec = reconcile(self._est(), self._est(dimension=DIM_INTENSITY,
                                               value=0.02),
                        self._est(samples=[0.1, 0.3]), 0.10)
        assert rec["robust_marginal"]["dispersion"] == pytest.approx(0.2)
        assert len(rec["robust_marginal"]["samples"]) == 2


def test_dimension_labels_are_distinct():
    assert len({DIM_LEVEL, DIM_INTENSITY, DIM_MARGINAL}) == 3


def test_median_used_not_mean():
    """Sanity: the documented estimator is a median, not a mean."""
    series = [("2024", 1600.0, 40.0), ("2023", 1400.0, 40.0),
              ("2022", 1200.0, 900.0), ("2021", 1000.0, 0.0)]
    est = robust_marginal_nwc(series)
    assert est.value == statistics.median(est.samples)
    assert est.value != statistics.fmean(est.samples)
