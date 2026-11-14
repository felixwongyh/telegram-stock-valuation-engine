"""M-31 lock: segment-level revenue source + revenue-composition adapter.

Pins the FMP payload parsing (both documented shapes), the optional-key gate,
the disk cache (resumable / offline replay), the percentage normalisation, and
the business-value-first weighting used by the segment beta (M-35). Also pins
the production source **chain** (M-38): FMP first, then the key-free SEC
filing-instance XBRL fallback when FMP yields nothing. All network access is
faked — the suite stays offline.
"""
from __future__ import annotations

import json
import sys

import pytest

from data.filing_evidence import FilingBusinessExtractor
from data.identity_resolver import IdentityResolver
from data.industry_resolver import SectorIndustryResolver
from data.segment_revenue import (
    Segment,
    SegmentRevenueResolver,
    resolve_segments,
    segment_weights,
    to_revenue_composition,
)


@pytest.fixture(autouse=True)
def _clear_mem(monkeypatch):
    # The resolvers memoise per-ticker results on the class, so tests must
    # start from a clean slate (and a clean key env) to stay independent. The
    # optional FinanceDatabase import is forced to fail so the SEC fallback
    # layer stays hermetic (no local library dependency).
    SegmentRevenueResolver._MEM.clear()
    FilingBusinessExtractor._MEM.clear()
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "financedatabase", None)
    yield
    SegmentRevenueResolver._MEM.clear()
    FilingBusinessExtractor._MEM.clear()


class _FakeResp:
    def __init__(self, payload=None, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else ""

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


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def test_shape_date_to_mix_parses_latest(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "k")
    payload = [
        {"2023-09-30": {"iPhone": 200, "Services": 85}},
        {"2022-09-30": {"iPhone": 205, "Services": 78}},
    ]
    p = SegmentRevenueResolver(client=_FakeClient(payload), cache_path=tmp_path / "s.json")
    segs = p.get_segments("AAPL")
    labels = {s.label: s.revenue for s in segs}
    assert labels == {"iPhone": 200.0, "Services": 85.0}
    assert segs[0].as_of == "2023-09-30"
    assert segs[0].source == "fmp"


def test_shape_flat_segment_to_revenue(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "k")
    payload = [{"AWS": 907, "Advertising": 380, "Subscription": 100}]
    p = SegmentRevenueResolver(client=_FakeClient(payload), cache_path=tmp_path / "s.json")
    segs = p.get_segments("AMZN")
    assert {s.label for s in segs} == {"AWS", "Advertising", "Subscription"}


def test_shape_stable_data_wrapper(tmp_path, monkeypatch):
    # Current FMP /stable shape: metadata wrapper with a nested "data" mix.
    monkeypatch.setenv("FMP_API_KEY", "k")
    payload = [
        {
            "symbol": "AAPL",
            "fiscalYear": 2026,
            "period": "FY",
            "date": "2026-09-26",
            "data": {"iPhone": 254, "Service": 123, "Mac": 37},
        }
    ]
    p = SegmentRevenueResolver(client=_FakeClient(payload), cache_path=tmp_path / "s.json")
    segs = p.get_segments("AAPL")
    labels = {s.label: s.revenue for s in segs}
    assert labels == {"iPhone": 254.0, "Service": 123.0, "Mac": 37.0}
    assert segs[0].as_of == "2026-09-26"
    assert "fiscalYear" not in labels  # metadata must never leak in as a segment


def test_stable_endpoint_is_tried_first(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "k")
    client = _FakeClient([{"data": {"Cloud": 60}}])
    p = SegmentRevenueResolver(client=client, cache_path=tmp_path / "s.json")
    p.get_segments("GOOG")
    assert client.calls[0][0] == (
        "https://financialmodelingprep.com/stable/revenue-product-segmentation"
    )


def test_no_key_returns_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    client = _FakeClient([{"2023": {"X": 1}}])
    p = SegmentRevenueResolver(client=client, cache_path=tmp_path / "s.json")
    assert p.get_segments("AAPL") == []
    assert client.calls == []  # never hits the network without a key


def test_non_positive_and_blank_labels_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "k")
    payload = [{"2023": {"Good": 10, "Zero": 0, "Neg": -5, "": 7, "AlsoGood": 5}}]
    p = SegmentRevenueResolver(client=_FakeClient(payload), cache_path=tmp_path / "s.json")
    segs = p.get_segments("X")
    assert {s.label for s in segs} == {"Good", "AlsoGood"}


