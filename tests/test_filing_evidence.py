"""M-38 lock: 10-K / 20-F filing-instance XBRL business evidence.

Pins the extraction contract — locates the latest annual filing, downloads its
XBRL instance, and parses per-segment revenue without ever folding the
consolidated total into a segment or fabricating a mix. All network access is
faked, so the suite stays offline & deterministic.
"""
from __future__ import annotations

import sys

import pytest

from data.filing_evidence import (
    FilingBusinessExtractor,
    FilingRef,
    parse_segment_revenue,
)
from data.identity_resolver import IdentityResolver
from data.industry_resolver import SectorIndustryResolver
from data.segment_revenue import to_revenue_composition

_INSTANCE = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:us-gaap="http://fasb.org/us-gaap/2023"
            xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
  <xbrli:context id="c_total">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2022-10-01</xbrli:startDate><xbrli:endDate>2023-09-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c_sw">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2022-10-01</xbrli:startDate><xbrli:endDate>2023-09-30</xbrli:endDate></xbrli:period>
    <xbrli:segment>
      <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">us-gaap:SoftwareAndServicesMember</xbrldi:explicitMember>
    </xbrli:segment>
  </xbrli:context>
  <xbrli:context id="c_hw">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2022-10-01</xbrli:startDate><xbrli:endDate>2023-09-30</xbrli:endDate></xbrli:period>
    <xbrli:segment>
      <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">us-gaap:HardwareProductsMember</xbrldi:explicitMember>
    </xbrli:segment>
  </xbrli:context>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="c_total" unitRef="usd" decimals="-6">383285000000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="c_sw" unitRef="usd" decimals="-6">240000000000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="c_hw" unitRef="usd" decimals="-6">143285000000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
</xbrli:xbrl>
"""


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Class-level memo dicts + optional import are isolated per test."""
    SectorIndustryResolver._MEM = {}
    FilingBusinessExtractor._MEM = {}
    monkeypatch.setitem(sys.modules, "financedatabase", None)  # force ImportError
    yield
    SectorIndustryResolver._MEM = {}
    FilingBusinessExtractor._MEM = {}


