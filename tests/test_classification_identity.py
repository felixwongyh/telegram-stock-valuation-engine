"""
tests/test_classification_identity.py — Phase 1.3: identity vs economics

Business Identity  = what the company sells / to whom (external fact from the
                     provider's sector/industry).
Business Economics = margin / capex / leverage shape (ML + structural features).

The defect under test: high gross margin + high capex + low leverage being
treated as *proof* that a company is a Semiconductor, producing false certainty
when the statistical top-1 is ambiguous and disagrees with the identity.
"""
from __future__ import annotations

import pytest

from config import BusinessType
from classification.classifier import (
    CLASSIFICATION_STATUS_AMBIGUOUS,
    CLASSIFICATION_STATUS_CONFIDENT,
    IDENTITY_CONFLICT_RATIO_FLOOR,
    resolve_identity_economics_status,
)
from data import DataValidator, FinancialNormalizer, SyntheticDataProvider


def _load(ticker: str):
    d = SyntheticDataProvider().get_financial_data(ticker)
    d = FinancialNormalizer.normalize_all(d)
    d = DataValidator.validate(d)
    return d


class TestResolveIdentityEconomicsStatus:
    """Deterministic contract tests for the state machine."""

    def test_shape_driven_semiconductor_conflict_is_ambiguous(self):
        """MSFT-like: ML says Semiconductor 57.2% / MatureTech 32.3% while the
        identity is Software. Ratio 1.77 < 2 → must not be confident."""
        status, route, note = resolve_identity_economics_status(
            "Semiconductor", 0.572, 0.323, "Technology", "Software - Infrastructure",
        )
        assert status == CLASSIFICATION_STATUS_AMBIGUOUS
        # Conservative broad large-cap tech route, never the Semiconductor label.
        assert route == BusinessType.MATURE_TECH
        assert note and "Semiconductor" in note

    def test_decisive_ratio_is_confident_despite_conflict(self):
        """A decisive top-1 (ratio ≥ 2) is not ambiguous even if it disagrees."""
        status, route, note = resolve_identity_economics_status(
            "Semiconductor", 0.80, 0.10, "Technology", "Software - Infrastructure",
        )
        assert status == CLASSIFICATION_STATUS_CONFIDENT
        assert route is None
        assert note is None

    def test_identity_agreement_is_confident(self):
        """NVDA-like: identity is Semiconductors → no conflict."""
        status, route, _ = resolve_identity_economics_status(
            "Semiconductor", 0.57, 0.32, "Technology", "Semiconductors",
        )
        assert status == CLASSIFICATION_STATUS_CONFIDENT
        assert route is None

    def test_cross_family_conflict_routes_to_identity(self):
        """A mis-shaped bank must never become a tech prototype."""
        status, route, _ = resolve_identity_economics_status(
            "Semiconductor", 0.55, 0.35, "Financial Services", "Banks - Diversified",
        )
        assert status == CLASSIFICATION_STATUS_AMBIGUOUS
        assert route == BusinessType.BANK

    def test_non_semiconductor_tech_conflict_routes_to_identity(self):
        """A conflict that is *not* a semiconductor over-claim trusts identity."""
        status, route, _ = resolve_identity_economics_status(
            "Media", 0.45, 0.40, "Communication Services", "Telecom Services",
        )
        assert status == CLASSIFICATION_STATUS_AMBIGUOUS
        assert route == BusinessType.TELECOM

    def test_missing_identity_is_confident(self):
        """No sector/industry → no identity to conflict with → confident."""
        status, route, note = resolve_identity_economics_status(
            "Semiconductor", 0.50, 0.40, None, None,
        )
        assert status == CLASSIFICATION_STATUS_CONFIDENT
        assert route is None and note is None

    def test_ratio_floor_boundary_is_exclusive(self):
        """ratio exactly at the floor is NOT ambiguous (floor is exclusive-below)."""
        top2 = 0.25
        top1 = top2 * IDENTITY_CONFLICT_RATIO_FLOOR
        status, _, _ = resolve_identity_economics_status(
            "Semiconductor", top1, top2, "Technology", "Software",
        )
        assert status == CLASSIFICATION_STATUS_CONFIDENT

    def test_zero_top2_never_divides_by_zero(self):
        status, route, _ = resolve_identity_economics_status(
            "Semiconductor", 0.9, 0.0, "Technology", "Software",
        )
        assert status == CLASSIFICATION_STATUS_CONFIDENT
        assert route is None


