import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from lw_low_scan import is_near_last_week_low

DEFAULTS = dict(proximity_pct=5.0)


def _weekly_df(lows, closes=None, start="2026-06-01"):
    # start="2026-06-01" is a Monday, so periods are clean Mon-Fri business weeks:
    # week 1 = 06-01..06-05, week 2 = 06-08..06-12, etc.
    n = len(lows)
    idx = pd.bdate_range(start=start, periods=n)
    if closes is None:
        closes = [low + 1.0 for low in lows]
    return pd.DataFrame({"low": lows, "close": closes}, index=idx)


# Two full Mon-Fri weeks. Week 2's low is a clean 100 so percentage math is exact.
WEEK1_LOWS = [60, 59, 58, 57, 56]
WEEK2_LOWS = [104, 103, 102, 101, 100]


def _two_week_df(final_close):
    lows   = WEEK1_LOWS + WEEK2_LOWS
    closes = [low + 1.0 for low in lows]
    closes[-1] = final_close
    return _weekly_df(lows, closes)


def test_empty_df_returns_false():
    df = pd.DataFrame({"low": [], "close": []})
    result, low, dist = is_near_last_week_low(df, **DEFAULTS)
    assert result is False and low is None and dist is None


def test_insufficient_history_returns_false():
    # Only one Mon-Fri week of data (5 bars) -> resample produces a single
    # weekly bin, which fails the "at least 2 bins" guard.
    df = _weekly_df([10, 11, 9, 12, 8])
    result, low, dist = is_near_last_week_low(df, **DEFAULTS)
    assert result is False and low is None and dist is None


def test_mid_week_uses_prior_completed_week():
    # Week 1 (full, low=56) + week 2 partial Mon/Tue/Wed only (low=110, never
    # used). Last trading day is Wednesday of week 2, before that week's
    # Friday label -> falls back to week 1's low (56). Close = 56*1.03 = 57.68
    # (3% above week 1's low) should qualify against week 1, not week 2.
    lows   = WEEK1_LOWS + [110, 111, 112]
    closes = [low + 1.0 for low in lows]
    closes[-1] = 56 * 1.03
    df = _weekly_df(lows, closes)
    result, low, dist = is_near_last_week_low(df, **DEFAULTS)
    assert result is True
    assert low == pytest.approx(56.0)
    assert dist == pytest.approx(3.0, abs=0.1)


def test_friday_close_uses_current_now_complete_week():
    # Last trading day is week 2's Friday -> that week is now complete, so
    # week 2's low (100) is used, not week 1's (56). Close = 100*1.02 = 102
    # (2% above week 2's low) should qualify against week 2.
    df = _two_week_df(final_close=100 * 1.02)
    result, low, dist = is_near_last_week_low(df, **DEFAULTS)
    assert result is True
    assert low == pytest.approx(100.0)
    assert dist == pytest.approx(2.0, abs=0.1)


def test_friday_holiday_limitation_falls_back_to_prior_week():
    # Week 2 only has Mon-Thu (Friday was a market holiday, no row for it).
    # Documented accepted limitation: the bin is still labeled with that
    # week's Friday, so the last trading day (Thursday) falls before the
    # bin's Friday label and the week is misclassified as still in progress,
    # falling back to week 1's low (46) even though week 2 actually finished
    # trading. Close = 46.0 (0% from week 1's low) qualifies against week 1;
    # week 2's much lower low (27) would have excluded it if used instead.
    lows   = [50, 49, 48, 47, 46] + [30, 29, 28, 27]
    closes = [low + 1.0 for low in lows]
    closes[-1] = 46.0
    df = _weekly_df(lows, closes)
    result, low, dist = is_near_last_week_low(df, **DEFAULTS)
    assert result is True
    assert low == pytest.approx(46.0)
    assert dist == pytest.approx(0.0, abs=0.1)


def test_close_at_last_week_low_qualifies():
    df = _two_week_df(final_close=100.0)
    result, low, dist = is_near_last_week_low(df, **DEFAULTS)
    assert result is True
    assert dist == pytest.approx(0.0)


def test_close_three_pct_above_qualifies():
    df = _two_week_df(final_close=103.0)
    result, low, dist = is_near_last_week_low(df, **DEFAULTS)
    assert result is True
    assert dist == pytest.approx(3.0)


def test_close_three_pct_below_qualifies():
    df = _two_week_df(final_close=97.0)
    result, low, dist = is_near_last_week_low(df, **DEFAULTS)
    assert result is True
    assert dist == pytest.approx(-3.0)


def test_close_at_positive_boundary_qualifies():
    # Exactly +5% — inclusive boundary.
    df = _two_week_df(final_close=105.0)
    result, low, dist = is_near_last_week_low(df, **DEFAULTS)
    assert result is True
    assert dist == pytest.approx(5.0)


def test_close_at_negative_boundary_qualifies():
    # Exactly -5% — inclusive boundary.
    df = _two_week_df(final_close=95.0)
    result, low, dist = is_near_last_week_low(df, **DEFAULTS)
    assert result is True
    assert dist == pytest.approx(-5.0)


def test_close_just_outside_positive_boundary_excluded():
    df = _two_week_df(final_close=105.01)
    result, low, dist = is_near_last_week_low(df, **DEFAULTS)
    assert result is False and low is None and dist is None
