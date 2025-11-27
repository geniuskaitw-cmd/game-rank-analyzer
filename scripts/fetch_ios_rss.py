import json, datetime, pathlib, requests
from collections import defaultdict, Counter

# === Google Sheet 設定 ===
SHEET_ID = "1R-F71n6UVU528QVZmqmRLLgwmQUQpr6TtnBSwkjPG24"
SHEET_NAME = "RawData"
API_URL = f"https://opensheet.elk.sh/{SHEET_ID}/{SHEET_NAME}"

# === 路徑設定 ===
DATA_DIR = pathlib.Path("data")
RANKS_DIR = DATA_DIR / "ranks"
LATEST_DIR = DATA_DIR / "latest"
RANKS_DIR.mkdir(parents=True, exist_ok=True)
LATEST_DIR.mkdir(parents=True, exist_ok=True)

def safe_int(v, default=0):
    try:
        return int(float(v))
    except Exception:
        return default

def normalize_chart(chart_name):
    """辨識榜單類型（支援繁中、簡中、英文）"""
    name = str(chart_name).lower()
    if any(k in name for k in ["免費", "免费", "free"]):
        return "top_free"
    elif any(k in name for k in ["暢銷", "畅销", "營收", "grossing", "revenue"]):
        return "top_grossing"
    else:
        return "top_other"

def normalize_country(cc):
    cc = str(cc).strip().upper()
    return cc if cc else "TW"

def parse_date(date_str):
    """多格式日期解析"""
    s = str(date_str).strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None

def read_json(path, default_value=None):
    """
    安全讀取 JSON 檔案，不存在或錯誤則回傳預設值。
    修正: 讓呼叫者可以指定預設值。
    """
    if default_value is None:
        default_value = {}
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_value

def load_prev_rank(platform, country, chart, date_obj):
    """載入前一天榜單，用於 delta 計算"""
    date_str = date_obj.strftime("%Y%m%d")
    folder = RANKS_DIR / country
    
    # 讀取可用的日期清單
    avail_path = folder / f"available_dates_{country}.json"
    # [修正] 確保 dates 是一個列表，即使檔案不存在或讀取失敗
    dates = read_json(avail_path, default_value=[]) 
    
    try:
        current_date_index = dates.index(date_str)
        if current_date_index + 1 < len(dates):
            prev_date_str = dates[current_date_index + 1]
        else:
            return None # 找不到前一日數據
    except ValueError:
        # 當前日期可能首次被處理，不在可用清單中。
        # 嘗試尋找比 date_str 小的第一個日期 (dates 已排序 descending)
        prev_date_str = None
        for d in dates:
            if d < date_str:
                prev_date_str = d
                break
        
        if not prev_date_str:
            return None
    except AttributeError:
        # 避免非 list 物件的錯誤
        return None

    # 載入前一日榜單
    prefix = platform.lower()
    filename = f"{prefix}_{country.lower()}_{chart}_{prev_date_str}.json"
    prev_path = folder / filename
    
    prev_data = read_json(prev_path)
    if not prev_data:
        return None
        
    # 建立 app_id 到 rank 的映射
    return {r["app_id"]: r["rank"] for r in prev_data.get("rows", [])}


def write_json(platform, country, chart, date_obj, rows, type_counts):
    """輸出單一榜單 JSON 檔案"""
    folder = RANKS_DIR / country
    folder.mkdir(parents=True, exist_ok=True)
    date_str = date_obj.strftime("%Y%m%d")

    payload = {
        "date": date_obj.isoformat(),
        "platform": platform,
        "country": country,
        "chart": chart,
        "type_counts": type_counts,
        "rows": rows,
    }

    filename = f"{platform.lower()}_{country.lower()}_{chart}_{date_str}.json"
    filepath = folder / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[OK] {filepath} ({len(rows)} rows)")

    # 寫出最新榜單 (LATEST_DIR)
    latest = LATEST_DIR / f"{platform.lower()}_{country.lower()}_{chart}.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return date_str

