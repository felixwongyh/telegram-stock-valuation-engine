"""
classification/ml_classifier.py - ML-Enhanced Business Classifier (Item #14)

LightGBM multi-class model trained on 1000+ labeled companies (synthetic archetypes
with realistic perturbations; pluggable for real labeled data).

Features (input-side):
  - Numerical: 3Y margin volatility, D/E, Beta, revenue size (log),
    revenue CAGR, gross margin, operating margin, FCF margin,
    capex/revenue, interest/revenue, P/E, P/B, EV/EBITDA.
  - Textual: TF-IDF on (name + sector + industry) w/ domain keyword vocabulary.

Output:
  - Full probability distribution across all 11 BusinessTypes.
  - Top-2 candidates (label + probability).
  - If ML confidence (top prob) < ML_FALLBACK_THRESHOLD, OR LightGBM import
    fails / model unavailable, fallback to deterministic BusinessClassifier
    rules (already proven ~85% accurate on typical cases).

Goal: improve edge-case accuracy (e.g. high-margin semiconductor vs REIT-like
margin profile) from ~85% -> ~97% with probability-calibrated output.
"""
from __future__ import annotations

import math
import os
import pickle
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import BusinessType, ROOT_DIR, get_logger
from data.models import CompanyProfile, FinancialData

log = get_logger("classification.ml_classifier")

ML_MODEL_DIR: Path = ROOT_DIR / "classification" / "_ml_artifacts"
ML_MODEL_DIR.mkdir(parents=True, exist_ok=True)

ML_MODEL_PATH: Path = ML_MODEL_DIR / "lgbm_multiclass_v2.pkl"
ML_VECTORIZER_PATH: Path = ML_MODEL_DIR / "tfidf_vectorizer_v2.pkl"
ML_META_PATH: Path = ML_MODEL_DIR / "train_meta_v2.pkl"

ML_FALLBACK_THRESHOLD: float = 0.40
SYNTHETIC_TRAIN_SIZE: int = 1500
SYNTHETIC_RANDOM_SEED: int = 42

# Case-B hybrid floor: a financial-led company (Top-1 is a financial type) is
# treated as a FinTech hybrid only when the Technology exposure reaches this
# floor. SOFI sits at 5.5% — below the floor — because a missing provider
# sector/industry down-weights the text features (DATA-DRIVEN), not because the
# rule is wrong. The correct fix is a feature task (impute sector/industry),
# never "lower the floor until SOFI flips": lowering it perturbs the golden
# baseline. This value is locked by tests/test_hybrid_threshold_lock.py (M-16).
HYBRID_FIN_TO_TECH_FLOOR: float = 0.08

# A company spending more on capex than its own revenue while burning cash is
# running a capital-intensive build-out, not an asset-light software model.
# When the numeric ML label says SaaS/MatureTech/Media but this ratio is hit,
# the label is a prototype conflict and confidence must be deducted.
ASSET_LIGHT_CONFLICT_CAPEX_RATIO: float = 1.0
# Business types whose economics assume a light balance sheet (low capex).
ASSET_LIGHT_TYPES: frozenset = frozenset({
    BusinessType.SAAS, BusinessType.MATURE_TECH, BusinessType.MEDIA,
})

DOMAIN_KEYWORDS: List[str] = list(dict.fromkeys([
    "reit", "real estate", "property trust", "realty",
    "bank", "commercial", "savings", "investment bank", "securities",
    "insurance", "life", "property casualty", "reinsurance", "allstate", "metlife",
    "utility", "utilities", "electric", "water", "gas", "power",
    "semiconductor", "chip", "ic", "integrated circuit", "foundry", "fabless",
    "gpu", "nvidia", "memory", "processor", "qualcomm", "broadcom",
    "saas", "cloud", "software", "subscription", "platform", "enterprise",
    "technology", "hardware", "internet", "consumer", "electronics",
    "auto", "automobile", "vehicle", "retail", "store", "ecommerce",
    "travel", "hotel", "airline", "cruise", "restaurant",
    "food", "beverage", "tobacco", "grocery", "supermarket", "household",
    "oil", "petroleum", "energy", "pipeline", "midstream", "refining", "refinery",
    "mining", "metal", "steel", "coal", "commodity", "chemical", "fertilizer",
    "industrial", "construction", "machinery", "aerospace", "defense",
    "logistics", "freight", "courier", "trucking", "shipping", "warehouse",
    "conglomerate", "holding", "group", "diversified",
    "pharma", "biotech", "medical", "healthcare", "drug", "therapeutic",
    "diagnostic", "device", "life science", "hospital", "制药", "医药",
    "telecom", "telecommunication", "wireless", "cable", "broadband", "fiber",
    "media", "entertainment", "streaming", "publishing", "gaming",
    "broadcast", "television", "movie", "film", "studio",
    "fintech", "payment", "digital financial", "neobank", "nubank",
    "paypal", "square", "block", "sofi", "affirm", "upstart",
    "lending", "buy now pay later", "bnpl", "digital wallet",
    # Additional Yahoo Finance sub-industry keywords
    "mortgage", "brokerage", "capital markets", "stock exchange",
    "credit services", "financial data",
    "aerospace & defense", "general dynamics", "lockheed", "northrop",
    "raytheon", "rtx", "boeing", "caterpillar", "deere",
    "medical devices", "medical instruments", "drug manufacturers",
    "healthcare plans", "medical care facilities",
    "oil & gas", "e&p", "integrated", "equipment & services",
    "steel", "aluminum", "copper", "gold", "silver", "precious metals",
    "specialty chemicals", "agricultural inputs", "building materials",
    "packaging", "paper",
    "farm & heavy", "industrial distribution", "rental & leasing",
    "engineering & construction", "infrastructure operations",
    "marine shipping", "railroads", "waste management",
    "auto manufacturers", "auto parts", "auto dealers",
    "department stores", "apparel retail", "footwear",
    "home improvement", "internet retail", "specialty retail",
    "gambling", "lodging", "residential construction",
    "packaged foods", "confectioners", "farm products",
    "discount stores", "personal services",
    "banks - regional", "banks - diversified", "banks - savings",
    "insurance - diversified", "insurance - life", "insurance - specialty",
    "insurance brokers",
    "reit - residential", "reit - retail", "reit - office",
    "reit - hotel", "reit - mortgage", "reit - healthcare",
    "utilities - regulated", "utilities - independent power",
    "electric utilities", "gas utilities", "water utilities",
    "software - application", "software - infrastructure",
    "computer hardware", "electronic components", "electronic equipment",
    "scientific & technical instruments",
    "telecom services", "entertainment", "broadcasting",
    "interactive media", "advertising", "marketing",
]))

_TARGET_BUSINESS_TYPES: List[BusinessType] = [
    BusinessType.MATURE_TECH,
    BusinessType.SAAS,
    BusinessType.SEMICONDUCTOR,
    BusinessType.CONSUMER_CYCLICAL,
    BusinessType.CONSUMER_STAPLES,
    BusinessType.REIT,
    BusinessType.BANK,
    BusinessType.INSURANCE,
    BusinessType.FINTECH,
    BusinessType.NEOBANK,
    BusinessType.COMMODITY,
    BusinessType.UTILITIES,
    BusinessType.ENERGY,
    BusinessType.INDUSTRIAL,
    BusinessType.HEALTHCARE,
    BusinessType.TELECOM,
    BusinessType.MEDIA,
    BusinessType.CONGLOMERATE,
    BusinessType.UNKNOWN,
]

_NUM_FEATURE_NAMES: List[str] = [
    "log_revenue",
    "revenue_cagr_3y",
    "gross_margin",
    "gross_margin_vol_3y",
    "operating_margin",
    "operating_margin_vol_3y",
    "fcf_margin",
    "capex_to_revenue",
    "interest_to_revenue",
    "de_ratio",
    "beta",
    "market_cap_log",
    "pe",
    "pb",
    "ev_ebitda",
]


# ---------------------------------------------------------------------------
# Archetype profiles: each BusinessType has a centroid + std for every feature.
# These are empirically tuned; replace with real-label data averages at scale.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Archetype:
    name: str
    log_revenue: Tuple[float, float] = (10.0, 1.2)
    revenue_cagr_3y: Tuple[float, float] = (0.08, 0.06)
    gross_margin: Tuple[float, float] = (0.40, 0.12)
    gross_margin_vol_3y: Tuple[float, float] = (0.08, 0.04)
    operating_margin: Tuple[float, float] = (0.18, 0.08)
    operating_margin_vol_3y: Tuple[float, float] = (0.10, 0.06)
    fcf_margin: Tuple[float, float] = (0.10, 0.08)
    capex_to_revenue: Tuple[float, float] = (0.06, 0.04)
    interest_to_revenue: Tuple[float, float] = (0.03, 0.02)
    de_ratio: Tuple[float, float] = (1.0, 0.8)
    beta: Tuple[float, float] = (1.1, 0.35)
    market_cap_log: Tuple[float, float] = (10.0, 1.5)
    pe: Tuple[float, float] = (22.0, 10.0)
    pb: Tuple[float, float] = (4.0, 3.0)
    ev_ebitda: Tuple[float, float] = (14.0, 7.0)
    keywords: Tuple[str, ...] = ()


def _sample(rng: random.Random, mu_sigma: Tuple[float, float], clip: Optional[Tuple[float, float]] = None) -> float:
    mu, sd = mu_sigma
    v = rng.gauss(mu, sd)
    if clip is not None:
        v = max(clip[0], min(clip[1], v))
    return v


