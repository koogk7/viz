#!/usr/bin/env python3
"""Collect 15-month US close price history for rank-momentum viz."""
import json, os, sys, time, math
from datetime import date
import yfinance as yf
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
US_JSON = os.path.join(DATA, "us.json")
PROG_FILE = os.path.join(DATA, "us-hist-progress.json")
OUT_FILE = os.path.join(DATA, "us-history.json")

START = "2025-06-22"
END   = "2026-09-23"   # yfinance end is exclusive
BATCH = 200

def load_progress():
    if os.path.exists(PROG_FILE):
        with open(PROG_FILE) as f:
            return json.load(f)
    return {"closes": {}, "dates": None}

def save_progress(prog):
    with open(PROG_FILE, "w") as f:
        json.dump(prog, f, separators=(",", ":"))

def safe_int(v):
    try:
        f = float(v)
        if not math.isfinite(f) or math.isnan(f):
            return None
        return int(round(f * 100))
    except (TypeError, ValueError):
        return None

def main():
    with open(US_JSON) as f:
        symbols = [s["symbol"] for s in json.load(f)["stocks"]]
    print(f"Universe: {len(symbols)} symbols")

    prog = load_progress()
    closes = prog.get("closes", {})
    all_dates = prog.get("dates", None)
    done = set(closes.keys())
    remaining = [s for s in symbols if s not in done]
    print(f"Already done: {len(done)}, remaining: {len(remaining)}")

    for i in range(0, len(remaining), BATCH):
        batch = remaining[i:i+BATCH]
        print(f"Batch {i//BATCH+1}/{math.ceil(len(remaining)/BATCH)}: {batch[0]}..{batch[-1]}")
        try:
            df = yf.download(batch, start=START, end=END,
                             auto_adjust=True, progress=False, threads=True)
            if df is None or df.empty:
                print("  empty result, skipping batch")
                for sym in batch:
                    closes[sym] = None
            else:
                # Extract Close — handle both single and multi-ticker cases
                if isinstance(df.columns, pd.MultiIndex):
                    close_df = df["Close"]
                else:
                    # single ticker case
                    close_df = df[["Close"]].rename(columns={"Close": batch[0]})

                # Build master date index from first batch
                batch_dates = [str(d.date()) for d in close_df.index]
                if all_dates is None:
                    all_dates = batch_dates
                    prog["dates"] = all_dates

                for sym in batch:
                    if sym in close_df.columns:
                        col = close_df[sym]
                        row = [safe_int(col.get(d)) if d in col.index else None
                               for d in pd.to_datetime(all_dates)]
                        # simpler: align by date string
                        date_to_val = {str(d.date()): safe_int(v)
                                       for d, v in zip(close_df.index, close_df[sym])
                                       if not (isinstance(v, float) and math.isnan(v))}
                        row = [date_to_val.get(d) for d in all_dates]
                        closes[sym] = row
                    else:
                        closes[sym] = None
        except Exception as e:
            print(f"  Batch ERR: {e}")
            for sym in batch:
                if sym not in closes:
                    closes[sym] = None

        prog["closes"] = closes
        if all_dates:
            prog["dates"] = all_dates
        save_progress(prog)
        n_valid = len([s for s in closes if closes[s] is not None])
        print(f"  Progress: {n_valid} valid / {len(closes)} total")
        time.sleep(0.5)

    if all_dates is None:
        print("ERROR: no dates collected")
        sys.exit(1)

    valid_closes = {k: v for k, v in closes.items() if v is not None}
    print(f"\nValid symbols: {len(valid_closes)} / {len(symbols)}")
    print(f"Dates: {len(all_dates)} ({all_dates[0]} → {all_dates[-1]})")

    out = {
        "market": "US",
        "generated": str(date.today()),
        "dates": all_dates,
        "closes": valid_closes
    }
    with open(OUT_FILE, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    size_mb = os.path.getsize(OUT_FILE) / 1e6
    print(f"Written: {OUT_FILE} ({size_mb:.1f} MB)")

    # Spot-check AAPL
    if "AAPL" in valid_closes:
        last_cents = valid_closes["AAPL"][-1]
        print(f"AAPL last close: ${last_cents/100:.2f} ({last_cents} cents)")

if __name__ == "__main__":
    main()
