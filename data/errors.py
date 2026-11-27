"""
data/errors.py - Data provider errors (fail loud, no silent demo substitution).
"""
from __future__ import annotations


class YahooFinanceUnavailableError(Exception):
    """Yahoo Finance could not supply usable data for the requested ticker."""


class UnknownSyntheticTickerError(Exception):
    """No curated synthetic fixture exists for this ticker."""


class FrozenSnapshotMissError(Exception):
    """A frozen run asked for data the frozen cache does not hold.

    Raised instead of fetching: a frozen snapshot's whole purpose is that the
    market inputs cannot change mid-run. Silently downloading on a miss would mix
    a frozen snapshot with live data and make the run unreproducible (§1.3.2).
    """


__all__ = [
    "UnknownSyntheticTickerError",
    "YahooFinanceUnavailableError",
    "FrozenSnapshotMissError",
]
