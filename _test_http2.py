import os
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

for _k in ("NO_PROXY", "no_proxy"):
    _v = os.environ.get(_k)
    if _v:
        _parts = [p.strip() for p in _v.split(",") if p.strip()]
        _clean = [
            p for p in _parts
            if not (p.startswith("::") or p == "::1" or p == "::")
            and not ("/" in p and p.startswith("::"))
        ]
        if "localhost" not in _clean:
            _clean.append("localhost")
        if "127.0.0.1" not in _clean:
            _clean.append("127.0.0.1")
        os.environ[_k] = ",".join(_clean)

import httpx
import json

symbol = 'AAPL'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

print('--- Test 3: Yahoo v8 finance chart + fundamentals ---')
try:
    with httpx.Client(timeout=25, follow_redirects=True, headers=headers) as client:
        # First warm up cookie
        client.get('https://finance.yahoo.com/quote/AAPL', timeout=15)

        modules = [
            'summaryProfile',
            'price',
            'summaryDetail',
            'defaultKeyStatistics',
            'financialData',
            'incomeStatementHistory',
            'balanceSheetHistory',
            'cashflowStatementHistory',
            'incomeStatementHistoryQuarterly',
            'balanceSheetHistoryQuarterly',
            'cashflowStatementHistoryQuarterly',
        ]
        r = client.get(
            f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}',
            params={'modules': ','.join(modules)},
        )
        print(f'quoteSummary Status: {r.status_code}')
        if r.status_code != 200:
            print(f'Response snippet: {r.text[:500]}')
            # Try alternative endpoint
            print('\n--- Trying timeseries alternative ---')
            r2 = client.get(
                f'https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}',
                params={
                    'period1': str(int(__import__('time').time()) - 3600*24*365*8),
                    'period2': str(int(__import__('time').time()) + 3600*24),
                    'type': 'annualTotalRevenue,annualNetIncome,annualGrossProfit,annualEbit,annualEbitda,annualFreeCashFlow,annualOperatingCashFlow,annualCapitalExpenditure,annualInterestExpense,annualTaxProvision,annualDepreciationAndAmortization,annualTotalAssets,annualTotalLiabilitiesNetMinorityInterest,annualCashAndCashEquivalents,annualTotalDebt,annualStockholdersEquity,annualOrdinarySharesNumber,quarterlyTotalRevenue,quarterlyNetIncome,quarterlyGrossProfit,quarterlyFreeCashFlow,quarterlyOperatingCashFlow,quarterlyCapitalExpenditure',
                },
            )
            print(f'timeseries Status: {r2.status_code}')
            if r2.status_code == 200:
                d2 = r2.json()
                res2 = d2.get('timeseries', {}).get('result', [])
                print(f'Got {len(res2)} result entries')
                for entry in res2[:10]:
                    meta = entry.get('meta', {})
                    ttypes = meta.get('type', [])
                    for t in ttypes[:1]:
                        vals = entry.get(t, [])
                        valid = [v for v in vals if v and v.get('reportedValue', {}).get('raw') is not None]
                        if valid:
                            print(f'  {t}: {len(valid)} periods')
except Exception as e:
    print(f'ERROR: {e}')
    import traceback
    traceback.print_exc()
