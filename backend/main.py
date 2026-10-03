import sys
from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import hashlib
import hmac
import json
import os
import requests
import secrets
import time
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from backend.listing_service import ListingServiceError, create_offer_listing, decode_photo_data as service_decode_photo_data
from backend.db import get_db

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "klapa_net_bot").lstrip("@")
SITE_URL = os.getenv("SITE_URL", "https://klapa.net").rstrip("/")
YANDEX_MAPS_JS_KEY = (
    os.getenv("YANDEX_MAPS_JS_KEY")
    or os.getenv("YANDEX_JAVA")
    or os.getenv("Yandex_java")
)
YANDEX_GEOCODER_KEY = (
    os.getenv("YANDEX_GEOCODER_KEY")
    or os.getenv("YANDEX_GEOCODER")
    or os.getenv("Yandex_geocoder")
)

from backend.migrations import init_db as initialize_database
from backend.notifications import start_worker, enqueue_admin
from backend.storage import UPLOAD_DIR as SHARED_UPLOAD_DIR, photo_url, validate_storage
from backend.security import now_iso as shared_now_iso, make_session_cookie as issue_session, read_session_cookie as lookup_session, revoke_session, upsert_user as store_user, create_challenge, digest, SESSION_SECONDS
from backend.lifecycle import manage_listing, effective_status
from backend.search import search_clause, save_preferences as store_preferences
from backend.catalogs import DISTRICTS, UNIVERSITIES, HOUSING_TYPES, AMENITIES, STATUS_LABELS

@asynccontextmanager
async def lifespan(app):
    validate_storage()
    initialize_database()
    stop, thread = (None, None) if os.getenv('DISABLE_BACKGROUND_WORKER') == 'true' else start_worker()
    try:
        yield
    finally:
        if stop:
            stop.set()
            thread.join(timeout=10)

app = FastAPI(lifespan=lifespan)
from backend.request_limits import BodyLimit
app.add_middleware(BodyLimit)

@app.middleware('http')
async def refresh_assets(request, call_next):
    response = await call_next(request)
    if request.url.path in ('/','/xarita','/publish','/favorites','/about') or request.url.path.endswith(('.js','.css')):
        response.headers['Cache-Control'] = 'no-cache'
    return response


# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = SHARED_UPLOAD_DIR
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# Initialization, expiry and delivery are owned by lifespan and shared services.

def now_iso():
    return shared_now_iso()


def make_session_cookie(user_id):
    return issue_session(user_id)

def read_session_cookie(cookie_value):
    return lookup_session(cookie_value)

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
    return store_user(cursor, telegram_user_id, username, first_name, last_name, photo_url, bot_started)

