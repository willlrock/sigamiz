import io
import json
import math
import os
import random
import sqlite3
import threading
import traceback
from contextlib import contextmanager

import requests
import telebot
from dotenv import load_dotenv
from PIL import Image
from telebot import types
from telebot.custom_filters import IsDigitFilter

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
SITE_URL = os.getenv("SITE_URL", "https://klapa.net").rstrip("/")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "backend", "database.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
SESSION_PATH = os.path.join(BASE_DIR, "bot_sessions.json")

bot = telebot.TeleBot(TOKEN, use_class_middlewares=True)

bot.add_custom_filter(IsDigitFilter())


class AddListingStates:
    rules_confirm = "rules_confirm"
    gender_author = "gender_author"
    location = "location"
    university = "university"
    district = "district"
    housing_type = "housing_type"
    room_count = "room_count"
    price = "price"
    roommates_needed = "roommates_needed"
    preferred_gender = "preferred_gender"
    amenities = "amenities"
    description = "description"
    phone_visibility = "phone_visibility"
    phone = "phone"
    photos = "photos"
    confirm = "confirm"


class SearchStates:
    gender_author = "search_gender_author"
    preferred_gender = "search_preferred_gender"
    price_min = "search_price_min"
    price_max = "search_price_max"
    amenities = "search_amenities"
    location_choice = "search_location_choice"
    district = "search_district"


DISTRICTS = [
    "Mirzo-Ulug'bek", "Yunusobod", "Mirobod", "Chilonzor", "Yakkasaroy",
    "Shayxontohur", "Uchtepa", "Sergeli", "Yashnobod", "Bektemir", "Olmazor"
]

DISTRICT_CENTERS = {
    "Mirzo-Ulug'bek": (41.3250, 69.3340),
    "Yunusobod": (41.3650, 69.2850),
    "Mirobod": (41.2960, 69.2900),
    "Chilonzor": (41.2850, 69.2030),
    "Yakkasaroy": (41.2850, 69.2550),
    "Shayxontohur": (41.3260, 69.2420),
    "Uchtepa": (41.3030, 69.1660),
    "Sergeli": (41.2260, 69.2200),
    "Yashnobod": (41.2960, 69.3700),
    "Bektemir": (41.2070, 69.3340),
    "Olmazor": (41.3450, 69.2050),
}

DISTRICT_ALIASES = {
    "mirzo ulugbek": "Mirzo-Ulug'bek",
    "mirzo-ulugbek": "Mirzo-Ulug'bek",
    "mirzo ulug'bek": "Mirzo-Ulug'bek",
    "yunusobod": "Yunusobod",
    "yunusabad": "Yunusobod",
    "mirobod": "Mirobod",
    "mirabad": "Mirobod",
    "chilonzor": "Chilonzor",
    "chilanzar": "Chilonzor",
    "yakkasaroy": "Yakkasaroy",
    "yakkasaray": "Yakkasaroy",
    "shayxontohur": "Shayxontohur",
    "shayhantaur": "Shayxontohur",
    "uchtepa": "Uchtepa",
    "sergeli": "Sergeli",
    "yashnobod": "Yashnobod",
    "yashnabad": "Yashnobod",
    "bektemir": "Bektemir",
    "olmazor": "Olmazor",
    "almazar": "Olmazor",
}

UNIVERSITIES = ["TATU", "WIUT", "INHA", "O'zMU", "TMI", "TDIU", "TSUULL", "TTA", "Other"]
HOUSING_TYPES = ["Kvartira", "Xonadonli uy", "Yotoqxona", "Boshqa"]
AMENITIES = [
    ("wifi", "Wi-Fi", "has_wifi"),
    ("ac", "Konditsioner", "has_ac"),
    ("washer", "Kir yuvish mashinasi", "has_washing_machine"),
    ("no_landlord", "Xo'jayin hovlida turmaydi", "no_landlord_in_yard"),
    ("metro", "Metro yaqin", "near_metro"),
]
AMENITY_LABELS = {key: label for key, label, _ in AMENITIES}
AMENITY_COLUMNS = {key: column for key, _, column in AMENITIES}
MAX_INLINE_RESULTS = 8
session_lock = threading.Lock()


def session_key(user_id, chat_id):
    return f"{chat_id}:{user_id}"


def load_sessions_unlocked():
    if not os.path.exists(SESSION_PATH):
        return {}
    try:
        with open(SESSION_PATH, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}


def save_sessions_unlocked(sessions):
    tmp_path = f"{SESSION_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as file:
        json.dump(sessions, file, ensure_ascii=False)
    os.replace(tmp_path, SESSION_PATH)


@contextmanager
def draft_data(user_id, chat_id):
    key = session_key(user_id, chat_id)
    with session_lock:
        sessions = load_sessions_unlocked()
        data = dict(sessions.get(key, {}))
    try:
        yield data
    finally:
        with session_lock:
            sessions = load_sessions_unlocked()
            sessions[key] = data
            save_sessions_unlocked(sessions)


def clear_draft(user_id, chat_id):
    key = session_key(user_id, chat_id)
    with session_lock:
        sessions = load_sessions_unlocked()
        if key in sessions:
            sessions.pop(key, None)
            save_sessions_unlocked(sessions)


def main_menu_markup():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📢 E'lon joylashtirish", callback_data="type_offer"),
        types.InlineKeyboardButton("🔍 Xonadosh/joy qidirish", callback_data="type_seek"),
        types.InlineKeyboardButton("🗺 Xaritani ochish", url=f"{SITE_URL}/xarita"),
    )
    return markup


