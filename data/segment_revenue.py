"""data/segment_revenue.py - Segment-level revenue source (M-31).

Why (M-31)
----------
Dimension ③ of the internal taxonomy (Revenue Composition) was permanently
``unavailable``: no provider supplied segment-level revenue, so multi-business
companies could not be decomposed — and the segment-level beta upgrade (M-35)
had no weights to aggregate with.

Resolution chain (first non-empty wins)
---------------------------------------
  Layer 1  Financial Modeling Prep  ``/stable`` / ``v4`` / ``v3``
           ``revenue-product-segmentation`` — only when ``FMP_API_KEY`` is set.
  Layer 2  SEC 10-K / 20-F **filing-instance XBRL** (``data.filing_evidence``,
           M-38) — key-free; used when FMP resolves nothing (missing / expired /
           rate-limited key, or an uncovered ticker). Wired by
           :func:`resolve_segments`.

Note on SEC EDGAR
-----------------
SEC's ``companyfacts`` JSON was verified to contain **only consolidated** facts
(no ``Axis`` / ``srt:ProductOrServiceAxis`` dimensions), so it cannot supply
segment revenue. The two viable key-free routes are the quarterly Financial
Statement Data Sets (whole-zip downloads) or **filing-instance XBRL** parsing —
M-38 implemented the latter (see :mod:`data.filing_evidence`). We never
fabricate segments; when no source resolves the caller gets an explicit empty
list.

Results are memoised in-process and, when ``cache_path`` is supplied, persisted
to disk so batch runs are resumable and the test suite stays offline and
deterministic.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import get_logger

log = get_logger("data.segment_revenue")

_DEFAULT_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "segment_revenue.json"
_FMP_STABLE = "https://financialmodelingprep.com/stable/revenue-product-segmentation"
_FMP_V4 = "https://financialmodelingprep.com/api/v4/revenue-product-segmentation"
_FMP_V3 = "https://financialmodelingprep.com/api/v3/revenue-product-segmentation/{symbol}"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)


def _fmp_keys() -> List[str]:
    """Return the configured FMP API keys.

    ``FMP_API_KEY`` may hold several comma-separated keys; they are tried in
    order so a rate-limited / exhausted key transparently falls through to the
    next one. Returns ``[]`` when unset (caller then resolves nothing).
    """
    raw = os.environ.get("FMP_API_KEY", "") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


@dataclass(frozen=True)
class Segment:
    """One reported business segment (raw, un-normalised)."""

    label: str
    revenue: Optional[float] = None           # absolute revenue, as reported
    operating_income: Optional[float] = None  # when the source provides it
    as_of: Optional[str] = None               # ISO date of the reported figure
    source: str = "unknown"


class SegmentRevenueResolver:
    """Resolve segment-level revenue from FMP (optional key), else explicit empty."""

    _MEM: Dict[str, List[Dict[str, Any]]] = {}

    def __init__(
        self,
        client: Any = None,
        cache_path: Optional[Path] = None,
        *,
        offline: bool = False,
    ) -> None:
        self._client = client
        self._offline = offline
        self._cache_path = Path(cache_path) if cache_path else _DEFAULT_CACHE
        self._disk: Optional[Dict[str, List[Dict[str, Any]]]] = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def get_segments(self, ticker: str) -> List[Segment]:
        """Return the latest reported segments for ``ticker`` (possibly empty)."""
        t = (ticker or "").upper().strip()
        if not t:
            return []
        if t in self._MEM:
            return _from_payload(self._MEM[t])
        disk = self._load_disk()
        if t in disk:
            self._MEM[t] = disk[t]
            return _from_payload(disk[t])

        raw: List[Dict[str, Any]] = []
        if not self._offline:
            for layer in (self._from_fmp_stable, self._from_fmp_v4, self._from_fmp_v3):
                try:
                    raw = layer(t)
                except Exception as e:  # network / parse errors are non-fatal
                    log.debug(f"segment source {layer.__name__} failed for {t}: {e}")
                    raw = []
                if raw:
                    break

        self._MEM[t] = raw
        disk[t] = raw
        self._save_disk(disk)
        return _from_payload(raw)

    def batch_get(self, tickers, *, sleep: float = 0.0) -> Dict[str, List[Segment]]:
        """Resolve many tickers; only non-empty segment lists are returned."""
        import time

        out: Dict[str, List[Segment]] = {}
        items = list(tickers)
        for i, tk in enumerate(items):
            segs = self.get_segments(tk)
            if segs:
                out[(tk or "").upper()] = segs
            if sleep and i + 1 < len(items):
                time.sleep(sleep)
        return out

    # ------------------------------------------------------------------
    # layers
    # ------------------------------------------------------------------
    def _from_fmp_stable(self, ticker: str) -> List[Dict[str, Any]]:
        """Current FMP endpoint (``/stable``) — flat annual product segmentation."""
        return self._from_fmp(
            _FMP_STABLE,
            {"symbol": ticker, "period": "annual", "structure": "flat"},
        )

    def _from_fmp_v4(self, ticker: str) -> List[Dict[str, Any]]:
        return self._from_fmp(
            _FMP_V4,
            {"symbol": ticker, "period": "annual", "structure": "flat"},
        )

    def _from_fmp_v3(self, ticker: str) -> List[Dict[str, Any]]:
        """Legacy endpoint (path carries the symbol)."""
        return self._from_fmp(_FMP_V3.format(symbol=ticker), {"period": "annual"})

    def _from_fmp(self, url: str, base_params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Call ``url`` with each configured key in turn until rows resolve."""
        keys = _fmp_keys()
        if not keys:
            return []
        for key in keys:
            params = dict(base_params)
            params["apikey"] = key
            r = self._get(url, params=params)
            if r is None or r.status_code != 200:
                continue
            try:
                payload = r.json()
            except Exception:
                continue
            rows = _extract_fmp(payload)
            if rows:
                return rows
        return []

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _get(self, url: str, params: Dict[str, Any]):
        client = self._client
        if client is None:
            import httpx

            client = httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
            self._client = client
        return client.get(url, params=params, headers={"User-Agent": _USER_AGENT})

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
            log.debug(f"segment revenue cache write failed: {e}")


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------
def _extract_fmp(payload: Any) -> List[Dict[str, Any]]:
    """Normalise FMP product-segmentation payloads into ``{label, revenue}`` rows.

    Accepts the shapes FMP returns:
      * ``[{"symbol":..., "date":..., "data": {segment: revenue}}]`` (``/stable``)
      * ``[{"2023-09-30": {"iPhone": 100, ...}}, ...]`` (date → segment → revenue)
      * ``[{"Aapl": 100, "Services": 50}, ...]`` (flat segment → revenue)
    Only the **most recent** period is kept (the latest reported mix).
    """
    if not isinstance(payload, list) or not payload:
        return []
    first = payload[0]
    if not isinstance(first, dict):
        return []

    # Shape C: current /stable response — metadata wrapper with a "data" mix.
    if isinstance(first.get("data"), dict):
        for row in payload:  # newest first; keep the first usable period
            mix = row.get("data") if isinstance(row, dict) else None
            if isinstance(mix, dict):
                as_of = row.get("date")
                rows = _rows_from_mix(
                    mix, as_of=as_of if isinstance(as_of, str) else None
                )
                if rows:
                    return rows
        return []

    # Shape B: list of single-key date dicts.
    if len(first) == 1 and isinstance(next(iter(first.values())), dict):
        for row in payload:  # FMP returns newest first; keep the first usable
            for date_key, mix in row.items():
                if isinstance(mix, dict):
                    return _rows_from_mix(mix, as_of=str(date_key))
        return []

    # Shape A: flat segment → revenue mapping.
    return _rows_from_mix(first, as_of=None)


