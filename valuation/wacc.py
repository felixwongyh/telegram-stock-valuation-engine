"""
valuation/wacc.py - Dynamic WACC Calculator
Based on CAPM + Implied Cost of Debt + Effective Tax Rate + Industry Sanity Check.

Input:  FinancialData (MarketData + TTM statements + 3y annuals + sector/industry)
Output: WaccBreakdown (ke, kd, tax, we, wd, wacc, industry_range, sanity_status, sources)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from config import (
    DEFAULT_DCF_CONFIG,
    DCFConfig,
    get_logger,
)
from data.models import FinancialData

log = get_logger("valuation.wacc")


# Industry WACC ranges (Damodaran Jan 2025 US market approximations)
# Format: { Industry_Keyword_Substring: (min_wacc, max_wacc, sector_name) }
INDUSTRY_WACC_RANGES: Dict[str, Tuple[float, float, str]] = {
    "Semiconductor":    (0.085, 0.120, "Semiconductors"),
    "Software":         (0.080, 0.115, "Software"),
    "Internet":         (0.085, 0.120, "Internet Content"),
    "Consumer Electronics": (0.075, 0.105, "Consumer Electronics"),
    "Technology":       (0.075, 0.105, "Technology (general)"),
    "REIT":             (0.060, 0.090, "REITs"),
    "Real Estate":      (0.060, 0.090, "Real Estate"),
    "Bank":             (0.070, 0.100, "Banks"),
    "Insurance":        (0.075, 0.105, "Insurance"),
    "Financial":        (0.070, 0.100, "Financial Services"),
    "Utility":          (0.055, 0.080, "Utilities"),
    "Energy":           (0.070, 0.100, "Energy"),
    "Oil":              (0.070, 0.100, "Oil & Gas"),
    "Health":           (0.075, 0.105, "Healthcare"),
    "Pharma":           (0.075, 0.105, "Pharmaceuticals"),
    "Retail":           (0.070, 0.100, "Retail"),
    "Auto":             (0.075, 0.105, "Automotive"),
    "Media":            (0.075, 0.105, "Media"),
    "Telecom":          (0.065, 0.090, "Telecom Services"),
    "Communications":   (0.065, 0.090, "Communications"),
    "Industrial":       (0.070, 0.095, "Industrials"),
    "Industrials":      (0.070, 0.095, "Industrials"),
    "Logistics":        (0.070, 0.095, "Air Freight & Logistics"),
    "Parcel":           (0.070, 0.095, "Air Freight & Logistics"),
    "Freight":          (0.070, 0.095, "Air Freight & Logistics"),
    "Transportation":   (0.070, 0.095, "Transportation"),
    "Shipping":         (0.070, 0.095, "Transportation"),
    "Conglomerate":     (0.070, 0.095, "Conglomerates"),
}

DEFAULT_INDUSTRY_RANGE: Tuple[float, float, str] = (0.065, 0.115, "Market Average")


@dataclass
class WaccBreakdown:
    """Fully auditable WACC breakdown. All rates are decimals (0.08 = 8%)."""
    wacc: float
    cost_of_equity: float
    cost_of_debt: float
    after_tax_cost_of_debt: float
    effective_tax_rate: float
    weight_equity: float
    weight_debt: float
    total_debt: float
    market_cap: float
    enterprise_value: float
    risk_free_rate: float
    equity_risk_premium: float
    beta: float
    industry_range_min: float
    industry_range_max: float
    industry_label: str
    sanity_status: str  # "Within Range" | "Below Range" | "Above Range" | "Unknown"
    sources: Dict[str, str] = field(default_factory=dict)  # field → how it was computed
    cost_of_debt_implied_raw: Optional[float] = None  # before Rf floor / cap (audit)

    def sanity_message(self) -> str:
        if self.sanity_status == "Within Range":
            return (f"Calculated WACC = {self.wacc:.2%}  —  within industry range "
                    f"{self.industry_range_min:.2%} ~ {self.industry_range_max:.2%} "
                    f"（{self.industry_label}）")
        if self.sanity_status == "Below Range":
            return (f"⚠ Calculated WACC = {self.wacc:.2%}  —  below industry range "
                    f"{self.industry_range_min:.2%} ~ {self.industry_range_max:.2%}. "
                    "Consider checking Beta / Cost of Debt assumptions.")
        if self.sanity_status == "Above Range":
            return (f"⚠ Calculated WACC = {self.wacc:.2%}  —  above industry range "
                    f"{self.industry_range_min:.2%} ~ {self.industry_range_max:.2%}. "
                    "Consider checking Beta / Cost of Debt assumptions.")
        return f"Calculated WACC = {self.wacc:.2%}  (industry range unknown)"

    def formatted_sanity_check(self) -> str:
        """严格按照用户要求的 Sanity Check 输出格式：
        Calculated WACC       XX.XX%
        Industry Range        YY.YY% - ZZ.ZZ%
        """
        wacc_pct = f"{self.wacc * 100:.2f}%"
        range_pct = f"{self.industry_range_min * 100:.2f}% - {self.industry_range_max * 100:.2f}%"
        label_line = f"（{self.industry_label}）" if self.industry_label else ""
        lines = [
            f"Calculated WACC       {wacc_pct}",
            f"Industry Range        {range_pct} {label_line}".rstrip(),
        ]
        if self.sanity_status != "Within Range":
            lines.append(f"Sanity Status         ⚠ {self.sanity_status}")
        else:
            lines.append(f"Sanity Status         ✅ {self.sanity_status}")
        return "\n".join(lines)

    def step_by_step_summary(self) -> str:
        """7步WACC计算流程汇总输出（全审计追踪）"""
        lines = [
            "── WACC 7-Step Calculation ──",
            f"Step 1 - Risk Free Rate (Rf)     : {self.risk_free_rate*100:.2f}%    [{self.sources.get('Rf', self.sources.get('risk_free_rate', 'N/A'))}]",
            f"Step 2 - Beta (β)                 : {self.beta:.3f}       [{self.sources.get('β', self.sources.get('beta', 'N/A'))}]",
            f"Step 3 - Equity Risk Premium (ERP): {self.equity_risk_premium*100:.2f}%    [{self.sources.get('ERP', self.sources.get('equity_risk_premium', 'N/A'))}]",
            f"Step 4 - Cost of Equity (CAPM)    : {self.cost_of_equity*100:.2f}%    [{self.sources.get('ke', self.sources.get('cost_of_equity', 'CAPM'))}]",
            f"Step 5 - Cost of Debt (pre-tax)   : {self.cost_of_debt*100:.2f}%    [{self.sources.get('kd (pre-tax)', self.sources.get('cost_of_debt', 'N/A'))}]",
            f"Step 6 - After-tax Cost of Debt   : {self.after_tax_cost_of_debt*100:.2f}%    [ETR={self.effective_tax_rate*100:.2f}%  {self.sources.get('ETR', self.sources.get('effective_tax_rate', 'N/A'))}]",
            f"Step 7 - Capital Structure + WACC  : E/(D+E)={self.weight_equity*100:.1f}%  D/(D+E)={self.weight_debt*100:.1f}%",
            f"         → WACC = E%·ke + D%·kd·(1−t) = {self.wacc*100:.2f}%",
            "",
            self.formatted_sanity_check(),
        ]
        return "\n".join(lines)


class WaccCalculator:
    """Auditable bottom-up WACC calculator with:

    - Cost of Equity (CAPM):  ke = Rf + β×ERP
    - Cost of Debt (Implied): kd = TTM InterestExpense / Avg(TotalDebt[t], TotalDebt[t-1])
      → fallback to synthetic credit rating based on interest coverage
    - Effective Tax Rate (TTM / 3y avg): ETR = IncomeTax / (EBIT - InterestExpense)
      → fallback to DCFConfig default
    - Weights (market-value): E = market cap, D = latest total debt
    - Industry sanity check via INDUSTRY_WACC_RANGES fuzzy match on sector/industry
    """

    def __init__(self, config: DCFConfig = DEFAULT_DCF_CONFIG) -> None:
        self.cfg = config

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------
    def calculate(self, data: FinancialData, profile: Any = None) -> WaccBreakdown:
        mkt = data.market
        sources: Dict[str, str] = {}

        # 1. Risk-Free Rate — priority order:
        #    (a) Injected via data.market.risk_free_rate (e.g. Yahoo Finance ^TNX)
        #    (b) REAL-TIME 10Y U.S. Treasury from TreasuryYieldProvider (treasury.gov CSV)
        #    (c) DCFConfig default constant
        rf = getattr(mkt, "risk_free_rate", None)
        rf_src_tag = ""
        if rf and 0.005 < rf < 0.15:
            rf_src_tag = f"MarketData injected (10Y approx) ({rf:.3%})"
            sources["Rf"] = rf_src_tag
        else:
            # Try TreasuryYieldProvider — download/cache from home.treasury.gov
            try:
                from data.providers import TreasuryYieldProvider
                tp = TreasuryYieldProvider()
                curve = tp.get_yield_curve()
                t10 = (curve or {}).get("rates", {}).get("10 Yr") if curve else None
                if t10 is not None and 0.005 < float(t10) < 0.15:
                    rf = float(t10)
                    as_of = (curve or {}).get("as_of_date", "")
                    src_extra = f" (as_of {as_of})" if as_of else ""
                    rf_src_tag = (
                        f"U.S. Treasury 10Y Par Yield {rf:.3%}"
                        f" via home.treasury.gov CSV{src_extra}"
                    )
                    sources["Rf"] = rf_src_tag
            except Exception as e:
                log.info(f"TreasuryYieldProvider lookup failed (non-fatal): {e}")
            # Fallback to DCFConfig default if still no value
            if rf is None or not (0.005 < rf < 0.15):
                rf = self.cfg.risk_free_rate
                rf_src_tag = f"Default constant fallback ({rf:.3%})"
                sources["Rf"] = rf_src_tag

        # 2. Equity Risk Premium — injected via MarketData or DCFConfig default
        erp = getattr(mkt, "equity_risk_premium", None)
        if erp and 0.02 < erp < 0.12:
            sources["ERP"] = f"Injected ({erp:.2%})"
        else:
            erp = self.cfg.equity_risk_premium
            sources["ERP"] = f"Default constant ({erp:.2%})"

        # 3. Beta (MarketData estimate from 3Y monthly returns vs SPY, fallback to 1.1)
        beta_raw = mkt.beta
        if beta_raw is None:
            beta = self.cfg.default_unlevered_beta
            sources["β"] = f"Fallback unlevered beta ({beta:.2f})"
        else:
            # Winsorize β ∈ [0.3, 3.0]
            beta = max(0.3, min(3.0, float(beta_raw)))
            sources["β"] = f"3Y monthly vs SPY estimate = {beta_raw:.3f} (winsorized to [{min(0.3,beta):.1f}, {max(3.0,beta):.1f}])"

        # 4. Cost of Equity (CAPM)
        ke = rf + beta * erp
        sources["ke"] = f"CAPM = {rf:.2%} + {beta:.3f}×{erp:.2%} = {ke:.3%}"

        # 5. Implied Cost of Debt
        kd_raw, src_kd = self._implied_cost_of_debt(data)
        kd, kd_src = self._apply_cost_of_debt_clamp(kd_raw, rf, src_kd)
        sources["kd (pre-tax)"] = kd_src
        sources["kd (implied raw)"] = src_kd

        # 6. Effective Tax Rate
        etr, src_etr = self._effective_tax_rate(data)
        etr = max(0.0, min(0.50, etr))  # clamp to sensible 0%~50%
        sources["ETR"] = src_etr

        kd_after_tax = kd * (1 - etr)
        sources["kd (after-tax)"] = f"{kd:.3%} × (1 - {etr:.3%}) = {kd_after_tax:.3%}"

        # 7. Capital Structure Weights (market values)
        E = mkt.market_cap
        if E is None or E <= 0:
            price = mkt.current_price or 0
            sh = mkt.shares_outstanding or 0
            E = max(1.0, price * sh)
            sources["E (Market Cap)"] = f"Estimated from Price×Shares = {E:,.0f} (chart.meta fallback)"
        else:
            sources["E (Market Cap)"] = f"{E:,.0f}"

        D = mkt.total_debt or 0.0
        if D <= 0:
            sources["D (Total Debt)"] = "0 (unlevered; using 1×E minimum for stability)"
            D = 0.0
        else:
            sources["D (Total Debt)"] = f"{D:,.0f}"

        V = E + D
        we = E / V if V > 0 else 1.0
        wd = D / V if V > 0 else 0.0
        sources["Weights"] = f"E/(D+E) = {we:.2%}, D/(D+E) = {wd:.2%}"

        # 8. WACC = We×Ke + Wd×Kd×(1-t)
        wacc_raw = we * ke + wd * kd_after_tax
        wacc = max(self.cfg.min_wacc, min(self.cfg.max_wacc, wacc_raw))
        if wacc != wacc_raw:
            sources["WACC (final)"] = (
                f"{we:.4f}×{ke:.4f} + {wd:.4f}×{kd_after_tax:.4f} = {wacc_raw:.4%}"
                f"  →  clamped to [{self.cfg.min_wacc:.2%}, {self.cfg.max_wacc:.2%}] → {wacc:.4%}"
            )
        else:
            sources["WACC (final)"] = f"{we:.4f}×{ke:.4f} + {wd:.4f}×{kd_after_tax:.4f} = {wacc:.4%}"

        # 9. Industry Sanity Check
        lo, hi, label = self._match_industry_range(
            mkt.sector, mkt.industry, mkt.company_name
        )
        if wacc < lo:
            sanity = "Below Range"
        elif wacc > hi:
            sanity = "Above Range"
        else:
            sanity = "Within Range"

        return WaccBreakdown(
            wacc=wacc,
            cost_of_equity=ke,
            cost_of_debt=kd,
            cost_of_debt_implied_raw=kd_raw,
            after_tax_cost_of_debt=kd_after_tax,
            effective_tax_rate=etr,
            weight_equity=we,
            weight_debt=wd,
            total_debt=D,
            market_cap=E,
            enterprise_value=V,
            risk_free_rate=rf,
            equity_risk_premium=erp,
            beta=beta,
            industry_range_min=lo,
            industry_range_max=hi,
            industry_label=label,
            sanity_status=sanity,
            sources=sources,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_cost_of_debt_clamp(
        kd_raw: float, rf: float, implied_source: str
    ) -> Tuple[float, str]:
        """Floor at Rf+50bp and cap at 25%; audit text must match ``cost_of_debt``."""
        kd_floor = rf + 0.005
        kd_cap = 0.25
        kd = max(kd_floor, min(kd_cap, kd_raw))
        if abs(kd - kd_raw) < 1e-8:
            return kd, implied_source
        if kd_raw < kd_floor:
            return (
                kd,
                f"{implied_source}; WACC uses floor Rf+0.5% = {kd_floor:.3%} "
                f"(implied {kd_raw:.3%} < floor)",
            )
        return (
            kd,
            f"{implied_source}; WACC uses cap {kd_cap:.3%} "
            f"(implied {kd_raw:.3%} > cap)",
        )

    @classmethod
    def _implied_cost_of_debt(cls, data: FinancialData) -> Tuple[float, str]:
        """
        Cost of Debt (pre-tax) estimation:
        Priority 1: TTM Interest_Expense / Avg(Debt[t], Debt[t-1])
        Priority 2: Synthetic credit rating from interest coverage ratio
        Priority 3: Rf + 2.5% spread
        """
        mkt = data.market
        rf = getattr(mkt, "risk_free_rate", None) or DEFAULT_DCF_CONFIG.risk_free_rate

        # Priority 1: Implied kd from TTM interest / avg debt
        ttm = data.ttm
        int_exp = None
        if ttm is not None and ttm.interest_expense is not None and ttm.interest_expense > 0:
            int_exp = float(ttm.interest_expense)
        else:
            # Fallback: latest annual interest
            if data.annual_income and data.annual_income[0].interest_expense:
                int_exp = float(data.annual_income[0].interest_expense)

        debts_over_time: List[float] = []
        for rec in data.annual_balance_sheet:
            d = rec.get("Total Debt")
            if d is not None and float(d) > 0:
                debts_over_time.append(float(d))
        if mkt.total_debt and mkt.total_debt > 0:
            debts_over_time.insert(0, float(mkt.total_debt))

        if int_exp is not None and len(debts_over_time) >= 1:
            avg_debt = mean(debts_over_time[:min(2, len(debts_over_time))])
            if avg_debt > 0:
                kd_implied = int_exp / avg_debt
                if 0.005 < kd_implied < 0.30:
                    return (
                        kd_implied,
                        (f"Implied TTM interest / avg debt = "
                         f"{int_exp:,.0f} / {avg_debt:,.0f} = {kd_implied:.3%}"),
                    )

        # Priority 2: Synthetic credit rating via TTM interest coverage
        if ttm is not None and ttm.ebit and ttm.interest_expense and ttm.interest_expense > 0:
            icr = float(ttm.ebit) / float(ttm.interest_expense)
            spread = cls._credit_spread_for_icr(icr)
            kd = rf + spread
            return (
                kd,
                (f"Synthetic rating: ICR = EBIT/Interest = {icr:.2f} → spread ≈ {spread:.2%} "
                 f"→ kd = {rf:.2%} + {spread:.2%} = {kd:.3%}"),
            )

        # Priority 3: BBB-ish default
        spread_default = 0.025
        kd = rf + spread_default
        return (
            kd,
            (f"No interest / debt data — fallback BBB-like spread {spread_default:.2%} "
             f"→ kd = {rf:.2%} + {spread_default:.2%} = {kd:.3%}"),
        )

    @staticmethod
    def _credit_spread_for_icr(icr: float) -> float:
        """Rough ICR → credit spread table (10Y US Industrial averages, indicative)."""
        if icr >= 20:   return 0.006  # AAA
        if icr >= 12:   return 0.009  # AA
        if icr >= 8:    return 0.013  # A
        if icr >= 5:    return 0.019  # BBB
        if icr >= 3:    return 0.032  # BB
        if icr >= 1.8:  return 0.050  # B
        if icr >= 1.0:  return 0.080  # CCC
        return 0.120    # distressed

    @classmethod
    def _effective_tax_rate(cls, data: FinancialData) -> Tuple[float, str]:
        """
        ETR = Σ TaxProvision / Σ (EBIT − InterestExpense)  across last 3y + TTM when available.
        """
        stmts: List[Any] = []
        if data.ttm is not None:
            stmts.append(data.ttm)
        stmts.extend(data.annual_income[:3])

        sum_tax = 0.0
        sum_ebt = 0.0
        n_used = 0
        for s in stmts:
            tax = getattr(s, "income_tax", None)
            ebit = getattr(s, "ebit", None)
            ie = getattr(s, "interest_expense", None)
            if tax is None or ebit is None:
                continue
            ebt = float(ebit) - (float(ie) if ie is not None else 0.0)
            if ebt <= 0:
                continue
            if not math_isfinite(tax) or not math_isfinite(ebt):
                continue
            sum_tax += float(tax)
            sum_ebt += ebt
            n_used += 1

        if n_used >= 1 and sum_ebt > 0:
            etr = sum_tax / sum_ebt
            if 0.0 <= etr <= 0.60:
                return (
                    etr,
                    (f"ΣTax/ΣEBT over {n_used} period(s) = "
                     f"{sum_tax:,.0f} / {sum_ebt:,.0f} = {etr:.3%}"),
                )

        default_etr = DEFAULT_DCF_CONFIG.tax_rate
        return (
            default_etr,
            (f"Insufficient tax/EBT data  →  fallback default US statutory "
             f"{default_etr:.2%}"),
        )

    @classmethod
    def _match_industry_range(
        cls,
        sector: Optional[str],
        industry: Optional[str],
        company_name: Optional[str] = None,
    ) -> Tuple[float, float, str]:
        haystack_parts: List[str] = []
        if sector: haystack_parts.append(sector)
        if industry: haystack_parts.append(industry)
        if company_name: haystack_parts.append(company_name)
        haystack = " / ".join(haystack_parts)
        if not haystack:
            return DEFAULT_INDUSTRY_RANGE
        for keyword, rng in INDUSTRY_WACC_RANGES.items():
            if keyword.lower() in haystack.lower():
                return rng
        return DEFAULT_INDUSTRY_RANGE


def math_isfinite(x: float) -> bool:
    try:
        import math
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


__all__ = ["WaccCalculator", "WaccBreakdown", "INDUSTRY_WACC_RANGES"]
