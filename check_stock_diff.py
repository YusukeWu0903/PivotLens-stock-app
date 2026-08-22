import os
import json
import requests
import pandas as pd

# ==========================================
# 參數與全域變數設定
# ==========================================
LOCAL_STOCK_NAMES_FILE = "stock_names.json"

# 政府開放資料 OpenAPI 端點
TWSE_L_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"  # 上市公司 (18419)
TWSE_O_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_O"  # 上櫃公司 (25036 - 證交所託管版)
TPEX_O_URL = "https://www.tpex.org.tw/openapi/v1/mops0055"           # 上櫃公司 (櫃買官方備用)
TPEX_EM_URL = "https://www.tpex.org.tw/openapi/v1/mops0055_EM"       # 興櫃公司 (28568 - 櫃買官方)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*"
}

def fetch_gov_stocks():
    """從政府 Open API 抓取最新上市、上櫃與興櫃公司清單與名稱"""
    print("⏳ 正在連線政府 Open API 抓取全市場 (上市/上櫃/興櫃) 基本資料...")
    gov_stocks = {}
    
    # ---------------------------------------------------------
    # 1. 抓取上市公司 (TWSE 18419)
    # ---------------------------------------------------------
    try:
        res = requests.get(TWSE_L_URL, headers=HEADERS, timeout=10)
        if res.status_code == 200 and not res.text.strip().startswith("<"):
            for item in res.json():
                sid = str(item.get("公司代號", "")).strip()
                sname = str(item.get("公司簡稱", "")).strip()
                if len(sid) == 4 and sid.isdigit():
                    gov_stocks[sid] = {"name": sname, "market": "上市"}
            print(f"✅ 上市公司 (TWSE): {len([v for v in gov_stocks.values() if v['market'] == '上市'])} 檔")
    except Exception as e:
        print(f"⚠️ 上市公司 API 讀取失敗: {e}")

    # ---------------------------------------------------------
    # 2. 抓取上櫃公司 (三層備援：TWSE_O → TPEX → FinMind)
    # ---------------------------------------------------------
    otc_success = False
    
    # 備援 1：證交所託管版
    try:
        res = requests.get(TWSE_O_URL, headers=HEADERS, timeout=10)
        if res.status_code == 200 and not res.text.strip().startswith("<"):
            for item in res.json():
                sid = str(item.get("公司代號", "")).strip()
                sname = str(item.get("公司簡稱", "")).strip() or str(item.get("公司名稱", "")).strip()
                if len(sid) == 4 and sid.isdigit():
                    gov_stocks[sid] = {"name": sname, "market": "上櫃"}
            if any(v['market'] == '上櫃' for v in gov_stocks.values()):
                print(f"✅ 上櫃公司 (TWSE 端點): {len([v for v in gov_stocks.values() if v['market'] == '上櫃'])} 檔")
                otc_success = True
    except Exception:
        pass

    # 備援 2：櫃買中心官方端點
    if not otc_success:
        try:
            res = requests.get(TPEX_O_URL, headers=HEADERS, timeout=10)
            if res.status_code == 200 and not res.text.strip().startswith("<"):
                for item in res.json():
                    sid = str(item.get("公司代號", "")).strip()
                    sname = str(item.get("公司名稱", "")).strip() or str(item.get("公司簡稱", "")).strip()
                    if len(sid) == 4 and sid.isdigit():
                        gov_stocks[sid] = {"name": sname, "market": "上櫃"}
                if any(v['market'] == '上櫃' for v in gov_stocks.values()):
                    print(f"✅ 上櫃公司 (TPEx 端點): {len([v for v in gov_stocks.values() if v['market'] == '上櫃'])} 檔")
                    otc_success = True
        except Exception:
            pass

    # 備援 3：FinMind API
    if not otc_success:
        try:
            from FinMind.data import DataLoader
            dl = DataLoader()
            df_info = dl.taiwan_stock_info()
            tpex_stocks = df_info[df_info['type'] == 'tpex']
            for _, row in tpex_stocks.iterrows():
                sid = str(row['stock_id']).strip()
                sname = str(row.get('stock_name', '')).strip()
                if len(sid) == 4 and sid.isdigit():
                    gov_stocks[sid] = {"name": sname, "market": "上櫃"}
            count = len([v for v in gov_stocks.values() if v['market'] == '上櫃'])
            if count > 0:
                print(f"✅ 上櫃公司 (FinMind 備援): {count} 檔")
                otc_success = True
        except Exception as e:
            print(f"❌ 上櫃 FinMind 備援失敗: {e}")

    # ---------------------------------------------------------
    # 3. 抓取興櫃公司 (28568 - 雙層備援：TPEX_EM → FinMind)
    # ---------------------------------------------------------
    em_success = False
    
    # 管道 A：TPEx 興櫃 OpenAPI (mops0055_EM)
    try:
        res = requests.get(TPEX_EM_URL, headers=HEADERS, timeout=10)
        if res.status_code == 200 and not res.text.strip().startswith("<"):
            data = res.json()
            if isinstance(data, list):
                for item in data:
                    sid = str(item.get("公司代號", "")).strip()
                    sname = str(item.get("公司名稱", "")).strip() or str(item.get("公司簡稱", "")).strip()
                    if len(sid) == 4 and sid.isdigit():
                        gov_stocks[sid] = {"name": sname, "market": "興櫃"}
                em_count = len([v for v in gov_stocks.values() if v['market'] == '興櫃'])
                print(f"✅ 興櫃公司 (TPEx OpenAPI 28568): {em_count} 檔")
                em_success = True
    except Exception:
        pass

    # 管道 B：FinMind API 興櫃備援 (type == 'emerging')
    if not em_success:
        try:
            from FinMind.data import DataLoader
            dl = DataLoader()
            df_info = dl.taiwan_stock_info()
            em_stocks = df_info[df_info['type'] == 'emerging']
            for _, row in em_stocks.iterrows():
                sid = str(row['stock_id']).strip()
                sname = str(row.get('stock_name', '')).strip()
                if len(sid) == 4 and sid.isdigit():
                    gov_stocks[sid] = {"name": sname, "market": "興櫃"}
            em_count = len([v for v in gov_stocks.values() if v['market'] == '興櫃'])
            if em_count > 0:
                print(f"✅ 興櫃公司 (FinMind 備援): {em_count} 檔")
                em_success = True
        except Exception as e:
            print(f"⚠️ 興櫃 FinMind 備援失敗: {e}")

    return gov_stocks


