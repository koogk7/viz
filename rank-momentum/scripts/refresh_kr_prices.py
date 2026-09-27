#!/usr/bin/env python3
"""
Refresh price/return fields in kr.json using yfinance EOD data.
Keeps static fields (sector, industry, themes, per, pbr, marcap,
inst_net_20d, for_net_20d, etc.) unchanged.
Only recalculates: ret_*, gap_52w_high, price, price_date, pct_*,
mom_score, price_score, combined.

Recovered from scratchpad 2026-09-28 (see scripts/README.md) — originally
written 2026-09-24, never committed. Path handling made relative to repo
layout; added no-regression gate for static fields and a NaN/Infinity
sanitizer (see README "알려진 사고").

Run: ~/.venv-trading/bin/python3 refresh_kr_prices.py
     (or any python3 with yfinance/pandas/numpy installed)
"""
import json, time, math, sys
from datetime import datetime, timedelta
from pathlib import Path
import yfinance as yf
import pandas as pd
import numpy as np

BASE = Path(__file__).resolve().parent.parent
KR_JSON = BASE / "data" / "kr.json"

# Load existing kr.json
with open(KR_JSON) as f:
    kr = json.load(f)
stocks = kr["stocks"]
print(f"Loaded {len(stocks)} stocks from kr.json")

# ── Baseline fill-rates for STATIC fields (must not regress) ───────────────
STATIC_FIELDS = ["sector", "industry", "themes", "per", "pbr", "marcap",
                  "inst_net_20d", "for_net_20d"]

def _filled(v):
    return v is not None and v != [] and v != ""

baseline = {f: sum(1 for s in stocks if _filled(s.get(f))) for f in STATIC_FIELDS}
print("Baseline static-field fill counts:", baseline)

def to_yf_ticker(code, market):
    return f"{code}.KS" if market == "KOSPI" else f"{code}.KQ"

# Fetch prices: use end = tomorrow to guarantee today's EOD is included
end_dt = datetime.now() + timedelta(days=1)
start_dt = end_dt - timedelta(days=420)
start_str = start_dt.strftime("%Y-%m-%d")
end_str = end_dt.strftime("%Y-%m-%d")
print(f"Fetching {start_str} → {end_str}")

# Build ticker list
code_to_yf = {s["code"]: to_yf_ticker(s["code"], s["market"]) for s in stocks}
all_tickers = [code_to_yf[s["code"]] for s in stocks]
codes = [s["code"] for s in stocks]

# Download in batches
BATCH = 50
all_prices = {}
for i in range(0, len(all_tickers), BATCH):
    batch_tks = all_tickers[i:i+BATCH]
    batch_codes = codes[i:i+BATCH]
    print(f"  Batch {i//BATCH+1}/{math.ceil(len(all_tickers)/BATCH)}: {batch_tks[0]}...", flush=True)
    try:
        df = yf.download(batch_tks, start=start_str, end=end_str,
                         auto_adjust=True, progress=False, threads=True)
        if df is None or df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            close_df = df["Close"]
        else:
            close_df = df[["Close"]].rename(columns={"Close": batch_tks[0]})
        for code, yf_tk in zip(batch_codes, batch_tks):
            if yf_tk in close_df.columns:
                series = close_df[yf_tk].dropna()
                if len(series) >= 20:
                    all_prices[code] = series
    except Exception as e:
        print(f"  Batch error: {e}")
    time.sleep(0.3)

print(f"Got prices for {len(all_prices)} / {len(codes)} tickers")

# Calendar return helper
def cal_return(series, weeks):
    today_idx = series.index[-1]
    target = today_idx - pd.Timedelta(days=7*weeks)
    past = series[series.index <= target]
    if len(past) == 0:
        return None
    past_price = float(past.iloc[-1])
    now_price = float(series.iloc[-1])
    if past_price <= 0:
        return None
    return (now_price / past_price - 1) * 100

# Percentrank helper
def percentrank(arr, v):
    valid = [x for x in arr if x is not None and not math.isnan(x)]
    if len(valid) <= 1:
        return 50.0
    below = sum(1 for x in valid if x < v)
    return below / (len(valid) - 1) * 100

# Recompute price/return fields for each stock
results = []
for s in stocks:
    code = s["code"]
    if code not in all_prices:
        # Keep existing data if fetch failed
        results.append(s)
        continue

    series = all_prices[code]
    r4w  = cal_return(series, 4)
    r12w = cal_return(series, 12)
    r25w = cal_return(series, 25)
    r52w = cal_return(series, 52)
    r1w  = cal_return(series, 1)
    # ③ 가격모멘텀 전용: 달력 기준 1개월(30일)·3개월(90일) — ①의 4w/12w와 다른 기준
    r1m  = cal_return(series, 30/7)   # ~30 calendar days
    r3m  = cal_return(series, 90/7)   # ~90 calendar days

    # 52W high gap
    recent_high = float(series.tail(252).max()) if len(series) >= 20 else None
    gap_52w = ((float(series.iloc[-1]) / recent_high - 1) * 100
               if recent_high and recent_high > 0 else None)

    # Build updated stock dict (preserve static fields)
    updated = dict(s)  # copy all existing fields
    updated.update({
        "ret_4w": r4w, "ret_12w": r12w, "ret_25w": r25w, "ret_52w": r52w,
        "ret_1w": r1w, "ret_1m": r1m, "ret_3m": r3m,
        "gap_52w_high": gap_52w,
        "price": float(series.iloc[-1]),
        "price_date": str(series.index[-1].date()),
    })
    results.append(updated)

