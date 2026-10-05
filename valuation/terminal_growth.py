"""
valuation/terminal_growth.py - Terminal Growth three-band calculator
(Base / Low / High) with explicit clamping rules + auditable source.

Rules (per user requirement):
  base = min(
    normalized_growth (company 3y revenue CAGR halved / 2.5% cap),
    long_term_nominal_gdp,
    wacc - 0.5%
  )
  low  = max(1.5%, base - 0.5%)
  high = min(long_term_nominal_gdp, base + 0.5%)

All rates are clamped globally to [1.5%, min(4.5%, wacc - 0.005)]
to avoid Gordon Growth divergence (g >= WACC).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import DEFAULT_DCF_CONFIG, get_logger
from data.models import FinancialData

log = get_logger("valuation.terminal_growth")


# Long-term US nominal GDP growth assumption (2% real + 2.5% inflation ≈ 4.5%)
LONG_TERM_NOMINAL_GDP_DEFAULT: float = 0.045

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
            f"  Low  = max({self.global_min*100:.1f}%, Base−0.5%) = {self.low*100:.2f}%",
            f"  High = min(LT_GDP/WACC−0.5%, Base+0.5%) = {self.high*100:.2f}%",
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
        global_min: float = 0.015,
        global_max_hard: float = 0.045,
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

        # 4. Global clamp on base (respect global_min / global_max_hard / WACC−0.5%)
        ceil = min(self.global_max_hard, wacc_floor)
        floor = self.global_min
        base = max(floor, min(ceil, base_unclamped))
        if base != base_unclamped:
            notes.append(
                f"Base clamped to [{floor:.2%}, {ceil:.2%}] → Base = {base:.3%}"
            )

        # 5. Low / High bands (±0.5%)
        low = max(floor, base - 0.005)
        high = min(ceil, base + 0.005)
        notes.append(
            f"Low = Base−0.5% = {low:.3%};  High = Base+0.5% = {high:.3%}"
        )

        return TerminalGrowthRange(
            base=base,
            low=low,
            high=high,
            long_term_nominal_gdp=self.lt_nominal_gdp,
            normalized_growth=norm_g,
            wacc_minus_half_pct=wacc_floor,
            global_min=floor,
            global_max_hard=self.global_max_hard,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
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
]