def compare_stock_lists():
    gov_map = fetch_gov_stocks()
    
    # 讀取本地 stock_names.json
    local_map = {}
    if os.path.exists(LOCAL_STOCK_NAMES_FILE):
        with open(LOCAL_STOCK_NAMES_FILE, "r", encoding="utf-8") as f:
            local_map = json.load(f)
    else:
        print(f"❌ 找不到本地 {LOCAL_STOCK_NAMES_FILE}！請確認檔案在同一層目錄。")
        return

    gov_sids = set(gov_map.keys())
    local_sids = set(local_map.keys())

    print("\n" + "="*70)
    print("📊【全台股上市 / 上櫃 / 興櫃清單與名稱交叉比對報告】")
    print("="*70)
    print(f"🏛️  政府官方全市場 (含興櫃) 總數 : {len(gov_sids)} 檔")
    print(f"📂 本地字典檔 (stock_names.json)  : {len(local_sids)} 檔")
    print("="*70)

    # ---------------------------------------------------------
    # 差異 1：政府有，但本地沒有 (本地漏抓)
    # ---------------------------------------------------------
    missing_sids = gov_sids - local_sids
    print(f"\n🔍【差異 1】政府官方有，但本地缺失的股票 ({len(missing_sids)} 檔)：")
    if missing_sids:
        missing_data = [
            {"股票代號": sid, "官方股票名稱": gov_map[sid]["name"], "市場類別": gov_map[sid]["market"]}
            for sid in sorted(missing_sids)
        ]
        print(pd.DataFrame(missing_data).to_string(index=False))
    else:
        print("  🎉 無缺失！官方所有上市、上櫃與興櫃股票皆已存在於本地清單中。")

    # ---------------------------------------------------------
    # 差異 2：本地有，但政府清單沒有 (多出標的，如大盤指數、特別股或 ETF)
    # ---------------------------------------------------------
    extra_sids = local_sids - gov_sids
    print(f"\n🔍【差異 2】本地有，但不在政府『上市/上櫃/興櫃』普通股清單的股票 ({len(extra_sids)} 檔)：")
    if extra_sids:
        extra_data = [{"股票代號": sid, "本地股票名稱": local_map[sid]} for sid in sorted(extra_sids)]
        print(pd.DataFrame(extra_data).to_string(index=False))
    else:
        print("  🎉 無多餘標的！本地字典檔極度純淨。")

    # ---------------------------------------------------------
    # 差異 3：代號相同，但兩邊「股票名稱不一致」
    # ---------------------------------------------------------
    common_sids = gov_sids & local_sids
    name_mismatches = []
    for sid in sorted(common_sids):
        gov_name = gov_map[sid]["name"].strip()
        local_name = str(local_map[sid]).strip()
        if gov_name != local_name:
            name_mismatches.append({
                "股票代號": sid,
                "本地名稱": local_name,
                "官方名稱": gov_name,
                "市場類別": gov_map[sid]["market"]
            })

    print(f"\n🔍【差異 3】代號存在但兩邊「股票名稱不一致」 ({len(name_mismatches)} 檔)：")
    if name_mismatches:
        print(pd.DataFrame(name_mismatches).to_string(index=False))
    else:
        print("  🎉 完全吻合！所有共同股票的中文名稱皆一致。")


if __name__ == "__main__":
    compare_stock_lists()