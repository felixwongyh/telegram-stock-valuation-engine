"""SOTP valuation model for diversified businesses."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from config import ModelName, SolverStatus, get_logger
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult

log = get_logger("models.sotp")


class SOTPModel(ValuationModel):
    NAME = ModelName.SOTP

    def __init__(self, conglomerate_discount: float = 0.10) -> None:
        super().__init__()
        self.conglomerate_discount = conglomerate_discount

    def applicability_check(self, data: FinancialData, profile: Any) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        bt = getattr(profile, "business_type", None) if profile else None
        conf = float(getattr(profile, "classification_confidence", 0.0) or 0.0)
        is_hybrid = bool(getattr(profile, "is_hybrid_classification", False))
        # ---- Permissive set: SOTP is computable (as Approximate) for ----
        # Conglomerate / Diversified / Unknown / hybrid classifications.
        # Also applicable for companies with significant multi-sector exposure
        # (top-2 exposure weight >= 10%).
        allowed_set = {"Conglomerate", "Diversified", "Unknown"}
        if profile is None:
            reasons.append("No company profile available")
            return False, reasons

        # Check if the company has significant multi-sector exposure
        exposures = getattr(profile, "business_exposures", [])
        has_significant_secondary = False
        second_weight = 0.0
        if len(exposures) >= 2:
            second_weight = float(getattr(exposures[1], "weight", 0.0))
            if second_weight >= 0.10:
                has_significant_secondary = True

        if bt not in allowed_set and not is_hybrid and not has_significant_secondary:
            reasons.append("SOTP is intended for conglomerates/diversified groups")
            return False, reasons

        # Informational warnings (do NOT block calculation — status downgraded in calculate())
        if bt == "Unknown" or is_hybrid:
            reasons.append(
                "SOTP ran for Unknown/hybrid-classified company — conglomerate discount NOT "
                "validated; treat as Approximate result."
            )
        if has_significant_secondary and bt not in allowed_set:
            reasons.append(
                f"SOTP triggered by significant secondary exposure "
                f"(weight={second_weight:.0%}) — business lines differ materially."
            )
        # ADR-023: classification/classifier.py caps classification_confidence to
        # *exactly* 0.55 when sector/industry is missing (min(confidence, 0.55)).
        # A strict `< 0.55` would miss that capped value, silently treating a
        # knowingly-degraded classification as high-confidence → use a closed interval.
        if conf <= 0.55 and bt in {"Conglomerate", "Diversified"}:
            reasons.append(
                "Classification confidence low — conglomerate discount applied without strong signal"
            )
        if data.ttm is None:
            reasons.append("TTM financials required")
            return False, reasons
        return True, reasons

    def calculate(self, data: FinancialData, profile: Any, **kwargs) -> ValuationResult:
        bt = getattr(profile, "business_type", None) if profile else None
        conf = float(getattr(profile, "classification_confidence", 0.0) or 0.0)
        unknown_classification = bt == "Unknown"
        low_confidence = conf <= 0.55  # ADR-023: closed interval (cap lands exactly on 0.55)
        hybrid_or_unknown = bool(getattr(profile, "is_hybrid_classification", False)) or unknown_classification

        segments: Dict[str, float] = kwargs.get("segments", {})
        if not segments:
            segments = self._derive_segments_from_profile(data, profile)

        values = {}
        total_ev = 0.0
        for name, value in segments.items():
            if value < 0:
                values[name] = value
            else:
                values[name] = float(value)
            total_ev += values[name]

        debt = float(data.market.total_debt or 0.0)
        cash = float(data.market.cash_and_equivalents or 0.0)
        equity_value = total_ev - debt + cash
        shares = data.market.shares_outstanding or (data.ttm.shares_outstanding if data.ttm else None)
        if shares is None or shares <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Shares outstanding missing"],
                data_quality_score=data.quality.data_quality_score,
            )

        base_discount = float(kwargs.get("conglomerate_discount", self.conglomerate_discount))
        # Classification uncertainty → discount unvalidated, mark Approximate status
        if hybrid_or_unknown:
            # Don't change the number — just flag it clearly
            discount = base_discount
            discount_validated = False
            status = SolverStatus.APPROXIMATE
        elif low_confidence and bt in {"Conglomerate", "Diversified"}:
            discount = base_discount
            discount_validated = False
            status = SolverStatus.APPROXIMATE
        else:
            discount = base_discount
            discount_validated = True
            status = SolverStatus.SOLVED
        value_per_share = (equity_value * (1 - discount)) / shares

        assumptions = [
            ValuationAssumption("Segments", round(total_ev, 2), "USD", "Sum of segment values"),
            ValuationAssumption("Debt", round(debt, 2), "USD", "Net debt adjustment"),
            ValuationAssumption("Cash", round(cash, 2), "USD", "Cash adjustment"),
            ValuationAssumption(
                "Conglomerate Discount", round(discount, 4), "%",
                "Portfolio discount" + (" (NOT VALIDATED — classification uncertain)"
                                        if not discount_validated else ""),
            ),
        ]
        notes = [
            f"SOTP Equity Value = Segment EV - Debt + Cash = ${equity_value:,.2f}",
            f"After {discount:.1%} conglomerate discount, implied value is ${value_per_share:,.2f}/share",
        ]
        if not discount_validated:
            notes.append(
                "⚠️ Conglomerate discount NOT VALIDATED: classification uncertain (Unknown or Low "
                "confidence). SOTP result should be treated as a reference, not a precise number."
            )
            if bt == "Unknown":
                notes.append(
                    f"Classification: Unknown (p≈{getattr(profile, 'ml_raw_confidence', conf)*100:.0f}% "
                    "from ML); SOTP confidence = Low."
                )
        if data.market.current_price:
            spread = (value_per_share - data.market.current_price) / data.market.current_price
            notes.append(f"Price spread vs market: {spread:+.1%}")

        breakdown = {
            "segments": values,
            "total_segment_ev": total_ev,
            "debt": debt,
            "cash": cash,
            "equity_value": equity_value,
            "conglomerate_discount": discount,
            "discount_validated": discount_validated,
            "value_per_share": value_per_share,
            "shares_outstanding": shares,
            "classification_confidence": conf,
        }

        return ValuationResult(
            model_name=self.model_name,
            status=status,
            value_per_share=value_per_share,
            enterprise_value=total_ev,
            equity_value=equity_value,
            assumptions=assumptions,
            notes=notes,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
        )

    def _derive_segments_from_profile(self, data: FinancialData, profile: Any) -> Dict[str, float]:
        """Derive SOTP segments from the company's business_exposures.

        For hybrid/diversified companies, we use the ML probability distribution
        (via business_exposures) to weight the operating business value.

        Segment structure:
        1. Operating business segments: weighted by exposure weights
        2. Financial assets: cash & equivalents
        3. Investment portfolio: marketable securities (if available)
        4. Other assets: net of debt adjustments

        The operating EV is estimated using a simple EV/Revenue multiple
        derived from the company's own EV/Revenue (if available) or a
        type-appropriate default.
        """
        segments: Dict[str, float] = {}

        # Base revenue as starting point
        ttm = data.ttm
        revenue = float(ttm.revenue) if ttm and ttm.revenue else 0.0
        mkt = data.market

        # Company's own EV/Revenue multiple (most accurate if available)
        ev_rev_mult = 2.0  # default
        if revenue > 0:
            ev = 0.0
            if mkt.market_cap is not None and mkt.net_debt_or_zero is not None:
                ev = float(mkt.market_cap) + float(mkt.net_debt_or_zero())
            elif mkt.enterprise_value is not None:
                ev = float(mkt.enterprise_value)
            if ev > 0 and revenue > 0:
                ev_rev_mult = max(0.5, min(10.0, ev / revenue))

        operating_ev = revenue * ev_rev_mult

        # Get business exposures from profile (ML probability distribution)
        exposures = getattr(profile, "business_exposures", []) if profile else []
        if exposures and len(exposures) >= 2:
            # Use top exposures as SOTP segments
            for exp in exposures:
                label = getattr(exp, "label", "Other")
                weight = float(getattr(exp, "weight", 0.0))
                if weight >= 0.03:  # Only segments with >=3% weight
                    seg_value = operating_ev * weight
                    if seg_value > 0:
                        segments[label] = seg_value
        else:
            # Fallback: single operating segment
            segments["Operating Business"] = operating_ev * 0.80

        # Financial assets segment
        cash = float(mkt.cash_and_equivalents or 0.0)
        if cash > 0:
            segments["Cash & Equivalents"] = cash

        # Add net debt as negative segment (will reduce equity value)
        debt = float(mkt.total_debt or 0.0)
        if debt > 0:
            segments["Debt (deduction)"] = -debt

        # If no segments were created, use a fallback
        if not segments:
            segments["Operating Business"] = max(operating_ev * 0.80, 1000.0)

        return segments


__all__ = ["SOTPModel"]
