import os
import random
import sqlite3
import telebot
import requests
import io
from PIL import Image
from telebot import custom_filters, types
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "backend", "database.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

storage = StateMemoryStorage()
bot = telebot.TeleBot(TOKEN, state_storage=storage)

class AddListingStates(StatesGroup):
    location = State()
    price = State()
    roommates_needed = State()
    amenities = State()
    photos = State()
    confirm = State()

import math
import random

def blur_location(lat, lng):
    # Расстояние: 150-200 метров (в градусах lat/lng 1 градус ~ 111 км, 1 м ~ 0.000009 градусов)
    # 150 метров = 0.00135 градусов, 200 метров = 0.0018 градусов
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

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Welcome! Use /add to create a listing or /my to view your listings.")

@bot.message_handler(commands=['add'])
def start_add_flow(message):
    if is_banned(message.from_user.id):
        bot.reply_to(message, "You are banned from adding listings.")
        return
    bot.set_state(message.from_user.id, AddListingStates.location, message.chat.id)
    bot.reply_to(message, "Please send your location.")

@bot.message_handler(state=AddListingStates.location, content_types=['location'])
def handle_location(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['lat'], data['lng'] = blur_location(message.location.latitude, message.location.longitude)
    bot.send_message(message.chat.id, "Price per person (UZS):")
    bot.set_state(message.from_user.id, AddListingStates.price, message.chat.id)

@bot.message_handler(state=AddListingStates.price, is_digit=True)
def handle_price(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['price'] = int(message.text)
    bot.send_message(message.chat.id, "Roommates needed? (1, 2, or 3+)")
    bot.set_state(message.from_user.id, AddListingStates.roommates_needed, message.chat.id)

@bot.message_handler(state=AddListingStates.roommates_needed)
def handle_roommates(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        data['needed'] = message.text
        data['amenities'] = []
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    options = ["Wi-Fi", "AC", "Washer", "No Landlord", "Metro"]
    for opt in options:
        markup.add(types.InlineKeyboardButton(opt, callback_data=opt))
    markup.add(types.InlineKeyboardButton("Done", callback_data="done"))
    bot.send_message(message.chat.id, "Select amenities:", reply_markup=markup)
    bot.set_state(message.from_user.id, AddListingStates.amenities, message.chat.id)

@bot.callback_query_handler(state=AddListingStates.amenities, func=lambda call: True)
def handle_amenities(call):
    with bot.retrieve_data(call.from_user.id, call.message.chat.id) as data:
        if call.data == "done":
            data['photos'] = []
            bot.send_message(call.message.chat.id, "Amenities saved. Send up to 5 photos. Type /done when finished.")
            bot.set_state(call.from_user.id, AddListingStates.photos, call.message.chat.id)
        else:
            if call.data not in data['amenities']:
                data['amenities'].append(call.data)
                bot.answer_callback_query(call.id, f"Added {call.data}")

@bot.message_handler(state=AddListingStates.photos, content_types=['photo'])
def handle_photos(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        if len(data['photos']) < 5:
            file_id = message.photo[-1].file_id
            data['photos'].append(file_id)
            bot.reply_to(message, f"Photo {len(data['photos'])}/5 added.")
        else:
            bot.reply_to(message, "Limit of 5 photos reached. Type /done.")

@bot.message_handler(state=AddListingStates.photos, commands=['done'])
def save_listing(message):
    with bot.retrieve_data(message.from_user.id, message.chat.id) as data:
        # Подготовка удобств
        amenities = data.get('amenities', [])
        has_wifi = 1 if "Wi-Fi" in amenities else 0
        has_ac = 1 if "AC" in amenities else 0
        has_washing_machine = 1 if "Washer" in amenities else 0
        no_landlord_in_yard = 1 if "No Landlord" in amenities else 0
        near_metro = 1 if "Metro" in amenities else 0

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO listings (telegram_user_id, telegram_username, lat, lng, price_per_person, people_needed, 
                                  has_wifi, has_ac, has_washing_machine, no_landlord_in_yard, near_metro, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '+7 days'))
        """, (message.from_user.id, message.from_user.username or "none", data['lat'], data['lng'], 
              data['price'], data['needed'], has_wifi, has_ac, has_washing_machine, no_landlord_in_yard, near_metro))
        listing_id = cursor.lastrowid
        
        os.makedirs(f"{UPLOAD_DIR}/{listing_id}", exist_ok=True)
        for i, file_id in enumerate(data['photos']):
            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            img = Image.open(io.BytesIO(downloaded_file))
            if img.width > 1200:
                ratio = 1200 / float(img.width)
                height = int(float(img.height) * float(ratio))
                img = img.resize((1200, height), Image.Resampling.LANCZOS)
            file_path = f"{UPLOAD_DIR}/{listing_id}/{i}.jpg"
            img.save(file_path, 'JPEG', quality=80)
            cursor.execute("INSERT INTO listing_photos (listing_id, file_path) VALUES (?, ?)", (listing_id, file_path))
        
        conn.commit()
        conn.close()
    
    bot.reply_to(message, "Listing created successfully!")
    print("Bot started...")
bot.infinity_polling()

@bot.message_handler(commands=['my'])
def my_listings(message):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    listings = cursor.execute("SELECT * FROM listings WHERE telegram_user_id = ? AND status != 'expired'", (message.from_user.id,)).fetchall()
    conn.close()

    if not listings:
        bot.reply_to(message, "You don't have any active listings.")
        return

    for listing in listings:
        text = f"Listing ID: {listing['id']}\nPrice: {listing['price_per_person']}\nStatus: {listing['status']}"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Delete", callback_data=f"del_{listing['id']}"))
        markup.add(types.InlineKeyboardButton("Extend 7 days", callback_data=f"ext_{listing['id']}"))
        bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('del_', 'ext_')))
def handle_manage_listing(call):
    action, listing_id = call.data.split('_')
    conn = sqlite3.connect(DB_PATH)
    if action == 'del':
        conn.execute("UPDATE listings SET status = 'deleted' WHERE id = ?", (listing_id,))
        bot.answer_callback_query(call.id, "Deleted.")
    elif action == 'ext':
        conn.execute("UPDATE listings SET expires_at = datetime('now', '+7 days') WHERE id = ?", (listing_id,))
        bot.answer_callback_query(call.id, "Extended.")
    conn.commit()
    conn.close()
    bot.edit_message_text("Updated.", chat_id=call.message.chat.id, message_id=call.message.message_id)
