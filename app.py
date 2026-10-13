import os, re, asyncio, tempfile
from datetime import datetime
from functools import wraps
from pathlib import Path
from uuid import uuid4
from bson.objectid import ObjectId
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify,current_app,Blueprint,abort
import secrets, time
from flask_pymongo import PyMongo
from werkzeug.utils import secure_filename
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
import requests
from pymongo import MongoClient, ReturnDocument
from uploader import upload_video_to_telegram,upload_file_to_telegram
import io
import cloudinary
from PIL import Image, ImageOps
import random
import cloudinary.api
import cloudinary.uploader
import mimetypes
import re,threading
from datetime import datetime, timedelta,date
from flask import (
    Response,
    abort,
    request,
    stream_with_context,
)

from pymongo.errors import DuplicateKeyError
from uploader import (
    telegram_range_stream,
)
from flask_session import Session
load_dotenv()
def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)
app = Flask(__name__, static_url_path='/static')
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "2048"))
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/render_server")
mongo_client = MongoClient(os.getenv("MONGO_URI"))
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "anime_db")

paylink_url = os.getenv("paylink_url", "")
from utils import *
app.config["SESSION_TYPE"] = "mongodb"
app.config["SESSION_MONGODB"] = mongo_client
app.config["SESSION_MONGODB_DB"] = MONGO_DB_NAME
app.config["SESSION_MONGODB_COLLECT"] = "flask_sessions"

app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=2)

app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY",'1234qwerasdfzxcvuiop')

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

Session(app)
PROFILE_IMAGE_MAX_MB = 5

api_key_verify=os.getenv("api_key_verify", "")
verify_url=os.getenv("verify_url",'')

mongo_db = mongo_client[MONGO_DB_NAME]
# * MONGO DB COLLECTIONS >>--- --- -- -> >>--- --- -- -> >>--- --- -- -> >>--- --- -- -> >>--- --- -- -> >>--- --- -- -> >>--- --- -- -> 

videos_collection = mongo_db["videos"]
anime_collection = mongo_db["anime"]
files_collection = mongo_db["files"]
home_comments_collection = mongo_db["home_comments"]
zip_files = mongo_db["zip_files"]
watch_history_collection = mongo_db['watch_history']
users_collection = mongo_db.users
genres_collection = mongo_db.genres
home_slides_collection = mongo_db.home_slides
DOWNLOAD_CATEGORIES = {
    "game", "software", "application",
    "document", "ebook", "other"
}

MAX_COVER_SIZE = 5 * 1024 * 1024
ACTIVE_TTL = 90 
MAX_CONN = 3
ACTIVE = {}                  # token -> тоо
ACTIVE_LOCK = threading.Lock()

ALLOWED_FILE_EXTENSIONS = {
    ".pdf",
    ".rar",
    ".zip",
}
def allowed_upload_file(
    filename
):
    extension = (
        Path(filename)
        .suffix
        .lower()
    )

    return (
        extension
        in ALLOWED_FILE_EXTENSIONS
    )

def acquire(token):
    with ACTIVE_LOCK:
        print("🎉🎉🎍🎍 | Line: 117 CONN_COUNT",ACTIVE.get(token, 0))
        if ACTIVE.get(token, 0) >= MAX_CONN:
            
            return False
        ACTIVE[token] = ACTIVE.get(token, 0) + 1
        return True

def release(token):
    with ACTIVE_LOCK:
        n = ACTIVE.get(token, 0) - 1
        if n <= 0:
            ACTIVE.pop(token, None)
        else:
            ACTIVE[token] = n

def guarded(gen, token):
    try:
        yield from gen
    finally:
        release(token)   
def allowed_file(filename):

    ext = os.path.splitext(
        filename
    )[1].lower()

    return ext in ALLOWED_FILE_EXTENSIONS

home_slides_collection.create_index(
    [
        ("active", 1),
        ("sequence", 1),
    ]
)
genres_collection.create_index(
    "name",
    unique=True,
)

pending_auth_collection = mongo_db.pending_auth
# Утасны дугаар давхардахгүй.
users_collection.create_index(
    "phone",
    unique=True,
)
pending_auth_collection.create_index(
    "expires_at",
    expireAfterSeconds=0,
)
def parse_iso_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )
    except Exception:
        return None


def valid_phone(phone):
    return bool(
        re.fullmatch(
            r"\d{8}",
            phone,
        )
    )
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

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

config = cloudinary.config()
print("CLOUDINARY_URL:", bool(os.getenv("CLOUDINARY_URL")))
print("API key loaded:", bool(config.api_key))
print("API secret loaded:", bool(config.api_secret))

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
def serialize_anime(anime):
    genre_ids = anime.get(
        "genre_ids",
        []
    )
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
        "genre_ids": [
            str(genre_id)
            for genre_id in genre_ids
        ],
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
    import re

    phone = str(phone or "").strip()

    # +, space, -, () гэх мэт бүгдийг авна
    phone = re.sub(r"\D", "", phone)

    # +97685963616 -> 97685963616
    # 97685963616 -> 85963616
    if phone.startswith("976") and len(phone) == 11:
        phone = phone[3:]

    # Mongo-д хадгалах final format
    if len(phone) != 8:
        return None

    return f"+976{phone}"

def display_phone(phone):
    return phone[4:] if phone and phone.startswith("+976") else (phone or "")

import random

def get_random_anonymous_avatar():
    avatars = [
        'https://res.cloudinary.com/gchtspsh/image/upload/v1791511351/girl.png',
        'https://res.cloudinary.com/gchtspsh/image/upload/v1791511349/ghost.png',
        'https://res.cloudinary.com/gchtspsh/image/upload/v1791511350/sailor.png',
        'https://res.cloudinary.com/gchtspsh/image/upload/v1791511348/schoolgirl.png',
        'https://res.cloudinary.com/gchtspsh/image/upload/v1791511348/student.png',
        'https://res.cloudinary.com/gchtspsh/image/upload/v1791511347/woman.png',
        'https://res.cloudinary.com/gchtspsh/image/upload/v1791511347/woman_1.png',
        'https://res.cloudinary.com/gchtspsh/image/upload/v1791511347/student_1.png',
        'https://res.cloudinary.com/gchtspsh/image/upload/v1791511346/nerd.png',
        'https://res.cloudinary.com/gchtspsh/image/upload/v1791511346/otaku.png'
    ]
    
    return random.choice(avatars)

def get_random_video_screenshot(video_path, duration):
    if not duration or float(duration) <= 240:
        return None

    second = random.randint(240, min(480, int(float(duration)) - 1))

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-ss", str(second),
                "-i", video_path,
                "-frames:v", "1",
                "-vf", "scale=1280:-2",
                "-q:v", "5",
                "-f", "image2pipe",
                "-vcodec", "mjpeg",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=45,
            check=True,
        )

        if result.stdout:
            return {
                "second": second,
                "image_bytes": result.stdout,
            }

    except (subprocess.SubprocessError, OSError) as exc:
        print("Screenshot error:", exc)

    return None

def admin_phones():
    raw = os.getenv("ADMIN_PHONES", "85963616,88961331")
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
import uuid

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

def get_current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    try:
        return users_collection.find_one(
            {
                "_id": ObjectId(user_id),
            }
        )
    except Exception:
        return None
@app.route("/admin/home-slides")
def home_slides_admin_page():

    return render_template(
        "home_slides_admin.html"
    )

@app.route(
    "/api/admin/home-slides",
    methods=["GET"],
)

def upload_image_to_cloudinary(
    image_bytes,
    folder_name="anime_screenshots",
    image_format="webp",
    compress=True,
    quality=75,
    max_width=1280,
):
    try:
        if image_format not in ("webp", "original"):
            raise ValueError("image_format нь webp эсвэл original байна.")

        image = Image.open(io.BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image)
        original_format = (image.format or "JPEG").upper()

        if original_format not in ("JPEG", "PNG", "WEBP"):
            original_format = "PNG"

        if compress and image.width > max_width:
            new_height = round(image.height * max_width / image.width)
            image = image.resize(
                (max_width, new_height),
                Image.Resampling.LANCZOS
            )

        output = io.BytesIO()

        if image_format == "webp":
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

            image.save(
                output,
                format="WEBP",
                quality=quality if compress else 100,
                method=6,
                lossless=not compress,
            )
            extension = "webp"

        else:
            if original_format == "JPEG":
                if image.mode != "RGB":
                    image = image.convert("RGB")

                image.save(
                    output,
                    format="JPEG",
                    quality=quality if compress else 95,
                    optimize=True,
                )
                extension = "jpg"

            elif original_format == "PNG":
                image.save(
                    output,
                    format="PNG",
                    optimize=compress,
                )
                extension = "png"

            else:
                image.save(
                    output,
                    format="WEBP",
                    quality=quality if compress else 100,
                    method=6,
                    lossless=not compress,
                )
                extension = "webp"

        output.seek(0)
        processed_bytes = output.getvalue()

        result = cloudinary.uploader.upload(
            processed_bytes,
            folder=folder_name,
            public_id=f"img_{uuid4().hex}",
            resource_type="image",
            format=extension,
            overwrite=False,
        )

        return {
            "url": result["secure_url"],
            "public_id": result["public_id"],
            "format": extension,
            "size": len(processed_bytes),
        }

    except Exception as exc:
        print("Cloudinary image upload error:", exc)
        return None

