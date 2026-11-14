"""H-03 lock: multi-source sector/industry resolution chain.

Pins the resolution order — FinanceDatabase (offline) -> SEC EDGAR SIC (bridged
via ``data.sic_map``) -> Wikidata — plus the disk cache and the "never fabricate"
contract. All network access is faked, so the suite stays offline & deterministic.
"""
from __future__ import annotations

import json
import sys
import types

import pandas as pd
import pytest

from data.industry_resolver import SectorIndustryResolver


@pytest.fixture(autouse=True)
def _clear_mem():
    """The memo dict is class-level; isolate tests from each other."""
    SectorIndustryResolver._MEM = {}
    yield
    SectorIndustryResolver._MEM = {}


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeClient:
    """Routes a GET by URL substring so one client serves every layer."""

    def __init__(self, routes, default=None):
        self._routes = routes
        self._default = default
        self.calls = []

    def get(self, url, params=None, headers=None):
        self.calls.append((url, params))
        for needle, payload in self._routes.items():
            if needle in url:
                if isinstance(payload, tuple):
                    return _FakeResp(payload[0], payload[1])
                return _FakeResp(payload)
        if self._default is not None:
            return _FakeResp(self._default)
        return _FakeResp({}, 404)


def _fake_financedatabase(df):
    class _Eq:
        def select(self, **kwargs):
            return df

    return types.SimpleNamespace(Equities=lambda: _Eq())


def test_financedatabase_layer_parsed_first(monkeypatch, tmp_path):
    df = pd.DataFrame(
        [{"sector": "Financial Services", "industry": "Asset Management"}],
        index=["BLK"],
    )
    monkeypatch.setitem(sys.modules, "financedatabase", _fake_financedatabase(df))
    client = _FakeClient({})
    r = SectorIndustryResolver(client=client, cache_path=tmp_path / "c.json")
    info = r.resolve("BLK")
    assert info["sector"] == "Financial Services"
    assert info["industry"] == "Asset Management"
    assert info["source"] == "financedatabase"
    # No HTTP should have fired when the offline DB answers.
    assert client.calls == []


def test_sec_layer_maps_sic_to_yahoo(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "financedatabase", None)  # force ImportError
    client = _FakeClient(
        {
            "company_tickers.json": {"0": {"cik_str": 320193, "ticker": "AAPL"}},
            "submissions/CIK0000320193.json": {
                "sic": "3571",
                "sicDescription": "Electronic Computers",
            },
        }
    )
    r = SectorIndustryResolver(client=client, cache_path=tmp_path / "c.json")
    info = r.resolve("AAPL")
    assert info["sector"] == "Technology"
    assert info["industry"] == "Computer Hardware"
    assert info["sic"] == "3571"
    assert info["sic_description"] == "Electronic Computers"
    assert info["source"] == "sec-edgar"


def test_sec_layer_handles_dotted_ticker_variants(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "financedatabase", None)
    client = _FakeClient(
        {
            "company_tickers.json": {"0": {"cik_str": 1067983, "ticker": "BRK-B"}},
            "submissions/CIK0001067983.json": {"sic": "6331", "sicDescription": "Fire, Marine & Casualty"},
        }
    )
    r = SectorIndustryResolver(client=client, cache_path=tmp_path / "c.json")
    info = r.resolve("BRK.B")
    assert info["source"] == "sec-edgar"
    assert info["industry"] == "Insurance - Property & Casualty"


def test_wikidata_layer_used_as_last_resort(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "financedatabase", None)
    client = _FakeClient(
        {
            "company_tickers.json": {},  # no SEC mapping -> SEC layer abstains
            "query.wikidata.org": {
                "results": {"bindings": [{"industryLabel": {"value": "Software industry"}}]}
            },
        }
    )
    r = SectorIndustryResolver(client=client, cache_path=tmp_path / "c.json")
    info = r.resolve("ZZZZ")
    assert info["source"] == "wikidata"
    assert info["sector"] == "Technology"
    assert info["industry"] == "Software - Application"


def test_result_persisted_and_reused_offline(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "financedatabase", None)
    cache = tmp_path / "c.json"
    client = _FakeClient(
        {
            "company_tickers.json": {"0": {"cik_str": 789019, "ticker": "MSFT"}},
            "submissions/CIK0000789019.json": {"sic": "7372", "sicDescription": "Services-Prepackaged Software"},
        }
    )
    first = SectorIndustryResolver(client=client, cache_path=cache).resolve("MSFT")
    assert first["sector"] == "Technology"
    assert cache.exists()
    on_disk = json.loads(cache.read_text(encoding="utf-8"))
    assert on_disk["MSFT"]["industry"] == "Software - Application"

    # Fresh, offline provider with no client -> served purely from disk.
    offline = SectorIndustryResolver(cache_path=cache, offline=True)
    assert offline.resolve("MSFT")["industry"] == "Software - Application"


def test_offline_without_cache_returns_empty(tmp_path):
    r = SectorIndustryResolver(cache_path=tmp_path / "missing.json", offline=True)
    assert r.resolve("AAPL") == {}


def test_returns_empty_when_nothing_resolves(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "financedatabase", None)
    client = _FakeClient({"company_tickers.json": {}})
    r = SectorIndustryResolver(client=client, cache_path=tmp_path / "c.json")
    assert r.resolve("NOPE") == {}


def test_batch_get_returns_only_nonempty(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "financedatabase", None)
    client = _FakeClient(
        {
            "company_tickers.json": {"0": {"cik_str": 320193, "ticker": "AAPL"}},
            "submissions/CIK0000320193.json": {"sic": "3571", "sicDescription": "Electronic Computers"},
        }
    )
    r = SectorIndustryResolver(client=client, cache_path=tmp_path / "c.json")
    out = r.batch_get(["AAPL", "NOPE"])
    assert set(out) == {"AAPL"}
    assert out["AAPL"]["source"] == "sec-edgar"
