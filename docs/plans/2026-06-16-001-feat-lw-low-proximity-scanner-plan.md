---
title: "feat: LW Low proximity scanner"
status: completed
created: 2026-06-16
type: feat
---

# feat: LW Low proximity scanner

## Summary

Add a new scanner, `lw_low_scan.py`, that reuses the existing screener pipeline (same `darvas_config.ini`-driven universe, same screener CSV, same OHLC fetch utilities) but replaces Darvas Box detection with a simple proximity check: flag any ticker whose latest close sits within a configurable `±N%` band (default ±5%) of the low of the most recently completed Monday–Friday calendar week. Darvas Box (`darvas_scan.py`) and LC Line (`lc_scan.py`) detection are untouched.

## Problem Frame

The existing pipeline detects two specific consolidation patterns (Darvas Box, LC Line). The user wants a third, much simpler signal that does not require any box or line state machine: "is this ticker currently trading near where it was at its weakest point last week?" — a basic support-proximity screen, intentionally loose at first (±5%) so it can be tightened after live testing.

## Requirements

- Reuse the same screener output (`DARVAS Raw Screener_*.csv`) and the same OHLC fetch utilities (`fetch_ohlc_bulk`, `fetch_ohlc_single`, `find_latest_csv`) already shared by `darvas_scan.py` / `lc_scan.py` — no new screener.
- Detection logic must NOT use Darvas Box or LC Line state machines. It computes the low of the most recently *completed* calendar week (Monday–Friday) and compares the latest close against it.
- A ticker qualifies when `abs((latest_close - last_week_low) / last_week_low * 100) <= proximity_pct`, i.e. within `proximity_pct` percent above OR below last week's low.
- `proximity_pct` must be tunable via `darvas_config.ini` (start at 5.0, per user request, to allow tightening after testing) — never hardcoded.
- Output a `.txt` candidate file and a log file following the existing naming/logging conventions (`_Tee`, one ticker per line).
- Provide a double-click launcher `RUN LW Low Candidates.command` that runs `darvas_screener.py` then `lw_low_scan.py`, matching the existing `RUN LC Scan.command` pattern exactly (same shebang, same `cd`, same "press any key" footer).

## Key Technical Decisions

### KTD1: "Last week" = most recently completed Mon–Fri calendar week, determined from the data itself

Resample the daily OHLC frame's `low` column to weekly bins anchored on Friday (`resample("W-FRI")`), which groups Saturday–Friday into bins labeled by that bin's Friday. The *last* bin is only usable as "last week" if it is actually complete — i.e. if the OHLC frame's last trading day is on or after that bin's Friday label. If the last trading day falls before that Friday (mid-week data, the current week still in progress), fall back to the second-to-last bin instead.

**Rationale:** Using the data's own last trading day (rather than `date.today()`) keeps the detection function pure and deterministic — no wall-clock dependency, fully unit-testable with synthetic date ranges. It also means a scan run after Friday's close immediately treats that week as "complete" rather than waiting until Monday, which matches how the existing scanner scripts are run ad hoc for next-session trading decisions.

**Accepted limitation:** if the week's actual last trading day is a Thursday because Friday was a market holiday, the data's last trading day (Thursday) falls before the bin's Friday label, so the week is misclassified as "still in progress" and the function falls back to the prior week's low. This is a rare, narrow edge case (a handful of weeks per year) and is not worth a trading-calendar dependency to fix. Documented here and covered by a test asserting the documented (not "ideal") behavior.

### KTD2: Proximity uses latest close, not intraday low/high

Mirrors the existing `MAX_PRICE_DIST_PCT` check in `lc_scan.py` (`df["close"].iloc[-1]`), which is the established local convention for "how close is price to a reference level" checks in this codebase.

### KTD3: Symmetric ±band, not breakout/breakdown-aware