def update_available_dates(country, new_date):
    """更新 available_dates_xx.json"""
    folder = RANKS_DIR / country
    folder.mkdir(parents=True, exist_ok=True) 
    path = folder / f"available_dates_{country}.json"

    # [修正] 確保 dates 是一個列表
    dates = read_json(path, default_value=[]) 

    if new_date not in dates:
        dates.insert(0, new_date)
    # 保持排序「新到舊」
    dates = sorted(set(dates), reverse=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dates[:50], f, ensure_ascii=False, indent=2)
    print(f"[OK] available_dates_{country}.json updated at {path}")

def fetch_and_generate():
    print(f"[INFO] Fetching JSON from: {API_URL}")
    r = requests.get(API_URL, timeout=30)
    r.raise_for_status()
    data = r.json()
    print(f"[INFO] Loaded {len(data)} rows")

    # 先找出資料內所有有效日期
    all_dates = [parse_date(row.get("日期", "")) for row in data if parse_date(row.get("日期", ""))]
    if not all_dates:
        print("⚠️ 無有效日期欄位，請確認 Google Sheet。")
        return
    latest_date = max(all_dates)
    print(f"[INFO] 最新日期為：{latest_date}")

    grouped = defaultdict(list)
    for row in data:
        date_obj = parse_date(row.get("日期", ""))
        if not date_obj:
            continue

        platform = row.get("平台", "iOS")
        country = normalize_country(row.get("國家", "TW"))
        chart = normalize_chart(row.get("排行榜類別", "暢銷榜"))
        
        # === 修正：統一處理平台名稱，提高識別容錯性 ===
        platform_str = str(platform).lower().strip() if platform else "ios"
        
        if "google" in platform_str or "gp" in platform_str:
            # 判斷為 Google Play 平台
            platform = "gp"
        elif "ios" in platform_str or "app store" in platform_str:
            # 判斷為 iOS/App Store 平台
            platform = "ios"
        else:
            # 如果還是無法識別，預設為 ios (以兼容舊有數據或未知錯誤)
            platform = "ios"
        # === 修正結束 ===

        key = (platform, country, chart, date_obj)

        app_id = str(row.get("遊戲ID編碼", "")).strip()
        app_name = str(row.get("遊戲名稱", "")).strip()
        developer = str(row.get("開發商", "")).strip()
        genre = str(row.get("子類別", "Games")).strip()
        rank = safe_int(row.get("排名") or row.get("總榜排名") or 0, 0)

        grouped[key].append({
            "rank": rank,
            "app_id": app_id,
            "app_name": app_name,
            "app_name_zh": app_name,
            "developer": developer,
            "genre": genre or "Games",
            "delta": 0,
            "alert": False,
            "ai_type": None,
        })

    if not grouped:
        print("⚠️ No valid groups found. Please check sheet columns.")
        return

    generated_dates = set()

    # 第二階段：計算 delta 並輸出 JSON
    for (platform, country, chart, date_obj), rows in grouped.items():
        rows = sorted(rows, key=lambda x: x["rank"] or 9999)
        type_counts = dict(Counter([r["genre"] for r in rows if r["genre"]]))

        # --- 新增 Delta 計算邏輯 ---
        prev_rank_map = load_prev_rank(platform, country, chart, date_obj)
        if prev_rank_map:
            for r in rows:
                aid = r["app_id"]
                current_rank = r["rank"]
                prev_rank = prev_rank_map.get(aid)
                
                if prev_rank and current_rank:
                    r["delta"] = prev_rank - current_rank
        
        # 必須在計算完 delta 後再更新 available_dates，否則 load_prev_rank 會出錯
        date_str = date_obj.strftime("%Y%m%d")
        update_available_dates(country, date_str) 
        
        write_json(platform, country, chart, date_obj, rows, type_counts)
        generated_dates.add((country, date_str))

    print("\n=== Summary ===")
    for cc, dt in sorted(generated_dates):
        print(f"[OK] {cc} - {dt}")
    print("✅ All JSON generated successfully.")

if __name__ == "__main__":
    try:
        fetch_and_generate()
    except Exception as e:
        print(f"Error: {e}")
