from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import sqlite3
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

app = FastAPI()

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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER,
            telegram_username TEXT,
            lat REAL,
            lng REAL,
            price_per_person INTEGER,
            people_needed INTEGER,
            has_wifi BOOLEAN,
            has_ac BOOLEAN,
            status TEXT DEFAULT 'active',
            expires_at DATETIME
        )
    """)
    # Проверка на наличие столбца status
    cursor.execute("PRAGMA table_info(listings)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'status' not in columns:
        cursor.execute("ALTER TABLE listings ADD COLUMN status TEXT DEFAULT 'active'")
        
    # Засеиваем, если пусто
    if cursor.execute("SELECT count(*) FROM listings").fetchone()[0] == 0:
        expires_at = datetime.now() + timedelta(days=7)
        cursor.execute("""
            INSERT INTO listings (telegram_user_id, telegram_username, lat, lng, price_per_person, people_needed, has_wifi, has_ac, status, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (371445197, "Tameweezer", 41.2995, 69.2401, 1500000, 1, 1, 1, 'active', expires_at))
    conn.commit()
    conn.close()

init_db()

# Функция очистки устаревших объявлений
def delete_expired_listings():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now()
    cursor.execute("DELETE FROM listings WHERE expires_at < ?", (now,))
    conn.commit()
    conn.close()
    print(f"[{now}] Очистка старых объявлений выполнена.")

# Запуск планировщика
scheduler = BackgroundScheduler()
scheduler.add_job(delete_expired_listings, 'interval', days=1)
scheduler.start()

# API
@app.get("/api/listings")
async def get_listings():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, lat, lng, price_per_person, people_needed FROM listings WHERE status = 'active'")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "lat": r[1], "lng": r[2], "price": r[3], "people_needed": r[4]} for r in rows]

@app.get("/api/listings/{id}")
async def get_listing(id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM listings WHERE id = ?", (id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "telegram_username": row[2], "price": row[5], "photos": []}
    return {"error": "Not found"}

# Статика и корень
@app.get("/")
async def read_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/listings")
def get_listings():
    conn = get_db()
    cursor = conn.cursor()
    listings = cursor.execute("SELECT * FROM listings WHERE status = 'active'").fetchall()
    
    results = []
    for row in listings:
        results.append({
            "id": row["id"],
            "lat": row["lat"],
            "lng": row["lng"],
            "price": row["price_per_person"],
            "people_needed": row["people_needed"]
        })
    conn.close()
    return results

@app.get("/api/listings/{listing_id}")
def get_listing_detail(listing_id: int):
    conn = get_db()
    cursor = conn.cursor()
    listing = cursor.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not listing:
        return {"error": "Not found"}
    
    photos = cursor.execute("SELECT file_path FROM listing_photos WHERE listing_id = ?", (listing_id,)).fetchall()
    conn.close()
    
    return {
        "id": listing["id"],
        "price": listing["price_per_person"],
        "photos": [p["file_path"].replace(BASE_DIR, "").replace("\\", "/") for p in photos],
        "telegram_username": listing["telegram_username"]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
