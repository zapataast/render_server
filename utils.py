import os
import requests
import json
import subprocess
from datetime import datetime, timezone
from bson import ObjectId
from pymongo import MongoClient
from dotenv import load_dotenv
from pymongo import MongoClient
load_dotenv()
paylink_url = os.getenv("paylink_url", "")
import mysql.connector

DB_CONFIG = {
    "host": os.getenv("mysqlhost", "localhost"),
    "port": int(os.getenv("mysqlport", "3306")),
    "user": os.getenv("dbuser","root"),
    "password": os.getenv("dbuser_pass","it#2016"),
    "database": os.getenv("mysqldb",'mysqldb'),
    "charset": "utf8mb4",
    "collation": "utf8mb4_unicode_ci",
    "autocommit": True,
}
MAX_COMMENT_LEN = 1000

def get_conn():
    return mysql.connector.connect(**DB_CONFIG)


def add_comment(user_id: str, video_id: str, comment: str) -> int:
    comment = (comment or "").strip()
    if not comment:
        raise ValueError("Comment хоосон байна")
    if len(comment) > MAX_COMMENT_LEN:
        raise ValueError(f"Comment {MAX_COMMENT_LEN} тэмдэгтээс хэтэрсэн")

    sql = "INSERT INTO comments (user_id, video_id, comment) VALUES (%s, %s, %s)"
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, (str(user_id), str(video_id), comment))
        new_id = cur.lastrowid
        cur.close()
        return new_id
    finally:
        conn.close()

