"""Prepare and compile the bot changes without applying them to bot/main.py."""
import ast
from pathlib import Path
from audit.edit_source import ROOT,replace_function,save

s=(ROOT/'bot/main.py').read_text(encoding='utf-8')
s=s.replace('from backend.listing_service import ListingServiceError, create_offer_listing','''from backend.listing_service import ListingServiceError, create_offer_listing
from backend.migrations import init_db
from backend.security import upsert_user, approve_challenge
from backend.search import search_clause, bot_filters, save_preferences as store_preferences
from backend.lifecycle import manage_listing, review_listing as moderate_listing, expire_listings, effective_status
from backend.notifications import start_worker
from backend.storage import UPLOAD_DIR as SHARED_UPLOAD_DIR, delete_photo, validate_storage
from backend.drafts import draft_data, clear_draft
from backend.catalogs import DISTRICTS, DISTRICT_CENTERS, DISTRICT_ALIASES, UNIVERSITIES, HOUSING_TYPES, AMENITIES, STATUS_LABELS
UPLOAD_DIR = SHARED_UPLOAD_DIR''')
s=s.replace('telebot.TeleBot(TOKEN,','telebot.TeleBot(TOKEN or "0:disabled",')
for name in ('session_key','load_sessions_unlocked','save_sessions_unlocked','draft_data','clear_draft','blur_location','ensure_web_login_tokens_table','confirm_web_login_token','ensure_search_preferences_table','listing_matches_preferences','notify_matching_search_preferences','send_admin_notification','ensure_listing_photo_hashes_table','average_image_hash','hash_distance','find_similar_photo'):
    s=replace_function(s,name,'')
catalog_names={'DISTRICTS','DISTRICT_CENTERS','DISTRICT_ALIASES','UNIVERSITIES','HOUSING_TYPES','AMENITIES'}
lines=s.splitlines()
for node in sorted([n for n in ast.parse(s).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in catalog_names for t in n.targets)],key=lambda n:n.lineno,reverse=True):
    del lines[node.lineno-1:node.end_lineno]
s='\n'.join(lines)+'\n'
s=replace_function(s,'mark_bot_started','''def mark_bot_started(user):
    conn=get_db()
    try:
        upsert_user(conn.cursor(),user.id,user.username,user.first_name,user.last_name,bot_started=True)
        conn.commit()
    finally:
        conn.close()
''')
s=replace_function(s,'save_search_preferences','''def save_search_preferences(user_id,data):
    conn=get_db()
    try:
        store_preferences(conn.cursor(),user_id,bot_filters(data))
        conn.commit()
    finally:
        conn.close()
''')
s=replace_function(s,'has_active_listing','''def has_active_listing(user_id):
    conn=get_db()
    try:
        return conn.execute("SELECT 1 FROM listings WHERE telegram_user_id=? AND (status='hidden_pending_review' OR (status='active' AND datetime(expires_at)>datetime('now')))",(user_id,)).fetchone() is not None
    finally:
        conn.close()
''')
s=replace_function(s,'send_welcome','''@bot.message_handler(commands=['start'])
def send_welcome(message):
    mark_bot_started(message.from_user)
    parts=(message.text or '').split(maxsplit=1)
    payload=parts[1].strip() if len(parts)>1 else ''
    if payload.startswith('web_'):
        with draft_data(message.from_user.id,message.chat.id) as data:
            data['web_login_token']=payload[4:]
            data['web_login_previous_step']=data.get('flow_step')
            data['flow_step']='web_login'
        bot.reply_to(message,f"{SITE_URL} saytiga kirishni tasdiqlash uchun SAYTDA ko'rsatilgan 6 raqamli kodni yuboring. Faqat o'zingiz kirishni boshlagan bo'lsangiz tasdiqlang. Boshqa odam yuborgan havolani tasdiqlamang. /cancel — bekor qilish.")
        return
    bot.reply_to(message,'Sigamiz: e’lon joylashtiring yoki uy qidiring.',reply_markup=main_menu_markup())
''')
s=replace_function(s,'review_listing','''@bot.message_handler(commands=['review'])
def review_listing(message):
    if not is_admin_chat(message):
        bot.reply_to(message,'Bu buyruq faqat admin chat uchun.');return
    parts=(message.text or '').split()
    if len(parts)!=3 or not parts[1].isdigit() or parts[2] not in ('approve','ban'):
        bot.reply_to(message,'Format: /review <id> approve|ban');return
    conn=get_db()
    try:
        status=moderate_listing(conn.cursor(),int(parts[1]),parts[2])
        conn.commit()
        bot.reply_to(message,f'E’lon {parts[1]}: {status}')
    except ListingServiceError as exc:
        conn.rollback();bot.reply_to(message,exc.message)
    except Exception as exc:
        conn.rollback()
        if getattr(exc,'pgcode',None)=='23505' or 'UNIQUE constraint' in str(exc):
            bot.reply_to(message,'Muallifda boshqa faol e’lon bor.')
        else:
            traceback.print_exc();bot.reply_to(message,'Saqlab bo‘lmadi. Qayta urinib ko‘ring.')
    finally:
        conn.close()
''')
s=s.replace('data["lat"], data["lng"] = blur_location(message.location.latitude, message.location.longitude)','data["lat"], data["lng"] = message.location.latitude, message.location.longitude')
s=s.replace('    if call.data == "phone_no":','''    if call.data == "phone_no":
        if not call.from_user.username:
            bot.send_message(call.message.chat.id,"Telegram username yo'q. Telefon ko'rsatishni tanlang yoki Telegram sozlamalarida username qo'shing.")
            return''')
