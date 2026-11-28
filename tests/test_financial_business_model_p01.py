"""Session #56 P0.1: financial business classification hardening.

Three concepts had been conflated: industry label → business model → valuation
model. Taxonomy mapped asset managers, broker-dealers and exchanges to
``BusinessType.BANK``, so ``MODELS_BY_TYPE[BANK]`` handed them Bank DDM/RIM on a
label alone.

These tests pin the separation:

    BLK  asset manager    → ASSET_MANAGER    no bank models
    SCHW broker + bank    → BANK             bank models (it is a BHC)
    CME  exchange         → EXCHANGE         no bank models
    MA   payment network  → PAYMENT_NETWORK  no bank models, keeps FCFF

Fixtures are static, not fetched. BLK/SCHW/CME/MA are absent from the frozen
snapshot, and inventing their numbers by fetching live data into a frozen
snapshot is exactly what the snapshot discipline forbids. These fixtures
reproduce each company's *structure* (identity wording plus balance-sheet
shape), which is all the classifier consumes.
"""
from __future__ import annotations

import pytest

from classification.classifier import BusinessClassifier, BANK_HOLDING_COMPANIES
from config import BusinessType, FinancialBusinessModel
from data.models import FinancialData, FinancialStatement, MarketData


def _company(
    ticker: str,
    *,
    industry: str,
    sector: str = "Financial Services",
    revenue: float = 1.0e10,
    operating_income: float = 3.0e9,
    interest_expense: float | None = 1.0e8,
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


# ---------------------------------------------------------------------------
# Fixtures reproducing each company's observable structure
# ---------------------------------------------------------------------------
BLK = _company(
    "BLK", industry="Asset Management",
    revenue=2.0e10, operating_income=6.0e9, interest_expense=3.0e8,
    total_assets=1.2e11, total_debt=1.0e10, equity=4.0e10,
)
SCHW = _company(
    "SCHW", industry="Capital Markets",
    revenue=1.9e10, operating_income=6.5e9, interest_expense=4.5e9,
    total_assets=4.5e11, total_debt=6.0e10, equity=4.0e10,
)
CME = _company(
    "CME", industry="Financial Data & Stock Exchanges",
    revenue=6.0e9, operating_income=3.5e9, interest_expense=1.5e8,
    total_assets=1.0e11, total_debt=3.0e9, equity=2.8e10,
)
MA = _company(
    "MA", industry="Credit Services",
    revenue=2.8e10, operating_income=1.5e10, interest_expense=6.0e8,
    total_assets=4.0e10, total_debt=1.5e10, equity=5.0e9,
)


def _classify(data: FinancialData, bt: BusinessType):
    return BusinessClassifier.classify_financial_business_model(data, bt)


def _route(data: FinancialData, bt: BusinessType):
    applicable, na, _reasons = BusinessClassifier._model_applicability(data, bt)
    return applicable, na


# ---------------------------------------------------------------------------
# Acceptance criterion: none of these may enter Bank RIM automatically
# ---------------------------------------------------------------------------
class TestNoAutomaticBankRIM:
    @pytest.mark.parametrize("data,expected", [
        (BLK, FinancialBusinessModel.ASSET_MANAGER),
        (CME, FinancialBusinessModel.EXCHANGE),
        (MA, FinancialBusinessModel.PAYMENT_NETWORK),
    ])
    def test_classification(self, data, expected):
        v = _classify(data, BusinessType.BANK)
        assert v.model is expected, v.reason

    @pytest.mark.parametrize("data", [BLK, CME, MA])
    def test_no_bank_models(self, data):
        applicable, _na = _route(data, BusinessType.BANK)
        assert "Bank RIM" not in applicable
        assert "Bank DDM" not in applicable

    @pytest.mark.parametrize("data", [BLK, CME, MA])
    def test_bank_models_are_explicitly_not_applicable(self, data):
        """Exclusion must be recorded, not silently dropped."""
        _applicable, na = _route(data, BusinessType.BANK)
        assert "Bank RIM" in na
        assert "Bank DDM" in na


class TestAssetManager:
    def test_identity_is_high_confidence(self):
        v = _classify(BLK, BusinessType.BANK)
        assert v.confidence == "high"
        assert "asset management" in v.reason.lower()

    def test_keeps_multiple_based_models(self):
        applicable, _ = _route(BLK, BusinessType.BANK)
        assert "P/E" in applicable
        assert "P/B" in applicable

    def test_keeps_fcff_models(self):
        """AUM fees are a real cash flow; the BANK archetype must not strip DCF."""
        applicable, _ = _route(BLK, BusinessType.BANK)
        assert "DCF" in applicable
        assert "ReverseDCF" in applicable


class TestExchange:
    def test_financial_data_and_exchanges_is_not_a_bank(self):
        """The literal Yahoo industry contains the word "exchanges"."""
        v = _classify(CME, BusinessType.BANK)
        assert v.model is FinancialBusinessModel.EXCHANGE

    def test_exchange_identity_not_confused_by_word_financial(self):
        v = _classify(CME, BusinessType.BANK)
        assert v.model is not FinancialBusinessModel.BANK

    def test_keeps_fcff_models(self):
        """Listing/transaction fees are a real cash flow."""
        applicable, _ = _route(CME, BusinessType.BANK)
        assert "DCF" in applicable
        assert "ReverseDCF" in applicable


class TestPaymentNetwork:
    def test_credit_services_alone_does_not_decide(self):
        """MA and JPM share "Credit Services"; structure must separate them."""
        v = _classify(MA, BusinessType.FINTECH)
        assert v.model is FinancialBusinessModel.PAYMENT_NETWORK

    def test_keeps_fcff_models(self):
        applicable, _ = _route(MA, BusinessType.FINTECH)
        assert "DCF" in applicable
        assert "ReverseDCF" in applicable

    def test_is_the_control_case_for_visa(self):
        """V and MA must land in the same business model."""
        visa = _company("V", industry="Credit Services",
                        revenue=3.5e10, operating_income=2.2e10,
                        interest_expense=5.5e8)
        assert _classify(visa, BusinessType.FINTECH).model is \
            _classify(MA, BusinessType.FINTECH).model


class TestBrokerDealerVsBank:
    def test_schw_is_a_bank_holding_company(self):
        """SCHW is broker-branded but files as a BHC: bank models apply."""
        assert "SCHW" in BANK_HOLDING_COMPANIES
        v = _classify(SCHW, BusinessType.BANK)
        assert v.model is FinancialBusinessModel.BANK, v.reason

    def test_schw_keeps_bank_models(self):
        applicable, _ = _route(SCHW, BusinessType.BANK)
        assert "Bank RIM" in applicable

    def test_pure_broker_is_not_a_bank(self):
        """A broker's customer payables must not be read as deposits."""
        ibkr = _company(
            "IBKR", industry="Capital Markets",
            revenue=4.0e9, operating_income=2.0e9, interest_expense=8.0e8,
            total_assets=1.2e11, total_debt=2.0e10, equity=3.0e9,
        )
        v = _classify(ibkr, BusinessType.BANK)
        assert v.model is FinancialBusinessModel.BROKER_DEALER, v.reason
        applicable, _ = _route(ibkr, BusinessType.BANK)
        assert "Bank RIM" not in applicable

    def test_registry_membership_is_what_decides(self):
        """Same identity, different regulatory status → different verdict."""
        same_shape = dict(
            industry="Capital Markets", revenue=1.9e10,
            operating_income=6.5e9, interest_expense=4.5e9,
            total_assets=4.5e11, total_debt=6.0e10, equity=4.0e10,
        )
        bhc = _company("GS", **same_shape)
        broker = _company("IBKR", **same_shape)
        assert _classify(bhc, BusinessType.BANK).model is FinancialBusinessModel.BANK
        assert _classify(broker, BusinessType.BANK).model \
            is FinancialBusinessModel.BROKER_DEALER


# ---------------------------------------------------------------------------
# FintechLender: never inherits bank models, never forced into FCFF either
# ---------------------------------------------------------------------------
class TestFintechLenderSplit:
    LENDER = _company(
        "TESTLENDER", industry="Credit Services",
        revenue=1.0e10, operating_income=2.0e9, interest_expense=1.2e9,
    )

    def test_classified_as_lender(self):
        v = _classify(self.LENDER, BusinessType.FINTECH)
        assert v.model is FinancialBusinessModel.FINTECH_LENDER

    def test_does_not_inherit_bank_models(self):
        applicable, na = _route(self.LENDER, BusinessType.FINTECH)
        assert "Bank RIM" not in applicable
        assert "Bank DDM" not in applicable
        assert "Bank RIM" in na

    def test_is_not_pushed_into_fcff(self):
        """Funding cost is core to a lender, so FCFF must be earned, not assumed."""
        applicable, _ = _route(self.LENDER, BusinessType.FINTECH)
        assert "DCF" not in applicable
        assert "ReverseDCF" not in applicable

    def test_keeps_multiple_based_coverage(self):
        applicable, _ = _route(self.LENDER, BusinessType.FINTECH)
        assert "P/E" in applicable
        assert "P/B" in applicable


# ---------------------------------------------------------------------------
# Interest funding intensity is an auxiliary signal, never a bank verdict
# ---------------------------------------------------------------------------
class TestInterestIntensityIsAuxiliary:
    def test_high_intensity_does_not_make_a_bank(self):
        """An asset manager can carry real funding cost without being a bank."""
        blk_levered = _company(
            "BLK", industry="Asset Management",
            revenue=2.0e10, operating_income=2.0e9, interest_expense=1.9e9,
            total_assets=1.2e11, total_debt=1.0e10, equity=4.0e10,
        )
        v = _classify(blk_levered, BusinessType.BANK)
        assert v.model is FinancialBusinessModel.ASSET_MANAGER
        assert v.model is not FinancialBusinessModel.BANK

    def test_signal_is_recorded_as_evidence(self):
        v = _classify(BLK, BusinessType.BANK)
        assert "interest_funding_intensity" in v.evidence
        assert "deposit_liability_ratio" in v.evidence

    def test_identity_dominates_the_ratio(self):
        """Same ratio, opposite identity → opposite verdicts."""
        ratio = 0.5
        mgr = _company("BLK", industry="Asset Management",
                       revenue=2.0e10, operating_income=4.0e9,
                       interest_expense=4.0e9 * ratio)
        bank = _company("JPM", industry="Banks—Diversified",
                        revenue=2.0e10, operating_income=4.0e9,
                        interest_expense=4.0e9 * ratio,
                        total_assets=4.0e12, total_debt=5.0e11, equity=3.6e11)
        assert _classify(mgr, BusinessType.BANK).model \
            is FinancialBusinessModel.ASSET_MANAGER
        assert _classify(bank, BusinessType.BANK).model \
            is FinancialBusinessModel.BANK


# ---------------------------------------------------------------------------
# Unknown / conflicting evidence must not be forced into a bank bucket
# ---------------------------------------------------------------------------
class TestNoForcedClassification:
    def test_no_identity_no_structure_is_other_financial(self):
        opaque = _company("OPAQUE", industry="", sector="",
                          revenue=1.0e10, operating_income=2.0e9,
                          interest_expense=None)
        v = _classify(opaque, BusinessType.FINTECH)
        assert v.model is FinancialBusinessModel.OTHER_FINANCIAL
        assert v.confidence == "low"

    def test_contradictory_evidence_is_flagged(self):
        """A "Banks" label on a balance sheet with no deposit base conflicts."""
        contradictory = _company(
            "CONFLICT", industry="Banks—Diversified",
            revenue=1.0e10, operating_income=3.0e9,
            total_assets=1.0e11, total_debt=5.0e10, equity=5.0e10,
        )
        v = _classify(contradictory, BusinessType.BANK)
        assert v.model is FinancialBusinessModel.OTHER_FINANCIAL
        assert v.confidence == "low"
        assert "conflict" in v.reason.lower()

    def test_other_financial_grants_no_bank_models(self):
        opaque = _company("OPAQUE", industry="", sector="",
                          revenue=1.0e10, operating_income=2.0e9,
                          interest_expense=None)
        applicable, _ = _route(opaque, BusinessType.FINTECH)
        assert "Bank RIM" not in applicable

    @pytest.mark.parametrize("model", list(FinancialBusinessModel))
    def test_every_model_is_explicitly_enumerated(self, model):
        """No accidental fallback: the enum is the complete taxonomy."""
        assert model.value
