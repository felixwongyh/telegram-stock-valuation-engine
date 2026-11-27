"""A benchmark run must be reproducible from one data snapshot.

The 4h cache TTL refetched the 10Y Treasury yield mid-validation, moving PFE's
WACC from 6.267% to 6.123% and its implied revenue CAGR from 1.93% to 1.39%
with no code change. That is market-data drift masquerading as a code
regression - precisely what Master Validation §1.2/§9 forbid.

``UVE_FREEZE_CACHE`` makes cached payloads immortal so a run can be reproduced
byte-for-byte from a fixed snapshot.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from data.providers import TreasuryYieldProvider, YahooFinanceProvider


def _age_file(path: str, hours: float) -> None:
    """Backdate a file's mtime so it looks older than the TTL."""
    old = time.time() - hours * 3600
    os.utime(path, (old, old))


@pytest.fixture()
def frozen(monkeypatch):
    monkeypatch.setenv(YahooFinanceProvider._FREEZE_ENV, "1")
    yield
    monkeypatch.delenv(YahooFinanceProvider._FREEZE_ENV, raising=False)


def test_freeze_flag_is_read_from_env(monkeypatch) -> None:
    monkeypatch.setenv(YahooFinanceProvider._FREEZE_ENV, "1")
    assert YahooFinanceProvider._cache_frozen() is True
    monkeypatch.setenv(YahooFinanceProvider._FREEZE_ENV, "0")
    assert YahooFinanceProvider._cache_frozen() is False
    monkeypatch.delenv(YahooFinanceProvider._FREEZE_ENV, raising=False)
    assert YahooFinanceProvider._cache_frozen() is False


def _write_yahoo_cache(tmp_path, provider: YahooFinanceProvider, ticker: str) -> str:
    """Write a minimally valid cache file and return its path."""
    path = str(tmp_path / f"{ticker}_test.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"__cache_schema_version__": provider._CACHE_SCHEMA_VERSION}, fh)
    return path


def test_expired_cache_is_deleted_when_not_frozen(tmp_path, monkeypatch) -> None:
    """Baseline: without the flag, a stale file is removed (existing behaviour)."""
    monkeypatch.delenv(YahooFinanceProvider._FREEZE_ENV, raising=False)
    p = YahooFinanceProvider()
    path = _write_yahoo_cache(tmp_path, p, "TEST")
    _age_file(path, hours=24)
    monkeypatch.setattr(p, "_cache_path", lambda t: path)
    assert p._cache_read("TEST") is None
    assert not os.path.exists(path), "stale cache should have been deleted"


def test_expired_cache_survives_when_frozen(tmp_path, monkeypatch, frozen) -> None:
    """With the flag, a stale file is neither deleted nor ignored for age.

    The read may still fail to decode a deliberately minimal payload, but the
    *file* must survive: that is what makes the snapshot reproducible.
    """
    p = YahooFinanceProvider()
    path = _write_yahoo_cache(tmp_path, p, "TEST")
    _age_file(path, hours=24)
    monkeypatch.setattr(p, "_cache_path", lambda t: path)
    p._cache_read("TEST")
    assert os.path.exists(path), "frozen cache must never be deleted"


def test_freeze_is_shared_by_treasury_provider(monkeypatch) -> None:
    """The yield provider must honour the same switch, not its own copy."""
    monkeypatch.setenv(YahooFinanceProvider._FREEZE_ENV, "1")
    assert TreasuryYieldProvider._cache_frozen() is True
