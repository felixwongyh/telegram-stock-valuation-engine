"""
config.py
Universal Valuation Engine - Global Configuration, Constants, Logging
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

import sys as _sys
import io as _io

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
    max_wacc: float = 0.20
    max_terminal_growth: float = 0.045
    tax_rate: float = 0.21


DEFAULT_DCF_CONFIG = DCFConfig()

LONG_TERM_NOMINAL_GDP: float = 0.045  # 2% real + 2.5% inflation (US 10y consensus)


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


DEFAULT_REVERSE_DCF_CONFIG = ReverseDCFConfig()


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


DEFAULT_MC_CONFIG = MonteCarloConfig()


# -----------------------------
# Enums
# -----------------------------
class BusinessType(str, Enum):
    MATURE_TECH = "MatureTech"
    SAAS = "SaaS"
    SEMICONDUCTOR = "Semiconductor"
    CONSUMER_CYCLICAL = "ConsumerCyclical"
    REIT = "REIT"
    BANK = "Bank"
    INSURANCE = "Insurance"
    COMMODITY = "Commodity"
    UTILITIES = "Utilities"
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
    BANK_DDM = "Bank DDM"
    BANK_RIM = "Bank RIM"


class SolverStatus(str, Enum):
    SOLVED = "Solved"
    APPROXIMATE = "Approximate"
    NO_SOLUTION_IN_RANGE = "No Solution In Range"
    INSUFFICIENT_DATA = "Insufficient Data"
    INFEASIBLE = "Infeasible Assumptions"


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
        "growth_vol_medium": 0.30,
        "growth_vol_high": 0.60,
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
        "positive_fcf_gap_medium": 0.10,
        "positive_fcf_gap_high": 0.25,
    },
}


# -----------------------------
# Telegram / Reporting
# -----------------------------
TELEGRAM_MAX_MESSAGE_LENGTH: int = 4000

REPORT_SECTION_TITLES: Dict[str, str] = {
    "provenance": "⚠️ 数据溯源",
    "business": "🏢 业务",
    "market": "📊 市场",
    "valuation": "💰 基本面估值",
    "scenarios": "🎭 情景分析",
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
    "ReverseDCFConfig", "DEFAULT_REVERSE_DCF_CONFIG",
    "ScenarioConfig", "DEFAULT_SCENARIO_CONFIG",
    "SENSITIVITY_DEFAULT_STEPS", "SENSITIVITY_WACC_MIN", "SENSITIVITY_WACC_MAX",
    "SENSITIVITY_TVG_MIN", "SENSITIVITY_TVG_MAX", "LONG_TERM_NOMINAL_GDP",
    "MonteCarloConfig", "DEFAULT_MC_CONFIG",
    "BusinessType", "ModelName", "SolverStatus", "RiskSeverity", "RiskType",
    "ScenarioType", "DataSource",
    "RISK_THRESHOLDS",
    "TELEGRAM_MAX_MESSAGE_LENGTH", "REPORT_SECTION_TITLES",
]
