"""
data/akshare_provider.py - Akshare fallback for sector/industry enrichment.

When Yahoo Finance quoteSummary returns empty sector/industry, this module
provides a fallback using akshare's stock_individual_info_em() API.

Usage:
    from data.akshare_provider import AkshareSectorProvider
    info = AkshareSectorProvider().get_sector_industry("JNJ")
    # -> {"sector": "Healthcare", "industry": "Pharmaceuticals", "source": "akshare"}

Akshare is optional; if not installed, all methods return empty dicts gracefully.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from config import get_logger

log = get_logger("data.akshare_provider")

# ---------------------------------------------------------------------------
# Yahoo Finance 11 sectors → canonical sector names
# ---------------------------------------------------------------------------
_YAHOO_SECTORS = {
    "technology", "consumer cyclical", "consumer defensive",
    "financial", "communication services", "energy", "healthcare",
    "industrials", "real estate", "materials", "utilities",
}

# ---------------------------------------------------------------------------
# Akshare 行业分类 → Yahoo Finance sector mapping
# Akshare (东方财富) industry categories mapped to Yahoo canonical sectors
# ---------------------------------------------------------------------------
_AKSHARE_SECTOR_MAP: Dict[str, str] = {
    # --- Technology ---
    "电子元件": "Technology",
    "电子制造": "Technology",
    "半导体": "Technology",
    "半导体及元件": "Technology",
    "计算机设备": "Technology",
    "通信设备": "Communication Services",
    "软件服务": "Technology",
    "软件开发": "Technology",
    "互联网服务": "Communication Services",
    "信息技术": "Technology",
    "消费电子": "Consumer Cyclical",
    # --- Consumer Cyclical ---
    "汽车零部件": "Consumer Cyclical",
    "汽车制造": "Consumer Cyclical",
    "零售": "Consumer Cyclical",
    "商业百货": "Consumer Cyclical",
    "服装家纺": "Consumer Cyclical",
    "家电": "Consumer Cyclical",
    "旅游酒店": "Consumer Cyclical",
    "餐饮": "Consumer Cyclical",
    "文教休闲": "Consumer Cyclical",
    "家居": "Consumer Cyclical",
    # --- Consumer Defensive / Staples ---
    "食品饮料": "Consumer Defensive",
    "农牧饲渔": "Consumer Defensive",
    "日用品": "Consumer Defensive",
    "烟草": "Consumer Defensive",
    # --- Financial ---
    "银行": "Financial",
    "保险": "Financial",
    "证券": "Financial",
    "多元金融": "Financial",
    "房地产": "Real Estate",
    "房地产服务": "Real Estate",
    # --- Energy ---
    "石油": "Energy",
    "天然气": "Energy",
    "煤炭": "Energy",
    "油气开采": "Energy",
    # --- Healthcare ---
    "医疗器械": "Healthcare",
    "医药制造": "Healthcare",
    "中药": "Healthcare",
    "生物制品": "Healthcare",
    "医疗服务": "Healthcare",
    "医药商业": "Healthcare",
    # --- Industrials ---
    "航空航天": "Industrials",
    "国防军工": "Industrials",
    "机械": "Industrials",
    "工程机械": "Industrials",
    "通用设备": "Industrials",
    "专用设备": "Industrials",
    "物流": "Industrials",
    "交通运输": "Industrials",
    "建筑": "Industrials",
    "建材": "Industrials",
    "电气设备": "Industrials",
    "环保": "Industrials",
    # --- Materials ---
    "化工": "Materials",
    "化学原料": "Materials",
    "化学制品": "Materials",
    "钢铁": "Materials",
    "有色金属": "Materials",
    "贵金属": "Materials",
    "非金属矿物": "Materials",
    "造纸": "Materials",
    "包装": "Materials",
    # --- Utilities ---
    "电力": "Utilities",
    "水务": "Utilities",
    "燃气": "Utilities",
    "公用事业": "Utilities",
    # --- Communication Services ---
    "通信服务": "Communication Services",
    "电信": "Communication Services",
    "广电": "Communication Services",
    "传媒": "Communication Services",
    "游戏": "Communication Services",
    "影视": "Communication Services",
    # --- Real Estate ---
    "房地产开发": "Real Estate",
    "产业地产": "Real Estate",
    "物业管理": "Real Estate",
    "REITs": "Real Estate",
}


class AkshareSectorProvider:
    """Akshare-based sector/industry fallback provider.

    Tries akshare's stock_individual_info_em() for A-share / HK / US stocks
    to fill in sector/industry when Yahoo Finance returns empty.

    Akshare is optional — if import fails, all calls return empty.
    """

    _instance: Optional["AkshareSectorProvider"] = None
    _akshare_ok: bool = False
    _cache: Dict[str, Dict[str, str]] = {}

    def __new__(cls) -> "AkshareSectorProvider":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_akshare()
        return cls._instance

    def _init_akshare(self) -> None:
        try:
            import akshare as ak  # noqa: F401
            self._akshare_ok = True
            log.info("akshare available — sector fallback enabled")
        except ImportError:
            self._akshare_ok = False
            log.info("akshare not installed — sector fallback disabled (pip install akshare)")

    @property
    def available(self) -> bool:
        return self._akshare_ok

    def get_sector_industry(self, ticker: str) -> Dict[str, str]:
        """Get sector/industry for a ticker via akshare.

        Returns dict with keys: sector, industry, source.
        Empty dict if akshare unavailable or ticker not found.
        """
        if not self._akshare_ok:
            return {}

        ticker_u = ticker.upper().strip()
        if ticker_u in self._cache:
            return self._cache[ticker_u]

        result: Dict[str, str] = {}
        try:
            result = self._fetch_from_akshare(ticker_u)
        except Exception as e:
            log.debug(f"akshare fetch failed for {ticker_u}: {e}")

        self._cache[ticker_u] = result
        return result

    def _fetch_from_akshare(self, ticker: str) -> Dict[str, str]:
        """Try multiple akshare APIs to get sector/industry."""
        import akshare as ak

        # --- US stocks via akshare ---
        # ak.stock_individual_info_em(symbol="JNJ") returns 行业 field
        info: Dict[str, str] = {}
        try:
            df = ak.stock_individual_info_em(symbol=ticker)
            if df is not None and not df.empty:
                # df has columns: item, value
                for _, row in df.iterrows():
                    key = str(row.get("item", "")).strip()
                    val = str(row.get("value", "")).strip()
                    if not val or val == "nan":
                        continue
                    if key in ("行业", "行业类别"):
                        mapped = self._map_akshare_industry(val)
                        if mapped:
                            info["sector"] = mapped[0]
                            info["industry"] = mapped[1]
                        else:
                            info["industry"] = val
                    elif key == "股票简称" and not info.get("company_name"):
                        info["company_name"] = val
        except Exception as e:
            log.debug(f"stock_individual_info_em failed for {ticker}: {e}")

        if info.get("sector") and info.get("industry"):
            info["source"] = "akshare"
            return info

        # --- Try US stock sector list ---
        if not info.get("sector"):
            try:
                sector = self._lookup_us_stock_sector(ticker)
                if sector:
                    info["sector"] = sector
                    info["source"] = "akshare-us-list"
            except Exception as e:
                log.debug(f"US sector lookup failed for {ticker}: {e}")

        if info:
            info.setdefault("source", "akshare")
        return info

    def _map_akshare_industry(self, ak_industry: str) -> Optional[Tuple[str, str]]:
        """Map akshare (东方财富) industry string to (yahoo_sector, industry)."""
        if not ak_industry:
            return None
        # Try exact match
        for ak_key, yahoo_sector in _AKSHARE_SECTOR_MAP.items():
            if ak_key in ak_industry:
                return (yahoo_sector, ak_industry)
        return None

    def _lookup_us_stock_sector(self, ticker: str) -> Optional[str]:
        """Look up US stock sector from akshare's US stock list."""
        import akshare as ak
        try:
            # Try US stock list
            df = ak.stock_us_spot_em()
            if df is not None and not df.empty:
                row = df[df["代码"].str.upper() == ticker.upper()]
                if not row.empty:
                    # Look for sector/industry columns
                    for col in ["行业", "板块", "sector", "industry"]:
                        if col in df.columns:
                            val = str(row.iloc[0].get(col, "")).strip()
                            if val and val != "nan":
                                mapped = self._map_akshare_industry(val)
                                if mapped:
                                    return mapped[0]
                                return val
        except Exception as e:
            log.debug(f"US stock list lookup failed for {ticker}: {e}")
        return None

    def batch_get_sector_industry(self, tickers: List[str]) -> Dict[str, Dict[str, str]]:
        """Batch fetch sector/industry for multiple tickers."""
        results: Dict[str, Dict[str, str]] = {}
        for t in tickers:
            info = self.get_sector_industry(t)
            if info:
                results[t.upper()] = info
        return results


__all__ = ["AkshareSectorProvider"]
