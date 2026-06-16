# LC Phase 3 Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `lc_scan.py` (LC-only) and `darvas_scan_lc.py` (combined) to scan for stocks with an active solid LC resistance line, writing `LC_Phase3_YYYY-MM-DD.txt` in the same format as `phase3_*.txt`.

**Architecture:** `is_lc_active()` is a bar-by-bar Python translation of the LC Line Breakout Pine Script. Both new scripts import utilities and `is_phase3` from the untouched `darvas_scan.py`. `darvas_scan_lc.py` fetches OHLC once and runs both checks per ticker in a single pass.

**Tech Stack:** Python 3.11+, pandas, numpy, yfinance, configparser. No new dependencies.

---

## File Map

| Action | File |
|---|---|
| Modify | `darvas_config.ini` — append `[lc_scanner]` section |
| Create | `lc_scan.py` — LC-only scan (config loading, `is_lc_active()`, `_run()`, `main()`) |
| Create | `darvas_scan_lc.py` — combined scan (imports both, fetches once, writes both outputs) |
| Create | `RUN LC Scan.command` — launcher: screener → lc_scan |
| Create | `RUN Darvas + LC Scan.command` — launcher: screener → darvas_scan_lc |
| Create | `tests/test_lc_active.py` — unit tests for `is_lc_active()` |
| **Untouched** | `darvas_scan.py`, `darvas_screener.py`, `RUN Darvas Scan.command` |

---

## Task 1: Add `[lc_scanner]` to `darvas_config.ini`

**Files:**
- Modify: `darvas_config.ini`

- [ ] **Step 1: Append the section**

Open `darvas_config.ini` and append to the end:

```ini
[lc_scanner]
min_bars_lc         = 5
lookback_lc         = 200
bars_back           = 300
left_bars           = 2
right_bars          = 2
allow_equal_highs   = true
replace_active_line = true
replace_only_higher = false
pivot_src           = high
history_period      = 1y
fetch_chunk_size    = 50
```

- [ ] **Step 2: Verify it parses**

```bash
cd "/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"
venv/bin/python3 -c "
import configparser
cfg = configparser.ConfigParser()
cfg.read('darvas_config.ini')
s = cfg['lc_scanner']
print('min_bars_lc:', s.get('min_bars_lc'))
print('lookback_lc:', s.get('lookback_lc'))
print('OK')
"
```
Expected output:
```
min_bars_lc: 5
lookback_lc: 200
OK
```

---

## Task 2: Write tests for `is_lc_active()`

**Files:**
- Create: `tests/test_lc_active.py`

- [ ] **Step 1: Create the tests directory**

```bash
mkdir -p "/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan/tests"
```

- [ ] **Step 2: Create `tests/test_lc_active.py`**

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from lc_scan import is_lc_active

DEFAULTS = dict(
    min_bars_lc=5,
    lookback_lc=200,
    bars_back=300,
    left_bars=2,
    right_bars=2,
    allow_equal_highs=True,
    replace_active_line=True,
    replace_only_higher=False,
    pivot_src="high",
)

def _df(highs, lows=None, closes=None):
    n = len(highs)
    if lows is None:
        lows = [h - 1.0 for h in highs]
    if closes is None:
        closes = [h - 0.5 for h in highs]
    return pd.DataFrame({"high": highs, "low": lows, "close": closes})


def test_empty_df_returns_false():
    df = pd.DataFrame({"high": [], "low": [], "close": []})
    result, price, age = is_lc_active(df, **DEFAULTS)
    assert result is False and price is None and age is None


def test_active_line_detected():
    # Pivot high = 15 at bar 4, confirmed at bar 6 (right_bars=2).
    # Age at bar 9 = 9-4 = 5 = min_bars_lc → first bar it goes active.
    # Closes are all 0.5 below highs, so never above pivot 15.
    highs  = [10, 11, 12, 13, 15, 14, 13, 12, 12, 12]
    df     = _df(highs)
    result, price, age = is_lc_active(df, **DEFAULTS)
    assert result is True
    assert price == pytest.approx(15.0)
    assert age == 5


def test_forming_line_not_active():
    # Same pivot at bar 4, data ends at bar 7 → age = 3 < min_bars_lc=5.
    highs = [10, 11, 12, 13, 15, 14, 13, 12]
    result, price, age = is_lc_active(_df(highs), **DEFAULTS)
    assert result is False


