"""
classification/_semi_auto_label.py
===================================
Semi-automatically pre-fill the `label` column in `labeling_dump.csv` using:
  1. Explicit ticker whitelist (well-known ticker → BusinessType) — hits 90%+ confidence
  2. Yahoo Finance sector/industry string matching (GISC mapping)
  3. company_name keyword match (reusing BusinessClassifier.KEYWORDS)
  4. Financial-ratio heuristic rules:
       - Bank  : interest / revenue > 0.20  (from classifier._looks_like_bank)
       - REIT  : EBITDA margin ∈ [0.55, 0.90] AND beta < 2.0
       - SaaS  : gross_margin ≥ 0.70 AND revenue CAGR ≥ 0.10
  5. Remaining rows stay Unknown → user manual review.

Outputs `labeling_dump.csv` IN-PLACE (overwritten). Also prints a report
(pre-filled distribution, remaining Unknown list for manual review).

Run:  python classification\_semi_auto_label.py
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import BusinessType  # noqa: E402
from classification.classifier import BusinessClassifier  # noqa: E402

CSV_PATH = ROOT / "classification" / "labeling_dump.csv"

# ---------------------------------------------------------------------------
# 1. Explicit ticker whitelist — the single highest-precision signal.
#    Organised so the mapping is immediately readable / extendable by humans.
# ---------------------------------------------------------------------------
_TICKER_WHITELIST: Dict[str, BusinessType] = {}

def _wl(bt: BusinessType, tickers: List[str]) -> None:
    for t in tickers:
        _TICKER_WHITELIST[t.strip().upper()] = bt

_wl(BusinessType.MATURE_TECH, [
    "AAPL", "MSFT", "GOOGL", "GOOG", "META", "ORCL", "IBM", "CSCO", "ADBE", "INTC",
    "QCOM", "TXN", "AVGO", "AMAT", "MU", "LRCX", "KLAC", "ADI", "NXPI", "MCHP",
    "APH", "GLW", "FTV", "ANET", "PANW", "FTNT", "CRWD", "HUBS", "NOW", "TEAM",
    "SNOW", "WDAY", "RXRX", "VRSN", "CHKP", "CDNS", "SNPS", "ANSS",
])
_wl(BusinessType.SAAS, [
    "CRM", "ZS", "NET", "OKTA", "DDOG", "MDB", "SHOP", "SQ", "PYPL", "DOCU",
    "COUP", "TWLO", "BL", "BILL", "WIX", "SPLK", "ESTC", "CLDR", "APP",
    "PD", "MNDY", "LCID", "RIVN", "FROG", "PATH", "ASAN", "JAMF",
])
_wl(BusinessType.SEMICONDUCTOR, [
    "NVDA", "AMD", "TSM", "ASML", "ARM", "SMCI", "MRVL", "ON", "SWKS", "MPWR",
    "QRVO", "SLAB", "COHR", "LITE", "IIVI", "IPGP", "ENTG", "TER", "AMKR",
    "DIOD", "MTSI", "LSCC", "OSIS", "MSEM", "VLN", "AXTI", "NPTN", "SILK",
])
_wl(BusinessType.CONSUMER_CYCLICAL, [
    "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "BKNG", "TJX", "MAR",
    "YUM", "DG", "DLTR", "ROST", "BBY", "EXPE", "CMG", "MGM", "LVS", "WYNN",
    "DHI", "LEN", "PHM", "TGT", "AZO", "ORLY", "F", "GM", "RACE", "CCL",
    "NCLH", "RCL", "AAL", "DAL", "UAL", "LUV", "HA", "ALK", "SKYW",
])
_wl(BusinessType.REIT, [
    "PLD", "AMT", "EQIX", "CCI", "SPG", "PSA", "O", "WELL", "EQR", "AVB",
    "DLR", "VICI", "ARE", "BXP", "HST", "PEAK", "EXR", "MAA", "ESS", "UDR",
    "REG", "FRT", "ADC", "AKR", "WPC", "STOR", "NNN", "STAG", "IRM", "VTR",
    "HCP", "DOC", "SBAC", "CSGP", "ELV", "INVH", "AMH", "BRX", "KIM",
])
_wl(BusinessType.BANK, [
    "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW", "AXP", "COF",
    "USB", "TFC", "PNC", "MET", "PRU", "AIG", "ALL", "AJG", "MMC", "BK",
    "STT", "NTRS", "CME", "ICE", "SPGI", "MCO", "MA", "V", "DFS", "SYF",
    "ALLY", "CFG", "HBAN", "KEY", "MTB", "FITB", "RF", "TROW", "EV",
    "ZION", "PBCT", "CBSH", "FRC", "SIVB", "WAL", "CMA", "EWBC", "SNV",
])
_wl(BusinessType.INSURANCE, [
    "BRK.B", "BRK", "TRV", "PGR", "CB", "ALL", "AFL", "HIG", "AIZ", "LNC",
    "MET", "PRU", "AIG", "UNM", "PFG", "RGA", "CINF", "WRB", "GL", "RE",
    "CNA", "C", "BHF", "CFR", "FNF", "STC", "MCY", "ASR", "AXS", "SIGI",
])
_wl(BusinessType.COMMODITY, [
    "XOM", "CVX", "COP", "SHEL", "TTE", "BP", "SLB", "EOG", "MPC", "PSX",
    "VLO", "OXY", "PXD", "DVN", "WMB", "ET", "KMI", "LNG", "APA", "MRO",
    "FANG", "CTRA", "HES", "HAL", "BKR", "RRC", "SWN", "EQT", "COG",
    "FCX", "RIO", "BHP", "GLNCY", "VALE", "NEM", "GOLD", "AU", "AG",
    "AA", "NUE", "STLD", "CLF", "X", "RS", "TMST", "CF", "MOS", "IPI",
])
_wl(BusinessType.UTILITIES, [
    "NEE", "DUK", "SO", "D", "EXC", "AEP", "SRE", "XEL", "WEC", "ES",
    "ED", "EIX", "FE", "PPL", "CMS", "LNT", "DTE", "ETR", "AWK", "VST",
    "DUKH", "CEG", "POR", "BEP", "BEPC", "PNW", "PEG", "UGI", "ATO", "GAS",
    "CNP", "NRG", "AEE", "CNX", "ETRN", "OKE", "TRGP", "ENB",
])
_wl(BusinessType.CONGLOMERATE, [
    "BRK.B", "BRK", "GE", "HON", "UTX", "RTX", "CAT", "DE", "ETN", "EMR",
    "ITW", "ABB", "SI", "HMC", "TM", "MMM", "PH", "ROK", "IEX", "GD",
    "LMT", "NOC", "BA", "TXT", "LHX", "TDG", "CARR", "OTIS", "RGEN",
])


# ---------------------------------------------------------------------------
# 2. Yahoo sector/industry (GISC) → BusinessType mapping
# ---------------------------------------------------------------------------
_SECTOR_MAP: Dict[str, BusinessType] = {
    "semiconductors": BusinessType.SEMICONDUCTOR,
    "semiconductor": BusinessType.SEMICONDUCTOR,
    "banks": BusinessType.BANK,
    "bank": BusinessType.BANK,
    "insurance": BusinessType.INSURANCE,
    "insurers": BusinessType.INSURANCE,
    "reits": BusinessType.REIT,
    "reit": BusinessType.REIT,
    "real estate": BusinessType.REIT,
    "utilities": BusinessType.UTILITIES,
    "electric utilities": BusinessType.UTILITIES,
    "gas utilities": BusinessType.UTILITIES,
    "water utilities": BusinessType.UTILITIES,
    "oil & gas": BusinessType.COMMODITY,
    "oil and gas": BusinessType.COMMODITY,
    "energy minerals": BusinessType.COMMODITY,
    "energy": BusinessType.COMMODITY,
    "metals & mining": BusinessType.COMMODITY,
    "metals and mining": BusinessType.COMMODITY,
    "chemicals": BusinessType.COMMODITY,
    "steel": BusinessType.COMMODITY,
    "coal": BusinessType.COMMODITY,
    "internet retail": BusinessType.CONSUMER_CYCLICAL,
    "specialty retail": BusinessType.CONSUMER_CYCLICAL,
    "automobiles": BusinessType.CONSUMER_CYCLICAL,
    "auto": BusinessType.CONSUMER_CYCLICAL,
    "auto manufacturers": BusinessType.CONSUMER_CYCLICAL,
    "leisure": BusinessType.CONSUMER_CYCLICAL,
    "hotels": BusinessType.CONSUMER_CYCLICAL,
    "restaurants": BusinessType.CONSUMER_CYCLICAL,
    "airlines": BusinessType.CONSUMER_CYCLICAL,
    "travel services": BusinessType.CONSUMER_CYCLICAL,
    "homebuilding": BusinessType.CONSUMER_CYCLICAL,
    "home improvement": BusinessType.CONSUMER_CYCLICAL,
    "software": BusinessType.MATURE_TECH,
    "software - application": BusinessType.MATURE_TECH,
    "software - infrastructure": BusinessType.MATURE_TECH,
    "information technology services": BusinessType.MATURE_TECH,
    "communication equipment": BusinessType.MATURE_TECH,
    "electronic equipment": BusinessType.MATURE_TECH,
    "diversified industrials": BusinessType.CONGLOMERATE,
    "conglomerates": BusinessType.CONGLOMERATE,
}

_INDUSTRY_BOOST_SAAS = {"saaS", "cloud computing", "software - application",
                        "software as a service", "application software"}


def _match_keyword_text(text: str) -> Optional[BusinessType]:
    """Keyword match against classifier.KEYWORDS (copied rule)."""
    if not text:
        return None
    t = text.lower()
    best: Optional[BusinessType] = None
    best_hits = 0
    for bt, kws in BusinessClassifier.KEYWORDS.items():
        hits = sum(1 for kw in kws if kw.lower() in t)
        if hits > best_hits:
            best_hits = hits
            best = bt
    if best_hits == 0:
        return None
    return best


def _match_sector_industry(sector: str, industry: str) -> Optional[BusinessType]:
    concat = f"{sector or ''} {industry or ''}".lower().strip()
    if not concat or concat == "n/a n/a":
        return None
    # 1) direct hash
    for key, bt in _SECTOR_MAP.items():
        if key in concat:
            return bt
    # 2) SaaS boost
    if any(s in concat for s in _INDUSTRY_BOOST_SAAS):
        return BusinessType.SAAS
    return None


def _ratio_rules(row: Dict[str, str]) -> Optional[BusinessType]:
    def f(k: str) -> Optional[float]:
        v = row.get(k, "")
        if not v or v.lower() in {"", "n/a", "nan", "none"}:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    interest_to_rev = f("interest_to_revenue")
    if interest_to_rev is not None and interest_to_rev > 0.20:
        return BusinessType.BANK

    gross_margin = f("gross_margin")
    rev_cagr = f("revenue_cagr_3y")
    if (gross_margin is not None and gross_margin >= 0.70
            and rev_cagr is not None and rev_cagr >= 0.10):
        return BusinessType.SAAS

    op_margin = f("operating_margin")
    beta = f("beta")
    # REIT ratio rule: EBITDA margin ∈ [0.55, 0.90] and beta < 2.0
    if (op_margin is not None and 0.55 <= op_margin <= 0.90
            and (beta is None or beta <= 2.0)):
        return BusinessType.REIT
    return None


def _label_one(row: Dict[str, str]) -> Tuple[Optional[BusinessType], str]:
    """Return (label, source_reason) — or (None, '') if still unknown."""
    ticker = (row.get("ticker") or "").strip().upper()
    sector = row.get("sector") or ""
    industry = row.get("industry") or ""
    name = row.get("company_name") or ""
    note_field = row.get("note") or ""

    # 1. Whitelist (highest confidence, short-circuits)
    if ticker in _TICKER_WHITELIST:
        return _TICKER_WHITELIST[ticker], "whitelist"

    # 2. sector / industry mapping
    by_sec = _match_sector_industry(sector, industry)
    if by_sec is not None:
        if by_sec == BusinessType.MATURE_TECH:
            via_ratio = _ratio_rules(row)
            if via_ratio is BusinessType.SAAS:
                return BusinessType.SAAS, "sector+ratio→SaaS"
        return by_sec, "sector/industry"

    # 3. keyword text match (classifier.KEYWORDS)
    by_kw = _match_keyword_text(f"{name} {sector} {industry}")
    if by_kw is not None:
        return by_kw, "keyword"

    # 4. company-name deep rule (fills gap where Yahoo sector/industry 401)
    by_name_deep = _name_deep_rules(name)
    if by_name_deep is not None:
        if by_name_deep == BusinessType.MATURE_TECH:
            via_ratio = _ratio_rules(row)
            if via_ratio is BusinessType.SAAS:
                return BusinessType.SAAS, "name+ratio→SaaS"
        return by_name_deep, "name-deep-rule"

    # 5. financial ratio rules
    by_ratio = _ratio_rules(row)
    if by_ratio is not None:
        return by_ratio, "ratio-heuristic"

    # 6. Synthetic rows → Unknown but note-marked, user can skip
    if note_field and "synthetic" in note_field.lower():
        return BusinessType.UNKNOWN, "synthetic-fallback"

    return None, ""


# ---------------------------------------------------------------------------
# 4b. company_name deep-rules — catch-alls for the 83% with Yahoo sector=401.
#     Each rule returns the *first* BT that matches (ordered by precision).
# ---------------------------------------------------------------------------
_NAME_RULES: List[Tuple[BusinessType, List[str]]] = [
    # --- Bank / Financial Services (high precision) ---
    (BusinessType.BANK, [
        "bank", "banking", "bancorp", "bancshares", "community bank",
        "federal savings", "savings bank", "holding corp", "trust bank",
        "national banc", "commercial bank", "securities group",
        "brokerage", "asset management", "capital markets", "investment bank",
        "exchange-traded fund", "etf", "mutual fund", "closed-end fund",
        "trust company", "state street", "depositary", "clearing",
        "financial services", "finance corp", "consumer finance",
        "card services", "credit services", "payment",
        "financial group", "financial corp", "nasdaq", "cme group",
        "intercontinental exchange", "markit", "s&p global",
        "moody's corp", "cboe global markets", "nasdaq inc",
        "cboe", "chubb limited", "united wholesale mortgage",
        "upstart holdings", "sofi technologies", "lendingclub",
        "ally financial", "synchrony financial", "discover financial",
        "capital one financial", "american express", "beacon financial",
        "capital corp", "first interstate", "western alliance",
        "pacwest bancorp", "zion", "keycorp", "huntington bancshares",
        "regions financial", "fifth third", "truist financial",
        "pnc financial", "us bancorp", "citizens financial",
    ]),
    (BusinessType.INSURANCE, [
        "insurance", "assurance", "reinsurance", "life ins", "property and casualty",
        "p&c insurance", "auto ins", "health insurance", "title insurance",
        "guaranty", "benefit plans", "surety", "american family",
        "berkshire hathaway", "progressive corp", "marsh & mclennan",
        "arthur j. gallagher", "aon plc", "welltower",
        "sun life financial", "manulife financial", "power corp of canada",
        "great-west lifeco", "equitable holdings", "lincoln national",
        "prudential financial", "metlife", "brighthouse financial",
        "american international group", "unum group", "principal financial",
        "reinsurance group", "old republic", "rli corp",
        "american financial group", "cno financial", "loews corp",
        "kinsale capital", "hci group", "proassurance",
        "national health investors", "healthcare investors",
        "welltower", "ventas", "sabra health care",
        "medical properties", "omega healthcare",
        "healthpeak properties", "h-ta", "inventrust properties",
        "beacon financial", "arc investment management",
        "ha sustainable infrastructure",
    ]),
    (BusinessType.REIT, [
        "reit", "real estate", "property trust", "apartment investment",
        "residential", "lifestyle properties", "shopping center",
        "data centre realty", "data center", "digital realty",
        "communications tower", "tower realty", "public storage",
        "extra space", "cube smart", "life storage", "equity residential",
        "aimco", "u dr", "mid-america", "home properties", "estar",
        "macerich", "taubman", "cbl properties", "simon property",
        "general growth", "premium outlets", "tanger",
    ]),
    # --- Semiconductor + hardware manufacturing ---
    (BusinessType.SEMICONDUCTOR, [
        "semiconductor", "silicon motion", "wolfspeed",
        "kulicke", "axcelis", "onsemi",
        "chip design", "chip equipment", "memory chip", "memory products",
        "wafer", "photronics", "cadence design", "synopsys", "ansys",
        "silicon labs", "microchip technology", "monolithic power",
        "power integrations", "rambus", "marvell technology",
    ]),
    # --- Conglomerate: diversified / Staples / Holding / Industrial — also absorbs Consumer Staples (KO/PEP/PG/CL/KMB/KO/PEP...) because no Staples BusinessType exists ---
    (BusinessType.CONGLOMERATE, [
        "diversified industrials", "diversified holdings", "global industrials",
        "group holdings", "industrial conglomerate", "multi-industry",
        "carlisle", "dover corp", "illinois tool works", "emerson electric",
        "honeywell", "general electric", "3m company", "parker-hannifin",
        "rtx corp", "lockheed martin", "northrop grumman", "l3harris",
        "boeing co", "general dynamics", "raytheon", "textron",
        "caterpillar", "deere & company", "cummins", "eaton corp",
        "abb ltd", "siemens", "hitachi", "mitsubishi", "sumitomo",
        # Industrial distribution / manufacturing (not clearly pure-Cyclical)
        "fastenal company", "paccar inc", "ingersoll rand",
        "stanley black & decker", "howmet aerospace",
        "quanta services", "steris plc",
        # Consumer Staples → Conglomerate mapping (stable, defensive, diversified)
        "coca-cola", "pepsico", "kraft heinz", "mondelez international",
        "general mills", "kraft foods", "campbell soup", "kellogg",
        "hershey", "j.m. smucker", "snyders-lance",
        "procter & gamble", "colgate-palmolive", "clorox",
        "kimberly-clark", "church & dwight",
        "estee lauder", "coty inc", "avon products",
        "walgreens boots", "cvs health", "rite aid",
        "albertsons", "kroger", "supermarket",
        "altria group", "marlboro", "philip morris",
        "imperial brands", "british american tobacco",
        "kimberly", "personal products", "household products",
        "beverages", "soft drink", "bottling",
        "food products", "grocery stores",
        "loews corporation", "markel group",
        "kinross gold",
    ]),
    # --- Commodity: energy, mining, chemicals, steel, forest products — plus Chemicals (PPG/FMC/ASH/EMN/ALB/LTHM/CTVA ...) & Midstream ---
    (BusinessType.COMMODITY, [
        "petroleum", "oil and gas", "natural gas", "energy corp",
        "exploration and production", "upstream oil", "midstream",
        "refining", "marathon petroleum", "pbf energy", "hollyfrontier",
        "western midstream", "enable midstream", "mpLX", "oneok",
        "pipeline", "coal", "uranium", "cameco", "peabody", "arch resources",
        "mining", "freeport-mcmoran", "barrick gold", "newmont",
        "agnico eagle", "wheaton precious", "kirkland lake",
        "steel", "nucor", "stelco", "united states steel",
        "reliance steel", "commercial metals", "cleveland-cliffs",
        "chemicals", "dupont", "dow inc", "basf", "lyondellbasell",
        "fertilizer", "mosaic co", "cf industries", "nutrien",
        "timber", "weyerhaeuser", "rayonier", "potlatchdeltic",
        "lp building", "suzano", "fibria", "klabin",
        "enterprise products", "canadian natural resources",
        "suncor energy", "teck resources", "southern copper",
        "albemarle", "livent", "lithium", "vylor", "fmc corporation",
        "ashland", "eastman chemical", "ppg industries",
        "corteva", "bunge", "archer daniels", "ingredion",
    ]),
    # --- Utilities: electric, gas, water, power generation — plus Telecom/Wireless/Cable (Comm Svcs → Utilities-like stable regulated) ---
    (BusinessType.UTILITIES, [
        "electric power", "electric utility", "power & light",
        "power and light", "gas utilities", "gas company",
        "northwest natural", "southwest gas", "spire inc",
        "water utilities", "water company", "american water works",
        "california water", "water service",
        "exelon corp", "constellation energy",
        "nextEra energy", "dominion energy", "southern company",
        "american electric", "firstenergy", "entergy",
        "alliant energy", "centerpoint energy", "evergy",
        "public service enterprise", "pnr resources",
        "boston properties utility", "utility holding",
        "pge corporation", "pg&e", "idacorp", "nisource",
        "companhia energetica", "cemig", "enel",
        "telecommunications", "communications inc",
        "verizon communications", "at&t", "t-mobile us",
        "charter communications", "comcast corp",
        "cable one", "lumen technologies", "centurylink",
        "windstream holdings", "frontier communications",
        "iridium communications", "ribbon communications",
        "rogers communications", "shaw communications",
        "telus corp", "bce inc",
    ]),
    # --- Consumer Cyclical: retail, restaurant, travel, auto, home ---
    (BusinessType.CONSUMER_CYCLICAL, [
        "retail", "retailers", "department store", "specialty store",
        "discount store", "walmart", "costco", "target corp",
        "tjx companies", "ross stores", "burlington stores",
        "dollar general", "dollar tree", "big lots",
        "macy's", "kohl's", "dillard's", "nordstrom", "belk",
        "lululemon", "crocs", "deckers outdoor", "pvh corp",
        "under armour", "nike inc", "adidas", "skechers",
        "restaurant", "pizza", "chili's", "cheesecake factory",
        "brinker international", "darden restaurants",
        "restaurant brands", "starbucks corp", "mcdonald's",
        "yum! brands", "domino's pizza", "papa john's",
        "chipotle mexican", "wendy's", "bloomin' brands",
        "resorts", "hotels", "marriott int", "hyatt hotels",
        "intercontinental hotels", "wyndham hotels", "hilton worldwide",
        "wynn resorts", "las vegas sands", "mgm resorts",
        "airlines", "airways", "delta air", "american airlines",
        "united continental", "southwest airlines", "jetblue",
        "alaska air", "skywest", "allegiant travel",
        "automobile", "tesla", "ford motor", "general motors",
        "nio inc", "xpeng inc", "li auto", "rivian", "lucid",
        "homebuilding", "home builder", "d.r. horton",
        "lenox corp", "pultegroup", "nvr inc",
        "tri pointe", "kb home", "toll brothers",
        "expedia", "tripadvisor", "booking holdings", "airbnb",
        "lyft", "doordash", "ubereats", "uber technologies",
        "netflix", "roku inc", "streaming entertainment",
        "autonation", "carvana", "group 1 automotive",
        # --- Building materials + homebuilding 追加 ---
        "builders firstsource", "bluelinx holdings",
        "abercrombie & fitch", "american eagle outfitters",
        "imax corporation", "cinemark", "amc entertainment",
        "microstrategy", "strategy inc", "snap inc",
    ]),
    # --- Mature Tech: hardware, IT services, consulting, internet platform — also absorbs **Pharma / MedTech / Healthcare** (no dedicated Healthcare BT) via margin profile heuristics later ---
    (BusinessType.MATURE_TECH, [
        "technologies", "technology inc", "tech corp", "information tech",
        "software", "systems inc", "data storage", "hardware",
        "computer", "computing", "network", "networking",
        "communications equipment", "data communications",
        "corning inc", "dell technologies", "hewlett packard", "hp inc",
        "flex ltd", "jabil inc", "celestica", "sanmina",
        "seagate", "western digital", "pure storage",
        "quantum corp", "netapp inc", "cognizant tech",
        "accenture plc", "infosys ltd", "wipro", "tata consultancy",
        "hcl technologies", "capgemini", "epam systems",
        "cisco systems", "juniper networks", "palo alto networks",
        "fortinet inc", "crowdstrike", "zscaler", "check point",
        "cloudflare", "akamai tech", "f5 networks",
        "arista networks", "extreme networks", "commscope",
        "motorola solutions", "keysight technologies",
        "monolithic power", "maxlinear", "silicon motion",
        "box, inc.", "dropbox", "zoom video", "five9",
        "smartsheet", "hubspot", "yext inc",
        "electronic arts", "take-two interactive", "activision",
        "roblox corp", "unity software",
        "motorola mobility", "blackberry ltd",
        "printing & publishing tech", "xerox",
        # Pharma / Biotech / Healthcare → MatureTech fallback (no dedicated BT)
        # High margin + high CAGR → SaaS upgrade handled in _label_one ratio rule
        "johnson & johnson", "pfizer", "eli lilly", "merck & co",
        "novartis", "roche holding", "abbvie", "bristol myers",
        "astrazeneca", "gilead sciences", "amgen", "biogen",
        "regeneron pharmaceuticals", "vertex pharmaceuticals",
        "moderna", "biontech", "alnylam pharmaceuticals",
        "regeneron", "incyte corporation", "lilly",
        "pharmaceuticals", "biotech", "biopharma",
        "gene therapy", "cell therapy", "rna therapeutics",
        "antibody", "oncology", "immunology",
        "thermo fisher scientific", "bristol-myers squibb",
        "mckesson", "cardinal health", "cencora",
        "zoetis", "illumina", "idexx laboratories",
        "teladoc health", "life sciences",
        "diagnostics", "genomics", "genetic testing",
        "medical devices", "health care",
        # Distributors / Pharma wholesalers → Conglomerate (later stage will fall through here; but line is MatureTech first, that's fine - healthcare distributors often paired with MatureTech)
        # Agri + Animal health
        "zoetis", "corteva", "bunge", "archer daniels midland",
        "agriculture", "fertilizer", "farm equipment",
        # Media / Entertainment → Cyclical
        "walt disney", "warner bros", "fox corp",
        "news corp", "liberty broadband",
        # Chinese tech / e-commerce → MatureTech
        "sea limited", "jd.com", "baidu", "pinduoduo",
        "bilibili", "tencent", "alibaba",
        # Defense industrials → Conglomerate (already partial)
        "huntington ingalls",
        # Semiconductor extra
        "viasat", "lumentum", "coherent",
        # Vodafone / telecoms → Utilities (already handled by "communications" trigger above in Utilities; keep for safety)
        "vodafone group", "orange", "deutsche telekom",
        # Misc CPG / food distribution → Conglomerate
        "sysco corporation", "tyson foods",
        "hormel foods", "mccormick & company",
        "diageo plc", "nomad foods", "flowers foods",
        "campbell soup", "hain celestial", "ethan allen interiors",
        # Insurance catch-ups already in INSURANCE rule — keeping here for doc purposes only
        # MedTech
        "medtronic", "johnson & johnson medtech", "abbott laboratories",
        "boston scientific", "edwards lifesciences",
        "intuitive surgical", "stryker corp", "zimmer biomet",
        "dexcom", "abridge", "masimo corp", "align technology",
        # Healthcare services / providers (non-REIT)
        "unitedhealth", "cigna group", "elevance health",
        "centene corp", "molina healthcare", "humana inc",
        "hca healthcare", "tenet healthcare", "community health",
        "universal health services", "davita",
        "lab corp", "quest diagnostics",
        "steris plc", "west pharmaceutical",
        "syndax pharmaceuticals", "bridgebio pharma",
        "eagle pharmaceuticals", "ascendis pharma",
    ]),
    # --- SaaS: keyword late catch (rules already high in order) ---
    (BusinessType.SAAS, [
        "zoom communications", "datadog", "mongo", "atlassian",
        "workday", "salesforce", "servicenow", "shopify",
        "coupa software", "procurement software",
        "docuSign", "digital signature",
        "twilio", "bandwidth", "8x8 inc",
        "snowflake inc", "confluent", "databricks",
        "hubspot inc", "martech", "crm software",
        "zendesk", "freshworks", "kanzhun", "recruit tech",
        "okta inc", "onfido", "cyberark",
        "crowdstrike's", "sentinelone",
    ]),
]


def _name_deep_rules(name: str) -> Optional[BusinessType]:
    if not name:
        return None
    nm = name.lower()
    # exact ticker-like synthetic names that are gibberish → skip
    if ("synthetic demo" in nm or len(nm.strip()) <= 10) and nm == nm.upper():
        return None
    for bt, kws in _NAME_RULES:
        for kw in kws:
            if kw.lower() in nm:
                return bt
    return None


def main() -> int:
    if not CSV_PATH.exists():
        print(f"ERROR: CSV not found: {CSV_PATH}")
        return 1

    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("ERROR: CSV is empty.")
        return 1

    total = len(rows)
    sources = Counter()
    label_counts = Counter()
    unknown_rows: List[Dict[str, str]] = []

    for row in rows:
        label, src = _label_one(row)
        if label is None:
            label = BusinessType.UNKNOWN
            src = "unresolved→Unknown"
        # If label already filled by hand, don't overwrite (idempotent)
        existing = (row.get("label") or "").strip()
        if existing and existing != BusinessType.UNKNOWN.value:
            # validate it maps to a real BT
            try:
                _ = BusinessType(existing)
                label_value = existing
                src = "manual-existing"
            except ValueError:
                label_value = label.value
        else:
            label_value = label.value
            row["label"] = label_value
        label_counts[label_value] += 1
        sources[src] += 1
        if label_value == BusinessType.UNKNOWN.value and src != "synthetic-fallback":
            unknown_rows.append(row)

    # Write back IN-PLACE
    fieldnames = list(rows[0].keys())
    tmp = CSV_PATH.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(CSV_PATH)

    # Report
    print("\n" + "=" * 72)
    print(f"Semi-auto label report for {CSV_PATH.name} (n={total})")
    print("=" * 72)
    print("\n--- Label distribution ---")
    for k, v in label_counts.most_common():
        pct = 100.0 * v / total
        bar = "█" * int(pct / 2.5)
        print(f"  {k:<20s} {v:>5d}  {pct:5.1f}%  {bar}")
    print(f"\n--- Reason source distribution ---")
    for k, v in sources.most_common():
        print(f"  {k:<24s} {v:>5d}  ({100.0*v/total:.1f}%)")

    n_unknown_real = len(unknown_rows)
    synth_unknown = sources.get("synthetic-fallback", 0)
    print(f"\n--- Remaining manual review ({n_unknown_real} rows, "
          f"excludes {synth_unknown} synthetic-unknown rows) ---")
    if unknown_rows:
        for r in unknown_rows[:80]:
            print(f"  {r['ticker']:<8s}  {r.get('company_name','')[:50]:<50s}  "
                  f"{r.get('sector','') or 'N/A':<30s}  {r.get('industry','') or 'N/A':<30s}")
        if len(unknown_rows) > 80:
            print(f"  ... +{len(unknown_rows) - 80} more rows "
                  f"(see {CSV_PATH.name} filter by label=Unknown)")

    prefilled = total - n_unknown_real - synth_unknown
    print(f"\n✅ Pre-filled {prefilled}/{total} rows automatically "
          f"({100.0*prefilled/total:.1f}%). "
          f"Remaining manual review: {n_unknown_real} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