def chunked_markup(buttons, row_width=2):
    markup = types.InlineKeyboardMarkup(row_width=row_width)
    markup.add(*buttons)
    return markup


def gender_label(value):
    return {"male": "Erkak", "female": "Ayol", "any": "Farqi yo'q"}.get(value or "", "-")


def format_price(value):
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "-"


def parse_optional_price(text):
    text = (text or "").strip().replace(" ", "")
    if text.lower() == "/skip":
        return None, None
    if not text.isdigit():
        return None, "Narxni raqam bilan yozing yoki /skip yuboring."
    value = int(text)
    if value < 0 or value > 50_000_000:
        return None, "Narx 0 dan 50 000 000 so'mgacha bo'lishi kerak."
    return value, None


def blur_location(lat, lng):
    radius = random.uniform(0.00135, 0.0018)
    angle = random.uniform(0, 2 * math.pi)
    return lat + radius * math.cos(angle), lng + radius * math.sin(angle)


def normalize_district_name(value):
    if not value:
        return None
    cleaned = str(value).lower()
    for suffix in ["district", "tumani", "район", "тумани", "tuman"]:
        cleaned = cleaned.replace(suffix, "")
    cleaned = cleaned.replace("ʻ", "'").replace("’", "'").replace("`", "'")
    cleaned = " ".join(cleaned.replace("-", " ").split())
    for key, district in DISTRICT_ALIASES.items():
        normalized_key = " ".join(key.replace("-", " ").split())
        if normalized_key in cleaned:
            return district
    return None


def nearest_district(lat, lng):
    def distance_sq(center):
        center_lat, center_lng = center
        return (lat - center_lat) ** 2 + (lng - center_lng) ** 2

    return min(DISTRICT_CENTERS.items(), key=lambda item: distance_sq(item[1]))[0]


def detect_district(lat, lng):
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "format": "jsonv2",
                "lat": lat,
                "lon": lng,
                "accept-language": "uz,en,ru",
                "zoom": 13,
            },
            headers={"User-Agent": "sigamiz-bot/1.0"},
            timeout=4,
        )
        response.raise_for_status()
        address = response.json().get("address", {})
        for key in ("city_district", "suburb", "borough", "county", "municipality"):
            district = normalize_district_name(address.get(key))
            if district:
                return district
    except Exception:
        pass
    return nearest_district(lat, lng)


