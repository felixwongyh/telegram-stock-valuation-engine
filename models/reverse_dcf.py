"""
models/reverse_dcf.py - Reverse DCF Solver
Solves for the implied FCF CAGR baked into the current market price.
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
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult
from models.dcf import DCFModel

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
            if ttm.free_cash_flow is None:
                reasons.append("TTM FCF required")
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

        base_fcf = ttm.free_cash_flow or 0.0
        if base_fcf <= 0:
            base_fcf = abs(ttm.operating_cash_flow + (ttm.capex or 0)) if ttm.operating_cash_flow is not None else 1.0
        wacc = self._dcf._estimate_wacc(data, profile)
        tg = self.dcfg.default_terminal_growth

        assumptions = [
            ValuationAssumption("Target Price", price, "$/share", "Current market"),
            ValuationAssumption("WACC", round(wacc, 4), "%", "As per DCF"),
            ValuationAssumption("Terminal Growth", round(tg, 4), "%", "Default"),
            ValuationAssumption("Base FCF", base_fcf, "", "TTM"),
            ValuationAssumption("Solver Method", "Bisection + Newton", "", "Scipy fallback"),
        ]

        cagr, status, notes = self._solve_cagr(base_fcf, target_ev, wacc, tg)

        rev_cagr = None
        if cagr is not None and ttm.revenue and ttm.revenue > 0:
            fcf_margin = base_fcf / ttm.revenue
            if fcf_margin > 0:
                rev_cagr = (1 + cagr) ** 0.9 - 1

        breakdown = {
            "implied_fcf_cagr": cagr,
            "implied_revenue_cagr": rev_cagr,
            "target_enterprise_value": target_ev,
            "target_equity_value": target_equity,
            "wacc": wacc,
            "terminal_growth": tg,
            "base_fcf": base_fcf,
        }

        if cagr is None:
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

    def _project_ev(self, base_fcf: float, cagr: float, wacc: float, tg: float) -> float:
        pv_explicit = 0.0
        fcf = base_fcf
        last_fcf = base_fcf
        for t in range(1, self.horizon + 1):
            fcf = fcf * (1 + cagr)
            last_fcf = fcf
            pv_explicit += fcf / (1 + wacc) ** t
        if wacc > tg:
            tv = (last_fcf * (1 + tg)) / (wacc - tg)
        else:
            tv = (last_fcf * (1 + tg)) / max(1e-3, wacc - tg + 1e-3)
        pv_tv = tv / (1 + wacc) ** self.horizon
        return pv_explicit + pv_tv

    def _solve_cagr(
        self, base_fcf: float, target_ev: float, wacc: float, tg: float
    ) -> Tuple[Optional[float], SolverStatus, List[str]]:
        notes: List[str] = []
        lo = self.rcfg.min_implied_cagr
        hi = self.rcfg.max_implied_cagr
        try:
            ev_lo = self._project_ev(base_fcf, lo, wacc, tg)
            ev_hi = self._project_ev(base_fcf, hi, wacc, tg)
        except Exception as e:
            return None, SolverStatus.INFEASIBLE, [f"Projection error: {e}"]

        if not ((ev_lo - target_ev) * (ev_hi - target_ev) < 0):
            if ev_hi < target_ev:
                notes.append(
                    f"Even at {hi:.0%} CAGR, EV only ${ev_hi:,.0f} < target ${target_ev:,.0f}"
                )
            else:
                notes.append(
                    f"At {lo:.0%} CAGR, EV ${ev_lo:,.0f} > target ${target_ev:,.0f}"
                )
            return None, SolverStatus.NO_SOLUTION_IN_RANGE, notes

        try:
            from scipy.optimize import brentq
            def _f(g):
                return self._project_ev(base_fcf, g, wacc, tg) - target_ev
            cagr = brentq(_f, lo, hi, maxiter=self.rcfg.bisection_steps, xtol=self.rcfg.newton_tol)
            return cagr, SolverStatus.SOLVED, []
        except Exception as e:
            pass

        steps = self.rcfg.bisection_steps
        for _ in range(steps):
            mid = (lo + hi) / 2
            ev_mid = self._project_ev(base_fcf, mid, wacc, tg)
            if (ev_mid - target_ev) * (self._project_ev(base_fcf, lo, wacc, tg) - target_ev) <= 0:
                hi = mid
            else:
                lo = mid
        cagr = (lo + hi) / 2
        return cagr, SolverStatus.APPROXIMATE, [f"Bisection fallback used ({steps} steps)"]


__all__ = ["ReverseDCFModel"]
