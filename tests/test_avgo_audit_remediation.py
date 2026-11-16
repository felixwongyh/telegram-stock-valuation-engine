"""
tests/test_avgo_audit_remediation.py — AVGO Audit Remediation Phase 1.

Regression tests for the three P0 defects surfaced by the AVGO report
(2026-11-15 06:27 UTC):

  * P0-1  Equity Bridge missing-data safety — an absent EV / debt / cash input
          must never be silently converted to a fabricated ``0``.
  * P0-2  P/E numerator/denominator consistency — the per-share value must be
          rebuilt on the SAME (TTM) share-count basis that EPS is built from,
          never multiplied by an unrelated market count.
  * P0-3  Share-count evidence gate — market-implied / filing-period-end /
          diluted-weighted-average counts are compared as *independent*
          evidence; an over-tolerance disagreement downgrades the per-share
          conclusion while the EV-level result stays valid.

Tests 1–4 (missing EV, missing debt/cash, verified zero net debt, complex
bridge) are pinned in ``tests/test_equity_bridge.py``; this file adds the
remaining P0-2/P0-3 regressions plus an explicit model-agreement / Golden
Baseline compatibility check. No Golden Baseline is regenerated here.
"""
from __future__ import annotations

import pytest

from analysis.model_agreement import ModelAgreementAnalyzer
from config import SolverStatus
from data import DataValidator, FinancialNormalizer, SyntheticDataProvider
from data.models import FinancialData, FinancialStatement, MarketData
from data.reconciliation import share_count_evidence
from models.base import ShareCountBasis, ValuationResult, make_share_count
from models.multiples import MultiplesModel
from reporting.verdict_intuition import build_valuation_verdict
from valuation.equity_bridge import (
    EB_STATUS_INCOMPLETE,
    EB_STATUS_OK,
    EB_STATUS_UNAVAILABLE,
    enterprise_to_equity,
)

_TOL_SHARES = 0.25


def _fresh(ticker: str = "AAPL"):
    """A validated FinancialData + profile, isolated from the session fixtures."""
    from classification.classifier import BusinessClassifier

    data = SyntheticDataProvider().get_financial_data(ticker)
    data = FinancialNormalizer.normalize_all(data)
    data = DataValidator.validate(data)
    profile = BusinessClassifier().classify(data)
    return data, profile


# ===========================================================================
# P0-1 — no silent missing-value → zero (bridge end-to-end safety)
# ===========================================================================
class TestP01EquityBridgeMissingData:
    def test_missing_ev_never_becomes_a_zero_equity_value(self):
        b = enterprise_to_equity(None, MarketData(total_debt=1000.0, cash_and_equivalents=200.0))
        assert b.equity_value is None
        assert b.status == EB_STATUS_UNAVAILABLE
        assert b.is_reliable() is False
        assert "enterprise_value" in b.missing_inputs

    def test_missing_debt_and_cash_is_incomplete_not_verified_zero(self):
        b = enterprise_to_equity(5000.0, MarketData())
        assert b.net_debt_verified is False
        assert b.status == EB_STATUS_INCOMPLETE
        assert b.missing_inputs == ["net_debt"]

    def test_verified_zero_net_debt_stays_ok(self):
        b = enterprise_to_equity(5000.0, MarketData(total_debt=500.0, cash_and_equivalents=500.0))
        assert b.net_debt == pytest.approx(0.0)
        assert b.net_debt_verified is True
        assert b.status == EB_STATUS_OK

    def test_complex_bridge_keeps_double_count_protection(self):
        m = MarketData(
            total_debt=1000.0,
            cash_and_equivalents=200.0,
            minority_interest=300.0,
            preferred_equity=150.0,
            non_operating_assets=400.0,
        )
        # minority/preferred already inside net debt → must not be deducted twice
        b = enterprise_to_equity(
            5000.0, m,
            net_debt_includes_minority=True,
            net_debt_includes_preferred=True,
        )
        assert b.minority_interest == 0.0
        assert b.preferred_equity == 0.0
        # 5000 - 800 (net debt) + 400 (non-op assets)
        assert b.equity_value == pytest.approx(4600.0)
        assert b.status == EB_STATUS_OK


