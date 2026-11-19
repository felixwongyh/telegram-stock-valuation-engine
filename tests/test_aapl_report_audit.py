"""Regression tests for the AAPL report audit (Session #46)."""
from types import SimpleNamespace


# ---- BUG-3: NWC caliber (marginal ΔNWC/ΔRev vs revenue share) --------------
def test_fcf_normalisation_converts_marginal_nwc_to_revenue_share():
    """A marginal NWC rate must be scaled by growth before being subtracted from
    a revenue-share FCF margin; using it raw produced −11.6% for AAPL."""
    from analysis import divergence

    class _FakeEngine:
        def __init__(self, **kw):
            pass

        def _extract_history(self, data):
            # 37.9% marginal NWC, 7% growth, 30% op margin, 3% D&A, 3% capex, 15% tax
            return 0.07, 0.0, 0.30, 0.03, 0.03, 0.379, 0.15

    ttm = SimpleNamespace(
        revenue=100.0, operating_income=30.0, da=3.0, capex=3.0,
        change_in_nwc=3.1, pretax_income=30.0, tax_provision=4.5,
    )
    data = SimpleNamespace(ttm=ttm, annual_income=[], business_type="MatureTech")

    import forecasts.forecast as fc
    orig = fc.ForecastEngine
    fc.ForecastEngine = _FakeEngine
    try:
        check = divergence._fcf_normalization_layer(data, SimpleNamespace(business_type="MatureTech"))
    finally:
        fc.ForecastEngine = orig

    assert check is not None
    # hist margin = 0.30*0.85 + 0.03 - 0.03 - (0.379*0.07=0.02653) = 0.22847
    assert "22.8%" in check.detail or "22.9%" in check.detail
    assert "-11" not in check.detail


# ---- BUG-8: *.generic economics node must not coarsen a precise identity ----
def test_generic_economics_label_keeps_precise_identity():
    from classification.taxonomy import ExternalClassification, reconcile_identity

    rec = reconcile_identity(
        external=ExternalClassification(yahoo_sector="Technology", yahoo_industry="Consumer Electronics"),
        economics_key="tech.generic",
    )
    assert rec.canonical_key == "tech.hardware"
    assert rec.valuation_archetype.value == "MatureTech"


def test_specific_economics_conflict_still_collapses_to_ancestor():
    from classification.taxonomy import ExternalClassification, reconcile_identity

    rec = reconcile_identity(
        external=ExternalClassification(yahoo_sector="Technology", yahoo_industry="Consumer Electronics"),
        economics_key="tech.semiconductor",
    )
    assert rec.canonical_key == "tech"


# ---- BUG-6: growth profile survives a missing oldest-year revenue ----------
def test_growth_profile_uses_longest_usable_span():
    from classification.classifier import BusinessClassifier
    from config import BusinessType

    def _yr(rev):
        return SimpleNamespace(revenue=rev, period_end=None)

    # Newest first; oldest year revenue missing (AAPL's 2022).
    annuals = [_yr(478.8e9), _yr(416.2e9), _yr(391.0e9), _yr(383.3e9), _yr(None)]
    class _Any(SimpleNamespace):
        def __getattr__(self, name):
            return None

    data = _Any(ttm=_Any(revenue=478.8e9, operating_income=130e9),
                annual_income=annuals, market=_Any(), balance_sheet=_Any())
    out = BusinessClassifier._characterize_profile(data, BusinessType.MATURE_TECH)
    # 383.3 -> 478.8 over 3y ≈ 7.7% → "Stable" (>=0, <8%)
    assert out["growth_profile"] == "Stable"


# ---- BUG-4: forecast FCF CAGR must not mix bridge and reported calibers -----
def test_forecast_fcf_cagr_uses_bridge_anchor():
    """Reported TTM FCF (OCF−capex, SBC added back) is not comparable to a
    bridge-caliber projection; mixing them read a rising path as −1.6%."""
    from forecasts.forecast import ForecastEngine

    class _Any(SimpleNamespace):
        def __getattr__(self, name):
            return None

    ttm = _Any(revenue=100.0, free_cash_flow=28.0)  # reported caliber
    annuals = [
        _Any(revenue=100.0, operating_income=30.0, change_in_nwc=3.0),
        _Any(revenue=93.0, operating_income=28.0, change_in_nwc=3.0),
    ]
    data = _Any(ttm=ttm, annual_income=annuals)

    anchor = ForecastEngine(horizon_years=5).bridge_fcf_anchor(data)
    assert anchor is not None
    # Bridge anchor must not equal the reported figure — it is a different caliber.
    assert abs(anchor - 28.0) > 1e-9
    # Sanity: bridge FCF is a plausible share of revenue, not a sign flip.
    assert 0.0 < anchor / 100.0 < 0.40
