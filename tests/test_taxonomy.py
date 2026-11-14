"""
tests/test_taxonomy.py — Internal Standard Business Taxonomy (five dimensions)

Locks the contract introduced by ``classification/taxonomy.py``:

  * node-tree integrity (every parent exists; depth matches the dotted key)
  * longest-key-wins Yahoo mapping (removes the old order dependence)
  * the GOLDEN RULE — economics may only *refine* an identity **within its own
    family**; it can never decide the Business Identity across families
    (high margin + high capex + low leverage ≠ Semiconductor)
  * common-ancestor collapse for same-family prototype conflicts
  * the five-dimension assembly contract (①..⑤) via ``attach_taxonomy_profile``,
    which must stay *additive* (never rewrite ``business_type`` / routing)
"""
from __future__ import annotations

import pytest

from config import BusinessType
from classification.classifier import BusinessClassifier
from classification.taxonomy import (
    ARCHETYPE_FAMILIES,
    ConflictKind,
    DecisionStatus,
    ExternalClassification,
    IDENTITY_NODES,
    ML_LABEL_TO_NODE,
    TAXONOMY_ROUTING_STATUSES,
    BusinessModel,
    attach_taxonomy_profile,
    build_taxonomy_profile,
    common_ancestor,
    decide_status,
    derive_economic_profile,
    economic_identity_ceiling,
    infer_business_models,
    node_archetype,
    node_from_description,
    node_from_ml_label,
    node_from_yahoo,
    reconcile_identity,
    same_identity_family,
    taxonomy_routing_override,
)
from data import DataValidator, FinancialNormalizer, SyntheticDataProvider
from data.models import FinancialData, FinancialStatement, MarketData


def _load(ticker: str) -> FinancialData:
    d = SyntheticDataProvider().get_financial_data(ticker)
    d = FinancialNormalizer.normalize_all(d)
    d = DataValidator.validate(d)
    return d


# ===========================================================================
# Node tree integrity
# ===========================================================================
class TestNodeTreeIntegrity:
    def test_every_parent_exists(self):
        for key, n in IDENTITY_NODES.items():
            if n.parent is not None:
                assert n.parent in IDENTITY_NODES, f"{key} has dangling parent {n.parent}"

    def test_family_roots_are_parentless(self):
        # A node without a dotted key is a family root and must have no parent.
        for key, n in IDENTITY_NODES.items():
            if "." not in key:
                assert n.parent is None, f"root {key} must not have a parent"

    def test_depth_is_structural(self):
        # depth follows the parent chain, not the key's dot count (grouping
        # nodes such as cons.cyclical parent children at their own dot depth).
        for key, n in IDENTITY_NODES.items():
            if n.parent is None:
                assert n.depth == 0, key
            else:
                assert n.depth == IDENTITY_NODES[n.parent].depth + 1, key

    def test_parents_are_shallower(self):
        for key, n in IDENTITY_NODES.items():
            if n.parent is not None:
                assert IDENTITY_NODES[n.parent].depth < n.depth, key

    def test_archetypes_are_business_types(self):
        for n in IDENTITY_NODES.values():
            assert isinstance(n.archetype, BusinessType)

    def test_ml_label_map_targets_shadow_existing_nodes(self):
        for label, key in ML_LABEL_TO_NODE.items():
            assert key in IDENTITY_NODES, f"ML label {label} → unknown node {key}"


