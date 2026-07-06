import os
import sqlite3
import telebot
import io
import traceback
import math
import random
from PIL import Image
from telebot import types
from telebot.handler_backends import State, StatesGroup
from telebot.custom_filters import StateFilter, IsDigitFilter
from telebot.storage import StatePickleStorage
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "backend", "database.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

state_storage = StatePickleStorage(file_path=os.path.join(BASE_DIR, "state_storage.pkl"))
bot = telebot.TeleBot(TOKEN, state_storage=state_storage, use_class_middlewares=True)

bot.add_custom_filter(StateFilter(bot))
bot.add_custom_filter(IsDigitFilter())

class AddListingStates(StatesGroup):
    listing_type = State()
    location = State()
    university = State()
    district = State()
    housing_type = State()
    room_count = State()
    price = State()
    roommates_needed = State()
    amenities = State()
    description = State()
    phone = State()
    photos = State()
    confirm = State()

def blur_location(lat, lng):
    # Offset the exact point by roughly 150-200 meters for privacy.
    radius = random.uniform(0.00135, 0.0018)
    angle = random.uniform(0, 2 * math.pi)
    
    lat_offset = radius * math.cos(angle)
    lng_offset = radius * math.sin(angle)
    
    return lat + lat_offset, lng + lng_offset

def is_banned(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM banned_users WHERE telegram_user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

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

DISTRICTS = ["Mirzo-Ulug'bek", "Yunusobod", "Mirobod", "Chilonzor", "Yakkasaroy", "Shayxontohur", "Uchtepa", "Sergeli", "Yashnobod", "Bektemir", "Olmazor"]

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Salom! Klapa.net botiga xush kelibsiz.\n\nE'lon qo'shish uchun /add yoki e'lonlaringizni ko'rish uchun /my buyrug'ini tanlang.\n\nQoidalar:\n- Faqat xonadosh qidirish (butun kvartira emas);\n- Maklerlar taqiqlanadi;\n- E'lon 7 kundan keyin avtomatik o'chiriladi.")

@bot.message_handler(commands=['add'])
def start_add_flow(message):
    if is_banned(message.from_user.id):
        bot.reply_to(message, "Sizga e'lon qo'shish taqiqlangan.")
        return
    if has_active_listing(message.from_user.id):
        bot.reply_to(message, "Sizda allaqachon faol e'lon bor. Yangisini qo'shishdan oldin uni /my orqali o'chiring yoki tugating.")
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Uyim bor, xonadosh qidiryapman", callback_data="type_offer"),
        types.InlineKeyboardButton("Turar joy qidiryapman", callback_data="type_seek")
    )
    bot.reply_to(message, "Siz e'lon beryapsizmi yoki qidiryapsizmi?", reply_markup=markup)
    bot.set_state(message.from_user.id, AddListingStates.listing_type, message.chat.id)

@bot.callback_query_handler(state=AddListingStates.listing_type, func=lambda call: call.data.startswith("type_"))
def handle_listing_type(call):
    listing_type = call.data.split("_")[1] # "offer" or "seek"
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        data['listing_type'] = listing_type
    bot.edit_message_text("Tanlandi.", call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, "Iltimos, lokatsiyangizni yuboring.")
    bot.set_state(call.from_user.id, AddListingStates.location, call.message.chat.id)

import traceback
@bot.message_handler(state=AddListingStates.location, content_types=['location'])
def handle_location(message):
    try:
        print(f"DEBUG: Received location from {message.from_user.id}")
        with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
            data['lat'], data['lng'] = blur_location(message.location.latitude, message.location.longitude)
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        universities = ["TATU", "WIUT", "INHA", "O'zMU", "TMI", "TDIU", "TSUULL", "TTA", "Other"]
        for uni in universities:
            markup.add(types.InlineKeyboardButton(uni, callback_data=f"uni_{uni}"))
        
        bot.send_message(message.chat.id, "Select your university:", reply_markup=markup)
        bot.set_state(message.from_user.id, AddListingStates.university, message.chat.id)
    except Exception as e:
        print(f"ERROR in handle_location: {traceback.format_exc()}")
        bot.reply_to(message, "An error occurred. Please try again later.")

