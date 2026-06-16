# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Scans

The project uses a local `venv/` virtualenv. All commands below assume the project root as the working directory.

```bash
# Full Darvas-only pipeline (screener → Darvas Phase 3 scan)
venv/bin/python3 darvas_screener.py && venv/bin/python3 darvas_scan.py

# Full LC-only pipeline (screener → LC scan)
venv/bin/python3 darvas_screener.py && venv/bin/python3 lc_scan.py

# Combined pipeline (screener → Darvas + LC in one pass)
venv/bin/python3 darvas_screener.py && venv/bin/python3 darvas_scan_lc.py

# LW Low pipeline (screener → last-week-low proximity scan)
venv/bin/python3 darvas_screener.py && venv/bin/python3 lw_low_scan.py

# Run tests
venv/bin/python3 -m pytest tests/

# Run a single test
venv/bin/python3 -m pytest tests/test_lc_active.py::test_active_line_detected
```

macOS double-click launchers (`RUN Darvas Scan.command`, `RUN LC Scan.command`, `RUN Darvas + LC Scan.command`, `RUN LW Low Candidates.command`) wrap the same commands above.

## Architecture

### Two-Stage Pipeline

Every scan run follows the same two stages:

**Stage 1 — Screener (`darvas_screener.py`):**  
Downloads 1 year of daily OHLC for the full NASDAQ+NYSE universe (~6,500 tickers). Applies in-memory filters (price, volume, EMA trend, ADR, RSI, ATH proximity) and then individual market-cap checks on survivors. Writes `DARVAS Raw Screener_YYYY-MM-DD.csv` to the project root.

**Stage 2 — Scanner(s):**  
Read the latest screener CSV (matched by filename glob), download OHLC again for the surviving tickers only, and run the pattern-detection algorithm. Outputs a `.txt` file of candidate tickers.

| Script | Stage 2 algorithm | Output file |
|---|---|---|
| `darvas_scan.py` | Darvas Phase 3 state machine | `phase3_YYYY-MM-DD.txt` |
| `lc_scan.py` | LC Line Breakout state machine | `LC_Phase3_YYYY-MM-DD.txt` |
| `darvas_scan_lc.py` | Both algorithms in a single pass | Both `.txt` files above |
| `lw_low_scan.py` | Last-week-low proximity check (no state machine — standalone, not part of `darvas_scan_lc.py`) | `LW_Low_YYYY-MM-DD.txt` |

### Module Relationships

`darvas_scan.py` is the shared utility layer. `lc_scan.py` and `darvas_scan_lc.py` both import from it:

- `fetch_ohlc_bulk` / `fetch_ohlc_single` — chunked yfinance download with retry
- `find_latest_csv` — locates the most recent screener output
- `_Tee` — stdout multiplexer for simultaneous terminal + log file output

`darvas_scan_lc.py` imports the detection functions directly from both modules and runs them on a single shared OHLC fetch per symbol.

### Key Detection Functions

**`is_phase3(df)`** in `darvas_scan.py`:  
Bar-by-bar state machine (0 → 2 → 3) translated 1-to-1 from the Pine Script TradingView indicator. Phase 0 hunts for a ceiling candidate (gated by EMA20 > EMA50). Phase 2 confirms the ceiling and hunts the floor. Phase 3 is the active confirmed box. Returns `(True, ceil, floor, height_pct)` or `(False, None, None, None)`.

**`is_lc_active(df)`** in `lc_scan.py`:  
Tracks a single horizontal resistance line from a pivot high. The line starts "forming" and becomes "active" once it has aged `min_bars_lc` bars without a close above it. Uses a dynamic lookback window (shrinks in flat markets). Returns `(True, pivot_price, age_bars)` or `(False, None, None)`.

**`is_near_last_week_low(df)`** in `lw_low_scan.py`:  
No state machine — resamples daily lows into Friday-anchored weekly bins and checks whether the latest close sits within `±proximity_pct` of the most recently *completed* Monday–Friday week's low. Returns `(True, last_week_low, distance_pct)` or `(False, None, None)`.

### Configuration

All tunable parameters live in `darvas_config.ini` (sections `[screener]`, `[scanner]`, `[lc_scanner]`). Each script reads the `.ini` at startup and falls back to hardcoded defaults if the file is missing. Parameters in the `[scanner]` and `[lc_scanner]` sections must stay in sync with the corresponding TradingView Pine Script indicator inputs — divergence causes the Python scan to return different results than the chart.

### Critical Constraint: yfinance Threading

**Never pass `threads=N` to `yf.download()`** — Yahoo Finance's v8 chart API rate-limits concurrent requests, producing silent empty responses. The bulk download functions always use `threads=False`. The market-cap step in the screener uses `ThreadPoolExecutor` safely because it hits a different Yahoo endpoint (`fast_info`) with a small ticker count (~200 post-filter survivors). See `docs/solutions/performance-issues/yfinance-bulk-download-threading-rate-limit.md` for the full investigation.

### Output Files (project root)

| File pattern | Producer | Consumer |
|---|---|---|
| `DARVAS Raw Screener_YYYY-MM-DD.csv` | `darvas_screener.py` | scanner scripts |
| `phase3_YYYY-MM-DD.txt` | scanner scripts | manual review |
| `LC_Phase3_YYYY-MM-DD.txt` | scanner scripts | manual review |
| `screener_log_YYYY-MM-DD.txt` | screener | debugging |
| `scan_log_YYYY-MM-DD.txt` | scanner | debugging |
| `lc_scan_log_YYYY-MM-DD.txt` | lc scanner | debugging |
| `LW_Low_YYYY-MM-DD.txt` | lw low scanner | manual review |
| `lw_low_scan_log_YYYY-MM-DD.txt` | lw low scanner | debugging |

## Domain Vocabulary

See `CONCEPTS.md` for the full glossary. Key terms:

- **Phase 3** — Darvas Box confirmed (ceiling + floor both held for ≥3 bars) with no breakout yet. This is what the scanner detects.
- **LC Line** — Horizontal resistance from a pivot high. "Forming" until aged `min_bars_lc` bars; "active" (solid) after.
- **Ceiling** — Upper bound of the Darvas Box. A close above it triggers a breakout reset.
- **Floor** — Lower bound. A wick below (without a close below) sends the box back to floor-hunting without resetting the ceiling.
