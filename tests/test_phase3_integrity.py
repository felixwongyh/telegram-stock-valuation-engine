"""Tests for the Phase 3 valuation-integrity work (Session #21).

Covers three P1 hardening items:

  3.1  WACC β multi-window sensitivity (2Y weekly / 3Y & 5Y monthly) + a
       bottom-up β slot that stays ``None`` (never fabricated) when unsourced.
  3.2  Peer-multiple provenance labels + comparable sample size, so a fallback
       peer anchor cannot masquerade as an exact-industry match.
  3.3  Duplicate-evidence de-duplication: models sharing one underlying source
       (P/E ↔ Historical Multiples; EV/Sales ↔ EV/Sales (Unit Econ)) count as a
       single unit of independent evidence when gating agreement.
"""
from __future__ import annotations

from typing import Any, Dict, List

from analysis.model_agreement import (
    _AGREEMENT_ORDER,
    _independent_evidence,
    ModelAgreementAnalyzer,
)
from config import SolverStatus
from data.models import FinancialData, FinancialStatement, MarketData
from data.providers import YahooFinanceProvider
from models.base import ValuationResult
from models.multiples import (
    PEER_SOURCE_APPROXIMATE,
    PEER_SOURCE_BUSINESS_TYPE_FALLBACK,
    PEER_SOURCE_EXACT_INDUSTRY,
    PEER_SOURCE_LABELS,
    PEER_SOURCE_SECTOR_FALLBACK,
)
from valuation.wacc import WaccBreakdown, WaccCalculator


# ---------------------------------------------------------------------------
# 3.1 — β multi-window sensitivity
# ---------------------------------------------------------------------------
def _wacc_data(**market_kwargs) -> FinancialData:
    ttm = FinancialStatement(
        period_end="TTM", revenue=1e9, shares_outstanding=1e9, interest_expense=1e7,
    )
    market = MarketData(
        current_price=100.0, market_cap=1e10, total_debt=1e9,
        equity_risk_premium=0.05, risk_free_rate=0.045, beta=1.2, **market_kwargs,
    )
    return FinancialData(
        ticker="TEST", annual_income=[ttm], annual_balance_sheet=[],
        ttm=ttm, market=market,
    )


def test_beta_window_note_requires_two_windows():
    """A single (or zero) window cannot evidence stability → no note."""
    wb = WaccBreakdown(
        wacc=0.1, cost_of_equity=0.1, cost_of_debt=0.05, after_tax_cost_of_debt=0.04,
        effective_tax_rate=0.2, weight_equity=1.0, weight_debt=0.0, total_debt=0.0,
        market_cap=1.0, enterprise_value=1.0, risk_free_rate=0.04,
        equity_risk_premium=0.05, beta=1.0, industry_range_min=0.07,
        industry_range_max=0.12, industry_label="x", sanity_status="Within Range",
        beta_windows={"3y_monthly": 1.10},
    )
    assert wb.beta_window_note() is None
    wb.beta_windows = {}
    assert wb.beta_window_note() is None


def test_beta_window_note_reports_dispersion():
    wb = WaccBreakdown(
        wacc=0.1, cost_of_equity=0.1, cost_of_debt=0.05, after_tax_cost_of_debt=0.04,
        effective_tax_rate=0.2, weight_equity=1.0, weight_debt=0.0, total_debt=0.0,
        market_cap=1.0, enterprise_value=1.0, risk_free_rate=0.04,
        equity_risk_premium=0.05, beta=1.0, industry_range_min=0.07,
        industry_range_max=0.12, industry_label="x", sanity_status="Within Range",
        beta_windows={"2y_weekly": 2.20, "3y_monthly": 1.60, "5y_monthly": 1.55},
    )
    note = wb.beta_window_note()
    assert note is not None
    assert "极差 0.65" in note
    assert "波动较大" in note  # span 0.65 > 0.50 → flagged unstable


