"""P1 — EV(g) may be non-monotone; every turning point must be found.

A single grid maximum assumes unimodality. A curve with two peaks (or a peak
inside the band plus edge extremes) would hide the second turning point, and a
"best plausible growth" quoted at an edge the business type disallows would
contradict the band the report itself states.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from models.reverse_dcf import ReverseDCFModel


class _Model(ReverseDCFModel):
    def __init__(self, ev_fn):
        super().__init__()
        self._ev_fn = ev_fn

    def _project_ev(self, data, profile, rev_cagr, wacc, tg, horizon, nwc_ratio=None):
        return self._ev_fn(rev_cagr)


_DATA = SimpleNamespace(ttm=SimpleNamespace(revenue=100.0))
_PROFILE = SimpleNamespace(business_type="Unknown")


def _peaks(ev_fn, lo=-0.10, hi=0.30):
    return _Model(ev_fn)._ev_curve_peaks(_DATA, _PROFILE, 0.09, 0.02, 5, lo, hi)


class TestMultiPeakDetection:
    def test_unimodal_interior_peak_is_found_once(self):
        peaks = _peaks(lambda g: 100.0 - 5000.0 * (g - 0.10) ** 2)
        assert len(peaks) >= 1
        assert abs(peaks[0]["growth"] - 0.10) < 0.01
        assert peaks[0]["at_edge"] is False

    def test_monotone_curve_reports_the_high_edge(self):
        peaks = _peaks(lambda g: 100.0 + 900.0 * g)
        assert abs(peaks[0]["growth"] - 0.30) < 1e-6
        assert peaks[0]["at_edge"] is True

    def test_two_interior_peaks_are_both_reported(self):
        # Two separated humps. Two downward parabolas summed would still be a
        # single parabola, so use distinct bumps with a real valley between.
        def ev(g):
            return (
                100.0 * math.exp(-((g - 0.05) / 0.02) ** 2)
                + 80.0 * math.exp(-((g - 0.20) / 0.02) ** 2)
            )

        peaks = _peaks(ev, lo=-0.10, hi=0.40)
        growths = sorted(p["growth"] for p in peaks if not p["at_edge"])
        assert len(growths) >= 2, f"expected both humps, got {growths}"
        assert any(abs(g - 0.05) < 0.02 for g in growths)
        assert any(abs(g - 0.20) < 0.02 for g in growths)

    def test_global_max_is_first(self):
        def ev(g):
            return (
                100.0 * math.exp(-((g - 0.05) / 0.02) ** 2)
                + 60.0 * math.exp(-((g - 0.20) / 0.02) ** 2)
            )

        peaks = _peaks(ev, lo=-0.10, hi=0.40)
        assert peaks[0]["ev"] == max(p["ev"] for p in peaks)

    def test_peaks_are_deduplicated(self):
        peaks = _peaks(lambda g: 100.0 - 5000.0 * (g - 0.10) ** 2)
        growths = [round(p["growth"], 6) for p in peaks]
        assert len(growths) == len(set(growths))

    def test_empty_projection_returns_no_peaks(self):
        def ev(g):
            raise RuntimeError("boom")

        assert _peaks(ev) == []

    def test_degenerate_band_returns_single_point(self):
        peaks = _peaks(lambda g: 50.0 + g, lo=0.05, hi=0.05)
        assert len(peaks) == 1
        assert peaks[0]["at_edge"] is True


class TestPeakConfinedToPlausibilityBand:
    def test_solver_uses_plausibility_band_not_search_band(self):
        """The peak must be searched inside the band the report quotes.

        SO's EV peaks at 15% while its utility band is [-2%, 10%]; quoting the
        15% peak as "best plausible growth" contradicts the stated band.
        """
        src = open(
            "/workspace/telegram-stock-valuation-engine/models/reverse_dcf.py",
            encoding="utf-8",
        ).read()
        assert "plausible_lo" in src and "plausible_hi" in src
        # The scan window must come from the plausibility band.
        assert "scan_lo, scan_hi = band_lo, band_hi" in src
