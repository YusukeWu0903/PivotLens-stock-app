import os
import subprocess
import sys

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def main():
    while True:
        clear_screen()
        print("=" * 45)
        print("         📈 台股量化分析工具主選單         ")
        print("=" * 45)
        print(" [1] 🚀 啟動選股分析網頁介面 (App.py)")
        print(" [2] 🔍 啟動本地快取檢視器 (View Local Cache)")
        print(" [3] 🔄 執行全市場數據增量更新 (Update Market Data)")
        print(" [4] 📊 查詢 FinMind API 剩餘額度")
        print(" [0] 🚪 離開系統")
        print("=" * 45)
        
        choice = input("👉 請輸入您的選擇代號 (0-4): ").strip()
        
        if choice == '1':
            print("\n🚀 正在啟動選股分析網頁 (Port 8501)...")
            subprocess.run([sys.executable, "-m", "streamlit", "run", "app.py"])
            input("\n按 Enter 鍵返回主選單...")
            
        elif choice == '2':
            print("\n🔍 正在啟動本地快取檢視器 (Port 8502)...")
            subprocess.run([sys.executable, "-m", "streamlit", "run", "view_local_cache.py", "--server.port", "8502"])
            input("\n按 Enter 鍵返回主選單...")
            
        elif choice == '3':
            print("\n🔄 開始執行市場數據增量更新...")
            subprocess.run([sys.executable, "update_market_data.py"])
            input("\n執行完畢！按 Enter 鍵返回主選單...")
            
        elif choice == '4':
            print("\n📊 正在查詢 API 額度...")
            if os.path.exists("check_finmind_quota.py"):
                subprocess.run([sys.executable, "check_finmind_quota.py"])
            else:
                print("❌ 找不到 check_finmind_quota.py，請確認檔案是否存在。")
            input("\n按 Enter 鍵返回主選單...")
            
        elif choice == '0':
            print("\n👋 感謝使用，系統已關閉。")
            break
        else:
            input("\n❌ 輸入錯誤！請輸入有效代號 (0-4)，按 Enter 鍵繼續...")

if __name__ == "__main__":
    main()