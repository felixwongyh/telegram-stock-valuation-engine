"""Bank valuation models: Dividend Discount (DDM) and Residual Income (RIM).

Both models share the single β exit (`resolve_effective_beta`) and the same
risk-free / equity-risk-premium inputs the WACC / scenario path uses, so the
bank surface can never read a different β or cost of equity than the rest of
the report (Recursion SOFI round1 fix).

P0 Refactor: The beta chain (raw → normalized → valuation → scenario) is now
tracked via :class:`valuation.capm_engine.BetaChain`. The raw CAPM ke is always
preserved alongside the adjusted valuation ke, and the bank ke band clamp is
recorded transparently — never hidden.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from config import ModelName, SolverStatus, get_logger
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult
from valuation.wacc import resolve_effective_beta

if TYPE_CHECKING:
    from valuation.capm_engine import BetaChain

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

    For banks, the raw CAPM β may push cost of equity outside the bank ke band
    (7%–10%). Since bank β regressions are noisy (regulatory capital changes,
    rate-cycle sensitivity), we clamp β so ke stays within the band rather than
    silently emitting an implausible discount rate. This is a bank-specific
    adjustment on top of the universal [0.30, 2.50] winsorization.

    When an explicit ``beta`` override is passed (e.g. from scenario analysis),
    the clamp is NOT applied — scenarios must be free to stress β beyond the
    band so Bear/Base/Bull produce differentiated ke values.

    The raw (pre-clamp) β and whether clamping occurred are available via
    :func:`_resolve_discount_inputs_detail` for audit / note rendering.
    """
    beta, rf, erp, _raw, _clamped, _chain = _resolve_discount_inputs_detail(data, **kwargs)
    return beta, rf, erp


def _resolve_discount_inputs_detail(
    data: FinancialData, **kwargs,
) -> Tuple[float, float, float, Optional[float], bool, Optional["BetaChain"]]:
    """Same as ``_resolve_discount_inputs`` but also returns (beta_raw, clamped).

    ``beta_raw`` is the pre-clamp β (None when no clamp was applied / no override
    was given and no clamp was needed). ``clamped`` is True when the bank ke band
    caused β to differ from the raw value.

    P0 Refactor: This function now uses :class:`valuation.capm_engine.CAPMEngine`
    internally to produce a full :class:`BetaChain`, returned to the caller so
    the model can attach it to its breakdown (raw vs adjusted ke audit trail).

    The chain is *returned* rather than written into ``kwargs``: a function that
    receives ``**kwargs`` gets its own dict, so ``kwargs["_capm_chain"] = chain``
    never reached the caller and ``breakdown["capm_chain"]`` was always None.
    """
    from valuation.capm_engine import CAPMEngine

    beta_override = kwargs.get("beta")
    if beta_override is None:
        eff = resolve_effective_beta(data)
        raw_beta = eff.beta_raw if eff.beta_raw is not None else eff.beta
        raw_beta_source = getattr(eff, "source", "resolve_effective_beta")
    else:
        raw_beta = float(beta_override)
        raw_beta_source = "scenario_override"

    mkt = data.market
    rf = kwargs.get("risk_free")
    if rf is None:
        if mkt.risk_free_rate is not None:
            rf = mkt.risk_free_rate
            rf_source = mkt.risk_free_source or "market.risk_free_rate"
        else:
            # Pinned basis: a missing 10Y yield must not be silently imputed.
            # 4% is the documented bank default (matches the historical report
            # fixtures); record it so the audit trail shows an *assumed* Rf
            # rather than a market-observed one.
            rf = 0.04
            rf_source = "assumed_default_4pct (snapshot Rf missing)"
    else:
        rf_source = "explicit_override"
    erp = kwargs.get("market_premium")
    if erp is None:
        erp = mkt.equity_risk_premium if mkt.equity_risk_premium is not None else 0.06

    # Determine if this is a base case (no beta override → bank band applies)
    is_base = beta_override is None
    is_bank = True  # this function is only called for bank models

    engine = CAPMEngine()
    chain: BetaChain = engine.compute(
        raw_beta=raw_beta,
        risk_free_rate=float(rf),
        equity_risk_premium=float(erp),
        raw_beta_source=raw_beta_source,
        risk_free_source=rf_source,
        is_bank=is_bank,
        apply_bank_ke_band=True,
        bank_ke_band=_BANK_KE_BAND,
        is_base_case=is_base,
        scenario_shift=0.0,
        valuation_beta_override=None,  # let the engine handle normalization + bank band
    )

    beta = chain.valuation_beta
    # ``beta_raw`` must always carry the unmodified raw β, not only when a
    # clamp fired: dropping it on unclamped banks left the audit field null
    # exactly where it was needed to prove "raw was not overwritten".
    beta_raw = chain.raw_beta
    clamped = chain.ke_adjusted

    return float(beta), float(rf), float(erp), beta_raw, clamped, chain


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
    # Phase 1.3 — Use SEC period-end shares if available, not just Yahoo
    sec_pe = getattr(data.market, "sec_period_end_shares", None)
    bv = data.market.book_value
    ttm = data.ttm
    shares = sec_pe or (ttm.shares_outstanding if ttm else None) or data.market.shares_outstanding
    if bv is not None and shares and float(shares) > 0 and float(bv) > 0:
        return float(bv) / float(shares)
    return None


