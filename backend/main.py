from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import base64
import hashlib
import hmac
import json
import sqlite3
import os
import requests
import secrets
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
SESSION_SECRET = os.getenv("SESSION_SECRET") or BOT_TOKEN or secrets.token_hex(32)

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
        "author_gender": "TEXT",
        "preferred_gender": "TEXT",
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
        "reporter_key": "TEXT",
        "reason": "TEXT",
        "created_at": "DATETIME",
    })
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_listing_reporter_key "
        "ON reports (listing_id, reporter_key)"
    )
    ensure_columns(cursor, "banned_users", {
        "reason": "TEXT",
        "banned_at": "DATETIME",
    })
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_user_id INTEGER PRIMARY KEY,
            telegram_username TEXT,
            first_name TEXT,
            last_name TEXT,
            photo_url TEXT,
            bot_started_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen_at DATETIME
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            telegram_user_id INTEGER NOT NULL,
            listing_id INTEGER NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (telegram_user_id, listing_id),
            FOREIGN KEY (listing_id) REFERENCES listings (id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS listing_views (
            telegram_user_id INTEGER NOT NULL,
            listing_id INTEGER NOT NULL,
            viewed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (telegram_user_id, listing_id),
            FOREIGN KEY (listing_id) REFERENCES listings (id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS search_preferences (
            telegram_user_id INTEGER PRIMARY KEY,
            price_min INTEGER,
            price_max INTEGER,
            districts TEXT,
            housing_type TEXT,
            room_count INTEGER,
            university TEXT,
            has_wifi BOOLEAN DEFAULT 0,
            has_ac BOOLEAN DEFAULT 0,
            has_washing_machine BOOLEAN DEFAULT 0,
            no_landlord_in_yard BOOLEAN DEFAULT 0,
            near_metro BOOLEAN DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

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
                    author_gender, preferred_gender,
                    lat, lng, price_per_person, people_needed, has_wifi, has_ac, has_washing_machine,
                    no_landlord_in_yard, near_metro, status, expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                0, "demo_user", "offer", "TATU", "Yunusobod", "Kvartira",
                "Demo e'lon: 2 ta talaba uchun joy bor.", "male", "any", 41.2995, 69.2401,
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

def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")

def sign_value(value):
    return hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()

def make_session_cookie(user_id):
    payload = base64.urlsafe_b64encode(str(user_id).encode()).decode()
    return f"{payload}.{sign_value(payload)}"

def read_session_cookie(cookie_value):
    if not cookie_value or "." not in cookie_value:
        return None
    payload, signature = cookie_value.rsplit(".", 1)
    if not hmac.compare_digest(sign_value(payload), signature):
        return None
    try:
        return int(base64.urlsafe_b64decode(payload.encode()).decode())
    except Exception:
        return None

def current_user_id(request: Request | None = None, sigamiz_session: str | None = None):
    cookie_value = sigamiz_session
    if request is not None:
        cookie_value = cookie_value or request.cookies.get("sigamiz_session")
    return read_session_cookie(cookie_value)

def require_user_id(request: Request | None = None, sigamiz_session: str | None = None):
    user_id = current_user_id(request, sigamiz_session)
    if not user_id:
        raise HTTPException(status_code=401, detail="Telegram login required")
    return user_id

def upsert_user(cursor, telegram_user_id, username=None, first_name=None, last_name=None, photo_url=None, bot_started=False):
    existing = cursor.execute(
        "SELECT telegram_user_id, bot_started_at FROM users WHERE telegram_user_id = ?",
        (telegram_user_id,),
    ).fetchone()
    bot_started_at = now_iso() if bot_started and (not existing or not existing["bot_started_at"]) else (existing["bot_started_at"] if existing else None)
    cursor.execute(
        """
        INSERT INTO users (
            telegram_user_id, telegram_username, first_name, last_name, photo_url,
            bot_started_at, created_at, last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            telegram_username = COALESCE(excluded.telegram_username, users.telegram_username),
            first_name = COALESCE(excluded.first_name, users.first_name),
            last_name = COALESCE(excluded.last_name, users.last_name),
            photo_url = COALESCE(excluded.photo_url, users.photo_url),
            bot_started_at = COALESCE(users.bot_started_at, excluded.bot_started_at),
            last_seen_at = excluded.last_seen_at
        """,
        (telegram_user_id, username, first_name, last_name, photo_url, bot_started_at, now_iso(), now_iso()),
    )

def listing_to_dict(row, photos_by_listing=None, favorite_ids=None, viewed_map=None):
    favorite_ids = favorite_ids or set()
    viewed_map = viewed_map or {}
    return {
        "id": row["id"],
        "listing_type": row["listing_type"],
        "telegram_username": row["telegram_username"],
        "university": row["university"],
        "district": row["district"],
        "housing_type": row["housing_type"],
        "room_count": row["room_count"],
        "description": row["description"],
        "phone_number": row["phone_number"],
        "author_gender": row["author_gender"],
        "preferred_gender": row["preferred_gender"],
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
        "photos": (photos_by_listing or {}).get(row["id"], []),
        "is_favorite": row["id"] in favorite_ids,
        "viewed_at": viewed_map.get(row["id"]),
    }

def get_user_listing_state(cursor, user_id, listing_ids):
    if not user_id or not listing_ids:
        return set(), {}
    placeholders = ",".join("?" for _ in listing_ids)
    favorite_rows = cursor.execute(
        f"SELECT listing_id FROM favorites WHERE telegram_user_id = ? AND listing_id IN ({placeholders})",
        [user_id, *listing_ids],
    ).fetchall()
    view_rows = cursor.execute(
        f"SELECT listing_id, viewed_at FROM listing_views WHERE telegram_user_id = ? AND listing_id IN ({placeholders})",
        [user_id, *listing_ids],
    ).fetchall()
    return {row["listing_id"] for row in favorite_rows}, {row["listing_id"]: row["viewed_at"] for row in view_rows}

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
def get_listings(
    request: Request,
    listing_type: str | None = None,
    district: str | None = None,
    university: str | None = None,
    preferred_gender: str | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    has_wifi: bool | None = None,
    has_ac: bool | None = None,
    has_washing_machine: bool | None = None,
    no_landlord_in_yard: bool | None = None,
    near_metro: bool | None = None,
):
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
    if preferred_gender and preferred_gender != "any":
        query += " AND (author_gender = ? OR preferred_gender = ? OR preferred_gender = 'any')"
        params.extend([preferred_gender, preferred_gender])
    if price_min is not None:
        query += " AND price_per_person >= ?"
        params.append(price_min)
    if price_max is not None:
        query += " AND price_per_person <= ?"
        params.append(price_max)
    amenity_filters = {
        "has_wifi": has_wifi,
        "has_ac": has_ac,
        "has_washing_machine": has_washing_machine,
        "no_landlord_in_yard": no_landlord_in_yard,
        "near_metro": near_metro,
    }
    for column, value in amenity_filters.items():
        if value:
            query += f" AND {column} = 1"
        
    listings = cursor.execute(query, params).fetchall()
    listing_ids = [row["id"] for row in listings]
    photos_by_listing = get_listing_photos(cursor, listing_ids)
    favorite_ids, viewed_map = get_user_listing_state(cursor, current_user_id(request), listing_ids)
    results = [listing_to_dict(row, photos_by_listing, favorite_ids, viewed_map) for row in listings]
    conn.close()
    return results

@app.get("/api/listings/{listing_id}")
def get_listing_detail(listing_id: int, request: Request):
    conn = get_db()
    cursor = conn.cursor()
    listing = cursor.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not listing:
        conn.close()
        return {"error": "Not found"}
    
    photos = get_listing_photos(cursor, [listing_id]).get(listing_id, [])
    favorite_ids, viewed_map = get_user_listing_state(cursor, current_user_id(request), [listing_id])
    data = listing_to_dict(listing, {listing_id: photos}, favorite_ids, viewed_map)
    conn.close()
    return data

def validate_telegram_login(payload):
    if not BOT_TOKEN or "fake_token_for_testing" in BOT_TOKEN:
        dev_user_id = payload.get("id")
        if not dev_user_id:
            raise HTTPException(status_code=400, detail="Telegram id is required")
        return payload

    auth_hash = payload.get("hash")
    if not auth_hash:
        raise HTTPException(status_code=400, detail="Telegram hash is required")
    auth_date = int(payload.get("auth_date", 0) or 0)
    if auth_date and time.time() - auth_date > 86400:
        raise HTTPException(status_code=401, detail="Telegram auth expired")
    check_parts = []
    for key in sorted(payload):
        if key != "hash" and payload.get(key) is not None:
            check_parts.append(f"{key}={payload[key]}")
    data_check_string = "\n".join(check_parts)
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, auth_hash):
        raise HTTPException(status_code=401, detail="Invalid Telegram auth")
    return payload

@app.post("/api/auth/telegram")
async def auth_telegram(payload: dict, response: Response):
    data = validate_telegram_login(payload)
    telegram_user_id = int(data["id"])
    conn = get_db()
    cursor = conn.cursor()
    upsert_user(
        cursor,
        telegram_user_id,
        username=data.get("username"),
        first_name=data.get("first_name"),
        last_name=data.get("last_name"),
        photo_url=data.get("photo_url"),
    )
    conn.commit()
    user = cursor.execute("SELECT * FROM users WHERE telegram_user_id = ?", (telegram_user_id,)).fetchone()
    conn.close()
    response.set_cookie(
        "sigamiz_session",
        make_session_cookie(telegram_user_id),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 90,
    )
    return {"user": dict(user)}

@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie("sigamiz_session")
    return {"ok": True}

@app.get("/api/me")
def get_me(request: Request):
    user_id = current_user_id(request)
    if not user_id:
        return {"user": None}
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE telegram_user_id = ?", (user_id,)).fetchone()
    conn.close()
    return {"user": dict(user) if user else None}

@app.get("/api/config")
def get_config():
    return {"bot_username": BOT_USERNAME}

@app.get("/api/favorites")
def get_favorites(request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT listings.* FROM favorites
        JOIN listings ON listings.id = favorites.listing_id
        WHERE favorites.telegram_user_id = ? AND listings.status = 'active'
        ORDER BY favorites.created_at DESC
        """,
        (user_id,),
    ).fetchall()
    listing_ids = [row["id"] for row in rows]
    photos_by_listing = get_listing_photos(cursor, listing_ids)
    favorite_ids, viewed_map = get_user_listing_state(cursor, user_id, listing_ids)
    results = [listing_to_dict(row, photos_by_listing, favorite_ids, viewed_map) for row in rows]
    conn.close()
    return results

@app.post("/api/favorites/{listing_id}")
def add_favorite(listing_id: int, request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    cursor = conn.cursor()
    listing = cursor.execute("SELECT id FROM listings WHERE id = ? AND status = 'active'", (listing_id,)).fetchone()
    if not listing:
        conn.close()
        raise HTTPException(status_code=404, detail="Listing not found")
    cursor.execute(
        "INSERT OR IGNORE INTO favorites (telegram_user_id, listing_id) VALUES (?, ?)",
        (user_id, listing_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "is_favorite": True}

@app.delete("/api/favorites/{listing_id}")
def remove_favorite(listing_id: int, request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    conn.execute(
        "DELETE FROM favorites WHERE telegram_user_id = ? AND listing_id = ?",
        (user_id, listing_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "is_favorite": False}

@app.post("/api/listings/{listing_id}/view")
def mark_listing_viewed(listing_id: int, request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    cursor = conn.cursor()
    listing = cursor.execute("SELECT id FROM listings WHERE id = ? AND status = 'active'", (listing_id,)).fetchone()
    if not listing:
        conn.close()
        raise HTTPException(status_code=404, detail="Listing not found")
    cursor.execute(
        """
        INSERT INTO listing_views (telegram_user_id, listing_id, viewed_at)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_user_id, listing_id) DO UPDATE SET viewed_at = excluded.viewed_at
        """,
        (user_id, listing_id, now_iso()),
    )
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/preferences")
def get_preferences(request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    row = conn.execute("SELECT * FROM search_preferences WHERE telegram_user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return {"telegram_user_id": user_id, "districts": []}
    data = dict(row)
    data["districts"] = json.loads(data["districts"] or "[]")
    return data

@app.put("/api/preferences")
async def save_preferences(payload: dict, request: Request):
    user_id = require_user_id(request)
    districts = payload.get("districts") or []
    if isinstance(districts, str):
        districts = [districts]
    values = {
        "price_min": payload.get("price_min"),
        "price_max": payload.get("price_max"),
        "districts": json.dumps(districts, ensure_ascii=False),
        "housing_type": payload.get("housing_type"),
        "room_count": payload.get("room_count"),
        "university": payload.get("university"),
        "has_wifi": 1 if payload.get("has_wifi") else 0,
        "has_ac": 1 if payload.get("has_ac") else 0,
        "has_washing_machine": 1 if payload.get("has_washing_machine") else 0,
        "no_landlord_in_yard": 1 if payload.get("no_landlord_in_yard") else 0,
        "near_metro": 1 if payload.get("near_metro") else 0,
    }
    conn = get_db()
    conn.execute(
        """
        INSERT INTO search_preferences (
            telegram_user_id, price_min, price_max, districts, housing_type, room_count,
            university, has_wifi, has_ac, has_washing_machine, no_landlord_in_yard,
            near_metro, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            price_min = excluded.price_min,
            price_max = excluded.price_max,
            districts = excluded.districts,
            housing_type = excluded.housing_type,
            room_count = excluded.room_count,
            university = excluded.university,
            has_wifi = excluded.has_wifi,
            has_ac = excluded.has_ac,
            has_washing_machine = excluded.has_washing_machine,
            no_landlord_in_yard = excluded.no_landlord_in_yard,
            near_metro = excluded.near_metro,
            updated_at = excluded.updated_at
        """,
        (
            user_id,
            values["price_min"],
            values["price_max"],
            values["districts"],
            values["housing_type"],
            values["room_count"],
            values["university"],
            values["has_wifi"],
            values["has_ac"],
            values["has_washing_machine"],
            values["no_landlord_in_yard"],
            values["near_metro"],
            now_iso(),
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/recommended")
def get_recommended(request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    cursor = conn.cursor()
    prefs = cursor.execute("SELECT * FROM search_preferences WHERE telegram_user_id = ?", (user_id,)).fetchone()

    query = "SELECT * FROM listings WHERE status = 'active' AND listing_type = 'offer'"
    params = []
    if prefs:
        districts = json.loads(prefs["districts"] or "[]")
        if prefs["price_min"] is not None:
            query += " AND price_per_person >= ?"
            params.append(prefs["price_min"])
        if prefs["price_max"] is not None:
            query += " AND price_per_person <= ?"
            params.append(prefs["price_max"])
        if districts:
            placeholders = ",".join("?" for _ in districts)
            query += f" AND district IN ({placeholders})"
            params.extend(districts)
        if prefs["housing_type"]:
            query += " AND housing_type = ?"
            params.append(prefs["housing_type"])
        if prefs["room_count"] is not None:
            query += " AND room_count = ?"
            params.append(prefs["room_count"])
        if prefs["university"]:
            query += " AND university = ?"
            params.append(prefs["university"])
        for column in (
            "has_wifi",
            "has_ac",
            "has_washing_machine",
            "no_landlord_in_yard",
            "near_metro",
        ):
            if prefs[column]:
                query += f" AND {column} = 1"

    rows = cursor.execute(query + " ORDER BY created_at DESC, id DESC LIMIT 30", params).fetchall()
    listing_ids = [row["id"] for row in rows]
    photos_by_listing = get_listing_photos(cursor, listing_ids)
    favorite_ids, viewed_map = get_user_listing_state(cursor, user_id, listing_ids)
    results = [listing_to_dict(row, photos_by_listing, favorite_ids, viewed_map) for row in rows]
    conn.close()
    return results

@app.post("/api/report")
async def report_listing(listing_id: int, reason: str, reporter_id: int = 0, reporter_key: str | None = None):
    normalized_reporter_key = (reporter_key or "").strip()[:128]
    if not normalized_reporter_key and reporter_id:
        normalized_reporter_key = f"telegram:{reporter_id}"
    if not normalized_reporter_key:
        raise HTTPException(status_code=400, detail="Reporter identity is required")

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

    duplicate = cursor.execute(
        "SELECT 1 FROM reports WHERE listing_id = ? AND reporter_key = ?",
        (listing_id, normalized_reporter_key),
    ).fetchone()
    if duplicate:
        conn.close()
        return {"message": "Shikoyat allaqachon qabul qilingan"}

    if reporter_column:
        cursor.execute(
            f"INSERT OR IGNORE INTO reports (listing_id, reason, reporter_key, {reporter_column}) VALUES (?, ?, ?, ?)",
            (listing_id, reason, normalized_reporter_key, reporter_id if reporter_id != 0 else 0),
        )
    else:
        cursor.execute(
            "INSERT OR IGNORE INTO reports (listing_id, reason, reporter_key) VALUES (?, ?, ?)",
            (listing_id, reason, normalized_reporter_key),
        )
    if cursor.rowcount == 0:
        conn.close()
        return {"message": "Shikoyat allaqachon qabul qilingan"}

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
            f"Oxirgi sabab: {reason}\n\n"
            f"Tasdiqlash: /review {listing_id} approve\n"
            f"Ban qilish: /review {listing_id} ban"
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

@app.get("/favorites")
async def get_favorites_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "favorites.html"))

@app.get("/about")
async def get_about():
    return FileResponse(os.path.join(FRONTEND_DIR, "about.html"))

# Mount static files without shadowing root routes.
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
