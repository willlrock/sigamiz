"""Persistent bot drafts, serialized per conversation across threads/processes."""
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from backend.db import get_db
from backend import db

_locks, _guard = {}, threading.Lock()

@contextmanager
def draft_data(user_id, chat_id):
    key = f'{chat_id}:{user_id}'
    with _guard:
        lock = _locks.setdefault(key, threading.RLock())
    with lock:
        conn = get_db()
        pg = hasattr(conn, 'conn')
        lock_file = None
        advisory_key = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'big', signed=True)
        try:
            if pg:
                conn.execute('SELECT pg_advisory_lock(?)', (advisory_key,))
                conn.commit()
            else:
                directory = os.path.join(os.path.dirname(db.SQLITE_DB_PATH), '.draft-locks')
                os.makedirs(directory, exist_ok=True)
                lock_file = open(os.path.join(directory, hashlib.sha256(key.encode()).hexdigest()), 'a+b')
                if os.name == 'nt':
                    import msvcrt
                    lock_file.seek(0)
                    if not lock_file.read(1):
                        lock_file.write(b'0'); lock_file.flush()
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_file, fcntl.LOCK_EX)
            row = conn.execute('SELECT payload FROM bot_drafts WHERE draft_key=?', (key,)).fetchone()
            conn.commit()
            data = json.loads(row[0]) if row else {}
            yield data
            conn.execute("INSERT INTO bot_drafts (draft_key,payload) VALUES (?,?) ON CONFLICT(draft_key) DO UPDATE SET payload=excluded.payload,updated_at=CURRENT_TIMESTAMP", (key,json.dumps(data,ensure_ascii=False)))
            conn.commit()
        finally:
            if pg:
                conn.rollback()
                conn.execute('SELECT pg_advisory_unlock(?)', (advisory_key,))
                conn.commit()
            elif lock_file:
                if os.name == 'nt':
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
                lock_file.close()
            conn.close()

def clear_draft(user_id, chat_id):
    with draft_data(user_id, chat_id) as data:
        data.clear()
