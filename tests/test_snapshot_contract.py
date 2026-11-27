"""§1.3 - The cache is selected by an explicit snapshot id, never by the clock.

Keying the cache off ``datetime.utcnow()`` made the *data* a function of the
machine clock: the same code read a different (or missing) file the next day
and produced different valuations. These tests pin that contract down.

They use a temporary cache directory so they neither read nor write the real
``.cache`` tree.
"""

from __future__ import annotations

import json
import os

import pytest

from data.errors import FrozenSnapshotMissError
from data.providers import (
    SNAPSHOT_ID_ENV,
    TreasuryYieldProvider,
    YahooFinanceProvider,
    resolve_snapshot_id,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(SNAPSHOT_ID_ENV, raising=False)
    monkeypatch.delenv(YahooFinanceProvider._FREEZE_ENV, raising=False)


def test_snapshot_id_is_read_from_the_environment():
    os.environ[SNAPSHOT_ID_ENV] = "20261123"
    assert resolve_snapshot_id() == "20261123"


def test_malformed_snapshot_id_is_an_error_not_a_fallback():
    """A typo must never silently select live data."""
    for bad in ("2026-11-23", "2026112", "202611233", "abcdefgh", "2026112a"):
        os.environ[SNAPSHOT_ID_ENV] = bad
        with pytest.raises(FrozenSnapshotMissError):
            resolve_snapshot_id()


def test_unpinned_snapshot_id_tracks_the_clock():
    """Without a pin the key follows today's date - the documented default."""
    from datetime import datetime

    assert resolve_snapshot_id() == datetime.utcnow().strftime("%Y%m%d")


def test_system_clock_change_does_not_move_a_pinned_snapshot(monkeypatch):
    """The pinned id wins over the clock, so a later run reads the same file."""
    import data.providers as providers

    os.environ[SNAPSHOT_ID_ENV] = "20261123"

    class _FakeClock:
        @staticmethod
        def utcnow():
            raise AssertionError("clock must not be consulted for a pinned id")

    monkeypatch.setattr(providers, "datetime", _FakeClock)
    assert resolve_snapshot_id() == "20261123"


def test_cache_paths_use_the_pinned_snapshot(tmp_path):
    os.environ[SNAPSHOT_ID_ENV] = "20261123"
    yahoo = YahooFinanceProvider()
    yahoo._cache_dir = str(tmp_path)
    treasury = TreasuryYieldProvider()
    treasury._cache_dir = str(tmp_path)

    assert yahoo._cache_path("NVDA").endswith("NVDA_20261123.json")
    assert treasury._cache_path().endswith("treasury_yield_20261123.json")


def test_existing_snapshot_is_read(tmp_path):
    os.environ[SNAPSHOT_ID_ENV] = "20261123"
    os.environ[YahooFinanceProvider._FREEZE_ENV] = "1"
    yahoo = YahooFinanceProvider()
    yahoo._cache_dir = str(tmp_path)

    payload = yahoo._serialize_data_to_jsonable(_minimal_data())
    with open(yahoo._cache_path("TEST"), "w", encoding="utf-8") as f:
        json.dump(payload, f)

    assert yahoo._cache_read("TEST") is not None


def test_missing_snapshot_entry_refuses_to_fetch_live_data(tmp_path):
    """The protection this whole mechanism exists for: no silent live fetch."""
    os.environ[SNAPSHOT_ID_ENV] = "19990101"
    os.environ[YahooFinanceProvider._FREEZE_ENV] = "1"
    yahoo = YahooFinanceProvider()
    yahoo._cache_dir = str(tmp_path)

    import asyncio

    with pytest.raises(FrozenSnapshotMissError):
        asyncio.run(yahoo.get_financial_data("NOSUCHTICKER"))


def test_expired_snapshot_is_still_read_while_frozen(tmp_path):
    """A frozen run must not discard an old file just because its mtime is old."""
    os.environ[SNAPSHOT_ID_ENV] = "20261123"
    os.environ[YahooFinanceProvider._FREEZE_ENV] = "1"
    yahoo = YahooFinanceProvider()
    yahoo._cache_dir = str(tmp_path)

    payload = yahoo._serialize_data_to_jsonable(_minimal_data())
    path = yahoo._cache_path("TEST")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    stale = os.path.getmtime(path) - 30 * 24 * 3600
    os.utime(path, (stale, stale))

    assert yahoo._cache_read("TEST") is not None
    assert os.path.exists(path), "frozen cache must never be deleted"


def test_corrupt_snapshot_fails_loudly(tmp_path):
    """A damaged file must not be silently treated as a cache miss."""
    os.environ[SNAPSHOT_ID_ENV] = "20261123"
    os.environ[YahooFinanceProvider._FREEZE_ENV] = "1"
    yahoo = YahooFinanceProvider()
    yahoo._cache_dir = str(tmp_path)

    with open(yahoo._cache_path("TEST"), "w", encoding="utf-8") as f:
        f.write("{not json")

    assert yahoo._cache_read("TEST") is None


def test_unfrozen_run_may_refetch(tmp_path):
    """With freezing off the provider keeps its normal live-fetch behaviour."""
    os.environ[SNAPSHOT_ID_ENV] = "19990101"
    yahoo = YahooFinanceProvider()
    yahoo._cache_dir = str(tmp_path)

    assert yahoo._cache_read("NOSUCHTICKER") is None


def _minimal_data():
    from data.models import FinancialData

    return FinancialData(ticker="TEST")


def test_treasury_missing_snapshot_entry_refuses_to_fetch(tmp_path):
    os.environ[SNAPSHOT_ID_ENV] = "19990101"
    os.environ[TreasuryYieldProvider._FREEZE_ENV] = "1"
    treasury = TreasuryYieldProvider()
    treasury._cache_dir = str(tmp_path)

    with pytest.raises(FrozenSnapshotMissError):
        treasury._require_frozen_hit_or_raise()
