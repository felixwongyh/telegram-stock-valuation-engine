"""
tests/test_ml_classifier.py - Tests for Item #14 ML-Enhanced Classifier
"""
from __future__ import annotations

import pytest

from classification import (
    MLHybridClassifier,
    LightGBMBusinessClassifier,
    extract_numerical_features,
    build_text_corpus,
    build_synthetic_training_set,
)
from classification.classifier import BusinessClassifier
from data import SyntheticDataProvider, FinancialNormalizer, DataValidator
from config import BusinessType


@pytest.fixture(scope="module")
def hybrid_cls():
    c = MLHybridClassifier()
    ok, msg = c.ensure_ready()
    assert ok, f"ML classifier should initialize: {msg}"
    return c


class TestMLFeatureEngineering:
    def test_extract_numerical_features_has_all_keys(self):
        d = SyntheticDataProvider().get_financial_data("NVDA")
        d = FinancialNormalizer.normalize_all(d)
        feats = extract_numerical_features(d)
        expected = [
            "log_revenue", "revenue_cagr_3y", "gross_margin", "gross_margin_vol_3y",
            "operating_margin", "operating_margin_vol_3y", "fcf_margin",
            "capex_to_revenue", "interest_to_revenue", "de_ratio", "beta",
            "market_cap_log", "pe", "pb", "ev_ebitda",
        ]
        for k in expected:
            assert k in feats, f"Missing numerical feature {k}"
            assert isinstance(feats[k], float)

    def test_extract_features_missing_data_robust(self):
        d = SyntheticDataProvider().get_financial_data("UNKNOWN_TICKER_XYZ")
        d.ttm = None
        d.annual_income = []
        feats = extract_numerical_features(d)
        assert isinstance(feats, dict)
        assert len(feats) == 15

    def test_build_text_corpus(self):
        d = SyntheticDataProvider().get_financial_data("NVDA")
        corpus = build_text_corpus(d)
        assert "nvidia" in corpus
        assert "semiconductor" in corpus.lower()


class TestMLTrainingBuilder:
    def test_synthetic_training_set_shape(self):
        X_num, X_text, y = build_synthetic_training_set(n_total=500, seed=7)
        assert len(X_num) == 500
        assert len(X_text) == 500
        assert len(y) == 500
        labels = set(y)
        assert BusinessType.BANK.value in labels
        assert BusinessType.REIT.value in labels
        assert BusinessType.SEMICONDUCTOR.value in labels
        for row in X_num:
            assert len(row) == 15


class TestMLHybridClassifier:
    def test_ml_used_for_nvda(self, hybrid_cls):
        d = SyntheticDataProvider().get_financial_data("NVDA")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = hybrid_cls.classify(d)
        assert p.business_type != BusinessType.REIT.value
        assert p.is_reit is False
        assert "DCF" in p.applicable_models

    def test_bank_detected(self, hybrid_cls):
        d = SyntheticDataProvider().get_financial_data("JPM")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = hybrid_cls.classify(d)
        assert p.is_financial_institution is True

    def test_reit_detected(self, hybrid_cls):
        d = SyntheticDataProvider().get_financial_data("PLD")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = hybrid_cls.classify(d)
        assert p.is_reit is True or p.business_type == BusinessType.REIT.value

    def test_probability_output_shape(self, hybrid_cls):
        d = SyntheticDataProvider().get_financial_data("AAPL")
        d = FinancialNormalizer.normalize_all(d)
        p = hybrid_cls.classify(d)
        assert isinstance(p.ml_probabilities, dict)
        if p.ml_model_used:
            assert len(p.ml_probabilities) >= 2
            total = sum(p.ml_probabilities.values())
            assert 0.95 <= total <= 1.05

    def test_top_2_candidates(self, hybrid_cls):
        d = SyntheticDataProvider().get_financial_data("MSFT")
        d = FinancialNormalizer.normalize_all(d)
        p = hybrid_cls.classify(d)
        if p.ml_model_used:
            assert len(p.top_2_candidates) == 2
            for tup in p.top_2_candidates:
                assert isinstance(tup, tuple)
                assert len(tup) == 2
                assert isinstance(tup[0], str)
                assert isinstance(tup[1], float)

    def test_ml_model_version_filled(self, hybrid_cls):
        d = SyntheticDataProvider().get_financial_data("MSFT")
        d = FinancialNormalizer.normalize_all(d)
        p = hybrid_cls.classify(d)
        if p.ml_model_used:
            assert p.ml_model_version != ""

    def test_rule_fallback_when_model_unavailable(self):
        c = MLHybridClassifier()
        c._ml._available = False
        c._initialized_ok = True
        d = SyntheticDataProvider().get_financial_data("AAPL")
        d = FinancialNormalizer.normalize_all(d)
        p = c.classify(d)
        assert p.rule_fallback_triggered is True
        assert p.ml_model_used is False
        assert p.business_type != ""


class TestEdgeCases:
    def test_high_margin_semiconductor_not_reit(self, hybrid_cls):
        """Edge case: high-margin semiconductor should never be classified as REIT."""
        d = SyntheticDataProvider().get_financial_data("NVDA")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = hybrid_cls.classify(d)
        assert p.business_type != BusinessType.REIT.value
        assert p.is_reit is False

    def test_classifier_backward_compat_with_rules(self):
        """Deterministic BusinessClassifier rules should still work standalone."""
        d = SyntheticDataProvider().get_financial_data("JPM")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = BusinessClassifier.classify(d)
        assert p.is_financial_institution is True
        assert "DCF" in p.not_applicable_models or "DCF" not in p.applicable_models
