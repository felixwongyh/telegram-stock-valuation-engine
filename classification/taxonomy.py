"""
classification/taxonomy.py — Internal Standard Business Taxonomy (5 dimensions)

Motivation
----------
The engine previously derived a single flat ``BusinessType`` label from a mix of
a Yahoo sector/industry substring list, ML probabilities and keyword rules, and
reconciled the disagreements with ad-hoc ``if`` blocks spread across two
classifiers (`classifier.py` and `ml_classifier.py`). This module introduces one
explicit internal taxonomy plus one reconciliation contract so that five
*distinct* dimensions are handled separately and auditably:

    ① Business Identity       — what the company actually does
                                (Software Platform, Semiconductor Manufacturer,
                                 Cloud Infrastructure, E-commerce, Bank, ...)
    ② Business Model          — how it makes money
                                (SaaS Subscription, Licensing, Advertising,
                                 Transaction Fee, Hardware Sales, Cloud Usage, ...)
    ③ Revenue Composition     — where revenue comes from (segment % + as-of date)
    ④ Economic Profile        — margin / capex / FCF / leverage *shape*
    ⑤ External Classification — raw third-party labels, stored verbatim

Golden rule
-----------
Financial characteristics inform the Economic Profile, but they must NEVER on
their own set the Business Identity. High gross margin + high capex + low
leverage is a *shape*, not proof of a Semiconductor manufacturer — the same shape
describes a Software/Cloud operator running large AI data centres.
:func:`economic_identity_ceiling` enforces this at the API level: economics may
only *refine* an identity **within its own family**, never cross families.

This module is intentionally additive: it produces an auditable five-dimension
profile and a reconciliation verdict, but it does not (yet) replace the existing
routing in the classifiers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from config import BusinessType, get_logger

log = get_logger("classification.taxonomy")


# ===========================================================================
# Dimension ① — Business Identity taxonomy (tree of canonical nodes)
# ===========================================================================
# Each node has a canonical key, a human label, a parent and the valuation
# archetype (BusinessType) it collapses to. Intermediate nodes carry the
# archetype of the broad family so "collapse to common ancestor" always resolves
# to a meaningful model route.
#
# key, label, parent (None for family roots), archetype
_NODE_DEFS: List[Tuple[str, str, Optional[str], BusinessType]] = [
    # ---- Technology -------------------------------------------------------
    ("tech", "Technology", None, BusinessType.MATURE_TECH),
    ("tech.software", "Software", "tech", BusinessType.SAAS),
    ("tech.software.platform", "Software Platform (SaaS)", "tech.software", BusinessType.SAAS),
    ("tech.software.application", "Application Software", "tech.software", BusinessType.SAAS),
    ("tech.software.infra", "Infrastructure Software", "tech.software", BusinessType.SAAS),
    ("tech.cloud_infra", "Cloud / AI Infrastructure Operator", "tech", BusinessType.MATURE_TECH),
    ("tech.semiconductor", "Semiconductor Manufacturer", "tech", BusinessType.SEMICONDUCTOR),
    ("tech.semi_equipment", "Semiconductor Equipment", "tech", BusinessType.SEMICONDUCTOR),
    ("tech.hardware", "Computer Hardware / Consumer Electronics", "tech", BusinessType.MATURE_TECH),
    ("tech.components", "Electronic Components", "tech", BusinessType.MATURE_TECH),
    ("tech.it_services", "IT Services", "tech", BusinessType.MATURE_TECH),
    ("tech.internet", "Internet Content / Platform", "tech", BusinessType.MATURE_TECH),
    ("tech.generic", "Technology (unspecified)", "tech", BusinessType.MATURE_TECH),

    # ---- Financial --------------------------------------------------------
    ("fin", "Financial Services", None, BusinessType.BANK),
    ("fin.bank", "Bank", "fin", BusinessType.BANK),
    ("fin.capital_markets", "Capital Markets / Brokerage", "fin", BusinessType.BANK),
    ("fin.asset_management", "Asset Management", "fin", BusinessType.BANK),
    ("fin.exchange", "Financial Data & Exchanges", "fin", BusinessType.BANK),
    ("fin.insurance", "Insurance", "fin", BusinessType.INSURANCE),
    ("fin.fintech", "FinTech / Payments", "fin", BusinessType.FINTECH),
    ("fin.neobank", "Neobank / Digital Bank", "fin", BusinessType.NEOBANK),
    ("fin.generic", "Financial Services (unspecified)", "fin", BusinessType.BANK),

    # ---- Real Estate ------------------------------------------------------
    ("re", "Real Estate", None, BusinessType.REIT),
    ("re.reit", "REIT", "re", BusinessType.REIT),
    ("re.development", "Real Estate Development", "re", BusinessType.REIT),
    ("re.services", "Real Estate Services", "re", BusinessType.REIT),
    ("re.generic", "Real Estate (unspecified)", "re", BusinessType.REIT),

    # ---- Consumer ---------------------------------------------------------
    ("cons", "Consumer", None, BusinessType.CONSUMER_CYCLICAL),
    ("cons.cyclical", "Consumer Cyclical", "cons", BusinessType.CONSUMER_CYCLICAL),
    ("cons.retail", "Retail (Discretionary)", "cons.cyclical", BusinessType.CONSUMER_CYCLICAL),
    ("cons.ecommerce", "E-commerce / Internet Retail", "cons.cyclical", BusinessType.CONSUMER_CYCLICAL),
    ("cons.auto", "Autos & Parts", "cons.cyclical", BusinessType.CONSUMER_CYCLICAL),
    ("cons.apparel", "Apparel & Accessories", "cons.cyclical", BusinessType.CONSUMER_CYCLICAL),
    ("cons.restaurants", "Restaurants", "cons.cyclical", BusinessType.CONSUMER_CYCLICAL),
    ("cons.travel", "Travel / Lodging / Leisure Airlines", "cons.cyclical", BusinessType.CONSUMER_CYCLICAL),
    ("cons.homebuilding", "Homebuilding & Construction", "cons.cyclical", BusinessType.CONSUMER_CYCLICAL),
    ("cons.leisure", "Leisure & Gambling", "cons.cyclical", BusinessType.CONSUMER_CYCLICAL),
    ("cons.generic", "Consumer Cyclical (unspecified)", "cons", BusinessType.CONSUMER_CYCLICAL),
    ("cs", "Consumer Staples", None, BusinessType.CONSUMER_STAPLES),
    ("cs.food", "Food & Packaged Goods", "cs", BusinessType.CONSUMER_STAPLES),
    ("cs.beverage", "Beverages", "cs", BusinessType.CONSUMER_STAPLES),
    ("cs.tobacco", "Tobacco", "cs", BusinessType.CONSUMER_STAPLES),
    ("cs.household", "Household & Personal Products", "cs", BusinessType.CONSUMER_STAPLES),
    ("cs.retail", "Grocery / Discount Retail", "cs", BusinessType.CONSUMER_STAPLES),
    ("cs.generic", "Consumer Staples (unspecified)", "cs", BusinessType.CONSUMER_STAPLES),

    # ---- Healthcare -------------------------------------------------------
    ("hc", "Healthcare", None, BusinessType.HEALTHCARE),
    ("hc.pharma", "Pharmaceuticals", "hc", BusinessType.HEALTHCARE),
    ("hc.biotech", "Biotechnology", "hc", BusinessType.HEALTHCARE),
    ("hc.medtech", "Medical Devices / Instruments", "hc", BusinessType.HEALTHCARE),
    ("hc.diagnostics", "Diagnostics & Research", "hc", BusinessType.HEALTHCARE),
    ("hc.providers", "Healthcare Providers & Plans", "hc", BusinessType.HEALTHCARE),
    ("hc.distribution", "Medical Distribution", "hc", BusinessType.HEALTHCARE),
    ("hc.generic", "Healthcare (unspecified)", "hc", BusinessType.HEALTHCARE),

    # ---- Industrial -------------------------------------------------------
    ("ind", "Industrials", None, BusinessType.INDUSTRIAL),
    ("ind.aero_defense", "Aerospace & Defense", "ind", BusinessType.INDUSTRIAL),
    ("ind.machinery", "Machinery & Equipment", "ind", BusinessType.INDUSTRIAL),
    ("ind.construction", "Engineering & Construction", "ind", BusinessType.INDUSTRIAL),
    ("ind.logistics", "Freight / Rail / Marine Logistics", "ind", BusinessType.INDUSTRIAL),
    ("ind.distribution", "Industrial Distribution & Leasing", "ind", BusinessType.INDUSTRIAL),
    ("ind.waste", "Waste Management", "ind", BusinessType.INDUSTRIAL),
    ("ind.generic", "Industrials (unspecified)", "ind", BusinessType.INDUSTRIAL),

    # ---- Energy -----------------------------------------------------------
    ("en", "Energy", None, BusinessType.ENERGY),
    ("en.oil_gas", "Oil & Gas", "en", BusinessType.ENERGY),
    ("en.oil_gas.eup", "Oil & Gas E&P", "en.oil_gas", BusinessType.ENERGY),
    ("en.oil_gas.integrated", "Oil & Gas Integrated", "en.oil_gas", BusinessType.ENERGY),
    ("en.oil_gas.midstream", "Oil & Gas Midstream", "en.oil_gas", BusinessType.ENERGY),
    ("en.oil_gas.refining", "Oil & Gas Refining", "en.oil_gas", BusinessType.ENERGY),
    ("en.oil_gas.equipment", "Oil & Gas Equipment & Services", "en.oil_gas", BusinessType.ENERGY),
    ("en.uranium", "Uranium", "en", BusinessType.ENERGY),
    ("en.generic", "Energy (unspecified)", "en", BusinessType.ENERGY),

    # ---- Materials --------------------------------------------------------
    ("mat", "Materials", None, BusinessType.COMMODITY),
    ("mat.metals_mining", "Metals & Mining", "mat", BusinessType.COMMODITY),
    ("mat.chemicals", "Chemicals", "mat", BusinessType.COMMODITY),
    ("mat.construction", "Building Materials", "mat", BusinessType.COMMODITY),
    ("mat.packaging", "Paper & Packaging", "mat", BusinessType.COMMODITY),
    ("mat.agri", "Agricultural Inputs", "mat", BusinessType.COMMODITY),
    ("mat.generic", "Materials (unspecified)", "mat", BusinessType.COMMODITY),

    # ---- Utilities --------------------------------------------------------
    ("util", "Utilities", None, BusinessType.UTILITIES),
    ("util.electric", "Regulated Electric Utility", "util", BusinessType.UTILITIES),
    ("util.gas", "Regulated Gas Utility", "util", BusinessType.UTILITIES),
    ("util.water", "Regulated Water Utility", "util", BusinessType.UTILITIES),
    ("util.ipp", "Independent Power Producer", "util", BusinessType.UTILITIES),
    ("util.diversified", "Diversified Utility", "util", BusinessType.UTILITIES),
    ("util.generic", "Utilities (unspecified)", "util", BusinessType.UTILITIES),

    # ---- Telecom ----------------------------------------------------------
    ("tel", "Telecom", None, BusinessType.TELECOM),
    ("tel.carrier", "Wireless / Wireline Carrier", "tel", BusinessType.TELECOM),
    ("tel.cable", "Cable & Broadband", "tel", BusinessType.TELECOM),
    ("tel.tower", "Tower / Infrastructure", "tel", BusinessType.TELECOM),
    ("tel.generic", "Telecom (unspecified)", "tel", BusinessType.TELECOM),

    # ---- Media ------------------------------------------------------------
    ("med", "Media", None, BusinessType.MEDIA),
    ("med.entertainment", "Entertainment & Film", "med", BusinessType.MEDIA),
    ("med.streaming", "Streaming", "med", BusinessType.MEDIA),
    ("med.gaming", "Gaming & Interactive", "med", BusinessType.MEDIA),
    ("med.publishing", "Publishing & Broadcasting", "med", BusinessType.MEDIA),
    ("med.advertising", "Advertising & Marketing", "med", BusinessType.MEDIA),
    ("med.generic", "Media (unspecified)", "med", BusinessType.MEDIA),

    # ---- Conglomerate -----------------------------------------------------
    ("congl", "Conglomerate", None, BusinessType.CONGLOMERATE),
    ("congl.diversified", "Diversified Holding", "congl", BusinessType.CONGLOMERATE),

    # ---- Unknown ----------------------------------------------------------
    ("unknown", "Unknown", None, BusinessType.UNKNOWN),
]


@dataclass(frozen=True)
class IdentityNode:
    """One canonical node in the Business Identity taxonomy."""

    key: str
    label: str
    parent: Optional[str]
    archetype: BusinessType
    depth: int = 0

    @property
    def family(self) -> str:
        """Level-1 family key (the root of this node's branch)."""
        return self.key.split(".", 1)[0]


_PARENT_OF: Dict[str, Optional[str]] = {k: p for k, _l, p, _b in _NODE_DEFS}


def _structural_depth(key: str) -> int:
    """Distance from the family root along the parent chain.

    Deliberately *not* ``key.count(".")``: grouping nodes such as
    ``cons.cyclical`` parent their children at the grouping key's own dotted
    depth, so the key's dot count does not describe specificity. The parent
    chain does.
    """
    depth = 0
    cur = _PARENT_OF.get(key)
    while cur is not None:
        depth += 1
        cur = _PARENT_OF.get(cur)
    return depth


IDENTITY_NODES: Dict[str, IdentityNode] = {
    _k: IdentityNode(_k, _label, _parent, _bt, _structural_depth(_k))
    for _k, _label, _parent, _bt in _NODE_DEFS
}

# Family roots must exist; a node's parent must exist too.
for _node in IDENTITY_NODES.values():
    if _node.parent is not None and _node.parent not in IDENTITY_NODES:
        raise RuntimeError(f"taxonomy node '{_node.key}' has unknown parent '{_node.parent}'")


def node(key: Optional[str]) -> Optional[IdentityNode]:
    """Look up a canonical node by key; ``None`` for unknown/empty keys."""
    if not key:
        return None
    return IDENTITY_NODES.get(key)


def node_archetype(key: Optional[str]) -> BusinessType:
    """Valuation archetype for a node key (``UNKNOWN`` when unresolved)."""
    n = node(key)
    return n.archetype if n is not None else BusinessType.UNKNOWN


def _ancestors(key: str) -> List[str]:
    """Ordered ancestor chain, self first then up to the family root."""
    out: List[str] = []
    cur: Optional[str] = key
    while cur is not None:
        out.append(cur)
        n = IDENTITY_NODES.get(cur)
        cur = n.parent if n is not None else None
    return out


def common_ancestor(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Deepest shared ancestor key of two nodes (``None`` if disjoint families)."""
    if not a or not b:
        return None
    b_chain = set(_ancestors(b))
    for k in _ancestors(a):
        if k in b_chain:
            return k
    return None


def economic_identity_ceiling(identity_key: Optional[str], economics_key: Optional[str]) -> Optional[str]:
    """Enforce the golden rule: economics may only *refine* an identity within
    its own family — it can never decide the Business Identity.

    Returns the deepest node we are willing to accept given the two signals:

      * no identity           → the economics node stands alone (weak, flagged)
      * different families    → the identity is kept outright
      * same family, same node→ that node
      * same family, siblings → the shared ancestor, never the economics node

    The last case is exactly the headline defect: an Infrastructure-Software
    company whose financial *shape* looks semiconductor-like must collapse to
    the shared ``tech`` ancestor, never be promoted to Semiconductor.
    """
    if not identity_key:
        return economics_key
    if not economics_key or economics_key == identity_key:
        return identity_key
    if IDENTITY_NODES[identity_key].family != IDENTITY_NODES[economics_key].family:
        return identity_key
    return common_ancestor(identity_key, economics_key) or identity_key


# ===========================================================================
# Dimension ② — Business Model (how the company makes money)
# ===========================================================================
class BusinessModel(str, Enum):
    SAAS_SUBSCRIPTION = "SaaS Subscription"
    RECURRING_SUBSCRIPTION = "Recurring Subscription"
    LICENSING = "Licensing"
    CLOUD_USAGE = "Cloud Usage"
    ADVERTISING = "Advertising"
    TRANSACTION_FEE = "Transaction Fee"
    PAYMENTS = "Payments / Take Rate"
    INTEREST_SPREAD = "Interest Spread"
    PREMIUM = "Insurance Premium"
    HARDWARE_SALES = "Hardware Sales"
    PRODUCT_SALES = "Product Sales"
    SERVICE_FEE = "Service Fee"
    RENTAL = "Rental / Lease"
    ASSET_BACKED = "Asset-Backed / NAV"
    COMMODITY_SPOT = "Commodity Spot"
    UNKNOWN = "Unknown"


_MODEL_KEYWORDS: List[Tuple[str, BusinessModel]] = [
    ("subscription", BusinessModel.SAAS_SUBSCRIPTION),
    ("saas", BusinessModel.SAAS_SUBSCRIPTION),
    ("software as a service", BusinessModel.SAAS_SUBSCRIPTION),
    ("recurring", BusinessModel.RECURRING_SUBSCRIPTION),
    ("license", BusinessModel.LICENSING),
    ("licens", BusinessModel.LICENSING),
    ("cloud", BusinessModel.CLOUD_USAGE),
    ("usage-based", BusinessModel.CLOUD_USAGE),
    ("advertis", BusinessModel.ADVERTISING),
    ("ad revenue", BusinessModel.ADVERTISING),
    ("transaction fee", BusinessModel.TRANSACTION_FEE),
    ("take rate", BusinessModel.PAYMENTS),
    ("payment", BusinessModel.PAYMENTS),
    ("interchange", BusinessModel.PAYMENTS),
    ("interest income", BusinessModel.INTEREST_SPREAD),
    ("net interest", BusinessModel.INTEREST_SPREAD),
    ("premium", BusinessModel.PREMIUM),
    ("underwriting", BusinessModel.PREMIUM),
    ("semiconductor", BusinessModel.HARDWARE_SALES),
    ("hardware", BusinessModel.HARDWARE_SALES),
    ("device", BusinessModel.HARDWARE_SALES),
    ("rent", BusinessModel.RENTAL),
    ("lease", BusinessModel.RENTAL),
    ("commodit", BusinessModel.COMMODITY_SPOT),
    ("commodity", BusinessModel.COMMODITY_SPOT),
]


def infer_business_models(text: Optional[str]) -> List[BusinessModel]:
    """Infer business models from free text (business description / industry).

    Best-effort and explainable: returns every model whose keyword is present,
    ordered by first appearance. Empty list when nothing matches.
    """
    if not text:
        return []
    low = text.lower()
    found: List[BusinessModel] = []
    for kw, bm in _MODEL_KEYWORDS:
        if kw in low and bm not in found:
            found.append(bm)
    return found


# ===========================================================================
# Dimension ③ — Revenue Composition (segment mix)
# ===========================================================================
@dataclass(frozen=True)
class SegmentRevenue:
    """One reported business segment: share of revenue plus its source date."""

    label: str
    pct: Optional[float]              # 0..1 share of total revenue
    as_of: Optional[str] = None       # ISO date of the reported figure
    source: str = "unknown"


@dataclass
class RevenueComposition:
    """Where the revenue comes from.

    ``available`` is explicit: when no segment source exists we must say so
    rather than silently pretending the mix is unknown-but-fine. Providers that
    can supply segments populate ``segments``; everything else leaves it empty.
    """

    available: bool = False
    segments: List[SegmentRevenue] = field(default_factory=list)
    as_of: Optional[str] = None
    source: str = "unavailable"
    note: Optional[str] = None

    @property
    def is_concentrated(self) -> Optional[bool]:
        """True when a single segment exceeds 60% of revenue (``None`` if N/A)."""
        if not self.available or not self.segments:
            return None
        top = max((s.pct or 0.0) for s in self.segments)
        return top >= 0.60

    @classmethod
    def unavailable(cls, reason: str = "no segment-level revenue source") -> "RevenueComposition":
        return cls(available=False, segments=[], source="unavailable", note=reason)


# ===========================================================================
# Dimension ④ — Economic Profile (the *shape*, never the identity)
# ===========================================================================
@dataclass(frozen=True)
class EconomicProfile:
    """Financial shape. Deliberately kept separate from Business Identity."""

    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    fcf_margin: Optional[float] = None
    capex_to_revenue: Optional[float] = None
    de_ratio: Optional[float] = None
    revenue_cagr: Optional[float] = None
    recurring_revenue_pct: Optional[float] = None  # only when ③ is available
    is_loss_making: bool = False
    is_capex_heavy: bool = False
    is_asset_light: bool = False
    notes: List[str] = field(default_factory=list)


# ===========================================================================
# Dimension ⑤ — External Classification (raw labels, never overwritten)
# ===========================================================================
@dataclass
class ExternalClassification:
    """Third-party labels kept *verbatim* for audit.

    These are recorded, not authoritative: the internal taxonomy decides, and the
    raw provider strings are preserved so a disagreement can be explained later.
    """

    yahoo_sector: Optional[str] = None
    yahoo_industry: Optional[str] = None
    gics_sector: Optional[str] = None       # not supplied by current providers
    gics_industry: Optional[str] = None
    naics: Optional[str] = None
    ml_label: Optional[str] = None
    ml_confidence: Optional[float] = None
    source_note: Optional[str] = None

    @property
    def has_structured_identity(self) -> bool:
        return bool(self.yahoo_sector or self.yahoo_industry
                    or self.gics_sector or self.gics_industry or self.naics)


# ===========================================================================
# Explicit mapping tables → canonical nodes
# ===========================================================================
# Yahoo industry substring → node key. Matching is *longest-key-wins* rather than
# first-match-wins, which removes the order-dependence of the old flat list.
YAHOO_INDUSTRY_TO_NODE: List[Tuple[str, str]] = [
    # ---- Healthcare ----
    ("pharmaceuticals", "hc.pharma"),
    ("drug manufacturers", "hc.pharma"),
    ("biotechnology", "hc.biotech"),
    ("medical devices", "hc.medtech"),
    ("medical instruments", "hc.medtech"),
    ("diagnostics & research", "hc.diagnostics"),
    ("healthcare plans", "hc.providers"),
    ("medical care facilities", "hc.providers"),
    ("healthcare information", "hc.providers"),
    ("medical distribution", "hc.distribution"),
    ("healthcare", "hc.generic"),
    # ---- Energy ----
    ("oil & gas e&p", "en.oil_gas.eup"),
    ("oil & gas integrated", "en.oil_gas.integrated"),
    ("oil & gas midstream", "en.oil_gas.midstream"),
    ("oil & gas refining", "en.oil_gas.refining"),
    ("oil & gas equipment", "en.oil_gas.equipment"),
    ("oil & gas services", "en.oil_gas.equipment"),
    ("uranium", "en.uranium"),
    ("energy", "en.generic"),
    # ---- Materials ----
    ("other industrial metals & mining", "mat.metals_mining"),
    ("copper", "mat.metals_mining"),
    ("gold", "mat.metals_mining"),
    ("silver", "mat.metals_mining"),
    ("steel", "mat.metals_mining"),
    ("aluminum", "mat.metals_mining"),
    ("specialty chemicals", "mat.chemicals"),
    ("chemicals", "mat.chemicals"),
    ("agricultural inputs", "mat.agri"),
    ("building materials", "mat.construction"),
    ("paper & paperboard", "mat.packaging"),
    ("packaging & containers", "mat.packaging"),
    ("specialty business services", "mat.generic"),
    ("materials", "mat.generic"),
    # ---- Industrials ----
    ("aerospace & defense", "ind.aero_defense"),
    ("specialty industrial machinery", "ind.machinery"),
    ("farm & heavy construction machinery", "ind.machinery"),
    ("industrial distribution", "ind.distribution"),
    ("rental & leasing services", "ind.distribution"),
    ("business equipment", "ind.machinery"),
    ("engineering & construction", "ind.construction"),
    ("infrastructure operations", "ind.construction"),
    ("marine shipping", "ind.logistics"),
    ("railroads", "ind.logistics"),
    ("integrated freight", "ind.logistics"),
    ("freight & logistics", "ind.logistics"),
    ("logistics", "ind.logistics"),
    ("air freight", "ind.logistics"),
    ("waste management", "ind.waste"),
    ("security & protection services", "ind.generic"),
    ("industrials", "ind.generic"),
    # ---- Consumer Cyclical ----
    ("auto manufacturers", "cons.auto"),
    ("auto parts", "cons.auto"),
    ("auto dealers", "cons.auto"),
    ("department stores", "cons.retail"),
    ("apparel retail", "cons.retail"),
    ("apparel manufacturing", "cons.apparel"),
    ("footwear & accessories", "cons.apparel"),
    ("furnishings, fixtures & appliances", "cons.retail"),
    ("home improvement retail", "cons.retail"),
    ("internet retail", "cons.ecommerce"),
    ("specialty retail", "cons.retail"),
    ("gambling", "cons.leisure"),
    ("lodging", "cons.travel"),
    ("restaurants", "cons.restaurants"),
    ("residential construction", "cons.homebuilding"),
    ("travel services", "cons.travel"),
    ("leisure", "cons.leisure"),
    ("consumer cyclical", "cons.generic"),
    # ---- Consumer Staples ----
    ("packaged foods", "cs.food"),
    ("confectioners", "cs.food"),
    ("farm products", "cs.food"),
    ("beverages - non-alcoholic", "cs.beverage"),
    ("beverages - alcoholic", "cs.beverage"),
    ("beverages - brewers", "cs.beverage"),
    ("beverages - wineries", "cs.beverage"),
    ("beverages - distillers", "cs.beverage"),
    ("tobacco", "cs.tobacco"),
    ("grocery stores", "cs.retail"),
    ("discount stores", "cs.retail"),
    ("household & personal products", "cs.household"),
    ("personal services", "cs.generic"),
    ("consumer defensive", "cs.generic"),
    # ---- Financial ----
    ("banks - regional", "fin.bank"),
    ("banks - diversified", "fin.bank"),
    ("banks - savings", "fin.bank"),
    ("mortgage finance", "fin.bank"),
    ("capital markets", "fin.capital_markets"),
    ("brokerage", "fin.capital_markets"),
    ("asset management", "fin.asset_management"),
    ("credit services", "fin.fintech"),
    ("financial data & stock exchanges", "fin.exchange"),
    ("insurance - diversified", "fin.insurance"),
    ("insurance - life", "fin.insurance"),
    ("insurance - property & casualty", "fin.insurance"),
    ("insurance - reinsurance", "fin.insurance"),
    ("insurance - specialty", "fin.insurance"),
    ("insurance brokers", "fin.insurance"),
    ("financials", "fin.generic"),
    # ---- Real Estate ----
    ("reit - residential", "re.reit"),
    ("reit - retail", "re.reit"),
    ("reit - industrial", "re.reit"),
    ("reit - healthcare facilities", "re.reit"),
    ("reit - office", "re.reit"),
    ("reit - hotel", "re.reit"),
    ("reit - mortgage", "re.reit"),
    ("reit - diversified", "re.reit"),
    ("reit - specialty", "re.reit"),
    ("reits", "re.reit"),
    ("reit", "re.reit"),
    ("real estate - services", "re.services"),
    ("real estate - development", "re.development"),
    ("real estate", "re.reit"),
    # ---- Technology ----
    ("software - application", "tech.software.application"),
    ("software - infrastructure", "tech.software.infra"),
    ("software as a service", "tech.software.platform"),
    ("cloud computing", "tech.cloud_infra"),
    ("information technology services", "tech.it_services"),
    ("communication equipment", "tech.components"),
    ("computer hardware", "tech.hardware"),
    ("consumer electronics", "tech.hardware"),
    ("electronic components", "tech.components"),
    ("electronic equipment", "tech.components"),
    ("scientific & technical instruments", "tech.components"),
    ("semiconductors", "tech.semiconductor"),
    ("semiconductor equipment", "tech.semi_equipment"),
    ("semiconductor", "tech.semiconductor"),
    ("solar", "tech.semiconductor"),
    ("internet content & information", "tech.internet"),
    ("technology", "tech.generic"),
    # ---- Communication Services / Telecom / Media ----
    ("telecom services", "tel.carrier"),
    ("telecommunication", "tel.carrier"),
    ("telecom", "tel.carrier"),
    ("entertainment", "med.entertainment"),
    ("broadcasting", "med.publishing"),
    ("publishing", "med.publishing"),
    ("movies & entertainment", "med.entertainment"),
    ("gaming", "med.gaming"),
    ("interactive media", "med.generic"),
    ("advertising agencies", "med.advertising"),
    ("marketing services", "med.advertising"),
    ("communication services", "tel.generic"),
    # ---- Utilities ----
    ("utilities - regulated electric", "util.electric"),
    ("utilities - regulated gas", "util.gas"),
    ("utilities - regulated water", "util.water"),
    ("utilities - independent power", "util.ipp"),
    ("utilities - diversified", "util.diversified"),
    ("utilities", "util.generic"),
    ("electric utilities", "util.electric"),
    ("gas utilities", "util.gas"),
    ("water utilities", "util.water"),
    # ---- Conglomerate ----
    ("conglomerates", "congl.diversified"),
    ("conglomerate", "congl.diversified"),
    ("diversified holding", "congl.diversified"),
    ("holding company", "congl.diversified"),
]

# Yahoo top-level sector → node key (fallback when no sub-industry matches).
YAHOO_SECTOR_TO_NODE: Dict[str, str] = {
    "healthcare": "hc.generic",
    "energy": "en.generic",
    "materials": "mat.generic",
    "industrials": "ind.generic",
    "consumer cyclical": "cons.generic",
    "consumer discretionary": "cons.generic",
    "consumer defensive": "cs.generic",
    "consumer staples": "cs.generic",
    "financial": "fin.generic",
    "financial services": "fin.generic",
    "financials": "fin.generic",
    "real estate": "re.generic",
    "technology": "tech.generic",
    "communication services": "tel.generic",
    "utilities": "util.generic",
}

# Internal archetype label (BusinessType value / ML top-1) → the node it implies.
# This is the ⑤-ML signal expressed in taxonomy coordinates.
ML_LABEL_TO_NODE: Dict[str, str] = {
    BusinessType.MATURE_TECH.value: "tech.generic",
    BusinessType.SAAS.value: "tech.software.platform",
    BusinessType.SEMICONDUCTOR.value: "tech.semiconductor",
    BusinessType.CONSUMER_CYCLICAL.value: "cons.generic",
    BusinessType.CONSUMER_STAPLES.value: "cs.generic",
    BusinessType.REIT.value: "re.reit",
    BusinessType.BANK.value: "fin.bank",
    BusinessType.INSURANCE.value: "fin.insurance",
    BusinessType.FINTECH.value: "fin.fintech",
    BusinessType.NEOBANK.value: "fin.neobank",
    BusinessType.COMMODITY.value: "mat.generic",
    BusinessType.UTILITIES.value: "util.generic",
    BusinessType.ENERGY.value: "en.generic",
    BusinessType.INDUSTRIAL.value: "ind.generic",
    BusinessType.HEALTHCARE.value: "hc.generic",
    BusinessType.TELECOM.value: "tel.generic",
    BusinessType.MEDIA.value: "med.generic",
    BusinessType.CONGLOMERATE.value: "congl.diversified",
    BusinessType.UNKNOWN.value: "unknown",
}

# Description keywords that *refine* an identity within its own family. Used by
# :func:`node_from_description`; deliberately conservative (only high-precision
# phrases that discriminate sibling nodes, e.g. a data-centre operator).
_DESCRIPTION_NODE_HINTS: List[Tuple[str, str]] = [
    ("data center", "tech.cloud_infra"),
    ("data centre", "tech.cloud_infra"),
    ("data-center", "tech.cloud_infra"),
    ("data centre operator", "tech.cloud_infra"),
    ("hyperscale", "tech.cloud_infra"),
    ("gpu cloud", "tech.cloud_infra"),
    ("ai infrastructure", "tech.cloud_infra"),
    ("cloud infrastructure", "tech.cloud_infra"),
    ("neocloud", "tech.cloud_infra"),
    ("semiconductor", "tech.semiconductor"),
    ("chipmaker", "tech.semiconductor"),
    ("foundry", "tech.semiconductor"),
    ("fabless", "tech.semiconductor"),
    ("software as a service", "tech.software.platform"),
    ("subscription software", "tech.software.platform"),
    ("enterprise software", "tech.software.application"),
    ("internet retail", "cons.ecommerce"),
    ("e-commerce", "cons.ecommerce"),
    ("online marketplace", "cons.ecommerce"),
    ("commercial bank", "fin.bank"),
    ("retail bank", "fin.bank"),
    ("neobank", "fin.neobank"),
    ("digital bank", "fin.neobank"),
    ("payment network", "fin.fintech"),
    ("real estate investment trust", "re.reit"),
    ("regulated utility", "util.electric"),
]


def _norm_industry(text: Optional[str]) -> str:
    """Lower-case and unify dashes for industry matching.

    Providers differ in dash style: Yahoo emits en/em dashes with no surrounding
    spaces ("Utilities—Independent Power Producers") while the mapping tables
    use " - " (space-hyphen-space). Normalizing *both* the table key and the
    query text — and dropping spaces around hyphens — lets an exact identity
    match survive that formatting difference. Without this, a merchant power
    producer's identity key silently degraded to the generic sector node.
    """
    t = (text or "").lower().strip()
    t = t.replace("\u2014", "-").replace("\u2013", "-")
    t = t.replace(" - ", "-").replace("- ", "-").replace(" -", "-")
    return t


def _longest_industry_match(text: Optional[str]) -> Optional[str]:
    """Longest mapping key present in ``text`` (``None`` when nothing matches)."""
    if not text:
        return None
    low = _norm_industry(text)
    best_key: Optional[str] = None
    best_len = -1
    for sub, node_key in YAHOO_INDUSTRY_TO_NODE:
        norm_sub = _norm_industry(sub)
        if norm_sub in low and len(norm_sub) > best_len:
            best_key, best_len = node_key, len(norm_sub)
    return best_key


def node_from_yahoo(sector: Optional[str], industry: Optional[str]) -> Optional[str]:
    """Map Yahoo sector/industry strings to a canonical node.

    Two-phase on purpose: the *industry* is the specific signal and is matched
    first, then the sector string, and only then the broad sector→family table.
    Concatenating the two would let a long broad sector phrase (e.g.
    "Consumer Cyclical", 17 chars) outrank a shorter specific industry
    ("Internet Retail", 15 chars) under longest-key-wins — the wrong node.
    """
    industry_key = _longest_industry_match(industry)
    if industry_key is not None:
        return industry_key

    sector_key = _longest_industry_match(sector)
    if sector_key is not None:
        return sector_key

    sec = (sector or "").lower().strip()
    if not sec or sec in {"n/a", "na", "none", "unknown"}:
        return None
    return YAHOO_SECTOR_TO_NODE.get(sec)


def node_from_ml_label(label: Optional[str]) -> Optional[str]:
    """Map an internal archetype label (ML top-1 / BusinessType) to a node."""
    if not label:
        return None
    return ML_LABEL_TO_NODE.get(label)


def node_from_description(text: Optional[str]) -> Optional[str]:
    """Refine an identity node from free-text business description keywords."""
    if not text:
        return None
    low = text.lower()
    for kw, node_key in _DESCRIPTION_NODE_HINTS:
        if kw in low:
            return node_key
    return None


# ===========================================================================
# Reconciliation contract
# ===========================================================================
class ConflictKind(str, Enum):
    """How the identity signals withstood each other."""

    CONSISTENT = "consistent"            # structured identity == economics node
    REFINEMENT = "refinement"            # same family → collapse to common ancestor
    IDENTITY_WINS = "identity_wins"      # cross-family → identity kept, economics rejected
    ECONOMICS_ONLY = "economics_only"    # no structured identity → economics used
    INSUFFICIENT = "insufficient"        # nothing usable → UNKNOWN


class DecisionStatus(str, Enum):
    """Unified classification *decision* contract (what to do with the verdict).

    This is deliberately separate from :class:`ConflictKind` (which describes
    *how* the signals related). ``ConflictKind`` answers "did they agree?"; the
    decision status answers "is the classification safe to act on?":

      CONFIRMED         — reliable evidence agrees → auto-pass
      PROBABLE          — strong evidence supports → usable, flag retained
      AMBIGUOUS         — important evidence conflicts → widen analysis / audit
      INSUFFICIENT_DATA — no reliable evidence → do NOT force a classification
    """

    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT_DATA = "insufficient_data"


# Minimum ML confidence for an economics-only verdict to deserve a PROBABLE (as
# opposed to AMBIGUOUS) decision status. Below it we refuse to promote a label
# derived from financial shape alone.
_ECONOMICS_ONLY_MIN_CONF = 0.55

# Human-readable labels for the decision contract (rendering consumers may map
# from the enum value instead; this is only for the audit trace).
_DECISION_LABELS: Dict[str, str] = {
    DecisionStatus.CONFIRMED.value: "已确认",
    DecisionStatus.PROBABLE.value: "较可能",
    DecisionStatus.AMBIGUOUS.value: "存在歧义",
    DecisionStatus.INSUFFICIENT_DATA.value: "数据不足",
}


@dataclass(frozen=True)
class TaxonomyReconciliation:
    """Auditable verdict of the identity reconciliation."""

    canonical_key: Optional[str]
    valuation_archetype: BusinessType
    conflict_kind: ConflictKind
    identity_source: str                  # yahoo_industry | description | ml_label | none
    confidence_delta: float = 0.0
    notes: List[str] = field(default_factory=list)


def reconcile_identity(
    *,
    external: ExternalClassification,
    description_key: Optional[str] = None,
    economics_key: Optional[str] = None,
) -> TaxonomyReconciliation:
    """Reconcile the identity signals into one canonical node + archetype.

    Signal precedence (structured external fact > free-text refinement >
    internal economics):
      1. ``external`` (Yahoo sector/industry) establishes the *identity*.
      2. ``description_key`` may refine it **within the same family**.
      3. ``economics_key`` (ML archetype) may refine it **within the same
         family** only — via :func:`economic_identity_ceiling`. It never crosses
         families, which is the golden rule.
    """
    notes: List[str] = []
    industry_key = node_from_yahoo(external.yahoo_sector, external.yahoo_industry)
    economics_key = economics_key or node_from_ml_label(external.ml_label)

    # ---- Resolve the identity from structured + free-text signals ----------
    identity_key = industry_key
    identity_source = "yahoo_industry" if industry_key else "none"

    if industry_key is None and description_key is not None:
        identity_key = description_key
        identity_source = "description"
        notes.append(
            f"无结构化行业标签，采用业务描述推断身份 → {IDENTITY_NODES[description_key].label}"
        )
    elif industry_key is not None and description_key is not None:
        if description_key == industry_key:
            notes.append("业务描述与行业标签一致，强化身份判定")
        elif IDENTITY_NODES[description_key].family == IDENTITY_NODES[industry_key].family:
            if IDENTITY_NODES[description_key].depth > IDENTITY_NODES[industry_key].depth:
                notes.append(
                    f"业务描述在族内细化身份：{IDENTITY_NODES[industry_key].label} → "
                    f"{IDENTITY_NODES[description_key].label}"
                )
                identity_key = description_key
                identity_source = "yahoo_industry+description"
        else:
            notes.append(
                f"业务描述（{IDENTITY_NODES[description_key].label}）与行业标签"
                f"（{IDENTITY_NODES[industry_key].label}）跨族冲突 → 以结构化行业标签为准"
            )

    # ---- No identity at all: fall back to economics, explicitly flagged -----
    if identity_key is None:
        if economics_key is not None:
            notes.append(
                f"无外部身份信号；以经济特征（ML={external.ml_label}）作为唯一线索，"
                f"身份确定性较低"
            )
            return TaxonomyReconciliation(
                canonical_key=economics_key,
                valuation_archetype=node_archetype(economics_key),
                conflict_kind=ConflictKind.ECONOMICS_ONLY,
                identity_source="ml_label",
                confidence_delta=-0.10,
                notes=notes,
            )
        return TaxonomyReconciliation(
            canonical_key=None,
            valuation_archetype=BusinessType.UNKNOWN,
            conflict_kind=ConflictKind.INSUFFICIENT,
            identity_source="none",
            confidence_delta=-0.15,
            notes=notes + ["身份信号缺失，无法定位业务身份"],
        )

    # ---- Economics may only refine WITHIN the identity family --------------
    if economics_key is None:
        return TaxonomyReconciliation(
            canonical_key=identity_key,
            valuation_archetype=node_archetype(identity_key),
            conflict_kind=ConflictKind.CONSISTENT,
            identity_source=identity_source,
            notes=notes,
        )

    if economics_key == identity_key:
        return TaxonomyReconciliation(
            canonical_key=identity_key,
            valuation_archetype=node_archetype(identity_key),
            conflict_kind=ConflictKind.CONSISTENT,
            identity_source=identity_source,
            notes=notes,
        )

    id_family = IDENTITY_NODES[identity_key].family
    ec_family = IDENTITY_NODES[economics_key].family

    if id_family != ec_family:
        # Golden rule: cross-family claims from economics are rejected.
        notes.append(
            f"经济特征暗示 '{IDENTITY_NODES[economics_key].label}'，与外部身份 "
            f"'{IDENTITY_NODES[identity_key].label}' 跨族冲突 → 经济特征不得单独决定"
            f" Business Identity，保留外部身份"
        )
        return TaxonomyReconciliation(
            canonical_key=identity_key,
            valuation_archetype=node_archetype(identity_key),
            conflict_kind=ConflictKind.IDENTITY_WINS,
            identity_source=identity_source,
            confidence_delta=-0.10,
            notes=notes,
        )

    # Same family but different node → collapse to the common ancestor (this
    # generalises the previous, tech-only "collapse to MatureTech" behaviour to
    # every family).
    #
    # Exception: an *unspecified* economics node (``*.generic``) is the absence
    # of a refinement, not a competing one. Collapsing on it would throw away a
    # precise structured industry (AAPL: Yahoo "Consumer Electronics" →
    # tech.hardware, ML "MatureTech" → tech.generic, ancestor "tech"), which is
    # the opposite of the golden rule that economics may only refine identity.
    if economics_key.endswith(".generic"):
        notes.append(
            f"经济特征 '{IDENTITY_NODES[economics_key].label}' 为未细分标签，不构成对"
            f"身份 '{IDENTITY_NODES[identity_key].label}' 的细化或冲突 → 保留外部身份"
        )
        return TaxonomyReconciliation(
            canonical_key=identity_key,
            valuation_archetype=node_archetype(identity_key),
            conflict_kind=ConflictKind.CONSISTENT,
            identity_source=identity_source,
            notes=notes,
        )

    anc = common_ancestor(identity_key, economics_key) or id_family
    notes.append(
        f"族内原型冲突：身份 '{IDENTITY_NODES[identity_key].label}' vs 经济特征 "
        f"'{IDENTITY_NODES[economics_key].label}' → 收敛至共同祖先 "
        f"'{IDENTITY_NODES[anc].label}'，不采用任一细分标签作为估值原型"
    )
    return TaxonomyReconciliation(
        canonical_key=anc,
        valuation_archetype=node_archetype(anc),
        conflict_kind=ConflictKind.REFINEMENT,
        identity_source=identity_source,
        confidence_delta=-0.05,
        notes=notes,
    )


def decide_status(
    conflict_kind: ConflictKind,
    identity_source: str,
    *,
    ml_confidence: Optional[float] = None,
) -> DecisionStatus:
    """Map a reconciliation verdict onto the four-state decision contract.

    Evidence-driven and deterministic (no name-specific thresholds):

      * ``INSUFFICIENT``   → INSUFFICIENT_DATA — nothing reliable to classify.
      * ``IDENTITY_WINS``  → AMBIGUOUS — an important cross-family conflict exists.
      * ``ECONOMICS_ONLY`` → PROBABLE when the ML signal is reasonably strong,
                             else AMBIGUOUS (no structured evidence at all).
      * ``REFINEMENT``     → PROBABLE — same-family collapse, minor ambiguity.
      * ``CONSISTENT``     → CONFIRMED when the identity rests on a structured
                             external fact, else PROBABLE (free text only).
    """
    if conflict_kind == ConflictKind.INSUFFICIENT:
        return DecisionStatus.INSUFFICIENT_DATA
    if conflict_kind == ConflictKind.IDENTITY_WINS:
        return DecisionStatus.AMBIGUOUS
    if conflict_kind == ConflictKind.ECONOMICS_ONLY:
        if ml_confidence is not None and ml_confidence >= _ECONOMICS_ONLY_MIN_CONF:
            return DecisionStatus.PROBABLE
        return DecisionStatus.AMBIGUOUS
    if conflict_kind == ConflictKind.REFINEMENT:
        return DecisionStatus.PROBABLE
    # CONSISTENT
    if identity_source.startswith("yahoo_industry"):
        return DecisionStatus.CONFIRMED
    return DecisionStatus.PROBABLE


# ===========================================================================
# Five-dimension assembly
# ===========================================================================
@dataclass
class BusinessTaxonomyProfile:
    """The five dimensions assembled for one company, plus the verdict."""

    identity_key: Optional[str]
    identity_label: Optional[str]
    identity_business_type: str
    business_models: List[str]
    revenue_composition: RevenueComposition
    economic_profile: EconomicProfile
    external: ExternalClassification
    reconciliation: TaxonomyReconciliation
    decision_status: DecisionStatus
    description_refined_node: Optional[str] = None

    def audit_lines(self) -> List[str]:
        lines: List[str] = []
        lines.append(
            f"① 业务身份: {self.identity_label or '未定'}"
            f"（{self.identity_key or 'n/a'} → 估值原型 {self.identity_business_type}）"
        )
        if self.business_models:
            lines.append("② 商业模式: " + "、".join(self.business_models))
        if self.revenue_composition.available and self.revenue_composition.segments:
            seg = "、".join(
                f"{s.label} {('%.0f%%' % (s.pct * 100)) if s.pct is not None else 'n/a'}"
                for s in self.revenue_composition.segments
            )
            lines.append(f"③ 收入构成: {seg}（as-of {self.revenue_composition.as_of or 'n/a'}）")
        else:
            lines.append("③ 收入构成: 不可用（无分部收入数据源）")
        ep = self.economic_profile
        bits = []
        if ep.gross_margin is not None:
            bits.append(f"毛利率 {ep.gross_margin:.0%}")
        if ep.capex_to_revenue is not None:
            bits.append(f"CapEx/营收 {ep.capex_to_revenue:.0%}")
        if ep.fcf_margin is not None:
            bits.append(f"FCF 利润率 {ep.fcf_margin:.0%}")
        lines.append("④ 经济特征: " + ("、".join(bits) if bits else "n/a"))
        ext = self.external
        lines.append(
            f"⑤ 外部标签: Yahoo='{ext.yahoo_sector or 'n/a'}/{ext.yahoo_industry or 'n/a'}'"
            f"，ML='{ext.ml_label or 'n/a'}'"
        )
        lines.append(
            f"◆ 决策状态: {_DECISION_LABELS.get(self.decision_status.value, self.decision_status.value)}"
            f"（{self.decision_status.value}）"
        )
        for n in self.reconciliation.notes:
            lines.append(f"  · {n}")
        return lines


def _pct(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None or den <= 0:
        return None
    return num / den


def derive_economic_profile(data: Any,
                            revenue_composition: Optional[RevenueComposition] = None) -> EconomicProfile:
    """Derive dimension ④ from the financial statements (ttm-first)."""
    notes: List[str] = []
    ttm = getattr(data, "ttm", None)
    annuals = getattr(data, "annual_income", None) or []

    gm = om = fcfm = capex_r = de_r = cagr = None
    is_loss = False
    if ttm is not None and ttm.revenue and ttm.revenue > 0:
        gm = _pct(ttm.gross_profit, ttm.revenue)
        om = _pct(ttm.operating_income, ttm.revenue)
        fcfm = _pct(ttm.free_cash_flow, ttm.revenue)
        capex_r = _pct(abs(ttm.capex) if ttm.capex is not None else None, ttm.revenue)
        is_loss = bool(
            (ttm.net_income is not None and ttm.net_income < 0)
            or (ttm.operating_income is not None and ttm.operating_income < 0)
        )

    mkt = getattr(data, "market", None)
    if (mkt is not None and mkt.total_debt is not None
            and mkt.book_value and mkt.book_value > 0):
        de_r = mkt.total_debt / mkt.book_value

    if len(annuals) >= 2 and annuals[0].revenue and annuals[-1].revenue and annuals[-1].revenue > 0:
        n = len(annuals) - 1
        try:
            cagr = (annuals[0].revenue / annuals[-1].revenue) ** (1 / n) - 1
        except (ValueError, ZeroDivisionError):
            cagr = None

    recurring = None
    if revenue_composition is not None and revenue_composition.available:
        recurring = None  # not derivable from generic segments yet
        notes.append("收入构成可用，但经常性收入占比尚未细分，留空")

    return EconomicProfile(
        gross_margin=gm,
        operating_margin=om,
        fcf_margin=fcfm,
        capex_to_revenue=capex_r,
        de_ratio=de_r,
        revenue_cagr=cagr,
        recurring_revenue_pct=recurring,
        is_loss_making=is_loss,
        is_capex_heavy=bool(capex_r is not None and capex_r >= 0.20),
        is_asset_light=bool(capex_r is not None and capex_r < 0.05 and (gm or 0) >= 0.50),
        notes=notes,
    )


def build_taxonomy_profile(
    data: Any,
    *,
    ml_label: Optional[str] = None,
    ml_confidence: Optional[float] = None,
    description: Optional[str] = None,
    revenue_composition: Optional[RevenueComposition] = None,
    external: Optional[ExternalClassification] = None,
) -> BusinessTaxonomyProfile:
    """Assemble the five-dimension taxonomy profile for one company.

    ``data`` is a :class:`~data.models.FinancialData`. ``ml_label`` is the
    internal archetype label (ML top-1 or rule top-1). ``description`` is the
    provider's business summary. ``revenue_composition`` defaults to explicit
    "unavailable" because no segment source is wired yet.
    """
    mkt = getattr(data, "market", None)

    if external is None:
        external = ExternalClassification(
            yahoo_sector=getattr(mkt, "sector", None) if mkt is not None else None,
            yahoo_industry=getattr(mkt, "industry", None) if mkt is not None else None,
            ml_label=ml_label,
            ml_confidence=ml_confidence,
            source_note="yahoo sector/industry from MarketData",
        )
    else:
        if external.ml_label is None:
            external.ml_label = ml_label
        if external.ml_confidence is None:
            external.ml_confidence = ml_confidence

    if description is None:
        description = (getattr(mkt, "description", None) or getattr(mkt, "business_summary", None)
                       if mkt is not None else None)

    if revenue_composition is None:
        # M-31: providers stash a resolved composition on the FinancialData
        # object; fall back to explicit "unavailable" when absent (offline/golden).
        revenue_composition = getattr(data, "revenue_composition", None) or RevenueComposition.unavailable()

    description_key = node_from_description(description)
    economics_key = node_from_ml_label(ml_label)

    reconciliation = reconcile_identity(
        external=external,
        description_key=description_key,
        economics_key=economics_key,
    )

    canonical = reconciliation.canonical_key

    decision_status = decide_status(
        reconciliation.conflict_kind,
        reconciliation.identity_source,
        ml_confidence=external.ml_confidence,
    )

    models = infer_business_models(
        " ".join(filter(None, [description, external.yahoo_industry, external.yahoo_sector]))
    )

    return BusinessTaxonomyProfile(
        identity_key=canonical,
        identity_label=IDENTITY_NODES[canonical].label if canonical else None,
        identity_business_type=node_archetype(canonical).value,
        business_models=[m.value for m in models],
        revenue_composition=revenue_composition or RevenueComposition.unavailable(),
        economic_profile=derive_economic_profile(data, revenue_composition),
        external=external,
        reconciliation=reconciliation,
        decision_status=decision_status,
        description_refined_node=description_key,
    )


def attach_taxonomy_profile(
    data: Any,
    profile: Any,
    *,
    ml_label: Optional[str] = None,
    ml_confidence: Optional[float] = None,
    description: Optional[str] = None,
    tp: Optional[BusinessTaxonomyProfile] = None,
) -> BusinessTaxonomyProfile:
    """Build the taxonomy profile and write its primitives onto ``profile``.

    Additive only: it never mutates ``business_type`` / ``applicable_models`` /
    routing, so the existing golden fingerprints do not drift. The wiring lives
    here (one place) so both the rule and the ML classifier expose the same
    five-dimension contract.

    ``tp`` lets a caller that already built the profile reuse it (M-32 needs the
    taxonomy *before* model routing to feed :func:`taxonomy_routing_override`).
    """
    tp = tp or build_taxonomy_profile(
        data, ml_label=ml_label, ml_confidence=ml_confidence, description=description,
    )
    try:
        profile.taxonomy_identity_key = tp.identity_key
        profile.taxonomy_identity_label = tp.identity_label
        profile.taxonomy_business_models = list(tp.business_models)
        profile.taxonomy_conflict_kind = tp.reconciliation.conflict_kind.value
        profile.taxonomy_decision_status = tp.decision_status.value
        profile.taxonomy_audit = tp.audit_lines()
        profile.revenue_composition_available = tp.revenue_composition.available
        profile.revenue_composition_note = tp.revenue_composition.note
        profile.external_classification = {
            "yahoo_sector": tp.external.yahoo_sector,
            "yahoo_industry": tp.external.yahoo_industry,
            "ml_label": tp.external.ml_label,
            "ml_confidence": tp.external.ml_confidence,
        }
    except AttributeError:
        log.debug("profile object does not support taxonomy fields; skipping attach")
    return tp


# ===========================================================================
# M-32 — Taxonomy as a routing participant (cross-family gate)
# ===========================================================================
# Until M-32 the taxonomy was purely additive (a shadow): it recorded the five
# dimensions but never touched ``business_type`` / model routing. M-32 lets it
# *direct* routing — but only behind a deliberately narrow gate, so the change
# is auditable and the existing golden routing cannot drift:
#
#   1. the decision must be CONFIRMED (multi-source agreement, not a guess);
#   2. the canonical identity must conflict with the internal route *across
#      identity families* (e.g. Industrials → Financials). A same-family
#      difference — ``MatureTech`` vs ``SaaS`` are both ``tech`` — is a
#      *narrowing* the economics-driven classifier may legitimately own, so it
#      is NOT overridden;
#   3. the economic guardrail always wins: a target archetype that claims an
#      asset-light model while the company is visibly running a capital-heavy
#      build-out is rejected (the caller passes ``guard_blocked=True``).
TAXONOMY_ROUTING_STATUSES: frozenset = frozenset({DecisionStatus.CONFIRMED})


def _archetype_family_index() -> Dict[BusinessType, frozenset]:
    idx: Dict[BusinessType, set] = {}
    for n in IDENTITY_NODES.values():
        if n.archetype == BusinessType.UNKNOWN:
            continue
        idx.setdefault(n.archetype, set()).add(n.family)
    return {bt: frozenset(fams) for bt, fams in idx.items()}


# Which identity family (or families) each valuation archetype belongs to.
# Derived from the node tree so the two can never drift apart.
ARCHETYPE_FAMILIES: Dict[BusinessType, frozenset] = _archetype_family_index()


def same_identity_family(internal_bt: Any, taxonomy_key: Optional[str]) -> bool:
    """True when ``taxonomy_key``'s family is one the internal archetype maps to.

    ``UNKNOWN`` (or an unmapped archetype) has no family of its own, so it never
    counts as "same family" — the taxonomy is free to supply the missing route.
    """
    n = node(taxonomy_key)
    if n is None or internal_bt == BusinessType.UNKNOWN:
        return False
    return n.family in ARCHETYPE_FAMILIES.get(internal_bt, frozenset())


def taxonomy_routing_override(
    internal_bt: Any,
    taxonomy_key: Optional[str],
    decision_status: Any = None,
    *,
    guard_blocked: bool = False,
) -> Optional[BusinessType]:
    """Archetype the taxonomy should route to, or ``None`` to keep the internal one.

    See the module-level M-32 note for the three gate conditions. Pure and
    side-effect free so both classifiers share one routing rule.
    """
    if decision_status not in TAXONOMY_ROUTING_STATUSES:
        return None
    n = node(taxonomy_key)
    if n is None or n.archetype == BusinessType.UNKNOWN:
        return None
    if n.archetype == internal_bt:
        return None
    if same_identity_family(internal_bt, taxonomy_key):
        return None
    if guard_blocked:
        return None
    return n.archetype


__all__ = [
    "IdentityNode", "IDENTITY_NODES", "node", "node_archetype",
    "common_ancestor", "economic_identity_ceiling",
    "BusinessModel", "infer_business_models",
    "SegmentRevenue", "RevenueComposition",
    "EconomicProfile", "ExternalClassification",
    "YAHOO_INDUSTRY_TO_NODE", "YAHOO_SECTOR_TO_NODE", "ML_LABEL_TO_NODE",
    "node_from_yahoo", "node_from_ml_label", "node_from_description",
    "ConflictKind", "TaxonomyReconciliation", "reconcile_identity",
    "BusinessTaxonomyProfile", "derive_economic_profile", "build_taxonomy_profile",
    "attach_taxonomy_profile",
    "TAXONOMY_ROUTING_STATUSES", "ARCHETYPE_FAMILIES", "same_identity_family",
    "taxonomy_routing_override",
]
