# Render Flask + MongoDB Login

## User fields

MongoDB `users` collection:

```json
{
  "_id": "...",
  "phone": "+97699112233",
  "nickname": "Yagaa",
  "password_hash": "..."
}
```

There is no username or email.

## Registration

URL:

```text
/register
```

Fields:

- phone
- nickname
- password
- confirm password

## Login

URL:

```text
/login
```

Fields:

- phone
- password

## MongoDB

Set this environment variable in Render:

```text
MONGO_URI=mongodb+srv://USERNAME:PASSWORD@CLUSTER.mongodb.net/render_server?retryWrites=true&w=majority
```

Also add:

```text
SECRET_KEY=<random-long-secret>
```

If `render.yaml` is used, SECRET_KEY can be generated automatically.

## Render

Build:

```text
pip install -r requirements.txt
```

Start:

```text
gunicorn app:app
```

Health:

```text
/health
```

## Git push

```bat
cd C:\Users\myagmardorj\Documents\render_server

git add .
git commit -m "Use MongoDB phone authentication"
git push origin main
```
