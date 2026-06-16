import configparser
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd
import requests
import yfinance as yf

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


try:
    import certifi
    for _k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ.setdefault(_k, certifi.where())
except ImportError:
    pass

# ── Screener parameters — loaded from darvas_config.ini, with hardcoded fallbacks
_cfg = configparser.ConfigParser()
_cfg.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), "darvas_config.ini"))
_s = _cfg["screener"] if "screener" in _cfg else {}

MIN_PRICE        = float(_s.get("min_price",         5.0))
MIN_MARKET_CAP   = int(  _s.get("min_market_cap",    500_000_000))
MIN_AVG_VOL_30D  = int(  _s.get("min_avg_vol_30d",   500_000))
MIN_ADR_PCT      = float(_s.get("min_adr_pct",       2.0))
EMA_FAST         = int(  _s.get("ema_fast",          50))
EMA_SLOW         = int(  _s.get("ema_slow",          200))
RSI_LOW          = float(_s.get("rsi_low",           45))
RSI_HIGH         = float(_s.get("rsi_high",          75))
ATH_MAX_DIST_PCT = float(_s.get("ath_max_dist_pct",  5.0))
HISTORY_PERIOD   =       _s.get("history_period",    "1y")
FETCH_CHUNK_SIZE = int(  _s.get("fetch_chunk_size",  50))
INTER_CHUNK_DELAY= float(_s.get("inter_chunk_delay", 1.0))

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
NYSE_URL   = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


# ── Universe ─────────────────────────────────────────────────────────────────

def _fetch_universe() -> list[str]:
    headers = {"User-Agent": "Mozilla/5.0"}
    tickers: list[str] = []

    # NASDAQ common stocks
    try:
        r = requests.get(NASDAQ_URL, headers=headers, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), sep="|")
        df = df[(df["ETF"] == "N") & (df["Test Issue"] == "N")]
        df = df[df["Symbol"].str.match(r"^[A-Z]{1,5}$", na=False)]
        tickers += df["Symbol"].tolist()
        print(f"  NASDAQ: {len(df)} common stocks")
    except Exception as e:
        print(f"  NASDAQ fetch failed: {e}")

    # NYSE common stocks (Exchange == "N")
    try:
        r = requests.get(NYSE_URL, headers=headers, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), sep="|")
        df = df[(df["ETF"] == "N") & (df["Test Issue"] == "N") & (df["Exchange"] == "N")]
        df = df[df["ACT Symbol"].str.match(r"^[A-Z]{1,5}$", na=False)]
        tickers += df["ACT Symbol"].tolist()
        print(f"  NYSE:   {len(df)} common stocks")
    except Exception as e:
        print(f"  NYSE fetch failed: {e}")

    seen, out = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ── OHLC helpers ──────────────────────────────────────────────────────────────

def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(how="all")
    if df.empty:
        return None
    df.columns = df.columns.str.lower()
    if not {"high", "low", "close", "volume"}.issubset(df.columns):
        return None
    return df


def _extract(downloaded: pd.DataFrame, symbol: str, chunk_len: int) -> pd.DataFrame | None:
    if downloaded is None or downloaded.empty:
        return None
    if isinstance(downloaded.columns, pd.MultiIndex):
        if symbol in downloaded.columns.get_level_values(0):
            return _clean_frame(downloaded[symbol])
        if symbol in downloaded.columns.get_level_values(1):
            return _clean_frame(downloaded.xs(symbol, level=1, axis=1))
        return None
    if chunk_len == 1:
        return _clean_frame(downloaded)
    return None