_ARCHETYPES: Dict[BusinessType, Archetype] = {
    BusinessType.MATURE_TECH: Archetype(
        name="MatureTech",
        log_revenue=(11.5, 0.9),
        revenue_cagr_3y=(0.07, 0.05),
        gross_margin=(0.55, 0.10),
        operating_margin=(0.28, 0.07),
        operating_margin_vol_3y=(0.06, 0.03),
        fcf_margin=(0.20, 0.06),
        capex_to_revenue=(0.05, 0.02),
        interest_to_revenue=(0.02, 0.015),
        de_ratio=(0.8, 0.5),
        beta=(1.15, 0.25),
        market_cap_log=(12.5, 1.0),
        pe=(26.0, 8.0),
        pb=(8.0, 5.0),
        ev_ebitda=(18.0, 6.0),
        keywords=("technology", "software", "hardware", "internet", "consumer electronics"),
    ),
    BusinessType.SAAS: Archetype(
        name="SaaS",
        log_revenue=(8.5, 1.0),
        revenue_cagr_3y=(0.25, 0.12),
        gross_margin=(0.72, 0.08),
        gross_margin_vol_3y=(0.05, 0.02),
        operating_margin=(0.05, 0.12),
        operating_margin_vol_3y=(0.20, 0.15),
        fcf_margin=(0.15, 0.10),
        capex_to_revenue=(0.03, 0.015),
        interest_to_revenue=(0.02, 0.015),
        de_ratio=(0.4, 0.4),
        beta=(1.3, 0.3),
        market_cap_log=(10.0, 1.6),
        pe=(60.0, 40.0),
        pb=(20.0, 14.0),
        ev_ebitda=(35.0, 20.0),
        keywords=("saas", "cloud", "software", "platform", "subscription", "enterprise"),
    ),
    BusinessType.SEMICONDUCTOR: Archetype(
        name="Semiconductor",
        log_revenue=(9.0, 1.1),
        revenue_cagr_3y=(0.15, 0.18),
        gross_margin=(0.50, 0.16),
        gross_margin_vol_3y=(0.20, 0.10),
        operating_margin=(0.30, 0.14),
        operating_margin_vol_3y=(0.28, 0.14),
        fcf_margin=(0.18, 0.12),
        capex_to_revenue=(0.14, 0.08),
        interest_to_revenue=(0.02, 0.015),
        de_ratio=(0.3, 0.3),
        beta=(1.6, 0.35),
        market_cap_log=(11.0, 1.8),
        pe=(35.0, 22.0),
        pb=(12.0, 9.0),
        ev_ebitda=(22.0, 14.0),
        keywords=("semiconductor", "chip", "gpu", "nvidia", "foundry", "memory", "processor"),
    ),
    BusinessType.CONSUMER_CYCLICAL: Archetype(
        name="ConsumerCyclical",
        log_revenue=(10.0, 1.2),
        revenue_cagr_3y=(0.05, 0.08),
        gross_margin=(0.32, 0.12),
        operating_margin=(0.10, 0.06),
        operating_margin_vol_3y=(0.18, 0.10),
        fcf_margin=(0.05, 0.06),
        capex_to_revenue=(0.05, 0.03),
        interest_to_revenue=(0.03, 0.02),
        de_ratio=(1.0, 0.8),
        beta=(1.3, 0.35),
        market_cap_log=(10.5, 1.6),
        pe=(18.0, 8.0),
        pb=(3.5, 2.0),
        ev_ebitda=(11.0, 5.0),
        keywords=("auto", "retail", "travel", "hotel", "airline", "consumer"),
    ),
    BusinessType.CONSUMER_STAPLES: Archetype(
        name="ConsumerStaples",
        log_revenue=(10.5, 1.2),
        revenue_cagr_3y=(0.04, 0.03),
        gross_margin=(0.40, 0.10),
        gross_margin_vol_3y=(0.04, 0.02),
        operating_margin=(0.15, 0.05),
        operating_margin_vol_3y=(0.06, 0.03),
        fcf_margin=(0.10, 0.05),
        capex_to_revenue=(0.05, 0.02),
        interest_to_revenue=(0.03, 0.015),
        de_ratio=(1.2, 0.8),
        beta=(0.65, 0.20),
        market_cap_log=(11.0, 1.2),
        pe=(22.0, 8.0),
        pb=(5.0, 3.0),
        ev_ebitda=(16.0, 5.0),
        keywords=(
            "food", "beverage", "tobacco", "grocery", "supermarket", "household",
            "coca cola", "pepsi", "procter", "unilever", "colgate",
            "kraft", "general mills", "tyson", "sysco",
            "altria", "philip morris", "british american tobacco",
            "costco", "walmart", "target", "kroger", "dollar",
            "diageo", "anheuser", "nestle", "mondelez",
        ),
    ),
    BusinessType.REIT: Archetype(
        name="REIT",
        log_revenue=(9.0, 0.8),
        revenue_cagr_3y=(0.06, 0.05),
        gross_margin=(0.75, 0.08),
        gross_margin_vol_3y=(0.04, 0.02),
        operating_margin=(0.55, 0.10),
        operating_margin_vol_3y=(0.05, 0.03),
        fcf_margin=(0.20, 0.06),
        capex_to_revenue=(0.22, 0.06),
        interest_to_revenue=(0.18, 0.06),
        de_ratio=(2.8, 1.0),
        beta=(0.85, 0.25),
        market_cap_log=(10.0, 1.0),
        pe=(28.0, 10.0),
        pb=(3.0, 1.5),
        ev_ebitda=(22.0, 6.0),
        keywords=("reit", "real estate", "property trust"),
    ),
    BusinessType.BANK: Archetype(
        name="Bank",
        log_revenue=(11.0, 1.0),
        revenue_cagr_3y=(0.05, 0.05),
        gross_margin=(0.85, 0.08),
        gross_margin_vol_3y=(0.04, 0.02),
        operating_margin=(0.42, 0.08),
        operating_margin_vol_3y=(0.08, 0.04),
        fcf_margin=(0.30, 0.10),
        capex_to_revenue=(0.025, 0.012),
        interest_to_revenue=(0.48, 0.10),
        de_ratio=(7.0, 2.0),
        beta=(1.1, 0.25),
        market_cap_log=(11.5, 1.0),
        pe=(12.0, 4.0),
        pb=(1.3, 0.4),
        ev_ebitda=(0.0, 0.0),
        keywords=("bank", "commercial", "savings", "investment bank", "securities"),
    ),
    BusinessType.INSURANCE: Archetype(
        name="Insurance",
        log_revenue=(10.8, 1.0),
        revenue_cagr_3y=(0.05, 0.04),
        gross_margin=(0.55, 0.15),
        operating_margin=(0.12, 0.06),
        fcf_margin=(0.08, 0.05),
        capex_to_revenue=(0.02, 0.01),
        interest_to_revenue=(0.22, 0.08),
        de_ratio=(5.0, 2.0),
        beta=(0.95, 0.25),
        market_cap_log=(11.0, 1.0),
        pe=(13.0, 4.0),
        pb=(1.5, 0.6),
        ev_ebitda=(0.0, 0.0),
        keywords=("insurance", "life", "property casualty"),
    ),
    BusinessType.COMMODITY: Archetype(
        name="Commodity",
        log_revenue=(10.0, 1.2),
        revenue_cagr_3y=(0.03, 0.15),
        gross_margin=(0.25, 0.12),
        gross_margin_vol_3y=(0.25, 0.15),
        operating_margin=(0.12, 0.10),
        operating_margin_vol_3y=(0.35, 0.18),
        fcf_margin=(0.06, 0.09),
        capex_to_revenue=(0.10, 0.05),
        interest_to_revenue=(0.04, 0.02),
        de_ratio=(1.2, 0.8),
        beta=(1.35, 0.4),
        market_cap_log=(10.2, 1.5),
        pe=(12.0, 6.0),
        pb=(1.6, 0.8),
        ev_ebitda=(6.5, 3.0),
        keywords=("oil", "gas", "mining", "metal", "steel", "coal", "petroleum"),
    ),
    BusinessType.UTILITIES: Archetype(
        name="Utilities",
        log_revenue=(10.0, 0.8),
        revenue_cagr_3y=(0.04, 0.03),
        gross_margin=(0.35, 0.08),
        gross_margin_vol_3y=(0.04, 0.02),
        operating_margin=(0.20, 0.05),
        operating_margin_vol_3y=(0.05, 0.02),
        fcf_margin=(0.06, 0.04),
        capex_to_revenue=(0.15, 0.05),
        interest_to_revenue=(0.14, 0.04),
        de_ratio=(2.5, 0.9),
        beta=(0.55, 0.15),
        market_cap_log=(10.3, 0.8),
        pe=(19.0, 4.0),
        pb=(2.2, 0.6),
        ev_ebitda=(11.0, 2.5),
        keywords=("utility", "utilities", "electric", "power", "water", "gas"),
    ),
    BusinessType.CONGLOMERATE: Archetype(
        name="Conglomerate",
        log_revenue=(10.8, 1.0),
        revenue_cagr_3y=(0.05, 0.05),
        gross_margin=(0.30, 0.10),
        operating_margin=(0.13, 0.05),
        fcf_margin=(0.07, 0.05),
        capex_to_revenue=(0.06, 0.03),
        interest_to_revenue=(0.05, 0.02),
        de_ratio=(1.2, 0.6),
        beta=(1.05, 0.25),
        market_cap_log=(11.0, 1.0),
        pe=(17.0, 5.0),
        pb=(2.2, 1.0),
        ev_ebitda=(10.0, 3.5),
        keywords=("conglomerate", "holding", "group"),
    ),
    BusinessType.FINTECH: Archetype(
        name="FinTech",
        log_revenue=(9.5, 1.3),
        revenue_cagr_3y=(0.28, 0.16),
        gross_margin=(0.60, 0.18),
        gross_margin_vol_3y=(0.07, 0.04),
        operating_margin=(0.08, 0.16),
        operating_margin_vol_3y=(0.25, 0.18),
        fcf_margin=(-0.02, 0.14),
        capex_to_revenue=(0.06, 0.03),
        interest_to_revenue=(0.14, 0.08),
        de_ratio=(1.6, 1.2),
        beta=(1.25, 0.30),
        market_cap_log=(10.5, 1.8),
        pe=(38.0, 20.0),
        pb=(6.0, 3.5),
        ev_ebitda=(22.0, 12.0),
        keywords=(
            "fintech", "payment", "digital financial", "technology platform", "financial technology",
            "lending platform", "insurance tech", "insurtech", "payments network",
            "digital wallet", "blockchain", "neobank", "nu holdings", "nubank",
            "sofi", "block", "square", "paypal", "stripe", "affirm", "upstart",
            "dave inc", "dave", "cash advance", "personal loan", "banking app",
            "buy now pay later", "bnpl", "credit builder", "earned wage access",
        ),
    ),
    BusinessType.NEOBANK: Archetype(
        name="Neobank",
        log_revenue=(9.2, 1.1),
        revenue_cagr_3y=(0.35, 0.20),
        gross_margin=(0.78, 0.10),
        gross_margin_vol_3y=(0.05, 0.03),
        operating_margin=(0.04, 0.20),
        operating_margin_vol_3y=(0.30, 0.20),
        fcf_margin=(-0.05, 0.12),
        capex_to_revenue=(0.04, 0.02),
        interest_to_revenue=(0.30, 0.12),
        de_ratio=(4.0, 2.5),
        beta=(1.30, 0.35),
        market_cap_log=(9.8, 1.6),
        pe=(45.0, 25.0),
        pb=(3.5, 2.0),
        ev_ebitda=(0.0, 0.0),
        keywords=(
            "neobank", "digital bank", "challenger bank", "online banking", "mobile banking",
            "nubank", "nu holdings", "revolut", "chime", "monzo", "starling", "ally",
            "discover", "sofi bank", "current", "varo",
            "dave", "dave inc", "wise",
        ),
    ),
    BusinessType.ENERGY: Archetype(
        name="Energy",
        log_revenue=(10.5, 1.3),
        revenue_cagr_3y=(0.05, 0.08),
        gross_margin=(0.35, 0.15),
        gross_margin_vol_3y=(0.20, 0.12),
        operating_margin=(0.15, 0.10),
        operating_margin_vol_3y=(0.25, 0.15),
        fcf_margin=(0.08, 0.06),
        capex_to_revenue=(0.15, 0.06),
        interest_to_revenue=(0.04, 0.02),
        de_ratio=(1.0, 0.6),
        beta=(1.2, 0.4),
        market_cap_log=(11.0, 1.3),
        pe=(12.0, 6.0),
        pb=(2.0, 1.0),
        ev_ebitda=(6.5, 3.0),
        keywords=(
            "oil", "petroleum", "energy", "pipeline", "midstream", "refining",
            "exxon", "chevron", "shell", "conoco", "occidental",
            "energy transfer", "kinder morgan", "williams", "enterprise products",
            "targa resources", "enbridge",
            "valero", "marathon petroleum", "phillips 66",
            "halliburton", "schlumberger",
        ),
    ),
    BusinessType.INDUSTRIAL: Archetype(
        name="Industrial",
        log_revenue=(10.0, 1.2),
        revenue_cagr_3y=(0.05, 0.05),
        gross_margin=(0.35, 0.10),
        gross_margin_vol_3y=(0.08, 0.04),
        operating_margin=(0.15, 0.06),
        operating_margin_vol_3y=(0.10, 0.05),
        fcf_margin=(0.10, 0.05),
        capex_to_revenue=(0.06, 0.03),
        interest_to_revenue=(0.03, 0.015),
        de_ratio=(1.0, 0.7),
        beta=(1.1, 0.3),
        market_cap_log=(10.8, 1.2),
        pe=(20.0, 8.0),
        pb=(4.0, 2.0),
        ev_ebitda=(14.0, 5.0),
        keywords=(
            "industrial", "construction", "machinery", "aerospace", "defense",
            "logistics", "freight", "courier", "trucking", "shipping", "warehouse",
            "boeing", "lockheed martin", "general dynamics", "northrop",
            "raytheon", "rtx", "l3harris", "huntington ingalls",
            "honeywell", "3m", "eaton", "emerson", "rockwell", "cummins",
            "fastenal", "quanta services", "caterpillar",
            "fedex", "ups", "united parcel",
        ),
    ),
    BusinessType.TELECOM: Archetype(
        name="Telecom",
        log_revenue=(10.5, 1.0),
        revenue_cagr_3y=(0.02, 0.03),
        gross_margin=(0.55, 0.10),
        gross_margin_vol_3y=(0.04, 0.02),
        operating_margin=(0.25, 0.06),
        operating_margin_vol_3y=(0.05, 0.02),
        fcf_margin=(0.15, 0.05),
        capex_to_revenue=(0.15, 0.04),
        interest_to_revenue=(0.06, 0.02),
        de_ratio=(2.0, 0.8),
        beta=(0.75, 0.20),
        market_cap_log=(11.0, 1.0),
        pe=(16.0, 5.0),
        pb=(2.5, 1.0),
        ev_ebitda=(8.0, 3.0),
        keywords=(
            "telecom", "telecommunication", "wireless", "cable", "broadband", "fiber",
            "at&t", "verizon", "t-mobile", "tmus",
            "charter communications", "comcast",
            "vodafone", "telus", "rogers", "bell canada",
            "american tower", "sba communications", "crown castle",
            "cell tower", "tower",
        ),
    ),
    BusinessType.MEDIA: Archetype(
        name="Media",
        log_revenue=(9.5, 1.2),
        revenue_cagr_3y=(0.08, 0.06),
        gross_margin=(0.45, 0.12),
        gross_margin_vol_3y=(0.08, 0.04),
        operating_margin=(0.18, 0.10),
        operating_margin_vol_3y=(0.12, 0.06),
        fcf_margin=(0.12, 0.06),
        capex_to_revenue=(0.04, 0.02),
        interest_to_revenue=(0.04, 0.02),
        de_ratio=(0.8, 0.5),
        beta=(1.1, 0.25),
        market_cap_log=(10.5, 1.3),
        pe=(22.0, 12.0),
        pb=(4.0, 2.5),
        ev_ebitda=(14.0, 6.0),
        keywords=(
            "media", "entertainment", "streaming", "publishing", "gaming",
            "broadcast", "television", "movie", "film", "studio",
            "disney", "warner", "netflix", "fox", "news corp",
            "spotify", "take-two", "electronic arts",
            "activision", "roblox", "paramount", "imax",
        ),
    ),
    BusinessType.HEALTHCARE: Archetype(
        name="Healthcare",
        log_revenue=(10.5, 1.2),
        revenue_cagr_3y=(0.06, 0.06),
        gross_margin=(0.65, 0.12),
        gross_margin_vol_3y=(0.06, 0.03),
        operating_margin=(0.25, 0.08),
        operating_margin_vol_3y=(0.08, 0.04),
        fcf_margin=(0.18, 0.08),
        capex_to_revenue=(0.07, 0.03),
        interest_to_revenue=(0.03, 0.02),
        de_ratio=(0.6, 0.5),
        beta=(0.85, 0.25),
        market_cap_log=(11.0, 1.2),
        pe=(24.0, 10.0),
        pb=(5.0, 3.0),
        ev_ebitda=(17.0, 7.0),
        keywords=(
            "pharma", "pharmaceutical", "biotech", "biotechnology", "medical",
            "medical device", "healthcare", "health", "drug", "therapeutic",
            "diagnostic", "life science", "biopharm",
            "j&j", "johnson & johnson", "unitedhealth", "pfizer", "merck",
            "novartis", "roche", "abbvie", "eli lilly", "bristol",
            "medtronic", "teladoc", "regeneron", "vertex",
        ),
    ),
    BusinessType.UNKNOWN: Archetype(
        name="Unknown",
        log_revenue=(8.0, 1.5),
        revenue_cagr_3y=(0.0, 0.20),
        gross_margin=(0.25, 0.20),
        gross_margin_vol_3y=(0.20, 0.15),
        operating_margin=(0.0, 0.15),
        operating_margin_vol_3y=(0.30, 0.20),
        fcf_margin=(0.0, 0.15),
        capex_to_revenue=(0.08, 0.08),
        interest_to_revenue=(0.05, 0.05),
        de_ratio=(1.5, 1.5),
        beta=(1.2, 0.6),
        market_cap_log=(8.0, 2.0),
        pe=(25.0, 25.0),
        pb=(3.0, 3.0),
        ev_ebitda=(15.0, 15.0),
        keywords=(),
    ),
}


