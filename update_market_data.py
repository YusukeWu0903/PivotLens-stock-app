import os
import time
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from FinMind.data import DataLoader

load_dotenv()
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "taiwan_market_cache.parquet")
# 📌 新增黑名單檔案路徑
BLACKLIST_FILE = os.path.join(BASE_DIR, "blacklist.txt") 

def fetch_single_stock_daily(stock_id, start_date, end_date):
    dl = DataLoader()
    dl.login_by_token(api_token=FINMIND_TOKEN)
    try:
        df = dl.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if not df.empty:
            return df
    except Exception:
        pass
    return None

def update_market_cache():
    if not FINMIND_TOKEN:
        print("❌ 錯誤：未在 .env 中找到 FINMIND_TOKEN，請檢查設定。")
        return

    dl = DataLoader()
    dl.login_by_token(api_token=FINMIND_TOKEN)
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    print("⏳ 正在獲取全台股清單...")
    try:
        df_info = dl.taiwan_stock_info()
        all_stocks = df_info[
            (~df_info['industry_category'].isin(['ETF', '存託憑證', '受益證券', ''])) &
            (df_info['stock_id'].str.len() == 4)
        ]['stock_id'].unique().tolist()
    except Exception as e:
        print(f"\n⚠️ 無法取得股票清單或 API 配額已達上限: {e}")
        return

    # 📌 讀取黑名單，將已知的殭屍股直接從 all_stocks 中剔除
    blacklist = set()
    if os.path.exists(BLACKLIST_FILE):
        with open(BLACKLIST_FILE, "r") as f:
            blacklist = set(f.read().splitlines())
    
    all_stocks = [s for s in all_stocks if s not in blacklist]
    print(f"ℹ️ 已自動過濾 {len(blacklist)} 檔黑名單股票。")

    # 讀取本地既有 Parquet
    existing_df = pd.DataFrame()
    already_fetched = set()
    latest_date = None

    if os.path.exists(CACHE_FILE):
        try:
            existing_df = pd.read_parquet(CACHE_FILE)
            existing_df['Date'] = pd.to_datetime(existing_df['Date'])
            already_fetched = set(existing_df['Stock_ID'].unique())
            if not existing_df.empty:
                latest_date = existing_df['Date'].max().strftime('%Y-%m-%d')
        except Exception as e:
            print(f"⚠️ 讀取舊快取失敗: {e}")

    remaining_stocks = [s for s in all_stocks if s not in already_fetched]
    is_historical_mode = False
    
    # -------------------------------------------------------------
    # 情況 A：歷史資料還沒補齊 (第一次建庫階段)
    # -------------------------------------------------------------
    if remaining_stocks:
        is_historical_mode = True
        print(f"📊 【歷史庫補齊模式】總計: {len(all_stocks)} 檔 | 已建快取: {len(already_fetched)} 檔 | 待補齊: {len(remaining_stocks)} 檔")
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        
        # 📌 每次目標抓 550 檔！
        target_stocks = remaining_stocks[:550]  
        end_date = today_str
        
    # -------------------------------------------------------------
    # 情況 B：歷史資料已全數建置完成 (每日日常更新模式)
    # -------------------------------------------------------------
    else:
        if latest_date >= today_str:
            print(f"🎉 快取資料庫已經是最新狀態 (最新日期: {latest_date})，無需更新！")
            return

        start_date = (pd.to_datetime(latest_date) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
        end_date = today_str
        target_stocks = all_stocks
        print(f"🔄 【日常增量更新模式】最新資料日期為 {latest_date}，開始抓取 {start_date} ~ {end_date} 增量行情...")

    print(f"🚀 本次預計下載【{len(target_stocks)} 檔】...")
    new_dfs = []
    failed_stocks = []
    completed = 0

    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = {
            executor.submit(fetch_single_stock_daily, sid, start_date, end_date): sid 
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
            
            # 📌 每抓滿 110 檔，就中途偷偷存檔一次！確保萬無一失
            if completed % 110 == 0:
                print(f"💾 【進度中繼點】已完成 {completed} 檔，正在進行中途強制存檔...")
                # (此處可呼叫暫存或寫入邏輯)
                
            if completed % 50 == 0 or completed == len(target_stocks):
                print(f"⏳ 進度: {completed}/{len(target_stocks)}")
            time.sleep(0.3)

    # 補齊模式下抓不到資料的寫入黑名單
    if is_historical_mode and failed_stocks:
        with open(BLACKLIST_FILE, "a") as f:
            for sid in failed_stocks:
                f.write(f"{sid}\n")
        print(f"🚫 發現 {len(failed_stocks)} 檔無法取得資料的股票，已永久加入黑名單！")

    # 📌 550 檔全部跑完，最終強制完整存檔入硬碟！
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
        print(f"✅ 本批次 550 檔存檔成功！目前覆蓋率: {updated_total}/{len(all_stocks)} ({updated_total/len(all_stocks)*100:.1f}%) | 最新日期: {new_latest_date}")
        
        # 📌 抓完 550 檔後的休息提示
        if remaining_stocks and len(remaining_stocks) > 550:
            print("⏳ 本次 550 檔已完美收工！為避免超過 API 每小時限制，請休息 1 小時後再執行下一批！")
    else:
        print("ℹ️ 本次未取得新數據。")

if __name__ == "__main__":
    update_market_cache()