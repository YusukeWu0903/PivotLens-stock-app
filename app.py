"""
PivotLens - 台股均線轉折選股系統
重構版：模組化架構，純 UI 進入點
"""

import os
import streamlit as st
import pandas as pd

# 專案模組
from src.config_manager import get_strategy_config, get_strategy_names, I18N, get_stock_name_map
from src.strategies import run_market_scanner
from src.charts import render_kline_chart


# ==========================================
# 頁面設定與語言包
# ==========================================
t = I18N["ZH"]
st.set_page_config(page_title=t["page_title"], page_icon="📈", layout="wide")
st.title(t["app_title"])
st.caption(t["app_subtitle"])


# ==========================================
# 核心資料載入 (帶快取)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 讀取新的分層快取目錄
CACHE_DIR = os.path.join(BASE_DIR, "market_cache")


@st.cache_data
def load_market_data():
    """載入市場資料並轉為字典引擎 (O(1) 查詢)"""
    try:
        # 讀取分層 parquet 目錄
        df = pd.read_parquet(CACHE_DIR)
        df["Date"] = pd.to_datetime(df["Date"])

        # 轉為 {stock_id: DataFrame} 字典
        grouped = df.groupby("Stock_ID")
        stock_dict = {
            stock_id: group.set_index("Date").sort_index()
            for stock_id, group in grouped
        }
        return stock_dict
    except Exception as e:
        st.error(f"❌ 無法讀取本地快取檔，請確認 market_cache/ 目錄是否存在。錯誤: {e}")
        return {}


# 載入資料
stock_dict = load_market_data()

if not stock_dict:
    st.warning(
        "⚠️ 目前讀取不到市場數據，請確認 market_cache/ 目錄已成功建立。"
    )
    st.stop()

stock_name_map = get_stock_name_map()


def get_stock_name(stock_id):
    return stock_name_map.get(str(stock_id), f"{stock_id}")


# ==========================================
# 掃描器包裝函式 (帶快取)
# ==========================================
@st.cache_data
def run_scanner_cached(_stock_dict, strategy_name):  # 👈 在 stock_dict 前加上底線
    """只快取「基礎大掃描」的結果，與 UI 條件脫鉤"""
    return run_market_scanner(
        stock_dict=_stock_dict,
        strategy_name=strategy_name
    )


# ==========================================
# 側邊欄 UI - 策略選擇與參數設定
# ==========================================
st.sidebar.header("🎯 策略選擇")

# 1. 交易方向單選按鈕
trade_direction = st.sidebar.radio(
    "交易方向",
    options=["做多 (金叉買進)", "做空 (死叉賣出)"],
    index=0,
    horizontal=True,
)
is_short = "做空" in trade_direction

# 2. 依據多空方向動態載入策略名稱
strategy_names = get_strategy_names(is_short=is_short)
strategy_name = st.sidebar.selectbox(
    "選擇選股模式",
    options=strategy_names,
    index=0,
)

st.sidebar.divider()
st.sidebar.subheader("⚙️ 選股池設定")

filter_high_vol = st.sidebar.checkbox("僅篩選 20 日均量 ≥ 1000 張 (預設)", value=True)
min_vol = 1000 if filter_high_vol else 0

exclude_emerging = st.sidebar.checkbox("排除興櫃與創櫃板 (預設)", value=True)

price_range = st.sidebar.selectbox(
    "股價區間",
    options=["高價股(100元以上)", "低價股(100元以下)"],
    index=0,
)

# 3. 依多空調整進場型態文案 (純粹二選一雙引擎)
if not is_short:
    pattern_label = "買點型態"
    pattern_options = ["拉回支撐 (量縮潛伏)", "強勢創高 (帶量突破)"]
    pattern_help = "【拉回支撐】買在主力防守點：要求今日量縮，且股價回測長均線 (0~8%) 守穩不破。\n【強勢創高】追擊主升段：要求帶量實質過前高 (20日最高)，且尾盤強勢收高。"
else:
    pattern_label = "賣點/放空型態"
    pattern_options = ["反彈遇壓 (量縮潛伏)", "弱勢破底 (帶量下殺)"]
    pattern_help = "【反彈遇壓】空在壓力防守點：要求今日量縮，且股價反彈至長均線 (0~8%) 受阻不破。\n【弱勢破底】追擊主跌段：要求帶量實質破前低 (20日最低)，且尾盤弱勢收低。"

entry_pattern = st.sidebar.selectbox(
    pattern_label,
    options=pattern_options,
    index=0,
    help=pattern_help,
)

