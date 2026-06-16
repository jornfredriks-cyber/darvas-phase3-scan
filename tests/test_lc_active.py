import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import pytest
from lc_scan import is_lc_active

DEFAULTS = dict(
    min_bars_lc=5,
    lookback_lc=200,
    bars_back=300,
    left_bars=2,
    right_bars=2,
    allow_equal_highs=True,
    replace_active_line=True,
    replace_only_higher=False,
    pivot_src="high",
)

def _df(highs, lows=None, closes=None):
    n = len(highs)
    if lows is None:
        lows = [h - 1.0 for h in highs]
    if closes is None:
        closes = [h - 0.5 for h in highs]
    return pd.DataFrame({"high": highs, "low": lows, "close": closes})


def test_empty_df_returns_false():
    df = pd.DataFrame({"high": [], "low": [], "close": []})
    result, price, age = is_lc_active(df, **DEFAULTS)
    assert result is False and price is None and age is None


def test_active_line_detected():
    # Pivot high = 15 at bar 4, confirmed at bar 6 (right_bars=2).
    # Age at bar 9 = 9-4 = 5 = min_bars_lc → first bar it goes active.
    # Closes are all 0.5 below highs so never above pivot 15.
    highs  = [10, 11, 12, 13, 15, 14, 13, 12, 12, 12]
    df     = _df(highs)
    result, price, age = is_lc_active(df, **DEFAULTS)
    assert result is True
    assert price == pytest.approx(15.0)
    assert age == 5


def test_forming_line_not_active():
    # Same pivot at bar 4, data ends at bar 7 → age = 3 < min_bars_lc=5.
    highs = [10, 11, 12, 13, 15, 14, 13, 12]
    result, price, age = is_lc_active(_df(highs), **DEFAULTS)
    assert result is False


def test_breakout_deletes_line():
    # Pivot = 15 at bar 4, active by bar 9. Close > 15 at bar 10 → breakout.
    highs  = [10, 11, 12, 13, 15, 14, 13, 12, 12, 12, 16, 15]
    closes = [h - 0.5 for h in highs]
    closes[10] = 15.5   # close above pivot → line deleted
    lows   = [h - 1.0 for h in highs]
    result, price, age = is_lc_active(
        pd.DataFrame({"high": highs, "low": lows, "close": closes}), **DEFAULTS
    )
    assert result is False


def test_line_expires_past_lookback():
    # Pivot = 15 at bar 4. 260 bars of mostly flat price.
    # Dynamic lookback shrinks to ~20 in flat market → line expires well before bar 259.
    n = 260
    highs = [10.0] * n
    highs[2], highs[3], highs[4] = 13.0, 14.0, 15.0
    highs[5], highs[6]           = 13.0, 12.0
    result, price, age = is_lc_active(_df(highs), **DEFAULTS)
    assert result is False


def test_forming_line_not_replaced_by_new_pivot():
    # First pivot = 15 at bar 4, confirmed bar 6, still forming (age=4 < 5 at bar 8).
    # canReplace is False while first line is forming → original line stays.
    # Data ends at bar 8: age = 4 < 5 → forming, result False.
    highs = [10, 11, 12, 13, 15, 14, 13, 12, 11]
    result, price, age = is_lc_active(_df(highs), **DEFAULTS)
    assert result is False


def test_replace_only_higher_blocks_lower_pivot():
    # First pivot = 20 at bar 4, active by bar 9.
    # Second pivot = 18 at bar 10 (lower), confirmed bar 12.
    # replace_only_higher=True: new pivot 18 < 20 → no replacement.
    highs = [10,11,12,13, 20, 19,18,17,16,16, 18,17,16, 16,16,16]
    result, price, age = is_lc_active(
        _df(highs), **{**DEFAULTS, "replace_only_higher": True}
    )
    assert result is True
    assert price == pytest.approx(20.0)


def test_allow_equal_highs_false_rejects_plateau():
    # Plateau at bars 3,4,5 all high=15 — not a strict pivot high.
    highs = [10, 12, 13, 15, 15, 15, 14, 13, 12, 12, 12, 12]
    result, price, age = is_lc_active(
        _df(highs), **{**DEFAULTS, "allow_equal_highs": False}
    )
    assert result is False