def api_home_slides_list():

    slides = list(
        home_slides_collection.find(
            {}
        ).sort(
            [
                ("sequence", 1),
                ("_id", -1),
            ]
        )
    )

    results = []

    for slide in slides:

        results.append({
            "id": str(
                slide["_id"]
            ),

            "title":
                slide.get(
                    "title",
                    ""
                ),

            "subtitle":
                slide.get(
                    "subtitle",
                    ""
                ),

            "image_url":
                slide.get(
                    "image_url",
                    ""
                ),

            "image_public_id":
                slide.get(
                    "image_public_id",
                    ""
                ),

            "link_url":
                slide.get(
                    "link_url",
                    ""
                ),

            "sequence":
                slide.get(
                    "sequence",
                    10
                ),

            "active":
                slide.get(
                    "active",
                    True
                ),
        })

    return jsonify({
        "ok": True,
        "results": results,
    })

@app.route(
    "/api/admin/home-slides/create",
    methods=["POST"],
)
def api_home_slide_create():

    data = request.get_json(
        silent=True
    ) or {}

    image_url = str(
        data.get("image_url")
        or ""
    ).strip()

    if not image_url:

        return jsonify({
            "ok": False,
            "error": "Banner зураг оруулна уу.",
        }), 400


    title = str(
        data.get("title")
        or ""
    ).strip()

    subtitle = str(
        data.get("subtitle")
        or ""
    ).strip()

    link_url = str(
        data.get("link_url")
        or ""
    ).strip()

    image_public_id = str(
        data.get("image_public_id")
        or ""
    ).strip()


    try:

        sequence = int(
            data.get(
                "sequence",
                10
            )
            or 10
        )

    except Exception:

        sequence = 10


    now = utcnow()


    result = home_slides_collection.insert_one({
        "title": title,

        "subtitle": subtitle,

        "image_url": image_url,

        "image_public_id":
            image_public_id,

        "link_url": link_url,

        "sequence": sequence,

        "active": bool(
            data.get(
                "active",
                True
            )
        ),

        "created_at": now,

        "updated_at": now,
    })


    return jsonify({
        "ok": True,

        "id": str(
            result.inserted_id
        ),
    })


@app.route(
    "/api/admin/home-slides/<slide_id>",
    methods=["PUT"],
)
def api_home_slide_update(
    slide_id
):

    if not ObjectId.is_valid(
        slide_id
    ):

        return jsonify({
            "ok": False,
            "error": "Slide ID буруу байна.",
        }), 400


    data = request.get_json(
        silent=True
    ) or {}


    image_url = str(
        data.get("image_url")
        or ""
    ).strip()


    if not image_url:

        return jsonify({
            "ok": False,
            "error": "Banner зураг оруулна уу.",
        }), 400


    try:

        sequence = int(
            data.get(
                "sequence",
                10
            )
            or 10
        )

    except Exception:

        sequence = 10


    result = home_slides_collection.update_one(
        {
            "_id": ObjectId(
                slide_id
            )
        },

        {
            "$set": {

                "title":
                    str(
                        data.get("title")
                        or ""
                    ).strip(),

                "subtitle":
                    str(
                        data.get("subtitle")
                        or ""
                    ).strip(),

                "image_url":
                    image_url,

                "image_public_id":
                    str(
                        data.get(
                            "image_public_id"
                        )
                        or ""
                    ).strip(),

                "link_url":
                    str(
                        data.get("link_url")
                        or ""
                    ).strip(),

                "sequence":
                    sequence,

                "active":
                    bool(
                        data.get(
                            "active",
                            True
                        )
                    ),

                "updated_at":
                    utcnow(),
            }
        }
    )


    if not result.matched_count:

        return jsonify({
            "ok": False,
            "error": "Slide олдсонгүй.",
        }), 404


    return jsonify({
        "ok": True,
    })

@app.route(
    "/api/admin/home-slides/<slide_id>",
    methods=["DELETE"],
)
def api_home_slide_delete(
    slide_id
):

    if not ObjectId.is_valid(
        slide_id
    ):

        return jsonify({
            "ok": False,
            "error": "Slide ID буруу байна.",
        }), 400


    slide = home_slides_collection.find_one(
        {
            "_id": ObjectId(
                slide_id
            )
        }
    )


    if not slide:

        return jsonify({
            "ok": False,
            "error": "Slide олдсонгүй.",
        }), 404


    # Хэрэв Cloudinary дээрх хуучин зургийг
    # delete хийхийг хүсвэл энд public_id-аар устгаж болно.
    #
    # public_id = slide.get("image_public_id")
    #
    # if public_id:
    #     cloudinary.uploader.destroy(public_id)


    home_slides_collection.delete_one(
        {
            "_id": ObjectId(
                slide_id
            )
        }
    )


    return jsonify({
        "ok": True,
    })

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


@app.route("/login")
def login():

    if get_current_user():
        return redirect(
            url_for("home")
        )

    return render_template(
        "login.html"
    )

@app.route(
    "/auth/start",
    methods=["POST"],
)
def auth_start():

    raw_phone = request.form.get("phone")

    phone = normalize_phone(raw_phone)

    if not phone:
        return render_template(
            "login.html",
            error="Утасны дугаар буруу байна.",
            phone=raw_phone,
        )

    # +97685963616 -> 85963616
    verify_phone = phone[4:]
    print("🐍 File: render_server/app.py | Line: 352 | auth_start ~ verify_phone",verify_phone)

    try:

        # ====================================================
        # VERIFY.MN CREATE SESSION
        # ====================================================

        result = verify_create_session(
            verify_phone,
            None,
            verify_url,
            api_key_verify,
        )


    except Exception as e:

        print(
            "VERIFY CREATE ERROR:",
            e,
        )

        return render_template(
            "login.html",
            error="Баталгаажуулах хүсэлт үүсгэж чадсангүй.",
            phone=phone,
        )

    if not isinstance(result, dict):

        return render_template(
            "login.html",
            error="VERIFY.MN буруу хариу буцаалаа.",
            phone=phone,
        )

    verify_session_id = result.get(
        "sessionId"
    )
    if str(phone) in admin_phones():
        verify_session_id = '98590f15-ffdb-4c7f-bf8b-ae3478938785'
    if not verify_session_id:

        return render_template(
            "login.html",
            error=(
                result.get("message")
                or
                "Session ID олдсонгүй."
            ),
            phone=phone,
        )

    # Browser-д VERIFY sessionId өгөхгүй.
    pending_id = str(
        uuid.uuid4()
    )

    expires_at = parse_iso_datetime(
        result.get("expiresAt")
    )

    if not expires_at:

        # API expiry өгөөгүй тохиолдолд
        # production дээр өөр timeout тавьж болно.
        expires_at = utcnow()

    pending_auth_collection.insert_one(
        {
            "_id": pending_id,

            "phone": phone,

            # VERIFY.MN-ийн session id
            "verify_session_id": verify_session_id,

            "shortcode": result.get(
                "shortcode"
            ),

            "text": result.get(
                "text"
            ),

            "sms_uri": result.get(
                "smsUri"
            ),

            "display_instruction": result.get(
                "displayInstruction"
            ),

            "expires_at": expires_at,

            "created_at": utcnow(),

            "status": "PENDING",

            "last_verify_status": None,
        }
    )

    return redirect(
        url_for(
            "verify_page",
            pending_id=pending_id,
        )
    )

@app.route(
    "/auth/verify/<pending_id>"
)
def verify_page(pending_id):

    pending = pending_auth_collection.find_one(
        {
            "_id": pending_id,
        }
    )

    if not pending:

        return redirect(
            url_for("login")
        )

    if pending.get("status") == "VERIFIED":

        if get_current_user():

            return redirect(
                url_for("home")
            )

    expires_at = pending.get(
        "expires_at"
    )

    if (
        expires_at
        and
        expires_at <= utcnow()
    ):

        pending_auth_collection.update_one(
            {
                "_id": pending_id,
            },
            {
                "$set": {
                    "status": "EXPIRED",
                }
            },
        )

        return render_template(
            "login.html",
            error=(
                "Баталгаажуулах хугацаа дууссан. "
                "Дахин оролдоно уу."
            ),
        )

    return render_template(
        "verify.html",

        pending_id=pending_id,

        phone=pending.get(
            "phone"
        ),

        shortcode=pending.get(
            "shortcode"
        ),

        text=pending.get(
            "text"
        ),

        sms_uri=pending.get(
            "sms_uri"
        ),

        display_instruction=pending.get(
            "display_instruction"
        ),

        expires_at=(
            expires_at.isoformat()
            if expires_at
            else ""
        ),
    )


