# Sigamiz Features

Sigamiz helps students find shared housing in Tashkent while reducing broker spam and duplicate listings.

## Documentation Rule

- When a user-facing feature, auth flow, moderation rule, notification behavior, or deployment-relevant setting is added or changed, update this file in the same change.

## Authentication

- The primary web login path uses the official Telegram Login Widget.
- The visible login button uses `https://oauth.telegram.org/js/telegram-login.js?5` with `data-client-id`; the client id is derived from the public numeric prefix of `BOT_TOKEN` and exposed by `/api/config`.
- `/api/auth/telegram` accepts only Telegram-signed payloads and verifies the HMAC signature with `BOT_TOKEN`.
- Telegram `auth_date` is required and expires after 24 hours.
- If Telegram auth is not configured, the backend fails closed instead of accepting unsigned user ids.
- Web sessions are signed with `SESSION_SECRET`, which must be separate from `BOT_TOKEN`.
- A bot deep-link login exists in code as a fallback, but the visible UI currently hides it while the primary Telegram Login Widget flow is being verified.

## Publishing

- Telegram login is required before a listing can be published.
- The bot must be opened once so the app can notify the user later and so bot-link fallback login can confirm the account.
- One Telegram account can have one active apartment listing at a time. This keeps the board closer to real student listings and makes broker behavior harder.
- Listings expire after 7 days unless extended from the bot.
- Publishers can add district, university, housing type, room count, price per person, roommate preference, amenities, phone visibility, description, location, and up to 5 photos.
- The website can capture browser location or geocode a typed address through backend `/api/geocode` using `Yandex_geocoder`. Raw latitude and longitude are stored internally but are no longer the primary user input.

## Maps And Search

- The map shows active apartment offers only and uses Yandex Maps when `Yandex_java`/`YANDEX_JAVA` is configured.
- If Yandex Maps cannot load, the map falls back to the previous Leaflet/OpenStreetMap renderer.
- Students can filter by price, amenities, district/university text search, and sort by price.
- Listing cards show price, district/university, photos, amenities, and contact actions.
- The top map navigation keeps `Map`, `About`, and `How it works`; favorites live under the account menu.
- The account icon opens a menu with Telegram login, favorites, and publishing links.
- Users can report suspicious listings. After 3 reports, the listing is hidden for admin review.

## Telegram Bot

- The bot can publish listings through a guided flow.
- The bot can search for matching apartments by gender preference, price range, amenities, and location.
- If no apartment matches, the bot saves the search preferences and tells the user it will notify them later.
- When a new active listing matches saved preferences, the user gets a Telegram notification.

## Favorites

- Telegram login is required for favorites.
- Saving a listing from the map sends it to favorites and shows a notice that multiple saved listings can be compared on the favorites page.
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
- `backend/seed.py` - idempotently recreates 10 generated test listings for manual map/favorites QA.
