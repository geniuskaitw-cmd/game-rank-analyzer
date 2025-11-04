#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_rank_movers.py
功能：分析所有歷史榜單日期的名次上升與下降。
  - 遍歷 available_dates_XX.json 中所有相鄰日期對。
  - 輸出：movers_YYYYMMDD.json (YYYYMMDD 為較新的日期)
"""

import os, json, pathlib, datetime
from collections import defaultdict

# --- 路徑與常數設定 (修正後的地圖) ---
BASE_DIR = pathlib.Path(".").resolve() 
RANKS_DIR = BASE_DIR / "data" / "ranks"
MOVERS_DIR = BASE_DIR / "data" / "movers"
MOVERS_DIR.mkdir(parents=True, exist_ok=True)

TARGET_COUNTRIES = ["TW", "US", "CN", "TH", "PH"]
TARGET_CHARTS = ["top_grossing", "top_free"]
PLATFORMS = ["ios", "gp"] 

# --- 工具函式 ---
def read_json(path):
    """安全讀取 JSON 檔案，不存在或錯誤則回傳空字典"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def load_available_dates(country: str):
    """讀取某國可用的日期清單"""
    path = RANKS_DIR / country / f"available_dates_{country}.json"
    # 確保回傳值是列表
    data = read_json(path)
    return data if isinstance(data, list) else []

def load_rank(country, date_str, chart, platform="ios"):
    """載入指定國家、日期、榜單與平台的排行榜 JSON 檔案。"""
    prefix = platform.lower()
    path = RANKS_DIR / country / f"{prefix}_{country.lower()}_{chart}_{date_str}.json"
    if not path.exists():
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None

def analyze_date_pair_movers(country, chart, platform, today_str, yesterday_str):
    """比較特定日期對的榜單，找出名次大幅變動者"""
    
    today_data = load_rank(country, today_str, chart, platform)
    yesterday_data = load_rank(country, yesterday_str, chart, platform)
    
    if not today_data or not yesterday_data:
        # 如果任一天數據缺失，則跳過
        return []

    # 建立昨日 app_id 到 rank 的映射
    prev_map = {r["app_id"]: r["rank"] for r in yesterday_data["rows"]}
    movers = []
    
    for r in today_data["rows"]:
        aid = r["app_id"]
        # 僅考慮昨日存在榜單上的 app
        if aid not in prev_map:
            continue
            
        delta = prev_map[aid] - r["rank"]
        
        # 名次變動絕對值大於等於 10 才記錄
        if abs(delta) >= 10:
            movers.append({
                "name": r["app_name"],
                "delta": delta,
                "direction": "rise" if delta > 0 else "fall"
            })

    # 依變動幅度絕對值排序，取 Top 10
    movers.sort(key=lambda x: -abs(x["delta"]))
    return movers[:10]

def main():
    # 最終輸出結果結構: { date_str: { country: { chart: { platform_chart: [movers] } } } }
    # 這裡將 all_results 的結構調整為 { date_str: { country: { platform: { chart: [movers] } } } }
    # 以便於儲存時能正確區分平台和榜單
    all_results = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))) 

    print("=== 開始分析歷史名次變動 (Movers) ===")
    
    for cc in TARGET_COUNTRIES:
        
        dates = load_available_dates(cc)
        if len(dates) < 2:
            print(f"[WARN] {cc}: 缺少足夠的可用日期 (至少需要 2 天)，跳過。")
            continue
            
        print(f"\n--- 處理 {cc} ({len(dates)} 個可用日期) ---")
        
        # 遍歷所有可比較的日期對 (dates[i] vs dates[i+1])
        for i in range(len(dates) - 1):
            today_str = dates[i]    # 較新的日期
            yesterday_str = dates[i+1] # 較舊的日期
          
            # 由於我們要輸出包含 ios/gp 的綜合結果，建議先手動刪除 data/movers/ 下舊的 movers_YYYYMMDD.json
            out_path = MOVERS_DIR / f"movers_{today_str}.json"
            # 為了確保涵蓋 GP 數據，如果檔案已存在，我們仍然會重新計算，但這裡先註釋掉跳過邏輯。
            # if out_path.exists():
            #     print(f"[SKIP] {cc}: movers_{today_str}.json 已存在，跳過計算。")
            #     continue
            
            for platform in PLATFORMS:
                
                for chart in TARGET_CHARTS:
                    
                    movers = analyze_date_pair_movers(cc, chart, platform, today_str, yesterday_str)
                    
                    if movers:
                        # 修正：將結果儲存到正確的層級: all_results[date][country][platform][chart]
                        all_results[today_str][cc.lower()][platform][chart] = movers
                        print(f"[OK] {cc} {chart} ({platform.upper()}): {len(movers)} movers detected ({today_str} vs {yesterday_str}).")
                    else:
                        print(f"[INFO] {cc} {chart} ({platform.upper()}): No movers detected ({today_str} vs {yesterday_str}).")


    # 輸出所有日期的結果檔案
    generated_files = []
    
    for today_str, country_data in all_results.items():
        
        # 準備最終輸出結構: { country: { platform: { chart: [movers] } } }
        final_result = {}
        for country_code, platform_data in country_data.items():
            final_result[country_code] = {}
            for platform, chart_data in platform_data.items():
                # 將 defaultdict(list) 轉換為標準 dict
                final_result[country_code][platform] = dict(chart_data)

        out_path = MOVERS_DIR / f"movers_{today_str}.json"
        
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
            
        generated_files.append(out_path.name)
    
    print("\n=== Summary ===")
    if generated_files:
        print(f"✅ 成功生成以下 Movers 報告：{', '.join(generated_files)}")
    else:
        print("⚠️ 無任何 Movers 報告產生。")

if __name__ == "__main__":
    main()
