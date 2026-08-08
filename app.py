"""
PivotLens - 台股均線轉折選股系統
重構版：模組化架構，純 UI 進入點
"""

import os
import streamlit as st
import pandas as pd

# 專案模組
from src.config_manager import get_strategy_config, get_strategy_names
from src.strategies import run_market_scanner
from src.charts import render_kline_chart
from config import I18N, get_stock_name_map


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
def run_scanner_cached(
    _stock_dict, strategy_name, entry_pattern, min_volume_sheets, price_range, exclude_emerging, new_tag_days
):
    """包裝 run_market_scanner 以便套用 @st.cache_data"""
    return run_market_scanner(
        _stock_dict,
        strategy_name,
        entry_pattern,
        min_volume_sheets,
        price_range,
        exclude_emerging,
        new_tag_days,
    )


# ==========================================
# 側邊欄 UI - 策略選擇與參數設定
# ==========================================
st.sidebar.header("🎯 策略選擇")

strategy_names = get_strategy_names()
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

entry_pattern = st.sidebar.selectbox(
    "買點型態",
    options=["貼近均線 (強效支撐)", "適度回測 (標準進場)", "允許追高 (強勢動能)"],
    index=0,
    help="貼近均線代表股價剛拉回長均線支撐附近，進場風險最低。",
)


# ==========================================
# 執行掃描
# ==========================================
with st.spinner(f"正在以【{strategy_name}】模式掃描全台股..."):
    scan_df = run_scanner_cached(
        stock_dict,
        strategy_name,
        entry_pattern,
        min_vol,
        price_range,
        exclude_emerging,
        new_tag_days=3,
    )

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
    st.info("💡 **篩選邏輯說明**："
            "" + chr(10) + chr(10) + ""
            "* **核心策略**：" + cfg['desc'] + ""
            "" + chr(10) + chr(10) + ""
            "* **過濾條件**：市場別：**" + market_text + "** | 20 日均量 " + vol_text + " | 股價 " + price_text + " | "
            "近 **" + str(curr_n_days) + "** 根 " + tf_unit + "K 棒內交叉 | 買點位置：**" + entry_pattern + "**"
            "" + chr(10) + chr(10) + ""
            "* **自動洗盤防禦**：排除近 20 根 K 棒交叉 3 次以上之均線糾結橫盤股。")

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