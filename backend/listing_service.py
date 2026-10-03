import base64
import binascii
import io
import os
import math
import re
import hashlib

from PIL import Image, ImageOps, ImageStat
from backend.catalogs import DISTRICTS, UNIVERSITIES, HOUSING_TYPES
from backend.storage import store_photo, delete_photo


class ListingServiceError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def bool_from_payload(payload, key):
    raw = payload.get(key, False)
    if raw in (True, 1, "1", "true", "on", "yes"):
        return 1
    if raw in (False, 0, None, "", "0", "false", "off", "no"):
        return 0
    raise ListingServiceError(f"{key}: noto'g'ri qiymat")


def parse_int_field(payload, key, *, minimum=None, maximum=None, required=True):
    raw = payload.get(key)
    if raw in (None, ""):
        if required:
            raise ListingServiceError(f"{key} is required")
        return None
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise ListingServiceError(f"{key}: butun son kiriting")
    if isinstance(raw, str):
        raw = raw.replace(" ", "").replace("\u00a0", "")
        if not raw.isdigit():
            raise ListingServiceError(f"{key}: butun son kiriting")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ListingServiceError(f"{key} must be a number")
    if minimum is not None and value < minimum:
        raise ListingServiceError(f"{key} is too small")
    if maximum is not None and value > maximum:
        raise ListingServiceError(f"{key} is too large")
    return value


def parse_float_field(payload, key, *, minimum=None, maximum=None):
    raw = payload.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise ListingServiceError(f"{key}: noto'g'ri koordinata")
    if raw in (None, ""):
        raise ListingServiceError(f"{key} is required")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ListingServiceError(f"{key} must be a number")
    if not math.isfinite(value):
        raise ListingServiceError(f"{key}: noto'g'ri koordinata")
    if minimum is not None and value < minimum:
        raise ListingServiceError(f"{key} is too small")
    if maximum is not None and value > maximum:
        raise ListingServiceError(f"{key} is too large")
    return value


def decode_photo_data(photo_data):
    if not isinstance(photo_data, str) or not photo_data:
        raise ListingServiceError("photo is empty")
    if len(photo_data) > 5 * 1024 * 1024 * 4 // 3 + 256:
        raise ListingServiceError("Har bir rasm 5 MB dan kichik bo'lishi kerak", 413)
    encoded = str(photo_data)
    if "," in encoded:
        encoded = encoded.split(",", 1)[1]
    try:
        return base64.b64decode(encoded, validate=True)
    except binascii.Error:
        raise ListingServiceError("photo must be base64")


def average_image_hash(image):
    small = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    if ImageStat.Stat(small).stddev[0] < 12:
        return None
    values = list(small.getdata())
    avg = sum(values) / len(values)
    bits = "".join("1" if value >= avg else "0" for value in values)
    return f"{int(bits, 2):016x}"


def hash_distance(left, right):
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except (TypeError, ValueError):
        return 64




def find_similar_photo(cursor, photo_hash, listing_id, max_distance=4):
    if not photo_hash:
        return None
    rows = cursor.execute(
        """
        SELECT listing_photo_hashes.listing_id, listing_photo_hashes.photo_hash
        FROM listing_photo_hashes
        JOIN listings ON listings.id = listing_photo_hashes.listing_id
        WHERE listings.status IN ('active', 'hidden_pending_review')
          AND listings.id != ? AND datetime(listings.expires_at) > datetime('now')
        ORDER BY listing_photo_hashes.id DESC
        LIMIT 500
        """, (listing_id,)
    ).fetchall()
    for row in rows:
        distance = hash_distance(photo_hash, row["photo_hash"])
        if distance <= max_distance:
            return {"listing_id": row["listing_id"], "distance": distance}
    return None


