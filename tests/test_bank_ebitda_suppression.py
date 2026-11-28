"""A bank's EBITDA must be absent once its EBIT is withheld (U-8).

``_suppress_bank_operating_income`` cleared ``operating_income`` and ``ebit`` but
left ``ebitda``. For JPM the survivor was bit-identical to the pre-fix
synthesized EBIT plus D&A::

    186249682034.89746 + 9896000000.0 = 196145682034.89746

That is a DERIVED number whose only input had just been deleted. It is not a
vendor EBITDA, and letting a multiple model consume it would value the bank on a
quantity that does not exist.

Three paths can produce the field, and all three are pinned here:
  provider ``_suppress_bank_operating_income``, the frozen-cache read, and
  ``FinancialNormalizer.fill_derived_fields`` re-synthesis.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from data.bank_registry import BANK_HOLDING_COMPANIES
from data.models import FinancialData, FinancialStatement
from data.normalizer import FinancialNormalizer
from data.providers import YahooFinanceProvider

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "yahoo_finance"


def _frozen_env(monkeypatch) -> None:
    monkeypatch.setenv("UVE_SNAPSHOT_ID", "20261123")
    monkeypatch.setenv("UVE_FREEZE_CACHE", "1")


def _has_bank_snapshot(ticker: str) -> bool:
    return (CACHE_DIR / f"{ticker}_20261123.json").exists()


# --------------------------------------------------------------- the invariant

def test_bank_ebitda_is_none_and_ebit_is_none(monkeypatch):
    """JPM: after suppression there is no EBIT *and* no EBITDA, in every period."""
    _frozen_env(monkeypatch)
    if not _has_bank_snapshot("JPM"):
        pytest.skip("no frozen JPM snapshot")

    data = asyncio.run(YahooFinanceProvider().get_financial_data("JPM"))
    stmts = [s for s in [data.ttm, *data.annual_income, *data.quarterly_income]
             if s is not None]
    assert stmts, "snapshot yielded no statements"

    for s in stmts:
        assert s.operating_income is None, f"{s.period_type} operating_income leaked"
        assert s.ebit is None, f"{s.period_type} ebit leaked"
        assert s.ebitda is None, (
            f"{s.period_type} ebitda survived suppression: {s.ebitda!r}"
        )


def test_suppression_keeps_the_audit_record(monkeypatch):
    """The number is gone but its provenance is not: on-disk JPM had
    ebitda = ebit + D&A before suppression, and the audit says so."""
    _frozen_env(monkeypatch)
    if not _has_bank_snapshot("JPM"):
        pytest.skip("no frozen JPM snapshot")

    data = asyncio.run(YahooFinanceProvider().get_financial_data("JPM"))

    audited = [s for s in [data.ttm, *data.annual_income, *data.quarterly_income]
               if s is not None and s.suppression_audit.get("ebitda")]
    assert audited, "no statement recorded the suppressed EBITDA"

    for s in audited:
        rec = s.suppression_audit["ebitda"]
        assert rec["availability"] == "NOT_APPLICABLE"
        assert rec["origin_type"] == "DERIVED"
        assert rec["derivation_status"] == "INVALID_INPUT"
        assert rec["input_fields"] == ["ebit", "depreciation_amortization"]
        assert rec["suppressed_value"] > 0
        assert "bank" in rec["reason"].lower()


def test_no_statement_shows_ebitda_while_ebit_is_none(monkeypatch):
    """The specific inconsistency that made this a defect rather than a choice."""
    _frozen_env(monkeypatch)
    if not _has_bank_snapshot("JPM"):
        pytest.skip("no frozen JPM snapshot")

    data = asyncio.run(YahooFinanceProvider().get_financial_data("JPM"))
    for s in [x for x in [data.ttm, *data.annual_income, *data.quarterly_income]
              if x is not None]:
        assert not (s.ebitda is not None and s.ebit is None), (
            f"{s.period_type}: ebitda present while ebit is None"
        )


# ------------------------------------------------- third path: the normalizer

def test_normalizer_does_not_rebuild_bank_ebitda(monkeypatch):
    """``fill_derived_fields`` sets ``ebitda = ebit + D&A`` when ebitda is None.
    For a bank that would undo the suppression, so it must not fire."""
    _frozen_env(monkeypatch)
    data = FinancialData(
        ticker="JPM",
        ttm=FinancialStatement(
            period_end="2026-09-30", period_type="ttm",
            depreciation_amortization=9_896_000_000.0,
        ),
    )
    out = FinancialNormalizer.fill_derived_fields(data)
    assert out.ttm.ebitda is None


def test_normalizer_still_builds_ebitda_for_a_non_bank():
    """The guard is bank-specific. A non-bank keeps the derived field."""
    data = FinancialData(
        ticker="AAPL",
        ttm=FinancialStatement(
            period_end="2026-09-30", period_type="ttm",
            ebit=100.0, depreciation_amortization=10.0,
        ),
    )
    out = FinancialNormalizer.fill_derived_fields(data)
    assert out.ttm.ebitda == 110.0


def test_non_bank_snapshot_keeps_ebitda(monkeypatch):
    """End to end: a non-bank from the same frozen set still has an EBITDA."""
    _frozen_env(monkeypatch)
    if not _has_bank_snapshot("AMD"):
        pytest.skip("no frozen AMD snapshot")
    data = asyncio.run(YahooFinanceProvider().get_financial_data("AMD"))
    present = [s for s in [data.ttm, *data.annual_income] if s is not None
               and s.ebitda is not None]
    assert present, "non-bank ebitda should not be suppressed"


def test_suppression_is_scoped_to_the_bank_registry(monkeypatch):
    """Every ticker in the registry loses EBITDA; nothing else does."""
    monkeypatch.setenv("UVE_FREEZE_CACHE", "1")
    monkeypatch.setenv("UVE_SNAPSHOT_ID", "20261123")
    p = YahooFinanceProvider()
    stmt = FinancialStatement(period_end="2026-09-30", ebit=5.0, ebitda=9.0)
    for ticker in BANK_HOLDING_COMPANIES:
        data = FinancialData(ticker=ticker, ttm=FinancialStatement(
            period_end="2026-09-30", ebit=5.0, ebitda=9.0))
        p._suppress_bank_operating_income(data)
        assert data.ttm.ebitda is None, f"{ticker} kept EBITDA"
