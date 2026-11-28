"""benchmark/build_shadow_snapshot.py -- build shadow snapshots for tickers.

Usage:
    python -m benchmark.build_shadow_snapshot MSFT JPM BAC AMD
    python -m benchmark.build_shadow_snapshot --all

What it does
------------
For each ticker it retrieves the vendor responses *now*, keeps them byte-exact,
and writes them plus a per-field provenance record into
``data/shadow_snapshots/<SNAPSHOT_ID>/<TICKER>/``.

What it deliberately does not do
--------------------------------
* It never writes to ``.cache/yahoo_finance`` or any golden file.
* It never reuses a historical snapshot id for freshly fetched data. The id is
  derived from the retrieval date unless one is passed explicitly, so a shadow
  built today cannot masquerade as the frozen 20261123 set.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from config import get_logger
from data.provenance import (
    DataAvailability,
    DataOriginType,
    FieldProvenance,
    compute_input_hash,
)
from data.shadow_snapshot import (
    SEC_CONCEPT_MAP,
    VENDOR_FIELD_MAP,
    VENDOR_SEC,
    VENDOR_YAHOO,
    ShadowWriter,
    annual_facts_from_concept,
    build_ttm_from_quarters,
    corroborate,
    fetch_artifact,
    fetch_company_concept,
    load_sec_ticker_map,
    parse_timeseries_artifact,
    sleep_for_sec_rate_limit,
    verify_shadow,
    _CHART_URL,
    _QUOTE_SUMMARY_URL,
    _TIMESERIES_URL,
)

log = get_logger("benchmark.build_shadow_snapshot")

_ANNUAL_TYPES = list(VENDOR_FIELD_MAP.keys())


def _timeseries_types() -> str:
    out = []
    for p in ("annual", "quarterly"):
        for t in _ANNUAL_TYPES:
            out.append(f"{p}{t}")
    return ",".join(out)


def _vendor_provenance(
    value: Optional[float], vendor_type: str, period_end: str,
    artifact_sha: str,
) -> Dict[str, Any]:
    """A vendor-reported record. Never COMPANY_REPORTED on its own."""
    if value is None:
        return FieldProvenance(
            availability=DataAvailability.MISSING,
            origin_type=None,
        ).__dict__ | {"field_name": vendor_type}
    return FieldProvenance(
        availability=DataAvailability.AVAILABLE,
        origin_type=DataOriginType.VENDOR_REPORTED,
        source_provider=VENDOR_YAHOO,
        source_field=vendor_type,
        source_fields=[vendor_type],
        # The vendor's normalised line, not a filing line. Recorded as such.
        derivation_method="VENDOR_NORMALISED",
        input_fields=[vendor_type],
        input_hash=compute_input_hash({"vendor_type": vendor_type,
                                       "raw_sha256": artifact_sha}),
        output_value=float(value),
    ).__dict__ | {"field_name": vendor_type}


def _promote_with_evidence(
    base: Dict[str, Any], match: Dict[str, Any],
) -> Dict[str, Any]:
    """Reward a verified match with COMPANY_REPORTED, carrying the filing refs."""
    rec = dict(base)
    rec["origin_type"] = DataOriginType.COMPANY_REPORTED
    rec["source_provider"] = f"{VENDOR_YAHOO}+{VENDOR_SEC}"
    rec["source_field"] = match.get("sec_concept")
    rec["source_fields"] = [match.get("sec_concept")]
    rec["derivation_method"] = "SEC_XBRL_MATCH"
    # The hash now covers both sides of the match: the vendor number and the
    # filing fact it was checked against. Recomputing it from the vendor line
    # alone would let the corroboration change without the hash moving.
    rec["input_hash"] = compute_input_hash({
        "sec_concept": match.get("sec_concept"),
        "sec_value": match.get("sec_value"),
        "vendor_value": match.get("vendor_value"),
        "sec_accession": match.get("sec_accession"),
    })
    rec["sec_accession"] = match.get("sec_accession")
    rec["sec_filed"] = match.get("sec_filed")
    rec["sec_form"] = match.get("sec_form")
    rec["sec_relative_delta"] = match.get("relative_delta")
    rec["evidence_raw_sha256"] = match.get("raw_sha256")
    return rec


def build_one(
    ticker: str,
    snapshot_id: str,
    session: httpx.Client,
    sec_map: Dict[str, str],
    *,
    with_sec: bool = True,
) -> Dict[str, Any]:
    """Build (or rebuild) one ticker's shadow snapshot."""
    art_chart = fetch_artifact(
        session, "chart", _CHART_URL.format(ticker=ticker),
        params={"range": "10y", "interval": "1mo",
                "includePrePost": "false", "events": "div,splits"},
    )
    art_ts = fetch_artifact(
        session, "timeseries", _TIMESERIES_URL.format(ticker=ticker),
        params={
            "period1": str(int(datetime.now(timezone.utc).timestamp()) - 10 * 366 * 86400),
            "period2": str(int(datetime.now(timezone.utc).timestamp()) + 24 * 3600),
            "type": _timeseries_types(),
        },
    )
    art_qs = fetch_artifact(
        session, "quote_summary", _QUOTE_SUMMARY_URL.format(ticker=ticker),
        params={"modules": "assetProfile,summaryDetail,defaultKeyStatistics,price"},
    )

    artifacts = [a for a in (art_chart, art_ts, art_qs) if a is not None]
    if art_ts is None:
        return {"ticker": ticker, "ok": False, "reason": "no timeseries response"}

    ts = parse_timeseries_artifact(art_ts)
    cik = sec_map.get(ticker.upper())

    # Audit the *latest annual period* the vendor returned: that is the period a
    # valuation would actually consume.
    annual: Dict[str, Dict[str, Any]] = {}
    for vendor_type, values in ts.items():
        if not vendor_type.startswith("annual"):
            continue
        base = vendor_type[len("annual"):]
        if not values:
            continue
        latest = sorted(values, key=lambda v: v["period_end"])[-1]
        annual[base] = latest

    if not annual:
        return {"ticker": ticker, "ok": False, "reason": "no annual vendor rows"}

    period_ends = sorted({v["period_end"] for v in annual.values()})
    period_end = period_ends[-1]

    provenance: Dict[str, Dict[str, Any]] = {}
    statement: Dict[str, Any] = {"period_end": period_end, "fields": {}}
    corroborations: Dict[str, Any] = {}
    matched_fields: List[str] = []

    for vendor_type, latest in annual.items():
        field_name = VENDOR_FIELD_MAP.get(vendor_type, vendor_type)
        value = latest.get("value")
        statement["fields"][field_name] = value
        rec = _vendor_provenance(value, vendor_type, latest["period_end"],
                                 art_ts.sha256)

        if with_sec and value is not None and cik and field_name in SEC_CONCEPT_MAP:
            m = corroborate(field_name, value, latest["period_end"], cik, session)
            corroborations[field_name] = m
            sleep_for_sec_rate_limit()
            if m.get("status") == "matched":
                rec = _promote_with_evidence(rec, m)
                matched_fields.append(field_name)

        rec["period_end"] = latest["period_end"]
        rec["vendor_data_id"] = latest.get("vendor_data_id")
        rec["vendor_period_type"] = latest.get("period_type")
        rec["vendor_currency"] = latest.get("currency")
        provenance[field_name] = rec

    # --- TTM view, at the cadence the frozen golden uses -------------------
    ttm_period = max(
        (r["period_end"] for v in ts.values() if v for r in v),
        default=period_end,
    )
    ttm_raw = build_ttm_from_quarters(ts, ttm_period)
    ttm_fields: Dict[str, Any] = {}
    ttm_provenance: Dict[str, Dict[str, Any]] = {}
    for vendor_type, agg in ttm_raw.items():
        field_name = VENDOR_FIELD_MAP.get(vendor_type, vendor_type)
        ttm_fields[field_name] = agg["value"]
        rec = _vendor_provenance(agg["value"], f"quarterly{vendor_type}",
                                 agg["period_end"], art_ts.sha256)
        # A TTM sum is a derivation over four vendor rows, never a filing line.
        # It therefore stays VENDOR_REPORTED/DERIVED territory: no company files
        # a twelve-month total for a non-calendar window, so no SEC fact can
        # corroborate it and none is claimed.
        rec["derivation_method"] = f"TTM_4Q_VENDOR_{agg['basis']}"
        rec["input_fields"] = agg["quarters"]
        rec["input_hash"] = compute_input_hash({
            "quarters": agg["quarters"],
            "values": [agg["value"]],
            "raw_sha256": art_ts.sha256,
        })
        rec["ttm_complete"] = agg["complete"]
        rec["ttm_basis"] = agg["basis"]
        rec["ttm_missing_quarters"] = agg["missing_quarters"]
        rec["period_end"] = agg["period_end"]
        if not agg["complete"]:
            rec["origin_type"] = DataOriginType.IMPUTED
            rec["availability"] = DataAvailability.AVAILABLE
        ttm_provenance[field_name] = rec

    writer = ShadowWriter(snapshot_id=snapshot_id)
    notes = []
    if not cik:
        notes.append("no SEC CIK resolved; nothing claims COMPANY_REPORTED")

    out_dir = writer.write(
        ticker, artifacts, statement, provenance,
        sec_facts={"corroborations": corroborations,
                   "matched_fields": matched_fields,
                   "cik": cik,
                   "ttm_period_end": ttm_period,
                   "ttm_fields": ttm_fields,
                   "ttm_incomplete": [k for k, v in ttm_raw.items()
                                      if not v["complete"]]},
        notes=notes,
        ttm={"period_end": ttm_period, "fields": ttm_fields},
        ttm_provenance=ttm_provenance,
    )
    check = verify_shadow(snapshot_id, ticker)
    return {
        "ticker": ticker, "ok": bool(check.get("ok")),
        "dir": str(out_dir), "period_end": period_end,
        "ttm_period_end": ttm_period,
        "n_fields": len(provenance),
        "n_ttm_fields": len(ttm_provenance),
        "matched_company_reported": matched_fields,
        "verify": check,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build shadow snapshots.")
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--snapshot-id", default=None)
    ap.add_argument("--no-sec", action="store_true",
                    help="skip SEC corroboration (vendor-only shadow)")
    args = ap.parse_args(argv)

    if args.all:
        from benchmark.registry import tickers as all_tickers
        targets = list(all_tickers())
    elif args.tickers:
        targets = [t.upper() for t in args.tickers]
    else:
        ap.error("give tickers or --all")

    # Never let freshly fetched data wear a historical id by default.
    sid = args.snapshot_id or datetime.now(timezone.utc).strftime("shadow-%Y%m%d")

    results = []
    with httpx.Client(follow_redirects=True) as session:
        sec_map = {} if args.no_sec else load_sec_ticker_map(session)
        for t in targets:
            try:
                r = build_one(t, sid, session, sec_map, with_sec=not args.no_sec)
            except Exception as e:
                r = {"ticker": t, "ok": False, "reason": f"{type(e).__name__}: {e}"}
            results.append(r)
            status = "OK " if r.get("ok") else "FAIL"
            n = len(r.get("matched_company_reported") or [])
            print(f"[{status}] {t:6s} fields={r.get('n_fields','-'):>3} "
                  f"company_reported={n} {r.get('reason','')}")

    ok = sum(1 for r in results if r.get("ok"))
    print(f"\n{ok}/{len(results)} shadow snapshots written under "
          f"data/shadow_snapshots/{sid}/")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
