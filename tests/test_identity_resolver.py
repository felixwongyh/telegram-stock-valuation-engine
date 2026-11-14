"""Identity layer lock: ticker → durable identity anchors (CIK / SIC / FIGI).

Pins the "never fabricate" contract and the optional-source behaviour: the SEC
chain supplies CIK/SIC, OpenFIGI is used only when a key is present, and every
absent identifier stays ``None`` (never a guessed value). All network access is
faked so the suite stays offline & deterministic.
"""
from __future__ import annotations

import pytest

from data.identity_resolver import IdentityResolver, ResolvedIdentity
from data.industry_resolver import SectorIndustryResolver


@pytest.fixture(autouse=True)
def _clear_mem():
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
    def __init__(self, routes=None, default=None, post_payload=None):
        self._routes = routes or {}
        self._default = default
        self._post_payload = post_payload
        self.get_calls = []
        self.post_calls = []

    def get(self, url, params=None, headers=None):
        self.get_calls.append((url, params))
        for needle, payload in self._routes.items():
            if needle in url:
                if isinstance(payload, tuple):
                    return _FakeResp(payload[0], payload[1])
                return _FakeResp(payload)
        if self._default is not None:
            return _FakeResp(self._default)
        return _FakeResp({}, 404)

    def post(self, url, json=None, headers=None):
        self.post_calls.append((url, json, headers))
        return _FakeResp(self._post_payload if self._post_payload is not None else [])


def _sec_routes(payload):
    return {
        "company_tickers": {"0": {"ticker": "AAPL", "cik_str": 320193}},
        "submissions": payload,
    }


def _resolver(tmp_path, client, key=None):
    sector = SectorIndustryResolver(client=client, cache_path=tmp_path / "c.json")
    return IdentityResolver(client=client, sector_resolver=sector, openfigi_key=key)


def test_sec_chain_supplies_cik(tmp_path):
    client = _FakeClient(_sec_routes({"sic": 3571, "sicDescription": "Electronic Computers"}))
    ident = _resolver(tmp_path, client).resolve("AAPL")
    assert isinstance(ident, ResolvedIdentity)
    assert ident.cik == "0000320193"
    assert ident.has_regulatory_id


def test_nothing_resolved_is_never_fabricated(tmp_path):
    client = _FakeClient({})  # every layer 404 / empty
    ident = _resolver(tmp_path, client).resolve("ZZZZ")
    assert ident.cik is None
    assert ident.sic is None
    assert ident.figi is None
    assert not ident.has_regulatory_id
    assert ident.note
    assert set(ident.provenance().values()) == {"unknown"}


def test_openfigi_used_only_with_key(tmp_path):
    client = _FakeClient(_sec_routes({}), post_payload=[{"data": [{"figi": "BBG000B9XRY4"}]}])
    with_key = _resolver(tmp_path, client, key="k").resolve("AAPL")
    assert with_key.figi == "BBG000B9XRY4"
    assert len(client.post_calls) == 1

    client2 = _FakeClient(_sec_routes({}), post_payload=[{"data": [{"figi": "SHOULD_NOT_USE"}]}])
    without_key = _resolver(tmp_path, client2).resolve("AAPL")
    assert without_key.figi is None
    assert client2.post_calls == []


def test_offline_skips_openfigi(tmp_path):
    client = _FakeClient(_sec_routes({}), post_payload=[{"data": [{"figi": "X"}]}])
    sector = SectorIndustryResolver(client=client, cache_path=tmp_path / "c.json")
    ident = IdentityResolver(
        client=client, sector_resolver=sector, offline=True, openfigi_key="k"
    ).resolve("AAPL")
    assert ident.figi is None
    assert client.post_calls == []


def test_empty_ticker(tmp_path):
    ident = _resolver(tmp_path, _FakeClient({})).resolve("   ")
    assert ident.cik is None and ident.figi is None