def test_wacc_calculator_populates_beta_windows_and_dispersion():
    data = _wacc_data(beta_windows={"2y_weekly": 1.40, "3y_monthly": 1.20, "5y_monthly": 1.10})
    wb = WaccCalculator().calculate(data)
    assert wb.beta_windows == {"2y_weekly": 1.40, "3y_monthly": 1.20, "5y_monthly": 1.10}
    assert wb.beta_dispersion is not None
    assert abs(wb.beta_dispersion - 0.30) < 1e-9
    assert "β (windows)" in wb.sources
    # The CAPM β must be unchanged by the sensitivity data (still the scalar β).
    assert abs(wb.cost_of_equity - (0.045 + 1.2 * 0.05)) < 1e-9


def test_wacc_without_windows_reports_none_honestly():
    data = _wacc_data()  # no beta_windows
    wb = WaccCalculator().calculate(data)
    assert wb.beta_windows is None
    assert wb.beta_dispersion is None
    assert wb.beta_window_note() is None
    assert "β (windows)" not in wb.sources


def test_wacc_bottom_up_beta_slot_absent_by_default():
    """No sourced peer β → the slot stays None (no fabricated value)."""
    data = _wacc_data()
    wb = WaccCalculator().calculate(data)
    assert wb.beta_bottom_up is None
    assert "N/A" in wb.beta_transparency_note()


class _FakeResp:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self) -> Any:
        return self._payload


def _series(interval: str, n: int):
    """Target closes = 2× SPY returns → regression β must be ≈ 2.0."""
    import math

    step = 7 * 86400 if interval == "1wk" else 30 * 86400
    base = 1_600_000_000
    ts: List[int] = []
    spy: List[float] = []
    tgt: List[float] = []
    s = 100.0
    t = 100.0
    for i in range(n):
        ts.append(base + i * step)
        if i > 0:
            r = 0.01 * math.sin(i)
            s *= (1.0 + r)
            t *= (1.0 + 2.0 * r)
        spy.append(s)
        tgt.append(t)
    return ts, spy, tgt


class _FakeClient:
    """Serves SPY or the target chart keyed off the requested interval."""

    def __init__(self) -> None:
        self.calls: List[tuple] = []

    def get(self, url: str, params: Dict[str, Any] | None = None, timeout: int | None = None):
        interval = (params or {}).get("interval", "1mo")
        n = 60 if interval == "1wk" else 45
        ts, spy, tgt = _series(interval, n)
        closes = spy if "SPY" in url else tgt
        self.calls.append((url, interval))
        chart = {"timestamp": ts, "indicators": {"quote": [{"close": closes}]}}
        return _FakeResp({"chart": {"result": [chart]}})


def test_provider_beta_weekly_keying():
    """Weekly windows must key per ISO week; otherwise 60 weekly points collapse
    to ~14 monthly keys and the estimate is wrongly rejected."""
    client = _FakeClient()
    ts, _spy, tgt = _series("1wk", 60)
    tgt_chart = {"timestamp": ts, "indicators": {"quote": [{"close": tgt}]}}

    weekly = YahooFinanceProvider._estimate_beta(
        tgt_chart, client, "TEST", range_="2y", interval="1wk", min_obs=40,
    )
    assert weekly is not None and abs(weekly["beta"] - 2.0) < 1e-6

    # Same weekly-spaced chart read as monthly collapses to < min_obs → None.
    monthly = YahooFinanceProvider._estimate_beta(
        tgt_chart, client, "TEST", range_="2y", interval="1mo", min_obs=40,
    )
    assert monthly is None


def test_provider_estimate_beta_windows_returns_all_windows():
    client = _FakeClient()
    windows = YahooFinanceProvider._estimate_beta_windows(client, "TEST")
    assert set(windows) == {"2y_weekly", "3y_monthly", "5y_monthly"}
    for label, beta in windows.items():
        assert beta is not None, label
        # ≈2.0; monthly calendars occasionally collapse two 30-day samples into
        # one month key, so allow a small tolerance rather than an exact match.
        assert abs(beta - 2.0) < 0.01, label


