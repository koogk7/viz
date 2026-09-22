#!/usr/bin/env python3
"""Collect 15-month KR close price history for rank-momentum viz.
Source: yfinance auto_adjust=True (same as kr.json generation source).
Note: pykrx was the previous source and caused 수정주가 mismatches.
"""
import json, os, sys, time, math
from datetime import date
import yfinance as yf
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
KR_JSON = os.path.join(DATA, "kr.json")
PROG_FILE = os.path.join(DATA, "kr-hist-progress.json")
OUT_FILE = os.path.join(DATA, "kr-history.json")

START = "2025-06-22"
END   = "2026-09-23"  # yfinance end is exclusive; includes through 2026-09-22
BATCH = 50

def load_progress():
    if os.path.exists(PROG_FILE):
        with open(PROG_FILE) as f:
            return json.load(f)
    return {"closes": {}, "dates": None}

def save_progress(prog):
    with open(PROG_FILE, "w") as f:
        json.dump(prog, f, separators=(",", ":"))

def safe_int(v):
    """Convert KRW float to integer, None for missing/invalid values."""
    try:
        f = float(v)
        if not math.isfinite(f) or math.isnan(f):
            return None
        return int(round(f))  # KRW integer (not cents like US)
    except (TypeError, ValueError):
        return None

def to_yf_ticker(code, market):
    if market == "KOSPI":
        return f"{code}.KS"
    else:
        return f"{code}.KQ"

def main():
    with open(KR_JSON) as f:
        stocks = json.load(f)["stocks"]
    # Build mapping: code -> (yf_ticker, market)
    code_to_yf = {s["code"]: to_yf_ticker(s["code"], s["market"]) for s in stocks}
    codes = [s["code"] for s in stocks]
    yf_tickers = [code_to_yf[c] for c in codes]
    print(f"Universe: {len(codes)} codes")

    prog = load_progress()
    closes = prog.get("closes", {})
    all_dates = prog.get("dates", None)
    done = set(closes.keys())
    remaining = [c for c in codes if c not in done]
    print(f"Already done: {len(done)}, remaining: {len(remaining)}")

    for i in range(0, len(remaining), BATCH):
        batch_codes = remaining[i:i+BATCH]
        batch_tickers = [code_to_yf[c] for c in batch_codes]
        print(f"Batch {i//BATCH+1}/{math.ceil(len(remaining)/BATCH)}: {batch_tickers[0]}..{batch_tickers[-1]}", flush=True)
        try:
            df = yf.download(batch_tickers, start=START, end=END,
                             auto_adjust=True, progress=False, threads=True)
            if df is None or df.empty:
                print("  empty result, marking batch as None")
                for c in batch_codes:
                    closes[c] = None
            else:
                # Extract Close — handle both single and multi-ticker cases
                if isinstance(df.columns, pd.MultiIndex):
                    close_df = df["Close"]
                else:
                    close_df = df[["Close"]].rename(columns={"Close": batch_tickers[0]})

                # Build master date index from first successful batch
                batch_dates = [str(d.date()) for d in close_df.index]
                if all_dates is None:
                    all_dates = batch_dates
                    prog["dates"] = all_dates

                for code, yf_tk in zip(batch_codes, batch_tickers):
                    if yf_tk in close_df.columns:
                        col = close_df[yf_tk]
                        date_to_val = {}
                        for d, v in zip(close_df.index, col):
                            sv = safe_int(v)
                            if sv is not None:
                                date_to_val[str(d.date())] = sv
                        row = [date_to_val.get(d) for d in all_dates]
                        # Only include if we got meaningful data
                        valid_count = sum(1 for v in row if v is not None)
                        if valid_count < 20:
                            print(f"  SKIP {code} ({yf_tk}): only {valid_count} valid days")
                            closes[code] = None
                        else:
                            closes[code] = row
                    else:
                        print(f"  MISS {code} ({yf_tk}): not in response")
                        closes[code] = None

        except Exception as e:
            print(f"  Batch ERR: {e}", flush=True)
            for c in batch_codes:
                if c not in closes:
                    closes[c] = None

        prog["closes"] = closes
        if all_dates:
            prog["dates"] = all_dates
        save_progress(prog)
        n_valid = len([c for c in closes if closes[c] is not None])
        print(f"  Progress: {n_valid} valid / {len(closes)} total", flush=True)
        time.sleep(0.5)

    if all_dates is None:
        print("ERROR: no dates collected")
        sys.exit(1)

    valid_closes = {k: v for k, v in closes.items() if v is not None}
    print(f"\nValid codes: {len(valid_closes)} / {len(codes)}")
    print(f"Dates: {len(all_dates)} ({all_dates[0]} -> {all_dates[-1]})")

    out = {
        "market": "KR",
        "generated": str(date.today()),
        "source": "yfinance-auto_adjust",
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
        print(f"Samsung (005930) last close: {last_close} KRW")

    # Spot-check 가온전선
    if "000500" in valid_closes:
        last_close = valid_closes["000500"][-1]
        print(f"가온전선 (000500) last close: {last_close} KRW")

if __name__ == "__main__":
    main()
