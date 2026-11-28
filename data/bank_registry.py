"""Bank holding company registry, importable from the data layer.

Lives here rather than in ``classification.classifier`` because the provider
needs it to decide whether a vendor's ``operatingIncome`` line can be trusted,
and ``data`` must not import ``classification``.
"""

from __future__ import annotations

from typing import FrozenSet

#: Bank holding companies: the regulatory structure, not a vendor label.
#:
#: A broker-dealer identity ("Capital Markets") covers both pure brokers and
#: Fed-supervised bank holding companies (GS, MS, SCHW), and no field in the
#: data model distinguishes them: a broker's customer payables sit in exactly the
#: same place as a bank's deposits, so the residual-liability ratio cannot
#: separate IBKR from GS. Regulatory status is the fact that actually decides it,
#: so it is recorded here explicitly and reviewed deliberately rather than
#: inferred. Adding a ticker is a claim that the company files as a BHC.
BANK_HOLDING_COMPANIES: FrozenSet[str] = frozenset({
    "JPM", "BAC", "GS", "MS", "C", "WFC", "SCHW", "USB", "PNC", "TFC",
    "COF", "AXP", "BK", "STT", "NTRS", "RF", "KEY", "CFG", "HBAN", "FITB",
    "MTB", "ZION", "SBNY", "FRC", "ALLY", "DFS", "SYF",
})
