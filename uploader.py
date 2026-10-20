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

async def _upload(file_path, caption, supports_streaming, force_document):
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    channel_id = int(_required_env("TELEGRAM_CHANNEL_ID"))

    message = await _client.send_file(
        channel_id,
        str(path),
        caption=caption,
        supports_streaming=supports_streaming,
        force_document=force_document,
    )

    return {
        "success": True,
        "channel_id": channel_id,
        "message_id": message.id,
        "file_name": message.file.name if message.file else path.name,
        "file_size": message.file.size if message.file else path.stat().st_size,
    }

def upload_video_to_telegram_sync(file_path, caption="", is_video=True):
    return run_tg(
        _upload(file_path, caption, is_video, not is_video),
        timeout=3600,
    )


_loop = None
_client = None
_init_error = None
_ready = threading.Event()
_start_lock = threading.Lock()
_started = False


def _loop_worker():
    global _loop, _client, _init_error

    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    try:
        _client = _build_client()  # TELEGRAM_SESSION-тэй хувилбар

        async def _init():
            await _client.connect()
            if not await _client.is_user_authorized():
                raise RuntimeError("Telegram session authorized биш байна.")

        _loop.run_until_complete(_init())
    except Exception as e:
        _init_error = e
        _ready.set()
        return

    _ready.set()
    _loop.run_forever()


def ensure_started():
    global _started

    with _start_lock:
        if not _started:
            threading.Thread(
                target=_loop_worker,
                name="telegram-loop",
                daemon=True,
            ).start()
            _started = True

    _ready.wait(timeout=30)

    if _init_error:
        raise _init_error
    if _client is None:
        raise RuntimeError("Telegram client эхлээгүй байна.")


def run_tg(coro, timeout=60):
    """Sync кодоос background loop дээр coroutine ажиллуулна."""
    ensure_started()
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(timeout)


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


def _cache_delete(cache, key):
    with _telegram_cache_lock:
        cache.pop(key, None)
async def resolve_channel(client, channel_id):
    target = int(channel_id)
    async for dialog in client.iter_dialogs():
        if dialog.id == target:
            return dialog.entity
    raise RuntimeError(f"Telegram channel олдсонгүй: {channel_id}")


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
async def get_cached_telegram_media(client, channel, channel_id, message_id):
    key = (int(channel_id), int(message_id))

    media = _cache_get(_telegram_message_cache, key)
    if media is not None:
        return media

    message = await client.get_messages(channel, ids=int(message_id))

    if not message or not message.media:
        raise RuntimeError("Telegram video олдсонгүй.")

    _cache_set(_telegram_message_cache, key, message.media)
    return message.media
def telegram_range_stream(channel_id, message_id, start, end):
    ensure_started()
    client = _client

    start = int(start)
    end = int(end)
    remaining = end - start + 1

    if remaining <= 0:
        return

    iterator = None

    try:
        channel = run_tg(get_cached_telegram_channel(client, channel_id))
        media = run_tg(
            get_cached_telegram_media(client, channel, channel_id, message_id)
        )

        aligned_start = (start // TELEGRAM_CHUNK_SIZE) * TELEGRAM_CHUNK_SIZE
        skip_bytes = start - aligned_start

        async def _open():
            it = client.iter_download(
                media,
                offset=aligned_start,
                request_size=TELEGRAM_CHUNK_SIZE,
            )
            return it, it.__aiter__()

        iterator, ait = run_tg(_open())

        async def _next():
            try:
                return await ait.__anext__()
            except StopAsyncIteration:
                return None

        started_at = time.time()
        last_log_at = started_at
        sent_bytes = 0

        while remaining > 0:
            chunk = run_tg(_next(), timeout=30)

            if not chunk:
                break

            chunk = bytes(chunk)

            if skip_bytes > 0:
                if skip_bytes >= len(chunk):
                    skip_bytes -= len(chunk)
                    continue
                chunk = chunk[skip_bytes:]
                skip_bytes = 0

            if len(chunk) > remaining:
                chunk = chunk[:remaining]

            if not chunk:
                break

            remaining -= len(chunk)
            sent_bytes += len(chunk)

            now = time.time()
            if now - last_log_at >= 2:
                elapsed = now - started_at
                print(
                    f"[TELEGRAM STREAM] sent={sent_bytes/1024/1024:.2f} MB | "
                    f"speed={sent_bytes/elapsed/1024:.2f} KB/s"
                )
                last_log_at = now

            yield chunk

    except GeneratorExit:
        return

    except Exception:
        # file reference хуучирсан байж болно
        _cache_delete(
            _telegram_message_cache,
            (int(channel_id), int(message_id)),
        )
        raise

    finally:
        # client-ийг disconnect ХИЙХГҮЙ, зөвхөн iterator-ийг хаана
        if iterator is not None:
            async def _close():
                r = iterator.close()
                if asyncio.iscoroutine(r):
                    await r
            try:
                run_tg(_close(), timeout=10)
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

    client = _client()

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



async def upload_video_to_telegram(file_path, caption="", is_video=True):
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    channel_id = int(_required_env("TELEGRAM_CHANNEL_ID"))
    client = _client

    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session is not authorized.")

        message = await client.send_file(
            channel_id,
            str(path),
            caption=caption,
            supports_streaming=is_video,
            force_document=not is_video,
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