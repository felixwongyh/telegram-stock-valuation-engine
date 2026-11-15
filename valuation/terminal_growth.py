"""
valuation/terminal_growth.py - Terminal Growth three-band calculator
(Base / Low / High) with explicit clamping rules + auditable source.

Economic meaning of the three bands
-----------------------------------
The long-run nominal GDP ceiling (4.5%) is a constraint on a *sustainable
terminal growth rate*, not on a scenario band. Only Base is a long-run stable
terminal growth rate, so only Base must respect it:

  Base  = the long-run stable terminal growth rate fed into the base-case DCF.
          It is capped by BOTH the long-run nominal GDP ceiling (4.5%) and the
          Gordon stability bound (WACC − 0.5%) — a perpetuity cannot grow faster
          than nominal GDP forever.
  Low   = conservative *scenario* band (Base − step), floored so it stays < Base.
  High  = optimistic *scenario* band (Base + step). It MAY exceed the long-run
          nominal GDP ceiling — it is an upside scenario, explicitly NOT a
          long-run stable terminal growth rate. It is bounded only by the Gordon
          stability cap (WACC − 0.5%), beyond which the perpetuity diverges.
          Whenever High > nominal GDP it is flagged (``high_exceeds_gdp``) so
          the report labels it as a scenario, never as a long-run rate.

Derivation
----------
  base = min(
    normalized_growth (company 3y revenue CAGR halved / 5% cap),
    long_term_nominal_gdp,
    wacc - 0.5%
  )
  If unclamped base >= 1.5%: clamp Base to [1.5%, min(4.5%, WACC−0.5%)]
  If unclamped base is negative: fade Base to 0.5% (do NOT lift a declining firm to 1.5%)
  If 0 <= unclamped < 1.5%: lift Base to the 1.5% mature floor (flat ≠ declining)
  low  = Base − 0.5% (may be 0% for declining names)
  high = Base + 0.5%

Invariant (always): Low < Base < High.
Low may dip to 1.0% when Base sits on the 1.5% floor, so Low stays strictly below Base.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import (
    CURRENCY_NOMINAL_GDP,
    DEFAULT_MACRO_CURRENCY,
    get_logger,
)
from data.models import FinancialData

log = get_logger("valuation.terminal_growth")


# Long-term US nominal GDP growth assumption (2% real + 2.5% inflation ≈ 4.5%).
# This is the ceiling for a *sustainable long-run* terminal growth rate, so it
# binds on Base only — the optimistic High *scenario* band is allowed above it.
LONG_TERM_NOMINAL_GDP_DEFAULT: float = 0.045
# Symmetric Low/High offset around Base (50 bps).
BAND_STEP: float = 0.005
# Base floor for healthy/mature firms. Declining firms fade to DECLINING_BASE instead.
BASE_FLOOR: float = 0.015
LOW_HARD_FLOOR: float = 0.010
DECLINING_BASE: float = 0.005
DECLINING_LOW_FLOOR: float = 0.0
# Base ceiling = long-run nominal GDP consensus (4.5%). Base is where the
# sustainable-terminal-growth constraint applies; the optimistic High scenario
# may sit BAND_STEP above it (bounded only by the Gordon cap WACC−0.5%).
BASE_HARD_CEILING: float = 0.045

TVG_SOURCE_MODEL_ASSUMPTION = "Model assumption (clamped normalized growth, LT nominal GDP, WACC-0.5%)"

# Engine-level band semantics (contract). The render layer must map these keys
# to localized copy instead of hardcoding its own wording — see dashboard.py.
BAND_LABELS: Dict[str, str] = {
    "low": "Conservative scenario: long-run terminal growth − 0.5%",
    "base": "Long-run stable terminal growth rate (long-run GDP-capped; used in the base-case DCF)",
    "high": "Optimistic scenario: may exceed long-run GDP; only Gordon-capped at WACC−0.5%, NOT a long-run stable terminal growth rate",
}


@dataclass
class TerminalGrowthRange:
    """Three-band terminal growth with auditable derivation."""
    base: float
    low: float
    high: float
    long_term_nominal_gdp: float
    normalized_growth: float
    wacc_minus_half_pct: float
    global_min: float = 0.015
    global_max_hard: float = 0.045
    source: str = TVG_SOURCE_MODEL_ASSUMPTION
    notes: List[str] = field(default_factory=list)
    # True when the optimistic High band sits above the long-run nominal GDP
    # ceiling → the render layer must label High as a scenario, not a long-run
    # stable terminal growth rate.
    high_exceeds_gdp: bool = False
    gdp_ceiling: float = LONG_TERM_NOMINAL_GDP_DEFAULT
    band_labels: Dict[str, str] = field(default_factory=lambda: dict(BAND_LABELS))

    def as_assumptions_table(self) -> List[Dict[str, Any]]:
        return [
            {"band": "Low",  "value": self.low,  "vs_base": self.low - self.base},
            {"band": "Base", "value": self.base, "vs_base": 0.0},
            {"band": "High", "value": self.high, "vs_base": self.high - self.base},
        ]

    def summary_line(self) -> str:
        return (
            f"Terminal Growth  —  Low {self.low:.2%}  |  "
            f"Base {self.base:.2%}  |  High {self.high:.2%}  "
            f"(Source: {self.source})"
        )

    def formatted_output(self) -> str:
        """严格按照用户要求的 Terminal Growth 输出格式：
        Terminal Growth
        Base:       XX.XX%
        Low:        YY.YY%
        High:       ZZ.ZZ%
        Source:     Model assumption
        """
        lines = [
            "Terminal Growth",
            f"Base:       {self.base * 100:.2f}%",
            f"Low:        {self.low * 100:.2f}%",
            f"High:       {self.high * 100:.2f}%",
            f"Source:     {self.source}",
        ]
        return "\n".join(lines)

    def derivation_trace(self) -> str:
        """详细推导过程追踪（全审计）"""
        lines = [
            "── Terminal Growth Derivation ──",
            f"  normalized_growth (company) : {self.normalized_growth*100:.2f}%  (3y CAGR × 50% mean-reversion, capped ±5%)",
            f"  long_term_nominal_gdp       : {self.long_term_nominal_gdp*100:.2f}%  (2% real + 2.5% inflation consensus)",
            f"  wacc - 0.5% (Gordon bound)  : {self.wacc_minus_half_pct*100:.2f}%  (g must be << WACC to avoid divergence)",
            f"  base = min(above three)     : {self.base*100:.2f}%  (long-run stable rate; GDP-capped)",
            f"  Low  = Base−0.5% (floor {self.global_min*100:.1f}%) = {self.low*100:.2f}%  [conservative scenario]",
            f"  High = Base+0.5% = {self.high*100:.2f}%  "
            f"[optimistic scenario; {'ABOVE' if self.high_exceeds_gdp else 'within'} long-run GDP "
            f"{self.long_term_nominal_gdp*100:.2f}%; Gordon cap WACC−0.5%]",
            f"  invariant Low < Base < High : {self.low < self.base < self.high}",
        ]
        if self.notes:
            lines.append("  Notes:")
            for n in self.notes[:4]:
                lines.append(f"    • {n}")
        return "\n".join(lines)


class TerminalGrowthCalculator:

    def __init__(
        self,
        long_term_nominal_gdp: float = LONG_TERM_NOMINAL_GDP_DEFAULT,
        global_min: float = BASE_FLOOR,
        global_max_hard: float = BASE_HARD_CEILING,
    ) -> None:
        self.lt_nominal_gdp = long_term_nominal_gdp
        self.global_min = global_min
        self.global_max_hard = global_max_hard

    # ------------------------------------------------------------------
    # Public entrypoints
    # ------------------------------------------------------------------
    def calculate(self, data: FinancialData, wacc: float,
                  normalized_growth_hint: Optional[float] = None,
                  nominal_gdp_ceiling: Optional[float] = None) -> TerminalGrowthRange:
        notes: List[str] = []

        # 0. Currency-aware long-run nominal GDP ceiling. The terminal growth of a
        # perpetuity is a *cash-flow-currency* quantity: discounting CNY cash flows
        # at a CNY rate while assuming a US 4.5% terminal growth (or vice versa)
        # mixes an interest-rate/inflation regime with the wrong economy. When a
        # ceiling is not supplied explicitly it is derived from the company's
        # cash-flow currency, so every DCF / scenario / MC caller stays consistent.
        ccy = DEFAULT_MACRO_CURRENCY
        if data is not None and getattr(data, "market", None) is not None:
            ccy = (getattr(data.market, "currency", None) or DEFAULT_MACRO_CURRENCY).upper()
        gdp_ceiling = float(self.lt_nominal_gdp)
        if nominal_gdp_ceiling is None:
            nominal_gdp_ceiling = CURRENCY_NOMINAL_GDP.get(ccy)
        if nominal_gdp_ceiling is not None and _isf(nominal_gdp_ceiling):
            gdp_ceiling = float(nominal_gdp_ceiling)
            if abs(gdp_ceiling - self.lt_nominal_gdp) > 1e-9:
                notes.append(
                    f"长期名义 GDP 上限按现金流币种调整（{ccy}）: "
                    f"{self.lt_nominal_gdp:.2%} → {gdp_ceiling:.2%}"
                )

        # 1. Normalized company growth (3y revenue CAGR, halved & capped 5%)
        if normalized_growth_hint is not None and _isf(normalized_growth_hint):
            norm_g = float(normalized_growth_hint)
            src_norm = "Hint passed by caller"
        else:
            cagr = self._historical_revenue_cagr_3y(data)
            # Normalize: halve the historical CAGR to reflect reversion-to-mean,
            # then clamp internally to [-5%, 5%] before any other rule is applied.
            reversion = (cagr or 0.025) * 0.5
            norm_g = max(-0.05, min(0.05, reversion))
            if cagr is None:
                src_norm = (f"No 3y revenue CAGR  →  default 2.5% × 50% mean-reversion "
                           f"= {norm_g:.3%}")
            else:
                src_norm = (f"3y revenue CAGR = {cagr:.3%} × 50% mean-reversion "
                           f"→ normalized growth = {norm_g:.3%}")
        notes.append(src_norm)

        # 2. WACC - 0.5% upper bound (Gordon stability: g << WACC)
        wacc_floor = max(0.005, wacc - 0.005)
        notes.append(
            f"Gordon stability bound (WACC−0.5%) = {wacc:.3%} − 0.5% = {wacc_floor:.3%}"
        )

        # 3. Base = min(norm_g, LT_nominal_GDP, WACC−0.5%)
        base_unclamped = min(norm_g, gdp_ceiling, wacc_floor)
        notes.append(
            f"min(normalized={norm_g:.3%}, LT_GDP={gdp_ceiling:.3%}, "
            f"WACC−0.5%={wacc_floor:.3%}) = {base_unclamped:.3%}"
        )

        # 4. Clamp Base: do not lift declining companies to the 1.5% mature floor.
        # The hard Base ceiling tracks the cash-flow-currency nominal GDP when it
        # differs from the USD anchor; otherwise it stays at the configured cap.
        hard_cap = self.global_max_hard
        if abs(gdp_ceiling - self.lt_nominal_gdp) > 1e-9:
            hard_cap = gdp_ceiling
        ceil_base = min(hard_cap, wacc_floor)
        low_floor = LOW_HARD_FLOOR
        if base_unclamped < 0:
            base = DECLINING_BASE
            low_floor = DECLINING_LOW_FLOOR
            notes.append(
                f"Negative normalized growth ({norm_g:.3%}): fade Base to "
                f"{DECLINING_BASE:.2%} instead of mature floor {BASE_FLOOR:.2%}"
            )
        elif base_unclamped < BASE_FLOOR:
            # Modest positive growth below the mature floor → lift to the mature
            # floor. Only genuinely declining firms (negative growth, handled
            # above) fade to DECLINING_BASE; a flat/healthy firm's terminal
            # growth should not collapse to ~0%.
            base = max(self.global_min, min(ceil_base, BASE_FLOOR))
            low_floor = LOW_HARD_FLOOR
            notes.append(
                f"Normalized growth below mature floor → Base lifted to "
                f"{BASE_FLOOR:.2%} (mature floor); Low floor = {LOW_HARD_FLOOR:.2%}"
            )
        else:
            floor_base = self.global_min
            base = max(floor_base, min(ceil_base, base_unclamped))
            if base != base_unclamped:
                notes.append(
                    f"Base clamped to [{floor_base:.2%}, {ceil_base:.2%}] → Base = {base:.3%}"
                )

        # 5. Low / High bands (±0.5%) with Low < Base < High always.
        # Base is the long-run stable rate and keeps the GDP cap. Low / High are
        # *scenario* bands: the optimistic High may exceed long-run GDP and is
        # then flagged (high_exceeds_gdp) so it is never mistaken for a long-run
        # stable terminal growth rate. Only the Gordon bound (WACC−0.5%) caps High.
        base_before_bands = base
        low, base, high = self._enforce_strict_bands(
            base=base,
            step=BAND_STEP,
            low_floor=low_floor,
            high_cap=wacc_floor,
        )
        if abs(base - base_before_bands) > 1e-9:
            notes.append(
                f"Base slid {base_before_bands:.3%} → {base:.3%} so High stays < WACC−0.5% "
                f"while preserving Low < Base < High"
            )
        high_exceeds_gdp = high > gdp_ceiling + 1e-9
        if high_exceeds_gdp:
            notes.append(
                f"Optimistic High {high:.3%} > long-run nominal GDP {gdp_ceiling:.3%}: "
                f"High is a scenario band (only Gordon-capped at WACC−0.5%), "
                f"NOT a long-run stable terminal growth rate"
            )
        notes.append(
            f"Low = {low:.3%};  Base = {base:.3%};  High = {high:.3%}  "
            f"(Low < Base < High, step={BAND_STEP:.1%}; Base is GDP-capped, "
            f"High only Gordon-capped at WACC−0.5%)"
        )
        if not (low < base < high):
            notes.append("ERROR: TVG bands failed Low < Base < High invariant")

        return TerminalGrowthRange(
            base=base,
            low=low,
            high=high,
            long_term_nominal_gdp=gdp_ceiling,
            normalized_growth=norm_g,
            wacc_minus_half_pct=wacc_floor,
            global_min=LOW_HARD_FLOOR,
            global_max_hard=self.global_max_hard,
            notes=notes,
            high_exceeds_gdp=high_exceeds_gdp,
            gdp_ceiling=gdp_ceiling,
            band_labels=dict(BAND_LABELS),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _enforce_strict_bands(
        base: float,
        step: float,
        low_floor: float,
        high_cap: float,
    ) -> tuple:
        """Place Low / Base / High so Low < Base < High.

        Prefer Base ± step. If High would hit the Gordon cap (the hard stability
        bound), slide the whole window down. If Low would hit the floor, slide
        the window up. High is deliberately NOT clamped to the GDP/4.5% Base
        ceiling — it is a scenario band (see ``high_exceeds_gdp``).
        """
        eps = 1e-9
        span = high_cap - low_floor
        if span <= 2 * eps:
            high = high_cap
            base_adj = high - eps
            low = base_adj - eps
            return low, base_adj, high

        step = min(abs(step), span / 2.0)
        low = base - step
        high = base + step

        if high > high_cap + eps:
            overflow = high - high_cap
            high = high_cap
            base -= overflow
            low -= overflow

        if low < low_floor - eps:
            underflow = low_floor - low
            low = low_floor
            base += underflow
            high += underflow
            if high > high_cap + eps:
                high = high_cap
                base = (low + high) / 2.0

        high = min(high, high_cap)
        low = max(low, low_floor)
        if not (low < base < high):
            base = (low + high) / 2.0
        return low, base, high

    @staticmethod
    def _historical_revenue_cagr_3y(data: FinancialData) -> Optional[float]:
        revs = [
            s.revenue for s in data.annual_income
            if s.revenue is not None and s.revenue != 0
        ]
        if len(revs) < 4:
            return None
        # annual_income is newest-first: [yr0, yr1, yr2, yr3, ...]
        newest = float(revs[0])
        oldest = float(revs[min(3, len(revs) - 1)])
        if newest <= 0 or oldest <= 0:
            return None
        n_years = min(3, len(revs) - 1)
        cagr = (newest / oldest) ** (1.0 / n_years) - 1.0
        return cagr


def _isf(x: float) -> bool:
    try:
        import math
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


__all__ = [
    "TerminalGrowthCalculator",
    "TerminalGrowthRange",
    "BAND_LABELS",
    "LONG_TERM_NOMINAL_GDP_DEFAULT",
    "BAND_STEP",
    "BASE_FLOOR",
    "LOW_HARD_FLOOR",
    "DECLINING_BASE",
    "DECLINING_LOW_FLOOR",
    "BASE_HARD_CEILING",
]
