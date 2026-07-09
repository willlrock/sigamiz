# Sigamiz

Student housing and roommate map for Tashkent students.

Sigamiz combines a Telegram bot for listing creation with a FastAPI backend and static frontend pages. Students can publish either an "I have a place" listing or an "I am looking for housing" listing, then browse active listings on a map.

Feature documentation lives in [FEATURES.md](FEATURES.md).

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
SESSION_SECRET=generate_a_long_random_secret
DATABASE_URL=postgresql://user:password@host:port/dbname
Yandex_java=your_yandex_maps_javascript_api_key
Yandex_geocoder=your_yandex_geocoder_api_key
SEED_DEMO_DATA=false
```

`ADMIN_CHAT_ID` can contain one chat id or a comma-separated list.
`BOT_USERNAME` defaults to `klapa_net_bot`; set it explicitly when deploying another bot.
`SESSION_SECRET` signs web sessions; keep it separate from `BOT_TOKEN`.
`DATABASE_URL` is optional locally. When it is set to a `postgres://` or `postgresql://` URL, both the backend and bot use Postgres instead of `backend/database.db`.
`Yandex_java` is exposed to the browser for Yandex Maps JavaScript API. `Yandex_geocoder` stays backend-only for address lookup.

## Local Run

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python backend/main.py
```

Run the bot in another terminal:

```bash
.venv/bin/python bot/main.py
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
SESSION_SECRET=generate_a_long_random_secret
BOT_TOKEN=your_telegram_bot_token
BOT_USERNAME=Sigamiz_bot
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

Deploy the Telegram bot as a separate worker/service with:

```bash
python bot/main.py
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

- SQLite migrations are lightweight and run on backend startup.
- Runtime files such as `.env`, `backend/database.db`, `uploads/`, and agent workspace files are ignored by git.
