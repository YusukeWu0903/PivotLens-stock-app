import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from FinMind.data import DataLoader

# ==========================================
# 0. 多國語言 (i18n) 全局字典對照表
# ==========================================
I18N = {
    "ZH": {
        "page_title": "台股均線轉折選股系統",
        "app_title": "📈 台股均線轉折選股系統",
        "app_subtitle": "⚡ 自動過濾冷門殭屍股，專注於具備流動性之熱門標的轉折買賣點。",
        "sidebar_lang": "🌐 語言 / Language",
        "sidebar_params": "⚙️ 選股門檻與參數設定",
        "sidebar_liquidity": "🛡️ 第一道：流動性防線",
        "min_volume": "最低 20 日均量 (張)",
        "min_price": "最低股價 (元)",
        "sidebar_ma": "📊 第二道：均線型態參數",
        "short_ma": "短均線天數 (MA)",
        "long_ma": "長均線天數 (MA)",
        "cross_days": "近期發生交叉天數",
        "tolerance": "均線容錯極限 (%)",
        "scan_btn": "🚀 執行熱門股轉折掃描",
        "scanning_msg": "系統正在計算精選指標股，並進行流動性過濾...",
        "active_filters": "📌 **當前篩選條件：** ① 近 20 日均量 $\ge$ **{vol}** 張且股價 $\ge$ **{price}** 元 ｜ ② 近 **{days}** 天內曾發生 **{short}MA** 與 **{long}MA** 交叉 ｜ ③ 當前股價距 **{long}MA** 介於 **$\pm${pct}%** 內",
        "tab_bull": "🟢 多方金叉回測 ({count})",
        "tab_bear": "🔴 空方死叉反彈 ({count})",
        "no_bull_msg": "當前條件下無符合之【多方金叉回測】股票，可嘗試於左側調大容錯極限 (%)。",
        "no_bear_msg": "當前條件下無符合之【空方死叉反彈】股票，可嘗試於左側調大容錯極限 (%)。",
        "select_stock_prompt": "🔎 點擊選擇股票查看診斷與走勢",
        "select_bull_label": "請選擇多方標的：",
        "select_bear_label": "請選擇空方標的：",
        "win_rate_header": "📊 歷史勝率統計 (近 1 年)",
        "win_rate_5d": "5日勝率",
        "win_rate_10d": "10日勝率",
        "win_rate_20d": "20日勝率",
        "signals_count_msg": "💡 過去一年共發動 **{count}** 次相同訊號。",
        "no_sample_msg": "該股過去一年發動相同訊號樣本數不足，無法計算歷史勝率。",
        "diag_header": "💡 技術面診斷與情境策略",
        "expander_logs": "📅 點擊展開「近一年歷史進出場日期與報酬率明細」以供券商軟體對照驗證",
        "col_symbol": "股票代號",
        "col_name": "股票名稱",
        "col_close": "最新收盤價",
        "col_vol": "20日均量(張)",
        "col_dist": "距長均線(%)",
        "col_signal": "訊號類型",
        "col_date": "資料日期",
        "chart_open": "開盤",
        "chart_high": "最高",
        "chart_low": "最低",
        "chart_close": "收盤",
        "chart_kline": "K棒",
        "chart_vol": "成交量",
        "log_entry_date": "訊號觸發(進場)日",
        "log_entry_price": "進場價格",
        "log_exit_date": "{days}日後結算日",
        "log_ret": "{days}日報酬(%)",
        "diag_bull_up_lowvol": "🟢 **【量縮驚驚漲 / 惜售】** 今日上漲 **{pct:+.2f}%** 且量能低於均量，顯示籌碼沉澱且市場惜售。關鍵防守位為 **{ma_val:.2f} 元** ({long_ma}MA)。",
        "diag_bull_up_highvol": "🚀 **【帶量強勢攻擊】** 今日帶量上漲 **{pct:+.2f}%**，多頭買盤強勁，持續看好延伸行情。",
        "diag_bull_down_lowvol": "🧘 **【健康量縮回測】** 今日拉回 **{pct:+.2f}%** 但成交量萎縮，屬於健康回測。守穩 **{ma_val:.2f} 元** 均線支撐皆可看多。",
        "diag_bull_down_highvol": "⚠️ **【留意帶量拉回】** 今日爆量下跌 **{pct:+.2f}%**，賣壓增強，請密切注意 **{ma_val:.2f} 元** 支撐，跌破需防金叉失敗。",
        "diag_bear_down_highvol": "🔴 **【帶量下殺 / 遇壓】** 今日帶量下殺 **{pct:+.2f}%**，受制於 **{ma_val:.2f} 元** ({long_ma}MA) 反壓，空方力道強勁。",
        "diag_bear_up": "🚀 **【死叉有化解跡象】** 今日逆勢反彈 **{pct:+.2f}%** 並逼近/突破 **{ma_val:.2f} 元**，留意空方反彈壓力是否被強行扭轉。",
        "diag_bear_down_lowvol": "📉 **【無量弱勢陰跌】** 今日下跌 **{pct:+.2f}%** 且無買盤承接，短線反彈無力，提防再度破底。"
    },
    "EN": {
        "page_title": "Taiwan Stock MA Crossover Screener",
        "app_title": "📈 Taiwan Stock MA Crossover Screener",
        "app_subtitle": "⚡ Filter low-liquidity stocks & focus on turning points of liquid targets.",
        "sidebar_lang": "🌐 Language / 語言",
        "sidebar_params": "⚙️ Screener Thresholds & Parameters",
        "sidebar_liquidity": "🛡️ Step 1: Liquidity Filter",
        "min_volume": "Min 20D Avg Volume (Sheets)",
        "min_price": "Min Stock Price (TWD)",
        "sidebar_ma": "📊 Step 2: Technical Parameters",
        "short_ma": "Short MA (Days)",
        "long_ma": "Long MA (Days)",
        "cross_days": "Recent Crossover Window (Days)",
        "tolerance": "MA Distance Tolerance (%)",
        "scan_btn": "🚀 Run Market Screener",
        "scanning_msg": "Calculating indicator stocks & applying liquidity filters...",
        "active_filters": "📌 **Active Filters:** ① 20D Avg Vol $\ge$ **{vol}** sheets & Price $\ge$ **{price}** TWD ｜ ② **{short}MA** & **{long}MA** crossover within **{days}** days ｜ ③ Price within **$\pm${pct}%** of **{long}MA**",
        "tab_bull": "🟢 Bullish Golden Cross ({count})",
        "tab_bear": "🔴 Bearish Death Cross ({count})",
        "no_bull_msg": "No stocks match 【Bullish Golden Cross】 under active criteria. Try increasing tolerance (%) in sidebar.",
        "no_bear_msg": "No stocks match 【Bearish Death Cross】 under active criteria. Try increasing tolerance (%) in sidebar.",
        "select_stock_prompt": "🔎 Select a stock to inspect technical diagnosis & chart",
        "select_bull_label": "Select Bullish Target:",
        "select_bear_label": "Select Bearish Target:",
        "win_rate_header": "📊 Historical Win Rate (Past 1 Year)",
        "win_rate_5d": "5D Win Rate",
        "win_rate_10d": "10D Win Rate",
        "win_rate_20d": "20D Win Rate",
        "signals_count_msg": "💡 **{count}** identical signals triggered in past year.",
        "no_sample_msg": "Insufficient signal samples in past year to compute historical win rate.",
        "diag_header": "💡 Technical Diagnosis & Strategy",
        "expander_logs": "📅 Click to expand '1-Year Entry/Exit Trade Logs' for brokerage verification",
        "col_symbol": "Symbol",
        "col_name": "Name",
        "col_close": "Close Price",
        "col_vol": "20D Avg Vol",
        "col_dist": "Dist to MA (%)",
        "col_signal": "Signal Type",
        "col_date": "Date",
        "chart_open": "Open",
        "chart_high": "High",
        "chart_low": "Low",
        "chart_close": "Close",
        "chart_kline": "Candlestick",
        "chart_vol": "Volume",
        "log_entry_date": "Signal Entry Date",
        "log_entry_price": "Entry Price",
        "log_exit_date": "{days}D Exit Date",
        "log_ret": "{days}D Return (%)",
        "diag_bull_up_lowvol": "🟢 **【Low Volume Creep / Low Supply】** Price up **{pct:+.2f}%** today with volume below MA. Supply is tight. Defense level at **{ma_val:.2f} TWD** ({long_ma}MA).",
        "diag_bull_up_highvol": "🚀 **【Strong Volume Attack】** Strong surge **{pct:+.2f}%** on high volume. Bullish momentum active.",
        "diag_bull_down_lowvol": "🧘 **【Healthy Low-Volume Pullback】** Pullback of **{pct:+.2f}%** on shrinking volume. Healthy retracement as long as **{ma_val:.2f} TWD** holds.",
        "diag_bull_down_highvol": "⚠️ **【Beware Heavy Volume Drop】** Sharp fall **{pct:+.2f}%** on heavy volume. Watch **{ma_val:.2f} TWD** support carefully.",
        "diag_bear_down_highvol": "🔴 **【Heavy Volume Selloff】** Sharp drop **{pct:+.2f}%** under **{ma_val:.2f} TWD** ({long_ma}MA) resistance. Bearish pressure dominant.",
        "diag_bear_up": "🚀 **【Death Cross Break Reversal】** Rebound **{pct:+.2f}%** testing/breaking **{ma_val:.2f} TWD**. Watch if short squeeze develops.",
        "diag_bear_down_lowvol": "📉 **【Weak Low-Volume Drift Down】** Down **{pct:+.2f}%** without buying interest. Rebound weak, beware further lows."
    }
}

