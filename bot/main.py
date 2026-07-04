import os
import random
import sqlite3
import telebot
import requests
from telebot import custom_filters, types
from telebot.handler_backends import State, StatesGroup
from telebot.storage import StateMemoryStorage
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = "D:/Projects/sigamiz/backend/database.db"
UPLOAD_DIR = "D:/Projects/sigamiz/uploads"

storage = StateMemoryStorage()
bot = telebot.TeleBot(TOKEN, state_storage=storage)

class AddListingStates(StatesGroup):
    location = State()
    price = State()
    roommates_needed = State()
    amenities = State()
    photos = State()
    confirm = State()

def blur_location(lat, lng):
    offset = random.uniform(0.0015, 0.002)
    return lat + offset, lng + offset

@bot.message_handler(commands=['add'])
def start_add_flow(message):
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
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO listings (telegram_user_id, telegram_username, lat, lng, price_per_person, people_needed, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now', '+7 days'))
        """, (message.from_user.id, message.from_user.username or "none", data['lat'], data['lng'], data['price'], data['needed']))
        listing_id = cursor.lastrowid
        
        os.makedirs(f"{UPLOAD_DIR}/{listing_id}", exist_ok=True)
        for i, file_id in enumerate(data['photos']):
            file_info = bot.get_file(file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            file_path = f"{UPLOAD_DIR}/{listing_id}/{i}.jpg"
            with open(file_path, 'wb') as new_file:
                new_file.write(downloaded_file)
            cursor.execute("INSERT INTO listing_photos (listing_id, file_path) VALUES (?, ?)", (listing_id, file_path))
        
        conn.commit()
        conn.close()
    
    bot.reply_to(message, "Listing created successfully!")
    bot.delete_state(message.from_user.id, message.chat.id)

if __name__ == "__main__":
    bot.add_custom_filter(custom_filters.StateFilter(bot))
    bot.infinity_polling()
