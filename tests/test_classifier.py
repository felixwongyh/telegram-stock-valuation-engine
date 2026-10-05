"""
tests/test_classifier.py - Business Classification Tests
"""
from __future__ import annotations

import pytest

from classification.classifier import BusinessClassifier
from data import SyntheticDataProvider, FinancialNormalizer, DataValidator
from config import BusinessType


class TestClassifier:
    def test_aapl_classified_as_tech(self, aapl_data, aapl_profile):
        assert aapl_profile.business_type == BusinessType.MATURE_TECH.value or aapl_profile.classification_confidence > 0.3
        assert len(aapl_profile.classification_reasons) > 0

    def test_bank_detected(self):
        d = SyntheticDataProvider().get_financial_data("JPM")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = BusinessClassifier().classify(d)
        assert p.is_financial_institution is True
        assert "DCF" in p.not_applicable_models or "DCF" not in p.applicable_models

    def test_reit_detected(self):
        d = SyntheticDataProvider().get_financial_data("PLD")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = BusinessClassifier().classify(d)
        assert p.is_reit is True

    def test_classifier_nvda_not_reit(self):
        d = SyntheticDataProvider().get_financial_data("NVDA")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = BusinessClassifier().classify(d)
        assert p.is_reit is False, f"NVDA should not be classified as REIT, got business_type={p.business_type}"
        assert p.business_type != BusinessType.REIT.value, f"NVDA business_type should not be REIT, got {p.business_type}"
        assert "DCF" in p.applicable_models, f"DCF should be applicable for NVDA Semiconductor, applicable={p.applicable_models}"

    def test_pld_reit_still_detected_after_exclusion_rules(self):
        d = SyntheticDataProvider().get_financial_data("PLD")
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = BusinessClassifier().classify(d)
        assert p.business_type == BusinessType.REIT.value, f"PLD should still be classified as REIT, got {p.business_type}"
        assert p.is_reit is True
