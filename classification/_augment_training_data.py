"""
classification/_augment_training_data.py - Augment training CSV to ensure
every BusinessType has at least MIN_PER_CLASS samples.

Reads the existing labeling_dump.csv, counts samples per label, and generates
additional synthetic rows (using the same Archetype profiles from ml_classifier)
for any class below the threshold.  Generated rows are marked in the `note`
column with "augmented" so they can be distinguished from real data.

The generated rows use the same feature distribution as the archetypes in
ml_classifier.py, ensuring the ML model sees enough examples of each class.

Usage:
    python -m classification._augment_training_data
    # or
    python classification/_augment_training_data.py
"""
from __future__ import annotations

import csv
import math
import random
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import BusinessType, get_logger
from classification.ml_classifier import (
    _ARCHETYPES,
    _NUM_FEATURE_NAMES,
    _sample,
    _generate_text_from_keywords,
)

log = get_logger("classification.augment")

MIN_PER_CLASS: int = 200  # Target: at least 200 samples per BusinessType
RANDOM_SEED: int = 99  # Different seed from training to avoid correlation
CSV_PATH: Path = Path(__file__).parent / "labeling_dump.csv"


def _generate_augmented_row(
    bt: BusinessType,
    rng: random.Random,
) -> Dict[str, str]:
    """Generate one synthetic CSV row from the archetype for this BusinessType."""
    arch = _ARCHETYPES[bt]

    feat = {
        "ticker": f"AUG_{bt.value}_{rng.randint(10000, 99999)}",
        "company_name": "",
        "sector": "",
        "industry": "",
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
        "label": bt.value,
        "note": "augmented",
    }

    # Generate company_name/sector/industry from keywords
    text = _generate_text_from_keywords(rng, arch)
    feat["company_name"] = text.title()

    # Add some sector/industry hints based on archetype
    _sector_industry_hints = {
        BusinessType.MATURE_TECH: ("Technology", "Software - Infrastructure"),
        BusinessType.SAAS: ("Technology", "Software - Application"),
        BusinessType.SEMICONDUCTOR: ("Technology", "Semiconductors"),
        BusinessType.CONSUMER_CYCLICAL: ("Consumer Cyclical", "Auto Manufacturers"),
        BusinessType.CONSUMER_STAPLES: ("Consumer Defensive", "Packaged Foods"),
        BusinessType.REIT: ("Real Estate", "REIT - Diversified"),
        BusinessType.BANK: ("Financial", "Banks - Diversified"),
        BusinessType.INSURANCE: ("Financial", "Insurance - Diversified"),
        BusinessType.FINTECH: ("Financial", "Credit Services"),
        BusinessType.NEOBANK: ("Financial", "Banks - Regional"),
        BusinessType.COMMODITY: ("Materials", "Other Industrial Metals & Mining"),
        BusinessType.UTILITIES: ("Utilities", "Utilities - Regulated Electric"),
        BusinessType.ENERGY: ("Energy", "Oil & Gas E&P"),
        BusinessType.INDUSTRIAL: ("Industrials", "Aerospace & Defense"),
        BusinessType.HEALTHCARE: ("Healthcare", "Drug Manufacturers - Specialty & Generic"),
        BusinessType.TELECOM: ("Communication Services", "Telecom Services"),
        BusinessType.MEDIA: ("Communication Services", "Movies & Entertainment"),
        BusinessType.CONGLOMERATE: ("Industrials", "Conglomerates"),
        BusinessType.UNKNOWN: ("", ""),
    }
    sec, ind = _sector_industry_hints.get(bt, ("", ""))
    # For ~40% of augmented rows, leave sector/industry empty to simulate
    # the real-world scenario where Yahoo doesn't return sector/industry
    if rng.random() < 0.4:
        feat["sector"] = sec
        feat["industry"] = ind

    # Round floats for CSV
    for k in _NUM_FEATURE_NAMES:
        v = feat[k]
        if isinstance(v, float):
            if abs(v) < 0.0001:
                feat[k] = "0.0"
            else:
                feat[k] = str(round(v, 6))

    return feat


def augment_csv(csv_path: Path = CSV_PATH, min_per_class: int = MIN_PER_CLASS) -> int:
    """Augment the CSV so every BusinessType has at least min_per_class rows.

    Returns the number of augmented rows added.
    """
    if not csv_path.exists():
        log.error(f"CSV not found: {csv_path}")
        return 0

    # Read existing data
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        existing_rows = list(reader)

    # Count per label
    label_counts: Counter = Counter()
    for row in existing_rows:
        label = (row.get("label") or "").strip()
        if label:
            label_counts[label] += 1

    log.info(f"Existing label distribution: {dict(label_counts)}")

    # Determine how many to generate per class
    rng = random.Random(RANDOM_SEED)
    new_rows: List[Dict[str, str]] = []
    total_needed = 0

    for bt in BusinessType:
        if bt == BusinessType.UNKNOWN:
            # Don't augment Unknown — it's already over-represented
            continue
        current = label_counts.get(bt.value, 0)
        needed = max(0, min_per_class - current)
        if needed > 0:
            log.info(f"  {bt.value}: {current} → need {needed} more")
            for _ in range(needed):
                new_rows.append(_generate_augmented_row(bt, rng))
            total_needed += needed
        else:
            log.info(f"  {bt.value}: {current} (sufficient)")

    if not new_rows:
        log.info("All classes already meet minimum threshold. No augmentation needed.")
        return 0

    # Backup original
    backup_path = csv_path.with_suffix(f".bak.augment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    shutil.copy2(csv_path, backup_path)
    log.info(f"Backed up original to {backup_path}")

    # Append augmented rows
    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for row in new_rows:
            # Ensure all fieldnames are present
            out = {k: row.get(k, "") for k in fieldnames}
            writer.writerow(out)

    # Verify
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        final_counts: Counter = Counter()
        for row in csv.DictReader(f):
            label = (row.get("label") or "").strip()
            if label:
                final_counts[label] += 1

    log.info(f"Final label distribution: {dict(final_counts)}")
    log.info(f"Total rows: {sum(final_counts.values())}")
    log.info(f"Augmented rows added: {total_needed}")

    return total_needed


if __name__ == "__main__":
    n = augment_csv()
    print(f"\nDone. {n} augmented rows added to {CSV_PATH}")
