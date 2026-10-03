"""One versioned schema owner for both entry points."""
from backend.db import execute_schema, get_db
from backend.lifecycle import expire_listings


def ensure_columns(cursor, table, columns):
    existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db():
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT pg_advisory_xact_lock(73423691)" if getattr(cursor, "is_postgres", False) else "BEGIN IMMEDIATE")
        execute_schema(cursor)
        cursor.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        if not cursor.execute("SELECT 1 FROM schema_migrations WHERE version = 1").fetchone():
            ensure_columns(cursor, "listings", {"listing_type": "TEXT DEFAULT 'seek'", "university": "TEXT", "district": "TEXT", "housing_type": "TEXT", "description": "TEXT", "phone_number": "TEXT", "room_count": "INTEGER", "author_gender": "TEXT", "preferred_gender": "TEXT", "has_washing_machine": "INTEGER DEFAULT 0", "no_landlord_in_yard": "INTEGER DEFAULT 0", "near_metro": "INTEGER DEFAULT 0", "report_count": "INTEGER DEFAULT 0", "created_at": "DATETIME", "location_blurred": "INTEGER DEFAULT 0"})
            ensure_columns(cursor, "listing_photos", {"file_path": "TEXT", "sort_order": "INTEGER DEFAULT 0"})
            ensure_columns(cursor, "reports", {"reporter_telegram_id": "BIGINT", "reporter_key": "TEXT", "reason": "TEXT", "created_at": "DATETIME"})
            ensure_columns(cursor, 'banned_users', {'reason':'TEXT','banned_at':'DATETIME'})
            ensure_columns(cursor, "search_preferences", {"seeker_gender": "TEXT", "preferred_gender": "TEXT"})
            ensure_columns(cursor, "web_login_tokens", {"browser_hash": "TEXT", "code_hash": "TEXT", "attempts": "INTEGER DEFAULT 0"})
            for row in cursor.execute("SELECT id, lat, lng FROM listings WHERE location_blurred = 0").fetchall():
                cursor.execute("UPDATE listings SET lat=?, lng=?, location_blurred=1 WHERE id=?", (round(row["lat"] / .002) * .002, round(row["lng"] / .003) * .003, row["id"]))
            expire_listings(cursor)
            seen = set()
            for row in cursor.execute("SELECT id, telegram_user_id, status FROM listings WHERE status IN ('active','hidden_pending_review') ORDER BY id DESC").fetchall():
                if row["telegram_user_id"] in seen:
                    status='archived_pending_review' if row['status']=='hidden_pending_review' else 'expired'
                    cursor.execute("UPDATE listings SET status=? WHERE id=?", (status,row["id"]))
                seen.add(row["telegram_user_id"])
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_one_live_listing_per_owner ON listings (telegram_user_id) WHERE status IN ('active','hidden_pending_review')")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_listing_reporter_key ON reports (listing_id, reporter_key)")
            if getattr(cursor, "is_postgres", False):
                for table in ("users", "listings", "banned_users", "favorites", "listing_views", "search_preferences", "web_login_tokens"):
                    cursor.execute(f"ALTER TABLE {table} ALTER COLUMN telegram_user_id TYPE BIGINT")
                for name in ("reporter_telegram_id", "reporter_telegram_user_id"):
                    if name in {r[1] for r in cursor.execute("PRAGMA table_info(reports)").fetchall()}:
                        cursor.execute(f"ALTER TABLE reports ALTER COLUMN {name} TYPE BIGINT")
            cursor.execute("INSERT INTO schema_migrations (version) VALUES (1)")
        if not cursor.execute('SELECT 1 FROM schema_migrations WHERE version=2').fetchone():
            ensure_columns(cursor, 'web_login_tokens', {'approved_at': 'DATETIME'})
            cursor.execute('INSERT INTO schema_migrations (version) VALUES (2)')
        expire_listings(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
