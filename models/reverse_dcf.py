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

        assumptions = [
            ValuationAssumption("Target Price", price, "$/share", "Current market"),
            ValuationAssumption("WACC", round(wacc, 4), "%", "As per DCF"),
            ValuationAssumption("Terminal Growth", round(tg, 4), "%", tvg.source),
            ValuationAssumption(
                "Base FCF (TTM)", base_fcf, "", f"Reference ({fcf_source})"
            ),
            ValuationAssumption("Solver Method", "Bisection + Brent", "", "Revenue CAGR on FCF bridge"),
        ]

        rev_cagr, status, notes, proj = self._solve_revenue_cagr(
            data, profile, target_ev, wacc, tg
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
    ) -> Tuple[Optional[float], SolverStatus, List[str], Any]:
        notes: List[str] = []
        lo = self.rcfg.min_implied_cagr
        hi = self.rcfg.max_implied_cagr
        try:
            ev_lo = self._project_ev(data, profile, lo, wacc, tg)
            ev_hi = self._project_ev(data, profile, hi, wacc, tg)
        except Exception as e:
            return None, SolverStatus.INFEASIBLE, [f"Projection error: {e}"], None

        if not ((ev_lo - target_ev) * (ev_hi - target_ev) < 0):
            if ev_hi < target_ev:
                notes.append(
                    f"Even at {hi:.0%} revenue CAGR, EV only ${ev_hi:,.0f} < target ${target_ev:,.0f}"
                )
            else:
                notes.append(
                    f"At {lo:.0%} revenue CAGR, EV ${ev_lo:,.0f} > target ${target_ev:,.0f}"
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


__all__ = ["ReverseDCFModel"]
