import os
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
# 1. 核心資料載入與【O(1) 快取字典引擎】建置
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "taiwan_market_cache.parquet")

@st.cache_data
def load_market_data():
    try:
        df = pd.read_parquet(CACHE_FILE)
        df['Date'] = pd.to_datetime(df['Date'])
        
        # 🚀 效能革命 1：將 DataFrame 轉為「字典 (Hash Map)」
        # 讓後續取用個別股票時，速度從 O(N) 變成 O(1) 的瞬間讀取！
        grouped = df.groupby('Stock_ID')
        stock_dict = {stock_id: group.set_index('Date').sort_index() for stock_id, group in grouped}
        
        return stock_dict
    except Exception as e:
        st.error(f"❌ 無法讀取本地快取檔，請確認 taiwan_market_cache.parquet 是否存在。錯誤: {e}")
        return {}

# 取得預先整理好的字典，取代原本厚重的 df_all
stock_dict = load_market_data()

if not stock_dict:
    st.warning("⚠️ 目前讀取不到市場數據，請確認 taiwan_market_cache.parquet 檔案已成功推送到 GitHub 儲存庫根目錄。")
    st.stop()

stock_name_map = get_stock_name_map()

def get_stock_name(stock_id):
    return stock_name_map.get(str(stock_id), f"{stock_id}")

# ==========================================
# 2. 策略設定與【輕量化】技術指標計算
# ==========================================
STRATEGY_CONFIG = {
    "短多 (日K 5MA + 20MA)": {
        "timeframe": "D", "short_ma": 5, "long_ma": 20, "n_days": 5,
        "desc": "適合短線動能追蹤：抓取日線 5MA 近 5 日黃金交叉 20MA 且股價回測月線附近之標的。"
    },
    "中多 (日K 20MA + 60MA)": {
        "timeframe": "D", "short_ma": 20, "long_ma": 60, "n_days": 10,
        "desc": "適合波段佈局：抓取日線 20MA 近 10 日黃金交叉 60MA（季線）且月線斜率向上之標的。"
    },
    "長多 (周K 13MA + 52MA)": {
        "timeframe": "W", "short_ma": 13, "long_ma": 52, "n_days": 20,
        "desc": "適合大趨勢保護：抓取周線 13MA 近 20 周黃金交叉 52MA（一年）之長線趨勢發動股。"
    },
}

def process_timeframe_and_ma(df, timeframe, short_ma, long_ma):
    """根據指定週期進行重採樣與均線計算"""
    if timeframe == "W":
        df_resampled = df.resample('W-FRI').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
    else:
        df_resampled = df.copy()

    df_resampled['MA_short'] = df_resampled['Close'].rolling(window=short_ma).mean()
    df_resampled['MA_long'] = df_resampled['Close'].rolling(window=long_ma).mean()
    df_resampled['Vol_MA20'] = df_resampled['Volume'].rolling(window=20).mean()
    return df_resampled

@st.cache_data
def run_market_scanner(_stock_dict, strategy_name, entry_pattern, min_volume_sheets, price_range, exclude_emerging=True, new_tag_days=3):
    cfg = STRATEGY_CONFIG[strategy_name]
    timeframe = cfg['timeframe']
    short_ma = cfg['short_ma']
    long_ma = cfg['long_ma']
    n_days = cfg['n_days']
    
    pattern_map = {
        "貼近均線 (強效支撐)": 0.03,
        "適度回測 (標準進場)": 0.05,
        "允許追高 (強勢動能)": 0.08
    }
    threshold = pattern_map.get(entry_pattern, 0.05)
    results = []
    
    for stock_id, df_raw in _stock_dict.items():
        # 📌 興櫃與創櫃板過濾判斷
        stock_market = df_raw['Market'].iloc[-1] if 'Market' in df_raw.columns else None
        
        if exclude_emerging:
            if stock_market in ["興櫃", "創櫃"]:
                continue
            if stock_market is None and (str(stock_id).startswith('74') or str(stock_id).startswith('75')):
                continue

        lookback_bars = 350 if timeframe == "W" else 120
        df_slice = df_raw.tail(lookback_bars).copy()
        
        if len(df_slice) < 40:
            continue

        latest_close = df_slice['Close'].iloc[-1]
        raw_avg_vol = (df_slice['Volume'] // 1000).tail(20).mean()
        
        if raw_avg_vol < min_volume_sheets:
            continue
            
        if price_range == "高價股(100元以上)" and latest_close < 100:
            continue
        elif price_range == "低價股(100元以下)" and latest_close >= 100:
            continue
            
        df = process_timeframe_and_ma(df_slice, timeframe, short_ma, long_ma)
        if len(df) < (long_ma + 5):
            continue

        golden_cross = (df['MA_short'] > df['MA_long']) & (df['MA_short'].shift(1) <= df['MA_long'].shift(1))
        death_cross = (df['MA_short'] < df['MA_long']) & (df['MA_short'].shift(1) >= df['MA_long'].shift(1))
        
        entangled_crosses = (golden_cross | death_cross).tail(20).sum()
        if entangled_crosses >= 3:
            continue
            
        current_ma_long = df['MA_long'].iloc[-1]
        ma_long_prev = df['MA_long'].iloc[-4] if len(df) >= 4 else current_ma_long
        is_long_ma_up = current_ma_long > ma_long_prev

        recent_golden = golden_cross.tail(n_days).any()
        ma_bullish = df['MA_short'].iloc[-1] > df['MA_long'].iloc[-1]
        price_near = (abs(df['Close'].iloc[-1] - current_ma_long) / current_ma_long) <= threshold
        
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
                "股票名稱": get_stock_name(stock_id),
                "最新收盤價": round(latest_close, 2),
                "20日均量(張)": int(raw_avg_vol),
                "距長均線(%)": round((df['Close'].iloc[-1] - current_ma_long) / current_ma_long * 100, 2),
                "週期形態": "周K" if timeframe == "W" else "日K",
                "資料日期": df.index[-1].strftime('%Y-%m-%d')
            })
            
    return pd.DataFrame(results)

