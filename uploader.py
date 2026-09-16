import os
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession
import asyncio
import threading
import time

TELEGRAM_CACHE_TTL = 10 * 60
TELEGRAM_CHUNK_SIZE = 512 * 1024

_telegram_channel_cache = {}
_telegram_message_cache = {}
_telegram_cache_lock = threading.Lock()
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
def _cache_get(cache, key):
    now = time.time()

    with _telegram_cache_lock:
        item = cache.get(key)

        if not item:
            return None

        expires_at, value = item

        if expires_at <= now:
            cache.pop(key, None)
            return None

        return value


def _cache_set(cache, key, value):
    with _telegram_cache_lock:
        cache[key] = (
            time.time() + TELEGRAM_CACHE_TTL,
            value,
        )
async def get_cached_telegram_channel(client, channel_id):
    cache_key = int(channel_id)

    channel = _cache_get(
        _telegram_channel_cache,
        cache_key,
    )

    if channel is not None:
        return channel

    channel = await resolve_channel(
        client,
        channel_id,
    )

    if channel is not None:
        _cache_set(
            _telegram_channel_cache,
            cache_key,
            channel,
        )

    return channel

async def get_cached_telegram_message(
    client,
    channel,
    channel_id,
    message_id,
):
    cache_key = (
        int(channel_id),
        int(message_id),
    )

    message = _cache_get(
        _telegram_message_cache,
        cache_key,
    )

    if message is not None:
        return message

    message = await get_telegram_message(
        client,
        channel,
        channel_id,
        message_id,
    )

    if message is not None:
        _cache_set(
            _telegram_message_cache,
            cache_key,
            message,
        )

    return message

def _cache_delete(cache, key):
    with _telegram_cache_lock:
        cache.pop(key, None)
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

def telegram_range_stream(channel_id, message_id, start, end):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    client = build_telegram_client()
    iterator = None

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
        # CHANNEL
        # CACHE HIT үед Telegram request явахгүй.
        # =====================================================
        channel = loop.run_until_complete(
            get_cached_telegram_channel(
                client,
                channel_id,
            )
        )

        if channel is None:
            raise RuntimeError(
                f"Telegram channel олдсонгүй: {channel_id}"
            )

        # =====================================================
        # MESSAGE
        # CACHE HIT үед get_messages дахиж дуудагдахгүй.
        # =====================================================
        message = loop.run_until_complete(
            get_cached_telegram_message(
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
        # RANGE
        # =====================================================
        start = int(start)
        end = int(end)

        remaining = end - start + 1

        if remaining <= 0:
            return

        # =====================================================
        # TELEGRAM OFFSET ALIGN
        # =====================================================
        aligned_start = (
            start // TELEGRAM_CHUNK_SIZE
        ) * TELEGRAM_CHUNK_SIZE

        skip_bytes = start - aligned_start

        # =====================================================
        # DOWNLOAD
        # =====================================================
        iterator = client.iter_download(
            message.media,
            offset=aligned_start,
            request_size=TELEGRAM_CHUNK_SIZE,
            chunk_size=TELEGRAM_CHUNK_SIZE,
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

            chunk = bytes(chunk)

            # =================================================
            # ALIGN-аас үүссэн эхний илүү хэсгийг хаяна.
            # =================================================
            if skip_bytes > 0:
                if skip_bytes >= len(chunk):
                    skip_bytes -= len(chunk)
                    continue

                chunk = chunk[skip_bytes:]
                skip_bytes = 0

            # =================================================
            # Browser-ийн хүссэн range-ээс хэтрүүлэхгүй.
            # =================================================
            if len(chunk) > remaining:
                chunk = chunk[:remaining]

            if not chunk:
                break

            remaining -= len(chunk)

            yield chunk

    except GeneratorExit:
        return

    except Exception:
        # Media reference асуудал гарсан байж болох учраас
        # тухайн message cache-ийг invalidate хийнэ.
        _cache_delete(
            _telegram_message_cache,
            (
                int(channel_id),
                int(message_id),
            ),
        )

        raise

    finally:
        # =====================================================
        # ITERATOR CLOSE
        # =====================================================
        if iterator is not None:
            try:
                result = iterator.close()

                if asyncio.iscoroutine(result):
                    loop.run_until_complete(result)

            except Exception:
                pass

        # =====================================================
        # CLIENT DISCONNECT
        # =====================================================
        try:
            if client.is_connected():
                result = client.disconnect()

                if asyncio.iscoroutine(result):
                    loop.run_until_complete(result)

        except Exception:
            pass

        # =====================================================
        # LOOP CLOSE
        # =====================================================
        try:
            loop.close()
        except Exception:
            pass


async def upload_file_to_telegram(
    file_path,
    caption="",
):
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {file_path}"
        )

    channel_id = int(
        _required_env(
            "TELEGRAM_CHANNEL_ID"
        )
    )

    client = _build_client()

    await client.connect()

    try:

        if not await client.is_user_authorized():

            raise RuntimeError(
                "Telegram session is not authorized. "
                "Set TELEGRAM_SESSION on Render."
            )

        message = await client.send_file(
            channel_id,
            str(path),
            caption=caption,
            supports_streaming=False,
            force_document=True,
        )

        return {
            "success": True,
            "channel_id": channel_id,
            "message_id": message.id,
            "file_name": (
                message.file.name
                if message.file
                else path.name
            ),
            "file_size": (
                message.file.size
                if message.file
                else path.stat().st_size
            ),
        }

    finally:

        await client.disconnect()
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
