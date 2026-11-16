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
    # ---- SEC-sourced weighted average shares (P0 — Share Count Reconciliation)
    # ``shares_outstanding`` is the period-end count (or Yahoo fallback). The
    # fields below carry the SEC-sourced *weighted average* shares for the same
    # period, so EPS / P/E use the correct denominator.
    weighted_avg_basic_shares: Optional[float] = None
    weighted_avg_diluted_shares: Optional[float] = None
    shares_source: Optional[str] = None  # "yahoo" | "sec_filing" | "fallback"
    eps: Optional[float] = None
    # Stock-based compensation (cash-flow-statement non-cash add-back). Kept
    # separately from ``operating_cash_flow`` so the SBC-normalization layer can
    # charge it back as an economic cost (Phase 1 — SBC Normalization).
    stock_based_compensation: Optional[float] = None

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

    # ---- Enterprise-to-Equity bridge components (Phase 1) ------------------
    # Claims that rank ahead of / alongside common equity in the EV→Equity
    # bridge, kept separate from ``net_debt`` so a complex capital structure
    # (Tencent/Alibaba-style minority interests, preferreds, associates) is not
    # silently collapsed into a single "net debt" that double-counts or
    # under-counts. All optional; ``None`` == "no such claim on file".
    minority_interest: Optional[float] = None
    preferred_equity: Optional[float] = None
    # Non-operating assets NOT captured in the operating FCF (associates / JV /
    # long-term investments) → added back to equity in the bridge.
    non_operating_assets: Optional[float] = None
    # True when ``total_debt`` is understood to already include lease liabilities
    # (the provider's "Total Debt" convention). Used by the bridge to avoid
    # double-deducting IFRS-16 leases.
    leases_in_debt: Optional[bool] = None

    shares_outstanding: Optional[float] = None
    # ---- SEC Filing share-count provenance (P0 — Share Count Reconciliation) --
    # ``shares_outstanding`` above is the Yahoo/market-implied snapshot. The
    # fields below carry the SEC filing-sourced share counts with full
    # provenance, so models can select the *correct* caliber instead of
    # blindly using the market snapshot.
    sec_share_count: Optional[Any] = None  # ShareCountData (data/share_count_engine.py)
    sec_reconciliation: Optional[Any] = None  # ShareCountReconciliation
    # SEC-sourced individual calibers (for quick access by models)
    sec_period_end_shares: Optional[float] = None      # latest period-end common shares
    sec_weighted_avg_diluted: Optional[float] = None   # TTM diluted weighted avg
    sec_weighted_avg_basic: Optional[float] = None     # TTM basic weighted avg
    sec_shares_period_end: Optional[str] = None        # ISO date of period-end shares
    sec_shares_source: Optional[str] = None            # "edgartools" | "sec_api"

    book_value: Optional[float] = None
    book_value_per_share: Optional[float] = None

    sector: Optional[str] = None
    industry: Optional[str] = None
    company_name: Optional[str] = None
    # Raw provider business summary (Yahoo assetProfile.longBusinessSummary).
    # Stored verbatim for the taxonomy description signal; never used to
    # overwrite an internal Business Identity.
    description: Optional[str] = None

    dividend_yield: Optional[float] = None
    beta: Optional[float] = None
    # ---- Beta multi-window sensitivity (Phase 3 / Session #21) -----------
    # A single regression β hides how unstable the estimate is across windows.
    # `beta_windows` records the per-window regression β (window label → value);
    # `industry_beta` carries a bottom-up / peer unlevered β when one exists.
    # Both are optional: `None` means "no source", never a fabricated value.
    beta_windows: Optional[Dict[str, float]] = None
    industry_beta: Optional[float] = None
    # ---- Bottom-up beta chain (Session #25 / M-34) ------------------------
    # `bottom_up_beta` is the **target-relevered, cash-adjusted** β that CAPM
    # consumes when available (peer levered → unlevered → median → cash-adjusted
    # → relevered). `bottom_up_beta_chain` keeps every step + screen level for
    # audit. `industry_beta` above stays the raw peer-median *unlevered* value.
    bottom_up_beta: Optional[float] = None
    bottom_up_beta_chain: Optional[Dict[str, Any]] = None
    # ---- β provenance (Phase 1 — Beta Source & Provenance) ----------------
    # Records HOW ``beta`` was obtained so a report can label it truthfully and
    # never assert a method it cannot prove ("3Y monthly vs SPY" was hard-coded
    # in WACC regardless of the real source). Populated by the provider; a
    # missing dict means "provenance unknown", which the report must flag as
    # *assumed* rather than verified. Keys: source, method, window_label,
    # window_start, window_end, price_basis, n_observations, missing_periods,
    # benchmark, provider_beta.
    beta_provenance: Optional[Dict[str, Any]] = None
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    price_to_book: Optional[float] = None

    # Macroeconomic / derived inputs (populated by provider or calculator)
    risk_free_rate: Optional[float] = None
    # Provenance for the injected ``risk_free_rate`` (e.g. "^TNX US 10Y"). Lets
    # WACC detect a *currency-mismatched* Rf — a USD Treasury yield injected for
    # an HKD/CNY/MYR cash-flow stream — and substitute a currency-appropriate
    # one instead of silently discounting foreign cash flows at the US rate.
    risk_free_source: Optional[str] = None
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

    # ---- M-31: segment-level revenue composition (taxonomy ③) --------------
    # Resolved by data/segment_revenue.py and consumed by the taxonomy builder.
    # ``Any`` avoids a data → classification import cycle. Defaults to None →
    # the taxonomy treats it as explicitly "unavailable" (offline/golden safe).
    revenue_composition: Optional[Any] = None

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
    # ---- Phase 1.5: report math & wording self-audit (ReportMathAudit)
    math_audit: Optional[object] = None

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

    # ---- Classification identity vs economics (Phase 1.3)
    # Business Identity = what the company actually sells / to whom → derived
    # from the provider's sector/industry (a hard, external fact). Business
    # Economics = margin / capex / leverage / FCF shape → derived from the ML
    # model and structural features. Structure alone (high gross margin + high
    # capex + low leverage) is NOT proof of a specialist prototype such as
    # Semiconductor. When the ML/rule top-1 is statistically ambiguous
    # (top-1/top-2 ratio < 2) AND disagrees with the identity, the label must
    # not be used silently as the valuation prototype:
    #   classification_status = "ambiguous / review_required"
    classification_status: str = "confident"
    identity_business_type: Optional[str] = None
    classification_conflict_note: Optional[str] = None

    # ---- Business Taxonomy — five dimensions (additive / shadow) ----------
    # Produced by classification/taxonomy.py. Purely additive: none of these
    # fields change business_type / applicable_models / model routing, so the
    # valuation pipeline and golden fingerprints are unaffected.
    #   ① identity  ② business models  ③ revenue composition
    #   ④ economic profile (internal)  ⑤ external labels (verbatim)
    taxonomy_identity_key: Optional[str] = None
    taxonomy_identity_label: Optional[str] = None
    taxonomy_business_models: List[str] = field(default_factory=list)
    taxonomy_conflict_kind: Optional[str] = None
    taxonomy_decision_status: Optional[str] = None
    taxonomy_audit: List[str] = field(default_factory=list)
    revenue_composition_available: bool = False
    revenue_composition_note: Optional[str] = None
    external_classification: Dict[str, Any] = field(default_factory=dict)


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
