"""data/shadow_snapshot.py -- shadow snapshots with retrievable evidence.

Why this exists
---------------
The frozen ``.cache/yahoo_finance`` snapshots store *normalised statements only*.
The vendor's raw response was parsed and discarded, so no field in them can be
traced back to bytes anyone can re-check. That is why the frozen set is 91%
``UNKNOWN_LEGACY``: the label is honest, because the evidence is gone.

A shadow snapshot is the opposite: it keeps the **raw response body**, its
SHA-256, and the retrieval timestamp *next to* the parsed statement. Nothing is
written over an existing golden file, and nothing is ever labelled
``COMPANY_REPORTED`` merely because Yahoo returned it.

The two-part discipline
-----------------------
1. **Evidence first.** Every shadow directory holds ``raw/*.json`` (byte-exact
   responses) and ``manifest.json`` (digest per artefact). A provenance claim
   with no digest in the manifest is not made.
2. **Vendor is not the company.** Yahoo's ``reportedValue`` is a normalised,
   restated figure. It is recorded as ``VENDOR_REPORTED`` until an SEC XBRL fact
   with an accession number is matched to the same fiscal period, at which point
   (and only then) the field may be ``COMPANY_REPORTED``.

Layout
------
``data/shadow_snapshots/<SNAPSHOT_ID>/<TICKER>/``
    ``manifest.json``      -- ticker, vendor, retrieval time, artefact digests
    ``raw/chart.json``     -- byte-exact Yahoo chart response
    ``raw/timeseries.json``-- byte-exact fundamentals-timeseries response
    ``raw/quote_summary.json``
    ``statement.json``     -- normalised statements + per-field provenance
    ``sec_facts.json``     -- SEC XBRL facts used for corroboration (if any)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import get_logger

log = get_logger("data.shadow_snapshot")

SHADOW_ROOT = Path(__file__).resolve().parent.parent / "data" / "shadow_snapshots"

VENDOR_YAHOO = "yahoo_finance"
VENDOR_SEC = "sec_edgar"

_UA_BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
# SEC fair-access policy requires a descriptive agent with contact details.
_UA_SEC = "ValuationEngine/1.0 (research; contact@example.com)"

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
_TIMESERIES_URL = ("https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/"
                   "finance/timeseries/{ticker}")
_QUOTE_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
_SEC_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json"
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

#: Vendor timeseries names -> the statement field they populate. Used to carry
#: the vendor's own label through to the provenance record so a reader can see
#: which vendor line a number came from.
VENDOR_FIELD_MAP: Dict[str, str] = {
    "TotalRevenue": "revenue",
    "NetIncome": "net_income",
    "GrossProfit": "gross_profit",
    "EBIT": "ebit",
    "EBITDA": "ebitda",
    "FreeCashFlow": "free_cash_flow",
    "OperatingCashFlow": "operating_cash_flow",
    "CapitalExpenditure": "capex",
    "ChangeInWorkingCapital": "change_in_nwc",
    "InterestExpense": "interest_expense",
    "TaxProvision": "income_tax",
    "DepreciationAndAmortization": "depreciation_amortization",
    "TotalAssets": "total_assets",
    "TotalLiabilitiesNetMinorityInterest": "total_liabilities",
    "CashAndCashEquivalents": "cash",
    "TotalDebt": "total_debt",
    "StockholdersEquity": "stockholders_equity",
    "OrdinarySharesNumber": "shares_outstanding",
    "StockBasedCompensation": "stock_based_compensation",
}

#: Statement field -> SEC us-gaap concepts that can corroborate it, in
#: preference order. Only concepts whose *value semantics* equal the statement
#: field belong here; a near-synonym would manufacture false corroboration.
#:
#: ``ebit`` is deliberately absent. ``OperatingIncomeLoss`` is not EBIT: EBIT
#: also carries non-operating income, and matching the two produced a false
#: 8.9% "contradiction" on MSFT (155.2B vs 169.0B) — proof the mapping, not the
#: data, was wrong. EBIT has no single us-gaap concept, so it stays
#: VENDOR_REPORTED and says so.
SEC_CONCEPT_MAP: Dict[str, List[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating"],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
    ],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "stockholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "shares_outstanding": ["CommonStockSharesOutstanding"],
}

#: Concepts whose XBRL unit is ``shares``, not ``USD``. Reading them out of the
#: USD bucket silently returns nil, which looks like "no filing exists".
CONCEPT_UNITS: Dict[str, str] = {
    "CommonStockSharesOutstanding": "shares",
    "WeightedAverageNumberOfSharesOutstandingBasic": "shares",
    "EntityCommonStockSharesOutstanding": "shares",
}

#: Fields where the statement convention and the XBRL convention differ in sign.
#: ``PaymentsToAcquirePropertyPlantAndEquipment`` is a positive outflow in XBRL;
#: this pipeline stores capex as a negative number. A pure sign flip is not a
#: data discrepancy, so it must be normalised before comparing — otherwise every
#: capex field reports "contradicted" and the real contradictions get lost.
SIGN_FLIP = frozenset({"capex"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_date(s: Any):
    """Parse ``YYYY-MM-DD``; ``None`` when absent or malformed."""
    from datetime import date as _date
    if not s:
        return None
    try:
        y, m, d = str(s)[:10].split("-")
        return _date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def _date_ordinal(s: Any) -> int:
    d = _parse_date(s)
    return d.toordinal() if d else 0


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@dataclass
class RawArtifact:
    """One retrieved response, byte-exact and digests included."""

    name: str
    url: str
    http_status: int
    fetched_at: str
    sha256: str
    byte_length: int
    vendor: str
    #: Written to disk next to the manifest; not serialised into JSON twice.
    body: bytes = field(default=b"", repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "http_status": self.http_status,
            "fetched_at": self.fetched_at,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "vendor": self.vendor,
        }


def fetch_artifact(session: Any, name: str, url: str, *,
                   params: Optional[Dict[str, str]] = None,
                   vendor: str = VENDOR_YAHOO,
                   timeout: float = 40.0,
                   user_agent: str = _UA_BROWSER) -> Optional[RawArtifact]:
    """Retrieve one response and record its digest.

    Returns ``None`` on a transport failure rather than raising: a missing
    artefact must produce a *missing* field, never a fabricated one. The caller
    sees the absence and records it.
    """
    try:
        r = session.get(url, params=params, timeout=timeout,
                        headers={"User-Agent": user_agent}, follow_redirects=True)
    except Exception as e:  # transport, DNS, timeout -- all mean "no evidence"
        log.debug(f"artifact {name} fetch failed: {type(e).__name__}")
        return None
    body = r.content or b""
    return RawArtifact(
        name=name, url=str(r.url), http_status=int(r.status_code),
        fetched_at=_utc_now(), sha256=sha256_bytes(body),
        byte_length=len(body), vendor=vendor, body=body,
    )


def parse_timeseries_artifact(artifact: RawArtifact) -> Dict[str, List[Dict[str, Any]]]:
    """Extract ``{vendor_type: [{period_end, value}]}`` from a raw body.

    Kept separate from fetching so the parse is testable against a stored
    artefact without touching the network.
    """
    try:
        data = json.loads(artifact.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for entry in (data.get("timeseries", {}) or {}).get("result") or []:
        meta = entry.get("meta", {}) or {}
        for t in (meta.get("type") or []):
            values: List[Dict[str, Any]] = []
            for v in entry.get(t) or []:
                if not v:
                    continue
                rv = (v.get("reportedValue") or {}).get("raw")
                as_of = v.get("asOfDate")
                if rv is None or as_of is None:
                    continue
                try:
                    fv = float(rv)
                except (TypeError, ValueError):
                    continue
                values.append({
                    "period_end": str(as_of),
                    "value": fv,
                    "period_type": v.get("periodType"),
                    "currency": v.get("currencyCode"),
                    # The vendor's own dataId: the only vendor-side identifier
                    # available, and notably NOT a filing identifier.
                    "vendor_data_id": v.get("dataId"),
                })
            out[t] = values
    return out


@dataclass
class ShadowWriter:
    """Writes one ticker's shadow snapshot. Never reads or modifies a golden."""

    snapshot_id: str
    root: Path = SHADOW_ROOT

    def ticker_dir(self, ticker: str) -> Path:
        return self.root / self.snapshot_id / ticker

    def write(
        self,
        ticker: str,
        artifacts: List[RawArtifact],
        statement: Dict[str, Any],
        provenance: Dict[str, Dict[str, Any]],
        *,
        sec_facts: Optional[Dict[str, Any]] = None,
        notes: Optional[List[str]] = None,
        ttm: Optional[Dict[str, Any]] = None,
        ttm_provenance: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Path:
        d = self.ticker_dir(ticker)
        (d / "raw").mkdir(parents=True, exist_ok=True)

        for a in artifacts:
            if not a.body:
                continue
            # Stored byte-exact; the digest in the manifest is computed from
            # these same bytes, so a reader can re-hash and compare.
            (d / "raw" / f"{a.name}.json").write_bytes(a.body)

        all_arts = list(artifacts)
        if sec_facts is not None:
            sec_body = json.dumps(sec_facts, indent=2, sort_keys=True).encode()
            all_arts.append(RawArtifact(
                name="sec_facts", url="(derived from SEC companyconcept queries)",
                http_status=200, fetched_at=_utc_now(),
                sha256=sha256_bytes(sec_body), byte_length=len(sec_body),
                vendor=VENDOR_SEC, body=sec_body,
            ))
            (d / "raw" / "sec_facts.json").write_bytes(sec_body)

        (d / "statement.json").write_text(
            json.dumps(statement, indent=2, sort_keys=True, default=str))
        (d / "provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True, default=str))

        # The annual and TTM views are kept in separate files: they cover
        # different twelve months, and merging them would invite comparing one
        # against a golden built at the other cadence.
        if ttm is not None:
            (d / "ttm_statement.json").write_text(
                json.dumps(ttm, indent=2, sort_keys=True, default=str))
        if ttm_provenance is not None:
            (d / "ttm_provenance.json").write_text(
                json.dumps(ttm_provenance, indent=2, sort_keys=True, default=str))

        manifest = {
            "snapshot_id": self.snapshot_id,
            "ticker": ticker,
            "written_at": _utc_now(),
            "vendors": sorted({a.vendor for a in all_arts}),
            "artifacts": [a.to_dict() for a in all_arts],
            "has_company_filing_evidence": bool(
                (sec_facts or {}).get("matched_fields")),
            "annual_period_end": statement.get("period_end"),
            "ttm_period_end": (ttm or {}).get("period_end"),
            "notes": list(notes or []),
        }
        (d / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True))
        return d


def verify_shadow(snapshot_id: str, ticker: str,
                  root: Path = SHADOW_ROOT) -> Dict[str, Any]:
    """Re-hash every stored artefact and compare to the manifest.

    This is the reproducibility check: if a byte changed, the digest will not
    match and the evidence chain is broken. Silent edits become visible.
    """
    d = root / snapshot_id / ticker
    manifest_path = d / "manifest.json"
    if not manifest_path.exists():
        return {"ticker": ticker, "present": False, "mismatches": []}
    manifest = json.loads(manifest_path.read_text())
    mismatches: List[Dict[str, str]] = []
    checked = 0
    for entry in manifest.get("artifacts", []):
        p = d / "raw" / f"{entry['name']}.json"
        if not p.exists():
            mismatches.append({"name": entry["name"], "reason": "file missing"})
            continue
        actual = sha256_bytes(p.read_bytes())
        checked += 1
        if actual != entry["sha256"]:
            mismatches.append({
                "name": entry["name"], "reason": "digest changed",
                "expected": entry["sha256"], "actual": actual,
            })
    return {
        "ticker": ticker, "present": True, "artifacts_checked": checked,
        "mismatches": mismatches, "ok": not mismatches,
        "has_company_filing_evidence": bool(
            manifest.get("has_company_filing_evidence")),
    }


def list_shadows(snapshot_id: str, root: Path = SHADOW_ROOT) -> List[str]:
    base = root / snapshot_id
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def load_sec_ticker_map(session: Any) -> Dict[str, str]:
    """ticker -> zero-padded 10-digit CIK, from SEC's public mapping."""
    art = fetch_artifact(session, "sec_tickers", _SEC_TICKERS_URL,
                         vendor=VENDOR_SEC, user_agent=_UA_SEC, timeout=30.0)
    if art is None or art.http_status != 200:
        return {}
    try:
        raw = json.loads(art.body)
    except json.JSONDecodeError:
        return {}
    out: Dict[str, str] = {}
    for row in (raw or {}).values():
        t = (row.get("ticker") or "").upper()
        c = row.get("cik_str")
        if t and c is not None:
            out[t] = f"{int(c):010d}"
    return out


def fetch_company_concept(session: Any, cik: str, tag: str) -> Optional[RawArtifact]:
    """One us-gaap concept's facts for a company (all periods, all forms)."""
    return fetch_artifact(
        session, f"sec_{tag}", _SEC_CONCEPT_URL.format(cik=cik, tag=tag),
        vendor=VENDOR_SEC, user_agent=_UA_SEC, timeout=30.0,
    )


def annual_facts_from_concept(
    artifact: RawArtifact, period_end: str, *, unit: str = "USD",
    max_days_apart: int = 10,
) -> Optional[Dict[str, Any]]:
    """Find the annual fact whose period end matches ``period_end``.

    A 10-K fact is preferred over a 10-Q because only the annual filing carries
    the full-year figure with a comparable basis. Returns the fact verbatim, so
    ``accn`` / ``filed`` / ``form`` travel with the number -- that trio is what
    makes an origin claim checkable.

    ``unit`` must match the concept: shares live in the ``shares`` bucket, and
    looking for them under ``USD`` returns nothing while looking exactly like a
    company that never filed a share count.

    ``max_days_apart`` exists because vendors and filers disagree about period
    *labels*, not only about numbers. AMD's fiscal year ends on the last Saturday
    of December: SEC reports ``2025-12-27`` while Yahoo labels the same year
    ``2025-12-31``. Requiring an exact string match reported 13 of 13 AMD fields
    as "no filing exists" — a false negative that looks exactly like missing
    data. A 52/53-week year can end up to 6 days from the calendar boundary; 10
    days leaves margin without giving a different fiscal year room to match.
    """
    try:
        data = json.loads(artifact.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    facts = (data.get("units", {}) or {}).get(unit) or []

    target = _parse_date(period_end)
    candidates = []
    for f in facts:
        if f.get("val") is None:
            continue
        if f.get("form") not in ("10-K", "20-F", "10-K/A", "20-F/A"):
            continue
        end = _parse_date(f.get("end"))
        if end is None:
            continue
        gap = abs((end - target).days) if target else None
        if gap is not None and gap <= max_days_apart:
            candidates.append((gap, f))
    if not candidates:
        return None
    # Nearest period end first (so a 52/53-week year lands on its own fact, not
    # a neighbour); then newest filing, because a restatement supersedes the
    # original.
    candidates.sort(key=lambda pair: (pair[0],
                                      -_date_ordinal(pair[1].get("filed"))))
    best = candidates[0][1]
    out = dict(best)
    out["_period_gap_days"] = candidates[0][0]
    return out


def corroborate(
    field_name: str,
    vendor_value: Optional[float],
    period_end: str,
    cik: Optional[str],
    session: Any,
    *,
    tolerance: float = 0.005,
) -> Dict[str, Any]:
    """Try to match a vendor value to an SEC fact for the same fiscal period.

    Returns a record with ``status`` in:

    * ``matched``        -- an SEC fact agrees within ``tolerance``
    * ``contradicted``   -- an SEC fact exists but disagrees
    * ``no_sec_fact``    -- no concept/period matched, so nothing is claimed
    * ``no_cik``         -- the company could not be mapped to a filer

    Only ``matched`` permits ``COMPANY_REPORTED``. ``contradicted`` is the most
    valuable outcome: it proves the vendor number is *not* what the company
    filed, and it must never be silently rounded into agreement.
    """
    rec: Dict[str, Any] = {
        "field": field_name, "period_end": period_end,
        "vendor_value": vendor_value, "status": "no_sec_fact",
    }
    if vendor_value is None:
        rec["status"] = "missing_vendor_value"
        return rec
    if not cik:
        rec["status"] = "no_cik"
        return rec
    concepts = SEC_CONCEPT_MAP.get(field_name) or []
    for tag in concepts:
        art = fetch_company_concept(session, cik, tag)
        if art is None or art.http_status != 200:
            continue
        unit = CONCEPT_UNITS.get(tag, "USD")
        fact = annual_facts_from_concept(art, period_end, unit=unit)
        if fact is None:
            continue
        sec_val = float(fact["val"]) if fact.get("val") is not None else None
        if sec_val is None:
            continue
        if field_name in SIGN_FLIP:
            # XBRL records the outflow as positive; the statement stores it
            # negative. Flip before measuring, or every capex looks wrong.
            sec_val = -abs(sec_val) if vendor_value < 0 else abs(sec_val)
        rec.update({
            "sec_concept": tag,
            "sec_unit": unit,
            "sec_value": sec_val,
            "sec_value_as_filed": fact.get("val"),
            "sign_normalised": field_name in SIGN_FLIP,
            "sec_period_end": fact.get("end"),
            # Recorded, not hidden: a fiscal-period label gap is exactly the kind
            # of detail an auditor needs to see when two sources "agree".
            "period_label_gap_days": fact.get("_period_gap_days"),
            "sec_accession": fact.get("accn"),
            "sec_filed": fact.get("filed"),
            "sec_form": fact.get("form"),
            "sec_fy": fact.get("fy"),
            "sec_fp": fact.get("fp"),
            "raw_sha256": art.sha256,
            "vendor_artifact_url": art.url,
        })
        rec["absolute_delta"] = sec_val - float(vendor_value)
        denom = abs(sec_val) or 1.0
        rec["relative_delta"] = abs(sec_val - float(vendor_value)) / denom
        rec["status"] = ("matched" if rec["relative_delta"] <= tolerance
                         else "contradicted")
        return rec
    return rec


#: Fields that are *stocks* (a point-in-time balance), not *flows* (a period
#: total). A TTM figure for a stock is the latest quarter's balance, never the
#: sum of four quarters.
#:
#: Summing these produced obviously absurd numbers — MSFT share count came out
#: at 29.7B (four quarters of ~7.4B added together) and equity at 1.7 trillion.
#: The check that caught it is simple: a balance-sheet line cannot grow 4x by
#: being measured over a year. Any field not proven to be a flow is treated as a
#: stock, so a new field fails safe.
STOCK_FIELDS: frozenset = frozenset({
    "cash", "total_debt", "stockholders_equity", "shares_outstanding",
    "total_assets", "total_liabilities",
})

#: Vendor timeseries name -> statement field. :data:`VENDOR_FIELD_MAP` is already
#: keyed by vendor name, so this is a copy, not an inversion. (An earlier version
#: unpacked ``items()`` the wrong way round and produced a field->vendor map,
#: which made every lookup miss.)
_VENDOR_TO_FIELD: Dict[str, str] = dict(VENDOR_FIELD_MAP)


def _is_stock_field(vendor_base: str) -> bool:
    """True for balance-sheet items. Fails safe *only* for unknown names.

    A known vendor line is classified solely by :data:`STOCK_FIELDS`. The
    substring heuristic runs only for names absent from the map, because it is
    otherwise wrong in exactly the case that matters: ``FreeCashFlow`` contains
    "cash" and was summed as if it were a balance, turning MSFT's TTM FCF
    (59.96B) into a single quarter (18.63B).
    """
    if vendor_base in _VENDOR_TO_FIELD:
        return _VENDOR_TO_FIELD[vendor_base] in STOCK_FIELDS
    lowered = vendor_base.lower()
    return any(w in lowered for w in (
        "assets", "liabilities", "equity", "cash", "debt", "shares",
    ))


def build_ttm_from_quarters(
    ts: Dict[str, List[Dict[str, Any]]], period_end: str,
) -> Dict[str, Dict[str, Any]]:
    """Build a twelve-month view ending at ``period_end``.

    Why this exists: the frozen golden is a **TTM** statement, so comparing it to
    a shadow that holds an *annual* figure reports a period change as a data
    change. MSFT's annual FY2026-06-30 revenue (331.8B) versus its TTM
    2026-09-30 revenue (346.4B) differ by 4.2% purely because they cover
    different twelve months. Presenting that as "revenue fell 4.2%" would be a
    fabricated conclusion, so the shadow is built at the same cadence as the
    thing it is compared against.

    Flow fields are summed over four quarters; stock fields take the latest
    quarter unchanged (see :data:`STOCK_FIELDS`). Mixing the two rules is how a
    share count silently quadruples.

    A quarter that is missing makes a flow sum *understated* rather than absent,
    so such a field is returned with ``complete=False`` and must be reported as
    partial — never as a real figure.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for vendor_type, rows in ts.items():
        if not vendor_type.startswith("quarterly"):
            continue
        base = vendor_type[len("quarterly"):]
        if not rows:
            continue
        ordered = sorted(rows, key=lambda r: r["period_end"])
        upto = [r for r in ordered if r["period_end"] <= period_end]
        if not upto:
            continue
        window = upto[-4:]
        present = [r for r in window if r.get("value") is not None]
        if _is_stock_field(base):
            latest_present = [r for r in upto if r.get("value") is not None]
            if not latest_present:
                continue
            value = latest_present[-1]["value"]
            complete = True
            method = "LATEST_QUARTER_BALANCE"
        else:
            value = sum(r["value"] for r in present)
            complete = len(window) == 4 and len(present) == 4
            method = "SUM_4Q"
        out[base] = {
            "value": value,
            "complete": complete,
            "basis": method,
            "quarters": [r["period_end"] for r in window],
            "missing_quarters": [r["period_end"] for r in window
                                 if r.get("value") is None],
            "period_end": window[-1]["period_end"],
        }
    return out


def sleep_for_sec_rate_limit(seconds: float = 0.15) -> None:
    """SEC allows 10 req/s; a small delay keeps us well inside it."""
    time.sleep(seconds)
