import os
import requests
import json
import subprocess
from datetime import datetime, timezone
from bson import ObjectId
from pymongo import MongoClient



from dotenv import load_dotenv
from pymongo import MongoClient


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