# 動態轉換 Dataframe 標頭
def format_df_for_lang(df, lang):
    t = I18N[lang]
    col_map = {
        "股票代號": t["col_symbol"],
        "股票名稱": t["col_name"],
        "最新收盤價": t["col_close"],
        "20日均量(張)": t["col_vol"],
        "距長均線(%)": t["col_dist"],
        "資料日期": t["col_date"],
        "訊號類型": t["col_signal"]
    }
    return df.copy().rename(columns=col_map)

# ==========================================
# 1. 數據獲取與對照模組
# ==========================================
@st.cache_data(ttl=86400)
def get_stock_name_dict():
    return {
        "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2308": "台達電", "2382": "廣達",
        "3231": "緯創", "2376": "技嘉", "2603": "長榮", "3037": "欣興", "2303": "聯電",
        "1513": "中興電", "1504": "東元", "2609": "陽明", "2615": "萬海", "3017": "奇鋐",
        "3661": "世芯-KY", "6669": "緯穎", "3443": "創意", "2357": "華碩", "2301": "光寶科",
        "2881": "富邦金", "2882": "國泰金", "2891": "中信金", "5880": "合庫金", "2618": "長榮航",
        "2610": "華航", "2002": "中鋼", "1301": "台塑", "1303": "南亞", "3711": "日月光投控"
    }

