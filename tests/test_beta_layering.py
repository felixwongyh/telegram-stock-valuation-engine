"""Acceptance tests for the β three-layer separation and its statistics.

Why this exists
---------------
The report used to show one number for β with no way to tell whether it was

  * the raw regression estimate,
  * a risk-adjusted value, or
  * the value the valuation actually used (after the [0.30, 2.50] band).

That mattered because a defensive name can regress to β ≈ 0.00 with a standard
error of 0.23 — a number that carries no information — and then be displayed as
0.30 as if it did. The data-alignment hypothesis was tested first and *rejected*:
the estimator already regresses simple returns on adjusted close, keyed by
month/week, so a negative β is real statistics, not a join bug. These tests pin
that (a) the alignment is returns-on-returns with period keys, and (b) the
uncertainty is now visible instead of being silently absorbed by the band.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest

from data.providers import YahooFinanceProvider


class _Resp:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self) -> Any:
        return self._payload


def _series(interval: str, n: int, beta: float, noise: float = 0.0):
    """Target returns = beta × SPY returns (+ optional independent noise).

    Monthly steps use 28 days: short enough that every sample lands in the *next*
    calendar month (no key collapse, no skipped month), which keeps the
    estimator's own gap detector quiet.
    """
    step = 7 * 86400 if interval == "1wk" else 28 * 86400
    base = 1_600_000_000
    ts: List[int] = []
    spy: List[float] = []
    tgt: List[float] = []
    s = t = 100.0
    for i in range(n):
        ts.append(base + i * step)
        if i > 0:
            r = 0.01 * math.sin(i)
            s *= (1.0 + r)
            t *= (1.0 + beta * r + noise * math.cos(3.1 * i))
        spy.append(s)
        tgt.append(t)
    return ts, spy, tgt


class _Client:
    def __init__(self, beta: float, noise: float = 0.0) -> None:
        self._beta = beta
        self._noise = noise

    def get(self, url: str, params: Dict[str, Any] | None = None, timeout: int | None = None):
        interval = (params or {}).get("interval", "1mo")
        n = 60 if interval == "1wk" else 45
        ts, spy, tgt = _series(interval, n, self._beta, self._noise)
        closes = spy if "SPY" in url else tgt
        chart = {"timestamp": ts, "indicators": {"quote": [{"close": closes}]}}
        return _Resp({"chart": {"result": [chart]}})


def _estimate(beta: float, noise: float = 0.0, **kw):
    ts, _spy, tgt = _series("1mo", 45, beta, noise)
    chart = {"timestamp": ts, "indicators": {"quote": [{"close": tgt}]}}
    return YahooFinanceProvider._estimate_beta(
        chart, _Client(beta, noise), "TEST", range_="3y", interval="1mo", **kw
    )


class TestBetaIsReturnsOnReturns:
    """Rule out the data-alignment hypothesis before touching the model."""

    def test_alignment_is_recorded_as_ok(self):
        res = _estimate(1.5)
        prov = res["provenance"]
        assert prov["missing_periods"] == 0
        assert prov["alignment_status"] == "ok"
        assert prov["return_frequency"] == "monthly"
        assert prov["regression_period"] == "3Y"

    def test_recovers_a_known_slope(self):
        # Tolerance reflects a real effect, not slop: a 28-day sample step drifts
        # against calendar months, so a few samples share a month key and the
        # estimator keeps 40 of 44 points. The recovered slope still has to be
        # right to ~0.1%, which is far tighter than any valuation cares about.
        res = _estimate(1.5)
        assert res["beta"] == pytest.approx(1.5, abs=2e-3)

    def test_price_basis_prefers_adjusted_close(self):
        # A split/dividend-unadjusted series would break the slope; the estimator
        # must prefer adjclose when the feed provides it.
        res = _estimate(1.2)
        assert "adjclose" in res["provenance"]["price_basis"] or res[
            "provenance"
        ]["price_basis"]


class TestBetaStatisticalDiagnostics:
    """A point estimate without uncertainty is not evidence."""

    def test_noiseless_fit_is_perfectly_explained(self):
        res = _estimate(1.5)
        prov = res["provenance"]
        assert prov["beta_r_squared"] == pytest.approx(1.0, abs=1e-4)
        assert prov["beta_standard_error"] == pytest.approx(0.0, abs=1e-3)
        assert prov["beta_significant"] is True

    def test_noisy_fit_reports_low_r2_and_wide_error(self):
        res = _estimate(0.0, noise=0.05)
        prov = res["provenance"]
        assert prov["beta_r_squared"] < 0.2, "independent noise must not be 'explained'"
        assert prov["beta_standard_error"] > 0.05
        assert prov["beta_significant"] is False, (
            "β≈0 with a wide SE must not be reported as a significant slope"
        )

    def test_significant_slope_is_flagged(self):
        res = _estimate(1.5, noise=0.002)
        assert res["provenance"]["beta_significant"] is True

    def test_negative_beta_is_reported_not_swallowed(self):
        """A genuinely negative slope must survive to the caller unchanged.

        This is the KO/DUK case: the raw regression really is negative. The
        estimator must not 'fix' it — the band is applied later and disclosed.
        """
        res = _estimate(-0.4)
        assert res["beta"] == pytest.approx(-0.4, abs=2e-3)

    def test_diagnostics_are_present_for_every_window(self):
        client = _Client(1.5)
        prov: Dict[str, Dict[str, Any]] = {}
        YahooFinanceProvider._estimate_beta_windows(client, "TEST", provenance_out=prov)
        assert prov, "window provenance must be captured"
        for label, p in prov.items():
            if not p:
                continue
            assert "beta_r_squared" in p, label
            assert "beta_standard_error" in p, label


class TestCrossWindowConfidence:
    def test_agreeing_windows_grade_high(self):
        out = YahooFinanceProvider._build_beta_provenance(
            "regression", None, None,
            {"2y_weekly": {"beta": 1.10}, "3y_monthly": {"beta": 1.12},
             "5y_monthly": {"beta": 1.08}},
        )
        assert out["beta_confidence"] == "high"
        assert out["cross_window_spread"] == pytest.approx(0.04, abs=1e-6)

    def test_disagreeing_windows_grade_low_with_note(self):
        # KO-like dispersion: 0.08 / -0.03 / 0.22
        out = YahooFinanceProvider._build_beta_provenance(
            "regression", None, None,
            {"2y_weekly": {"beta": 0.0772}, "3y_monthly": {"beta": -0.0284},
             "5y_monthly": {"beta": 0.2197}},
        )
        assert out["beta_confidence"] == "low"
        assert "beta_confidence_note" in out
        assert out["cross_window_spread"] > 0.20

    def test_single_window_cannot_be_graded(self):
        out = YahooFinanceProvider._build_beta_provenance(
            "regression", None, None, {"3y_monthly": {"beta": 1.0}},
        )
        assert "beta_confidence" not in out
