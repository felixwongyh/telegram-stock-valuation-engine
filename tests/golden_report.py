"""
tests/golden_report.py - Deterministic report fingerprinting for regression diffs

Purpose (Session #10)
---------------------
The recursive self-improvement loop used to advance by *reading* a rendered
report and eyeballing for self-contradictions. That does not scale and does not
catch a newly-introduced inconsistency when the next round of changes lands.

This module turns "上一轮报告 → 缺陷清单" into an *assertable* artifact:

  * `build_fingerprint(ticker)` runs the full deterministic pipeline
    (synthetic provider → normalize → validate → classify → route → scenario /
    implied-gap / sensitivity → risk → agreement) and extracts a compact,
    stable dict of *decision-relevant signals* — NOT the raw text (which carries
    timestamps and would diff on every run).

  * `report_fingerprints.json` stores the golden baseline. A regression test
    diffs live fingerprints against it, so any behavioural drift is surfaced for
    review rather than discovered by hand.

  * `check_invariants(fingerprint)` returns a list of *self-contradictions*
    (defect checklist): coverage-identity breaks, agreement returned above what
    the coverage cap allows, β read differently across market/risk/WACC, negative
    solved values, or an override that did not take effect. An empty list means
    the report is internally consistent.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

from classification.classifier import BusinessClassifier
from data import DataValidator, FinancialNormalizer, SyntheticDataProvider
from analysis.expectation import ExpectationAnalyzer
from analysis.model_agreement import ModelAgreementAnalyzer
from analysis.risk import RiskAnalyzer
from analysis.scenario import ScenarioAnalyzer
from analysis.sensitivity import SensitivityAnalyzer
from models.router import ModelRouter
from valuation.caliber import build_caliber_contract
from valuation.wacc import resolve_effective_beta

# Representative asset structures across the archetypes the engine must handle.
# Phase 4 extended the basket from the original 9 to the full regression
# universe so classification / routing / agreement cannot drift silently for the
# archetypes below:
#   * GOOGL — mega-cap ad + cloud (Communication Services) → MatureTech
#   * AMZN  — e-commerce retail with negative-FCF years → ConsumerCyclical
#   * AVGO  — semiconductor → Semiconductor
#   * ORCL  — enterprise infrastructure software → MatureTech
#   * CRWV  — AI neocloud build-out (capex ≫ revenue, negative FCF) → MatureTech
#   * UPS   — industrial logistics → Industrial
#   * KR    — consumer staples grocery → ConsumerStaples
#   * BAC   — diversified bank (no EBITDA) → Bank (ke caliber, DDM/RIM)
#   * NU    — high-growth neobank / fintech → FinTech
BASKET: List[str] = [
    "AAPL", "MSFT", "NVDA", "JPM", "PLD", "NOW", "NBIS", "AMT", "XOM",
    "GOOGL", "AMZN", "AVGO", "ORCL", "CRWV", "UPS", "KR", "BAC", "NU",
]

_AGREEMENT_ORDER = ["Very Strong", "Strong", "Moderate", "Weak", "Very Weak"]
# Maximum agreement level allowed for a given number of solved models (mirrors
# analysis/model_agreement._COVERAGE_CAP).
_COVERAGE_CAP = {0: "Very Weak", 1: "Very Weak", 2: "Weak", 3: "Moderate"}


def _cap_for(n_solved: int) -> str:
    if n_solved >= 4:
        return "Very Strong"
    return _COVERAGE_CAP.get(n_solved, "Very Weak")


def _round(x: Any, nd: int = 2) -> Any:
    try:
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


def run_pipeline(ticker: str, provider: Any = None, classifier: Any = None) -> Dict[str, Any]:
    """Run the deterministic offline pipeline; return all intermediate objects.

    `provider` / `classifier` default to the offline synthetic provider and the
    rule-based classifier (what the golden basket pins). Pass
    `YahooFinanceProvider()` + `MLHybridClassifier()` to fingerprint the live
    production path instead.
    """
    import asyncio

    provider = provider or SyntheticDataProvider()
    raw = provider.get_financial_data(ticker)
    if asyncio.iscoroutine(raw):
        data = asyncio.run(raw)
    else:
        data = copy.deepcopy(raw)
    data = FinancialNormalizer.normalize_all(data)
    data = DataValidator.validate(data)

    profile = (classifier or BusinessClassifier()).classify(data)
    model_results = ModelRouter().run_all(data, profile)

    scenarios = dict(ScenarioAnalyzer().run_all(data, profile))
    try:
        sens = SensitivityAnalyzer().wacc_vs_terminal_growth(data, profile)
    except Exception:
        sens = None
    implied, gap = ExpectationAnalyzer().gap_analysis(data, profile)
    risk = RiskAnalyzer().analyze(data, _dcf_breakdown(model_results), profile)
    agreement = ModelAgreementAnalyzer().analyze(
        model_results, data.market.current_price, data=data, profile=profile,
    )

    from reporting.verdict_intuition import build_growth_verdict, build_valuation_verdict
    profile.growth_verdict = build_growth_verdict(gap)
    profile.valuation_verdict = build_valuation_verdict(
        agreement=agreement, scenarios=scenarios, model_results=model_results,
        data=data, profile=profile, implied=implied,
    )

    return {
        "data": data, "profile": profile, "model_results": model_results,
        "scenarios": scenarios, "sens": sens, "implied": implied, "gap": gap,
        "risk": risk, "agreement": agreement,
    }


def _dcf_breakdown(model_results: Dict[str, Any]):
    r = model_results.get("DCF")
    if r is not None and r.is_success() and getattr(r, "breakdown", None):
        return r.breakdown
    return None


def render_report(ctx: Dict[str, Any]) -> str:
    from reporting.dashboard import ValuationReportBuilder
    return ValuationReportBuilder.build_report(
        ctx["data"], ctx["profile"], ctx["model_results"], ctx["scenarios"],
        ctx["implied"], ctx["gap"], ctx["sens"], ctx["agreement"], ctx["risk"], None,
    )


def build_fingerprint(
    ticker: str, ctx: Dict[str, Any] | None = None,
    provider: Any = None, classifier: Any = None,
) -> Dict[str, Any]:
    """Compact, stable signals extracted from one full pipeline run."""
    ctx = ctx if ctx is not None else run_pipeline(ticker, provider=provider, classifier=classifier)
    data, profile = ctx["data"], ctx["profile"]
    ma, risk = ctx["agreement"], ctx["risk"]
    dcf_bd = _dcf_breakdown(ctx["model_results"])

    eb = resolve_effective_beta(data, dcf_bd)
    overrides = getattr(data, "reconciliation_overrides", None)
    override_applied = sorted(
        r.field for r in getattr(overrides, "records", []) if getattr(r, "applied", False)
    ) if overrides is not None else []

    rec = getattr(data, "reconciliation", None)
    contract = build_caliber_contract(profile)
    scenario_calibers = sorted({
        (sv.assumptions or {}).get("discount_label") or "WACC"
        for sv in ctx["scenarios"].values() if sv is not None
    })
    return {
        "ticker": ticker,
        "business_type": profile.business_type,
        "applicable_models": sorted(profile.applicable_models),
        "caliber": contract.discount.value,
        "scenario_calibers": scenario_calibers,
        "n_total": ma.n_total,
        "n_applicable": ma.n_applicable,
        "n_solved": ma.n_solved,
        "n_failed": ma.n_failed,
        "n_not_applicable": ma.n_not_applicable,
        "n_display_only": ma.n_display_only,
        # Phase 1 raw-vs-filtered accounting and Phase 3 independent-evidence
        # count. Pinned so a change that silently drops the core model (DCF) or
        # collapses distinct families into a fake consensus shows up as drift.
        "n_independent_evidence": ma.n_independent_evidence,
        "raw_solved_count": ma.raw_solved_count,
        "outlier_count": ma.outlier_count,
        "effective_aggregation_count": ma.effective_aggregation_count,
        "core_model_excluded": ma.core_model_excluded,
        "agreement_level": ma.agreement_level,
        "median_value": _round(ma.median_value),
        "median_value_weighted": _round(ma.median_value_weighted),
        "beta_effective": _round(eb.beta),
        "beta_origin": eb.origin,
        "recon_checks": len(rec.checks) if rec is not None else 0,
        "recon_mismatches": len(rec.mismatches) if rec is not None else 0,
        "override_applied": override_applied,
        "risk_score": risk.overall_score,
        "risk_severity": risk.overall_severity,
        "risk_types": sorted({f.risk_type for f in risk.flags}),
        # P0-3: per-share denominator contract — the reference caliber used for
        # cross-model comparability and which models were dropped from the
        # consensus because their denominator was not comparable.
        "share_ref_source": ma.share_count_reference_source,
        "share_count_excluded": sorted(ma.share_count_excluded_models),
    }


def check_invariants(fp: Dict[str, Any], ctx: Dict[str, Any] | None = None) -> List[str]:
    """Return a list of self-contradictions (empty == internally consistent)."""
    defects: List[str] = []
    t = fp["ticker"]

    # 1. Coverage accounting identity: applicable == solved + failed
    if fp["n_applicable"] != fp["n_solved"] + fp["n_failed"]:
        defects.append(
            f"{t}: coverage identity broken — applicable {fp['n_applicable']} != "
            f"solved {fp['n_solved']} + failed {fp['n_failed']}"
        )

    # 2. Agreement level must not exceed the coverage cap. The cap is gated on
    #    the *independent evidence* count (Phase 3.3), not the raw solved count —
    #    so a duplicated family cannot buy a stronger conclusion.
    cap = _cap_for(fp["n_independent_evidence"])
    lvl = fp["agreement_level"]
    if lvl in _AGREEMENT_ORDER and cap in _AGREEMENT_ORDER:
        if _AGREEMENT_ORDER.index(lvl) < _AGREEMENT_ORDER.index(cap):
            defects.append(
                f"{t}: agreement '{lvl}' exceeds coverage cap '{cap}' "
                f"for {fp['n_independent_evidence']} independent evidence units"
            )

    # 2b. A core model dropped by the IQR filter must surface as an unresolved
    #     disagreement, never as a "Very Strong"/"Strong" consensus.
    if fp.get("core_model_excluded") and lvl in ("Very Strong", "Strong", "Moderate"):
        defects.append(
            f"{t}: core model excluded by IQR but agreement reported as '{lvl}' "
            "— silent removal of the core model"
        )

    # 3. No negative solved per-share value.
    if fp["median_value"] is not None and fp["median_value"] < 0:
        defects.append(f"{t}: median value is negative ({fp['median_value']})")

    if ctx is not None:
        # 4. β must be identical across market section / risk flag / WACC.
        data, model_results = ctx["data"], ctx["model_results"]
        dcf_bd = _dcf_breakdown(model_results)
        eff = resolve_effective_beta(data, dcf_bd)
        if dcf_bd is not None:
            wb = dcf_bd.get("wacc_breakdown")
            wb_beta = getattr(wb, "beta", None) if wb is not None else None
            if wb_beta is not None and abs(float(wb_beta) - float(eff.beta)) > 1e-6:
                defects.append(
                    f"{t}: β mismatch — WACC breakdown {wb_beta} vs effective {eff.beta}"
                )
        for f in ctx["risk"].flags:
            if f.risk_type == "WACC Risk" and f.metric_value is not None:
                if abs(float(f.metric_value) - float(eff.beta)) > 1e-6:
                    defects.append(
                        f"{t}: β mismatch — risk flag {f.metric_value} vs effective {eff.beta}"
                    )

        # 5. Every override flagged as applied must actually have taken effect.
        data_overrides = getattr(data, "reconciliation_overrides", None)
        if data_overrides is not None:
            from data.reconciliation import _OVERRIDE_FIELDS
            for r in data_overrides.records:
                if not r.applied:
                    continue
                target = _OVERRIDE_FIELDS.get(r.check_name)
                if target is None:
                    continue
                attr = target[0]
                actual = getattr(data.market, attr, None)
                if actual is None or r.internal_value is None:
                    continue
                if abs(float(actual) - float(r.internal_value)) > 1e-6 * max(1.0, abs(float(r.internal_value))):
                    defects.append(
                        f"{t}: override for {r.field} not applied — "
                        f"market.{attr}={actual} vs logged internal={r.internal_value}"
                    )

        # 6. Scenario discount caliber must equal the engine-declared caliber.
        #    The main model and the Bear/Base/Bull band must not disagree about
        #    which discount caliber applies (Recursion SOFI round2 — where the
        #    bank main model said ke while the scenario band still said WACC).
        contract = build_caliber_contract(ctx["profile"])
        for name, sv in ctx["scenarios"].items():
            if sv is None:
                continue
            lbl = (sv.assumptions or {}).get("discount_label") or "WACC"
            if lbl != contract.discount.value:
                defects.append(
                    f"{t}: scenario '{name}' caliber '{lbl}' != engine caliber "
                    f"'{contract.discount.value}' — main model / scenario disagreement"
                )

    return defects
