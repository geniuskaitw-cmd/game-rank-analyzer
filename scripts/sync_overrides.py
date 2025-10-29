# -*- coding: utf-8 -*-
"""
sync_overrides.py
功能：
  - 從 Firebase Firestore 下載人工覆寫分類結果
  - 同步更新至 data/game_types.json
  - 加強安全性與 log 輸出
"""

import os
import json
import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# === Firestore 初始化 ===
CRED_PATH = os.getenv("FIREBASE_CRED_JSON", "firebase_key.json")
if not os.path.exists(CRED_PATH):
    raise FileNotFoundError(f"找不到憑證檔案: {CRED_PATH}")

cred = credentials.Certificate(CRED_PATH)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()

# === 路徑設定 ===
DATA_DIR = "data"
GAME_TYPES_PATH = os.path.join(DATA_DIR, "game_types.json")
os.makedirs(DATA_DIR, exist_ok=True)

def load_local_game_types():
    if not os.path.exists(GAME_TYPES_PATH):
        return {}
    with open(GAME_TYPES_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}

def save_game_types(data):
    with open(GAME_TYPES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def fetch_overrides():
    """從 Firebase 撈取 override 類別"""
    overrides = {}
    docs = db.collection("overrides").stream()
    for doc in docs:
        d = doc.to_dict()
        app_id = str(d.get("app_id") or "").strip()
        category = str(d.get("category") or "").strip()
        if app_id and category:
            overrides[app_id] = category
    print(f"[INFO] 從 Firebase 撈取 {len(overrides)} 筆覆寫資料")
    return overrides

def main():
    print("[INFO] 開始同步 Firebase overrides ...")
    local_types = load_local_game_types()
    overrides = fetch_overrides()

    updated = 0
    for app_id, new_cat in overrides.items():
        old_cat = local_types.get(app_id)
        if old_cat != new_cat:
            local_types[app_id] = new_cat
            updated += 1

    save_game_types(local_types)
    print(f"[OK] 已更新 {updated} 筆覆寫資料，共 {len(local_types)} 筆快取。")
    print(f"[TIME] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 完成同步。")

if __name__ == "__main__":
    main()
