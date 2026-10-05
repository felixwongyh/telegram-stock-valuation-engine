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
    txt = client.get(f"https://finance.yahoo.com/quote/{ticker}/profile/").text
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', txt, flags=re.DOTALL)
    for i, s in enumerate(scripts):
        # 寻找 AAPL 的行业关键词：Technology / Consumer Electronics / Apple Inc
        for needle in ["Technology", "Consumer Electronics", "sector"]:
            if needle in s:
                print(f"script[{i}] contains '{needle}', len={len(s)}")
                idx = s.find(needle)
                print(s[max(0,idx-200):idx+400])
                print("---")
                break
        # 或者找带完整 JSON 的大脚本：找类似 `{"AAPL":` 或包含完整 assetProfile 的块
    # 也直接搜 HTML 中的行业 / 板块（不用 script）
    print("\n=== HTML search for sector/industry ===")
    for pat in [r'>Sector<.*?<td[^>]*>(.*?)</td>', r'>Industry<.*?<td[^>]*>(.*?)</td>']:
        m = re.search(pat, txt, flags=re.DOTALL)
        if m:
            print("match:", pat, m.group(1))
    # 使用 beta
    for pat in [r'>Beta<.*?<td[^>]*>(.*?)</td>']:
        m = re.search(pat, txt, flags=re.DOTALL)
        if m:
            print("beta match:", m.group(1))