@bot.callback_query_handler(state=AddListingStates.university, func=lambda call: call.data.startswith("uni_"))
def handle_university(call):
    uni = call.data.split("_")[1]
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        data['university'] = uni
    bot.edit_message_text(f"University saved: {uni}", call.message.chat.id, call.message.message_id)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    for dist in DISTRICTS:
        markup.add(types.InlineKeyboardButton(dist, callback_data=f"dist_{dist}"))
    bot.send_message(call.message.chat.id, "Iltimos, tumanni tanlang:", reply_markup=markup)
    bot.set_state(call.from_user.id, AddListingStates.district, call.message.chat.id)

@bot.callback_query_handler(state=AddListingStates.district, func=lambda call: call.data.startswith("dist_"))
def handle_district(call):
    district = call.data.split("_", 1)[1]
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        data['district'] = district
        listing_type = data.get('listing_type')
        
    bot.edit_message_text(f"Tuman: {district}", call.message.chat.id, call.message.message_id)
    
    if listing_type == 'offer':
        markup = types.InlineKeyboardMarkup(row_width=2)
        options = ["Kvartira", "Xonadonli uy", "Yotoqxona", "Boshqa"]
        for opt in options:
            markup.add(types.InlineKeyboardButton(opt, callback_data=f"house_{opt}"))
        bot.send_message(call.message.chat.id, "Uy turini tanlang:", reply_markup=markup)
        bot.set_state(call.from_user.id, AddListingStates.housing_type, call.message.chat.id)
    else:
        bot.send_message(call.message.chat.id, "Price per person (UZS):")
        bot.set_state(call.from_user.id, AddListingStates.price, call.message.chat.id)

# 3.4. Update Roommates section to inline buttons
@bot.message_handler(state=AddListingStates.price, is_digit=True)
def handle_price(message):
    price = int(message.text)
    if price < 100000 or price > 20000000:
        bot.reply_to(message, "Narx 100 000 dan 20 000 000 so'mgacha bo'lishi kerak.")
        return
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['price'] = price
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("1", callback_data="room_1"),
        types.InlineKeyboardButton("2", callback_data="room_2"),
        types.InlineKeyboardButton("3+", callback_data="room_3")
    )
    bot.send_message(message.chat.id, "Nechta xonadosh kerak?", reply_markup=markup)
    bot.set_state(message.from_user.id, AddListingStates.roommates_needed, message.chat.id)

