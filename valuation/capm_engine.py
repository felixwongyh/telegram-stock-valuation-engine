"""valuation/capm_engine.py — CAPM Beta / Cost of Equity Engine (P0 Refactor).

Separates the four distinct beta types that were previously conflated:

  1. **Raw Beta** — the market-data beta as obtained (Yahoo provider / regression),
     never silently modified.

  2. **Normalized Beta** — Raw Beta after an *explicit*, recorded statistical
     adjustment (e.g. Blume shrinkage toward 1.0, winsorization to [0.30, 2.50]).
     The method and parameters are stored in provenance.

  3. **Valuation Beta** — the beta actually used for the base-case valuation.
     May differ from Normalized Beta when an explicit adjustment (e.g. bank ke
     band) is applied. The reason is always recorded.

  4. **Scenario Beta** — derived from Valuation Beta via a transparent shift
     (bear = valuation_beta + shock, bull = valuation_beta − shock). Never
     re-computed from Raw Beta.

CAPM formula:
    Ke = Risk Free Rate + Beta × Equity Risk Premium

The engine always preserves:
  - raw_capm_ke    = Rf + raw_beta × ERP      (the unmodified CAPM result)
  - normalized_ke  = Rf + normalized_beta × ERP
  - adjusted_ke    = Rf + valuation_beta × ERP  (what the valuation actually uses)

If adjusted_ke ≠ raw_capm_ke, the report must show the difference and reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from config import DEFAULT_DCF_CONFIG, get_logger

log = get_logger("valuation.capm_engine")

# Winsorization band (imported from wacc.py for consistency)
BETA_WINSOR_LO: float = 0.30
BETA_WINSOR_HI: float = 2.50

# Bank cost-of-equity sanity band
BANK_KE_BAND: Tuple[float, float] = (0.070, 0.100)


@dataclass
class BetaChain:
    """Full audit trail for a single beta → ke calculation.

    Every CAPM computation (base, bear, bull) produces one of these so the
    report can show the complete chain from raw → adjusted, with reasons.
    """
    # --- Inputs ---
    risk_free_rate: float = 0.0
    equity_risk_premium: float = 0.0
    # Provenance of the risk-free rate so a report can distinguish a
    # market-observed 10Y yield from an assumed default.
    risk_free_source: str = ""

    # --- Beta chain ---
    raw_beta: Optional[float] = None           # from market data, unmodified
    raw_beta_source: str = ""                  # "provider" | "regression" | "bottom_up"
    normalized_beta: Optional[float] = None    # after winsorize / Blume shrinkage
    normalization_method: str = ""             # "winsorize_[0.30,2.50]" | "blume_shrinkage_0.35" | "none"
    valuation_beta: float = 1.0                # the beta actually used for valuation
    valuation_beta_reason: str = ""            # why valuation_beta differs from normalized_beta
    scenario_beta: Optional[float] = None      # for bear/bull: the shifted beta
    scenario_shift: float = 0.0                # +0.30 for bear, -0.30 for bull, 0 for base

    # --- Ke chain ---
    raw_capm_ke: Optional[float] = None        # Rf + raw_beta × ERP (unmodified)
    normalized_ke: Optional[float] = None      # Rf + normalized_beta × ERP
    adjusted_valuation_ke: float = 0.0         # Rf + valuation_beta × ERP (what valuation uses)

    # --- Adjustment metadata ---
    ke_floor: Optional[float] = None           # if a floor was applied
    ke_ceiling: Optional[float] = None         # if a ceiling was applied
    ke_adjusted: bool = False                  # True if adjusted_valuation_ke ≠ raw_capm_ke
    adjustment_reason: str = ""                # full explanation

    # --- Provenance ---
    is_bank: bool = False
    is_base_case: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "risk_free_rate": self.risk_free_rate,
            "risk_free_source": self.risk_free_source,
            "equity_risk_premium": self.equity_risk_premium,
            "raw_beta": self.raw_beta,
            "raw_beta_source": self.raw_beta_source,
            "normalized_beta": self.normalized_beta,
            "normalization_method": self.normalization_method,
            "valuation_beta": self.valuation_beta,
            "valuation_beta_reason": self.valuation_beta_reason,
            "scenario_beta": self.scenario_beta,
            "scenario_shift": self.scenario_shift,
            "raw_capm_ke": self.raw_capm_ke,
            "normalized_ke": self.normalized_ke,
            "adjusted_valuation_ke": self.adjusted_valuation_ke,
            "ke_floor": self.ke_floor,
            "ke_ceiling": self.ke_ceiling,
            "ke_adjusted": self.ke_adjusted,
            "adjustment_reason": self.adjustment_reason,
            "is_bank": self.is_bank,
            "is_base_case": self.is_base_case,
        }


class CAPMEngine:
    """Computes CAPM Ke with full separation of raw / normalized / valuation / scenario beta.

    Usage:
        engine = CAPMEngine()
        chain = engine.compute(
            raw_beta=2.09,
            risk_free_rate=0.045,
            equity_risk_premium=0.055,
            is_bank=True,
        )
        # chain.raw_capm_ke → 0.1604 (15.99%)
        # chain.adjusted_valuation_ke → 0.10 (if bank band applied)
        # chain.ke_adjusted → True
    """

    def compute(
        self,
        *,
        raw_beta: Optional[float],
        risk_free_rate: float,
        equity_risk_premium: float,
        raw_beta_source: str = "provider",
        risk_free_source: str = "",
        is_bank: bool = False,
        # Normalization
        winsorize: bool = True,
        winsor_lo: float = BETA_WINSOR_LO,
        winsor_hi: float = BETA_WINSOR_HI,
        blume_shrinkage: float = 0.0,
        # Valuation adjustment
        apply_bank_ke_band: bool = True,
        bank_ke_band: Tuple[float, float] = BANK_KE_BAND,
        # Scenario
        scenario_shift: float = 0.0,
        is_base_case: bool = True,
        # Override (from resolve_effective_beta / WACC)
        valuation_beta_override: Optional[float] = None,
    ) -> BetaChain:
        """Compute the full beta → ke chain.

        Parameters:
            raw_beta: the unmodified market beta (None → fallback).
            risk_free_rate: Rf (decimal, e.g. 0.045).
            equity_risk_premium: ERP (decimal, e.g. 0.055).
            is_bank: whether the entity is a financial institution.
            winsorize: whether to apply the [lo, hi] winsorization.
            blume_shrinkage: weight to shrink toward 1.0 (0.0 = no shrinkage).
            apply_bank_ke_band: whether to clamp ke to the bank band.
            scenario_shift: beta shift for scenarios (+0.30 bear, -0.30 bull).
            is_base_case: True for the base scenario.
            valuation_beta_override: if provided, use this as the valuation beta
                (e.g. from resolve_effective_beta which already selected bottom-up).

        Returns:
            :class:`BetaChain` with the full audit trail.
        """
        chain = BetaChain(
            risk_free_rate=risk_free_rate,
            risk_free_source=risk_free_source,
            equity_risk_premium=equity_risk_premium,
            raw_beta=raw_beta,
            raw_beta_source=raw_beta_source,
            is_bank=is_bank,
            is_base_case=is_base_case,
            scenario_shift=scenario_shift,
        )

        # --- Step 1: Raw CAPM Ke (preserve the unmodified result) ---
        if raw_beta is not None:
            chain.raw_capm_ke = risk_free_rate + raw_beta * equity_risk_premium

        # --- Step 2: Normalized Beta ---
        if raw_beta is None:
            # Fallback
            normalized = float(DEFAULT_DCF_CONFIG.default_unlevered_beta)
            chain.normalized_beta = normalized
            chain.normalization_method = "fallback_default_beta"
        else:
            normalized = float(raw_beta)
            methods = []

            if winsorize:
                clamped = max(winsor_lo, min(winsor_hi, normalized))
                if abs(clamped - normalized) > 1e-9:
                    methods.append(f"winsorize_[{winsor_lo},{winsor_hi}]")
                normalized = clamped

            if blume_shrinkage > 0:
                normalized = (1 - blume_shrinkage) * normalized + blume_shrinkage * 1.0
                methods.append(f"blume_shrinkage_{blume_shrinkage:.2f}")

            chain.normalized_beta = normalized
            chain.normalization_method = "; ".join(methods) if methods else "none"

        chain.normalized_ke = risk_free_rate + chain.normalized_beta * equity_risk_premium

        # --- Step 3: Valuation Beta ---
        # The valuation beta is what the base-case valuation actually uses.
        # It may differ from normalized_beta due to:
        #   (a) bank ke band clamping
        #   (b) an override from resolve_effective_beta (bottom-up selection)
        #   (c) scenario shift
        if valuation_beta_override is not None:
            chain.valuation_beta = float(valuation_beta_override)
            chain.valuation_beta_reason = "override from resolve_effective_beta (bottom-up or WACC-selected)"
        else:
            chain.valuation_beta = chain.normalized_beta
            chain.valuation_beta_reason = "normalized_beta (no override)"

        # --- Step 4: Bank ke band adjustment (TRANSPARENT, not hidden) ---
        ke = risk_free_rate + chain.valuation_beta * equity_risk_premium
        adjustment_reasons: list[str] = []

        if is_bank and apply_bank_ke_band and is_base_case and equity_risk_premium > 0:
            # Clamp beta so ke stays within [bank_lo, bank_hi]
            # This is equivalent to clamping ke, but done via beta for auditability.
            beta_hi = (bank_ke_band[1] - risk_free_rate) / equity_risk_premium
            beta_lo = (bank_ke_band[0] - risk_free_rate) / equity_risk_premium
            clamped_beta = max(beta_lo, min(beta_hi, chain.valuation_beta))
            if abs(clamped_beta - chain.valuation_beta) > 1e-9:
                adjustment_reasons.append(
                    f"Bank ke band [{bank_ke_band[0]:.1%}, {bank_ke_band[1]:.1%}] applied: "
                    f"β clamped from {chain.valuation_beta:.2f} to {clamped_beta:.2f} "
                    f"(raw CAPM ke={chain.raw_capm_ke:.2%} → adjusted ke={risk_free_rate + clamped_beta * equity_risk_premium:.2%})"
                )
                chain.valuation_beta = clamped_beta
                chain.valuation_beta_reason = (
                    "bank ke band clamp: " + chain.valuation_beta_reason
                )
                chain.ke_floor = bank_ke_band[0]
                chain.ke_ceiling = bank_ke_band[1]
            ke = risk_free_rate + chain.valuation_beta * equity_risk_premium

        # --- Step 5: Scenario shift ---
        # Scenario betas are derived from the VALUATION beta (after bank band
        # if applied), NOT from raw beta. This ensures Base/Bear/Bull share the
        # same basis.
        if scenario_shift != 0:
            scenario_beta = chain.valuation_beta + scenario_shift
            # Apply winsorization to scenario beta too (guard rail)
            scenario_beta = max(winsor_lo, min(winsor_hi, scenario_beta))
            chain.scenario_beta = scenario_beta
            # For scenarios, the ke is computed from scenario_beta directly,
            # WITHOUT the bank band (scenarios must stress beyond the band).
            ke = risk_free_rate + scenario_beta * equity_risk_premium
            chain.valuation_beta = scenario_beta
            chain.valuation_beta_reason = (
                f"scenario shift {scenario_shift:+.2f} from base valuation beta → "
                f"scenario_beta={scenario_beta:.2f} (bank ke band NOT applied to scenarios)"
            )

        chain.adjusted_valuation_ke = ke

        # --- Step 6: Record whether adjustment occurred ---
        if chain.raw_capm_ke is not None and abs(ke - chain.raw_capm_ke) > 1e-6:
            chain.ke_adjusted = True
            if not adjustment_reasons:
                adjustment_reasons.append(
                    f"Adjusted ke ({ke:.2%}) differs from raw CAPM ke ({chain.raw_capm_ke:.2%})"
                )
        chain.adjustment_reason = "; ".join(adjustment_reasons) if adjustment_reasons else "none"

        return chain


# ---------------------------------------------------------------------------
# Convenience: compute the base-case beta chain from FinancialData
# ---------------------------------------------------------------------------
def compute_base_capm(
    data: Any,
    *,
    is_bank: bool = False,
    dcf_breakdown: Any = None,
) -> BetaChain:
    """Compute the base-case CAPM chain from FinancialData.

    Reads Rf / ERP from MarketData, raw beta from resolve_effective_beta,
    and applies the bank ke band if ``is_bank`` is True.
    """
    from valuation.wacc import resolve_effective_beta

    mkt = getattr(data, "market", None)
    rf = getattr(mkt, "risk_free_rate", None) or DEFAULT_DCF_CONFIG.risk_free_rate
    erp = getattr(mkt, "equity_risk_premium", None) or DEFAULT_DCF_CONFIG.equity_risk_premium

    eff = resolve_effective_beta(data, dcf_breakdown)
    raw_beta = eff.beta_raw if eff.beta_raw is not None else eff.beta
    source = eff.source if hasattr(eff, "source") else "resolve_effective_beta"

    # If bottom-up beta exists and was selected, pass it as override
    override = None
    bottom_up = getattr(mkt, "bottom_up_beta", None)
    if bottom_up is not None and bottom_up > 0:
        # resolve_effective_beta may have already used it; if raw_beta differs,
        # the override path is taken
        override = eff.beta

    engine = CAPMEngine()
    return engine.compute(
        raw_beta=raw_beta,
        risk_free_rate=float(rf),
        equity_risk_premium=float(erp),
        raw_beta_source=source,
        is_bank=is_bank,
        valuation_beta_override=override if override != raw_beta else None,
    )


def compute_scenario_capm(
    base_chain: BetaChain,
    scenario_shift: float,
    *,
    is_bank: bool = False,
) -> BetaChain:
    """Compute a scenario (bear/bull) CAPM chain from the base chain.

    The scenario beta is derived from the BASE valuation_beta + shift.
    Bank ke band is NOT applied to scenarios (they must stress beyond the band).
    """
    engine = CAPMEngine()
    return engine.compute(
        raw_beta=base_chain.raw_beta,
        risk_free_rate=base_chain.risk_free_rate,
        equity_risk_premium=base_chain.equity_risk_premium,
        raw_beta_source=base_chain.raw_beta_source,
        is_bank=is_bank,
        apply_bank_ke_band=False,  # scenarios do not apply bank band
        scenario_shift=scenario_shift,
        is_base_case=False,
        valuation_beta_override=base_chain.valuation_beta,  # shift from base valuation beta
    )


__all__ = [
    "BetaChain",
    "CAPMEngine",
    "BANK_KE_BAND",
    "BETA_WINSOR_LO",
    "BETA_WINSOR_HI",
    "compute_base_capm",
    "compute_scenario_capm",
]
