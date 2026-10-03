# Sigamiz Features

Update this file when authentication, publication, moderation, notifications or deployment settings change.

**Implementation status:** API and website changes below are applied. Telegram changes are prepared and tested offline in `audit/proposals/bot_main.py`, but are not applied to `bot/main.py`. The release contract check prevents deployment of this incomplete pair.

## Authentication

- Website login creates a browser-bound challenge and shows a six-digit code. The updated bot asks for that code and explicit consent; another person's link cannot silently authorize an account.
- Challenges expire after 10 minutes, allow five code attempts and are consumed atomically once. Completion requires the initiating browser cookie and an approval marker. Legacy bot auto-confirmation is rejected.
- The signed Telegram payload endpoint remains available and verifies HMAC, a maximum age of 24 hours and future clock tolerance. Unsigned identifiers are rejected.
- Sessions store token hashes, expiry and revocation in the shared database. They expire after 30 days. Logout revokes the server record. Production HTTPS cookies are Secure, HttpOnly and SameSite.
- Signed-in users see logout and no redundant bot login prompt.

## Publication and lifecycle

- Both transports use the same service, catalogs, ban check and bot-start requirement. Website publication respects bans.
- One account can have one active or pending-review listing. Owner locks and database uniqueness enforce this during simultaneous requests.
- Listings include district, university, housing type, rooms, monthly price per person, needed people, both gender fields, amenities, description and location. Phone is required without a Telegram username.
- Publication reduces coordinates to a shared public grid, about 200–250 metres per step in Tashkent. Exact input coordinates are not retained. Approximate location is not a guarantee of anonymity.
- Active listings expire after seven days and immediately disappear from public queries. Removed listings and moderation holds retain their status.
- Website and updated bot offer extension/removal. Expired listings reactivate on extension; held listings stay pending. Removed listings cannot be extended.
- Up to five photos, at most 5 MB each, are validated and reencoded as JPEG with EXIF removed. Decoded dimensions and request size are bounded. Storage uses portable keys.
- Identical photos within one publication are deduplicated. Low-information single-color images do not trigger perceptual similarity checks. Similarity to another live listing sends a new listing to review; responses say that accurately.
- Failed publication rolls back records and cleans newly stored files.

## Search, notifications and moderation

- Map, recommendations, saved bot searches and publication notifications share SQL predicates, including expiry, seeker gender and desired author gender.
- Updated bot searches save preferences whether results exist or not. Omitted housing/room/university fields clear stale preferences.
- Transactional outbox entries are committed with publication. Delivery occurs afterward, retries with backoff up to eight attempts, and uses event/recipient uniqueness. Delivery is at least once: an ambiguous timeout after Telegram accepts a message can cause a repeat.
- Three unique account reports hide an active listing. Self-reports, duplicate reports and reports of expired listings are rejected.
- Updated bot admins use `/review <id> approve` or `/review <id> ban`. Approval resets reports and extends the listing, respecting one-live-listing uniqueness. Ban removes the owner's public/held listings and blocks publication.
- Conflicting older holds migrate to `archived_pending_review`, remain nonpublic and require moderation.

## Website experience

- Cards retain their photo area/height with many results. Titles link to exact listings. Default order is newest; homepage totals use an independent query.
- Prices consistently show monthly cost per person. Details include needed people, gender fields and all photos with previous/next controls.
- Detail dialogs have labels, focus trapping, Escape closure and focus restoration. Telephone links contain the full sanitized number. Mobile details fit the viewport.
- Leaflet marker hit areas match rendered pins. Mobile filters show their names. All pages are reachable through the mobile menu.
- Loading, API failure/retry, empty results and empty favorites have explicit states. Production errors never render generated demo listings.
- Publication explains missing location, focuses the address control and disables repeated submissions. Per-user drafts, including photos, survive navigation/reload when browser storage is available.
- Shared rendering/authentication/catalogs/styles reduce copied rules. Navigation and explanatory copy use Uzbek. Unsupported success/trust claims were removed.

## Verification

`tests/` covers publication races, bans, expiry, search parity, photos, sessions, bound login, drafts, migrations, outbox retry and storage adapters. `scripts/check_frontend.js` compiles browser scripts and detects damaged encoding. `scripts/check_bot_contract.py` blocks a legacy bot/new API release. Local evidence and remaining limits are recorded in `audit/2026-10-02/fixes.md`.
