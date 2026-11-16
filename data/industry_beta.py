"""data/industry_beta.py - Bottom-up (peer-derived) beta chain (H-03 → M-34).

``MarketData.industry_beta`` used to be an empty audit slot; a first pass
(Session #24) filled it with a **single unlevered peer median** obtained from
``get_companies_by_industry(industry)``. That is too coarse: two firms in the
same Yahoo industry can carry very different business risk (a fabless designer
vs. a capital-heavy foundry). This module upgrades the estimator into a
business-identity screen plus a *full* bottom-up beta chain:

  Level 1  same sub-industry + business model            (exact peers)
  Level 2  adjacent industries + similar economic shape  (approximate peers)
  Level 3  Damodaran industry benchmark                  (static last resort)

For whichever level resolves, the beta is built through the whole chain:

  Peer levered β  →  Peer unlevered β (Hamada)  →  Median unlevered β
                  →  Cash-adjusted β  →  Target-relevered β

The target-relevered value is the one CAPM consumes (M-34); the intermediate
steps stay attached to the result so the WACC is fully auditable.

Design discipline (unchanged): everything is injectable (``peer_lister`` /
``beta_fetcher`` / ``model_resolver`` / ``neighbor_lister``) so the test suite
stays offline and deterministic; a failure returns ``None`` — never a
fabricated value. The L3 benchmark is a *bundled published snapshot*
(``data/damodaran_beta.json``); an industry absent from it resolves to ``None``
rather than a guessed number.
"""
from __future__ import annotations

import json
import math
import os
import statistics
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import get_logger

log = get_logger("data.industry_beta")

_DEFAULT_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "industry_beta.json"
_DEFAULT_DAMODARAN = Path(__file__).resolve().parent / "damodaran_beta.json"
_DEFAULT_TAX = 0.21        # US statutory corporate rate
_MIN_PEERS = 3             # below this the peer median is too noisy to trust
_DEFAULT_MAX_PEERS = 10
_CASH_TO_FIRM_CAP = 0.90   # a >90% cash shell is not a business-risk proxy


# ---------------------------------------------------------------------------
# data structures
# ---------------------------------------------------------------------------
@dataclass
class PeerBeta:
    """One peer's raw beta inputs: levered regression β + capital structure."""

    beta_levered: float
    d2e: float = 0.0
    cash_to_firm: Optional[float] = None  # Cash / (MarketCap + Debt), when known


@dataclass
class PeerScreen:
    """Result of the three-level business-identity peer screen."""

    level: int              # 1 (exact) | 2 (approximate) | 3 (benchmark)
    tickers: List[str]      # empty for level 3 (benchmark carries the beta)
    industry: str
    rationale: str = ""


@dataclass
class IndustryBetaResult:
    """Auditable bottom-up beta chain (every step exposed, nothing fabricated)."""

    beta_unlevered: float
    n_peers: int
    industry: str
    level: int = 1
    beta_cash_adjusted: Optional[float] = None
    beta_relevered: Optional[float] = None
    cash_to_firm: Optional[float] = None
    target_d2e: Optional[float] = None
    tax_rate: float = _DEFAULT_TAX
    as_of: str = field(default_factory=lambda: date.today().isoformat())
    source: str = "peer-median"
    rationale: str = ""
    peer_levered: Optional[List[float]] = None
    peer_unlevered: Optional[List[float]] = None
    segments: Optional[List[Dict[str, Any]]] = None  # M-35 audit, segment-level

    def note(self) -> str:
        """Human-readable audit of the whole chain."""
        label = {
            0: "分部加权 (Segment-level)",
            1: "L1 同业（同子行业+商业模式）",
            2: "L2 相邻行业+相似经济特征",
            3: "L3 Damodaran 行业基准",
        }.get(self.level, f"L{self.level}")
        parts = [f"bottom-up β 链[{label}]"]
        if self.n_peers:
            parts.append(f"同业去杠杆中位 {self.beta_unlevered:.2f}（{self.n_peers} 家）")
        else:
            parts.append(f"去杠杆中位 {self.beta_unlevered:.2f}")
        if self.segments:
            rows: List[str] = []
            for s in self.segments:
                if s.get("beta_unlevered") is None:
                    continue
                peers = s.get("peer_levered") or []
                peers_txt = (
                    "，同业原始β["
                    + ", ".join(f"{p:.2f}" for p in peers)
                    + f"]（{s.get('n_peers') or len(peers)} 家）"
                    if peers else "，同业原始β n/a"
                )
                d2e = s.get("target_d2e")
                d2e_txt = f"，D/E={d2e:.2f}" if isinstance(d2e, (int, float)) else ""
                rsn = s.get("rationale")
                rsn_txt = f"，筛选：{rsn}" if rsn else ""
                rows.append(
                    f"{s.get('label')}→{s.get('industry')}"
                    f"（权重 {s.get('weight', 0):.0%}，L{s.get('level')} {s.get('source')}，"
                    f"unlevered β={s.get('beta_unlevered'):.2f}{d2e_txt}{peers_txt}"
                    f"，as_of {s.get('as_of')}{rsn_txt}）"
                )
            if rows:
                parts.append("分部明细：" + "；".join(rows))
        if self.beta_cash_adjusted is not None and self.cash_to_firm is not None:
            parts.append(f"现金调整(Cash/Firm {self.cash_to_firm:.0%}) → {self.beta_cash_adjusted:.2f}")
        if self.beta_relevered is not None:
            d2e_txt = f"{self.target_d2e:.2f}" if self.target_d2e is not None else "n/a"
            parts.append(f"按目标 D/E={d2e_txt} relever → {self.beta_relevered:.2f}")
        parts.append(f"as_of {self.as_of}")
        return "；".join(parts)

    def to_chain(self) -> Dict[str, Any]:
        """Full chain snapshot for ``MarketData`` / report audit."""
        return {
            "level": self.level,
            "n_peers": self.n_peers,
            "source": self.source,
            "industry": self.industry,
            "peer_median_unlevered": self.beta_unlevered,
            "cash_to_firm": self.cash_to_firm,
            "cash_adjusted": self.beta_cash_adjusted,
            "target_d2e": self.target_d2e,
            "relevered": self.beta_relevered,
            "tax_rate": self.tax_rate,
            "as_of": self.as_of,
            "rationale": self.rationale,
            "note": self.note(),
            "segments": self.segments,
        }


