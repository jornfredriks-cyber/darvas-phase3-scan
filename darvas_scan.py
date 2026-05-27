import glob
import os
import sys
import time
from datetime import date

import pandas as pd
import yfinance as yf

# Point libcurl at certifi's CA bundle so Homebrew OpenSSL mismatches don't fail
try:
    import certifi
    for _k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ.setdefault(_k, certifi.where())
except ImportError:
    pass


class _Tee:
    """Writes to both the terminal and a log file simultaneously."""
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            s.write(data)

    def flush(self):
        for s in self._streams:
            s.flush()


# ── Parameters (match your TradingView indicator settings) ───────────────────
MAX_HEIGHT_PCT = 8.0   # max box height as % of floor
SEED_FLOOR     = False # seed floor with lowest low from Phase 0 — must match indicator (default: false)
SMA_SHORT      = 20    # SMA trend filter fast period — must match indicator "SMA Short Length"
SMA_LONG       = 50    # SMA trend filter slow period — must match indicator "SMA Long Length"
HISTORY_PERIOD = "1y"  # how much OHLC history to pull per ticker
FETCH_CHUNK_SIZE = 50  # yfinance symbols per request; keeps large screener exports stable
FETCH_RETRIES = 2
FETCH_RETRY_DELAY = 2.0


def find_latest_csv(folder: str) -> str:
    # Accept both naming variants exported by TradingView:
    #   "DARVAS Raw Screener_YYYY-MM-DD.csv"  (original)
    #   "Darvas Raw Screener YYYY_MM_DD_HHMM.csv"  (newer TV export)
    files = glob.glob(os.path.join(folder, "*[Ss]creener*.csv"))
    if not files:
        raise FileNotFoundError(f"No screener CSV found in {folder}")
    return max(files, key=os.path.getmtime)


