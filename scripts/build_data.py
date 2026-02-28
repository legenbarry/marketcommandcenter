#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import date, timedelta, datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API_KEY = os.environ.get("POLYGON_API_KEY", "").strip()
if not API_KEY:
    print("POLYGON_API_KEY is required", file=sys.stderr)
    sys.exit(1)

BASE = "https://api.polygon.io"

# Display symbol -> Polygon source symbol (proxy when needed)
PROXY = {
    # Futures proxies
    "ES1!": "SPY", "NQ1!": "QQQ", "RTY1!": "IWM", "YM1!": "DIA",
    # DX/VIX proxies
    "DX-Y.NYB": "UUP", "CBOE:VIX": "VXX",
    # Metals & commodities
    "GC1!": "GLD", "SI1!": "SLV", "HG1!": "COPX", "PL1!": "PPLT", "PA1!": "PALL", "ALI1!": "CPER",
    "CL1!": "USO", "NG1!": "UNG",
    # Yield proxies
    "US2Y": "SHY", "US10Y": "IEF", "US30Y": "TLT",
    # Global indices proxies
    "^N225": "EWJ", "^KS11": "EWY", "^NSEI": "INDA", "000001.SS": "MCHI", "000300.SS": "ASHR",
    "^HSI": "EWH", "^FTSE": "EWU", "^FCHI": "EWQ", "^GDAXI": "EWG",
}

SECTIONS = {
    "futures":   ["ES1!","NQ1!","RTY1!","YM1!"],
    "dxvix":     ["DX-Y.NYB","CBOE:VIX"],
    "metals":    ["GC1!","SI1!","HG1!","PL1!","PA1!","ALI1!"],
    "commod":    ["CL1!","NG1!"],
    "yields":    ["US2Y","US10Y","US30Y"],
    "global":    ["^N225","^KS11","^NSEI","000001.SS","000300.SS","^HSI","^FTSE","^FCHI","^GDAXI"],
    "etfmain":   ["SPY","QQQ","DIA","IWM"],
    "submarket": ["IVW","IVE","IJK","IJJ","IJT","IJS","MGK","VUG","VTV"],
    "sector":    ["XLK","XLV","XLF","XLE","XLY","XLI","XLB","XLU","XLRE","XLC","XLP"],
    "sectorew":  ["RYT","RYH","RYF","RYE","RCD","RGI","RTM","RYU","EWRE","EWCO","RHS"],
    "thematic":  ["BOTZ","HACK","SOXX","ICLN","SKYY","XBI","ITA","FINX","ARKG","URA","AIQ","CIBR","ROBO","ARKK","DRIV","OGIG","ACES","PAVE","HERO","CLOU"],
    "country":   ["EWJ","EWY","INDA","MCHI","GXC","EWH","EWU","EWQ","EWG","EWZ","EWT","EWA","EWC","EWL","EWP","EWS","TUR","EWM","EPHE","THD","VNM","EWI","EWN","EWD","EWK","EWO"],
}

CRYPTO = [
    ("bitcoin", "BTC", "Bitcoin", "X:BTCUSD", "IBIT"),
    ("ethereum", "ETH", "Ethereum", "X:ETHUSD", "ETHA"),
    ("solana", "SOL", "Solana", "X:SOLUSD", "SOLQ"),
    ("ripple", "XRP", "Ripple", "X:XRPUSD", "XXRP"),
]


def api(path, params=None):
    params = params or {}
    params["apiKey"] = API_KEY
    req = Request(f"{BASE}{path}?{urlencode(params)}", headers={"User-Agent": "marketcommandcenter/1.0"})
    wait = 0.8
    for _ in range(8):
        try:
            with urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(wait)
                wait *= 1.8
                continue
            raise
    raise RuntimeError(f"API failed: {path}")


def pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round(((a / b) - 1) * 100.0, 2)


