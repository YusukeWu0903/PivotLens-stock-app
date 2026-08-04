import streamlit as st
import pandas as pd
import json
import os

# 頁面基本設定
st.set_page_config(page_title="本地快取資料檢視器", page_icon="🔍", layout="wide")
st.title("🔍 本地台股快取資料檢視器")
st.caption("⚡ 離線讀取 taiwan_market_cache.parquet，秒級查詢所有已快取的股票歷史數據與成交量。")

# 1. 載入快取與名稱對照
@st.cache_data
def load_cache_data():
    if not os.path.exists("taiwan_market_cache.parquet") or not os.path.exists("stock_names.json"):
        return None, {}
    
    df = pd.read_parquet("taiwan_market_cache.parquet")
    df['Date'] = pd.to_datetime(df['Date'])
    
    with open("stock_names.json", "r", encoding="utf-8") as f:
        stock_map = json.load(f)
        
    return df, stock_map

df_all, stock_map = load_cache_data()

if df_all is None:
    st.error("❌ 找不到 `taiwan_market_cache.parquet` 或 `stock_names.json`，請確認檔案是否存在於專案根目錄！")
else:
    # 2. 整理每一檔股票的摘要清單（供總覽與搜尋）
    @st.cache_data
    def get_stock_summary(_df):
        summary_list = []
        grouped = _df.groupby('Stock_ID')
        for stock_id, group in grouped:
            name = stock_map.get(str(stock_id), "未知公司")
            latest_date = group['Date'].max().strftime('%Y-%m-%d')
            total_records = len(group)
            latest_close = group.sort_values('Date')['Close'].iloc[-1]
            latest_vol = group.sort_values('Date')['Volume'].iloc[-1]
            # 轉換為張數
            latest_vol_sheets = int(latest_vol // 1000)
            
            summary_list.append({
                "股票代號": stock_id,
                "股票名稱": name,
                "最新日期": latest_date,
                "最新收盤價": round(latest_close, 2),
                "最新成交量(張)": latest_vol_sheets,
                "資料筆數": total_records
            })
        return pd.DataFrame(summary_list)

    df_summary = get_stock_summary(df_all)

    # 3. 側邊欄：搜尋與篩選器
    st.sidebar.header("🔎 搜尋與過濾")
    search_keyword = st.sidebar.text_input("輸入股票代號或名稱關鍵字 (例如: 2330 或 台積電)").strip()
    
    # 根據關鍵字過濾摘要清單
    if search_keyword:
        filtered_summary = df_summary[
            df_summary['股票代號'].str.contains(search_keyword, case=False, na=False) |
            df_summary['股票名稱'].str.contains(search_keyword, case=False, na=False)
        ]
    else:
        filtered_summary = df_summary

    # 4. 主畫面呈現：先列出所有資料清單
    st.markdown(f"### 📋 已快取股票總覽清單 (共收錄 {len(df_summary)} 檔有效標的)")
    st.dataframe(filtered_summary, width="stretch", height=300)

    st.divider()

    # 5. 下拉選單：選擇特定股票查看詳細歷史數據
    st.markdown("### 📊 單一股票詳細歷史交易明細")
    
    # 下拉選項格式：「2330 - 台積電」
    stock_options = [f"{row['股票代號']} - {row['股票名稱']}" for _, row in filtered_summary.iterrows()]
    
    if stock_options:
        selected_option = st.selectbox("請選擇或輸入想要檢視的股票：", options=stock_options)
        selected_id = selected_option.split(" - ")[0]
        
        # 抓取該股票的完整歷史資料
        df_single = df_all[df_all['Stock_ID'] == selected_id].sort_values('Date', ascending=False).copy()
        
        # 轉換成交量單位供顯示
        df_single['成交量(張)'] = df_single['Volume'] // 1000
        df_single['日期'] = df_single['Date'].dt.strftime('%Y-%m-%d')
        
        # 挑選要顯示的欄位
        display_cols = ['日期', 'Open', 'High', 'Low', 'Close', '成交量(張)']
        df_display = df_single[display_cols].rename(columns={
            'Open': '開盤價', 'High': '最高價', 'Low': '最低價', 'Close': '收盤價'
        })
        
        st.success(f"正在顯示 【{selected_option}】 的歷史交易資料（共 {len(df_display)} 筆）：")
        st.dataframe(df_display, width="stretch", height=400)
    else:
        st.warning("⚠️ 找不到符合搜尋條件的股票，請重新輸入關鍵字。")