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
    CURRENCY_NOMINAL_GDP,
    CURRENCY_RISK_FREE_RATES,
    DEFAULT_DCF_CONFIG,
    DEFAULT_MACRO_CURRENCY,
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
    # NOTE: the substring must be "Utilities" — the plural is what appears in
    # Yahoo's sector/industry strings ("Utilities", "Utilities—Independent Power
    # Producers"). The previous singular "Utility" never matched the plural, so
    # every utility silently fell through to the market-average default band
    # (P0-1). Kept both forms because some providers emit the singular.
    "Utilities":        (0.055, 0.085, "Utilities"),
    "Utility":          (0.055, 0.085, "Utilities"),
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


# Canonical Taxonomy Key → industry WACC reference band (P0-1).
#
# Preferred over the substring table above: a canonical key is an *exact
# economic identity*, not a bag of words. This matters most for Utilities,
# where a regulated electric utility (rate-base, allowed ROE, near-bond risk)
# and an independent / merchant power producer (commodity-price and volumetric
# risk, no guaranteed return) are different economic models and must NOT share
# one band. Reading the band off the identity key also removes the
# "Utility" vs "Utilities" substring trap by construction.
#
# Only keys whose band must differ from — or be pinned independently of — the
# keyword table are listed here; every other identity falls back to the
# (dash-normalized) keyword table, then the market-average default.
CANONICAL_KEY_WACC_RANGES: Dict[str, Tuple[float, float, str]] = {
    "util":             (0.055, 0.085, "Utilities"),
    "util.generic":     (0.055, 0.085, "Utilities (unspecified)"),
    "util.electric":    (0.050, 0.078, "Regulated Electric Utility"),
    "util.gas":         (0.048, 0.075, "Regulated Gas Utility"),
    "util.water":       (0.045, 0.072, "Regulated Water Utility"),
    # Merchant / IPP: higher cost of capital than regulated peers (no rate base,
    # commodity + volume exposure) → deliberately above the regulated band.
    "util.ipp":         (0.065, 0.098, "Independent Power Producer (Merchant)"),
    "util.diversified": (0.055, 0.085, "Diversified / Integrated Utility"),
    "en.oil_gas.integrated": (0.070, 0.100, "Integrated Energy"),
}


def _normalize_industry_text(text: Optional[str]) -> str:
    """Lower-case and unify dashes so provider strings match the tables.

    Yahoo emits en/em dashes without surrounding spaces ("Utilities—Independent
    Power Producers") while the mapping tables use " - " (space-hyphen-space).
    Normalizing both sides — and dropping spaces around hyphens — lets an exact
    identity match survive that formatting difference.
    """
    t = (text or "").lower().strip()
    t = t.replace("\u2014", "-").replace("\u2013", "-")
    t = t.replace(" - ", "-").replace("- ", "-").replace(" -", "-")
    return t


def _beta_uncertainty_label(dispersion: Optional[float]) -> str:
    """Map window β dispersion (max−min) to a coarse uncertainty label (P1-6)."""
    if dispersion is None:
        return "unknown"
    if dispersion <= BETA_DISPERSION_SHRINK_THRESHOLD:
        return "low"
    if dispersion <= 1.0:
        return "medium"
    return "high"


# ---- Beta methodology divergence (Phase E) --------------------------------
# Judging β uncertainty ONLY from the regression-window range is wrong when the
# β actually fed to CAPM is a bottom-up (peer-derived) estimate: a stable
# 3-window regression can still disagree sharply with the peer-derived β, and
# that disagreement is a *methodology* divergence that must be surfaced instead
# of hidden behind a "低不确定性" label.
#
# M-67: the peer floor is no longer one global number. It is calibrated by
# *peer-pool breadth* via `threshold_calibration.beta_min_peers_for()` — a deep
# public pool must supply more names before its median is reliable, while a
# niche archetype (neobank / fintech / conglomerate) is honestly judged on a
# smaller floor. BETA_BOTTOM_UP_MIN_PEERS is kept as the neutral default used
# when no archetype is supplied (equals the unknown-pool floor).
BETA_BOTTOM_UP_MIN_PEERS: int = 4           # neutral default (unknown pool breadth)
BETA_METHOD_DIVERGENCE_MINOR: float = 0.15   # |bottom-up − regression| / |regression|
BETA_METHOD_DIVERGENCE_MATERIAL: float = 0.30


def _bottom_up_reliability_label(
    beta_bottom_up: Optional[float],
    chain: Optional[Dict[str, Any]],
    business_type: Any = None,
) -> str:
    """Peer-sample quality behind a bottom-up β (Phase E, calibrated M-67).

    Levels mirror ``data.industry_beta``: 0 = segment-weighted, 1 = exact peer
    sub-industry, 2 = adjacent-industry, 3 = Damodaran benchmark (no live peers).

    ``business_type`` selects the archetype's peer floor (M-67); without it the
    neutral default floor is used, so the label is never silently tightened for
    an unmapped archetype.
    """
    if beta_bottom_up is None:
        return "n/a"
    chain = chain or {}
    level = chain.get("level")
    n_peers = chain.get("n_peers") or 0
    if business_type is None:
        min_peers = BETA_BOTTOM_UP_MIN_PEERS
    else:
        # Imported lazily: ``analysis`` (package __init__) pulls the valuation
        # model graph, so a module-level import here would make ``models.dcf``
        # → ``valuation.wacc`` → ``analysis`` → ``models.reverse_dcf`` →
        # ``models.dcf`` a circular import.
        from analysis.threshold_calibration import beta_min_peers_for

        min_peers = beta_min_peers_for(business_type)
    if level == 0:  # segment-weighted aggregate
        return "high" if n_peers >= min_peers else "medium"
    if level == 1:
        if n_peers >= min_peers:
            return "high"
        # One name short of the archetype floor is still worth a "medium" label
        # (the floor itself may be 3 for a niche pool); below that, review.
        if n_peers >= max(1, min_peers - 1):
            return "medium"
        return "requires_review"
    if level == 2:
        return "medium"
    return "requires_review"  # level 3 benchmark / unknown → no live peer evidence


def _methodology_divergence_label(
    beta_regression: Optional[float], beta_bottom_up: Optional[float]
) -> str:
    """Divergence between the regression β and the bottom-up β (Phase E)."""
    if beta_regression is None or beta_bottom_up is None or beta_bottom_up == 0:
        return "n/a"
    base = abs(float(beta_regression))
    if base < 1e-9:
        return "n/a"
    gap = abs(float(beta_bottom_up) - float(beta_regression)) / base
    if gap >= BETA_METHOD_DIVERGENCE_MATERIAL:
        return "material"
    if gap >= BETA_METHOD_DIVERGENCE_MINOR:
        return "minor"
    return "none"



