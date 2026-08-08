"""
view_local_cache.py
本地快取資料檢視器 - 重構版支援分層快取 (market_cache/)

功能：
- 讀取分層 Parquet 目錄 (market_cache/)
- 支援 Tier 分層過濾 (tier1_hot, tier2_warm, tier3_cold)
- 股票搜尋、篩選、詳細歷史資料查看
- 統計摘要與快取健康度檢查
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
st.caption("⚡ 離線讀取 market_cache/ 分層快取，支援 Tier 分層過濾與股票搜尋")

# ==========================================
# 常數設定
# ==========================================
BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "market_cache"
STOCK_NAMES_FILE = BASE_DIR / "stock_names.json"

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
    return {}

# ==========================================
# 載入資料
# ==========================================
df = load_cache_data()
stock_names = load_stock_names()

if df is None:
    st.error("❌ 找不到 `market_cache/` 目錄，請先執行 `python update_market_data.py` 建立快取")
    st.stop()

# ==========================================
# 側邊欄：搜尋與過濾器
# ==========================================
st.sidebar.header("🔎 搜尋與過濾")

# Tier 過濾
tier_options = ["全部"] + sorted(df['Tier'].unique().tolist())
selected_tier = st.sidebar.selectbox("Tier 分層", options=tier_options)

# 關鍵字搜尋
search_keyword = st.sidebar.text_input("股票代號或名稱關鍵字").strip()

# ==========================================
# 套用過濾
# ==========================================
filtered_df = df.copy()

if selected_tier != "全部":
    filtered_df = filtered_df[filtered_df['Tier'] == selected_tier]

if search_keyword:
    # 代號搜尋
    code_match = filtered_df['Stock_ID'].astype(str).str.contains(search_keyword, case=False, na=False)
    # 名稱搜尋
    name_match = filtered_df['Stock_ID'].astype(str).map(
        lambda x: search_keyword.lower() in stock_names.get(x, "").lower()
    ).fillna(False)
    filtered_df = filtered_df[code_match | name_match]

# ==========================================
# 主畫面：總覽統計
# ==========================================
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("總筆數", f"{len(df):,}")
with col2:
    st.metric("股票檔數", f"{df['Stock_ID'].nunique():,}")
with col3:
    st.metric("日期範圍", f"{df['Date'].min().strftime('%Y-%m-%d')} ~ {df['Date'].max().strftime('%Y-%m-%d')}")
with col4:
    st.metric("Tier 分層", f"{df['Tier'].nunique()} 層")

st.divider()

# ==========================================
# Tier 分層統計
# ==========================================
st.subheader("📊 Tier 分層統計")
tier_stats = df.groupby('Tier').agg(
    筆數=('Stock_ID', 'count'),
    檔數=('Stock_ID', 'nunique'),
    最早日期=('Date', 'min'),
    最新日期=('Date', 'max')
).reset_index()

st.dataframe(tier_stats, width="stretch")

# Tier 筆數長條圖
tier_counts = df['Tier'].value_counts().sort_index()
st.bar_chart(tier_counts)

st.divider()

# ==========================================
# 股票清單總覽
# ==========================================
st.subheader(f"📋 股票清單總覽 (共 {len(filtered_df):,} 筆 / {filtered_df['Stock_ID'].nunique()} 檔)")

# 建立摘要清單
@st.cache_data
def get_stock_summary(_df):
    summary_list = []
    for stock_id, group in _df.groupby('Stock_ID'):
        name = stock_names.get(str(stock_id), "未知公司")
        latest = group.sort_values('Date').iloc[-1]
        summary_list.append({
            "股票代號": stock_id,
            "股票名稱": name,
            "Tier": group['Tier'].iloc[0],
            "最新日期": latest['Date'].strftime('%Y-%m-%d'),
            "最新收盤價": round(latest['Close'], 2),
            "最新成交量(張)": int(latest['Volume'] // 1000),
            "資料筆數": len(group),
        })
    return pd.DataFrame(summary_list)

df_summary = get_stock_summary(filtered_df)

# 顯示清單
st.dataframe(df_summary, width="stretch", height=400)

st.divider()

# ==========================================
# 單一股票詳細歷史資料
# ==========================================
st.subheader("📊 單一股票詳細歷史交易明細")

# 下拉選單選擇股票
stock_options = [f"{row['股票代號']} - {row['股票名稱']}" for _, row in df_summary.iterrows()]

if stock_options:
    selected_option = st.selectbox("請選擇或輸入想要檢視的股票：", options=stock_options)
    selected_id = selected_option.split(" - ")[0]
    
    # 取得該股票完整歷史資料
    df_single = df[df['Stock_ID'] == selected_id].sort_values('Date', ascending=False).copy()
    
    # 單位轉換
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
    
    # 下載按鈕
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
- 快取格式：分層 Parquet (market_cache/)，依 Tier 分區儲存
- Tier 分層：tier1_hot (熱門/大盤) > tier2_warm (中型) > tier3_cold (冷門)
- 興櫃/創櫃過濾：依 FinMind `type=emerging` 自動更新 `emerging_stocks.txt`
""")