def is_banned(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM banned_users WHERE telegram_user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None


def is_admin_chat(message):
    if not ADMIN_CHAT_ID:
        return False
    allowed_ids = {item.strip() for item in ADMIN_CHAT_ID.split(",") if item.strip()}
    return str(message.chat.id) in allowed_ids


def has_active_listing(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM listings WHERE telegram_user_id = ? AND status IN ('active', 'hidden_pending_review')",
        (user_id,),
    )
    res = cursor.fetchone()
    conn.close()
    return res is not None


def get_listing_photo_column(cursor):
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(listing_photos)").fetchall()}
    if "photo_path" in columns:
        return "photo_path"
    if "file_path" in columns:
        return "file_path"
    return "file_path"


def amenities_markup(prefix="amenity"):
    buttons = [
        types.InlineKeyboardButton(label, callback_data=f"{prefix}_{key}")
        for key, label, _ in AMENITIES
    ]
    buttons.append(types.InlineKeyboardButton("✅ Tayyor", callback_data=f"{prefix}_done"))
    return chunked_markup(buttons, row_width=2)


def districts_markup(prefix="dist"):
    buttons = [types.InlineKeyboardButton(dist, callback_data=f"{prefix}_{dist}") for dist in DISTRICTS]
    return chunked_markup(buttons, row_width=2)


def cancel_flow(user_id, chat_id, text="Bekor qilindi."):
    clear_draft(user_id, chat_id)
    bot.send_message(chat_id, text, reply_markup=main_menu_markup())


@bot.message_handler(commands=["start"])
def send_welcome(message):
    text = (
        "Salom! Sigamiz botiga xush kelibsiz.\n\n"
        "Bu yerda siz xonadosh topish uchun e'lon joylashtirishingiz yoki mavjud uylarni qidirishingiz mumkin."
    )
    bot.reply_to(message, text, reply_markup=main_menu_markup())


@bot.message_handler(commands=["cancel"])
def cancel_command(message):
    cancel_flow(message.from_user.id, message.chat.id)


@bot.message_handler(commands=["add"])
def start_add_flow(message):
    if is_banned(message.from_user.id):
        bot.reply_to(message, "Sizga bu botdan foydalanish taqiqlangan.")
        return
    bot.reply_to(message, "Nima qilmoqchisiz?", reply_markup=main_menu_markup())


@bot.message_handler(commands=["review"])
def review_listing(message):
    if not is_admin_chat(message):
        bot.reply_to(message, "Bu buyruq faqat admin chat uchun.")
        return

    parts = (message.text or "").split()
    if len(parts) != 3 or parts[2] not in {"approve", "ban"}:
        bot.reply_to(message, "Format: /review <listing_id> approve|ban")
        return

    try:
        listing_id = int(parts[1])
    except ValueError:
        bot.reply_to(message, "Listing ID raqam bo'lishi kerak.")
        return

    action = parts[2]
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    listing = cursor.execute(
        "SELECT id, telegram_user_id, status FROM listings WHERE id = ?",
        (listing_id,),
    ).fetchone()

    if not listing:
        conn.close()
        bot.reply_to(message, f"E'lon {listing_id} topilmadi.")
        return

    if action == "approve":
        cursor.execute("UPDATE listings SET status = 'active', report_count = 0 WHERE id = ?", (listing_id,))
        response = f"E'lon {listing_id} yana active holatiga qaytarildi."
    else:
        owner_id = listing["telegram_user_id"]
        cursor.execute("UPDATE listings SET status = 'removed' WHERE id = ?", (listing_id,))
        banned_columns = {row[1] for row in cursor.execute("PRAGMA table_info(banned_users)").fetchall()}
        if "reason" in banned_columns:
            cursor.execute(
                "INSERT OR REPLACE INTO banned_users (telegram_user_id, reason) VALUES (?, ?)",
                (owner_id, f"Admin review ban for listing {listing_id}"),
            )
        else:
            cursor.execute("INSERT OR IGNORE INTO banned_users (telegram_user_id) VALUES (?)", (owner_id,))
        response = f"E'lon {listing_id} removed qilindi, muallif {owner_id} ban qilindi."

    conn.commit()
    conn.close()
    bot.reply_to(message, response)


@bot.callback_query_handler(func=lambda call: call.data == "type_offer")
def handle_type_offer(call):
    bot.answer_callback_query(call.id)
    if is_banned(call.from_user.id):
        bot.send_message(call.message.chat.id, "Sizga bu botdan foydalanish taqiqlangan.")
        return
    if has_active_listing(call.from_user.id):
        bot.send_message(
            call.message.chat.id,
            "Sizda allaqachon faol e'lon bor. Yangisini qo'shishdan oldin uni /my orqali o'chiring yoki tugating.",
        )
        return

    rules_text = (
        "📋 Qoidalar:\n"
        "— Faqat xonadosh/joy qidirish uchun, butun kvartira ijarasi emas;\n"
        "— Vositachilar va maklerlar taqiqlanadi;\n"
        "— E'lon 7 kundan keyin avtomatik yashiriladi;\n"
        "— Ma'lumotlarni halol va aniq kiriting."
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✅ Davom etish, men makler emasman", callback_data="rules_ack"),
        types.InlineKeyboardButton("❌ Bekor qilish", callback_data="rules_cancel"),
    )
    bot.send_message(call.message.chat.id, rules_text, reply_markup=markup)
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data.clear()
        data["flow_step"] = AddListingStates.rules_confirm


@bot.callback_query_handler(func=lambda call: call.data in {"rules_ack", "rules_cancel"})
def handle_rules_confirm(call):
    bot.answer_callback_query(call.id)
    if call.data == "rules_cancel":
        bot.edit_message_text("Bekor qilindi.", call.message.chat.id, call.message.message_id)
        clear_draft(call.from_user.id, call.message.chat.id)
        return

    bot.edit_message_text("Qoidalar qabul qilindi.", call.message.chat.id, call.message.message_id)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👨 Erkak", callback_data="gender_male"),
        types.InlineKeyboardButton("👩 Ayol", callback_data="gender_female"),
    )
    bot.send_message(call.message.chat.id, "Jinsingiz:", reply_markup=markup)
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data["flow_step"] = AddListingStates.gender_author


@bot.callback_query_handler(func=lambda call: call.data.startswith("gender_"))
def handle_gender_author(call):
    gender = call.data.split("_", 1)[1]
    if gender not in {"male", "female"}:
        bot.answer_callback_query(call.id, "Noto'g'ri tanlov")
        return
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data["listing_type"] = "offer"
        data["author_gender"] = gender
        data["flow_step"] = AddListingStates.location
    bot.answer_callback_query(call.id)
    bot.edit_message_text(f"Jins: {gender_label(gender)}", call.message.chat.id, call.message.message_id)
    location_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    location_markup.add(types.KeyboardButton("Lokatsiyani yuborish", request_location=True))
    bot.send_message(call.message.chat.id, "Uy joylashgan taxminiy lokatsiyani yuboring.", reply_markup=location_markup)


@bot.message_handler(content_types=["location"])
def handle_location(message):
    if current_flow_step(message.from_user.id, message.chat.id) != AddListingStates.location:
        bot.reply_to(
            message,
            "E'lon joylashtirish uchun avval /add buyrug'ini yuboring va \"Opublikovat\" tugmasini bosing.",
        )
        return

    try:
        detected_district = detect_district(message.location.latitude, message.location.longitude)
        with draft_data(message.from_user.id, message.chat.id) as data:
            data.setdefault("listing_type", "offer")
            data.setdefault("author_gender", None)
            data["district"] = detected_district
            data["lat"], data["lng"] = blur_location(message.location.latitude, message.location.longitude)
            data["flow_step"] = AddListingStates.university

        buttons = [types.InlineKeyboardButton(uni, callback_data=f"uni_{uni}") for uni in UNIVERSITIES]
        bot.send_message(
            message.chat.id,
            f"Lokatsiya saqlandi. Tuman: {detected_district}.",
            reply_markup=types.ReplyKeyboardRemove(),
        )
        bot.send_message(
            message.chat.id,
            "Universitetni tanlang:",
            reply_markup=chunked_markup(buttons, row_width=2),
        )
    except Exception:
        print(f"ERROR in handle_location: {traceback.format_exc()}")
        bot.reply_to(message, "Xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")


