"""data/secondary_profile.py - Secondary sector/industry data source (H-03).

Problem (H-03)
--------------
Yahoo's ``quoteSummary`` ``assetProfile`` module is frequently gated behind a
crumb/consent wall (HTTP 401 / empty payload), so ``sector`` / ``industry`` come
back ``None``. Missing sector/industry is the DATA-DRIVEN root cause of two
downstream defects:

  * M-16 — the ML classifier's TF-IDF text features lose the strongest
    sector/industry signal, so a fintech like SOFI has its Technology weight
    suppressed and never crosses the hybrid floor.

The fix is a feature task: impute sector/industry from a *second* source rather
than nudging classifier thresholds.

Resolution chain (first non-empty wins)
---------------------------------------
  Layer 1  Yahoo ``v1/finance/search``  — returns sector/industry in the quote
           payload and is NOT gated by the assetProfile 401.
  Layer 2  Financial Modeling Prep       — only when ``FMP_API_KEY`` is set.
  Layer 3  Alpha Vantage                 — only when ``ALPHAVANTAGE_API_KEY`` is set.
  Layer 4  (empty)                       — caller keeps its own fallback.

Results are memoised in-process and, when a ``cache_path`` is supplied, persisted
to disk so a large batch backfill is resumable and the test suite stays offline
and deterministic.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from config import get_logger

log = get_logger("data.secondary_profile")

_DEFAULT_CACHE = Path(__file__).resolve().parent.parent / ".cache" / "secondary_profile.json"
_YAHOO_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


class SecondaryProfileProvider:
    """Sector/industry fallback chain used when Yahoo assetProfile is empty."""

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

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def get_sector_industry(self, ticker: str) -> Dict[str, str]:
        """Return ``{"sector", "industry", "source"}`` or ``{}`` when unknown."""
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
            for layer in (self._from_yahoo_search, self._from_fmp, self._from_alpha_vantage):
                try:
                    result = layer(t)
                except Exception as e:  # network / parse errors are non-fatal
                    log.debug(f"secondary profile layer {layer.__name__} failed for {t}: {e}")
                    result = {}
                if result.get("sector") or result.get("industry"):
                    break

        self._MEM[t] = result
        disk[t] = result
        self._save_disk(disk)
        return result

    def batch_get(self, tickers, *, sleep: float = 0.0) -> Dict[str, Dict[str, str]]:
        """Resolve many tickers; only non-empty results are returned."""
        import time

        out: Dict[str, Dict[str, str]] = {}
        for i, tk in enumerate(tickers):
            info = self.get_sector_industry(tk)
            if info.get("sector") or info.get("industry"):
                out[tk.upper()] = info
            if sleep and i + 1 < len(tickers):
                time.sleep(sleep)
        return out

    # ------------------------------------------------------------------
    # layers
    # ------------------------------------------------------------------
    def _from_yahoo_search(self, ticker: str) -> Dict[str, str]:
        r = self._get(
            _YAHOO_SEARCH,
            params={"q": ticker, "quotesCount": "6", "newsCount": "0"},
        )
        if r is None or r.status_code != 200:
            return {}
        quotes = (r.json() or {}).get("quotes") or []
        # Prefer an exact symbol match among equity quotes.
        pick = None
        for q in quotes:
            if str(q.get("symbol", "")).upper() == ticker:
                pick = q
                break
        if pick is None:
            for q in quotes:
                if q.get("quoteType") == "EQUITY":
                    pick = q
                    break
        if pick is None:
            return {}
        sect = pick.get("sector")
        ind = pick.get("industry")
        if not (sect or ind):
            return {}
        return {
            "sector": sect or "",
            "industry": ind or "",
            "source": "yahoo-search",
        }

    def _from_fmp(self, ticker: str) -> Dict[str, str]:
        key = os.environ.get("FMP_API_KEY")
        if not key:
            return {}
        r = self._get(
            "https://financialmodelingprep.com/api/v3/profile/" + ticker,
            params={"apikey": key},
        )
        if r is None or r.status_code != 200:
            return {}
        rows = r.json() or []
        row = rows[0] if isinstance(rows, list) and rows else {}
        sect, ind = row.get("sector"), row.get("industry")
        if not (sect or ind):
            return {}
        return {"sector": sect or "", "industry": ind or "", "source": "fmp"}

    def _from_alpha_vantage(self, ticker: str) -> Dict[str, str]:
        key = os.environ.get("ALPHAVANTAGE_API_KEY")
        if not key:
            return {}
        r = self._get(
            "https://www.alphavantage.co/query",
            params={"function": "OVERVIEW", "symbol": ticker, "apikey": key},
        )
        if r is None or r.status_code != 200:
            return {}
        row = r.json() or {}
        sect, ind = row.get("Sector"), row.get("Industry")
        if not (sect or ind):
            return {}
        return {
            "sector": _yahoo_sector(sect),
            "industry": ind or "",
            "source": "alpha-vantage",
        }

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

    def _load_disk(self) -> Dict[str, Dict[str, str]]:
        if self._disk is not None:
            return self._disk
        if self._cache_path.exists():
            try:
                self._disk = json.loads(self._cache_path.read_text(encoding="utf-8"))
            except Exception:
                self._disk = {}
        else:
            self._disk = {}
        return self._disk

    def _save_disk(self, data: Dict[str, Dict[str, str]]) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(data, indent=0, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as e:
            log.debug(f"secondary profile cache write failed: {e}")


# Alpha Vantage uses its own sector taxonomy (e.g. "Financials") — map to the
# Yahoo canonical sectors the rest of the engine expects.
_AV_TO_YAHOO = {
    "Financials": "Financial Services",
    "Information Technology": "Technology",
    "Health Care": "Healthcare",
    "Consumer Discretionary": "Consumer Cyclical",
    "Consumer Staples": "Consumer Defensive",
    "Materials": "Basic Materials",
    "Real Estate": "Real Estate",
    "Communication Services": "Communication Services",
    "Energy": "Energy",
    "Industrials": "Industrials",
    "Utilities": "Utilities",
}


def _yahoo_sector(av_sector: str) -> str:
    return _AV_TO_YAHOO.get(av_sector, av_sector)


__all__ = ["SecondaryProfileProvider"]
