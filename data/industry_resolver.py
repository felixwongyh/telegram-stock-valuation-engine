"""data/industry_resolver.py - Multi-source sector/industry completion (H-03).

Yahoo's ``quoteSummary`` ``assetProfile`` is frequently gated (HTTP 401), so
``sector`` / ``industry`` come back ``None``. That missing pair is the
data-driven root cause of two downstream defects (M-16 / classification
accuracy): the +3.0 sector/industry hard rule never fires and the ML text
features lose their strongest signal.

This module completes the missing pair from three *additional* sources, in
priority order (first non-empty wins):

  Layer 1  FinanceDatabase       — offline, Yahoo-compatible ``sector`` /
           ``industry`` for 300k+ global tickers (``financedatabase``).
  Layer 2  SEC EDGAR             — authoritative US regulatory **SIC** code +
           description from the official JSON API
           (``company_tickers.json`` → ``submissions``), bridged to the Yahoo
           taxonomy via :mod:`data.sic_map`.
  Layer 3  Wikidata / Wikipedia  — last-resort industry lookup for obscure /
           newly listed / delisted tickers (Wikidata ``P452``),
           with ``wikipedia-api`` used to enrich the description when present.

Each source is **optional**: if a library is missing or the network is down the
layer returns ``{}`` and the chain continues. Results are memoised in-process
and, when a ``cache_path`` is supplied, persisted to disk so batch backfills are
resumable and the test suite stays offline and deterministic.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from config import get_logger
from data.sic_map import map_sic_to_yahoo

log = get_logger("data.industry_resolver")

_DEFAULT_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "industry_resolver.json"
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

# SEC requires a descriptive User-Agent with contact info (their fair-access
# policy). Override with SEC_USER_AGENT to set your own contact.
_DEFAULT_UA = "ValuationEngine/1.0 (research; contact@example.com)"

# Wikidata P452 industry label -> (Yahoo sector, Yahoo industry) keywords.
# Coarse on purpose: this is the last-resort layer.
_WIKIDATA_INDUSTRY_KEYWORDS = (
    ("semiconductor", "Technology", "Semiconductors"),
    ("software", "Technology", "Software - Application"),
    ("computer", "Technology", "Computer Hardware"),
    ("information technolog", "Technology", "Information Technology Services"),
    ("telecommunication", "Communication Services", "Telecom Services"),
    ("bank", "Financial Services", "Banks - Diversified"),
    ("insurance", "Financial Services", "Insurance - Diversified"),
    ("financial", "Financial Services", "Capital Markets"),
    ("real estate", "Real Estate", "REIT - Diversified"),
    ("pharmaceutical", "Healthcare", "Drug Manufacturers - General"),
    ("biotechnology", "Healthcare", "Biotechnology"),
    ("medical", "Healthcare", "Medical Devices"),
    ("health care", "Healthcare", "Medical Care Facilities"),
    ("oil", "Energy", "Oil & Gas E&P"),
    ("petroleum", "Energy", "Oil & Gas E&P"),
    ("natural gas", "Energy", "Oil & Gas Midstream"),
    ("electric", "Utilities", "Utilities - Regulated Electric"),
    ("utility", "Utilities", "Utilities - Diversified"),
    ("mining", "Basic Materials", "Other Industrial Metals & Mining"),
    ("chemical", "Basic Materials", "Specialty Chemicals"),
    ("automotive", "Consumer Cyclical", "Auto Manufacturers"),
    ("retail", "Consumer Cyclical", "Internet Retail"),
    ("food", "Consumer Defensive", "Packaged Foods"),
    ("beverage", "Consumer Defensive", "Beverages - Non-Alcoholic"),
    ("tobacco", "Consumer Defensive", "Tobacco"),
    ("airline", "Industrials", "Airlines"),
    ("aerospace", "Industrials", "Aerospace & Defense"),
    ("defense", "Industrials", "Aerospace & Defense"),
    ("railway", "Industrials", "Railroads"),
    ("logistics", "Industrials", "Integrated Freight & Logistics"),
    ("entertainment", "Communication Services", "Entertainment"),
    ("media", "Communication Services", "Entertainment"),
    ("conglomerate", "Industrials", "Conglomerates"),
)


class SectorIndustryResolver:
    """Resolve ``sector`` / ``industry`` from FinanceDatabase → SEC → Wikidata."""

    _MEM: Dict[str, Dict[str, str]] = {}

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
        self._disk: Optional[Dict[str, Dict[str, str]]] = None
        self._sec_ticker_map: Optional[Dict[str, str]] = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def resolve(self, ticker: str) -> Dict[str, str]:
        """Return ``{sector, industry, sic, sic_description, source}`` (subset)."""
        t = (ticker or "").upper().strip()
        if not t:
            return {}
        if t in self._MEM:
            return self._MEM[t]
        disk = self._load_disk()
        if t in disk:
            self._MEM[t] = disk[t]
            return disk[t]

        result: Dict[str, str] = {}
        if not self._offline:
            for layer in (self._from_financedatabase, self._from_sec_edgar, self._from_wikidata):
                try:
                    result = layer(t)
                except Exception as e:  # network / parse / library errors are non-fatal
                    log.debug(f"industry resolver layer {layer.__name__} failed for {t}: {e}")
                    result = {}
                if result.get("sector") or result.get("industry"):
                    break

        self._MEM[t] = result
        disk[t] = result
        self._save_disk(disk)
        return result

    def batch_get(self, tickers: Iterable[str], *, sleep: float = 0.0) -> Dict[str, Dict[str, str]]:
        """Resolve many tickers; only non-empty results are returned."""
        import time

        out: Dict[str, Dict[str, str]] = {}
        items = list(tickers)
        for i, tk in enumerate(items):
            info = self.resolve(tk)
            if info.get("sector") or info.get("industry"):
                out[(tk or "").upper()] = info
            if sleep and i + 1 < len(items):
                time.sleep(sleep)
        return out

    def resolve_identity(self, ticker: str) -> Dict[str, str]:
        """Return durable identity anchors (subset of a superset of keys).

        Reuses the same three-layer chain but additionally surfaces the SEC
        **CIK** (a stable filing identity, not a market label). Missing fields
        are omitted rather than guessed — this never fabricates an identifier.
        """
        t = (ticker or "").upper().strip()
        if not t:
            return {}
        out: Dict[str, str] = {}
        cik = self._sec_cik_for(t)
        if cik:
            out["cik"] = cik
        info = self.resolve(t)
        for key in ("sic", "sic_description", "sector", "industry", "source"):
            value = info.get(key)
            if value:
                out[key] = value
        return out

    # ------------------------------------------------------------------
    # Layer 1 — FinanceDatabase (offline, Yahoo taxonomy)
    # ------------------------------------------------------------------
    def _from_financedatabase(self, ticker: str) -> Dict[str, str]:
        try:
            import financedatabase as fd  # type: ignore
        except Exception:
            return {}
        row = None
        try:
            equities = fd.Equities()
            df = equities.select(symbol=ticker)
            if df is not None and not getattr(df, "empty", True):
                row = df.iloc[0].to_dict()
        except Exception as e:
            log.debug(f"financedatabase lookup failed for {ticker}: {e}")
            return {}
        if not row:
            return {}
        sector = _first_str(row, ("sector", "sector_", "gics_sector"))
        industry = _first_str(row, ("industry", "industry_group", "sub_industry"))
        if not (sector or industry):
            return {}
        return {"sector": sector or "", "industry": industry or "", "source": "financedatabase"}

    # ------------------------------------------------------------------
    # Layer 2 — SEC EDGAR official JSON (SIC → Yahoo via data.sic_map)
    # ------------------------------------------------------------------
    def _from_sec_edgar(self, ticker: str) -> Dict[str, str]:
        cik = self._sec_cik_for(ticker)
        if not cik:
            return {}
        r = self._get(_SEC_SUBMISSIONS_URL.format(cik=cik), headers={"User-Agent": _sec_ua()})
        if r is None or r.status_code != 200:
            return {}
        j = r.json() or {}
        sic = j.get("sic")
        sic_desc = j.get("sicDescription")
        mapped = map_sic_to_yahoo(sic, sic_desc)
        if mapped is None:
            return {}
        sector, industry = mapped
        return {
            "sector": sector,
            "industry": industry,
            "sic": str(sic) if sic is not None else "",
            "sic_description": str(sic_desc) if sic_desc else "",
            "source": "sec-edgar",
        }

    def _sec_cik_for(self, ticker: str) -> Optional[str]:
        mapping = self._load_sec_ticker_map()
        if not mapping:
            return None
        for variant in _ticker_variants(ticker):
            cik = mapping.get(variant)
            if cik:
                return str(int(cik)).zfill(10)
        return None

    def _load_sec_ticker_map(self) -> Dict[str, str]:
        if self._sec_ticker_map is not None:
            return self._sec_ticker_map
        cache_file = self._cache_path.parent / "sec_company_tickers.json"

        raw: Any = None
        if cache_file.exists():
            try:
                raw = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                raw = None
        if raw is None:
            r = self._get(_SEC_TICKERS_URL, headers={"User-Agent": _sec_ua()})
            if r is None or r.status_code != 200:
                self._sec_ticker_map = {}
                return {}
            try:
                raw = r.json()
            except Exception:
                raw = None
            if raw is None:
                self._sec_ticker_map = {}
                return {}
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(raw), encoding="utf-8")
            except Exception as e:
                log.debug(f"SEC ticker map cache write failed: {e}")

        mapping: Dict[str, str] = {}
        rows = raw.values() if isinstance(raw, dict) else raw
        try:
            for row in rows:
                tk = str(row.get("ticker") or "").upper().strip()
                cik = row.get("cik_str")
                if tk and cik is not None:
                    mapping[tk] = str(cik)
        except Exception as e:
            log.debug(f"SEC ticker map parse failed: {e}")
            mapping = {}
        self._sec_ticker_map = mapping
        return mapping

    # ------------------------------------------------------------------
    # Layer 3 — Wikidata / Wikipedia
    # ------------------------------------------------------------------
    def _from_wikidata(self, ticker: str) -> Dict[str, str]:
        label = self._wikidata_industry_label(ticker)
        if not label:
            return {}
        low = label.lower()
        for kw, sector, industry in _WIKIDATA_INDUSTRY_KEYWORDS:
            if kw in low:
                return {"sector": sector, "industry": industry, "source": "wikidata"}
        # Unknown label: still useful as free-text industry for the ML text model.
        return {"sector": "", "industry": label.title(), "source": "wikidata"}

    def _wikidata_industry_label(self, ticker: str) -> Optional[str]:
        query = (
            "SELECT ?industryLabel WHERE {"
            '  ?company p:P249 ?st .'
            f'  ?st ps:P249 "{ticker}" .'
            "  ?company wdt:P452 ?industry ."
            '  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }'
            "} LIMIT 1"
        )
        r = self._get(
            _WIKIDATA_SPARQL,
            params={"query": query, "format": "json"},
            headers={"User-Agent": _DEFAULT_UA, "Accept": "application/sparql-results+json"},
        )
        if r is None or r.status_code != 200:
            return None
        try:
            bindings = (((r.json() or {}).get("results") or {}).get("bindings")) or []
        except Exception:
            return None
        for b in bindings:
            val = ((b.get("industryLabel") or {}).get("value") or "").strip()
            if val:
                return val
        return None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _get(self, url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        client = self._client
        if client is None:
            import httpx

            client = httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
            self._client = client
        merged = {"User-Agent": _DEFAULT_UA}
        if headers:
            merged.update(headers)
        return client.get(url, params=params, headers=merged)

    def _load_disk(self) -> Dict[str, Dict[str, str]]:
        if self._disk is not None:
            return self._disk
        disk: Dict[str, Dict[str, str]] = {}
        if self._cache_path.exists():
            try:
                loaded = json.loads(self._cache_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    disk = {
                        key: value
                        for key, value in loaded.items()
                        if isinstance(key, str)
                        and isinstance(value, dict)
                        and all(isinstance(f, str) and isinstance(v, str) for f, v in value.items())
                    }
            except Exception:
                disk = {}
        self._disk = disk
        return disk

    def _save_disk(self, data: Dict[str, Dict[str, str]]) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(data, indent=0, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as e:
            log.debug(f"industry resolver cache write failed: {e}")


# ---------------------------------------------------------------------------
# module helpers
# ---------------------------------------------------------------------------
def _sec_ua() -> str:
    return os.environ.get("SEC_USER_AGENT", _DEFAULT_UA)


def _ticker_variants(ticker: str) -> tuple:
    """SEC / Yahoo ticker punctuation variants (e.g. BRK.B vs BRK-B)."""
    t = (ticker or "").upper().strip()
    seen = []
    for v in (t, t.replace("-", "."), t.replace(".", "-"), t.replace(".", ""), t.replace("-", "")):
        if v and v not in seen:
            seen.append(v)
    return tuple(seen)


def _first_str(row: Dict[str, Any], keys: tuple) -> str:
    for k in keys:
        v = row.get(k)
        if isinstance(v, str) and v.strip() and v.strip().lower() not in {"nan", "none", "n/a"}:
            return v.strip()
    return ""


def resolve_sector_industry(
    ticker: str, *, client: Any = None, offline: bool = False
) -> Dict[str, str]:
    """Convenience one-shot resolver (creates a throwaway provider)."""
    return SectorIndustryResolver(client=client, offline=offline).resolve(ticker)


__all__ = ["SectorIndustryResolver", "resolve_sector_industry"]
