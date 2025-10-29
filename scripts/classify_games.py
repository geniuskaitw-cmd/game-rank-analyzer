import os
import json
import datetime
from pathlib import Path
from collections import Counter
import time

# === 新增 AI 相關模組 ===
from openai import OpenAI
import re

# === 路徑與常數設定 ===
DATA_DIR = Path("data")
RANKS_DIR = DATA_DIR / "ranks"
OUTPUT_SUFFIX = "_classified.json"
# 遊戲類型快取檔案 (讀取與寫入)
GAME_TYPES_CACHE_PATH = DATA_DIR / "game_types.json"

# 前端定義的統一 AI 分類 (7 種)，這是 AI 必須回答的唯一選項
AI_CATEGORIES = ["角色扮演", "社交賭場", "策略對戰", "動作競技", "模擬沙盒", "休閒益智", "其他"]

# === OpenAI AI 初始化 ===
# 從 GitHub Actions 傳入的環境變數讀取 API Key
api_key = os.getenv("OPENAI_API_KEY")
client = None
if api_key:
    try:
        client = OpenAI(api_key=api_key)
        print("[INFO] OpenAI Client 成功初始化。")
    except Exception as e:
        print(f"[FATAL ERROR] OpenAI Client 初始化失敗: {e}")
else:
    print("[FATAL ERROR] 找不到 OPENAI_API_KEY 環境變數。AI 功能將無法運作。")

# --- 工具函式 ---

def read_json(path):
    """安全讀取 JSON 檔案，不存在或錯誤則回傳空字典"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(path, data):
    """安全寫入 JSON 檔案"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[INFO] 成功將 {len(data)} 筆快取資料回存至 {path}")
    except Exception as e:
        print(f"[FATAL ERROR] 無法寫入 JSON 檔案 {path}: {e}")