# ===========================================================================
# Feature Engineering
# ===========================================================================
def _safe_div(a: Optional[float], b: Optional[float], default: float = 0.0) -> float:
    if a is None or b is None or b == 0 or not math.isfinite(a) or not math.isfinite(b):
        return default
    return float(a) / float(b)


def extract_numerical_features(data: FinancialData) -> Dict[str, float]:
    """Extract 15 numerical features from FinancialData (robust to missing)."""
    out: Dict[str, float] = {f: 0.0 for f in _NUM_FEATURE_NAMES}

    ttm = data.ttm
    annuals = data.annual_income
    mkt = data.market

    rev_ttm = ttm.revenue if ttm and ttm.revenue is not None else (annuals[0].revenue if annuals else None)
    if rev_ttm is not None and rev_ttm > 0:
        out["log_revenue"] = math.log10(rev_ttm)
    else:
        out["log_revenue"] = 0.0

    if len(annuals) >= 2:
        latest = annuals[0].revenue
        oldest = annuals[min(2, len(annuals) - 1)].revenue
        if latest and oldest and oldest > 0:
            n = min(2, len(annuals) - 1)
            cagr = (latest / oldest) ** (1.0 / max(1, n)) - 1.0
            out["revenue_cagr_3y"] = max(-0.5, min(1.5, float(cagr)))

    gm_latest = 0.0
    if rev_ttm and ttm and ttm.gross_profit is not None:
        gm_latest = ttm.gross_profit / rev_ttm
    elif rev_ttm and annuals and annuals[0].gross_profit is not None:
        gm_latest = annuals[0].gross_profit / rev_ttm
    out["gross_margin"] = max(-0.5, min(1.0, float(gm_latest)))

    gm_series: List[float] = []
    for stmt in annuals[:3]:
        if stmt.revenue and stmt.revenue > 0 and stmt.gross_profit is not None:
            gm_series.append(stmt.gross_profit / stmt.revenue)
    if len(gm_series) >= 2:
        mu = sum(gm_series) / len(gm_series)
        var = sum((x - mu) ** 2 for x in gm_series) / len(gm_series)
        vol = math.sqrt(var) / abs(mu) if abs(mu) > 1e-6 else 0.0
        out["gross_margin_vol_3y"] = max(0.0, min(2.0, float(vol)))

    om_latest = 0.0
    if rev_ttm and ttm and ttm.operating_income is not None:
        om_latest = ttm.operating_income / rev_ttm
    elif rev_ttm and annuals and annuals[0].operating_income is not None:
        om_latest = annuals[0].operating_income / rev_ttm
    out["operating_margin"] = max(-1.0, min(1.0, float(om_latest)))

    om_series: List[float] = []
    for stmt in annuals[:3]:
        if stmt.revenue and stmt.revenue > 0 and stmt.operating_income is not None:
            om_series.append(stmt.operating_income / stmt.revenue)
    if len(om_series) >= 2:
        mu = sum(om_series) / len(om_series)
        var = sum((x - mu) ** 2 for x in om_series) / len(om_series)
        vol = math.sqrt(var) / abs(mu) if abs(mu) > 1e-6 else 0.0
        out["operating_margin_vol_3y"] = max(0.0, min(3.0, float(vol)))

    if rev_ttm and ttm and ttm.free_cash_flow is not None:
        out["fcf_margin"] = max(-1.0, min(1.0, float(ttm.free_cash_flow / rev_ttm)))
    elif rev_ttm and annuals and annuals[0].free_cash_flow is not None:
        out["fcf_margin"] = max(-1.0, min(1.0, float(annuals[0].free_cash_flow / rev_ttm)))

    if rev_ttm and ttm and ttm.capex is not None:
        out["capex_to_revenue"] = max(0.0, min(1.0, float(abs(ttm.capex) / rev_ttm)))

    if rev_ttm and ttm and ttm.interest_expense is not None:
        out["interest_to_revenue"] = max(0.0, min(2.0, float(ttm.interest_expense / rev_ttm)))

    if mkt.total_debt is not None and mkt.book_value and mkt.book_value > 0:
        out["de_ratio"] = max(0.0, min(20.0, float(mkt.total_debt / mkt.book_value)))

    if mkt.beta is not None:
        out["beta"] = max(-2.0, min(5.0, float(mkt.beta)))

    if mkt.market_cap is not None and mkt.market_cap > 0:
        out["market_cap_log"] = math.log10(mkt.market_cap)

    if mkt.trailing_pe is not None and mkt.trailing_pe > 0:
        out["pe"] = min(200.0, float(mkt.trailing_pe))

    if mkt.price_to_book is not None and mkt.price_to_book > 0:
        out["pb"] = min(100.0, float(mkt.price_to_book))

    if mkt.ev_to_ebitda is not None and mkt.ev_to_ebitda > 0:
        out["ev_ebitda"] = min(100.0, float(mkt.ev_to_ebitda))

    return out


def build_text_corpus(data: FinancialData) -> str:
    sector = data.market.sector or ""
    industry = data.market.industry or ""
    name = data.market.company_name or ""
    ticker = data.ticker or ""
    # Normalize: lowercase, replace hyphens with spaces for keyword matching
    # (e.g. "Coca-Cola" -> "coca cola" so keyword "coca cola" matches)
    text = f"{name} {sector} {industry} {ticker}".lower()
    text = text.replace("-", " ").replace(".", " ").replace(",", " ")
    return text


_BOUNDED_KW_RE: Dict[str, "re.Pattern[str]"] = {}


def keyword_hit(text: str, keyword: str) -> bool:
    """Keyword match that is safe for short, ambiguous brand/ticker tokens.

    Plain substring matching makes short tokens collide with longer words
    ("ups" inside "upstart", "amt" inside "amount", "iron" inside "environment").
    For *bare* ASCII tokens of <= 4 chars we require word boundaries; everything
    else keeps the original substring semantics so legitimate plural/inflected
    forms still match (e.g. "industrial" -> "industrials", "metal" -> "metals").
    Tokens with deliberate leading/trailing spaces (e.g. " logistics") and
    non-ASCII (CJK) keywords keep plain substring matching on purpose.
    """
    if keyword != keyword.strip() or not keyword.isascii():
        return keyword in text
    if len(keyword) > 4:
        return keyword in text
    pat = _BOUNDED_KW_RE.get(keyword)
    if pat is None:
        pat = re.compile(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])")
        _BOUNDED_KW_RE[keyword] = pat
    return pat.search(text) is not None


# ===========================================================================
# Synthetic Training Set Builder (1500 labeled samples)
# ===========================================================================
def _generate_text_from_keywords(rng: random.Random, arch: Archetype) -> str:
    parts: List[str] = []
    if arch.keywords:
        k = min(len(arch.keywords), rng.randint(1, 3))
        parts.extend(rng.sample(list(arch.keywords), k))
    if rng.random() < 0.4:
        generic = rng.choice(["inc.", "corp.", "holdings", "group", "international", "co.", "ltd."])
        parts.append(generic)
    if rng.random() < 0.3:
        extra = rng.choice(DOMAIN_KEYWORDS[:15])
        if extra not in parts:
            parts.append(extra)
    rng.shuffle(parts)
    return " ".join(parts)


def build_synthetic_training_set(n_total: int = SYNTHETIC_TRAIN_SIZE,
                                  seed: int = SYNTHETIC_RANDOM_SEED
                                  ) -> Tuple[List[Dict[str, float]], List[str], List[str]]:
    """Build synthetic training set with balanced classes (plus Unknown tail)."""
    rng = random.Random(seed)
    bts = [b for b in _TARGET_BUSINESS_TYPES if b != BusinessType.UNKNOWN]
    per_class = n_total // (len(bts) + 1)
    n_unknown = n_total - per_class * len(bts)

    X_num: List[Dict[str, float]] = []
    X_text: List[str] = []
    y: List[str] = []

    for bt in bts:
        arch = _ARCHETYPES[bt]
        for _ in range(per_class):
            feat = {
                "log_revenue": _sample(rng, arch.log_revenue),
                "revenue_cagr_3y": _sample(rng, arch.revenue_cagr_3y, (-0.3, 1.0)),
                "gross_margin": _sample(rng, arch.gross_margin, (0.0, 1.0)),
                "gross_margin_vol_3y": max(0.0, _sample(rng, arch.gross_margin_vol_3y, (0.0, 2.0))),
                "operating_margin": _sample(rng, arch.operating_margin, (-0.5, 0.8)),
                "operating_margin_vol_3y": max(0.0, _sample(rng, arch.operating_margin_vol_3y, (0.0, 3.0))),
                "fcf_margin": _sample(rng, arch.fcf_margin, (-0.5, 0.6)),
                "capex_to_revenue": max(0.0, _sample(rng, arch.capex_to_revenue, (0.0, 0.5))),
                "interest_to_revenue": max(0.0, _sample(rng, arch.interest_to_revenue, (0.0, 2.0))),
                "de_ratio": max(0.0, _sample(rng, arch.de_ratio, (0.0, 20.0))),
                "beta": _sample(rng, arch.beta, (-2.0, 5.0)),
                "market_cap_log": _sample(rng, arch.market_cap_log),
                "pe": max(1.0, _sample(rng, arch.pe, (1.0, 200.0))),
                "pb": max(0.1, _sample(rng, arch.pb, (0.1, 100.0))),
                "ev_ebitda": max(0.1, _sample(rng, arch.ev_ebitda, (0.1, 100.0))),
            }
            X_num.append(feat)
            X_text.append(_generate_text_from_keywords(rng, arch))
            y.append(bt.value)

    arch_u = _ARCHETYPES[BusinessType.UNKNOWN]
    for _ in range(n_unknown):
        src_bt = rng.choice(bts)
        arch = _ARCHETYPES[src_bt]
        feat = {
            "log_revenue": _sample(rng, arch_u.log_revenue),
            "revenue_cagr_3y": _sample(rng, arch_u.revenue_cagr_3y, (-0.5, 1.0)),
            "gross_margin": _sample(rng, arch_u.gross_margin, (0.0, 1.0)),
            "gross_margin_vol_3y": max(0.0, _sample(rng, arch_u.gross_margin_vol_3y, (0.0, 2.0))),
            "operating_margin": _sample(rng, arch_u.operating_margin, (-0.8, 0.8)),
            "operating_margin_vol_3y": max(0.0, _sample(rng, arch_u.operating_margin_vol_3y, (0.0, 3.0))),
            "fcf_margin": _sample(rng, arch_u.fcf_margin, (-0.8, 0.6)),
            "capex_to_revenue": max(0.0, _sample(rng, arch_u.capex_to_revenue, (0.0, 0.5))),
            "interest_to_revenue": max(0.0, _sample(rng, arch_u.interest_to_revenue, (0.0, 2.0))),
            "de_ratio": max(0.0, _sample(rng, arch_u.de_ratio, (0.0, 20.0))),
            "beta": _sample(rng, arch_u.beta, (-2.0, 5.0)),
            "market_cap_log": _sample(rng, arch_u.market_cap_log),
            "pe": max(1.0, _sample(rng, arch_u.pe, (1.0, 200.0))),
            "pb": max(0.1, _sample(rng, arch_u.pb, (0.1, 100.0))),
            "ev_ebitda": max(0.1, _sample(rng, arch_u.ev_ebitda, (0.1, 100.0))),
        }
        X_num.append(feat)
        pool = DOMAIN_KEYWORDS + [f"generic{i}" for i in range(20)]
        k = rng.randint(0, 2)
        parts = rng.sample(pool, k) if k else []
        rng.shuffle(parts)
        X_text.append(" ".join(parts))
        y.append(BusinessType.UNKNOWN.value)

    return X_num, X_text, y


# ===========================================================================
# Real Labeled CSV Import Interface (Phase 3 — when 1000+ manual labels ready)
# ===========================================================================
CSV_REQUIRED_COLUMNS: Tuple[str, ...] = (
    "ticker", "label",  # label must be one of BusinessType values
)
CSV_NUMERICAL_COLUMNS: Tuple[str, ...] = tuple(_NUM_FEATURE_NAMES)
CSV_TEXT_COLUMNS: Tuple[str, ...] = ("company_name", "sector", "industry")


