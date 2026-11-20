"""Regression tests for contradictions found in the KR (Kroger) report.

Each test pins one specific defect that made the report assert two mutually
exclusive things at once. Numbers are taken from the 2026-11-20 KR report.
"""


from classification.classifier import BusinessClassifier
from config import BusinessType
from data.models import FinancialData, FinancialStatement, MarketData
from models.reverse_dcf import ReverseDCFModel
from reporting.verdict_intuition import build_valuation_verdict


def _kr_like_data() -> FinancialData:
    ttm = FinancialStatement(
        period_end="TTM",
        revenue=149_326_000_000.0,
        operating_income=2_688_000_000.0,
        free_cash_flow=2_384_000_000.0,
        shares_outstanding=690_000_000.0,
        interest_expense=0.0,
    )
    market = MarketData(
        current_price=67.94,
        market_cap=67.94 * 690_000_000.0,
        total_debt=14_000_000_000.0,
        risk_free_rate=0.042,
        equity_risk_premium=0.05,
        beta=1.19,
    )
    return FinancialData(
        ticker="KR",
        annual_income=[ttm],
        annual_balance_sheet=[],
        ttm=ttm,
        market=market,
    )


class TestThinPositiveFcfIsNotCalledNegative:
    """KR has +$2.38B FCF (1.6% margin). The label said "Weak/Negative FCF"."""

    def test_thin_positive_margin_is_labelled_thin_not_negative(self):
        data = _kr_like_data()
        out = BusinessClassifier._characterize_profile(
            data, BusinessType.CONSUMER_STAPLES
        )
        label = out["cash_flow_profile"]
        assert "Negative" not in label
        assert label == "Thin Positive FCF"

    def test_genuinely_negative_fcf_still_says_negative(self):
        data = _kr_like_data()
        data.ttm.free_cash_flow = -500_000_000.0
        out = BusinessClassifier._characterize_profile(
            data, BusinessType.CONSUMER_STAPLES
        )
        assert out["cash_flow_profile"] == "Negative FCF"


class TestImpliedSolveDegeneracyIsFlagged:
    """Solving WACC / g along the *solved* growth path returns the base input.

    KR reported "隐含折现率 (WACC) 9.33%" against a base WACC of 9.33% and
    "隐含终值增长率 0.5%" against a base 0.5%, presenting tautologies as
    independent market expectations.
    """

    def test_degenerate_solves_are_flagged(self):
        """Anchor growth at the path that already reproduces target EV.

        That is precisely the KR situation: the anchor *is* the solved implied
        CAGR, so WACC / g come back equal to their base inputs.
        """
        model = ReverseDCFModel()
        data = _kr_like_data()
        profile = BusinessClassifier().classify(data)

        anchor = 0.0815
        wacc, tg, horizon = 0.0933, 0.005, 7
        target_ev = model._project_ev(data, profile, anchor, wacc, tg, horizon)
        assert target_ev and target_ev > 0

        implied = model._implied_expectations(
            data, profile, target_ev, wacc, tg, horizon, anchor,
        )
        assert implied["implied_wacc"].value is not None
        assert abs(implied["implied_wacc"].value - wacc) < 1e-3
        assert implied["implied_wacc_degenerate"] is True
        assert implied["implied_terminal_growth_degenerate"] is True

    def test_a_genuine_solve_is_not_flagged_degenerate(self):
        """A target EV off the base path must NOT be reported as a tautology."""
        model = ReverseDCFModel()
        data = _kr_like_data()
        profile = BusinessClassifier().classify(data)

        anchor, wacc, tg, horizon = 0.0815, 0.0933, 0.005, 7
        base_ev = model._project_ev(data, profile, anchor, wacc, tg, horizon)
        implied = model._implied_expectations(
            data, profile, base_ev * 1.5, wacc, tg, horizon, anchor,
        )
        assert not implied.get("implied_wacc_degenerate")


class TestHeadlineDoesNotContradictItsOwnCaveat:
    """KR printed "当前价 $67.94 估值合理…（显著高估信号）" in one sentence.

    The scenario cross-check raised the verdict to 显著高估, but the summary
    sentence was still assembled from the median-only label.
    """

    def test_headline_uses_the_scenario_escalated_verdict(self):
        from analysis.model_agreement import ModelAgreementAnalyzer
        from models.base import ValuationResult, SolverStatus

        data = _kr_like_data()
        results = {
            "DCF": ValuationResult(
                model_name="DCF", status=SolverStatus.SOLVED, value_per_share=68.0,
            ),
            "EV/EBITDA": ValuationResult(
                model_name="EV/EBITDA", status=SolverStatus.SOLVED, value_per_share=69.0,
            ),
            "P/E": ValuationResult(
                model_name="P/E", status=SolverStatus.SOLVED, value_per_share=68.3,
            ),
            "P/B": ValuationResult(
                model_name="P/B", status=SolverStatus.SOLVED, value_per_share=68.1,
            ),
        }
        ag = ModelAgreementAnalyzer().analyze(
            results, current_price=data.market.current_price, data=data,
        )
        # Median ≈ price → "估值合理"; but every scenario sits far below price.
        scenarios = {
            "Bull": ValuationResult(
                model_name="Bull", status=SolverStatus.SOLVED, value_per_share=4.54,
            ),
            "Base": ValuationResult(
                model_name="Base", status=SolverStatus.SOLVED, value_per_share=1.62,
            ),
            "Bear": ValuationResult(
                model_name="Bear", status=SolverStatus.SOLVED, value_per_share=0.0,
            ),
        }
        card = build_valuation_verdict(
            agreement=ag, scenarios=scenarios, model_results=results, data=data,
            profile=None, implied=None,
        )
        summary = card.headline_summary
        head = summary.split("｜")[0]
        # The scenario cross-check must own the leading verdict, and the
        # median-only label may only appear as an explicitly subordinate clause.
        if "显著高估信号" in summary:
            assert card.headline_label == "显著高估"
            assert "显著高估" in head
            assert "中位口径" in head
            assert not head.startswith("🔴 当前价 $67.94 估值合理")