# ===========================================================================
# ① — Yahoo industry mapping (longest-key-wins)
# ===========================================================================
class TestYahooMapping:
    def test_software_infrastructure_does_not_collide_with_application(self):
        assert node_from_yahoo("Technology", "Software - Infrastructure") == "tech.software.infra"

    def test_software_application(self):
        assert node_from_yahoo("Technology", "Software - Application") == "tech.software.application"

    def test_semiconductor_equipment_beats_semiconductor(self):
        # "semiconductor" is a substring of "semiconductor equipment"; the longer
        # key must win regardless of list order.
        assert node_from_yahoo("Technology", "Semiconductor Equipment") == "tech.semi_equipment"

    def test_semiconductors_maps_to_manufacturer(self):
        assert node_from_yahoo("Technology", "Semiconductors") == "tech.semiconductor"

    def test_reit_subtypes_collapse_to_reit(self):
        assert node_from_yahoo("Real Estate", "REIT - Industrial") == "re.reit"

    def test_sector_only_falls_back(self):
        assert node_from_yahoo("Technology", None) == "tech.generic"

    def test_industry_beats_longer_broad_sector_phrase(self):
        # "Consumer Cyclical" (17 chars) is longer than "Internet Retail" (15);
        # a naive concatenated longest-match would pick the vague sector node.
        assert node_from_yahoo("Consumer Cyclical", "Internet Retail") == "cons.ecommerce"
        assert node_from_yahoo("Consumer Defensive", "Grocery Stores") == "cs.retail"
        assert node_from_yahoo("Industrials", "Integrated Freight & Logistics") == "ind.logistics"

    def test_na_inputs_return_none(self):
        assert node_from_yahoo(None, None) is None
        assert node_from_yahoo("N/A", "N/A") is None

    def test_unmapped_industry_falls_back_to_sector(self):
        assert node_from_yahoo("Industrials", "Some Exotic Niche Industry") == "ind.generic"

    def test_mapping_is_order_independent(self):
        """The result must not depend on the order of the mapping table."""
        import classification.taxonomy as tax

        original = list(tax.YAHOO_INDUSTRY_TO_NODE)
        try:
            tax.YAHOO_INDUSTRY_TO_NODE = list(reversed(original))
            assert tax.node_from_yahoo("Technology", "Software - Infrastructure") == "tech.software.infra"
            assert tax.node_from_yahoo("Technology", "Semiconductor Equipment") == "tech.semi_equipment"
        finally:
            tax.YAHOO_INDUSTRY_TO_NODE = original

    def test_archetype_of_mapped_node(self):
        assert node_archetype("tech.semiconductor") == BusinessType.SEMICONDUCTOR
        assert node_archetype("fin.bank") == BusinessType.BANK
        assert node_archetype("does.not.exist") == BusinessType.UNKNOWN


# ===========================================================================
# The GOLDEN RULE — economics cannot decide Identity
# ===========================================================================
class TestGoldenRule:
    def test_economic_identity_ceiling_blocks_cross_family(self):
        # Bank identity, tech economics → identity kept.
        assert economic_identity_ceiling("fin.bank", "tech.semiconductor") == "fin.bank"
        # Staples identity, cyclical economics → identity kept (different family).
        assert economic_identity_ceiling("cs.food", "cons.retail") == "cs.food"

    def test_economic_identity_ceiling_blocks_same_family_promotion(self):
        # Software + semiconductor share the 'tech' family, but economics may
        # not *promote* a software identity to Semiconductor — it collapses to
        # the shared ancestor instead.
        assert economic_identity_ceiling("tech.software.infra", "tech.semiconductor") == "tech"

    def test_economic_identity_ceiling_returns_identity_when_identical(self):
        assert economic_identity_ceiling("tech.semiconductor", "tech.semiconductor") == "tech.semiconductor"

    def test_ceiling_without_identity_returns_economics(self):
        assert economic_identity_ceiling(None, "tech.semiconductor") == "tech.semiconductor"

    def test_ceiling_without_economics_returns_identity(self):
        assert economic_identity_ceiling("tech.semiconductor", None) == "tech.semiconductor"

    def test_cross_family_reconciliation_keeps_identity(self):
        """A mis-shaped bank must never be relabelled as a tech prototype."""
        ext = ExternalClassification(
            yahoo_sector="Financial Services", yahoo_industry="Banks - Diversified",
        )
        rec = reconcile_identity(external=ext, economics_key="tech.semiconductor")
        assert rec.conflict_kind == ConflictKind.IDENTITY_WINS
        assert rec.canonical_key == "fin.bank"
        assert rec.valuation_archetype == BusinessType.BANK
        assert rec.confidence_delta < 0