# ============================================================
# CHECK VERIFY STATUS
# ============================================================

@app.route(
    "/auth/status/<pending_id>",
    methods=["GET"],
)
def auth_status(pending_id):

    pending = pending_auth_collection.find_one(
        {
            "_id": pending_id,
        }
    )

    if not pending:

        return jsonify(
            {
                "success": False,
                "status": "NOT_FOUND",
                "message": "Login хүсэлт олдсонгүй.",
            }
        ), 404

    if pending.get("status") == "EXPIRED":

        return jsonify(
            {
                "success": False,
                "status": "EXPIRED",
            }
        )

    expires_at = pending.get(
        "expires_at"
    )

    if (
        expires_at
        and
        expires_at <= utcnow()
    ):

        pending_auth_collection.update_one(
            {
                "_id": pending_id,
            },
            {
                "$set": {
                    "status": "EXPIRED",
                }
            },
        )

        return jsonify(
            {
                "success": False,
                "status": "EXPIRED",
                "message": "Хугацаа дууссан.",
            }
        )

    verify_session_id = pending.get(
        "verify_session_id"
    )
    #print("🐍 File: render_server/app.py | Line: 621 | auth_status ~ verify_session_id",verify_session_id)

    if not verify_session_id:

        return jsonify(
            {
                "success": False,
                "status": "INVALID",
            }
        ), 400

    try:

    # ====================================================
    # NORMALIZE PHONE
        # ====================================================

        phone = str(
            pending.get("phone") or ""
        ).strip()


        # admin_phones() дотор int/string аль нь байсан
        # адилхан string болгож шалгана
        admin_phone_list = [
            str(p).strip()
            for p in admin_phones()
        ]

        print(
            "AUTH STATUS PHONE >>>",
            phone,
        )

        print(
            "ADMIN PHONES >>>",
            admin_phone_list,
        )

        # ====================================================
        # ADMIN TEST LOGIN
        # ====================================================

        if phone in admin_phone_list:

            print(
                "ADMIN TEST VERIFY >>>",
                phone,
            )

            result = {
                "sessionId": verify_session_id,
                "sessionStatus": "VERIFIED",
                "callbackStatus": "SENT",
                "verifiedAt": utcnow().isoformat(),
                "expiresAt": None,
            }

        # ====================================================
        # REAL VERIFY.MN
        # ====================================================

        else:

            result = verify_msg_log(
                verify_session_id,
                verify_url,
            )

        print(
            "VERIFY STATUS >>>>>>>>>>>>>>",
            result,
        )

    except Exception as e:

        print(
            "VERIFY STATUS ERROR:",
            e,
        )

        return jsonify(
            {
                "success": False,
                "status": "ERROR",
                "message": "VERIFY.MN шалгалт амжилтгүй.",
            }
        ), 500

    if not isinstance(result, dict):

        return jsonify(
            {
                "success": False,
                "status": "ERROR",
            }
        )

    verify_status = result.get(
        "sessionStatus"
    )

    pending_auth_collection.update_one(
        {
            "_id": pending_id,
        },
        {
            "$set": {
                "last_verify_status": verify_status,
                "last_checked_at": utcnow(),
            }
        },
    )

    # ========================================================
    # NOT VERIFIED YET
    # ========================================================

    if verify_status != "VERIFIED":

        return jsonify(
            {
                "success": False,
                "verified": False,
                "status": (
                    verify_status
                    or
                    "PENDING"
                ),
            }
        )

    # ========================================================
    # ATOMIC CONSUME
    # ========================================================
    #
    # Нэг VERIFY session-ээр олон browser login хийхээс хамгаална.
    # ========================================================

    consumed = pending_auth_collection.find_one_and_update(
        {
            "_id": pending_id,
            "status": "PENDING",
        },
        {
            "$set": {
                "status": "VERIFIED",
                "verified_at": utcnow(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    

    if not consumed:

        return jsonify(
            {
                "success": False,
                "status": "ALREADY_USED",
            }
        ), 409

    phone = consumed.get(
        "phone"
    )

    now = utcnow()

    # ========================================================
    # CREATE / UPDATE USER
    # ========================================================

    user = users_collection.find_one(
        {
            "phone": phone,
        }
    )
    # ========================================================
    # FLASK LOGIN SESSION
    # ========================================================
    if user:
        session.clear()

        session.permanent = True

        session["user_id"] = str(
            user["_id"]
        )

        session["phone"] = phone

        session["authenticated"] = True

        users_collection.update_one(
            {
                "_id": user["_id"],
            },
            {
                "$set": {
                    "last_login_at": utcnow(),
                }
            },
        )
        return jsonify(
            {
                "success": True,
                "verified": True,
                "status": "VERIFIED",
                "redirect": url_for("home"),
            }
        )
    # ========================================================
    # 2. ШИНЭ ХЭРЭГЛЭГЧ
    # ========================================================
    #
    # ОДООХОНДОО users collection-д үүсгэхгүй.
    # VERIFY болсон утсыг session-д түр хадгална.
    # ========================================================

    session.clear()

    session["phone_verified"] = True
    session["verified_phone"] = phone
    session["registration_pending"] = True

    return jsonify(
        {
            "success": True,
            "verified": True,
            "status": "VERIFIED",
            "is_new_user": True,
            "redirect": url_for(
                "setup_nickname"
            ),
        }
    )


@app.route(
    "/setup-nickname",
    methods=["GET", "POST"],
)
def setup_nickname():

    # =====================================================
    # ЗӨВХӨН VERIFY ХИЙСЭН ШИНЭ USER ОРОХ ЭРХТЭЙ
    # =====================================================

    if not session.get("phone_verified"):

        return redirect(
            url_for("login")
        )

    if not session.get("registration_pending"):

        return redirect(
            url_for("login")
        )


    phone = session.get(
        "verified_phone"
    )

    if not phone:

        session.clear()

        return redirect(
            url_for("login")
        )


    # =====================================================
    # ДАХИН ШАЛГАНА
    # =====================================================

    existing_user = users_collection.find_one(
        {
            "phone": phone,
        }
    )

    if existing_user:

        # Хэрэв зэрэгцээ request-ээр user аль хэдийн үүссэн бол
        # шууд login болгоно.

        session.clear()

        session.permanent = True

        session["user_id"] = str(
            existing_user["_id"]
        )

        session["phone"] = phone

        session["nickname"] = existing_user.get(
            "nickname"
        )

        session["authenticated"] = True

        return redirect(
            url_for("home")
        )


    # =====================================================
    # GET
    # =====================================================

    if request.method == "GET":

        return render_template(
            "setup_nickname.html",
            phone=phone,
        )


    # =====================================================
    # POST
    # =====================================================

    nickname = str(
        request.form.get("nickname")
        or ""
    ).strip()


    # =====================================================
    # VALIDATION
    # =====================================================

    if len(nickname) < 3:

        return render_template(
            "setup_nickname.html",
            phone=phone,
            nickname=nickname,
            error="Nickname хамгийн багадаа 3 тэмдэгт байна.",
        )


    if len(nickname) > 30:

        return render_template(
            "setup_nickname.html",
            phone=phone,
            nickname=nickname,
            error="Nickname хамгийн ихдээ 30 тэмдэгт байна.",
        )


    # =====================================================
    # NICKNAME ДАВХАРДСАН ЭСЭХ
    # =====================================================

    import re

    nickname_exists = users_collection.find_one(
        {
            "nickname": {
                "$regex": (
                    "^"
                    + re.escape(nickname)
                    + "$"
                ),
                "$options": "i",
            }
        }
    )

    if nickname_exists:

        return render_template(
            "setup_nickname.html",
            phone=phone,
            nickname=nickname,
            error="Энэ nickname аль хэдийн ашиглагдаж байна.",
        )


    # =====================================================
    # USER CREATE
    # =====================================================

    now = utcnow()

    new_user = {
        "phone": phone,
        "nickname": nickname,

        # Password шаардлагагүй.
        # password_hash field үүсгэхгүй.

        "created_at": now,
        "last_login_at": now,

        "is_active": True,

        "auth_method": "phone",
    }


    result = users_collection.insert_one(
        new_user
    )


    # =====================================================
    # LOGIN SESSION
    # =====================================================

    session.clear()

    session.permanent = True

    session["user_id"] = str(
        result.inserted_id
    )

    session["phone"] = phone

    session["nickname"] = nickname

    session["authenticated"] = True

    session["authenticated_at"] = (
        now.isoformat()
    )


    return redirect(
        url_for("home")
    )

def _get_json():
    # sendBeacon нь text/plain илгээдэг тул force=True
    return request.get_json(force=True, silent=True) or {}

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/playback/ping", methods=["POST"])
def playback_ping():
    user = get_current_user()
    if not user:
        return "", 401
    res = users_collection.update_one(
        {"_id": user["_id"], "playback.token": _get_json().get("t")},
        {"$set": {"playback.last_seen": time.time()}}
    )

    if res.matched_count:
        return jsonify(reason="ok"), 200
    return jsonify(reason="stale"), 409

@app.route("/playback/end", methods=["POST"])
def playback_end():
    user = get_current_user()
    if not user:
        return "", 204
    users_collection.update_one(
        {"_id": user["_id"], "playback.token": _get_json().get("t")},
        {"$unset": {"playback": ""}}
    )
    return "", 204

def save_watch_history(user, video):
    anime_id = video.get("anime_id")
    if not anime_id:
        return
   
    watch_history_collection.update_one(
        {"user_id": user["_id"], "anime_id": anime_id},
        {
            "$set": {
                "video_id": video["_id"],
                "watched_at": time.time(),
            },
            "$setOnInsert": {
                "created_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
    )
CLEAR_ENDPOINTS = {"home", "anime_detail"}   # өөрийн route-уудын функцийн нэрээр солино

@app.before_request
def clear_playback_on_navigation():
    if request.method != "GET":
        return
    if request.headers.get("Sec-Fetch-Dest") != "document":
        return
    if request.endpoint not in CLEAR_ENDPOINTS:
        return

    uid = session.get("user_id")
    if not uid or not ObjectId.is_valid(uid):
        return
    print(" 👻👻👻 >> --- > cleared")
    users_collection.update_one(
        {"_id": ObjectId(uid), "playback": {"$exists": True}},
        {"$unset": {"playback": ""}},
    )
@app.get("/watch/<video_id>")
def watch_video(video_id):
    user = get_current_user()
    if not user:
        return render_template("login.html")

    if not ObjectId.is_valid(video_id):
        abort(404)

    video = videos_collection.find_one({
        "_id": ObjectId(video_id),
        "is_uploaded": True,
    })
    
    if not video:
        abort(404)

    save_watch_history(user, video)   

    video["id"] = str(video["_id"])

    token = secrets.token_urlsafe(24)
    # Өмнөх ангийн сесс энд дарагдаж автоматаар хүчингүй болно
    r= users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {"playback": {
            "video_id": str(video["_id"]),
            "token": token,
            "last_seen": time.time(),
            "ua": request.headers.get("User-Agent", ""),
        }}}
    )

    anime = None
    prev_video = None
    next_video = None

    anime_id = video.get("anime_id")
    current_episode = video.get("episode_number")

    print("anime_id:", anime_id)
    print("current_episode:", current_episode)

    if anime_id:

        anime = anime_collection.find_one({
            "_id": anime_id
        })

        if anime:
            anime["id"] = str(anime["_id"])

        # episode_number байгаа үед previous / next хайна
        if current_episode is not None:

            prev_video = videos_collection.find_one(
                {
                    "anime_id": anime_id,
                    "is_uploaded": True,
                    "episode_number": {
                        "$lt": current_episode
                    }
                },
                sort=[
                    ("episode_number", -1)
                ]
            )

            next_video = videos_collection.find_one(
                {
                    "anime_id": anime_id,
                    "is_uploaded": True,
                    "episode_number": {
                        "$gt": current_episode
                    }
                },
                sort=[
                    ("episode_number", 1)
                ]
            )

            if prev_video:
                prev_video["id"] = str(prev_video["_id"])

            if next_video:
                next_video["id"] = str(next_video["_id"])
    stream_url = url_for("stream_video", video_id=str(video["_id"]), t=token)
    return render_template(
        "watch.html",
        video=video,
        anime=anime,
        prev_video=prev_video,
        token=token,
        next_video=next_video,
        stream_url=stream_url,
        
    )
    
@app.get("/dashboard")
@login_required
def dashboard():
    user = current_user()
    return render_template("dashboard.html", user=user, display_phone=display_phone, is_admin_user=is_admin(user) )


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
from bson.errors import InvalidId
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
        cloudinary_screenshots = []
        screenshot = get_random_video_screenshot(temp_path, duration)

        cloudinary_screenshot = None

        if screenshot:
            result = upload_image_to_cloudinary(
                screenshot["image_bytes"],
                folder_name="anime_screenshots",
                quality=75
            )
            print("🐍 File: render_server/app.py | Line: 1973 | upload_video ~ result",result)
            '''
            result = upload_image_to_cloudinary(
                avatar_bytes,
                folder_name="avatars",
                image_format="original",
                compress=False,
            )
            '''

            if result:
                cloudinary_screenshot = {
                    "second": screenshot["second"],
                    **result,
                }


        metadata = {
            "anime_id": anime_id,
            "title": title,
            "episode_number": episode_number,
            "telegram_channel_id": telegram_result["channel_id"],
            "telegram_message_id": telegram_result["message_id"],
            "file_name": telegram_result.get("file_name") or original_name,
            "file_size": telegram_result.get("file_size") or file_size,
            "duration": duration,
            "screenshot": cloudinary_screenshot,
            "is_uploaded": True,
        }
        #djang = send_video_info_to_django(metadata)
        djang = send_video_info_to_mongodb(metadata,videos_collection)
        print("✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️✔️")
        print("SUCCESSFULLY UPLOADED",djang , ' ' ,title )
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

    user = current_user()

    # ==========================================
    # HOME SLIDES
    # ==========================================
    comments = list(
    home_comments_collection.find(
            {"active": True}
        ).sort("created_at", -1).limit(50)
    )

    for comment in comments:
        comment["id"] = str(comment["_id"])

    slides = list(
        home_slides_collection.find(
            {
                "active": True
            }
        ).sort(
            [
                ("sequence", 1),
                ("_id", -1),
            ]
        )
    )
    for slide in slides:
        slide["id"] = str(
            slide["_id"]
        )

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
    # ==========================================
    # LATEST 10 UPLOADED EPISODES
    # ==========================================

    latest_videos = list(
        videos_collection.find({
            "is_uploaded": True,
            "anime_id": {"$ne": None}
        }).sort("_id", -1).limit(10)
    )

    anime_map = {
        str(anime["_id"]): anime
        for anime in anime_list
    }

    latest_episodes = []

    for video in latest_videos:
        anime = anime_map.get(str(video.get("anime_id")))

        if not anime:
            continue

        screenshot = video.get("screenshot") or {}

        latest_episodes.append({
            "id": str(video["_id"]),
            "anime_id": str(anime["_id"]),
            "anime_name": anime.get("name", ""),
            "image_url": screenshot.get("url") or anime.get("image_url", ""),
            "episode_number": video.get("episode_number"),
            "title": video.get("title", ""),
            "created_at": video["_id"].generation_time,
        })
    return render_template(
        "home.html",

        user=user,
        slides=slides,
        anime_list=anime_list,
        latest_episodes=latest_episodes,
        comments=comments,
        display_phone=display_phone,

        is_admin_user=(
            is_admin(user)
            if user
            else False
        ),
    )

@app.route("/api/home/comments", methods=["POST"])
def create_home_comment():
    user = get_current_user()
    data = request.get_json(silent=True) or {}

    content = data.get("content", "")

    if not isinstance(content, str):
        return jsonify({
            "success": False,
            "message": "Сэтгэгдэл буруу байна."
        }), 400

    content = content.strip()

    if not content or len(content) > 1000:
        return jsonify({
            "success": False,
            "message": "Сэтгэгдэл 1-1000 тэмдэгттэй байна."
        }), 400
    avatar_url = (
        user.get("avatar_url")
        if user
        else get_random_anonymous_avatar()
    )
    print("🐍 File: render_server/app.py | Line: 1978 | create_home_comment ~ avatar_url",avatar_url)
    comment = {
        "user_id": user["_id"] if user else None,
        "nickname": (user.get("nickname") or "User") if user else "Anonymous",
        "content": content,
        "active": True,
        "avatar_url": avatar_url,
        "created_at": datetime.now(timezone.utc),
    }

    home_comments_collection.insert_one(comment)

    return jsonify({
        "success": True,
        "message": "Сэтгэгдэл амжилттай нэмэгдлээ."
    })
@app.route("/anime/<anime_id>")
def anime_detail(anime_id):
    if get_current_user():   
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
        genre_ids = anime.get(
            "genre_ids",
            []
        )

        genres = []

        if genre_ids:

            genres = list(
                genres_collection.find(
                    {
                        "_id": {
                            "$in": genre_ids
                        }
                    }
                ).sort(
                    "name",
                    1
                )
            )

            for genre in genres:
                genre["id"] = str(
                    genre["_id"]
                )


        anime["genres"] = genres

        for video in videos:
            video["id"] = str(video["_id"])

        return render_template(
            "anime_detail.html",
            anime=anime,
            videos=videos,
        )
    else:
        return render_template(
            "login.html"
        )
VERCEL_RANGE_SIZE = 8 * 1024 * 1024  # 8 MB
@app.get("/stream/<video_id>")
@login_required
def stream_video(video_id):
    if not ObjectId.is_valid(video_id):
        abort(404)
    user = get_current_user()
    if not user:
        abort(401)
    pb = user.get("playback") or {}
    tok = request.args.get("t", "")
    # 1) Яг одоо үзэж буй анги мөн эсэх
    if str(pb.get("video_id")) != str(video_id):
        abort(403)

    # 2) Токен таарч байгаа эсэх
    if not secrets.compare_digest(str(pb.get("token", "")).encode(), tok.encode()):
        abort(403)

    # 3) Хуудас нээлттэй байгаа эсэх (heartbeat)
    if time.time() - pb.get("last_seen", 0) > ACTIVE_TTL:
        abort(403)
    # 4) Нэг browser-оос ирсэн эсэх
    if pb.get("ua") != request.headers.get("User-Agent", ""):
        abort(403)

    # 5) <video> элементээс ирсэн хүсэлт эсэх (IDM дахин татахдаа энэ header-ийг илгээдэггүй)
    if request.headers.get("Sec-Fetch-Dest") != "video":
        abort(403)

    video = videos_collection.find_one({
        "_id": ObjectId(video_id),
        "is_uploaded": True,
    })
    
    if not video:
        abort(404)

    channel_id = int(video["telegram_channel_id"])
    message_id = int(video["telegram_message_id"])
    file_size = int(video.get("file_size") or 0)

    if file_size <= 0:
        abort(404)

    file_name = video.get("file_name", "")
    mime_type = mimetypes.guess_type(file_name)[0] or "video/mp4"

    # =====================================================
    # CACHE VALIDATOR
    # =====================================================
    etag = f'"{message_id}-{file_size}"'

    range_header = request.headers.get("Range")

    if not range_header:
        if request.headers.get("If-None-Match") == etag:
            return Response(
                status=304,
                headers={
                    "ETag": etag,
                    "Cache-Control": "private, max-age=86400",
                },
            )

    # =====================================================
    # RANGE
    # =====================================================
    start = 0
    end = file_size - 1
    status = 200

    if range_header:
        match = re.match(r"bytes=(\d*)-(\d*)", range_header)

        if not match:
            return Response(
                status=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        start_text = match.group(1)
        end_text = match.group(2)

        if start_text:
            start = int(start_text)

        if end_text:
            requested_end = min(int(end_text), file_size - 1)
        else:
            requested_end = file_size - 1

        # Vercel дээр нэг invocation-аар бүх видеог stream хийхгүй.
        # Нэг request-д хамгийн ихдээ 8 MB өгнө.
        end = min(
            requested_end,
            start + VERCEL_RANGE_SIZE - 1,
            file_size - 1,
        )

        if start >= file_size or start > end:
            return Response(
                status=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        status = 206
    content_length = end - start + 1
    duration = float(video.get("duration") or 0)

    if duration > 0:
        bytes_per_second = file_size / duration
        range_seconds = content_length / bytes_per_second

        print(
            f"[STREAM] Range={range_header} "
            f"bytes={content_length:,} "
            f"~{range_seconds:.2f}s "
            f"start={start:,} end={end:,}"
        )
    else:
        print(
            f"[STREAM] Range={range_header} "
            f"bytes={content_length:,} "
            f"start={start:,} end={end:,}"
        )
    # =====================================================
    # RESPONSE HEADERS
    # =====================================================
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Cache-Control": "private, max-age=86400",
        "ETag": etag,
        "X-Accel-Buffering": "no",
    }

    if status == 206:
        headers["Content-Range"] = (
            f"bytes {start}-{end}/{file_size}"
        )
    if not acquire(tok): 
        print("[STREAM 429] too many connections", tok[:6]) 
        return "Too many connections", 429
    resp = Response(
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
    resp.call_on_close(lambda: release(tok))
    return resp

 ## * END STREAM CODE <<<<<<<<<<<<<<<<<<<<<<<<<<
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
def prepare_genre_ids(values):

    if not isinstance(values, list):
        return []

    object_ids = []

    for value in values:

        if not ObjectId.is_valid(value):
            continue

        genre_id = ObjectId(value)

        if genre_id not in object_ids:
            object_ids.append(
                genre_id
            )

    if not object_ids:
        return []

    # DB дээр үнэхээр байгаа genre-үүдийг л авна
    valid_genres = genres_collection.find(
        {
            "_id": {
                "$in": object_ids
            }
        },
        {
            "_id": 1
        }
    )

    return [
        genre["_id"]
        for genre in valid_genres
    ]
@app.route("/anime/create")
def anime_create_page():

    genres = list(
        genres_collection.find(
            {}
        ).sort(
            "name",
            1
        )
    )

    for genre in genres:
        genre["id"] = str(
            genre["_id"]
        )

    return render_template(
        "anime_create.html",
        genres=genres,
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
        genre_ids = prepare_genre_ids(
            data.get(
                "genre_ids",
                []
            )
        )
        anime_data = {

            "name": name,

            "description": (
                data.get("description") or ""
            ).strip(),

            "active": bool(
                data.get("active", True)
            ),
            "genre_ids": genre_ids,
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
        genre_ids = prepare_genre_ids(
            data.get(
                "genre_ids",
                []
            )
        )
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
            "genre_ids":
            genre_ids,
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


@app.route("/admin/genre/create", methods=["POST"])
def create_genre():

    name = str(
        request.form.get("name")
        or ""
    ).strip()

    if not name:
        return jsonify({
            "success": False,
            "message": "Genre нэр оруулна уу."
        }), 400

    try:

        result = genres_collection.insert_one({
            "name": name,
            "created_at": utcnow(),
        })

        return jsonify({
            "success": True,
            "id": str(result.inserted_id),
            "name": name,
        })

    except DuplicateKeyError:

        return jsonify({
            "success": False,
            "message": "Энэ genre аль хэдийн байна."
        }), 409

def get_video_query(video_id):
    """
    _id нь ObjectId, int, string аль нь байсан
    боломжийн хэмжээнд олно.
    """
    queries = [
        {"_id": video_id},
    ]

    if ObjectId.is_valid(video_id):
        queries.append({
            "_id": ObjectId(video_id),
        })

    try:
        numeric_id = int(video_id)

        queries.append({
            "_id": numeric_id,
        })

        queries.append({
            "id": numeric_id,
        })

    except (ValueError, TypeError):
        pass

    return {
        "$or": queries,
    }


# =========================================================
# VIDEO MANAGEMENT PAGE
# =========================================================

@app.route("/admin/videos")
def admin_videos_page():

    # Хэрэв admin session шалгадаг бол эндээ оруулна
    # if "user_name" not in session:
    #     return redirect("/login")

    return render_template(
        "admin_videos.html"
    )


# =========================================================
# GET VIDEOS
# =========================================================

@app.route(
    "/api/admin/videos",
    methods=["GET"],
)
def admin_get_videos():

    videos = list(
        videos_collection.find(
            {}
        ).sort(
            "episode_number",
            1,
        )
    )

    result = []

    for video in videos:

        result.append({
            "id": str(
                video.get("_id")
            ),
            "anime_id": str(
                video.get(
                    "anime_id",
                    ""
                )
            ),
            "title": video.get(
                "title",
                ""
            ),
            "episode_number": video.get(
                "episode_number",
                ""
            ),
            "file_name": video.get(
                "file_name",
                ""
            ),
            "file_size": video.get(
                "file_size",
                0
            ),
            "telegram_channel_id": video.get(
                "telegram_channel_id",
                ""
            ),
            "telegram_message_id": video.get(
                "telegram_message_id",
                ""
            ),
            "is_uploaded": video.get(
                "is_uploaded",
                False
            ),
        })

    return jsonify({
        "success": True,
        "videos": result,
    })


# =========================================================
# UPDATE VIDEO
# =========================================================

@app.route(
    "/api/admin/videos/<video_id>",
    methods=["PUT"],
)
def admin_update_video(video_id):

    data = request.get_json(
        silent=True
    ) or {}

    title = str(
        data.get(
            "title",
            ""
        )
    ).strip()

    episode_number = data.get(
        "episode_number"
    )

    if not title:

        return jsonify({
            "success": False,
            "message": "Видео нэр хоосон байна.",
        }), 400

    try:
        episode_number = int(
            episode_number
        )

    except (
        ValueError,
        TypeError,
    ):

        return jsonify({
            "success": False,
            "message": (
                "Episode number "
                "тоо байх ёстой."
            ),
        }), 400

    result = videos_collection.update_one(
        get_video_query(
            video_id
        ),
        {
            "$set": {
                "title": title,
                "episode_number": episode_number,
                "updated_at": utcnow(),
            }
        },
    )

    if result.matched_count == 0:

        return jsonify({
            "success": False,
            "message": (
                "Видео олдсонгүй."
            ),
        }), 404

    return jsonify({
        "success": True,
        "message": (
            "Видео амжилттай "
            "засагдлаа."
        ),
    })


# =========================================================
# DELETE VIDEO
# =========================================================

@app.route(
    "/api/admin/videos/<video_id>",
    methods=["DELETE"],
)
def admin_delete_video(video_id):

    result = videos_collection.delete_one(
        get_video_query(
            video_id
        )
    )

    if result.deleted_count == 0:

        return jsonify({
            "success": False,
            "message": "Видео олдсонгүй.",
        }), 404

    return jsonify({
        "success": True,
        "message": (
            "Видео амжилттай "
            "устгагдлаа."
        ),
    })


# =========================================================
# DELETE ALL VIDEOS
# =========================================================

@app.route(
    "/api/admin/videos",
    methods=["DELETE"],
)
def admin_delete_all_videos():

    result = videos_collection.delete_many(
        {}
    )

    return jsonify({
        "success": True,
        "deleted_count": (
            result.deleted_count
        ),
        "message": (
            f"{result.deleted_count} "
            "видео устгагдлаа."
        ),
    })

@app.route(
    "/api/admin/files/upload",
    methods=["POST"],
)
def admin_upload_file():

    uploaded_file = (
        request.files.get(
            "file"
        )
    )

    name = str(
        request.form.get(
            "name",
            ""
        )
    ).strip()

    description = str(
        request.form.get(
            "description",
            ""
        )
    ).strip()


    # ==========================================
    # VALIDATE
    # ==========================================

    if not uploaded_file:

        return jsonify({
            "success": False,
            "message": (
                "Файл сонгоогүй байна."
            ),
        }), 400


    if not uploaded_file.filename:

        return jsonify({
            "success": False,
            "message": (
                "Файлын нэр байхгүй байна."
            ),
        }), 400


    if not allowed_upload_file(
        uploaded_file.filename
    ):

        return jsonify({
            "success": False,
            "message": (
                "PDF, ZIP, RAR файл "
                "upload хийх боломжтой."
            ),
        }), 400


    original_file_name = (
        uploaded_file.filename
    )

    suffix = (
        Path(
            original_file_name
        )
        .suffix
        .lower()
    )


    if not name:

        name = (
            Path(
                original_file_name
            ).stem
        )


    temp_path = None


    try:

        # ======================================
        # TEMP SAVE
        # ======================================

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:

            temp_path = (
                temp_file.name
            )


        uploaded_file.save(
            temp_path
        )


        # ======================================
        # FILE META
        # ======================================

        file_size = (
            os.path.getsize(
                temp_path
            )
        )

        mime_type = (
            mimetypes.guess_type(
                original_file_name
            )[0]
            or
            "application/octet-stream"
        )


        # ======================================
        # TELEGRAM
        # ======================================

        telegram_result = (
            asyncio.run(
                upload_file_to_telegram(
                    temp_path,
                    caption=name,
                )
            )
        )


        if not telegram_result.get(
            "success"
        ):

            raise RuntimeError(
                "Telegram upload failed"
            )


        # ======================================
        # MONGODB
        # ======================================

        document = {

            "name": name,

            "description":
                description,

            "file_name":
                telegram_result.get(
                    "file_name"
                )
                or
                original_file_name,

            "file_type":
                suffix.lstrip(
                    "."
                ),

            "mime_type":
                mime_type,

            "file_size":
                telegram_result.get(
                    "file_size",
                    file_size,
                ),

            "telegram_channel_id":
                telegram_result[
                    "channel_id"
                ],

            "telegram_message_id":
                telegram_result[
                    "message_id"
                ],

            "is_uploaded":
                True,

            "created_at":
                utcnow(),

            "updated_at":
                utcnow(),
        }


        result = (
            files_collection
            .insert_one(
                document
            )
        )


        return jsonify({
            "success": True,

            "message": (
                "Файл амжилттай "
                "upload хийгдлээ."
            ),

            "file": {
                "id": str(
                    result.inserted_id
                ),

                "name":
                    document["name"],

                "file_name":
                    document[
                        "file_name"
                    ],

                "file_type":
                    document[
                        "file_type"
                    ],

                "file_size":
                    document[
                        "file_size"
                    ],

                "channel_id":
                    document[
                        "telegram_channel_id"
                    ],

                "message_id":
                    document[
                        "telegram_message_id"
                    ],
            },
        })


    except Exception as e:

        print(
            "FILE UPLOAD ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "message": str(e),
        }), 500


    finally:

        if (
            temp_path
            and
            os.path.exists(
                temp_path
            )
        ):

            os.remove(
                temp_path
            )
@app.route("/admin/files")
def admin_files_page():

    return render_template(
        "admin_files.html"
    )

def upload_admin_file():

    uploaded_file = request.files.get(
        "file"
    )

    name = str(
        request.form.get(
            "name",
            ""
        )
    ).strip()

    description = str(
        request.form.get(
            "description",
            ""
        )
    ).strip()


    # =====================================================
    # VALIDATE
    # =====================================================

    if not uploaded_file:

        return jsonify({
            "success": False,
            "message": "Файл сонгоогүй байна.",
        }), 400


    if not uploaded_file.filename:

        return jsonify({
            "success": False,
            "message": "Файлын нэр байхгүй байна.",
        }), 400


    if not allowed_file(
        uploaded_file.filename
    ):

        return jsonify({
            "success": False,
            "message": (
                "Зөвхөн PDF, RAR, ZIP "
                "файл upload хийх боломжтой."
            ),
        }), 400


    original_filename = (
        uploaded_file.filename
    )

    ext = os.path.splitext(
        original_filename
    )[1].lower()


    if not name:

        name = os.path.splitext(
            original_filename
        )[0]


    # =====================================================
    # TEMP FILE
    # =====================================================

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=ext,
        ) as temp_file:

            temp_path = temp_file.name

            uploaded_file.save(
                temp_path
            )


        file_size = os.path.getsize(
            temp_path
        )

        mime_type = (
            mimetypes.guess_type(
                original_filename
            )[0]
            or
            "application/octet-stream"
        )


        # =================================================
        # TELEGRAM UPLOAD
        # =================================================

        telegram_result = run_async(
            upload_file_to_telegram(
                temp_path,
                original_filename,
            )
        )


        telegram_channel_id = (
            telegram_result[
                "channel_id"
            ]
        )

        telegram_message_id = (
            telegram_result[
                "message_id"
            ]
        )


        # =================================================
        # SAVE MONGODB
        # =================================================

        document = {

            "name": name,

            "file_name":
                original_filename,

            "file_type":
                ext.replace(
                    ".",
                    ""
                ),

            "mime_type":
                mime_type,

            "file_size":
                file_size,

            "telegram_channel_id":
                telegram_channel_id,

            "telegram_message_id":
                telegram_message_id,

            "description":
                description,

            "is_uploaded":
                True,

            "created_at":
                utcnow(),

            "updated_at":
                utcnow(),
        }


        result = (
            files_collection
            .insert_one(
                document
            )
        )


        return jsonify({
            "success": True,

            "message":
                "Файл амжилттай upload хийгдлээ.",

            "file": {
                "id": str(
                    result.inserted_id
                ),
                "name": name,
                "file_name":
                    original_filename,
                "file_type":
                    document[
                        "file_type"
                    ],
                "file_size":
                    file_size,
                "telegram_channel_id":
                    telegram_channel_id,
                "telegram_message_id":
                    telegram_message_id,
            },
        })


    except Exception as e:

        print(
            "FILE UPLOAD ERROR:",
            str(e)
        )

        return jsonify({
            "success": False,
            "message": str(e),
        }), 500


    finally:

        if (
            temp_path
            and
            os.path.exists(
                temp_path
            )
        ):

            os.remove(
                temp_path
            )

@app.route(
    "/api/admin/files",
    methods=["GET"],
)
def admin_get_files():

    files = list(
        files_collection.find(
            {}
        ).sort(
            "created_at",
            -1,
        )
    )

    result = []

    for file in files:

        channel_id = file.get(
            "telegram_channel_id"
        )

        message_id = file.get(
            "telegram_message_id"
        )

        telegram_link = None

        # Private channel/supergroup link:
        # -1001234567890 -> 1234567890
        if (
            channel_id
            and
            message_id
        ):

            channel_str = str(
                channel_id
            )

            if channel_str.startswith(
                "-100"
            ):

                internal_id = (
                    channel_str[4:]
                )

                telegram_link = (
                    f"https://t.me/c/"
                    f"{internal_id}/"
                    f"{message_id}"
                )


        created_at = file.get(
            "created_at"
        )


        result.append({

            "id": str(
                file.get("_id")
            ),

            "name": file.get(
                "name",
                ""
            ),

            "description": file.get(
                "description",
                ""
            ),

            "file_name": file.get(
                "file_name",
                ""
            ),

            "file_type": file.get(
                "file_type",
                ""
            ),

            "mime_type": file.get(
                "mime_type",
                ""
            ),

            "file_size": file.get(
                "file_size",
                0
            ),

            "telegram_channel_id":
                channel_id,

            "telegram_message_id":
                message_id,

            "telegram_link":
                telegram_link,

            "is_uploaded": file.get(
                "is_uploaded",
                False
            ),

            "created_at": (
                created_at.isoformat()
                if created_at
                else None
            ),
        })


    return jsonify({
        "success": True,
        "files": result,
    })

@app.get("/admin/users")
@login_required
def admin_users_page():
    if not is_admin(current_user()):
        abort(403)

    users = list(
        users_collection.find(
            {},
            {"password_hash": 0}
        ).sort("created_at", -1)
    )

    for user in users:
        user["_id"] = str(user["_id"])

    return render_template(
        "admin_users.html",
        users=users,
        current_user_id=str(session.get("user_id") or ""),
    )


@app.delete("/api/admin/users/<user_id>")
@login_required
def admin_user_delete(user_id):
    if not is_admin(current_user()):
        return jsonify({
            "ok": False,
            "message": "Admin эрх шаардлагатай."
        }), 403

    if not ObjectId.is_valid(user_id):
        return jsonify({
            "ok": False,
            "message": "User ID буруу байна."
        }), 400

    current_user_id = str(session.get("user_id") or "")

    if current_user_id == user_id:
        return jsonify({
            "ok": False,
            "message": "Өөрийн admin хэрэглэгчийг устгах боломжгүй."
        }), 400

    user = users_collection.find_one({
        "_id": ObjectId(user_id)
    })

    if not user:
        return jsonify({
            "ok": False,
            "message": "Хэрэглэгч олдсонгүй."
        }), 404

    result = users_collection.delete_one({
        "_id": ObjectId(user_id)
    })

    if result.deleted_count != 1:
        return jsonify({
            "ok": False,
            "message": "Хэрэглэгч устгаж чадсангүй."
        }), 500

    return jsonify({
        "ok": True,
        "message": "Хэрэглэгч амжилттай устлаа."
    })
def upload_download_cover_to_cloudinary(file):
    if not file or not file.filename:
        return None

    if file.mimetype not in ("image/jpeg", "image/png", "image/webp"):
        raise ValueError("Cover зураг JPG, PNG, WEBP байх ёстой.")

    image_bytes = file.read(MAX_COVER_SIZE + 1)

    if not image_bytes or len(image_bytes) > MAX_COVER_SIZE:
        raise ValueError("Cover зураг 5 MB-аас бага байх ёстой.")

    import io

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            if image.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("Зургийн формат буруу байна.")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("Зургийн файл гэмтсэн эсвэл буруу байна.")

    result = cloudinary.uploader.upload(
        image_bytes,
        folder="download/covers",
        resource_type="image",
        transformation=[
            {"quality": "auto", "fetch_format": "auto"}
        ]
    )

    return {
        "url": result["secure_url"],
        "public_id": result["public_id"]
    }


def delete_download_cover_from_cloudinary(cover):
    public_id = (cover or {}).get("public_id")

    if public_id:
        cloudinary.uploader.destroy(
            public_id,
            resource_type="image",
            invalidate=True
        )
@app.route("/admin/download-items")
def admin_download_items():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    # Энд одоо байгаа project-ийн admin эрх шалгах логикийг ашиглана.
    if not is_admin(current_user()):
        abort(403)

    return render_template("download_items.html")

from urllib.parse import urlsplit

def validate_external_url(value):
    value = (value or "").strip()

    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or len(value) > 2048
        ):
            raise ValueError()
    except ValueError:
        raise ValueError("External URL хүчинтэй HTTPS холбоос байх ёстой.")

    return value

@app.route("/admin/api/upload", methods=["POST"])
@admin_required
def admin_upload():
    # ==========================================
    # 1. FORM VALUES
    # ==========================================
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("category", "other").strip().lower()
    access_type = request.form.get("access_type", "free").strip().lower()
    storage_type = request.form.get("storage_type", "telegram").strip().lower()
    price_raw = request.form.get("price", "0").strip()

    file = request.files.get("file")
    cover_file = request.files.get("cover")

    # ==========================================
    # 2. VALIDATION
    # ==========================================
    if not title or len(title) > 200:
        return jsonify({
            "success": False,
            "message": "Item нэр 1–200 тэмдэгт байх ёстой."
        }), 400

    if category not in DOWNLOAD_CATEGORIES:
        return jsonify({
            "success": False,
            "message": "Category буруу байна."
        }), 400

    if access_type not in ("free", "paid"):
        return jsonify({
            "success": False,
            "message": "Access type буруу байна."
        }), 400

    if storage_type not in ("telegram", "external"):
        return jsonify({
            "success": False,
            "message": "Storage type буруу байна."
        }), 400

    try:
        if access_type == "paid":
            if not price_raw.isdigit():
                raise ValueError()

            price = int(price_raw)

            if price <= 0:
                raise ValueError()
        else:
            price = 0

    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "message": "Үнэ зөв оруулна уу."
        }), 400

    # ==========================================
    # 3. EXTERNAL URL VALIDATION
    # ==========================================
    external_url = None

    if storage_type == "external":
        try:
            external_url = validate_external_url(
                request.form.get("external_url")
            )
        except ValueError as exc:
            return jsonify({
                "success": False,
                "message": str(exc)
            }), 400

    # ==========================================
    # 4. TELEGRAM FILE VALIDATION
    # ==========================================
    filename = ""
    file_type = ""
    file_size = 0

    if storage_type == "telegram":
        if not file or not file.filename:
            return jsonify({
                "success": False,
                "message": "Telegram файл сонгоно уу."
            }), 400

        filename = secure_filename(file.filename)

        if not filename:
            return jsonify({
                "success": False,
                "message": "Файлын нэр буруу байна."
            }), 400

        file_type = Path(filename).suffix.lower().lstrip(".")

    # ==========================================
    # 5. UPLOAD + SAVE
    # ==========================================
    telegram_data = None
    cover_data = None
    mongo_saved = False

    try:
        # --------------------------------------
        # A. TELEGRAM UPLOAD
        # --------------------------------------
        if storage_type == "telegram":
            with tempfile.TemporaryDirectory() as temp_dir:
                file_path = os.path.join(temp_dir, filename)
                file.save(file_path)

                file_size = os.path.getsize(file_path)

                if file_size == 0:
                    return jsonify({
                        "success": False,
                        "message": "Хоосон файл upload хийх боломжгүй."
                    }), 400

                is_video = file_type in {
                    "mp4", "mkv", "mov", "webm", "avi"
                }

                upload_result = asyncio.run(
                    upload_video_to_telegram(
                        file_path,
                        caption=title,
                        is_video=is_video
                    )
                )

                if not upload_result or not upload_result.get("success"):
                    raise RuntimeError("Telegram upload амжилтгүй.")

                telegram_data = {
                    "channel_id": upload_result.get("channel_id"),
                    "message_id": upload_result.get("message_id"),
                    "file_name": filename,
                    "file_size": upload_result.get("file_size", file_size)
                }

        # --------------------------------------
        # B. CLOUDINARY COVER UPLOAD
        # --------------------------------------
        if cover_file and cover_file.filename:
            cover_data = upload_download_cover_to_cloudinary(
                cover_file
            )

        # --------------------------------------
        # C. MONGODB SAVE
        # --------------------------------------
        now = datetime.now(timezone.utc)

        item = {
            "item_type": "download",
            "title": title,
            "description": description,
            "category": category,
            "access_type": access_type,
            "price": price,
            "currency": "MNT",
            "storage_type": storage_type,
            "external_url": external_url,
            "file_type": file_type,
            "telegram": telegram_data,
            "cover": cover_data,
            "is_published": False,
            "download_count": 0,
            "created_at": now,
            "updated_at": now
        }

        result = zip_files.insert_one(item)
        mongo_saved = True

        # --------------------------------------
        # D. RESPONSE
        # --------------------------------------
        return jsonify({
            "success": True,
            "message": (
                "External Link амжилттай бүртгэгдлээ."
                if storage_type == "external"
                else "Telegram файл амжилттай бүртгэгдлээ."
            ),
            "item_id": str(result.inserted_id),
            "storage_type": storage_type,
            "telegram": telegram_data,
            "external_url": external_url,
            "cover": cover_data
        }), 201

    except ValueError as exc:
        return jsonify({
            "success": False,
            "message": str(exc)
        }), 400

    except Exception:
        current_app.logger.exception("Admin upload failed")

        if cover_data and not mongo_saved:
            try:
                delete_download_cover_from_cloudinary(cover_data)
            except Exception:
                current_app.logger.exception(
                    "Cloudinary cover rollback failed"
                )

        return jsonify({
            "success": False,
            "message": "Item бүртгэхэд алдаа гарлаа."
        }), 500

@app.route("/admin/api/download-items", methods=["GET"])
@admin_required
def get_download_items():
    try:
        items = list(
            zip_files.find({
                "item_type": "download"
            }).sort("created_at", -1)
        )

        for item in items:
            item["_id"] = str(item["_id"])

            item["cover_url"] = (
                (item.get("cover") or {}).get("url")
            )

            item["category"] = item.get("category", "other")

            if isinstance(item.get("created_at"), datetime):
                item["created_at"] = item["created_at"].isoformat()

            if isinstance(item.get("updated_at"), datetime):
                item["updated_at"] = item["updated_at"].isoformat()

        return jsonify({
            "success": True,
            "items": items,
            "total": len(items)
        }), 200

    except Exception:
        current_app.logger.exception("Get download items failed")

        return jsonify({
            "success": False,
            "message": "Бүртгэлүүдийг авахад алдаа гарлаа."
        }), 500

@app.route("/admin/api/download-items/<item_id>", methods=["PATCH"])
@admin_required
def update_download_item(item_id):
    try:
        object_id = ObjectId(item_id)
    except (InvalidId, TypeError):
        return jsonify({
            "success": False,
            "message": "Item ID буруу."
        }), 400

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "message": "JSON өгөгдөл буруу."
        }), 400

    title = data.get("title", "")
    description = data.get("description", "")
    category = data.get("category", "other")
    access_type = data.get("access_type", "free")
    is_published = data.get("is_published", False)

    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        return jsonify({
            "success": False,
            "message": "Item нэр буруу."
        }), 400

    if not isinstance(description, str):
        return jsonify({
            "success": False,
            "message": "Тайлбар буруу."
        }), 400

    if category not in DOWNLOAD_CATEGORIES:
        return jsonify({
            "success": False,
            "message": "Category буруу."
        }), 400

    if access_type not in ("free", "paid"):
        return jsonify({
            "success": False,
            "message": "Access type буруу."
        }), 400

    if not isinstance(is_published, bool):
        return jsonify({
            "success": False,
            "message": "Published утга буруу."
        }), 400

    try:
        raw_price = data.get("price", 0)

        if access_type == "paid":
            if isinstance(raw_price, bool):
                raise ValueError()

            if not str(raw_price).isdigit():
                raise ValueError()

            price = int(raw_price)

            if price <= 0:
                raise ValueError()
        else:
            price = 0

    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": "Үнэ буруу."
        }), 400

    update_data = {
        "title": title.strip(),
        "description": description.strip(),
        "category": category,
        "access_type": access_type,
        "price": price,
        "currency": "MNT",
        "is_published": is_published,
        "updated_at": datetime.now(timezone.utc)
    }

    try:
        result = zip_files.update_one(
            {
                "_id": object_id,
                "item_type": "download"
            },
            {"$set": update_data}
        )

        if not result.matched_count:
            return jsonify({
                "success": False,
                "message": "Item олдсонгүй."
            }), 404

        return jsonify({
            "success": True,
            "message": "Item амжилттай шинэчлэгдлээ.",
            "item_id": item_id
        }), 200

    except Exception:
        current_app.logger.exception("Update download item failed")

        return jsonify({
            "success": False,
            "message": "Item засахад алдаа гарлаа."
        }), 500

