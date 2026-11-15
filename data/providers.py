"""
data/providers.py - Data Providers (Yahoo Finance; optional explicit synthetic fallback)
"""
from __future__ import annotations

import asyncio
import math
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from config import DEFAULT_DCF_CONFIG, YAHOO_ALLOW_SYNTHETIC_FALLBACK, DataSource, get_logger
from data.errors import UnknownSyntheticTickerError, YahooFinanceUnavailableError
from data.models import (
    DataQualityFlags,
    FinancialData,
    FinancialStatement,
    MarketData,
)

log = get_logger("data.providers")


def _safe_err(e: Exception) -> str:
    s = str(e)
    try:
        s.encode("ascii")
        return s
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s.encode("ascii", "replace").decode("ascii")


# ---------------------------------------------------------------------------
# Synthetic Data - High quality parameterized fixtures for 10 typical tickers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Treasury Yield Curve Provider (U.S. Department of the Treasury, CSV feed)
#   - Source: home.treasury.gov (user-specified URL)
#   - Cache:  .cache/treasury_yield/treasury_yield_{YYYYMMDD}.json (4h TTL)
#   - Output: Dict of {tenor_name: rate_decimal}, e.g. {"10 Yr": 0.0425}
# ---------------------------------------------------------------------------

_TREASURY_CSV_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/all/all?"
    "type=daily_treasury_yield_curve&page&_format=csv"
)
# Treasury.gov also publishes an official XML feed at:
#   https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve
_TREASURY_XML_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/pages/xml?data=daily_treasury_yield_curve"
)
# Fallback: Yahoo Finance ticker for 10-Year Treasury Yield
_YAHOO_TNX_TICKER = "^TNX"

_TREASURY_YIELD_CACHE_SUBDIR = "treasury_yield"
_TREASURY_YIELD_TTL_SECONDS = 4 * 3600  # 4 hours, aligned with Yahoo cache


_TENOR_COLUMN_NORMALIZER: Dict[str, str] = {
    # Map Treasury CSV column headers → canonical tenor key
    "1 Mo": "1 Mo",
    "2 Mo": "2 Mo",
    "3 Mo": "3 Mo",
    "4 Mo": "4 Mo",
    "6 Mo": "6 Mo",
    "1 Yr": "1 Yr",
    "2 Yr": "2 Yr",
    "3 Yr": "3 Yr",
    "5 Yr": "5 Yr",
    "7 Yr": "7 Yr",
    "10 Yr": "10 Yr",
    "20 Yr": "20 Yr",
    "30 Yr": "30 Yr",
    # Old treasury CSV used "10 Yr" etc.; some views use "10yr"
    "1mo": "1 Mo", "2mo": "2 Mo", "3mo": "3 Mo", "4mo": "4 Mo", "6mo": "6 Mo",
    "1yr": "1 Yr", "2yr": "2 Yr", "3yr": "3 Yr", "5yr": "5 Yr", "7yr": "7 Yr",
    "10yr": "10 Yr", "20yr": "20 Yr", "30yr": "30 Yr",
    "1M": "1 Mo", "2M": "2 Mo", "3M": "3 Mo", "6M": "6 Mo",
    "1Y": "1 Yr", "2Y": "2 Yr", "3Y": "3 Yr", "5Y": "5 Yr", "7Y": "7 Yr",
    "10Y": "10 Yr", "20Y": "20 Yr", "30Y": "30 Yr",
}


class TreasuryYieldProvider:
    """Download & cache the daily U.S. Treasury par yield curve from treasury.gov.

    Typical usage:
        r = TreasuryYieldProvider()
        curve = r.get_yield_curve()          # → {"10 Yr": 0.0425, ...}
        r10 = curve.get("10 Yr")             # → 0.0425 (4.25%)
    """

    _CACHE_DIR_NAME = ".cache"
    _CACHE_TTL_SECONDS = _TREASURY_YIELD_TTL_SECONDS
    _CSV_URL = _TREASURY_CSV_URL

    # Full browser-grade headers for treasury.gov (avoids 403 Forbidden from WAF)
    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0"
    )
    _EXTRA_HEADERS_CSV = {
        "Accept": "text/csv,application/csv,text/plain,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "max-age=0",
        "Referer": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Chromium";v="129", "Not=A?Brand";v="8", "Microsoft Edge";v="129"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1",
    }
    _EXTRA_HEADERS_XML = {
        "Accept": "application/xml,text/xml,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    }

    def __init__(self, cache_enabled: bool = True) -> None:
        self.cache_enabled = cache_enabled
        self._cache_dir: Optional[str] = None
        cache_root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            self._CACHE_DIR_NAME, _TREASURY_YIELD_CACHE_SUBDIR,
        )
        cache_root = os.path.normpath(cache_root)
        try:
            os.makedirs(cache_root, exist_ok=True)
            self._cache_dir = cache_root
        except Exception as e:
            log.warning(f"Treasury cache dir unavailable ({_safe_err(e)}); running cache disabled.")
            self._cache_dir = None
            self.cache_enabled = False

    # ------------------------------------------------------------------
    # Cache helpers (mirror YahooFinanceProvider: atomic tmp+replace, 4h TTL)
    # ------------------------------------------------------------------
    def _cache_path(self) -> Optional[str]:
        if not self.cache_enabled or not self._cache_dir:
            return None
        today = datetime.utcnow().strftime("%Y%m%d")
        return os.path.join(self._cache_dir, f"treasury_yield_{today}.json")

    def _cache_read(self) -> Optional[Dict[str, Any]]:
        path = self._cache_path()
        if not path or not os.path.exists(path):
            return None
        try:
            st = os.stat(path)
            age = (datetime.utcnow() - datetime.utcfromtimestamp(st.st_mtime)).total_seconds()
            if age > self._CACHE_TTL_SECONDS:
                try:
                    os.remove(path)
                except Exception:
                    pass
                return None
            import json as _json
            with open(path, "r", encoding="utf-8") as f:
                blob = _json.load(f)
            log.debug(f"Treasury yield cache hit (age={age/60:.1f}min)")
            return blob
        except Exception as e:
            log.warning(f"Treasury cache read failed: {_safe_err(e)}")
            return None

    def _cache_write(self, blob: Dict[str, Any]) -> None:
        path = self._cache_path()
        if not path:
            return
        try:
            import json as _json
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(blob, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            log.warning(f"Treasury cache write failed: {_safe_err(e)}")

    # ------------------------------------------------------------------
    # HTTP + CSV parse
    # ------------------------------------------------------------------
    @classmethod
    def _build_client(cls):
        import httpx
        return httpx.Client(
            timeout=httpx.Timeout(25.0, connect=12.0),
            follow_redirects=True,
            headers={"User-Agent": cls._USER_AGENT},
            trust_env=False,
            http2=True,
        )

    @staticmethod
    def _parse_treasury_csv(raw_text: str) -> Optional[Dict[str, Any]]:
        """Parse treasury.gov CSV into {tenor: decimal_rate} dict.

        CSV format (first row = headers, first column = Date MM/DD/YYYY):
            Date,1 Mo,2 Mo,3 Mo,6 Mo,1 Yr,2 Yr,3 Yr,5 Yr,7 Yr,10 Yr,20 Yr,30 Yr
            09/19/2026,5.25,5.22,5.18,5.05,4.98,4.75,4.61,4.42,4.35,4.28,4.31,4.30
        We take the *last* non-empty data row (most recent business day).
        """
        if not raw_text:
            return None
        # Normalize newlines, split
        lines = [ln for ln in raw_text.replace("\r", "\n").split("\n") if ln.strip()]
        if len(lines) < 2:
            return None

        # Header row: first non-empty line (CSV can have a BOM, so strip it)
        import csv as _csv
        import io
        reader = _csv.reader(io.StringIO(raw_text))
        rows = [r for r in reader if any((c or "").strip() for c in r)]
        if len(rows) < 2:
            return None
        header = [c.strip().lstrip("\ufeff") for c in rows[0]]
        if not header or "Date" not in header[0]:
            return None

        # Find most recent data row → last row with len == len(header)
        data_rows = [r for r in rows[1:] if len(r) == len(header)]
        if not data_rows:
            return None
        latest_row = data_rows[-1]
        date_str = latest_row[0].strip() or ""

        rates: Dict[str, float] = {}
        for col_name, raw_val in zip(header[1:], latest_row[1:]):
            col_clean = col_name.strip()
            try:
                val = float((raw_val or "").strip())
            except (TypeError, ValueError):
                continue
            if val <= 0 or val > 50:
                # Treasury yields never hit 50% — malformed
                continue
            # CSV values are *percents* (4.25 means 4.25%), store as decimal
            rate_decimal = val / 100.0
            # Canonical tenor name
            canonical = _TENOR_COLUMN_NORMALIZER.get(col_clean, col_clean)
            rates[canonical] = rate_decimal

        if not rates:
            return None
        return {
            "source": "U.S. Department of the Treasury (home.treasury.gov CSV)",
            "as_of_date": date_str,
            "downloaded_at_utc": datetime.utcnow().isoformat(),
            "rates": rates,  # {"10 Yr": 0.0425, ...}
        }

    @staticmethod
    def _parse_treasury_xml(raw_text: str) -> Optional[Dict[str, Any]]:
        """Parse the official Treasury.gov XML feed into {tenor: rate_decimal}.

        The feed structure looks like (simplified):
            <m:properties>
                <d:NEW_DATE>2026-09-19T00:00:00</d:NEW_DATE>
                <d:BC_1MONTH>5.25</d:BC_1MONTH>
                <d:BC_3MONTH>5.18</d:BC_3MONTH>
                <d:BC_6MONTH>5.05</d:BC_6MONTH>
                <d:BC_1YEAR>4.98</d:BC_1YEAR>
                <d:BC_2YEAR>4.75</d:BC_2YEAR>
                <d:BC_3YEAR>4.61</d:BC_3YEAR>
                <d:BC_5YEAR>4.42</d:BC_5YEAR>
                <d:BC_7YEAR>4.35</d:BC_7YEAR>
                <d:BC_10YEAR>4.28</d:BC_10YEAR>
                <d:BC_20YEAR>4.31</d:BC_20YEAR>
                <d:BC_30YEAR>4.30</d:BC_30YEAR>
            </m:properties>
        We take the *last* <m:properties> entry = most recent day.
        """
        if not raw_text:
            return None
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(raw_text)
        except Exception as e:
            log.warning(f"Treasury XML parse failed (invalid XML): {_safe_err(e)}")
            return None

        # Namespace mapping: atom + m (metadata) + d (data)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
            "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
        }
        # Try several XPath variants (some feeds use <entry><content><properties> directly)
        props = root.findall(".//m:properties", ns)
        if not props:
            props = root.findall(".//{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties")
        if not props:
            return None
        last = props[-1]

        # Map Treasury XML field names → canonical tenor keys
        field_2_tenor: Dict[str, str] = {
            "BC_1MONTH": "1 Mo",
            "BC_2MONTH": "2 Mo",
            "BC_3MONTH": "3 Mo",
            "BC_4MONTH": "4 Mo",
            "BC_6MONTH": "6 Mo",
            "BC_1YEAR": "1 Yr",
            "BC_2YEAR": "2 Yr",
            "BC_3YEAR": "3 Yr",
            "BC_5YEAR": "5 Yr",
            "BC_7YEAR": "7 Yr",
            "BC_10YEAR": "10 Yr",
            "BC_20YEAR": "20 Yr",
            "BC_30YEAR": "30 Yr",
        }
        rates: Dict[str, float] = {}
        date_str = ""
        for child in last:
            tag = child.tag
            # Strip namespace prefix
            local = tag.split("}", 1)[1] if "}" in tag else tag
            if local == "NEW_DATE":
                date_str = (child.text or "").split("T")[0]
                continue
            if local not in field_2_tenor:
                continue
            raw = (child.text or "").strip()
            if not raw:
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                continue
            if val <= 0 or val > 50:
                continue
            rates[field_2_tenor[local]] = val / 100.0  # percent → decimal

        if not rates:
            return None
        return {
            "source": "U.S. Department of the Treasury (home.treasury.gov official XML feed)",
            "as_of_date": date_str or "unknown",
            "downloaded_at_utc": datetime.utcnow().isoformat(),
            "rates": rates,
        }

    def _fallback_via_yahoo_tnx(self) -> Optional[Dict[str, Any]]:
        """Last-resort fallback: treat Yahoo Finance ^TNX ticker price as 10Y yield percent.

        Returns the same dict shape as get_yield_curve (only 10 Yr populated).
        """
        try:
            import asyncio
            import concurrent.futures
            yp = YahooFinanceProvider(use_fallback=False, cache_enabled=True)
            fut = yp.get_financial_data(_YAHOO_TNX_TICKER)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    data = pool.submit(asyncio.run, fut).result()
            else:
                data = asyncio.run(fut)
            price = getattr(data.market, "current_price", None) if data and data.market else None
            if price is None:
                return None
            p = float(price)
            # ^TNX on Yahoo is reported as *percent* (e.g. 4.25 = 4.25%)
            if 0.1 <= p <= 20.0:
                r10 = p / 100.0
                return {
                    "source": f"Yahoo Finance {_YAHOO_TNX_TICKER} last price (fallback for 10Y only)",
                    "as_of_date": datetime.utcnow().strftime("%Y-%m-%d"),
                    "downloaded_at_utc": datetime.utcnow().isoformat(),
                    "rates": {"10 Yr": r10},
                }
        except Exception as e:
            log.warning(f"Treasury fallback via Yahoo ^TNX failed: {_safe_err(e)}")
        return None

    # ------------------------------------------------------------------
    # Public synchronous API
    # ------------------------------------------------------------------
    def get_yield_curve(self) -> Optional[Dict[str, Any]]:
        """Return the latest Treasury yield curve {rates, as_of_date, source}.

        Data source priority (first one that returns non-empty curve wins):
          1. home.treasury.gov CSV download (CSV API URL)
          2. home.treasury.gov official XML feed
          3. Yahoo Finance ^TNX (10Y only, last-resort)
        Cached in .cache/treasury_yield/ with 4h TTL (any source).
        Returns None on total failure (caller falls back to DCFConfig default Rf).
        """
        cached = self._cache_read()
        if cached is not None:
            return cached

        text = None
        parsed: Optional[Dict[str, Any]] = None
        src_used = ""

        # --- Attempt 1: CSV URL (browser-grade headers) ---
        try:
            with self._build_client() as client:
                headers = dict(self._EXTRA_HEADERS_CSV)
                headers["User-Agent"] = self._USER_AGENT
                resp = client.get(self._CSV_URL, headers=headers)
                if resp.status_code == 200:
                    text = resp.text
        except Exception as e:
            log.info(f"Treasury CSV attempt failed: {_safe_err(e)}")

        if text:
            parsed = self._parse_treasury_csv(text)
            src_used = "CSV" if parsed else ""

        # --- Attempt 2: XML feed ---
        if parsed is None:
            try:
                with self._build_client() as client:
                    headers = dict(self._EXTRA_HEADERS_XML)
                    headers["User-Agent"] = self._USER_AGENT
                    resp = client.get(_TREASURY_XML_URL, headers=headers)
                    if resp.status_code == 200:
                        xml_text = resp.text
                        parsed = self._parse_treasury_xml(xml_text)
                        src_used = "XML" if parsed else ""
            except Exception as e:
                log.info(f"Treasury XML attempt failed: {_safe_err(e)}")

        # --- Attempt 3: Yahoo Finance ^TNX (10Y only) ---
        if parsed is None:
            parsed = self._fallback_via_yahoo_tnx()
            src_used = "Yahoo ^TNX fallback" if parsed else ""

        if parsed is None:
            log.warning(
                "Treasury yield — ALL 3 sources failed (CSV 403, XML, Yahoo ^TNX). "
                "WACC Step 1 will use DCFConfig default Rf."
            )
            return None

        parsed["_source_pipeline"] = src_used
        self._cache_write(parsed)
        return parsed

    # Convenience helpers
    def get_10y_yield(self) -> Optional[float]:
        """Return 10-Year Treasury yield as decimal, or None if unavailable."""
        curve = self.get_yield_curve()
        if not curve:
            return None
        rates = curve.get("rates") or {}
        return rates.get("10 Yr")

    def get_2y_yield(self) -> Optional[float]:
        curve = self.get_yield_curve()
        if not curve:
            return None
        return (curve.get("rates") or {}).get("2 Yr")

    def get_3m_yield(self) -> Optional[float]:
        curve = self.get_yield_curve()
        if not curve:
            return None
        return (curve.get("rates") or {}).get("3 Mo")


