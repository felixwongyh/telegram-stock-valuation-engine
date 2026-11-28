"""Per-field data provenance: where a number came from, and how much to trust it.

Implements the schema in ``docs/audit/data_provenance_design.md`` (U-2b). Two
independent axes, as ruled:

* origin -- *where* a value came from (``REPORTED`` … ``IMPUTED`` …)
* availability -- *whether* a usable value exists (``AVAILABLE`` … ``INVALID``)

They stay separate on purpose: ``MISSING`` answers "is there a number",
``IMPUTED`` answers "where did it come from", and collapsing them into one enum
forces a value to surrender one of the two facts.

The origin axis is ordered by how much the number can be trusted, and consumers
gate on that order -- see :class:`ProvenanceTier` and :func:`gate_field`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class DataOriginType(str, Enum):
    """Where a value came from. ``str`` mixin is mandatory: the cache serializer
    handles ``str`` before ``Enum``, so a plain ``Enum`` would be written as
    ``null`` (design §7.1).

    ``REPORTED`` is retained for backward compatibility with records written
    before the two-source split, and for statements whose origin is genuinely
    "reported by *someone*" without a located filing. New writers should prefer
    the more specific level:

    * ``COMPANY_REPORTED`` -- the number was matched to a filing the company
      submitted (SEC XBRL fact with an accession number and filing date).
    * ``VENDOR_REPORTED`` -- the number came from the vendor's normalised
      statement and *no* filing was located to corroborate it. This is *not*
      the same claim as ``COMPANY_REPORTED``: a vendor restates, reclassifies and
      rounds, so "Yahoo says so" is a weaker statement than "the 10-K says so".

    Collapsing the two is the specific laundering this schema exists to prevent:
    a normalised vendor figure must never be presented as a company disclosure
    merely because it is labelled "reported".
    """

    COMPANY_REPORTED = "company_reported"
    VENDOR_REPORTED = "vendor_reported"
    REPORTED = "reported"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    IMPUTED = "imputed"
    UNKNOWN_LEGACY = "unknown_legacy"


class DataAvailability(str, Enum):
    """Whether a usable value exists. Independent of :class:`DataOriginType`."""

    AVAILABLE = "available"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    INVALID = "invalid"


class ProvenanceTier(int, Enum):
    """Trust ordering used for gating. Lower is more trustworthy.

    ``UNKNOWN_LEGACY`` sits at the *bottom*, not the top: a number whose origin
    nobody recorded must never outrank one the company actually filed. Tiering it
    as trusted-by-default is how unknown data gets laundered into fact.

    ``COMPANY_REPORTED`` outranks ``VENDOR_REPORTED`` because a located filing is
    stronger evidence than a vendor restatement. ``REPORTED`` (the legacy label
    with no source split) sits between the two: it is a real vendor-reported
    signal, but it makes no claim of filing corroboration.
    """

    COMPANY_REPORTED = 0
    REPORTED = 1
    VENDOR_REPORTED = 2
    DERIVED = 3
    ESTIMATED = 4
    IMPUTED = 5
    UNKNOWN_LEGACY = 6


_TIER_BY_ORIGIN = {
    DataOriginType.COMPANY_REPORTED: ProvenanceTier.COMPANY_REPORTED,
    DataOriginType.REPORTED: ProvenanceTier.REPORTED,
    DataOriginType.VENDOR_REPORTED: ProvenanceTier.VENDOR_REPORTED,
    DataOriginType.DERIVED: ProvenanceTier.DERIVED,
    DataOriginType.ESTIMATED: ProvenanceTier.ESTIMATED,
    DataOriginType.IMPUTED: ProvenanceTier.IMPUTED,
    DataOriginType.UNKNOWN_LEGACY: ProvenanceTier.UNKNOWN_LEGACY,
}


def _coerce_origin(value: Any) -> Optional[DataOriginType]:
    """Accept an enum, a bare string from a JSON round trip, or ``None``.

    The cache turns ``DataOriginType.REPORTED`` into the plain string
    ``"reported"`` (design §7.3). Coercing on the way in means a deserialized
    object behaves identically to a fresh one, instead of raising
    ``AttributeError: 'str' object has no attribute 'value'`` at the first
    ``.value`` access.
    """
    if value is None or isinstance(value, DataOriginType):
        return value
    try:
        return DataOriginType(str(value))
    except ValueError:
        return DataOriginType.UNKNOWN_LEGACY


def _coerce_availability(value: Any) -> DataAvailability:
    if isinstance(value, DataAvailability):
        return value
    try:
        return DataAvailability(str(value))
    except ValueError:
        return DataAvailability.MISSING


@dataclass
class FieldProvenance:
    """Origin and availability of one numeric field, plus an audit record.

    ``origin_type`` is optional because a ``NOT_APPLICABLE`` field has no number
    whose origin could be described -- forcing one would be a lie (design §2).

    The audit fields (``algorithm_version`` .. ``output_value``) exist so a
    derived number can be *recomputed* and *attributed*, not merely labelled:

    * ``source_fields`` -- the concrete field names that were read (distinct from
      ``input_fields``, which names the derivation's parameters when the inputs
      are not themselves statement fields, e.g. a prior-year ratio)
    * ``algorithm_version`` -- registry version, see ``data.algorithm_versions``
    * ``input_hash`` -- digest of the input *values*, so "same inputs" is
      checkable without storing every number twice
    * ``output_value`` -- what the derivation produced, so a later value that
      differs can be proven to have drifted rather than guessed at
    * ``generated_at`` -- when this record was written (UTC ISO-8601)
    """

    availability: DataAvailability = DataAvailability.MISSING
    origin_type: Optional[DataOriginType] = None
    source_provider: Optional[str] = None
    source_field: Optional[str] = None
    source_period: Optional[str] = None
    snapshot_id: Optional[str] = None
    derivation_method: Optional[str] = None
    input_fields: List[str] = field(default_factory=list)

    # ---- audit record (Phase 1) -------------------------------------------
    source_fields: List[str] = field(default_factory=list)
    algorithm_version: Optional[str] = None
    input_hash: Optional[str] = None
    output_value: Optional[float] = None
    generated_at: Optional[str] = None

    def __post_init__(self) -> None:
        self.availability = _coerce_availability(self.availability)
        self.origin_type = _coerce_origin(self.origin_type)
        if self.input_fields is None:
            self.input_fields = []
        if self.source_fields is None:
            self.source_fields = []
        if self.algorithm_version is None and self.derivation_method:
            # Fill from the registry, but never invent a version for an
            # unregistered method -- that would hide an unversioned derivation.
            from data.algorithm_versions import version_of

            self.algorithm_version = version_of(self.derivation_method)

    @property
    def tier(self) -> ProvenanceTier:
        if self.origin_type is None:
            return ProvenanceTier.UNKNOWN_LEGACY
        return _TIER_BY_ORIGIN.get(self.origin_type, ProvenanceTier.UNKNOWN_LEGACY)

    @property
    def is_derived(self) -> bool:
        """True for the three inferred origins. ``UNKNOWN_LEGACY`` is *not*
        derived: it may be a reported number whose record was lost."""
        return self.origin_type in (
            DataOriginType.DERIVED,
            DataOriginType.ESTIMATED,
            DataOriginType.IMPUTED,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "availability": self.availability.value,
            "origin_type": self.origin_type.value if self.origin_type else None,
            "source_provider": self.source_provider,
            "source_field": self.source_field,
            "source_period": self.source_period,
            "snapshot_id": self.snapshot_id,
            "derivation_method": self.derivation_method,
            "input_fields": list(self.input_fields),
            "source_fields": list(self.source_fields),
            "algorithm_version": self.algorithm_version,
            "input_hash": self.input_hash,
            "output_value": self.output_value,
            "generated_at": self.generated_at,
        }


class GateAction(str, Enum):
    """What a consumer should do with a field, given its provenance tier."""

    ALLOW = "allow"                    # use as-is
    ALLOW_WITH_FLAG = "allow_with_flag"  # use, but record that it is inferred
    DOWNWEIGHT = "downweight"          # usable, but must not drive a headline
    REFUSE = "refuse"                  # no usable value


@dataclass
class GateDecision:
    action: GateAction
    tier: ProvenanceTier
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action is not GateAction.REFUSE


#: Tier -> (action, human reason) for a *core valuation model* consuming the
#: field. Advisory for the middle tiers, hard stop only when there is no value.
_CORE_MODEL_GATE = {
    ProvenanceTier.REPORTED: (GateAction.ALLOW, "reported by the filer"),
    ProvenanceTier.DERIVED: (
        GateAction.ALLOW, "derived deterministically from reported inputs"),
    ProvenanceTier.ESTIMATED: (
        GateAction.ALLOW_WITH_FLAG, "estimated from a ratio or history"),
    ProvenanceTier.IMPUTED: (
        GateAction.ALLOW_WITH_FLAG,
        "imputed from a model or prior margin -- not disclosed by the company"),
    ProvenanceTier.UNKNOWN_LEGACY: (
        GateAction.ALLOW_WITH_FLAG, "origin not recorded (legacy data)"),
}

#: A classification feature is a derived signal, not a headline number, so an
#: imputed input degrades the confidence rather than blocking the feature.
_CLASSIFICATION_GATE = {
    ProvenanceTier.REPORTED: (GateAction.ALLOW, "reported"),
    ProvenanceTier.DERIVED: (GateAction.ALLOW, "derived from reported inputs"),
    ProvenanceTier.ESTIMATED: (
        GateAction.DOWNWEIGHT, "estimated input -- down-weight the feature"),
    ProvenanceTier.IMPUTED: (
        GateAction.DOWNWEIGHT, "imputed input -- down-weight the feature"),
    ProvenanceTier.UNKNOWN_LEGACY: (
        GateAction.DOWNWEIGHT, "unknown origin -- down-weight the feature"),
}


def _decision(table, prov: Optional[FieldProvenance], field_name: str) -> GateDecision:
    if prov is None:
        return GateDecision(
            action=GateAction.ALLOW_WITH_FLAG,
            tier=ProvenanceTier.UNKNOWN_LEGACY,
            reason=f"{field_name}: no provenance recorded (treated as legacy)",
        )
    if prov.availability is not DataAvailability.AVAILABLE:
        return GateDecision(
            action=GateAction.REFUSE,
            tier=prov.tier,
            reason=f"{field_name}: {prov.availability.value}",
        )
    action, reason = table[prov.tier]
    return GateDecision(action=action, tier=prov.tier, reason=f"{field_name}: {reason}")


def gate_field(stmt: Any, field_name: str,
               consumer: str = "core_model") -> GateDecision:
    """Decide how a consumer may use ``field_name`` on ``stmt``.

    ``consumer`` is ``"core_model"`` (DCF/RIM/DDM) or ``"classification"``.
    Provenance lives on the sidecar so the numeric attribute keeps its plain
    ``float | None`` contract for the ~74 existing read sites.
    """
    prov_map = getattr(stmt, "field_provenance", None) or {}
    prov = prov_map.get(field_name)
    table = _CLASSIFICATION_GATE if consumer == "classification" else _CORE_MODEL_GATE
    return _decision(table, prov, field_name)


def compute_input_hash(inputs: Dict[str, Any]) -> str:
    """Stable digest of the input *values* feeding a derivation.

    Key order is normalised and floats are rounded to 12 significant digits, so
    the hash identifies the arithmetic inputs rather than the float noise of a
    different code path. Two runs with the same numbers produce the same hash;
    any input that changes enough to change the 12th digit does not match.
    """
    def _norm(v: Any) -> Any:
        if isinstance(v, float):
            return float(f"{v:.12g}")
        if isinstance(v, dict):
            return {str(k): _norm(val) for k, val in sorted(v.items())}
        if isinstance(v, (list, tuple)):
            return [_norm(x) for x in v]
        return v

    payload = json.dumps(_norm(inputs), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp(stmt: Any, field_name: str, origin_type: DataOriginType,
          *, derivation_method: Optional[str] = None,
          input_fields: Optional[List[str]] = None,
          source_provider: Optional[str] = None,
          source_field_name: Optional[str] = None,
          availability: DataAvailability = DataAvailability.AVAILABLE,
          snapshot_id: Optional[str] = None,
          source_fields: Optional[List[str]] = None,
          input_values: Optional[Dict[str, Any]] = None,
          algorithm_version: Optional[str] = None) -> None:
    """Record provenance for one field on one statement.

    Every writer goes through here rather than appending to the dict directly,
    so the two axes cannot be set inconsistently by accident.

    For an inferred value the caller passes ``input_values`` (the numbers the
    derivation actually read); ``input_hash`` and ``output_value`` are then
    filled in here, so no writer can forget them. ``output_value`` is read from
    ``stmt`` *after* the value was assigned, which is why callers must stamp
    after setting the attribute.
    """
    prov_map = getattr(stmt, "field_provenance", None)
    if prov_map is None:
        prov_map = {}
        stmt.field_provenance = prov_map

    value = getattr(stmt, field_name, None)
    prov_map[field_name] = FieldProvenance(
        availability=availability,
        origin_type=origin_type,
        source_provider=source_provider,
        source_field=source_field_name,
        derivation_method=derivation_method,
        input_fields=list(input_fields or []),
        snapshot_id=snapshot_id,
        source_fields=list(source_fields or []),
        algorithm_version=algorithm_version,
        input_hash=(compute_input_hash(input_values)
                    if input_values is not None else None),
        output_value=(float(value) if isinstance(value, (int, float)) else None),
        generated_at=_utc_now_iso(),
    )


# --------------------------------------------------------------- audit tools

def audit_records(stmt: Any) -> List[Dict[str, Any]]:
    """Flat audit rows for every stamped field on one statement.

    The columns are the ones the Phase 1 brief names, in that order, so the
    output can be diffed between runs without a translation step.
    """
    rows: List[Dict[str, Any]] = []
    for name, prov in sorted((getattr(stmt, "field_provenance", None) or {}).items()):
        value = getattr(stmt, name, None)
        rows.append({
            "field_name": name,
            "origin_type": prov.origin_type.value if prov.origin_type else None,
            "availability": prov.availability.value,
            "source_fields": list(prov.source_fields),
            "derivation_method": prov.derivation_method,
            "algorithm_version": prov.algorithm_version,
            "input_hash": prov.input_hash,
            "output_value": prov.output_value,
            "value_now": float(value) if isinstance(value, (int, float)) else None,
            "generated_at": prov.generated_at,
        })
    return rows


def drifted_fields(stmt: Any, *, tolerance: float = 0.0) -> List[Dict[str, Any]]:
    """Fields whose current value no longer matches its recorded ``output_value``.

    This is the "input changed, identify the blast radius" check: if a
    derivation was stamped and the number later moved without a new stamp, the
    provenance record and the statement disagree, and that is exactly the state
    in which an unexplained value reaches a valuation.
    """
    out = []
    for name, prov in (getattr(stmt, "field_provenance", None) or {}).items():
        if prov.output_value is None:
            continue
        value = getattr(stmt, name, None)
        if not isinstance(value, (int, float)):
            out.append({"field_name": name, "recorded": prov.output_value,
                        "current": None, "reason": "value disappeared"})
            continue
        if abs(float(value) - float(prov.output_value)) > tolerance:
            out.append({"field_name": name, "recorded": prov.output_value,
                        "current": float(value), "reason": "value differs"})
    return out


class ProvenanceError(RuntimeError):
    """Raised when a provenance rule is violated at write time."""


#: Origins that assert "this number was reported by a source outside our
#: pipeline". Any of them is an *upgrade* from an inferred or unknown origin.
_REPORTED_LEVELS = (
    DataOriginType.COMPANY_REPORTED,
    DataOriginType.REPORTED,
    DataOriginType.VENDOR_REPORTED,
)

#: Origins that must never be silently promoted into a level above.
_INFERRED_LEVELS = (
    DataOriginType.DERIVED,
    DataOriginType.ESTIMATED,
    DataOriginType.IMPUTED,
    DataOriginType.UNKNOWN_LEGACY,
)

_FORBIDDEN_UPGRADES = {
    # (from, to) pairs that must never happen automatically.
    #
    # Built as a product rather than listed by hand: the previous hand-written
    # list named only ``REPORTED`` as a target, so adding ``COMPANY_REPORTED``
    # and ``VENDOR_REPORTED`` would have left six silent holes. A rule about
    # "no laundering" must not depend on remembering to extend a table.
    (old, new)
    for old in _INFERRED_LEVELS
    for new in _REPORTED_LEVELS
} | {
    # An inferred value may not be relabelled as computed from other fields
    # either: ``derived`` asserts a specific audited derivation, so promotion
    # into it without that derivation is equally a fabrication.
    (DataOriginType.UNKNOWN_LEGACY, DataOriginType.DERIVED),
    (DataOriginType.ESTIMATED, DataOriginType.DERIVED),
    (DataOriginType.IMPUTED, DataOriginType.DERIVED),
    # A vendor's normalised figure is weaker evidence than a located filing, so
    # it may not be silently upgraded to ``COMPANY_REPORTED`` without a match.
    (DataOriginType.VENDOR_REPORTED, DataOriginType.COMPANY_REPORTED),
    (DataOriginType.REPORTED, DataOriginType.COMPANY_REPORTED),
}


def is_forbidden_upgrade(old: Any, new: Any) -> bool:
    """Rule 4/5 guard: an inferred or unknown origin may not become reported.

    A real correction is allowed only by introducing a fresh, explicitly
    sourced value -- never by relabelling an existing one, which is how unknown
    data gets laundered into fact.
    """
    old_o = old.origin_type if isinstance(old, FieldProvenance) else old
    new_o = new.origin_type if isinstance(new, FieldProvenance) else new
    return (old_o, new_o) in _FORBIDDEN_UPGRADES


def assert_no_forbidden_upgrade(old: Any, new: Any, field_name: str = "",
                               *, evidence: Optional[Dict[str, Any]] = None) -> None:
    """Refuse a silent promotion, unless fresh evidence is supplied.

    The distinction the guard must respect: relabelling an *existing* record is
    laundering; *re-sourcing* a field from a newly fetched, hash-recorded
    response is legitimate scholarship. A shadow snapshot does the latter, so it
    passes ``evidence`` naming what was retrieved.

    ``evidence`` must carry a raw-response digest -- an origin claim with no
    retrievable artefact behind it is exactly what this function exists to stop.
    """
    if not is_forbidden_upgrade(old, new):
        return
    old_o = old.origin_type if isinstance(old, FieldProvenance) else old
    new_o = new.origin_type if isinstance(new, FieldProvenance) else new
    if evidence and evidence.get("raw_sha256"):
        return
    raise ProvenanceError(
        f"{field_name}: illegal origin upgrade "
        f"{old_o.value if old_o else None} -> {new_o.value if new_o else None}; "
        "an inferred/unknown value may not be relabelled as reported without "
        "retrieved evidence (pass evidence={'raw_sha256': ...} when re-sourcing)"
    )


def coverage_summary(data: Any) -> Dict[str, Any]:
    """Count origins across every statement of a ``FinancialData``.

    Used by the golden-readiness report: "how much of what we value is actually
    filed by the company" is a percentage, not an impression.
    """
    counts: Dict[str, int] = {}
    derived_missing_audit: List[str] = []
    for idx, stmt in enumerate([data.ttm, *data.annual_income, *data.quarterly_income]):
        if stmt is None:
            continue
        for name, prov in (getattr(stmt, "field_provenance", None) or {}).items():
            key = prov.origin_type.value if prov.origin_type else "none"
            counts[key] = counts.get(key, 0) + 1
            if prov.is_derived and not (prov.algorithm_version and prov.input_hash):
                derived_missing_audit.append(f"stmt[{idx}].{name}")
    total = sum(counts.values())
    return {
        "total_fields": total,
        "by_origin": dict(sorted(counts.items())),
        "reported_share": (counts.get("reported", 0) / total) if total else 0.0,
        "derived_without_audit": derived_missing_audit,
    }