@bot.message_handler(func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == AddListingStates.location, content_types=["text"])
def handle_location_text(message):
    bot.reply_to(message, "Iltimos, Telegram lokatsiya tugmasi orqali joylashuvni yuboring.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("uni_"))
def handle_university(call):
    uni = call.data.split("_", 1)[1]
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data["university"] = uni
        data["flow_step"] = AddListingStates.housing_type
    bot.answer_callback_query(call.id)
    bot.edit_message_text(f"Universitet: {uni}", call.message.chat.id, call.message.message_id)
    buttons = [types.InlineKeyboardButton(opt, callback_data=f"house_{opt}") for opt in HOUSING_TYPES]
    bot.send_message(call.message.chat.id, "Uy turini tanlang:", reply_markup=chunked_markup(buttons, row_width=2))


@bot.callback_query_handler(func=lambda call: call.data.startswith("house_"))
def handle_housing_type(call):
    h_type = call.data.split("_", 1)[1]
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data["housing_type"] = h_type
        data["flow_step"] = AddListingStates.room_count
    bot.answer_callback_query(call.id)
    bot.edit_message_text(f"Uy turi: {h_type}", call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, "Nechta xona? Masalan: 2")


@bot.message_handler(func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == AddListingStates.room_count, is_digit=True)
def handle_room_count(message):
    room_count = int(message.text)
    if room_count < 1 or room_count > 10:
        bot.reply_to(message, "Xona soni 1 dan 10 gacha bo'lishi kerak.")
        return
    with draft_data(message.from_user.id, message.chat.id) as data:
        data["room_count"] = room_count
        data["flow_step"] = AddListingStates.price
    bot.send_message(message.chat.id, "Bir kishi uchun oylik narxni yozing (so'mda). Masalan: 900000")


@bot.message_handler(func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == AddListingStates.room_count, content_types=["text"])
def handle_room_count_invalid(message):
    bot.reply_to(message, "Xona sonini faqat raqam bilan yozing. Masalan: 2")


@bot.message_handler(func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == AddListingStates.price, is_digit=True)
def handle_price(message):
    price = int(message.text)
    if price < 100_000 or price > 20_000_000:
        bot.reply_to(message, "Narx 100 000 dan 20 000 000 so'mgacha bo'lishi kerak.")
        return
    with draft_data(message.from_user.id, message.chat.id) as data:
        data["price"] = price
        data["flow_step"] = AddListingStates.roommates_needed

    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("1", callback_data="room_1"),
        types.InlineKeyboardButton("2", callback_data="room_2"),
        types.InlineKeyboardButton("3+", callback_data="room_3"),
    )
    bot.send_message(message.chat.id, "Nechta xonadosh kerak?", reply_markup=markup)


@bot.message_handler(func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == AddListingStates.price, content_types=["text"])
def handle_price_invalid(message):
    bot.reply_to(message, "Narxni faqat raqam bilan yozing. Masalan: 900000")


@bot.callback_query_handler(func=lambda call: call.data.startswith("room_"))
def handle_roommates(call):
    needed = call.data.split("_", 1)[1]
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data["needed"] = needed
        data["flow_step"] = AddListingStates.preferred_gender
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("👨 Erkak", callback_data="pref_male"),
        types.InlineKeyboardButton("👩 Ayol", callback_data="pref_female"),
        types.InlineKeyboardButton("🤷 Farqi yo'q", callback_data="pref_any"),
    )
    bot.answer_callback_query(call.id)
    bot.edit_message_text("Qanday xonadosh qidiryapsiz?", call.message.chat.id, call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("pref_"))
def handle_preferred_gender(call):
    pref = call.data.split("_", 1)[1]
    if pref not in {"male", "female", "any"}:
        bot.answer_callback_query(call.id, "Noto'g'ri tanlov")
        return
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data["preferred_gender"] = pref
        data["amenities"] = []
        data["flow_step"] = AddListingStates.amenities
    bot.answer_callback_query(call.id)
    bot.edit_message_text("Qulayliklarni tanlang:", call.message.chat.id, call.message.message_id, reply_markup=amenities_markup("amenity"))


@bot.callback_query_handler(func=lambda call: call.data.startswith("amenity_"))
def handle_amenities(call):
    value = call.data.split("_", 1)[1]
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        if value == "done":
            bot.answer_callback_query(call.id)
            labels = [AMENITY_LABELS.get(key, key) for key in data.get("amenities", [])]
            data["flow_step"] = AddListingStates.description
            text = "Qulayliklar saqlandi"
            if labels:
                text += ": " + ", ".join(labels)
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "Qisqacha tavsif yozing yoki /skip yuboring.")
            return
        if value not in AMENITY_LABELS:
            bot.answer_callback_query(call.id, "Noto'g'ri tanlov")
            return
        amenities = data.setdefault("amenities", [])
        if value in amenities:
            amenities.remove(value)
            bot.answer_callback_query(call.id, f"O'chirildi: {AMENITY_LABELS[value]}")
        else:
            amenities.append(value)
            bot.answer_callback_query(call.id, f"Qo'shildi: {AMENITY_LABELS[value]}")


@bot.message_handler(func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == AddListingStates.description, content_types=["text"])
def handle_description(message):
    text = (message.text or "").strip()
    with draft_data(message.from_user.id, message.chat.id) as data:
        data["description"] = None if text.lower() == "/skip" else text[:1000]
        data["flow_step"] = AddListingStates.phone_visibility

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✅ Ha, telefon ko'rinsin", callback_data="phone_yes"),
        types.InlineKeyboardButton("❌ Yo'q, faqat Telegram", callback_data="phone_no"),
    )
    bot.send_message(message.chat.id, "Telefon raqamingizni ko'rsatishni xohlaysizmi?", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("phone_"))
