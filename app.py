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
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "anime_db")

mongo_client = MongoClient(os.getenv("MONGO_URI"))
mongo_db = mongo_client[MONGO_DB_NAME]
videos_collection = mongo_db["videos"]
anime_collection = mongo_db["anime"]

metadata = {
    "anime_id": "123",
    "title": "Episode 1",
    "episode": 1,
    "telegram_channel_id": -1001234567890,
    "telegram_message_id": 55,
    "file_name": "episode_1.mp4",
    "file_size": 123456789,
    "active": True,
}



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
def serialize_anime(anime):
    return {
        "id": str(anime["_id"]),
        "name": anime.get("name", ""),
        "description": anime.get("description", ""),
        "active": anime.get("active", True),

        "anime_type": anime.get("anime_type", "tv"),
        "episodes": anime.get("episodes"),

        "status": anime.get("status", "finished"),

        "aired_from": (
            anime.get("aired_from").strftime("%Y-%m-%d")
            if anime.get("aired_from")
            else ""
        ),

        "aired_to": (
            anime.get("aired_to").strftime("%Y-%m-%d")
            if anime.get("aired_to")
            else ""
        ),

        "premiered": anime.get("premiered", ""),
        "broadcast": anime.get("broadcast", ""),
        "producers": anime.get("producers", ""),
        "licensors": anime.get("licensors", ""),
        "studios": anime.get("studios", ""),

        "image_url": anime.get("image_url", ""),
        "image_public_id": anime.get("image_public_id", ""),
    }

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

