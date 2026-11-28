"""benchmark/reconcile.py -- explain every material change between the frozen
golden baseline and a shadow snapshot.

The rule this module enforces
-----------------------------
A comparison that only prints "old 214.26, new 198.10" is useless: it cannot
distinguish a real data change from a restated vendor figure from an algorithm
edit. So every row carries *why*:

* ``source_changed``    -- the underlying source/provenance is different
* ``algorithm_changed`` -- the derivation version behind a value is different
* ``reason``            -- a sentence naming which of those applies

Two layers are compared, because either alone is misleading:

* **data layer**     -- the statement fields a valuation consumes
* **valuation layer** -- WACC, DCF value, reverse-DCF output, solved status

A shadow that changes the data but not the valuation (or vice versa) must say so,
rather than being reported as "no change".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import get_logger

log = get_logger("benchmark.reconcile")

#: Statement fields the task requires, in report order.
DATA_FIELDS: Tuple[str, ...] = (
    "revenue", "ebitda", "ebit", "net_income", "cash", "total_debt",
    "stockholders_equity", "shares_outstanding", "free_cash_flow",
)

#: Valuation-layer metrics: (label, shadow-path, golden-path).
VALUATION_METRICS: Tuple[Tuple[str, Tuple[str, ...], Optional[str]], ...] = (
    ("WACC", ("dcf_wacc",), "beta_effective"),
    ("DCF Value/Share", ("dcf_value_per_share",), "median_value"),
    ("DCF Enterprise Value", ("dcf_enterprise_value",), None),
    ("Reverse DCF Status", ("rd_status",), None),
    ("Reverse DCF Value/Share", ("rd_value_per_share",), None),
    ("Reverse DCF Implied CAGR", ("rd_implied_revenue_cagr",), None),
    ("Solved Status", ("rd_status",), None),
)

#: Relative delta above which a difference is called material. Below this a
#: vendor's rounding is indistinguishable from a real change, and claiming one
#: would be noise dressed as signal.
MATERIALITY = 0.005


@dataclass
class FieldDelta:
    metric: str
    layer: str                  # "data" | "valuation"
    old_value: Optional[float] = None
    new_value: Optional[float] = None
    old_provenance: Optional[str] = None
    new_provenance: Optional[str] = None
    absolute_delta: Optional[float] = None
    percentage_delta: Optional[float] = None
    reason: str = ""
    source_changed: bool = False
    algorithm_changed: bool = False
    material: bool = False
    period_gap_days: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "layer": self.layer,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "old_provenance": self.old_provenance,
            "new_provenance": self.new_provenance,
            "absolute_delta": self.absolute_delta,
            "percentage_delta": self.percentage_delta,
            "reason": self.reason,
            "source_changed": self.source_changed,
            "algorithm_changed": self.algorithm_changed,
            "material": self.material,
            "period_gap_days": self.period_gap_days,
        }


def _pct(old: Optional[float], new: Optional[float]) -> Optional[float]:
    if old is None or new is None:
        return None
    if old == 0:
        return None if new == 0 else float("inf")
    return (new - old) / abs(old)


def _diff(
    metric: str, layer: str,
    old_value: Optional[float], new_value: Optional[float],
    old_prov: Optional[str], new_prov: Optional[str],
    *,
    old_algo: Optional[str] = None, new_algo: Optional[str] = None,
    period_gap_days: Optional[int] = None,
) -> FieldDelta:
    d = FieldDelta(
        metric=metric, layer=layer,
        old_value=old_value, new_value=new_value,
        old_provenance=old_prov, new_provenance=new_prov,
        period_gap_days=period_gap_days,
    )
    if old_value is not None and new_value is not None:
        d.absolute_delta = new_value - old_value
        d.percentage_delta = _pct(old_value, new_value)

    d.source_changed = (old_prov != new_prov)
    d.algorithm_changed = bool(
        old_algo and new_algo and old_algo != new_algo
    ) or bool(old_algo and not new_algo) or bool(new_algo and not old_algo)

    material_value = (d.percentage_delta is not None
                      and abs(d.percentage_delta) > MATERIALITY)

    # Reason: name the *first* applicable cause, most specific first. A row with
    # a delta but no named cause is what makes a reconciliation report unreadable.
    if old_value is None and new_value is None:
        d.reason = "absent in both"
    elif old_value is None:
        d.reason = f"newly available ({new_prov or 'unknown origin'})"
        d.material = True
    elif new_value is None:
        d.reason = f"lost ({old_prov or 'unknown origin'} -> absent)"
        d.material = True
    elif d.algorithm_changed:
        d.reason = f"algorithm changed ({old_algo} -> {new_algo})"
        d.material = True
    elif not material_value:
        d.reason = "within materiality tolerance"
        d.material = False
    elif d.source_changed:
        d.reason = (f"source changed ({old_prov} -> {new_prov}) and value moved "
                    f"{d.percentage_delta:+.2%}")
        d.material = True
    else:
        d.reason = (f"same source, value moved {d.percentage_delta:+.2%} "
                    "-- investigate (restatement or period shift)")
        d.material = True

    if period_gap_days:
        d.reason += f"; fiscal-period label gap {period_gap_days}d"
    return d


def reconcile_data(
    golden: Dict[str, Any], shadow: Dict[str, Any],
) -> List[FieldDelta]:
    """Compare statement-level fields.

    ``golden`` and ``shadow`` are ``{field: value}`` plus a parallel
    ``{field: provenance}`` mapping under key ``_provenance``.
    """
    rows: List[FieldDelta] = []
    g_prov = golden.get("_provenance") or {}
    s_prov = shadow.get("_provenance") or {}
    for name in DATA_FIELDS:
        gp = g_prov.get(name) or {}
        sp = s_prov.get(name) or {}
        rows.append(_diff(
            name, "data",
            golden.get(name), shadow.get(name),
            gp.get("origin_type"), sp.get("origin_type"),
            old_algo=gp.get("algorithm_version"),
            new_algo=sp.get("algorithm_version"),
            period_gap_days=sp.get("sec_period_gap_days") or sp.get("period_gap_days"),
        ))
    return rows


def reconcile_valuation(
    golden: Dict[str, Any], shadow: Dict[str, Any],
) -> List[FieldDelta]:
    """Compare valuation outputs and their drivers."""
    rows: List[FieldDelta] = []
    for label, path, golden_key in VALUATION_METRICS:
        new_val: Any = shadow
        for p in path:
            new_val = (new_val or {}).get(p) if isinstance(new_val, dict) else None
        old_val = golden.get(golden_key) if golden_key else None

        # Non-numeric status strings still need comparison, and turning them into
        # a delta would be meaningless. Compare them as categories.
        if isinstance(new_val, str) or isinstance(old_val, str):
            same = new_val == old_val
            rows.append(FieldDelta(
                metric=label, layer="valuation",
                old_provenance=str(old_val) if old_val is not None else None,
                new_provenance=str(new_val) if new_val is not None else None,
                reason="unchanged" if same else f"status changed: {old_val} -> {new_val}",
                material=not same,
            ))
            continue

        rows.append(_diff(
            label, "valuation",
            old_val if isinstance(old_val, (int, float)) else None,
            new_val if isinstance(new_val, (int, float)) else None,
            golden.get("beta_origin") or "golden_fingerprint",
            "shadow_pipeline",
        ))
    return rows


def load_golden(path: Path) -> Dict[str, Dict[str, Any]]:
    return json.loads(path.read_text())


def load_shadow(snapshot_id: str, ticker: str,
                root: Optional[Path] = None, *, view: str = "ttm") -> Dict[str, Any]:
    """Load a shadow for comparison.

    ``view`` selects the cadence. ``"ttm"`` is the default because the frozen
    golden is a TTM statement; comparing an annual shadow against it would
    report a period shift as a data change.
    """
    base = root or (Path(__file__).resolve().parent.parent
                    / "data" / "shadow_snapshots")
    d = base / snapshot_id / ticker
    if view == "ttm":
        stmt_path = d / "ttm_statement.json"
        prov_path = d / "ttm_provenance.json"
    else:
        stmt_path = d / "statement.json"
        prov_path = d / "provenance.json"
    if not stmt_path.exists():
        return {}
    stmt = json.loads(stmt_path.read_text())
    prov = json.loads(prov_path.read_text()) if prov_path.exists() else {}
    out: Dict[str, Any] = dict(stmt.get("fields") or {})
    out["_provenance"] = prov
    out["_period_end"] = stmt.get("period_end")
    out["_view"] = view
    return out


def summary(rows: List[FieldDelta]) -> Dict[str, Any]:
    return {
        "total_rows": len(rows),
        "material": sum(1 for r in rows if r.material),
        "source_changed": sum(1 for r in rows if r.source_changed),
        "algorithm_changed": sum(1 for r in rows if r.algorithm_changed),
        "data_layer": sum(1 for r in rows if r.layer == "data"),
        "valuation_layer": sum(1 for r in rows if r.layer == "valuation"),
    }
