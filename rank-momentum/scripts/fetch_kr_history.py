#!/usr/bin/env python3
"""Collect 15-month KR close price history for rank-momentum viz."""
import json, os, sys, time
from datetime import date
from pykrx import stock

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
KR_JSON = os.path.join(DATA, "kr.json")
PROG_FILE = os.path.join(DATA, "kr-hist-progress.json")
OUT_FILE = os.path.join(DATA, "kr-history.json")

START = "20250622"
END   = "20260922"
BATCH = 50

def load_progress():
    if os.path.exists(PROG_FILE):
        with open(PROG_FILE) as f:
            return json.load(f)
    return {"closes": {}}

def save_progress(prog):
    with open(PROG_FILE, "w") as f:
        json.dump(prog, f)

def main():
    with open(KR_JSON) as f:
        codes = [s["code"] for s in json.load(f)["stocks"]]
    print(f"Universe: {len(codes)} codes")

    prog = load_progress()
    closes = prog["closes"]
    done = set(closes.keys())
    remaining = [c for c in codes if c not in done]
    print(f"Already done: {len(done)}, remaining: {len(remaining)}")

    all_dates = None  # establish master date index from first successful fetch

    # If we already have closes, derive all_dates from existing data
    if closes:
        # find longest date list
        best = max(closes.values(), key=len)
        # Dates not stored in progress — we'll rebuild from scratch if needed
        # Actually we need to store dates in progress too
        if "dates" in prog:
            all_dates = prog["dates"]

    for i in range(0, len(remaining), BATCH):
        batch = remaining[i:i+BATCH]
        for code in batch:
            try:
                df = stock.get_market_ohlcv(START, END, code)
                if df is None or df.empty:
                    print(f"  SKIP {code}: empty")
                    closes[code] = None
                    continue
                df.index = [str(d.date()) for d in df.index]
                if all_dates is None:
                    all_dates = list(df.index)
                    prog["dates"] = all_dates
                row = [int(df.loc[d, "종가"]) if d in df.index else None for d in all_dates]
                closes[code] = row
                print(f"  {code}: {len([x for x in row if x is not None])} days")
            except Exception as e:
                print(f"  ERR {code}: {e}")
                closes[code] = None

        prog["closes"] = closes
        if all_dates:
            prog["dates"] = all_dates
        save_progress(prog)
        print(f"Checkpoint: {len([c for c in closes if closes[c] is not None])} collected")

    if all_dates is None:
        print("ERROR: no dates collected")
        sys.exit(1)

    # Build final output — exclude None closes
    valid_closes = {k: v for k, v in closes.items() if v is not None}
    print(f"\nValid tickers: {len(valid_closes)} / {len(codes)}")
    print(f"Dates: {len(all_dates)} ({all_dates[0]} → {all_dates[-1]})")

    out = {
        "market": "KR",
        "generated": str(date.today()),
        "dates": all_dates,
        "closes": valid_closes
    }
    with open(OUT_FILE, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    size_mb = os.path.getsize(OUT_FILE) / 1e6
    print(f"Written: {OUT_FILE} ({size_mb:.1f} MB)")

    # Spot-check Samsung
    if "005930" in valid_closes:
        last_close = valid_closes["005930"][-1]
        print(f"Samsung (005930) last close: {last_close}")

if __name__ == "__main__":
    main()
