#!/usr/bin/env python3
"""
Refresh price/return fields in us.json using yfinance EOD data.
Keeps static fields (sector, industry, themes, per, forward_per, roe,
earnings_growth, marcap_usd, inst_net_20d, for_net_20d, etc.) unchanged.
Only recalculates: ret_*, gap_52w_high, high_52w, price, price_date,
mom_score, price_score, combined.

Recovered from scratchpad 2026-09-28 (see scripts/README.md) — originally
written 2026-09-24, never committed. Path made relative to repo layout;
added no-regression gate for static fields and a NaN/Infinity sanitizer
(see README "알려진 사고").

Run: ~/.venv-trading/bin/python3 refresh_us_prices.py
"""
import json, math, time, sys
from datetime import datetime, timedelta
from pathlib import Path
import yfinance as yf
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
US_JSON = BASE / "data" / "us.json"

with open(US_JSON) as f:
    us = json.load(f)
stocks = us["stocks"]
symbols = [s["symbol"] for s in stocks]
print(f"Loaded {len(stocks)} US stocks")

# ── Baseline fill-rates for STATIC fields (must not regress) ───────────────
STATIC_FIELDS = ["sector", "sector_raw", "industry", "themes", "per",
                  "forward_per", "roe", "earnings_growth", "marcap_usd",
                  "inst_net_20d", "for_net_20d"]

def _filled(v):
    return v is not None and v != [] and v != ""

baseline = {f: sum(1 for s in stocks if _filled(s.get(f))) for f in STATIC_FIELDS}
print("Baseline static-field fill counts:", baseline)

end_dt = datetime.now() + timedelta(days=1)
start_dt = end_dt - timedelta(days=420)
start_str = start_dt.strftime("%Y-%m-%d")
end_str = end_dt.strftime("%Y-%m-%d")
print(f"Fetching {start_str} → {end_str}")

BATCH = 100
all_prices = {}
for i in range(0, len(symbols), BATCH):
    batch = symbols[i:i+BATCH]
    print(f"  Batch {i//BATCH+1}/{math.ceil(len(symbols)/BATCH)}: {batch[0]}...", flush=True)
    try:
        df = yf.download(batch, start=start_str, end=end_str, auto_adjust=True, progress=False, threads=True)
        if df is None or df.empty:
            continue
        close_df = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": batch[0]})
        for sym in batch:
            if sym in close_df.columns:
                series = close_df[sym].dropna()
                if len(series) >= 20:
                    all_prices[sym] = series
    except Exception as e:
        print(f"  Error: {e}")
    time.sleep(0.2)

print(f"Got prices for {len(all_prices)} / {len(symbols)}")

def cal_return(series, weeks):
    today_idx = series.index[-1]
    target = today_idx - pd.Timedelta(days=7*weeks)
    past = series[series.index <= target]
    if len(past) == 0:
        return None
    p0 = float(past.iloc[-1])
    p1 = float(series.iloc[-1])
    if p0 <= 0:
        return None
    return (p1/p0 - 1) * 100

def percentrank(arr, v):
    valid = [x for x in arr if x is not None and not math.isnan(x)]
    if len(valid) <= 1:
        return 50.0
    below = sum(1 for x in valid if x < v)
    return below / (len(valid) - 1) * 100

updated = 0
for s in stocks:
    sym = s["symbol"]
    if sym not in all_prices:
        continue
    ser = all_prices[sym]
    price = float(ser.iloc[-1])
    price_date = ser.index[-1].strftime("%Y-%m-%d")
    s["price"] = price
    s["price_date"] = price_date
    for weeks, key in [(1,"ret_1w"),(4,"ret_4w"),(12,"ret_12w"),(25,"ret_25w"),(52,"ret_52w")]:
        s[key] = cal_return(ser, weeks)
    # ③ 가격모멘텀 전용: 달력 기준 1개월(30일)·3개월(90일) — ①의 4w/12w와 다른 기준
    s["ret_1m"] = cal_return(ser, 30/7)   # ~30 calendar days
    s["ret_3m"] = cal_return(ser, 90/7)   # ~90 calendar days
    high_52w = float(ser.tail(365).max())
    s["high_52w"] = high_52w
    s["gap_52w_high"] = (price / high_52w - 1) * 100 if high_52w > 0 else None
    updated += 1

