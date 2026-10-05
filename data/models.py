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

    def score_label(self) -> str:
        if self.data_quality_score >= 80:
            return "High"
        elif self.data_quality_score >= 60:
            return "Medium"
        elif self.data_quality_score >= 40:
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

    manual_override: bool = False
    override_note: Optional[str] = None

    ml_probabilities: Dict[str, float] = field(default_factory=dict)
    top_2_candidates: List[Tuple[str, float]] = field(default_factory=list)
    ml_model_used: bool = False
    ml_model_version: str = ""
    rule_fallback_triggered: bool = False


__all__ = [
    "FinancialStatement",
    "MarketData",
    "DataQualityFlags",
    "FinancialData",
    "ForecastPeriod",
    "CompanyProfile",
]
