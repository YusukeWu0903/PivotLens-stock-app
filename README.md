# PivotLens - 台股均線轉折選股系統

> **專案定位**：專為台灣股市設計的均線轉折自動選股系統，採用雙引擎量價策略，內建流動性過濾、洗盤防禦與 K 線診斷，支援 Streamlit 雲端部署與 GitHub Actions 無人值守每日自動更新。

---

## 🎯 核心特色

| 功能 | 說明 |
|------|------|
| **🎯 雙引擎量價策略** | 「潛伏引擎」(拉回支撐/反彈遇壓) +「動能引擎」(強勢創高/弱勢破底) 兩大核心邏輯 |
| **🛡️ 三層防禦體系** | 流動性門檻 → 洗盤量縮過濾 → K 棒形態驗證，層層把關 |
| **📊 即時 K 線診斷** | 自動判讀量價關係，輸出中文技術面分析卡片 |
| **⚡ 極速記憶體過濾** | 策略計算與 UI 過濾分離，切換條件 0 秒響應 |
| **🤖 無人值守每日更新** | GitHub Actions 4 輪排程 (17:35/19:35/21:35/23:35)，自動更新 2,300+ 檔股票 |
| **🛡️ 智慧黑名單管理** | 永久/暫時/觀察三級分級，官方下市自動偵測，暫時停牌不誤判 |

---

## 🏗️ 系統架構

```
PivotLens/
├── app.py                          # Streamlit 進入點 (純 UI)
├── update_market_data.py           # 每日資料更新腳本 (GitHub Actions 執行)
├── check_stock_diff.py             # 政府官方清單比對工具
├── requirements.txt                # 依賴清單
├── .github/workflows/update_data.yml  # GitHub Actions 排程設定
│
├── src/
│   ├── config_manager.py           # 策略設定 + 多國語言 + 離線名稱
│   ├── strategies.py               # 核心掃描邏輯 (純 Pandas，零 API)
│   └── charts.py                   # K 線圖渲染 (Plotly)
│
├── tests/
│   └── test_strategies.py          # 18 個單元測試 (pytest)
│
├── market_cache/                   # 分層 Parquet 快取 (Tier 1/2/3)
├── blacklist.txt                   # 永久黑名單 (下市/終止上市)
├── temp_blacklist.txt              # 暫時黑名單 (30 天自動過期)
├── watchlist.txt                   # 觀察名單 (暫時停牌/無成交)
├── emerging_stocks.txt             # 興櫃股票清單 (每日自動更新)
├── stock_names.json                # 股票代號↔名稱對照 (離線)
├── requirements.txt
└── README.md
```

---

## 🔧 核心策略邏輯

### 雙引擎架構

| 引擎 | 適用場景 | 核心條件 |
|------|----------|----------|
| **🛡️ 潛伏引擎**<br>拉回支撐 / 反彈遇壓 | 尋找主力防守點 | 1. 乖離率 0%~8%<br>2. 股價守穩長均線<br>3. **量縮**洗盤 (成交量 < 20日均量) |
| **🚀 動能引擎**<br>強勢創高 / 弱勢破底 | 追擊主升/主跌段 | 1. **實質突破** 20日高低點<br>2. K 棒**收高/收低** (實體佔比)<br>4. **出量**發動 (成交量 > 20日均量 1.2倍) |

### 策略參數表

| 策略 | 週期 | 短均線 | 長均線 | 有效窗口 | 適用場景 |
|------|------|--------|--------|----------|----------|
| **短多** | 日 K | 5MA | 20MA | 10 日 | 短線轉折 |
| **中多** | 日 K | 20MA | 60MA | 20 日 | 波段佈局 |
| **長多** | 週 K | 13MA | 52MA | 20 日 | 大趨勢 |
| **短空 / 中空 / 長空** | 同左 | 同左 | 同左 | 同左 | 空方對應 |

---

## 🚀 快速開始

### 本地開發環境

```bash
# 1. 複製專案
git clone https://github.com/YusukeWu0903/PivotLens-stock-app.git
cd PivotLens-stock-app

# 2. 建立虛擬環境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安裝依賴
pip install -r requirements.txt

# 4. 設定環境變數
cp .env.example .env
# 編輯 .env 填入 FINMIND_TOKEN

# 5. 執行 Streamlit
streamlit run app.py
```