print(f"Updated {updated} stocks")

# Percentranks
all_rets = {k: [s.get(k) for s in stocks] for k in ["ret_1w","ret_4w","ret_12w","ret_25w","ret_52w","ret_1m","ret_3m"]}
gap_vals = [s.get("gap_52w_high") for s in stocks]

for s in stocks:
    # mom_score: ① 4/12/25/52주 PERCENTRANK 평균 (1w 제외)
    ranks = []
    for k in ["ret_4w","ret_12w","ret_25w","ret_52w"]:
        v = s.get(k)
        if v is not None:
            ranks.append(percentrank(all_rets[k], v))
    s["mom_score"] = sum(ranks)/len(ranks) if ranks else None
    # price_score: ③ 4성분 동일가중 — 1W + 1M(30일) + 3M(90일) + 52W 고가 괴리율
    parts = []
    for k in ["ret_1w","ret_1m","ret_3m"]:
        v = s.get(k)
        if v is not None:
            parts.append(percentrank(all_rets[k], v))
    g = s.get("gap_52w_high")
    if g is not None:
        parts.append(percentrank(gap_vals, g))
    s["price_score"] = sum(parts)/len(parts) if parts else None
    m, p = s.get("mom_score"), s.get("price_score")
    s["combined"] = (2*m + p)/3 if m is not None and p is not None else (m if m is not None else p)

# ── Sanitize: no non-finite float may reach json.dump ───────────────────────
def _sanitize(obj):
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj

stocks = _sanitize(stocks)
us["stocks"] = stocks

# ── Gate A: static fields must not regress (this script must not touch them) ─
after_static = {f: sum(1 for s in stocks if _filled(s.get(f))) for f in STATIC_FIELDS}
regressions = [f for f in STATIC_FIELDS if after_static[f] < baseline[f]]
if regressions:
    print("STATIC FIELD REGRESSION — aborting save:")
    for f in regressions:
        print(f"  {f}: {baseline[f]} → {after_static[f]}")
    sys.exit(1)
print("Static field check OK:", after_static)

# ── Gate B: computed-field fill-rate threshold (ret_52w only — sector/industry
#    baselines are already below the KR 99% bar for US and are not touched
#    here, so they're covered by Gate A instead, not an absolute bar) ────────
n = len(stocks)
ret52_rate = sum(1 for s in stocks if s.get("ret_52w") is not None) / n
status = "✅" if ret52_rate >= 0.90 else "❌"
print(f"  fill-rate ret_52w: {ret52_rate*100:.1f}% (min 90%) {status}")
if ret52_rate < 0.90:
    print("FILL-RATE GATE FAILED (ret_52w) — aborting save")
    sys.exit(1)

for fld in ("sector", "industry"):
    rate = sum(1 for s in stocks if s.get(fld) is not None) / n
    print(f"  fill-rate {fld}: {rate*100:.1f}% (informational — see Gate A)")

us["as_of"] = datetime.now().strftime("%Y-%m-%d")
with open(US_JSON, "w") as f:
    json.dump(us, f, separators=(",",":"), allow_nan=False)

# spot check
aapl = next((s for s in stocks if s["symbol"]=="AAPL"), None)
if aapl and aapl.get("ret_52w") is not None:
    print(f"AAPL: price={aapl['price']:.2f}, ret_52w={aapl.get('ret_52w'):.2f}%, price_date={aapl.get('price_date')}")
print(f"Saved us.json as_of: {us['as_of']}")
