import os, re
from datetime import datetime
from functools import wraps

from bson.objectid import ObjectId
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_pymongo import PyMongo
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash, check_password_hash

import cloudinary
import cloudinary.uploader

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/render_server")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
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


@app.get("/")
def index():
    return redirect(url_for("dashboard" if session.get("user_id") else "login"))


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


@app.get("/dashboard")
@login_required
def dashboard():
    user = current_user()
    return render_template("dashboard.html", user=user, display_phone=display_phone)


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


@app.get("/health")
def health():
    try:
        mongo.cx.admin.command("ping")
        return jsonify({"status": "ok", "database": "mongodb"}), 200
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.errorhandler(413)
def file_too_large(_):
    flash("Зураг 5MB-аас их байна.", "danger")
    return redirect(url_for("profile"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
