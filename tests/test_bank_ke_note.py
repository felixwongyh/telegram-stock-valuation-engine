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


# ---------------------------------------------------------------------------
# Three-layer Ke decomposition (spec 3.4 / 8.2): raw → selected → used.
# Beta adjustment and the bank Ke band clamp must be reported separately, and
# the two layers must sum to the total. Attributing a band clamp to "beta" is a
# misreport, so these tests pin the attribution.
# ---------------------------------------------------------------------------
def _layered_chain(
    raw_beta: float,
    selected_beta: float,
    used_beta: float,
    *,
    rf: float = RF,
    erp: float = ERP,
    normalization_method: str = "none",
    valuation_beta_reason: str = "normalized_beta (no override)",
) -> dict:
    chain = _chain(
        raw_beta,
        used_beta,
        rf=rf,
        erp=erp,
        normalization_method=normalization_method,
        valuation_beta_reason=valuation_beta_reason,
    )
    chain["normalized_beta"] = selected_beta
    chain["normalized_ke"] = rf + selected_beta * erp
    return chain


def test_three_layer_split_attributes_clamp_not_beta():
    """GS-style case: pure band clamp must load onto the clamp layer, not beta."""
    raw, selected, used = 1.368, 1.368, 1.090909090909091
    note = build_bank_ke_note(
        _layered_chain(
            raw, selected, used,
            valuation_beta_reason="bank ke band clamp: normalized_beta",
        ),
        base_ke=_ke(used),
        base_beta=used,
        risk_free=RF,
        erp=ERP,
    )
    assert note is not None
    assert "分层" in note
    # No beta shrinkage happened → beta layer is exactly zero.
    assert "β 调整 +0.0 bps" in note
    expected_clamp = (_ke(used) - _ke(selected)) * 10000.0
    assert f"银行 Ke 区间夹紧 {expected_clamp:+.1f} bps" in note


def test_three_layer_split_attributes_shrinkage_not_clamp():
    """Blume/winsorize-only case: adjustment must load onto the beta layer."""
    raw, selected, used = 1.80, 1.52, 1.52
    note = build_bank_ke_note(
        _layered_chain(raw, selected, used, normalization_method="blume_shrinkage_0.35"),
        base_ke=_ke(used),
        base_beta=used,
        risk_free=RF,
        erp=ERP,
    )
    assert note is not None
    expected_beta_adj = (_ke(selected) - _ke(raw)) * 10000.0
    assert f"β 调整 {expected_beta_adj:+.1f} bps" in note
    assert "银行 Ke 区间夹紧 +0.0 bps" in note


def test_three_layer_split_layers_sum_to_total():
    """beta_adj + clamp must equal the total difference, to 1e-6 bps."""
    raw, selected, used = 1.368, 1.30, 1.090909090909091
    note = build_bank_ke_note(
        _layered_chain(raw, selected, used),
        base_ke=_ke(used),
        base_beta=used,
        risk_free=RF,
        erp=ERP,
    )
    assert note is not None
    beta_adj = (_ke(selected) - _ke(raw)) * 10000.0
    clamp = (_ke(used) - _ke(selected)) * 10000.0
    total = (_ke(used) - _ke(raw)) * 10000.0
    assert abs((beta_adj + clamp) - total) < 1e-6
    assert f"β 调整 {beta_adj:+.1f} bps" in note
    assert f"银行 Ke 区间夹紧 {clamp:+.1f} bps" in note
    assert f"差异 {total:+.1f} bps" in note


def test_inconsistent_layered_chain_yields_no_note():
    """A chain whose layers do not reconcile must be rejected, not misreported."""
    chain = _layered_chain(1.368, 1.368, 1.090909090909091)
    # Corrupt the intermediate Ke so beta_adj + clamp != total.
    chain["normalized_ke"] = chain["normalized_ke"] + 0.01
    assert build_bank_ke_note(
        chain, base_ke=_ke(1.090909090909091), base_beta=1.090909090909091,
        risk_free=RF, erp=ERP,
    ) is None


