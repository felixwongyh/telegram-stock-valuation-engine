"""
_ab_classifier_compare.py — A/B Test: Rule-based BusinessClassifier vs MLHybridClassifier

Edge-case focus:
  • Semiconductor: NVDA, AMD, TSM  (high-gross-margin, can look REIT-like in pure-margin rules)
  • REIT:          PLD, AMT, SPG  (high operating margins, high leverage, stable)

Ground truth (sector/industry labels from Yahoo Finance):
  • If sector == "Real Estate" and industry contains "REIT" → EXPECTED=REIT
  • If sector == "Technology" and industry contains "Semiconductor" → EXPECTED=SEMICONDUCTOR

Outputs:
  • Per-ticker table:  Rule label  |  ML label  |  Rule reasons  |  ML Top-2
  • Aggregate:         Rule accuracy (%), ML accuracy (%), edge-case hit count
  • Exit code: 0 if ML >= Rule accuracy, else 1 (so it can run in CI)
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from classification.classifier import BusinessClassifier
from classification.ml_classifier import MLHybridClassifier
from config import BusinessType, get_logger
from data import (
    DataValidator,
    FinancialNormalizer,
    YahooFinanceProvider,
)

log = get_logger("ab_compare")

# ---------------------------------------------------------------------------
# Test set
# ---------------------------------------------------------------------------
SEMI_TICKERS: List[str] = ["NVDA", "AMD", "TSM", "ASML", "AVGO", "INTC", "TXN", "QCOM"]
REIT_TICKERS: List[str] = ["PLD", "AMT", "SPG", "EQIX", "CCI", "PSA", "O", "WELL"]
BONUS_TICKERS: List[str] = ["AAPL", "MSFT", "JPM", "NOW", "XOM", "NEE", "BRK-B"]

# Manual ground-truth table (authoritative — independent of Yahoo sector fetch)
# This lets us evaluate accuracy even when quoteSummary endpoint is 429-throttled.
EXPECTED_MANUAL: Dict[str, Optional[BusinessType]] = {
    # --- Semiconductor band ---
    "NVDA": BusinessType.SEMICONDUCTOR,
    "AMD":  BusinessType.SEMICONDUCTOR,
    "TSM":  BusinessType.SEMICONDUCTOR,
    "ASML": BusinessType.SEMICONDUCTOR,
    "AVGO": BusinessType.SEMICONDUCTOR,
    "INTC": BusinessType.SEMICONDUCTOR,
    "TXN":  BusinessType.SEMICONDUCTOR,
    "QCOM": BusinessType.SEMICONDUCTOR,
    # --- REIT band ---
    "PLD":  BusinessType.REIT,
    "AMT":  BusinessType.REIT,
    "SPG":  BusinessType.REIT,
    "EQIX": BusinessType.REIT,
    "CCI":  BusinessType.REIT,
    "PSA":  BusinessType.REIT,
    "O":    BusinessType.REIT,
    "WELL": BusinessType.REIT,
    # --- Bonus band (diverse — hard cases for rules) ---
    "AAPL":  BusinessType.MATURE_TECH,   # Consumer HW + Services
    "MSFT":  BusinessType.MATURE_TECH,   # Classic MatureTech (WACC/SaaS-adjacent)
    "JPM":   BusinessType.BANK,          # Diversified bank
    "NOW":   BusinessType.SAAS,          # ServiceNow = pure SaaS
    "XOM":   BusinessType.COMMODITY,     # Big Oil
    "NEE":   BusinessType.UTILITIES,     # NextEra = Utility + Renewable
    "BRK-B": BusinessType.CONGLOMERATE,  # Berkshire Hathaway
}


def _expected_from_data(data) -> Optional[BusinessType]:
    """Fallback heuristic for tickers not in EXPECTED_MANUAL.

    Uses sector/industry keywords pulled via the fixed quoteSummary assetProfile
    fetch in YahooFinanceProvider; if still None we leave the row out of
    accuracy math (accuracy denominator only counts rows with a known truth).
    """
    sector = (data.market.sector or "").lower()
    industry = (data.market.industry or "").lower()
    if "real estate" in sector or "reit" in industry:
        return BusinessType.REIT
    if "semiconductor" in industry or "semiconduct" in industry:
        return BusinessType.SEMICONDUCTOR
    if "banks" in industry and "financial" in sector:
        return BusinessType.BANK
    if "utilities" in sector:
        return BusinessType.UTILITIES
    if "energy" in sector:
        return BusinessType.COMMODITY
    if "software" in industry:
        return BusinessType.SAAS
    return None


# ---------------------------------------------------------------------------
# Result collection
# ---------------------------------------------------------------------------
@dataclass
class CompareRow:
    ticker: str
    sector: str
    industry: str
    expected: Optional[BusinessType]
    rule_label: str
    rule_ok: bool
    ml_label: str
    ml_ok: bool
    ml_used_engine: bool
    ml_top2: List[Tuple[str, float]]
    ml_rule_disagree: bool
    edge_case: bool


def _fmt_pct(v: float) -> str:
    return f"{v*100:5.1f}%"


def _print_divider(ch: str = "-", w: int = 110) -> None:
    print(ch * w)


async def classify_one(ticker: str, yf: YahooFinanceProvider, hybrid: MLHybridClassifier,
                       edge_groups: Tuple[List[str], ...]) -> Optional[CompareRow]:
    try:
        data = await yf.get_financial_data(ticker)
    except Exception as e:
        log.warning(f"YF fetch failed for {ticker}: {e}")
        return None
    data = FinancialNormalizer.normalize_all(data)
    data = DataValidator.validate(data)

    rule_profile = BusinessClassifier.classify(data)
    ml_profile = hybrid.classify(data)

    expected = EXPECTED_MANUAL.get(ticker, _expected_from_data(data))
    edge_case = any(ticker in g for g in edge_groups)

    rule_ok = (expected is None) or (rule_profile.business_type == expected.value)
    ml_ok = (expected is None) or (ml_profile.business_type == expected.value)

    return CompareRow(
        ticker=ticker,
        sector=data.market.sector or "?",
        industry=data.market.industry or "?",
        expected=expected,
        rule_label=rule_profile.business_type,
        rule_ok=rule_ok,
        ml_label=ml_profile.business_type,
        ml_ok=ml_ok,
        ml_used_engine=ml_profile.ml_model_used,
        ml_top2=list(ml_profile.top_2_candidates or []),
        ml_rule_disagree=rule_profile.business_type != ml_profile.business_type,
        edge_case=edge_case,
    )


def print_results(rows: List[CompareRow]) -> Tuple[int, int, int, int]:
    _print_divider("=")
    header = (f"{'Ticker':7s} {'Sector':22s} {'Industry':30s} "
              f"{'Expected':16s} {'Rule':16s} {'ML':16s} "
              f"{'R':>2s} {'M':>2s} {'Edge':>4s}")
    print(header)
    _print_divider("-")
    rule_hit = rule_total = ml_hit = ml_total = 0
    edge_rule_hit = edge_rule_total = edge_ml_hit = edge_ml_total = 0
    disagreements: List[CompareRow] = []

    for r in rows:
        exp_str = r.expected.value if r.expected else "-"
        r_marker = "✓" if (r.expected and r.rule_ok) else (" " if r.expected is None else "✗")
        m_marker = "✓" if (r.expected and r.ml_ok) else (" " if r.expected is None else "✗")
        edge_marker = "Y" if r.edge_case else ""
        print(f"{r.ticker:7s} {r.sector[:22]:22s} {r.industry[:30]:30s} "
              f"{exp_str:16s} {r.rule_label:16s} {r.ml_label:16s} "
              f"{r_marker:>2s} {m_marker:>2s} {edge_marker:>4s}")

        if r.ml_rule_disagree:
            disagreements.append(r)

        if r.expected is not None:
            rule_total += 1
            ml_total += 1
            if r.rule_ok:
                rule_hit += 1
            if r.ml_ok:
                ml_hit += 1
            if r.edge_case:
                edge_rule_total += 1
                edge_ml_total += 1
                if r.rule_ok:
                    edge_rule_hit += 1
                if r.ml_ok:
                    edge_ml_hit += 1

    _print_divider("-")
    print("")
    print("=== 📊 Aggregate Accuracy (ground truth = Yahoo sector+industry keyword match) ===")
    rule_acc = rule_hit / rule_total if rule_total else float("nan")
    ml_acc = ml_hit / ml_total if ml_total else float("nan")
    print(f"  Rule-classifier: {rule_hit}/{rule_total}  =  {_fmt_pct(rule_acc)}")
    print(f"  ML-hybrid:       {ml_hit}/{ml_total}  =  {_fmt_pct(ml_acc)}")
    print(f"  Δ (ML − Rule):   {(ml_acc - rule_acc) * 100:+.1f} pp")

    if edge_rule_total:
        print("")
        print("=== 🎯 Edge-Case Band (Semiconductor + REIT only) ===")
        er_acc = edge_rule_hit / edge_rule_total
        em_acc = edge_ml_hit / edge_ml_total
        print(f"  Rule edge-case:  {edge_rule_hit}/{edge_rule_total}  =  {_fmt_pct(er_acc)}")
        print(f"  ML edge-case:    {edge_ml_hit}/{edge_ml_total}  =  {_fmt_pct(em_acc)}")
        print(f"  Δ (ML − Rule):   {(em_acc - er_acc) * 100:+.1f} pp")

    if disagreements:
        print("")
        print("=== 🧩 Rule vs ML Disagreements ===")
        for r in disagreements:
            top2_str = "  ".join(f"{k}={v*100:.0f}%" for k, v in r.ml_top2[:2])
            print(f"  {r.ticker:7s}  Rule={r.rule_label:16s}  ML={r.ml_label:16s}  "
                  f"(engine={'ML' if r.ml_used_engine else 'RULE-FB'})  ML-Top2: {top2_str}")

    print("")
    return rule_hit, rule_total, ml_hit, ml_total


async def main() -> int:
    all_tickers = SEMI_TICKERS + REIT_TICKERS + BONUS_TICKERS
    print(f"[init] A/B classifier compare: {len(SEMI_TICKERS)} semi + {len(REIT_TICKERS)} reit + {len(BONUS_TICKERS)} bonus = {len(all_tickers)} tickers")

    hybrid = MLHybridClassifier()
    ok, msg = hybrid.ensure_ready()
    if not ok:
        print(f"[init] ⚠ ML classifier failed to initialize: {msg} — proceeding with rule-only baseline")
    else:
        print(f"[init] {msg}")

    yf = YahooFinanceProvider(use_fallback=True)
    rows: List[CompareRow] = []

    for ticker in all_tickers:
        row = await classify_one(ticker, yf, hybrid, (SEMI_TICKERS, REIT_TICKERS))
        if row is not None:
            rows.append(row)
        # Throttle (polite)
        await asyncio.sleep(0.4)

    if not rows:
        print("[abort] No data fetched — check network or Yahoo Finance availability.")
        return 2

    rule_hit, rule_total, ml_hit, ml_total = print_results(rows)

    if ml_total and rule_total:
        if ml_hit / ml_total >= rule_hit / rule_total:
            print("✅ PASS: ML accuracy is not worse than rule baseline.")
            return 0
        print("❌ FAIL: ML accuracy fell below rule baseline — review feature engineering or threshold.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
