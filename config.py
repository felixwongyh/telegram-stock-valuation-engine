"""
config.py
Universal Valuation Engine - Global Configuration, Constants, Logging
"""
from __future__ import annotations

import io as _io
import logging
import os
import sys as _sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Optional as _Opt

ROOT_DIR: Path = Path(__file__).parent.resolve()

def _load_env_manually(env_path: Path) -> bool:
    if not env_path.exists():
        return False
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                os.environ.setdefault(key, value)
        return True
    except Exception:
        return False

_env_loaded = False
try:
    from dotenv import load_dotenv
    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        _env_loaded = load_dotenv(dotenv_path=env_path, override=True)
except Exception:
    _env_loaded = False

if not _env_loaded:
    _env_loaded = _load_env_manually(ROOT_DIR / ".env")

DATA_DIR: Path = ROOT_DIR / "data"
CLASSIFICATION_DIR: Path = ROOT_DIR / "classification"
FORECASTS_DIR: Path = ROOT_DIR / "forecasts"
MODELS_DIR: Path = ROOT_DIR / "models"
ANALYSIS_DIR: Path = ROOT_DIR / "analysis"
SIMULATION_DIR: Path = ROOT_DIR / "simulation"
REPORTING_DIR: Path = ROOT_DIR / "reporting"
TELEGRAM_BOT_DIR: Path = ROOT_DIR / "telegram_bot"
TESTS_DIR: Path = ROOT_DIR / "tests"
LOG_DIR: Path = ROOT_DIR / "logs"

for p in [DATA_DIR, CLASSIFICATION_DIR, FORECASTS_DIR, MODELS_DIR,
           ANALYSIS_DIR, SIMULATION_DIR, REPORTING_DIR, TELEGRAM_BOT_DIR,
           TESTS_DIR, LOG_DIR]:
    p.mkdir(parents=True, exist_ok=True)
    init_file = p / "__init__.py"
    if not init_file.exists() and p != LOG_DIR:
        init_file.touch()


LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

_log_format = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_datefmt = "%Y-%m-%d %H:%M:%S"

_log_handlers = []
_stream_handler = logging.StreamHandler()
if _sys.platform == "win32":
    try:
        _stream_handler.setStream(_io.TextIOWrapper(_sys.stderr.buffer, encoding="utf-8", errors="replace"))
    except Exception:
        pass

class _SafeFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        try:
            _sys.stderr.buffer.write((msg + "\n").encode("utf-8"))
        except Exception:
            pass
        return msg

_stream_handler.setFormatter(logging.Formatter(_log_format, datefmt=_datefmt))
_log_handlers.append(_stream_handler)

logging.basicConfig(level=LOG_LEVEL, format=_log_format, datefmt=_datefmt, handlers=_log_handlers, force=True)
logger = logging.getLogger("uve")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"uve.{name}")


# -----------------------------
# Telegram Bot
# -----------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "")
    if not raw:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# When False (default), Yahoo failures do NOT silently substitute SYNTHETIC_DATA.
YAHOO_ALLOW_SYNTHETIC_FALLBACK: bool = _env_bool("YAHOO_ALLOW_SYNTHETIC_FALLBACK", False)


# -----------------------------
# Forecast Defaults
# -----------------------------
DEFAULT_FORECAST_HORIZON_YEARS: int = 5


@dataclass
class ForecastHistoryDefaults:
    """Fallback assumptions when annual history is missing or ratios invalid."""

    rev_cagr: float = 0.05
    gross_margin: float = 0.40
    operating_margin: float = 0.15
    da_to_revenue: float = 0.05
    capex_to_revenue: float = 0.05
    marginal_nwc_ratio: float = 0.02


DEFAULT_FORECAST_HISTORY = ForecastHistoryDefaults()


