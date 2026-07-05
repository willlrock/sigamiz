-- schema.sql для klapa.net

CREATE TABLE listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    telegram_username TEXT NOT NULL,
    university TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    price_per_person INTEGER NOT NULL,
    people_needed INTEGER NOT NULL,
    has_wifi BOOLEAN DEFAULT 0,
    has_ac BOOLEAN DEFAULT 0,
    has_washing_machine BOOLEAN DEFAULT 0,
    no_landlord_in_yard BOOLEAN DEFAULT 0,
    near_metro BOOLEAN DEFAULT 0,
    status TEXT DEFAULT 'active',
    report_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL
);

CREATE TABLE listing_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    reporter_telegram_id INTEGER,
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE banned_users (
    telegram_user_id INTEGER PRIMARY KEY,
    reason TEXT,
    banned_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