def _fetch_ohlc(symbols: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    chunks = list(_chunks(symbols, FETCH_CHUNK_SIZE))
    n = len(chunks)
    for idx, chunk in enumerate(chunks, 1):
        if idx == 1 or idx % 20 == 0 or idx == n:
            print(f"  chunk {idx}/{n}  ({idx * FETCH_CHUNK_SIZE}/{len(symbols)} tickers)…")
        try:
            dl = yf.download(
                " ".join(chunk),
                period=HISTORY_PERIOD,
                interval="1d",
                group_by="ticker",
                progress=False,
                auto_adjust=True,
                threads=False,
            )
            for sym in chunk:
                df = _extract(dl, sym, len(chunk))
                if df is not None:
                    result[sym] = df
        except Exception as e:
            print(f"  chunk {idx} error: {e}")
        if idx < n:
            time.sleep(INTER_CHUNK_DELAY)
    return result


# ── Technical filter functions ────────────────────────────────────────────────

def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs    = gain / loss
    return float((100 - 100 / (1 + rs)).iloc[-1])


def _adr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    return float(((high - low) / close * 100).tail(period).mean())


def _passes(df: pd.DataFrame) -> tuple[bool, str]:
    if len(df) < EMA_SLOW + 10:
        return False, "bars"
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    if float(c.iloc[-1]) < MIN_PRICE:
        return False, "price"
    if float(v.tail(30).mean()) < MIN_AVG_VOL_30D:
        return False, "volume"
    if _ema(c, EMA_FAST).iloc[-1] <= _ema(c, EMA_SLOW).iloc[-1]:
        return False, "ema"
    if _adr(h, l, c) < MIN_ADR_PCT:
        return False, "adr"
    rsi = _rsi(c)
    if not (RSI_LOW <= rsi <= RSI_HIGH):
        return False, "rsi"
    ath  = float(c.max())
    dist = (ath - float(c.iloc[-1])) / ath * 100
    if not (0.0 <= dist <= ATH_MAX_DIST_PCT):
        return False, "ath"
    return True, "ok"


# ── Main ──────────────────────────────────────────────────────────────────────

def run_screener(output_folder: str | None = None) -> str:
    folder = output_folder or os.path.dirname(os.path.abspath(__file__))
    today  = date.today()

    print("=" * 55)
    print(f"Darvas Screener  |  {today}")
    print(
        f"Price>{MIN_PRICE} | MktCap>{MIN_MARKET_CAP / 1e6:.0f}M | "
        f"AvgVol30D>{MIN_AVG_VOL_30D / 1e3:.0f}K | ADR>{MIN_ADR_PCT}% | "
        f"EMA{EMA_FAST}>EMA{EMA_SLOW} | RSI {RSI_LOW}-{RSI_HIGH} | "
        f"ATH dist 0-{ATH_MAX_DIST_PCT}%"
    )
    print("=" * 55)

    # 1. Universe
    print("\n[1/4] Fetching ticker universe (NASDAQ Trader)…")
    universe = _fetch_universe()
    print(f"  Total: {len(universe)} tickers\n")

    # 2. OHLC
    print(f"[2/4] Downloading {HISTORY_PERIOD} daily OHLC ({len(universe)} tickers)…")
    ohlc = _fetch_ohlc(universe)
    print(f"  Downloaded: {len(ohlc)}/{len(universe)}\n")

    # 3. Technical filters (in-memory, fast)
    print("[3/4] Applying technical filters…")
    passed = []
    rejected: dict[str, int] = {}
    for sym, df in ohlc.items():
        ok, reason = _passes(df)
        if ok:
            passed.append(sym)
        else:
            rejected[reason] = rejected.get(reason, 0) + 1
    print(f"  {len(passed)} pass all filters")
    for reason, count in sorted(rejected.items(), key=lambda x: -x[1]):
        print(f"  {count:5d} rejected by {reason}")
    print()

    # 4. Market cap (individual calls only on the small passing set)
    print(f"[4/4] Fetching market cap for {len(passed)} candidates…")

    def _fetch_mcap(sym: str) -> tuple[str, float | None]:
        try:
            return sym, yf.Ticker(sym).fast_info.market_cap
        except Exception:
            return sym, None

    mcap_map: dict[str, float | None] = {}
    checked = 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        for sym, mcap in executor.map(_fetch_mcap, passed):
            checked += 1
            mcap_map[sym] = mcap
            if checked % 25 == 0:
                qualifying = sum(1 for m in mcap_map.values() if m and m >= MIN_MARKET_CAP)
                print(f"  …{checked}/{len(passed)} checked, {qualifying} qualifying so far")

    final = [sym for sym in passed if mcap_map.get(sym) and mcap_map[sym] >= MIN_MARKET_CAP]
    print(f"  {len(final)} pass market cap >{MIN_MARKET_CAP / 1e6:.0f}M\n")

    # Save
    out_name = f"DARVAS Raw Screener_{today}.csv"
    out_path = os.path.join(folder, out_name)
    pd.DataFrame({"Symbol": final}).to_csv(out_path, index=False)
    print(f"Saved → {out_name}  ({len(final)} tickers)")
    return out_path


def main():
    folder   = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(folder, f"screener_log_{date.today()}.txt")
    log_file = open(log_path, "w", buffering=1)
    sys.stdout = _Tee(sys.__stdout__, log_file)
    try:
        run_screener(folder)
    finally:
        sys.stdout = sys.__stdout__
        log_file.close()
        print(f"Screener log → {os.path.basename(log_path)}")


if __name__ == "__main__":
    main()
