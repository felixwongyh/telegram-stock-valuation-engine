"""data/identity_resolver.py — Business Intelligence Layer: identity resolution.

Resolves a ticker to its durable **identity anchors** — the securities /
regulatory identifiers that describe *which instrument / issuer this is*, as
opposed to a market label such as a sector, which can change over time:

  CIK   — SEC Central Index Key (authoritative US filing identity)
  SIC   — SEC Standard Industrial Classification (regulatory industry code)
  FIGI  — OpenFIGI Financial Instrument Global Identifier (open standard)

Why a separate layer
--------------------
The proposal (Business Intelligence Layer) keeps **identity** distinct from
**classification**: identity answers "who is this issuer?", classification
answers "what business is it in?". Downstream consumers (taxonomy resolver,
peer selection, provenance) can then cite a stable key rather than a fuzzy
label.

Design discipline (same as ``data/industry_resolver.py``):
  * **Optional sources** — a missing API key / library / network yields no
    value; an identifier is NEVER fabricated.
  * **Provenance** — :class:`ResolvedIdentity` records which source produced
    each field so a disagreement can be explained later.
  * **Offline-safe** — OpenFIGI is skipped unless ``OPENFIGI_API_KEY`` is set
    (or a key is passed explicitly), so the test suite stays deterministic.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import get_logger
from data.industry_resolver import SectorIndustryResolver

log = get_logger("data.identity_resolver")

_OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"


@dataclass
class ResolvedIdentity:
    """Durable identity anchors for one ticker (missing fields stay ``None``)."""

    ticker: str
    cik: Optional[str] = None
    sic: Optional[str] = None
    sic_description: Optional[str] = None
    figi: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    sources: List[str] = field(default_factory=list)
    note: str = ""

    @property
    def has_regulatory_id(self) -> bool:
        """True when at least one regulatory / open identifier was resolved."""
        return bool(self.cik or self.sic or self.figi)

    def provenance(self) -> Dict[str, str]:
        """Field → source map (``unknown`` when the field is empty)."""
        return {
            "cik": "sec" if self.cik else "unknown",
            "sic": "sec" if self.sic else "unknown",
            "figi": "openfigi" if self.figi else "unknown",
            "sector": "sector_industry_chain" if self.sector else "unknown",
            "industry": "sector_industry_chain" if self.industry else "unknown",
        }


class IdentityResolver:
    """Compose the SEC identity chain with an optional OpenFIGI lookup."""

    def __init__(
        self,
        client: Any = None,
        *,
        sector_resolver: Optional[SectorIndustryResolver] = None,
        offline: bool = False,
        openfigi_key: Optional[str] = None,
    ) -> None:
        self._client = client
        self._offline = offline
        self._openfigi_key = (
            openfigi_key if openfigi_key is not None else os.environ.get("OPENFIGI_API_KEY", "")
        )
        self._sector_resolver = sector_resolver or SectorIndustryResolver(
            client=client, offline=offline
        )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def resolve(self, ticker: str) -> ResolvedIdentity:
        """Resolve a ticker to its identity anchors (never fabricates)."""
        t = (ticker or "").upper().strip()
        ident = ResolvedIdentity(ticker=t)
        if not t:
            ident.note = "空 ticker"
            return ident

        # Layer A — SEC chain (CIK / SIC / sector / industry), in-place reuse.
        try:
            sec = self._sector_resolver.resolve_identity(t)
        except Exception as e:  # network / parse errors are non-fatal
            log.debug(f"identity resolver SEC layer failed for {t}: {e}")
            sec = {}
        ident.cik = sec.get("cik")
        ident.sic = sec.get("sic")
        ident.sic_description = sec.get("sic_description")
        ident.sector = sec.get("sector")
        ident.industry = sec.get("industry")
        if sec.get("source"):
            ident.sources.append(sec["source"])

        # Layer B — OpenFIGI (optional; requires an API key by design).
        figi = self._from_openfigi(t)
        if figi:
            ident.figi = figi
            ident.sources.append("openfigi")

        if not ident.has_regulatory_id:
            ident.note = "未解析到监管/开放标识（CIK/SIC/FIGI）"
        return ident

    # ------------------------------------------------------------------
    # OpenFIGI
    # ------------------------------------------------------------------
    def _from_openfigi(self, ticker: str) -> Optional[str]:
        """Return the primary FIGI for ``ticker`` or ``None``.

        Unauthenticated OpenFIGI is deliberately not used: without a key we
        return ``None`` rather than risk a rate-limited / unreliable call.
        """
        if self._offline or not self._openfigi_key:
            return None
        client = self._client
        if client is None:
            import httpx

            client = httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0))
            self._client = client
        payload = [{"idType": "TICKER", "idValue": ticker, "exchCode": "US"}]
        headers = {
            "Content-Type": "application/json",
            "X-OPENFIGI-APIKEY": self._openfigi_key,
        }
        try:
            r = client.post(_OPENFIGI_URL, json=payload, headers=headers)
        except Exception as e:
            log.debug(f"openfigi lookup failed for {ticker}: {e}")
            return None
        if getattr(r, "status_code", 0) != 200:
            return None
        try:
            body = r.json()
        except Exception:
            return None
        return _first_figi(body)


def _first_figi(body: Any) -> Optional[str]:
    """Extract the first FIGI from an OpenFIGI ``/v3/mapping`` response."""
    if not isinstance(body, list) or not body:
        return None
    entry = body[0]
    if not isinstance(entry, dict):
        return None
    rows = entry.get("data")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        figi = rows[0].get("figi")
        if isinstance(figi, str) and figi.strip():
            return figi.strip()
    return None


def resolve_identity(ticker: str, *, offline: bool = False) -> ResolvedIdentity:
    """Convenience one-shot resolver (creates a throwaway resolver)."""
    return IdentityResolver(offline=offline).resolve(ticker)


__all__ = ["IdentityResolver", "ResolvedIdentity", "resolve_identity"]