def _format_beta_source(prov: Optional[Dict[str, Any]], beta_value: float) -> str:
    """Render an honest β source label from recorded provenance.

    Phase 1 — Beta Source & Provenance: WACC used to hard-code "3Y monthly vs SPY
    estimate" regardless of how ``beta`` was actually obtained. This renders only
    what the provenance dict *proves*: the regression method, window start/end,
    price basis, benchmark and observation count. When provenance is missing it
    says so explicitly rather than asserting a method it cannot verify.
    """
    prov = prov or {}
    src = prov.get("source")
    if src == "regression":
        wl = prov.get("window_label") or "regression"
        basis = prov.get("price_basis") or "unknown basis"
        bench = prov.get("benchmark") or "SPY"
        start = prov.get("window_start")
        end = prov.get("window_end")
        span = f"{start}→{end}" if start and end else "window n/a"
        n = prov.get("n_observations")
        gaps = prov.get("missing_periods")
        detail = f"{n} obs" if n is not None else "obs n/a"
        if gaps:
            detail += f", {int(gaps)} gap(s)"
        return (
            f"Regression β ({wl}, {basis}, vs {bench}) {span}, {detail} = {beta_value:.3f}"
        )
    if src == "provider":
        return f"Provider β (Yahoo vendor estimate, method unverified) = {beta_value:.3f}"
    return f"β source unverified (no provenance recorded) = {beta_value:.3f}"


def currency_macro_anchors(currency: Optional[str]) -> Tuple[float, float]:
    """Return ``(risk_free_anchor, nominal_gdp_ceiling)`` for a cash-flow currency.

    Keeps the Rf ↔ inflation ↔ terminal-growth triangle on ONE currency, so a DCF
    for HKD/CNY/MYR cash flows is not discounted at the USD rate while its
    terminal growth is capped at US nominal GDP. Unknown currencies fall back to
    the USD band (documented, not silent).
    """
    ccy = (currency or DEFAULT_MACRO_CURRENCY).upper()
    rf = CURRENCY_RISK_FREE_RATES.get(ccy, CURRENCY_RISK_FREE_RATES[DEFAULT_MACRO_CURRENCY])
    gdp = CURRENCY_NOMINAL_GDP.get(ccy, CURRENCY_NOMINAL_GDP[DEFAULT_MACRO_CURRENCY])
    return float(rf), float(gdp)


# CAPM beta winsorization band. Regression betas outside this band (e.g. a
# negative beta for a low-beta staple, or an extreme high-beta reading) produce
# an implausible cost of equity, so WACC clamps them. Exposed as constants so the
# report can annotate the *displayed* raw beta with the value actually used.
BETA_WINSOR_LO: float = 0.30
BETA_WINSOR_HI: float = 2.50

