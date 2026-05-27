import asyncio
import glob
import json
import os
import re
from datetime import date, timedelta

import twscrape

SCAN_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = (
    "/Users/jamesblond/Documents/2-Areas/Finans/Aksjer"
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


def classify_tweet(text: str) -> int:
    lower = text.lower()
    is_bullish = any(term in lower for term in BULLISH_TERMS)
    is_bearish = any(term in lower for term in BEARISH_TERMS)
    if is_bullish and not is_bearish:
        return 1
    if is_bearish and not is_bullish:
        return -1
    return 0


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


async def run_sentiment(
    phase3_path: str,
    output_dir: str,
    cookies_path: str | None = None,
) -> None:
    pass


def main() -> None:
    pass
