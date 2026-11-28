"""
data/normalizer.py - Financial Data Normalization
- TTM calculations
- Unit consistency tracking
- Missing value marking
- Fiscal period alignment
"""
from __future__ import annotations

from typing import List, Optional

from config import get_logger
from data.bank_registry import BANK_HOLDING_COMPANIES
from data.models import FinancialData, FinancialStatement
from data.nwc_utils import infer_change_in_nwc
from data.provenance import DataOriginType, stamp

#: Default origin for normalizer arithmetic. Every branch below is deterministic
#: arithmetic over already-known fields, so DERIVED is the honest label -- except
#: where a *prior-period ratio* stands in for a missing current figure, which is
#: an ESTIMATED value and is stamped as such at the call site.
_DERIVED = DataOriginType.DERIVED
_ESTIMATED = DataOriginType.ESTIMATED
_IMPUTED = DataOriginType.IMPUTED


def _stamp_derived(stmt, field_name, method, *, source_fields, input_values,
                   origin: DataOriginType = _DERIVED) -> None:
    """Record that ``field_name`` was computed here, and from what.

    Called *after* the attribute is assigned so ``stamp`` can capture the
    produced value. Any inferred number that is not stamped here would be
    indistinguishable from a filed one -- the exact defect U-2 exists to close.
    """
    stamp(stmt, field_name, origin,
          derivation_method=method,
          source_fields=source_fields,
          input_fields=list(source_fields),
          input_values=input_values,
          source_provider="normalizer")


log = get_logger("data.normalizer")


def _ttm_eps(
    quarters: List[FinancialStatement],
    net_income: Optional[float],
    shares: Optional[float],
) -> Optional[float]:
    """TTM EPS = sum of four quarterly EPS, else NI / shares. Never average quarterly EPS."""
    q_eps = [s.eps for s in quarters if s.eps is not None]
    if len(q_eps) == 4:
        return float(sum(q_eps))
    if net_income is not None and shares and shares > 0:
        return float(net_income) / float(shares)
    return None


def _stamp_ttm_sums(ttm, quarters, partial_fields) -> None:
    """Stamp every summed TTM field with how it was built.

    A field summed from four complete quarters is ``DERIVED``; a field summed
    while skipping a missing quarter is ``IMPUTED`` and names the gap, because
    the resulting number is understated by construction and must not be read as
    a clean total (design §7.2).
    """
    summed = (
        "revenue", "gross_profit", "operating_income", "ebit", "ebitda",
        "net_income", "depreciation_amortization", "capex",
        "operating_cash_flow", "free_cash_flow", "change_in_nwc",
        "interest_expense", "income_tax", "stock_based_compensation",
    )
    periods = [s.period_end for s in quarters]
    for name in summed:
        if getattr(ttm, name, None) is None:
            continue
        partial = name in partial_fields
        inputs = {name: getattr(ttm, name), "periods": periods}
        if partial:
            inputs["missing_quarters"] = True
        stamp(
            ttm, name,
            _IMPUTED if partial else _DERIVED,
            derivation_method="TTM_SUM_4Q",
            source_fields=[f"quarterly_income[].{name}"],
            input_fields=[f"quarterly_income[].{name}"],
            input_values=inputs,
            source_provider="normalizer",
        )
    if any(getattr(ttm, n, None) is not None for n in summed):
        stamp(ttm, "eps", _DERIVED, derivation_method="TTM_EPS_SUM_4Q",
              source_fields=["quarterly_income[].eps", "net_income"],
              input_fields=["eps", "net_income"],
              input_values={"eps": ttm.eps, "periods": periods},
              source_provider="normalizer")


