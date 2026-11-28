"""Algorithm fingerprints must cover dependencies, not just the anchor.

The property under test: a derivation can change without its anchor's source
changing. Two ways that happens, both caught here by mutating real code at
runtime:

* a helper called from the anchor is edited;
* a module-level constant the anchor reads is rebound.

If either escapes the fingerprint, then "the algorithm version did not change"
stops meaning anything, and a reconciliation report would attribute a moved
number to the data.
"""

from __future__ import annotations

import sys
import types

import pytest

from data.algorithm_versions import (
    ALGORITHM_VERSIONS,
    _collect_dependencies,
    dependency_fingerprint,
    fingerprint_table,
    source_fingerprint,
)


def test_every_method_has_a_distinct_dependency_fingerprint():
    """Five methods share ``_build_statements``; before the method identity was
    mixed in, all five hashed identically and an edit could not be attributed."""
    table = fingerprint_table()
    fps = [v["dependency_fingerprint"] for v in table.values()]
    assert len(set(fps)) == len(fps), "dependency fingerprints collide"


def test_unknown_method_is_not_silently_versioned():
    from data.algorithm_versions import version_of

    assert version_of("NOT_A_REAL_METHOD") is None


def test_closure_reaches_helpers_and_constants():
    """TTM_SUM_4Q should depend on its helpers, not only on its own body."""
    deps = dependency_fingerprint("TTM_SUM_4Q")["dependencies"]
    assert any("_ttm_eps" in d for d in deps), deps
    assert any("stamp" in d for d in deps), deps


def test_nwc_closure_reaches_its_helpers():
    deps = dependency_fingerprint("NWC_FROM_NOPAT_DA_CAPEX_FCF")["dependencies"]
    assert any("effective_tax_rate" in d for d in deps), deps
    assert any("capex_cash_outflow" in d for d in deps), deps


# ------------------------------------------------ mutation of a real dependency

def test_editing_a_helper_moves_the_fingerprint(monkeypatch):
    """Change a helper's arithmetic, keep the anchor byte-identical."""
    import data.nwc_utils as nwc

    before = dependency_fingerprint("NWC_FROM_NOPAT_DA_CAPEX_FCF")["fingerprint"]

    # Replace the helper with a semantically different function that keeps the
    # same name, which is what a real edit looks like to the caller.
    def effective_tax_rate(*args, **kwargs):
        return 0.99  # deliberately different from whatever the real one does

    monkeypatch.setattr(nwc, "effective_tax_rate", effective_tax_rate)

    after = dependency_fingerprint("NWC_FROM_NOPAT_DA_CAPEX_FCF")["fingerprint"]
    assert after != before, "a helper edit must change the closure fingerprint"


def test_changing_a_constant_moves_the_fingerprint(monkeypatch):
    """Rebind a constant the anchor reads; its expression text is unchanged."""
    import data.normalizer as norm

    before = dependency_fingerprint("TTM_SUM_4Q")["fingerprint"]
    monkeypatch.setattr(norm, "_DERIVED", "a-different-sentinel")
    after = dependency_fingerprint("TTM_SUM_4Q")["fingerprint"]
    assert after != before, "a constant change must change the closure fingerprint"


def test_anchor_only_fingerprint_does_not_see_helper_edits(monkeypatch):
    """Documents *why* the closure exists: the narrow fingerprint is blind here.

    This is not a defect being asserted as correct -- it is the gap the closure
    fingerprint closes, pinned so nobody "simplifies" back to the narrow one.
    """
    import data.nwc_utils as nwc

    narrow_before = source_fingerprint("NWC_FROM_NOPAT_DA_CAPEX_FCF")
    wide_before = dependency_fingerprint("NWC_FROM_NOPAT_DA_CAPEX_FCF")["fingerprint"]

    def effective_tax_rate(*args, **kwargs):
        return 0.99

    monkeypatch.setattr(nwc, "effective_tax_rate", effective_tax_rate)

    narrow_after = source_fingerprint("NWC_FROM_NOPAT_DA_CAPEX_FCF")
    wide_after = dependency_fingerprint("NWC_FROM_NOPAT_DA_CAPEX_FCF")["fingerprint"]

    assert narrow_after == narrow_before, "narrow hash cannot see a helper edit"
    assert wide_after != wide_before, "closure hash must see it"


def test_dependency_walk_is_depth_bounded():
    """A deep graph must terminate rather than hash the whole package."""
    deps = _collect_dependencies(_collect_dependencies, max_depth=1)
    assert len(deps) < 50


def test_all_registered_methods_are_fingerprintable():
    for method in ALGORITHM_VERSIONS:
        fp = dependency_fingerprint(method)["fingerprint"]
        assert fp not in ("unavailable", "unparsable"), method
        assert len(fp) == 16, method
