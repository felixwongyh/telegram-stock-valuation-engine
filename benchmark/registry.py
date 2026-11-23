"""50-ticker Reverse DCF benchmark registry (Benchmark v1.0).

The registry is the source of truth for *what correct behaviour looks like* for
each ticker, so a run can be judged rather than merely observed. It encodes an
expectation per ticker:

* ``expect_applicable`` - should Reverse DCF be attempted at all?
* ``expected_route`` - which methodology family the router must choose.
* ``accept_statuses`` - which solver statuses are legitimate here.
* ``forbidden_statuses`` - statuses that prove a specific bug if seen.

A ticker is not "failing" because it does not produce a growth rate. Banks,
insurers, REITs and negative-FCF companies are *supposed* to return
NOT_APPLICABLE / INSUFFICIENT_DATA / NO_SOLUTION_IN_RANGE. The failure mode this
registry exists to catch is the opposite: a model that fabricates a number where
it should have declined, or that declines where it should have solved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from config import SolverStatus


@dataclass(frozen=True)
class BenchmarkEntry:
    ticker: str
    company: str
    focus: str
    sector: str
    #: Must Reverse DCF be attempted for this ticker?
    expect_applicable: bool
    #: Methodology family the router is expected to choose.
    expected_route: str
    #: Solver statuses that are legitimate outcomes for this ticker.
    accept_statuses: tuple[str, ...]
    #: Statuses whose appearance would prove a routing/logic defect.
    forbidden_statuses: tuple[str, ...] = field(default_factory=tuple)
    #: Free-form note surfaced in the report.
    note: str = ""

    @property
    def solved_ok(self) -> bool:
        return SolverStatus.SOLVED.value in self.accept_statuses


_SOLVED = SolverStatus.SOLVED.value
_APPROX = SolverStatus.APPROXIMATE.value
_NO_SOL = SolverStatus.NO_SOLUTION_IN_RANGE.value
_INSUFF = SolverStatus.INSUFFICIENT_DATA.value
_INFEAS = SolverStatus.INFEASIBLE.value
_NONMONO = SolverStatus.NON_MONOTONIC.value
_MULTI = SolverStatus.MULTIPLE_ROOTS.value
_FLAT = SolverStatus.FLAT_OBJECTIVE.value

#: Any FCF-based operating company may legitimately fail to solve (band limits,
#: negative terminal FCF) - a bounded, explainable outcome, not a bug.
_OPERATING_OK = (_SOLVED, _APPROX, _NO_SOL, _NONMONO, _MULTI, _FLAT)

#: Financial institutions must never receive a fabricated FCF-DCF growth rate.
_FIN_OK = (_INSUFF, _INFEAS, _NO_SOL)

#: REITs should route to NAV/FFO, so the FCF Reverse DCF must decline.
_REIT_OK = (_INSUFF, _INFEAS, _NO_SOL)

#: Any status that means "a number was produced".
_ANY_SOLVED = (_SOLVED, _APPROX)


ENTRIES: tuple[BenchmarkEntry, ...] = (
    # ---- Technology ----
    BenchmarkEntry(
        "NVDA", "NVIDIA", "AI high growth, margin, CapEx", "Semiconductor",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="High-growth solver must stay stable; TV share must be sane.",
    ),
    BenchmarkEntry(
        "MSFT", "Microsoft", "Cloud, mature growth", "Technology",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
    ),
    BenchmarkEntry(
        "AVGO", "Broadcom", "Semiconductor, software, M&A", "Semiconductor",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Mixed business: cash-flow caliber must stay consistent.",
    ),
    BenchmarkEntry(
        "ORCL", "Oracle", "Cloud transition, debt", "Technology",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Debt, CapEx and FCF must be correct.",
    ),
    BenchmarkEntry(
        "CRM", "Salesforce", "SaaS, SBC", "Technology",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="SBC must be counted once - neither double nor omitted.",
    ),
    BenchmarkEntry(
        "AMD", "AMD", "Semiconductor cycle, high growth", "Semiconductor",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
    ),
    BenchmarkEntry(
        "GOOGL", "Alphabet", "Advertising, Cloud, cash", "Technology",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Cash / EV / FCF bridge must be correct.",
    ),
    BenchmarkEntry(
        "META", "Meta", "Advertising, AI CapEx", "Technology",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="CapEx must be consistent with the growth assumption.",
    ),
    BenchmarkEntry(
        "NFLX", "Netflix", "Subscriptions, content spend", "Communication Services",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Content amortization: cash-flow caliber must be defensible.",
    ),
    # ---- Communication / Consumer ----
    BenchmarkEntry(
        "VZ", "Verizon", "Telecom, low growth, high debt", "Communication Services",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Leverage + low growth: discounting must handle it.",
    ),
    BenchmarkEntry(
        "AMZN", "Amazon", "Retail + AWS", "Consumer Cyclical",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Mixed business: margin and FCF caliber.",
    ),
    BenchmarkEntry(
        "TSLA", "Tesla", "High growth, cyclical, volatile", "Consumer Cyclical",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Extreme assumptions: FCF stability must be tested.",
    ),
    BenchmarkEntry(
        "MCD", "McDonald's", "Mature, franchising", "Consumer Cyclical",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Franchise cash-flow characteristics.",
    ),
    BenchmarkEntry(
        "NKE", "Nike", "Brand, recovery cycle", "Consumer Cyclical",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Negative / recovery growth must be representable.",
    ),
    BenchmarkEntry(
        "BKNG", "Booking Holdings", "Asset-light, buybacks", "Consumer Cyclical",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Share count + buybacks must be consistent.",
    ),
    BenchmarkEntry(
        "PG", "Procter & Gamble", "Mature consumer staples", "Consumer Defensive",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Low-growth model must behave normally.",
    ),
    BenchmarkEntry(
        "KO", "Coca-Cola", "Brand, stable cash flow", "Consumer Defensive",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Terminal value + low growth must stay sane.",
    ),
    BenchmarkEntry(
        "WMT", "Walmart", "Low margin, high turnover", "Consumer Defensive",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Thin margin is not low quality.",
    ),
    BenchmarkEntry(
        "COST", "Costco", "Low margin, membership", "Consumer Defensive",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Low margin must not be misread as poor quality.",
    ),
    # ---- Energy / Materials / Industrial ----
    BenchmarkEntry(
        "XOM", "ExxonMobil", "Oil cycle", "Energy",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Peak / trough FCF must be recognised.",
    ),
    BenchmarkEntry(
        "CVX", "Chevron", "Oil cycle, CapEx", "Energy",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
    ),
    BenchmarkEntry(
        "SLB", "SLB", "Oil-services cycle", "Energy",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
    ),
    BenchmarkEntry(
        "COP", "ConocoPhillips", "Upstream energy", "Energy",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Commodity sensitivity.",
    ),
    BenchmarkEntry(
        "LIN", "Linde", "Industrial gases", "Basic Materials",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
    ),
    BenchmarkEntry(
        "FCX", "Freeport-McMoRan", "Copper cycle", "Basic Materials",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Commodity / normalized FCF.",
    ),
    BenchmarkEntry(
        "NUE", "Nucor", "Steel cycle", "Basic Materials",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="High / low cycle margins.",
    ),
    BenchmarkEntry(
        "CAT", "Caterpillar", "Industrial cycle", "Industrials",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
    ),
    BenchmarkEntry(
        "GE", "GE Aerospace", "Industrial, orders, cash flow", "Industrials",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="FCF conversion and long-term growth.",
    ),
    BenchmarkEntry(
        "UPS", "UPS", "Transport, CapEx", "Industrials",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="CapEx and working capital.",
    ),
    BenchmarkEntry(
        "BA", "Boeing", "Negative FCF, debt, recovery", "Industrials",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK + (_INFEAS,),
        note="Negative FCF must not yield a misleading growth rate.",
    ),
    BenchmarkEntry(
        "UNP", "Union Pacific", "Rail, capital intensive", "Industrials",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
    ),
    # ---- Healthcare ----
    BenchmarkEntry(
        "LLY", "Eli Lilly", "High-growth pharma", "Healthcare",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="High growth, product cycle, terminal value.",
    ),
    BenchmarkEntry(
        "JNJ", "Johnson & Johnson", "Mature pharma / medtech", "Healthcare",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
    ),
    BenchmarkEntry(
        "PFE", "Pfizer", "Patent cycle, revenue decline", "Healthcare",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="FCF normalization under negative growth.",
    ),
    BenchmarkEntry(
        "ISRG", "Intuitive Surgical", "High-growth medtech", "Healthcare",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="Growth fade and terminal growth.",
    ),
    BenchmarkEntry(
        "MRNA", "Moderna", "Biotech, negative-FCF risk", "Healthcare",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK + (_INFEAS,),
        note="Negative FCF / solver guard.",
    ),
    # ---- Financials ----
    BenchmarkEntry(
        "JPM", "JPMorgan", "Bank", "Financial Services",
        expect_applicable=False, expected_route="BANK",
        accept_statuses=_FIN_OK, forbidden_statuses=_ANY_SOLVED,
        note="Traditional FCFF DCF must not be applied to a bank.",
    ),
    BenchmarkEntry(
        "BAC", "Bank of America", "Bank, rate sensitive", "Financial Services",
        expect_applicable=False, expected_route="BANK",
        accept_statuses=_FIN_OK, forbidden_statuses=_ANY_SOLVED,
    ),
    BenchmarkEntry(
        "GS", "Goldman Sachs", "Investment bank", "Financial Services",
        expect_applicable=False, expected_route="BANK",
        accept_statuses=_FIN_OK, forbidden_statuses=_ANY_SOLVED,
    ),
    BenchmarkEntry(
        "V", "Visa", "Payments, asset-light", "Financial Services",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK, forbidden_statuses=(_INSUFF,),
        note="High margin, strong cash flow - must NOT be routed as a bank.",
    ),
    BenchmarkEntry(
        "CB", "Chubb", "Insurance", "Financial Services",
        expect_applicable=False, expected_route="INSURANCE",
        accept_statuses=_FIN_OK, forbidden_statuses=_ANY_SOLVED,
    ),
    BenchmarkEntry(
        "BRK-B", "Berkshire Hathaway", "Conglomerate", "Financial Services",
        expect_applicable=False, expected_route="SOTP_NAV",
        accept_statuses=_FIN_OK, forbidden_statuses=_ANY_SOLVED,
        note="SOTP / NAV applicability must be recognised.",
    ),
    # ---- Utilities ----
    BenchmarkEntry(
        "NEE", "NextEra Energy", "Utility, growth, CapEx", "Utilities",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK,
        note="High CapEx, debt, discounting.",
    ),
    BenchmarkEntry(
        "DUK", "Duke Energy", "Stable utility", "Utilities",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK,
    ),
    BenchmarkEntry(
        "CEG", "Constellation Energy", "Power, energy growth", "Utilities",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK,
    ),
    BenchmarkEntry(
        "SO", "Southern Company", "Traditional utility", "Utilities",
        expect_applicable=True, expected_route="FCF_DCF",
        accept_statuses=_OPERATING_OK,
    ),
    # ---- REITs ----
    BenchmarkEntry(
        "PLD", "Prologis", "Logistics REIT", "Real Estate",
        expect_applicable=False, expected_route="REIT_NAV",
        accept_statuses=_REIT_OK, forbidden_statuses=_ANY_SOLVED,
        note="AFFO / NAV applicability.",
    ),
    BenchmarkEntry(
        "O", "Realty Income", "REIT", "Real Estate",
        expect_applicable=False, expected_route="REIT_NAV",
        accept_statuses=_REIT_OK, forbidden_statuses=_ANY_SOLVED,
    ),
    BenchmarkEntry(
        "AMT", "American Tower", "Tower REIT", "Real Estate",
        expect_applicable=False, expected_route="REIT_NAV",
        accept_statuses=_REIT_OK, forbidden_statuses=_ANY_SOLVED,
    ),
    BenchmarkEntry(
        "VICI", "VICI Properties", "Gaming REIT", "Real Estate",
        expect_applicable=False, expected_route="REIT_NAV",
        accept_statuses=_REIT_OK, forbidden_statuses=_ANY_SOLVED,
    ),
)

BY_TICKER: dict[str, BenchmarkEntry] = {e.ticker: e for e in ENTRIES}


def tickers() -> list[str]:
    return [e.ticker for e in ENTRIES]


def validate_registry() -> list[str]:
    """Structural checks on the registry itself (dupes, gaps, contradictions)."""
    problems: list[str] = []
    seen: set[str] = set()
    for e in ENTRIES:
        if e.ticker in seen:
            problems.append(f"duplicate ticker: {e.ticker}")
        seen.add(e.ticker)
        if not e.accept_statuses:
            problems.append(f"{e.ticker}: no accepted status")
        overlap = set(e.accept_statuses) & set(e.forbidden_statuses)
        if overlap:
            problems.append(f"{e.ticker}: status both accepted and forbidden: {overlap}")
        if not e.expect_applicable and e.solved_ok:
            problems.append(f"{e.ticker}: not applicable but Solved is accepted")
        if e.expect_applicable and _SOLVED in e.forbidden_statuses:
            problems.append(f"{e.ticker}: applicable but Solved forbidden")
    if len(ENTRIES) != 50:
        problems.append(f"expected 50 entries, found {len(ENTRIES)}")
    return problems


__all__ = ["BenchmarkEntry", "ENTRIES", "BY_TICKER", "tickers", "validate_registry"]