def init_comments_table():
    sql = """
        CREATE TABLE IF NOT EXISTS comments (
            id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            user_id     VARCHAR(64)  NOT NULL,
            video_id    VARCHAR(64)  NOT NULL,
            comment     TEXT         NOT NULL,
            is_deleted  TINYINT(1)   NOT NULL DEFAULT 0,
            created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_video_created (video_id, created_at),
            KEY idx_user (user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    sql2 = """
        CREATE TABLE IF NOT EXISTS video_ratings (
            id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            user_id           VARCHAR(64) NOT NULL,
            video_id          VARCHAR(64) NOT NULL,
            episode_score     TINYINT UNSIGNED NULL,
            translation_score TINYINT UNSIGNED NULL,
            created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                              ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_user_video (user_id, video_id),
            KEY idx_video (video_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    sql_comments = """
        CREATE TABLE IF NOT EXISTS home_comments (
            id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            mongo_id    CHAR(24) NULL,                 -- хуучин Mongo _id (migration давхцахаас сэргийлнэ)
            user_id     VARCHAR(64) NULL,              -- NULL = Anonymous
            nickname    VARCHAR(100) NOT NULL DEFAULT 'Anonymous',
            content     TEXT NOT NULL,
            avatar_url  VARCHAR(500) NULL,
            active      TINYINT(1) NOT NULL DEFAULT 1,
            created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_mongo_id (mongo_id),
            KEY idx_active_created (active, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    watchsql = """
        CREATE TABLE IF NOT EXISTS watch_history (
            id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            user_id     VARCHAR(64)  NOT NULL,
            anime_id    VARCHAR(64)  NOT NULL,
            anime_name  VARCHAR(64)  NOT NULL,
            video_id    VARCHAR(64)  NOT NULL,
            name        VARCHAR(255) NULL,
            watched_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_user_anime (user_id, anime_id),
            KEY idx_watched (watched_at),
            KEY idx_video (video_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    favorite_anime_sql = """
        CREATE TABLE IF NOT EXISTS favorite_anime (
            id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            user_id     VARCHAR(64) NOT NULL,
            anime_id    VARCHAR(64) NOT NULL,
            created_at  DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_user_anime (user_id, anime_id),
            KEY idx_anime (anime_id),
            KEY idx_user_created (user_id, created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    sql_watch_progress = """
        CREATE TABLE IF NOT EXISTS watch_progress (
            id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            user_id      VARCHAR(64) NOT NULL,
            video_id     VARCHAR(64) NOT NULL,
            anime_id     VARCHAR(64) NULL,
            current_time_sec DOUBLE NOT NULL DEFAULT 0,
            duration_sec DOUBLE NULL,
            completed    TINYINT(1) NOT NULL DEFAULT 0,
            created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                         ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_user_video (user_id, video_id),
            KEY idx_user_updated (user_id, updated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cur.execute(sql2)
        cur.execute(sql_comments)
        cur.execute(watchsql)
        cur.execute(favorite_anime_sql)
        cur.execute(sql_watch_progress)
        cur.close()
    finally:
        conn.close()

def save_progress(user_id, video_id, anime_id, current, duration):
    current = max(0.0, float(current or 0))
    duration = float(duration) if duration else None
    # 95%+ үзсэн бол дууссан гэж үзнэ, дараагийн удаа эхнээс нь эхэлнэ
    completed = 1 if duration and current >= duration * 0.95 else 0

    sql = """
        INSERT INTO watch_progress
            (user_id, video_id, anime_id, current_time_sec, duration_sec, completed)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            current_time_sec = VALUES(current_time_sec),
            duration_sec     = COALESCE(VALUES(duration_sec), duration_sec),
            completed        = VALUES(completed),
            anime_id         = COALESCE(VALUES(anime_id), anime_id)
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, (str(user_id), str(video_id),
                          str(anime_id) if anime_id else None,
                          current, duration, completed))
        cur.close()
    finally:
        conn.close()


def get_progress(user_id, video_id):
    """Үргэлжлүүлэх секунд. Дууссан эсвэл байхгүй бол 0."""
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""SELECT current_time_sec, completed FROM watch_progress
                       WHERE user_id=%s AND video_id=%s""",
                    (str(user_id), str(video_id)))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    if not row or row["completed"]:
        return 0.0
    return float(row["current_time_sec"])
def get_comments(video_id: str, limit: int = 20, offset: int = 0) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    sql = """
        SELECT id, user_id, comment, created_at
        FROM comments
        WHERE video_id = %s AND is_deleted = 0
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s
    """
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, (str(video_id), limit, offset))
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    for r in rows:
        r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
    return rows


def count_comments(video_id: str) -> int:
    sql = "SELECT COUNT(*) FROM comments WHERE video_id = %s AND is_deleted = 0"
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, (str(video_id),))
        total = cur.fetchone()[0]
        cur.close()
        return total
    finally:
        conn.close()
def check_invoice_paylink(inv_id='inv_mw7mxyy2404052'):
    import requests

    url = paylink_url+ "v1/external/process"

    payload = { "invid": inv_id }
    headers = {
        "content-type": "application/json",
        "pc": "cu0904",
        "X-SIGNATURE": os.getenv("paylink_token" , False),
        "X-USERNAME": os.getenv("paylink_username" , 'zapataast@gmail.com')
    }

    response = requests.post(url, json=payload, headers=headers,timeout=3)

    return response.json()
_RATING_COLS = {"episode": "episode_score", "translation": "translation_score"}


def set_rating(user_id: str, video_id: str, kind: str, score: int):
    col = _RATING_COLS.get(kind)          # whitelist: SQL injection-ээс хамгаална
    if not col:
        raise ValueError("Буруу төрөл")
    score = int(score)
    if not 1 <= score <= 5:
        raise ValueError("Оноо 1-5 байх ёстой")

    sql = f"""
        INSERT INTO video_ratings (user_id, video_id, {col})
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE {col} = VALUES({col})
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, (str(user_id), str(video_id), score))
        cur.close()
    finally:
        conn.close()


def get_ratings(video_id: str, user_id: str | None = None) -> dict:
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT AVG(episode_score) AS ep_avg, COUNT(episode_score) AS ep_cnt,
                   AVG(translation_score) AS tr_avg, COUNT(translation_score) AS tr_cnt
            FROM video_ratings WHERE video_id = %s
        """, (str(video_id),))
        s = cur.fetchone()

        mine = {"episode": None, "translation": None}
        if user_id:
            cur.execute("""
                SELECT episode_score, translation_score FROM video_ratings
                WHERE video_id = %s AND user_id = %s
            """, (str(video_id), str(user_id)))
            m = cur.fetchone()
            if m:
                mine = {"episode": m["episode_score"], "translation": m["translation_score"]}
        cur.close()
    finally:
        conn.close()

    return {
        "episode":     {"avg": round(float(s["ep_avg"] or 0), 1), "count": s["ep_cnt"], "mine": mine["episode"]},
        "translation": {"avg": round(float(s["tr_avg"] or 0), 1), "count": s["tr_cnt"], "mine": mine["translation"]},
    }
def create_invoice_paylink(amount=0, msg='' , merchant_ref='Nirgee'):
    pc ="cu0900"
    url = paylink_url + "v1/external/process"
    X_SIGNATURE = os.getenv("paylink_token" , False)
    X_username = os.getenv("paylink_username" , 'zapataast@gmail.com')
    payload = {
        "amount_total": amount,
        "count_total": 1,
        "amount": amount,
        "txndesc": msg,
        "merchant_ref": merchant_ref,
        "fee_percent": 0,
        "fee_amount": 0,
        "base_amount": amount
    }
    headers = {
        "content-type": "application/json",
        "pc": pc,
        "X-SIGNATURE": X_SIGNATURE,
        "X-USERNAME": X_username
    }

    response = requests.post(url, json=payload, headers=headers,timeout=3)

    print(response.json())

    return response.json()

def verify_msg_log(uid,verify_url=None):
    import requests

    url = verify_url+ f"/sessions/{uid}"

    response = requests.get(url,timeout=5)

    print(response.json())
    if response.status_code in (200, 201):
        return response.json()
    else:
        return {}
def verify_create_session(phone="85963616",code = None , verify_url=None,api_key_verify=None,ref = None ):

    import secrets
    import string
    if code is None:
        code = ''.join(secrets.choice(string.digits) for _ in range(4))
    payload = {
        "phone": phone,
        "text": code
    }
    if ref:
        payload['responseSms'] = 'Verification received: loginname: ' + ref
    headers = {
        "content-type": "application/json",
        "Authorization": f"Bearer {api_key_verify}"
    }
    url = verify_url+ "/sessions"
    r = requests.post(url, json=payload, headers=headers,timeout=10)
    return r.json();


def send_anime_info_to_mongodb(metadata,anime_collection):
    try:
        now = datetime.now(timezone.utc)

        anime_data = {
            "name": metadata.get("name", "").strip(),
            "description": metadata.get("description", "").strip(),

            "active": metadata.get("active", True),

            "anime_type": metadata.get("anime_type", "tv"),

            "episodes": metadata.get("episodes"),

            "status": metadata.get(
                "status",
                "finished"
            ),

            "aired_from": metadata.get("aired_from"),
            "aired_to": metadata.get("aired_to"),

            "premiered": metadata.get(
                "premiered",
                ""
            ).strip(),

            "broadcast": metadata.get(
                "broadcast",
                ""
            ).strip(),

            "producers": metadata.get(
                "producers",
                ""
            ).strip(),

            "licensors": metadata.get(
                "licensors",
                ""
            ).strip(),

            "studios": metadata.get(
                "studios",
                ""
            ).strip(),

            "image_url": metadata.get(
                "image_url",
                ""
            ).strip(),

            "created_at": now,
            "updated_at": now,
        }

        result = anime_collection.insert_one(
            anime_data
        )

        return {
            "success": True,
            "anime_id": str(
                result.inserted_id
            ),
        }

    except Exception as e:
        print(
            "❌ MongoDB anime insert error:",
            e
        )

def send_video_info_to_mongodb(metadata,videos_collection):
    try:
        video_data = {
            **metadata,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        result = videos_collection.insert_one(video_data)

        return {
            "success": True,
            "video_id": str(result.inserted_id),
        }

    except Exception as e:
        print("❌ MongoDB insert error:", e)

        return {
            "success": False,
            "error": str(e),
        }


def get_video_duration(file_path):
    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        file_path,
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )

    data = json.loads(result.stdout)

    duration = data.get(
        "format",
        {}
    ).get(
        "duration"
    )

    if duration is None:
        return None

    return round(float(duration), 2)
def send_video_info_to_django(data):
    print("🐍 File: render_server/utils.py | Line: 6 | undefined ~ data",data)
    django_url = os.environ["DJANGO_API_URL"].rstrip("/")
    print("🐍 File: render_server/utils.py | Line: 8 | send_video_info_to_django ~ django_url",django_url)
    api_key = os.environ["DJANGO_API_KEY"]

    response = requests.post(
        f"{django_url}/api/videos/create/",
        json=data,
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        },
        timeout=30,
    )

    response.raise_for_status()

    return response.json()



def add_home_comment(user_id, nickname, content, avatar_url) -> int:
    sql = """
        INSERT INTO home_comments (user_id, nickname, content, avatar_url, created_at)
        VALUES (%s, %s, %s, %s, %s)
    """
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)   # MySQL DATETIME = UTC
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, (
            str(user_id) if user_id else None,
            (nickname or "Anonymous")[:100],
            content,
            avatar_url,
            now_utc,
        ))
        new_id = cur.lastrowid
        cur.close()
        return new_id
    finally:
        conn.close()


