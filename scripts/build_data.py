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
    ("bitcoin", "BTC", "Bitcoin"),
    ("ethereum", "ETH", "Ethereum"),
    ("solana", "SOL", "Solana"),
    ("ripple", "XRP", "Ripple"),
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
    try:
        d = api(
            f"/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{today.isoformat()}",
            {"adjusted": "true", "sort": "asc", "limit": 5000},
        )
        rows = d.get("results", [])
    except Exception:
        rows = []
    cache[ticker] = rows
    time.sleep(0.12)
    return rows


def metrics_from_closes(closes, timestamps_ms=None):
    if len(closes) < 2:
        return None
    last = closes[-1]
    prev = closes[-2]
    week_base = closes[-6] if len(closes) >= 6 else closes[0]
    high52 = max(closes)

    jan1 = datetime(date.today().year, 1, 1, tzinfo=timezone.utc)
    ytd_base = closes[0]
    if timestamps_ms:
        for ts, c in zip(timestamps_ms, closes):
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


def yahoo_metrics(ticker):
    try:
        req = Request(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d",
            headers={"User-Agent": "marketcommandcenter/1.0"},
        )
        with urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8"))
        res = (d.get("chart") or {}).get("result") or []
        if not res:
            return None
        r0 = res[0]
        ts = r0.get("timestamp") or []
        q = (((r0.get("indicators") or {}).get("quote") or [{}])[0])
        close = q.get("close") or []
        pairs = [(t * 1000, c) for t, c in zip(ts, close) if c is not None]
        if len(pairs) < 2:
            return None
        tms = [p[0] for p in pairs]
        cls = [float(p[1]) for p in pairs]
        return metrics_from_closes(cls, tms)
    except Exception:
        return None


def metrics_for(ticker, cache):
    rows = bars_for(ticker, cache)
    closes = [r.get("c") for r in rows if r.get("c") is not None]
    if len(closes) >= 2:
        ts = [r.get("t") for r in rows if r.get("c") is not None and r.get("t") is not None]
        return metrics_from_closes(closes, ts)
    return yahoo_metrics(ticker)


def sources_for(sym):
    primary = PROXY.get(sym, sym)
    fallbacks = {
        "US10Y": ["IEF", "VGIT", "TLH"],
        "US30Y": ["TLT", "VGLT"],
        "US2Y": ["SHY", "VGSH"],
        "DX-Y.NYB": ["UUP", "USDU"],
        "CBOE:VIX": ["VXX", "UVXY"],
    }
    out = [primary]
    out.extend(fallbacks.get(sym, []))
    seen = set()
    return [x for x in out if not (x in seen or seen.add(x))]


def merge_section(seed_rows, symbols, cache):
    # Preserve name/flag/holdings-friendly metadata from seed rows
    by_sym = {r.get("sym"): r for r in seed_rows}
    out = []
    for sym in symbols:
        m = None
        for src in sources_for(sym):
            m = metrics_for(src, cache)
            if m:
                break
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


def gecko_json(url):
    req = Request(url, headers={"User-Agent": "marketcommandcenter/1.0"})
    wait = 0.8
    for _ in range(6):
      try:
        with urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
      except HTTPError as e:
        if e.code in (429, 500, 502, 503, 504):
            time.sleep(wait)
            wait *= 1.8
            continue
        raise
    raise RuntimeError("CoinGecko API request failed")


def crypto_rows(seed, cache):
    by_sym = {r.get("sym"): r for r in seed}
    out = []

    ids = ",".join([c[0] for c in CRYPTO])
    spot = gecko_json(
        f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
    )

    jan1 = datetime(date.today().year, 1, 1, tzinfo=timezone.utc)

    for cid, sym, name in CRYPTO:
        base = by_sym.get(sym, {"id": cid, "sym": sym, "name": name})
        row = dict(base)

        # 365d daily series for w1 / 52w high / ytd / spark
        hist = gecko_json(
            f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart?vs_currency=usd&days=365&interval=daily"
        )
        prices = hist.get("prices", [])
        closes = [p[1] for p in prices if p and len(p) >= 2]
        times = [p[0] for p in prices if p and len(p) >= 2]

        if not closes:
            # keep prior row if source fails
            if sym in by_sym:
                out.append(by_sym[sym])
            continue

        last = float(spot.get(cid, {}).get("usd", closes[-1]))
        d1 = float(spot.get(cid, {}).get("usd_24h_change", 0.0) or 0.0)
        week_base = closes[-8] if len(closes) >= 8 else closes[0]
        high52 = max(closes)

        ytd_base = closes[0]
        for ts, c in zip(times, closes):
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

        row.update({
            "id": cid,
            "sym": sym,
            "name": row.get("name") or name,
            "price": round(last, 2 if last >= 100 else 4),
            "d1": round(d1, 2),
            "w1": pct(last, week_base) or 0.0,
            "hi52": pct(last, high52) or 0.0,
            "ytd": pct(last, ytd_base) or 0.0,
            "spark": spark,
        })
        out.append(row)
        time.sleep(0.35)

    return out


def fetch_mortgage_rows():
    def fred_series(series_id):
        # use raw urllib for CSV
        req = Request(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", headers={"User-Agent": "marketcommandcenter/1.0"})
        with urlopen(req, timeout=30) as r:
            csv = r.read().decode("utf-8")
        rows = []
        for line in csv.strip().split("\n")[1:]:
            d, v = line.split(",")
            if v == '.':
                continue
            rows.append((d, float(v)))
        return rows

    out = []
    for sid, label in [("MORTGAGE15US", "15-Year Fixed (US)"), ("MORTGAGE30US", "30-Year Fixed (US)")]:
        rows = fred_series(sid)
        if len(rows) < 2:
            continue
        d, latest = rows[-1]
        _, prevw = rows[-2]
        bps = round((latest - prevw) * 100, 1)
        trend = "rising" if bps > 0 else "falling" if bps < 0 else "flat"
        out.append({"tenor": label, "rate": round(latest, 2), "w1_bps": bps, "trend": trend, "date": d})
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
    try:
        data["mortgage"] = fetch_mortgage_rows()
    except Exception:
        data["mortgage"] = data.get("mortgage", [])

    data["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    print("Updated all dashboard sections natively from Polygon")


if __name__ == "__main__":
    main()
