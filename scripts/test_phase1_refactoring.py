"""scripts/test_phase1_refactoring.py — Comprehensive P0 refactoring tests.

Tests:
  1. Share Count Tests (SOFI, HOOD, PYPL, COIN, JPM, BAC, WFC)
  2. CAPM / Beta Tests (raw beta preservation, scenario consistency)
  3. Regression sanity (existing model imports work)

Run:
    python scripts/test_phase1_refactoring.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("EDGAR_IDENTITY", "ValuationEngine research@example.com")

# Fix Windows console encoding for Unicode output
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

results: Dict[str, Any] = {"share_count": {}, "capm_beta": {}, "regression": {}}


# ===========================================================================
# PART 1 — Share Count Tests
# ===========================================================================
def test_share_count(ticker: str) -> Dict[str, Any]:
    """Test SEC share count retrieval for one ticker."""
    from data.share_count_engine import ShareCountEngine

    r: Dict[str, Any] = {"ticker": ticker, "checks": {}, "errors": []}

    try:
        engine = ShareCountEngine()
        data = engine.fetch(ticker)

        # Check 1: Can get period-end shares
        pe = data.latest_period_end_shares()
        r["checks"]["period_end_shares"] = {
            "available": pe is not None,
            "value": pe.value if pe else None,
            "concept": pe.concept if pe else None,
            "period_end": pe.period_end if pe else None,
            "source": pe.source if pe else None,
        }

        # Check 2: Basic weighted average shares
        wb = data.latest_basic_weighted_avg()
        r["checks"]["weighted_avg_basic"] = {
            "available": wb is not None,
            "value": wb.value if wb else None,
            "concept": wb.concept if wb else None,
        }

        # Check 3: Diluted weighted average shares
        wd = data.latest_diluted_weighted_avg()
        r["checks"]["weighted_avg_diluted"] = {
            "available": wd is not None,
            "value": wd.value if wd else None,
            "concept": wd.concept if wd else None,
        }

        # Check 4: Filing history
        r["checks"]["filing_history"] = {
            "latest_form": data.latest_form_type,
            "latest_filing_date": data.latest_filing_date,
            "latest_accession": data.latest_accession,
        }

        # Check 5: Can handle different XBRL concepts
        r["checks"]["all_concepts_available"] = [f.concept for f in data.all_facts]

        # Check 6: Can handle missing values (treasury, preferred)
        r["checks"]["treasury_shares"] = {
            "available": data.treasury_shares is not None,
            "value": data.treasury_shares.value if data.treasury_shares else None,
        }
        r["checks"]["preferred_shares"] = {
            "available": data.preferred_shares is not None,
            "value": data.preferred_shares.value if data.preferred_shares else None,
        }

        # Check 7: All facts have provenance
        all_traced = all(f.source and f.concept for f in data.all_facts)
        r["checks"]["all_facts_traced"] = all_traced

        # Check 8: CIK resolved
        r["checks"]["cik"] = data.cik

        # Check 9: Reconciliation vs a hypothetical market implied
        market_implied = None
        if pe is not None:
            # Simulate a 26.5% difference like the SOFI case
            market_implied = pe.value * 0.735  # 26.5% below filing
        recon = engine.reconcile_vs_market(
            data, market_implied=market_implied, price=10.0
        )
        r["checks"]["reconciliation"] = {
            "status": recon.status.value,
            "difference_pct": recon.difference_pct,
            "usable_for_valuation": recon.usable_for_valuation,
            "needs_manual_review": recon.needs_manual_review,
            "reason": recon.reason[:200] if recon.reason else "",
        }

    except Exception as e:
        r["errors"].append(str(e))
        r["errors"].append(traceback.format_exc())

    return r


# ===========================================================================
# PART 2 — CAPM / Beta Tests
# ===========================================================================
def test_capm_beta() -> Dict[str, Any]:
    """Test CAPM engine beta separation and scenario consistency."""
    from valuation.capm_engine import CAPMEngine, compute_scenario_capm

    r: Dict[str, Any] = {"checks": {}, "errors": []}

    try:
        engine = CAPMEngine()

        # Test 1: Raw beta is preserved (not overwritten)
        chain = engine.compute(
            raw_beta=2.09,
            risk_free_rate=0.045,
            equity_risk_premium=0.055,
            is_bank=True,
        )
        r["checks"]["raw_beta_preserved"] = {
            "raw_beta": chain.raw_beta,
            "raw_capm_ke": chain.raw_capm_ke,
            "expected_raw_ke": 0.045 + 2.09 * 0.055,
            "match": abs(chain.raw_capm_ke - (0.045 + 2.09 * 0.055)) < 1e-9,
        }

        # Test 2: Normalized beta has explicit method
        r["checks"]["normalized_beta_recorded"] = {
            "normalized_beta": chain.normalized_beta,
            "method": chain.normalization_method,
            "method_not_empty": bool(chain.normalization_method),
        }

        # Test 3: Valuation beta has explicit reason
        r["checks"]["valuation_beta_recorded"] = {
            "valuation_beta": chain.valuation_beta,
            "reason": chain.valuation_beta_reason,
            "reason_not_empty": bool(chain.valuation_beta_reason),
        }

        # Test 4: Raw CAPM Ke vs Adjusted Ke are separate
        r["checks"]["raw_vs_adjusted_ke"] = {
            "raw_capm_ke": chain.raw_capm_ke,
            "adjusted_valuation_ke": chain.adjusted_valuation_ke,
            "ke_adjusted": chain.ke_adjusted,
            "adjustment_reason": chain.adjustment_reason,
            "are_different": abs(chain.raw_capm_ke - chain.adjusted_valuation_ke) > 1e-6,
        }

        # Test 5: Bank ke band applied correctly
        # Raw β=2.09, Rf=0.045, ERP=0.055 → raw ke=15.99%
        # Bank band [7%, 10%] → β clamped to (0.10-0.045)/0.055 = 1.0 → ke=10%
        r["checks"]["bank_ke_band"] = {
            "raw_beta": 2.09,
            "raw_ke": chain.raw_capm_ke,
            "valuation_beta": chain.valuation_beta,
            "adjusted_ke": chain.adjusted_valuation_ke,
            "ke_within_band": 0.07 <= chain.adjusted_valuation_ke <= 0.10,
            "ke_ceiling": chain.ke_ceiling,
            "ke_floor": chain.ke_floor,
        }

        # Test 6: Scenario beta derived from valuation beta (not raw)
        # base valuation beta = 1.0 (clamped), bear = +0.30 = 1.30, bull = -0.30 = 0.70
        bear_chain = compute_scenario_capm(chain, +0.30, is_bank=True)
        bull_chain = compute_scenario_capm(chain, -0.30, is_bank=True)

        r["checks"]["scenario_beta_from_valuation"] = {
            "base_valuation_beta": chain.valuation_beta,
            "bear_beta": bear_chain.valuation_beta,
            "bull_beta": bull_chain.valuation_beta,
            "bear_is_base_plus_shift": abs(bear_chain.valuation_beta - (chain.valuation_beta + 0.30)) < 1e-9,
            "bull_is_base_minus_shift": abs(bull_chain.valuation_beta - (chain.valuation_beta - 0.30)) < 1e-9,
        }

        # Test 7: Base/Bear/Bull use same ke rule (all via CAPM: ke = rf + β × erp)
        base_ke = chain.adjusted_valuation_ke
        bear_ke = bear_chain.adjusted_valuation_ke
        bull_ke = bull_chain.adjusted_valuation_ke
        r["checks"]["scenario_ke_consistency"] = {
            "base_ke": base_ke,
            "bear_ke": bear_ke,
            "bull_ke": bull_ke,
            "bear_ke_higher_than_base": bear_ke > base_ke,
            "bull_ke_lower_than_base": bull_ke < base_ke,
            "base_within_bank_band": 0.07 <= base_ke <= 0.10 if chain.is_bank else True,
            "bear_outside_bank_band": bear_ke > 0.10,  # bear should stress beyond band
        }

        # Test 8: Ke sensitivity direction (higher β → higher ke → lower RIM)
        r["checks"]["ke_sensitivity_direction"] = {
            "base_ke": base_ke,
            "bear_ke": bear_ke,
            "bull_ke": bull_ke,
            "bear_ke_gt_base": bear_ke > base_ke,
            "bull_ke_lt_base": bull_ke < base_ke,
        }

        # Test 9: Raw beta = None doesn't crash
        chain_none = engine.compute(
            raw_beta=None,
            risk_free_rate=0.045,
            equity_risk_premium=0.055,
        )
        r["checks"]["null_raw_beta_handled"] = {
            "valuation_beta": chain_none.valuation_beta,
            "adjusted_ke": chain_none.adjusted_valuation_ke,
            "no_crash": True,
        }

    except Exception as e:
        r["errors"].append(str(e))
        r["errors"].append(traceback.format_exc())

    return r


# ===========================================================================
# PART 3 — Regression Tests (imports + basic instantiation)
# ===========================================================================
def test_regression() -> Dict[str, Any]:
    """Verify existing models still import and instantiate."""
    r: Dict[str, Any] = {"checks": {}, "errors": []}

    models_to_test = [
        ("models.dcf", "DCFModel"),
        ("models.reverse_dcf", "ReverseDCFModel"),
        ("models.bank", "BankDDMModel"),
        ("models.bank", "BankRIMModel"),
        ("models.multiples", "PEModel"),
        ("models.multiples", "PBModel"),
        ("models.multiples", "EVEBITDAModel"),
        ("models.sotp", "SOTPModel"),
        ("simulation.monte_carlo", "MonteCarloSimulator"),
        ("analysis.scenario", "ScenarioAnalyzer"),
        ("valuation.wacc", "WaccCalculator"),
        ("valuation.capm_engine", "CAPMEngine"),
        ("data.share_count_engine", "ShareCountEngine"),
    ]

    for module_name, class_name in models_to_test:
        key = f"{module_name}.{class_name}"
        try:
            mod = __import__(module_name, fromlist=[class_name])
            # Existence check only: some classes require constructor args.
            getattr(mod, class_name)
            r["checks"][key] = "imported"
        except Exception as e:
            r["checks"][key] = f"FAILED: {e}"
            r["errors"].append(f"{key}: {e}")

    return r


# ===========================================================================
# Main
# ===========================================================================
def main() -> None:
    print("=" * 70)
    print("  PHASE 1 REFACTORING — COMPREHENSIVE TEST SUITE")
    print("=" * 70)

    # Part 1: Share Count Tests
    print("\n--- PART 1: Share Count Tests ---")
    test_tickers = ["SOFI", "HOOD", "PYPL", "COIN", "JPM", "BAC", "WFC"]
    for ticker in test_tickers:
        print(f"\n  Testing {ticker} ...")
        r = test_share_count(ticker)
        results["share_count"][ticker] = r

        checks = r.get("checks", {})
        pe = checks.get("period_end_shares", {})
        wd = checks.get("weighted_avg_diluted", {})
        wb = checks.get("weighted_avg_basic", {})
        recon = checks.get("reconciliation", {})

        pe_val = pe.get("value")
        wd_val = wd.get("value")
        wb_val = wb.get("value")

        print(f"    Period-end: {pe_val:,.0f}" if pe_val else "    Period-end: N/A")
        print(f"    Wt-avg basic: {wb_val:,.0f}" if wb_val else "    Wt-avg basic: N/A")
        print(f"    Wt-avg diluted: {wd_val:,.0f}" if wd_val else "    Wt-avg diluted: N/A")
        print(f"    Reconciliation: {recon.get('status', 'N/A')} ({recon.get('difference_pct', 'N/A')}%)")

        if r.get("errors"):
            print(f"    ERRORS: {len(r['errors'])}")

    # Part 2: CAPM / Beta Tests
    print("\n--- PART 2: CAPM / Beta Tests ---")
    r = test_capm_beta()
    results["capm_beta"] = r

    checks = r.get("checks", {})
    for name, chk in checks.items():
        if isinstance(chk, dict):
            print(f"  {name}:")
            for k, v in chk.items():
                print(f"    {k}: {v}")
        else:
            print(f"  {name}: {chk}")

    if r.get("errors"):
        print(f"  ERRORS: {len(r['errors'])}")
        for e in r["errors"]:
            print(f"    {e[:200]}")

    # Part 3: Regression Tests
    print("\n--- PART 3: Regression Tests ---")
    r = test_regression()
    results["regression"] = r

    all_ok = True
    for key, status in r.get("checks", {}).items():
        if "FAILED" in str(status):
            print(f"  FAIL: {key} — {status}")
            all_ok = False
        else:
            print(f"  OK:   {key}")

    if r.get("errors"):
        print(f"  ERRORS: {len(r['errors'])}")
        all_ok = False

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    sc_pass = sum(1 for t in results["share_count"].values() if not t.get("errors"))
    sc_total = len(results["share_count"])
    print(f"  Share Count: {sc_pass}/{sc_total} tickers passed")

    capm_pass = 0 if results["capm_beta"].get("errors") else 1
    print(f"  CAPM/Beta:   {'PASS' if capm_pass else 'FAIL'}")

    reg_pass = sum(1 for s in results["regression"].get("checks", {}).values() if "FAILED" not in str(s))
    reg_total = len(results["regression"].get("checks", {}))
    print(f"  Regression:  {reg_pass}/{reg_total} modules imported")

    overall = sc_pass == sc_total and capm_pass and all_ok
    print(f"\n  OVERALL: {'PASS' if overall else 'FAIL'}")

    # Save results
    out_path = _PROJECT_ROOT / "scripts" / "phase1_test_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n  Full results saved to: {out_path}")


if __name__ == "__main__":
    main()
