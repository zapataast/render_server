import os
import re
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from flask_pymongo import PyMongo
from pymongo.errors import DuplicateKeyError
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key-in-render"
)

app.config["MONGO_URI"] = os.environ.get(
    "MONGO_URI",
    "mongodb://localhost:27017/render_server"
)

mongo = PyMongo(app)


def ensure_indexes():
    """
    Утасны дугаар давхардахгүй байхаар unique index үүсгэнэ.
    """
    try:
        mongo.db.users.create_index("phone", unique=True)
    except Exception as exc:
        print(f"Mongo index warning: {exc}")


with app.app_context():
    ensure_indexes()


def normalize_phone(phone: str) -> str:
    """
    Монгол дугаарыг нэг формат руу оруулна.

    99112233       -> +97699112233
    97699112233    -> +97699112233
    +97699112233   -> +97699112233
    """

    raw = str(phone or "").strip()

    # цифрээс бусад тэмдэгтийг арилгана
    digits = re.sub(r"\D", "", raw)

    if len(digits) == 8:
        return f"+976{digits}"

    if len(digits) == 11 and digits.startswith("976"):
        return f"+{digits}"

    return ""


def display_phone(phone: str) -> str:
    if phone and phone.startswith("+976") and len(phone) == 12:
        return phone[4:]
    return phone or ""


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped


@app.get("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        raw_phone = request.form.get("phone") or ""
        password = request.form.get("password") or ""

        phone = normalize_phone(raw_phone)

        if not phone:
            flash("Утасны дугаар буруу байна. 8 оронтой дугаар оруулна уу.", "danger")
            return render_template("login.html", phone=raw_phone)

        user = mongo.db.users.find_one({"phone": phone})

        if not user or not check_password_hash(
            user.get("password_hash", ""),
            password
        ):
            flash("Утасны дугаар эсвэл нууц үг буруу байна.", "danger")
            return render_template(
                "login.html",
                phone=display_phone(phone)
            )

        session.clear()
        session["user_id"] = str(user["_id"])
        session["phone"] = user["phone"]
        session["nickname"] = user["nickname"]

        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        raw_phone = request.form.get("phone") or ""
        nickname = (request.form.get("nickname") or "").strip()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        phone = normalize_phone(raw_phone)

        if not phone:
            flash("Утасны дугаар 8 оронтой байх ёстой.", "danger")
            return render_template(
                "register.html",
                phone=raw_phone,
                nickname=nickname
            )

        if len(nickname) < 2:
            flash("Nickname хамгийн багадаа 2 тэмдэгт байна.", "danger")
            return render_template(
                "register.html",
                phone=display_phone(phone),
                nickname=nickname
            )

        if len(nickname) > 50:
            flash("Nickname хэт урт байна.", "danger")
            return render_template(
                "register.html",
                phone=display_phone(phone),
                nickname=nickname
            )

        if len(password) < 6:
            flash("Нууц үг хамгийн багадаа 6 тэмдэгт байна.", "danger")
            return render_template(
                "register.html",
                phone=display_phone(phone),
                nickname=nickname
            )

        if password != confirm_password:
            flash("Нууц үг хоорондоо таарахгүй байна.", "danger")
            return render_template(
                "register.html",
                phone=display_phone(phone),
                nickname=nickname
            )

        existing_user = mongo.db.users.find_one({"phone": phone})

        if existing_user:
            flash("Энэ утасны дугаараар бүртгэл үүссэн байна.", "danger")
            return render_template(
                "register.html",
                phone=display_phone(phone),
                nickname=nickname
            )

        user_document = {
            "phone": phone,
            "nickname": nickname,
            "password_hash": generate_password_hash(password),
        }

        try:
            mongo.db.users.insert_one(user_document)
        except DuplicateKeyError:
            flash("Энэ утасны дугаараар бүртгэл үүссэн байна.", "danger")
            return render_template(
                "register.html",
                phone=display_phone(phone),
                nickname=nickname
            )

        flash("Бүртгэл амжилттай үүслээ. Одоо нэвтэрнэ үү.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.get("/dashboard")
@login_required
def dashboard():
    try:
        user_id = ObjectId(session["user_id"])
    except Exception:
        session.clear()
        return redirect(url_for("login"))

    user = mongo.db.users.find_one({"_id": user_id})

    if not user:
        session.clear()
        return redirect(url_for("login"))

    return render_template(
        "dashboard.html",
        user={
            "nickname": user.get("nickname", ""),
            "phone": display_phone(user.get("phone", "")),
        }
    )


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/health")
def health():
    try:
        mongo.cx.admin.command("ping")
        return jsonify({
            "status": "ok",
            "database": "mongodb"
        }), 200
    except Exception as exc:
        return jsonify({
            "status": "error",
            "database": "mongodb",
            "message": str(exc)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )
