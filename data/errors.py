"""
data/errors.py - Data provider errors (fail loud, no silent demo substitution).
"""
from __future__ import annotations


class YahooFinanceUnavailableError(Exception):
    """Yahoo Finance could not supply usable data for the requested ticker."""


class UnknownSyntheticTickerError(Exception):
    """No curated synthetic fixture exists for this ticker."""


__all__ = ["UnknownSyntheticTickerError", "YahooFinanceUnavailableError"]
