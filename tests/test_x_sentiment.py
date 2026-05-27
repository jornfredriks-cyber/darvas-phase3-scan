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
    mock_api.pool.add_account_cookies = AsyncMock()
    mock_api.search = mock_search

    with patch("x_sentiment.twscrape.API", return_value=mock_api):
        await run_sentiment(str(phase3), output_dir, cookies_path=str(cookies_file))

    out_file = os.path.join(output_dir, "X_Sentiment_2026-05-27.md")
    assert os.path.exists(out_file)
    content = open(out_file).read()
    assert "date: 2026-05-27" in content
    assert "SBLK" in content