# ---------------------------------------------------------------------------
# beta-chain math
# ---------------------------------------------------------------------------
def _unlever(beta_l: float, d2e: float, tax: float) -> float:
    """Hamada: β_u = β_L / (1 + (1 − t)·D/E)."""
    denom = 1.0 + (1.0 - tax) * max(0.0, d2e)
    return beta_l / denom if denom > 0 else beta_l


def _relever(beta_u: float, d2e: float, tax: float) -> float:
    """Hamada (forward): β_L = β_u × (1 + (1 − t)·D/E)."""
    return beta_u * (1.0 + (1.0 - tax) * max(0.0, d2e))


def _cash_adjust(beta_u: float, cash_to_firm: Optional[float]) -> float:
    """Remove the cash drag on beta: β_business = β_firm / (1 − Cash/Firm).

    Cash is a near-risk-free asset with β ≈ 0, so holding it dilutes the
    measured firm beta; dividing by the operating weight recovers the beta of
    the *business*. Unavailable cash data → the value passes through unchanged
    (never imputed).
    """
    if cash_to_firm is None:
        return beta_u
    c = max(0.0, min(_CASH_TO_FIRM_CAP, float(cash_to_firm)))
    denom = 1.0 - c
    return beta_u / denom if denom > 0 else beta_u


# ---------------------------------------------------------------------------
# default data hooks (optional, network/DB backed)
# ---------------------------------------------------------------------------
def _default_peer_lister(industry: str, sector: Optional[str]) -> List[str]:
    """List peers in ``industry`` via FinanceDatabase (offline DB)."""
    if not industry:
        return []
    try:
        import financedatabase as fd  # type: ignore
    except Exception:
        return []
    try:
        equities = fd.Equities()
        df = equities.select(industry=industry)
        if df is None or getattr(df, "empty", True):
            return []
        return [str(s).upper() for s in df.index.tolist()]
    except Exception as e:
        log.debug(f"financedatabase peer listing failed for {industry}: {e}")
        return []


def _default_neighbor_lister(industry: str, sector: Optional[str]) -> List[str]:
    """List adjacent-industry peers via FinanceDatabase (same sector)."""
    if not sector:
        return []
    try:
        import financedatabase as fd  # type: ignore
    except Exception:
        return []
    try:
        equities = fd.Equities()
        df = equities.select(sector=sector)
        if df is None or getattr(df, "empty", True):
            return []
        tickers = [str(s).upper() for s in df.index.tolist()]
        # Adjacency = same sector, different industry: the exact-industry set is
        # already level 1, so keeping it here would just duplicate level 1.
        return tickers
    except Exception as e:
        log.debug(f"financedatabase neighbor listing failed for {sector}: {e}")
        return []


def _default_beta_fetcher(ticker: str) -> Optional[PeerBeta]:
    """Return a peer's ``PeerBeta`` (levered β, D/E, cash/firm) via yfinance."""
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return None
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as e:
        log.debug(f"peer beta fetch failed for {ticker}: {e}")
        return None
    beta = info.get("beta")
    if not isinstance(beta, (int, float)) or beta <= 0:
        return None
    d2e_raw = info.get("debtToEquity")
    # yfinance reports debtToEquity as a percentage (e.g. 154.2 == 1.542).
    d2e = float(d2e_raw) / 100.0 if isinstance(d2e_raw, (int, float)) and d2e_raw >= 0 else 0.0
    cash_to_firm: Optional[float] = None
    cash = info.get("totalCash")
    mcap = info.get("marketCap")
    debt = info.get("totalDebt")
    if isinstance(cash, (int, float)) and isinstance(mcap, (int, float)):
        firm = float(mcap) + (float(debt) if isinstance(debt, (int, float)) else 0.0)
        if firm > 0:
            cash_to_firm = max(0.0, min(_CASH_TO_FIRM_CAP, float(cash) / firm))
    return PeerBeta(beta_levered=float(beta), d2e=d2e, cash_to_firm=cash_to_firm)