@dataclass
class NwcConfig:
    """Net working capital defaults (marginal ΔNWC / ΔRevenue)."""

    default_marginal_ratio: float = 0.02
    default_level_ratio: float = 0.02
    marginal_clamp_min: float = -0.50
    marginal_clamp_max: float = 0.50
    industry_blend_historical: float = 0.70
    industry_blend_benchmark: float = 0.30
    benchmark_saas: float = -0.05
    benchmark_mature_tech: float = 0.02
    benchmark_reit: float = 0.03
    benchmark_industrial: float = 0.12


DEFAULT_NWC_CONFIG = NwcConfig()


# Used when DCF base run fails inside sensitivity grids (hidden unless documented).
SENSITIVITY_FALLBACK_WACC: float = 0.10
SENSITIVITY_FALLBACK_TERMINAL_GROWTH: float = 0.025

# -----------------------------
# DCF Defaults
# -----------------------------
@dataclass
class DCFConfig:
    risk_free_rate: float = 0.045
    equity_risk_premium: float = 0.055
    default_unlevered_beta: float = 1.1
    default_terminal_growth: float = 0.025
    min_wacc: float = 0.06
    max_wacc: float = 0.25   # raised from 0.20 to allow high-beta growth stocks
    max_terminal_growth: float = 0.045
    tax_rate: float = 0.21


DEFAULT_DCF_CONFIG = DCFConfig()

LONG_TERM_NOMINAL_GDP: float = 0.045  # 2% real + 2.5% inflation (US 10y consensus)


# -----------------------------
# Currency-aware macro anchors (Phase 1 — Valuation Integrity)
# -----------------------------
# A discount rate is only meaningful against the *currency of the cash flows*.
# Injecting a USD 10Y Treasury yield to discount HKD / CNY / MYR cash flows
# breaks the internal consistency CAPM depends on (and with it the
# terminal-growth ↔ inflation coupling). These tables give each currency a
# **static, documented** long-run 10Y sovereign anchor + nominal-GDP growth
# ceiling. They are *fallbacks* used when the live/injected rate's currency does
# not match the company's reporting currency — never a silent substitution:
# WACC records the substitution and flags the mismatch.
CURRENCY_RISK_FREE_RATES: Dict[str, float] = {
    "USD": 0.045,   # US 10Y Treasury
    "HKD": 0.045,   # HK 10Y (USD-pegged; tracks USD closely)
    "CNY": 0.023,   # China 10Y government bond
    "MYR": 0.039,   # Malaysia 10Y MGS
    "EUR": 0.030,   # Germany 10Y Bund (EUR benchmark)
    "GBP": 0.045,   # UK 10Y Gilt
    "JPY": 0.012,   # Japan 10Y JGB
    "SGD": 0.030,   # Singapore 10Y SGS
}

CURRENCY_NOMINAL_GDP: Dict[str, float] = {
    "USD": 0.045,
    "HKD": 0.040,
    "CNY": 0.055,
    "MYR": 0.055,
    "EUR": 0.035,
    "GBP": 0.040,
    "JPY": 0.015,
    "SGD": 0.040,
}

# Default macro anchor when a currency is unknown (fall back to the USD band).
DEFAULT_MACRO_CURRENCY: str = "USD"


# -----------------------------
# Reverse DCF Defaults
# -----------------------------
@dataclass
class ReverseDCFConfig:
    min_implied_cagr: float = -0.10
    max_implied_cagr: float = 0.80
    newton_max_iter: int = 100
    newton_tol: float = 1e-4
    bisection_steps: int = 60
    # ---- Phase 2: constraint-based implied solver (Session #17) ----
    # Search bounds + feasibility constraints for the one-at-a-time implied
    # solves (operating margin / FCF margin / WACC / terminal growth). Every
    # bound is a hard constraint: a solution outside it is reported as
    # NO_SOLUTION_IN_RANGE rather than clamped to the edge.
    implied_margin_lo: float = -1.00
    implied_margin_hi: float = 1.00
    implied_fcf_margin_lo: float = -1.00
    implied_fcf_margin_hi: float = 1.00
    implied_wacc_lo: float = 0.02
    implied_wacc_hi: float = 0.40
    implied_tg_lo: float = -0.02
    implied_tg_hi: float = 0.05
    implied_residual_tol: float = 1e-3
    # Number of interval samples used to *validate* the declared monotonicity of
    # the implied objective before solving (Session #18). Endpoint-only checks
    # cannot prove monotonicity, so the solver samples the interval; a violation
    # is reported as NON_MONOTONIC / MULTIPLE_ROOTS instead of trusting one root.
    implied_monotonic_samples: int = 21


