"""
simulation/monte_carlo.py - Monte Carlo Simulation Engine

Two explicit modes (Phase 2):

* ``base_case`` — the distribution is centred on the **deterministic DCF's own
  base-case assumptions** (effective revenue CAGR and level operating margin
  implied by the DCF base forecast). Perturbing these by their uncertainty is a
  *stress distribution around the DCF point value*, so the 0-perturbation anchor
  reconciles with the DCF baseline. This is the default.
* ``historical`` — the distribution is centred on the **raw historical
  statistics** (5-year revenue CAGR and average operating margin). This is an
  independent, history-based view.

Monte Carlo here is a *DCF assumption-perturbation distribution*, not an
independent valuation model and not independent evidence of fair value; the
report must say so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from config import (
    DEFAULT_DCF_CONFIG,
    DEFAULT_MC_CONFIG,
    MonteCarloConfig,
    ScenarioType,
    get_logger,
    resolve_forecast_horizon,
)
from data.models import FinancialData

log = get_logger("simulation.monte_carlo")


PERCENTILES = [1, 5, 10, 25, 50, 75, 90, 95, 99]

MODE_BASE_CASE = "base_case"
MODE_HISTORICAL = "historical"

# Driver order is fixed and shared with the correlation matrix below so the
# Cholesky factor lines up with the drawn vector.
DRIVER_LABELS = ["revenue_cagr", "operating_margin", "wacc", "terminal_growth"]


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
    prob_equity_zero: Optional[float] = None      # P(intrinsic <= 0)

    # ---- Reproducibility / audit metadata (Phase 2) -----------------------
    mode: str = MODE_BASE_CASE
    random_seed: Optional[int] = None
    n_requested: int = 0            # draws attempted
    n_invalid: int = 0              # draws dropped (non-finite / absurd value)
    n_truncated: int = 0            # valid draws whose equity value was floored to 0
    param_distributions: Dict[str, Any] = field(default_factory=dict)
    correlation: Optional[Dict[str, Any]] = None
    # Deterministic reconciliation (base_case mode): the 0-perturbation anchor
    # and its gap vs the deterministic DCF value-per-share, when supplied.
    anchor_value: Optional[float] = None
    dcf_anchor: Optional[float] = None
    reconcile_gap: Optional[float] = None


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

    def _resolve_horizon(self, profile: Any) -> int:
        if self._horizon_override is not None:
            return int(self._horizon_override)
        from forecasts.nwc_utils import business_type_from_profile

        return resolve_forecast_horizon(business_type_from_profile(profile))

    # ------------------------------------------------------------------
    # Driver centring
    # ------------------------------------------------------------------
    def _base_case_path(
        self, data: FinancialData, profile: Any, horizon: int,
    ) -> Optional[Dict[str, Any]]:
        """Expose the DCF base forecast as a *perturbable* path shape.

        The deterministic DCF projects a *decaying* growth path and a
        *drifting* operating margin. A flat-CAGR / flat-margin projection
        cannot reproduce that point value (MSFT: +13.9% gap), so instead of
        flattening we parametrise the very same base forecast the DCF uses:

            revenue_t   = ttm_revenue * (1 + g)^t * shape_rev[t]
            op_margin_t = om + margin_offsets[t]

        with ``shape_rev``/``margin_offsets`` derived from the DCF base path so
        that ``(g, om) = (eff_cagr, eff_om)`` reproduces the base path exactly.
        This makes the 0-perturbation Monte-Carlo anchor reconcile with the
        deterministic DCF (acceptance #5). Returns ``None`` on any failure so
        the caller falls back to the flat historical projection.
        """
        try:
            from forecasts.forecast import ForecastEngine
            from forecasts.nwc_utils import business_type_from_profile

            eng = ForecastEngine(
                horizon_years=horizon,
                business_type=business_type_from_profile(profile),
            )
            base = eng._build_scenario(data, ScenarioType.BASE)
        except Exception as e:  # pragma: no cover - defensive
            log.warning(f"Base-case path derivation failed: {e}")
            return None
        ttm = data.ttm
        if (
            not base or len(base) < horizon or ttm is None
            or not ttm.revenue or ttm.revenue <= 0 or horizon < 1
        ):
            return None
        last_rev = base[horizon - 1].revenue
        if not last_rev or last_rev <= 0:
            return None
        eff_cagr = (last_rev / ttm.revenue) ** (1.0 / horizon) - 1.0
        oms = [base[i].operating_margin for i in range(horizon)]
        if any(o is None for o in oms):
            return None
        operating_margins = [o for o in oms if o is not None]
        eff_om = sum(operating_margins) / len(operating_margins)
        shape_rev: List[float] = []
        margin_offsets: List[float] = []
        for i in range(horizon):
            denom = ttm.revenue * (1.0 + eff_cagr) ** (i + 1)
            shape_rev.append(base[i].revenue / denom)
            margin_offsets.append(operating_margins[i] - eff_om)
        return {
            "cagr": eff_cagr,
            "om": eff_om,
            "shape_rev": shape_rev,
            "margin_offsets": margin_offsets,
        }

    def run(
        self,
        data: FinancialData,
        profile: Any,
        mode: Optional[str] = None,
        dcf_value: Optional[float] = None,
    ) -> MonteCarloResult:
        ttm = data.ttm
        if ttm is None or ttm.revenue is None or ttm.shares_outstanding is None or ttm.shares_outstanding <= 0:
            return MonteCarloResult(
                n_simulations=0, values=[],
                percentiles={}, mean_value=0.0, median_value=0.0, std_dev=0.0,
                notes=["Insufficient TTM data for Monte Carlo"],
            )

        run_mode = (mode or getattr(self.cfg, "mode", None) or MODE_BASE_CASE).lower()
        if run_mode not in (MODE_BASE_CASE, MODE_HISTORICAL):
            run_mode = MODE_BASE_CASE

        # base_case reconciles against a deterministic DCF anchor; without one
        # (banks/insurers on cost-of-equity caliber, or an unsolved DCF) the mode
        # is not meaningful, so fall back to the independent historical view.
        mode_fallback_note: Optional[str] = None
        if run_mode == MODE_BASE_CASE and dcf_value is None:
            run_mode = MODE_HISTORICAL
            mode_fallback_note = (
                "无确定性 DCF 基准（金融股走 RIM/DDM 或 DCF 未求解），"
                "base_case 无从对账 → 已回退为历史分布模式"
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

        # base_case mode parametrises the DCF's own base forecast path (exact
        # 0-perturbation reconciliation); historical mode centres on raw stats.
        path = self._base_case_path(data, profile, horizon) if run_mode == MODE_BASE_CASE else None
        if path is not None:
            cagr_center, om_center = path["cagr"], path["om"]
        else:
            cagr_center, om_center = hist_rev_cagr, hist_om

        # Configurable business bounds (NOT an opinion on the central tendency).
        # The margin mean is deliberately NOT floored at a positive value: a
        # loss-making company keeps a negative margin so distress is representable.
        cagr_lo, cagr_hi = self.cfg.revenue_cagr_lower, self.cfg.revenue_cagr_upper
        om_lo, om_hi = self.cfg.op_margin_lower, self.cfg.op_margin_upper
        wacc_lo, wacc_hi = self.cfg.wacc_lower, self.cfg.wacc_upper
        tg_lo, tg_hi = self.cfg.tg_lower, self.cfg.tg_upper

        dist_params = {
            "revenue_cagr_mean": max(cagr_lo, min(cagr_hi, cagr_center)),
            "revenue_cagr_std": max(0.02, min(0.15, abs(cagr_center) * 0.5 + 0.05)),
            "op_margin_mean": max(om_lo, min(om_hi, om_center)),
            "op_margin_std": max(0.01, min(0.12, abs(om_center) * 0.3 + 0.02)),
            "wacc_mean": wacc_mean,
            "wacc_std": self.cfg.wacc_std,
            "tg_mean": tg_mean,
            "tg_std": self.cfg.tg_std,
            "da_ratio": hist_da_ratio,
            "capex_ratio": hist_capex_ratio,
            "nwc_marginal_ratio": hist_nwc_ratio,
            "tax_rate": hist_tax,
        }

        param_distributions = {
            "revenue_cagr": {
                "mean": dist_params["revenue_cagr_mean"],
                "std": dist_params["revenue_cagr_std"],
                "lower": cagr_lo, "upper": cagr_hi,
            },
            "operating_margin": {
                "mean": dist_params["op_margin_mean"],
                "std": dist_params["op_margin_std"],
                "lower": om_lo, "upper": om_hi,
            },
            "wacc": {
                "mean": dist_params["wacc_mean"], "std": dist_params["wacc_std"],
                "lower": wacc_lo, "upper": wacc_hi,
            },
            "terminal_growth": {
                "mean": dist_params["tg_mean"], "std": dist_params["tg_std"],
                "lower": tg_lo, "upper": tg_hi,
            },
        }
        correlation = {"drivers": list(DRIVER_LABELS), "matrix": _DRIVER_CORR.tolist()}

        # ---- Deterministic 0-perturbation anchor (reconciliation) ----------
        def project(cagr: float, om: float, wacc: float, tg: float) -> Optional[float]:
            """Equity value/share; path-based when a base shape exists."""
            if path is not None:
                return self._project_one_path(
                    base_rev, path["shape_rev"], path["margin_offsets"], cagr, om,
                    dist_params["da_ratio"], dist_params["capex_ratio"],
                    dist_params["nwc_marginal_ratio"], dist_params["tax_rate"],
                    wacc, tg, shares, net_debt, horizon,
                )
            return self._project_one(
                base_rev, cagr, om, wacc, tg,
                dist_params["da_ratio"], dist_params["capex_ratio"],
                dist_params["nwc_marginal_ratio"], dist_params["tax_rate"],
                shares, net_debt, horizon,
            )

        anchor_tg = min(dist_params["tg_mean"], dist_params["wacc_mean"] - 0.005)
        anchor_value = project(
            dist_params["revenue_cagr_mean"], dist_params["op_margin_mean"],
            dist_params["wacc_mean"], anchor_tg,
        )
        reconcile_gap = None
        if anchor_value is not None:
            # Match the DCF's reporting convention (negative equity floored to 0,
            # i.e. equity wipeout) and the per-sim flooring below, so the anchor
            # is the same quantity the DCF reports.
            if anchor_value < 0:
                anchor_value = 0.0
            if dcf_value is not None:
                dcf_f = float(dcf_value)
                if abs(dcf_f) > 1e-9:
                    reconcile_gap = (anchor_value - dcf_f) / dcf_f
                elif abs(anchor_value) < 1e-9:
                    reconcile_gap = 0.0  # both floored to 0 (pre-profit / insolvent)

        all_values: List[float] = []
        n_equity_zero = 0
        n_invalid = 0
        n = self.cfg.n_simulations
        # Re-seed per run so results are reproducible regardless of how many
        # times the shared instance has been used (avoids the shared-singleton
        # state-drift class of bug fixed elsewhere in the engine).
        self.rng = np.random.RandomState(self.cfg.random_seed)
        self._corr_l = _correlation_cholesky(_DRIVER_CORR)
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
            cagr = max(cagr_lo, min(cagr_hi, cagr))
            om = max(om_lo, min(om_hi, om))
            wacc = max(wacc_lo, min(wacc_hi, wacc))
            tg = max(tg_lo, min(tg_hi, tg))
            # Gordon stability: terminal growth must stay below the discount rate.
            tg = min(tg, wacc - 0.005)

            pps = project(cagr, om, wacc, tg)
            if pps is None or not np.isfinite(pps) or pps > 1e6:
                n_invalid += 1
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
                mode=run_mode, random_seed=self.cfg.random_seed,
                n_requested=n, n_invalid=n_invalid, n_truncated=0,
                param_distributions=param_distributions, correlation=correlation,
                anchor_value=anchor_value, dcf_anchor=dcf_value,
                reconcile_gap=reconcile_gap,
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

        mode_label = "基期假设扰动（与确定性 DCF 基准对账）" if run_mode == MODE_BASE_CASE \
            else "历史分布（以历史统计为中心）"
        notes: List[str] = []
        if mode_fallback_note:
            notes.append(mode_fallback_note)
        notes.append(
            f"模式 = {mode_label}；随机种子 = {self.cfg.random_seed}；"
            f"请求 {n} · 有效 {n_valid} · 无效 {n_invalid} · 截断(负值 floor) {n_equity_zero}"
        )
        notes.append(
            "蒙特卡洛为 DCF 假设扰动分布，不是独立估值证据；"
            "只是把同一套 DCF 假设的不确定性可视化。"
        )
        if run_mode == MODE_BASE_CASE and anchor_value is not None:
            if reconcile_gap is not None and dcf_value is not None:
                notes.append(
                    f"对账：零扰动锚点 ${anchor_value:.2f} vs 确定性 DCF ${float(dcf_value):.2f} "
                    f"（差 {reconcile_gap:+.1%}）"
                )
            else:
                notes.append(f"对账：零扰动锚点 ${anchor_value:.2f}（未提供 DCF 基准）")
        if prob_above_price is not None:
            notes.append(
                f"P(内在价值 > 当前价 ${price:.2f}) = {prob_above_price:.1%}"
            )
            notes.append(f"P(高估 > 30%) = {prob_overvalued_30:.1%}")
            if prob_equity_zero and prob_equity_zero > 0:
                notes.append(
                    f"模拟下的 Equity Value Wipeout Probability = {prob_equity_zero:.1%}"
                    f"（负股权价值已 floor 到 0；非实际破产概率）"
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
            mode=run_mode,
            random_seed=self.cfg.random_seed,
            n_requested=n,
            n_invalid=n_invalid,
            n_truncated=n_equity_zero,
            param_distributions=param_distributions,
            correlation=correlation,
            anchor_value=anchor_value,
            dcf_anchor=dcf_value,
            reconcile_gap=reconcile_gap,
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

    def _project_one_path(
        self,
        ttm_rev: float,
        shape_rev: List[float],
        margin_offsets: List[float],
        cagr: float,
        om: float,
        da_ratio: float,
        capex_ratio: float,
        nwc_marginal_ratio: float,
        tax_rate: float,
        wacc: float,
        tg: float,
        shares: float,
        net_debt: float,
        horizon: int,
    ) -> Optional[float]:
        """Project equity/share along the parametrised DCF base path.

        At ``(cagr, om) = (eff_cagr, eff_om)`` this reproduces the deterministic
        DCF base-case FCF path exactly, so the Monte-Carlo anchor reconciles.
        """
        from forecasts.fcf_projection import gordon_terminal_value
        from forecasts.nwc_utils import forecast_nwc_change

        capex_ratio = abs(capex_ratio)
        rev_prev = ttm_rev
        fcfs: List[float] = []
        for i in range(horizon):
            rev = ttm_rev * (1.0 + cagr) ** (i + 1) * shape_rev[i]
            op = rev * (om + margin_offsets[i])
            nopat = op * (1.0 - tax_rate)
            da = rev * da_ratio
            capex = rev * capex_ratio
            nwc = forecast_nwc_change(rev - rev_prev, nwc_marginal_ratio)
            fcfs.append(nopat + da - capex - nwc)
            rev_prev = rev
        pv_explicit = sum(f / (1.0 + wacc) ** (t + 1) for t, f in enumerate(fcfs))
        tv = gordon_terminal_value(fcfs[-1], wacc, tg, horizon)
        ev = pv_explicit + tv.pv_terminal_value
        eq = ev - net_debt
        return eq / shares if shares > 0 else None

    def _extract_stats(self, data: FinancialData, profile: Any = None):
        from forecasts.forecast import ForecastEngine
        from forecasts.nwc_utils import business_type_from_profile

        eng = ForecastEngine(business_type=business_type_from_profile(profile))
        return eng._extract_history(data)


__all__ = [
    "MonteCarloSimulator",
    "MonteCarloResult",
    "MODE_BASE_CASE",
    "MODE_HISTORICAL",
    "DRIVER_LABELS",
]