# ---- Multi-window beta stability (P1-6) -----------------------------------
# A single regression beta hides how unstable the estimate is across sampling
# windows (e.g. 2Y weekly vs 3Y/5Y monthly). When windows disagree beyond
# ``BETA_DISPERSION_SHRINK_THRESHOLD`` the estimate is treated as noisy and
# shrunk toward the market average (β = 1.0) — the standard Blume-style
# correction. We deliberately do NOT simply average the windows: they differ in
# observation frequency and sample length, so a raw average is not a valid
# estimator. Shrinkage scales linearly with the excess dispersion and is capped
# at ``BETA_MAX_SHRINK`` so a genuinely high-beta company is not flattened.
BETA_DISPERSION_SHRINK_THRESHOLD: float = 0.50
BETA_MAX_SHRINK: float = 0.35


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
    # How the sanity band was resolved (P0-1): canonical taxonomy key vs the
    # legacy keyword table vs the market-average default. Kept so a band that
    # fell through to the default is visible, not silent.
    industry_range_source: str = ""
    # Which period caliber the ETR used: "ttm" | "fyN" | "default" (P0-2).
    tax_period_basis: str = ""
    sources: Dict[str, str] = field(default_factory=dict)  # field → how it was computed
    cost_of_debt_implied_raw: Optional[float] = None  # before Rf floor / cap (audit)
    # ---- CAPM Engine integration (Phase 2.2) -------------------------------
    # Raw CAPM ke (rf + raw_beta × erp) preserved for audit. ``cost_of_equity``
    # is the adjusted valuation ke (which may differ from raw_capm_ke due to
    # winsorization, bottom-up selection, or shrinkage).
    raw_capm_ke: Optional[float] = None
    capm_chain: Optional[Dict[str, Any]] = None  # full BetaChain audit trail
    # ---- Beta transparency (Session #07 / #25) ----------------------------
    beta_raw: Optional[float] = None          # regression beta before winsorizing
    beta_bottom_up: Optional[float] = None    # bottom-up β used by CAPM, if sourced
    beta_bottom_up_note: Optional[str] = None  # full peer-chain audit (M-34)
    # ---- Beta multi-window sensitivity (Phase 3.1 / P1-6) -----------------
    beta_windows: Optional[Dict[str, float]] = None  # window label → regression β
    beta_dispersion: Optional[float] = None          # max−min across available windows
    beta_selected: Optional[float] = None     # base β chosen before shrinkage (P1-6)
    beta_adjusted: Optional[float] = None     # final β after winsorize + shrinkage
    beta_shrinkage: float = 0.0               # weight pulled toward market β=1.0
    #: Which estimator ``beta_selected`` came from. This must be explicit: a
    #: bottom-up β *replacing* the regression β is a selection decision, NOT a
    #: Blume adjustment, and conflating the two makes the audit trail wrong.
    beta_selection_method: Optional[str] = None   # bottom_up | regression | fallback
    #: Blume-only value: ``(1-shrink)*winsor(β_selected) + shrink*1.0``.
    #: Equals ``beta_adjusted`` when shrinkage ran; ``None`` when it did not, so
    #: "no shrinkage" is distinguishable from "shrinkage of zero".
    beta_blume_adjusted: Optional[float] = None
    beta_uncertainty: str = "unknown"         # low | medium | high | unknown
    # ---- Beta reliability — three independent indicators (Phase E) ---------
    # The report must NOT collapse β confidence into the regression-window range
    # alone. Each dimension is labelled separately so a stable regression cannot
    # mask a material disagreement with the peer-derived β.
    beta_regression_stability: str = "unknown"      # window β stability
    beta_bottom_up_reliability: str = "n/a"         # peer-sample quality
    beta_methodology_divergence: str = "n/a"        # regression vs bottom-up gap
    # WACC re-valued at the window β band, so β uncertainty propagates into a
    # WACC range (not just a report reminder).
    wacc_beta_lo: Optional[float] = None
    wacc_beta_hi: Optional[float] = None
    # ---- β source provenance (Phase 1 — Beta Source & Provenance) ----------
    # Records HOW the scalar β was obtained (provider vs self-computed regression,
    # method, window, price basis, observation count). A missing dict means
    # "unverified" and the report must not assert a method it cannot prove.
    beta_provenance: Optional[Dict[str, Any]] = None
    # ---- WACC raw vs clamped (Phase 1 — WACC Clamp Separation) -------------
    # The clamp to [min_wacc, max_wacc] is a guard-rail, NOT a result. Keeping the
    # raw computed WACC and the clamp reason separate prevents a report from
    # presenting the floored/capped value as if the model had produced it.
    wacc_raw: Optional[float] = None
    wacc_clamped: bool = False
    wacc_clamp_reason: Optional[str] = None
    # ---- Currency consistency (Phase 1 — Currency-aware Rf) ----------------
    # Which cash-flow currency the Rf was matched to, and that currency's
    # long-run nominal-GDP ceiling (kept so terminal growth can be capped on the
    # SAME currency, not the US one). ``risk_free_currency_note`` surfaces a
    # substituted / unknown-currency Rf as a valuation caveat.
    risk_free_currency: str = ""
    nominal_gdp_ceiling: Optional[float] = None
    risk_free_currency_note: Optional[str] = None

    def wacc_clamp_note(self) -> Optional[str]:
        """Surface a clamp as a valuation-risk flag, not a normal result (Phase 1)."""
        if not self.wacc_clamped or self.wacc_raw is None:
            return None
        return (
            f"⚠ WACC 被钳制：模型原始计算值 {self.wacc_raw:.2%}，"
            f"最终采用 {self.wacc:.2%}（{self.wacc_clamp_reason}）。"
            "该最终值并非模型真实输出，估值对其高度敏感，应视为估值风险而非正常结果。"
        )

    def beta_transparency_note(self) -> str:
        """Show raw vs selected vs adjusted vs bottom-up beta so it is auditable."""
        parts = []
        if self.beta_raw is not None:
            parts.append(f"raw β = {self.beta_raw:.2f}")
        if self.beta_selected is not None and (
            self.beta_selected != self.beta_raw or self.beta_shrinkage > 0
        ):
            parts.append(f"selected β = {self.beta_selected:.2f}")
        if self.beta_shrinkage > 0:
            parts.append(
                f"adjusted β = {self.beta_adjusted:.2f}"
                f"（向市场均值 1.0 收缩 {self.beta_shrinkage:.0%}，用于 CAPM）"
            )
        elif self.beta_adjusted is not None and self.beta_adjusted != self.beta_selected:
            parts.append(f"adjusted β = {self.beta_adjusted:.2f}（winsorize 后用于 CAPM）")
        else:
            parts.append(f"winsorized β = {self.beta:.2f}（用于 CAPM）")
        if self.beta_bottom_up is not None:
            parts.append(self.beta_bottom_up_note or f"bottom-up β = {self.beta_bottom_up:.2f}")
        else:
            parts.append("bottom-up β = N/A（无同行 β 数据源）")
        return "；".join(parts)

    def beta_uncertainty_note(self) -> Optional[str]:
        """State β reliability across THREE indicators + the WACC range (Phase E).

        Regression Stability, Bottom-up Reliability and Methodology Divergence
        are reported separately so a stable regression window cannot make a
        material regression-vs-bottom-up disagreement read as "低不确定性".
        """
        if (
            self.beta_uncertainty in ("unknown", "")
            and self.wacc_beta_lo is None
            and self.beta_methodology_divergence in ("n/a", "")
        ):
            return None
        _stab = {"low": "低", "medium": "中", "high": "高", "unknown": "未知"}
        # The stored value is an *uncertainty* level, so the heading must name
        # uncertainty: "Regression Stability: 低" read as "stability is low",
        # the opposite of a low-dispersion window set.
        _stab_interp = {"low": "窗口间稳定", "medium": "窗口间中度波动",
                        "high": "窗口间波动较大", "unknown": "不可判定"}
        _bu = {"high": "可信", "medium": "中等", "requires_review": "需要复核", "n/a": "不适用"}
        _div = {"none": "一致", "minor": "轻微分歧", "material": "显著分歧", "n/a": "不适用"}
        stab = self.beta_regression_stability or self.beta_uncertainty
        bits = [
            f"Regression Stability（回归窗口不确定性）: "
            f"{_stab.get(stab, stab)}（{_stab_interp.get(stab, '不可判定')}）",
            f"Bottom-up Reliability（同业可靠性）: "
            f"{_bu.get(self.beta_bottom_up_reliability, self.beta_bottom_up_reliability)}",
            f"Methodology Divergence（方法分歧）: "
            f"{_div.get(self.beta_methodology_divergence, self.beta_methodology_divergence)}",
            f"Selected Beta（采用值）: {self.beta:.2f}",
        ]
        if self.beta_dispersion is not None:
            bits.append(f"窗口极差 {self.beta_dispersion:.2f}")
        if self.wacc_beta_lo is not None and self.wacc_beta_hi is not None:
            bits.append(
                f"→ 由 β 不确定性推算的 WACC 区间 [{self.wacc_beta_lo:.2%}, {self.wacc_beta_hi:.2%}]"
                "（敏感性参考；DCF 仍以采用值单点折现）"
            )
        return "；".join(bits)

    def beta_window_note(self) -> Optional[str]:
        """Sensitivity note across regression windows (2Y weekly / 3Y & 5Y monthly).

        Returns ``None`` when fewer than two windows resolved — a single window
        cannot evidence *stability*, so the report must not imply it does.
        """
        wins = {k: v for k, v in (self.beta_windows or {}).items() if v is not None}
        if len(wins) < 2:
            return None
        lo, hi = min(wins.values()), max(wins.values())
        detail = "，".join(f"{k}={v:.2f}" for k, v in wins.items())
        span = hi - lo
        # Wording must agree with the coarse uncertainty label used by
        # ``beta_uncertainty_note`` for the SAME dispersion; a stricter threshold
        # here made one object print "中度波动" and "波动较大" side by side.
        _lbl = _beta_uncertainty_label(span)
        stability = {
            "low": "窗口间稳定",
            "medium": "窗口间中度波动",
            "high": "窗口间波动较大（β 随取样窗口显著变化，结论对该假设敏感）",
        }.get(_lbl, "不可判定")
        return f"多窗口 β 敏感性（{len(wins)} 个窗口）：{detail}（极差 {span:.2f}）→ {stability}"

    def wacc_range_note(self) -> Optional[str]:
        """When WACC sits outside the industry band, recommend a range, not a point."""
        if self.sanity_status not in ("Above Range", "Below Range"):
            return None
        return (
            f"WACC {self.wacc:.2%} 超出行业区间 "
            f"[{self.industry_range_min:.2%}, {self.industry_range_max:.2%}]；"
            f"高估/低估结论对该 WACC 敏感，建议以区间复核而非单点"
        )

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


