# -*- coding: utf-8 -*-
"""
fetch_app_updates.py

功能（修正版）：
  - 讀取各國 iOS/GP 排行榜（暢銷榜與免費榜）
  - 從 available_dates_XX.json 中取得所有可比較的前後兩日日期對。
  - 針對每一對日期，抓取 Top 50 遊戲版本號、更新時間、release notes。
  - 比對兩個日期，若版本號或更新時間不同則標記「改版事件」。
  - 輸出：data/ranks/updates/updates_YYYYMMDD.json (YYYYMMDD 為較新的日期)
  - 只有當有實際更新事件發生時，才輸出 JSON 檔案。
"""

import os
import json
import pathlib
import datetime
import requests
import time
from collections import defaultdict

# --- 路徑與常數設定 ---
DATA_DIR = pathlib.Path("data")
RANKS_DIR = DATA_DIR / "ranks"
UPDATE_DIR = RANKS_DIR / "updates" # 修正：將 updates 放在 ranks/updates
UPDATE_DIR.mkdir(parents=True, exist_ok=True)

TARGET_COUNTRIES = ["US", "CN", "TW", "TH", "PH"]
TOP_LIMIT = 50 

CHARTS = ["top_grossing", "top_free"] 
PLATFORMS = ["ios", "gp"] # 支援 iOS 和 Google Play (GP)

# --- 工具函式 ---
def read_json(path):
    """安全讀取 JSON 檔案，不存在或錯誤則回傳空字典"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def write_json(path, data):
    """安全寫入 JSON 檔案"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[FATAL ERROR] 無法寫入 JSON 檔案 {path}: {e}")

def load_available_dates(country: str):
    """讀取某國可用的日期清單"""
    # 路徑已與 fetch_ios_rss.py 修正後保持一致
    path = RANKS_DIR / country / f"available_dates_{country}.json"
    # 確保回傳值是列表，以防萬一
    data = read_json(path)
    return data if isinstance(data, list) else []

def load_rank_data(country: str, date_str: str, chart: str, platform: str):
    """載入指定日期的榜單資料"""
    folder = RANKS_DIR / country
    filename = f"{platform.lower()}_{country.lower()}_{chart}_{date_str}.json"
    fpath = folder / filename
    return read_json(fpath)

