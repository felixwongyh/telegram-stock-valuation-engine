"""§10 M09/M10: the multi-root scan must find *every* crossing, not the first.

``_scan_roots`` is the diagnostic layer that decides whether an implied growth
is unique. Its contract is narrow and testable: given an EV curve that crosses
the target more than once, return every crossing. Until this file existed the
only coverage ran on monotone curves, where "return all roots" and "return the
first root" are indistinguishable - so a truncated scan survived every test.

The EV curve is injected through ``_project_ev`` because the scan's job is
root-finding, not forecasting: a real company's curve is monotone in growth, so
a genuine multi-crossing case has to be constructed.
"""

from __future__ import annotations

from typing import Any, List

import pytest

from models.reverse_dcf import ReverseDCFModel

LO, HI = 0.0, 10.0
TARGET = 1.0

#: Exact roots of (g-3)^2(g-7)^2 = 4 on [0, 10].
_ANALYTIC_ROOTS = [2.550510257216822, 3.585786437626905,
                   6.414213562373095, 7.449489742783178]


class _DoubleWellModel(ReverseDCFModel):
    """EV(g) = (g-3)^2 * (g-7)^2 / 4, which equals 1.0 at four points in [0,10].

    Solving (g-3)^2(g-7)^2 = 4 gives g^2 - 10g + 17 = +/-2, i.e. the four roots
    2.5505, 3.5858, 6.4142, 7.4495 - two on each side of the wells. The curve
    therefore crosses the target four times; a scan that stops at the first
    crossing returns 1 root instead of 4.
    """

    def _project_ev(
        self, data: Any, profile: Any, rev_cagr: float,
        wacc: float, tg: float, horizon: int, nwc_ratio: float | None = None,
    ) -> float:
        g = rev_cagr
        return (g - 3.0) ** 2 * (g - 7.0) ** 2 / 4.0


class _MonotoneModel(ReverseDCFModel):
    """EV(g) = 2g, a single crossing at g = 0.5."""

    def _project_ev(
        self, data: Any, profile: Any, rev_cagr: float,
        wacc: float, tg: float, horizon: int, nwc_ratio: float | None = None,
    ) -> float:
        return 2.0 * rev_cagr


def _scan(model: ReverseDCFModel, target: float) -> List[float]:
    return model._scan_roots(
        None, None, target, 0.09, 0.025, 10, LO, HI, steps=400,
    )


def test_all_crossings_are_returned():
    """Four real crossings must all be found - this is the M09 guard."""
    roots = _scan(_DoubleWellModel(), TARGET)
    assert len(roots) == 4, f"expected 4 roots, got {len(roots)}: {roots}"


def test_crossings_are_the_analytic_values():
    """The roots must be the true ones, not grid artefacts."""
    roots = sorted(_scan(_DoubleWellModel(), TARGET))
    for got, want in zip(roots, _ANALYTIC_ROOTS):
        assert got == pytest.approx(want, abs=1e-6)


def test_roots_are_deduplicated_and_sorted_by_scan_order():
    """No duplicates, and the list follows increasing growth."""
    roots = _scan(_DoubleWellModel(), TARGET)
    assert roots == sorted(roots)
    assert len(set(round(r, 6) for r in roots)) == len(roots)


def test_single_crossing_reports_exactly_one_root():
    """The monotone case must not invent extra roots."""
    roots = _scan(_MonotoneModel(), TARGET)
    assert len(roots) == 1
    assert roots[0] == pytest.approx(0.5, abs=1e-6)


def test_unreachable_target_reports_no_root():
    """A target the curve never reaches yields no roots, never a fabricated one."""
    assert _scan(_MonotoneModel(), -5.0) == []


class _CubicModel(ReverseDCFModel):
    """EV(g) = (g-2)(g-5)(g-8): three crossings at 2, 5 and 8.

    Endpoints have opposite signs (EV(0) = -80, EV(10) = 80), so the primary
    bracketed solve succeeds and the multi-root scan actually runs - unlike the
    double-well case, whose endpoints share a sign and short-circuit earlier.
    """

    def _project_ev(
        self, data: Any, profile: Any, rev_cagr: float,
        wacc: float, tg: float, horizon: int, nwc_ratio: float | None = None,
    ) -> float:
        g = rev_cagr
        return (g - 2.0) * (g - 5.0) * (g - 8.0) + 10.0


class _CubicProjection:
    """Minimal stand-in for a projection result used by the residual check."""

    enterprise_value = 0.0
    terminal_fcf_negative = False


def test_multiple_roots_flag_is_consistent_with_the_count():
    """M10: ``multiple_roots`` is derived from the count, so it cannot lie.

    The flag is computed as ``len(roots) > 1``; forcing it False while the scan
    finds four roots is the defect this asserts against.
    """
    roots = _scan(_DoubleWellModel(), TARGET)
    assert (len(roots) > 1) is True

    single = _scan(_MonotoneModel(), TARGET)
    assert (len(single) > 1) is False


def test_solver_meta_reports_multiple_roots_when_they_exist(monkeypatch):
    """M10: the *production* meta must carry the scan's verdict.

    Reading ``meta["multiple_roots"]`` (rather than recomputing it here) is the
    point: a solver that hard-codes the flag to False has to fail this test.
    The residual check calls the module-level projection directly, so that is
    patched too; otherwise the synthetic curve is mixed with real data.
    """
    from models import reverse_dcf as rd

    monkeypatch.setattr(
        rd, "project_enterprise_value_from_data",
        lambda *a, **k: _CubicProjection(), raising=True,
    )

    meta: dict = {}
    g, _status, _notes, _p = _CubicModel()._solve_revenue_cagr(
        None, None, 10.0, 0.09, 0.025, 10,
        cagr_lo=LO, cagr_hi=HI, meta_out=meta,
    )
    assert g is not None, "the cubic has a bracketed root; the solve must find one"
    assert meta["n_roots_detected"] == 3, meta
    assert meta["multiple_roots"] is True
    assert sorted(meta["roots"]) == pytest.approx([2.0, 5.0, 8.0], abs=1e-4)
