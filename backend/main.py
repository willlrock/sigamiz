from fastapi import FastAPI, HTTPException
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

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "backend", "database.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# Database initialization
def ensure_columns(cursor, table_name, columns):
    existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for column_name, column_sql in columns.items():
        if column_name not in existing:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
            existing.add(column_name)

def migrate_db(cursor):
    ensure_columns(cursor, "listings", {
        "listing_type": "TEXT NOT NULL DEFAULT 'seek'",
        "university": "TEXT",
        "district": "TEXT",
        "housing_type": "TEXT",
        "description": "TEXT",
        "phone_number": "TEXT",
        "room_count": "INTEGER",
        "has_washing_machine": "BOOLEAN DEFAULT 0",
        "no_landlord_in_yard": "BOOLEAN DEFAULT 0",
        "near_metro": "BOOLEAN DEFAULT 0",
        "report_count": "INTEGER DEFAULT 0",
        "created_at": "DATETIME",
    })
    ensure_columns(cursor, "listing_photos", {
        "file_path": "TEXT",
        "sort_order": "INTEGER DEFAULT 0",
    })
    ensure_columns(cursor, "reports", {
        "reporter_telegram_id": "INTEGER",
        "reason": "TEXT",
        "created_at": "DATETIME",
    })
    ensure_columns(cursor, "banned_users", {
        "reason": "TEXT",
        "banned_at": "DATETIME",
    })

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Apply base schema and lightweight migrations for existing SQLite files.
    with open(os.path.join(BASE_DIR, "backend", "schema.sql"), "r", encoding="utf-8") as f:
        schema = f.read()
    cursor.executescript(schema)
    migrate_db(cursor)
        
    # Seed demo data only when explicitly enabled.
    if cursor.execute("SELECT count(*) FROM listings").fetchone()[0] == 0:
        seed_demo = os.getenv("SEED_DEMO_DATA", "false").lower() == "true"
        if seed_demo:
            expires_at = datetime.now() + timedelta(days=7)
            cursor.execute("""
                INSERT INTO listings (
                    telegram_user_id, telegram_username, listing_type, university, district, housing_type, description,
                    lat, lng, price_per_person, people_needed, has_wifi, has_ac, has_washing_machine,
                    no_landlord_in_yard, near_metro, status, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                0, "demo_user", "offer", "TATU", "Yunusobod", "Kvartira",
                "Demo e'lon: 2 ta talaba uchun joy bor.", 41.2995, 69.2401,
                1500000, 1, 1, 1, 1, 1, 1, "active", expires_at
            ))
    conn.commit()
    conn.close()

init_db()

# Expiration cleanup
def delete_expired_listings():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("UPDATE listings SET status = 'expired' WHERE expires_at < ?", (now,))
    conn.commit()
    conn.close()
    print(f"[{now}] Expired listings marked as expired.")

# Scheduler
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
    if "file_path" in columns and "photo_path" in columns:
        return "COALESCE(file_path, photo_path)"
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
    owner_row = cursor.execute(
        "SELECT telegram_user_id, report_count FROM listings WHERE id = ?",
        (listing_id,),
    ).fetchone()
    if not owner_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Listing not found")

    report_columns = {row[1] for row in cursor.execute("PRAGMA table_info(reports)").fetchall()}
    reporter_column = None
    if "reporter_telegram_user_id" in report_columns:
        reporter_column = "reporter_telegram_user_id"
    elif "reporter_telegram_id" in report_columns:
        reporter_column = "reporter_telegram_id"

    if reporter_id and reporter_column:
        duplicate = cursor.execute(
            f"SELECT 1 FROM reports WHERE listing_id = ? AND {reporter_column} = ?",
            (listing_id, reporter_id),
        ).fetchone()
        if duplicate:
            conn.close()
            return {"message": "Shikoyat allaqachon qabul qilingan"}

    if reporter_column:
        cursor.execute(
            f"INSERT INTO reports (listing_id, reason, {reporter_column}) VALUES (?, ?, ?)",
            (listing_id, reason, reporter_id if reporter_id != 0 else 0),
        )
    else:
        cursor.execute("INSERT INTO reports (listing_id, reason) VALUES (?, ?)", (listing_id, reason))

    cursor.execute("UPDATE listings SET report_count = report_count + 1 WHERE id = ?", (listing_id,))
    cursor.execute("SELECT report_count FROM listings WHERE id = ?", (listing_id,))
    count = cursor.fetchone()[0]
    if count >= 3:
        cursor.execute("UPDATE listings SET status = 'hidden_pending_review' WHERE id = ?", (listing_id,))
        print(f"Listing {listing_id} hidden for admin review after {count} reports.")
        send_admin_notification(
            f"E'lon {listing_id} admin tekshiruviga yashirildi.\n"
            f"Muallif: {owner_row['telegram_user_id']}\n"
            f"Shikoyatlar: {count}\n"
            f"Oxirgi sabab: {reason}"
        )

    conn.commit()
    conn.close()
    return {"message": "Shikoyat qabul qilindi"}

# Static pages
@app.get("/")
async def get_home():
    return FileResponse(os.path.join(FRONTEND_DIR, "landing.html"))

@app.get("/xarita")
async def get_map():
    return FileResponse(os.path.join(FRONTEND_DIR, "map.html"))

@app.get("/about")
async def get_about():
    return FileResponse(os.path.join(FRONTEND_DIR, "about.html"))

# Mount static files without shadowing root routes.
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
