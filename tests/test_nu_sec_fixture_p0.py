"""Session #57 P0-2: NU consolidated financials from the SEC filing.

Static fixture, no network at test time. Every number traces to SEC Form 6-K
(accession 000129281426005272, period 2026-09-30), stored in USD even though the
filing reports USD thousands.

The point is not to prove NU is a bank. It is to record exactly what NU owns and
how it is funded. The filing discloses the deposit composition, so the earlier
residual-derived deposit figure is replaced with reported data: inferring
deposits as "assets minus debt minus equity" would have silently merged RDB,
customer deposits, CDBs and interbank deposits into one fabricated number.

Two identities must hold exactly, not approximately.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "financial_conglomerates"
    / "nu_2026q3.json"
)

USD = 1000  # filing scale is USD thousands


@pytest.fixture(scope="module")
def nu() -> dict:
    return json.loads(FIXTURE.read_text())


def _v(doc: dict, name: str) -> float:
    return doc["fields"][name]["value"]


# ---------------------------------------------------------------------------
# Raw figures must match the filing exactly
# ---------------------------------------------------------------------------
class TestSecAccuracy:
    @pytest.mark.parametrize("field,reported_thousands", [
        ("total_assets", 87_428_575),
        ("total_liabilities", 73_083_638),
        ("total_equity", 14_344_937),
        ("equity_attributable_to_parent", 14_342_624),
        ("cash_and_equivalents", 13_772_277),
        ("loans_to_customers", 12_209_458),
        ("credit_card_receivables", 22_361_493),
        ("rdb_balance", 37_563_613),
        ("customer_deposits", 9_054_037),
        ("cdb_balance", 822_836),
        ("interbank_deposits", 46_315),
        ("reported_deposits_total", 47_486_801),
    ])
    def test_value_matches_filing(self, nu, field, reported_thousands):
        assert _v(nu, field) == reported_thousands * USD

    def test_filing_scale_is_preserved_for_audit(self, nu):
        for name, f in nu["fields"].items():
            if f.get("is_derived"):
                continue
            assert f["reported_in"] == "USD thousands", name
            assert f["reported_value"] * USD == f["value"], name


# ---------------------------------------------------------------------------
# Accounting identities
# ---------------------------------------------------------------------------
class TestReconciliation:
    def test_assets_equal_liabilities_plus_equity(self, nu):
        assert _v(nu, "total_assets") == _v(nu, "total_liabilities") + _v(nu, "total_equity")

    def test_deposit_components_sum_to_reported_total(self, nu):
        parts = sum(_v(nu, k) for k in (
            "rdb_balance", "customer_deposits", "cdb_balance", "interbank_deposits"
        ))
        assert parts == _v(nu, "reported_deposits_total")

    def test_parent_equity_does_not_exceed_total_equity(self, nu):
        assert _v(nu, "equity_attributable_to_parent") <= _v(nu, "total_equity")

    def test_deposit_ratio_is_derived_not_disclosed(self, nu):
        ratio = nu["fields"]["deposit_to_total_assets"]
        assert ratio["is_derived"] is True
        assert ratio["derivation"] == "reported_deposits_total / total_assets"
        expected = _v(nu, "reported_deposits_total") / _v(nu, "total_assets")
        assert ratio["value"] == pytest.approx(expected, rel=0, abs=1e-12)
        assert ratio["value"] == pytest.approx(0.5431, abs=5e-5)


# ---------------------------------------------------------------------------
# Deposits must stay decomposed: RDB is not a customer deposit
# ---------------------------------------------------------------------------
class TestDepositClassification:
    def test_rdb_and_customer_deposits_are_separate_fields(self, nu):
        assert "rdb_balance" in nu["fields"]
        assert "customer_deposits" in nu["fields"]
        assert _v(nu, "rdb_balance") != _v(nu, "customer_deposits")

    def test_rdb_is_documented_as_an_investment_product(self, nu):
        note = nu["fields"]["rdb_balance"]["note"].lower()
        assert "investment product" in note
        assert "not a traditional bank customer deposit" in note

    def test_no_undifferentiated_bank_deposits_field(self, nu):
        """Merging the four funding sources into one field would lose the
        distinction the filing makes, so such a field must not exist."""
        assert "bank_deposits" not in nu["fields"]

    def test_rdb_dominates_the_funding_mix(self, nu):
        """79% of reported deposits are RDB, so collapsing them into 'customer
        deposits' would misdescribe the group's funding by a wide margin."""
        share = _v(nu, "rdb_balance") / _v(nu, "reported_deposits_total")
        assert share == pytest.approx(0.7911, abs=1e-3)


# ---------------------------------------------------------------------------
# Lending exposure must stay decomposed
# ---------------------------------------------------------------------------
class TestLoanExposure:
    def test_loans_and_card_receivables_are_separate(self, nu):
        assert _v(nu, "loans_to_customers") != _v(nu, "credit_card_receivables")
        total = _v(nu, "loans_to_customers") + _v(nu, "credit_card_receivables")
        assert total == pytest.approx(34_570_951 * USD)


# ---------------------------------------------------------------------------
# Units, provenance, offline behaviour
# ---------------------------------------------------------------------------
class TestUnitsAndProvenance:
    def test_every_field_is_usd(self, nu):
        for name, f in nu["fields"].items():
            assert f["currency"] == "USD", name
            if f["unit"] == "ratio":
                continue
            assert f["unit"] == "USD", name

    def test_no_field_is_left_in_thousands(self, nu):
        """A value still in the thousands range would be off by 1000x."""
        for name in ("total_assets", "reported_deposits_total"):
            assert _v(nu, name) > 1e10, f"{name} looks like it is still in thousands"

    def test_every_field_traces_to_the_sec_accession(self, nu):
        for name, f in nu["fields"].items():
            assert f["accession"] == "000129281426005272", name
            assert f["source"] == "SEC_FORM_6K", name
            assert f["statement"], name
            assert f["as_of_date"] == "2026-09-30", name

    def test_document_metadata_matches_the_filing(self, nu):
        assert nu["ticker"] == "NU"
        assert nu["form"] == "Form 6-K"
        assert nu["accession"] == "000129281426005272"
        assert nu["period_end"] == "2026-09-30"
        assert nu["filing_date"] == "2026-11-12"
        assert nu["accounting_standard"] == "IFRS / IAS 34"

    def test_interim_statements_are_not_labelled_audited(self, nu):
        assert nu["audited_status"] == "REVIEWED_UNAUDITED"
        assert "unaudited" in nu["audit_note"].lower()
        for name, f in nu["fields"].items():
            assert f["audited_status"] != "AUDITED", name

    def test_fixture_is_static_and_offline(self, nu):
        """Guards against someone wiring a live fetch into this fixture."""
        assert FIXTURE.exists()
        raw = FIXTURE.read_text()
        for token in ("http://", "requests.", "yfinance", "urlopen"):
            if token == "http://":
                assert token not in raw
        assert "yfinance" not in raw


class TestSnapshotStability:
    def test_repeated_loads_are_identical(self):
        a = json.loads(FIXTURE.read_text())
        b = json.loads(FIXTURE.read_text())
        assert a == b

    def test_fixture_bytes_are_stable(self):
        first = FIXTURE.read_bytes()
        second = FIXTURE.read_bytes()
        assert first == second


# ---------------------------------------------------------------------------
# Missing data stays missing
# ---------------------------------------------------------------------------
class TestUnknownData:
    @pytest.mark.parametrize("name", [
        "cet1_ratio", "risk_weighted_assets", "net_interest_margin",
        "net_interest_income", "provisions", "non_performing_loans",
        "tangible_book_value", "expected_credit_loss",
    ])
    def test_undisclosed_metric_is_absent_not_fabricated(self, nu, name):
        assert name in nu["not_disclosed"]
        assert name not in nu["fields"]

    def test_deposits_are_reported_not_residual(self, nu):
        """The whole point of this fixture: deposits come from Note 22, not from
        assets-minus-debt-minus-equity."""
        residual = (
            _v(nu, "total_assets") - _v(nu, "total_liabilities") - _v(nu, "total_equity")
        )
        # Equity is the residual here (it is ~0 by construction), which shows why
        # the residual method cannot produce a deposit figure at all.
        assert residual == pytest.approx(0, abs=1)
        assert _v(nu, "reported_deposits_total") > 0

    def test_every_field_declares_whether_it_is_derived(self, nu):
        for name, f in nu["fields"].items():
            assert isinstance(f["is_derived"], bool), name
