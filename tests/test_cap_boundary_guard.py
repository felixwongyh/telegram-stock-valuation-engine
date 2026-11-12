"""Static audit for the ADR-023 bug class.

The bug (Recursion SOFI round3): a value is capped by ``min(x, C)`` upstream
while a downstream guard tests it with a *strict* inequality against ``C``.
Values that land exactly on the cap ``C`` then slip through the guard. The fix
is a *closed* interval (``<=`` / ``>=``).

This module turns "audit every min/max cap against its guard" into an
assertable test:

  * ``test_registered_guards_use_closed_interval`` — for each constant known to
    be a guard whose upstream cap can land exactly on it, asserts the source
    uses a closed comparison and never a strict one.

  * ``test_new_cap_literal_pairs_are_reviewed`` — auto-discovers numeric
    literals that appear BOTH inside a ``min()``/``max()`` cap AND in a strict
    comparison somewhere in the source. Any *new* such pair fails the test so a
    human reviews it (add the fix, or allowlist it with a reason). This is the
    "systematic scan" the recursion called for.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [
    "analysis", "classification", "data", "forecasts",
    "models", "reporting", "valuation",
]

# ---------------------------------------------------------------------------
# Part A — guard constants whose upstream cap can land exactly on the constant.
# Each MUST be compared with a closed interval. Key: constant name.
# ---------------------------------------------------------------------------
GUARDED_CONSTANTS: dict[str, str] = {
    # models/multiples.py: classifier caps confidence to *exactly* 0.55 when
    # sector/industry is missing, so the peer-multiple guard must use `<=`.
    "_PEER_MULTIPLE_CONF_FLOOR": "models/multiples.py",
}

# ---------------------------------------------------------------------------
# Part B — numeric literals that legitimately appear in both a min()/max() cap
# and a strict comparison *inside the same file*, but on unrelated variables.
# Add the literal with a one-line reason after review.
# ---------------------------------------------------------------------------
REVIEWED_CAP_LITERAL_PAIRS: dict[str, str] = {
    "0.50": (
        "classification/classifier.py: cap is min(confidence, 0.50) (line 542); the strict "
        "`capex_ratio < 0.50` (line 871) is a different variable — unrelated, not ADR-023."
    ),
    "0.55": (
        "classification/classifier.py: cap is min(confidence, 0.55) (line 509); the strict "
        "`top1_p < 0.55` (line 606) is a different variable (softmax top-1 prob). The actual "
        "confidence-cap guard is cross-file and is asserted by "
        "test_confidence_cap_guards_use_closed_interval."
    ),
    "1.0": (
        "classification/ml_classifier.py: 1.0 is a feature-clip bound max(-0.5, min(1.0, x)) "
        "for margins/ratios; the strict `de < 1.0` / `beta2 < 1.0` (lines 1286/1346) test a "
        "different variable — unrelated, not ADR-023."
    ),
}

# ---------------------------------------------------------------------------
# Part C — cross-file ADR-023: classification/classifier.py caps
# classification_confidence to these *exact* values. Any consumer that treats a
# confidence threshold as "low confidence" must use a closed interval, or the
# capped value slips through. This is the cross-file case the file-local
# literal scan cannot see (e.g. classifier.py caps, models/sotp.py guards).
# ---------------------------------------------------------------------------
CONFIDENCE_CAP_VALUES: frozenset = frozenset({"0.40", "0.50", "0.55"})

_CONF_STRICT_RE = re.compile(
    r"\b(?:conf|confidence|classification_confidence)\b\s*(<|>)(?!=)\s*(\d+\.\d+)\b"
)

_CAP_CALL_RE = re.compile(r"\b(?:min|max)\s*\(([^()]*)\)")
_NUM_RE = re.compile(r"(?<![\w.])(\d+\.\d+)(?![\w.])")
_STRICT_RE = re.compile(r"(?<![<>=!])(?:<|>)(?!=)\s*(\d+\.\d+)")


def _iter_source_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            yield p


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _cap_literals(text: str) -> set[str]:
    """Numeric literals used as an argument of a min()/max() cap call."""
    out: set[str] = set()
    for args in _CAP_CALL_RE.findall(text):
        out.update(_NUM_RE.findall(args))
    return out


def _strict_compare_literals(text: str) -> set[str]:
    """Numeric literals compared with a strict `<` / `>` (not `<=` / `>=`)."""
    return set(_STRICT_RE.findall(text))


def _discover_cap_literal_pairs() -> dict[str, list[str]]:
    """Literal -> [files where it is BOTH a min/max cap and a strict compare]."""
    pairs: dict[str, list[str]] = {}
    for p in _iter_source_files():
        text = _read(p)
        both = _cap_literals(text) & _strict_compare_literals(text)
        for lit in both:
            pairs.setdefault(lit, []).append(str(p.relative_to(ROOT)).replace("\\", "/"))
    return pairs


def test_registered_guards_use_closed_interval():
    """Every GUARDED_CONSTANTS entry must be compared with a closed interval."""
    problems: list[str] = []
    for name, rel in GUARDED_CONSTANTS.items():
        p = ROOT / rel
        assert p.is_file(), f"registered guard file missing: {rel}"
        text = _read(p)
        closed = (
            re.search(rf"(?:<=|>=)\s*{re.escape(name)}\b", text)
            or re.search(rf"\b{re.escape(name)}\s*(?:<=|>=)", text)
        )
        strict = (
            re.search(rf"(?<![<>=!])<\s*{re.escape(name)}\b", text)
            or re.search(rf"(?<![<>=!])>\s*{re.escape(name)}\b", text)
            or re.search(rf"\b{re.escape(name)}\s*(?<![<>=!])<(?!=)", text)
            or re.search(rf"\b{re.escape(name)}\s*(?<![<>=!])>(?!=)", text)
        )
        if not closed:
            problems.append(f"{name} ({rel}): no closed comparison (<= / >=) found")
        if strict:
            problems.append(f"{name} ({rel}): a STRICT comparison (< / >) was found — "
                            "an upstream min()/max() cap can land exactly on it (ADR-023)")
    assert not problems, "\n".join(problems)


def test_new_cap_literal_pairs_are_reviewed():
    """Auto-discovered cap-literal pairs must all be reviewed (allowlisted)."""
    discovered = _discover_cap_literal_pairs()
    unreviewed = {k: v for k, v in discovered.items() if k not in REVIEWED_CAP_LITERAL_PAIRS}
    assert not unreviewed, (
        "New min()/max() cap literal also appears in a strict comparison — review it:\n"
        + "\n".join(f"  {lit}: {files}" for lit, files in sorted(unreviewed.items()))
        + "\nIf this is the ADR-023 bug class, change the strict comparison to a closed "
          "interval. Otherwise add the literal to REVIEWED_CAP_LITERAL_PAIRS with a reason."
    )


def test_confidence_cap_guards_use_closed_interval():
    """Cross-file ADR-023: a strict comparison of a confidence value against a
    documented cap value must be a closed interval.

    classification/classifier.py caps ``classification_confidence`` to exactly
    0.40 / 0.50 / 0.55 via ``min(confidence, C)``. Any downstream guard that
    tests ``conf < C`` (strict) silently accepts the capped value as
    high-confidence. This test scans *all* modules so the cap and the guard do
    not have to live in the same file.
    """
    problems: list[str] = []
    for p in _iter_source_files():
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        for lineno, line in enumerate(_read(p).splitlines(), start=1):
            for op, lit in _CONF_STRICT_RE.findall(line):
                if lit in CONFIDENCE_CAP_VALUES:
                    problems.append(
                        f"{rel}:{lineno}: strict '{op} {lit}' on a confidence value — "
                        "an upstream min(confidence, C) cap can land exactly here (ADR-023); "
                        "use '<=' / '>='."
                    )
    assert not problems, "\n".join(problems)