# ===========================================================================
# P0-2 — P/E numerator/denominator basis consistency
# ===========================================================================
class TestP02PeShareCountBasis:
    def test_pe_rebuilds_equity_on_the_ttm_eps_denominator(self):
        data, profile = _fresh("AAPL")
        ttm = data.ttm
        assert ttm is not None and ttm.eps and ttm.eps > 0
        market_shares = data.market.shares_outstanding
        assert market_shares and market_shares > 0
        # Deliberately make the TTM (EPS-denominator) count differ from the
        # market count, so the test can tell which denominator was used.
        ttm_shares = market_shares * 0.90
        ttm.shares_outstanding = ttm_shares

        r = MultiplesModel("P/E").calculate(data, profile, multiple=15.0)
        assert r.status in (SolverStatus.SOLVED, SolverStatus.APPROXIMATE)

        audit = r.breakdown["pe_basis_audit"]
        assert audit["eps_basis"] == "TTM"
        assert audit["shares_basis"] == "ttm"
        assert audit["numerator_denominator_basis_match"] is True

        # value_per_share = multiple × TTM EPS; equity = that × the SAME TTM count.
        assert r.value_per_share == pytest.approx(15.0 * ttm.eps)
        assert r.equity_value == pytest.approx(15.0 * ttm.eps * ttm_shares)
        # It must NOT be a multiple of the unrelated market count.
        assert r.equity_value != pytest.approx(15.0 * ttm.eps * market_shares)

        assert r.share_count.basis == ShareCountBasis.TTM.value
        assert r.share_count.shares_used == pytest.approx(ttm_shares)

    def test_pe_falls_back_to_market_and_declares_the_mismatch(self):
        data, profile = _fresh("AAPL")
        ttm = data.ttm
        assert ttm is not None and ttm.eps and ttm.eps > 0
        # No income-statement share count → fall back to the market count, but
        # the audit must declare numerator/denominator basis mismatch loudly.
        ttm.shares_outstanding = None

        r = MultiplesModel("P/E").calculate(data, profile, multiple=15.0)
        assert r.status in (SolverStatus.SOLVED, SolverStatus.APPROXIMATE)
        audit = r.breakdown["pe_basis_audit"]
        assert audit["shares_basis"] == "market"
        assert audit["numerator_denominator_basis_match"] is False
        assert "口径不一致" in audit["shares_source"]

    def test_pe_row_vs_market_reference_is_flagged_incomparable(self):
        """P/E's TTM denominator is its *expected* basis, yet a large magnitude
        gap vs the market reference must still be flagged & dropped from the
        consensus (independent evidence, not a basis-label check)."""
        data, profile = _fresh("AAPL")
        ttm = data.ttm
        assert ttm is not None
        market_shares = data.market.shares_outstanding
        ttm.shares_outstanding = market_shares * 1.30  # +30% ≫ 10% comparability tol

        r = MultiplesModel("P/E").calculate(data, profile, multiple=15.0)
        results = {"P/E": r}
        ag = ModelAgreementAnalyzer().analyze(
            results, current_price=data.market.current_price, data=data
        )
        by_model = {row.model: row for row in ag.share_count_audit}
        assert "P/E" in by_model
        row = by_model["P/E"]
        assert row.basis == "ttm"
        assert row.basis_expected is True          # ttm IS P/E's expected basis
        assert row.deviation_vs_market == pytest.approx(0.30, abs=1e-6)
        assert row.comparable is False             # magnitude mismatch
        assert row.source and row.as_of is not None  # source + reporting period shown


# ===========================================================================
# P0-3 — share-count evidence gate (three independent calibers)
# ===========================================================================
class TestP03ShareCountEvidence:
    @staticmethod
    def _data(market: float, filing: float, diluted: float) -> FinancialData:
        return FinancialData(
            ticker="TST",
            market=MarketData(shares_outstanding=market, current_price=100.0,
                              market_cap=market * 100.0 if market else None),
            annual_income=[FinancialStatement(period_end="2024-12-31",
                                              shares_outstanding=filing)],
            ttm=FinancialStatement(period_end="2025-09-30", shares_outstanding=diluted),
        )

    def test_three_calibers_are_separated(self):
        ev = share_count_evidence(self._data(1.0e9, 1.0e9, 1.0e9))
        assert ev.market_implied == pytest.approx(1.0e9)
        assert ev.filing_period_end == pytest.approx(1.0e9)
        assert ev.diluted_weighted_avg == pytest.approx(1.0e9)
        assert ev.filing_period == "2024-12-31"
        assert ev.diluted_period == "2025-09-30"

    def test_deviation_above_25_percent_downgrades(self):
        ev = share_count_evidence(self._data(4.0e9, 5.2e9, 5.2e9))  # +30% off market
        assert ev.max_deviation == pytest.approx(0.30, abs=1e-6)
        assert ev.consistent is False
        assert any("EV 口径结果不受影响" in n for n in ev.notes)

    def test_consistent_within_tolerance(self):
        ev = share_count_evidence(self._data(1.0e9, 1.20e9, 1.0e9))  # +20% ≤ 25%
        assert ev.max_deviation == pytest.approx(0.20, abs=1e-6)
        assert ev.consistent is True

    def test_market_cap_over_price_is_not_proof_of_filing_shares(self):
        ev = share_count_evidence(self._data(1.0e9, 1.4e9, 1.0e9))
        joined = " ".join(ev.notes)
        assert "不能作为财报股数的证明" in joined
        assert ev.consistent is False

    def test_missing_market_implied_is_not_comparable(self):
        ev = share_count_evidence(self._data(None, 1.0e9, 1.0e9))
        assert ev.market_implied is None
        assert ev.max_deviation is None
        assert ev.consistent is True
        assert any("不得据此反推财报股数" in n for n in ev.notes)