def bars_for(ticker, cache):
    if ticker in cache:
        return cache[ticker]
    today = date.today()
    start = today - timedelta(days=380)
    d = api(
        f"/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{today.isoformat()}",
        {"adjusted": "true", "sort": "asc", "limit": 5000},
    )
    rows = d.get("results", [])
    cache[ticker] = rows
    time.sleep(0.25)
    return rows


def metrics_for(ticker, cache):
    rows = bars_for(ticker, cache)
    closes = [r.get("c") for r in rows if r.get("c") is not None]
    if len(closes) < 2:
        return None

    last = closes[-1]
    prev = closes[-2]
    week_base = closes[-6] if len(closes) >= 6 else closes[0]
    high52 = max(closes)

    jan1 = datetime(date.today().year, 1, 1, tzinfo=timezone.utc)
    ytd_base = closes[0]
    for r in rows:
        ts, c = r.get("t"), r.get("c")
        if ts is None or c is None:
            continue
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        if dt >= jan1:
            ytd_base = c
            break

    tail = closes[-5:] if len(closes) >= 5 else closes + [closes[-1]] * (5 - len(closes))
    spark = []
    prv = tail[0]
    for c in tail:
        spark.append(round((0.0 if prv in (0, None) else ((c / prv) - 1) * 100.0), 2))
        prv = c

    ema_uptrend = None
    if len(closes) >= 20:
        ema10 = sum(closes[-10:]) / 10
        ema20 = sum(closes[-20:]) / 20
        ema_uptrend = ema10 > ema20

    return {
        "price": round(last, 4 if last < 10 else 2),
        "d1": pct(last, prev) or 0.0,
        "w1": pct(last, week_base) or 0.0,
        "hi52": pct(last, high52) or 0.0,
        "ytd": pct(last, ytd_base) or 0.0,
        "spark": spark,
        "ema_uptrend": ema_uptrend,
    }


def merge_section(seed_rows, symbols, cache):
    # Preserve name/flag/holdings-friendly metadata from seed rows
    by_sym = {r.get("sym"): r for r in seed_rows}
    out = []
    for sym in symbols:
        src = PROXY.get(sym, sym)
        m = metrics_for(src, cache)
        if not m:
            # keep stale row if available, but still non-demo/real-origin historical structure
            if sym in by_sym:
                out.append(by_sym[sym])
            continue
        base = by_sym.get(sym, {"sym": sym})
        row = dict(base)
        row.update(m)
        row["sym"] = sym
        out.append(row)
    return out


def crypto_rows(seed, cache):
    by_sym = {r.get("sym"): r for r in seed}
    out = []
    for cid, sym, name, spot, etf_proxy in CRYPTO:
        m = metrics_for(spot, cache)
        if not m:
            m = metrics_for(etf_proxy, cache)
        if not m:
            if sym in by_sym:
                out.append(by_sym[sym])
            continue
        base = by_sym.get(sym, {"id": cid, "sym": sym, "name": name})
        row = dict(base)
        row.update(m)
        row["id"] = cid
        row["sym"] = sym
        row["name"] = row.get("name") or name
        out.append(row)
    return out


def main():
    path = "data/data.json"
    if not os.path.exists(path):
        print("Missing seed file data/data.json", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        data = json.load(f)

    cache = {}

    for k, syms in SECTIONS.items():
        seed_rows = data.get(k, [])
        rows = merge_section(seed_rows, syms, cache)

        # sort ranked sections by w1 descending
        if k in ("submarket", "sector", "sectorew", "thematic", "country"):
            rows.sort(key=lambda r: r.get("w1", -999), reverse=True)

        # keep yield 1D in bps style for UI function bps()
        if k == "yields":
            for r in rows:
                r["d1"] = round((r.get("d1", 0.0) * 10.0), 1)

        data[k] = rows

    data["crypto"] = crypto_rows(data.get("crypto", []), cache)
    data["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    print("Updated all dashboard sections natively from Polygon")


if __name__ == "__main__":
    main()
