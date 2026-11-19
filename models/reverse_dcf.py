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
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from config import (
    DEFAULT_DCF_CONFIG,
    DEFAULT_REVERSE_DCF_CONFIG,
    ModelName,
    ReverseDCFConfig,
    SolverStatus,
    get_logger,
    get_reverse_dcf_config,
    resolve_forecast_horizon,
)
from data.fcf_utils import resolve_ttm_fcf, resolve_ttm_fcf_normalized
from data.models import FinancialData
from forecasts.fcf_projection import (
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


class ReverseDCFModel(ValuationModel):
    NAME = ModelName.REVERSE_DCF

    def __init__(
        self,
        dcf_config=None,
        reverse_config: ReverseDCFConfig = DEFAULT_REVERSE_DCF_CONFIG,
        horizon: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.dcfg = dcf_config or DEFAULT_DCF_CONFIG
        self.rcfg = reverse_config
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
        if price is None or price <= 0 or shares is None or shares <= 0:
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
        bt_params = get_reverse_dcf_config(bt_str)

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
            ValuationAssumption("Solver Method", "Bisection + Brent", "",
                                "Revenue CAGR on the forward DCF's own FCF path"),
            ValuationAssumption("CAGR Range",
                                f"{rev_cfg_min:.0%} to {rev_cfg_max:.0%}",
                                "", f"Per-type for {bt_str}"),
            ValuationAssumption("Forecast Horizon", str(horizon), "years",
                                "Default" if horizon_is_default else f"Per-type for {bt_str}"),
        ]

        rev_cagr, status, notes, proj = self._solve_revenue_cagr(
            data, profile, target_ev, wacc, tg, horizon=horizon,
            cagr_lo=rev_cfg_min, cagr_hi=rev_cfg_max,
        )
        if tg_divergence is not None:
            notes.append(
                f"注：{bt_str} 类型的终值增长率参考值 {float(tg_per_type):.2%} 与前瞻 DCF "
                f"实际使用的 {tg:.2%} 不一致；反向求解已统一采用 DCF 值，"
                f"以保证「隐含增长」与 DCF 基准可比"
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
        }

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
            binding = "above_band_ceiling" if ev_at_ceiling < target_ev else "below_band_floor"
            breakdown["implied_revenue_cagr_binding"] = binding
            # Structured bound (Session #31): the market price sits outside what
            # the sanctioned growth band can justify. Surface this as a *bound*
            # (≥ ceiling / ≤ floor) with the EV it implies — never as a
            # fabricated point estimate. Downstream can state "growth alone
            # cannot explain the price" without inventing a number.
            bound_value = rev_cfg_max if binding == "above_band_ceiling" else rev_cfg_min
            bound_ev = ev_at_ceiling if binding == "above_band_ceiling" else ev_at_floor
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
            bridge_broken = base_fcf <= 0 or bool(breakdown.get("terminal_fcf_negative"))
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

        if rev_cagr is None:
            return ValuationResult(
                model_name=self.model_name,
                status=status,
                notes=notes,
                assumptions=assumptions,
                breakdown=breakdown,
                data_quality_score=data.quality.data_quality_score,
            )

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
    ) -> float:
        proj = project_enterprise_value_from_data(
            data, profile, rev_cagr, None, wacc, tg, horizon
        )
        if proj is None:
            return 0.0
        return proj.enterprise_value

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
    ) -> Tuple[Optional[float], SolverStatus, List[str], Any]:
        notes: List[str] = []
        lo = cagr_lo if cagr_lo is not None else self.rcfg.min_implied_cagr
        hi = cagr_hi if cagr_hi is not None else self.rcfg.max_implied_cagr
        try:
            ev_lo = self._project_ev(data, profile, lo, wacc, tg, horizon)
            ev_hi = self._project_ev(data, profile, hi, wacc, tg, horizon)
        except Exception as e:
            return None, SolverStatus.INFEASIBLE, [f"Projection error: {e}"], None

        abs_tol = 1e-3 * max(abs(target_ev), 1.0)

        # Endpoint equality is itself a solution (boundary root) — do not reject it.
        if abs(ev_lo - target_ev) <= abs_tol:
            proj = project_enterprise_value_from_data(data, profile, lo, None, wacc, tg, horizon)
            return self._finalize_revenue_cagr(lo, SolverStatus.SOLVED, notes, proj)
        if abs(ev_hi - target_ev) <= abs_tol:
            proj = project_enterprise_value_from_data(data, profile, hi, None, wacc, tg, horizon)
            return self._finalize_revenue_cagr(hi, SolverStatus.SOLVED, notes, proj)

        if (ev_lo - target_ev) * (ev_hi - target_ev) > 0:
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
            else:
                notes.append(
                    f"在 {lo:.0%} 营收 CAGR 下限时推算 EV ${ev_lo:,.0f} 已高于目标 "
                    f"${target_ev:,.0f}（市场隐含增长低于模型下限）"
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
            if rel_resid > 1e-3:
                notes.append(
                    f"⚠️ 求解器残差偏高：隐含营收 CAGR {rev_cagr:.2%} 下推算 EV 与目标 EV "
                    f"相差 ${residual:,.0f}（{rel_resid:.2%}），EV 曲面较平坦，结果标记为近似"
                )
                return self._finalize_revenue_cagr(rev_cagr, SolverStatus.APPROXIMATE, notes, proj)
            return self._finalize_revenue_cagr(rev_cagr, SolverStatus.SOLVED, notes, proj)
        except Exception:
            pass

        # ---- Bisection fallback: only valid on a re-verified bracket (S#18) ---
        fa, fb = ev_lo - target_ev, ev_hi - target_ev
        if fa * fb > 0:
            notes.append("求解失败：区间无有效 bracket（f(a)·f(b) > 0），拒绝返回可疑 CAGR")
            return None, SolverStatus.NO_SOLUTION_IN_RANGE, notes, None
        a, b = lo, hi
        for _ in range(self.rcfg.bisection_steps):
            mid = (a + b) / 2
            fm = self._project_ev(data, profile, mid, wacc, tg, horizon) - target_ev
            if fa * fm <= 0:
                b, fb = mid, fm
            else:
                a, fa = mid, fm
        rev_cagr = (a + b) / 2
        proj = project_enterprise_value_from_data(
            data, profile, rev_cagr, None, wacc, tg, horizon
        )
        residual = abs(self._project_ev(data, profile, rev_cagr, wacc, tg, horizon) - target_ev)
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