### 環境變數設定 (`.env`)

```env
FINMIND_TOKEN=your_finmind_api_token
UPDATE_MAX_WORKERS=2          # 最大並發數 (預設 2)
UPDATE_MAX_STOCKS_PER_RUN=582 # 單輪最大更新檔數 (預設 582)
UPDATE_REQUEST_DELAY=3.0      # 請求間隔秒數 (預設 3.0s)
UPDATE_API_TIMEOUT=30         # 單支 API 超時秒數 (預設 30s)
```

---

## 🤖 GitHub Actions 自動化部署

### 排程時間 (台灣時間)

| 輪次 | UTC 時間 | 台灣時間 | 更新範圍 |
|------|----------|----------|----------|
| 第 1 輪 | 09:35 | **17:35** | Rank 1~582 (大盤指數 + 熱門股) |
| 第 2 輮 | 11:35 | **19:35** | Rank 583~1164 |
| 第 3 輪 | 13:35 | **21:35** | Rank 1165~1746 |
| 第 4 輪 | 15:35 | **23:35** | Rank 1747~2328 (補漏) |

### 部署步驟

1. **Fork/Clone 專案**到你的 GitHub
2. **Settings → Secrets → Actions** 新增：
   - `FINMIND_TOKEN`：你的 FinMind API Token
3. **啟用 Actions**：Settings → Actions → General → Allow all actions
4. **手動觸發測試**：Actions → Auto Update Market Data → Run workflow

### 自動化流程

```mermaid
graph TD
    A[GitHub Actions 排程觸發] --> B[Checkout 程式碼]
    B --> C[安裝依賴 + 登入 FinMind]
    C --> D[下載 582 檔股票日線]
    D --> E[計算技術指標 + Tier 分層]
    E --> F[分區寫入 Parquet (Tier 1/2/3)]
    F --> G[更新 emerging_stocks.txt]
    G --> H[更新 stock_names.json]
    H --> I[Git Commit & Push 回 main]
    I --> J[Streamlit 雲端自動重新部署]
```

---

## 📦 資料快取架構

### 三層分層設計

| Tier | 排名範圍 | 更新頻率 | 典型股票 |
|------|----------|----------|----------|
| **Tier 1 (Hot)** | Rank 1~552 | 每日 | 大盤指數、台積電、聯發科、熱門權值股 |
| **Tier 2 (Warm)** | 553~1102 | 每日 | 中型股、題材股 |
| **Tier 3 (Cold)** | 1103~ | 每日 | 低流動性、興櫃/創櫃 |

### 快取特色

- **分區寫入**：`partition_cols=['Tier']` 自動建立三層目錄
- **每輪重新排名**：避免歷史殘留導致 Tier 膨脹
- **檔案更新即失效**：`os.walk` 遞迴掃描 mtime，Streamlit 秒級感知
- **斷點續傳**：每 110 檔中途存檔 `market_cache_checkpoint.parquet`

---

## 🛡️ 防禦機制詳解

### 1. API 保護 (四層)

| 層級 | 機制 | 參數 |
|------|------|------|
| L1 參數 | 低併發 + 延遲 | `MAX_WORKERS=2`, `REQUEST_DELAY=3.0s` |
| L2 執行 | 超時保護 + 熔斷器 | `API_TIMEOUT=30s`, 連續 3 失敗→暫停 60s |
| L3 輸出 | 詳細錯誤分類 | HTTPError/Timeout/空資料分離記錄 |
| L4 排程 | 4 輪分散 | 間隔 2 小時，單輪 29 分鐘 < 30min timeout |

### 2. 黑名單三級分級

| 等級 | 檔案 | 過期 | 適用對象 |
|------|------|------|----------|
| **L1 永久** | `blacklist.txt` | 永不 | 官方確認下市/終止上市 |
| **L2 暫時** | `temp_blacklist.txt` | 30 天 | 連續失敗、異常股票 |
| **L3 觀察** | `watchlist.txt` | 人工審核 | 暫時停牌、無成交 |

### 3. 資料完整性

