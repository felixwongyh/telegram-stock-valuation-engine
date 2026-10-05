"""
tests/conftest.py - Synthetic test fixtures
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data import FinancialNormalizer, SyntheticDataProvider, DataValidator
from classification.classifier import BusinessClassifier


@pytest.fixture(scope="session")
def synthetic_provider():
    return SyntheticDataProvider()


@pytest.fixture(scope="session")
def aapl_data(synthetic_provider):
    data = synthetic_provider.get_financial_data("AAPL")
    data = FinancialNormalizer.normalize_all(data)
    data = DataValidator.validate(data)
    return data


@pytest.fixture(scope="session")
def msft_data(synthetic_provider):
    data = synthetic_provider.get_financial_data("MSFT")
    data = FinancialNormalizer.normalize_all(data)
    data = DataValidator.validate(data)
    return data


@pytest.fixture(scope="session")
def nvda_data(synthetic_provider):
    data = synthetic_provider.get_financial_data("NVDA")
    data = FinancialNormalizer.normalize_all(data)
    data = DataValidator.validate(data)
    return data


@pytest.fixture(scope="session")
def aapl_profile(aapl_data):
    return BusinessClassifier().classify(aapl_data)
