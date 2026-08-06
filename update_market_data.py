import os
import time
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from FinMind.data import DataLoader
import requests

load_dotenv()
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "taiwan_market_cache.parquet")
BLACKLIST_FILE = os.path.join(BASE_DIR, "blacklist.txt")

# 可配置的多執行緒數量（預設 5，可透過環境變數覆蓋）
MAX_WORKERS = int(os.getenv("UPDATE_MAX_WORKERS", "5"))
# 單次執行最大更新檔數（避免超過 API 時限）
MAX_STOCKS_PER_RUN = int(os.getenv("UPDATE_MAX_STOCKS_PER_RUN", "550"))
# 中途存檔間隔
CHECKPOINT_INTERVAL = int(os.getenv("UPDATE_CHECKPOINT_INTERVAL", "110"))
# 請求間隔（秒）
REQUEST_DELAY = float(os.getenv("UPDATE_REQUEST_DELAY", "0.3"))


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
        all_stocks = df_info[
            (~df_info['industry_category'].isin(['ETF', '存託憑證', '受益證券', ''])) &
            (df_info['stock_id'].str.len() == 4)
        ]['stock_id'].unique().tolist()
    except Exception as e:
        print(f"\n⚠️ 無法取得股票清單: {e}")
        return

    # 讀取黑名單，過濾殭屍股
    blacklist = set()
    if os.path.exists(BLACKLIST_FILE):
        with open(BLACKLIST_FILE, "r") as f:
            blacklist = set(f.read().splitlines())
    all_stocks = [s for s in all_stocks if s not in blacklist]

    # 讀取本地既有 Parquet
    existing_df = pd.DataFrame()
    if os.path.exists(CACHE_FILE):
        try:
            existing_df = pd.read_parquet(CACHE_FILE)
            existing_df['Date'] = pd.to_datetime(existing_df['Date'])
        except Exception as e:
            print(f"⚠️ 讀取舊快取失敗: {e}")

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
    # 🚀 新增：基於歷史 20 日均量的動態優先級排序
    # ==========================================
    # 只在有既有資料時才計算均量排序；冷啟動時跳過，保持原順序
    if not existing_df.empty:
        # 計算每檔股票近 20 日平均成交量 (零 API 成本，純本地運算)
        vol_rank = existing_df.groupby("Stock_ID")["Volume"].apply(lambda x: x.tail(20).mean()).to_dict()
        # 依均量由大到小排序；無歷史資料的新股票預設為 0 (排最後)
        needs_update.sort(key=lambda sid: vol_rank.get(sid, 0), reverse=True)
        print(f"🔥 已依據歷史 20 日均量完成優先級排序，將優先更新成交量前 {MAX_STOCKS_PER_RUN} 大標的")
    else:
        print("⚡ 冷啟動模式：本地無歷史資料，跳過均量排序，依原順序更新")

    # 🚨 絕對安全限制：不管發生什麼事，每次最多只拿 MAX_STOCKS_PER_RUN 檔出來跑！
    target_stocks = needs_update[:MAX_STOCKS_PER_RUN]

    print(f"📊 總計掛牌: {len(all_stocks)} 檔 | 尚待更新: {len(needs_update)} 檔")
    print(f"🚀 本次批次安全下載【{len(target_stocks)} 檔】(max_workers={MAX_WORKERS})...")

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
            if res is not None:
                new_dfs.append(res)
            else:
                failed_stocks.append(sid)

            completed += 1

            # 📌 完美節奏：每抓滿 CHECKPOINT_INTERVAL 檔，中途強制幫你存檔一次！
            if completed % CHECKPOINT_INTERVAL == 0:
                print(f"💾 【進度中繼點】已完成 {completed} 檔，正在進行中途快取存檔...")
                if new_dfs:
                    temp_df = pd.concat(new_dfs, ignore_index=True)
                    temp_df = temp_df.rename(columns={
                        'date': 'Date', 'stock_id': 'Stock_ID', 'close': 'Close',
                        'Trading_Volume': 'Volume', 'max': 'High', 'min': 'Low', 'open': 'Open'
                    })
                    temp_df['Date'] = pd.to_datetime(temp_df['Date'])
                    temp_final = pd.concat([existing_df, temp_df], ignore_index=True) if not existing_df.empty else temp_df
                    temp_final = temp_final.drop_duplicates(subset=['Stock_ID', 'Date']).sort_values(['Stock_ID', 'Date'])
                    temp_final.to_parquet(CACHE_FILE, index=False)

            if completed % 50 == 0 or completed == len(target_stocks):
                print(f"⏳ 進度: {completed}/{len(target_stocks)}")
            time.sleep(REQUEST_DELAY)

    # 抓不到資料的寫入黑名單 (條件：只有要求抓「一年歷史」卻失敗的，才認定為死檔)
    default_start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    real_dead_stocks = [s for s in failed_stocks if fetch_tasks[s] == default_start]
    if real_dead_stocks:
        with open(BLACKLIST_FILE, "a") as f:
            for sid in real_dead_stocks:
                f.write(f"{sid}\n")
        print(f"🚫 發現 {len(real_dead_stocks)} 檔無法取得歷史資料，已永久加入黑名單！")

    # 📌 550 檔跑完，最終完整存檔！
    if new_dfs:
        df_batch = pd.concat(new_dfs, ignore_index=True)
        df_batch = df_batch.rename(columns={
            'date': 'Date', 'stock_id': 'Stock_ID', 'close': 'Close',
            'Trading_Volume': 'Volume', 'max': 'High', 'min': 'Low', 'open': 'Open'
        })
        df_batch['Date'] = pd.to_datetime(df_batch['Date'])

        final_df = pd.concat([existing_df, df_batch], ignore_index=True) if not existing_df.empty else df_batch
        final_df = final_df.drop_duplicates(subset=['Stock_ID', 'Date']).sort_values(['Stock_ID', 'Date'])
        final_df.to_parquet(CACHE_FILE, index=False)

        updated_total = len(final_df['Stock_ID'].unique())
        new_latest_date = final_df['Date'].max().strftime('%Y-%m-%d')
        print(f"✅ 本批次 {len(target_stocks)} 檔存檔成功！全台股覆蓋率: {updated_total}/{len(all_stocks)} | 最新日期: {new_latest_date}")

        # 🔔 完美提醒！
        if len(needs_update) > MAX_STOCKS_PER_RUN:
            print(f"⏳ 本次 {MAX_STOCKS_PER_RUN} 檔已完美收工！為避免超過 API 每小時限制，請【休息 1 小時】後再執行下一批！")
    else:
        print("ℹ️ 本次未取得新數據（可能是今日盤後數據尚未公佈）。")


if __name__ == "__main__":
    update_market_cache()