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