# ===========================================================================
# Reconciliation state machine
# ===========================================================================
class TestReconciliation:
    def test_consistent_when_identical(self):
        ext = ExternalClassification(yahoo_sector="Technology", yahoo_industry="Semiconductors")
        rec = reconcile_identity(external=ext, economics_key="tech.semiconductor")
        assert rec.conflict_kind == ConflictKind.CONSISTENT
        assert rec.canonical_key == "tech.semiconductor"

    def test_consistent_when_no_economics(self):
        ext = ExternalClassification(yahoo_sector="Technology", yahoo_industry="Semiconductors")
        rec = reconcile_identity(external=ext, economics_key=None)
        assert rec.conflict_kind == ConflictKind.CONSISTENT
        assert rec.canonical_key == "tech.semiconductor"

    def test_economics_only_when_no_structured_identity(self):
        ext = ExternalClassification(ml_label=BusinessType.SEMICONDUCTOR.value)
        rec = reconcile_identity(external=ext, economics_key="tech.semiconductor")
        assert rec.conflict_kind == ConflictKind.ECONOMICS_ONLY
        assert rec.canonical_key == "tech.semiconductor"
        assert rec.identity_source == "ml_label"
        assert rec.confidence_delta < 0

    def test_insufficient_when_nothing(self):
        rec = reconcile_identity(external=ExternalClassification())
        assert rec.conflict_kind == ConflictKind.INSUFFICIENT
        assert rec.canonical_key is None
        assert rec.valuation_archetype == BusinessType.UNKNOWN

    def test_description_used_when_no_industry(self):
        ext = ExternalClassification()
        rec = reconcile_identity(external=ext, description_key="tech.cloud_infra")
        assert rec.canonical_key == "tech.cloud_infra"
        assert rec.identity_source == "description"
        assert rec.conflict_kind == ConflictKind.CONSISTENT

    def test_description_refines_within_family(self):
        # Broad sector → tech.generic (depth 1); description nails a deeper node.
        ext = ExternalClassification(yahoo_sector="Technology")
        rec = reconcile_identity(external=ext, description_key="tech.software.application")
        assert rec.canonical_key == "tech.software.application"
        assert rec.identity_source == "yahoo_industry+description"
        assert rec.conflict_kind == ConflictKind.CONSISTENT

    def test_description_cross_family_conflict_keeps_industry(self):
        ext = ExternalClassification(yahoo_sector="Financial Services", yahoo_industry="Banks - Diversified")
        rec = reconcile_identity(external=ext, description_key="tech.cloud_infra")
        assert rec.canonical_key == "fin.bank"

    def test_same_family_semiconductor_vs_software_collapses_to_ancestor(self):
        """The headline defect: an infra-software company whose financial *shape*
        looks semiconductor-like must NOT be labelled Semiconductor. Both nodes
        live in family 'tech', so the verdict collapses to the shared ancestor."""
        ext = ExternalClassification(
            yahoo_sector="Technology", yahoo_industry="Software - Infrastructure",
        )
        rec = reconcile_identity(external=ext, economics_key="tech.semiconductor")
        assert rec.conflict_kind == ConflictKind.REFINEMENT
        assert rec.canonical_key == "tech"                    # common ancestor
        assert rec.valuation_archetype == BusinessType.MATURE_TECH
        assert rec.canonical_key != "tech.semiconductor"

    def test_common_ancestor_helpers(self):
        assert common_ancestor("tech.software.infra", "tech.semiconductor") == "tech"
        assert common_ancestor("tech.software.infra", "fin.bank") is None
        assert common_ancestor("en.oil_gas.eup", "en.oil_gas.midstream") == "en.oil_gas"