def test_disk_cache_persisted_and_replayed_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "k")
    cache = tmp_path / "s.json"
    p1 = SegmentRevenueResolver(
        client=_FakeClient([{"2023": {"Cloud": 60, "Ads": 40}}]), cache_path=cache
    )
    assert p1.get_segments("GOOG")
    assert cache.exists()
    assert json.loads(cache.read_text(encoding="utf-8"))["GOOG"][0]["label"] == "Cloud"

    # Fresh provider, offline, no client → replayed from disk.
    p2 = SegmentRevenueResolver(cache_path=cache, offline=True)
    segs = p2.get_segments("GOOG")
    assert {s.label for s in segs} == {"Cloud", "Ads"}


def test_returns_empty_when_nothing_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "k")
    p = SegmentRevenueResolver(client=_FakeClient({}), cache_path=tmp_path / "s.json")
    assert p.get_segments("ZZZ") == []


# ---------------------------------------------------------------------------
# revenue-composition adapter (taxonomy ③)
# ---------------------------------------------------------------------------
def test_to_revenue_composition_normalises_pct():
    segs = [
        Segment("A", revenue=60.0, source="fmp"),
        Segment("B", revenue=40.0, source="fmp"),
    ]
    comp = to_revenue_composition(segs)
    assert comp.available is True
    pct = {s.label: s.pct for s in comp.segments}
    assert pct == {"A": 0.6, "B": 0.4}
    assert comp.source == "fmp"


def test_to_revenue_composition_unavailable_when_empty():
    comp = to_revenue_composition([])
    assert comp.available is False
    assert comp.segments == []
    assert comp.source == "unavailable"


# ---------------------------------------------------------------------------
# weighting (M-35)
# ---------------------------------------------------------------------------
def test_weights_prefer_operating_income_when_present():
    segs = [
        Segment("A", revenue=100.0, operating_income=80.0),
        Segment("B", revenue=100.0, operating_income=20.0),
    ]
    w = dict(segment_weights(segs))
    assert w["A"] == 0.8
    assert w["B"] == 0.2


def test_weights_fallback_to_revenue_when_income_missing():
    segs = [
        Segment("A", revenue=75.0),
        Segment("B", revenue=25.0),
    ]
    w = dict(segment_weights(segs))
    assert w["A"] == 0.75
    assert w["B"] == 0.25


def test_weights_empty_when_nothing_usable():
    assert segment_weights([Segment("A", revenue=0.0)]) == []


# ---------------------------------------------------------------------------
# multi-key rotation (comma-separated FMP_API_KEY)
# ---------------------------------------------------------------------------
class _KeyAwareClient:
    """Returns 200 only for the accepted key; records every key it was asked."""

    def __init__(self, ok_key, payload):
        self.ok_key = ok_key
        self.payload = payload
        self.keys = []

    def get(self, url, params=None, headers=None):
        key = (params or {}).get("apikey")
        self.keys.append(key)
        if key == self.ok_key:
            return _FakeResp(self.payload, 200)
        return _FakeResp({"error": "Invalid API KEY"}, 401)


def test_multi_key_rotation_falls_through_to_second_key(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "bad-key,good-key")
    client = _KeyAwareClient("good-key", [{"AWS": 100, "Advertising": 50}])
    p = SegmentRevenueResolver(client=client, cache_path=tmp_path / "s.json")
    segs = p.get_segments("AMZN")
    assert {s.label for s in segs} == {"AWS", "Advertising"}
    assert client.keys[0] == "bad-key"          # first key tried first
    assert "good-key" in client.keys            # falls through to the second


def test_multi_key_strips_whitespace(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", " bad , good ")
    client = _KeyAwareClient("good", [{"Cloud": 60, "Ads": 40}])
    p = SegmentRevenueResolver(client=client, cache_path=tmp_path / "s.json")
    assert {s.label for s in p.get_segments("GOOG")} == {"Cloud", "Ads"}


def test_all_keys_exhausted_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "k1,k2")
    client = _KeyAwareClient("never-matches", [{"X": 1}])
    p = SegmentRevenueResolver(client=client, cache_path=tmp_path / "s.json")
    assert p.get_segments("ZZZ") == []
    assert set(client.keys) == {"k1", "k2"}


