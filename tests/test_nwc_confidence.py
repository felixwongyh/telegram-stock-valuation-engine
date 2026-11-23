"""Tests for the NWC confidence taxonomy.

The taxonomy is the single gate on direction claims, so the tests focus on the
gate: every class that must not license a direction is checked to not do so,
and the reason strings must name why.
"""
import pytest

from analysis.nwc_confidence import (
    MECHANISM_UNCONFIRMED,
    NWC_DIRECT,
    NWC_ESTIMATE_CONFLICT,
    NWC_INTENSITY_PROXY,
    NWC_ROBUST_MARGINAL,
    RECOMMENDED_ANNUAL_YEARS,
    classify_nwc_confidence,
)


def _rec(*, level=None, level_n=0, intensity=None, robust=None, robust_n=0,
         conflict=False, spread=None):
    return {
        "level": {"value": level, "n_observations": level_n},
        "intensity": {"value": intensity, "n_observations": level_n},
        "robust_marginal": {"value": robust, "n_observations": robust_n},
        "estimates_conflict": conflict,
        "marginal_spread": spread,
    }


class TestClassification:
    def test_direct_when_level_and_robust_available(self):
        out = classify_nwc_confidence(
            _rec(level=0.2, level_n=4, robust=0.15, robust_n=3), 4, True
        )
        assert out["kind"] == NWC_DIRECT
        assert out["can_claim_direction"] is True

    def test_robust_marginal_when_no_level(self):
        out = classify_nwc_confidence(
            _rec(robust=0.2, robust_n=4), 4, True
        )
        assert out["kind"] == NWC_ROBUST_MARGINAL

    def test_intensity_proxy_when_only_intensity(self):
        out = classify_nwc_confidence(_rec(intensity=0.02, level_n=4), 4, None)
        assert out["kind"] == NWC_INTENSITY_PROXY
        assert out["can_claim_direction"] is False

    def test_conflict_overrides_strongest_evidence(self):
        """Conflict must win even when a level ratio exists."""
        out = classify_nwc_confidence(
            _rec(level=0.2, level_n=4, robust=0.2, robust_n=4, conflict=True,
                 spread=1.2),
            4, True,
        )
        assert out["kind"] == NWC_ESTIMATE_CONFLICT
        assert out["can_claim_direction"] is False

    def test_unconfirmed_when_nothing(self):
        out = classify_nwc_confidence(_rec(), 4, None)
        assert out["kind"] == MECHANISM_UNCONFIRMED
        assert out["can_claim_direction"] is False


class TestDirectionGate:
    def test_direct_but_unstable_sweep_cannot_claim(self):
        out = classify_nwc_confidence(
            _rec(level=0.2, level_n=4, robust=0.15, robust_n=3), 4, False
        )
        assert out["kind"] == NWC_DIRECT
        assert out["can_claim_direction"] is False
        assert any("翻转" in n for n in out["notes"])

    def test_direct_with_unevaluated_sweep_cannot_claim(self):
        out = classify_nwc_confidence(
            _rec(level=0.2, level_n=4, robust=0.15, robust_n=3), 4, None
        )
        assert out["can_claim_direction"] is False

    def test_robust_but_unstable_cannot_claim(self):
        out = classify_nwc_confidence(_rec(robust=0.2, robust_n=4), 4, False)
        assert out["kind"] == NWC_ROBUST_MARGINAL
        assert out["can_claim_direction"] is False


class TestThresholds:
    def test_level_needs_minimum_periods(self):
        out = classify_nwc_confidence(
            _rec(level=0.2, level_n=2, robust=0.15, robust_n=3), 4, True
        )
        assert out["kind"] != NWC_DIRECT

    def test_marginal_needs_minimum_pairs(self):
        out = classify_nwc_confidence(
            _rec(level=0.2, level_n=4, robust=0.15, robust_n=2), 4, True
        )
        assert out["kind"] != NWC_DIRECT

    def test_short_history_noted(self):
        out = classify_nwc_confidence(
            _rec(level=0.2, level_n=4, robust=0.15, robust_n=3), 4, True
        )
        assert any(str(RECOMMENDED_ANNUAL_YEARS) in n for n in out["notes"])

    def test_long_history_not_noted(self):
        out = classify_nwc_confidence(
            _rec(level=0.2, level_n=6, robust=0.15, robust_n=5), 6, True
        )
        assert out["notes"] == []


