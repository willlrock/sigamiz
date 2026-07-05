import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")

from datetime import datetime, timedelta

def seed():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    expires_at = datetime.now() + timedelta(days=7)
    
    cursor.execute("""
        INSERT INTO listings (telegram_user_id, telegram_username, lat, lng, price_per_person, people_needed, has_wifi, has_ac, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (371445197, "Tameweezer", 41.2995, 69.2401, 1500000, 1, 1, 1, expires_at))
    
    conn.commit()
    conn.close()
    print("Database seeded!")

if __name__ == "__main__":
    seed()