def get_taiwan_stock_universe():
    return list(get_stock_name_dict().keys())

@st.cache_data(ttl=1800)
def fetch_stock_data(stock_id: str):
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    dl = DataLoader()
    try:
        df_fm = dl.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if df_fm.empty or len(df_fm) < 60:
            return None
        
        df = df_fm.rename(columns={
            'date': 'Date', 'close': 'Close', 'Trading_Volume': 'Volume',
            'max': 'High', 'min': 'Low', 'open': 'Open'
        })
        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        return df[['Open', 'High', 'Low', 'Close', 'Volume']].sort_index()
    except Exception:
        return None

# ==========================================
# 2. 技術面邏輯與單股掃描 Engine
# ==========================================
def calculate_moving_averages(df, short_window, long_window):
    df['MA_short'] = df['Close'].rolling(window=short_window).mean()
    df['MA_long'] = df['Close'].rolling(window=long_window).mean()
    df['Vol_MA20'] = df['Volume'].rolling(window=20).mean()
    return df

def scan_single_stock(stock_id, short_ma, long_ma, n_days, threshold, min_volume_sheets, min_price):
    df = fetch_stock_data(stock_id)
    if df is None or len(df) < (long_ma + 5):
        return None
        
    latest_close = df['Close'].iloc[-1]
    raw_avg_vol = df['Volume'].tail(20).mean()
    avg_vol_20d_sheets = raw_avg_vol / 1000.0 if raw_avg_vol > 5000 else raw_avg_vol
        
    if avg_vol_20d_sheets < min_volume_sheets or latest_close < min_price:
        return None
        
    df = calculate_moving_averages(df, short_window=short_ma, long_window=long_ma)
    
    golden_cross = (df['MA_short'] > df['MA_long']) & (df['MA_short'].shift(1) <= df['MA_long'].shift(1))
    recent_golden = golden_cross.tail(n_days).any()
    ma_bullish = df['MA_short'].iloc[-1] > df['MA_long'].iloc[-1]
    
    current_ma_long = df['MA_long'].iloc[-1]
    dist_pct = abs(latest_close - current_ma_long) / current_ma_long
    price_near = dist_pct <= threshold
    
    is_bullish = recent_golden and ma_bullish and price_near

    death_cross = (df['MA_short'] < df['MA_long']) & (df['MA_short'].shift(1) >= df['MA_long'].shift(1))
    recent_death = death_cross.tail(n_days).any()
    ma_bearish = df['MA_short'].iloc[-1] < df['MA_long'].iloc[-1]
    
    is_bearish = recent_death and ma_bearish and price_near

    if is_bullish or is_bearish:
        name_dict = get_stock_name_dict()
        stock_name = name_dict.get(stock_id, "未知")
        signal_type = "多方" if is_bullish else "空方"
        
        return {
            "股票代號": stock_id,
            "股票名稱": stock_name,
            "最新收盤價": round(latest_close, 2),
            "20日均量(張)": int(avg_vol_20d_sheets),
            "距長均線(%)": round((latest_close - current_ma_long) / current_ma_long * 100, 2),
            "訊號類型": signal_type,
            "資料日期": df.index[-1].strftime('%Y-%m-%d')
        }
    return None

