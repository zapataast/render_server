import os, re, asyncio, tempfile
from datetime import datetime
from functools import wraps

from bson.objectid import ObjectId
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_pymongo import PyMongo
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash, check_password_hash

import requests
from uploader import upload_video_to_telegram
from utils import *
import cloudinary
import cloudinary.uploader
import mimetypes
import re

from flask import (
    Response,
    abort,
    request,
    stream_with_context,
)

from uploader import (
    telegram_range_stream,
)
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/render_server")
PROFILE_IMAGE_MAX_MB = 5
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "2048"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
PROFILE_IMAGE_SCALE = int(
    os.getenv("PROFILE_IMAGE_SCALE", "100")
)

PROFILE_IMAGE_CROP = os.getenv(
    "PROFILE_IMAGE_CROP",
    "fit"
)
PROFILE_IMAGE_QUALITY = os.getenv(
    "PROFILE_IMAGE_QUALITY"
)
@app.context_processor
def inject_profile_settings():
    return {
        "PROFILE_IMAGE_SCALE": PROFILE_IMAGE_SCALE
    }
mongo = PyMongo(app)

if os.getenv("CLOUDINARY_URL"):
    cloudinary.config(secure=True)
else:
    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
        secure=True,
    )

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

with app.app_context():
    try:
        mongo.db.users.create_index("phone", unique=True)
        mongo.db.users.create_index("email", unique=True, sparse=True)
    except Exception as exc:
        print("Mongo index warning:", exc)


def normalize_phone(phone):
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) == 8:
        return "+976" + digits
    if len(digits) == 11 and digits.startswith("976"):
        return "+" + digits
    return ""


def display_phone(phone):
    return phone[4:] if phone and phone.startswith("+976") else (phone or "")


def admin_phones():
    raw = os.getenv("ADMIN_PHONES", "85963616")
    values = set()
    for item in raw.split(","):
        phone = normalize_phone(item.strip())
        if phone:
            values.add(phone)
    return values


def is_admin(user):
    return bool(user and user.get("phone") in admin_phones())


def current_user():
    try:
        return mongo.db.users.find_one({"_id": ObjectId(session.get("user_id"))})
    except Exception:
        return None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            session.clear()
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            session.clear()
            return redirect(url_for("login"))
        if not is_admin(user):
            flash("Энэ хэсэгт зөвхөн admin хэрэглэгч нэвтэрнэ.", "danger")
            return redirect(url_for("dashboard"))
        return fn(*args, **kwargs)
    return wrapper

VIDEO_INDEX = {}


def build_video_index(anime_list):
    global VIDEO_INDEX

    VIDEO_INDEX = {}

    for anime in anime_list:
        for video in anime.get("videos", []):
            video["anime"] = {
                "id": anime.get("id"),
                "name": anime.get("name"),
                "image_url": anime.get("image_url"),
                "description": anime.get("description"),
            }

            VIDEO_INDEX[int(video["id"])] = video
from flask import abort, render_template