# ---------------------------------------------------------------------------
# Synthetic Data - High quality parameterized fixtures for 10 typical tickers
# ---------------------------------------------------------------------------

SYNTHETIC_DATA: Dict[str, dict] = {

    "AAPL": {
        "name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics",
        "currency": "USD", "price": 180.5, "shares": 15_200_000_000,
        "total_debt": 108_000_000_000, "cash": 165_000_000_000, "book_value": 62_000_000_000,
        "beta": 1.28, "trailing_pe": 29.5, "ev_to_ebitda": 23.8, "price_to_book": 45.2,
        "annual_revenue": [383_285_000_000, 394_328_000_000, 365_817_000_000, 363_408_000_000, 274_515_000_000],
        "annual_ebit": [114_301_000_000, 119_437_000_000, 111_445_000_000, 108_874_000_000, 66_288_000_000],
        "annual_ebitda": [130_541_000_000, 135_963_000_000, 125_820_000_000, 123_096_000_000, 77_344_000_000],
        "annual_ni": [96_995_000_000, 90_146_000_000, 99_803_000_000, 94_680_000_000, 57_411_000_000],
        "annual_da": [16_240_000_000, 16_526_000_000, 14_375_000_000, 14_222_000_000, 11_056_000_000],
        "annual_capex": [11_084_000_000, 10_959_000_000, 11_241_000_000, 7_309_000_000, 6_831_000_000],
        "annual_ocf": [110_543_000_000, 122_151_000_000, 110_773_000_000, 104_038_000_000, 80_674_000_000],
        "annual_fcf": [99_459_000_000, 111_192_000_000, 99_532_000_000, 96_729_000_000, 73_843_000_000],
        "years": ["2023-09-30", "2022-09-30", "2021-09-30", "2020-09-30", "2019-09-30"],
        "interest": [3_933_000_000, 2_871_000_000, 2_687_000_000, 2_873_000_000, 3_576_000_000],
        "tax": [16_741_000_000, 19_300_000_000, 14_527_000_000, 9_680_000_000, 10_481_000_000],
    },
    "MSFT": {
        "name": "Microsoft Corp.", "sector": "Technology", "industry": "Software",
        "currency": "USD", "price": 415.0, "shares": 7_430_000_000,
        "total_debt": 79_000_000_000, "cash": 84_000_000_000, "book_value": 242_000_000_000,
        "beta": 0.91, "trailing_pe": 35.8, "ev_to_ebitda": 27.1, "price_to_book": 12.6,
        "annual_revenue": [211_915_000_000, 198_270_000_000, 168_088_000_000, 143_015_000_000, 125_843_000_000],
        "annual_ebit": [88_813_000_000, 80_632_000_000, 69_916_000_000, 53_218_000_000, 43_685_000_000],
        "annual_ebitda": [99_054_000_000, 90_514_000_000, 78_088_000_000, 60_993_000_000, 51_741_000_000],
        "annual_ni": [72_361_000_000, 72_738_000_000, 61_271_000_000, 44_281_000_000, 39_240_000_000],
        "annual_da": [10_241_000_000, 9_882_000_000, 8_172_000_000, 7_775_000_000, 8_056_000_000],
        "annual_capex": [26_014_000_000, 23_480_000_000, 20_900_000_000, 15_441_000_000, 13_925_000_000],
        "annual_ocf": [87_582_000_000, 89_031_000_000, 76_740_000_000, 60_675_000_000, 52_185_000_000],
        "annual_fcf": [61_568_000_000, 65_551_000_000, 55_840_000_000, 45_234_000_000, 38_260_000_000],
        "years": ["2023-06-30", "2022-06-30", "2021-06-30", "2020-06-30", "2019-06-30"],
        "interest": [2_290_000_000, 2_089_000_000, 2_075_000_000, 2_192_000_000, 2_686_000_000],
        "tax": [16_952_000_000, 15_139_000_000, 9_831_000_000, 8_755_000_000, 4_448_000_000],
    },
    "NVDA": {
        "name": "NVIDIA Corp.", "sector": "Technology", "industry": "Semiconductors",
        "currency": "USD", "price": 900.0, "shares": 2_450_000_000,
        "total_debt": 9_800_000_000, "cash": 58_000_000_000, "book_value": 41_000_000_000,
        "beta": 1.73, "trailing_pe": 72.3, "ev_to_ebitda": 64.5, "price_to_book": 56.0,
        "annual_revenue": [60_917_000_000, 26_974_000_000, 26_914_000_000, 16_675_000_000, 10_918_000_000],
        "annual_ebit": [34_031_000_000, 4_223_000_000, 9_917_000_000, 4_523_000_000, 2_799_000_000],
        "annual_ebitda": [35_818_000_000, 6_395_000_000, 12_172_000_000, 6_428_000_000, 4_355_000_000],
        "annual_ni": [29_760_000_000, 4_368_000_000, 9_752_000_000, 4_332_000_000, 2_796_000_000],
        "annual_da": [1_787_000_000, 2_172_000_000, 2_255_000_000, 1_905_000_000, 1_556_000_000],
        "annual_capex": [3_349_000_000, 3_412_000_000, 2_802_000_000, 949_000_000, 652_000_000],
        "annual_ocf": [27_535_000_000, 7_160_000_000, 9_081_000_000, 5_850_000_000, 3_746_000_000],
        "annual_fcf": [24_186_000_000, 3_748_000_000, 6_279_000_000, 4_901_000_000, 3_094_000_000],
        "years": ["2024-01-28", "2023-01-29", "2022-01-30", "2021-01-31", "2020-01-26"],
        "interest": [134_000_000, 264_000_000, 299_000_000, 262_000_000, 202_000_000],
        "tax": [4_055_000_000, 192_000_000, 667_000_000, 108_000_000, 77_000_000],
    },
    "JPM": {
        "name": "JPMorgan Chase & Co.", "sector": "Financial Services", "industry": "Banks - Diversified",
        "currency": "USD", "price": 195.0, "shares": 2_950_000_000,
        "total_debt": 3_100_000_000_000, "cash": 1_430_000_000_000, "book_value": 402_000_000_000,
        "beta": 1.20, "trailing_pe": 11.4, "ev_to_ebitda": None, "price_to_book": 1.43,
        # JPM pays a dividend (~2.3%); Bank DDM requires an actual dividend stream.
        "dividend_yield": 0.023,
        "annual_revenue": [157_813_000_000, 128_678_000_000, 125_305_000_000, 119_543_000_000, 115_627_000_000],
        "annual_ebit": [72_278_000_000, 48_964_000_000, 52_825_000_000, 47_367_000_000, 48_651_000_000],
        "annual_ebitda": [None, None, None, None, None],
        "annual_ni": [49_551_000_000, 31_559_000_000, 36_431_000_000, 29_131_000_000, 36_431_000_000],
        "annual_da": [14_200_000_000, 13_500_000_000, 13_000_000_000, 12_000_000_000, 11_000_000_000],
        "annual_capex": [4_200_000_000, 4_000_000_000, 3_700_000_000, 3_400_000_000, 3_100_000_000],
        "annual_ocf": [68_000_000_000, 46_000_000_000, 52_000_000_000, 44_000_000_000, 45_000_000_000],
        "annual_fcf": [63_800_000_000, 42_000_000_000, 48_300_000_000, 40_600_000_000, 41_900_000_000],
        "years": ["2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"],
        "interest": [77_479_000_000, 57_128_000_000, 37_923_000_000, 27_266_000_000, 35_449_000_000],
        "tax": [14_356_000_000, 8_613_000_000, 10_380_000_000, 7_118_000_000, 8_480_000_000],
    },
    "PLD": {
        "name": "Prologis Inc.", "sector": "Real Estate", "industry": "REIT - Industrial",
        "currency": "USD", "price": 155.0, "shares": 1_720_000_000,
        "total_debt": 42_000_000_000, "cash": 6_700_000_000, "book_value": 58_000_000_000,
        "beta": 1.01, "trailing_pe": 33.0, "ev_to_ebitda": 28.4, "price_to_book": 4.6,
        "annual_revenue": [7_760_000_000, 6_660_000_000, 5_900_000_000, 4_850_000_000, 3_736_000_000],
        "annual_ebit": [3_976_000_000, 3_328_000_000, 2_913_000_000, 2_281_000_000, 1_814_000_000],
        "annual_ebitda": [6_308_000_000, 5_450_000_000, 4_792_000_000, 3_886_000_000, 3_046_000_000],
        "annual_ni": [2_941_000_000, 2_354_000_000, 2_013_000_000, 1_476_000_000, 1_040_000_000],
        "annual_da": [2_332_000_000, 2_122_000_000, 1_879_000_000, 1_605_000_000, 1_232_000_000],
        "annual_capex": [3_750_000_000, 3_100_000_000, 2_600_000_000, 1_850_000_000, 1_500_000_000],
        "annual_ocf": [5_500_000_000, 4_700_000_000, 4_100_000_000, 3_350_000_000, 2_600_000_000],
        "annual_fcf": [1_750_000_000, 1_600_000_000, 1_500_000_000, 1_500_000_000, 1_100_000_000],
        "years": ["2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"],
        "interest": [1_250_000_000, 1_100_000_000, 900_000_000, 850_000_000, 800_000_000],
        "tax": [58_000_000, 44_000_000, 39_000_000, 27_000_000, 23_000_000],
    },
    "NOW": {
        "name": "ServiceNow Inc.", "sector": "Technology", "industry": "Software - Application",
        "currency": "USD", "price": 720.0, "shares": 300_000_000,
        "total_debt": 5_600_000_000, "cash": 14_300_000_000, "book_value": 10_500_000_000,
        "beta": 1.18, "trailing_pe": None, "ev_to_ebitda": 46.2, "price_to_book": 20.5,
        "annual_revenue": [8_866_000_000, 7_430_000_000, 6_061_000_000, 4_720_000_000, 3_645_000_000],
        "annual_ebit": [352_000_000, 688_000_000, 554_000_000, 142_000_000, -408_000_000],
        "annual_ebitda": [1_317_000_000, 1_524_000_000, 1_333_000_000, 882_000_000, 360_000_000],
        "annual_ni": [-151_000_000, 250_000_000, 209_000_000, -80_000_000, -614_000_000],
        "annual_da": [965_000_000, 836_000_000, 779_000_000, 740_000_000, 768_000_000],
        "annual_capex": [320_000_000, 280_000_000, 240_000_000, 180_000_000, 160_000_000],
        "annual_ocf": [1_900_000_000, 1_700_000_000, 1_360_000_000, 1_050_000_000, 850_000_000],
        "annual_fcf": [1_580_000_000, 1_420_000_000, 1_120_000_000, 870_000_000, 690_000_000],
        "years": ["2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"],
        "interest": [170_000_000, 156_000_000, 130_000_000, 112_000_000, 100_000_000],
        "tax": [92_000_000, 60_000_000, 48_000_000, 30_000_000, 0],
    },
}
# NOTE (Phase 4 / Session #22): a previous `SYNTHETIC_DATA.setdefault(t,
# SYNTHETIC_DATA["AAPL"].copy())` loop silently substituted **Apple's**
# financials for AMZN / GOOGL / META / TSLA. That is a fabricated-input
# violation (constraint #4) and a shallow-copy aliasing hazard (the borrowed
# ticker shared AAPL's mutable list objects). It has been removed. Unknown
# tickers now raise `UnknownSyntheticTickerError` (the honest "refusing to
# substitute another company's numbers" behaviour), and the Phase-4 regression
# universe gets distinct, explicitly-labelled fixtures below.


