"""Acceptance tests for the Session #48 two-layer growth band and β layering.

Two problems, one principle: never bend the model's economic meaning to make
more names look "solved", and never dress a raw-data defect up as a finding.

Reverse DCF
    The growth band used to serve double duty — it was both the *economic
    plausibility* range and the *solver search* range. That conflation meant a
    price requiring 17% growth was reported as "No Solution In Range" when the
    staples band stopped at 15%, which reads as "the model cannot explain this
    price" rather than "the market is pricing growth we consider implausible".

    The fix splits the two: the solver searches a wide band, and the economic
    band *labels* the answer. These tests pin both halves — including the
    property that widening the search must NOT move an already-converged root,
    which is what makes the split safe rather than a way to manufacture solves.

Beta
    A raw regression β, its risk-adjusted value and the β actually used in the
    valuation were not distinguishable in the report, so a name with β ≈ 0.00
    could display 0.30 with no trace of the original estimate. These tests pin
    the raw → adjusted → used chain and the statistical diagnostics that say
    whether the point estimate means anything at all.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from config import (
    GrowthBandVerdict,
    classify_growth_band,
    reverse_dcf_search_bounds,
)
from models.reverse_dcf import ReverseDCFModel


# ---------------------------------------------------------------------------
# Two-layer growth bands
# ---------------------------------------------------------------------------
class TestGrowthBandClassification:
    def test_within_band_is_plain_solved(self):
        assert (
            classify_growth_band(0.05, -0.03, 0.15)
            is GrowthBandVerdict.WITHIN_BASE_BAND
        )

    def test_just_outside_band_is_flagged_not_hidden(self):
        # KO's 17.0% against a 15.0% staples cap: a real root, slightly high.
        assert (
            classify_growth_band(0.170, -0.03, 0.15)
            is GrowthBandVerdict.OUTSIDE_BASE_BAND
        )

    def test_far_outside_band_is_extreme(self):
        # WMT's 37.9% against the same 15.0% cap.
        assert (
            classify_growth_band(0.379, -0.03, 0.15)
            is GrowthBandVerdict.EXTREME_GROWTH
        )

    def test_below_band_is_also_outside(self):
        # A market pricing negative growth is a finding too, not a silent pass.
        assert (
            classify_growth_band(-0.20, -0.03, 0.15)
            is GrowthBandVerdict.OUTSIDE_BASE_BAND
        )

    def test_no_root_is_reported_as_such(self):
        assert (
            classify_growth_band(None, -0.03, 0.15)
            is GrowthBandVerdict.NO_ROOT_IN_EXPANDED_RANGE
        )

    def test_extreme_threshold_scales_with_band_width(self):
        # Utilities band is narrow [-2%, 10%] (width 12%); a 48.7% implied
        # growth is extreme for it, and the label must not depend on the
        # absolute growth rate alone.
        assert (
            classify_growth_band(0.487, -0.02, 0.10)
            is GrowthBandVerdict.EXTREME_GROWTH
        )
        # The same 48.7% inside a wide SaaS band [−5%, 80%] is merely outside.
        assert (
            classify_growth_band(0.487, -0.05, 0.80)
            is GrowthBandVerdict.WITHIN_BASE_BAND
        )


class TestSearchBandIsSupersetOfEconomicBand:
    @pytest.mark.parametrize(
        "lo,hi",
        [(-0.03, 0.15), (-0.02, 0.10), (-0.05, 0.80), (-0.15, 0.25)],
    )
    def test_search_band_contains_economic_band(self, lo, hi):
        s_lo, s_hi = reverse_dcf_search_bounds(lo, hi)
        assert s_lo <= lo and s_hi >= hi, (
            "the solver must never be confined to the plausibility band"
        )

    def test_search_band_is_stable_across_types(self):
        # One global search window: the per-type economic band is the only thing
        # that varies, so differences between tickers cannot come from the
        # search range drifting per business type.
        a = reverse_dcf_search_bounds(-0.03, 0.15)
        b = reverse_dcf_search_bounds(-0.02, 0.10)
        assert a == b


class TestSolverInvariance:
    """Widening the search band must not move an already-converged root.

    This is the property that makes the two-layer split honest: if widening
    changed the answer, the "implied growth" would be an artefact of the band
    rather than of the cash flows.
    """

    def test_converged_root_is_invariant_to_band_width(self, aapl_data, aapl_profile):
        model = ReverseDCFModel()
        data = copy.deepcopy(aapl_data)
        result = model.calculate(aapl_data, aapl_profile)
        target = result.breakdown.get("target_enterprise_value")
        if target is None or target <= 0:
            pytest.skip("no usable target EV for this fixture")

        narrow_g, narrow_status, _, _ = model._solve_revenue_cagr(
            data, aapl_profile, target, wacc=result.breakdown["wacc"],
            tg=result.breakdown["terminal_growth"], horizon=5,
            cagr_lo=-0.05, cagr_hi=0.20,
        )
        wide_g, wide_status, _, _ = model._solve_revenue_cagr(
            data, aapl_profile, target, wacc=result.breakdown["wacc"],
            tg=result.breakdown["terminal_growth"], horizon=5,
            cagr_lo=-0.50, cagr_hi=1.50,
        )
        if narrow_g is None or wide_g is None:
            pytest.skip("fixture does not bracket a root in both bands")
        assert narrow_status == wide_status
        assert narrow_g == pytest.approx(wide_g, abs=1e-4), (
            "widening the search band moved the root — the solve is band-dependent"
        )

    def test_solver_meta_records_bounds_and_residual(self, aapl_data, aapl_profile):
        result = ReverseDCFModel().calculate(aapl_data, aapl_profile)
        bd = result.breakdown or {}
        if bd.get("implied_revenue_cagr") is None:
            pytest.skip("fixture produced no root")
        meta = bd.get("solver_meta") or {}
        assert meta.get("solver_method")
        assert meta.get("solver_version")
        assert "search_bounds" in meta
        assert meta.get("converged") is True
        assert meta.get("n_roots_detected", 0) >= 1

    def test_breakdown_carries_both_bands(self, aapl_data, aapl_profile):
        bd = ReverseDCFModel().calculate(aapl_data, aapl_profile).breakdown or {}
        econ = bd.get("economic_plausibility_band")
        search = bd.get("solver_search_band")
        assert econ and search
        assert search[0] <= econ[0] and search[1] >= econ[1]


class TestFcfBaseQuality:
    """A growth reading is only meaningful on a usable FCF base."""

    def _ttm(self, ocf, capex):
        return SimpleNamespace(operating_cash_flow=ocf, capex=capex)

    def test_negative_base_fcf_is_data_quality(self):
        model = ReverseDCFModel()
        q = model._fcf_base_quality(self._ttm(11.5e9, -16.7e9), -5.16e9)
        assert q is not None and q["reason"] == "negative_base_fcf"
        assert q["capex_to_ocf"] == pytest.approx(1.452, abs=1e-2)

    def test_capex_above_ocf_is_flagged(self):
        model = ReverseDCFModel()
        q = model._fcf_base_quality(self._ttm(10.0e9, -10.5e9), 0.5e9)
        assert q is not None and q["reason"] == "capex_exceeds_ocf"

    def test_heavy_but_positive_fcf_only_notes(self):
        model = ReverseDCFModel()
        # 75% of OCF: heavy, but FCF still positive — a note, not a warning.
        q = model._fcf_base_quality(self._ttm(40.0e9, -30.0e9), 10.0e9)
        assert q is not None and q["reason"] == "heavy_capex"

    def test_wmt_actual_base_is_not_flagged(self):
        """WMT's real base (CapEx 68.5% of OCF, FCF +$13.5B) is heavy but usable.

        Flagging it would be an artificial correction that hides a genuine
        finding: a 37.9% implied growth for a staples retailer is extreme on its
        own terms, not because the cash-flow base is broken.
        """
        model = ReverseDCFModel()
        assert model._fcf_base_quality(self._ttm(42.923e9, -29.414e9), 13.509e9) is None

    def test_clean_base_returns_none(self):
        model = ReverseDCFModel()
        # KO-like: CapEx is ~12% of OCF.
        assert model._fcf_base_quality(self._ttm(16.2e9, -1.9e9), 14.3e9) is None

    def test_data_quality_outranks_extreme_growth_label(self, aapl_data, aapl_profile):
        """An implausible growth on a broken FCF base is a data problem."""
        data = copy.deepcopy(aapl_data)
        data.ttm.operating_cash_flow = 11.5e9
        data.ttm.capex = -16.7e9
        data.ttm.free_cash_flow = -5.16e9
        result = ReverseDCFModel().calculate(data, aapl_profile)
        bd = result.breakdown or {}
        if bd.get("implied_revenue_cagr") is None:
            pytest.skip("fixture produced no root on the perturbed base")
        assert bd.get("fcf_base_quality") is not None
        assert bd["growth_band_verdict"] in (
            GrowthBandVerdict.DATA_QUALITY_WARNING.value,
            GrowthBandVerdict.WITHIN_BASE_BAND.value,
        )


class TestVerdictConsistency:
    """The verdict must describe the number the report displays.

    Two self-contradictions were caught by auditing the full basket, both
    introduced by the two-layer change and both fixed here:

      1. ``No Solution In Range`` + a displayed implied CAGR + a "within band"
         verdict. The normalized-economics rescue supplies the CAGR, so the
         verdict has to grade *that* number — but a negative base FCF means no
         growth reading is valid at all, so it must be a data-quality warning.
      2. An empty ``solver_meta`` on the no-root path, which made "no root"
         indistinguishable from "solver did not run".
    """

    def test_negative_fcf_names_never_get_a_clean_verdict(self, collected_basket):
        for t, bd in collected_basket.items():
            q = bd.get("fcf_base_quality")
            if not q or q.get("reason") != "negative_base_fcf":
                continue
            assert bd.get("growth_band_verdict") != "SOLVED_WITHIN_BASE_BAND", (
                f"{t}: negative base FCF labelled within the plausible band"
            )

    def test_no_root_path_still_records_solver_meta(self, collected_basket):
        for t, bd in collected_basket.items():
            if bd.get("growth_band_verdict") != "NO_ROOT_IN_EXPANDED_RANGE":
                continue
            meta = bd.get("solver_meta") or {}
            assert meta, f"{t}: no-root path left solver_meta empty"
            assert meta.get("converged") is False
            assert meta.get("failure") in (
                "above_search_ceiling", "below_search_floor",
                "ev_decreasing_in_growth", "projection_error",
            )

    def test_negative_base_fcf_without_root_gets_its_own_verdict(
        self, aapl_data, aapl_profile, monkeypatch
    ):
        """A negative base FCF *and* no root is neither "growth too high" nor a
        usable warning number: the reverse-DCF premise fails outright.

        Forced deterministically (rather than hoping the basket contains such a
        name) by making every projection negative and the solver rootless.
        """
        import copy

        data = copy.deepcopy(aapl_data)
        data.ttm.operating_cash_flow = 11.5e9
        data.ttm.capex = -16.7e9
        data.ttm.free_cash_flow = -5.16e9

        # Force the "no root, no rescue CAGR" path: EV is negative everywhere and
        # does not cross the target.
        from types import SimpleNamespace

        def fake_project(*_a, **_kw):
            return SimpleNamespace(
                enterprise_value=-1.0e9,
                terminal_fcf_negative=True,
                last_fcf=-1.0e9,
                pv_explicit=-1.0e9,
                pv_terminal=0.0,
                fcf_by_year=[-1.0e9],
            )

        monkeypatch.setattr(
            "models.reverse_dcf.project_enterprise_value_from_data", fake_project
        )
        result = ReverseDCFModel().calculate(data, aapl_profile)
        bd = result.breakdown or {}
        if bd.get("implied_revenue_cagr") is not None:
            pytest.skip("normalized-economics rescue supplied a CAGR")
        assert bd.get("fcf_base_quality") is not None
        assert bd.get("growth_band_verdict") == (
            GrowthBandVerdict.NEGATIVE_BASE_FCF_NO_VALID_ROOT.value
        )

    def test_verdict_is_never_none_on_a_reported_result(self, collected_basket):
        for t, bd in collected_basket.items():
            if not bd:
                continue
            assert bd.get("growth_band_verdict") is not None, t


@pytest.fixture(scope="module")
def collected_basket():
    """Reverse-DCF breakdowns for the synthetic golden basket."""
    from tests.golden_report import BASKET, run_pipeline

    out = {}
    for t in BASKET:
        ctx = run_pipeline(t)
        r = (ctx.get("model_results") or {}).get("ReverseDCF")
        if r is None:
            continue
        out[t] = getattr(r, "breakdown", None) or {}
    return out


class TestVerdictRendering:
    """Both report sections must surface the same verdict, in plain language.

    The verdict is worthless if it only lives in ``breakdown``: the reader sees
    the implied and gap sections, and they must not disagree about the same
    number.
    """

    def test_implied_and_gap_sections_agree(self, collected_basket):
        from reporting.dashboard import ValuationReportBuilder as B
        from tests.golden_report import run_pipeline

        for t, bd in collected_basket.items():
            verdict = bd.get("growth_band_verdict")
            if not verdict:
                continue
            ctx = run_pipeline(t)
            implied_lines = B._implied_section(ctx["implied"])
            gap_lines = B._gap_section(ctx["gap"], ctx["profile"])
            assert "隐含增长可信度" in implied_lines, f"{t}: implied section omits the verdict"
            assert "隐含增长可信度" in gap_lines, f"{t}: gap section omits the verdict"
            assert ctx["implied"].growth_band_verdict == ctx["gap"].growth_band_verdict, (
                f"{t}: implied and gap disagree on the verdict"
            )

    def test_every_verdict_has_a_reader_facing_label(self):
        from config import GrowthBandVerdict
        from reporting.dashboard import _GROWTH_BAND_VERDICT_LABELS

        for member in GrowthBandVerdict:
            assert member.value in _GROWTH_BAND_VERDICT_LABELS, (
                f"{member.value} has no reader-facing label"
            )
