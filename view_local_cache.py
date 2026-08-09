"""
view_local_cache.py
本地快取資料檢視器 - 重構版支援獨立大盤指數卡片與個股分層檢視

功能：
- 大盤與櫃買指數獨立立體化儀表板 (TAIEX / TPEx)
- 讀取分層 Parquet 目錄 (market_cache/)
- 支援 Tier 分層過濾 (tier1_hot, tier2_warm, tier3_cold)
- 個股 20 日均量排序、搜尋與歷史明細查看
"""

import streamlit as st
import pandas as pd
import os
from pathlib import Path

# ==========================================
# 頁面設定
# ==========================================
st.set_page_config(page_title="本地快取資料檢視器", page_icon="🔍", layout="wide")
st.title("🔍 本地台股快取資料檢視器")
st.caption("⚡ 離線讀取 market_cache/ 分層快取，支援大盤獨立儀表板與個股過濾")

# ==========================================
# 常數設定
# ==========================================
BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "market_cache"
STOCK_NAMES_FILE = BASE_DIR / "stock_names.json"
MARKET_INDICES = ["TAIEX", "TPEx"]

# ==========================================
# 快取載入 (帶 Streamlit 快取)
# ==========================================
@st.cache_data
def load_cache_data():
    """載入分層快取資料"""
    if not CACHE_DIR.exists():
        return None
    
    try:
        df = pd.read_parquet(CACHE_DIR)
        df['Date'] = pd.to_datetime(df['Date'])
        # 強制將 Stock_ID 轉為字串
        df['Stock_ID'] = df['Stock_ID'].astype(str)
        # 讀取端防禦性去重
        df = df.drop_duplicates(subset=['Stock_ID', 'Date'], keep='last')
        return df
    except Exception as e:
        st.error(f"❌ 無法讀取快取: {e}")
        return None

@st.cache_data
def load_stock_names():
    """載入股票名稱對照表"""
    if STOCK_NAMES_FILE.exists():
        try:
            with open(STOCK_NAMES_FILE, "r", encoding="utf-8") as f:
                import json
                return json.load(f)
        except Exception:
            pass
    return {"TAIEX": "加權指數", "TPEx": "櫃買指數"}

# ==========================================
# 載入資料
# ==========================================
df = load_cache_data()
stock_names = load_stock_names()

if df is None:
    st.error("❌ 找不到 `market_cache/` 目錄，請先執行 `python update_market_data.py` 建立快取")
    st.stop()

# ==========================================
# 🏛️ 獨立大盤與櫃買指數儀表板 (立體化卡片)
# ==========================================
st.subheader("🏛️ 市場大盤與櫃買指數總覽")

df_indices = df[df['Stock_ID'].isin(MARKET_INDICES)].copy()

if not df_indices.empty:
    idx_cols = st.columns(len(MARKET_INDICES))
    
    for i, idx_id in enumerate(MARKET_INDICES):
        idx_df = df_indices[df_indices['Stock_ID'] == idx_id].sort_values('Date')
        if idx_df.empty:
            continue
            
        latest = idx_df.iloc[-1]
        prev_close = idx_df.iloc[-2]['Close'] if len(idx_df) >= 2 else latest['Close']
        
        # 計算點數變動與漲跌幅
        change_pts = round(latest['Close'] - prev_close, 2)
        change_pct = round((change_pts / prev_close) * 100, 2) if prev_close != 0 else 0.0
        
        # 成交金額轉換為億元
        latest_money_yi = round(latest['Trading_money'] / 1e8, 2) if 'Trading_money' in latest else round((latest['Volume'] * latest['Close']) / 1e8, 2)
        avg_money_20_yi = round(idx_df['Trading_money'].tail(20).mean() / 1e8, 2) if 'Trading_money' in idx_df.columns else 0.0
        
        idx_name = stock_names.get(idx_id, "大盤指數" if idx_id == "TAIEX" else "櫃買指數")
        
        with idx_cols[i]:
            with st.container(border=True):
                st.markdown(f"### {idx_name} ({idx_id})")
                
                # 主指標：最新點數與漲跌幅
                st.metric(
                    label=f"最新指數 ({latest['Date'].strftime('%Y-%m-%d')})",
                    value=f"{latest['Close']:,.2f} 點",
                    delta=f"{change_pts:+.2f} 點 ({change_pct:+.2f}%)"
                )
                
                # 次要指標欄位
                sub_col1, sub_col2, sub_col3 = st.columns(3)
                with sub_col1:
                    st.caption("當日成交金額")
                    st.markdown(f"**{latest_money_yi:,.2f} 億**")
                with sub_col2:
                    st.caption("20日均額")
                    st.markdown(f"**{avg_money_20_yi:,.2f} 億**")
                with sub_col3:
                    st.caption("當日高低差")
                    spread = round(latest['High'] - latest['Low'], 2)
                    st.markdown(f"**{spread:,.2f} 點**")

st.divider()

# ==========================================
# 側面數據拆分：濾除大盤指數後的純個股資料集
# ==========================================
df_stocks = df[~df['Stock_ID'].isin(MARKET_INDICES)].copy()

# ==========================================
# 側邊欄：搜尋與過濾器
# ==========================================
st.sidebar.header("🔎 個股搜尋與過濾")

