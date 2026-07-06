from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import sqlite3
import os
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

app = FastAPI()

def send_admin_notification(text):
    if BOT_TOKEN and ADMIN_CHAT_ID:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        try:
            requests.post(url, data={"chat_id": ADMIN_CHAT_ID, "text": text})
        except Exception as e:
            print(f"Failed to send admin notification: {e}")

# Базовый путь
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "backend", "database.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# Инициализация БД
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Читаем схему из файла и выполняем
    with open(os.path.join(BASE_DIR, "backend", "schema.sql"), "r", encoding="utf-8") as f:
        schema = f.read()
    cursor.executescript(schema)
        
    # Засеиваем тестовыми данными, если пусто
    if cursor.execute("SELECT count(*) FROM listings").fetchone()[0] == 0:
        seed_demo = os.getenv("SEED_DEMO_DATA", "false").lower() == "true"
        if seed_demo:
            expires_at = datetime.now() + timedelta(days=7)
            cursor.execute("""
                INSERT INTO listings (telegram_user_id, telegram_username, lat, lng, price_per_person, people_needed, has_wifi, has_ac, status, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (000000000, "demo_user", 41.2995, 69.2401, 1500000, 1, 1, 1, 'active', expires_at))
    conn.commit()
    conn.close()

init_db()

# Функция очистки устаревших объявлений
def delete_expired_listings():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("UPDATE listings SET status = 'expired' WHERE expires_at < ?", (now,))
    conn.commit()
    conn.close()
    print(f"[{now}] Пометка старых объявлений как 'expired' выполнена.")

# Запуск планировщика
scheduler = BackgroundScheduler()
scheduler.add_job(delete_expired_listings, 'interval', days=1)
scheduler.start()

# API
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_photo_path_column(cursor):
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(listing_photos)").fetchall()}
    if "file_path" in columns:
        return "file_path"
    if "photo_path" in columns:
        return "photo_path"
    return None

def normalize_photo_path(path):
    if not path:
        return None
    normalized = str(path).replace("\\", "/")
    base = BASE_DIR.replace("\\", "/")
    if normalized.startswith(base):
        normalized = normalized[len(base):]
    if not normalized.startswith("/"):
        normalized = "/" + normalized.lstrip("/")
    return normalized

def get_listing_photos(cursor, listing_ids):
    if not listing_ids:
        return {}
    photo_column = get_photo_path_column(cursor)
    if not photo_column:
        return {listing_id: [] for listing_id in listing_ids}

    placeholders = ",".join("?" for _ in listing_ids)
    rows = cursor.execute(
        f"SELECT listing_id, {photo_column} AS path FROM listing_photos WHERE listing_id IN ({placeholders})",
        listing_ids,
    ).fetchall()

    photos_by_listing = {listing_id: [] for listing_id in listing_ids}
    for row in rows:
        photo = normalize_photo_path(row["path"])
        if photo:
            photos_by_listing.setdefault(row["listing_id"], []).append(photo)
    return photos_by_listing

@app.get("/api/listings")
def get_listings(listing_type: str | None = None, district: str | None = None, university: str | None = None):
    conn = get_db()
    cursor = conn.cursor()
    
    query = "SELECT * FROM listings WHERE status = 'active'"
    params = []
    if listing_type:
        query += " AND listing_type = ?"
        params.append(listing_type)
    if district:
        query += " AND district = ?"
        params.append(district)
    if university:
        query += " AND university = ?"
        params.append(university)
        
    listings = cursor.execute(query, params).fetchall()
    photos_by_listing = get_listing_photos(cursor, [row["id"] for row in listings])
    
    results = []
    for row in listings:
        results.append({
            "id": row["id"],
            "listing_type": row["listing_type"],
            "telegram_username": row["telegram_username"],
            "university": row["university"],
            "district": row["district"],
            "housing_type": row["housing_type"],
            "room_count": row["room_count"],
            "description": row["description"],
            "phone_number": row["phone_number"],
            "lat": row["lat"],
            "lng": row["lng"],
            "price": row["price_per_person"],
            "people_needed": row["people_needed"],
            "has_wifi": row["has_wifi"],
            "has_ac": row["has_ac"],
            "has_washing_machine": row["has_washing_machine"],
            "no_landlord_in_yard": row["no_landlord_in_yard"],
            "near_metro": row["near_metro"],
            "status": row["status"],
            "photos": photos_by_listing.get(row["id"], [])
        })
    conn.close()
    return results

@app.get("/api/listings/{listing_id}")
def get_listing_detail(listing_id: int):
    conn = get_db()
    cursor = conn.cursor()
    listing = cursor.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not listing:
        conn.close()
        return {"error": "Not found"}
    
    photos = get_listing_photos(cursor, [listing_id]).get(listing_id, [])
    conn.close()
    
    data = {
        "id": listing["id"],
        "listing_type": listing["listing_type"],
        "university": listing["university"],
        "district": listing["district"],
        "housing_type": listing["housing_type"],
        "room_count": listing["room_count"],
        "description": listing["description"],
        "price": listing["price_per_person"],
        "people_needed": listing["people_needed"],
        "photos": photos,
        "telegram_username": listing["telegram_username"]
    }
    if listing["phone_number"]:
        data["phone_number"] = listing["phone_number"]
        
    return data

@app.post("/api/report")
async def report_listing(listing_id: int, reason: str, reporter_id: int = 0):
    conn = get_db()
    cursor = conn.cursor()
    # 1. Вставляем жалобу
    report_columns = {row[1] for row in cursor.execute("PRAGMA table_info(reports)").fetchall()}
    reporter_column = None
    if "reporter_telegram_id" in report_columns:
        reporter_column = "reporter_telegram_id"
    elif "reporter_telegram_user_id" in report_columns:
        reporter_column = "reporter_telegram_user_id"

    if reporter_column:
        cursor.execute(
            f"INSERT INTO reports (listing_id, reason, {reporter_column}) VALUES (?, ?, ?)",
            (listing_id, reason, reporter_id if reporter_id != 0 else 0),
        )
    else:
        cursor.execute("INSERT INTO reports (listing_id, reason) VALUES (?, ?)", (listing_id, reason))
    # 2. Увеличиваем счетчик
    cursor.execute("UPDATE listings SET report_count = report_count + 1 WHERE id = ?", (listing_id,))
    # 3. Проверяем лимит
    cursor.execute("SELECT report_count FROM listings WHERE id = ?", (listing_id,))
    count = cursor.fetchone()[0]
    if count >= 3:
        cursor.execute("UPDATE listings SET status = 'hidden_pending_review' WHERE id = ?", (listing_id,))
        # Получаем владельца объявления для бана
        cursor.execute("SELECT telegram_user_id FROM listings WHERE id = ?", (listing_id,))
        owner_row = cursor.fetchone()
        if owner_row:
            owner_id = owner_row[0]
            banned_columns = {row[1] for row in cursor.execute("PRAGMA table_info(banned_users)").fetchall()}
            if "reason" in banned_columns:
                cursor.execute(
                    "INSERT OR IGNORE INTO banned_users (telegram_user_id, reason) VALUES (?, ?)",
                    (owner_id, f"3+ jalo, oxirgisi: {reason}")
                )
            else:
                cursor.execute(
                    "INSERT OR IGNORE INTO banned_users (telegram_user_id) VALUES (?)",
                    (owner_id,)
                )
        print(f"Listing {listing_id} hidden. Author {owner_row[0] if owner_row else '?'} banned.")
        send_admin_notification(f"Объявление {listing_id} скрыто, автор {owner_row[0] if owner_row else '?'} забанен.\nПричина: {reason}")
    
    conn.commit()
    conn.close()
    return {"message": "Жалоба принята"}

# API (оставляем без изменений)
# ...

# API (оставляем без изменений)
# ...

# Статика и маршрутизация
@app.get("/")
async def get_home():
    return FileResponse(os.path.join(FRONTEND_DIR, "landing.html"))

@app.get("/xarita")
async def get_map():
    return FileResponse(os.path.join(FRONTEND_DIR, "map.html"))

@app.get("/about")
async def get_about():
    return FileResponse(os.path.join(FRONTEND_DIR, "about.html"))

# Монтируем статику с префиксом /static, чтобы не перекрывать корни
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
