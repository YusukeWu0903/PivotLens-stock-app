"""Checks for the filters used by both the live screen and historical statistics."""

import pandas as pd
import pytest

from src.config_manager import I18N
from src.strategies import (
    calculate_screen_win_rate,
    filter_scan_results,
    run_market_scanner,
)


def make_trend(direction: int, future_bars: int = 0, volume: int = 800_000) -> pd.DataFrame:
    closes = [100.0] * 85
    closes += [100.0 + direction * step for step in range(1, 6)]
    closes += [100.0 + direction * 5] * future_bars
    dates = pd.bdate_range("2025-01-01", periods=len(closes))
    prices = pd.Series(closes, index=dates)
    if direction > 0:
        highs, lows = prices + 0.1, prices - 0.9
    else:
        highs, lows = prices + 0.9, prices - 0.1
    volumes = [1_000_000] * 85 + [volume] * 5 + [1_000_000] * future_bars
    return pd.DataFrame({
        "Open": prices, "High": highs, "Low": lows,
        "Close": prices, "Volume": volumes,
    }, index=dates)


@pytest.mark.parametrize(
    "direction,strategy,retreat,momentum",
    [
        (1, "短多 (日K 5MA + 20MA)", "拉回支撐 (量縮潛伏)", "強勢創高 (帶量突破)"),
        (-1, "短空 (日K 5MA + 20MA)", "反彈遇壓 (量縮潛伏)", "弱勢破底 (帶量下殺)"),
    ],
)
def test_volume_rules_and_opposite_directions(direction, strategy, retreat, momentum):
    for volume, retreat_expected, momentum_expected in (
        (800_000, True, False),
        (1_000_000, False, False),
        (1_300_000, False, True),
    ):
        df = make_trend(direction, volume=volume)
        scan = run_market_scanner({"2330": df}, strategy)
        assert len(scan) == 1
        kwargs = {"min_volume_sheets": 0, "price_range": "高價股(100元以上)" if direction > 0 else "低價股(100元以下)", "exclude_emerging": True}
        assert (not filter_scan_results(scan, retreat, **kwargs).empty) == retreat_expected
        assert (not filter_scan_results(scan, momentum, **kwargs).empty) == momentum_expected


@pytest.mark.parametrize(
    "direction,strategy,retreat",
    [
        (1, "短多 (日K 5MA + 20MA)", "拉回支撐 (量縮潛伏)"),
        (-1, "短空 (日K 5MA + 20MA)", "反彈遇壓 (量縮潛伏)"),
    ],
)
def test_historical_win_rate_replays_selected_filters(direction, strategy, retreat):
    df = make_trend(direction, future_bars=10)
    price_range = "高價股(100元以上)" if direction > 0 else "低價股(100元以下)"
    args = (df, "2330", strategy, retreat, 0, price_range, True, I18N["ZH"])
    summary, logs = calculate_screen_win_rate(*args)
    assert summary is not None and summary["total_signals"] >= 1
    assert summary["samples_5d"] >= 1
    assert summary["win_rate_5d"] == 100.0
    assert logs is not None and not logs.empty

    no_match, no_logs = calculate_screen_win_rate(
        df, "2330", strategy, retreat, 100_000, price_range, True, I18N["ZH"]
    )
    assert no_match is None and no_logs is None


def test_weekly_screen_uses_weekly_volume_and_cross():
    weekly_close = [100.0] * 62 + [101.0, 102.0, 103.0]
    dates = pd.bdate_range("2024-01-01", periods=len(weekly_close) * 5)
    closes = pd.Series([price for price in weekly_close for _ in range(5)], index=dates)
    volumes = [1_000_000] * (62 * 5) + [800_000] * (3 * 5)
    df = pd.DataFrame({
        "Open": closes, "High": closes + 0.1, "Low": closes - 0.9,
        "Close": closes, "Volume": volumes,
    }, index=dates)
    scan = run_market_scanner({"2330": df}, "長多 (周K 13MA + 52MA)")
    assert len(scan) == 1
    filtered = filter_scan_results(
        scan, "拉回支撐 (量縮潛伏)", 0, "高價股(100元以上)", True
    )
    assert len(filtered) == 1


def test_weekly_historical_returns_use_weeks():
    weekly_close = [100.0] * 62 + [101.0, 102.0, 103.0] + [103.0] * 6
    dates = pd.bdate_range("2024-01-01", periods=len(weekly_close) * 5)
    closes = pd.Series([price for price in weekly_close for _ in range(5)], index=dates)
    volumes = [1_000_000] * (62 * 5) + [800_000] * (3 * 5) + [1_000_000] * (6 * 5)
    df = pd.DataFrame({
        "Open": closes, "High": closes + 0.1, "Low": closes - 0.9,
        "Close": closes, "Volume": volumes,
    }, index=dates)
    summary, logs = calculate_screen_win_rate(
        df, "2330", "長多 (周K 13MA + 52MA)", "拉回支撐 (量縮潛伏)",
        0, "高價股(100元以上)", True, I18N["ZH"],
    )
    assert summary is not None and summary["samples_5d"] >= 1
    assert "5週後結算日" in logs.columns