class TestClassifierIdentityRegression:
    """Acceptance criterion 4 across the required regression universe."""

    @pytest.fixture(scope="class")
    def hybrid(self):
        from classification import MLHybridClassifier
        c = MLHybridClassifier()
        ok, msg = c.ensure_ready()
        assert ok, f"ML classifier should initialize: {msg}"
        return c

    @pytest.mark.parametrize("ticker", ["MSFT", "GOOGL", "AMZN", "NBIS", "CRWV"])
    def test_ambiguous_never_silently_routes_to_semiconductor(self, hybrid, ticker):
        p = hybrid.classify(_load(ticker))
        assert p.classification_status in (
            CLASSIFICATION_STATUS_CONFIDENT, CLASSIFICATION_STATUS_AMBIGUOUS,
        )
        if p.classification_status == CLASSIFICATION_STATUS_AMBIGUOUS:
            assert p.classification_conflict_note
            assert p.effective_business_type != BusinessType.SEMICONDUCTOR.value

    def test_microsoft_not_classified_semiconductor(self, hybrid):
        """Microsoft must not be Semiconductor merely from high capex + margin."""
        p = hybrid.classify(_load("MSFT"))
        assert p.business_type != BusinessType.SEMICONDUCTOR.value
        assert p.effective_business_type != BusinessType.SEMICONDUCTOR.value

    def test_nvidia_remains_semiconductor(self, hybrid):
        p = hybrid.classify(_load("NVDA"))
        assert p.business_type == BusinessType.SEMICONDUCTOR.value

    def test_rule_classifier_sets_identity_fields(self):
        """The deterministic rule path must also populate the new contract."""
        from classification.classifier import BusinessClassifier
        p = BusinessClassifier().classify(_load("MSFT"))
        assert p.classification_status in (
            CLASSIFICATION_STATUS_CONFIDENT, CLASSIFICATION_STATUS_AMBIGUOUS,
        )
        # MSFT identity = Technology/Software → mature tech family.
        assert p.identity_business_type == BusinessType.MATURE_TECH.value

    def test_wiring_applies_conservative_route_when_ml_conflicts(self, hybrid, monkeypatch):
        """End-to-end: a raw ML top-1 of Semiconductor against a Software identity
        must route the valuation conservatively (broad tech), not silently keep
        the Semiconductor prototype. Exercises the ML-path wiring directly."""
        d = _load("MSFT")

        def _stub_predict(_data):
            probs = {bt.value: 0.0 for bt in BusinessType}
            probs[BusinessType.SEMICONDUCTOR.value] = 0.572
            probs[BusinessType.MATURE_TECH.value] = 0.323
            probs[BusinessType.SAAS.value] = 0.105
            return {
                "probabilities": probs,
                "top1": BusinessType.SEMICONDUCTOR.value,
                "top1_prob": 0.572,
                "top2": BusinessType.MATURE_TECH.value,
                "top2_prob": 0.323,
                "model_version": "test-stub",
            }

        monkeypatch.setattr(hybrid._ml, "predict", _stub_predict)
        p = hybrid.classify(d)
        assert p.classification_status == CLASSIFICATION_STATUS_AMBIGUOUS
        assert p.classification_conflict_note
        assert p.effective_business_type == BusinessType.MATURE_TECH.value
        assert p.business_type != BusinessType.SEMICONDUCTOR.value
