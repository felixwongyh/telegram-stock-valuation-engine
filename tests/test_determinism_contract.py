"""§1.1/§1.2/§1.4 - determinism is a property of the *engine*, not of a run.

The one-off 50-ticker experiment proved frozen runs are bitwise identical and
order-independent. That experiment is not repeatable in CI (it needs a warm
cache and ~10s of wall clock), so the properties it demonstrated are asserted
here on a small, hermetic sample: same inputs twice, different order, and a
fresh process with a different hash seed.

If any of these fail, a 50-ticker run cannot be trusted to reproduce, and every
downstream drift comparison becomes meaningless.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest

from benchmark.collector import collect

SAMPLE = ["NVDA", "KO", "CEG", "PFE", "NEE", "WMT", "COST", "JNJ"]
VALUATION_KEYS = [
    "rd_status", "rd_implied_revenue_cagr", "rd_wacc", "rd_base_fcf",
    "beta_used", "risk_free_rate", "price", "rd_terminal_growth",
]


def _facts(t: str) -> dict:
    return asyncio.run(collect(t)).to_dict()


def _pick(d: dict) -> dict:
    return {k: d.get(k) for k in VALUATION_KEYS}


#: Pinned so a run on a later day reads the same files. See
#: ``data.providers.resolve_snapshot_id``.
SNAPSHOT_ID = "20261123"


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setenv("UVE_FREEZE_CACHE", "1")
    monkeypatch.setenv("UVE_SNAPSHOT_ID", SNAPSHOT_ID)


def test_repeat_run_is_bitwise_identical() -> None:
    """§1.1: run twice on the frozen snapshot, every valuation field must match."""
    first = {t: _pick(_facts(t)) for t in SAMPLE}
    second = {t: _pick(_facts(t)) for t in SAMPLE}
    for t in SAMPLE:
        assert first[t] == second[t], (
            f"{t} not reproducible:\n  run1={first[t]}\n  run2={second[t]}"
        )


def test_execution_order_does_not_change_results() -> None:
    """§1.2: a ticker's numbers must not depend on which ran before it."""
    forward = {t: _pick(_facts(t)) for t in SAMPLE}
    backward = {t: _pick(_facts(t)) for t in reversed(SAMPLE)}
    for t in SAMPLE:
        assert forward[t] == backward[t], (
            f"{t} changed with execution order: {forward[t]} vs {backward[t]}"
        )


def test_isolated_ticker_matches_full_run_value() -> None:
    """A ticker run alone must agree with its value from the 50-ticker sweep.

    Uses the frozen raw facts from the full run as the reference; a mismatch
    would mean shared state leaked between tickers.
    """
    path = "benchmark/results/raw_facts.json"
    if not os.path.exists(path):
        pytest.skip("no recorded full-run facts to compare against")
    full = json.load(open(path))
    for t in SAMPLE[:4]:
        if t not in full:
            continue
        alone = _pick(_facts(t))
        ref = _pick(full[t])
        assert alone == ref, f"{t} differs when run alone: {alone} vs {ref}"


def test_fresh_process_with_different_hash_seed_agrees() -> None:
    """§1.4: no hidden dependence on dict/set iteration order.

    A different ``PYTHONHASHSEED`` changes string hashing, which is the usual way
    an accidental set-iteration dependency shows up. Two seeds must agree.
    """
    script = (
        "import asyncio,json,logging,sys;"
        "logging.disable(logging.CRITICAL);"
        "sys.path.insert(0,'.');"
        "from benchmark.collector import collect;"
        "out={};"
        "\nfor t in %r:\n"
        "    out[t]=(lambda d:{k:d.get(k) for k in %r})(asyncio.run(collect(t)).to_dict())\n"
        "print(json.dumps(out,default=str))"
    ) % (SAMPLE[:3], VALUATION_KEYS)

    def run(seed: str) -> dict:
        env = dict(os.environ, PYTHONHASHSEED=seed, UVE_FREEZE_CACHE="1")
        r = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True,
            env=env, cwd=".", timeout=300,
        )
        assert r.returncode == 0, r.stderr[-2000:]
        return json.loads(r.stdout.strip().splitlines()[-1])

    a, b = run("0"), run("12345")
    assert a == b, f"hash seed changed results: {a} vs {b}"
