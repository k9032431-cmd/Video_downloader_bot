import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


MB = 1024 * 1024

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Свой сервер telegram-bot-api (https://github.com/tdlib/telegram-bot-api).
# С ним лимит на отправку файла — 2000 МБ вместо 50 МБ.
BOT_API_URL = os.environ.get("BOT_API_URL") or None
# Сервер запущен с --local и видит ту же папку загрузок: файлы отдаём по пути,
# без повторной загрузки через HTTP.
BOT_API_LOCAL_FILES = _bool("BOT_API_LOCAL_FILES", default=bool(BOT_API_URL))

COOKIES_FILE = os.environ.get("COOKIES_FILE") or None
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "3"))
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "downloads")).resolve()

# Лимит Telegram на один файл. Всё, что больше, режется на части.
MAX_UPLOAD_BYTES = (2000 if BOT_API_URL else 50) * MB
# Фото больше 10 МБ через sendPhoto не принимаются — шлём документом.
MAX_PHOTO_BYTES = 10 * MB
# Защита диска: больше этого не скачиваем вообще.
MAX_DOWNLOAD_BYTES = int(os.environ.get("MAX_DOWNLOAD_MB", "20000")) * MB
# Максимальное качество видео.
MAX_HEIGHT = int(os.environ.get("MAX_HEIGHT", "1080"))
# Сколько ждать ответа Telegram на отправку большого файла (секунды).
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "3600"))
