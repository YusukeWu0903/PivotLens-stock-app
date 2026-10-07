"""
src/strategies.py
核心策略運算邏輯模組

純 Pandas 運算，無 Streamlit 依賴，易於單元測試。
"""

import os
import pandas as pd


# ==========================================
# 興櫃股票清單快取（離線讀取，零 API 成本）
# ==========================================
_EMERGING_STOCKS_CACHE = None


def _load_emerging_stocks() -> set:
    """讀取本地 emerging_stocks.txt 中的興櫃股票代號"""
    global _EMERGING_STOCKS_CACHE
    if _EMERGING_STOCKS_CACHE is not None:
        return _EMERGING_STOCKS_CACHE

    file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "emerging_stocks.txt")
    try:
        with open(file_path, "r") as f:
            _EMERGING_STOCKS_CACHE = set(f.read().splitlines())
    except FileNotFoundError:
        print("⚠️ 找不到 emerging_stocks.txt，興櫃過濾可能不精準。")
        _EMERGING_STOCKS_CACHE = set()
    return _EMERGING_STOCKS_CACHE


def is_emerging_stock(stock_id: str) -> bool:
    """
    判斷是否為興櫃/創櫃股。
    優先使用本地 emerging_stocks.txt 清單，檔案遺失時退回代號前綴備用邏輯。
    """
    emerging_set = _load_emerging_stocks()
    if str(stock_id) in emerging_set:
        return True
    # 容錯備用：若清單遺失，退回最基本的防護（僅過濾 74, 75）
    return str(stock_id).startswith(("74", "75"))


# ==========================================
# 量價門檻與畫面篩選共用規則
# ==========================================
VOLUME_SHRINK_RATIO = 1.0
VOLUME_SURGE_RATIO = 1.2


def filter_scan_results(
    scan_df: pd.DataFrame,
    entry_pattern: str,
    min_volume_sheets: int,
    price_range: str,
    exclude_emerging: bool,
) -> pd.DataFrame:
    """Apply the same visible filters to today's scan and historical signals."""
    if scan_df.empty:
        return scan_df.copy()

    filtered = scan_df[scan_df["20日均量(張)"] >= min_volume_sheets]
    if price_range == "高價股(100元以上)":
        filtered = filtered[filtered["最新收盤價"] >= 100]
    elif price_range == "低價股(100元以下)":
        filtered = filtered[filtered["最新收盤價"] < 100]
    else:
        raise ValueError(f"未知的股價區間: {price_range}")

    if exclude_emerging:
        filtered = filtered[~filtered["Is_Emerging"]]

    if "強勢創高" in entry_pattern or "弱勢破底" in entry_pattern:
        return filtered[
            filtered["Support_Holds"]
            & filtered["Momentum_Breakout"]
            & filtered["Vol_Surge"]
        ].copy()
    if "拉回支撐" in entry_pattern or "反彈遇壓" in entry_pattern:
        return filtered[
            filtered["Support_Holds"]
            & filtered["Vol_Shrink"]
            & filtered["Bias_Rate"].between(0.0, 0.08)
        ].copy()
    raise ValueError(f"未知的買賣點型態: {entry_pattern}")


# ==========================================
# 核心運算函式
# ==========================================
def process_timeframe_and_ma(
    df: pd.DataFrame,
    timeframe: str,
    short_ma: int,
    long_ma: int
) -> pd.DataFrame:
    """
    根據指定週期進行重採樣與均線計算

    Args:
        df: 原始日線資料 (需包含 Date index, Open, High, Low, Close, Volume)
        timeframe: "D" (日線) 或 "W" (周線)
        short_ma: 短均線週期
        long_ma: 長均線週期

    Returns:
        處理後的 DataFrame (含 MA_short, MA_long, Vol_MA20)
    """
    if timeframe == "W":
        df_resampled = df.resample("W-FRI").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).dropna()
    else:
        df_resampled = df.copy()

    df_resampled["MA_short"] = df_resampled["Close"].rolling(window=short_ma).mean()
    df_resampled["MA_long"] = df_resampled["Close"].rolling(window=long_ma).mean()
    df_resampled["Vol_MA20"] = df_resampled["Volume"].rolling(window=20).mean()
    return df_resampled


