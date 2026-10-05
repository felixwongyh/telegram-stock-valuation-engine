from classification.classifier import BusinessClassifier
from data import DataValidator, FinancialNormalizer, SyntheticDataProvider
from models.router import ModelRouter


class TestSpecialModels:
    def test_reit_nav_model_runs(self):
        d = SyntheticDataProvider().get_financial_data("PLD")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = BusinessClassifier().classify(d)
        assert "REIT NAV" in p.applicable_models
        r = ModelRouter().run_single(d, p, "REIT NAV")
        assert r is not None
        assert r.is_success()
        assert r.value_per_share is not None
        assert r.value_per_share > 0

    def test_bank_ddm_model_runs(self):
        d = SyntheticDataProvider().get_financial_data("JPM")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = BusinessClassifier().classify(d)
        assert "Bank DDM" in p.applicable_models
        r = ModelRouter().run_single(d, p, "Bank DDM")
        assert r is not None
        assert r.is_success()
        assert r.value_per_share is not None
        assert r.value_per_share > 0

    def test_sotp_model_runs(self):
        d = SyntheticDataProvider().get_financial_data("AAPL")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        from data.models import CompanyProfile

        profile = CompanyProfile(
            ticker="TEST",
            business_type="Conglomerate",
            classification_confidence=0.9,
            classification_reasons=["synthetic conglomerate"],
            applicable_models=["SOTP"],
            not_applicable_models=[],
            not_applicable_reasons={},
            revenue_characteristic="Large Cap",
            growth_profile="Moderate Growth",
            profitability_profile="Excellent",
            cash_flow_profile="Strong FCF",
            leverage_profile="Low Leverage",
            capital_intensity="Capital Intensive",
            is_financial_institution=False,
            is_reit=False,
        )
        r = ModelRouter().run_single(d, profile, "SOTP")
        assert r is not None
        assert r.is_success()
        assert r.value_per_share is not None
        assert r.value_per_share > 0
