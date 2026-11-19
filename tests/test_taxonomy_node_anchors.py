"""
tests/test_taxonomy_node_anchors.py - Node-level anchors must beat the sector.

A Yahoo sector is a regulatory/economic label, not a valuation model. Merchant
IPPs (util.ipp) and regulated electric utilities (util.electric) both report
sector "Utilities", but the IPP has no rate base and earns commodity-linked
margins. Resolving the peer anchor (and the implied-growth search band) from the
sector alone priced VST — a merchant IPP trading near 9.8x book — on the
regulated-utility P/B anchor of 1.8x and reported "No Solution In Range" for its
reverse DCF purely because the regulated 10% growth cap was too tight.

Both failures came from discarding the taxonomy node that the classifier had
already resolved, so these tests pin the node-first behaviour.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from config import (
    REVERSE_DCF_BY_NODE,
    get_reverse_dcf_config,
    get_reverse_dcf_config_for,
)
from models.multiples import (
    PEER_SOURCE_EXACT_INDUSTRY,
    PEER_SOURCE_EXACT_SECTOR_ANCHOR,
    TAXONOMY_NODE_PEER_MULTIPLES,
    PBModel,
    PEModel,
)


def _data(sector: str, industry: str):
    from data.models import FinancialData, MarketData

    return FinancialData(
        ticker="VST",
        market=MarketData(current_price=100.0, sector=sector, industry=industry),
    )


def _profile(node_key: str | None, label: str = "Independent Power Producer"):
    return SimpleNamespace(
        taxonomy_identity_key=node_key,
        taxonomy_identity_label=label,
    )


class TestPeerAnchorUsesNodeBeforeSector:
    def test_merchant_ipp_does_not_inherit_regulated_utility_book_multiple(self):
        model = PBModel()
        value, source, kind, _ = model._sector_peer_multiple(
            _data("Utilities", "Utilities\u2014Independent Power Producers"),
            "P/B",
            _profile("util.ipp"),
        )

        assert value == TAXONOMY_NODE_PEER_MULTIPLES["P/B"]["util.ipp"]
        assert value != 1.8, "must not fall back to the regulated-utility anchor"
        assert kind == PEER_SOURCE_EXACT_INDUSTRY
        assert "util.ipp" in source

    def test_node_anchor_also_applies_to_earnings_multiples(self):
        model = PEModel()
        value, source, kind, _ = model._sector_peer_multiple(
            _data("Utilities", "Utilities\u2014Independent Power Producers"),
            "P/E",
            _profile("util.ipp"),
        )

        assert value == TAXONOMY_NODE_PEER_MULTIPLES["P/E"]["util.ipp"]
        assert kind == PEER_SOURCE_EXACT_INDUSTRY
        assert "util.ipp" in source

    @pytest.mark.parametrize(
        "node_key",
        ["util.electric", "util.gas", "util.water", "util.generic", None],
    )
    def test_regulated_and_unlisted_nodes_keep_the_sector_anchor(self, node_key):
        model = PBModel()
        value, _source, kind, _ = model._sector_peer_multiple(
            _data("Utilities", "Utilities - Regulated Electric"),
            "P/B",
            _profile(node_key) if node_key else None,
        )

        assert value == 1.8
        assert kind == PEER_SOURCE_EXACT_SECTOR_ANCHOR

    def test_missing_profile_falls_back_to_sector_anchor(self):
        model = PBModel()
        value, _source, kind, _ = model._sector_peer_multiple(
            _data("Utilities", "Utilities\u2014Independent Power Producers"),
            "P/B",
            None,
        )

        assert value == 1.8
        assert kind == PEER_SOURCE_EXACT_SECTOR_ANCHOR


class TestReverseDcfBandUsesNode:
    def test_merchant_ipp_gets_room_above_the_regulated_growth_cap(self):
        regulated = get_reverse_dcf_config("Utilities")
        merchant = get_reverse_dcf_config_for("Utilities", "util.ipp")

        assert regulated["max_implied_cagr"] == pytest.approx(0.10)
        assert merchant["max_implied_cagr"] > regulated["max_implied_cagr"]
        assert merchant["max_implied_cagr"] == pytest.approx(
            REVERSE_DCF_BY_NODE["util.ipp"]["max_implied_cagr"]
        )

    def test_node_override_keeps_untouched_keys_from_the_business_type(self):
        base = get_reverse_dcf_config("Utilities")
        merged = get_reverse_dcf_config_for("Utilities", "util.ipp")

        assert merged["terminal_growth"] == base["terminal_growth"]
        assert merged["horizon"] == base["horizon"]

    @pytest.mark.parametrize("node_key", ["util.electric", "util.generic", None, ""])
    def test_nodes_without_an_override_use_the_business_type_band(self, node_key):
        assert get_reverse_dcf_config_for("Utilities", node_key) == get_reverse_dcf_config(
            "Utilities"
        )

    def test_override_does_not_mutate_the_shared_business_type_table(self):
        before = dict(get_reverse_dcf_config("Utilities"))
        get_reverse_dcf_config_for("Utilities", "util.ipp")
        assert get_reverse_dcf_config("Utilities") == before


class TestPeerFitFlagsCoarseAnchor:
    """A confident classification must not certify an anchor that ignored it."""

    @staticmethod
    def _results(kind: str):
        return {
            "P/B": SimpleNamespace(breakdown={"peer_source_kind": kind}),
            "DCF": SimpleNamespace(breakdown={}),
        }

    def test_coarse_sector_anchor_on_a_finer_node_is_flagged(self):
        from analysis.divergence import _peer_fit_check

        check = _peer_fit_check(
            _profile("util.ipp"),
            SimpleNamespace(n_not_applicable=0),
            self._results(PEER_SOURCE_EXACT_SECTOR_ANCHOR),
        )

        assert "粗颗粒板块锚点" in check.detail
        assert "util.ipp" in check.detail
        assert "P/B" in check.detail
        assert "一致" not in check.detail

    def test_node_matched_anchor_is_not_flagged(self):
        from analysis.divergence import _peer_fit_check

        check = _peer_fit_check(
            _profile("util.ipp"),
            SimpleNamespace(n_not_applicable=0),
            self._results(PEER_SOURCE_EXACT_INDUSTRY),
        )

        assert "粗颗粒板块锚点" not in check.detail
        assert "一致" in check.detail

    def test_no_taxonomy_node_leaves_the_aligned_verdict(self):
        from analysis.divergence import _peer_fit_check

        check = _peer_fit_check(
            _profile(None),
            SimpleNamespace(n_not_applicable=0),
            self._results(PEER_SOURCE_EXACT_SECTOR_ANCHOR),
        )

        assert "一致" in check.detail


class TestFamilyRootNodeIsNotFlagged:
    """A family root (parent=None) IS the sector level, so a sector anchor matches
    it exactly. Flagging it would be a false positive (AAPL resolved to `tech`)."""

    def test_family_root_with_sector_anchor_is_aligned(self):
        from analysis.divergence import _peer_fit_check

        check = _peer_fit_check(
            _profile("tech"),
            SimpleNamespace(n_not_applicable=0),
            TestPeerFitFlagsCoarseAnchor._results(PEER_SOURCE_EXACT_SECTOR_ANCHOR),
        )

        assert "粗颗粒板块锚点" not in check.detail
        assert "一致" in check.detail
