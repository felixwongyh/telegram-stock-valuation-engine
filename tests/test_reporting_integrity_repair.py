"""Acceptance tests for the Phase A–F caliber / report-interpretation repair.

This suite locks in the *caliber-consistency* and *report-wording* guarantees
the review asked for — it deliberately adds no new valuation model:

  * Phase A — an FCF-margin forecast that is a large *relative* move (or a
    sign flip, or > 2× TTM) must be flagged even when the absolute gap is
    modest (GOOG: TTM 4.2% → forecast 13.7%, +9.5pp, must NOT read as aligned).
  * Phase B — the TV/EV *wording* is graded separately from the risk threshold:
    73.9% must read as "high terminal-value dependence", never "explicit period
    dominates".
  * Phase C — Monte Carlo bridges EV → Equity through the SAME
    ``enterprise_to_equity`` as the DCF, so the 0-perturbation anchor reconciles
    even under a complex capital structure (minority / preferred / leases /
    non-operating assets), and a missing EV is an invalid draw — never a 0.
  * Phase D — FCF Yield applies SBC normalization, and a missing FCF returns
    Insufficient Data instead of being silently read as a real zero.
  * Phase E — β reliability is reported across three independent indicators
    (regression stability / bottom-up reliability / methodology divergence),
    so a stable regression window cannot mask a material disagreement with the
    peer-derived β; segment β carries its peer evidence.
  * Phase F — a static sector anchor is never labelled a live peer median, and
    every per-share denominator is traceable via the Share Count Audit Table.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from analysis.divergence import (
    FCF_MARGIN_ALIGNED_PP,
    FCF_MARGIN_FLAG_PP,
    FCF_MARGIN_HIGH_RATIO,
    _STATUS_ALIGNED,
    _STATUS_FLAG,
    _STATUS_INFO,
    _STATUS_MODERATE,
    _fcf_margin_check,
    _tv_check,
)
from analysis.model_agreement import ModelAgreementAnalyzer
from config import SolverStatus
from data import DataValidator, FinancialNormalizer, SyntheticDataProvider
from data.models import MarketData
from models.base import ValuationResult, make_share_count
from models.multiples import MultiplesModel
from simulation.monte_carlo import MODE_BASE_CASE, MonteCarloSimulator
from valuation.wacc import (
    BETA_BOTTOM_UP_MIN_PEERS,
    _bottom_up_reliability_label,
    _methodology_divergence_label,
)


def _load(ticker: str):
    from classification.classifier import BusinessClassifier

    data = SyntheticDataProvider().get_financial_data(ticker)
    data = FinancialNormalizer.normalize_all(data)
    data = DataValidator.validate(data)
    profile = BusinessClassifier().classify(data)
    return data, profile


# ===========================================================================
# Phase A — FCF margin diagnostic (absolute AND relative)
# ===========================================================================
class TestFcfMarginDiagnostic:
    @staticmethod
    def _ttm_data(revenue: float, fcf: float):
        return SimpleNamespace(ttm=SimpleNamespace(revenue=revenue, free_cash_flow=fcf))

    def test_goog_4_2_vs_13_7_flags(self, monkeypatch):
        """TTM 4.2% → forecast 13.7% (+9.5pp, >3× TTM) must flag, not align."""
        import analysis.divergence as dv

        monkeypatch.setattr(dv, "_forecast_fcf_margin", lambda data, profile: 0.137)
        chk = _fcf_margin_check(self._ttm_data(1000.0, 42.0), None, None)
        assert chk.status == _STATUS_FLAG, chk.detail
        assert "13.7%" in chk.detail and "4.2%" in chk.detail

    def test_close_margin_stays_aligned(self, monkeypatch):
        """TTM 4.2% → forecast 4.5% (+0.3pp) must remain aligned."""
        import analysis.divergence as dv

        monkeypatch.setattr(dv, "_forecast_fcf_margin", lambda data, profile: 0.045)
        chk = _fcf_margin_check(self._ttm_data(1000.0, 42.0), None, None)
        assert chk.status == _STATUS_ALIGNED, chk.detail

    def test_mid_band_is_moderate(self, monkeypatch):
        """A 3–5pp gap (not >2×) is a moderate deviation, not a flag."""
        import analysis.divergence as dv

        # TTM 4.2% → 8.0%: +3.8pp, and 8.0 < 2×4.2 = 8.4 → moderate.
        monkeypatch.setattr(dv, "_forecast_fcf_margin", lambda data, profile: 0.080)
        chk = _fcf_margin_check(self._ttm_data(1000.0, 42.0), None, None)
        assert chk.status == _STATUS_MODERATE, chk.detail

    def test_double_ttm_flags_even_if_gap_small(self, monkeypatch):
        """A forecast > 2× TTM is a material change even when the pp gap is small."""
        import analysis.divergence as dv

        # TTM 2.0% → 4.5%: only +2.5pp (would be "aligned" on the pp axis) but
        # 4.5 > 2×2.0 → must still flag.
        monkeypatch.setattr(dv, "_forecast_fcf_margin", lambda data, profile: 0.045)
        chk = _fcf_margin_check(self._ttm_data(1000.0, 20.0), None, None)
        assert chk.status == _STATUS_FLAG, chk.detail
        assert "重大变化" in chk.detail

    def test_sign_flip_flags(self, monkeypatch):
        """A positive→negative (or negative→positive) flip always flags."""
        import analysis.divergence as dv

        monkeypatch.setattr(dv, "_forecast_fcf_margin", lambda data, profile: -0.01)
        chk = _fcf_margin_check(self._ttm_data(1000.0, 42.0), None, None)
        assert chk.status == _STATUS_FLAG, chk.detail

    def test_thresholds_are_ordered(self):
        assert 0 < FCF_MARGIN_ALIGNED_PP < FCF_MARGIN_FLAG_PP
        assert FCF_MARGIN_HIGH_RATIO == 2.0


# ===========================================================================
# Phase B — TV/EV wording graded separately from the risk threshold
# ===========================================================================
class TestTvWording:
    @pytest.mark.parametrize(
        "tv,status,must_contain,must_not_contain",
        [
            (0.45, _STATUS_ALIGNED, "显式预测期贡献占多数", "高终值依赖"),
            (0.50, _STATUS_INFO, "终值贡献占多数", "显式期贡献占主导"),
            (0.739, _STATUS_MODERATE, "高终值依赖", "显式期贡献占主导"),
            (0.80, _STATUS_FLAG, "极高终值依赖", "显式期贡献占主导"),
            (0.90, _STATUS_FLAG, "极高终值依赖", "显式期贡献占主导"),
        ],
    )
    def test_tv_grading(self, tv, status, must_contain, must_not_contain):
        chk = _tv_check({"tv_percent_of_ev": tv})
        assert chk.status == status, (tv, chk.status, chk.detail)
        assert must_contain in chk.detail, chk.detail
        assert must_not_contain not in chk.detail, chk.detail

    def test_739_never_reads_as_explicit_dominance(self):
        chk = _tv_check({"tv_percent_of_ev": 0.739})
        assert chk.status == _STATUS_MODERATE
        assert "73.9%" in chk.detail
        assert "显式期贡献占主导" not in chk.detail
        assert "高终值依赖" in chk.detail


# ===========================================================================
# Phase C — Monte Carlo uses the SHARED equity bridge
# ===========================================================================
def _complex_mkt() -> MarketData:
    return MarketData(
        total_debt=1000.0,
        cash_and_equivalents=200.0,
        minority_interest=300.0,
        preferred_equity=150.0,
        non_operating_assets=400.0,
        shares_outstanding=1000.0,
    )


class TestMonteCarloEquityBridge:
    def test_project_one_uses_shared_bridge(self):
        from forecasts.fcf_projection import project_enterprise_value
        from valuation.equity_bridge import enterprise_to_equity

        mc = MonteCarloSimulator()
        mkt = _complex_mkt()
        args = (1e9, 0.08, 0.20, 0.09, 0.025, 0.05, 0.06, 0.02, 0.21, 1000.0)
        got = mc._project_one(*args, mkt, 5)

        proj = project_enterprise_value(1e9, 0.08, 0.20, 0.21, 0.05, 0.06, 0.02, 0.09, 0.025, 5)
        expected = enterprise_to_equity(proj.enterprise_value, mkt).equity_value / 1000.0
        assert got == pytest.approx(expected, rel=1e-9)

        # A naive bare `ev − net_debt` ignores minority/preferred/non-operating,
        # so it differs by exactly (minority + preferred − non-operating)/shares.
        naive = (proj.enterprise_value - (1000.0 - 200.0)) / 1000.0
        assert got - naive == pytest.approx(-(300.0 + 150.0 - 400.0) / 1000.0, abs=1e-9)

    def test_missing_enterprise_value_is_not_zero(self, monkeypatch):
        import forecasts.fcf_projection as fp

        monkeypatch.setattr(
            fp, "project_enterprise_value",
            lambda *a, **k: SimpleNamespace(enterprise_value=None),
        )
        mc = MonteCarloSimulator()
        out = mc._project_one(
            1e9, 0.08, 0.20, 0.09, 0.025, 0.05, 0.06, 0.02, 0.21, 1000.0,
            _complex_mkt(), 5,
        )
        assert out is None  # invalid draw, never a silent 0

    @pytest.mark.parametrize("ticker", ["MSFT", "AAPL"])
    def test_anchor_reconciles_under_complex_structure(self, ticker):
        from models.router import ModelRouter

        data, profile = _load(ticker)
        # Inject a complex capital structure so a bare ev − net debt would drift.
        data.market.minority_interest = 5000.0
        data.market.preferred_equity = 2000.0
        data.market.non_operating_assets = 1500.0
        dcf = ModelRouter().run_all(data, profile).get("DCF")
        assert dcf is not None and dcf.is_success()
        dcf_v = dcf.value_per_share

        res = MonteCarloSimulator().run(data, profile, mode=MODE_BASE_CASE, dcf_value=dcf_v)
        assert res.reconcile_gap is not None
        assert abs(res.reconcile_gap) < 1e-3, (
            f"{ticker}: MC anchor ${res.anchor_value:.2f} vs DCF ${dcf_v:.2f} "
            f"→ gap {res.reconcile_gap:+.2%}"
        )


# ===========================================================================
# Phase D — SBC coverage in FCF Yield + data integrity
# ===========================================================================
class TestFcfYieldSbc:
    def test_fcf_yield_uses_sbc_adjusted_fcf(self):
        data, profile = _load("MSFT")
        ttm = data.ttm
        reported = float(ttm.free_cash_flow)
        # Force a large, unambiguous SBC charge so the adjustment is visible.
        ttm.stock_based_compensation = 0.20 * reported

        r = MultiplesModel("FCF Yield").calculate(data, profile)
        assert r.status == SolverStatus.SOLVED, r.notes
        fcf_used = r.breakdown["fcf_used"]
        assert fcf_used == pytest.approx(reported - 0.20 * reported, rel=1e-6)
        assert r.breakdown["sbc_normalization"]["applied"] is True

    def test_missing_fcf_returns_insufficient_data(self):
        data, profile = _load("MSFT")
        before = data.ttm.free_cash_flow
        data.ttm.free_cash_flow = None
        try:
            r = MultiplesModel("FCF Yield").calculate(data, profile)
        finally:
            data.ttm.free_cash_flow = before
        assert r.status == SolverStatus.INSUFFICIENT_DATA
        assert any("FCF" in n for n in r.notes)


# ===========================================================================
# Phase E — β reliability across three independent indicators
# ===========================================================================
class TestBetaReliability:
    def test_bottom_up_094_vs_regression_141_is_material(self):
        assert _methodology_divergence_label(1.41, 0.94) == "material"

    def test_small_gap_is_not_material(self):
        assert _methodology_divergence_label(1.00, 1.10) == "none"

    def test_divergence_needs_both_methods(self):
        assert _methodology_divergence_label(1.41, None) == "n/a"

    def test_thin_peer_sample_lowers_bottom_up_reliability(self):
        chain = {"level": 1, "n_peers": 2}
        assert _bottom_up_reliability_label(0.94, chain) == "requires_review"

    def test_rich_peer_sample_is_high(self):
        chain = {"level": 1, "n_peers": BETA_BOTTOM_UP_MIN_PEERS + 2}
        assert _bottom_up_reliability_label(0.94, chain) == "high"

    def test_segment_weighted_needs_enough_peers(self):
        assert _bottom_up_reliability_label(1.0, {"level": 0, "n_peers": 2}) == "medium"
        assert _bottom_up_reliability_label(1.0, {"level": 0, "n_peers": 6}) == "high"

    def test_benchmark_level_requires_review(self):
        assert _bottom_up_reliability_label(1.0, {"level": 3, "n_peers": 0}) == "requires_review"

    def test_absent_bottom_up_is_na(self):
        assert _bottom_up_reliability_label(None, {"level": 1, "n_peers": 9}) == "n/a"

    def test_note_reports_three_indicators(self):
        from valuation.wacc import WaccBreakdown

        wb = WaccBreakdown(
            wacc=0.09, cost_of_equity=0.10, cost_of_debt=0.05,
            after_tax_cost_of_debt=0.04, effective_tax_rate=0.21,
            weight_equity=0.8, weight_debt=0.2, total_debt=1000.0,
            market_cap=4000.0, enterprise_value=4800.0, risk_free_rate=0.04,
            equity_risk_premium=0.05, beta=0.94,
            industry_range_min=0.06, industry_range_max=0.12,
            industry_label="Technology", sanity_status="Within Range",
        )
        wb.beta_regression_stability = "low"
        wb.beta_bottom_up_reliability = "requires_review"
        wb.beta_methodology_divergence = "material"
        wb.wacc_beta_lo = 0.085
        wb.wacc_beta_hi = 0.11

        note = wb.beta_uncertainty_note()
        assert note is not None
        assert "Regression Stability" in note
        assert "Bottom-up Reliability" in note
        assert "Methodology Divergence" in note
        assert "显著分歧" in note
        assert "需要复核" in note
        assert "Selected Beta" in note


class TestSegmentBetaIdentity:
    @staticmethod
    def _seg_result(beta_u, peers):
        from data.industry_beta import IndustryBetaResult

        return IndustryBetaResult(
            beta_unlevered=beta_u, n_peers=len(peers), industry="seg", level=1,
            source="peer-median", peer_levered=list(peers),
            peer_unlevered=[round(p / 1.4, 3) for p in peers],
            target_d2e=0.4, rationale="同子行业+商业模式筛选",
        )

    def test_segment_breakdown_carries_peer_evidence(self):
        from data.industry_beta import derive_segment_level_beta

        res = derive_segment_level_beta(
            "GOOG",
            [("Google Services", 0.8), ("Google Cloud", 0.2)],
            segment_industry_resolver=lambda label: {
                "Google Services": "Internet Content & Information",
                "Google Cloud": "Information Technology Services",
            }.get(label),
            beta_provider=lambda t, s, industry, **kw: {
                "Internet Content & Information": self._seg_result(1.05, [1.30, 1.10]),
                "Information Technology Services": self._seg_result(0.85, [1.00, 0.90]),
            }.get(industry),
        )
        assert res is not None and res.segments is not None
        by_label = {s["label"]: s for s in res.segments}
        # Distinct segments map to DISTINCT industries — never one blanket sector.
        assert (
            by_label["Google Services"]["industry"]
            != by_label["Google Cloud"]["industry"]
        )
        for row in res.segments:
            assert row["peer_levered"], row
            assert row["n_peers"] == len(row["peer_levered"])
            assert row["rationale"]

        note = res.note()
        assert "同业原始β" in note
        assert "筛选：" in note
        assert "Internet Content & Information" in note


# ===========================================================================
# Monte Carlo truncated-distribution transparency
# ===========================================================================
class TestMonteCarloTruncationTransparency:
    def test_metadata_exposes_requested_vs_actual(self):
        data, profile = _load("MSFT")
        res = MonteCarloSimulator().run(
            data, profile, mode=MODE_BASE_CASE, dcf_value=100.0
        )
        assert set(res.sample_driver_mean) == {
            "revenue_cagr", "operating_margin", "wacc", "terminal_growth"
        }
        assert set(res.sample_driver_std) == set(res.sample_driver_mean)
        for k in res.sample_driver_mean:
            assert 0.0 <= res.lower_bound_hit_rate[k] <= 1.0
            assert 0.0 <= res.upper_bound_hit_rate[k] <= 1.0
        assert res.gordon_constraint_hit_rate is not None
        assert 0.0 <= res.gordon_constraint_hit_rate <= 1.0

    def test_note_reports_requested_and_actual(self):
        data, profile = _load("MSFT")
        res = MonteCarloSimulator().run(
            data, profile, mode=MODE_BASE_CASE, dcf_value=100.0
        )
        note = res.distribution_transparency_note()
        assert note is not None
        assert "请求分布" in note and "实际样本" in note
        assert "下界命中" in note and "上界命中" in note
        assert "Gordon" in note


# ===========================================================================
# Phase F — peer provenance + share-count audit
# ===========================================================================
class TestPeerProvenance:
    def test_static_anchor_is_not_live_peer_median(self):
        from models.multiples import (
            PEER_SOURCE_EXACT_SECTOR_ANCHOR,
            PEER_SOURCE_LABELS,
            PEER_SOURCE_LIVE_PEER_MEDIAN,
        )

        assert PEER_SOURCE_EXACT_SECTOR_ANCHOR != PEER_SOURCE_LIVE_PEER_MEDIAN
        assert "非实时" in PEER_SOURCE_LABELS[PEER_SOURCE_EXACT_SECTOR_ANCHOR]
        assert "实时" in PEER_SOURCE_LABELS[PEER_SOURCE_LIVE_PEER_MEDIAN]


class TestShareCountAudit:
    @staticmethod
    def _res(name: str, value: float, shares: float, basis: str) -> ValuationResult:
        return ValuationResult(
            model_name=name,
            status=SolverStatus.SOLVED,
            value_per_share=value,
            share_count=make_share_count(shares, f"{name} 分母", basis),
        )

    def test_market_ttm_annual_deviation_audit(self, msft_data):
        ref = msft_data.market.market_cap / msft_data.market.current_price
        results = {
            "DCF": self._res("DCF", 100.0, ref * 1.05, "ttm"),
            "P/E": self._res("P/E", 110.0, ref * 1.30, "ttm"),
            "EV/EBITDA": self._res("EV/EBITDA", 105.0, ref * 1.00, "market"),
            "Historical Multiples": self._res(
                "Historical Multiples", 95.0, ref * 0.85, "annual"
            ),
        }
        ag = ModelAgreementAnalyzer().analyze(
            results, current_price=msft_data.market.current_price, data=msft_data
        )
        by_model = {r.model: r for r in ag.share_count_audit}
        assert set(by_model) == set(results)

        assert by_model["DCF"].deviation_vs_market == pytest.approx(0.05, abs=1e-6)
        assert by_model["DCF"].comparable is True
        assert by_model["EV/EBITDA"].deviation_vs_market == pytest.approx(0.0, abs=1e-6)
        assert by_model["P/E"].deviation_vs_market == pytest.approx(0.30, abs=1e-6)
        assert by_model["P/E"].comparable is False
        assert by_model["Historical Multiples"].deviation_vs_market == pytest.approx(
            -0.15, abs=1e-6
        )
        assert by_model["Historical Multiples"].comparable is False

        assert set(ag.share_count_excluded_models) == {"P/E", "Historical Multiples"}
        assert "DCF" not in ag.share_count_excluded_models

    def test_audit_table_renders_bases_and_flags_incomparable(self, msft_data):
        ref = msft_data.market.market_cap / msft_data.market.current_price
        results = {
            "DCF": self._res("DCF", 100.0, ref * 1.02, "ttm"),
            "P/E": self._res("P/E", 110.0, ref * 1.30, "ttm"),
        }
        ag = ModelAgreementAnalyzer().analyze(
            results, current_price=msft_data.market.current_price, data=msft_data
        )
        table = ag.share_count_audit_table()
        assert "Share Count Audit" in table
        assert "| Model | Share Count | Basis | Deviation vs Market |" in table
        assert "不可比" in table          # P/E 30% off the market reference
        assert "DCF" in table and "P/E" in table


# ===========================================================================
# M-67 — cross-industry diagnostic-threshold calibration
# ===========================================================================
class TestCrossIndustryThresholdCalibration:
    """Phase A/E bands are calibrated per business archetype, not one global set.

    A 5pp FCF-margin swing is a normal cycle for a high-capex semiconductor but a
    large move for a regulated utility; a 4-name β peer median is thin in a deep
    public pool but broad in a niche archetype. These tests pin the calibration
    table AND the fact that the live diagnostics actually read it.
    """

    def test_dispersion_tiers_are_monotone(self):
        from analysis.threshold_calibration import (
            TIER_MODERATE,
            TIER_STABLE,
            TIER_VOLATILE,
            tier_for_dispersion,
        )

        assert tier_for_dispersion(None) == TIER_MODERATE
        assert tier_for_dispersion(0.01) == TIER_STABLE
        assert tier_for_dispersion(0.03) == TIER_MODERATE
        assert tier_for_dispersion(0.04) == TIER_MODERATE
        assert tier_for_dispersion(0.06) == TIER_VOLATILE
        assert tier_for_dispersion(0.20) == TIER_VOLATILE

    def test_archetype_resolves_to_tier(self):
        from analysis.threshold_calibration import (
            TIER_MODERATE,
            TIER_STABLE,
            TIER_VOLATILE,
            calibration_for,
        )

        assert calibration_for("Utilities").tier == TIER_STABLE
        assert calibration_for("MatureTech").tier == TIER_MODERATE
        assert calibration_for("Semiconductor").tier == TIER_VOLATILE

    def test_bands_widen_with_volatility(self):
        from analysis.threshold_calibration import calibration_for

        st, mo, vo = (
            calibration_for(x) for x in ("Utilities", "MatureTech", "Semiconductor")
        )
        assert st.fcf_aligned_pp < mo.fcf_aligned_pp < vo.fcf_aligned_pp
        assert st.fcf_flag_pp < mo.fcf_flag_pp < vo.fcf_flag_pp
        assert st.fcf_high_ratio < mo.fcf_high_ratio < vo.fcf_high_ratio

    def test_unknown_archetype_falls_back_to_default_band(self):
        from analysis.threshold_calibration import DEFAULT_CALIBRATION, calibration_for

        got = calibration_for("SomeUnmappedArchetype")
        assert got.tier == DEFAULT_CALIBRATION.tier
        assert got.fcf_flag_pp == DEFAULT_CALIBRATION.fcf_flag_pp
        assert got.fcf_high_ratio == DEFAULT_CALIBRATION.fcf_high_ratio

    def test_beta_peer_floor_tracks_pool_breadth(self):
        from analysis.threshold_calibration import (
            BETA_MIN_PEERS_BROAD,
            BETA_MIN_PEERS_NARROW,
            BETA_MIN_PEERS_UNKNOWN,
            beta_min_peers_for,
        )

        # niche public pools → smaller honest floor
        assert beta_min_peers_for("FinTech") == BETA_MIN_PEERS_NARROW
        assert beta_min_peers_for("Neobank") == BETA_MIN_PEERS_NARROW
        # deep public pool → broader sample required
        assert beta_min_peers_for("Semiconductor") == BETA_MIN_PEERS_BROAD
        # no archetype / unmapped → neutral default
        assert beta_min_peers_for(None) == BETA_MIN_PEERS_UNKNOWN
        assert beta_min_peers_for("SomeUnmappedArchetype") == BETA_MIN_PEERS_UNKNOWN

    # --- the calibrated band actually drives the FCF-margin diagnostic ------
    @staticmethod
    def _ttm(revenue: float, fcf: float):
        return SimpleNamespace(ttm=SimpleNamespace(revenue=revenue, free_cash_flow=fcf))

    @staticmethod
    def _check(monkeypatch, business_type, forecast_margin):
        """TTM margin is fixed at 10% (rev 1000, FCF 100)."""
        import analysis.divergence as dv

        monkeypatch.setattr(
            dv, "_forecast_fcf_margin", lambda data, profile: forecast_margin
        )
        profile = SimpleNamespace(business_type=business_type)
        return _fcf_margin_check(
            TestCrossIndustryThresholdCalibration._ttm(1000.0, 100.0), profile, None
        )

    def test_same_gap_flags_a_stable_utility_but_not_a_volatile_semi(self, monkeypatch):
        # TTM 10% → 14.5% = +4.5pp. Stable flag=4pp → FLAG; volatile flag=7pp
        # → MODERATE. Identical Δ, opposite verdict — the calibration decides.
        assert self._check(monkeypatch, "Utilities", 0.145).status == _STATUS_FLAG
        semi = self._check(monkeypatch, "Semiconductor", 0.145)
        assert semi.status == _STATUS_MODERATE, semi.detail

    def test_small_gap_aligned_for_moderate_but_moderate_for_stable(self, monkeypatch):
        # TTM 10% → 12.5% = +2.5pp. Moderate aligned=3pp → ALIGNED;
        # stable aligned=2pp → MODERATE.
        assert self._check(monkeypatch, "MatureTech", 0.125).status == _STATUS_ALIGNED
        assert self._check(monkeypatch, "Utilities", 0.125).status == _STATUS_MODERATE

    def test_detail_carries_calibration_audit_trail(self, monkeypatch):
        chk = self._check(monkeypatch, "Semiconductor", 0.145)
        assert "行业校准" in chk.detail
        assert "β 最小同业" in chk.detail
        assert "volatile" in chk.detail        # the resolved tier is stated

    def test_bottom_up_floor_is_archetype_aware(self):
        # 3 peers: "high" for a narrow pool (FinTech floor=3) but only "medium"
        # under the neutral global floor (4).
        chain3 = {"level": 1, "n_peers": 3}
        assert _bottom_up_reliability_label(0.94, chain3, "FinTech") == "high"
        assert _bottom_up_reliability_label(0.94, chain3) == "medium"
        # 4 peers: "high" under the neutral floor but only "medium" for a deep
        # pool (Semiconductor floor=5).
        chain4 = {"level": 1, "n_peers": 4}
        assert _bottom_up_reliability_label(0.94, chain4) == "high"
        assert _bottom_up_reliability_label(0.94, chain4, "Semiconductor") == "medium"


# ===========================================================================
# M-69 — SBC normalization sunk into the FCF main chain (one exit, applied once)
# ===========================================================================
class TestSbcMainChainExit:
    """SBC is applied exactly once at ``resolve_ttm_fcf_normalized`` (M-69).

    Every FCF consumer (reverse DCF / multiples / diagnostics) resolves its FCF
    through that one exit, so no model both deducts SBC *as an expense* and
    charges a *dilution* penalty for the same grants.
    """

    @staticmethod
    def _stmt(**kw):
        from data.models import FinancialStatement

        return FinancialStatement(period_end="2025-12-31", **kw)

    def test_raw_primitive_never_applies_sbc(self):
        from data.fcf_utils import resolve_ttm_fcf

        stmt = self._stmt(free_cash_flow=1000.0, stock_based_compensation=200.0)
        value, source = resolve_ttm_fcf(stmt)
        assert value == pytest.approx(1000.0)
        assert source == "reported"      # raw primitive: no SBC, no suffix

    def test_normalized_exit_deducts_sbc_once(self):
        from data.fcf_utils import resolve_ttm_fcf_normalized

        stmt = self._stmt(free_cash_flow=1000.0, stock_based_compensation=200.0)
        value, source, norm = resolve_ttm_fcf_normalized(stmt, shares=100.0)
        assert value == pytest.approx(800.0)          # ONE deduction, not 1000−2×200
        assert source == "reported+sbc_normalized"
        assert norm.applied is True
        assert norm.sbc_deduction == pytest.approx(200.0)
        assert norm.adjusted_fcf_per_share == pytest.approx(8.0)

    def test_derived_fcf_is_also_normalized(self):
        from data.fcf_utils import resolve_ttm_fcf_normalized

        stmt = self._stmt(
            operating_cash_flow=1000.0, capex=-200.0, stock_based_compensation=100.0
        )
        value, source, norm = resolve_ttm_fcf_normalized(stmt)
        assert value == pytest.approx(700.0)          # (1000 − 200) − 100
        assert source == "derived_ocf_capex+sbc_normalized"
        assert norm.applied is True

    def test_absent_sbc_leaves_fcf_untouched(self):
        from data.fcf_utils import resolve_ttm_fcf_normalized

        stmt = self._stmt(free_cash_flow=1000.0)      # SBC field absent
        value, source, norm = resolve_ttm_fcf_normalized(stmt)
        assert value == pytest.approx(1000.0)         # no fabricated cost
        assert source == "reported"                   # no suffix when unadjusted
        assert norm.applied is False

    def test_missing_fcf_is_not_a_fabricated_zero(self):
        from data.fcf_utils import resolve_ttm_fcf_normalized

        stmt = self._stmt(revenue=500.0)              # no FCF and no OCF−CapEx
        value, source, norm = resolve_ttm_fcf_normalized(stmt)
        assert value is None
        assert source == "missing"
        assert norm.fcf_available is False

    def test_reverse_dcf_charges_sbc_exactly_once(self):
        from models.reverse_dcf import ReverseDCFModel

        data, profile = _load("MSFT")
        reported = float(data.ttm.free_cash_flow)
        original = data.ttm.stock_based_compensation
        data.ttm.stock_based_compensation = 0.25 * reported
        try:
            r = ReverseDCFModel().calculate(data, profile)
        finally:
            data.ttm.stock_based_compensation = original

        assert r.status == SolverStatus.SOLVED, r.notes
        # reported − SBC once, never reported − 2×SBC (the double-count risk)
        assert r.breakdown["base_fcf"] == pytest.approx(reported * 0.75)
        assert r.breakdown["sbc_normalization"]["applied"] is True
        assert r.breakdown["fcf_source"].endswith("+sbc_normalized")