def test_every_kind_has_a_label():
    from analysis.nwc_confidence import LABELS
    for kind in (NWC_DIRECT, NWC_ROBUST_MARGINAL, NWC_INTENSITY_PROXY,
                 NWC_ESTIMATE_CONFLICT, MECHANISM_UNCONFIRMED):
        assert kind in LABELS
        assert LABELS[kind]


def test_result_is_serialisable():
    out = classify_nwc_confidence(_rec(level=0.2, level_n=4, robust=0.1,
                                       robust_n=3), 4, True)
    for key in ("kind", "label", "reason", "can_claim_direction",
                "n_annual_periods", "notes"):
        assert key in out


@pytest.mark.parametrize("conflict", [True, False])
def test_conflict_class_never_claims_direction(conflict):
    out = classify_nwc_confidence(
        _rec(level=0.2, level_n=4, robust=0.2, robust_n=4, conflict=conflict),
        4, True,
    )
    if conflict:
        assert out["can_claim_direction"] is False


# --- History-length grading (review requirement) ---------------------------

def test_history_grade_boundaries():
    from analysis.nwc_confidence import history_grade
    assert history_grade(0) == "INSUFFICIENT"
    assert history_grade(2) == "INSUFFICIENT"
    assert history_grade(3) == "INDICATIVE"
    assert history_grade(4) == "INDICATIVE"
    assert history_grade(5) == "PROVISIONAL"
    assert history_grade(7) == "PROVISIONAL"
    assert history_grade(8) == "MORE_ESTABLISHED"
    assert history_grade(40) == "MORE_ESTABLISHED"


def test_three_pairs_is_not_established_evidence():
    """A 'robust' statistic on 3 pairs is still 3 observations."""
    out = classify_nwc_confidence(
        _rec(level=0.2, level_n=4, robust=0.2, robust_n=3), 4, True
    )
    assert out["history_grade"] == "INDICATIVE"
    assert out["claim_strength"] == "indicative"
    assert any("指示性" in n for n in out["notes"])


def test_five_pairs_reaches_provisional():
    out = classify_nwc_confidence(
        _rec(level=0.2, level_n=6, robust=0.2, robust_n=5), 6, True
    )
    assert out["history_grade"] == "PROVISIONAL"
    assert out["claim_strength"] == "established"


def test_eight_pairs_is_more_established():
    out = classify_nwc_confidence(
        _rec(level=0.2, level_n=9, robust=0.2, robust_n=8), 9, True
    )
    assert out["history_grade"] == "MORE_ESTABLISHED"
    assert out["claim_strength"] == "established"


def test_insufficient_history_suppresses_direction():
    out = classify_nwc_confidence(
        _rec(level=0.2, level_n=3, robust=0.2, robust_n=2), 3, True
    )
    assert out["can_claim_direction"] is False
    assert out["claim_strength"] == "none"


def test_robust_name_does_not_upgrade_grade():
    """NWC_ROBUST_MARGINAL on thin data must not claim 'established'."""
    out = classify_nwc_confidence(_rec(robust=0.2, robust_n=3), 4, True)
    assert out["kind"] == NWC_ROBUST_MARGINAL
    assert out["claim_strength"] == "indicative"


def test_claim_strength_is_serialisable():
    out = classify_nwc_confidence(
        _rec(level=0.2, level_n=4, robust=0.2, robust_n=3), 4, True
    )
    assert "claim_strength" in out
    assert "history_grade" in out
    assert "history_grade_label" in out


# --- Grade framing: policy, not statistical law ----------------------------

def test_grade_is_labelled_as_policy_not_law():
    """The grade table is a product policy; the payload must say so."""
    from analysis.nwc_confidence import GRADE_IS_POLICY, GRADE_POLICY_NOTE
    assert GRADE_IS_POLICY is True
    assert "政策" in GRADE_POLICY_NOTE
    assert "不是统计学定律" in GRADE_POLICY_NOTE
    out = classify_nwc_confidence(
        _rec(level=0.2, level_n=9, robust=0.2, robust_n=8), 9, True
    )
    assert out["grade_is_policy"] is True
    assert out["grade_policy_note"] == GRADE_POLICY_NOTE


def test_more_established_does_not_claim_proof():
    """8+ pairs must not be worded as 'proven correct'."""
    from analysis.nwc_confidence import HISTORY_GRADE_LABELS, HISTORY_MORE_ESTABLISHED
    label = HISTORY_GRADE_LABELS[HISTORY_MORE_ESTABLISHED]
    assert "非已证明正确" in label
    assert "已确立" not in label
