"""analysis/threshold_calibration.py - Cross-industry diagnostic threshold calibration (M-67).

Why
---
Phase A and Phase E shipped with *global* thresholds: the FCF-margin bands
(3pp / 5pp / 2×) and the bottom-up β minimum-peer floor (4). A 5pp FCF-margin
swing does not mean the same thing for a regulated utility as for a high-capex
semiconductor, and a 4-name peer median is thin in an archetype with a deep
public peer pool but *broad* in a niche one. This module replaces the single
global constant with a per-archetype calibration table.

Two-source calibration (auditable, reproducible)
------------------------------------------------
1. **Internal sample** — ``_calibrate_thresholds.py`` measures, for every
   ticker in the offline regression basket, the population σ of the 3–5y
   annual **operating-margin** history. FCF margin = margin·(1−t) + D&A/Rev −
   CapEx/Rev − ΔNWC/Rev, so margin volatility dominates; the proxy is stated
   rather than implied. The observed σ/n per archetype is frozen in
   :data:`CALIBRATION_EVIDENCE` so a reviewer can re-derive it.
2. **Domain prior** — archetypes the 19-name basket cannot cover fall back to a
   documented prior (utilities/telecom/insurance = contracted cash flows).

Tier cut points are a documented, monotone rule::

    median σ < TIER_STABLE_MAX_DISPERSION (0.03)              → stable
    TIER_STABLE_MAX_DISPERSION ≤ σ < TIER_VOLATILE_MIN (0.06) → moderate
    σ ≥ TIER_VOLATILE_MIN_DISPERSION (0.06)                   → volatile

Bands **widen** with volatility (a stable business tolerates a tight band; a
volatile one needs a wider band before a gap is a diagnostic signal). The
bottom-up β peer floor instead tracks **peer-pool breadth**: a deep pool must
supply more names before its median is called reliable, while a niche archetype
with few listed comparables is judged on a smaller floor.

Honesty rules
-------------
* This table is the single *runtime* source, so the report is deterministic;
  the harness is a reproducibility tool and is never a report-time dependency.
* Sample size is disclosed: the basket is small, so ``n`` is recorded next to
  every observed σ and the sample is treated as *corroborating* evidence, never
  as a precision claim.
* An unknown / unmapped archetype falls back to :data:`DEFAULT_CALIBRATION`
  (the pre-M-67 global bands), so nothing is silently re-graded.
* Every profile carries its rationale so the report can print *why* a band was
  widened/tightened instead of asserting a bare number.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

# Volatility tiers (see the module docstring for the cut-point rule).
TIER_STABLE = "stable"
TIER_MODERATE = "moderate"
TIER_VOLATILE = "volatile"

TIER_STABLE_MAX_DISPERSION: float = 0.03
TIER_VOLATILE_MIN_DISPERSION: float = 0.06

# FCF-margin diagnostic bands per volatility tier.
#   aligned_pp : |Δ| below this is "aligned"
#   flag_pp    : |Δ| at/above this is a flag (between = moderate)
#   high_ratio : forecast margin above this multiple of TTM is a material change
_TIER_BANDS: Dict[str, Dict[str, float]] = {
    TIER_STABLE: {"fcf_aligned_pp": 0.02, "fcf_flag_pp": 0.04, "fcf_high_ratio": 1.75},
    TIER_MODERATE: {"fcf_aligned_pp": 0.03, "fcf_flag_pp": 0.05, "fcf_high_ratio": 2.00},
    TIER_VOLATILE: {"fcf_aligned_pp": 0.04, "fcf_flag_pp": 0.07, "fcf_high_ratio": 2.50},
}

# Bottom-up β peer floor, by *peer-pool breadth* (not by volatility): a deep
# public pool must supply a broader sample before its median is called reliable.
BETA_MIN_PEERS_BROAD: int = 5
BETA_MIN_PEERS_NARROW: int = 3
BETA_MIN_PEERS_UNKNOWN: int = 4          # neutral: no pool-breadth evidence

# Archetypes whose listed pure-play comparables are genuinely thin (each
# conglomerate is unique; pure-play neobanks/fintechs number in the low single
# digits), so a smaller peer floor is honest rather than a fallback.
_NARROW_PEER_POOLS: frozenset = frozenset({"NEOBANK", "FINTECH", "CONGLOMERATE"})

# Archetype → volatility tier, calibrated from the observed operating-margin
# dispersion over the offline basket (see CALIBRATION_EVIDENCE). Archetypes the
# basket cannot cover use the documented domain prior.
_ARCHETYPE_TIER: Dict[str, str] = {
    # --- evidence-driven (σ observed in the offline basket) ---
    "CONSUMERSTAPLES": TIER_STABLE,      # σ=0.0014
    "REIT": TIER_STABLE,                 # σ=0.0112
    "CONSUMERCYCLICAL": TIER_STABLE,     # σ=0.0140
    "INDUSTRIAL": TIER_STABLE,           # σ=0.0175
    "BANK": TIER_STABLE,                 # σ=0.0247
    "MATURETECH": TIER_MODERATE,         # σ=0.0310
    "SAAS": TIER_VOLATILE,               # σ=0.0747
    "ENERGY": TIER_VOLATILE,             # σ=0.1096
    "SEMICONDUCTOR": TIER_VOLATILE,      # σ=0.1118
    "FINTECH": TIER_VOLATILE,            # σ=0.1895
    # --- domain prior (not covered by the 19-name basket) ---
    "UTILITIES": TIER_STABLE,            # regulated / contracted cash flows
    "TELECOM": TIER_STABLE,              # subscription revenue
    "INSURANCE": TIER_STABLE,            # underwriting float, stable margins
    "HEALTHCARE": TIER_MODERATE,         # pharma stable, biotech lumpy → mid
    "MEDIA": TIER_MODERATE,              # content cyclicality
    "CONGLOMERATE": TIER_MODERATE,       # mixed-segment averaging
    "COMMODITY": TIER_VOLATILE,          # price-taker on commodity cycles
    "NEOBANK": TIER_VOLATILE,            # early-stage, scaling FCF
}

# Frozen snapshot of the calibration harness output: archetype → (median σ, n).
# Produced by ``python _calibrate_thresholds.py`` over ``tests.golden_report.BASKET``.
# A small n means the observation *corroborates* the tier; it is not a precision
# claim (disclosed in the report audit note).
CALIBRATION_EVIDENCE: Dict[str, Tuple[float, int]] = {
    "ConsumerStaples": (0.0014, 1),
    "REIT": (0.0112, 2),
    "ConsumerCyclical": (0.0140, 1),
    "Industrial": (0.0175, 1),
    "Bank": (0.0247, 2),
    "MatureTech": (0.0310, 6),
    "SaaS": (0.0747, 1),
    "Energy": (0.1096, 1),
    "Semiconductor": (0.1118, 2),
    "FinTech": (0.1895, 1),
}

_TIER_RATIONALE: Dict[str, str] = {
    TIER_STABLE: (
        "低 FCF-margin 波动：带收窄至 2pp/4pp/1.75×，"
        "使稳定业务的相对小幅偏离也能被识别"
    ),
    TIER_MODERATE: "中等 FCF-margin 波动：沿用全局基准带 3pp/5pp/2×",
    TIER_VOLATILE: (
        "高 FCF-margin 波动（强周期/重资本开支/早期 FCF）：带放宽至 "
        "4pp/7pp/2.5×，避免把正常周期波动误报为脱节"
    ),
}


@dataclass(frozen=True)
class ThresholdCalibration:
    """One archetype's calibrated diagnostic thresholds + audit rationale."""

    archetype: str
    tier: str
    fcf_aligned_pp: float
    fcf_flag_pp: float
    fcf_high_ratio: float
    beta_min_peers: int
    rationale: str
    # Observed volatility proxy that drove the tier (None when the archetype is
    # prior-governed rather than evidence-governed).
    judged_dispersion: Optional[float] = None
    evidence_n: int = 0

    def note(self) -> str:
        """Compact audit line for the report."""
        ev = ""
        if self.judged_dispersion is not None:
            ev = f"（观测 σ={self.judged_dispersion:.3f}, n={self.evidence_n}）"
        return (
            f"行业校准[{self.tier}]{ev}：FCF margin 带 "
            f"{self.fcf_aligned_pp*100:.0f}pp/{self.fcf_flag_pp*100:.0f}pp/"
            f"{self.fcf_high_ratio:.2f}×，β 最小同业 {self.beta_min_peers} 家；"
            f"{self.rationale}"
        )


