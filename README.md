# render_server — Admin Telegram Uploader

Existing Flask + MongoDB + Cloudinary app extended with an admin-only video uploader.

## Admin

Default admin phone:

```text
85963616
```

Internally it normalizes to `+97685963616`. You can override/add phones with:

```text
ADMIN_PHONES=85963616,99112233
```

Only an authenticated admin can open:

```text
/uploader
```

and call:

```text
POST /api/admin/upload-video
```

## Telegram env

```text
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_CHANNEL_ID=-100...
TELEGRAM_SESSION=
MAX_UPLOAD_MB=2048
```

Use a Telethon StringSession in `TELEGRAM_SESSION` on Render. Do not commit `.session` files.

## Optional Django callback

```text
DJANGO_API_URL=https://django-video-backend.onrender.com
DJANGO_API_KEY=
```

After Telegram upload, Flask POSTs metadata to:

```text
POST <DJANGO_API_URL>/api/videos/create/
```

If Django callback is not configured, Telegram upload still succeeds and the uploader page displays the returned channel/message IDs.

## Render

The Render free plan suspends the web service after a period without requests.
That can make the site appear disconnected, but it is separate from the Flask
login lifetime. Keep the generated `SECRET_KEY` environment variable unchanged
so signed login cookies remain valid when Render starts a new instance. Use a
paid always-on plan if the service must remain continuously connected.

Build command:

```text
pip install -r requirements.txt
```

Start command:

```text
gunicorn app:app --bind 0.0.0.0:$PORT --timeout 600
```