DEFAULT_REVERSE_DCF_CONFIG = ReverseDCFConfig()


# ---------------------------------------------------------------------------
# Reverse DCF parameters differentiated by BusinessType
# (min_implied_cagr, max_implied_cagr, terminal_growth_override, horizon_override)
# terminal_growth_override=None means "use the dynamic TG calculator"
# horizon_override=None means "use DEFAULT_FORECAST_HORIZON_YEARS"
# ---------------------------------------------------------------------------
REVERSE_DCF_BY_TYPE: Dict[str, Dict[str, _Opt[float]]] = {
    # ---- High-growth Technology ----
    "SaaS": {
        "min_implied_cagr": -0.05,
        "max_implied_cagr": 0.80,
        "terminal_growth": 0.030,
        "horizon": 7,
    },
    "Semiconductor": {
        "min_implied_cagr": -0.10,
        "max_implied_cagr": 0.60,
        "terminal_growth": 0.025,
        "horizon": 5,
    },
    "MatureTech": {
        "min_implied_cagr": -0.08,
        "max_implied_cagr": 0.35,
        "terminal_growth": 0.025,
        "horizon": 5,
    },
    # ---- Consumer ----
    "ConsumerCyclical": {
        "min_implied_cagr": -0.05,
        "max_implied_cagr": 0.30,
        "terminal_growth": 0.020,
        "horizon": 5,
    },
    "ConsumerStaples": {
        "min_implied_cagr": -0.03,
        "max_implied_cagr": 0.15,
        "terminal_growth": 0.020,
        "horizon": 7,
    },
    # ---- Financial (Reverse DCF typically disabled, but if forced) ----
    "Bank": {
        "min_implied_cagr": -0.05,
        "max_implied_cagr": 0.20,
        "terminal_growth": 0.015,
        "horizon": 7,
    },
    "Insurance": {
        "min_implied_cagr": -0.05,
        "max_implied_cagr": 0.20,
        "terminal_growth": 0.015,
        "horizon": 7,
    },
    "FinTech": {
        "min_implied_cagr": -0.05,
        "max_implied_cagr": 0.70,
        "terminal_growth": 0.025,
        "horizon": 7,
    },
    "Neobank": {
        "min_implied_cagr": -0.05,
        "max_implied_cagr": 0.60,
        "terminal_growth": 0.020,
        "horizon": 7,
    },
    "REIT": {
        "min_implied_cagr": -0.02,
        "max_implied_cagr": 0.12,
        "terminal_growth": 0.020,
        "horizon": 10,
    },
    # ---- Real Economy (slower growth, longer horizons) ----
    "Commodity": {
        "min_implied_cagr": -0.15,
        "max_implied_cagr": 0.25,
        "terminal_growth": 0.015,
        "horizon": 5,
    },
    "Utilities": {
        "min_implied_cagr": -0.02,
        "max_implied_cagr": 0.10,
        "terminal_growth": 0.015,
        "horizon": 10,
    },
    "Energy": {
        "min_implied_cagr": -0.10,
        "max_implied_cagr": 0.25,
        "terminal_growth": 0.010,
        "horizon": 5,
    },
    "Industrial": {
        "min_implied_cagr": -0.05,
        "max_implied_cagr": 0.25,
        "terminal_growth": 0.020,
        "horizon": 7,
    },
    "Healthcare": {
        "min_implied_cagr": -0.05,
        "max_implied_cagr": 0.35,
        "terminal_growth": 0.020,
        "horizon": 7,
    },
    "Telecom": {
        "min_implied_cagr": -0.03,
        "max_implied_cagr": 0.10,
        "terminal_growth": 0.010,
        "horizon": 10,
    },
    "Media": {
        "min_implied_cagr": -0.05,
        "max_implied_cagr": 0.40,
        "terminal_growth": 0.020,
        "horizon": 5,
    },
    "Conglomerate": {
        "min_implied_cagr": -0.05,
        "max_implied_cagr": 0.20,
        "terminal_growth": 0.020,
        "horizon": 7,
    },
    # ---- Unknown: use global defaults ----
    "Unknown": {
        "min_implied_cagr": -0.10,
        "max_implied_cagr": 0.80,
        "terminal_growth": None,  # use dynamic
        "horizon": None,  # use default
    },
}


