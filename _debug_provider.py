"""Debug script to inspect Yahoo provider intermediate outputs."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _fix_proxy_env() -> None:
    for _key in ("NO_PROXY", "no_proxy"):
        _val = os.environ.get(_key)
        if not _val: continue
        _parts = [p.strip() for p in _val.split(",") if p.strip()]
        _clean = [p for p in _parts if not (p.startswith("::") or p == "::1" or p == "::") and not ("/" in p and p.startswith("::"))]
        if "localhost" not in _clean: _clean.append("localhost")
        if "127.0.0.1" not in _clean: _clean.append("127.0.0.1")
        os.environ[_key] = ",".join(_clean)
_fix_proxy_env()

import httpx, re
from datetime import datetime

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

def main():
    ticker = "AAPL"
    with httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=True, headers={"User-Agent": UA}) as client:
        # --- 1) chart v8 ---
        r1 = client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=10y&interval=1mo&includePrePost=false&events=div%2Csplits")
        print("=== CHART STATUS:", r1.status_code)
        chart = r1.json()
        meta = (chart.get("chart", {}).get("result") or [{}])[0].get("meta", {})
        print("Meta keys:", sorted(meta.keys()))
        for k in ["symbol","exchangeName","currency","regularMarketPrice","shortName","longName","chartPreviousClose","previousClose","sharesOutstanding"]:
            print(f"  meta.{k} = {meta.get(k)!r}")

        # --- 2) profile ---
        r2 = client.get(f"https://finance.yahoo.com/quote/{ticker}/profile/")
        print("\n=== PROFILE STATUS:", r2.status_code, "len:", len(r2.text))
        txt = r2.text
        # dump a sample of the page around any sector/beta script
        m = re.search(r'"(sector|industry|shortName|longName|beta)"\s*:\s*"?([^,}\]\n]+)"?', txt)
        if m:
            i = m.start()
            snippet = txt[max(0,i-200):i+400]
            print("Profile snippet around first field match:")
            print(snippet)
        else:
            # try to find any JSON-like context with company info
            for needle in ["Apple", "AAPL", "sector", "beta"]:
                idx = txt.find(needle)
                if idx >= 0:
                    print(f"Found '{needle}' at pos {idx}")
                    print(txt[max(0,idx-100):idx+300])
                    print("---")

        # try different regex: root.App.main = {...}
        mm = re.search(r'root\.App\.main\s*=\s*(\{.*?\});\s*</script>', txt, flags=re.DOTALL)
        if mm:
            print("\n=== FOUND root.App.main block, len:", len(mm.group(1)))
            blob = mm.group(1)
            import json
            try:
                data = json.loads(blob)
                def walk(d, depth=0, path=""):
                    if depth > 6: return
                    if isinstance(d, dict):
                        for k,v in d.items():
                            if k.lower() in ("sector","industry","shortname","longname","beta","summaryprofile"):
                                print(f"  FOUND at {path}.{k} = {str(v)[:200]!r}")
                            walk(v, depth+1, f"{path}.{k}")
                    elif isinstance(d, list):
                        for i,v in enumerate(d[:3]):
                            walk(v, depth+1, f"{path}[{i}]")
                walk(data)
            except Exception as e:
                print("JSON parse err:", e)
        else:
            print("\nNO root.App.main found. Searching for script tags with 'sector':")
            for s in re.finditer(r'<script[^>]*>(.*?)</script>', txt, flags=re.DOTALL):
                body = s.group(1)
                if 'sector' in body.lower() or 'longName' in body:
                    print("  candidate script len:", len(body), body[:500])
                    print("  ...")
                    break

        # --- 3) timeseries annual/quarterly count ---
        import time
        period2 = int(time.time())
        period1 = period2 - 10*365*24*3600
        fields = ",".join([f"annual{x}" for x in ["TotalRevenue","NetIncome","GrossProfit","EBIT","EBITDA","FreeCashFlow","OperatingCashFlow","CapitalExpenditure","InterestExpense","TaxProvision","DepreciationAndAmortization","TotalAssets","TotalLiabilitiesNetMinorityInterest","CashAndCashEquivalents","TotalDebt","StockholdersEquity","OrdinarySharesNumber"]])
        fields += "," + ",".join([f"quarterly{x}" for x in ["TotalRevenue","NetIncome","GrossProfit","FreeCashFlow","OperatingCashFlow","CapitalExpenditure"]])
        r3 = client.get(f"https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{ticker}", params=dict(period1=period1, period2=period2, type=fields))
        print("\n=== TIMESERIES STATUS:", r3.status_code)
        ts = r3.json()
        results = (ts.get("timeseries", {}).get("result") or [])
        print(f"timeseries result entries: {len(results)}")
        ann_counts = {}
        q_counts = {}
        for r in results:
            meta = r.get("meta") or {}
            ttypes = meta.get("type") or []
            for t in ttypes:
                vals = r.get(t) or []
                clean = [v for v in vals if v and v.get("asOfDate") and v.get("reportedValue")]
                # latest date
                dates = [v["asOfDate"] for v in clean]
                if t.startswith("annual"):
                    ann_counts[t] = (len(clean), dates[:3])
                else:
                    q_counts[t] = (len(clean), dates[:3])
        print("\nAnnual fields (count, first 3 periods):")
        for k,v in sorted(ann_counts.items()):
            print(f"  {k}: {v[0]} rows, periods = {v[1]}")
        print("\nQuarterly fields (count, first 3 periods):")
        for k,v in sorted(q_counts.items()):
            print(f"  {k}: {v[0]} rows, periods = {v[1]}")

if __name__ == "__main__":
    main()
