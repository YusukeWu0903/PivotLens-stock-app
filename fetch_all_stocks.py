import pandas as pd
from datetime import datetime, timedelta
from FinMind.data import DataLoader

# 請填入你在 FinMind 註冊後取得的 免費 Token (可享每小時 600 次額度)
FINMIND_TOKEN = "YOUR_FINMIND_TOKEN_HERE" 

def download_full_market_data():
    dl = DataLoader()
    dl.login_by_token(api_token=FINMIND_TOKEN)
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    
    print("⏳ 正在批量下載全台股近一年歷史日 K 資料，請稍候...")
    
    # 💡 關鍵：不指定 stock_id，一次性要求全市場全區間數據！
    df_all = dl.taiwan_stock_daily(
        start_date=start_date, 
        end_date=end_date
    )
    
    if not df_all.empty:
        # 整理欄位格式
        df_all = df_all.rename(columns={
            'date': 'Date', 'stock_id': 'Stock_ID', 'close': 'Close',
            'Trading_Volume': 'Volume', 'max': 'High', 'min': 'Low', 'open': 'Open'
        })
        df_all['Date'] = pd.to_datetime(df_all['Date'])
        
        # 儲存為高效能的壓縮本地檔 (Parquet 或 Pickle，讀取速度遠勝 CSV)
        df_all.to_parquet("taiwan_all_stocks_daily.parquet", index=False)
        print("✅ 全台股資料下載完畢！已儲存至 taiwan_all_stocks_daily.parquet")
    else:
        print("❌ 下載失敗，請檢查 Token 或網路連線。")

if __name__ == "__main__":
    download_full_market_data()