def _resolve_rim_book_equity(data: FinancialData) -> Tuple[Optional[float], Optional[str]]:
    """Resolve book equity with a consistent BVPS x share-count pair.

    The RIM formula needs ROE = NI / BookEquity. BookEquity = BVPS x Shares.
    The BVPS and the share count MUST come from the same period and caliber,
    otherwise ROE is distorted (e.g. BVPS from a balance-sheet date divided
    by a market snapshot count).

    Priority:
      1. If ``data.market.book_value`` and SEC period-end shares are both
         available, compute BVPS = book_value / sec_period_end_shares.
         This guarantees the numerator and denominator are from the same
         balance-sheet date.
      2. If the provider already supplies book_value_per_share, use it with
         the SEC period-end shares (the provider's BVPS is period-consistent).
      3. Fall back to TTM shares, then Yahoo shares (with basis mismatch note).
    """
    bv = data.market.book_value
    sec_pe = getattr(data.market, "sec_period_end_shares", None)
    sec_pe_date = getattr(data.market, "sec_shares_period_end", None)
    ttm = data.ttm
    yahoo_shares = data.market.shares_outstanding

    # Priority 1: book_value / SEC period-end shares (same balance-sheet date)
    if bv is not None and float(bv) > 0 and sec_pe is not None and float(sec_pe) > 0:
        bvps = float(bv) / float(sec_pe)
        shares = float(sec_pe)
        return bvps * shares, f"book_value({bv:,.0f}) / sec_period_end_shares({sec_pe:,.0f} @ {sec_pe_date})"

    # Priority 2: provider BVPS x SEC period-end shares
    provider_bvps = data.market.book_value_per_share
    if provider_bvps is not None and float(provider_bvps) > 0:
        if sec_pe is not None and float(sec_pe) > 0:
            return float(provider_bvps) * float(sec_pe), (
                f"provider BVPS({provider_bvps:.2f}) x sec_period_end_shares({sec_pe:,.0f} @ {sec_pe_date})"
            )
        # Fall back to TTM / Yahoo
        ttm_shares = ttm.shares_outstanding if ttm else None
        shares = ttm_shares or yahoo_shares
        if shares and float(shares) > 0:
            return float(provider_bvps) * float(shares), (
                f"provider BVPS({provider_bvps:.2f}) x {'ttm' if ttm_shares else 'yahoo'}_shares({shares:,.0f})"
            )

    # Priority 3: TTM shares
    if ttm is not None and ttm.shares_outstanding and float(ttm.shares_outstanding) > 0:
        if bv is not None and float(bv) > 0:
            return float(bv) * float(ttm.shares_outstanding), (
                f"book_value({bv:,.0f}) x ttm_shares({ttm.shares_outstanding:,.0f})"
            )

    # Priority 4: Yahoo shares
    if yahoo_shares and float(yahoo_shares) > 0 and bv is not None and float(bv) > 0:
        return float(bv) * float(yahoo_shares), (
            f"book_value({bv:,.0f}) x yahoo_shares({yahoo_shares:,.0f})"
        )

    return None, None


