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
    r = client.get(f"https://finance.yahoo.com/quote/{ticker}/profile/")
    txt = r.text
    print("page len:", len(txt))
    # 找所有 script 标签
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', txt, flags=re.DOTALL)
    print(f"scripts: {len(scripts)}")
    for i, s in enumerate(scripts):
        # 找到包含 symbol 且等于 ticker（或其公司名）的 JSON
        if '"symbol":"AAPL"' in s or f'"AAPL"' in s:
            # try to find JSON objects with sector/industry/beta near AAPL
            # print s around AAPL
            for m in re.finditer(r'AAPL', s):
                pos = m.start()
                print(f"script[{i}] AAPL at pos {pos}:")
                snippet = s[max(0,pos-1500):pos+1500]
                print(snippet)
                print("---")
                break
            # also try: find sector/industry around this script
            break
    # 也试试 quoteSummary API 带 crumb，通过 finance.yahoo.com 拿 cookie + crumb
    print("\n--- trying quoteSummary v11 ---")
    # first get quote page for cookies
    home = client.get("https://finance.yahoo.com/quote/AAPL")
    print("quote page:", home.status_code, "cookies count:", len(client.cookies))
    for ck in client.cookies:
        print(f"  cookie: {ck.name} = {ck.value[:60]!r}")
