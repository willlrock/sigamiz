# Sigamiz

Student housing and roommate map for Tashkent students.

Sigamiz combines a Telegram bot for listing creation with a FastAPI backend and static frontend pages. Students publish housing offers and save roommate/housing search preferences.

Feature documentation lives in [FEATURES.md](FEATURES.md).

**Worktree status:** API and website fixes are applied. The matching bot update is prepared in `audit/proposals/bot_main.py` and awaits approval after automatic review rejected the combined rewrite. Do not deploy the new API with the existing bot. `scripts/check_bot_contract.py` blocks this incomplete pair.

## Project Structure

- `bot/` - Telegram bot powered by pyTelegramBotAPI.
- `backend/` - FastAPI app, SQLite schema, listing/report APIs.
- `frontend/` - Static HTML/CSS/JS pages for landing, map, and about.
- `uploads/` - Runtime photo storage, ignored by git.
- `*.service`, `klapa.nginx.conf` - Deployment examples.
- `CLOUDFLARE_TUNNEL.md`, `cloudflared.example.yml` - Cloudflare Tunnel setup for servers without a static public IP.

## Environment

Create `.env` in the project root:

```env
BOT_TOKEN=your_telegram_bot_token
BOT_USERNAME=your_bot_username_without_at
ADMIN_CHAT_ID=your_admin_chat_id
SITE_URL=https://your-domain.example
DATABASE_URL=postgresql://user:password@host:port/dbname
Yandex_java=your_yandex_maps_javascript_api_key
Yandex_geocoder=your_yandex_geocoder_api_key
```

`ADMIN_CHAT_ID` can contain one chat id or a comma-separated list.
`BOT_USERNAME` defaults to `klapa_net_bot`; set it explicitly when deploying another bot.
Sessions use random tokens whose hashes, expiry and revocation are stored in the database. `SESSION_SECRET` is no longer used; old signed cookies require login again.
`DATABASE_URL` is optional locally. When it is set to a `postgres://` or `postgresql://` URL, both the backend and bot use Postgres instead of `backend/database.db`.
`Yandex_java` is exposed to the browser for Yandex Maps JavaScript API. `Yandex_geocoder` stays backend-only for address lookup.

## Local Run

```bash
python -m venv .venv
# Activate: source .venv/bin/activate
# PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m backend.init_db
python -m backend.main
```

After applying and verifying the bot proposal, run it in another terminal:

```bash
python -m bot.main
```

Open:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/xarita`
- `http://127.0.0.1:8000/about`

## Railway Web Deploy

The repository includes `railpack.json` so Railway/Railpack can start the web app explicitly:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Set at least these Railway variables:

```env
SITE_URL=https://your-railway-domain-or-custom-domain
BOT_TOKEN=your_telegram_bot_token
BOT_USERNAME=Sigamiz_bot
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

Deploy the Telegram bot as a separate worker/service with:

```bash
python -m bot.main
```

## Moderation

After three reports, an active listing is moved to `hidden_pending_review` and the admin chat receives review commands:

```text
/review <listing_id> approve
/review <listing_id> ban
```

- `approve` returns the listing to `active` and resets `report_count`.
- `ban` marks the listing as `removed` and adds the owner to `banned_users`.

## Notes

- Database migrations are versioned, transactional and serialized. Importing the API performs no database initialization or background startup; the prepared bot follows the same rule.
- Runtime files such as `.env`, `backend/database.db`, `uploads/`, and agent workspace files are ignored by git.

## Shared storage and migration

Both services must use the same database. Single-host deployments share a persistent `UPLOAD_DIR`. Separate containers need an actual shared volume with `SHARED_UPLOAD_VOLUME=true`, or S3 compatible storage. Railway / `DEPLOYMENT_TOPOLOGY=split` fails startup without one of these. Use one shared `DATABASE_URL`; separate SQLite files cannot share users/listings.

```env
DEPLOYMENT_TOPOLOGY=split
S3_BUCKET=your_bucket
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=your_region
# Optional provider endpoint and public image base URL:
S3_ENDPOINT_URL=https://your-storage-endpoint.example
PHOTO_PUBLIC_URL=https://images.example
```

Without `PHOTO_PUBLIC_URL`, S3 URLs are signed for one hour. Local overrides: `UPLOAD_DIR` and `SIGAMIZ_DB_PATH`. A flag does not create a shared volume. Keep storage credentials private.

Back up the database and uploads before production migration. Existing coordinates are blurred; duplicate live owners are reconciled, retaining older moderation holds as nonpublic `archived_pending_review`. Legacy files must be available inside `UPLOAD_DIR`:

```bash
python -m backend.migrate_photos
python -m backend.migrate_photos --apply
```

The first command checks only; the second copies JPEG and updates paths. Originals remain. Missing files produce exit code 2. Stop the old bot before importing its JSON drafts or switching versions:

```bash
python -m backend.migrate_drafts bot_sessions.json
python -m backend.migrate_drafts bot_sessions.json --apply
```

Current database drafts are never overwritten.

## Verification

Use Python 3.12 and Node.js:

```bash
python -m unittest discover -s tests -v
node scripts/check_frontend.js
python scripts/check_bot_contract.py
```

Tests use disposable SQLite databases, synthetic users and mocked Telegram/S3. Browser checks use a separate disposable preview. Live PostgreSQL, S3 credentials and production deployment have not been exercised locally. The bot contract check currently fails intentionally until the approved proposal is applied. CI and deployment check rules, syntax and the bot contract before migration/restarts; deployment checks `/api/config` afterward. No production workflow or service was run during this repair.

Shared rules live in `backend/catalogs.py`, `search.py`, `listing_service.py`, `lifecycle.py`, `security.py`, `storage.py`, `notifications.py`, `drafts.py` and `migrations.py`. Website helpers live in `shared.js`, `auth.js`, `draft.js` and `shared.css`. Old prototypes are outside the served directory in `archive/frontend/`. Verification evidence: `audit/2026-10-02/fixes.md`.
