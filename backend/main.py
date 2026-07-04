from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import sqlite3
import os

app = FastAPI()

# Используем относительные пути для контейнера
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# Монтирование
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

DB_PATH = os.path.join(BASE_DIR, "backend", "database.db")

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
