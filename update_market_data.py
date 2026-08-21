import os
import time
import json
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dotenv import load_dotenv
from FinMind.data import DataLoader
import requests

load_dotenv()
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 分層快取目錄 (ARCHITECTURE 1.1)
CACHE_DIR = os.path.join(BASE_DIR, "market_cache")
# 中途暫存檔 (ARCHITECTURE 1.2)
CHECKPOINT_FILE = os.path.join(BASE_DIR, "market_cache_checkpoint.parquet")
# 黑名單相關檔案
BLACKLIST_FILE = os.path.join(BASE_DIR, "blacklist.txt")           # 永久封鎖 (手動+官方下市)
TEMP_BLACKLIST_FILE = os.path.join(BASE_DIR, "temp_blacklist.txt") # 暫時封鎖 (含時間戳, 30天自動過期)
WATCHLIST_FILE = os.path.join(BASE_DIR, "watchlist.txt")           # 觀察名單 (不封鎖, 僅記錄)
# 興櫃股票清單 (ARCHITECTURE 1.3)
EMERGING_LIST_FILE = os.path.join(BASE_DIR, "emerging_stocks.txt")
# 股票名稱對照表
STOCK_NAMES_FILE = os.path.join(BASE_DIR, "stock_names.json")

# 大盤指數代碼
MARKET_INDICES = ["TAIEX", "TPEx"]

# 可配置參數
MAX_WORKERS = int(os.getenv("UPDATE_MAX_WORKERS", "5"))
MAX_STOCKS_PER_RUN = int(os.getenv("UPDATE_MAX_STOCKS_PER_RUN", "582"))
CHECKPOINT_INTERVAL = int(os.getenv("UPDATE_CHECKPOINT_INTERVAL", "110"))
REQUEST_DELAY = float(os.getenv("UPDATE_REQUEST_DELAY", "1.0"))
API_TIMEOUT = int(os.getenv("UPDATE_API_TIMEOUT", "30"))
# 暫時黑名單過期天數 (預設 30 天)
TEMP_BLACKLIST_DAYS = int(os.getenv("TEMP_BLACKLIST_DAYS", "30"))