# ---------------------------------------------------------------------------
# Asset-structure coverage fixtures (Session #10).
#   * NBIS — AI/Cloud Infrastructure build-out: capital-intensive, negative FCF,
#     loss-making, high growth. FCF-based models collapse → exercises the
#     Replacement-cost NAV coverage anchor.
#   * AMT  — tower REIT: high EBITDA margin, heavy D&A, REIT-NAV route.
#   * XOM  — integrated Energy: cyclical, EV/EBITDA + P/E anchored.
# ---------------------------------------------------------------------------
SYNTHETIC_DATA["NBIS"] = {
    "name": "Nebius Group N.V.", "sector": "Technology",
    "industry": "Software - Infrastructure",
    "currency": "USD", "price": 41.0, "shares": 200_000_000,
    "total_debt": 1_000_000_000, "cash": 2_000_000_000, "book_value": 1_500_000_000,
    "beta": 2.60, "trailing_pe": None, "ev_to_ebitda": None, "price_to_book": 5.5,
    "annual_revenue": [120_000_000, 60_000_000, 30_000_000, 15_000_000, 8_000_000],
    "annual_ebit": [-200_000_000, -140_000_000, -90_000_000, -60_000_000, -35_000_000],
    "annual_ebitda": [20_000_000, 10_000_000, 5_000_000, 2_000_000, 1_000_000],
    "annual_ni": [-400_000_000, -250_000_000, -150_000_000, -100_000_000, -50_000_000],
    "annual_da": [220_000_000, 150_000_000, 95_000_000, 62_000_000, 36_000_000],
    "annual_capex": [2_500_000_000, 1_500_000_000, 800_000_000, 400_000_000, 200_000_000],
    "annual_ocf": [-300_000_000, -200_000_000, -120_000_000, -80_000_000, -40_000_000],
    "annual_fcf": [-2_800_000_000, -1_700_000_000, -920_000_000, -480_000_000, -240_000_000],
    "years": ["2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"],
    "interest": [40_000_000, 25_000_000, 15_000_000, 8_000_000, 4_000_000],
    "tax": [0, 0, 0, 0, 0],
}
SYNTHETIC_DATA["AMT"] = {
    "name": "American Tower Corp.", "sector": "Real Estate",
    "industry": "REIT - Specialty",
    "currency": "USD", "price": 200.0, "shares": 467_000_000,
    "total_debt": 40_000_000_000, "cash": 2_000_000_000, "book_value": 4_000_000_000,
    "beta": 0.72, "trailing_pe": 40.0, "ev_to_ebitda": 22.0, "price_to_book": 23.0,
    "annual_revenue": [11_100_000_000, 10_700_000_000, 9_360_000_000, 8_040_000_000, 7_580_000_000],
    "annual_ebit": [4_500_000_000, 4_200_000_000, 3_600_000_000, 3_100_000_000, 2_900_000_000],
    "annual_ebitda": [7_100_000_000, 6_800_000_000, 5_900_000_000, 5_100_000_000, 4_800_000_000],
    "annual_ni": [1_500_000_000, 1_700_000_000, 2_500_000_000, 1_600_000_000, 2_200_000_000],
    "annual_da": [2_600_000_000, 2_600_000_000, 2_300_000_000, 2_000_000_000, 1_900_000_000],
    "annual_capex": [1_800_000_000, 1_700_000_000, 1_600_000_000, 1_400_000_000, 1_500_000_000],
    "annual_ocf": [4_600_000_000, 4_300_000_000, 3_900_000_000, 3_400_000_000, 3_200_000_000],
    "annual_fcf": [2_800_000_000, 2_600_000_000, 2_300_000_000, 2_000_000_000, 1_700_000_000],
    "years": ["2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"],
    "interest": [1_400_000_000, 1_200_000_000, 1_000_000_000, 950_000_000, 900_000_000],
    "tax": [200_000_000, 180_000_000, 150_000_000, 120_000_000, 110_000_000],
}
SYNTHETIC_DATA["XOM"] = {
    "name": "Exxon Mobil Corp.", "sector": "Energy",
    "industry": "Oil & Gas Integrated",
    "currency": "USD", "price": 110.0, "shares": 4_000_000_000,
    "total_debt": 40_000_000_000, "cash": 30_000_000_000, "book_value": 200_000_000_000,
    "beta": 0.90, "trailing_pe": 13.0, "ev_to_ebitda": 7.0, "price_to_book": 2.0,
    "annual_revenue": [344_600_000_000, 413_700_000_000, 285_600_000_000, 181_500_000_000, 264_900_000_000],
    "annual_ebit": [43_000_000_000, 75_000_000_000, 31_000_000_000, -25_000_000_000, 20_000_000_000],
    "annual_ebitda": [62_000_000_000, 90_000_000_000, 45_000_000_000, -8_000_000_000, 40_000_000_000],
    "annual_ni": [36_000_000_000, 55_700_000_000, 23_000_000_000, -22_400_000_000, 14_300_000_000],
    "annual_da": [20_000_000_000, 24_000_000_000, 22_000_000_000, 21_000_000_000, 20_000_000_000],
    "annual_capex": [24_000_000_000, 22_000_000_000, 16_000_000_000, 21_000_000_000, 31_000_000_000],
    "annual_ocf": [55_000_000_000, 76_000_000_000, 48_000_000_000, 14_000_000_000, 30_000_000_000],
    "annual_fcf": [31_000_000_000, 54_000_000_000, 32_000_000_000, -7_000_000_000, -1_000_000_000],
    "years": ["2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"],
    "interest": [800_000_000, 800_000_000, 1_000_000_000, 1_200_000_000, 900_000_000],
    "tax": [12_000_000_000, 20_000_000_000, 7_000_000_000, -5_000_000_000, 6_000_000_000],
}
# CRWV — CoreWeave: AI/Cloud neocloud build-out. Extreme capital intensity
# (capex ≫ revenue), deeply negative FCF and net income, heavy debt, high beta.
# This is the archetypal "second leg" case: asset anchor (Replacement NAV) plus
# unit-economics earnings-power anchor (EV/Sales Unit Econ) both apply.
SYNTHETIC_DATA["CRWV"] = {
    "name": "CoreWeave, Inc.", "sector": "Technology",
    "industry": "Software - Infrastructure",
    "currency": "USD", "price": 75.0, "shares": 480_000_000,
    "total_debt": 9_000_000_000, "cash": 1_500_000_000, "book_value": 2_000_000_000,
    "beta": 2.60, "trailing_pe": None, "ev_to_ebitda": None, "price_to_book": 18.0,
    "annual_revenue": [1_915_000_000, 229_000_000, 16_000_000, 5_000_000, 2_000_000],
    "annual_ebit": [-1_100_000_000, -600_000_000, -50_000_000, -15_000_000, -5_000_000],
    "annual_ebitda": [500_000_000, 100_000_000, -30_000_000, -10_000_000, -3_000_000],
    "annual_ni": [-863_000_000, -594_000_000, -35_000_000, -10_000_000, -3_000_000],
    "annual_da": [1_200_000_000, 300_000_000, 30_000_000, 8_000_000, 2_000_000],
    "annual_capex": [7_600_000_000, 2_200_000_000, 300_000_000, 60_000_000, 15_000_000],
    "annual_ocf": [-1_200_000_000, -400_000_000, -40_000_000, -12_000_000, -4_000_000],
    "annual_fcf": [-8_800_000_000, -2_600_000_000, -340_000_000, -72_000_000, -19_000_000],
    "years": ["2024-12-31", "2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31"],
    "interest": [400_000_000, 150_000_000, 10_000_000, 3_000_000, 1_000_000],
    "tax": [0, 0, 0, 0, 0],
}


