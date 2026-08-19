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
# 買點/賣點型態區間映射：(min_thresh, max_thresh) 互斥區間
# 💡 當 max_thresh >= 0.10 時，系統將自動啟動「引擎二：動能追擊」
# ==========================================
PATTERN_THRESHOLD_MAP = {
    # 📈 多方選項
    "貼近均線 (量縮防守)": (0.00, 0.03),     # 引擎一
    "適度回測 (量縮洗盤)": (0.03, 0.08),     # 引擎一 (容忍稍微深一點的回測)
    "強勢創高 (帶量突破)": (0.10, 99.0),     # 引擎二 (解鎖乖離率上限)
    
    # 📉 空方選項
    "貼近均線 (量縮遇壓)": (0.00, 0.03),     # 引擎一
    "適度反彈 (量縮測壓)": (0.03, 0.08),     # 引擎一
    "弱勢破底 (帶量下殺)": (0.10, 99.0),     # 引擎二 (解鎖乖離率上限)
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

        # 📌 預先計算雙引擎所需的所有布林/數值指標 (不過濾，全保留)
        if not is_short_strategy:
            recent_cross_signal = golden_cross.tail(n_days).any()
            ma_alignment = df["MA_short"].iloc[-1] > df["MA_long"].iloc[-1]
            ma_trend = current_ma_long > ma_long_prev
            
            bias_rate = (close_price - current_ma_long) / current_ma_long
            support_holds = bias_rate >= -0.01
            
            recent_high = df["High"].tail(20).max()
            momentum_breakout = (close_price >= recent_high * 0.97)
        else:
            recent_cross_signal = death_cross.tail(n_days).any()
            ma_alignment = df["MA_short"].iloc[-1] < df["MA_long"].iloc[-1]
            ma_trend = current_ma_long < ma_long_prev
            
            bias_rate = (current_ma_long - close_price) / current_ma_long
            support_holds = bias_rate >= -0.01
            
            recent_low = df["Low"].tail(20).min()
            momentum_breakout = (close_price <= recent_low * 1.03)

        # 基礎門檻：連訊號或趨勢都沒有的，直接淘汰以省記憶體
        if not (recent_cross_signal and ma_alignment and ma_trend):
            continue

        vol_shrink = current_vol <= (vol_ma20 * 1.5)
        vol_surge = current_vol >= (vol_ma20 * 0.8)

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