def fetch_ios_metadata(app_id):
    """呼叫 Apple Lookup API 抓版本、更新時間、release notes"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        url = f"https://itunes.apple.com/lookup?id={app_id}"
        r = requests.get(url, timeout=10, headers=headers)

        if r.status_code != 200:
            return None

        js = r.json()
        if not js.get("results"):
            return None
        item = js["results"][0]
        return {
            "version": item.get("version"),
            "updated": item.get("currentVersionReleaseDate"),
            "releaseNotes": item.get("releaseNotes", ""),
            "app_id": str(app_id)
        }
    except Exception as e:
        print(f"[ERROR] fetch_ios_metadata {app_id}: {e}")
        return None

def detect_updates(today_data, yesterday_data):
    """
    比對今日與昨日版本差異。
    today_data / yesterday_data 的結構皆為 {app_name: {version, updated, ...}}
    """
    updates = {}
    for app_name, today_info in today_data.items():
        y_info = yesterday_data.get(app_name)
        if not y_info:
            continue
        # 判斷版本號或更新時間是否不同
        if (
            today_info.get("version") != y_info.get("version")
            or today_info.get("updated") != y_info.get("updated")
        ):
            updates[app_name] = dict(today_info)
            updates[app_name]["event"] = "版本更新"
    return updates

def process_date_pair(country, platform, chart, today_str, yday_str):
    """處理單一國家、平台、榜單的特定日期比對"""
    
    # 1. 載入今日與昨日榜單資料
    today_rank_data = load_rank_data(country, today_str, chart, platform)
    yesterday_rank_data = load_rank_data(country, yday_str, chart, platform)
    
    if not today_rank_data or not yesterday_rank_data:
        print(f"[WARN] {country} {platform.upper()} {chart}: 缺少 {today_str} 或 {yday_str} 榜單資料，跳過。")
        # [修正 1] 確保在缺少榜單資料時回傳兩個值
        return {}, {} 
    
    # 2. 確定需要查詢版本資訊的 App ID 集合 (Top Limit)
    union_apps = {}
    
    # 收集最新日期 (today_str) 榜單上的 Top N
    for r in today_rank_data.get("rows", [])[:TOP_LIMIT]:
        app_id = r.get("app_id")
        app_name = r.get("app_name")
        if app_id and app_name:
            union_apps[str(app_id)] = app_name

    if not union_apps:
        # [修正 2] 確保在 App 集合為空時回傳兩個值
        return {}, {} 
        
    # 3. 載入昨日已儲存的版本資料 (作為比對基線)
    yday_file = UPDATE_DIR / f"updates_{yday_str}.json"
    yesterday_update_data = read_json(yday_file).get(country, {}).get(platform, {}).get(chart, {})
    
    # 4. 查詢最新版本資訊 (Today's Metadata)
    today_data = {}
    for i, (app_id, app_name) in enumerate(union_apps.items(), start=1):
        if platform == "ios":
            
            info = fetch_ios_metadata(app_id)
            if not info:
                continue
                
            today_data[app_name] = {
                "version": info.get("version"),
                "updated": info.get("updated"),
                "releaseNotes": info.get("releaseNotes", ""),
                "app_id": info.get("app_id")
            }
            time.sleep(0.3)  # 避免請求過快被限流
        else:
            # TODO: 接入 Google Play 版本查詢 API
            pass

    # 5. 比較版本差異
    updates = detect_updates(today_data, yesterday_update_data)
    
    # 6. 回傳偵測到的更新，以及今天查詢到的版本資訊 (作為下一次比較的基準)
    return updates, today_data

def main():
    
    # 儲存所有日期對的結果，結構：{today_str: {country: {platform: {chart: updates}}}}
    all_results = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(dict))))
    
    # 儲存所有日期對的版本基準資料，結構：{today_str: {country: {platform: {chart: today_metadata}}}}
    all_metadata = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(dict))))
    
    print("=== 開始偵測版本更新事件 ===")
    
    # 修正: 讀取所有目標國家
    for country in TARGET_COUNTRIES:
        
        # 1. 載入日期清單
        dates = load_available_dates(country)
        # 確保有足夠的日期進行比較
        if not dates or len(dates) < 2:
            print(f"[WARN] {country}: 缺少足夠的可用日期 (至少需要 2 天)，跳過。")
            continue
            
        print(f"\n--- 處理 {country} ({len(dates)} 個可用日期) ---")
        
        # 2. 遍歷所有可比較的日期對 (dates[i] vs dates[i+1])
        for i in range(min(1, len(dates) - 1)):
            today_str = dates[i]
            yday_str = dates[i+1]
            
            for platform in PLATFORMS:
                if platform == "gp" and country in ["CN"]:
                    continue 
                
                for chart in CHARTS:
                    
                    # 這裡 process_date_pair 必須回傳兩個值
                    updates, today_metadata = process_date_pair(country, platform, chart, today_str, yday_str)
                    
                    # 儲存偵測結果 (updates)
                    if updates:
                        all_results[today_str][country][platform][chart] = updates
                        print(f"[OK] {country} {platform.upper()} {chart} ({today_str} vs {yday_str}): 偵測到 {len(updates)} 筆更新。")
                    else:
                        print(f"[INFO] {country} {platform.upper()} {chart} ({today_str} vs {yday_str}): 無更新。")
                        
                    # 儲存版本資訊 (metadata) - 作為下次比較的基準
                    if today_metadata:
                        all_metadata[today_str][country][platform][chart] = today_metadata

    # 3. 輸出結果與基準檔案
    generated_files = []
    
    # 遍歷所有有更新或有新 metadata 的日期
    for today_str in sorted(all_results.keys() | all_metadata.keys()):
        
        country_updates = all_results.get(today_str, {})
        
        # 檢查該日期是否有任何實際的更新事件
        has_updates = any(chart_updates for country_updates in country_updates.values() 
                          for platform_updates in country_updates.values()
                          for chart_updates in platform_updates.values())

        if has_updates:
            # 輸出更新偵測結果 (updates_YYYYMMDD.json)
            out_updates_path = UPDATE_DIR / f"updates_{today_str}.json"
            
            # 將 defaultdict 轉換為標準 dict 輸出
            final_updates_result = json.loads(json.dumps(country_updates))
            
            write_json(out_updates_path, final_updates_result)
            generated_files.append(out_updates_path.name)
            
        # 同時將該日期的版本資訊（Metadata）寫入，作為下次執行的「昨日」基準
        # 即使沒有 updates，只要有 metadata 就要寫入，確保下一次比較有基準
        if all_metadata[today_str]:
            out_metadata_path = UPDATE_DIR / f"metadata_cache_{today_str}.json"
            final_metadata_result = json.loads(json.dumps(all_metadata[today_str]))
            write_json(out_metadata_path, final_metadata_result)


    print("\n=== Summary ===")
    if generated_files:
        print(f"✅ 成功生成以下更新報告：{', '.join(generated_files)}")
    else:
        print("⚠️ 無任何更新報告產生。")

if __name__ == "__main__":
    main()