# ---------------------------------------------------------------------------
# Phase-4 regression universe (Session #22).
# Each entry below is a *labelled synthetic archetype* used ONLY for
# deterministic offline regression. It is NOT real market data and must never
# back a production valuation or an external report. They are deliberately
# distinct (never an AAPL template) so that classification, model routing,
# scenario caliber and agreement are exercised across the archetypes the engine
# must handle: mega-cap ad/cloud, e-commerce retail, semiconductor, enterprise
# software, industrial/logistics, consumer staples, diversified bank, and a
# high-growth neobank/fintech.
# ---------------------------------------------------------------------------
SYNTHETIC_DATA["GOOGL"] = {
    "name": "Alphabet Inc.", "sector": "Communication Services",
    "industry": "Internet Content & Information",
    "currency": "USD", "price": 175.0, "shares": 12_300_000_000,
    "total_debt": 28_000_000_000, "cash": 110_000_000_000, "book_value": 280_000_000_000,
    "beta": 1.05, "trailing_pe": 24.0, "ev_to_ebitda": 17.5, "price_to_book": 7.5,
    "annual_revenue": [307_394_000_000, 282_836_000_000, 257_637_000_000, 182_527_000_000, 161_857_000_000],
    "annual_ebit": [84_293_000_000, 74_842_000_000, 78_714_000_000, 41_224_000_000, 35_357_000_000],
    "annual_ebitda": [105_000_000_000, 94_000_000_000, 96_000_000_000, 55_000_000_000, 48_000_000_000],
    "annual_ni": [73_795_000_000, 59_972_000_000, 76_033_000_000, 40_269_000_000, 34_343_000_000],
    "annual_da": [15_000_000_000, 13_000_000_000, 12_000_000_000, 11_000_000_000, 10_000_000_000],
    "annual_capex": [32_251_000_000, 31_485_000_000, 24_640_000_000, 22_281_000_000, 23_548_000_000],
    "annual_ocf": [101_746_000_000, 91_495_000_000, 91_652_000_000, 65_124_000_000, 54_520_000_000],
    "annual_fcf": [69_495_000_000, 60_010_000_000, 67_012_000_000, 42_843_000_000, 30_972_000_000],
    "years": ["2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"],
    "interest": [308_000_000, 357_000_000, 346_000_000, 135_000_000, 152_000_000],
    "tax": [11_922_000_000, 11_356_000_000, 14_701_000_000, 7_813_000_000, 5_282_000_000],
}
SYNTHETIC_DATA["AMZN"] = {
    "name": "Amazon.com, Inc.", "sector": "Consumer Cyclical",
    "industry": "Internet Retail",
    "currency": "USD", "price": 185.0, "shares": 10_500_000_000,
    "total_debt": 140_000_000_000, "cash": 87_000_000_000, "book_value": 200_000_000_000,
    "beta": 1.15, "trailing_pe": 42.0, "ev_to_ebitda": 22.0, "price_to_book": 8.5,
    "annual_revenue": [574_785_000_000, 513_983_000_000, 469_822_000_000, 386_064_000_000, 280_522_000_000],
    "annual_ebit": [36_852_000_000, 12_248_000_000, 24_879_000_000, 22_899_000_000, 14_541_000_000],
    "annual_ebitda": [85_000_000_000, 70_000_000_000, 72_000_000_000, 60_000_000_000, 45_000_000_000],
    "annual_ni": [30_425_000_000, -2_722_000_000, 33_364_000_000, 21_331_000_000, 11_588_000_000],
    "annual_da": [48_000_000_000, 40_000_000_000, 40_000_000_000, 37_000_000_000, 30_000_000_000],
    "annual_capex": [48_133_000_000, 58_321_000_000, 55_396_000_000, 40_140_000_000, 16_861_000_000],
    "annual_ocf": [84_946_000_000, 46_752_000_000, 46_327_000_000, 66_064_000_000, 38_514_000_000],
    "annual_fcf": [36_813_000_000, -11_569_000_000, -9_069_000_000, 25_924_000_000, 21_653_000_000],
    "years": ["2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"],
    "interest": [3_182_000_000, 2_367_000_000, 1_809_000_000, 1_647_000_000, 1_600_000_000],
    "tax": [7_120_000_000, 4_131_000_000, 4_791_000_000, 2_863_000_000, 2_374_000_000],
}
SYNTHETIC_DATA["AVGO"] = {
    "name": "Broadcom Inc.", "sector": "Technology", "industry": "Semiconductors",
    "currency": "USD", "price": 165.0, "shares": 4_600_000_000,
    "total_debt": 67_000_000_000, "cash": 14_000_000_000, "book_value": 25_000_000_000,
    "beta": 1.20, "trailing_pe": 35.0, "ev_to_ebitda": 20.0, "price_to_book": 12.0,
    "annual_revenue": [35_819_000_000, 33_203_000_000, 27_450_000_000, 23_888_000_000, 22_597_000_000],
    "annual_ebit": [14_000_000_000, 11_000_000_000, 7_000_000_000, 4_500_000_000, 3_500_000_000],
    "annual_ebitda": [20_000_000_000, 17_000_000_000, 13_000_000_000, 10_000_000_000, 9_000_000_000],
    "annual_ni": [14_092_000_000, 11_495_000_000, 6_736_000_000, 2_960_000_000, 3_274_000_000],
    "annual_da": [7_000_000_000, 6_000_000_000, 6_000_000_000, 5_500_000_000, 4_800_000_000],
    "annual_capex": [600_000_000, 500_000_000, 450_000_000, 480_000_000, 500_000_000],
    "annual_ocf": [18_000_000_000, 16_000_000_000, 13_500_000_000, 12_000_000_000, 10_500_000_000],
    "annual_fcf": [17_400_000_000, 15_500_000_000, 13_050_000_000, 11_520_000_000, 10_000_000_000],
    "years": ["2023-10-29", "2022-10-30", "2021-10-31", "2020-11-01", "2019-11-03"],
    "interest": [3_210_000_000, 1_700_000_000, 1_400_000_000, 1_300_000_000, 1_200_000_000],
    "tax": [1_100_000_000, 600_000_000, 400_000_000, 200_000_000, 150_000_000],
}
SYNTHETIC_DATA["ORCL"] = {
    "name": "Oracle Corporation", "sector": "Technology",
    "industry": "Software - Infrastructure",
    "currency": "USD", "price": 130.0, "shares": 2_750_000_000,
    "total_debt": 90_000_000_000, "cash": 10_000_000_000, "book_value": 12_000_000_000,
    "beta": 1.05, "trailing_pe": 32.0, "ev_to_ebitda": 18.0, "price_to_book": 30.0,
    "annual_revenue": [49_954_000_000, 42_440_000_000, 40_479_000_000, 39_068_000_000, 39_506_000_000],
    "annual_ebit": [13_000_000_000, 11_000_000_000, 13_000_000_000, 12_000_000_000, 13_000_000_000],
    "annual_ebitda": [21_000_000_000, 18_000_000_000, 19_000_000_000, 18_000_000_000, 18_000_000_000],
    "annual_ni": [8_503_000_000, 6_717_000_000, 13_746_000_000, 10_135_000_000, 11_083_000_000],
    "annual_da": [6_000_000_000, 6_000_000_000, 5_500_000_000, 5_000_000_000, 5_000_000_000],
    "annual_capex": [6_900_000_000, 5_000_000_000, 2_500_000_000, 1_600_000_000, 1_600_000_000],
    "annual_ocf": [12_000_000_000, 9_500_000_000, 15_000_000_000, 13_000_000_000, 14_000_000_000],
    "annual_fcf": [5_100_000_000, 4_500_000_000, 12_500_000_000, 11_400_000_000, 12_400_000_000],
    "years": ["2024-05-31", "2023-05-31", "2022-05-31", "2021-05-31", "2020-05-31"],
    "interest": [3_500_000_000, 3_400_000_000, 3_000_000_000, 3_000_000_000, 2_000_000_000],
    "tax": [2_000_000_000, 1_500_000_000, 2_000_000_000, 2_500_000_000, 2_500_000_000],
}
SYNTHETIC_DATA["UPS"] = {
    "name": "United Parcel Service, Inc.", "sector": "Industrials",
    "industry": "Integrated Freight & Logistics",
    "currency": "USD", "price": 150.0, "shares": 855_000_000,
    "total_debt": 25_000_000_000, "cash": 6_000_000_000, "book_value": 17_000_000_000,
    "beta": 0.95, "trailing_pe": 20.0, "ev_to_ebitda": 12.0, "price_to_book": 8.0,
    "annual_revenue": [90_958_000_000, 100_338_000_000, 97_287_000_000, 84_628_000_000, 74_094_000_000],
    "annual_ebit": [9_200_000_000, 13_000_000_000, 12_800_000_000, 7_700_000_000, 7_000_000_000],
    "annual_ebitda": [12_000_000_000, 15_000_000_000, 15_000_000_000, 10_000_000_000, 9_000_000_000],
    "annual_ni": [6_700_000_000, 11_548_000_000, 12_890_000_000, 1_343_000_000, 4_440_000_000],
    "annual_da": [3_300_000_000, 3_200_000_000, 3_000_000_000, 2_800_000_000, 2_600_000_000],
    "annual_capex": [5_000_000_000, 6_000_000_000, 5_500_000_000, 5_000_000_000, 5_500_000_000],
    "annual_ocf": [10_200_000_000, 14_100_000_000, 13_900_000_000, 10_600_000_000, 9_500_000_000],
    "annual_fcf": [5_200_000_000, 8_100_000_000, 8_400_000_000, 5_600_000_000, 4_000_000_000],
    "years": ["2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"],
    "interest": [800_000_000, 700_000_000, 700_000_000, 700_000_000, 600_000_000],
    "tax": [1_900_000_000, 2_200_000_000, 2_900_000_000, 800_000_000, 1_300_000_000],
}
SYNTHETIC_DATA["KR"] = {
    "name": "The Kroger Co.", "sector": "Consumer Defensive",
    "industry": "Grocery Stores",
    "currency": "USD", "price": 50.0, "shares": 700_000_000,
    "total_debt": 16_000_000_000, "cash": 2_500_000_000, "book_value": 12_000_000_000,
    "beta": 0.55, "trailing_pe": 12.0, "ev_to_ebitda": 7.0, "price_to_book": 2.9,
    "annual_revenue": [150_039_000_000, 148_258_000_000, 137_888_000_000, 132_498_000_000, 122_286_000_000],
    "annual_ebit": [3_000_000_000, 2_900_000_000, 2_300_000_000, 2_600_000_000, 2_100_000_000],
    "annual_ebitda": [6_500_000_000, 6_300_000_000, 5_500_000_000, 5_600_000_000, 4_900_000_000],
    "annual_ni": [2_164_000_000, 2_244_000_000, 1_655_000_000, 2_585_000_000, 1_659_000_000],
    "annual_da": [3_500_000_000, 3_400_000_000, 3_200_000_000, 3_000_000_000, 2_800_000_000],
    "annual_capex": [3_600_000_000, 3_400_000_000, 3_200_000_000, 2_700_000_000, 2_900_000_000],
    "annual_ocf": [6_100_000_000, 5_500_000_000, 5_800_000_000, 5_300_000_000, 4_200_000_000],
    "annual_fcf": [2_500_000_000, 2_100_000_000, 2_600_000_000, 2_600_000_000, 1_300_000_000],
    "years": ["2023-02-04", "2022-01-29", "2021-01-30", "2020-02-01", "2019-02-02"],
    "interest": [600_000_000, 600_000_000, 600_000_000, 600_000_000, 600_000_000],
    "tax": [500_000_000, 500_000_000, 400_000_000, 600_000_000, 400_000_000],
}
SYNTHETIC_DATA["BAC"] = {
    "name": "Bank of America Corporation", "sector": "Financial Services",
    "industry": "Banks - Diversified",
    "currency": "USD", "price": 35.0, "shares": 7_900_000_000,
    "total_debt": 600_000_000_000, "cash": 300_000_000_000, "book_value": 290_000_000_000,
    "beta": 1.30, "trailing_pe": 11.0, "ev_to_ebitda": None, "price_to_book": 1.0,
    "dividend_yield": 0.027,
    "annual_revenue": [98_581_000_000, 94_950_000_000, 89_113_000_000, 85_528_000_000, 91_244_000_000],
    "annual_ebit": [31_000_000_000, 30_000_000_000, 33_000_000_000, 27_000_000_000, 32_000_000_000],
    "annual_ebitda": [None, None, None, None, None],
    "annual_ni": [26_515_000_000, 27_528_000_000, 31_978_000_000, 17_894_000_000, 27_430_000_000],
    "annual_da": [3_500_000_000, 3_400_000_000, 3_300_000_000, 3_200_000_000, 3_100_000_000],
    "annual_capex": [3_000_000_000, 2_800_000_000, 2_500_000_000, 2_400_000_000, 2_300_000_000],
    "annual_ocf": [36_000_000_000, 25_000_000_000, 45_000_000_000, 30_000_000_000, 32_000_000_000],
    "annual_fcf": [33_000_000_000, 22_200_000_000, 42_500_000_000, 27_600_000_000, 29_700_000_000],
    "years": ["2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"],
    "interest": [57_000_000_000, 29_000_000_000, 15_000_000_000, 14_000_000_000, 20_000_000_000],
    "tax": [4_000_000_000, 4_500_000_000, 4_000_000_000, 1_300_000_000, 5_500_000_000],
}
SYNTHETIC_DATA["NU"] = {
    "name": "Nu Holdings Ltd.", "sector": "Financial Services",
    "industry": "Credit Services",
    "currency": "USD", "price": 12.0, "shares": 4_800_000_000,
    "total_debt": 5_000_000_000, "cash": 8_000_000_000, "book_value": 8_000_000_000,
    "beta": 1.40, "trailing_pe": 25.0, "ev_to_ebitda": None, "price_to_book": 6.5,
    "annual_revenue": [11_000_000_000, 6_000_000_000, 2_400_000_000, 1_100_000_000, 500_000_000],
    "annual_ebit": [2_000_000_000, 1_000_000_000, -100_000_000, -200_000_000, -150_000_000],
    "annual_ebitda": [None, None, None, None, None],
    "annual_ni": [1_000_000_000, 200_000_000, -165_000_000, -230_000_000, -170_000_000],
    "annual_da": [400_000_000, 300_000_000, 200_000_000, 150_000_000, 100_000_000],
    "annual_capex": [300_000_000, 200_000_000, 100_000_000, 60_000_000, 40_000_000],
    "annual_ocf": [1_500_000_000, 800_000_000, 300_000_000, 100_000_000, 50_000_000],
    "annual_fcf": [1_200_000_000, 600_000_000, 200_000_000, 40_000_000, 10_000_000],
    "years": ["2023-12-31", "2022-12-31", "2021-12-31", "2020-12-31", "2019-12-31"],
    "interest": [500_000_000, 300_000_000, 100_000_000, 50_000_000, 20_000_000],
    "tax": [300_000_000, 100_000_000, 0, 0, 0],
}


class SyntheticDataProvider:
    """Curated demo fixtures for tests and explicit demo mode only."""

    def __init__(self) -> None:
        self._data = SYNTHETIC_DATA

    @classmethod
    def known_tickers(cls) -> List[str]:
        return sorted(SYNTHETIC_DATA.keys())

    def get_financial_data(
        self, ticker: str, *, allow_unknown_ticker: bool = False
    ) -> FinancialData:
        ticker_u = ticker.upper()
        params = self._data.get(ticker_u)
        template_ticker: Optional[str] = None
        if params is None:
            if not allow_unknown_ticker:
                raise UnknownSyntheticTickerError(
                    f"No synthetic fixture for {ticker_u}. "
                    f"Known demo tickers: {', '.join(self.known_tickers())}. "
                    "Refusing to substitute another company's numbers."
                )
            params = self._data["AAPL"].copy()
            template_ticker = "AAPL"
            params["name"] = f"{ticker_u} (Synthetic Demo — AAPL template)"
        data = self._build(ticker_u, params)
        if template_ticker:
            data.notes.append(
                f"⚠️ Synthetic template borrowed from {template_ticker}; "
                f"financials do NOT represent {ticker_u}."
            )
        return data

    def _build(self, ticker: str, p: dict) -> FinancialData:
        annuals: List[FinancialStatement] = []
        n = len(p["years"])
        shares = p["shares"]
        for i in range(n):
            ni = p["annual_ni"][i]
            eps = (ni / shares) if shares and ni is not None else None
            stmt = FinancialStatement(
                period_end=p["years"][i],
                period_type="annual",
                currency=p["currency"],
                revenue=p["annual_revenue"][i],
                gross_profit=p["annual_revenue"][i] - (p["annual_revenue"][i] * 0.4 if p["annual_revenue"][i] else 0),
                operating_income=p["annual_ebit"][i],
                ebit=p["annual_ebit"][i],
                ebitda=p["annual_ebitda"][i],
                net_income=ni,
                depreciation_amortization=p["annual_da"][i],
                capex=-abs(p["annual_capex"][i]),
                operating_cash_flow=p["annual_ocf"][i],
                free_cash_flow=p["annual_fcf"][i],
                interest_expense=p["interest"][i],
                income_tax=p["tax"][i],
                shares_outstanding=shares,
                eps=eps,
                raw_fields={},
            )
            stmt.cost_of_revenue = (stmt.revenue or 0) - (stmt.gross_profit or 0)
            annuals.append(stmt)

        ttm = FinancialStatement(
            period_end="TTM", period_type="ttm", currency=p["currency"],
            revenue=p["annual_revenue"][0],
            gross_profit=annuals[0].gross_profit,
            operating_income=p["annual_ebit"][0],
            ebit=p["annual_ebit"][0],
            ebitda=p["annual_ebitda"][0],
            net_income=p["annual_ni"][0],
            depreciation_amortization=p["annual_da"][0],
            capex=-abs(p["annual_capex"][0]),
            operating_cash_flow=p["annual_ocf"][0],
            free_cash_flow=p["annual_fcf"][0],
            interest_expense=p["interest"][0],
            income_tax=p["tax"][0],
            shares_outstanding=shares,
            eps=(p["annual_ni"][0] / shares) if shares else None,
        )

        # Derived: ETR = 3y avg tax / ebt
        _taxes = sum(x for x in p["tax"] if x is not None)
        _ebt = sum(
            (p["annual_ebit"][i] - (p["interest"][i] or 0))
            for i in range(min(3, len(p["annual_ebit"])))
            if p["annual_ebit"][i] is not None
        )
        etr_synth = 0.21
        if _ebt > 0 and _taxes > 0:
            e = _taxes / _ebt
            if 0.0 <= e <= 0.50:
                etr_synth = e
        # Derived: Implied Kd = avg interest / avg total debt
        kd_synth = 0.045 + 0.025  # fallback Rf(4.5%) + 2.5% BBB spread
        if p["total_debt"] and p["total_debt"] > 0 and p["interest"] and p["interest"][0]:
            _kd = float(p["interest"][0]) / float(p["total_debt"])
            if 0.01 < _kd < 0.20:
                kd_synth = _kd

        mkt = MarketData(
            as_of=datetime.utcnow(),
            currency=p["currency"],
            current_price=p["price"],
            market_cap=float(p["price"]) * float(p["shares"]),
            total_debt=p["total_debt"],
            cash_and_equivalents=p["cash"],
            net_debt=(p["total_debt"] or 0) - (p["cash"] or 0),
            shares_outstanding=p["shares"],
            book_value=p["book_value"],
            book_value_per_share=(p["book_value"] / shares) if shares else None,
            sector=p["sector"],
            industry=p["industry"],
            company_name=p["name"],
            beta=p["beta"],
            trailing_pe=p["trailing_pe"],
            ev_to_ebitda=p["ev_to_ebitda"],
            price_to_book=p["price_to_book"],
            dividend_yield=p.get("dividend_yield"),
            risk_free_rate=0.045,
            equity_risk_premium=0.055,
            effective_tax_rate=etr_synth,
            implied_cost_of_debt=kd_synth,
        )
        if p["ev_to_ebitda"] and p["annual_ebitda"][0]:
            mkt.enterprise_value = p["ev_to_ebitda"] * p["annual_ebitda"][0]
        elif mkt.market_cap:
            mkt.enterprise_value = mkt.market_cap + (p["total_debt"] or 0) - (p["cash"] or 0)

        quality = DataQualityFlags(
            missing_fields=[],
            inconsistent_periods=False, mixed_currencies=False,
            data_quality_score=92,
            raw_source_timestamp=datetime.utcnow(),
            restatement_notes=[],
        )

        data = FinancialData(
            ticker=ticker,
            source=DataSource.SYNTHETIC,
            annual_income=annuals,
            ttm=ttm,
            market=mkt,
            quality=quality,
            notes=[
                f"⚠️ SYNTHETIC 演示数据（{ticker}）— 非 Yahoo / 非 live 市场数据。",
                "勿用于生产估值或对外报告。",
            ],
        )
        return data


