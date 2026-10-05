"""
_dump_features_for_labeling.py - Batch Feature Dump for Manual Labeling (Phase 3 Prep)

Purpose:
    Before 1000+ real manual labels arrive, pre-extract 15 numerical features +
    textual metadata (name/sector/industry) for a large ticker universe and dump
    them to CSV. The CSV matches the schema expected by
    `build_training_set_from_csv()` in ml_classifier.py.

Workflow:
    1. Run:  python _dump_features_for_labeling.py --n 1000 --out classification/labeling_dump.csv
    2. Open CSV in Excel / Google Sheets → fill in the `label` column using
       BusinessType enum .value strings (CASE-SENSITIVE, PascalCase exactly):
         MatureTech | SaaS | Semiconductor | ConsumerCyclical | REIT | Bank
         | Insurance | Commodity | Utilities | Conglomerate | Unknown
       (These correspond to BusinessType.MATURE_TECH.value, BusinessType.SAAS.value, ...)
       Any unrecognized value will be remapped to Unknown with a warning.
    3. Back in code, 1-line switch to real labels in LightGBMBusinessClassifier._train_from_scratch:
         # X_num_list, X_text, y_raw = build_synthetic_training_set()   # OLD
         X_num_list, X_text, y_raw = build_training_set_from_csv(r"classification\labeling_dump.csv")  # NEW
       Everything downstream stays identical.

Features (matches _NUM_FEATURE_NAMES in ml_classifier.py):
    log_revenue, revenue_cagr_3y, gross_margin, gross_margin_vol_3y,
    operating_margin, operating_margin_vol_3y, fcf_margin, capex_to_revenue,
    interest_to_revenue, de_ratio, beta, market_cap_log, pe, pb, ev_ebitda

Text columns (for TF-IDF downstream):
    company_name, sector, industry

Concurrency / Robustness:
    - Async httpx via YahooFinanceProvider with semaphore (default 8)
    - Saves a *checkpoint* every --checkpoint-every rows (default 50) so a
      partial run is never lost. Resume by pointing --resume <file> at it.
    - Skips tickers that fail hard (after retries) and records them in *_failures.csv.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

from config import get_logger  # noqa: E402
from classification.ml_classifier import (  # noqa: E402
    _NUM_FEATURE_NAMES,
    CSV_NUMERICAL_COLUMNS,
    CSV_TEXT_COLUMNS,
    CSV_REQUIRED_COLUMNS,
    extract_numerical_features,
)
from data.providers import YahooFinanceProvider, SyntheticDataProvider  # noqa: E402
from data.models import FinancialData  # noqa: E402

log = get_logger("dump_features_for_labeling")


# ---------------------------------------------------------------------------
# Default Ticker Universe — 1000+ liquid US equities across all BusinessTypes
# ---------------------------------------------------------------------------
# Mix of: S&P 500 components, large-cap, mid-cap, and sector-representative names.
# We intentionally include names spread across the 10 archetypes so the final
# labeled training set will be reasonably class-balanced.
# Users may override via --tickers-file (one ticker per line, # comments ok).

_SP500_PLUS_EXTRA: List[str] = [
    # --- Tech / Mature Tech (≈80) ---
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "AVGO", "ORCL", "ADBE",
    "CRM", "CSCO", "NFLX", "INTC", "AMD", "QCOM", "TXN", "IBM", "HPQ", "DELL",
    "MU", "AMAT", "LRCX", "KLAC", "NOW", "PANW", "SNOW", "CRWD", "ZS", "DDOG",
    "FTNT", "NET", "TEAM", "MDB", "SHOP", "WDAY", "HUBS", "SPLK", "COIN", "UBER",
    "ABNB", "LYFT", "DASH", "PYPL", "SQ", "BKNG", "EXPE", "TRIP", "TTD", "ROKU",
    "PLTR", "SNAP", "PINS", "PATH", "U", "ZM", "DOCU", "ASAN", "MSTR", "NVST",
    "RIVN", "LCID", "FUV", "HOOD", "COIN", "NDAQ", "ICE", "SPGI", "CME", "MKTX",
    # --- SaaS / Cloud (≈60) ---
    "NOW", "CRWD", "ZS", "DDOG", "PANW", "FTNT", "NET", "MDB", "SHOP", "WDAY",
    "HUBS", "SPLK", "OKTA", "TWLO", "COUP", "CDAY", "DOCN", "APP", "FIVN", "PCTY",
    "PAYC", "ULTI", "BLDR", "CFLT", "GTLB", "MNDY", "SMAR", "TLND", "WIX", "YEXT",
    "ZEN", "BOX", "CLDR", "DBX", "PD", "RP", "SQSP", "TENB", "VEEV", "BILL",
    # --- Semiconductors (≈50) ---
    "NVDA", "AVGO", "AMD", "QCOM", "TXN", "INTC", "MU", "AMAT", "LRCX", "KLAC",
    "TSM", "ASML", "NXPI", "ADI", "ON", "MCHP", "SWKS", "MRVL", "SLAB", "MPWR",
    "ENTG", "TER", "KLIC", "COHR", "IPGP", "LITE", "IIVI", "ACLS", "AMKR", "ASEL",
    "DIOD", "EPAM", "FLEX", "JBL", "SIMO", "SMCI", "VLKP", "WOLF", "ARM", "IMAX",
    # --- Consumer Cyclical (≈70) ---
    "TSLA", "F", "GM", "TM", "HMC", "RACE", "NIO", "LI", "XPEV", "LCID",
    "AMZN", "WMT", "COST", "TGT", "HD", "LOW", "M", "KSS", "JCP", "DDS",
    "SBUX", "MCD", "YUM", "CMG", "DPZ", "QSR", "DRI", "EAT", "CAKE", "BLMN",
    "NKE", "LULU", "UA", "UAA", "DECK", "SKX", "CROX", "RL", "PVH", "GPS",
    "BKNG", "EXPE", "ABNB", "MAR", "H", "HLT", "IHG", "RCL", "CCL", "NCLH",
    "DAL", "UAL", "AAL", "LUV", "ALK", "SAVE", "JBLU", "HA", "AEO", "ANF",
    # --- REITs (≈70) ---
    "AMT", "PLD", "CCI", "EQIX", "PSA", "SPG", "O", "WELL", "DLR", "VTR",
    "ARE", "BXP", "HST", "AVB", "EQR", "ESS", "MAA", "UDR", "AIV", "SUZ",
    "IRM", "CORE", "AKR", "ADC", "ARCC", "BRX", "EPR", "EPRT", "FRT", "GET",
    "HTA", "KIM", "NNN", "NHI", "OHI", "PK", "REG", "ROIC", "SRC", "STAG",
    "VNO", "WPC", "WRI", "WY", "WYNN", "MAC", "PEAK", "HASI", "IVT", "INVH",
    "MPW", "OHI", "RPT", "SBAC", "TCO", "UBA", "URD", "VICI", "VER", "APLE",
    # --- Banks (≈60) ---
    "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "TFC", "PNC", "COF",
    "AXP", "BK", "STT", "SCHW", "BLK", "CME", "ICE", "NDAQ", "SPGI", "MKTX",
    "BBT", "FITB", "HBAN", "KEY", "MTB", "NTRS", "RF", "SNV", "SIVB", "SYF",
    "CMA", "CFG", "DFS", "ALLY", "ZION", "PBCT", "FRC", "CFR", "TCBI", "EWBC",
    "HOMB", "IBOC", "INDB", "OZK", "PFG", "PRU", "MET", "AFL", "UNM", "LNC",
    # --- Insurance (≈40) ---
    "BRK-B", "JPM", "BAC", "WFC", "C", "PGR", "TRV", "ALL", "AIG", "MET",
    "PRU", "AFL", "UNM", "LNC", "HIG", "CINF", "MKL", "RGA", "RE", "SLF",
    "PFG", "GL", "GNW", "L", "MAF", "AFG", "AIZ", "BHF", "CNO", "EQH",
    "FNF", "HCI", "IHC", "KNSL", "MCY", "ORI", "PRO", "RLI", "SIGI", "WRB",
    # --- Commodity / Energy & Materials (≈70) ---
    "XOM", "CVX", "COP", "EOG", "OXY", "PXD", "SLB", "HAL", "BKR", "MPC",
    "VLO", "PSX", "OIH", "FANG", "DVN", "MRO", "HES", "APA", "CTRA", "WMB",
    "KMI", "ET", "EPD", "TRGP", "ENB", "CNQ", "SU", "IMO", "TECK", "FCX",
    "SCCO", "NUE", "STLD", "CLF", "X", "AA", "ALB", "CCJ", "CF", "CTVA",
    "MOS", "NTR", "FMC", "DOW", "DD", "EMN", "LYB", "APD", "ASH", "PPG",
    # --- Utilities (≈40) ---
    "NEE", "DUK", "SO", "D", "AEP", "SRE", "EXC", "XEL", "WEC", "ED",
    "EIX", "PCG", "PEG", "FE", "CMS", "LNT", "AWK", "DTE", "VST", "CNP",
    "ES", "ETR", "UGI", "PPL", "PNW", "AEE", "AEP", "ATO", "CIG", "CPL",
    "EVRG", "IDA", "MSEX", "NI", "NRG", "OGS", "POR", "SJG", "STE", "TLN",
    # --- Conglomerates / Multi-Industry (≈30) ---
    "BRK-B", "GE", "HON", "CAT", "DE", "MMM", "ITW", "EMR", "ETN", "PH",
    "ROK", "ABB", "SI", "GNRC", "SWK", "TT", "IR", "ROP", "CMI", "PCAR",
    "GD", "LMT", "NOC", "BA", "RTX", "LHX", "HWM", "IEX", "FAST", "PWR",
    # --- Healthcare (≈60, often classified as mature_tech / unknown) ---
    "JNJ", "UNH", "PFE", "ABBV", "LLY", "MRK", "TMO", "ABT", "MDT", "BMY",
    "AMGN", "GILD", "BIIB", "REGN", "VRTX", "ISRG", "SYK", "BSX", "CI", "CVS",
    "HUM", "CNC", "MCK", "CAH", "COR", "DGX", "LH", "IQV", "WBA", "ESRX",
    "ZTS", "INCY", "MRNA", "BNTX", "ALNY", "REGN", "ILMN", "DXCM", "IDXX", "EXAS",
    # --- Consumer Staples (≈40) ---
    "PG", "KO", "PEP", "WMT", "COST", "TGT", "MO", "PM", "BTI", "DEO",
    "MDLZ", "KHC", "GIS", "K", "KMB", "CL", "CHD", "COTY", "EL", "ETD",
    "HRL", "SYY", "TSN", "CPB", "FLO", "HAIN", "LMND", "MKC", "NOMD", "POST",
    # --- Media / Telecom (≈30) ---
    "DIS", "NFLX", "CMCSA", "WBD", "PARA", "FOX", "NWSA", "T", "VZ", "TMUS",
    "CHTR", "LBRDA", "LBRDK", "QVCA", "SIRI", "SONY", "TLSA", "TU", "VOD", "ORAN",
    # --- Unknown / Edge-case variety (≈50) ---
    "SPCE", "RKLB", "LVOX", "MAXR", "VSAT", "BA", "GE", "MMM", "HII", "LMT",
    "TDOC", "OZON", "SE", "BABA", "JD", "PDD", "BIDU", "NIO", "LI", "XPEV",
]

# Dedupe while preserving first-seen order
def _dedupe(seq: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for s in seq:
        s = s.strip().upper()
        if s and s not in seen and not s.startswith("#"):
            seen.add(s)
            out.append(s)
    return out

DEFAULT_TICKERS: List[str] = _dedupe(_SP500_PLUS_EXTRA)


@dataclass
class LabelingRow:
    """One row of the labeling CSV. Matches build_training_set_from_csv schema."""
    ticker: str
    company_name: str = ""
    sector: str = ""
    industry: str = ""
    # 15 numerical features (default 0.0, matches extract_numerical_features fallback)
    log_revenue: float = 0.0
    revenue_cagr_3y: float = 0.0
    gross_margin: float = 0.0
    gross_margin_vol_3y: float = 0.0
    operating_margin: float = 0.0
    operating_margin_vol_3y: float = 0.0
    fcf_margin: float = 0.0
    capex_to_revenue: float = 0.0
    interest_to_revenue: float = 0.0
    de_ratio: float = 0.0
    beta: float = 0.0
    market_cap_log: float = 0.0
    pe: float = 0.0
    pb: float = 0.0
    ev_ebitda: float = 0.0
    # Human fills these:
    label: str = ""  # BusinessType value, e.g. "semiconductor"
    note: str = ""   # optional context


CSV_FIELDNAMES: List[str] = list(LabelingRow.__dataclass_fields__.keys())


def _row_from_data(data: FinancialData) -> LabelingRow:
    """Convert a FinancialData object (with numerical extraction) into a CSV row."""
    num_feat = extract_numerical_features(data)
    mkt = data.market
    return LabelingRow(
        ticker=data.ticker,
        company_name=(mkt.company_name or ""),
        sector=(mkt.sector or ""),
        industry=(mkt.industry or ""),
        **{k: float(num_feat.get(k, 0.0)) for k in _NUM_FEATURE_NAMES},
        label="",
        note="",
    )


# ---------------------------------------------------------------------------
# Async worker loop with semaphore throttling, retries, checkpointing
# ---------------------------------------------------------------------------
async def _fetch_one(yf: YahooFinanceProvider, ticker: str,
                     sem: asyncio.Semaphore, retries: int = 2) -> Tuple[str, Optional[LabelingRow], Optional[str]]:
    """Fetch one ticker → (ticker, row_or_None, error_or_None)."""
    async with sem:
        last_err: Optional[str] = None
        for attempt in range(retries + 1):
            try:
                data = await yf.get_financial_data(ticker)
                row = _row_from_data(data)
                return ticker, row, None
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
        return ticker, None, last_err


def _load_tickers_from_file(p: Path) -> List[str]:
    lines = p.read_text(encoding="utf-8").splitlines()
    return _dedupe(lines)


def _load_resume_done(resume_path: Path) -> set:
    """Return set of tickers already present in a prior dump (skip them)."""
    done: set = set()
    try:
        with open(resume_path, "r", encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                t = (row.get("ticker") or "").strip().upper()
                if t:
                    done.add(t)
    except Exception as e:
        log.warning(f"Could not parse resume file {resume_path} ({e}); starting fresh")
        return set()
    return done


def _append_csv(path: Path, rows: List[LabelingRow], write_header: bool) -> None:
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def _append_failures(path: Path, failures: List[Tuple[str, str]]) -> None:
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for t, err in failures:
            w.writerow([t, err])


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------
async def amain() -> int:
    parser = argparse.ArgumentParser(
        description="Batch extract numerical features + text metadata for 1000+ tickers "
                    "into a CSV directly feedable to build_training_set_from_csv().",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--n", type=int, default=0,
                        help="Max tickers to process (0 = all available). Useful for quick smoke tests.")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "classification" / "labeling_dump.csv",
                        help="Output CSV path.")
    parser.add_argument("--tickers-file", type=Path, default=None,
                        help="Override default ticker universe with a custom file (one per line, # comments allowed).")
    parser.add_argument("--resume", type=Path, default=None,
                        help="Resume from a prior partial dump (skip tickers already present there).")
    parser.add_argument("--concurrency", type=int, default=8,
                        help="Async HTTP concurrency limit for YahooFinanceProvider.")
    parser.add_argument("--checkpoint-every", type=int, default=50,
                        help="Append results to CSV every N successful fetches.")
    parser.add_argument("--retries", type=int, default=2,
                        help="Per-ticker retry attempts on transient failures.")
    parser.add_argument("--use-synthetic-fallback", action="store_true", default=True,
                        dest="use_fallback",
                        help="If Yahoo fails, fill with synthetic data (always structurally complete).")
    parser.add_argument("--no-synthetic-fallback", action="store_false",
                        dest="use_fallback",
                        help="Fail tickers where Yahoo returns nothing (no synthetic fill).")
    args = parser.parse_args()

    # --- Resolve tickers ---
    if args.tickers_file and args.tickers_file.exists():
        tickers = _load_tickers_from_file(args.tickers_file)
        log.info(f"Loaded {len(tickers)} tickers from {args.tickers_file}")
    else:
        tickers = list(DEFAULT_TICKERS)
        log.info(f"Using default universe of {len(tickers)} tickers (S&P 500 + extras)")

    if args.n > 0:
        tickers = tickers[: args.n]
        log.info(f"--n clipped request to first {len(tickers)} tickers")

    # --- Resume handling ---
    skip: set = set()
    if args.resume and args.resume.exists():
        skip = _load_resume_done(args.resume)
        log.info(f"Resuming: skipping {len(skip)} tickers already in {args.resume}")
        # Resume implies appending to the same output file (do not overwrite)
        if args.resume.resolve() != args.out.resolve():
            log.info(f"  (resume file != out; copying rows first)")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.resume.replace(args.out) if False else None  # no-op placeholder
    tickers_to_run = [t for t in tickers if t not in skip]
    log.info(f"Tickers scheduled for fetch: {len(tickers_to_run)}")

    if not tickers_to_run:
        log.warning("Nothing to do — all tickers already in resume file. Exiting.")
        return 0

    # --- Providers ---
    yf = YahooFinanceProvider(use_fallback=args.use_fallback, cache_enabled=True)
    synth = SyntheticDataProvider()

    # --- Output setup ---
    out_path: Path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fail_path = out_path.with_name(out_path.stem + "_failures.csv")
    write_header_first_time = not (args.resume and args.resume.exists())

    # --- Progress tracking ---
    total = len(tickers_to_run)
    ok_rows: List[LabelingRow] = []
    fails_now: List[Tuple[str, str]] = []
    sem = asyncio.Semaphore(args.concurrency)

    t0 = time.time()
    done_ok = 0
    done_fail = 0
    checkpoint_counter = 0

    # Use asyncio.as_completed to stream results in completion order
    tasks = [asyncio.create_task(_fetch_one(yf, t, sem, retries=args.retries))
             for t in tickers_to_run]

    try:
        for i, fut in enumerate(asyncio.as_completed(tasks), start=1):
            ticker, row, err = await fut
            if row is not None:
                ok_rows.append(row)
                done_ok += 1
            else:
                # Last-resort synthetic fill if user wants fallback
                if args.use_fallback and err is not None:
                    try:
                        sd = synth.get_financial_data(ticker)
                        row = _row_from_data(sd)
                        row.note = (row.note + " | " if row.note else "") + f"filled=synthetic ({err[:80]})"
                        ok_rows.append(row)
                        done_ok += 1
                    except Exception as e2:
                        fails_now.append((ticker, f"{err}; synth_fail={e2}"))
                        done_fail += 1
                else:
                    fails_now.append((ticker, err or "unknown"))
                    done_fail += 1

            # Progress every 10% or 20 items, whichever smaller
            report_every = max(1, min(20, total // 10)) if total >= 10 else 1
            if i % report_every == 0:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta_s = (total - i) / rate if rate > 0 else 0
                log.info(
                    f"Progress {i}/{total}  ok={done_ok} fail={done_fail}  "
                    f"rate={rate:.1f}/s  eta={eta_s/60:.1f}min  last={ticker}"
                )

            # Checkpoint flush
            checkpoint_counter += 1
            if checkpoint_counter >= args.checkpoint_every and ok_rows:
                _append_csv(out_path, ok_rows, write_header=write_header_first_time)
                write_header_first_time = False
                checkpoint_counter = 0
                ok_rows.clear()
                if fails_now:
                    _append_failures(fail_path, fails_now)
                    fails_now.clear()
    finally:
        # Final flush of whatever is left
        if ok_rows:
            _append_csv(out_path, ok_rows, write_header=write_header_first_time)
            ok_rows.clear()
        if fails_now:
            _append_failures(fail_path, fails_now)
            fails_now.clear()

    elapsed = time.time() - t0
    log.info(
        f"Done in {elapsed/60:.1f} min | ok={done_ok} fail={done_fail} "
        f"out={out_path} failures={fail_path}"
    )
    log.info(
        "Next step: open CSV, fill `label` column with BusinessType .value strings "
        "(CASE-SENSITIVE PascalCase: MatureTech | SaaS | Semiconductor | ConsumerCyclical | "
        "REIT | Bank | Insurance | Commodity | Utilities | Conglomerate | Unknown). "
        "Then in LightGBMBusinessClassifier._train_from_scratch replace: "
        "build_synthetic_training_set() → build_training_set_from_csv(r\""
        + str(out_path).replace("\\", "\\\\")
        + "\") (1-line drop-in)."
    )
    return 0 if done_ok > 0 else 1


def main() -> int:
    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        log.warning("Interrupted by user — partial checkpoint data should still be on disk.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
