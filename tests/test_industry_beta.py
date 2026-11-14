"""H-03 lock: bottom-up (peer-derived) unlevered industry beta.

Pins the Hamada un-levering math, the peer-median aggregation, the "never
fabricate" floor (``None`` below 3 usable peers), the target-ticker exclusion,
and the per-industry cache. Peer listing and beta fetching are injected, so the
suite never touches the network.
"""
from __future__ import annotations

import json

import pytest

from data.industry_beta import (
    IndustryBetaResult,
    PeerBeta,
    _cash_adjust,
    _coerce_segments,
    _damodaran_lookup,
    _default_segment_industry_resolver,
    _relever,
    _unlever,
    derive_bottom_up_beta,
    derive_industry_unlevered_beta,
    derive_segment_level_beta,
    get_companies_by_business_identity,
)
from data.models import FinancialData, FinancialStatement, MarketData
from valuation.wacc import WaccCalculator


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("BOTTOM_UP_BETA", raising=False)


def _lister(tickers):
    return lambda industry, sector: list(tickers)


def _fetcher(table):
    return lambda ticker: table.get(ticker)


def test_hamada_unlevering_math():
    # β_u = β_L / (1 + (1 − t)·D/E); t = 0.21.
    assert _unlever(1.5, 0.0, 0.21) == pytest.approx(1.5)
    assert _unlever(1.5, 0.5, 0.21) == pytest.approx(1.5 / 1.395)
    # Negative D/E is clamped to 0 (a net-cash peer is not a levered proxy).
    assert _unlever(1.5, -0.5, 0.21) == pytest.approx(1.5)


def test_median_of_unlevered_betas(tmp_path):
    table = {"A": (1.0, 0.0), "B": (2.0, 0.0), "C": (3.0, 0.0)}
    out = derive_industry_unlevered_beta(
        "TGT", "Technology", "Semiconductors",
        peer_lister=_lister(["A", "B", "C"]),
        beta_fetcher=_fetcher(table),
        cache_path=tmp_path / "b.json",
    )
    assert out == pytest.approx(2.0)


def test_hamada_applied_across_peers(tmp_path):
    table = {
        "A": (1.0, 0.0),
        "B": (1.5, 0.5),
        "C": (2.0, 1.0),
        "D": (1.2, 0.2),
    }
    out = derive_industry_unlevered_beta(
        "TGT", "Technology", "Semiconductors",
        peer_lister=_lister(["A", "B", "C", "D"]),
        beta_fetcher=_fetcher(table),
        cache_path=tmp_path / "b.json",
    )
    unlevered = sorted([1.0, 1.5 / 1.395, 2.0 / 1.79, 1.2 / 1.158])
    expected = (unlevered[1] + unlevered[2]) / 2
    assert out == pytest.approx(round(expected, 4))


def test_target_ticker_excluded_from_peers(tmp_path):
    # The target's own (wildly levered) beta must not pollute the median.
    table = {"TGT": (5.0, 2.0), "A": (1.0, 0.0), "B": (1.0, 0.0), "C": (1.0, 0.0)}
    out = derive_industry_unlevered_beta(
        "TGT", "Technology", "Semiconductors",
        peer_lister=_lister(["TGT", "A", "B", "C"]),
        beta_fetcher=_fetcher(table),
        cache_path=tmp_path / "b.json",
    )
    assert out == pytest.approx(1.0)


def test_returns_none_below_min_peers(tmp_path):
    table = {"A": (1.0, 0.0), "B": (2.0, 0.0)}  # only 2 usable
    out = derive_industry_unlevered_beta(
        "TGT", "Technology", "Semiconductors",
        peer_lister=_lister(["A", "B", "C"]),
        beta_fetcher=_fetcher(table),  # C has no row -> unusable
        cache_path=tmp_path / "b.json",
    )
    assert out is None


def test_returns_none_when_industry_missing(tmp_path):
    out = derive_industry_unlevered_beta(
        "TGT", "Technology", None,
        peer_lister=_lister(["A", "B", "C"]),
        beta_fetcher=_fetcher({"A": (1.0, 0.0)}),
        cache_path=tmp_path / "b.json",
    )
    assert out is None