def _coerce_peer_beta(row: Any) -> Optional[PeerBeta]:
    """Accept a ``PeerBeta`` or a legacy ``(β_L, D/E[, cash/firm])`` tuple."""
    if row is None:
        return None
    if isinstance(row, PeerBeta):
        return row
    if isinstance(row, (tuple, list)):
        try:
            if len(row) >= 3:
                cf = float(row[2]) if row[2] is not None else None
                return PeerBeta(float(row[0]), float(row[1]), cf)
            if len(row) == 2:
                return PeerBeta(float(row[0]), float(row[1]), None)
        except (TypeError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# three-level business-identity screen
# ---------------------------------------------------------------------------
def _profile_matches(target_ep: Any, peer_ep: Any) -> bool:
    """Compare the *shape* flags of two economic profiles (duck-typed).

    Missing data on either side is not a mismatch — we never invent a shape.
    """
    if target_ep is None or peer_ep is None:
        return True
    for attr in ("is_capex_heavy", "is_loss_making", "is_asset_light"):
        tv = getattr(target_ep, attr, None)
        pv = getattr(peer_ep, attr, None)
        if tv is not None and pv is not None and bool(tv) != bool(pv):
            return False
    return True


def get_companies_by_business_identity(
    sub_industry: Optional[str],
    business_model: Optional[str] = None,
    economic_profile: Any = None,
    *,
    sector: Optional[str] = None,
    industry_lister: Optional[Callable[[str, Optional[str]], List[str]]] = None,
    neighbor_lister: Optional[Callable[[str, Optional[str]], List[str]]] = None,
    model_resolver: Optional[Callable[[str], Optional[str]]] = None,
    profile_resolver: Optional[Callable[[str], Any]] = None,
    min_peers: int = _MIN_PEERS,
    use_neighbors: bool = True,
) -> PeerScreen:
    """Screen peers by business identity instead of raw industry membership.

    Level 1 — same sub-industry **and** business model. When ``model_resolver``
    is available we keep only peers whose model matches; otherwise the
    sub-industry set is used as-is (documented, never claimed as "same model").

    Level 2 — adjacent industries (same sector) narrowed by a similar economic
    shape when ``profile_resolver`` provides peer profiles.

    Level 3 — no peer set; the caller falls back to the Damodaran benchmark.
    """
    ind = (sub_industry or "").strip()
    if not ind:
        return PeerScreen(level=3, tickers=[], industry="", rationale="无子行业 → 仅基准")

    lister = industry_lister or _default_peer_lister
    try:
        l1 = [t for t in lister(ind, sector) if t]
    except Exception as e:
        log.debug(f"L1 peer listing failed for {ind}: {e}")
        l1 = []

    if model_resolver is not None and business_model:
        kept: List[str] = []
        for t in l1:
            try:
                if model_resolver(t) == business_model:
                    kept.append(t)
            except Exception:
                continue
        l1 = kept
        model_note = f"同商业模式({business_model})"
    else:
        model_note = "子行业内（无商业模式解析器，未按模型过滤）"

    if len(l1) >= min_peers:
        return PeerScreen(level=1, tickers=l1, industry=ind, rationale=f"L1 {model_note}")

    if not use_neighbors:
        return PeerScreen(level=3, tickers=[], industry=ind, rationale="L1 同业不足")

    nlister = neighbor_lister or _default_neighbor_lister
    try:
        l2 = [t for t in nlister(ind, sector) if t and t not in set(l1)]
    except Exception as e:
        log.debug(f"L2 neighbor listing failed for {ind}: {e}")
        l2 = []

    if profile_resolver is not None and economic_profile is not None:
        filtered: List[str] = []
        for t in l2:
            try:
                if _profile_matches(economic_profile, profile_resolver(t)):
                    filtered.append(t)
            except Exception:
                continue
        l2 = filtered
        econ_note = " + 相似经济特征"
    else:
        econ_note = "（无同业经济特征解析器，仅按行业相邻）"

    if len(l2) >= min_peers:
        return PeerScreen(level=2, tickers=l2, industry=ind, rationale=f"L2 相邻行业{econ_note}")

    return PeerScreen(level=3, tickers=[], industry=ind, rationale="L1/L2 同业不足 → 基准")


# ---------------------------------------------------------------------------
# L3 — Damodaran industry benchmark (bundled published snapshot)
# ---------------------------------------------------------------------------
# Yahoo industry string → Damodaran industry name. Only confident mappings are
# listed; everything else falls through to an exact/normalized match, and an
# unmatched industry resolves to None (never fabricated).
_DAMODARAN_ALIASES: Dict[str, str] = {
    "semiconductors": "Semiconductor",
    "semiconductor equipment & materials": "Semiconductor Equip",
    "software—application": "Software (System & Application)",
    "software—infrastructure": "Software (System & Application)",
    "software - application": "Software (System & Application)",
    "software - infrastructure": "Software (System & Application)",
    "information technology services": "Computer Services",
    "computer hardware": "Computers/Peripherals",
    "consumer electronics": "Electronics (Consumer & Office)",
    "electronic components": "Electronics (General)",
    "scientific & technical instruments": "Electrical Equipment",
    "banks—regional": "Banks (Regional)",
    "banks - regional": "Banks (Regional)",
    "banks—diversified": "Bank (Money Center)",
    "banks - diversified": "Bank (Money Center)",
    "capital markets": "Brokerage & Investment Banking",
    "asset management": "Investments & Asset Management",
    "financial conglomerates": "Financial Svcs. (Non-bank & Insurance)",
    "credit services": "Financial Svcs. (Non-bank & Insurance)",
    "insurance—property & casualty": "Insurance (Prop/Cas.)",
    "insurance—life": "Insurance (Life)",
    "insurance—diversified": "Insurance (General)",
    "reinsurance": "Reinsurance",
    "reit—retail": "Retail (REITs)",
    "reit—residential": "R.E.I.T.",
    "reit—industrial": "R.E.I.T.",
    "reit—office": "R.E.I.T.",
    "reit—specialty": "R.E.I.T.",
    "reit—healthcare facilities": "R.E.I.T.",
    "reit—diversified": "R.E.I.T.",
    "real estate—development": "Real Estate (Development)",
    "real estate services": "Real Estate (Operations & Services)",
    "oil & gas integrated": "Oil/Gas (Integrated)",
    "oil & gas e&p": "Oil/Gas (Production and Exploration)",
    "oil & gas midstream": "Oil/Gas Distribution",
    "oil & gas equipment & services": "Oilfield Svcs/Equip.",
    "biotechnology": "Drugs (Biotechnology)",
    "drug manufacturers—general": "Drugs (Pharmaceutical)",
    "drug manufacturers—specialty & generic": "Drugs (Pharmaceutical)",
    "medical devices": "Healthcare Products",
    "medical instruments & supplies": "Healthcare Products",
    "healthcare plans": "Healthcare Support Services",
    "health information services": "Heathcare Information and Technology",
    "utilities—regulated electric": "Power",
    "utilities—regulated gas": "Oil/Gas Distribution",
    "utilities—regulated water": "Utility (Water)",
    "utilities—renewable": "Green & Renewable Energy",
    "utilities—diversified": "Utility (General)",
    "airlines": "Air Transport",
    "railroads": "Transportation (Railroads)",
    "trucking": "Trucking",
    "integrated freight & logistics": "Transportation",
    "aerospace & defense": "Aerospace/Defense",
    "specialty chemicals": "Chemical (Specialty)",
    "agricultural inputs": "Chemical (Basic)",
    "packaging & containers": "Packaging & Container",
    "building materials": "Building Materials",
    "steel": "Steel",
    "gold": "Precious Metals",
    "other precious metals & mining": "Precious Metals",
    "copper": "Metals & Mining",
    "farm & heavy construction machinery": "Machinery",
    "specialty industrial machinery": "Machinery",
    "tobacco": "Tobacco",
    "beverages—non-alcoholic": "Beverage (Soft)",
    "beverages—brewers": "Beverage (Alcoholic)",
    "beverages—wineries & distilleries": "Beverage (Alcoholic)",
    "restaurants": "Restaurant/Dining",
    "apparel retail": "Retail (Special Lines)",
    "home improvement retail": "Retail (Building Supply)",
    "discount stores": "Retail (General)",
    "grocery stores": "Retail (Grocery and Food)",
    "auto manufacturers": "Auto & Truck",
    "auto parts": "Auto Parts",
    "entertainment": "Entertainment",
    "publishing": "Publishing & Newspapers",
    "broadcasting": "Broadcasting",
    "telecom services": "Telecom. Services",
    "internet content & information": "Software (Internet)",
    "advertising agencies": "Advertising",
    "education & training services": "Education",
    "staffing & employment services": "Business & Consumer Services",
    "consulting services": "Business & Consumer Services",
    "waste management": "Environmental & Waste Services",
    "paper & paper products": "Paper/Forest Products",
    "household & personal products": "Household Products",
    "food distribution": "Food Wholesalers",
    "packaged foods": "Food Processing",
}


def _normalize_industry(name: str) -> str:
    return name.strip().lower().replace("–", "-").replace("—", "-")


def _damodaran_lookup(
    industry: str, path: Optional[Path] = None
) -> Optional[Tuple[float, float]]:
    """Return ``(unlevered_beta, cash_adjusted_beta)`` for an industry, or None."""
    file = Path(path) if path else _DEFAULT_DAMODARAN
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except Exception:
        return None
    table = payload.get("industries") if isinstance(payload, dict) else None
    if not isinstance(table, dict):
        return None

    norm = _normalize_industry(industry)
    canonical = _DAMODARAN_ALIASES.get(_normalize_industry(industry))
    candidates = [canonical] if canonical else []
    candidates.append(industry)
    candidates.extend(k for k in table if _normalize_industry(k) == norm)

    for key in candidates:
        if key and key in table:
            row = table[key]
            ub = row.get("unlevered_beta")
            ca = row.get("unlevered_beta_cash_adjusted")
            if isinstance(ub, (int, float)):
                return float(ub), (float(ca) if isinstance(ca, (int, float)) else float(ub))
    return None


# ---------------------------------------------------------------------------
# peer chain assembly
# ---------------------------------------------------------------------------
def _collect_peer_chain(
    tickers: List[str],
    fetcher: Callable[[str], Any],
    target: str,
    max_peers: int,
    tax: float,
) -> Tuple[List[float], List[float], List[float]]:
    """Fetch up to ``max_peers`` peers and return the levered/unlevered/cash lists."""
    peer_levered: List[float] = []
    peer_unlevered: List[float] = []
    cash_ratios: List[float] = []
    for t in tickers:
        if len(peer_levered) >= max_peers:
            break
        if t.upper() == target:
            continue
        try:
            row = _coerce_peer_beta(fetcher(t))
        except Exception:
            row = None
        if row is None:
            continue
        if not math.isfinite(row.beta_levered) or row.beta_levered <= 0:
            continue
        peer_levered.append(row.beta_levered)
        peer_unlevered.append(_unlever(row.beta_levered, row.d2e, tax))
        if row.cash_to_firm is not None and math.isfinite(row.cash_to_firm):
            cash_ratios.append(row.cash_to_firm)
    return peer_levered, peer_unlevered, cash_ratios


def _build_result(
    *,
    industry: str,
    level: int,
    n_peers: int,
    beta_unlevered: float,
    cash_to_firm: Optional[float],
    beta_cash_adjusted: float,
    target_d2e: Optional[float],
    tax: float,
    source: str,
    rationale: str,
    peer_levered: Optional[List[float]] = None,
    peer_unlevered: Optional[List[float]] = None,
    segments: Optional[List[Dict[str, Any]]] = None,
) -> IndustryBetaResult:
    beta_relevered = round(_relever(beta_cash_adjusted, target_d2e or 0.0, tax), 4)
    return IndustryBetaResult(
        beta_unlevered=round(beta_unlevered, 4),
        n_peers=n_peers,
        industry=industry,
        level=level,
        beta_cash_adjusted=round(beta_cash_adjusted, 4),
        beta_relevered=beta_relevered,
        cash_to_firm=cash_to_firm,
        target_d2e=target_d2e,
        tax_rate=tax,
        source=source,
        rationale=rationale,
        peer_levered=peer_levered,
        peer_unlevered=peer_unlevered,
        segments=segments,
    )


# ---------------------------------------------------------------------------
# M-35 — segment-level beta (multi-business companies)
# ---------------------------------------------------------------------------
# Segment label keyword → Yahoo industry, most-specific first. Only segments
# whose label maps to a *resolvable* industry contribute; everything else is
# dropped (never guessed). Industries are chosen to also hit the Damodaran
# alias table so a segment can fall back to the L3 benchmark.
_SEGMENT_INDUSTRY_KEYWORDS: Tuple[Tuple[str, str], ...] = (
    ("semiconductor", "Semiconductors"),
    ("chip", "Semiconductors"),
    ("wafer", "Semiconductor Equipment & Materials"),
    ("pharmaceutical", "Drug Manufacturers - General"),
    ("biotech", "Biotechnology"),
    ("medical device", "Medical Devices"),
    ("cloud", "Information Technology Services"),
    ("aws", "Information Technology Services"),
    ("data center", "Information Technology Services"),
    ("saas", "Software - Application"),
    ("software", "Software - Infrastructure"),
    ("subscription", "Software - Application"),
    ("advertising", "Advertising Agencies"),
    ("search", "Internet Content & Information"),
    ("streaming", "Entertainment"),
    ("media", "Entertainment"),
    ("content", "Entertainment"),
    ("iphone", "Consumer Electronics"),
    ("smartphone", "Consumer Electronics"),
    ("wearable", "Consumer Electronics"),
    ("ipad", "Computer Hardware"),
    ("mac", "Computer Hardware"),
    ("hardware", "Computer Hardware"),
    ("device", "Consumer Electronics"),
    ("insurance", "Insurance - Diversified"),
    ("bank", "Banks - Diversified"),
    ("credit", "Credit Services"),
    ("asset management", "Asset Management"),
    # --- M-35 real-corpus additions (Session #27, FMP /stable segment labels) ---
    # Business-line vocabulary generalised from ~90 multi-segment issuers.
    # Non-segment buckets ("Other", "Corporate", "All Other", geographic
    # regions, XBRL reconciling items, drug brand names) are intentionally left
    # unmapped so they are dropped instead of guessed.
    ("aeronautics", "Aerospace & Defense"),
    ("commercial airplanes", "Aerospace & Defense"),
    ("rotary and mission", "Aerospace & Defense"),
    ("missiles and fire control", "Aerospace & Defense"),
    ("biopharma", "Drug Manufacturers - General"),
    ("innovative medicine", "Drug Manufacturers - General"),
    ("medtech", "Medical Devices"),
    ("medical technology", "Medical Devices"),
    ("upstream", "Oil & Gas E&P"),
    ("downstream", "Oil & Gas Refining & Marketing"),
    ("refinery", "Oil & Gas Refining & Marketing"),
    ("midstream", "Oil & Gas Midstream"),
    ("exploration and production", "Oil & Gas E&P"),
    ("energy generation", "Utilities - Renewable"),
    ("foundry", "Semiconductors"),
    ("client computing", "Semiconductors"),
    ("embedded", "Semiconductors"),
    ("asset and wealth management", "Asset Management"),
    ("investment management", "Asset Management"),
    ("wealth", "Asset Management"),
    ("commercial and investment bank", "Banks - Diversified"),
    ("investment bank", "Capital Markets"),
    ("global markets", "Capital Markets"),
    ("transaction revenues", "Credit Services"),
    ("broadband", "Telecom Services"),
    ("voice and data", "Telecom Services"),
    ("youtube", "Internet Content & Information"),
    ("linkedin", "Internet Content & Information"),
    ("windows", "Software - Infrastructure"),
    ("theme park", "Entertainment"),
    ("resorts", "Entertainment"),
    ("online stores", "Internet Retail"),
    ("hardlines", "Discount Stores"),
    ("concentrate operations", "Beverages - Non-Alcoholic"),
    ("finished product operations", "Beverages - Non-Alcoholic"),
    ("apparel", "Apparel Retail"),
    ("footwear", "Footwear & Accessories"),
    # --- M-35 round 2 (Session #27): residual generalisable business-line words ---
    # After round 1 the uncovered labels that remain are overwhelmingly NOT
    # mappable and are deliberately left out: non-segment buckets ("Other",
    # "Corporate", "…and Eliminations"), geographic regions ("Africa, Middle
    # East and South Asia", "Latin America (Segment)"), issuer-specific drug
    # brand names ("Botox", "RINVOQ", …) and issuer acronyms ("GMI", "GMNA").
    # Only words that recur as a genuine business line across issuers are
    # added here (each also lands on a Damodaran-aliased industry for L3).
    ("space", "Aerospace & Defense"),
    ("print and publishing", "Publishing"),
    ("publishing", "Publishing"),
    ("data processing", "Information Technology Services"),
    ("energy products", "Oil & Gas Refining & Marketing"),
    ("digital experience", "Software - Application"),
    ("investment", "Capital Markets"),
    ("retail", "Internet Retail"),
    ("e-commerce", "Internet Retail"),
    ("grocery", "Grocery Stores"),
    ("restaurant", "Restaurants"),
    ("beverage", "Beverages - Non-Alcoholic"),
    ("food", "Packaged Foods"),
    ("refining", "Oil & Gas Refining & Marketing"),
    ("oil", "Oil & Gas Integrated"),
    ("chemical", "Specialty Chemicals"),
    ("mining", "Other Industrial Metals & Mining"),
    ("steel", "Steel"),
    ("utility", "Utilities - Regulated Electric"),
    ("electric", "Utilities - Regulated Electric"),
    ("renewable", "Utilities - Renewable"),
    ("airline", "Airlines"),
    ("aerospace", "Aerospace & Defense"),
    ("defense", "Aerospace & Defense"),
    ("railroad", "Railroads"),
    ("logistics", "Integrated Freight & Logistics"),
    ("freight", "Integrated Freight & Logistics"),
    ("real estate", "Real Estate Services"),
    ("homebuild", "Residential Construction"),
    ("machinery", "Specialty Industrial Machinery"),
    ("auto", "Auto Manufacturers"),
    ("vehicle", "Auto Manufacturers"),
    ("telecom", "Telecom Services"),
    ("wireless", "Telecom Services"),
    ("network", "Communication Equipment"),
    ("consulting", "Consulting Services"),
    ("service", "Information Technology Services"),
)

_MIN_SEGMENT_COVERAGE = 0.60  # resolved-weight share below which we fall back


def _default_segment_industry_resolver(label: str) -> Optional[str]:
    """Map a segment label to a Yahoo industry via keyword matching (or None)."""
    low = (label or "").lower()
    for kw, industry in _SEGMENT_INDUSTRY_KEYWORDS:
        if kw in low:
            return industry
    return None


def _coerce_segments(segments: Any) -> List[Tuple[str, float]]:
    """Accept ``[(label, weight)]`` or objects exposing ``label`` / ``weight``."""
    out: List[Tuple[str, float]] = []
    for item in segments or []:
        label: Optional[str] = None
        weight: Optional[float] = None
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            label, weight = str(item[0]), item[1]
        else:
            label = getattr(item, "label", None)
            weight = getattr(item, "weight", None)
        if not label or weight is None:
            continue
        try:
            w = float(weight)
        except (TypeError, ValueError):
            continue
        if w > 0:
            out.append((label, w))
    return out


def derive_segment_level_beta(
    ticker: str,
    segments: Any,
    *,
    sector: Optional[str] = None,
    target_d2e: Optional[float] = None,
    target_tax_rate: Optional[float] = None,
    cash_to_firm: Optional[float] = None,
    segment_industry_resolver: Optional[Callable[[str], Optional[str]]] = None,
    beta_provider: Optional[Callable[..., Optional[IndustryBetaResult]]] = None,
    benchmark_path: Optional[Path] = None,
    offline: bool = False,
    min_coverage: float = _MIN_SEGMENT_COVERAGE,
    min_segments: int = 2,
) -> Optional[IndustryBetaResult]:
    """Aggregate per-segment bottom-up β into a company-level equity beta (M-35).

    For each segment: label → industry (keyword resolver by default) → the same
    three-level business-identity chain used at company level → segment
    unlevered β. Segments are weighted (revenue/business-value weights supplied
    by the caller, renormalised over the resolvable subset), summed to a company
    unlevered β, cash-adjusted and re-levered to the target D/E.

    Returns ``None`` (never a fabricated value) when fewer than ``min_segments``
    resolve, or when the resolvable weight share is below ``min_coverage`` — the
    caller then keeps the company-level beta.
    """
    if offline or os.environ.get("BOTTOM_UP_BETA", "1") == "0":
        return None
    pairs = _coerce_segments(segments)
    if len(pairs) < min_segments:
        return None

    tax = target_tax_rate if target_tax_rate is not None else _DEFAULT_TAX
    resolver = segment_industry_resolver or _default_segment_industry_resolver
    provider = beta_provider or derive_bottom_up_beta

    breakdown: List[Dict[str, Any]] = []
    resolved: List[Tuple[float, float]] = []  # (weight, beta_u)
    dropped: List[str] = []
    for label, weight in pairs:
        try:
            industry = resolver(label)
        except Exception:
            industry = None
        if not industry:
            dropped.append(label)
            continue
        try:
            seg_res = provider(
                ticker,
                sector,
                industry,
                target_d2e=None,
                target_tax_rate=tax,
                benchmark_path=benchmark_path,
            )
        except Exception:
            seg_res = None
        if seg_res is None:
            dropped.append(label)
            continue
        beta_u = seg_res.beta_unlevered
        resolved.append((weight, beta_u))
        breakdown.append(
            {
                "label": label,
                "industry": industry,
                "weight": round(weight, 4),
                "beta_unlevered": round(float(beta_u), 4),
                "level": seg_res.level,
                "source": seg_res.source,
                # Phase E — per-segment audit evidence: which peers, their raw
                # betas, the segment D/E, the screening rationale and the as-of
                # date, so a segment β is traceable back to its inputs.
                "n_peers": seg_res.n_peers,
                "peer_levered": [round(x, 4) for x in (seg_res.peer_levered or [])],
                "peer_unlevered": [round(x, 4) for x in (seg_res.peer_unlevered or [])],
                "target_d2e": seg_res.target_d2e,
                "as_of": seg_res.as_of,
                "rationale": seg_res.rationale,
            }
        )

    if len(resolved) < min_segments:
        return None
    coverage = sum(w for w, _ in resolved)
    if coverage <= 0 or coverage < min_coverage:
        return None

    beta_u_company = sum((w / coverage) * b for w, b in resolved)
    cash_adjusted = _cash_adjust(beta_u_company, cash_to_firm)
    for row in breakdown:  # renormalise the audit weights to the covered subset
        row["weight"] = round(row["weight"] / coverage, 4)

    rationale = f"分部加权（{len(resolved)}/{len(pairs)} 分部可解析，覆盖权重 {coverage:.0%}）"
    if dropped:
        rationale += f"；未解析：{', '.join(dropped[:4])}"
    return _build_result(
        industry=f"{len(resolved)}-segment mix",
        level=0,
        n_peers=len(resolved),
        beta_unlevered=beta_u_company,
        cash_to_firm=cash_to_firm,
        beta_cash_adjusted=cash_adjusted,
        target_d2e=target_d2e,
        tax=tax,
        source="segment-weighted",
        rationale=rationale,
        segments=breakdown,
    )


# ---------------------------------------------------------------------------
# public API — full three-level chain
# ---------------------------------------------------------------------------
def derive_bottom_up_beta(
    ticker: str,
    sector: Optional[str],
    industry: Optional[str],
    *,
    sub_industry: Optional[str] = None,
    business_model: Optional[str] = None,
    economic_profile: Any = None,
    target_d2e: Optional[float] = None,
    target_tax_rate: Optional[float] = None,
    peer_lister: Optional[Callable[[str, Optional[str]], List[str]]] = None,
    neighbor_lister: Optional[Callable[[str, Optional[str]], List[str]]] = None,
    beta_fetcher: Optional[Callable[[str], Any]] = None,
    model_resolver: Optional[Callable[[str], Optional[str]]] = None,
    profile_resolver: Optional[Callable[[str], Any]] = None,
    max_peers: int = _DEFAULT_MAX_PEERS,
    tax_rate: float = _DEFAULT_TAX,
    cache_path: Optional[Path] = None,
    offline: bool = False,
    use_neighbors: bool = True,
    use_benchmark: bool = True,
    benchmark_path: Optional[Path] = None,
    segments: Any = None,
    segment_industry_resolver: Optional[Callable[[str], Optional[str]]] = None,
    segment_cash_to_firm: Optional[float] = None,
    segment_beta_provider: Optional[Callable[..., Optional[IndustryBetaResult]]] = None,
) -> Optional[IndustryBetaResult]:
    """Derive the full bottom-up beta chain for a target company.

    Screening escalates level 1 → 2 → 3; at each level the beta is built as
    peer-levered → peer-unlevered → median → cash-adjusted → target-relevered.
    When ``segments`` (``[(label, weight)]``) are supplied and enough of them
    resolve to a segment beta (M-35), the segment-weighted aggregate is used
    instead of the company-level chain. Returns ``None`` when no level resolves
    (never a fabricated value).
    """
    if offline or os.environ.get("BOTTOM_UP_BETA", "1") == "0":
        return None

    tax = target_tax_rate if target_tax_rate is not None else tax_rate

    if segments:
        seg = derive_segment_level_beta(
            ticker,
            segments,
            sector=sector,
            target_d2e=target_d2e,
            target_tax_rate=tax,
            cash_to_firm=segment_cash_to_firm,
            segment_industry_resolver=segment_industry_resolver,
            beta_provider=segment_beta_provider,
            benchmark_path=benchmark_path,
            offline=offline,
        )
        if seg is not None:
            return seg

    ind = (sub_industry or industry or "").strip()
    if not ind:
        return None
    target = (ticker or "").upper().strip()

    cache_file = Path(cache_path) if cache_path else _DEFAULT_CACHE
    key = f"{(sector or '').strip()}|{ind}" + (f"|{business_model}" if business_model else "")
    cached = _load_cache(cache_file)
    if key in cached:
        return _result_from_cache(cached[key], ind, target_d2e, tax)

    lister = peer_lister or _default_peer_lister
    fetcher = beta_fetcher or _default_beta_fetcher

    screen = get_companies_by_business_identity(
        ind,
        business_model,
        economic_profile,
        sector=sector,
        industry_lister=lister,
        neighbor_lister=neighbor_lister,
        model_resolver=model_resolver,
        profile_resolver=profile_resolver,
        min_peers=_MIN_PEERS,
        use_neighbors=use_neighbors,
    )

    result: Optional[IndustryBetaResult] = None

    if screen.level in (1, 2):
        peer_levered, peer_unlevered, cash_ratios = _collect_peer_chain(
            screen.tickers, fetcher, target, max_peers, tax
        )
        if len(peer_unlevered) >= _MIN_PEERS:
            median_unlevered = statistics.median(peer_unlevered)
            cash_med = round(statistics.median(cash_ratios), 4) if cash_ratios else None
            cash_adjusted = _cash_adjust(median_unlevered, cash_med)
            result = _build_result(
                industry=ind,
                level=screen.level,
                n_peers=len(peer_unlevered),
                beta_unlevered=median_unlevered,
                cash_to_firm=cash_med,
                beta_cash_adjusted=cash_adjusted,
                target_d2e=target_d2e,
                tax=tax,
                source="peer-median",
                rationale=screen.rationale,
                peer_levered=[round(x, 4) for x in peer_levered],
                peer_unlevered=[round(x, 4) for x in peer_unlevered],
            )

    if result is None and use_benchmark:
        bench = _damodaran_lookup(ind, benchmark_path)
        if bench is not None:
            ub, ca = bench
            result = _build_result(
                industry=ind,
                level=3,
                n_peers=0,
                beta_unlevered=ub,
                cash_to_firm=None,
                beta_cash_adjusted=ca,
                target_d2e=target_d2e,
                tax=tax,
                source="damodaran-benchmark",
                rationale=f"L3 Damodaran 基准（{ind}）",
            )

    if result is None:
        log.debug(f"bottom-up beta for {ind}: no level resolved (no fabrication)")
        return None

    _store_cache(cache_file, key, result)
    return result


def derive_industry_unlevered_beta(
    ticker: str,
    sector: Optional[str],
    industry: Optional[str],
    *,
    peer_lister: Optional[Callable[[str, Optional[str]], List[str]]] = None,
    beta_fetcher: Optional[Callable[[str], Any]] = None,
    max_peers: int = _DEFAULT_MAX_PEERS,
    tax_rate: float = _DEFAULT_TAX,
    cache_path: Optional[Path] = None,
    offline: bool = False,
) -> Optional[float]:
    """Peer-only unlevered β (level 1, no L2/L3 escalation).

    Retained as the narrow "raw peer median" accessor; use
    :func:`derive_bottom_up_beta` for the full screened chain used by WACC.
    Returns ``None`` when fewer than ``_MIN_PEERS`` peers are usable.
    """
    res = derive_bottom_up_beta(
        ticker,
        sector,
        industry,
        peer_lister=peer_lister,
        beta_fetcher=beta_fetcher,
        max_peers=max_peers,
        tax_rate=tax_rate,
        cache_path=cache_path,
        offline=offline,
        use_neighbors=False,
        use_benchmark=False,
    )
    return res.beta_unlevered if res is not None else None


# ---------------------------------------------------------------------------
# cache helpers
# ---------------------------------------------------------------------------
def _cache_payload(result: IndustryBetaResult) -> Dict[str, Any]:
    """Only the *peer-dependent* part is cached; the target relever is per-call."""
    return {
        "beta_unlevered": result.beta_unlevered,
        "beta_cash_adjusted": result.beta_cash_adjusted,
        "cash_to_firm": result.cash_to_firm,
        "n_peers": result.n_peers,
        "level": result.level,
        "source": result.source,
        "rationale": result.rationale,
        "as_of": result.as_of,
        "peer_levered": result.peer_levered,
        "peer_unlevered": result.peer_unlevered,
    }


def _result_from_cache(
    payload: Dict[str, Any], industry: str, target_d2e: Optional[float], tax: float
) -> Optional[IndustryBetaResult]:
    ub = payload.get("beta_unlevered")
    if not isinstance(ub, (int, float)):
        return None
    ca = payload.get("beta_cash_adjusted")
    cash_adjusted = float(ca) if isinstance(ca, (int, float)) else float(ub)
    return _build_result(
        industry=industry,
        level=int(payload.get("level", 1)),
        n_peers=int(payload.get("n_peers", 0)),
        beta_unlevered=float(ub),
        cash_to_firm=(payload.get("cash_to_firm") if isinstance(payload.get("cash_to_firm"), (int, float)) else None),
        beta_cash_adjusted=cash_adjusted,
        target_d2e=target_d2e,
        tax=tax,
        source=str(payload.get("source", "peer-median")),
        rationale=str(payload.get("rationale", "")),
        peer_levered=payload.get("peer_levered"),
        peer_unlevered=payload.get("peer_unlevered"),
    )


def _load_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _store_cache(path: Path, key: str, result: IndustryBetaResult) -> None:
    data = _load_cache(path)
    data[key] = _cache_payload(result)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=0, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    except Exception as e:
        log.debug(f"industry beta cache write failed: {e}")


__all__ = [
    "IndustryBetaResult",
    "PeerBeta",
    "PeerScreen",
    "derive_bottom_up_beta",
    "derive_industry_unlevered_beta",
    "derive_segment_level_beta",
    "get_companies_by_business_identity",
]
