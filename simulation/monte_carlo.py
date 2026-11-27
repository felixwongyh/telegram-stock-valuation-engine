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

**P0-1 (Financial Institution Split):** Banks / insurers must NOT use the
ordinary DCF Monte Carlo (revenue CAGR / operating margin / WACC / terminal
growth are undefined for a borrowing business). Instead, a dedicated
``run_bank`` path perturbs the two drivers that actually matter for a bank:

* **Cost of Equity (Ke)** — from the unified CAPM β exit, perturbed in β space.
* **ROE** — from TTM net income / book equity, perturbed as a relative shock.

The bank MC outputs bank-specific probability statements:
  * ``P(Intrinsic Value > Market Price)``
  * ``P(Overvalued > 20%)``
  * ``P(Undervalued > 20%)``
  * ``P(Value below Book Value)``
  * ``P(ROE below Cost of Equity)``

When the bank MC is not implementable (missing book value / net income / β),
the report shows ``Monte Carlo: Not Applicable — Financial Institution``.
"""
from __future__ import annotations

import math
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

    # ---- Truncated-distribution transparency ------------------------------
    # After a normal draw the drivers are clamped to their bounds and the
    # terminal growth is capped below WACC, which piles probability mass onto
    # the boundaries: the *requested* mean/std no longer equal the *actual*
    # sample statistics. Recording both, plus the boundary hit rates, stops the
    # requested parameters from being misread as the realised sample moments.
    sample_driver_mean: Dict[str, float] = field(default_factory=dict)
    sample_driver_std: Dict[str, float] = field(default_factory=dict)
    lower_bound_hit_rate: Dict[str, float] = field(default_factory=dict)
    upper_bound_hit_rate: Dict[str, float] = field(default_factory=dict)
    gordon_constraint_hit_rate: Optional[float] = None

    # ---- P0-1: Bank-specific probability fields --------------------------
    # These are only populated by ``run_bank`` (financial institutions). The
    # ordinary DCF MC leaves them as ``None`` so the report can distinguish.
    is_bank: bool = False
    book_value_per_share: Optional[float] = None
    prob_overvalued_20: Optional[float] = None       # P(intrinsic < 0.80 × price)
    prob_undervalued_20: Optional[float] = None      # P(intrinsic > 1.20 × price)
    prob_below_book: Optional[float] = None          # P(intrinsic < book value)
    prob_roe_below_ke: Optional[float] = None        # P(ROE < cost of equity)
    # Bank MC draws ROE and Ke per simulation; store sample stats for audit.
    bank_roe_mean: Optional[float] = None
    bank_roe_std: Optional[float] = None
    bank_ke_mean: Optional[float] = None
    bank_ke_std: Optional[float] = None

    def distribution_transparency_note(self) -> Optional[str]:
        """Report requested-vs-actual sample stats + boundary hit rates.

        Returns ``None`` when no in-bounds draw was recorded (nothing to show).
        """
        return _format_transparency_note(
            self.param_distributions, self.sample_driver_mean, self.sample_driver_std,
            self.lower_bound_hit_rate, self.upper_bound_hit_rate,
            self.gordon_constraint_hit_rate,
        )


def _format_transparency_note(
    param_distributions: Dict[str, Any],
    sample_mean: Dict[str, float],
    sample_std: Dict[str, float],
    lower_rate: Dict[str, float],
    upper_rate: Dict[str, float],
    gordon_rate: Optional[float],
) -> Optional[str]:
    """Format the truncated-distribution transparency line, or ``None``."""
    if not sample_mean:
        return None
    parts: List[str] = []
    for k in DRIVER_LABELS:
        if k not in sample_mean:
            continue
        req = param_distributions.get(k, {})
        lo = lower_rate.get(k)
        hi = upper_rate.get(k)
        lo_txt = f"{lo:.1%}" if lo is not None else "n/a"
        hi_txt = f"{hi:.1%}" if hi is not None else "n/a"
        parts.append(
            f"{k}: 请求 μ={req.get('mean', float('nan')):+.3f}/σ={req.get('std', float('nan')):.3f}"
            f" → 实际样本 μ={sample_mean[k]:+.3f}/σ={sample_std.get(k, float('nan')):.3f}"
            f"（下界命中 {lo_txt}，上界命中 {hi_txt}）"
        )
    if gordon_rate is not None:
        parts.append(f"Gordon 约束(g<WACC)命中 {gordon_rate:.1%}")
    return "截断分布透明度（请求分布 vs 实际样本）: " + "；".join(parts)


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
        # Equity bridge (Phase C): MC must use the SAME enterprise→equity bridge
        # as the DCF (`enterprise_to_equity`), not a bare `EV − net_debt`, so a
        # complex capital structure (minority interest / preferred / leases /
        # non-operating assets) reconciles between the MC anchor and the DCF.
        mkt = data.market
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
                    wacc, tg, shares, mkt, horizon,
                )
            return self._project_one(
                base_rev, cagr, om, wacc, tg,
                dist_params["da_ratio"], dist_params["capex_ratio"],
                dist_params["nwc_marginal_ratio"], dist_params["tax_rate"],
                shares, mkt, horizon,
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
        # Truncation transparency: collect the *used* driver values and count
        # how often each draw was clamped to a bound or capped by Gordon.
        driver_used: Dict[str, List[float]] = {k: [] for k in DRIVER_LABELS}
        lower_hits: Dict[str, int] = {k: 0 for k in DRIVER_LABELS}
        upper_hits: Dict[str, int] = {k: 0 for k in DRIVER_LABELS}
        n_gordon = 0
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
        bounds = [
            ("revenue_cagr", cagr_lo, cagr_hi),
            ("operating_margin", om_lo, om_hi),
            ("wacc", wacc_lo, wacc_hi),
            ("terminal_growth", tg_lo, tg_hi),
        ]
        for _ in range(n):
            # Correlated driver draw (growth / margin / WACC / terminal growth).
            z = self._corr_l @ self.rng.normal(0.0, 1.0, 4)
            raw = means + stds * z
            cagr = max(cagr_lo, min(cagr_hi, raw[0]))
            om = max(om_lo, min(om_hi, raw[1]))
            wacc = max(wacc_lo, min(wacc_hi, raw[2]))
            tg = max(tg_lo, min(tg_hi, raw[3]))
            for (lbl, lo, hi), rv in zip(bounds, raw):
                if rv < lo:
                    lower_hits[lbl] += 1
                elif rv > hi:
                    upper_hits[lbl] += 1
            # Gordon stability: terminal growth must stay below the discount rate.
            tg_capped = min(tg, wacc - 0.005)
            if tg_capped < tg - 1e-12:
                n_gordon += 1
            tg = tg_capped
            for lbl, val in (("revenue_cagr", cagr), ("operating_margin", om),
                             ("wacc", wacc), ("terminal_growth", tg)):
                driver_used[lbl].append(float(val))

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

        # ---- Truncation transparency (requested vs actual sample) -----------
        n_draws = len(driver_used["revenue_cagr"])
        sample_mean = {k: float(np.mean(v)) for k, v in driver_used.items() if v}
        sample_std = {k: float(np.std(v)) for k, v in driver_used.items() if v}
        lower_rate = {k: (lower_hits[k] / n_draws if n_draws else 0.0) for k in DRIVER_LABELS}
        upper_rate = {k: (upper_hits[k] / n_draws if n_draws else 0.0) for k in DRIVER_LABELS}
        gordon_rate = (n_gordon / n_draws) if n_draws else None

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
        # Truncated-distribution transparency: the requested mean/std are NOT the
        # realised sample moments once draws are clamped to their bounds.
        _trunc_note = _format_transparency_note(
            param_distributions, sample_mean, sample_std, lower_rate, upper_rate,
            gordon_rate,
        )
        if _trunc_note:
            notes.append(_trunc_note)
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
            sample_driver_mean=sample_mean,
            sample_driver_std=sample_std,
            lower_bound_hit_rate=lower_rate,
            upper_bound_hit_rate=upper_rate,
            gordon_constraint_hit_rate=gordon_rate,
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
        mkt: Any,
        horizon: int,
    ) -> Optional[float]:
        from forecasts.fcf_projection import project_enterprise_value
        from valuation.equity_bridge import enterprise_to_equity

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
        ev = getattr(proj, "enterprise_value", None)
        if ev is None:
            # Missing EV is an *invalid* draw, never a silent 0.
            return None
        eq = enterprise_to_equity(ev, mkt).equity_value
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
        mkt: Any,
        horizon: int,
    ) -> Optional[float]:
        """Project equity/share along the parametrised DCF base path.

        At ``(cagr, om) = (eff_cagr, eff_om)`` this reproduces the deterministic
        DCF base-case FCF path exactly, so the Monte-Carlo anchor reconciles.
        The enterprise→equity step uses the same bridge as the DCF (Phase C).
        """
        from forecasts.fcf_projection import gordon_terminal_value
        from forecasts.nwc_utils import forecast_nwc_change
        from valuation.equity_bridge import enterprise_to_equity

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
        eq = enterprise_to_equity(ev, mkt).equity_value
        return eq / shares if shares > 0 else None

    def _extract_stats(self, data: FinancialData, profile: Any = None):
        from forecasts.forecast import ForecastEngine
        from forecasts.nwc_utils import business_type_from_profile

        eng = ForecastEngine(business_type=business_type_from_profile(profile))
        return eng._extract_history(data)

    # ------------------------------------------------------------------
    # P0-1: Bank Monte Carlo — RIM-based, perturbing Ke and ROE
    # ------------------------------------------------------------------
    def run_bank(
        self,
        data: FinancialData,
        profile: Any,
    ) -> MonteCarloResult:
        """Bank-specific Monte Carlo via the Residual Income Model.

        Banks must NOT use the ordinary DCF Monte Carlo (revenue CAGR /
        operating margin / WACC / terminal growth are undefined for a borrowing
        business). Instead, this path perturbs the two drivers that actually
        matter for a bank:

        * **Cost of Equity (Ke)** — β perturbed around the unified CAPM exit.
        * **ROE** — TTM net income / book equity, perturbed as a relative shock.

        Each draw re-runs the RIM valuation with the perturbed (Ke, ROE) pair
        and records the per-share intrinsic value. The resulting distribution
        outputs bank-specific probability statements:
          * ``P(Intrinsic Value > Market Price)``
          * ``P(Overvalued > 20%)``  — intrinsic < 0.80 × price
          * ``P(Undervalued > 20%)`` — intrinsic > 1.20 × price
          * ``P(Value below Book Value)`` — intrinsic < book value per share
          * ``P(ROE below Cost of Equity)`` — the drawn ROE < drawn Ke

        Returns a ``MonteCarloResult`` with ``is_bank=True``. When the required
        inputs (book value, net income, β) are unavailable, returns a result
        with ``n_simulations=0`` and notes directing the report to show
        "Monte Carlo: Not Applicable — Financial Institution".
        """
        from models.bank import (
            BankRIMModel,
            _book_equity_per_share,
        )

        ttm = data.ttm
        price = data.market.current_price
        bvps = _book_equity_per_share(data)

        # ---- Pre-condition: sufficient bank data ----
        missing: List[str] = []
        if ttm is None:
            missing.append("TTM 财报")
        if ttm is not None and ttm.net_income is None:
            missing.append("TTM 净利润")
        if bvps is None or bvps <= 0:
            missing.append("每股账面价值")
        if price is None or price <= 0:
            missing.append("当前价格")

        if missing:
            return MonteCarloResult(
                n_simulations=0,
                values=[],
                percentiles={},
                mean_value=0.0,
                median_value=0.0,
                std_dev=0.0,
                notes=[
                    "Monte Carlo: Not Applicable — Financial Institution",
                    f"缺失输入：{', '.join(missing)}",
                ],
                is_bank=True,
                current_price=price,
                book_value_per_share=bvps,
            )

        # ---- Resolve base Ke and ROE (from the bank model itself) ----
        model = BankRIMModel()
        try:
            probe = model.calculate(data, profile)
        except Exception as e:  # pragma: no cover - defensive
            log.warning(f"Bank RIM base probe failed for MC: {e}")
            return MonteCarloResult(
                n_simulations=0,
                values=[],
                percentiles={},
                mean_value=0.0,
                median_value=0.0,
                notes=[
                    "Monte Carlo: Not Applicable — Financial Institution",
                    f"Bank RIM 基准求解失败: {e}",
                ],
                is_bank=True,
                current_price=price,
                book_value_per_share=bvps,
            )

        if not probe.is_success() or not probe.breakdown:
            return MonteCarloResult(
                n_simulations=0,
                values=[],
                percentiles={},
                mean_value=0.0,
                median_value=0.0,
                notes=[
                    "Monte Carlo: Not Applicable — Financial Institution",
                    f"Bank RIM 状态: {probe.status.value}",
                ],
                is_bank=True,
                current_price=price,
                book_value_per_share=bvps,
            )

        bd = probe.breakdown
        base_ke = float(bd.get("cost_of_equity", 0))
        base_roe = float(bd.get("roe", 0))
        base_beta = float(bd.get("beta", 1.0))
        payout = float(bd.get("payout", 0.0))
        horizon = int(bd.get("horizon", 5))
        risk_free = float(data.market.risk_free_rate or 0.04)
        erp = float(data.market.equity_risk_premium or 0.06)

        # Raw-vs-adjusted Ke audit: the chain is produced by the bank model's
        # own CAPM path, so the note reuses it instead of re-deriving Ke here.
        capm_chain = bd.get("capm_chain")
        ke_note = build_bank_ke_note(
            capm_chain,
            base_ke=base_ke,
            base_beta=base_beta,
            risk_free=risk_free,
            erp=erp,
        )

        if base_ke <= 0 or base_roe == 0:
            return MonteCarloResult(
                n_simulations=0,
                values=[],
                percentiles={},
                mean_value=0.0,
                median_value=0.0,
                notes=[
                    "Monte Carlo: Not Applicable — Financial Institution",
                    f"基准 Ke={base_ke:.2%} 或 ROE={base_roe:.2%} 无效",
                ],
                is_bank=True,
                current_price=price,
                book_value_per_share=bvps,
            )

        # ---- Perturbation parameters ----
        # β perturbation: ±0.30 around base (same width as the scenario analyzer).
        # ROE perturbation: ±20% relative shock (same as _FIN_ROE_SHOCK).
        beta_std = 0.15
        roe_shock_std = 0.12  # relative (multiplicative)

        # Ke and ROE are negatively correlated: when risk rises (β↑ → Ke↑),
        # ROE tends to compress (credit cycle). A mild negative correlation
        # prevents purely independent noise from producing implausible pairs.
        _BANK_CORR = np.array([
            [1.0, -0.25],   # β
            [-0.25, 1.0],   # roe shock
        ])
        corr_l = _correlation_cholesky(_BANK_CORR)

        n = self.cfg.n_simulations
        self.rng = np.random.RandomState(self.cfg.random_seed)

        all_values: List[float] = []
        roe_draws: List[float] = []
        ke_draws: List[float] = []
        n_roe_below_ke = 0
        n_below_book = 0
        n_invalid = 0

        param_distributions = {
            "beta": {
                "mean": base_beta,
                "std": beta_std,
                "lower": 0.30,
                "upper": 2.50,
            },
            "roe_shock": {
                "mean": 0.0,
                "std": roe_shock_std,
                "lower": -0.50,
                "upper": 0.50,
            },
        }

        b0 = float(bvps)
        for _ in range(n):
            z = corr_l @ self.rng.normal(0.0, 1.0, 2)
            beta_draw = max(0.30, min(2.50, base_beta + z[0] * beta_std))
            roe_shock = max(-0.50, min(0.50, z[1] * roe_shock_std))
            ke_draw = risk_free + beta_draw * erp
            roe_draw = base_roe * (1.0 + roe_shock)

            if ke_draw <= 0:
                n_invalid += 1
                continue

            # RIM: V0 = B0 + Σ (ROE_t − Ke) · B_{t−1} / (1+Ke)^t
            # ROE fades linearly to Ke over the horizon (same as BankRIMModel).
            b = b0
            pv_residual = 0.0
            for t in range(1, horizon + 1):
                roe_t = roe_draw + (ke_draw - roe_draw) * (t / horizon)
                ri_t = (roe_t - ke_draw) * b
                pv_residual += ri_t / (1.0 + ke_draw) ** t
                b = b * (1.0 + roe_t * (1.0 - payout))

            pps = b0 + pv_residual

            if not np.isfinite(pps) or pps > 1e6:
                n_invalid += 1
                continue
            if pps < 0:
                pps = 0.0

            all_values.append(pps)
            roe_draws.append(roe_draw)
            ke_draws.append(ke_draw)
            if roe_draw < ke_draw:
                n_roe_below_ke += 1
            if pps < b0:
                n_below_book += 1

        if not all_values:
            return MonteCarloResult(
                n_simulations=n,
                values=[],
                percentiles={},
                mean_value=0.0,
                median_value=0.0,
                notes=["All bank simulations produced invalid values"],
                is_bank=True,
                current_price=price,
                book_value_per_share=bvps,
                n_requested=n,
                n_invalid=n_invalid,
                random_seed=self.cfg.random_seed,
                param_distributions=param_distributions,
            )

        arr = np.array(all_values)
        percentiles = {p: float(np.percentile(arr, p)) for p in PERCENTILES}
        n_valid = len(all_values)

        # ---- Bank probability statements ----
        prob_above_price = None
        prob_overvalued_20 = None
        prob_undervalued_20 = None
        if price is not None and price > 0:
            prob_above_price = float((arr > price).mean())
            prob_overvalued_20 = float((arr < price * 0.80).mean())
            prob_undervalued_20 = float((arr > price * 1.20).mean())

        prob_below_book = n_below_book / n_valid if n_valid else None
        prob_roe_below_ke = n_roe_below_ke / n_valid if n_valid else None

        roe_arr = np.array(roe_draws)
        ke_arr = np.array(ke_draws)

        notes: List[str] = [
            f"银行 Monte Carlo（Bank RIM 模拟）: N={n}，有效 {n_valid}，无效 {n_invalid}",
            f"模式 = 权益成本 Ke 与 ROE 联合扰动（β ±{beta_std:.2f}σ，ROE 相对冲击 ±{roe_shock_std:.0%}σ）",
            "银行不使用普通企业 DCF 假设的 Monte Carlo（revenue CAGR / operating margin / "
            "WACC / terminal growth 对借贷型业务无经济含义）",
            f"基准 Ke={base_ke:.2%}（β={base_beta:.2f}），基准 ROE={base_roe:.2%}",
        ]
        if ke_note:
            notes.append(ke_note)
        if prob_above_price is not None:
            notes.append(
                f"P(内在价值 > 市场价 ${price:.2f}) = {prob_above_price:.1%}"
            )
            notes.append(f"P(高估 > 20%) = {prob_overvalued_20:.1%}")
            notes.append(f"P(低估 > 20%) = {prob_undervalued_20:.1%}")
            notes.append(f"P(内在价值 < 每股账面价值) = {prob_below_book:.1%}")
            notes.append(f"P(ROE < Ke) = {prob_roe_below_ke:.1%}")

        return MonteCarloResult(
            n_simulations=n,
            n_valid=n_valid,
            values=all_values,
            percentiles=percentiles,
            mean_value=float(arr.mean()),
            median_value=float(np.median(arr)),
            std_dev=float(arr.std()),
            assumptions={
                "base_ke": base_ke,
                "base_roe": base_roe,
                "base_beta": base_beta,
                "payout": payout,
                "horizon": horizon,
                "bvps": b0,
            },
            current_price=price,
            prob_above_price=prob_above_price,
            is_bank=True,
            book_value_per_share=b0,
            prob_overvalued_20=prob_overvalued_20,
            prob_undervalued_20=prob_undervalued_20,
            prob_below_book=prob_below_book,
            prob_roe_below_ke=prob_roe_below_ke,
            mode="bank_rim",
            random_seed=self.cfg.random_seed,
            n_requested=n,
            n_invalid=n_invalid,
            n_truncated=0,
            param_distributions=param_distributions,
            bank_roe_mean=float(roe_arr.mean()),
            bank_roe_std=float(roe_arr.std()),
            bank_ke_mean=float(ke_arr.mean()),
            bank_ke_std=float(ke_arr.std()),
            notes=notes,
        )


def build_bank_ke_note(
    chain: Optional[Dict[str, Any]],
    *,
    base_ke: Optional[float],
    base_beta: Optional[float],
    risk_free: Optional[float],
    erp: Optional[float],
    selection_method: Optional[str] = None,
) -> Optional[str]:
    """Render the raw-vs-adjusted CAPM cost-of-equity audit line for bank MC.

    Compares ``raw_capm_ke`` (Rf + raw_beta x ERP, unmodified) against the Ke the
    valuation actually consumed (``base_ke``), both on the *same* Rf/ERP basis.
    Returns ``None`` - never a fabricated line - when the inputs are missing,
    non-finite, or mutually inconsistent (a mismatch means the chain does not
    describe the Ke the simulation used, so any difference would be misleading).
    """
    if not chain or not isinstance(chain, dict):
        return None

    def _finite(x: Any) -> Optional[float]:
        try:
            v = float(x)
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) else None

    raw_beta = _finite(chain.get("raw_beta"))
    used_beta = _finite(chain.get("valuation_beta"))
    raw_ke = _finite(chain.get("raw_capm_ke"))
    rf = _finite(chain.get("risk_free_rate"))
    prem = _finite(chain.get("equity_risk_premium"))
    used_ke = _finite(base_ke)

    if None in (raw_beta, used_beta, raw_ke, rf, prem, used_ke):
        return None

    # Optional cross-check inputs must be finite when supplied; NaN/inf would
    # make the comparisons below vacuously pass (NaN != NaN), so reject them.
    optional = {"base_beta": base_beta, "risk_free": risk_free, "erp": erp}
    for name, value in optional.items():
        if value is not None and _finite(value) is None:
            return None

    mc_beta = _finite(base_beta)

    # The chain must describe the same Ke basis the simulation drew from.
    if abs((rf + used_beta * prem) - used_ke) > 1e-9:
        return None
    if mc_beta is not None and abs(mc_beta - used_beta) > 1e-9:
        return None
    if risk_free is not None and erp is not None:
        if abs(float(risk_free) - rf) > 1e-9 or abs(float(erp) - prem) > 1e-9:
            return None

    # ---- Three-layer Ke decomposition (raw → selected → used) --------------
    # Only rendered when the chain actually carries the normalization layer.
    # A chain that claims shrinkage/clamping but omits the intermediate Ke
    # cannot support a per-layer split, so we fall back to the total-only line
    # rather than inventing a 0 bps "beta adjustment".
    selected_beta = _finite(chain.get("beta_selected"))
    if selected_beta is None:
        selected_beta = _finite(chain.get("normalized_beta"))
    selected_ke = _finite(chain.get("normalized_ke"))
    layered = selected_beta is not None and selected_ke is not None

    # When the bank ke band fired, ``valuation_beta`` is NOT a selection result:
    # it is the beta implied by the clamped Ke, i.e. (used_ke − Rf)/ERP. Report
    # it under its own name so the clamp is never attributed to beta selection.
    clamp_equiv = _finite(chain.get("clamp_equivalent_beta"))
    if clamp_equiv is None and layered and abs(used_beta - selected_beta) > 1e-9:
        clamp_equiv = used_beta
    clamped = clamp_equiv is not None and abs(clamp_equiv - selected_beta) > 1e-9

    diff_bps = (used_ke - raw_ke) * 10000.0

    if layered:
        beta_adj_bps = (selected_ke - raw_ke) * 10000.0
        clamp_bps = (used_ke - selected_ke) * 10000.0
        # The intermediate Ke must be the CAPM Ke of the selected beta, else the
        # chain is internally inconsistent (e.g. a stale normalized_ke) and the
        # per-layer split would attribute bps to the wrong cause.
        if abs(selected_ke - (rf + selected_beta * prem)) > 1e-9:
            return None
    else:
        beta_adj_bps = clamp_bps = 0.0

    reasons: List[str] = []
    norm = str(chain.get("normalization_method") or "none")
    if "blume_shrinkage" in norm:
        reasons.append("Blume 收缩")
    if "winsorize" in norm:
        reasons.append("β 截断")
    reason_text = str(chain.get("valuation_beta_reason") or "")
    if "bank ke band" in reason_text:
        reasons.append("银行 Ke 区间夹紧")
    if selection_method:
        reasons.append(f"β 选择={selection_method}")
    if not reasons:
        reasons.append("未调整" if abs(diff_bps) < 1e-6 else "调整原因未记录")

    method = selection_method or str(chain.get("raw_beta_source") or "未记录")
    if layered and clamped:
        # The selected beta is the pre-clamp value; the used beta is a derived
        # equivalent and must not be labelled with the selection method.
        base = (
            f"CAPM Ke 溯源：原始 β={raw_beta:.3f} → 选定 β={selected_beta:.3f}"
            f"（选择方法={method}）｜原始 CAPM Ke={raw_ke:.2%} → 采用 Ke={used_ke:.2%}"
            f"（夹紧等效 β={clamp_equiv:.3f}，由 Ke 反推，非选择结果）"
            f"｜差异 {diff_bps:+.1f} bps（采用 Ke − 原始 Ke）"
        )
    else:
        base = (
            f"CAPM Ke 溯源：原始 β={raw_beta:.3f} → 采用 β={used_beta:.3f}"
            f"（选择方法={method}）｜原始 CAPM Ke={raw_ke:.2%} → 采用 Ke={used_ke:.2%}"
            f"｜差异 {diff_bps:+.1f} bps（采用 Ke − 原始 Ke）"
        )
    if layered:
        base += (
            f"｜分层：β 调整 {beta_adj_bps:+.1f} bps（原始 β={raw_beta:.3f}→选定 β={selected_beta:.3f}，"
            f"选定 Ke={selected_ke:.2%}）+ 银行 Ke 区间夹紧 {clamp_bps:+.1f} bps"
        )
    # Rf provenance: an assumed default must be visible, never implied as market
    # data (spec: every CAPM input carries a source).
    rf_src = str(chain.get("risk_free_source") or "")
    if rf_src.startswith("assumed"):
        base += f"｜⚠ Rf={rf:.2%} 为假定默认（{rf_src}），非市场实测"
    return base + f"｜说明：{'；'.join(reasons)}"


__all__ = [
    "MonteCarloSimulator",
    "MonteCarloResult",
    "MODE_BASE_CASE",
    "MODE_HISTORICAL",
    "DRIVER_LABELS",
    "build_bank_ke_note",
]