# ---------------------------------------------------------------------------
# 3.2 — peer-multiple provenance
# ---------------------------------------------------------------------------
def test_peer_source_labels_are_a_closed_set():
    labels = {
        PEER_SOURCE_EXACT_INDUSTRY,
        PEER_SOURCE_SECTOR_FALLBACK,
        PEER_SOURCE_BUSINESS_TYPE_FALLBACK,
        PEER_SOURCE_APPROXIMATE,
    }
    assert labels == set(PEER_SOURCE_LABELS)


def test_multiples_breakdown_carries_peer_provenance():
    """Every successful relative multiple must declare its peer source kind and
    sample size (or an explicit None for static anchors)."""
    from tests.golden_report import run_pipeline

    ctx = run_pipeline("AAPL")
    seen = 0
    for name, r in ctx["model_results"].items():
        bd = getattr(r, "breakdown", None) or {}
        if "peer_source_kind" not in bd:
            continue
        seen += 1
        assert bd["peer_source_kind"] in PEER_SOURCE_LABELS, name
        assert "peer_sample_size" in bd, name
        n = bd["peer_sample_size"]
        assert n is None or (isinstance(n, int) and n > 0), name
    assert seen >= 1


def test_approximate_peer_reroute_reports_sample_size():
    """A compute-infrastructure re-route must be labelled APPROXIMATE and expose
    the peer-group size (never a bare value with no provenance)."""
    from tests.golden_report import run_pipeline

    ctx = run_pipeline("NBIS")
    approx = [
        (name, r.breakdown)
        for name, r in ctx["model_results"].items()
        if (getattr(r, "breakdown", None) or {}).get("peer_source_kind")
        == PEER_SOURCE_APPROXIMATE
    ]
    assert approx, "NBIS should exercise the AI/cloud approximate re-route"
    for _name, bd in approx:
        assert bd["peer_sample_size"] is not None and bd["peer_sample_size"] > 0


# ---------------------------------------------------------------------------
# 3.3 — duplicate-evidence de-duplication
# ---------------------------------------------------------------------------
def test_independent_evidence_groups_duplicate_families():
    n, dup = _independent_evidence({"P/E": 100.0, "Historical Multiples": 101.0})
    assert n == 1
    assert dup == {"earnings_multiple": ["P/E", "Historical Multiples"]}


def test_independent_evidence_counts_unique_models_individually():
    solved = {"DCF": 1.0, "EV/EBITDA": 2.0, "P/B": 3.0}
    n, dup = _independent_evidence(solved)
    assert n == 3
    assert dup == {}


def _result(name: str, value: float, status: SolverStatus = SolverStatus.SOLVED) -> ValuationResult:
    return ValuationResult(model_name=name, status=status, value_per_share=value)


def test_agreement_dedups_duplicate_family_for_cap():
    """4 solved models but only 3 independent sources → the coverage cap must
    apply as if 3 (Moderate), so a duplicated family cannot buy 'Very Strong'."""
    results = {
        "DCF": _result("DCF", 100.0),
        "P/E": _result("P/E", 102.0),
        "Historical Multiples": _result("Historical Multiples", 101.0),
        "EV/EBITDA": _result("EV/EBITDA", 103.0),
    }
    ma = ModelAgreementAnalyzer().analyze(results, current_price=100.0)
    assert ma.n_solved == 4
    assert ma.n_independent_evidence == 3
    assert "earnings_multiple" in ma.duplicate_evidence_groups
    # Cap for 3 independent sources is Moderate; the raw CV is tiny (Very Strong).
    assert ma.agreement_level_raw == "Very Strong"
    assert _AGREEMENT_ORDER.index(ma.agreement_level) >= _AGREEMENT_ORDER.index("Moderate")
    assert any("独立证据计数" in n for n in ma.notes)


def test_agreement_no_dedup_note_without_duplicates():
    results = {
        "DCF": _result("DCF", 100.0),
        "EV/EBITDA": _result("EV/EBITDA", 101.0),
        "P/B": _result("P/B", 102.0),
        "SOTP": _result("SOTP", 99.0),
    }
    ma = ModelAgreementAnalyzer().analyze(results, current_price=100.0)
    assert ma.n_independent_evidence == 4
    assert ma.duplicate_evidence_groups == {}
    assert not any("独立证据计数" in n for n in ma.notes)
