"""
data/reconciliation.py - 数据对账层 (Cross-field reconciliation)

Cross-validates the identity relationships among the headline market/financial
fields so that a single bad or differently-defined provider field (e.g. a
mis-scaled trailing P/E, or an annual-vs-TTM EBITDA used in EV/EBITDA) cannot
silently distort a valuation multiple.

Checked identities
------------------
  1. market_cap      ~ price × shares_outstanding
  2. enterprise_value~ market_cap + total_debt − cash
  3. TTM EPS         ~ TTM net_income / shares
  4. trailing P/E    ~ price / TTM EPS
  5. EV/EBITDA       ~ enterprise_value / TTM EBITDA
  6. P/B             ~ price / book_value_per_share
  7. EV/Sales        ~ enterprise_value / TTM revenue      (derived, reference)
  8. TTM FCF         ~ operating_cash_flow + capex
  9. market shares   ~ latest annual shares_outstanding
 10. EBITDA sanity   ~ EBITDA ≤ revenue  (flags D&A-inflated EBITDA)

Design notes
------------
* `reconcile()` is pure read-only: it never mutates FinancialData.
* Every check carries an auditable expected/actual pair plus a relative
  deviation, so the report can show exactly *why* a field was flagged.
* Tolerance is tight (5%) for accounting identities that must hold by
  construction, and looser (20%) for provider-stated ratios that legitimately
  differ in methodology (annual vs TTM windows, diluted vs basic shares).

Reverse validation (`apply_overrides`)
--------------------------------------
Flagging a contaminated provider field is not enough: if it is left in place,
downstream models keep reading the polluted base. `apply_overrides()` therefore
*corrects* provider-stated ratio fields whose deviation exceeds
`_OVERRIDE_TOLERANCE` (25%) by substituting the internally recomputed value,
and returns an auditable `OverrideLog`. Only fields whose internal derivation is
unambiguous (EV, trailing P/E, EV/EBITDA, P/B) are replaced; market cap and the
share count — which anchor the per-share basis — are never blindly overwritten
(see `apply_overrides` for the guarded share-count rule).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from config import get_logger
from data.models import FinancialData

log = get_logger("data.reconciliation")

# Identity tolerances -------------------------------------------------------
_TOL_IDENTITY = 0.05   # must hold by construction (market cap, EV, EPS, FCF)
_TOL_PROVIDER = 0.20   # provider-stated ratios: methodology may differ
_TOL_SHARES = 0.25     # share count drifts (buybacks / dilution) between periods

# Above this deviation a provider-stated field is not just flagged but REPLACED
# by the internally recomputed value (see apply_overrides).
_OVERRIDE_TOLERANCE = 0.25


@dataclass
class ReconciliationCheck:
    """One cross-validation between a provider field and an internally derived one."""

    name: str
    expected: Optional[float] = None      # internally recomputed value
    actual: Optional[float] = None        # provider-reported value
    rel_diff: Optional[float] = None      # (actual - expected) / |expected|
    tolerance: float = _TOL_IDENTITY
    unit: str = ""
    status: str = "NA"                    # OK | MISMATCH | NA
    note: str = ""

    @property
    def is_mismatch(self) -> bool:
        return self.status == "MISMATCH"

    def render(self, fmt) -> str:
        """fmt(value, unit) -> str; unit lets the caller format money vs shares vs x."""
        icon = {"OK": "✅", "MISMATCH": "⚠️", "NA": "➖"}.get(self.status, "•")
        if self.status == "NA":
            return f"{icon} {self.name}: 无法对账（{self.note or '数据缺失'}）"
        dev = f"{self.rel_diff:+.1%}" if self.rel_diff is not None else "n/a"
        line = (
            f"{icon} {self.name}: 供应商 {fmt(self.actual, self.unit)} vs 内部推算 "
            f"{fmt(self.expected, self.unit)}（偏差 {dev}，容差 ±{self.tolerance:.0%}）"
        )
        if self.note:
            line += f"\n    ‣ {self.note}"
        return line


@dataclass
class ShareCountEvidence:
    """The *independent* share-count calibers behind a per-share number (P0-3).

    A per-share valuation divides equity by a share count, but the market, the
    income statement and the balance sheet each carry a *differently defined*
    count:

      * ``market_implied``      — the count the market is pricing
        (``MarketData.shares_outstanding``). ``market_cap ÷ price`` reproduces
        this number, so it is **market-implied** — it is NOT evidence of the
        filing share count and must never be used to "verify" one.
      * ``filing_period_end``   — the period-end count stamped on the latest
        annual filing (basic shares on the balance sheet at year end).
      * ``diluted_weighted_avg``— the income-statement weighted-average count the
        TTM EPS denominator is built from (includes option/RSU dilution).

    When these disagree beyond ``tolerance`` a per-share conclusion cannot be
    stated as a fact; the EV-level result stays valid.
    """

    market_implied: Optional[float] = None
    market_source: str = ""
    filing_period_end: Optional[float] = None
    filing_period: Optional[str] = None
    diluted_weighted_avg: Optional[float] = None
    diluted_period: Optional[str] = None
    max_deviation: Optional[float] = None   # |market_implied − other| / market_implied
    consistent: bool = True
    tolerance: float = _TOL_SHARES
    notes: List[str] = field(default_factory=list)

    def to_lines(self, fmt) -> List[str]:
        def _s(v):  # noqa: ANN001 - local formatter
            return fmt(v, "股") if v is not None else "N/A"

        out = ["", "**🧮 股数三口径证据（Share Count Evidence）:**"]
        out.append(f"  • 市场隐含：{_s(self.market_implied)}（{self.market_source or 'N/A'}）")
        out.append(
            f"  • 财报期末：{_s(self.filing_period_end)}"
            f"（报告期 {self.filing_period or 'N/A'}）"
        )
        out.append(
            f"  • 稀释加权平均（EPS 分母）：{_s(self.diluted_weighted_avg)}"
            f"（报告期 {self.diluted_period or 'N/A'}）"
        )
        if self.max_deviation is not None:
            tag = "✅ 一致" if self.consistent else "⚠️ 超出容差"
            out.append(
                f"  • 最大偏差：{self.max_deviation:+.1%}"
                f"（容差 ±{self.tolerance:.0%}）→ {tag}"
            )
        for n in self.notes:
            out.append(f"    ‣ {n}")
        return out


def share_count_evidence(data: FinancialData) -> ShareCountEvidence:
    """Resolve the three independent share-count calibers for ``data`` (P0-3).

    Separates market-implied / filing-period-end / diluted-weighted-average
    counts so the audit compares *independent evidence sources* instead of
    treating ``market_cap ÷ price`` as proof of the filing share count.
    """
    mkt = data.market
    market_implied = mkt.shares_outstanding
    market_source = "MarketData 流通股数（市场隐含口径）"
    annual = data.annual_income[0] if data.annual_income else None
    filing_period_end = annual.shares_outstanding if annual is not None else None
    filing_period = annual.period_end if annual is not None else None
    ttm = data.ttm
    diluted = ttm.shares_outstanding if ttm is not None else None
    diluted_period = ttm.period_end if ttm is not None else None

    notes: List[str] = []
    if market_implied is None or market_implied <= 0:
        notes.append(
            "市场隐含股数缺失 → 无法比较口径（market_cap ÷ price 亦不可得，"
            "不得据此反推财报股数）"
        )
        return ShareCountEvidence(
            market_implied=market_implied, market_source=market_source,
            filing_period_end=filing_period_end, filing_period=filing_period,
            diluted_weighted_avg=diluted, diluted_period=diluted_period,
            max_deviation=None, consistent=True, notes=notes,
        )

    devs: List[float] = []
    if filing_period_end and filing_period_end > 0:
        devs.append(abs(filing_period_end - market_implied) / market_implied)
    if diluted and diluted > 0:
        devs.append(abs(diluted - market_implied) / market_implied)
    max_dev = max(devs) if devs else None
    consistent = max_dev is None or max_dev <= _TOL_SHARES

    notes.append(
        "市场隐含股数来自行情（market_cap ÷ price 仅为同口径复算），"
        "不能作为财报股数的证明"
    )
    if not consistent:
        notes.append(
            f"市场隐含与财报口径偏差 {max_dev:.1%} > ±{_TOL_SHARES:.0%} → "
            "每股结论需降级为方向性参考（EV 口径结果不受影响）"
        )
    return ShareCountEvidence(
        market_implied=market_implied, market_source=market_source,
        filing_period_end=filing_period_end, filing_period=filing_period,
        diluted_weighted_avg=diluted, diluted_period=diluted_period,
        max_deviation=max_dev, consistent=consistent, notes=notes,
    )


@dataclass
class ReconciliationReport:
    """Aggregated reconciliation result attached to FinancialData."""

    checks: List[ReconciliationCheck] = field(default_factory=list)
    # P0-3: the three independent share-count calibers behind every per-share
    # figure (market-implied / filing-period-end / diluted-weighted-average).
    share_count_evidence: Optional[ShareCountEvidence] = None

    @property
    def mismatches(self) -> List[ReconciliationCheck]:
        return [c for c in self.checks if c.is_mismatch]

    @property
    def n_ok(self) -> int:
        return sum(1 for c in self.checks if c.status == "OK")

    @property
    def n_na(self) -> int:
        return sum(1 for c in self.checks if c.status == "NA")

    def has_mismatch(self, name_substr: str) -> bool:
        return any(
            c.is_mismatch and name_substr.lower() in c.name.lower()
            for c in self.checks
        )

    def to_lines(self, fmt=lambda v, unit="": f"{v:.2f}" if v is not None else "N/A") -> List[str]:
        if not self.checks:
            return []
        out: List[str] = []
        out.append(
            f"  已校验 {len(self.checks)} 项 · 一致 {self.n_ok} · "
            f"不一致 {len(self.mismatches)} · 数据不足 {self.n_na}"
        )
        for c in self.checks:
            out.append("  " + c.render(fmt))
        if self.mismatches:
            out.append(
                "  _存在不一致项：相关倍数可能因供应商口径（年度 vs TTM、稀释股数等）"
                "而失真，估值中以内部推算为准或已标记为不可比。_"
            )
        if self.share_count_evidence is not None:
            out.extend(self.share_count_evidence.to_lines(fmt))
        return out


def _rel_diff(actual: Optional[float], expected: Optional[float]) -> Optional[float]:
    if actual is None or expected is None:
        return None
    if abs(expected) < 1e-9:
        return None
    return (actual - expected) / abs(expected)


def _check(
    name: str,
    actual: Optional[float],
    expected: Optional[float],
    tolerance: float,
    unit: str = "",
    na_note: str = "输入缺失",
    mismatch_note: str = "",
) -> ReconciliationCheck:
    rd = _rel_diff(actual, expected)
    if actual is None or expected is None or rd is None:
        return ReconciliationCheck(
            name=name, expected=expected, actual=actual, rel_diff=None,
            tolerance=tolerance, unit=unit, status="NA", note=na_note,
        )
    if abs(rd) <= tolerance:
        return ReconciliationCheck(
            name=name, expected=expected, actual=actual, rel_diff=rd,
            tolerance=tolerance, unit=unit, status="OK",
        )
    return ReconciliationCheck(
        name=name, expected=expected, actual=actual, rel_diff=rd,
        tolerance=tolerance, unit=unit, status="MISMATCH", note=mismatch_note,
    )


def reconcile(data: FinancialData) -> ReconciliationReport:
    """Run the full cross-field reconciliation for a FinancialData bundle."""
    mkt = data.market
    ttm = data.ttm
    checks: List[ReconciliationCheck] = []

    price = mkt.current_price
    shares = mkt.shares_outstanding
    mcap = mkt.market_cap
    debt = mkt.total_debt
    cash = mkt.cash_and_equivalents
    ev = mkt.enterprise_value

    # --- 1. market cap = price × shares -------------------------------------
    if price is not None and shares is not None and shares > 0:
        checks.append(_check(
            "市值 ≈ 价格 × 股数", mcap, price * shares, _TOL_IDENTITY, "USD",
            na_note="市值缺失",
            mismatch_note="供应商市值与 价格×股数 不一致，股数口径可能不同（基本/稀释）",
        ))
    else:
        checks.append(_check("市值 ≈ 价格 × 股数", mcap, None, _TOL_IDENTITY, "USD"))

    # --- 2. EV = market cap + debt − cash -----------------------------------
    if mcap is not None and debt is not None and cash is not None:
        checks.append(_check(
            "企业价值 ≈ 市值 + 债务 − 现金", ev, mcap + debt - cash, _TOL_IDENTITY, "USD",
            na_note="EV 缺失",
            mismatch_note="供应商 EV 与 市值+净债 不一致，可能包含少数股东权益/养老负债",
        ))
    else:
        checks.append(_check("企业价值 ≈ 市值 + 债务 − 现金", ev, None, _TOL_IDENTITY, "USD"))

    # --- 3 & 4. EPS and trailing P/E ---------------------------------------
    ttm_eps = ttm.eps if ttm is not None else None
    eps_derived = None
    if ttm is not None and ttm.net_income is not None and shares and shares > 0:
        eps_derived = ttm.net_income / shares
    checks.append(_check(
        "TTM EPS ≈ 净利润 / 股数", ttm_eps, eps_derived, _TOL_PROVIDER, "USD/股",
        na_note="TTM EPS 或净利润缺失",
        mismatch_note="TTM EPS 与 净利润/股数 不一致，可能使用了非 GAAP 或摊薄口径",
    ))

    pe_provider = mkt.trailing_pe
    pe_derived = None
    eps_for_pe = ttm_eps if (ttm_eps is not None and ttm_eps > 0) else eps_derived
    if price is not None and eps_for_pe is not None and eps_for_pe > 0:
        pe_derived = price / eps_for_pe

    # Direction-aware mismatch wording. A provider P/E that disagrees with
    # price / its own TTM EPS has two very different root causes:
    #   * provider P/E < price/EPS → the provider's P/E implies a HIGHER EPS than
    #     the reported GAAP EPS — the routine "adjusted / normalized EPS" basis
    #     (common for nearly every large cap; NOT earnings instability)
    #   * provider P/E > price/EPS → the provider implies a LOWER EPS (stale
    #     trailing window, or a fully-diluted vs basic basis)
    # Blanket-calling both "盈利基数极不稳定" mislabels a routine accounting-basis
    # difference as a data-quality red flag.
    _pe_mismatch_note = "供应商 P/E 与 价格/TTM EPS 不一致（口径可能不同）"
    if (pe_provider is not None and pe_provider > 0
            and pe_derived is not None and pe_derived > 0):
        if pe_provider < pe_derived * (1 - _TOL_PROVIDER):
            _pe_mismatch_note = (
                f"供应商 P/E ({pe_provider:.1f}x) 明显低于 价格/TTM GAAP EPS 隐含的 "
                f"{pe_derived:.1f}x → 供应商 P/E 隐含的 EPS 高于报告口径，"
                "通常为『调整后（non-GAAP）/正常化 EPS』差异（非盈利不稳定）；"
                "两种口径不可混用，P/E 估值应以统一口径复核"
            )
        elif pe_provider > pe_derived * (1 + _TOL_PROVIDER):
            _pe_mismatch_note = (
                f"供应商 P/E ({pe_provider:.1f}x) 明显高于 价格/TTM EPS 隐含的 "
                f"{pe_derived:.1f}x → 供应商可能使用旧口径/摊薄股数，或盈利已下滑；"
                "P/E 估值应以统一口径复核"
            )
    checks.append(_check(
        "滚动 P/E ≈ 价格 / TTM EPS", pe_provider, pe_derived, _TOL_PROVIDER, "x",
        na_note="P/E 或 EPS 缺失/非正",
        mismatch_note=_pe_mismatch_note,
    ))

    # --- 5. EV/EBITDA -------------------------------------------------------
    ebitda = ttm.ebitda if ttm is not None else None
    evebitda_derived = None
    if ev is not None and ebitda is not None and ebitda > 0:
        evebitda_derived = ev / ebitda
    checks.append(_check(
        "EV/EBITDA ≈ EV / TTM EBITDA", mkt.ev_to_ebitda, evebitda_derived, _TOL_PROVIDER, "x",
        na_note="EV/EBITDA、EV 或 EBITDA 缺失/非正",
        mismatch_note="供应商 EV/EBITDA 与 EV/TTM EBITDA 不符 → 多为供应商用年度 EBITDA，口径不一致",
    ))

    # --- 6. P/B -------------------------------------------------------------
    bvps = mkt.book_value_per_share
    pb_derived = price / bvps if (price is not None and bvps and bvps > 0) else None
    checks.append(_check(
        "P/B ≈ 价格 / 每股账面价值", mkt.price_to_book, pb_derived, _TOL_PROVIDER, "x",
        na_note="P/B 或每股账面价值缺失",
        mismatch_note="供应商 P/B 与 价格/每股账面价值 不一致",
    ))

    # --- 7. EV/Sales (derived reference) -----------------------------------
    revenue = ttm.revenue if ttm is not None else None
    ev_sales_derived = ev / revenue if (ev is not None and revenue and revenue > 0) else None
    if ev_sales_derived is not None:
        checks.append(ReconciliationCheck(
            name="EV/Sales (内部推算)", expected=ev_sales_derived,
            actual=ev_sales_derived, rel_diff=0.0, tolerance=_TOL_PROVIDER,
            unit="x", status="OK",
            note="供应商未提供 EV/Sales，估值引擎按 EV/TTM 营收推算",
        ))
    else:
        checks.append(_check("EV/Sales (内部推算)", None, None, _TOL_PROVIDER, "x",
                             na_note="EV 或营收缺失"))

    # --- 8. FCF = OCF + capex ----------------------------------------------
    if ttm is not None and ttm.operating_cash_flow is not None and ttm.capex is not None:
        checks.append(_check(
            "TTM FCF ≈ 经营现金流 + 资本开支", ttm.free_cash_flow,
            ttm.operating_cash_flow + ttm.capex, _TOL_IDENTITY, "USD",
            na_note="FCF / OCF / capex 缺失",
            mismatch_note="FCF 与 经营现金流+资本开支 不一致",
        ))
    else:
        checks.append(_check("TTM FCF ≈ 经营现金流 + 资本开支", None, None,
                             _TOL_IDENTITY, "USD"))

    # --- 9. share count consistency (market vs latest annual) --------------
    # P0-3: this compares two INDEPENDENT sources — the market-implied count and
    # the filing period-end count. ``market_cap ÷ price`` reproduces the market
    # count and is therefore NOT a third source / not proof of the filing count;
    # the three-caliber evidence is attached separately (ShareCountEvidence).
    annual_shares = None
    if data.annual_income:
        annual_shares = data.annual_income[0].shares_outstanding
    checks.append(_check(
        "流通股数 ≈ 最新年报股数", shares, annual_shares, _TOL_SHARES, "股",
        na_note="股数缺失",
        mismatch_note=(
            "市场隐含股数与最新年报期末股数偏差较大（增发/回购/摊薄）；"
            "两者为独立证据源，每股指标口径需注意（market_cap÷price 不构成财报股数的证明）"
        ),
    ))

    # --- 10. EBITDA plausibility (EBITDA/revenue ratio must be ≤ 100%) ------
    if ebitda is not None and revenue is not None and revenue > 0:
        margin = ebitda / revenue
        checks.append(ReconciliationCheck(
            name="EBITDA/营收 比率 ≤ 100%", expected=1.0, actual=margin,
            rel_diff=margin - 1.0, tolerance=0.0, unit="",
            status="MISMATCH" if margin > 1.0 else "OK",
            note=(
                f"EBITDA/营收 = {margin:.0%} > 100%：折旧摊销异常巨大（重资产折旧），"
                f"EV/EBITDA 与 EBITDA 在此类公司上不可比"
                if margin > 1.0 else f"EBITDA/营收 = {margin:.0%}"
            ),
        ))

    report = ReconciliationReport(checks=checks)
    # P0-3: attach the three independent share-count calibers so a per-share
    # conclusion can be gated on evidence-source agreement, not on a single
    # (market-implied) number masquerading as the filing count.
    try:
        report.share_count_evidence = share_count_evidence(data)
    except Exception as e:  # evidence must never break reconciliation
        log.warning("share_count_evidence failed for %s: %s", data.ticker, e)
    if report.mismatches:
        log.info(
            "reconcile %s: %d mismatch(es) — %s",
            data.ticker, len(report.mismatches),
            "; ".join(c.name for c in report.mismatches),
        )
    return report


# ---------------------------------------------------------------------------
# Reverse validation — correct provider fields that materially disagree
# ---------------------------------------------------------------------------

@dataclass
class OverrideRecord:
    """One provider field replaced by (or deliberately left to) an internal value."""

    field: str
    check_name: str
    provider_value: Optional[float]
    internal_value: Optional[float]
    rel_diff: Optional[float] = None
    unit: str = ""
    applied: bool = False
    reason: str = ""

    def render(self, fmt) -> str:
        if not self.applied:
            return (
                f"➖ {self.field}: 仅标注（未覆盖）— {self.reason}"
                f"（供应商 {fmt(self.provider_value, self.unit)} vs 内部 "
                f"{fmt(self.internal_value, self.unit)}）"
            )
        dev = f"{self.rel_diff:+.1%}" if self.rel_diff is not None else "n/a"
        return (
            f"✅ {self.field}: 已自动改用内部推算值 {fmt(self.internal_value, self.unit)}"
            f"（原供应商 {fmt(self.provider_value, self.unit)}，偏差 {dev} > ±{_OVERRIDE_TOLERANCE:.0%}）"
        )


@dataclass
class OverrideLog:
    """Audit trail of the reverse-validation corrections applied to FinancialData."""

    records: List[OverrideRecord] = field(default_factory=list)

    @property
    def applied(self) -> List[OverrideRecord]:
        return [r for r in self.records if r.applied]

    @property
    def n_applied(self) -> int:
        return len(self.applied)

    def to_lines(self, fmt) -> List[str]:
        if not self.records:
            return []
        out: List[str] = ["", "**🩹 对账自动修正（偏差 > 25% 时改用内部推算值）:**"]
        for r in self.records:
            out.append("  " + r.render(fmt))
        if self.n_applied:
            out.append(
                "  _已对上述字段改用内部推算值，下游估值不再读取被污染的供应商口径；"
                "修正前后对照见上。_"
            )
        return out


# check name → (MarketData attribute, human label). Only provider-stated ratios
# whose internal recomputation is unambiguous are eligible for replacement.
_OVERRIDE_FIELDS = {
    "企业价值 ≈ 市值 + 债务 − 现金": ("enterprise_value", "企业价值 (EV)"),
    "滚动 P/E ≈ 价格 / TTM EPS": ("trailing_pe", "滚动 P/E"),
    "EV/EBITDA ≈ EV / TTM EBITDA": ("ev_to_ebitda", "EV/EBITDA"),
    "P/B ≈ 价格 / 每股账面价值": ("price_to_book", "P/B"),
}


def apply_overrides(data: FinancialData, report: Optional[ReconciliationReport] = None) -> OverrideLog:
    """Replace provider fields that disagree with the internal value by >25%.

    This is the *write* counterpart to `reconcile()`. It closes the loop the user
    flagged: previously a mismatch was only rendered as a warning while the
    polluted provider number kept flowing downstream. Now the internally derived
    value is substituted and the substitution is logged.

    Guards:
      * Only provider-stated ratios (EV, trailing P/E, EV/EBITDA, P/B) are
        replaced — market cap stays the anchor.
      * The share count is never blindly overwritten: when the market-cap
        identity already holds, the market share count is internally consistent
        and the deviation is a legitimate basis difference (equity issuance /
        buyback / multi-class) — we annotate, we do not override. Only when the
        share count ALSO breaks the market-cap identity do we re-anchor shares
        to market_cap / price.
    """
    report = report if report is not None else reconcile(data)
    mkt = data.market
    override_log = OverrideLog()
    by_name = {c.name: c for c in report.checks}

    for c in report.checks:
        if not c.is_mismatch or c.rel_diff is None or c.expected is None:
            continue
        if abs(c.rel_diff) <= _OVERRIDE_TOLERANCE:
            continue
        target = _OVERRIDE_FIELDS.get(c.name)
        if target is None:
            continue
        attr, label = target
        old = getattr(mkt, attr, None)
        setattr(mkt, attr, float(c.expected))
        override_log.records.append(OverrideRecord(
            field=label, check_name=c.name,
            provider_value=old, internal_value=float(c.expected),
            rel_diff=c.rel_diff, unit=c.unit, applied=True,
            reason=f"供应商 {label} 偏差 {c.rel_diff:+.1%} 超过 ±{_OVERRIDE_TOLERANCE:.0%}",
        ))
        log.info(
            "override %s %s: provider=%s -> internal=%s (%+.1f%%)",
            data.ticker, label, old, c.expected, c.rel_diff * 100.0,
        )

    # ---- Share count: guarded decision (annotate vs re-anchor) -------------
    sh = by_name.get("流通股数 ≈ 最新年报股数")
    if sh is not None and sh.is_mismatch and sh.rel_diff is not None \
            and abs(sh.rel_diff) > _OVERRIDE_TOLERANCE:
        mcap_check = by_name.get("市值 ≈ 价格 × 股数")
        identity_ok = mcap_check is not None and not mcap_check.is_mismatch
        price = mkt.current_price
        mcap = mkt.market_cap
        if identity_ok or not (price and price > 0 and mcap and mcap > 0):
            override_log.records.append(OverrideRecord(
                field="流通股数", check_name=sh.name,
                provider_value=sh.actual, internal_value=sh.expected,
                rel_diff=sh.rel_diff, unit=sh.unit, applied=False,
                reason=("行情股数与市值恒等式自洽（市值 = 价格 × 股数），"
                        "差异源于年报口径（增发/回购/多类别股）；以行情股数为准，"
                        "不覆盖以避免破坏市值锚定"),
            ))
        else:
            new_shares = float(mcap) / float(price)
            old = mkt.shares_outstanding
            mkt.shares_outstanding = new_shares
            override_log.records.append(OverrideRecord(
                field="流通股数", check_name=sh.name,
                provider_value=old, internal_value=new_shares,
                rel_diff=sh.rel_diff, unit=sh.unit, applied=True,
                reason="行情股数与市值恒等式不一致 → 以 市值 / 价格 反推股数作为内部推算值",
            ))
            log.info(
                "override %s shares: provider=%s -> internal=%s (identity broken)",
                data.ticker, old, new_shares,
            )

    return override_log


__all__ = [
    "ReconciliationCheck",
    "ReconciliationReport",
    "ShareCountEvidence",
    "share_count_evidence",
    "reconcile",
    "OverrideRecord",
    "OverrideLog",
    "apply_overrides",
]
