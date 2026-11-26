"""cPanel "Setup Python App" (Phusion Passenger) entry point.

Passenger энэ файлаас `application` нэртэй WSGI объектыг хайдаг.
"""
import os
import sys

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

os.chdir(APP_ROOT)
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

# .env-г app импортлохоос өмнө ачаална (cPanel-ийн env var-ууд давуу эрхтэй).
from dotenv import load_dotenv

load_dotenv(os.path.join(APP_ROOT, ".env"), override=False)

# Том upload-ийн temp файлууд /tmp-г дүүргэхгүйн тулд home доторх хавтсанд бичнэ.
_tmp = os.getenv("TMPDIR") or os.path.join(APP_ROOT, "tmp")
os.makedirs(_tmp, exist_ok=True)
os.environ["TMPDIR"] = _tmp

from app import app as application  # noqa: E402
