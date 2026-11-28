"""Harvest structured, auditable facts for one ticker.

The collector deliberately records raw inputs *and* derived values side by side,
so an audit can recompute rather than trust. It never raises on a per-ticker
failure: a fetch problem is itself a result (DATA_ISSUE), not a crash.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class TickerFacts:
    ticker: str
    fetch_ok: bool = False
    fetch_error: Optional[str] = None

    # ---- raw inputs ----
    price: Optional[float] = None
    market_cap: Optional[float] = None
    total_debt: Optional[float] = None
    cash: Optional[float] = None
    shares_ttm: Optional[float] = None
    shares_market: Optional[float] = None
    revenue: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    ocf: Optional[float] = None
    capex: Optional[float] = None
    fcf_reported: Optional[float] = None
    ebitda: Optional[float] = None
    sbc: Optional[float] = None
    interest_expense: Optional[float] = None
    equity: Optional[float] = None
    currency: Optional[str] = None
    sector: Optional[str] = None
    instrument_type: Optional[str] = None

    # ---- classification ----
    business_type: Optional[str] = None
    is_financial_institution: Optional[bool] = None
    is_reit: Optional[bool] = None
    classification_status: Optional[str] = None
    classification_confidence: Optional[float] = None
    applicable_models: list[str] = field(default_factory=list)
    not_applicable_models: list[str] = field(default_factory=list)
    #: What the financial business does (Bank / PaymentNetwork / FintechLender /
    #: AssetManager / BrokerDealer / Exchange / Insurance / OtherFinancial /
    #: NotFinancial) — the axis model routing keys on.
    financial_business_model: Optional[str] = None
    #: Why that business model was chosen, so routing stays auditable.
    financial_business_model_reason: Optional[str] = None
    #: high / medium / low. "low" means evidence was missing or contradictory.
    financial_business_model_confidence: Optional[str] = None

    # ---- reverse DCF ----
    #: True when the router declined to run ReverseDCF at all (it appeared in
    #: ``not_applicable_models``). This is a *correct* decline, not a failure,
    #: and must never be conflated with "ran and produced no status".
    rd_routed_out: bool = False
    rd_routed_out_reason: Optional[str] = None
    #: Status from calling ReverseDCF directly even when the router skipped it,
    #: so a decline can be verified for the *right reason* (defence in depth).
    rd_direct_status: Optional[str] = None
    rd_direct_notes: list[str] = field(default_factory=list)
    rd_direct_value_per_share: Optional[float] = None
    rd_direct_implied_revenue_cagr: Optional[float] = None
    rd_direct_bound: Optional[dict] = None
    rd_direct_breakdown_keys: list[str] = field(default_factory=list)
    rd_status: Optional[str] = None
    rd_notes: list[str] = field(default_factory=list)
    rd_value_per_share: Optional[float] = None
    rd_enterprise_value: Optional[float] = None
    rd_implied_revenue_cagr: Optional[float] = None
    rd_implied_cagr_bound: Optional[dict] = None
    rd_terminal_growth: Optional[float] = None
    rd_wacc: Optional[float] = None
    rd_horizon: Optional[int] = None
    rd_tv_share: Optional[float] = None
    rd_breakdown_keys: list[str] = field(default_factory=list)

    # ---- reverse DCF audit trail (Stage 3) ----
    #: Verdict separating "solved" from "solved and we believe it".
    rd_growth_band_verdict: Optional[str] = None
    rd_growth_band: Optional[list] = None
    rd_search_band: Optional[list] = None
    rd_solver_meta: dict = field(default_factory=dict)
    rd_projection_vs_reported_fcf: dict = field(default_factory=dict)
    rd_base_fcf: Optional[float] = None
    rd_base_revenue: Optional[float] = None

    # ---- beta chain (Stage 3): raw -> adjusted -> used, never collapsed ----
    beta_raw: Optional[float] = None
    beta_adjusted: Optional[float] = None
    beta_used: Optional[float] = None
    beta_floor_applied: Optional[str] = None
    beta_source: Optional[str] = None
    beta_chain_explain: Optional[str] = None
    #: Beta *selection* inputs. ``beta_adjusted`` is the normalized *selected*
    #: beta, which may be a bottom-up peer beta rather than a shrunk regression
    #: beta -- so "adjusted vs raw" is only meaningful when selection used raw.
    beta_selected: Optional[float] = None
    beta_bottom_up: Optional[float] = None
    beta_shrinkage: Optional[float] = None
    #: Which estimator produced ``beta_selected``: bottom_up | regression | fallback.
    #: Recorded so a bottom-up *selection* is never mistaken for a Blume adjustment.
    beta_selection_method: Optional[str] = None
    #: Blume-only result (None when no shrinkage was applied).
    beta_blume_adjusted: Optional[float] = None
    beta_windows: dict = field(default_factory=dict)
    beta_dispersion: Optional[float] = None
    beta_uncertainty: Optional[str] = None
    #: Date alignment evidence for the regression windows.
    beta_window_spec: Optional[str] = None
    beta_as_of: Optional[str] = None
    beta_benchmark: Optional[str] = None
    beta_n_observations: Optional[int] = None
    beta_missing_periods: Optional[int] = None
    beta_verified: Optional[bool] = None
    risk_free_rate: Optional[float] = None
    equity_risk_premium: Optional[float] = None
    cost_of_equity: Optional[float] = None

    # ---- forward DCF (for round-trip) ----
    dcf_status: Optional[str] = None
    dcf_value_per_share: Optional[float] = None
    dcf_enterprise_value: Optional[float] = None
    dcf_wacc: Optional[float] = None

    # ---- data quality ----
    data_quality_score: Optional[int] = None
    reconciliation_mismatches: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _g(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


def _num(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


async def collect(ticker: str, *, fetch: bool = True) -> TickerFacts:
    """Run the real pipeline for ``ticker`` and capture facts.

    Mirrors ``ValuationPipeline.run`` up to model execution, but keeps the
    objects instead of rendering text, so every number can be audited.
    """
    from classification.ml_classifier import MLHybridClassifier
    from data import DataValidator, FinancialNormalizer, YahooFinanceProvider
    from models.router import ModelRouter

    facts = TickerFacts(ticker=ticker)

    if not fetch:
        facts.fetch_error = "fetch disabled"
        return facts

    try:
        data = await YahooFinanceProvider().get_financial_data(ticker)
    except Exception as e:  # noqa: BLE001 - a fetch failure is a result
        facts.fetch_error = f"{type(e).__name__}: {e}"
        return facts

    facts.fetch_ok = True
    try:
        data = FinancialNormalizer.normalize_all(data)
        data = DataValidator.validate(data)
    except Exception as e:  # noqa: BLE001
        facts.fetch_error = f"normalize/validate failed: {type(e).__name__}: {e}"
        return facts

    ttm = _g(data, "ttm")
    mkt = _g(data, "market")

    facts.price = _num(_g(mkt, "current_price"))
    facts.market_cap = _num(_g(mkt, "market_cap"))
    facts.total_debt = _num(_g(mkt, "total_debt"))
    facts.cash = _num(_g(mkt, "cash"))
    facts.currency = _g(mkt, "currency")
    facts.sector = _g(mkt, "sector")
    facts.instrument_type = _g(mkt, "instrument_type")

    if ttm is not None:
        facts.shares_ttm = _num(_g(ttm, "shares_outstanding"))
        facts.revenue = _num(_g(ttm, "revenue"))
        facts.operating_income = _num(_g(ttm, "operating_income"))
        facts.net_income = _num(_g(ttm, "net_income"))
        facts.ocf = _num(_g(ttm, "operating_cash_flow"))
        facts.capex = _num(_g(ttm, "capital_expenditure"))
        facts.fcf_reported = _num(_g(ttm, "free_cash_flow"))
        facts.ebitda = _num(_g(ttm, "ebitda"))
        facts.sbc = _num(_g(ttm, "stock_based_compensation"))
        facts.interest_expense = _num(_g(ttm, "interest_expense"))
        facts.equity = _num(_g(ttm, "total_equity"))

    if facts.market_cap and facts.price:
        facts.shares_market = facts.market_cap / facts.price

    # ---- classification ----
    try:
        profile = MLHybridClassifier().classify(data)
        facts.business_type = _g(profile, "business_type")
        facts.is_financial_institution = _g(profile, "is_financial_institution")
        facts.is_reit = _g(profile, "is_reit")
        facts.classification_status = _g(profile, "classification_status")
        facts.classification_confidence = _num(_g(profile, "classification_confidence"))
        facts.applicable_models = list(_g(profile, "applicable_models") or [])
        facts.not_applicable_models = list(_g(profile, "not_applicable_models") or [])
        # Classification and routing are recorded as separate axes so a routing
        # change can be told apart from a label change.
        facts.financial_business_model = _g(profile, "financial_business_model")
        facts.financial_business_model_reason = _g(
            profile, "financial_business_model_reason"
        )
        facts.financial_business_model_confidence = _g(
            profile, "financial_business_model_confidence"
        )
    except Exception as e:  # noqa: BLE001
        facts.notes.append(f"classification failed: {type(e).__name__}: {e}")
        return facts

    # ---- models ----
    try:
        results = ModelRouter().run_all(data, profile)
    except Exception as e:  # noqa: BLE001
        facts.notes.append(f"router failed: {type(e).__name__}: {e}")
        return facts

    rd = results.get("ReverseDCF")
    if rd is None:
        # The router declined. Record *why*, and probe the model directly so the
        # decline can be verified as "refused for the right reason" rather than
        # merely "never asked".
        facts.rd_routed_out = "ReverseDCF" in facts.not_applicable_models
        if facts.rd_routed_out:
            reasons = _g(profile, "not_applicable_reasons") or {}
            if isinstance(reasons, dict):
                facts.rd_routed_out_reason = str(reasons.get("ReverseDCF") or "")
            else:
                facts.rd_routed_out_reason = str(reasons)
        try:
            from models.reverse_dcf import ReverseDCFModel

            probe = ReverseDCFModel().run(data, profile)
            facts.rd_direct_status = _g(_g(probe, "status"), "value")
            facts.rd_direct_notes = list(_g(probe, "notes") or [])
            # Capture what the direct probe actually computed, so a routed-out
            # ticker that *would* have solved is visible rather than opaque.
            facts.rd_direct_value_per_share = _num(_g(probe, "value_per_share"))
            pbd = _g(probe, "breakdown") or {}
            facts.rd_direct_implied_revenue_cagr = _num(pbd.get("implied_revenue_cagr"))
            facts.rd_direct_bound = pbd.get("implied_revenue_cagr_bound")
            facts.rd_direct_breakdown_keys = sorted(pbd.keys())
        except Exception as e:  # noqa: BLE001
            facts.rd_direct_notes = [f"direct probe raised: {type(e).__name__}: {e}"]
    else:
        facts.rd_status = _g(_g(rd, "status"), "value")
        facts.rd_notes = list(_g(rd, "notes") or [])
        facts.rd_value_per_share = _num(_g(rd, "value_per_share"))
        facts.rd_enterprise_value = _num(_g(rd, "enterprise_value"))
        facts.data_quality_score = _g(rd, "data_quality_score")
        bd = _g(rd, "breakdown") or {}
        facts.rd_breakdown_keys = sorted(bd.keys())
        facts.rd_implied_revenue_cagr = _num(bd.get("implied_revenue_cagr"))
        facts.rd_implied_cagr_bound = bd.get("implied_revenue_cagr_bound")
        facts.rd_terminal_growth = _num(bd.get("terminal_growth"))
        facts.rd_wacc = _num(bd.get("wacc"))
        facts.rd_horizon = bd.get("horizon")
        facts.rd_tv_share = _num(bd.get("tv_share") or bd.get("terminal_value_share"))
        facts.rd_growth_band_verdict = bd.get("growth_band_verdict")
        facts.rd_growth_band = bd.get("economic_plausibility_band") or bd.get("growth_band")
        facts.rd_search_band = bd.get("solver_search_band")
        facts.rd_solver_meta = bd.get("solver_meta") or {}
        facts.rd_projection_vs_reported_fcf = bd.get("projection_vs_reported_fcf") or {}
        facts.rd_base_fcf = _num(bd.get("base_fcf"))
        facts.rd_base_revenue = _num(bd.get("base_revenue"))

    dcf = results.get("DCF")
    if dcf is not None:
        facts.dcf_status = _g(_g(dcf, "status"), "value")
        facts.dcf_value_per_share = _num(_g(dcf, "value_per_share"))
        facts.dcf_enterprise_value = _num(_g(dcf, "enterprise_value"))
        bd = _g(dcf, "breakdown") or {}
        facts.dcf_wacc = _num(bd.get("wacc"))

    # ---- beta chain: raw -> adjusted -> used, recorded separately ----
    try:
        from valuation.wacc import resolve_effective_beta

        eb = resolve_effective_beta(data, _g(dcf, "breakdown") if dcf else None)
        facts.beta_raw = _num(eb.beta_raw)
        facts.beta_adjusted = _num(eb.beta_adjusted)
        facts.beta_used = _num(eb.beta)
        facts.beta_floor_applied = eb.floor_applied
        facts.beta_source = eb.source
        facts.beta_chain_explain = eb.explain()
    except Exception as e:  # noqa: BLE001
        facts.notes.append(f"beta resolution failed: {type(e).__name__}: {e}")

    mkt = _g(data, "market")
    windows = _g(mkt, "beta_windows") or {}
    if isinstance(windows, dict):
        facts.beta_windows = {str(k): _num(v) for k, v in windows.items() if v is not None}
    vals = [v for v in facts.beta_windows.values() if v is not None]
    facts.beta_dispersion = (max(vals) - min(vals)) if len(vals) >= 2 else None
    try:
        from valuation.wacc import _beta_uncertainty_label

        facts.beta_uncertainty = _beta_uncertainty_label(facts.beta_dispersion)
    except Exception:  # noqa: BLE001
        facts.beta_uncertainty = None
    prov = _g(mkt, "beta_provenance") or {}
    if isinstance(prov, dict):
        # Date alignment is proven by the window bounds + benchmark + sample
        # size, not by a single "as_of" field.
        _spec_bits = [
            str(prov.get("window_label") or ""),
            f"{prov.get('window_start')}..{prov.get('window_end')}"
            if prov.get("window_start") or prov.get("window_end") else "",
            f"vs {prov.get('benchmark')}" if prov.get("benchmark") else "",
            f"n={prov.get('n_observations')}" if prov.get("n_observations") is not None else "",
            str(prov.get("price_basis") or ""),
        ]
        _spec = ", ".join(b for b in _spec_bits if b)
        facts.beta_window_spec = _spec or None
        facts.beta_as_of = str(prov.get("window_end") or "") or None
        facts.beta_benchmark = str(prov.get("benchmark") or "") or None
        facts.beta_n_observations = prov.get("n_observations")
        facts.beta_missing_periods = prov.get("missing_periods")
        facts.beta_verified = prov.get("verified")
    facts.risk_free_rate = _num(_g(mkt, "risk_free_rate"))
    facts.equity_risk_premium = _num(_g(mkt, "equity_risk_premium"))
    _dcf_bd = _g(dcf, "breakdown") if dcf is not None else None
    # ``breakdown`` is a plain dict; ``wacc_breakdown`` inside it is a dataclass.
    _wb = _dcf_bd.get("wacc_breakdown") if isinstance(_dcf_bd, dict) else None
    if _wb is not None:
        facts.risk_free_rate = facts.risk_free_rate or _num(_g(_wb, "risk_free_rate"))
        facts.equity_risk_premium = facts.equity_risk_premium or _num(
            _g(_wb, "equity_risk_premium"))
        facts.cost_of_equity = _num(_g(_wb, "cost_of_equity"))
        # The WACC breakdown carries the *authoritative* beta chain; prefer it
        # over the standalone resolver so the audit sees what actually priced.
        facts.beta_raw = _num(_g(_wb, "beta_raw")) or facts.beta_raw
        facts.beta_adjusted = _num(_g(_wb, "beta_adjusted")) or facts.beta_adjusted
        facts.beta_used = _num(_g(_wb, "beta")) or facts.beta_used
        facts.beta_selected = _num(_g(_wb, "beta_selected"))
        facts.beta_bottom_up = _num(_g(_wb, "beta_bottom_up"))
        facts.beta_shrinkage = _num(_g(_wb, "beta_shrinkage"))
        facts.beta_selection_method = _g(_wb, "beta_selection_method")
        facts.beta_blume_adjusted = _num(_g(_wb, "beta_blume_adjusted"))

    recon = _g(data, "reconciliation")
    if recon is not None:
        mism = _g(recon, "mismatches") or []
        facts.reconciliation_mismatches = [
            str(_g(m, "name") or m) for m in mism
        ]

    return facts


__all__ = ["TickerFacts", "collect"]
