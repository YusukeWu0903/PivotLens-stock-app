import os
import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("FINMIND_TOKEN")

if not token:
    print("❌ 找不到 FINMIND_TOKEN，請檢查 .env 檔案。")
else:
    url = "https://api.web.finmindtrade.com/v2/user_info"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            # 根據 FinMind 官方文件解析欄位
            user_count = data.get("user_count", "未知")
            api_limit = data.get("api_request_limit", "未知")
            
            print("=" * 40)
            print("📊 FinMind API 額度狀態查詢")
            print("=" * 40)
            print(print(f"🔹 目前已使用次數: {user_count}"))
            print(f"🔹 每小時請求上限: {api_limit}")
            print("=" * 40)
        else:
            print(f"⚠️ 查詢失敗，狀態碼: {response.status_code}，訊息: {response.text}")
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")