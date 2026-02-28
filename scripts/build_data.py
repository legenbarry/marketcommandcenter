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

SYMBOL_MAP = {
    "ES1!": "SPY", "NQ1!": "QQQ", "YM1!": "DIA", "RTY1!": "IWM",
    "DXY": "UUP", "VIX": "VXX",
    "GC1!": "GLD", "SI1!": "SLV", "CL1!": "USO", "NG1!": "UNG",
    "US02Y": "SHY", "US10Y": "IEF", "US30Y": "TLT",
    "^GSPC": "SPY", "^FTSE": "EWU", "^N225": "EWJ", "^HSI": "EWH",
}


def api(path, params=None):
    params = params or {}
    params["apiKey"] = API_KEY
    url = f"{BASE}{path}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "marketcommandcenter/1.0"})
    backoff = 0.8
    for _ in range(8):
        try:
            with urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(backoff)
                backoff *= 1.7
                continue
            raise
    raise RuntimeError(f"API failed: {path}")


def ticker_stats(ticker):
    end = date.today()
    start = end - timedelta(days=21)
    d = api(f"/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{end.isoformat()}",
            {"adjusted": "true", "sort": "asc", "limit": 200})
    rows = d.get("results", [])
    closes = [r.get("c") for r in rows if r.get("c") is not None]
    if len(closes) < 2:
        return None
    last = closes[-1]
    prev = closes[-2]
    week_base = closes[-6] if len(closes) >= 6 else closes[0]
    spark_tail = closes[-5:] if len(closes) >= 5 else closes

    def pct(a, b):
        if not b:
            return 0.0
        return round(((a / b) - 1) * 100, 2)

    spark = []
    p = spark_tail[0]
    for c in spark_tail:
        spark.append(pct(c, p))
        p = c

    return {
        "price": round(last, 4 if last < 10 else 2),
        "d1": pct(last, prev),
        "w1": pct(last, week_base),
        "spark": spark,
    }


def update_rows(rows):
    for row in rows:
        sym = row.get("sym")
        src = SYMBOL_MAP.get(sym, sym)
        st = ticker_stats(src)
        if not st:
            continue
        row["price"] = st["price"]
        row["d1"] = st["d1"]
        row["w1"] = st["w1"]
        row["spark"] = st["spark"]
        if "ema_uptrend" in row:
            row["ema_uptrend"] = st["w1"] >= 0


def update_crypto(rows):
    # Keep existing crypto values if crypto access isn't available on key tier
    for r in rows:
        sym = r.get("sym")
        map_sym = {"BTC": "IBIT", "ETH": "ETHA", "SOL": "SOLZ", "XRP": "XXRP"}.get(sym)
        if not map_sym:
            continue
        st = ticker_stats(map_sym)
        if not st:
            continue
        r["d1"] = st["d1"]
        r["w1"] = st["w1"]
        r["spark"] = st["spark"]


def main():
    path = "data/data.json"
    if not os.path.exists(path):
        print("Missing data/data.json seed file", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        data = json.load(f)

    for key in ["futures", "dxvix", "metals", "commod", "yields", "global", "etfmain", "submarket", "sector", "sectorew", "thematic", "country"]:
        rows = data.get(key, [])
        update_rows(rows)

    if "crypto" in data:
        update_crypto(data["crypto"])

    data["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    print("Updated data/data.json from Polygon")


if __name__ == "__main__":
    main()
