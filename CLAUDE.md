# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Flask anime streaming / download site (UI text and code comments are mostly Mongolian). Video files live in a private Telegram channel and are streamed to the browser through Flask via Telethon; metadata lives in MongoDB; some per-user data lives in MySQL; images go to Cloudinary. Deployed on Render (`render.yaml`).

## Commands

```bash
pip install -r requirements.txt
python app.py                                   # dev server on $PORT or 5004
gunicorn app:app --bind 0.0.0.0:$PORT --timeout 600   # production (Render)
```

There are no tests, linter, or build step. `GET /health` is the Render health check.

Note: `utils.py` imports `mysql.connector` and `session_generator.py` imports `qrcode`, but neither package is in `requirements.txt` — install `mysql-connector-python` / `qrcode` manually if needed.

Telegram session setup (one-off, local): `session_generator.py` logs in via QR and writes `for_versel.session`; `session_to_string.py` converts it to a StringSession for the `TELEGRAM_SESSION` env var. Never commit `.session` files.

## Architecture

- **`app.py`** (~5.4k lines) — the whole web app: config, all routes (public, auth, playback, admin, APIs), helpers. It does `from uploader import *` and `from utils import *`, so names used in `app.py` may be defined in either module.
- **`uploader.py`** — Telethon client running on a dedicated background asyncio loop thread (`ensure_started` / `run_tg` bridge sync Flask code to it). Provides `upload_video_to_telegram_sync` and `telegram_range_stream` (byte-range download from a channel message, with TTL caches for channel/message lookups).
- **`utils.py`** — MySQL helpers (comments, ratings, watch progress, watch history, favorites, home comments, continue-watching), verify.mn phone-auth calls, paylink invoice create/check, Mongo insert helpers for anime/video metadata, ffprobe duration.
- **`templates/`** Jinja (all extend `base.html`), **`static/`** CSS/JS (`uploader.js` drives the admin uploader page).

### Data stores
- **MongoDB** (`MONGO_URI`, db `MONGO_DB_NAME`, default `anime_db`): `users`, `anime`, `videos`, `files`, `purchases`, `genres`, `home_slides`, `pending_auth`, plus `flask_sessions` (server-side sessions via Flask-Session). Some docs store `user_id`/`video_id` as `str` and others as `ObjectId` — queries often match both (`{"$in": [str(x), ObjectId(x)]}`).
- **MySQL** (`mysqlhost`, `mysqlport`, `dbuser`, `dbuser_pass`, `mysqldb`): comments, ratings, watch progress, watch history, favorites. Watch history was migrated here from Mongo (the Mongo collection is commented out). `init_comments_table()` runs at import.

### Auth
Phone-number login only (normalized to `+976XXXXXXXX`). `/auth/start` creates a verify.mn session (`verify_url`, `api_key_verify`); `/auth/verify/<pending_id>` + `/auth/status/<pending_id>` poll for confirmation via `pending_auth`; new users go to `/setup-nickname`. Admins are phones listed in `ADMIN_PHONES` (`admin_phones()` / `is_admin()`); decorators `login_required` and `admin_required`.

### Video playback protection (the subtle part)
1. `/watch/<video_id>` issues a random playback token stored on the user doc as `users.playback` (`video_id`, `anime_id`, `token`, `ua`, `last_seen`, `pos`, ...), and renders `watch.html` with `stream_url = /stream/<id>?t=<token>`.
2. The page sends `/playback/ping` heartbeats (current time, paused flag); these update `playback.pos` and save resume progress to MySQL. `/playback/end` and `before_request` navigation to `CLEAR_ENDPOINTS` clear the playback.
3. `/stream/<video_id>` rejects unless: video matches `playback.video_id`, token matches, heartbeat within `ACTIVE_TTL`, same User-Agent, purchase exists for non-free `price_type`. Ranges are capped at `VERCEL_RANGE_SIZE` per request. Requests outside `[pos-BEHIND, pos+AHEAD]` seconds (excluding the `HEAD`/`TAIL` bytes) earn strikes (`STRIKE_LIMIT` → revoke), and `check_rate` throttles/revokes per token. These limits are module-level constants near the top of `app.py`; rate/strike state is in-process memory (per gunicorn worker).

When changing `watch.html`'s player JS, keep it consistent with these server checks (ping cadence, token, seek behavior), or legitimate playback gets 403s.

### Uploads / payments
- Admin uploads (`/uploader`, `/api/admin/upload-video`, `/admin/videos`, `/admin/files`, `/admin/download-items`) save to a temp file, push to Telegram, then store channel/message IDs + `file_size` + `duration` in Mongo. Optional callback to a Django backend (`DJANGO_API_URL`, `DJANGO_API_KEY`).
- Paid episodes: `/payment/create/<video_id>` creates a paylink invoice (`paylink_url`), `/payment/check/<msg>` verifies and calls `record_purchase` into `purchases`.
- `/software` pages serve downloadable items with tier gating (`user_can_download`).

## Environment

See `render.yaml` and `README.md` for the full list. Key vars: `MONGO_URI`, `CLOUDINARY_URL` (or `CLOUDINARY_CLOUD_NAME/_API_KEY/_API_SECRET`), `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_CHANNEL_ID`, `TELEGRAM_SESSION`, `ADMIN_PHONES`, `MAX_UPLOAD_MB`, MySQL vars above, `verify_url`, `api_key_verify`, `paylink_url`. Loaded from `.env` via python-dotenv.

Note: `app.py` reads the Flask secret from `FLASK_SECRET_KEY`, while `render.yaml` generates `SECRET_KEY` — these do not match.
