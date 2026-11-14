"""data/filing_evidence.py — SEC 10-K / 20-F business evidence extraction (M-38).

Why (M-38)
----------
``data/segment_revenue.py`` supplies dimension ③ (Revenue Composition) from FMP,
but that needs a paid key. SEC's ``companyfacts`` JSON was verified to hold only
**consolidated** facts (no ``Axis`` / ``srt:ProductOrServiceAxis`` dimensions —
see the note in ``segment_revenue``), so it cannot provide a segment mix. The one
authoritative, key-free source that *does* carry dimensional revenue is the
**filing-instance XBRL** embedded in each 10-K / 20-F.

This module fills that gap: it locates the latest 10-K / 20-F for a ticker,
downloads the filing's XBRL instance document, and parses out the per-segment
revenue facts. It is a **drop-in layer** alongside FMP: it returns the same
``data.segment_revenue.Segment`` rows, so
``data.segment_revenue.to_revenue_composition`` turns them into the taxonomy's
``RevenueComposition`` unchanged.

Resolution chain
----------------
  1. CIK           — reused from :class:`data.identity_resolver.IdentityResolver`.
  2. Latest filing — ``https://data.sec.gov/submissions/CIK{cik}.json``
                     (``filings.recent`` arrays; newest first).
  3. Instance URL  — the filing directory index JSON
                     (``/Archives/edgar/data/{cik}/{accession}/index.json``),
                     preferring the ``*_htm.xml`` XBRL instance.
  4. Parse         — :func:`parse_segment_revenue` (pure, offline-testable).

Discipline (same as every other source layer)
  * **Optional / graceful** — a missing CIK, filing, instance or parse yields an
    empty list; nothing is ever fabricated.
  * **Never sum the consolidated total into a segment** — only facts carrying a
    segment axis are kept.
  * **Offline-safe** — results are memoised and cached to disk, so the suite
    stays deterministic.
"""
from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import get_logger
from data.identity_resolver import IdentityResolver
from data.segment_revenue import Segment

log = get_logger("data.filing_evidence")

_DEFAULT_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "filing_evidence.json"
_SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
_SEC_FILING_INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
_SEC_ARCHIVE_FILE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{name}"

# SEC requires a descriptive User-Agent with contact info (fair-access policy).
_DEFAULT_UA = "ValuationEngine/1.0 (research; contact@example.com)"

# US annual report (10-K) and foreign private issuer annual report (20-F).
_FORMS = ("10-K", "20-F")

# Revenue concepts across us-gaap and ifrs-full (20-F uses the latter).
_REVENUE_LOCALS = frozenset(
    {
        # us-gaap
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
        # ifrs-full
        "Revenue",
        "RevenueFromContractsWithCustomers",
    }
)

# Axes that describe *where* revenue comes from, in preference order. Business
# segments are the truest "composition"; product/service and geography are
# coarse fallbacks; only ONE axis is ever used so mixes are never double-counted.
_AXIS_PRIORITY = (
    "StatementBusinessSegmentsAxis",
    "ProductOrServiceAxis",
    "SegmentsAxis",  # ifrs-full
    "StatementGeographicalAxis",
)
_SEGMENT_AXES = frozenset(_AXIS_PRIORITY)

# XBRL report helper files that are never the instance document.
_NON_INSTANCE_XML = re.compile(r"^(r\d+|filingsummary)\.xml$|_(cal|def|lab|pre|ref)\.xml$")


@dataclass(frozen=True)
class FilingRef:
    """A located SEC annual filing (identity + where its instance lives)."""

    cik: str
    form: str
    accession: str
    filing_date: Optional[str] = None
    primary_document: Optional[str] = None

    @property
    def accession_nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def index_url(self) -> str:
        return _SEC_FILING_INDEX.format(cik=_cik_int(self.cik), accession=self.accession_nodash)


