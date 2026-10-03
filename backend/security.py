"""Opaque, revocable sessions and browser-bound Telegram login challenges."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from backend.db import get_db

SESSION_SECONDS = 60 * 60 * 24 * 30


def now_iso():
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def make_session_cookie(user_id):
    token = secrets.token_urlsafe(32)
    conn = get_db()
    try:
        conn.execute("INSERT INTO web_sessions (token_hash, telegram_user_id, expires_at) VALUES (?, ?, ?)",
                     (digest(token), user_id, (datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS)).replace(tzinfo=None).isoformat(sep=" ")))
        conn.commit()
    finally:
        conn.close()
    return token


def read_session_cookie(token):
    if not isinstance(token, str) or len(token) > 128:
        return None
    conn = get_db()
    try:
        row = conn.execute("SELECT telegram_user_id FROM web_sessions WHERE token_hash = ? AND expires_at > datetime('now') AND revoked_at IS NULL", (digest(token),)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def revoke_session(token):
    if token:
        conn = get_db()
        try:
            conn.execute("UPDATE web_sessions SET revoked_at = datetime('now') WHERE token_hash = ?", (digest(token),))
            conn.commit()
        finally:
            conn.close()


def create_challenge(cursor, binding):
    token, code = secrets.token_urlsafe(18), f"{secrets.randbelow(1000000):06d}"
    cursor.execute("INSERT INTO web_login_tokens (token, browser_hash, code_hash, expires_at) VALUES (?, ?, ?, datetime('now', '+10 minutes'))", (token, digest(binding), digest(code)))
    return token, code


def approve_challenge(cursor, token, code, user_id):
    # Wrong guesses are bounded per challenge; approval never rebinds an account.
    cursor.execute("UPDATE web_login_tokens SET attempts = attempts + 1 WHERE token = ? AND used_at IS NULL AND attempts < 5", (token,))
    if cursor.rowcount != 1:
        return False
    cursor.execute("UPDATE web_login_tokens SET telegram_user_id = ?, approved_at = datetime('now') WHERE token = ? AND code_hash = ? AND telegram_user_id IS NULL AND expires_at > datetime('now') AND used_at IS NULL AND attempts <= 5", (user_id, token, digest(code)))
    return cursor.rowcount == 1


def upsert_user(cursor, telegram_user_id, username=None, first_name=None, last_name=None, photo_url=None, bot_started=False):
    cursor.execute("""INSERT INTO users (telegram_user_id, telegram_username, first_name, last_name, photo_url, bot_started_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(telegram_user_id) DO UPDATE SET
        telegram_username = excluded.telegram_username,
        first_name = COALESCE(excluded.first_name, users.first_name),
        last_name = COALESCE(excluded.last_name, users.last_name),
        photo_url = COALESCE(excluded.photo_url, users.photo_url),
        bot_started_at = COALESCE(users.bot_started_at, excluded.bot_started_at), last_seen_at = excluded.last_seen_at""",
        (telegram_user_id, username, first_name, last_name, photo_url, now_iso() if bot_started else None, now_iso()))
