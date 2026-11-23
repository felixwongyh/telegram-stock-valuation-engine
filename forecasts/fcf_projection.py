"""
forecasts/fcf_projection.py - Shared explicit-period FCF / DCF EV projection.

Two projection *bases* live here, and choosing the right one is a precision
question, not a stylistic one:

* **flat** (``project_enterprise_value``) — constant revenue CAGR and constant
  operating margin. Simple, but it is NOT the path the forward DCF values: the
  DCF applies a decaying growth path and a drifting margin. A reverse solve on
  the flat basis therefore answers a different question than "what growth does
  today's price imply *under the DCF's own model*".
* **DCF-path shaped** (``project_enterprise_value_shaped`` +
  ``dcf_projection_shape``) — the exact base-case path the forward DCF projects,
  re-parametrised as ``revenue_t = ttm_rev × (1+g)^t × shape_rev[t]`` and
  ``margin_t = om + margin_offsets[t]``. At ``(g, om) = (base_cagr, om_center)``
  this reproduces the DCF enterprise value to floating-point precision, so a
  reverse DCF solved on this basis is directly comparable with the DCF's own
  base case (same horizon, same growth shape, same margin path, same terminal
  growth).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from data.models import FinancialData
from forecasts.forecast import ForecastEngine
from forecasts.nwc_utils import business_type_from_profile, forecast_nwc_change
from valuation.equity_bridge import enterprise_to_equity

# Unified floor for the Gordon-growth denominator spread (WACC − g). Terminal
# growth is already capped at WACC − 0.5% upstream, so this branch is a safety
# net only; the single constant replaces the previous inconsistent 1e-3 / 1e-4
# floors scattered across dcf.py / fcf_projection.py (Session #16).
MIN_WACC_TG_SPREAD: float = 0.005


@dataclass
class FcfProjectionResult:
    fcf_by_year: List[float]
    last_fcf: float
    pv_explicit: float
    pv_terminal: float
    enterprise_value: float
    # True when the terminal-year FCF is ≤ 0 and the terminal value was
    # suppressed (not sign-flipped). Callers must surface this explicitly.
    terminal_fcf_negative: bool = False
    # Growth actually applied per year (``None`` for a flat-CAGR projection,
    # where every year grows at the single solved CAGR).
    growth_by_year: Optional[List[float]] = None
    operating_margin_by_year: Optional[List[float]] = None


# The forward DCF's own path conventions (ForecastEngine._build_base). They are
# duplicated here as named constants *only* so the reverse solve can reproduce
# that path exactly; the engine remains the single place that defines them for
# forward projections.
DCF_GROWTH_FADE = 0.5      # initial growth fades by 50% linearly over the window
DCF_MARGIN_DRIFT = 0.05    # operating margin fades 5% (relative) per year
DCF_GROWTH_CLAMP_Y0 = (-0.30, 0.60)
DCF_GROWTH_CLAMP_LATER = (-0.20, 0.40)
DCF_MARGIN_CLAMP = (-0.30, 0.60)


def dcf_growth_path(initial_growth: float, horizon: int) -> List[float]:
    """Year-over-year growth path used by the forward DCF base case."""
    out: List[float] = []
    for i in range(max(0, horizon)):
        decay = 1.0 - (i / max(1, horizon)) * DCF_GROWTH_FADE
        g = initial_growth * decay
        lo, hi = DCF_GROWTH_CLAMP_Y0 if i == 0 else DCF_GROWTH_CLAMP_LATER
        out.append(max(lo, min(hi, g)))
    return out


def dcf_margin_path(initial_margin: float, horizon: int) -> List[float]:
    """Operating-margin path used by the forward DCF base case."""
    lo, hi = DCF_MARGIN_CLAMP
    return [
        max(lo, min(hi, initial_margin * (1 - DCF_MARGIN_DRIFT * i)))
        for i in range(max(0, horizon))
    ]


@dataclass
class DcfPathInputs:
    """Fixed FCF-bridge inputs of the forward DCF, plus its path conventions.

    ``base_growth`` / ``base_margin`` are the *year-0* values the forward DCF
    actually uses, so ``(base_growth, base_margin)`` reproduces the DCF EV.
    """
    base_revenue: float
    base_growth: float
    base_margin: float
    tax_rate: float
    da_ratio: float
    capex_ratio: float
    nwc_marginal_ratio: float
    horizon: int



@dataclass
class TerminalValueResult:
    terminal_fcf: float
    terminal_value: float
    pv_terminal_value: float
    suppressed: bool
    inflated: bool
    note: Optional[str]


def gordon_terminal_value(
    last_fcf: Optional[float],
    wacc: float,
    terminal_growth: float,
    discount_years: int,
) -> TerminalValueResult:
    """Single, honest Gordon-growth terminal value used by every FCF model.

    Two defects this fixes (Session #16):

    1. **No silent sign flip.** The old code did
       ``if last_fcf <= 0: last_fcf = avg(abs(fcf_list))`` — a cash-burning
       terminal year was turned into a *positive* number and fed to Gordon
       growth, fabricating a positive terminal value for a company that never
       earns money. Here a non-positive terminal FCF suppresses the terminal
       value (0.0) and sets ``suppressed=True``; callers must mark the result
       APPROXIMATE / "turnaround assumption required" instead of quietly
       inventing value.
    2. **One consistent WACC − g guard.** ``spread <= 0`` uses a single floor
       (``MIN_WACC_TG_SPREAD``) and sets ``inflated=True`` so the caller can warn.
    """
    if last_fcf is None or last_fcf <= 0:
        return TerminalValueResult(
            terminal_fcf=last_fcf if last_fcf is not None else 0.0,
            terminal_value=0.0,
            pv_terminal_value=0.0,
            suppressed=True,
            inflated=False,
            note=(
                "终期 FCF ≤ 0：已抑制终值（不做符号翻转），仅保留显式期现值作为下限；"
                "该估值需明确转型（turnaround）假设才成立"
            ),
        )
    spread = wacc - terminal_growth
    inflated = spread <= 0
    if inflated:
        spread = MIN_WACC_TG_SPREAD
    tv = (last_fcf * (1 + terminal_growth)) / spread
    pv = tv / (1 + wacc) ** max(0, discount_years)
    return TerminalValueResult(
        terminal_fcf=last_fcf,
        terminal_value=tv,
        pv_terminal_value=pv,
        suppressed=False,
        inflated=inflated,
        note=(
            f"WACC ≤ 终值增长率：终值分母已用一致下限 {MIN_WACC_TG_SPREAD:.3%}（终值偏大，需谨慎）"
            if inflated
            else None
        ),
    )


def project_enterprise_value(
    base_revenue: float,
    revenue_cagr: float,
    operating_margin: float,
    tax_rate: float,
    da_ratio: float,
    capex_ratio: float,
    nwc_marginal_ratio: float,
    wacc: float,
    terminal_growth: float,
    horizon: int,
) -> FcfProjectionResult:
    capex_ratio = abs(capex_ratio)
    pv_explicit = 0.0
    rev = base_revenue
    fcf_list: List[float] = []
    last_fcf = 0.0

    for _ in range(horizon):
        prev_rev = rev
        rev *= 1 + revenue_cagr
        op = rev * operating_margin
        nopat = op * (1 - tax_rate)
        da = rev * da_ratio
        capex = rev * capex_ratio
        nwc = forecast_nwc_change(rev - prev_rev, nwc_marginal_ratio)
        fcf = nopat + da - capex - nwc
        fcf_list.append(fcf)
        last_fcf = fcf

    for t, fcf in enumerate(fcf_list, start=1):
        pv_explicit += fcf / (1 + wacc) ** t

    tv_res = gordon_terminal_value(last_fcf, wacc, terminal_growth, horizon)

    return FcfProjectionResult(
        fcf_by_year=fcf_list,
        last_fcf=last_fcf,
        pv_explicit=pv_explicit,
        pv_terminal=tv_res.pv_terminal_value,
        enterprise_value=pv_explicit + tv_res.pv_terminal_value,
        terminal_fcf_negative=tv_res.suppressed,
    )


def project_enterprise_value_flat_margin(
    base_revenue: float,
    revenue_cagr: float,
    fcf_margin: float,
    wacc: float,
    terminal_growth: float,
    horizon: int,
    growth_shape: Optional[Sequence[float]] = None,
) -> FcfProjectionResult:
    """Project EV under a *flat* FCF/revenue margin (``FCF_t = revenue_t × fcf_margin``).

    Bypasses the operating-margin → NOPAT → D&A/CapEx/NWC bridge so that
    ``fcf_margin`` becomes a well-defined, independent solve target for the
    reverse-DCF "implied FCF margin" question (Phase 2, Session #17). Terminal
    value still routes through the single honest ``gordon_terminal_value`` guard.

    ``growth_shape`` lets the caller run the flat margin along the forward DCF's
    own revenue path, so the implied margin is comparable with the DCF's own
    FCF margins rather than with a constant-growth counterfactual.
    """
    g_shape = list(growth_shape) if growth_shape else [1.0] * horizon
    pv_explicit = 0.0
    fcf_list: List[float] = []
    last_fcf = 0.0
    for i in range(horizon):
        shape = g_shape[i] if i < len(g_shape) else 1.0
        rev = base_revenue * (1 + revenue_cagr) ** (i + 1) * shape
        fcf = rev * fcf_margin
        fcf_list.append(fcf)
        last_fcf = fcf

    for t, fcf in enumerate(fcf_list, start=1):
        pv_explicit += fcf / (1 + wacc) ** t

    tv_res = gordon_terminal_value(last_fcf, wacc, terminal_growth, horizon)
    return FcfProjectionResult(
        fcf_by_year=fcf_list,
        last_fcf=last_fcf,
        pv_explicit=pv_explicit,
        pv_terminal=tv_res.pv_terminal_value,
        enterprise_value=pv_explicit + tv_res.pv_terminal_value,
        terminal_fcf_negative=tv_res.suppressed,
    )


def project_enterprise_value_shaped(
    base_revenue: float,
    revenue_cagr: float,
    operating_margin: float,
    tax_rate: float,
    da_ratio: float,
    capex_ratio: float,
    nwc_marginal_ratio: float,
    wacc: float,
    terminal_growth: float,
    horizon: int,
    growth_shape: Optional[Sequence[float]] = None,
    margin_offsets: Optional[Sequence[float]] = None,
) -> FcfProjectionResult:
    """Project EV along the forward DCF's *own* growth / margin path.

    ``revenue_t = base_revenue × (1 + revenue_cagr)^t × shape_rev[t]`` and
    ``margin_t = operating_margin + margin_offsets[t]``, where the shapes come
    from :func:`dcf_projection_shape`. With the DCF's own base growth and base
    margin this reproduces the forward DCF enterprise value exactly, which is
    what makes a reverse solve on this basis comparable with the DCF itself.
    """
    capex_ratio = abs(capex_ratio)
    g_shape = list(growth_shape) if growth_shape else [1.0] * horizon
    m_off = list(margin_offsets) if margin_offsets else [0.0] * horizon

    pv_explicit = 0.0
    fcf_list: List[float] = []
    revs: List[float] = []
    margins: List[float] = []
    rev_prev = base_revenue
    last_fcf = 0.0

    for i in range(horizon):
        shape = g_shape[i] if i < len(g_shape) else 1.0
        rev = base_revenue * (1 + revenue_cagr) ** (i + 1) * shape
        om = operating_margin + (m_off[i] if i < len(m_off) else 0.0)
        nopat = rev * om * (1 - tax_rate)
        da = rev * da_ratio
        capex = rev * capex_ratio
        nwc = forecast_nwc_change(rev - rev_prev, nwc_marginal_ratio)
        fcf = nopat + da - capex - nwc
        fcf_list.append(fcf)
        revs.append(rev)
        margins.append(om)
        rev_prev = rev
        last_fcf = fcf

    for t, fcf in enumerate(fcf_list, start=1):
        pv_explicit += fcf / (1 + wacc) ** t

    tv_res = gordon_terminal_value(last_fcf, wacc, terminal_growth, horizon)
    return FcfProjectionResult(
        fcf_by_year=fcf_list,
        last_fcf=last_fcf,
        pv_explicit=pv_explicit,
        pv_terminal=tv_res.pv_terminal_value,
        enterprise_value=pv_explicit + tv_res.pv_terminal_value,
        terminal_fcf_negative=tv_res.suppressed,
        growth_by_year=[
            (revs[i] / (revs[i - 1] if i else base_revenue)) - 1
            for i in range(len(revs))
        ],
        operating_margin_by_year=margins,
    )


def dcf_projection_shape(
    base_revenue: float,
    base_growth: float,
    base_margin: float,
    horizon: int,
) -> tuple:
    """Shapes that make ``project_enterprise_value_shaped`` reproduce the DCF path.

    Returns ``(effective_cagr, shape_rev, margin_offsets, om_center)`` where
    ``effective_cagr`` is the *terminal-consistent* CAGR of the DCF's own
    revenue path and ``om_center`` the mean operating margin. Solving for
    ``effective_cagr`` at the DCF's base margin reproduces the DCF EV exactly;
    reporting it (rather than the year-0 growth) keeps "implied growth" a
    like-for-like comparison with the DCF's own growth assumption.
    """
    growths = dcf_growth_path(base_growth, horizon)
    margins = dcf_margin_path(base_margin, horizon)
    if not growths or base_revenue <= 0:
        return base_growth, [1.0] * max(0, horizon), [0.0] * max(0, horizon), base_margin

    revs: List[float] = []
    rev = base_revenue
    for g in growths:
        rev *= 1 + g
        revs.append(rev)

    last_rev = revs[-1]
    if last_rev <= 0:
        return base_growth, [1.0] * horizon, [0.0] * horizon, base_margin

    eff_cagr = (last_rev / base_revenue) ** (1.0 / horizon) - 1.0
    om_center = sum(margins) / len(margins)
    shape_rev = [
        revs[i] / (base_revenue * (1.0 + eff_cagr) ** (i + 1))
        for i in range(horizon)
    ]
    margin_offsets = [margins[i] - om_center for i in range(horizon)]
    return eff_cagr, shape_rev, margin_offsets, om_center


def dcf_path_inputs_from_data(
    data: FinancialData,
    profile: Any,
    horizon: int,
) -> Optional[DcfPathInputs]:
    """Extract the forward DCF's fixed inputs + its year-0 growth/margin.

    Reads the same history the forward DCF reads (``ForecastEngine``), so the
    returned ``base_growth`` / ``base_margin`` are the values the DCF actually
    applies in year 0 — not an independent re-derivation.
    """
    ttm = data.ttm
    if ttm is None or ttm.revenue is None or ttm.revenue <= 0 or horizon < 1:
        return None
    eng = ForecastEngine(
        horizon_years=horizon,
        business_type=business_type_from_profile(profile),
    )
    hist_rev_cagr, _gm, hist_om, da_ratio, capex_ratio, nwc_ratio, tax_rate = (
        eng._extract_history(data)
    )
    growths = dcf_growth_path(hist_rev_cagr, horizon)
    margins = dcf_margin_path(hist_om, horizon)
    return DcfPathInputs(
        base_revenue=ttm.revenue,
        base_growth=growths[0] if growths else hist_rev_cagr,
        base_margin=margins[0] if margins else hist_om,
        tax_rate=tax_rate,
        da_ratio=da_ratio,
        capex_ratio=capex_ratio,
        nwc_marginal_ratio=nwc_ratio,
        horizon=horizon,
    )


def project_enterprise_value_from_data(
    data: FinancialData,
    profile: Any,
    revenue_cagr: float,
    operating_margin: Optional[float],
    wacc: float,
    terminal_growth: float,
    horizon: int,
    shaped: bool = True,
    nwc_ratio_override: Optional[float] = None,
) -> Optional[FcfProjectionResult]:
    """Project EV from a ``FinancialData`` snapshot.

    ``shaped=True`` (default) follows the forward DCF's own decaying-growth /
    drifting-margin path, so a solve on this basis is directly comparable with
    the DCF. ``shaped=False`` keeps the legacy flat-CAGR behaviour for callers
    that deliberately want a constant-growth sensitivity surface.

    ``nwc_ratio_override`` replaces the inferred marginal ΔNWC ratio. Used only
    to probe how sensitive a conclusion is to that inference (it is a residual,
    so it is the least reliable projection input).
    """
    inputs = dcf_path_inputs_from_data(data, profile, horizon)
    if inputs is None:
        return None
    nwc_ratio = (
        inputs.nwc_marginal_ratio
        if nwc_ratio_override is None
        else nwc_ratio_override
    )
    om = operating_margin if operating_margin is not None else inputs.base_margin
    if not shaped:
        return project_enterprise_value(
            inputs.base_revenue,
            revenue_cagr,
            om,
            inputs.tax_rate,
            inputs.da_ratio,
            inputs.capex_ratio,
            nwc_ratio,
            wacc,
            terminal_growth,
            horizon,
        )
    eff_cagr, shape_rev, margin_offsets, om_center = dcf_projection_shape(
        inputs.base_revenue, inputs.base_growth, inputs.base_margin, horizon
    )
    if operating_margin is None:
        # Preserve the DCF's drifting margin around its own mean.
        return project_enterprise_value_shaped(
            inputs.base_revenue,
            revenue_cagr,
            om_center,
            inputs.tax_rate,
            inputs.da_ratio,
            inputs.capex_ratio,
            nwc_ratio,
            wacc,
            terminal_growth,
            horizon,
            growth_shape=shape_rev,
            margin_offsets=margin_offsets,
        )
    return project_enterprise_value_shaped(
        inputs.base_revenue,
        revenue_cagr,
        om,
        inputs.tax_rate,
        inputs.da_ratio,
        inputs.capex_ratio,
        nwc_ratio,
        wacc,
        terminal_growth,
        horizon,
        growth_shape=shape_rev,
    )


def equity_value_per_share(
    data: FinancialData,
    profile: Any,
    revenue_cagr: float,
    operating_margin: Optional[float],
    wacc: float,
    terminal_growth: float,
    horizon: int,
) -> Optional[float]:
    ttm = data.ttm
    if ttm is None or ttm.shares_outstanding is None or ttm.shares_outstanding <= 0:
        return None
    proj = project_enterprise_value_from_data(
        data, profile, revenue_cagr, operating_margin, wacc, terminal_growth, horizon
    )
    if proj is None:
        return None
    eq = enterprise_to_equity(proj.enterprise_value, data.market).equity_value
    if eq is None:
        return None
    return eq / ttm.shares_outstanding


def fcf_cagr_from_projection(fcf_list: List[float], horizon: int) -> Optional[float]:
    if not fcf_list or horizon < 1:
        return None
    start = fcf_list[0]
    end = fcf_list[-1]
    if start is None or end is None or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / horizon) - 1


__all__ = [
    "FcfProjectionResult",
    "TerminalValueResult",
    "MIN_WACC_TG_SPREAD",
    "equity_value_per_share",
    "fcf_cagr_from_projection",
    "gordon_terminal_value",
    "DCF_GROWTH_FADE",
    "DCF_MARGIN_DRIFT",
    "DcfPathInputs",
    "dcf_growth_path",
    "dcf_margin_path",
    "dcf_path_inputs_from_data",
    "dcf_projection_shape",
    "project_enterprise_value",
    "project_enterprise_value_flat_margin",
    "project_enterprise_value_from_data",
    "project_enterprise_value_shaped",
]


@dataclass
class GrowthValueAttribution:
    """How each cash-flow component contributes to dEV/dg.

    ``EV`` is *linear* in the additive FCF components
    (``FCF = NOPAT + D&A − CapEx − ΔNWC``), so the change in EV caused by a
    growth change decomposes exactly into these parts — no interaction terms and
    no counterfactual re-solving. That matters because a naive "zero this input
    and re-solve" decomposition is order-dependent and can flip the sign of the
    total; an exact additive split cannot.

    All values are the change in enterprise value between ``g_lo`` and ``g_hi``.
    """

    g_lo: float
    g_hi: float
    total: float
    nopat: float
    da: float
    capex: float
    nwc: float
    terminal: float
    # Share of |total| contributed by the largest offsetting component; a large
    # value means the sign of dEV is a near-cancellation of opposing forces and
    # is therefore fragile to the inputs that set them.
    cancellation_ratio: float

    def as_dict(self) -> dict:
        return {
            "g_lo": self.g_lo,
            "g_hi": self.g_hi,
            "total": self.total,
            "nopat": self.nopat,
            "da": self.da,
            "capex": self.capex,
            "nwc": self.nwc,
            "terminal": self.terminal,
            "cancellation_ratio": self.cancellation_ratio,
        }


def _component_pv(
    base_revenue: float,
    revenue_cagr: float,
    operating_margin: float,
    tax_rate: float,
    da_ratio: float,
    capex_ratio: float,
    nwc_marginal_ratio: float,
    wacc: float,
    terminal_growth: float,
    horizon: int,
    growth_shape: Optional[Sequence[float]],
    margin_offsets: Optional[Sequence[float]],
) -> dict:
    """PV of each FCF component, plus the PV of the terminal value."""
    capex_ratio = abs(capex_ratio)
    g_shape = list(growth_shape) if growth_shape else [1.0] * horizon
    m_off = list(margin_offsets) if margin_offsets else [0.0] * horizon

    pv_nopat = pv_da = pv_capex = pv_nwc = 0.0
    rev_prev = base_revenue
    last_fcf = 0.0
    for i in range(horizon):
        shape = g_shape[i] if i < len(g_shape) else 1.0
        rev = base_revenue * (1 + revenue_cagr) ** (i + 1) * shape
        om = operating_margin + (m_off[i] if i < len(m_off) else 0.0)
        disc = (1 + wacc) ** (i + 1)
        nopat = rev * om * (1 - tax_rate)
        da = rev * da_ratio
        capex = rev * capex_ratio
        nwc = forecast_nwc_change(rev - rev_prev, nwc_marginal_ratio)
        pv_nopat += nopat / disc
        pv_da += da / disc
        pv_capex += capex / disc
        pv_nwc += nwc / disc
        last_fcf = nopat + da - capex - nwc
        rev_prev = rev

    tv_res = gordon_terminal_value(last_fcf, wacc, terminal_growth, horizon)
    return {
        "nopat": pv_nopat,
        "da": pv_da,
        "capex": pv_capex,
        "nwc": pv_nwc,
        "terminal": tv_res.pv_terminal_value,
    }


def attribute_growth_value(
    base_revenue: float,
    operating_margin: float,
    tax_rate: float,
    da_ratio: float,
    capex_ratio: float,
    nwc_marginal_ratio: float,
    wacc: float,
    terminal_growth: float,
    horizon: int,
    g_lo: float,
    g_hi: float,
    growth_shape: Optional[Sequence[float]] = None,
    margin_offsets: Optional[Sequence[float]] = None,
) -> GrowthValueAttribution:
    """Exact additive attribution of ``EV(g_hi) − EV(g_lo)`` by FCF component."""
    lo = _component_pv(
        base_revenue, g_lo, operating_margin, tax_rate, da_ratio, capex_ratio,
        nwc_marginal_ratio, wacc, terminal_growth, horizon,
        growth_shape, margin_offsets,
    )
    hi = _component_pv(
        base_revenue, g_hi, operating_margin, tax_rate, da_ratio, capex_ratio,
        nwc_marginal_ratio, wacc, terminal_growth, horizon,
        growth_shape, margin_offsets,
    )
    # FCF = NOPAT + D&A − CapEx − ΔNWC, so the last two components reduce EV
    # as they rise. The PVs above are unsigned magnitudes; apply the FCF signs
    # here so the split stays additive and reproduces EV(g_hi) − EV(g_lo).
    signs = {"nopat": 1.0, "da": 1.0, "capex": -1.0, "nwc": -1.0, "terminal": 1.0}
    parts = {k: (hi[k] - lo[k]) * signs[k] for k in lo}
    total = sum(parts.values())
    gross = sum(abs(v) for v in parts.values())
    # A total that is small relative to the gross movement is a cancellation:
    # its *sign* is the fragile part, even when its magnitude is stable.
    cancellation = (gross / abs(total)) if abs(total) > 1e-12 else float("inf")
    return GrowthValueAttribution(
        g_lo=g_lo,
        g_hi=g_hi,
        total=total,
        nopat=parts["nopat"],
        da=parts["da"],
        capex=parts["capex"],
        nwc=parts["nwc"],
        terminal=parts["terminal"],
        cancellation_ratio=cancellation,
    )
