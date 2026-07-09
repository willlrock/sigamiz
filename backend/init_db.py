import os
try:
    from db import execute_schema, get_db
except ModuleNotFoundError:
    from backend.db import execute_schema, get_db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "database.db")

def init_db():
    if not os.getenv("DATABASE_URL") and os.path.exists(db_path):
        print(f"{db_path} already exists. Skipping creation.")
        return

    conn = get_db()
    cursor = conn.cursor()
    execute_schema(cursor)
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

if __name__ == "__main__":
    init_db()
