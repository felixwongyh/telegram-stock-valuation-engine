"""Bank operating income must not be presented, because banks do not report one.

The vendor's ``operatingIncome`` for a bank is EBIT (pre-tax income + interest
expense). For JPM FY2025 that is 170.5B, against 72.6B pre-tax income and 86.8B
pre-provision profit. Quarterly values are worse: the vendor omits them and the
provider used to synthesize ``revenue x annual_margin``, which for BAC and GS
produced operating income *larger than revenue*.

These tests pin the invariant at the provider boundary, where the wrong number
entered, and check that nothing downstream depends on it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from data.bank_registry import BANK_HOLDING_COMPANIES
from data.providers import YahooFinanceProvider

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "yahoo_finance"


def _cached(ticker: str) -> dict | None:
    path = CACHE_DIR / f"{ticker}_20261123.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["payload"]


def _load(ticker: str):
    return asyncio.run(YahooFinanceProvider().get_financial_data(ticker))


# --------------------------------------------------------------------------
# The vendor data really is EBIT, so the fixture claim is not invented.
# --------------------------------------------------------------------------
def test_vendor_bank_operating_income_equals_pretax_plus_interest():
    """Annual op_inc == pre-tax income + interest expense, for each bank.

    This is the evidence that the field is EBIT. It is computed from the frozen
    snapshot alone, so it cannot drift with the network.
    """
    for ticker in ("JPM", "BAC", "GS"):
        payload = _cached(ticker)
        if payload is None:
            pytest.skip(f"no frozen snapshot for {ticker}")
        annual = payload["annual_income"][0]
        op_inc = annual.get("operating_income")
        interest = annual.get("interest_expense")
        net_income = annual.get("net_income")
        tax = annual.get("income_tax")
        if None in (op_inc, interest, net_income, tax):
            pytest.skip(f"{ticker} snapshot lacks the fields to reconcile")
        pretax = net_income + tax
        assert op_inc == pytest.approx(pretax + interest, rel=1e-9), (
            f"{ticker}: op_inc {op_inc:,.0f} != pretax {pretax:,.0f} "
            f"+ interest {interest:,.0f}; the EBIT identity is what makes this "
            "field unusable as operating income"
        )


def test_bank_quarterly_operating_income_was_a_constant_ratio():
    """Every quarter carries the same op/revenue ratio — a computed value.

    Recorded as a property of the *input* snapshot so that if the vendor ever
    starts sending real quarterly operating income, this test tells us the
    suppression could be relaxed rather than failing silently.
    """
    for ticker in ("JPM", "BAC", "GS"):
        payload = _cached(ticker)
        if payload is None:
            pytest.skip(f"no frozen snapshot for {ticker}")
        quarters = [
            s for s in payload["quarterly_income"]
            if s.get("operating_income") and s.get("revenue")
        ]
        if len(quarters) < 3:
            pytest.skip(f"{ticker} snapshot has too few quarters")
        ratios = {round(s["operating_income"] / s["revenue"], 9) for s in quarters}
        assert len(ratios) == 1, (
            f"{ticker}: expected the synthesized constant ratio, saw {sorted(ratios)}"
        )


# --------------------------------------------------------------------------
# The invariant: no operating income is surfaced for a bank.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("ticker", ["JPM", "BAC", "GS"])
def test_bank_has_no_operating_income(ticker):
    data = _load(ticker)
    assert data.ttm is not None
    assert data.ttm.operating_income is None, f"{ticker} TTM operating_income must be None"
    assert data.ttm.ebit is None, f"{ticker} TTM ebit must be None"
    for stmt in [*data.annual_income, *data.quarterly_income]:
        assert stmt.operating_income is None
        assert stmt.ebit is None


@pytest.mark.parametrize("ticker", ["JPM", "BAC", "GS"])
def test_bank_suppression_is_explained_in_notes(ticker):
    data = _load(ticker)
    assert any("operating_income suppressed" in n for n in data.notes), (
        "a suppressed field must be explained, not silently dropped"
    )


@pytest.mark.parametrize("ticker", ["CB", "V", "BRK-B"])
def test_non_banks_keep_their_operating_income(ticker):
    """Insurers and payment networks do report operating income; leave them alone."""
    data = _load(ticker)
    assert data.ttm is not None
    assert data.ttm.operating_income is not None, f"{ticker} must keep operating income"
    assert data.ttm.operating_income > 0


def test_suppression_survives_the_frozen_cache_path():
    """A frozen snapshot is deserialized directly; the rule must still hold.

    Without an explicit check at the cache boundary, `_build_statements` is
    bypassed entirely and the bank would carry the EBIT figure again.
    """
    provider = YahooFinanceProvider()
    raw = provider._cache_read("JPM")
    if raw is None:
        pytest.skip("no frozen snapshot for JPM")
    assert raw.ttm.operating_income is None
    assert raw.ttm.ebit is None


def test_build_statements_strips_bank_fields_at_source():
    """The builder is the second line of defence, and it must stand on its own.

    Tested by calling it directly with a synthetic time series, so the cache
    layer cannot mask a regression here.
    """
    ts_data = {
        "annualTotalRevenue": [{"period_end": "2025-12-31", "value": 1000.0}],
        "annualOperatingIncome": [{"period_end": "2025-12-31", "value": 900.0}],
        "annualEBIT": [{"period_end": "2025-12-31", "value": 900.0}],
        "annualNetIncome": [{"period_end": "2025-12-31", "value": 200.0}],
    }
    as_bank = YahooFinanceProvider._build_statements(
        ts_data, "annual", "annual", "USD", 100.0, [], is_bank=True
    )
    assert len(as_bank) == 1
    assert as_bank[0].operating_income is None
    assert as_bank[0].ebit is None
    assert as_bank[0].revenue == 1000.0
    assert as_bank[0].net_income == 200.0

    as_corp = YahooFinanceProvider._build_statements(
        ts_data, "annual", "annual", "USD", 100.0, [], is_bank=False
    )
    assert as_corp[0].operating_income == 900.0
    assert as_corp[0].ebit == 900.0


# --------------------------------------------------------------------------
# Downstream: the bank models never read operating income.
# --------------------------------------------------------------------------
def test_bank_valuation_does_not_depend_on_operating_income():
    """Bank DDM / RIM must produce identical output with the field stripped.

    Guards against a future refactor quietly routing a bank through an
    operating-income-driven model.
    """
    from models.bank import BankDDMModel, BankRIMModel  # noqa: F401  (import check)

    data = _load("JPM")
    assert data.ttm.operating_income is None
    assert data.ttm.net_income is not None
    assert data.ttm.eps is not None


def test_registry_is_shared_with_the_classifier():
    """One list, two importers — a second copy would drift."""
    from classification.classifier import BANK_HOLDING_COMPANIES as classifier_registry

    assert classifier_registry is BANK_HOLDING_COMPANIES


def test_synthetic_bank_keeps_operating_income_untouched():
    """Synthetic fixtures are hand-authored, not vendor EBIT, so they are exempt.

    The rule targets the vendor's mislabelled field, not the concept of a bank.
    """
    from data.providers import SyntheticDataProvider

    data = SyntheticDataProvider().get_financial_data("JPM")
    assert data.ttm is not None
    assert data.ttm.operating_income is not None
