"""Run the 50-ticker benchmark and persist raw facts."""

import asyncio
import json
import logging
import os
import sys
import time

logging.disable(logging.INFO)

sys.path.insert(0, "/workspace/telegram-stock-valuation-engine")

from benchmark.collector import TickerFacts, collect  # noqa: E402
from benchmark.registry import tickers  # noqa: E402

RESULTS_DIR = "/workspace/telegram-stock-valuation-engine/benchmark/results"
OUT = os.path.join(RESULTS_DIR, "raw_facts.json")


def _flush(out: dict) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    os.replace(tmp, OUT)


async def main() -> None:
    out: dict = {}
    t0 = time.time()
    for i, t in enumerate(tickers(), 1):
        try:
            f = await asyncio.wait_for(collect(t), timeout=240)
        except asyncio.TimeoutError:
            f = TickerFacts(ticker=t, fetch_error="timeout 240s")
        except Exception as e:  # noqa: BLE001
            f = TickerFacts(ticker=t, fetch_error=f"{type(e).__name__}: {e}")
        out[t] = f.to_dict()
        print(
            f"[{i:2d}/50] {t:6s} fetch={f.fetch_ok} rd={out[t].get('rd_status')}",
            flush=True,
        )
        _flush(out)  # persist incrementally so a late crash loses nothing
    print(f"done in {time.time() - t0:.0f}s", flush=True)


asyncio.run(main())