class _FakeResp:
    def __init__(self, payload=None, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else ""

    def json(self):
        return self._payload


class _FakeClient:
    """Routes a GET by URL substring (order matters: most specific first)."""

    def __init__(self, routes=None, default=None):
        self._routes = routes or {}
        self._default = default
        self.calls = []

    def get(self, url, params=None, headers=None):
        self.calls.append(url)
        for needle, payload in self._routes.items():
            if needle in url:
                if isinstance(payload, _FakeResp):
                    return payload
                return _FakeResp(payload)
        if self._default is not None:
            return self._default
        return _FakeResp({}, 404)


# ===========================================================================
# Pure XBRL parsing
# ===========================================================================
class TestParseSegmentRevenue:
    def test_segments_parsed_and_total_excluded(self):
        rows = parse_segment_revenue(_INSTANCE)
        assert rows == [("Software And Services", 240000000000.0), ("Hardware Products", 143285000000.0)]

    def test_latest_period_wins(self):
        xml = _INSTANCE.replace(
            "</xbrli:xbrl>",
            """<xbrli:context id="c_sw_prev">
    <xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2021-10-01</xbrli:startDate><xbrli:endDate>2022-09-30</xbrli:endDate></xbrli:period>
    <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">us-gaap:SoftwareAndServicesMember</xbrldi:explicitMember></xbrli:segment>
  </xbrli:context>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="c_sw_prev" unitRef="usd">999</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
</xbrli:xbrl>""",
        )
        rows = parse_segment_revenue(xml)
        # Prior-year comparative is ignored; the current period is used.
        assert ("Software And Services", 240000000000.0) in rows
        assert all(v != 999.0 for _, v in rows)

    def test_business_axis_preferred_over_geographic(self):
        xml = """<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:us-gaap="http://fasb.org/us-gaap/2023"
            xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
  <xbrli:context id="b"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period>
    <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">us-gaap:CloudMember</xbrldi:explicitMember></xbrli:segment></xbrli:context>
  <xbrli:context id="g"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-12-31</xbrli:endDate></xbrli:period>
    <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementGeographicalAxis">us-gaap:AmericasMember</xbrldi:explicitMember></xbrli:segment></xbrli:context>
  <us-gaap:Revenues contextRef="b" unitRef="usd">100</us-gaap:Revenues>
  <us-gaap:Revenues contextRef="g" unitRef="usd">100</us-gaap:Revenues>
</xbrli:xbrl>"""
        assert parse_segment_revenue(xml) == [("Cloud", 100.0)]

    def test_instant_context_is_ignored(self):
        xml = """<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:us-gaap="http://fasb.org/us-gaap/2023"
            xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
  <xbrli:context id="i"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period>
    <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">us-gaap:CloudMember</xbrldi:explicitMember></xbrli:segment></xbrli:context>
  <us-gaap:Revenues contextRef="i" unitRef="usd">100</us-gaap:Revenues>
</xbrli:xbrl>"""
        assert parse_segment_revenue(xml) == []

    def test_malformed_and_empty_return_empty(self):
        assert parse_segment_revenue("<not-xml") == []
        assert parse_segment_revenue("") == []


# ===========================================================================
# Filing locator + end-to-end extraction (faked network)
# ===========================================================================
def _routes(instance=_INSTANCE, forms=("8-K", "10-K")):
    return {
        "company_tickers": {"0": {"ticker": "AAPL", "cik_str": 320193}},
        "submissions": {
            "filings": {
                "recent": {
                    "form": list(forms),
                    "accessionNumber": ["0000320193-23-000077", "0000320193-23-000106"],
                    "filingDate": ["2023-11-02", "2023-11-03"],
                    "primaryDocument": ["a8k.htm", "aapl-20230930.htm"],
                }
            }
        },
        "_htm.xml": _FakeResp(text=instance),
        "/Archives/edgar/data/320193/": {
            "directory": {"item": [{"name": "FilingSummary.xml"}, {"name": "aapl-20230930_htm.xml"}]}
        },
    }


def _extractor(tmp_path, client):
    """Wire a hermetic extractor (tmp caches, so no repo state is touched)."""
    sector = SectorIndustryResolver(client=client, cache_path=tmp_path / "c.json")
    ident = IdentityResolver(client=client, sector_resolver=sector)
    return FilingBusinessExtractor(
        client=client, cache_path=tmp_path / "f.json", identity_resolver=ident
    )


def test_latest_filing_picks_annual_form(tmp_path):
    ref = _extractor(tmp_path, _FakeClient(_routes())).latest_filing("AAPL")
    assert isinstance(ref, FilingRef)
    assert ref.form == "10-K"
    assert ref.accession == "0000320193-23-000106"
    assert ref.accession_nodash == "000032019323000106"
    assert "Archives/edgar/data/320193/000032019323000106/index.json" in ref.index_url


def test_get_segments_end_to_end(tmp_path):
    segs = _extractor(tmp_path, _FakeClient(_routes())).get_segments("AAPL")
    assert [s.label for s in segs] == ["Software And Services", "Hardware Products"]
    assert all(s.source == "sec-xbrl" for s in segs)
    assert segs[0].as_of == "2023-11-03"

    comp = to_revenue_composition(segs, source="sec-xbrl")
    assert comp.available and comp.source == "sec-xbrl"
    assert round(sum(s.pct for s in comp.segments), 4) == 1.0


def test_unresolved_is_empty_and_never_fabricated(tmp_path):
    # Every layer 404s → empty list, no invented segments.
    assert _extractor(tmp_path, _FakeClient({})).get_segments("ZZZZ") == []


def test_offline_makes_no_calls(tmp_path):
    client = _FakeClient(_routes())
    segs = FilingBusinessExtractor(client=client, cache_path=tmp_path / "f.json", offline=True).get_segments("AAPL")
    assert segs == []
    assert client.calls == []
