"""
_demo_ml_classifier.py — Item #14 Demo / Regression Script

Runs end-to-end:
  1. Train (or load cached) LightGBM multi-class model on 1500 synthetic labeled samples
  2. For each archetype ticker (NVDA, PLD, JPM, NOW, AAPL, MSFT, ...):
     - Print ML probabilities (top 3) + Top-2 candidates
     - Indicate rule fallback triggered or not
     - Show structural sanity override notes
  3. Exit non-zero if any regression (e.g. NVDA classified as REIT, bank not detected)

Used as a smoke test / visual regression guard for the Telegram report classifier output.
"""
from __future__ import annotations

import sys
from typing import Dict, List

from data import SyntheticDataProvider, FinancialNormalizer, DataValidator
from classification import MLHybridClassifier, ML_FALLBACK_THRESHOLD
from config import BusinessType


TICKER_EXPECTATIONS: Dict[str, Dict] = {
    "AAPL":  {"must_avoid": [BusinessType.REIT, BusinessType.BANK],
              "preferred": [BusinessType.MATURE_TECH, BusinessType.CONSUMER_CYCLICAL]},
    "MSFT":  {"must_avoid": [BusinessType.REIT, BusinessType.BANK, BusinessType.COMMODITY],
              "preferred": [BusinessType.MATURE_TECH, BusinessType.SAAS]},
    "NVDA":  {"must_avoid": [BusinessType.REIT],
              "preferred": [BusinessType.SEMICONDUCTOR, BusinessType.MATURE_TECH],
              "not_reit": True},
    "JPM":   {"must_avoid": [BusinessType.REIT, BusinessType.SEMICONDUCTOR],
              "preferred": [BusinessType.BANK, BusinessType.INSURANCE],
              "financial_institution": True},
    "PLD":   {"must_avoid": [BusinessType.SEMICONDUCTOR, BusinessType.SAAS],
              "preferred": [BusinessType.REIT, BusinessType.UTILITIES],
              "is_reit": True},
    "NOW":   {"must_avoid": [BusinessType.BANK, BusinessType.COMMODITY],
              "preferred": [BusinessType.SAAS, BusinessType.MATURE_TECH]},
    "AMZN":  {"must_avoid": [BusinessType.BANK, BusinessType.REIT],
              "preferred": [BusinessType.CONSUMER_CYCLICAL, BusinessType.MATURE_TECH]},
    "GOOGL": {"must_avoid": [BusinessType.BANK],
              "preferred": [BusinessType.MATURE_TECH, BusinessType.SAAS]},
    "META":  {"must_avoid": [BusinessType.BANK],
              "preferred": [BusinessType.MATURE_TECH, BusinessType.SAAS]},
    "TSLA":  {"must_avoid": [BusinessType.BANK, BusinessType.REIT],
              "preferred": [BusinessType.CONSUMER_CYCLICAL, BusinessType.MATURE_TECH]},
}


def _fmt_pct(x: float) -> str:
    return f"{x*100:5.1f}%"


def run_demo() -> int:
    errors: List[str] = []
    sp = SyntheticDataProvider()
    cls = MLHybridClassifier()
    ok, msg = cls.ensure_ready()
    print(f"[init] {msg}")
    print(f"[init] ML fallback threshold: top prob >= {ML_FALLBACK_THRESHOLD:.0%} else rules\n")

    for ticker, expect in TICKER_EXPECTATIONS.items():
        d = sp.get_financial_data(ticker)
        d = FinancialNormalizer.normalize_all(d)
        d = DataValidator.validate(d)
        p = cls.classify(d)

        probs = p.ml_probabilities or {}
        sorted_probs = sorted(probs.items(), key=lambda kv: -kv[1])

        top3 = sorted_probs[:3]
        top3_str = "  ".join(f"{k:18s} {_fmt_pct(v)}" for k, v in top3)
        fb = "🔁 RULE FALLBACK  " if p.rule_fallback_triggered else "✅ ML DIRECT       "
        model_used = "ML" if p.ml_model_used else "RULE"

        print(f"=== {ticker:6s} [{fb}] best={p.business_type:20s} conf={p.classification_confidence:.2f} ===")
        print(f"       model_used={model_used}   top2={p.top_2_candidates}")
        print(f"       Top3 probs: {top3_str}")
        for r in p.classification_reasons[:5]:
            print(f"        · {r}")

        bt = p.business_type
        avoid_values = {b.value for b in expect.get("must_avoid", [])}
        if bt in avoid_values:
            errors.append(f"{ticker}: best={bt} in must_avoid set {avoid_values}")

        if expect.get("not_reit") and p.is_reit:
            errors.append(f"{ticker}: is_reit=True but should be False")
        if expect.get("is_reit") and not p.is_reit and bt != BusinessType.REIT.value:
            errors.append(f"{ticker}: should be REIT, got best={bt} is_reit={p.is_reit}")
        if expect.get("financial_institution") and not p.is_financial_institution:
            errors.append(f"{ticker}: is_financial_institution=False but should be True")

        if p.top_2_candidates and len(p.top_2_candidates) != 2:
            errors.append(f"{ticker}: top_2_candidates != 2 entries: {p.top_2_candidates}")

        print()

    print("=" * 78)
    if errors:
        print("REGRESSION FAILURES:")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    print("All tickers passed ML classifier regression guard.")
    return 0


if __name__ == "__main__":
    sys.exit(run_demo())