# ===========================================================================
# ② — Business Model inference
# ===========================================================================
class TestBusinessModels:
    def test_multiple_models_ordered_by_appearance(self):
        text = "We sell subscription software and derive advertising revenue."
        models = infer_business_models(text)
        assert BusinessModel.SAAS_SUBSCRIPTION in models
        assert BusinessModel.ADVERTISING in models
        # subscription appears before advertis → order preserved
        assert models.index(BusinessModel.SAAS_SUBSCRIPTION) < models.index(BusinessModel.ADVERTISING)

    def test_empty_input(self):
        assert infer_business_models(None) == []
        assert infer_business_models("") == []

    def test_no_match(self):
        assert infer_business_models("a company that does nothing obvious") == []

    def test_commodities_keyword_variants(self):
        # Both the base and the plural stem must be recognised.
        assert BusinessModel.COMMODITY_SPOT in infer_business_models("commodities trading")
        assert BusinessModel.COMMODITY_SPOT in infer_business_models("commodity exposure")

    def test_deduplicates(self):
        models = infer_business_models("subscription subscription saas")
        assert models.count(BusinessModel.SAAS_SUBSCRIPTION) == 1


# ===========================================================================
# ③ / ④ — Revenue composition + economic shape
# ===========================================================================
class TestRevenueAndEconomics:
    def test_revenue_composition_unavailable_is_explicit(self):
        from classification.taxonomy import RevenueComposition

        rc = RevenueComposition.unavailable()
        assert rc.available is False
        assert rc.is_concentrated is None
        assert rc.note

    def test_revenue_composition_concentration(self):
        from classification.taxonomy import RevenueComposition, SegmentRevenue

        rc = RevenueComposition(
            available=True,
            segments=[SegmentRevenue("Cloud", 0.75), SegmentRevenue("Ads", 0.25)],
            source="test",
        )
        assert rc.is_concentrated is True

    def test_economics_are_shape_only(self):
        ttm = FinancialStatement(
            period_end="TTM", period_type="ttm",
            revenue=100.0, gross_profit=60.0, operating_income=25.0,
            net_income=20.0, free_cash_flow=15.0, capex=-30.0,
        )
        data = FinancialData(ticker="SHAPE", ttm=ttm, market=MarketData(total_debt=40.0, book_value=100.0))
        ep = derive_economic_profile(data)
        assert ep.gross_margin == pytest.approx(0.60)
        assert ep.operating_margin == pytest.approx(0.25)
        assert ep.capex_to_revenue == pytest.approx(0.30)
        assert ep.de_ratio == pytest.approx(0.40)
        assert ep.is_capex_heavy is True
        assert ep.is_loss_making is False

    def test_asset_light_flag(self):
        ttm = FinancialStatement(
            period_end="TTM", period_type="ttm",
            revenue=100.0, gross_profit=80.0, operating_income=30.0,
            net_income=25.0, free_cash_flow=28.0, capex=-2.0,
        )
        ep = derive_economic_profile(FinancialData(ticker="LIGHT", ttm=ttm))
        assert ep.is_asset_light is True
        assert ep.is_capex_heavy is False

    def test_loss_making_flag(self):
        ttm = FinancialStatement(
            period_end="TTM", period_type="ttm",
            revenue=100.0, gross_profit=40.0, operating_income=-15.0,
            net_income=-20.0, free_cash_flow=-5.0, capex=-10.0,
        )
        ep = derive_economic_profile(FinancialData(ticker="LOSS", ttm=ttm))
        assert ep.is_loss_making is True

    def test_revenue_cagr(self):
        # annuals newest-first, as the engine stores them; CAGR spans len-1
        # intervals, so three consecutive years give a 2-year growth rate.
        annuals = [
            FinancialStatement(period_end="2024", revenue=121.0),
            FinancialStatement(period_end="2023", revenue=110.0),
            FinancialStatement(period_end="2022", revenue=100.0),
        ]
        ttm = FinancialStatement(period_end="TTM", period_type="ttm", revenue=121.0)
        ep = derive_economic_profile(
            FinancialData(ticker="GROW", ttm=ttm, annual_income=annuals)
        )
        assert ep.revenue_cagr == pytest.approx(0.10, abs=0.005)


