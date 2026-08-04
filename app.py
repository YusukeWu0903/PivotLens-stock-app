import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from config import I18N, get_stock_name_map

t = I18N["ZH"]
st.set_page_config(page_title=t["page_title"], page_icon="📈", layout="wide")
st.title(t["app_title"])
st.caption(t["app_subtitle"])

# ==========================================
# 1. 核心資料載入與名稱對照
# ==========================================
@st.cache_data
def load_market_data():
    try:
        df = pd.read_parquet("taiwan_market_cache.parquet")
        df['Date'] = pd.to_datetime(df['Date'])
        return df
    except Exception as e:
        st.error(f"❌ 無法讀取本地快取檔，請確認 taiwan_market_cache.parquet 是否存在。錯誤: {e}")
        return pd.DataFrame()

df_all = load_market_data()
stock_name_map = get_stock_name_map()

def get_stock_name(stock_id):
    return stock_name_map.get(str(stock_id), f"{stock_id}")

def fetch_stock_data_from_cache(stock_id):
    df_single = df_all[df_all['Stock_ID'] == stock_id].copy()
    if df_single.empty:
        return None
    df_single = df_single.set_index('Date').sort_index()
    return df_single

# ==========================================
# 2. 技術面計算與圖表/診斷邏輯
# ==========================================
def calculate_moving_averages(df, short_window, long_window):
    df['MA_short'] = df['Close'].rolling(window=short_window).mean()
    df['MA_long'] = df['Close'].rolling(window=long_window).mean()
    df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()
    return df

@st.cache_data
def run_market_scanner(_df_all, short_ma, long_ma, n_days, threshold, min_volume_sheets, min_price):
    results = []
    stock_universe = _df_all['Stock_ID'].unique()
    
    for stock_id in stock_universe:
        df = fetch_stock_data_from_cache(stock_id)
        if df is None or len(df) < (long_ma + 5):
            continue
            
        latest_close = df['Close'].iloc[-1]
        # 新程式碼（正確：全面無條件捨去成張數）
        df['Volume_Sheets'] = df['Volume'] // 1000
        raw_avg_vol = df['Volume_Sheets'].tail(20).mean()
        avg_vol_20d = raw_avg_vol
            
        if avg_vol_20d < min_volume_sheets or latest_close < min_price:
            continue
            
        df = calculate_moving_averages(df, short_window=short_ma, long_window=long_ma)
        
        # 多方金叉判定
        golden_cross = (df['MA_short'] > df['MA_long']) & (df['MA_short'].shift(1) <= df['MA_long'].shift(1))
        recent_golden = golden_cross.tail(n_days).any()
        ma_bullish = df['MA_short'].iloc[-1] > df['MA_long'].iloc[-1]
        current_ma_long = df['MA_long'].iloc[-1]
        price_near = (abs(latest_close - current_ma_long) / current_ma_long) <= threshold
        is_bullish = recent_golden and ma_bullish and price_near

        # 空方死叉判定
        death_cross = (df['MA_short'] < df['MA_long']) & (df['MA_short'].shift(1) >= df['MA_long'].shift(1))
        recent_death = death_cross.tail(n_days).any()
        ma_bearish = df['MA_short'].iloc[-1] < df['MA_long'].iloc[-1]
        is_bearish = recent_death and ma_bearish and price_near

        if is_bullish or is_bearish:
            results.append({
                "股票代號": stock_id,
                "股票名稱": get_stock_name(stock_id),
                "最新收盤價": round(latest_close, 2),
                "20日均量(張)": int(avg_vol_20d),
                "距長均線(%)": round((latest_close - current_ma_long) / current_ma_long * 100, 2),
                "訊號類型": "多方" if is_bullish else "空方",
                "資料日期": df.index[-1].strftime('%Y-%m-%d')
            })
            
    return pd.DataFrame(results)

