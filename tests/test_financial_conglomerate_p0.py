"""Session #57 P0: financial conglomerate classification and routing.

A group can own a bank, a payment institution, a lender and a broker at the same
time (NU). The top-level business model is exclusive, but the sub-businesses are
not, so the two are separate axes:

    financial_business_model      what the group is          (exclusive)
    financial_subsegments         what the group is made of  (coexisting)
    group_level_bank_rim_eligible whether Bank RIM may be used (routing output)

The third field must be produced by the routing layer and must never contradict
``applicable_models``. A classifier must not be able to declare itself eligible.

Sub-business evidence is tri-state: True (proven present), False (proven
absent), None (not disclosed). "No evidence found" must not be recorded as
"proven absent".
"""
from __future__ import annotations

import pytest

from classification.classifier import BusinessClassifier, FINANCIAL_CONGLOMERATES
from config import BusinessType, FinancialBusinessModel, GroupBankRimEligibility
from data.models import (
    FinancialData,
    FinancialStatement,
    MarketData,
    SubsegmentEvidence,
)


def _company(
    ticker: str,
    *,
    industry: str = "Credit Services",
    sector: str = "Financial Services",
    revenue: float = 3.0e10,
    operating_income: float = 3.0e9,
    interest_expense: float | None = 2.0e9,
    total_assets: float | None = None,
    total_debt: float | None = 0.0,
    equity: float | None = 0.0,
) -> FinancialData:
    stmt = FinancialStatement(
        period_end="2026-09-30",
        period_type="ttm",
        revenue=revenue,
        operating_income=operating_income,
        interest_expense=interest_expense,
        net_income=2.0e9,
    )
    sheets = []
    if total_assets is not None:
        sheets = [{
            "Total Assets": total_assets,
            "Total Debt": total_debt or 0.0,
            "Stockholders Equity": equity or 0.0,
        }]
    return FinancialData(
        ticker=ticker,
        ttm=stmt,
        annual_income=[stmt],
        annual_balance_sheet=sheets,
        market=MarketData(sector=sector, industry=industry),
    )


# NU consolidated 2026-09-30: assets 87.43B, equity 14.34B, deposits/RDB 47.49B.
# Modelled as total assets / equity, with deposits carried as the residual
# non-debt, non-equity liability that the structural signal actually measures.
NU = _company(
    "NU", industry="Credit Services",
    revenue=1.2e10, operating_income=2.0e9, interest_expense=2.4e9,
    total_assets=8.743e10, total_debt=2.59e10, equity=1.434e10,
)


def _classify(data: FinancialData, bt: BusinessType = BusinessType.FINTECH):
    return BusinessClassifier.classify_financial_business_model(data, bt)


def _route(data: FinancialData, bt: BusinessType = BusinessType.FINTECH):
    applicable, na, _reasons = BusinessClassifier._model_applicability(data, bt)
    return applicable, na


# ---------------------------------------------------------------------------
# Top-level classification
# ---------------------------------------------------------------------------
class TestConglomerateClassification:
    def test_nu_is_classified_as_conglomerate(self):
        assert _classify(NU).model is FinancialBusinessModel.FINANCIAL_CONGLOMERATE

    def test_conglomerate_is_not_reported_as_a_single_line(self):
        """NU's label says "Credit Services"; that must not win over the group."""
        verdict = _classify(NU)
        assert verdict.model is not FinancialBusinessModel.PAYMENT_NETWORK
        assert verdict.model is not FinancialBusinessModel.FINTECH_LENDER

    def test_conglomerate_grants_no_bank_models(self):
        applicable, _ = _route(NU)
        assert "Bank DDM" not in applicable
        assert "Bank RIM" not in applicable

    def test_conglomerate_is_not_forced_into_plain_fcff(self):
        """Funding cost is core to the group's lending; FCFF must not be assumed."""
        applicable, _ = _route(NU)
        assert "DCF" not in applicable

    def test_reason_names_the_subsegments_found(self):
        reason = _classify(NU).reason
        assert "conglomerate" in reason.lower()
        assert "banking" in reason

    def test_non_conglomerate_has_no_subsegments(self):
        jpm = _company("JPM", industry="Banks—Diversified",
                       total_assets=4.0e12, total_debt=1.1e12, equity=3.3e11)
        verdict = _classify(jpm)
        assert verdict.model is FinancialBusinessModel.BANK
        assert "financial_subsegments" not in verdict.evidence