@dataclass
class EffectiveBeta:
    """Single authoritative β export shared by WACC / risk flags / report.

    Before this, the market section displayed the raw regression β, the risk
    flag read `data.market.beta` (also raw), and WACC used its own winsorized
    value — three different "β" in one report. `resolve_effective_beta()` is
    now the one place that decides which β is used, and everyone consumes it.
    """

    beta: float                              # value actually used (winsorized, CAPM-usable)
    beta_raw: Optional[float] = None         # provider regression β before clamping
    source: str = ""                         # human-readable provenance
    clamped: bool = False                    # raw β sat outside the CAPM band
    origin: str = "provider"                 # wacc_breakdown | provider | fallback
    beta_adjusted: Optional[float] = None    # risk-adjusted (Blume) before the band
    floor_applied: Optional[str] = None      # "lo" / "hi" when the band bound the value
    floor_reason: str = ""                   # why the floor/cap bound the β

    @property
    def used_beta(self) -> float:
        """The β that actually prices equity — the only one valuation may use."""
        return self.beta

    def explain(self) -> str:
        """One-line audit trail: raw → adjusted → used, with the band reason.

        ``raw`` must never be lost: a report that shows only 0.30 for a name whose
        regression β is −0.03 is asserting a risk profile the data does not
        support, so the chain is always reconstructable.
        """
        parts = [f"raw β={self.beta_raw:.3f}" if self.beta_raw is not None else "raw β=n/a"]
        if self.beta_adjusted is not None and (
            self.beta_raw is None or abs(self.beta_adjusted - self.beta_raw) > 1e-9
        ):
            parts.append(f"adjusted β={self.beta_adjusted:.3f}")
        parts.append(f"used β={self.beta:.3f}")
        if self.floor_applied:
            parts.append(f"[{self.floor_applied} floor: {self.floor_reason}]")
        return " → ".join(parts)


def _beta_from_breakdown(dcf_breakdown: Any) -> Optional[Tuple[float, Optional[float]]]:
    """Extract (beta, beta_raw) from a DCF breakdown carrying a WaccBreakdown."""
    if dcf_breakdown is None:
        return None
    if isinstance(dcf_breakdown, dict):
        wb = dcf_breakdown.get("wacc_breakdown")
    else:
        wb = getattr(dcf_breakdown, "wacc_breakdown", None)
    if wb is None:
        return None
    beta = wb.get("beta") if isinstance(wb, dict) else getattr(wb, "beta", None)
    if beta is None:
        return None
    raw = wb.get("beta_raw") if isinstance(wb, dict) else getattr(wb, "beta_raw", None)
    return float(beta), (float(raw) if raw is not None else None)


def resolve_effective_beta(
    data: FinancialData, dcf_breakdown: Any = None
) -> EffectiveBeta:
    """Return the single β that every report surface must use.

    Priority:
      1. The β actually used by WACC (`WaccBreakdown.beta`) when the DCF ran —
         guarantees the market / risk / WACC sections cannot diverge.
      2. Otherwise winsorize `data.market.beta` with the same band WACC uses.
      3. Otherwise the config fallback unlevered β.
    """
    from_bd = _beta_from_breakdown(dcf_breakdown)
    if from_bd is not None:
        beta, raw = from_bd
        # `clamped` means the *raw regression* β sat outside the CAPM band — not
        # merely "differs from the β used" (M-34 may legitimately select a
        # bottom-up β, which must not be reported as a band clipping).
        clamped = raw is not None and (raw < BETA_WINSOR_LO or raw > BETA_WINSOR_HI)
        floor_applied = None
        floor_reason = ""
        if clamped:
            if raw < BETA_WINSOR_LO:
                floor_applied = "lo"
                floor_reason = (
                    f"原始回归 β={raw:.3f} 低于下限 {BETA_WINSOR_LO:.2f}"
                    f"（统计上不可区分于零或为负），按政策下限取值"
                )
            else:
                floor_applied = "hi"
                floor_reason = (
                    f"原始回归 β={raw:.3f} 高于上限 {BETA_WINSOR_HI:.2f}，按政策上限取值"
                )
        return EffectiveBeta(
            beta=beta, beta_raw=raw, clamped=clamped,
            source="WACC breakdown (CAPM)", origin="wacc_breakdown",
            floor_applied=floor_applied, floor_reason=floor_reason,
        )

    raw = getattr(getattr(data, "market", None), "beta", None)
    if raw is None:
        beta = float(DEFAULT_DCF_CONFIG.default_unlevered_beta)
        return EffectiveBeta(
            beta=beta, beta_raw=None, clamped=False,
            source=f"Fallback unlevered beta ({beta:.2f})", origin="fallback",
        )
    raw_f = float(raw)
    # Phase 2.2 — delegate winsorization to CAPM Engine (single core)
    from valuation.capm_engine import CAPMEngine
    _capm = CAPMEngine()
    _chain = _capm.compute(
        raw_beta=raw_f,
        risk_free_rate=0.0,  # only beta normalization needed here
        equity_risk_premium=0.0,
        winsorize=True,
        winsor_lo=BETA_WINSOR_LO,
        winsor_hi=BETA_WINSOR_HI,
    )
    beta = _chain.valuation_beta
    floor_applied = None
    floor_reason = ""
    if raw_f < BETA_WINSOR_LO:
        floor_applied = "lo"
        floor_reason = (
            f"原始回归 β={raw_f:.3f} 低于下限 {BETA_WINSOR_LO:.2f}"
            f"（统计上不可区分于零或为负），按政策下限取值"
        )
    elif raw_f > BETA_WINSOR_HI:
        floor_applied = "hi"
        floor_reason = f"原始回归 β={raw_f:.3f} 高于上限 {BETA_WINSOR_HI:.2f}，按政策上限取值"
    return EffectiveBeta(
        beta=beta, beta_raw=raw_f, clamped=abs(beta - raw_f) > 1e-6,
        source="Provider regression beta (CAPM Engine winsorized)", origin="provider",
        beta_adjusted=_chain.normalized_beta,
        floor_applied=floor_applied, floor_reason=floor_reason,
    )


