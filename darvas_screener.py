import io
import os
import time
from datetime import date

import pandas as pd
import requests
import yfinance as yf

try:
    import certifi
    for _k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        os.environ.setdefault(_k, certifi.where())
except ImportError:
    pass

# ── Screener parameters (match TradingView settings) ────────────────────────
MIN_PRICE        = 5.0
MIN_MARKET_CAP   = 500_000_000    # 500 M USD
MIN_AVG_VOL_30D  = 500_000
MIN_ADR_PCT      = 2.0            # 14-day average daily range %
EMA_FAST         = 50
EMA_SLOW         = 200
RSI_LOW          = 45
RSI_HIGH         = 75
ATH_MAX_DIST_PCT = 5.0            # price must be within 5 % of the 52-week high
                                   # (proxy for true ATH — adequate for Phase-3 setups)
HISTORY_PERIOD   = "1y"
FETCH_CHUNK_SIZE = 50
INTER_CHUNK_DELAY = 1.0

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


def _passes(df: pd.DataFrame) -> bool:
    if len(df) < EMA_SLOW + 10:
        return False
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    if float(c.iloc[-1]) < MIN_PRICE:
        return False
    if float(v.tail(30).mean()) < MIN_AVG_VOL_30D:
        return False
    if _ema(c, EMA_FAST).iloc[-1] <= _ema(c, EMA_SLOW).iloc[-1]:
        return False
    if _adr(h, l, c) < MIN_ADR_PCT:
        return False
    rsi = _rsi(c)
    if not (RSI_LOW <= rsi <= RSI_HIGH):
        return False
    ath  = float(c.max())
    dist = (ath - float(c.iloc[-1])) / ath * 100
    if not (0.0 <= dist <= ATH_MAX_DIST_PCT):
        return False
    return True


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
    passed = [sym for sym, df in ohlc.items() if _passes(df)]
    print(f"  {len(passed)} pass price / volume / EMA / ADR / RSI / ATH\n")

    # 4. Market cap (individual calls only on the small passing set)
    print(f"[4/4] Fetching market cap for {len(passed)} candidates…")
    final: list[str] = []
    for i, sym in enumerate(passed, 1):
        time.sleep(0.3)
        try:
            mcap = yf.Ticker(sym).fast_info.market_cap
            if mcap and mcap >= MIN_MARKET_CAP:
                final.append(sym)
        except Exception:
            pass
        if i % 25 == 0:
            print(f"  …{i}/{len(passed)} checked, {len(final)} qualifying so far")
    print(f"  {len(final)} pass market cap >{MIN_MARKET_CAP / 1e6:.0f}M\n")

    # Save
    out_name = f"DARVAS Raw Screener_{today}.csv"
    out_path = os.path.join(folder, out_name)
    pd.DataFrame({"Symbol": final}).to_csv(out_path, index=False)
    print(f"Saved → {out_name}  ({len(final)} tickers)")
    return out_path


if __name__ == "__main__":
    run_screener()
