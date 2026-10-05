from data import DataValidator, FinancialNormalizer, SyntheticDataProvider
from config import REPORT_SECTION_TITLES
from reporting.dashboard import ValuationReportBuilder


def test_report_titles_and_labels_are_chinese():
    data = SyntheticDataProvider().get_financial_data("MSFT")
    data = FinancialNormalizer.normalize_all(data)
    data = DataValidator.validate(data)

    market_section = ValuationReportBuilder._market_section(data)

    assert REPORT_SECTION_TITLES["business"] == "🏢 业务"
    assert "当前价格" in market_section
    assert "市值" in market_section