def calculate_historical_win_rate(df, short_ma, long_ma, signal_type, n_days=15, threshold=0.04):
    df_calc = df.copy()
    cross = (df_calc['MA_short'] > df_calc['MA_long']) & (df_calc['MA_short'].shift(1) <= df_calc['MA_long'].shift(1)) if signal_type == "多方" else (df_calc['MA_short'] < df_calc['MA_long']) & (df_calc['MA_short'].shift(1) >= df_calc['MA_long'].shift(1))
    order = df_calc['MA_short'] > df_calc['MA_long'] if signal_type == "多方" else df_calc['MA_short'] < df_calc['MA_long']
    
    recent_cross = cross.rolling(window=n_days).max() > 0
    price_near = (abs(df_calc['Close'] - df_calc['MA_long']) / df_calc['MA_long']) <= threshold
    signal_mask = recent_cross & order & price_near
    entry_signals = signal_mask & (~signal_mask.shift(1).fillna(False))
    signal_dates = df_calc[entry_signals].index
    
    results, trade_logs = [], []
    for date in signal_dates:
        loc = df_calc.index.get_loc(date)
        entry_price = df_calc.loc[date, 'Close']
        log_entry = {t["log_entry_date"]: date.strftime('%Y-%m-%d'), t["log_entry_price"]: round(entry_price, 2)}
        res = {}
        for hold_days in [5, 10, 20]:
            if loc + hold_days < len(df_calc):
                exit_date = df_calc.index[loc + hold_days]
                future_price = df_calc['Close'].iloc[loc + hold_days]
                ret = (future_price - entry_price) / entry_price if signal_type == "多方" else (entry_price - future_price) / entry_price
                res[f'ret_{hold_days}d'] = ret
                res[f'win_{hold_days}d'] = 1 if ret > 0 else 0
                log_entry[t["log_exit_date"].format(days=hold_days)] = exit_date.strftime('%Y-%m-%d')
                log_entry[t["log_ret"].format(days=hold_days)] = f"{round(ret * 100, 2)}%"
        if res:
            results.append(res)
            trade_logs.append(log_entry)
            
    if not results:
        return None, None
        
    df_res, df_logs = pd.DataFrame(results), pd.DataFrame(trade_logs)
    summary = {"total_signals": len(df_res)}
    for hold_days in [5, 10, 20]:
        if f'win_{hold_days}d' in df_res.columns:
            summary[f'win_rate_{hold_days}d'] = round(df_res[f'win_{hold_days}d'].mean() * 100, 1)
            summary[f'avg_ret_{hold_days}d'] = round(df_res[f'ret_{hold_days}d'].mean() * 100, 2)
    return summary, df_logs