class FilingBusinessExtractor:
    """Resolve segment revenue from the latest 10-K / 20-F XBRL instance."""

    _MEM: Dict[str, List[Dict[str, Any]]] = {}

    def __init__(
        self,
        client: Any = None,
        cache_path: Optional[Path] = None,
        *,
        offline: bool = False,
        identity_resolver: Optional[IdentityResolver] = None,
    ) -> None:
        self._client = client
        self._offline = offline
        self._cache_path = Path(cache_path) if cache_path else _DEFAULT_CACHE
        self._disk: Optional[Dict[str, List[Dict[str, Any]]]] = None
        self._identity = identity_resolver or IdentityResolver(client=client, offline=offline)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def latest_filing(self, ticker: str) -> Optional[FilingRef]:
        """Return the most recent 10-K / 20-F reference for ``ticker`` (or None)."""
        cik = self._cik_for(ticker)
        if not cik:
            return None
        r = self._get(_SEC_SUBMISSIONS.format(cik=cik))
        if r is None or r.status_code != 200:
            return None
        try:
            body = r.json() or {}
        except Exception:
            return None
        recent = ((body.get("filings") or {}).get("recent")) or {}
        forms = recent.get("form") or []
        accs = recent.get("accessionNumber") or []
        dates = recent.get("filingDate") or []
        docs = recent.get("primaryDocument") or []
        for i, form in enumerate(forms):  # newest first
            if form in _FORMS:
                return FilingRef(
                    cik=cik,
                    form=str(form),
                    accession=_at(accs, i) or "",
                    filing_date=_at(dates, i),
                    primary_document=_at(docs, i),
                )
        return None

    def get_segments(self, ticker: str) -> List[Segment]:
        """Return segment revenue from the latest annual filing (possibly empty)."""
        t = (ticker or "").upper().strip()
        if not t:
            return []
        if t in self._MEM:
            return _from_rows(self._MEM[t])
        disk = self._load_disk()
        if t in disk:
            self._MEM[t] = disk[t]
            return _from_rows(disk[t])

        rows: List[Dict[str, Any]] = []
        if not self._offline:
            try:
                rows = self._resolve(t)
            except Exception as e:  # network / parse errors are non-fatal
                log.debug(f"filing evidence extraction failed for {t}: {e}")
                rows = []

        self._MEM[t] = rows
        disk[t] = rows
        self._save_disk(disk)
        return _from_rows(rows)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _resolve(self, ticker: str) -> List[Dict[str, Any]]:
        ref = self.latest_filing(ticker)
        if ref is None:
            return []
        url = self._instance_url(ref)
        if not url:
            return []
        r = self._get(url, headers={"Accept": "application/xml"})
        if r is None or r.status_code != 200:
            return []
        text = getattr(r, "text", None)
        if not isinstance(text, str) or not text:
            return []
        parsed = parse_segment_revenue(text)
        if not parsed:
            return []
        return [{"label": label, "revenue": value, "as_of": ref.filing_date} for label, value in parsed]

    def _instance_url(self, ref: FilingRef) -> Optional[str]:
        r = self._get(ref.index_url)
        if r is None or r.status_code != 200:
            return None
        try:
            body = r.json() or {}
        except Exception:
            return None
        items = ((body.get("directory") or {}).get("item")) or []
        names = [str(it.get("name")) for it in items if isinstance(it, dict) and it.get("name")]
        name = _pick_instance(names)
        if not name:
            return None
        return _SEC_ARCHIVE_FILE.format(cik=_cik_int(ref.cik), accession=ref.accession_nodash, name=name)

    def _cik_for(self, ticker: str) -> Optional[str]:
        try:
            return self._identity.resolve(ticker).cik
        except Exception as e:
            log.debug(f"identity lookup failed for {ticker}: {e}")
            return None

    def _get(self, url: str, headers: Optional[Dict[str, str]] = None):
        client = self._client
        if client is None:
            import httpx

            client = httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
            self._client = client
        merged = {"User-Agent": _sec_ua()}
        if headers:
            merged.update(headers)
        return client.get(url, headers=merged)

    def _load_disk(self) -> Dict[str, List[Dict[str, Any]]]:
        if self._disk is not None:
            return self._disk
        disk: Dict[str, List[Dict[str, Any]]] = {}
        if self._cache_path.exists():
            try:
                loaded = json.loads(self._cache_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    disk = {
                        k: v
                        for k, v in loaded.items()
                        if isinstance(k, str) and isinstance(v, list)
                    }
            except Exception:
                disk = {}
        self._disk = disk
        return disk

    def _save_disk(self, data: Dict[str, List[Dict[str, Any]]]) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(data, indent=0, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as e:
            log.debug(f"filing evidence cache write failed: {e}")


# ---------------------------------------------------------------------------
# XBRL instance parsing (pure — no network, so it is unit-testable offline)
# ---------------------------------------------------------------------------
def parse_segment_revenue(xml_text: str) -> List[Tuple[str, float]]:
    """Parse per-segment revenue from an XBRL instance document.

    Only facts that carry a **segment axis** are kept (the consolidated total is
    never folded into a segment). All matching facts are grouped by member and
    the single latest period end is used, so prior-year comparatives do not
    double-count. Returns ``[(label, revenue)]`` sorted by revenue desc, or
    ``[]`` when nothing usable is present.
    """
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    contexts = _parse_contexts(root)
    facts: List[Tuple[str, str, str, str, float]] = []  # axis, member, end, concept, value
    for el in root.iter():
        concept = _local(el.tag)
        if concept not in _REVENUE_LOCALS:
            continue
        cref = el.get("contextRef")
        if not cref or el.text is None:
            continue
        ctx = contexts.get(cref)
        if not ctx:
            continue
        end, axis, member = ctx
        if not axis or not member or not end:
            continue
        value = _to_float(el.text)
        if value is None:
            continue
        facts.append((axis, member, end or "", concept, value))

    if not facts:
        return []
    for axis in _AXIS_PRIORITY:
        rows = _aggregate([f for f in facts if f[0] == axis])
        if rows:
            return rows
    return []


def _parse_contexts(root: ET.Element) -> Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]]:
    """Map ``context id -> (endDate, axis, member)`` for segment contexts."""
    out: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = {}
    for el in root.iter():
        if _local(el.tag) != "context":
            continue
        cid = el.get("id")
        if not cid:
            continue
        end: Optional[str] = None
        axis: Optional[str] = None
        member: Optional[str] = None
        for sub in el.iter():
            lname = _local(sub.tag)
            if lname == "endDate" and sub.text and end is None:
                end = sub.text.strip()
            elif lname == "explicitMember":
                dim = _local_attr(sub.get("dimension") or "")
                if dim in _SEGMENT_AXES and sub.text:
                    axis = dim
                    member = sub.text.strip().split(":", 1)[-1]
        out[cid] = (end, axis, member)
    return out


