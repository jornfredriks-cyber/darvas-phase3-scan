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


def classify_tweet(tweet_text: str) -> str:
    """Classify tweet sentiment as bullish, bearish, or neutral."""
    pass


def compute_rating(bullish_count: int, bearish_count: int, neutral_count: int) -> float:
    """Compute sentiment rating from counts."""
    pass


def build_markdown(ticker: str, rating: float, tweets: list[dict]) -> str:
    """Build markdown report for a ticker."""
    pass


async def run_sentiment():
    """Main async function to run X sentiment scan."""
    pass