def get_home_comments(limit: int = 50) -> list[dict]:
    sql = """
        SELECT id, user_id, nickname, content, avatar_url, active, created_at
        FROM home_comments
        WHERE active = 1
        ORDER BY created_at DESC, id DESC
        LIMIT %s
    """
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, (int(limit),))
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    for r in rows:
        r["id"] = str(r["id"])
    return rows    


def upsert_watch_history(user_id, anime_id,anime_name, video_id, name):
    sql = """
        INSERT INTO watch_history (user_id, anime_id,anime_name, video_id, name, watched_at)
        VALUES (%s, %s, %s, %s, %s ,%s)
        ON DUPLICATE KEY UPDATE
            video_id   = VALUES(video_id),
            name       = VALUES(name),
            watched_at = VALUES(watched_at)
    """
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, (str(user_id), str(anime_id),str(anime_name), str(video_id),
                          (name or "")[:255], now_utc))
        cur.close()
    finally:
        conn.close()


def get_user_history(user_id, limit=50):
    """Нэг хэрэглэгчийн түүх (өмнө Mongo-оос уншдаг байсан газар солино)."""
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT anime_id,anime_name, video_id, name, watched_at
            FROM watch_history WHERE user_id = %s
            ORDER BY watched_at DESC LIMIT %s
        """, (str(user_id), int(limit)))
        rows = cur.fetchall()
        cur.close()
        return rows
    finally:
        conn.close()


def list_all_watches(page=1, per_page=50, user_id=None, q=None):
    """Админ: бүх хэрэглэгчийн үзэлт."""
    page = max(1, int(page))
    per_page = max(1, min(int(per_page), 200))

    where, params = [], []
    if user_id:
        where.append("user_id = %s")
        params.append(str(user_id))
    if q:
        where.append("name LIKE %s")
        params.append(f"%{q}%")
    w = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(f"SELECT COUNT(*) AS c FROM watch_history {w}", params)
        total = cur.fetchone()["c"]
        cur.execute(f"""
            SELECT user_id, anime_id,anime_name, video_id, name, watched_at, created_at
            FROM watch_history {w}
            ORDER BY watched_at DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, (page - 1) * per_page])
        rows = cur.fetchall()
        cur.close()
        return total, rows
    finally:
        conn.close()

