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
    "user": os.getenv("dbuser"),
    "password": os.getenv("dbuser_pass"),
    "database": os.getenv("mysqldb"),
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
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cur.execute(sql2)
  
        cur.close()
    finally:
        conn.close()
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