def handle_phone_visibility(call):
    bot.answer_callback_query(call.id)
    if call.data == "phone_no":
        with draft_data(call.from_user.id, call.message.chat.id) as data:
            data["phone"] = None
            data["photos"] = []
            data["flow_step"] = AddListingStates.photos
        bot.edit_message_text("Yaxshi, faqat Telegram orqali bog'lanishadi.", call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "Rasmlarni yuboring (5 tagacha). Tugatgach /done yozing.")
        return

    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data["flow_step"] = AddListingStates.phone
    bot.edit_message_text("Siz telefon raqamingizni ko'rsatishni tanladingiz.", call.message.chat.id, call.message.message_id)
    contact_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    contact_markup.add(types.KeyboardButton("Kontaktni yuborish", request_contact=True))
    bot.send_message(
        call.message.chat.id,
        "Pastdagi tugma orqali telefon raqamingizni yuboring.",
        reply_markup=contact_markup,
    )


@bot.message_handler(func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == AddListingStates.phone, content_types=["contact"])
def handle_phone_contact(message):
    contact = message.contact
    if contact.user_id and contact.user_id != message.from_user.id:
        bot.reply_to(message, "Iltimos, faqat o'zingizning kontaktingizni yuboring.")
        return

    phone = contact.phone_number or ""
    if len(phone) < 5:
        bot.reply_to(message, "Telefon raqam juda qisqa. Masalan: +998901234567")
        return
    if not phone.startswith("+"):
        phone = f"+{phone}"

    with draft_data(message.from_user.id, message.chat.id) as data:
        data["phone"] = phone[:40]
        data["photos"] = []
        data["flow_step"] = AddListingStates.photos
    bot.send_message(
        message.chat.id,
        "Raqam saqlandi. Rasmlarni yuboring (5 tagacha). Tugatgach /done yozing.",
        reply_markup=types.ReplyKeyboardRemove(),
    )


@bot.message_handler(func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == AddListingStates.phone, content_types=["text"])
def handle_phone(message):
    text = (message.text or "").strip()
    if len(text) < 5:
        bot.reply_to(message, "Telefon raqam juda qisqa. Masalan: +998901234567")
        return
    with draft_data(message.from_user.id, message.chat.id) as data:
        data["phone"] = text[:40]
        data["photos"] = []
        data["flow_step"] = AddListingStates.photos
    bot.send_message(
        message.chat.id,
        "Rasmlarni yuboring (5 tagacha). Tugatgach /done yozing.",
        reply_markup=types.ReplyKeyboardRemove(),
    )


@bot.message_handler(func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == AddListingStates.photos, content_types=["photo"])
def handle_photos(message):
    with draft_data(message.from_user.id, message.chat.id) as data:
        photos = data.setdefault("photos", [])
        if len(photos) < 5:
            file_id = message.photo[-1].file_id
            photos.append(file_id)
            bot.reply_to(message, f"Rasm qo'shildi: {len(photos)}/5. Tugatish uchun /done yuboring.")
        else:
            bot.reply_to(message, "5 ta rasm limiti to'ldi. Tugatish uchun /done yuboring.")


REQUIRED_LISTING_FIELDS = {
    "author_gender": "jins",
    "district": "tuman",
    "lat": "lokatsiya",
    "lng": "lokatsiya",
    "university": "universitet",
    "housing_type": "uy turi",
    "room_count": "xona soni",
    "price": "narx",
    "needed": "xonadosh soni",
    "preferred_gender": "xonadosh jinsi",
}


def missing_listing_fields(data):
    missing = []
    for key, label in REQUIRED_LISTING_FIELDS.items():
        if data.get(key) in (None, "", []):
            missing.append(label)
    return sorted(set(missing))


