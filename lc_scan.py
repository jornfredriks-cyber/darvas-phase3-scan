import configparser
import os
import sys
import time
from datetime import date

import numpy as np
import pandas as pd

# Import shared utilities — darvas_scan.py is NOT modified
from darvas_scan import (
    _Tee,
    fetch_ohlc_bulk,
    fetch_ohlc_single,
    find_latest_csv,
)

# ── Config ────────────────────────────────────────────────────────────────────
_cfg = configparser.ConfigParser()
_cfg.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), "darvas_config.ini"))
_lc = _cfg["lc_scanner"] if "lc_scanner" in _cfg else {}

MIN_BARS_LC         = int(  _lc.get("min_bars_lc",         5))
LOOKBACK_LC         = int(  _lc.get("lookback_lc",         200))
BARS_BACK           = int(  _lc.get("bars_back",           300))
LEFT_BARS           = int(  _lc.get("left_bars",           2))
RIGHT_BARS          = int(  _lc.get("right_bars",          2))
ALLOW_EQUAL_HIGHS   =       _lc.get("allow_equal_highs",   "true").lower()  == "true"
REPLACE_ACTIVE_LINE =       _lc.get("replace_active_line", "true").lower()  == "true"
REPLACE_ONLY_HIGHER =       _lc.get("replace_only_higher", "false").lower() == "true"
PIVOT_SRC           =       _lc.get("pivot_src",           "high")
PIVOT_MAX_DIST_PCT  = float(_lc.get("pivot_max_dist_pct",  5.0))
MAX_PRICE_DIST_PCT  = float(_lc.get("max_price_dist_pct",  2.0))
HISTORY_PERIOD      =       _lc.get("history_period",      "1y")
FETCH_CHUNK_SIZE    = int(  _lc.get("fetch_chunk_size",    50))