def validate_offer_payload(payload):
    for key in ('district', 'university', 'housing_type', 'description', 'phone_number', 'author_gender', 'preferred_gender'):
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > (1000 if key == 'description' else 80)):
            raise ListingServiceError(f"{key}: noto'g'ri matn")
    district = (payload.get("district") or "").strip()[:80]
    university = (payload.get("university") or "").strip()[:80]
    housing_type = (payload.get("housing_type") or "").strip()[:80]
    description = (payload.get("description") or "").strip()[:1000]
    phone_number = (payload.get("phone_number") or "").strip()[:40] or None
    author_gender = (payload.get("author_gender") or "").strip()
    preferred_gender = (payload.get("preferred_gender") or "").strip()
    if not district or not university or not housing_type:
        raise ListingServiceError("district, university and housing_type are required")
    if district not in DISTRICTS or university not in UNIVERSITIES or housing_type not in HOUSING_TYPES:
        raise ListingServiceError("Tuman, universitet yoki uy turi noto'g'ri")
    if phone_number:
        phone_number = re.sub(r'[^0-9+]', '', phone_number)
        if not re.fullmatch(r'\+?[0-9]{9,15}', phone_number):
            raise ListingServiceError("Telefon raqamini tekshiring")
    if author_gender not in {"male", "female"}:
        raise ListingServiceError("author_gender must be male or female")
    if preferred_gender not in {"male", "female", "any"}:
        raise ListingServiceError("preferred_gender must be male, female or any")
    return {
        "district": district,
        "university": university,
        "housing_type": housing_type,
        "description": description or None,
        "phone_number": phone_number,
        "author_gender": author_gender,
        "preferred_gender": preferred_gender,
        "lat": parse_float_field(payload, "lat", minimum=40.0, maximum=42.5),
        "lng": parse_float_field(payload, "lng", minimum=68.0, maximum=71.5),
        "price": parse_int_field(payload, "price", minimum=1, maximum=100_000_000),
        "people_needed": parse_int_field(payload, "people_needed", minimum=1, maximum=10),
        "room_count": parse_int_field(payload, "room_count", minimum=1, maximum=20),
        "has_wifi": bool_from_payload(payload, "has_wifi"),
        "has_ac": bool_from_payload(payload, "has_ac"),
        "has_washing_machine": bool_from_payload(payload, "has_washing_machine"),
        "no_landlord_in_yard": bool_from_payload(payload, "no_landlord_in_yard"),
        "near_metro": bool_from_payload(payload, "near_metro"),
    }


