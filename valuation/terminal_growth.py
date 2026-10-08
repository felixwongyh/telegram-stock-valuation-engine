"""
valuation/terminal_growth.py - Terminal Growth three-band calculator
(Base / Low / High) with explicit clamping rules + auditable source.

Rules:
  base = min(
    normalized_growth (company 3y revenue CAGR halved / 5% cap),
    long_term_nominal_gdp,
    wacc - 0.5%
  )
  If unclamped base >= 1.5%: clamp Base to [1.5%, min(4.5%, WACC−0.5%)]
  If unclamped base is negative: fade Base to 0.5% (do NOT lift a declining firm to 1.5%)
  If 0 <= unclamped < 1.5%: keep unclamped (modest positive g)
  low  = Base − 0.5% (may be 0% for declining names)
  high = Base + 0.5%

Invariant (always): Low < Base < High.

High is NOT capped by long-term GDP / 4.5%. That cap applies to Base only.
Otherwise a 4.5% Base would collapse High == Base (e.g. AVGO).
High is capped only by the Gordon bound (WACC−0.5%). If that bound would
collapse the spread, the whole ±0.5% window slides down so the invariant holds.
Low may dip to 1.0% when Base sits on the 1.5% floor, so Low stays strictly below Base.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import DEFAULT_DCF_CONFIG, get_logger
from data.models import FinancialData

log = get_logger("valuation.terminal_growth")


# Long-term US nominal GDP growth assumption (2% real + 2.5% inflation ≈ 4.5%)
LONG_TERM_NOMINAL_GDP_DEFAULT: float = 0.045
# Symmetric Low/High offset around Base (50 bps).
BAND_STEP: float = 0.005
# Base floor for healthy/mature firms. Declining firms fade to DECLINING_BASE instead.
BASE_FLOOR: float = 0.015
LOW_HARD_FLOOR: float = 0.010
DECLINING_BASE: float = 0.005
DECLINING_LOW_FLOOR: float = 0.0
# Base ceiling (GDP consensus). High may exceed this by BAND_STEP.
# Base ceiling (GDP consensus). High may exceed this by BAND_STEP.
BASE_HARD_CEILING: float = 0.045

TVG_SOURCE_MODEL_ASSUMPTION = "Model assumption (clamped normalized growth, LT nominal GDP, WACC-0.5%)"


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
            f"  base = min(above three)     : {self.base*100:.2f}%",
            f"  Low  = Base−0.5% (floor {self.global_min*100:.1f}%) = {self.low*100:.2f}%",
            f"  High = Base+0.5% (Gordon cap WACC−0.5%, not GDP) = {self.high*100:.2f}%",
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
                  normalized_growth_hint: Optional[float] = None) -> TerminalGrowthRange:
        notes: List[str] = []

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
        base_unclamped = min(norm_g, self.lt_nominal_gdp, wacc_floor)
        notes.append(
            f"min(normalized={norm_g:.3%}, LT_GDP={self.lt_nominal_gdp:.3%}, "
            f"WACC−0.5%={wacc_floor:.3%}) = {base_unclamped:.3%}"
        )

        # 4. Clamp Base: do not lift declining companies to the 1.5% mature floor.
        ceil_base = min(self.global_max_hard, wacc_floor)
        low_floor = LOW_HARD_FLOOR
        if base_unclamped < 0:
            base = DECLINING_BASE
            low_floor = DECLINING_LOW_FLOOR
            notes.append(
                f"Negative normalized growth ({norm_g:.3%}): fade Base to "
                f"{DECLINING_BASE:.2%} instead of mature floor {BASE_FLOOR:.2%}"
            )
        elif base_unclamped < BASE_FLOOR:
            base = max(DECLINING_LOW_FLOOR + BAND_STEP, min(ceil_base, base_unclamped))
            low_floor = DECLINING_LOW_FLOOR
            notes.append(
                f"Normalized growth below mature floor; keeping Base={base:.3%} "
                f"(not lifted to {BASE_FLOOR:.2%})"
            )
        else:
            floor_base = self.global_min
            base = max(floor_base, min(ceil_base, base_unclamped))
            if base != base_unclamped:
                notes.append(
                    f"Base clamped to [{floor_base:.2%}, {ceil_base:.2%}] → Base = {base:.3%}"
                )

        # 5. Low / High bands (±0.5%) with Low < Base < High always.
        # High may exceed LT GDP / 4.5%; only Gordon bound (WACC−0.5%) is a hard cap.
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
        notes.append(
            f"Low = {low:.3%};  Base = {base:.3%};  High = {high:.3%}  "
            f"(Low < Base < High, step={BAND_STEP:.1%}; High cap = WACC−0.5% not GDP)"
        )
        if not (low < base < high):
            notes.append("ERROR: TVG bands failed Low < Base < High invariant")

        return TerminalGrowthRange(
            base=base,
            low=low,
            high=high,
            long_term_nominal_gdp=self.lt_nominal_gdp,
            normalized_growth=norm_g,
            wacc_minus_half_pct=wacc_floor,
            global_min=LOW_HARD_FLOOR,
            global_max_hard=self.global_max_hard,
            notes=notes,
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

        Prefer Base ± step. If High would hit the Gordon cap, slide the whole
        window down. If Low would hit the floor, slide the window up. Never
        clamp High to the GDP/4.5% Base ceiling.
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
        revs = [s.revenue for s in data.annual_income if getattr(s, "revenue", None) not in (None, 0)]
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
    "LONG_TERM_NOMINAL_GDP_DEFAULT",
    "BAND_STEP",
    "BASE_FLOOR",
    "LOW_HARD_FLOOR",
    "DECLINING_BASE",
    "DECLINING_LOW_FLOOR",
    "BASE_HARD_CEILING",
]