@app.get("/watch/<video_id>")
def watch_video(video_id):

    if not ObjectId.is_valid(video_id):
        abort(404)

    video = videos_collection.find_one({
        "_id": ObjectId(video_id),
        "is_uploaded": True,
    })

    if not video:
        abort(404)

    video["id"] = str(
        video["_id"]
    )

    anime = None

    anime_id = video.get(
        "anime_id"
    )

    if anime_id:

        anime = anime_collection.find_one({
            "_id": anime_id
        })

        if anime:
            anime["id"] = str(
                anime["_id"]
            )

    return render_template(
        "watch.html",
        video=video,
        anime=anime,
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


from bson import ObjectId
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
    print("🐍 File: render_server/app.py | Line: 490 | upload_video ~ anime_id_raw",anime_id_raw)
    episode_raw = (request.form.get("episode_number") or "").strip()
    duration_raw = (request.form.get("duration") or "").strip()

    if not title:
        return jsonify({"ok": False, "error": "Title заавал оруулна."}), 400

    try:
        anime_id = ObjectId(anime_id_raw) if anime_id_raw else None
        episode_number = int(episode_raw) if episode_raw else None
        #duration = float(duration_raw) if duration_raw else None
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
        print("🐍 File: render_server/app.py | Line: 515 | upload_video ~ duration",duration)
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
        #djang = send_video_info_to_django(metadata)
        djang = send_video_info_to_mongodb(metadata,videos_collection)
        print("✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️")
        print("SUCCESSFULLY UPLOADED",djang)
        print("▶️▶️▶️▶️▶️▶️▶️▶️▶️▶️▶️▶️▶️▶️▶️▶️")
        #django_result = save_video_metadata_to_django(metadata)

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
    anime_list = list(
        anime_collection.find(
            {
                "active": True
            }
        ).sort(
            "created_at",
            -1
        )
    )

    for anime in anime_list:
        anime["id"] = str(anime["_id"])

    return render_template(
        "home.html",
        anime_list=anime_list,
    )

@app.route("/anime/<anime_id>")
def anime_detail(anime_id):

    if not ObjectId.is_valid(anime_id):
        abort(404)

    anime_object_id = ObjectId(anime_id)

    anime = anime_collection.find_one({
        "_id": anime_object_id,
        "active": True,
    })

    if not anime:
        abort(404)

    anime["id"] = str(anime["_id"])

    videos = list(
        videos_collection.find(
            {
                "anime_id": anime_object_id,
               
            }
        ).sort(
            "episode_number",
            1
        )
    )

    for video in videos:
        video["id"] = str(video["_id"])

    return render_template(
        "anime_detail.html",
        anime=anime,
        videos=videos,
    )


@app.get("/stream/<video_id>")
def stream_video(video_id):

    # =====================================================
    # 1. MONGODB VIDEO FIND
    # =====================================================

    if not ObjectId.is_valid(video_id):
        abort(404)

    video = videos_collection.find_one({
        "_id": ObjectId(video_id),
        "is_uploaded": True,
    })

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


TYPE_CHOICES = [
    ("tv", "TV"),
    ("movie", "Movie"),
    ("ova", "OVA"),
    ("ona", "ONA"),
    ("special", "Special"),
    ("music", "Music"),
]


STATUS_CHOICES = [
    ("finished", "Finished Airing"),
    ("airing", "Currently Airing"),
    ("not_yet_aired", "Not Yet Aired"),
]


def parse_date(value):
    if not value:
        return None

    return datetime.strptime(
        value,
        "%Y-%m-%d"
    )
@app.route("/api/admin/anime", methods=["GET"])
def api_admin_anime():
    try:

        anime_list = anime_collection.find(
            {}
        ).sort(
            "created_at",
            -1
        )

        results = [
            serialize_anime(anime)
            for anime in anime_list
        ]

        return jsonify({
            "ok": True,
            "results": results,
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500
@app.route(
    "/api/admin/anime/image-upload",
    methods=["POST"],
)
def anime_image_upload():

    try:

        file = request.files.get("image")

        if not file:
            return jsonify({
                "ok": False,
                "error": "Зураг сонгоогүй байна.",
            }), 400

        upload_result = cloudinary.uploader.upload(
            file,
            folder="anime/posters",
            resource_type="image",

            transformation=[
                {
                    "quality": "auto",
                    "fetch_format": "auto",
                }
            ],
        )

        return jsonify({
            "ok": True,
            "image_url": upload_result.get(
                "secure_url"
            ),
            "public_id": upload_result.get(
                "public_id"
            ),
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500

# =========================================================
# PAGE
# =========================================================

@app.route("/anime/create")
def anime_create_page():
    return render_template(
        "anime_create.html"
    )


@app.route(
    "/api/admin/anime/create",
    methods=["POST"],
)
def api_anime_create():

    try:

        data = request.get_json() or {}

        name = (
            data.get("name") or ""
        ).strip()

        if not name:
            return jsonify({
                "ok": False,
                "error": "Anime нэр заавал оруулна.",
            }), 400

        episodes = data.get("episodes")

        if episodes in ["", None]:
            episodes = None
        else:
            episodes = int(episodes)

        now = datetime.now(timezone.utc)

        anime_data = {

            "name": name,

            "description": (
                data.get("description") or ""
            ).strip(),

            "active": bool(
                data.get("active", True)
            ),

            "anime_type": data.get(
                "anime_type",
                "tv"
            ),

            "episodes": episodes,

            "status": data.get(
                "status",
                "finished"
            ),

            "aired_from": parse_date(
                data.get("aired_from")
            ),

            "aired_to": parse_date(
                data.get("aired_to")
            ),

            "premiered": (
                data.get("premiered") or ""
            ).strip(),

            "broadcast": (
                data.get("broadcast") or ""
            ).strip(),

            "producers": (
                data.get("producers") or ""
            ).strip(),

            "licensors": (
                data.get("licensors") or ""
            ).strip(),

            "studios": (
                data.get("studios") or ""
            ).strip(),

            "image_url": (
                data.get("image_url") or ""
            ).strip(),

            "image_public_id": (
                data.get("image_public_id") or ""
            ).strip(),

            "created_at": now,
            "updated_at": now,
        }

        result = anime_collection.insert_one(
            anime_data
        )

        return jsonify({
            "ok": True,
            "id": str(result.inserted_id),
            "message": "Anime амжилттай бүртгэгдлээ.",
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500


# =========================================================
# UPDATE
# =========================================================

@app.route(
    "/api/admin/anime/<anime_id>",
    methods=["PUT"],
)
def api_anime_update(anime_id):

    try:

        if not ObjectId.is_valid(anime_id):
            return jsonify({
                "ok": False,
                "error": "Anime ID буруу байна.",
            }), 400

        anime = anime_collection.find_one({
            "_id": ObjectId(anime_id)
        })

        if not anime:
            return jsonify({
                "ok": False,
                "error": "Anime олдсонгүй.",
            }), 404

        data = request.get_json() or {}

        episodes = data.get("episodes")

        if episodes in ["", None]:
            episodes = None
        else:
            episodes = int(episodes)

        # -----------------------------------------
        # зураг солигдсон бол хуучныг Cloudinary-с устгах
        # -----------------------------------------

        new_public_id = (
            data.get("image_public_id")
            or ""
        ).strip()

        old_public_id = anime.get(
            "image_public_id",
            ""
        )

        if (
            new_public_id
            and old_public_id
            and new_public_id != old_public_id
        ):
            try:
                cloudinary.uploader.destroy(
                    old_public_id
                )
            except Exception as image_error:
                print(
                    "Old image delete error:",
                    image_error
                )

        update_data = {

            "name": (
                data.get("name") or ""
            ).strip(),

            "description": (
                data.get("description") or ""
            ).strip(),

            "active": bool(
                data.get("active", True)
            ),

            "anime_type": data.get(
                "anime_type",
                "tv"
            ),

            "episodes": episodes,

            "status": data.get(
                "status",
                "finished"
            ),

            "aired_from": parse_date(
                data.get("aired_from")
            ),

            "aired_to": parse_date(
                data.get("aired_to")
            ),

            "premiered": (
                data.get("premiered") or ""
            ).strip(),

            "broadcast": (
                data.get("broadcast") or ""
            ).strip(),

            "producers": (
                data.get("producers") or ""
            ).strip(),

            "licensors": (
                data.get("licensors") or ""
            ).strip(),

            "studios": (
                data.get("studios") or ""
            ).strip(),

            "image_url": (
                data.get("image_url") or ""
            ).strip(),

            "image_public_id": new_public_id,

            "updated_at":
                datetime.now(timezone.utc),
        }

        anime_collection.update_one(
            {
                "_id": ObjectId(anime_id)
            },
            {
                "$set": update_data
            }
        )

        return jsonify({
            "ok": True,
            "message": "Anime мэдээлэл шинэчлэгдлээ.",
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500


# =========================================================
# DELETE
# =========================================================

@app.route(
    "/api/admin/anime/<anime_id>",
    methods=["DELETE"],
)
def api_anime_delete(anime_id):

    try:

        if not ObjectId.is_valid(anime_id):
            return jsonify({
                "ok": False,
                "error": "Anime ID буруу байна.",
            }), 400

        anime_object_id = ObjectId(
            anime_id
        )

        anime = anime_collection.find_one({
            "_id": anime_object_id
        })

        if not anime:
            return jsonify({
                "ok": False,
                "error": "Anime олдсонгүй.",
            }), 404

        # Энэ anime дээр video байгаа эсэх
        video_count = videos_collection.count_documents({
            "anime_id": anime_object_id
        })

        if video_count > 0:
            return jsonify({
                "ok": False,
                "error": (
                    f"Энэ Anime дээр {video_count} video байна. "
                    "Video-уудаа эхлээд устгана уу."
                ),
            }), 409

        public_id = anime.get(
            "image_public_id"
        )

        if public_id:
            try:
                cloudinary.uploader.destroy(
                    public_id
                )
            except Exception as image_error:
                print(
                    "Cloudinary delete error:",
                    image_error
                )

        anime_collection.delete_one({
            "_id": anime_object_id
        })

        return jsonify({
            "ok": True,
            "message": "Anime устгагдлаа.",
        })

    except Exception as e:

        return jsonify({
            "ok": False,
            "error": str(e),
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5002)), debug=True)
