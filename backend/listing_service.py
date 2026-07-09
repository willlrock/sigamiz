import base64
import binascii
import io
import os

from PIL import Image


class ListingServiceError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def bool_from_payload(payload, key):
    return 1 if payload.get(key) in (True, 1, "1", "true", "on", "yes") else 0


def parse_int_field(payload, key, *, minimum=None, maximum=None, required=True):
    raw = payload.get(key)
    if raw in (None, ""):
        if required:
            raise ListingServiceError(f"{key} is required")
        return None
    if isinstance(raw, str):
        raw = raw.replace(" ", "").replace(",", "").replace(".", "")
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
    if raw in (None, ""):
        raise ListingServiceError(f"{key} is required")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ListingServiceError(f"{key} must be a number")
    if minimum is not None and value < minimum:
        raise ListingServiceError(f"{key} is too small")
    if maximum is not None and value > maximum:
        raise ListingServiceError(f"{key} is too large")
    return value


def decode_photo_data(photo_data):
    if not photo_data:
        raise ListingServiceError("photo is empty")
    encoded = str(photo_data)
    if "," in encoded:
        encoded = encoded.split(",", 1)[1]
    try:
        return base64.b64decode(encoded, validate=True)
    except binascii.Error:
        raise ListingServiceError("photo must be base64")


def average_image_hash(image):
    small = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    values = list(small.getdata())
    avg = sum(values) / len(values)
    bits = "".join("1" if value >= avg else "0" for value in values)
    return f"{int(bits, 2):016x}"


def hash_distance(left, right):
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except (TypeError, ValueError):
        return 64


def ensure_listing_photo_hashes_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS listing_photo_hashes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL,
            photo_hash TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (listing_id) REFERENCES listings (id)
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_listing_photo_hashes_hash ON listing_photo_hashes (photo_hash)"
    )


def find_similar_photo(cursor, photo_hash, max_distance=8):
    ensure_listing_photo_hashes_table(cursor)
    rows = cursor.execute(
        """
        SELECT listing_photo_hashes.listing_id, listing_photo_hashes.photo_hash
        FROM listing_photo_hashes
        JOIN listings ON listings.id = listing_photo_hashes.listing_id
        WHERE listings.status IN ('active', 'hidden_pending_review')
        ORDER BY listing_photo_hashes.id DESC
        LIMIT 500
        """
    ).fetchall()
    for row in rows:
        distance = hash_distance(photo_hash, row["photo_hash"])
        if distance <= max_distance:
            return {"listing_id": row["listing_id"], "distance": distance}
    return None


def validate_offer_payload(payload):
    district = (payload.get("district") or "").strip()[:80]
    university = (payload.get("university") or "").strip()[:80]
    housing_type = (payload.get("housing_type") or "").strip()[:80]
    description = (payload.get("description") or "").strip()[:1000]
    phone_number = (payload.get("phone_number") or "").strip()[:40] or None
    author_gender = (payload.get("author_gender") or "").strip()
    preferred_gender = (payload.get("preferred_gender") or "").strip()
    if not district or not university or not housing_type:
        raise ListingServiceError("district, university and housing_type are required")
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
    photo_bytes_list = list(photo_bytes_list or [])[:5]

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
    listing_dir = os.path.join(upload_dir, str(listing_id))
    os.makedirs(listing_dir, exist_ok=True)
    ensure_listing_photo_hashes_table(cursor)

    duplicate_matches = []
    for index, photo_bytes in enumerate(photo_bytes_list):
        try:
            image = Image.open(io.BytesIO(photo_bytes))
            image.verify()
            image = Image.open(io.BytesIO(photo_bytes))
        except Exception:
            raise ListingServiceError("photo is not a valid image")
        image_hash = average_image_hash(image)
        similar = find_similar_photo(cursor, image_hash)
        if similar:
            duplicate_matches.append(similar)
        if image.width > 1200:
            ratio = 1200 / float(image.width)
            image = image.resize((1200, int(float(image.height) * ratio)), Image.Resampling.LANCZOS)
        file_path = os.path.join(listing_dir, f"{index}.jpg")
        image.convert("RGB").save(file_path, "JPEG", quality=80)
        cursor.execute(
            f"INSERT INTO listing_photos (listing_id, {photo_column}, sort_order) VALUES (?, ?, ?)",
            (listing_id, file_path, index),
        )
        cursor.execute(
            "INSERT INTO listing_photo_hashes (listing_id, photo_hash) VALUES (?, ?)",
            (listing_id, image_hash),
        )

    status = "active"
    if duplicate_matches:
        status = "hidden_pending_review"
        cursor.execute("UPDATE listings SET status = ? WHERE id = ?", (status, listing_id))

    listing = cursor.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    return {
        "listing_id": listing_id,
        "listing": listing,
        "status": status,
        "duplicate_matches": duplicate_matches,
    }
