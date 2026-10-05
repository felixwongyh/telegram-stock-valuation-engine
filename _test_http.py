import os
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Fix NO_PROXY first
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

symbol = 'AAPL'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

print('--- Test 1: Yahoo chart API ---')
try:
    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
        r = client.get(
            f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}',
            params={'range': '10y', 'interval': '1mo', 'includePrePost': 'false', 'events': 'div,splits'},
        )
        print(f'Status: {r.status_code}')
        if r.status_code == 200:
            data = r.json()
            result = data.get('chart', {}).get('result', [None])[0]
            if result:
                meta = result.get('meta', {})
                print('Symbol:', meta.get('symbol'))
                print('Price:', meta.get('regularMarketPrice'))
                print('Currency:', meta.get('currency'))
                print('Exchange:', meta.get('exchangeName'))
                print('MarketCap:', meta.get('marketCap'))
                ts = result.get('timestamp', [])
                print('Monthly bars:', len(ts))
                quotes = result.get('indicators', {}).get('quote', [{}])[0]
                closes = [c for c in quotes.get('close', []) if c is not None]
                if closes:
                    print('Last 5 closes:', closes[-5:])
except Exception as e:
    print(f'httpx ERROR: {e}')
    import traceback
    traceback.print_exc()

print()

print('--- Test 2: Yahoo quote summary (for info fields) ---')
try:
    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as client:
        modules = ['price', 'summaryDetail', 'defaultKeyStatistics', 'financialData', 'balanceSheetHistory', 'incomeStatementHistory', 'cashflowStatementHistory']
        r = client.get(
            f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}',
            params={'modules': ','.join(modules)},
        )
        print(f'Status: {r.status_code}')
        if r.status_code == 200:
            d = r.json()
            res = d.get('quoteSummary', {}).get('result', [None])[0]
            if res:
                price = res.get('price', {})
                print('shortName:', price.get('shortName'))
                print('longName:', price.get('longName'))
                print('sector:', res.get('summaryProfile', {}).get('sector') if res.get('summaryProfile') else 'N/A')
                print('regularMarketPrice:', price.get('regularMarketPrice', {}).get('raw'))
                sd = res.get('summaryDetail', {})
                print('trailingPE:', sd.get('trailingPE', {}).get('raw'))
                print('beta:', sd.get('beta', {}).get('raw'))
                print('marketCap:', price.get('marketCap', {}).get('raw'))
                fdata = res.get('financialData', {})
                print('totalRevenue:', fdata.get('totalRevenue', {}).get('raw'))
                print('ebitda:', fdata.get('ebitda', {}).get('raw'))
                dks = res.get('defaultKeyStatistics', {})
                print('sharesOutstanding:', dks.get('sharesOutstanding', {}).get('raw'))
                print('bookValue:', dks.get('bookValue', {}).get('raw'))
                print('totalDebt:', fdata.get('totalDebt', {}).get('raw'))
                print('totalCash:', fdata.get('totalCash', {}).get('raw'))
except Exception as e:
    print(f'quoteSummary ERROR: {e}')
    import traceback
    traceback.print_exc()