@bot.callback_query_handler(state=AddListingStates.roommates_needed, func=lambda call: call.data.startswith("room_"))
def handle_roommates(call):
    needed = call.data.split("_")[1]
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        data['needed'] = needed
        data['amenities'] = []
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    options = ["Wi-Fi", "AC", "Washer", "No Landlord", "Metro"]
    for opt in options:
        markup.add(types.InlineKeyboardButton(opt, callback_data=opt))
    markup.add(types.InlineKeyboardButton("Done", callback_data="done"))
    bot.edit_message_text("Qulayliklarni tanlang:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.set_state(call.from_user.id, AddListingStates.amenities, call.message.chat.id)

@bot.callback_query_handler(state=AddListingStates.housing_type, func=lambda call: call.data.startswith("house_"))
def handle_housing_type(call):
    h_type = call.data.split("_", 1)[1]
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        data['housing_type'] = h_type
    bot.edit_message_text(f"Uy turi: {h_type}", call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, "Nechta xona?")
    bot.set_state(call.from_user.id, AddListingStates.room_count, call.message.chat.id)

@bot.message_handler(state=AddListingStates.room_count, is_digit=True)
def handle_room_count(message):
    room_count = int(message.text)
    if room_count < 1 or room_count > 10:
        bot.reply_to(message, "Xona soni 1 dan 10 gacha bo'lishi kerak.")
        return
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['room_count'] = room_count
    bot.send_message(message.chat.id, "Price per person (UZS):")
    bot.set_state(message.from_user.id, AddListingStates.price, message.chat.id)

@bot.callback_query_handler(state=AddListingStates.amenities, func=lambda call: True)
def handle_amenities(call):
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        if call.data == "done":
            bot.edit_message_text("Qulayliklar saqlandi.", call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "Qisqacha tavsif yozing (yoki /skip):")
            bot.set_state(call.from_user.id, AddListingStates.description, call.message.chat.id)
            return

        amenities = data.setdefault('amenities', [])
        if call.data in amenities:
            amenities.remove(call.data)
            bot.answer_callback_query(call.id, f"Removed {call.data}")
        else:
            amenities.append(call.data)
            bot.answer_callback_query(call.id, f"Added {call.data}")

@bot.message_handler(state=AddListingStates.description, content_types=['text'])
def handle_description(message):
    text = (message.text or "").strip()
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['description'] = None if text.lower() == "/skip" else text[:1000]
    bot.send_message(message.chat.id, "Telefon raqamingizni yuboring (ixtiyoriy, /skip mumkin):")
    bot.set_state(message.from_user.id, AddListingStates.phone, message.chat.id)

@bot.message_handler(state=AddListingStates.phone, content_types=['text'])
def handle_phone(message):
    text = (message.text or "").strip()
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['phone'] = None if text.lower() == "/skip" else text[:40]
        data['photos'] = []
    bot.send_message(message.chat.id, "Rasmlarni yuboring (5 tagacha). Tugatgach /done yozing.")
    bot.set_state(message.from_user.id, AddListingStates.photos, message.chat.id)

@bot.message_handler(state=AddListingStates.photos, content_types=['photo'])
def handle_photos(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        if len(data['photos']) < 5:
            file_id = message.photo[-1].file_id
            data['photos'].append(file_id)
            bot.reply_to(message, f"Photo {len(data['photos'])}/5 added. Type /done when finished.")
        else:
            bot.reply_to(message, "Limit of 5 photos reached. Type /done.")

@bot.message_handler(state=AddListingStates.photos, content_types=['text'], func=lambda message: (message.text or "").strip().lower() == "/done")
def confirm_listing(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        summary = (
            f"Summary:\n"
            f"Type: {data.get('listing_type')}\n"
            f"University: {data.get('university')}\n"
            f"District: {data.get('district')}\n"
            f"Housing type: {data.get('housing_type') or 'N/A'}\n"
            f"Rooms: {data.get('room_count') or 'N/A'}\n"
            f"Price: {data.get('price')} UZS\n"
            f"Roommates needed: {data.get('needed')}\n"
            f"Description: {data.get('description') or 'None'}\n"
            f"Phone: {data.get('phone') or 'None'}\n"
            f"Amenities: {', '.join(data.get('amenities', []))}\n"
            f"Photos: {len(data.get('photos', []))}"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Joylashtirish", callback_data="confirm_yes"))
        markup.add(types.InlineKeyboardButton("Bekor qilish", callback_data="confirm_no"))
        bot.send_message(message.chat.id, summary, reply_markup=markup)
        bot.set_state(message.from_user.id, AddListingStates.confirm, message.chat.id)

@bot.callback_query_handler(state=AddListingStates.confirm, func=lambda call: call.data.startswith("confirm_"))
def handle_confirm(call):
    if call.data == "confirm_yes":
        save_listing_to_db(call.from_user.id, call.message.chat.id, call.from_user.username)
        bot.edit_message_text("Listing created successfully!", call.message.chat.id, call.message.message_id)
        bot.delete_state(call.from_user.id, call.message.chat.id)
    else:
        bot.edit_message_text("Listing creation cancelled.", call.message.chat.id, call.message.message_id)
        bot.delete_state(call.from_user.id, call.message.chat.id)

def save_listing_to_db(user_id, chat_id, username=None):
    with bot.retrieve_data(user_id, chat_id) as data:
        amenities = data.get('amenities', [])
        has_wifi = 1 if "Wi-Fi" in amenities else 0
        has_ac = 1 if "AC" in amenities else 0
        has_washing_machine = 1 if "Washer" in amenities else 0
        no_landlord_in_yard = 1 if "No Landlord" in amenities else 0
        near_metro = 1 if "Metro" in amenities else 0

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        needed_val = data.get('needed')
        needed_int = 3 if needed_val == '3' else int(needed_val)
        
        cursor.execute("""
            INSERT INTO listings (telegram_user_id, telegram_username, listing_type, university, district, housing_type, description, phone_number, room_count, lat, lng, price_per_person, people_needed, 
                                  has_wifi, has_ac, has_washing_machine, no_landlord_in_yard, near_metro, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '+7 days'))
        """, (user_id, username or "", data.get('listing_type'), data.get('university'), data.get('district'), data.get('housing_type'),
              data.get('description'), data.get('phone'), data.get('room_count'), data['lat'], data['lng'], 
              data['price'], needed_int, has_wifi, has_ac, has_washing_machine, no_landlord_in_yard, near_metro))
        listing_id = cursor.lastrowid
        photo_column = get_listing_photo_column(cursor)
        
        os.makedirs(f"{UPLOAD_DIR}/{listing_id}", exist_ok=True)
        for i, file_id in enumerate(data.get('photos', [])):
            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            img = Image.open(io.BytesIO(downloaded_file))
            if img.width > 1200:
                ratio = 1200 / float(img.width)
                height = int(float(img.height) * float(ratio))
                img = img.resize((1200, height), Image.Resampling.LANCZOS)
            file_path = f"{UPLOAD_DIR}/{listing_id}/{i}.jpg"
            img.save(file_path, 'JPEG', quality=80)
            cursor.execute(f"INSERT INTO listing_photos (listing_id, {photo_column}) VALUES (?, ?)", (listing_id, file_path))
        
        conn.commit()
        conn.close()

@bot.message_handler(commands=['my'])
def my_listings(message):
    try:
        print(f"DEBUG: Fetching listings for {message.from_user.id}")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM listings WHERE telegram_user_id = ? AND status IN ('active', 'hidden_pending_review')",
            (message.from_user.id,),
        )
        listings = cursor.fetchall()
        conn.close()
        print(f"DEBUG: Found {len(listings)} listings.")
        
        if not listings:
            bot.reply_to(message, "You don't have any active listings.")
            return

        for listing in listings:
            text = f"Listing ID: {listing['id']}\nPrice: {listing['price_per_person']}\nStatus: {listing['status']}"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Delete", callback_data=f"del_{listing['id']}"))
            markup.add(types.InlineKeyboardButton("Extend 7 days", callback_data=f"ext_{listing['id']}"))
            bot.send_message(message.chat.id, text, reply_markup=markup)
    except Exception as e:
        print(f"ERROR in my_listings: {traceback.format_exc()}")
        bot.reply_to(message, "An error occurred fetching your listings.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(('del_', 'ext_')))
def handle_manage_listing(call):
    action, listing_id_str = call.data.split('_')
    listing_id = int(listing_id_str)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_user_id FROM listings WHERE id = ?", (listing_id,))
    row = cursor.fetchone()
    
    if not row or row[0] != call.from_user.id:
        bot.answer_callback_query(call.id, "Bu sizning e'loningiz emas.")
        conn.close()
        return

    if action == 'del':
        conn.execute("UPDATE listings SET status = 'removed' WHERE id = ?", (listing_id,))
        bot.answer_callback_query(call.id, "Removed.")
    elif action == 'ext':
        conn.execute("UPDATE listings SET expires_at = datetime('now', '+7 days') WHERE id = ?", (listing_id,))
        bot.answer_callback_query(call.id, "Extended.")
    conn.commit()
    conn.close()
    bot.edit_message_text("Updated.", chat_id=call.message.chat.id, message_id=call.message.message_id)

print("Bot started...")
bot.infinity_polling()