class YahooFinanceProvider:
    """
    Real Yahoo Finance data provider using httpx to call Yahoo public APIs directly.
    - Chart v8: price, market metadata, currency
    - Fundamentals timeseries v1: income / balance sheet / cash flow (annual + quarterly)

    Synthetic fallback only when ``use_fallback=True`` or env
    ``YAHOO_ALLOW_SYNTHETIC_FALLBACK=1`` (off by default).
    """

    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    _ANNUAL_TIMESERIES = [
        "TotalRevenue", "NetIncome", "GrossProfit",
        "EBIT", "EBITDA", "FreeCashFlow",
        "OperatingCashFlow", "CapitalExpenditure",
        "InterestExpense", "TaxProvision",
        "DepreciationAndAmortization", "TotalAssets",
        "TotalLiabilitiesNetMinorityInterest",
        "CashAndCashEquivalents", "TotalDebt",
        "StockholdersEquity", "OrdinarySharesNumber",
        # Phase 1 — SBC normalization + EV→Equity bridge components.
        "StockBasedCompensation", "MinorityInterest", "PreferredStock",
    ]
    _QUARTERLY_TIMESERIES = [
        "TotalRevenue", "NetIncome", "GrossProfit",
        "FreeCashFlow", "OperatingCashFlow", "CapitalExpenditure",
    ]

    _CACHE_DIR_NAME = ".cache"
    _CACHE_TTL_SECONDS = 4 * 3600  # 4 hours

    def __init__(
        self,
        use_fallback: Optional[bool] = None,
        cache_enabled: bool = True,
    ) -> None:
        if use_fallback is None:
            use_fallback = YAHOO_ALLOW_SYNTHETIC_FALLBACK
        self.use_fallback = use_fallback
        self._synthetic = SyntheticDataProvider()
        self.cache_enabled = cache_enabled
        self._cache_dir: Optional[Any] = None
        cache_root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            self._CACHE_DIR_NAME, "yahoo_finance"
        )
        cache_root = os.path.normpath(cache_root)
        try:
            os.makedirs(cache_root, exist_ok=True)
            self._cache_dir = cache_root
        except Exception as e:
            log.warning(f"Yahoo cache dir unavailable ({_safe_err(e)}); running cache disabled.")
            self._cache_dir = None
            self.cache_enabled = False

    def _cache_path(self, ticker_u: str) -> Optional[str]:
        if not self.cache_enabled or not self._cache_dir:
            return None
        today = datetime.utcnow().strftime("%Y%m%d")
        return os.path.join(self._cache_dir, f"{ticker_u}_{today}.json")

    @classmethod
    def _serialize_data_to_jsonable(cls, data: FinancialData) -> Dict[str, Any]:
        """Custom JSON serializer for FinancialData. Lossless enough for cache reuse.

        Converts datetime / tuple / object attributes that are dataclass-like into plain dicts/lists."""
        def _to(obj):
            if obj is None or isinstance(obj, (int, float, str, bool)):
                return obj
            if isinstance(obj, datetime):
                return {"__type__": "datetime", "iso": obj.isoformat()}
            if isinstance(obj, (list, tuple)):
                return [_to(x) for x in obj]
            if isinstance(obj, dict):
                return {str(k): _to(v) for k, v in obj.items()}
            # Enum
            if hasattr(obj, "__dataclass_fields__"):
                out = {"__type__": type(obj).__name__}
                for f in getattr(obj, "__dataclass_fields__", {}).keys():
                    out[f] = _to(getattr(obj, f, None))
                return out
            if isinstance(obj, DataSource):
                return {"__type__": "DataSource", "value": obj.value}
            return None
        payload = _to(data)
        return {"__cache_schema_version__": 1, "saved_at": datetime.utcnow().isoformat(), "payload": payload}

    @classmethod
    def _dataclass_registry(cls) -> Dict[str, Any]:
        """Map ``__type__`` names → dataclasses that can appear on a cached
        ``FinancialData``.

        The cache writer stamps every dataclass with ``__type__ = type name``
        (see :meth:`_serialize_data_to_jsonable`). The reader must reverse that
        for *all* of them — otherwise a cache hit silently degrades a structured
        object into a plain ``dict`` (e.g. ``revenue_composition`` losing
        ``.available`` → taxonomy crash; ``reconciliation_overrides`` losing
        ``.records`` → the reverse-validation log disappears). Imports are
        resolved lazily so ``data`` never imports ``classification`` at module
        load time (avoids a circular import).
        """
        reg: Dict[str, Any] = {
            "FinancialData": FinancialData,
            "FinancialStatement": FinancialStatement,
            "MarketData": MarketData,
            "DataQualityFlags": DataQualityFlags,
        }
        for modname, names in (
            ("data.reconciliation",
             ("ReconciliationCheck", "ReconciliationReport",
              "OverrideRecord", "OverrideLog")),
            ("classification.taxonomy",
             ("RevenueComposition", "SegmentRevenue")),
        ):
            try:
                import importlib
                mod = importlib.import_module(modname)
            except Exception:  # pragma: no cover - import-cycle / optional dep
                continue
            for n in names:
                obj = getattr(mod, n, None)
                if obj is not None:
                    reg[n] = obj
        return reg

    @classmethod
    def _data_from_jsonable(cls, blob: Dict[str, Any]) -> Optional[FinancialData]:
        dataclass_fields_map = cls._dataclass_registry()
        def _from(o):
            if o is None or isinstance(o, (int, float, str, bool)):
                return o
            if isinstance(o, list):
                return [_from(x) for x in o]
            if isinstance(o, dict):
                t = o.get("__type__")
                if t == "datetime":
                    try:
                        return datetime.fromisoformat(o["iso"])
                    except Exception:
                        return None
                if t == "DataSource":
                    try:
                        return DataSource(o["value"])
                    except Exception:
                        return None
                if t in dataclass_fields_map:
                    cls_type = dataclass_fields_map[t]
                    kwargs = {}
                    for f in getattr(cls_type, "__dataclass_fields__", {}).keys():
                        if f in o:
                            kwargs[f] = _from(o[f])
                    try:
                        return cls_type(** kwargs)
                    except Exception:
                        return None
                # plain dict
                return {str(k): _from(v) for k, v in o.items()}
            return o
        payload = blob.get("payload")
        if not payload:
            return None
        decoded = _from(payload)
        return decoded if isinstance(decoded, FinancialData) else None

    def _cache_read(self, ticker_u: str) -> Optional[FinancialData]:
        path = self._cache_path(ticker_u)
        if not path:
            return None
        try:
            if not os.path.exists(path):
                return None
            st = os.stat(path)
            age = (datetime.utcnow() - datetime.utcfromtimestamp(st.st_mtime)).total_seconds()
            if age > self._CACHE_TTL_SECONDS:
                try:
                    os.remove(path)
                except Exception:
                    pass
                return None
            import json as _json
            with open(path, "r", encoding="utf-8") as f:
                blob = _json.load(f)
            data = self._data_from_jsonable(blob)
            if data is not None:
                log.debug(f"Yahoo cache hit for {ticker_u} (age={age/60:.1f}min)")
                return data
        except Exception as e:
            log.warning(f"Yahoo cache read failed for {ticker_u}: {_safe_err(e)}")
        return None

    def _cache_write(self, ticker_u: str, data: FinancialData) -> None:
        path = self._cache_path(ticker_u)
        if not path:
            return
        try:
            import json as _json
            blob = self._serialize_data_to_jsonable(data)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(blob, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as e:
            log.warning(f"Yahoo cache write failed for {ticker_u}: {_safe_err(e)}")

    async def get_financial_data(self, ticker: str) -> FinancialData:
        ticker_u = ticker.upper()
        # Cache read must stay inside thread wrapper so even the async path benefits
        cached = None
        if self.cache_enabled:
            cached = self._cache_read(ticker_u)
            if cached is not None:
                return cached
        try:
            data = await asyncio.to_thread(self._get_financial_data_sync, ticker)
            if self.cache_enabled:
                self._cache_write(ticker_u, data)
            return data
        except Exception as e:
            log.warning(f"Yahoo Finance failed for {ticker.upper()}: {_safe_err(e)}")
            if self.use_fallback:
                return self._fallback_to_synthetic(ticker_u, _safe_err(e))
            raise YahooFinanceUnavailableError(
                f"Yahoo Finance failed for {ticker_u}: {_safe_err(e)}"
            ) from e

    def _fallback_to_synthetic(self, ticker_u: str, reason: str) -> FinancialData:
        log.warning(
            "YAHOO_ALLOW_SYNTHETIC_FALLBACK enabled: using synthetic fixture for %s (%s)",
            ticker_u,
            reason,
        )
        try:
            data = self._synthetic.get_financial_data(
                ticker_u, allow_unknown_ticker=False
            )
        except UnknownSyntheticTickerError as e:
            raise YahooFinanceUnavailableError(
                f"Yahoo failed for {ticker_u} ({reason}); "
                f"no synthetic fixture — {e}"
            ) from e
        data.notes.insert(
            0,
            f"⚠️ Yahoo Finance 不可用（{reason}）；已回退至 SYNTHETIC 演示数据。",
        )
        data.quality.data_quality_score = min(data.quality.data_quality_score, 30)
        data.quality.restatement_notes.append(
            f"yahoo_fallback_synthetic:{ticker_u}"
        )
        return data

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    @classmethod
    def _build_client(cls):
        import httpx
        return httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": cls._USER_AGENT},
            trust_env=False,  # 禁用 HTTP_PROXY / HTTPS_PROXY 环境变量，避免 "Invalid port: ':1'"
        )

    @staticmethod
    def _ts_raw(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract list of {period_end, value} dicts from a timeseries result entry."""
        if not entry:
            return []
        meta = entry.get("meta", {}) or {}
        ttypes = meta.get("type", []) or []
        for t in ttypes:
            vals = entry.get(t) or []
            out: List[Dict[str, Any]] = []
            for v in vals:
                if not v:
                    continue
                rv = v.get("reportedValue")
                as_of = v.get("asOfDate")
                if rv is None or as_of is None:
                    continue
                raw = rv.get("raw")
                try:
                    raw = float(raw)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(raw):
                    continue
                out.append({"period_end": str(as_of), "value": raw})
            if out:
                return out
        return []

    @staticmethod
    def _merge_by_period(rows_by_period: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        sorted_periods = sorted(rows_by_period.keys(), reverse=True)
        return [rows_by_period[p] for p in sorted_periods]

    # ------------------------------------------------------------------
    # API fetches
    # ------------------------------------------------------------------
    @classmethod
    def _fetch_chart(cls, client, ticker: str) -> Dict[str, Any]:
        r = client.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={
                "range": "10y",
                "interval": "1mo",
                "includePrePost": "false",
                "events": "div,splits",
            },
        )
        r.raise_for_status()
        data = r.json()
        result = data.get("chart", {}).get("result") or [None]
        if not result:
            return {}
        record = result[0]
        if not isinstance(record, dict):
            return {}
        return {str(key): value for key, value in record.items()}

    @classmethod
    def _fetch_timeseries(cls, client, ticker: str, period_types: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        types = []
        for p in period_types:
            for x in cls._ANNUAL_TIMESERIES if p == "annual" else cls._QUARTERLY_TIMESERIES:
                types.append(f"{p}{x}")
        now = int(datetime.utcnow().timestamp())
        r = client.get(
            f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{ticker}",
            params={
                "period1": str(now - 10 * 366 * 86400),
                "period2": str(now + 24 * 3600),
                "type": ",".join(types),
            },
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("timeseries", {}).get("result") or []
        out: Dict[str, List[Dict[str, Any]]] = {}
        for entry in results:
            meta = entry.get("meta", {}) or {}
            for t in (meta.get("type") or []):
                if t not in out:
                    # _ts_raw uses first type in meta; override here for this specific t
                    direct_vals = entry.get(t) or []
                    cleaned: List[Dict[str, Any]] = []
                    for v in direct_vals:
                        if not v:
                            continue
                        rv = v.get("reportedValue")
                        as_of = v.get("asOfDate")
                        if rv is None or as_of is None:
                            continue
                        raw = rv.get("raw")
                        try:
                            raw = float(raw)
                        except (TypeError, ValueError):
                            continue
                        if not math.isfinite(raw):
                            continue
                        cleaned.append({"period_end": str(as_of), "value": raw})
                    out[t] = cleaned
        return out

    # Beta multi-window sensitivity (Phase 3.1). Each entry:
    #   (window_label, yahoo_range, yahoo_interval, min_observations)
    # A single-window regression β hides how unstable the estimate is; the
    # primary β stays 3Y-monthly (unchanged CAPM input) and the other windows
    # are surfaced as a dispersion / stability audit, never silently swapped in.
    BETA_WINDOWS: Tuple[Tuple[str, str, str, int], ...] = (
        ("2y_weekly", "2y", "1wk", 40),
        ("3y_monthly", "3y", "1mo", 18),
        ("5y_monthly", "5y", "1mo", 30),
    )

    @classmethod
    def _estimate_beta(
        cls,
        chart: Dict[str, Any],
        client,
        ticker: str,
        range_: str = "3y",
        interval: str = "1mo",
        min_obs: int = 6,
    ) -> Optional[Dict[str, Any]]:
        """Estimate β vs SPY from **adjusted** closes over the given window.

        Returns ``{"beta": float, "provenance": {...}}`` or ``None``. β is the
        OLS slope (cov/var) of the target's simple returns on SPY's simple
        returns. Prices use the dividend/split-adjusted close (``adjclose``)
        because a raw-close regression mis-measures β across dividends and
        splits; the raw close is only a fallback when adjclose is unavailable.

        The provenance dict records method, window start/end, price basis,
        observation count and the number of *missing* grid periods, so a report
        can label the β truthfully instead of asserting a method it cannot prove.
        """
        try:
            tgt_chart = chart
            # Fetch SPY chart
            r = client.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/SPY",
                params=dict(range=range_, interval=interval, includePrePost="false"),
                timeout=15,
            )
            if r.status_code != 200:
                return None
            spy_chart = (r.json().get("chart", {}).get("result") or [{}])[0]

            def _series(ch: Dict[str, Any]) -> List[Tuple[datetime, float, str]]:
                """(dt, price, basis) tuples; adjusted close preferred."""
                ts_arr = ch.get("timestamp") or []
                indicators = ch.get("indicators") or {}
                adj = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
                close = (indicators.get("quote") or [{}])[0].get("close") or []
                out: List[Tuple[datetime, float, str]] = []
                for i, ts in enumerate(ts_arr):
                    px: Optional[float] = None
                    basis = ""
                    if i < len(adj) and adj[i] is not None:
                        px, basis = adj[i], "adjclose"
                    elif i < len(close) and close[i] is not None:
                        px, basis = close[i], "close"
                    if px is None:
                        continue
                    try:
                        out.append((datetime.utcfromtimestamp(int(ts)), float(px), basis))
                    except (TypeError, ValueError, OSError):
                        continue
                return out

            def _period_map(
                pts: List[Tuple[datetime, float, str]]
            ) -> Dict[str, Tuple[float, str, datetime]]:
                m: Dict[str, Tuple[float, str, datetime]] = {}
                for dt, px, basis in pts:
                    # Weekly windows must key per ISO week, otherwise every
                    # weekly point in a month collapses to one monthly key.
                    if interval == "1wk":
                        iso = dt.isocalendar()
                        key = f"{iso[0]}-W{iso[1]:02d}"
                    else:
                        key = f"{dt.year}-{dt.month:02d}"
                    m[key] = (px, basis, dt)
                return m

            def _key_index(key: str) -> int:
                """Monotonic grid index so adjacent-period gaps are measurable."""
                if interval == "1wk":
                    y, w = key.split("-W")
                    return int(y) * 53 + int(w)
                y, mo = key.split("-")
                return int(y) * 12 + (int(mo) - 1)

            tgt_p = _period_map(_series(tgt_chart))
            spy_p = _period_map(_series(spy_chart))
            common = sorted(set(tgt_p.keys()) & set(spy_p.keys()))
            if len(common) < min_obs:
                return None

            # Date-continuity check: grid periods absent between the first and
            # last common period (a gap ⇒ the regression's frequency assumption
            # is broken, which the report must be able to flag).
            missing_periods = 0
            for i in range(1, len(common)):
                step = _key_index(common[i]) - _key_index(common[i - 1])
                if step > 1:
                    missing_periods += step - 1

            t_ret: List[float] = []
            s_ret: List[float] = []
            bases: set = set()
            for i in range(1, len(common)):
                tp = tgt_p[common[i - 1]][0]
                tc = tgt_p[common[i]][0]
                sp = spy_p[common[i - 1]][0]
                sc = spy_p[common[i]][0]
                if tp <= 0 or sp <= 0:
                    continue
                bases.add(tgt_p[common[i - 1]][1])
                bases.add(spy_p[common[i - 1]][1])
                t_ret.append(tc / tp - 1.0)
                s_ret.append(sc / sp - 1.0)
            n = min(len(t_ret), len(s_ret))
            if n < min_obs:
                return None
            t_ret = t_ret[:n]
            s_ret = s_ret[:n]
            mean_t = sum(t_ret) / n
            mean_s = sum(s_ret) / n
            cov = sum((t_ret[i]-mean_t)*(s_ret[i]-mean_s) for i in range(n)) / n
            var_s = sum((s_ret[i]-mean_s)**2 for i in range(n)) / n
            if var_s <= 0:
                return None

            window_label = {
                "1y": "1Y", "2y": "2Y", "3y": "3Y", "4y": "4Y", "5y": "5Y",
            }.get(range_, range_)
            interval_label = {
                "1mo": "monthly", "1wk": "weekly", "1d": "daily",
            }.get(interval, interval)
            if bases == {"adjclose"}:
                price_basis = "adjclose (dividend/split-adjusted)"
            elif "adjclose" in bases:
                price_basis = "adjclose (with raw-close fallback)"
            else:
                price_basis = "close (unadjusted — adjclose unavailable)"

            provenance = {
                "source": "regression",
                "method": "OLS cov/var of simple returns vs SPY",
                "window_label": f"{window_label} {interval_label}",
                "window_start": tgt_p[common[0]][2].strftime("%Y-%m-%d"),
                "window_end": tgt_p[common[-1]][2].strftime("%Y-%m-%d"),
                "price_basis": price_basis,
                "n_observations": n,
                "missing_periods": missing_periods,
                "benchmark": "SPY",
                "verified": True,
            }
            return {"beta": cov / var_s, "provenance": provenance}
        except Exception as e:
            log.debug(f"beta estimate failed for {ticker}: {_safe_err(e)}")
            return None

    @classmethod
    def _estimate_beta_windows(
        cls, client, ticker: str, provenance_out: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Optional[float]]:
        """Regression β vs SPY across the configured windows (Phase 3.1).

        Returns {window_label: beta or None}. Missing/failed windows are kept as
        explicit ``None`` (no silent fabrication) so the WACC layer can report
        "N of M windows available" instead of pretending a single value. When
        ``provenance_out`` is passed, each resolved window's provenance dict is
        recorded there (Phase 1 — β provenance), so no extra SPY fetch is needed.
        """
        out: Dict[str, Optional[float]] = {}
        for label, rng, itv, min_obs in cls.BETA_WINDOWS:
            beta: Optional[float] = None
            try:
                r = client.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                    params=dict(range=rng, interval=itv, includePrePost="false"),
                    timeout=15,
                )
                if r.status_code == 200:
                    tgt_chart = (r.json().get("chart", {}).get("result") or [{}])[0]
                    res = cls._estimate_beta(
                        tgt_chart, client, ticker,
                        range_=rng, interval=itv, min_obs=min_obs,
                    )
                    if res is not None:
                        beta = res["beta"]
                        if provenance_out is not None:
                            provenance_out[label] = res["provenance"]
            except Exception as e:
                log.debug(f"beta window {label} failed for {ticker}: {_safe_err(e)}")
            out[label] = beta
        return out

    @staticmethod
    def _build_beta_provenance(
        chosen_source: str,
        provider_beta: Optional[float],
        regression_result: Optional[Dict[str, Any]],
        window_prov: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Assemble the β provenance recorded on ``MarketData.beta_provenance``.

        ``chosen_source``: "provider" (vendor β used), "regression" (self-computed
        β used) or "none" (no β resolved). The provider β stays the preferred
        scalar when present (a vendor-standard estimate); the regression β is
        always recorded alongside so the report can *compare* methods instead of
        asserting one blindly. A missing provenance dict means "unverified",
        which downstream surfaces must flag as *assumed*, not proven.
        """
        reg_beta: Optional[float] = regression_result["beta"] if regression_result else None
        if reg_beta is None:
            reg_beta = (window_prov.get("3y_monthly") or {}).get("beta")  # type: ignore[assignment]
        out: Dict[str, Any] = {
            "source": chosen_source,
            "provider_beta": (float(provider_beta) if provider_beta is not None else None),
            "regression_beta": (float(reg_beta) if reg_beta is not None else None),
        }
        if chosen_source == "regression" and regression_result is not None:
            out.update(regression_result["provenance"])
        elif chosen_source == "provider":
            out.update({
                "method": "Yahoo quoteSummary defaultKeyStatistics.beta (vendor-provided)",
                "window_label": "vendor (typically 5Y monthly vs S&P 500)",
                "price_basis": "unknown (vendor)",
                "benchmark": "S&P 500 (vendor)",
                "n_observations": None,
                "missing_periods": None,
                "window_start": None,
                "window_end": None,
                "verified": False,
            })
        else:
            out.update({
                "method": "no β source resolved",
                "window_label": None,
                "price_basis": None,
                "benchmark": None,
                "n_observations": None,
                "missing_periods": None,
                "verified": False,
            })
        reg_from_windows = (window_prov.get("3y_monthly") or {}).get("beta")
        if provider_beta is not None and reg_from_windows is not None:
            out["comparison"] = (
                f"provider β={provider_beta:.2f} vs regression β={reg_from_windows:.2f} "
                f"(|Δ|={abs(float(provider_beta) - float(reg_from_windows)):.2f})"
            )
        return out

    @classmethod
    def _fetch_quote_summary_simple(cls, client, ticker: str) -> Dict[str, Any]:
        """Fetch assetProfile + summaryDetail (sector, industry, longName, trailingPE,
        priceToBook, beta) from Yahoo quoteSummary endpoint.

        This is used to fill the `extra` dict consumed by the final MarketData
        constructor; missing values are OK — they'll be estimated elsewhere or
        left None for downstream validators.
        """
        out: Dict[str, Any] = {}
        asset: Dict[str, Any] = {}
        price: Dict[str, Any] = {}
        detail: Dict[str, Any] = {}
        ks: Dict[str, Any] = {}
        try:
            r = client.get(
                f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}",
                params={"modules": "assetProfile,summaryDetail,defaultKeyStatistics,price"},
            )
            # NOTE: do NOT early-return on 401 / empty result — that is exactly
            # the H-03 401 scenario, and returning here would skip the
            # sector/industry fallback chain below (making it dead code).
            if r.status_code == 200:
                data = r.json()
                result = ((data.get("quoteSummary") or {}).get("result") or [None])[0]
                if result:
                    asset = result.get("assetProfile") or {}
                    price = result.get("price") or {}
                    detail = result.get("summaryDetail") or {}
                    ks = result.get("defaultKeyStatistics") or {}
        except Exception as e:
            log.debug(f"quoteSummary fetch failed for {ticker}: {_safe_err(e)}")

        for src in (asset, price):
            if not out.get("sector") and isinstance(src.get("sector"), str):
                out["sector"] = src["sector"]
            if not out.get("industry") and isinstance(src.get("industry"), str):
                out["industry"] = src["industry"]

        # Business description (taxonomy ①-signal). assetProfile already carries
        # longBusinessSummary; it was previously fetched and discarded. Stored
        # verbatim and never used to overwrite an internal Business Identity.
        if not out.get("description"):
            for src in (asset,):
                if isinstance(src.get("longBusinessSummary"), str) and src["longBusinessSummary"].strip():
                    out["description"] = src["longBusinessSummary"].strip()
                    break

        # ---- Fallback chain for sector/industry (runs even when quoteSummary
        #      itself is 401/empty) ----
        # Layer-1: akshare (A-share / HK / US stock info API)
        if not out.get("sector") or not out.get("industry"):
            try:
                from data.akshare_provider import AkshareSectorProvider
                ak_provider = AkshareSectorProvider()
                if ak_provider.available:
                    ak_info = ak_provider.get_sector_industry(ticker)
                    if ak_info:
                        if not out.get("sector") and ak_info.get("sector"):
                            out["sector"] = ak_info["sector"]
                            log.debug(f"akshare filled sector for {ticker}: {ak_info['sector']}")
                        if not out.get("industry") and ak_info.get("industry"):
                            out["industry"] = ak_info["industry"]
                            log.debug(f"akshare filled industry for {ticker}: {ak_info['industry']}")
            except Exception as e:
                log.debug(f"akshare sector fallback failed for {ticker}: {_safe_err(e)}")

        # Layer-2 (H-03): Yahoo v1/finance/search (+ optional FMP / Alpha
        # Vantage) carries sector/industry and is not gated by the assetProfile 401.
        if not out.get("sector") or not out.get("industry"):
            try:
                from data.secondary_profile import SecondaryProfileProvider
                sec_info = SecondaryProfileProvider(client=client).get_sector_industry(ticker)
                if sec_info:
                    if not out.get("sector") and sec_info.get("sector"):
                        out["sector"] = sec_info["sector"]
                        log.debug(f"secondary source filled sector for {ticker}: {sec_info['sector']}")
                    if not out.get("industry") and sec_info.get("industry"):
                        out["industry"] = sec_info["industry"]
                        log.debug(f"secondary source filled industry for {ticker}: {sec_info['industry']}")
            except Exception as e:
                log.debug(f"secondary sector fallback failed for {ticker}: {_safe_err(e)}")

        # Layer-3 (H-03): authoritative + offline sources — FinanceDatabase
        # (offline Yahoo-compatible) → SEC EDGAR (official SIC, bridged to the
        # Yahoo taxonomy via data.sic_map) → Wikidata/Wikipedia. Completes the
        # sector/industry pair the +3.0 hard rule and taxonomy mapper need.
        if not out.get("sector") or not out.get("industry"):
            try:
                from data.industry_resolver import SectorIndustryResolver
                res_info = SectorIndustryResolver(client=client).resolve(ticker)
                if res_info:
                    if not out.get("sector") and res_info.get("sector"):
                        out["sector"] = res_info["sector"]
                    if not out.get("industry") and res_info.get("industry"):
                        out["industry"] = res_info["industry"]
                    if res_info.get("sic"):
                        out["sic"] = res_info["sic"]
                    if res_info.get("sic_description"):
                        out["sic_description"] = res_info["sic_description"]
                    if out.get("sector") or out.get("industry"):
                        log.debug(
                            f"industry resolver ({res_info.get('source')}) filled {ticker}: "
                            f"{out.get('sector')}/{out.get('industry')}"
                        )
            except Exception as e:
                log.debug(f"industry resolver fallback failed for {ticker}: {_safe_err(e)}")

        # company_name fallback (if chart meta doesn't have longName)
        if not out.get("company_name"):
            for src in (price, asset):
                if isinstance(src.get("longName"), str):
                    out["company_name"] = src["longName"]
                    break
                if isinstance(src.get("shortName"), str):
                    out["company_name"] = src["shortName"]
                    break

        def _pick_num(key: str, src_list) -> Optional[float]:
            for src in src_list:
                raw = src.get(key)
                if isinstance(raw, dict) and isinstance(raw.get("raw"), (int, float)):
                    return float(raw["raw"])
                if isinstance(raw, (int, float)):
                    return float(raw)
            return None

        beta = _pick_num("beta", (detail, price, asset))
        if beta is not None:
            out["beta"] = beta
        trailing_pe = _pick_num("trailingPE", (detail, price))
        if trailing_pe is not None:
            out["trailing_pe"] = trailing_pe
        pb = _pick_num("priceToBook", (detail,))
        if pb is not None:
            out["pb"] = pb
        ev_ebitda = _pick_num("enterpriseToEbitda", (detail, ks))
        if ev_ebitda is not None:
            out["ev_ebitda"] = ev_ebitda
        return out

    # ------------------------------------------------------------------
    # Data construction
    # ------------------------------------------------------------------
    @classmethod
    def _build_statements(
        cls,
        ts_data: Dict[str, List[Dict[str, Any]]],
        prefix: str,
        period_type: str,
        currency: str,
        shares_latest: Optional[float],
        shares_series: List[Dict[str, Any]],
        ebit_margin_latest_annual: Optional[float] = None,
        da_to_revenue_latest_annual: Optional[float] = None,
    ) -> List[FinancialStatement]:
        periods: Dict[str, Dict[str, Any]] = {}

        def _add(field_name: str, ts_key: str, neg: bool = False) -> None:
            for v in ts_data.get(f"{prefix}{ts_key}", []):
                p_end = v["period_end"]
                periods.setdefault(p_end, {"period_end": p_end})
                val = -abs(v["value"]) if neg else v["value"]
                periods[p_end][field_name] = val

        _add("revenue", "TotalRevenue")
        _add("gross_profit", "GrossProfit")
        _add("ebit", "EBIT")
        _add("operating_income", "EBIT")
        _add("ebitda", "EBITDA")
        _add("net_income", "NetIncome")
        _add("depreciation_amortization", "DepreciationAndAmortization")
        _add("capex", "CapitalExpenditure", neg=True)
        _add("change_in_nwc_cf", "ChangeInWorkingCapital")
        _add("operating_cash_flow", "OperatingCashFlow")
        _add("free_cash_flow", "FreeCashFlow")
        _add("interest_expense", "InterestExpense")
        _add("income_tax", "TaxProvision")
        _add("stock_based_compensation", "StockBasedCompensation")

        rows = cls._merge_by_period(periods)
        stmts: List[FinancialStatement] = []
        for r in rows[:8]:
            period_end = r["period_end"]
            sh = shares_latest
            if shares_series:
                for s in shares_series:
                    if s["period_end"] == period_end:
                        sh = s["value"]
                        break
            rev = r.get("revenue")
            ebit = r.get("ebit")
            op_inc = r.get("operating_income") or ebit
            ebitda = r.get("ebitda")
            da = r.get("depreciation_amortization")
            ni = r.get("net_income")
            int_exp = r.get("interest_expense")
            tax = r.get("income_tax")
            # Infer EBIT from net income + interest + tax when Yahoo omits EBIT
            # (common for financial-services / credit-services tickers like UPST).
            if ebit is None and ni is not None:
                addbacks: List[float] = []
                if int_exp is not None:
                    addbacks.append(abs(float(int_exp)))
                if tax is not None:
                    addbacks.append(abs(float(tax)))
                if addbacks:
                    ebit = float(ni) + sum(addbacks)
                    op_inc = ebit
            # Infer EBIT from gross profit * annual margin if missing (for quarterly)
            if ebit is None and rev and ebit_margin_latest_annual is not None:
                ebit = rev * ebit_margin_latest_annual
                op_inc = ebit
            if ebitda is None and ebit is not None and da is None and da_to_revenue_latest_annual is not None and rev:
                da = rev * da_to_revenue_latest_annual
                ebitda = ebit + da
            elif ebitda is None and ebit is not None and da is not None:
                ebitda = ebit + da
            # DA standalone inference
            if da is None and rev and da_to_revenue_latest_annual is not None:
                da = rev * da_to_revenue_latest_annual
            cf_wc = r.get("change_in_nwc_cf")
            change_in_nwc = None
            if cf_wc is not None:
                from data.nwc_utils import nwc_from_cashflow_line

                change_in_nwc = nwc_from_cashflow_line(cf_wc)
            stmt = FinancialStatement(
                period_end=period_end,
                period_type=period_type,
                currency=currency,
                revenue=rev,
                gross_profit=r.get("gross_profit"),
                operating_income=op_inc,
                ebit=ebit,
                ebitda=ebitda,
                net_income=r.get("net_income"),
                depreciation_amortization=da,
                capex=r.get("capex"),
                change_in_nwc=change_in_nwc,
                operating_cash_flow=r.get("operating_cash_flow"),
                free_cash_flow=r.get("free_cash_flow"),
                interest_expense=r.get("interest_expense"),
                income_tax=r.get("income_tax"),
                shares_outstanding=sh,
                stock_based_compensation=r.get("stock_based_compensation"),
            )
            operating_cash_flow = stmt.operating_cash_flow
            free_cash_flow = stmt.free_cash_flow
            capex = stmt.capex
            if operating_cash_flow is None and free_cash_flow is not None and capex is not None:
                stmt.operating_cash_flow = free_cash_flow - capex
            if free_cash_flow is None and operating_cash_flow is not None and capex is not None:
                stmt.free_cash_flow = operating_cash_flow + capex
            if stmt.net_income is not None and sh:
                stmt.eps = stmt.net_income / sh
            revenue = stmt.revenue
            cost_of_revenue = stmt.cost_of_revenue
            if revenue is not None and stmt.gross_profit is None and cost_of_revenue is not None:
                stmt.gross_profit = revenue - cost_of_revenue
            stmts.append(stmt)
        return stmts

    @classmethod
    def _build_bs_records(
        cls,
        ts_data: Dict[str, List[Dict[str, Any]]],
        prefix: str,
    ) -> List[Dict[str, Any]]:
        periods: Dict[str, Dict[str, Any]] = {}
        mapping = {
            "TotalDebt": "Total Debt",
            "TotalLiabilitiesNetMinorityInterest": "Total Liabilities Net Minority Interest",
            "CashAndCashEquivalents": "Cash And Cash Equivalents",
            "TotalAssets": "Total Assets",
            "StockholdersEquity": "Stockholders Equity",
            "OrdinarySharesNumber": "Ordinary Shares Number",
            # Phase 1 — EV→Equity bridge components.
            "MinorityInterest": "Minority Interest",
            "PreferredStock": "Preferred Stock",
        }
        for ts_key, alias in mapping.items():
            for v in ts_data.get(f"{prefix}{ts_key}", []):
                p_end = v["period_end"]
                periods.setdefault(p_end, {"period_end": p_end})
                periods[p_end][alias] = v["value"]
        return cls._merge_by_period(periods)

    def _get_financial_data_sync(self, ticker: str) -> FinancialData:
        ticker_u = ticker.upper()
        try:
            with self._build_client() as client:
                chart = self._fetch_chart(client, ticker_u)
                meta = (chart.get("meta") or {}) if chart else {}

                currency = str(meta.get("currency") or "USD")
                # Prefer chart.meta names (verified correct), not profile page (had AAPL->META mix-up)
                company_name = (
                    meta.get("longName")
                    or meta.get("shortName")
                    or meta.get("symbol")
                    or ticker_u
                )
                exchange = meta.get("exchangeName")

                price: Optional[float] = None
                for k in ("regularMarketPrice", "chartPreviousClose", "previousClose"):
                    try:
                        v = meta.get(k)
                        if v is not None:
                            price = float(v)
                            break
                    except (TypeError, ValueError):
                        continue
                if price is None:
                    ts_arr = chart.get("timestamp") or []
                    quotes = (chart.get("indicators") or {}).get("quote") or [{}]
                    if ts_arr and quotes:
                        closes = [c for c in (quotes[0].get("close") or []) if c is not None]
                        if closes:
                            price = float(closes[-1])

                ts_data = self._fetch_timeseries(client, ticker_u, ["annual", "quarterly"])
                extra = self._fetch_quote_summary_simple(client, ticker_u)

                # β provenance (Phase 1). The *provider* β (quoteSummary) stays the
                # preferred scalar when present — a vendor-standard estimate — and
                # the self-computed 3Y-monthly regression β is only used when the
                # provider value is missing. Both are recorded (with method, window,
                # price basis, observation count) so the report can compare sources
                # instead of asserting a method it cannot prove.
                provider_beta = extra.get("beta")
                regression_result = None
                if not provider_beta:
                    regression_result = self._estimate_beta(chart, client, ticker_u)
                    if regression_result is not None:
                        extra["beta"] = regression_result["beta"]

                # Phase 3.1: multi-window β sensitivity (independent audit input;
                # never overrides the scalar `beta` used by CAPM). Provenance of
                # each window is captured in ``window_prov`` for the β audit trail.
                window_prov: Dict[str, Dict[str, Any]] = {}
                try:
                    extra["beta_windows"] = self._estimate_beta_windows(
                        client, ticker_u, provenance_out=window_prov
                    )
                except Exception as e:
                    log.debug(f"beta windows failed for {ticker_u}: {_safe_err(e)}")

                try:
                    if regression_result is not None:
                        beta_src = "regression"
                    elif provider_beta is not None:
                        beta_src = "provider"
                    else:
                        beta_src = "none"
                    extra["beta_provenance"] = self._build_beta_provenance(
                        beta_src, provider_beta, regression_result, window_prov
                    )
                except Exception as e:
                    log.debug(f"beta provenance build failed for {ticker_u}: {_safe_err(e)}")

            shares_series_annual = [
                v for v in ts_data.get("annualOrdinarySharesNumber", [])
            ]
            shares_latest: Optional[float] = None
            if shares_series_annual:
                shares_latest = float(shares_series_annual[0]["value"])
            if shares_latest is None and meta.get("sharesOutstanding"):
                try:
                    shares_latest = float(meta["sharesOutstanding"])
                except (TypeError, ValueError):
                    pass

            annual_stmts = self._build_statements(
                ts_data, "annual", "annual", currency, shares_latest, shares_series_annual
            )

            # Latest-annual margins for quarterly EBIT / DA inference (when quarterly lacks these)
            ebit_margin_latest_annual: Optional[float] = None
            da_to_revenue_latest_annual: Optional[float] = None
            if annual_stmts:
                first = annual_stmts[0]
                if first.revenue and first.ebit and first.revenue > 0:
                    ebit_margin_latest_annual = first.ebit / first.revenue
                if first.revenue and first.depreciation_amortization and first.revenue > 0:
                    da_to_revenue_latest_annual = first.depreciation_amortization / first.revenue

            shares_series_q = [v for v in ts_data.get("quarterlyOrdinarySharesNumber", [])]
            quarterly_stmts = self._build_statements(
                ts_data, "quarterly", "quarterly", currency, shares_latest, shares_series_q,
                ebit_margin_latest_annual=ebit_margin_latest_annual,
                da_to_revenue_latest_annual=da_to_revenue_latest_annual,
            )

            # Fetch 10Y Treasury yield (^TNX) for risk_free_rate (shared across tickers)
            rf_10y = None
            try:
                rf_chart = self._fetch_chart(client, "^TNX")
                rf_meta = (rf_chart.get("meta") or {}) if rf_chart else {}
                for k in ("regularMarketPrice", "chartPreviousClose", "previousClose"):
                    try:
                        v = rf_meta.get(k)
                        if v is not None:
                            # ^TNX yields are quoted as percentages (4.35 means 4.35%)
                            rf_10y = float(v) / 100.0
                            break
                    except (TypeError, ValueError):
                        continue
            except Exception as _e:
                log.debug(f"^TNX 10Y Treasury fetch failed: {_safe_err(_e)}")
                rf_10y = None

            annual_bs_records = self._build_bs_records(ts_data, "annual")
            quarterly_bs_records = self._build_bs_records(ts_data, "quarterly")
            annual_cf_records = []
            quarterly_cf_records = []
            if annual_stmts:
                for s in annual_stmts:
                    annual_cf_records.append({
                        "period_end": s.period_end,
                        "Cash From Operating Activities": s.operating_cash_flow,
                        "Capital Expenditure": s.capex,
                        "Free Cash Flow": s.free_cash_flow,
                    })
            if quarterly_stmts:
                for s in quarterly_stmts:
                    quarterly_cf_records.append({
                        "period_end": s.period_end,
                        "Cash From Operating Activities": s.operating_cash_flow,
                        "Capital Expenditure": s.capex,
                        "Free Cash Flow": s.free_cash_flow,
                    })

            total_debt: Optional[float] = None
            cash_eq: Optional[float] = None
            book_value: Optional[float] = None
            if annual_bs_records:
                latest = annual_bs_records[0]
                total_debt = latest.get("Total Debt") or latest.get("Total Liabilities Net Minority Interest")
                cash_eq = latest.get("Cash And Cash Equivalents")
                book_value = latest.get("Stockholders Equity")

            market_cap = None
            if price is not None and shares_latest is not None:
                market_cap = price * shares_latest

            trailing_pe: Optional[float] = None
            ev_to_ebitda: Optional[float] = None
            price_to_book: Optional[float] = None
            if annual_stmts:
                latest_annual = annual_stmts[0]
                if latest_annual.net_income and shares_latest and price:
                    eps = latest_annual.net_income / shares_latest
                    if eps and eps > 0:
                        trailing_pe = price / eps
                if latest_annual.ebitda and total_debt is not None and cash_eq is not None and market_cap is not None:
                    ev = market_cap + total_debt - cash_eq
                    if latest_annual.ebitda > 0:
                        ev_to_ebitda = ev / latest_annual.ebitda
                if book_value and shares_latest and book_value > 0 and price:
                    bvps = book_value / shares_latest
                    if bvps > 0:
                        price_to_book = price / bvps

            dividend_yield: Optional[float] = None
            events = (chart.get("events") or {}).get("dividends") or {}
            if events and price:
                cutoff_ts = int((datetime.utcnow() - timedelta(days=365)).timestamp())
                total_div = 0.0
                for ts_str, d in events.items():
                    try:
                        ts = int(ts_str) if isinstance(ts_str, str) else int(ts_str)
                    except (TypeError, ValueError):
                        continue
                    if ts >= cutoff_ts:
                        amt = d.get("amount") or 0
                        try:
                            total_div += float(amt)
                        except (TypeError, ValueError):
                            pass
                if total_div > 0 and price:
                    dividend_yield = total_div / price

            beta: Optional[float] = None
            try:
                bv = extra.get("beta")
                if bv is not None:
                    beta = float(bv)
            except (TypeError, ValueError):
                pass
            # Estimate beta from chart vs SPY if possible (skip for simplicity)

            ttm: Optional[FinancialStatement] = None
            if quarterly_stmts and len(quarterly_stmts) >= 4:
                from data.normalizer import FinancialNormalizer
                ttm = FinancialNormalizer.compute_ttm_from_quarters(quarterly_stmts)
            elif annual_stmts:
                first = annual_stmts[0]
                ttm = FinancialStatement(
                    period_end=f"TTM(approx from {first.period_end})",
                    period_type="ttm",
                    currency=currency,
                    revenue=first.revenue,
                    gross_profit=first.gross_profit,
                    operating_income=first.operating_income,
                    ebit=first.ebit,
                    ebitda=first.ebitda,
                    net_income=first.net_income,
                    depreciation_amortization=first.depreciation_amortization,
                    capex=first.capex,
                    operating_cash_flow=first.operating_cash_flow,
                    free_cash_flow=first.free_cash_flow,
                    interest_expense=first.interest_expense,
                    income_tax=first.income_tax,
                    shares_outstanding=shares_latest,
                    eps=first.eps,
                )

            # ---- Derived: effective tax rate & implied cost of debt (snapshot, for use in WACC calc) ----
            etr_snapshot: Optional[float] = None
            try:
                candidates: List[Any] = []
                if ttm is not None:
                    candidates.append(ttm)
                candidates.extend(annual_stmts[:3])
                _tax = 0.0
                _ebt = 0.0
                for s in candidates:
                    _t = getattr(s, "income_tax", None)
                    _eb = getattr(s, "ebit", None)
                    _ie = getattr(s, "interest_expense", None)
                    if _t is None or _eb is None:
                        continue
                    __ebt = float(_eb) - (float(_ie) if _ie is not None else 0.0)
                    if __ebt <= 0:
                        continue
                    _tax += float(_t)
                    _ebt += __ebt
                if _ebt > 0 and 0.0 <= _tax / _ebt <= 0.60:
                    etr_snapshot = _tax / _ebt
            except Exception:
                etr_snapshot = None

            kd_snapshot: Optional[float] = None
            try:
                _int_list: List[float] = []
                ttm_interest = ttm.interest_expense if ttm is not None else None
                annual_interest = annual_stmts[0].interest_expense if annual_stmts else None
                if ttm_interest is not None and ttm_interest > 0:
                    _int_list.append(float(ttm_interest))
                elif annual_interest is not None and annual_interest > 0:
                    _int_list.append(float(annual_interest))
                _dlist: List[float] = []
                for rec in annual_bs_records:
                    _d = rec.get("Total Debt")
                    if _d is not None and float(_d) > 0:
                        _dlist.append(float(_d))
                if total_debt and total_debt > 0:
                    _dlist.insert(0, float(total_debt))
                if _int_list and _dlist:
                    avg_d = sum(_dlist[:2]) / float(len(_dlist[:2]))
                    if avg_d > 0:
                        kd_impl = _int_list[0] / avg_d
                        if 0.005 < kd_impl < 0.30:
                            kd_snapshot = kd_impl
            except Exception:
                kd_snapshot = None

            # ---- Bottom-up β chain (H-03 → M-34 → M-35) -------------------
            # Three-level business-identity screen (L1 exact / L2 adjacent /
            # L3 Damodaran benchmark) + full chain: peer levered → unlevered →
            # median → cash-adjusted → target-relevered. When segment revenue
            # resolves (M-31), the segment-weighted beta (M-35) is used instead
            # of the company-level chain. The target D/E and the tax rate are
            # only known here (after financials). Never fabricated: None when no
            # level resolves.
            #
            # Segment revenue goes through the source chain: FMP first (needs a
            # key), then the key-free SEC 10-K / 20-F filing-instance XBRL
            # fallback (M-38) — so an expired / missing / rate-limited FMP key
            # degrades gracefully instead of losing the mix.
            bottom_up_beta: Optional[float] = None
            industry_beta_unlev: Optional[float] = None
            bottom_up_chain: Optional[Dict[str, Any]] = None
            revenue_composition_snapshot: Optional[Any] = None
            from data.segment_revenue import (
                resolve_segments,
                segment_weights,
                to_revenue_composition,
            )

            try:
                _segments = resolve_segments(ticker)
            except Exception as e:
                log.debug(f"segment revenue failed for {ticker}: {_safe_err(e)}")
                _segments = []
            if _segments:
                try:
                    revenue_composition_snapshot = to_revenue_composition(_segments)
                except Exception as e:
                    log.debug(f"revenue composition build failed for {ticker}: {_safe_err(e)}")

            try:
                from data.industry_beta import derive_bottom_up_beta
                _ind = extra.get("industry")
                _bm: Optional[str] = None
                try:
                    from classification.taxonomy import infer_business_models
                    _models = infer_business_models(
                        (extra.get("description") or "") + " " + (_ind or "")
                    )
                    if _models:
                        _bm = _models[0].value
                except Exception:
                    _bm = None
                _d2e = (
                    float(total_debt) / float(market_cap)
                    if (total_debt and market_cap and market_cap > 0)
                    else None
                )
                _cash_to_firm = None
                if cash_eq and market_cap and market_cap > 0:
                    _firm = float(market_cap) + (float(total_debt) if total_debt else 0.0)
                    if _firm > 0:
                        _cash_to_firm = float(cash_eq) / _firm
                _seg_weights = segment_weights(_segments) if _segments else None
                _bu = derive_bottom_up_beta(
                    ticker,
                    extra.get("sector"),
                    _ind,
                    business_model=_bm,
                    target_d2e=_d2e,
                    target_tax_rate=etr_snapshot,
                    segments=_seg_weights,
                    segment_cash_to_firm=_cash_to_firm,
                )
                if _bu is not None:
                    bottom_up_beta = _bu.beta_relevered
                    industry_beta_unlev = _bu.beta_unlevered
                    bottom_up_chain = _bu.to_chain()
            except Exception as e:
                log.debug(f"bottom-up beta failed for {ticker}: {_safe_err(e)}")

            mkt = MarketData(
                as_of=datetime.utcnow(),
                currency=currency,
                current_price=price,
                market_cap=market_cap,
                enterprise_value=(
                    market_cap + total_debt - cash_eq
                    if (market_cap is not None and total_debt is not None and cash_eq is not None)
                    else None
                ),
                total_debt=total_debt,
                cash_and_equivalents=cash_eq,
                net_debt=(
                    total_debt - cash_eq
                    if (total_debt is not None and cash_eq is not None)
                    else None
                ),
                shares_outstanding=shares_latest,
                book_value=book_value,
                book_value_per_share=(book_value / shares_latest if (book_value and shares_latest and shares_latest > 0) else None),
                sector=extra.get("sector"),
                industry=extra.get("industry"),
                company_name=company_name,
                description=extra.get("description"),
                beta=beta,
                beta_windows=extra.get("beta_windows"),
                beta_provenance=extra.get("beta_provenance"),
                industry_beta=industry_beta_unlev,
                bottom_up_beta=bottom_up_beta,
                bottom_up_beta_chain=bottom_up_chain,
                trailing_pe=trailing_pe,
                forward_pe=None,
                ev_to_ebitda=ev_to_ebitda,
                price_to_book=price_to_book,
                dividend_yield=dividend_yield,
                # Macroeconomic / derived snapshot values
                risk_free_rate=rf_10y,
                risk_free_source=(
                    "^TNX US 10Y Treasury (Yahoo)" if rf_10y is not None else None
                ),
                equity_risk_premium=DEFAULT_DCF_CONFIG.equity_risk_premium,
                effective_tax_rate=etr_snapshot,
                implied_cost_of_debt=kd_snapshot,
            )

            quality = DataQualityFlags()
            if not annual_stmts:
                quality.missing_fields.append("Annual Financial Statements")
            if len(annual_stmts) < 3:
                quality.missing_fields.append(f"Only {len(annual_stmts)} annual periods (<3)")
            if price is None:
                quality.missing_fields.append("Current Price")
            score = 100 - 10 * max(0, 5 - len(annual_stmts)) - (30 if not annual_stmts else 0)
            quality.data_quality_score = max(0, min(100, score))

            historical_prices: List[Tuple[datetime, float]] = []
            ts_arr = chart.get("timestamp") or []
            quotes = (chart.get("indicators") or {}).get("quote") or [{}]
            if ts_arr and quotes:
                closes = quotes[0].get("close") or []
                for i, ts in enumerate(ts_arr):
                    if i >= len(closes):
                        break
                    try:
                        dt = datetime.utcfromtimestamp(int(ts))
                        c = closes[i]
                        if c is not None:
                            historical_prices.append((dt, float(c)))
                    except Exception:
                        continue

            notes: List[str] = []
            if exchange:
                notes.append(f"Source exchange: {exchange}")
            notes.append("Data: Yahoo Finance (real-time quote + fundamentals timeseries)")

            data = FinancialData(
                ticker=ticker_u,
                source=DataSource.YAHOO_FINANCE,
                annual_income=annual_stmts,
                quarterly_income=quarterly_stmts,
                ttm=ttm,
                annual_balance_sheet=annual_bs_records,
                quarterly_balance_sheet=quarterly_bs_records,
                annual_cashflow=annual_cf_records,
                quarterly_cashflow=quarterly_cf_records,
                market=mkt,
                quality=quality,
                historical_prices=historical_prices,
                fetched_at=datetime.utcnow(),
                notes=notes,
                revenue_composition=revenue_composition_snapshot,
            )

            if self.use_fallback and (not annual_stmts or price is None):
                raise RuntimeError(
                    f"Yahoo returned incomplete market snapshot for {ticker_u} "
                    f"(annual_periods={len(annual_stmts)}, price={price})"
                )
            if len(annual_stmts) < 3 or price is None:
                log.warning(
                    f"Data quality for {ticker_u} is limited (score={quality.data_quality_score}). "
                    f"Missing: {quality.missing_fields}"
                )
            return data
        except Exception as e:
            log.error(
                f"Failed to build FinancialData from Yahoo for {ticker_u}: {_safe_err(e)}",
                exc_info=True,
            )
            if self.use_fallback:
                return self._fallback_to_synthetic(ticker_u, _safe_err(e))
            raise YahooFinanceUnavailableError(
                f"Yahoo Finance failed for {ticker_u}: {_safe_err(e)}"
            ) from e


__all__ = ["SyntheticDataProvider", "YahooFinanceProvider"]