def _rows_from_mix(mix: Dict[str, Any], as_of: Optional[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for label, val in mix.items():
        if not isinstance(label, str) or not label.strip():
            continue
        num = _to_float(val)
        if num is None or num <= 0:
            continue
        rows.append({"label": label.strip(), "revenue": num, "as_of": as_of})
    return rows


def _to_float(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return None
    return None


def _from_payload(rows: List[Dict[str, Any]]) -> List[Segment]:
    out: List[Segment] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        label = row.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        out.append(
            Segment(
                label=label.strip(),
                revenue=_to_float(row.get("revenue")),
                operating_income=_to_float(row.get("operating_income")),
                as_of=(row.get("as_of") if isinstance(row.get("as_of"), str) else None),
                source="fmp",
            )
        )
    return out


# ---------------------------------------------------------------------------
# downstream adapters
# ---------------------------------------------------------------------------
def to_revenue_composition(segments: List[Segment], *, source: str = "fmp") -> Any:
    """Build a taxonomy ``RevenueComposition`` from segments (pct of total revenue).

    Returns an explicit ``RevenueComposition.unavailable()`` when there are no
    usable segment revenues — never a fabricated mix.
    """
    from classification.taxonomy import RevenueComposition, SegmentRevenue

    usable: List[Tuple[Segment, float]] = []
    for s in segments:
        rev = s.revenue
        if isinstance(rev, (int, float)) and rev > 0:
            usable.append((s, float(rev)))
    if not usable:
        return RevenueComposition.unavailable("no segment revenue source resolved")

    total = sum(rev for _, rev in usable)
    if total <= 0:
        return RevenueComposition.unavailable("segment revenue totals to zero")

    as_of = next((s.as_of for s, _ in usable if s.as_of), None)
    items = [
        SegmentRevenue(
            label=s.label,
            pct=round(rev / total, 4),
            as_of=s.as_of,
            source=s.source or source,
        )
        for s, rev in usable
    ]
    return RevenueComposition(
        available=True,
        segments=items,
        as_of=as_of,
        source=source,
        note=f"{len(items)} 个分部（按收入占比）",
    )


def segment_weights(
    segments: List[Segment], *, by: str = "value"
) -> List[Tuple[str, float]]:
    """Segment weights for beta aggregation (M-35).

    ``by="value"`` prefers **operating income** (closer to business value) and
    falls back to revenue per segment when operating income is missing for any
    usable segment. ``by="revenue"`` forces revenue weighting. Returns
    ``[(label, weight)]`` summing to 1.0, or ``[]`` when nothing is usable.
    """
    usable = [
        s
        for s in segments
        if (s.revenue is not None and s.revenue > 0)
        or (s.operating_income is not None and s.operating_income > 0)
    ]
    if not usable:
        return []

    if by == "value" and all(
        s.operating_income is not None and s.operating_income > 0 for s in usable
    ):
        key = lambda s: float(s.operating_income)  # noqa: E731
    else:
        key = lambda s: float(s.revenue or 0.0)  # noqa: E731

    weights = [(s.label, key(s)) for s in usable]
    total = sum(w for _, w in weights)
    if total <= 0:
        return []
    return [(label, w / total) for label, w in weights]


# ---------------------------------------------------------------------------
# source chain — the production default path (M-31 → M-38)
# ---------------------------------------------------------------------------
def resolve_segments(
    ticker: str,
    *,
    client: Any = None,
    offline: bool = False,
    fmp_cache_path: Optional[Path] = None,
    filing_cache_path: Optional[Path] = None,
    identity_resolver: Any = None,
) -> List[Segment]:
    """Resolve segment revenue through the full source chain (first non-empty wins).

    Layer 1  FMP ``revenue-product-segmentation`` — structured and fast, but
             gated on ``FMP_API_KEY``; yields nothing when the key is missing,
             expired, rate-limited / out of credit, or the ticker is uncovered.
    Layer 2  SEC 10-K / 20-F **filing-instance XBRL** — key-free and
             authoritative; tried whenever layer 1 resolves nothing.

    Returns ``[]`` when neither layer produces a usable mix — never a fabricated
    one. The SEC layer is imported lazily so this module keeps no import cycle
    with :mod:`data.filing_evidence` (which imports ``Segment`` from here).
    """
    segs = SegmentRevenueResolver(
        client=client, cache_path=fmp_cache_path, offline=offline
    ).get_segments(ticker)
    if segs:
        return segs

    try:
        from data.filing_evidence import FilingBusinessExtractor
    except Exception as e:  # pragma: no cover - import guard
        log.debug(f"filing evidence layer unavailable: {e}")
        return []
    try:
        return FilingBusinessExtractor(
            client=client,
            cache_path=filing_cache_path,
            offline=offline,
            identity_resolver=identity_resolver,
        ).get_segments(ticker)
    except Exception as e:
        log.debug(f"filing evidence fallback failed for {ticker}: {e}")
        return []


__all__ = [
    "Segment",
    "SegmentRevenueResolver",
    "resolve_segments",
    "segment_weights",
    "to_revenue_composition",
]