def test_breakout_deletes_line():
    # Pivot = 15 at bar 4, active by bar 9. Close > 15 at bar 10 → breakout.
    highs  = [10, 11, 12, 13, 15, 14, 13, 12, 12, 12, 16, 15]
    closes = [h - 0.5 for h in highs]
    closes[10] = 15.5   # close above pivot → line deleted
    lows   = [h - 1.0 for h in highs]
    result, price, age = is_lc_active(
        pd.DataFrame({"high": highs, "low": lows, "close": closes}), **DEFAULTS
    )
    assert result is False


def test_line_expires_past_lookback():
    # Pivot = 15 at bar 4. 260 bars of flat price.
    # Dynamic lookback will be short (bars_since_low ≈ 0 in a flat market),
    # so line expires well before bar 259 regardless.
    n = 260
    highs = [10.0] * n
    highs[2], highs[3], highs[4] = 13.0, 14.0, 15.0
    highs[5], highs[6]           = 13.0, 12.0
    result, price, age = is_lc_active(_df(highs), **DEFAULTS)
    assert result is False


def test_forming_line_not_replaced_by_new_pivot():
    # First pivot = 15 at bar 4, confirmed bar 6, forming (age < 5).
    # Potential second pivot at bar 5 (high=14), confirmed bar 7, but lower → irrelevant.
    # canReplace is False while first line is still forming.
    # Data ends at bar 8: age = 4 < 5 → still forming, result False.
    highs = [10, 11, 12, 13, 15, 14, 13, 12, 11]
    result, price, age = is_lc_active(_df(highs), **DEFAULTS)
    assert result is False


def test_replace_only_higher_blocks_lower_pivot():
    # First pivot = 20 at bar 4, active by bar 9.
    # Second pivot = 18 at bar 10 (lower), confirmed bar 12.
    # replace_only_higher=True: new pivot 18 < 20, no replacement.
    highs = [10,11,12,13, 20, 19,18,17,16,16, 18,17,16, 16,16,16]
    result, price, age = is_lc_active(
        _df(highs), **{**DEFAULTS, "replace_only_higher": True}
    )
    assert result is True
    assert price == pytest.approx(20.0)


def test_allow_equal_highs_false_rejects_plateau():
    # Plateau at bars 3,4,5 all high=15 — not a strict pivot high without equal highs.
    highs = [10, 12, 13, 15, 15, 15, 14, 13, 12, 12, 12, 12]
    result, price, age = is_lc_active(
        _df(highs), **{**DEFAULTS, "allow_equal_highs": False}
    )
    assert result is False
