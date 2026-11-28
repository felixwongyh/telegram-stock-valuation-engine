"""Independent routing golden.

The report golden (`tests/golden/report_fingerprints.json`) pins whole-report
output. It would catch a routing regression only indirectly, and only for the
18 tickers in that basket -- which is why a Visa routed back into Bank RIM has
to fail a test that talks about *routing*, not about median values.

This file is that test. It pins, per ticker, the business model and the exact
model set, and it asserts the routing invariant directly:

    a business model that is not BANK must never receive Bank DDM / Bank RIM

Regenerate deliberately after a reviewed change:

    UPDATE_ROUTING_GOLDEN=1 pytest tests/test_routing_golden.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from classification.classifier import BusinessClassifier
from config import BusinessType, FinancialBusinessModel
from data.models import FinancialData, FinancialStatement, MarketData

GOLDEN_PATH = Path(__file__).parent / "golden" / "routing_fingerprints.json"

BANK_MODELS = ("Bank DDM", "Bank RIM")


def _company(ticker, *, industry, sector="Financial Services",
             revenue=1.0e10, operating_income=3.0e9, interest_expense=1.0e8,
             total_assets=None, total_debt=0.0, equity=0.0):
    stmt = FinancialStatement(
        period_end="2026-09-30", period_type="ttm", revenue=revenue,
        operating_income=operating_income, interest_expense=interest_expense,
        net_income=2.0e9,
    )
    sheets = []
    if total_assets is not None:
        sheets = [{
            "Total Assets": total_assets,
            "Total Debt": total_debt or 0.0,
            "Stockholders Equity": equity or 0.0,
        }]
    return FinancialData(
        ticker=ticker, ttm=stmt, annual_income=[stmt],
        annual_balance_sheet=sheets,
        market=MarketData(sector=sector, industry=industry),
    )


#: (ticker, fixture, BusinessType the caller would assign from the label)
CASES = [
    ("JPM", _company("JPM", industry="Banks—Diversified", revenue=1.6e11,
                     operating_income=6.0e10, interest_expense=8.0e10,
                     total_assets=4.0e12, total_debt=5.0e11, equity=3.6e11),
     BusinessType.BANK),
    ("BAC", _company("BAC", industry="Banks—Diversified", revenue=1.0e11,
                     operating_income=3.5e10, interest_expense=6.8e10,
                     total_assets=3.4e12, total_debt=3.7e11, equity=3.0e11),
     BusinessType.BANK),
    ("GS", _company("GS", industry="Capital Markets", revenue=5.0e10,
                    operating_income=2.0e10, interest_expense=1.5e10,
                    total_assets=1.8e12, total_debt=3.9e11, equity=1.25e11),
     BusinessType.BANK),
    ("SCHW", _company("SCHW", industry="Capital Markets", revenue=1.9e10,
                      operating_income=6.5e9, interest_expense=4.5e9,
                      total_assets=4.5e11, total_debt=6.0e10, equity=4.0e10),
     BusinessType.BANK),
    ("IBKR", _company("IBKR", industry="Capital Markets", revenue=4.0e9,
                      operating_income=2.0e9, interest_expense=8.0e8,
                      total_assets=1.2e11, total_debt=2.0e10, equity=3.0e9),
     BusinessType.BANK),
    ("V", _company("V", industry="Credit Services", revenue=3.5e10,
                   operating_income=2.2e10, interest_expense=5.5e8,
                   total_assets=9.4e10, total_debt=2.2e10, equity=3.6e10),
     BusinessType.FINTECH),
    ("MA", _company("MA", industry="Credit Services", revenue=2.8e10,
                    operating_income=1.5e10, interest_expense=6.0e8,
                    total_assets=4.0e10, total_debt=1.5e10, equity=5.0e9),
     BusinessType.FINTECH),
    ("BLK", _company("BLK", industry="Asset Management", revenue=2.0e10,
                     operating_income=6.0e9, interest_expense=3.0e8,
                     total_assets=1.2e11, total_debt=1.0e10, equity=4.0e10),
     BusinessType.BANK),
    ("CME", _company("CME", industry="Financial Data & Stock Exchanges",
                     revenue=6.0e9, operating_income=3.5e9,
                     interest_expense=1.5e8, total_assets=1.0e11,
                     total_debt=3.0e9, equity=2.8e10),
     BusinessType.BANK),
    ("LENDER", _company("LENDER", industry="Credit Services", revenue=1.0e10,
                        operating_income=2.0e9, interest_expense=1.2e9),
     BusinessType.FINTECH),
    ("INSURER", _company("INSURER", industry="Insurance—Property & Casualty",
                         revenue=5.0e10, operating_income=8.0e9,
                         interest_expense=6.0e8, total_assets=2.7e11,
                         total_debt=1.7e10, equity=7.4e10),
     BusinessType.INSURANCE),
    ("NVDA", _company("NVDA", industry="Semiconductors", sector="Technology",
                      revenue=1.0e11, operating_income=6.0e10,
                      interest_expense=2.0e8, total_assets=2.0e11,
                      total_debt=1.1e10, equity=1.5e11),
     BusinessType.SEMICONDUCTOR),
]


def _fingerprint(data: FinancialData, bt: BusinessType) -> dict:
    verdict = BusinessClassifier.classify_financial_business_model(data, bt)
    applicable, _na, _r = BusinessClassifier._model_applicability(data, bt)
    return {
        "financial_business_model": verdict.model.value,
        "confidence": verdict.confidence,
        "applicable_models": sorted(applicable),
    }


def _collect() -> dict:
    return {t: _fingerprint(d, bt) for t, d, bt in CASES}


class TestRoutingGolden:
    def test_routing_matches_golden(self):
        live = _collect()
        if os.environ.get("UPDATE_ROUTING_GOLDEN") == "1" or not GOLDEN_PATH.exists():
            GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_PATH.write_text(json.dumps(live, indent=2, sort_keys=True) + "\n")
            pytest.skip("routing golden written; re-run to verify")

        golden = json.loads(GOLDEN_PATH.read_text())
        diffs = []
        for ticker, live_fp in live.items():
            g = golden.get(ticker)
            if g is None:
                diffs.append(f"{ticker}: missing from golden")
                continue
            for key in ("financial_business_model", "confidence", "applicable_models"):
                if g.get(key) != live_fp.get(key):
                    diffs.append(
                        f"{ticker}.{key}: golden={g.get(key)!r} -> live={live_fp.get(key)!r}"
                    )
        assert not diffs, "Routing drifted:\n  " + "\n  ".join(diffs)


class TestRoutingInvariant:
    """The invariant that must hold for every case, golden or not."""

    @pytest.mark.parametrize("ticker,data,bt", CASES, ids=[c[0] for c in CASES])
    def test_only_bank_gets_bank_models(self, ticker, data, bt):
        verdict = BusinessClassifier.classify_financial_business_model(data, bt)
        applicable, _na, _r = BusinessClassifier._model_applicability(data, bt)
        if verdict.model is FinancialBusinessModel.BANK:
            assert "Bank RIM" in applicable, f"{ticker}: bank lost RIM"
            assert "Bank DDM" in applicable, f"{ticker}: bank lost DDM"
        else:
            assert "Bank RIM" not in applicable, (
                f"{ticker} is {verdict.model.value} but received Bank RIM"
            )
            assert "Bank DDM" not in applicable, (
                f"{ticker} is {verdict.model.value} but received Bank DDM"
            )

    @pytest.mark.parametrize("ticker,data,bt", CASES, ids=[c[0] for c in CASES])
    def test_every_verdict_is_traceable(self, ticker, data, bt):
        verdict = BusinessClassifier.classify_financial_business_model(data, bt)
        assert verdict.reason
        assert verdict.confidence in ("high", "medium", "low")
        assert isinstance(verdict.evidence, dict)
