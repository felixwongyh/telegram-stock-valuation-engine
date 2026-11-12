"""
simulation/monte_carlo.py - Monte Carlo Simulation Engine
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from config import (
    DEFAULT_DCF_CONFIG,
    DEFAULT_MC_CONFIG,
    MonteCarloConfig,
    get_logger,
    resolve_forecast_horizon,
)
from data.models import FinancialData

log = get_logger("simulation.monte_carlo")


PERCENTILES = [1, 5, 10, 25, 50, 75, 90, 95, 99]


@dataclass
class MonteCarloResult:
    n_simulations: int
    values: List[float]
    percentiles: Dict[int, float]
    mean_value: float
    median_value: float
    std_dev: float
    assumptions: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    # ---- Probabilistic verdict (Session #07) ------------------------------
    # A single "median intrinsic value" hides the fact that the answer is a
    # distribution. When the current price sits in the tail, a probability
    # statement is more honest than a point estimate.
    n_valid: int = 0
    current_price: Optional[float] = None
    prob_above_price: Optional[float] = None      # P(intrinsic > current price)
    prob_overvalued_30: Optional[float] = None    # P(intrinsic < 0.70 × price)
    prob_equity_zero: Optional[float] = None      # P(equity value <= 0)


# One-factor correlation among the value drivers so that growth, margin and
# discount rate do not vary as pure independent noise. Rationale:
#   * higher assumed growth usually travels with higher perceived risk (WACC↑)
#   * scale and operating margin are mildly positively linked
#   * terminal growth tracks the discount-rate regime
_DRIVER_CORR = np.array([
    #  cagr   om    wacc   tg
    [1.00,  0.20,  0.30,  0.20],   # cagr
    [0.20,  1.00,  0.00,  0.10],   # om
    [0.30,  0.00,  1.00,  0.30],   # wacc
    [0.20,  0.10,  0.30,  1.00],   # tg
])


def _correlation_cholesky(corr: np.ndarray) -> np.ndarray:
    """Return a factor L with L @ L.T ~ corr, robust to small non-PSD drift."""
    try:
        return np.linalg.cholesky(corr)
    except np.linalg.LinAlgError:
        vals, vecs = np.linalg.eigh(corr)
        vals = np.clip(vals, 1e-8, None)
        psd = vecs @ np.diag(vals) @ vecs.T
        return np.linalg.cholesky(psd)


class MonteCarloSimulator:
    """Runs Monte Carlo simulations on DCF inputs."""

    def __init__(
        self,
        config: MonteCarloConfig = DEFAULT_MC_CONFIG,
        horizon: Optional[int] = None,
    ) -> None:
        self.cfg = config
        # Horizon resolved per call from the profile (never cached), so it stays
        # identical to the DCF / Reverse DCF window for the same business type
        # (Session #16). Pass an int only to force an explicit override.
        self._horizon_override = horizon
        self.rng = np.random.RandomState(self.cfg.random_seed)
        self._corr_l = _correlation_cholesky(_DRIVER_CORR)

    def _resolve_horizon(self, profile: Any) -> int:
        if self._horizon_override is not None:
            return int(self._horizon_override)
        from forecasts.nwc_utils import business_type_from_profile

        return resolve_forecast_horizon(business_type_from_profile(profile))

    def run(self, data: FinancialData, profile: Any) -> MonteCarloResult:
        ttm = data.ttm
        if ttm is None or ttm.revenue is None or ttm.shares_outstanding is None or ttm.shares_outstanding <= 0:
            return MonteCarloResult(
                n_simulations=0, values=[],
                percentiles={}, mean_value=0.0, median_value=0.0, std_dev=0.0,
                notes=["Insufficient TTM data for Monte Carlo"],
            )

        hist_rev_cagr, hist_gm, hist_om, hist_da_ratio, hist_capex_ratio, hist_nwc_ratio, hist_tax = (
            self._extract_stats(data, profile)
        )
        horizon = self._resolve_horizon(profile)
        from valuation.terminal_growth import TerminalGrowthCalculator
        from valuation.wacc import WaccCalculator

        wacc_bd = WaccCalculator(config=DEFAULT_DCF_CONFIG).calculate(data, profile)
        wacc_mean = float(wacc_bd.wacc)
        tg_mean = float(
            TerminalGrowthCalculator().calculate(data, wacc=wacc_mean).base
        )
        base_rev = ttm.revenue
        shares = ttm.shares_outstanding
        net_debt = data.market.net_debt_or_zero()
        price = data.market.current_price

        dist_params = {
            "revenue_cagr_mean": max(-0.10, min(0.35, hist_rev_cagr)),
            "revenue_cagr_std": max(0.02, min(0.15, abs(hist_rev_cagr) * 0.5 + 0.05)),
            "op_margin_mean": max(0.02, min(0.50, hist_om)),
            "op_margin_std": max(0.01, min(0.10, abs(hist_om) * 0.3 + 0.02)),
            "wacc_mean": wacc_mean,
            "wacc_std": self.cfg.wacc_std,
            "tg_mean": tg_mean,
            "tg_std": self.cfg.tg_std,
            "da_ratio": hist_da_ratio,
            "capex_ratio": hist_capex_ratio,
            "nwc_marginal_ratio": hist_nwc_ratio,
            "tax_rate": hist_tax,
        }

        all_values: List[float] = []
        n_equity_zero = 0
        n = self.cfg.n_simulations
        means = np.array([
            dist_params["revenue_cagr_mean"],
            dist_params["op_margin_mean"],
            dist_params["wacc_mean"],
            dist_params["tg_mean"],
        ])
        stds = np.array([
            dist_params["revenue_cagr_std"],
            dist_params["op_margin_std"],
            dist_params["wacc_std"],
            dist_params["tg_std"],
        ])
        for _ in range(n):
            # Correlated driver draw (growth / margin / WACC / terminal growth).
            z = self._corr_l @ self.rng.normal(0.0, 1.0, 4)
            cagr, om, wacc, tg = means + stds * z
            cagr = max(-0.20, min(0.60, cagr))
            om = max(-0.30, min(0.70, om))
            wacc = max(0.05, min(0.25, wacc))
            tg = max(0.0, min(0.05, tg))
            # Gordon stability: terminal growth must stay below the discount rate.
            tg = min(tg, wacc - 0.005)

            pps = self._project_one(base_rev, cagr, om, wacc, tg,
                                     dist_params["da_ratio"], dist_params["capex_ratio"],
                                     dist_params["nwc_marginal_ratio"],
                                     dist_params["tax_rate"], shares, net_debt, horizon)
            if pps is None or pps > 1e6:
                continue
            if pps < 0:
                # Negative equity value = insolvency: floor at 0 and record it
                # rather than silently dropping the worst tail.
                n_equity_zero += 1
                pps = 0.0
            all_values.append(pps)

        if not all_values:
            return MonteCarloResult(
                n_simulations=n, values=[],
                percentiles={}, mean_value=0.0, median_value=0.0, std_dev=0.0,
                assumptions=dist_params,
                notes=["All simulations produced invalid values"],
            )

        arr = np.array(all_values)
        percentiles = {p: float(np.percentile(arr, p)) for p in PERCENTILES}
        n_valid = len(all_values)

        prob_above_price = None
        prob_overvalued_30 = None
        prob_equity_zero = n_equity_zero / n_valid if n_valid else None
        if price is not None and price > 0:
            prob_above_price = float((arr > price).mean())
            prob_overvalued_30 = float((arr < price * 0.70).mean())

        notes: List[str] = []
        if prob_above_price is not None:
            notes.append(
                f"P(内在价值 > 当前价 ${price:.2f}) = {prob_above_price:.1%}"
            )
            notes.append(
                f"P(高估 > 30%) = {prob_overvalued_30:.1%}"
            )
            if prob_equity_zero and prob_equity_zero > 0:
                notes.append(
                    f"P(股权价值归零/资不抵债) = {prob_equity_zero:.1%}（负值已 floor 到 0）"
                )

        return MonteCarloResult(
            n_simulations=n,
            n_valid=n_valid,
            values=all_values,
            percentiles=percentiles,
            mean_value=float(arr.mean()),
            median_value=float(np.median(arr)),
            std_dev=float(arr.std()),
            assumptions=dist_params,
            current_price=price,
            prob_above_price=prob_above_price,
            prob_overvalued_30=prob_overvalued_30,
            prob_equity_zero=prob_equity_zero,
            notes=notes,
        )

    def _project_one(
        self,
        base_rev: float,
        cagr: float,
        om: float,
        wacc: float,
        tg: float,
        da_ratio: float,
        capex_ratio: float,
        nwc_marginal_ratio: float,
        tax_rate: float,
        shares: float,
        net_debt: float,
        horizon: int,
    ) -> Optional[float]:
        from forecasts.fcf_projection import project_enterprise_value

        proj = project_enterprise_value(
            base_rev,
            cagr,
            om,
            tax_rate,
            da_ratio,
            capex_ratio,
            nwc_marginal_ratio,
            wacc,
            tg,
            horizon,
        )
        eq = proj.enterprise_value - net_debt
        return eq / shares if shares > 0 else None

    def _extract_stats(self, data: FinancialData, profile: Any = None):
        from forecasts.forecast import ForecastEngine
        from forecasts.nwc_utils import business_type_from_profile

        eng = ForecastEngine(business_type=business_type_from_profile(profile))
        return eng._extract_history(data)


__all__ = ["MonteCarloSimulator", "MonteCarloResult"]