# ---------------------------------------------------------------------------
# source chain: FMP → SEC filing-instance XBRL fallback (M-31 → M-38)
# ---------------------------------------------------------------------------
_INSTANCE_XBRL = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:us-gaap="http://fasb.org/us-gaap/2023"
            xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
  <xbrli:context id="c_sw"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period>
    <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">us-gaap:CloudMember</xbrldi:explicitMember></xbrli:segment></xbrli:context>
  <xbrli:context id="c_hw"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period>
    <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">us-gaap:HardwareMember</xbrldi:explicitMember></xbrli:segment></xbrli:context>
  <us-gaap:Revenues contextRef="c_sw" unitRef="usd">80</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="c_hw" unitRef="usd">20</us-gaap:Revenues>
</xbrli:xbrl>
"""


class _ChainClient:
    """Routes a GET to either the FMP or the SEC layer by URL substring."""

    def __init__(self, *, fmp_payload=None, fmp_status=200, instance=_INSTANCE_XBRL):
        self._fmp_payload = fmp_payload
        self._fmp_status = fmp_status
        self._routes = {
            "company_tickers": {"0": {"ticker": "AAPL", "cik_str": 320193}},
            "submissions": {
                "filings": {
                    "recent": {
                        "form": ["10-K"],
                        "accessionNumber": ["0000320193-23-000106"],
                        "filingDate": ["2023-11-03"],
                        "primaryDocument": ["aapl-20231231.htm"],
                    }
                }
            },
            "_htm.xml": _FakeResp(text=instance),
            "/Archives/edgar/data/320193/": {
                "directory": {"item": [{"name": "aapl-20231231_htm.xml"}]}
            },
        }
        self.calls = []

    def get(self, url, params=None, headers=None):
        self.calls.append(url)
        if "financialmodelingprep.com" in url:
            return _FakeResp(self._fmp_payload, self._fmp_status)
        for needle, payload in self._routes.items():
            if needle in url:
                return payload if isinstance(payload, _FakeResp) else _FakeResp(payload)
        return _FakeResp({}, 404)

    def sec_calls(self):
        return [u for u in self.calls if "sec.gov" in u]


def _ident(client, tmp_path):
    """Hermetic identity resolver (tmp cache, so the repo cache is untouched)."""
    sector = SectorIndustryResolver(client=client, cache_path=tmp_path / "c.json")
    return IdentityResolver(client=client, sector_resolver=sector)


def _chain(ticker, client, tmp_path, *, offline=False, identity_resolver=None):
    return resolve_segments(
        ticker,
        client=client,
        offline=offline,
        fmp_cache_path=tmp_path / "s.json",
        filing_cache_path=tmp_path / "f.json",
        identity_resolver=identity_resolver,
    )


def test_chain_uses_fmp_and_never_hits_sec_when_key_works(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "good")
    client = _ChainClient(fmp_payload=[{"AWS": 100, "Advertising": 50}])
    segs = _chain("AMZN", client, tmp_path)
    assert {s.label for s in segs} == {"AWS", "Advertising"}
    assert all(s.source == "fmp" for s in segs)
    assert client.sec_calls() == []  # FMP resolved → SEC fallback untouched


def test_chain_falls_back_to_sec_when_fmp_key_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "expired")
    client = _ChainClient(fmp_payload={"error": "Invalid API KEY"}, fmp_status=401)
    segs = _chain("AAPL", client, tmp_path, identity_resolver=_ident(client, tmp_path))
    assert [s.label for s in segs] == ["Cloud", "Hardware"]
    assert all(s.source == "sec-xbrl" for s in segs)
    assert client.sec_calls()  # the SEC layer was reached


def test_chain_falls_back_to_sec_when_no_key(tmp_path, monkeypatch):
    client = _ChainClient()
    segs = _chain("AAPL", client, tmp_path, identity_resolver=_ident(client, tmp_path))
    assert {s.label for s in segs} == {"Cloud", "Hardware"}
    assert all(s.source == "sec-xbrl" for s in segs)


def test_chain_empty_when_neither_layer_resolves(tmp_path, monkeypatch):
    client = _ChainClient(fmp_payload={"error": "Invalid API KEY"}, fmp_status=401)
    # Blank the SEC routes so nothing resolves there either.
    client._routes = {}
    segs = _chain("AAPL", client, tmp_path, identity_resolver=_ident(client, tmp_path))
    assert segs == []


def test_chain_offline_makes_no_network_calls(tmp_path, monkeypatch):
    client = _ChainClient()
    segs = _chain("AAPL", client, tmp_path, offline=True)
    assert segs == []
    assert client.calls == []
