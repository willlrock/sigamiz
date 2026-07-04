from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import sqlite3
import os

app = FastAPI()

# 1. Обслуживание статических фото (API)
UPLOAD_DIR = "D:/Projects/sigamiz/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# 2. Обслуживание фронтенда
FRONTEND_DIR = "D:/Projects/sigamiz/frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

DB_PATH = "D:/Projects/sigamiz/backend/database.db"

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
        "photos": [p["file_path"].replace("D:/Projects/sigamiz/uploads", "/uploads") for p in photos],
        "telegram_username": listing["telegram_username"]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