@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        phone = normalize_phone(request.form.get("phone"))
        nickname = (request.form.get("nickname") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not phone:
            flash("Утасны дугаар 8 оронтой байна.", "danger")
        elif not 2 <= len(nickname) <= 50:
            flash("Nickname 2-50 тэмдэгт байна.", "danger")
        elif len(password) < 6:
            flash("Нууц үг хамгийн багадаа 6 тэмдэгт байна.", "danger")
        elif password != confirm:
            flash("Нууц үг таарахгүй байна.", "danger")
        else:
            try:
                result = mongo.db.users.insert_one({
                    "phone": phone,
                    "nickname": nickname,
                    "password_hash": generate_password_hash(password),
                    "birthdate": None,
                    "bio": "",
                    "profile_image_url": None,
                    "profile_image_public_id": None,
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                })
                session["user_id"] = str(result.inserted_id)
                return redirect(url_for("dashboard"))
            except DuplicateKeyError:
                flash("Энэ утсаар бүртгэл үүссэн байна.", "danger")

        return render_template("register.html", phone=display_phone(phone), nickname=nickname)

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = normalize_phone(request.form.get("phone"))
        password = request.form.get("password") or ""
        user = mongo.db.users.find_one({"phone": phone}) if phone else None

        if not user or not check_password_hash(user.get("password_hash", ""), password):
            flash("Утасны дугаар эсвэл нууц үг буруу байна.", "danger")
            return render_template("login.html", phone=display_phone(phone))

        session.clear()
        session["user_id"] = str(user["_id"])
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/watch/<int:video_id>")
def watch_video(video_id):
    video = VIDEO_INDEX.get(
        video_id
    )

    if not video:
        abort(404)

    return render_template(
        "watch.html",
        video=video,
    )
@app.get("/dashboard")
@login_required
def dashboard():
    user = current_user()
    return render_template("dashboard.html", user=user, display_phone=display_phone, is_admin_user=is_admin(user))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()

    if request.method == "POST":
        nickname = (request.form.get("nickname") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        birthdate = (request.form.get("birthdate") or "").strip()
        bio = (request.form.get("bio") or "").strip()

        if not 2 <= len(nickname) <= 50:
            flash("Nickname 2-50 тэмдэгт байна.", "danger")
            return redirect(url_for("profile"))

        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Email буруу байна.", "danger")
            return redirect(url_for("profile"))

        if birthdate:
            try:
                parsed = datetime.strptime(birthdate, "%Y-%m-%d").date()
                if parsed > datetime.now().date():
                    raise ValueError
            except ValueError:
                flash("Төрсөн огноо буруу байна.", "danger")
                return redirect(url_for("profile"))

        if len(bio) > 500:
            flash("Bio 500 тэмдэгтээс ихгүй байна.", "danger")
            return redirect(url_for("profile"))

        update = {
            "$set": {
                "nickname": nickname,
                "birthdate": birthdate or None,
                "bio": bio,
                "updated_at": datetime.utcnow(),
            }
        }

        if email:
            update["$set"]["email"] = email
        else:
            update["$unset"] = {"email": ""}

        try:
            mongo.db.users.update_one({"_id": user["_id"]}, update)
            flash("Profile хадгалагдлаа.", "success")
        except DuplicateKeyError:
            flash("Энэ email өөр хэрэглэгч дээр бүртгэлтэй байна.", "danger")

        return redirect(url_for("profile"))

    return render_template("profile.html", user=user, display_phone=display_phone)


@app.post("/profile/image")
@login_required
def upload_profile_image():
    user = current_user()
    image = request.files.get("profile_image")

    if not image or not image.filename:
        flash("Зураг сонгоно уу.", "danger")
        return redirect(url_for("profile"))

    if request.content_length and request.content_length > PROFILE_IMAGE_MAX_MB * 1024 * 1024:
        flash(f"Зураг {PROFILE_IMAGE_MAX_MB}MB-аас их байна.", "danger")
        return redirect(url_for("profile"))

    ext = image.filename.rsplit(".", 1)[-1].lower() if "." in image.filename else ""
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        flash("JPG, PNG эсвэл WEBP зураг ашиглана уу.", "danger")
        return redirect(url_for("profile"))

    try:
        result = cloudinary.uploader.upload(
            image,
            folder="render_server/profile_images",
            public_id=f"user_{user['_id']}",
            overwrite=True,
            invalidate=True,
            transformation=[
                {"width": 800, "height": 800, "crop": "fill", "gravity": "face"},
                {"quality": PROFILE_IMAGE_QUALITY, "fetch_format": "auto"},
            ],
        )

        mongo.db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {
                "profile_image_url": result.get("secure_url"),
                "profile_image_public_id": result.get("public_id"),
                "updated_at": datetime.utcnow(),
            }}
        )
        flash("Profile зураг шинэчлэгдлээ.", "success")
    except Exception as exc:
        print("Cloudinary upload error:", exc)
        flash("Зураг upload хийхэд алдаа гарлаа.", "danger")

    return redirect(url_for("profile"))


