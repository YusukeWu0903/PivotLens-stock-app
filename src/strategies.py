"""
src/strategies.py
核心策略運算邏輯模組

純 Pandas 運算，無 Streamlit 依賴，易於單元測試。
"""

import pandas as pd


# ==========================================
# 常數定義
# ==========================================
PATTERN_THRESHOLD_MAP = {
    "貼近均線 (強效支撐)": 0.03,
    "適度回測 (標準進場)": 0.05,
    "允許追高 (強勢動能)": 0.08,
}


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
    cross = (
        (df_calc["MA_short"] > df_calc["MA_long"])
        & (df_calc["MA_short"].shift(1) <= df_calc["MA_long"].shift(1))
    )
    order = df_calc["MA_short"] > df_calc["MA_long"]

    recent_cross = cross.rolling(window=n_days).max() > 0
    price_near = (abs(df_calc["Close"] - df_calc["MA_long"]) / df_calc["MA_long"]) <= threshold
    signal_mask = recent_cross & order & price_near
    entry_signals = signal_mask & (~signal_mask.shift(1).fillna(False))
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
                res[f"win_{hold_days}d"] = 1 if ret > 0 else 0
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
    entry_pattern: str,
    min_volume_sheets: int,
    price_range: str,
    exclude_emerging: bool = True,
    new_tag_days: int = 3,
    strategy_config: dict | None = None,
) -> pd.DataFrame:
    """
    全市場掃描主邏輯 (純運算版，無 Streamlit 依賴)
    
    Args:
        stock_dict: {stock_id: DataFrame} 的字典
        strategy_name: 策略名稱
        entry_pattern: 買點型態
        min_volume_sheets: 最低 20 日均量 (張)
        price_range: "高價股(100元以上)" 或 "低價股(100元以下)"
        exclude_emerging: 是否排除興櫃/創櫃
        new_tag_days: NEW 標籤天數
        strategy_config: 策略設定字典 (若為 None 會從 config_manager 取得)
    
    Returns:
        掃描結果 DataFrame
    """
    if strategy_config is None:
        from src.config_manager import get_strategy_config
        strategy_config = get_strategy_config(strategy_name)

    cfg = strategy_config
    timeframe = cfg["timeframe"]
    short_ma = cfg["short_ma"]
    long_ma = cfg["long_ma"]
    n_days = cfg["n_days"]

    threshold = PATTERN_THRESHOLD_MAP.get(entry_pattern, 0.05)
    results = []

    for stock_id, df_raw in stock_dict.items():
        # 📌 興櫃與創櫃板過濾判斷
        # 注意：Parquet 快取中目前無 Market 欄位，需透過股票代號前綴判斷
        # 興櫃：74xx, 75xx | 創櫃：76xx, 77xx (部分) | 一般上市/上櫃：其他
        stock_id_str = str(stock_id)
        is_emerging = stock_id_str.startswith(("74", "75", "76", "77"))

        if exclude_emerging and is_emerging:
            continue

        lookback_bars = 350 if timeframe == "W" else 120
        df_slice = df_raw.tail(lookback_bars).copy()

        if len(df_slice) < 40:
            continue

        latest_close = df_slice["Close"].iloc[-1]
        raw_avg_vol = (df_slice["Volume"] // 1000).tail(20).mean()

        if raw_avg_vol < min_volume_sheets:
            continue

        if price_range == "高價股(100元以上)" and latest_close < 100:
            continue
        elif price_range == "低價股(100元以下)" and latest_close >= 100:
            continue

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
        is_long_ma_up = current_ma_long > ma_long_prev

        recent_golden = golden_cross.tail(n_days).any()
        ma_bullish = df["MA_short"].iloc[-1] > df["MA_long"].iloc[-1]
        price_near = (abs(df["Close"].iloc[-1] - current_ma_long) / current_ma_long) <= threshold

        is_selected = recent_golden and ma_bullish and price_near and is_long_ma_up

        if is_selected:
            golden_indices = df[golden_cross].index
            is_new_signal = False
            if len(golden_indices) > 0:
                last_cross_date = golden_indices[-1]
                days_since_cross = (df.index[-1] - last_cross_date).days
                if days_since_cross <= (new_tag_days * (7 if timeframe == "W" else 1)):
                    is_new_signal = True

            results.append({
                "Is_New": is_new_signal,
                "股票代號": stock_id,
                "股票名稱": stock_id,  # 會在 UI 層透過 stock_name_map 解析
                "最新收盤價": round(latest_close, 2),
                "20日均量(張)": int(raw_avg_vol),
                "距長均線(%)": round((df["Close"].iloc[-1] - current_ma_long) / current_ma_long * 100, 2),
                "週期形態": "周K" if timeframe == "W" else "日K",
                "資料日期": df.index[-1].strftime("%Y-%m-%d"),
            })

    return pd.DataFrame(results)