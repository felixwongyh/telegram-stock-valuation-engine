"""
data/models.py - Data Classes for Financial Data
Raw data separated from normalized data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from config import DataSource


@dataclass
class FinancialStatement:
    """Single period financial statement (annual, quarterly, or TTM)."""
    period_end: str
    period_type: str = "annual"
    currency: str = "USD"

    revenue: Optional[float] = None
    cost_of_revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    ebit: Optional[float] = None
    ebitda: Optional[float] = None
    net_income: Optional[float] = None
    depreciation_amortization: Optional[float] = None

    capex: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    free_cash_flow: Optional[float] = None
    change_in_nwc: Optional[float] = None

    interest_expense: Optional[float] = None
    income_tax: Optional[float] = None
    shares_outstanding: Optional[float] = None
    eps: Optional[float] = None

    raw_fields: Dict[str, Any] = field(default_factory=dict)
    restated: bool = False
    source_timestamp: datetime = field(default_factory=datetime.utcnow)

    def has_minimal_dcf_inputs(self) -> bool:
        return (self.revenue is not None
                and self.operating_income is not None
                and self.shares_outstanding is not None)


@dataclass
class MarketData:
    as_of: datetime = field(default_factory=datetime.utcnow)
    currency: str = "USD"

    current_price: Optional[float] = None
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None

    total_debt: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    net_debt: Optional[float] = None

    shares_outstanding: Optional[float] = None

    book_value: Optional[float] = None
    book_value_per_share: Optional[float] = None

    sector: Optional[str] = None
    industry: Optional[str] = None
    company_name: Optional[str] = None

    dividend_yield: Optional[float] = None
    beta: Optional[float] = None
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    price_to_book: Optional[float] = None

    # Macroeconomic / derived inputs (populated by provider or calculator)
    risk_free_rate: Optional[float] = None
    equity_risk_premium: Optional[float] = None
    effective_tax_rate: Optional[float] = None
    implied_cost_of_debt: Optional[float] = None

    def net_debt_or_zero(self) -> float:
        if self.net_debt is not None:
            return float(self.net_debt)
        d = self.total_debt or 0.0
        c = self.cash_and_equivalents or 0.0
        return float(d - c)


@dataclass
class DataQualityFlags:
    missing_fields: List[str] = field(default_factory=list)
    inconsistent_periods: bool = False
    mixed_currencies: bool = False
    data_quality_score: int = 100
    raw_source_timestamp: datetime = field(default_factory=datetime.utcnow)
    restatement_notes: List[str] = field(default_factory=list)

    # ---- Valuation usability (Session #07) -------------------------------
    # "Source quality" answers "is the data internally coherent?"; "valuation
    # usability" answers "can I trust a per-share number built from it?".
    # Reconciliation mismatches (annual vs TTM, share-count basis) degrade the
    # latter far more than the former.
    reconciliation_mismatches: int = 0
    valuation_usability_score: int = 100

    def score_label(self) -> str:
        if self.data_quality_score >= 80:
            return "High"
        elif self.data_quality_score >= 60:
            return "Medium"
        elif self.data_quality_score >= 40:
            return "Low"
        return "Critical"

    def usability_label(self) -> str:
        s = self.valuation_usability_score
        if s >= 80:
            return "High"
        elif s >= 60:
            return "Medium"
        elif s >= 40:
            return "Low"
        return "Critical"


@dataclass
class FinancialData:
    ticker: str
    source: DataSource = DataSource.UNKNOWN

    annual_income: List[FinancialStatement] = field(default_factory=list)
    quarterly_income: List[FinancialStatement] = field(default_factory=list)
    ttm: Optional[FinancialStatement] = None

    annual_balance_sheet: List[Dict[str, Any]] = field(default_factory=list)
    quarterly_balance_sheet: List[Dict[str, Any]] = field(default_factory=list)

    annual_cashflow: List[Dict[str, Any]] = field(default_factory=list)
    quarterly_cashflow: List[Dict[str, Any]] = field(default_factory=list)

    market: MarketData = field(default_factory=MarketData)
    quality: DataQualityFlags = field(default_factory=DataQualityFlags)

    historical_prices: List[Tuple[datetime, float]] = field(default_factory=list)
    historical_multiples: Dict[str, List[Tuple[datetime, float]]] = field(default_factory=dict)

    fetched_at: datetime = field(default_factory=datetime.utcnow)
    notes: List[str] = field(default_factory=list)

    # ---- 数据对账层 (Cross-field reconciliation; see data/reconciliation.py)
    reconciliation: Optional[Any] = None
    # Reverse-validation log: which provider fields were replaced by internal
    # values after a >25% deviation (see reconciliation.apply_overrides).
    reconciliation_overrides: Optional[Any] = None

    def latest_annual(self) -> Optional[FinancialStatement]:
        return self.annual_income[0] if self.annual_income else None

    def latest_ttm_or_annual(self) -> Optional[FinancialStatement]:
        return self.ttm or self.latest_annual()

    def n_periods(self, annual: bool = True) -> int:
        return len(self.annual_income) if annual else len(self.quarterly_income)


@dataclass
class ForecastPeriod:
    year_index: int
    label: str
    revenue: Optional[float] = None
    revenue_growth: Optional[float] = None
    gross_profit: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_income: Optional[float] = None
    operating_margin: Optional[float] = None
    nopat: Optional[float] = None
    depreciation: Optional[float] = None
    capex: Optional[float] = None
    change_in_nwc: Optional[float] = None
    free_cash_flow: Optional[float] = None
    effective_tax_rate: Optional[float] = None
    shares_outstanding: Optional[float] = None


@dataclass
class ConfidenceAdjustment:
    """Single adjustment step in the classification confidence pipeline.

    Records how we went from ML raw top-1 probability down to final reported
    confidence. Enables full audit trail for end-users in reports.
    """
    step_name: str
    delta: float
    reason: str


@dataclass
class BusinessExposure:
    """Exposure weight for one business-model axis.

    Used when a company spans multiple archetypes (e.g. SoFi = Bank + FinTech +
    Technology). The sum across a given axis does not have to sum to 1.0; they are
    human-legible exposure weights, not strict probability distributions.
    """
    label: str
    weight: float
    source: str = "ml_aggregate"


@dataclass
class GrowthVerdictCard:
    """Human-legible qualitative labels for growth comparisons.

    Converts raw CAGR percentages (historical / base forecast / market implied)
    into one-sentence plain-language verdicts so Telegram readers don't need to
    mentally compare percentages.
    """

    historical_revenue_label: str = "未知"
    historical_revenue_detail: str = ""
    forecast_revenue_label: str = "未知"
    forecast_vs_history_label: str = ""
    forecast_vs_history_detail: str = ""
    implied_revenue_label: str = "未知"
    implied_vs_history_label: str = ""
    implied_vs_forecast_label: str = ""
    overall_growth_label: str = "未知"
    overall_growth_emoji: str = "📊"
    overall_growth_summary: str = ""
    historical_fcf_label: str = "未知"

    def bullet_lines(self) -> List[str]:
        lines: List[str] = []
        if self.overall_growth_summary:
            lines.append(f"{self.overall_growth_emoji} **整体增长判断:** {self.overall_growth_summary}")
        if self.historical_revenue_detail:
            lines.append(f"  • 历史增长：{self.historical_revenue_detail}")
        if self.forecast_vs_history_detail:
            lines.append(f"  • 基础预测 vs 历史：{self.forecast_vs_history_detail}")
        if self.implied_vs_history_label or self.implied_vs_forecast_label:
            bits = []
            if self.implied_vs_history_label:
                bits.append(f"市场隐含 vs 历史：{self.implied_vs_history_label}")
            if self.implied_vs_forecast_label:
                bits.append(f"vs 基础预测：{self.implied_vs_forecast_label}")
            if bits:
                lines.append("  • " + "；".join(bits))
        return lines


@dataclass
class ValuationVerdictCard:
    """Human-legible valuation verdict from multiple signals.

    Produces one headline verdict (e.g. "明显高估", "合理偏弱") plus a
    reasoning line and per-model labels so the user sees the conclusion without
    scanning the percentage spread.
    """

    headline_label: str = "数据不足"
    headline_emoji: str = "⚪"
    headline_summary: str = ""
    reasoning: str = ""
    scenario_label: str = ""
    scenario_summary: str = ""
    median_vs_price_label: str = ""
    median_vs_price_detail: str = ""
    model_coverage_label: str = ""
    fair_value_estimate_label: str = ""
    fair_value_estimate_range: str = ""

    def header_lines(self, *, include_headline: bool = True) -> List[str]:
        lines: List[str] = []
        if include_headline and self.headline_summary:
            lines.append(f"{self.headline_emoji} **一句话估值结论:** {self.headline_summary}")
        if self.median_vs_price_label:
            detail = f"（{self.median_vs_price_detail}）" if self.median_vs_price_detail else ""
            lines.append(f"  • 中位估值对比：{self.median_vs_price_label}{detail}")
        if self.scenario_summary:
            lines.append(f"  • 三档情景跨度：{self.scenario_summary}")
        if self.fair_value_estimate_range:
            lines.append(f"  • 公允估值参考区间：{self.fair_value_estimate_range}（{self.fair_value_estimate_label}）")
        if self.reasoning:
            lines.append(f"  • 判断依据：{self.reasoning}")
        return lines


@dataclass
class CompanyProfile:
    ticker: str
    business_type: str
    classification_confidence: float
    classification_reasons: List[str]
    applicable_models: List[str]
    not_applicable_models: List[str]
    not_applicable_reasons: Dict[str, str]

    revenue_characteristic: str = "Unknown"
    growth_profile: str = "Unknown"
    profitability_profile: str = "Unknown"
    cash_flow_profile: str = "Unknown"
    leverage_profile: str = "Unknown"
    capital_intensity: str = "Unknown"
    is_financial_institution: bool = False
    is_reit: bool = False

    # ---- Plain-language intuitive cards (rendered after hard numbers)
    growth_verdict: Optional[GrowthVerdictCard] = None
    valuation_verdict: Optional[ValuationVerdictCard] = None

    manual_override: bool = False
    override_note: Optional[str] = None

    ml_probabilities: Dict[str, float] = field(default_factory=dict)
    top_2_candidates: List[Tuple[str, float]] = field(default_factory=list)
    ml_model_used: bool = False
    ml_model_version: str = ""
    rule_fallback_triggered: bool = False

    # ---- Confidence transparency (Issue #1)
    ml_raw_confidence: Optional[float] = None
    confidence_adjustments: List[ConfidenceAdjustment] = field(default_factory=list)

    # ---- Hybrid classification (Issue #2)
    is_hybrid_classification: bool = False
    primary_business_type: Optional[str] = None
    secondary_business_type: Optional[str] = None
    hybrid_classification_label: Optional[str] = None
    classification_confidence_level: str = ""
    business_exposures: List[BusinessExposure] = field(default_factory=list)

    # ---- Asset-light prototype conflict (valuation archetype re-route)
    # When the ML label implies an asset-light model (e.g. SaaS) but the actual
    # economics are a capital-intensive build-out, the peer/multiple layer
    # re-routes the *valuation archetype*. Surface it so the business headline
    # does not contradict the engine's own conflict warning.
    effective_business_type: Optional[str] = None
    business_type_conflict_note: Optional[str] = None


__all__ = [
    "FinancialStatement",
    "MarketData",
    "DataQualityFlags",
    "FinancialData",
    "ForecastPeriod",
    "ConfidenceAdjustment",
    "BusinessExposure",
    "GrowthVerdictCard",
    "ValuationVerdictCard",
    "CompanyProfile",
]