@app.post("/profile/image/remove")
@login_required
def remove_profile_image():
    user = current_user()
    public_id = user.get("profile_image_public_id")

    if public_id:
        try:
            cloudinary.uploader.destroy(public_id, invalidate=True)
        except Exception as exc:
            print("Cloudinary destroy warning:", exc)

    mongo.db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "profile_image_url": None,
            "profile_image_public_id": None,
            "updated_at": datetime.utcnow(),
        }}
    )
    flash("Profile зураг устгагдлаа.", "success")
    return redirect(url_for("profile"))


VIDEO_EXTENSIONS = {"mp4", "mkv", "webm", "mov", "avi", "m4v"}


def save_video_metadata_to_django(payload):
    base_url = os.getenv("DJANGO_API_URL", "").strip()
    if not base_url:
        return {
            "configured": False,
            "saved": False,
            "message": "DJANGO_API_URL тохируулаагүй байна.",
        }

    url = f"{base_url.rstrip('/')}/api/videos/create/"
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("DJANGO_API_KEY", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        try:
            body = response.json()
        except Exception:
            body = {"raw": response.text[:1000]}

        return {
            "configured": True,
            "saved": response.ok,
            "status_code": response.status_code,
            "response": body,
        }
    except Exception as exc:
        return {
            "configured": True,
            "saved": False,
            "error": str(exc),
        }


@app.get("/uploader")
@admin_required
def uploader_page():
    user = current_user()
    return render_template(
        "uploader.html",
        user=user,
        display_phone=display_phone,
        max_upload_mb=MAX_UPLOAD_MB,
        django_configured=bool(os.getenv("DJANGO_API_URL")),
    )


@app.get("/api/admin/anime")
@admin_required
def anime_proxy():
    base_url = os.getenv("DJANGO_API_URL", "").strip()
    if not base_url:
        return jsonify({"ok": False, "error": "DJANGO_API_URL тохируулаагүй байна."}), 503

    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/anime/", timeout=2)
        try:
            data = response.json()
        except Exception:
            data = {"error": response.text[:1000]}
        return jsonify(data), response.status_code
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@app.post("/api/admin/upload-video")
@admin_required
def upload_video():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"ok": False, "error": "Video file сонгоно уу."}), 400

    original_name = os.path.basename(uploaded.filename)
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in VIDEO_EXTENSIONS:
        return jsonify({
            "ok": False,
            "error": "MP4, MKV, WEBM, MOV, AVI эсвэл M4V файл ашиглана уу."
        }), 400

    title = (request.form.get("title") or "").strip()
    anime_id_raw = (request.form.get("anime_id") or "").strip()
    episode_raw = (request.form.get("episode_number") or "").strip()
    duration_raw = (request.form.get("duration") or "").strip()

    if not title:
        return jsonify({"ok": False, "error": "Title заавал оруулна."}), 400

    try:
        anime_id = int(anime_id_raw) if anime_id_raw else None
        episode_number = int(episode_raw) if episode_raw else None
        duration = float(duration_raw) if duration_raw else None
    except ValueError:
        return jsonify({"ok": False, "error": "Anime / Episode / Duration утга буруу байна."}), 400

    temp_path = None
    try:
        suffix = f".{ext}" if ext else ".mp4"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
            temp_path = temp.name
            uploaded.save(temp)

        file_size = os.path.getsize(temp_path)

        duration = get_video_duration(
            temp_path
        )
        caption = title + (f" - EP {episode_number}" if episode_number is not None else "")

        telegram_result = asyncio.run(
            upload_video_to_telegram(temp_path, caption=caption)
        )

        metadata = {
            "anime_id": anime_id,
            "title": title,
            "episode_number": episode_number,
            "telegram_channel_id": telegram_result["channel_id"],
            "telegram_message_id": telegram_result["message_id"],
            "file_name": telegram_result.get("file_name") or original_name,
            "file_size": telegram_result.get("file_size") or file_size,
            "duration": duration,
            "is_uploaded": True,
        }
        djang = send_video_info_to_django(metadata)
        django_result = save_video_metadata_to_django(metadata)

        return jsonify({
            "ok": True,
            "message": "Telegram upload амжилттай.",
            "video": metadata,
            "django": djang,
        }), 201

    except Exception as exc:
        app.logger.exception("Telegram video upload failed")
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass

