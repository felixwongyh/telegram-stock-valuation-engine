"""Session #56 P0: financial business-model classification and model routing.

The defect these pin: ``FINTECH`` was a catch-all for Yahoo's "Credit Services"
industry, and ``MODELS_BY_TYPE[FINTECH]`` hard-coded ``Bank DDM`` / ``Bank RIM``.
Visa and JPMorgan share that industry, so Visa was valued with a bank
residual-income model. Two ML paths made it worse by forcing ``NEOBANK`` (the
bank model set) from the *label text* alone, bypassing any structural test.

The fix separates the two axes the verdict asks for:

1. classification — what the business does (``FinancialBusinessModel``)
2. routing — which models that business model supports

Bank models are now granted only when the business model proves a loan book.
Every test below asserts a *routing* outcome, not a display label.
"""
from __future__ import annotations

from config import BusinessType, FinancialBusinessModel
from classification.classifier import BusinessClassifier
from data.models import FinancialData, FinancialStatement


def _financial_data(
    *,
    ticker: str = "TEST",
    revenue: float | None = 1.0e10,
    operating_income: float | None = 3.0e9,
    interest_expense: float | None = 1.0e8,
    net_income: float | None = 2.0e9,
) -> FinancialData:
    stmt = FinancialStatement(
        period_end="2026-09-30",
        period_type="ttm",
        revenue=revenue,
        operating_income=operating_income,
        interest_expense=interest_expense,
        net_income=net_income,
        eps=1.0,
        shares_outstanding=1.0e9,
        free_cash_flow=5.0e9,
    )
    return FinancialData(
        ticker=ticker,
        ttm=stmt,
        annual_income=[stmt],
    )


def _route(data: FinancialData, bt: BusinessType):
    applicable, not_applicable, _reasons = BusinessClassifier._model_applicability(data, bt)
    return applicable, not_applicable


# ---------------------------------------------------------------- classification


class TestFinancialBusinessModelClassification:
    def test_bank_label_classifies_as_bank(self):
        model, reason = BusinessClassifier.classify_financial_business_model(
            _financial_data(), BusinessType.BANK
        )
        assert model is FinancialBusinessModel.BANK
        assert "Bank" in reason

    def test_payment_network_has_no_loan_book(self):
        # interest expense / operating income = 0.025, far below the 0.20 gate
        model, reason = BusinessClassifier.classify_financial_business_model(
            _financial_data(interest_expense=7.5e7, operating_income=3.0e9),
            BusinessType.FINTECH,
        )
        assert model is FinancialBusinessModel.PAYMENT_NETWORK
        assert "payment network" in reason

    def test_fintech_lender_is_not_a_bank(self):
        # 0.40 of operating income consumed by funding cost -> lender
        model, reason = BusinessClassifier.classify_financial_business_model(
            _financial_data(interest_expense=1.2e9, operating_income=3.0e9),
            BusinessType.FINTECH,
        )
        assert model is FinancialBusinessModel.FINTECH_LENDER
        assert "lender" in reason

    def test_insurance_is_other_financial_not_bank(self):
        model, _ = BusinessClassifier.classify_financial_business_model(
            _financial_data(), BusinessType.INSURANCE
        )
        assert model is FinancialBusinessModel.OTHER_FINANCIAL

    def test_non_financial_is_not_financial(self):
        model, _ = BusinessClassifier.classify_financial_business_model(
            _financial_data(), BusinessType.SEMICONDUCTOR
        )
        assert model is FinancialBusinessModel.NOT_FINANCIAL

    def test_fintech_without_interest_expense_is_not_routed_to_bank(self):
        """Missing evidence must not be read as "probably a bank"."""
        model, reason = BusinessClassifier.classify_financial_business_model(
            _financial_data(interest_expense=None), BusinessType.FINTECH
        )
        assert model is FinancialBusinessModel.OTHER_FINANCIAL
        assert "no evidence" in reason

    def test_fintech_without_revenue_is_not_routed_to_bank(self):
        model, reason = BusinessClassifier.classify_financial_business_model(
            _financial_data(revenue=None), BusinessType.FINTECH
        )
        assert model is FinancialBusinessModel.OTHER_FINANCIAL
        assert "no revenue base" in reason

    def test_classification_is_traceable(self):
        """Every decision carries a human-readable reason (checklist item)."""
        for bt in (BusinessType.BANK, BusinessType.INSURANCE, BusinessType.FINTECH,
                   BusinessType.NEOBANK, BusinessType.SEMICONDUCTOR):
            _model, reason = BusinessClassifier.classify_financial_business_model(
                _financial_data(), bt
            )
            assert reason and isinstance(reason, str)


