"""Triage §10 survivors: is the named test wrong, or is the defect unguarded?

For each mutation, inject it and run the *whole* suite. Two outcomes:

* some other test fails -> MISATTRIBUTED: the guard exists, the mapping is wrong.
* nothing fails         -> UNGUARDED: the suite genuinely cannot see the defect.

The distinction decides the fix: remap the mutation, or write a test.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_mutation_experiments import MUTATIONS, REPO, apply_mutation  # noqa: E402


def full_suite() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:randomly",
         "--tb=no"],
        cwd=REPO, capture_output=True, text=True,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    fails = [ln for ln in lines if ln.startswith("FAILED")]
    return proc.returncode, "\n".join(fails[:12]) or (lines[-1] if lines else "")


def main() -> int:
    ids = sys.argv[1:]
    for m in MUTATIONS:
        if ids and m.mid not in ids:
            continue
        target = REPO / m.path
        original = target.read_bytes()
        sha = hashlib.sha256(original).hexdigest()
        backup = Path(tempfile.mkdtemp()) / "b"
        backup.write_bytes(original)

        err = apply_mutation(m)
        if err:
            print(f"{m.mid}: ANCHOR DRIFT - {err}")
            continue
        try:
            rc, detail = full_suite()
        finally:
            target.write_bytes(backup.read_bytes())
            assert hashlib.sha256(target.read_bytes()).hexdigest() == sha

        verdict = "MISATTRIBUTED" if rc != 0 else "UNGUARDED"
        print(f"\n=== {m.mid} {m.title} -> {verdict}")
        print(f"    named test: {m.tests[0]}")
        print(detail[:900])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