# ===========================================================================
# P0-3 — unreliable per-share basis must not yield a strong verdict,
#        while the EV-level result stays available.
# ===========================================================================
class TestP03PerShareDowngradeKeepsEv:
    @staticmethod
    def _inconsistent_data():
        data, _profile = _fresh("AVGO")
        market = data.market.shares_outstanding
        # Filing-period & TTM counts far from the market-implied count → the
        # independent evidence disagrees beyond tolerance.
        if data.annual_income:
            data.annual_income[0].shares_outstanding = market * 1.35
        if data.ttm is not None:
            data.ttm.shares_outstanding = market * 1.35
        return data

    def test_unreliable_basis_caps_headline_but_ev_survives(self):
        data = self._inconsistent_data()
        ref = data.market.market_cap / data.market.current_price  # comparable denominator
        results = {
            "DCF": ValuationResult(
                model_name="DCF", status=SolverStatus.SOLVED, value_per_share=100.0,
                enterprise_value=2.0e12,
                share_count=make_share_count(ref, "TTM 财务报表股数", "ttm"),
            ),
            "EV/EBITDA": ValuationResult(
                model_name="EV/EBITDA", status=SolverStatus.SOLVED, value_per_share=105.0,
                enterprise_value=2.05e12,
                share_count=make_share_count(ref, "MarketData 流通股数", "market"),
            ),
            "P/B": ValuationResult(
                model_name="P/B", status=SolverStatus.SOLVED, value_per_share=98.0,
                enterprise_value=1.9e12,
                share_count=make_share_count(ref, "MarketData 流通股数", "market"),
            ),
        }
        ag = ModelAgreementAnalyzer().analyze(
            results, current_price=data.market.current_price, data=data
        )

        # Evidence gate fired independently of any single reconciliation check.
        assert ag.share_count_reliable is False
        assert ag.median_value is not None  # per-share figure still computed…

        # …and the EV-level results are preserved (not zeroed / dropped).
        for name, r in results.items():
            assert r.enterprise_value is not None, name

        card = build_valuation_verdict(
            agreement=ag, scenarios={}, model_results=results, data=data,
            profile=None, implied=None,
        )
        assert card.headline_label == "每股口径不可靠"
        assert card.headline_emoji == "🟠"
        assert "股数证据不一致" in card.headline_summary


# ===========================================================================
# Existing model-agreement + Golden Baseline compatibility (no regeneration)
# ===========================================================================
class TestExistingAgreementAndGoldenCompatibility:
    def test_avgo_pipeline_invariants_and_share_contract(self):
        from tests.golden_report import (
            BASKET,
            build_fingerprint,
            check_invariants,
            run_pipeline,
        )

        assert "AVGO" in BASKET
        ctx = run_pipeline("AVGO")
        fp = build_fingerprint("AVGO", ctx)

        # No self-contradictions introduced by P0-1/P0-2/P0-3.
        assert not check_invariants(fp, ctx)

        # The self-consistent synthetic feed keeps every denominator comparable
        # and the evidence gate silent (zero drift vs the golden baseline).
        assert fp["share_count_excluded"] == []
        assert fp["share_ref_source"] == "market_cap ÷ current_price"
        assert ctx["agreement"].share_count_reliable is True

    def test_golden_baseline_file_untouched(self):
        import json
        from pathlib import Path

        golden_path = Path(__file__).parent / "golden" / "report_fingerprints.json"
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        from tests.golden_report import BASKET

        # Every basket ticker is pinned, and the P0-3 keys are present without a
        # single baseline regeneration.
        assert set(golden) == set(BASKET)
        for t in BASKET:
            assert "share_ref_source" in golden[t]
            assert golden[t]["share_count_excluded"] == []
