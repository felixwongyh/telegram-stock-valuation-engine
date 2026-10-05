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

with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA}) as client:
    ticker = "AAPL"
    r = client.get(f"https://finance.yahoo.com/quote/{ticker}/profile/")
    txt = r.text
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', txt, flags=re.DOTALL)
    # 在每个 script 里找包含 quoteSummaryStore 或 assetProfile 的 JSON 块
    for i, s in enumerate(scripts):
        # 找 "assetProfile" 或 "quoteSummary" 节点
        if '"assetProfile"' in s or '"quoteSummary"' in s or '"summaryProfile"' in s:
            print(f"=== script[{i}] has assetProfile/quoteSummary, len={len(s)}")
            # dump all occurrences
            for key in ["assetProfile", "quoteSummary", "summaryProfile"]:
                for m in re.finditer(re.escape('"'+key+'"'), s):
                    pos = m.start()
                    print(f"  '{key}' at {pos}:")
                    print(s[max(0,pos-50):pos+1500])
                    print("  ---")
            # 整段 parse 成 json 试试：找最大的合法 JSON 对象（从 { 开始配对）
            # 策略：在第 i 个 script 中从第一个 { 开始，用括号配对找完整 json
            for start_match in re.finditer(r'\{', s):
                start = start_match.start()
                depth = 0
                end = None
                in_str = False
                esc = False
                for p in range(start, len(s)):
                    c = s[p]
                    if esc:
                        esc = False
                        continue
                    if c == '\\':
                        esc = True
                        continue
                    if c == '"':
                        in_str = not in_str
                    elif not in_str:
                        if c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                            if depth == 0:
                                end = p+1
                                break
                if end:
                    blob = s[start:end]
                    if len(blob) > 10000:
                        try:
                            d = json.loads(blob)
                            # 深度搜索 assetProfile / sector / industry
                            def walk(obj, path=""):
                                if isinstance(obj, dict):
                                    for k,v in obj.items():
                                        k_low = k.lower()
                                        if k_low in ("sector","industry","summaryprofile","assetprofile","beta"):
                                            print(f"FOUND {path}.{k} = {str(v)[:500]}")
                                            yield (f"{path}.{k}", v)
                                        yield from walk(v, f"{path}.{k}")
                                elif isinstance(obj, list):
                                    for idx,v in enumerate(obj[:10]):
                                        yield from walk(v, f"{path}[{idx}]")
                            list(walk(d))
                            break
                        except Exception as e:
                            continue
