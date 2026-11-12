"""Bank valuation models: Dividend Discount (DDM) and Residual Income (RIM).

Both models share the single β exit (`resolve_effective_beta`) and the same
risk-free / equity-risk-premium inputs the WACC / scenario path uses, so the
bank surface can never read a different β or cost of equity than the rest of
the report (Recursion SOFI round1 fix).
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from config import ModelName, SolverStatus, get_logger
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult
from valuation.wacc import resolve_effective_beta

log = get_logger("models.bank")

# Bank cost-of-equity sanity band (mirrors INDUSTRY_WACC_RANGES entries for
# Banks / Financial Services). A CAPM ke far outside this band is almost always
# driven by an extreme regression β and must be surfaced, not hidden.
_BANK_KE_BAND: Tuple[float, float] = (0.070, 0.100)
_RIM_HORIZON = 5


def _resolve_discount_inputs(data: FinancialData, **kwargs) -> Tuple[float, float, float]:
    """Return (beta, risk_free, market_premium) from the unified β exit.

    β comes from `resolve_effective_beta` (WACC breakdown → winsorized provider
    β → config fallback). Rf / ERP are read from the same fields the WACC path
    reads, so the CAPM cost of equity is identical wherever it appears.
    """
    beta = kwargs.get("beta")
    if beta is None:
        beta = resolve_effective_beta(data).beta
    mkt = data.market
    rf = kwargs.get("risk_free")
    if rf is None:
        rf = mkt.risk_free_rate if mkt.risk_free_rate is not None else 0.04
    erp = kwargs.get("market_premium")
    if erp is None:
        erp = mkt.equity_risk_premium if mkt.equity_risk_premium is not None else 0.06
    return float(beta), float(rf), float(erp)


def _actual_dividend_per_share(data: FinancialData) -> Optional[float]:
    """Real dividend per share, or None when the company pays no dividend.

    A financial with no dividend history must NOT be valued with a fabricated
    yield (the old code silently substituted 2%), which is exactly what drove an
    artificial "severely overvalued" headline for SOFI.
    """
    ttm = data.ttm
    dps = getattr(ttm, "dividend_per_share", None) if ttm else None
    if dps is not None and float(dps) > 0:
        return float(dps)
    y = data.market.dividend_yield
    price = data.market.current_price
    if y is not None and float(y) > 0 and price:
        return float(y) * float(price)
    return None


def _book_equity_per_share(data: FinancialData) -> Optional[float]:
    bvps = data.market.book_value_per_share
    if bvps is not None and float(bvps) > 0:
        return float(bvps)
    bv = data.market.book_value
    ttm = data.ttm
    shares = data.market.shares_outstanding or (ttm.shares_outstanding if ttm else None)
    if bv is not None and shares and float(shares) > 0 and float(bv) > 0:
        return float(bv) / float(shares)
    return None


class BankDDMModel(ValuationModel):
    NAME = ModelName.BANK_DDM

    def __init__(self, risk_free: float = 0.04, market_premium: float = 0.06, beta: float = 1.0) -> None:
        super().__init__()
        self.risk_free = risk_free
        self.market_premium = market_premium
        self.beta = beta

    def applicability_check(self, data: FinancialData, profile: Any) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        if not profile or not getattr(profile, "is_financial_institution", False):
            reasons.append("Bank DDM is only for financial institutions")
        if data.ttm is None:
            reasons.append("TTM financials required")
        if data.market.current_price is None:
            reasons.append("Current price required")
        if _actual_dividend_per_share(data) is None:
            reasons.append(
                "No dividend paid — DDM requires a dividend stream; "
                "use Bank RIM (residual income) for non-dividend financials"
            )
        return (len(reasons) == 0, reasons)

    def calculate(self, data: FinancialData, profile: Any, **kwargs) -> ValuationResult:
        ttm = data.ttm
        shares = data.market.shares_outstanding or (ttm.shares_outstanding if ttm else None)
        if shares is None or shares <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Shares outstanding missing"],
                data_quality_score=data.quality.data_quality_score,
            )

        dividend = _actual_dividend_per_share(data)
        if dividend is None:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["No dividend paid — DDM not applicable"],
                data_quality_score=data.quality.data_quality_score,
            )

        growth_1 = float(kwargs.get("growth_1", 0.08))
        growth_2 = float(kwargs.get("growth_2", 0.04))
        terminal_growth = float(kwargs.get("terminal_growth", 0.025))
        beta, risk_free, market_premium = _resolve_discount_inputs(data, **kwargs)
        cost_of_equity = risk_free + beta * market_premium
        if cost_of_equity <= terminal_growth:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INFEASIBLE,
                notes=[
                    f"Cost of equity {cost_of_equity:.2%} ≤ terminal growth "
                    f"{terminal_growth:.2%} — Gordon growth undefined"
                ],
                data_quality_score=data.quality.data_quality_score,
            )

        yr1 = dividend * (1 + growth_1)
        yr2 = yr1 * (1 + growth_1)
        yr3 = yr2 * (1 + growth_2)
        terminal_value = (yr3 * (1 + terminal_growth)) / (cost_of_equity - terminal_growth)
        pv = dividend / (1 + cost_of_equity) + yr1 / (1 + cost_of_equity) ** 2 + yr2 / (1 + cost_of_equity) ** 3
        pv += terminal_value / (1 + cost_of_equity) ** 3
        value_per_share = pv

        assumptions = [
            ValuationAssumption("Dividend", round(dividend, 4), "USD/share", "Current dividend (actual)"),
            ValuationAssumption("Beta (unified)", round(beta, 4), "x", "resolve_effective_beta()"),
            ValuationAssumption("Cost of Equity", round(cost_of_equity, 4), "%", "CAPM estimate"),
            ValuationAssumption("Stage 1 Growth", round(growth_1, 4), "%", "Initial phase"),
            ValuationAssumption("Stage 2 Growth", round(growth_2, 4), "%", "Transition phase"),
            ValuationAssumption("Terminal Growth", round(terminal_growth, 4), "%", "Long-run growth"),
        ]
        notes = [
            f"Bank DDM price = ${value_per_share:,.2f}/share using CAPM cost of equity "
            f"{cost_of_equity:.2%} (β={beta:.2f})",
            f"Dividend assumptions: {growth_1:.2%} -> {growth_2:.2%} -> {terminal_growth:.2%}",
        ]
        if not (_BANK_KE_BAND[0] <= cost_of_equity <= _BANK_KE_BAND[1]):
            notes.append(
                f"⚠ Cost of equity {cost_of_equity:.2%} outside the bank band "
                f"{_BANK_KE_BAND[0]:.1%}–{_BANK_KE_BAND[1]:.1%} — driven by β={beta:.2f}"
            )
        if data.market.current_price:
            spread = (value_per_share - data.market.current_price) / data.market.current_price
            notes.append(f"Price spread vs market: {spread:+.1%}")

        breakdown = {
            "dividend": dividend,
            "beta": beta,
            "cost_of_equity": cost_of_equity,
            "growth_1": growth_1,
            "growth_2": growth_2,
            "terminal_growth": terminal_growth,
            "terminal_value": terminal_value,
            "pv_dividends": pv,
            "value_per_share": value_per_share,
            "shares_outstanding": shares,
        }

        return ValuationResult(
            model_name=self.model_name,
            status=SolverStatus.SOLVED,
            value_per_share=value_per_share,
            assumptions=assumptions,
            notes=notes,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
        )


class BankRIMModel(ValuationModel):
    """Residual Income Model (Ohlson) for financial institutions.

    A bank's value is its book equity plus the present value of the residual
    income it earns above its cost of equity:

        V0 = B0 + Σ_{t=1..N} (ROE_t − r) · B_{t−1} / (1+r)^t

    Book value compounds under the clean-surplus relation
    (B_t = B_{t−1}·(1 + ROE_t·(1 − payout))) and ROE fades linearly from the
    current level to the cost of equity by year N, so no arbitrary terminal
    persistence factor is needed (terminal residual income = 0 by construction).

    RIM is dividend-independent, which makes it the correct anchor for
    non-dividend-paying financials (digital banks / fintech lenders).
    """

    NAME = ModelName.BANK_RIM

    def __init__(self, horizon: int = _RIM_HORIZON) -> None:
        super().__init__()
        self.horizon = horizon

    def applicability_check(self, data: FinancialData, profile: Any) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        if not profile or not getattr(profile, "is_financial_institution", False):
            reasons.append("Bank RIM is only for financial institutions")
        if data.ttm is None:
            reasons.append("TTM financials required")
        if _book_equity_per_share(data) is None:
            reasons.append("Positive book value per share required (book value anchor)")
        if data.ttm is not None and data.ttm.net_income is None:
            reasons.append("TTM net income required to estimate ROE")
        return (len(reasons) == 0, reasons)

    def calculate(self, data: FinancialData, profile: Any, **kwargs) -> ValuationResult:
        ttm = data.ttm
        b0 = _book_equity_per_share(data)
        if b0 is None or ttm is None or ttm.net_income is None:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Book value per share and TTM net income required"],
                data_quality_score=data.quality.data_quality_score,
            )

        horizon = int(kwargs.get("horizon", self.horizon))
        terminal_growth = float(kwargs.get("terminal_growth", 0.025))
        beta, risk_free, market_premium = _resolve_discount_inputs(data, **kwargs)
        cost_of_equity = risk_free + beta * market_premium
        if cost_of_equity <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INFEASIBLE,
                notes=[f"Cost of equity {cost_of_equity:.2%} non-positive"],
                data_quality_score=data.quality.data_quality_score,
            )

        # ROE from TTM net income over current book equity.
        book_equity = b0 * ttm.shares_outstanding if ttm.shares_outstanding else None
        if book_equity is None or book_equity <= 0:
            mkt_shares = data.market.shares_outstanding
            book_equity = b0 * mkt_shares if mkt_shares else None
        if book_equity is None or book_equity <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Book equity unavailable for ROE estimate"],
                data_quality_score=data.quality.data_quality_score,
            )
        roe_0 = float(ttm.net_income) / float(book_equity)
        # Operating-driver override: scenarios vary ROE (the aggregate outcome of
        # net interest margin and credit costs) so the bank band reflects an
        # *operating* driver, not only the discount rate (Recursion SOFI round3
        # follow-up). None → use the TTM-derived ROE.
        roe_override = kwargs.get("roe_override")
        roe_source = "ttm"
        if roe_override is not None:
            roe_0 = float(roe_override)
            roe_source = "scenario_override"

        # Payout from the actual dividend (0 for non-payers).
        dps = _actual_dividend_per_share(data)
        eps = ttm.eps
        payout = 0.0
        if dps is not None and eps and float(eps) > 0:
            payout = min(1.0, max(0.0, float(dps) / float(eps)))

        b = float(b0)
        pv_residual = 0.0
        schedule: List[dict] = []
        for t in range(1, horizon + 1):
            roe_t = roe_0 + (cost_of_equity - roe_0) * (t / horizon)
            ri_t = (roe_t - cost_of_equity) * b
            pv_residual += ri_t / (1 + cost_of_equity) ** t
            schedule.append({
                "year": t,
                "roe": round(roe_t, 4),
                "begin_book": round(b, 2),
                "residual_income": round(ri_t, 2),
            })
            b = b * (1 + roe_t * (1 - payout))

        value_per_share = float(b0) + pv_residual

        assumptions = [
            ValuationAssumption("Book Value/Share", round(b0, 2), "USD/share", "Current book equity anchor"),
            ValuationAssumption("ROE (TTM)", round(roe_0, 4), "%", "TTM net income / book equity"),
            ValuationAssumption("Beta (unified)", round(beta, 4), "x", "resolve_effective_beta()"),
            ValuationAssumption("Cost of Equity", round(cost_of_equity, 4), "%", "CAPM estimate"),
            ValuationAssumption("Payout Ratio", round(payout, 4), "%", "Actual dividend / EPS"),
            ValuationAssumption("Horizon", horizon, "years", "ROE fades to cost of equity"),
            ValuationAssumption("Terminal Growth", round(terminal_growth, 4), "%", "Reference only (terminal RI = 0)"),
        ]
        notes = [
            f"Bank RIM value = ${value_per_share:,.2f}/share = book value "
            f"${b0:,.2f} + PV of residual income ${pv_residual:,.2f} (β={beta:.2f}, ke={cost_of_equity:.2%})",
            f"ROE {roe_0:.2%} fades linearly to cost of equity {cost_of_equity:.2%} over {horizon}y "
            "(no terminal excess return assumed)",
        ]
        if roe_0 < cost_of_equity:
            notes.append(
                f"ROE {roe_0:.2%} below cost of equity {cost_of_equity:.2%} → intrinsic value "
                "below book; the market is pricing a future ROE recovery above this path"
            )
        if not (_BANK_KE_BAND[0] <= cost_of_equity <= _BANK_KE_BAND[1]):
            notes.append(
                f"⚠ Cost of equity {cost_of_equity:.2%} outside the bank band "
                f"{_BANK_KE_BAND[0]:.1%}–{_BANK_KE_BAND[1]:.1%} — driven by β={beta:.2f}"
            )
        if data.market.current_price:
            spread = (value_per_share - data.market.current_price) / data.market.current_price
            notes.append(f"Price spread vs market: {spread:+.1%}")

        breakdown = {
            "book_value_per_share": b0,
            "roe": roe_0,
            "roe_source": roe_source,
            "beta": beta,
            "cost_of_equity": cost_of_equity,
            "payout": payout,
            "horizon": horizon,
            "pv_residual_income": pv_residual,
            "residual_schedule": schedule,
            "value_per_share": value_per_share,
        }

        return ValuationResult(
            model_name=self.model_name,
            status=SolverStatus.SOLVED,
            value_per_share=value_per_share,
            assumptions=assumptions,
            notes=notes,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
        )


__all__ = ["BankDDMModel", "BankRIMModel"]
