"""H-03 lock: secondary sector/industry data source resolution chain.

Verifies the fallback provider is (a) parsed correctly for each layer, (b)
memoised to disk so a batch backfill is resumable, and (c) silent (empty) when
no source can resolve. All network access is faked — the suite stays offline.
"""
from __future__ import annotations

import json
from pathlib import Path

from data.secondary_profile import SecondaryProfileProvider


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.calls = []

    def get(self, url, params=None, headers=None):
        self.calls.append((url, params))
        return _FakeResp(self._payload, self.status_code)


def test_yahoo_search_layer_parses_and_prefers_exact_symbol(tmp_path):
    payload = {
        "quotes": [
            {"symbol": "SOFI.W", "quoteType": "EQUITY", "sector": "Wrong", "industry": "Wrong"},
            {"symbol": "SOFI", "quoteType": "EQUITY",
             "sector": "Financial Services", "industry": "Credit Services"},
        ]
    }
    client = _FakeClient(payload)
    p = SecondaryProfileProvider(client=client, cache_path=tmp_path / "c.json")
    info = p.get_sector_industry("SOFI")
    assert info["sector"] == "Financial Services"
    assert info["industry"] == "Credit Services"
    assert info["source"] == "yahoo-search"
    assert client.calls[0][0].endswith("/v1/finance/search")


def test_result_persisted_to_disk_and_reused_offline(tmp_path):
    cache = tmp_path / "c.json"
    p1 = SecondaryProfileProvider(
        client=_FakeClient({"quotes": [{"symbol": "XOM", "quoteType": "EQUITY",
                                        "sector": "Energy", "industry": "Oil & Gas Integrated"}]}),
        cache_path=cache,
    )
    assert p1.get_sector_industry("XOM")["sector"] == "Energy"
    assert cache.exists()
    assert json.loads(cache.read_text(encoding="utf-8"))["XOM"]["sector"] == "Energy"

    # Fresh provider, offline, no client → served from disk.
    p2 = SecondaryProfileProvider(cache_path=cache, offline=True)
    info = p2.get_sector_industry("XOM")
    assert info["sector"] == "Energy"
    assert info["industry"] == "Oil & Gas Integrated"


def test_returns_empty_when_nothing_resolves(tmp_path):
    p = SecondaryProfileProvider(
        client=_FakeClient({"quotes": []}), cache_path=tmp_path / "c.json"
    )
    assert p.get_sector_industry("NOPE") == {}


def test_fmp_layer_used_only_when_key_present(tmp_path, monkeypatch):
    # With no key, the FMP layer must be skipped entirely.
    p = SecondaryProfileProvider(
        client=_FakeClient({"quotes": []}), cache_path=tmp_path / "c.json"
    )
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    assert p._from_fmp("AAPL") == {}