def create_offer_listing(cursor, user, payload, photo_bytes_list, upload_dir, photo_column):
    if not user:
        raise ListingServiceError("Telegram login required", status_code=401)
    if user["bot_started_at"] is None:
        raise ListingServiceError("Bot must be started before publishing", status_code=403)
    if getattr(cursor, 'is_postgres', False):
        cursor.execute('SELECT telegram_user_id FROM users WHERE telegram_user_id = ? FOR UPDATE', (user['telegram_user_id'],))
    elif not cursor.connection.in_transaction:
        cursor.execute('BEGIN IMMEDIATE')
    from backend.lifecycle import expire_listings
    expire_listings(cursor)
    if cursor.execute('SELECT 1 FROM banned_users WHERE telegram_user_id = ?', (user['telegram_user_id'],)).fetchone():
        raise ListingServiceError('Akkaunt bloklangan', 403)
    active_listing = cursor.execute(
        "SELECT id FROM listings WHERE telegram_user_id = ? AND status IN ('active', 'hidden_pending_review')",
        (user["telegram_user_id"],),
    ).fetchone()
    if active_listing:
        raise ListingServiceError(
            "Sizda allaqachon faol e'lon bor. Bitta Telegram akkaunt bitta kvartira joylay oladi.",
            status_code=409,
        )

    values = validate_offer_payload(payload)
    values['lat'] = round(values['lat'] / .002) * .002
    values['lng'] = round(values['lng'] / .003) * .003
    if not user['telegram_username'] and not values['phone_number']:
        raise ListingServiceError('Telegram username yo‘q: ochiq telefon raqamini kiriting')
    if not isinstance(photo_bytes_list, (list, tuple)) or len(photo_bytes_list) > 5:
        raise ListingServiceError('Ko‘pi bilan 5 ta rasm yuklang')
    prepared, seen = [], set()
    for data in photo_bytes_list:
        if not isinstance(data, bytes) or len(data) > 5 * 1024 * 1024:
            raise ListingServiceError('Rasm 5 MB dan katta', 413)
        try:
            with Image.open(io.BytesIO(data)) as source:
                if source.width * source.height > 20_000_000:
                    raise ListingServiceError('Rasm o‘lchami juda katta', 413)
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, 'JPEG', quality=80)
                encoded = buffer.getvalue()
                fingerprint = hashlib.sha256(encoded).hexdigest()
                if fingerprint not in seen:
                    prepared.append((encoded, average_image_hash(image)))
                    seen.add(fingerprint)
        except ListingServiceError:
            raise
        except Exception:
            raise ListingServiceError('Rasmni ochib bo‘lmadi')

    returning_id = " RETURNING id" if getattr(cursor, "is_postgres", False) else ""
    cursor.execute(
        f"""
        INSERT INTO listings (
            telegram_user_id, telegram_username, listing_type, university, district, housing_type,
            description, phone_number, room_count, author_gender, preferred_gender,
            lat, lng, price_per_person, people_needed,
            has_wifi, has_ac, has_washing_machine, no_landlord_in_yard, near_metro, status, expires_at
        )
        VALUES (?, ?, 'offer', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', datetime('now', '+7 days'))
        {returning_id}
        """,
        (
            user["telegram_user_id"],
            user["telegram_username"] or "",
            values["university"],
            values["district"],
            values["housing_type"],
            values["description"],
            values["phone_number"],
            values["room_count"],
            values["author_gender"],
            values["preferred_gender"],
            values["lat"],
            values["lng"],
            values["price"],
            values["people_needed"],
            values["has_wifi"],
            values["has_ac"],
            values["has_washing_machine"],
            values["no_landlord_in_yard"],
            values["near_metro"],
        ),
    )
    listing_id = cursor.fetchone()[0] if getattr(cursor, "is_postgres", False) else cursor.lastrowid
    cursor.execute('UPDATE listings SET location_blurred = 1 WHERE id = ?', (listing_id,))

    duplicate_matches = []
    stored_keys = []
    try:
        for index, (encoded, image_hash) in enumerate(prepared):
            similar = find_similar_photo(cursor, image_hash, listing_id)
            if similar:
                duplicate_matches.append(similar)
            file_path = store_photo(encoded, upload_dir)
            stored_keys.append(file_path)
            cursor.execute(
                f"INSERT INTO listing_photos (listing_id, {photo_column}, sort_order) VALUES (?, ?, ?)",
                (listing_id, file_path, index),
            )
            if image_hash:
                cursor.execute(
                "INSERT INTO listing_photo_hashes (listing_id, photo_hash) VALUES (?, ?)",
                (listing_id, image_hash),
            )

        status = "active"
        if duplicate_matches:
            status = "hidden_pending_review"
            cursor.execute("UPDATE listings SET status = ? WHERE id = ?", (status, listing_id))

        listing = cursor.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
        from backend.notifications import enqueue_publication, enqueue_admin
        if status == 'active':
            enqueue_publication(cursor, listing_id)
        else:
            enqueue_admin(cursor, f'review:{listing_id}', f"E'lon {listing_id}: /review {listing_id} approve yoki ban")
        return {
            "listing_id": listing_id,
            "listing": listing,
            "status": status,
            "duplicate_matches": duplicate_matches,
            "photo_keys": stored_keys,
        }
    except Exception:
        for key in stored_keys:
            try:
                delete_photo(key, upload_dir)
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Photo cleanup failed for key %s',key)
        raise