def _norm(business_type: Any) -> str:
    if business_type is None:
        return ""
    if not isinstance(business_type, str):
        business_type = getattr(business_type, "value", str(business_type))
    return business_type.replace(" ", "").replace("_", "").upper()


def tier_for_dispersion(dispersion: Optional[float]) -> str:
    """Map an observed margin dispersion onto a volatility tier (monotone)."""
    if dispersion is None:
        return TIER_MODERATE
    if dispersion < TIER_STABLE_MAX_DISPERSION:
        return TIER_STABLE
    if dispersion >= TIER_VOLATILE_MIN_DISPERSION:
        return TIER_VOLATILE
    return TIER_MODERATE


def thresholds_for_tier(
    tier: str, *, judged_dispersion: Optional[float] = None
) -> ThresholdCalibration:
    """Build a calibration for an explicit tier (used by the harness)."""
    tier = tier if tier in _TIER_BANDS else TIER_MODERATE
    bands = _TIER_BANDS[tier]
    return ThresholdCalibration(
        archetype="",
        tier=tier,
        fcf_aligned_pp=bands["fcf_aligned_pp"],
        fcf_flag_pp=bands["fcf_flag_pp"],
        fcf_high_ratio=bands["fcf_high_ratio"],
        beta_min_peers=BETA_MIN_PEERS_BROAD,
        rationale=_TIER_RATIONALE[tier],
        judged_dispersion=judged_dispersion,
    )


