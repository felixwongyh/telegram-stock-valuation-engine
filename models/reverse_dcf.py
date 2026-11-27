"""
models/reverse_dcf.py - Reverse DCF Solver
Solves for implied revenue CAGR (and derived FCF CAGR) using the same FCF bridge as forward DCF.

Phase 2 (Session #17) adds a *constraint-based implied solver*: in addition to the
Revenue CAGR, it one-at-a-time inverts four more inputs (operating margin, FCF
margin, WACC, terminal growth) so the report can state the market-implied value
of each while holding every other assumption at its base case.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Callable, List, Optional, Sequence, Tuple

from config import (
    DEFAULT_DCF_CONFIG,
    DEFAULT_REVERSE_DCF_CONFIG,
    GrowthBandVerdict,
    ModelName,
    ReverseDCFConfig,
    SolverStatus,
    classify_growth_band,
    get_logger,
    get_reverse_dcf_config_for,
    resolve_forecast_horizon,
    reverse_dcf_search_bounds,
)
from data.fcf_utils import resolve_ttm_fcf, resolve_ttm_fcf_normalized
from data.models import FinancialData
from forecasts.fcf_projection import (
    attribute_growth_value,
    MIN_WACC_TG_SPREAD,
    dcf_path_inputs_from_data,
    dcf_projection_shape,
    fcf_cagr_from_projection,
    project_enterprise_value_flat_margin,
    project_enterprise_value_from_data,
    project_enterprise_value_shaped,
)
from models.base import (
    ShareCountBasis,
    ValuationAssumption,
    ValuationModel,
    ValuationResult,
    make_share_count,
)
from models.dcf import DCFModel
from valuation.equity_bridge import equity_to_enterprise
from valuation.terminal_growth import TerminalGrowthCalculator

log = get_logger("models.reverse_dcf")

# Bumped whenever the solver's *answer* could legitimately change (algorithm,
# bracket policy, tolerance). A result is only comparable to another with the
# same version — otherwise a moved root is a code change, not a data change.
SOLVER_VERSION = "2.0-brentq-two-layer"


@dataclass
class ImpliedSolve:
    """Result of a single-variable implied solve (Phase 2, Session #17).

    ``value`` is the input that reproduces the target EV *holding every other
    input at its base case*. ``status`` is a ``SolverStatus`` value. When no
    solution exists inside the constraint bounds, ``value`` is ``None`` and
    ``note`` names the binding bound (rather than silently clamping to the edge).
    """
    value: Optional[float]
    status: str
    residual: Optional[float] = None
    rel_residual: Optional[float] = None
    bound_lo: Optional[float] = None
    bound_hi: Optional[float] = None
    note: Optional[str] = None


def _classify_no_root(
    *,
    failure: Optional[str],
    direction_undetermined: bool,
    peak_below_target: bool,
) -> str:
    """Split "no solution" into categories that mean *different* things.

    Collapsing them into one status hides whether the model is wrong, the data
    is wrong, or the question is unanswerable at this precision:

    ``SEARCH_DOMAIN_INSUFFICIENT``
        The market price sits outside the searched growth band, but the model
        itself behaves fine — widen the domain before concluding anything.
    ``NO_ROOT_IN_DOMAIN``
        The model's cash-flow path cannot reach the target EV at any growth in
        the band. A substantive finding about the pricing, not a solver defect.
    ``EV_DIRECTION_UNDETERMINED``
        The direction of EV(g) flips under plausible working-capital
        assumptions, so even "cannot reach it at any growth" is not
        established. The honest answer is "undetermined".
    ``DATA_QUALITY_WARNING``
        Reserved for callers that flag the underlying inputs; a no-root result
        resting on suspect inputs must not read as a valuation conclusion.
    """
    if direction_undetermined:
        return "EV_DIRECTION_UNDETERMINED"
    if failure in ("above_search_ceiling", "below_search_floor"):
        return "SEARCH_DOMAIN_INSUFFICIENT"
    if not peak_below_target:
        # A root exists inside the band but the solver did not find it (the
        # bracket or the iteration limit failed, not the economics).
        return "SOLVER_NONCONVERGENCE"
    return "NO_ROOT_IN_DOMAIN"


def _is_finite_positive(x: Any) -> bool:
    """True only for a real, finite, strictly positive number.

    NaN defeats every naive ``<= 0`` comparison, so validity checks that guard a
    solve must test finiteness first.
    """
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v) and v > 0.0


def _non_finite_outputs(
    rev_cagr: Any, breakdown: dict, target_ev: Any
) -> List[str]:
    """Names of reported values that are not finite.

    A result may only claim SOLVED if every number a reader will see exists in
    the real numbers. ``nan > tol`` and ``nan <= tol`` are both False, so a
    non-finite value silently satisfies *any* threshold comparison - it must be
    caught by an explicit finiteness test, never inferred from a bound check.
    """
    bad: List[str] = []
    if not (isinstance(target_ev, (int, float)) and math.isfinite(target_ev)):
        bad.append(f"enterprise_value={target_ev!r}")
    if not (isinstance(rev_cagr, (int, float)) and math.isfinite(rev_cagr)):
        bad.append(f"implied_revenue_cagr={rev_cagr!r}")
    for key in (
        "implied_revenue_cagr",
        "target_enterprise_value",
        "implied_wacc",
        "ev_peak",
        "ev_peak_growth",
    ):
        val = breakdown.get(key)
        if isinstance(val, (int, float)) and not math.isfinite(val):
            bad.append(f"{key}={val!r}")
    return bad


class ReverseDCFModel(ValuationModel):
    NAME = ModelName.REVERSE_DCF

    def __init__(
        self,
        dcf_config=None,
        reverse_config: Optional[ReverseDCFConfig] = None,
        horizon: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.dcfg = dcf_config or DEFAULT_DCF_CONFIG
        # Copy, never alias: ``DEFAULT_REVERSE_DCF_CONFIG`` is a module-level
        # mutable object, so a caller tuning ``model.rcfg.newton_tol`` on one
        # instance used to rewrite the default for every later instance in the
        # process. That made a ticker's solver tolerances depend on what ran
        # before it (§1.2). ``dataclasses.replace`` on a fresh instance keeps the
        # defaults immutable while still allowing per-instance overrides.
        base = reverse_config or DEFAULT_REVERSE_DCF_CONFIG
        self.rcfg = replace(base)
        # NOTE: the projection window is resolved *per call* from the profile
        # (``_resolve_horizon``), never cached on the instance. ``ReverseDCFModel``
        # is a singleton in ``NAME_TO_MODEL``; the old ``self.horizon = int(...)``
        # inside ``calculate`` leaked one ticker's horizon into the next
        # (Session #16 state-pollution fix). Pass an int here only to force an
        # explicit override for every call.
        self._horizon_override = horizon
        self._dcf = DCFModel(self.dcfg)
        self._tvg_calc = TerminalGrowthCalculator()

    def _resolve_horizon(self, profile: Any) -> int:
        """Per-call horizon: explicit override if given, else per business type."""
        if self._horizon_override is not None:
            return int(self._horizon_override)
        from forecasts.nwc_utils import business_type_from_profile

        return resolve_forecast_horizon(business_type_from_profile(profile))

    def applicability_check(
        self, data: FinancialData, profile: Any
    ) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        if profile and getattr(profile, "is_financial_institution", False):
            reasons.append("ReverseDCF unreliable for financial institutions")
        if data.market.current_price is None or data.market.current_price <= 0:
            reasons.append("Need valid current price to reverse-solve")
        ttm = data.ttm
        if ttm is None:
            reasons.append("No TTM statement")
        else:
            if ttm.shares_outstanding is None or ttm.shares_outstanding <= 0:
                reasons.append("Shares required")
            if ttm.revenue is None or ttm.revenue <= 0:
                reasons.append("TTM revenue required")
            ref_fcf, fcf_src = resolve_ttm_fcf(ttm)
            if ref_fcf is None:
                reasons.append(
                    "TTM free_cash_flow missing; cannot derive from operating_cash_flow + capex"
                )
        ok0, r0 = self._dcf.applicability_check(data, profile)
        reasons.extend(r0)
        return (len(reasons) == 0, reasons)

    def calculate(
        self, data: FinancialData, profile: Any, **kwargs
    ) -> ValuationResult:
        ttm = data.ttm
        if ttm is None:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Reverse DCF requires TTM financials"],
                assumptions=[],
                breakdown={"base_fcf": None, "fcf_source": "missing"},
                data_quality_score=data.quality.data_quality_score,
            )
        price = data.market.current_price
        shares = ttm.shares_outstanding
        # ``price <= 0`` is False for NaN, so a NaN/inf quote slipped through and
        # produced ``target_ev = nan``; the solver then "converged" onto a search
        # bound and reported SOLVED with a fabricated CAGR. Require finiteness
        # explicitly - a non-finite quote is missing data, not a cheap stock.
        if not _is_finite_positive(price) or not _is_finite_positive(shares):
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["A positive current price and TTM share count are required"],
                assumptions=[],
                breakdown={"base_fcf": None, "fcf_source": "missing"},
                data_quality_score=data.quality.data_quality_score,
            )
        target_equity = price * shares
        # Equity → EV via the shared bridge so the target EV is on the *same*
        # claim basis the forward DCF projects (net debt + minority interest +
        # preferred + leases − non-operating assets). Using a bare net-debt
        # target here would make the implied solve inconsistent with the DCF.
        target_ev = equity_to_enterprise(target_equity, data.market)
        # ``price`` and ``shares`` are each finite, but their product (or the
        # bridge) can overflow to inf. Check the *derived* value too: guarding
        # only the inputs would let a finite-but-absurd pair through.
        if not (math.isfinite(target_equity) and math.isfinite(target_ev)):
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.DATA_QUALITY_ERROR,
                notes=[
                    f"股价 × 股数（{price!r} × {shares!r}）或其企业价值桥接溢出为"
                    f"非有限值（equity={target_equity!r}, EV={target_ev!r}）："
                    "输入量级不合理，无法反解隐含增速。"
                ],
                assumptions=[],
                breakdown={"base_fcf": None, "fcf_source": "non_finite_target"},
                data_quality_score=data.quality.data_quality_score,
            )

        # SBC normalization now lives at the FCF main-chain exit (M-69):
        # resolve_ttm_fcf_normalized() applies it ONCE, so this model must not
        # re-apply it (that would double-count SBC). The TTM FCF is CFO − CapEx,
        # which already added SBC back inside CFO; charging it once as an
        # economic cost keeps the reference FCF on the same convention as the
        # margin-built forecast FCF. The raw vs adjusted FCF is recorded for audit.
        base_fcf, fcf_source, sbc_norm = resolve_ttm_fcf_normalized(
            ttm, shares=shares,
        )
        if base_fcf is None:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=[
                    "Reverse DCF stopped: no TTM FCF and cannot derive from OCF + CapEx "
                    "(will not use placeholder Base FCF)."
                ],
                assumptions=[],
                breakdown={"base_fcf": None, "fcf_source": "missing"},
                data_quality_score=data.quality.data_quality_score,
            )

        wacc = self._dcf._estimate_wacc(data, profile)
        tvg = self._tvg_calc.calculate(data, wacc=wacc)
        tg = tvg.base

        # Resolved risk-free rate used by the WACC (single source of truth).
        # The implied-WACC solve is floored at Rf below: a going-concern discount
        # rate below the risk-free rate is economically incoherent, so the solver
        # must report that as a binding bound rather than emit a sub-Rf point
        # estimate (Session #33).
        try:
            risk_free_rate = float(
                self._dcf._estimate_wacc_breakdown(data, profile).risk_free_rate
            )
        except Exception:
            risk_free_rate = None

        # ---- BusinessType-specific reverse DCF overrides ----
        bt_str = getattr(profile, "business_type", "Unknown") if profile else "Unknown"
        bt_params = get_reverse_dcf_config_for(
            bt_str, getattr(profile, "taxonomy_identity_key", None)
        )

        # Terminal growth: the reverse solve MUST invert the same model the
        # forward DCF values, otherwise "implied growth" answers a different
        # question than "what growth would justify the price under our DCF".
        # The DCF's own terminal growth is already business- and
        # currency-aware (TerminalGrowthCalculator), so a per-type override
        # here would silently put the two models on different perpetuity
        # assumptions — for AAPL that alone moved the implied EV by ~20%.
        # The per-type value is therefore reported, never applied.
        tg_per_type = bt_params.get("terminal_growth")
        tg_divergence = (
            float(tg_per_type) - float(tg)
            if tg_per_type is not None and abs(float(tg_per_type) - float(tg)) > 0.0025
            else None
        )

        # Projection window: resolved per call from the profile so it can never
        # leak between tickers via the shared singleton (Session #16).
        horizon = self._resolve_horizon(profile)
        horizon_is_default = bt_params.get("horizon") is None

        # Create a per-call reverse config override
        _min_cagr = bt_params.get("min_implied_cagr")
        _max_cagr = bt_params.get("max_implied_cagr")
        rev_cfg_min = _min_cagr if _min_cagr is not None else self.rcfg.min_implied_cagr
        rev_cfg_max = _max_cagr if _max_cagr is not None else self.rcfg.max_implied_cagr

        # Two-layer bands: `rev_cfg_min/max` is the ECONOMIC PLAUSIBILITY band
        # (what growth we would defend for this business type). The solver is
        # given the wider SEARCH band so that a market pricing implausible
        # growth is reported as such, instead of being masked as "no solution".
        search_lo, search_hi = reverse_dcf_search_bounds(rev_cfg_min, rev_cfg_max)
        solver_meta: dict = {}

        assumptions = [
            ValuationAssumption("Target Price", price, "$/share", "Current market"),
            ValuationAssumption("WACC", round(wacc, 4), "%", "As per DCF"),
            ValuationAssumption("Terminal Growth", round(tg, 4), "%",
                                f"{tvg.source} ({bt_str}) — same as forward DCF"),
            ValuationAssumption(
                "Base FCF (TTM)", base_fcf, "", f"Reference ({fcf_source})"
            ),
            ValuationAssumption(
                "SBC Adjustment", round(sbc_norm.sbc_deduction, 2), "",
                sbc_norm.itemized_note(),
            ),
            ValuationAssumption("Solver Method", "Brent (bracketed) + bisection fallback", "",
                                "Revenue CAGR on the forward DCF's own FCF path"),
            ValuationAssumption("Economic Plausibility Band",
                                f"{rev_cfg_min:.0%} to {rev_cfg_max:.0%}",
                                "", f"Per-type for {bt_str} — labels the result, does not limit the solve"),
            ValuationAssumption("Solver Search Band",
                                f"{search_lo:.0%} to {search_hi:.0%}",
                                "", "Wider than the plausibility band; a root outside it is a finding"),
            ValuationAssumption("Forecast Horizon", str(horizon), "years",
                                "Default" if horizon_is_default else f"Per-type for {bt_str}"),
        ]

        rev_cagr, status, notes, proj = self._solve_revenue_cagr(
            data, profile, target_ev, wacc, tg, horizon=horizon,
            cagr_lo=search_lo, cagr_hi=search_hi, meta_out=solver_meta,
            plausible_lo=rev_cfg_min, plausible_hi=rev_cfg_max,
        )

        # ---- Growth-band verdict (computed after all implied values settle) --
        # "Did the maths find a root" and "is that root economically credible"
        # are different questions, and the answer must describe the number the
        # report actually shows. That number can change below: when the raw
        # bridge has no root, the normalized-economics rescue may still produce
        # an implied growth. Grading the raw ``None`` there would label a
        # displayed 26% as "no root", so the verdict is finalized at the end.
        fcf_quality = self._fcf_base_quality(ttm, base_fcf)
        if fcf_quality is not None:
            notes.append(fcf_quality["note"])
        if tg_divergence is not None:
            notes.append(
                f"注：{bt_str} 类型的终值增长率参考值 {float(tg_per_type):.2%} 与前瞻 DCF "
                f"实际使用的 {tg:.2%} 不一致；反向求解已统一采用 DCF 值，"
                f"以保证「隐含增长」与 DCF 基准可比"
            )

        # Disclose the SBC-adjusted FCF basis whenever it materially moves the
        # reference. The wording must NOT claim the solve runs on this figure:
        # the revenue-CAGR solve inverts a *margin-built* projection
        # (revenue x operating margin), which already carries SBC as an
        # operating expense. ``base_fcf`` is a reporting/bridge reference only.
        _reported_fcf = sbc_norm.reported_fcf
        if (
            sbc_norm.applied
            and _reported_fcf is not None
            and abs(_reported_fcf) > 0
            and abs(sbc_norm.sbc_deduction) > 0.05 * abs(_reported_fcf)
        ):
            notes.insert(
                0,
                f"注：参考 FCF 已按 SBC 归一化（{sbc_norm.method}）——"
                f"报表 TTM FCF {_reported_fcf / 1e9:,.2f}B − SBC "
                f"{sbc_norm.sbc_deduction / 1e9:,.2f}B = "
                f"{base_fcf / 1e9:,.2f}B。该值为桥接/展示口径；"
                f"营收 CAGR 求解走「营收 × 营业利润率」路径，"
                f"营业利润率已含 SBC 费用，故不重复扣减",
            )

        fcf_cagr = None
        if proj is not None:
            fcf_cagr = fcf_cagr_from_projection(proj.fcf_by_year, horizon)

        breakdown = {
            "implied_fcf_cagr": fcf_cagr,
            "implied_revenue_cagr": rev_cagr,
            "target_enterprise_value": target_ev,
            "target_equity_value": target_equity,
            "wacc": wacc,
            "terminal_growth": tg,
            "base_fcf": base_fcf,
            "fcf_source": fcf_source,
            "sbc_normalization": sbc_norm.as_dict(),
            # Terminal-value suppression signal (Session #18) — propagated so the
            # report/risk layer can flag a suppressed-TV reverse DCF.
            "terminal_fcf_negative": (
                bool(getattr(proj, "terminal_fcf_negative", False)) if proj is not None else None
            ),
            # ---- Two-layer growth bands (Session #48) ----------------------
            # `growth_band_verdict` answers "is the solved growth economically
            # credible", separately from "did a root exist". The plausibility
            # band never limits the solve, so a market pricing implausible
            # growth is reported as such instead of as an unexplained price.
            "growth_band_verdict": None,  # finalized below, after implied values settle
            "economic_plausibility_band": [rev_cfg_min, rev_cfg_max],
            "solver_search_band": [search_lo, search_hi],
            "solver_meta": dict(solver_meta),
            "fcf_base_quality": fcf_quality,
        }

        # ---- Projection-vs-reported FCF reconciliation ----------------------
        # The solve inverts a margin-built projection (NOPAT + D&A − CapEx −
        # ΔNWC), while ``base_fcf`` is the reported CFO − CapEx figure. For most
        # names the two agree within a few percent. They diverge badly when the
        # D&A add-back has no matching cash outflow on the CapEx line — the
        # clearest case being content amortisation (NFLX: D&A ≈ 41% of revenue
        # against CapEx ≈ 1%), where the amortised spend is already inside CFO.
        # In that regime the projected FCF is several times the reported FCF, so
        # an implied growth solved on it is not comparable to the reported cash
        # flow and must be disclosed rather than presented as-is.
        _recon_probe = proj
        if _recon_probe is None:
            _recon_probe = project_enterprise_value_from_data(
                data, profile,
                rev_cagr if rev_cagr is not None else rev_cfg_min,
                None, wacc, tg, horizon,
            )
        _recon_fcf_y1 = (
            _recon_probe.fcf_by_year[0]
            if (_recon_probe is not None and _recon_probe.fcf_by_year)
            else None
        )
        if (
            _recon_fcf_y1 is not None
            and base_fcf is not None
            and abs(base_fcf) > 0
        ):
            _recon_gap = abs(_recon_fcf_y1 - base_fcf) / abs(base_fcf)
            breakdown["projection_vs_reported_fcf"] = {
                "projection_year1": _recon_fcf_y1,
                "reported_ttm": base_fcf,
                "relative_gap": _recon_gap,
            }
            if _recon_gap > 0.50:
                breakdown["projection_fcf_caliber_mismatch"] = True
                notes.append(
                    f"注：投影首年 FCF ${_recon_fcf_y1 / 1e9:,.2f}B 与报表 TTM FCF "
                    f"${base_fcf / 1e9:,.2f}B 相差 {_recon_gap:.0%}。"
                    f"投影按「NOPAT + 折旧摊销 − 资本开支 − 营运资本变动」构建，"
                    f"当折旧摊销远大于资本开支（如内容/无形摊销对应的现金支出已计入"
                    f"经营现金流）时，该口径会高于报表 FCF；隐含增长基于投影口径，"
                    f"与报表现金流不可直接比较"
                )

        # ---- Normalized-economics diagnostic (Session #07) ------------------
        # For deeply FCF-negative, capital-intensive names (capex > revenue) the
        # FCF bridge yields a *negative* EV, so "no solution in range" with a
        # negative EV is meaningless. Re-solve under a normalized mature-economics
        # profile (steady-state margin + normalized capex) and report the implied
        # minimum growth — a positive, interpretable statement.
        #
        # The normalized search is bounded by the SAME per-type band the raw solve
        # uses: an implied CAGR surfaced as a "market expectation" must never fall
        # outside the business type's sanctioned range, or the report contradicts
        # itself (e.g. a copper miner "implying" a 75% CAGR against a 25% ceiling).
        binding: Optional[str] = None
        if rev_cagr is None:
            # Explain the "no solution" honestly instead of leaving the implied
            # block silent. Recompute EV at the sanctioned band edges so the
            # binding bound can be named (the raw solve already failed, so one
            # of these must hold).
            ev_at_floor = self._project_ev(data, profile, rev_cfg_min, wacc, tg, horizon)
            ev_at_ceiling = self._project_ev(data, profile, rev_cfg_max, wacc, tg, horizon)
            # Direction matters: "above ceiling" asserts that a *higher* growth
            # would reach the price. When EV falls as growth rises that claim is
            # false, so the bound is reported as a non-monotone model limit
            # rather than a growth ceiling (NEE/CEG: EV peaks near g=0).
            #
            # The direction must also survive the NWC inference before it is
            # used to label anything: the marginal ΔNWC ratio is a residual and
            # for 13 of 41 benchmark tickers the direction flips at a plausible
            # value (SO: rising at its own ratio, falling at 5%). Labelling
            # "implied growth ≥ ceiling" there would assert a monotonicity the
            # data does not support.
            ev_rising = ev_at_ceiling > ev_at_floor
            nwc_used = self._nwc_ratio_for(data, profile, horizon)
            band_robustness = self._ev_direction_robustness(
                data, profile, wacc, tg, horizon, rev_cfg_min, rev_cfg_max,
                list(self.rcfg.nwc_sensitivity_ratios) + [nwc_used],
            )
            direction_undetermined = not band_robustness.get("robust")
            if direction_undetermined:
                binding = "ev_direction_undetermined"
            elif ev_rising:
                binding = (
                    "above_band_ceiling" if ev_at_ceiling < target_ev
                    else "below_band_floor"
                )
            else:
                binding = "ev_decreasing_in_growth"
            breakdown["implied_revenue_cagr_binding"] = binding
            # Structured bound (Session #31): the market price sits outside what
            # the sanctioned growth band can justify. Surface this as a *bound*
            # (≥ ceiling / ≤ floor) with the EV it implies — never as a
            # fabricated point estimate. Downstream can state "growth alone
            # cannot explain the price" without inventing a number.
            bound_value = rev_cfg_max if binding != "below_band_floor" else rev_cfg_min
            bound_ev = (
                ev_at_ceiling if binding != "below_band_floor" else ev_at_floor
            )
            breakdown["implied_revenue_cagr_bound"] = {
                "kind": binding,
                "value": bound_value,
                "ev_at_bound": bound_ev,
            }

            # The mature-steady-state rescue applies ONLY when the actual FCF
            # bridge is broken (TTM FCF ≤ 0 or a suppressed terminal value).
            # Applying it to a healthy name would *replace* good economics with
            # the conservative 20% margin / 15% capex profile, which can only
            # understate value — so it is skipped there and the honest bound is
            # reported instead (Session #30).
            #
            # ``base_fcf`` is an SBC-normalized *reporting* figure; the projection
            # is built from revenue x operating margin. A name whose reported FCF
            # is negative only because of the SBC deduction (e.g. a profitable
            # company with large stock comp) is NOT bridge-broken. Judge on the
            # projection's own first-year FCF; the raw solve failed so ``proj`` is
            # None here and we must project once at the band floor to obtain it.
            _proj_probe = project_enterprise_value_from_data(
                data, profile, rev_cfg_min, None, wacc, tg, horizon
            )
            _proj_fcf_y1 = (
                _proj_probe.fcf_by_year[0]
                if (_proj_probe is not None and _proj_probe.fcf_by_year)
                else None
            )
            _bridge_ref = _proj_fcf_y1 if _proj_fcf_y1 is not None else base_fcf
            bridge_broken = _bridge_ref <= 0 or bool(breakdown.get("terminal_fcf_negative"))
            breakdown["bridge_reference_fcf"] = _bridge_ref
            breakdown["bridge_reference_source"] = (
                "projection_year1" if _proj_fcf_y1 is not None else "sbc_normalized_ttm"
            )
            normalized = (
                self._normalized_growth_solve(
                    data, profile, target_ev, wacc, tg, horizon=horizon,
                    cagr_lo=rev_cfg_min, cagr_hi=rev_cfg_max,
                )
                if bridge_broken else None
            )
            a = normalized.get("assumptions", {}) if normalized is not None else {}
            if normalized is not None and normalized.get("implied_revenue_cagr") is not None:
                # Surface the normalized-economics derivation into the STRUCTURED
                # implied field — otherwise the "市场隐含预期" block renders N/A
                # while the value only exists in free-text notes (Round-3 defect:
                # note said ≈26% but the field said N/A).
                breakdown["normalized_growth_solve"] = normalized
                breakdown["implied_revenue_cagr"] = normalized["implied_revenue_cagr"]
                breakdown["implied_revenue_cagr_source"] = "normalized_growth_solve"
                notes.append(
                    f"隐含量化（按成熟稳态假设：营业利润率 {a.get('operating_margin', 0):.0%}、"
                    f"capex/营收 {a.get('capex_ratio', 0):.0%}）：当前价隐含营收 CAGR "
                    f"≈ {normalized['implied_revenue_cagr']:.0%}"
                )
            elif binding == "above_band_ceiling":
                # Honest bound: the market price sits above what the model can
                # justify even at the type's sanctioned growth ceiling. Stated as
                # "implied growth ≥ ceiling" — never as a fabricated point value.
                notes.append(
                    f"当前股价已高于模型在 {bt_str} 类型营收 CAGR 上限 {rev_cfg_max:.0%} 内"
                    f"所能支撑的估值（模型推算 EV 上限 ${ev_at_ceiling:,.0f} < 目标 EV "
                    f"${target_ev:,.0f}）：市场隐含营收 CAGR ≥ {rev_cfg_max:.0%}，"
                    f"超出该业务类型的合理性上限"
                )
            elif binding == "ev_direction_undetermined":
                notes.append(
                    f"在 {bt_str} 类型合理区间 "
                    f"[{rev_cfg_min:.0%}, {rev_cfg_max:.0%}] 内，模型 EV 随营收 CAGR 的"
                    f"方向对营运资本假设敏感（在合理参数范围内既可能上升也可能下降），"
                    f"因此该区间无法给出「市场隐含增速」的上下界"
                )
            elif binding == "ev_decreasing_in_growth":
                # Growth is not a lever that reaches the price here: EV falls as
                # growth rises, so "implied growth >= ceiling" would be false.
                # But the endpoints alone cannot prove monotonicity — LLY peaks
                # *inside* the band (g≈10%) and then declines, so a blanket
                # "falls throughout" statement would contradict the peak the
                # solver note reports. Name the interior peak when there is one.
                interior_peak_g, interior_peak_ev = self._peak_in_band(
                    data, profile, wacc, tg, horizon,
                    rev_cfg_min, rev_cfg_max,
                )
                if (
                    interior_peak_ev > max(ev_at_floor, ev_at_ceiling) * (1 + 1e-9)
                    and rev_cfg_min < interior_peak_g < rev_cfg_max
                ):
                    notes.append(
                        f"在 {bt_str} 类型合理区间 "
                        f"[{rev_cfg_min:.0%}, {rev_cfg_max:.0%}] 内，模型 EV 在 "
                        f"g≈{interior_peak_g:.0%} 处达到最大值 ${interior_peak_ev:,.0f} "
                        f"后转为下降（两端为 ${ev_at_floor:,.0f} / ${ev_at_ceiling:,.0f}）："
                        f"曲线非单调，因此该区间无法给出「市场隐含增速」的上下界"
                    )
                else:
                    notes.append(
                        f"在 {bt_str} 类型合理区间 "
                        f"[{rev_cfg_min:.0%}, {rev_cfg_max:.0%}] 内，模型 EV 随营收 CAGR "
                        f"上升而下降（${ev_at_floor:,.0f} → ${ev_at_ceiling:,.0f}），"
                        f"因此该区间无法给出「市场隐含增速」的上下界"
                    )
            else:
                notes.append(
                    f"当前股价低于模型在 {bt_str} 类型营收 CAGR 下限 {rev_cfg_min:.0%} 时的"
                    f"推算 EV（${ev_at_floor:,.0f} > 目标 EV ${target_ev:,.0f}）：市场隐含"
                    f"营收 CAGR ≤ {rev_cfg_min:.0%}，低于该业务类型的合理下限"
                )

        # ---- Phase 2: constraint-based implied expectations (Session #17) ----
        # One-at-a-time inverse solves for the *other* value drivers, holding the
        # solved revenue CAGR as the base case. Uses the normalized-solve CAGR
        # when the raw bridge had no solution (deeply FCF-negative names).
        base_cagr_for_implied = rev_cagr
        if base_cagr_for_implied is None:
            base_cagr_for_implied = breakdown.get("implied_revenue_cagr")
        if base_cagr_for_implied is None and breakdown.get("implied_revenue_cagr_bound") is not None:
            # Growth alone cannot reproduce the target inside the sanctioned band
            # (Session #31). Pin growth at the binding edge and still run the
            # one-at-a-time implied solves for the *other* drivers, so the report
            # answers "what would have to be true" (margin / WACC / terminal
            # growth) instead of leaving the whole implied block N/A. The base
            # CAGR is explicitly flagged as a bound, not a solved expectation.
            base_cagr_for_implied = breakdown["implied_revenue_cagr_bound"]["value"]
            breakdown["implied_base_cagr_is_bound"] = True
        if base_cagr_for_implied is not None:
            try:
                breakdown["implied_expectations"] = self._implied_expectations(
                    data, profile, target_ev, wacc, tg, horizon, base_cagr_for_implied,
                    risk_free_rate=risk_free_rate,
                )
            except Exception as e:  # never let a diagnostic solve break the model
                log.info("implied expectations solve skipped: %s", e)

        # Backfill the top-level suppression flag (Session #18): when the raw
        # revenue-CAGR solve produced no projection (proj is None) but the implied
        # block found a suppressed terminal value on the base projection, surface
        # it at the top level too — otherwise consumers reading
        # ``breakdown["terminal_fcf_negative"]`` would see None while the TV was
        # in fact suppressed.
        ie_block = breakdown.get("implied_expectations")
        if breakdown.get("terminal_fcf_negative") is None and isinstance(ie_block, dict):
            breakdown["terminal_fcf_negative"] = ie_block.get("terminal_fcf_negative")

        # ---- Finalize the growth-band verdict -------------------------------
        # Grade the growth the report actually reports. Prefer the raw solved
        # root; fall back to the normalized-economics estimate when that is what
        # the reader will see. Never let a data-quality defect pass as a finding.
        reported_cagr = rev_cagr
        if reported_cagr is None:
            reported_cagr = breakdown.get("implied_revenue_cagr")
        band_verdict = classify_growth_band(reported_cagr, rev_cfg_min, rev_cfg_max)
        if fcf_quality is not None:
            # A negative base FCF admits no growth interpretation at all: the
            # normalized-economics estimate that rescues such names is a
            # hypothetical ("if this matured"), not an implied expectation, so it
            # must never be labelled "within the plausible band" — that would turn
            # a cash-burning company into a comforting data point.
            if fcf_quality["reason"] == "negative_base_fcf":
                if reported_cagr is None:
                    # No root at all on a negative cash-flow base: the reverse-DCF
                    # premise fails, so this is neither "growth too high" nor a
                    # usable warning number.
                    band_verdict = GrowthBandVerdict.NEGATIVE_BASE_FCF_NO_VALID_ROOT
                else:
                    band_verdict = GrowthBandVerdict.DATA_QUALITY_WARNING
            elif band_verdict in (
                GrowthBandVerdict.OUTSIDE_BASE_BAND,
                GrowthBandVerdict.EXTREME_GROWTH,
            ):
                band_verdict = GrowthBandVerdict.DATA_QUALITY_WARNING
        breakdown["growth_band_verdict"] = band_verdict.value

        # ---- Solver input dependencies (Session #52) ------------------------
        # Which inputs the implied-growth solve actually consumes is not obvious
        # from the outside: TTM FCF is a *display* figure (SBC-normalised bridge)
        # and does not move the answer, while revenue and operating margin do.
        # Stating this explicitly stops a reader from assuming "base FCF drives
        # implied growth" and concluding the model is broken when FCF changes
        # leave the CAGR untouched.
        breakdown["solver_input_dependencies"] = {
            "drivers": {
                "revenue_ttm": "求解驱动：投影按 营收 × 营业利润率 构建现金流路径",
                "operating_margin": "求解驱动：历史利润率决定 NOPAT，进而决定 FCF",
                "wacc": "求解驱动：折现率",
                "terminal_growth": "求解驱动：永续增长率",
                "shares_outstanding": "求解驱动：与股价相乘得到目标权益，经桥接得到目标 EV",
                "current_price": "求解驱动：反解的目标",
            },
            "display_only": {
                "base_fcf": "仅展示/参考：SBC 归一后的桥接口径，不参与营收 CAGR 反解",
                "sbc_deduction": "仅展示：已含在营业利润率路径中，不重复扣减",
                "projection_vs_reported_fcf": "仅披露：投影 FCF 与报表 FCF 的口径差异",
            },
            "projection_participants": {
                "capex": "参与投影：从 NOPAT 扣除",
                "da": "参与投影：加回 NOPAT",
                "nwc_delta": "参与投影：营运资本增量扣减",
            },
        }

        # ---- Local WACC elasticity (Session #52) ----------------------------
        # Report the *local* sensitivity of implied growth to the discount rate
        # via a central difference. It is a property of this ticker at this
        # growth/WACC, not a universal constant, so it is recorded with the
        # evaluation point rather than assumed to be ~4x everywhere.
        #
        # The root is defined implicitly by EV(g, wacc) = target, so
        #   dg/dwacc = -(dEV/dwacc) / (dEV/dg)
        # Both partials come from central differences at the solved point. Taking
        # only dEV/dwacc would report a value with the wrong units and the wrong
        # sign (EV falls as WACC rises, growth rises as WACC rises).
        if rev_cagr is not None:
            try:
                h = 0.0025
                pts = {
                    "w_up": (rev_cagr, wacc + h),
                    "w_dn": (rev_cagr, wacc - h),
                    "g_up": (rev_cagr + h, wacc),
                    "g_dn": (rev_cagr - h, wacc),
                }
                ev = {
                    k: self._project_ev(data, profile, g, w, tg, horizon)
                    for k, (g, w) in pts.items()
                }
                if all(math.isfinite(v) for v in ev.values()):
                    d_ev_dw = (ev["w_up"] - ev["w_dn"]) / (2 * h)
                    d_ev_dg = (ev["g_up"] - ev["g_dn"]) / (2 * h)
                    dg_dw = (
                        -d_ev_dw / d_ev_dg if abs(d_ev_dg) > 0 else None
                    )
                    breakdown["wacc_local_elasticity"] = {
                        "dg_dwacc": dg_dw,
                        "d_ev_dwacc": d_ev_dw,
                        "d_ev_dgrowth": d_ev_dg,
                        "method": "implicit function: -(dEV/dWACC)/(dEV/dg), central difference",
                        "wacc": wacc,
                        "growth": rev_cagr,
                        "step": h,
                    }
            except Exception as e:  # never let a diagnostic break the solve
                log.info("wacc local elasticity skipped: %s", e)

        if band_verdict == GrowthBandVerdict.OUTSIDE_BASE_BAND:
            notes.append(
                f"⚠️ 隐含营收 CAGR {reported_cagr:.2%} 超出 {bt_str} 的经济合理区间 "
                f"[{rev_cfg_min:.0%}, {rev_cfg_max:.0%}]：数学上有解，但该增速对"
                f"本商业模式属高要求，不宜直接作为正常估值结论"
            )
        elif band_verdict == GrowthBandVerdict.EXTREME_GROWTH:
            notes.append(
                f"⚠️ 隐含营收 CAGR {reported_cagr:.2%} 远超 {bt_str} 的经济合理区间 "
                f"[{rev_cfg_min:.0%}, {rev_cfg_max:.0%}]：仅在极端增长假设下成立，"
                f"更可能是现金流基数或再投资假设存在问题"
            )
        elif band_verdict == GrowthBandVerdict.NO_ROOT_IN_EXPANDED_RANGE:
            notes.append(
                f"在扩展搜索区间 [{search_lo:.0%}, {search_hi:.0%}] 内仍无根："
                f"目标 EV 无法由本模型的现金流路径解释（非带宽伪影）"
            )

        if rev_cagr is None:
            return ValuationResult(
                model_name=self.model_name,
                status=status,
                notes=notes,
                assumptions=assumptions,
                breakdown=breakdown,
                data_quality_score=data.quality.data_quality_score,
            )

        # ---- Final output finiteness gate (Session #52, P0-7) ----------------
        # Everything above can pass while a *reported* number is still non-finite
        # (a projection that overflowed only at the root, an implied sub-solve
        # that divided by ~0). A SOLVED answer is a promise that the numbers are
        # usable, so the promise is checked at the boundary rather than trusted.
        non_finite = _non_finite_outputs(rev_cagr, breakdown, target_ev)
        if non_finite:
            notes.append(
                "⚠️ 最终输出含非有限数值（"
                + ", ".join(non_finite)
                + "）：结果不可用，已降级为数据质量问题而非估值结论"
            )
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.DATA_QUALITY_ERROR,
                notes=notes,
                assumptions=assumptions,
                breakdown=breakdown,
                data_quality_score=data.quality.data_quality_score,
            )

        # ---- SOLVED eligibility gate (Session #52) --------------------------
        # Ten independent conditions, checked in one place. The gate only ever
        # demotes: a status that claims SOLVED but cannot prove every clause is
        # reported as APPROXIMATE with the failing conditions named, so a reader
        # sees *why* the claim was withdrawn rather than a silent downgrade.
        if status == SolverStatus.SOLVED:
            from models.solved_eligibility import check_solved_eligibility

            eligibility = check_solved_eligibility(
                price=price,
                shares=shares,
                target_ev=target_ev,
                wacc=wacc,
                terminal_growth=tg,
                solver_meta=solver_meta,
                implied_revenue_cagr=rev_cagr,
                value_per_share=price,
                growth_band_verdict=breakdown.get("growth_band_verdict"),
                price_residual_tol=self.rcfg.price_residual_tol,
                recompute_ev=lambda g: self._project_ev(
                    data, profile, g, wacc, tg, horizon
                ),
            )
            breakdown["solved_eligibility"] = {
                "passed": eligibility.ok,
                "checks": eligibility.checks,
                "failed": eligibility.failed,
            }
            if not eligibility.ok:
                notes.append(eligibility.note())
                status = SolverStatus.APPROXIMATE

        return ValuationResult(
            model_name=self.model_name,
            status=status,
            value_per_share=price,
            enterprise_value=target_ev,
            equity_value=target_equity,
            assumptions=assumptions,
            notes=notes,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
            share_count=make_share_count(
                shares, "TTM 财务报表股数", ShareCountBasis.TTM, ttm.period_end
            ),
        )

    def _project_ev(
        self,
        data: FinancialData,
        profile: Any,
        rev_cagr: float,
        wacc: float,
        tg: float,
        horizon: int,
        nwc_ratio: Optional[float] = None,
    ) -> float:
        proj = project_enterprise_value_from_data(
            data, profile, rev_cagr, None, wacc, tg, horizon,
            nwc_ratio_override=nwc_ratio,
        )
        if proj is None:
            # Returning 0.0 here would present a *failed* projection as a
            # legitimate EV of zero, which the solver would happily invert
            # (a zero target is reachable and would be reported as a root).
            # NaN is the honest answer: "no EV exists at this growth", and the
            # solver refuses any non-finite objective value.
            return float("nan")
        return proj.enterprise_value

    def _ev_curve_peaks(
        self,
        data: FinancialData,
        profile: Any,
        wacc: float,
        tg: float,
        horizon: int,
        lo: float,
        hi: float,
        samples: int = 61,
    ) -> List[dict]:
        """Find *all* local maxima of EV(g) on ``[lo, hi]``, refined locally.

        A single grid maximum assumes the curve is unimodal. That assumption is
        not safe: EV is a ratio of a growth-scaled numerator to a discount
        factor, and a non-monotone working-capital / margin path can produce
        more than one turning point. Reporting only the global grid maximum
        would silently hide a second peak — and if the *global* peak sits at a
        growth the business type disallows, the "best plausible growth" claim
        would be wrong.

        Returns one dict per local maximum (including the endpoints when they
        are the extreme), sorted by EV descending. Each entry carries the
        refined growth, EV, and whether it sits on a band edge.
        """
        if hi <= lo:
            return [{
                "growth": lo,
                "ev": self._project_ev(data, profile, lo, wacc, tg, horizon),
                "at_edge": True,
            }]
        grid = [lo + (hi - lo) * i / samples for i in range(samples + 1)]
        values: List[Tuple[float, float]] = []
        for g in grid:
            try:
                values.append((g, self._project_ev(data, profile, g, wacc, tg, horizon)))
            except Exception:
                continue
        if not values:
            return []
        if len(values) == 1:
            return [{"growth": values[0][0], "ev": values[0][1], "at_edge": True}]

        candidates: List[Tuple[int, float, float]] = []
        # Interior local maxima.
        for i in range(1, len(values) - 1):
            if values[i][1] >= values[i - 1][1] and values[i][1] >= values[i + 1][1]:
                candidates.append((i, values[i][0], values[i][1]))
        # Endpoints are always candidates: a peak may sit on the band edge.
        candidates.append((0, values[0][0], values[0][1]))
        candidates.append((len(values) - 1, values[-1][0], values[-1][1]))

        peaks: List[dict] = []
        for idx, _g, _ev in candidates:
            left = values[idx - 1][0] if idx > 0 else _g
            right = values[idx + 1][0] if idx < len(values) - 1 else _g
            best_g, best_ev = _g, _ev
            if right > left:
                for _ in range(60):
                    if right - left < 1e-6:
                        break
                    m1 = left + (right - left) / 3.0
                    m2 = right - (right - left) / 3.0
                    try:
                        f1 = self._project_ev(data, profile, m1, wacc, tg, horizon)
                        f2 = self._project_ev(data, profile, m2, wacc, tg, horizon)
                    except Exception:
                        break
                    if f1 < f2:
                        left = m1
                    else:
                        right = m2
                mid = (left + right) / 2.0
                try:
                    mid_ev = self._project_ev(data, profile, mid, wacc, tg, horizon)
                except Exception:
                    mid_ev = best_ev
                if mid_ev > best_ev:
                    best_g, best_ev = mid, mid_ev
            peaks.append({
                "growth": best_g,
                "ev": best_ev,
                "at_edge": idx in (0, len(values) - 1),
            })

        # Deduplicate peaks that converged to the same growth, keeping the best.
        merged: List[dict] = []
        for p in sorted(peaks, key=lambda x: x["ev"], reverse=True):
            if any(abs(p["growth"] - q["growth"]) < 1e-4 for q in merged):
                continue
            merged.append(p)
        return merged

    def _peak_in_band(
        self,
        data: FinancialData,
        profile: Any,
        wacc: float,
        tg: float,
        horizon: int,
        lo: float,
        hi: float,
        samples: int = 61,
    ) -> Tuple[float, float]:
        """The global EV maximum on ``[lo, hi]`` as ``(growth, ev)``."""
        peaks = self._ev_curve_peaks(
            data, profile, wacc, tg, horizon, lo, hi, samples=samples
        )
        if not peaks:
            return lo, 0.0
        best = peaks[0]
        return best["growth"], best["ev"]

    def _growth_value_attribution(
        self,
        data: FinancialData,
        profile: Any,
        wacc: float,
        tg: float,
        horizon: int,
        g_lo: float,
        g_hi: float,
    ) -> Optional[dict]:
        """Exact additive split of EV(g_hi) − EV(g_lo) by FCF component.

        Explains *why* the curve has the shape it does: e.g. NEE's growth adds
        NOPAT and D&A but CapEx and the terminal value subtract more, so the
        components nearly cancel and the sign of the total is fragile. A
        cancellation ratio far above 1 is the numeric signature of "this
        conclusion depends on inputs we cannot pin down".
        """
        try:
            inputs = dcf_path_inputs_from_data(data, profile, horizon)
            if inputs is None:
                return None
            _, shape, offsets, om_center = dcf_projection_shape(
                inputs.base_revenue, inputs.base_growth, inputs.base_margin, horizon
            )
            attr = attribute_growth_value(
                inputs.base_revenue,
                om_center,
                inputs.tax_rate,
                inputs.da_ratio,
                abs(inputs.capex_ratio),
                inputs.nwc_marginal_ratio,
                wacc,
                tg,
                horizon,
                g_lo,
                g_hi,
                growth_shape=shape,
                margin_offsets=offsets,
            )
            return attr.as_dict()
        except Exception:
            return None

    def _nwc_ratio_for(
        self, data: FinancialData, profile: Any, horizon: int
    ) -> float:
        """The marginal ΔNWC ratio the projection will actually use."""
        try:
            inputs = dcf_path_inputs_from_data(data, profile, horizon)
            if inputs is not None:
                return float(inputs.nwc_marginal_ratio)
        except Exception:
            pass
        return 0.0

    def _ev_direction_robustness(
        self,
        data: FinancialData,
        profile: Any,
        wacc: float,
        tg: float,
        horizon: int,
        band_lo: float,
        band_hi: float,
        nwc_ratios: Sequence[float],
    ) -> dict:
        """Does the EV-vs-growth *direction* survive plausible NWC assumptions?

        The marginal ΔNWC ratio is the least reliable input in the projection:
        it is inferred as a residual (NOPAT + D&A − capex − FCF), so it absorbs
        every one-off working-capital swing. On the 50-ticker benchmark the
        ratio swings widely across defensible estimators (NEE: 14% per-year
        marginal vs 25% aggregate slope) and the EV direction *flips* at a
        plausible value for 13 of 41 tickers. Asserting "growth destroys value"
        from a single point estimate would therefore state a conclusion the data
        does not support.

        This probes EV at the band edges under several NWC assumptions and
        reports whether every one agrees on the direction. A non-robust result
        must be reported as "direction undetermined", never as a mechanism.
        """
        directions: dict[float, int] = {}
        for ratio in nwc_ratios:
            try:
                ev_lo = self._project_ev(
                    data, profile, band_lo, wacc, tg, horizon, nwc_ratio=ratio
                )
                ev_hi = self._project_ev(
                    data, profile, band_hi, wacc, tg, horizon, nwc_ratio=ratio
                )
            except Exception:
                continue
            directions[ratio] = 1 if ev_hi > ev_lo else -1
        if not directions:
            return {"robust": False, "reason": "no_projection_succeeded"}
        ordered = sorted(directions.items())
        signs = {sign for _, sign in ordered}
        robust = len(signs) == 1
        flips = [
            (round(ordered[i][0], 4), round(ordered[i + 1][0], 4))
            for i in range(len(ordered) - 1)
            if ordered[i][1] != ordered[i + 1][1]
        ]
        return {
            "robust": robust,
            "direction": (
                ("increasing" if ordered[0][1] > 0 else "decreasing")
                if robust else "mixed"
            ),
            "by_nwc_ratio": {round(k, 4): v for k, v in ordered},
            # The adjacent candidate pair where the sign actually changes, so a
            # reader can see *where* the conclusion stops holding — not merely
            # the span of the candidate set.
            "flips_between": flips or None,
        }


    def _solve_revenue_cagr(
        self,
        data: FinancialData,
        profile: Any,
        target_ev: float,
        wacc: float,
        tg: float,
        horizon: int,
        cagr_lo: Optional[float] = None,
        cagr_hi: Optional[float] = None,
        meta_out: Optional[dict] = None,
        plausible_lo: Optional[float] = None,
        plausible_hi: Optional[float] = None,
    ) -> Tuple[Optional[float], SolverStatus, List[str], Any]:
        notes: List[str] = []
        # Defence in depth: a non-finite target can never be inverted. NaN would
        # sail through brentq's sign tests and return a bound labelled SOLVED.
        # This is a data/numerical-domain failure, not an economic verdict, so it
        # is reported as DATA_QUALITY_ERROR rather than NO_SOLUTION or SOLVED.
        if not (isinstance(target_ev, (int, float)) and math.isfinite(target_ev)):
            notes.append(f"目标 EV 非有限值（{target_ev!r}）→ 数据质量问题，拒绝求解")
            return None, SolverStatus.DATA_QUALITY_ERROR, notes, None
        if not (math.isfinite(wacc) and math.isfinite(tg)):
            notes.append("WACC/终值增长率非有限值 → 数据质量问题，拒绝求解")
            return None, SolverStatus.DATA_QUALITY_ERROR, notes, None
        lo = cagr_lo if cagr_lo is not None else self.rcfg.min_implied_cagr
        hi = cagr_hi if cagr_hi is not None else self.rcfg.max_implied_cagr
        # The peak / direction statements must be confined to the *plausibility*
        # band, not the wider search band: quoting "best plausible growth" at a
        # CAGR the business type disallows would be self-contradictory (SO's EV
        # peaks at 15% under a [-2%, 10%] utility band).
        band_lo = plausible_lo if plausible_lo is not None else lo
        band_hi = plausible_hi if plausible_hi is not None else hi
        if band_hi <= band_lo:
            band_lo, band_hi = lo, hi
        try:
            ev_lo = self._project_ev(data, profile, lo, wacc, tg, horizon)
            ev_hi = self._project_ev(data, profile, hi, wacc, tg, horizon)
        except Exception as e:
            if meta_out is not None:
                meta_out.update({
                    "solver_method": "brentq (bracketed)",
                    "solver_version": SOLVER_VERSION,
                    "search_bounds": [lo, hi],
                    "converged": False,
                    "failure": f"projection_error: {e}",
                })
            return None, SolverStatus.INFEASIBLE, [f"Projection error: {e}"], None

        # Endpoint equality is itself a solution (boundary root) - but it must
        # clear the *same* price-residual bar as an interior root. Using a looser
        # absolute tolerance here let a target 5e-4 relative away from the
        # endpoint EV be reported SOLVED with no residual computed at all, i.e.
        # the residual gate was bypassed by the short-circuit (§3.1).
        tol = self.rcfg.price_residual_tol
        for bound, ev_bound in ((lo, ev_lo), (hi, ev_hi)):
            if not math.isfinite(ev_bound):
                # ``nan > tol`` is False, so an overflowing projection used to
                # pass this gate and be reported as a boundary root. A non-finite
                # endpoint EV is a numerical failure, never a solution.
                continue
            rel = abs(ev_bound - target_ev) / abs(target_ev) if target_ev else 0.0
            if not math.isfinite(rel) or rel > tol:
                continue
            proj = project_enterprise_value_from_data(
                data, profile, bound, None, wacc, tg, horizon
            )
            if meta_out is not None:
                meta_out.update({
                    "solver_method": "brentq (bracketed)",
                    "solver_version": SOLVER_VERSION,
                    "search_bounds": [lo, hi],
                    "residual": abs(ev_bound - target_ev),
                    "relative_residual": rel,
                    "converged": True,
                    "n_roots_detected": 1,
                    "roots": [round(bound, 6)],
                    "multiple_roots": False,
                    "root_at_bound": True,
                })
            return self._finalize_revenue_cagr(bound, SolverStatus.SOLVED, notes, proj)

        if (ev_lo - target_ev) * (ev_hi - target_ev) > 0:
            # Same sign at both ends ⇒ no sign change ⇒ no bracketed root.
            # Which *kind* of no-root this is depends on the direction of the
            # EV curve, not on where `ev_hi` happens to sit:
            #
            #   * monotone increasing (ev_lo < ev_hi): the whole curve sits
            #     below or above the target ⇒ target above ceiling / below floor.
            #   * monotone decreasing (ev_lo > ev_hi): growth *destroys* value,
            #     which happens when the terminal FCF is suppressed (≤ 0) and
            #     the explicit period cannot carry the valuation. Labelling this
            #     "above_search_ceiling" is false — a *lower* growth would get
            #     closer, so the target is not above any ceiling.
            #
            # Both cases mean the model cannot explain the price, so the status
            # stays NO_SOLUTION_IN_RANGE, but `failure` must name the real cause.
            increasing = ev_hi > ev_lo
            if increasing:
                if ev_hi < target_ev:
                    if ev_hi < 0:
                        notes.append(
                            f"即便取 {hi:.0%} 营收 CAGR 上限，模型推算 EV 仍为负"
                            f"（约 ${ev_hi:,.0f}）：FCF 深度为负、终值无法支撑正的"
                            f"企业价值 → 当前价隐含的增长超出模型可解区间"
                        )
                    else:
                        notes.append(
                            f"在 {hi:.0%} 营收 CAGR 上限内无法达到目标 EV "
                            f"${target_ev:,.0f}（模型推算 EV 上限 ${ev_hi:,.0f}，仍低于目标）"
                        )
                    failure = "above_search_ceiling"
                else:
                    notes.append(
                        f"在 {lo:.0%} 营收 CAGR 下限时推算 EV ${ev_lo:,.0f} 已高于目标 "
                        f"${target_ev:,.0f}（市场隐含增长低于模型下限）"
                    )
                    failure = "below_search_floor"
            else:
                # Direction stability is decided against the *sanctioned* band,
                # the same window the report quotes. The NWC ratio is a residual
                # and for 13 of 41 benchmark tickers the direction flips at a
                # plausible value, so a mechanism must not be asserted unless it
                # holds across them.
                nwc_used = self._nwc_ratio_for(data, profile, horizon)
                band_robustness = self._ev_direction_robustness(
                    data, profile, wacc, tg, horizon,
                    band_lo, band_hi,
                    list(self.rcfg.nwc_sensitivity_ratios) + [nwc_used],
                )
                direction_undetermined = not band_robustness.get("robust")
                # EV falls as growth rises. The cause is *not* always a
                # suppressed terminal value, so find where EV actually peaks
                # instead of asserting a mechanism that may not apply (NEE's
                # terminal FCF is positive, yet EV still declines). Reporting
                # the achievable maximum turns "no root" into an actionable
                # statement: the model cannot justify the price at *any* growth.
                # Scan for the peak inside the *sanctioned* band, not the
                # expanded search window: "even at the best plausible growth"
                # must not point at a growth the business type disallows.
                scan_lo, scan_hi = band_lo, band_hi
                # Enumerate *all* local maxima, not just the grid maximum: a
                # non-monotone curve can have several turning points and the
                # global one may sit at an edge the business type disallows.
                peaks = self._ev_curve_peaks(
                    data, profile, wacc, tg, horizon, scan_lo, scan_hi
                )
                if peaks:
                    peak_g, peak_ev = peaks[0]["growth"], peaks[0]["ev"]
                else:
                    peak_g = scan_lo
                    peak_ev = self._project_ev(
                        data, profile, scan_lo, wacc, tg, horizon
                    )
                proj_suppressed = False
                try:
                    _p = project_enterprise_value_from_data(
                        data, profile, peak_g, None, wacc, tg, horizon
                    )
                    proj_suppressed = bool(
                        getattr(_p, "terminal_fcf_negative", False)
                        if _p is not None else False
                    )
                except Exception:
                    pass
                if peak_ev < target_ev:
                    # The mechanism behind "EV falls as growth rises" must be
                    # *established*, not assumed: terminal-FCF suppression is
                    # only one of several causes, and the direction itself may
                    # not survive the NWC inference. `direction_undetermined`
                    # was already decided against the sanctioned band above.
                    if direction_undetermined:
                        notes.append(
                            f"模型推算 EV 在 g≈{peak_g:.0%} 处见顶（${peak_ev:,.0f}），"
                            f"低于目标 EV ${target_ev:,.0f}；但 EV 随增长的方向"
                            f"对营运资本假设敏感（在合理区间内既可能上升也可能下降，"
                            f"翻转发生在 NWC 比率 {band_robustness.get('flips_between')} 之间），"
                            f"因此本报告不据此断言「增长毁灭价值」等经济机制——"
                            f"只能说该模型在此参数不确定性下无法解释当前价格"
                        )
                    else:
                        if proj_suppressed:
                            cause = (
                                "终期 FCF ≤ 0、终值被抑制，更高的增长只会放大显式期内的"
                                "负现金流"
                            )
                        else:
                            cause = (
                                "增长所需的再投资（CapEx / 营运资本）超过其自身产生的"
                                "现金流，增长率越高、自由现金流越被侵蚀"
                            )
                        notes.append(
                            f"模型推算 EV 随营收 CAGR 上升而下降，且在 g≈{peak_g:.0%} 处"
                            f"达到最大值 ${peak_ev:,.0f}，仍低于目标 EV ${target_ev:,.0f}："
                            f"{cause}。因此即便取最优增速，本模型的现金流路径也无法"
                            f"解释当前价格——这不是「增长超出上限」，而是该模型不适用于"
                            f"此定价"
                        )
                else:
                    notes.append(
                        f"模型推算 EV 随营收 CAGR 上升而下降（g={lo:.0%} 时 "
                        f"${ev_lo:,.0f} → g={hi:.0%} 时 ${ev_hi:,.0f}）：增长率越高、"
                        f"模型给出的价值越低，目标 EV 落在非单调区间内，"
                        f"无法用单一隐含增速表示"
                    )
                failure = "ev_decreasing_in_growth"
            if meta_out is not None:
                meta_out.update({
                    "solver_method": "brentq (bracketed)",
                    "solver_version": SOLVER_VERSION,
                    "search_bounds": [lo, hi],
                    "ev_at_lo": ev_lo,
                    "ev_at_hi": ev_hi,
                    "ev_direction": "increasing" if increasing else "decreasing",
                    "converged": False,
                    "n_roots_detected": 0,
                    "multiple_roots": False,
                    "failure": failure,
                })
                if not increasing:
                    meta_out["ev_peak_growth"] = peak_g
                    meta_out["ev_peak"] = peak_ev
                    meta_out["ev_peak_below_target"] = peak_ev < target_ev
                    meta_out["terminal_fcf_negative_at_peak"] = proj_suppressed
                    meta_out["ev_direction_undetermined"] = direction_undetermined
                    meta_out["ev_flips_between"] = band_robustness.get(
                        "flips_between"
                    )
                    meta_out["nwc_ratio_used"] = round(nwc_used, 4)
                    meta_out["ev_peak_count"] = len(peaks)
                    meta_out["ev_peaks"] = [
                        {
                            "growth": round(p["growth"], 4),
                            "ev": p["ev"],
                            "at_edge": p["at_edge"],
                        }
                        for p in peaks
                    ]
                    meta_out["peak_search_range"] = [scan_lo, scan_hi]
                    meta_out["growth_value_attribution"] = (
                        self._growth_value_attribution(
                            data, profile, wacc, tg, horizon, scan_lo, scan_hi
                        )
                    )
            if meta_out is not None:
                meta_out["no_root_kind"] = _classify_no_root(
                    failure=failure,
                    direction_undetermined=bool(
                        meta_out.get("ev_direction_undetermined")
                    ),
                    peak_below_target=bool(
                        meta_out.get("ev_peak_below_target")
                    ),
                )
            return None, SolverStatus.NO_SOLUTION_IN_RANGE, notes, None

        try:
            from scipy.optimize import brentq

            def _f(g: float) -> float:
                return self._project_ev(data, profile, g, wacc, tg, horizon) - target_ev

            root = brentq(
                _f, lo, hi, maxiter=self.rcfg.bisection_steps,
                xtol=self.rcfg.newton_tol, full_output=False,
            )
            rev_cagr = float(root[0] if isinstance(root, tuple) else root)
            # ---- Solver residual / convergence check (Session #16) ----------
            # brentq only guarantees the *bracket* narrowed; on a near-flat EV
            # surface it can return a "root" that still misses target EV. Verify
            # the residual and degrade to APPROXIMATE instead of claiming SOLVED.
            residual = abs(_f(rev_cagr))
            proj = project_enterprise_value_from_data(
                data, profile, rev_cagr, None, wacc, tg, horizon
            )
            rel_resid = (residual / abs(target_ev)) if target_ev else 0.0

            # ---- Non-finite residual gate (Session #52, P0-7) ---------------
            # ``nan > tol`` is False, so an overflowing projection (finite
            # inputs, inf/nan EV) used to clear the residual bar and be reported
            # SOLVED with a fabricated CAGR. A non-finite residual proves the
            # projection has no economically meaningful value at the root, so the
            # answer is a data-quality failure - not a solution, and not an
            # "unsolved" either.
            if not math.isfinite(residual) or not math.isfinite(rel_resid):
                notes.append(
                    "模型在求得的增速处推算 EV 溢出为非有限值（inf/nan）："
                    "输入虽为有限数，但投影过程中发生数值溢出，无法给出有意义的估值。"
                    "这不是「无解」，而是数据/数值域问题，需检查营收与利润率量级。"
                )
                if meta_out is not None:
                    meta_out.update({
                        "solver_method": "brentq (bracketed)",
                        "solver_version": SOLVER_VERSION,
                        "search_bounds": [lo, hi],
                        "residual": residual,
                        "relative_residual": rel_resid,
                        "converged": False,
                        "failure": "non_finite_residual",
                    })
                return None, SolverStatus.DATA_QUALITY_ERROR, notes, None

            # ---- Multi-root detection (Session #48) -------------------------
            # A bracketed root find returns *one* root. If the EV curve crosses
            # the target more than once in the search interval, that root is not
            # unique and the "implied growth" is not well defined — the report
            # must say so rather than present one crossing as the answer.
            roots = self._scan_roots(data, profile, target_ev, wacc, tg, horizon, lo, hi)
            multi = len(roots) > 1

            meta = {
                "solver_method": "brentq (bracketed)",
                "solver_version": SOLVER_VERSION,
                "search_bounds": [lo, hi],
                "residual": residual,
                "relative_residual": rel_resid,
                "converged": rel_resid <= self.rcfg.price_residual_tol,
                "n_roots_detected": len(roots),
                "roots": [round(r, 6) for r in roots],
                "multiple_roots": multi,
            }
            if meta_out is not None:
                meta_out.update(meta)
            if multi:
                notes.append(
                    f"⚠️ 搜索区间内检测到 {len(roots)} 个数学根"
                    f"（{', '.join(f'{r:.2%}' for r in roots)}）：EV 曲线非单调，"
                    f"隐含增长不唯一，报告仅呈现其中一个，不应视为确定结论"
                )
            if rel_resid > self.rcfg.price_residual_tol:
                notes.append(
                    f"⚠️ 求解器残差偏高：隐含营收 CAGR {rev_cagr:.2%} 下推算 EV 与目标 EV "
                    f"相差 ${residual:,.0f}（{rel_resid:.2%}），EV 曲面较平坦，结果标记为近似"
                )
                return self._finalize_revenue_cagr(
                    rev_cagr, SolverStatus.APPROXIMATE, notes, proj
                )
            return self._finalize_revenue_cagr(rev_cagr, SolverStatus.SOLVED, notes, proj)
        except Exception:
            pass

        # ---- Bisection fallback: only valid on a re-verified bracket (S#18) ---
        fa, fb = ev_lo - target_ev, ev_hi - target_ev
        # A non-finite bracket is not a bracket. ``nan * anything > 0`` is False,
        # so the sign check below would "pass" and the loop would then walk ``a``
        # to the upper bound (``nan <= 0`` is also False) and report that bound as
        # an approximate root - the same fabrication as P0-7, one layer down.
        if not (math.isfinite(fa) and math.isfinite(fb)):
            notes.append(
                "二分回退中止：区间端点 EV 为非有限值（inf/nan），"
                "投影发生数值溢出，无法在该区间内搜索有意义的隐含增速"
            )
            return None, SolverStatus.DATA_QUALITY_ERROR, notes, None
        if fa * fb > 0:
            notes.append("求解失败：区间无有效 bracket（f(a)·f(b) > 0），拒绝返回可疑 CAGR")
            return None, SolverStatus.NO_SOLUTION_IN_RANGE, notes, None
        a, b = lo, hi
        for _ in range(self.rcfg.bisection_steps):
            mid = (a + b) / 2
            fm = self._project_ev(data, profile, mid, wacc, tg, horizon) - target_ev
            if not math.isfinite(fm):
                notes.append(
                    "二分回退中止：区间内部投影溢出为非有限值（inf/nan），"
                    "搜索无法继续，拒绝返回可疑 CAGR"
                )
                return None, SolverStatus.DATA_QUALITY_ERROR, notes, None
            if fa * fm <= 0:
                b, fb = mid, fm
            else:
                a, fa = mid, fm
        rev_cagr = (a + b) / 2
        proj = project_enterprise_value_from_data(
            data, profile, rev_cagr, None, wacc, tg, horizon
        )
        residual = abs(self._project_ev(data, profile, rev_cagr, wacc, tg, horizon) - target_ev)
        if not math.isfinite(residual):
            notes.append(
                "二分回退结果残差为非有限值（inf/nan）：该增速处的推算 EV 不可用"
            )
            return None, SolverStatus.DATA_QUALITY_ERROR, notes, None
        notes.append(
            f"Bisection fallback used ({self.rcfg.bisection_steps} steps): implied revenue CAGR "
            f"{rev_cagr:.2%}, residual ${residual:,.0f}"
        )
        return self._finalize_revenue_cagr(rev_cagr, SolverStatus.APPROXIMATE, notes, proj)

    @staticmethod
    def _finalize_revenue_cagr(
        rev_cagr: float,
        status: SolverStatus,
        notes: List[str],
        proj: Any,
    ) -> Tuple[Optional[float], SolverStatus, List[str], Any]:
        """Fold the terminal-FCF suppression flag into the reverse-DCF status.

        When the base projection's terminal FCF ≤ 0 the terminal value was
        suppressed, so the implied CAGR is only supported by the *explicit-period*
        cash flows (needs a turnaround assumption) — degrade SOLVED to APPROXIMATE
        instead of presenting it as a complete perpetuity-based solve.

        """
        if proj is not None and getattr(proj, "terminal_fcf_negative", False):
            notes.append(
                "⚠️ 终期 FCF ≤ 0，终值已抑制：隐含营收 CAGR 仅由显式期现金流支撑"
                "（需明确转型 turnaround 假设），非正常永续经营价值"
            )
            if status == SolverStatus.SOLVED:
                status = SolverStatus.APPROXIMATE
        return rev_cagr, status, notes, proj

    def _fcf_base_quality(
        self, ttm: Any, base_fcf: Optional[float]
    ) -> Optional[dict]:
        """Flag an FCF base that cannot support a growth interpretation.

        A reverse DCF asks "what growth justifies this price", which presupposes
        the base FCF is a representative steady-state cash flow. Two failure
        modes break that premise and must be disclosed rather than absorbed into
        an implausible implied growth:

        1. **Negative base FCF** — the price is then being justified off a
           negative cash flow, so *any* implied growth is an artefact of the
           explicit-period path, not a growth requirement. Heavy-capex utilities
           in a build-out year (DUK: TTM FCF −$5.2B, CapEx = 145% of OCF) are the
           canonical case: 48.7% "implied growth" is a capex artefact, not a
           growth expectation.
        2. **CapEx consuming most of OCF** — the FCF base is dominated by a
           single year's reinvestment intensity; the same company one year later
           can show a completely different FCF base and hence a different
           implied growth, which is a data-stability problem, not information.

        Returns ``None`` when the base looks usable.
        """
        ocf = getattr(ttm, "operating_cash_flow", None) if ttm is not None else None
        capex = getattr(ttm, "capex", None) if ttm is not None else None
        capex_ratio = None
        if ocf and capex and ocf > 0:
            capex_ratio = abs(float(capex)) / float(ocf)

        if base_fcf is not None and float(base_fcf) <= 0:
            return {
                "reason": "negative_base_fcf",
                "base_fcf": float(base_fcf),
                "operating_cash_flow": (float(ocf) if ocf is not None else None),
                "capex": (float(capex) if capex is not None else None),
                "capex_to_ocf": capex_ratio,
                "note": (
                    f"⚠️ 基准 FCF 为负（${float(base_fcf)/1e9:,.2f}B）：价格无法由"
                    f"负现金流解释，隐含增长仅反映显式期路径，不应解读为增长预期"
                ),
            }
        if capex_ratio is not None and capex_ratio >= 1.0:
            return {
                "reason": "capex_exceeds_ocf",
                "base_fcf": (float(base_fcf) if base_fcf is not None else None),
                "operating_cash_flow": float(ocf),
                "capex": float(capex),
                "capex_to_ocf": capex_ratio,
                "note": (
                    f"⚠️ CapEx 达经营现金流的 {capex_ratio:.0%}：单年重资本开支严重"
                    f"扭曲 FCF 基数，隐含增长对资本开支假设高度敏感"
                ),
            }
        if capex_ratio is not None and capex_ratio >= 0.70:
            return {
                "reason": "heavy_capex",
                "base_fcf": (float(base_fcf) if base_fcf is not None else None),
                "operating_cash_flow": float(ocf),
                "capex": float(capex),
                "capex_to_ocf": capex_ratio,
                "note": (
                    f"注：CapEx 达经营现金流的 {capex_ratio:.0%}，FCF 基数对"
                    f"再投资强度敏感，隐含增长应结合资本开支周期解读"
                ),
            }
        return None

    def _scan_roots(
        self,
        data: FinancialData,
        profile: Any,
        target_ev: float,
        wacc: float,
        tg: float,
        horizon: int,
        lo: float,
        hi: float,
        steps: int = 40,
    ) -> List[float]:
        """Detect *all* sign changes of (EV − target) on a coarse grid, then
        refine each bracket with brentq.

        This is a diagnostic layer, not the solve: the reported answer still
        comes from the primary bracketed solve, but if the curve crosses the
        target more than once the "implied growth" is not unique and callers
        must say so. Grid density only affects *detection*, never the root
        values (each is refined to brentq tolerance).
        """
        roots: List[float] = []
        step = (hi - lo) / max(steps, 1)
        prev_g = lo
        try:
            prev_f = self._project_ev(data, profile, prev_g, wacc, tg, horizon) - target_ev
        except Exception:
            return roots
        for i in range(1, steps + 1):
            g = lo + step * i
            try:
                f = self._project_ev(data, profile, g, wacc, tg, horizon) - target_ev
            except Exception:
                prev_g, prev_f = g, None
                continue
            if prev_f is not None and prev_f * f <= 0:
                try:
                    from scipy.optimize import brentq
                    r = brentq(
                        lambda x: self._project_ev(data, profile, x, wacc, tg, horizon) - target_ev,
                        prev_g, g, maxiter=self.rcfg.bisection_steps,
                        xtol=self.rcfg.newton_tol,
                    )
                    roots.append(float(r))
                except Exception:
                    pass
            prev_g, prev_f = g, f
        # De-duplicate roots that landed on the same grid boundary.
        uniq: List[float] = []
        for r in roots:
            if not any(abs(r - u) < 1e-4 for u in uniq):
                uniq.append(r)
        return uniq

    # ------------------------------------------------------------------
    # Phase 2 (Session #17): constraint-based implied solver
    # ------------------------------------------------------------------
    def _bridge_inputs(
        self, data: FinancialData, profile: Any, horizon: int
    ) -> Tuple[float, float, float, float, float]:
        """Extract the fixed FCF-bridge inputs (hist margin, D&A, CapEx, NWC, tax)."""
        from forecasts.forecast import ForecastEngine
        from forecasts.nwc_utils import business_type_from_profile

        eng = ForecastEngine(
            horizon_years=horizon,
            business_type=business_type_from_profile(profile),
        )
        _, _, hist_om, da_ratio, capex_ratio, nwc_ratio, tax_rate = eng._extract_history(data)
        return hist_om, da_ratio, capex_ratio, nwc_ratio, tax_rate

    @staticmethod
    def _root_brackets(
        xs: List[float], fs: List[float], target: float
    ) -> List[Tuple[float, float]]:
        """Contiguous sample intervals where ``f - target`` changes sign.

        Adjacent sign-changing intervals are merged so a sample landing exactly on
        the target is not double-counted as two distinct roots.
        """
        brackets: List[Tuple[float, float]] = []
        i = 0
        n = len(xs)
        while i < n - 1:
            if (fs[i] - target) * (fs[i + 1] - target) <= 0:
                a, b = xs[i], xs[i + 1]
                j = i + 1
                while j < n - 1 and (fs[j] - target) * (fs[j + 1] - target) <= 0:
                    b = xs[j + 1]
                    j += 1
                brackets.append((a, b))
                i = j
            else:
                i += 1
        return brackets

    def _finish_root(
        self,
        objective: Callable[[float], float],
        target: float,
        a: float,
        b: float,
        name: str,
        bound_lo: float,
        bound_hi: float,
        abs_tol: float,
        extra_note: Optional[str] = None,
    ) -> ImpliedSolve:
        """Solve inside a *verified* bracket ``[a, b]`` and check the residual."""

        def _h(x: float) -> float:
            return float(objective(x)) - target

        try:
            ha, hb = _h(a), _h(b)
        except Exception as e:
            return ImpliedSolve(
                None, SolverStatus.INFEASIBLE.value, bound_lo=bound_lo, bound_hi=bound_hi,
                note=f"{name} 求解失败：{e}",
            )

        if abs(ha) <= abs_tol:
            root, status = a, SolverStatus.SOLVED.value
        elif abs(hb) <= abs_tol:
            root, status = b, SolverStatus.SOLVED.value
        else:
            try:
                from scipy.optimize import brentq

                root_result = brentq(
                    _h, a, b, maxiter=self.rcfg.bisection_steps, xtol=self.rcfg.newton_tol
                )
                root = float(
                    root_result[0] if isinstance(root_result, tuple) else root_result
                )
                status = SolverStatus.SOLVED.value
            except Exception:
                # Bisection is only safe on a *valid* bracket — refuse to return a
                # plausible-looking root when f(a)·f(b) > 0 (Session #18, P0).
                if ha * hb > 0:
                    return ImpliedSolve(
                        None, SolverStatus.NO_SOLUTION_IN_RANGE.value,
                        bound_lo=bound_lo, bound_hi=bound_hi,
                        note=f"{name} 求解失败：区间无有效 bracket（f(a)·f(b) > 0），拒绝返回可疑根",
                    )
                x0, x1, h_x0 = a, b, ha
                for _ in range(self.rcfg.bisection_steps):
                    mid = (x0 + x1) / 2
                    h_mid = _h(mid)
                    if h_x0 * h_mid <= 0:
                        x1 = mid
                    else:
                        x0, h_x0 = mid, h_mid
                root = (x0 + x1) / 2
                status = SolverStatus.APPROXIMATE.value

        residual = abs(_h(root))
        rel = residual / abs(target) if target else 0.0
        prefix = f"{extra_note}；" if extra_note else ""
        if rel > self.rcfg.implied_residual_tol:
            return ImpliedSolve(
                root, SolverStatus.APPROXIMATE.value, residual, rel, bound_lo, bound_hi,
                note=(prefix + f"⚠️ {name} 求解残差偏高（${residual:,.0f}，{rel:.2%}），"
                      "EV 曲面较平坦，结果标记为近似"),
            )
        return ImpliedSolve(root, status, residual, rel, bound_lo, bound_hi, note=extra_note or None)

    def _solve_implied_scalar(
        self,
        objective: Callable[[float], float],
        target: float,
        lo: float,
        hi: float,
        increasing: bool,
        name: str,
    ) -> ImpliedSolve:
        """Find x in [lo, hi] with ``objective(x) == target`` under a monotonicity
        constraint (``increasing`` = objective rises with x).

        Hard constraints (Session #18):
          * the interval is *sampled* to validate the declared monotonicity — a
            non-monotonic surface is scanned for root brackets (0 → no solution,
            1 → solve, >1 → MULTIPLE_ROOTS) rather than trusting a single root;
          * a flat objective (no sensitivity) is reported as FLAT_OBJECTIVE and
            never returned as a "solution";
          * a target outside the reachable range returns NO_SOLUTION_IN_RANGE and
            names the binding bound — it is never clamped to the edge;
          * the bisection fallback only runs on a re-verified bracket (a failed
            brentq with f(a)·f(b) > 0 returns NO_SOLUTION_IN_RANGE, not a root);
          * a root whose residual exceeds ``implied_residual_tol`` degrades to
            APPROXIMATE instead of claiming SOLVED.
        """
        try:
            f_lo = float(objective(lo))
            f_hi = float(objective(hi))
        except Exception as e:
            return ImpliedSolve(
                None, SolverStatus.INFEASIBLE.value, bound_lo=lo, bound_hi=hi,
                note=f"{name} 求解失败：{e}",
            )

        tol = self.rcfg.implied_residual_tol
        span = max(abs(f_hi), abs(f_lo), abs(target), 1.0)
        abs_tol = tol * span

        # ---- 1) sample the interval to validate monotonicity ----------------
        n = max(3, int(self.rcfg.implied_monotonic_samples))
        xs = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
        try:
            fs = [float(objective(x)) for x in xs]
        except Exception as e:
            return ImpliedSolve(
                None, SolverStatus.INFEASIBLE.value, bound_lo=lo, bound_hi=hi,
                note=f"{name} 区间采样失败：{e}",
            )

        fmin, fmax = min(fs), max(fs)

        # (a) flat objective → the input has no leverage on EV; refuse a value.
        if (fmax - fmin) <= abs_tol:
            if abs(fs[n // 2] - target) <= abs_tol:
                return ImpliedSolve(
                    None, SolverStatus.FLAT_OBJECTIVE.value, bound_lo=lo, bound_hi=hi,
                    note=f"{name} 在约束区间内对 EV 无敏感度（近似常数），无法唯一确定隐含值",
                )
            return ImpliedSolve(
                None, SolverStatus.NO_SOLUTION_IN_RANGE.value, bound_lo=lo, bound_hi=hi,
                note=f"{name} 在约束区间内对 EV 无敏感度，且与目标不符（目标超出约束区间）",
            )

        diffs = [fs[i + 1] - fs[i] for i in range(n - 1)]
        # Monotonicity uses a *step-scale* tolerance, not the residual tolerance:
        # the latter is scaled by |target| and would flag a genuinely monotone
        # surface as flat/non-monotonic when the step is comparable to it.
        f_span = max(1.0, abs(fmax), abs(fmin))
        mono_tol = 1e-6 * f_span
        going_up = all(d >= -mono_tol for d in diffs)
        going_down = all(d <= mono_tol for d in diffs)

        # (b) ill-conditioned: neither direction dominates at sample resolution.
        if going_up and going_down:
            return ImpliedSolve(
                None, SolverStatus.NON_MONOTONIC.value, bound_lo=lo, bound_hi=hi,
                note=f"{name} 目标函数在约束区间内近似平坦（步长级噪声），单调性不可判定，拒绝输出隐含值",
            )

        # (c) non-monotonic → scan for root brackets.
        if not (going_up or going_down):
            brackets = self._root_brackets(xs, fs, target)
            if not brackets:
                return ImpliedSolve(
                    None, SolverStatus.NO_SOLUTION_IN_RANGE.value, bound_lo=lo, bound_hi=hi,
                    note=f"{name} 目标函数非单调且在约束区间内无根（目标超出可达范围）",
                )
            if len(brackets) > 1:
                return ImpliedSolve(
                    None, SolverStatus.MULTIPLE_ROOTS.value, bound_lo=lo, bound_hi=hi,
                    note=(f"{name} 目标函数非单调且区间内存在 {len(brackets)} 个根 → 多解，"
                          "拒绝输出单一隐含值"),
                )
            a, b = brackets[0]
            return self._finish_root(objective, target, a, b, name, lo, hi, abs_tol)

        # ---- 2) monotone: reachability from the sampled extrema --------------
        # ``lo_val``/``hi_val`` are the *reachable range* of the objective
        # (independent of direction); ``x_at_max``/``x_at_min`` locate the ends.
        detected_increasing = going_up
        lo_val, hi_val = fmin, fmax
        if detected_increasing:
            x_at_max, x_at_min = hi, lo
        else:
            x_at_max, x_at_min = lo, hi

        if target > hi_val + abs_tol:
            return ImpliedSolve(
                None, SolverStatus.NO_SOLUTION_IN_RANGE.value, bound_lo=lo, bound_hi=hi,
                note=(f"即便 {name}={x_at_max:.2%}，推算 EV ${hi_val:,.0f} 仍低于目标 "
                      f"${target:,.0f}（目标超出约束上界）"),
            )
        if target < lo_val - abs_tol:
            return ImpliedSolve(
                None, SolverStatus.NO_SOLUTION_IN_RANGE.value, bound_lo=lo, bound_hi=hi,
                note=(f"{name}={x_at_min:.2%} 时推算 EV ${lo_val:,.0f} 已高于目标 "
                      f"${target:,.0f}（目标低于约束下界）"),
            )

        extra_note = None
        if detected_increasing != increasing:
            extra_note = (f"注：实测目标函数方向为{'递增' if detected_increasing else '递减'}，"
                          f"与声明的 {'递增' if increasing else '递减'} 不一致（已按实测方向求解）")
        return self._finish_root(objective, target, lo, hi, name, lo, hi, abs_tol, extra_note)

    def _implied_expectations(
        self,
        data: FinancialData,
        profile: Any,
        target_ev: float,
        wacc: float,
        tg: float,
        horizon: int,
        base_revenue_cagr: float,
        risk_free_rate: Optional[float] = None,
    ) -> dict:
        """One-at-a-time implied solves for margin / FCF margin / WACC / terminal growth.

        Every solve holds all other inputs at the base case (revenue CAGR solved
        first, then the historical margin / D&A / CapEx / NWC / tax from the FCF
        bridge). Each number answers: "if nothing else changed, what would this
        single assumption have to be to justify today's price?"
        """
        out: dict = {
            "method": "one_at_a_time",
            "horizon": horizon,
            "base_assumptions": {
                "revenue_cagr": base_revenue_cagr,
                "wacc": wacc,
                "terminal_growth": tg,
            },
            # The revenue/margin path every implied solve is projected along.
            # Exposed so a caller can re-run the same projection and verify the
            # implied value reproduces the target EV (round-trip auditability).
            "path_shape": None,
            "note": (
                "单变量隐含解（其余假设固定为基准），非联合求解：回答「若其它条件不变，"
                "当前价隐含的 X 是多少」。"
            ),
        }
        ttm = data.ttm
        if ttm is None or ttm.revenue is None or ttm.revenue <= 0:
            out["note"] = "无 TTM 营收，无法求解隐含值"
            return out

        base_rev = ttm.revenue
        try:
            hist_om, da_ratio, capex_ratio, nwc_ratio, tax_rate = self._bridge_inputs(
                data, profile, horizon
            )
        except Exception as e:
            log.info("implied-expectations bridge extraction failed: %s", e)
            out["note"] = f"FCF 桥接输入缺失：{e}"
            return out

        # Shape every implied solve onto the forward DCF's own revenue/margin
        # path. Solving the one-at-a-time drivers on a flat-CAGR surface would
        # hold growth at ``base_revenue_cagr`` but project a *different* FCF
        # path than the DCF, so the implied margin / WACC / terminal growth
        # would not reconcile with the DCF's own base case.
        shape_rev = None
        margin_offsets = None
        try:
            path_in = dcf_path_inputs_from_data(data, profile, horizon)
            if path_in is not None:
                _, shape_rev, margin_offsets, om_center = dcf_projection_shape(
                    path_in.base_revenue, path_in.base_growth, path_in.base_margin, horizon
                )
                hist_om = om_center
        except Exception as e:
            log.info("implied-expectations path shape unavailable: %s", e)
            shape_rev = None
            margin_offsets = None
        out["base_assumptions"]["operating_margin"] = hist_om
        out["path_shape"] = {
            "growth_shape": shape_rev,
            "margin_offsets": margin_offsets,
        }

        def _ev_bridge(g: float, om: float, w: float, tgr: float) -> float:
            p = project_enterprise_value_shaped(
                base_rev, g, om, tax_rate, da_ratio, capex_ratio, nwc_ratio, w, tgr,
                horizon, growth_shape=shape_rev, margin_offsets=margin_offsets,
            )
            return p.enterprise_value

        # Terminal-value suppression of the *base* projection (Session #18): when
        # the terminal FCF ≤ 0 the TV is suppressed, so every implied value below
        # is only supported by explicit-period cash flows.
        base_proj = project_enterprise_value_from_data(
            data, profile, base_revenue_cagr, None, wacc, tg, horizon
        )
        base_tv_suppressed = bool(
            base_proj is not None and getattr(base_proj, "terminal_fcf_negative", False)
        )
        out["terminal_fcf_negative"] = base_tv_suppressed
        if base_tv_suppressed:
            out["note"] = (
                out["note"]
                + " ⚠️ 基准投影终期 FCF ≤ 0，终值已抑制：隐含值基于显式期现金流（需转型假设）。"
            )

        # 1) Implied operating margin (hold g, wacc, tg).
        out["implied_operating_margin"] = self._solve_implied_scalar(
            lambda om: _ev_bridge(base_revenue_cagr, om, wacc, tg),
            target_ev, self.rcfg.implied_margin_lo, self.rcfg.implied_margin_hi,
            increasing=True, name="营业利润率",
        )

        # 2) Implied FCF margin (flat-margin bridge; hold g, wacc, tg).
        out["implied_fcf_margin"] = self._solve_implied_scalar(
            lambda fm: project_enterprise_value_flat_margin(
                base_rev, base_revenue_cagr, fm, wacc, tg, horizon,
                growth_shape=shape_rev,
            ).enterprise_value,
            target_ev, self.rcfg.implied_fcf_margin_lo, self.rcfg.implied_fcf_margin_hi,
            increasing=True, name="FCF 利润率",
        )

        # 3) Implied WACC (hold g, margin, tg). Constraint: WACC > tg + spread,
        #    and WACC ≥ Rf. A going-concern discount rate below the risk-free rate
        #    is economically incoherent (negative risk premium), so if the target
        #    EV cannot be reached even at Rf the solver reports NO_SOLUTION_IN_RANGE
        #    naming that floor — it never emits a sub-Rf point estimate.
        wacc_lo = max(self.rcfg.implied_wacc_lo, tg + MIN_WACC_TG_SPREAD)
        if risk_free_rate is not None and risk_free_rate > 0:
            wacc_lo = max(wacc_lo, risk_free_rate)
        out["implied_wacc_floor_rf"] = risk_free_rate
        out["implied_wacc"] = self._solve_implied_scalar(
            lambda w: _ev_bridge(base_revenue_cagr, hist_om, w, tg),
            target_ev, wacc_lo, self.rcfg.implied_wacc_hi,
            increasing=False, name="折现率(WACC)",
        )

        # 4) Implied terminal growth (hold g, margin, wacc). Constraint: tg < wacc - spread.
        tg_lo = self.rcfg.implied_tg_lo
        tg_hi = min(self.rcfg.implied_tg_hi, wacc - MIN_WACC_TG_SPREAD)
        if tg_hi <= tg_lo:
            out["implied_terminal_growth"] = ImpliedSolve(
                None, SolverStatus.INFEASIBLE.value, bound_lo=tg_lo, bound_hi=tg_hi,
                note="WACC 过低，终值增长率可行区间为空",
            )
        else:
            out["implied_terminal_growth"] = self._solve_implied_scalar(
                lambda g: _ev_bridge(base_revenue_cagr, hist_om, wacc, g),
                target_ev, tg_lo, tg_hi, increasing=True, name="终值增长率",
            )

        # The growth anchor above is the *solved* implied CAGR, i.e. a path that
        # already reproduces the target EV. Solving WACC or g along that same
        # path therefore returns its own base value — a tautology, not a market
        # expectation (KR reported implied WACC 9.327% against a base 9.327%).
        # Flag those so the renderer can say "当前增速已足以解释股价" instead of
        # printing the base number back as if it were an independent finding.
        for _key, _base in (
            ("implied_wacc", wacc),
            ("implied_terminal_growth", tg),
        ):
            _s = out.get(_key)
            _v = getattr(_s, "value", None)
            if _v is not None and _base is not None and abs(_v - _base) <= max(
                1e-4, abs(_base) * 1e-3
            ):
                out[f"{_key}_degenerate"] = True
        return out

    def _normalized_growth_solve(
        self,
        data: FinancialData,
        profile: Any,
        target_ev: float,
        wacc: float,
        tg: float,
        horizon: int,
        cagr_hi: float = 3.00,
        cagr_lo: Optional[float] = None,
        margin_norm: float = 0.20,
        capex_norm: float = 0.15,
    ) -> Optional[dict]:
        """Re-solve implied growth under *normalized* mature economics.

        Fixes a steady-state operating margin and a normalized capex/revenue
        ratio (mature compute-infra profile) and searches the revenue CAGR that
        reproduces the target EV. Turns a meaningless negative-EV "no solution"
        into an interpretable "what would have to be true" statement.

        ``cagr_lo`` / ``cagr_hi`` bound the search to the business type's
        sanctioned growth band so a surfaced "market-implied" CAGR can never sit
        outside the range the raw solver would accept.
        """
        ttm = data.ttm
        base_revenue = ttm.revenue if ttm is not None else None
        if base_revenue is None or base_revenue <= 0:
            return None
        try:
            from forecasts.forecast import ForecastEngine
            from forecasts.fcf_projection import project_enterprise_value
            from forecasts.nwc_utils import business_type_from_profile

            eng = ForecastEngine(
                horizon_years=horizon,
                business_type=business_type_from_profile(profile),
            )
            _, _, _hist_om, da_ratio, _capex_ratio, nwc_ratio, tax_rate = eng._extract_history(data)

            def _ev(g: float) -> float:
                p = project_enterprise_value(
                    base_revenue, g, margin_norm, tax_rate, da_ratio,
                    capex_norm, nwc_ratio, wacc, tg, horizon,
                )
                return p.enterprise_value if p is not None else 0.0

            _candidates = [0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 0.75, 1.00, 1.50, 2.00, cagr_hi]
            grid = [g for g in _candidates if g <= cagr_hi + 1e-9]
            if cagr_lo is not None and cagr_lo > grid[0]:
                grid = [cagr_lo] + [g for g in grid if g > cagr_lo]
            # Scan only the projection's *valid domain*. Past it the FCF bridge
            # breaks down (working-capital drag plus a suppressed terminal value
            # can drive EV to absurd values — e.g. −7.7e15 at a 300% CAGR), which
            # used to be reported in the diagnostic note as if it were an
            # estimate. A well-behaved projection is monotone non-decreasing in
            # growth until it reaches the target, so stop at the first break.
            pts: List[Tuple[float, float]] = []
            prev_ev: Optional[float] = None
            for g in grid:
                ev = _ev(g)
                if ev is None or not math.isfinite(ev):
                    break
                if prev_ev is not None and ev < prev_ev:
                    break
                pts.append((g, float(ev)))
                prev_ev = ev
            if not pts:
                return None
            g_peak, ev_at_hi = max(pts, key=lambda p: p[1])
            bracket = None
            for (g0, e0), (g1, e1) in zip(pts, pts[1:]):
                if (e0 - target_ev) * (e1 - target_ev) <= 0:
                    bracket = (g0, g1)
                    break
            if bracket is None:
                return {
                    "assumptions": {"operating_margin": margin_norm, "capex_ratio": capex_norm},
                    "implied_revenue_cagr": None,
                    "cagr_hi": g_peak,
                    "ev_at_hi": ev_at_hi,
                }
            lo_b, hi_b = bracket
            for _ in range(80):
                mid = (lo_b + hi_b) / 2
                if (_ev(lo_b) - target_ev) * (_ev(mid) - target_ev) <= 0:
                    hi_b = mid
                else:
                    lo_b = mid
            return {
                "assumptions": {"operating_margin": margin_norm, "capex_ratio": capex_norm},
                "implied_revenue_cagr": (lo_b + hi_b) / 2,
                "cagr_hi": g_peak,
                "ev_at_hi": ev_at_hi,
            }
        except Exception as e:
            log.info("normalized growth solve failed: %s", e)
            return None


__all__ = ["ReverseDCFModel"]
