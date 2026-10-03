from backend.listing_service import ListingServiceError
from datetime import datetime, timezone


def effective_status(row):
    if row['status']!='active':
        return row['status']
    try:
        expires=datetime.fromisoformat(str(row['expires_at']).replace('Z','+00:00'))
        if expires.tzinfo is None:
            expires=expires.replace(tzinfo=timezone.utc)
        return 'active' if expires>datetime.now(timezone.utc) else 'expired'
    except (TypeError,ValueError):
        return 'expired'


def expire_listings(cursor):
    # Moderation holds and removed records are never resurrected by expiry.
    cursor.execute("UPDATE listings SET status = 'expired' WHERE status = 'active' AND datetime(expires_at) <= datetime('now')")


def manage_listing(cursor, listing_id, user_id, action, admin=False):
    owner=cursor.execute('SELECT telegram_user_id FROM listings WHERE id=?',(listing_id,)).fetchone()
    if not owner or (not admin and owner['telegram_user_id']!=user_id):
        raise ListingServiceError('E‘lon topilmadi',404)
    if getattr(cursor,'is_postgres',False):
        cursor.execute('SELECT telegram_user_id FROM users WHERE telegram_user_id=? FOR UPDATE',(owner['telegram_user_id'],))
    expire_listings(cursor)
    lock = " FOR UPDATE" if getattr(cursor, "is_postgres", False) else ""
    row = cursor.execute("SELECT * FROM listings WHERE id = ?" + lock, (listing_id,)).fetchone()
    if not row or (not admin and row["telegram_user_id"] != user_id):
        raise ListingServiceError("E'lon topilmadi", 404)
    if action == "remove":
        cursor.execute("UPDATE listings SET status = 'removed' WHERE id = ?", (listing_id,))
        return "removed"
    if action not in ("extend", "approve") or (action == "approve" and not admin):
        raise ListingServiceError("Noto'g'ri amal")
    if row["status"] == "removed":
        raise ListingServiceError("O'chirilgan e'lonni uzaytirib bo'lmaydi", 409)
    if cursor.execute("SELECT 1 FROM banned_users WHERE telegram_user_id = ?", (row["telegram_user_id"],)).fetchone():
        raise ListingServiceError("Akkaunt bloklangan", 403)
    target = "hidden_pending_review" if row["status"] in ('hidden_pending_review','archived_pending_review') and action == "extend" else "active"
    if cursor.execute("SELECT 1 FROM listings WHERE telegram_user_id = ? AND id != ? AND status IN ('active','hidden_pending_review')", (row["telegram_user_id"], listing_id)).fetchone():
        raise ListingServiceError("Avval boshqa faol e'lonni o'chiring", 409)
    cursor.execute("UPDATE listings SET status = ?, expires_at = datetime('now', '+7 days'), report_count = ? WHERE id = ?", (target, 0 if action=='approve' else row['report_count'], listing_id))
    if target == "active":
        from backend.notifications import enqueue_publication
        enqueue_publication(cursor, listing_id)
    return target


def review_listing(cursor, listing_id, action):
    if action=='approve':
        return manage_listing(cursor,listing_id,None,'approve',admin=True)
    if action!='ban':
        raise ListingServiceError('Noto‘g‘ri amal')
    row=cursor.execute('SELECT telegram_user_id FROM listings WHERE id=?',(listing_id,)).fetchone()
    if not row:
        raise ListingServiceError('E‘lon topilmadi',404)
    owner=row['telegram_user_id']
    if getattr(cursor,'is_postgres',False):
        cursor.execute('SELECT telegram_user_id FROM users WHERE telegram_user_id=? FOR UPDATE',(owner,))
    elif not cursor.connection.in_transaction:
        cursor.execute('BEGIN IMMEDIATE')
    cursor.execute("INSERT INTO banned_users (telegram_user_id,reason) VALUES (?,?) ON CONFLICT(telegram_user_id) DO UPDATE SET reason=excluded.reason,banned_at=CURRENT_TIMESTAMP",(owner,f'Admin review for listing {listing_id}'))
    cursor.execute("UPDATE listings SET status='removed' WHERE telegram_user_id=? AND status IN ('active','hidden_pending_review','archived_pending_review')",(owner,))
    return 'removed'
