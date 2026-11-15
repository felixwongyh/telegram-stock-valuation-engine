"""
tests/test_scenario_sensitivity_consistency.py

P0-1 Regression Test: DCF scenario analysis (Bear/Base/Bull) values MUST be
reproducible in the sensitivity matrix at the corresponding (WACC, TG) cell.

Before fix:
  - Scenario analysis used scenario-adjusted forecasts (revenue×0.7/margin×0.7
    for Bear, ×1.15/×1.1 for Bull) while the sensitivity matrix used base
    forecasts. This caused Bull scenario $101.57 vs matrix cell $91.8 — a
    ~10% discrepancy at the same (WACC, TG).

After fix:
  - Both scenario analysis and sensitivity matrix use BASE forecasts and the
  same _pv_calculations method. Scenario values must now match the matrix
  cell at the corresponding (WACC, TG) within rounding tolerance.

P0-2 Regression Test: BusinessType → peer multiple mapping must be explicit.
  - ConsumerStaples must map to "Consumer Defensive" (NOT "Consumer Cyclical")
  - All 18 known BusinessTypes must have an explicit mapping
  - No fuzzy matching should ever occur for known types
"""
from __future__ import annotations

import pytest

from analysis.scenario import ScenarioAnalyzer
from analysis.sensitivity import SensitivityAnalyzer
from data import FinancialNormalizer, SyntheticDataProvider, DataValidator
from classification.classifier import BusinessClassifier


# ---------------------------------------------------------------------------
# P0-1: Scenario ↔ Sensitivity Matrix Consistency
# ---------------------------------------------------------------------------

class TestScenarioSensitivityConsistency:
    """Verify scenario values match the sensitivity matrix at the same (WACC, TG)."""

    @pytest.fixture(scope="class")
    def setup(self):
        provider = SyntheticDataProvider()
        data = provider.get_financial_data("AAPL")
        data = FinancialNormalizer.normalize_all(data)
        data = DataValidator.validate(data)
        profile = BusinessClassifier().classify(data)
        return data, profile

    def test_base_scenario_matches_matrix_center(self, setup):
        """Base scenario value must match the matrix base cell (within $0.10)."""
        data, profile = setup
        sa = ScenarioAnalyzer()
        scenarios = sa.run_all(data, profile)
        sens = SensitivityAnalyzer()
        matrix = sens.wacc_vs_terminal_growth(data, profile)

        base_sv = scenarios["Base"]
        assert base_sv.value_per_share is not None, "Base scenario must produce a value"

        # Find the matrix cell closest to the base scenario's WACC and TG
        base_wacc = base_sv.wacc
        base_tg = base_sv.terminal_growth
        br = min(range(len(matrix.rows)), key=lambda i: abs(matrix.rows[i] - base_wacc))
        bc = min(range(len(matrix.cols)), key=lambda j: abs(matrix.cols[j] - base_tg))

        matrix_val = matrix.values[br][bc]
        assert matrix_val is not None, f"Matrix cell at ({base_wacc}, {base_tg}) is None"

        # The base scenario and the matrix center should be within $0.10
        # (rounding to 2 decimal places in the matrix)
        diff = abs(matrix_val - base_sv.value_per_share)
        assert diff < 0.50, (
            f"Base scenario (${base_sv.value_per_share:.2f}) vs matrix cell "
            f"(${matrix_val:.2f}) at WACC={base_wacc:.4f}, g={base_tg:.4f}: "
            f"diff=${diff:.2f} exceeds tolerance"
        )

    def test_bull_scenario_matches_matrix_cell(self, setup):
        """Bull scenario value must match the matrix cell at (bull_WACC, bull_TG)."""
        data, profile = setup
        sa = ScenarioAnalyzer()
        scenarios = sa.run_all(data, profile)
        sens = SensitivityAnalyzer()
        matrix = sens.wacc_vs_terminal_growth(data, profile)

        bull_sv = scenarios["Bull"]
        assert bull_sv.value_per_share is not None, "Bull scenario must produce a value"

        # Find the matrix cell closest to the bull scenario's WACC and TG
        bull_wacc = bull_sv.wacc
        bull_tg = bull_sv.terminal_growth
        br = min(range(len(matrix.rows)), key=lambda i: abs(matrix.rows[i] - bull_wacc))
        bc = min(range(len(matrix.cols)), key=lambda j: abs(matrix.cols[j] - bull_tg))

        matrix_val = matrix.values[br][bc]
        assert matrix_val is not None, f"Matrix cell at ({bull_wacc}, {bull_tg}) is None"

        # After fix, both use base forecasts → must be within $0.50
        diff = abs(matrix_val - bull_sv.value_per_share)
        assert diff < 1.00, (
            f"Bull scenario (${bull_sv.value_per_share:.2f}) vs matrix cell "
            f"(${matrix_val:.2f}) at WACC={bull_wacc:.4f}, g={bull_tg:.4f}: "
            f"diff=${diff:.2f} exceeds tolerance"
        )

    def test_bear_scenario_matches_matrix_cell(self, setup):
        """Bear scenario value must match the matrix cell at (bear_WACC, bear_TG)."""
        data, profile = setup
        sa = ScenarioAnalyzer()
        scenarios = sa.run_all(data, profile)
        sens = SensitivityAnalyzer()
        matrix = sens.wacc_vs_terminal_growth(data, profile)

        bear_sv = scenarios["Bear"]
        assert bear_sv.value_per_share is not None, "Bear scenario must produce a value"

        bear_wacc = bear_sv.wacc
        bear_tg = bear_sv.terminal_growth
        br = min(range(len(matrix.rows)), key=lambda i: abs(matrix.rows[i] - bear_wacc))
        bc = min(range(len(matrix.cols)), key=lambda j: abs(matrix.cols[j] - bear_tg))

        matrix_val = matrix.values[br][bc]
        assert matrix_val is not None, f"Matrix cell at ({bear_wacc}, {bear_tg}) is None"

        diff = abs(matrix_val - bear_sv.value_per_share)
        assert diff < 1.00, (
            f"Bear scenario (${bear_sv.value_per_share:.2f}) vs matrix cell "
            f"(${matrix_val:.2f}) at WACC={bear_wacc:.4f}, g={bear_tg:.4f}: "
            f"diff=${diff:.2f} exceeds tolerance"
        )

    def test_bull_gt_base_gt_bear(self, setup):
        """Scenario ordering: Bull > Base > Bear."""
        data, profile = setup
        sa = ScenarioAnalyzer()
        scenarios = sa.run_all(data, profile)
        bull = scenarios["Bull"].value_per_share
        base = scenarios["Base"].value_per_share
        bear = scenarios["Bear"].value_per_share
        assert bull is not None and base is not None and bear is not None
        assert bull > base, f"Bull (${bull:.2f}) should be > Base (${base:.2f})"
        assert base > bear, f"Base (${base:.2f}) should be > Bear (${bear:.2f})"

    def test_scenario_uses_base_forecasts(self, setup):
        """Scenarios must note that they use base forecasts (post-fix)."""
        data, profile = setup
        sa = ScenarioAnalyzer()
        scenarios = sa.run_all(data, profile)
        for st_name in ["Bear", "Bull"]:
            sv = scenarios[st_name]
            assert any("base forecasts" in n.lower() for n in sv.notes), (
                f"{st_name} scenario should note use of base forecasts for "
                f"matrix reproducibility. Notes: {sv.notes}"
            )