# ===========================================================================
# ⑤ — External labels preserved verbatim + additive wiring
# ===========================================================================
class TestFiveDimensionContract:
    def test_external_labels_are_preserved_verbatim(self):
        ext = ExternalClassification(
            yahoo_sector="Technology", yahoo_industry="Software - Infrastructure",
        )
        rec = reconcile_identity(external=ext, economics_key="tech.semiconductor")
        # Raw provider strings are never overwritten by the internal verdict.
        assert ext.yahoo_industry == "Software - Infrastructure"
        assert rec.canonical_key != "tech.semiconductor"

    def test_node_from_description_refines(self):
        assert node_from_description("Operates large AI data centers worldwide") == "tech.cloud_infra"
        assert node_from_description("A fabless chipmaker") == "tech.semiconductor"
        assert node_from_description(None) is None
        assert node_from_description("just a normal company") is None

    def test_attach_is_additive_and_populates_five_dimensions(self):
        data = _load("NVDA")
        profile = BusinessClassifier.classify(data)
        # taxonomy fields populated …
        assert profile.taxonomy_identity_key in IDENTITY_NODES
        assert profile.taxonomy_conflict_kind in {k.value for k in ConflictKind}
        assert isinstance(profile.taxonomy_business_models, list)
        assert profile.taxonomy_audit and any("①" in line for line in profile.taxonomy_audit)
        assert isinstance(profile.external_classification, dict)
        # … without rewriting the routing contract.
        assert profile.business_type
        assert isinstance(profile.applicable_models, list)

    def test_attach_uses_market_description_signal(self):
        # MSFT's synthetic industry ("Software") maps to the broad tech.generic
        # node (depth 1); a deeper description node must refine it.
        data = _load("MSFT")
        assert node_from_yahoo(data.market.sector, data.market.industry) == "tech.generic"
        data.market.description = "Sells enterprise software and related cloud services."
        profile = BusinessClassifier.classify(data)
        assert profile.taxonomy_identity_key == "tech.software.application"

    def test_ml_label_signal_maps_to_node(self):
        assert node_from_ml_label(BusinessType.SEMICONDUCTOR.value) == "tech.semiconductor"
        assert node_from_ml_label(None) is None
        assert node_from_ml_label("NotAThing") is None


# ===========================================================================
# Decision contract — ConflictKind → four-state DecisionStatus
# ===========================================================================
class TestDecisionContract:
    def test_insufficient_maps_to_insufficient_data(self):
        assert decide_status(ConflictKind.INSUFFICIENT, "none") is DecisionStatus.INSUFFICIENT_DATA

    def test_cross_family_conflict_is_ambiguous(self):
        assert decide_status(ConflictKind.IDENTITY_WINS, "yahoo_industry") is DecisionStatus.AMBIGUOUS

    def test_refinement_is_probable(self):
        assert decide_status(ConflictKind.REFINEMENT, "yahoo_industry") is DecisionStatus.PROBABLE

    def test_consistent_structured_identity_is_confirmed(self):
        assert decide_status(ConflictKind.CONSISTENT, "yahoo_industry") is DecisionStatus.CONFIRMED
        assert (
            decide_status(ConflictKind.CONSISTENT, "yahoo_industry+description")
            is DecisionStatus.CONFIRMED
        )

    def test_consistent_description_only_is_probable(self):
        # Free-text-only identity is usable but not "confirmed".
        assert decide_status(ConflictKind.CONSISTENT, "description") is DecisionStatus.PROBABLE

    def test_economics_only_depends_on_ml_confidence(self):
        assert (
            decide_status(ConflictKind.ECONOMICS_ONLY, "ml_label", ml_confidence=0.80)
            is DecisionStatus.PROBABLE
        )
        assert (
            decide_status(ConflictKind.ECONOMICS_ONLY, "ml_label", ml_confidence=0.40)
            is DecisionStatus.AMBIGUOUS
        )
        assert (
            decide_status(ConflictKind.ECONOMICS_ONLY, "ml_label", ml_confidence=None)
            is DecisionStatus.AMBIGUOUS
        )

    def test_attach_writes_decision_status(self):
        data = _load("NVDA")
        profile = BusinessClassifier.classify(data)
        assert profile.taxonomy_decision_status in {s.value for s in DecisionStatus}
        assert any("决策状态" in line for line in profile.taxonomy_audit)


