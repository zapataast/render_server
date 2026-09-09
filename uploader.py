import os
from telethon import TelegramClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
load_dotenv()

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID"))
print("🐍 File: render_server/uploader.py | Line: 10 | undefined ~ CHANNEL_ID",CHANNEL_ID)

client = TelegramClient(
    "telegram_session",
    API_ID,
    API_HASH,
)


async def upload_video_to_telegram(
    file_path,
    caption="",
):
    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"File not found: {file_path}"
        )

    await client.start()

    message = await client.send_file(
        CHANNEL_ID,
        file_path,
        caption=caption,
        supports_streaming=True,
    )

    file_name = None
    file_size = None

    if message.file:
        file_name = message.file.name
        file_size = message.file.size

    return {
        "success": True,
        "channel_id": message.chat_id,
        "message_id": message.id,
        "file_name": file_name,
        "file_size": file_size,
    }
import asyncio
result = asyncio.run(
    upload_video_to_telegram(
        r"F:\render_server\Working.mkv",
        caption="Working_ep1",
    )
)


print(result)