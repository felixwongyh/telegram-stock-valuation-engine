"""Tests for the bank Monte Carlo raw-vs-adjusted CAPM Ke note.

The note is purely explanatory: it must report the Ke the valuation actually
used against the unmodified CAPM Ke on the same Rf/ERP basis, and must stay
silent rather than fabricate a line when the data cannot support one.
"""
from __future__ import annotations

import math

import pytest

from simulation.monte_carlo import build_bank_ke_note

RF = 0.04
ERP = 0.06


def _chain(
    raw_beta: float,
    used_beta: float,
    *,
    rf: float = RF,
    erp: float = ERP,
    normalization_method: str = "none",
    valuation_beta_reason: str = "normalized_beta (no override)",
    raw_capm_ke: float | None = None,
) -> dict:
    return {
        "risk_free_rate": rf,
        "equity_risk_premium": erp,
        "raw_beta": raw_beta,
        "valuation_beta": used_beta,
        "raw_capm_ke": rf + raw_beta * erp if raw_capm_ke is None else raw_capm_ke,
        "normalization_method": normalization_method,
        "valuation_beta_reason": valuation_beta_reason,
        "raw_beta_source": "Provider regression beta",
    }


def _ke(beta: float, rf: float = RF, erp: float = ERP) -> float:
    return rf + beta * erp


# 1. Raw beta differs from the Blume-shrunk beta.
def test_blume_adjusted_beta_differs_from_raw():
    raw = 1.80
    shrunk = 0.65 * raw + 0.35 * 1.0
    note = build_bank_ke_note(
        _chain(raw, shrunk, normalization_method="blume_shrinkage_0.35"),
        base_ke=_ke(shrunk),
        base_beta=shrunk,
        risk_free=RF,
        erp=ERP,
    )
    assert note is not None
    assert f"原始 β={raw:.3f}" in note
    assert f"采用 β={shrunk:.3f}" in note
    assert "Blume" in note


# 2. Raw beta differs from the bottom-up selected beta.
def test_bottom_up_beta_differs_from_raw():
    raw, bottom_up = 1.40, 0.95
    note = build_bank_ke_note(
        _chain(raw, bottom_up),
        base_ke=_ke(bottom_up),
        base_beta=bottom_up,
        risk_free=RF,
        erp=ERP,
        selection_method="bottom_up",
    )
    assert note is not None
    assert "bottom_up" in note
    assert f"采用 β={bottom_up:.3f}" in note


# 3. Raw beta equals the used beta -> no adjustment claimed.
def test_raw_beta_equals_used_beta():
    beta = 1.10
    note = build_bank_ke_note(
        _chain(beta, beta),
        base_ke=_ke(beta),
        base_beta=beta,
        risk_free=RF,
        erp=ERP,
    )
    assert note is not None
    assert f"原始 β={beta:.3f}" in note
    assert f"采用 β={beta:.3f}" in note
    assert "未调整" in note
    assert "+0.0 bps" in note


# 4. Ke difference positive (used Ke above raw Ke).
def test_ke_difference_positive():
    raw, used = 0.60, 0.90
    note = build_bank_ke_note(
        _chain(raw, used),
        base_ke=_ke(used),
        base_beta=used,
        risk_free=RF,
        erp=ERP,
    )
    assert note is not None
    expected_bps = (_ke(used) - _ke(raw)) * 10000.0
    assert expected_bps > 0
    assert f"{expected_bps:+.1f} bps" in note


# 5. Ke difference negative (used Ke below raw Ke, e.g. bank band clamp).
def test_ke_difference_negative():
    raw, used = 1.368, 1.0
    note = build_bank_ke_note(
        _chain(
            raw,
            used,
            valuation_beta_reason="bank ke band clamp: normalized_beta",
        ),
        base_ke=_ke(used),
        base_beta=used,
        risk_free=RF,
        erp=ERP,
    )
    assert note is not None
    expected_bps = (_ke(used) - _ke(raw)) * 10000.0
    assert expected_bps < 0
    assert f"{expected_bps:+.1f} bps" in note
    assert "银行 Ke 区间夹紧" in note


# 6. Ke difference zero -> explicit "未调整", still shows +0.0 bps.
def test_ke_difference_zero():
    beta = 0.85
    note = build_bank_ke_note(
        _chain(beta, beta),
        base_ke=_ke(beta),
        base_beta=beta,
        risk_free=RF,
        erp=ERP,
    )
    assert note is not None
    assert "+0.0 bps" in note
    assert "未调整" in note


