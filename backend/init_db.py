import sqlite3
import os

db_path = "database.db"
schema_path = "schema.sql"

def init_db():
    if os.path.exists(db_path):
        print(f"{db_path} already exists. Skipping creation.")
        return

    with open(schema_path, 'r', encoding='utf-8') as f:
        schema = f.read()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executescript(schema)
    conn.commit()
    conn.close()
    print(f"Database {db_path} initialized successfully.")

if __name__ == "__main__":
    init_db()