def calculate_historical_win_rate(df, short_ma, long_ma, signal_type="多方", n_days=15, threshold=0.04):
    df_calc = df.copy()
    cross = (df_calc['MA_short'] > df_calc['MA_long']) & (df_calc['MA_short'].shift(1) <= df_calc['MA_long'].shift(1))
    order = df_calc['MA_short'] > df_calc['MA_long']
    
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
                ret = (future_price - entry_price) / entry_price
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

def render_kline_chart(stock_id, strategy_name):
    cfg = STRATEGY_CONFIG[strategy_name]
    timeframe = cfg['timeframe']
    short_ma = cfg['short_ma']
    long_ma = cfg['long_ma']

    df_raw = stock_dict.get(stock_id)
    if df_raw is None:
        return
    
    df_selected = process_timeframe_and_ma(df_raw, timeframe, short_ma, long_ma)
    
    stats, trade_logs_df = calculate_historical_win_rate(df_selected, short_ma, long_ma)
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
        if is_price_up and is_vol_low: st.success(t["diag_bull_up_lowvol"].format(pct=price_change_pct, ma_val=long_ma_val, long_ma=long_ma))
        elif is_price_up: st.success(t["diag_bull_up_highvol"].format(pct=price_change_pct))
        elif is_vol_low: st.info(t["diag_bull_down_lowvol"].format(pct=price_change_pct, ma_val=long_ma_val))
        else: st.warning(t["diag_bull_down_highvol"].format(pct=price_change_pct, ma_val=long_ma_val))

    if trade_logs_df is not None and not trade_logs_df.empty:
        with st.expander(t["expander_logs"]): st.dataframe(trade_logs_df, width="stretch")

    st.divider()

    df_chart = df_selected.tail(90).reset_index()
    df_chart['Volume_Sheets'] = df_chart['Volume'] // 1000
    df_chart['Prev_Close'] = df_chart['Close'].shift(1).fillna(df_chart['Open'])
    
    date_strings = df_chart['Date'].dt.strftime('%Y-%m-%d').tolist()
    x_vals = date_strings 

    vol_hover_texts = []
    combined_texts = [] 
    
    tf_label = "周" if timeframe == "W" else "日"

    for idx, row in df_chart.iterrows():
        vol_hover_texts.append(f"<b>{date_strings[idx]} ({tf_label}K)</b><br>成交量: {row['Volume_Sheets']:,} 張")
        
        prev_c = row['Prev_Close']
        def get_color_str(val, base):
            if val > base: return f"<span style='color:#ef5350;'>{val:.2f} ▲</span>"
            elif val < base: return f"<span style='color:#26a69a;'>{val:.2f} ▼</span>"
            else: return f"<span style='color:#ffffff;'>{val:.2f}</span>"

        open_html = get_color_str(row['Open'], prev_c)
        high_html = get_color_str(row['High'], prev_c)
        low_html = get_color_str(row['Low'], prev_c)
        close_html = get_color_str(row['Close'], prev_c)

        text = (
            f"<b>{date_strings[idx]} ({tf_label}K)</b><br><br>"
            f"{t['chart_open']}: {open_html}<br>"
            f"{t['chart_high']}: {high_html}<br>"
            f"{t['chart_low']}: {low_html}<br>"
            f"{t['chart_close']}: {close_html}<br><br>"
            f"<span style='color:#ffa726;'>{short_ma}{tf_label}MA: {row['MA_short']:.2f}</span><br>"
            f"<span style='color:#42a5f5;'>{long_ma}{tf_label}MA: {row['MA_long']:.2f}</span>"
        )
        combined_texts.append(text)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])

    fig.add_trace(go.Scatter(
        x=x_vals, y=df_chart['Close'], mode='lines', line=dict(color='rgba(0,0,0,0)'), 
        text=combined_texts, hovertemplate="%{text}<extra></extra>", showlegend=False, hoverinfo="text"
    ), row=1, col=1)

    fig.add_trace(go.Candlestick(
        x=x_vals, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], 
        name=f"{tf_label}K線", increasing_line_color='#ef5350', decreasing_line_color='#26a69a', hoverinfo='skip'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=x_vals, y=df_chart['MA_short'], name=f"{short_ma}{tf_label}MA", line=dict(color='orange', width=1.5), hoverinfo='skip'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=x_vals, y=df_chart['MA_long'], name=f"{long_ma}{tf_label}MA", line=dict(color='#42a5f5', width=1.5), hoverinfo='skip'
    ), row=1, col=1)
    
    price_diff = df_chart['Close'].diff().fillna(0)
    vol_colors = ['#ef5350' if diff >= 0 else '#26a69a' for diff in price_diff]
    fig.add_trace(go.Bar(
        x=x_vals, y=df_chart['Volume_Sheets'], name=t['chart_vol'], 
        marker_color=vol_colors, opacity=0.7, hoverinfo="text", hovertext=vol_hover_texts
    ), row=2, col=1)

    fig.update_layout(
        hovermode='x', hoverdistance=100, spikedistance=1000, height=500, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(0,0,0,0)")
    )
    
    fig.update_xaxes(type='category', showspikes=True, spikethickness=1, spikemode='across', spikedash='dash')
    
    step = max(1, len(x_vals) // 10)
    fig.update_xaxes(tickmode='array', tickvals=x_vals[::step], ticktext=x_vals[::step], tickangle=-30, row=2, col=1)
    
    st.plotly_chart(fig, width="stretch", use_container_width=True)

# ==========================================
# 3. Streamlit 前端 UI 介面
# ==========================================
st.sidebar.header("🎯 策略選擇")

strategy_name = st.sidebar.selectbox(
    "選擇選股模式",
    options=list(STRATEGY_CONFIG.keys()),
    index=0
)

st.sidebar.divider()
st.sidebar.subheader("⚙️ 選股池設定")

filter_high_vol = st.sidebar.checkbox("僅篩選 20 日均量 ≥ 1000 張 (預設)", value=True)
min_vol = 1000 if filter_high_vol else 0

exclude_emerging = st.sidebar.checkbox("排除興櫃與創櫃板 (預設)", value=True)

price_range = st.sidebar.selectbox(
    "股價區間",
    options=["高價股(100元以上)", "低價股(100元以下)"],
    index=0
)

entry_pattern = st.sidebar.selectbox(
    "買點型態",
    options=["貼近均線 (強效支撐)", "適度回測 (標準進場)", "允許追高 (強勢動能)"],
    index=0,
    help="貼近均線代表股價剛拉回長均線支撐附近，進場風險最低。"
)

with st.spinner(f"正在以【{strategy_name}】模式掃描全台股..."):
    scan_df = run_market_scanner(
        stock_dict, strategy_name, entry_pattern, min_vol, price_range, exclude_emerging, new_tag_days=3
    )

st.divider()

# ==========================================
# 4. 顯示掃描結果與說明卡片
# ==========================================
if scan_df is not None and not scan_df.empty:
    cfg = STRATEGY_CONFIG[strategy_name]
    
    vol_text = "≥ **1000** 張 (主流流動性)" if filter_high_vol else "**包含 1000 張以下標的** (全市場)"
    price_text = "≥ **100** 元 (高價股)" if price_range == "高價股(100元以上)" else "< **100** 元 (低價股)"
    market_text = "上市/上櫃" if exclude_emerging else "全市場 (含興櫃/創櫃)"
    curr_n_days = cfg['n_days']
    tf_unit = "周" if cfg['timeframe'] == "W" else "日"
    
    st.subheader(f"📊 掃描結果：{strategy_name}")
    st.info(
        f"💡 **篩選邏輯說明**：\n"
        f"* **核心策略**：{cfg['desc']}\n"
        f"* **過濾條件**：市場別：**{market_text}** | 20 日均量 {vol_text} | 股價 {price_text} | "
        f"近 **{curr_n_days}** 根 {tf_unit}K 棒內交叉 | 買點位置：**{entry_pattern}**\n"
        f"* **自動洗盤防禦**：排除近 20 根 K 棒交叉 3 次以上之均線糾結橫盤股。"
    )

    new_count = scan_df['Is_New'].sum()
    st.caption(f"共掃描出 **{len(scan_df)}** 檔標的（其中 **{new_count}** 檔為近 3 天內剛交叉的 **NEW** 標的）")

    scan_df = scan_df.sort_values(by=['Is_New', '距長均線(%)'], ascending=[False, True])
    
    st.markdown(f"##### {t['select_stock_prompt']}")
    
    options = [
        f"{row['股票代號']} - {row['股票名稱']}{' (NEW)' if row['Is_New'] else ''}"
        for _, row in scan_df.iterrows()
    ]
    
    selected_stock = st.selectbox(
        "請選擇股票查看分析與圖表：",
        options=options,
        key="selected_stock"
    )
    
    if selected_stock:
        stock_id = selected_stock.split(" - ")[0].strip()
        render_kline_chart(stock_id, strategy_name)

else:
    st.info("ℹ️ 當前條件下未找到符合策略之股票，請嘗試切換其他股價區間或買點型態。")