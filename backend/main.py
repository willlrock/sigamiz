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
    
    # Читаем схему из файла и выполняем
    with open(os.path.join(BASE_DIR, "backend", "schema.sql"), "r", encoding="utf-8") as f:
        schema = f.read()
    cursor.executescript(schema)
        
    # Засеиваем тестовыми данными, если пусто
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

@app.get("/api/listings")
def get_listings():
    conn = get_db()
    cursor = conn.cursor()
    # Добавляем необходимые поля: university, has_wifi, has_ac, has_washing_machine, no_landlord_in_yard, near_metro
    listings = cursor.execute("SELECT * FROM listings WHERE status = 'active'").fetchall()
    
    results = []
    for row in listings:
        results.append({
            "id": row["id"],
            "lat": row["lat"],
            "lng": row["lng"],
            "price": row["price_per_person"],
            "people_needed": row["people_needed"],
            "has_wifi": row["has_wifi"],
            "has_ac": row["has_ac"],
            "has_washing_machine": row["has_washing_machine"],
            "no_landlord_in_yard": row["no_landlord_in_yard"],
            "near_metro": row["near_metro"],
            "status": row["status"]
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
    
    # Предполагаем, что таблица listing_photos существует
    photos = []
    try:
        photos = cursor.execute("SELECT file_path FROM listing_photos WHERE listing_id = ?", (listing_id,)).fetchall()
    except sqlite3.OperationalError:
        pass # Таблица может отсутствовать
    conn.close()
    
    return {
        "id": listing["id"],
        "price": listing["price_per_person"],
        "photos": [p["file_path"].replace(BASE_DIR, "").replace("\\", "/") for p in photos],
        "telegram_username": listing["telegram_username"]
    }

@app.post("/api/report")
async def report_listing(listing_id: int, reason: str):
    conn = get_db()
    cursor = conn.cursor()
    # 1. Вставляем жалобу
    cursor.execute("INSERT INTO reports (listing_id, reason) VALUES (?, ?)", (listing_id, reason))
    # 2. Увеличиваем счетчик
    cursor.execute("UPDATE listings SET report_count = report_count + 1 WHERE id = ?", (listing_id,))
    # 3. Проверяем лимит
    cursor.execute("SELECT report_count FROM listings WHERE id = ?", (listing_id,))
    count = cursor.fetchone()[0]
    if count >= 3:
        cursor.execute("UPDATE listings SET status = 'hidden_pending_review' WHERE id = ?", (listing_id,))
        print(f"Listing {listing_id} hidden due to reports.")
    
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

# Монтируем статику с префиксом /static, чтобы не перекрывать корни
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
