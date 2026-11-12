"""valuation/caliber.py - Engine-emitted caliber contract for metric meaning.

Why this exists (Session #13 follow-up, extends ADR-022)
-------------------------------------------------------
Whether a metric (EV / Net Debt / FCF / EV-EBITDA / FCF-Yield) or a discount
rate (WACC vs cost of equity) is *meaningful* depends on the company's economic
structure (bank / insurer / REIT / standard). Previously every render site
re-derived that judgement inline (``if profile.is_financial_institution: ...``),
which is exactly how the SOFI round-2 contradiction arose: the report's main
model had already switched to the bank caliber while its scenario section kept
the DCF caliber, and neither site knew the other disagreed.

The judgement is now an **engine output**: ``build_caliber_contract(profile)``
returns a frozen :class:`CaliberContract` built from enums. Render sites *read*
the contract and branch on it; they must not re-guess the caliber. Adding a new
archetype means editing this one builder, not every ``if`` in the dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping

__all__ = [
    "MetricMeaning",
    "DiscountCaliber",
    "CaliberContract",
    "build_caliber_contract",
]


class MetricMeaning(str, Enum):
    """Whether a metric carries economic meaning for a given company type."""

    MEANINGFUL = "meaningful"
    # Show the value, but explicitly not as a core anchor (e.g. REIT FCF → FFO).
    REFERENCE_ONLY = "reference_only"
    # Do not use at all; render as N/M with an explanatory note (e.g. bank FCF).
    NOT_MEANINGFUL = "not_meaningful"


class DiscountCaliber(str, Enum):
    """The discount-rate caliber the whole report must use for this company."""

    WACC = "WACC"
    # Banks / insurers: capital is equity, so the correct rate is the cost of
    # equity (CAPM ke). DCF calibers (FCF, net debt, EV) are undefined here.
    COST_OF_EQUITY = "ke"


@dataclass(frozen=True)
class CaliberContract:
    """Frozen declaration of which metrics/caliber apply to this company."""

    archetype: str
    discount: DiscountCaliber
    metrics: Mapping[str, MetricMeaning] = field(default_factory=dict)
    notes: Mapping[str, str] = field(default_factory=dict)
    sensitivity_applicable: bool = True

    def meaning(self, metric: str) -> MetricMeaning:
        """Meaning of `metric`; anything unlisted defaults to MEANINGFUL."""
        return self.metrics.get(metric, MetricMeaning.MEANINGFUL)

    def is_meaningful(self, metric: str) -> bool:
        return self.meaning(metric) is MetricMeaning.MEANINGFUL

    def metric_note(self, metric: str) -> str:
        """Inline caveat (leading space included) for a metric, or ''."""
        return self.notes.get(metric, "")

    def note(self, key: str) -> str:
        """Section-level note keyed by 'overview' / 'sensitivity', or ''."""
        return self.notes.get(key, "")


# ---------------------------------------------------------------------------
# Archetype metric tables. Only non-MEANINGFUL entries need to be listed;
# everything omitted is MEANINGFUL by construction.
# ---------------------------------------------------------------------------
_FINANCIAL_METRICS: Dict[str, MetricMeaning] = {
    "EV": MetricMeaning.NOT_MEANINGFUL,
    "NetDebt": MetricMeaning.NOT_MEANINGFUL,
    "FCF": MetricMeaning.NOT_MEANINGFUL,
    "EV_EBITDA": MetricMeaning.NOT_MEANINGFUL,
    "FCF_Yield": MetricMeaning.NOT_MEANINGFUL,
    "P/E": MetricMeaning.MEANINGFUL,
    "P/B": MetricMeaning.MEANINGFUL,
    "DDM": MetricMeaning.MEANINGFUL,
}

_REIT_METRICS: Dict[str, MetricMeaning] = {
    "FCF": MetricMeaning.REFERENCE_ONLY,
}

# Unit-economics build-out (pre-profit, capital-intensive commissioning phase,
# e.g. GPU / datacenter neoclouds). Earnings-based anchors are structurally
# unavailable — the whole investment case is the installed capacity × mature
# unit economics, so only a *revenue*-anchored lens is meaningful.
_UNIT_ECON_METRICS: Dict[str, MetricMeaning] = {
    "P/E": MetricMeaning.NOT_MEANINGFUL,
    "FCF_Yield": MetricMeaning.NOT_MEANINGFUL,
    # EBITDA is positive only because D&A is added back on a just-built asset
    # base → directional reference, never a core anchor.
    "EV_EBITDA": MetricMeaning.REFERENCE_ONLY,
    # Book value lags the replacement cost of the fleet under construction.
    "P/B": MetricMeaning.REFERENCE_ONLY,
    "EV_Sales": MetricMeaning.MEANINGFUL,
}

# Asset-revaluation archetype (energy / commodity producers). The valuation
# lens is the asset/reserve base, so flow-based *sales* multiples are secondary
# (revenue is price × volume and swings with the commodity cycle).
_ENERGY_METRICS: Dict[str, MetricMeaning] = {
    "EV_Sales": MetricMeaning.REFERENCE_ONLY,
}


def _is_unit_econ_archetype(profile: Any) -> bool:
    """True when the profile is a pre-profit capital-intensive build-out.

    The classifier adds ``EV/Sales (Unit Econ)`` / ``Replacement NAV`` to the
    applicable-model list only for that candidate class, so the archetype is
    read from the engine's own routing decision rather than re-derived here.
    """
    models = getattr(profile, "applicable_models", None) or []
    return "EV/Sales (Unit Econ)" in models or "Replacement NAV" in models


def _is_energy_archetype(profile: Any) -> bool:
    bt = getattr(profile, "business_type", None) or getattr(profile, "effective_business_type", None)
    return str(bt) == "Energy"


def build_caliber_contract(profile: Any) -> CaliberContract:
    """Return the caliber contract for `profile` (the single caliber source)."""
    is_fin = bool(profile is not None and getattr(profile, "is_financial_institution", False))
    is_reit = bool(profile is not None and getattr(profile, "is_reit", False))

    if is_fin:
        return CaliberContract(
            archetype="financial",
            discount=DiscountCaliber.COST_OF_EQUITY,
            metrics=dict(_FINANCIAL_METRICS),
            notes={
                "overview": (
                    "⚠️ 金融机构：EV / Net Debt / FCF / EV/EBITDA 对银行/保险非标准指标，"
                    "借贷为业务本身，解读需谨慎"
                ),
                "EV": " _（金融机构不适用，银行借贷=业务）_",
                "NetDebt": " _（金融机构债务≠普通企业债务）_",
                "EV_EBITDA": " _（银行/保险业不适用）_",
                "FCF": " _（金融机构 FCF 定义不同于普通企业，详见风险部分备注）_",
                "sensitivity": (
                    "_金融机构（银行/保险）不适用 DCF 敏感性矩阵：WACC / 终值增长 / FCF 口径对"
                    "借贷型业务无经济含义，展示会与银行主模型冲突。请以 Bank DDM/RIM、P/B、P/E "
                    "结果为估值锚点。_"
                ),
            },
            sensitivity_applicable=False,
        )

    if is_reit:
        return CaliberContract(
            archetype="reit",
            discount=DiscountCaliber.WACC,
            metrics=dict(_REIT_METRICS),
            notes={
                "overview": "⚠️ REIT：FCF 应参考 FFO / AFFO；此处报告 FCF 仅供对比，不作为核心指标",
                "FCF": " _（REIT 请优先参考 FFO/AFFO）_",
            },
            sensitivity_applicable=True,
        )

    if _is_unit_econ_archetype(profile):
        return CaliberContract(
            archetype="unit_econ",
            discount=DiscountCaliber.WACC,
            metrics=dict(_UNIT_ECON_METRICS),
            notes={
                "overview": (
                    "⚠️ 单位经济学建设期标的：盈利类指标（P/E、FCF Yield）不具备经济含义，"
                    "估值锚点为 EV/Sales × 成熟期单位经济学；EV/EBITDA 与 P/B 仅供方向性参考"
                ),
                "P/E": " _（建设期亏损/微利，P/E 无意义）_",
                "FCF_Yield": " _（建设期 FCF 为负，FCF Yield 无意义）_",
                "EV_EBITDA": " _（EBITDA 由 D&A 加回主导，仅作方向性参考）_",
                "P/B": " _（账面价值低于在建资产的重置成本，仅作方向性参考）_",
            },
            sensitivity_applicable=True,
        )

    if _is_energy_archetype(profile):
        return CaliberContract(
            archetype="energy",
            discount=DiscountCaliber.WACC,
            metrics=dict(_ENERGY_METRICS),
            notes={
                "overview": (
                    "⚠️ 能源资产重估原型：营收随商品价格×产量波动，EV/Sales 仅供方向性参考；"
                    "估值锚点应偏向资产/储量重估与 EV/EBITDA"
                ),
                "EV_Sales": " _（商品价格×产量驱动营收，销售倍数仅作方向性参考）_",
            },
            sensitivity_applicable=True,
        )

    return CaliberContract(
        archetype="standard",
        discount=DiscountCaliber.WACC,
        metrics={},
        notes={},
        sensitivity_applicable=True,
    )
