"""
models/reverse_dcf.py - Reverse DCF Solver
Solves for implied revenue CAGR (and derived FCF CAGR) using the same FCF bridge as forward DCF.
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from config import (
    DEFAULT_DCF_CONFIG,
    DEFAULT_FORECAST_HORIZON_YEARS,
    DEFAULT_REVERSE_DCF_CONFIG,
    ModelName,
    ReverseDCFConfig,
    SolverStatus,
    get_logger,
    get_reverse_dcf_config,
)
from data.fcf_utils import resolve_ttm_fcf
from data.models import FinancialData
from forecasts.fcf_projection import (
    fcf_cagr_from_projection,
    project_enterprise_value_from_data,
)
from models.base import ValuationAssumption, ValuationModel, ValuationResult
from models.dcf import DCFModel
from valuation.terminal_growth import TerminalGrowthCalculator

log = get_logger("models.reverse_dcf")


class ReverseDCFModel(ValuationModel):
    NAME = ModelName.REVERSE_DCF

    def __init__(
        self,
        dcf_config=None,
        reverse_config: ReverseDCFConfig = DEFAULT_REVERSE_DCF_CONFIG,
        horizon: int = DEFAULT_FORECAST_HORIZON_YEARS,
    ) -> None:
        super().__init__()
        self.dcfg = dcf_config or DEFAULT_DCF_CONFIG
        self.rcfg = reverse_config
        self.horizon = horizon
        self._dcf = DCFModel(self.dcfg, self.horizon)
        self._tvg_calc = TerminalGrowthCalculator()

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

        # Override horizon if specified
        horizon = bt_params.get("horizon")
        if horizon is not None:
            self.horizon = int(horizon)

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
            ValuationAssumption("Forecast Horizon", str(self.horizon), "years",
                                f"Per-type for {bt_str}" if horizon is not None else "Default"),
        ]

        rev_cagr, status, notes, proj = self._solve_revenue_cagr(
            data, profile, target_ev, wacc, tg,
            cagr_lo=rev_cfg_min, cagr_hi=rev_cfg_max,
        )

        fcf_cagr = None
        if proj is not None:
            fcf_cagr = fcf_cagr_from_projection(proj.fcf_by_year, self.horizon)

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
                data, profile, target_ev, wacc, tg
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
        self, data: FinancialData, profile: Any, rev_cagr: float, wacc: float, tg: float
    ) -> float:
        proj = project_enterprise_value_from_data(
            data, profile, rev_cagr, None, wacc, tg, self.horizon
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
        cagr_lo: Optional[float] = None,
        cagr_hi: Optional[float] = None,
    ) -> Tuple[Optional[float], SolverStatus, List[str], Any]:
        notes: List[str] = []
        lo = cagr_lo if cagr_lo is not None else self.rcfg.min_implied_cagr
        hi = cagr_hi if cagr_hi is not None else self.rcfg.max_implied_cagr
        try:
            ev_lo = self._project_ev(data, profile, lo, wacc, tg)
            ev_hi = self._project_ev(data, profile, hi, wacc, tg)
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
                return self._project_ev(data, profile, g, wacc, tg) - target_ev

            rev_cagr = brentq(_f, lo, hi, maxiter=self.rcfg.bisection_steps, xtol=self.rcfg.newton_tol)
            proj = project_enterprise_value_from_data(
                data, profile, rev_cagr, None, wacc, tg, self.horizon
            )
            return rev_cagr, SolverStatus.SOLVED, [], proj
        except Exception:
            pass

        steps = self.rcfg.bisection_steps
        for _ in range(steps):
            mid = (lo + hi) / 2
            ev_mid = self._project_ev(data, profile, mid, wacc, tg)
            if (ev_mid - target_ev) * (self._project_ev(data, profile, lo, wacc, tg) - target_ev) <= 0:
                hi = mid
            else:
                lo = mid
        rev_cagr = (lo + hi) / 2
        proj = project_enterprise_value_from_data(
            data, profile, rev_cagr, None, wacc, tg, self.horizon
        )
        return rev_cagr, SolverStatus.APPROXIMATE, [f"Bisection fallback used ({steps} steps)"], proj

    def _normalized_growth_solve(
        self,
        data: FinancialData,
        profile: Any,
        target_ev: float,
        wacc: float,
        tg: float,
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
                horizon_years=self.horizon,
                business_type=business_type_from_profile(profile),
            )
            _, _, _hist_om, da_ratio, _capex_ratio, nwc_ratio, tax_rate = eng._extract_history(data)

            def _ev(g: float) -> float:
                p = project_enterprise_value(
                    ttm.revenue, g, margin_norm, tax_rate, da_ratio,
                    capex_norm, nwc_ratio, wacc, tg, self.horizon,
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