def listing_to_dict(row, photos_by_listing=None, favorite_ids=None, viewed_map=None):
    favorite_ids = favorite_ids or set()
    viewed_map = viewed_map or {}
    row_keys = set(row.keys())
    return {
        "id": row["id"],
        "listing_type": row["listing_type"],
        "telegram_username": row["telegram_username"],
        "author_photo_url": row["author_photo_url"] if "author_photo_url" in row_keys else None,
        "author_first_name": row["author_first_name"] if "author_first_name" in row_keys else None,
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
        "status": effective_status(row),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
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

def get_photo_insert_column(cursor):
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(listing_photos)").fetchall()}
    if "photo_path" in columns:
        return "photo_path"
    return "file_path"

def normalize_photo_path(path):
    return photo_url(path)

def get_listing_photos(cursor, listing_ids):
    if not listing_ids:
        return {}
    photo_column = get_photo_path_column(cursor)
    if not photo_column:
        return {listing_id: [] for listing_id in listing_ids}

    placeholders = ",".join("?" for _ in listing_ids)
    rows = cursor.execute(
        f"SELECT listing_id, {photo_column} AS path FROM listing_photos WHERE listing_id IN ({placeholders}) ORDER BY sort_order, id",
        listing_ids,
    ).fetchall()

    photos_by_listing = {listing_id: [] for listing_id in listing_ids}
    for row in rows:
        photo = normalize_photo_path(row["path"])
        if photo:
            photos_by_listing.setdefault(row["listing_id"], []).append(photo)
    return photos_by_listing


@app.get('/api/listings')
def get_listings(request: Request):
    try:
        clause, params = search_clause(dict(request.query_params))
    except ListingServiceError as exc:
        raise HTTPException(exc.status_code, exc.message)
    conn = get_db()
    try:
        cursor = conn.cursor()
        rows = cursor.execute('SELECT listings.*, users.photo_url AS author_photo_url, users.first_name AS author_first_name FROM listings LEFT JOIN users ON users.telegram_user_id=listings.telegram_user_id WHERE ' + clause + ' ORDER BY listings.created_at DESC, listings.id DESC', params).fetchall()
        ids = [r['id'] for r in rows]
        favorites, viewed = get_user_listing_state(cursor,current_user_id(request),ids)
        return [listing_to_dict(row,get_listing_photos(cursor,ids),favorites,viewed) for row in rows]
    finally:
        conn.close()

@app.get("/api/listings/{listing_id}")
def get_listing_detail(listing_id: int, request: Request):
    conn = get_db()
    try:
        cursor = conn.cursor()
        listing = cursor.execute(
            """
            SELECT listings.*, users.photo_url AS author_photo_url, users.first_name AS author_first_name
            FROM listings
            LEFT JOIN users ON users.telegram_user_id = listings.telegram_user_id
            WHERE listings.id = ?
            """,
            (listing_id,),
        ).fetchone()
        if not listing:
            conn.close()
            raise HTTPException(status_code=404, detail="Listing not found")
        user_id = current_user_id(request)
        is_public = cursor.execute("SELECT 1 FROM listings WHERE id=? AND status='active' AND datetime(expires_at)>datetime('now')",(listing_id,)).fetchone()
        if not is_public and listing["telegram_user_id"] != user_id:
            conn.close()
            raise HTTPException(status_code=404, detail="Listing not found")

        photos = get_listing_photos(cursor, [listing_id]).get(listing_id, [])
        favorite_ids, viewed_map = get_user_listing_state(cursor, user_id, [listing_id])
        data = listing_to_dict(listing, {listing_id: photos}, favorite_ids, viewed_map)
        conn.close()
        return data
    finally:
        conn.close()

def validate_telegram_login(payload):
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Telegram auth is not configured")

    auth_hash = payload.get("hash")
    if not auth_hash:
        raise HTTPException(status_code=400, detail="Telegram hash is required")
    try:
        auth_date = int(payload.get("auth_date", 0) or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Telegram auth_date is invalid")
    if not auth_date:
        raise HTTPException(status_code=400, detail="Telegram auth_date is required")
    if not -60 <= time.time() - auth_date <= 86400:
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
def auth_telegram(payload: dict, response: Response):
    data = validate_telegram_login(payload)
    telegram_user_id = int(data["id"])
    conn = get_db()
    try:
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
            max_age=SESSION_SECONDS,
            secure=SITE_URL.startswith('https://'),
        )
        return {"user": dict(user)}
    finally:
        conn.close()

@app.post("/api/auth/telegram/start")
def start_telegram_bot_login(response: Response):
    if not BOT_USERNAME:
        raise HTTPException(status_code=503, detail="BOT_USERNAME is not configured")
    binding = secrets.token_urlsafe(32)
    conn = get_db()
    try:
        token, code = create_challenge(conn.cursor(), binding)
        conn.commit()
        conn.close()
        response.set_cookie('sigamiz_login_binding', binding, httponly=True, samesite='strict', secure=SITE_URL.startswith('https://'), max_age=600)
        return {
            "token": token,
            "code": code,
            "bot_url": f"https://t.me/{BOT_USERNAME}?start=web_{token}",
        }
    finally:
        conn.close()

@app.post("/api/auth/telegram/complete")
def complete_telegram_bot_login(payload: dict, response: Response, request: Request):
    token = payload.get("token")
    binding = request.cookies.get('sigamiz_login_binding')
    if not isinstance(token, str) or not binding:
        raise HTTPException(status_code=400, detail="token is required")

    conn = get_db()
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            """
            SELECT * FROM web_login_tokens
            WHERE token = ? AND browser_hash = ? AND datetime(expires_at) > datetime('now') AND used_at IS NULL
            """,
            (token, digest(binding)),
        ).fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Login token expired")
        if not row["telegram_user_id"] or not row['approved_at']:
            conn.close()
            return {"ok": False, "pending": True}

        user = cursor.execute("SELECT * FROM users WHERE telegram_user_id = ?", (row["telegram_user_id"],)).fetchone()
        if not user:
            conn.close()
            raise HTTPException(status_code=404, detail="Telegram user not found")
        cursor.execute("UPDATE web_login_tokens SET used_at = datetime('now') WHERE token = ? AND used_at IS NULL AND datetime(expires_at) > datetime('now')", (token,))
        if cursor.rowcount != 1:
            conn.rollback()
            conn.close()
            raise HTTPException(409, 'Login already completed')
        conn.commit()
        conn.close()
        response.set_cookie(
            "sigamiz_session",
            make_session_cookie(row["telegram_user_id"]),
            httponly=True,
            samesite="lax",
            max_age=SESSION_SECONDS,
            secure=SITE_URL.startswith('https://'),
        )
        return {"ok": True, "user": dict(user)}
    finally:
        conn.close()