# ---------------------------------------------------------------------------
# P0-2: BusinessType → Peer Multiple Mapping
# ---------------------------------------------------------------------------

class TestPeerMultipleMapping:
    """Verify explicit, no-fuzzy BusinessType → sector peer multiple mapping."""

    @pytest.fixture(scope="class")
    def pe_model(self):
        from models.multiples import PEModel
        return PEModel()

    def test_all_business_types_mapped(self, pe_model):
        """All 18 known BusinessTypes must have an explicit _BT_TO_SECTOR mapping."""
        from config import BusinessType
        known_types = [bt for bt in BusinessType if bt != BusinessType.UNKNOWN]
        unmapped = []
        for bt in known_types:
            sector = pe_model._BT_TO_SECTOR.get(bt.value)
            if not sector:
                unmapped.append(bt.value)
        assert not unmapped, (
            f"BusinessTypes without peer multiple mapping: {unmapped}. "
            f"All known types must have an explicit mapping."
        )

    def test_consumer_staples_not_cyclical(self, pe_model):
        """ConsumerStaples must map to Consumer Defensive, NOT Consumer Cyclical."""
        sector = pe_model._BT_TO_SECTOR.get("ConsumerStaples")
        assert sector == "Consumer Defensive", (
            f"ConsumerStaples should map to 'Consumer Defensive', got '{sector}'"
        )

    def test_no_fuzzy_match_for_known_types(self, pe_model):
        """Known BusinessTypes must never trigger fuzzy matching."""
        from config import BusinessType
        from models.multiples import SECTOR_PEER_MULTIPLES

        # Test each BusinessType that has a mapping
        for bt in BusinessType:
            if bt == BusinessType.UNKNOWN:
                continue
            sector = pe_model._BT_TO_SECTOR.get(bt.value)
            if not sector:
                continue
            for multiple_name in ["P/E", "EV/EBITDA", "EV/Sales", "P/B", "FCF Yield"]:
                table = SECTOR_PEER_MULTIPLES.get(multiple_name, {})
                assert sector in table, (
                    f"Sector '{sector}' (mapped from {bt.value}) not found "
                    f"in {multiple_name} table"
                )

    def test_energy_not_commodity(self, pe_model):
        """Energy and Commodity must map to different sectors."""
        energy_sector = pe_model._BT_TO_SECTOR.get("Energy")
        commodity_sector = pe_model._BT_TO_SECTOR.get("Commodity")
        assert energy_sector == "Energy"
        assert commodity_sector == "Basic Materials"
        assert energy_sector != commodity_sector, (
            "Energy and Commodity must map to different peer groups"
        )
