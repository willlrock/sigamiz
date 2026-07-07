CREATE TABLE IF NOT EXISTS listings (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 telegram_user_id INTEGER NOT NULL,
 telegram_username TEXT NOT NULL,
 listing_type TEXT NOT NULL DEFAULT 'seek' CHECK(listing_type IN ('offer','seek')),
 university TEXT,
 district TEXT,
 housing_type TEXT,
 description TEXT,
 phone_number TEXT,
 room_count INTEGER,
 author_gender TEXT CHECK(author_gender IN ('male','female')),
 preferred_gender TEXT CHECK(preferred_gender IN ('male','female','any')),
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

CREATE TABLE IF NOT EXISTS listing_photos (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 listing_id INTEGER NOT NULL,
 file_path TEXT NOT NULL,
 sort_order INTEGER DEFAULT 0,
 FOREIGN KEY (listing_id) REFERENCES listings (id)
);

CREATE TABLE IF NOT EXISTS reports (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 listing_id INTEGER NOT NULL,
 reporter_telegram_id INTEGER,
 reporter_key TEXT,
 reason TEXT,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (listing_id) REFERENCES listings (id)
);

CREATE TABLE IF NOT EXISTS banned_users (
 telegram_user_id INTEGER PRIMARY KEY,
 reason TEXT,
 banned_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
 telegram_user_id INTEGER PRIMARY KEY,
 telegram_username TEXT,
 first_name TEXT,
 last_name TEXT,
 photo_url TEXT,
 bot_started_at DATETIME,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 last_seen_at DATETIME
);

CREATE TABLE IF NOT EXISTS favorites (
 telegram_user_id INTEGER NOT NULL,
 listing_id INTEGER NOT NULL,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (telegram_user_id, listing_id),
 FOREIGN KEY (listing_id) REFERENCES listings (id)
);

CREATE TABLE IF NOT EXISTS listing_views (
 telegram_user_id INTEGER NOT NULL,
 listing_id INTEGER NOT NULL,
 viewed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (telegram_user_id, listing_id),
 FOREIGN KEY (listing_id) REFERENCES listings (id)
);

CREATE TABLE IF NOT EXISTS search_preferences (
 telegram_user_id INTEGER PRIMARY KEY,
 price_min INTEGER,
 price_max INTEGER,
 districts TEXT,
 housing_type TEXT,
 room_count INTEGER,
 university TEXT,
 has_wifi BOOLEAN DEFAULT 0,
 has_ac BOOLEAN DEFAULT 0,
 has_washing_machine BOOLEAN DEFAULT 0,
 no_landlord_in_yard BOOLEAN DEFAULT 0,
 near_metro BOOLEAN DEFAULT 0,
 updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS listing_photo_hashes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 listing_id INTEGER NOT NULL,
 photo_hash TEXT NOT NULL,
 created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (listing_id) REFERENCES listings (id)
);

CREATE INDEX IF NOT EXISTS idx_listing_photo_hashes_hash ON listing_photo_hashes (photo_hash);
