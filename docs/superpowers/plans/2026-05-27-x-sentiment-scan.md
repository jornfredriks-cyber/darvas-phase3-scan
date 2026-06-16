# X Sentiment Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Python script that reads the latest `phase3_*.txt` ticker list, searches X for high-engagement sentiment posts per ticker (last 30 days), and writes a rated Markdown report to an Obsidian folder.

**Architecture:** `x_sentiment.py` is a standalone script with an importable async `run_sentiment()` function. Pure utility functions (parsing, classification, rating, markdown) are tested independently. `darvas_scan.py` imports and calls `run_sentiment` at the end of its `_run()` function.

**Tech Stack:** Python 3.11+, `twscrape` (X/Twitter scraping via cookie auth), `pytest`, `pytest-asyncio`

---

## File Map

| Action | Path |
|--------|------|
| Create | `x_sentiment.py` |
| Create | `x_cookies.json.example` |
| Create | `tests/test_x_sentiment.py` |
| Create | `conftest.py` (pytest path setup) |
| Modify | `darvas_scan.py` |

All paths relative to `/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan/`.

---

## Task 1: Install dependencies and scaffold test infrastructure

**Files:**
- Create: `conftest.py`
- Create: `tests/test_x_sentiment.py`

- [ ] **Step 1: Install dependencies**

```bash
cd "/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"
pip install twscrape pytest pytest-asyncio
```

Expected: packages install without errors.

- [ ] **Step 2: Create conftest.py** at project root so pytest can find `x_sentiment`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
```

- [ ] **Step 3: Create tests/test_x_sentiment.py** with imports only (no tests yet):

```python
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from x_sentiment import (
    find_latest_phase3,
    parse_phase3_file,
    classify_tweet,
    compute_rating,
    build_markdown,
    run_sentiment,
)
```

- [ ] **Step 4: Verify imports resolve** (x_sentiment.py doesn't exist yet — expect ImportError)

```bash
cd "/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"
python -c "import tests.test_x_sentiment" 2>&1 | head -5
```

Expected: `ModuleNotFoundError: No module named 'x_sentiment'` — correct, we haven't written it yet.

- [ ] **Step 5: Commit**

```bash
git init  # only if not already a git repo
git add conftest.py "tests/test_x_sentiment.py"
git commit -m "test: scaffold x_sentiment test file"
```

---

## Task 2: Phase3 file parsing utilities

**Files:**
- Create: `x_sentiment.py` (partial — parsing functions only)
- Modify: `tests/test_x_sentiment.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_x_sentiment.py`:

```python
# ── find_latest_phase3 ────────────────────────────────────────────────────────

def test_find_latest_phase3_returns_most_recent(tmp_path):
    (tmp_path / "phase3_2026-05-25.txt").write_text("AAPL")
    (tmp_path / "phase3_2026-05-27.txt").write_text("MSFT")
    result = find_latest_phase3(str(tmp_path))
    assert result.endswith("phase3_2026-05-27.txt")


def test_find_latest_phase3_raises_when_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_latest_phase3(str(tmp_path))


# ── parse_phase3_file ─────────────────────────────────────────────────────────

def test_parse_phase3_numbered_format(tmp_path):
    p = tmp_path / "phase3_2026-05-27.txt"
    p.write_text("1\tADAM\n2\tASND\n3\tEXEL\n")
    tickers, date_str = parse_phase3_file(str(p))
    assert tickers == ["ADAM", "ASND", "EXEL"]
    assert date_str == "2026-05-27"


def test_parse_phase3_plain_format(tmp_path):
    p = tmp_path / "phase3_2026-05-20.txt"
    p.write_text("SBLK\nURI\n")
    tickers, date_str = parse_phase3_file(str(p))
    assert tickers == ["SBLK", "URI"]
    assert date_str == "2026-05-20"


