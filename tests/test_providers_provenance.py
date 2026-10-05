"""
tests/test_providers_provenance.py - Yahoo vs synthetic data provenance
"""
from __future__ import annotations

import pytest

from config import DataSource
from data.errors import UnknownSyntheticTickerError, YahooFinanceUnavailableError
from data.providers import SyntheticDataProvider, YahooFinanceProvider


class TestSyntheticProvenance:
    def test_unknown_ticker_raises_without_template(self):
        synth = SyntheticDataProvider()
        with pytest.raises(UnknownSyntheticTickerError):
            synth.get_financial_data("BAC", allow_unknown_ticker=False)

    def test_known_synthetic_ticker_marked(self):
        synth = SyntheticDataProvider()
        data = synth.get_financial_data("AAPL")
        assert data.source == DataSource.SYNTHETIC
        assert any("SYNTHETIC" in n for n in data.notes)


class TestYahooFallbackDefault:
    def test_default_no_fallback_on_failure(self):
        yf = YahooFinanceProvider(use_fallback=False, cache_enabled=False)

        def _boom(_ticker: str):
            raise RuntimeError("simulated yahoo outage")

        yf._get_financial_data_sync = _boom  # type: ignore[method-assign]
        import asyncio

        with pytest.raises(YahooFinanceUnavailableError):
            asyncio.run(yf.get_financial_data("BAC"))

    def test_fallback_refuses_unknown_ticker(self):
        yf = YahooFinanceProvider(use_fallback=True, cache_enabled=False)

        def _boom(_ticker: str):
            raise RuntimeError("simulated yahoo outage")

        yf._get_financial_data_sync = _boom  # type: ignore[method-assign]
        import asyncio

        with pytest.raises(YahooFinanceUnavailableError) as exc:
            asyncio.run(yf.get_financial_data("BAC"))
        assert "no synthetic fixture" in str(exc.value).lower() or "BAC" in str(exc.value)
