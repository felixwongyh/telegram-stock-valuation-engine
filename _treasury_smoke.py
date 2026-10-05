import sys
from pathlib import Path
ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT))

from data.providers import TreasuryYieldProvider

print("--- TreasuryYieldProvider smoke test ---")
tp = TreasuryYieldProvider()
print("  Cache dir =", tp._cache_dir)
curve = tp.get_yield_curve()
if curve is None:
    print("  FAIL: curve = None (network/parse error).")
    sys.exit(1)

src = curve.get("source", "")
date = curve.get("as_of_date", "")
print("  OK: source=", src)
print("  OK: as_of_date=", date)
rates = curve.get("rates") or {}
print("  Tenors available:", list(rates.keys()))
for k in ["3 Mo","6 Mo","2 Yr","5 Yr","10 Yr","30 Yr"]:
    v = rates.get(k)
    if v is not None:
        pct = v * 100
        print(f"    {k:<6}: {pct:.2f}%")

curve2 = tp.get_yield_curve()
print("  Cache test: second call exists?", curve2 is not None)
p = tp._cache_path()
import os
print("  Cache file exists:", os.path.exists(p), " ->", p)