class BankDDMModel(ValuationModel):
    NAME = ModelName.BANK_DDM

    # Dividend growth bounds for banks: initial stage growth must stay within
    # a sane band relative to long-run nominal GDP and the terminal growth rate.
    # A bank with a noisy revenue trajectory should not have its dividend growth
    # inherit an absurd CAGR (e.g. a cyclical -3% or an unsustainable +15%).
    _DDM_GROWTH_CEILING = 0.045  # long-run nominal GDP cap
    _DDM_GROWTH_FLOOR = 0.0      # dividends do not decline in the base case

    def __init__(self, risk_free: float = 0.04, market_premium: float = 0.06, beta: float = 1.0) -> None:
        super().__init__()
        self.risk_free = risk_free
        self.market_premium = market_premium
        self.beta = beta

    def _estimate_growth_from_revenue(
        self, data: FinancialData, terminal_growth: float = 0.025,
    ) -> Tuple[float, Optional[float]]:
        """Derive the initial dividend growth rate from historical revenue CAGR.

        Banks with a longer profitable track record tend to grow dividends in
        line with revenue (payout ratio is sticky in the medium term). When the
        historical revenue CAGR is available and positive, we use it — clamped
        to a bank-sane band [terminal_growth, GDP ceiling] — as the stage-1
        dividend growth ``growth_1``. If the data is insufficient or the CAGR
        is non-positive (declining revenue), we fall back to a conservative
        5% which linearly decays to ``terminal_growth`` over the explicit period.

        Returns ``(growth_1, revenue_cagr)`` where ``revenue_cagr`` is the raw
        historical CAGR (``None`` when fallback was used) so the caller can
        annotate the report with the actual growth trajectory observed.
        """
        try:
            revs = [
                float(s.revenue) for s in data.annual_income
                if s.revenue is not None and float(s.revenue) > 0
            ]
        except (TypeError, ValueError, AttributeError):
            revs = []
        if len(revs) < 2:
            return 0.05, None  # fallback: 5% → terminal_growth
        # Revenue series is newest-first; CAGR = (rev_newest / rev_oldest)^(1/n) - 1
        n = len(revs) - 1
        cagr = (revs[0] / revs[-1]) ** (1.0 / n) - 1.0
        # Clamp to the bank-sane band so a noisy / outlier-driven CAGR cannot
        # push dividend growth beyond economic reasonableness.
        lo = max(terminal_growth, self._DDM_GROWTH_FLOOR)
        hi = max(self._DDM_GROWTH_CEILING, terminal_growth + 0.01)
        growth = max(lo, min(hi, cagr))
        return float(growth), float(cagr)

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
        # Phase 1.3 — Use unified Share Count Selector for DDM.
        # DDM requires period-end common shares (matching dividend per share basis).
        from data.share_count_selector import select_share_count, ValuationModel as SCModel
        _ddm_selection = select_share_count(data, SCModel.DDM)
        shares = _ddm_selection.value
        if shares is None or shares <= 0:
            # Fallback to old path (Yahoo or TTM) if Selector returns nothing
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

        # Derive growth_1 from historical revenue CAGR when available, instead
        # of a fixed 5% default. This anchors dividend growth to the bank's
        # actual growth trajectory. Falls back to 5% if data is insufficient.
        terminal_growth = float(kwargs.get("terminal_growth", 0.025))
        growth_1_source = "kwargs"
        if "growth_1" in kwargs:
            growth_1 = float(kwargs["growth_1"])
        else:
            growth_1, rev_cagr = self._estimate_growth_from_revenue(data, terminal_growth)
            growth_1_source = "revenue_cagr" if rev_cagr is not None else "fallback_5pct"
        beta, risk_free, market_premium, beta_raw, beta_clamped, capm_chain = _resolve_discount_inputs_detail(data, **kwargs)
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

        # Five-year explicit DDM with linearly decaying growth from growth_1
        # to terminal_growth. A longer explicit period reduces the terminal
        # value's weight (the 3-year version had TV at >100% of PV), making the
        # valuation less sensitive to the Gordon growth perpetuity assumption.
        # yr_t is discounted at t (end of year t); yr0 (current dividend) is
        # already paid and NOT discounted.
        n_explicit = 5
        growth_schedule: List[float] = []
        for t in range(1, n_explicit + 1):
            frac = (t - 1) / max(1, n_explicit - 1)
            g = growth_1 + (terminal_growth - growth_1) * frac
            growth_schedule.append(g)

        dividends: List[float] = []
        d = dividend
        for g in growth_schedule:
            d = d * (1 + g)
            dividends.append(d)

        terminal_value = (dividends[-1] * (1 + terminal_growth)) / (cost_of_equity - terminal_growth)
        pv = 0.0
        for i, dv in enumerate(dividends, start=1):
            pv += dv / (1 + cost_of_equity) ** i
        pv += terminal_value / (1 + cost_of_equity) ** n_explicit
        value_per_share = pv

        assumptions = [
            ValuationAssumption("Dividend", round(dividend, 4), "USD/share", "Current dividend (actual)"),
            ValuationAssumption("Beta (unified)", round(beta, 4), "x", "resolve_effective_beta()"),
            ValuationAssumption("Cost of Equity", round(cost_of_equity, 4), "%", "CAPM estimate"),
            ValuationAssumption("Stage 1 Growth", round(growth_1, 4), "%", "Initial phase (5y explicit)"),
            ValuationAssumption("Terminal Growth", round(terminal_growth, 4), "%", "Long-run growth (Gordon)"),
        ]
        notes = [
            f"Bank DDM price = ${value_per_share:,.2f}/share using CAPM cost of equity "
            f"{cost_of_equity:.2%} (β={beta:.2f})",
            f"5y explicit dividends with growth {growth_1:.2%} → {terminal_growth:.2%} (linear decay), "
            f"then Gordon terminal at {terminal_growth:.2%}",
        ]
        # Explain growth_1 derivation so a flat schedule (growth_1 == terminal_growth)
        # is transparent rather than puzzling to the reader.
        if growth_1_source == "revenue_cagr" and rev_cagr is not None:
            if abs(growth_1 - terminal_growth) < 1e-6:
                notes.append(
                    f"Stage 1 growth {growth_1:.2%} == terminal growth {terminal_growth:.2%} "
                    f"(revenue CAGR {rev_cagr:.2%} clamped to band floor {terminal_growth:.2%}; "
                    "explicit period is flat → equivalent to Gordon perpetuity)"
                )
            else:
                notes.append(
                    f"Stage 1 growth {growth_1:.2%} derived from revenue CAGR {rev_cagr:.2%} "
                    f"(clamped to bank band [{self._DDM_GROWTH_FLOOR:.1%}, {self._DDM_GROWTH_CEILING:.1%}])"
                )
        elif growth_1_source == "fallback_5pct":
            notes.append(
                f"Stage 1 growth {growth_1:.2%} = fallback (insufficient revenue history for CAGR; "
                "decays to terminal growth over explicit period)"
            )
        if not (_BANK_KE_BAND[0] <= cost_of_equity <= _BANK_KE_BAND[1]):
            notes.append(
                f"⚠ Cost of equity {cost_of_equity:.2%} outside the bank band "
                f"{_BANK_KE_BAND[0]:.1%}–{_BANK_KE_BAND[1]:.1%} — driven by β={beta:.2f}"
            )
        if beta_clamped and beta_raw is not None:
            notes.append(
                f"⚠ β clamped from {beta_raw:.2f} to {beta:.2f} — CAPM ke "
                f"{risk_free + beta_raw * market_premium:.2%} exceeds bank ke band "
                f"{_BANK_KE_BAND[0]:.1%}–{_BANK_KE_BAND[1]:.1%}; "
                "β adjusted to keep ke within band (market section shows raw β)"
            )
        if data.market.current_price:
            spread = (value_per_share - data.market.current_price) / data.market.current_price
            notes.append(f"Price spread vs market: {spread:+.1%}")

        breakdown = {
            "dividend": dividend,
            "beta": beta,
            "beta_raw": beta_raw,
            "beta_clamped": beta_clamped,
            "cost_of_equity": cost_of_equity,
            "capm_chain": capm_chain.as_dict() if capm_chain else None,
            "growth_1": growth_1,
            "growth_1_source": growth_1_source,
            "revenue_cagr": rev_cagr,
            "growth_schedule": growth_schedule,
            "n_explicit_years": n_explicit,
            "terminal_growth": terminal_growth,
            "terminal_value": terminal_value,
            "pv_explicit": sum(
                dv / (1 + cost_of_equity) ** i for i, dv in enumerate(dividends, start=1)
            ),
            "pv_terminal": terminal_value / (1 + cost_of_equity) ** n_explicit,
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
        beta, risk_free, market_premium, beta_raw, beta_clamped, capm_chain = _resolve_discount_inputs_detail(data, **kwargs)
        cost_of_equity = risk_free + beta * market_premium
        if cost_of_equity <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INFEASIBLE,
                notes=[f"Cost of equity {cost_of_equity:.2%} non-positive"],
                data_quality_score=data.quality.data_quality_score,
            )

        # ROE from TTM net income over current book equity.
        # Phase 1.3 — Use unified book equity resolver so BVPS and share count
        # come from the same period / caliber (prevents ROE distortion from
        # mixing a balance-sheet BVPS with a market-snapshot share count).
        book_equity, book_equity_source = _resolve_rim_book_equity(data)
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
        if beta_clamped and beta_raw is not None:
            notes.append(
                f"⚠ β clamped from {beta_raw:.2f} to {beta:.2f} — CAPM ke "
                f"{risk_free + beta_raw * market_premium:.2%} exceeds bank ke band "
                f"{_BANK_KE_BAND[0]:.1%}–{_BANK_KE_BAND[1]:.1%}; "
                "β adjusted to keep ke within band (market section shows raw β)"
            )
        if data.market.current_price:
            spread = (value_per_share - data.market.current_price) / data.market.current_price
            notes.append(f"Price spread vs market: {spread:+.1%}")

        breakdown = {
            "book_value_per_share": b0,
            "book_equity": book_equity,
            "book_equity_source": book_equity_source,
            "roe": roe_0,
            "roe_source": roe_source,
            "beta": beta,
            "beta_raw": beta_raw,
            "beta_clamped": beta_clamped,
            "cost_of_equity": cost_of_equity,
            "capm_chain": capm_chain.as_dict() if capm_chain else None,
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
