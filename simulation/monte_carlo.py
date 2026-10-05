"""
simulation/monte_carlo.py - Monte Carlo Simulation Engine
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from config import DEFAULT_MC_CONFIG, DEFAULT_DCF_CONFIG, DEFAULT_FORECAST_HORIZON_YEARS, MonteCarloConfig, get_logger
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


class MonteCarloSimulator:
    """Runs Monte Carlo simulations on DCF inputs."""

    def __init__(
        self,
        config: MonteCarloConfig = DEFAULT_MC_CONFIG,
        horizon: int = DEFAULT_FORECAST_HORIZON_YEARS,
    ) -> None:
        self.cfg = config
        self.horizon = horizon
        self.rng = np.random.RandomState(self.cfg.random_seed)

    def run(self, data: FinancialData, profile: Any) -> MonteCarloResult:
        ttm = data.ttm
        if ttm is None or ttm.revenue is None or ttm.shares_outstanding is None or ttm.shares_outstanding <= 0:
            return MonteCarloResult(
                n_simulations=0, values=[],
                percentiles={}, mean_value=0.0, median_value=0.0, std_dev=0.0,
                notes=["Insufficient TTM data for Monte Carlo"],
            )

        hist_rev_cagr, hist_gm, hist_om, hist_da_ratio, hist_capex_ratio, _, hist_tax = (
            self._extract_stats(data)
        )
        base_rev = ttm.revenue
        shares = ttm.shares_outstanding
        net_debt = data.market.net_debt_or_zero()

        dist_params = {
            "revenue_cagr_mean": max(-0.10, min(0.35, hist_rev_cagr)),
            "revenue_cagr_std": max(0.02, min(0.15, abs(hist_rev_cagr) * 0.5 + 0.05)),
            "op_margin_mean": max(0.02, min(0.50, hist_om)),
            "op_margin_std": max(0.01, min(0.10, abs(hist_om) * 0.3 + 0.02)),
            "wacc_mean": 0.10,
            "wacc_std": 0.015,
            "tg_mean": 0.025,
            "tg_std": 0.008,
            "da_ratio": hist_da_ratio,
            "capex_ratio": hist_capex_ratio,
            "tax_rate": hist_tax,
        }

        all_values: List[float] = []
        n = self.cfg.n_simulations
        for _ in range(n):
            cagr = self.rng.normal(dist_params["revenue_cagr_mean"], dist_params["revenue_cagr_std"])
            om = self.rng.normal(dist_params["op_margin_mean"], dist_params["op_margin_std"])
            wacc = self.rng.normal(dist_params["wacc_mean"], dist_params["wacc_std"])
            tg = self.rng.normal(dist_params["tg_mean"], dist_params["tg_std"])
            cagr = max(-0.20, min(0.60, cagr))
            om = max(-0.30, min(0.70, om))
            wacc = max(0.05, min(0.25, wacc))
            tg = max(0.0, min(0.05, tg))

            pps = self._project_one(base_rev, cagr, om, wacc, tg,
                                     dist_params["da_ratio"], dist_params["capex_ratio"],
                                     dist_params["tax_rate"], shares, net_debt)
            if pps is not None and 0 <= pps <= 1e6:
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
        return MonteCarloResult(
            n_simulations=n,
            values=all_values,
            percentiles=percentiles,
            mean_value=float(arr.mean()),
            median_value=float(np.median(arr)),
            std_dev=float(arr.std()),
            assumptions=dist_params,
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
        tax_rate: float,
        shares: float,
        net_debt: float,
    ) -> Optional[float]:
        n = self.horizon
        pv_explicit = 0.0
        rev = base_rev
        last_fcf = 0.0
        for t in range(1, n + 1):
            rev *= (1 + cagr)
            op = rev * om
            nopat = op * (1 - tax_rate)
            da = rev * da_ratio
            capex = rev * capex_ratio
            nwc = rev * 0.002
            fcf = nopat + da - capex - nwc
            last_fcf = fcf
            pv_explicit += fcf / (1 + wacc) ** t
        if wacc > tg and last_fcf > 0:
            tv = (last_fcf * (1 + tg)) / (wacc - tg)
        else:
            tv = 0.0
        pv_tv = tv / (1 + wacc) ** n
        ev = pv_explicit + pv_tv
        eq = ev - net_debt
        return eq / shares if shares > 0 else None

    def _extract_stats(self, data: FinancialData):
        from forecasts.forecast import ForecastEngine
        eng = ForecastEngine()
        return eng._extract_history(data)


__all__ = ["MonteCarloSimulator", "MonteCarloResult"]
