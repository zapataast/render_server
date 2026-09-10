import os
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession


def _required_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required.")
    return value


def _build_client():
    api_id = int(_required_env("TELEGRAM_API_ID"))
    api_hash = _required_env("TELEGRAM_API_HASH")
    session_string = os.getenv("TELEGRAM_SESSION", "").strip()

    if session_string:
        session = StringSession(session_string)
    else:
        # Local development fallback only. On Render, TELEGRAM_SESSION is recommended.
        session = os.getenv("TELEGRAM_SESSION_FILE", "telegram_session")

    return TelegramClient(session, api_id, api_hash)


async def upload_video_to_telegram(file_path, caption=""):
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    channel_id = int(_required_env("TELEGRAM_CHANNEL_ID"))
    client = _build_client()

    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not authorized. Set TELEGRAM_SESSION on Render."
            )

        message = await client.send_file(
            channel_id,
            str(path),
            caption=caption,
            supports_streaming=True,
            force_document=False,
        )

        return {
            "success": True,
            "channel_id": channel_id,
            "message_id": message.id,
            "file_name": message.file.name if message.file else path.name,
            "file_size": message.file.size if message.file else path.stat().st_size,
        }
    finally:
        await client.disconnect()
