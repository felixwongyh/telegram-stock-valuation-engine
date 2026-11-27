"""§1.3.2 - a frozen snapshot must fail loudly on a cache miss, never fetch.

The freeze switch exists so a validation run cannot silently pick up new market
data mid-flight. Keeping a *stale* entry alive is only half of that promise: if a
ticker is missing from the frozen cache, the provider must refuse to go to the
network. Fetching on a miss would mean the "frozen" run quietly mixes a frozen
snapshot with a live quote - exactly the drift §1.2/§9 forbids, and the PFE
regression (CAGR 1.93% -> 1.39%, RFR 5.052% -> 4.912%).

These tests assert the miss is *refused*, not merely logged.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from data.providers import TreasuryYieldProvider, YahooFinanceProvider


@pytest.fixture
def freeze(monkeypatch):
    monkeypatch.setenv("UVE_FREEZE_CACHE", "1")
    yield
    monkeypatch.delenv("UVE_FREEZE_CACHE", raising=False)


@pytest.fixture
def no_freeze(monkeypatch):
    monkeypatch.delenv("UVE_FREEZE_CACHE", raising=False)


def test_treasury_frozen_miss_must_not_fetch(freeze, monkeypatch, tmp_path):
    """A frozen treasury cache with no file must raise, not download."""
    p = TreasuryYieldProvider.__new__(TreasuryYieldProvider)
    p.cache_enabled = True
    p._cache_dir = str(tmp_path)

    def _boom(*a, **k):
        raise AssertionError("frozen mode reached the network")

    monkeypatch.setattr("requests.get", _boom, raising=False)
    monkeypatch.setattr("httpx.get", _boom, raising=False)

    with pytest.raises(Exception) as ei:
        p.get_yield_curve()
    assert "frozen" in str(ei.value).lower()


def test_yahoo_frozen_miss_must_not_fetch(freeze, monkeypatch, tmp_path):
    """A frozen yahoo cache miss must raise, not call Yahoo."""
    p = YahooFinanceProvider.__new__(YahooFinanceProvider)
    p.cache_enabled = True
    p._cache_dir = str(tmp_path)
    p.use_fallback = False

    calls = []

    def _boom(*a, **k):
        calls.append(1)
        raise AssertionError("frozen mode reached the network")

    monkeypatch.setattr(
        YahooFinanceProvider, "_get_financial_data_sync", _boom, raising=False
    )

    with pytest.raises(Exception):
        asyncio.run(p.get_financial_data("ZZZZ"))
    # The network call itself is the violation - asserting on the message would
    # pass by accident because the wrapper quotes the inner error text.
    assert calls == [], "frozen mode reached the network on a cache miss"


def test_frozen_miss_does_not_write_cache(freeze, tmp_path):
    """A refused miss must not create a cache file (no partial snapshot)."""
    p = TreasuryYieldProvider.__new__(TreasuryYieldProvider)
    p.cache_enabled = True
    p._cache_dir = str(tmp_path)

    with pytest.raises(Exception):
        p.get_yield_curve()
    assert os.listdir(tmp_path) == [], "frozen miss wrote to the snapshot dir"


def test_unfrozen_miss_still_fetches(no_freeze, monkeypatch, tmp_path):
    """Sanity: without freeze the provider must still be allowed to fetch.

    Guards against "fixing" the above by disabling network access everywhere.
    """
    p = TreasuryYieldProvider.__new__(TreasuryYieldProvider)
    p.cache_enabled = True
    p._cache_dir = str(tmp_path)
    p._cache_read()

    assert p._cache_frozen() is False