# ==========================================
# 執行掃描與極速記憶體過濾
# ==========================================
with st.spinner(f"正在計算【{strategy_name}】全市場指標 (每日初次或切換策略時較久)..."):
    # 這裡只傳入策略名稱，提取已算好的全市場 DataFrame
    raw_scan_df = run_scanner_cached(_stock_dict=stock_dict, strategy_name=strategy_name) # 👈 加上 _stock_dict=

# ⚡ 開始零延遲 Pandas 記憶體過濾
if raw_scan_df is not None and not raw_scan_df.empty:
    df_filtered = raw_scan_df.copy()

    # 1. 流動性與價位過濾
    df_filtered = df_filtered[df_filtered["20日均量(張)"] >= min_vol]
    if price_range == "高價股(100元以上)":
        df_filtered = df_filtered[df_filtered["最新收盤價"] >= 100]
    else:
        df_filtered = df_filtered[df_filtered["最新收盤價"] < 100]
    
    # 2. 興櫃過濾
    if exclude_emerging:
        df_filtered = df_filtered[~df_filtered["Is_Emerging"]]

    # 3. 雙引擎型態動態過濾 (二選一極簡邏輯)
    if "強勢創高" in entry_pattern or "弱勢破底" in entry_pattern:
        # 🚀 引擎二：動能追擊 (實質過前高/前低 + 收高/收低 + 出量)
        df_filtered = df_filtered[
            df_filtered["Support_Holds"] & 
            df_filtered["Momentum_Breakout"] & 
            df_filtered["Vol_Surge"]
        ]
    else:
        # 🛡️ 引擎一：拉回支撐 / 反彈遇壓 (統一 0% ~ 8% 區間 + 守穩 + 量縮)
        df_filtered = df_filtered[
            df_filtered["Support_Holds"] & 
            df_filtered["Vol_Shrink"] & 
            (df_filtered["Bias_Rate"] >= 0.00) & 
            (df_filtered["Bias_Rate"] <= 0.08)
        ]

    scan_df = df_filtered
else:
    scan_df = pd.DataFrame()

st.divider()

# ==========================================
# 顯示掃描結果與說明卡片
# ==========================================
if scan_df is not None and not scan_df.empty:
    cfg = get_strategy_config(strategy_name)

    vol_text = "≥ **1000** 張 (主流流動性)" if filter_high_vol else "**包含 1000 張以下標的** (全市場)"
    price_text = "≥ **100** 元 (高價股)" if price_range == "高價股(100元以上)" else "< **100** 元 (低價股)"
    market_text = "上市/上櫃" if exclude_emerging else "全市場 (含興櫃/創櫃)"
    curr_n_days = cfg["n_days"]
    tf_unit = "周" if cfg["timeframe"] == "W" else "日"

    st.subheader(f"📊 掃描結果：{strategy_name}")
    st.info("💡 **雙引擎量價策略與洗盤防禦說明**："
            "" + chr(10) + chr(10) + ""
            "* **核心邏輯**：" + cfg['desc'] + ""
            "" + chr(10) + chr(10) + ""
            "* **潛伏引擎 (拉回支撐 / 反彈遇壓)**：買在主力防守點。**量縮洗盤**，**股價回測均線 0~8% 內且守穩**，剔除爆量貫破支撐的接刀股。"
            "" + chr(10) + chr(10) + ""
            "* **動能引擎 (強勢創高 / 弱勢破底)**：追擊主升/主跌段。**突破過往 20 日高低點** + **K棒強勢收高/收低** + **帶量發動**，剔除假創高與高檔甩轎盤。"
            "" + chr(10) + chr(10) + ""
            "* **過濾條件**：20 日均量 " + vol_text + " | 股價 " + price_text + " | 排除 20 日內頻繁交叉 3 次以上之均線糾結橫盤股。")

    new_count = scan_df["Is_New"].sum()
    st.caption(
        f"共掃描出 **{len(scan_df)}** 檔標的（其中 **{new_count}** 檔為近 3 天內剛交叉的 **NEW** 標的）"
    )

    # 排序：NEW 優先，再按距長均線距離
    scan_df = scan_df.sort_values(by=["Is_New", "距長均線(%)"], ascending=[False, True])

    st.markdown(f"##### {t['select_stock_prompt']}")

    options = [
        f"{row['股票代號']} - {get_stock_name(row['股票代號'])}{' (NEW)' if row['Is_New'] else ''}"
        for _, row in scan_df.iterrows()
    ]

    selected_stock = st.selectbox(
        "請選擇股票查看分析與圖表：",
        options=options,
        key="selected_stock",
    )

    if selected_stock:
        stock_id = selected_stock.split(" - ")[0].strip()
        render_kline_chart(stock_id, strategy_name, stock_dict, stock_name_map, t)

else:
    st.info("ℹ️ 當前條件下未找到符合策略之股票，請嘗試切換其他股價區間或買點型態。")