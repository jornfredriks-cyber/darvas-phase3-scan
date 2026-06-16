---
title: "yfinance Bulk Download: threads=N Triggers Yahoo Finance Rate Limiting"
date: 2026-06-03
category: performance-issues
module: darvas_screener
problem_type: performance_issue
component: tooling
severity: high
tags:
  - yfinance
  - rate-limiting
  - threading
  - bulk-download
  - yf.download
related_components:
  - development_workflow
symptoms:
  - Scan produced zero or near-zero Phase 3 candidates after enabling threads=4
  - High volume of yfinance stderr errors for valid tickers (rate limiting)
  - 100-ticker chunk took ~25s instead of ~8s — opposite of the expected speedup
  - Many tickers returned empty DataFrames despite being valid
root_cause: config_error
resolution_type: code_fix
---

# yfinance Bulk Download: threads=N Triggers Yahoo Finance Rate Limiting

## Problem

Enabling `threads=4` in `yf.download()` for bulk OHLC downloads triggered Yahoo Finance rate limiting, causing most ticker responses to return empty data. The Phase 3 scanner produced zero results because no tickers survived the technical filters when their price history was blank.

## Symptoms

- Scan returned no Phase 3 candidates in Command Central (previously returned 10–40)
- Command Central UI showed many error messages (yfinance stderr: `$ACB: possibly delisted; no price data found (period=1y)` repeated for many tickers)
- Wall-clock time for a 100-ticker chunk increased from ~8s (sequential) to ~38.9s (threaded) — the opposite of the intended speedup
- No Python exception or non-zero exit code; the process completed "successfully" with an empty result set

## What Didn't Work

- **Suspected `ResourceWarning: unclosed database` on stderr** — only appears when Python is launched with `-W all`; absent in normal operation with `PYTHONUNBUFFERED=1`
- **Suspected a DataFrame shape mismatch** between `threads=4` and `threads=False` output — MultiIndex structure was identical in both cases; the `_extract` function would have worked correctly if data were present
- **Suspected a Python-level crash or threading exception** — none found; `ThreadPoolExecutor` for the market cap step ran without errors in isolation; `multitasking` swallows thread exceptions internally
- **Suspected the larger chunk size (`fetch_chunk_size=100` vs 50)** — chunk size alone is not the issue; 100 tickers downloaded sequentially is fine

## Solution

Revert the `threads` parameter to `False` in both OHLC download call sites. All other config changes were kept.

`darvas_screener.py:129` and `darvas_scan.py:115`:

```python
# Before (broken — triggers rate limiting)
dl = yf.download(
    " ".join(chunk),
    period=HISTORY_PERIOD,
    interval="1d",
    group_by="ticker",
    progress=False,
    auto_adjust=True,
    threads=4,
)

# After (fixed — sequential, Yahoo-friendly)
dl = yf.download(
    " ".join(chunk),
    period=HISTORY_PERIOD,
    interval="1d",
    group_by="ticker",
    progress=False,
    auto_adjust=True,
    threads=False,   # DO NOT enable threading — Yahoo rate-limits concurrent v8 chart
                     # requests; threads=N is slower and causes silent empty responses
)
```

Config changes kept (safe and beneficial):

```ini
# darvas_config.ini [screener]
fetch_chunk_size = 100      # was 50; fewer round-trips, safe with sequential requests
inter_chunk_delay = 0.5     # was 1.0s; still enough breathing room between chunks
```

Market cap step kept with `ThreadPoolExecutor` (safe — small set, different endpoint):

```python
def _fetch_mcap(sym: str) -> tuple[str, float | None]:
    try:
        return sym, yf.Ticker(sym).fast_info.market_cap
    except Exception:
        return sym, None

with ThreadPoolExecutor(max_workers=5) as executor:
    for sym, mcap in executor.map(_fetch_mcap, passed):
        ...
```

## Why This Works

`yf.download()` with `threads=N` fires N concurrent HTTP requests to Yahoo Finance's v8 chart API simultaneously (`tkr.history()` under the hood, one request per ticker). Yahoo Finance's API detects concurrent request bursts and throttles responses:

- **Sequential (`threads=False`)**: each ticker ~80ms → 100 tickers → ~8s per chunk
- **Concurrent (`threads=4`)**: Yahoo throttles each response to ~400–500ms → 100 tickers → ~38.9s per chunk (~5× slower)

Throttled responses frequently return partial or empty data rather than an explicit HTTP 429 error, so `yf.download()` completes without raising an exception. Technical filters (EMA, ATH proximity, volume) pass zero tickers when there is no price history, producing a valid but empty result set. The silent failure is what makes this hard to diagnose — no crash, just no data.

The `ThreadPoolExecutor` for the market cap step is safe because:
1. It hits `fast_info`, a different Yahoo endpoint than the v8 chart API
2. It only processes ~200 tickers (post-filter survivors), not 6,500
3. Individual `Ticker()` calls are low-volume and don't share a rate-limit quota with bulk chart downloads

## Prevention

**1. Comment the `threads` parameter at the call site:**

```python
dl = yf.download(
    " ".join(chunk),
    ...
    threads=False,   # DO NOT enable — Yahoo rate-limits concurrent v8 chart requests;
                     # threads=N is slower and produces silent empty responses at scale
)
```

**2. Benchmark before committing a concurrency change.** A per-chunk timer is sufficient:

```python
import time
t0 = time.time()
dl = yf.download(...)
elapsed = time.time() - t0
# If elapsed > chunk_size * 0.15s, throttling is occurring
print(f"[bench] chunk={len(chunk)} tickers, elapsed={elapsed:.1f}s")
```

**3. Apply the volume threshold rule for yfinance concurrency:**

| Scenario | Recommendation |
|---|---|
| >500 tickers via `yf.download()` | `threads=False` — sequential only |
| <300 tickers via `yf.Ticker().fast_info` | `ThreadPoolExecutor(max_workers=4–8)` safe |
| Bulk OHLC via `yf.download()`, any size | Never use `threads=N` |

**4. Validate result counts as a smoke test.** Zero Phase 3 candidates from 6,500 tickers signals upstream data failure, not a genuine market condition:

```python
if not candidates:
    print("[WARN] Zero candidates — possible rate-limiting or data fetch failure",
          file=sys.stderr)
```

## Related Issues

- No existing docs/solutions/ entries at time of writing
