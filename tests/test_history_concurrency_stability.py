"""§6/§7 - Time-series inputs and interleaved execution.

§6: the engine reads TTM plus historical statements. A single corrupted or
reordered history must not silently change the valuation - either it is used
correctly or the model declines.

§7: ``NAME_TO_MODEL`` holds one shared model instance per model name, so any
per-call state written onto the model leaks between tickers. Concurrent and
interleaved execution must produce exactly the sequential result.
"""

from __future__ import annotations

import asyncio
import copy
import logging

import pytest

from benchmark.collector import collect
from classification.classifier import BusinessClassifier
from data.normalizer import FinancialNormalizer
from data.providers import SyntheticDataProvider
from data.validator import DataValidator
from models.reverse_dcf import ReverseDCFModel

logging.disable(logging.CRITICAL)


@pytest.fixture(scope="module")
def base():
    d = DataValidator.validate(
        FinancialNormalizer.normalize_all(SyntheticDataProvider().get_financial_data("AAPL"))
    )
    return d, BusinessClassifier().classify(d)


# ---------------------------------------------------------------- §6 history

def test_identical_history_gives_identical_answer(base) -> None:
    """§6.1: the same history twice must not drift (no hidden state in history)."""
    data, profile = base
    a = ReverseDCFModel().calculate(copy.deepcopy(data), profile)
    b = ReverseDCFModel().calculate(copy.deepcopy(data), profile)
    assert (a.breakdown or {}).get("implied_revenue_cagr") == (
        b.breakdown or {}
    ).get("implied_revenue_cagr")


def test_model_does_not_mutate_the_input_data(base) -> None:
    """§6.2: a run must not write into the caller's FinancialData.

    Silent input mutation would make the second call on the same object behave
    differently from the first - a reproducibility bug disguised as a modelling
    result.
    """
    data, profile = base
    before = copy.deepcopy(data)
    ReverseDCFModel().calculate(data, profile)

    for attr in ("revenue", "free_cash_flow", "operating_cash_flow", "capex"):
        assert getattr(data.ttm, attr, None) == getattr(before.ttm, attr, None), attr
    assert data.market.current_price == before.market.current_price
    assert data.market.shares_outstanding == before.market.shares_outstanding


def test_repeated_calls_on_same_model_are_stable(base) -> None:
    """§6.3: the shared model instance must not accumulate state across calls."""
    data, profile = base
    m = ReverseDCFModel()
    first = (m.calculate(data, profile).breakdown or {}).get("implied_revenue_cagr")
    for _ in range(3):
        again = (m.calculate(data, profile).breakdown or {}).get("implied_revenue_cagr")
        assert again == first


# ------------------------------------------------------------ §7 concurrency

@pytest.fixture(scope="module")
def frozen(module_missing_guard=None):
    import os
    os.environ.setdefault("UVE_FREEZE_CACHE", "1")
    return True


SAMPLE = ["NVDA", "KO", "CEG", "PFE", "NEE", "WMT", "COST", "JNJ"]
KEYS = ["rd_status", "rd_implied_revenue_cagr", "rd_wacc", "beta_used", "risk_free_rate"]


def _pick(d: dict) -> dict:
    return {k: d.get(k) for k in KEYS}


def test_concurrent_collection_matches_sequential(frozen) -> None:
    """§7.1: gathering all tickers at once must equal running them one by one."""
    async def run() -> tuple[dict, dict]:
        seq = {}
        for t in SAMPLE:
            seq[t] = _pick((await collect(t)).to_dict())
        conc = {}
        results = await asyncio.gather(*[collect(t) for t in SAMPLE])
        for t, r in zip(SAMPLE, results):
            conc[t] = _pick(r.to_dict())
        return seq, conc

    seq, conc = asyncio.run(run())
    for t in SAMPLE:
        assert seq[t] == conc[t], f"{t} differs under concurrency: {seq[t]} vs {conc[t]}"


def test_interleaved_models_do_not_cross_contaminate(base) -> None:
    """§7.2: two models run in alternation must each keep their own answer.

    ``ReverseDCFModel`` is a process-wide singleton, so alternating calls is the
    cheapest way to expose leaked instance state.
    """
    data, profile = base
    m1 = ReverseDCFModel()
    m2 = ReverseDCFModel()

    a1 = (m1.calculate(data, profile).breakdown or {}).get("implied_revenue_cagr")
    b1 = (m2.calculate(data, profile).breakdown or {}).get("implied_revenue_cagr")
    a2 = (m1.calculate(data, profile).breakdown or {}).get("implied_revenue_cagr")
    b2 = (m2.calculate(data, profile).breakdown or {}).get("implied_revenue_cagr")

    assert a1 == a2 == b1 == b2, f"interleaving changed results: {a1},{a2},{b1},{b2}"


def test_horizon_does_not_leak_between_business_types() -> None:
    """§7.3: the Session #16 horizon leak must stay fixed.

    A model forced to one horizon for a SaaS profile must not carry that horizon
    into a subsequent utility run.
    """
    from types import SimpleNamespace

    from config import resolve_forecast_horizon

    m = ReverseDCFModel()
    assert m._resolve_horizon(SimpleNamespace(business_type="SaaS")) == 7
    # The shared instance must resolve the next type independently, not reuse 7.
    assert m._resolve_horizon(SimpleNamespace(business_type="Utility")) == 5
    assert m._resolve_horizon(SimpleNamespace(business_type="Utility")) == (
        resolve_forecast_horizon("Utility")
    )
    # Back to SaaS still yields its own horizon.
    assert m._resolve_horizon(SimpleNamespace(business_type="SaaS")) == 7
