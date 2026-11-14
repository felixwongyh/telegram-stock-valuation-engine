"""H-03 lock: SEC SIC code -> Yahoo taxonomy bridge (``data/sic_map.py``).

The map is pure data + pure functions (no network), so these tests pin the
resolution order (exact code -> 2-digit group -> description keyword) and, most
importantly, assert that **every emitted industry is consumable by the
classifier hard rule** — otherwise the SEC layer would fill ``sector`` /
``industry`` with strings the engine cannot act on.
"""
from __future__ import annotations

import pytest

from classification.classifier import map_sector_industry
from data.sic_map import SIC2_TO_YAHOO, SIC_DESC_KEYWORDS, SIC_TO_YAHOO, map_sic_to_yahoo


@pytest.mark.parametrize(
    "sic,expected",
    [
        ("3571", ("Technology", "Computer Hardware")),
        ("3674", ("Technology", "Semiconductors")),
        ("3672", ("Technology", "Electronic Components")),
        ("7372", ("Technology", "Software - Application")),
        ("6021", ("Financial Services", "Banks - Diversified")),
        ("6331", ("Financial Services", "Insurance - Property & Casualty")),
        ("6798", ("Real Estate", "REIT - Diversified")),
        ("2834", ("Healthcare", "Drug Manufacturers - General")),
        ("2911", ("Energy", "Oil & Gas Refining & Marketing")),
        ("4911", ("Utilities", "Utilities - Regulated Electric")),
        ("1040", ("Basic Materials", "Gold")),
        ("3721", ("Industrials", "Aerospace & Defense")),
        ("3711", ("Consumer Cyclical", "Auto Manufacturers")),
        ("5411", ("Consumer Defensive", "Grocery Stores")),
        ("4813", ("Communication Services", "Telecom Services")),
        ("9995", ("Industrials", "Conglomerates")),
    ],
)
def test_exact_sic_mapping(sic, expected):
    assert map_sic_to_yahoo(sic) == expected


def test_two_digit_major_group_fallback_when_code_unknown():
    # "3699" is not a curated exact code, so it falls to the "36" major group.
    assert map_sic_to_yahoo("3699") == SIC2_TO_YAHOO["36"]


def test_description_keyword_fallback_when_code_missing():
    assert map_sic_to_yahoo(None, "Services-Prepackaged Software") == (
        "Technology",
        "Software - Application",
    )


def test_description_keyword_fallback_when_code_unknown():
    # Unknown 4-digit code under a known major group still resolves by group.
    assert map_sic_to_yahoo("1399", "Crude Petroleum & Natural Gas") == SIC2_TO_YAHOO["13"]


def test_unknown_returns_none():
    assert map_sic_to_yahoo(None, None) is None
    assert map_sic_to_yahoo("", "") is None
    assert map_sic_to_yahoo("ab", "totally unrelated text") is None


def test_int_and_str_sic_are_equivalent():
    assert map_sic_to_yahoo(3571) == map_sic_to_yahoo("3571")
    assert map_sic_to_yahoo("357") == map_sic_to_yahoo("0357")


def test_zero_padding_is_applied():
    # SEC sometimes renders short codes; they must be left-padded to 4 digits.
    assert map_sic_to_yahoo("100") == map_sic_to_yahoo("0100")


def test_every_exact_industry_is_classifiable():
    """Regression guard (H-03/M-16): the SEC layer must emit usable industries."""
    unclassifiable = [
        (sic, sector, industry)
        for sic, (sector, industry) in SIC_TO_YAHOO.items()
        if map_sector_industry(sector, industry) is None
    ]
    assert unclassifiable == []


def test_every_major_group_industry_is_classifiable():
    unclassifiable = [
        (code, sector, industry)
        for code, (sector, industry) in SIC2_TO_YAHOO.items()
        if map_sector_industry(sector, industry) is None
    ]
    assert unclassifiable == []


def test_every_description_keyword_is_classifiable_and_ordered_specific_first():
    unclassifiable = [
        (kw, sector, industry)
        for kw, sector, industry in SIC_DESC_KEYWORDS
        if map_sector_industry(sector, industry) is None
    ]
    assert unclassifiable == []
    # "semiconductor" must precede "software" so the more specific term wins.
    keywords = [kw for kw, _, _ in SIC_DESC_KEYWORDS]
    assert keywords.index("semiconductor") < keywords.index("software")