s=replace_function(s,'save_listing_to_db','''def save_listing_to_db(user_id,chat_id,username=None):
    with draft_data(user_id,chat_id) as data:
        if missing_listing_fields(data):
            raise ListingServiceError('E’lon ma’lumotlari to‘liq emas.')
        photos=[]
        for file_id in data.get('photos',[]):
            info=bot.get_file(file_id)
            if info.file_size and info.file_size>5*1024*1024:
                raise ListingServiceError('Rasm 5 MB dan katta',413)
            photos.append(bot.download_file(info.file_path))
        payload={key:data.get(key) for key in ('university','district','housing_type','description','room_count','author_gender','preferred_gender','lat','lng','price')}
        payload.update(phone_number=data.get('phone'),people_needed=data.get('needed'),**{column:key in data.get('amenities',[]) for key,_,column in AMENITIES})
        conn=get_db();created=None;committed=False
        try:
            cursor=conn.cursor()
            user=cursor.execute('SELECT * FROM users WHERE telegram_user_id=?',(user_id,)).fetchone()
            created=create_offer_listing(cursor,user,payload,photos,UPLOAD_DIR,get_listing_photo_column(cursor))
            conn.commit();committed=True
            return created
        except Exception:
            conn.rollback();raise
        finally:
            if created and not committed:
                for key in created['photo_keys']:delete_photo(key,UPLOAD_DIR)
            conn.close()
''')
s=s.replace('def start_add_flow(message):','def start_add_flow(message):\n    mark_bot_started(message.from_user)')
s=s.replace('def handle_type_offer(call):','def handle_type_offer(call):\n    mark_bot_started(call.from_user)')
s=s.replace('listing_id = save_listing_to_db(', 'created = save_listing_to_db(')
s=s.replace('        except Exception:\n            print(f"ERROR in save_listing_to_db:', '        except ListingServiceError as exc:\n            bot.send_message(call.message.chat.id,exc.message)\n            return\n        except Exception:\n            print(f"ERROR in save_listing_to_db:')
s=s.replace('bot.edit_message_text(f"E\'lon joylashtirildi. ID: {listing_id}", call.message.chat.id, call.message.message_id)','label="E’lon tekshiruvga yuborildi" if created["status"]=="hidden_pending_review" else "E’lon joylashtirildi"\n        bot.edit_message_text(f"{label}. ID: {created[\'listing_id\']}", call.message.chat.id, call.message.message_id)')
start=s.index('    query = "SELECT * FROM listings WHERE status = \'active\' AND listing_type = \'offer\'"',s.index('def run_search_and_reply'))
end=s.index('    conn = get_db()',start)
s=s[:start]+'''    filters=bot_filters(data)
    query,params=search_clause(filters,prefix='')
    query='SELECT * FROM listings WHERE '+query+' ORDER BY created_at DESC,id DESC LIMIT 30'
    save_search_preferences(user_id,data)

'''+s[end:]
start=s.index('        save_search_preferences(user_id, {',s.index('def run_search_and_reply'))
end=s.index('        markup =',start)
s=s[:start]+s[end:]
s=s.replace('    bot.send_message(chat_id, f"{len(results)} ta mos e\'lon topildi:")','    bot.send_message(chat_id, f"{len(results)} ta mos e\'lon topildi. Qidiruv saqlandi: yangi mos e’lon uchun xabar yuboramiz.")')
s=s.replace('WHERE telegram_user_id = ? AND status IN (\'active\', \'hidden_pending_review\')','WHERE telegram_user_id = ? AND status != \'removed\'')
s=s.replace('        cursor = conn.cursor()\n        cursor.execute(\n            "SELECT * FROM listings WHERE telegram_user_id', '        cursor = conn.cursor()\n        expire_listings(cursor);conn.commit()\n        cursor.execute(\n            "SELECT * FROM listings WHERE telegram_user_id')
s=s.replace("f\"Status: {listing['status']}\"", "f\"Holat: {STATUS_LABELS.get(effective_status(listing), 'Tekshiruvda')}\"")
s=replace_function(s,'handle_manage_listing','''@bot.callback_query_handler(func=lambda call:call.data.startswith(('del_','ext_')))
def handle_manage_listing(call):
    action,listing_id=call.data.split('_',1)
    if not listing_id.isdigit():return
    conn=get_db()
    try:
        status=manage_listing(conn.cursor(),int(listing_id),call.from_user.id,'remove' if action=='del' else 'extend')
        conn.commit();bot.answer_callback_query(call.id,'Yangilandi.')
        bot.edit_message_text('O‘chirildi.' if status=='removed' else 'E’lon yangilandi.',call.message.chat.id,call.message.message_id)
    except ListingServiceError as exc:
        conn.rollback();bot.answer_callback_query(call.id,exc.message,show_alert=True)
    except Exception:
        conn.rollback();traceback.print_exc();bot.answer_callback_query(call.id,'Saqlab bo‘lmadi. Qayta urinib ko‘ring.',show_alert=True)
    finally:
        conn.close()
''')
s=s.replace('    text = (message.text or "").strip()\n    if text.startswith("/")', '''    text = (message.text or "").strip()
    with draft_data(message.from_user.id,message.chat.id) as data:
        token=data.get('web_login_token')
    if token and not text.startswith('/'):
        conn=get_db()
        try:
            ok=len(text)==6 and text.isdigit() and approve_challenge(conn.cursor(),token,text,message.from_user.id)
            conn.commit()
        finally:
            conn.close()
        if ok:
            with draft_data(message.from_user.id,message.chat.id) as data:
                data.pop('web_login_token',None)
                previous=data.pop('web_login_previous_step',None)
                if previous:data['flow_step']=previous
                else:data.pop('flow_step',None)
            bot.reply_to(message,'Kirish tasdiqlandi. Saytga qayting.')
        else:
            bot.reply_to(message,'Kod noto‘g‘ri yoki eskirgan. 5 urinishdan keyin kirishni qayta boshlang.')
        return
    if text.startswith("/")''')
s=s.replace('print("Bot started...")\nbot.infinity_polling()', '''def run():
    if not TOKEN:raise RuntimeError('BOT_TOKEN is required')
    validate_storage()
    init_db()
    stop,worker=start_worker()
    try:bot.infinity_polling()
    finally:stop.set();worker.join(timeout=10)

if __name__=='__main__':run()''')
for line in ('import io\n','import random\n','import threading\n','from contextlib import contextmanager\n','from PIL import Image\n','SESSION_PATH = os.path.join(BASE_DIR, "bot_sessions.json")\n','session_lock = threading.Lock()\n'):
    s=s.replace(line,'')
compile(s,'proposed bot','exec')
save('audit/proposals/bot_main.py',s)
print('Compiled bot proposal saved; bot/main.py is unchanged.')
