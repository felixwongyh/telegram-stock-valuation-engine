"""Recover a *known* beta from synthetic prices, and prove date alignment.

A beta can be numerically plausible while being computed from misaligned data,
so this exercises the **production** ``_estimate_beta`` (via a fake HTTP client
that returns synthetic charts) rather than re-implementing the regression:

1. **Recovery** — when the target's monthly return is exactly
   ``beta × SPY return`` plus small idiosyncratic noise, the estimator must
   return that beta. This validates the estimator, not merely "a number".
2. **Date alignment** — prices are keyed by calendar period (month / ISO week)
   and the intersection is taken. A missing month on one side must therefore
   *reduce the sample*, never shift the pairing. That is asserted directly.
3. **Disjoint series** must yield ``None`` (insufficient overlap), never a beta.
"""

from __future__ import annotations

import datetime as dt
import random

import pytest

from data.providers import YahooFinanceProvider


class _FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Serves one synthetic chart per URL, keyed by ticker in the URL."""

    def __init__(self, charts):
        self._charts = charts

    def get(self, url, params=None, timeout=None):
        for ticker, chart in self._charts.items():
            if f"/chart/{ticker}" in url:
                return _FakeResponse({"chart": {"result": [chart]}})
        return _FakeResponse({"chart": {"result": []}})


def _next_month(d: dt.date) -> dt.date:
    y, m = d.year, d.month + 1
    if m > 12:
        y, m = y + 1, 1
    return dt.date(y, m, 15)


def _chart_from_prices(prices: list[float], start: dt.date) -> dict:
    """Build a Yahoo-shaped monthly chart (one point per calendar month)."""
    stamps, adj, d = [], [], start
    for px in prices:
        stamps.append(int(dt.datetime(d.year, d.month, 15).timestamp()))
        adj.append(px)
        d = _next_month(d)
    return {
        "timestamp": stamps,
        "indicators": {
            "adjclose": [{"adjclose": adj}],
            "quote": [{"close": adj}],
        },
    }


def _drop_month(chart: dict, idx: int) -> dict:
    """Return a copy of ``chart`` with the ``idx``-th monthly point removed."""
    adj = chart["indicators"]["adjclose"][0]["adjclose"]
    return {
        "timestamp": chart["timestamp"][:idx] + chart["timestamp"][idx + 1:],
        "indicators": {
            "adjclose": [{"adjclose": adj[:idx] + adj[idx + 1:]}],
            "quote": [{"close": adj[:idx] + adj[idx + 1:]}],
        },
    }


def _prices_from_returns(returns: list[float], start_px: float = 100.0):
    prices, px = [start_px], start_px
    for r in returns:
        px = px * (1.0 + r)
        prices.append(px)
    return prices


def _synthetic(beta: float, n_months: int = 36, seed: int = 11):
    """Return ``(target_chart, spy_chart)`` with target = beta × spy + noise."""
    rng = random.Random(seed)
    spy = [rng.gauss(0.008, 0.04) for _ in range(n_months)]
    tgt = [beta * r + rng.gauss(0.0, 0.0015) for r in spy]
    start = dt.date(2022, 1, 15)
    return (
        _chart_from_prices(_prices_from_returns(tgt), start),
        _chart_from_prices(_prices_from_returns(spy), start),
    )


def _estimate(tgt_chart, spy_chart):
    client = _FakeClient({"SPY": spy_chart, "TEST": tgt_chart})
    return YahooFinanceProvider._estimate_beta(
        chart=tgt_chart, client=client, ticker="TEST", range_="3y", interval="1mo"
    )


def _synthetic_noiseless(beta: float, n_months: int = 36, seed: int = 11):
    """Like ``_synthetic`` but with zero noise: target returns are *exactly* beta×spy.

    With noise the OLS estimate has an inherent sampling error, so a loose
    tolerance is honest there. Noiseless is the only setting where the estimator
    itself can be held to ~1e-6, which is what Master Validation §5 asks for.
    """
    rng = random.Random(seed)
    spy = [rng.gauss(0.008, 0.04) for _ in range(n_months)]
    tgt = [beta * r for r in spy]
    start = dt.date(2022, 1, 15)
    return (
        _chart_from_prices(_prices_from_returns(tgt), start),
        _chart_from_prices(_prices_from_returns(spy), start),
    )


@pytest.mark.parametrize("beta", [0.35, 0.93, 1.0, 1.65, 2.43])
def test_noiseless_beta_is_recovered_to_1e6(beta: float) -> None:
    """§5: on a noiseless synthetic series beta must return to ~1e-6.

    This guards the *estimator*, independent of market noise. It is tighter than
    the noisy test above on purpose: if the OLS path regressed (wrong alignment,
    missing intercept, dropped month), the noisy 2e-2 tolerance would still pass
    while this would not.
    """
    tgt, spy = _synthetic_noiseless(beta)
    out = _estimate(tgt, spy)
    assert out is not None
    assert out["beta"] == pytest.approx(beta, abs=1e-6), (
        f"noiseless beta {beta} recovered only to {abs(out['beta'] - beta):.3e}"
    )


@pytest.mark.parametrize("beta", [0.0, 0.35, 0.93, 1.0, 1.65, 2.43])
def test_known_beta_is_recovered(beta: float) -> None:
    """A series built with a known beta must regress back to it."""
    tgt, spy = _synthetic(beta)
    out = _estimate(tgt, spy)
    assert out is not None, "estimator returned None on a clean synthetic series"
    assert out["beta"] == pytest.approx(beta, abs=2e-2), (
        f"beta {beta} not recovered (got {out['beta']:.4f})"
    )
    prov = out["provenance"]
    assert prov["benchmark"] == "SPY"
    assert prov["n_observations"] == 36
    assert prov["missing_periods"] == 0
    assert prov["alignment_status"] == "ok"


def test_missing_month_reduces_sample_without_shifting_pairs() -> None:
    """Dropping a month from SPY must shrink n and keep the beta stable.

    Positional alignment would pair every later target return with the wrong SPY
    month and move the beta. Calendar-keyed alignment only loses that month.

    The beta is checked against the *known* 1.3, not only against ``full``: a
    misaligned estimator corrupts both runs, so a full-vs-partial comparison
    alone is blind to a uniform shift.
    """
    tgt, spy = _synthetic(1.3)
    full = _estimate(tgt, spy)
    partial = _estimate(tgt, _drop_month(spy, 11))

    assert partial is not None
    assert full["beta"] == pytest.approx(1.3, abs=0.05)
    assert partial["provenance"]["n_observations"] < full["provenance"]["n_observations"]
    assert partial["beta"] == pytest.approx(1.3, abs=0.05), (
        f"beta not recovered after a missing month: {partial['beta']:.4f} "
        "(alignment is positional, not calendar-keyed)"
    )
    assert partial["beta"] == pytest.approx(full["beta"], abs=0.02)


def test_disjoint_series_returns_none() -> None:
    """No overlapping months => no beta, rather than a fabricated one."""
    tgt, _spy = _synthetic(1.0)
    disjoint = _chart_from_prices(
        _prices_from_returns([0.01] * 35), dt.date(2015, 1, 15)
    )
    assert _estimate(tgt, disjoint) is None, "disjoint date ranges produced a beta"


def test_provenance_records_window_bounds() -> None:
    """The provenance must state the actual first/last aligned dates."""
    tgt, spy = _synthetic(0.9)
    prov = _estimate(tgt, spy)["provenance"]
    assert prov["window_start"] == "2022-01-15"
    assert prov["window_end"] == "2025-01-15"
    assert prov["price_basis"].startswith("adjclose")
