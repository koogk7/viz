#!/usr/bin/env python3
"""
Incremental US valuation backfill.
- Reads progress from data/us-val-progress.json (symbol -> {per, roe, forward_per, earnings_growth})
- Processes CHUNK_SIZE symbols per batch, saves after each batch
- Stops cleanly on 429/401/rate-limit signals
- Merges final result into data/us.json
"""

import json, math, time, sys
from pathlib import Path

BASE = Path(__file__).parent.parent
US_JSON  = BASE / "data" / "us.json"
PROG_FILE = BASE / "data" / "us-val-progress.json"

CHUNK_SIZE = 150
DELAY_BETWEEN_CHUNKS = 4.0  # seconds
DELAY_PER_TICKER = 0.3      # seconds within chunk

RATE_LIMIT_SIGNALS = ("429", "401", "too many", "rate", "unauthorized")

def is_rate_limited(exc_str: str) -> bool:
    s = exc_str.lower()
    return any(sig in s for sig in RATE_LIMIT_SIGNALS)

def fetch_info(symbol: str) -> dict | None:
    """Returns {per, roe, forward_per, earnings_growth} or None on rate limit."""
    import yfinance as yf
    try:
        info = yf.Ticker(symbol).info
        if not info or len(info) <= 5:
            # Likely rate-limited or empty response
            return None
        def _safe(key, divisor=1):
            v = info.get(key)
            if v is None or v != v:  # None or NaN check
                return None
            try:
                f = float(v) / divisor
                # Guard: Infinity comes from EPS≈0 (P/E = price/~0). Treat as null.
                if not math.isfinite(f):
                    return None
                return round(f, 2)
            except (TypeError, ValueError):
                return None
        return {
            "per":             _safe("trailingPE"),
            "forward_per":     _safe("forwardPE"),
            "roe":             _safe("returnOnEquity", 0.01),  # yf gives decimal → convert to %
            "earnings_growth": _safe("earningsGrowth", 0.01),  # same
        }
    except Exception as e:
        msg = str(e)
        if is_rate_limited(msg):
            raise RateLimitError(msg)
        return None  # Other errors → treat as missing, continue

class RateLimitError(Exception):
    pass

def load_progress() -> dict:
    if PROG_FILE.exists():
        return json.loads(PROG_FILE.read_text())
    return {}

def save_progress(prog: dict):
    PROG_FILE.write_text(json.dumps(prog, ensure_ascii=False))

def merge_into_us_json(prog: dict):
    data = json.loads(US_JSON.read_text())
    for stock in data.get("stocks", []):
        sym = stock.get("symbol")
        if sym in prog:
            v = prog[sym]
            stock["per"]             = v.get("per")
            stock["forward_per"]     = v.get("forward_per")
            stock["roe"]             = v.get("roe")
            stock["earnings_growth"] = v.get("earnings_growth")
    US_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2))

def main():
    data = json.loads(US_JSON.read_text())
    stocks = data.get("stocks", [])
    symbols = [s["symbol"] for s in stocks]
    total = len(symbols)

    prog = load_progress()
    remaining = [s for s in symbols if s not in prog]
    print(f"Total: {total} | Already done: {len(prog)} | Remaining: {len(remaining)}")

    if not remaining:
        print("All done. Merging into us.json.")
        merge_into_us_json(prog)
        return

    processed = 0
    rate_limited = False

    for chunk_start in range(0, len(remaining), CHUNK_SIZE):
        chunk = remaining[chunk_start: chunk_start + CHUNK_SIZE]
        print(f"\n--- Chunk {chunk_start//CHUNK_SIZE + 1}: {chunk[0]}..{chunk[-1]} ({len(chunk)} symbols) ---")

        for sym in chunk:
            try:
                result = fetch_info(sym)
                prog[sym] = result if result else {"per": None, "forward_per": None, "roe": None, "earnings_growth": None}
                processed += 1
                time.sleep(DELAY_PER_TICKER)
            except RateLimitError as e:
                print(f"RATE LIMIT at {sym}: {e}")
                rate_limited = True
                break

        save_progress(prog)
        done_count = len(prog)
        print(f"Progress saved: {done_count}/{total} ({done_count/total*100:.1f}%)")

        if rate_limited:
            print("Stopping due to rate limit. Re-run to continue from checkpoint.")
            break

        if chunk_start + CHUNK_SIZE < len(remaining):
            print(f"Waiting {DELAY_BETWEEN_CHUNKS}s before next chunk...")
            time.sleep(DELAY_BETWEEN_CHUNKS)

    # Merge whatever we have
    print(f"\nMerging {len(prog)} records into us.json...")
    merge_into_us_json(prog)

    # Fill rates
    filled_per = sum(1 for v in prog.values() if v and v.get("per") is not None)
    filled_roe = sum(1 for v in prog.values() if v and v.get("roe") is not None)
    reached    = len(prog)
    print(f"\n=== Fill rates (of {reached} reached) ===")
    print(f"per:             {filled_per}/{reached} ({filled_per/reached*100:.1f}% of reached, {filled_per}/{total} total)")
    print(f"roe:             {filled_roe}/{reached} ({filled_roe/reached*100:.1f}% of reached, {filled_roe}/{total} total)")
    if rate_limited:
        print(f"\nPartial run: reached {reached}/{total}. Re-run to continue.")
    else:
        print(f"\nFull run complete: {reached}/{total} processed.")

if __name__ == "__main__":
    main()
