import configparser
import os
import sys
import time
from datetime import date

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
_lw = _cfg["lw_low_scanner"] if "lw_low_scanner" in _cfg else {}

PROXIMITY_PCT    = float(_lw.get("proximity_pct",    5.0))
FETCH_CHUNK_SIZE = int(  _lw.get("fetch_chunk_size", 50))


def is_near_last_week_low(df: pd.DataFrame, proximity_pct: float = PROXIMITY_PCT) -> tuple:
    """
    Checks whether the latest close sits within ±proximity_pct of the low of
    the most recently completed Monday–Friday calendar week.

    Resamples the daily 'low' column into Friday-anchored weekly bins. The
    last bin is used only if the frame's last trading day falls on or after
    that bin's Friday label (the week has actually finished); otherwise the
    second-to-last (last fully completed) bin is used instead.

    Returns:
        (True,  last_week_low, distance_pct)  — latest close within band
        (False, None,          None)          — outside band, or fewer than
                                                  2 completed weekly bins
    """
    if df is None or len(df) == 0:
        return False, None, None

    weekly_low = df["low"].resample("W-FRI").min()
    if len(weekly_low) < 2:
        return False, None, None

    last_bin_friday  = weekly_low.index[-1]
    last_trading_day = df.index[-1]

    completed_low = (weekly_low.iloc[-1] if last_trading_day >= last_bin_friday
                      else weekly_low.iloc[-2])

    latest_close = df["close"].iloc[-1]
    distance_pct = (latest_close - completed_low) / completed_low * 100

    if abs(distance_pct) <= proximity_pct:
        return True, round(completed_low, 4), round(distance_pct, 2)

    return False, None, None


def main():
    folder   = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(folder, f"lw_low_scan_log_{date.today()}.txt")
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
    print(f"Proximity band: ±{PROXIMITY_PCT}% of last week's low")
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

            near, low, dist = is_near_last_week_low(df)

            if near:
                candidates.append(sym)
                print(f"  [{i:3d}/{len(symbols)}] {sym:10s}"
                      f"  LW LOW  low:{low:.2f}  dist:{dist:+.1f}%")
            else:
                print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  —")

        except Exception as exc:
            errors += 1
            print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  ERROR: {exc}")

    print(f"\n{'='*55}")
    print(f"LW Low candidates : {len(candidates)}")
    print(f"Errors            : {errors}")

    if candidates:
        out_name = f"LW_Low_{date.today()}.txt"
        out_path = os.path.join(folder, out_name)
        with open(out_path, "w") as f:
            f.write("\n".join(candidates))
        print(f"Saved → {out_name}")
    else:
        print("No LW Low candidates found.")


if __name__ == "__main__":
    main()
