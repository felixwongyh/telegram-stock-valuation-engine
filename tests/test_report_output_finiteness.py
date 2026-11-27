"""The report boundary must never emit a non-finite token (Session #52).

Every formatter is a place where a bad number can escape as text. ``float('nan')``
formats happily as ``"nan"``, so ``f"${v:,.2f}"`` renders ``"$nan"`` - a value
that looks like money and is not a number. These tests pin the boundary: the
dashboard formatters and the reverse-DCF breakdown must degrade to ``N/A`` or a
data-quality status instead of printing an impossible figure.
"""

from __future__ import annotations

import math

import pytest

from reporting.dashboard import _fmt_money, _fmt_num, _fmt_pct, _fmt_recon, _fmt_share

NON_FINITE = (float("nan"), float("inf"), float("-inf"))
FORMATTERS = (_fmt_money, _fmt_share, _fmt_pct, _fmt_num, _fmt_recon)


@pytest.mark.parametrize("fmt", FORMATTERS, ids=lambda f: f.__name__)
@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "pos_inf", "neg_inf"])
def test_formatters_render_non_finite_as_na(fmt, bad) -> None:
    out = fmt(bad)
    assert out == "N/A", f"{fmt.__name__}({bad!r}) rendered {out!r}"


@pytest.mark.parametrize("fmt", FORMATTERS, ids=lambda f: f.__name__)
def test_formatters_still_format_real_numbers(fmt) -> None:
    out = fmt(1234.5)
    assert out != "N/A"
    assert "nan" not in out.lower() and "inf" not in out.lower()


def test_formatters_never_contain_nan_or_inf_substrings() -> None:
    """A single sweep over the sentinel values, as a text-level guarantee."""
    for fmt in FORMATTERS:
        for bad in NON_FINITE + (1e308 * 10, -1e308 * 10):
            text = fmt(bad).lower()
            assert "nan" not in text, f"{fmt.__name__} leaked {text!r}"
            assert "inf" not in text, f"{fmt.__name__} leaked {text!r}"


def test_fmt_money_handles_large_but_finite_values() -> None:
    """Guard against over-eager rejection: finite magnitudes must still print."""
    assert _fmt_money(2.5e12) == "$2T"  # default decimals=0 rounds to whole units
    assert _fmt_money(2.5e12, decimals=1) == "$2.5T"
    assert _fmt_money(3.2e9) == "$3B"
    assert math.isfinite(2.5e12)


# ---------------------------------------------- the analysis layer's copies

def test_divergence_share_formatter_rejects_non_finite() -> None:
    from analysis.divergence import _fmt_share as div_share

    for bad in NON_FINITE:
        assert div_share(bad) == "N/A"
    assert div_share(12.5) == "$12.50"


def test_model_agreement_table_never_prints_nan_share_count() -> None:
    """``float('nan')`` is truthy, so a plain ``if x`` guard is not enough."""
    from analysis.model_agreement import (
        ModelAgreement,
        ShareCountAuditRow,
    )

    rows = [
        ShareCountAuditRow(
            model="ReverseDCF",
            share_count=float("nan"),
            basis="TTM",
            deviation_vs_market=float("inf"),
            comparable=True,
        ),
        ShareCountAuditRow(
            model="DCF",
            share_count=1.5e9,
            basis="TTM",
            deviation_vs_market=0.0123,
            comparable=True,
        ),
    ]
    agreement = ModelAgreement(
        n_applicable=2, n_solved=2, values={}, share_count_audit=rows
    )
    table = agreement.share_count_audit_table()
    assert "nan" not in table.lower()
    assert "inf" not in table.lower()
    assert "1,500,000,000" in table
    assert "+1.2%" in table


# ------------------------------------- benchmark report: the last gate

def _report_status(**over):
    from benchmark.report import _final_status

    facts = {"ticker": "TEST", "rd_status": "Solved"}
    facts.update(over)
    return _final_status(facts, None)


def test_benchmark_report_maps_non_finite_projection_to_data_error() -> None:
    status, reason = _report_status(
        rd_status="Data Quality Error (Non-Finite Projection)"
    )
    assert status == "DATA_ERROR"
    assert "Non-Finite" in reason or "solver" in reason


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "pos_inf", "neg_inf"])
def test_benchmark_report_never_reports_solved_with_non_finite_residual(bad) -> None:
    """A NaN residual passes ``rr <= bar``, so the report must check explicitly."""
    status, _reason = _report_status(
        rd_solver_meta={"converged": True, "relative_residual": bad}
    )
    assert status != "SOLVED", f"non-finite residual {bad!r} reported as SOLVED"


def test_benchmark_report_never_reports_solved_without_convergence_record() -> None:
    status, _reason = _report_status(rd_solver_meta={"relative_residual": 1e-9})
    assert status != "SOLVED"


def test_benchmark_report_still_reports_a_clean_solve() -> None:
    status, reason = _report_status(
        rd_solver_meta={"converged": True, "relative_residual": 1e-9},
        rd_growth_band_verdict="WITHIN_BAND",
    )
    assert status == "SOLVED"
    assert reason
