"""
models/router.py - Valuation Model Router
Selects and runs applicable models based on business classification.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from config import get_logger
from data.models import CompanyProfile, FinancialData
from models.base import ValuationModel, ValuationResult
from models.bank import BankDDMModel
from models.dcf import DCFModel
from models.nav import REITNAVModel
from models.multiples import (
    EVEBITDAModel,
    EVSalesModel,
    FCFYieldModel,
    PBModel,
    PEModel,
)
from models.reverse_dcf import ReverseDCFModel
from models.sotp import SOTPModel

log = get_logger("models.router")


NAME_TO_MODEL: Dict[str, ValuationModel] = {
    "DCF": DCFModel(),
    "ReverseDCF": ReverseDCFModel(),
    "P/E": PEModel(),
    "EV/EBITDA": EVEBITDAModel(),
    "EV/Sales": EVSalesModel(),
    "P/B": PBModel(),
    "FCF Yield": FCFYieldModel(),
    "Historical Multiples": PEModel(),
    "SOTP": SOTPModel(),
    "REIT NAV": REITNAVModel(),
    "Bank DDM": BankDDMModel(),
    "Bank RIM": BankDDMModel(),
}


class ModelRouter:
    """Runs all applicable models and collects results."""

    def __init__(self) -> None:
        self._models = dict(NAME_TO_MODEL)

    def run_all(
        self,
        data: FinancialData,
        profile: CompanyProfile,
        model_names: Optional[List[str]] = None,
    ) -> Dict[str, ValuationResult]:
        results: Dict[str, ValuationResult] = {}
        names = model_names or profile.applicable_models
        for name in names:
            mdl = self._models.get(name)
            if mdl is None:
                log.info(f"Skipping {name}: model not yet implemented")
                continue
            try:
                r = mdl.run(data, profile)
                results[name] = r
            except Exception as e:
                log.exception(f"Model {name} failed: {e}")
                from config import SolverStatus
                results[name] = ValuationResult(
                    model_name=name,
                    status=SolverStatus.INFEASIBLE,
                    notes=[f"Unhandled exception: {e}"],
                )
        return results

    def run_single(
        self, data: FinancialData, profile: CompanyProfile, model_name: str
    ) -> Optional[ValuationResult]:
        r = self.run_all(data, profile, model_names=[model_name])
        return r.get(model_name)


__all__ = ["ModelRouter"]
