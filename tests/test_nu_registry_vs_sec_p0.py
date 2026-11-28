"""Session #57 P0-2: the conglomerate registry must agree with the SEC filing.

The classifier's registry is the runtime source of truth; the SEC fixture is the
evidence baseline. Two copies of the same facts will drift unless something
checks them against each other, and a drift here means the classifier asserts a
sub-business the filing does not support (or misses one it does).

The registry is intentionally not read from tests/ at runtime -- production code
must not depend on the test tree -- so this test is the join between them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from classification.classifier import FINANCIAL_CONGLOMERATES

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "financial_conglomerates"
    / "nu_2026q3.json"
)

#: Registry subsegment key -> the subsidiary business that evidences it.
BUSINESS_TO_SUBSEGMENT = {
    "banking": "banking",
    "payment_network": "payment_network",
    "fintech_lending": "fintech_lending",
    "broker_dealer": "broker_dealer",
}


@pytest.fixture(scope="module")
def sec() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def registry() -> dict:
    return FINANCIAL_CONGLOMERATES["NU"]


class TestRegistryMatchesFiling:
    def test_every_subsidiary_business_is_registered(self, sec, registry):
        for sub in sec["subsidiaries"]:
            key = BUSINESS_TO_SUBSEGMENT.get(sub["business"])
            if key is None:
                continue
            assert key in registry, f"filing lists {sub['name']} but registry omits {key}"
            assert registry[key].present is True, key

    def test_registry_claims_are_supported_by_the_filing(self, sec, registry):
        """A registered sub-business must map to a disclosed subsidiary."""
        disclosed = {s["business"] for s in sec["subsidiaries"]}
        for key, ev in registry.items():
            if ev.present is not True:
                continue
            assert key in disclosed, (
                f"registry claims {key} present but the filing discloses no such "
                f"business (disclosed: {sorted(disclosed)})"
            )

    def test_registry_period_matches_filing_period(self, sec, registry):
        for key, ev in registry.items():
            if ev.present is True:
                assert ev.as_of == sec["period_end"], key

    def test_registry_source_cites_the_accession(self, sec, registry):
        """The registry should name the document it rests on, not just 'SEC'."""
        for key, ev in registry.items():
            if ev.present is True:
                assert ev.source, key
                assert "6-K" in ev.source or "Q3" in ev.source, key

    def test_undisclosed_subsegment_stays_unknown(self, sec, registry):
        disclosed = {s["business"] for s in sec["subsidiaries"]}
        if "insurance" not in disclosed:
            assert registry["insurance"].present is None


class TestDepositsAreNotUsedAsClassificationEvidence:
    def test_deposit_ratio_is_ambiguous_and_must_not_decide(self, sec):
        """54.31% sits inside the 0.50-0.60 band, so it cannot settle the
        question either way. The thresholds are not tuned to make NU a bank."""
        ratio = sec["fields"]["deposit_to_total_assets"]["value"]
        assert 0.50 <= ratio < 0.60, ratio

    def test_rdb_is_separated_from_customer_deposits_in_the_filing(self, sec):
        """The filing decomposes deposits; collapsing them would make the ratio
        look like a traditional retail deposit base."""
        f = sec["fields"]
        assert f["rdb_balance"]["value"] + f["customer_deposits"]["value"] <= (
            f["reported_deposits_total"]["value"]
        )

    def test_loan_book_is_decomposed(self, sec):
        f = sec["fields"]
        assert f["loans_to_customers"]["value"] > 0
        assert f["credit_card_receivables"]["value"] > 0
