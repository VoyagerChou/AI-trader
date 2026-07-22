"""Independent Eastmoney sector fund flow fetcher.

This script is intentionally kept separate from the main backend module tree
so it does NOT inherit AkShare's global requests/proxy configuration. The
advanced data builder calls this via subprocess to get real fund flow data.
"""
import json
import sys

import requests

SESS = requests.Session()
SESS.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://data.eastmoney.com/",
        "Accept": "application/json, text/plain, */*",
    }
)
SESS.trust_env = False

WARMUP_URL = "https://data.eastmoney.com/bkzj/hy.html"
URL = "https://push2.eastmoney.com/api/qt/clist/get"
PARAMS = {
    "pn": "1",
    "pz": "100",
    "po": "1",
    "np": "1",
    "ut": "b2884a393a59ad64002292a3e90d46a5",
    "fltt": "2",
    "invt": "2",
    "fid0": "f62",
    "fs": "m:90 t:2",
    "stat": "1",
    "fields": "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124",
    "rt": "52975239",
}
TIMEOUT = 15
MAX_ATTEMPTS = 3


def main() -> int:
    for attempt in range(MAX_ATTEMPTS):
        try:
            # Warm up cookies / anti-bot tokens from the actual page first.
            SESS.get(WARMUP_URL, timeout=TIMEOUT)

            import time

            params = dict(PARAMS)
            params["_"] = int(time.time() * 1000)
            r = SESS.get(URL, params=params, timeout=TIMEOUT)
            data = r.json()
            rows = (data.get("data") or {}).get("diff") or []
            if not rows:
                sys.stderr.write(f"Attempt {attempt+1}: empty rows\n")
                continue
            out = []
            for row in rows:
                out.append(
                    {
                        "name": str(row.get("f14", "")).strip(),
                        "net_inflow_main": float(row.get("f62") or 0),
                        "net_inflow_super_large": float(row.get("f66") or 0),
                        "net_inflow_large": float(row.get("f72") or 0),
                        "net_inflow_ratio": float(row.get("f184") or 0),
                    }
                )
            json.dump(out, sys.stdout, ensure_ascii=True)
            return 0
        except Exception as exc:
            sys.stderr.write(f"Attempt {attempt+1} error: {exc}\n")
            continue
    json.dump([], sys.stdout, ensure_ascii=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
