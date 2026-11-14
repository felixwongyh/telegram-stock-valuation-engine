"""Tests for the Phase 4 valuation-integrity work (Session #22).

Phase 4 is the *acceptance* pass over the whole refactor. It locks in the
decision-level guarantees the earlier phases promised, at the level where they
were previously only checked by reading a rendered report:

  * Criterion 1/2 — a core model (DCF) dropped by the IQR filter must surface as
    an *unresolved disagreement*, never as a strong-consensus label, and the
    agreement cap is gated on *independent evidence* (Phase 3.3), not the raw
    solved count.
  * Criterion 3 — the risk severity FLOOR: a High flag can never yield an overall
    "Low" label just because the additive score stayed high.
  * Criterion 6 — the report must distinguish raw solved / IQR-excluded / final
    aggregation counts (raw == survivors + outliers).
  * Criterion 7 — the whole regression universe keeps the invariants that the
    earlier phases established (coverage identity, β single-source, calibration).
  * Criteria 8/9 — a missing peer identity must never be labelled an EXACT
    industry match (no fabricated comparables).
  * Criterion 10 — every rendered percentage direction agrees with its base.
"""
from __future__ import annotations

from typing import Optional

from analysis.model_agreement import (
    ModelAgreementAnalyzer,
    _MATERIAL_DISAGREEMENT,
)
from analysis.risk import RiskAnalyzer, _SEVERITY_ORDER
from config import SolverStatus
from models.base import ValuationResult
from models.multiples import (
    PEER_SOURCE_EXACT_INDUSTRY,
    PEER_SOURCE_LABELS,
    MultiplesModel,
)
from tests.golden_report import BASKET, build_fingerprint, check_invariants, run_pipeline

_STRONG_LEVELS = ("Very Strong", "Strong")


def _result(
    name: str,
    value: float,
    status: SolverStatus = SolverStatus.SOLVED,
    breakdown: Optional[dict] = None,
) -> ValuationResult:
    return ValuationResult(
        model_name=name, status=status, value_per_share=value,
        breakdown=breakdown or {},
    )


# ---------------------------------------------------------------------------
# Criterion 3 — risk severity floor
# ---------------------------------------------------------------------------
def test_severity_floor_never_safer_than_worst_flag():
    """Across the whole universe the overall label can be no safer than the
    worst *genuine* (non-provenance) flag, and `severity_floor` records it."""
    for t in BASKET:
        r = run_pipeline(t)["risk"]
        worst = 0
        for f in r.flags:
            if getattr(f, "is_provenance", False):
                continue
            assert f.severity in _SEVERITY_ORDER, (t, f.severity)
            worst = max(worst, _SEVERITY_ORDER.index(f.severity))
        assert _SEVERITY_ORDER.index(r.overall_severity) >= worst, t
        assert r.severity_floor == _SEVERITY_ORDER[worst], t


def test_high_flag_forces_overall_at_least_high():
    """A guaranteed High flag (suppressed terminal FCF) must lift the overall
    label to at least High, regardless of the additive score."""
    ctx = run_pipeline("AAPL")
    r = RiskAnalyzer().analyze(ctx["data"], {"terminal_fcf_negative": True}, ctx["profile"])
    assert any(
        f.risk_type == "Terminal Value Risk" and f.severity == "High" for f in r.flags
    ), "expected a High terminal-value flag"
    assert r.severity_floor == "High"
    assert _SEVERITY_ORDER.index(r.overall_severity) >= _SEVERITY_ORDER.index("High")


def test_severity_floor_actually_engages_in_universe():
    """The floor must not be a no-op: somewhere in the regression universe a
    High flag lifts the label *above* what the raw score alone would give."""
    engaged = []
    for t in BASKET:
        r = run_pipeline(t)["risk"]
        if _SEVERITY_ORDER.index(r.overall_severity) > _SEVERITY_ORDER.index(
            r.overall_severity_by_score
        ):
            engaged.append(t)
    assert engaged, "severity floor never changed a label in the regression universe"


# ---------------------------------------------------------------------------
# Criteria 1/2 — core-model IQR exclusion ⇒ unresolved disagreement
# ---------------------------------------------------------------------------
def test_iqr_excluded_core_model_is_unresolved_disagreement():
    """A DCF far outside a tight multiple cluster is removed by IQR; the report
    must then say the disagreement is *unresolved*, not cap silently."""
    results = {
        "DCF": _result("DCF", 300.0),
        "EV/EBITDA": _result("EV/EBITDA", 100.0),
        "P/E": _result("P/E", 101.0),
        "P/B": _result("P/B", 102.0),
        "EV/Sales": _result("EV/Sales", 103.0),
    }
    ma = ModelAgreementAnalyzer().analyze(results, current_price=100.0)
    assert ma.core_model_excluded is True
    assert ma.core_model_excluded_names == ["DCF"]
    assert ma.material_disagreement is True
    assert ma.agreement_level == _MATERIAL_DISAGREEMENT
    assert ma.agreement_level not in _STRONG_LEVELS
    assert any("核心模型" in n for n in ma.notes)