def build_training_set_from_csv(
    csv_path: os.PathLike | str,
    *,
    label_column: str = "label",
    text_columns: Tuple[str, ...] = CSV_TEXT_COLUMNS,
    numerical_default: float = 0.0,
) -> Tuple[List[Dict[str, float]], List[str], List[str]]:
    """
    Load a manually-labeled CSV and convert it into the same (X_num, X_text, y)
    tuple shape returned by build_synthetic_training_set().

    Designed as a DROP-IN REPLACEMENT for build_synthetic_training_set():
    In LightGBMBusinessClassifier._train_from_scratch, replace:
        X_num_list, X_text, y_raw = build_synthetic_training_set()
    with:
        X_num_list, X_text, y_raw = build_training_set_from_csv("path/to/labels.csv")

    Expected CSV schema (minimum 1000 rows for Phase 3):
        ticker, company_name, sector, industry,
        log_revenue, revenue_cagr_3y, gross_margin, gross_margin_vol_3y,
        operating_margin, operating_margin_vol_3y, fcf_margin, capex_to_revenue,
        interest_to_revenue, de_ratio, beta, market_cap_log, pe, pb, ev_ebitda,
        label, note

    Rules:
      * label  values MUST match BusinessType enum value strings (case-sensitive).
        Unknown/unrecognized labels are remapped to BusinessType.UNKNOWN.value.
      * Missing numerical columns filled with `numerical_default`.
      * Missing text columns are treated as empty string.
      * Rows with empty/missing `ticker` or `label` are SKIPPED with a warning.
    """
    import csv as _csv

    p = Path(csv_path)
    if not p.exists():
        raise FileNotFoundError(f"Labeled CSV not found: {p}")

    valid_labels = {b.value for b in _TARGET_BUSINESS_TYPES}

    X_num: List[Dict[str, float]] = []
    X_text: List[str] = []
    y: List[str] = []
    skipped = 0
    unknown_labels = 0

    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        reader = _csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            ticker = (row.get("ticker") or "").strip()
            label_raw = (row.get(label_column) or "").strip()
            if not ticker or not label_raw:
                skipped += 1
                log.warning(f"CSV L{i}: missing ticker or label — skipped")
                continue

            if label_raw not in valid_labels:
                unknown_labels += 1
                label = BusinessType.UNKNOWN.value
                log.warning(f"CSV L{i}: label='{label_raw}' not in BusinessType → mapped to Unknown")
            else:
                label = label_raw

            feat: Dict[str, float] = {}
            for name in _NUM_FEATURE_NAMES:
                raw = row.get(name)
                if raw is None or raw == "":
                    feat[name] = numerical_default
                else:
                    try:
                        feat[name] = float(raw)
                    except (TypeError, ValueError):
                        feat[name] = numerical_default
                        log.warning(f"CSV L{i}: col={name} not numeric → used default")
            X_num.append(feat)

            text_parts: List[str] = []
            for tc in text_columns:
                v = (row.get(tc) or "").strip()
                if v:
                    text_parts.append(v.lower())
            # Explicit ticker also goes into text (improves keyword matches when name is blank)
            text_parts.append(ticker.lower())
            X_text.append(" ".join(text_parts))

            y.append(label)

    log.info(
        f"Loaded labeled CSV: {len(y)} rows | skipped={skipped} | unknown_labels={unknown_labels} | path={p}"
    )
    if not X_num:
        raise ValueError(f"No valid rows loaded from CSV: {p}")
    return X_num, X_text, y


# ===========================================================================
# LightGBM Model Train / Predict
# ===========================================================================
@dataclass
class TrainMeta:
    version: str = "2.0-synthetic"
    n_classes: int = len(_TARGET_BUSINESS_TYPES)
    class_labels: List[str] = field(default_factory=lambda: [b.value for b in _TARGET_BUSINESS_TYPES])
    num_feature_names: List[str] = field(default_factory=lambda: list(_NUM_FEATURE_NAMES))
    n_samples_train: int = 0
    train_accuracy: float = 0.0
    fallback_threshold: float = ML_FALLBACK_THRESHOLD
    note: str = ""