def get_reverse_dcf_config(business_type: str) -> Dict[str, _Opt[float]]:
    """Get reverse DCF parameters for a given business type.

    Returns a dict with keys: min_implied_cagr, max_implied_cagr,
    terminal_growth (may be None for dynamic), horizon (may be None for default).
    """
    return REVERSE_DCF_BY_TYPE.get(business_type, REVERSE_DCF_BY_TYPE["Unknown"])


# Taxonomy-node overrides for the implied-growth search band.
#
# The BusinessType band is too coarse for nodes whose growth economics differ
# from their parent: a merchant IPP grows with contracted capacity additions and
# power prices, not with a regulated rate base, so capping its implied growth at
# the regulated-utility 10% manufactures a "No Solution In Range" verdict that
# says nothing about the price. Mirrors CANONICAL_KEY_WACC_RANGES, which already
# splits util.ipp from the regulated nodes.
REVERSE_DCF_BY_NODE: Dict[str, Dict[str, _Opt[float]]] = {
    "util.ipp": {
        "min_implied_cagr": -0.05,
        "max_implied_cagr": 0.30,
    },
}


def get_reverse_dcf_config_for(
    business_type: str, taxonomy_key: _Opt[str] = None
) -> Dict[str, _Opt[float]]:
    """BusinessType reverse-DCF params with any taxonomy-node override applied.

    Node keys are more specific than BusinessType, so they win where they exist;
    keys the node table omits fall back to the BusinessType value.
    """
    base = dict(get_reverse_dcf_config(business_type))
    override = REVERSE_DCF_BY_NODE.get(taxonomy_key or "")
    if override:
        base.update({k: v for k, v in override.items() if v is not None})
    return base


def resolve_forecast_horizon(business_type: _Opt[str]) -> int:
    """Single source of truth for the explicit-forecast horizon (years).

    Every FCF-based consumer (DCF, Reverse DCF, Scenario, Sensitivity, Monte
    Carlo, Expectation) MUST resolve its projection window through this
    function so that (a) all models share one horizon per business type and
    (b) the horizon is *derived from the current profile* rather than read from
    a possibly-mutated shared model instance.

    Before Session #16 ``ReverseDCFModel.calculate`` did ``self.horizon = ...``
    on a singleton held in ``NAME_TO_MODEL``; an "Unknown" ticker then silently
    inherited the previous ticker's horizon (state pollution).
    """
    key = business_type if business_type is not None else "Unknown"
    cfg = REVERSE_DCF_BY_TYPE.get(key, REVERSE_DCF_BY_TYPE["Unknown"])
    h = cfg.get("horizon")
    return int(h) if h is not None else DEFAULT_FORECAST_HORIZON_YEARS


# -----------------------------
# Scenario Defaults
# -----------------------------
@dataclass
class ScenarioConfig:
    bear_revenue_mult: float = 0.7
    bear_margin_mult: float = 0.7
    bear_wacc_add: float = 0.02
    bear_tv_add: float = -0.01
    base_revenue_mult: float = 1.0
    base_margin_mult: float = 1.0
    bull_revenue_mult: float = 1.15
    bull_margin_mult: float = 1.1
    bull_wacc_add: float = -0.005
    bull_tv_add: float = 0.01


DEFAULT_SCENARIO_CONFIG = ScenarioConfig()