def _aggregate(facts: Sequence[Tuple[str, str, str, str, float]]) -> List[Tuple[str, float]]:
    """Sum one axis's latest-period facts per member (dedup by concept)."""
    target = max(f[2] for f in facts)
    by_member: Dict[str, Dict[str, float]] = {}
    for _, member, end, concept, value in facts:
        if end != target:
            continue
        by_member.setdefault(member, {})[concept] = value
    rows = [
        (_humanize(member), round(sum(concepts.values()), 2))
        for member, concepts in by_member.items()
    ]
    rows = [(label, value) for label, value in rows if value > 0]
    rows.sort(key=lambda kv: kv[1], reverse=True)
    return rows


def _humanize(member: str) -> str:
    """``SoftwareAndServicesMember`` -> ``Software And Services``."""
    name = re.sub(r"Member$", "", member) or member
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return name.strip() or member


def _pick_instance(names: Sequence[str]) -> Optional[str]:
    """Pick the XBRL instance from an EDGAR filing directory listing."""
    for n in names:
        if n.lower().endswith("_htm.xml"):
            return n
    for n in names:
        low = n.lower()
        if not low.endswith(".xml") or _NON_INSTANCE_XML.match(low):
            continue
        return n
    return None


def _from_rows(rows: List[Dict[str, Any]]) -> List[Segment]:
    out: List[Segment] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        label = row.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        revenue = _to_float(row.get("revenue"))
        if revenue is None or revenue <= 0:
            continue
        as_of = row.get("as_of")
        out.append(
            Segment(
                label=label.strip(),
                revenue=revenue,
                as_of=as_of if isinstance(as_of, str) else None,
                source="sec-xbrl",
            )
        )
    return out


# ---------------------------------------------------------------------------
# module helpers
# ---------------------------------------------------------------------------
def _local(tag: str) -> str:
    """Local name of an ElementTree namespaced tag (``{uri}local``)."""
    if not tag:
        return ""
    return tag.rsplit("}", 1)[-1]


def _local_attr(value: str) -> str:
    """Local name of a QName-as-string (``us-gaap:FooAxis`` -> ``FooAxis``)."""
    return value.split(":", 1)[-1]


def _at(seq: Sequence[Any], i: int) -> Optional[str]:
    if i < len(seq) and seq[i] is not None:
        return str(seq[i])
    return None


def _cik_int(cik: str) -> str:
    try:
        return str(int(cik))
    except (TypeError, ValueError):
        return str(cik)


def _sec_ua() -> str:
    return os.environ.get("SEC_USER_AGENT", _DEFAULT_UA)


def _to_float(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").strip())
        except ValueError:
            return None
    return None


def get_filing_segments(
    ticker: str, *, client: Any = None, offline: bool = False
) -> List[Segment]:
    """Convenience one-shot extraction (creates a throwaway extractor)."""
    return FilingBusinessExtractor(client=client, offline=offline).get_segments(ticker)


__all__ = [
    "FilingRef",
    "FilingBusinessExtractor",
    "parse_segment_revenue",
    "get_filing_segments",
]