def fetch_single_stock_daily(dl: DataLoader, stock_id: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """使用共用的 DataLoader 實例抓取單一股票日線資料。"""
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
    """根據優先級排名決定儲存分層 (ARCHITECTURE 1.1)"""
    if rank <= 552:
        return "tier1_hot"
    elif rank <= 1102:
        return "tier2_warm"
    else:
        return "tier3_cold"


def _normalize_stock_id(df: pd.DataFrame) -> pd.DataFrame:
    """強制 Stock_ID 轉為字串，避免 int/str 型態地雷"""
    if 'Stock_ID' in df.columns:
        df['Stock_ID'] = df['Stock_ID'].astype(str)
    return df


def _normalize_concat(df: pd.DataFrame) -> pd.DataFrame:
    """合併後強制統一型態，防止 concat 將 Date 提升為 object 導致去重失效"""
    if 'Date' in df.columns:
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    if 'Stock_ID' in df.columns:
        df['Stock_ID'] = df['Stock_ID'].astype(str)
    return df


def read_existing_cache() -> pd.DataFrame:
    """ARCHITECTURE 1.2：同時讀取主快取與暫存檔，斷點續傳"""
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
    combined_df = _normalize_concat(combined_df)
    combined_df = combined_df.drop_duplicates(subset=['Stock_ID', 'Date'], keep='last')
    return combined_df


def smart_blacklist_manager(dl: DataLoader) -> set:
    """
    🛡️ 智慧黑名單管理器 v2
    分三級管理，只讀不自動寫入失敗股，但主動偵測官方下市股。

    Returns: 合併後的完整封鎖清單 (permanent + unexpired temp)
    """
    permanent = set()
    temp_active = set()

    # ========== L1: 載入永久黑名單 (手動維護 + 官方下市) ==========
    if os.path.exists(BLACKLIST_FILE):
        with open(BLACKLIST_FILE, "r") as f:
            permanent = set(f.read().splitlines())

    # ========== L2: 載入暫時黑名單 (含時間戳，過期自動清除) ==========
    temp_updated = []
    if os.path.exists(TEMP_BLACKLIST_FILE):
        with open(TEMP_BLACKLIST_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) == 2:
                    sid, ts_str = parts
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if datetime.now() - ts < timedelta(days=TEMP_BLACKLIST_DAYS):
                            temp_active.add(sid)
                            temp_updated.append(line)
                    except ValueError:
                        continue

    # 寫回 (自動清除過期條目)
    if len(temp_updated) != len([l for l in open(TEMP_BLACKLIST_FILE) if l.strip()]):
        with open(TEMP_BLACKLIST_FILE, "w") as f:
            for line in temp_updated:
                f.write(line + "\n")

    # ========== L3: 主動偵測官方下市股 (FinMind 官方標記) ==========
    try:
        df_info = dl.taiwan_stock_info()
        # 官方 type 包含下市、終止上市、暫停交易等
        delisted_candidates = df_info[
            df_info['type'].isin(['delisted', 'terminated', 'suspended'])
        ]['stock_id'].astype(str).tolist()
        # 加入永久封鎖 (只加新的)
        new_delisted = set(delisted_candidates) - permanent
        if new_delisted:
            permanent.update(new_delisted)
            with open(BLACKLIST_FILE, "a") as f:
                for sid in sorted(new_delisted):
                    f.write(f"{sid}\n")
            print(f"✅ 主動偵測到 {len(new_delisted)} 檔新下市股，已加入永久黑名單")
    except Exception as e:
        print(f"⚠️ 偵測下市股失敗 (不影響執行): {e}")

    print(f"📋 黑名單狀態：永久 {len(permanent)} 檔 | 暫時 {len(temp_active)} 檔 (過期 {TEMP_BLACKLIST_DAYS} 天)")
    return permanent | temp_active


def update_market_cache():
    if not FINMIND_TOKEN:
        print("❌ 錯誤：未在 .env 中找到 FINMIND_TOKEN，請檢查設定。")
        return

    # 🔑 關鍵優化：主執行緒只建立一次 DataLoader 並完成登入
    dl = DataLoader()
    dl.login_by_token(api_token=FINMIND_TOKEN)

    # 📌 週末防呆機制
    now = datetime.now()
    if now.weekday() == 5:
        now = now - timedelta(days=1)
    elif now.weekday() == 6:
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

        for idx in MARKET_INDICES:
            if idx not in all_stocks:
                all_stocks.insert(0, idx)

        # 生成興櫃清單
        try:
            emerging_stocks = df_info[df_info['type'] == 'emerging']['stock_id'].astype(str).tolist()
            with open(EMERGING_LIST_FILE, "w") as f:
                for sid in emerging_stocks:
                    f.write(f"{sid}\n")
            print(f"✅ 已更新興櫃清單：{len(emerging_stocks)} 檔 (emerging_stocks.txt)")
        except Exception as e:
            print(f"⚠️ 無法寫入興櫃清單: {e}")

        # 生成股票名稱對照表
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

    # ========== 🛡️ 智慧黑名單過濾 ==========
    all_blacklist = smart_blacklist_manager(dl)
    all_stocks = [s for s in all_stocks if s not in all_blacklist]

    # 讀取本地既有快取
    existing_df = read_existing_cache()

    # ========== 計算哪些股票需要更新 ==========
    needs_update = []
    fetch_tasks = {}

    if existing_df.empty:
        needs_update = all_stocks
        default_start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        for sid in all_stocks:
            fetch_tasks[sid] = default_start
    else:
        latest_dates = existing_df.groupby('Stock_ID')['Date'].max()
        for sid in all_stocks:
            if sid not in latest_dates:
                needs_update.append(sid)
                fetch_tasks[sid] = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
            else:
                stock_latest = latest_dates[sid]
                if stock_latest < today_ts:
                    needs_update.append(sid)
                    fetch_tasks[sid] = (stock_latest + timedelta(days=1)).strftime('%Y-%m-%d')

    if not needs_update:
        print(f"🎉 恭喜！全市場資料庫已經是最新的，無需更新！")
        return

    # ========== 均量排序 + VIP 霸王條款 ==========
    if not existing_df.empty:
        vol_rank = existing_df.groupby("Stock_ID")["Volume"].apply(lambda x: x.tail(20).mean()).to_dict()
        for idx in MARKET_INDICES:
            vol_rank[idx] = float('inf')
        needs_update.sort(key=lambda sid: vol_rank.get(sid, 0), reverse=True)
        print(f"🔥 已依據歷史 20 日均量完成優先級排序（大盤指數 VIP 置頂），將優先更新前 {MAX_STOCKS_PER_RUN} 大標的")
    else:
        print("⚡ 冷啟動模式：跳過均量排序，依原順序更新")

    target_stocks = needs_update[:MAX_STOCKS_PER_RUN]

    print(f"📊 總計掛牌: {len(all_stocks)} 檔 | 尚待更新: {len(needs_update)} 檔")
    print(f"🚀 本次批次安全下載【{len(target_stocks)} 檔】(max_workers={MAX_WORKERS})")
    if "TAIEX" in target_stocks and "TPEx" in target_stocks:
        print(f"   🏆 VIP 確認：TAIEX、TPEx 已鎖定優先更新")

    new_dfs = []
    failed_stocks = []
    completed = 0

    # ========== 多執行緒抓取 (含超時保護) ==========
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(fetch_single_stock_daily, dl, sid, fetch_tasks[sid], today_str): sid
            for sid in target_stocks
        }

        pending = set(futures.keys())

        while pending:
            done, pending = wait(pending, timeout=API_TIMEOUT, return_when=FIRST_COMPLETED)

            for future in done:
                sid = futures[future]
                try:
                    res = future.result(timeout=0)
                    if res is not None and not res.empty:
                        new_dfs.append(res)
                    else:
                        failed_stocks.append(sid)
                except Exception as e:
                    print(f"  ⚠️ {sid}: 執行失敗 - {e}")
                    failed_stocks.append(sid)

                completed += 1

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
                        temp_final = _normalize_concat(temp_final)
                        temp_final = temp_final.drop_duplicates(subset=['Stock_ID', 'Date'], keep='last').sort_values(['Stock_ID', 'Date'])
                        temp_final.to_parquet(CHECKPOINT_FILE, index=False)

                if completed % 50 == 0 or completed == len(target_stocks):
                    print(f"⏳ 進度: {completed}/{len(target_stocks)}")
                time.sleep(REQUEST_DELAY)

            if pending:
                timed_out = [futures[f] for f in pending]
                print(f"⚠️ {len(timed_out)} 支 API 逾時 ({API_TIMEOUT}s)，標記為失敗：{timed_out[:5]}...")
                failed_stocks.extend(timed_out)
                for f in pending:
                    f.cancel()

    # ========== 失敗記錄到觀察清單 (不封鎖) ==========
    if failed_stocks:
        print(f"⚠️ 本批次失敗 {len(failed_stocks)} 檔: {failed_stocks[:10]}... 將記錄到觀察清單，留待下一輪排程補抓")
        try:
            with open(WATCHLIST_FILE, "a") as f:
                now_iso = datetime.now().isoformat()
                for sid in failed_stocks:
                    f.write(f"{sid},{now_iso}\n")
        except Exception as e:
            print(f"⚠️ 寫入觀察清單失敗: {e}")

    # ========== 最終完整存檔 ==========
    if new_dfs:
        df_batch = pd.concat(new_dfs, ignore_index=True)
        df_batch = df_batch.rename(columns={
            'date': 'Date', 'stock_id': 'Stock_ID', 'close': 'Close',
            'Trading_Volume': 'Volume', 'max': 'High', 'min': 'Low', 'open': 'Open'
        })
        df_batch['Date'] = pd.to_datetime(df_batch['Date'])
        df_batch = _normalize_stock_id(df_batch)

        final_df = pd.concat([existing_df, df_batch], ignore_index=True) if not existing_df.empty else df_batch
        final_df = _normalize_concat(final_df)
        final_df = final_df.drop_duplicates(subset=['Stock_ID', 'Date'], keep='last').sort_values(['Stock_ID', 'Date'])
        final_df = _normalize_stock_id(final_df)

        # Tier 分層計算
        latest_vol_rank = final_df.groupby("Stock_ID")["Volume"].apply(lambda x: x.tail(20).mean()).to_dict()
        for idx in MARKET_INDICES:
            latest_vol_rank[idx] = float('inf')

        all_sids = list(latest_vol_rank.keys())
        all_sids.sort(key=lambda sid: latest_vol_rank.get(sid, 0), reverse=True)
        tier_map = {sid: get_tier(rank + 1) for rank, sid in enumerate(all_sids)}

        final_df['Tier'] = final_df['Stock_ID'].map(tier_map).fillna('tier3_cold').astype(str)

        if os.path.exists(CACHE_DIR):
            import shutil
            shutil.rmtree(CACHE_DIR)
            print(f"🧹 已清空舊快取目錄，準備寫入新分區檔案...")

        final_df.to_parquet(CACHE_DIR, index=False, partition_cols=['Tier'])

        updated_total = len(final_df['Stock_ID'].unique())
        new_latest_date = final_df['Date'].max().strftime('%Y-%m-%d')
        tier_stock_counts = final_df.groupby('Tier')['Stock_ID'].nunique().to_dict()

        print(f"✅ 本批次 {len(target_stocks)} 檔存檔成功！全台股覆蓋率: {updated_total}/{len(all_stocks)} | 最新日期: {new_latest_date}")
        print(f"   📦 各層股票數: {tier_stock_counts}")

        if len(needs_update) > MAX_STOCKS_PER_RUN:
            print(f"⏳ 本次 {MAX_STOCKS_PER_RUN} 檔已完美收工！為避免超過 API 每小時限制，請【休息 1 小時】後再執行下一批！")
    else:
        print("ℹ️ 本次未取得新數據（可能是今日盤後數據尚未公佈）。")


if __name__ == "__main__":
    try:
        update_market_cache()
    finally:
        # 確保幽靈暫存檔徹底清除
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
            print("🧹 程式結束，已確保中斷暫存檔被徹底清除。")