# -----------------------------
# Sensitivity Defaults
# -----------------------------
SENSITIVITY_DEFAULT_STEPS: int = 7
SENSITIVITY_WACC_MIN: float = 0.07
SENSITIVITY_WACC_MAX: float = 0.13
SENSITIVITY_TVG_MIN: float = 0.015
SENSITIVITY_TVG_MAX: float = 0.040


# -----------------------------
# Monte Carlo Defaults
# -----------------------------
@dataclass
class MonteCarloConfig:
    n_simulations: int = 2000
    random_seed: int = 42
    wacc_std: float = 0.015
    tg_std: float = 0.008
    # wacc_mean / tg_mean: taken from WaccCalculator + TerminalGrowthCalculator per ticker.
    #
    # ---- Configurable business bounds (Phase 2) ---------------------------
    # These are the *feasible windows* a perturbed driver may occupy. They are
    # business bounds, NOT an opinion on the central tendency: a loss-making,
    # cash-burning company keeps a negative operating-margin mean so the model
    # can honestly represent distress. The previous hard-coded `max(0.02, ...)`
    # floor on the margin mean silently turned every loss-maker into a
    # profitable one — that artificial floor has been removed.
    revenue_cagr_lower: float = -0.20
    revenue_cagr_upper: float = 0.60
    op_margin_lower: float = -0.50
    op_margin_upper: float = 0.70
    wacc_lower: float = 0.05
    wacc_upper: float = 0.25
    tg_lower: float = 0.0
    tg_upper: float = 0.05
    # Default simulation mode: "base_case" perturbs the deterministic DCF's own
    # base-case assumptions (so the distribution reconciles with the DCF anchor);
    # "historical" perturbs the raw historical statistics instead.
    mode: str = "base_case"


DEFAULT_MC_CONFIG = MonteCarloConfig()


# -----------------------------
# Enums
# -----------------------------
class BusinessType(str, Enum):
    # --- Technology ---
    MATURE_TECH = "MatureTech"
    SAAS = "SaaS"
    SEMICONDUCTOR = "Semiconductor"
    # --- Consumer ---
    CONSUMER_CYCLICAL = "ConsumerCyclical"
    CONSUMER_STAPLES = "ConsumerStaples"       # Food, Beverage, Tobacco, Household, Grocery
    # --- Financial ---
    REIT = "REIT"
    BANK = "Bank"
    INSURANCE = "Insurance"
    FINTECH = "FinTech"
    NEOBANK = "Neobank"
    # --- Real Economy ---
    COMMODITY = "Commodity"                     # Mining, Oil&Gas, Metals, Chemicals, Materials
    UTILITIES = "Utilities"                     # Electric, Water, Gas utilities (regulated)
    ENERGY = "Energy"                            # Oil&Gas E&P, Midstream, Pipeline, Refining
    INDUSTRIAL = "Industrial"                    # Aerospace, Defense, Construction, Machinery, Logistics
    HEALTHCARE = "Healthcare"                    # Pharma, Biotech, Medical Devices, Hospitals
    TELECOM = "Telecom"                          # Telecom, Wireless, Cable, Communications
    MEDIA = "Media"                              # Entertainment, Streaming, Publishing, Gaming
    CONGLOMERATE = "Conglomerate"
    UNKNOWN = "Unknown"


class ModelName(str, Enum):
    DCF = "DCF"
    REVERSE_DCF = "ReverseDCF"
    PE = "P/E"
    EV_EBITDA = "EV/EBITDA"
    EV_SALES = "EV/Sales"
    PB = "P/B"
    FCF_YIELD = "FCF Yield"
    HISTORICAL_MULTIPLES = "Historical Multiples"
    SOTP = "SOTP"
    REIT_NAV = "REIT NAV"
    REPLACEMENT_NAV = "Replacement NAV"
    UNIT_ECON_SALES = "EV/Sales (Unit Econ)"
    BANK_DDM = "Bank DDM"
    BANK_RIM = "Bank RIM"