def beta_min_peers_for(business_type: Any) -> int:
    """Peer floor by *pool breadth* of the archetype (not by volatility)."""
    key = _norm(business_type)
    if not key:
        return BETA_MIN_PEERS_UNKNOWN
    if key in _NARROW_PEER_POOLS:
        return BETA_MIN_PEERS_NARROW
    if key in _ARCHETYPE_TIER:
        return BETA_MIN_PEERS_BROAD
    return BETA_MIN_PEERS_UNKNOWN


def calibration_for(business_type: Any) -> ThresholdCalibration:
    """Resolve the calibrated thresholds for a business archetype."""
    key = _norm(business_type)
    tier = _ARCHETYPE_TIER.get(key, TIER_MODERATE)
    cal = thresholds_for_tier(tier)
    # The frozen evidence snapshot is keyed on the canonical (CamelCase) label.
    sigma, n = None, 0
    for label, (s, cnt) in CALIBRATION_EVIDENCE.items():
        if _norm(label) == key:
            sigma, n = s, cnt
            break
    return ThresholdCalibration(
        archetype=key or "UNKNOWN",
        tier=cal.tier,
        fcf_aligned_pp=cal.fcf_aligned_pp,
        fcf_flag_pp=cal.fcf_flag_pp,
        fcf_high_ratio=cal.fcf_high_ratio,
        beta_min_peers=beta_min_peers_for(key),
        rationale=cal.rationale,
        judged_dispersion=sigma,
        evidence_n=n,
    )


# Backwards-compatible default: the pre-M-67 global bands (moderate tier).
DEFAULT_CALIBRATION: ThresholdCalibration = thresholds_for_tier(TIER_MODERATE)


def calibration_evidence_note() -> str:
    """Frozen snapshot of the internal calibration sample (audit trail)."""
    rows = [
        f"{bt}: σ={sigma:.4f}(n={n})"
        for bt, (sigma, n) in sorted(CALIBRATION_EVIDENCE.items())
    ]
    return "行业校准样本（3–5 年营业利润率 σ 代理，离线回归篮子）：" + "；".join(rows)


def calibration_table_note() -> str:
    """Audit summary of the whole calibration table (report / docs)."""
    rows = []
    for tier in (TIER_STABLE, TIER_MODERATE, TIER_VOLATILE):
        b = _TIER_BANDS[tier]
        rows.append(
            f"{tier}: {b['fcf_aligned_pp']*100:.0f}pp/"
            f"{b['fcf_flag_pp']*100:.0f}pp/{b['fcf_high_ratio']:.2f}×"
        )
    return (
        "跨行业阈值校准（按业务原型波动分档）："
        + "；".join(rows)
        + f"；β 最小同业：宽池 {BETA_MIN_PEERS_BROAD} 家 / 窄池 {BETA_MIN_PEERS_NARROW} 家"
        f"（窄池={sorted(_NARROW_PEER_POOLS)}）"
    )


__all__ = [
    "BETA_MIN_PEERS_BROAD",
    "BETA_MIN_PEERS_NARROW",
    "BETA_MIN_PEERS_UNKNOWN",
    "CALIBRATION_EVIDENCE",
    "DEFAULT_CALIBRATION",
    "TIER_MODERATE",
    "TIER_STABLE",
    "TIER_STABLE_MAX_DISPERSION",
    "TIER_VOLATILE",
    "TIER_VOLATILE_MIN_DISPERSION",
    "ThresholdCalibration",
    "beta_min_peers_for",
    "calibration_evidence_note",
    "calibration_for",
    "calibration_table_note",
    "thresholds_for_tier",
    "tier_for_dispersion",
]