@app.post("/api/logout")
def logout(response: Response, request: Request):
    revoke_session(request.cookies.get('sigamiz_session'))
    response.delete_cookie("sigamiz_session")
    return {"ok": True}

@app.get("/api/me")
def get_me(request: Request):
    user_id = current_user_id(request)
    if not user_id:
        return {"user": None}
    conn = get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE telegram_user_id = ?", (user_id,)).fetchone()
        conn.close()
        return {"user": dict(user) if user else None}
    finally:
        conn.close()

@app.get("/api/config")
def get_config():
    telegram_client_id = None
    if BOT_TOKEN and ":" in BOT_TOKEN:
        token_prefix = BOT_TOKEN.split(":", 1)[0]
        if token_prefix.isdigit():
            telegram_client_id = token_prefix
    return {
        "bot_username": BOT_USERNAME,
        "telegram_client_id": telegram_client_id,
        "yandex_maps_js_key": YANDEX_MAPS_JS_KEY,
        "catalogs": {"districts": DISTRICTS, "universities": UNIVERSITIES, "housing_types": HOUSING_TYPES, "amenities": AMENITIES, "statuses":STATUS_LABELS},
    }

@app.get("/api/geocode")
def geocode_address(address: str):
    query = (address or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="address is required")
    if not YANDEX_GEOCODER_KEY:
        raise HTTPException(status_code=503, detail="Yandex geocoder is not configured")

    try:
        response = requests.get(
            "https://geocode-maps.yandex.ru/1.x/",
            params={
                "apikey": YANDEX_GEOCODER_KEY,
                "format": "json",
                "geocode": f"{query}, Tashkent, Uzbekistan",
                "results": 1,
                "lang": "uz_UZ",
            },
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        members = data["response"]["GeoObjectCollection"]["featureMember"]
    except Exception:
        raise HTTPException(status_code=502, detail="Yandex geocoder request failed")

    if not members:
        raise HTTPException(status_code=404, detail="Address not found")

    geo_object = members[0]["GeoObject"]
    lon, lat = geo_object["Point"]["pos"].split()
    return {
        "lat": float(lat),
        "lng": float(lon),
        "label": geo_object.get("metaDataProperty", {}).get("GeocoderMetaData", {}).get("text") or query,
    }

@app.get("/api/favorites")
def get_favorites(request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    try:
        cursor = conn.cursor()
        rows = cursor.execute(
            """
            SELECT listings.*, users.photo_url AS author_photo_url, users.first_name AS author_first_name FROM favorites
            JOIN listings ON listings.id = favorites.listing_id
            LEFT JOIN users ON users.telegram_user_id = listings.telegram_user_id
            WHERE favorites.telegram_user_id = ? AND listings.status = 'active' AND datetime(listings.expires_at) > datetime('now')
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
    finally:
        conn.close()

@app.post("/api/favorites/{listing_id}")
def add_favorite(listing_id: int, request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    try:
        cursor = conn.cursor()
        listing = cursor.execute("SELECT id FROM listings WHERE id = ? AND status = 'active' AND datetime(expires_at) > datetime('now')", (listing_id,)).fetchone()
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
    finally:
        conn.close()

@app.delete("/api/favorites/{listing_id}")
def remove_favorite(listing_id: int, request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM favorites WHERE telegram_user_id = ? AND listing_id = ?",
            (user_id, listing_id),
        )
        conn.commit()
        conn.close()
        return {"ok": True, "is_favorite": False}
    finally:
        conn.close()

@app.post("/api/listings/{listing_id}/view")
def mark_listing_viewed(listing_id: int, request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    try:
        cursor = conn.cursor()
        listing = cursor.execute("SELECT id FROM listings WHERE id = ? AND status = 'active' AND datetime(expires_at) > datetime('now')", (listing_id,)).fetchone()
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
    finally:
        conn.close()

@app.get("/api/preferences")
def get_preferences(request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM search_preferences WHERE telegram_user_id = ?", (user_id,)).fetchone()
        conn.close()
        if not row:
            return {"telegram_user_id": user_id, "districts": []}
        data = dict(row)
        data["districts"] = json.loads(data["districts"] or "[]")
        return data
    finally:
        conn.close()

@app.put('/api/preferences')
def save_preferences(payload: dict, request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    try:
        store_preferences(conn.cursor(),user_id,payload)
        conn.commit()
        return {'ok':True}
    except ListingServiceError as exc:
        conn.rollback()
        raise HTTPException(exc.status_code,exc.message)
    finally:
        conn.close()

@app.get('/api/recommended')
def get_recommended(request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    try:
        cursor = conn.cursor()
        prefs = cursor.execute('SELECT * FROM search_preferences WHERE telegram_user_id=?',(user_id,)).fetchone()
        clause, params = search_clause(dict(prefs) if prefs else {})
        rows = cursor.execute('SELECT listings.*, users.photo_url AS author_photo_url, users.first_name AS author_first_name FROM listings LEFT JOIN users ON users.telegram_user_id=listings.telegram_user_id WHERE ' + clause + ' ORDER BY listings.created_at DESC, listings.id DESC LIMIT 30',params).fetchall()
        ids = [r['id'] for r in rows]
        favorites, viewed = get_user_listing_state(cursor,user_id,ids)
        photos = get_listing_photos(cursor,ids)
        return [listing_to_dict(row,photos,favorites,viewed) for row in rows]
    finally:
        conn.close()

@app.get("/api/my-listings")
def get_my_listings(request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    try:
        cursor = conn.cursor()
        rows = cursor.execute(
            """
            SELECT listings.*, users.photo_url AS author_photo_url, users.first_name AS author_first_name
            FROM listings
            LEFT JOIN users ON users.telegram_user_id = listings.telegram_user_id
            WHERE listings.telegram_user_id = ? AND listings.status != 'removed'
            ORDER BY listings.created_at DESC, listings.id DESC
            """,
            (user_id,),
        ).fetchall()
        listing_ids = [row["id"] for row in rows]
        photos_by_listing = get_listing_photos(cursor, listing_ids)
        favorite_ids, viewed_map = get_user_listing_state(cursor, user_id, listing_ids)
        results = [listing_to_dict(row, photos_by_listing, favorite_ids, viewed_map) for row in rows]
        conn.close()
        return results
    finally:
        conn.close()

@app.post('/api/listings')
def create_listing(payload: dict, request: Request):
    from backend.storage import delete_photo
    user_id = require_user_id(request)
    conn = get_db()
    created, committed = None, False
    try:
        cursor = conn.cursor()
        photos = payload.get('photos') or []
        if not isinstance(photos,list) or len(photos) > 5:
            raise ListingServiceError('Ko‘pi bilan 5 ta rasm yuklang')
        decoded = [service_decode_photo_data(p) for p in photos]
        user = cursor.execute('SELECT * FROM users WHERE telegram_user_id=?',(user_id,)).fetchone()
        created = create_offer_listing(cursor,user,payload,decoded,UPLOAD_DIR,get_photo_insert_column(cursor))
        conn.commit()
        committed = True
        return {'ok':True,'status':created['status'],'listing':listing_to_dict(created['listing'],get_listing_photos(cursor,[created['listing_id']]))}
    except ListingServiceError as exc:
        conn.rollback()
        raise HTTPException(exc.status_code,exc.message)
    except Exception as exc:
        conn.rollback()
        if getattr(exc,'pgcode',None) == '23505' or 'UNIQUE constraint' in str(exc):
            raise HTTPException(409,'Sizda faol e‘lon bor')
        raise
    finally:
        if created and not committed:
            for key in created['photo_keys']:
                delete_photo(key,UPLOAD_DIR)
        conn.close()

@app.post("/api/report")
def report_listing(listing_id: int, reason: str, request: Request):
    reporter_id = require_user_id(request)
    if not reason.strip() or len(reason) > 1000:
        raise HTTPException(400, 'Shikoyat sababini kiriting')
    normalized_reporter_key = f"telegram:{reporter_id}"

    conn = get_db()
    try:
        cursor = conn.cursor()
        owner_row = cursor.execute(
            "SELECT telegram_user_id, report_count, status, expires_at FROM listings WHERE id = ?",
            (listing_id,),
        ).fetchone()
        if not owner_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Listing not found")
        if effective_status(owner_row) != 'active':
            conn.close()
            raise HTTPException(status_code=404, detail="Listing not found")
        if owner_row["telegram_user_id"] == reporter_id:
            conn.close()
            raise HTTPException(status_code=400, detail="You cannot report your own listing")

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
            cursor.execute("UPDATE listings SET status = 'hidden_pending_review' WHERE id = ? AND status='active'", (listing_id,))
        if count >= 3 and cursor.rowcount == 1:
            last_report = cursor.execute('SELECT MAX(id) FROM reports WHERE listing_id=?',(listing_id,)).fetchone()[0]
            print(f"Listing {listing_id} hidden for admin review after {count} reports.")
            enqueue_admin(cursor, f'reports:{listing_id}:{last_report}',
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
    finally:
        conn.close()

# Static pages
@app.post('/api/my-listings/{listing_id}/{action}')
def manage_my_listing(listing_id: int, action: str, request: Request):
    user_id = require_user_id(request)
    conn = get_db()
    try:
        status = manage_listing(conn.cursor(), listing_id, user_id, action)
        conn.commit()
        return {'ok': True, 'status': status}
    except ListingServiceError as exc:
        conn.rollback()
        raise HTTPException(exc.status_code, exc.message)
    except Exception as exc:
        conn.rollback()
        if getattr(exc,'pgcode',None) == '23505' or 'UNIQUE constraint' in str(exc):
            raise HTTPException(409, 'Avval boshqa faol e‘lonni o‘chiring')
        raise
    finally:
        conn.close()

@app.get('/api/stats')
def public_stats():
    conn = get_db()
    try:
        return {'active_listings': conn.execute("SELECT COUNT(*) FROM listings WHERE status='active' AND listing_type='offer' AND datetime(expires_at) > datetime('now')").fetchone()[0]}
    finally:
        conn.close()

@app.get("/")
async def get_home():
    return FileResponse(os.path.join(FRONTEND_DIR, "landing.html"))

@app.get("/xarita")
async def get_map():
    return FileResponse(os.path.join(FRONTEND_DIR, "map.html"))

@app.get("/favorites")
async def get_favorites_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "favorites.html"))

@app.get("/publish")
async def get_publish_page():
    return FileResponse(os.path.join(FRONTEND_DIR, "publish.html"))

@app.get("/about")
async def get_about():
    return FileResponse(os.path.join(FRONTEND_DIR, "about.html"))

# Mount static files without shadowing root routes.
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
