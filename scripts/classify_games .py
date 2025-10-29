import os
import json
import datetime
from pathlib import Path
from collections import Counter

# === 路徑與常數設定 ===
DATA_DIR = Path("data")
RANKS_DIR = DATA_DIR / "ranks"
OUTPUT_SUFFIX = "_classified.json"

# 前端定義的統一 AI 分類 (7 種)
AI_CATEGORIES = ["角色扮演", "社交賭場", "策略對戰", "動作競技", "模擬沙盒", "休閒益智", "其他"]

def read_json(path):
    """安全讀取 JSON 檔案，不存在或錯誤則回傳空字典"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def classify_game(app):
    """
    模擬 AI 類型分類：強制歸類到 AI_CATEGORIES 中的一種。
    這是當遊戲沒有手動覆寫時的備用邏輯。
    """
    name = app.get("app_name", "").lower()
    genre = app.get("genre", "").lower()

    # 確保所有邏輯都指向 AI_CATEGORIES 中的一員
    if any(k in genre for k in ["rpg", "adventure", "role"]):
        return "角色扮演"
    elif any(k in name for k in ["casino", "poker", "slot", "賭場"]):
        return "社交賭場"
    elif any(k in name for k in ["strategy", "war", "clash", "empire", "對戰", "戰鬥"]):
        return "策略對戰"
    elif any(k in name for k in ["action", "battle", "shooter", "moba", "動作", "競技"]):
        return "動作競技"
    elif any(k in name for k in ["sim", "tycoon", "farm", "city", "模擬", "沙盒"]):
        return "模擬沙盒"
    elif any(k in name for k in ["merge", "match", "puzzle", "idle", "休閒", "益智"]):
        return "休閒益智"
    else:
        # 如果以上條件都沒有命中，則歸入「其他」，確保所有遊戲都被分類
        return "其他"

def process_country_folder(country_folder: Path, override_map: dict):
    # 使用 glob 匹配 ios_* 或 gp_* 的榜單檔案
    for json_file in sorted(country_folder.glob("*.json")):
        if json_file.name.endswith(OUTPUT_SUFFIX) or json_file.name.startswith("available_dates_"):
            continue  # 跳過已分類檔和日期檔

        # 確保只處理 ios_ 或 gp_ 開頭的原始榜單檔
        if not json_file.name.startswith(("ios_", "gp_")):
             continue
        
        payload = read_json(json_file)
        if not payload:
            print(f"[WARN] 無法載入或解析 {json_file.name}，略過。")
            continue

        rows = payload.get("rows", [])
        chart = payload.get("chart", "")
        country = payload.get("country", "")
        date_str = payload.get("date", "")
        
        try:
            date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            print(f"[WARN] {json_file.name} 缺少有效日期欄位，略過。")
            continue

        print(f"[INFO] 正在分類排行榜檔案：{json_file.name}")

        # === 進行分類 (優先使用覆寫) ===
        for app in rows:
            app_id = app.get("app_id")
            
            # 判斷 1：檢查是否有手動覆寫的類型 (最高優先級)
            if app_id in override_map:
                app["ai_type"] = override_map[app_id]
            else:
                # 判斷 2：執行模擬 AI 分類 (次級優先級)
                app["ai_type"] = classify_game(app)

        # === 統計類型與百分比 ===
        # 1. 原始類型統計 (使用原本的 genre 欄位)
        type_counts_raw = dict(Counter([r["genre"] for r in rows if r.get("genre")]))
        
        # 2. AI/覆寫類型統計 (使用 ai_type 欄位)
        type_counts_ai = dict(Counter([r["ai_type"] for r in rows if r.get("ai_type")]))
        
        # 3. 計算 AI 類型百分比
        total_ai_classified = sum(type_counts_ai.values())
        type_percentages_ai = {}
        if total_ai_classified > 0:
            for k, v in type_counts_ai.items():
                # 計算百分比並四捨五入到整數
                type_percentages_ai[k] = round(v / total_ai_classified * 100)

        # === 輸出 ===
        # 根據檔名前綴確定平台，確保輸出檔名與 fetch_ios_rss.py 輸出匹配
        platform = json_file.name.split('_')[0]
        
        outfile = json_file.parent / f"{platform}_{country.lower()}_{chart}_{date_obj.strftime('%Y%m%d')}_classified.json"
        
        # 將所有統計數據寫入 payload
        payload["type_counts"] = type_counts_raw
        payload["type_counts_ai"] = type_counts_ai
        payload["type_percentages_ai"] = type_percentages_ai # 新增百分比

        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print(f"[OK] 已輸出分類檔案：{outfile.name}")

def main():
    print("=== 開始分類排行榜檔案 ===")
    if not RANKS_DIR.exists():
        print("❌ 找不到 data/ranks 資料夾")
        return

    # 載入手動覆寫地圖
    override_path = DATA_DIR / "game_types.json"
    override_data = read_json(override_path)
    if override_data:
        print(f"[INFO] 成功載入 {len(override_data)} 筆遊戲類型覆寫數據。")
    
    # 遍歷所有國家資料夾
    for cc_folder in RANKS_DIR.iterdir():
        if cc_folder.is_dir():
            print(f"\n--- 處理國家資料夾: {cc_folder.name} ---")
            process_country_folder(cc_folder, override_data)

    print("✅ 所有國家分類完成")

if __name__ == "__main__":
    main()
