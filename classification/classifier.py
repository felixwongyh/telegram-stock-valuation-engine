"""
classification/classifier.py - Business Classification Engine
Classifies companies into 10 business types with explainable rules.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from config import BusinessType, get_logger
from data.models import CompanyProfile, FinancialData

log = get_logger("classification.classifier")


MODELS_BY_TYPE: Dict[BusinessType, List[str]] = {
    BusinessType.MATURE_TECH: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "EV/Sales", "FCF Yield", "Historical Multiples"],
    BusinessType.SAAS: ["DCF", "ReverseDCF", "EV/Sales", "EV/EBITDA", "FCF Yield", "P/E"],
    BusinessType.SEMICONDUCTOR: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "P/B", "Historical Multiples"],
    BusinessType.CONSUMER_CYCLICAL: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "EV/Sales", "P/B"],
    BusinessType.REIT: ["REIT NAV", "P/B", "P/E", "EV/EBITDA"],
    BusinessType.BANK: ["Bank DDM", "Bank RIM", "P/E", "P/B"],
    BusinessType.INSURANCE: ["P/E", "P/B", "EV/EBITDA"],
    BusinessType.COMMODITY: ["EV/EBITDA", "P/E", "P/B"],
    BusinessType.UTILITIES: ["DCF", "P/E", "EV/EBITDA", "P/B"],
    BusinessType.CONGLOMERATE: ["SOTP", "DCF", "P/E", "EV/EBITDA"],
    BusinessType.UNKNOWN: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "EV/Sales", "P/B", "FCF Yield", "SOTP", "REIT NAV", "Bank DDM", "Bank RIM"],
}


class BusinessClassifier:
    """Classifies a company into a BusinessType with explainable rules."""

    KEYWORDS: Dict[BusinessType, List[str]] = {
        BusinessType.REIT: ["reit", "real estate", "property trust", "地产投资信托"],
        BusinessType.BANK: ["bank", "商业银行", "储蓄银行", "investment bank", "证券"],
        BusinessType.INSURANCE: ["insurance", "保险", "寿险", "财险"],
        BusinessType.UTILITIES: ["utility", "utilities", "电力", "水务", "燃气", "能源公用"],
        BusinessType.SEMICONDUCTOR: ["semiconductor", "chip", "半导体", "芯片", "集成电路", "foundry", "fabless", "gpu", "nvidia"],
        BusinessType.SAAS: ["saas", "cloud", "software as a service", "订阅", "企业软件", "platform"],
        BusinessType.CONSUMER_CYCLICAL: ["auto", "automobile", "汽车", "retail", "零售", "travel", "酒店", "航空"],
        BusinessType.COMMODITY: ["oil", "gas", "石油", "矿业", "mining", "metal", "钢铁", "煤炭", "commodity"],
        BusinessType.CONGLOMERATE: ["conglomerate", "集团", "控股", "holding"],
    }

    @staticmethod
    def classify(data: FinancialData) -> CompanyProfile:
        reasons: List[str] = []
        scores: Dict[BusinessType, float] = {bt: 0.0 for bt in BusinessType}

        sector = (data.market.sector or "").lower()
        industry = (data.market.industry or "").lower()
        name = (data.market.company_name or "").lower()
        text = f"{name} {sector} {industry}"

        explicit_keyword_hits: List[BusinessType] = []
        for bt, kws in BusinessClassifier.KEYWORDS.items():
            for kw in kws:
                if kw.lower() in text:
                    scores[bt] += 2.5
                    if bt not in explicit_keyword_hits:
                        explicit_keyword_hits.append(bt)
                    reasons.append(f"Keyword match '{kw}' -> {bt.value} (weight x2.5)")

        if BusinessClassifier._looks_like_bank(data):
            scores[BusinessType.BANK] += 2.0
            reasons.append("Financial ratio profile matches Bank (high leverage, high interest)")

        keyword_blocked_reit = BusinessType.SEMICONDUCTOR in explicit_keyword_hits or BusinessType.SAAS in explicit_keyword_hits
        if not keyword_blocked_reit and BusinessClassifier._looks_like_reit(data):
            scores[BusinessType.REIT] += 2.0
            reasons.append("REIT-like financial profile (high D&A, stable margins)")
        elif keyword_blocked_reit and BusinessClassifier._looks_like_reit(data):
            reasons.append("REIT margin rule skipped: explicit Semiconductor/SaaS keyword takes priority")

        if BusinessClassifier._looks_like_saas(data):
            scores[BusinessType.SAAS] += 1.5
            reasons.append("SaaS-like financial profile (high growth, high gross margin)")

        scores = BusinessClassifier._apply_default_mature_tech(
            data, scores, reasons, sector, industry
        )

        sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
        best_bt, best_score = sorted_scores[0]
        if best_score <= 0:
            best_bt = BusinessType.UNKNOWN
            reasons.append("No strong signals; defaulting to Unknown")

        confidence = min(1.0, 0.3 + best_score * 0.2)
        applicable, not_applicable, na_reasons = BusinessClassifier._model_applicability(
            data, best_bt
        )

        profiles = BusinessClassifier._characterize_profile(data, best_bt)

        return CompanyProfile(
            ticker=data.ticker,
            business_type=best_bt.value,
            classification_confidence=round(confidence, 3),
            classification_reasons=reasons[:6],
            applicable_models=applicable,
            not_applicable_models=not_applicable,
            not_applicable_reasons=na_reasons,
            **profiles,
        )

    @staticmethod
    def _looks_like_bank(data: FinancialData) -> bool:
        ttm = data.ttm
        if ttm is None or ttm.interest_expense is None or ttm.revenue is None:
            return False
        if ttm.revenue <= 0:
            return False
        interest_ratio = ttm.interest_expense / ttm.revenue
        return interest_ratio > 0.20

    @staticmethod
    def _looks_like_reit(data: FinancialData) -> bool:
        ttm = data.ttm
        if ttm is None or ttm.revenue is None or ttm.ebitda is None:
            return False
        margin = ttm.ebitda / ttm.revenue
        if not (0.55 <= margin <= 0.90):
            return False
        mkt = data.market
        if mkt.beta is not None and mkt.beta > 2.0:
            return False
        annuals = data.annual_income
        if len(annuals) >= 4 and annuals[0].revenue and annuals[-1].revenue and annuals[-1].revenue > 0:
            n = len(annuals) - 1
            cagr = (annuals[0].revenue / annuals[-1].revenue) ** (1 / n) - 1
            if cagr > 0.25:
                return False
        return True

    @staticmethod
    def _looks_like_saas(data: FinancialData) -> bool:
        ttm = data.ttm
        if ttm is None or not data.annual_income:
            return False
        if ttm.revenue is None:
            return False
        latest = data.annual_income[0]
        if len(data.annual_income) < 2 or latest.revenue is None:
            return False
        prev = data.annual_income[-1]
        if prev.revenue is None or prev.revenue <= 0:
            return False
        cagr = (latest.revenue / prev.revenue) ** (1 / max(1, len(data.annual_income) - 1)) - 1
        gm = (latest.gross_profit or 0) / latest.revenue if latest.revenue else 0
        return cagr >= 0.15 and gm >= 0.60

    @staticmethod
    def _apply_default_mature_tech(
        data: FinancialData,
        scores: Dict[BusinessType, float],
        reasons: List[str],
        sector: str,
        industry: str,
    ) -> Dict[BusinessType, float]:
        tech_keywords = ["tech", "technology", "software", "hardware", "internet", "科技", "电子", "计算机"]
        if any(k in f"{sector} {industry}" for k in tech_keywords):
            if max(scores.values()) <= 0.5:
                scores[BusinessType.MATURE_TECH] += 0.8
                reasons.append("Tech sector default -> MatureTech")
        return scores

    @staticmethod
    def _model_applicability(
        data: FinancialData, bt: BusinessType
    ) -> Tuple[List[str], List[str], Dict[str, str]]:
        allowed = MODELS_BY_TYPE.get(bt, MODELS_BY_TYPE[BusinessType.UNKNOWN])
        applicable: List[str] = []
        not_applicable: List[str] = []
        na_reasons: Dict[str, str] = {}

        for m in MODELS_BY_TYPE[BusinessType.UNKNOWN]:
            if m in allowed:
                applicable.append(m)
            else:
                not_applicable.append(m)
                na_reasons[m] = f"Not applicable for business type {bt.value}"

        if bt in (BusinessType.BANK, BusinessType.INSURANCE):
            if "DCF" in applicable:
                applicable.remove("DCF")
                not_applicable.append("DCF")
                na_reasons["DCF"] = "FCF unreliable for financial institutions; use DDM/RIM"
            if "EV/EBITDA" in applicable:
                applicable.remove("EV/EBITDA")
                not_applicable.append("EV/EBITDA")
                na_reasons["EV/EBITDA"] = "EV/EBITDA not meaningful for banks/insurance"

        if bt == BusinessType.REIT:
            if "DCF" in applicable:
                applicable.remove("DCF")
                not_applicable.append("DCF")
                na_reasons["DCF"] = "REITs prefer NAV/FFO models over FCF-based DCF"

        return applicable, not_applicable, na_reasons

    @staticmethod
    def _characterize_profile(data: FinancialData, bt: BusinessType) -> dict:
        ttm = data.ttm
        annuals = data.annual_income
        out = {
            "revenue_characteristic": "Unknown",
            "growth_profile": "Unknown",
            "profitability_profile": "Unknown",
            "cash_flow_profile": "Unknown",
            "leverage_profile": "Unknown",
            "capital_intensity": "Unknown",
            "is_financial_institution": False,
            "is_reit": False,
        }

        if bt in (BusinessType.BANK, BusinessType.INSURANCE):
            out["is_financial_institution"] = True
        if bt == BusinessType.REIT:
            out["is_reit"] = True

        if ttm and ttm.revenue is not None:
            if ttm.revenue >= 50e9:
                out["revenue_characteristic"] = "Large Cap"
            elif ttm.revenue >= 5e9:
                out["revenue_characteristic"] = "Mid Cap"
            elif ttm.revenue >= 0.5e9:
                out["revenue_characteristic"] = "Small Cap"
            else:
                out["revenue_characteristic"] = "Micro Cap"

        if len(annuals) >= 2 and annuals[0].revenue and annuals[-1].revenue and annuals[-1].revenue > 0:
            n = len(annuals) - 1
            cagr = (annuals[0].revenue / annuals[-1].revenue) ** (1 / n) - 1
            if cagr >= 0.20:
                out["growth_profile"] = "High Growth"
            elif cagr >= 0.08:
                out["growth_profile"] = "Moderate Growth"
            elif cagr >= 0.0:
                out["growth_profile"] = "Stable"
            else:
                out["growth_profile"] = "Declining"

        if ttm and ttm.revenue and ttm.operating_income is not None:
            om = ttm.operating_income / ttm.revenue
            if om >= 0.25:
                out["profitability_profile"] = "Excellent"
            elif om >= 0.15:
                out["profitability_profile"] = "Good"
            elif om >= 0.05:
                out["profitability_profile"] = "Marginal"
            else:
                out["profitability_profile"] = "Loss Making"

        if ttm and ttm.revenue and ttm.free_cash_flow is not None:
            fcf_margin = ttm.free_cash_flow / ttm.revenue
            if fcf_margin >= 0.10:
                out["cash_flow_profile"] = "Strong FCF"
            elif fcf_margin >= 0.03:
                out["cash_flow_profile"] = "Positive FCF"
            else:
                out["cash_flow_profile"] = "Weak/Negative FCF"

        mkt = data.market
        if mkt.total_debt is not None and mkt.book_value and mkt.book_value > 0:
            de = mkt.total_debt / mkt.book_value
            if de >= 4:
                out["leverage_profile"] = "Very High Leverage"
            elif de >= 2:
                out["leverage_profile"] = "High Leverage"
            elif de >= 0.5:
                out["leverage_profile"] = "Moderate Leverage"
            else:
                out["leverage_profile"] = "Low Leverage"

        if ttm and ttm.revenue and ttm.capex is not None:
            ci = abs(ttm.capex) / ttm.revenue
            if ci >= 0.20:
                out["capital_intensity"] = "Very Capital Intensive"
            elif ci >= 0.10:
                out["capital_intensity"] = "Capital Intensive"
            elif ci >= 0.03:
                out["capital_intensity"] = "Moderate"
            else:
                out["capital_intensity"] = "Asset Light"

        return out


__all__ = ["BusinessClassifier"]