```

- [ ] **Step 3: Run tests — expect ImportError (lc_scan not written yet)**

```bash
cd "/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"
venv/bin/python3 -m pytest tests/test_lc_active.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'lc_scan'`

---

## Task 3: Create `lc_scan.py` with `is_lc_active()` and full runner

**Files:**
- Create: `lc_scan.py`

- [ ] **Step 1: Create `lc_scan.py`**

```python
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
        min_val    = win_lows.min()
        # Most recent occurrence (matches Pine Script's ta.lowestbars behaviour)
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
                can_replace = (
                    lc_price is None
                    or (replace_active_line and lc_is_act
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
    print(f"History       : {HISTORY_PERIOD}  |  Min bars LC: {MIN_BARS_LC}"
          f"  |  Lookback cap: {LOOKBACK_LC}")
    print(f"Pivot         : src={PIVOT_SRC}  left={LEFT_BARS}  right={RIGHT_BARS}")
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
```

- [ ] **Step 2: Run the test suite**

```bash
cd "/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"
venv/bin/python3 -m pytest tests/test_lc_active.py -v
```
Expected: `8 passed`

- [ ] **Step 3: Smoke-test the import**

```bash
venv/bin/python3 -c "from lc_scan import is_lc_active, main; print('OK')"
```
Expected: `OK`

---

## Task 4: Create `darvas_scan_lc.py`

**Files:**
- Create: `darvas_scan_lc.py`

- [ ] **Step 1: Create `darvas_scan_lc.py`**

```python
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
    SEED_FLOOR,
    fetch_ohlc_bulk,
    fetch_ohlc_single,
    find_latest_csv,
    is_phase3,
)
from lc_scan import (
    BARS_BACK,
    LEFT_BARS,
    LOOKBACK_LC,
    MIN_BARS_LC,
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

    ceil_str = f"{CEIL_MAX_DIST_PCT}%" if CEIL_MAX_DIST_PCT < 100 else "off"
    print(f"[Darvas] Max height: {MAX_HEIGHT_PCT}%  |  Ceil proximity: {ceil_str}"
          f"  |  EMA{EMA_SHORT}>{EMA_LONG}")
    print(f"[LC]     Min bars: {MIN_BARS_LC}  |  Lookback cap: {LOOKBACK_LC}"
          f"  |  Pivot src: {PIVOT_SRC}  left:{LEFT_BARS} right:{RIGHT_BARS}")
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

            # Single OHLC fetch, both checks run on same DataFrame
            in_p3, ceil, floor, height = is_phase3(df)
            lc_act, pivot, age         = is_lc_active(df)

            # Apply Darvas 52W proximity filter
            if in_p3 and CEIL_MAX_DIST_PCT < 100:
                high_52w  = df["high"].max()
                ceil_dist = (high_52w - ceil) / high_52w * 100
                if ceil_dist > CEIL_MAX_DIST_PCT:
                    in_p3 = False

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
```

- [ ] **Step 2: Smoke-test the import**

```bash
cd "/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"
venv/bin/python3 -c "from darvas_scan_lc import main; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Run full test suite**

```bash
venv/bin/python3 -m pytest tests/test_lc_active.py -v
```
Expected: `8 passed`

---

## Task 5: Create `.command` launchers

**Files:**
- Create: `RUN LC Scan.command`
- Create: `RUN Darvas + LC Scan.command`

- [ ] **Step 1: Create `RUN LC Scan.command`**

```bash
#!/bin/zsh
SCRIPT_DIR="/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"

cd "$SCRIPT_DIR"
venv/bin/python3 darvas_screener.py && venv/bin/python3 lc_scan.py

echo ""
echo "Press any key to close this window..."
read -k 1
```

- [ ] **Step 2: Create `RUN Darvas + LC Scan.command`**

```bash
#!/bin/zsh
SCRIPT_DIR="/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"

cd "$SCRIPT_DIR"
venv/bin/python3 darvas_screener.py && venv/bin/python3 darvas_scan_lc.py

echo ""
echo "Press any key to close this window..."
read -k 1
```

- [ ] **Step 3: Make both files executable**

```bash
cd "/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"
chmod +x "RUN LC Scan.command" "RUN Darvas + LC Scan.command"
```

- [ ] **Step 4: Verify executable bits**

```bash
ls -l "RUN LC Scan.command" "RUN Darvas + LC Scan.command"
```
Expected: both lines show `-rwxr-xr-x`

---

## Task 6: End-to-end smoke test

- [ ] **Step 1: Confirm darvas_scan.py is untouched**

```bash
cd "/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"
venv/bin/python3 -c "
from darvas_scan import is_phase3, fetch_ohlc_bulk, find_latest_csv
print('darvas_scan.py untouched ✓')
"
```
Expected: `darvas_scan.py untouched ✓`

- [ ] **Step 2: Dry-run lc_scan.py (import + config only)**

```bash
venv/bin/python3 -c "
import lc_scan
print('MIN_BARS_LC   :', lc_scan.MIN_BARS_LC)
print('LOOKBACK_LC   :', lc_scan.LOOKBACK_LC)
print('PIVOT_SRC     :', lc_scan.PIVOT_SRC)
print('Config loaded ✓')
"
```
Expected: prints values matching `darvas_config.ini` `[lc_scanner]` section.

- [ ] **Step 3: Run lc_scan.py against latest screener CSV**

```bash
venv/bin/python3 lc_scan.py
```
Expected:
- Prints screener filename and ticker count
- Prints `[  N/NNN] TICKER  LC ACTIVE  pivot:XX.XX  age:Xb` or `—` per ticker
- Writes `LC_Phase3_YYYY-MM-DD.txt` and `lc_scan_log_YYYY-MM-DD.txt`

- [ ] **Step 4: Check output file format**

```bash
cat "LC_Phase3_$(date +%Y-%m-%d).txt"
```
Expected: one ticker symbol per line, no extra formatting — identical pattern to `phase3_*.txt`.

- [ ] **Step 5: Run darvas_scan_lc.py**

```bash
venv/bin/python3 darvas_scan_lc.py
```
Expected:
- Two-column console output per ticker (Darvas | LC)
- Summary shows both Phase 3 and LC candidate counts
- Writes both `phase3_YYYY-MM-DD.txt` and `LC_Phase3_YYYY-MM-DD.txt`