def calculate_historical_win_rate(
    df: pd.DataFrame,
    short_ma: int,
    long_ma: int,
    signal_type: str = "多方",
    n_days: int = 15,
    threshold: float = 0.04,
    i18n: dict | None = None
) -> tuple[dict | None, pd.DataFrame | None]:
    """
    計算歷史勝率與交易明細

    Args:
        df: 已計算好均線的 DataFrame
        short_ma: 短均線週期
        long_ma: 長均線週期
        signal_type: "多方" 或 "空方"
        n_days: 近期交叉天數窗口
        threshold: 均線容錯極限 (%)
        i18n: 語言包字典 (用於日誌欄位名稱)

    Returns:
        (summary_dict, trade_logs_df) 或 (None, None) 若無樣本
    """
    df_calc = df.copy()

    # 根據 signal_type 決定交叉方向、排列條件與勝率判定
    if signal_type == "空方":
        # 空方：死叉 + 空頭排列 (短均線 < 長均線)
        cross = (
            (df_calc["MA_short"] < df_calc["MA_long"])
            & (df_calc["MA_short"].shift(1) >= df_calc["MA_long"].shift(1))
        )
        order = df_calc["MA_short"] < df_calc["MA_long"]
        win_condition = lambda ret: ret < 0  # 做空獲利：價格下跌算贏
    else:
        # 多方：金叉 + 多頭排列 (短均線 > 長均線)
        cross = (
            (df_calc["MA_short"] > df_calc["MA_long"])
            & (df_calc["MA_short"].shift(1) <= df_calc["MA_long"].shift(1))
        )
        order = df_calc["MA_short"] > df_calc["MA_long"]
        win_condition = lambda ret: ret > 0  # 做多獲利：價格上漲算贏

    recent_cross = cross.rolling(window=n_days).max() > 0
    price_near = (abs(df_calc["Close"] - df_calc["MA_long"]) / df_calc["MA_long"]) <= threshold
    signal_mask = recent_cross & order & price_near
    entry_signals = signal_mask & (~signal_mask.shift(1, fill_value=False))
    signal_dates = df_calc[entry_signals].index

    if i18n is None:
        i18n = {
            "log_entry_date": "訊號觸發(進場)日",
            "log_entry_price": "進場價格",
            "log_exit_date": "{days}日後結算日",
            "log_ret": "{days}日報酬(%)",
        }

    results, trade_logs = [], []
    for date in signal_dates:
        loc = df_calc.index.get_loc(date)
        entry_price = df_calc.loc[date, "Close"]
        log_entry = {
            i18n["log_entry_date"]: date.strftime("%Y-%m-%d"),
            i18n["log_entry_price"]: round(entry_price, 2),
        }
        res = {}
        for hold_days in [5, 10, 20]:
            if loc + hold_days < len(df_calc):
                exit_date = df_calc.index[loc + hold_days]
                future_price = df_calc["Close"].iloc[loc + hold_days]
                ret = (future_price - entry_price) / entry_price
                res[f"ret_{hold_days}d"] = ret
                res[f"win_{hold_days}d"] = 1 if win_condition(ret) else 0
                log_entry[i18n["log_exit_date"].format(days=hold_days)] = exit_date.strftime("%Y-%m-%d")
                log_entry[i18n["log_ret"].format(days=hold_days)] = f"{round(ret * 100, 2)}%"
        if res:
            results.append(res)
            trade_logs.append(log_entry)

    if not results:
        return None, None

    df_res, df_logs = pd.DataFrame(results), pd.DataFrame(trade_logs)
    summary = {"total_signals": len(df_res)}
    for hold_days in [5, 10, 20]:
        if f"win_{hold_days}d" in df_res.columns:
            summary[f"win_rate_{hold_days}d"] = round(df_res[f"win_{hold_days}d"].mean() * 100, 1)
            summary[f"avg_ret_{hold_days}d"] = round(df_res[f"ret_{hold_days}d"].mean() * 100, 2)
    return summary, df_logs