# 🔄 清除快取按鈕
if st.sidebar.button("🔄 重新整理 / 清除快取"):
    st.cache_data.clear()
    st.rerun()

# Tier 過濾
tier_options = ["全部"] + sorted(df_stocks['Tier'].unique().tolist())
selected_tier = st.sidebar.selectbox("Tier 分層", options=tier_options)

# 關鍵字搜尋
search_keyword = st.sidebar.text_input("股票代號或名稱關鍵字").strip()

# 套用過濾
filtered_stocks_df = df_stocks.copy()

if selected_tier != "全部":
    filtered_stocks_df = filtered_stocks_df[filtered_stocks_df['Tier'] == selected_tier]

if search_keyword:
    code_match = filtered_stocks_df['Stock_ID'].str.contains(search_keyword, case=False, na=False)
    name_match = filtered_stocks_df['Stock_ID'].map(
        lambda x: search_keyword.lower() in stock_names.get(x, "").lower()
    ).fillna(False)
    filtered_stocks_df = filtered_stocks_df[code_match | name_match]

# ==========================================
# 主畫面：全市場總覽統計 (個股)
# ==========================================
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("總歷史紀錄筆數", f"{len(df_stocks):,}")
with col2:
    st.metric("上市櫃股票檔數", f"{df_stocks['Stock_ID'].nunique():,}")
with col3:
    st.metric("資料日期範圍", f"{df_stocks['Date'].min().strftime('%Y-%m-%d')} ~ {df_stocks['Date'].max().strftime('%Y-%m-%d')}")
with col4:
    st.metric("Tier 分層數", f"{df_stocks['Tier'].nunique()} 層")

st.divider()

# ==========================================
# 快取摘要計算 (純個股)
# ==========================================
def get_stock_summary(df_input):
    """計算個股摘要清單 - 含 20 日均量並依均量降序排列"""
    summary_list = []
    for stock_id, group in df_input.groupby('Stock_ID'):
        name = stock_names.get(str(stock_id), "未知公司")
        sorted_group = group.sort_values('Date')
        latest = sorted_group.iloc[-1]
        
        # 計算近 20 日平均成交量 (張)
        avg_vol_20_sheets = int(sorted_group['Volume'].tail(20).mean() // 1000) if not sorted_group.empty else 0
        
        summary_list.append({
            "股票代號": stock_id,
            "股票名稱": name,
            "Tier": group['Tier'].iloc[0],
            "20日均量(張)": avg_vol_20_sheets,
            "最新日期": latest['Date'].strftime('%Y-%m-%d'),
            "最新收盤價": round(latest['Close'], 2),
            "最新成交量(張)": int(latest['Volume'] // 1000),
            "資料筆數": len(group),
        })
    
    df_summary = pd.DataFrame(summary_list)
    if not df_summary.empty:
        df_summary = df_summary.sort_values(by="20日均量(張)", ascending=False).reset_index(drop=True)
        
    return df_summary

# ==========================================
# 股票清單總覽
# ==========================================
st.subheader(f"📋 個股清單總覽 (按 20 日均量降序排列，共 {len(filtered_stocks_df):,} 筆 / {filtered_stocks_df['Stock_ID'].nunique()} 檔)")

df_summary = get_stock_summary(filtered_stocks_df)
st.dataframe(df_summary, width="stretch", height=400)

st.divider()

# ==========================================
# 單一股票詳細歷史資料
# ==========================================
st.subheader("📊 單一股票詳細歷史交易明細")

stock_options = [f"{row['股票代號']} - {row['股票名稱']}" for _, row in df_summary.iterrows()]

if stock_options:
    selected_option = st.selectbox("請選擇或輸入想要檢視的股票：", options=stock_options)
    selected_id = selected_option.split(" - ")[0]
    
    df_single = df_stocks[df_stocks['Stock_ID'] == selected_id].sort_values('Date', ascending=False).copy()
    
    df_display = df_single.copy()
    df_display['成交量(張)'] = df_display['Volume'] // 1000
    df_display['日期'] = df_display['Date'].dt.strftime('%Y-%m-%d')
    
    display_cols = ['日期', 'Open', 'High', 'Low', 'Close', '成交量(張)', 'Trading_money', 'spread', 'Trading_turnover', 'Tier']
    df_display = df_display[display_cols].rename(columns={
        'Open': '開盤價', 'High': '最高價', 'Low': '最低價', 'Close': '收盤價',
        'Trading_money': '成交金額', 'spread': '漲跌價差', 'Trading_turnover': '換手率'
    })
    
    st.success(f"正在顯示 【{selected_id} - {stock_names.get(selected_id, '未知公司')}】 的歷史交易資料（共 {len(df_display)} 筆）：")
    st.dataframe(df_display, width="stretch", height=400)
    
    csv = df_display.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 下載 CSV",
        data=csv,
        file_name=f"{selected_id}_history.csv",
        mime="text/csv"
    )
else:
    st.warning("⚠️ 找不到符合條件的股票，請調整搜尋條件。")

# ==========================================
# 頁尾資訊
# ==========================================
st.divider()
st.caption("""
**說明**：
- 資料來源：FinMind API (台股日線資料)
- 大盤數據：獨立顯示 TAIEX（加權指數）與 TPEx（櫃買指數）之當日與 20 日均額（億元）
- 快取格式：分層 Parquet (market_cache/)，依 Tier 分區儲存
""")