class WaccCalculator:
    """Auditable bottom-up WACC calculator with:

    - Cost of Equity (CAPM):  ke = Rf + β×ERP
    - Cost of Debt (Implied): kd = TTM InterestExpense / Avg(TotalDebt[t], TotalDebt[t-1])
      → fallback to synthetic credit rating based on interest coverage
    - Effective Tax Rate (non-overlapping periods): ETR = ΣIncomeTax / Σ(EBIT − InterestExpense)
      over TTM *or* N complete fiscal years (never both) → fallback to DCFConfig default
    - Weights (market-value): E = market cap, D = latest total debt
    - Industry sanity check: the canonical Taxonomy identity key first
      (CANONICAL_KEY_WACC_RANGES), then the legacy keyword table
      (INDUSTRY_WACC_RANGES) on dash-normalized sector/industry
    """

    def __init__(self, config: DCFConfig = DEFAULT_DCF_CONFIG) -> None:
        self.cfg = config

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------
    def calculate(self, data: FinancialData, profile: Any = None) -> WaccBreakdown:
        mkt = data.market
        sources: Dict[str, str] = {}

        # 1. Risk-Free Rate — currency-consistent (Phase 1 — Currency-aware Rf):
        #    The Rf must match the *cash-flow currency*. A USD 10Y yield injected
        #    for an HKD/CNY/MYR cash-flow stream silently violates CAPM's internal
        #    consistency (and the terminal-growth ↔ inflation coupling), so a
        #    non-USD company gets a currency-matched sovereign anchor and the
        #    substitution is recorded — never silent.
        #    Priority: (a) injected value if currency-consistent → (b) live U.S.
        #    Treasury (USD only) → (c) currency anchor → (d) config default.
        cf_ccy = (getattr(mkt, "currency", None) or DEFAULT_MACRO_CURRENCY).upper()
        rf_prov = str(getattr(mkt, "risk_free_source", "") or "")
        rf = getattr(mkt, "risk_free_rate", None)
        rf_valid = bool(rf) and 0.005 < float(rf) < 0.15

        def _rf_is_usd_sourced() -> bool:
            tag = rf_prov.lower()
            return any(k in tag for k in ("usd", "^tnx", "treasury", "u.s.", "us 10y"))

        # A non-USD company may only keep an injected rate when its provenance is
        # *unknown* or explicitly matches (i.e. not a US-sourced rate).
        injected_ok = rf_valid and (
            cf_ccy == DEFAULT_MACRO_CURRENCY or not _rf_is_usd_sourced()
        )
        currency_mismatch: Optional[str] = None
        rf_src_tag = ""
        if injected_ok:
            ccy_tag = "USD-consistent" if cf_ccy == DEFAULT_MACRO_CURRENCY else cf_ccy
            rf_src_tag = f"MarketData injected 10Y ({float(rf):.3%}) [{ccy_tag}]"
            sources["Rf"] = rf_src_tag
        else:
            if rf_valid and cf_ccy != DEFAULT_MACRO_CURRENCY and _rf_is_usd_sourced():
                currency_mismatch = (
                    f"注入 Rf {float(rf):.3%} 为 USD 来源（{rf_prov or 'unspecified'}），"
                    f"而现金流币种为 {cf_ccy} → 已替换为 {cf_ccy} 主权 10Y"
                )
            anchor = CURRENCY_RISK_FREE_RATES.get(cf_ccy)
            if cf_ccy == DEFAULT_MACRO_CURRENCY:
                # USD path keeps the live Treasury lookup (home.treasury.gov CSV).
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
                if rf is None or not (0.005 < float(rf) < 0.15):
                    rf = self.cfg.risk_free_rate
                    rf_src_tag = f"Default constant fallback ({rf:.3%})"
                    sources["Rf"] = rf_src_tag
            elif anchor is not None:
                rf = float(anchor)
                rf_src_tag = (
                    f"{cf_ccy} 10Y sovereign anchor ({rf:.3%}) [currency-matched; "
                    "static fallback — see CURRENCY_RISK_FREE_RATES]"
                )
                sources["Rf"] = rf_src_tag
            else:
                rf = self.cfg.risk_free_rate
                rf_src_tag = (
                    f"Default constant ({rf:.3%}) — 未知币种 {cf_ccy}，"
                    "未能确认与现金流币种一致"
                )
                sources["Rf"] = rf_src_tag
        if currency_mismatch:
            sources["Rf (currency)"] = f"⚠ {currency_mismatch}"
        _, nominal_gdp_ceiling = currency_macro_anchors(cf_ccy)
        rf_currency_note: Optional[str] = None
        if currency_mismatch:
            rf_currency_note = f"Rf 币种调整：{currency_mismatch}"
        elif cf_ccy not in CURRENCY_RISK_FREE_RATES:
            rf_currency_note = (
                f"未知现金流币种 {cf_ccy}，Rf 使用默认值，可能未与现金流币种匹配"
            )

        # 2. Equity Risk Premium — injected via MarketData or DCFConfig default
        erp = getattr(mkt, "equity_risk_premium", None)
        if erp and 0.02 < erp < 0.12:
            sources["ERP"] = f"Injected ({erp:.2%})"
        else:
            erp = self.cfg.equity_risk_premium
            sources["ERP"] = f"Default constant ({erp:.2%})"

        # 3. Beta (M-34): a bottom-up (peer-derived) β — cash-adjusted and
        #    target-relevered — takes precedence when sourced; otherwise the
        #    3Y-monthly regression β. Either path feeds the *same* β to CAPM
        #    and every report surface (`resolve_effective_beta`), so
        #    market/risk/WACC cannot diverge.
        #
        #    Phase 2.2 — WACC no longer performs its own winsorization or
        #    shrinkage. Beta *selection* (which source to use) stays here, but
        #    Beta *normalization* (winsorize, Blume shrinkage) is delegated to
        #    CAPM Engine via its parameters. This ensures there is exactly ONE
        #    place that applies the winsorization band and ONE place that
        #    computes Ke = Rf + β × ERP.
        beta_raw = mkt.beta
        beta_bottom_up = getattr(mkt, "bottom_up_beta", None)
        industry_beta = getattr(mkt, "industry_beta", None)
        bottom_up_chain = getattr(mkt, "bottom_up_beta_chain", None) or {}

        # 3a. Multi-window regression β (P1-6) — computed up-front so the
        #     *stability* of the estimate can feed the β-selection below, rather
        #     than merely being printed as a footnote.
        beta_windows_raw = getattr(mkt, "beta_windows", None) or {}
        beta_windows: Dict[str, float] = {
            str(k): float(v) for k, v in beta_windows_raw.items()
            if v is not None
        }
        beta_dispersion: Optional[float] = None
        if len(beta_windows) >= 2:
            beta_dispersion = max(beta_windows.values()) - min(beta_windows.values())
        beta_uncertainty = _beta_uncertainty_label(beta_dispersion)
        # Phase E: three independent β-reliability indicators. The regression β
        # (winsorized) is compared with the bottom-up β even when that bottom-up
        # β is the one actually selected, so a methodology gap cannot be hidden.
        beta_regression_stability = beta_uncertainty
        beta_regression_w: Optional[float] = (
            max(BETA_WINSOR_LO, min(BETA_WINSOR_HI, float(beta_raw)))
            if beta_raw is not None else None
        )
        beta_bottom_up_reliability = _bottom_up_reliability_label(
            beta_bottom_up, bottom_up_chain, getattr(profile, "business_type", None)
        )
        beta_methodology_divergence = _methodology_divergence_label(
            beta_regression_w, beta_bottom_up
        )

        # 3b. Beta SELECTION — decide which raw beta to feed to CAPM Engine.
        #     Normalization (winsorize, shrinkage) is done by CAPM Engine.
        beta_selected: float
        beta_selection_method: str = "unknown"
        blume_shrinkage: float = 0.0
        if beta_bottom_up is not None and beta_bottom_up > 0:
            # Bottom-up (peer-derived, cash-adjusted, target-relevered) β takes
            # precedence whenever reliable peer data exists. No shrinkage
            # applied — bottom-up β is already a stable peer estimate.
            beta_selected = float(beta_bottom_up)
            beta_selection_method = "bottom_up"
            lvl = bottom_up_chain.get("level")
            lvl_txt = f"L{lvl}" if lvl else "peer-derived"
            sources["β"] = (
                f"bottom-up ({lvl_txt}, cash-adjusted + target-relevered) = {beta_bottom_up:.3f} "
                f"(CAPM Engine winsorizes to [{BETA_WINSOR_LO}, {BETA_WINSOR_HI}])"
            )
        elif beta_raw is None:
            beta_selected = self.cfg.default_unlevered_beta
            beta_selection_method = "fallback"
            sources["β"] = f"Fallback unlevered beta ({beta_selected:.2f})"
        else:
            beta_selected = float(beta_raw)
            beta_selection_method = "regression"
            # Phase 1 — render the *recorded* provenance, never a hard-coded
            # "3Y monthly vs SPY" claim the code cannot prove.
            beta_prov = getattr(mkt, "beta_provenance", None) or {}
            src_txt = (
                f"{_format_beta_source(beta_prov, float(beta_raw))} "
                f"(CAPM Engine winsorizes to [{BETA_WINSOR_LO}, {BETA_WINSOR_HI}])"
            )
            # No bottom-up β ⇒ let multi-window divergence drive a shrinkage
            # toward the market mean (β=1.0, Blume-style). We do NOT average the
            # windows: they differ in sampling frequency and length, so a raw
            # mean is not a valid estimator.
            if beta_dispersion is not None and beta_dispersion > BETA_DISPERSION_SHRINK_THRESHOLD:
                blume_shrinkage = min(
                    BETA_MAX_SHRINK,
                    (beta_dispersion - BETA_DISPERSION_SHRINK_THRESHOLD)
                    / BETA_DISPERSION_SHRINK_THRESHOLD * BETA_MAX_SHRINK,
                )
                src_txt += (
                    f"; 窗口极差 {beta_dispersion:.2f} > {BETA_DISPERSION_SHRINK_THRESHOLD:.2f} → "
                    f"CAPM Engine 向市场均值 1.0 收缩 {blume_shrinkage:.0%}"
                )
            sources["β"] = src_txt
        # Phase 2.2 — beta_selected is the RAW selected beta (pre-winsorize).
        # CAPM Engine will winsorize and apply blume_shrinkage. We set beta =
        # beta_selected here for source-tracking and non-CAPM surfaces, but the
        # actual Ke is computed by CAPM Engine below.
        beta = beta_selected
        if industry_beta is not None:
            sources["β (bottom-up unlevered)"] = f"Peer/industry unlevered beta = {industry_beta:.2f}"
        if len(beta_windows) >= 2:
            sources["β (windows)"] = (
                "多窗口回归 β — "
                + "，".join(f"{k}={v:.2f}" for k, v in beta_windows.items())
                + f"（极差 {beta_dispersion:.2f}；不确定性 {beta_uncertainty}）"
            )
        elif beta_windows:
            sources["β (windows)"] = (
                "仅有 1 个窗口 β 可用（"
                + "，".join(f"{k}={v:.2f}" for k, v in beta_windows.items())
                + "），无法评估窗口稳定性"
            )

        # 4. Cost of Equity (CAPM) — Phase 2.2: Unified via CAPM Engine
        #    WACC no longer performs its own Beta winsorization independently.
        #    The Beta SELECTION logic above decides WHICH raw beta to use
        #    (bottom-up vs regression). The selected raw beta and blume_shrinkage
        #    are passed to CAPM Engine, which performs:
        #      - winsorization (winsor_lo, winsor_hi)
        #      - blume shrinkage (toward 1.0)
        #      - ke = rf + valuation_beta × erp
        #    This ensures there is exactly ONE Beta normalization core.
        from valuation.capm_engine import CAPMEngine, BetaChain

        _capm_engine = CAPMEngine()
        _beta_prov = getattr(mkt, "beta_provenance", None) or {}
        _capm_chain: BetaChain = _capm_engine.compute(
            raw_beta=beta_selected,
            risk_free_rate=float(rf),
            equity_risk_premium=float(erp),
            raw_beta_source=(
                _format_beta_source(_beta_prov, float(beta_raw))
                if beta_raw is not None else "none"
            ),
            is_bank=False,  # WACC is for non-bank DCF; bank ke uses BankRIM path
            winsorize=True,
            winsor_lo=BETA_WINSOR_LO,
            winsor_hi=BETA_WINSOR_HI,
            blume_shrinkage=blume_shrinkage,
            # Do NOT pass valuation_beta_override — let CAPM Engine do the
            # normalization (winsorize + shrinkage) so there is ONE core.
        )

        ke = _capm_chain.adjusted_valuation_ke
        raw_capm_ke = _capm_chain.raw_capm_ke
        # Update beta to the CAPM Engine's valuation_beta (post-normalization)
        beta = _capm_chain.valuation_beta

        sources["ke"] = f"CAPM = {rf:.2%} + {beta:.3f}×{erp:.2%} = {ke:.3%}"
        if raw_capm_ke is not None and abs(raw_capm_ke - ke) > 1e-6:
            sources["ke (raw CAPM)"] = (
                f"Raw CAPM ke = {rf:.2%} + {beta_raw:.3f}×{erp:.2%} = {raw_capm_ke:.3%} "
                f"(unmodified; adjusted valuation ke = {ke:.3%})"
            )
        sources["ke (capm_chain)"] = _capm_chain.as_dict()

        # 5. Implied Cost of Debt — pass the *resolved* Rf so the debt fallback
        #    shares one Rf with CAPM (ke = rf + β·ERP). If this method re-read
        #    MarketData.risk_free_rate on its own, an empty MarketData would make
        #    kd fall back to the config default while ke used the Treasury value.
        kd_raw, src_kd = self._implied_cost_of_debt(data, risk_free_rate=rf)
        kd, kd_src = self._apply_cost_of_debt_clamp(kd_raw, rf, src_kd)
        sources["kd (pre-tax)"] = kd_src
        sources["kd (implied raw)"] = src_kd

        # 6. Effective Tax Rate (P0-2) — non-overlapping periods only; the
        #    returned basis records whether TTM or N fiscal years were used.
        etr, src_etr, etr_basis = self._effective_tax_rate(data)
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
        # Phase 1: keep raw vs clamped separate. The clamp is a guard-rail, not a
        # result — a report must never present the floored/capped value as if the
        # model had produced it, so the raw value + reason travel with the object.
        wacc_clamped = abs(wacc - wacc_raw) > 1e-12
        wacc_clamp_reason: Optional[str] = None
        if wacc_clamped:
            if wacc_raw < self.cfg.min_wacc:
                wacc_clamp_reason = (
                    f"原始 WACC {wacc_raw:.2%} 低于下限 {self.cfg.min_wacc:.2%}"
                    "（β/ke/kd 输入异常偏低）"
                )
            else:
                wacc_clamp_reason = (
                    f"原始 WACC {wacc_raw:.2%} 高于上限 {self.cfg.max_wacc:.2%}"
                    "（β/ke/kd 输入异常偏高）"
                )
        if wacc_clamped:
            sources["WACC (raw)"] = f"model-computed (pre-clamp) = {wacc_raw:.4%}"
            sources["WACC (final)"] = (
                f"{we:.4f}×{ke:.4f} + {wd:.4f}×{kd_after_tax:.4f} = {wacc_raw:.4%}"
                f"  →  clamped to [{self.cfg.min_wacc:.2%}, {self.cfg.max_wacc:.2%}] → {wacc:.4%}"
                f"  [{wacc_clamp_reason}]"
            )
        else:
            sources["WACC (final)"] = f"{we:.4f}×{ke:.4f} + {wd:.4f}×{kd_after_tax:.4f} = {wacc:.4%}"

        # 8b. Propagate β uncertainty into a WACC range (P1-6). Re-price the CAPM
        #     cost of equity at the *dispersion* of the multi-window β set, applied
        #     as an offset around the β that CAPM actually used.
        #
        #     Centering on the selected β matters: the window betas are regression
        #     betas, while the selected β is frequently a bottom-up estimate. Using
        #     the raw window values as the band edges (the previous behaviour)
        #     produced a WACC interval from a *different* β population than the one
        #     being reported — KR showed "WACC 区间 [6.07%, 6.17%]" beside a Final
        #     WACC of 9.33%, i.e. an interval that did not contain its own base.
        wacc_beta_lo: Optional[float] = None
        wacc_beta_hi: Optional[float] = None
        if len(beta_windows) >= 2 and beta_dispersion:
            # Half-width of the observed window spread, in β units.
            half_span = 0.5 * beta_dispersion
            b_lo = max(BETA_WINSOR_LO, min(BETA_WINSOR_HI, beta_selected - half_span))
            b_hi = max(BETA_WINSOR_LO, min(BETA_WINSOR_HI, beta_selected + half_span))
            if abs(b_hi - b_lo) > 1e-6:
                ke_lo = rf + b_lo * erp
                ke_hi = rf + b_hi * erp
                wacc_beta_lo = max(self.cfg.min_wacc, min(self.cfg.max_wacc, we * ke_lo + wd * kd_after_tax))
                wacc_beta_hi = max(self.cfg.min_wacc, min(self.cfg.max_wacc, we * ke_hi + wd * kd_after_tax))
                sources["WACC (β window band)"] = (
                    f"β∈[{b_lo:.2f}, {b_hi:.2f}]（以采用值 {beta_selected:.2f} 为中心，"
                    f"±窗口极差/2 = ±{half_span:.2f}）→ WACC∈[{wacc_beta_lo:.2%}, {wacc_beta_hi:.2%}]"
                )

        # 9. Industry Sanity Check (P0-1) — resolve the band from the canonical
        #    Taxonomy identity key first (via the profile), so a merchant power
        #    producer is not sanity-checked against a regulated-utility band.
        lo, hi, label, range_src = self._match_industry_range(
            mkt.sector, mkt.industry, mkt.company_name,
            taxonomy_key=getattr(profile, "taxonomy_identity_key", None),
        )
        sources["Industry sanity"] = f"[{lo:.2%} ~ {hi:.2%}] {label}  ({range_src})"
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
            raw_capm_ke=raw_capm_ke,
            capm_chain=_capm_chain.as_dict() if _capm_chain else None,
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
            industry_range_source=range_src,
            tax_period_basis=etr_basis,
            sources=sources,
            beta_raw=(float(beta_raw) if beta_raw is not None else None),
            beta_bottom_up=(float(beta_bottom_up) if beta_bottom_up is not None else None),
            beta_bottom_up_note=(
                bottom_up_chain.get("note") if isinstance(bottom_up_chain, dict) else None
            ),
            beta_windows=(beta_windows or None),
            beta_dispersion=beta_dispersion,
            beta_selected=beta_selected,
            beta_adjusted=beta,  # Phase 2.2: valuation beta from CAPM Engine
            beta_shrinkage=blume_shrinkage,
            beta_selection_method=beta_selection_method,
            beta_blume_adjusted=(
                (1 - blume_shrinkage) * max(BETA_WINSOR_LO, min(BETA_WINSOR_HI, beta_selected))
                + blume_shrinkage * 1.0
                if blume_shrinkage > 0
                else None
            ),
            beta_uncertainty=beta_uncertainty,
            beta_regression_stability=beta_regression_stability,
            beta_bottom_up_reliability=beta_bottom_up_reliability,
            beta_methodology_divergence=beta_methodology_divergence,
            wacc_beta_lo=wacc_beta_lo,
            wacc_beta_hi=wacc_beta_hi,
            beta_provenance=getattr(mkt, "beta_provenance", None),
            wacc_raw=wacc_raw,
            wacc_clamped=wacc_clamped,
            wacc_clamp_reason=wacc_clamp_reason,
            risk_free_currency=cf_ccy,
            nominal_gdp_ceiling=nominal_gdp_ceiling,
            risk_free_currency_note=rf_currency_note,
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
    def _implied_cost_of_debt(
        cls, data: FinancialData, risk_free_rate: Optional[float] = None
    ) -> Tuple[float, str]:
        """
        Cost of Debt (pre-tax) estimation:
        Priority 1: TTM Interest_Expense / Avg(Debt[t], Debt[t-1])
        Priority 2: Synthetic credit rating from interest coverage ratio
        Priority 3: Rf + 2.5% spread

        ``risk_free_rate`` MUST be the value already resolved by ``calculate()``
        (MarketData → Treasury → config). Passing it in keeps *every* debt-cost
        fallback on the same Rf as the CAPM cost of equity. Re-reading
        ``data.market.risk_free_rate`` here silently diverges from the reported
        Rf whenever that field is empty/out-of-range — the Treasury value would
        feed ke while kd quietly used the config default.
        """
        mkt = data.market
        if risk_free_rate is not None and 0.0 < float(risk_free_rate) < 0.15:
            rf = float(risk_free_rate)
        else:
            # Standalone callers (e.g. unit tests) keep the same priority chain
            # calculate() uses, so behaviour stays coherent.
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
        if icr >= 20:
            return 0.006  # AAA
        if icr >= 12:
            return 0.009  # AA
        if icr >= 8:
            return 0.013  # A
        if icr >= 5:
            return 0.019  # BBB
        if icr >= 3:
            return 0.032  # BB
        if icr >= 1.8:
            return 0.050  # B
        if icr >= 1.0:
            return 0.080  # CCC
        return 0.120  # distressed

    @classmethod
    def _effective_tax_rate(cls, data: FinancialData) -> Tuple[float, str, str]:
        """Effective tax rate from NON-OVERLAPPING periods (P0-2).

        The previous implementation summed ``data.ttm`` *plus* the latest three
        annual statements. TTM already contains the most recent four quarters, so
        the newest fiscal year was counted **twice** — its tax and EBIT were
        double-weighted, biasing the ETR and, downstream, the after-tax cost of
        debt and the WACC.

        Period policy (never mix overlapping windows):
          1. TTM mode   — when the TTM statement carries both tax and EBIT, use
             ONLY that trailing-twelve-month window;
          2. history mode — otherwise use non-overlapping *complete fiscal years*
             (de-duplicated by ``period_end``, most recent first);
          3. fallback   — the configured statutory default.

        Returns ``(etr, source, tax_period_basis)`` — ``tax_period_basis``
        records which caliber fired (``ttm`` / ``fyN`` / ``default``) so the
        report can state the ETR's period basis rather than implying a generic
        "ΣTax/ΣEBT".
        """
        default_etr = DEFAULT_DCF_CONFIG.tax_rate

        def _period_tax_ebt(s: Any) -> Optional[Tuple[float, float]]:
            tax = getattr(s, "income_tax", None)
            ebit = getattr(s, "ebit", None)
            ie = getattr(s, "interest_expense", None)
            if tax is None or ebit is None:
                return None
            ebt = float(ebit) - (float(ie) if ie is not None else 0.0)
            if ebt <= 0 or not math_isfinite(tax) or not math_isfinite(ebt):
                return None
            return float(tax), ebt

        # 1. TTM-only — the trailing twelve months already cover the latest FY.
        ttm = getattr(data, "ttm", None)
        if ttm is not None:
            pair = _period_tax_ebt(ttm)
            if pair is not None:
                tax, ebt = pair
                etr = tax / ebt
                if 0.0 <= etr <= 0.60:
                    return (
                        etr,
                        f"TTM tax/EBT = {tax:,.0f} / {ebt:,.0f} = {etr:.3%}",
                        "ttm",
                    )

        # 2. History mode — non-overlapping complete fiscal years only.
        seen_periods: set = set()
        sum_tax = 0.0
        sum_ebt = 0.0
        n_used = 0
        for s in (getattr(data, "annual_income", None) or [])[:3]:
            pe = getattr(s, "period_end", None)
            if pe is not None:
                if pe in seen_periods:
                    continue
                seen_periods.add(pe)
            pair = _period_tax_ebt(s)
            if pair is None:
                continue
            sum_tax += pair[0]
            sum_ebt += pair[1]
            n_used += 1
        if n_used >= 1 and sum_ebt > 0:
            etr = sum_tax / sum_ebt
            if 0.0 <= etr <= 0.60:
                return (
                    etr,
                    (f"ΣTax/ΣEBT over {n_used} non-overlapping fiscal year(s) = "
                     f"{sum_tax:,.0f} / {sum_ebt:,.0f} = {etr:.3%}"),
                    f"fy{n_used}",
                )

        return (
            default_etr,
            (f"Insufficient tax/EBT data  →  fallback default US statutory "
             f"{default_etr:.2%}"),
            "default",
        )

    @classmethod
    def _match_industry_range(
        cls,
        sector: Optional[str],
        industry: Optional[str],
        company_name: Optional[str] = None,
        taxonomy_key: Optional[str] = None,
    ) -> Tuple[float, float, str, str]:
        """Resolve the industry WACC sanity band (P0-1).

        Priority:
          1. the canonical Taxonomy identity key carried by the profile — an
             *exact* economic identity, so ``util.ipp`` (merchant generation)
             no longer shares the regulated-utility band;
          2. a canonical key resolved from the Yahoo sector/industry strings;
          3. the legacy substring keyword table (dash-normalized);
          4. the market-average default.

        Returns ``(lo, hi, label, source)`` — ``source`` names which rule fired
        so a default-band fall-through is auditable rather than silent.
        """
        # 1 & 2 — canonical identity key
        key = taxonomy_key
        if not key:
            try:
                from classification.taxonomy import node_from_yahoo
                key = node_from_yahoo(sector, industry)
            except Exception as e:  # pragma: no cover - defensive
                log.debug(f"taxonomy key lookup failed (non-fatal): {e}")
                key = None
        if key and key in CANONICAL_KEY_WACC_RANGES:
            lo, hi, label = CANONICAL_KEY_WACC_RANGES[key]
            return lo, hi, label, f"Taxonomy canonical key '{key}'"

        # 3 — legacy keyword table (dash-normalized so an em-dashed provider
        #     string still matches, e.g. "Utilities—Independent Power Producers")
        haystack_parts = [p for p in (sector, industry, company_name) if p]
        if haystack_parts:
            haystack = _normalize_industry_text(" / ".join(haystack_parts))
            for keyword, rng in INDUSTRY_WACC_RANGES.items():
                if _normalize_industry_text(keyword) in haystack:
                    lo, hi, label = rng
                    return lo, hi, label, f"industry keyword '{keyword}'"

        lo, hi, label = DEFAULT_INDUSTRY_RANGE
        return lo, hi, label, "market-average default"


def math_isfinite(x: float) -> bool:
    try:
        import math
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


__all__ = [
    "WaccCalculator",
    "WaccBreakdown",
    "EffectiveBeta",
    "resolve_effective_beta",
    "INDUSTRY_WACC_RANGES",
    "CANONICAL_KEY_WACC_RANGES",
    "DEFAULT_INDUSTRY_RANGE",
    "BETA_WINSOR_LO",
    "BETA_WINSOR_HI",
    "currency_macro_anchors",
]