def test_offline_returns_none_without_touching_lister(tmp_path):
    calls = []

    def lister(industry, sector):
        calls.append(industry)
        return ["A", "B", "C"]

    out = derive_industry_unlevered_beta(
        "TGT", "Technology", "Semiconductors",
        peer_lister=lister,
        beta_fetcher=_fetcher({"A": (1.0, 0.0)}),
        cache_path=tmp_path / "b.json",
        offline=True,
    )
    assert out is None
    assert calls == []


def test_env_flag_disables_bottom_up(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTTOM_UP_BETA", "0")
    out = derive_industry_unlevered_beta(
        "TGT", "Technology", "Semiconductors",
        peer_lister=_lister(["A", "B", "C"]),
        beta_fetcher=_fetcher({"A": (1.0, 0.0), "B": (1.0, 0.0), "C": (1.0, 0.0)}),
        cache_path=tmp_path / "b.json",
    )
    assert out is None


def test_peer_lister_failure_returns_none(tmp_path):
    def boom(industry, sector):
        raise RuntimeError("network down")

    out = derive_industry_unlevered_beta(
        "TGT", "Technology", "Semiconductors",
        peer_lister=boom,
        beta_fetcher=_fetcher({"A": (1.0, 0.0)}),
        cache_path=tmp_path / "b.json",
    )
    assert out is None


def test_result_cached_per_industry(tmp_path):
    cache = tmp_path / "b.json"
    calls = []

    def lister(industry, sector):
        calls.append(industry)
        return ["A", "B", "C"]

    kwargs = dict(
        peer_lister=lister,
        beta_fetcher=_fetcher({"A": (1.0, 0.0), "B": (1.0, 0.0), "C": (1.0, 0.0)}),
        cache_path=cache,
    )
    first = derive_industry_unlevered_beta("T1", "Technology", "Semiconductors", **kwargs)
    second = derive_industry_unlevered_beta("T2", "Technology", "Semiconductors", **kwargs)
    assert first == second == pytest.approx(1.0)
    assert calls == ["Semiconductors"]  # second call served from cache
    assert cache.exists()

    # A fresh process reads the same value off disk with no lister call.
    third = derive_industry_unlevered_beta(
        "T3", "Technology", "Semiconductors",
        peer_lister=_lister([]), beta_fetcher=_fetcher({}), cache_path=cache,
    )
    assert third == pytest.approx(1.0)
    assert json.loads(cache.read_text(encoding="utf-8"))["Technology|Semiconductors"]["n_peers"] == 3


def test_max_peers_cap_respected(tmp_path):
    table = {f"P{i}": (1.0, 0.0) for i in range(10)}
    seen = []

    def fetcher(ticker):
        seen.append(ticker)
        return table.get(ticker)

    derive_industry_unlevered_beta(
        "TGT", "Technology", "Semiconductors",
        peer_lister=_lister([f"P{i}" for i in range(10)]),
        beta_fetcher=fetcher,
        max_peers=4,
        cache_path=tmp_path / "b.json",
    )
    assert len(seen) == 4


def test_note_is_human_readable():
    note = IndustryBetaResult(beta_unlevered=1.0558, n_peers=4, industry="Semiconductors").note()
    assert "1.06" in note
    assert "4" in note
    assert "去杠杆" in note


# ---------------------------------------------------------------------------
# M-34: cash-adjust / relever math
# ---------------------------------------------------------------------------
def test_cash_adjust_math():
    # β_business = β_firm / (1 − Cash/Firm); missing cash passes through.
    assert _cash_adjust(1.0, None) == pytest.approx(1.0)
    assert _cash_adjust(1.0, 0.0) == pytest.approx(1.0)
    assert _cash_adjust(1.0, 0.20) == pytest.approx(1.25)
    # A >90% cash shell is capped: the operating weight floor is 10%.
    assert _cash_adjust(1.0, 0.95) == pytest.approx(1.0 / 0.10)


def test_relever_math():
    # Hamada forward: β_L = β_u × (1 + (1 − t)·D/E); t = 0.21.
    assert _relever(1.0, 0.0, 0.21) == pytest.approx(1.0)
    assert _relever(1.0, 0.5, 0.21) == pytest.approx(1.395)
    assert _relever(1.0, -0.5, 0.21) == pytest.approx(1.0)  # net-cash clamped to 0


# ---------------------------------------------------------------------------
# M-34: three-level business-identity screen
# ---------------------------------------------------------------------------
def test_screen_l1_same_subindustry_without_model_resolver():
    screen = get_companies_by_business_identity(
        "Semiconductors", sector="Technology",
        industry_lister=_lister(["A", "B", "C"]),
    )
    assert screen.level == 1
    assert screen.tickers == ["A", "B", "C"]
    assert "未按模型过滤" in screen.rationale


def test_screen_l1_filters_by_business_model():
    models = {"A": "SaaS", "B": "SaaS", "C": "SaaS", "D": "Foundry"}
    screen = get_companies_by_business_identity(
        "Software—Application", "SaaS", sector="Technology",
        industry_lister=_lister(["A", "B", "C", "D"]),
        model_resolver=lambda t: models[t],
    )
    assert screen.level == 1
    assert screen.tickers == ["A", "B", "C"]
    assert "SaaS" in screen.rationale


def test_screen_escalates_to_l2_when_l1_thin():
    # Only 2 same-industry peers (< 3) → escalate to adjacent industries.
    screen = get_companies_by_business_identity(
        "Semiconductors", sector="Technology",
        industry_lister=_lister(["A", "B"]),
        neighbor_lister=_lister(["C", "D", "E"]),
    )
    assert screen.level == 2
    assert set(screen.tickers) == {"C", "D", "E"}
    assert "L2" in screen.rationale


def test_screen_l2_filters_by_economic_profile():
    class _EP:
        def __init__(self, capex_heavy):
            self.is_capex_heavy = capex_heavy
            self.is_loss_making = False
            self.is_asset_light = not capex_heavy

    profiles = {
        "C": _EP(True), "D": _EP(True), "E": _EP(False),
        "F": _EP(True), "G": _EP(False),
    }
    screen = get_companies_by_business_identity(
        "Semiconductors", sector="Technology",
        economic_profile=_EP(True),
        industry_lister=_lister(["A", "B"]),
        neighbor_lister=_lister(["C", "D", "E", "F", "G"]),
        profile_resolver=lambda t: profiles[t],
    )
    assert screen.level == 2
    assert set(screen.tickers) == {"C", "D", "F"}  # only capex-heavy peers survive
    assert "相似经济特征" in screen.rationale


def test_screen_l3_when_no_peers():
    screen = get_companies_by_business_identity(
        "Semiconductors", sector="Technology",
        industry_lister=_lister([]),
        neighbor_lister=_lister([]),
    )
    assert screen.level == 3
    assert screen.tickers == []


def test_screen_l3_when_subindustry_blank():
    screen = get_companies_by_business_identity("", sector="Technology")
    assert screen.level == 3
    assert screen.tickers == []


# ---------------------------------------------------------------------------
# M-34: L3 Damodaran benchmark lookup
# ---------------------------------------------------------------------------
def _bench(tmp_path, industries):
    p = tmp_path / "dm.json"
    p.write_text(json.dumps({"industries": industries}), encoding="utf-8")
    return p


def test_damodaran_lookup_resolves_alias(tmp_path):
    p = _bench(tmp_path, {
        "Semiconductor": {"unlevered_beta": 1.49, "unlevered_beta_cash_adjusted": 1.50},
    })
    # "Semiconductors" (Yahoo) → "Semiconductor" (Damodaran) via the alias table.
    assert _damodaran_lookup("Semiconductors", p) == pytest.approx((1.49, 1.50))


def test_damodaran_lookup_unmatched_returns_none(tmp_path):
    p = _bench(tmp_path, {
        "Semiconductor": {"unlevered_beta": 1.49, "unlevered_beta_cash_adjusted": 1.50},
    })
    assert _damodaran_lookup("Totally Fictional Industry ZZ", p) is None


def test_damodaran_lookup_missing_file_returns_none(tmp_path):
    assert _damodaran_lookup("Semiconductors", tmp_path / "absent.json") is None


def test_bundled_damodaran_snapshot_is_present():
    # The shipped snapshot must resolve a common industry and never a bogus one.
    assert _damodaran_lookup("Semiconductors") is not None
    assert _damodaran_lookup("This Industry Does Not Exist 12345") is None


# ---------------------------------------------------------------------------
# M-34: full derive_bottom_up_beta chain
# ---------------------------------------------------------------------------
def test_bottom_up_full_chain_with_cash_and_relever(tmp_path):
    import statistics

    table = {"A": (1.0, 0.0, 0.20), "B": (1.5, 0.5, 0.30), "C": (2.0, 1.0, 0.40)}
    res = derive_bottom_up_beta(
        "TGT", "Technology", "Semiconductors",
        target_d2e=0.5,
        peer_lister=_lister(["A", "B", "C"]),
        beta_fetcher=_fetcher(table),
        cache_path=tmp_path / "b.json",
    )
    assert res is not None
    assert res.level == 1 and res.n_peers == 3 and res.source == "peer-median"

    median_unlev = statistics.median([1.0, 1.5 / 1.395, 2.0 / 1.79])
    assert res.beta_unlevered == pytest.approx(round(median_unlev, 4))
    assert res.cash_to_firm == pytest.approx(0.30)
    assert res.beta_cash_adjusted == pytest.approx(round(median_unlev / 0.70, 4))
    assert res.beta_relevered == pytest.approx(round(median_unlev / 0.70 * 1.395, 4))
    assert len(res.peer_levered or []) == 3
    assert len(res.peer_unlevered or []) == 3


def test_bottom_up_l3_benchmark_fallback(tmp_path):
    p = _bench(tmp_path, {
        "Semiconductor": {"unlevered_beta": 1.49, "unlevered_beta_cash_adjusted": 1.50},
    })
    res = derive_bottom_up_beta(
        "TGT", "Technology", "Semiconductors",
        target_d2e=0.2,
        peer_lister=_lister([]),
        neighbor_lister=_lister([]),
        beta_fetcher=_fetcher({}),
        cache_path=tmp_path / "b.json",
        benchmark_path=p,
    )
    assert res is not None
    assert res.level == 3 and res.n_peers == 0
    assert res.source == "damodaran-benchmark"
    assert res.beta_unlevered == pytest.approx(1.49)
    assert res.beta_cash_adjusted == pytest.approx(1.50)
    assert res.beta_relevered == pytest.approx(round(1.50 * (1 + 0.79 * 0.2), 4))


def test_bottom_up_returns_none_when_no_level_resolves(tmp_path):
    res = derive_bottom_up_beta(
        "TGT", "Technology", "No Such Industry 999",
        peer_lister=_lister([]),
        neighbor_lister=_lister([]),
        beta_fetcher=_fetcher({}),
        cache_path=tmp_path / "b.json",
    )
    assert res is None


def test_bottom_up_chain_dict_is_complete(tmp_path):
    res = derive_bottom_up_beta(
        "TGT", "Technology", "Semiconductors",
        target_d2e=0.5,
        peer_lister=_lister(["A", "B", "C"]),
        beta_fetcher=_fetcher({"A": (1.0, 0.0), "B": (1.0, 0.0), "C": (1.0, 0.0)}),
        cache_path=tmp_path / "b.json",
    )
    assert res is not None
    chain = res.to_chain()
    for key in (
        "level", "n_peers", "source", "industry", "peer_median_unlevered",
        "cash_adjusted", "relevered", "target_d2e", "tax_rate", "as_of", "note",
    ):
        assert key in chain
    assert chain["level"] == 1
    assert chain["n_peers"] == 3


def test_bottom_up_accepts_peerbeta_objects(tmp_path):
    table = {
        "A": PeerBeta(1.0, 0.0, 0.10),
        "B": PeerBeta(1.0, 0.0, 0.20),
        "C": PeerBeta(1.0, 0.0, 0.30),
    }
    res = derive_bottom_up_beta(
        "TGT", "Technology", "Semiconductors",
        peer_lister=_lister(["A", "B", "C"]),
        beta_fetcher=_fetcher(table),
        cache_path=tmp_path / "b.json",
    )
    assert res is not None
    assert res.cash_to_firm == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# M-34: CAPM priority — bottom-up first, regression fallback (wacc.py)
# ---------------------------------------------------------------------------
def _fd(market: MarketData) -> FinancialData:
    ttm = FinancialStatement(period_end="TTM", revenue=1e9, shares_outstanding=1e9)
    return FinancialData(
        ticker="T", annual_income=[ttm], annual_balance_sheet=[], ttm=ttm, market=market,
    )


def _market(**kwargs) -> MarketData:
    base = dict(
        current_price=100.0, market_cap=1e10, total_debt=1e9,
        risk_free_rate=0.04, equity_risk_premium=0.055,
    )
    base.update(kwargs)
    return MarketData(**base)


def test_capm_prefers_bottom_up_beta():
    market = _market(
        beta=1.40, bottom_up_beta=0.90,
        bottom_up_beta_chain={"level": 1, "note": "CHAIN-NOTE"},
    )
    wb = WaccCalculator().calculate(_fd(market))
    assert wb.beta == pytest.approx(0.90)
    assert wb.beta_bottom_up == pytest.approx(0.90)
    assert "bottom-up" in wb.sources["β"]
    assert "L1" in wb.sources["β"]
    assert "CHAIN-NOTE" in wb.beta_transparency_note()


def test_capm_falls_back_to_regression_beta():
    market = _market(beta=1.40)  # no bottom-up source
    wb = WaccCalculator().calculate(_fd(market))
    assert wb.beta == pytest.approx(1.40)
    assert wb.beta_bottom_up is None
    assert "3Y monthly" in wb.sources["β"]
    assert "N/A" in wb.beta_transparency_note()


def test_capm_bottom_up_winsorized_above_band():
    market = _market(
        beta=1.40, bottom_up_beta=3.20, bottom_up_beta_chain={"level": 2},
    )
    wb = WaccCalculator().calculate(_fd(market))
    assert wb.beta == pytest.approx(2.50)          # clamped at BETA_WINSOR_HI
    assert wb.beta_bottom_up == pytest.approx(3.20)  # raw bottom-up preserved
    assert "bottom-up" in wb.sources["β"]


# ---------------------------------------------------------------------------
# M-35: segment-level beta — weight segments, run the chain per segment
# ---------------------------------------------------------------------------
def _seg_resolver(mapping):
    """label → industry (injected, offline)."""
    return lambda label: mapping.get(label)


def _seg_provider(table):
    """industry → IndustryBetaResult for the segment chain (injected, offline)."""
    def _p(ticker, sector, industry, *, target_d2e=None,
           target_tax_rate=None, benchmark_path=None):
        return table.get(industry)
    return _p


def _seg_result(beta_u, level=1, source="peer-median"):
    return IndustryBetaResult(
        beta_unlevered=beta_u, n_peers=3, industry="seg", level=level, source=source,
    )


def test_segment_weights_sum_beta_unlevered():
    # β_u_company = Σ (w_i / coverage) · β_u_i  = 0.6·1.2 + 0.4·0.8 = 1.04
    res = derive_segment_level_beta(
        "AMZN",
        [("Semiconductors", 0.6), ("Cloud", 0.4)],
        segment_industry_resolver=_seg_resolver(
            {"Semiconductors": "Semiconductors", "Cloud": "Information Technology Services"}
        ),
        beta_provider=_seg_provider({
            "Semiconductors": _seg_result(1.2),
            "Information Technology Services": _seg_result(0.8),
        }),
    )
    assert res is not None
    assert res.level == 0
    assert res.source == "segment-weighted"
    assert res.n_peers == 2
    assert res.beta_unlevered == pytest.approx(1.04)
    # Cash absent + no target D/E → both steps pass the unlevered β through.
    assert res.beta_cash_adjusted == pytest.approx(1.04)
    assert res.beta_relevered == pytest.approx(1.04)


def test_segment_audit_breakdown_and_chain_keys():
    res = derive_segment_level_beta(
        "BRK-B",
        [("Insurance", 0.7), ("Railroad", 0.3)],
        segment_industry_resolver=_seg_resolver(
            {"Insurance": "Insurance - Diversified", "Railroad": "Railroads"}
        ),
        beta_provider=_seg_provider({
            "Insurance - Diversified": _seg_result(0.7),
            "Railroads": _seg_result(0.9, level=2, source="neighbor-median"),
        }),
    )
    assert res is not None
    assert len(res.segments) == 2
    by_label = {s["label"]: s for s in res.segments}
    assert by_label["Insurance"]["industry"] == "Insurance - Diversified"
    assert by_label["Railroad"]["beta_unlevered"] == pytest.approx(0.9)
    assert by_label["Railroad"]["level"] == 2
    chain = res.to_chain()
    assert chain["level"] == 0
    assert chain["segments"] == res.segments
    assert "分部加权" in res.note()


def test_segment_weights_renormalised_over_resolved_subset():
    # Unresolved "Unknown" (weight 0.25) is dropped; the 0.75 that resolves is
    # renormalised to 1.0 so the audit weights sum to 1.
    res = derive_segment_level_beta(
        "GE",
        [("Semiconductors", 0.5), ("Cloud", 0.25), ("Unknown Segment", 0.25)],
        segment_industry_resolver=_seg_resolver(
            {"Semiconductors": "Semiconductors", "Cloud": "Information Technology Services"}
        ),
        beta_provider=_seg_provider({
            "Semiconductors": _seg_result(1.0),
            "Information Technology Services": _seg_result(0.5),
        }),
    )
    assert res is not None
    assert sum(s["weight"] for s in res.segments) == pytest.approx(1.0)
    assert {s["label"] for s in res.segments} == {"Semiconductors", "Cloud"}
    # 0.5/0.75·1.0 + 0.25/0.75·0.5 = 0.6667 + 0.1667 = 0.8333
    assert res.beta_unlevered == pytest.approx(0.8333, abs=1e-4)
    assert "未解析：Unknown Segment" in res.rationale


def test_segment_level_beta_cash_adjust_and_relever():
    res = derive_segment_level_beta(
        "TGT",
        [("Semiconductors", 0.5), ("Cloud", 0.5)],
        target_d2e=0.5,
        target_tax_rate=0.21,
        cash_to_firm=0.20,
        segment_industry_resolver=_seg_resolver(
            {"Semiconductors": "Semiconductors", "Cloud": "Information Technology Services"}
        ),
        beta_provider=_seg_provider({
            "Semiconductors": _seg_result(1.0),
            "Information Technology Services": _seg_result(1.0),
        }),
    )
    assert res is not None
    assert res.beta_unlevered == pytest.approx(1.0)
    assert res.beta_cash_adjusted == pytest.approx(_cash_adjust(1.0, 0.20))
    assert res.beta_cash_adjusted == pytest.approx(1.25)
    assert res.cash_to_firm == pytest.approx(0.20)
    assert res.target_d2e == pytest.approx(0.5)
    assert res.beta_relevered == pytest.approx(
        _relever(_cash_adjust(1.0, 0.20), 0.5, 0.21), abs=1e-4
    )


def test_segment_returns_none_below_min_segments():
    # Only one of the two labels resolves → below min_segments → None.
    res = derive_segment_level_beta(
        "TGT",
        [("Semiconductors", 0.6), ("Unknown Segment", 0.4)],
        segment_industry_resolver=_seg_resolver({"Semiconductors": "Semiconductors"}),
        beta_provider=_seg_provider({"Semiconductors": _seg_result(1.0)}),
    )
    assert res is None


def test_segment_returns_none_below_min_coverage():
    # Two segments resolve, but they cover only 50% of the weight (< 0.60).
    res = derive_segment_level_beta(
        "TGT",
        [("Semiconductors", 0.25), ("Cloud", 0.25), ("Unknown Segment", 0.5)],
        segment_industry_resolver=_seg_resolver(
            {"Semiconductors": "Semiconductors", "Cloud": "Information Technology Services"}
        ),
        beta_provider=_seg_provider({
            "Semiconductors": _seg_result(1.0),
            "Information Technology Services": _seg_result(1.0),
        }),
    )
    assert res is None


def test_segment_offline_returns_none():
    res = derive_segment_level_beta(
        "TGT",
        [("Semiconductors", 0.6), ("Cloud", 0.4)],
        segment_industry_resolver=_seg_resolver(
            {"Semiconductors": "Semiconductors", "Cloud": "Information Technology Services"}
        ),
        beta_provider=_seg_provider({
            "Semiconductors": _seg_result(1.0),
            "Information Technology Services": _seg_result(0.5),
        }),
        offline=True,
    )
    assert res is None


def test_bottom_up_prefers_segment_branch():
    # When segments resolve, the company-level peer chain must NOT run.
    def _boom(*a, **k):
        raise AssertionError("company-level chain must not run when segments resolve")

    res = derive_bottom_up_beta(
        "AMZN", "Technology", "Semiconductors",
        segments=[("Semiconductors", 0.6), ("Cloud", 0.4)],
        segment_industry_resolver=_seg_resolver(
            {"Semiconductors": "Semiconductors", "Cloud": "Information Technology Services"}
        ),
        segment_beta_provider=_seg_provider({
            "Semiconductors": _seg_result(1.2),
            "Information Technology Services": _seg_result(0.8),
        }),
        peer_lister=_boom,
        beta_fetcher=_boom,
    )
    assert res is not None
    assert res.level == 0
    assert res.source == "segment-weighted"
    assert res.beta_unlevered == pytest.approx(1.04)


def test_bottom_up_falls_back_to_company_when_segments_unresolved(tmp_path):
    # Segments present but too few resolve → transparent fallback to the
    # company-level peer chain (the classic L1 path).
    table = {"A": (1.0, 0.0), "B": (1.0, 0.0), "C": (1.0, 0.0)}
    res = derive_bottom_up_beta(
        "TGT", "Technology", "Semiconductors",
        segments=[("Semiconductors", 0.6), ("Unknown Segment", 0.4)],
        segment_industry_resolver=_seg_resolver({"Semiconductors": "Semiconductors"}),
        segment_beta_provider=_seg_provider({"Semiconductors": _seg_result(1.0)}),
        peer_lister=_lister(["A", "B", "C"]),
        beta_fetcher=_fetcher(table),
        cache_path=tmp_path / "b.json",
    )
    assert res is not None
    assert res.level == 1
    assert res.n_peers == 3
    assert res.segments is None


def test_default_segment_industry_resolver_keyword_map():
    assert _default_segment_industry_resolver("iPhone") == "Consumer Electronics"
    assert _default_segment_industry_resolver("Semiconductor Products") == "Semiconductors"
    assert _default_segment_industry_resolver("AWS Cloud Services") == "Information Technology Services"
    assert _default_segment_industry_resolver("Automotive Vehicle Sales") == "Auto Manufacturers"
    assert _default_segment_industry_resolver("Something Unmappable") is None


def test_default_segment_resolver_real_corpus_additions():
    # Session #27 — mappings generalised from real FMP /stable segment labels.
    r = _default_segment_industry_resolver
    assert r("Upstream") == "Oil & Gas E&P"
    assert r("Downstream") == "Oil & Gas Refining & Marketing"
    assert r("Biopharma Segment") == "Drug Manufacturers - General"
    assert r("MedTech") == "Medical Devices"
    assert r("Aeronautics") == "Aerospace & Defense"
    assert r("Commercial Airplanes") == "Aerospace & Defense"
    assert r("Intel Foundry Services") == "Semiconductors"
    assert r("Asset and Wealth Management Segment") == "Asset Management"
    assert r("YouTube ads") == "Internet Content & Information"
    assert r("Online Stores") == "Internet Retail"
    assert r("Apparel & accessories") == "Apparel Retail"
    # Round 2 — residual generalisable business-line words.
    assert r("Space") == "Aerospace & Defense"
    assert r("Print And Publishing") == "Publishing"
    assert r("Data Processing Revenues") == "Information Technology Services"
    assert r("Energy Products") == "Oil & Gas Refining & Marketing"
    assert r("Digital Experience") == "Software - Application"
    # Non-segments / geographic / XBRL artifacts stay unmapped → dropped.
    assert r("Other") is None
    assert r("Corporate & Other") is None
    assert r("All Other") is None
    assert r("Latin America (Segment)") is None
    assert r("Segment Reporting, Reconciling Item, Corporate Nonsegment") is None
    # Issuer-specific drug brand names / acronyms stay unmapped → dropped.
    assert r("Botox Cosmetic") is None
    assert r("RINVOQ") is None
    assert r("GMNA") is None


def test_coerce_segments_accepts_pairs_and_objects():
    class _Seg:
        def __init__(self, label, weight):
            self.label = label
            self.weight = weight

    assert _coerce_segments([("A", 0.6), ("B", 0.4)]) == [("A", 0.6), ("B", 0.4)]
    assert _coerce_segments([_Seg("A", 0.7), _Seg("B", 0.3)]) == [("A", 0.7), ("B", 0.3)]
    # Non-positive / unparsable weights are dropped (never guessed).
    assert _coerce_segments([("A", 0.0), ("B", None), ("C", "x"), ("D", 1.0)]) == [("D", 1.0)]
    assert _coerce_segments(None) == []


def test_bottom_up_env_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("BOTTOM_UP_BETA", "0")
    res = derive_bottom_up_beta(
        "AMZN", "Technology", "Semiconductors",
        segments=[("Semiconductors", 0.6), ("Cloud", 0.4)],
        segment_industry_resolver=_seg_resolver(
            {"Semiconductors": "Semiconductors", "Cloud": "Information Technology Services"}
        ),
        segment_beta_provider=_seg_provider({
            "Semiconductors": _seg_result(1.2),
            "Information Technology Services": _seg_result(0.8),
        }),
    )
    assert res is None