def _chunks(items: list[str], size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _clean_ohlc_frame(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(how="all")
    if df.empty:
        return None
    df.columns = df.columns.str.lower()
    required = {"high", "low", "close"}
    if not required.issubset(set(df.columns)):
        return None
    return df


def _extract_symbol_frame(downloaded: pd.DataFrame, symbol: str, chunk_len: int) -> pd.DataFrame | None:
    if downloaded is None or downloaded.empty:
        return None

    if isinstance(downloaded.columns, pd.MultiIndex):
        if symbol in downloaded.columns.get_level_values(0):
            return _clean_ohlc_frame(downloaded[symbol])
        if symbol in downloaded.columns.get_level_values(1):
            return _clean_ohlc_frame(downloaded.xs(symbol, level=1, axis=1))
        return None

    if chunk_len == 1:
        return _clean_ohlc_frame(downloaded)
    return None


def fetch_ohlc_bulk(
    yf_symbols: list[str],
    chunk_size: int = FETCH_CHUNK_SIZE,
    retries: int = FETCH_RETRIES,
    retry_delay: float = FETCH_RETRY_DELAY,
) -> dict[str, pd.DataFrame]:
    result = {}
    unique_symbols = list(dict.fromkeys(yf_symbols))

    for chunk_index, chunk in enumerate(_chunks(unique_symbols, chunk_size), 1):
        downloaded = None
        for attempt in range(retries + 1):
            try:
                downloaded = yf.download(
                    " ".join(chunk),
                    period=HISTORY_PERIOD,
                    interval="1d",
                    group_by="ticker",
                    progress=False,
                    auto_adjust=True,
                    threads=False,
                )
                break
            except Exception as exc:
                if attempt >= retries:
                    print(f"  chunk {chunk_index}: yfinance ERROR after {retries + 1} attempts: {exc}")
                else:
                    time.sleep(retry_delay)

        if downloaded is None:
            continue

        for yf_symbol in chunk:
            df = _extract_symbol_frame(downloaded, yf_symbol, len(chunk))
            if df is not None:
                result[yf_symbol] = df

        if chunk_index * chunk_size < len(unique_symbols):
            time.sleep(0.5)

    return result


def fetch_ohlc_single(yf_symbol: str) -> pd.DataFrame | None:
    """Fetch OHLC for one symbol via Ticker.history — used for post-bulk retries."""
    try:
        df = yf.Ticker(yf_symbol).history(period=HISTORY_PERIOD, interval="1d", auto_adjust=True)
        return _clean_ohlc_frame(df)
    except Exception:
        return None


def is_phase3(df: pd.DataFrame, max_height: float = MAX_HEIGHT_PCT, seed_floor: bool = SEED_FLOOR) -> tuple:
    """
    Runs the Darvas Box state machine (translated 1-to-1 from the Pine Script).

    Returns (True, ceil_high, floor_low, box_height_pct) when the final bar
    leaves the stock in Phase 3 (box confirmed, no breakout yet).
    Returns (False, None, None, None) otherwise.

    State machine phases:
      0 – hunting for a ceiling candidate
      2 – ceiling confirmed, hunting for floor
      3 – box confirmed and active (what we want)
    """
    close_ser = pd.Series(df["close"].to_numpy())
    sma20 = close_ser.rolling(SMA_SHORT).mean().to_numpy()
    sma50 = close_ser.rolling(SMA_LONG).mean().to_numpy()

    phase = 0

    ceil_candidate = None
    ceil_count = 0
    ceil_high = None
    lowest_since_ceil = None

    floor_low = None
    floor_count = 0
    confirmed_floor = None

    for i, row in enumerate(df.itertuples(index=False)):
        high  = row.high
        low   = row.low
        close = row.close
        do_reset = False

        # ── Phase 0: hunt ceiling ────────────────────────────────────────────
        if phase == 0:
            if ceil_candidate is None or high > ceil_candidate:
                ceil_candidate    = high
                ceil_count        = 0
                lowest_since_ceil = low
            else:
                if close > ceil_candidate:
                    # Close breaks above candidate → new candidate
                    ceil_candidate    = high
                    ceil_count        = 0
                    lowest_since_ceil = low
                else:
                    # Bar contained below candidate → count it
                    if lowest_since_ceil is None or low < lowest_since_ceil:
                        lowest_since_ceil = low
                    ceil_count += 1
                    if ceil_count >= 3:
                        ceil_high   = ceil_candidate
                        floor_count = 0
                        # When seedFloor=True the floor search starts from the
                        # lowest low observed while the ceiling was being confirmed
                        floor_low = lowest_since_ceil if seed_floor else None
                        phase = 2

        # ── Phase 2: ceiling confirmed, hunt floor ───────────────────────────
        elif phase == 2:
            if close > ceil_high:
                # Ceiling pierced → restart
                ceil_candidate    = high
                ceil_count        = 0
                ceil_high         = None
                floor_low         = None
                floor_count       = 0
                lowest_since_ceil = low
                phase = 0
            else:
                if floor_low is None or low < floor_low:
                    floor_low   = low
                    floor_count = 0
                else:
                    floor_count += 1
                    if floor_count >= 3:
                        box_height = (ceil_high - floor_low) / floor_low * 100
                        s20, s50 = sma20[i], sma50[i]
                        trend_ok = not (pd.isna(s20) or pd.isna(s50)) and s20 >= s50
                        if box_height <= max_height and trend_ok:
                            confirmed_floor = floor_low
                            phase = 3
                        else:
                            do_reset = True

        # ── Phase 3: active box ──────────────────────────────────────────────
        elif phase == 3:
            if close > ceil_high:
                # Breakout → not Phase 3 anymore
                do_reset = True
            elif low < confirmed_floor and close >= confirmed_floor:
                # Wick below floor but closes inside → reset floor, back to 2
                floor_low       = low
                floor_count     = 0
                confirmed_floor = None
                phase = 2
            elif close < confirmed_floor:
                # Breakdown → reset
                do_reset = True

        if do_reset:
            phase             = 0
            ceil_candidate    = None
            ceil_count        = 0
            ceil_high         = None
            floor_low         = None
            floor_count       = 0
            confirmed_floor   = None
            lowest_since_ceil = None

    if phase == 3 and ceil_high is not None and confirmed_floor is not None:
        box_height = (ceil_high - confirmed_floor) / confirmed_floor * 100
        return True, ceil_high, confirmed_floor, round(box_height, 2)

    return False, None, None, None


def main():
    folder   = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(folder, f"scan_log_{date.today()}.txt")
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

    tv = pd.read_csv(csv_path)
    symbols = tv["Symbol"].dropna().tolist()
    print(f"Tickers loaded: {len(symbols)}")
    print(f"History period: {HISTORY_PERIOD}  |  Max box height: {MAX_HEIGHT_PCT}%")
    print(f"Fetch mode    : yfinance bulk chunks of {FETCH_CHUNK_SIZE}\n")

    candidates = []
    errors     = 0
    symbol_pairs = []

    for sym in symbols:
        if not isinstance(sym, str):
            continue
        yf_sym = sym.replace(".", "-").replace("/", "-")   # BRK.B → BRK-B, MITT/PB → MITT-PB
        symbol_pairs.append((sym, yf_sym))

    ohlc_by_symbol = fetch_ohlc_bulk([yf_sym for _, yf_sym in symbol_pairs])

    # Retry any symbol that came back empty — individually, no threading
    failed_yf = [yf_sym for _, yf_sym in symbol_pairs if yf_sym not in ohlc_by_symbol]
    if failed_yf:
        print(f"Retrying {len(failed_yf)} failed symbols one-by-one…")
        recovered = 0
        for yf_sym in failed_yf:
            time.sleep(0.5)
            df = fetch_ohlc_single(yf_sym)
            if df is not None:
                ohlc_by_symbol[yf_sym] = df
                recovered += 1
        print(f"Recovered {recovered}/{len(failed_yf)} on retry\n")

    for i, (sym, yf_sym) in enumerate(symbol_pairs, 1):
        try:
            df = ohlc_by_symbol.get(yf_sym)
            if df is None:
                print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  — no data")
                continue

            in_p3, ceil, floor, height = is_phase3(df)

            if in_p3:
                candidates.append(sym)
                print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  PHASE 3  box {floor:.2f}–{ceil:.2f}  ({height:.1f}%)")
            else:
                print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  —")

        except Exception as exc:
            errors += 1
            print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  ERROR: {exc}")

    print(f"\n{'='*55}")
    print(f"Phase 3 candidates : {len(candidates)}")
    print(f"Errors             : {errors}")

    if candidates:
        out_name = f"phase3_{date.today()}.txt"
        out_path = os.path.join(folder, out_name)
        with open(out_path, "w") as f:
            f.write("\n".join(candidates))
        print(f"Saved → {out_name}")
    else:
        print("No Phase 3 candidates found.")


if __name__ == "__main__":
    main()