# ---------------------------------------------------------------------- routing


class TestModelRouting:
    def test_bank_gets_bank_models(self):
        applicable, _ = _route(_financial_data(), BusinessType.BANK)
        assert "Bank RIM" in applicable
        assert "Bank DDM" in applicable

    def test_payment_network_is_excluded_from_bank_models(self):
        data = _financial_data(interest_expense=7.5e7, operating_income=3.0e9)
        applicable, not_applicable = _route(data, BusinessType.FINTECH)
        assert "Bank RIM" not in applicable
        assert "Bank DDM" not in applicable
        assert "Bank RIM" in not_applicable
        assert "Bank DDM" in not_applicable

    def test_payment_network_keeps_fcff_models(self):
        """The verdict asks for FCFF if supported — it is, so it must be routed."""
        data = _financial_data(interest_expense=7.5e7, operating_income=3.0e9)
        applicable, _ = _route(data, BusinessType.FINTECH)
        assert "DCF" in applicable
        assert "ReverseDCF" in applicable

    def test_fintech_lender_keeps_bank_models(self):
        """A genuine lender must not lose bank models (NU regression guard)."""
        data = _financial_data(interest_expense=1.2e9, operating_income=3.0e9)
        applicable, _ = _route(data, BusinessType.FINTECH)
        assert "Bank RIM" in applicable
        assert "Bank DDM" in applicable

    def test_insurance_never_gets_bank_models(self):
        applicable, _ = _route(_financial_data(), BusinessType.INSURANCE)
        assert "Bank RIM" not in applicable
        assert "Bank DDM" not in applicable

    def test_unknown_financial_does_not_enter_bank_rim(self):
        """No evidence of a loan book must not silently become Bank RIM."""
        data = _financial_data(interest_expense=None)
        applicable, _ = _route(data, BusinessType.FINTECH)
        assert "Bank RIM" not in applicable

    def test_na_reason_recorded_for_excluded_bank_model(self):
        data = _financial_data(interest_expense=7.5e7, operating_income=3.0e9)
        _applicable, _na, reasons = BusinessClassifier._model_applicability(
            data, BusinessType.FINTECH
        )
        assert "Bank RIM" in reasons
        assert "FinTech" in reasons["Bank RIM"]


# --------------------------------------------------------------------- mutation
#
# These fail if the routing ever regresses to keying on the sector label again.


class TestRoutingMutation:
    def test_visa_forced_to_bank_would_be_caught(self):
        """If a payment network were routed as BANK, bank models appear — fail."""
        visa = _financial_data(ticker="V", interest_expense=7.5e7, operating_income=3.0e9)
        # Correct routing:
        correct, _ = _route(visa, BusinessType.FINTECH)
        assert "Bank RIM" not in correct
        # The mutation: treat it as a bank.
        mutated, _ = _route(visa, BusinessType.BANK)
        assert "Bank RIM" in mutated
        # The invariant that must hold in production:
        assert "Bank RIM" not in _route(visa, BusinessType.FINTECH)[0]

    def test_jpm_downgraded_to_payment_network_would_be_caught(self):
        """If a bank were routed as a payment network, it loses RIM — fail."""
        jpm = _financial_data(ticker="JPM", interest_expense=8.0e10,
                              operating_income=1.2e11, revenue=1.2e11)
        # Correct routing keeps bank models.
        correct, _ = _route(jpm, BusinessType.BANK)
        assert "Bank RIM" in correct
        # The mutation: route by the "financial services" label as a fee business.
        model, _ = BusinessClassifier.classify_financial_business_model(jpm, BusinessType.FINTECH)
        assert model is FinancialBusinessModel.FINTECH_LENDER, (
            "a bank's funding cost ratio must not read as a payment network"
        )

    def test_missing_classification_is_not_guessed_as_bank(self):
        """Dropping the evidence must not fall back to Bank RIM."""
        for missing in (
            _financial_data(interest_expense=None),
            _financial_data(revenue=None),
        ):
            model, _ = BusinessClassifier.classify_financial_business_model(
                missing, BusinessType.FINTECH
            )
            assert model is not FinancialBusinessModel.BANK
            assert model is not FinancialBusinessModel.FINTECH_LENDER

    def test_bank_models_never_come_from_the_label_alone(self):
        """A FINTECH label with no funding cost must never yield bank models."""
        for ie in (None, 1.0, 7.5e7):
            data = _financial_data(interest_expense=ie, operating_income=3.0e9)
            applicable, _ = _route(data, BusinessType.FINTECH)
            assert "Bank RIM" not in applicable, f"interest_expense={ie}"
            assert "Bank DDM" not in applicable, f"interest_expense={ie}"
