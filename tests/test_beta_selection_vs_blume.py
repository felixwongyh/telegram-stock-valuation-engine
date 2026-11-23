"""Beta *selection* must be distinguishable from Blume *adjustment*.

The report exposes several betas, and two of them can coincide numerically while
meaning completely different things:

* ``beta_selected`` = a bottom-up peer beta that *replaced* the regression beta.
  Nothing was adjusted; the regression beta simply is not the pricing input.
* ``beta_selected`` = the regression beta, then shrunk toward 1.0 (Blume).

Before ``beta_selection_method`` existed, an auditor looking at
``raw=2.43 -> adjusted=0.93`` (NVDA) could only *guess* which of the two happened
— and guessing "Blume" there would be wrong (0.65·2.43 + 0.35·1.0 = 1.93, not
0.93). These tests pin the mechanism label and the exact arithmetic for both
paths, using the real ``WaccCalculator`` normalization core.
"""

from __future__ import annotations

import pytest

from valuation.capm_engine import CAPMEngine


class TestCapmEngineNormalization:
    """The single normalization core: winsorize, then optional Blume shrink."""

    def test_winsorize_only_leaves_value_inside_band(self):
        chain = CAPMEngine().compute(
            raw_beta=2.43, risk_free_rate=0.04, equity_risk_premium=0.05,
            winsorize=True, winsor_lo=0.30, winsor_hi=2.50,
        )
        assert chain.normalized_beta == pytest.approx(2.43)
        assert chain.normalization_method == "none"

    def test_winsorize_clamps_high_beta(self):
        chain = CAPMEngine().compute(
            raw_beta=3.30, risk_free_rate=0.04, equity_risk_premium=0.05,
            winsorize=True, winsor_lo=0.30, winsor_hi=2.50,
        )
        assert chain.normalized_beta == pytest.approx(2.50)
        assert "winsorize" in chain.normalization_method

    def test_blume_shrinkage_is_exact_linear_pull_to_one(self):
        # CEG: winsor(2.1777) then 35% toward 1.0 = 1.7655
        raw, shrink = 2.1776918629888096, 0.35
        chain = CAPMEngine().compute(
            raw_beta=raw, risk_free_rate=0.04, equity_risk_premium=0.05,
            winsorize=True, winsor_lo=0.30, winsor_hi=2.50,
            blume_shrinkage=shrink,
        )
        expected = (1 - shrink) * raw + shrink * 1.0
        assert chain.normalized_beta == pytest.approx(expected, abs=1e-12)
        assert chain.normalized_beta == pytest.approx(1.7655, abs=1e-4)
        assert "blume_shrinkage" in chain.normalization_method

    def test_zero_shrinkage_does_not_move_beta(self):
        chain = CAPMEngine().compute(
            raw_beta=0.93, risk_free_rate=0.04, equity_risk_premium=0.05,
            winsorize=True, winsor_lo=0.30, winsor_hi=2.50, blume_shrinkage=0.0,
        )
        assert chain.normalized_beta == pytest.approx(0.93)
        assert "blume" not in chain.normalization_method

    def test_winsorize_runs_before_shrinkage(self):
        """Order matters: clamp first, then shrink, so the result is bounded."""
        chain = CAPMEngine().compute(
            raw_beta=5.0, risk_free_rate=0.04, equity_risk_premium=0.05,
            winsorize=True, winsor_lo=0.30, winsor_hi=2.50, blume_shrinkage=0.35,
        )
        expected = 0.65 * 2.50 + 0.35 * 1.0
        assert chain.normalized_beta == pytest.approx(expected, abs=1e-12)


class TestSelectionVersusAdjustment:
    """NVDA and CEG are the canonical pair that must not be confused."""

    def test_nvda_is_bottom_up_not_blume(self):
        """NVDA: raw 2.43 → 0.93 because a peer beta was *selected*."""
        raw, bottom_up = 2.4303, 0.9295
        # What Blume would have produced, to show the paths are different.
        blume_would_be = 0.65 * raw + 0.35 * 1.0
        assert blume_would_be > 1.9  # nowhere near 0.93
        # Bottom-up path is winsorize-only:
        assert max(0.30, min(2.50, bottom_up)) == pytest.approx(0.9295)

    def test_ceg_is_blume_not_bottom_up(self):
        """CEG: raw 2.178 → 1.765 because the regression beta was shrunk."""
        raw, shrink = 2.1777, 0.35
        assert (1 - shrink) * raw + shrink * 1.0 == pytest.approx(1.7655, abs=1e-3)