def test_parse_phase3_skips_blank_lines(tmp_path):
    p = tmp_path / "phase3_2026-05-27.txt"
    p.write_text("1\tADAM\n\n2\tASND\n")
    tickers, _ = parse_phase3_file(str(p))
    assert tickers == ["ADAM", "ASND"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"
python -m pytest tests/test_x_sentiment.py -k "phase3" -v 2>&1 | tail -15
```

Expected: `ERROR` — `x_sentiment` cannot be imported.

- [ ] **Step 3: Create x_sentiment.py** with just the parsing functions:

```python
import asyncio
import glob
import json
import os
import re
from datetime import date, timedelta

import twscrape

SCAN_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = (
    "/Users/jamesblond/Documents/1-Projects/AI Trade"
    "/Breakout Strategy Daily/X Research Phase3 Candidates"
)
COOKIES_PATH = os.path.join(SCAN_DIR, "x_cookies.json")

BULLISH_TERMS = frozenset(
    {"bullish", "strong buy", "loading up", "upgrade", "breakout", "catalyst", "buy"}
)
BEARISH_TERMS = frozenset(
    {"bearish", "dumping", "strong sell", "downgrade", "breakdown", "short"}
)


def find_latest_phase3(folder: str) -> str:
    files = glob.glob(os.path.join(folder, "phase3_*.txt"))
    if not files:
        raise FileNotFoundError(f"No phase3_*.txt found in {folder}")
    return max(files, key=os.path.getmtime)


def parse_phase3_file(path: str) -> tuple[list[str], str]:
    basename = os.path.basename(path)
    m = re.search(r"phase3_(\d{4}-\d{2}-\d{2})\.txt", basename)
    date_str = m.group(1) if m else str(date.today())
    tickers = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            ticker = parts[-1].strip()
            if ticker:
                tickers.append(ticker)
    return tickers, date_str
```

- [ ] **Step 4: Run tests again — expect pass**

```bash
python -m pytest tests/test_x_sentiment.py -k "phase3" -v 2>&1 | tail -15
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add x_sentiment.py "tests/test_x_sentiment.py"
git commit -m "feat: add phase3 file parsing utilities"
```

---

## Task 3: Tweet classification

**Files:**
- Modify: `x_sentiment.py` (add `classify_tweet`)
- Modify: `tests/test_x_sentiment.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_x_sentiment.py`:

```python
# ── classify_tweet ────────────────────────────────────────────────────────────

def test_classify_tweet_bullish():
    assert classify_tweet("$SBLK is very bullish right now") == 1
    assert classify_tweet("Strong buy on $URI catalyst") == 1
    assert classify_tweet("LOADING UP on $ASND before breakout") == 1


def test_classify_tweet_bearish():
    assert classify_tweet("$DVA dumping hard today") == -1
    assert classify_tweet("bearish on this name, short it") == -1
    assert classify_tweet("downgrade — breakdown incoming") == -1


def test_classify_tweet_neutral_no_keywords():
    assert classify_tweet("$AAPL reports earnings next week") == 0


def test_classify_tweet_mixed_is_neutral():
    assert classify_tweet("bullish on $URI but also bearish risk") == 0


def test_classify_tweet_case_insensitive():
    assert classify_tweet("BULLISH on $SBLK") == 1
    assert classify_tweet("BEARISH on $DVA") == -1
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_x_sentiment.py -k "classify" -v 2>&1 | tail -15
```

Expected: `ImportError` — `classify_tweet` not yet defined.

- [ ] **Step 3: Add classify_tweet to x_sentiment.py** after the `parse_phase3_file` function:

```python
def classify_tweet(text: str) -> int:
    lower = text.lower()
    is_bullish = any(term in lower for term in BULLISH_TERMS)
    is_bearish = any(term in lower for term in BEARISH_TERMS)
    if is_bullish and not is_bearish:
        return 1
    if is_bearish and not is_bullish:
        return -1
    return 0
```

- [ ] **Step 4: Run to verify pass**

```bash
python -m pytest tests/test_x_sentiment.py -k "classify" -v 2>&1 | tail -15
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add x_sentiment.py "tests/test_x_sentiment.py"
git commit -m "feat: add tweet keyword classification"
```

---

## Task 4: Rating computation

**Files:**
- Modify: `x_sentiment.py` (add `compute_rating`)
- Modify: `tests/test_x_sentiment.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_x_sentiment.py`:

```python
# ── compute_rating ────────────────────────────────────────────────────────────

def _tweet(text, likes=100, retweets=20):
    return {"text": text, "likes": likes, "retweets": retweets}


def test_compute_rating_low_visibility():
    tweets = [_tweet("bullish $SBLK"), _tweet("buy $SBLK")]
    rating, count, note = compute_rating(tweets)
    assert rating == 3
    assert count == 2
    assert note == "Low X visibility"


def test_compute_rating_strongly_bullish():
    tweets = [_tweet("bullish strong buy catalyst $URI", likes=500)] * 10
    rating, count, note = compute_rating(tweets)
    assert rating == 5
    assert count == 10


def test_compute_rating_strongly_bearish():
    tweets = [_tweet("bearish dumping breakdown $DVA", likes=500)] * 10
    rating, count, note = compute_rating(tweets)
    assert rating == 1


def test_compute_rating_mixed_neutral():
    bullish = [_tweet("bullish $X", likes=100)] * 5
    bearish = [_tweet("bearish $X", likes=100)] * 5
    rating, count, note = compute_rating(bullish + bearish)
    assert rating == 3


def test_compute_rating_key_note_is_highest_engagement():
    low = _tweet("bullish $X", likes=50, retweets=10)
    high = _tweet("Strong buy $X catalyst", likes=800, retweets=200)
    neutral = _tweet("$X quiet", likes=60, retweets=5)
    rating, count, note = compute_rating([low, high, neutral])
    assert "Strong buy $X catalyst" in note
    assert "800♥" in note
    assert "200🔁" in note
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_x_sentiment.py -k "compute_rating" -v 2>&1 | tail -15
```

Expected: `ImportError` — `compute_rating` not yet defined.

- [ ] **Step 3: Add compute_rating to x_sentiment.py** after `classify_tweet`:

```python
def compute_rating(tweets: list[dict]) -> tuple[int, int, str]:
    if len(tweets) < 3:
        return 3, len(tweets), "Low X visibility"

    weighted_score = 0
    total_weight = 0
    for t in tweets:
        classification = classify_tweet(t["text"])
        weighted_score += classification * t["likes"]
        total_weight += t["likes"]

    net = weighted_score / total_weight if total_weight > 0 else 0.0

    if net >= 0.6:
        rating = 5
    elif net >= 0.3:
        rating = 4
    elif net > -0.3:
        rating = 3
    elif net > -0.6:
        rating = 2
    else:
        rating = 1

    best = max(tweets, key=lambda t: t["likes"] + 2 * t["retweets"])
    snippet = best["text"].replace("\n", " ")[:120]
    key_note = f'"{snippet}" ({best["likes"]}♥ {best["retweets"]}🔁)'

    return rating, len(tweets), key_note
```

- [ ] **Step 4: Run to verify pass**

```bash
python -m pytest tests/test_x_sentiment.py -k "compute_rating" -v 2>&1 | tail -15
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add x_sentiment.py "tests/test_x_sentiment.py"
git commit -m "feat: add engagement-weighted rating computation"
```

---

## Task 5: Markdown report generation

**Files:**
- Modify: `x_sentiment.py` (add `build_markdown`)
- Modify: `tests/test_x_sentiment.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_x_sentiment.py`:

```python
# ── build_markdown ────────────────────────────────────────────────────────────

def _results(*items):
    return [{"ticker": t, "rating": r, "tweets": 5, "key_note": "note"} for t, r in items]


def test_build_markdown_contains_frontmatter():
    md = build_markdown(_results(("SBLK", 4)), "2026-05-27", ["SBLK"])
    assert "date: 2026-05-27" in md
    assert "tickers: SBLK" in md


def test_build_markdown_contains_table_header():
    md = build_markdown(_results(("SBLK", 4)), "2026-05-27", ["SBLK"])
    assert "| Ticker | Rating | Tweets | Key Note |" in md


def test_build_markdown_sorted_by_rating_desc_then_alpha():
    results = _results(("AAPL", 3), ("SBLK", 5), ("URI", 5), ("DVA", 1))
    md = build_markdown(results, "2026-05-27", ["AAPL", "SBLK", "URI", "DVA"])
    lines = [l for l in md.splitlines() if l.startswith("|") and "Ticker" not in l and "---" not in l]
    tickers_in_order = [l.split("|")[1].strip() for l in lines]
    assert tickers_in_order == ["SBLK", "URI", "AAPL", "DVA"]


def test_build_markdown_na_for_rating_zero():
    results = [{"ticker": "ERR", "rating": 0, "tweets": 0, "key_note": "Error: timeout"}]
    md = build_markdown(results, "2026-05-27", ["ERR"])
    assert "N/A" in md
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_x_sentiment.py -k "build_markdown" -v 2>&1 | tail -15
```

Expected: `ImportError` — `build_markdown` not yet defined.

- [ ] **Step 3: Add build_markdown to x_sentiment.py** after `compute_rating`:

```python
def build_markdown(results: list[dict], date_str: str, tickers: list[str]) -> str:
    sorted_results = sorted(results, key=lambda r: (-r["rating"], r["ticker"]))
    rows = []
    for r in sorted_results:
        rating_display = str(r["rating"]) if r["rating"] > 0 else "N/A"
        rows.append(
            f"| {r['ticker']:<6} | {rating_display:<6} | {r['tweets']:<6} | {r['key_note']} |"
        )
    table = "\n".join(rows)
    ticker_list = ", ".join(tickers)
    return (
        f"---\n"
        f"date: {date_str}\n"
        f"tickers: {ticker_list}\n"
        f"---\n\n"
        f"# X Sentiment Scan — Phase 3 Candidates ({date_str})\n\n"
        f"> Search: `$TICKER (bullish OR bearish OR \"strong buy\" OR \"loading up\" "
        f"OR dumping OR \"big catalyst\") min_faves:50 min_retweets:10` — last 30 days\n\n"
        f"| Ticker | Rating | Tweets | Key Note |\n"
        f"|--------|--------|--------|----------|\n"
        f"{table}\n"
    )
```

- [ ] **Step 4: Run to verify pass**

```bash
python -m pytest tests/test_x_sentiment.py -k "build_markdown" -v 2>&1 | tail -15
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add x_sentiment.py "tests/test_x_sentiment.py"
git commit -m "feat: add markdown report builder"
```

---

## Task 6: run_sentiment() and main()

**Files:**
- Modify: `x_sentiment.py` (add `run_sentiment`, `main`)
- Modify: `tests/test_x_sentiment.py`

- [ ] **Step 1: Write failing tests** — append to `tests/test_x_sentiment.py`:

```python
# ── run_sentiment ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_sentiment_skips_if_no_cookies(tmp_path, capsys):
    phase3 = tmp_path / "phase3_2026-05-27.txt"
    phase3.write_text("1\tSBLK\n2\tURI\n3\tADAM\n")
    output_dir = str(tmp_path / "output")
    missing_cookies = str(tmp_path / "no_cookies.json")

    await run_sentiment(str(phase3), output_dir, cookies_path=missing_cookies)

    captured = capsys.readouterr()
    assert "Skipped" in captured.out
    assert not os.path.exists(output_dir)


@pytest.mark.asyncio
async def test_run_sentiment_writes_markdown(tmp_path):
    phase3 = tmp_path / "phase3_2026-05-27.txt"
    phase3.write_text("1\tSBLK\n2\tURI\n3\tADAM\n")
    output_dir = str(tmp_path / "output")

    cookies_file = tmp_path / "x_cookies.json"
    cookies_file.write_text(json.dumps({"auth_token": "tok123", "ct0": "ct456"}))

    mock_tweet = MagicMock()
    mock_tweet.rawContent = "bullish $SBLK strong buy catalyst"
    mock_tweet.likeCount = 200
    mock_tweet.retweetCount = 50

    async def mock_search(query, limit=50):
        for _ in range(5):
            yield mock_tweet

    mock_api = MagicMock()
    mock_api.pool.add_account = AsyncMock()
    mock_api.pool.login_all = AsyncMock()
    mock_api.search = mock_search

    with patch("x_sentiment.twscrape.API", return_value=mock_api):
        await run_sentiment(str(phase3), output_dir, cookies_path=str(cookies_file))

    out_file = os.path.join(output_dir, "X_Sentiment_2026-05-27.md")
    assert os.path.exists(out_file)
    content = open(out_file).read()
    assert "date: 2026-05-27" in content
    assert "SBLK" in content
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/test_x_sentiment.py -k "run_sentiment" -v 2>&1 | tail -15
```

Expected: `ImportError` — `run_sentiment` not yet defined.

- [ ] **Step 3: Add run_sentiment and main to x_sentiment.py** after `build_markdown`:

```python
async def run_sentiment(
    phase3_path: str,
    output_dir: str,
    cookies_path: str | None = None,
) -> None:
    _cookies_path = cookies_path or COOKIES_PATH
    if not os.path.exists(_cookies_path):
        print(
            f"\n[x_sentiment] Skipped: x_cookies.json not found at {_cookies_path}\n"
            "  Create it: {\"auth_token\": \"...\", \"ct0\": \"...\"}\n"
            "  (copy from x.com DevTools → Application → Cookies)"
        )
        return

    with open(_cookies_path) as f:
        cookies = json.load(f)

    tickers, date_str = parse_phase3_file(phase3_path)
    since_date = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")

    api = twscrape.API()
    try:
        await api.pool.add_account(
            username="user",
            password="pass",
            email="user@example.com",
            cookies=f"auth_token={cookies['auth_token']}; ct0={cookies['ct0']}",
        )
        await api.pool.login_all()
    except Exception as e:
        print(f"[x_sentiment] Auth error: {e}")
        return

    results = []
    for ticker in tickers:
        query = (
            f"${ticker} (bullish OR bearish OR \"strong buy\" OR \"loading up\" "
            f"OR dumping OR \"big catalyst\") min_faves:50 min_retweets:10 lang:en since:{since_date}"
        )
        tweets = []
        try:
            async for tweet in api.search(query, limit=50):
                tweets.append({
                    "text": tweet.rawContent,
                    "likes": tweet.likeCount,
                    "retweets": tweet.retweetCount,
                })
        except Exception as e:
            print(f"  [{ticker}] search error: {e}")
            results.append({"ticker": ticker, "rating": 0, "tweets": 0, "key_note": f"Error: {e}"})
            await asyncio.sleep(0.5)
            continue

        rating, count, key_note = compute_rating(tweets)
        results.append({"ticker": ticker, "rating": rating, "tweets": count, "key_note": key_note})
        print(f"  [{ticker}] rating={rating} tweets={count}")
        await asyncio.sleep(0.5)

    md = build_markdown(results, date_str, tickers)
    out_path = os.path.join(output_dir, f"X_Sentiment_{date_str}.md")
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w") as f:
        f.write(md)
    print(f"[x_sentiment] Saved → {out_path}")


def main() -> None:
    phase3_path = find_latest_phase3(SCAN_DIR)
    asyncio.run(run_sentiment(phase3_path, OUTPUT_DIR))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/test_x_sentiment.py -v 2>&1 | tail -25
```

Expected: all tests PASSED (the `asyncio` tests need `pytest-asyncio` — if they fail with `PytestUnraisableExceptionWarning`, add `asyncio_mode = "auto"` to a `pytest.ini` or `pyproject.toml`).

If needed, create `pytest.ini` in the project root:
```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 5: Commit**

```bash
git add x_sentiment.py "tests/test_x_sentiment.py"
git commit -m "feat: add run_sentiment async core and main entry point"
```

---

## Task 7: Create x_cookies.json.example

**Files:**
- Create: `x_cookies.json.example`

- [ ] **Step 1: Create the template file**

```json
{
  "auth_token": "PASTE_YOUR_auth_token_COOKIE_VALUE_HERE",
  "ct0": "PASTE_YOUR_ct0_COOKIE_VALUE_HERE"
}
```

Save as `x_cookies.json.example` in the project folder.

How to get these values:
1. Open [https://x.com](https://x.com) and log in
2. Open DevTools (F12 or Cmd+Option+I)
3. Go to Application → Cookies → https://x.com
4. Copy the **Value** column for `auth_token` and `ct0`
5. Rename `x_cookies.json.example` to `x_cookies.json` and paste the values

- [ ] **Step 2: Commit**

```bash
git add x_cookies.json.example
git commit -m "docs: add x_cookies.json setup template"
```

---

## Task 8: Integrate into darvas_scan.py

**Files:**
- Modify: `darvas_scan.py` (lines 1–16 for import, lines 330–338 for the call)

- [ ] **Step 1: Add import** at the top of `darvas_scan.py`, after the existing imports (after line 16):

```python
try:
    from x_sentiment import run_sentiment as _run_sentiment
    import asyncio as _asyncio
    _SENTIMENT_AVAILABLE = True
except ImportError:
    _SENTIMENT_AVAILABLE = False
```

- [ ] **Step 2: Add constant** after the `FETCH_RETRY_DELAY` line (after line 41):

```python
SENTIMENT_OUTPUT_DIR = (
    "/Users/jamesblond/Documents/1-Projects/AI Trade"
    "/Breakout Strategy Daily/X Research Phase3 Candidates"
)
```

- [ ] **Step 3: Add call** inside the `if candidates:` block in `_run()`, after `print(f"Saved → {out_name}")` (after line 337):

```python
        if _SENTIMENT_AVAILABLE:
            print("\nRunning X sentiment scan…")
            _asyncio.run(_run_sentiment(out_path, SENTIMENT_OUTPUT_DIR))
        else:
            print("\n[x_sentiment] Not available — run x_sentiment.py separately.")
```

The full `if candidates:` block after the change looks like:

```python
    if candidates:
        out_name = f"phase3_{date.today()}.txt"
        out_path = os.path.join(folder, out_name)
        with open(out_path, "w") as f:
            f.write("\n".join(candidates))
        print(f"Saved → {out_name}")
        if _SENTIMENT_AVAILABLE:
            print("\nRunning X sentiment scan…")
            _asyncio.run(_run_sentiment(out_path, SENTIMENT_OUTPUT_DIR))
        else:
            print("\n[x_sentiment] Not available — run x_sentiment.py separately.")
    else:
        print("No Phase 3 candidates found.")
```

- [ ] **Step 4: Run full test suite to ensure darvas_scan.py is unaffected**

```bash
python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests still PASSED.

- [ ] **Step 5: Quick smoke test of the import**

```bash
cd "/Users/jamesblond/Documents/1-Projects/AI Trade/Darvas Phase3 Scan"
python -c "import darvas_scan; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 6: Commit**

```bash
git add darvas_scan.py
git commit -m "feat: chain x_sentiment scan after darvas phase3 scan"
```

---

## Done

After Task 8:
- `python x_sentiment.py` runs the sentiment scan standalone
- Running `darvas_scan.py` (or `RUN Darvas Scan.command`) automatically chains the sentiment scan
- Set up `x_cookies.json` once using the `.example` template before first run