- **官方下市偵測**：`check_stock_diff.py` 每日對比政府 OpenAPI
- **興櫃自動更新**：每日抓取 FinMind `type=emerging`
- **分區重寫前清空**：`shutil.rmtree(CACHE_DIR)` 防止碎片檔
- **去重保護**：`drop_duplicates(subset=['Stock_ID','Date'], keep='last')`

---

## 🧪 測試與驗證

### 執行測試

```bash
# 執行所有單元測試
pytest tests/ -v

# 執行特定測試
pytest tests/test_strategies.py::test_entry_pattern_mutual_exclusive -v
```

### 測試覆蓋

| 測試項目 | 數量 | 覆蓋範圍 |
|----------|------|----------|
| 策略互斥邊界 | 3 | 0%/2%/4%/6%/8% 邊界值 |
| 均線計算 | 3 | MA 計算、金叉/死叉判定 |
| 乖離率計算 | 2 | Bias_Rate 公式驗證 |
| 交叉有效窗口 | 3 | n_days 邊界 (含周 K) |
| 勝率計算 | 2 | 5/10/20 日勝率 |
| 冷啟動 | 1 | 無歷史資料時排序 |
| 興櫃過濾 | 2 | 前綴 74/75/76/77 + 官方清單 |

---

## 📁 關鍵檔案說明

| 檔案 | 用途 | 更新頻率 |
|------|------|----------|
| `market_cache/` | 分層 Parquet 快取 | 每日 4 輪 |
| `blacklist.txt` | 永久黑名單 | 人工/官方偵測 |
| `temp_blacklist.txt` | 暫時黑名單 | 30 天自動過期 |
| `watchlist.txt` | 觀察名單 | 每輪更新 |
| `emerging_stocks.txt` | 興櫃清單 | 每日更新 |
| `stock_names.json` | 代號↔名稱 | 每日更新 |
| `stock_names.json` | 代號↔名稱 | 每日更新 |

---

## 📝 開發規範

### 程式碼風格

- **類型提示**：所有函數必須有 type hints
- **文件字串**：Google 風格 docstring
- **錯誤處理**：具體例外類型，禁止裸露 `except:`

### Git 規範

```bash
# Commit message 格式
type: 簡短描述

- 詳細說明
- 影響範圍

# type: feat/fix/perf/docs/refactor/ci/chore
```

### 命名規範

| 類型 | 規範 | 範例 |
|------|------|------|
| 變數/函數 | snake_case | `max_workers`, `run_market_scanner` |
| 類別 | PascalCase | `DataLoader`, `CircuitBreaker` |
| 常數 | UPPER_SNAKE | `MAX_WORKERS`, `API_TIMEOUT` |
| 檔案 | snake_case.py | `update_market_data.py` |

---

## 🐛 常見問題排查

| 現象 | 可能原因 | 解決方案 |
|------|----------|----------|
| Actions 熔斷器頻繁觸發 | FinMind 限流 | 確認 `REQUEST_DELAY=3.0`, `MAX_WORKERS=2` |
| 本地無資料顯示 | `market_cache/` 缺失 | 手動執行 `python update_market_data.py` |
| Streamlit 重跑慢 | 快取失效 | 確認 `@st.cache_data` key 正確 |
| 興櫃股票未過濾 | `emerging_stocks.txt` 過期 | 手動執行更新腳本 |
| 熔斷器誤觸發 | 空資料計入失敗 | 確認版本 ≥ `408397c` |

---

## 📄 授權條款

MIT License - 詳見 [LICENSE](LICENSE)

---

## 🙏 致謝

- **FinMind** 提供優質台灣股市 API
- **台灣證券交易所 / 櫃買中心** 開放政府資料 API
- **Streamlit** 提供優雅的資料應用框架
- **Plotly** 提供互動式圖表庫

---

## 📞 聯絡方式

- **專案維護者**：[@YusukeWu0903](https://github.com/YusukeWu0903)
- **Issue 回報**：[GitHub Issues](https://github.com/YusukeWu0903/PivotLens-stock-app/issues)

---

> **免責聲明**：本系統僅供技術研究與學習參考，不構成投資建議。股市有風險，投資需謹慎。