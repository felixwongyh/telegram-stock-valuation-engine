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
        # ---- No independent segment data ⇒ circular ⇒ display-only (P1-SOTP) --
        # The parts are just ML exposures (or a single operating block) scaled by
        # the company's OWN EV/Revenue, so the result carries no independent
        # information. It is still computed for display, but must NOT count as a
        # solved valuation.
        from models.sotp import SOTPModel, SOTP_INSUFFICIENT

        r = ModelRouter().run_single(d, profile, "SOTP")
        assert r is not None
        assert r.value_per_share is not None
        assert r.value_per_share > 0
        assert not r.is_success()
        assert r.breakdown["sotp_state"] == SOTP_INSUFFICIENT
        assert r.breakdown["display_only"] is True
        # Every business segment must be non-independent (circular).
        assert r.breakdown["n_independent_segments"] == 0

        # ---- Independent external segments ⇒ SOLVED --------------------------
        r_ok = SOTPModel().run(
            d, profile,
            segments=[
                {"label": "Energy", "segment_ev": 5.0e10, "revenue": 1.0e10,
                 "applied_multiple": 5.0, "source": "external comps"},
                {"label": "Utilities", "segment_ev": 3.0e10, "revenue": 5.0e9,
                 "applied_multiple": 6.0, "source": "external comps"},
            ],
        )
        assert r_ok.is_success()
        assert r_ok.breakdown["sotp_state"] == "SOLVED"
        assert r_ok.breakdown["n_independent_segments"] == 2
        assert r_ok.breakdown["display_only"] is False