@st.cache_data(ttl=1800)
def run_market_scanner(stock_pool, short_ma, long_ma, n_days, threshold, min_vol, min_price):
    results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(scan_single_stock, s_id, short_ma, long_ma, n_days, threshold, min_vol, min_price): s_id 
            for s_id in stock_pool
        }
        for future in as_completed(futures):
            res = future.result()
            if res:
                results.append(res)
    return pd.DataFrame(results)

# ==========================================
# 3. 歷史勝率與動態診斷 Engine (含 i18n)
# ==========================================
def calculate_historical_win_rate(df, short_ma, long_ma, signal_type, lang="ZH", n_days=15, threshold=0.04):
    t = I18N[lang]
    df_calc = df.copy()
    
    if signal_type == "多方":
        cross = (df_calc['MA_short'] > df_calc['MA_long']) & (df_calc['MA_short'].shift(1) <= df_calc['MA_long'].shift(1))
        order = df_calc['MA_short'] > df_calc['MA_long']
    else:
        cross = (df_calc['MA_short'] < df_calc['MA_long']) & (df_calc['MA_short'].shift(1) >= df_calc['MA_long'].shift(1))
        order = df_calc['MA_short'] < df_calc['MA_long']
        
    recent_cross = cross.rolling(window=n_days).max() > 0
    dist_pct = abs(df_calc['Close'] - df_calc['MA_long']) / df_calc['MA_long']
    price_near = dist_pct <= threshold
    
    signal_mask = recent_cross & order & price_near
    entry_signals = signal_mask & (~signal_mask.shift(1).fillna(False))
    signal_dates = df_calc[entry_signals].index
    
    results = []
    trade_logs = []
    
    for date in signal_dates:
        loc = df_calc.index.get_loc(date)
        entry_price = df_calc.loc[date, 'Close']
        entry_date_str = date.strftime('%Y-%m-%d')
        
        res = {}
        log_entry = {
            t["log_entry_date"]: entry_date_str,
            t["log_entry_price"]: round(entry_price, 2)
        }
        
        for hold_days in [5, 10, 20]:
            if loc + hold_days < len(df_calc):
                exit_date = df_calc.index[loc + hold_days]
                exit_date_str = exit_date.strftime('%Y-%m-%d')
                future_price = df_calc['Close'].iloc[loc + hold_days]
                
                ret = (future_price - entry_price) / entry_price if signal_type == "多方" else (entry_price - future_price) / entry_price
                res[f'ret_{hold_days}d'] = ret
                res[f'win_{hold_days}d'] = 1 if ret > 0 else 0
                
                exit_lbl = t["log_exit_date"].format(days=hold_days)
                ret_lbl = t["log_ret"].format(days=hold_days)
                log_entry[exit_lbl] = exit_date_str
                log_entry[ret_lbl] = f"{round(ret * 100, 2)}%"
                
        if res:
            results.append(res)
            trade_logs.append(log_entry)
            
    if not results:
        return None, None
        
    df_res = pd.DataFrame(results)
    df_logs = pd.DataFrame(trade_logs)
    
    summary = {"total_signals": len(df_res)}
    for hold_days in [5, 10, 20]:
        if f'win_{hold_days}d' in df_res.columns:
            summary[f'win_rate_{hold_days}d'] = round(df_res[f'win_{hold_days}d'].mean() * 100, 1)
            summary[f'avg_ret_{hold_days}d'] = round(df_res[f'ret_{hold_days}d'].mean() * 100, 2)
            
    return summary, df_logs

