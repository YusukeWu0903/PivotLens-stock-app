import os
import time
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from FinMind.data import DataLoader

load_dotenv()
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")
CACHE_FILE = "taiwan_market_cache.parquet"

def fetch_single_stock_daily(stock_id, start_date, end_date):
    dl = DataLoader()
    dl.login_by_token(api_token=FINMIND_TOKEN)
    try:
        df = dl.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if not df.empty and len(df) >= 40:
            return df
    except Exception:
        pass
    return None

def update_market_cache_incremental():
    if not FINMIND_TOKEN:
        print("❌ 錯誤：未在 .env 中找到 FINMIND_TOKEN，請檢查設定。")
        return

    dl = DataLoader()
    dl.login_by_token(api_token=FINMIND_TOKEN)
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    
    print("⏳ 正在獲取全台股清單...")
    try:
        df_info = dl.taiwan_stock_info()
        all_stocks = df_info[
            (~df_info['industry_category'].isin(['ETF', '存託憑證', '受益證券', ''])) &
            (df_info['stock_id'].str.len() == 4)
        ]['stock_id'].unique().tolist()
    except Exception as e:
        print(f"\n⚠️ 無法取得股票清單！可能是 FinMind 免費 API 每小時 600 次配額已達上限。")
        print(f"詳細訊息：{e}")
        print("💡 請等待 30~60 分鐘待額度重置後，再重新執行 python update_market_data.py。")
        return

    # 檢查本地既有 Parquet，實現續傳
    existing_df = pd.DataFrame()
    already_fetched = set()
    if os.path.exists(CACHE_FILE):
        try:
            existing_df = pd.read_parquet(CACHE_FILE)
            already_fetched = set(existing_df['Stock_ID'].unique())
        except Exception:
            pass
            
    remaining_stocks = [s for s in all_stocks if s not in already_fetched]
    
    print(f"📊 全台股總計: {len(all_stocks)} 檔 | 已建立快取: {len(already_fetched)} 檔 | 待抓取: {len(remaining_stocks)} 檔")
    
    if not remaining_stocks:
        print("🎉 恭喜！全台股 100% 歷史資料已建立完成！")
        return

    # 本次僅安全抓取 450 檔
    batch_to_fetch = remaining_stocks[:450]
    print(f"🚀 本次預計批次下載【{len(batch_to_fetch)} 檔】...")
    
    new_dfs = []
    completed = 0
    rate_limit_hit = False

    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = {
            executor.submit(fetch_single_stock_daily, sid, start_date, end_date): sid 
            for sid in batch_to_fetch
        }
        for future in as_completed(futures):
            res = future.result()
            if res is not None:
                new_dfs.append(res)
            completed += 1
            if completed % 50 == 0 or completed == len(batch_to_fetch):
                print(f"⏳ 進度: {completed}/{len(batch_to_fetch)}")
            time.sleep(0.3)

    # 存檔保護
    if new_dfs:
        df_batch = pd.concat(new_dfs, ignore_index=True)
        df_batch = df_batch.rename(columns={
            'date': 'Date', 'stock_id': 'Stock_ID', 'close': 'Close',
            'Trading_Volume': 'Volume', 'max': 'High', 'min': 'Low', 'open': 'Open'
        })
        df_batch['Date'] = pd.to_datetime(df_batch['Date'])
        
        final_df = pd.concat([existing_df, df_batch], ignore_index=True) if not existing_df.empty else df_batch
        final_df.to_parquet(CACHE_FILE, index=False)
        
        updated_total = len(final_df['Stock_ID'].unique())
        print(f"✅ 本次批次存檔成功！全台股資料庫覆蓋率已達: {updated_total}/{len(all_stocks)} ({updated_total/len(all_stocks)*100:.1f}%)")
    else:
        print("❌ 本次未成功取得新資料，請確認 API 配額。")

if __name__ == "__main__":
    update_market_cache_incremental()