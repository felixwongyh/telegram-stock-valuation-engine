"""Demo: WACC 7-step bottom-up + TVG 3-band (Base/Low/High) + Sensitivity Matrix Stability Analysis.

Runs both (a) Synthetic AAPL/MSFT/NVDA (fast & deterministic) and
     (b) Real Yahoo Finance AAPL (if network/API reachable, else skip)

Output format follows user's strict requirements:
  • WACC: Calculated WACC + Industry Range (sanity check table)
  • Terminal Growth: Base / Low / High + Source
  • Sensitivity: Markdown table (WACC rows × Terminal Growth cols), *base cell highlighted*
"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data import FinancialNormalizer, SyntheticDataProvider, DataValidator
from classification.classifier import BusinessClassifier
from models.dcf import DCFModel
from analysis.sensitivity import SensitivityAnalyzer
from reporting.dashboard import _fmt_pct, _fmt_num, _fmt_share, _fmt_money


def print_treasury_banner() -> None:
    """Print the latest Treasury yield curve (real data via TreasuryYieldProvider)."""
    print("\n" + "=" * 78)
    print("  🇺🇸  U.S. Treasury Yield Curve (Latest Business Day) — SOURCE: home.treasury.gov")
    print("=" * 78)
    try:
        from data.providers import TreasuryYieldProvider
        tp = TreasuryYieldProvider()
        curve = tp.get_yield_curve()
        if curve is None:
            print("  ⚠  Treasury provider returned None — network/CSV unreachable."
                  "  WACC will use DCFConfig default Rf (4.50%).")
            return
        rates = curve.get("rates") or {}
        as_of = curve.get("as_of_date", "unknown date")
        src = curve.get("source", "home.treasury.gov")
        print(f"  As-of date : {as_of}")
        print(f"  Source     : {src}")
        print(f"  Downloaded : {curve.get('downloaded_at_utc','N/A')} UTC")
        print()
        # Order by tenor — display the canonical 13 tenors
        display_order = ["1 Mo", "2 Mo", "3 Mo", "4 Mo", "6 Mo",
                         "1 Yr", "2 Yr", "3 Yr", "5 Yr", "7 Yr",
                         "10 Yr", "20 Yr", "30 Yr"]
        # Build rows: 1m/2m/3m/4m/6m | 1y/2y/3y | 5y/7y/10y | 20y/30y
        def pct(v: float) -> str:
            return f"{(v*100):.2f}%" if v is not None else "  N/A "
        row1 = []
        for t in display_order[:5]:
            row1.append(f"{t:>6}:{pct(rates.get(t)):>9}")
        row2 = []
        for t in display_order[5:8]:
            row2.append(f"{t:>6}:{pct(rates.get(t)):>9}")
        row3 = []
        for t in display_order[8:11]:
            row3.append(f"{t:>6}:{pct(rates.get(t)):>9}")
        row4 = []
        for t in display_order[11:]:
            row4.append(f"{t:>6}:{pct(rates.get(t)):>9}")
        print("  Money Market : " + "   ".join(row1))
        print("  Short End     : " + "   ".join(row2))
        print("  Belly         : " + "   ".join(row3))
        print("  Long End      : " + "   ".join(row4))
        # Highlight 10Y (our primary Rf input)
        r10 = rates.get("10 Yr")
        if r10 is not None:
            print(f"\n  ⭐ 10-Year Par Yield = {pct(r10)}   ←  used by WACC Step 1 as Risk-Free Rate (Rf)")
    except Exception as e:
        print(f"  ⚠  Treasury banner failed (non-fatal): {e}")


def run_one(tkr: str, data_raw, title: str) -> None:
    normalizer = FinancialNormalizer
    data = normalizer.normalize_all(data_raw)
    data = DataValidator.validate(data)
    profile = BusinessClassifier().classify(data)
    dcf = DCFModel()
    sens = SensitivityAnalyzer(steps=7)

    print(f"\n{'='*78}\n  {title}  |  Ticker: {tkr}\n{'='*78}")

    # --- Run DCF ---
    res = dcf.calculate(data, profile)
    if not res.is_success() or not res.breakdown:
        print(f"  !! DCF failed: status={res.status}, notes={res.notes}")
        return

    bd = res.breakdown
    wb = bd.get("wacc_breakdown")
    tvg = bd.get("tvg_range")

    # --- Market snapshot ---
    print(f"\n[Market Snapshot]")
    print(f"  Price={_fmt_share(data.market.current_price)}  |  "
          f"MCap={_fmt_money(data.market.market_cap)}  |  "
          f"β={_fmt_num(data.market.beta, 2)}  |  "
          f"Sector/Industry = {data.market.sector or 'N/A'} / {data.market.industry or 'N/A'}")

    # ================================================================
    # (1) WACC 7-step + Sanity Check (严格格式输出)
    # ================================================================
    if wb is not None:
        print("\n[1] WACC Bottom-Up Calculation (7 steps, auditable)")
        print("-" * 60)
        print(wb.step_by_step_summary())
        # --- Strict Sanity Check table (per user requirement) ---
        print("\n    ── Sanity Check (Industry WACC Range) ──")
        for line in wb.formatted_sanity_check().splitlines():
            print(f"    {line}")

    # ================================================================
    # (2) Terminal Growth 三档 (Base/Low/High) — 严格格式输出
    # ================================================================
    if tvg is not None:
        print("\n[2] Terminal Growth (dynamic, 3 scenarios)")
        print("-" * 60)
        # 严格按照用户要求格式：
        print(tvg.formatted_output())
        print()
        print(tvg.derivation_trace())

        v_base = res.value_per_share
        v_low = bd.get("value_per_share_low_g")
        v_high = bd.get("value_per_share_high_g")
        price = data.market.current_price
        print(f"\n  → 3-Scenario Valuation vs Current ({_fmt_share(price)}):")
        for tag, v in [("Low  g", v_low), ("Base g", v_base), ("High g", v_high)]:
            if v is None or price is None:
                continue
            diff = (v - price) / price * 100
            mark = "✅" if -15 <= diff <= 30 else ("🟢" if diff < -15 else "🟠")
            print(f"    {mark} {tag}: {_fmt_share(v):>9}   vs price = {diff:+.1f}%")

    # ================================================================
    # (3) Sensitivity Matrix (WACC rows × TVG cols) — Markdown table
    # ================================================================
    print("\n[3] Sensitivity Matrix: WACC vs Terminal Growth")
    print("-" * 60)
    try:
        mat = sens.wacc_vs_terminal_growth(data, profile)
        # Markdown 表格 (严格格式: | WACC \ g | 2.0% | ... |)
        md_table = mat.formatted_markdown_table(
            row_title="WACC", col_title="g",
            row_decimals=1, col_decimals=2,
            max_rows=7, max_cols=7,
        )
        print(md_table)

        # Stability analysis
        stats = mat.stability_stats()
        if stats.get("n_valid_cells", 0) > 0:
            print("\n  ── Matrix Stability Analysis (is valuation robust?) ──")
            print(f"    Valid cells          : {stats['n_valid_cells']}")
            print(f"    Min / Max value      : {_fmt_share(stats['min'])}  ↔  {_fmt_share(stats['max'])}")
            print(f"    Range vs Base        : {stats['range_pct_vs_base']:.1f}%  "
                  f"({'✅ Stable (<40%)' if stats['range_pct_vs_base'] < 40 else '⚠ Sensitive (≥40%)' if stats['range_pct_vs_base'] < 80 else '🔴 Highly Sensitive (≥80%)'})")
            print(f"    Coefficient of Var.  : {stats['cv_pct']:.1f}%  (lower = more robust)")
            dev = stats.get("pct_deviation_vs_base", {})
            print(f"    Avg |Δ vs Base|      : {dev.get('avg_abs', 0):.1f}%")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  !! Sensitivity fail: {e!r}")

    # --- Final verdict ---
    price = data.market.current_price
    pps = res.value_per_share
    if price and pps:
        upside = (pps - price) / price * 100
        print(f"\n{'='*78}")
        verdict = "BUY" if upside > 15 else ("HOLD" if upside > -15 else "SELL")
        print(f"  [DCF Verdict]  Fair Value = {_fmt_share(pps)}  vs  Price = {_fmt_share(price)}  "
              f"→  Upside {upside:+.1f}%  →  **{verdict}**")
        print(f"{'='*78}")


async def real_yahoo_or_none(tkr: str):
    try:
        from data.providers import YahooFinanceProvider
    except Exception as e:
        print(f"  ! Yahoo import err: {e!r}")
        return None
    yahoo = YahooFinanceProvider()
    try:
        return await yahoo.get_financial_data(tkr)
    except Exception as e:
        print(f"  ! Yahoo fetch failed for {tkr}: {e!r}")
        return None


async def main():
    # 0. Print real Treasury yield banner (real data from home.treasury.gov)
    print_treasury_banner()

    # 1. Synthetic providers (fast, deterministic)
    synth = SyntheticDataProvider()
    for tkr in ["AAPL", "MSFT", "NVDA"]:
        data_raw = synth.get_financial_data(tkr)
        run_one(tkr, data_raw, title=f"[Synthetic DEMO] {tkr}")

    # 2. Real Yahoo AAPL (optional; network unreachable → skip)
    print("\n" + "#" * 78)
    print("# Attempting REAL Yahoo Finance for AAPL… (optional, slow)")
    print("#" * 78)
    real_aapl = await real_yahoo_or_none("AAPL")
    if real_aapl is not None:
        run_one("AAPL", real_aapl, title="[REAL Yahoo Finance] AAPL (cached)")
    else:
        print("  (Real Yahoo skipped/unreachable — demo is still valid with Synthetic data.)")

    # Addt'l tickers from cache if exist
    for extra in ["BAC", "JNJ"]:
        cached = ROOT / ".cache" / "yahoo_finance" / f"{extra}_20260922.json"
        if cached.exists():
            print(f"\n(Found cached {extra}; skipping to avoid Yahoo rate limits.)")


if __name__ == "__main__":
    asyncio.run(main())
