"""
analysis/model_agreement.py - Model Agreement & Valuation Spread

Coverage-aware model agreement
------------------------------
A small spread across a handful of *surviving* models is NOT evidence of
reliability — it can be pure survivorship bias. If 4 of 6 models are dropped
(not-applicable or failed) and the remaining 2 happen to sit close together,
reporting "Very Strong consistency" is misleading: it says "依据更少、结论更
自信" (less evidence, more confident), which is the opposite of honest.

This module therefore gates the agreement level on three independent factors:

    gated_cv = base_cv × coverage_factor ÷ quality_factor

  * coverage_factor — penalises low solved/applicable coverage:
        sqrt(applicable / solved), clamped to [1.0, 2.0]
  * quality_factor  — each SOLVED model counts 1.0, each APPROXIMATE model 0.5,
        and a DCF whose terminal value dominates EV (>80%) is halved again
        (terminal-value "rescue" is not a trustworthy signal)

On top of the continuous gated_cv, a hard coverage cap forbids strong
conclusions when few models survive:

    solved <= 1 → cap Very Weak | ==2 → Weak | ==3 → Moderate | >=4 → no cap

Models are also split into honest buckets so the denominator is no
longer inflated (applicable = solved + failed must hold exactly):
  * solved          — produced a value (SOLVED or APPROXIMATE)
  * not_applicable  — INSUFFICIENT_DATA (e.g. P/E with ~0 earnings, FCF Yield
                      with negative FCF) — must NOT count as "failed"
  * failed          — attempted but no solution (NO_SOLUTION_IN_RANGE / INFEASIBLE)
  * display_only    — solved but circular/derived (ReverseDCF = current price);
                      rendered for context, excluded from applicable/solved/failed
                      so it never masquerades as a failed model
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median, pstdev
from typing import Dict, List, Optional, Tuple

from config import get_logger, SolverStatus
from models.base import ValuationResult

log = get_logger("analysis.model_agreement")


# Severity ordering: index 0 = strongest agreement, 4 = weakest.
_AGREEMENT_ORDER: List[str] = ["Very Strong", "Strong", "Moderate", "Weak", "Very Weak"]
# Coverage cap: maximum agreement level allowed for a given number of solved models.
_COVERAGE_CAP: Dict[int, str] = {0: "Very Weak", 1: "Very Weak", 2: "Weak", 3: "Moderate"}
# A value below this many solved models can never be called strongly consistent.
_COVERAGE_STRONG_MIN_SOLVED = 4
# DCF terminal-value dominance thresholds (TV as a fraction of EV).
#   > 0.80 → downweighted (terminal-value "rescue" is not trustworthy)
#   > 1.50 → the explicit-period PV of FCF is deeply negative; the point value
#            is almost entirely a terminal assumption → heavy downweight
#   > 3.00 → terminal value swamps EV many times over (a data/assumption
#            artifact for pre-profit build-outs) → near-artifact weight
_TV_DOMINANCE_THRESHOLD = 0.80
_TV_EXTREME_THRESHOLD = 1.50
_TV_ARTIFACT_THRESHOLD = 3.00
# Classification confidence below this halves a multiple model's weight again.
_LOW_CONFIDENCE_THRESHOLD = 0.55
# Reverse DCF returns the current price (circular) — never a valuation.
_EXCLUDED_FROM_MEDIAN = {"ReverseDCF", "reverse_dcf", "Reverse DCF"}
# Models whose removal from the aggregation is a *material* event. A valuation
# built from forecast FCF (DCF) disagreeing with the peer-multiple cluster is
# precisely the "models strongly disagree" case that must NOT be masked by an
# IQR rule that quietly drops the dissenter and then reports a tight survivor
# cluster as "Very Strong" (survivorship bias). Excluding a core model therefore
# forces the disagreement to be surfaced explicitly, not hidden.
_CORE_MODELS: set = {"DCF", "dcf", "DCF "}
# Distinct (non-ordinal) level used when a core model was dropped: the report
# must say "unresolved disagreement", not silently downgrade to Moderate.
_MATERIAL_DISAGREEMENT = "Unresolved Disagreement (Review Required)"
# ---------------------------------------------------------------------------
# Duplicate-evidence de-duplication (Phase 3.3 / Session #21).
#
# Some registry entries are the *same* underlying evidence presented twice:
#   * "P/E" and "Historical Multiples" both run ``PEModel`` — one model rendered
#     under two names, so counting them as two solved models inflates both the
#     coverage cap and the apparent agreement.
#   * "EV/Sales" and "EV/Sales (Unit Econ)" both anchor on a sales multiple
#     drawn from the same peer table.
# When gating agreement each family collapses to ONE unit of *independent*
# evidence: fewer independent sources ⇒ weaker confidence cap, which is exactly
# the honesty the user demanded ("no false high consistency").
_MODEL_FAMILY: Dict[str, str] = {
    "P/E": "earnings_multiple",
    "Historical Multiples": "earnings_multiple",
    "EV/Sales": "sales_multiple",
    "EV/Sales (Unit Econ)": "sales_multiple",
    "DCF": "dcf_forecast",
    "dcf": "dcf_forecast",
    "ReverseDCF": "dcf_forecast",
    "reverse_dcf": "dcf_forecast",
    "Reverse DCF": "dcf_forecast",
}


def _independent_evidence(
    solved: Dict[str, float]
) -> Tuple[int, Dict[str, List[str]]]:
    """Return (independent-evidence count, {family: members} for duplicated families).

    Models absent from ``_MODEL_FAMILY`` are treated as their own unique family,
    so an unmapped model never silently loses evidence.
    """
    groups: Dict[str, List[str]] = {}
    for name in solved:
        groups.setdefault(_MODEL_FAMILY.get(name, f"__unique__:{name}"), []).append(name)
    duplicated = {fam: members for fam, members in groups.items() if len(members) > 1}
    return len(groups), duplicated


def _weaker_level(a: str, b: str) -> str:
    """Return the less confident (weaker) of two agreement levels."""
    ia = _AGREEMENT_ORDER.index(a) if a in _AGREEMENT_ORDER else len(_AGREEMENT_ORDER)
    ib = _AGREEMENT_ORDER.index(b) if b in _AGREEMENT_ORDER else len(_AGREEMENT_ORDER)
    return a if ia >= ib else b


def _level_from_cv(cv: float) -> str:
    if cv < 0.10:
        return "Very Strong"
    if cv < 0.20:
        return "Strong"
    if cv < 0.35:
        return "Moderate"
    if cv < 0.55:
        return "Weak"
    return "Very Weak"


@dataclass
class ModelAgreement:
    n_applicable: int
    n_solved: int
    values: Dict[str, Optional[float]]
    median_value: Optional[float] = None
    mean_value: Optional[float] = None
    low_value: Optional[float] = None
    high_value: Optional[float] = None
    std_dev: Optional[float] = None
    cv: Optional[float] = None
    spread_pct: Optional[float] = None
    agreement_level: str = "Unknown"
    notes: List[str] = field(default_factory=list)
    n_approximate: int = 0
    n_high_confidence: int = 0
    median_value_high_conf: Optional[float] = None
    median_value_robust: Optional[float] = None
    outliers_removed: List[str] = field(default_factory=list)

    # ---- Coverage / quality gating (Session #07) -------------------------
    n_total: int = 0
    n_not_applicable: int = 0
    n_failed: int = 0
    n_display_only: int = 0
    not_applicable_models: List[Tuple[str, str]] = field(default_factory=list)
    failed_models: List[Tuple[str, str]] = field(default_factory=list)
    display_only_models: List[str] = field(default_factory=list)
    coverage_ratio: float = 1.0
    quality_factor: float = 1.0
    coverage_factor: float = 1.0
    gated_cv: Optional[float] = None
    agreement_level_raw: str = "Unknown"
    coverage_sufficient: bool = True
    median_value_weighted: Optional[float] = None
    model_weights: Dict[str, float] = field(default_factory=dict)
    downweighted_models: List[str] = field(default_factory=list)
    low_conf_downgraded_models: List[str] = field(default_factory=list)
    # ---- Duplicate-evidence de-dup (Phase 3.3) ---------------------------
    # n_independent_evidence = distinct model families among solved models; the
    # coverage cap is gated on this, not the raw solved count, so a duplicated
    # family cannot buy a strong-agreement conclusion.
    n_independent_evidence: int = 0
    duplicate_evidence_groups: Dict[str, List[str]] = field(default_factory=dict)

    # ---- Phase 1 (Valuation Integrity): raw vs survivor statistics --------
    # raw_solved_count counts every model that produced a value *before* the IQR
    # filter; effective_aggregation_count counts those that actually entered the
    # median. Reporting both (plus outlier_count) prevents "less evidence, more
    # confident". all_model_* describe the FULL solved set; survivor_* describe
    # the post-IQR subset that the median is computed from.
    raw_solved_count: int = 0
    outlier_count: int = 0
    effective_aggregation_count: int = 0
    all_model_mean: Optional[float] = None
    all_model_median: Optional[float] = None
    all_model_cv: Optional[float] = None
    all_model_dispersion_level: str = "Unknown"
    survivor_mean: Optional[float] = None
    survivor_median: Optional[float] = None
    survivor_cv: Optional[float] = None
    survivor_spread_pct: Optional[float] = None
    survivor_agreement_level: str = "Unknown"
    core_model_excluded: bool = False
    core_model_excluded_names: List[str] = field(default_factory=list)
    material_disagreement: bool = False
    # Raw (pre-IQR) DCF value and the peer-multiple cluster range, so the report
    # can show "DCF vs multiples 各自区间" even when IQR excluded the DCF.
    dcf_value: Optional[float] = None
    multiples_low: Optional[float] = None
    multiples_high: Optional[float] = None
    # Phase 1.2: structured, auditable DCF-vs-multiple divergence diagnostic
    # (built only when a FinancialData is supplied to analyze()).
    divergence: Optional[object] = None


class ModelAgreementAnalyzer:
    """Summarizes the agreement across multiple valuation models."""

    @staticmethod
    def _iqr_filter(
        solved: Dict[str, float]
    ) -> Tuple[Dict[str, float], List[str]]:
        """Remove outliers using the IQR method.

        Returns (filtered_dict, list_of_removed_model_names).
        Only applies when there are >= 4 models; otherwise returns all.
        Uses a generous 2.5×IQR multiplier to avoid removing legitimate values.
        """
        if len(solved) < 4:
            return solved, []

        vals = sorted(solved.values())
        n = len(vals)
        # Q1 and Q3 using linear interpolation
        q1_idx = (n - 1) * 0.25
        q3_idx = (n - 1) * 0.75
        q1 = vals[int(q1_idx)] + (q1_idx - int(q1_idx)) * (
            vals[min(int(q1_idx) + 1, n - 1)] - vals[int(q1_idx)]
        ) if int(q1_idx) + 1 < n else vals[int(q1_idx)]
        q3 = vals[int(q3_idx)] + (q3_idx - int(q3_idx)) * (
            vals[min(int(q3_idx) + 1, n - 1)] - vals[int(q3_idx)]
        ) if int(q3_idx) + 1 < n else vals[int(q3_idx)]

        iqr = q3 - q1
        lower_bound = q1 - 2.5 * iqr
        upper_bound = q3 + 2.5 * iqr

        removed = []
        filtered = {}
        for name, v in solved.items():
            if v < lower_bound or v > upper_bound:
                removed.append(name)
            else:
                filtered[name] = v

        # Safety: never remove more than 1 value (keep at least n-1)
        if len(removed) > 1:
            # Only remove the single most extreme outlier
            all_items = list(solved.items())
            median_val = median(vals)
            most_extreme = max(all_items, key=lambda kv: abs(kv[1] - median_val))
            removed = [most_extreme[0]]
            filtered = {k: v for k, v in solved.items() if k != most_extreme[0]}

        return filtered, removed

    @staticmethod
    def _weighted_median(values: Dict[str, float], weights: Dict[str, float]) -> Optional[float]:
        """Weighted median over (model → value) with per-model quality weights.

        Uses the standard *midpoint* definition: the average of the **lower** and
        **upper** weighted medians. This guarantees that when every weight is
        equal (the common case, e.g. six SOLVED models each at 1.0) the result
        collapses **exactly** to the ordinary median.

        The previous implementation returned the first value whose cumulative
        weight reached half the total — for equal weights that is the (n/2)-th
        value rather than ``mean(values[n/2-1], values[n/2])``, so the "weighted"
        median silently drifted from the ordinary median (observed on AAPL:
        176.12 vs 165.24 with identical weights).
        """
        if not values:
            return None
        items = sorted(values.items(), key=lambda kv: kv[1])
        wts = [max(0.0, weights.get(k, 1.0)) for k, _ in items]
        total = sum(wts)
        if total <= 0.0:
            return None
        half = total / 2.0

        # Lower weighted median: first ascending value whose running weight
        # reaches half of the total.
        cum = 0.0
        lower = items[-1][1]
        for (_, v), w in zip(items, wts):
            cum += w
            if cum >= half:
                lower = v
                break

        # Upper weighted median: symmetric scan from the largest value down.
        cum = 0.0
        upper = items[0][1]
        for (_, v), w in zip(reversed(items), reversed(wts)):
            cum += w
            if cum >= half:
                upper = v
                break

        return (lower + upper) / 2.0

    def analyze(self, results: Dict[str, ValuationResult], current_price: Optional[float] = None,
                data: Optional[object] = None, profile: Optional[object] = None) -> ModelAgreement:
        n_total = len(results)
        solved: Dict[str, float] = {}
        values_all: Dict[str, Optional[float]] = {}
        high_conf_vals: List[float] = []
        approx_names: List[str] = []
        not_applicable: List[Tuple[str, str]] = []
        failed: List[Tuple[str, str]] = []
        display_only: List[str] = []
        weights: Dict[str, float] = {}
        downweighted: List[str] = []
        low_conf_downgraded: List[str] = []
        extreme_tv: List[Tuple[str, float]] = []

        for name, r in results.items():
            value_per_share = r.value_per_share
            if r.is_success() and value_per_share is not None:
                values_all[name] = value_per_share
                if name in _EXCLUDED_FROM_MEDIAN:
                    # ReverseDCF returns the current price (circular) — display
                    # only, never part of the valuation statistics or coverage.
                    # Track it explicitly so the bucket accounting stays honest
                    # (otherwise total = solved + failed + not_applicable breaks).
                    display_only.append(name)
                    continue
                solved[name] = value_per_share
                # ---- per-model quality weight -------------------------------
                w = 1.0
                if r.status == SolverStatus.APPROXIMATE:
                    approx_names.append(name)
                    w = 0.5
                    # A multiple whose peer bucket came from a low-confidence
                    # classification (e.g. 50%) must not carry the same weight
                    # as a well-classified one.
                    conf = None
                    try:
                        raw_conf = (r.breakdown or {}).get("classification_confidence")
                        if raw_conf is not None:
                            conf = float(raw_conf)
                    except (TypeError, ValueError):
                        conf = None
                    if conf is not None and conf < _LOW_CONFIDENCE_THRESHOLD:
                        w *= 0.5
                        low_conf_downgraded.append(name)
                else:
                    high_conf_vals.append(value_per_share)
                tv_pct = (r.breakdown or {}).get("tv_percent_of_ev")
                if name in ("DCF", "dcf") and tv_pct is not None and tv_pct > _TV_DOMINANCE_THRESHOLD:
                    if tv_pct > _TV_ARTIFACT_THRESHOLD:
                        w *= 0.10
                    elif tv_pct > _TV_EXTREME_THRESHOLD:
                        w *= 0.25
                    else:
                        w *= 0.5
                    downweighted.append(name)
                    if tv_pct > _TV_EXTREME_THRESHOLD:
                        extreme_tv.append((name, tv_pct))
                weights[name] = w
            else:
                values_all[name] = None
                reason = "; ".join(r.notes) if r.notes else r.status.value
                if r.status == SolverStatus.INSUFFICIENT_DATA:
                    not_applicable.append((name, reason))
                else:
                    failed.append((name, reason))

        n_not_applicable = len(not_applicable)
        n_display_only = len(display_only)
        # Display-only models (e.g. ReverseDCF, which returns the current price by
        # construction) are neither solved nor failed nor not-applicable — they
        # must be removed from the applicable denominator so that
        # applicable = solved + failed holds exactly.
        n_applicable = max(0, n_total - n_not_applicable - n_display_only)

        # Duplicate-evidence de-dup (Phase 3.3): models sharing one underlying
        # source (e.g. P/E ↔ Historical Multiples, both PEModel) count as a
        # single unit of independent evidence when gating agreement.
        n_independent, dup_groups = _independent_evidence(solved)

        # IQR-based outlier removal (only when >= 4 models)
        solved_filtered, removed_outliers = self._iqr_filter(solved)
        if removed_outliers:
            # Recompute high_conf_vals from filtered set
            high_conf_vals = [
                v for name, v in solved_filtered.items()
                if name not in approx_names
            ]

        vals = list(solved_filtered.values())
        n_solved = len(vals) + len(removed_outliers)  # report original count
        n_stats = len(vals)  # actual count used for stats

        # ---- All-model vs survivor-only dispersion (Phase 1, honesty) --------
        # raw_solved_count = every model that produced a value (IQR outliers
        # included); effective_aggregation_count = those actually entering the
        # median. Reporting both stops "fewer survivors, higher confidence".
        raw_solved_count = len(solved)
        all_vals = list(solved.values())
        all_model_mean = sum(all_vals) / len(all_vals) if all_vals else None
        all_model_median = median(all_vals) if all_vals else None
        all_model_cv = None
        if len(all_vals) >= 2 and all_model_mean and all_model_mean > 0:
            all_model_cv = pstdev(all_vals) / all_model_mean
        all_model_dispersion_level = (
            _level_from_cv(all_model_cv) if all_model_cv is not None else "Unknown"
        )

        survivor_mean = sum(vals) / len(vals) if vals else None
        survivor_median = median(vals) if vals else None
        survivor_cv = None
        if len(vals) >= 2 and survivor_mean and survivor_mean > 0:
            survivor_cv = pstdev(vals) / survivor_mean
        survivor_spread_pct = None
        if vals and survivor_median and survivor_median > 0:
            survivor_spread_pct = (max(vals) - min(vals)) / survivor_median
        survivor_agreement_level = (
            _level_from_cv(survivor_cv) if survivor_cv is not None else "Unknown"
        )
        core_excluded = [n for n in removed_outliers if n in _CORE_MODELS]
        # Raw (pre-IQR) DCF value and peer-multiple cluster range for the
        # "disagreement is not hidden" diagnostic in the report.
        dcf_value = next((v for k, v in solved.items() if k in _CORE_MODELS), None)
        _mult_vals = [v for k, v in solved.items() if k not in _CORE_MODELS]
        multiples_low = min(_mult_vals) if _mult_vals else None
        multiples_high = max(_mult_vals) if _mult_vals else None
        n_approximate = len([n for n in approx_names if n in solved_filtered])
        n_high_confidence = n_stats - n_approximate

        ma = ModelAgreement(
            n_applicable=n_applicable,
            n_solved=n_solved,
            values=values_all,
            n_approximate=n_approximate,
            n_high_confidence=n_high_confidence,
            outliers_removed=removed_outliers,
            n_total=n_total,
            n_not_applicable=n_not_applicable,
            n_failed=len(failed),
            n_display_only=n_display_only,
            not_applicable_models=not_applicable,
            failed_models=failed,
            display_only_models=display_only,
            model_weights=dict(weights),
            downweighted_models=downweighted,
            low_conf_downgraded_models=low_conf_downgraded,
            raw_solved_count=raw_solved_count,
            outlier_count=len(removed_outliers),
            effective_aggregation_count=n_stats,
            all_model_mean=all_model_mean,
            all_model_median=all_model_median,
            all_model_cv=all_model_cv,
            all_model_dispersion_level=all_model_dispersion_level,
            survivor_mean=survivor_mean,
            survivor_median=survivor_median,
            survivor_cv=survivor_cv,
            survivor_spread_pct=survivor_spread_pct,
            survivor_agreement_level=survivor_agreement_level,
            core_model_excluded=bool(core_excluded),
            core_model_excluded_names=list(core_excluded),
            n_independent_evidence=n_independent,
            duplicate_evidence_groups=dup_groups,
            dcf_value=dcf_value,
            multiples_low=multiples_low,
            multiples_high=multiples_high,
        )

        if vals:
            mv = sorted(vals)
            ma.low_value = mv[0]
            ma.high_value = mv[-1]
            ma.mean_value = sum(vals) / len(vals)
            ma.median_value = median(vals)

            # Robust median (same as regular median when outliers already filtered,
            # but stored separately for clarity in reporting)
            ma.median_value_robust = ma.median_value

            # High-confidence median (SOLVED models only, excluding APPROXIMATE)
            if high_conf_vals:
                ma.median_value_high_conf = median(high_conf_vals)

            # Quality-weighted median (SOLVED=1.0, APPROXIMATE=0.5,
            # TV-dominated DCF halved again)
            ma.median_value_weighted = self._weighted_median(
                {k: v for k, v in solved_filtered.items()}, weights
            )

            if len(vals) >= 2:
                ma.std_dev = pstdev(vals)
                if ma.mean_value and ma.mean_value > 0:
                    ma.cv = ma.std_dev / ma.mean_value
            if ma.low_value is not None and ma.high_value is not None and ma.median_value and ma.median_value > 0:
                ma.spread_pct = (ma.high_value - ma.low_value) / ma.median_value

            # Note if outliers were removed
            if removed_outliers:
                outlier_vals = [f"{name} (${values_all[name]:.2f})" for name in removed_outliers]
                ma.notes.append(
                    f"⚠️ IQR outlier filter removed: {', '.join(outlier_vals)} "
                    "(extreme value(s) excluded from median/spread)"
                )

            # When all solved models are APPROXIMATE, flag the median as unreliable
            if n_approximate == n_stats and n_stats > 0:
                ma.notes.append(
                    f"⚠️ All {n_stats} solved models are APPROXIMATE — "
                    "median valuation is directional only (low confidence)"
                )
                if ma.median_value and current_price:
                    ma.notes.append(
                        "Consider scenario analysis (DCF-based) as the primary valuation reference "
                        "instead of the multiples-based median."
                    )
            elif n_approximate > 0 and n_approximate < n_stats:
                ma.notes.append(
                    f"{n_approximate} of {n_stats} models are APPROXIMATE — "
                    "median includes low-confidence estimates"
                )

            # ---- Continuous gated CV + hard coverage cap -------------------
            quality_factor = (
                sum(max(0.0, weights.get(k, 1.0)) for k in solved_filtered) / n_stats
                if n_stats > 0 else 0.0
            )
            coverage_ratio = (n_solved / n_applicable) if n_applicable > 0 else 0.0
            coverage_factor = (
                min(2.0, max(1.0, (n_applicable / n_solved) ** 0.5)) if n_solved > 0 else 2.0
            )
            ma.quality_factor = round(quality_factor, 4)
            ma.coverage_ratio = round(coverage_ratio, 4)
            ma.coverage_factor = round(coverage_factor, 4)
            ma.coverage_sufficient = (
                n_solved >= _COVERAGE_STRONG_MIN_SOLVED and coverage_ratio >= 0.6
            )

            if ma.cv is not None:
                gated_cv = ma.cv * coverage_factor / max(quality_factor, 0.25)
                ma.gated_cv = gated_cv
                raw_level = _level_from_cv(gated_cv)
                ma.agreement_level_raw = raw_level
                # Phase 3.3: the cap is gated on *independent* evidence (distinct
                # model families), not the raw solved count — a duplicated family
                # must not buy a stronger conclusion.
                cap = _COVERAGE_CAP.get(n_independent)  # None when >= 4
                level = _weaker_level(raw_level, cap) if cap else raw_level
                if cap and level != raw_level:
                    ma.notes.append(
                        f"一致性降级：仅 {n_solved} 个模型解算（覆盖 {n_solved}/{n_applicable}）→ "
                        f"由「{raw_level}」封顶为「{level}」（低覆盖不得给出强结论）"
                    )
                if not ma.coverage_sufficient:
                    ma.notes.append(
                        f"⚠️ 模型覆盖不足（{n_solved}/{n_applicable} 解算，"
                        f"质量因子 {quality_factor:.2f}）→ 结论只能作为方向性参考"
                    )
                if quality_factor < 0.50:
                    level = _weaker_level(level, "Moderate")
                    ma.notes.append(
                        f"质量因子过低（{quality_factor:.2f}）→ 一致性再下调至「{level}」"
                    )
                ma.agreement_level = level
                # ---- Core-model exclusion ⇒ unresolved disagreement --------
                # If IQR dropped a CORE model (DCF), the survivor cluster CANNOT
                # certify agreement: the dissenter was removed by a statistical
                # rule, not shown to be wrong. Surface the disagreement (do not
                # silently cap to Moderate), and keep both the all-model and the
                # survivor ranges visible for the reader.
                if core_excluded:
                    ma.material_disagreement = True
                    ma.agreement_level = _MATERIAL_DISAGREEMENT
                    ma.notes.insert(0,
                        f"⚠️ 核心模型 {', '.join(core_excluded)} 被 IQR 排除 → "
                        f"模型分歧未解决（Material Disagreement / Review Required）："
                        f"中位估值仅代表 {n_stats} 个幸存模型，"
                        f"非 {raw_solved_count} 个模型的共识；须展示 DCF 与倍数法各自区间"
                    )
            else:
                ma.agreement_level = "N/A (single model)"
                ma.agreement_level_raw = "N/A (single model)"
        else:
            ma.agreement_level = "N/A (no solved models)"
            ma.agreement_level_raw = "N/A (no solved models)"
            ma.coverage_ratio = 0.0
            ma.coverage_sufficient = False
            ma.notes.append("No models produced a valid value")

        # ---- Honest bucket reporting -------------------------------------
        if not_applicable:
            items = ", ".join(f"{name}（{reason}）" for name, reason in not_applicable)
            ma.notes.append(
                f"不适用模型 {n_not_applicable} 个（数据不足，不计入分母）: {items}"
            )
        if failed:
            items = ", ".join(f"{name}（{reason}）" for name, reason in failed)
            ma.notes.append(f"失败模型 {len(failed)} 个: {items}")
        if n_display_only:
            ma.notes.append(
                f"仅展示模型 {n_display_only} 个（不计入适用/解算统计）: "
                f"{', '.join(display_only)}"
            )
        if len(failed) > 0 and n_solved < n_applicable:
            ma.notes.append(
                f"{len(failed)} of {n_applicable} applicable models failed"
            )
        if downweighted:
            ma.notes.append(
                f"以下模型因终值占比过高（TV/EV>{_TV_DOMINANCE_THRESHOLD:.0%}）被降权: "
                f"{', '.join(downweighted)}"
            )
        if extreme_tv:
            items = ", ".join(f"{name}（TV/EV={pct:.0%}）" for name, pct in extreme_tv)
            # Highest-priority caveat: place first so it survives the report's
            # note-truncation and is not buried under routine bookkeeping notes.
            ma.notes.insert(0,
                f"⚠️ 极端终值占比重估: {items} — 显式期自由现金流现值深度为负，点估值几乎完全由终值假设决定，"
                "不构成可靠公允价值，已大幅降权"
            )
        if low_conf_downgraded:
            ma.notes.append(
                f"以下倍数模型因分类置信度 <{_LOW_CONFIDENCE_THRESHOLD:.0%} 再次降权（权重 ×0.25）: "
                f"{', '.join(low_conf_downgraded)}"
            )
        if dup_groups:
            items = "；".join(
                f"{', '.join(members)}"
                for members in dup_groups.values()
            )
            ma.notes.append(
                f"去重：{len(dup_groups)} 组模型共享同一证据来源（{items}）→ "
                f"一致性门控按 {n_independent} 个独立证据计数（而非 {n_solved} 个解算模型）"
            )

        if current_price and ma.median_value is not None and ma.median_value > 0:
            pct = (current_price - ma.median_value) / ma.median_value
            ma.notes.append(f"当前价格 ${current_price:.2f} vs 中位估值 ${ma.median_value:.2f} ({pct:+.1%})")

        # ---- Phase 1.2: forced DCF-vs-multiple divergence diagnostic --------
        # Built whenever we have the underlying data, so a material disagreement
        # can never be hidden behind an IQR-excluded core model: the report must
        # show the diagnostic reasoning, not just a tighter survivor cluster.
        try:
            from analysis.divergence import diagnose_dcf_vs_multiples

            ma.divergence = diagnose_dcf_vs_multiples(
                results, data=data, agreement=ma, profile=profile,
            )
        except Exception as e:  # pragma: no cover - diagnostics must never break valuation
            log.debug(f"divergence diagnostic failed: {e}")

        return ma


__all__ = ["ModelAgreementAnalyzer", "ModelAgreement"]