class LightGBMBusinessClassifier:
    """LightGBM multi-class model with TF-IDF text features + numerical features."""

    MODEL_VERSION = "2.0.0"

    def __init__(self) -> None:
        self._model: Any = None
        self._vectorizer: Any = None
        self._selector: Any = None
        self._meta: TrainMeta = TrainMeta()
        self._label_to_idx: Dict[str, int] = {}
        self._idx_to_label: List[str] = []
        self._n_text_features: int = 0
        self._available: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._available

    def load_or_train(self, force_retrain: bool = False) -> Tuple[bool, str]:
        """Load saved artifacts, or train from scratch. Returns (ok, message)."""
        if not force_retrain and ML_MODEL_PATH.exists() and ML_VECTORIZER_PATH.exists() and ML_META_PATH.exists():
            try:
                with open(ML_MODEL_PATH, "rb") as f:
                    self._model = pickle.load(f)
                with open(ML_VECTORIZER_PATH, "rb") as f:
                    saved = pickle.load(f)
                self._vectorizer = saved.get("vectorizer")
                self._selector = saved.get("selector")
                with open(ML_META_PATH, "rb") as f:
                    self._meta = pickle.load(f)
                self._idx_to_label = list(self._meta.class_labels)
                self._label_to_idx = {lab: i for i, lab in enumerate(self._idx_to_label)}
                self._n_text_features = saved.get("n_text_features", 0)
                self._available = True
                log.info(f"ML model loaded: {self._meta.version}, train_acc={self._meta.train_accuracy:.3f}, n={self._meta.n_samples_train}")
                return True, f"Loaded saved model v{self._meta.version} (train_acc={self._meta.train_accuracy:.2%})"
            except Exception as e:
                log.warning(f"ML model load failed, will retrain: {e}")

        try:
            return self._train_from_scratch()
        except Exception as e:
            log.exception(f"ML train failed: {e}")
            self._available = False
            return False, f"Train failed: {e}"

    def _train_from_scratch(self) -> Tuple[bool, str]:
        try:
            import lightgbm as lgb
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.feature_selection import SelectKBest, chi2
            import numpy as np
        except Exception as e:
            return False, f"scikit-learn/lightgbm unavailable: {e}"

        X_num_list, X_text, y_raw = build_training_set_from_csv(str(ROOT_DIR / "classification" / "labeling_dump.csv"))
        labels = sorted(set(y_raw))
        self._idx_to_label = labels
        self._label_to_idx = {lab: i for i, lab in enumerate(labels)}
        y = np.array([self._label_to_idx[lab] for lab in y_raw], dtype=np.int32)

        X_num = np.array([[row[k] for k in _NUM_FEATURE_NAMES] for row in X_num_list], dtype=np.float32)

        vec = TfidfVectorizer(
            vocabulary=DOMAIN_KEYWORDS,
            ngram_range=(1, 2),
            lowercase=True,
            min_df=1,
            max_features=200,
        )
        X_text_mat = vec.fit_transform(X_text)

        n_classes = len(labels)
        if X_text_mat.shape[1] > 0 and n_classes > 1:
            try:
                k_best = min(60, X_text_mat.shape[1])
                sel = SelectKBest(chi2, k=k_best)
                X_text_sel = sel.fit_transform(X_text_mat, y).toarray()
                self._selector = sel
                self._n_text_features = X_text_sel.shape[1]
            except Exception:
                X_text_sel = X_text_mat.toarray()
                self._selector = None
                self._n_text_features = X_text_sel.shape[1]
        else:
            X_text_sel = X_text_mat.toarray()
            self._selector = None
            self._n_text_features = X_text_sel.shape[1]

        self._vectorizer = vec

        X_combined = np.concatenate([X_num, X_text_sel.astype(np.float32)], axis=1)

        rng = np.random.default_rng(SYNTHETIC_RANDOM_SEED)
        perm = rng.permutation(len(y))
        X_train = X_combined[perm]
        y_train = y[perm]

        params = {
            "objective": "multiclass",
            "num_class": n_classes,
            "metric": "multi_logloss",
            "learning_rate": 0.06,
            "num_leaves": 48,
            "feature_fraction": 0.85,
            "bagging_fraction": 0.85,
            "bagging_freq": 5,
            "min_data_in_leaf": 20,
            "verbose": -1,
            "seed": SYNTHETIC_RANDOM_SEED,
            "is_unbalance": True,
        }

        d_train = lgb.Dataset(X_train, label=y_train, free_raw_data=False)
        model = lgb.train(params, d_train, num_boost_round=220)
        self._model = model

        preds = np.asarray(model.predict(X_train))
        pred_idx = np.argmax(preds, axis=1)
        acc = float(np.mean(pred_idx == y_train))

        self._meta = TrainMeta(
            version="2.0-synthetic",
            n_classes=n_classes,
            class_labels=list(labels),
            num_feature_names=list(_NUM_FEATURE_NAMES),
            n_samples_train=len(y_train),
            train_accuracy=round(acc, 4),
            fallback_threshold=ML_FALLBACK_THRESHOLD,
            note="Trained on parameterized archetypes w/ realistic perturbations.",
        )
        self._meta.version = "2.1-real-data-train%d" % len(y_train)
        self._meta.note = "real-data trained on %d manually labeled rows from labeling_dump.csv" % len(y_train)

        try:
            with open(ML_MODEL_PATH, "wb") as f:
                pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)
            with open(ML_VECTORIZER_PATH, "wb") as f:
                pickle.dump(
                    {
                        "vectorizer": self._vectorizer,
                        "selector": self._selector,
                        "n_text_features": self._n_text_features,
                    },
                    f,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
            with open(ML_META_PATH, "wb") as f:
                pickle.dump(self._meta, f, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:
            log.warning(f"Could not save ML artifacts: {e}")

        self._available = True
        log.info(f"ML model trained: {self._meta.version}, train_acc={acc:.3f}, n={len(y_train)}")
        return True, f"Trained fresh model (train_acc={acc:.2%}, n={len(y_train)})"

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def predict(self, data: FinancialData) -> Optional[Dict[str, Any]]:
        """Return dict with {probabilities, top1, top2, confidence}. None if unavailable."""
        if not self._available:
            return None
        try:
            import numpy as np
        except Exception:
            return None
        try:
            num_feat = extract_numerical_features(data)
            X_num = np.array([[num_feat[k] for k in _NUM_FEATURE_NAMES]], dtype=np.float32)

            if self._vectorizer is None:
                X_text_sel = np.zeros((1, max(1, self._n_text_features)), dtype=np.float32)
            else:
                corpus = build_text_corpus(data)
                X_t = self._vectorizer.transform([corpus])
                if self._selector is not None:
                    try:
                        X_t_sel = self._selector.transform(X_t).toarray()
                    except Exception:
                        X_t_sel = X_t.toarray()
                else:
                    X_t_sel = X_t.toarray()
                expected = self._n_text_features
                if X_t_sel.shape[1] < expected:
                    pad = np.zeros((1, expected - X_t_sel.shape[1]), dtype=np.float32)
                    X_t_sel = np.concatenate([X_t_sel, pad], axis=1)
                elif X_t_sel.shape[1] > expected:
                    X_t_sel = X_t_sel[:, :expected]
                X_text_sel = X_t_sel.astype(np.float32)

            X_combined = np.concatenate([X_num, X_text_sel], axis=1)
            probs = self._model.predict(X_combined)[0]

            prob_map: Dict[str, float] = {}
            for i, lab in enumerate(self._idx_to_label):
                prob_map[lab] = float(probs[i]) if i < len(probs) else 0.0

            sorted_items = sorted(prob_map.items(), key=lambda kv: -kv[1])
            top1_label, top1_p = sorted_items[0]
            top2_label, top2_p = sorted_items[1] if len(sorted_items) > 1 else (BusinessType.UNKNOWN.value, 0.0)

            return {
                "probabilities": prob_map,
                "top1": top1_label,
                "top1_prob": top1_p,
                "top2": top2_label,
                "top2_prob": top2_p,
                "confidence": float(top1_p),
                "model_version": self.MODEL_VERSION,
                "train_meta": {
                    "version": self._meta.version,
                    "n_samples_train": self._meta.n_samples_train,
                    "train_accuracy": self._meta.train_accuracy,
                },
            }
        except Exception as e:
            log.exception(f"ML predict failed: {e}")
            return None


# ===========================================================================
# Hybrid Top-level Classifier (ML + Rule fallback)
# ===========================================================================
class MLHybridClassifier:
    """
    Hybrid classifier:
      1. Run LightGBM multi-class -> probability distribution
      2. If top probability >= ML_FALLBACK_THRESHOLD: trust ML, but also
         apply hard-coded structural overrides (e.g. keyword 'bank' + high D/E
         must not be classified as Commodity).
      3. Else: fall back to deterministic BusinessClassifier.classify rules.
      4. Always attach probabilities + Top-2 candidates to CompanyProfile.
    """

    def __init__(self, ml: Optional[LightGBMBusinessClassifier] = None) -> None:
        self._ml = ml or LightGBMBusinessClassifier()
        self._rule_cls: Any = None
        self._initialized_ok: bool = False
        self._init_message: str = ""

    def ensure_ready(self, force_retrain: bool = False) -> Tuple[bool, str]:
        if self._initialized_ok and not force_retrain:
            return True, self._init_message
        ok, msg = self._ml.load_or_train(force_retrain=force_retrain)
        self._init_message = msg
        if ok:
            self._initialized_ok = True
        return ok, msg

    # ------------------------------------------------------------------
    # Structural sanity overrides (apply after ML, before fallback decision)
    # ------------------------------------------------------------------
    @staticmethod
    def _structural_overrides(data: FinancialData, ml_result: Dict[str, Any]
                              ) -> Tuple[Dict[str, Any], List[str]]:
        changes: List[str] = []
        probs = dict(ml_result["probabilities"])
        text = build_text_corpus(data)
        ttm = data.ttm

        def _swap_boost(label_keep: str, label_drop: str, reason: str) -> None:
            nonlocal changes
            if ml_result["top1"] == label_drop:
                old_p_top1 = probs.get(label_drop, 0.0)
                if probs.get(label_keep, 0.0) > 0:
                    probs[label_keep] += old_p_top1 * 0.6
                    probs[label_drop] *= 0.4
                    changes.append(reason)

        def _force_label(label_keep: str, reason: str) -> None:
            """Hard override: redistribute probability so label_keep ends up >= 0.50.

            Applied only when numerical heuristics are near-certain, e.g.
            "REIT margin profile (0.55-0.90 EBITDA/rev) + low-beta + low-growth".
            """
            nonlocal changes
            cur = probs.get(label_keep, 0.0)
            if cur >= 0.50:
                return
            need = 0.50 - cur
            donors = [(k, v) for k, v in probs.items()
                      if k != label_keep and v > 0.01]
            donors.sort(key=lambda kv: -kv[1])
            taken = 0.0
            for k, v in donors:
                if taken >= need:
                    break
                # take up to 80% of donor's probability to avoid zeroing it out
                give = min(v * 0.80, need - taken)
                if give <= 0:
                    break
                probs[k] = v - give
                probs[label_keep] = cur = cur + give
                taken += give
            if taken > 0.001:
                changes.append(reason)

        def _kw_hit(keyword: str) -> bool:
            """Substring hit that refuses to match a *short* ASCII token embedded
            inside a longer word. "gold" ⊂ "goldman" previously fired the
            commodity rule on Goldman Sachs; multi-word / non-ASCII / longer
            keywords keep plain substring semantics."""
            if not (keyword.isascii() and len(keyword) <= 5 and keyword[0].isalpha()):
                return keyword in text
            idx = text.find(keyword)
            while idx != -1:
                after = text[idx + len(keyword)] if idx + len(keyword) < len(text) else ""
                if not after.isalpha():
                    return True
                # allow a simple plural ("metal" → "metals")
                if after == "s" and (idx + len(keyword) + 1 >= len(text)
                                     or not text[idx + len(keyword) + 1].isalpha()):
                    return True
                idx = text.find(keyword, idx + 1)
            return False

        # ---- 0) Sector/Industry hard rule (layer-2, BEFORE all other overrides) ----
        # When Yahoo/akshare provides a sector/industry, it's a very strong signal.
        # If ML's top-1 disagrees with sector mapping, force sector mapping.
        from classification.classifier import map_sector_industry
        sector_bt = map_sector_industry(data.market.sector, data.market.industry)
        if sector_bt is not None:
            sector_label = sector_bt.value
            if ml_result["top1"] != sector_label:
                # Force sector mapping over ML when they disagree
                _force_label(sector_label,
                             f"Sector/Industry hard rule: '{data.market.sector}/{data.market.industry}' "
                             f"-> {sector_label} (overrides ML top-1 {ml_result['top1']})")

        # ---- 1) Bank (pure numeric: interest/revenue > 20%) ----------------
        if ttm and ttm.interest_expense and ttm.revenue and ttm.revenue > 0:
            ir = ttm.interest_expense / ttm.revenue
            if ir > 0.20 and ("bank" in text or "commercial" in text or "savings" in text):
                _swap_boost(BusinessType.BANK.value, BusinessType.REIT.value,
                            f"Structural: interest/revenue={ir:.2f} + bank keyword -> Bank over REIT")
                _swap_boost(BusinessType.BANK.value, BusinessType.SEMICONDUCTOR.value,
                            "Structural: bank signal overrides Semiconductor")
            # Pure-numeric bank fallback (even without keywords)
            if ir > 0.30:
                de_r = None
                if (data.market.total_debt is not None
                        and data.market.book_value and data.market.book_value > 0):
                    de_r = data.market.total_debt / data.market.book_value
                if de_r is None or de_r >= 1.5:
                    _force_label(BusinessType.BANK.value,
                                 f"Structural FORCE→Bank (interest/revenue={ir:.2f}, "
                                 f"high-leverage profile)")

        # ---- 2) Semiconductor keyword + low leverage -----------------------
        high_semi_keyword = any(k in text for k in [
            "semiconductor", "chip", "gpu", "nvidia", "foundry", "fabless", "ic design"
        ])
        de = None
        if data.market.total_debt is not None and data.market.book_value and data.market.book_value > 0:
            de = data.market.total_debt / data.market.book_value
        if high_semi_keyword and (de is None or de < 1.5):
            _swap_boost(BusinessType.SEMICONDUCTOR.value, BusinessType.REIT.value,
                        "Structural: Semiconductor keyword w/ low D/E -> not REIT")
            _swap_boost(BusinessType.SEMICONDUCTOR.value, BusinessType.UTILITIES.value,
                        "Structural: Semiconductor keyword w/ low D/E -> not Utilities")
            _swap_boost(BusinessType.SEMICONDUCTOR.value, BusinessType.MATURE_TECH.value,
                        "Structural: Semiconductor keyword overrides MatureTech")

        # Pure-numeric "semi-like" shape: high gross margin + low leverage +
        # capex-heavy. This shape only rules OUT margin/leverage overlap classes
        # (REIT / Utilities); it must NOT promote Semiconductor over MatureTech.
        # High margin + high capex + low leverage is a *shape*, not proof of a
        # semiconductor identity — Phase 1.3 resolves that with the identity vs
        # economics state machine instead of manufacturing a label here.
        if ttm and ttm.revenue and ttm.revenue > 0 and ttm.gross_profit is not None:
            gm = ttm.gross_profit / ttm.revenue
            capex_r = (abs(ttm.capex) / ttm.revenue
                       if ttm.capex is not None else 0.0)
            if gm >= 0.50 and capex_r >= 0.08 and (de is None or de < 1.0):
                _swap_boost(BusinessType.SEMICONDUCTOR.value, BusinessType.REIT.value,
                            f"Structural-num: gm={gm:.2f} capex/r={capex_r:.2f} low-D/E → not REIT")
                _swap_boost(BusinessType.SEMICONDUCTOR.value, BusinessType.UTILITIES.value,
                            "Structural-num: semi-like profile → not Utilities")
                # NOTE: intentionally no overrides against MATURE_TECH/SaaS here.
                # Promoting Semiconductor from structure alone is the exact
                # false-certainty defect Phase 1.3 removes.

        # ---- 3) REIT: keyword -------------------------------------------------
        if "reit" in text or "real estate" in text or "property trust" in text:
            _swap_boost(BusinessType.REIT.value, BusinessType.SEMICONDUCTOR.value,
                        "Structural: explicit REIT keyword overrides Semiconductor margin overlap")
            _swap_boost(BusinessType.REIT.value, BusinessType.SAAS.value,
                        "Structural: explicit REIT keyword overrides SaaS")
            _swap_boost(BusinessType.REIT.value, BusinessType.MATURE_TECH.value,
                        "Structural: explicit REIT keyword overrides MatureTech")

        # Pure-numeric REIT fallback (the *critical* one for when text is empty):
        #   Rules-classifier _looks_like_reit criteria:
        #      EBITDA margin 55%-90%, beta < 2, revenue CAGR < 25%
        #   + additionally: high interest/revenue (4%-30%, indicative of property debt),
        #                   D/E > 0.5, dividend yield > 2%
        if ttm and ttm.revenue and ttm.ebitda and ttm.revenue > 0:
            ebitda_m = ttm.ebitda / ttm.revenue
            beta = data.market.beta
            div_y = data.market.dividend_yield or 0.0
            # CAGR check (same as BusinessClassifier._looks_like_reit)
            cagr_ok = True
            annuals = data.annual_income
            if len(annuals) >= 4 and annuals[0].revenue and annuals[-1].revenue and annuals[-1].revenue > 0:
                n = len(annuals) - 1
                cagr = (annuals[0].revenue / annuals[-1].revenue) ** (1 / n) - 1
                cagr_ok = cagr <= 0.25
            if (0.55 <= ebitda_m <= 0.90
                    and (beta is None or beta < 2.0)
                    and cagr_ok
                    and (div_y >= 0.02 or (de is not None and de >= 0.5))):
                # Strong REIT → force override MatureTech/Conglomerate/SaaS tops
                _force_label(BusinessType.REIT.value,
                             f"Structural-num FORCE→REIT (ebitda_m={ebitda_m:.2f}, "
                             f"beta={beta}, div_y={div_y:.2%}, de={de})")

        # ---- 3b) Semiconductor keyword force-label (AFTER REIT force) ---------
        # Must run after REIT pure-numeric force so that semiconductor keyword
        # can override the REIT margin overlap (e.g. NVDA has high EBITDA margin
        # but is clearly a semiconductor company based on name/keyword).
        if high_semi_keyword and (de is None or de < 1.5):
            _force_label(BusinessType.SEMICONDUCTOR.value,
                         "Structural FORCE->Semiconductor (explicit keyword in name, low D/E)")

        # ---- 4) Utilities: keyword + high dividend + low beta -----------------
        if any(k in text for k in ["utility", "utilities", "electric", "power", "water", "gas utility"]):
            _swap_boost(BusinessType.UTILITIES.value, BusinessType.COMMODITY.value,
                        "Structural: Utilities keyword overrides Commodity/Energy")
            _swap_boost(BusinessType.UTILITIES.value, BusinessType.SEMICONDUCTOR.value,
                        "Structural: Utilities keyword overrides Semiconductor")
        # Pure-numeric Utilities: very high dividend (≥3%) + high D/E + low beta
        beta2 = data.market.beta
        div_y2 = data.market.dividend_yield or 0.0
        if (div_y2 >= 0.03 and (beta2 is None or beta2 < 1.0)
                and (de is not None and de >= 1.0)):
            _swap_boost(BusinessType.UTILITIES.value, BusinessType.COMMODITY.value,
                        f"Structural-num: div_y={div_y2:.1%} low-β high-D/E → not Commodity")
            _swap_boost(BusinessType.UTILITIES.value, BusinessType.REIT.value,
                        "Structural-num: utility profile nudges away from REIT")

        # ---- 5) Healthcare / Pharma / Biotech keyword override -----------------
        healthcare_keywords = [
            "pharma", "pharmaceutical", "biotech", "biotechnology", "medical",
            "medical device", "healthcare", "health", "drug", "therapeutic",
            "diagnostic", "life science", "biopharm",
            "j&j", "johnson & johnson", "unitedhealth", "pfizer", "merck",
            "novartis", "roche", "abbvie", "eli lilly", "bristol",
            "medtronic", "teladoc", "regeneron", "vertex",
            "制药", "医药", "生物技术", "医疗器械", "医疗", "健康", "药品", "药物",
        ]
        if any(k in text for k in healthcare_keywords):
            _swap_boost(BusinessType.HEALTHCARE.value, BusinessType.MATURE_TECH.value,
                        "Structural: healthcare/pharma keyword overrides MatureTech")
            _swap_boost(BusinessType.HEALTHCARE.value, BusinessType.SAAS.value,
                        "Structural: healthcare/pharma keyword overrides SaaS")
            _swap_boost(BusinessType.HEALTHCARE.value, BusinessType.CONGLOMERATE.value,
                        "Structural: healthcare/pharma keyword overrides Conglomerate")

        # ---- 6) Industrial / Aerospace / Defense / Logistics keyword override ----
        industrial_keywords = [
            "industrial", "construction", "machinery", "aerospace", "defense",
            " freight", " courier", " trucking", " shipping",
            "package delivery", "warehouse", "manufacturing",
            "boeing", "lockheed", "general dynamics", "northrop",
            "raytheon", "rtx", "l3harris", "huntington",
            "honeywell", "eaton", "emerson", "rockwell", "cummins",
            "paccar", "howmet", "textron",
            "fastenal", "quanta", "caterpillar",
            "fedex", "ups", "united parcel",
            "rocket lab", "virgin galactic", "teledyne",
            # Use " logistics" (with leading space) to avoid matching "prologis"
            " logistics",
        ]
        # Skip industrial override if REIT keyword is already present (e.g. PLD has
        # industry "REIT - Industrial" which contains "industrial" as substring).
        has_reit_keyword = any(k in text for k in ["reit", "real estate", "property trust", "realty"])
        if any(keyword_hit(text, k) for k in industrial_keywords) and not has_reit_keyword:
            _swap_boost(BusinessType.INDUSTRIAL.value, BusinessType.CONGLOMERATE.value,
                        "Structural: industrial/aerospace/logistics keyword overrides Conglomerate")
            _swap_boost(BusinessType.INDUSTRIAL.value, BusinessType.MATURE_TECH.value,
                        "Structural: industrial/aerospace keyword overrides MatureTech")
            _swap_boost(BusinessType.INDUSTRIAL.value, BusinessType.UNKNOWN.value,
                        "Structural: industrial keyword overrides Unknown")
            _swap_boost(BusinessType.INDUSTRIAL.value, BusinessType.CONSUMER_CYCLICAL.value,
                        "Structural: logistics/industrial keyword overrides ConsumerCyclical")
            _force_label(BusinessType.INDUSTRIAL.value,
                         "Structural FORCE->Industrial (explicit industrial keyword in name)")

        # ---- 7) Energy / Oil & Gas / Pipeline keyword override -----------------
        energy_keywords = [
            "oil", "petroleum", "energy", "pipeline", "midstream", "refining", "refinery",
            "exxon", "chevron", "shell", "conoco", "occidental",
            "diamondback", "devon", "apa", "civitas",
            "energy transfer", "kinder morgan", "williams", "enterprise products",
            "targa", "enbridge", "plains",
            "valero", "marathon petroleum", "phillips 66",
            "halliburton", "schlumberger", "baker hughes",
            "hess", "suncor", "canadian natural",
        ]
        # "Energy" is a generic corporate word ("Constellation Energy",
        # "NextEra Energy", "Duke Energy"). When the provider's sector/industry
        # already identifies the company as a regulated utility, that identity
        # must not be overturned by a bare "energy" token — only unambiguous
        # upstream oil & gas / midstream words may redirect to Energy.
        utilities_identity = sector_bt == BusinessType.UTILITIES
        energy_hit = any(
            k in text for k in energy_keywords
            if not (utilities_identity and k == "energy")
        )
        if energy_hit:
            _swap_boost(BusinessType.ENERGY.value, BusinessType.COMMODITY.value,
                        "Structural: oil/gas/energy keyword overrides Commodity")
            _swap_boost(BusinessType.ENERGY.value, BusinessType.UTILITIES.value,
                        "Structural: oil/gas/energy keyword overrides Utilities")
            _swap_boost(BusinessType.ENERGY.value, BusinessType.CONGLOMERATE.value,
                        "Structural: energy keyword overrides Conglomerate")
            _swap_boost(BusinessType.ENERGY.value, BusinessType.MATURE_TECH.value,
                        "Structural: energy keyword overrides MatureTech")
            _force_label(BusinessType.ENERGY.value,
                         "Structural FORCE->Energy (explicit oil/gas/energy keyword in name)")

        # ---- 8) Telecom / Cable / Wireless keyword override --------------------
        telecom_keywords = [
            "telecom", "telecommunication", "wireless", "cable", "broadband", "fiber",
            "at&t", "verizon", "t-mobile", "tmus",
            "charter communications", "comcast",
            "vodafone", "telus", "rogers", "bell canada", "bce",
            "iridium", "ribbon communications",
            "american tower", "sba communications", "crown castle",
            "cell tower", "tower",
        ]
        if any(k in text for k in telecom_keywords):
            _swap_boost(BusinessType.TELECOM.value, BusinessType.UTILITIES.value,
                        "Structural: telecom keyword overrides Utilities")
            _swap_boost(BusinessType.TELECOM.value, BusinessType.MATURE_TECH.value,
                        "Structural: telecom keyword overrides MatureTech")
            _swap_boost(BusinessType.TELECOM.value, BusinessType.CONGLOMERATE.value,
                        "Structural: telecom keyword overrides Conglomerate")
            _swap_boost(BusinessType.TELECOM.value, BusinessType.UNKNOWN.value,
                        "Structural: telecom keyword overrides Unknown")
            _swap_boost(BusinessType.TELECOM.value, BusinessType.COMMODITY.value,
                        "Structural: telecom keyword overrides Commodity")
            # Force-label if still not top-1 (don't let Commodity beat Telecom on name match)
            _force_label(BusinessType.TELECOM.value,
                         "Structural FORCE->Telecom (explicit telecom keyword in name)")

        # ---- 9) Media / Entertainment / Streaming keyword override -------------
        media_keywords = [
            "media", "entertainment", "streaming", "publishing", "gaming",
            "broadcast", "television", "movie", "film", "studio",
            "disney", "warner", "netflix", "fox", "news corp",
            "spotify", "take-two", "electronic arts",
            "activision", "roblox", "paramount", "imax",
        ]
        if any(k in text for k in media_keywords):
            _swap_boost(BusinessType.MEDIA.value, BusinessType.MATURE_TECH.value,
                        "Structural: media/entertainment keyword overrides MatureTech")
            _swap_boost(BusinessType.MEDIA.value, BusinessType.CONGLOMERATE.value,
                        "Structural: media keyword overrides Conglomerate")
            _swap_boost(BusinessType.MEDIA.value, BusinessType.CONSUMER_CYCLICAL.value,
                        "Structural: media keyword overrides ConsumerCyclical")
            _force_label(BusinessType.MEDIA.value,
                         "Structural FORCE->Media (explicit media/entertainment keyword in name)")

        # ---- 10) Consumer Staples / Food / Beverage / Tobacco keyword override --
        staples_keywords = [
            "food", "beverage", "tobacco", "grocery", "supermarket", "household",
            "coca cola", "pepsi", "procter", "unilever", "colgate",
            "kraft", "general mills", "hormel", "tyson", "sysco",
            "altria", "philip morris", "british american tobacco",
            "costco", "walmart", "target", "kroger", "dollar",
            "diageo", "anheuser", "nestle", "mondelez", "campbell",
            "church & dwight",
        ]
        if any(k in text for k in staples_keywords):
            _swap_boost(BusinessType.CONSUMER_STAPLES.value, BusinessType.MATURE_TECH.value,
                        "Structural: consumer staples keyword overrides MatureTech")
            _swap_boost(BusinessType.CONSUMER_STAPLES.value, BusinessType.CONGLOMERATE.value,
                        "Structural: consumer staples keyword overrides Conglomerate")
            _swap_boost(BusinessType.CONSUMER_STAPLES.value, BusinessType.CONSUMER_CYCLICAL.value,
                        "Structural: consumer staples keyword overrides ConsumerCyclical")
            _force_label(BusinessType.CONSUMER_STAPLES.value,
                         "Structural FORCE->ConsumerStaples (explicit staples keyword in name)")

        # ---- 11) Insurance keyword override ----------------------------------
        insurance_keywords = [
            "insurance", "life insurance", "property casualty", "reinsurance",
            "allstate", "metlife", "aflac", "travelers", "chubb", "progressive",
            "aig", "hartford", "cigna", "unum", " rga", "arch capital",
            "kns/l", " rlc", " sigi", " wrb", "orion", "fidelity national",
            "insurance brokers", "marsh mclennan", "aon", "arthur j gallagher",
            "人寿", "保险", "财险", "再保险",
        ]
        # NOTE: removed bare "re" (matched "real", "reit", "industrial", etc.)
        # and bare "met" (matched "metals", "metric", etc.)
        # and bare "pru" (matched "prudential" which is correct, but also
        # false positives). Now using space-prefixed versions for short tickers.
        if any(k in text for k in insurance_keywords):
            _swap_boost(BusinessType.INSURANCE.value, BusinessType.BANK.value,
                        "Structural: insurance keyword overrides Bank")
            _swap_boost(BusinessType.INSURANCE.value, BusinessType.MATURE_TECH.value,
                        "Structural: insurance keyword overrides MatureTech")
            _swap_boost(BusinessType.INSURANCE.value, BusinessType.CONGLOMERATE.value,
                        "Structural: insurance keyword overrides Conglomerate")
            _force_label(BusinessType.INSURANCE.value,
                         "Structural FORCE->Insurance (explicit insurance keyword in name)")

        # ---- 12) Consumer Cyclical keyword override --------------------------
        consumer_cyclical_keywords = [
            "auto", "automobile", "retail", "travel", "hotel", "airline",
            "cruise", "restaurant", "fashion", "apparel", "clothing", "luxury",
            "home depot", "lowe", "tesla", "ford", "gm", "toyota",
            "starbucks", "mcdonald", "carnival", "royal caribbean",
            "marriott", "hilton", "booking", "expedia", "airbnb",
            "nike", "lululemon", "ralph lauren", "gap",
            "home improvement", "department store", "specialty retail",
            "consumer cyclical", "discretionary",
            "航空", "汽车", "零售", "酒店", "旅游",
        ]
        has_staples = any(k in text for k in [
            "food", "beverage", "tobacco", "grocery", "supermarket", "household",
            "coca cola", "pepsi", "procter", "unilever", "costco", "walmart",
        ])
        if any(k in text for k in consumer_cyclical_keywords) and not has_staples:
            _swap_boost(BusinessType.CONSUMER_CYCLICAL.value, BusinessType.MATURE_TECH.value,
                        "Structural: consumer cyclical keyword overrides MatureTech")
            _swap_boost(BusinessType.CONSUMER_CYCLICAL.value, BusinessType.CONGLOMERATE.value,
                        "Structural: consumer cyclical keyword overrides Conglomerate")
            _swap_boost(BusinessType.CONSUMER_CYCLICAL.value, BusinessType.UNKNOWN.value,
                        "Structural: consumer cyclical keyword overrides Unknown")
            _force_label(BusinessType.CONSUMER_CYCLICAL.value,
                         "Structural FORCE->ConsumerCyclical (explicit cyclical keyword in name)")

        # ---- 13) Commodity / Mining / Materials keyword override ------------
        commodity_keywords = [
            "mining", "metal", "steel", "iron", "copper", "gold", "silver",
            "aluminum", "alcoa", "nucor", "freeport", "southern copper",
            "cleveland cliffs", "chemical", "化工", "dupont", "dow",
            "lyondellbasell", "ashland", "eastman", "ppg",
            "fertilizer", "agriculture", "农业",
            "albemarle", "nutrien", "cf industries", "mosaic", "fmc",
            "timber", "paper", "pulp", "packaging",
            "packaging & containers", "building materials",
            "specialty chemicals", "矿业", "钢铁", "煤炭",
        ]
        # Distinguish from Energy (oil/gas/petroleum should go to Energy, not Commodity)
        has_energy = any(k in text for k in [
            "oil", "petroleum", "refining", "refinery", "midstream", "pipeline",
            "exxon", "chevron", "shell", "conoco",
        ])
        if any(_kw_hit(k) for k in commodity_keywords) and not has_energy:
            _swap_boost(BusinessType.COMMODITY.value, BusinessType.ENERGY.value,
                        "Structural: mining/materials keyword overrides Energy")
            _swap_boost(BusinessType.COMMODITY.value, BusinessType.INDUSTRIAL.value,
                        "Structural: commodity keyword overrides Industrial")
            _swap_boost(BusinessType.COMMODITY.value, BusinessType.MATURE_TECH.value,
                        "Structural: commodity keyword overrides MatureTech")
            _swap_boost(BusinessType.COMMODITY.value, BusinessType.CONGLOMERATE.value,
                        "Structural: commodity keyword overrides Conglomerate")
            _force_label(BusinessType.COMMODITY.value,
                         "Structural FORCE->Commodity (explicit mining/materials keyword in name)")

        # ---- 14) Conglomerate / Diversified holding override ----------------
        cong_keywords = [
            "conglomerate", "diversified holding", "holding company",
            "berkshire", "general electric", "honeywell",
            "3m", "danaher", "roper", "idex",
            "集团", "控股",
        ]
        # Don't trigger Conglomerate if another explicit sector keyword is dominant
        has_dominant_other = (
            has_energy or any(_kw_hit(k) for k in commodity_keywords)
            or any(k in text for k in insurance_keywords)
            or any(k in text for k in ["bank", "commercial", "savings"])
            or any(k in text for k in ["reit", "real estate", "property trust"])
            or any(k in text for k in ["semiconductor", "chip", "gpu"])
            or any(k in text for k in ["pharma", "biotech", "healthcare", "medical"])
        )
        # Berkshire Hathaway is filed by Yahoo as an insurer (insurance-led
        # holding) but is valued as a diversified conglomerate: insurance +
        # railroad + utilities + manufacturing. Its identity must not collapse
        # to a single operating segment, so the holding-company route wins.
        berkshire_cong = "berkshire" in text
        if berkshire_cong:
            _swap_boost(BusinessType.CONGLOMERATE.value, BusinessType.INSURANCE.value,
                        "Structural: Berkshire Hathaway is a diversified conglomerate, "
                        "not a pure insurer")
        if (any(k in text for k in cong_keywords) and not has_dominant_other) or berkshire_cong:
            _swap_boost(BusinessType.CONGLOMERATE.value, BusinessType.MATURE_TECH.value,
                        "Structural: conglomerate keyword overrides MatureTech")
            _swap_boost(BusinessType.CONGLOMERATE.value, BusinessType.UNKNOWN.value,
                        "Structural: conglomerate keyword overrides Unknown")
            _force_label(BusinessType.CONGLOMERATE.value,
                         "Structural FORCE->Conglomerate (explicit conglomerate/holding keyword in name)")

        sorted_items = sorted(probs.items(), key=lambda kv: -kv[1])
        ml_result = dict(ml_result)
        ml_result["probabilities"] = probs
        ml_result["top1"], ml_result["top1_prob"] = sorted_items[0]
        if len(sorted_items) > 1:
            ml_result["top2"], ml_result["top2_prob"] = sorted_items[1]
        ml_result["confidence"] = ml_result["top1_prob"]
        return ml_result, changes

    # ------------------------------------------------------------------
    # Hybrid classification helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _build_exposures(prob_map: Dict[str, float]) -> List[Any]:
        """Aggregate raw class probabilities into human-legible exposure axes.

        IMPORTANT: sum of all output weights ≈ 100% (includes Unknown / Unclassified bucket).
        This avoids the "77% missing" display bug.

        Financial axis:  Bank + Insurance + REIT + FinTech + Neobank
        Technology axis: SaaS + MatureTech + Semiconductor
        Healthcare axis: Healthcare (Pharma/Biotech/MedDevice)
        Cyclical axis:   ConsumerCyclical
        Staples axis:    ConsumerStaples (Food/Beverage/Tobacco)
        Energy axis:     Energy (Oil/Gas/Pipeline)
        HardAssets axis: Commodity + Utilities
        Industrial axis: Industrial (Aerospace/Defense/Logistics)
        Telecom axis:    Telecom (Wireless/Cable/Tower)
        Media axis:      Media (Entertainment/Streaming/Gaming)
        Diversified axis: Conglomerate
        Unknown axis:    Unknown (ML explicitly said "I don't know")
        """
        from data.models import BusinessExposure

        def _agg(keys):
            return sum(prob_map.get(k, 0.0) for k in keys)

        fin_p = _agg([
            BusinessType.BANK.value, BusinessType.INSURANCE.value, BusinessType.REIT.value,
            BusinessType.FINTECH.value, BusinessType.NEOBANK.value,
        ])
        tech_p = _agg([BusinessType.SAAS.value, BusinessType.MATURE_TECH.value, BusinessType.SEMICONDUCTOR.value])
        health_p = _agg([BusinessType.HEALTHCARE.value])
        cyc_p = _agg([BusinessType.CONSUMER_CYCLICAL.value])
        staples_p = _agg([BusinessType.CONSUMER_STAPLES.value])
        energy_p = _agg([BusinessType.ENERGY.value])
        hard_p = _agg([BusinessType.COMMODITY.value, BusinessType.UTILITIES.value])
        ind_p = _agg([BusinessType.INDUSTRIAL.value])
        telecom_p = _agg([BusinessType.TELECOM.value])
        media_p = _agg([BusinessType.MEDIA.value])
        div_p = _agg([BusinessType.CONGLOMERATE.value])
        unknown_p = float(prob_map.get(BusinessType.UNKNOWN.value, 0.0))

        accounted = (fin_p + tech_p + health_p + cyc_p + staples_p
                     + energy_p + hard_p + ind_p + telecom_p + media_p + div_p)
        total_prob = accounted + unknown_p
        other_p = max(0.0, 1.0 - total_prob)

        exposures = [
            BusinessExposure(label="Financial (Bank/Insurance/REIT/FinTech)", weight=round(fin_p, 4)),
            BusinessExposure(label="Technology (SaaS/Tech/Semi)", weight=round(tech_p, 4)),
        ]
        if health_p >= 0.02:
            exposures.append(BusinessExposure(label="Healthcare (Pharma/Biotech/MedDevice)", weight=round(health_p, 4)))
        if cyc_p >= 0.02:
            exposures.append(BusinessExposure(label="Consumer Cyclical", weight=round(cyc_p, 4)))
        if staples_p >= 0.02:
            exposures.append(BusinessExposure(label="Consumer Staples (Food/Beverage/Tobacco)", weight=round(staples_p, 4)))
        if energy_p >= 0.02:
            exposures.append(BusinessExposure(label="Energy (Oil/Gas/Pipeline)", weight=round(energy_p, 4)))
        if hard_p >= 0.02:
            exposures.append(BusinessExposure(label="Hard Assets (Commodity/Utilities)", weight=round(hard_p, 4)))
        if ind_p >= 0.02:
            exposures.append(BusinessExposure(label="Industrial (Aerospace/Defense/Logistics)", weight=round(ind_p, 4)))
        if telecom_p >= 0.02:
            exposures.append(BusinessExposure(label="Telecom (Wireless/Cable/Tower)", weight=round(telecom_p, 4)))
        if media_p >= 0.02:
            exposures.append(BusinessExposure(label="Media (Entertainment/Streaming/Gaming)", weight=round(media_p, 4)))
        if div_p >= 0.02:
            exposures.append(BusinessExposure(label="Conglomerate/Diversified", weight=round(div_p, 4)))
        if other_p >= 0.02:
            exposures.append(BusinessExposure(label="Other Sectors", weight=round(other_p, 4)))
        if unknown_p >= 0.005:
            exposures.append(BusinessExposure(
                label="Unclassified (ML Unknown)",
                weight=round(unknown_p, 4),
                source="ml_unknown_class",
            ))
        exposures.sort(key=lambda e: -e.weight)
        return exposures

    @staticmethod
    def _detect_hybrid(best_bt: Any, prob_map: Dict[str, float],
                       ) -> Tuple[bool, Optional[str], Optional[str], Optional[str], str]:
        """Detect hybrid/mixed-model companies.

        Returns (is_hybrid, primary, secondary, label, confidence_level_text).

        Hybrid trigger (any of):
          - Top-1 is a Financial type AND Tech exposure >= 0.10 → "FinTech Hybrid"
          - Top-1 is a Tech type AND Financial exposure >= 0.10 → "Tech-Enabled Finance"
          - Top-1 is Unknown AND (Fin+Tech combined >= 0.15) → "FinTech / Digital Financial Services"
          - Top-1 probability < 0.55 AND Top-1/Top-2 ratio < 3 → "Mixed Classification"
        """
        fin_keys = {
            BusinessType.BANK.value, BusinessType.INSURANCE.value, BusinessType.REIT.value,
            BusinessType.FINTECH.value, BusinessType.NEOBANK.value,
        }
        tech_keys = {BusinessType.SAAS.value, BusinessType.MATURE_TECH.value, BusinessType.SEMICONDUCTOR.value}
        cong_key = BusinessType.CONGLOMERATE.value

        def _agg(keys):
            return sum(prob_map.get(k, 0.0) for k in keys)

        fin_p = _agg(fin_keys)
        tech_p = _agg(tech_keys)
        unknown_p = float(prob_map.get(BusinessType.UNKNOWN.value, 0.0))

        sorted_probs = sorted(prob_map.items(), key=lambda kv: -kv[1])
        top1_p = sorted_probs[0][1] if sorted_probs else 0.0
        top2_p = sorted_probs[1][1] if len(sorted_probs) > 1 else 0.0
        ratio = top1_p / top2_p if top2_p > 1e-9 else 99.0

        # Primary / secondary: when Unknown is top-1, use top KNOWN classes instead
        known_sorted = [(k, v) for k, v in sorted_probs if k != BusinessType.UNKNOWN.value]
        if best_bt == BusinessType.UNKNOWN:
            # primary = top known class (not Unknown itself)
            primary = known_sorted[0][0] if known_sorted else best_bt.value
            secondary = (
                known_sorted[1][0]
                if len(known_sorted) > 1 and known_sorted[1][1] >= 0.05
                else None
            )
        else:
            primary = best_bt.value
            secondary = sorted_probs[1][0] if len(sorted_probs) > 1 and sorted_probs[1][1] >= 0.08 else None

        label = None
        is_hybrid = False

        # ---- Case A: ML says Unknown → build a descriptive label from rule signals ----
        if best_bt == BusinessType.UNKNOWN:
            combined_fin_tech = fin_p + tech_p
            # NU case: Fin ~10% + Tech ~10% → FinTech / Digital Financial Services
            if combined_fin_tech >= 0.15 and fin_p >= 0.05 and tech_p >= 0.05:
                is_hybrid = True
                label = "FinTech / Digital Financial Services"
                if secondary is None:
                    secondary = (
                        BusinessType.MATURE_TECH.value
                        if tech_p >= fin_p
                        else BusinessType.BANK.value
                    )
                if primary == cong_key:
                    # Never let Conglomerate stand as "primary" when Unknown is dominant
                    primary = (
                        BusinessType.BANK.value
                        if fin_p >= tech_p
                        else BusinessType.MATURE_TECH.value
                    )
            # Just Financial signal + something else
            elif fin_p >= 0.10:
                is_hybrid = True
                label = "Financial Services with Unclassified Segments"
                if secondary is None:
                    secondary = known_sorted[1][0] if len(known_sorted) > 1 else None
            elif tech_p >= 0.10:
                is_hybrid = True
                label = "Technology with Unclassified Segments"
                if secondary is None:
                    secondary = known_sorted[1][0] if len(known_sorted) > 1 else None
            else:
                # Catch-all for Unknown without strong signals
                is_hybrid = True
                label = "Unclassified Business Model (Use multi-model average)"
        # ---- Case B: FinTech hybrid rule (SOFI case) ----
        elif best_bt.value in fin_keys and tech_p >= HYBRID_FIN_TO_TECH_FLOOR:
            is_hybrid = True
            label = "Hybrid Financial Institution (FinTech)"
            if secondary is None:
                secondary = (
                    BusinessType.MATURE_TECH.value
                    if prob_map.get(BusinessType.MATURE_TECH.value, 0) >= prob_map.get(BusinessType.SAAS.value, 0)
                    else BusinessType.SAAS.value
                )
        # ---- Case C: Tech-enabled finance (e.g. SQ, PYPL) ----
        elif best_bt.value in tech_keys and fin_p >= 0.08:
            is_hybrid = True
            label = "Technology Company with Financial Exposure"
            if secondary is None:
                secondary = BusinessType.BANK.value
        # ---- Case D: Generic low-confidence mixture ----
        elif top1_p < 0.55 and ratio < 3.0:
            is_hybrid = True
            label = "Mixed / Diversified Business Model"

        # ---- Confidence level (text): when Unknown dominates, force Low ----
        if best_bt == BusinessType.UNKNOWN and unknown_p >= 0.45:
            clevel = "Low"
        elif best_bt == BusinessType.UNKNOWN:
            clevel = "Low-Medium" if (top1_p >= 0.35 or (fin_p + tech_p) >= 0.10) else "Low"
        elif top1_p >= 0.75 and ratio >= 5.0:
            clevel = "High"
        elif top1_p >= 0.55 and ratio >= 2.0:
            clevel = "Medium"
        else:
            clevel = "Low"

        return is_hybrid, primary, secondary, label, clevel

    # ------------------------------------------------------------------
    # Main classify entrypoint
    # ------------------------------------------------------------------
    def classify(self, data: FinancialData) -> CompanyProfile:
        from classification.classifier import BusinessClassifier
        from data.models import ConfidenceAdjustment

        self.ensure_ready()

        ml_result = None
        rule_fallback = False
        raw_ml_snapshot: Optional[Dict[str, Any]] = None
        structural_changes: List[str] = []
        threshold = self._ml._meta.fallback_threshold if self._ml._meta else ML_FALLBACK_THRESHOLD

        if self._ml.available:
            raw = self._ml.predict(data)
            if raw is not None:
                # Snapshot the *raw* model opinion BEFORE the sector/industry
                # hard rule rewrites it. Phase 1.3 needs the statistical top-1 to
                # detect a conflict with the provider's identity; the post-rule
                # label already equals the identity, so it can never show one.
                raw_ml_snapshot = {
                    "top1": raw.get("top1"),
                    "top1_prob": float(raw.get("top1_prob") or 0.0),
                    "top2": raw.get("top2"),
                    "top2_prob": float(raw.get("top2_prob") or 0.0),
                }
                raw, structural_changes = self._structural_overrides(data, raw)
                if raw["top1_prob"] >= threshold:
                    ml_result = raw
                else:
                    rule_fallback = True
                    ml_result = raw
            else:
                rule_fallback = True
        else:
            rule_fallback = True

        if rule_fallback or ml_result is None:
            profile = BusinessClassifier.classify(data)
            if ml_result is None:
                profile.ml_probabilities = {}
                profile.top_2_candidates = []
            else:
                profile.ml_probabilities = ml_result["probabilities"]
                sorted_items = sorted(ml_result["probabilities"].items(), key=lambda kv: -kv[1])
                top2 = [(x[0], round(x[1], 4)) for x in sorted_items[:2]]
                profile.top_2_candidates = top2
                # ---- Confidence trail for rule-fallback path ----
                raw_c = float(ml_result["top1_prob"])
                profile.ml_raw_confidence = round(raw_c, 4)
                adj: List[ConfidenceAdjustment] = []
                final_c = profile.classification_confidence
                delta = round(final_c - raw_c, 4)
                if abs(delta) > 1e-6:
                    adj.append(ConfidenceAdjustment(
                        step_name="Rule-engine override / fallback",
                        delta=delta,
                        reason=f"ML top prob below {threshold:.0%} threshold; used deterministic rules",
                    ))
                profile.confidence_adjustments = adj

                # ---- FinTech hybrid detection in rule-fallback path ----
                # Even when ML fallback fires, if ML probabilities show strong
                # FinTech/Neobank/Bank signals, we should route models as a
                # financial institution (Bank DDM, exclude DCF/EV-EBITDA).
                ml_probs = ml_result["probabilities"]
                fin_tech_p = (
                    float(ml_probs.get(BusinessType.FINTECH.value, 0.0))
                    + float(ml_probs.get(BusinessType.NEOBANK.value, 0.0))
                    + float(ml_probs.get(BusinessType.BANK.value, 0.0))
                    + float(ml_probs.get(BusinessType.INSURANCE.value, 0.0))
                    + float(ml_probs.get(BusinessType.REIT.value, 0.0))
                )
                if fin_tech_p >= 0.10:
                    profile.is_financial_institution = True
                    from classification.classifier import BusinessClassifier as _BC
                    effective_bt = BusinessType.NEOBANK
                    applicable, not_applicable, na_reasons = _BC._model_applicability(
                        data, effective_bt
                    )
                    characterize = _BC._characterize_profile(data, effective_bt)
                    profile.applicable_models = applicable
                    profile.not_applicable_models = not_applicable
                    profile.not_applicable_reasons = na_reasons
                    profile.is_financial_institution = True
                    profile.leverage_profile = characterize.get(
                        "leverage_profile", profile.leverage_profile
                    )
                    profile.capital_intensity = characterize.get(
                        "capital_intensity", profile.capital_intensity
                    )
                    profile.cash_flow_profile = characterize.get(
                        "cash_flow_profile", profile.cash_flow_profile
                    )
                    profile.classification_reasons = (
                        profile.classification_reasons +
                        [f"FinTech hybrid detected in ML fallback "
                         f"(Fin exposure={fin_tech_p:.1%}) → model routing uses Neobank"]
                    )
                    # Rebuild exposures from ML probabilities (more accurate than rule pseudo-probs)
                    ml_exposures = self._build_exposures(ml_probs)
                    profile.business_exposures = ml_exposures
                    profile.is_hybrid_classification = True
                    profile.hybrid_classification_label = "FinTech / Digital Financial Services"

            profile.ml_model_used = False
            profile.rule_fallback_triggered = True
            profile.classification_reasons = (
                profile.classification_reasons +
                ([f"ML fallback (top prob < {threshold:.0%})"] if ml_result else ["ML model unavailable"]) +
                structural_changes
            )

            # ---- Business Taxonomy (five dimensions, additive / shadow) ----
            from classification.taxonomy import attach_taxonomy_profile
            attach_taxonomy_profile(
                data, profile,
                ml_label=(str(ml_result["top1"]) if ml_result else None),
                ml_confidence=(float(ml_result["top1_prob"]) if ml_result else None),
            )
            return profile

        best_label = ml_result["top1"]
        best_bt = BusinessType(best_label) if best_label in {b.value for b in BusinessType} else BusinessType.UNKNOWN
        reasons = [
            f"ML LightGBM v{ml_result.get('model_version', '?')} top-1: {best_label} (p={ml_result['top1_prob']:.2%})",
            f"Top-2 candidate: {ml_result['top2']} (p={ml_result['top2_prob']:.2%})",
        ]
        meta = ml_result.get("train_meta") or {}
        if meta:
            reasons.append(
                f"Training: {meta.get('version')} n={meta.get('n_samples_train')} acc={meta.get('train_accuracy', 0):.1%}"
            )
        reasons.extend(structural_changes)

        # ---- Probability map must be defined early, before any code uses it ----
        sorted_probs = sorted(ml_result["probabilities"].items(), key=lambda kv: -kv[1])
        prob_map = {k: round(v, 4) for k, v in sorted_probs}
        top2 = [(k, round(v, 4)) for k, v in sorted_probs[:2]]

        # Unknown from ML: NEVER map directly to Conglomerate or any single known type.
        # Instead: keep Unknown as best_bt, and use rule signals only as secondary hints
        # (exposure aggregation) to produce a descriptive label like "FinTech / Digital Financial Services".
        unknown_p = float(prob_map.get(BusinessType.UNKNOWN.value, 0.0))
        UNKNOWN_DOMINANT_THRESHOLD = 0.45  # if Unknown > this, we trust the ML's "don't know"
        if best_bt == BusinessType.UNKNOWN and unknown_p >= UNKNOWN_DOMINANT_THRESHOLD:
            # Keep Unknown. Still pull rule profile for rule-based exposure hints + keyword signals.
            rule_profile = BusinessClassifier.classify(data)
            reasons.append(
                f"ML top-1 is Unknown (p={unknown_p:.1%}); type kept as Unknown (not mapped to Conglomerate)"
            )
            reasons.append(
                "Rule signals below used only for exposure hints, NOT as authoritative classification."
            )
            # Absorb any strong rule-based keyword signals into the reason trail
            for r in rule_profile.classification_reasons[:2]:
                if "Keyword match" in r or "keyword" in r.lower():
                    reasons.append(f"[rule hint] {r}")
        elif best_bt == BusinessType.UNKNOWN and unknown_p < UNKNOWN_DOMINANT_THRESHOLD:
            # Unknown is top-1 but not dominant. Use rule-engine as a soft tie-breaker,
            # but only when rule engine has a confident answer AND we mark it clearly.
            rule_profile = BusinessClassifier.classify(data)
            if (rule_profile.business_type != BusinessType.UNKNOWN.value
                    and rule_profile.classification_confidence >= 0.55):
                rule_bt = BusinessType(rule_profile.business_type)
                reasons.append(
                    f"ML top-1 is Unknown (p={unknown_p:.1%} < {UNKNOWN_DOMINANT_THRESHOLD:.0%}); "
                    f"rule engine soft-override → {rule_bt.value} (rule_conf={rule_profile.classification_confidence:.0%})"
                )
                reasons.extend(rule_profile.classification_reasons[:3])
                best_bt = rule_bt
            else:
                reasons.append(
                    f"ML top-1 is Unknown (p={unknown_p:.1%}); rule engine also unsure — kept as Unknown"
                )

        # ================================================================
        # ISSUE #1 — Confidence transparency audit trail
        # ================================================================
        ml_raw_conf = float(ml_result["top1_prob"])
        confidence = ml_raw_conf
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
            # If company name contains explicit industry keywords, we have enough
            # textual signal even without sector/industry from data provider.
            # Use a higher cap (75%) vs the default 55% when no keywords are found.
            text_corpus = build_text_corpus(data)
            has_strong_keyword = any(k in text_corpus for k in [
                "pharma", "pharmaceutical", "biotech", "medical", "healthcare",
                "bank", "commercial", "savings", "insurance",
                "reit", "real estate", "property trust", "realty",
                "semiconductor", "chip", "gpu", "foundry",
                "saas", "cloud", "software",
                "utility", "utilities", "electric",
                "oil", "petroleum", "energy", "pipeline", "refining",
                "mining", "metal", "steel", "chemical",
                "industrial", "aerospace", "defense", "logistics", "freight",
                "telecom", "wireless", "cable", "broadband",
                "media", "entertainment", "streaming", "gaming",
                "food", "beverage", "tobacco", "grocery", "household",
                "auto", "retail", "airline", "hotel",
                "conglomerate", "holding",
                "j&j", "johnson & johnson", "unitedhealth",
                "exxon", "chevron", "at&t", "verizon", "t-mobile",
                "boeing", "lockheed", "disney", "netflix",
                "coca cola", "pepsi", "walmart", "costco",
            ])
            cap = 0.75 if has_strong_keyword else 0.55
            cap_name = "75% (strong keyword in name)" if has_strong_keyword else "55%"
            confidence = min(confidence, cap)
            delta = round(confidence - old, 4)
            if abs(delta) > 1e-6:
                adjustments.append(ConfidenceAdjustment(
                    step_name="Missing sector/industry cap",
                    delta=delta,
                    reason=f"sector/industry missing from data provider; confidence capped to {cap_name} (was {old:.1%})",
                ))
            reasons.append(f"sector/industry missing; classification confidence capped to {cap_name}")

        # ================================================================
        # ISSUE #2 — Hybrid classification + multi-axis exposures
        # ================================================================
        is_hybrid, primary_bt, secondary_bt, hybrid_label, clevel = (
            self._detect_hybrid(best_bt, prob_map)
        )
        exposures = self._build_exposures(prob_map)

        # ---- Detect FinTech hybrid BEFORE model applicability ----
        # If hybrid_label indicates FinTech, we need to treat this as a financial
        # institution for model routing purposes (even when best_bt is Unknown).
        is_fintech_hybrid = False
        hybrid_lbl_preview = ""
        # Pre-compute hybrid label to check if it's FinTech
        _, _, _, _pre_label, _ = self._detect_hybrid(best_bt, prob_map)
        hybrid_lbl_preview = (_pre_label or "").lower()
        if any(x in hybrid_lbl_preview for x in (
            "fintech", "digital financial", "financial services",
            "neobank", "digital bank",
        )):
            is_fintech_hybrid = True

        # Determine effective business type for model routing
        effective_bt = best_bt
        if is_fintech_hybrid and best_bt == BusinessType.UNKNOWN:
            # Route as Neobank (closest model set: Bank DDM + P/E + P/B)
            effective_bt = BusinessType.NEOBANK
            reasons.append(
                "FinTech hybrid detected → model routing uses Neobank "
                "(Bank DDM + P/E + P/B; excludes DCF/EV-EBITDA/FCF Yield)"
            )

        # ---- Phase 1.3: identity (what it sells) vs economics (shape) ----
        # Compare the *raw* ML top-1 (pre sector-hard-rule) with the provider's
        # identity. A statistically ambiguous top-1 that disagrees with the
        # identity must not be used as the valuation prototype.
        from classification.classifier import (
            CLASSIFICATION_STATUS_AMBIGUOUS as _CLS_AMBIGUOUS,
            CLASSIFICATION_STATUS_CONFIDENT as _CLS_CONFIDENT,
            map_sector_industry as _map_sector_industry,
            resolve_identity_economics_status as _resolve_cls_status,
        )
        identity_bt = _map_sector_industry(data.market.sector, data.market.industry)
        cls_status = _CLS_CONFIDENT
        conflict_note: Optional[str] = None
        if raw_ml_snapshot is not None:
            cls_status, _route_bt, conflict_note = _resolve_cls_status(
                str(raw_ml_snapshot.get("top1") or ""),
                float(raw_ml_snapshot.get("top1_prob") or 0.0),
                float(raw_ml_snapshot.get("top2_prob") or 0.0),
                data.market.sector,
                data.market.industry,
            )
            if cls_status == _CLS_AMBIGUOUS and _route_bt is not None:
                effective_bt = _route_bt
                reasons.append(
                    f"Classification {cls_status}: identity "
                    f"'{identity_bt.value if identity_bt else 'N/A'}' "
                    f"vs ML top-1 '{raw_ml_snapshot.get('top1')}' "
                    f"(p={float(raw_ml_snapshot.get('top1_prob') or 0.0):.1%}) → "
                    f"保守估值路由 {_route_bt.value}"
                )

        # ---- M-32: taxonomy participates in routing (cross-family gate) ----
        # Built before model applicability so the structured identity can direct
        # routing when it conflicts with the internal identity verdict
        # (``best_bt``) across identity families. The comparison is against the
        # verdict, not ``effective_bt``, which is a deliberately conservative
        # interim route and must not be read as an identity claim. A same-family
        # difference keeps the internal route and the asset-light guardrail
        # always wins. The economics signal is the *raw* ML top-1 (pre
        # sector-hard-rule), so the reconciliation can still see a
        # statistical/prototype conflict, and the same profile object is reused
        # by attach_taxonomy_profile below.
        from classification.taxonomy import (
            build_taxonomy_profile as _build_taxonomy,
            node_archetype as _node_archetype,
            taxonomy_routing_override as _taxonomy_routing_override,
        )
        _tax_label = (
            str(raw_ml_snapshot.get("top1")) if raw_ml_snapshot is not None else best_bt.value
        )
        _tax_conf = (
            float(raw_ml_snapshot.get("top1_prob") or 0.0) if raw_ml_snapshot is not None else None
        )
        _taxonomy = _build_taxonomy(data, ml_label=_tax_label, ml_confidence=_tax_conf)
        _routed_business_type = best_bt
        _tax_bt = _taxonomy_routing_override(
            best_bt,
            _taxonomy.identity_key,
            _taxonomy.decision_status,
            guard_blocked=BusinessClassifier._asset_light_guard_blocked(
                data, _node_archetype(_taxonomy.identity_key)
            ),
        )
        if _tax_bt is not None:
            reasons.append(
                f"Taxonomy routing: 结构化身份 '{_taxonomy.identity_label}' 与内部身份 "
                f"'{best_bt.value}' 跨族冲突（{_taxonomy.decision_status.value}）"
                f" → 估值路由 {_tax_bt.value}"
            )
            effective_bt = _tax_bt
            _routed_business_type = _tax_bt

        applicable, not_applicable, na_reasons = BusinessClassifier._model_applicability(
            data, effective_bt,
            is_hybrid=is_hybrid,
            business_exposures=exposures,
        )
        characterize = BusinessClassifier._characterize_profile(data, effective_bt)

        # Ensure FinTech hybrid always sets is_financial_institution regardless of effective_bt
        if is_fintech_hybrid:
            characterize["is_financial_institution"] = True

        # ================================================================
        # ISSUE #1b — Asset-light prototype conflict
        # The numeric ML model scores by growth/margin shape and can label a
        # capital-intensive build-out as SaaS. When actual capex/revenue >= 1.0
        # with negative FCF, the label conflicts with reality: deduct confidence
        # (peer-multiple layer then re-routes to AI/Cloud Infrastructure).
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
                            f"ML label '{best_bt.value}' implies an asset-light model, but "
                            f"capex/revenue = {_capex_ratio:.0%} with negative FCF — "
                            f"capital-intensive compute build-out; confidence capped to 50%"
                        ),
                    ))
                reasons.append(
                    f"Asset-light prototype conflict: label '{best_bt.value}' vs capex/revenue="
                    f"{_capex_ratio:.0%} + negative FCF → confidence capped; peer route → compute infra"
                )
                # Surface the valuation archetype the peer layer re-routes to, so
                # the business headline no longer claims the rejected label.
                effective_business_type = "AI/Cloud Infrastructure"
                business_type_conflict_note = (
                    f"ML 标签 '{best_bt.value}'（资产轻）与实际重资产算力建设冲突"
                    f"（capex/营收={_capex_ratio:.0%}、FCF 为负）→ 估值原型重路由为 "
                    f"AI/Cloud Infrastructure"
                )

        # Ambiguous identity/economics conflict surfaces the archetype actually
        # used for valuation (unless the asset-light conflict already did).
        if cls_status == _CLS_AMBIGUOUS and effective_business_type is None:
            effective_business_type = effective_bt.value
            business_type_conflict_note = conflict_note

        profile = CompanyProfile(
            ticker=data.ticker,
            business_type=_routed_business_type.value,
            classification_confidence=round(confidence, 3),
            classification_reasons=reasons[:8],
            applicable_models=applicable,
            not_applicable_models=not_applicable,
            not_applicable_reasons=na_reasons,
            ml_probabilities=prob_map,
            top_2_candidates=top2,
            ml_model_used=True,
            ml_model_version=str(ml_result.get("model_version", "")),
            rule_fallback_triggered=False,
            # ---- Issue #1 fields ----
            ml_raw_confidence=round(ml_raw_conf, 4),
            confidence_adjustments=adjustments,
            # ---- Issue #2 fields ----
            is_hybrid_classification=is_hybrid,
            primary_business_type=primary_bt,
            secondary_business_type=secondary_bt,
            hybrid_classification_label=hybrid_label,
            classification_confidence_level=clevel,
            business_exposures=exposures,
            # ---- Asset-light prototype conflict (valuation archetype) ----
            effective_business_type=effective_business_type,
            business_type_conflict_note=business_type_conflict_note,
            # ---- Phase 1.3: identity vs economics ----
            classification_status=cls_status,
            identity_business_type=(identity_bt.value if identity_bt is not None else None),
            classification_conflict_note=conflict_note,
            **characterize,
        )

        # ---- Business Taxonomy (five dimensions) ----
        # Reuses the profile built above for the M-32 routing gate.
        from classification.taxonomy import attach_taxonomy_profile
        attach_taxonomy_profile(data, profile, tp=_taxonomy)

        return profile


__all__ = [
    "MLHybridClassifier",
    "LightGBMBusinessClassifier",
    "extract_numerical_features",
    "build_text_corpus",
    "build_synthetic_training_set",
    "build_training_set_from_csv",
    "CSV_REQUIRED_COLUMNS",
    "CSV_NUMERICAL_COLUMNS",
    "CSV_TEXT_COLUMNS",
    "ML_MODEL_PATH",
    "ML_VECTORIZER_PATH",
    "ML_META_PATH",
    "ML_FALLBACK_THRESHOLD",
    "TrainMeta",
]
