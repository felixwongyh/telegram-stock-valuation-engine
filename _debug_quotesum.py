import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
def _fix_proxy_env():
    for _key in ("NO_PROXY", "no_proxy"):
        _val = os.environ.get(_key)
        if not _val: continue
        _parts = [p.strip() for p in _val.split(",") if p.strip()]
        _clean = [p for p in _parts if not (p.startswith("::") or p == "::1" or p == "::") and not ("/" in p and p.startswith("::"))]
        if "localhost" not in _clean: _clean.append("localhost")
        if "127.0.0.1" not in _clean: _clean.append("127.0.0.1")
        os.environ[_key] = ",".join(_clean)
_fix_proxy_env()
import httpx, re, json
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
ticker = "AAPL"
with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA}) as client:
    # 改用 quoteSummary API: 先用 query2 的 quote/v6/finance/quoteSummary（与 timeseries 同域，也无 crumb？）
    # 或者 /v10/finance/quoteSummary 要 crumb，但试试
    urls = [
        f"https://query2.finance.yahoo.com/quoteSummary/{ticker}?modules=assetProfile,summaryProfile,defaultKeyStatistics,financialData,price",
        f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=assetProfile,summaryProfile,defaultKeyStatistics,financialData,price",
    ]
    for u in urls:
        r = client.get(u, timeout=20)
        print("URL:", u[:80], "...")
        print("status:", r.status_code, "len:", len(r.text))
        try:
            data = r.json()
            print("json parsed. keys top:", list(data.keys())[:5])
            # assetProfile / summaryProfile
            qs = (data.get("quoteSummary") or {}).get("result") or []
            if qs:
                res = qs[0]
                for k in ["assetProfile", "summaryProfile", "defaultKeyStatistics", "financialData", "price"]:
                    v = res.get(k)
                    if v:
                        print(f"  {k}:")
                        if isinstance(v, dict):
                            for sk in ["sector","industry","beta","shortName","longName"]:
                                if sk in v:
                                    print(f"    {sk} = {v[sk]}")
        except Exception as e:
            print("json err:", e)
            print(r.text[:500])
        print("---")
