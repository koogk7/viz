#!/usr/bin/env python3
"""
Validate that kr-history.json and us-history.json correctly reproduce
the return values in kr.json / us.json.

Source unification (2026-09-22):
- kr-history.json now uses yfinance auto_adjust (same as kr.json)
- Previously used pykrx → caused 46pp discrepancy on 가온전선 (무상증자)

Run: ~/.venv-trading/bin/python3 scripts/validate_history.py
"""
import json, bisect, sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent / "data"

def snap_date(dates, target_str):
    idx = bisect.bisect_right(dates, target_str) - 1
    return idx if idx >= 0 else None

def cal_ret_from_history(closes, dates, code, ref_str, weeks):
    if code not in closes:
        return None
    row = closes[code]
    ref_idx = snap_date(dates, ref_str)
    if ref_idx is None or row[ref_idx] is None:
        return None
    ref_price = row[ref_idx]
    ref_dt = datetime.strptime(ref_str, "%Y-%m-%d")
    target_str = (ref_dt - timedelta(days=7*weeks)).strftime("%Y-%m-%d")
    past_idx = snap_date(dates, target_str)
    if past_idx is None or row[past_idx] is None:
        return None
    return (ref_price / row[past_idx] - 1) * 100

def main():
    errors = []

    # ── KR ────────────────────────────────────────────────────────────────────
    print("=== KR validation ===")
    with open(BASE / "kr-history.json") as f:
        kr_hist = json.load(f)
    with open(BASE / "kr.json") as f:
        kr = json.load(f)

    kr_dates = kr_hist["dates"]
    kr_closes = kr_hist["closes"]
    kr_as_of = kr["as_of"]
    kr_map = {s["code"]: s for s in kr["stocks"]}

    # Validate these 4 stocks. 삼성전자/DL이앤씨 expect ≤1pp,
    # 가온전선/SK하이닉스 allow ≤3pp (intraday jitter during market hours).
    kr_checks = [
        ("005930", "삼성전자",  1.0),
        ("000660", "SK하이닉스", 3.0),
        ("000500", "가온전선",   3.0),
        ("375500", "DL이앤씨",  1.0),
    ]

    for code, name, tol in kr_checks:
        stock = kr_map.get(code)
        if not stock:
            print(f"  SKIP {name}: not in kr.json")
            continue
        ref_str = stock.get("price_date", kr_as_of)
        hist_ret = cal_ret_from_history(kr_closes, kr_dates, code, ref_str, 52)
        kr_ret = stock.get("ret_52w")

        if hist_ret is None or kr_ret is None:
            print(f"  SKIP {name}: missing data (hist={hist_ret}, kr={kr_ret})")
            continue

        diff = abs(hist_ret - kr_ret)
        ok = diff <= tol
        marker = "✅" if ok else "❌"
        print(f"  {name} ({code}): hist={hist_ret:.2f}% kr={kr_ret:.2f}% diff={diff:.2f}pp tol={tol}pp {marker}")
        if not ok:
            errors.append(
                f"KR {name} ({code}): {diff:.2f}pp > {tol}pp tolerance "
                f"[hist={hist_ret:.2f}% kr={kr_ret:.2f}%]"
            )

    # ── US ────────────────────────────────────────────────────────────────────
    print("\n=== US validation ===")
    with open(BASE / "us-history.json") as f:
        us_hist = json.load(f)
    with open(BASE / "us.json") as f:
        us = json.load(f)

    us_dates = us_hist["dates"]
    us_closes = us_hist["closes"]
    us_map = {s["symbol"]: s for s in us["stocks"]}

    # AAPL — use its price_date (not as_of) since US data may lag
    aapl = us_map.get("AAPL")
    if aapl:
        ref_str = aapl.get("price_date", us["as_of"])
        hist_ret = cal_ret_from_history(us_closes, us_dates, "AAPL", ref_str, 52)
        us_ret = aapl.get("ret_52w")
        if hist_ret is not None and us_ret is not None:
            diff = abs(hist_ret - us_ret)
            ok = diff <= 1.0
            marker = "✅" if ok else "❌"
            print(f"  AAPL: hist={hist_ret:.2f}% us={us_ret:.2f}% diff={diff:.4f}pp {marker}")
            if not ok:
                errors.append(f"US AAPL: {diff:.2f}pp > 1pp [hist={hist_ret:.2f}% us={us_ret:.2f}%]")
        else:
            print(f"  SKIP AAPL: missing data")

    # ── Result ────────────────────────────────────────────────────────────────
    print()
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(f"  ❌ {e}")
        sys.exit(1)
    else:
        print("VALIDATION PASSED ✅")
        print("Note: 가온전선/SK하이닉스 use 3pp tolerance (intraday jitter when market is open)")
        print("      For EOD prices (market closed), all stocks should pass 1pp.")
        sys.exit(0)

if __name__ == "__main__":
    main()
