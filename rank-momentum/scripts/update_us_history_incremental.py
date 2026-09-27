#!/usr/bin/env python3
"""
Incrementally append new trading dates to us-history.json.

Recovered from scratchpad 2026-09-28 (see scripts/README.md) — originally
written 2026-09-24, never committed. Path made relative to repo layout.

Run: ~/.venv-trading/bin/python3 update_us_history_incremental.py
"""
import json, math, time
from datetime import datetime, timedelta
from pathlib import Path
import yfinance as yf
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
US_JSON = BASE / "data" / "us.json"
HIST_JSON = BASE / "data" / "us-history.json"

with open(US_JSON) as f:
    us = json.load(f)
with open(HIST_JSON) as f:
    hist = json.load(f)

stocks = us["stocks"]
symbols = [s["symbol"] for s in stocks]
existing_dates = set(hist["dates"])
print(f"Existing dates: {len(existing_dates)}, last: {hist['dates'][-1]}")
print(f"Universe: {len(symbols)} symbols")

end_dt = datetime.now() + timedelta(days=1)
start_dt = end_dt - timedelta(days=10)
start_str = start_dt.strftime("%Y-%m-%d")
end_str = end_dt.strftime("%Y-%m-%d")
print(f"Fetching incremental: {start_str} → {end_str}")

BATCH = 100
new_date_data = {}
new_dates_found = set()

for i in range(0, len(symbols), BATCH):
    batch_syms = symbols[i:i+BATCH]
    print(f"  Batch {i//BATCH+1}/{math.ceil(len(symbols)/BATCH)}: {batch_syms[0]}...", flush=True)
    try:
        df = yf.download(batch_syms, start=start_str, end=end_str, auto_adjust=True, progress=False, threads=True)
        if df is None or df.empty:
            continue
        close_df = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": batch_syms[0]})
        for dt in close_df.index:
            date_str = dt.strftime("%Y-%m-%d")
            if date_str not in existing_dates:
                new_dates_found.add(date_str)
                if date_str not in new_date_data:
                    new_date_data[date_str] = {}
                for sym in batch_syms:
                    if sym in close_df.columns:
                        v = close_df.loc[dt, sym]
                        # us-history.json stores cents (int), matching
                        # fetch_us_history.py's safe_int() convention —
                        # NOT dollars. A dollars/cents unit mismatch here
                        # silently breaks validate_history.py's ret_52w
                        # cross-check (found + fixed 2026-09-28).
                        if pd.notna(v) and float(v) > 0:
                            new_date_data[date_str][sym] = int(round(float(v) * 100))
    except Exception as e:
        print(f"  Error: {e}")
    time.sleep(0.2)

if not new_dates_found:
    print("No new dates — already up to date.")
else:
    new_dates_sorted = sorted(new_dates_found)
    print(f"New dates: {new_dates_sorted}")
    for d in new_dates_sorted:
        hist["dates"].append(d)
        for sym in symbols:
            price = new_date_data[d].get(sym)
            if sym not in hist["closes"]:
                hist["closes"][sym] = [None] * len(hist["dates"])
            else:
                hist["closes"][sym].append(price)
    n = len(hist["dates"])
    for sym in symbols:
        arr = hist["closes"].get(sym, [])
        if len(arr) < n:
            hist["closes"][sym] = arr + [None] * (n - len(arr))
    hist["generated"] = datetime.now().strftime("%Y-%m-%d")
    with open(HIST_JSON, "w") as f:
        json.dump(hist, f, separators=(",",":"), allow_nan=False)
    print(f"Saved. Total dates: {len(hist['dates'])}, last: {hist['dates'][-1]}")
