"""Quick script to force-retrain classifier on labeling_dump.csv and report key metrics + sanity predictions."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio
from classification.ml_classifier import (
    LightGBMBusinessClassifier,
    extract_numerical_features,
    build_text_corpus,
)
from data.providers import YahooFinanceProvider

def main() -> int:
    clf = LightGBMBusinessClassifier()
    ok, msg = clf.load_or_train()
    print(f"[1] Load/Train: OK={ok} msg={msg}")
    if not ok:
        return 1

    meta = clf._meta
    print(f"\n[2] TrainMeta")
    print(f"  version         : {meta.version}")
    print(f"  train_accuracy  : {meta.train_accuracy:.4f}")
    print(f"  n_samples_train : {meta.n_samples_train}")
    print(f"  class_labels    : {meta.class_labels}")
    print(f"  num_features    : {meta.num_feature_names}")
    print(f"  fallback_thresh : {meta.fallback_threshold}")
    print(f"  note            : {meta.note!r}")
    print(f"  artifact_paths  :")
    from classification.ml_classifier import ML_MODEL_PATH, ML_VECTORIZER_PATH, ML_META_PATH
    for p in (ML_MODEL_PATH, ML_VECTORIZER_PATH, ML_META_PATH):
        sz = p.stat().st_size if p.exists() else -1
        print(f"    {p.name} : {sz} bytes")

    # Sanity predictions
    samples = ["AAPL", "MSFT", "NVDA", "JPM", "BAC", "PLD", "AMT",
               "XOM", "CVX", "NEE", "DUK", "KO", "PEP", "JNJ", "CRM"]

    async def _pred():
        yp = YahooFinanceProvider(use_fallback=True, cache_enabled=True)
        print(f"\n[3] Sanity predictions (n={len(samples)})")
        for t in samples:
            try:
                d = await yp.get_financial_data(t)
                num = extract_numerical_features(d)
                txt = build_text_corpus(d)
                res = clf.predict(d)
                if not res:
                    print(f"  {t:<6s} predict() returned None")
                    continue
                label = res.get("label", "?")
                conf = float(res.get("confidence", 0.0))
                probs = res.get("probabilities", {}) or {}
                top2 = sorted(probs.items(), key=lambda kv: -kv[1])[:2]
                reasons = res.get("reasons", []) or []
                print(f"  {t:<6s} => {label:<20s} conf={conf*100:5.1f}%"
                      f"  top2={[(k,round(v*100,1)) for k,v in top2]}")
            except Exception as e:
                print(f"  {t:<6s} FAIL: {e!r}")

    asyncio.run(_pred())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
