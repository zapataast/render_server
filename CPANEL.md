# cPanel дээр байршуулах

cPanel-ийн **Setup Python App** (Phusion Passenger) ашиглана. Entry point нь `passenger_wsgi.py`.

## 1. Файлуудыг байршуулах

Git (cPanel → Git Version Control) эсвэл File Manager-ээр репог серверт хуул. Жишээ нь `~/anime_app`.
Branch нь `cpanel`. `.env`, `*.session` файлуудыг git-ээр бүү хуул.

## 2. Python App үүсгэх

cPanel → **Setup Python App** → **Create Application**:

| Талбар | Утга |
|---|---|
| Python version | 3.11 эсвэл түүнээс дээш |
| Application root | `anime_app` |
| Application URL | домэйн (эсвэл дэд домэйн) |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |

## 3. Сангуудыг суулгах

App хуудасны дээд хэсэгт байгаа `source .../bin/activate && cd ...` командыг хуулж Terminal-д ажиллуул:

```bash
source /home/USER/virtualenv/anime_app/3.11/bin/activate && cd /home/USER/anime_app
pip install -r requirements.txt
```

Эсвэл App хуудсан дээрх **Run Pip Install** товчийг дар.

## 4. Environment variables

App хуудсан дээрх **Environment variables** хэсэгт нэм. Эсвэл `~/anime_app/.env` файлд бич (cPanel дээр тохируулсан утга давуу эрхтэй).

```text
FLASK_SECRET_KEY=урт_санамсаргүй_утга
MONGO_URI=mongodb+srv://...
MONGO_DB_NAME=anime_db
CLOUDINARY_URL=cloudinary://...
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_CHANNEL_ID=-100...
TELEGRAM_SESSION=
ADMIN_PHONES=85963616
MAX_UPLOAD_MB=2048

# cPanel-ийн MySQL (cPanel → MySQL Databases дээр үүсгэнэ)
mysqlhost=localhost
mysqlport=3306
mysqldb=USER_dbname
dbuser=USER_dbuser
dbuser_pass=

verify_url=
api_key_verify=
paylink_url=

# Заавал биш
TMPDIR=/home/USER/anime_app/tmp
FFMPEG_BIN=/home/USER/bin/ffmpeg
FFPROBE_BIN=/home/USER/bin/ffprobe
```

Env өөрчилсний дараа **Restart** дар.

## 5. Шалгах

`https://ДОМЭЙН/health` → `{"status": "ok"}` гарах ёстой.
Алдаа гарвал `~/anime_app/stderr.log`-г шалга (зарим host дээр `~/logs/` дотор байдаг).

Код шинэчилсний дараа **Restart** дар, эсвэл:

```bash
mkdir -p ~/anime_app/tmp && touch ~/anime_app/tmp/restart.txt
```

## Анхаарах зүйлс

- **Telegram session-ийг хоёр газар зэрэг бүү ажиллуул.** Нэг `TELEGRAM_SESSION`-ийг Render болон cPanel дээр зэрэг ашиглавал (өөр өөр IP) Telegram session-ийг хүчингүй болгож болзошгүй. cPanel руу шилжмэгц Render-ийн service-ийг зогсоо.
- **Passenger Python-д процесс бүр нэг удаад нэг хүсэлт** боловсруулдаг. Зэрэг хүсэлт олон бол Passenger шинэ процесс асаана, процесс бүр өөрийн Telegram холболтыг үүсгэнэ. Нэг серверээс (нэг IP) холбогддог тул ихэвчлэн асуудалгүй. Гэхдээ host-ийн процессын хязгаар (CloudLinux-ийн EP/NPROC) бага бол video stream удаан эсвэл 503 болж болно. Тийм тохиолдолд host-оос хязгаарыг нэмүүл эсвэл VPS ашигла.
- **Rate/strike хамгаалалт процесс бүрт тусдаа** тоолдог. Олон процесс асах үед хязгаар бага зэрэг сул болно (буруу 403 гаргахгүй).
- **ffmpeg/ffprobe** shared host дээр ихэвчлэн байдаггүй. Байхгүй бол upload ажиллана, гэхдээ видеоны `duration` болон screenshot хоосон үлдэнэ. Static build-ийг `~/bin/` руу хуулж, `FFMPEG_BIN` / `FFPROBE_BIN`-д замыг нь өг.
- **Том upload (2GB).** Apache/LiteSpeed-ийн хүсэлтийн хэмжээ болон timeout-ийн хязгаар host-ын тохиргооноос хамаарна. Том файл upload хийхэд алдаа гарвал host-оос эдгээр хязгаарыг нэмүүл.
- Temp файлууд `~/anime_app/tmp` руу бичигдэнэ (`passenger_wsgi.py` тохируулна). Диск квотоо анхаар.