The user explicitly asked for `±5%` (above OR below last week's low) rather than an asymmetric "only above" band, to keep the first pass loose for live testing before tightening `proximity_pct` down in `darvas_config.ini`.

### KTD4: Standalone script and launcher, not merged into `darvas_scan_lc.py`

This scan is added as its own module + its own launcher (`RUN LW Low Candidates.command`), not wired into the existing combined Darvas+LC runner. Keeps `darvas_scan_lc.py` untouched and avoids conflating an unrelated signal into the existing combined output. A combined "Darvas + LC + LW Low" runner is explicitly deferred (see Scope Boundaries).

## Scope Boundaries

**In scope:**
- New `[lw_low_scanner]` config section, new `lw_low_scan.py` module, new test file, new launcher, a small documentation update.

**Out of scope / non-goals:**
- Modifying `darvas_scan.py`, `lc_scan.py`, `darvas_scan_lc.py`, or `darvas_screener.py`.
- Any new screener-level filters — the existing screener CSV is reused as-is.

### Deferred to Follow-Up Work
- A combined runner that fetches OHLC once and runs Darvas + LC + LW Low together (mirrors `darvas_scan_lc.py`'s pattern) — not built now since the user only asked for a standalone scanner; can be added later if the three signals are commonly run together.
- Tightening `proximity_pct` below 5.0 once the user has live-tested the candidate list — explicitly a config change for the user to make later, not a code change.

## Implementation Units

### U1. Add `[lw_low_scanner]` config section

**Goal:** Make the proximity band and fetch parameters tunable from `darvas_config.ini`, matching the `[lc_scanner]` section's structure and inline-comment style.

**Requirements:** Supports the "tunable `proximity_pct`" and "reuse existing config conventions" requirements.

**Dependencies:** None.

**Files:**
- Modify: `darvas_config.ini`

**Approach:** Append a new `[lw_low_scanner]` section after `[lc_scanner]`:
```ini
[lw_low_scanner]
# Band around last week's low, in percent. A ticker qualifies when its latest
# close is within this many percent ABOVE OR BELOW last week's low.
# Start loose (5.0) and tighten after live testing.
proximity_pct       = 5.0

fetch_chunk_size    = 50
```

Deliberately omits `history_period`: `darvas_scan.py`'s `fetch_ohlc_bulk`/`fetch_ohlc_single` hardcode `period=HISTORY_PERIOD` from their own `[scanner]`-section constant inside `yf.download()`, with no parameter to override it per call — a `[lw_low_scanner].history_period` value would load but never be wired to anything (the same dead-config gap already present, unused, in `[lc_scanner]`). Not propagating a known-unused setting into new code.

**Patterns to follow:** `darvas_config.ini` `[lc_scanner]` section's inline-comment style (comment above each tunable, blank line between logical groups).

**Test scenarios:**
Test expectation: none — pure config file addition, parsed by U2's module-level `configparser` block and exercised indirectly by U2/U3's tests.

**Verification:** `configparser.ConfigParser().read("darvas_config.ini")["lw_low_scanner"]["proximity_pct"]` returns `"5.0"`.

---

### U2. Implement `lw_low_scan.py`

**Goal:** New module providing `is_near_last_week_low()` (the detection function) plus the same `main()`/`_run()` pipeline shape as `lc_scan.py`: read latest screener CSV, bulk-fetch OHLC, run detection per ticker, write `.txt` candidates and a log file.

**Requirements:** Covers all functional requirements — reuse of screener/fetch utilities, weekly-low detection logic, ±band check, tunable config, output file, logging.

**Dependencies:** U1 (config section must exist for the module-level config load to find real values; falls back to hardcoded defaults otherwise, matching the existing `lc_scan.py` convention).

**Files:**
- Create: `lw_low_scan.py`
- Create (test): `tests/test_lw_low_scan.py` (see U3)

**Approach:**
- Import `_Tee`, `fetch_ohlc_bulk`, `fetch_ohlc_single`, `find_latest_csv` from `darvas_scan` — exactly as `lc_scan.py` does. Do not duplicate fetch logic.
- Load `[lw_low_scanner]` via the same `configparser` + fallback-default pattern used in `lc_scan.py`'s config block (`PROXIMITY_PCT`, `FETCH_CHUNK_SIZE`).
- `is_near_last_week_low(df, proximity_pct=PROXIMITY_PCT) -> tuple` implements KTD1/KTD2/KTD3: resample `df["low"]` weekly (`W-FRI`), pick the last bin if the frame's final trading day is on/after that bin's Friday, else the second-to-last bin; guard for fewer than 2 weekly bins (insufficient history) by returning `(False, None, None)`; compute `distance_pct = (latest_close - completed_low) / completed_low * 100`; return `(True, completed_low, distance_pct)` when `abs(distance_pct) <= proximity_pct`, else `(False, None, None)`.
- `main()`/`_run(folder)` mirror `lc_scan.py`'s structure: log to `lw_low_scan_log_{date}.txt` via `_Tee`, read the latest screener CSV, bulk-fetch + single-retry OHLC exactly as `lc_scan.py` does, call `is_near_last_week_low` per ticker, print a per-ticker line (`LW LOW  low:{:.2f}  dist:{:+.1f}%` or `—`), and on completion write `LW_Low_{date}.txt` (one ticker per line) if any candidates were found.

**Technical design (directional, not implementation-specification):**
```
weekly_low = df["low"].resample("W-FRI").min()
if len(weekly_low) < 2:
    return False, None, None

last_bin_friday = weekly_low.index[-1]
last_trading_day = df.index[-1]

completed_low = (weekly_low.iloc[-1] if last_trading_day >= last_bin_friday
                  else weekly_low.iloc[-2])

distance_pct = (df["close"].iloc[-1] - completed_low) / completed_low * 100
qualifies = abs(distance_pct) <= proximity_pct
```

**Patterns to follow:** `lc_scan.py` in its entirety — config-loading block, `main()`/`_run()` skeleton, retry-on-failed-fetch block, per-ticker print formatting, output-file-write block. `darvas_scan.py`'s `is_phase3()` docstring style (states the return contract explicitly) for `is_near_last_week_low()`'s docstring.

**Test scenarios:**
- Happy path: close exactly at last week's low (`distance_pct == 0`) → qualifies.
- Happy path: close 3% above last week's low → qualifies (within ±5% default).
- Happy path: close 3% below last week's low → qualifies (within ±5% default, confirms symmetric band).
- Edge case: close exactly at the `+proximity_pct` boundary → qualifies (inclusive `<=`).
- Edge case: close exactly at the `-proximity_pct` boundary → qualifies (inclusive `<=`).
- Edge case: close at `proximity_pct + 0.01` → excluded.
- Edge case: fewer than 2 completed weekly bins (e.g. a recent IPO with ~5 trading days of history) → returns `(False, None, None)`.
- Edge case: last trading day is mid-week (e.g. Wednesday) → uses the *prior* completed week's low, not the in-progress week's partial low (covers KTD1's core behavior).
- Edge case: last trading day is a Friday → uses *that* week's low (now complete), confirming the "complete on Friday, not Monday" rule from KTD1.
- Edge case: documents KTD1's accepted limitation — a week whose actual last trading day is Thursday (Friday holiday) is treated as still-in-progress and falls back to the prior week. Assert the documented behavior so a future change to this rule is a deliberate, visible diff.
- Error path: empty DataFrame → returns `(False, None, None)` (matches `is_lc_active`'s empty-df guard).

**Verification:** `tests/test_lw_low_scan.py` passes; `venv/bin/python3 -c "from lw_low_scan import is_near_last_week_low, main; print('OK')"` succeeds; running `lw_low_scan.py` against an existing screener CSV produces `LW_Low_YYYY-MM-DD.txt` and `lw_low_scan_log_YYYY-MM-DD.txt` with the same one-ticker-per-line format as `LC_Phase3_*.txt`.

---

### U3. Add `tests/test_lw_low_scan.py`

**Goal:** Unit-test `is_near_last_week_low()` in isolation, following the existing `tests/test_lc_active.py` style (synthetic DataFrames, one behavior per test, comment explaining the constructed scenario).

**Requirements:** Verifies KTD1 (week-completeness rule), KTD2 (close-based comparison), KTD3 (symmetric band), and the insufficient-history guard.

**Dependencies:** U2 (imports `is_near_last_week_low` from `lw_low_scan`).

**Files:**
- Create: `tests/test_lw_low_scan.py`

**Approach:** Unlike `tests/test_lc_active.py`'s index-free DataFrames, these tests need an explicit `DatetimeIndex` (e.g. `pd.date_range(start=..., periods=n, freq="B")`) so the weekly resample has real calendar semantics. Build a small helper (e.g. `_weekly_df(...)`) that takes a start date and a list of `(low, close)` pairs per business day and returns a DataFrame indexed accordingly — mirrors the `_df()` helper pattern in `test_lc_active.py` but date-aware.

**Patterns to follow:** `tests/test_lc_active.py` — module-level `DEFAULTS` dict (here: just `proximity_pct=5.0`), one `def test_*` per scenario, inline comment above each test explaining the constructed bars/dates and why the assertion follows.

**Test scenarios:** Same list as enumerated under U2 — this unit's sole purpose is encoding those scenarios as executable tests, one test function per bullet.

**Verification:** `venv/bin/python3 -m pytest tests/test_lw_low_scan.py -v` — all tests pass.

---

### U4. Add `RUN LW Low Candidates.command` launcher

**Goal:** Double-click launcher running `darvas_screener.py && lw_low_scan.py`, identical in structure to `RUN LC Scan.command`.

**Requirements:** Satisfies the "double-click launcher" requirement with the exact filename the user requested.

**Dependencies:** U2 (script must exist for the launcher to call it).

**Files:**
- Create: `RUN LW Low Candidates.command`

**Approach:** Copy `RUN LC Scan.command` verbatim, swapping `lc_scan.py` for `lw_low_scan.py`. Same shebang (`#!/bin/zsh`), same `SCRIPT_DIR` absolute path, same "press any key to close" footer. Mark executable (`chmod +x`).

**Patterns to follow:** `RUN LC Scan.command` (exact structure).

**Test scenarios:**
Test expectation: none — shell launcher with no branching logic; correctness is verified by running it once.

**Verification:** `ls -l "RUN LW Low Candidates.command"` shows the executable bit set; double-clicking (or running directly) executes the screener then `lw_low_scan.py` and closes only after a keypress.

---

### U5. Update documentation

**Goal:** Keep `CLAUDE.md` (Darvas Phase3 Scan) and `CONCEPTS.md` in sync with the new script, per this project's existing convention of documenting every scanner script in both files.

**Requirements:** No functional requirement; keeps institutional documentation accurate for future sessions.

**Dependencies:** U2 (describes the shipped behavior).

**Files:**
- Modify: `CLAUDE.md` (Darvas Phase3 Scan root)
- Modify: `CONCEPTS.md`

**Approach:** `CLAUDE.md` documents each existing scanner in three separate places — update all three, matching the existing `lc_scan.py`/`is_lc_active`/`LC_Phase3_*.txt` entries' level of detail in each:
- The Stage-2-algorithm table under "Two-Stage Pipeline" — add a row for `lw_low_scan.py` → its detection approach → `LW_Low_YYYY-MM-DD.txt`.
- The "Key Detection Functions" section — add an entry describing `is_near_last_week_low(df)`'s return contract, matching the existing `is_phase3()`/`is_lc_active()` entries.
- The "Output Files (project root)" table — add rows for `LW_Low_YYYY-MM-DD.txt` and `lw_low_scan_log_YYYY-MM-DD.txt`.

In `CONCEPTS.md`, add a short glossary entry for "LW Low" (or "Last Week Low") under the Scanner Pipeline section, matching the existing "LC Line" entry's style (one short paragraph, no implementation detail).

**Patterns to follow:** Existing `CLAUDE.md` table rows and `CONCEPTS.md` entries for `lc_scan.py` / "LC Line".

**Test scenarios:**
Test expectation: none — documentation-only change.

**Verification:** Manual read-through; new entries match the formatting of surrounding entries.

---

## Risks & Dependencies

- **Friday-holiday week misclassification (KTD1):** accepted and documented, not mitigated. Low impact — affects which week's low is used only during the handful of weeks per year with a Friday market holiday, and only shifts the comparison to the prior week's low rather than producing a wrong/crashing result.
- **No new external dependency:** reuses `pandas`'s `resample`, already a transitive dependency via existing OHLC handling in `darvas_scan.py`.
- **Screener coupling:** like `lc_scan.py` and `darvas_scan.py`, this scanner is only as good as the shared screener CSV — no new risk introduced beyond what already exists for the other two scanners.

## Verification Strategy

- `venv/bin/python3 -m pytest tests/test_lw_low_scan.py -v` — new unit tests pass.
- `venv/bin/python3 -m pytest tests/ -v` — full suite still passes (confirms `darvas_scan.py`/`lc_scan.py` untouched).
- Manual run: `venv/bin/python3 darvas_screener.py && venv/bin/python3 lw_low_scan.py` against a real screener CSV, confirming console output format and the written `LW_Low_*.txt` / `lw_low_scan_log_*.txt` files.
- Double-click `RUN LW Low Candidates.command` once to confirm the launcher itself works end-to-end.
