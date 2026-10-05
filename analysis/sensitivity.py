"""
analysis/sensitivity.py - Sensitivity Matrix Analysis
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import (
    DEFAULT_DCF_CONFIG,
    DEFAULT_FORECAST_HORIZON_YEARS,
    SENSITIVITY_DEFAULT_STEPS,
    SENSITIVITY_FALLBACK_TERMINAL_GROWTH,
    SENSITIVITY_FALLBACK_WACC,
    SENSITIVITY_TVG_MAX,
    SENSITIVITY_TVG_MIN,
    SENSITIVITY_WACC_MAX,
    SENSITIVITY_WACC_MIN,
    get_logger,
)
from data.models import FinancialData
from models.dcf import DCFModel

log = get_logger("analysis.sensitivity")


@dataclass
class SensitivityMatrix:
    title: str
    rows: List[float]
    cols: List[float]
    row_label: str
    col_label: str
    values: List[List[Optional[float]]]
    base_row_idx: int = 0
    base_col_idx: int = 0

    def _fmt_cell(self, v: Optional[float], is_base: bool = False) -> str:
        if v is None:
            return "     -   "
        s = f"${v:>6.2f}"
        return f"*{s}*" if is_base else f" {s} "

    def formatted_markdown_table(self,
                                 row_unit: str = "%",
                                 col_unit: str = "%",
                                 row_decimals: int = 1,
                                 col_decimals: int = 2,
                                 max_rows: Optional[int] = None,
                                 max_cols: Optional[int] = None,
                                 row_title: Optional[str] = None,
                                 col_title: Optional[str] = None) -> str:
        """生成符合规范的 Markdown 敏感性矩阵表格：
        | WACC \\ g | 2.0% | 2.33% | 2.5% | 3.0% |
        |----------|------|-------|------|------|
        | 7%       |      |       |      |      |
        | 8%       |      | $3.67 |      |      |
        | 9%       |      |       |      |      |
        """
        n_rows = len(self.rows) if max_rows is None else min(max_rows, len(self.rows))
        n_cols = len(self.cols) if max_cols is None else min(max_cols, len(self.cols))
        r_label = row_title if row_title is not None else self.row_label
        c_label = col_title if col_title is not None else self.col_label
        row_header = f"{r_label} \\ {c_label}"

        # Build column headers
        col_headers = [f"{c * 100:.{col_decimals}f}{col_unit}" for c in self.cols[:n_cols]]
        header_line = f"| {row_header:<12} | " + " | ".join(f"{h:>9}" for h in col_headers) + " |"
        sep_line = f"|{'-' * 14}|" + "|".join(f"{'-' * 11}" for _ in col_headers) + "|"
        lines = [self.title, "", header_line, sep_line]

        # Build each row
        for i in range(n_rows):
            row_str = f"{self.rows[i] * 100:.{row_decimals}f}{row_unit}"
            cells = []
            for j in range(n_cols):
                v = self.values[i][j] if i < len(self.values) and j < len(self.values[i]) else None
                is_base = (i == self.base_row_idx and j == self.base_col_idx)
                cells.append(self._fmt_cell(v, is_base=is_base))
            lines.append(f"| {row_str:<12} | " + " | ".join(cells) + " |")

        # Base cell note
        try:
            bv = self.values[self.base_row_idx][self.base_col_idx]
            br = self.rows[self.base_row_idx] * 100
            bc = self.cols[self.base_col_idx] * 100
            lines.append("")
            lines.append(
                f"_Base cell (row={br:.1f}{row_unit}, col={bc:.2f}{col_unit}) = "
                f"${bv:.2f} (matches DCF base valuation)_"
            )
        except Exception:
            pass
        return "\n".join(lines)

    def formatted_code_table(
        self,
        *,
        row_title: str = "WACC",
        col_title: str = "g",
        row_decimals: int = 1,
        col_decimals: int = 1,
        max_rows: Optional[int] = None,
        max_cols: Optional[int] = None,
        value_decimals: int = 1,
    ) -> str:
        """
        Fixed-width table in a fenced code block (Telegram / mobile friendly).
        Row & column headers are fractions stored in ``rows`` / ``cols`` → shown as %.
        """
        n_rows = len(self.rows) if max_rows is None else min(max_rows, len(self.rows))
        n_cols = len(self.cols) if max_cols is None else min(max_cols, len(self.cols))
        label_w = max(8, len(f"{row_title}\\{col_title}") + 1)
        col_w = max(7, col_decimals + 4)
        cell_w = max(7, value_decimals + 3)

        def _col_hdr(c: float) -> str:
            return f"{c * 100:.{col_decimals}f}%".rjust(col_w)

        def _row_lbl(r: float) -> str:
            return f"{r * 100:.{row_decimals}f}%".rjust(label_w)

        corner = f"{row_title}\\{col_title}".ljust(label_w)
        header = corner + "".join(_col_hdr(c) for c in self.cols[:n_cols])
        sep = " " * label_w + "-" * (col_w * n_cols)
        body: List[str] = [header, sep]
        for i in range(n_rows):
            line = _row_lbl(self.rows[i])
            for j in range(n_cols):
                v = (
                    self.values[i][j]
                    if i < len(self.values) and j < len(self.values[i])
                    else None
                )
                is_base = i == self.base_row_idx and j == self.base_col_idx
                if v is None:
                    cell = "-".rjust(cell_w)
                else:
                    s = f"${v:.{value_decimals}f}"
                    if is_base:
                        s = f"*{s}*"
                    cell = s.rjust(cell_w)
                line += cell
            body.append(line)
        return "```\n" + "\n".join(body) + "\n```"

    def stability_stats(self) -> Dict[str, Any]:
        """分析矩阵的稳定性：检查估值结果对参数的敏感程度，输出极差、CV等。"""
        all_vals: List[float] = [
            v for row in self.values for v in row if isinstance(v, (int, float))
        ]
        if not all_vals:
            return {"n_valid_cells": 0}
        import numpy as np
        arr = np.array(all_vals, dtype=float)
        try:
            base_val = self.values[self.base_row_idx][self.base_col_idx]
        except Exception:
            base_val = float(np.median(arr))
        pct_from_base = [
            ((v - base_val) / abs(base_val) * 100) if base_val else 0.0
            for v in all_vals
        ]
        return {
            "n_valid_cells": len(arr),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "range": float(np.max(arr) - np.min(arr)),
            "range_pct_vs_base": float((np.max(arr) - np.min(arr)) / max(1e-6, abs(base_val)) * 100),
            "mean": float(np.mean(arr)),
            "median": float(np.median(arr)),
            "std": float(np.std(arr)),
            "cv_pct": float(np.std(arr) / max(1e-6, np.mean(arr)) * 100) if np.mean(arr) else 0.0,
            "base_value": base_val,
            "pct_deviation_vs_base": {
                "min": float(min(pct_from_base)),
                "max": float(max(pct_from_base)),
                "avg_abs": float(sum(abs(x) for x in pct_from_base) / len(pct_from_base)),
            },
        }


class SensitivityAnalyzer:
    """Generates sensitivity matrices for key DCF inputs."""

    def __init__(
        self,
        steps: int = SENSITIVITY_DEFAULT_STEPS,
        horizon: int = DEFAULT_FORECAST_HORIZON_YEARS,
    ) -> None:
        self.steps = steps
        self.horizon = horizon

    def wacc_vs_terminal_growth(
        self,
        data: FinancialData,
        profile: Any,
        wacc_min: Optional[float] = None,
        wacc_max: Optional[float] = None,
        tvg_min: Optional[float] = None,
        tvg_max: Optional[float] = None,
    ) -> SensitivityMatrix:
        from config import DCFConfig
        from forecasts.forecast import ForecastEngine
        from config import ScenarioType

        # 1. Compute base scenario to anchor matrix center
        base = DCFModel(forecast_horizon=self.horizon)
        base_res = base.calculate(data, profile)
        base_wacc = base_res.breakdown.get("wacc") if base_res.is_success() else None
        base_tg = base_res.breakdown.get("terminal_growth") if base_res.is_success() else None
        base_tg_low = base_res.breakdown.get("terminal_growth_low")
        base_tg_high = base_res.breakdown.get("terminal_growth_high")

        # 2. Build rows = WACC values: centered at base_wacc with 0.5% step, steps columns
        if base_wacc is not None:
            n = self.steps
            half = n // 2
            step_w = 0.005  # 0.5% increments
            waccs = [base_wacc + (i - half) * step_w for i in range(n)]
        else:
            waccs = list(np.linspace(wacc_min or SENSITIVITY_WACC_MIN,
                                      wacc_max or SENSITIVITY_WACC_MAX, self.steps))
        # Ensure WACC stays within sane positive bounds
        waccs = [max(0.02, min(0.30, w)) for w in waccs]

        # 3. Build cols = TVG values: cover [tg_low, tg_high] + extra with 0.25% step, OR use base centered
        if base_tg is not None and base_tg_low is not None and base_tg_high is not None:
            # Always include base_tg_low, base_tg, base_tg_high explicitly
            # Pad to self.steps using 0.25% step outward
            pad = 0.0025
            span = max(base_tg_high - base_tg_low, 0.0025)
            lo = base_tg_low - pad
            hi = base_tg_high + pad
            # ensure at least 3 distinct points
            if hi - lo < 0.0075:
                hi = lo + 0.0075
            tvgs = list(np.linspace(lo, hi, self.steps))
            # Ensure tg < wacc (any wacc row min) to not break Gordon for all cells
            any_valid_wacc = min(waccs)
            tvgs = [min(max(0.01, t), any_valid_wacc - 0.001) for t in tvgs]
        else:
            tvgs = list(np.linspace(tvg_min or SENSITIVITY_TVG_MIN,
                                     tvg_max or SENSITIVITY_TVG_MAX, self.steps))

        from forecasts.nwc_utils import business_type_from_profile

        forecast_engine = ForecastEngine(
            horizon_years=self.horizon,
            business_type=business_type_from_profile(profile),
        )
        base_forecasts = forecast_engine.build_all(data).get(ScenarioType.BASE, [])
        if not base_forecasts:
            base_forecasts = forecast_engine._build_scenario(data, ScenarioType.BASE) or []

        matrix: List[List[Optional[float]]] = []
        for w in waccs:
            row: List[Optional[float]] = []
            for tg in tvgs:
                try:
                    if not base_forecasts:
                        row.append(None)
                        continue
                    pv_explicit = 0.0
                    last_fcf = 0.0
                    for i, fp in enumerate(base_forecasts):
                        t_idx = i + 1
                        fcf = fp.free_cash_flow or 0.0
                        last_fcf = fcf
                        pv_explicit += fcf / (1 + w) ** t_idx
                    n = len(base_forecasts)
                    if last_fcf <= 0:
                        last_fcf = sum(abs(p.free_cash_flow or 0) for p in base_forecasts) / max(1, len(base_forecasts)) or 1.0
                    if w > tg:
                        tv = (last_fcf * (1 + tg)) / (w - tg)
                    else:
                        tv = (last_fcf * (1 + tg)) / max(1e-3, w - tg + 1e-3)
                    pv_tv = tv / (1 + w) ** n
                    ev = pv_explicit + pv_tv
                    net_debt = data.market.net_debt_or_zero()
                    eq = ev - net_debt
                    shares = base_forecasts[-1].shares_outstanding or (
                        data.ttm.shares_outstanding if data.ttm else None
                    )
                    if shares and shares > 0 and eq is not None:
                        pps = eq / shares
                        row.append(round(pps, 2) if 0 <= pps <= 1e6 else None)
                    else:
                        row.append(None)
                except Exception:
                    row.append(None)
            matrix.append(row)

        br = min(range(len(waccs)), key=lambda i: abs(waccs[i] - (base_wacc or waccs[len(waccs)//2])))
        bc = min(range(len(tvgs)), key=lambda i: abs(tvgs[i] - (base_tg or tvgs[len(tvgs)//2])))
        return SensitivityMatrix(
            title="WACC vs Terminal Growth — Value per Share ($) (centered on actual base)",
            rows=[round(w, 6) for w in waccs],
            cols=[round(t, 6) for t in tvgs],
            row_label="WACC",
            col_label="Terminal g",
            values=matrix,
            base_row_idx=br,
            base_col_idx=bc,
        )

    def growth_vs_margin(
        self, data: FinancialData, profile: Any
    ) -> SensitivityMatrix:
        from config import DCFConfig, DEFAULT_SCENARIO_CONFIG, ScenarioConfig
        from forecasts.forecast import ForecastEngine
        steps = self.steps
        grs = np.linspace(-0.10, 0.40, steps)
        oms = np.linspace(0.05, 0.40, steps)
        matrix: List[List[Optional[float]]] = []
        base = DCFModel(forecast_horizon=self.horizon)
        base_res = base.calculate(data, profile)
        wacc = (
            base_res.breakdown.get("wacc")
            if base_res.is_success()
            else SENSITIVITY_FALLBACK_WACC
        )
        tg = (
            base_res.breakdown.get("terminal_growth")
            if base_res.is_success()
            else SENSITIVITY_FALLBACK_TERMINAL_GROWTH
        )

        for om in oms:
            row: List[Optional[float]] = []
            for gr in grs:
                try:
                    pps = self._project_value(data, gr, om, wacc, tg, profile)
                    row.append(round(pps, 2) if pps else None)
                except Exception:
                    row.append(None)
            matrix.append(row)

        return SensitivityMatrix(
            title="Revenue CAGR vs Op Margin — Value per Share ($)",
            rows=[round(o * 100, 1) for o in oms],
            cols=[round(g * 100, 1) for g in grs],
            row_label="Op Margin (%)",
            col_label="Revenue CAGR (%)",
            values=matrix,
            base_row_idx=steps // 2,
            base_col_idx=steps // 2,
        )

    def _project_value(
        self,
        data: FinancialData,
        cagr: float,
        om: float,
        wacc: float,
        tg: float,
        profile: Any = None,
    ) -> Optional[float]:
        from forecasts.fcf_projection import equity_value_per_share

        return equity_value_per_share(
            data, profile, cagr, om, wacc, tg, self.horizon
        )


__all__ = ["SensitivityAnalyzer", "SensitivityMatrix"]
