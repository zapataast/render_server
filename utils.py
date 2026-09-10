import os
import requests
import json
import subprocess
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