"""SOLVED eligibility gate for the reverse DCF.

A `SOLVED` status is a promise: "this implied growth is a real number, obtained
from a converged root of the model the report describes, on valid inputs". Each
clause of that promise is a separate way to be wrong, and this module checks them
all in one place so the promise is enforced rather than assumed.

The gate is deliberately *additive*: it never upgrades a status, only demotes it.
Callers run the solver as before and then ask "is this really SOLVED?".

Conditions (all must hold):

 1. price and share count are finite and positive
 2. target EV, WACC and terminal growth are finite
 3. the projection inputs that actually drive the solve are usable
 4. the model is applicable to this business type
 5. no data-quality warning blocks the solve
 6. the solver reports convergence
 7. the root is independently recomputed and matches
 8. price residual <= price_residual_tol
 9. reported EV, CAGR and value per share are finite
10. the growth band and the chosen root are explicitly recorded
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class EligibilityResult:
    """Outcome of the eligibility gate.

    ``ok`` is True only when every condition passed. ``failed`` lists the
    conditions that did not, so a demotion is never silent: the caller can put
    the reason in the report instead of degrading the status anonymously.
    """

    ok: bool
    failed: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)

    def note(self) -> Optional[str]:
        if self.ok:
            return None
        return "SOLVED 资格门禁未通过：" + "；".join(self.failed)


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def check_solved_eligibility(
    *,
    price: Any,
    shares: Any,
    target_ev: Any,
    wacc: Any,
    terminal_growth: Any,
    solver_meta: dict,
    implied_revenue_cagr: Any,
    value_per_share: Any,
    growth_band_verdict: Any,
    projection_inputs_ok: bool = True,
    model_applicable: bool = True,
    data_quality_blocking: bool = False,
    price_residual_tol: float = 1e-4,
    recompute_ev: Optional[Callable[[float], float]] = None,
) -> EligibilityResult:
    """Evaluate the ten SOLVED conditions.

    ``recompute_ev`` is called with the solved growth to obtain an *independent*
    EV. Passing it makes condition 7 a real check; omitting it marks condition 7
    as unverified, which fails the gate - an unverified promise is not a kept one.
    """
    meta = solver_meta or {}
    checks: dict[str, bool] = {}
    failed: list[str] = []

    checks["finite_price_and_shares"] = (
        _finite(price) and price > 0 and _finite(shares) and shares > 0
    )
    checks["finite_target_wacc_tg"] = (
        _finite(target_ev) and _finite(wacc) and _finite(terminal_growth)
    )
    checks["projection_inputs_ok"] = bool(projection_inputs_ok)
    checks["model_applicable"] = bool(model_applicable)
    checks["no_blocking_data_quality"] = not bool(data_quality_blocking)
    checks["solver_converged"] = bool(meta.get("converged"))
    checks["residual_within_tolerance"] = (
        _finite(meta.get("relative_residual"))
        and meta["relative_residual"] <= price_residual_tol
    )
    checks["outputs_finite"] = (
        _finite(target_ev) and _finite(implied_revenue_cagr) and _finite(value_per_share)
    )
    checks["band_and_root_recorded"] = (
        growth_band_verdict is not None
        and bool(meta.get("search_bounds"))
        and meta.get("solver_method") is not None
    )

    # Condition 7: an independent recomputation of the root.
    if recompute_ev is None or not _finite(implied_revenue_cagr):
        checks["root_independently_recomputed"] = False
    else:
        try:
            recomputed = recompute_ev(float(implied_revenue_cagr))
            if not _finite(recomputed) or not _finite(target_ev) or target_ev == 0:
                checks["root_independently_recomputed"] = False
            else:
                rel = abs(recomputed - target_ev) / abs(target_ev)
                checks["root_independently_recomputed"] = (
                    _finite(rel) and rel <= price_residual_tol
                )
        except Exception:  # noqa: BLE001 - any failure to recompute is a failure to verify
            checks["root_independently_recomputed"] = False

    labels = {
        "finite_price_and_shares": "1 价格/股数非有限正数",
        "finite_target_wacc_tg": "2 目标EV/WACC/终值增长非有限",
        "projection_inputs_ok": "3 投影输入不可用",
        "model_applicable": "4 模型不适用于该业务类型",
        "no_blocking_data_quality": "5 存在阻断求解的数据质量告警",
        "solver_converged": "6 求解器未收敛",
        "root_independently_recomputed": "7 根未能独立复核",
        "residual_within_tolerance": "8 残差超出容差",
        "outputs_finite": "9 输出含非有限数值",
        "band_and_root_recorded": "10 增长区间/根未明确记录",
    }
    for key, ok in checks.items():
        if not ok:
            failed.append(labels.get(key, key))

    return EligibilityResult(ok=not failed, failed=failed, checks=checks)