# ---------------------------------------------------------------------------
# Sub-business evidence: tri-state and sourced
# ---------------------------------------------------------------------------
class TestSubsegmentEvidence:
    def test_nu_subsegments_recorded(self):
        subs = _classify(NU).evidence["financial_subsegments"]
        for key in ("banking", "payment_network", "fintech_lending", "broker_dealer"):
            assert subs[key]["present"] is True, key

    def test_undisclosed_subsegment_is_none_not_false(self):
        """Absence of evidence is not evidence of absence."""
        subs = _classify(NU).evidence["financial_subsegments"]
        assert subs["insurance"]["present"] is None

    def test_undisclosed_subsegment_is_not_counted_as_present(self):
        """The derived list must require proven presence, not merely non-absence.

        ``insurance`` is undisclosed (None). Counting it as present would turn
        "we do not know" into a positive claim about the group.
        """
        evidence = _classify(NU).evidence
        assert "insurance" not in evidence["subsegments_present"]
        assert set(evidence["subsegments_present"]) == {
            "banking", "payment_network", "fintech_lending", "broker_dealer"
        }

    def test_every_present_claim_carries_provenance(self):
        subs = _classify(NU).evidence["financial_subsegments"]
        for key, ev in subs.items():
            if ev["present"] is True:
                assert ev["source"], f"{key} claims presence with no source"
                assert ev["as_of"], f"{key} claims presence with no as-of date"

    def test_subsegment_evidence_is_tri_state_typed(self):
        ev = SubsegmentEvidence(present=None)
        assert ev.present is None
        assert ev.as_dict() == {
            "present": None, "source": None, "as_of": None, "evidence_ref": None
        }

    def test_registry_claims_are_sourced(self):
        for ticker, subs in FINANCIAL_CONGLOMERATES.items():
            for key, ev in subs.items():
                if ev.present is True:
                    assert ev.source, f"{ticker}.{key} present without source"
                    assert ev.as_of, f"{ticker}.{key} present without as_of"


# ---------------------------------------------------------------------------
# Routing output: eligibility must agree with the model set
# ---------------------------------------------------------------------------
class TestEligibilityConsistency:
    def test_conglomerate_is_pending_not_ineligible(self):
        """Structure permits Bank RIM; only the evidence is missing."""
        applicable, na = _route(NU)
        got = BusinessClassifier.derive_group_bank_rim_eligibility(
            FinancialBusinessModel.FINANCIAL_CONGLOMERATE, applicable, na
        )
        assert got == GroupBankRimEligibility.PENDING_VALIDATION.value

    def test_bank_is_eligible(self):
        jpm = _company("JPM", industry="Banks—Diversified",
                       total_assets=4.0e12, total_debt=1.1e12, equity=3.3e11)
        applicable, na = _route(jpm, BusinessType.BANK)
        assert "Bank RIM" in applicable
        assert BusinessClassifier.derive_group_bank_rim_eligibility(
            FinancialBusinessModel.BANK, applicable, na
        ) == GroupBankRimEligibility.ELIGIBLE.value

    def test_payment_network_is_ineligible(self):
        ma = _company("MA", industry="Credit Services",
                      revenue=2.8e10, operating_income=1.5e10,
                      interest_expense=6.0e8, total_assets=4.0e10,
                      total_debt=1.5e10, equity=5.0e9)
        applicable, na = _route(ma)
        assert BusinessClassifier.derive_group_bank_rim_eligibility(
            FinancialBusinessModel.PAYMENT_NETWORK, applicable, na
        ) == GroupBankRimEligibility.INELIGIBLE.value

    @pytest.mark.parametrize("model", list(FinancialBusinessModel))
    def test_eligibility_never_contradicts_the_model_set(self, model):
        """The invariant: ELIGIBLE iff Bank RIM applicable; PENDING iff excluded
        for want of evidence; INELIGIBLE iff excluded by business model."""
        applicable, na = _route(NU)
        got = BusinessClassifier.derive_group_bank_rim_eligibility(model, applicable, na)
        bank_rim_applicable = "Bank RIM" in applicable
        if got == GroupBankRimEligibility.ELIGIBLE.value:
            assert bank_rim_applicable
        elif got == GroupBankRimEligibility.INELIGIBLE.value:
            assert not bank_rim_applicable
        elif got == GroupBankRimEligibility.PENDING_VALIDATION.value:
            assert not bank_rim_applicable

    def test_pending_validation_implies_no_bank_rim(self):
        applicable, na = _route(NU)
        eligible = BusinessClassifier.derive_group_bank_rim_eligibility(
            FinancialBusinessModel.FINANCIAL_CONGLOMERATE, applicable, na
        )
        assert eligible == GroupBankRimEligibility.PENDING_VALIDATION.value
        assert "Bank RIM" not in applicable


# ---------------------------------------------------------------------------
# End-to-end: the profile carries all three axes
# ---------------------------------------------------------------------------
class TestProfileIntegration:
    def test_profile_exposes_three_separate_axes(self):
        profile = BusinessClassifier().classify(NU)
        assert profile.financial_business_model == (
            FinancialBusinessModel.FINANCIAL_CONGLOMERATE.value
        )
        assert profile.financial_subsegments is not None
        assert profile.financial_subsegments["banking"].present is True
        assert profile.group_level_bank_rim_eligible == (
            GroupBankRimEligibility.PENDING_VALIDATION.value
        )

    def test_profile_eligibility_matches_applicable_models(self):
        profile = BusinessClassifier().classify(NU)
        if profile.group_level_bank_rim_eligible == GroupBankRimEligibility.ELIGIBLE.value:
            assert "Bank RIM" in profile.applicable_models
        else:
            assert "Bank RIM" not in profile.applicable_models

    def test_unknown_ticker_has_no_eligibility_field(self):
        """A non-financial has no Bank RIM question to answer at all."""
        nvda = _company("NVDA", industry="Semiconductors", sector="Technology",
                        interest_expense=1.0e8)
        profile = BusinessClassifier().classify(nvda)
        assert profile.group_level_bank_rim_eligible is None
        assert profile.financial_subsegments is None