@bot.message_handler(content_types=["text"], func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == AddListingStates.photos and (message.text or "").strip().lower() == "/done")
def confirm_listing(message):
    missing = []
    with draft_data(message.from_user.id, message.chat.id) as data:
        data["flow_step"] = AddListingStates.confirm
        missing = missing_listing_fields(data)
        if not missing:
            amenities = [AMENITY_LABELS.get(key, key) for key in data.get("amenities", [])]
            phone_status = "ko'rsatiladi" if data.get("phone") else "faqat Telegram"
            summary = (
                "📌 E'lonni tekshiring:\n\n"
                f"🏠 Uy turi: {data.get('housing_type') or '-'}\n"
                f"📍 Tuman: {data.get('district') or '-'}\n"
                f"🎓 Universitet: {data.get('university') or '-'}\n"
                f"🚪 Xonalar: {data.get('room_count') or '-'}\n"
                f"💰 Narx: {format_price(data.get('price'))} so'm/kishi\n"
                f"👥 Kerak: {data.get('needed') or '-'} kishi\n"
                f"🧑 Siz: {gender_label(data.get('author_gender'))}\n"
                f"🤝 Xonadosh: {gender_label(data.get('preferred_gender'))}\n"
                f"☎️ Telefon: {phone_status}\n"
                f"✨ Qulayliklar: {', '.join(amenities) if amenities else '-'}\n"
                f"📝 Tavsif: {data.get('description') or '-'}\n"
                f"🖼 Rasmlar: {len(data.get('photos', []))}"
            )
    if missing:
        clear_draft(message.from_user.id, message.chat.id)
        bot.send_message(
            message.chat.id,
            "E'lon ma'lumotlari to'liq saqlanmadi. Iltimos, /add orqali qayta boshlang.",
            reply_markup=main_menu_markup(),
        )
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("✅ Joylashtirish", callback_data="confirm_yes"),
        types.InlineKeyboardButton("❌ Bekor qilish", callback_data="confirm_no"),
    )
    bot.send_message(message.chat.id, summary, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_"))
def handle_confirm(call):
    bot.answer_callback_query(call.id)
    if call.data == "confirm_yes":
        try:
            listing_id = save_listing_to_db(call.from_user.id, call.message.chat.id, call.from_user.username)
        except Exception:
            print(f"ERROR in save_listing_to_db: {traceback.format_exc()}")
            bot.send_message(call.message.chat.id, "E'lonni saqlashda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.")
            return
        bot.edit_message_text(f"E'lon joylashtirildi. ID: {listing_id}", call.message.chat.id, call.message.message_id)
        clear_draft(call.from_user.id, call.message.chat.id)
    else:
        bot.edit_message_text("E'lon yaratish bekor qilindi.", call.message.chat.id, call.message.message_id)
        clear_draft(call.from_user.id, call.message.chat.id)


def save_listing_to_db(user_id, chat_id, username=None):
    with draft_data(user_id, chat_id) as data:
        missing = missing_listing_fields(data)
        if missing:
            raise ValueError(f"Incomplete listing draft: {', '.join(missing)}")
        amenities = data.get("amenities", [])
        amenity_flags = {column: 1 if key in amenities else 0 for key, _, column in AMENITIES}
        needed_val = data.get("needed")
        needed_int = 3 if needed_val == "3" else int(needed_val)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO listings (
                telegram_user_id, telegram_username, listing_type, university, district, housing_type,
                description, phone_number, room_count, author_gender, preferred_gender,
                lat, lng, price_per_person, people_needed,
                has_wifi, has_ac, has_washing_machine, no_landlord_in_yard, near_metro, expires_at
            )
            VALUES (?, ?, 'offer', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '+7 days'))
            """,
            (
                user_id,
                username or "",
                data.get("university"),
                data.get("district"),
                data.get("housing_type"),
                data.get("description"),
                data.get("phone"),
                data.get("room_count"),
                data.get("author_gender"),
                data.get("preferred_gender"),
                data["lat"],
                data["lng"],
                data["price"],
                needed_int,
                amenity_flags["has_wifi"],
                amenity_flags["has_ac"],
                amenity_flags["has_washing_machine"],
                amenity_flags["no_landlord_in_yard"],
                amenity_flags["near_metro"],
            ),
        )
        listing_id = cursor.lastrowid
        photo_column = get_listing_photo_column(cursor)

        os.makedirs(os.path.join(UPLOAD_DIR, str(listing_id)), exist_ok=True)
        for i, file_id in enumerate(data.get("photos", [])):
            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            img = Image.open(io.BytesIO(downloaded_file))
            if img.width > 1200:
                ratio = 1200 / float(img.width)
                height = int(float(img.height) * ratio)
                img = img.resize((1200, height), Image.Resampling.LANCZOS)
            file_path = os.path.join(UPLOAD_DIR, str(listing_id), f"{i}.jpg")
            img.save(file_path, "JPEG", quality=80)
            cursor.execute(f"INSERT INTO listing_photos (listing_id, {photo_column}) VALUES (?, ?)", (listing_id, file_path))

        conn.commit()
        conn.close()
        return listing_id


@bot.callback_query_handler(func=lambda call: call.data == "type_seek")
def handle_type_seek(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text("🔍 Mavjud e'lonlar orasidan qidiramiz.", call.message.chat.id, call.message.message_id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🌐 Saytda qidirish", url=f"{SITE_URL}/xarita?listing_type=offer"),
        types.InlineKeyboardButton("🤖 Botda davom etish", callback_data="seek_in_bot"),
    )
    bot.send_message(call.message.chat.id, "Qanday qidirishni xohlaysiz?", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "seek_in_bot")
def handle_seek_in_bot(call):
    bot.answer_callback_query(call.id)
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data.clear()
        data["flow_step"] = SearchStates.gender_author
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("👨 Erkak", callback_data="sgender_male"),
        types.InlineKeyboardButton("👩 Ayol", callback_data="sgender_female"),
    )
    bot.send_message(call.message.chat.id, "Jinsingiz:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("sgender_"))
def handle_search_gender(call):
    gender = call.data.split("_", 1)[1]
    if gender not in {"male", "female"}:
        bot.answer_callback_query(call.id, "Noto'g'ri tanlov")
        return
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data["s_gender"] = gender
        data["flow_step"] = SearchStates.preferred_gender
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("👨 Erkak", callback_data="spref_male"),
        types.InlineKeyboardButton("👩 Ayol", callback_data="spref_female"),
        types.InlineKeyboardButton("🤷 Farqi yo'q", callback_data="spref_any"),
    )
    bot.edit_message_text("Qanday xonadosh/uy egasini qidiryapsiz?", call.message.chat.id, call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("spref_"))
def handle_search_preferred_gender(call):
    pref = call.data.split("_", 1)[1]
    if pref not in {"male", "female", "any"}:
        bot.answer_callback_query(call.id, "Noto'g'ri tanlov")
        return
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data["s_preferred_gender"] = pref
        data["flow_step"] = SearchStates.price_min
    bot.answer_callback_query(call.id)
    bot.edit_message_text("Minimal narxni yozing yoki /skip yuboring:", call.message.chat.id, call.message.message_id)


@bot.message_handler(func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == SearchStates.price_min, content_types=["text"])
def handle_search_price_min(message):
    value, error = parse_optional_price(message.text)
    if error:
        bot.reply_to(message, error)
        return
    with draft_data(message.from_user.id, message.chat.id) as data:
        data["s_price_min"] = value
        data["flow_step"] = SearchStates.price_max
    bot.send_message(message.chat.id, "Maksimal narxni yozing yoki /skip yuboring:")


@bot.message_handler(func=lambda message: current_flow_step(message.from_user.id, message.chat.id) == SearchStates.price_max, content_types=["text"])
def handle_search_price_max(message):
    value, error = parse_optional_price(message.text)
    if error:
        bot.reply_to(message, error)
        return
    with draft_data(message.from_user.id, message.chat.id) as data:
        price_min = data.get("s_price_min")
        if price_min is not None and value is not None and value < price_min:
            bot.reply_to(message, "Maksimal narx minimal narxdan kichik bo'lmasligi kerak.")
            return
        data["s_price_max"] = value
        data["s_amenities"] = []
        data["flow_step"] = SearchStates.amenities
    bot.send_message(
        message.chat.id,
        "Qanday qulayliklar muhim? Bir nechtasini tanlashingiz mumkin.",
        reply_markup=amenities_markup("samenity"),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("samenity_"))
def handle_search_amenities(call):
    value = call.data.split("_", 1)[1]
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        if value == "done":
            bot.answer_callback_query(call.id)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🏙 Butun Toshkent", callback_data="sloc_all"),
                types.InlineKeyboardButton("📍 Aniq tumanni tanlash", callback_data="sloc_district"),
            )
            bot.edit_message_text("Qulayliklar saqlandi.", call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "Qayerdan qidiramiz?", reply_markup=markup)
            data["flow_step"] = SearchStates.location_choice
            return
        if value not in AMENITY_LABELS:
            bot.answer_callback_query(call.id, "Noto'g'ri tanlov")
            return
        amenities = data.setdefault("s_amenities", [])
        if value in amenities:
            amenities.remove(value)
            bot.answer_callback_query(call.id, f"O'chirildi: {AMENITY_LABELS[value]}")
        else:
            amenities.append(value)
            bot.answer_callback_query(call.id, f"Qo'shildi: {AMENITY_LABELS[value]}")


@bot.callback_query_handler(func=lambda call: call.data in {"sloc_all", "sloc_district"})
def handle_search_location_choice(call):
    bot.answer_callback_query(call.id)
    if call.data == "sloc_all":
        with draft_data(call.from_user.id, call.message.chat.id) as data:
            data["s_district"] = None
            data["flow_step"] = "search_results"
        bot.edit_message_text("Butun Toshkent bo'yicha qidirilmoqda...", call.message.chat.id, call.message.message_id)
        run_search_and_reply(call.from_user.id, call.message.chat.id)
        return
    bot.edit_message_text("Tumanni tanlang:", call.message.chat.id, call.message.message_id, reply_markup=districts_markup("sdist"))
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data["flow_step"] = SearchStates.district


@bot.callback_query_handler(func=lambda call: call.data.startswith("sdist_"))
def handle_search_district(call):
    district = call.data.split("_", 1)[1]
    with draft_data(call.from_user.id, call.message.chat.id) as data:
        data["s_district"] = district
        data["flow_step"] = "search_results"
    bot.answer_callback_query(call.id)
    bot.edit_message_text(f"Tuman: {district}. Qidirilmoqda...", call.message.chat.id, call.message.message_id)
    run_search_and_reply(call.from_user.id, call.message.chat.id)


def run_search_and_reply(user_id, chat_id):
    with draft_data(user_id, chat_id) as data:
        seeker_gender = data.get("s_gender")
        desired_gender = data.get("s_preferred_gender")
        price_min = data.get("s_price_min")
        price_max = data.get("s_price_max")
        amenities = data.get("s_amenities", [])
        district = data.get("s_district")

    query = "SELECT * FROM listings WHERE status = 'active' AND listing_type = 'offer'"
    params = []
    if desired_gender and desired_gender != "any":
        query += " AND (author_gender = ? OR author_gender IS NULL)"
        params.append(desired_gender)
    if seeker_gender:
        query += " AND (preferred_gender = ? OR preferred_gender = 'any' OR preferred_gender IS NULL)"
        params.append(seeker_gender)
    if price_min is not None:
        query += " AND price_per_person >= ?"
        params.append(price_min)
    if price_max is not None:
        query += " AND price_per_person <= ?"
        params.append(price_max)
    if district:
        query += " AND district = ?"
        params.append(district)
    for amenity in amenities:
        column = AMENITY_COLUMNS.get(amenity)
        if column:
            query += f" AND {column} = 1"
    query += " ORDER BY created_at DESC LIMIT 30"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    results = cursor.execute(query, params).fetchall()
    conn.close()

    if not results:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🗺 Xaritada ko'rish", url=f"{SITE_URL}/xarita?listing_type=offer"))
        bot.send_message(chat_id, "Hozircha mos e'lon topilmadi. Filtrlarni o'zgartirib ko'ring yoki xaritani oching.", reply_markup=markup)
        clear_draft(user_id, chat_id)
        return

    if len(results) > MAX_INLINE_RESULTS:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🗺 Xaritada ko'rish", url=f"{SITE_URL}/xarita?listing_type=offer"))
        bot.send_message(chat_id, f"{len(results)} ta e'lon topildi. Xaritada ko'rish qulayroq:", reply_markup=markup)
        clear_draft(user_id, chat_id)
        return

    bot.send_message(chat_id, f"{len(results)} ta mos e'lon topildi:")
    for row in results:
        text = (
            f"💰 {format_price(row['price_per_person'])} so'm/kishi\n"
            f"📍 {row['district'] or '-'}, {row['university'] or '-'}\n"
            f"🏠 {row['housing_type'] or '-'}, {row['room_count'] or '-'} xona\n"
            f"🤝 Xonadosh: {gender_label(row['preferred_gender'])}\n"
            f"📝 {row['description'] or '-'}"
        )
        if row["phone_number"]:
            text += f"\n☎️ Tel: {row['phone_number']}"
        markup = types.InlineKeyboardMarkup(row_width=1)
        username = (row["telegram_username"] or "").lstrip("@")
        if username:
            markup.add(types.InlineKeyboardButton("💬 Telegram orqali yozish", url=f"https://t.me/{username}"))
        bot.send_message(chat_id, text, reply_markup=markup)

    clear_draft(user_id, chat_id)


@bot.message_handler(commands=["my"])
def my_listings(message):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM listings WHERE telegram_user_id = ? AND status IN ('active', 'hidden_pending_review')",
            (message.from_user.id,),
        )
        listings = cursor.fetchall()
        conn.close()

        if not listings:
            bot.reply_to(message, "Sizda faol e'lon yo'q.")
            return

        for listing in listings:
            text = (
                f"ID: {listing['id']}\n"
                f"Narx: {format_price(listing['price_per_person'])} so'm\n"
                f"Status: {listing['status']}"
            )
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("O'chirish", callback_data=f"del_{listing['id']}"),
                types.InlineKeyboardButton("7 kunga uzaytirish", callback_data=f"ext_{listing['id']}"),
            )
            bot.send_message(message.chat.id, text, reply_markup=markup)
    except Exception:
        print(f"ERROR in my_listings: {traceback.format_exc()}")
        bot.reply_to(message, "E'lonlarni olishda xatolik yuz berdi.")


@bot.callback_query_handler(func=lambda call: call.data.startswith(("del_", "ext_")))
def handle_manage_listing(call):
    action, listing_id_str = call.data.split("_", 1)
    listing_id = int(listing_id_str)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_user_id FROM listings WHERE id = ?", (listing_id,))
    row = cursor.fetchone()

    if not row or row[0] != call.from_user.id:
        bot.answer_callback_query(call.id, "Bu sizning e'loningiz emas.")
        conn.close()
        return

    if action == "del":
        conn.execute("UPDATE listings SET status = 'removed' WHERE id = ?", (listing_id,))
        bot.answer_callback_query(call.id, "O'chirildi.")
    elif action == "ext":
        conn.execute("UPDATE listings SET expires_at = datetime('now', '+7 days') WHERE id = ?", (listing_id,))
        bot.answer_callback_query(call.id, "Uzaytirildi.")
    conn.commit()
    conn.close()
    bot.edit_message_text("Yangilandi.", chat_id=call.message.chat.id, message_id=call.message.message_id)


def current_flow_step(user_id, chat_id):
    with draft_data(user_id, chat_id) as data:
        return data.get("flow_step")


@bot.message_handler(content_types=["photo"])
def route_photo_by_flow_step(message):
    if current_flow_step(message.from_user.id, message.chat.id) == "photos":
        handle_photos(message)


@bot.message_handler(content_types=["document"])
def route_document_by_flow_step(message):
    if current_flow_step(message.from_user.id, message.chat.id) == "photos":
        bot.reply_to(message, "Iltimos, rasmni fayl emas, Telegram photo sifatida yuboring yoki /done yozing.")


@bot.message_handler(content_types=["text"])
def route_text_by_flow_step(message):
    text = (message.text or "").strip()
    if text.startswith("/") and text.lower() not in {"/skip", "/done"}:
        return

    step = current_flow_step(message.from_user.id, message.chat.id)
    if step == "location":
        bot.reply_to(message, "Iltimos, Telegram lokatsiya tugmasi orqali joylashuvni yuboring.")
        return
    if step in {"university", "housing_type", "roommates_needed", "preferred_gender", "amenities", "phone_visibility", "confirm"}:
        bot.reply_to(message, "Iltimos, yuqoridagi tugmalardan birini tanlang.")
        return
    if step in {"search_gender_author", "search_preferred_gender", "search_amenities", "search_location_choice", "search_district"}:
        bot.reply_to(message, "Iltimos, qidiruvni davom ettirish uchun tugmalardan birini tanlang.")
        return
    if step == "room_count":
        if text.isdigit():
            handle_room_count(message)
        else:
            handle_room_count_invalid(message)
        return
    if step == "price":
        if text.isdigit():
            handle_price(message)
        else:
            handle_price_invalid(message)
        return
    if step == "description":
        handle_description(message)
        return
    if step == "phone":
        handle_phone(message)
        return
    if step == "photos":
        if text.lower() == "/done":
            confirm_listing(message)
        else:
            bot.reply_to(message, "Rasm yuboring yoki tugatish uchun /done yozing.")
        return
    if step == "search_price_min":
        handle_search_price_min(message)
        return
    if step == "search_price_max":
        handle_search_price_max(message)


print("Bot started...")
bot.infinity_polling()
