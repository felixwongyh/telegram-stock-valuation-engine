"""
models/unit_economics.py - Unit-economics-anchored EV/Sales for capital-intensive build-outs

Why this model exists
---------------------
For a capital-intensive compute build-out (AI cloud / GPU infrastructure /
neocloud) that is still pre-profit, the standard toolkit collapses:

    * DCF          → explicit-period FCF is deeply negative, so the point value
                     is almost entirely a terminal-value assumption.
    * P/E          → no positive earnings to anchor on.
    * EV/EBITDA    → EBITDA is dominated by the D&A add-back (capital deployed
                     ahead of monetisation), so the multiple is not comparable.

The plain `EV/Sales` model still *applies* (revenue is positive), but it prices
the whole company off a single static peer multiple and ignores the central
fact of the build-out: **how much revenue-generating capacity has already been
installed but not yet monetised**. That is the unit-economics question a neocloud
analyst actually asks — utilisation (GPU 稼动率) × price (ARPU) at maturity.

Construction
------------
The model values the *deployed asset base at its mature unit economics*, then
discounts for the time still needed to ramp utilisation to the mature level:

    deployed_capital   = Σ capex − Σ D&A            (net PP&E proxy — the fleet)
    current_yield      = TTM revenue / deployed_capital   (observable ARPU×util proxy)
    capacity_revenue   = max(TTM revenue, deployed_capital × BENCHMARK_REVENUE_YIELD)
    utilisation_gap    = clamp(1 − current_yield / BENCHMARK_REVENUE_YIELD, 0, 1)
    ramp_discount      = (1 + WACC) ^ −(RAMP_YEARS × utilisation_gap)
    EV                 = capacity_revenue × MATURE_EV_SALES × ramp_discount
    equity             = EV − net debt
    value_per_share    = equity / shares

Economic reading
----------------
* `BENCHMARK_REVENUE_YIELD` (revenue per $ of net PP&E at maturity, ≈0.35) is the
  unit-economics anchor for a mature datacenter / cloud operator — it plays the
  role of "ARPU × utilisation" in a single observable ratio.
* `MATURE_EV_SALES` is the EV/Sales a *mature*, moderate-growth infrastructure
  operator earns once utilisation has ramped; it is deliberately conservative
  (capital-heavy models trade at a fraction of asset-light SaaS).
* `WACC` (reused from the unified 7-step calculator) prices the ramp risk — the
  same β / cost-of-capital the rest of the report reads.

No GPU-level utilisation or ARPU field exists in the data layer, so the yield
ratio is an explicitly *derived proxy*. The result is therefore returned as
`SolverStatus.APPROXIMATE`, never SOLVED.

This is intentionally a *coverage* model: it gives an asset-heavy pre-profit
name a third/fourth economically-grounded survivor instead of relying on a
down-weighted DCF.
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from config import (
    DEFAULT_DCF_CONFIG,
    ModelName,
    SolverStatus,
    get_logger,
)
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult
from valuation.equity_bridge import enterprise_to_equity
from valuation.wacc import WaccCalculator

log = get_logger("models.unit_economics")


class UnitEconomicsSalesModel(ValuationModel):
    """Unit-economics-justified EV/Sales for capital-intensive build-outs."""

    NAME = ModelName.UNIT_ECON_SALES

    # Below this capex/revenue ratio the company is not a capital-intensive
    # build-out and the unit-economics construction is not the right lens.
    MIN_CAPEX_RATIO: float = 0.50
    # Revenue a mature datacenter / cloud operator generates per $1 of net PP&E.
    # (ARPU × utilisation, expressed as an asset productivity ratio; Equinix /
    # Digital Realty anchor ≈ 0.25–0.35.)
    BENCHMARK_REVENUE_YIELD: float = 0.35
    # EV/Sales a mature infrastructure operator earns once utilisation has ramped.
    MATURE_EV_SALES: float = 4.0
    # Years of utilisation ramp from the current (pre-profit) level to mature.
    RAMP_YEARS: float = 3.0

    _SENSITIVITY_YIELDS: Tuple[float, ...] = (0.25, 0.35, 0.50)
    _SENSITIVITY_RAMP_YEARS: Tuple[float, ...] = (2.0, 3.0, 5.0)

    def __init__(self) -> None:
        super().__init__()
        self._wacc_calc = WaccCalculator(config=DEFAULT_DCF_CONFIG)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _shares(data: FinancialData) -> Optional[float]:
        shares = data.market.shares_outstanding
        if shares is None and data.ttm is not None:
            shares = data.ttm.shares_outstanding
        return float(shares) if shares else None

    @staticmethod
    def _capex_ratio(data: FinancialData) -> Optional[float]:
        ttm = data.ttm
        if ttm is None or not ttm.revenue or ttm.revenue <= 0 or ttm.capex is None:
            return None
        return abs(float(ttm.capex)) / float(ttm.revenue)

    @staticmethod
    def _accumulated(data: FinancialData) -> Tuple[float, float]:
        """Return (Σ capex, Σ D&A) over the available annual history."""
        acc_capex = 0.0
        acc_da = 0.0
        for s in (data.annual_income or []):
            if s.capex is not None:
                acc_capex += abs(float(s.capex))
            if s.depreciation_amortization is not None:
                acc_da += abs(float(s.depreciation_amortization))
        return acc_capex, acc_da

    @staticmethod
    def _is_build_out(data: FinancialData, profile: Any) -> bool:
        """Pre-profit / high-growth build-out that cash-flow models mishandle."""
        ttm = data.ttm
        neg_fcf = bool(ttm and ttm.free_cash_flow is not None and ttm.free_cash_flow < 0)
        neg_ni = bool(ttm and ttm.net_income is not None and ttm.net_income < 0)
        high_growth = bool(profile and getattr(profile, "growth_profile", "") == "High Growth")
        return neg_fcf or neg_ni or high_growth

    # --------------------------------------------------------------- interface
    def applicability_check(
        self, data: FinancialData, profile: Any
    ) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        if profile is not None and getattr(profile, "is_financial_institution", False):
            reasons.append("Unit-economics EV/Sales is not meaningful for financial institutions")
        if profile is not None and getattr(profile, "is_reit", False):
            reasons.append("REITs are valued on NAV/FFO, not unit-economics EV/Sales")
        if self._shares(data) is None:
            reasons.append("Shares outstanding required for EV/Sales (Unit Econ)")
        ttm = data.ttm
        if ttm is None or not ttm.revenue or ttm.revenue <= 0:
            reasons.append("Unit-economics EV/Sales requires positive revenue")
        ratio = self._capex_ratio(data)
        if ratio is None or ratio < self.MIN_CAPEX_RATIO:
            reasons.append(
                "Unit-economics EV/Sales requires a capital-intensive build-out "
                f"(capex/revenue ≥ {self.MIN_CAPEX_RATIO:.0%})"
            )
        acc_capex, acc_da = self._accumulated(data)
        if acc_capex - acc_da <= 0:
            reasons.append(
                "No net deployed asset base reconstructable from capex history (Σ capex ≤ Σ D&A)"
            )
        if not self._is_build_out(data, profile):
            reasons.append(
                "Unit-economics EV/Sales is for pre-profit / high-growth build-outs "
                "(cash-flow models remain the primary anchor here)"
            )
        return (len(reasons) == 0, reasons)

    def calculate(self, data: FinancialData, profile: Any, **kwargs) -> ValuationResult:
        shares = self._shares(data)
        if shares is None or shares <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Shares outstanding missing"],
                data_quality_score=data.quality.data_quality_score,
            )

        ttm = data.ttm
        revenue = float(ttm.revenue) if ttm and ttm.revenue else 0.0
        if revenue <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Unit-economics EV/Sales requires positive revenue"],
                data_quality_score=data.quality.data_quality_score,
            )

        acc_capex, acc_da = self._accumulated(data)
        deployed_capital = acc_capex - acc_da
        if deployed_capital <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=[
                    f"Net deployed asset base not reconstructable "
                    f"(Σ capex {acc_capex:,.0f} ≤ Σ D&A {acc_da:,.0f})"
                ],
                data_quality_score=data.quality.data_quality_score,
            )

        benchmark_yield = float(
            kwargs.get("benchmark_yield", self.BENCHMARK_REVENUE_YIELD)
        )
        if benchmark_yield <= 0:
            benchmark_yield = self.BENCHMARK_REVENUE_YIELD
        mature_ev_sales = float(kwargs.get("mature_ev_sales", self.MATURE_EV_SALES))
        if mature_ev_sales <= 0:
            mature_ev_sales = self.MATURE_EV_SALES
        ramp_years = float(kwargs.get("ramp_years", self.RAMP_YEARS))

        wacc_bd = self._wacc_calc.calculate(data, profile)
        wacc = float(wacc_bd.wacc)

        current_yield = revenue / deployed_capital
        capacity_revenue = max(revenue, deployed_capital * benchmark_yield)
        utilisation_gap = max(0.0, min(1.0, 1.0 - current_yield / benchmark_yield))
        effective_ramp_years = ramp_years * utilisation_gap
        ramp_discount = (1.0 + wacc) ** (-effective_ramp_years) if wacc > -1.0 else 1.0

        enterprise_value = capacity_revenue * mature_ev_sales * ramp_discount
        # EV → Equity via the shared bridge (net debt + minority interest +
        # preferred + leases − non-operating assets), not a bare net-debt line.
        bridge = enterprise_to_equity(enterprise_value, data.market)
        net_debt = bridge.net_debt
        equity_value = bridge.equity_value
        if equity_value is None or equity_value <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=[
                    "Unit-economics equity value unavailable/non-positive"
                    + (f" (${equity_value:,.0f})" if equity_value is not None else "")
                    + " — capacity value at maturity does not cover liabilities"
                ] + bridge.notes,
                data_quality_score=data.quality.data_quality_score,
            )

        value_per_share = equity_value / shares

        sens: List[Tuple[float, float, float]] = []
        for y in self._SENSITIVITY_YIELDS:
            cap_rev = max(revenue, deployed_capital * y)
            gap = max(0.0, min(1.0, 1.0 - current_yield / y)) if y > 0 else 1.0
            for ry in self._SENSITIVITY_RAMP_YEARS:
                disc = (1.0 + wacc) ** (-(ry * gap))
                ev = cap_rev * mature_ev_sales * disc
                eq = enterprise_to_equity(ev, data.market).equity_value
                if eq is not None and eq > 0:
                    sens.append((round(y, 2), round(ry, 1), round(eq / shares, 2)))

        assumptions = [
            ValuationAssumption("Deployed Capital (Σ capex − Σ D&A)", round(deployed_capital, 2), "USD",
                                "Net PP&E proxy — installed compute/equipment base"),
            ValuationAssumption("Current Revenue Yield", round(current_yield, 4), "x",
                                "TTM revenue / deployed capital (observable ARPU×utilisation proxy)"),
            ValuationAssumption("Benchmark Revenue Yield", round(benchmark_yield, 3), "x",
                                "Mature revenue per $ of net PP&E (datacenter/cloud anchor)"),
            ValuationAssumption("Capacity Revenue at Maturity", round(capacity_revenue, 2), "USD",
                                "max(TTM revenue, deployed capital × benchmark yield)"),
            ValuationAssumption("Mature EV/Sales", round(mature_ev_sales, 2), "x",
                                "EV/Sales of a mature infrastructure operator"),
            ValuationAssumption("Utilisation Gap", round(utilisation_gap, 3), "x",
                                "1 − current yield / benchmark yield (0 = fully monetised)"),
            ValuationAssumption("Effective Ramp Years", round(effective_ramp_years, 2), "years",
                                "RAMP_YEARS × utilisation gap"),
            ValuationAssumption("WACC (ramp discount)", round(wacc, 4), "%",
                                wacc_bd.sources.get("WACC (final)", "7-step CAPM + D/E")),
            ValuationAssumption("Ramp Discount", round(ramp_discount, 4), "x",
                                "(1 + WACC) ^ −effective_ramp_years"),
            ValuationAssumption("Net Debt", round(net_debt, 2), "USD", "Total debt − cash"),
        ]

        notes = [
            f"Unit-economics EV/Sales per Share = capacity revenue ${capacity_revenue:,.0f} "
            f"× {mature_ev_sales:g}x mature EV/Sales × {ramp_discount:.3f} ramp discount "
            f"= ${enterprise_value:,.0f} EV → ${value_per_share:,.2f}",
            f"资产基础产品率：当前营收/净 PP&E = {current_yield:.2%}（成熟基准 {benchmark_yield:.0%}）；"
            f"产能利用率缺口 {utilisation_gap:.0%} → 需 {effective_ramp_years:.1f} 年爬坡",
            f"隐含当期 EV/Sales ≈ {enterprise_value / revenue:.1f}x"
            if revenue > 0 else "隐含当期 EV/Sales N/A",
            "单位经济学（单位资产营收 = 稼动率 × ARPU 代理）锚定 EV/Sales：不依赖当期 FCF/盈利，"
            "适用于重资本·高增长·亏损期的算力/设备建设期标的",
            f"EV→Equity 桥接: {bridge.itemized_note()}",
            "⚠️ APPROXIMATE: 数据层无 GPU 稼动率 / ARPU 明细字段，单位资产营收为派生代理，"
            "结果为方向性参考",
        ]
        notes.extend(bridge.notes)
        if data.market.current_price:
            gap_pct = (value_per_share - data.market.current_price) / data.market.current_price
            notes.append(f"Current price vs Unit-econ EV/Sales: {gap_pct:+.1%}")

        breakdown = {
            "deployed_capital": deployed_capital,
            "accumulated_capex": acc_capex,
            "accumulated_da": acc_da,
            "current_revenue_yield": current_yield,
            "benchmark_revenue_yield": benchmark_yield,
            "capacity_revenue": capacity_revenue,
            "mature_ev_sales": mature_ev_sales,
            "utilisation_gap": utilisation_gap,
            "effective_ramp_years": effective_ramp_years,
            "ramp_discount": ramp_discount,
            "wacc": wacc,
            "wacc_breakdown": wacc_bd,
            "enterprise_value": enterprise_value,
            "net_debt": net_debt,
            "equity_bridge": bridge.adjustments,
            "equity_value": equity_value,
            "shares_outstanding": shares,
            "implied_ev_sales": enterprise_value / revenue if revenue > 0 else None,
            "sensitivity": sens,
            "value_per_share": value_per_share,
        }

        return ValuationResult(
            model_name=self.model_name,
            status=SolverStatus.APPROXIMATE,
            value_per_share=value_per_share,
            enterprise_value=enterprise_value,
            equity_value=equity_value,
            assumptions=assumptions,
            notes=notes,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
        )


__all__ = ["UnitEconomicsSalesModel"]
