"""data/share_count_engine.py — Share Count Reconciliation Engine (P0 Refactor).

Provides:
  - :class:`ShareFact` — a single XBRL share-count fact with full provenance.
  - :class:`ShareCountData` — the aggregated share-count model for one company.
  - :class:`ShareCountReconciliation` — comparison result with explicit status.
  - :class:`ShareCountEngine` — fetches from EdgarTools → SEC API → Filing XBRL,
    then reconciles Market Implied vs Filing-derived share counts.

Design principles (from the P0 spec):
  * Every share number must trace to a source — never fabricate.
  * Market Cap = Price × Implied Shares only proves *internal* consistency;
    it does NOT prove the count matches the filing's share caliber.
  * Different valuations need different calibers (P/E → diluted weighted avg,
    P/B → period-end common shares, etc.). Mixing them silently is forbidden.
  * Missing data returns N/A or WARNING, never a silent fill.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import get_logger

log = get_logger("data.share_count_engine")

# SEC requires a descriptive User-Agent.
_DEFAULT_UA = "ValuationEngine/1.0 (research; contact@example.com)"
_SEC_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_int}.json"
_SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik_int}.json"

# XBRL share-count concepts to probe (ordered by priority).
_SHARE_CONCEPTS: List[str] = [
    # Period-end shares (instant)
    "dei:EntityCommonStockSharesOutstanding",
    "us-gaap:CommonStockSharesOutstanding",
    "us-gaap:CommonStockSharesIssued",
    # Weighted average shares (duration)
    "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
    "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
    "us-gaap:WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
    # Treasury / Preferred
    "us-gaap:TreasuryStockShares",
    "us-gaap:PreferredStockSharesOutstanding",
]

# Map concept → caliber classification
_CONCEPT_CALIBER: Dict[str, str] = {
    "dei:EntityCommonStockSharesOutstanding": "period_end_dei",
    "us-gaap:CommonStockSharesOutstanding": "period_end_common",
    "us-gaap:CommonStockSharesIssued": "period_end_issued",
    "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic": "weighted_avg_basic",
    "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding": "weighted_avg_diluted",
    "us-gaap:WeightedAverageNumberOfShareOutstandingBasicAndDiluted": "weighted_avg_basic_diluted",
    "us-gaap:TreasuryStockShares": "treasury",
    "us-gaap:PreferredStockSharesOutstanding": "preferred",
}


class ReconciliationStatus(str, Enum):
    """Outcome of comparing two share counts."""
    MATCHED = "matched"                         # < 2% difference, same caliber
    ACCEPTABLE_DIFFERENCE = "acceptable_difference"  # 2-5%, same caliber
    RECONCILIATION_REQUIRED = "reconciliation_required"  # > 5%, same caliber
    DATA_MISSING = "data_missing"               # one or both sources absent
    PERIOD_MISMATCH = "period_mismatch"         # different period-end dates
    CLASS_MISMATCH = "class_mismatch"           # different share classes / calibers
    SOURCE_CONFLICT = "source_conflict"         # same caliber, different sources disagree


@dataclass(frozen=True)
class ShareFact:
    """A single XBRL share-count fact with full provenance.

    Every share number that enters the valuation engine must be representable
    as one of these — so the audit trail is uniform regardless of source.
    """
    value: float
    unit: str                          # "shares", "shares_millions", etc.
    concept: str                       # XBRL concept name (e.g. "dei:EntityCommonStockSharesOutstanding")
    caliber: str                       # classified caliber (see _CONCEPT_CALIBER)
    period_end: Optional[str] = None   # ISO date
    period_start: Optional[str] = None # ISO date (None for instant concepts)
    period_type: str = ""              # "instant" or "duration"
    filing_date: Optional[str] = None
    form_type: str = ""                # 10-K, 10-Q, 20-F, etc.
    accession_number: str = ""
    source: str = ""                   # "edgartools", "sec_api", "filing_xbrl"
    dimensions: str = ""               # XBRL dimensions (for Class A/B etc.)

    @property
    def is_instant(self) -> bool:
        return self.period_type == "instant"

    @property
    def is_annual(self) -> bool:
        return self.form_type in ("10-K", "20-F")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "concept": self.concept,
            "caliber": self.caliber,
            "period_end": self.period_end,
            "period_start": self.period_start,
            "period_type": self.period_type,
            "filing_date": self.filing_date,
            "form_type": self.form_type,
            "accession_number": self.accession_number,
            "source": self.source,
            "dimensions": self.dimensions,
        }


@dataclass
class ShareCountData:
    """Aggregated share-count model for one company at one point in time.

    Each field is a :class:`ShareFact` (or None) so the consumer always knows
    the source, period, and caliber — never just a bare number.
    """
    # Period-end shares
    period_end_dei: Optional[ShareFact] = None          # dei:EntityCommonStockSharesOutstanding (cover page)
    period_end_common: Optional[ShareFact] = None       # us-gaap:CommonStockSharesOutstanding (balance sheet)
    period_end_issued: Optional[ShareFact] = None       # us-gaap:CommonStockSharesIssued
    treasury_shares: Optional[ShareFact] = None
    preferred_shares: Optional[ShareFact] = None

    # Weighted average shares
    weighted_avg_basic: Optional[ShareFact] = None
    weighted_avg_diluted: Optional[ShareFact] = None

    # Class-level (if dimensioned)
    class_a_shares: Optional[ShareFact] = None
    class_b_shares: Optional[ShareFact] = None

    # Dilution evidence (Phase 1.4) — raw evidence, NOT a fully-diluted calculation
    dilution_evidence: Optional[Any] = None  # DilutionEvidenceReport

    # Metadata
    ticker: str = ""
    cik: str = ""
    latest_filing_date: Optional[str] = None
    latest_form_type: str = ""
    latest_accession: str = ""
    all_facts: List[ShareFact] = field(default_factory=list)

    def latest_period_end_shares(self) -> Optional[ShareFact]:
        """Best available period-end common share count."""
        for f in (self.period_end_dei, self.period_end_common, self.period_end_issued):
            if f is not None and f.value > 0:
                return f
        return None

    def latest_diluted_weighted_avg(self) -> Optional[ShareFact]:
        """Diluted weighted average shares (for P/E, EPS)."""
        return self.weighted_avg_diluted

    def latest_basic_weighted_avg(self) -> Optional[ShareFact]:
        """Basic weighted average shares (for Basic EPS)."""
        return self.weighted_avg_basic

    def as_dict(self) -> Dict[str, Any]:
        def _v(f: Optional[ShareFact]) -> Optional[Dict[str, Any]]:
            return f.as_dict() if f else None
        return {
            "ticker": self.ticker,
            "cik": self.cik,
            "period_end_dei": _v(self.period_end_dei),
            "period_end_common": _v(self.period_end_common),
            "period_end_issued": _v(self.period_end_issued),
            "treasury_shares": _v(self.treasury_shares),
            "preferred_shares": _v(self.preferred_shares),
            "weighted_avg_basic": _v(self.weighted_avg_basic),
            "weighted_avg_diluted": _v(self.weighted_avg_diluted),
            "class_a_shares": _v(self.class_a_shares),
            "class_b_shares": _v(self.class_b_shares),
            "dilution_evidence": (
                self.dilution_evidence.as_dict()
                if self.dilution_evidence and hasattr(self.dilution_evidence, "as_dict")
                else None
            ),
            "latest_filing_date": self.latest_filing_date,
            "latest_form_type": self.latest_form_type,
            "latest_accession": self.latest_accession,
            "all_facts_count": len(self.all_facts),
        }


@dataclass
class ShareCountReconciliation:
    """Result of comparing two share counts (e.g. Market Implied vs Filing)."""
    status: ReconciliationStatus
    source_a_label: str        # e.g. "Market Implied (Price × Shares)"
    source_b_label: str        # e.g. "SEC Filing (dei:EntityCommonStockSharesOutstanding)"
    value_a: Optional[float] = None
    value_b: Optional[float] = None
    caliber_a: str = ""
    caliber_b: str = ""
    period_a: Optional[str] = None
    period_b: Optional[str] = None
    difference_pct: Optional[float] = None
    reason: str = ""
    usable_for_valuation: bool = False
    needs_manual_review: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "source_a": self.source_a_label,
            "source_b": self.source_b_label,
            "value_a": self.value_a,
            "value_b": self.value_b,
            "caliber_a": self.caliber_a,
            "caliber_b": self.caliber_b,
            "period_a": self.period_a,
            "period_b": self.period_b,
            "difference_pct": self.difference_pct,
            "reason": self.reason,
            "usable_for_valuation": self.usable_for_valuation,
            "needs_manual_review": self.needs_manual_review,
        }


def _sec_ua() -> str:
    return os.environ.get("SEC_USER_AGENT", _DEFAULT_UA)


def _edgar_identity() -> str:
    return os.environ.get("EDGAR_IDENTITY", "ValuationEngine research@example.com")


class ShareCountEngine:
    """Fetches share-count data from EdgarTools → SEC API → Filing XBRL,
    then reconciles against Market Implied shares.

    Usage:
        engine = ShareCountEngine()
        data = engine.fetch("SOFI")
        recon = engine.reconcile_vs_market(data, market_implied=933.9e6, price=...)
    """

    _MEM: Dict[str, ShareCountData] = {}
    _LOCK = threading.Lock()
    _DEFAULT_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "share_count_engine.json"

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        self._cache_path = Path(cache_path) if cache_path else self._DEFAULT_CACHE
        self._disk: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch(self, ticker: str) -> ShareCountData:
        """Fetch share-count data for ``ticker`` via EdgarTools (with SEC API fallback).

        Returns a :class:`ShareCountData` with all available facts. Missing
        concepts stay ``None`` — never fabricated.
        """
        t = (ticker or "").upper().strip()
        if not t:
            return ShareCountData()

        with self._LOCK:
            if t in self._MEM:
                return self._MEM[t]
            disk = self._load_disk()
            if t in disk:
                data = _dict_to_share_count_data(disk[t], t)
                self._MEM[t] = data
                return data

        data = self._fetch_edgartools(t)
        if data is None or not data.all_facts:
            # Fallback to SEC Company Facts API
            data = self._fetch_sec_api(t) or ShareCountData(ticker=t)

        # Phase 1.1/1.2 — Always try the original Filing XBRL extractor.
        # EdgarTools / SEC Company Facts API only return *un-dimensioned*
        # (consolidated) facts. Companies like HOOD that report shares BY
        # CLASS (Class A / Class B / Class C) via XBRL dimensions will show
        # 0 or missing for the consolidated concept, while the dimensioned
        # facts in the original filing instance carry the real numbers.
        #
        # This step is NOT optional: without it, the class-level breakdown
        # (class_a_shares / class_b_shares) is never populated, and the
        # period-end total for multi-class companies is wrong.
        data = self._enrich_from_filing_xbrl(t, data)

        with self._LOCK:
            self._MEM[t] = data
            disk = self._load_disk()
            disk[t] = data.as_dict()
            self._save_disk(disk)

        return data

    def reconcile_vs_market(
        self,
        filing_data: ShareCountData,
        market_implied: Optional[float],
        *,
        price: Optional[float] = None,
        market_cap: Optional[float] = None,
        market_period: Optional[str] = None,
    ) -> ShareCountReconciliation:
        """Reconcile Market Implied shares vs the best Filing share count.

        Market Implied = MarketCap / Price (or the provider's shares_outstanding).
        Filing = the latest period-end common shares from SEC.

        This comparison must NOT assume Market Implied is correct merely because
        it satisfies MarketCap = Price × Shares.
        """
        # Resolve market-implied shares
        if market_implied is None and market_cap is not None and price is not None and price > 0:
            market_implied = market_cap / price

        filing_fact = filing_data.latest_period_end_shares()

        # Data missing
        if market_implied is None or market_implied <= 0:
            return ShareCountReconciliation(
                status=ReconciliationStatus.DATA_MISSING,
                source_a_label="Market Implied",
                source_b_label="SEC Filing" + (f" ({filing_fact.concept})" if filing_fact else ""),
                value_a=None,
                value_b=filing_fact.value if filing_fact else None,
                caliber_a="market",
                caliber_b=filing_fact.caliber if filing_fact else "",
                period_a=market_period,
                period_b=filing_fact.period_end if filing_fact else None,
                reason="Market implied shares not available",
                usable_for_valuation=False,
                needs_manual_review=True,
            )
        if filing_fact is None:
            return ShareCountReconciliation(
                status=ReconciliationStatus.DATA_MISSING,
                source_a_label="Market Implied",
                source_b_label="SEC Filing (no period-end shares found)",
                value_a=market_implied,
                value_b=None,
                caliber_a="market",
                caliber_b="",
                period_a=market_period,
                period_b=None,
                reason="No period-end share count available from SEC filings",
                usable_for_valuation=False,
                needs_manual_review=True,
            )

        # Caliber comparison — market implied vs filing period-end
        caliber_a = "market_implied"
        caliber_b = filing_fact.caliber

        # Period comparison
        period_a = market_period
        period_b = filing_fact.period_end
        period_gap = _period_gap_days(period_a, period_b)

        # Difference
        diff_pct = (market_implied - filing_fact.value) / filing_fact.value * 100.0
        abs_diff = abs(diff_pct)

        # Determine status
        if period_gap is not None and period_gap > 180:
            status = ReconciliationStatus.PERIOD_MISMATCH
            reason = (
                f"Market period ({period_a}) and filing period ({period_b}) "
                f"differ by {period_gap} days — counts may legitimately differ "
                f"due to buybacks/issuance between dates"
            )
            usable = False
            review = True
        elif abs_diff < 2.0:
            status = ReconciliationStatus.MATCHED
            reason = f"Difference {diff_pct:+.2f}% within 2% tolerance"
            usable = True
            review = False
        elif abs_diff < 5.0:
            status = ReconciliationStatus.ACCEPTABLE_DIFFERENCE
            reason = f"Difference {diff_pct:+.2f}% within 5% — likely timing/rounding"
            usable = True
            review = False
        else:
            status = ReconciliationStatus.RECONCILIATION_REQUIRED
            reason = (
                f"Difference {diff_pct:+.2f}% exceeds 5% — market implied "
                f"{market_implied:,.0f} vs filing {filing_fact.value:,.0f} "
                f"({filing_fact.concept} @ {filing_fact.period_end}). "
                f"Possible causes: recent buyback/issuance not yet in latest filing, "
                f"different share class, or data provider error. "
                f"Do NOT assume market implied is correct."
            )
            usable = False
            review = True

        return ShareCountReconciliation(
            status=status,
            source_a_label="Market Implied (Price × Shares or provider)",
            source_b_label=f"SEC Filing ({filing_fact.concept})",
            value_a=market_implied,
            value_b=filing_fact.value,
            caliber_a=caliber_a,
            caliber_b=caliber_b,
            period_a=period_a,
            period_b=period_b,
            difference_pct=diff_pct,
            reason=reason,
            usable_for_valuation=usable,
            needs_manual_review=review,
        )

    # ------------------------------------------------------------------
    # EdgarTools path (primary)
    # ------------------------------------------------------------------
    def _fetch_edgartools(self, ticker: str) -> Optional[ShareCountData]:
        """Fetch via EdgarTools — returns None on failure."""
        try:
            import edgar

            edgar.set_identity(_edgar_identity())
            from edgar import Company

            company = Company(ticker)
            if company is None or getattr(company, "not_found", False):
                return None

            cik = str(company.cik) if company.cik else ""
            facts = company.facts
            if facts is None:
                return ShareCountData(ticker=ticker, cik=cik)

            df = facts.to_dataframe()
            all_facts: List[ShareFact] = []
            data = ShareCountData(ticker=ticker, cik=cik)

            for concept in _SHARE_CONCEPTS:
                sub = df[df["concept"] == concept]
                if len(sub) == 0:
                    continue
                # Get the latest fact — EdgarTools DataFrame is ordered oldest-first,
                # so the LAST row is the most recent. Sort by period_end to be safe.
                try:
                    sub_sorted = sub.sort_values("period_end", na_position="first")
                    latest_row = sub_sorted.iloc[-1]
                except Exception:
                    latest_row = sub.iloc[-1]
                fact = _row_to_share_fact(latest_row, concept, source="edgartools")
                if fact is None or fact.value <= 0:
                    continue
                all_facts.append(fact)
                _assign_to_data(data, fact)

            # Also get the shares_outstanding convenience property
            try:
                so = company.shares_outstanding
                if so is not None and so > 0 and data.period_end_dei is None:
                    # Use the convenience property as a fallback for dei
                    fact = ShareFact(
                        value=float(so),
                        unit="shares",
                        concept="dei:EntityCommonStockSharesOutstanding",
                        caliber="period_end_dei",
                        period_type="instant",
                        source="edgartools_property",
                    )
                    data.period_end_dei = fact
                    all_facts.append(fact)
            except Exception:
                pass

            data.all_facts = all_facts

            # Filing history metadata
            try:
                filings = company.get_filings(form="10-K")
                latest_filing = next(iter(filings), None)
                if latest_filing:
                    data.latest_filing_date = str(latest_filing.filing_date)
                    data.latest_form_type = str(latest_filing.form)
                    data.latest_accession = str(latest_filing.accession_number)
            except Exception:
                pass

            if not all_facts:
                # Try latest 10-Q filing too
                try:
                    qfilings = company.get_filings(form="10-Q")
                    latest_q = next(iter(qfilings), None)
                    if latest_q:
                        data.latest_filing_date = str(latest_q.filing_date)
                        data.latest_form_type = str(latest_q.form)
                        data.latest_accession = str(latest_q.accession_number)
                except Exception:
                    pass

            return data

        except Exception as e:
            log.debug(f"EdgarTools fetch failed for {ticker}: {e}")
            return None

    # ------------------------------------------------------------------
    # SEC API fallback
    # ------------------------------------------------------------------
    def _fetch_sec_api(self, ticker: str) -> Optional[ShareCountData]:
        """Fallback: directly use SEC Company Facts JSON API."""
        try:
            import httpx

            # Resolve CIK via the identity resolver
            from data.identity_resolver import IdentityResolver

            resolver = IdentityResolver(offline=False)
            identity = resolver.resolve(ticker)
            cik = identity.cik
            if not cik:
                return None

            cik_int = str(int(cik))
            url = _SEC_COMPANYFACTS.format(cik_int=cik_int)
            headers = {"User-Agent": _sec_ua()}
            client = httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
            r = client.get(url, headers=headers)
            client.close()
            if r.status_code != 200:
                return None

            body = r.json()
            facts = body.get("facts", {})
            us_gaap = facts.get("us-gaap", {})
            dei = facts.get("dei", {})

            data = ShareCountData(ticker=ticker, cik=cik)
            all_facts: List[ShareFact] = []

            for concept in _SHARE_CONCEPTS:
                taxonomy, local_name = concept.split(":", 1) if ":" in concept else ("", concept)
                tax_data = dei if taxonomy == "dei" else us_gaap
                concept_data = tax_data.get(local_name)
                if not concept_data:
                    continue
                units = concept_data.get("units", {})
                shares_units = units.get("shares", [])
                if not shares_units:
                    continue
                # Get the latest fact (last in the array is typically newest)
                latest = shares_units[-1]
                val = latest.get("val")
                if val is None or val <= 0:
                    continue
                period_end = latest.get("end")
                period_start = latest.get("start")
                period_type = "duration" if period_start else "instant"
                form = latest.get("form", "")
                accn = latest.get("accn", "")
                filed = latest.get("filed", "")
                fact = ShareFact(
                    value=float(val),
                    unit="shares",
                    concept=concept,
                    caliber=_CONCEPT_CALIBER.get(concept, "unknown"),
                    period_end=period_end,
                    period_start=period_start,
                    period_type=period_type,
                    filing_date=filed,
                    form_type=form,
                    accession_number=accn,
                    source="sec_api",
                )
                all_facts.append(fact)
                _assign_to_data(data, fact)

            data.all_facts = all_facts
            if all_facts:
                latest = max(all_facts, key=lambda f: f.filing_date or "")
                data.latest_filing_date = latest.filing_date
                data.latest_form_type = latest.form_type
                data.latest_accession = latest.accession_number
            return data if all_facts else None

        except Exception as e:
            log.debug(f"SEC API fetch failed for {ticker}: {e}")
            return None

    # ------------------------------------------------------------------
    # Filing XBRL enrichment (Phase 1.1 / 1.2)
    # ------------------------------------------------------------------
    def _enrich_from_filing_xbrl(self, ticker: str, data: ShareCountData) -> ShareCountData:
        """Enrich ShareCountData with dimensioned facts from the original filing XBRL.

        EdgarTools and the SEC Company Facts API return only **un-dimensioned**
        (consolidated) facts. For multi-class companies (HOOD Class A/B/C,
        GOOGL Class A/B/C, META Class A/B), the consolidated concept may be 0
        or missing, while the dimensioned facts in the filing instance carry
        the real per-class numbers.

        This method:
          1. Downloads the latest 10-K / 10-Q XBRL instance via
             :class:`FilingShareExtractor`.
          2. Parses all share-related facts including dimensions.
          3. Uses :func:`aggregate_share_classes_multi` to resolve the
             period-end total across concepts (Outstanding vs Issued) and
             share classes.
          4. Fills in class_a_shares / class_b_shares on the ShareCountData.
          5. If the period-end total was missing from EdgarTools/SEC API but
             found via the filing XBRL, fills it in too.

        Rules (from the P0 spec):
          - 0 values are NOT used as valid share counts (is_valid=False).
          - Weighted Average Shares are NOT used as a proxy for period-end.
          - Class-level facts are only summed when mutually exclusive.
          - Dimensioned and un-dimensioned totals are never double-counted.
          - Missing data stays None — never fabricated.
        """
        try:
            from data.filing_share_extractor import (
                FilingShareExtractor,
                aggregate_share_classes_multi,
                find_dei_shares,
                FilingShareFact,
            )

            extractor = FilingShareExtractor()
            filing_facts: List[FilingShareFact] = extractor.extract(ticker, max_filings=3)
            if not filing_facts:
                return data

            # Convert FilingShareFact → ShareFact for unified storage
            for ff in filing_facts:
                concept_full = ff.concept
                # Map local concept name to full concept for caliber lookup
                if concept_full == "EntityCommonStockSharesOutstanding":
                    concept_full = "dei:EntityCommonStockSharesOutstanding"
                else:
                    concept_full = f"us-gaap:{ff.concept}"

                caliber = _CONCEPT_CALIBER.get(concept_full, "unknown")
                if caliber == "unknown":
                    # Skip concepts we don't know how to classify
                    continue

                # Only keep valid facts (value > 0) for the main data fields
                if not ff.is_valid:
                    # Still record 0-value facts in all_facts for audit
                    # but do NOT assign them to data fields
                    continue

                share_fact = ShareFact(
                    value=ff.value,
                    unit="shares",
                    concept=concept_full,
                    caliber=caliber,
                    period_end=ff.period_end,
                    period_start=ff.period_start,
                    period_type=ff.period_type,
                    filing_date=ff.filing_date,
                    form_type=ff.filing_form,
                    accession_number=ff.accession_number,
                    source="filing_xbrl",
                    dimensions=str(ff.dimensions) if ff.dimensions else "",
                )

                # Check if this fact is already in all_facts (avoid duplicates
                # from EdgarTools/SEC API which may have the same consolidated fact)
                already_present = any(
                    f.concept == share_fact.concept
                    and f.value == share_fact.value
                    and f.period_end == share_fact.period_end
                    for f in data.all_facts
                )
                if not already_present:
                    data.all_facts.append(share_fact)

                # Assign to data fields only if not already set
                _assign_to_data(data, share_fact)

            # --- Class-level breakdown ---
            breakdown = aggregate_share_classes_multi(filing_facts)
            if breakdown.reconciliation_status != "INCOMPLETE":
                # Populate class-level fields
                for class_name, shares in breakdown.classes.items():
                    class_name_lower = class_name.lower()
                    if "classa" in class_name_lower or "class_a" in class_name_lower:
                        if data.class_a_shares is None:
                            data.class_a_shares = ShareFact(
                                value=shares,
                                unit="shares",
                                concept="CommonStockSharesOutstanding (Class A)",
                                caliber="period_end_common",
                                period_end=breakdown.period_end,
                                period_type="instant",
                                accession_number=breakdown.source_filing,
                                source="filing_xbrl_dimension",
                                dimensions=f"ClassA:{class_name}",
                            )
                    elif "classb" in class_name_lower or "class_b" in class_name_lower:
                        if data.class_b_shares is None:
                            data.class_b_shares = ShareFact(
                                value=shares,
                                unit="shares",
                                concept="CommonStockSharesOutstanding (Class B)",
                                caliber="period_end_common",
                                period_end=breakdown.period_end,
                                period_type="instant",
                                accession_number=breakdown.source_filing,
                                source="filing_xbrl_dimension",
                                dimensions=f"ClassB:{class_name}",
                            )

                # If period-end was missing from EdgarTools/SEC API, fill it
                # from the filing XBRL breakdown
                if breakdown.total is not None and breakdown.total > 0:
                    if data.latest_period_end_shares() is None:
                        data.period_end_common = ShareFact(
                            value=breakdown.total,
                            unit="shares",
                            concept="CommonStockSharesOutstanding (sum of classes)",
                            caliber="period_end_common",
                            period_end=breakdown.period_end,
                            period_type="instant",
                            accession_number=breakdown.source_filing,
                            source="filing_xbrl_dimension",
                            dimensions=f"method={breakdown.calculation_method}",
                        )

            # --- DEI fallback ---
            # If DEI was not found via EdgarTools/SEC API, check filing XBRL
            if data.period_end_dei is None:
                dei_fact = find_dei_shares(filing_facts)
                if dei_fact is not None:
                    data.period_end_dei = ShareFact(
                        value=dei_fact.value,
                        unit="shares",
                        concept="dei:EntityCommonStockSharesOutstanding",
                        caliber="period_end_dei",
                        period_end=dei_fact.period_end,
                        period_type="instant",
                        filing_date=dei_fact.filing_date,
                        form_type=dei_fact.filing_form,
                        accession_number=dei_fact.accession_number,
                        source="filing_xbrl",
                    )

            # Update filing metadata if missing
            if not data.latest_accession:
                latest = max(filing_facts, key=lambda f: f.filing_date or "")
                data.latest_filing_date = latest.filing_date
                data.latest_form_type = latest.filing_form
                data.latest_accession = latest.accession_number

            # --- Dilution evidence (Phase 1.4) ---
            # Extract Options / RSU / Convertible / SBC evidence from the same
            # XBRL instances. This ONLY COLLECTS EVIDENCE — it does NOT compute
            # fully-diluted shares. The evidence is attached to ShareCountData
            # so models can inspect it without re-downloading filings.
            if data.dilution_evidence is None:
                try:
                    from data.dilution_evidence import build_dilution_report
                    dilution_facts = extractor.extract_dilution(ticker)
                    if dilution_facts:
                        report = build_dilution_report(ticker, dilution_facts)
                        # Enrich with GAAP diluted WA if available
                        if data.weighted_avg_diluted is not None:
                            report.gaap_diluted_weighted_avg_shares = data.weighted_avg_diluted.value
                        data.dilution_evidence = report
                except Exception as de:
                    log.debug(f"Dilution evidence extraction failed for {ticker}: {de}")

            return data

        except Exception as e:
            log.debug(f"Filing XBRL enrichment failed for {ticker}: {e}")
            return data

    # ------------------------------------------------------------------
    # Disk cache
    # ------------------------------------------------------------------
    def _load_disk(self) -> Dict[str, Any]:
        if self._disk is not None:
            return self._disk
        disk: Dict[str, Any] = {}
        if self._cache_path.exists():
            try:
                loaded = json.loads(self._cache_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    disk = loaded
            except Exception:
                disk = {}
        self._disk = disk
        return disk

    def _save_disk(self, data: Dict[str, Any]) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            log.debug(f"share count cache write failed: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row_to_share_fact(row: Any, concept: str, source: str = "") -> Optional[ShareFact]:
    """Convert a pandas DataFrame row to a ShareFact."""
    try:
        val = row["numeric_value"]
        if val is None or (isinstance(val, float) and val != val):  # NaN check
            return None
        val = float(val)
        if val <= 0:
            return None
        period_end = str(row.get("period_end", "") or "")
        period_start = str(row.get("period_start", "") or "")
        period_type = "duration" if period_start and period_start != "None" else "instant"
        fiscal_period = str(row.get("fiscal_period", "") or "")
        form_type = ""
        # Map fiscal_period to likely form type
        if fiscal_period == "FY":
            form_type = "10-K"
        elif fiscal_period in ("Q1", "Q2", "Q3"):
            form_type = "10-Q"
        return ShareFact(
            value=val,
            unit=str(row.get("unit", "shares") or "shares"),
            concept=concept,
            caliber=_CONCEPT_CALIBER.get(concept, "unknown"),
            period_end=period_end if period_end and period_end != "None" else None,
            period_start=period_start if period_start and period_start != "None" else None,
            period_type=period_type,
            form_type=form_type,
            source=source,
        )
    except Exception:
        return None


def _assign_to_data(data: ShareCountData, fact: ShareFact) -> None:
    """Route a ShareFact to the correct field on ShareCountData."""
    caliber = fact.caliber
    if caliber == "period_end_dei" and data.period_end_dei is None:
        data.period_end_dei = fact
    elif caliber == "period_end_common" and data.period_end_common is None:
        data.period_end_common = fact
    elif caliber == "period_end_issued" and data.period_end_issued is None:
        data.period_end_issued = fact
    elif caliber == "weighted_avg_basic" and data.weighted_avg_basic is None:
        data.weighted_avg_basic = fact
    elif caliber == "weighted_avg_diluted" and data.weighted_avg_diluted is None:
        data.weighted_avg_diluted = fact
    elif caliber == "treasury" and data.treasury_shares is None:
        data.treasury_shares = fact
    elif caliber == "preferred" and data.preferred_shares is None:
        data.preferred_shares = fact


def _dict_to_share_count_data(d: Dict[str, Any], ticker: str) -> ShareCountData:
    """Reconstruct ShareCountData from a cached dict."""
    data = ShareCountData(
        ticker=ticker,
        cik=str(d.get("cik", "")),
        latest_filing_date=d.get("latest_filing_date"),
        latest_form_type=d.get("latest_form_type", ""),
        latest_accession=d.get("latest_accession", ""),
    )
    for key, attr in [
        ("period_end_dei", "period_end_dei"),
        ("period_end_common", "period_end_common"),
        ("period_end_issued", "period_end_issued"),
        ("treasury_shares", "treasury_shares"),
        ("preferred_shares", "preferred_shares"),
        ("weighted_avg_basic", "weighted_avg_basic"),
        ("weighted_avg_diluted", "weighted_avg_diluted"),
        ("class_a_shares", "class_a_shares"),
        ("class_b_shares", "class_b_shares"),
    ]:
        v = d.get(key)
        if v and isinstance(v, dict):
            setattr(data, attr, ShareFact(**{
                k: v[k] for k in ShareFact.__dataclass_fields__ if k in v
            }))
    return data


def _period_gap_days(a: Optional[str], b: Optional[str]) -> Optional[int]:
    """Approximate day gap between two ISO date strings."""
    if not a or not b:
        return None
    try:
        from datetime import date

        da = date.fromisoformat(str(a)[:10])
        db = date.fromisoformat(str(b)[:10])
        return abs((da - db).days)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------
_engine: Optional[ShareCountEngine] = None


def get_share_count_engine() -> ShareCountEngine:
    """Singleton accessor."""
    global _engine
    if _engine is None:
        _engine = ShareCountEngine()
    return _engine


def fetch_share_count(ticker: str) -> ShareCountData:
    """One-shot convenience: fetch share-count data for a ticker."""
    return get_share_count_engine().fetch(ticker)


__all__ = [
    "ShareFact",
    "ShareCountData",
    "ShareCountReconciliation",
    "ReconciliationStatus",
    "ShareCountEngine",
    "get_share_count_engine",
    "fetch_share_count",
]