def test_chain_without_normalization_fields_has_no_layer_clause():
    """Legacy/partial chains must not gain a fabricated 0 bps beta layer."""
    note = build_bank_ke_note(
        _chain(1.10, 1.10),
        base_ke=_ke(1.10),
        base_beta=1.10,
        risk_free=RF,
        erp=ERP,
    )
    assert note is not None
    assert "分层" not in note


def test_assumed_rf_is_surfaced_as_not_market_observed():
    """An assumed default Rf must be labelled, never implied as market data."""
    chain = _chain(1.0, 1.0)
    chain["risk_free_source"] = "assumed_default_4pct (snapshot Rf missing)"
    note = build_bank_ke_note(
        chain, base_ke=_ke(1.0), base_beta=1.0, risk_free=RF, erp=ERP,
    )
    assert note is not None
    assert "假定默认" in note
    assert "非市场实测" in note

    # A market-sourced Rf must NOT carry the assumed-default warning.
    chain2 = _chain(1.0, 1.0)
    chain2["risk_free_source"] = "^TNX US 10Y Treasury (Yahoo)"
    note2 = build_bank_ke_note(
        chain2, base_ke=_ke(1.0), base_beta=1.0, risk_free=RF, erp=ERP,
    )
    assert note2 is not None
    assert "假定默认" not in note2



# ---------------------------------------------------------------------------
# Field-semantics contract (GS fixture): the beta implied by a clamped Ke must
# never be reported as the *selected* beta. 1.091 = (10% − 4%) / 5.5% is a
# derived equivalent, not a selection outcome, so the note must keep them apart.
# ---------------------------------------------------------------------------
def test_clamped_note_labels_equivalent_beta_as_derived_not_selected():
    """GS fixture basis: Rf=4%, ERP=5.5% → clamped Ke 10% implies β=1.0909."""
    rf, erp = 0.04, 0.055
    raw = 1.368
    selected = 1.368                      # selection layer chose the raw beta
    used_ke = 0.10
    clamp_equiv = (used_ke - rf) / erp    # 1.0909..., implied by the clamped Ke
    assert clamp_equiv == pytest.approx(1.090909090909091, abs=1e-12)

    chain = _layered_chain(
        raw, selected, clamp_equiv, rf=rf, erp=erp,
        valuation_beta_reason="bank ke band clamp: normalized_beta (no override)",
    )
    chain["beta_selected"] = selected
    chain["clamp_equivalent_beta"] = clamp_equiv

    note = build_bank_ke_note(
        chain, base_ke=used_ke, base_beta=clamp_equiv, risk_free=rf, erp=erp,
    )
    assert note is not None
    # The selected beta is the pre-clamp value.
    assert f"选定 β={selected:.3f}" in note
    # The clamp-implied beta is labelled as derived, never as a selection.
    assert f"夹紧等效 β={clamp_equiv:.3f}" in note
    assert "非选择结果" in note
    # The clamp must not be attributed to a beta adjustment.
    assert "β 调整 +0.0 bps" in note
    expected_clamp = (used_ke - (rf + selected * erp)) * 10000.0
    assert f"银行 Ke 区间夹紧 {expected_clamp:+.1f} bps" in note
    # Round-tripping the reported equivalent beta reproduces the used Ke.
    assert rf + clamp_equiv * erp == pytest.approx(used_ke, abs=1e-12)


def test_unclamped_note_keeps_plain_used_beta_wording():
    """Without a clamp there is no equivalent-beta language at all."""
    beta = 1.10
    chain = _layered_chain(beta, beta, beta)
    chain["beta_selected"] = beta
    note = build_bank_ke_note(
        chain, base_ke=_ke(beta), base_beta=beta, risk_free=RF, erp=ERP,
    )
    assert note is not None
    assert "夹紧等效" not in note
    assert f"采用 β={beta:.3f}" in note
