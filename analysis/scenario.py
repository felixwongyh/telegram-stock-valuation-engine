"""
analysis/scenario.py - Bear/Base/Bull Scenario Analysis
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config import (
    DEFAULT_DCF_CONFIG,
    DEFAULT_SCENARIO_CONFIG,
    ScenarioConfig,
    ScenarioType,
    get_logger,
    resolve_forecast_horizon,
)
from config import DCFConfig
from data.models import FinancialData
from forecasts.forecast import ForecastEngine
from forecasts.nwc_utils import business_type_from_profile
from models.dcf import DCFModel
from valuation.caliber import CaliberContract, DiscountCaliber, build_caliber_contract
from valuation.terminal_growth import TerminalGrowthCalculator

log = get_logger("analysis.scenario")


@dataclass
class ScenarioValuation:
    scenario: str
    value_per_share: Optional[float]
    wacc: float
    terminal_growth: float
    notes: List[str] = field(default_factory=list)
    assumptions: Dict[str, Any] = field(default_factory=dict)
    # Which family of drivers this scenario actually varies. The Bear/Base/Bull
    # trio alone is NOT a full operating scenario: it only moves the discount
    # rate (WACC) and terminal growth. "operating" is a genuinely separate
    # family that moves revenue growth / operating margin / CapEx / FCF.
    scenario_kind: str = "discount_rate"
    drivers: Dict[str, Any] = field(default_factory=dict)


class ScenarioAnalyzer:
    """Runs DCF under Bear/Base/Bull scenarios.

    Financial institutions (banks / insurers) are the exception: DCF calibers
    (FCF, Net Debt, EV, WACC) are undefined for a borrowing business, so their
    Bear/Base/Bull band is produced by the *applicable* bank model (Bank RIM),
    varied along the cost of equity.
    """

    # Cost-of-equity scenario width for financials, expressed in β units. The
    # CAPM shift is applied on top of the unified β exit, then clamp-guarded to
    # the winsorised band [0.30, 2.50] used everywhere else.
    _FIN_BETA_STEP = 0.30
    # Operating-driver width for financials, expressed as a *relative* swing on
    # ROE (the aggregate outcome of net interest margin and credit costs). Bear
    # = ROE down, Bull = ROE up. ROE is the best operating proxy available from
    # the TTM data; a true NIM / provision split would need line-item data.
    _FIN_ROE_SHOCK = 0.20

    def __init__(
        self,
        scenario_cfg: ScenarioConfig = DEFAULT_SCENARIO_CONFIG,
        dcf_cfg: DCFConfig = DEFAULT_DCF_CONFIG,
        horizon: Optional[int] = None,
    ) -> None:
        self.sc = scenario_cfg
        self.dc = dcf_cfg
        # Horizon is resolved per call from the profile (Session #16) so scenario
        # values share the exact DCF / Reverse DCF window. Pass an int only to
        # force an explicit override.
        self._horizon_override = horizon
        self.scenario_cfg = scenario_cfg
        self.forecast: Optional[ForecastEngine] = None

    def _resolve_horizon(self, profile: Any) -> int:
        if self._horizon_override is not None:
            return int(self._horizon_override)
        return resolve_forecast_horizon(business_type_from_profile(profile))

    def _forecast_engine(self, profile: Any, horizon: int) -> ForecastEngine:
        return ForecastEngine(
            horizon_years=horizon,
            scenario_config=self.scenario_cfg,
            business_type=business_type_from_profile(profile),
        )

    def run_all(self, data: FinancialData, profile: Any) -> Dict[str, ScenarioValuation]:
        # The discount caliber is an ENGINE output (CaliberContract), not a
        # render-time guess. When the engine declares a cost-of-equity caliber
        # (banks / insurers) the DCF path is a forbidden caliber here.
        contract = build_caliber_contract(profile)
        if contract.discount is DiscountCaliber.COST_OF_EQUITY:
            return self._run_financial_scenarios(data, profile, contract)
        horizon = self._resolve_horizon(profile)
        forecast = self._forecast_engine(profile, horizon)
        self.forecast = forecast
        results: Dict[str, ScenarioValuation] = {}
        for s in ScenarioType:
            results[s.value] = self._run_one(data, profile, s, horizon)
        return results

    def _run_financial_scenarios(
        self, data: FinancialData, profile: Any,
        contract: Optional[CaliberContract] = None,
    ) -> Dict[str, ScenarioValuation]:
        """Bear/Base/Bull for banks & insurers via the residual-income model.

        A DCF scenario for a bank is a forbidden caliber: the report itself
        flags "DCF unreliable for financial institutions", so presenting a
        WACC/terminal-growth band here would contradict both that note and the
        bank-model median (Recursion SOFI round2 fix).

        Scenarios vary *two* financial-specific drivers instead of reusing DCF:
          * discount side — cost of equity around the unified β exit, and
          * operating side — ROE (≈ net interest margin / credit cost), the
            residual-income model's profitability driver.
        This gives the band an operating dimension rather than pure rate
        sensitivity (Recursion SOFI round3 follow-up).

        P0 Refactor: Scenario betas are now derived from the BASE valuation_beta
        (after bank ke band clamp), NOT from the raw winsorized beta. This
        ensures Bear/Base/Bull share the same basis. The CAPM chain (raw →
        normalized → valuation → scenario) is tracked for each scenario.
        """
        from models.bank import BankRIMModel
        from valuation.capm_engine import compute_base_capm, compute_scenario_capm

        contract = contract or build_caliber_contract(profile)
        discount_label = contract.discount.value
        model = BankRIMModel()

        # Compute the base-case CAPM chain to get the ACTUAL valuation beta
        # (after bank ke band clamp). Scenario betas must be derived from THIS
        # value, not from the raw winsorized beta.
        base_chain = compute_base_capm(data, is_bank=True)
        base_valuation_beta = base_chain.valuation_beta  # clamped if bank band applied

        # Probe the base case once to read the TTM-derived ROE the model uses.
        # No beta override — let the bank model's ke clamp apply so the probe
        # matches the actual base case.
        base_roe: Optional[float] = None
        try:
            probe = model.calculate(data, profile)
            if probe.is_success() and probe.breakdown:
                base_roe = probe.breakdown.get("roe")
        except Exception as e:  # pragma: no cover - defensive
            log.exception(f"Bank RIM base probe failed: {e}")

        plan = (
            (ScenarioType.BEAR, +self._FIN_BETA_STEP, -self._FIN_ROE_SHOCK),
            (ScenarioType.BASE, 0.0, 0.0),
            (ScenarioType.BULL, -self._FIN_BETA_STEP, +self._FIN_ROE_SHOCK),
        )
        out: Dict[str, ScenarioValuation] = {}
        for st, shift, roe_shock in plan:
            # P0 Refactor: Scenario beta = base VALUATION beta + shift.
            # This ensures Bear/Bull/Base all use the same starting point.
            # Bank ke band is NOT applied to scenarios (they must stress beyond).
            if shift != 0:
                # Compute scenario chain from the base chain
                scenario_chain = compute_scenario_capm(
                    base_chain, shift, is_bank=True
                )
                beta = scenario_chain.valuation_beta
            else:
                beta = None  # BASE: let _resolve_discount_inputs apply bank clamp
                scenario_chain = base_chain
            roe_override = None
            if base_roe is not None and roe_shock:
                roe_override = base_roe * (1.0 + roe_shock)
            drivers: List[str] = []
            if shift:
                # Show the shift from the ACTUAL base valuation beta (post-clamp)
                drivers.append(
                    f"折现率 ke {'↑' if shift > 0 else '↓'}"
                    f"（β = {base_valuation_beta:.2f} {shift:+.2f} = {beta:.2f}）"
                )
            if roe_override is not None and base_roe is not None:
                drivers.append(f"经营性 ROE {'↓' if roe_shock < 0 else '↑'}"
                               f"（{base_roe:.2%}→{roe_override:.2%}）")
            driver_txt = " + ".join(drivers) if drivers else "基准假设（未加驱动偏移）"

            try:
                r = model.calculate(data, profile, beta=beta, roe_override=roe_override)
            except Exception as e:  # pragma: no cover - defensive
                log.exception(f"Bank RIM scenario {st.value} failed: {e}")
                out[st.value] = ScenarioValuation(
                    scenario=st.value, value_per_share=None, wacc=0.0,
                    terminal_growth=0.0, notes=[f"Error: {e}"],
                    assumptions={
                        "model": "Bank RIM", "discount_label": discount_label,
                        "drivers": driver_txt,
                        "capm_chain": scenario_chain.as_dict() if scenario_chain else None,
                    },
                    scenario_kind="financial",
                    drivers={"beta": beta or 0.0, "roe_override": roe_override},
                )
                continue
            bd = getattr(r, "breakdown", None) or {}
            ke = bd.get("cost_of_equity")
            beta_used = bd.get("beta", beta)
            roe_used = bd.get("roe")
            ok = r.is_success() and r.value_per_share is not None
            value_per_share = r.value_per_share
            if not r.is_success():
                value_per_share = None
            if ke is not None:
                roe_bit = (
                    f"；ROE（≈ 净息差/信用成本的综合体现，APPROXIMATE）={float(roe_used):.2%}"
                    if isinstance(roe_used, (int, float)) else ""
                )
                # P0: Show raw CAPM ke vs adjusted ke in the scenario notes
                capm_note = ""
                if scenario_chain and scenario_chain.ke_adjusted and scenario_chain.raw_capm_ke is not None:
                    capm_note = (
                        f"；Raw CAPM ke={scenario_chain.raw_capm_ke:.2%} "
                        f"（raw β={scenario_chain.raw_beta:.2f}）→ "
                        f"Adjusted ke={ke:.2%}（valuation β={beta_used:.2f}）"
                    )
                notes = [
                    f"金融标的情景：以 Bank RIM（残差收益）计算，折现率 = 权益成本 "
                    f"ke={float(ke):.2%}（β={float(beta_used):.2f}）{roe_bit}{capm_note}；DCF（WACC/净债务/EV）对"
                    f"银行/保险不适用",
                    f"情景驱动：{driver_txt}",
                ]
            else:
                notes = ["金融标的情景：DCF 不适用，改用 Bank RIM 但成本法未解出"]
            if ok and r.notes:
                notes.append(r.notes[0])
            out[st.value] = ScenarioValuation(
                scenario=st.value,
                value_per_share=(
                    float(value_per_share) if value_per_share is not None else None
                ),
                wacc=float(ke) if ke is not None else 0.0,
                terminal_growth=0.0,
                notes=notes,
                assumptions={
                    "model": "Bank RIM",
                    "beta": beta_used,
                    "discount_label": discount_label,
                    "cost_of_equity": ke,
                    "roe": roe_used,
                    "drivers": driver_txt,
                    "capm_chain": scenario_chain.as_dict() if scenario_chain else None,
                    "base_valuation_beta": base_valuation_beta,
                },
                scenario_kind="financial",
                drivers={
                    "cost_of_equity": ke, "beta": beta_used,
                    "roe_override": roe_override,
                    "raw_capm_ke": scenario_chain.raw_capm_ke if scenario_chain else None,
                    "raw_beta": scenario_chain.raw_beta if scenario_chain else None,
                },
            )
        return out

    # ------------------------------------------------------------------
    # P0-3: Single-variable sensitivities for financial institutions.
    # The original ``_run_financial_scenarios`` varies BOTH Ke (β shift) and
    # ROE simultaneously — that is a *combined* scenario, not a clean
    # sensitivity. To make the description match the actual variable, we now
    # expose two single-variable families:
    #   * ``run_cost_of_equity_sensitivity`` — only Ke (β) moves, ROE held at base.
    #   * ``run_operating_sensitivity_bank`` — only ROE moves, Ke held at base.
    # The original combined band is retained as ``run_combined_scenario_bank``.
    # Non-financial companies use the existing DCF families (discount-rate and
    # operating) but are wrapped here so the caller gets a uniform interface.
    # ------------------------------------------------------------------
    def run_cost_of_equity_sensitivity(
        self, data: FinancialData, profile: Any
    ) -> Dict[str, ScenarioValuation]:
        """Vary **only** the cost of equity (via β), holding ROE at base.

        For financial institutions: Bank RIM re-run with β shifted by
        ±_FIN_BETA_STEP, no ROE override.

        For non-financials: the existing discount-rate Bear/Base/Bull band
        (WACC / terminal growth) is the cost-of-capital sensitivity, so we
        delegate to ``run_all`` and relabel.
        """
        contract = build_caliber_contract(profile)
        if contract.discount is DiscountCaliber.COST_OF_EQUITY:
            return self._run_bank_ke_sensitivity(data, profile, contract)
        # Non-financial: discount-rate scenarios ARE the cost-of-equity
        # sensitivity (WACC is the blended cost of capital). Return them with
        # the correct scenario_kind label.
        results = self.run_all(data, profile)
        for sv in results.values():
            sv.scenario_kind = "cost_of_equity"
        return results

    def _run_bank_ke_sensitivity(
        self, data: FinancialData, profile: Any,
        contract: Optional[CaliberContract] = None,
    ) -> Dict[str, ScenarioValuation]:
        """Bank RIM with **only** β (→ Ke) shifted; ROE held at base."""
        from models.bank import BankRIMModel
        from valuation.wacc import resolve_effective_beta

        contract = contract or build_caliber_contract(profile)
        discount_label = contract.discount.value
        base_beta = float(resolve_effective_beta(data).beta)
        model = BankRIMModel()

        plan = (
            (ScenarioType.BEAR, +self._FIN_BETA_STEP),
            (ScenarioType.BASE, 0.0),
            (ScenarioType.BULL, -self._FIN_BETA_STEP),
        )
        out: Dict[str, ScenarioValuation] = {}
        for st, shift in plan:
            if shift != 0:
                beta = min(2.50, max(0.30, base_beta + shift))
            else:
                beta = None
            driver_txt = (
                f"仅变动权益成本 Ke（β{shift:+.2f}）"
                if shift else "基准假设（Ke 不变）"
            )
            try:
                r = model.calculate(data, profile, beta=beta)
            except Exception as e:
                log.exception(f"Bank Ke sensitivity {st.value} failed: {e}")
                out[st.value] = ScenarioValuation(
                    scenario=st.value, value_per_share=None, wacc=0.0,
                    terminal_growth=0.0, notes=[f"Error: {e}"],
                    assumptions={"model": "Bank RIM", "discount_label": discount_label,
                                 "drivers": driver_txt},
                    scenario_kind="cost_of_equity",
                    drivers={"beta": beta or 0.0},
                )
                continue
            bd = getattr(r, "breakdown", None) or {}
            ke = bd.get("cost_of_equity")
            beta_used = bd.get("beta", beta)
            ok = r.is_success() and r.value_per_share is not None
            vps = r.value_per_share if ok else None
            if ke is not None:
                notes = [
                    f"Cost of Equity Sensitivity：仅变动 Ke（β={float(beta_used):.2f} → "
                    f"ke={float(ke):.2%}），ROE 固定在基准",
                    f"情景驱动：{driver_txt}",
                ]
            else:
                notes = ["Cost of Equity Sensitivity：Ke 未解出"]
            if ok and r.notes:
                notes.append(r.notes[0])
            out[st.value] = ScenarioValuation(
                scenario=st.value,
                value_per_share=(float(vps) if vps is not None else None),
                wacc=float(ke) if ke is not None else 0.0,
                terminal_growth=0.0,
                notes=notes,
                assumptions={"model": "Bank RIM", "beta": beta_used,
                             "discount_label": discount_label, "cost_of_equity": ke,
                             "drivers": driver_txt},
                scenario_kind="cost_of_equity",
                drivers={"cost_of_equity": ke, "beta": beta_used},
            )
        return out

    def run_operating_sensitivity(
        self, data: FinancialData, profile: Any
    ) -> Dict[str, ScenarioValuation]:
        """Vary **only** the operating driver, holding the discount rate at base.

        For financial institutions: Bank RIM re-run with ROE shifted by
        ±_FIN_ROE_SHOCK (relative), no β override.

        For non-financials: the existing operating Bear/Base/Bull (revenue /
        margin multipliers → CapEx / D&A / NWC → FCF), holding WACC at base.
        """
        contract = build_caliber_contract(profile)
        if contract.discount is DiscountCaliber.COST_OF_EQUITY:
            return self._run_bank_roe_sensitivity(data, profile, contract)
        return self.run_operating(data, profile)

    def _run_bank_roe_sensitivity(
        self, data: FinancialData, profile: Any,
        contract: Optional[CaliberContract] = None,
    ) -> Dict[str, ScenarioValuation]:
        """Bank RIM with **only** ROE shifted; Ke held at base (no β override)."""
        from models.bank import BankRIMModel

        contract = contract or build_caliber_contract(profile)
        discount_label = contract.discount.value
        model = BankRIMModel()

        # Probe base ROE
        base_roe: Optional[float] = None
        try:
            probe = model.calculate(data, profile)
            if probe.is_success() and probe.breakdown:
                base_roe = probe.breakdown.get("roe")
        except Exception as e:
            log.exception(f"Bank RIM base probe failed (ROE sensitivity): {e}")

        plan = (
            (ScenarioType.BEAR, -self._FIN_ROE_SHOCK),
            (ScenarioType.BASE, 0.0),
            (ScenarioType.BULL, +self._FIN_ROE_SHOCK),
        )
        out: Dict[str, ScenarioValuation] = {}
        for st, roe_shock in plan:
            roe_override = None
            if base_roe is not None and roe_shock:
                roe_override = base_roe * (1.0 + roe_shock)
            driver_txt = (
                f"仅变动经营性 ROE（{'↓' if roe_shock < 0 else '↑'}"
                f"{base_roe:.2%}→{roe_override:.2%}）"
                if roe_override is not None and base_roe is not None
                else "基准假设（ROE 不变）"
            )
            try:
                # No beta override → Ke stays at base (bank model ke clamp applies)
                r = model.calculate(data, profile, roe_override=roe_override)
            except Exception as e:
                log.exception(f"Bank ROE sensitivity {st.value} failed: {e}")
                out[st.value] = ScenarioValuation(
                    scenario=st.value, value_per_share=None, wacc=0.0,
                    terminal_growth=0.0, notes=[f"Error: {e}"],
                    assumptions={"model": "Bank RIM", "discount_label": discount_label,
                                 "drivers": driver_txt},
                    scenario_kind="operating_performance",
                    drivers={"roe_override": roe_override},
                )
                continue
            bd = getattr(r, "breakdown", None) or {}
            ke = bd.get("cost_of_equity")
            roe_used = bd.get("roe")
            ok = r.is_success() and r.value_per_share is not None
            vps = r.value_per_share if ok else None
            roe_txt = (
                f"，ROE={float(roe_used):.2%}" if isinstance(roe_used, (int, float)) else ""
            )
            ke_txt = f"，Ke={float(ke):.2%}" if isinstance(ke, (int, float)) else ""
            notes = [
                f"Operating Performance Sensitivity：仅变动 ROE{roe_txt}（Ke 固定在基准{ke_txt}）",
                f"情景驱动：{driver_txt}",
            ]
            if ok and r.notes:
                notes.append(r.notes[0])
            out[st.value] = ScenarioValuation(
                scenario=st.value,
                value_per_share=(float(vps) if vps is not None else None),
                wacc=float(ke) if ke is not None else 0.0,
                terminal_growth=0.0,
                notes=notes,
                assumptions={"model": "Bank RIM", "beta": bd.get("beta"),
                             "discount_label": discount_label,
                             "cost_of_equity": ke, "roe": roe_used,
                             "drivers": driver_txt},
                scenario_kind="operating_performance",
                drivers={"cost_of_equity": ke, "roe_override": roe_override, "roe": roe_used},
            )
        return out

    def run_combined_scenario(
        self, data: FinancialData, profile: Any
    ) -> Dict[str, ScenarioValuation]:
        """Vary **both** the discount rate and operating driver simultaneously.

        For financial institutions: the original ``_run_financial_scenarios``
        band (β shift + ROE shock together) — now explicitly labeled as the
        Combined Scenario.

        For non-financials: not applicable in the same framework (the
        discount-rate and operating bands are separate DCF families with
        different forecast paths). Returns an explanatory empty dict so the
        report shows a clear N/A.
        """
        contract = build_caliber_contract(profile)
        if contract.discount is DiscountCaliber.COST_OF_EQUITY:
            results = self._run_financial_scenarios(data, profile, contract)
            for sv in results.values():
                sv.scenario_kind = "combined"
            return results
        # Non-financials: combined scenario is conceptually the intersection
        # of the two single-variable families. We do not fabricate a hybrid
        # DCF path; the report shows this as N/A.
        return {}

    def _run_one(
        self, data: FinancialData, profile: Any, st: ScenarioType, horizon: int
    ) -> ScenarioValuation:
        forecast = self.forecast
        if forecast is None:
            return ScenarioValuation(
                scenario=st.value,
                value_per_share=None,
                wacc=0.0,
                terminal_growth=0.0,
                notes=["Forecast engine is unavailable"],
            )
        if st == ScenarioType.BEAR:
            wacc_add = self.sc.bear_wacc_add
        elif st == ScenarioType.BULL:
            wacc_add = self.sc.bull_wacc_add
        else:
            wacc_add = 0.0

        dcfg = DCFConfig(
            risk_free_rate=self.dc.risk_free_rate,
            equity_risk_premium=self.dc.equity_risk_premium,
            default_unlevered_beta=self.dc.default_unlevered_beta,
            default_terminal_growth=self.dc.default_terminal_growth,
            min_wacc=self.dc.min_wacc,
            max_wacc=self.dc.max_wacc,
            max_terminal_growth=self.dc.max_terminal_growth,
            tax_rate=self.dc.tax_rate,
        )
        model = DCFModel(config=dcfg, forecast_horizon=horizon)

        try:
            from config import ScenarioType as ST
            if st == ST.BASE:
                result = model.calculate(data, profile)
            else:
                wacc = model._estimate_wacc(data, profile) + wacc_add
                tvg = TerminalGrowthCalculator().calculate(data, wacc=wacc)
                if st == ST.BEAR:
                    tg = tvg.low
                elif st == ST.BULL:
                    tg = tvg.high
                else:
                    tg = tvg.base
                tg = min(max(0.0, tg), wacc - 0.001)

                # ---- Use BASE forecasts for all scenarios (consistent with
                # sensitivity matrix). Previously, bear/bull used scenario-
                # adjusted forecasts (revenue×0.7, margin×0.7, etc.), which
                # caused the scenario values to diverge from the sensitivity
                # matrix at the same (WACC, TG) pair.
                # This is the fix for P0-1: scenario values must be reproducible
                # in the sensitivity matrix.
                forecasts = forecast.build_all(data).get(ST.BASE, [])
                if not forecasts:
                    forecasts = forecast._build_scenario(data, ST.BASE) or []

                if not forecasts:
                    return ScenarioValuation(
                        scenario=st.value,
                        value_per_share=None,
                        wacc=wacc,
                        terminal_growth=tg,
                        notes=["No forecast data available"],
                    )
                pv_explicit, tv, pv_tv, fcf_list, tv_pct = model._pv_calculations(forecasts, wacc, tg)
                ev = pv_explicit + pv_tv
                net_debt = data.market.net_debt_or_zero()
                eq = ev - net_debt
                shares = forecasts[-1].shares_outstanding or (data.ttm.shares_outstanding if data.ttm else None)
                if shares and shares > 0 and eq is not None:
                    pps = eq / shares
                    notes = []
                    if pps < 0:
                        # Negative per-share equity is not a price target — floor to 0
                        # and flag equity-wipeout / insolvency risk instead.
                        notes.append(
                            f"⚠️ 股权价值归零（原始推算 ${pps:.2f} < 0）：该情景下 EV 低于净债务，"
                            "存在资不抵债 / 股权被清零风险"
                        )
                        pps = 0.0
                    if tv_pct > 0.85:
                        notes.append(f"TV weight {tv_pct:.1%}")
                    notes.append(
                        f"Scenario uses base forecasts with WACC={wacc:.4f}, g={tg:.4f} "
                        f"(consistent with sensitivity matrix)"
                    )
                    return ScenarioValuation(
                        scenario=st.value,
                        value_per_share=pps,
                        wacc=wacc,
                        terminal_growth=tg,
                        notes=notes,
                        assumptions={"tv_pct": tv_pct, "ev": ev, "equity": eq},
                        scenario_kind="discount_rate",
                        drivers={"wacc": wacc, "terminal_growth": tg},
                    )
                return ScenarioValuation(
                    scenario=st.value, value_per_share=None, wacc=wacc, terminal_growth=tg,
                    notes=["Invalid shares or equity"],
                )
        except Exception as e:
            log.exception(f"Scenario {st.value} failed: {e}")
            return ScenarioValuation(
                scenario=st.value,
                value_per_share=None,
                wacc=self.dc.risk_free_rate,
                terminal_growth=self.dc.default_terminal_growth,
                notes=[f"Error: {e}"],
            )

        if result.is_success():
            pps = result.value_per_share
            notes = list(result.notes) if result.notes else []
            tv_pct = result.breakdown.get("tv_percent_of_ev") if result.breakdown else None
            # Apply the same negative-equity floor as Bear/Bull scenarios
            # (a negative per-share value is not a price target — it signals
            # equity-wipeout / insolvency risk).
            if pps is not None and pps < 0:
                notes.insert(0,
                    f"⚠️ 股权价值归零（原始推算 ${pps:.2f} < 0）：该情景下 EV 低于净债务，"
                    "存在资不抵债 / 股权被清零风险"
                )
                pps = 0.0
            return ScenarioValuation(
                scenario=st.value,
                value_per_share=pps,
                wacc=result.breakdown.get("wacc", 0) if result.breakdown else 0,
                terminal_growth=result.breakdown.get("terminal_growth", 0) if result.breakdown else 0,
                notes=notes,
                assumptions={
                    "tv_pct": tv_pct,
                    "ev": result.breakdown.get("enterprise_value") if result.breakdown else None,
                },
                scenario_kind="discount_rate",
                drivers={
                    "wacc": result.breakdown.get("wacc", 0) if result.breakdown else 0,
                    "terminal_growth": result.breakdown.get("terminal_growth", 0) if result.breakdown else 0,
                },
            )
        return ScenarioValuation(
            scenario=st.value,
            value_per_share=None,
            wacc=self.dc.risk_free_rate,
            terminal_growth=self.dc.default_terminal_growth,
            notes=result.notes,
        )

    # ------------------------------------------------------------------
    # Operating scenarios (Phase 2): a family SEPARATE from the discount-rate
    # Bear/Base/Bull in run_all. These move revenue growth / operating margin
    # (which flow through to CapEx / D&A / NWC / FCF) while holding the
    # discount rate at the deterministic base case. Reporting them apart is the
    # fix for "Bear/Base/Bull only changes WACC/g, yet is called a full scenario".
    # ------------------------------------------------------------------
    def run_operating(
        self, data: FinancialData, profile: Any
    ) -> Dict[str, ScenarioValuation]:
        contract = build_caliber_contract(profile)
        if contract.discount is DiscountCaliber.COST_OF_EQUITY:
            # DCF operating scenarios (revenue/margin/CapEx/FCF) are a forbidden
            # caliber for banks/insurers; their ROE sensitivity already lives in
            # the financial family. Do not fabricate a DCF operating band.
            return {}

        horizon = self._resolve_horizon(profile)
        self.forecast = self._forecast_engine(profile, horizon)
        base_forecasts = self.forecast.build_all(data).get(ScenarioType.BASE, [])
        if not base_forecasts:
            base_forecasts = self.forecast._build_scenario(data, ScenarioType.BASE) or []
        if not base_forecasts:
            return {}

        dcfg = DCFConfig(
            risk_free_rate=self.dc.risk_free_rate,
            equity_risk_premium=self.dc.equity_risk_premium,
            default_unlevered_beta=self.dc.default_unlevered_beta,
            default_terminal_growth=self.dc.default_terminal_growth,
            min_wacc=self.dc.min_wacc,
            max_wacc=self.dc.max_wacc,
            max_terminal_growth=self.dc.max_terminal_growth,
            tax_rate=self.dc.tax_rate,
        )
        model = DCFModel(config=dcfg, forecast_horizon=horizon)
        try:
            wacc = model._estimate_wacc(data, profile)
        except Exception as e:  # pragma: no cover - defensive
            log.exception(f"Operating scenario WACC failed: {e}")
            return {}
        tg = TerminalGrowthCalculator().calculate(data, wacc=wacc).base
        tg = min(max(0.0, tg), wacc - 0.001)
        net_debt = data.market.net_debt_or_zero()
        shares = base_forecasts[-1].shares_outstanding or (
            data.ttm.shares_outstanding if data.ttm else None
        )

        plan = {
            ScenarioType.BEAR.value: (self.sc.bear_revenue_mult, self.sc.bear_margin_mult),
            ScenarioType.BASE.value: (1.0, 1.0),
            ScenarioType.BULL.value: (self.sc.bull_revenue_mult, self.sc.bull_margin_mult),
        }
        out: Dict[str, ScenarioValuation] = {}
        for name, (rev_mult, margin_mult) in plan.items():
            if rev_mult == 1.0 and margin_mult == 1.0:
                fc = base_forecasts
            else:
                fc = self.forecast._apply_multipliers(base_forecasts, rev_mult, margin_mult)
            try:
                pv_explicit, _tv, pv_tv, fcf_list, tv_pct = model._pv_calculations(fc, wacc, tg)
            except Exception as e:  # pragma: no cover - defensive
                log.exception(f"Operating scenario {name} failed: {e}")
                out[name] = ScenarioValuation(
                    scenario=name, value_per_share=None, wacc=wacc, terminal_growth=tg,
                    notes=[f"Error: {e}"], scenario_kind="operating",
                    drivers={"revenue_mult": rev_mult, "margin_mult": margin_mult},
                )
                continue
            ev = pv_explicit + pv_tv
            eq = ev - net_debt
            pps: Optional[float] = None
            notes: List[str] = []
            if shares and shares > 0 and eq is not None:
                pps = eq / shares
                if pps < 0:
                    notes.append(
                        f"⚠️ 股权价值归零（原始推算 ${pps:.2f} < 0）：该情景下 EV 低于净债务，"
                        "存在资不抵债 / 股权被清零风险"
                    )
                    pps = 0.0
            notes.append(
                f"经营性情景：营收 ×{rev_mult:.2f}（{rev_mult - 1:+.0%}）、"
                f"营业利润 ×{margin_mult:.2f}（{margin_mult - 1:+.0%}），经 CapEx/D&A/NWC 传导至 FCF；"
                f"折现率固定为基准 WACC={wacc:.4f}, g={tg:.4f}"
            )
            if tv_pct > 0.85:
                notes.append(f"TV weight {tv_pct:.1%}")
            out[name] = ScenarioValuation(
                scenario=name,
                value_per_share=pps,
                wacc=wacc,
                terminal_growth=tg,
                notes=notes,
                assumptions={
                    "tv_pct": tv_pct, "ev": ev, "equity": eq,
                    "revenue_mult": rev_mult, "margin_mult": margin_mult,
                    "last_fcf": fcf_list[-1] if fcf_list else None,
                },
                scenario_kind="operating",
                drivers={
                    "revenue_mult": rev_mult, "margin_mult": margin_mult,
                    "revenue_growth_delta": rev_mult - 1.0,
                    "operating_margin_delta": margin_mult - 1.0,
                },
            )
        return out


__all__ = ["ScenarioAnalyzer", "ScenarioValuation"]