@app.route("/admin/api/download-items/<item_id>/cover", methods=["POST"])
@admin_required
def update_download_item_cover(item_id):
    try:
        object_id = ObjectId(item_id)
    except (InvalidId, TypeError):
        return jsonify({
            "success": False,
            "message": "Item ID буруу."
        }), 400

    item = zip_files.find_one({
        "_id": object_id,
        "item_type": "download"
    })

    if not item:
        return jsonify({
            "success": False,
            "message": "Item олдсонгүй."
        }), 404

    cover_file = request.files.get("cover")

    if not cover_file or not cover_file.filename:
        return jsonify({
            "success": False,
            "message": "Cover зураг сонгоно уу."
        }), 400

    new_cover = None

    try:
        new_cover = upload_download_cover_to_cloudinary(
            cover_file
        )

        result = zip_files.update_one(
            {
                "_id": object_id,
                "item_type": "download"
            },
            {
                "$set": {
                    "cover": new_cover,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )

        if result.matched_count == 0:
            delete_download_cover_from_cloudinary(new_cover)
            return jsonify({
                "success": False,
                "message": "Item олдсонгүй."
            }), 404

        old_cover = item.get("cover")

        if old_cover:
            try:
                delete_download_cover_from_cloudinary(old_cover)
            except Exception:
                current_app.logger.exception(
                    "Old Cloudinary cover cleanup failed"
                )

        return jsonify({
            "success": True,
            "message": "Cover зураг шинэчлэгдлээ.",
            "cover": new_cover
        }), 200

    except ValueError as exc:
        return jsonify({
            "success": False,
            "message": str(exc)
        }), 400

    except Exception:
        current_app.logger.exception("Update cover failed")

        if new_cover:
            try:
                delete_download_cover_from_cloudinary(new_cover)
            except Exception:
                current_app.logger.exception("Cover rollback failed")

        return jsonify({
            "success": False,
            "message": "Cover зураг солиход алдаа гарлаа."
        }), 500


@app.route("/admin/api/download-items/<item_id>", methods=["DELETE"])
@admin_required
def delete_download_item(item_id):
    try:
        object_id = ObjectId(item_id)
    except (InvalidId, TypeError):
        return jsonify({
            "success": False,
            "message": "Item ID буруу."
        }), 400

    try:
        item = zip_files.find_one({
            "_id": object_id,
            "item_type": "download"
        })

        if not item:
            return jsonify({
                "success": False,
                "message": "Item олдсонгүй."
            }), 404

        result = zip_files.delete_one({
            "_id": object_id,
            "item_type": "download"
        })

        if not result.deleted_count:
            return jsonify({
                "success": False,
                "message": "Item устгагдсангүй."
            }), 404

        cover = item.get("cover")

        if cover:
            try:
                delete_download_cover_from_cloudinary(cover)
            except Exception:
                current_app.logger.exception(
                    "Cloudinary delete failed"
                )

        return jsonify({
            "success": True,
            "message": "Item устгагдлаа. Telegram файл хэвээр үлдсэн.",
            "item_id": item_id
        }), 200

    except Exception:
        current_app.logger.exception("Delete download item failed")

        return jsonify({
            "success": False,
            "message": "Item устгахад алдаа гарлаа."
        }), 500

@app.route("/software")
def software_page():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip().lower()

    query = {
        "item_type": "download",
        "is_published": True,
    }

    if category:
        query["category"] = category

    if q:
        query["title"] = {"$regex": q, "$options": "i"}

    items = list(
        zip_files.find(query).sort("created_at", -1)
    )

    for item in items:
        item["_id"] = str(item["_id"])
        item["cover_url"] = (item.get("cover") or {}).get("url")
        item["detail_url"] = url_for(
            "software_detail_page",
            item_id=item["_id"]
        )

    return render_template(
        "software/list.html",
        items=items,
        selected_category=category,
        search_query=q,
    )

@app.route("/software/<item_id>")
def software_detail_page(item_id):
    try:
        object_id = ObjectId(item_id)
    except Exception:
        abort(404)

    item = zip_files.find_one({
        "_id": object_id,
        "item_type": "download",
        "is_published": True,
    })

    if not item:
        abort(404)

    item["_id"] = str(item["_id"])
    item["cover_url"] = (item.get("cover") or {}).get("url")

    return render_template(
        "software/detail.html",
        item=item
    )
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5002)), debug=True)