class SolverStatus(str, Enum):
    SOLVED = "Solved"
    APPROXIMATE = "Approximate"
    NO_SOLUTION_IN_RANGE = "No Solution In Range"
    INSUFFICIENT_DATA = "Insufficient Data"
    INFEASIBLE = "Infeasible Assumptions"
    # ---- Phase 2 diagnostics (Session #18): constraint-based implied solver ----
    NON_MONOTONIC = "Non-Monotonic Objective"
    MULTIPLE_ROOTS = "Multiple Roots In Range"
    FLAT_OBJECTIVE = "Flat Objective (No Sensitivity)"


class RiskSeverity(str, Enum):
    NONE = "None"
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class RiskType(str, Enum):
    GROWTH = "Growth Risk"
    MARGIN = "Margin Risk"
    WACC = "WACC Risk"
    TERMINAL_VALUE = "Terminal Value Risk"
    LEVERAGE = "Leverage Risk"
    CONCENTRATION = "Business Concentration Risk"
    COMPETITIVE = "Competitive Risk"
    DATA_QUALITY = "Data Quality Risk"
    FORECAST = "Forecast Risk"


class ScenarioType(str, Enum):
    BEAR = "Bear"
    BASE = "Base"
    BULL = "Bull"


class DataSource(str, Enum):
    YAHOO_FINANCE = "Yahoo Finance (Real)"
    SYNTHETIC = "Synthetic Demo Data"
    USER_PROVIDED = "User Provided"
    UNKNOWN = "Unknown"


# -----------------------------
# Risk Thresholds (可解释规则)
# -----------------------------
RISK_THRESHOLDS: Dict[RiskType, Dict] = {
    RiskType.LEVERAGE: {
        "de_ratio_medium": 2.0,
        "de_ratio_high": 4.0,
        "int_cov_medium": 3.0,
        "int_cov_high": 1.5,
    },
    RiskType.TERMINAL_VALUE: {
        "tv_pct_medium": 0.65,
        "tv_pct_high": 0.80,
    },
    RiskType.GROWTH: {
        # Growth Risk measures *downside* revenue dispersion: how far, and how
        # often, revenue contracts year over year (semi-deviation of negative
        # growth w.r.t. zero). Total dispersion σ and CV = σ/|μ| both misfire:
        #   * CV explodes as the trend μ → 0 (a regulated utility SO:
        #     μ≈0.9%, σ≈10.5pp → CV≈11.9 reads "High" purely from the tiny
        #     denominator);
        #   * σ counts upward dispersion — a monotone acquisition ramp
        #     (PLD: 6.0→8.0→8.2→8.8bn, VICI: 2.6→3.6→3.8→4.0bn) is *growth*,
        #     not risk, yet σ≈14–16pp flagged it "High" (Session #33).
        # Downside deviation keeps the economically meaningful part and drops
        # both artifacts.
        "growth_dd_medium": 0.05,
        "growth_dd_high": 0.10,
    },
    RiskType.MARGIN: {
        "margin_vol_medium": 0.50,  # std / mean
        "margin_vol_high": 1.0,
        "negative_fcf_years": 2,
    },
    RiskType.DATA_QUALITY: {
        "score_medium": 70,
        "score_high": 50,
    },
    RiskType.FORECAST: {
        "horizon_gt": 10,
        # FCF-yield reference level — a *generic* anchor for a mature
        # cash-generative business. It is NOT an all-industry risk standard:
        # an asset-light compounder and a capital-heavy utility legitimately
        # sit at different yields. Only a *shortfall* below it is a valuation
        # observation; a yield ABOVE it is never risk (P0-4).
        "fcf_yield_reference": 0.04,
        # Gap magnitude = |yield − reference| / reference. Used to decide
        # whether a shortfall is material enough to surface at all.
        "positive_fcf_gap_medium": 0.10,
        "positive_fcf_gap_high": 0.25,
        # Cumulative FCF decline (latest vs oldest of the window) that marks a
        # deteriorating cash-flow trend, and the consecutive-decline count that
        # confirms persistence (P0-4).
        "fcf_decline_medium": 0.30,
        "fcf_decline_high": 0.60,
        "fcf_decline_consecutive": 2,
    },
}

