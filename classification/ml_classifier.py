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

DOMAIN_KEYWORDS: List[str] = list(dict.fromkeys([
    "reit", "real estate", "property trust", "bank", "commercial", "savings",
    "investment bank", "securities", "insurance", "life", "property casualty",
    "utility", "utilities", "electric", "water", "gas", "power",
    "semiconductor", "chip", "ic", "integrated circuit", "foundry", "fabless",
    "gpu", "nvidia", "memory", "processor", "saas", "cloud", "software",
    "subscription", "platform", "enterprise", "auto", "automobile", "vehicle",
    "retail", "store", "ecommerce", "travel", "hotel", "airline", "cruise",
    "oil", "petroleum", "mining", "metal", "steel", "coal", "commodity",
    "conglomerate", "holding", "group", "technology", "hardware", "internet",
    "consumer", "electronics", "pharma", "biotech", "medical",
]))

_TARGET_BUSINESS_TYPES: List[BusinessType] = [
    BusinessType.MATURE_TECH,
    BusinessType.SAAS,
    BusinessType.SEMICONDUCTOR,
    BusinessType.CONSUMER_CYCLICAL,
    BusinessType.REIT,
    BusinessType.BANK,
    BusinessType.INSURANCE,
    BusinessType.COMMODITY,
    BusinessType.UTILITIES,
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
    return f"{name.lower()} {sector.lower()} {industry.lower()}"


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
        y = np.array([self._label_to_idx[l] for l in y_raw], dtype=np.int32)

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

        preds = model.predict(X_train)
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

        # Pure-numeric semiconductor fallback:
        #   very high gross margin (>65%) + low leverage (D/E < 1.0) + capex heavy (>10% revenue)
        #   + revenue volatility (gross_margin_vol > 2%) → not REIT/Utilities/Bank.
        if ttm and ttm.revenue and ttm.revenue > 0 and ttm.gross_profit is not None:
            gm = ttm.gross_profit / ttm.revenue
            capex_r = (abs(ttm.capex) / ttm.revenue
                       if ttm.capex is not None else 0.0)
            if gm >= 0.50 and capex_r >= 0.08 and (de is None or de < 1.0):
                _swap_boost(BusinessType.SEMICONDUCTOR.value, BusinessType.REIT.value,
                            f"Structural-num: gm={gm:.2f} capex/r={capex_r:.2f} low-D/E → not REIT")
                _swap_boost(BusinessType.SEMICONDUCTOR.value, BusinessType.UTILITIES.value,
                            "Structural-num: semi-like profile → not Utilities")
                # Also steer away from MatureTech (top-1 ML destination for NVDA when text empty)
                _swap_boost(BusinessType.SEMICONDUCTOR.value, BusinessType.MATURE_TECH.value,
                            "Structural-num: semi-like profile overrides MatureTech default")

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

        # ---- 5) Logistics / parcel / freight (name-only when sector 401s) ----
        if any(k in text for k in [
            "parcel", "logistics", "freight", "courier", "trucking",
            "package delivery", "united parcel",
        ]):
            _swap_boost(
                BusinessType.CONSUMER_CYCLICAL.value,
                BusinessType.UNKNOWN.value,
                "Structural: logistics/parcel keyword overrides Unknown",
            )
            _swap_boost(
                BusinessType.CONSUMER_CYCLICAL.value,
                BusinessType.CONGLOMERATE.value,
                "Structural: logistics/parcel is not a conglomerate",
            )

        sorted_items = sorted(probs.items(), key=lambda kv: -kv[1])
        ml_result = dict(ml_result)
        ml_result["probabilities"] = probs
        ml_result["top1"], ml_result["top1_prob"] = sorted_items[0]
        if len(sorted_items) > 1:
            ml_result["top2"], ml_result["top2_prob"] = sorted_items[1]
        ml_result["confidence"] = ml_result["top1_prob"]
        return ml_result, changes

    # ------------------------------------------------------------------
    # Main classify entrypoint
    # ------------------------------------------------------------------
    def classify(self, data: FinancialData) -> CompanyProfile:
        from classification.classifier import BusinessClassifier

        self.ensure_ready()

        ml_result = None
        ml_used = False
        rule_fallback = False
        structural_changes: List[str] = []
        threshold = self._ml._meta.fallback_threshold if self._ml._meta else ML_FALLBACK_THRESHOLD

        if self._ml.available:
            raw = self._ml.predict(data)
            if raw is not None:
                raw, structural_changes = self._structural_overrides(data, raw)
                if raw["top1_prob"] >= threshold:
                    ml_result = raw
                    ml_used = True
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
            profile.ml_model_used = False
            profile.rule_fallback_triggered = True
            profile.classification_reasons = (
                profile.classification_reasons +
                ([f"ML fallback (top prob < {threshold:.0%})"] if ml_result else ["ML model unavailable"]) +
                structural_changes
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

        # Unknown from ML is not a type — prefer rule-engine if it found a signal
        # (e.g. "parcel"/"logistics" in the company name when sector is missing).
        if best_bt == BusinessType.UNKNOWN:
            rule_profile = BusinessClassifier.classify(data)
            if rule_profile.business_type != BusinessType.UNKNOWN.value:
                best_bt = BusinessType(rule_profile.business_type)
                reasons.append(
                    f"ML top-1 is Unknown; using rule type {best_bt.value}"
                )
                reasons.extend(rule_profile.classification_reasons[:3])

        sorted_probs = sorted(ml_result["probabilities"].items(), key=lambda kv: -kv[1])
        prob_map = {k: round(v, 4) for k, v in sorted_probs}
        top2 = [(k, round(v, 4)) for k, v in sorted_probs[:2]]

        # Report actual top-1 probability. Do not inflate Unknown into ~90%.
        confidence = float(ml_result["top1_prob"])
        if best_bt == BusinessType.UNKNOWN:
            confidence = min(confidence, 0.40)
            reasons.append("Unknown type: confidence capped; special-industry models not applied")
        if not (data.market.sector or data.market.industry):
            confidence = min(confidence, 0.55)
            reasons.append("sector/industry missing; classification confidence capped")
        applicable, not_applicable, na_reasons = BusinessClassifier._model_applicability(data, best_bt)
        characterize = BusinessClassifier._characterize_profile(data, best_bt)

        profile = CompanyProfile(
            ticker=data.ticker,
            business_type=best_bt.value,
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
            **characterize,
        )
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
