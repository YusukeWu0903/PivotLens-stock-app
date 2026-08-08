"""
src/charts.py
視覺化圖表渲染模組

負責 K 線圖、成交量圖、勝率統計、技術診斷的 Streamlit 渲染。
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def render_kline_chart(
    stock_id: str,
    strategy_name: str,
    stock_dict: dict,
    stock_name_map: dict,
    i18n: dict
) -> None:
    """
    渲染單一股票的 K 線圖、勝率統計、技術診斷
    
    Args:
        stock_id: 股票代號
        strategy_name: 策略名稱
        stock_dict: 全市場資料字典
        stock_name_map: 股票名稱對照表
        i18n: 語言包字典
    """
    from src.config_manager import get_strategy_config
    
    cfg = get_strategy_config(strategy_name)
    timeframe = cfg["timeframe"]
    short_ma = cfg["short_ma"]
    long_ma = cfg["long_ma"]

    df_raw = stock_dict.get(stock_id)
    if df_raw is None:
        return

    # 重新計算該股票在該策略下的指標
    df_selected = process_timeframe_for_chart(df_raw, timeframe, short_ma, long_ma)

    stats, trade_logs_df = calculate_win_rate_for_chart(
        df_selected, short_ma, long_ma, i18n
    )
    latest_close = df_selected["Close"].iloc[-1]
    prev_close = df_selected["Close"].iloc[-2]
    price_change_pct = ((latest_close - prev_close) / prev_close) * 100
    is_price_up = price_change_pct >= 0
    is_vol_low = df_selected["Volume"].iloc[-1] < df_selected["Vol_MA20"].iloc[-1]
    long_ma_val = df_selected["MA_long"].iloc[-1]

    # ========== 勝率統計區 ==========
    col_stat, col_diag = st.columns([1, 1])
    with col_stat:
        st.markdown(f"##### {i18n['win_rate_header']}")
        if stats and "win_rate_5d" in stats:
            m1, m2, m3 = st.columns(3)
            m1.metric(i18n["win_rate_5d"], f"{stats.get('win_rate_5d', 0)}%", f"{stats.get('avg_ret_5d', 0)}%")
            m2.metric(i18n["win_rate_10d"], f"{stats.get('win_rate_10d', 0)}%", f"{stats.get('avg_ret_10d', 0)}%")
            m3.metric(i18n["win_rate_20d"], f"{stats.get('win_rate_20d', 0)}%", f"{stats.get('avg_ret_20d', 0)}%")
            st.caption(i18n["signals_count_msg"].format(count=stats["total_signals"]))
        else:
            st.info(i18n["no_sample_msg"])

    # ========== 技術面診斷區 ==========
    with col_diag:
        st.markdown(f"##### {i18n['diag_header']}")
        if is_price_up and is_vol_low:
            st.success(i18n["diag_bull_up_lowvol"].format(pct=price_change_pct, ma_val=long_ma_val, long_ma=long_ma))
        elif is_price_up:
            st.success(i18n["diag_bull_up_highvol"].format(pct=price_change_pct))
        elif is_vol_low:
            st.info(i18n["diag_bull_down_lowvol"].format(pct=price_change_pct, ma_val=long_ma_val))
        else:
            st.warning(i18n["diag_bull_down_highvol"].format(pct=price_change_pct, ma_val=long_ma_val))

    # ========== 歷史交易明細展開區 ==========
    if trade_logs_df is not None and not trade_logs_df.empty:
        with st.expander(i18n["expander_logs"]):
            st.dataframe(trade_logs_df, width="stretch")

    st.divider()

    # ========== K 線圖繪製 ==========
    df_chart = df_selected.tail(90).reset_index()
    df_chart["Volume_Sheets"] = df_chart["Volume"] // 1000
    df_chart["Prev_Close"] = df_chart["Close"].shift(1).fillna(df_chart["Open"])

    date_strings = df_chart["Date"].dt.strftime("%Y-%m-%d").tolist()
    x_vals = date_strings

    vol_hover_texts = []
    combined_texts = []
    tf_label = "周" if timeframe == "W" else "日"

    for idx, row in df_chart.iterrows():
        vol_hover_texts.append(f"<b>{date_strings[idx]} ({tf_label}K)</b><br>成交量: {row['Volume_Sheets']:,} 張")

        prev_c = row["Prev_Close"]
        
        def get_color_str(val, base):
            if val > base:
                return f"<span style='color:#ef5350;'>{val:.2f} ▲</span>"
            elif val < base:
                return f"<span style='color:#26a69a;'>{val:.2f} ▼</span>"
            else:
                return f"<span style='color:#ffffff;'>{val:.2f}</span>"

        open_html = get_color_str(row["Open"], prev_c)
        high_html = get_color_str(row["High"], prev_c)
        low_html = get_color_str(row["Low"], prev_c)
        close_html = get_color_str(row["Close"], prev_c)

        text = (
            f"<b>{date_strings[idx]} ({tf_label}K)</b><br><br>"
            f"{i18n['chart_open']}: {open_html}<br>"
            f"{i18n['chart_high']}: {high_html}<br>"
            f"{i18n['chart_low']}: {low_html}<br>"
            f"{i18n['chart_close']}: {close_html}<br><br>"
            f"<span style='color:#ffa726;'>{short_ma}{tf_label}MA: {row['MA_short']:.2f}</span><br>"
            f"<span style='color:#42a5f5;'>{long_ma}{tf_label}MA: {row['MA_long']:.2f}</span>"
        )
        combined_texts.append(text)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3]
    )

    # 價格軌跡 (透明線，用於 hover)
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=df_chart["Close"],
            mode="lines",
            line=dict(color="rgba(0,0,0,0)"),
            text=combined_texts,
            hovertemplate="%{text}<extra></extra>",
            showlegend=False,
            hoverinfo="text",
        ),
        row=1,
        col=1,
    )

    # K 線圖
    fig.add_trace(
        go.Candlestick(
            x=x_vals,
            open=df_chart["Open"],
            high=df_chart["High"],
            low=df_chart["Low"],
            close=df_chart["Close"],
            name=f"{tf_label}K線",
            increasing_line_color="#ef5350",
            decreasing_line_color="#26a69a",
            hoverinfo="skip",
        ),
        row=1,
        col=1,
    )

    # 短均線
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=df_chart["MA_short"],
            name=f"{short_ma}{tf_label}MA",
            line=dict(color="orange", width=1.5),
            hoverinfo="skip",
        ),
        row=1,
        col=1,
    )

    # 長均線
    fig.add_trace(
        go.Scatter(
            x=x_vals,
            y=df_chart["MA_long"],
            name=f"{long_ma}{tf_label}MA",
            line=dict(color="#42a5f5", width=1.5),
            hoverinfo="skip",
        ),
        row=1,
        col=1,
    )

    # 成交量柱狀圖
    price_diff = df_chart["Close"].diff().fillna(0)
    vol_colors = ["#ef5350" if diff >= 0 else "#26a69a" for diff in price_diff]
    fig.add_trace(
        go.Bar(
            x=x_vals,
            y=df_chart["Volume_Sheets"],
            name=i18n["chart_vol"],
            marker_color=vol_colors,
            opacity=0.7,
            hoverinfo="text",
            hovertext=vol_hover_texts,
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        hovermode="x",
        hoverdistance=100,
        spikedistance=1000,
        height=500,
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(0,0,0,0)",
        ),
    )

    fig.update_xaxes(type="category", showspikes=True, spikethickness=1, spikemode="across", spikedash="dash")

    step = max(1, len(x_vals) // 10)
    fig.update_xaxes(
        tickmode="array",
        tickvals=x_vals[::step],
        ticktext=x_vals[::step],
        tickangle=-30,
        row=2,
        col=1,
    )

    st.plotly_chart(fig, width="stretch", use_container_width=True)


# ==========================================
# 內部輔助函式 (為了保持介面整潔，放在模組內部)
# ==========================================
def process_timeframe_for_chart(
    df: pd.DataFrame,
    timeframe: str,
    short_ma: int,
    long_ma: int
) -> pd.DataFrame:
    """為圖表處理時間框架與均線 (內部使用)"""
    # 🛡️ 確保索引是 DatetimeIndex，並移除重複日期
    df_work = df.copy()
    if not isinstance(df_work.index, pd.DatetimeIndex):
        if "Date" in df_work.columns:
            df_work = df_work.set_index("Date")
        df_work.index = pd.to_datetime(df_work.index)
    df_work = df_work.sort_index()
    
    # 🛡️ 移除重複日期（保留最後一筆）
    df_work = df_work[~df_work.index.duplicated(keep='last')]
    
    if timeframe == "W":
        df_resampled = df_work.resample("W-FRI").agg({
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }).dropna()
    else:
        df_resampled = df_work

    df_resampled["MA_short"] = df_resampled["Close"].rolling(window=short_ma).mean()
    df_resampled["MA_long"] = df_resampled["Close"].rolling(window=long_ma).mean()
    df_resampled["Vol_MA20"] = df_resampled["Volume"].rolling(window=20).mean()
    return df_resampled


def calculate_win_rate_for_chart(
    df: pd.DataFrame,
    short_ma: int,
    long_ma: int,
    i18n: dict
) -> tuple[dict | None, pd.DataFrame | None]:
    """為圖表計算勝率 (內部使用)"""
    df_calc = df.copy()
    
    # 🛡️ 防禦性修正：確保索引是 DatetimeIndex，避免 get_loc 回傳 slice
    if not isinstance(df_calc.index, pd.DatetimeIndex):
        if "Date" in df_calc.columns:
            df_calc = df_calc.set_index("Date")
        df_calc.index = pd.to_datetime(df_calc.index)
    df_calc = df_calc.sort_index()
    # 🛡️ 移除重複日期（保留最後一筆）
    df_calc = df_calc[~df_calc.index.duplicated(keep='last')]
    
    cross = (
        (df_calc["MA_short"] > df_calc["MA_long"])
        & (df_calc["MA_short"].shift(1) <= df_calc["MA_long"].shift(1))
    )
    order = df_calc["MA_short"] > df_calc["MA_long"]

    recent_cross = cross.rolling(window=15).max() > 0
    price_near = (abs(df_calc["Close"] - df_calc["MA_long"]) / df_calc["MA_long"]) <= 0.04
    signal_mask = recent_cross & order & price_near
    entry_signals = signal_mask & (~signal_mask.shift(1).fillna(False))
    signal_dates = df_calc[entry_signals].index

    results, trade_logs = [], []
    for date in signal_dates:
        loc = df_calc.index.get_loc(date)
        if isinstance(loc, slice):
            loc = loc.start if loc.start is not None else 0
        # 🛡️ 強制轉型為標量：確保 entry_price 非 Series
        entry_price_raw = df_calc.loc[date, "Close"]
        entry_price = float(entry_price_raw.iloc[0] if isinstance(entry_price_raw, pd.Series) else entry_price_raw)
        log_entry = {
            i18n["log_entry_date"]: date.strftime("%Y-%m-%d"),
            i18n["log_entry_price"]: round(entry_price, 2),
        }
        res = {}
        for hold_days in [5, 10, 20]:
            if loc + hold_days < len(df_calc):
                exit_date = df_calc.index[loc + hold_days]
                future_price_raw = df_calc["Close"].iloc[loc + hold_days]
                # 🛡️ 強制轉型為標量：確保 future_price 非 Series
                if isinstance(future_price_raw, pd.Series):
                    future_price_raw = future_price_raw.iloc[0]
                future_price = float(future_price_raw)
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