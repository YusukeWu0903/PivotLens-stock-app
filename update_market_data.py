import os
import time
import json
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from FinMind.data import DataLoader
import requests

load_dotenv()
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 使用分層儲存目錄，取代單一 parquet 檔案 (ARCHITECTURE 1.1)
CACHE_DIR = os.path.join(BASE_DIR, "market_cache")
# 中途存檔使用臨時檔案名稱，避免與分區目錄衝突 (ARCHITECTURE 1.2)
CHECKPOINT_FILE = os.path.join(BASE_DIR, "market_cache_checkpoint.parquet")
BLACKLIST_FILE = os.path.join(BASE_DIR, "blacklist.txt")
# 興櫃股票清單（由 FinMind type=emerging 自動產生） (ARCHITECTURE 1.3)
EMERGING_LIST_FILE = os.path.join(BASE_DIR, "emerging_stocks.txt")
# 股票名稱對照表（由資料管線預先生成，供 UI 層離線讀取）
STOCK_NAMES_FILE = os.path.join(BASE_DIR, "stock_names.json")

# 大盤指數代碼 (FinMind API 使用的代碼)
MARKET_INDICES = ["TAIEX", "TPEx"]

# 可配置的多執行緒數量（預設 5，可透過環境變數覆蓋）
MAX_WORKERS = int(os.getenv("UPDATE_MAX_WORKERS", "5"))
# 單次執行最大更新檔數：582 = 2 檔大盤指數 + 580 檔熱門股 (約 2300 檔 / 4 批次)
MAX_STOCKS_PER_RUN = int(os.getenv("UPDATE_MAX_STOCKS_PER_RUN", "582"))
# 中途存檔間隔 (ARCHITECTURE 1.2：每 110 筆)
CHECKPOINT_INTERVAL = int(os.getenv("UPDATE_CHECKPOINT_INTERVAL", "110"))
# 請求間隔（秒）
REQUEST_DELAY = float(os.getenv("UPDATE_REQUEST_DELAY", "1.0"))


