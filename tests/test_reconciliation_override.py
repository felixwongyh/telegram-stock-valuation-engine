"""
tests/test_reconciliation_override.py - Reverse-validation (provider override) tests

Covers the write-side of the reconciliation layer (`apply_overrides`): a provider
field whose deviation from the internal recomputation exceeds 25% must be
replaced (not merely flagged), while the per-share anchor (market cap / share
count) is protected by a guard.
"""
from __future__ import annotations

import copy

from data.reconciliation import apply_overrides, reconcile

_OVERRIDE_TOL = 0.25


def _fresh(synthetic_provider, ticker="AAPL"):
    """Build a mutable FinancialData (no validation → no auto-override)."""
    return copy.deepcopy(synthetic_provider.get_financial_data(ticker))


class TestProviderOverride:
    def test_ev_override_replaces_contaminated_field(self, synthetic_provider):
        data = _fresh(synthetic_provider)
        mkt = data.market
        internal_ev = mkt.market_cap + mkt.total_debt - mkt.cash_and_equivalents
        # Inflate the provider EV by +100% (> 25% tolerance)
        mkt.enterprise_value = internal_ev * 2.0

        report = reconcile(data)
        log = apply_overrides(data, report)

        assert any(r.field.startswith("企业价值") and r.applied for r in log.records)
        assert abs(mkt.enterprise_value - internal_ev) < 1e-6
        assert log.n_applied >= 1

    def test_small_deviation_is_not_overridden(self, synthetic_provider):
        data = _fresh(synthetic_provider)
        mkt = data.market
        internal_ev = mkt.market_cap + mkt.total_debt - mkt.cash_and_equivalents
        # +10% deviation: flagged (tolerance 5%) but below the 25% override bar
        mkt.enterprise_value = internal_ev * 1.10

        report = reconcile(data)
        log = apply_overrides(data, report)

        assert not any(r.field.startswith("企业价值") for r in log.records)
        assert abs(mkt.enterprise_value - internal_ev * 1.10) < 1e-6

    def test_share_guard_annotates_when_identity_holds(self, synthetic_provider):
        data = _fresh(synthetic_provider)
        mkt = data.market
        orig_shares = mkt.shares_outstanding
        # Annual shares 60% higher than the market share count → mismatch, but
        # price × shares still equals market cap (identity intact) → annotate only.
        data.annual_income[0].shares_outstanding = orig_shares * 1.6

        report = reconcile(data)
        log = apply_overrides(data, report)

        shares_recs = [r for r in log.records if r.field == "流通股数"]
        assert shares_recs and shares_recs[0].applied is False
        assert abs(mkt.shares_outstanding - orig_shares) < 1e-6

    def test_share_guard_reanchors_when_identity_broken(self, synthetic_provider):
        data = _fresh(synthetic_provider)
        mkt = data.market
        orig_shares = mkt.shares_outstanding
        # Break the market-cap identity AND deviate from annual shares.
        mkt.shares_outstanding = orig_shares * 2.0
        data.annual_income[0].shares_outstanding = orig_shares

        report = reconcile(data)
        log = apply_overrides(data, report)

        shares_recs = [r for r in log.records if r.field == "流通股数"]
        assert shares_recs and shares_recs[0].applied is True
        # Re-anchored to market_cap / price == original share count
        assert abs(mkt.shares_outstanding - orig_shares) / orig_shares < 0.01

    def test_override_log_renders(self, synthetic_provider):
        data = _fresh(synthetic_provider)
        mkt = data.market
        internal_ev = mkt.market_cap + mkt.total_debt - mkt.cash_and_equivalents
        mkt.enterprise_value = internal_ev * 2.0

        report = reconcile(data)
        log = apply_overrides(data, report)
        lines = log.to_lines(lambda v, unit="": f"{v:.2f}" if v is not None else "N/A")

        assert any("对账自动修正" in ln for ln in lines)
        assert any("✅" in ln for ln in lines)


class TestOverrideWiring:
    def test_validator_attaches_override_log(self, synthetic_provider):
        from data import DataValidator, FinancialNormalizer

        data = _fresh(synthetic_provider)
        mkt = data.market
        internal_ev = mkt.market_cap + mkt.total_debt - mkt.cash_and_equivalents
        mkt.enterprise_value = internal_ev * 2.0

        data = FinancialNormalizer.normalize_all(data)
        data = DataValidator.validate(data)

        assert getattr(data, "reconciliation_overrides", None) is not None
        assert data.reconciliation_overrides.n_applied >= 1
        assert abs(data.market.enterprise_value - internal_ev) / abs(internal_ev) < 0.01
