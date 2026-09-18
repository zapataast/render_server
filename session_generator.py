import os
import asyncio

import qrcode

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError


load_dotenv()


API_ID = int(
    os.getenv("TELEGRAM_API_ID")
)

API_HASH = os.getenv(
    "TELEGRAM_API_HASH"
)

SESSION_NAME = 'for_render'


async def main():

    client = TelegramClient(
        SESSION_NAME,
        API_ID,
        API_HASH,
    )

    await client.connect()

    try:

        if await client.is_user_authorized():

            me = await client.get_me()

            print("✅ Session already authorized")
            print("ID:", me.id)
            print("Username:", me.username)
            print(
                "Session:",
                f"{SESSION_NAME}.session",
            )

            return

        print()
        print("QR login үүсгэж байна...")
        print()

        qr_login = await client.qr_login()

        qr = qrcode.QRCode(
            version=None,
            box_size=10,
            border=4,
        )

        qr.add_data(
            qr_login.url
        )

        qr.make(
            fit=True
        )

        image = qr.make_image(
            fill_color="black",
            back_color="white",
        )

        qr_file = "telegram_login_qr.png"

        image.save(
            qr_file
        )

        print(
            f"✅ QR зураг үүслээ: {qr_file}"
        )

        print()
        print(
            "Telegram app дээр QR-г scan хийнэ."
        )

        print()
        print(
            "Settings → Devices → Link Desktop Device"
        )

        print()
        print(
            "Scan хийхийг хүлээж байна..."
        )

        try:

            await qr_login.wait()

        except SessionPasswordNeededError:

            print()
            print(
                "🔐 2FA password шаардлагатай."
            )

            password = input(
                "Telegram 2FA password: "
            )

            await client.sign_in(
                password=password
            )

        me = await client.get_me()

        print()
        print("=" * 60)
        print("✅ LOGIN SUCCESS")
        print("=" * 60)

        print(
            "ID:",
            me.id,
        )

        print(
            "Username:",
            me.username,
        )

        print(
            "Phone:",
            me.phone,
        )

        print(
            "Session:",
            f"{SESSION_NAME}.session",
        )

    finally:

        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())