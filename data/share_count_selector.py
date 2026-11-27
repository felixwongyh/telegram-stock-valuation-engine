"""data/share_count_selector.py — Unified share-count selection for valuation models.

Phase 1.3: Every valuation model (P/E, P/B, RIM, DCF, Monte Carlo) must get its
share count from ONE place, not decide independently. This module is that place.

Selection rules (from the P0 spec):
  * P/E → TTM Diluted Weighted Average Shares (matches the EPS denominator)
  * P/B → Period-end Common Shares (matches the book-value denominator)
  * Bank RIM → Period-end Common Shares (matches the BVPS denominator)
  * Market Cap → Current market shares (Yahoo provider)
  * EV-based → Market shares (market-cap consistent)

Every selection returns a :class:`ShareCountSelection` with:
  - value: the selected share count
  - caliber: which type was selected
  - source: where it came from ("sec_filing", "yahoo", "ttm_statement", etc.)
  - confidence: HIGH / MEDIUM / LOW (based on evidence quality, not source name)
  - status: VERIFIED / NEEDS_REVIEW / MISSING / FALLBACK
  - evidence: full provenance chain

Missing data returns status=MISSING with value=None — never a silent fill.
Fallbacks are explicit and recorded.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from config import get_logger
from data.models import FinancialData

log = get_logger("data.share_count_selector")


class ShareCaliber(str, Enum):
    """The type of share count — determines which model uses it."""
    PERIOD_END_DEI = "period_end_dei"               # dei:EntityCommonStockSharesOutstanding (cover page)
    PERIOD_END_COMMON = "period_end_common"          # us-gaap:CommonStockSharesOutstanding (balance sheet)
    PERIOD_END_ISSUED = "period_end_issued"           # us-gaap:CommonStockSharesIssued
    WEIGHTED_AVG_BASIC = "weighted_avg_basic"         # TTM basic weighted average
    WEIGHTED_AVG_DILUTED = "weighted_avg_diluted"     # TTM diluted weighted average
    MARKET_IMPLIED = "market_implied"                 # Yahoo / provider snapshot
    TTM_STATEMENT = "ttm_statement"                   # from TTM financial statement
    FALLBACK = "fallback"                             # no reliable source


class Confidence(str, Enum):
    HIGH = "HIGH"          # Direct SEC filing fact, valid value, correct period
    MEDIUM = "MEDIUM"      # SEC filing fact but period mismatch or class ambiguity
    LOW = "LOW"            # Yahoo provider or indirect calculation
    NONE = "NONE"          # Missing or unreliable


class SelectionStatus(str, Enum):
    VERIFIED = "VERIFIED"              # High-quality source, correct caliber
    NEEDS_REVIEW = "NEEDS_REVIEW"      # Source available but may have issues
    FALLBACK = "FALLBACK"              # Fell back to a less-preferred source
    MISSING = "MISSING"                # No data available


class ValuationModel(str, Enum):
    PE = "PE"
    PB = "PB"
    RIM = "RIM"
    DDM = "DDM"
    DCF = "DCF"
    EPS = "EPS"
    MARKET_CAP = "MARKET_CAP"
    EV_EBITDA = "EV_EBITDA"
    EV_SALES = "EV_SALES"
    FCF_YIELD = "FCF_YIELD"
    MONTE_CARLO = "MONTE_CARLO"


@dataclass
class ShareCountSelection:
    """The result of selecting a share count for a valuation model.

    Every field must be populated — no silent defaults. If data is missing,
    status=MISSING and value=None.
    """
    value: Optional[float]
    caliber: ShareCaliber
    source: str               # "sec_filing_dei", "sec_filing_common", "yahoo", "ttm", etc.
    confidence: Confidence
    status: SelectionStatus
    period_end: Optional[str] = None   # ISO date of the share count
    filing_form: str = ""              # "10-K", "10-Q" if from SEC
    accession_number: str = ""
    xbrl_concept: str = ""             # if from SEC
    calculation_method: str = ""       # "DIRECT_FACT", "SUM_OF_CLASSES", etc.
    reason: str = ""                   # why this caliber was chosen
    fallback_from: Optional[str] = None  # what was preferred but unavailable

    def as_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "caliber": self.caliber.value,
            "source": self.source,
            "confidence": self.confidence.value,
            "status": self.status.value,
            "period_end": self.period_end,
            "filing_form": self.filing_form,
            "accession_number": self.accession_number,
            "xbrl_concept": self.xbrl_concept,
            "calculation_method": self.calculation_method,
            "reason": self.reason,
            "fallback_from": self.fallback_from,
        }


def select_share_count(
    data: FinancialData,
    model: ValuationModel,
) -> ShareCountSelection:
    """Select the correct share count for a valuation model.

    This is the SINGLE entry point — models must not read shares directly.

    Selection priority by model:
      PE / EPS:
        1. SEC TTM Diluted Weighted Average Shares
        2. TTM statement shares_outstanding
        3. Yahoo market shares (FALLBACK — basis mismatch warning)

      PB / RIM:
        1. SEC Period-end Common Shares (dei or us-gaap)
        2. TTM balance-sheet shares
        3. Yahoo market shares (FALLBACK — basis mismatch warning)

      MARKET_CAP / EV_EBITDA / EV_SALES:
        1. Yahoo market shares (correct for market-cap consistency)
        2. SEC period-end (FALLBACK — may be stale)

      DCF:
        1. Yahoo market shares (market-cap consistent for WACC weights)
        2. SEC period-end (FALLBACK)

      DDM:
        1. SEC Period-end Common Shares
        2. Yahoo market shares (FALLBACK)
    """
    mkt = data.market
    ttm = data.ttm

    # SEC-sourced shares (already populated by ShareCountEngine in providers.py)
    sec_data = getattr(mkt, "sec_share_count", None)
    sec_period_end = getattr(mkt, "sec_period_end_shares", None)
    sec_diluted_wa = getattr(mkt, "sec_weighted_avg_diluted", None)
    sec_pe_date = getattr(mkt, "sec_shares_period_end", None)
    sec_source = getattr(mkt, "sec_shares_source", None)

    # Yahoo / provider shares
    yahoo_shares = mkt.shares_outstanding

    # TTM statement shares
    ttm_shares = ttm.shares_outstanding if ttm else None

    if model in (ValuationModel.PE, ValuationModel.EPS):
        # P/E needs TTM Diluted Weighted Average Shares
        if sec_diluted_wa is not None and sec_diluted_wa > 0:
            # Get the fact object for provenance
            concept = "WeightedAverageNumberOfDilutedSharesOutstanding"
            fact = None
            if sec_data:
                fact = sec_data.weighted_avg_diluted
            return ShareCountSelection(
                value=sec_diluted_wa,
                caliber=ShareCaliber.WEIGHTED_AVG_DILUTED,
                source=f"sec_filing_{sec_source or 'edgartools'}",
                confidence=Confidence.HIGH,
                status=SelectionStatus.VERIFIED,
                period_end=fact.period_end if fact else sec_pe_date,
                filing_form=fact.form_type if fact else "",
                accession_number=fact.accession_number if fact else "",
                xbrl_concept=fact.concept if fact else concept,
                calculation_method="DIRECT_FACT",
                reason="P/E requires TTM diluted weighted average shares (matches EPS denominator)",
            )
        if ttm_shares is not None and ttm_shares > 0:
            return ShareCountSelection(
                value=ttm_shares,
                caliber=ShareCaliber.TTM_STATEMENT,
                source="ttm_statement",
                confidence=Confidence.MEDIUM,
                status=SelectionStatus.NEEDS_REVIEW,
                period_end=ttm.period_end if ttm else None,
                reason="TTM statement shares (SEC diluted weighted avg unavailable — may not match EPS caliber)",
                fallback_from="sec_weighted_avg_diluted",
            )
        if yahoo_shares is not None and yahoo_shares > 0:
            return ShareCountSelection(
                value=yahoo_shares,
                caliber=ShareCaliber.MARKET_IMPLIED,
                source="yahoo_provider",
                confidence=Confidence.LOW,
                status=SelectionStatus.FALLBACK,
                reason="Yahoo market shares used for P/E — basis mismatch: EPS denominator may differ from market snapshot",
                fallback_from="sec_weighted_avg_diluted",
            )
        return ShareCountSelection(
            value=None,
            caliber=ShareCaliber.FALLBACK,
            source="none",
            confidence=Confidence.NONE,
            status=SelectionStatus.MISSING,
            reason="No share count available for P/E (SEC diluted WA, TTM, and Yahoo all unavailable)",
        )

    if model in (ValuationModel.PB, ValuationModel.RIM, ValuationModel.DDM):
        # P/B and RIM need period-end common shares
        # Priority: SEC DEI (cover page) > SEC CommonStockSharesOutstanding > TTM > Yahoo
        if sec_data:
            # Try DEI first (cover page — most accurate period-end)
            dei_fact = sec_data.latest_period_end_shares()
            if dei_fact is not None and dei_fact.value > 0:
                return ShareCountSelection(
                    value=dei_fact.value,
                    caliber=ShareCaliber.PERIOD_END_DEI,
                    source=f"sec_filing_{dei_fact.source}",
                    confidence=Confidence.HIGH,
                    status=SelectionStatus.VERIFIED,
                    period_end=dei_fact.period_end,
                    filing_form=dei_fact.form_type,
                    accession_number=dei_fact.accession_number,
                    xbrl_concept=dei_fact.concept,
                    calculation_method="DIRECT_FACT",
                    reason=f"{model.value} requires period-end common shares matching book-value denominator",
                )

        if sec_period_end is not None and sec_period_end > 0:
            return ShareCountSelection(
                value=sec_period_end,
                caliber=ShareCaliber.PERIOD_END_COMMON,
                source=f"sec_filing_{sec_source or 'edgartools'}",
                confidence=Confidence.HIGH,
                status=SelectionStatus.VERIFIED,
                period_end=sec_pe_date,
                reason=f"{model.value} requires period-end common shares (from MarketData SEC field)",
            )
        if ttm_shares is not None and ttm_shares > 0:
            return ShareCountSelection(
                value=ttm_shares,
                caliber=ShareCaliber.TTM_STATEMENT,
                source="ttm_statement",
                confidence=Confidence.MEDIUM,
                status=SelectionStatus.NEEDS_REVIEW,
                period_end=ttm.period_end if ttm else None,
                reason=f"TTM statement shares for {model.value} (SEC period-end unavailable — may be weighted avg, not period-end)",
                fallback_from="sec_period_end",
            )
        if yahoo_shares is not None and yahoo_shares > 0:
            return ShareCountSelection(
                value=yahoo_shares,
                caliber=ShareCaliber.MARKET_IMPLIED,
                source="yahoo_provider",
                confidence=Confidence.LOW,
                status=SelectionStatus.FALLBACK,
                reason=f"Yahoo market shares for {model.value} — basis mismatch: market snapshot may not match book-value period",
                fallback_from="sec_period_end",
            )
        return ShareCountSelection(
            value=None,
            caliber=ShareCaliber.FALLBACK,
            source="none",
            confidence=Confidence.NONE,
            status=SelectionStatus.MISSING,
            reason=f"No share count available for {model.value}",
        )

    if model in (ValuationModel.MARKET_CAP, ValuationModel.EV_EBITDA,
                 ValuationModel.EV_SALES, ValuationModel.FCF_YIELD):
        # Market-cap-based models need the current market snapshot
        if yahoo_shares is not None and yahoo_shares > 0:
            return ShareCountSelection(
                value=yahoo_shares,
                caliber=ShareCaliber.MARKET_IMPLIED,
                source="yahoo_provider",
                confidence=Confidence.MEDIUM,
                status=SelectionStatus.VERIFIED,
                reason=f"{model.value} uses market-implied shares (consistent with market cap)",
            )
        # Fallback to SEC period-end
        if sec_period_end is not None and sec_period_end > 0:
            return ShareCountSelection(
                value=sec_period_end,
                caliber=ShareCaliber.PERIOD_END_COMMON,
                source=f"sec_filing_{sec_source or 'edgartools'}",
                confidence=Confidence.MEDIUM,
                status=SelectionStatus.FALLBACK,
                period_end=sec_pe_date,
                reason=f"SEC period-end shares for {model.value} (Yahoo unavailable — may be stale vs market)",
                fallback_from="yahoo_market",
            )
        return ShareCountSelection(
            value=None,
            caliber=ShareCaliber.FALLBACK,
            source="none",
            confidence=Confidence.NONE,
            status=SelectionStatus.MISSING,
            reason=f"No share count available for {model.value}",
        )

    if model == ValuationModel.DCF:
        # DCF uses market-cap for WACC weights → market shares
        if yahoo_shares is not None and yahoo_shares > 0:
            return ShareCountSelection(
                value=yahoo_shares,
                caliber=ShareCaliber.MARKET_IMPLIED,
                source="yahoo_provider",
                confidence=Confidence.MEDIUM,
                status=SelectionStatus.VERIFIED,
                reason="DCF uses market-implied shares (consistent with WACC market-cap weights)",
            )
        if sec_period_end is not None and sec_period_end > 0:
            return ShareCountSelection(
                value=sec_period_end,
                caliber=ShareCaliber.PERIOD_END_COMMON,
                source=f"sec_filing_{sec_source or 'edgartools'}",
                confidence=Confidence.MEDIUM,
                status=SelectionStatus.FALLBACK,
                period_end=sec_pe_date,
                reason="SEC period-end for DCF (Yahoo unavailable)",
                fallback_from="yahoo_market",
            )
        return ShareCountSelection(
            value=None,
            caliber=ShareCaliber.FALLBACK,
            source="none",
            confidence=Confidence.NONE,
            status=SelectionStatus.MISSING,
            reason="No share count available for DCF",
        )

    if model == ValuationModel.MONTE_CARLO:
        # MC typically follows the underlying model's share count
        # Default to period-end for banks, market for others
        if sec_period_end is not None and sec_period_end > 0:
            return ShareCountSelection(
                value=sec_period_end,
                caliber=ShareCaliber.PERIOD_END_COMMON,
                source=f"sec_filing_{sec_source or 'edgartools'}",
                confidence=Confidence.HIGH,
                status=SelectionStatus.VERIFIED,
                period_end=sec_pe_date,
                reason="Monte Carlo uses SEC period-end shares",
            )
        if yahoo_shares is not None and yahoo_shares > 0:
            return ShareCountSelection(
                value=yahoo_shares,
                caliber=ShareCaliber.MARKET_IMPLIED,
                source="yahoo_provider",
                confidence=Confidence.MEDIUM,
                status=SelectionStatus.FALLBACK,
                reason="Monte Carlo uses Yahoo market shares (SEC unavailable)",
                fallback_from="sec_period_end",
            )
        return ShareCountSelection(
            value=None,
            caliber=ShareCaliber.FALLBACK,
            source="none",
            confidence=Confidence.NONE,
            status=SelectionStatus.MISSING,
            reason="No share count available for Monte Carlo",
        )

    # Unknown model
    return ShareCountSelection(
        value=None,
        caliber=ShareCaliber.FALLBACK,
        source="none",
        confidence=Confidence.NONE,
        status=SelectionStatus.MISSING,
        reason=f"Unknown model: {model}",
    )


__all__ = [
    "ShareCaliber",
    "Confidence",
    "SelectionStatus",
    "ValuationModel",
    "ShareCountSelection",
    "select_share_count",
]
