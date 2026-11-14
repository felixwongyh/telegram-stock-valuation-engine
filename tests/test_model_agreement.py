"""
tests/test_model_agreement.py — quality-weighted median (Session #19, ADR-033).

Regression target: `_weighted_median()` must use the standard *midpoint*
definition (average of lower and upper weighted medians) so that equal weights
collapse **exactly** to the ordinary median. The prior implementation returned
the first value whose cumulative weight reached half the total, which for equal
weights and an even count returned the (n/2)-th value instead of
mean(values[n/2-1], values[n/2]) — the AAPL 176.12 vs 165.24 mismatch.
"""
from __future__ import annotations

import pytest

from analysis.model_agreement import ModelAgreementAnalyzer
from statistics import median


WM = ModelAgreementAnalyzer._weighted_median


class TestWeightedMedianEqualWeights:
    """Equal weights ⇒ weighted median MUST equal the ordinary median."""

    def test_even_count_equal_weights_matches_plain_median(self):
        values = {"a": 100.0, "b": 120.0, "c": 165.24, "d": 176.12, "e": 200.0, "f": 220.0}
        weights = {k: 1.0 for k in values}
        got = WM(values, weights)
        assert got == pytest.approx(median(list(values.values())))  # (165.24 + 176.12)/2
        assert got == pytest.approx(170.68)
        # The old code returned the 3rd value (165.24); the midpoint is 170.68.
        assert got != 165.24

    def test_odd_count_equal_weights_matches_plain_median(self):
        values = {"a": 10.0, "b": 20.0, "c": 30.0, "d": 40.0, "e": 50.0}
        weights = {k: 1.0 for k in values}
        assert WM(values, weights) == pytest.approx(30.0)

    def test_two_equal_weights_averages_both(self):
        assert WM({"a": 10.0, "b": 20.0}, {"a": 1.0, "b": 1.0}) == pytest.approx(15.0)

    def test_single_value_returns_itself(self):
        assert WM({"only": 42.0}, {"only": 1.0}) == pytest.approx(42.0)

    def test_unsorted_input_is_sorted_internally(self):
        values = {"a": 50.0, "b": 10.0, "c": 30.0, "d": 40.0}
        weights = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}
        assert WM(values, weights) == pytest.approx(35.0)  # median(10,30,40,50)


class TestWeightedMedianUnequalWeights:
    """Unequal weights: heavy value dominates; no spurious averaging."""

    def test_dominant_heavy_weight_selects_its_value(self):
        # weight 5 on 200 far exceeds the rest → median sits at 200.
        values = {"a": 100.0, "b": 200.0, "c": 300.0}
        weights = {"a": 1.0, "b": 5.0, "c": 1.0}
        assert WM(values, weights) == pytest.approx(200.0)

    def test_exact_half_tie_averages_adjacent_values(self):
        # total = 4, half = 2 → cumulative hits 2.0 exactly at the 2nd value.
        values = {"a": 10.0, "b": 20.0, "c": 30.0, "d": 40.0}
        weights = {"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}
        assert WM(values, weights) == pytest.approx(25.0)  # (20+30)/2

    def test_uneven_weights_no_exact_tie(self):
        # total = 1.0+3.0+1.0 = 5 → half = 2.5, crossed at b (cum=4).
        values = {"a": 10.0, "b": 20.0, "c": 30.0}
        weights = {"a": 1.0, "b": 3.0, "c": 1.0}
        assert WM(values, weights) == pytest.approx(20.0)

    def test_lopsided_low_weight_below_half(self):
        # total = 1+1+8 = 10, half = 5; cum reaches 5 only at the heaviest value.
        values = {"a": 10.0, "b": 20.0, "c": 30.0}
        weights = {"a": 1.0, "b": 1.0, "c": 8.0}
        assert WM(values, weights) == pytest.approx(30.0)


class TestWeightedMedianZeroWeights:
    """Zero-weight models must be excluded from the statistic."""

    def test_single_zero_weight_ignored(self):
        values = {"a": 10.0, "b": 20.0, "c": 30.0}
        weights = {"a": 0.0, "b": 1.0, "c": 1.0}
        # Effectively median over {20, 30} = 25.
        assert WM(values, weights) == pytest.approx(25.0)

    def test_all_zero_weights_returns_none(self):
        values = {"a": 10.0, "b": 20.0}
        weights = {"a": 0.0, "b": 0.0}
        assert WM(values, weights) is None

    def test_negative_weight_clamped_to_zero(self):
        values = {"a": 10.0, "b": 20.0}
        weights = {"a": -5.0, "b": 1.0}
        assert WM(values, weights) == pytest.approx(20.0)

    def test_missing_weight_defaults_to_one(self):
        values = {"a": 10.0, "b": 20.0}
        # Only "a" is present in weights; "b" must default to 1.0.
        assert WM(values, weights={"a": 1.0}) == pytest.approx(15.0)


class TestWeightedMedianEdgeCases:
    def test_empty_values_returns_none(self):
        assert WM({}, {}) is None

    def test_zero_total_with_missing_weights_returns_none(self):
        # weights present but all zero after clamping.
        assert WM({"a": 1.0, "b": 2.0}, {"a": 0.0, "b": 0.0}) is None

    def test_equal_weights_via_missing_dict_matches_median(self):
        # No weights dict entries at all → all default 1.0 → plain median.
        values = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}
        assert WM(values, {}) == pytest.approx(2.5)
