# Sigamiz Features

Sigamiz helps students find shared housing in Tashkent while reducing broker spam and duplicate listings.

## Publishing

- Telegram login is required before a listing can be published.
- The bot must be opened once so the app can notify the user later.
- One Telegram account can have one active apartment listing at a time. This keeps the board closer to real student listings and makes broker behavior harder.
- Listings expire after 7 days unless extended from the bot.
- Publishers can add district, university, housing type, room count, price per person, roommate preference, amenities, phone visibility, description, location, and up to 5 photos.
- The website can capture browser location or geocode a typed address. Raw latitude and longitude are stored internally but are no longer the primary user input.

## Maps And Search

- The map shows active apartment offers only.
- Students can filter by price, amenities, district/university text search, and sort by price.
- Listing cards show price, district/university, photos, amenities, and contact actions.
- Users can report suspicious listings. After 3 reports, the listing is hidden for admin review.

## Telegram Bot

- The bot can publish listings through a guided flow.
- The bot can search for matching apartments by gender preference, price range, amenities, and location.
- If no apartment matches, the bot saves the search preferences and tells the user it will notify them later.
- When a new active listing matches saved preferences, the user gets a Telegram notification.

## Favorites

- Telegram login is required for favorites.
- Users can save listings, remove them, and compare saved apartments by price, district, university distance, room count, housing type, and amenities.

## Moderation And Anti-Broker Logic

- One active listing per Telegram account reduces repeated broker inventory.
- Duplicate-looking photos are detected with image hashes and can send a listing to `hidden_pending_review`.
- Admins receive review commands:

```text
/review <listing_id> approve
/review <listing_id> ban
```

- `approve` returns the listing to active status.
- `ban` removes the listing and bans the author.

## Main Files

- `frontend/map.html` - map, filters, listing cards, reports, favorites entry point.
- `frontend/publish.html` - Telegram-gated publishing form, address/location UX, photo upload.
- `frontend/favorites.html` - saved listings and comparison table.
- `backend/main.py` - FastAPI app, listing APIs, Telegram auth, favorites, reports, notifications.
- `bot/main.py` - Telegram bot flows for publishing, search, saved preferences, listing management.
- `backend/schema.sql` - SQLite base schema.
