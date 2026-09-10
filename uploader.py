import os
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession
import asyncio

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

def build_telegram_client():
    api_id = int(
        os.environ["TELEGRAM_API_ID"]
    )

    api_hash = os.environ[
        "TELEGRAM_API_HASH"
    ]

    session_string = (
        os.environ["TELEGRAM_SESSION"]
        .strip()
    )

    return TelegramClient(
        StringSession(
            session_string
        ),
        api_id,
        api_hash,
    )
CHANNEL_CACHE = {}

async def resolve_channel(client, channel_id):
    if channel_id in CHANNEL_CACHE:
        return CHANNEL_CACHE[channel_id]

    dialogs = await client.get_dialogs()

    for dialog in dialogs:
        if dialog.id == int(channel_id):
            CHANNEL_CACHE[channel_id] = dialog.entity
            return dialog.entity

    raise RuntimeError(
        f"Telegram channel олдсонгүй: {channel_id}"
    )

MESSAGE_CACHE = {}


async def get_telegram_message(
    client,
    channel,
    channel_id,
    message_id,
):
    key = (
        int(channel_id),
        int(message_id),
    )

    if key in MESSAGE_CACHE:
        return MESSAGE_CACHE[key]

    message = await client.get_messages(
        channel,
        ids=int(message_id),
    )

    if not message or not message.media:
        raise RuntimeError(
            "Telegram video олдсонгүй."
        )

    MESSAGE_CACHE[key] = message

    return message

def telegram_range_stream(
    channel_id,
    message_id,
    start,
    end,
):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    client = build_telegram_client()

    try:
        # =====================================================
        # CONNECT
        # =====================================================
        loop.run_until_complete(
            client.connect()
        )

        authorized = loop.run_until_complete(
            client.is_user_authorized()
        )

        if not authorized:
            raise RuntimeError(
                "Telegram session authorized биш байна."
            )

        # =====================================================
        # RESOLVE CHANNEL
        # =====================================================
        channel = loop.run_until_complete(
            resolve_channel(
                client,
                channel_id,
            )
        )
        if channel is None:
            raise RuntimeError(
                f"Telegram channel олдсонгүй: {channel_id}"
            )

        # =====================================================
        # GET MESSAGE
        # =====================================================
        message = loop.run_until_complete(
            get_telegram_message(
                client,
                channel,
                channel_id,
                message_id,
            )
        )

        if not message:
            raise RuntimeError(
                f"Telegram message олдсонгүй: {message_id}"
            )

        if not message.media:
            raise RuntimeError(
                "Telegram message дээр media байхгүй."
            )

        # =====================================================
        # BYTE RANGE
        # =====================================================
        remaining = (
            int(end)
            - int(start)
            + 1
        )

        iterator = client.iter_download(
            message.media,

            offset=int(start),

            request_size=512 * 1024,
            chunk_size=512 * 1024,
        )

        async_iterator = iterator.__aiter__()

        while remaining > 0:

            try:
                chunk = loop.run_until_complete(
                    async_iterator.__anext__()
                )

            except StopAsyncIteration:
                break

            if not chunk:
                break

            # ===============================================
            # Werkzeug-д заавал bytes өгнө
            # ===============================================
            chunk = bytes(chunk)

            if len(chunk) > remaining:
                chunk = chunk[:remaining]

            remaining -= len(chunk)

            yield chunk

    except GeneratorExit:
        # Browser seek хийх, video request cancel хийх үед
        # хэвийн тохиолдол.
        return

    finally:
        # =====================================================
        # IMPORTANT:
        #
        # client.disconnect()-г run_until_complete хийхгүй.
        # Telethon disconnect() өөрөө cleanup хийдэг.
        # =====================================================
        try:
            if client.is_connected():
                client.disconnect()

        except Exception:
            pass

        try:
            loop.close()
        except Exception:
            pass

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