@app.get("/debug/config")
@admin_required
def debug_config():
    return jsonify({
        "DJANGO_API_URL_set": bool(
            os.getenv("DJANGO_API_URL")
        ),
        "DJANGO_API_URL": os.getenv(
            "DJANGO_API_URL",
            ""
        ),
        "DJANGO_API_KEY_set": bool(
            os.getenv("DJANGO_API_KEY")
        ),
        "TELEGRAM_API_ID_set": bool(
            os.getenv("TELEGRAM_API_ID")
        ),
        "TELEGRAM_CHANNEL_ID_set": bool(
            os.getenv("TELEGRAM_CHANNEL_ID")
        ),
        "TELEGRAM_SESSION_set": bool(
            os.getenv("TELEGRAM_SESSION")
        ),
    })
@app.get("/health")
def health():
    try:
        mongo.cx.admin.command("ping")
        return jsonify({"status": "ok", "database": "mongodb"}), 200
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.errorhandler(413)
def file_too_large(_):
    if request.path.startswith("/api/admin/upload-video"):
        return jsonify({
            "ok": False,
            "error": f"Video файл хэт том байна. MAX_UPLOAD_MB={MAX_UPLOAD_MB} MB.",
        }), 413
    flash(f"Файл хэт том байна. Max {MAX_UPLOAD_MB}MB.", "danger")
    return redirect(request.referrer or url_for("dashboard"))

def get_django_base_url():
    url = os.environ.get("DJANGO_API_URL", "").strip()
    if not url:
        raise RuntimeError("DJANGO_API_URL тохируулаагүй байна.")
    return url.rstrip("/")


def fetch_anime_with_videos():
    base_url = get_django_base_url()
    url = f"{base_url}/api/public/anime-with-videos/"

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    data = response.json()

    return data.get("results", [])

@app.route("/")
def home():
    anime_list = []
    error = ""

    try:
        anime_list = fetch_anime_with_videos()
    except Exception as exc:
        error = str(exc)

    build_video_index(
        anime_list
    )

    return render_template(
        "home.html",
        anime_list=anime_list,
    )
@app.get("/stream/<int:video_id>")
def stream_video(video_id):

    video = VIDEO_INDEX.get(
        video_id
    )

    if not video:
        abort(404)

    channel_id = int(
        video["telegram_channel_id"]
    )

    message_id = int(
        video["telegram_message_id"]
    )

    file_size = int(
        video.get("file_size") or 0
    )

    if file_size <= 0:
        abort(404)

    file_name = video.get(
        "file_name",
        ""
    )

    mime_type = (
        mimetypes.guess_type(
            file_name
        )[0]
        or "video/mp4"
    )

    start = 0
    end = file_size - 1

    range_header = request.headers.get(
        "Range"
    )

    status = 200

    if range_header:

        match = re.match(
            r"bytes=(\d*)-(\d*)",
            range_header,
        )

        if not match:
            return Response(
                status=416,
                headers={
                    "Content-Range":
                    f"bytes */{file_size}"
                },
            )

        start_text = match.group(1)
        end_text = match.group(2)

        if start_text:
            start = int(start_text)

        if end_text:
            end = min(
                int(end_text),
                file_size - 1,
            )

        if start >= file_size:
            return Response(
                status=416,
                headers={
                    "Content-Range":
                    f"bytes */{file_size}"
                },
            )

        status = 206

    content_length = (
        end - start + 1
    )

    headers = {
        "Accept-Ranges": "bytes",

        "Content-Length": str(
            content_length
        ),

        "Cache-Control": (
            "private, no-cache"
        ),
    }

    if status == 206:
        headers[
            "Content-Range"
        ] = (
            f"bytes "
            f"{start}-{end}/"
            f"{file_size}"
        )

    return Response(
        stream_with_context(
            telegram_range_stream(
                channel_id=channel_id,
                message_id=message_id,
                start=start,
                end=end,
            )
        ),
        status=status,
        headers=headers,
        content_type=mime_type,
        direct_passthrough=True,
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5002)), debug=True)
