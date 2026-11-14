"""
models/multiples.py - Relative Valuation Multiples: P/E, EV/EBITDA, EV/Sales, P/B, FCF Yield

Peer/sector multiples must be supplied (kwargs) or looked up from a sector table.
Never use the subject company's own trailing PE / EV/EBITDA / P/B — that is a
tautology (multiple × own metric ≈ current price).
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from config import ModelName, SolverStatus, get_logger
from data.models import FinancialData
from models.base import ValuationAssumption, ValuationModel, ValuationResult
from valuation.caliber import MetricMeaning, build_caliber_contract

log = get_logger("models.multiples")

# Peer-multiple name → CaliberContract metric key. The caliber of *whether* a
# multiple is meaningful for a company archetype (bank FCF, REIT FFO, unit-econ
# build-out earnings, energy sales) is an ENGINE output; this layer must read
# the contract instead of re-deriving it inline (ADR-024).
_MULTIPLE_TO_CONTRACT_KEY: dict = {
    "P/E": "P/E",
    "EV/EBITDA": "EV_EBITDA",
    "EV/Sales": "EV_Sales",
    "P/B": "P/B",
    "FCF Yield": "FCF_Yield",
}

# Coarse sector defaults (NOT the company's own trading multiple).
# Used only when Yahoo sector/industry is present. Missing comps → insufficient.
#
# The "Software - *" / "Semiconductors" / "AI/Cloud Infrastructure" keys are the
# finer buckets used when the classified BusinessType is known, so that a SaaS
# company is not valued on generic "Technology" multiples that also cover
# semiconductors and capital-intensive compute infrastructure.
SECTOR_PEER_MULTIPLES: dict = {
    "P/E": {
        "Technology": 22.0, "Consumer Cyclical": 16.0, "Industrials": 16.0,
        "Communication Services": 18.0, "Healthcare": 20.0, "Consumer Defensive": 18.0,
        "Energy": 12.0, "Basic Materials": 14.0, "Utilities": 16.0,
        "Financial Services": 12.0, "Banks": 11.0, "Real Estate": 18.0,
        "Software - SaaS": 30.0, "Software - Mature": 25.0,
        "Semiconductors": 24.0, "AI/Cloud Infrastructure": 35.0,
    },
    "EV/EBITDA": {
        "Technology": 14.0, "Consumer Cyclical": 10.0, "Industrials": 10.0,
        "Communication Services": 11.0, "Healthcare": 13.0, "Consumer Defensive": 11.0,
        "Energy": 6.0, "Basic Materials": 8.0, "Utilities": 10.0,
        "Financial Services": 10.0, "Banks": 9.0, "Real Estate": 16.0,
        "Software - SaaS": 20.0, "Software - Mature": 17.0,
        "Semiconductors": 15.0, "AI/Cloud Infrastructure": 18.0,
    },
    "EV/Sales": {
        "Technology": 4.0, "Consumer Cyclical": 1.2, "Industrials": 1.2,
        "Communication Services": 2.5, "Healthcare": 3.0, "Consumer Defensive": 1.5,
        "Energy": 1.5, "Basic Materials": 1.5, "Utilities": 3.0,
        "Financial Services": 3.5, "Banks": 3.0, "Real Estate": 8.0,
        "Software - SaaS": 6.0, "Software - Mature": 5.0,
        "Semiconductors": 6.0, "AI/Cloud Infrastructure": 8.0,
    },
    "P/B": {
        "Technology": 6.0, "Consumer Cyclical": 2.5, "Industrials": 3.0,
        "Communication Services": 3.0, "Healthcare": 4.0, "Consumer Defensive": 3.5,
        "Energy": 1.8, "Basic Materials": 2.0, "Utilities": 1.8,
        "Financial Services": 1.2, "Banks": 1.2, "Real Estate": 1.5,
        "Software - SaaS": 8.0, "Software - Mature": 7.0,
        "Semiconductors": 6.0, "AI/Cloud Infrastructure": 7.0,
    },
    "FCF Yield": {
        "Technology": 0.035, "Consumer Cyclical": 0.05, "Industrials": 0.05,
        "Communication Services": 0.04, "Healthcare": 0.04, "Consumer Defensive": 0.04,
        "Energy": 0.07, "Basic Materials": 0.06, "Utilities": 0.05,
        "Financial Services": 0.05, "Banks": 0.06, "Real Estate": 0.05,
        "Software - SaaS": 0.025, "Software - Mature": 0.035,
        "Semiconductors": 0.030, "AI/Cloud Infrastructure": 0.015,
    },
}

# Above this implied P/E the earnings base is too small to be a meaningful
# valuation anchor (the multiple is dominated by rounding-level earnings).
_IMMATERIAL_PE_THRESHOLD: float = 100.0
# Above this EBITDA/revenue ratio the EBITDA figure is dominated by D&A
# (typical for a capital-intensive build-out) and is not comparable.
_DNA_LOADED_EBITDA_MARGIN: float = 0.90
# Classification confidence at or below this floor means the peer-multiple
# mapping is not validated by provider sector/industry data. The classifier
# caps confidence to *exactly* this value when sector/industry is missing, so a
# strict `<` test would silently skip the capped case — that gap let a
# 55%-confidence "Bank" present its banker peer P/E and P/B as fully validated
# (Recursion SOFI round3 fix). Use `<=` so the cap is always caught.
_PEER_MULTIPLE_CONF_FLOOR: float = 0.55
# A company whose capex exceeds its own revenue (ratio >= 1.0) while running
# negative FCF in high growth is building out compute capacity (datacenter /
# GPU leasing) — asset-light SaaS and fab-based semiconductor peer multiples
# do not fit its economics.
_COMPUTE_INFRA_CAPEX_RATIO: float = 1.0

# ---------------------------------------------------------------------------
# Peer-source provenance labels (Phase 3 / Session #21).
#
# The user demanded that the report distinguish HOW a peer multiple was
# obtained, not just its value — a multiple taken from an exact provider
# industry match carries far more weight than one guessed from a low-confidence
# classification fallback. These labels are the engine's honest provenance
# contract; the report renders them verbatim (no renderer-side guesswork).
# ---------------------------------------------------------------------------
PEER_SOURCE_EXACT_INDUSTRY = "EXACT_INDUSTRY"              # Yahoo sector/industry exact match
PEER_SOURCE_SECTOR_FALLBACK = "SECTOR_FALLBACK"            # fuzzy keyword / sector bucket
PEER_SOURCE_BUSINESS_TYPE_FALLBACK = "BUSINESS_TYPE_FALLBACK"  # classified BusinessType → bucket
PEER_SOURCE_APPROXIMATE = "APPROXIMATE"                    # exposure / hybrid / compute re-route
# Human-readable gloss for the report line.
PEER_SOURCE_LABELS: dict = {
    PEER_SOURCE_EXACT_INDUSTRY: "供应商行业/板块精确匹配",
    PEER_SOURCE_SECTOR_FALLBACK: "板块关键词模糊回退",
    PEER_SOURCE_BUSINESS_TYPE_FALLBACK: "分类业务类型回退",
    PEER_SOURCE_APPROXIMATE: "近似回退（暴露度/混合/重路由）",
}

# ---------------------------------------------------------------------------
# Manually curated AI-cloud / GPU-infrastructure / neocloud peer group.
#
# `peers` lists the comparables a human analyst would use for a capital-
# intensive compute build-out. The indicative *band* is derived from the
# AI/Cloud Infrastructure anchor with a fixed width — it is a STATIC reference,
# NOT live peer quotes. Live peer multiples would require a market data feed.
# ---------------------------------------------------------------------------
AI_CLOUD_PEER_GROUP: dict = {
    "label": "AI Cloud / GPU Infrastructure / Neocloud",
    "peers": [
        "CoreWeave (CRWV)", "IREN (IREN)", "Equinix (EQIX)",
        "Oracle Cloud (ORCL)", "Nebius (NBIS)",
    ],
    "band_width": 0.625,  # ±62.5% around the anchor (e.g. EV/Sales 8 → [3.0, 13.0])
}



class MultiplesModel(ValuationModel):
    """Relative valuation using peer multiples (sector table or explicit kwargs)."""

    RANGE_BOUNDS: dict = {
        "P/E": {"low": 10.0, "high": 30.0},
        "EV/EBITDA": {"low": 5.0, "high": 22.0},
        "EV/Sales": {"low": 0.5, "high": 8.0},
        "P/B": {"low": 0.8, "high": 6.0},
        "FCF Yield": {"low": 0.02, "high": 0.08},
    }

    def __init__(self, multiple_name: str = "P/E") -> None:
        super().__init__(name=multiple_name)
        self.multiple_name = multiple_name

    def applicability_check(
        self, data: FinancialData, profile: Any
    ) -> Tuple[bool, List[str]]:
        reasons: List[str] = []
        ttm = data.ttm
        m = self.multiple_name
        mkt = data.market

        # Caliber gate (ADR-024): the engine's CaliberContract declares whether
        # this multiple is meaningful for the company archetype. A metric that
        # is NOT_MEANINGFUL (e.g. EV/EBITDA for a bank, P/E / FCF Yield for a
        # pre-profit unit-econ build-out) is not applicable — the judgement is
        # read here, never re-derived inline.
        contract = build_caliber_contract(profile)
        metric_key = _MULTIPLE_TO_CONTRACT_KEY.get(m)
        if metric_key is not None:
            meaning = contract.meaning(metric_key)
            if meaning is MetricMeaning.NOT_MEANINGFUL:
                reasons.append(
                    f"{m} not meaningful for archetype '{contract.archetype}'"
                    f"{contract.metric_note(metric_key)}"
                )

        if m == "P/E":
            if ttm is None or ttm.eps is None or ttm.eps <= 0:
                reasons.append("P/E requires positive EPS")
            if mkt.shares_outstanding is None or mkt.shares_outstanding <= 0:
                reasons.append("Shares outstanding required for P/E")
            # Earnings-meaningfulness guard: with a rounding-level net income the
            # multiple is not a usable valuation anchor (e.g. $42M NI on a $55B
            # market cap ⇒ implied P/E > 1000x).
            implied_pe = None
            if ttm is not None and ttm.eps and ttm.eps > 0 and mkt.current_price:
                implied_pe = mkt.current_price / ttm.eps
            if implied_pe is not None and implied_pe > _IMMATERIAL_PE_THRESHOLD:
                reasons.append(
                    f"P/E not meaningful: implied P/E ≈ {implied_pe:,.0f}x (>{_IMMATERIAL_PE_THRESHOLD:.0f}x) "
                    f"— earnings base immaterial relative to price"
                )
        elif m == "EV/EBITDA":
            if ttm is None or ttm.ebitda is None or ttm.ebitda <= 0:
                reasons.append("EV/EBITDA requires positive EBITDA")
            # D&A-loaded EBITDA guard: EBITDA ≥ 90% of revenue means the figure is
            # dominated by add-back of depreciation (capital-intensive build-out)
            # and is not comparable to peer EV/EBITDA.
            if (ttm is not None and ttm.ebitda and ttm.revenue and ttm.revenue > 0
                    and ttm.ebitda / ttm.revenue > _DNA_LOADED_EBITDA_MARGIN):
                reasons.append(
                    f"EV/EBITDA not directly comparable: EBITDA = {ttm.ebitda/ttm.revenue:.0%} of revenue "
                    f"(D&A-dominated, capital-intensive build-out)"
                )
        elif m == "EV/Sales":
            if ttm is None or ttm.revenue is None or ttm.revenue <= 0:
                reasons.append("EV/Sales requires positive revenue")
        elif m == "P/B":
            bvps = data.market.book_value_per_share
            if bvps is None or bvps <= 0:
                reasons.append("P/B requires positive book value per share")
        elif m == "FCF Yield":
            if ttm is None or ttm.free_cash_flow is None or ttm.free_cash_flow <= 0:
                reasons.append("FCF Yield requires positive FCF")
            if data.market.market_cap is None or data.market.market_cap <= 0:
                reasons.append("FCF Yield requires market cap")
        else:
            reasons.append(f"Unknown multiple: {m}")
        return (len(reasons) == 0, reasons)

    def calculate(
        self, data: FinancialData, profile: Any, **kwargs
    ) -> ValuationResult:
        m = self.multiple_name
        sector = data.market.sector or ""
        industry = data.market.industry or ""
        bounds = MultiplesModel.RANGE_BOUNDS[m]

        multiple = kwargs.get("multiple")
        multiple_src = "explicit kwargs"
        peer_source_kind: str = PEER_SOURCE_EXACT_INDUSTRY
        n_peers: Optional[int] = None
        if multiple is None:
            multiple, multiple_src, peer_source_kind, n_peers = self._sector_peer_multiple(data, m, profile)

        if multiple is None:
            return ValuationResult(
                model_name=m,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=[
                    "No peer/sector multiple available (will not use the company's own "
                    f"trading {m} or a silent global default)"
                ],
                assumptions=[],
                breakdown={
                    "sector": sector or "Unknown",
                    "industry": industry or "Unknown",
                    "peer_source_kind": peer_source_kind,
                    "peer_sample_size": None,
                },
                data_quality_score=data.quality.data_quality_score,
            )

        assumptions = [
            ValuationAssumption("Multiple", round(multiple, 4), "x", multiple_src),
            ValuationAssumption("Multiple Low", bounds["low"], "x", "Range bound"),
            ValuationAssumption("Multiple High", bounds["high"], "x", "Range bound"),
        ]

        ttm = data.ttm
        mkt = data.market
        if ttm is None and m in {"P/E", "EV/EBITDA", "EV/Sales", "FCF Yield"}:
            return ValuationResult(
                model_name=m,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["TTM financials required for this multiple"],
                assumptions=assumptions,
                breakdown={},
                data_quality_score=data.quality.data_quality_score,
            )
        pps: Optional[float] = None
        ev: Optional[float] = None
        eq: Optional[float] = None
        breakdown: dict = {
            "multiple": multiple,
            "multiple_source": multiple_src,
            "peer_source_kind": peer_source_kind,
            "peer_sample_size": n_peers,
            "sector": sector or "Unknown",
            "used_own_multiple": False,
        }

        if m == "P/E":
            eps = ttm.eps if ttm is not None else None
            if eps and eps > 0:
                pps = multiple * eps
                eq = pps * (mkt.shares_outstanding or 0)
                ev = eq + mkt.net_debt_or_zero()
        elif m == "EV/EBITDA":
            if ttm is not None and ttm.ebitda and ttm.ebitda > 0:
                ev = multiple * ttm.ebitda
                eq = ev - mkt.net_debt_or_zero()
                shares = mkt.shares_outstanding or ttm.shares_outstanding
                if shares and shares > 0 and eq is not None:
                    pps = eq / shares
        elif m == "EV/Sales":
            if ttm is not None and ttm.revenue and ttm.revenue > 0:
                ev = multiple * ttm.revenue
                eq = ev - mkt.net_debt_or_zero()
                shares = mkt.shares_outstanding or ttm.shares_outstanding
                if shares and shares > 0 and eq is not None:
                    pps = eq / shares
        elif m == "P/B":
            bvps = mkt.book_value_per_share
            if bvps and bvps > 0:
                pps = multiple * bvps
                eq = pps * (mkt.shares_outstanding or 0)
                ev = eq + mkt.net_debt_or_zero()
        elif m == "FCF Yield":
            if ttm is not None and ttm.free_cash_flow and ttm.free_cash_flow > 0 and multiple > 0:
                eq = ttm.free_cash_flow / multiple
                shares = mkt.shares_outstanding or ttm.shares_outstanding
                if shares and shares > 0:
                    pps = eq / shares
                ev = eq + mkt.net_debt_or_zero()

        if pps is None:
            return ValuationResult(
                model_name=m,
                status=SolverStatus.INSUFFICIENT_DATA,
                notes=["Unable to compute value with current inputs"],
                assumptions=assumptions,
                breakdown=breakdown,
                data_quality_score=data.quality.data_quality_score,
            )

        breakdown.update({"enterprise_value": ev, "equity_value": eq, "value_per_share": pps})
        low_pps, high_pps = self._range(pps, bounds)
        breakdown["low_value_per_share"] = low_pps
        breakdown["high_value_per_share"] = high_pps
        notes = [f"Peer/sector {m} = {multiple:g} ({multiple_src})"]
        gloss = PEER_SOURCE_LABELS.get(peer_source_kind, "")
        if n_peers is not None:
            notes.append(f"Peer 来源：{peer_source_kind}（{gloss}），可比样本 n={n_peers}")
        else:
            notes.append(
                f"Peer 来源：{peer_source_kind}（{gloss}），静态行业锚点"
                "（无可比样本清单，n_peers 不可得；非实时同业报价）"
            )

        # Classification uncertainty → valuation uncertainty (Issue #3 fix)
        bt = getattr(profile, "business_type", None) if profile else None
        conf = float(getattr(profile, "classification_confidence", 0.0) or 0.0)
        unknown_or_hybrid = (
            bt == "Unknown"
            or bool(getattr(profile, "is_hybrid_classification", False))
        )
        bt_mapped_via_classification = "classified type" in multiple_src
        approx_fallback = "(APPROXIMATE)" in multiple_src
        # Caliber contract (ADR-024): a REFERENCE_ONLY multiple is directional
        # only for this archetype — it must never surface as a SOLVED anchor.
        contract = build_caliber_contract(profile)
        metric_key = _MULTIPLE_TO_CONTRACT_KEY.get(m)
        reference_only = (
            metric_key is not None
            and contract.meaning(metric_key) is MetricMeaning.REFERENCE_ONLY
        )
        multiple_unvalidated = (
            approx_fallback
            or reference_only
            or (unknown_or_hybrid and bt_mapped_via_classification)
            or (bt_mapped_via_classification and conf <= _PEER_MULTIPLE_CONF_FLOOR)
        )

        status = SolverStatus.SOLVED
        if multiple_unvalidated:
            status = SolverStatus.APPROXIMATE
            if reference_only:
                notes.append(
                    f"⚠️ {m} is REFERENCE_ONLY under archetype '{contract.archetype}' "
                    f"(directional, not a core anchor)."
                )
            elif approx_fallback:
                notes.append(
                    "⚠️ Peer multiple is APPROXIMATE: not sourced from a provider "
                    "sector/industry field but from the classification / peer fallback chain. "
                    "Directional reference only."
                )
            else:
                notes.append(
                    "⚠️ Peer multiple NOT FULLY VALIDATED: classification uncertain "
                    "(Unknown or Low confidence); result treated as Approximate."
                )
            notes.append(f"   Peer multiple source = {multiple_src}")
            if conf <= _PEER_MULTIPLE_CONF_FLOOR:
                notes.append(f"   Classification confidence = {conf:.0%}")
        if data.market.current_price:
            pct = (pps - data.market.current_price) / data.market.current_price
            notes.append(f"当前价格 vs 估值：{pct:+.1%}")
        breakdown["classification_confidence"] = conf
        breakdown["multiple_unvalidated"] = multiple_unvalidated
        return ValuationResult(
            model_name=m,
            status=status,
            value_per_share=pps,
            enterprise_value=ev,
            equity_value=eq,
            assumptions=assumptions,
            notes=notes,
            breakdown=breakdown,
            data_quality_score=data.quality.data_quality_score,
        )

    # Fine-grained buckets: SaaS / mature software / semiconductors / capital-
    # intensive compute infrastructure are distinct peer groups. Collapsing them
    # into a single "Technology" bucket distorted SaaS multiples (P/E 22,
    # EV/Sales 4) onto capital-intensive, negative-FCF compute companies.
    _BT_TO_SECTOR = {
        "MatureTech": "Software - Mature",
        "SaaS": "Software - SaaS",
        "Semiconductor": "Semiconductors",
        "FinTech": "Financial Services",
        "Neobank": "Banks",
        "ConsumerCyclical": "Consumer Cyclical",
        "ConsumerStaples": "Consumer Defensive",
        "REIT": "Real Estate",
        "Bank": "Banks",
        "Insurance": "Financial Services",
        "Commodity": "Basic Materials",
        "Utilities": "Utilities",
        "Energy": "Energy",
        "Industrial": "Industrials",
        "Healthcare": "Healthcare",
        "Telecom": "Communication Services",
        "Media": "Communication Services",
        "Conglomerate": "Industrials",
        "Diversified": "Industrials",
    }

    # Mapping from BusinessExposure labels (see _build_exposures in ml_classifier.py +
    # classifier.py) to SECTOR_PEER_MULTIPLES sector keys. Used as the LAST fallback when
    # classification is Unknown and Yahoo sector/industry is missing.
    _EXPOSURE_LABEL_TO_SECTOR = {
        "Financial (Bank/Insurance/REIT)": "Financial Services",
        "Technology (SaaS/Tech/Semi)": "Technology",
        "Consumer Cyclical": "Consumer Cyclical",
        "Hard Assets": "Basic Materials",
        "Conglomerate/Diversified": "Industrials",
        "Financial Services": "Financial Services",
        "Technology": "Technology",
        "FinTech / Digital Financial Services": "Financial Services",
        "Digital Banking / Neobank": "Financial Services",
    }

    # Tech-family buckets a capital-intensive compute build-out may be re-routed
    # away from (software/SaaS/semi multiples do not fit datacenter/GPU leasing).
    _COMPUTE_INFRA_SOURCE_BUCKETS = {
        "Technology", "Software - SaaS", "Software - Mature", "Semiconductors",
    }

    def _compute_infra_override(self, data: FinancialData, profile: Any) -> bool:
        """Detect capital-intensive compute / AI-cloud infrastructure economics.

        A company spending more on capex than it earns in revenue while running
        negative FCF in high growth is building out datacenter / GPU capacity.
        Its economics (heavy D&A, negative FCF, near-zero earnings) do not fit
        asset-light SaaS or fab-based semiconductor peer multiples.
        """
        if profile is None:
            return False
        if getattr(profile, "is_financial_institution", False) or getattr(profile, "is_reit", False):
            return False
        if getattr(profile, "capital_intensity", "") != "Very Capital Intensive":
            return False
        if getattr(profile, "growth_profile", "") not in ("High Growth", "Moderate Growth"):
            return False
        cf = str(getattr(profile, "cash_flow_profile", "")).lower()
        if not ("weak" in cf or "neg" in cf):
            return False
        ttm = data.ttm
        if ttm is None:
            return False
        revenue = ttm.revenue
        capex = ttm.capex
        if revenue is None or revenue <= 0 or capex is None:
            return False
        return abs(capex) / revenue >= _COMPUTE_INFRA_CAPEX_RATIO

    @staticmethod
    def _ai_cloud_peer_note(anchor: float) -> str:
        """Indicative peer distribution for the AI-cloud / GPU-infra group.

        Static reference band around the anchor multiple (NOT live peer quotes).
        """
        g = AI_CLOUD_PEER_GROUP
        w = float(g.get("band_width", 0.625))
        lo = anchor * (1 - w)
        hi = anchor * (1 + w)
        peers = ", ".join(g.get("peers", []))
        return (
            f"｜人工可比组 {g.get('label','AI Cloud')}: [{lo:g}x ~ {anchor:g}x ~ {hi:g}x]"
            f"（静态参考带，非实时可比报价）；可比公司 = {peers}"
        )

    def _sector_peer_multiple(
        self, data: FinancialData, m: str, profile: Any = None
    ) -> Tuple[Optional[float], str, str, Optional[int]]:
        """Return (value, source_text, source_kind, n_peers).

        `source_kind` is one of the PEER_SOURCE_* provenance labels; `n_peers`
        is the number of comparables the anchor was derived from, or ``None``
        when the anchor is a static sector figure with no peer sample list
        (the report must then say so — peer data is never fabricated).
        """
        table = SECTOR_PEER_MULTIPLES.get(m) or {}
        if not table:
            return None, f"no sector table defined for {m}", PEER_SOURCE_APPROXIMATE, None

        key, src, blend, kind = self._resolve_peer_bucket(data, m, table, profile)
        if key is None and blend is None:
            return None, src, kind, None

        n_peers: Optional[int] = None

        # AI/Cloud compute-infrastructure re-route: only upgrade *within* the
        # tech family so financials/energy/utilities are never re-labelled.
        if (key is not None and key in self._COMPUTE_INFRA_SOURCE_BUCKETS
                and "AI/Cloud Infrastructure" in table
                and self._compute_infra_override(data, profile)):
            anchor = float(table["AI/Cloud Infrastructure"])
            key = "AI/Cloud Infrastructure"
            kind = PEER_SOURCE_APPROXIMATE
            n_peers = len(AI_CLOUD_PEER_GROUP.get("peers", []))
            src = (f"{src} → re-routed to table[AI/Cloud Infrastructure] "
                   f"(capital-intensive compute build-out: capex > revenue, negative FCF, "
                   f"high growth) (APPROXIMATE){self._ai_cloud_peer_note(anchor)}")

        if key == "AI/Cloud Infrastructure" and n_peers is None:
            # Curated group also backs a direct AI/Cloud match elsewhere.
            n_peers = len(AI_CLOUD_PEER_GROUP.get("peers", []))

        raw_value = table[key] if key is not None else blend
        if raw_value is None:
            raise ValueError("Peer bucket resolved without a multiple value")
        value = float(raw_value)
        return value, src, kind, n_peers

    def _resolve_peer_bucket(
        self, data: FinancialData, m: str, table: dict, profile: Any = None
    ) -> Tuple[Optional[str], str, Optional[float], str]:
        """Return (table_key, source, blend_value, source_kind); key/blend 恰一非空.

        Fallback chain (4 levels; stop on first match):
          1. Yahoo sector exact match              → EXACT_INDUSTRY
          2. Yahoo industry / sector fuzzy match   → SECTOR_FALLBACK
          3. Classified business type → peer bucket → BUSINESS_TYPE_FALLBACK
          4. Top business exposures (directional)   → APPROXIMATE
        """
        sector = (data.market.sector or "").strip()
        industry = (data.market.industry or "").strip()
        hay = f"{sector} {industry}".lower()

        # Level 1 — Yahoo sector exact match (strongest signal)
        if sector and sector in table:
            return sector, f"Yahoo sector: {sector} → table[{sector}]", None, PEER_SOURCE_EXACT_INDUSTRY

        # Level 2 — Yahoo industry / sector fuzzy keyword match
        if hay.strip():
            for key, val in table.items():
                if key.lower() in hay:
                    return key, f"Yahoo keyword '{sector or industry}' → table[{key}]", None, PEER_SOURCE_SECTOR_FALLBACK
            # Also try 'Banks' / 'Insurance' / 'Fintech' keyword → Financial Services
            fin_keywords = ("bank", "insurance", "fintech", "credit", "lending",
                            "capital markets", "asset management")
            if any(k in hay for k in fin_keywords) and "Financial Services" in table:
                return "Financial Services", "Yahoo Fin/Bank keyword → table[Financial Services]", None, PEER_SOURCE_SECTOR_FALLBACK
            tech_keywords = ("software", "internet", "semiconductor", "tech", "saas",
                             "cloud", "it ", "information technology")
            if any(k in hay for k in tech_keywords) and "Technology" in table:
                return "Technology", "Yahoo Tech keyword → table[Technology]", None, PEER_SOURCE_SECTOR_FALLBACK

        # Level 3 — Classified business type → sector (trusted when not Unknown)
        bt = getattr(profile, "business_type", None) if profile else None
        if bt and bt != "Unknown":
            mapped = self._BT_TO_SECTOR.get(bt)
            if mapped and mapped in table:
                return mapped, f"classified type {bt} → sector table[{mapped}]", None, PEER_SOURCE_BUSINESS_TYPE_FALLBACK
            # No exact mapping for this BusinessType — do NOT fuzzy-match by
            # first word (that caused ConsumerStaples → Consumer Cyclical).
            # Instead, log a warning and fall through to Level 4.
            log.warning(
                f"BusinessType '{bt}' has no explicit peer-multiple mapping; "
                f"falling through to exposure-based lookup (no fuzzy match)"
            )

        # Level 4 — Last-resort: use top exposures (ML or rule) to find a sector.
        # When classification is Unknown / FinTech hybrid, this provides a directional
        # (Approximate) peer multiple instead of returning No-Data.
        exposures = getattr(profile, "business_exposures", None) if profile else None
        if exposures:
            # ============================================================
            # Level 4a — FinTech Hybrid blended multiple (HIGHEST PRIORITY
            # inside Level 4). When hybrid_label indicates FinTech/Digital
            # Financials, blend Financial+Tech peer multiples weighted by
            # exposure. Produces a more representative NU-style result.
            # ============================================================
            is_hybrid = bool(getattr(profile, "is_hybrid_classification", False))
            hybrid_label = str(getattr(profile, "hybrid_classification_label", "") or "")
            fintech_like = ("fintech" in hybrid_label.lower()
                            or "digital financial" in hybrid_label.lower()
                            or "tech-enabled finance" in hybrid_label.lower())
            if is_hybrid and fintech_like \
                    and "Financial Services" in table and "Technology" in table:
                fin_w, tech_w = 0.0, 0.0
                for e in exposures:
                    lbl = getattr(e, "label", "") or ""
                    w = float(getattr(e, "weight", 0.0))
                    if any(x in lbl.lower() for x in ("financ", "bank", "insur")):
                        fin_w += w
                    if any(x in lbl.lower() for x in ("tech", "soft", "saas", "semi")):
                        tech_w += w
                if fin_w + tech_w > 0.05:
                    blended = (fin_w * table["Financial Services"]
                               + tech_w * table["Technology"]) / (fin_w + tech_w)
                    return (
                        None,
                        f"FinTech hybrid blend — Fin({fin_w*100:.1f}%)×{table['Financial Services']}x + "
                        f"Tech({tech_w*100:.1f}%)×{table['Technology']}x = {blended:.2f}x (APPROXIMATE)",
                        float(blended),
                        PEER_SOURCE_APPROXIMATE,
                    )

            # ============================================================
            # Level 4b — Single exposure bucket fallback.
            # Try the top-3 heaviest known buckets (skip Unclassified/Unknown/Other).
            # ============================================================
            skip = {"unclassified", "unknown", "other"}
            sorted_exps = sorted(
                [e for e in exposures
                 if isinstance(getattr(e, "label", ""), str)
                 and not any(s in e.label.lower() for s in skip)],
                key=lambda e: -float(getattr(e, "weight", 0.0)),
            )[:3]
            for exp in sorted_exps:
                lbl = getattr(exp, "label", "")
                w = float(getattr(exp, "weight", 0.0))
                if w < 0.05:
                    continue
                direct = self._EXPOSURE_LABEL_TO_SECTOR.get(lbl)
                if direct and direct in table:
                    return (
                        direct,
                        f"top exposure '{lbl}' ({w*100:.1f}%) → sector table[{direct}] (APPROXIMATE)",
                        None,
                        PEER_SOURCE_APPROXIMATE,
                    )
                for key, val in table.items():
                    kw = key.lower().split()[0]
                    if kw and kw in lbl.lower() and len(kw) >= 4:
                        return (
                            key,
                            f"top exposure '{lbl}' keyword '{kw}' → table[{key}] ({w*100:.1f}%) (APPROXIMATE)",
                            None,
                            PEER_SOURCE_APPROXIMATE,
                        )
                if any(x in lbl.lower() for x in ("financ", "bank", "insur")) \
                        and "Financial Services" in table:
                    return (
                        "Financial Services",
                        f"top exposure '{lbl}' ({w*100:.1f}%) → table[Financial Services] (APPROXIMATE)",
                        None,
                        PEER_SOURCE_APPROXIMATE,
                    )
                if any(x in lbl.lower() for x in ("tech", "soft", "saas", "semi")) \
                        and "Technology" in table:
                    return (
                        "Technology",
                        f"top exposure '{lbl}' ({w*100:.1f}%) → table[Technology] (APPROXIMATE)",
                        None,
                        PEER_SOURCE_APPROXIMATE,
                    )

        return None, "no sector table match", None, PEER_SOURCE_APPROXIMATE

    def _range(self, pps: float, bounds: dict) -> Tuple[float, float]:
        mid = (bounds["low"] + bounds["high"]) / 2.0
        ratio_low = bounds["low"] / max(1e-9, mid)
        ratio_high = bounds["high"] / max(1e-9, mid)
        return pps * ratio_low, pps * ratio_high


class PEModel(MultiplesModel):
    NAME = ModelName.PE
    def __init__(self) -> None: super().__init__("P/E")

class EVEBITDAModel(MultiplesModel):
    NAME = ModelName.EV_EBITDA
    def __init__(self) -> None: super().__init__("EV/EBITDA")

class EVSalesModel(MultiplesModel):
    NAME = ModelName.EV_SALES
    def __init__(self) -> None: super().__init__("EV/Sales")

class PBModel(MultiplesModel):
    NAME = ModelName.PB
    def __init__(self) -> None: super().__init__("P/B")

class FCFYieldModel(MultiplesModel):
    NAME = ModelName.FCF_YIELD
    def __init__(self) -> None: super().__init__("FCF Yield")


__all__ = [
    "MultiplesModel",
    "PEModel",
    "EVEBITDAModel",
    "EVSalesModel",
    "PBModel",
    "FCFYieldModel",
    "SECTOR_PEER_MULTIPLES",
    "AI_CLOUD_PEER_GROUP",
    "PEER_SOURCE_EXACT_INDUSTRY",
    "PEER_SOURCE_SECTOR_FALLBACK",
    "PEER_SOURCE_BUSINESS_TYPE_FALLBACK",
    "PEER_SOURCE_APPROXIMATE",
    "PEER_SOURCE_LABELS",
]
