"""P0 — a direction conclusion must survive the ΔNWC inference.

The marginal ΔNWC ratio is inferred as a residual (NOPAT + D&A − capex − FCF),
so it absorbs one-off working-capital swings. On the 50-ticker benchmark the
EV-vs-growth *direction* flips at a plausible ratio for 13 of 41 tickers, which
means "growth destroys value" cannot be asserted from a single point estimate.

These tests pin the contract:
  * a direction stable across candidates may be reported as a mechanism;
  * a direction that flips must be reported as undetermined, and the reported
    flip point must be the *actual* sign change, not the span of candidates;
  * the binding label must not contradict the undetermined verdict.
"""
from __future__ import annotations

from types import SimpleNamespace


from models.reverse_dcf import ReverseDCFModel


class _Model(ReverseDCFModel):
    """Reverse DCF whose EV curve is supplied directly, so the test controls
    the direction without depending on any real company's financials."""

    def __init__(self, ev_fn):
        super().__init__()
        self._ev_fn = ev_fn

    def _project_ev(self, data, profile, rev_cagr, wacc, tg, horizon, nwc_ratio=None):
        return self._ev_fn(rev_cagr, nwc_ratio)


_DATA = SimpleNamespace(ttm=SimpleNamespace(revenue=100.0))
_PROFILE = SimpleNamespace(business_type="Unknown")


def _robustness(ev_fn, ratios):
    model = _Model(ev_fn)
    return model._ev_direction_robustness(
        _DATA, _PROFILE, 0.09, 0.02, 5, -0.10, 0.30, ratios
    )


class TestDirectionRobustness:
    def test_stable_decreasing_is_reported_as_decreasing(self):
        result = _robustness(lambda g, nwc: 900.0 - 500.0 * g, [0.0, 0.1, 0.2])
        assert result["robust"] is True
        assert result["direction"] == "decreasing"
        assert result["flips_between"] is None

    def test_stable_increasing_is_reported_as_increasing(self):
        result = _robustness(lambda g, nwc: 900.0 + 500.0 * g, [0.0, 0.1, 0.2])
        assert result["robust"] is True
        assert result["direction"] == "increasing"

    def test_flip_is_reported_as_mixed_not_as_a_mechanism(self):
        # Rising at a low NWC ratio, falling at a high one — the real NEE shape.
        def ev(g, nwc):
            return 1000.0 + g * (50.0 - 400.0 * (nwc or 0.0))

        result = _robustness(ev, [0.0, 0.05, 0.10, 0.20])
        assert result["robust"] is False
        assert result["direction"] == "mixed"

    def test_flip_point_is_the_actual_sign_change_not_the_candidate_span(self):
        def ev(g, nwc):
            return 1000.0 + g * (50.0 - 400.0 * (nwc or 0.0))

        ratios = [-0.10, 0.0, 0.05, 0.10, 0.15, 0.20, 0.30]
        result = _robustness(ev, ratios)
        flips = result["flips_between"]
        assert flips, "a mixed direction must name where it flips"
        # The flip must be an adjacent candidate pair, not (min, max) of the set.
        for lo, hi in flips:
            assert lo in ratios and hi in ratios
            assert ratios.index(hi) == ratios.index(lo) + 1
        assert flips != [(min(ratios), max(ratios))]

    def test_by_nwc_ratio_records_every_direction(self):
        def ev(g, nwc):
            return 1000.0 + g * (50.0 - 400.0 * (nwc or 0.0))

        ratios = [0.0, 0.2]
        result = _robustness(ev, ratios)
        by = result["by_nwc_ratio"]
        assert set(by) == {0.0, 0.2}
        assert by[0.0] == 1
        assert by[0.2] == -1

    def test_no_successful_projection_is_not_robust(self):
        def ev(g, nwc):
            raise RuntimeError("projection failed")

        result = _robustness(ev, [0.0, 0.1])
        assert result["robust"] is False
        assert result["reason"] == "no_projection_succeeded"


class TestBindingDoesNotContradictUndetermined:
    """SO showed the failure this guards: one note said the direction was
    sensitive, another asserted "implied growth >= ceiling"."""

    def test_undetermined_binding_kind_exists_and_renders(self):
        from reporting.dashboard import ValuationReportBuilder

        source = ValuationReportBuilder.__module__
        import importlib
        mod = importlib.import_module(source)
        src = open(mod.__file__, encoding="utf-8").read()
        assert "ev_direction_undetermined" in src, (
            "the undetermined binding kind must have a render branch, or the "
            "report would fall through to a contradictory default"
        )

    def test_mechanism_asserted_only_when_direction_is_robust(self):
        src = open(
            "/workspace/telegram-stock-valuation-engine/models/reverse_dcf.py",
            encoding="utf-8",
        ).read()
        # The mechanism wording must sit behind the undetermined guard.
        idx_guard = src.index("if direction_undetermined:")
        idx_mechanism = src.index("增长所需的再投资")
        assert idx_guard < idx_mechanism, (
            "the reinvestment mechanism must only be stated when the direction "
            "is not undetermined"
        )