# ===========================================================================
# Decision contract — end-to-end through the real builder / classifier
# ===========================================================================
class TestDecisionContractEndToEnd:
    """The four-state verdict propagates through the real assembly pipeline.

    Unlike ``TestDecisionContract`` (which pins ``decide_status`` in isolation),
    these run ``build_taxonomy_profile`` / ``attach_taxonomy_profile`` /
    ``BusinessClassifier`` on real ``FinancialData`` so the *wiring* is locked:
    a change that stops the status reaching the profile must fail here.
    """

    def test_structured_identity_is_confirmed(self):
        data = _load("NVDA")
        ext = ExternalClassification(
            yahoo_sector="Technology", yahoo_industry="Semiconductors",
        )
        tp = build_taxonomy_profile(data, external=ext)
        assert tp.reconciliation.conflict_kind is ConflictKind.CONSISTENT
        assert tp.decision_status is DecisionStatus.CONFIRMED
        assert any("决策状态" in ln and "已确认" in ln for ln in tp.audit_lines())

    def test_no_evidence_is_insufficient_data(self):
        tp = build_taxonomy_profile(FinancialData(ticker="ZZZ"))
        assert tp.reconciliation.conflict_kind is ConflictKind.INSUFFICIENT
        assert tp.decision_status is DecisionStatus.INSUFFICIENT_DATA
        assert tp.identity_key is None

    def test_cross_family_conflict_is_ambiguous(self):
        ext = ExternalClassification(
            yahoo_sector="Technology",
            yahoo_industry="Semiconductors",
            ml_label=BusinessType.BANK.value,  # economics claims a different family
        )
        tp = build_taxonomy_profile(FinancialData(ticker="ZZZ"), external=ext)
        assert tp.reconciliation.conflict_kind is ConflictKind.IDENTITY_WINS
        assert tp.decision_status is DecisionStatus.AMBIGUOUS

    def test_description_only_identity_is_probable(self):
        tp = build_taxonomy_profile(FinancialData(ticker="ZZZ"), description="A fabless chipmaker")
        assert tp.reconciliation.identity_source == "description"
        assert tp.decision_status is DecisionStatus.PROBABLE

    def test_attach_propagates_status_to_company_profile(self):
        data = _load("NVDA")
        cp = BusinessClassifier.classify(data)
        # A cross-family ML claim must surface as AMBIGUOUS on the profile.
        tp = attach_taxonomy_profile(data, cp, ml_label=BusinessType.BANK.value)
        assert cp.taxonomy_decision_status == tp.decision_status.value
        assert cp.taxonomy_decision_status == DecisionStatus.AMBIGUOUS.value

    def test_full_pipeline_status_is_valid_across_archetypes(self):
        for tk in ("NVDA", "MSFT", "JPM", "PLD"):
            profile = BusinessClassifier.classify(_load(tk))
            assert profile.taxonomy_decision_status in {s.value for s in DecisionStatus}, tk
            assert any("决策状态" in ln for ln in profile.taxonomy_audit), tk


