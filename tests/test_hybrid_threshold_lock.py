"""M-16 lock: the Case-B FinTech hybrid floor must not be lowered to force SOFI.

SOFI's Technology exposure is 5.5%, below the 8% floor, so the classifier does
not attach the "Hybrid Financial Institution (FinTech)" label. The root cause is
DATA-DRIVEN (a missing provider sector/industry down-weights the text features),
so the fix belongs in feature imputation — not in nudging the threshold down,
which would silently perturb the golden baseline for every financial.

This test pins both the constant value and the detector behaviour so a future
agent cannot "fix" SOFI by relaxing the floor without an explicit decision.
"""
from __future__ import annotations

from config import BusinessType
from classification.ml_classifier import HYBRID_FIN_TO_TECH_FLOOR, MLHybridClassifier

TECH_KEY = BusinessType.MATURE_TECH.value


def test_hybrid_fin_to_tech_floor_value_locked():
    assert HYBRID_FIN_TO_TECH_FLOOR == 0.08, (
        "The Case-B hybrid floor changed. If this is intentional, update "
        "AGENT.md Known Issues #13-4, TODO.md M-16 and the golden baseline — "
        "do NOT lower it merely to make SOFI flip to hybrid (data-driven root cause)."
    )


def test_detector_flips_only_at_or_above_floor():
    detect = MLHybridClassifier._detect_hybrid

    def is_hybrid(tech_p: float) -> bool:
        prob_map = {BusinessType.BANK.value: 0.711, TECH_KEY: tech_p}
        return detect(BusinessType.BANK, prob_map)[0]

    # Just below the floor (SOFI's actual 5.5% exposure) → not a hybrid.
    assert is_hybrid(HYBRID_FIN_TO_TECH_FLOOR - 1e-6) is False
    # Exactly at the floor → hybrid (closed interval: the rule uses >=).
    assert is_hybrid(HYBRID_FIN_TO_TECH_FLOOR) is True
