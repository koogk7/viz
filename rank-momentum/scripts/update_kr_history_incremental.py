#!/usr/bin/env python3
"""
Incrementally append new trading dates to kr-history.json.
Uses yfinance auto_adjust=True (same source as kr.json).

Recovered from scratchpad 2026-09-28 (see scripts/README.md) — originally
written 2026-09-24, never committed. Path made relative to repo layout.

Run: ~/.venv-trading/bin/python3 update_kr_history_incremental.py
"""
import json, math, time
from datetime import datetime, timedelta
from pathlib import Path
import yfinance as yf
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
KR_JSON = BASE / "data" / "kr.json"
HIST_JSON = BASE / "data" / "kr-history.json"

with open(KR_JSON) as f:
    kr = json.load(f)
with open(HIST_JSON) as f:
    hist = json.load(f)

stocks = kr["stocks"]
code_to_yf = {s["code"]: (f"{s['code']}.KS" if s["market"]=="KOSPI" else f"{s['code']}.KQ") for s in stocks}
codes = [s["code"] for s in stocks]

existing_dates = set(hist["dates"])
print(f"Existing dates: {len(existing_dates)}, last: {hist['dates'][-1]}")

# Download last 10 days to catch new trading dates
end_dt = datetime.now() + timedelta(days=1)
start_dt = end_dt - timedelta(days=10)
start_str = start_dt.strftime("%Y-%m-%d")
end_str = end_dt.strftime("%Y-%m-%d")
print(f"Fetching incremental: {start_str} → {end_str}")

BATCH = 50
new_date_data = {}  # date -> {code: price}
new_dates_found = set()

for i in range(0, len(codes), BATCH):
    batch_codes = codes[i:i+BATCH]
    batch_tks = [code_to_yf[c] for c in batch_codes]
    print(f"  Batch {i//BATCH+1}/{math.ceil(len(codes)/BATCH)}: {batch_tks[0]}...", flush=True)
    try:
        df = yf.download(batch_tks, start=start_str, end=end_str,
                         auto_adjust=True, progress=False, threads=True)
        if df is None or df.empty:
            continue
        close_df = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": batch_tks[0]})
        for dt in close_df.index:
            date_str = dt.strftime("%Y-%m-%d")
            if date_str not in existing_dates:
                new_dates_found.add(date_str)
                if date_str not in new_date_data:
                    new_date_data[date_str] = {}
                for code, yf_tk in zip(batch_codes, batch_tks):
                    if yf_tk in close_df.columns:
                        v = close_df.loc[dt, yf_tk]
                        if pd.notna(v) and float(v) > 0:
                            new_date_data[date_str][code] = int(round(float(v)))
    except Exception as e:
        print(f"  Error: {e}")
    time.sleep(0.2)

if not new_dates_found:
    print("No new dates found — already up to date.")
else:
    new_dates_sorted = sorted(new_dates_found)
    print(f"New dates: {new_dates_sorted}")

    # Append to hist
    for d in new_dates_sorted:
        hist["dates"].append(d)
        for code in codes:
            price = new_date_data[d].get(code)
            if code not in hist["closes"]:
                hist["closes"][code] = [None] * len(hist["dates"])
            else:
                hist["closes"][code].append(price)

    # Ensure all closes arrays have same length as dates
    n = len(hist["dates"])
    for code in codes:
        arr = hist["closes"].get(code, [])
        if len(arr) < n:
            hist["closes"][code] = arr + [None] * (n - len(arr))

    hist["generated"] = datetime.now().strftime("%Y-%m-%d")
    with open(HIST_JSON, "w") as f:
        json.dump(hist, f, separators=(",",":"), allow_nan=False)
    print(f"Saved. New total dates: {len(hist['dates'])}, last: {hist['dates'][-1]}")