# 7. Missing beta data -> no note.
@pytest.mark.parametrize(
    "chain",
    [
        None,
        {},
        {"raw_beta": None, "valuation_beta": 1.0, "raw_capm_ke": 0.10,
         "risk_free_rate": RF, "equity_risk_premium": ERP},
        {"raw_beta": 1.0, "valuation_beta": None, "raw_capm_ke": 0.10,
         "risk_free_rate": RF, "equity_risk_premium": ERP},
        {"raw_beta": 1.0, "valuation_beta": 1.0, "raw_capm_ke": None,
         "risk_free_rate": RF, "equity_risk_premium": ERP},
    ],
)
def test_missing_beta_data_yields_no_note(chain):
    assert build_bank_ke_note(
        chain, base_ke=0.10, base_beta=1.0, risk_free=RF, erp=ERP
    ) is None


# 8. NaN / Infinity inputs -> no note.
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_inputs_yield_no_note(bad):
    assert build_bank_ke_note(
        _chain(1.0, 1.0), base_ke=bad, base_beta=1.0, risk_free=RF, erp=ERP
    ) is None
    assert build_bank_ke_note(
        _chain(1.0, 1.0), base_ke=0.10, base_beta=bad, risk_free=RF, erp=ERP
    ) is None
    chain = _chain(1.0, 1.0)
    chain["raw_beta"] = bad
    assert build_bank_ke_note(
        chain, base_ke=0.10, base_beta=1.0, risk_free=RF, erp=ERP
    ) is None


# 9. Different beta selection methods are surfaced distinctly.
@pytest.mark.parametrize(
    "method",
    ["bottom_up", "regression", "fallback"],
)
def test_selection_method_surfaced(method):
    note = build_bank_ke_note(
        _chain(1.2, 1.1),
        base_ke=_ke(1.1),
        base_beta=1.1,
        risk_free=RF,
        erp=ERP,
        selection_method=method,
    )
    assert note is not None
    assert method in note


# 10. Note is consistent with the actual Monte Carlo Ke input.
def test_note_matches_monte_carlo_ke_input():
    raw, used = 1.5, 1.090909090909091
    rf, erp = 0.042, 0.055
    # base_ke is exactly what the simulation draws around: rf + used_beta * erp
    base_ke = rf + used * erp
    note = build_bank_ke_note(
        _chain(raw, used, rf=rf, erp=erp),
        base_ke=base_ke,
        base_beta=used,
        risk_free=rf,
        erp=erp,
    )
    assert note is not None
    assert f"采用 Ke={base_ke:.2%}" in note

    # A chain that does NOT reproduce the simulation's Ke must be rejected,
    # otherwise the reported difference would describe a different basis.
    assert build_bank_ke_note(
        _chain(raw, used, rf=rf, erp=erp),
        base_ke=base_ke + 0.01,
        base_beta=used,
        risk_free=rf,
        erp=erp,
    ) is None
    # Likewise when Rf/ERP differ from the chain's own basis.
    assert build_bank_ke_note(
        _chain(raw, used, rf=rf, erp=erp),
        base_ke=base_ke,
        base_beta=used,
        risk_free=rf + 0.005,
        erp=erp,
    ) is None


def test_note_reaches_rendered_report():
    """The note must be user-visible, not just present on the result object."""
    from types import SimpleNamespace

    from reporting.dashboard import bank_ke_note_lines

    note = build_bank_ke_note(
        _chain(1.368, 1.0, valuation_beta_reason="bank ke band clamp: normalized_beta"),
        base_ke=_ke(1.0),
        base_beta=1.0,
        risk_free=RF,
        erp=ERP,
    )
    assert note is not None

    lines = bank_ke_note_lines(SimpleNamespace(notes=["unrelated", note]))
    assert len(lines) == 1
    assert "CAPM Ke 溯源" in lines[0]
    assert "bps" in lines[0]
    assert lines[0].startswith("  • ")

    # No note -> nothing rendered (never a placeholder line).
    assert bank_ke_note_lines(SimpleNamespace(notes=["unrelated"])) == []
    assert bank_ke_note_lines(SimpleNamespace(notes=[])) == []
