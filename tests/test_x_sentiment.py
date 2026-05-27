import os
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from x_sentiment import (
    find_latest_phase3,
    parse_phase3_file,
    classify_tweet,
    compute_rating,
    build_markdown,
    run_sentiment,
)

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
