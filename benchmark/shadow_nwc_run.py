"""Shadow-mode NWC run over the benchmark universe.

Writes a per-ticker report and a summary table. Reads the engine's own
breakdown but never writes to it, so golden and every published number are
untouched. The output exists to decide *whether* to adopt a new NWC treatment,
not to adopt it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections import Counter

logging.disable(logging.WARNING)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.nwc_shadow import diagnose, format_report  # noqa: E402
from benchmark.registry import tickers  # noqa: E402
from classification.ml_classifier import MLHybridClassifier  # noqa: E402
from config import resolve_forecast_horizon  # noqa: E402
from data import DataValidator, FinancialNormalizer, YahooFinanceProvider  # noqa: E402
from forecasts.fcf_projection import (  # noqa: E402
    dcf_path_inputs_from_data,
    dcf_projection_shape,
)
from forecasts.nwc_utils import business_type_from_profile  # noqa: E402
from models.router import NAME_TO_MODEL, ModelRouter  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "shadow_nwc")


async def _one(ticker: str) -> dict:
    provider = YahooFinanceProvider()
    data = await provider.get_financial_data(ticker)
    data = DataValidator.validate(FinancialNormalizer.normalize_all(data))
    profile = MLHybridClassifier().classify(data)
    models = ModelRouter().run_all(data, profile)
    rd = models.get("ReverseDCF")
    if rd is None:
        # Correct routing, not a failure: banks/insurers/REITs have no
        # operating working capital in the DCF sense, so a Reverse-DCF NWC
        # diagnosis is not applicable to them.
        return {"ticker": ticker, "not_applicable": True,
                "reason": "ReverseDCF not routed (financial/REIT by design)"}
    bd = rd.breakdown or {}
    horizon = resolve_forecast_horizon(business_type_from_profile(profile))
    inputs = dcf_path_inputs_from_data(data, profile, horizon)
    if inputs is None:
        return {"ticker": ticker, "error": "no dcf path inputs"}
    _, _shape, _off, om_center = dcf_projection_shape(
        inputs.base_revenue, inputs.base_growth, inputs.base_margin, horizon
    )
    meta = bd.get("solver_meta") or {}
    undetermined = meta.get("ev_direction_undetermined")

    # The engine only records ``ev_direction_undetermined`` on the no-root path,
    # so most tickers carry no flag at all. Re-run the engine's *own* sweep with
    # the *same* sanctioned band and NWC candidates rather than inferring the
    # flag from its absence — a missing key means "not computed", not "robust".
    band = bd.get("economic_plausibility_band")
    if undetermined is None and band:
        model = NAME_TO_MODEL["ReverseDCF"]
        nwc_used = model._nwc_ratio_for(data, profile, horizon)
        sweep = model._ev_direction_robustness(
            data, profile, bd["wacc"], bd["terminal_growth"], horizon,
            float(band[0]), float(band[1]),
            list(model.rcfg.nwc_sensitivity_ratios) + [nwc_used],
        )
        undetermined = not sweep.get("robust")

    diag = diagnose(
        data,
        wacc=bd.get("wacc"),
        terminal_growth=bd.get("terminal_growth"),
        horizon=horizon,
        operating_margin=om_center,
        tax_rate=inputs.tax_rate,
        da_ratio=inputs.da_ratio,
        capex_ratio=abs(inputs.capex_ratio),
        direction_robust=(not undetermined) if undetermined is not None else None,
        margin_is_flat=True,
    )
    diag["reverse_dcf_status"] = bd.get("implied_expectations", {}).get(
        "reverse_dcf_status"
    ) or rd.status
    diag["engine_nwc_ratio"] = bd.get("implied_expectations", {}).get("nwc_ratio_used")
    diag["engine_direction_undetermined"] = undetermined
    return diag


async def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    results = []
    for t in tickers():
        try:
            results.append(await _one(t))
        except Exception as exc:  # noqa: BLE001 - a shadow run must not abort
            results.append({"ticker": t, "error": str(exc)[:160]})

    blocks = []
    rows = []
    for r in results:
        if r.get("not_applicable"):
            blocks.append(f"{r['ticker']} — 不适用：{r['reason']}")
            rows.append((r["ticker"], "NOT_APPLICABLE", "", "", "", "", ""))
            continue
        if "error" in r:
            blocks.append(f"{r['ticker']} — ERROR: {r['error']}")
            rows.append((r["ticker"], "ERROR", "", "", "", "", ""))
            continue
        blocks.append(format_report(r))
        est = r["estimators"]
        dt = r.get("direction_test") or {}
        rows.append((
            r["ticker"],
            r["confidence"]["kind"],
            est["level"]["value"],
            est["intensity"]["value"],
            est["robust_marginal"]["value"],
            est.get("intensity_proxy_marginal"),
            "conflict" if est.get("estimates_conflict") else "",
            dt.get("applicable"),
            dt.get("verdict"),
        ))

    with open(os.path.join(OUT_DIR, "per_ticker.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n\n".join(blocks))

    def _f(v):
        return "" if v is None else f"{v:+.3f}"

    with open(os.path.join(OUT_DIR, "summary.tsv"), "w", encoding="utf-8") as fh:
        fh.write("ticker\tconfidence\tlevel\tintensity\trobust_marginal\t"
                 "intensity_proxy\tconflict\tdisc_applicable\tdisc_verdict\n")
        for row in rows:
            if len(row) == 7:
                fh.write("\t".join(str(x) for x in row) + "\n")
            else:
                fh.write("\t".join([
                    row[0], row[1], _f(row[2]), _f(row[3]), _f(row[4]),
                    _f(row[5]), row[6], str(row[7]), str(row[8]),
                ]) + "\n")

    with open(os.path.join(OUT_DIR, "diagnostics.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, ensure_ascii=False, default=str)

    kinds = Counter(
        r["confidence"]["kind"]
        for r in results
        if "error" not in r and not r.get("not_applicable")
    )
    n_na = sum(1 for r in results if r.get("not_applicable"))
    print("=" * 78)
    print(f"SHADOW NWC RUN — {len(results)} tickers (golden untouched)")
    print("=" * 78)
    for k, n in kinds.most_common():
        print(f"  {k:26s} {n:3d}")
    if n_na:
        print(f"  {'NOT_APPLICABLE (routing)':26s} {n_na:3d}")
    n_err = sum(1 for r in results if "error" in r)
    if n_err:
        print(f"  {'ERROR':26s} {n_err:3d}")
    print(f"\n  Output: {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
