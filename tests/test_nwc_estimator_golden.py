"""Independent golden baseline for the NWC estimators.

Why this exists
---------------
The report fingerprint (`golden/report_fingerprints.json`) contains **no NWC
fields at all**. That means it can prove a change did not move the rendered
valuation, but it can prove nothing about whether the NWC estimators themselves
behave consistently, and it will say nothing when NWC estimates are later wired
into the projection. Relying on it for NWC safety would be a false assurance.

So there are two separate baselines:

  * ``nwc_estimator_fingerprints.json`` — the *estimator* baseline. Locks the
    three dimension-separated estimates, the history grade, and the confidence
    class for every basket ticker. A change here is a change in what we believe
    about working capital, and must be reviewed as such.

  * ``nwc_sensitivity_fingerprints.json`` — the *sensitivity* baseline. Locks
    how the reverse-DCF EV responds to sweeping the NWC coefficient, so that
    wiring NWC into the projection later cannot silently change valuations.

Both are deliberately separate from the report golden: an NWC change should not
need a report-golden regeneration, and a report change should not mask an NWC
regression.

Regenerate only after a reviewed, intended change:

    UPDATE_NWC_GOLDEN=1 pytest tests/test_nwc_estimator_golden.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from forecasts.fcf_projection import project_enterprise_value_shaped
from tests.golden_report import BASKET, run_pipeline

GOLDEN_DIR = Path(__file__).parent / "golden"
ESTIMATOR_PATH = GOLDEN_DIR / "nwc_estimator_fingerprints.json"
SENSITIVITY_PATH = GOLDEN_DIR / "nwc_sensitivity_fingerprints.json"

#: NWC coefficients swept for the sensitivity baseline. Fixed, so the baseline
#: does not drift when the engine's own candidate list changes.
SENSITIVITY_W = [0.0, 0.10, 0.25, 0.50, 0.80, 1.50]

#: Growth rates for the sweep. All must be non-zero: the NWC term is proportional
#: to Delta revenue, so at g = 0 every coefficient yields the same EV and the
#: sweep carries no information. Three fixed points plus each company's own
#: implied revenue CAGR, so a name that only becomes NWC-sensitive at its own
#: growth rate is not missed by a single hard-coded test point.
SENSITIVITY_GROWTHS = (0.02, 0.05, 0.10)

#: Kept for the single-point callers/readers that predate the multi-point sweep.
SENSITIVITY_GROWTH = 0.05

#: EV is reported relative to the w=0 case, which removes the revenue scale and
#: keeps the numbers comparable across tickers.
_EV_TOLERANCE = 1e-6


def _round(x, nd=6):
    if x is None:
        return None
    return round(float(x), nd)


def _estimator_fingerprint(ticker: str) -> dict:
    """Estimator-side facts only — no valuation output."""
    from analysis.nwc_shadow import diagnose

    ctx = run_pipeline(ticker)
    data = ctx["data"]
    diag = diagnose(data)
    est = diag["estimators"]
    conf = diag["confidence"]
    dt = diag.get("direction_test") or {}
    return {
        "ticker": ticker,
        "level": _round((est.get("level") or {}).get("value")),
        "level_n": (est.get("level") or {}).get("n_observations"),
        "intensity": _round((est.get("intensity") or {}).get("value")),
        "robust_marginal": _round((est.get("robust_marginal") or {}).get("value")),
        "robust_n": (est.get("robust_marginal") or {}).get("n_observations"),
        "n_annual_periods": conf.get("n_annual_periods"),
        "history_grade": conf.get("history_grade"),
        "claim_strength": conf.get("claim_strength"),
        "confidence_kind": conf.get("kind"),
        "estimates_conflict": bool(est.get("estimates_conflict")),
        # The local-scope verdict, including where it stops holding.
        "verdict": dt.get("verdict"),
        "verdict_scope": dt.get("verdict_scope"),
        "flips_at_growth": _round(dt.get("flips_at_growth"), 4),
    }


def _sensitivity_fingerprint(ticker: str) -> dict:
    """How EV responds to the NWC coefficient, relative to w = 0.

    The projection parameters come from the engine's own DCF path, so this
    baseline measures what the engine actually runs rather than a look-alike.
    EV is expressed relative to ``w = 0``, which removes the revenue scale.
    """
    from analysis.nwc_shadow import projection_params_from_engine

    ctx = run_pipeline(ticker)
    rd = ctx["model_results"].get("ReverseDCF")
    params = projection_params_from_engine(
        ctx["data"], ctx["profile"], (getattr(rd, "breakdown", None) or {})
    )
    base = {"ticker": ticker, "available": params is not None,
            "ev_relative": {}}
    if not params:
        return base

    # Include the company's own implied revenue CAGR as an extra scan point, so
    # the baseline is evaluated where this name actually grows, not only at the
    # fixed test rates. Rounded into the key so it is stable across runs.
    growths = list(SENSITIVITY_GROWTHS)
    implied = None
    try:
        bd = getattr(rd, "breakdown", None) or {}
        implied = bd.get("implied_revenue_cagr")
    except Exception:
        implied = None
    if implied is not None and implied > 0:
        growths.append(round(float(implied), 4))

    for g in growths:
        key = f"g={g:.4f}"
        ev_by_w = {}
        for w in SENSITIVITY_W:
            ev_by_w[w] = project_enterprise_value_shaped(
                params["revenue0"], g, params["operating_margin"],
                params["tax_rate"], params["da_ratio"], params["capex_ratio"],
                w, params["wacc"], params["terminal_growth"], params["horizon"],
            ).enterprise_value
        base_ev = ev_by_w.get(0.0)
        base["ev_relative"][key] = {
            f"{w:.2f}": (_round(ev / base_ev) if base_ev not in (None, 0) else None)
            for w, ev in ev_by_w.items()
        }

    base["growth_points"] = [round(g, 4) for g in growths]
    base["implied_growth_used"] = (round(float(implied), 4)
                                   if implied is not None and implied > 0 else None)
    return base


def _collect(kind: str) -> dict:
    out = {}
    for t in BASKET:
        out[t] = (
            _estimator_fingerprint(t) if kind == "estimator"
            else _sensitivity_fingerprint(t)
        )
    return out


def _diff(golden: dict, live: dict) -> list:
    diffs = []
    for ticker in sorted(set(golden) | set(live)):
        gold, live_rec = golden.get(ticker), live.get(ticker)
        if gold is None or live_rec is None:
            diffs.append(f"{ticker}: present in only one side")
            continue
        for key in sorted(set(gold) | set(live_rec)):
            gv, lv = gold.get(key), live_rec.get(key)
            if gv != lv:
                diffs.append(f"{ticker}.{key}: golden={gv!r} -> live={lv!r}")
    return diffs


@pytest.fixture(scope="module")
def estimator_live():
    return _collect("estimator")


@pytest.fixture(scope="module")
def sensitivity_live():
    return _collect("sensitivity")


class TestNwcEstimatorGolden:
    def test_estimator_fingerprint_matches(self, estimator_live):
        if os.environ.get("UPDATE_NWC_GOLDEN") == "1":
            ESTIMATOR_PATH.write_text(
                json.dumps(estimator_live, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            pytest.skip("estimator golden regenerated")
        if not ESTIMATOR_PATH.exists():
            pytest.skip("no estimator baseline yet; run UPDATE_NWC_GOLDEN=1")
        golden = json.loads(ESTIMATOR_PATH.read_text(encoding="utf-8"))
        diffs = _diff(golden, estimator_live)
        assert not diffs, "NWC estimator drift:\n  " + "\n  ".join(diffs[:40])


class TestNwcSensitivityGolden:
    def test_sensitivity_fingerprint_matches(self, sensitivity_live):
        if os.environ.get("UPDATE_NWC_GOLDEN") == "1":
            SENSITIVITY_PATH.write_text(
                json.dumps(sensitivity_live, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            pytest.skip("sensitivity golden regenerated")
        if not SENSITIVITY_PATH.exists():
            pytest.skip("no sensitivity baseline yet; run UPDATE_NWC_GOLDEN=1")
        golden = json.loads(SENSITIVITY_PATH.read_text(encoding="utf-8"))
        diffs = _diff(golden, sensitivity_live)
        assert not diffs, "NWC sensitivity drift:\n  " + "\n  ".join(diffs[:40])