# ===========================================================================
# M-32 — Taxonomy as a routing participant (cross-family gate)
# ===========================================================================
class TestTaxonomyRoutingGate:
    """Locks the M-32 gate.

    The taxonomy *directs* routing only on a CONFIRMED cross-family conflict.
    A same-family narrowing (``MatureTech`` vs ``SaaS`` — both ``tech``) is left
    to the economics-driven classifier, and the asset-light economic guardrail
    always wins. This is what keeps the golden routing from drifting.
    """

    def test_cross_family_confirmed_overrides(self):
        assert taxonomy_routing_override(
            BusinessType.INDUSTRIAL, "fin.bank", DecisionStatus.CONFIRMED
        ) is BusinessType.BANK

    def test_same_family_narrowing_is_not_overridden(self):
        # ORCL / NBIS / CRWV: internal MatureTech vs tech.software.infra (SaaS).
        assert taxonomy_routing_override(
            BusinessType.MATURE_TECH, "tech.software.infra", DecisionStatus.CONFIRMED
        ) is None
        # Semiconductor is also in the `tech` family → no cross-family override.
        assert taxonomy_routing_override(
            BusinessType.SEMICONDUCTOR, "tech.software.infra", DecisionStatus.CONFIRMED
        ) is None

    def test_agreement_is_noop(self):
        assert taxonomy_routing_override(
            BusinessType.SAAS, "tech.software.infra", DecisionStatus.CONFIRMED
        ) is None

    def test_non_confirmed_status_never_overrides(self):
        for status in (
            DecisionStatus.PROBABLE,
            DecisionStatus.AMBIGUOUS,
            DecisionStatus.INSUFFICIENT_DATA,
            "probable",
            None,
        ):
            assert taxonomy_routing_override(
                BusinessType.INDUSTRIAL, "fin.bank", status
            ) is None, status

    def test_guardrail_blocks_an_asset_light_target(self):
        # Media is asset-light → allowed only when the guard is silent.
        assert taxonomy_routing_override(
            BusinessType.INDUSTRIAL, "med.streaming", DecisionStatus.CONFIRMED
        ) is BusinessType.MEDIA
        assert taxonomy_routing_override(
            BusinessType.INDUSTRIAL, "med.streaming", DecisionStatus.CONFIRMED,
            guard_blocked=True,
        ) is None

    def test_unknown_internal_lets_taxonomy_supply_the_route(self):
        assert taxonomy_routing_override(
            BusinessType.UNKNOWN, "hc.pharma", DecisionStatus.CONFIRMED
        ) is BusinessType.HEALTHCARE

    def test_missing_or_unknown_key_is_noop(self):
        for key in (None, "", "does.not.exist", "unknown"):
            assert taxonomy_routing_override(
                BusinessType.INDUSTRIAL, key, DecisionStatus.CONFIRMED
            ) is None, key

    def test_routing_statuses_are_confirmed_only(self):
        assert TAXONOMY_ROUTING_STATUSES == frozenset({DecisionStatus.CONFIRMED})

    def test_family_index_covers_every_archetype(self):
        for bt in BusinessType:
            if bt is BusinessType.UNKNOWN:
                continue
            assert bt in ARCHETYPE_FAMILIES, bt
        assert BusinessType.UNKNOWN not in ARCHETYPE_FAMILIES

    def test_same_identity_family_helper(self):
        assert same_identity_family(BusinessType.MATURE_TECH, "tech.hardware") is True
        assert same_identity_family(BusinessType.BANK, "tech.hardware") is False
        assert same_identity_family(BusinessType.UNKNOWN, "tech.hardware") is False

    def test_tension_basket_keeps_its_routed_business_type(self):
        # The three golden tickers whose taxonomy identity is a *same-family*
        # narrowing of the internal route must keep MatureTech (not drift to
        # SaaS) — the zero-drift guarantee for the golden basket.
        for tk in ("ORCL", "NBIS", "CRWV"):
            profile = BusinessClassifier.classify(_load(tk))
            assert profile.taxonomy_identity_key == "tech.software.infra", tk
            assert profile.business_type == BusinessType.MATURE_TECH.value, tk