def render_diagnosis_and_backtest(df_selected, signal_type, short_ma, long_ma, lang="ZH"):
    t = I18N[lang]
    latest_close = df_selected['Close'].iloc[-1]
    prev_close = df_selected['Close'].iloc[-2]
    latest_vol = df_selected['Volume'].iloc[-1]
    vol_ma20 = df_selected['Vol_MA20'].iloc[-1]
    long_ma_val = df_selected['MA_long'].iloc[-1]
    
    price_change_pct = ((latest_close - prev_close) / prev_close) * 100
    is_price_up = price_change_pct >= 0
    is_vol_low = latest_vol < vol_ma20
    
    stats, trade_logs_df = calculate_historical_win_rate(df_selected, short_ma, long_ma, signal_type, lang=lang)
    
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
            if is_price_up and is_vol_low:
                st.success(t["diag_bull_up_lowvol"].format(pct=price_change_pct, ma_val=long_ma_val, long_ma=long_ma))
            elif is_price_up and not is_vol_low:
                st.success(t["diag_bull_up_highvol"].format(pct=price_change_pct))
            elif not is_price_up and is_vol_low:
                st.info(t["diag_bull_down_lowvol"].format(pct=price_change_pct, ma_val=long_ma_val))
            else:
                st.warning(t["diag_bull_down_highvol"].format(pct=price_change_pct, ma_val=long_ma_val))
        else:
            if not is_price_up and not is_vol_low:
                st.error(t["diag_bear_down_highvol"].format(pct=price_change_pct, ma_val=long_ma_val, long_ma=long_ma))
            elif is_price_up:
                st.info(t["diag_bear_up"].format(pct=price_change_pct, ma_val=long_ma_val))
            else:
                st.warning(t["diag_bear_down_lowvol"].format(pct=price_change_pct))

    if trade_logs_df is not None and not trade_logs_df.empty:
        with st.expander(t["expander_logs"]):
            st.dataframe(trade_logs_df, width="stretch")

