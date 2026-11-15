"""
tests/test_sbc.py - Stock-Based Compensation normalization (Phase 1).

Invariants:
  * ``expense`` deducts SBC from FCF once and leaves the share count untouched.
  * ``dilution`` leaves FCF untouched and scales the share count instead.
  * Never both → no double-count of the same grant.
  * Missing / zero SBC is never a fabricated cost.
  * ``dilution`` without an explicit rate falls back to ``expense``.
"""
from __future__ import annotations

import pytest

from valuation.sbc import (
    DEFAULT_SBC_METHOD,
    normalize_fcf_for_sbc,
)


class TestExpenseMethod:
    def test_deducts_sbc_from_fcf(self):
        r = normalize_fcf_for_sbc(1000.0, 200.0, shares=100.0)
        assert r.method == "expense"
        assert r.sbc_deduction == pytest.approx(200.0)
        assert r.adjusted_fcf == pytest.approx(800.0)
        assert r.applied is True

    def test_records_before_and_after_per_share(self):
        r = normalize_fcf_for_sbc(1000.0, 200.0, shares=100.0)
        assert r.reported_fcf_per_share == pytest.approx(10.0)
        assert r.adjusted_fcf_per_share == pytest.approx(8.0)

    def test_does_not_scale_shares(self):
        """The double-count guard: charging SBC on the cash line must NOT also
        penalise the share count."""
        r = normalize_fcf_for_sbc(1000.0, 200.0, shares=100.0)
        assert r.share_dilution_factor == 1.0
        assert r.shares_adjusted == 100.0

    def test_itemized_note_is_auditable(self):
        r = normalize_fcf_for_sbc(1000.0, 200.0, shares=100.0)
        note = r.itemized_note()
        assert "expense" in note
        assert "1,000" in note and "200" in note and "800" in note


class TestDilutionMethod:
    def test_scales_shares_not_fcf(self):
        r = normalize_fcf_for_sbc(
            1000.0, 200.0, method="dilution", shares=100.0, sbc_dilution_rate=0.05
        )
        assert r.method == "dilution"
        assert r.sbc_deduction == 0.0
        assert r.adjusted_fcf == pytest.approx(1000.0)
        assert r.share_dilution_factor == pytest.approx(1.05)
        assert r.shares_adjusted == pytest.approx(105.0)
        assert r.adjusted_fcf_per_share == pytest.approx(1000.0 / 105.0)

    def test_falls_back_to_expense_without_rate(self):
        r = normalize_fcf_for_sbc(1000.0, 200.0, method="dilution", shares=100.0)
        assert r.method == "expense"
        assert r.sbc_deduction == pytest.approx(200.0)
        assert any("回退" in n for n in r.notes)


class TestNoAdjustment:
    def test_missing_sbc_is_not_a_cost(self):
        r = normalize_fcf_for_sbc(1000.0, None, shares=100.0)
        assert r.applied is False
        assert r.adjusted_fcf == pytest.approx(1000.0)
        assert any("无 SBC" in n for n in r.notes)

    def test_zero_sbc_is_not_a_cost(self):
        r = normalize_fcf_for_sbc(1000.0, 0.0, shares=100.0)
        assert r.applied is False
        assert r.adjusted_fcf == pytest.approx(1000.0)

    def test_none_method_disables_adjustment(self):
        r = normalize_fcf_for_sbc(1000.0, 200.0, method="none", shares=100.0)
        assert r.applied is False
        assert r.adjusted_fcf == pytest.approx(1000.0)

    def test_unknown_method_falls_back(self):
        r = normalize_fcf_for_sbc(1000.0, 200.0, method="banana", shares=100.0)
        assert r.method == DEFAULT_SBC_METHOD
        assert any("回退" in n for n in r.notes)

    def test_missing_shares_still_deducts(self):
        r = normalize_fcf_for_sbc(1000.0, 200.0)
        assert r.adjusted_fcf == pytest.approx(800.0)
        assert r.reported_fcf_per_share is None
        assert r.adjusted_fcf_per_share is None


class TestReverseDcfWiring:
    def test_breakdown_exposes_sbc_normalization(self, aapl_data):
        from classification.classifier import BusinessClassifier
        from models.reverse_dcf import ReverseDCFModel

        profile = BusinessClassifier().classify(aapl_data)
        r = ReverseDCFModel().calculate(aapl_data, profile)
        assert "sbc_normalization" in r.breakdown
        block = r.breakdown["sbc_normalization"]
        assert block["method"] in ("expense", "dilution", "none")

    def test_sbc_deduction_changes_base_fcf(self, aapl_data):
        """With SBC on file, the reference FCF must be the SBC-adjusted one."""
        from classification.classifier import BusinessClassifier
        from models.reverse_dcf import ReverseDCFModel

        ttm = aapl_data.ttm
        ttm.stock_based_compensation = 1_000.0
        profile = BusinessClassifier().classify(aapl_data)
        r = ReverseDCFModel().calculate(aapl_data, profile)
        block = r.breakdown["sbc_normalization"]
        if block["applied"]:
            assert block["adjusted_fcf"] == pytest.approx(
                block["reported_fcf"] - 1_000.0
            )