class FinancialNormalizer:
    """Normalizes raw financial data for valuation models."""

    @staticmethod
    def compute_ttm_from_quarters(q_stmts: List[FinancialStatement]) -> Optional[FinancialStatement]:
        """Compute Trailing-Twelve-Month from 4 latest quarterly statements."""
        if not q_stmts or len(q_stmts) < 4:
            return None
        last4 = q_stmts[:4]
        # Design §7.2: a quarter with a missing value is *skipped* by the sum,
        # which silently understates the TTM (4 quarters, one op_inc=None ->
        # 75% of the true figure, looking like an ordinary number). Track which
        # fields were partial so the TTM can be stamped IMPUTED and name them.
        partial_fields: List[str] = []

        def _sum(attr: str) -> Optional[float]:
            vals = [getattr(s, attr) for s in last4]
            if all(v is None for v in vals):
                return None
            try:
                total = sum(float(v) for v in vals if v is not None)
            except (ValueError, TypeError):
                return None
            if any(v is None for v in vals) and attr not in partial_fields:
                partial_fields.append(attr)
            return total

        ttm = FinancialStatement(
            period_end=f"TTM({last4[0].period_end})",
            period_type="ttm",
            currency=last4[0].currency,
            revenue=_sum("revenue"),
            gross_profit=_sum("gross_profit"),
            operating_income=_sum("operating_income"),
            ebit=_sum("ebit"),
            ebitda=_sum("ebitda"),
            net_income=_sum("net_income"),
            depreciation_amortization=_sum("depreciation_amortization"),
            capex=_sum("capex"),
            operating_cash_flow=_sum("operating_cash_flow"),
            free_cash_flow=_sum("free_cash_flow"),
            change_in_nwc=_sum("change_in_nwc"),
            interest_expense=_sum("interest_expense"),
            income_tax=_sum("income_tax"),
            stock_based_compensation=_sum("stock_based_compensation"),
            shares_outstanding=last4[0].shares_outstanding,
            eps=_ttm_eps(last4, _sum("net_income"), last4[0].shares_outstanding),
        )
        _stamp_ttm_sums(ttm, last4, partial_fields)
        return ttm

    @staticmethod
    def ensure_ttm(data: FinancialData) -> FinancialData:
        """Ensure TTM is populated. If missing, approximate from latest annual."""
        if data.ttm is None:
            if data.quarterly_income and len(data.quarterly_income) >= 4:
                data.ttm = FinancialNormalizer.compute_ttm_from_quarters(data.quarterly_income)
                data.notes.append("TTM computed from 4 most recent quarters.")
            elif data.annual_income:
                latest = data.annual_income[0]
                data.ttm = FinancialStatement(
                    period_end=f"TTM(approx from {latest.period_end})",
                    period_type="ttm",
                    currency=latest.currency,
                    revenue=latest.revenue,
                    gross_profit=latest.gross_profit,
                    operating_income=latest.operating_income,
                    ebit=latest.ebit,
                    ebitda=latest.ebitda,
                    net_income=latest.net_income,
                    depreciation_amortization=latest.depreciation_amortization,
                    capex=latest.capex,
                    operating_cash_flow=latest.operating_cash_flow,
                    free_cash_flow=latest.free_cash_flow,
                    change_in_nwc=latest.change_in_nwc,
                    interest_expense=latest.interest_expense,
                    income_tax=latest.income_tax,
                    stock_based_compensation=latest.stock_based_compensation,
                    shares_outstanding=latest.shares_outstanding,
                    eps=latest.eps,
                )
                data.notes.append("TTM approximated from latest annual report (not true TTM).")
                # A TTM copied from an annual report is not a TTM: it is a
                # stand-in whose figures belong to a different period. Marking
                # it ESTIMATED keeps "we approximated" from reading as "we
                # measured" downstream.
                _fields = (
                    "revenue", "gross_profit", "operating_income", "ebit",
                    "ebitda", "net_income", "depreciation_amortization",
                    "capex", "operating_cash_flow", "free_cash_flow",
                    "change_in_nwc", "interest_expense", "income_tax",
                    "stock_based_compensation", "shares_outstanding", "eps",
                )
                for _name in _fields:
                    if getattr(data.ttm, _name, None) is None:
                        continue
                    stamp(data.ttm, _name, _ESTIMATED,
                          derivation_method="TTM_FROM_LATEST_ANNUAL",
                          source_fields=[f"annual_income[0].{_name}"],
                          input_fields=[f"annual_income[0].{_name}"],
                          input_values={_name: getattr(data.ttm, _name),
                                        "source_period": latest.period_end},
                          source_provider="normalizer")
        return data

    @staticmethod
    def fill_derived_fields(data: FinancialData) -> FinancialData:
        """Fill derived fields (gross profit from re-cogs, EBIT from OpInc, FCF from OCF-CapEx)."""
        # A bank's "operating income" is not a figure it reports; deriving
        # EBIT = NI + interest + tax here would put back exactly the value the
        # provider just refused to supply.
        is_bank = data.ticker.upper() in BANK_HOLDING_COMPANIES
        # Pre-compute latest-annual ratios for TTM interest/tax estimation
        # (quarterly data often lacks InterestExpense / TaxProvision).
        _int_ratio = None  # interest_expense / revenue
        _tax_ratio = None  # income_tax / revenue
        if data.annual_income:
            a0 = data.annual_income[0]
            if a0.revenue and a0.revenue > 0:
                if a0.interest_expense is not None:
                    _int_ratio = abs(float(a0.interest_expense)) / float(a0.revenue)
                if a0.income_tax is not None:
                    _tax_ratio = abs(float(a0.income_tax)) / float(a0.revenue)

        all_stmts: List[FinancialStatement] = list(data.annual_income) + list(data.quarterly_income)
        if data.ttm is not None:
            all_stmts.append(data.ttm)
        for s in all_stmts:
            if s.revenue is not None and s.cost_of_revenue is not None and s.gross_profit is None:
                s.gross_profit = s.revenue - s.cost_of_revenue
                _stamp_derived(s, "gross_profit", "GROSS_PROFIT_FROM_REVENUE_MINUS_COGS",
                               source_fields=["revenue", "cost_of_revenue"],
                               input_values={"revenue": s.revenue,
                                             "cost_of_revenue": s.cost_of_revenue})
            if s.revenue is not None and s.gross_profit is not None and s.cost_of_revenue is None:
                s.cost_of_revenue = s.revenue - s.gross_profit
                _stamp_derived(s, "cost_of_revenue", "COGS_FROM_REVENUE_MINUS_GROSS_PROFIT",
                               source_fields=["revenue", "gross_profit"],
                               input_values={"revenue": s.revenue,
                                             "gross_profit": s.gross_profit})
            if s.operating_income is not None and s.ebit is None and not is_bank:
                s.ebit = s.operating_income
                _stamp_derived(s, "ebit", "EBIT_FROM_OPERATING_INCOME",
                               source_fields=["operating_income"],
                               input_values={"operating_income": s.operating_income})
            # Estimate interest_expense / income_tax for TTM from annual ratios
            # when quarterly data omits these fields.
            if s.period_type == "ttm" and s.revenue and s.revenue > 0:
                if s.interest_expense is None and _int_ratio is not None:
                    s.interest_expense = float(s.revenue) * _int_ratio
                    _stamp_derived(s, "interest_expense",
                                   "REVENUE_X_PRIOR_INTEREST_RATIO",
                                   source_fields=["revenue", "annual_income[0].interest_expense"],
                                   input_values={"revenue": s.revenue,
                                                 "ratio": _int_ratio},
                                   origin=DataOriginType.ESTIMATED)
                if s.income_tax is None and _tax_ratio is not None:
                    s.income_tax = float(s.revenue) * _tax_ratio
                    _stamp_derived(s, "income_tax", "REVENUE_X_PRIOR_TAX_RATIO",
                                   source_fields=["revenue", "annual_income[0].income_tax"],
                                   input_values={"revenue": s.revenue,
                                                 "ratio": _tax_ratio},
                                   origin=DataOriginType.ESTIMATED)
            # Infer EBIT from Net Income + Interest Expense + Income Tax
            # when Yahoo omits EBIT (common for credit-services / FinTech tickers).
            if s.ebit is None and s.net_income is not None and not is_bank:
                _addbacks = 0.0
                _has_addback = False
                if s.interest_expense is not None:
                    _addbacks += abs(float(s.interest_expense))
                    _has_addback = True
                if s.income_tax is not None:
                    _addbacks += abs(float(s.income_tax))
                    _has_addback = True
                if _has_addback:
                    _inputs = {"net_income": s.net_income}
                    if s.interest_expense is not None:
                        _inputs["interest_expense"] = s.interest_expense
                    if s.income_tax is not None:
                        _inputs["income_tax"] = s.income_tax
                    s.ebit = float(s.net_income) + _addbacks
                    s.operating_income = s.ebit
                    for _name in ("ebit", "operating_income"):
                        _stamp_derived(s, _name, "NI_PLUS_INTEREST_PLUS_TAX",
                                       source_fields=list(_inputs),
                                       input_values=_inputs)
            # Not for banks: `ebit` was suppressed deliberately (U-1), so
            # rebuilding ebitda here would resurrect a DERIVED value whose only
            # input is the very number the provider refused to supply (U-8).
            if (not is_bank and s.ebit is not None
                    and s.depreciation_amortization is not None
                    and s.ebitda is None):
                s.ebitda = s.ebit + s.depreciation_amortization
                _stamp_derived(s, "ebitda", "EBIT_PLUS_DA",
                               source_fields=["ebit", "depreciation_amortization"],
                               input_values={"ebit": s.ebit,
                                             "da": s.depreciation_amortization})
            if (s.operating_cash_flow is not None and s.capex is not None and s.free_cash_flow is None):
                s.free_cash_flow = s.operating_cash_flow + s.capex
                _stamp_derived(s, "free_cash_flow", "FCF_FROM_OCF_PLUS_CAPEX",
                               source_fields=["operating_cash_flow", "capex"],
                               input_values={"operating_cash_flow": s.operating_cash_flow,
                                             "capex": s.capex})
            if s.change_in_nwc is None:
                inferred = infer_change_in_nwc(s)
                if inferred is not None:
                    s.change_in_nwc = inferred
                    _stamp_derived(s, "change_in_nwc", "NWC_FROM_NOPAT_DA_CAPEX_FCF",
                                   source_fields=["operating_income",
                                                  "depreciation_amortization",
                                                  "capex", "free_cash_flow"],
                                   input_values={"operating_income": s.operating_income,
                                                 "da": s.depreciation_amortization,
                                                 "capex": s.capex,
                                                 "free_cash_flow": s.free_cash_flow})
            if s.net_income is not None and s.shares_outstanding and s.shares_outstanding > 0:
                derived = s.net_income / s.shares_outstanding
                # TTM EPS must be annualized (NI / shares). Never keep a quarterly average.
                if s.period_type == "ttm" or s.eps is None:
                    s.eps = derived
                    _stamp_derived(s, "eps", "EPS_FROM_NI_OVER_SHARES",
                                   source_fields=["net_income", "shares_outstanding"],
                                   input_values={"net_income": s.net_income,
                                                 "shares": s.shares_outstanding})
        return data

    @staticmethod
    def normalize_all(data: FinancialData) -> FinancialData:
        """Full normalization pipeline."""
        data = FinancialNormalizer.ensure_ttm(data)
        data = FinancialNormalizer.fill_derived_fields(data)
        data = FinancialNormalizer._mark_missing(data)
        data = FinancialNormalizer._validate_currency_consistency(data)
        return data

    @staticmethod
    def _mark_missing(data: FinancialData) -> FinancialData:
        ttm = data.ttm
        if ttm is None:
            return data
        required = ["revenue", "operating_income", "ebit", "net_income",
                    "depreciation_amortization", "capex", "operating_cash_flow",
                    "free_cash_flow", "shares_outstanding"]
        for f in required:
            if getattr(ttm, f) is None:
                data.quality.missing_fields.append(f"ttm.{f}")
        n_years = len(data.annual_income)
        if n_years < 3:
            data.quality.data_quality_score -= 20
            data.quality.missing_fields.append(f"annual_income only {n_years}y (want ≥3y)")
        if data.market.current_price is None:
            data.quality.data_quality_score -= 20
        data.quality.data_quality_score = max(0, min(100, data.quality.data_quality_score))
        return data

    @staticmethod
    def _validate_currency_consistency(data: FinancialData) -> FinancialData:
        currencies = set()
        for s in data.annual_income:
            if s.currency:
                currencies.add(s.currency)
        for s in data.quarterly_income:
            if s.currency:
                currencies.add(s.currency)
        if data.ttm and data.ttm.currency:
            currencies.add(data.ttm.currency)
        if data.market.currency:
            currencies.add(data.market.currency)
        if len(currencies) > 1:
            data.quality.mixed_currencies = True
            data.quality.data_quality_score = max(0, data.quality.data_quality_score - 30)
            data.notes.append(f"WARNING: Mixed currencies detected: {currencies}")
        return data


__all__ = ["FinancialNormalizer"]
