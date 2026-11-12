"""
models/reverse_dcf.py - Reverse DCF Solver
Solves for implied revenue CAGR (and derived FCF CAGR) using the same FCF bridge as forward DCF.

Phase 2 (Session #17) adds a *constraint-based implied solver*: in addition to the
Revenue CAGR, it one-at-a-time inverts four more inputs (operating margin, FCF
margin, WACC, terminal growth) so the report can state the market-implied value
of each while holding every other assumption at its base case.
"""
from __future__ import annotations

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
from data.fcf_utils import resolve_ttm_fcf
from data.models import FinancialData
from forecasts.fcf_projection import (
    MIN_WACC_TG_SPREAD,
    fcf_cagr_from_projection,
    project_enterprise_value,
    project_enterprise_value_flat_margin,
    project_enterprise_value_from_data,
)
from models.base import ValuationAssumption, ValuationModel, ValuationResult
from models.dcf import DCFModel
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
        price = data.market.current_price
        shares = ttm.shares_outstanding
        net_debt = data.market.net_debt_or_zero()
        target_equity = price * shares
        target_ev = target_equity + net_debt

        base_fcf, fcf_source = resolve_ttm_fcf(ttm)
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

        # ---- BusinessType-specific reverse DCF overrides ----
        bt_str = getattr(profile, "business_type", "Unknown") if profile else "Unknown"
        bt_params = get_reverse_dcf_config(bt_str)

        # Override terminal growth if the per-type config specifies one
        tg_override = bt_params.get("terminal_growth")
        if tg_override is not None:
            tg = tg_override

        # Projection window: resolved per call from the profile so it can never
        # leak between tickers via the shared singleton (Session #16).
        horizon = self._resolve_horizon(profile)
        horizon_is_default = bt_params.get("horizon") is None

        # Create a per-call reverse config override
        rev_cfg_min = bt_params.get("min_implied_cagr", self.rcfg.min_implied_cagr)
        rev_cfg_max = bt_params.get("max_implied_cagr", self.rcfg.max_implied_cagr)

        assumptions = [
            ValuationAssumption("Target Price", price, "$/share", "Current market"),
            ValuationAssumption("WACC", round(wacc, 4), "%", "As per DCF"),
            ValuationAssumption("Terminal Growth", round(tg, 4), "%",
                                f"{'Per-type override' if tg_override is not None else tvg.source} "
                                f"({bt_str})"),
            ValuationAssumption(
                "Base FCF (TTM)", base_fcf, "", f"Reference ({fcf_source})"
            ),
            ValuationAssumption("Solver Method", "Bisection + Brent", "", "Revenue CAGR on FCF bridge"),
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
        }

        # ---- Normalized-economics diagnostic (Session #07) ------------------
        # For deeply FCF-negative, capital-intensive names (capex > revenue) the
        # FCF bridge yields a *negative* EV, so "no solution in range" with a
        # negative EV is meaningless. Re-solve under a normalized mature-economics
        # profile (steady-state margin + normalized capex) and report the implied
        # minimum growth — a positive, interpretable statement.
        if rev_cagr is None:
            normalized = self._normalized_growth_solve(
                data, profile, target_ev, wacc, tg, horizon=horizon
            )
            if normalized is not None:
                breakdown["normalized_growth_solve"] = normalized
                a = normalized.get("assumptions", {})
                if normalized.get("implied_revenue_cagr") is not None:
                    # Surface the normalized-economics derivation into the STRUCTURED
                    # implied field — otherwise the "市场隐含预期" block renders N/A
                    # while the value only exists in free-text notes (Round-3 defect:
                    # note said ≈26% but the field said N/A).
                    breakdown["implied_revenue_cagr"] = normalized["implied_revenue_cagr"]
                    breakdown["implied_revenue_cagr_source"] = "normalized_growth_solve"
                    notes.append(
                        f"隐含量化（按成熟稳态假设：营业利润率 {a.get('operating_margin', 0):.0%}、"
                        f"capex/营收 {a.get('capex_ratio', 0):.0%}）：当前价隐含营收 CAGR "
                        f"≈ {normalized['implied_revenue_cagr']:.0%}"
                    )
                else:
                    notes.append(
                        f"即使在成熟稳态假设下（营业利润率 {a.get('operating_margin', 0):.0%}、"
                        f"capex/营收 {a.get('capex_ratio', 0):.0%}）营收增长至 {normalized.get('cagr_hi', 0):.0%}，"
                        f"推算 EV {normalized.get('ev_at_hi', 0):,.0f} 仍低于目标 EV {target_ev:,.0f}，"
                        "说明当前价隐含的增长/盈利假设已超出模型可解范围"
                    )

        # ---- Phase 2: constraint-based implied expectations (Session #17) ----
        # One-at-a-time inverse solves for the *other* value drivers, holding the
        # solved revenue CAGR as the base case. Uses the normalized-solve CAGR
        # when the raw bridge had no solution (deeply FCF-negative names).
        base_cagr_for_implied = rev_cagr
        if base_cagr_for_implied is None:
            base_cagr_for_implied = breakdown.get("implied_revenue_cagr")
        if base_cagr_for_implied is not None:
            try:
                breakdown["implied_expectations"] = self._implied_expectations(
                    data, profile, target_ev, wacc, tg, horizon, base_cagr_for_implied
                )
            except Exception as e:  # never let a diagnostic solve break the model
                log.info("implied expectations solve skipped: %s", e)

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

        if not ((ev_lo - target_ev) * (ev_hi - target_ev) < 0):
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

        proj = None
        try:
            from scipy.optimize import brentq

            def _f(g: float) -> float:
                return self._project_ev(data, profile, g, wacc, tg, horizon) - target_ev

            rev_cagr = brentq(_f, lo, hi, maxiter=self.rcfg.bisection_steps, xtol=self.rcfg.newton_tol)
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
                return rev_cagr, SolverStatus.APPROXIMATE, notes, proj
            return rev_cagr, SolverStatus.SOLVED, notes, proj
        except Exception:
            pass

        steps = self.rcfg.bisection_steps
        for _ in range(steps):
            mid = (lo + hi) / 2
            ev_mid = self._project_ev(data, profile, mid, wacc, tg, horizon)
            if (ev_mid - target_ev) * (self._project_ev(data, profile, lo, wacc, tg, horizon) - target_ev) <= 0:
                hi = mid
            else:
                lo = mid
        rev_cagr = (lo + hi) / 2
        proj = project_enterprise_value_from_data(
            data, profile, rev_cagr, None, wacc, tg, horizon
        )
        residual = abs(self._project_ev(data, profile, rev_cagr, wacc, tg, horizon) - target_ev)
        notes.append(
            f"Bisection fallback used ({steps} steps): implied revenue CAGR "
            f"{rev_cagr:.2%}, residual ${residual:,.0f}"
        )
        return rev_cagr, SolverStatus.APPROXIMATE, notes, proj

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

        Hard constraints: when the target is unreachable inside [lo, hi] the solve
        returns NO_SOLUTION_IN_RANGE and names the binding bound — it never clamps
        to the edge. A root whose residual exceeds ``implied_residual_tol`` (flat
        EV surface → possibly ill-conditioned) degrades to APPROXIMATE.
        """
        try:
            f_lo = float(objective(lo))
            f_hi = float(objective(hi))
        except Exception as e:
            return ImpliedSolve(
                None, SolverStatus.INFEASIBLE.value, bound_lo=lo, bound_hi=hi,
                note=f"{name} 求解失败：{e}",
            )

        # Achievable [min, max] of the objective over the constraint interval.
        if increasing:
            lo_val, hi_val = f_lo, f_hi
            x_at_max, x_at_min = hi, lo
        else:
            lo_val, hi_val = f_hi, f_lo
            x_at_max, x_at_min = lo, hi

        tol = self.rcfg.implied_residual_tol
        span = max(abs(hi_val), abs(lo_val), 1.0)
        if target > hi_val + tol * span:
            return ImpliedSolve(
                None, SolverStatus.NO_SOLUTION_IN_RANGE.value, bound_lo=lo, bound_hi=hi,
                note=(f"即便 {name}={x_at_max:.2%}，推算 EV ${hi_val:,.0f} 仍低于目标 "
                      f"${target:,.0f}（目标超出约束上界）"),
            )
        if target < lo_val - tol * span:
            return ImpliedSolve(
                None, SolverStatus.NO_SOLUTION_IN_RANGE.value, bound_lo=lo, bound_hi=hi,
                note=(f"{name}={x_at_min:.2%} 时推算 EV ${lo_val:,.0f} 已高于目标 "
                      f"${target:,.0f}（目标低于约束下界）"),
            )

        def _h(x: float) -> float:
            return float(objective(x)) - target

        try:
            from scipy.optimize import brentq

            root = brentq(
                _h, lo, hi, maxiter=self.rcfg.bisection_steps, xtol=self.rcfg.newton_tol
            )
            status = SolverStatus.SOLVED.value
        except Exception:
            # Bisection fallback (brentq unavailable / failed to bracket).
            a, b = lo, hi
            for _ in range(self.rcfg.bisection_steps):
                mid = (a + b) / 2
                if _h(a) * _h(mid) <= 0:
                    b = mid
                else:
                    a = mid
            root = (a + b) / 2
            status = SolverStatus.APPROXIMATE.value

        residual = abs(_h(root))
        rel = residual / abs(target) if target else 0.0
        if rel > tol:
            return ImpliedSolve(
                root, SolverStatus.APPROXIMATE.value, residual, rel, lo, hi,
                note=(f"⚠️ {name} 求解残差偏高（${residual:,.0f}，{rel:.2%}），"
                      "EV 曲面较平坦，结果标记为近似"),
            )
        return ImpliedSolve(root, status, residual, rel, lo, hi)

    def _implied_expectations(
        self,
        data: FinancialData,
        profile: Any,
        target_ev: float,
        wacc: float,
        tg: float,
        horizon: int,
        base_revenue_cagr: float,
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
        out["base_assumptions"]["operating_margin"] = hist_om

        def _ev_bridge(g: float, om: float, w: float, tgr: float) -> float:
            p = project_enterprise_value(
                base_rev, g, om, tax_rate, da_ratio, capex_ratio, nwc_ratio, w, tgr, horizon
            )
            return p.enterprise_value

        # 1) Implied operating margin (hold g, wacc, tg).
        out["implied_operating_margin"] = self._solve_implied_scalar(
            lambda om: _ev_bridge(base_revenue_cagr, om, wacc, tg),
            target_ev, self.rcfg.implied_margin_lo, self.rcfg.implied_margin_hi,
            increasing=True, name="营业利润率",
        )

        # 2) Implied FCF margin (flat-margin bridge; hold g, wacc, tg).
        out["implied_fcf_margin"] = self._solve_implied_scalar(
            lambda fm: project_enterprise_value_flat_margin(
                base_rev, base_revenue_cagr, fm, wacc, tg, horizon
            ).enterprise_value,
            target_ev, self.rcfg.implied_fcf_margin_lo, self.rcfg.implied_fcf_margin_hi,
            increasing=True, name="FCF 利润率",
        )

        # 3) Implied WACC (hold g, margin, tg). Constraint: WACC > tg + spread.
        wacc_lo = max(self.rcfg.implied_wacc_lo, tg + MIN_WACC_TG_SPREAD)
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
        margin_norm: float = 0.20,
        capex_norm: float = 0.15,
    ) -> Optional[dict]:
        """Re-solve implied growth under *normalized* mature economics.

        Fixes a steady-state operating margin and a normalized capex/revenue
        ratio (mature compute-infra profile) and searches the revenue CAGR that
        reproduces the target EV. Turns a meaningless negative-EV "no solution"
        into an interpretable "what would have to be true" statement.
        """
        ttm = data.ttm
        if ttm is None or ttm.revenue is None or ttm.revenue <= 0:
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
                    ttm.revenue, g, margin_norm, tax_rate, da_ratio,
                    capex_norm, nwc_ratio, wacc, tg, horizon,
                )
                return p.enterprise_value if p is not None else 0.0

            grid = [0.0, 0.10, 0.20, 0.30, 0.50, 0.75, 1.00, 1.50, 2.00, cagr_hi]
            ev_at_hi = _ev(cagr_hi)
            bracket = None
            prev_g, prev_ev = grid[0], _ev(grid[0])
            for g in grid[1:]:
                ev = _ev(g)
                if (prev_ev - target_ev) * (ev - target_ev) <= 0:
                    bracket = (prev_g, g)
                    break
                prev_g, prev_ev = g, ev
            if bracket is None:
                return {
                    "assumptions": {"operating_margin": margin_norm, "capex_ratio": capex_norm},
                    "implied_revenue_cagr": None,
                    "cagr_hi": cagr_hi,
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
                "cagr_hi": cagr_hi,
                "ev_at_hi": ev_at_hi,
            }
        except Exception as e:
            log.info("normalized growth solve failed: %s", e)
            return None


__all__ = ["ReverseDCFModel"]