def get_ai_classification(app_name: str, app_genre: str):
    """
    呼叫 OpenAI API 取得遊戲分類。
    """
    if not client:
        print(f"[WARN] OpenAI Client 未初始化，跳過 AI 分類: {app_name}")
        return "其他" # 如果 AI 服務失效，則歸類為「其他」

    # 建立一個非常嚴格的 Prompt，強制 AI 只能回答七種類型中的一種
    prompt = f"""
    請根據以下遊戲名稱和類型，判斷它屬於哪一個主要分類。
    遊戲名稱: "{app_name}"
    遊戲類型(Genre): "{app_genre}"

    請「只回答」以下七個選項中的「一個」：
    1. 角色扮演 (包含 RPG, 冒險, MMORPG)
    2. 社交賭場 (包含 撲克, 老虎機, 賭博, 賓果)
    3. 策略對戰 (包含 戰爭, 塔防, SLG, 帝國, 三國)
    4. 動作競技 (包含 射擊, MOBA, 格鬥, 運動, 賽車)
    5. 模擬沙盒 (包含 經營, 建造, 農場, 模擬器, 開放世界)
    6. 休閒益智 (包含 三消, 合併, 填字, 益智, 消除, 放置)
    7. 其他 (若以上皆非)

    請「只輸出」分類名稱，不要包含任何數字、標點符號或額外說明。
    """

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini", # 使用最新且快速的 gpt-4o-mini 模型
            messages=[
                {"role": "system", "content": "你是一個精準的遊戲分類專家。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0, # 盡可能產生確定性的結果
            max_tokens=20 # 限制回答長度 (分類名稱通常很短)
        )
        
        # 取得 AI 的原始回答
        raw_response = completion.choices[0].message.content.strip()

        # 清理並驗證回答
        # 移除任何潛在的標點符號 (例如 1. 角色扮演)
        cleaned_response = re.sub(r"^\d+\.\s*", "", raw_response).strip() 

        # 檢查 AI 回答是否在我們的 7 種分類中
        if cleaned_response in AI_CATEGORIES:
            print(f"[AI OK] 遊戲: {app_name} -> AI 分類: {cleaned_response}")
            return cleaned_response
        else:
            # 如果 AI 回答的格式不對，例如："這是一款 角色扮演 遊戲"
            # 我們嘗試從回答中提取關鍵字
            for category in AI_CATEGORIES:
                if category in cleaned_response:
                    print(f"[AI WARN] AI 回答格式不標準 ({cleaned_response})，但成功提取: {category}")
                    return category
            
            # 如果 AI 回答不在列表中 (例如 "動作遊戲")，則強制歸類為「其他」
            print(f"[AI ERROR] AI 回答 '{raw_response}' 無法識別，強制歸類為「其他」")
            return "其他"

    except Exception as e:
        print(f"[AI FATAL] 呼叫 OpenAI API 失敗: {e}。遊戲 {app_name} 強制歸類為「其他」")
        return "其他"

def process_country_folder(country_folder: Path, game_type_cache: dict):
    # 使用 glob 匹配 ios_* 或 gp_* 的榜單檔案
    for json_file in sorted(country_folder.glob("*.json")):
        if json_file.name.endswith(OUTPUT_SUFFIX) or json_file.name.startswith("available_dates_"):
            continue  # 跳過已分類檔和日期檔
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

        # === 進行分類 (優先使用快取/覆寫) ===
        is_cache_updated = False # 標記快取是否被更動
        
        for app in rows:
            app_id = app.get("app_id")
            app_name = app.get("app_name", "")
            app_genre = app.get("genre", "")
            
            # 判斷 1：檢查是否在快取中 (最高優先級)
            if app_id in game_type_cache:
                app["ai_type"] = game_type_cache[app_id]
            else:
                # 判斷 2：如果不在快取中，呼叫 AI
                print(f"[AI REQ] 新遊戲: {app_name} (ID: {app_id})，開始呼叫 AI 分類...")
                ai_category = get_ai_classification(app_name, app_genre)
                
                app["ai_type"] = ai_category
                
                # 將 AI 的新結果存入快取，供下次使用
                game_type_cache[app_id] = ai_category
                is_cache_updated = True # 標記快取已被更新
                
                # 避免 API 呼叫過於頻繁
                time.sleep(1) 

        # === 統計類型與百分比 ===
        type_counts_raw = dict(Counter([r["genre"] for r in rows if r.get("genre")]))
        type_counts_ai = dict(Counter([r["ai_type"] for r in rows if r.get("ai_type")]))
        
        total_ai_classified = sum(type_counts_ai.values())
        type_percentages_ai = {}
        if total_ai_classified > 0:
            for k, v in type_counts_ai.items():
                type_percentages_ai[k] = round(v / total_ai_classified * 100)

        # === 輸出 ===
        platform = json_file.name.split('_')[0]
        outfile = json_file.parent / f"{platform}_{country.lower()}_{chart}_{date_obj.strftime('%Y%m%d')}_classified.json"
        
        payload["type_counts"] = type_counts_raw
        payload["type_counts_ai"] = type_counts_ai
        payload["type_percentages_ai"] = type_percentages_ai 

        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print(f"[OK] 已輸出分類檔案：{outfile.name}")
        
    # 回傳快取是否有被更新的狀態
    return is_cache_updated

def main():
    print("=== 開始使用 AI 分類排行榜檔案 ===")
    if not RANKS_DIR.exists():
        print("❌ 找不到 data/ranks 資料夾")
        return
    
    if not client:
        print("❌ OpenAI Client 未成功初始化，無法執行 AI 分類。")
        return

    # 載入遊戲類型快取 (包含人工覆寫)
    game_type_cache = read_json(GAME_TYPES_CACHE_PATH)
    if game_type_cache:
        print(f"[INFO] 成功載入 {len(game_type_cache)} 筆遊戲類型快取/覆寫數據。")
    
    cache_needs_saving = False # 總標記
    
    # 遍歷所有國家資料夾
    for cc_folder in RANKS_DIR.iterdir():
        if cc_folder.is_dir():
            print(f"\n--- 處理國家資料夾: {cc_folder.name} ---")
            # 傳入快取，並接收快取是否有被更新
            was_updated = process_country_folder(cc_folder, game_type_cache)
            if was_updated:
                cache_needs_saving = True

    # 如果在處理過程中，AI 增加了新的分類到快取中，則執行回存
    if cache_needs_saving:
        print("\n[INFO] 偵測到 AI 已新增分類，正在將快取回存至 game_types.json...")
        save_json(GAME_TYPES_CACHE_PATH, game_type_cache)
    else:
        print("\n[INFO] AI 未增加新分類，快取無需回存。")

    print("✅ 所有國家 AI 分類完成")

if __name__ == "__main__":
    main()
