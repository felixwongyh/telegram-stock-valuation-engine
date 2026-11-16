"""SOTP valuation model for diversified businesses.

Evidence contract (P1-SOTP)
---------------------------
A sum-of-the-parts valuation is only meaningful when every part is valued on
its OWN evidence. The original fallback derived each "segment" by taking the
company's *own* enterprise value (``market_cap + net_debt``) and splitting it by
ML exposure weights — every segment then re-states the market price, so the
"parts" carry no independent information (circular valuation). The model now
classifies what evidence actually backs each segment and reports one of three
states:

    SOLVED            每一分部都有独立证据（外部传入的分部 EV / 独立同行倍数）
    APPROXIMATE       部分分部有真实财务数据（如 FMP/SEC 分部收入），其余为估算
    INSUFFICIENT_DATA 仅由 ML 暴露度按公司自身 EV 拆分（循环）→ 只展示，不参与共识

The value is still computed and rendered in the INSUFFICIENT_DATA case so the
reader can see it, but ``breakdown["display_only"]`` marks it as non-evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from config import ModelName, SolverStatus, get_logger
from data.models import FinancialData
from models.base import (
    ShareCountBasis,
    ValuationAssumption,
    ValuationModel,
    ValuationResult,
    make_comparability,
    make_share_count,
)
from valuation.equity_bridge import enterprise_to_equity, equity_to_enterprise

log = get_logger("models.sotp")


# ---- SOTP evidence states (the user-requested three-state contract, P1) ----
SOTP_SOLVED = "SOLVED"
SOTP_APPROXIMATE = "APPROXIMATE"
SOTP_INSUFFICIENT = "INSUFFICIENT_DATA"

_STATE_TO_STATUS = {
    SOTP_SOLVED: SolverStatus.SOLVED,
    SOTP_APPROXIMATE: SolverStatus.APPROXIMATE,
    SOTP_INSUFFICIENT: SolverStatus.INSUFFICIENT_DATA,
}

# Revenue provenance labels.
_REV_REPORTED = "reported"    # 来自 FMP / SEC 分部的真实分部收入
_REV_ALLOCATED = "allocated"  # 由 ML 权重（或单一营业整体）分摊的公司营收
_REV_NONE = "none"            # 无营收明细（外部仅提供 EV）


@dataclass
class SOTPSegment:
    """One business line of the SOTP with its evidence provenance (P1-SOTP).

    ``independent`` is True only when the segment EV comes from the segment's
    OWN valuation basis (an externally supplied segment value, or an
    independently sourced peer multiple). A segment that merely inherits the
    company's own EV/Revenue is circular and must never be presented as
    independent evidence for a business line.
    """
    label: str
    segment_ev: float
    revenue: Optional[float] = None
    ebit: Optional[float] = None
    ebitda: Optional[float] = None
    applied_multiple: Optional[float] = None
    multiple_basis: str = ""
    source: str = ""
    revenue_source: str = _REV_NONE
    confidence: float = 0.0
    as_of: Optional[str] = None
    independent: bool = False
    is_adjustment: bool = False  # cash / debt bridge line (not a business part)

    def is_independent_evidence(self) -> bool:
        """True when this business line is valued on its own evidence."""
        return bool(self.independent) and not self.is_adjustment

    def as_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "segment_ev": round(float(self.segment_ev), 2),
            "revenue": round(float(self.revenue), 2) if self.revenue is not None else None,
            "ebit": round(float(self.ebit), 2) if self.ebit is not None else None,
            "ebitda": round(float(self.ebitda), 2) if self.ebitda is not None else None,
            "applied_multiple": (
                round(float(self.applied_multiple), 3)
                if self.applied_multiple is not None else None
            ),
            "multiple_basis": self.multiple_basis,
            "source": self.source,
            "revenue_source": self.revenue_source,
            "confidence": round(float(self.confidence), 3),
            "as_of": self.as_of,
            "independent": self.independent,
        }


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

        supplied = kwargs.get("segments")
        externally_supplied = bool(supplied)
        if externally_supplied:
            segments: List[SOTPSegment] = self._normalize_external_segments(supplied)
        else:
            segments = self._derive_segments_from_profile(data, profile)

        business = [s for s in segments if not s.is_adjustment]
        adjustments = [s for s in segments if s.is_adjustment]
        total_ev = sum(float(s.segment_ev) for s in segments)

        # ---- Three-state evidence classification (P1-SOTP) ------------------
        n_independent = sum(1 for s in business if s.is_independent_evidence())
        n_reported = sum(1 for s in business if s.revenue_source == _REV_REPORTED)
        if business and n_independent == len(business):
            evidence_state = SOTP_SOLVED
        elif n_independent > 0 or n_reported > 0:
            evidence_state = SOTP_APPROXIMATE
        else:
            evidence_state = SOTP_INSUFFICIENT

        debt = float(data.market.total_debt or 0.0)
        cash = float(data.market.cash_and_equivalents or 0.0)
        # Business parts only ⇒ bridge ONCE here. (The old fallback put cash/+debt
        # inside ``segments`` AND bridged again, subtracting net debt twice.) The
        # EV → Equity bridge also carries minority interests, preferred equity,
        # leases and non-operating assets so a Tencent/Alibaba-style structure is
        # not collapsed into a single "net debt" line.
        bridge = enterprise_to_equity(total_ev, data.market)
        equity_value = bridge.equity_value
        shares = data.market.shares_outstanding or (data.ttm.shares_outstanding if data.ttm else None)
        if data.market.shares_outstanding:
            _share_count = make_share_count(
                data.market.shares_outstanding, "MarketData 流通股数", ShareCountBasis.MARKET
            )
        elif data.ttm is not None and data.ttm.shares_outstanding:
            _share_count = make_share_count(
                data.ttm.shares_outstanding, "TTM 财务报表股数", ShareCountBasis.TTM,
                data.ttm.period_end,
            )
        else:
            _share_count = make_share_count(None, "Unknown", ShareCountBasis.UNKNOWN)
        if shares is None or shares <= 0:
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Shares outstanding missing"],
                data_quality_score=data.quality.data_quality_score,
            )
        if equity_value is None:
            # P0-1: a missing EV never bridges to a fabricated equity value.
            return ValuationResult(
                model_name=self.model_name,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["EV→Equity bridge 不可用（企业价值缺失）"] + bridge.notes,
                data_quality_score=data.quality.data_quality_score,
            )

        base_discount = float(kwargs.get("conglomerate_discount", self.conglomerate_discount))
        # Classification uncertainty → discount unvalidated, downgrade to Approximate.
        if hybrid_or_unknown or (low_confidence and bt in {"Conglomerate", "Diversified"}):
            discount = base_discount
            discount_validated = False
            if evidence_state == SOTP_SOLVED:
                evidence_state = SOTP_APPROXIMATE
        else:
            discount = base_discount
            discount_validated = True
        status = _STATE_TO_STATUS[evidence_state]
        display_only = evidence_state == SOTP_INSUFFICIENT
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
            f"SOTP 股权价值 = 分部 EV 合计 − 净债务等索偿 = ${equity_value:,.2f}",
            f"EV→Equity 桥接: {bridge.itemized_note()}",
            f"After {discount:.1%} conglomerate discount, implied value is ${value_per_share:,.2f}/share",
        ]
        notes.extend(bridge.notes)
        if evidence_state == SOTP_INSUFFICIENT:
            notes.append(
                "⚠️ 分部证据不足（INSUFFICIENT_DATA）：各分部由 ML 业务暴露度按公司自身 "
                "EV/Revenue 拆分 → 循环估值，既非独立分部财务数据、亦非独立同行倍数。"
                "结果仅作展示参考，不计入共识中位数。"
            )
        elif evidence_state == SOTP_APPROXIMATE:
            notes.append(
                f"分部证据部分可得（APPROXIMATE）：{n_reported}/{len(business)} 个分部有真实收入，"
                "但适用倍数为公司自身口径，未使用独立同行倍数。"
            )
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
            "segments": {s.label: float(s.segment_ev) for s in segments},
            "segments_detail": [s.as_dict() for s in segments],
            "sotp_state": evidence_state,
            "display_only": display_only,
            "n_business_segments": len(business),
            "n_independent_segments": n_independent,
            "n_reported_revenue_segments": n_reported,
            "n_adjustment_segments": len(adjustments),
            "total_segment_ev": total_ev,
            "debt": debt,
            "cash": cash,
            "equity_bridge": bridge.adjustments,
            "equity_value": equity_value,
            "conglomerate_discount": discount,
            "discount_validated": discount_validated,
            "value_per_share": value_per_share,
            "shares_outstanding": shares,
            "share_count": _share_count.as_dict(),
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
            share_count=_share_count,
            # P1-8: only an SOTP whose parts rest on INDEPENDENT evidence is a
            # comparable anchor. When the parts are the company's own EV/Revenue
            # split by ML weights (APPROXIMATE / INSUFFICIENT) the peer basis is
            # the subject itself — peer_valid=False so the gate can keep it out
            # of the consensus median.
            comparability=make_comparability(
                currency=getattr(data.market, "currency", None),
                financial_period="TTM",
                valuation_date=getattr(data.market, "as_of", None),
                value_basis="equity_per_share",
                peer_valid=(evidence_state == SOTP_SOLVED),
            ),
        )

    # ------------------------------------------------------------------
    # Segment construction
    # ------------------------------------------------------------------
    def _normalize_external_segments(
        self, supplied: Union[Dict[str, float], List[Any], Tuple[Any, ...]]
    ) -> List[SOTPSegment]:
        """Turn caller-supplied segments into :class:`SOTPSegment` records.

        ``calculate(..., segments=...)`` is the *independent* path: the caller
        brings real segment values, so those parts are treated as independent
        evidence (SOLVED). Rich records (``SOTPSegment`` or dicts carrying
        revenue / multiple / source) keep their detail; a plain ``{label: ev}``
        map is accepted too (revenue detail then shows as N/A).
        """
        out: List[SOTPSegment] = []
        items = supplied.items() if isinstance(supplied, dict) else enumerate(supplied)
        for key, raw in items:
            if isinstance(raw, SOTPSegment):
                raw.independent = True
                out.append(raw)
                continue
            if isinstance(raw, dict):
                out.append(SOTPSegment(
                    label=str(raw.get("label", key)),
                    segment_ev=float(raw.get("segment_ev", raw.get("value", 0.0)) or 0.0),
                    revenue=_opt_float(raw.get("revenue")),
                    ebit=_opt_float(raw.get("ebit")),
                    ebitda=_opt_float(raw.get("ebitda")),
                    applied_multiple=_opt_float(raw.get("applied_multiple")),
                    multiple_basis=str(raw.get("multiple_basis", "")),
                    source=str(raw.get("source", "外部输入分部")),
                    revenue_source=str(raw.get("revenue_source", _REV_REPORTED)),
                    confidence=float(raw.get("confidence", 1.0) or 1.0),
                    as_of=raw.get("as_of"),
                    independent=True,
                ))
                continue
            # Plain float value ⇒ an externally supplied segment EV.
            out.append(SOTPSegment(
                label=str(key),
                segment_ev=float(raw or 0.0),
                source="外部传入分部 EV",
                confidence=1.0,
                independent=True,
            ))
        return out

    def _derive_segments_from_profile(
        self, data: FinancialData, profile: Any
    ) -> List[SOTPSegment]:
        """Derive business parts from the best available evidence.

        Priority:
          1. Reported segment revenue (``data.revenue_composition`` from FMP /
             SEC) — real revenue split, but the multiple is the company's own
             ⇒ APPROXIMATE (partial evidence).
          2. ML ``business_exposures`` — weights only, no independent segment
             financials ⇒ INSUFFICIENT_DATA (circular; display-only).
          3. Single operating block as a last resort ⇒ INSUFFICIENT_DATA.
        """
        ttm = data.ttm
        revenue = float(ttm.revenue) if ttm and ttm.revenue else 0.0
        mkt = data.market

        # Company's own EV/Revenue (only used as a *scaling* multiple when no
        # independent segment multiple exists — it is circular by construction).
        ev_rev_mult = 2.0
        ev = 0.0
        if revenue > 0:
            if mkt.market_cap is not None and mkt.net_debt_or_zero() is not None:
                # Equity → EV on the same claim basis the bridge uses (adds
                # minority interest / preferred / leases, removes non-op assets).
                ev = equity_to_enterprise(mkt.market_cap, mkt)
            elif mkt.enterprise_value is not None:
                ev = float(mkt.enterprise_value)
            if ev is not None and ev > 0:
                ev_rev_mult = max(0.5, min(10.0, ev / revenue))

        segments: List[SOTPSegment] = []

        # ---- 1. Reported segment revenue (FMP / SEC) ------------------------
        rc = getattr(data, "revenue_composition", None)
        rc_segments = getattr(rc, "segments", None) if rc is not None else None
        if getattr(rc, "available", False) and rc_segments and len(rc_segments) >= 2 and revenue > 0:
            rc_source = getattr(rc, "source", "segment") or "segment"
            for seg in rc_segments:
                pct = float(getattr(seg, "pct", 0.0) or 0.0)
                if pct <= 0:
                    continue
                seg_rev = revenue * pct
                segments.append(SOTPSegment(
                    label=str(getattr(seg, "label", "Segment")),
                    segment_ev=seg_rev * ev_rev_mult,
                    revenue=seg_rev,
                    applied_multiple=ev_rev_mult,
                    multiple_basis="EV/Revenue（公司自身）",
                    source=f"分部收入（{rc_source}）",
                    revenue_source=_REV_REPORTED,
                    confidence=0.5,
                    as_of=getattr(seg, "as_of", None) or getattr(rc, "as_of", None),
                    independent=False,
                ))
            if segments:
                return segments

        # ---- 2. ML business exposures (circular) ----------------------------
        exposures = getattr(profile, "business_exposures", []) if profile else []
        if exposures and len(exposures) >= 2:
            conf = float(getattr(profile, "classification_confidence", 0.0) or 0.0)
            for exp in exposures:
                label = getattr(exp, "label", "Other")
                weight = float(getattr(exp, "weight", 0.0))
                if weight < 0.03:  # ignore immaterial exposures
                    continue
                seg_rev = revenue * weight if revenue > 0 else None
                segments.append(SOTPSegment(
                    label=str(label),
                    segment_ev=revenue * ev_rev_mult * weight if revenue > 0 else 0.0,
                    revenue=seg_rev,
                    applied_multiple=ev_rev_mult,
                    multiple_basis="EV/Revenue（公司自身）",
                    source="ML business_exposure（无独立分部财务数据）",
                    revenue_source=_REV_ALLOCATED,
                    confidence=conf,
                    independent=False,
                ))
            if segments:
                return segments

        # ---- 3. Last resort: one operating block ---------------------------
        segments.append(SOTPSegment(
            label="Operating Business",
            segment_ev=revenue * ev_rev_mult if revenue > 0 else 1000.0,
            revenue=revenue if revenue > 0 else None,
            applied_multiple=ev_rev_mult,
            multiple_basis="EV/Revenue（公司自身）",
            source="单一营业整体回退（无分部数据）",
            revenue_source=_REV_ALLOCATED if revenue > 0 else _REV_NONE,
            confidence=float(getattr(profile, "classification_confidence", 0.0) or 0.0),
            independent=False,
        ))
        return segments


def _opt_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


__all__ = ["SOTPModel", "SOTPSegment", "SOTP_SOLVED", "SOTP_APPROXIMATE", "SOTP_INSUFFICIENT"]
