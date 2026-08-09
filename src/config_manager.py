"""
src/config_manager.py
策略設定管理 + 多國語言 (i18n) + 離線名稱對照

本模組整合原先分散在 config.py 的：
- STRATEGY_CONFIG（策略參數）
- I18N（多國語言字典）
- get_stock_name_map()（純離線讀取股票名稱）

依 ARCHITECTURE Rule 2，UI 層嚴禁發 API 請求，故股票名稱一律離線讀取，
由資料管線 update_market_data.py 預先生成 stock_names.json。
"""

import json
import os

# ==========================================
# 策略設定字典 (未來可移至外部配置檔)
# ==========================================
STRATEGY_CONFIG = {
    "短多 (日K 5MA + 20MA)": {
        "timeframe": "D",
        "short_ma": 5,
        "long_ma": 20,
        "n_days": 5,
        "desc": "適合短線動能追蹤：抓取日線 5MA 近 5 日黃金交叉 20MA 且股價回測月線附近之標的。",
    },
    "中多 (日K 20MA + 60MA)": {
        "timeframe": "D",
        "short_ma": 20,
        "long_ma": 60,
        "n_days": 10,
        "desc": "適合波段佈局：抓取日線 20MA 近 10 日黃金交叉 60MA（季線）且月線斜率向上之標的。",
    },
    "長多 (周K 13MA + 52MA)": {
        "timeframe": "W",
        "short_ma": 13,
        "long_ma": 52,
        "n_days": 20,
        "desc": "適合大趨勢保護：抓取周線 13MA 近 20 周黃金交叉 52MA（一年）之長線趨勢發動股。",
    },
}


def get_strategy_config(strategy_name: str | None = None) -> dict:
    """
    取得策略設定。

    Args:
        strategy_name: 策略名稱，若為 None 則回傳所有策略設定

    Returns:
        dict: 策略設定字典
    """
    if strategy_name is None:
        return STRATEGY_CONFIG
    return STRATEGY_CONFIG.get(strategy_name, {})


def get_strategy_names() -> list[str]:
    """取得所有策略名稱列表"""
    return list(STRATEGY_CONFIG.keys())


def validate_strategy_params(params: dict) -> bool:
    """
    驗證策略參數是否完整

    Args:
        params: 策略參數字典

    Returns:
        bool: 參數是否有效
    """
    required_keys = {"timeframe", "short_ma", "long_ma", "n_days"}
    return all(key in params for key in required_keys)


# ==========================================
# 多國語言 (i18n) 全局字典對照表
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
        "active_filters": "📌 **當前篩選條件：** ① 近 20 日均量 $\\ge$ **{vol}** 張且股價 $\\ge$ **{price}** 元 ｜ ② 近 **{days}** 天內曾發生 **{short}MA** 與 **{long}MA** 交叉 ｜ ③ 當前股價距 **{long}MA** 介於 **$\\pm${pct}%** 內",
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
        "active_filters": "📌 **Active Filters:** ① 20D Avg Vol $\\ge$ **{vol}** sheets & Price $\\ge$ **{price}** TWD ｜ ② **{short}MA** & **{long}MA** crossover within **{days}** days ｜ ③ Price within **$\\pm${pct}%** of **{long}MA**",
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


def get_stock_name_map() -> dict:
    """純離線讀取股票名稱，絕對禁止發起 API 請求 (ARCHITECTURE Rule 2)"""
    # 根據 src/config_manager.py 的位置，指回根目錄的 stock_names.json
    json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "stock_names.json")
    stock_map = {}
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                stock_map = json.load(f)
        except Exception as e:
            print(f"⚠️ 讀取 stock_names.json 失敗: {e}")
    return stock_map