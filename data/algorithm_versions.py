"""Canonical algorithm versions for every derived/imputed/estimated value.

Requirement (Phase 1, rule 3): "when the algorithm version changes the change
must be recorded". That can only be enforced if the version is attached to the
*implementation*, not asserted in prose. Each entry names a version string and
the function whose source implements it; ``source_fingerprint()`` hashes that
source so an edit that changes behaviour without a version bump is detectable
(see ``tests/test_provenance_breakage.py``).

Adding a method or editing an implementation is therefore a two-step change:
edit the code, then regenerate ``data/provenance_baseline.json`` via
``python -m data.algorithm_versions --write-baseline``. The diff of that file is
the record of the change.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

BASELINE_PATH = Path(__file__).resolve().parent / "provenance_baseline.json"


@dataclass(frozen=True)
class AlgorithmSpec:
    """Version + the function that implements the derivation."""

    version: str
    anchor: str        # "module:function" - the implementation to fingerprint
    description: str


#: Every derivation method that can appear in ``FieldProvenance.derivation_method``.
#: A method absent here stamps ``algorithm_version=None`` and is reported by the
#: audit as *unversioned*, which the coverage test treats as a failure.
ALGORITHM_VERSIONS: Dict[str, AlgorithmSpec] = {
    # --- providers._build_statements -------------------------------------
    "NI_PLUS_INTEREST_PLUS_TAX": AlgorithmSpec(
        "1", "data.providers:YahooFinanceProvider._build_statements",
        "EBIT := net_income + |interest_expense| + |income_tax|"),
    "REVENUE_X_PRIOR_MARGIN": AlgorithmSpec(
        "1", "data.providers:YahooFinanceProvider._build_statements",
        "EBIT := revenue x prior-year EBIT margin"),
    "REVENUE_X_PRIOR_DA_RATIO": AlgorithmSpec(
        "1", "data.providers:YahooFinanceProvider._build_statements",
        "D&A := revenue x prior-year D&A/revenue"),
    "EBIT_PLUS_DA": AlgorithmSpec(
        "1", "data.providers:YahooFinanceProvider._build_statements",
        "EBITDA := EBIT + D&A"),
    "OCF_FROM_FCF_MINUS_CAPEX": AlgorithmSpec(
        "1", "data.providers:YahooFinanceProvider._build_statements",
        "operating_cash_flow := free_cash_flow - capex"),
    "FCF_FROM_OCF_PLUS_CAPEX": AlgorithmSpec(
        "1", "data.providers:YahooFinanceProvider._build_statements",
        "free_cash_flow := operating_cash_flow + capex (capex negative)"),
    # --- base-case defaults used when a prior ratio is unavailable --------
    "PRIOR_MARGIN_FALLBACK": AlgorithmSpec(
        "1", "data.providers:YahooFinanceProvider._build_statements",
        "prior margin taken from the latest annual statement"),
    # --- data.normalizer.fill_derived_fields ------------------------------
    "GROSS_PROFIT_FROM_REVENUE_MINUS_COGS": AlgorithmSpec(
        "1", "data.normalizer:FinancialNormalizer.fill_derived_fields",
        "gross_profit := revenue - cost_of_revenue"),
    "COGS_FROM_REVENUE_MINUS_GROSS_PROFIT": AlgorithmSpec(
        "1", "data.normalizer:FinancialNormalizer.fill_derived_fields",
        "cost_of_revenue := revenue - gross_profit"),
    "EBIT_FROM_OPERATING_INCOME": AlgorithmSpec(
        "1", "data.normalizer:FinancialNormalizer.fill_derived_fields",
        "ebit := operating_income"),
    "REVENUE_X_PRIOR_INTEREST_RATIO": AlgorithmSpec(
        "1", "data.normalizer:FinancialNormalizer.fill_derived_fields",
        "interest_expense := revenue x prior-year interest/revenue"),
    "REVENUE_X_PRIOR_TAX_RATIO": AlgorithmSpec(
        "1", "data.normalizer:FinancialNormalizer.fill_derived_fields",
        "income_tax := revenue x prior-year tax/revenue"),
    "FCF_FROM_OCF_PLUS_CAPEX": AlgorithmSpec(
        "1", "data.normalizer:FinancialNormalizer.fill_derived_fields",
        "free_cash_flow := operating_cash_flow + capex (capex negative)"),
    "EPS_FROM_NI_OVER_SHARES": AlgorithmSpec(
        "1", "data.normalizer:FinancialNormalizer.fill_derived_fields",
        "eps := net_income / shares_outstanding"),
    "NWC_FROM_NOPAT_DA_CAPEX_FCF": AlgorithmSpec(
        "1", "data.nwc_utils:infer_change_in_nwc",
        "change_in_nwc := NOPAT + D&A + capex - FCF"),
    # --- data.normalizer TTM construction --------------------------------
    "TTM_SUM_4Q": AlgorithmSpec(
        "1", "data.normalizer:FinancialNormalizer.compute_ttm_from_quarters",
        "TTM field := sum of the 4 most recent quarters (None-skipping)"),
    "TTM_FROM_LATEST_ANNUAL": AlgorithmSpec(
        "1", "data.normalizer:FinancialNormalizer.ensure_ttm",
        "TTM := latest annual statement, relabelled (not a true TTM)"),
    "TTM_EPS_SUM_4Q": AlgorithmSpec(
        "1", "data.normalizer:_ttm_eps",
        "TTM eps := sum of 4 quarterly eps, else NI / shares"),
}


def available_methods() -> list[str]:
    return sorted(ALGORITHM_VERSIONS)


def version_of(method: Optional[str]) -> Optional[str]:
    """Registry lookup. An unknown method yields ``None`` on purpose: an
    unversioned derivation must be visible, never silently given a version."""
    if not method:
        return None
    spec = ALGORITHM_VERSIONS.get(method)
    return spec.version if spec else None


def _resolve_anchor(anchor: str) -> Callable:
    import importlib

    mod_name, _, attr_path = anchor.partition(":")
    mod = importlib.import_module(mod_name)
    obj = mod
    for part in attr_path.split("."):
        obj = getattr(obj, part)
    return obj


def _module_of(obj: Any) -> Optional[str]:
    return getattr(obj, "__module__", None)


def _collect_dependencies(fn: Callable, *, max_depth: int = 3) -> Dict[str, str]:
    """Map ``"module:qualname" -> canonical AST`` for ``fn`` and what it uses.

    A fingerprint that hashes only the anchor's own body misses the two ways a
    derivation silently changes:

    * it calls a helper whose arithmetic was edited (the caller's AST is
      identical, so the old fingerprint still "matches");
    * it reads a module-level constant or default whose value was changed (the
      expression ``TOLERANCE`` is unchanged, only its binding is).

    So the closure is walked: every function called from the body, and every
    module-level name referenced that resolves to a function or to a scalar
    constant. Depth is bounded to keep a deep call graph from hashing half the
    package, and unresolvable names are skipped rather than failing the audit.
    """
    import importlib

    found: Dict[str, str] = {}
    seen: set = set()

    def visit(func: Callable, depth: int) -> None:
        key = f"{_module_of(func)}:{getattr(func, '__qualname__', func)}"
        if key in seen or depth > max_depth:
            return
        seen.add(key)
        try:
            src = inspect.getsource(func)
        except (OSError, TypeError):  # pragma: no cover - C builtins
            return
        try:
            tree = ast.parse(textwrap.dedent(src))
        except SyntaxError:  # pragma: no cover
            return
        found[key] = ast.dump(tree, annotate_fields=True, include_attributes=False)

        mod = sys.modules.get(_module_of(func) or "")
        if mod is None:
            return

        referenced: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                referenced.add(node.id)
            elif isinstance(node, ast.Attribute):
                # ``self._helper`` / ``cls._helper`` live on the class, not the
                # module; resolve those through the function's own owner.
                referenced.add(node.attr)

        for name in referenced:
            target = getattr(mod, name, None)
            if target is None and "." in key:
                # Method on a class: try the class namespace too.
                owner_path = key.split(":")[-1].rsplit(".", 1)[0]
                if owner_path:
                    try:
                        owner = mod
                        for part in owner_path.split("."):
                            owner = getattr(owner, part)
                        target = getattr(owner, name, None)
                    except AttributeError:
                        target = None
            if target is None:
                continue
            if inspect.isfunction(target) or inspect.ismethod(target):
                visit(target, depth + 1)
            elif isinstance(target, (int, float, str, bool, tuple, frozenset)):
                # A constant's *value* is part of the semantics; record it so a
                # changed threshold moves the fingerprint.
                found[f"const:{_module_of(func)}:{name}"] = repr(target)

    visit(fn, 0)
    return dict(sorted(found.items()))


def dependency_fingerprint(method: str) -> Dict[str, Any]:
    """Closure fingerprint: the anchor plus everything it transitively uses.

    The method's own name and documented formula are mixed in. Several methods
    share one anchor (``_build_statements`` implements five of them), so hashing
    the closure alone gave all five the *same* digest -- which means editing one
    derivation could not be attributed to it. Including the identity keeps the
    digest specific to the derivation, while the closure part still catches
    helper and constant edits.
    """
    spec = ALGORITHM_VERSIONS[method]
    try:
        anchor = _resolve_anchor(spec.anchor)
    except (AttributeError, ImportError):  # pragma: no cover
        return {"fingerprint": "unavailable", "dependencies": [],
                "dependency_count": 0}
    deps = _collect_dependencies(anchor)
    deps["@method"] = method
    deps["@formula"] = spec.description
    payload = json.dumps(deps, sort_keys=True).encode()
    return {
        "fingerprint": hashlib.sha256(payload).hexdigest()[:16],
        "dependencies": sorted(k for k in deps if not k.startswith("@")),
        "dependency_count": len(deps) - 2,
    }


def source_fingerprint(method: str) -> str:
    """SHA-256 of the implementation's *semantics*, via its AST.

    Using the parsed tree rather than the raw text means comments, blank lines
    and re-indentation do not raise a false alarm, while any change to an
    expression, constant, branch or call does. That is the distinction the
    version rule cares about: behaviour, not formatting.

    This hashes the anchor alone; :func:`dependency_fingerprint` covers the
    helpers and constants the anchor depends on.
    """
    spec = ALGORITHM_VERSIONS[method]
    try:
        src = inspect.getsource(_resolve_anchor(spec.anchor))
    except (OSError, TypeError, AttributeError):  # pragma: no cover
        return "unavailable"
    try:
        tree = ast.parse(textwrap.dedent(src))
    except SyntaxError:  # pragma: no cover
        return "unparsable"
    # ``ast.dump`` without attributes leaves positions out, which is exactly the
    # normalisation wanted: two spellings of the same code hash the same.
    canonical = ast.dump(tree, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def fingerprint_table() -> Dict[str, Dict[str, Any]]:
    table: Dict[str, Dict[str, Any]] = {}
    for method, spec in ALGORITHM_VERSIONS.items():
        dep = dependency_fingerprint(method)
        table[method] = {
            "version": spec.version,
            "fingerprint": source_fingerprint(method),
            "dependency_fingerprint": dep["fingerprint"],
            "dependency_count": dep.get("dependency_count", 0),
        }
    return table


def load_baseline() -> Dict[str, Dict[str, str]]:
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text())


def write_baseline() -> None:
    BASELINE_PATH.write_text(json.dumps(fingerprint_table(), indent=2, sort_keys=True) + "\n")


def baseline_mismatches() -> Dict[str, str]:
    """Return method -> explanation for every drift between code and baseline.

    Empty means "the algorithms are exactly the versions we recorded". A version
    bump without a baseline refresh, or an edit without a bump, both show up.
    """
    baseline = load_baseline()
    current = fingerprint_table()
    problems: Dict[str, str] = {}
    for method, cur in current.items():
        rec = baseline.get(method)
        if rec is None:
            problems[method] = "not in baseline (new or unregistered)"
            continue
        if rec["version"] != cur["version"]:
            problems[method] = (f"version changed {rec['version']} -> {cur['version']}"
                                " without baseline refresh")
        elif rec["fingerprint"] != cur["fingerprint"]:
            problems[method] = ("implementation changed without a version bump"
                                f" ({rec['fingerprint']} -> {cur['fingerprint']})")
    for method in baseline:
        if method not in current:
            problems[method] = "recorded in baseline but no longer registered"
    return problems


if __name__ == "__main__":  # pragma: no cover
    import sys

    if "--write-baseline" in sys.argv:
        write_baseline()
        print(f"wrote {BASELINE_PATH}")
    else:
        drift = baseline_mismatches()
        for method, why in sorted(drift.items()):
            print(f"{method}: {why}")
        print(f"{len(drift)} mismatch(es)")
