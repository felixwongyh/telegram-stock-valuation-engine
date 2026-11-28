"""
classification/classifier.py - Business Classification Engine
Classifies companies into 10 business types with explainable rules.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from config import BusinessType, FinancialBusinessModel, get_logger
from data.models import BusinessExposure, CompanyProfile, FinancialData

log = get_logger("classification.classifier")


GENERIC_CORPORATE_MODELS: List[str] = [
    "DCF", "ReverseDCF", "P/E", "EV/EBITDA", "EV/Sales", "P/B", "FCF Yield",
]
ALL_MODELS: List[str] = GENERIC_CORPORATE_MODELS + [
    "Historical Multiples", "SOTP", "REIT NAV", "Replacement NAV",
    "EV/Sales (Unit Econ)", "Bank DDM", "Bank RIM",
]

# A company spending more on capex than its own revenue while burning cash is
# running a capital-intensive build-out, not an asset-light software model.
# Kept aligned with classification/ml_classifier.py so the deterministic rule
# path applies the same valuation-archetype re-route as the ML path.
ASSET_LIGHT_CONFLICT_CAPEX_RATIO: float = 1.0
ASSET_LIGHT_TYPES: frozenset = frozenset({
    BusinessType.SAAS, BusinessType.MATURE_TECH, BusinessType.MEDIA,
})

# ---------------------------------------------------------------------------
# Classification identity vs economics (Phase 1.3)
# ---------------------------------------------------------------------------
# Business Identity  — what the company sells / to whom (external fact from the
#                      provider's sector/industry).
# Business Economics — margin / capex / leverage / FCF shape (ML + structural
#                      features).
# High gross margin + high capex + low leverage is a *shape*, not proof of a
# specialist prototype (e.g. Semiconductor). When the statistical top-1 is
# ambiguous (top-1/top-2 ratio below the floor) AND its label disagrees with the
# identity, we must not silently adopt the top-1 as the valuation prototype.
CLASSIFICATION_STATUS_CONFIDENT: str = "confident"
CLASSIFICATION_STATUS_AMBIGUOUS: str = "ambiguous / review_required"
IDENTITY_CONFLICT_RATIO_FLOOR: float = 2.0
# Technology-family identities. A disagreement that stays inside this family
# (ML says Semiconductor, industry says Software) is a *prototype* conflict →
# collapse to the broad large-cap tech route instead of either narrow label.
TECH_IDENTITY_TYPES: frozenset = frozenset({
    BusinessType.MATURE_TECH, BusinessType.SAAS, BusinessType.SEMICONDUCTOR,
})


def resolve_identity_economics_status(
    top1_label: str,
    top1_p: float,
    top2_p: float,
    sector: Optional[str],
    industry: Optional[str],
) -> Tuple[str, Optional[BusinessType], Optional[str]]:
    """Separate Business Identity from Business Economics (Phase 1.3).

    Returns ``(status, valuation_route_bt, conflict_note)``.

    * ``status``            — ``"confident"`` or ``"ambiguous / review_required"``.
    * ``valuation_route_bt`` — the BusinessType the model-routing layer must use
      when ambiguous (``None`` means "use the caller's own label").
    * ``conflict_note``     — human-readable audit string (``None`` when confident).

    Ambiguity trigger (exactly as specified): the top-1/top-2 probability ratio
    is below :data:`IDENTITY_CONFLICT_RATIO_FLOOR` **and** the identity derived
    from sector/industry disagrees with ``top1_label``. In that case the top-1
    label must not be used as the valuation prototype.

    Routing when ambiguous:
      * a shape-driven *Semiconductor* promotion (top-1 is Semiconductor while
        the identity says it is a different tech company) collapses to the broad
        large-cap tech route (:data:`BusinessType.MATURE_TECH`) — this is the
        exact false-certainty defect ("高毛利 + 高 CapEx + 低杠杆 ⇒ 半导体");
      * every other conflict trusts the identity (the hard external fact about
        what the company sells), so e.g. a mis-shaped bank profile cannot be
        turned into a tech prototype.
    """
    identity_bt = map_sector_industry(sector, industry)
    if identity_bt is None or not top1_label or identity_bt.value == top1_label:
        return CLASSIFICATION_STATUS_CONFIDENT, None, None

    ratio = top1_p / top2_p if top2_p > 1e-9 else 99.0
    if ratio >= IDENTITY_CONFLICT_RATIO_FLOOR:
        return CLASSIFICATION_STATUS_CONFIDENT, None, None

    try:
        top1_bt: Optional[BusinessType] = BusinessType(top1_label)
    except ValueError:
        top1_bt = None

    if top1_bt in TECH_IDENTITY_TYPES and identity_bt in TECH_IDENTITY_TYPES:
        # A prototype conflict that stays *inside* the technology family (e.g.
        # ML says Semiconductor while the industry says Software) collapses to
        # the broad large-cap tech route — never to either narrow prototype.
        route = BusinessType.MATURE_TECH
    else:
        # Every other conflict trusts the identity (the hard external fact about
        # what the company sells), so a mis-shaped bank profile cannot become a
        # tech prototype.
        route = identity_bt

    note = (
        f"分类模糊（top-1/top-2 = {ratio:.2f} < {IDENTITY_CONFLICT_RATIO_FLOOR:.1f}）"
        f"且行业身份与 top-1 冲突：身份='{identity_bt.value}'"
        f"（sector/industry='{sector or 'N/A'}/{industry or 'N/A'}'）"
        f"vs top-1='{top1_label}'（{top1_p:.1%}）。"
        f"不静默采用 top-1 作为估值原型，保守路由 → {route.value}"
    )
    return CLASSIFICATION_STATUS_AMBIGUOUS, route, note

# ---------------------------------------------------------------------------
# Sector/Industry → BusinessType hard mapping
# Covers all 11 Yahoo Finance sectors and ~200 sub-industries.
# Used as a layer-2 hard rule BEFORE the ML classifier.
# Format: (lowercase_substring, BusinessType)  — checked via `in` on "sector industry"
# ---------------------------------------------------------------------------
SECTOR_INDUSTRY_MAP: List[Tuple[str, BusinessType]] = [
    # ---- Healthcare ----
    ("pharmaceuticals", BusinessType.HEALTHCARE),
    ("biotechnology", BusinessType.HEALTHCARE),
    ("medical devices", BusinessType.HEALTHCARE),
    ("medical instruments", BusinessType.HEALTHCARE),
    ("diagnostics & research", BusinessType.HEALTHCARE),
    ("drug manufacturers", BusinessType.HEALTHCARE),
    ("healthcare plans", BusinessType.HEALTHCARE),
    ("medical care facilities", BusinessType.HEALTHCARE),
    ("healthcare information", BusinessType.HEALTHCARE),
    ("medical distribution", BusinessType.HEALTHCARE),
    ("healthcare", BusinessType.HEALTHCARE),

    # ---- Energy ----
    ("oil & gas e&p", BusinessType.ENERGY),
    ("oil & gas integrated", BusinessType.ENERGY),
    ("oil & gas midstream", BusinessType.ENERGY),
    ("oil & gas refining", BusinessType.ENERGY),
    ("oil & gas equipment", BusinessType.ENERGY),
    ("oil & gas services", BusinessType.ENERGY),
    ("uranium", BusinessType.ENERGY),
    ("energy", BusinessType.ENERGY),

    # ---- Materials / Commodity ----
    ("other industrial metals & mining", BusinessType.COMMODITY),
    ("copper", BusinessType.COMMODITY),
    ("gold", BusinessType.COMMODITY),
    ("silver", BusinessType.COMMODITY),
    ("specialty chemicals", BusinessType.COMMODITY),
    ("agricultural inputs", BusinessType.COMMODITY),
    ("building materials", BusinessType.COMMODITY),
    ("paper & paperboard", BusinessType.COMMODITY),
    ("packaging & containers", BusinessType.COMMODITY),
    ("specialty business services", BusinessType.COMMODITY),
    ("steel", BusinessType.COMMODITY),
    ("aluminum", BusinessType.COMMODITY),
    ("chemicals", BusinessType.COMMODITY),
    ("materials", BusinessType.COMMODITY),

    # ---- Industrials ----
    ("aerospace & defense", BusinessType.INDUSTRIAL),
    ("specialty industrial machinery", BusinessType.INDUSTRIAL),
    ("farm & heavy construction machinery", BusinessType.INDUSTRIAL),
    ("industrial distribution", BusinessType.INDUSTRIAL),
    ("rental & leasing services", BusinessType.INDUSTRIAL),
    ("business equipment", BusinessType.INDUSTRIAL),
    ("engineering & construction", BusinessType.INDUSTRIAL),
    ("infrastructure operations", BusinessType.INDUSTRIAL),
    ("marine shipping", BusinessType.INDUSTRIAL),
    ("railroads", BusinessType.INDUSTRIAL),
    ("waste management", BusinessType.INDUSTRIAL),
    ("security & protection services", BusinessType.INDUSTRIAL),
    ("industrials", BusinessType.INDUSTRIAL),

    # ---- Consumer Cyclical ----
    ("auto manufacturers", BusinessType.CONSUMER_CYCLICAL),
    ("auto parts", BusinessType.CONSUMER_CYCLICAL),
    ("auto dealers", BusinessType.CONSUMER_CYCLICAL),
    ("department stores", BusinessType.CONSUMER_CYCLICAL),
    ("apparel retail", BusinessType.CONSUMER_CYCLICAL),
    ("apparel manufacturing", BusinessType.CONSUMER_CYCLICAL),
    ("footwear & accessories", BusinessType.CONSUMER_CYCLICAL),
    ("furnishings, fixtures & appliances", BusinessType.CONSUMER_CYCLICAL),
    ("home improvement retail", BusinessType.CONSUMER_CYCLICAL),
    ("internet retail", BusinessType.CONSUMER_CYCLICAL),
    ("specialty retail", BusinessType.CONSUMER_CYCLICAL),
    ("gambling", BusinessType.CONSUMER_CYCLICAL),
    ("lodging", BusinessType.CONSUMER_CYCLICAL),
    ("restaurants", BusinessType.CONSUMER_CYCLICAL),
    ("residential construction", BusinessType.CONSUMER_CYCLICAL),
    ("travel services", BusinessType.CONSUMER_CYCLICAL),
    ("leisure", BusinessType.CONSUMER_CYCLICAL),
    ("consumer cyclical", BusinessType.CONSUMER_CYCLICAL),

    # ---- Consumer Staples ----
    ("packaged foods", BusinessType.CONSUMER_STAPLES),
    ("confectioners", BusinessType.CONSUMER_STAPLES),
    ("farm products", BusinessType.CONSUMER_STAPLES),
    ("beverages - non-alcoholic", BusinessType.CONSUMER_STAPLES),
    ("beverages - alcoholic", BusinessType.CONSUMER_STAPLES),
    ("beverages - brewers", BusinessType.CONSUMER_STAPLES),
    ("beverages - wineries", BusinessType.CONSUMER_STAPLES),
    ("beverages - distillers", BusinessType.CONSUMER_STAPLES),
    ("tobacco", BusinessType.CONSUMER_STAPLES),
    ("grocery stores", BusinessType.CONSUMER_STAPLES),
    ("discount stores", BusinessType.CONSUMER_STAPLES),
    ("household & personal products", BusinessType.CONSUMER_STAPLES),
    ("personal services", BusinessType.CONSUMER_STAPLES),
    ("consumer defensive", BusinessType.CONSUMER_STAPLES),

    # ---- Financial ----
    ("banks - regional", BusinessType.BANK),
    ("banks - diversified", BusinessType.BANK),
    ("banks - savings", BusinessType.BANK),
    ("mortgage finance", BusinessType.BANK),
    ("capital markets", BusinessType.BANK),
    ("asset management", BusinessType.BANK),
    ("brokerage", BusinessType.BANK),
    ("credit services", BusinessType.FINTECH),
    ("financial data & stock exchanges", BusinessType.BANK),
    ("insurance - diversified", BusinessType.INSURANCE),
    ("insurance - life", BusinessType.INSURANCE),
    ("insurance - property & casualty", BusinessType.INSURANCE),
    ("insurance - reinsurance", BusinessType.INSURANCE),
    ("insurance - specialty", BusinessType.INSURANCE),
    ("insurance brokers", BusinessType.INSURANCE),
    ("financials", BusinessType.BANK),

    # ---- REIT ----
    ("reit - residential", BusinessType.REIT),
    ("reit - retail", BusinessType.REIT),
    ("reit - industrial", BusinessType.REIT),
    ("reit - healthcare facilities", BusinessType.REIT),
    ("reit - office", BusinessType.REIT),
    ("reit - hotel", BusinessType.REIT),
    ("reit - mortgage", BusinessType.REIT),
    ("reit - diversified", BusinessType.REIT),
    ("reit - specialty", BusinessType.REIT),
    ("reits", BusinessType.REIT),
    ("reit", BusinessType.REIT),
    ("real estate - services", BusinessType.REIT),
    ("real estate - development", BusinessType.REIT),
    ("real estate", BusinessType.REIT),

    # ---- Technology ----
    ("software - application", BusinessType.SAAS),
    ("software - infrastructure", BusinessType.SAAS),
    ("software as a service", BusinessType.SAAS),
    ("cloud computing", BusinessType.SAAS),
    ("information technology services", BusinessType.MATURE_TECH),
    # Internet platforms (Alphabet, Meta, …). Yahoo files these under the
    # *sector* "Communication Services", whose only mapping is TELECOM — a
    # coarse misroute. The specific sub-industry must win (it is listed before
    # the Communication Services block, and ``map_sector_industry`` returns the
    # first match).
    ("internet content & information", BusinessType.MATURE_TECH),
    ("communication equipment", BusinessType.MATURE_TECH),
    ("computer hardware", BusinessType.MATURE_TECH),
    ("consumer electronics", BusinessType.MATURE_TECH),
    ("electronic components", BusinessType.MATURE_TECH),
    ("electronic equipment", BusinessType.MATURE_TECH),
    ("scientific & technical instruments", BusinessType.MATURE_TECH),
    ("semiconductors", BusinessType.SEMICONDUCTOR),
    ("semiconductor", BusinessType.SEMICONDUCTOR),
    ("semiconductor equipment", BusinessType.SEMICONDUCTOR),
    ("solar", BusinessType.SEMICONDUCTOR),
    ("technology", BusinessType.MATURE_TECH),

    # ---- Communication Services / Telecom ----
    ("telecom services", BusinessType.TELECOM),
    ("telecommunication", BusinessType.TELECOM),
    ("telecom", BusinessType.TELECOM),
    ("entertainment", BusinessType.MEDIA),
    ("broadcasting", BusinessType.MEDIA),
    ("publishing", BusinessType.MEDIA),
    ("movies & entertainment", BusinessType.MEDIA),
    ("gaming", BusinessType.MEDIA),
    ("interactive media", BusinessType.MEDIA),
    ("advertising agencies", BusinessType.MEDIA),
    ("marketing services", BusinessType.MEDIA),
    ("communication services", BusinessType.TELECOM),

    # ---- Utilities ----
    ("utilities - regulated electric", BusinessType.UTILITIES),
    ("utilities - regulated gas", BusinessType.UTILITIES),
    ("utilities - regulated water", BusinessType.UTILITIES),
    ("utilities - independent power", BusinessType.UTILITIES),
    ("utilities - diversified", BusinessType.UTILITIES),
    ("utilities", BusinessType.UTILITIES),
    ("electric utilities", BusinessType.UTILITIES),
    ("gas utilities", BusinessType.UTILITIES),
    ("water utilities", BusinessType.UTILITIES),

    # ---- Conglomerate ----
    ("conglomerates", BusinessType.CONGLOMERATE),
    ("conglomerate", BusinessType.CONGLOMERATE),
    ("diversified holding", BusinessType.CONGLOMERATE),
    ("holding company", BusinessType.CONGLOMERATE),
]

# Canonical Yahoo Finance sector name → BusinessType (top-level fallback)
SECTOR_ONLY_MAP: Dict[str, BusinessType] = {
    "healthcare": BusinessType.HEALTHCARE,
    "energy": BusinessType.ENERGY,
    "materials": BusinessType.COMMODITY,
    "industrials": BusinessType.INDUSTRIAL,
    "consumer cyclical": BusinessType.CONSUMER_CYCLICAL,
    "consumer discretionary": BusinessType.CONSUMER_CYCLICAL,
    "consumer defensive": BusinessType.CONSUMER_STAPLES,
    "consumer staples": BusinessType.CONSUMER_STAPLES,
    "financial": BusinessType.BANK,
    "financials": BusinessType.BANK,
    "real estate": BusinessType.REIT,
    "technology": BusinessType.MATURE_TECH,
    "communication services": BusinessType.TELECOM,
    "utilities": BusinessType.UTILITIES,
}


def map_sector_industry(sector: Optional[str], industry: Optional[str]) -> Optional[BusinessType]:
    """Map Yahoo Finance sector/industry strings to a BusinessType.

    This is a layer-2 hard rule — checked BEFORE ML classifier.
    Returns None if no match found (falls through to ML/keyword rules).
    """
    concat = f"{sector or ''} {industry or ''}".lower().strip()
    if not concat or concat == "n/a n/a":
        return None

    # 1. Try sub-industry match (highest precision)
    for key, bt in SECTOR_INDUSTRY_MAP:
        if key in concat:
            return bt

    # 2. Try top-level sector only
    sec = (sector or "").lower().strip()
    if sec in SECTOR_ONLY_MAP:
        return SECTOR_ONLY_MAP[sec]

    return None


MODELS_BY_TYPE: Dict[BusinessType, List[str]] = {
    BusinessType.MATURE_TECH: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "EV/Sales", "FCF Yield", "Historical Multiples"],
    BusinessType.SAAS: ["DCF", "ReverseDCF", "EV/Sales", "EV/EBITDA", "FCF Yield", "P/E"],
    BusinessType.SEMICONDUCTOR: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "P/B", "Historical Multiples"],
    BusinessType.CONSUMER_CYCLICAL: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "EV/Sales", "P/B"],
    BusinessType.CONSUMER_STAPLES: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "EV/Sales", "P/B", "FCF Yield"],
    BusinessType.REIT: ["REIT NAV", "P/B", "P/E", "EV/EBITDA"],
    BusinessType.BANK: ["Bank DDM", "Bank RIM", "P/E", "P/B"],
    BusinessType.INSURANCE: ["P/E", "P/B", "EV/EBITDA"],
    # Bank DDM/RIM are added by _model_applicability only when the business model
    # proves a loan book (see classify_financial_business_model).
    BusinessType.FINTECH: ["P/E", "P/B", "EV/Sales"],
    BusinessType.NEOBANK: ["P/E", "P/B"],
    BusinessType.COMMODITY: ["DCF", "ReverseDCF", "EV/EBITDA", "P/E", "P/B"],
    BusinessType.UTILITIES: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "P/B"],
    BusinessType.ENERGY: ["DCF", "ReverseDCF", "EV/EBITDA", "P/E", "P/B", "EV/Sales"],
    BusinessType.INDUSTRIAL: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "P/B", "FCF Yield"],
    BusinessType.HEALTHCARE: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "EV/Sales", "FCF Yield"],
    BusinessType.TELECOM: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "P/B", "FCF Yield"],
    BusinessType.MEDIA: ["DCF", "ReverseDCF", "P/E", "EV/EBITDA", "EV/Sales", "FCF Yield"],
    BusinessType.CONGLOMERATE: ["SOTP", "DCF", "P/E", "EV/EBITDA"],
    # Unknown = generic corporates + SOTP (hybrid companies may need sum-of-parts).
    BusinessType.UNKNOWN: list(GENERIC_CORPORATE_MODELS) + ["SOTP"],
}


class BusinessClassifier:
    """Classifies a company into a BusinessType with explainable rules."""

    KEYWORDS: Dict[BusinessType, List[str]] = {
        # ---- Financial ----
        BusinessType.REIT: [
            "reit", "real estate", "property trust", "地产投资信托",
            "realty", "realty income", "prologis", "simon property",
        ],
        BusinessType.BANK: ["bank", "商业银行", "储蓄银行", "investment bank", "证券", "jpmorgan", "bank of america"],
        BusinessType.INSURANCE: ["insurance", "保险", "寿险", "财险", "allstate", "metlife", "aflac", "travelers", "chubb"],
        BusinessType.FINTECH: [
            "fintech", "financial technology", "digital financial", "payment",
            "digital wallet", "blockchain", "neobank", "nubank", "nu holdings",
            "sofi", "block", "square", "paypal", "stripe", "affirm", "upstart",
            "dave inc", "dave", "cash advance", "personal loan", "banking app",
            "lending platform", "buy now pay later", "bnpl", "credit builder",
            "earned wage access", "wage advance",
        ],
        BusinessType.NEOBANK: [
            "neobank", "digital bank", "challenger bank", "online banking",
            "mobile banking", "nubank", "nu holdings", "revolut", "chime",
            "monzo", "starling", "discover", "sofi bank",
            "dave", "dave inc", "varo", "current", "wise",
        ],
        # ---- Technology ----
        BusinessType.SEMICONDUCTOR: ["semiconductor", "chip", "半导体", "芯片", "集成电路", "foundry", "fabless", "gpu", "nvidia", "broadcom", "qualcomm", "texas instruments", "amd", "intel", "micron", "applied materials"],
        BusinessType.SAAS: ["saas", "cloud", "software as a service", "订阅", "企业软件", "platform", "servicenow", "workday", "snowflake", "palantir"],
        BusinessType.MATURE_TECH: [
            "technology", "software", "hardware", "internet", "科技", "电子", "计算机",
            "apple", "microsoft", "alphabet", "google", "meta", "netflix", "adobe", "oracle", "cisco", "ibm",
        ],
        # --- Consumer ----
        BusinessType.CONSUMER_CYCLICAL: [
            "auto", "automobile", "汽车", "retail", "零售", "travel", "酒店", "航空",
            "airline", "air lines", "cruise", "carnival", "royal caribbean",
            "restaurant", "starbucks", "chipotle", "mcdonald", "darden",
            "home depot", "lowe", "fashion", "apparel", "clothing", "luxury",
            "hotel", "marriott", "hilton", "booking",
            "consumer cyclical", "discretionary",
        ],
        BusinessType.CONSUMER_STAPLES: [
            "food", "beverage", "饮料", "食品", "tobacco", "烟草", "alcohol", "酒",
            "grocery", "grocer", "supermarket", "超市", "便利店",
            "household", "个人护理", "cleaning", "soap", "tissue",
            "coca cola", "pepsi", "procter", "unilever", "colgate", "kraft",
            "general mills", "hormel", "tyson", "sysco", "us foods",
            "altria", "philip morris", "british american tobacco",
            "costco", "walmart", "target", "dollar", "kroger",
            "diageo", "anheuser", "heineken", "monster",
            "mondelez", "nestle", "kraft heinz", "campbell",
            "estee lauder", "l'oreal", "church & dwight",
        ],
        # ---- Real Economy ----
        BusinessType.COMMODITY: [
            "mining", "矿业", "metal", "钢铁", "煤炭", "commodity",
            "steel", "iron", "copper", "gold", "silver", "aluminum",
            "nucor", "freeport", "southern copper", "alcoa", "cleveland cliffs",
            "albemarle", "nutrien", "cf industries", "mosaic", "fmc",
            "chemical", "化工", "dupont", "dow", "lyondellbasell", "ashland",
            "air products", "eastman", "ppg",
            "timber", "paper", "pulp", "packaging",
            "fertilizer", "agriculture", "农业",
            "agricultural", "agtech",
        ],
        BusinessType.ENERGY: [
            "oil", "petroleum", "石油", "gas", "天然气", "energy",
            "energy transfer", "pipeline", "midstream", "refining", "refinery",
            "exploration", "production", "e&p",
            "exxon", "chevron", "shell", "conoco", "occidental",
            "diamondback", "devon", "apa", "civitas",
            "energy transfer", "kinder morgan", "williams", "enterprise products",
            "targa resources", "enbridge", "plains",
            "valero", "marathon petroleum", "phillips 66",
            "halliburton", "schlumberger", "baker hughes",
            "hess", "ecopetrol", "suncor", "canadian natural",
            "talos", "murphy", "callon",
        ],
        BusinessType.UTILITIES: [
            "utility", "utilities", "电力", "水务", "燃气", "能源公用",
            "electric", "power company", "water works", "gas company",
            "nextera", "duke energy", "southern company", "american electric",
            "exelon", "consolidated edison", "edison international",
            "dominion", "sempra", "xcel", "evergy", "idacorp",
            "american water", "middlesex water",
            "atmos energy", "ni_source", "nisource", "centerpoint",
            "eversource", "vistra", "entergy", "ugi",
            "comerica", "pinnacle west", "ppl", "ameren",
            "portland general", "firstenergy", "alliant",
            "cms energy", "pg&e", "companhia energetica",
        ],
        BusinessType.INDUSTRIAL: [
            "industrial", "工业", "construction", "建筑", "machinery", "机械",
            "aerospace", "defense", "国防", "航空工业",
            "logistics", "parcel", "freight", "courier", "trucking", "shipping",
            "package delivery", "快递", "物流", "warehouse", "仓储",
            "manufacturing", "制造", "equipment",
            "boeing", "lockheed martin", "general dynamics", "northrop",
            "raytheon", "rtx", "l3harris", "huntington ingalls",
            "honeywell", "3m", "illinois tool", "eaton", "parker",
            "emerson", "rockwell", "generac", "stanley",
            "ingersoll", "cummins", "paccar", "howmet", "textron",
            "fastenal", "quanta services", "caterpillar",
            "fedex", "ups", "united parcel", "old dominion",
            "rocket lab", "virgin galactic", "teledyne",
            "trane", "steris", "roper", "idex",
        ],
        BusinessType.HEALTHCARE: [
            "pharma", "pharmaceutical", "biotech", "biotechnology", "medical",
            "medical device", "healthcare", "health", "drug", "therapeutic",
            "diagnostic", "life sciences", "life science", "biopharm",
            "制药", "医药", "生物技术", "医疗器械", "医疗", "健康",
            "药品", "药物", "诊断", "基因", "临床",
            "hospital", "诊所", "health system",
            "j&j", "johnson & johnson", "unitedhealth", "pfizer", "merck",
            "novartis", "roche", "abbvie", "eli lilly", "bristol",
            "medtronic", "teladoc", "regeneron", "vertex", "alnylam",
            "quest diagnostics", "cvs health", "cardinal health",
            "ge healthcare", "hca healthcare", "resmed",
            "moderna", "biontech", "gilead", "amgen", "astrazeneca",
            "stryker", "boston scientific", "intuitive surgical",
            "illumina", "guardant", "exact sciences",
        ],
        BusinessType.TELECOM: [
            "telecom", "telecommunication", "通信", "电信",
            "wireless", "cellular", "mobile carrier",
            "at&t", "verizon", "t-mobile", "tmus",
            "charter communications", "comcast", "cmcsa",
            "vodafone", "deutsche telekom", "telefonica",
            "telus", "rogers", "bell canada", "bce",
            "iridium", "ribbon communications",
            "cable", "broadband", "fiber",
            "american tower", "amt", "sba communications", "crown castle",
            "cell tower", "tower",
        ],
        BusinessType.MEDIA: [
            "media", "entertainment", "娱乐", "媒体",
            "streaming", "stream", "内容",
            "publishing", "publish", "出版", "news", "新闻",
            "gaming", "game", "游戏", "esports",
            "broadcast", "broadcasting", "television", "tv",
            "movie", "film", "studio", "cinema", "imax",
            "disney", "warner", "netflix", "fox",
            "news corp", "spotify", "take-two", "electronic arts",
            "activision", "roblox", "unity software",
            "discovery", "paramount", "vimeo",
            "warner bros", "mgm",
        ],
        BusinessType.CONGLOMERATE: [
            "conglomerate", "集团", "控股", "holding",
            "berkshire", "alphabet", "alphabet inc",
        ],
    }

    @staticmethod
    def classify(data: FinancialData) -> CompanyProfile:
        from data.models import ConfidenceAdjustment, BusinessExposure

        reasons: List[str] = []
        scores: Dict[BusinessType, float] = {bt: 0.0 for bt in BusinessType}

        sector = (data.market.sector or "").lower()
        industry = (data.market.industry or "").lower()
        name = (data.market.company_name or "").lower()
        text = f"{name} {sector} {industry}"

        # ---- Layer-2: Sector/Industry hard rule (BEFORE keyword matching) ----
        # This gives a very strong signal when Yahoo/akshare provides sector/industry.
        sector_bt = map_sector_industry(data.market.sector, data.market.industry)
        if sector_bt is not None:
            scores[sector_bt] += 3.0
            reasons.append(
                f"Sector/Industry hard rule: '{data.market.sector}/{data.market.industry}' -> {sector_bt.value} (weight x3.0)"
            )

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

        # ================================================================
        # ISSUE #1 — Confidence transparency audit trail (rule-engine version)
        # ================================================================
        base_confidence = min(1.0, 0.3 + best_score * 0.2)
        ml_raw_conf = round(base_confidence, 4)
        confidence = base_confidence
        adjustments: List[ConfidenceAdjustment] = []

        if best_bt == BusinessType.UNKNOWN:
            old = confidence
            confidence = min(confidence, 0.40)
            delta = round(confidence - old, 4)
            if abs(delta) > 1e-6:
                adjustments.append(ConfidenceAdjustment(
                    step_name="Unknown type cap",
                    delta=delta,
                    reason="Unknown type: confidence capped to 40% (special-industry models not applied)",
                ))
            reasons.append("Unknown type: confidence capped; special-industry models not applied")

        if not (data.market.sector or data.market.industry):
            old = confidence
            confidence = min(confidence, 0.55)
            delta = round(confidence - old, 4)
            if abs(delta) > 1e-6:
                adjustments.append(ConfidenceAdjustment(
                    step_name="Missing sector/industry cap",
                    delta=delta,
                    reason=f"sector/industry missing from data provider; confidence capped to 55% (was {old:.1%})",
                ))
            reasons.append("sector/industry missing; classification confidence capped")

        # ================================================================
        # ISSUE #1b — Asset-light prototype conflict (rule-engine mirror)
        # A capital-intensive compute build-out can be labelled SaaS/MatureTech
        # by the sector rule while spending more on capex than it earns. When
        # capex/revenue >= 1.0 with negative FCF the label is a prototype
        # conflict: cap confidence and record the archetype the peer layer
        # re-routes to (AI/Cloud Infrastructure), so the business headline no
        # longer contradicts the peer table rendered on the same report.
        # ================================================================
        effective_business_type = None
        business_type_conflict_note = None
        if best_bt in ASSET_LIGHT_TYPES:
            _ttm = data.ttm
            _capex_ratio = None
            if _ttm and _ttm.revenue and _ttm.revenue > 0 and _ttm.capex is not None:
                _capex_ratio = abs(_ttm.capex) / _ttm.revenue
            _neg_fcf = bool(
                _ttm and _ttm.free_cash_flow is not None and _ttm.free_cash_flow < 0
            )
            if (_capex_ratio is not None
                    and _capex_ratio >= ASSET_LIGHT_CONFLICT_CAPEX_RATIO
                    and _neg_fcf):
                old = confidence
                confidence = min(confidence, 0.50)
                delta = round(confidence - old, 4)
                if abs(delta) > 1e-6:
                    adjustments.append(ConfidenceAdjustment(
                        step_name="Asset-light prototype conflict",
                        delta=delta,
                        reason=(
                            f"rule label '{best_bt.value}' implies an asset-light model, but "
                            f"capex/revenue = {_capex_ratio:.0%} with negative FCF — "
                            f"capital-intensive compute build-out; confidence capped to 50%"
                        ),
                    ))
                reasons.append(
                    f"Asset-light prototype conflict: label '{best_bt.value}' vs capex/revenue="
                    f"{_capex_ratio:.0%} + negative FCF → confidence capped; peer route → compute infra"
                )
                effective_business_type = "AI/Cloud Infrastructure"
                business_type_conflict_note = (
                    f"规则标签 '{best_bt.value}'（资产轻）与实际重资产算力建设冲突"
                    f"（capex/营收={_capex_ratio:.0%}、FCF 为负）→ 估值原型重路由为 "
                    f"AI/Cloud Infrastructure"
                )

        # ================================================================
        # ISSUE #2 — Hybrid classification + exposures (rule-engine: simple heuristics)
        # ================================================================
        total_positive = sum(max(0.0, s) for s in scores.values())
        if total_positive > 0:
            pseudo_prob_map = {bt.value: round(max(0.0, s) / total_positive, 4) for bt, s in scores.items()}
        else:
            pseudo_prob_map = {bt.value: 1.0 / len(BusinessType) for bt in BusinessType}

        fin_keys = {
            BusinessType.BANK.value, BusinessType.INSURANCE.value, BusinessType.REIT.value,
            BusinessType.FINTECH.value, BusinessType.NEOBANK.value,
        }
        tech_keys = {BusinessType.SAAS.value, BusinessType.MATURE_TECH.value, BusinessType.SEMICONDUCTOR.value}
        fin_p = sum(pseudo_prob_map.get(k, 0.0) for k in fin_keys)
        tech_p = sum(pseudo_prob_map.get(k, 0.0) for k in tech_keys)

        sorted_probs = sorted(pseudo_prob_map.items(), key=lambda kv: -kv[1])
        top1_p = sorted_probs[0][1] if sorted_probs else 0.0
        top2_p = sorted_probs[1][1] if len(sorted_probs) > 1 else 0.0
        ratio = top1_p / top2_p if top2_p > 1e-9 else 99.0

        # ---- Phase 1.3: identity (what it sells) vs economics (shape) ----
        # The rule engine's top-1 can be a structural accident (high margin +
        # high capex + low leverage ⇒ "Semiconductor-like"). When it is
        # statistically ambiguous AND disagrees with the sector/industry
        # identity, do not silently use it as the valuation prototype.
        identity_bt = map_sector_industry(data.market.sector, data.market.industry)
        cls_status, _route_bt, conflict_note = resolve_identity_economics_status(
            best_bt.value, top1_p, top2_p, data.market.sector, data.market.industry
        )
        routing_bt = best_bt
        if cls_status == CLASSIFICATION_STATUS_AMBIGUOUS and _route_bt is not None:
            routing_bt = _route_bt
            reasons.append(
                f"Classification {cls_status}: identity '{identity_bt.value if identity_bt else 'N/A'}' "
                f"vs top-1 '{best_bt.value}' (ratio={ratio:.2f}) → 保守估值路由 {routing_bt.value}"
            )

        # ---- M-32: taxonomy participates in routing (cross-family gate) ----
        # Build the taxonomy profile here — before model applicability — so the
        # structured identity can *direct* routing when it conflicts with the
        # internal identity verdict (``best_bt``) across identity families. The
        # comparison is against the verdict, not ``routing_bt``: the latter is a
        # deliberately conservative interim route and must not be read as an
        # identity claim. A same-family difference keeps the internal route, and
        # the asset-light guardrail always wins. The same profile object is
        # reused by attach_taxonomy_profile at the end.
        from classification.taxonomy import (
            build_taxonomy_profile, node_archetype, taxonomy_routing_override,
        )
        _taxonomy = build_taxonomy_profile(data)
        _routed_business_type = best_bt
        _tax_bt = taxonomy_routing_override(
            best_bt,
            _taxonomy.identity_key,
            _taxonomy.decision_status,
            guard_blocked=BusinessClassifier._asset_light_guard_blocked(
                data, node_archetype(_taxonomy.identity_key)
            ),
        )
        if _tax_bt is not None:
            reasons.append(
                f"Taxonomy routing: 结构化身份 '{_taxonomy.identity_label}' 与内部身份 "
                f"'{best_bt.value}' 跨族冲突（{_taxonomy.decision_status.value}）"
                f" → 估值路由 {_tax_bt.value}"
            )
            routing_bt = _tax_bt
            _routed_business_type = _tax_bt

        is_hybrid = False
        hybrid_label = None
        primary_bt = best_bt.value
        secondary_bt = sorted_probs[1][0] if len(sorted_probs) > 1 and sorted_probs[1][1] >= 0.08 else None

        if best_bt.value in fin_keys and tech_p >= 0.08:
            is_hybrid = True
            hybrid_label = "Hybrid Financial Institution (FinTech)"
            if secondary_bt is None:
                secondary_bt = (
                    BusinessType.MATURE_TECH.value
                    if pseudo_prob_map.get(BusinessType.MATURE_TECH.value, 0) >= pseudo_prob_map.get(BusinessType.SAAS.value, 0)
                    else BusinessType.SAAS.value
                )
        elif best_bt.value in tech_keys and fin_p >= 0.08:
            is_hybrid = True
            hybrid_label = "Technology Company with Financial Exposure"
            if secondary_bt is None:
                secondary_bt = BusinessType.BANK.value
        elif top1_p < 0.55 and ratio < 3.0:
            is_hybrid = True
            hybrid_label = "Mixed / Diversified Business Model"

        if top1_p >= 0.75 and ratio >= 5.0:
            clevel = "High"
        elif top1_p >= 0.55 and ratio >= 2.0:
            clevel = "Medium"
        else:
            clevel = "Low"

        def _agg(keys):
            return sum(pseudo_prob_map.get(k, 0.0) for k in keys)

        fin_agg = _agg([BusinessType.BANK.value, BusinessType.INSURANCE.value, BusinessType.REIT.value,
                        BusinessType.FINTECH.value, BusinessType.NEOBANK.value])
        tech_agg = _agg([BusinessType.SAAS.value, BusinessType.MATURE_TECH.value, BusinessType.SEMICONDUCTOR.value])
        health_agg = _agg([BusinessType.HEALTHCARE.value])
        cyc_agg = _agg([BusinessType.CONSUMER_CYCLICAL.value])
        staples_agg = _agg([BusinessType.CONSUMER_STAPLES.value])
        energy_agg = _agg([BusinessType.ENERGY.value])
        hard_agg = _agg([BusinessType.COMMODITY.value, BusinessType.UTILITIES.value])
        ind_agg = _agg([BusinessType.INDUSTRIAL.value])
        telecom_agg = _agg([BusinessType.TELECOM.value])
        media_agg = _agg([BusinessType.MEDIA.value])
        div_agg = _agg([BusinessType.CONGLOMERATE.value])
        unknown_agg = float(pseudo_prob_map.get(BusinessType.UNKNOWN.value, 0.0))

        accounted = (fin_agg + tech_agg + health_agg + cyc_agg + staples_agg
                     + energy_agg + hard_agg + ind_agg + telecom_agg + media_agg
                     + div_agg + unknown_agg)
        other_agg = max(0.0, 1.0 - accounted)

        exposures: List[BusinessExposure] = [
            BusinessExposure(label="Financial (Bank/Insurance/REIT/FinTech)", weight=round(fin_agg, 4)),
            BusinessExposure(label="Technology (SaaS/Tech/Semi)", weight=round(tech_agg, 4)),
        ]
        if health_agg >= 0.02:
            exposures.append(BusinessExposure(label="Healthcare (Pharma/Biotech/MedDevice)", weight=round(health_agg, 4)))
        if cyc_agg >= 0.02:
            exposures.append(BusinessExposure(label="Consumer Cyclical", weight=round(cyc_agg, 4)))
        if staples_agg >= 0.02:
            exposures.append(BusinessExposure(label="Consumer Staples (Food/Beverage/Tobacco)", weight=round(staples_agg, 4)))
        if energy_agg >= 0.02:
            exposures.append(BusinessExposure(label="Energy (Oil/Gas/Pipeline)", weight=round(energy_agg, 4)))
        if hard_agg >= 0.02:
            exposures.append(BusinessExposure(label="Hard Assets (Commodity/Utilities)", weight=round(hard_agg, 4)))
        if ind_agg >= 0.02:
            exposures.append(BusinessExposure(label="Industrial (Aerospace/Defense/Logistics)", weight=round(ind_agg, 4)))
        if telecom_agg >= 0.02:
            exposures.append(BusinessExposure(label="Telecom (Wireless/Cable/Tower)", weight=round(telecom_agg, 4)))
        if media_agg >= 0.02:
            exposures.append(BusinessExposure(label="Media (Entertainment/Streaming/Gaming)", weight=round(media_agg, 4)))
        if div_agg >= 0.02:
            exposures.append(BusinessExposure(label="Conglomerate/Diversified", weight=round(div_agg, 4)))
        if other_agg >= 0.01:
            exposures.append(BusinessExposure(label="Other Sectors", weight=round(other_agg, 4)))
        if unknown_agg >= 0.005:
            exposures.append(BusinessExposure(
                label="Unclassified (Rule Unknown)",
                weight=round(unknown_agg, 4),
                source="rule_unknown_class",
            ))
        exposures.sort(key=lambda e: -e.weight)

        top2 = [(k, round(v, 4)) for k, v in sorted_probs[:2]]

        applicable, not_applicable, na_reasons = BusinessClassifier._model_applicability(
            data, routing_bt,
            is_hybrid=is_hybrid,
            business_exposures=exposures,
        )
        _fin_model, _fin_reason = BusinessClassifier.classify_financial_business_model(
            data, routing_bt
        )

        profiles = BusinessClassifier._characterize_profile(data, routing_bt)

        # When ambiguous, surface the archetype actually used for valuation so
        # the report headline does not claim the rejected top-1 label.
        if (cls_status == CLASSIFICATION_STATUS_AMBIGUOUS
                and effective_business_type is None and _route_bt is not None):
            effective_business_type = _route_bt.value
            business_type_conflict_note = conflict_note

        profile = CompanyProfile(
            ticker=data.ticker,
            business_type=_routed_business_type.value,
            classification_confidence=round(confidence, 3),
            classification_reasons=reasons[:6],
            applicable_models=applicable,
            not_applicable_models=not_applicable,
            not_applicable_reasons=na_reasons,
            financial_business_model=_fin_model.value,
            financial_business_model_reason=_fin_reason,
            ml_probabilities=pseudo_prob_map,
            top_2_candidates=top2,
            # ---- Issue #1 fields ----
            ml_raw_confidence=ml_raw_conf,
            confidence_adjustments=adjustments,
            # ---- Issue #2 fields ----
            is_hybrid_classification=is_hybrid,
            primary_business_type=primary_bt,
            secondary_business_type=secondary_bt,
            hybrid_classification_label=hybrid_label,
            classification_confidence_level=clevel,
            business_exposures=exposures,
            effective_business_type=effective_business_type,
            business_type_conflict_note=business_type_conflict_note,
            # ---- Phase 1.3: identity vs economics ----
            classification_status=cls_status,
            identity_business_type=(identity_bt.value if identity_bt is not None else None),
            classification_conflict_note=conflict_note,
            **profiles,
        )

        # ---- Business Taxonomy (five dimensions, additive / shadow) ----
        # The rule path has no external ML label, so the taxonomy economics
        # dimension is deliberately left empty here.
        from classification.taxonomy import attach_taxonomy_profile
        attach_taxonomy_profile(data, profile, tp=_taxonomy)

        return profile

    @staticmethod
    def _asset_light_guard_blocked(data: FinancialData, bt: Optional[BusinessType]) -> bool:
        """True when ``bt`` claims an asset-light model but the company is
        visibly running a capital-intensive build-out (capex/revenue ≥ 1.0 with
        negative FCF).

        Mirrors the inline guard further up so the M-32 taxonomy routing gate can
        ask "would this re-route contradict the economics?" without duplicating
        the threshold.
        """
        if bt not in ASSET_LIGHT_TYPES:
            return False
        _ttm = data.ttm
        if not _ttm or not _ttm.revenue or _ttm.revenue <= 0 or _ttm.capex is None:
            return False
        if abs(_ttm.capex) / _ttm.revenue < ASSET_LIGHT_CONFLICT_CAPEX_RATIO:
            return False
        return bool(_ttm.free_cash_flow is not None and _ttm.free_cash_flow < 0)

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
    def _is_balance_sheet_financial(data: FinancialData, bt: BusinessType) -> bool:
        """True when the business *is* a balance sheet (lending/underwriting).

        ``FINTECH`` is a catch-all for Yahoo's "Credit Services" industry, which
        contains two economically opposite businesses:

        * **payment networks** (V, MA) — fee-based toll booths. Revenue is
          volume-linked fees, interest expense is negligible, and FCF is a
          meaningful cash-flow concept.
        * **lenders / card issuers** (COF, AXP) — revenue is interest income and
          the balance sheet funds a loan book, so CFO is dominated by working
          capital swings in receivables and FCF is not an economic cash flow.

        Both share the same industry string, so the split must be structural:
        how much of pre-interest operating profit is consumed by funding cost.
        A lender's interest expense is a large fraction of operating income;
        a payment network's is a rounding error. Observed populations:
        V 0.03, MA 0.04, PYPL 0.07 vs AXP 0.37, COF 0.86, SOFI 0.69.
        A 0.20 threshold sits far from both clusters.
        """
        if bt in (BusinessType.BANK, BusinessType.INSURANCE, BusinessType.NEOBANK):
            return True
        if bt != BusinessType.FINTECH:
            return False
        ttm = data.ttm
        if ttm is None or not ttm.revenue or ttm.revenue <= 0:
            # No revenue base to judge on — keep the conservative default.
            return True
        if ttm.interest_expense is None:
            return True
        interest = abs(float(ttm.interest_expense))
        oi = ttm.operating_income
        if oi is not None and float(oi) > 0:
            return interest / float(oi) >= 0.20
        # Operating income unavailable or negative (loss-making lender): fall
        # back to interest expense as a share of revenue, where a funding-driven
        # balance sheet still shows a materially larger ratio than a fee network.
        return interest / float(ttm.revenue) >= 0.10

    @staticmethod
    def classify_financial_business_model(
        data: FinancialData, bt: BusinessType
    ) -> Tuple[FinancialBusinessModel, str]:
        """Resolve *what the financial business does*, with a traceable reason.

        Routing must not key on the sector label: V and JPM share Yahoo's
        "Financial Services" sector and even the "Credit Services" industry, yet
        one is a fee network and the other funds a loan book. The discriminator
        is structural — how much of pre-interest operating profit is consumed by
        funding cost (see ``_is_balance_sheet_financial`` for the observed
        populations: V 0.03, MA 0.04, PYPL 0.07 vs AXP 0.37, COF 0.86, SOFI 0.69).

        Returns ``(model, reason)``; the reason is stored on the profile so the
        routing decision is auditable.
        """
        if bt == BusinessType.BANK:
            return (
                FinancialBusinessModel.BANK,
                "BusinessType=Bank → deposit-funded lending/underwriting",
            )
        if bt == BusinessType.INSURANCE:
            return (
                FinancialBusinessModel.OTHER_FINANCIAL,
                "BusinessType=Insurance → underwriting, not a loan book",
            )
        if bt == BusinessType.NEOBANK:
            # A neobank is a bank charter with a digital front end.
            return (
                FinancialBusinessModel.BANK,
                "BusinessType=Neobank → chartered digital bank, loan book funded by deposits",
            )
        if bt != BusinessType.FINTECH:
            return (
                FinancialBusinessModel.NOT_FINANCIAL,
                f"BusinessType={bt.value} is not a financial business model",
            )

        # FINTECH is the ambiguous bucket: payments vs lenders.
        ttm = data.ttm
        if ttm is None or not ttm.revenue or ttm.revenue <= 0:
            return (
                FinancialBusinessModel.OTHER_FINANCIAL,
                "FinTech with no revenue base → cannot prove a loan book; "
                "not routed to Bank RIM",
            )
        if ttm.interest_expense is None:
            return (
                FinancialBusinessModel.OTHER_FINANCIAL,
                "FinTech with no interest expense reported → no evidence of "
                "funding cost; not routed to Bank RIM",
            )

        interest = abs(float(ttm.interest_expense))
        oi = ttm.operating_income
        if oi is not None and float(oi) > 0:
            ratio = interest / float(oi)
            basis = f"interest expense / operating income = {ratio:.3f}"
        else:
            ratio = interest / float(ttm.revenue)
            basis = f"interest expense / revenue = {ratio:.3f}"

        if ratio >= 0.20:
            return (
                FinancialBusinessModel.FINTECH_LENDER,
                f"FinTech with funding-driven balance sheet ({basis} >= 0.20) "
                "→ lender, needs its own applicability judgement",
            )
        return (
            FinancialBusinessModel.PAYMENT_NETWORK,
            f"FinTech with fee-based economics ({basis} < 0.20) → payment network",
        )

    @staticmethod
    def _model_applicability(
        data: FinancialData, bt: BusinessType,
        is_hybrid: bool = False,
        business_exposures: Optional[List[BusinessExposure]] = None,
    ) -> Tuple[List[str], List[str], Dict[str, str]]:
        allowed = MODELS_BY_TYPE.get(bt, GENERIC_CORPORATE_MODELS)
        fin_model, _fin_reason = BusinessClassifier.classify_financial_business_model(data, bt)
        # Bank DDM/RIM are granted by *business model*, never by the FINTECH
        # label: a payment network shares Yahoo's "Credit Services" industry with
        # card issuers, and routing it to a bank residual-income model would put
        # a fee business through a loan-book valuation.
        if fin_model in (FinancialBusinessModel.BANK, FinancialBusinessModel.FINTECH_LENDER):
            allowed = list(allowed) + ["Bank DDM", "Bank RIM"]
        else:
            allowed = [m for m in allowed if m not in ("Bank DDM", "Bank RIM")]
        # Payment networks are fee businesses, so the DCF family is meaningful for
        # them even though the FINTECH default list omits it.
        if fin_model == FinancialBusinessModel.PAYMENT_NETWORK:
            allowed = list(allowed) + ["DCF", "ReverseDCF"]
        applicable: List[str] = []
        not_applicable: List[str] = []
        na_reasons: Dict[str, str] = {}

        for m in ALL_MODELS:
            if m in allowed:
                applicable.append(m)
            else:
                not_applicable.append(m)
                na_reasons[m] = f"Not applicable for business type {bt.value}"

        # ---- SOTP: add for hybrid/diversified companies ----
        if is_hybrid and "SOTP" not in applicable:
            # Check if secondary exposure is significant
            has_significant_secondary = False
            if business_exposures and len(business_exposures) >= 2:
                second_weight = float(getattr(business_exposures[1], "weight", 0.0))
                if second_weight >= 0.10:
                    has_significant_secondary = True
            if has_significant_secondary:
                applicable.append("SOTP")
                if "SOTP" in not_applicable:
                    not_applicable.remove("SOTP")
                na_reasons.pop("SOTP", None)
                na_reasons["__sotp_added__"] = (
                    "SOTP added: hybrid classification with significant secondary exposure"
                )

        if BusinessClassifier._is_balance_sheet_financial(data, bt):
            if "DCF" in applicable:
                applicable.remove("DCF")
                not_applicable.append("DCF")
                na_reasons["DCF"] = "FCF unreliable for financial institutions; use DDM/RIM"
            if "ReverseDCF" in applicable:
                applicable.remove("ReverseDCF")
                not_applicable.append("ReverseDCF")
                na_reasons["ReverseDCF"] = "Reverse DCF unreliable for financial institutions; use DDM/RIM"
            if "EV/EBITDA" in applicable:
                applicable.remove("EV/EBITDA")
                not_applicable.append("EV/EBITDA")
                na_reasons["EV/EBITDA"] = "EV/EBITDA not meaningful for banks/insurance/FinTech"
            # EV/Sales is EV-based too: for lending-driven financials the EV
            # embeds the debt that funds the loan book, so an EV/Sales multiple
            # is not comparable across capital structures. Excluding DCF/EV-EBITDA
            # while keeping EV/Sales left a contradiction in the same report
            # (UPST round1: "EV -> N/M, financials" printed next to a $42/shr
            # EV/Sales anchor that was the single largest driver of the Very Weak
            # agreement). Keep the EV-family exclusions together.
            if "EV/Sales" in applicable:
                applicable.remove("EV/Sales")
                not_applicable.append("EV/Sales")
                na_reasons["EV/Sales"] = "EV/Sales not meaningful for financial institutions (EV embeds funding debt)"
            if "FCF Yield" in applicable:
                applicable.remove("FCF Yield")
                not_applicable.append("FCF Yield")
                na_reasons["FCF Yield"] = "FCF Yield not meaningful for financial institutions"

        if bt == BusinessType.REIT:
            if "DCF" in applicable:
                applicable.remove("DCF")
                not_applicable.append("DCF")
                na_reasons["DCF"] = "REITs prefer NAV/FFO models over FCF-based DCF"

        # ---- Replacement NAV: coverage anchor for capital-intensive build-outs ----
        # When a capital-intensive company is in a pre-profit / high-growth build-out
        # (negative FCF, loss-making), its FCF-based models collapse (DCF → terminal
        # -value rescue, ReverseDCF → infeasible). Rather than leaving 2 survivors and
        # down-weighting, add an explicit asset-based (replacement-cost) anchor so
        # coverage stays honest at 3-4 models.
        if BusinessClassifier._is_replacement_nav_candidate(data, bt):
            if "Replacement NAV" not in applicable:
                applicable.append("Replacement NAV")
                if "Replacement NAV" in not_applicable:
                    not_applicable.remove("Replacement NAV")
                na_reasons.pop("Replacement NAV", None)
                na_reasons["__replacement_nav_added__"] = (
                    "Replacement NAV added: capital-intensive build-out with negative FCF / "
                    "loss-making — asset-based anchor for coverage"
                )

        # ---- Unit-economics EV/Sales: revenue-anchored coverage for build-outs ----
        # The asset-based Replacement NAV gives the *floor* (what the fleet costs to
        # rebuild); the unit-economics EV/Sales adds an independent *earnings-power*
        # anchor (installed capacity × mature ARPU×utilisation). Two economically
        # distinct survivors instead of leaning on a down-weighted DCF.
        if BusinessClassifier._is_unit_economics_candidate(data, bt):
            if "EV/Sales (Unit Econ)" not in applicable:
                applicable.append("EV/Sales (Unit Econ)")
                if "EV/Sales (Unit Econ)" in not_applicable:
                    not_applicable.remove("EV/Sales (Unit Econ)")
                na_reasons.pop("EV/Sales (Unit Econ)", None)
                na_reasons["__unit_econ_added__"] = (
                    "EV/Sales (Unit Econ) added: capital-intensive build-out — "
                    "installed capacity × mature unit economics (ARPU×utilisation) anchor"
                )

        return applicable, not_applicable, na_reasons

    @staticmethod
    def _is_unit_economics_candidate(data: FinancialData, bt: BusinessType) -> bool:
        """Capital-intensive pre-profit build-out → unit-economics EV/Sales anchor."""
        if bt in (BusinessType.BANK, BusinessType.INSURANCE, BusinessType.FINTECH,
                  BusinessType.NEOBANK, BusinessType.REIT):
            return False
        ttm = data.ttm
        if ttm is None or not ttm.revenue or ttm.revenue <= 0 or ttm.capex is None:
            return False
        capex_ratio = abs(float(ttm.capex)) / float(ttm.revenue)
        if capex_ratio < 0.50:
            return False
        neg_fcf = ttm.free_cash_flow is not None and ttm.free_cash_flow < 0
        neg_ni = ttm.net_income is not None and ttm.net_income < 0
        acc_capex = 0.0
        acc_da = 0.0
        for s in (data.annual_income or []):
            if s.capex is not None:
                acc_capex += abs(float(s.capex))
            if s.depreciation_amortization is not None:
                acc_da += abs(float(s.depreciation_amortization))
        if acc_capex - acc_da <= 0:
            return False
        return bool(neg_fcf or neg_ni)

    @staticmethod
    def _is_replacement_nav_candidate(data: FinancialData, bt: BusinessType) -> bool:
        """Capital-intensive build-out (pre-profit / high-growth) → asset-based NAV."""
        if bt in (BusinessType.BANK, BusinessType.INSURANCE, BusinessType.FINTECH,
                  BusinessType.NEOBANK, BusinessType.REIT):
            return False
        ttm = data.ttm
        if ttm is None or not ttm.revenue or ttm.revenue <= 0:
            return False
        if ttm.capex is None:
            return False
        capex_ratio = abs(float(ttm.capex)) / float(ttm.revenue)
        if capex_ratio < 0.30:
            return False
        neg_fcf = ttm.free_cash_flow is not None and ttm.free_cash_flow < 0
        neg_ni = ttm.net_income is not None and ttm.net_income < 0
        # Reconstructable net asset base: cumulative capex must exceed cumulative D&A.
        acc_capex = 0.0
        acc_da = 0.0
        for s in (data.annual_income or []):
            if s.capex is not None:
                acc_capex += abs(float(s.capex))
            if s.depreciation_amortization is not None:
                acc_da += abs(float(s.depreciation_amortization))
        if acc_capex - acc_da <= 0:
            return False
        return bool((neg_fcf or neg_ni) and capex_ratio >= 0.30)

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

        if bt in (BusinessType.BANK, BusinessType.INSURANCE, BusinessType.NEOBANK):
            out["is_financial_institution"] = True
        elif bt == BusinessType.FINTECH:
            # Only balance-sheet fintechs (lenders/card issuers) are financial
            # institutions; payment networks (V, MA) are fee businesses.
            out["is_financial_institution"] = (
                BusinessClassifier._is_balance_sheet_financial(data, bt)
            )
        if bt == BusinessType.REIT:
            out["is_reit"] = True

        is_fin = out["is_financial_institution"]

        if ttm and ttm.revenue is not None:
            if ttm.revenue >= 50e9:
                out["revenue_characteristic"] = "Large Cap"
            elif ttm.revenue >= 5e9:
                out["revenue_characteristic"] = "Mid Cap"
            elif ttm.revenue >= 0.5e9:
                out["revenue_characteristic"] = "Small Cap"
            else:
                out["revenue_characteristic"] = "Micro Cap"

        # Use the longest usable span rather than requiring both endpoints to be
        # present: one gap in the oldest year (AAPL's 2022 revenue is None)
        # otherwise reports "Unknown" for a company with a measurable CAGR.
        _revs = [
            s.revenue for s in annuals
            if s.revenue is not None and s.revenue > 0
        ]
        if len(_revs) >= 2:
            newest, oldest = _revs[0], _revs[-1]
            n = len(_revs) - 1
            cagr = (newest / oldest) ** (1 / n) - 1
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
            if om >= 0.20:
                out["profitability_profile"] = "Excellent"
            elif om >= 0.10:
                out["profitability_profile"] = "Good"
            elif om >= 0.05:
                out["profitability_profile"] = "Fair"
            elif om >= 0:
                out["profitability_profile"] = "Marginal"
            else:
                out["profitability_profile"] = "Loss Making"
        elif is_fin and ttm and ttm.revenue and ttm.net_income is not None:
            # Financial institutions: operating income often missing from Yahoo;
            # fall back to net margin as a profitability proxy.
            nm = ttm.net_income / ttm.revenue
            if nm >= 0.25:
                out["profitability_profile"] = "Excellent"
            elif nm >= 0.15:
                out["profitability_profile"] = "Good"
            elif nm >= 0.08:
                out["profitability_profile"] = "Fair"
            elif nm >= 0:
                out["profitability_profile"] = "Marginal"
            else:
                out["profitability_profile"] = "Loss Making"

        # ---- Cash-flow profile: FCF for financials is NOT meaningful ----
        if is_fin:
            # Bank/Insurance: use net income stability + interest coverage proxy instead.
            if ttm and ttm.net_income is not None:
                if ttm.net_income > 0:
                    out["cash_flow_profile"] = "Profitable (see note: FCF N/M for banks)"
                else:
                    out["cash_flow_profile"] = "Loss-Making (see note: FCF N/M for banks)"
            else:
                out["cash_flow_profile"] = "N/A (FCF not meaningful for financial institutions)"
        elif out["is_reit"]:
            # REITs prefer FFO/AFFO over GAAP FCF. Mark but still report GAAP margin.
            if ttm and ttm.revenue and ttm.free_cash_flow is not None:
                fcf_margin = ttm.free_cash_flow / ttm.revenue
                if fcf_margin >= 0.10:
                    out["cash_flow_profile"] = "Strong GAAP FCF (prefer FFO/AFFO for REITs)"
                elif fcf_margin >= 0.03:
                    out["cash_flow_profile"] = "Positive GAAP FCF (prefer FFO/AFFO for REITs)"
                else:
                    out["cash_flow_profile"] = "Weak/Neg GAAP FCF (prefer FFO/AFFO for REITs)"
        else:
            if ttm and ttm.revenue and ttm.free_cash_flow is not None:
                fcf_margin = ttm.free_cash_flow / ttm.revenue
                if fcf_margin >= 0.10:
                    out["cash_flow_profile"] = "Strong FCF"
                elif fcf_margin >= 0.03:
                    out["cash_flow_profile"] = "Positive FCF"
                elif fcf_margin >= 0:
                    # Positive but thin — grocery/retail run low single-digit FCF
                    # margins structurally. Lumping this with negative FCF
                    # asserted a fact that is false (KR: +$2.38B, 1.6%).
                    out["cash_flow_profile"] = "Thin Positive FCF"
                else:
                    out["cash_flow_profile"] = "Negative FCF"

        mkt = data.market
        if mkt.total_debt is not None and mkt.book_value and mkt.book_value > 0:
            de = mkt.total_debt / mkt.book_value
            if is_fin:
                # For financial institutions, capital structure IS the business;
                # label it and explain.
                if de >= 8:
                    out["leverage_profile"] = "Very High Leverage (typical for banks; D/E reflects deposits/bonds)"
                elif de >= 4:
                    out["leverage_profile"] = "High Leverage (typical for banks; D/E reflects deposits/bonds)"
                elif de >= 1.5:
                    out["leverage_profile"] = "Moderate Leverage for financial institution"
                else:
                    out["leverage_profile"] = "Well Capitalized (Low D/E for financial institution)"
            else:
                if de >= 4:
                    out["leverage_profile"] = "Very High Leverage"
                elif de >= 2:
                    out["leverage_profile"] = "High Leverage"
                elif de >= 0.5:
                    out["leverage_profile"] = "Moderate Leverage"
                else:
                    out["leverage_profile"] = "Low Leverage"

        # ---- Capital intensity: skip for financials because Capex definition differs ----
        if is_fin:
            # Banks do not have a conventional "capex" ratio; mark as N/A.
            out["capital_intensity"] = "N/A (not meaningful for financial institutions)"
        elif ttm and ttm.revenue and ttm.capex is not None:
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