def render_kline_chart(stock_id, short_ma, long_ma, signal_type):
    df_selected = fetch_stock_data_from_cache(stock_id)
    if df_selected is None:
        return
    df_selected = calculate_moving_averages(df_selected, short_ma, long_ma)
    
    # 1. 技術面診斷與歷史勝率
    stats, trade_logs_df = calculate_historical_win_rate(df_selected, short_ma, long_ma, signal_type)
    latest_close = df_selected['Close'].iloc[-1]
    prev_close = df_selected['Close'].iloc[-2]
    price_change_pct = ((latest_close - prev_close) / prev_close) * 100
    is_price_up = price_change_pct >= 0
    is_vol_low = df_selected['Volume'].iloc[-1] < df_selected['Vol_MA20'].iloc[-1]
    long_ma_val = df_selected['MA_long'].iloc[-1]

    col_stat, col_diag = st.columns([1, 1])
    with col_stat:
        st.markdown(f"##### {t['win_rate_header']}")
        if stats and 'win_rate_5d' in stats:
            m1, m2, m3 = st.columns(3)
            m1.metric(t["win_rate_5d"], f"{stats.get('win_rate_5d', 0)}%", f"{stats.get('avg_ret_5d', 0)}%")
            m2.metric(t["win_rate_10d"], f"{stats.get('win_rate_10d', 0)}%", f"{stats.get('avg_ret_10d', 0)}%")
            m3.metric(t["win_rate_20d"], f"{stats.get('win_rate_20d', 0)}%", f"{stats.get('avg_ret_20d', 0)}%")
            st.caption(t["signals_count_msg"].format(count=stats['total_signals']))
        else:
            st.info(t["no_sample_msg"])

    with col_diag:
        st.markdown(f"##### {t['diag_header']}")
        if signal_type == "多方":
            if is_price_up and is_vol_low: st.success(t["diag_bull_up_lowvol"].format(pct=price_change_pct, ma_val=long_ma_val, long_ma=long_ma))
            elif is_price_up: st.success(t["diag_bull_up_highvol"].format(pct=price_change_pct))
            elif is_vol_low: st.info(t["diag_bull_down_lowvol"].format(pct=price_change_pct, ma_val=long_ma_val))
            else: st.warning(t["diag_bull_down_highvol"].format(pct=price_change_pct, ma_val=long_ma_val))
        else:
            if not is_price_up and not is_vol_low: st.error(t["diag_bear_down_highvol"].format(pct=price_change_pct, ma_val=long_ma_val, long_ma=long_ma))
            elif is_price_up: st.info(t["diag_bear_up"].format(pct=price_change_pct, ma_val=long_ma_val))
            else: st.warning(t["diag_bear_down_lowvol"].format(pct=price_change_pct))

    if trade_logs_df is not None and not trade_logs_df.empty:
        with st.expander(t["expander_logs"]): st.dataframe(trade_logs_df, width="stretch")

    st.divider()

    # 2. 準備圖表資料與單位換算
    df_chart = df_selected.tail(90).reset_index()
    # 新程式碼（正確：全面無條件捨去成張數）
    df_chart['Volume_Sheets'] = df_chart['Volume'] // 1000
    
    # 計算前一天收盤價做為 K棒 Hover 比對紅綠之基準
    df_chart['Prev_Close'] = df_chart['Close'].shift(1).fillna(df_chart['Open'])
    
    date_strings = df_chart['Date'].dt.strftime('%Y-%m-%d').tolist()
    x_indices = list(range(len(df_chart)))

    # 動態產生 K棒與成交量的 HTML 提示文字
    kline_hover_texts = []
    vol_hover_texts = []
    
    for idx, row in df_chart.iterrows():
        # 處理成交量 Hover
        vol_hover_texts.append(f"<b>{date_strings[idx]}</b><br>成交量: {row['Volume_Sheets']:,} 張")
        
        # 處理 K 棒 Hover (帶紅綠色與箭頭)
        prev_c = row['Prev_Close']
        
        def get_color_str(val, base):
            if val > base:
                return f"<span style='color:#ef5350;'>{val:.2f} ▲</span>"
            elif val < base:
                return f"<span style='color:#26a69a;'>{val:.2f} ▼</span>"
            else:
                return f"<span style='color:#ffffff;'>{val:.2f}</span>"

        open_html = get_color_str(row['Open'], prev_c)
        high_html = get_color_str(row['High'], prev_c)
        low_html = get_color_str(row['Low'], prev_c)
        close_html = get_color_str(row['Close'], prev_c)

        text = (
            f"<b>{date_strings[idx]}</b><br>"
            f"{t['chart_open']}: {open_html}<br>"
            f"{t['chart_high']}: {high_html}<br>"
            f"{t['chart_low']}: {low_html}<br>"
            f"{t['chart_close']}: {close_html}"
        )
        kline_hover_texts.append(text)

    # 3. 繪製圖表
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])

    # K 線圖 (補回 custom hovertext)
    fig.add_trace(go.Candlestick(
        x=x_indices, open=df_chart['Open'], high=df_chart['High'], 
        low=df_chart['Low'], close=df_chart['Close'], name=t['chart_kline'], 
        increasing_line_color='#ef5350', decreasing_line_color='#26a69a',
        hoverinfo="text",
        hovertext=kline_hover_texts
    ), row=1, col=1)

    # 均線
    fig.add_trace(go.Scatter(x=x_indices, y=df_chart['MA_short'], mode='lines', name=f'{short_ma}MA', line=dict(color='#ff9800', width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=x_indices, y=df_chart['MA_long'], mode='lines', name=f'{long_ma}MA', line=dict(color='#2196f3', width=2)), row=1, col=1)
    
    # 成交量柱狀圖
    price_diff = df_chart['Close'].diff().fillna(0)
    vol_colors = ['#ef5350' if diff >= 0 else '#26a69a' for diff in price_diff]
    
    fig.add_trace(go.Bar(
        x=x_indices, 
        y=df_chart['Volume_Sheets'], 
        name=t['chart_vol'], 
        marker_color=vol_colors, 
        opacity=0.7,
        hoverinfo="text",
        hovertext=vol_hover_texts
    ), row=2, col=1)

    fig.update_layout(height=500, margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False)
    step = max(1, len(x_indices) // 10)
    fig.update_xaxes(tickmode='array', tickvals=x_indices[::step], ticktext=[date_strings[i] for i in x_indices[::step]], tickangle=-30, row=2, col=1)
    
    st.plotly_chart(fig, width="stretch")

# ==========================================
# 3. Streamlit 前端 UI 介面
# ==========================================
st.sidebar.header("⚙️ 參數設定")
min_vol = st.sidebar.number_input("最低 20 日均量 (張)", value=500)
min_price = st.sidebar.number_input("最低股價 (元)", value=10.0)
short_ma = st.sidebar.number_input("短均線天數 (MA)", value=5)
long_ma = st.sidebar.number_input("長均線天數 (MA)", value=20)
n_days = st.sidebar.slider("近期交叉天數", 5, 30, 15)
threshold_pct = st.sidebar.slider("均線容錯極限 (%)", 0.5, 10.0, 4.0)

if st.button("🚀 執行全市場轉折掃描", type="primary"):
    with st.spinner("正在記憶體中掃描全台股標的..."):
        scan_df = run_market_scanner(df_all, short_ma, long_ma, n_days, threshold_pct/100.0, min_vol, min_price)
        st.session_state['scan_df'] = scan_df

st.divider()

if 'scan_df' in st.session_state and not st.session_state['scan_df'].empty:
    scan_df = st.session_state['scan_df']
    bull_df = scan_df[scan_df['訊號類型'] == '多方'].drop(columns=['訊號類型'])
    bear_df = scan_df[scan_df['訊號類型'] == '空方'].drop(columns=['訊號類型'])
    
    tab_bull, tab_bear = st.tabs([t["tab_bull"].format(count=len(bull_df)), t["tab_bear"].format(count=len(bear_df))])
    
    with tab_bull:
        if not bull_df.empty:
            st.dataframe(bull_df, width="stretch")
            st.markdown(f"##### {t['select_stock_prompt']}")
            selected_bull = st.selectbox(t["select_bull_label"], options=[f"{row['股票代號']} - {row['股票名稱']}" for _, row in bull_df.iterrows()], key="select_bull")
            if selected_bull:
                render_kline_chart(selected_bull.split(" - ")[0], short_ma, long_ma, "多方")
        else: st.info(t["no_bull_msg"])

    with tab_bear:
        if not bear_df.empty:
            st.dataframe(bear_df, width="stretch")
            st.markdown(f"##### {t['select_stock_prompt']}")
            selected_bear = st.selectbox(t["select_bear_label"], options=[f"{row['股票代號']} - {row['股票名稱']}" for _, row in bear_df.iterrows()], key="select_bear")
            if selected_bear:
                render_kline_chart(selected_bear.split(" - ")[0], short_ma, long_ma, "空方")
        else: st.info(t["no_bear_msg"])