def run_market_scanner(
    stock_dict: dict,
    strategy_name: str,
    strategy_config: dict | None = None,
) -> pd.DataFrame:
    """
    全市場掃描主邏輯 (極速預算版：只算全市場數據，不過濾 UI 條件)
    """
    if strategy_config is None:
        from src.config_manager import get_strategy_config
        strategy_config = get_strategy_config(strategy_name)

    cfg = strategy_config
    timeframe = cfg["timeframe"]
    short_ma = cfg["short_ma"]
    long_ma = cfg["long_ma"]
    n_days = cfg["n_days"]

    results = []
    is_short_strategy = "空" in strategy_name or "死" in strategy_name

    for stock_id, df_raw in stock_dict.items():
        # 🚫 排除非 4 位數字代號 (指數、ETF、Food食品指數等非個股)
        if not (str(stock_id).isdigit() and len(str(stock_id)) == 4):
            continue

        lookback_bars = 350 if timeframe == "W" else 120
        df_slice = df_raw.tail(lookback_bars).copy()

        if len(df_slice) < 40:
            continue

        latest_close = df_slice["Close"].iloc[-1]
        raw_avg_vol = (df_slice["Volume"] // 1000).tail(20).mean()

        df = process_timeframe_and_ma(df_slice, timeframe, short_ma, long_ma)
        if len(df) < (long_ma + 5):
            continue

        golden_cross = (
            (df["MA_short"] > df["MA_long"])
            & (df["MA_short"].shift(1) <= df["MA_long"].shift(1))
        )
        death_cross = (
            (df["MA_short"] < df["MA_long"])
            & (df["MA_short"].shift(1) >= df["MA_long"].shift(1))
        )

        entangled_crosses = (golden_cross | death_cross).tail(20).sum()
        if entangled_crosses >= 3:
            continue

        current_ma_long = df["MA_long"].iloc[-1]
        ma_long_prev = df["MA_long"].iloc[-4] if len(df) >= 4 else current_ma_long

        if pd.isna(current_ma_long) or current_ma_long == 0:
            continue

        close_price = df["Close"].iloc[-1]
        current_vol = df["Volume"].iloc[-1]
        vol_ma20 = df["Volume"].rolling(20).mean().iloc[-1]

        # 📌 計算每一根 K 棒距離最新資料日期的真實日曆天數 (解決周K會抓到20周的問題)
        days_diff = (df.index[-1] - df.index).days

        # ==========================================
        # 📈 雙引擎指標計算
        # ==========================================
        if not is_short_strategy:
            # 只要交叉發生在距離今天 n_days (例如 20 天) 以內，即算有效訊號
            recent_cross_signal = (golden_cross & (days_diff <= n_days)).any()
            ma_alignment = df["MA_short"].iloc[-1] > df["MA_long"].iloc[-1]
            ma_trend = current_ma_long > ma_long_prev

            bias_rate = (close_price - current_ma_long) / current_ma_long
            support_holds = bias_rate >= -0.01  # 支撐不破

            # 1. 抓取「昨天以前」近 20 日的最高價 (排除今天)
            prev_high_20 = df["High"].iloc[:-1].tail(20).max()

            # 2. 實質突破：今日收盤價必須「大於等於」前 20 日最高價 (無折扣)
            is_real_breakout = close_price >= prev_high_20

            # 3. K 棒實體強度：收盤價需位於今日高低振幅的上半部 60% 以上 (避免長上影線)
            day_range = df["High"].iloc[-1] - df["Low"].iloc[-1]
            is_strong_close = (close_price - df["Low"].iloc[-1]) >= (day_range * 0.6) if day_range > 0 else True

            momentum_breakout = is_real_breakout and is_strong_close

        else:
            # ==========================================
            # 📉 做空破底邏輯
            # ==========================================
            recent_cross_signal = (death_cross & (days_diff <= n_days)).any()
            ma_alignment = df["MA_short"].iloc[-1] < df["MA_long"].iloc[-1]
            ma_trend = current_ma_long < ma_long_prev

            bias_rate = (current_ma_long - close_price) / current_ma_long
            support_holds = bias_rate >= -0.01  # 壓力不破

            # 抓取「昨天以前」近 20 日的最低價
            prev_low_20 = df["Low"].iloc[:-1].tail(20).min()

            # 實質跌破：收盤價小於等於前 20 日最低價
            is_real_breakdown = close_price <= prev_low_20

            # K 棒收在低點附近 (收在振幅下半部 40% 以下)
            day_range = df["High"].iloc[-1] - df["Low"].iloc[-1]
            is_weak_close = (close_price - df["Low"].iloc[-1]) <= (day_range * 0.4) if day_range > 0 else True

            momentum_breakout = is_real_breakdown and is_weak_close

        # 基礎門檻：連訊號或趨勢都沒有的，直接淘汰以省記憶體
        if not (recent_cross_signal and ma_alignment and ma_trend):
            continue

        vol_shrink = current_vol < (vol_ma20 * VOLUME_SHRINK_RATIO)
        vol_surge = current_vol >= (vol_ma20 * VOLUME_SURGE_RATIO)

        # 判定是否為 3 天內新訊號
        cross_mask = death_cross if is_short_strategy else golden_cross
        cross_indices = df[cross_mask].index
        is_new_signal = False
        if len(cross_indices) > 0:
            last_cross_date = cross_indices[-1]
            days_since_cross = (df.index[-1] - last_cross_date).days
            if days_since_cross <= (3 * (7 if timeframe == "W" else 1)):
                is_new_signal = True

        results.append({
            "股票代號": stock_id,
            "股票名稱": stock_id,
            "最新收盤價": round(close_price, 2),
            "20日均量(張)": int(raw_avg_vol),
            "距長均線(%)": round(bias_rate * 100, 2),
            "Bias_Rate": bias_rate,
            "Support_Holds": support_holds,
            "Momentum_Breakout": momentum_breakout,
            "Vol_Shrink": vol_shrink,
            "Vol_Surge": vol_surge,
            "Is_New": is_new_signal,
            "Is_Emerging": is_emerging_stock(str(stock_id)),
            "週期形態": "周K" if timeframe == "W" else "日K",
            "資料日期": df.index[-1].strftime("%Y-%m-%d"),
        })

    return pd.DataFrame(results)


def calculate_screen_win_rate(
    df_raw: pd.DataFrame,
    stock_id: str,
    strategy_name: str,
    entry_pattern: str,
    min_volume_sheets: int,
    price_range: str,
    exclude_emerging: bool,
    i18n: dict,
) -> tuple[dict | None, pd.DataFrame | None]:
    """Replay the selected screen at each historical close over the last year.

    Consecutive matching bars form one entry. Returns are measured after 5, 10,
    and 20 trading bars for daily strategies or completed weekly bars for weekly
    strategies. An entry contributes only to horizons with a known exit price.
    """
    from src.config_manager import get_strategy_config

    cfg = get_strategy_config(strategy_name)
    daily = df_raw.copy()
    if not isinstance(daily.index, pd.DatetimeIndex):
        daily.index = pd.to_datetime(daily.index)
    daily = daily.sort_index()
    daily = daily[~daily.index.duplicated(keep="last")]
    if daily.empty:
        return None, None

    if cfg["timeframe"] == "W":
        candidate_dates = daily.groupby(pd.Grouper(freq="W-FRI")).tail(1).index
        unit = "週"
    else:
        candidate_dates = daily.index
        unit = "日"

    cutoff = daily.index[-1] - pd.Timedelta(days=365)
    first_recent = candidate_dates.searchsorted(cutoff)
    if first_recent == len(candidate_dates):
        return None, None

    # Replay one bar before the window so an existing matching run is not
    # incorrectly counted as a new entry at the one-year boundary.
    replay_start = max(0, first_recent - 1)
    previous_match = False
    entries = []
    for candidate_index in range(replay_start, len(candidate_dates)):
        date = candidate_dates[candidate_index]
        daily_position = daily.index.get_loc(date)
        snapshot = run_market_scanner(
            {str(stock_id): daily.iloc[:daily_position + 1]}, strategy_name
        )
        match = not filter_scan_results(
            snapshot, entry_pattern, min_volume_sheets, price_range,
            exclude_emerging,
        ).empty
        if candidate_index >= first_recent and match and not previous_match:
            entries.append(candidate_index)
        previous_match = match

    if not entries:
        return None, None

    closes = daily.loc[candidate_dates, "Close"]
    is_short = "空" in strategy_name or "死" in strategy_name
    summary = {"total_signals": len(entries)}
    logs = []
    horizon_results = {5: [], 10: [], 20: []}
    for entry_index in entries:
        entry_date = candidate_dates[entry_index]
        entry_price = float(closes.iloc[entry_index])
        log = {
            i18n["log_entry_date"]: entry_date.strftime("%Y-%m-%d"),
            i18n["log_entry_price"]: round(entry_price, 2),
        }
        for hold_bars in horizon_results:
            exit_index = entry_index + hold_bars
            if exit_index >= len(candidate_dates):
                continue
            exit_price = float(closes.iloc[exit_index])
            ret = (exit_price - entry_price) / entry_price
            if is_short:
                ret = -ret
            horizon_results[hold_bars].append(ret)
            log[f"{hold_bars}{unit}後結算日"] = candidate_dates[exit_index].strftime("%Y-%m-%d")
            log[f"{hold_bars}{unit}報酬(%)"] = f"{ret * 100:.2f}%"
        logs.append(log)

    for hold_bars, returns in horizon_results.items():
        summary[f"samples_{hold_bars}d"] = len(returns)
        if returns:
            summary[f"win_rate_{hold_bars}d"] = round(
                sum(ret > 0 for ret in returns) / len(returns) * 100, 1
            )
            summary[f"avg_ret_{hold_bars}d"] = round(
                sum(returns) / len(returns) * 100, 2
            )
    return summary, pd.DataFrame(logs)
