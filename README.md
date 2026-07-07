# Sigamiz

Student housing and roommate map for Tashkent students.

Sigamiz combines a Telegram bot for listing creation with a FastAPI backend and static frontend pages. Students can publish either an "I have a place" listing or an "I am looking for housing" listing, then browse active listings on a map.

## Project Structure

- `bot/` - Telegram bot powered by pyTelegramBotAPI.
- `backend/` - FastAPI app, SQLite schema, listing/report APIs.
- `frontend/` - Static HTML/CSS/JS pages for landing, map, and about.
- `uploads/` - Runtime photo storage, ignored by git.
- `*.service`, `klapa.nginx.conf` - Deployment examples.

## Environment

Create `.env` in the project root:

```env
BOT_TOKEN=your_telegram_bot_token
ADMIN_CHAT_ID=your_admin_chat_id
SITE_URL=https://your-domain.example
SEED_DEMO_DATA=false
```

`ADMIN_CHAT_ID` can contain one chat id or a comma-separated list.

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
