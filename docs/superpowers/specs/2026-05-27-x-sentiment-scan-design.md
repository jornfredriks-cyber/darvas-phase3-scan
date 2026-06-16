# X Sentiment Scan — Design Spec (2026-05-27)

## Overview

A Python script that reads the latest `phase3_*.txt` ticker list produced by the Darvas scan, searches X (Twitter) for high-engagement sentiment posts for each ticker over the last 30 days, and writes a rated Markdown report to an Obsidian note folder.

---

## Files

| File | Role |
|------|------|
| `x_sentiment.py` | New standalone + importable script |
| `x_cookies.json` | One-time cookie store (`auth_token`, `ct0`) — not committed |
| `darvas_scan.py` | Modified: one import + one `asyncio.run()` call added at end of `_run()` |
| Output: `X Research Phase3 Candidates/X_Sentiment_YYYY-MM-DD.md` | Obsidian Markdown report |

**Locations:**
- Script folder: `/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan/`
- Output folder: `/Users/jamesblond/Documents/1-Projects/AI Trade/Breakout Strategy Daily/X Research Phase3 Candidates/`

---

## Input Parsing

The phase3 file format is tab-separated with a leading line number:
```
1\tADAM
2\tASND
```
The script globs `phase3_*.txt` by modification time (same pattern as `find_latest_csv` in `darvas_scan.py`), then strips the number prefix to extract clean tickers. The date is parsed from the filename (`phase3_YYYY-MM-DD.txt`) and used in the output filename.

---

## X Authentication

Library: `twscrape` (async, supports advanced search operators including `min_faves`, `min_retweets`, `since`).

Authentication: cookie-based (works with Google-login X accounts). One-time setup:
1. Open x.com in a browser, open DevTools → Application → Cookies
2. Copy `auth_token` and `ct0` values
3. Paste into `x_cookies.json`:
   ```json
   { "auth_token": "...", "ct0": "..." }
   ```

The script reads this file and registers the account with twscrape's account pool on each run.

---

## Search Query

For each ticker:
```
$TICKER (bullish OR bearish OR "strong buy" OR "loading up" OR dumping OR "big catalyst") min_faves:50 min_retweets:10 lang:en since:YYYY-MM-DD
```
- `since` = today minus 30 days
- Max 50 tweets fetched per ticker
- 0.5s delay between tickers to respect rate limits

---

## Rating Logic

### Step 1 — Keyword classification per tweet

Each tweet text is checked for:
- **Bullish signals:** `bullish`, `strong buy`, `loading up`, `upgrade`, `breakout`, `catalyst`, `buy`
- **Bearish signals:** `bearish`, `dumping`, `strong sell`, `downgrade`, `breakdown`, `short`

A tweet is classified bullish (+1), bearish (-1), or neutral (0). Classification is case-insensitive. A tweet matching both sides is neutral.

### Step 2 — Engagement-weighted score

```
weighted_score = sum(classification × likes for each tweet)
total_weight   = sum(likes for each tweet)
net_sentiment  = weighted_score / total_weight  (range: -1 to +1)
```

### Step 3 — Map to 1–5 rating

| `net_sentiment` | Rating |
|-----------------|--------|
| ≥ 0.6 | 5 — Strongly Bullish |
| ≥ 0.3 | 4 — Bullish |
| > -0.3 | 3 — Mixed/Neutral |
| > -0.6 | 2 — Cautious |
| ≤ -0.6 | 1 — Bearish |
| Fewer than 3 tweets matched | 3 — noted as "Low X visibility" |

### Step 4 — Key note

The highest-engagement tweet (score = likes + 2 × retweets), text truncated to 120 characters, with engagement appended:
```
"Loading up $ASND ahead of catalyst" (847♥ 210🔁)
```
If no tweets found: `No high-engagement posts found`.

---

## Output Format

File: `X_Sentiment_YYYY-MM-DD.md` (date from phase3 filename)

```markdown
---
date: 2026-05-27
tickers: ADAM, ASND, EXEL, ...
---

# X Sentiment Scan — Phase 3 Candidates (2026-05-27)

> Search: `$TICKER (bullish OR bearish OR "strong buy" OR "loading up" OR dumping OR "big catalyst") min_faves:50 min_retweets:10` — last 30 days

| Ticker | Rating | Tweets | Key Note |
|--------|--------|--------|----------|
| SBLK   | 4      | 18     | "Q1 beat, loading up $SBLK" (312♥ 88🔁) |
| URI    | 5      | 34     | "$URI bull flag, strong buy" (621♥ 201🔁) |
| NVRI   | 3      | 2      | Low X visibility |
```

Tickers are sorted by rating descending, then alphabetically.

---

## Integration with darvas_scan.py

At the top of `darvas_scan.py`, add:
```python
from x_sentiment import run_sentiment
```

At the end of `_run()`, after saving `phase3_*.txt`, add:
```python
import asyncio
SENTIMENT_OUTPUT_DIR = "/Users/jamesblond/Documents/1-Projects/AI Trade/Breakout Strategy Daily/X Research Phase3 Candidates"
asyncio.run(run_sentiment(out_path, SENTIMENT_OUTPUT_DIR))
```

`x_sentiment.py` exposes:
- `async def run_sentiment(phase3_path: str, output_dir: str)` — for import
- `def main()` — for standalone use; globs the latest phase3 file automatically

---

## Error Handling

- Missing `x_cookies.json`: print a clear setup message and exit gracefully (don't crash the Darvas scan when chained).
- twscrape auth failure: log the error, skip sentiment scan.
- Per-ticker search failure: log the error, record rating as `N/A` in the table, continue.
- No phase3 file found: raise with a clear message.

---

## Dependencies

```
twscrape
```

Install: `pip install twscrape`

No other new dependencies beyond what's already in the project.
