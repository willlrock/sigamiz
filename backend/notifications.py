"""Transactional delivery queue. HTTP calls happen after publication commits."""
import json
import os
import threading
import logging
from datetime import datetime, timedelta, timezone
import requests
from backend.db import get_db
from backend.search import search_clause

log = logging.getLogger(__name__)


def enqueue(cursor, key, chat_id, text, markup=None):
    cursor.execute("INSERT OR IGNORE INTO notification_outbox (event_key, chat_id, payload) VALUES (?, ?, ?)", (key, str(chat_id), json.dumps({"text": text, "reply_markup": markup}, ensure_ascii=False)))


def enqueue_admin(cursor, key, text):
    for chat in (os.getenv("ADMIN_CHAT_ID") or "").split(","):
        if chat.strip():
            enqueue(cursor, f"admin:{key}:{chat.strip()}", chat.strip(), text)


def enqueue_publication(cursor, listing_id):
    listing = cursor.execute("SELECT * FROM listings WHERE id = ? AND status = 'active' AND datetime(expires_at) > datetime('now')", (listing_id,)).fetchone()
    if not listing:
        return
    for prefs in cursor.execute("SELECT * FROM search_preferences WHERE telegram_user_id != ?", (listing["telegram_user_id"],)).fetchall():
        clause, params = search_clause(dict(prefs))
        if not cursor.execute("SELECT id FROM listings WHERE id = ? AND " + clause, [listing_id, *params]).fetchone():
            continue
        text = f"Qidiruvingizga mos yangi e'lon: {listing['district']}\n{listing['price_per_person']:,} so'm / kishi / oy".replace(",", " ")
        markup = {"inline_keyboard": [[{"text": "E'lonni ochish", "url": f"{os.getenv('SITE_URL', 'https://klapa.net').rstrip('/')}/xarita?listing={listing_id}"}]]}
        enqueue(cursor, f"publication:{listing_id}:{prefs['telegram_user_id']}", prefs["telegram_user_id"], text, markup)


def deliver_batch():
    token = os.getenv("BOT_TOKEN")
    if not token:
        return
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM notification_outbox WHERE delivered_at IS NULL AND attempts < 8 AND next_attempt_at <= datetime('now') ORDER BY id LIMIT 20").fetchall()
    finally:
        conn.close()
    for row in rows:
        conn = get_db()
        try:
            lease = (datetime.now(timezone.utc) + timedelta(minutes=2)).replace(tzinfo=None).isoformat(sep=" ")
            claim = conn.execute("UPDATE notification_outbox SET next_attempt_at = ?, attempts = attempts + 1 WHERE id = ? AND delivered_at IS NULL AND next_attempt_at <= datetime('now')", (lease, row["id"]))
            won = claim.rowcount == 1
            conn.commit()
        finally:
            conn.close()
        if not won:
            continue
        ok = False
        try:
            data = json.loads(row["payload"])
            response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": row["chat_id"], **data}, timeout=8)
            ok = response.ok and response.json().get("ok", False)
        except (requests.RequestException, ValueError):
            log.warning("Telegram delivery failed for outbox item %s", row["id"])
        conn = get_db()
        try:
            retry = (datetime.now(timezone.utc) + timedelta(seconds=min(3600, 30 * 2 ** row["attempts"]))).replace(tzinfo=None).isoformat(sep=" ")
            conn.execute("UPDATE notification_outbox SET delivered_at = ?, next_attempt_at = ? WHERE id = ?", (datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ") if ok else None, retry, row["id"]))
            conn.commit()
        finally:
            conn.close()


def start_worker():
    stop = threading.Event()
    def run():
        while not stop.is_set():
            try:
                from backend.lifecycle import expire_listings
                conn = get_db()
                try:
                    expire_listings(conn.cursor())
                    conn.commit()
                finally:
                    conn.close()
                deliver_batch()
            except Exception:
                log.exception("Background worker failed")
            stop.wait(30)
    thread = threading.Thread(target=run, name="sigamiz-outbox", daemon=True)
    thread.start()
    return stop, thread
