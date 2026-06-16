import os
import sys
import time
from datetime import date

import pandas as pd

from darvas_scan import (
    _Tee,
    CEIL_MAX_DIST_PCT,
    EMA_LONG,
    EMA_SHORT,
    FETCH_CHUNK_SIZE,
    MAX_HEIGHT_PCT,
    fetch_ohlc_bulk,
    fetch_ohlc_single,
    find_latest_csv,
    is_phase3,
)
from lc_scan import (
    BARS_BACK,
    LEFT_BARS,
    LOOKBACK_LC,
    MAX_PRICE_DIST_PCT,
    MIN_BARS_LC,
    PIVOT_MAX_DIST_PCT,
    PIVOT_SRC,
    RIGHT_BARS,
    is_lc_active,
)


def main():
    folder   = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(folder, f"lc_scan_log_{date.today()}.txt")
    log_file = open(log_path, "w", buffering=1)
    sys.stdout = _Tee(sys.__stdout__, log_file)

    try:
        _run(folder)
    finally:
        sys.stdout = sys.__stdout__
        log_file.close()
        print(f"Log saved  → {os.path.basename(log_path)}")


def _run(folder: str):
    csv_path = find_latest_csv(folder)
    print(f"Screener file  : {os.path.basename(csv_path)}")

    tv      = pd.read_csv(csv_path)
    symbols = tv["Symbol"].dropna().tolist()
    print(f"Tickers loaded : {len(symbols)}")

    ceil_str  = f"{CEIL_MAX_DIST_PCT}%"  if CEIL_MAX_DIST_PCT  < 100 else "off"
    pivot_str = f"{PIVOT_MAX_DIST_PCT}%" if PIVOT_MAX_DIST_PCT < 100 else "off"
    price_str = f"{MAX_PRICE_DIST_PCT}%" if MAX_PRICE_DIST_PCT < 100 else "off"
    print(f"[Darvas] Max height: {MAX_HEIGHT_PCT}%  |  Ceil proximity: {ceil_str}"
          f"  |  EMA{EMA_SHORT}>{EMA_LONG}")
    print(f"[LC]     Min bars: {MIN_BARS_LC}  |  Lookback cap: {LOOKBACK_LC}"
          f"  |  Pivot src: {PIVOT_SRC}  left:{LEFT_BARS} right:{RIGHT_BARS}"
          f"  |  Pivot proximity: {pivot_str}  |  Price proximity: {price_str}")
    print(f"Fetch mode     : bulk chunks of {FETCH_CHUNK_SIZE}\n")

    darvas_candidates = []
    lc_candidates     = []
    errors            = 0
    symbol_pairs      = [
        (sym, sym.replace(".", "-").replace("/", "-"))
        for sym in symbols if isinstance(sym, str)
    ]

    ohlc = fetch_ohlc_bulk(
        [yf for _, yf in symbol_pairs],
        chunk_size=FETCH_CHUNK_SIZE,
    )

    failed = [yf for _, yf in symbol_pairs if yf not in ohlc]
    if failed:
        print(f"Retrying {len(failed)} failed symbols one-by-one…")
        recovered = 0
        for yf_sym in failed:
            time.sleep(0.5)
            df = fetch_ohlc_single(yf_sym)
            if df is not None:
                ohlc[yf_sym] = df
                recovered += 1
        print(f"Recovered {recovered}/{len(failed)} on retry\n")

    for i, (sym, yf_sym) in enumerate(symbol_pairs, 1):
        try:
            df = ohlc.get(yf_sym)
            if df is None:
                print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  — no data")
                continue

            # Single OHLC fetch — both checks run on the same DataFrame
            in_p3, ceil, floor, height = is_phase3(df)
            lc_act, pivot, age         = is_lc_active(df)

            # Apply Darvas 52W proximity filter
            if in_p3 and CEIL_MAX_DIST_PCT < 100:
                high_52w  = df["high"].max()
                ceil_dist = (high_52w - ceil) / high_52w * 100
                if ceil_dist > CEIL_MAX_DIST_PCT:
                    in_p3 = False

            # Apply LC pivot 52W proximity filter
            if lc_act and PIVOT_MAX_DIST_PCT < 100:
                high_52w   = df["high"].max()
                pivot_dist = (high_52w - pivot) / high_52w * 100
                if pivot_dist > PIVOT_MAX_DIST_PCT:
                    lc_act = False

            # Apply LC price proximity filter
            if lc_act and MAX_PRICE_DIST_PCT < 100:
                current_close = df["close"].iloc[-1]
                price_dist = (pivot - current_close) / pivot * 100
                if price_dist > MAX_PRICE_DIST_PCT:
                    lc_act = False

            if in_p3:
                darvas_candidates.append(sym)
            if lc_act:
                lc_candidates.append(sym)

            d_col = (f"PHASE3  {floor:.2f}–{ceil:.2f} ({height:.1f}%)"
                     if in_p3 else "—")
            l_col = (f"LC ACTIVE  pivot:{pivot:.2f}  age:{age}b"
                     if lc_act else "—")
            print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  {d_col:<38}  |  {l_col}")

        except Exception as exc:
            errors += 1
            print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  ERROR: {exc}")

    today = date.today()
    print(f"\n{'='*55}")
    print(f"Phase 3 candidates : {len(darvas_candidates)}")
    print(f"LC candidates      : {len(lc_candidates)}")
    print(f"Errors             : {errors}")

    if darvas_candidates:
        out = os.path.join(folder, f"phase3_{today}.txt")
        with open(out, "w") as f:
            f.write("\n".join(darvas_candidates))
        print(f"Saved → phase3_{today}.txt")
    else:
        print("No Darvas Phase 3 candidates found.")

    if lc_candidates:
        out = os.path.join(folder, f"LC_Phase3_{today}.txt")
        with open(out, "w") as f:
            f.write("\n".join(lc_candidates))
        print(f"Saved → LC_Phase3_{today}.txt")
    else:
        print("No LC candidates found.")


if __name__ == "__main__":
    main()
