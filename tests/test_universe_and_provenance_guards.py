"""§10 M08/M15: guards that had no test before this file existed.

Master Validation §10 asks for 16 deliberate defects, each caught by a *named*
test. Two of them had no test at all:

* M08 - deleting the synthetic-provenance tag, so demo data reads as live.
* M15 - dropping a ticker from the frozen universe, so 50 silently becomes 49.

A mutation with no test is not "not yet written"; it is a hole in the
acceptance suite. These tests close it.
"""

from __future__ import annotations

import copy

import pytest

from benchmark.registry import tickers, validate_registry
from data.models import DataSource
from data.normalizer import FinancialNormalizer
from data.providers import SyntheticDataProvider
from data.validator import DataValidator

FROZEN_UNIVERSE = 50


def _synthetic_aapl():
    return FinancialNormalizer.normalize_all(
        SyntheticDataProvider().get_financial_data("AAPL")
    )


def test_synthetic_source_is_flagged():
    """Synthetic data must carry a machine-readable provenance tag.

    Without the tag, a demo valuation is indistinguishable from a live one in
    the report - the reader cannot tell they are looking at fake numbers.
    """
    data = copy.deepcopy(_synthetic_aapl())
    data = DataValidator._check_data_provenance(data)

    assert data.source == DataSource.SYNTHETIC
    assert "synthetic_demo_not_live_market" in data.quality.missing_fields, (
        "synthetic data was not tagged; it would read as live market data"
    )
    assert data.quality.data_quality_score <= 35, (
        "synthetic data must cap the quality score at 35"
    )
    assert any("SYNTHETIC" in n for n in data.notes), (
        "the human-readable synthetic warning is missing from notes"
    )


def test_universe_is_fifty_tickers():
    """The frozen benchmark universe is exactly 50 unique tickers.

    The whole acceptance story rests on 50 = 32 + 9 + 9. If a ticker can vanish
    from the registry, that identity silently becomes 49 = ... and every
    downstream count is wrong.
    """
    ts = tickers()
    assert len(ts) == FROZEN_UNIVERSE, (
        f"universe has {len(ts)} tickers, expected {FROZEN_UNIVERSE}: "
        f"{sorted(set(ts))}"
    )
    assert len(set(ts)) == len(ts), "duplicate tickers in the universe"


def test_registry_has_no_structural_problems():
    """``validate_registry`` must stay clean: no dupes, gaps or contradictions."""
    problems = validate_registry()
    assert problems == [], f"registry problems: {problems}"


@pytest.mark.parametrize("ticker", ["VICI", "PLD", "AMT", "O"])
def test_reits_are_present_in_the_universe(ticker: str):
    """The routed-out REITs are part of the 9 ``MODEL_NOT_APPLICABLE`` names.

    Dropping one is the M15 defect in its most likely form: an edit to the
    registry that looks harmless and silently changes the denominator.
    """
    assert ticker in tickers(), f"{ticker} missing from the frozen universe"
