import configparser
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


# ── Parameters — loaded from darvas_config.ini, with hardcoded fallbacks ─────
_cfg = configparser.ConfigParser()
_cfg.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), "darvas_config.ini"))
_s = _cfg["scanner"] if "scanner" in _cfg else {}

MAX_HEIGHT_PCT    = float(_s.get("max_height_pct",    5.0))
CEIL_MAX_DIST_PCT = float(_s.get("ceil_max_dist_pct", 100.0))  # 100 = disabled by default
SEED_FLOOR        = _s.get("seed_floor",   "true").lower() == "true"
EMA_SHORT         = int(  _s.get("ema_short",        20))
EMA_LONG          = int(  _s.get("ema_long",         50))
HISTORY_PERIOD    =       _s.get("history_period",   "1y")
FETCH_CHUNK_SIZE  = int(  _s.get("fetch_chunk_size",  50))
FETCH_RETRIES     = int(  _s.get("fetch_retries",      2))
FETCH_RETRY_DELAY = float(_s.get("fetch_retry_delay", 2.0))


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
      0 – hunting for a ceiling candidate (gated by EMA trend filter)
      2 – ceiling confirmed, hunting for floor
      3 – box confirmed and active (what we want)
    """
    close_ser = pd.Series(df["close"].to_numpy())
    ema20 = close_ser.ewm(span=EMA_SHORT, adjust=False).mean().to_numpy()
    ema50 = close_ser.ewm(span=EMA_LONG,  adjust=False).mean().to_numpy()

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

        # ── Phase 0: hunt ceiling (EMA-gated) ───────────────────────────────
        if phase == 0:
            e20, e50 = ema20[i], ema50[i]
            ema_bearish = not (pd.isna(e20) or pd.isna(e50)) and e20 < e50
            if ema_bearish:
                # EMA bearish — discard partial candidate so it cannot resume
                # when the trend recovers
                if ceil_candidate is not None:
                    ceil_candidate    = None
                    ceil_count        = 0
                    lowest_since_ceil = None
            else:
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
                            # When seed_floor=True the floor search starts from
                            # the lowest low observed during ceiling confirmation
                            floor_low = lowest_since_ceil if seed_floor else None
                            phase = 2

        # ── Phase 2: ceiling confirmed, hunt floor ───────────────────────────
        # 'if' (not 'elif') matches Pine Script: when Phase 0 confirms the ceiling
        # and sets phase=2 on the same bar, Phase 2 also runs on that bar.
        if phase == 2:
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
                        box_height = (ceil_high - floor_low) / ceil_high * 100
                        if box_height <= max_height:
                            confirmed_floor = floor_low
                            phase = 3
                        else:
                            do_reset = True

        # ── Phase 3: active box ──────────────────────────────────────────────
        # 'if' (not 'elif') matches Pine Script: when Phase 2 confirms the floor
        # and sets phase=3 on the same bar, Phase 3 also runs on that bar.
        if phase == 3:
            if close > ceil_high:
                # Breakout → not Phase 3 anymore
                do_reset = True
            elif low < confirmed_floor:
                # Floor broken (wick or close) — keep ceiling, hunt new floor
                floor_low         = low
                floor_count       = 0
                confirmed_floor   = None
                lowest_since_ceil = None
                phase = 2

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
        box_height = (ceil_high - confirmed_floor) / ceil_high * 100
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
    ceil_dist_str = f"{CEIL_MAX_DIST_PCT}%" if CEIL_MAX_DIST_PCT < 100 else "off"
    print(f"History period: {HISTORY_PERIOD}  |  Max box height: {MAX_HEIGHT_PCT}%  |  Ceil proximity: {ceil_dist_str}")
    print(f"EMA filter    : EMA{EMA_SHORT} > EMA{EMA_LONG} (gates Phase 0)")
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
                if CEIL_MAX_DIST_PCT < 100:
                    high_52w = df["high"].max()
                    ceil_dist = (high_52w - ceil) / high_52w * 100
                    if ceil_dist > CEIL_MAX_DIST_PCT:
                        print(f"  [{i:3d}/{len(symbols)}] {sym:10s}  — ceil {ceil_dist:.1f}% below 52W high")
                        continue
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
