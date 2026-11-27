"""Regression guards for the two §3.1 false-SOLVED paths found in Session #51.

Both defects let a run *report* success that the numbers did not support, which
is the single most dangerous failure mode for this engine: a wrong answer that
looks authoritative.

1. The endpoint short-circuit compared EV against the search bounds with a loose
   1e-3 absolute tolerance and returned SOLVED without computing a residual. A
   target 5e-4 relative away from the endpoint was reported SOLVED.
2. ``ReverseDCFModel`` aliased the module-level ``DEFAULT_REVERSE_DCF_CONFIG``,
   so tuning one instance's tolerances silently rewrote the default for every
   later instance in the process.
"""

from __future__ import annotations

import logging

import pytest

from classification.classifier import BusinessClassifier
from config import DEFAULT_REVERSE_DCF_CONFIG, SolverStatus
from data.normalizer import FinancialNormalizer
from data.providers import SyntheticDataProvider
from data.validator import DataValidator
from forecasts.fcf_projection import project_enterprise_value_from_data
from models.reverse_dcf import ReverseDCFModel

logging.disable(logging.CRITICAL)

WACC, TG, HORIZON = 0.09, 0.025, 5


@pytest.fixture(scope="module")
def inputs():
    d = DataValidator.validate(
        FinancialNormalizer.normalize_all(SyntheticDataProvider().get_financial_data("AAPL"))
    )
    return d, BusinessClassifier().classify(d)


def test_endpoint_short_circuit_cannot_bypass_residual_bar(inputs) -> None:
    """A target just outside the bar of the endpoint EV must be solved, not assumed."""
    data, profile = inputs
    hi = 0.30
    ev_hi = project_enterprise_value_from_data(
        data, profile, hi, None, WACC, TG, HORIZON
    ).enterprise_value
    target = ev_hi * (1 - 5e-4)  # 5x the 1e-4 bar away from the ceiling

    meta: dict = {}
    g, status, _notes, _proj = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, target, WACC, TG, HORIZON,
        cagr_lo=0.0, cagr_hi=hi, meta_out=meta,
    )

    assert status == SolverStatus.SOLVED
    # If it truly solved, the residual must be tiny. If it short-circuited, the
    # residual would still be ~5e-4 - caught here rather than trusted.
    assert meta["relative_residual"] <= 1e-4, meta["relative_residual"]
    actual = project_enterprise_value_from_data(
        data, profile, g, None, WACC, TG, HORIZON
    ).enterprise_value
    assert abs(actual - target) / abs(target) <= 1e-4


def test_endpoint_solve_reports_a_residual_at_all(inputs) -> None:
    """SOLVED must always carry a residual; a None residual hides a bypass."""
    data, profile = inputs
    target = project_enterprise_value_from_data(
        data, profile, 0.20, None, WACC, TG, HORIZON
    ).enterprise_value
    meta: dict = {}
    _g, status, _n, _p = ReverseDCFModel()._solve_revenue_cagr(
        data, profile, target, WACC, TG, HORIZON,
        cagr_lo=0.0, cagr_hi=0.30, meta_out=meta,
    )
    assert status == SolverStatus.SOLVED
    assert meta.get("relative_residual") is not None
    assert meta.get("converged") is True


def test_tuning_one_instance_does_not_pollute_the_default() -> None:
    """Instance config must be a copy, not an alias of the module default."""
    a = ReverseDCFModel()
    a.rcfg.newton_tol = 1e-4
    a.rcfg.price_residual_tol = 1e-1

    b = ReverseDCFModel()
    assert b.rcfg.newton_tol == DEFAULT_REVERSE_DCF_CONFIG.newton_tol == 1e-10
    assert b.rcfg.price_residual_tol == 1e-4
    assert a.rcfg is not b.rcfg
    assert b.rcfg is not DEFAULT_REVERSE_DCF_CONFIG


def test_explicit_config_override_is_also_isolated() -> None:
    """Passing a config must not link two models to the same object."""
    from dataclasses import replace

    from config import ReverseDCFConfig

    cfg = replace(ReverseDCFConfig())
    m1 = ReverseDCFModel(reverse_config=cfg)
    m1.rcfg.newton_tol = 1e-3
    assert cfg.newton_tol == ReverseDCFConfig().newton_tol
    m2 = ReverseDCFModel(reverse_config=cfg)
    assert m2.rcfg.newton_tol == ReverseDCFConfig().newton_tol