def is_favorite(user_id, anime_id) -> bool:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM favorite_anime WHERE user_id=%s AND anime_id=%s LIMIT 1",
                    (str(user_id), str(anime_id)))
        found = cur.fetchone() is not None
        cur.close()
        return found
    finally:
        conn.close()


def toggle_favorite(user_id, anime_id) -> bool:
    """Нэмсэн бол True, хассан бол False буцаана."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM favorite_anime WHERE user_id=%s AND anime_id=%s",
                    (str(user_id), str(anime_id)))
        if cur.rowcount:                 # байсан тул хасагдлаа
            cur.close()
            return False
        cur.execute("INSERT IGNORE INTO favorite_anime (user_id, anime_id) VALUES (%s, %s)",
                    (str(user_id), str(anime_id)))
        cur.close()
        return True
    finally:
        conn.close()


def get_user_favorites(user_id, limit=100) -> list[str]:
    """Хэрэглэгчийн дуртай anime_id-ууд (шинэ нь эхэнд)."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""SELECT anime_id FROM favorite_anime
                       WHERE user_id=%s ORDER BY created_at DESC LIMIT %s""",
                    (str(user_id), int(limit)))
        ids = [r[0] for r in cur.fetchall()]
        cur.close()
        return ids
    finally:
        conn.close()        

def get_continue_watching(user_id, limit=10):
    """Дуусаагүй, сүүлд үзсэн ангиуд (anime тус бүрт нэг)."""
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT video_id, anime_id, current_time_sec, duration_sec, updated_at
            FROM watch_progress
            WHERE user_id = %s AND completed = 0 AND current_time_sec > 5
            ORDER BY updated_at DESC
            LIMIT %s
        """, (str(user_id), int(limit) * 3))
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    seen, result = set(), []
    for r in rows:
        key = r["anime_id"] or r["video_id"]
        if key in seen:
            continue
        seen.add(key)
        result.append(r)
        if len(result) >= limit:
            break
    return result