# Recompute percentrank scores
for period, field, score_field in [
    (4, "ret_4w", "pct_4w"), (12, "ret_12w", "pct_12w"),
    (25, "ret_25w", "pct_25w"), (52, "ret_52w", "pct_52w"),
    ("1w", "ret_1w", "pct_1w"),
    ("1m", "ret_1m", "pct_1m"),   # 30-day — ③ 전용
    ("3m", "ret_3m", "pct_3m"),   # 90-day — ③ 전용
]:
    vals = [r.get(field) for r in results]
    for r in results:
        v = r.get(field)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            r[score_field] = None
        else:
            r[score_field] = percentrank([x for x in vals if x is not None], v)

# mom_score: ① 4·12·25·52주 PERCENTRANK 평균
for r in results:
    sub = [r.get(f"pct_{p}w") for p in [4, 12, 25, 52]]
    valid = [x for x in sub if x is not None]
    r["mom_score"] = sum(valid) / len(valid) if valid else None

# price_score: ③ 4성분 동일가중 — 1W + 1M(30일) + 3M(90일) + 52W 고가 괴리율
# 1M·3M은 ①의 4W·12W와 다른 달력 기준이라 이중 계상 없음
gap_vals = [r.get("gap_52w_high") for r in results if r.get("gap_52w_high") is not None]
for r in results:
    parts = []
    for fld in ("pct_1w", "pct_1m", "pct_3m"):
        if r.get(fld) is not None:
            parts.append(r[fld])
    g = r.get("gap_52w_high")
    if g is not None:
        parts.append(percentrank(gap_vals, g))
    r["price_score"] = sum(parts) / len(parts) if parts else None

# combined
for r in results:
    m, p = r.get("mom_score"), r.get("price_score")
    if m is not None and p is not None:
        r["combined"] = (2*m + p) / 3
    elif m is not None:
        r["combined"] = m
    else:
        r["combined"] = None

results.sort(key=lambda r: (r.get("combined") or 0), reverse=True)

# ── Sanitize: no non-finite float may reach json.dump ───────────────────────
def _sanitize(obj):
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj

results = _sanitize(results)

# ── Gate A: static fields must not regress (this script must not touch them) ─
after_static = {f: sum(1 for r in results if _filled(r.get(f))) for f in STATIC_FIELDS}
regressions = [f for f in STATIC_FIELDS if after_static[f] < baseline[f]]
if regressions:
    print("STATIC FIELD REGRESSION — aborting save:")
    for f in regressions:
        print(f"  {f}: {baseline[f]} → {after_static[f]}")
    sys.exit(1)
print("Static field check OK:", after_static)

# ── Gate B: computed-field fill-rate thresholds ─────────────────────────────
total_r = len(results)
checks = [
    ("sector",   0.99, lambda r: bool(r.get("sector"))),
    ("industry", 0.99, lambda r: bool(r.get("industry"))),
    ("themes",   0.20, lambda r: bool(r.get("themes"))),
    ("inst_net", 0.95, lambda r: r.get("inst_net_20d") is not None),
    ("ret_52w",  0.90, lambda r: r.get("ret_52w") is not None),
]
gate_errors = []
for field, threshold, pred in checks:
    rate = sum(1 for r in results if pred(r)) / total_r
    status = "✅" if rate >= threshold else "❌"
    print(f"  fill-rate {field}: {rate*100:.1f}% (min {threshold*100:.0f}%) {status}")
    if rate < threshold:
        gate_errors.append(f"{field}: {rate*100:.1f}% < {threshold*100:.0f}%")
if gate_errors:
    print(f"\nFILL-RATE GATE FAILED — aborting save:\n" + "\n".join(gate_errors))
    sys.exit(1)

# Save
today_str = datetime.now().strftime("%Y-%m-%d")
output = dict(kr)  # preserve top-level metadata
output["as_of"] = today_str
output["fetched_at"] = datetime.now().isoformat()
output["stocks"] = results

with open(KR_JSON, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, allow_nan=False)

print(f"Saved {len(results)} stocks → kr.json (as_of: {today_str})")

# Spot checks
for code, name in [("005930","삼성전자"), ("000660","SK하이닉스"), ("000500","가온전선"), ("375500","DL이앤씨")]:
    s = next((r for r in results if r["code"]==code), None)
    if s and s.get("ret_52w") is not None:
        print(f"  {name}: price={s['price']}, ret_52w={s.get('ret_52w'):.2f}%, price_date={s.get('price_date')}")