def test_agreement_cap_gated_on_independent_evidence_not_solved_count():
    """Two duplicate-family models (P/E ↔ Historical Multiples) must not buy a
    strong conclusion the raw solved count would allow."""
    results = {
        "DCF": _result("DCF", 100.0),
        "EV/EBITDA": _result("EV/EBITDA", 101.0),
        "P/E": _result("P/E", 102.0),
        "Historical Multiples": _result("Historical Multiples", 102.5),
    }
    ma = ModelAgreementAnalyzer().analyze(results, current_price=100.0)
    assert ma.n_solved == 4
    assert ma.n_independent_evidence == 3  # P/E + Historical Multiples share one source
    assert ma.agreement_level_raw in _STRONG_LEVELS  # raw dispersion is tiny
    assert ma.agreement_level not in _STRONG_LEVELS  # but the cap demotes it


def test_extreme_tv_dominance_downweights_dcf():
    """A DCF that is almost entirely terminal value must be downweighted, and the
    report must say so (terminal-value "rescue" is not trustworthy)."""
    results = {
        "DCF": _result("DCF", 101.5, breakdown={"tv_percent_of_ev": 1.6}),
        "EV/EBITDA": _result("EV/EBITDA", 100.0),
        "P/E": _result("P/E", 102.0),
        "P/B": _result("P/B", 101.0),
        "EV/Sales": _result("EV/Sales", 99.0),
    }
    ma = ModelAgreementAnalyzer().analyze(results, current_price=100.0)
    assert "DCF" in ma.downweighted_models
    assert not ma.core_model_excluded  # 101.5 is inside the cluster; not an outlier
    assert any("降权" in n for n in ma.notes)


# ---------------------------------------------------------------------------
# Criteria 8/9 — missing peer identity must never fabricate an exact match
# ---------------------------------------------------------------------------
def test_unknown_identity_never_claims_exact_industry_match():
    ctx = run_pipeline("AAPL")
    data = ctx["data"]
    data.market.sector = "Fictional Sector"
    data.market.industry = "Fictional Industry"
    model = MultiplesModel("EV/EBITDA")

    # With a classified profile but a non-matching identity → a *labelled*
    # business-type fallback, never an exact-industry match.
    _value, _src, kind, _n = model._sector_peer_multiple(data, "EV/EBITDA", ctx["profile"])
    assert kind in PEER_SOURCE_LABELS
    assert kind != PEER_SOURCE_EXACT_INDUSTRY

    # With no identity at all → APPROXIMATE (and never EXACT).
    _v2, _s2, kind2, _n2 = model._sector_peer_multiple(data, "EV/EBITDA", None)
    assert kind2 in PEER_SOURCE_LABELS
    assert kind2 != PEER_SOURCE_EXACT_INDUSTRY


# ---------------------------------------------------------------------------
# Criteria 6/7/10 — whole-universe acceptance audit
# ---------------------------------------------------------------------------
def test_whole_universe_invariants_and_sample_accounting():
    """Every ticker: coverage identity, sample-count identity, no report
    self-contradiction, and a base-consistent rendered percentage."""
    for t in BASKET:
        ctx = run_pipeline(t)
        fp = build_fingerprint(t, ctx)

        # No self-contradictions (coverage, cap, β, overrides, calibration).
        assert not check_invariants(fp, ctx), (t, check_invariants(fp, ctx))

        # Criterion 6 — raw solved == final aggregation + IQR-excluded.
        ma = ctx["agreement"]
        assert ma.raw_solved_count == ma.effective_aggregation_count + ma.outlier_count, t
        if ma.outlier_count > 0:
            assert any("IQR" in n or "原始" in n or "样本" in n for n in ma.notes), t

        # Criterion 10 — the verdict card's own math audit must pass.
        card = getattr(ctx["profile"], "valuation_verdict", None)
        audit = getattr(card, "math_audit", None) if card is not None else None
        if audit is not None:
            assert audit.ok, (t, [c.detail for c in audit.checks])


def test_negative_fcf_build_outs_stay_flagged():
    """Capital-intensive, negative-FCF build-outs (CRWV/NBIS) must keep the
    negative-FCF / terminal-value caveats: terminal value suppressed (not
    fabricated positive) and flagged as a Terminal Value Risk."""
    for t in ("CRWV", "NBIS"):
        ctx = run_pipeline(t)
        dcf = ctx["model_results"].get("DCF")
        assert dcf is not None
        bd = dcf.breakdown or {}
        assert bd.get("terminal_fcf_negative") is True, t
        # Suppressed terminal → tv share is 0, never an inflated positive value.
        assert bd.get("tv_percent_of_ev", 0.0) == 0.0, t
        # And the DCF must be flagged APPROXIMATE (degraded to explicit-period PV).
        assert dcf.status == SolverStatus.APPROXIMATE, t
        r = ctx["risk"]
        assert "Terminal Value Risk" in {f.risk_type for f in r.flags}, t
        assert r.overall_severity in ("High", "Critical"), (t, r.overall_severity)