def fetch_single_stock_daily(dl: DataLoader, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """
    使用共用的 DataLoader 實例抓取單一股票日線資料。
    回傳 DataFrame 或 None（失敗）。
    """
    try:
        df = dl.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if not df.empty:
            return df
    except requests.exceptions.Timeout:
        print(f"  ⚠️ {stock_id}: 請求逾時")
    except requests.exceptions.RequestException as e:
        print(f"  ⚠️ {stock_id}: 網路請求錯誤 - {e}")
    except Exception as e:
        print(f"  ⚠️ {stock_id}: 未預期錯誤 - {e}")
    return None


def get_tier(rank: int) -> str:
    """
    根據優先級排名決定儲存分層 (ARCHITECTURE 1.1)
    Rank 1~552  -> tier1_hot  (第一批：大盤指數 + 550 檔熱門股)
    Rank 553~1102 -> tier2_warm (第二批：550 檔中型股)
    Rank 1103~    -> tier3_cold (其餘冷門股)
    """
    if rank <= 552:
        return "tier1_hot"
    elif rank <= 1102:
        return "tier2_warm"
    else:
        return "tier3_cold"


def _normalize_stock_id(df: pd.DataFrame) -> pd.DataFrame:
    """ARCHITECTURE 2.1：強制 Stock_ID 一律轉為字串，避免 int/str 型態地雷"""
    if 'Stock_ID' in df.columns:
        df['Stock_ID'] = df['Stock_ID'].astype(str)
    return df


def _normalize_concat(df: pd.DataFrame) -> pd.DataFrame:
    """ARCHITECTURE 2.1：合併後強制統一型態，防止 concat 將 Date 提升為 object 導致去重失效。
    pandas concat 不同 timestamp 精度/型態時會 upcast 為 object，使 drop_duplicates 無法辨識同一天。
    此函式在去重前強制將 Date 統一為 datetime64、Stock_ID 統一為 str。"""
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    if 'Stock_ID' in df.columns:
        df['Stock_ID'] = df['Stock_ID'].astype(str)
    return df


def read_existing_cache() -> pd.DataFrame:
    """ARCHITECTURE 1.2：同時讀取主快取與暫存檔，暫存檔覆蓋舊資料，斷點續傳"""
    df_main = pd.DataFrame()
    df_checkpoint = pd.DataFrame()
    
    if os.path.exists(CACHE_DIR):
        try:
            df_main = pd.read_parquet(CACHE_DIR)
            df_main = _normalize_stock_id(df_main)
        except Exception as e:
            print(f"⚠️ 讀取主快取失敗: {e}")
            
    if os.path.exists(CHECKPOINT_FILE):
        try:
            df_checkpoint = pd.read_parquet(CHECKPOINT_FILE)
            df_checkpoint = _normalize_stock_id(df_checkpoint)
            print(f"♻️ 偵測到中斷暫存檔，已自動載入 {len(df_checkpoint)} 筆復原資料！")
        except Exception as e:
            print(f"⚠️ 讀取暫存檔失敗: {e}")
            
    if df_main.empty and df_checkpoint.empty:
        return pd.DataFrame()
        
    combined_df = pd.concat([df_main, df_checkpoint], ignore_index=True)
    # ARCHITECTURE 2.1：合併後強制統一型態，防止去重失效
    combined_df = _normalize_concat(combined_df)
    
    # ARCHITECTURE 2.1：去除重複值 (以暫存檔的最新資料為準, keep='last' 讓暫存覆蓋舊資料)
    combined_df = combined_df.drop_duplicates(subset=['Stock_ID', 'Date'], keep='last')
    return combined_df


def update_market_cache():
    if not FINMIND_TOKEN:
        print("❌ 錯誤：未在 .env 中找到 FINMIND_TOKEN，請檢查設定。")
        return

    # 🔑 關鍵優化：主執行緒只建立一次 DataLoader 並完成登入，共用給所有 worker
    dl = DataLoader()
    dl.login_by_token(api_token=FINMIND_TOKEN)

    # 📌 週末防呆機制：如果今天是六日，把「目標日」退回禮拜五，避免白白浪費 API 額度
    now = datetime.now()
    if now.weekday() == 5:  # 星期六
        now = now - timedelta(days=1)
    elif now.weekday() == 6:  # 星期日
        now = now - timedelta(days=2)

    today_str = now.strftime('%Y-%m-%d')
    today_ts = pd.to_datetime(today_str)

    print("⏳ 正在獲取全台股清單...")
    try:
        df_info = dl.taiwan_stock_info()
        # 一般股票：4 位數代碼，非 ETF/存託憑證/受益證券
        all_stocks = df_info[
            (~df_info['industry_category'].isin(['ETF', '存託憑證', '受益證券', ''])) &
            (df_info['stock_id'].str.len() == 4)
        ]['stock_id'].unique().tolist()
        
        # 🚀 VIP 霸王條款：強制加入大盤指數（不受 4 位數限制）
        for idx in MARKET_INDICES:
            if idx not in all_stocks:
                all_stocks.insert(0, idx)
        
        # ARCHITECTURE 1.3：生成興櫃股票清單 (type=emerging) 供 UI 層離線使用
        try:
            emerging_stocks = df_info[df_info['type'] == 'emerging']['stock_id'].astype(str).tolist()
            with open(EMERGING_LIST_FILE, "w") as f:
                for sid in emerging_stocks:
                    f.write(f"{sid}\n")
            print(f"✅ 已更新興櫃清單：{len(emerging_stocks)} 檔 (emerging_stocks.txt)")
        except Exception as e:
            print(f"⚠️ 無法寫入興櫃清單: {e}")
            
        # 📌 生成股票名稱對照表 (供 UI 層離線讀取，避免 UI 發 API 請求)
        try:
            name_map = {
                str(row['stock_id']): str(row['stock_name'])
                for _, row in df_info.iterrows()
                if len(str(row['stock_id'])) == 4 and str(row['stock_name'])
            }
            with open(STOCK_NAMES_FILE, "w", encoding="utf-8") as f:
                json.dump(name_map, f, ensure_ascii=False, indent=2)
            print(f"✅ 已更新股票名稱對照表：{len(name_map)} 檔 (stock_names.json)")
        except Exception as e:
            print(f"⚠️ 無法寫入股票名稱清單: {e}")
                
    except Exception as e:
        print(f"\n⚠️ 無法取得股票清單: {e}")
        return

    # 讀取黑名單，過濾殭屍股
    blacklist = set()
    if os.path.exists(BLACKLIST_FILE):
        with open(BLACKLIST_FILE, "r") as f:
            blacklist = set(f.read().splitlines())
    all_stocks = [s for s in all_stocks if s not in blacklist]

    # 讀取本地既有 Parquet (分層儲存)
    existing_df = read_existing_cache()

    # ==========================================
    # 📌 終極修復：統一計算「哪些股票真的需要更新？」
    # ==========================================
    needs_update = []
    fetch_tasks = {}  # 記錄 {股票代號: 要從哪天開始抓}

    if existing_df.empty:
        # 情況 A：完全沒資料
        needs_update = all_stocks
        default_start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        for sid in all_stocks:
            fetch_tasks[sid] = default_start
    else:
        # 情況 B：找出進度落後的股票
        latest_dates = existing_df.groupby('Stock_ID')['Date'].max()
        for sid in all_stocks:
            if sid not in latest_dates:
                # 沒抓過的，抓一年
                needs_update.append(sid)
                fetch_tasks[sid] = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            else:
                # 抓過的，檢查是不是還沒更新到今天(或週五)
                stock_latest = latest_dates[sid]
                if stock_latest < today_ts:
                    needs_update.append(sid)
                    fetch_tasks[sid] = (stock_latest + timedelta(days=1)).strftime('%Y-%m-%d')

    if not needs_update:
        print(f"🎉 恭喜！全市場資料庫已經是最新的，無需更新！去喝杯咖啡吧！")
        return

    # ==========================================
    # 🚀 基於歷史 20 日均量的動態優先級排序 + VIP 霸王條款
    # ==========================================
    # 只在有既有資料時才計算均量排序；冷啟動時跳過，保持原順序
    if not existing_df.empty:
        # 計算每檔股票近 20 日平均成交量 (零 API 成本，純本地運算)
        vol_rank = existing_df.groupby("Stock_ID")["Volume"].apply(lambda x: x.tail(20).mean()).to_dict()
        
        # 🏆 VIP 霸王條款：大盤指數強制設為無限大，保證排第 1、2 名
        for idx in MARKET_INDICES:
            vol_rank[idx] = float('inf')
        
        # 依均量由大到小排序；無歷史資料的新股票預設為 0 (排最後)
        needs_update.sort(key=lambda sid: vol_rank.get(sid, 0), reverse=True)
        print(f"🔥 已依據歷史 20 日均量完成優先級排序（大盤指數 VIP 置頂），將優先更新前 {MAX_STOCKS_PER_RUN} 大標的")
    else:
        print("⚡ 冷啟動模式：本地無歷史資料，跳過均量排序，依原順序更新")

    # 🚨 絕對安全限制：不管發生什麼事，每次最多只拿 MAX_STOCKS_PER_RUN 檔出來跑！
    target_stocks = needs_update[:MAX_STOCKS_PER_RUN]

    print(f"📊 總計掛牌: {len(all_stocks)} 檔 | 尚待更新: {len(needs_update)} 檔")
    print(f"🚀 本次批次安全下載【{len(target_stocks)} 檔】(max_workers={MAX_WORKERS})")
    if "TAIEX" in target_stocks and "TPEx" in target_stocks:
        print(f"   🏆 VIP 確認：TAIEX、TPEx 已鎖定優先更新")

    new_dfs = []
    failed_stocks = []
    completed = 0

    # 使用 ThreadPoolExecutor，共用 dl 實例
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_single_stock_daily, dl, sid, fetch_tasks[sid], today_str): sid
            for sid in target_stocks
        }
        for future in as_completed(futures):
            res = future.result()
            sid = futures[future]
            if res is not None and not res.empty:
                new_dfs.append(res)
            else:
                failed_stocks.append(sid)

            completed += 1

            # ARCHITECTURE 1.2：每抓滿 CHECKPOINT_INTERVAL 檔，中途強制存檔一次！
            if completed % CHECKPOINT_INTERVAL == 0:
                print(f"💾 【進度中繼點】已完成 {completed} 檔，正在進行中途快取存檔...")
                if new_dfs:
                    temp_df = pd.concat(new_dfs, ignore_index=True)
                    temp_df = temp_df.rename(columns={
                        'date': 'Date', 'stock_id': 'Stock_ID', 'close': 'Close',
                        'Trading_Volume': 'Volume', 'max': 'High', 'min': 'Low', 'open': 'Open'
                    })
                    temp_df['Date'] = pd.to_datetime(temp_df['Date'])
                    temp_df = _normalize_stock_id(temp_df)
                    temp_final = pd.concat([existing_df, temp_df], ignore_index=True) if not existing_df.empty else temp_df
                    # ARCHITECTURE 2.1：合併後強制統一型態，防止去重失效
                    temp_final = _normalize_concat(temp_final)
                    # ARCHITECTURE 2.1：去除重複值 (以暫存檔最新資料為準)
                    temp_final = temp_final.drop_duplicates(subset=['Stock_ID', 'Date'], keep='last').sort_values(['Stock_ID', 'Date'])
                    # 中途存檔不分區（避免 Tier 欄位尚未建立），最終存檔時再分區
                    # 使用臨時檔案名稱，避免與分區目錄衝突
                    temp_final.to_parquet(CHECKPOINT_FILE, index=False)

            if completed % 50 == 0 or completed == len(target_stocks):
                print(f"⏳ 進度: {completed}/{len(target_stocks)}")
            time.sleep(REQUEST_DELAY)

    # 🔄 同輪次重試機制：對失敗股票進行即時重試 (最多 2 次，指數退避)
    MAX_RETRIES = 2
    RETRY_DELAY = 5  # 秒
    
    for attempt in range(1, MAX_RETRIES + 1):
        if not failed_stocks:
            break
        
        print(f"🔄 第 {attempt} 次重試，剩餘 {len(failed_stocks)} 檔失敗股票...")
        retry_stocks = failed_stocks.copy()
        failed_stocks = []
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(fetch_single_stock_daily, dl, sid, fetch_tasks[sid], today_str): sid
                for sid in retry_stocks
            }
            for future in as_completed(futures):
                res = future.result()
                sid = futures[future]
                if res is not None and not res.empty:
                    new_dfs.append(res)
                    print(f"   ✅ 重試成功: {sid}")
                else:
                    failed_stocks.append(sid)
        
        if failed_stocks and attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY * attempt)  # 指數退避: 5s, 10s
    
    # 最終仍失敗的，印出警告但不寫入黑名單，留待下一輪排程補抓
    if failed_stocks:
        print(f"⚠️ 經 {MAX_RETRIES} 次重試仍失敗 {len(failed_stocks)} 檔: {failed_stocks[:10]}... 將留待下一輪排程補抓")

    # 📌 最終完整存檔：加入 Tier 分層欄位並分區寫入
    if new_dfs:
        df_batch = pd.concat(new_dfs, ignore_index=True)
        df_batch = df_batch.rename(columns={
            'date': 'Date', 'stock_id': 'Stock_ID', 'close': 'Close',
            'Trading_Volume': 'Volume', 'max': 'High', 'min': 'Low', 'open': 'Open'
        })
        df_batch['Date'] = pd.to_datetime(df_batch['Date'])
        df_batch = _normalize_stock_id(df_batch)
        
        final_df = pd.concat([existing_df, df_batch], ignore_index=True) if not existing_df.empty else df_batch
        # ARCHITECTURE 2.1：合併後強制統一型態（Date→datetime、Stock_ID→str），防 concat upcast 致去重失效
        final_df = _normalize_concat(final_df)
        # ARCHITECTURE 2.1：去除重複值，防止資料分裂與重複 K 線
        final_df = final_df.drop_duplicates(subset=['Stock_ID', 'Date'], keep='last').sort_values(['Stock_ID', 'Date'])
        final_df = _normalize_stock_id(final_df)
        
        # ==========================================
        # 🚀 關鍵 (ARCHITECTURE 1.1)：為每筆資料加上 Tier 分層標籤
        # 【徹底解鎖版】每次存檔強制對「所有已抓取股票」重新計算均量排名，保證數量精準不膨脹！
        # ==========================================
        
        # 1. 計算當前資料庫中「所有股票」的近 20 日平均成交量
        latest_vol_rank = final_df.groupby("Stock_ID")["Volume"].apply(lambda x: x.tail(20).mean()).to_dict()
        
        # 2. 🏆 VIP 霸王條款：確保大盤指數永遠排第一、第二
        for idx in MARKET_INDICES:
            latest_vol_rank[idx] = float('inf')
        
        # 3. 將所有股票依照均量由大到小排序
        all_sids = list(latest_vol_rank.keys())
        all_sids.sort(key=lambda sid: latest_vol_rank.get(sid, 0), reverse=True)
        
        # 4. 依照絕對排名分配 Tier (1~552: tier1_hot | 553~1102: tier2_warm | 其餘: tier3_cold)
        tier_map = {sid: get_tier(rank + 1) for rank, sid in enumerate(all_sids)}
        
        # 5. 無視舊有 Tier，強制將重新計算的精準 Tier 覆寫上去
        final_df['Tier'] = final_df['Stock_ID'].map(tier_map).fillna('tier3_cold').astype(str)
        
        # ARCHITECTURE 1.1：寫入前先清空舊分區目錄，防止 Parquet 碎片檔案無限增生與 Git 空間膨脹
        if os.path.exists(CACHE_DIR):
            import shutil
            shutil.rmtree(CACHE_DIR)
            print(f"🧹 已清空舊快取目錄，準備寫入新分區檔案...")
        
        # 分區寫入：partition_cols=['Tier'] 會自動建立 tier1_hot/、tier2_warm/、tier3_cold/ 子目錄
        final_df.to_parquet(CACHE_DIR, index=False, partition_cols=['Tier'])
        
        updated_total = len(final_df['Stock_ID'].unique())
        new_latest_date = final_df['Date'].max().strftime('%Y-%m-%d')
        
        # 統計各 Tier 筆數
        tier_stock_counts = final_df.groupby('Tier')['Stock_ID'].nunique().to_dict()
        print(f"✅ 本批次 {len(target_stocks)} 檔存檔成功！全台股覆蓋率: {updated_total}/{len(all_stocks)} | 最新日期: {new_latest_date}")
        print(f"   📦 各層股票數: {tier_stock_counts}")
        
        # 🔔 完美提醒！
        if len(needs_update) > MAX_STOCKS_PER_RUN:
            print(f"⏳ 本次 {MAX_STOCKS_PER_RUN} 檔已完美收工！為避免超過 API 每小時限制，請【休息 1 小時】後再執行下一批！")
    else:
        print("ℹ️ 本次未取得新數據（可能是今日盤後數據尚未公佈）。")


if __name__ == "__main__":
    try:
        update_market_cache()
    finally:
        # ARCHITECTURE 1.2：程式結束時的最後防線，無論成功/失敗/無新資料，確保幽靈暫存檔徹底刪除
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            print("🧹 程式結束，已確保中斷暫存檔被徹底清除。")