# 繪圖函式 (連動昨收與多國語言 Hover Tooltip)
def render_kline_chart(stock_id, short_ma, long_ma, signal_type, lang="ZH"):
    t = I18N[lang]
    df_selected = fetch_stock_data(stock_id)
    df_selected = calculate_moving_averages(df_selected, short_ma, long_ma)
    
    render_diagnosis_and_backtest(df_selected, signal_type, short_ma, long_ma, lang=lang)
    st.divider()
    
    df_chart = df_selected.tail(90).copy().reset_index()
    
    # 計算前一天收盤價做為 Hover 比對紅綠之基準
    df_chart['Prev_Close'] = df_chart['Close'].shift(1).fillna(df_chart['Open'])
    
    # 動態產生依據昨收價標示紅綠顏色的 HTML Hover 提示
    hover_texts = []
    for idx, row in df_chart.iterrows():
        prev_c = row['Prev_Close']
        date_str = row['Date'].strftime('%Y-%m-%d')
        
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
            f"<b>{date_str}</b><br>"
            f"{t['chart_open']}: {open_html}<br>"
            f"{t['chart_high']}: {high_html}<br>"
            f"{t['chart_low']}: {low_html}<br>"
            f"{t['chart_close']}: {close_html}"
        )
        hover_texts.append(text)

    date_strings = df_chart['Date'].dt.strftime('%Y-%m-%d').tolist()
    x_indices = list(range(len(df_chart)))

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])

    fig.add_trace(go.Candlestick(
        x=x_indices, open=df_chart['Open'], high=df_chart['High'],
        low=df_chart['Low'], close=df_chart['Close'], name=t['chart_kline'],
        hoverinfo="text", hovertext=hover_texts,
        increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=x_indices, y=df_chart['MA_short'], mode='lines', name=f'{short_ma}MA', hoverinfo="none", line=dict(color='#ff9800', width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=x_indices, y=df_chart['MA_long'], mode='lines', name=f'{long_ma}MA', hoverinfo="none", line=dict(color='#2196f3', width=2)), row=1, col=1)

    price_diff = df_chart['Close'].diff().fillna(0)
    vol_colors = ['#ef5350' if diff >= 0 else '#26a69a' for diff in price_diff]
    fig.add_trace(go.Bar(x=x_indices, y=df_chart['Volume'], name=t['chart_vol'], hoverinfo="x+y", marker_color=vol_colors, opacity=0.7), row=2, col=1)

    fig.update_layout(height=500, margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02, x=0.01))

    step = max(1, len(x_indices) // 10)
    fig.update_xaxes(tickmode='array', tickvals=x_indices[::step], ticktext=[date_strings[i] for i in x_indices[::step]], tickangle=-30, row=2, col=1)
    fig.update_yaxes(title_text="Price" if lang=="EN" else "股價", row=1, col=1)
    fig.update_yaxes(title_text="Volume" if lang=="EN" else "成交量", row=2, col=1)

    st.plotly_chart(fig, width="stretch", config={'displayModeBar': 'hover'})

# ==========================================
# 4. Streamlit 前端 UI 介面
# ==========================================
# 側邊欄：語言切換選單
st.sidebar.header("🌐 Language / 語言")
lang_choice = st.sidebar.selectbox("Select Language / 選擇介面語言", ["繁體中文", "English"])
lang = "EN" if lang_choice == "English" else "ZH"
t = I18N[lang]

st.set_page_config(page_title=t["page_title"], page_icon="📈", layout="wide")
st.title(t["app_title"])
st.caption(t["app_subtitle"])

# 側邊欄參數設定
st.sidebar.header(t["sidebar_params"])
st.sidebar.subheader(t["sidebar_liquidity"])
min_volume_sheets = st.sidebar.number_input(t["min_volume"], min_value=100, max_value=10000, value=500, step=100)
min_price = st.sidebar.number_input(t["min_price"], min_value=1.0, max_value=100.0, value=10.0, step=1.0)

st.sidebar.subheader(t["sidebar_ma"])
short_ma = st.sidebar.number_input(t["short_ma"], min_value=5, max_value=60, value=5)
long_ma = st.sidebar.number_input(t["long_ma"], min_value=20, max_value=240, value=20)
n_days = st.sidebar.slider(t["cross_days"], min_value=5, max_value=30, value=15)
threshold_pct = st.sidebar.slider(t["tolerance"], min_value=0.5, max_value=10.0, value=4.0, step=0.5)

# 掃描按鈕區塊
stock_universe = get_taiwan_stock_universe()
if st.button(t["scan_btn"], type="primary"):
    with st.spinner(t["scanning_msg"]):
        threshold = threshold_pct / 100.0
        scan_df = run_market_scanner(
            stock_universe, short_ma, long_ma, n_days, threshold, min_volume_sheets, min_price
        )
        st.session_state['scan_df'] = scan_df

st.caption(t["active_filters"].format(vol=min_volume_sheets, price=min_price, days=n_days, short=short_ma, long=long_ma, pct=threshold_pct))

st.divider()

if 'scan_df' in st.session_state:
    scan_df = st.session_state['scan_df']
    
    bull_df = scan_df[scan_df['訊號類型'] == '多方'].drop(columns=['訊號類型']) if not scan_df.empty else pd.DataFrame()
    bear_df = scan_df[scan_df['訊號類型'] == '空方'].drop(columns=['訊號類型']) if not scan_df.empty else pd.DataFrame()
    
    tab_bull, tab_bear = st.tabs([
        t["tab_bull"].format(count=len(bull_df)), 
        t["tab_bear"].format(count=len(bear_df))
    ])
    
    with tab_bull:
        if not bull_df.empty:
            st.dataframe(format_df_for_lang(bull_df, lang), width="stretch")
            
            st.markdown(f"##### {t['select_stock_prompt']}")
            col_sel1, _ = st.columns([1, 2])
            with col_sel1:
                bull_options = [f"{row['股票代號']} - {row['股票名稱'] if lang=='ZH' else row['股票代號']}" for _, row in bull_df.iterrows()]
                selected_bull = st.selectbox(t["select_bull_label"], options=bull_options, key="select_bull")
            
            if selected_bull:
                stock_id = selected_bull.split(" - ")[0]
                render_kline_chart(stock_id, short_ma, long_ma, "多方", lang=lang)
        else:
            st.info(t["no_bull_msg"])

    with tab_bear:
        if not bear_df.empty:
            st.dataframe(format_df_for_lang(bear_df, lang), width="stretch")
            
            st.markdown(f"##### {t['select_stock_prompt']}")
            col_sel2, _ = st.columns([1, 2])
            with col_sel2:
                bear_options = [f"{row['股票代號']} - {row['股票名稱'] if lang=='ZH' else row['股票代號']}" for _, row in bear_df.iterrows()]
                selected_bear = st.selectbox(t["select_bear_label"], options=bear_options, key="select_bear")
            
            if selected_bear:
                stock_id = selected_bear.split(" - ")[0]
                render_kline_chart(stock_id, short_ma, long_ma, "空方", lang=lang)
        else:
            st.info(t["no_bear_msg"])