# ---------------------------------------------------------------------------
# Per-share denominator comparability (P0-3)
#
# Models divide equity value by *different* share counts (forecast/TTM shares,
# market shares, EPS/BVPS denominators). A consensus median computed over mixed
# denominators compares different units. When a model's denominator deviates
# from the reference (market_cap ÷ price) by more than this relative tolerance,
# its per-share value is NOT comparable and must stay out of the consensus.
# EV / Equity Value remain available as a denominator-independent cross-check.
SHARE_COUNT_COMPARABLE_TOL: float = 0.10


# -----------------------------
# Telegram / Reporting
# -----------------------------
TELEGRAM_MAX_MESSAGE_LENGTH: int = 4000

REPORT_SECTION_TITLES: Dict[str, str] = {
    "provenance": "⚠️ 数据溯源",
    "business": "🏢 业务",
    "market": "📊 市场",
    "valuation": "💰 基本面估值",
    "scenarios": "🎭 折现率情景（Discount Rate Scenarios）",
    "operating_scenarios": "🏭 经营性情景（Operating Scenarios）",
    # ---- P0-3: Scenario description must match the actual variable ----
    "coe_sensitivity": "📉 Cost of Equity Sensitivity（权益成本敏感性）",
    "op_sensitivity": "⚙️ Operating Performance Sensitivity（经营绩效敏感性）",
    "combined_scenario": "🔀 Combined Scenario（联合情景）",
    "implied": "🔮 市场隐含预期",
    "gap": "📉 预期差距",
    "sensitivity": "🔥 敏感性",
    "models": "🤝 模型比较",
    "risk": "⚠️ 风险分析",
    "ml_prob": "🧠 ML 概率分布",
    "data": "🔍 数据质量与局限",
}


__all__ = [
    "ROOT_DIR", "DATA_DIR", "CLASSIFICATION_DIR", "FORECASTS_DIR",
    "MODELS_DIR", "ANALYSIS_DIR", "SIMULATION_DIR", "REPORTING_DIR",
    "TELEGRAM_BOT_DIR", "TESTS_DIR", "LOG_DIR",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "YAHOO_ALLOW_SYNTHETIC_FALLBACK",
    "get_logger",
    "DEFAULT_FORECAST_HORIZON_YEARS",
    "ForecastHistoryDefaults", "DEFAULT_FORECAST_HISTORY",
    "NwcConfig", "DEFAULT_NWC_CONFIG",
    "SENSITIVITY_FALLBACK_WACC", "SENSITIVITY_FALLBACK_TERMINAL_GROWTH",
    "DCFConfig", "DEFAULT_DCF_CONFIG",
    "ReverseDCFConfig", "DEFAULT_REVERSE_DCF_CONFIG", "resolve_forecast_horizon",
    "ScenarioConfig", "DEFAULT_SCENARIO_CONFIG",
    "SENSITIVITY_DEFAULT_STEPS", "SENSITIVITY_WACC_MIN", "SENSITIVITY_WACC_MAX",
    "SENSITIVITY_TVG_MIN", "SENSITIVITY_TVG_MAX", "LONG_TERM_NOMINAL_GDP",
    "CURRENCY_RISK_FREE_RATES", "CURRENCY_NOMINAL_GDP", "DEFAULT_MACRO_CURRENCY",
    "MonteCarloConfig", "DEFAULT_MC_CONFIG",
    "BusinessType", "ModelName", "SolverStatus", "RiskSeverity", "RiskType",
    "ScenarioType", "DataSource",
    "RISK_THRESHOLDS",
    "SHARE_COUNT_COMPARABLE_TOL",
    "TELEGRAM_MAX_MESSAGE_LENGTH", "REPORT_SECTION_TITLES",
    "REVERSE_DCF_BY_TYPE", "get_reverse_dcf_config",
    "REVERSE_DCF_BY_NODE", "get_reverse_dcf_config_for",
]