def is_lc_active(
    df: pd.DataFrame,
    min_bars_lc: int          = MIN_BARS_LC,
    lookback_lc: int          = LOOKBACK_LC,
    bars_back: int            = BARS_BACK,
    left_bars: int            = LEFT_BARS,
    right_bars: int           = RIGHT_BARS,
    allow_equal_highs: bool   = ALLOW_EQUAL_HIGHS,
    replace_active_line: bool = REPLACE_ACTIVE_LINE,
    replace_only_higher: bool = REPLACE_ONLY_HIGHER,
    pivot_src: str            = PIVOT_SRC,
) -> tuple:
    """
    Bar-by-bar translation of the LC Line Breakout Pine Script.

    Tracks a single horizontal resistance line (pivot high). The line
    starts as 'forming' (age < min_bars_lc) and becomes 'active' (solid)
    once it has aged enough without a close above it. A stock is an LC
    candidate when the final bar has an active line.

    Returns:
        (True,  pivot_price, age_bars)  — active line on last bar
        (False, None,        None)      — no active line
    """
    if df is None or len(df) == 0:
        return False, None, None

    highs  = df["high"].to_numpy(dtype=float)
    lows   = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    src    = highs if pivot_src.lower() == "high" else closes
    n      = len(src)

    lc_price:  float | None = None
    lc_birth:  int   | None = None
    lc_is_act: bool         = False

    for i in range(n):
        # ── Dynamic lookback: bars since the most recent lowest low ──────────
        win_start  = max(0, i - bars_back + 1)
        win_lows   = lows[win_start : i + 1]
        # Most recent occurrence of minimum (matches Pine Script ta.lowestbars)
        last_idx   = len(win_lows) - 1 - int(np.argmin(win_lows[::-1]))
        bars_since = i - (win_start + last_idx)
        dynamic_lb = min(lookback_lc, max(20, bars_since))

        # ── Pivot detection: candidate is right_bars bars ago ────────────────
        pivot_bar = i - right_bars
        if pivot_bar >= left_bars:
            c  = src[pivot_bar]
            ok = True
            for j in range(1, left_bars + 1):
                ok = ok and (c >= src[pivot_bar - j] if allow_equal_highs
                             else c > src[pivot_bar - j])
            for j in range(1, right_bars + 1):
                ok = ok and (c >= src[pivot_bar + j] if allow_equal_highs
                             else c > src[pivot_bar + j])

            if ok:
                # replace_active_line=False → once any pivot is set, it holds until
                # breakout or expiry (forming AND active lines are both preserved).
                # replace_active_line=True  → any existing line can be overwritten
                # by a new pivot; replace_only_higher further gates that.
                can_replace = (
                    lc_price is None
                    or (replace_active_line
                        and (not replace_only_higher or c > lc_price))
                )
                if can_replace:
                    lc_price  = c
                    lc_birth  = pivot_bar
                    lc_is_act = False

        # ── Line management ──────────────────────────────────────────────────
        if lc_price is not None:
            age = i - lc_birth

            if age > dynamic_lb:
                # Expired
                lc_price  = None
                lc_birth  = None
                lc_is_act = False
            else:
                if age >= min_bars_lc:
                    lc_is_act = True
                # Breakout: close above pivot deletes line
                if lc_price is not None and closes[i] > lc_price:
                    lc_price  = None
                    lc_birth  = None
                    lc_is_act = False

    if lc_is_act and lc_price is not None and lc_birth is not None:
        return True, round(lc_price, 4), (n - 1) - lc_birth

    return False, None, None


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
    print(f"Screener file : {os.path.basename(csv_path)}")

    tv      = pd.read_csv(csv_path)
    symbols = tv["Symbol"].dropna().tolist()
    print(f"Tickers loaded: {len(symbols)}")
    pivot_str = f"{PIVOT_MAX_DIST_PCT}%" if PIVOT_MAX_DIST_PCT < 100 else "off"
    price_str = f"{MAX_PRICE_DIST_PCT}%" if MAX_PRICE_DIST_PCT < 100 else "off"
    print(f"History       : {HISTORY_PERIOD}  |  Min bars LC: {MIN_BARS_LC}"
          f"  |  Lookback cap: {LOOKBACK_LC}")
    print(f"Pivot         : src={PIVOT_SRC}  left={LEFT_BARS}  right={RIGHT_BARS}"
          f"  |  Pivot proximity: {pivot_str}  |  Price proximity: {price_str}")
    print(f"Fetch mode    : bulk chunks of {FETCH_CHUNK_SIZE}\n")

    candidates   = []
    errors       = 0
    symbol_pairs = [
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

            active, pivot, age = is_lc_active(df)

            if active and PIVOT_MAX_DIST_PCT < 100:
                high_52w   = df["high"].max()
                pivot_dist = (high_52w - pivot) / high_52w * 100
                if pivot_dist > PIVOT_MAX_DIST_PCT:
                    active = False

            if active and MAX_PRICE_DIST_PCT < 100:
                current_close = df["close"].iloc[-1]
                price_dist = (pivot - current_close) / pivot * 100
                if price_dist > MAX_PRICE_DIST_PCT:
                    active = False

            if active:
                candidates.append(sym)
                print(f"  [{i:3d}/{len(symbols)}] {sym:10s}"
                      f"  LC ACTIVE  pivot:{pivot:.2f}  age:{age}b")
            else:
                print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  —")

        except Exception as exc:
            errors += 1
            print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  ERROR: {exc}")

    print(f"\n{'='*55}")
    print(f"LC candidates : {len(candidates)}")
    print(f"Errors        : {errors}")

    if candidates:
        out_name = f"LC_Phase3_{date.today()}.txt"
        out_path = os.path.join(folder, out_name)
        with open(out_path, "w") as f:
            f.write("\n".join(candidates))
        print(f"Saved → {out_name}")
    else:
        print("No LC candidates found.")


if __name__ == "__main__":
    main()
